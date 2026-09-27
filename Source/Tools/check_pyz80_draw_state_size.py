#!/usr/bin/env python3
"""Reproduce the pinned-SDCC draw-state sidecar size certificate."""

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

from pyz80_compiler.draw_state_backend import (
    build_draw_state_model,
    emit_draw_state_backend,
)
from pyz80_compiler.draw_vm_backend import emit_draw_vm_backend
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.render_order_backend import emit_render_order_backend
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-state-target-size-probe-v1"
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


class DrawStateSizeError(RuntimeError):
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
        raise DrawStateSizeError(f"SDCC .rel lacks symbol {name}")
    return int(match.group(1), 16)


def _sizeof_value(text: str, name: str) -> int:
    match = re.search(
        rf"^_{re.escape(name)}:\s*\r?\n\s*\.dw\s+#0x([0-9A-Fa-f]+)$",
        text, re.MULTILINE)
    if match is None:
        raise DrawStateSizeError(f"SDCC size probe lacks {name}")
    return int(match.group(1), 16)


def _exact_generated(
        generated: Path, artifacts: object,
        ) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for role, name, text in (
            ("header", artifacts.header_name, artifacts.header),
            ("source", artifacts.source_name, artifacts.source),
            ("manifest", artifacts.manifest_name, artifacts.manifest)):
        expected = text.encode("utf-8")
        path = generated / name
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise DrawStateSizeError(f"missing generated artifact {path}") from exc
        if actual != expected:
            raise DrawStateSizeError(f"generated artifact is stale: {path}")
        result[role] = {
            "path": "Source/C/generated/" + name,
            "bytes": len(actual),
            "sha256": _sha256(actual),
        }
    return result


