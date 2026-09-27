#!/usr/bin/env python3
"""Focused tests for physical HQT3/RAM_G scope packs and transitions."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from check_pyz80_hqt3_ramg_schedule import validate_report
from pyz80_compiler.hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_CELL_BYTES,
    HQT3_HEADER_BYTES,
    HQT3_RAMG_SCHEDULE_FORMAT,
    HQT3_RAMG_SCHEDULE_STATUS,
    HQT3_RECORD_BYTES,
    HQT3_STATE_BYTES,
    HQT3RAMGScheduleError,
    TSCONF_RAM_BYTES,
    compile_pixel_packs,
    derive_event_transition_obligations,
)


ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "Build" / "rtype_python_hqt3_ramg_schedule_status.json"


def _rehash(value: dict[str, object]) -> None:
    semantic = dict(value)
    semantic.pop("analysis_sha256", None)
    value["analysis_sha256"] = hashlib.sha256(json.dumps(
        semantic, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _scope(scope_id: str, stage: int) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "stage": stage,
        "pixel_pack_id": "sprite-test-a",
        "capacity": {"ram_g_isolated_fit": True},
    }


class HQT3RAMGScheduleTests(unittest.TestCase):
    def test_process_pool_preserves_sorted_pack_identity(self) -> None:
        packs = compile_pixel_packs(
            ROOT,
            {"sprite-empty-b": (), "sprite-empty-a": ()},
            27,
            30,
            max_workers=2,
        )
        self.assertEqual(
            list(packs), ["sprite-empty-a", "sprite-empty-b"])
        self.assertEqual(packs, {
            "sprite-empty-a": None,
            "sprite-empty-b": None,
        })

    def test_physical_hqt3_struct_sizes_match_real_generator(self) -> None:
        self.assertEqual(HQT3_HEADER_BYTES, 20)
        self.assertEqual(HQT3_RECORD_BYTES, 18)
        self.assertEqual(HQT3_STATE_BYTES, 8)
        self.assertEqual(HQT3_CELL_BYTES, 9)

    def test_event_transition_never_turns_disappearance_into_eviction(
            self) -> None:
        scopes = {
            "stage:1:class:A": _scope("stage:1:class:A", 1),
            "stage:1:class:B": _scope("stage:1:class:B", 1),
        }
        events = (
            {
                "event_id": "stage:1:event:1000",
                "stage": 1,
                "address": 0x1000,
                "class_scope_ids": ["stage:1:class:A"],
                "correlation_exact": True,
                "pack_id": "sprite-test-a",
                "pair_sha256": "a" * 64,
                "ambiguous_classes": [],
            },
            {
                "event_id": "stage:1:event:1004",
                "stage": 1,
                "address": 0x1004,
                "class_scope_ids": ["stage:1:class:B"],
                "correlation_exact": False,
                "pack_id": "sprite-test-b",
                "pair_sha256": "b" * 64,
                "ambiguous_classes": ["B"],
            },
        )
        result = derive_event_transition_obligations(
            events, scopes, (), (), ())
        self.assertEqual(result["event_obligation_count"], 2)
        second = result["obligations"][1]
        self.assertEqual(
            second["candidate_disappeared_scope_ids"],
            ["stage:1:class:A"])
        self.assertFalse(second["disappeared_scope_eviction_permitted"])
        self.assertFalse(second["required_scope_union_residency_proved"])
        self.assertIsNone(second["transition_byte_cost"])
        self.assertEqual(result["event_correlation_ambiguous_count"], 1)

    def test_event_order_must_remain_strict_source_order(self) -> None:
        events = (
            {
                "event_id": "stage:1:event:1004", "stage": 1,
                "address": 0x1004, "class_scope_ids": [],
                "correlation_exact": True,
                "pack_id": "sprite-empty", "pair_sha256": "0" * 64,
                "ambiguous_classes": [],
            },
            {
                "event_id": "stage:1:event:1000", "stage": 1,
                "address": 0x1000, "class_scope_ids": [],
                "correlation_exact": True,
                "pack_id": "sprite-empty", "pair_sha256": "0" * 64,
                "ambiguous_classes": [],
            },
        )
        with self.assertRaisesRegex(
                HQT3RAMGScheduleError, "strict source order"):
            derive_event_transition_obligations(events, {}, (), (), ())

    def test_active_status_proves_all_174_scopes_without_residency_fiction(
            self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        validate_report(value)
        self.assertEqual(value["format"], HQT3_RAMG_SCHEDULE_FORMAT)
        self.assertEqual(value["status"], HQT3_RAMG_SCHEDULE_STATUS)
        self.assertEqual(value["scope_pack_census"]["scope_count"], 174)
        census = value["scope_pack_census"]
        self.assertEqual(census["unique_pixel_pack_count"], 83)
        self.assertEqual(census["ram_g_isolated_fit_count"], 171)
        self.assertEqual(census["ram_g_isolated_nonfit_count"], 3)
        self.assertEqual(census["ram_g_isolated_nonfit_scope_ids"], [
            "stage:2:class:Enemy6F89",
            "stage:2:class:Multipart915BChild",
            "stage:5:class:Formation78F8Child",
        ])
        self.assertEqual(census["ts_compiled_isolated_fit_count"], 174)
        self.assertEqual(census["ts_compiled_isolated_nonfit_count"], 0)
        self.assertEqual(census["ts_raw_argb4444_isolated_nonfit_count"], 2)
        self.assertEqual(census["hqt3_index_width_nonfit_count"], 3)
        self.assertEqual(census["hqt3_index_width_nonfit_scope_ids"], [
            "stage:2:class:Child8D85",
            "stage:2:class:Enemy6F89",
            "stage:5:class:Formation78F8Child",
        ])
        self.assertEqual(
            census["worst_ram_g_scope_id"],
            "stage:5:class:Formation78F8Child")
        self.assertEqual(census["worst_ram_g_payload_bytes"], 2339476)
        self.assertEqual(census["worst_hqt3_bytes"], 78368)
        self.assertEqual(value["inventory_binding"]["event_count"], 788)
        self.assertEqual(
            value["event_transitions"]["event_obligation_count"], 788)
        self.assertEqual(
            value["event_transitions"]["event_correlation_ambiguous_count"],
            663)
        self.assertEqual(
            value["event_transitions"]["unique_event_pixel_pack_count"], 36)
        self.assertEqual(
            value["event_transitions"]
            ["event_count_without_independent_scope_pack"], 77)
        self.assertEqual(
            len(value["event_transitions"]
                ["unique_event_pixel_packs_without_independent_scope"]), 13)
        self.assertEqual(value["resident_combinations"], [])
        self.assertFalse(value["whole_inventory_resident"])
        self.assertFalse(value["whole_stage_union_resident"])
        self.assertFalse(value["load_schedule_complete"])
        self.assertFalse(value["live"])
        self.assertEqual(
            {item["code"] for item in value["blockers"]},
            {"PZRG301", "PZRG303", "PZRG304", "PZRG305",
             "PZRG306", "PZRG307", "PZRG308"})
        self.assertTrue(value["proof_boundaries"]
                        ["upstream_inventory_fixed_hqt3_layout_matches_physical"])

    def test_empty_service_scopes_have_only_a_physical_hqt3_header(self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        empty = [
            scope for scope in value["scope_packs"]
            if scope["pixel_pack"]["logical_cell_count"] == 0
        ]
        self.assertEqual(len(empty), 56)
        for scope in empty:
            self.assertEqual(scope["pixel_pack"]["ft812_payload_bytes"], 0)
            self.assertEqual(scope["hqt3"]["record_count"], 0)
            self.assertEqual(scope["hqt3"]["cell_reference_count"], 0)
            self.assertEqual(scope["hqt3"]["state_count"], 0)
            self.assertEqual(scope["hqt3"]["total_bytes"], HQT3_HEADER_BYTES)

    def test_ram_g_and_ts_staging_are_classified_separately(self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        for scope in value["scope_packs"]:
            capacity = scope["capacity"]
            self.assertEqual(
                capacity["ram_g_isolated_fit"],
                capacity["ram_g_payload_bytes"] <= FT812_RAM_G_BYTES)
            self.assertEqual(
                capacity["ts_staging_compiled_isolated_fit"],
                capacity["ts_staging_compiled_payload_plus_hqt3_bytes"] <=
                TSCONF_RAM_BYTES)
            self.assertFalse(capacity["ram_g_gameplay_profile_fit_proved"])
            self.assertFalse(capacity["ts_whole_machine_allocation_fit_proved"])

    def test_validator_rejects_a_forged_resident_claim(self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        forged = copy.deepcopy(value)
        forged["scope_packs"][0]["resident"] = True
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3RAMGScheduleError, "unproved resident scope"):
            validate_report(forged)

    def test_validator_rejects_mixed_ram_g_and_ts_arithmetic(self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        forged = copy.deepcopy(value)
        forged["scope_packs"][0]["capacity"][
            "ts_staging_compiled_payload_plus_hqt3_bytes"] += 1
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3RAMGScheduleError, "capacity classification"):
            validate_report(forged)


if __name__ == "__main__":
    unittest.main()
