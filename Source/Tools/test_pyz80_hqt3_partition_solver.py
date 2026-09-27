#!/usr/bin/env python3
"""Focused tests for semantic HQT3 sharding and RAM_G paging boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from check_pyz80_hqt3_partition_solver import validate_report
from pyz80_compiler.hqt3_partition_solver import (
    AMBIGUOUS_FACTS,
    HQT3_PARTITION_SOLVER_FORMAT,
    HQT3_PARTITION_SOLVER_STATUS,
    HQT3PartitionSolverError,
)
from pyz80_compiler.hqt3_ramg_schedule import (
    HQT3_CELL_BYTES,
    HQT3_HEADER_BYTES,
    HQT3_RECORD_BYTES,
    HQT3_STATE_BYTES,
)


ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "Build" / "rtype_python_hqt3_partition_solver_status.json"


def _rehash(value: dict[str, object]) -> None:
    semantic = dict(value)
    semantic.pop("analysis_sha256", None)
    value["analysis_sha256"] = hashlib.sha256(json.dumps(
        semantic, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class HQT3PartitionSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.value = json.loads(STATUS.read_text(encoding="utf-8"))
        validate_report(cls.value)

    def test_physical_hqt3_layout_is_bound_to_18_byte_records(self) -> None:
        self.assertEqual(HQT3_HEADER_BYTES, 20)
        self.assertEqual(HQT3_RECORD_BYTES, 18)
        self.assertEqual(HQT3_STATE_BYTES, 8)
        self.assertEqual(HQT3_CELL_BYTES, 9)

    def test_active_status_has_exact_problem_and_event_census(self) -> None:
        value = self.value
        self.assertEqual(value["format"], HQT3_PARTITION_SOLVER_FORMAT)
        self.assertEqual(value["status"], HQT3_PARTITION_SOLVER_STATUS)
        self.assertEqual(value["problem_scope_count"], 4)
        census = value["event_cost_census"]
        self.assertEqual(census["event_count"], 788)
        self.assertEqual(census["exact_event_count"], 125)
        self.assertEqual(census["ambiguous_event_count"], 663)
        self.assertEqual(census["unique_requirement_count"], 37)
        self.assertEqual(census["unique_pixel_pack_count"], 36)
        self.assertEqual(census["union_event_count"], 77)
        self.assertEqual(census["union_only_pixel_pack_count"], 13)
        self.assertEqual(census["exact_event_nonfit_count"], 1)
        self.assertEqual(census["exact_event_nonfit_requirement_count"], 1)

    def test_descriptor_pages_are_semantic_atoms_not_size_cuts(self) -> None:
        accepted: list[str] = []
        partition_counts: dict[str, int] = {}
        for scope in self.value["problem_scopes"]:
            scope_id = scope["scope_id"]
            summary = scope["descriptor_page_summary"]
            partition_counts[scope_id] = summary["partition_count"]
            self.assertEqual(summary["axis"], "exact-bank-plus-rom-descriptor")
            self.assertTrue(summary["all_templates_atomic"])
            self.assertFalse(summary["arbitrary_size_cut"])
            self.assertTrue(summary["all_full_pages_individually_meet_targets"])
            self.assertFalse(summary["full_pages_ram_g_simultaneous_fit"])
            for page in scope["descriptor_pages"]:
                self.assertTrue(page["template_atomic"])
                self.assertFalse(page["arbitrary_size_cut"])
                self.assertFalse(page["runtime_eviction_permitted"])
                self.assertTrue(page["full_page_cost"]
                                ["partition_targets"]["all_targets_pass"])
            if scope["accepted_partition_plan"] is not None:
                accepted.append(scope_id)
        self.assertEqual(partition_counts, {
            "stage:2:class:Child8D85": 213,
            "stage:2:class:Enemy6F89": 680,
            "stage:2:class:Multipart915BChild": 554,
            "stage:5:class:Formation78F8Child": 1173,
        })
        self.assertEqual(accepted, ["stage:2:class:Child8D85"])

    def test_hqt_overflows_are_structurally_solved_but_ramg_is_not(self) -> None:
        resolution = self.value["blocker_resolution"]
        self.assertFalse(resolution["PZRG301"]
                         ["can_eliminate_by_structural_paging_without_python_semantic_change"])
        self.assertEqual(
            resolution["PZRG301"]["structurally_solved_scope_ids"], [])
        self.assertTrue(resolution["PZRG307"]
                        ["can_eliminate_by_structural_hqt_sharding_without_python_semantic_change"])
        self.assertEqual(
            resolution["PZRG307"]["structurally_solved_scope_ids"], [
                "stage:2:class:Child8D85",
                "stage:2:class:Enemy6F89",
                "stage:5:class:Formation78F8Child",
            ])
        self.assertTrue(resolution["PZRG307"]
                        ["target_multi_table_resolver_still_required"])

    def test_ramg_block_is_backed_by_active_source_ast_witnesses(self) -> None:
        witnesses = self.value["source_evidence"]["ast_witnesses"]
        self.assertTrue(witnesses["formation_linked_children"]
                        ["passes_previous_head"])
        self.assertTrue(witnesses["multipart_linked_children"]
                        ["passes_previous_head"])
        self.assertEqual(witnesses["child8d85_multiple_timer_spawns"]
                         ["distinct_timer_values"], [0x80, 0xC0])
        self.assertFalse(witnesses["enemy6f89_direct_unguarded_dispatch"]
                         ["singleton_guard_in_handler_branch"])
        self.assertTrue(witnesses["cross_event_survivor_retention"]
                        ["live_enemies_retained"])

    def test_exact_events_have_concrete_hash_bound_cost_obligations(self) -> None:
        exact = self.value["exact_event_partition_obligations"]
        self.assertEqual(len(exact), 125)
        nonfit = []
        for row in exact:
            self.assertTrue(row["semantic_event_relation_exact"])
            self.assertIsNotNone(row["semantic_selected_cost"])
            self.assertTrue(row["union_keys_computable"])
            self.assertFalse(row["eviction_permitted"])
            self.assertIsInstance(row["concrete_partition_obligation"], str)
            if not row["single_union_partition_meets_targets"]:
                nonfit.append(row)
        self.assertEqual([row["event_id"] for row in nonfit], [
            "stage:2:event:BCAB"])
        self.assertEqual(nonfit[0]["semantic_selected_cost"]["ram_g_bytes"], 1263796)

    def test_ambiguous_events_fail_closed_with_minimal_facts(self) -> None:
        ambiguous = self.value["ambiguous_event_partition_obligations"]
        fact_ids = [item["fact_id"] for item in AMBIGUOUS_FACTS]
        self.assertEqual(len(ambiguous), 663)
        for row in ambiguous:
            self.assertFalse(row["semantic_event_relation_exact"])
            self.assertIsNone(row["semantic_selected_cost"])
            self.assertIsNotNone(row["conservative_candidate_union_cost"])
            self.assertEqual(row["minimum_required_fact_ids"], fact_ids)
            self.assertFalse(row["eviction_permitted"])

    def test_union_only_event_packs_have_exact_physical_costs(self) -> None:
        requirements = {
            row["requirement_id"]: row
            for row in self.value["event_union_requirements"]
        }
        union_rows = [
            row for row in (
                self.value["exact_event_partition_obligations"] +
                self.value["ambiguous_event_partition_obligations"])
            if row["union_only_pixel_pack"]
        ]
        self.assertEqual(len(union_rows), 77)
        self.assertEqual(len({
            requirements[row["requirement_id"]]["pixel_pack_id"]
            for row in union_rows
        }), 13)
        for row in union_rows:
            requirement = requirements[row["requirement_id"]]
            self.assertTrue(requirement["union_keys_computable"])
            self.assertIsNotNone(requirement["union_cost"])
            self.assertEqual(
                requirement["union_cost_sha256"],
                hashlib.sha256(json.dumps(
                    requirement["union_cost"], ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest())

    def test_validator_rejects_forged_event_eviction(self) -> None:
        forged = copy.deepcopy(self.value)
        forged["exact_event_partition_obligations"][0][
            "eviction_permitted"] = True
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3PartitionSolverError, "event semantic boundary"):
            validate_report(forged)

    def test_validator_rejects_arbitrary_size_partition(self) -> None:
        forged = copy.deepcopy(self.value)
        forged["problem_scopes"][0]["descriptor_pages"][0][
            "arbitrary_size_cut"] = True
        _rehash(forged)
        with self.assertRaisesRegex(
                HQT3PartitionSolverError, "non-semantic page"):
            validate_report(forged)


if __name__ == "__main__":
    unittest.main()
