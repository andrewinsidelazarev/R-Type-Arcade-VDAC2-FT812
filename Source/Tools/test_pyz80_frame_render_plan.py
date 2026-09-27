#!/usr/bin/env python3
"""Tests for the active-Python whole-frame Z-order IR."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pyz80_compiler.frame_render_plan import (
    FRAME_RENDER_PLAN_FORMAT,
    FrameRenderPlanError,
    compile_active_frame_render_plan,
)


ROOT = Path(__file__).resolve().parents[2]


class FrameRenderPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = compile_active_frame_render_plan(ROOT)

    def test_full_order_is_derived_and_background_is_lowest(self) -> None:
        report = self.plan.as_dict()
        self.assertEqual(report["format"], FRAME_RENDER_PLAN_FORMAT)
        self.assertEqual(
            report["status"], "SOURCE_DERIVED_IR_LIVE_LOWERING_BLOCKED")
        self.assertFalse(report["source_program"]["canonical"])
        self.assertEqual(report["source_program"]["module"],
                         "rtype_port.app")
        self.assertEqual(len(report["groups"]), 16)
        self.assertEqual(len(report["sinks"]), 19)
        paths = [item["call_path"] for item in report["sinks"]]
        self.assertEqual(paths[:5], [
            "target.fill",
            "self.stage.draw_back",
            "self.enemy_world.draw",
            "self.force.draw",
            "self.bits.draw",
        ])
        self.assertEqual(paths[-6:], [
            "self.stage.draw_front",
            "target.blit",
            "self._draw_player_label",
            "self._draw_score",
            "self._draw_beam_meter",
            "self._draw_debug_distance",
        ])
        z_order = report["z_order_contract"]
        self.assertTrue(z_order["background_is_lowest_visible_layer"])
        self.assertTrue(z_order["distance_is_last"])
        self.assertEqual(z_order["background_ordinal"], 1)
        self.assertEqual(z_order["foreground_ordinal"], 13)
        self.assertEqual(z_order["hud_ordinal"], 14)
        self.assertFalse(report["live_target_lowering_present"])
        self.assertTrue(report["live_blockers"])

    def test_plan_is_deterministic_and_hashes_its_semantics(self) -> None:
        repeated = compile_active_frame_render_plan(ROOT)
        self.assertEqual(self.plan, repeated)
        self.assertEqual(len(self.plan.source_sha256), 64)
        self.assertEqual(len(self.plan.method_ast_sha256), 64)
        self.assertEqual(len(self.plan.sink_order_sha256), 64)
        self.assertEqual(len(self.plan.semantic_sha256), 64)
        self.assertEqual(
            json.loads(json.dumps(self.plan.as_dict(), sort_keys=True)),
            self.plan.as_dict())

    def test_moving_background_after_enemies_fails_closed(self) -> None:
        source = (ROOT / "Source" / "Python" / "rtype_port" /
                  "game.py").read_text(encoding="utf-8")
        pair = (
            "        self.stage.draw_back(target)\n"
            "        self.enemy_world.draw(target)\n")
        self.assertEqual(source.count(pair), 1)
        stale = source.replace(
            pair,
            "        self.enemy_world.draw(target)\n"
            "        self.stage.draw_back(target)\n",
            1)
        with self.assertRaisesRegex(FrameRenderPlanError, "PZFRP007"):
            compile_active_frame_render_plan(
                ROOT, game_source_override=stale)

    def test_unknown_target_render_call_fails_closed(self) -> None:
        source = (ROOT / "Source" / "Python" / "rtype_port" /
                  "game.py").read_text(encoding="utf-8")
        needle = '        target.fill("black")\n'
        self.assertEqual(source.count(needle), 1)
        stale = source.replace(
            needle, needle + "        target.unknown_render()\n", 1)
        with self.assertRaisesRegex(FrameRenderPlanError, "PZFRP004"):
            compile_active_frame_render_plan(
                ROOT, game_source_override=stale)

    def test_distance_layer_must_remain_last(self) -> None:
        source = (ROOT / "Source" / "Python" / "rtype_port" /
                  "game.py").read_text(encoding="utf-8")
        needle = "        self._draw_debug_distance(target)\n"
        self.assertEqual(source.count(needle), 1)
        stale = source.replace(
            needle,
            needle + "        self._draw_beam_meter(target)\n",
            1)
        with self.assertRaisesRegex(FrameRenderPlanError, "PZFRP006|PZFRP008"):
            compile_active_frame_render_plan(
                ROOT, game_source_override=stale)


if __name__ == "__main__":
    unittest.main()
