from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtype_python_translator as translator
from pyz80_compiler.sprite_working_sets import (
    MissingInvariant,
    SchedulerFacts,
    SpriteWorkingSetError,
    WorkingSetPlan,
)


def _blocked_plan(coverage: SimpleNamespace) -> WorkingSetPlan:
    return WorkingSetPlan(
        root_module=coverage.root_module,
        coverage_source_hashes=coverage.source_hashes,
        rom_sha256=coverage.rom_sha256,
        scheduler=SchedulerFacts(
            source_sha256="1" * 64,
            object_pool_slots=96,
            initially_allocatable_slots=94,
            maximum_event_dispatches_per_update=1,
            retains_live_objects_across_updates=True,
            appends_event_objects_to_existing_list=True,
            event_specific_lifetime_bounds=False,
        ),
        common_domains=(),
        class_domains=(),
        event_packs=(),
        ambient_class_domain_ids=(),
        unique_pack_measurements=(),
        proven_resident_combinations=(),
        missing_invariants=(MissingInvariant(
            code="PZSW102",
            scope="stage-object-lifetimes",
            required_fact="last draw",
            reason="not present in coverage",
            source_symbols=("rtype_port.enemies.M72EnemyWorld.update",),
        ),),
    )


class TranslatorWorkingSetIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coverage = SimpleNamespace(
            root_module="rtype_port.app",
            source_hashes=(("rtype_port.enemies", "2" * 64),),
            rom_sha256="3" * 64,
            unresolved_domains=(),
        )

    def test_report_is_stably_source_bound_and_preserves_blocked_status(
            self) -> None:
        plan = _blocked_plan(self.coverage)
        with mock.patch.object(
                translator, "plan_sprite_working_sets", return_value=plan):
            first = translator.sprite_working_set_report(
                self.coverage, Path("unused"))
            second = translator.sprite_working_set_report(
                self.coverage, Path("unused"))
        self.assertEqual(first, second)
        self.assertFalse(first["ready"])
        self.assertEqual(first["status"], "BLOCKED_MISSING_LIFETIME_PROOF")
        self.assertEqual(first["rom_sha256"], self.coverage.rom_sha256)
        self.assertEqual(len(first["source_binding_sha256"]), 64)
        reported_hash = first.pop("analysis_sha256")
        stable_json = json.dumps(
            first, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            reported_hash,
            hashlib.sha256(stable_json.encode("utf-8")).hexdigest(),
        )

    def test_working_set_failure_precedes_first_generator_write(self) -> None:
        with (mock.patch.object(
                  translator, "analyze_sprite_coverage",
                  return_value=self.coverage),
              mock.patch.object(
                  translator, "sprite_working_set_report",
                  side_effect=SpriteWorkingSetError("no lifetime proof")),
              mock.patch.object(
                  translator, "emit_draw_c_backend_stage") as first_writer):
            with self.assertRaisesRegex(
                    SpriteWorkingSetError, "no lifetime proof"):
                translator._translate_untransactional(False)
        first_writer.assert_not_called()

    def test_report_write_is_after_analysis_and_status_path_is_transactional(
            self) -> None:
        source = inspect.getsource(translator._translate_untransactional)
        analysis = source.index(
            "sprite_working_sets = sprite_working_set_report")
        first_write = source.index(
            "draw_c_backend = emit_draw_c_backend_stage")
        report_key = source.index(
            '"sprite_working_sets": sprite_working_sets')
        status_write = source.index(
            "OUT_SPRITE_WORKING_SET_STATUS.write_text")
        self.assertLess(analysis, first_write)
        self.assertLess(analysis, report_key)
        self.assertLess(report_key, status_write)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files, _directories = translator.translator_generation_surfaces(root)
            expected = (
                root / "Build" /
                "rtype_python_sprite_working_set_status.json").resolve()
            self.assertIn(expected, files)
            self.assertFalse(any(
                path.name == "rtype_python_sprite_working_set_status.json" and
                "Source" in path.parts
                for path in files
            ))

    def test_cli_catches_working_set_error(self) -> None:
        with (mock.patch.object(
                  translator, "translate",
                  side_effect=SpriteWorkingSetError("blocked proof")),
              mock.patch.object(sys, "argv", ["rtype_python_translator.py"]),
              mock.patch("builtins.print") as output):
            self.assertEqual(translator.main(), 1)
        output.assert_called_once()
        self.assertIn("blocked proof", output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
