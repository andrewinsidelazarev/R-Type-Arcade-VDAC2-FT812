#!/usr/bin/env python3
"""Fast AST/IR and mutation tests for ``M72EnemyWorld.draw``.

The expensive eight-stage coverage analysis is intentionally not invoked.
One test joins the plan to a tiny object exposing the public
``CoverageReport.owned_sink_ids`` field, which is the same operation build
orchestration can perform with an already-computed report.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from pyz80_compiler.draw_plan import (
    ACTIVE_ENEMY_DRAW_CONTRACT,
    DrawExpr,
    DrawPlanCompileError,
    compile_active_enemy_draw_plan,
    compile_sprite_draw_plan,
    cross_check_coverage_sinks,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"


def _attr(value: DrawExpr, name: str) -> bool:
    return value.op == "attribute" and value.value == name


def _constant(value: DrawExpr) -> object:
    if value.op != "constant":
        raise AssertionError(value.as_dict())
    return value.value


def _condition_key(values: tuple[DrawExpr, ...]) -> object:
    return tuple(item.semantic_key() for item in values)


class DrawPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE_PATH.read_bytes().decode("utf-8")
        cls.plan = compile_active_enemy_draw_plan(ROOT)

    def test_lexical_sinks_are_distinct_from_finite_record_expansion(self) -> None:
        plan = self.plan
        self.assertEqual(len(plan.loops), 2)
        self.assertEqual(len(plan.sink_occurrences), 16)
        self.assertEqual(len(plan.actions), 34)
        self.assertEqual(
            [len(item.action_ordinals) for item in plan.loops], [33, 1])
        self.assertEqual(
            [item.ordinal for item in plan.sink_occurrences], list(range(16)))
        self.assertEqual([item.ordinal for item in plan.actions], list(range(34)))
        self.assertEqual(
            [item.span.line for item in plan.sink_occurrences],
            sorted(item.span.line for item in plan.sink_occurrences))
        self.assertEqual(ACTIVE_ENEMY_DRAW_CONTRACT.sink_occurrence_count, 16)
        self.assertEqual(ACTIVE_ENEMY_DRAW_CONTRACT.record_action_count, 34)

    def test_four_skip_predicates_and_palette_selector_are_literal_ast_ir(self) -> None:
        enemy_loop = self.plan.loops[0]
        predicates = [item.predicate for item in enemy_loop.continue_predicates]
        self.assertEqual([item.op for item in predicates],
                         ["equal", "not", "all", "all"])
        self.assertTrue(_attr(predicates[0].arguments[0], "palette"))
        self.assertEqual(_constant(predicates[0].arguments[1]), 0xFF)
        self.assertEqual(predicates[1].arguments[0].op, "getattr")
        self.assertEqual(
            _constant(predicates[1].arguments[0].arguments[1]),
            "render_ready")
        self.assertEqual(
            _constant(predicates[1].arguments[0].arguments[2]), True)
        self.assertEqual(
            predicates[2].arguments[0].arguments[1].arguments[0].value,
            "BackgroundParticleE5CD")
        self.assertTrue(_attr(
            predicates[2].arguments[1].arguments[0], "render_ready"))
        self.assertEqual(
            predicates[3].arguments[0].arguments[1].arguments[0].value,
            "Targeting80E3AttackFlash")
        self.assertTrue(_attr(
            predicates[3].arguments[1].arguments[0], "visible"))

        primary = self.plan.actions[0]
        self.assertEqual(len(primary.conditions), 4)
        self.assertTrue(all(item.op == "not" for item in primary.conditions))
        palette = primary.palette
        self.assertEqual(palette.op, "select")
        selector, active, fallback = palette.arguments
        self.assertEqual(selector.op, "type_is")
        self.assertTrue(_attr(active, "active_palette"))
        self.assertTrue(_attr(fallback, "palette"))
        classes = tuple(
            item.value for item in selector.arguments[1].arguments)
        self.assertEqual(classes, (
            "GroundWalker", "PlayerTargeting80E3", "LargeTerrain74B4",
            "Handler60BA", "Enemy8561", "TerrainEnemy696E", "Enemy6F89",
            "Enemy7294", "Enemy5EED", "Formation78F8Child",
            "Multipart915BChild", "AttachedAC4C", "MultipartA71DBody",
            "BossB7FBCore", "Enemy7D68", "Child8D85", "DobkeratopsBody",
        ))
        resource = primary.resource_type
        self.assertEqual(resource.op, "subscript")
        self.assertEqual(resource.arguments[1], palette)

    def test_primary_adjacent_overlay_and_transient_fields_are_exact(self) -> None:
        actions = self.plan.actions
        primary = actions[0]
        self.assertTrue(_attr(primary.descriptor, "descriptor"))
        self.assertTrue(_attr(primary.anchor_x, "x"))
        self.assertTrue(_attr(primary.anchor_y, "y"))

        adjacent = actions[1:11] + actions[24:25]
        self.assertEqual(len(adjacent), 11)
        for item in adjacent:
            self.assertEqual(item.descriptor.op, "add")
            self.assertTrue(_attr(item.descriptor.arguments[0], "descriptor"))
            self.assertEqual(_constant(item.descriptor.arguments[1]), 6)

        overlay = actions[32]
        self.assertTrue(_attr(overlay.descriptor, "overlay_descriptor"))
        self.assertTrue(_attr(overlay.anchor_x, "overlay_x"))
        self.assertTrue(_attr(overlay.anchor_y, "overlay_y"))

        transient = actions[33]
        self.assertEqual(transient.loop_id, "loop_1")
        self.assertEqual(transient.conditions, ())
        self.assertEqual(transient.descriptor, DrawExpr("name", value="descriptor"))
        self.assertEqual(transient.palette, DrawExpr("name", value="palette"))
        self.assertEqual(
            transient.resource_type, DrawExpr("name", value="resource_type"))
        self.assertEqual(transient.anchor_x, DrawExpr("name", value="x"))
        self.assertEqual(transient.anchor_y, DrawExpr("name", value="y"))

    def test_body_kind_and_fixed_tuples_expand_without_cartesian_product(self) -> None:
        body = self.plan.actions[11:24]
        self.assertEqual(
            [_constant(item.descriptor) for item in body],
            [0x5A08, 0x5A0E, 0x5A14, 0x5A1A, 0x5A20,
             0x5A4C, 0x5A52, 0x5A58, 0x5A5E, 0x5A64,
             0x5A88, 0x5A8E, 0x5A94])
        condition_groups = [
            {_condition_key(item.conditions) for item in body[0:5]},
            {_condition_key(item.conditions) for item in body[5:10]},
            {_condition_key(item.conditions) for item in body[10:13]},
        ]
        self.assertEqual([len(item) for item in condition_groups], [1, 1, 1])
        self.assertEqual(len(set.union(*condition_groups)), 3)
        self.assertEqual([len(body[i].conditions) for i in (0, 5, 10)],
                         [6, 7, 7])

        fixed = self.plan.actions[25:32]
        self.assertEqual(
            [_constant(item.descriptor) for item in fixed],
            [0x3048, 0x304E, 0x3054, 0x305A,
             0x3060, 0x3066, 0x306C])
        self.assertEqual(
            len({_condition_key(item.conditions) for item in fixed}), 1)

    def test_json_and_small_report_are_deterministic(self) -> None:
        again = compile_active_enemy_draw_plan(ROOT)
        self.assertEqual(self.plan.to_json(), again.to_json())
        parsed = json.loads(self.plan.to_json())
        self.assertEqual(parsed["format"], "pyz80.sprite-draw-plan.v1")
        self.assertEqual(parsed["semantic_sha256"], self.plan.semantic_sha256)
        report = self.plan.report()
        self.assertEqual(report["sink_occurrence_count"], 16)
        self.assertEqual(report["record_action_count"], 34)
        self.assertEqual(report["continue_predicate_count"], 4)

    def test_every_action_and_filter_has_source_span_and_ast_hash(self) -> None:
        for item in self.plan.actions:
            self.assertEqual(item.span.path,
                             "Source/Python/rtype_port/enemies.py")
            self.assertGreaterEqual(item.span.line, 6632)
            self.assertEqual(len(item.ast_sha256), 64)
        for loop in self.plan.loops:
            self.assertEqual(len(loop.ast_sha256), 64)
            for item in loop.continue_predicates:
                self.assertEqual(len(item.ast_sha256), 64)
                self.assertGreaterEqual(item.span.line, 6632)
        for item in self.plan.sink_occurrences:
            self.assertEqual(len(item.ast_sha256), 64)
            self.assertEqual(len(item.control_sha256), 64)

    def test_already_computed_public_coverage_report_can_be_joined_cheaply(self) -> None:
        ids = [item.coverage_id for item in self.plan.sink_occurrences]
        report = SimpleNamespace(owned_sink_ids=(
            "rtype_port.force:Force.draw:unrelated:0", *reversed(ids)))
        cross_check_coverage_sinks(self.plan, report)
        with self.assertRaisesRegex(DrawPlanCompileError, "PZDP022"):
            cross_check_coverage_sinks(
                self.plan, SimpleNamespace(owned_sink_ids=ids[:-1]))

    def test_generic_frontend_also_compiles_player_bits_draw(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "bits.py"
        plan = compile_sprite_draw_plan(
            path.read_bytes().decode("utf-8"),
            source_path="Source/Python/rtype_port/bits.py",
            module="rtype_port.bits", class_name="PlayerBits",
            atlas_receiver="atlas", target_argument="target")
        self.assertEqual(plan.symbol, "rtype_port.bits.PlayerBits.draw")
        self.assertEqual(len(plan.loops), 1)
        self.assertEqual(len(plan.sink_occurrences), 1)
        self.assertEqual(len(plan.actions), 1)
        action = plan.actions[0]
        self.assertEqual(action.conditions[-1].op, "not_equal")
        self.assertTrue(_attr(action.descriptor, "descriptor"))
        self.assertEqual(_constant(action.resource_type), 0x56)

    def _assert_mutation_fails(
            self, mutated: str, code: str) -> DrawPlanCompileError:
        with self.assertRaises(DrawPlanCompileError) as caught:
            compile_active_enemy_draw_plan(ROOT, source_override=mutated)
        error = caught.exception
        self.assertEqual(error.code, code, str(error))
        self.assertEqual(error.span.path,
                         "Source/Python/rtype_port/enemies.py")
        self.assertEqual(len(error.source_sha256), 64)
        self.assertEqual(len(error.method_ast_sha256), 64)
        self.assertEqual(len(error.node_ast_sha256), 64)
        self.assertIn("source_sha256=", str(error))
        self.assertIn("node_ast_sha256=", str(error))
        return error

    def test_reordered_same_shape_extras_fail_on_control_order_hash(self) -> None:
        first = "            if isinstance(enemy, PlayerTargeting80E3):\n"
        second = "            if isinstance(enemy, Targeting80E3Projectile):\n"
        self.assertIn(first, self.source)
        self.assertIn(second, self.source)
        mutated = self.source.replace(first, "            if isinstance(enemy, __SWAP__):\n", 1)
        mutated = mutated.replace(second, first, 1)
        mutated = mutated.replace("            if isinstance(enemy, __SWAP__):\n",
                                  second, 1)
        self._assert_mutation_fails(mutated, "PZDP018")

    def test_changed_adjacent_descriptor_offset_fails_closed(self) -> None:
        old = "read_descriptor(self.rom, enemy.descriptor + 6)"
        self.assertIn(old, self.source)
        mutated = self.source.replace(
            old, "read_descriptor(self.rom, enemy.descriptor + 12)", 1)
        self._assert_mutation_fails(mutated, "PZDP017")

    def test_changed_active_palette_class_tuple_fails_closed(self) -> None:
        old = "                        DobkeratopsBody))"
        self.assertIn(old, self.source)
        mutated = self.source.replace(
            old, "                        DobkeratopsBodyChanged))", 1)
        self._assert_mutation_fails(mutated, "PZDP020")

    def test_new_sink_is_not_hidden_by_tuple_expansion(self) -> None:
        call = (
            "            self.atlas.draw(target, "
            "read_descriptor(self.rom, enemy.descriptor),\n"
            "                            palette, resource_type, enemy.x, enemy.y)\n"
        )
        self.assertIn(call, self.source)
        mutated = self.source.replace(call, call + call, 1)
        self._assert_mutation_fails(mutated, "PZDP016")

    def test_unsupported_call_fails_at_its_own_source_span(self) -> None:
        marker = (
            "    def draw(self, target: pygame.Surface) -> None:\n"
            "        for enemy in self.enemies:\n"
        )
        self.assertIn(marker, self.source)
        mutated = self.source.replace(
            marker, marker + "            audit_enemy(enemy)\n", 1)
        error = self._assert_mutation_fails(mutated, "PZDP008")
        self.assertIn("expression is not an atlas.draw sink", error.detail)

    def test_changed_transient_tuple_arity_fails_closed(self) -> None:
        old = ("        for descriptor, palette, resource_type, x, y in "
               "self.transient_sprites:\n")
        self.assertIn(old, self.source)
        mutated = self.source.replace(
            old,
            "        for descriptor, palette, resource_type, x, y, unused in "
            "self.transient_sprites:\n", 1)
        self._assert_mutation_fails(mutated, "PZDP020")


if __name__ == "__main__":
    unittest.main()
