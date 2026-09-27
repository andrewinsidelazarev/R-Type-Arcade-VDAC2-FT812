#!/usr/bin/env python3
"""Focused tests for weighted sprite-fragment envelope construction."""

from __future__ import annotations

import copy
import unittest

from pyz80_compiler.frame_sprite_fragment_envelope import (
    FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT,
    FrameSpriteFragmentEnvelopeError,
    TemplateMetric,
    build_frame_sprite_fragment_envelope,
)


def _bound() -> dict[str, object]:
    return {
        "format": "pyz80.frame-draw-record-bound.v2",
        "status": "READY_CONSERVATIVE_REACHABLE_STATE_BOUND",
        "proof_complete": True,
        "can_certify_frame_budget": True,
        "bound_kind": "conservative_upper_bound",
        "certified_frame_max_records": 5,
        "object_pool": {"allocatable_record_count": 2},
        "object_multiplicity": {"classes": [
            {
                "class_name": "A", "max_records_per_object": 1,
                "action_ordinals": [0], "witness_fields": {"state": "a"},
            },
            {
                "class_name": "B", "max_records_per_object": 2,
                "action_ordinals": [0, 1], "witness_fields": {"state": "b"},
            },
        ]},
        "abstract_reachability": {
            "object_records": {"finite_upper_bound": 3},
            "spawn_reachability": {
                "finite_class_instance_upper_bounds": {"B": 1}},
            "transient_sprites": {
                "finite_per_frame_upper_bound": 2,
                "lifetime_emission_contributions": {"T": 2},
            },
        },
    }


def _plan() -> dict[str, object]:
    return {"actions": [{"ordinal": 0}, {"ordinal": 1}, {"ordinal": 2}]}


def _domains() -> dict[str, tuple[tuple[int, int], ...]]:
    return {
        "A": ((0x0101, 0x1000),),
        "B": ((0x0102, 0x2000),),
        "T": ((0x0003, 0x3000),),
    }


def _metrics() -> dict[tuple[int, int], TemplateMetric]:
    rows = (
        TemplateMetric(0x0101, 0x1000, 4, 3, 1, (4,) * 25),
        TemplateMetric(0x0102, 0x2000, 10, 7, 4, (10,) * 25),
        TemplateMetric(0x0003, 0x3000, 6, 5, 2, (6,) * 25),
    )
    return {item.key: item for item in rows}


