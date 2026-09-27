#!/usr/bin/env python3
"""Coverage and semantic proofs for target-neutral draw mutation hooks."""

from __future__ import annotations

import ast
import copy
import itertools
import unittest
from pathlib import Path
from types import SimpleNamespace

from pyz80_compiler.mutation_hook_ir import (
    MUTATION_HOOK_IR_FORMAT,
    MutationHookIRError,
    _finite_strings,
    _lower_getter,
    build_mutation_hook_ir,
    evaluate_derived_expression,
)


ROOT = Path(__file__).resolve().parents[2]


def _object_from_paths(values: dict[tuple[str, ...], object]) -> object:
    root: dict[str, object] = {}
    for path, value in values.items():
        cursor = root
        for part in path[:-1]:
            child = cursor.setdefault(part, {})
            assert isinstance(child, dict)
            cursor = child
        cursor[path[-1]] = value

    def convert(value: object) -> object:
        if isinstance(value, dict):
            return SimpleNamespace(**{
                key: convert(item) for key, item in value.items()})
        return value

    return convert(root)


def _domain(path: tuple[str, ...]) -> tuple[object, ...]:
    leaf = path[-1]
    if leaf == "state":
        return ("falling", "scripted", "active")
    if leaf in ("flash_visible", "controller_flash"):
        return (False, True)
    if leaf == "world_frame":
        return (0, 4, 5)
    if "palette" in leaf:
        return (0, 7, 0xFF)
    return (0, 1, 4)


class MutationHookIRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_mutation_hook_ir(ROOT)
        source_path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        cls.source = source_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(source_path))

    def test_all_active_candidates_have_one_target_neutral_lowering(self) -> None:
        report = self.plan.as_dict()
        self.assertEqual(report["format"], MUTATION_HOOK_IR_FORMAT)
        self.assertFalse(report["live"])
        coverage = report["coverage"]
        self.assertTrue(coverage["complete_ast_coverage"])
        self.assertTrue(coverage["independent_census_matches_draw_state"])
        self.assertFalse(coverage["manual_object_type_switch"])
        self.assertFalse(coverage["runtime_hooks_installed"])
        self.assertEqual(coverage["counts"], {
            "direct_and_implicit_candidates": 368,
            "direct_runtime_sync_hooks": 364,
            "implicit_bind_schema_fields": 4,
            "direct_and_implicit_lowered": 368,
            "derived_getter_candidates": 17,
            "derived_getter_programs": 17,
            "derived_read_candidates": 3,
            "derived_reads_lowered": 3,
            "dynamic_setattr_candidates": 5,
            "dynamic_setattrs_lowered": 5,
            "dynamic_setattrs_proved_disjoint": 5,
            "lifecycle_identity_candidates": 14,
            "lifecycle_identities_lowered": 14,
        })
        self.assertEqual(
            [item["site_id"] for item in self.plan.mutation_hooks],
            list(range(368)))
        self.assertEqual(len(self.plan.derived_dispatch), 73)

    def test_store_hooks_preserve_python_evaluation_contract(self) -> None:
        runtime = [item for item in self.plan.mutation_hooks
                   if item["runtime_hook_required"]]
        schema = [item for item in self.plan.mutation_hooks
                  if not item["runtime_hook_required"]]
        self.assertEqual(len(runtime), 364)
        self.assertEqual(len(schema), 4)
        self.assertTrue(all(item["hook_op"] == "draw-sync-if-bound"
                            for item in runtime))
        self.assertTrue(all(item["rhs_evaluated_once"] and
                            item["receiver_evaluated_once"] and
                            item["reuse_lowered_receiver_temp"] and
                            item["reuse_lowered_value_temp"]
                            for item in runtime))
        self.assertEqual(
            {item["field"] for item in schema},
            {"x", "y", "palette", "descriptor"})
        augmented = [item for item in runtime
                     if item["source_kind"] == "augassign"]
        self.assertEqual(len(augmented), 1)

    def test_derived_programs_match_the_active_python_getters(self) -> None:
        classes = {node.name: node for node in self.tree.body
                   if isinstance(node, ast.ClassDef)}
        for program in self.plan.derived_programs:
            getter = next(node for node in classes[program.owner_class].body
                          if isinstance(node, ast.FunctionDef) and
                          node.name == "active_palette")
            oracle_node = copy.deepcopy(getter)
            oracle_node.decorator_list = []
            oracle_node.name = "oracle"
            module = ast.Module(body=[oracle_node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace: dict[str, object] = {}
            exec(compile(module, "<active_palette_oracle>", "exec"), namespace)
            oracle = namespace["oracle"]
            for sample in itertools.product(*(
                    _domain(path) for path in program.dependency_paths)):
                values = dict(zip(program.dependency_paths, sample))
                instance = _object_from_paths(values)
                self.assertEqual(
                    evaluate_derived_expression(program.expression, values),
                    oracle(instance),
                    (program.owner_class, values),
                )

    def test_dynamic_setattr_names_are_finite_and_disjoint(self) -> None:
        self.assertEqual(
            {tuple(item["possible_attribute_names"])
             for item in self.plan.dynamic_setattrs},
            {("build_cursor", "erase_cursor"),
             ("build_path", "erase_path")})
        self.assertTrue(all(
            item["lowering"] == "proved-disjoint-no-hook" and
            item["draw_field_intersection"] == [] and
            not item["runtime_hook_required"]
            for item in self.plan.dynamic_setattrs))

        unresolved = ast.parse(
            "def f(self, name, value):\n"
            "    setattr(self, name, value)\n").body[0]
        assert isinstance(unresolved, ast.FunctionDef)
        call = next(node for node in ast.walk(unresolved)
                    if isinstance(node, ast.Call))
        with self.assertRaisesRegex(MutationHookIRError, "PZMH005"):
            _finite_strings(call.args[1], {}, {})

    def test_lifecycle_sites_use_primitives_not_callsite_duplication(self) -> None:
        hooks = self.plan.lifecycle_hooks
        self.assertEqual(len(hooks), 14)
        self.assertEqual(sum(item["insertion_phase"] == "call-edge"
                             for item in hooks), 8)
        self.assertEqual(sum(item["hook_op"] == "bind-snapshot"
                             for item in hooks), 3)
        self.assertEqual(sum(item["hook_op"] == "clear-captured-slot"
                             for item in hooks), 1)
        self.assertEqual(sum(
            item["hook_op"] == "replace-same-slot-snapshot"
            for item in hooks), 1)
        self.assertEqual(sum(
            item["hook_op"] == "proved-replacement-detach-no-op"
            for item in hooks), 1)

    def test_unsupported_derived_control_flow_fails_closed(self) -> None:
        node = ast.parse(
            "def active_palette(self):\n"
            "    for value in self.values:\n"
            "        return value\n"
            "    return self.palette\n").body[0]
        assert isinstance(node, ast.FunctionDef)
        with self.assertRaisesRegex(MutationHookIRError, "PZMH003"):
            _lower_getter(node)


if __name__ == "__main__":
    unittest.main()
