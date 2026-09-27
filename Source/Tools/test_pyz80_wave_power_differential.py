#!/usr/bin/env python3
"""Focused tests for wave_power differential input and trace validation."""

from __future__ import annotations

import copy
import unittest

import pyz80_wave_power_differential as differential
from pyz80_translation_checkpoint import CHECKPOINT_FORMAT


def _digest(label: str) -> str:
    return differential._sha256(label.encode("utf-8"))


def _report_records(
        reports: dict[str, dict[str, object]],
        ) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for stage, relative in differential.CHECKPOINT_REPORT_PATHS.items():
        raw = differential._canonical(reports[stage])
        result[stage] = {
            "stage": stage,
            "path": relative.as_posix(),
            "present": True,
            "bytes": len(raw),
            "sha256": differential._sha256(raw),
        }
    return result


def _resign_checkpoint(checkpoint: dict[str, object]) -> None:
    payload = {key: value for key, value in checkpoint.items()
               if key != "semantic_sha256"}
    checkpoint["semantic_sha256"] = differential._sha256(
        differential._canonical(payload))


def _fixture() -> tuple[
        dict[str, object], dict[str, dict[str, object]],
        dict[str, dict[str, object]], bytes]:
    graph_sha = _digest("graph")
    lowering_sha = _digest("lowering")
    call_abi_sha = _digest("call-abi")
    artifact_sha = _digest("artifact")
    proof_sha = _digest("proof")
    image = b"synthetic-pzvt-image"
    target_sha = differential._sha256(image)
    reports: dict[str, dict[str, object]] = {
        "active_call_graph": {
            "semantic_sha256": graph_sha,
            "call_graph": {
                "proven_reachable_callable_ids": [
                    "example::other@1", differential.CALLABLE_ID,
                ],
            },
        },
        "active_call_site_lowering": {
            "semantic_sha256": lowering_sha,
            "active_call_graph_semantic_sha256": graph_sha,
        },
        "whole_program_vm_call_abi": {
            "semantic_sha256": call_abi_sha,
            "active_call_graph_semantic_sha256": graph_sha,
            "call_site_lowering_semantic_sha256": lowering_sha,
        },
        "whole_program_vm": {
            "artifact_semantic_sha256": artifact_sha,
            "active_call_graph_semantic_sha256": graph_sha,
            "call_abi_binding": {
                "active_call_site_lowering_semantic_sha256": lowering_sha,
                "whole_program_vm_call_abi_semantic_sha256": call_abi_sha,
            },
            "target_bytecode": {
                "bytes": len(image),
                "sha256": target_sha,
            },
            "host_proof": {"sha256": proof_sha},
        },
        "whole_program_vm_stack_bound": {
            "binding": {
                "active_call_graph_semantic_sha256": graph_sha,
                "artifact_semantic_sha256": artifact_sha,
                "target_bytecode_sha256": target_sha,
                "proof_bytecode_sha256": proof_sha,
            },
        },
    }
    records = _report_records(reports)
    report_rows = [records[stage] for stage in sorted(records)]
    checkpoint: dict[str, object] = {
        "format": CHECKPOINT_FORMAT,
        "coherent": True,
        "live_claim": False,
        "snapshot_sha256": differential._sha256(
            differential._canonical(report_rows)),
        "stage_semantic_sha256": {
            "active_call_graph": graph_sha,
            "active_call_site_lowering": lowering_sha,
            "whole_program_vm_call_abi": call_abi_sha,
            "whole_program_vm_artifact": artifact_sha,
        },
        "report_files": report_rows,
        "bindings": differential._expected_checkpoint_bindings(reports),
        "issue_count": 0,
        "issues": [],
        "proof_scope": {
            "cross_artifact_binding_only": True,
            "stage_validators_are_still_required": True,
            "never_promotes_live": True,
        },
    }
    _resign_checkpoint(checkpoint)
    return checkpoint, reports, records, image


