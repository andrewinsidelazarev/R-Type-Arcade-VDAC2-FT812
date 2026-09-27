#!/usr/bin/env python3
"""Focused tests for frame-local HQT3 page feasibility boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from check_pyz80_hqt3_frame_page_solver import validate_report
from pyz80_compiler.hqt3_frame_page_solver import (
    EXACT_NONFIT_EVENT_ID,
    FRAME_RATE_HZ,
    FRAME_RECORD_LIMIT,
    HQT3_FRAME_PAGE_SOLVER_FORMAT,
    HQT3_FRAME_PAGE_SOLVER_STATUS,
    HQT3FramePageSolverError,
    RAMG_OVERSIZED_SCOPE_IDS,
)
from pyz80_compiler.hqt3_ramg_schedule import FT812_RAM_G_BYTES


ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "Build" / "rtype_python_hqt3_frame_page_solver_status.json"


def _rehash(value: dict[str, object]) -> None:
    semantic = dict(value)
    semantic.pop("analysis_sha256", None)
    value["analysis_sha256"] = hashlib.sha256(json.dumps(
        semantic, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class HQT3FramePageSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.value = json.loads(STATUS.read_text(encoding="utf-8"))
        validate_report(cls.value)

    def test_status_is_explicitly_non_live_and_undecided(self) -> None:
        value = self.value
        self.assertEqual(value["format"], HQT3_FRAME_PAGE_SOLVER_FORMAT)
        self.assertEqual(value["status"], HQT3_FRAME_PAGE_SOLVER_STATUS)
        self.assertFalse(value["live"])
        self.assertEqual(
            value["physical_feasibility_decision"],
            "UNDECIDED_LIFETIME_AND_BANDWIDTH_BLOCKED")

    def test_three_ramg_oversized_scopes_are_not_hidden_by_hqt_shards(self) -> None:
        scopes = self.value["problem_scope_page_catalogs"]
        oversized = {
            row["scope_id"] for row in scopes
            if row["ram_g_oversized_scope"]
        }
        self.assertEqual(oversized, set(RAMG_OVERSIZED_SCOPE_IDS))
        for row in scopes:
            self.assertTrue(row["all_atoms_semantic"])
            self.assertTrue(row["all_atoms_individually_strict_ram_g_fit"])
            self.assertFalse(row["exact_per_frame_page_set_proved"])
            self.assertFalse(row["upper_estimate_is_reachability_tight"])

    def test_exact_bcab_union_is_reproduced_but_never_declared_resident(self) -> None:
        bcab = self.value["exact_bcab_page_catalog"]
        self.assertEqual(bcab["scope_id"], EXACT_NONFIT_EVENT_ID)
        self.assertEqual(bcab["template_count"], 596)
        self.assertEqual(bcab["page_atom_count"], 596)
        self.assertEqual(bcab["union_ram_g_bytes"], 1_263_796)
        self.assertEqual(
            bcab["union_ram_g_overflow_bytes"],
            1_263_796 - FT812_RAM_G_BYTES)
        self.assertFalse(bcab["single_union_strict_ram_g_fit"])
        self.assertEqual(len(bcab["page_atoms"]), 596)
        for atom in bcab["page_atoms"]:
            self.assertEqual(
                atom["semantic_axis"], "exact-bank-plus-rom-descriptor")
            self.assertFalse(atom["arbitrary_size_cut"])
            self.assertFalse(atom["eviction_inferred"])
            self.assertLess(atom["ram_g_bytes"], FT812_RAM_G_BYTES)

    def test_source_rom_first_child_cold_miss_floor_is_conditional(self) -> None:
        witness = self.value["source_evidence"]["bcab_rom_witness"]
        self.assertEqual(witness["event_address"], 0xBCAB)
        self.assertEqual(witness["command"], 0x7404)
        self.assertEqual(witness["handler"], 0x915B)
        self.assertEqual(witness["parent_sequence"], 0x40C6)
        self.assertEqual(witness["first_initializer"], 0x9246)
        self.assertEqual(witness["first_child_descriptor"], 0x419E)
        first = self.value["strict_lower_bounds"]["bcab_first_child"]
        self.assertTrue(
            first["conditional_on_event_and_successful_object_allocation"])
        self.assertEqual(first["palette_slot_candidates"], list(range(16)))
        self.assertEqual(first["cold_miss_upload_min_bytes"], 3760)
        self.assertEqual(first["cold_miss_upload_max_bytes"], 5296)
        self.assertEqual(
            first["cold_miss_minimum_average_bytes_per_second_at_55hz"],
            3760 * FRAME_RATE_HZ)

    def test_228_records_do_not_forge_a_byte_exact_page_set(self) -> None:
        frame = self.value["frame_record_contract"]
        self.assertEqual(frame["certified_frame_max_records"], FRAME_RECORD_LIMIT)
        self.assertEqual(frame["maximum_distinct_page_references_per_frame"],
                         FRAME_RECORD_LIMIT)
        self.assertFalse(frame["exact_page_identity_sequence_proved"])
        double = self.value["double_buffer_capacity"]
        self.assertEqual(
            double["required_resident_relation"],
            "pages(frame_n) UNION pages(frame_n+1)")
        self.assertIsNone(double["exact_two_generation_union_bytes"])
        self.assertFalse(double["strict_fit_proved"])
        self.assertFalse(double["event_order_used_as_eviction_proof"])

    def test_upload_bandwidth_is_a_requirement_not_an_invented_measurement(self) -> None:
        upload = self.value["upload_bandwidth"]
        self.assertEqual(upload["frame_rate_hz"], 55)
        self.assertIsNone(upload["transport_measured_bytes_per_second"])
        self.assertIsNone(upload["transport_setup_latency_microseconds"])
        self.assertIsNone(upload["transport_available_window_microseconds"])
        self.assertFalse(upload["deadline_proved"])

    def test_hqt_integer_widths_are_valid_after_semantic_paging(self) -> None:
        widths = self.value["hqt_width_contract"]
        self.assertEqual(widths["global_template_count"], 10776)
        self.assertTrue(widths["global_template_id_uint16_fit"])
        self.assertEqual(widths["page_atom_record_count_max"], 1)
        self.assertEqual(widths["page_atom_cell_count_max"], 64)
        self.assertEqual(widths["page_atom_state_count_max"], 47)
        self.assertTrue(widths["all_page_atom_indices_fit"])
        self.assertTrue(widths["frame_record_count_uint8_fit"])

    def test_active_call_graph_is_bound_but_dynamic_child_chain_fails_closed(self) -> None:
        source = self.value["source_evidence"]
        self.assertFalse(
            source["active_call_graph_exactly_reaches_complete_child_chain"])
        by_name = {
            row["qualname"]: row
            for row in source["active_callable_witnesses"]
        }
        self.assertTrue(by_name["M72EnemyWorld.update"]
                        ["proven_reachable_by_exact_call_edges"])
        self.assertFalse(by_name["Multipart915BParent.update"]
                         ["proven_reachable_by_exact_call_edges"])
        self.assertFalse(by_name["Multipart915BChild.__init__"]
                         ["proven_reachable_by_exact_call_edges"])

    def test_validator_rejects_forged_event_eviction(self) -> None:
        forged = copy.deepcopy(self.value)
        forged["double_buffer_capacity"][
            "event_order_used_as_eviction_proof"] = True
        forged["eviction_inferences"] = [{"event": "BCAB", "evict": "prior"}]
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3FramePageSolverError,
                "double-buffer|residency/eviction"):
            validate_report(forged)

    def test_validator_rejects_arbitrary_size_page_cut(self) -> None:
        forged = copy.deepcopy(self.value)
        forged["exact_bcab_page_catalog"]["page_atoms"][0][
            "arbitrary_size_cut"] = True
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3FramePageSolverError, "semantic boundary"):
            validate_report(forged)

    def test_validator_rejects_unmeasured_bandwidth_claim(self) -> None:
        forged = copy.deepcopy(self.value)
        forged["upload_bandwidth"][
            "transport_measured_bytes_per_second"] = 99_999_999
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3FramePageSolverError, "upload bandwidth"):
            validate_report(forged)


if __name__ == "__main__":
    unittest.main()
