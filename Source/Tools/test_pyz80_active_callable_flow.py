#!/usr/bin/env python3
"""Tests for source-proven unresolved callable-value flow inventory."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

import pyz80_compiler.active_callable_flow as callable_flow
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_callable_flow import (
    ACTIVE_CALLABLE_FLOW_FORMAT,
    ACTIVE_CALLABLE_FLOW_STATUS,
    ActiveCallableFlowError,
    analyze_active_callable_flow,
    validate_active_callable_flow_report,
)


ROOT = Path(__file__).resolve().parents[2]


def _resign(report: dict[str, object]) -> None:
    report["semantic_sha256"] = callable_flow._json_sha256(
        callable_flow._semantic_payload(report))


class ActiveCallableFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.active_graph = analyze_active_call_graph(ROOT)
        cls.report = analyze_active_callable_flow(
            ROOT, active_graph=cls.active_graph)
        cls.sites = cls.report["unresolved_local_sites_in_source_order"]
        cls.units = {row["callable_value_id"]: row for row in
                     cls.report["callable_value_units_in_source_order"]}

    def test_current_nine_sites_have_exact_dynamic_census(self) -> None:
        self.assertEqual(self.report["format"], ACTIVE_CALLABLE_FLOW_FORMAT)
        self.assertEqual(self.report["status"], ACTIVE_CALLABLE_FLOW_STATUS)
        self.assertFalse(self.report["live"])
        census = self.report["census"]
        self.assertEqual(
            census["reachable_unresolved_local_callable_site_count"], 9)
        self.assertEqual(census["callee_name_counts"], {
            "contact": 1, "damage_at": 6, "play_sfx": 2})
        self.assertEqual(len(self.sites), 9)

    def test_damage_callbacks_are_distinct_source_bound_lambdas(self) -> None:
        damage = [row for row in self.sites
                  if row["callee_name"] == "damage_at"]
        self.assertEqual(len(damage), 6)
        self.assertTrue(all(row["incoming_candidates_complete"]
                            for row in damage))
        for row in damage:
            self.assertEqual(row["candidate_count"], 1)
            unit = self.units[row["candidate_callable_value_ids"][0]]
            self.assertEqual(unit["kind"], "lambda")
            self.assertEqual(
                [item["name"] for item in unit["signature"]["parameters"]],
                ["rect", "damage"])
            self.assertEqual(unit["closure"]["captured_names"], ["self"])
            self.assertFalse(unit["callable_unit_integrated"])

    def test_play_sfx_flow_retains_bound_method_and_fallback_lambdas(
            self) -> None:
        sites = [row for row in self.sites
                 if row["callee_name"] == "play_sfx"]
        self.assertEqual(len(sites), 2)
        self.assertTrue(all(row["incoming_candidates_complete"]
                            for row in sites))
        for row in sites:
            kinds = row["candidate_kind_counts"]
            self.assertGreaterEqual(kinds.get("lambda", 0), 2)
            self.assertEqual(kinds.get("bound-method"), 1)
            bound = [self.units[item]
                     for item in row["candidate_callable_value_ids"]
                     if self.units[item]["kind"] == "bound-method"]
            self.assertEqual(len(bound), 1)
            self.assertTrue(bound[0]["receiver_proof"]["complete"])
            self.assertIn("::TargetAudio.play@",
                          str(bound[0]["target_callable_id"]))

    def test_dynamic_getattr_contact_is_explicitly_incomplete(self) -> None:
        contact = next(row for row in self.sites
                       if row["callee_name"] == "contact")
        self.assertFalse(contact["incoming_candidates_complete"])
        self.assertEqual(contact["candidate_count"], 0)
        self.assertEqual(len(contact["dynamic_source_ids"]), 1)
        dynamic = self.report["dynamic_sources_in_source_order"][0]
        self.assertEqual(dynamic["kind"], "dynamic-getattr")
        self.assertEqual(dynamic["attribute_name"], "player_contact")
        self.assertIn(
            "getattr-receiver-class-not-source-proven", dynamic["reasons"])

    def test_candidates_never_become_graph_reachability_edges(self) -> None:
        self.assertTrue(all(row["proven"] is False and
                            row["promotion_permitted"] is False
                            for row in self.sites))
        self.assertTrue(all(row["proven_reachability_edge"] is False and
                            row["callable_unit_integrated"] is False
                            for row in self.units.values()))
        self.assertFalse(
            self.report["proof"]["callable_units_and_dispatch_integrated"])

    def test_report_is_deterministic_for_same_validated_graph(self) -> None:
        repeated = callable_flow._build_report(ROOT, self.active_graph)
        self.assertEqual(repeated["semantic_sha256"],
                         self.report["semantic_sha256"])
        self.assertEqual(repeated, self.report)

    def test_resigned_candidate_completion_unit_and_order_tampering(self) -> None:
        mutations = []
        candidate = copy.deepcopy(self.report)
        row = next(item for item in candidate[
            "unresolved_local_sites_in_source_order"]
                   if item["candidate_callable_value_ids"])
        row["proven"] = True
        mutations.append(candidate)

        completion = copy.deepcopy(self.report)
        row = next(item for item in completion[
            "unresolved_local_sites_in_source_order"]
                   if not item["incoming_candidates_complete"])
        row["incoming_candidates_complete"] = True
        mutations.append(completion)

        unit = copy.deepcopy(self.report)
        unit["callable_value_units_in_source_order"][0][
            "callable_unit_integrated"] = True
        mutations.append(unit)

        order = copy.deepcopy(self.report)
        order["unresolved_local_sites_in_source_order"][0:2] = reversed(
            order["unresolved_local_sites_in_source_order"][0:2])
        mutations.append(order)

        for index, tampered in enumerate(mutations):
            with self.subTest(index=index):
                _resign(tampered)
                with self.assertRaises(ActiveCallableFlowError):
                    validate_active_callable_flow_report(
                        ROOT, tampered, active_graph=self.active_graph)


if __name__ == "__main__":
    unittest.main()