class WavePowerDifferentialInputTests(unittest.TestCase):
    def test_complete_synthetic_checkpoint_binding_is_deterministic(
            self) -> None:
        checkpoint, reports, records, image = _fixture()
        differential._validate_artifact_bindings(
            checkpoint, reports, records, image)
        repeated = _fixture()
        self.assertEqual(repeated, (checkpoint, reports, records, image))
        self.assertEqual(
            checkpoint["snapshot_sha256"],
            differential._sha256(differential._canonical(
                checkpoint["report_files"])))

    def test_unsigned_and_resigned_checkpoint_tamper_fail_closed(self) -> None:
        checkpoint, reports, records, image = _fixture()

        unsigned = copy.deepcopy(checkpoint)
        unsigned["snapshot_sha256"] = "0" * 64
        with self.assertRaises(differential.DifferentialError):
            differential._validate_artifact_bindings(
                unsigned, reports, records, image)

        snapshot = copy.deepcopy(checkpoint)
        snapshot["snapshot_sha256"] = "0" * 64
        _resign_checkpoint(snapshot)

        file_hash = copy.deepcopy(checkpoint)
        file_hash["report_files"][0]["sha256"] = "0" * 64
        file_hash["snapshot_sha256"] = differential._sha256(
            differential._canonical(file_hash["report_files"]))
        _resign_checkpoint(file_hash)

        binding_table = copy.deepcopy(checkpoint)
        binding_table["bindings"][0]["actual"] = "0" * 64
        binding_table["bindings"][0]["matches"] = True
        _resign_checkpoint(binding_table)

        stage_semantic = copy.deepcopy(checkpoint)
        stage_semantic["stage_semantic_sha256"][
            "active_call_graph"] = "0" * 64
        _resign_checkpoint(stage_semantic)

        for index, tampered in enumerate((
                snapshot, file_hash, binding_table, stage_semantic)):
            with self.subTest(index=index):
                with self.assertRaises(differential.DifferentialError):
                    differential._validate_artifact_bindings(
                        tampered, reports, records, image)

    def test_artifact_hash_and_cross_stage_binding_tamper_fail_closed(
            self) -> None:
        checkpoint, reports, records, image = _fixture()

        graph_binding = copy.deepcopy(reports)
        graph_binding["whole_program_vm"][
            "active_call_graph_semantic_sha256"] = _digest("other-graph")

        stack_binding = copy.deepcopy(reports)
        stack_binding["whole_program_vm_stack_bound"]["binding"][
            "target_bytecode_sha256"] = _digest("other-target")

        actual_record = copy.deepcopy(records)
        actual_record["whole_program_vm"]["sha256"] = "0" * 64

        cases = [
            (reports, records, image + b"tamper"),
            (graph_binding, records, image),
            (stack_binding, records, image),
            (reports, actual_record, image),
        ]
        for index, (case_reports, case_records, case_image) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(differential.DifferentialError):
                    differential._validate_artifact_bindings(
                        checkpoint, case_reports, case_records, case_image)

    def test_wave_power_function_table_binding_is_exact(self) -> None:
        _checkpoint, reports, _records, _image = _fixture()
        graph = reports["active_call_graph"]
        self.assertEqual(differential._wave_power_function_index(
            graph, {"functions": [10, 11]}), 1)

        missing = copy.deepcopy(graph)
        missing["call_graph"]["proven_reachable_callable_ids"] = [
            "example::other@1", "example::absent@2"]
        duplicate = copy.deepcopy(graph)
        duplicate["call_graph"]["proven_reachable_callable_ids"] = [
            differential.CALLABLE_ID, differential.CALLABLE_ID]
        cases = [
            (missing, {"functions": [10, 11]}),
            (duplicate, {"functions": [10, 11]}),
            (graph, {"functions": [10]}),
            (graph, {"functions": "malformed"}),
        ]
        for index, (case_graph, program) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(differential.DifferentialError):
                    differential._wave_power_function_index(
                        case_graph, program)

    def test_adapter_descriptor_binding_is_fail_closed(self) -> None:
        descriptor = {
            "op": "python-compare",
            "argument_count": 3,
            "attributes": {"python_data_model": True},
            "semantic_sha256": _digest("adapter"),
        }
        adapter_table = [{} for _index in range(8)]
        adapter_table[7] = descriptor
        program = {
            "functions": [0],
            "units": [{
                "blocks": [{
                    "instructions": [{
                        "adapter_id": 7,
                        "arguments": [{"kind": "constant", "id": 0}],
                    }],
                    "terminator": {},
                }],
            }],
            "constants": ["lt"],
        }
        status = {"adapter_table": adapter_table}
        self.assertEqual(
            differential._adapter_contract(program, status, 0),
            (7, 0, descriptor["semantic_sha256"]))
        tampered = copy.deepcopy(status)
        tampered["adapter_table"][7]["argument_count"] = 2
        with self.assertRaises(differential.DifferentialError):
            differential._adapter_contract(program, tampered, 0)


