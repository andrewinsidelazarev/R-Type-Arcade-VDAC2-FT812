#!/usr/bin/env python3
"""Compare active Python ``wave_power`` with PZVT oracle and C runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from pyz80_compiler.whole_program_vm_backend import (
    CompactTargetVMOracle,
    decode_compact_target_vm,
)
from pyz80_translation_checkpoint import (
    TranslationCheckpointError,
    validate_translation_checkpoint,
)


ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
CALLABLE_ID = "rtype_port.game::wave_power@158"
STATUS_PATH = Path("Build/rtype_python_wave_power_differential_status.json")
CHECKPOINT_PATH = Path("Build/rtype_python_translation_checkpoint.json")
CHECKPOINT_REPORT_PATHS = {
    "active_call_graph": Path(
        "Build/rtype_python_active_call_graph_status.json"),
    "active_call_site_lowering": Path(
        "Build/rtype_python_active_call_site_lowering_status.json"),
    "whole_program_vm_call_abi": Path(
        "Build/rtype_python_whole_program_vm_call_abi_status.json"),
    "whole_program_vm": Path(
        "Build/rtype_python_whole_program_vm_status.json"),
    "whole_program_vm_stack_bound": Path(
        "Build/rtype_python_whole_program_vm_stack_bound_status.json"),
}
IMAGE_PATH = Path("Build/rtype_python_whole_program_vm.bin")
RUNTIME_C = Path("Source/C/python_vm/pyz80_whole_program_vm.c")
RUNTIME_H = Path("Source/C/python_vm/pyz80_whole_program_vm.h")
RUNNER_C = Path("Source/C/python_vm/pyz80_vm_diff_runner.c")
TCC_CANDIDATES = (
    Path("E:/zx/tcc-0.9.27/tcc/tcc.exe"),
    ROOT.parent / "tcc-0.9.27/tcc/tcc.exe",
)


class DifferentialError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DifferentialError(f"invalid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DifferentialError(f"JSON root is not an object: {path}")
    return value


def _read_checkpoint_reports(
        root: Path,
        ) -> tuple[dict[str, dict[str, Any]],
                   dict[str, dict[str, Any]]]:
    reports: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    for stage, relative in CHECKPOINT_REPORT_PATHS.items():
        path = root / relative
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DifferentialError(
                f"invalid UTF-8 JSON: {relative.as_posix()}: {exc}") from exc
        if not isinstance(value, dict):
            raise DifferentialError(
                f"JSON root is not an object: {relative.as_posix()}")
        reports[stage] = value
        records[stage] = {
            "stage": stage,
            "path": relative.as_posix(),
            "present": True,
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
    return reports, records


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DifferentialError(f"{label} is absent or malformed")
    return value


def _require_sha(value: object, label: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            any(character not in "0123456789abcdef" for character in value)):
        raise DifferentialError(f"{label} is not a SHA-256 digest")
    return value


def _matching_binding(_stage: str, field: str, actual: str,
                      expected: str) -> dict[str, Any]:
    return {
        "field": field,
        "actual": actual,
        "expected": expected,
        "matches": actual == expected,
    }


def _expected_checkpoint_bindings(
        reports: dict[str, dict[str, Any]],
        ) -> list[dict[str, Any]]:
    graph = reports["active_call_graph"]
    lowering = reports["active_call_site_lowering"]
    call_abi = reports["whole_program_vm_call_abi"]
    vm = reports["whole_program_vm"]
    stack = reports["whole_program_vm_stack_bound"]
    graph_sha = _require_sha(
        graph.get("semantic_sha256"), "active call graph semantic hash")
    lowering_sha = _require_sha(
        lowering.get("semantic_sha256"), "call-site lowering semantic hash")
    call_abi_sha = _require_sha(
        call_abi.get("semantic_sha256"), "call ABI semantic hash")
    artifact_sha = _require_sha(
        vm.get("artifact_semantic_sha256"), "VM artifact semantic hash")
    vm_binding = _require_mapping(
        vm.get("call_abi_binding"), "VM call ABI binding")
    stack_binding = _require_mapping(
        stack.get("binding"), "stack-bound binding")
    target = _require_mapping(vm.get("target_bytecode"), "target bytecode")
    proof = _require_mapping(vm.get("host_proof"), "host proof")
    return [
        _matching_binding(
            "active_call_site_lowering",
            "active_call_graph_semantic_sha256",
            _require_sha(lowering.get("active_call_graph_semantic_sha256"),
                         "lowering graph binding"),
            graph_sha),
        _matching_binding(
            "whole_program_vm_call_abi",
            "active_call_graph_semantic_sha256",
            _require_sha(call_abi.get("active_call_graph_semantic_sha256"),
                         "call ABI graph binding"),
            graph_sha),
        _matching_binding(
            "whole_program_vm_call_abi",
            "call_site_lowering_semantic_sha256",
            _require_sha(call_abi.get(
                "call_site_lowering_semantic_sha256"),
                "call ABI lowering binding"),
            lowering_sha),
        _matching_binding(
            "whole_program_vm", "active_call_graph_semantic_sha256",
            _require_sha(vm.get("active_call_graph_semantic_sha256"),
                         "VM graph binding"),
            graph_sha),
        _matching_binding(
            "whole_program_vm",
            "call_abi_binding.active_call_site_lowering_semantic_sha256",
            _require_sha(vm_binding.get(
                "active_call_site_lowering_semantic_sha256"),
                "VM lowering binding"),
            lowering_sha),
        _matching_binding(
            "whole_program_vm",
            "call_abi_binding.whole_program_vm_call_abi_semantic_sha256",
            _require_sha(vm_binding.get(
                "whole_program_vm_call_abi_semantic_sha256"),
                "VM call ABI binding"),
            call_abi_sha),
        _matching_binding(
            "whole_program_vm_stack_bound",
            "binding.active_call_graph_semantic_sha256",
            _require_sha(stack_binding.get(
                "active_call_graph_semantic_sha256"),
                "stack-bound graph binding"),
            graph_sha),
        _matching_binding(
            "whole_program_vm_stack_bound",
            "binding.artifact_semantic_sha256",
            _require_sha(stack_binding.get("artifact_semantic_sha256"),
                         "stack-bound artifact binding"),
            artifact_sha),
        _matching_binding(
            "whole_program_vm_stack_bound",
            "binding.target_bytecode_sha256",
            _require_sha(stack_binding.get("target_bytecode_sha256"),
                         "stack-bound target binding"),
            _require_sha(target.get("sha256"), "target bytecode hash")),
        _matching_binding(
            "whole_program_vm_stack_bound",
            "binding.proof_bytecode_sha256",
            _require_sha(stack_binding.get("proof_bytecode_sha256"),
                         "stack-bound proof binding"),
            _require_sha(proof.get("sha256"), "host proof hash")),
    ]


def _validate_artifact_bindings(
        checkpoint: dict[str, Any],
        reports: dict[str, dict[str, Any]],
        report_records: dict[str, dict[str, Any]], image: bytes,
        ) -> None:
    """Reject stale, re-signed, or cross-snapshot differential inputs."""
    try:
        validate_translation_checkpoint(checkpoint)
    except (TranslationCheckpointError, TypeError, ValueError) as exc:
        raise DifferentialError(
            f"translation checkpoint validation failed: {exc}") from exc
    if checkpoint.get("coherent") is not True:
        raise DifferentialError("translation checkpoint is incoherent")

    expected_stages = set(CHECKPOINT_REPORT_PATHS)
    if set(reports) != expected_stages or set(report_records) != expected_stages:
        raise DifferentialError("checkpoint report stage set differs")
    actual_rows = [report_records[stage]
                   for stage in sorted(report_records)]
    checkpoint_rows = checkpoint.get("report_files")
    if not isinstance(checkpoint_rows, list):
        raise DifferentialError("checkpoint report file census is malformed")
    try:
        snapshot_sha = _sha256(_canonical(checkpoint_rows))
    except (TypeError, ValueError) as exc:
        raise DifferentialError(
            "checkpoint report file census is not canonical JSON") from exc
    if checkpoint.get("snapshot_sha256") != snapshot_sha:
        raise DifferentialError("checkpoint snapshot hash differs")
    if checkpoint_rows != actual_rows:
        raise DifferentialError("checkpoint report file hash binding differs")

    expected_bindings = _expected_checkpoint_bindings(reports)
    if any(row["matches"] is not True for row in expected_bindings):
        raise DifferentialError("cross-stage report binding differs")
    if checkpoint.get("bindings") != expected_bindings:
        raise DifferentialError("checkpoint cross-stage binding table differs")

    graph = reports["active_call_graph"]
    lowering = reports["active_call_site_lowering"]
    call_abi = reports["whole_program_vm_call_abi"]
    vm_status = reports["whole_program_vm"]
    expected_semantics = {
        "active_call_graph": _require_sha(
            graph.get("semantic_sha256"), "active graph semantic hash"),
        "active_call_site_lowering": _require_sha(
            lowering.get("semantic_sha256"), "lowering semantic hash"),
        "whole_program_vm_call_abi": _require_sha(
            call_abi.get("semantic_sha256"), "call ABI semantic hash"),
        "whole_program_vm_artifact": _require_sha(
            vm_status.get("artifact_semantic_sha256"),
            "VM artifact semantic hash"),
    }
    if checkpoint.get("stage_semantic_sha256") != expected_semantics:
        raise DifferentialError("checkpoint stage semantic binding differs")

    target = _require_mapping(
        vm_status.get("target_bytecode"), "target bytecode")
    image_sha = _sha256(image)
    if image_sha != _require_sha(
            target.get("sha256"), "target bytecode hash"):
        raise DifferentialError("PZVT file hash differs from VM status")
    if target.get("bytes") != len(image):
        raise DifferentialError("PZVT file size differs from VM status")


def _file_record(root: Path, relative: Path) -> dict[str, Any]:
    data = (root / relative).read_bytes()
    return {"path": relative.as_posix(), "bytes": len(data),
            "sha256": _sha256(data)}


def _reachable_units(program: dict[str, Any], function_index: int) -> set[int]:
    pending = [int(program["functions"][function_index])]
    result: set[int] = set()
    while pending:
        unit_index = pending.pop()
        if unit_index in result:
            continue
        result.add(unit_index)
        unit = program["units"][unit_index]
        for block in unit["blocks"]:
            for instruction in block["instructions"]:
                child = instruction.get("unit")
                if isinstance(child, int):
                    pending.append(child)
    return result


def _wave_power_function_index(graph: dict[str, Any],
                               program: dict[str, Any]) -> int:
    call_graph = _require_mapping(graph.get("call_graph"), "call graph")
    function_ids = call_graph.get("proven_reachable_callable_ids")
    functions = program.get("functions")
    if not isinstance(function_ids, list) or not isinstance(functions, list):
        raise DifferentialError("wave_power/function table is malformed")
    # The compact table appends finite-dispatch guard-only callables after the
    # proven-reachable prefix.  Their presence must not renumber that prefix.
    if (function_ids.count(CALLABLE_ID) != 1 or
            len(function_ids) > len(functions)):
        raise DifferentialError("wave_power/function table binding changed")
    return function_ids.index(CALLABLE_ID)


def _adapter_contract(program: dict[str, Any], vm_status: dict[str, Any],
                      function_index: int) -> tuple[int, int, str]:
    adapter_ids: set[int] = set()
    operator_symbols: set[int] = set()
    for unit_index in _reachable_units(program, function_index):
        for block in program["units"][unit_index]["blocks"]:
            rows = [*block["instructions"], block["terminator"]]
            for row in rows:
                adapter_id = row.get("adapter_id")
                if not isinstance(adapter_id, int):
                    continue
                adapter_ids.add(adapter_id)
                arguments = row.get("arguments", [])
                if arguments and arguments[0].get("kind") == "constant":
                    symbol = int(arguments[0]["id"])
                    if program["constants"][symbol] == "lt":
                        operator_symbols.add(symbol)
    if len(adapter_ids) != 1 or len(operator_symbols) != 1:
        raise DifferentialError(
            f"wave_power adapter closure changed: {adapter_ids}, {operator_symbols}")
    adapter_id = next(iter(adapter_ids))
    descriptor = vm_status["adapter_table"][adapter_id]
    if (descriptor.get("op") != "python-compare" or
            descriptor.get("argument_count") != 3 or
            descriptor.get("attributes") != {"python_data_model": True}):
        raise DifferentialError(f"unexpected adapter descriptor: {descriptor}")
    return adapter_id, next(iter(operator_symbols)), descriptor["semantic_sha256"]


def _parse_c_rows(output: str) -> dict[int, tuple[int, tuple[int, ...]]]:
    """Parse the runner protocol without accepting partial or duplicate rows."""
    result: dict[int, tuple[int, tuple[int, ...]]] = {}
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            raise DifferentialError(
                f"malformed C row at line {line_number}: blank line")
        try:
            fields = [int(value) for value in line.split()]
        except ValueError as exc:
            raise DifferentialError(
                f"malformed C row at line {line_number}: {line}") from exc
        if len(fields) < 3 or fields[2] < 0 or fields[2] != len(fields) - 3:
            raise DifferentialError(f"malformed C row: {line}")
        charge, result_value, _count, *thresholds = fields
        if charge in result:
            raise DifferentialError(f"duplicate C row: {charge}")
        result[charge] = result_value, tuple(thresholds)
    return result


def _validated_result_row(
        charge: int, python_result: object, compact_result: object,
        trace: list[int], c_rows: dict[int, tuple[int, tuple[int, ...]]],
        ) -> dict[str, Any]:
    c_result = c_rows.get(charge)
    if c_result is None:
        raise DifferentialError(f"C result is absent for charge={charge}")
    if (python_result != compact_result or python_result != c_result[0] or
            tuple(trace) != c_result[1]):
        raise DifferentialError(
            "first divergence at charge="
            f"{charge}: Python={python_result}, PZVT={compact_result}, "
            f"C={c_result}, PZVT trace={tuple(trace)}")
    return {"charge": charge, "result": python_result,
            "thresholds": list(trace)}


def _validate_c_domain(
        c_rows: dict[int, tuple[int, tuple[int, ...]]], *,
        first: int = 0, last: int = 128,
        ) -> None:
    expected = set(range(first, last + 1))
    actual = set(c_rows)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise DifferentialError(
            "C runner result domain differs: "
            f"missing={missing}, unexpected={unexpected}")


def _compiler(root: Path) -> tuple[Path, str]:
    tcc = next((path for path in TCC_CANDIDATES if path.is_file()), None)
    if tcc is None:
        found = shutil.which("tcc")
        tcc = Path(found) if found else None
    if tcc is None:
        raise DifferentialError("TCC is not available")
    completed = subprocess.run(
        [str(tcc), "-v"], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=30)
    version = completed.stdout.strip()
    if completed.returncode != 0 or not version:
        raise DifferentialError(f"TCC version probe failed: {version}")
    return tcc.resolve(), version


def _cached_runner(root: Path) -> tuple[Path, dict[str, Any]]:
    tcc, version = _compiler(root)
    inputs = [_file_record(root, path) for path in
              (RUNTIME_C, RUNTIME_H, RUNNER_C)]
    compiler = {"path": str(tcc), "sha256": _sha256(tcc.read_bytes()),
                "version": version}
    key = _sha256(_canonical({"inputs": inputs, "compiler": compiler}))
    directory = root / "Build/HostTools"
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / f"pyz80_vm_diff_runner_{key[:16]}.exe"
    if not executable.is_file():
        command = [
            str(tcc), "-std=c11", "-Wall", "-Werror",
            str(root / RUNTIME_C), str(root / RUNNER_C),
            "-I", str(root / RUNTIME_H.parent), "-o", str(executable),
        ]
        completed = subprocess.run(
            command, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=120)
        if completed.returncode != 0:
            raise DifferentialError(f"C runner compile failed:\n{completed.stdout}")
    return executable, {"cache_key_sha256": key, "inputs": inputs,
                        "compiler": compiler,
                        "executable_sha256": _sha256(executable.read_bytes())}


def run_differential(project_root: Path | str = ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checkpoint = _read_json(root / CHECKPOINT_PATH)
    reports, report_records = _read_checkpoint_reports(root)
    graph = reports["active_call_graph"]
    vm_status = reports["whole_program_vm"]
    stack = reports["whole_program_vm_stack_bound"]
    image_path = root / IMAGE_PATH
    image = image_path.read_bytes()
    _validate_artifact_bindings(
        checkpoint, reports, report_records, image)
    program = decode_compact_target_vm(
        image, expected_proof_semantic_sha256=vm_status[
            "artifact_semantic_sha256"])
    function_index = _wave_power_function_index(graph, program)
    adapter_id, lt_symbol, adapter_semantic = _adapter_contract(
        program, vm_status, function_index)
    arena = stack["arena"]
    max_depth = arena["proved_call_depth_lower_bound"]
    locals_per_frame = arena["locals_per_frame_required"]
    max_arguments = arena["max_arguments_required"]
    executable, runner = _cached_runner(root)
    command = [
        str(executable), str(image_path), vm_status["artifact_semantic_sha256"],
        str(function_index), str(adapter_id), str(lt_symbol), str(max_depth),
        str(locals_per_frame), str(max_arguments),
    ]
    completed = subprocess.run(
        command, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=120)
    if completed.returncode != 0:
        raise DifferentialError(
            f"C runner failed ({completed.returncode}):\n{completed.stdout}")
    c_rows = _parse_c_rows(completed.stdout)

    # Match run_python.cmd's dependency roots without starting the application.
    sys.path.insert(0, str(root / "Build/PythonDeps"))
    sys.path.insert(0, str(root / "Source/Python"))
    sys.dont_write_bytecode = True
    from rtype_port.game import wave_power  # noqa: PLC0415

    trace: list[int] = []

    def adapter(current_id: int, arguments: list[Any],
                _descriptor: dict[str, Any]) -> bool:
        if (current_id != adapter_id or len(arguments) != 3 or
                arguments[0] != "lt" or
                not isinstance(arguments[1], int) or
                not isinstance(arguments[2], int)):
            raise DifferentialError(
                f"unexpected compact adapter call: {current_id}, {arguments}")
        trace.append(arguments[2])
        return arguments[1] < arguments[2]

    oracle = CompactTargetVMOracle(image, adapter=adapter)
    result_rows: list[dict[str, Any]] = []
    total_adapter_calls = 0
    for charge in range(129):
        trace.clear()
        python_result = wave_power(charge)
        compact_result = oracle.run(function_index, [charge])
        total_adapter_calls += len(trace)
        result_rows.append(_validated_result_row(
            charge, python_result, compact_result, trace, c_rows))
    _validate_c_domain(c_rows)

    callable_row = next(row for row in graph["callable_inventory"]["callables"]
                        if row["callable_id"] == CALLABLE_ID)
    report: dict[str, Any] = {
        "format": "pyz80.wave-power-differential.v1",
        "status": "exact-for-tested-domain",
        "live": False,
        "translation_checkpoint_snapshot_sha256": checkpoint[
            "snapshot_sha256"],
        "active_call_graph_semantic_sha256": graph["semantic_sha256"],
        "vm_artifact_semantic_sha256": vm_status["artifact_semantic_sha256"],
        "target_bytecode_sha256": vm_status["target_bytecode"]["sha256"],
        "callable": {
            "callable_id": CALLABLE_ID,
            "numeric_function_id": function_index,
            "cfg_semantic_sha256": callable_row["cfg"]["semantic_sha256"],
        },
        "adapter": {
            "adapter_id": adapter_id,
            "semantic_sha256": adapter_semantic,
            "operator_symbol_constant_id": lt_symbol,
            "total_call_count": total_adapter_calls,
        },
        "input_schedule": {"first": 0, "last": 128, "count": 129,
                           "sha256": _sha256(_canonical(list(range(129))))},
        "result_trace_sha256": _sha256(_canonical(result_rows)),
        "runner": runner,
        "proof": {
            "active_python_imported_without_source_changes": True,
            "compact_oracle_matches_active_python": True,
            "c_runtime_matches_active_python": True,
            "adapter_sequence_matches_between_compact_and_c": True,
            "all_integer_inputs_0_through_128_checked": True,
        },
        "live_blockers": [{
            "code": "PZDIFF201",
            "detail": ("This closes one pure active-Python function only; "
                       "persistent Game.update/object state is not executable yet."),
        }],
    }
    report["semantic_sha256"] = _sha256(_canonical(report))
    output = root / STATUS_PATH
    rendered = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8") + b"\n"
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(rendered)
    os.replace(temporary, output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = run_differential(args.project_root)
    except (OSError, ValueError, KeyError, DifferentialError) as exc:
        print(f"PZVT DIFFERENTIAL ERROR: {exc}")
        return 1
    print(json.dumps({
        "status": report["status"],
        "inputs": report["input_schedule"]["count"],
        "adapter_calls": report["adapter"]["total_call_count"],
        "trace_sha256": report["result_trace_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
