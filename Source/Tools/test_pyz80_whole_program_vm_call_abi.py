#!/usr/bin/env python3
"""Semantic and fresh-graph tests for the whole-program call ABI proof."""

from __future__ import annotations

import copy
import unittest
from collections import Counter
from pathlib import Path

import pyz80_compiler.whole_program_vm_call_abi as call_abi
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_call_site_lowering import (
    analyze_active_call_site_lowering,
)
from pyz80_compiler.whole_program_vm_call_abi import (
    WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
    WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
    WholeProgramVMCallABIError,
    analyze_whole_program_vm_call_abi,
    execute_call_binding_oracle,
    validate_whole_program_vm_call_abi_report,
)


ROOT = Path(__file__).resolve().parents[2]


def _target(
        numeric: int, mapping: list[dict[str, object]], *,
        callable_id: str = "fixture::target@1",
        ) -> dict[str, object]:
    return {
        "numeric_function_id": numeric,
        "callable_id": callable_id,
        "parameter_destination_map": mapping,
    }


def _descriptor(
        mode: str, target: dict[str, object], *,
        classification: str = "proven-single-internal",
        ) -> dict[str, object]:
    return {
        "numeric_call_site_id": 7,
        "classification": classification,
        "binding_mode": mode,
        "target_descriptors": [target],
    }


class CallABIBindingOracleTests(unittest.TestCase):
    def test_bound_receiver_is_preserved(self) -> None:
        receiver = object()
        descriptor = _descriptor("bound-method", _target(3, [{
            "destination_parameter": "self",
            "destination_kind": "positional-or-keyword",
            "source_kind": "receiver",
            "source_value": "%receiver",
        }, {
            "destination_parameter": "value",
            "destination_kind": "positional-or-keyword",
            "source_kind": "argument",
            "source_value": "%argument",
        }]))
        result = execute_call_binding_oracle(
            descriptor, {"%receiver": receiver, "%argument": 19})
        self.assertIs(result["bound_parameters"]["self"], receiver)
        self.assertEqual(result["bound_parameters"]["value"], 19)

    def test_classmethod_receiver_is_preserved(self) -> None:
        class_object = object()
        descriptor = _descriptor("classmethod", _target(9, [{
            "destination_parameter": "cls",
            "destination_kind": "positional-or-keyword",
            "source_kind": "receiver",
            "source_value": "%class-object",
        }]))
        result = execute_call_binding_oracle(
            descriptor, {"%class-object": class_object})
        self.assertIs(result["bound_parameters"]["cls"], class_object)

    def test_constructor_returns_allocated_object_after_init_binding(self) -> None:
        allocated = object()
        descriptor = _descriptor("constructor", _target(4, [{
            "destination_parameter": "self",
            "destination_kind": "positional-or-keyword",
            "source_kind": "allocated-object",
            "source_value": "$allocated-object",
        }, {
            "destination_parameter": "value",
            "destination_kind": "positional-or-keyword",
            "source_kind": "argument",
            "source_value": "%value",
        }]))
        result = execute_call_binding_oracle(
            descriptor, {"%value": 23}, allocated_object=allocated)
        self.assertIs(result["bound_parameters"]["self"], allocated)
        self.assertIs(result["return_value"], allocated)

    def test_keyword_and_default_binding(self) -> None:
        descriptor = _descriptor("free", _target(5, [{
            "destination_parameter": "named",
            "destination_kind": "positional-or-keyword",
            "source_kind": "argument",
            "source_value": "%keyword",
            "keyword": "named",
        }, {
            "destination_parameter": "optional",
            "destination_kind": "positional-or-keyword",
            "source_kind": "default",
            "source_value": "default-ast-sha",
        }]))
        result = execute_call_binding_oracle(
            descriptor, {"%keyword": 31}, defaults={"optional": 37})
        self.assertEqual(result["bound_parameters"], {
            "named": 31, "optional": 37})

    def test_nested_call_requires_and_retains_lexical_environment(self) -> None:
        descriptor = _descriptor("nested", _target(6, []))
        with self.assertRaises(WholeProgramVMCallABIError) as raised:
            execute_call_binding_oracle(descriptor, {})
        self.assertEqual(raised.exception.code, "PZCABI303")
        environment = {"captured": 41}
        result = execute_call_binding_oracle(
            descriptor, {}, lexical_environment=environment)
        self.assertIs(result["lexical_environment"], environment)

    def test_finite_dispatch_is_fail_closed_without_guarded_selection(self) -> None:
        descriptor = _descriptor(
            "free", _target(8, []), classification="finite-non-proven")
        with self.assertRaises(WholeProgramVMCallABIError) as raised:
            execute_call_binding_oracle(descriptor, {})
        self.assertEqual(raised.exception.code, "PZCABI301")
        result = execute_call_binding_oracle(
            descriptor, {}, finite_target_numeric_function_id=8)
        self.assertTrue(result["finite_selection_was_runtime_guarded"])

    def test_super_proxy_is_never_executed_as_target_self(self) -> None:
        descriptor = _descriptor("super", _target(10, [{
            "destination_parameter": "self",
            "destination_kind": "positional-or-keyword",
            "source_kind": "receiver",
            "source_value": "%super-proxy",
        }]))
        with self.assertRaises(WholeProgramVMCallABIError) as raised:
            execute_call_binding_oracle(
                descriptor, {"%super-proxy": object()})
        self.assertEqual(raised.exception.code, "PZCABI214")

    def test_generated_dataclass_binds_real_self_and_literal_defaults(self) -> None:
        instance = object()
        schema = {
            "fields": [{"name": "required"}, {"name": "optional"}],
        }
        target = _target(11, [{
            "destination_parameter": "self",
            "destination_kind": "positional-or-keyword",
            "source_kind": "receiver",
            "source_value": "self",
        }, {
            "destination_parameter": "required",
            "destination_kind": "positional-or-keyword",
            "source_kind": "argument",
            "source_value": "%required",
        }, {
            "destination_parameter": "optional",
            "destination_kind": "positional-or-keyword",
            "source_kind": "literal-default",
            "source_value": 29,
        }])
        descriptor = _descriptor(
            "generated-dataclass-init", target,
            classification="proven-core-generated-dataclass-init")
        descriptor["generated_dataclass_init"] = schema
        result = execute_call_binding_oracle(
            descriptor, {"self": instance, "%required": 17})
        self.assertIs(result["bound_parameters"]["self"], instance)
        self.assertEqual(result["generated_field_state"], {
            "required": 17, "optional": 29})


