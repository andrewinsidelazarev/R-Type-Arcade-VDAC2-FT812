#!/usr/bin/env python3
"""Tests for the source-sealed reachable call-site lowering inventory."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

import pyz80_compiler.active_call_site_lowering as lowering
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_call_site_lowering import (
    ACTIVE_CALL_SITE_LOWERING_FORMAT,
    ACTIVE_CALL_SITE_LOWERING_STATUS,
    ActiveCallSiteLoweringError,
    analyze_active_call_site_lowering,
    validate_active_call_site_lowering_report,
)


ROOT = Path(__file__).resolve().parents[2]


def _resign(report: dict[str, object]) -> None:
    report["semantic_sha256"] = lowering._json_sha256(
        lowering._semantic_payload(report))


class ActiveCallSiteLoweringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.active_graph = analyze_active_call_graph(ROOT)
        cls.report = analyze_active_call_site_lowering(
            ROOT, active_graph=cls.active_graph)

    def test_report_is_bound_to_fresh_validated_graph(self) -> None:
        self.assertEqual(self.report["format"],
                         ACTIVE_CALL_SITE_LOWERING_FORMAT)
        self.assertEqual(self.report["status"],
                         ACTIVE_CALL_SITE_LOWERING_STATUS)
        self.assertFalse(self.report["live"])
        self.assertEqual(
            self.report["active_call_graph_semantic_sha256"],
            self.active_graph["semantic_sha256"])
        self.assertTrue(
            self.report["proof"]["active_call_graph_validated_in_memory"])

    def test_every_cfg_python_call_has_one_full_span_mapping(self) -> None:
        mapping = self.report["mapping"]
        occurrences = self.report["cfg_occurrences_in_cfg_order"]
        sites = self.report["sites_in_source_order"]
        self.assertEqual(mapping["cfg_python_call_occurrence_count"],
                         len(occurrences))
        self.assertEqual(mapping["represented_graph_call_site_count"],
                         len(sites))
        self.assertEqual(mapping["missing_cfg_to_graph_match_count"], 0)
        self.assertEqual(mapping["ambiguous_cfg_to_graph_match_count"], 0)
        by_id = {row["call_site_id"]: row for row in sites}
        self.assertTrue(occurrences)
        for occurrence in occurrences:
            site = by_id[occurrence["call_site_id"]]
            self.assertEqual(occurrence["numeric_call_site_id"],
                             site["numeric_call_site_id"])
            self.assertEqual(occurrence["caller"], site["caller"])
            self.assertEqual(occurrence["span"], site["span"])

    def test_numeric_ids_and_duplicate_occurrences_are_stable(self) -> None:
        represented = self.report["sites_in_source_order"]
        unrepresented = self.report[
            "unrepresented_graph_sites_in_source_order"]
        all_sites = sorted(
            represented + unrepresented,
            key=lambda row: row["numeric_call_site_id"])
        self.assertEqual(
            [row["numeric_call_site_id"] for row in all_sites],
            list(range(1, len(all_sites) + 1)))
        duplicates = [row for row in represented
                      if row["cfg_occurrence_count"] > 1]
        self.assertTrue(duplicates)
        occurrences = self.report["cfg_occurrences_in_cfg_order"]
        for site in duplicates:
            rows = [occurrences[index]
                    for index in site["cfg_occurrence_indexes"]]
            self.assertEqual({row["call_site_id"] for row in rows},
                             {site["call_site_id"]})
            self.assertEqual({row["numeric_call_site_id"] for row in rows},
                             {site["numeric_call_site_id"]})

    def test_resolution_and_argument_obligations_stay_explicit(self) -> None:
        sites = self.report["sites_in_source_order"]
        classifications = {row["classification"] for row in sites}
        self.assertIn("proven-single-internal", classifications)
        self.assertIn("finite-non-proven", classifications)
        self.assertIn("host-boundary", classifications)
        self.assertIn("unresolved", classifications)
        for row in sites:
            if row["classification"] == "finite-non-proven":
                self.assertFalse(row["proven"])
                self.assertTrue(row["targets"])
            occurrence = self.report["cfg_occurrences_in_cfg_order"][
                row["cfg_occurrence_indexes"][0]]
            self.assertEqual(
                [item["argument_index"]
                 for item in occurrence["argument_layout"]],
                list(range(len(occurrence["argument_layout"]))))
            obligations = row["obligations"]
            self.assertIn("constructor_allocation", obligations)
            self.assertIn("default_argument_binding", obligations)
            self.assertIn("keyword_binding", obligations)
            self.assertIn("star_argument_expansion", obligations)
        self.assertTrue(any(row["binding_mode"] == "constructor"
                            for row in sites))
        self.assertTrue(any(row["binding_mode"] == "bound-method"
                            for row in sites))

    def test_unrepresented_graph_sites_are_separate(self) -> None:
        mapping = self.report["mapping"]
        rows = self.report["unrepresented_graph_sites_in_source_order"]
        self.assertEqual(mapping["unrepresented_graph_call_site_count"],
                         len(rows))
        self.assertEqual(
            mapping["reachable_graph_call_site_count"],
            mapping["represented_graph_call_site_count"] + len(rows))
        self.assertTrue(all("PZCSL204" in row["blocker_codes"]
                            for row in rows))

    def test_resigned_span_callee_proven_order_and_duplicate_tampering(
            self) -> None:
        mutations = []

        span = copy.deepcopy(self.report)
        span["sites_in_source_order"][0]["span"]["column"] += 1
        mutations.append(("span", span))

        callee = copy.deepcopy(self.report)
        callee["sites_in_source_order"][0]["callee_source"] += ".tampered"
        mutations.append(("callee", callee))

        proven = copy.deepcopy(self.report)
        exact = next(row for row in proven["sites_in_source_order"]
                     if row["classification"] == "proven-single-internal")
        exact["proven"] = False
        mutations.append(("proven", proven))

        finite = copy.deepcopy(self.report)
        candidate = next(row for row in finite["sites_in_source_order"]
                         if row["classification"] == "finite-non-proven")
        candidate["proven"] = True
        mutations.append(("finite-promotion", finite))

        order = copy.deepcopy(self.report)
        order["sites_in_source_order"][0:2] = reversed(
            order["sites_in_source_order"][0:2])
        mutations.append(("order", order))

        duplicate = copy.deepcopy(self.report)
        duplicate_site = next(
            row for row in duplicate["sites_in_source_order"]
            if row["cfg_occurrence_count"] > 1)
        occurrence_index = duplicate_site["cfg_occurrence_indexes"][1]
        duplicate["cfg_occurrences_in_cfg_order"][occurrence_index][
            "numeric_call_site_id"] += 1
        mutations.append(("duplicate", duplicate))

        for name, tampered in mutations:
            with self.subTest(name=name):
                _resign(tampered)
                with self.assertRaises(ActiveCallSiteLoweringError):
                    validate_active_call_site_lowering_report(
                        ROOT, tampered, active_graph=self.active_graph)


if __name__ == "__main__":
    unittest.main()
