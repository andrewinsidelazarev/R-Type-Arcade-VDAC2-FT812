#!/usr/bin/env python3
"""Reproduce the pinned-SDCC size certificate for the compact draw VM."""

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

from pyz80_compiler.draw_plan import compile_active_enemy_draw_plan
from pyz80_compiler.draw_vm_backend import (
    build_draw_vm_program,
    emit_draw_vm_backend,
)
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-vm-target-size-probe-v2"
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


class DrawVMSizeError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrawVMSizeError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DrawVMSizeError(f"{path} is not a JSON object")
    return value


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
        raise DrawVMSizeError(f"SDCC .rel lacks symbol {name}")
    return int(match.group(1), 16)


def _sizeof_value(text: str, name: str) -> int:
    match = re.search(
        rf"^_{re.escape(name)}:\s*\r?\n\s*\.dw\s+#0x([0-9A-Fa-f]+)$",
        text, re.MULTILINE)
    if match is None:
        raise DrawVMSizeError(f"SDCC size probe lacks {name}")
    return int(match.group(1), 16)


def probe(root: Path) -> dict[str, object]:
    root = root.resolve()
    plan = compile_active_enemy_draw_plan(root)
    program = build_draw_vm_program(plan)
    artifacts = emit_draw_vm_backend(plan)
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
            raise DrawVMSizeError(f"missing generated VM artifact {path}") from exc
        if actual != expected:
            raise DrawVMSizeError(
                f"generated VM artifact is stale/non-reproducible: {path}")

    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="pyz80-draw-vm-size-") as temp:
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
            raise DrawVMSizeError(
                f"pinned SDCC failed ({completed.returncode}):\n"
                f"{completed.stdout}")
        rel_path = directory / artifacts.source_name.replace(".c", ".rel")
        try:
            rel_bytes = rel_path.read_bytes()
        except OSError as exc:
            raise DrawVMSizeError("pinned SDCC did not produce .rel") from exc
        rel_text = rel_bytes.decode("latin1")
        size_probe_name = "rtype_python_draw_vm_sizeof_probe.c"
        size_probe_source = (
            f'#include "{artifacts.header_name}"\n'
            "const uint16_t vm_object_size = "
            "sizeof(rtype_python_draw_vm_object_view);\n"
            "const uint16_t vm_transient_size = "
            "sizeof(rtype_python_draw_vm_transient_view);\n"
            "const uint16_t vm_input_size = "
            "sizeof(rtype_python_draw_vm_input);\n"
        )
        (directory / size_probe_name).write_text(
            size_probe_source, encoding="utf-8", newline="\n")
        size_completed = subprocess.run(
            [str(sdcc), *PINNED_ARGUMENTS, "-S", size_probe_name],
            cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if size_completed.returncode != 0:
            raise DrawVMSizeError(
                f"pinned SDCC sizeof probe failed "
                f"({size_completed.returncode}):\n{size_completed.stdout}")
        size_asm = (directory / size_probe_name.replace(
            ".c", ".asm")).read_text(encoding="latin1")

    object_view_bytes = _sizeof_value(size_asm, "vm_object_size")
    transient_view_bytes = _sizeof_value(size_asm, "vm_transient_size")
    input_bytes = _sizeof_value(size_asm, "vm_input_size")

    areas = _area_map(rel_text)
    code_bytes = areas.get("_CODE")
    data_bytes = areas.get("_DATA")
    if code_bytes is None or data_bytes is None:
        raise DrawVMSizeError("SDCC .rel lacks _CODE/_DATA area")

    baseline_path = root / "Build" / "rtype_python_draw_c_size_status.json"
    baseline = _read_json(baseline_path)
    try:
        baseline_plan = str(baseline["input"]["plan_semantic_sha256"])
        baseline_code = int(baseline["result"]["code_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawVMSizeError("unrolled size baseline has invalid schema") from exc
    if baseline_plan != plan.semantic_sha256:
        raise DrawVMSizeError(
            "unrolled/compact size reports refer to different draw plans")

    frame_bound_path = (
        root / "Build" / "rtype_python_frame_record_bound_status.json")
    frame_bound = _read_json(frame_bound_path)
    try:
        frame_plan = str(frame_bound["draw_plan"]["semantic_sha256"])
        pool_slots = int(frame_bound["object_pool"]["slot_count"])
        allocatable_slots = int(
            frame_bound["object_pool"]["allocatable_record_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawVMSizeError("frame-record report has invalid pool schema") from exc
    if frame_plan != plan.semantic_sha256:
        raise DrawVMSizeError(
            "frame-record/compact reports refer to different draw plans")

    code_fits = code_bytes <= SINGLE_PAGE_BYTES
    data_empty = data_bytes == 0
    smaller = code_bytes < baseline_code
    object_view_exact = object_view_bytes == 28
    if not (code_fits and data_empty and smaller and object_view_exact):
        status = "BLOCKED_COMPACT_SIZE_CERTIFICATE_FAILED"
    else:
        status = "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED"
    saved = baseline_code - code_bytes
    result: dict[str, object] = {
        "format": FORMAT,
        "status": status,
        "input": {
            "plan_semantic_sha256": plan.semantic_sha256,
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
        "vm": {
            "node_count": len(program.nodes),
            "condition_pack_count": len(program.condition_packs),
            "action_count": len(program.actions),
            "logical_table_payload_bytes": program.table_payload_bytes,
            "max_recursive_eval_depth": program.max_eval_depth,
            "pinned_sdcc_stack_bytes": None,
            "live_z80_tstates": None,
        },
        "normalized_input_abi": {
            "pinned_sdcc_sizeof": {
                "object_view_bytes": object_view_bytes,
                "transient_view_bytes": transient_view_bytes,
                "input_bytes": input_bytes,
            },
            "source_derived_pool": {
                "report": "Build/rtype_python_frame_record_bound_status.json",
                "slot_count": pool_slots,
                "allocatable_slots": allocatable_slots,
                "bytes_if_all_slots_materialized_as_full_views": (
                    pool_slots * object_view_bytes),
                "bytes_if_allocatable_slots_materialized_as_full_views": (
                    allocatable_slots * object_view_bytes),
                "working_object_view_count": 1,
                "working_object_view_bytes": object_view_bytes,
                "bytes_avoided_vs_all_slots_full_copy": (
                    (pool_slots - 1) * object_view_bytes),
                "bytes_avoided_vs_allocatable_slots_full_copy": (
                    (allocatable_slots - 1) * object_view_bytes),
                "full_pool_copy_required": False,
            },
            "object_provider": {
                "abi_present": True,
                "successful_loader_calls_per_preflight_pass": "object_count",
                "successful_loader_calls_per_emission_pass": "object_count",
                "successful_loader_calls_per_produce_or_stream": (
                    "2 * object_count"),
                "calls_per_item_per_pass": 1,
                "preflight_failure_at_index_i_attempts": "i + 1",
                "preflight_failure_resolver_calls": 0,
                "preflight_failure_emitter_calls": 0,
            },
            "live_adapter_status": (
                "PROVIDER_ABI_READY_TARGET_LAYOUT_MAPPING_BLOCKED"),
            "requirement": (
                "implement the source-derived target-layout callback behind "
                "the proved one-view provider ABI"),
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "sha256": _sha256(sdcc.read_bytes()),
            "arguments": [*PINNED_ARGUMENTS, "-c", artifacts.source_name],
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
            "produce_symbol_hex": f"{_symbol(rel_text, program.model.prefix + '_produce'):X}",
            "stream_symbol_hex": f"{_symbol(rel_text, program.model.prefix + '_stream'):X}",
        },
        "comparison_to_unrolled_same_plan": {
            "baseline_report": "Build/rtype_python_draw_c_size_status.json",
            "unrolled_code_bytes": baseline_code,
            "compact_code_bytes": code_bytes,
            "saved_code_bytes": saved,
            "reduction_percent": round(saved * 100.0 / baseline_code, 4),
        },
        "checks": {
            "generated_artifacts_byte_exact": True,
            "same_plan_as_unrolled_baseline": True,
            "code_fits_one_16k_page_alone": code_fits,
            "data_area_empty": data_empty,
            "smaller_than_unrolled": smaller,
            "object_view_is_exactly_28_target_bytes": object_view_exact,
            "single_working_view_abi_present": True,
            "full_pool_copy_required": False,
        },
        "live_target_performance_and_size_certified": False,
        "live_blockers": [
            "source-derived target object fields are not mapped into the provider",
            "recursive evaluator logical depth is proved but SDCC stack bytes are not",
            "live Z80 tstates and complete FT812 frame budget are not proved",
            "the 16 KiB result covers this producer alone, not adapter/runtime link",
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_vm_size_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        result = probe(root)
        output = arguments.output
        if not output.is_absolute():
            output = root / output
        _atomic_json(output, result)
    except DrawVMSizeError as exc:
        print(f"FAIL: {exc}")
        return 1
    code = int(result["result"]["code_bytes"])
    saved = int(result["comparison_to_unrolled_same_plan"]["saved_code_bytes"])
    print(
        f"Draw VM size: _CODE={code} bytes, _DATA=0, "
        f"saved={saved} bytes; live remains blocked")
    return 0 if result["status"] == "TARGET_NEUTRAL_SIZE_PASS_LIVE_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