def _resign(report: dict[str, object]) -> None:
    report["semantic_sha256"] = call_abi._json_sha256(
        call_abi._semantic_payload(report))


class WholeProgramVMCallABIFreshGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.active_graph = analyze_active_call_graph(ROOT)
        cls.call_lowering = analyze_active_call_site_lowering(
            ROOT, active_graph=cls.active_graph)
        cls.report = analyze_whole_program_vm_call_abi(
            ROOT, active_graph=cls.active_graph,
            call_site_lowering=cls.call_lowering)

    def test_one_descriptor_per_represented_cfg_occurrence(self) -> None:
        self.assertEqual(self.report["format"],
                         WHOLE_PROGRAM_VM_CALL_ABI_FORMAT)
        self.assertEqual(self.report["status"],
                         WHOLE_PROGRAM_VM_CALL_ABI_STATUS)
        self.assertFalse(self.report["live"])
        census = self.report["census"]
        self.assertEqual(
            census["call_occurrence_descriptor_count"],
            self.call_lowering["mapping"][
                "cfg_python_call_occurrence_count"])
        self.assertEqual(
            census["represented_call_site_count"],
            self.call_lowering["mapping"][
                "represented_graph_call_site_count"])
        descriptors = self.report[
            "occurrence_abi_descriptors_in_cfg_order"]
        self.assertEqual(
            [row["numeric_abi_descriptor_id"] for row in descriptors],
            list(range(len(descriptors))))

    def test_function_ids_and_ssa_receiver_chains_are_concrete(self) -> None:
        functions = self.report["function_id_table"]
        self.assertEqual(
            [row["numeric_function_id"] for row in functions],
            list(range(len(functions))))
        rows = self.report["occurrence_abi_descriptors_in_cfg_order"]
        bound = [row for row in rows if row["binding_mode"] in {
            "bound-method", "common-dispatch", "super", "classmethod"}]
        self.assertTrue(bound)
        exact_bound = [row for row in bound
                       if row["callable_ssa_provenance"]["status"] == "exact"]
        self.assertTrue(exact_bound)
        for row in exact_bound:
            provenance = row["callable_ssa_provenance"]
            self.assertEqual(provenance["require_callable"]["op"],
                             "require-callable")
            self.assertEqual(provenance["source_operation"],
                             "load-attribute")
            self.assertEqual(provenance["receiver_status"], "exact")
            self.assertIsNotNone(row["receiver_value"])
        super_rows = [row for row in rows
                      if row["binding_mode"] == "super"]
        self.assertTrue(super_rows)
        self.assertTrue(all(
            "PZCABI214" in row["blocker_codes"] for row in super_rows))
        self.assertEqual(
            self.report["census"]["blocker_descriptor_counts"]["PZCABI214"],
            len(super_rows))
        generated = [row for row in rows if row["binding_mode"] ==
                     "generated-dataclass-init"]
        self.assertTrue(generated)
        self.assertTrue(all(
            row["classification"] ==
            "proven-core-generated-dataclass-init" and
            not row["blocker_codes"] and
            row["receiver_value"] == "self" and
            row["generated_dataclass_init"]["fields"]
            for row in generated))

    def test_constructor_nested_and_finite_contracts_are_explicit(self) -> None:
        rows = self.report["occurrence_abi_descriptors_in_cfg_order"]
        constructors = [row for row in rows
                        if row["binding_mode"] == "constructor"]
        self.assertTrue(constructors)
        for row in constructors:
            self.assertEqual(
                [step["operation"] for step in row["constructor_sequence"]],
                ["allocate-instance", "bind-init-self", "invoke-__init__",
                 "return-allocated-instance"])
            self.assertNotIn("PZCABI211", row["blocker_codes"])
        nested = [row for row in rows if row["binding_mode"] == "nested"]
        self.assertTrue(nested)
        self.assertTrue(all(
            target["lexical_owner"] is not None
            for row in nested for target in row["target_descriptors"]))
        finite = [row for row in rows
                  if row["classification"] == "finite-non-proven"]
        self.assertTrue(finite)
        self.assertTrue(all(
            row["finite_dispatch_table"]["proven"] is False and
            row["finite_dispatch_table"]["runtime_identity_guard_required"]
            for row in finite))

    def test_current_graph_census_is_dynamic_and_self_consistent(self) -> None:
        census = self.report["census"]
        rows = self.report["occurrence_abi_descriptors_in_cfg_order"]
        self.assertEqual(sum(census["classification_counts"].values()),
                         len(rows))
        self.assertEqual(sum(census["binding_mode_counts"].values()),
                         len(rows))
        self.assertEqual(
            census["exact_callable_ssa_provenance_count"] +
            census["ambiguous_callable_ssa_provenance_count"], len(rows))
        self.assertFalse(
            self.report["proof"]["current_vm_backend_consumes_call_abi"])

    def test_unrepresented_sites_are_explicit_dynamic_prerequisites(self) -> None:
        expected = self.call_lowering[
            "unrepresented_graph_sites_in_source_order"]
        prerequisite = self.report["call_site_lowering_prerequisites"]
        census = self.report["census"]
        classifications = dict(sorted(Counter(
            str(row["classification"]) for row in expected).items()))
        self.assertTrue(expected)
        self.assertEqual(
            prerequisite["unrepresented_graph_sites_in_source_order"],
            expected)
        self.assertEqual(
            prerequisite["unrepresented_graph_call_site_count"],
            len(expected))
        self.assertEqual(
            prerequisite[
                "unrepresented_numeric_call_site_ids_in_source_order"],
            [int(row["numeric_call_site_id"]) for row in expected])
        self.assertEqual(
            prerequisite["unrepresented_call_site_ids_in_source_order"],
            [str(row["call_site_id"]) for row in expected])
        self.assertEqual(
            prerequisite["unrepresented_classification_counts"],
            classifications)
        self.assertEqual(
            census["unrepresented_graph_call_site_count"], len(expected))
        self.assertEqual(
            census["unrepresented_graph_call_site_classification_counts"],
            classifications)
        self.assertEqual(
            census["prerequisite_blocker_counts"],
            {"PZCABI215": len(expected)})
        blocker = next(row for row in self.report["live_blockers"]
                       if row["code"] == "PZCABI215")
        self.assertEqual(blocker["count"], len(expected))

    def test_descriptor_identity_is_occurrence_specific(self) -> None:
        proof = self.report["proof"]
        self.assertTrue(proof[
            "backend_must_address_numeric_abi_descriptor_id_and_cfg_occurrence"])
        self.assertTrue(proof[
            "numeric_call_site_id_alone_is_not_backend_dispatch_identity"])
        descriptors = self.report[
            "occurrence_abi_descriptors_in_cfg_order"]
        for site in self.report["site_abi_descriptors_in_source_order"]:
            for descriptor_id in site["numeric_abi_descriptor_ids"]:
                descriptor = descriptors[descriptor_id]
                self.assertEqual(
                    descriptor["numeric_call_site_id"],
                    site["numeric_call_site_id"])
                self.assertEqual(
                    descriptor["numeric_abi_descriptor_id"], descriptor_id)

    def test_resigned_exact_receiver_target_map_order_and_finite_tampering(
            self) -> None:
        mutations = []
        receiver = copy.deepcopy(self.report)
        receiver_row = next(
            row for row in receiver["occurrence_abi_descriptors_in_cfg_order"]
            if row["receiver_value"] is not None)
        receiver_row["receiver_value"] = "%invented-receiver"
        mutations.append(receiver)

        target = copy.deepcopy(self.report)
        target_row = next(
            row for row in target["occurrence_abi_descriptors_in_cfg_order"]
            if row["target_numeric_function_ids"])
        target_row["target_numeric_function_ids"][0] += 1
        mutations.append(target)

        parameter_map = copy.deepcopy(self.report)
        map_row = next(
            row for row in parameter_map[
                "occurrence_abi_descriptors_in_cfg_order"]
            if row["target_descriptors"] and
            row["target_descriptors"][0]["parameter_destination_map"])
        map_row["target_descriptors"][0]["parameter_destination_map"][0][
            "destination_parameter"] = "invented"
        mutations.append(parameter_map)

        order = copy.deepcopy(self.report)
        order["occurrence_abi_descriptors_in_cfg_order"][0:2] = reversed(
            order["occurrence_abi_descriptors_in_cfg_order"][0:2])
        mutations.append(order)

        finite = copy.deepcopy(self.report)
        finite_row = next(
            row for row in finite["occurrence_abi_descriptors_in_cfg_order"]
            if row["finite_dispatch_table"] is not None)
        finite_row["finite_dispatch_table"]["proven"] = True
        mutations.append(finite)

        for index, tampered in enumerate(mutations):
            with self.subTest(index=index):
                _resign(tampered)
                with self.assertRaises(WholeProgramVMCallABIError):
                    validate_whole_program_vm_call_abi_report(
                        ROOT, tampered, active_graph=self.active_graph,
                        call_site_lowering=self.call_lowering)

    def test_resigned_super_prerequisite_and_identity_tampering(self) -> None:
        mutations = []

        super_unblocked = copy.deepcopy(self.report)
        super_row = next(
            row for row in super_unblocked[
                "occurrence_abi_descriptors_in_cfg_order"]
            if row["binding_mode"] == "super")
        super_row["blocker_codes"].remove("PZCABI214")
        mutations.append(super_unblocked)

        prerequisite_dropped = copy.deepcopy(self.report)
        prerequisite_dropped.pop("call_site_lowering_prerequisites")
        mutations.append(prerequisite_dropped)

        prerequisite_unblocked = copy.deepcopy(self.report)
        prerequisite_unblocked["live_blockers"] = [
            row for row in prerequisite_unblocked["live_blockers"]
            if row["code"] != "PZCABI215"]
        mutations.append(prerequisite_unblocked)

        identity_unproved = copy.deepcopy(self.report)
        identity_unproved["proof"].pop(
            "numeric_call_site_id_alone_is_not_backend_dispatch_identity")
        mutations.append(identity_unproved)

        for index, tampered in enumerate(mutations):
            with self.subTest(index=index):
                _resign(tampered)
                with self.assertRaises(WholeProgramVMCallABIError):
                    validate_whole_program_vm_call_abi_report(
                        ROOT, tampered, active_graph=self.active_graph,
                        call_site_lowering=self.call_lowering)


if __name__ == "__main__":
    unittest.main()
