from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pyz80_translation_checkpoint import (
    CHECKPOINT_FORMAT,
    TranslationCheckpointError,
    analyze_translation_checkpoint,
    validate_translation_checkpoint,
    write_translation_checkpoint,
)


SHA = {letter: letter * 64 for letter in "abcdef"}


def _write(root: Path, name: str, value: object) -> None:
    path = root / "Build" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(root, "rtype_python_active_call_graph_status.json", {
        "semantic_sha256": SHA["a"]})
    _write(root, "rtype_python_active_call_site_lowering_status.json", {
        "semantic_sha256": SHA["b"],
        "active_call_graph_semantic_sha256": SHA["a"],
    })
    _write(root, "rtype_python_whole_program_vm_call_abi_status.json", {
        "semantic_sha256": SHA["c"],
        "active_call_graph_semantic_sha256": SHA["a"],
        "call_site_lowering_semantic_sha256": SHA["b"],
    })
    _write(root, "rtype_python_whole_program_vm_status.json", {
        "artifact_semantic_sha256": SHA["d"],
        "active_call_graph_semantic_sha256": SHA["a"],
        "call_abi_binding": {
            "active_call_site_lowering_semantic_sha256": SHA["b"],
            "whole_program_vm_call_abi_semantic_sha256": SHA["c"],
        },
        "target_bytecode": {"sha256": SHA["e"]},
        "host_proof": {"sha256": SHA["f"]},
    })
    _write(root, "rtype_python_whole_program_vm_stack_bound_status.json", {
        "binding": {
            "active_call_graph_semantic_sha256": SHA["a"],
            "artifact_semantic_sha256": SHA["d"],
            "target_bytecode_sha256": SHA["e"],
            "proof_bytecode_sha256": SHA["f"],
        },
    })


class TranslationCheckpointTests(unittest.TestCase):
    def test_coherent_snapshot_is_compact_deterministic_and_never_live(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyz80-checkpoint-") as raw:
            root = Path(raw)
            _fixture(root)
            first = analyze_translation_checkpoint(root)
            second = analyze_translation_checkpoint(root)
            self.assertEqual(first, second)
            self.assertEqual(first["format"], CHECKPOINT_FORMAT)
            self.assertTrue(first["coherent"])
            self.assertFalse(first["live_claim"])
            self.assertEqual(first["issue_count"], 0)
            self.assertTrue(all(row["matches"] for row in first["bindings"]))
            validate_translation_checkpoint(first)
            output = root / "Build" / "checkpoint.json"
            self.assertEqual(write_translation_checkpoint(root, output), first)
            self.assertLess(output.stat().st_size, 8192)

    def test_cross_snapshot_mix_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyz80-checkpoint-") as raw:
            root = Path(raw)
            _fixture(root)
            vm_path = root / "Build/rtype_python_whole_program_vm_status.json"
            vm = json.loads(vm_path.read_text(encoding="utf-8"))
            vm["active_call_graph_semantic_sha256"] = "9" * 64
            vm_path.write_text(json.dumps(vm), encoding="utf-8")
            report = analyze_translation_checkpoint(root)
            self.assertFalse(report["coherent"])
            self.assertEqual(report["issue_count"], 1)
            self.assertEqual(report["issues"][0]["code"], "PZCHK010")
            self.assertEqual(report["issues"][0]["stage"], "whole_program_vm")

    def test_missing_report_and_checkpoint_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyz80-checkpoint-") as raw:
            root = Path(raw)
            _fixture(root)
            (root / "Build/rtype_python_whole_program_vm_status.json").unlink()
            report = analyze_translation_checkpoint(root)
            self.assertFalse(report["coherent"])
            self.assertIn("PZCHK001", [row["code"] for row in report["issues"]])
            damaged = copy.deepcopy(report)
            damaged["issue_count"] += 1
            with self.assertRaisesRegex(TranslationCheckpointError, "PZCHK102"):
                validate_translation_checkpoint(damaged)


if __name__ == "__main__":
    unittest.main()