def probe(project_root: Path | str) -> dict[str, object]:
    root = Path(project_root).resolve()
    model = build_draw_state_model(root)
    artifacts = emit_draw_state_backend(root)
    vm_artifacts = emit_draw_vm_backend(model.plan)
    order_artifacts = emit_render_order_backend(root)
    generated = root / "Source" / "C" / "generated"
    sidecar_files = _exact_generated(generated, artifacts)
    vm_files = _exact_generated(generated, vm_artifacts)
    order_files = _exact_generated(generated, order_artifacts)

    compiler_manifest_path = (
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    compiler_manifest = CompilerManifest.load(compiler_manifest_path)
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="pyz80-draw-state-size-") as temp:
        directory = Path(temp)
        for item in (artifacts, vm_artifacts, order_artifacts):
            (directory / item.header_name).write_text(
                item.header, encoding="utf-8", newline="\n")
            (directory / item.source_name).write_text(
                item.source, encoding="utf-8", newline="\n")
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", artifacts.source_name]
        completed = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=240,
            env=environment)
        if completed.returncode != 0:
            raise DrawStateSizeError(
                f"pinned SDCC failed ({completed.returncode}):\n"
                f"{completed.stdout}")
        rel_path = directory / artifacts.source_name.replace(".c", ".rel")
        try:
            rel_bytes = rel_path.read_bytes()
        except OSError as exc:
            raise DrawStateSizeError("pinned SDCC did not produce .rel") from exc
        rel_text = rel_bytes.decode("latin1")

        probe_name = "rtype_python_draw_state_sizeof_probe.c"
        probe_source = f'''#include "{artifacts.header_name}"
const uint16_t draw_state_values_size = sizeof(rtype_python_draw_state_values);
const uint16_t draw_state_slot_size = sizeof(rtype_python_draw_state_slot_state);
const uint16_t draw_state_state_size = sizeof(rtype_python_draw_state_state);
const uint16_t draw_state_provider_size = sizeof(rtype_python_draw_state_provider_context);
'''
        (directory / probe_name).write_text(
            probe_source, encoding="utf-8", newline="\n")
        size_completed = subprocess.run(
            [str(sdcc), *PINNED_ARGUMENTS, "-S", probe_name],
            cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=240,
            env=environment)
        if size_completed.returncode != 0:
            raise DrawStateSizeError(
                "pinned SDCC sizeof probe failed "
                f"({size_completed.returncode}):\n{size_completed.stdout}")
        size_asm = (directory / probe_name.replace(
            ".c", ".asm")).read_text(encoding="latin1")

    areas = _area_map(rel_text)
    code_bytes = areas.get("_CODE")
    data_bytes = areas.get("_DATA")
    const_bytes = areas.get("_CONST", 0)
    if code_bytes is None or data_bytes is None:
        raise DrawStateSizeError("SDCC .rel lacks _CODE/_DATA area")
    values_bytes = _sizeof_value(size_asm, "draw_state_values_size")
    slot_bytes = _sizeof_value(size_asm, "draw_state_slot_size")
    state_bytes = _sizeof_value(size_asm, "draw_state_state_size")
    provider_bytes = _sizeof_value(size_asm, "draw_state_provider_size")
    layout_exact = (
        values_bytes == model.value_bytes and
        slot_bytes == model.slot_state_bytes and
        state_bytes == model.state_bytes)
    code_fits = code_bytes <= SINGLE_PAGE_BYTES
    data_empty = data_bytes == 0
    status = (
        "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED"
        if code_fits and data_empty and layout_exact
        else "BLOCKED_DRAW_STATE_SIZE_CERTIFICATE_FAILED")
    compiler_bytes = sdcc.read_bytes()
    compiler_manifest_bytes = compiler_manifest_path.read_bytes()
    return {
        "format": FORMAT,
        "status": status,
        "input": {
            "semantic_sha256": model.semantic_sha256,
            "active_python_source_sha256": model.source_sha256,
            "draw_plan_semantic_sha256": model.plan.semantic_sha256,
            "sidecar": sidecar_files,
            "draw_vm": vm_files,
            "render_order": order_files,
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "sha256": _sha256(compiler_bytes),
            "manifest_path": "Source/Tools/rtype_python_compiler.json",
            "manifest_sha256": _sha256(compiler_manifest_bytes),
            "arguments": [*PINNED_ARGUMENTS, "-c", artifacts.source_name],
        },
        "source_derived_model": {
            "slot_count": model.slot_count,
            "normalized_field_count": len(model.fields),
            "concrete_enemy_class_count": len(model.concrete_classes),
            "mutation_site_count": len(model.mutation_sites),
            "derived_field_site_count": len(model.derived_field_sites),
            "dynamic_write_blocker_count": len(model.dynamic_write_sites),
            "identity_site_count": len(model.identity_sites),
        },
        "result": {
            "rel_sha256": _sha256(rel_bytes),
            "rel_bytes": len(rel_bytes),
            "code_area_hex": f"{code_bytes:X}",
            "code_bytes": code_bytes,
            "const_area_hex": f"{const_bytes:X}",
            "const_bytes": const_bytes,
            "data_area_hex": f"{data_bytes:X}",
            "data_bytes": data_bytes,
            "single_page_bytes": SINGLE_PAGE_BYTES,
            "page_headroom_bytes_before_linked_vm_order_runtime": (
                SINGLE_PAGE_BYTES - code_bytes),
            "values_bytes": values_bytes,
            "slot_state_bytes": slot_bytes,
            "persistent_state_bytes": state_bytes,
            "provider_context_bytes": provider_bytes,
            "reset_symbol_hex": f"{_symbol(rel_text, 'rtype_python_draw_state_reset'):X}",
            "loader_symbol_hex": f"{_symbol(rel_text, 'rtype_python_draw_state_load_object'):X}",
            "set_at_site_symbol_hex": f"{_symbol(rel_text, 'rtype_python_draw_state_set_at_site'):X}",
        },
        "checks": {
            "generated_sidecar_vm_order_artifacts_byte_exact": True,
            "active_python_ast_reaudited": True,
            "plan_order_vm_hashes_pinned": True,
            "compiler_binary_and_manifest_hashes_pinned": True,
            "code_fits_one_16k_page_alone": code_fits,
            "data_area_empty": data_empty,
            "persistent_layout_exact": layout_exact,
            "full_pool_copy_per_frame": False,
        },
        "live": False,
        "live_blockers": [
            f"{len(model.mutation_sites)} generated mutation-site ids are "
            "not lowered/hooked on target",
            f"{len(model.derived_field_sites)} derived getter dependencies "
            "are not lowered",
            f"{len(model.dynamic_write_sites)} dynamic setattr sites remain "
            "conservative sync blockers",
            f"{len(model.identity_sites)} pool identity/order lifecycle "
            "sites are not hooked",
            "linked VM+order+sidecar placement, stack bytes and tstates are unproved",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_state_size_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        result = probe(root)
        output = arguments.output
        if not output.is_absolute():
            output = root / output
        _atomic_json(output, result)
    except DrawStateSizeError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "Draw state size: "
        f"_CODE={result['result']['code_bytes']} bytes, "
        f"_CONST={result['result']['const_bytes']} bytes, "
        f"_DATA={result['result']['data_bytes']} bytes, "
        f"state={result['result']['persistent_state_bytes']} bytes; "
        "live remains blocked")
    return 0 if result["status"] == (
        "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