class FrameSpriteFragmentEnvelopeTests(unittest.TestCase):
    def test_weighted_bound_uses_pool_baseline_and_finite_premium(self) -> None:
        report = build_frame_sprite_fragment_envelope(
            _bound(), _plan(), _domains(), _metrics(),
            transient_template_keys=_domains(), chunk_capacity=2).as_dict()
        self.assertEqual(
            report["format"], FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT)
        self.assertEqual(
            report["status"],
            "READY_CONSERVATIVE_ENVELOPE_PREPUBLICATION_BLOCKED")
        self.assertTrue(report["proof_complete"])
        self.assertEqual(report["record_envelope"]["max_chunks"], 3)
        weighted = report["weighted_display_list"]
        # A: 2*4 baseline. B: one (2*10-4) premium. T: 2*6.
        self.assertEqual(weighted["object_cmd_append_expanded_words"], 24)
        self.assertEqual(weighted["transient_cmd_append_expanded_words"], 12)
        self.assertEqual(weighted["max_cmd_append_expanded_words"], 36)
        self.assertEqual(weighted["max_fragment_expanded_dl_words"], 85)
        self.assertFalse(report["frame_budget_contract_pass"])
        self.assertFalse(report["prepublication_certified"])
        self.assertFalse(report["atomic_commit_certified"])
        self.assertFalse(report["live_eligible"])
        self.assertFalse(
            report["proof_scope"]["uses_global_template_max_times_frame_records"])

    def test_raster_is_768_line_conservative_envelope(self) -> None:
        report = build_frame_sprite_fragment_envelope(
            _bound(), _plan(), _domains(), _metrics(),
            transient_template_keys=_domains()).as_dict()
        raster = report["raster_envelope"]
        self.assertEqual(raster["height"], 768)
        self.assertEqual(len(raster["max_raster_cycles_by_line"]), 768)
        # A: 2*3. B: one (2*7-3) premium. T: 2*5.
        self.assertEqual(set(raster["max_raster_cycles_by_line"]), {27})
        self.assertEqual(raster["worst_line_raster_cycles"], 27)

    def test_unmapped_action_ordinal_is_a_hard_failure(self) -> None:
        bound = _bound()
        bound["object_multiplicity"]["classes"][0]["action_ordinals"] = [99]
        with self.assertRaises(FrameSpriteFragmentEnvelopeError) as caught:
            build_frame_sprite_fragment_envelope(
                bound, _plan(), _domains(), _metrics())
        self.assertEqual(caught.exception.code, "PZFSFE003")

    def test_unmapped_reachable_template_blocks_every_weighted_claim(self) -> None:
        metrics = _metrics()
        del metrics[(0x0102, 0x2000)]
        report = build_frame_sprite_fragment_envelope(
            _bound(), _plan(), _domains(), metrics,
            transient_template_keys=_domains()).as_dict()
        self.assertFalse(report["proof_complete"])
        self.assertEqual(
            report["status"], "BLOCKED_UNMAPPED_REACHABLE_TEMPLATE")
        self.assertIsNone(
            report["weighted_display_list"]["max_cmd_append_expanded_words"])
        self.assertIsNone(
            report["raster_envelope"]["max_raster_cycles_by_line"])
        blockers = {item["code"]: item for item in report["blockers"]}
        self.assertEqual(blockers["PZFSFE102"]["missing_template_count"], 1)

    def test_empty_action_domain_is_not_treated_as_zero_cost(self) -> None:
        domains = _domains()
        domains["A"] = ()
        report = build_frame_sprite_fragment_envelope(
            _bound(), _plan(), domains, _metrics(),
            transient_template_keys=domains).as_dict()
        self.assertFalse(report["proof_complete"])
        self.assertIn("PZFSFE101", {item["code"] for item in report["blockers"]})

    def test_source_proved_nonrendering_class_needs_no_fake_template(self) -> None:
        bound = copy.deepcopy(_bound())
        bound["object_multiplicity"]["classes"].append({
            "class_name": "Controller", "max_records_per_object": 1,
            "action_ordinals": [0], "witness_fields": {"visible": False},
        })
        bound["abstract_reachability"]["spawn_reachability"] \
            ["finite_class_instance_upper_bounds"]["Controller"] = 1
        report = build_frame_sprite_fragment_envelope(
            bound, _plan(), _domains(), _metrics(),
            transient_template_keys=_domains(),
            nonrendering_classes={"Controller"}).as_dict()
        self.assertTrue(report["proof_complete"])
        controller = next(
            item for item in report["class_action_witnesses"]
            if item["class_name"] == "Controller")
        self.assertTrue(controller["source_coverage_nonrendering"])
        self.assertEqual(
            controller["max_cmd_append_expanded_words_per_object"], 0)

    def test_optimistic_scalar_and_raster_claims_fail_closed(self) -> None:
        with self.assertRaises(FrameSpriteFragmentEnvelopeError) as caught:
            build_frame_sprite_fragment_envelope(
                _bound(), _plan(), _domains(), _metrics(),
                transient_template_keys=_domains(), chunk_capacity=2,
                claims={"max_cmd_append_expanded_words": 35})
        self.assertEqual(caught.exception.code, "PZFSFE007")
        with self.assertRaises(FrameSpriteFragmentEnvelopeError) as caught:
            build_frame_sprite_fragment_envelope(
                _bound(), _plan(), _domains(), _metrics(),
                transient_template_keys=_domains(),
                claims={"raster_cycles_by_line": [26] * 768})
        self.assertEqual(caught.exception.code, "PZFSFE007")

    def test_capacity_zero_or_above_target_max_fails_closed(self) -> None:
        for capacity in (0, 129):
            with self.subTest(capacity=capacity):
                with self.assertRaises(FrameSpriteFragmentEnvelopeError) as caught:
                    build_frame_sprite_fragment_envelope(
                        _bound(), _plan(), _domains(), _metrics(),
                        chunk_capacity=capacity)
                self.assertEqual(caught.exception.code, "PZFSFE002")

    def test_record_composition_cannot_be_optimistically_reduced(self) -> None:
        bound = copy.deepcopy(_bound())
        bound["certified_frame_max_records"] = 4
        with self.assertRaises(FrameSpriteFragmentEnvelopeError) as caught:
            build_frame_sprite_fragment_envelope(
                bound, _plan(), _domains(), _metrics())
        self.assertEqual(caught.exception.code, "PZFSFE006")


if __name__ == "__main__":
    unittest.main(verbosity=2)
