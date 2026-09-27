#!/usr/bin/env python3
"""Focused fail-closed tests for the abstract reachability sub-proof."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pyz80_compiler.frame_record_bound import analyze_active_frame_record_bound
from pyz80_compiler.frame_record_reachability import (
    FRAME_RECORD_REACHABILITY_FORMAT,
    FrameRecordReachabilityError,
    analyze_frame_record_reachability,
)


ROOT = Path(__file__).resolve().parents[2]
ENEMIES = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
GAME = ROOT / "Source" / "Python" / "rtype_port" / "game.py"


class FrameRecordReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.enemy_source = ENEMIES.read_text(encoding="utf-8")
        cls.game_source = GAME.read_text(encoding="utf-8")
        base = analyze_active_frame_record_bound(ROOT).as_dict()
        cls.capacity = base["object_pool"]["allocatable_record_count"]
        cls.pool_hash = base["abstract_reachability"]["source_bindings"][
            "pool_invariant_ast"]
        cls.multiplicities = {
            item["class_name"]: item["max_records_per_object"]
            for item in base["object_multiplicity"]["classes"]
        }
        cls.report = analyze_frame_record_reachability(
            ROOT,
            enemy_source=cls.enemy_source,
            game_source=cls.game_source,
            pool_record_capacity=cls.capacity,
            class_multiplicities=cls.multiplicities,
            pool_invariant_sha256=cls.pool_hash,
        )
        cls.value = cls.report.as_dict()

    def _analyse(self, enemy_source: str):
        return analyze_frame_record_reachability(
            ROOT,
            enemy_source=enemy_source,
            game_source=self.game_source,
            pool_record_capacity=self.capacity,
            class_multiplicities=self.multiplicities,
            pool_invariant_sha256=self.pool_hash,
        )

    def test_finite_composition_is_derived_but_not_exact(self) -> None:
        value = self.value
        self.assertEqual(value["format"], FRAME_RECORD_REACHABILITY_FORMAT)
        self.assertEqual(value["status"], "PROVED_FINITE_ABSTRACT_BOUND")
        self.assertTrue(value["proof_complete_for_finiteness"])
        self.assertTrue(
            value["proof_complete_for_conservative_certification"])
        self.assertFalse(value["proof_complete_for_exact_maximum"])
        objects = value["object_records"]
        self.assertEqual(objects["pool_record_capacity"], 94)
        self.assertEqual(objects["unbounded_class_baseline_records"], 2)
        self.assertEqual(objects["base_pool_contribution"], 188)
        self.assertEqual(objects["premium_contribution"], 18)
        self.assertEqual(objects["finite_upper_bound"], 206)
        self.assertEqual(value["transient_sprites"][
            "finite_per_frame_upper_bound"], 22)
        self.assertEqual(value["frame_records"]["finite_upper_bound"], 228)
        self.assertEqual(
            value["frame_records"]["bound_kind"], "conservative_upper_bound")
        self.assertIsNone(value["frame_records"]["exact_maximum"])
        self.assertFalse(value["frame_records"]["eligible_as_exact_frame_max"])
        self.assertTrue(
            value["frame_records"]["eligible_as_conservative_frame_max"])
        self.assertTrue(
            value["frame_records"]["sound_for_ram_dl_and_worst_case_timing"])

    def test_rom_cursor_is_finite_acyclic_and_source_bound(self) -> None:
        cursor = self.value["event_cursor"]
        self.assertTrue(cursor["acyclic"])
        self.assertEqual(cursor["transition_edges"], {
            "1": 2, "2": 3, "3": 4, "4": 5,
            "5": 6, "6": 7, "7": 8,
        })
        self.assertEqual(cursor["total_distinct_event_records"], 788)
        self.assertTrue(cursor["checkpoint_cursor_targets_fresh_world"])
        bindings = self.value["source_bindings"]
        self.assertEqual(len(bindings[cursor["rom_path"]]), 64)

    def test_high_multiplicity_premiums_have_finite_spawn_origins(self) -> None:
        premiums = {
            item["class_name"]: item
            for item in self.value["object_records"]["bounded_premium_classes"]
        }
        self.assertEqual(set(premiums), {
            "FixedLarge6E9B", "MultipartA71DBody"})
        self.assertEqual(
            premiums["FixedLarge6E9B"]["lifetime_instance_upper_bound"], 1)
        self.assertEqual(
            premiums["MultipartA71DBody"]["lifetime_instance_upper_bound"], 3)
        methods = {
            (item["owner_class"], item["method"])
            for item in self.value["spawn_reachability"][
                "one_shot_spawn_methods"]
        }
        self.assertIn(("MultipartA71DController", "_spawn"), methods)
        self.assertIn(("DobkeratopsRoot", "_spawn_parts"), methods)
        linearity = self.value["spawn_reachability"][
            "pending_identity_linearity"]
        self.assertEqual(linearity["pending_append_site_count"], 83)
        self.assertTrue(linearity["duplicate_publication_rejected"])
        self.assertEqual(len(linearity["inventory_sha256"]), 64)

    def test_transient_bound_uses_lifetime_instances_and_closed_states(self) -> None:
        transient = self.value["transient_sprites"]
        self.assertEqual(transient["producer_site_count"], 3)
        self.assertTrue(transient["shared_helper_kills_owner"])
        self.assertEqual(transient["lifetime_emissions_per_instance"], {
            "DobkeratopsBack": 2,
            "DobkeratopsBody": 1,
            "DobkeratopsTentacle": 1,
        })
        self.assertEqual(transient["lifetime_instance_upper_bounds"], {
            "DobkeratopsBack": 1,
            "DobkeratopsBody": 1,
            "DobkeratopsTentacle": 19,
        })
        self.assertEqual(
            transient["lifetime_emission_contributions"], {
                "DobkeratopsBack": 2,
                "DobkeratopsBody": 1,
                "DobkeratopsTentacle": 19,
            })
        self.assertIsNone(transient["exact_simultaneous_maximum"])

    def test_reopening_one_shot_root_guard_fails_closed(self) -> None:
        old = "        self.initialized = True\n\n    def _begin_end("
        new = "        self.initialized = False\n\n    def _begin_end("
        self.assertIn(old, self.enemy_source)
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            self._analyse(self.enemy_source.replace(old, new, 1))
        self.assertEqual(caught.exception.code, "PZFRR014")

    def test_unbounded_high_multiplicity_constructor_is_not_pool_max(self) -> None:
        marker = (
            "    def update(self, world: \"M72EnemyWorld\", "
            "foreground_delta: int) -> None:\n"
            "        self.x = _u16(self.x + foreground_delta)\n")
        self.assertIn(marker, self.enemy_source)
        mutation = marker + (
            "        world.pending.append(FixedLarge6E9B(world))\n")
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            self._analyse(self.enemy_source.replace(marker, mutation, 1))
        self.assertEqual(caught.exception.code, "PZFRR016")

    def test_premium_constructor_alias_fails_closed(self) -> None:
        marker = "\n\nclass Spawner875DChild(Enemy):\n"
        self.assertIn(marker, self.enemy_source)
        mutation = "\n\nFixedLargeAlias = FixedLarge6E9B" + marker
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            self._analyse(self.enemy_source.replace(marker, mutation, 1))
        self.assertEqual(caught.exception.code, "PZFRR012")

    def test_duplicate_pending_identity_fails_closed(self) -> None:
        old = "            world.pending.append(body)\n"
        new = old + old
        self.assertEqual(self.enemy_source.count(old), 1)
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            self._analyse(self.enemy_source.replace(old, new, 1))
        self.assertEqual(caught.exception.code, "PZFRR012")

    def test_caller_cannot_override_source_derived_pool_capacity(self) -> None:
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            analyze_frame_record_reachability(
                ROOT,
                enemy_source=self.enemy_source,
                game_source=self.game_source,
                pool_record_capacity=self.capacity - 1,
                class_multiplicities=self.multiplicities,
                pool_invariant_sha256=self.pool_hash,
            )
        self.assertEqual(caught.exception.code, "PZFRR015")

    def test_transient_clear_removal_fails_closed(self) -> None:
        old = "        self.transient_sprites.clear()\n"
        new = "        self.transient_sprites = []\n"
        self.assertEqual(self.enemy_source.count(old), 1)
        with self.assertRaises(FrameRecordReachabilityError) as caught:
            self._analyse(self.enemy_source.replace(old, new, 1))
        self.assertEqual(caught.exception.code, "PZFRR013")

    def test_json_is_deterministic_and_detached(self) -> None:
        self.assertEqual(self.report.to_json(), self.report.to_json())
        parsed = json.loads(self.report.to_json())
        self.assertEqual(parsed, self.value)
        parsed["frame_records"]["finite_upper_bound"] = 1
        self.assertEqual(
            self.report.as_dict()["frame_records"]["finite_upper_bound"], 228)


if __name__ == "__main__":
    unittest.main(verbosity=2)
