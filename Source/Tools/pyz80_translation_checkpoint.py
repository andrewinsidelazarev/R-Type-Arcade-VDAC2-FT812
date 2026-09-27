#!/usr/bin/env python3
"""Build a compact, fail-closed cross-artifact translator checkpoint.

The full active call graph is intentionally large.  Development tools and
agents must not reopen every report merely to discover that reports belong to
different translator snapshots.  This module reads each report once, records
its byte hash, and checks only the explicit cross-stage bindings.  It does not
replace the stage validators and never promotes a report to ``live``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


CHECKPOINT_FORMAT = "rtype-python-translation-checkpoint-v1"
DEFAULT_OUTPUT = Path("Build/rtype_python_translation_checkpoint.json")
_HEX_256 = re.compile(r"[0-9a-f]{64}")
_REPORTS = {
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


class TranslationCheckpointError(RuntimeError):
    """A checkpoint document or required report is malformed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items()
            if key != "semantic_sha256"}


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _HEX_256.fullmatch(value) is not None


def _read_report(root: Path, name: str, relative: Path,
                 issues: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / relative
    try:
        raw = path.read_bytes()
    except OSError as exc:
        issues.append({
            "code": "PZCHK001", "stage": name,
            "detail": f"required report cannot be read: {relative.as_posix()}: {exc}",
        })
        return {}, {
            "path": relative.as_posix(), "present": False,
            "bytes": 0, "sha256": None,
        }
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        issues.append({
            "code": "PZCHK002", "stage": name,
            "detail": f"required report is not valid UTF-8 JSON: {exc}",
        })
        return {}, {
            "path": relative.as_posix(), "present": True,
            "bytes": len(raw), "sha256": _sha256(raw),
        }
    if not isinstance(value, dict):
        issues.append({
            "code": "PZCHK003", "stage": name,
            "detail": "required report root is not an object",
        })
        value = {}
    return value, {
        "path": relative.as_posix(), "present": True,
        "bytes": len(raw), "sha256": _sha256(raw),
    }


def _binding(issues: list[dict[str, str]], stage: str, field: str,
             actual: object, expected: object) -> dict[str, Any]:
    matches = _valid_sha(actual) and _valid_sha(expected) and actual == expected
    if not matches:
        issues.append({
            "code": "PZCHK010", "stage": stage,
            "detail": f"{field} does not match its prerequisite",
        })
    return {
        "field": field,
        "actual": actual if _valid_sha(actual) else None,
        "expected": expected if _valid_sha(expected) else None,
        "matches": matches,
    }


def analyze_translation_checkpoint(
        project_root: Path | str, *, report_directory: Path | None = None,
        ) -> dict[str, Any]:
    """Return a small correlation manifest for the current Build reports."""
    root = Path(project_root).resolve()
    issues: list[dict[str, str]] = []
    reports: dict[str, dict[str, Any]] = {}
    files: dict[str, dict[str, Any]] = {}
    for name, relative in _REPORTS.items():
        if report_directory is not None:
            relative = (report_directory / relative.name).resolve().relative_to(root)
        reports[name], files[name] = _read_report(root, name, relative, issues)

    graph = reports["active_call_graph"]
    lowering = reports["active_call_site_lowering"]
    call_abi = reports["whole_program_vm_call_abi"]
    vm = reports["whole_program_vm"]
    stack = reports["whole_program_vm_stack_bound"]
    graph_semantic = graph.get("semantic_sha256")
    lowering_semantic = lowering.get("semantic_sha256")
    call_abi_semantic = call_abi.get("semantic_sha256")
    vm_artifact_semantic = vm.get("artifact_semantic_sha256")
    vm_binding = vm.get("call_abi_binding")
    if not isinstance(vm_binding, dict):
        vm_binding = {}
        issues.append({
            "code": "PZCHK011", "stage": "whole_program_vm",
            "detail": "call_abi_binding is absent or malformed",
        })
    stack_binding = stack.get("binding")
    if not isinstance(stack_binding, dict):
        stack_binding = {}
        issues.append({
            "code": "PZCHK011", "stage": "whole_program_vm_stack_bound",
            "detail": "binding is absent or malformed",
        })
    target = vm.get("target_bytecode")
    if not isinstance(target, dict):
        target = {}
    proof = vm.get("host_proof")
    if not isinstance(proof, dict):
        proof = {}

    bindings = [
        _binding(issues, "active_call_site_lowering",
                 "active_call_graph_semantic_sha256",
                 lowering.get("active_call_graph_semantic_sha256"),
                 graph_semantic),
        _binding(issues, "whole_program_vm_call_abi",
                 "active_call_graph_semantic_sha256",
                 call_abi.get("active_call_graph_semantic_sha256"),
                 graph_semantic),
        _binding(issues, "whole_program_vm_call_abi",
                 "call_site_lowering_semantic_sha256",
                 call_abi.get("call_site_lowering_semantic_sha256"),
                 lowering_semantic),
        _binding(issues, "whole_program_vm",
                 "active_call_graph_semantic_sha256",
                 vm.get("active_call_graph_semantic_sha256"), graph_semantic),
        _binding(issues, "whole_program_vm",
                 "call_abi_binding.active_call_site_lowering_semantic_sha256",
                 vm_binding.get(
                     "active_call_site_lowering_semantic_sha256"),
                 lowering_semantic),
        _binding(issues, "whole_program_vm",
                 "call_abi_binding.whole_program_vm_call_abi_semantic_sha256",
                 vm_binding.get("whole_program_vm_call_abi_semantic_sha256"),
                 call_abi_semantic),
        _binding(issues, "whole_program_vm_stack_bound",
                 "binding.active_call_graph_semantic_sha256",
                 stack_binding.get("active_call_graph_semantic_sha256"),
                 graph_semantic),
        _binding(issues, "whole_program_vm_stack_bound",
                 "binding.artifact_semantic_sha256",
                 stack_binding.get("artifact_semantic_sha256"),
                 vm_artifact_semantic),
        _binding(issues, "whole_program_vm_stack_bound",
                 "binding.target_bytecode_sha256",
                 stack_binding.get("target_bytecode_sha256"),
                 target.get("sha256")),
        _binding(issues, "whole_program_vm_stack_bound",
                 "binding.proof_bytecode_sha256",
                 stack_binding.get("proof_bytecode_sha256"),
                 proof.get("sha256")),
    ]

    file_key = [{"stage": name, **files[name]} for name in sorted(files)]
    snapshot_sha256 = _sha256(_canonical(file_key))
    result: dict[str, Any] = {
        "format": CHECKPOINT_FORMAT,
        "coherent": not issues,
        "live_claim": False,
        "snapshot_sha256": snapshot_sha256,
        "stage_semantic_sha256": {
            "active_call_graph": graph_semantic if _valid_sha(
                graph_semantic) else None,
            "active_call_site_lowering": lowering_semantic if _valid_sha(
                lowering_semantic) else None,
            "whole_program_vm_call_abi": call_abi_semantic if _valid_sha(
                call_abi_semantic) else None,
            "whole_program_vm_artifact": vm_artifact_semantic if _valid_sha(
                vm_artifact_semantic) else None,
        },
        "report_files": file_key,
        "bindings": bindings,
        "issue_count": len(issues),
        "issues": issues,
        "proof_scope": {
            "cross_artifact_binding_only": True,
            "stage_validators_are_still_required": True,
            "never_promotes_live": True,
        },
    }
    result["semantic_sha256"] = _sha256(_canonical(
        _semantic_payload(result)))
    return result


def validate_translation_checkpoint(report: Mapping[str, Any]) -> None:
    if report.get("format") != CHECKPOINT_FORMAT:
        raise TranslationCheckpointError("PZCHK100: format mismatch")
    expected = report.get("semantic_sha256")
    if not _valid_sha(expected):
        raise TranslationCheckpointError("PZCHK101: semantic hash is absent")
    actual = _sha256(_canonical(_semantic_payload(report)))
    if actual != expected:
        raise TranslationCheckpointError("PZCHK102: semantic hash mismatch")
    if report.get("live_claim") is not False:
        raise TranslationCheckpointError("PZCHK103: checkpoint invented live")
    issues = report.get("issues")
    if (not isinstance(issues, list) or
            report.get("issue_count") != len(issues) or
            report.get("coherent") is not (len(issues) == 0)):
        raise TranslationCheckpointError("PZCHK104: issue census mismatch")


def write_translation_checkpoint(project_root: Path | str,
                                 output: Path | str = DEFAULT_OUTPUT, *,
                                 report_directory: Path | None = None,
                                 ) -> dict[str, Any]:
    root = Path(project_root).resolve()
    destination = Path(output)
    if not destination.is_absolute():
        destination = root / destination
    report = analyze_translation_checkpoint(root, report_directory=report_directory)
    validate_translation_checkpoint(report)
    rendered = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8") + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(rendered)
    os.replace(temporary, destination)
    if destination.read_bytes() != rendered:
        raise TranslationCheckpointError("PZCHK105: checkpoint write differs")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-incoherent", action="store_true",
        help="write/print an incoherent checkpoint but return success")
    args = parser.parse_args()
    report = write_translation_checkpoint(args.project_root, args.output)
    print(json.dumps({
        "format": report["format"],
        "coherent": report["coherent"],
        "snapshot_sha256": report["snapshot_sha256"],
        "issue_count": report["issue_count"],
        "issues": report["issues"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["coherent"] or args.allow_incoherent else 1


if __name__ == "__main__":
    raise SystemExit(main())
