#!/usr/bin/env python3
"""Reproduce the pinned-SDCC size status for the render-order container."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.render_order_backend import (
    build_render_order_model,
    emit_render_order_backend,
)
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-render-order-target-size-probe-v1"
SINGLE_PAGE_BYTES = 0x4000
PINNED_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
)


class RenderOrderSizeError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    data = (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _area_map(text: str) -> dict[str, int]:
    return {
        match.group(1): int(match.group(2), 16)
        for match in re.finditer(
            r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+",
            text, re.MULTILINE)
    }


def _symbol(text: str, name: str) -> int:
    match = re.search(
        rf"^S\s+_{re.escape(name)}\s+Def([0-9A-Fa-f]+)$",
        text, re.MULTILINE)
    if match is None:
        raise RenderOrderSizeError(f"SDCC .rel lacks symbol {name}")
    return int(match.group(1), 16)


def _sizeof_value(text: str, name: str) -> int:
    match = re.search(
        rf"^_{re.escape(name)}:\s*\r?\n\s*\.dw\s+#0x([0-9A-Fa-f]+)$",
        text, re.MULTILINE)
    if match is None:
        raise RenderOrderSizeError(f"SDCC size probe lacks {name}")
    return int(match.group(1), 16)


def probe(project_root: Path | str) -> dict[str, object]:
    root = Path(project_root).resolve()
    model = build_render_order_model(root)
    artifacts = emit_render_order_backend(root)
    generated = root / "Source" / "C" / "generated"
    expected_files = {
        artifacts.header_name: artifacts.header.encode("utf-8"),
        artifacts.source_name: artifacts.source.encode("utf-8"),
        artifacts.manifest_name: artifacts.manifest.encode("utf-8"),
    }
    for name, expected in expected_files.items():
        path = generated / name
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise RenderOrderSizeError(
                f"missing generated render-order artifact {path}") from exc
        if actual != expected:
            raise RenderOrderSizeError(
                f"generated render-order artifact is stale: {path}")

    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="pyz80-render-order-size-") as temp:
        directory = Path(temp)
        for name in (artifacts.header_name, artifacts.source_name):
            (directory / name).write_bytes(expected_files[name])
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", artifacts.source_name]
        completed = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if completed.returncode != 0:
            raise RenderOrderSizeError(
                f"pinned SDCC failed ({completed.returncode}):\n"
                f"{completed.stdout}")
        rel_path = directory / artifacts.source_name.replace(".c", ".rel")
        try:
            rel_bytes = rel_path.read_bytes()
        except OSError as exc:
            raise RenderOrderSizeError(
                "pinned SDCC did not produce .rel") from exc
        rel_text = rel_bytes.decode("latin1")

        probe_name = "rtype_python_render_order_sizeof_probe.c"
        probe_source = (
            f'#include "{artifacts.header_name}"\n'
            "const uint16_t render_order_state_size = "
            "sizeof(rtype_python_render_order_state);\n"
        )
        (directory / probe_name).write_text(
            probe_source, encoding="utf-8", newline="\n")
        size_completed = subprocess.run(
            [str(sdcc), *PINNED_ARGUMENTS, "-S", probe_name],
            cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if size_completed.returncode != 0:
            raise RenderOrderSizeError(
                "pinned SDCC sizeof probe failed "
                f"({size_completed.returncode}):\n{size_completed.stdout}")
        size_asm = (directory / probe_name.replace(
            ".c", ".asm")).read_text(encoding="latin1")

    areas = _area_map(rel_text)
    code_bytes = areas.get("_CODE")
    data_bytes = areas.get("_DATA")
    if code_bytes is None or data_bytes is None:
        raise RenderOrderSizeError("SDCC .rel lacks _CODE/_DATA area")
    state_bytes = _sizeof_value(size_asm, "render_order_state_size")
    code_fits = code_bytes <= SINGLE_PAGE_BYTES
    state_exact = state_bytes == model.state_bytes
    data_empty = data_bytes == 0
    status = (
        "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED"
        if code_fits and state_exact and data_empty
        else "BLOCKED_RENDER_ORDER_SIZE_CERTIFICATE_FAILED")
    return {
        "format": FORMAT,
        "status": status,
        "input": {
            "semantic_sha256": model.semantic_sha256,
            "active_python_source_sha256": model.source_sha256,
            "source": {
                "path": "Source/C/generated/" + artifacts.source_name,
                "bytes": len(expected_files[artifacts.source_name]),
                "sha256": _sha256(expected_files[artifacts.source_name]),
            },
            "header": {
                "path": "Source/C/generated/" + artifacts.header_name,
                "bytes": len(expected_files[artifacts.header_name]),
                "sha256": _sha256(expected_files[artifacts.header_name]),
            },
            "manifest": {
                "path": "Source/C/generated/" + artifacts.manifest_name,
                "bytes": len(expected_files[artifacts.manifest_name]),
                "sha256": _sha256(expected_files[artifacts.manifest_name]),
            },
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "sha256": _sha256(sdcc.read_bytes()),
            "arguments": [*PINNED_ARGUMENTS, "-c", artifacts.source_name],
        },
        "source_derived_model": {
            "slot_count": model.slot_count,
            "reserved_sentinel_count": model.reserved_sentinel_count,
            "capacity": model.capacity,
            "checkpoint_count": len(model.checkpoint_slot_indices),
            "audited_enemy_mutation_kinds": len(model.enemy_mutations),
        },
        "result": {
            "rel_sha256": _sha256(rel_bytes),
            "rel_bytes": len(rel_bytes),
            "code_area_hex": f"{code_bytes:X}",
            "code_bytes": code_bytes,
            "data_area_hex": f"{data_bytes:X}",
            "data_bytes": data_bytes,
            "single_page_bytes": SINGLE_PAGE_BYTES,
            "page_headroom_bytes_before_adapter_and_runtime": (
                SINGLE_PAGE_BYTES - code_bytes),
            "state_bytes": state_bytes,
            "reset_symbol_hex": f"{_symbol(rel_text, 'rtype_python_render_order_reset'):X}",
            "slot_at_symbol_hex": f"{_symbol(rel_text, 'rtype_python_render_order_slot_at'):X}",
        },
        "checks": {
            "generated_artifacts_byte_exact": True,
            "active_python_ast_reaudited": True,
            "code_fits_one_16k_page_alone": code_fits,
            "data_area_empty": data_empty,
            "state_is_exactly_source_derived_191_bytes": state_exact,
            "full_object_copy_required": False,
        },
        "live": False,
        "live_blockers": [
            "object field/class sidecars and target allocation hooks are absent",
            "draw VM object loader is not connected to render-order slot_at",
            "linked code/RAM placement, stack bytes and live tstates are unproved",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_render_order_size_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        result = probe(root)
        output = arguments.output
        if not output.is_absolute():
            output = root / output
        _atomic_json(output, result)
    except RenderOrderSizeError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "Render order size: "
        f"_CODE={result['result']['code_bytes']} bytes, "
        f"state={result['result']['state_bytes']} bytes; live remains blocked")
    return 0 if result["status"] == (
        "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