class WavePowerDifferentialTraceTests(unittest.TestCase):
    OUTPUT = "2 20 2 5 10\r\n0 0 0\r\n1 10 1 7\r\n"

    def test_runner_rows_parse_deterministically_and_domain_is_exact(
            self) -> None:
        expected = {
            0: (0, ()),
            1: (10, (7,)),
            2: (20, (5, 10)),
        }
        parsed = differential._parse_c_rows(self.OUTPUT)
        self.assertEqual(parsed, expected)
        self.assertEqual(
            differential._parse_c_rows(self.OUTPUT.replace("\r\n", "\n")),
            expected)
        differential._validate_c_domain(parsed, first=0, last=2)

    def test_malformed_duplicate_and_incomplete_runner_rows_fail_closed(
            self) -> None:
        malformed = (
            "not integers",
            "0 1",
            "0 1 -1",
            "0 1 2 7",
            "0 1 0\n0 1 0\n",
            "0 1 0\n\n1 2 0\n",
        )
        for index, output in enumerate(malformed):
            with self.subTest(index=index):
                with self.assertRaises(differential.DifferentialError):
                    differential._parse_c_rows(output)

        parsed = differential._parse_c_rows("0 0 0\n2 20 0\n")
        with self.assertRaises(differential.DifferentialError):
            differential._validate_c_domain(parsed, first=0, last=2)
        parsed[1] = (10, ())
        parsed[3] = (30, ())
        with self.assertRaises(differential.DifferentialError):
            differential._validate_c_domain(parsed, first=0, last=2)

    def test_trace_and_result_comparison_is_exact_and_hash_stable(self) -> None:
        c_rows = differential._parse_c_rows(self.OUTPUT)
        rows = [
            differential._validated_result_row(
                0, 0, 0, [], c_rows),
            differential._validated_result_row(
                1, 10, 10, [7], c_rows),
            differential._validated_result_row(
                2, 20, 20, [5, 10], c_rows),
        ]
        self.assertEqual(rows, [
            {"charge": 0, "result": 0, "thresholds": []},
            {"charge": 1, "result": 10, "thresholds": [7]},
            {"charge": 2, "result": 20, "thresholds": [5, 10]},
        ])
        first_hash = differential._sha256(differential._canonical(rows))
        second_hash = differential._sha256(differential._canonical(
            copy.deepcopy(rows)))
        self.assertEqual(first_hash, second_hash)

        cases = (
            (1, 11, 10, [7]),
            (1, 10, 11, [7]),
            (1, 10, 10, [8]),
            (3, 30, 30, []),
        )
        for index, arguments in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(differential.DifferentialError):
                    differential._validated_result_row(*arguments, c_rows)


if __name__ == "__main__":
    unittest.main()
