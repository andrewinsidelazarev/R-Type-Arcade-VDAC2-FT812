#!/usr/bin/env python3
"""Tests for source-sealed lambda callable units and their Python oracle."""

from __future__ import annotations

import ast
import copy
import inspect
import unittest
from pathlib import Path

import pyz80_compiler.lambda_callable_units as lambda_units
from pyz80_compiler.active_call_graph import analyze_active_call_graph
from pyz80_compiler.active_callable_flow import analyze_active_callable_flow
from pyz80_compiler.lambda_callable_units import (
    LAMBDA_CALLABLE_UNITS_FORMAT,
    LAMBDA_CALLABLE_UNITS_STATUS,
    LambdaCallableUnitError,
    analyze_lambda_callable_units,
    bind_lambda_call_oracle,
    decode_lambda_callable_units,
    encode_lambda_callable_units,
    evaluate_lambda_definition_defaults_oracle,
    execute_lambda_unit_oracle,
    validate_lambda_callable_units_report,
)


ROOT = Path(__file__).resolve().parents[2]


def _resign(report: dict[str, object]) -> None:
    report["semantic_sha256"] = lambda_units._json_sha256(
        lambda_units._semantic_payload(report))


def _synthetic_lambda_unit(source: str) -> tuple[dict[str, object], ast.Lambda]:
    tree = ast.parse(source, filename="synthetic.py", type_comments=True)
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)]
    if len(nodes) != 1:
        raise AssertionError("synthetic source must contain exactly one lambda")
    node = nodes[0]
    parameters = []
    for argument, kind, default in lambda_units._parameter_nodes(node.args):
        parameters.append({
            "name": argument.arg,
            "kind": kind,
            "has_default": default is not None,
            "default_ast_sha256": (
                lambda_units._ast_sha256(default)
                if default is not None else None),
        })
    flow_unit = {
        "callable_value_id": (
            "lambda:synthetic:" + lambda_units._ast_sha256(node)),
        "kind": "lambda",
        "module": "synthetic",
        "lexical_owner": "synthetic::factory@1",
        "span": lambda_units._span("synthetic.py", node),
        "ast_sha256": lambda_units._ast_sha256(node),
        "signature": {"parameters": parameters},
        "closure": {
            "lexical_owner": "synthetic::factory@1",
            "captured_names": lambda_units._captured_names(node),
        },
    }
    return lambda_units._materialize_lambda_node(
        node, source_text=source, source_path="synthetic.py",
        flow_unit=flow_unit, numeric_id=1), node


class LambdaCallableUnitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.active_graph = analyze_active_call_graph(ROOT)
        cls.callable_flow = analyze_active_callable_flow(
            ROOT, active_graph=cls.active_graph)
        cls.report = analyze_lambda_callable_units(
            ROOT, active_graph=cls.active_graph,
            callable_flow=cls.callable_flow)
        cls.units = cls.report["lambda_callable_units_in_source_order"]
        cls.references = cls.report[
            "existing_callable_references_in_source_order"]

    def test_current_six_lambdas_are_exactly_materialized(self) -> None:
        self.assertEqual(self.report["format"],
                         LAMBDA_CALLABLE_UNITS_FORMAT)
        self.assertEqual(self.report["status"],
                         LAMBDA_CALLABLE_UNITS_STATUS)
        self.assertFalse(self.report["live"])
        census = self.report["census"]
        self.assertEqual(census["flow_lambda_candidate_unit_count"], 6)
        self.assertEqual(
            census["materialized_lambda_callable_unit_count"], 6)
        self.assertEqual(len(self.units), 6)
        self.assertEqual(
            [row["numeric_lambda_callable_id"] for row in self.units],
            list(range(1, 7)))
        self.assertEqual(len({row["lambda_callable_id"]
                              for row in self.units}), 6)
        self.assertTrue(all(row["callable_unit_materialized"] is True and
                            row["graph_reachability_edge"] is False and
                            row["runtime_integrated"] is False
                            for row in self.units))

    def test_body_cfg_signatures_closures_and_returns_are_source_sealed(
            self) -> None:
        fallback = [row for row in self.units
                    if row["body"]["source"] == "None"]
        damage = [row for row in self.units
                  if "damage_at" in row["body"]["source"]]
        self.assertEqual(len(fallback), 2)
        self.assertEqual(len(damage), 4)
        for row in fallback:
            self.assertEqual(row["closure"]["captured_names"], [])
            self.assertEqual(
                [item["name"] for item in row["signature"]["parameters"]],
                ["_name"])
        for row in damage:
            self.assertEqual(row["closure"]["captured_names"], ["self"])
            self.assertEqual(
                [item["name"] for item in row["signature"]["parameters"]],
                ["rect", "damage"])
            self.assertIn("python-call", row[
                "body"]["protocol_operations"])
        for row in self.units:
            body = row["body"]
            self.assertEqual(body["ast_sha256"],
                             body["expression_cfg"]["ast_sha256"])
            self.assertEqual(body["source"],
                             body["expression_cfg"]["source"])
            self.assertEqual(row["return_semantics"]["kind"],
                             "return-expression-result")

    def test_target_audio_play_remains_an_existing_callable_reference(
            self) -> None:
        self.assertEqual(len(self.references), 1)
        reference = self.references[0]
        self.assertEqual(reference["kind"], "bound-method")
        self.assertIn("::TargetAudio.play@",
                      str(reference["target_callable_id"]))
        self.assertFalse(reference["materialized_as_lambda"])
        self.assertFalse(reference["graph_reachability_edge"])
        materialized_sources = {row["source_callable_value_id"]
                                for row in self.units}
        self.assertNotIn(reference["source_callable_value_id"],
                         materialized_sources)

    def test_deterministic_report_and_binary_encoding(self) -> None:
        repeated = lambda_units._build_report(
            ROOT, self.active_graph, self.callable_flow)
        self.assertEqual(repeated, self.report)
        encoded = encode_lambda_callable_units(self.report)
        self.assertEqual(encoded, encode_lambda_callable_units(self.report))
        self.assertEqual(decode_lambda_callable_units(encoded), self.report)
        tampered = bytearray(encoded)
        tampered[-1] ^= 1
        with self.assertRaises(LambdaCallableUnitError) as caught:
            decode_lambda_callable_units(bytes(tampered))
        self.assertEqual(caught.exception.code, "PZLCU416")

    def test_python_oracle_matches_defaults_closure_and_keyword_binding(
            self) -> None:
        source = (
            "def factory():\n"
            "    captured = 5\n"
            "    fn = lambda x, y=captured, *, scale=2: "
            "(x + y) * scale + captured\n"
            "    captured = 11\n"
            "    return fn\n")
        unit, _ = _synthetic_lambda_unit(source)
        namespace: dict[str, object] = {}
        exec(compile(source, "synthetic.py", "exec"), namespace)
        python_lambda = namespace["factory"]()
        defaults = evaluate_lambda_definition_defaults_oracle(
            unit, {"captured": 5})
        self.assertEqual(defaults, {"y": 5, "scale": 2})
        self.assertEqual(
            execute_lambda_unit_oracle(
                unit, (3,), definition_defaults=defaults,
                closure={"captured": 11}),
            python_lambda(3))
        self.assertEqual(
            execute_lambda_unit_oracle(
                unit, (3,), keywords={"y": 7, "scale": 4},
                definition_defaults=defaults, closure={"captured": 11}),
            python_lambda(3, y=7, scale=4))

    def test_python_oracle_exact_varargs_binding_and_fail_closed_capture(
            self) -> None:
        source = (
            "fn = lambda a, /, b=2, *rest, c=3, **kw: "
            "(a, b, rest, c, kw)\n")
        unit, _ = _synthetic_lambda_unit(source)
        defaults = evaluate_lambda_definition_defaults_oracle(unit, {})
        bound = bind_lambda_call_oracle(
            unit, (1, 4, 5), keywords={"c": 6, "extra": 7},
            definition_defaults=defaults)
        actual = eval(source.split("=", 1)[1].strip())
        expected_bound = inspect.signature(actual).bind(
            1, 4, 5, c=6, extra=7)
        expected_bound.apply_defaults()
        self.assertEqual(bound, dict(expected_bound.arguments))
        self.assertEqual(execute_lambda_unit_oracle(
            unit, (1, 4, 5), keywords={"c": 6, "extra": 7},
            definition_defaults=defaults, closure={}),
            actual(1, 4, 5, c=6, extra=7))

        closure_source = "fn = lambda value: value + captured\n"
        closure_unit, _ = _synthetic_lambda_unit(closure_source)
        with self.assertRaises(LambdaCallableUnitError) as caught:
            execute_lambda_unit_oracle(
                closure_unit, (1,), definition_defaults={}, closure={})
        self.assertEqual(caught.exception.code, "PZLCU503")
        with self.assertRaises(LambdaCallableUnitError) as caught:
            execute_lambda_unit_oracle(
                unit, (1,), definition_defaults={"b": 2}, closure={})
        self.assertEqual(caught.exception.code, "PZLCU502")

    def test_resigned_source_cfg_reachability_reference_and_order_tamper(
            self) -> None:
        mutations: list[dict[str, object]] = []

        span = copy.deepcopy(self.report)
        span["lambda_callable_units_in_source_order"][0]["span"][
            "column"] += 1
        mutations.append(span)

        body = copy.deepcopy(self.report)
        body["lambda_callable_units_in_source_order"][0]["body"][
            "expression_cfg"]["result_kind"] = "forged"
        mutations.append(body)

        reachable = copy.deepcopy(self.report)
        reachable["lambda_callable_units_in_source_order"][0][
            "graph_reachability_edge"] = True
        mutations.append(reachable)

        reference = copy.deepcopy(self.report)
        reference["existing_callable_references_in_source_order"][0][
            "materialized_as_lambda"] = True
        mutations.append(reference)

        target = copy.deepcopy(self.report)
        target["existing_callable_references_in_source_order"][0][
            "target_callable_id"] = "forged::target@1"
        mutations.append(target)

        order = copy.deepcopy(self.report)
        order["lambda_callable_units_in_source_order"][0:2] = reversed(
            order["lambda_callable_units_in_source_order"][0:2])
        mutations.append(order)

        for index, tampered in enumerate(mutations):
            with self.subTest(index=index):
                _resign(tampered)
                with self.assertRaises(LambdaCallableUnitError):
                    validate_lambda_callable_units_report(
                        ROOT, tampered, active_graph=self.active_graph,
                        callable_flow=self.callable_flow)


if __name__ == "__main__":
    unittest.main()
