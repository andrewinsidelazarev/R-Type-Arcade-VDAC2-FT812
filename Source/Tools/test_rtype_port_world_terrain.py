"""Проверка общего runtime ring tilemap восьми stages."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.stage import M72Tilemaps
from rtype_port.world_terrain import (BG_X, BG_Y, FG_X, M72WorldTerrain,
                                      Stage3BackgroundController)


class WorldTerrainRuntimeTest(unittest.TestCase):
    def test_every_stage_preloads_seven_strips_from_its_checkpoint(self) -> None:
        expected_progression = (0x0600, 0x1500, 0x1F80, 0x2A00,
                                0x3480, 0x3F00, 0x4980, 0x5400)
        for stage in range(1, 9):
            with self.subTest(stage=stage):
                terrain = M72WorldTerrain(stage)
                self.assertEqual([0x70, 0x70], terrain.tracker)
                self.assertEqual(expected_progression[stage - 1],
                                 terrain.progression)

    def test_stage1_scroll_reaches_existing_previsible_tilemap(self) -> None:
        terrain = M72WorldTerrain(1)
        for _ in range(128):
            terrain.advance()
        reference = M72Tilemaps()
        self.assertEqual(reference.source, terrain.source)
        self.assertEqual(reference.tracker, terrain.tracker)
        self.assertEqual(reference.vram, terrain.vram)

    def test_checkpoint_offsets_are_used_literally(self) -> None:
        terrain = M72WorldTerrain(4, checkpoint=1)
        self.assertEqual(0x2F40, terrain.progression)
        self.assertEqual([1830 + 70, 2220 + 70], terrain.source)
        self.assertEqual([0x0080, 0, 0x0100, 0], terrain.velocity)

    def test_f0f3_event_uses_global_checkpoint_record(self) -> None:
        terrain = M72WorldTerrain(1)
        events = []
        while terrain.progression < 0x06C0:
            events.extend(terrain.advance())
        checkpoint_event = next(event for event in events
                                if event["handler"] == 0xF0F3 and
                                event["threshold"] == 0x06C0)
        self.assertEqual(1, checkpoint_event["command"] & 0x1F)
        self.assertEqual(0x06C0, terrain.progression)
        self.assertEqual([0x0080, 0, 0x0100, 0], terrain.velocity)

    def test_all_four_q8_scroll_integrators(self) -> None:
        terrain = M72WorldTerrain(1)
        terrain.velocity[:] = [0x0080, -0x0100, 0x0040, 0x0180]
        terrain.advance()
        self.assertEqual((0, 0x01FF, 0, 1),
                         (terrain.foreground_x, terrain.foreground_y,
                          terrain.background_x, terrain.background_y))
        self.assertEqual([0, 1, 0, 0xFFFF], terrain.delta)

    def test_stage3_c46e_background_path_is_applied_after_integrator(self) -> None:
        terrain = M72WorldTerrain(3)
        while terrain.progression < 0x2000:
            terrain.advance()
        self.assertIsNotNone(terrain.stage3_background)
        # Newly allocated controller does not run in its creation pass.
        self.assertEqual(0, terrain.velocity[BG_Y])
        terrain.advance()
        self.assertEqual(0x0080, terrain.velocity[BG_X])
        self.assertEqual(0, terrain.velocity[BG_Y])
        # Eight 16-VBlank records hold `(Y=0,X=8)`. Record 8 then becomes
        # visible on the following controller update as `Y=-1,X=4`.
        for _ in range(8 * 16):
            terrain.advance()
        self.assertEqual(0x0040, terrain.velocity[BG_X])
        self.assertEqual(-0x0010, terrain.velocity[BG_Y])

    def test_stage3_path_has_exact_9280_updates_and_384_terminal_updates(self) -> None:
        rom = (ROOT / "Assets" / "Converted" / "Arcade" /
               "RTYPE_MAINCPU_REGION.bin").read_bytes()[0x10000:0x20000]
        controller = Stage3BackgroundController(rom)
        terrain = SimpleNamespace(velocity=[0, 0, 0, 0],
                                  transition_requested=False)
        for _ in range(9279):
            controller.update(terrain)
        self.assertEqual("path", controller.state)
        controller.update(terrain)
        self.assertEqual("terminal", controller.state)
        self.assertEqual(0x72FF, controller.pointer)
        for _ in range(383):
            controller.update(terrain)
        self.assertFalse(terrain.transition_requested)
        controller.update(terrain)
        self.assertEqual("done", controller.state)
        self.assertTrue(terrain.transition_requested)


if __name__ == "__main__":
    unittest.main()
