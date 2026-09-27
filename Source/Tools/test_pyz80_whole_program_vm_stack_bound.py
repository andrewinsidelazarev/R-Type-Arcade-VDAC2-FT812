from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pyz80_compiler.whole_program_vm_backend import build_whole_program_vm
import pyz80_compiler.whole_program_vm_stack_bound as stack_bound
from pyz80_compiler.whole_program_vm_stack_bound import (
    WholeProgramVMStackBoundError,
    analyze_whole_program_vm_stack_bound,
    render_whole_program_vm_stack_bound,
    validate_whole_program_vm_stack_bound_report,
)


ROOT = Path(__file__).resolve().parents[2]
SPAN = {"path": "fixture.py", "line": 1, "column": 0,
        "end_line": 1, "end_column": 1}


def semantic(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def instruction(sequence: int, op: str, arguments: list[object],
                destination: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "sequence": sequence, "op": op, "arguments": arguments,
        "span": dict(SPAN),
    }
    if destination is not None:
        result["destination"] = destination
        result["value_kind"] = "py-value"
    return result


def terminator(op: str, arguments: list[object],
               targets: list[str]) -> dict[str, object]:
    return {"op": op, "arguments": arguments, "targets": targets,
            "span": dict(SPAN)}


def cfg(name: str, line: int, instructions: list[dict[str, object]], *,
        term: dict[str, object] | None = None,
        signature: dict[str, object] | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "function_id": f"{name}@{line}", "class": None, "function": name,
        "definition_line": line, "ast_sha256": semantic([name, line]),
        "signature": signature or {
            "async": False, "decorators": [], "parameters": [],
            "returns": "object"},
        "entry": "entry", "blocks": [{
            "name": "entry", "instructions": instructions,
            "terminator": term or terminator("return", [], []),
        }],
        "expression_programs": [], "mutation_site_ids": [],
        "spliced_store_fragments": [], "blockers": [],
    }
    result["semantic_sha256"] = semantic(result)
    return result


def graph(*, recursive: bool = False, unresolved: bool = False,
          finite_dynamic: bool = False, helper_parameter_count: int = 0
          ) -> dict[str, object]:
    identifiers = ("m::main@1", "m::helper@2", "m::frames@3")
    main = cfg("main", 1, [
        instruction(0, "constant", [1], "%one"),
        instruction(1, "vm-call", [identifiers[1], "%one"], "%answer"),
    ], term=terminator("return", ["%answer"], []))
    helper_instructions = [instruction(0, "constant", [2], "%two")]
    if recursive:
        helper_instructions.append(
            instruction(1, "vm-call", [identifiers[0]], "%again"))
    helper_signature = {
        "async": False, "decorators": [],
        "parameters": [
            {"name": f"parameter_{index}"}
            for index in range(helper_parameter_count)],
        "returns": "object",
    }
    helper = cfg("helper", 2, helper_instructions,
                 term=terminator("return", ["%two"], []),
                 signature=helper_signature)
    generator_signature = {
        "async": False, "decorators": [], "parameters": [],
        "returns": "Iterable[int]", "execution_kind": "generator-frame",
        "source_suspension_count": 1,
        "lowered_suspension_state_count": 1,
        "frame": {"format": "pyz80.generator-frame.v1",
                  "bounded_by_source_ast": True, "bounded_slot_count": 4,
                  "states": []},
    }
    frames = cfg(
        "frames", 3, [instruction(0, "constant", [3], "%three")],
        term=terminator("yield", ["%three"], ["entry"]),
        signature=generator_signature)
    cfgs = (main, helper, frames)
    rows = [{"callable_id": identifier, "module": "m",
             "qualname": item["function"], "cfg": item}
            for identifier, item in zip(identifiers, cfgs)]
    edges = [
        {"caller": identifiers[0], "callee": identifiers[1],
         "call_site_id": "site-main-helper"},
        {"caller": identifiers[0], "callee": identifiers[2],
         "call_site_id": "site-main-frames"},
    ]
    if recursive:
        edges.append({"caller": identifiers[1], "callee": identifiers[0],
                      "call_site_id": "site-helper-main"})
    unresolved_ids = ["site-unresolved"] if unresolved else []
    finite_dynamic_ids = ["site-finite-dynamic"] if finite_dynamic else []
    call_graph: dict[str, object] = {
        "entrypoint": identifiers[0],
        "proven_reachable_callable_ids": list(identifiers),
        "proven_reachable_callable_count": len(identifiers),
        "exact_internal_edges": edges,
        "exact_internal_edge_count": len(edges),
        "reachable_unresolved_call_site_ids": unresolved_ids,
        "reachable_unresolved_call_site_count": len(unresolved_ids),
        "reachable_finite_dynamic_dispatch_site_ids": finite_dynamic_ids,
        "reachable_finite_dynamic_dispatch_site_count": len(
            finite_dynamic_ids),
        "reachable_host_boundary_call_site_ids": [],
        "reachable_host_boundary_call_site_count": 0,
    }
    call_graph["semantic_sha256"] = semantic(call_graph)
    result: dict[str, object] = {
        "format": "fixture.active-call-graph.v1",
        "entrypoint": {"callable_id": identifiers[0]},
        "call_graph": call_graph,
        "callable_inventory": {"callables": rows},
    }
    result["semantic_sha256"] = semantic(result)
    return result


class WholeProgramVMStackBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = graph()
        cls.artifact = build_whole_program_vm(cls.graph)
        cls.report = analyze_whole_program_vm_stack_bound(
            cls.artifact, cls.graph, project_root=ROOT)

    def test_fixture_is_dynamic_and_separates_stack_from_arena(self) -> None:
        report = self.report
        self.assertEqual(
            report["source_call_graph"]["reachable_callable_count"], 3)
        self.assertEqual(
            report["source_call_graph"]["proven_entry_longest_path_depth"], 2)
        self.assertEqual(report["source_call_graph"]["recursive_scc_count"], 0)
        self.assertEqual(report["source_call_graph"][
            "proven_entry_condensation_depth_lower_bound"], 2)
        self.assertIsInstance(report["source_call_graph"][
            "proven_function_only_path_weighted_frame_slots"], int)
        self.assertEqual(
            report["arena"]["frame_slots_per_frame_required"],
            report["compact_core"]["max_frame_slot_count"])
        self.assertGreaterEqual(
            report["compact_core"]["max_frame_slot_count"],
            report["compact_core"]["max_ssa_local_count"])
        self.assertTrue(report["runtime_abi"][
            "exact_arena_byte_formula_available"])
        self.assertTrue(report["runtime_abi"][
            "frame_slot_runtime_contract"]["source_proved"])
        self.assertEqual(
            report["arena"]["local_bytes_per_uniform_frame"],
            report["arena"]["frame_slots_per_frame_required"] *
            report["runtime_abi"]["target_abi_probe"][
                "struct_sizes_bytes"]["local"])
        self.assertNotIn("unit_labels", report["compact_core"])
        self.assertTrue(report["memory_domains"]["caller_owned_vm_arena"][
            "contains_call_frames_locals_generators_and_argument_scratch"])
        self.assertFalse(report["memory_domains"]["z80_hardware_call_stack"][
            "contains_vm_frames_or_locals"])
        self.assertIsNone(report["arena"][
            "whole_program_arena_safe_upper_bound_bytes"])
        self.assertIn("PZVSBLIVE004",
                      {item["code"] for item in report["live_blockers"]})

    def test_constructor_core_edge_and_synthesized_self_are_bounded(self) -> None:
        from test_pyz80_whole_program_vm_backend import constructor_abi_graph

        constructor_graph, lowering, call_abi = constructor_abi_graph()
        artifact = build_whole_program_vm(
            constructor_graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        proof = stack_bound._compact_core_proof(
            artifact.document, artifact.compact_document,
            "m::abi_caller@20")
        self.assertEqual(proof["max_argument_count"], 3)
        self.assertEqual(proof["entry_exact_core_call_depth"], 2)
        self.assertGreaterEqual(proof["core_push_edge_count"], 1)

    def test_generated_dataclass_post_init_edge_and_field_arguments_are_bounded(
            self) -> None:
        compact = copy.deepcopy(self.artifact.compact_document)
        entry_unit = compact["functions"][0]
        compact["units"][entry_unit]["blocks"][0]["instructions"] = [{
            "opcode": 9,
            "destination_plus_one": 1,
            "field_store_adapter_id": 0,
            "post_init_function_plus_one": 2,
            "arguments": [{"kind": "local", "id": 0},
                          {"kind": "constant", "id": 0},
                          {"kind": "constant", "id": 0}],
        }]
        proof = stack_bound._compact_core_proof(
            self.artifact.document, compact, "m::main@1")
        self.assertEqual(proof["max_argument_count"], 3)
        self.assertEqual(proof["entry_exact_core_call_depth"], 2)
        self.assertGreaterEqual(proof["core_push_edge_count"], 1)

    def test_report_is_deterministic_and_validates_without_writes(self) -> None:
        second = analyze_whole_program_vm_stack_bound(
            self.artifact, copy.deepcopy(self.graph), project_root=ROOT)
        self.assertEqual(second, self.report)
        self.assertEqual(
            render_whole_program_vm_stack_bound(
                self.artifact, self.graph, project_root=ROOT),
            render_whole_program_vm_stack_bound(
                self.artifact, self.graph, project_root=ROOT))
        self.assertEqual(
            validate_whole_program_vm_stack_bound_report(
                self.artifact, self.graph, self.report, project_root=ROOT),
            self.report)

    def test_in_memory_analyzer_tuples_are_json_normalized(self) -> None:
        in_memory = copy.deepcopy(self.graph)
        call_graph = in_memory["call_graph"]
        call_graph["proven_reachable_callable_ids"] = tuple(
            call_graph["proven_reachable_callable_ids"])
        call_graph["exact_internal_edges"] = tuple(
            call_graph["exact_internal_edges"])
        callables = in_memory["callable_inventory"]["callables"]
        callables[0]["cfg"]["blocks"] = tuple(
            callables[0]["cfg"]["blocks"])
        self.assertEqual(
            analyze_whole_program_vm_stack_bound(
                self.artifact, in_memory, project_root=ROOT),
            self.report)

    def test_graph_semantic_tamper_fails_closed(self) -> None:
        damaged = copy.deepcopy(self.graph)
        damaged["call_graph"]["exact_internal_edges"][0]["callee"] = "m::frames@3"
        with self.assertRaisesRegex(
                WholeProgramVMStackBoundError, "PZVSB005"):
            analyze_whole_program_vm_stack_bound(
                self.artifact, damaged, project_root=ROOT)

    def test_artifact_bytecode_tamper_fails_closed(self) -> None:
        damaged_bytes = bytearray(self.artifact.target_bytecode)
        damaged_bytes[-1] ^= 0x80
        damaged = dataclasses.replace(
            self.artifact, target_bytecode=bytes(damaged_bytes))
        with self.assertRaisesRegex(
                WholeProgramVMStackBoundError, "PZVSB017"):
            analyze_whole_program_vm_stack_bound(
                damaged, self.graph, project_root=ROOT)

    def test_report_tamper_fails_closed(self) -> None:
        damaged = copy.deepcopy(self.report)
        damaged["arena"]["proved_call_depth_lower_bound"] += 1
        with self.assertRaisesRegex(
                WholeProgramVMStackBoundError, "PZVSB005"):
            validate_whole_program_vm_stack_bound_report(
                self.artifact, self.graph, damaged, project_root=ROOT)

    def test_recursive_scc_and_unresolved_site_are_distinct_blockers(self) -> None:
        recursive_graph = graph(recursive=True, unresolved=True)
        artifact = build_whole_program_vm(recursive_graph)
        report = analyze_whole_program_vm_stack_bound(
            artifact, recursive_graph, project_root=ROOT)
        codes = {item["code"] for item in report["live_blockers"]}
        self.assertEqual(report["source_call_graph"]["recursive_scc_count"], 1)
        self.assertIsNone(report["source_call_graph"][
            "proven_entry_longest_path_depth"])
        self.assertGreaterEqual(report["source_call_graph"][
            "proven_entry_condensation_depth_lower_bound"], 1)
        self.assertIn("PZVSBLIVE001", codes)
        self.assertIn("PZVSBLIVE002", codes)

    def test_finite_dynamic_dispatch_is_a_depth_blocker_and_count_is_bound(
            self) -> None:
        finite_graph = graph(finite_dynamic=True)
        artifact = build_whole_program_vm(finite_graph)
        report = analyze_whole_program_vm_stack_bound(
            artifact, finite_graph, project_root=ROOT)
        codes = {item["code"] for item in report["live_blockers"]}
        self.assertEqual(report["source_call_graph"][
            "reachable_finite_dynamic_dispatch_site_count"], 1)
        self.assertFalse(report["source_call_graph"][
            "finite_whole_program_call_depth_proved"])
        self.assertIn("PZVSBLIVE013", codes)

        damaged = copy.deepcopy(finite_graph)
        call_graph = damaged["call_graph"]
        call_graph["reachable_finite_dynamic_dispatch_site_count"] = 0
        call_graph["semantic_sha256"] = semantic({
            key: value for key, value in call_graph.items()
            if key != "semantic_sha256"})
        damaged["semantic_sha256"] = semantic({
            key: value for key, value in damaged.items()
            if key not in ("semantic_sha256", "status", "live",
                           "live_blockers")})
        with self.assertRaisesRegex(
                WholeProgramVMStackBoundError, "PZVSB011"):
            analyze_whole_program_vm_stack_bound(
                artifact, damaged, project_root=ROOT)

    def test_frame_slot_count_above_uint8_materializes_and_runtime_capacity_binds(
            self) -> None:
        wide_graph = graph(helper_parameter_count=260)
        artifact = build_whole_program_vm(wide_graph)
        report = analyze_whole_program_vm_stack_bound(
            artifact, wide_graph, project_root=ROOT)
        self.assertGreater(report["compact_core"]["max_frame_slot_count"], 255)
        self.assertNotIn(
            "PZVSBLIVE015",
            {item["code"] for item in report["live_blockers"]})

        with tempfile.TemporaryDirectory(prefix="pyz80-vm-stack-u8-") as raw:
            root = Path(raw)
            runtime = root / "Source/C/python_vm"
            runtime.mkdir(parents=True)
            for name in ("pyz80_whole_program_vm.h",
                         "pyz80_whole_program_vm.c"):
                shutil.copy2(ROOT / "Source/C/python_vm" / name, runtime / name)
            header_path = runtime / "pyz80_whole_program_vm.h"
            header = header_path.read_text(encoding="utf-8")
            self.assertIn("uint16_t locals_per_frame;", header)
            header_path.write_text(
                header.replace("uint16_t locals_per_frame;",
                               "uint8_t locals_per_frame;", 1),
                encoding="utf-8", newline="\n")
            narrowed = analyze_whole_program_vm_stack_bound(
                artifact, wide_graph, project_root=root)
            self.assertFalse(narrowed["complete_bound_proved"])
            self.assertEqual(narrowed["runtime_abi"][
                "frame_slot_runtime_contract"][
                    "maximum_frame_slot_count"], 255)
            self.assertIn(
                "PZVSBLIVE015",
                {item["code"] for item in narrowed["live_blockers"]})

    def test_runtime_hash_tamper_invalidates_prior_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyz80-vm-stack-test-") as raw:
            root = Path(raw)
            runtime = root / "Source/C/python_vm"
            runtime.mkdir(parents=True)
            for name in ("pyz80_whole_program_vm.h",
                         "pyz80_whole_program_vm.c"):
                shutil.copy2(ROOT / "Source/C/python_vm" / name, runtime / name)
            first = analyze_whole_program_vm_stack_bound(
                self.artifact, self.graph, project_root=root)
            c_path = runtime / "pyz80_whole_program_vm.c"
            c_path.write_text(c_path.read_text(encoding="utf-8") +
                              "\n/* stack-binding-tamper */\n",
                              encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(
                    WholeProgramVMStackBoundError, "PZVSB035"):
                validate_whole_program_vm_stack_bound_report(
                    self.artifact, self.graph, first, project_root=root)


if __name__ == "__main__":
    unittest.main()
