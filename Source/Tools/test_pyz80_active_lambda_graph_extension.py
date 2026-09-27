#!/usr/bin/env python3
"""Tests for the non-promoting active lambda call-graph overlay."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import pyz80_compiler.active_lambda_graph_extension as lambda_overlay
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_callable_flow import analyze_active_callable_flow
from pyz80_compiler.active_lambda_graph_extension import (
    ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT,
    ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS,
    ActiveLambdaGraphExtensionError,
    analyze_active_lambda_graph_extension,
    validate_active_lambda_graph_extension_report,
)
from pyz80_compiler.lambda_callable_units import (
    analyze_lambda_callable_units,
)


ROOT = Path(__file__).resolve().parents[2]


def _resign(report: dict[str, object]) -> None:
    report["semantic_sha256"] = lambda_overlay._json_sha256(
        lambda_overlay._semantic_payload(report))


class ActiveLambdaGraphExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.active_graph = analyze_active_call_graph(ROOT)
        cls.callable_flow = analyze_active_callable_flow(
            ROOT, active_graph=cls.active_graph)
        cls.lambda_units = analyze_lambda_callable_units(
            ROOT, active_graph=cls.active_graph,
            callable_flow=cls.callable_flow)
        cls.base_snapshot = copy.deepcopy(cls.active_graph)
        cls.base_reachability = tuple(cls.active_graph["call_graph"][
            "proven_reachable_callable_ids"])
        cls.report = analyze_active_lambda_graph_extension(
            ROOT, active_graph=cls.active_graph,
            callable_flow=cls.callable_flow,
            lambda_units=cls.lambda_units)
        cls.candidates = cls.report[
            "candidate_functions_in_source_order"]
        cls.sites = cls.report[
            "base_call_site_overlay_in_source_order"]

    def test_exact_census_bindings_and_non_live_status(self) -> None:
        self.assertEqual(self.report["format"],
                         ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT)
        self.assertEqual(self.report["status"],
                         ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS)
        self.assertFalse(self.report["live"])
        self.assertEqual(self.report["census"], {
            "blocker_counts": {
                "PZLGO201": 6,
                "PZLGO202": 8,
                "PZLGO203": 4,
                "PZLGO205": 1,
                "PZLGO206": 1,
                "PZLGO207": 4,
                "PZLGO208": 1,
            },
            "candidate_function_count": 7,
            "candidate_reference_count": 12,
            "dynamic_source_reference_count": 1,
            "existing_bound_method_candidate_count": 1,
            "finite_candidate_table_site_count": 8,
            "incomplete_unresolved_site_count": 1,
            "lambda_candidate_function_count": 6,
            "mapped_base_call_site_count": 9,
            "unique_candidate_function_reference_count": 7,
        })
        bindings = self.report["input_bindings"]
        self.assertEqual(
            bindings["active_call_graph_semantic_sha256"],
            self.active_graph["semantic_sha256"])
        self.assertEqual(
            bindings["active_call_graph_content_sha256"],
            lambda_overlay._json_sha256(self.active_graph))
        self.assertEqual(
            bindings["base_call_graph_semantic_sha256"],
            self.active_graph["call_graph"]["semantic_sha256"])
        self.assertEqual(
            bindings["active_callable_flow_semantic_sha256"],
            self.callable_flow["semantic_sha256"])
        self.assertEqual(
            bindings["lambda_callable_units_semantic_sha256"],
            self.lambda_units["semantic_sha256"])
        blockers = {row["code"]: row for row in
                    self.report["live_blockers"]}
        self.assertEqual(blockers["PZLGO208"]["count"], 1)
        self.assertIn("does not consume", blockers["PZLGO208"]["detail"])

    def test_six_lambda_cfgs_and_target_audio_play_are_inventoried(
            self) -> None:
        self.assertEqual(
            [row["numeric_candidate_function_id"]
             for row in self.candidates], list(range(1, 8)))
        lambda_candidates = [
            row for row in self.candidates
            if row["candidate_kind"] == "lambda-callable"]
        bound_candidates = [
            row for row in self.candidates
            if row["candidate_kind"] ==
            "existing-bound-method-reference"]
        self.assertEqual(len(lambda_candidates), 6)
        self.assertEqual(len(bound_candidates), 1)

        units_by_source = {
            row["source_callable_value_id"]: row
            for row in self.lambda_units[
                "lambda_callable_units_in_source_order"]}
        self.assertEqual(
            {row["source_callable_value_id"] for row in lambda_candidates},
            set(units_by_source))
        self.assertEqual(
            {row["lambda_callable_id"] for row in lambda_candidates},
            {row["lambda_callable_id"] for row in units_by_source.values()})
        for candidate in lambda_candidates:
            unit = units_by_source[candidate["source_callable_value_id"]]
            self.assertEqual(candidate["body"]["expression_cfg"],
                             unit["body"]["expression_cfg"])
            self.assertEqual(candidate["body"]["ast_sha256"],
                             unit["body"]["ast_sha256"])
            self.assertIsNone(candidate["base_target_callable_id"])

        reference = self.lambda_units[
            "existing_callable_references_in_source_order"][0]
        bound = bound_candidates[0]
        target = reference["target_callable_id"]
        self.assertIn("::TargetAudio.play@", str(target))
        self.assertEqual(bound["source_callable_value_id"],
                         reference["source_callable_value_id"])
        self.assertEqual(bound["base_target_callable_id"], target)
        self.assertTrue(bound["base_target_present"])
        self.assertFalse(bound["base_target_proven_reachable"])
        base_callables = {
            row["callable_id"]: row for row in self.active_graph[
                "callable_inventory"]["callables"]}
        self.assertEqual(
            bound["base_target_cfg_semantic_sha256"],
            base_callables[target]["cfg"]["semantic_sha256"])
        self.assertIsNone(bound["body"])

    def test_only_eight_complete_obligations_become_finite_tables(
            self) -> None:
        flow_by_site = {
            row["call_site_id"]: row for row in self.callable_flow[
                "unresolved_local_sites_in_source_order"]}
        overlay_by_site = {
            row["base_call_site_id"]: row for row in self.sites}
        self.assertEqual(set(overlay_by_site), set(flow_by_site))
        complete_ids = {
            site_id for site_id, row in flow_by_site.items()
            if row["incoming_candidates_complete"]}
        finite_ids = {
            site_id for site_id, row in overlay_by_site.items()
            if row["overlay_resolution_kind"] == "finite-candidate-table"}
        self.assertEqual(finite_ids, complete_ids)
        self.assertEqual(len(finite_ids), 8)
        finite = [row for row in self.sites
                  if row["overlay_resolution_kind"] ==
                  "finite-candidate-table"]
        self.assertEqual(
            [row["numeric_finite_candidate_table_id"] for row in finite],
            list(range(1, 9)))
        self.assertEqual(len({row["finite_candidate_table_id"]
                              for row in finite}), 8)
        for row in finite:
            flow = flow_by_site[row["base_call_site_id"]]
            self.assertEqual(row["base_resolution_kind"],
                             "unresolved-local-callable")
            self.assertTrue(row["base_graph_call_site_preserved"])
            self.assertEqual(
                [candidate["source_callable_value_id"]
                 for candidate in row["candidates"]],
                flow["candidate_callable_value_ids"])
            self.assertEqual(row["candidate_count"],
                             len(row["candidates"]))
            self.assertEqual(row["dynamic_source_ids"], [])

    def test_contact_dynamic_getattr_stays_the_only_unresolved_site(
            self) -> None:
        incomplete = [
            row for row in self.sites
            if row["overlay_resolution_kind"] ==
            "incomplete-dynamic-unresolved"]
        self.assertEqual(len(incomplete), 1)
        contact = incomplete[0]
        self.assertEqual(contact["callee_name"], "contact")
        self.assertFalse(contact["incoming_candidates_complete"])
        self.assertEqual(contact["candidate_count"], 0)
        self.assertEqual(contact["candidates"], [])
        self.assertIsNone(contact["numeric_finite_candidate_table_id"])
        self.assertIsNone(contact["finite_candidate_table_id"])
        self.assertEqual(len(contact["dynamic_source_ids"]), 1)
        dynamic_by_id = {
            row["dynamic_source_id"]: row for row in self.callable_flow[
                "dynamic_sources_in_source_order"]}
        dynamic = dynamic_by_id[contact["dynamic_source_ids"][0]]
        self.assertEqual(dynamic["kind"], "dynamic-getattr")
        self.assertEqual(dynamic["attribute_name"], "player_contact")

    def test_base_graph_is_immutable_and_reachability_is_not_promoted(
            self) -> None:
        self.assertEqual(self.active_graph, self.base_snapshot)
        self.assertEqual(
            tuple(self.active_graph["call_graph"][
                "proven_reachable_callable_ids"]),
            self.base_reachability)
        base_sites = {
            row["call_site_id"]: row for row in self.active_graph[
                "call_graph"]["call_sites"]}
        for row in self.sites:
            base = base_sites[row["base_call_site_id"]]
            self.assertEqual(base["resolution"]["kind"],
                             "unresolved-local-callable")
            self.assertFalse(row["proven"])
            self.assertFalse(row["promotion_permitted"])
            self.assertFalse(row["dispatch_integrated"])
            self.assertTrue(all(
                candidate["proven"] is False and
                candidate["candidate_only"] is True
                for candidate in row["candidates"]))
        self.assertTrue(all(
            row["candidate_only"] is True and
            row["proven"] is False and
            row["graph_reachable"] is False and
            row["runtime_integrated"] is False
            for row in self.candidates))
        proof = self.report["proof"]
        self.assertTrue(proof["candidate_sets_never_become_proven_edges"])
        self.assertTrue(proof[
            "base_graph_content_sha256_before_after_equal"])
        self.assertFalse(proof["base_graph_mutated_or_resigned"])
        self.assertFalse(proof["overlay_consumed_by_base_graph_or_backend"])

    def test_json_seal_and_all_derived_hashes_are_deterministic(self) -> None:
        repeated = lambda_overlay._build_report(
            self.active_graph, self.callable_flow, self.lambda_units)
        self.assertEqual(repeated, self.report)
        self.assertEqual(
            self.report["semantic_sha256"],
            lambda_overlay._json_sha256(
                lambda_overlay._semantic_payload(self.report)))
        canonical = json.loads(lambda_overlay._json_bytes(
            self.report).decode("utf-8"))
        self.assertEqual(canonical, self.report)
        for row in self.candidates:
            self.assertRegex(row["candidate_function_id"],
                             r"^lambda-overlay-candidate:[0-9a-f]{64}$")
        for row in self.sites:
            table_id = row["finite_candidate_table_id"]
            if table_id is not None:
                self.assertRegex(
                    table_id, r"^lambda-overlay-table:[0-9a-f]{64}$")

    def test_unsigned_and_resigned_tampering_fail_closed(self) -> None:
        unsigned = copy.deepcopy(self.report)
        unsigned["candidate_functions_in_source_order"][0][
            "graph_reachable"] = True
        with self.assertRaises(ActiveLambdaGraphExtensionError) as caught:
            validate_active_lambda_graph_extension_report(
                ROOT, unsigned, active_graph=self.active_graph,
                callable_flow=self.callable_flow,
                lambda_units=self.lambda_units)
        self.assertEqual(caught.exception.code, "PZLGO410")

        mutations: list[dict[str, object]] = []

        promoted = copy.deepcopy(self.report)
        promoted["candidate_functions_in_source_order"][0][
            "graph_reachable"] = True
        mutations.append(promoted)

        cfg = copy.deepcopy(self.report)
        lambda_row = next(row for row in cfg[
            "candidate_functions_in_source_order"]
                          if row["candidate_kind"] == "lambda-callable")
        lambda_row["body"]["expression_cfg"]["result_kind"] = "forged"
        mutations.append(cfg)

        target = copy.deepcopy(self.report)
        bound_row = next(row for row in target[
            "candidate_functions_in_source_order"]
                         if row["base_target_callable_id"] is not None)
        bound_row["base_target_cfg_semantic_sha256"] = "0" * 64
        mutations.append(target)

        finite = copy.deepcopy(self.report)
        finite_row = next(row for row in finite[
            "base_call_site_overlay_in_source_order"]
                          if row["finite_candidate_table_id"] is not None)
        finite_row["finite_candidate_table_id"] = (
            "lambda-overlay-table:" + "0" * 64)
        mutations.append(finite)

        dynamic = copy.deepcopy(self.report)
        contact = next(row for row in dynamic[
            "base_call_site_overlay_in_source_order"]
                       if row["callee_name"] == "contact")
        contact["overlay_resolution_kind"] = "finite-candidate-table"
        mutations.append(dynamic)

        binding = copy.deepcopy(self.report)
        binding["input_bindings"][
            "active_call_graph_content_sha256"] = "0" * 64
        mutations.append(binding)

        order = copy.deepcopy(self.report)
        order["candidate_functions_in_source_order"][0:2] = reversed(
            order["candidate_functions_in_source_order"][0:2])
        mutations.append(order)

        for index, tampered in enumerate(mutations):
            with self.subTest(index=index):
                _resign(tampered)
                with self.assertRaises(ActiveLambdaGraphExtensionError):
                    validate_active_lambda_graph_extension_report(
                        ROOT, tampered, active_graph=self.active_graph,
                        callable_flow=self.callable_flow,
                        lambda_units=self.lambda_units)


if __name__ == "__main__":
    unittest.main()
