"""Small execution regressions; no full game graph regeneration required."""
from __future__ import annotations

import ast
import hashlib
import unittest

from pyz80_compiler.cfg_ssa import DominatingDefinitions
from pyz80_compiler.whole_program_vm_call_abi import _build_report
from pyz80_compiler.whole_program_vm_backend import (
    CompactTargetVMOracle, build_whole_program_vm, WholeProgramVMError,
)
from test_pyz80_whole_program_vm_backend import (
    abi_bound_keyword_graph, _resign, instruction, terminator, block,
)


def omitted_default_fixture(source: str):
    graph, lowering, _ = abi_bound_keyword_graph()
    caller, target = [r["cfg"] for r in
                      graph["callable_inventory"]["callables"][:2]]
    caller["blocks"][0]["instructions"].pop()  # No arithmetic on return values.
    caller["blocks"][0]["terminator"] = terminator("return", ["%result_a"], [])
    call = caller["blocks"][0]["instructions"][5]
    call["arguments"] = ["%callable_a", "%left_a"]
    call["attributes"]["argument_count"] = 1
    call["attributes"]["argument_layout"] = [["keyword", "left"]]
    target["signature"]["parameters"][2]["default"] = source
    target["blocks"][0]["instructions"] = [
        instruction(0, "load-name", ["right"], "%answer")]
    target["blocks"][0]["terminator"] = terminator("return", ["%answer"], [])
    _resign(caller)
    _resign(target)
    _resign(graph)
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    occurrence = lowering["cfg_occurrences_in_cfg_order"][0]
    occurrence["argument_layout"] = [{
        "argument_index": 0, "kind": "keyword", "keyword": "left",
        "value": "%left_a"}]
    parameter = lowering["target_signatures"]["m::Worker.difference@21"][
        "parameters"][2]
    parameter["has_default"] = True
    parameter["default_ast_sha256"] = hashlib.sha256(ast.dump(
        ast.parse(source, mode="eval").body, include_attributes=False
    ).encode()).hexdigest()
    _resign(lowering)
    return graph, lowering, _build_report(graph, lowering)


class CallLoweringRegressionTests(unittest.TestCase):
    def test_omitted_scalar_defaults_match_python_execution(self):
        for source in ("None", "True", "False", "0", "-7", "0x0204",
                       "'%left_a'", "'normal text'", "2.5"):
            with self.subTest(source=source):
                graph, lowering, abi = omitted_default_fixture(source)
                artifact = build_whole_program_vm(
                    graph, active_call_site_lowering=lowering,
                    whole_program_vm_call_abi=abi)
                def adapter(_id, args, desc):
                    if desc["op"] in {"load-attribute", "require-callable"}:
                        return "callable"
                    self.fail(f"unexpected adapter {desc['op']}")
                actual = CompactTargetVMOracle(artifact, adapter=adapter).run(
                    "m::abi_caller@20")
                ns = {}
                exec(f"def reference(left, right={source}):\n    return right", ns)
                expected = ns["reference"](left=7)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))
                self.assertEqual(artifact.target_coverage[
                    "abi_unlowered_call_instruction_count"], 0)

    def test_compound_and_computed_defaults_require_definition_time_storage(self):
        for source in ("(1, 2)", "[1]", "{}", "b'bytes'", "1e999",
                       "INITIAL_LIVES", "make_value()"):
            with self.subTest(source=source):
                graph, lowering, abi = omitted_default_fixture(source)
                artifact = build_whole_program_vm(
                    graph, active_call_site_lowering=lowering,
                    whole_program_vm_call_abi=abi)
                self.assertEqual(artifact.target_coverage[
                    "abi_unlowered_call_instruction_count"], 1)

    def test_resigned_default_hash_mismatch_is_rejected(self):
        graph, lowering, abi = omitted_default_fixture("99")
        graph["callable_inventory"]["callables"][1]["cfg"]["signature"][
            "parameters"][2]["default"] = "100"
        _resign(graph["callable_inventory"]["callables"][1]["cfg"])
        _resign(graph)
        lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        _resign(lowering)
        abi = _build_report(graph, lowering)
        with self.assertRaisesRegex(WholeProgramVMError, "default AST hash mismatch"):
            build_whole_program_vm(graph, active_call_site_lowering=lowering,
                                   whole_program_vm_call_abi=abi)

    def test_branch_merge_sees_entry_but_not_branch_only_definition(self):
        unit = {"entry": "entry", "blocks": [
            block("entry", [instruction(0, "load-name", ["f"], "%f")],
                  terminator("branch-truth", [True], ["left", "right"])),
            block("left", [instruction(1, "load-name", ["g"], "%g")],
                  terminator("jump", [], ["join"])),
            block("right", [], terminator("jump", [], ["join"])),
            block("join", [instruction(2, "python-call", ["%f"], "%result")],
                  terminator("return", ["%result"], [])),
        ]}
        visible = DominatingDefinitions(unit).at(3, 0)
        self.assertIn("%f", visible)
        self.assertNotIn("%g", visible)
        self.assertNotIn("%result", visible)
        # An assignment on just one branch must invalidate uniqueness.
        unit["blocks"][1]["instructions"][0]["destination"] = "%f"
        self.assertEqual(len(DominatingDefinitions(unit).at(3, 0)["%f"]), 2)

    def test_loop_does_not_promote_backedge_definition(self):
        unit = {"entry": "entry", "blocks": [
            block("entry", [instruction(0, "load-name", ["f"], "%f")],
                  terminator("jump", [], ["loop"])),
            block("loop", [instruction(1, "python-call", ["%f"], "%r")],
                  terminator("branch-truth", [True], ["body", "exit"])),
            block("body", [instruction(2, "load-name", ["g"], "%g")],
                  terminator("jump", [], ["loop"])),
            block("exit", [], terminator("return", [], [])),
        ]}
        visible = DominatingDefinitions(unit).at(1, 0)
        self.assertIn("%f", visible)
        self.assertNotIn("%g", visible)


if __name__ == "__main__":
    unittest.main()
