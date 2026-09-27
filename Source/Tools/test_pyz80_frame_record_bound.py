#!/usr/bin/env python3
"""Focused fail-closed tests for the active frame-record bound analyser."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pyz80_compiler.frame_record_bound import (
    FRAME_RECORD_BOUND_FORMAT,
    FrameRecordBoundError,
    analyze_active_frame_record_bound,
)


ROOT = Path(__file__).resolve().parents[2]
ENEMIES = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"


class FrameRecordBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ENEMIES.read_bytes().decode("utf-8")
        cls.report = analyze_active_frame_record_bound(ROOT)
        cls.value = cls.report.as_dict()

    def test_active_result_is_a_conservative_not_copied_limit(self) -> None:
        value = self.value
        self.assertEqual(value["format"], FRAME_RECORD_BOUND_FORMAT)
        self.assertEqual(
            value["status"], "READY_CONSERVATIVE_REACHABLE_STATE_BOUND")
        self.assertTrue(value["proof_complete"])
        self.assertEqual(value["bound_kind"], "conservative_upper_bound")
        self.assertIsNone(value["exact_max_records"])
        self.assertEqual(value["certified_frame_max_records"], 228)
        self.assertTrue(value["can_certify_frame_budget"])
        self.assertTrue(value["finite_abstract_bound_proved"])
        self.assertEqual(value["finite_abstract_upper_bound_records"], 228)
        stream = value["streaming_transport"]
        self.assertEqual(stream["chunk_capacity_records"], 32)
        self.assertFalse(stream["record_array_required"])
        self.assertFalse(stream["whole_frame_limited_to_one_chunk"])
        self.assertFalse(stream["memory_safety_requires_exact_frame_max"])
        self.assertFalse(stream["ram_dl_and_timing_require_exact_frame_max"])
        self.assertTrue(stream["ram_dl_and_timing_require_sound_upper_bound"])

    def test_active_noncanonical_program_and_sources_are_bound(self) -> None:
        source = self.value["source_program"]
        self.assertEqual(source, {
            "launcher": "run_python.cmd",
            "module": "rtype_port.app",
            "canonical": False,
        })
        bindings = self.value["source_bindings"]
        self.assertEqual(set(bindings), {
            "run_python.cmd",
            "Source/Python/rtype_port/app.py",
            "Source/Python/rtype_port/game.py",
            "Source/Python/rtype_port/enemies.py",
        })
        self.assertTrue(all(len(value) == 64 for value in bindings.values()))

    def test_pool_ceiling_is_ast_derived_and_checkpoint_is_accounted(self) -> None:
        pool = self.value["object_pool"]
        self.assertEqual(pool["slot_count"], 96)
        self.assertEqual(pool["reserved_sentinel_count"], 2)
        self.assertEqual(pool["allocatable_record_count"], 94)
        self.assertEqual(pool["checkpoint_free_count"], 66)
        self.assertEqual(pool["checkpoint_allocated_count"], 30)
        self.assertEqual(pool["checkpoint_accounted_slots"], 30)
        self.assertEqual(len(pool["enemy_list_mutations"]), 6)

    def test_34_action_ir_produces_exact_snapshot_equation(self) -> None:
        plan = self.value["draw_plan"]
        self.assertEqual(plan["record_action_count"], 34)
        equation = plan["exact_counter_equation"]
        self.assertEqual(equation["object_action_count"], 33)
        self.assertEqual(equation["transient_records_per_tuple"], 1)
        self.assertEqual(equation["object_action_ordinals"], list(range(33)))
        self.assertEqual(equation["transient_action_ordinals"], [33])
        self.assertTrue(equation["exact_for_every_concrete_snapshot"])

    def test_per_class_multiplicity_comes_from_ir_and_class_graph(self) -> None:
        multiplicity = self.value["object_multiplicity"]
        self.assertEqual(multiplicity["max_records_per_pool_object"], 8)
        self.assertEqual(multiplicity["maximizer_classes"], ["FixedLarge6E9B"])
        self.assertEqual(multiplicity["pool_only_safe_object_upper_bound"], 752)
        self.assertFalse(multiplicity["is_live_reachability_bound"])
        self.assertEqual(
            multiplicity["source_derived_abstract_upper_bound"], 206)
        by_name = {item["class_name"]: item
                   for item in multiplicity["classes"]}
        self.assertEqual(by_name["FixedLarge6E9B"]["action_ordinals"],
                         [0, 25, 26, 27, 28, 29, 30, 31])
        self.assertEqual(by_name["MultipartA71DBody"]["max_records_per_object"],
                         6)

    def test_event_and_scheduler_facts_do_not_claim_occupancy(self) -> None:
        facts = self.value["event_scheduler"]
        self.assertTrue(facts["one_event_dispatch_site_per_world_update"])
        self.assertEqual(facts["event_pointer_step_bytes"], 4)
        self.assertEqual(set(facts["stage_event_record_counts"]),
                         {str(stage) for stage in range(1, 9)})
        self.assertEqual(facts["scheduler_snapshot_count"], 1)
        self.assertEqual(facts["pending_same_pass_update_sites"], 1)
        self.assertIn("do not by themselves", facts["proved"])

    def test_transients_have_finite_but_not_exact_simultaneous_bound(self) -> None:
        transients = self.value["transients"]
        self.assertTrue(transients["cleared_at_start_of_world_update"])
        self.assertEqual(transients["producer_count"], 3)
        self.assertEqual(len(transients["emitter_append_lines"]), 1)
        self.assertIsNone(transients["exact_per_frame_bound"])
        self.assertEqual(transients["source_derived_finite_upper_bound"], 22)
        self.assertEqual(self.value["blockers"], [])
        gaps = {item["code"]: item
                for item in self.value["optional_tightening_gaps"]}
        self.assertEqual(set(gaps), {"PZFRB101", "PZFRB102"})
        self.assertIn("same-update", gaps["PZFRB102"]["missing_invariant"])

    def test_abstract_reachability_is_a_subproof_not_an_exact_maximum(self) -> None:
        proof = self.value["abstract_reachability"]
        self.assertEqual(proof["status"], "PROVED_FINITE_ABSTRACT_BOUND")
        self.assertTrue(proof["proof_complete_for_finiteness"])
        self.assertFalse(proof["proof_complete_for_exact_maximum"])
        self.assertEqual(proof["object_records"]["finite_upper_bound"], 206)
        self.assertEqual(
            proof["transient_sprites"]["finite_per_frame_upper_bound"], 22)
        self.assertEqual(proof["frame_records"]["finite_upper_bound"], 228)
        self.assertIsNone(proof["frame_records"]["exact_maximum"])
        self.assertFalse(proof["frame_records"]["eligible_as_exact_frame_max"])

    def test_active_app_order_names_the_exact_bound_snapshot(self) -> None:
        order = self.value["active_frame_order"]
        self.assertLess(order["app_update_line"], order["app_render_line"])
        self.assertEqual(
            order["snapshot"],
            "after Game.update and before M72EnemyWorld.draw")

    def test_json_is_deterministic_and_detached(self) -> None:
        encoded = self.report.to_json()
        self.assertEqual(encoded, self.report.to_json())
        parsed = json.loads(encoded)
        self.assertEqual(parsed, self.value)
        parsed["streaming_transport"]["chunk_capacity_records"] = 7
        self.assertEqual(
            self.report.as_dict()["streaming_transport"]
            ["chunk_capacity_records"], 32)

    def test_pool_size_mutation_is_rederived_not_stale(self) -> None:
        old = "SLOTS = tuple(range(0x0540, 0x1D40, 0x40))"
        new = "SLOTS = tuple(range(0x0540, 0x1D80, 0x40))"
        self.assertIn(old, self.source)
        # The checkpoint table accounts the original occupied set.  Adding a
        # new free slot must be reflected in that finite table too; otherwise
        # the checkpoint accounting correctly rejects the source.  Mutate both
        # facts to exercise re-derivation rather than a pinned 96/94 constant.
        mutated = self.source.replace(old, new, 1)
        marker = "    0x0BC0, 0x0B80,\n)"
        self.assertIn(marker, mutated)
        mutated = mutated.replace(marker, "    0x0BC0, 0x0B80, 0x1D40,\n)", 1)
        report = analyze_active_frame_record_bound(
            ROOT, enemy_source_override=mutated).as_dict()
        self.assertEqual(report["object_pool"]["slot_count"], 97)
        self.assertEqual(report["object_pool"]["allocatable_record_count"], 95)
        self.assertEqual(
            report["object_multiplicity"]["pool_only_safe_object_upper_bound"],
            760)
        self.assertEqual(
            report["finite_abstract_upper_bound_records"], 230)
        self.assertEqual(report["certified_frame_max_records"], 230)
        self.assertIsNone(report["exact_max_records"])

    def test_unsupported_pool_shape_fails_closed(self) -> None:
        old = "SLOTS = tuple(range(0x0540, 0x1D40, 0x40))"
        self.assertIn(old, self.source)
        mutated = self.source.replace(
            old, "SLOTS = list(range(0x0540, 0x1D40, 0x40))", 1)
        with self.assertRaises(FrameRecordBoundError) as caught:
            analyze_active_frame_record_bound(
                ROOT, enemy_source_override=mutated)
        self.assertEqual(caught.exception.code, "PZFRB005")

    def test_build_gates_record_bound_before_assets_assembler_and_spg(
            self) -> None:
        build = (ROOT / "build.cmd").read_text(encoding="utf-8")
        translator = build.index("rtype_python_translator.py")
        status = build.index(
            "check_frame_record_bound.py --status --output ")
        gate = build.index(
            '"%PYTHON%" Source\\Tools\\check_frame_record_bound.py\n')
        assets = build.index("check_rtype_python_assets.py")
        frame_budget = build.index("check_frame_fragment_budget.py")
        assembler = build.index(
            '"%SJASMPLUS%" Source\\ASM\\main.asm')
        spgbld = build.index('"%SPGBLD%" -b')
        deploy = build.index('copy /y "Build\\rtype_vdac2.spg"')
        positions = (
            translator, status, gate, assets, frame_budget,
            assembler, spgbld, deploy)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertEqual(len(set(positions)), len(positions))
        self.assertEqual(
            build.count(
                '"%PYTHON%" Source\\Tools\\check_frame_record_bound.py\n'),
            1)

    def test_new_enemy_list_mutation_fails_closed(self) -> None:
        marker = "        self.enemies: list[Enemy] = []\n"
        self.assertIn(marker, self.source)
        mutated = self.source.replace(
            marker, marker + "        self.enemies.append(Enemy('x', 0, 0, 0, 0))\n",
            1)
        with self.assertRaises(FrameRecordBoundError) as caught:
            analyze_active_frame_record_bound(
                ROOT, enemy_source_override=mutated)
        self.assertEqual(caught.exception.code, "PZFRB009")


if __name__ == "__main__":
    unittest.main(verbosity=2)
