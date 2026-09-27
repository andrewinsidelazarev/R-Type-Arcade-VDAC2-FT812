from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from generate_pzvt_target_adapters import generate
from pyz80_translation_checkpoint import write_translation_checkpoint
from rebuild_whole_program_backend import (
    FORMAT, INPUT_REPORTS, MANIFEST_NAME, OUTPUT_NAMES, _record, _semantic, _valid_cache,
    _frontend_directory, _refresh_frontend,
)
from test_pyz80_translation_checkpoint import _fixture


class BackendRebuildTests(unittest.TestCase):
    def test_frontend_selection_rejects_partial_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="pz-front-select-") as raw:
            root = Path(raw).resolve()
            self.assertEqual(_frontend_directory(root), root / "Build")
            output = root / "Build/WholeProgramFrontend"
            output.mkdir(parents=True)
            (output / INPUT_REPORTS[0]).write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                _frontend_directory(root)
            for name in INPUT_REPORTS[1:]:
                (output / name).write_text("{}")
            self.assertEqual(_frontend_directory(root), output)

    def test_frontend_refresh_recomputes_instead_of_resigning_cached_ir(self):
        with tempfile.TemporaryDirectory(prefix="pz-front-refresh-") as raw:
            root = Path(raw).resolve()
            with (patch("rebuild_whole_program_backend._dependencies", return_value=[]) as deps,
                  patch("rebuild_whole_program_backend.build_mutation_hook_ir", return_value="hooks"),
                  patch("rebuild_whole_program_backend.lower_active_object_store_ir", return_value="stores") as stores,
                  patch("rebuild_whole_program_backend.analyze_active_call_graph", return_value={"fresh": "graph"}) as graph,
                  patch("rebuild_whole_program_backend.analyze_active_call_site_lowering", return_value={"fresh": "calls"}) as calls,
                  patch("rebuild_whole_program_backend.object_store_ir_report", return_value={"fresh": "stores"})):
                _refresh_frontend(root)
                stores.assert_called_once_with(root, hook_plan="hooks")
                graph.assert_called_once_with(root, hook_plan="hooks", object_store_module="stores")
                calls.assert_called_once_with(root, active_graph={"fresh": "graph"})
                self.assertEqual(deps.call_count, 2)
            output = root / "Build/WholeProgramFrontend"
            self.assertEqual([json.loads((output / name).read_bytes()) for name in INPUT_REPORTS],
                             [{"fresh": value} for value in ("graph", "calls", "stores")])

    def test_reuse_rejects_changed_inputs_output_or_manifest(self):
        with tempfile.TemporaryDirectory(prefix="pz-backend-cache-") as raw:
            root = Path(raw).resolve()
            output = root / "Build/WholeProgramBackend"
            output.mkdir(parents=True)
            for name in OUTPUT_NAMES:
                (output / name).write_bytes(name.encode())
            inputs = [{"path": "source.py", "bytes": 3, "sha256": "a" * 64}]
            report = {"format": FORMAT, "live": False, "inputs": inputs,
                      "outputs": [_record(root, output / name) for name in OUTPUT_NAMES]}
            report["semantic_sha256"] = _semantic(report)
            manifest = output / MANIFEST_NAME
            manifest.write_text(json.dumps(report))
            self.assertIsNotNone(_valid_cache(root, output, inputs))
            changed = copy.deepcopy(inputs)
            changed[0]["sha256"] = "b" * 64
            self.assertIsNone(_valid_cache(root, output, changed))
            payload = (output / OUTPUT_NAMES[0]).read_bytes()
            (output / OUTPUT_NAMES[0]).write_bytes(payload + b"changed")
            self.assertIsNone(_valid_cache(root, output, inputs))
            (output / OUTPUT_NAMES[0]).write_bytes(payload)
            report["outputs"] = []
            report["semantic_sha256"] = _semantic(report)
            manifest.write_text(json.dumps(report))
            self.assertIsNone(_valid_cache(root, output, inputs))

    def test_candidate_checkpoint_uses_selected_bundle(self):
        with tempfile.TemporaryDirectory(prefix="pz-backend-checkpoint-") as raw:
            root = Path(raw).resolve()
            _fixture(root)
            output = root / "Build/WholeProgramBackend"
            output.mkdir()
            for path in (root / "Build").glob("*.json"):
                (output / path.name).write_bytes(path.read_bytes())
            # Main generation changes must not contaminate this snapshot.
            (root / "Build/rtype_python_active_call_graph_status.json").write_text("{}")
            checkpoint = write_translation_checkpoint(
                root, output / "rtype_python_translation_checkpoint.json",
                report_directory=output)
            self.assertTrue(checkpoint["coherent"])
            self.assertTrue(all(record["path"].startswith("Build/WholeProgramBackend/")
                                for record in checkpoint["report_files"]))

    def test_adapter_generator_rejects_stale_coherent_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="pz-backend-adapters-") as raw:
            root = Path(raw).resolve()
            _fixture(root)
            build = root / "Build"
            (build / "rtype_python_whole_program_vm.bin").write_bytes(b"not-reached")
            write_translation_checkpoint(root)
            (build / "rtype_python_active_call_graph_status.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "stale checkpoint"):
                generate(root, build_directory=build, source_directory=build)
            self.assertFalse((build / "pyz80_target_adapter_plan_generated.c").exists())


if __name__ == "__main__":
    unittest.main()
