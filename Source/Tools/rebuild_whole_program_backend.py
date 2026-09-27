#!/usr/bin/env python3
"""Rebuild only the whole-program backend from validated frontend reports.

The candidate bundle is independent of the last full translation and SPG.
Its manifest records source/compiler inputs, every output, real timings and
remaining execution blockers. Reuse requires byte hashes of all these files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
import time

from generate_pzvt_target_adapters import generate
from pyz80_translation_checkpoint import write_translation_checkpoint
from pyz80_compiler.generation_transaction import GenerationTransaction
from pyz80_compiler.whole_program_vm_call_abi import analyze_whole_program_vm_call_abi
from pyz80_compiler.whole_program_vm_stack_bound import _locate_sdcc
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_call_site_lowering import analyze_active_call_site_lowering
from pyz80_compiler.frontend import lower_active_object_store_ir, object_store_ir_report
from pyz80_compiler.mutation_hook_ir import build_mutation_hook_ir
from rtype_python_translator import whole_program_vm_contract

ROOT = Path(__file__).resolve().parents[2]
INPUT_REPORTS = (
    "rtype_python_active_call_graph_status.json",
    "rtype_python_active_call_site_lowering_status.json",
    "rtype_python_object_store_ir_status.json",
)
OUTPUT_NAMES = (
    *INPUT_REPORTS[:2],
    "rtype_python_whole_program_vm_call_abi_status.json",
    "rtype_python_whole_program_vm.bin",
    "rtype_python_whole_program_vm_proof.bin",
    "rtype_python_whole_program_vm_status.json",
    "rtype_python_whole_program_vm_stack_bound_status.json",
    "rtype_python_translation_checkpoint.json",
    "rtype_python_target_adapter_backend_status.json",
    "pyz80_target_adapter_plan_generated.h",
    "pyz80_target_adapter_plan_generated.c",
    "core_tables.pztb",
    "core_tables.json",
    "pyz80_target_banked_plan_generated.h",
    "pyz80_target_banked_plan_generated.c",
)
MANIFEST_NAME = "backend_build.json"
FORMAT = "pyz80.validated-backend-build.v1"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _semantic(report: dict) -> str:
    return _hash(json.dumps({k: v for k, v in report.items()
                            if k != "semantic_sha256"}, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":")).encode())


def _record(root: Path, path: Path) -> dict:
    data = path.read_bytes()
    return {"path": (path.relative_to(root).as_posix()
                     if path.is_relative_to(root) else path.as_posix()),
            "bytes": len(data), "sha256": _hash(data)}


def _dependencies(root: Path, *, frontend_directory: Path | None = None) -> list[dict]:
    paths = [(frontend_directory or _frontend_directory(root)) / name for name in INPUT_REPORTS]
    paths.extend(root / "Source/Tools" / name for name in (
        "rtype_python_translator.py", "generate_pzvt_target_adapters.py",
        "pyz80_translation_checkpoint.py", "rebuild_whole_program_backend.py"))
    paths.extend((root / "Source/Tools/pyz80_compiler").glob("*.py"))
    paths.extend(path for path in (root / "Source/Tools").glob("*.py")
                 if not path.name.startswith("test_"))
    paths.extend((root / "Source/Python").rglob("*.py"))
    paths.extend(path for path in (root / "Source/C/python_vm").glob("*.*")
                 if path.suffix in {".c", ".h"} and "generated" not in path.name)
    paths.append(root / "run_python.cmd")
    paths.append(Path(sys.executable).resolve())
    sdcc = _locate_sdcc(root)
    if sdcc is not None:
        paths.append(sdcc)
    return [_record(root, path) for path in sorted(set(paths))]


def _frontend_directory(root: Path) -> Path:
    fresh = root / "Build/WholeProgramFrontend"
    present = [(fresh / name).is_file() for name in INPUT_REPORTS]
    if any(present) and not all(present):
        raise RuntimeError("incomplete isolated frontend; run --refresh-frontend")
    return fresh if all(present) else root / "Build"


def _refresh_frontend(root: Path) -> float:
    """Re-lower current source; never re-sign an old IR after a compiler edit."""
    def source_inputs():
        return [row for row in _dependencies(root, frontend_directory=root / "Build")
                if not row["path"].startswith("Build/")]

    before = source_inputs()
    started = time.perf_counter()
    hooks = build_mutation_hook_ir(root)
    stores = lower_active_object_store_ir(root, hook_plan=hooks)
    print(f"Fresh mutation/expression IR: {time.perf_counter() - started:.2f}s", flush=True)
    graph = analyze_active_call_graph(root, hook_plan=hooks, object_store_module=stores)
    print(f"Fresh source call graph: {time.perf_counter() - started:.2f}s", flush=True)
    lowering = analyze_active_call_site_lowering(root, active_graph=graph)
    if before != source_inputs():
        raise RuntimeError("source/compiler inputs changed during frontend refresh")
    output = root / "Build/WholeProgramFrontend"
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in INPUT_REPORTS]
    with GenerationTransaction(files=paths):
        for path, report in zip(paths, (graph, lowering, object_store_ir_report(stores))):
            path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    print(f"Isolated frontend saved: {time.perf_counter() - started:.2f}s", flush=True)
    return time.perf_counter() - started


def _valid_cache(root: Path, output: Path, dependencies: list[dict]) -> dict | None:
    try:
        report = json.loads((output / MANIFEST_NAME).read_bytes())
        if (report.get("format") != FORMAT or report.get("live") is not False or
                report.get("semantic_sha256") != _semantic(report) or
                report.get("inputs") != dependencies):
            return None
        expected = [_record(root, output / name) for name in OUTPUT_NAMES]
        if report.get("outputs") != expected:
            return None
        return report
    except (OSError, ValueError, TypeError, KeyError):
        return None


def rebuild(root: Path = ROOT, *, output: Path | None = None,
            force: bool = False, check_only: bool = False,
            refresh_frontend: bool = False) -> dict:
    root = root.resolve()
    output = (output or root / "Build/WholeProgramBackend").resolve()
    if not output.is_relative_to(root / "Build") or output == root / "Build":
        raise ValueError("backend output must be a dedicated directory below Build")
    if refresh_frontend and check_only:
        raise ValueError("frontend refresh cannot be combined with check-only")
    started = time.perf_counter()
    frontend_seconds = _refresh_frontend(root) if refresh_frontend else 0.0
    inputs = _dependencies(root)
    cached = _valid_cache(root, output, inputs)
    if cached is not None and not force:
        return {"reused": True, "seconds": round(time.perf_counter() - started, 3),
                "output": str(output), "result": cached["result"]}
    if check_only:
        raise RuntimeError("backend bundle is absent, stale or modified; run rebuild")

    raw = {name: (_frontend_directory(root) / name).read_bytes() for name in INPUT_REPORTS}
    graph, lowering, stores = [json.loads(raw[name]) for name in INPUT_REPORTS]
    timings = {"frontend_refresh": frontend_seconds}
    stage = time.perf_counter()
    # Public analysis validates the saved graph against current Python sources
    # and frontend code, and rechecks lowering. Stale frontend inputs fail.
    abi = analyze_whole_program_vm_call_abi(
        root, active_graph=graph, call_site_lowering=lowering)
    timings["validate_frontend_and_build_call_abi"] = time.perf_counter() - stage
    print(f"Validated frontend + call ABI: {timings['validate_frontend_and_build_call_abi']:.2f}s", flush=True)

    output.mkdir(parents=True, exist_ok=True)
    files = [output / name for name in (*OUTPUT_NAMES, MANIFEST_NAME)]
    with GenerationTransaction(files=files):
        stage = time.perf_counter()
        artifact, status, stack = whole_program_vm_contract(
            graph, lowering, abi, root, object_store_ir=stores,
            output_directory=output)
        timings["vm_and_z80_stack_certificate"] = time.perf_counter() - stage
        print(f"PZVT + stack certificate: {timings['vm_and_z80_stack_certificate']:.2f}s",
              flush=True)
        for name in INPUT_REPORTS[:2]:
            (output / name).write_bytes(raw[name])
        (output / "rtype_python_whole_program_vm_call_abi_status.json").write_text(
            json.dumps(abi, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        checkpoint = write_translation_checkpoint(
            root, output / "rtype_python_translation_checkpoint.json",
            report_directory=output)
        if not checkpoint["coherent"]:
            raise RuntimeError(f"backend checkpoint mismatch: {checkpoint['issues']}")
        generate(root, build_directory=output, source_directory=output)
        if _dependencies(root) != inputs:
            raise RuntimeError("source/compiler inputs changed during backend rebuild")
        coverage = artifact.target_coverage
        result = {
            "target_bytes": len(artifact.target_bytecode),
            "target_sha256": artifact.target_bytecode_sha256,
            "lowered_call_instructions": coverage["abi_lowered_call_instruction_count"],
            "unlowered_call_instructions": coverage["abi_unlowered_call_instruction_count"],
            "direct_call_instructions": coverage["direct_call_instruction_count"],
            "ambiguous_callable_ssa": abi["census"]["ambiguous_callable_ssa_provenance_count"],
            "python_call_adapters": sum(row["op"] == "python-call"
                                        for row in artifact.adapter_table),
            "stack_complete_bound_proved": stack["complete_bound_proved"],
            "phi_instructions_lowered": coverage["phi_instruction_count"],
            "phi_edge_copies": coverage["phi_edge_copy_instruction_count"],
            "phi_scratch_locals": coverage["phi_scratch_local_count"],
            "execution_blockers": status["live_blockers"],
        }
        timings["total"] = time.perf_counter() - started
        report = {"format": FORMAT, "live": False,
                  "scope": "validated backend candidate; not a linked game or SPG",
                  "inputs": inputs,
                  "outputs": [_record(root, output / name) for name in OUTPUT_NAMES],
                  "timings_seconds": {k: round(v, 3) for k, v in timings.items()},
                  "result": result}
        report["semantic_sha256"] = _semantic(report)
        (output / MANIFEST_NAME).write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    return {"reused": False, "seconds": round(timings["total"], 3),
            "output": str(output), "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--refresh-frontend", action="store_true",
                        help="rebuild source IR in an isolated folder after frontend changes")
    args = parser.parse_args()
    if args.check and (args.force or args.refresh_frontend):
        parser.error("--check cannot be combined with --force or --refresh-frontend")
    result = rebuild(force=args.force, check_only=args.check, refresh_frontend=args.refresh_frontend)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
