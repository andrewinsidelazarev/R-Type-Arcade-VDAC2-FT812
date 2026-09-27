"""Проверки буквальной временной шкалы смерти и checkpoint R-9."""
from __future__ import annotations

import unittest

import pygame

from rtype_port.player_lifecycle import (
    CHECKPOINTS,
    INITIAL_LIVES,
    LIFE_DECREMENT_AGE,
    MAX_LIVES,
    PLAYER_CLEAR_AGE,
    RESPAWN_AGE,
    PlayerLifecycle,
    checkpoint_for_progression,
)
from rtype_port.stage import Stage
from rtype_port.world_terrain import M72WorldTerrain


class CheckpointTests(unittest.TestCase):
    def test_complete_rom_table(self) -> None:
        self.assertEqual(16, len(CHECKPOINTS))
        self.assertEqual(tuple(range(16)), tuple(point.index for point in CHECKPOINTS))
        self.assertEqual(
            ((1, 0x0600), (1, 0x06C0), (1, 0x0A80), (1, 0x0FC0),
             (2, 0x1500), (2, 0x1A40), (3, 0x1F80),
             (4, 0x2A00), (4, 0x2F40), (5, 0x3480), (5, 0x3AC0),
             (6, 0x3F00), (6, 0x4540), (7, 0x4980), (7, 0x4F00),
             (8, 0x5400)),
            tuple((point.stage, point.progression) for point in CHECKPOINTS),
        )

    def test_latest_reached_checkpoint(self) -> None:
        self.assertEqual(0, checkpoint_for_progression(1, 0x05FF).index)
        self.assertEqual(0, checkpoint_for_progression(1, 0x06BF).index)
        self.assertEqual(1, checkpoint_for_progression(1, 0x0776).index)
        self.assertEqual(2, checkpoint_for_progression(1, 0x0A80).index)
        self.assertEqual(14, checkpoint_for_progression(7, 0x5300).index)


class LifecycleTests(unittest.TestCase):
    def test_default_and_awarded_lives_are_capped_at_eight(self) -> None:
        life = PlayerLifecycle()
        self.assertEqual(INITIAL_LIVES, life.lives)
        self.assertEqual(MAX_LIVES, life.lives)
        self.assertFalse(life.award_life())
        self.assertEqual(MAX_LIVES, life.lives)

        life = PlayerLifecycle(7)
        self.assertTrue(life.award_life())
        self.assertFalse(life.award_life())
        self.assertEqual(MAX_LIVES, life.lives)

        with self.assertRaises(ValueError):
            PlayerLifecycle(9)

    def test_exact_death_timeline_and_descriptors(self) -> None:
        life = PlayerLifecycle(3)
        self.assertTrue(life.begin_death(1, 0x0776))
        self.assertEqual(1, life.checkpoint.index)
        self.assertEqual(0x1338, life.explosion_descriptor)

        descriptors = {0: life.explosion_descriptor}
        events = {}
        for age in range(1, RESPAWN_AGE + 1):
            event = life.advance()
            descriptors[age] = life.explosion_descriptor
            if event != type(event)():
                events[age] = event

        self.assertEqual(0x1338, descriptors[3])
        self.assertEqual(0x133E, descriptors[4])
        self.assertEqual(0x1344, descriptors[7])
        self.assertEqual(0x134A, descriptors[9])
        self.assertEqual(0x1350, descriptors[11])
        self.assertEqual(0x1356, descriptors[13])
        self.assertEqual(0x135C, descriptors[16])
        self.assertEqual(0x1362, descriptors[20])
        self.assertIsNone(descriptors[PLAYER_CLEAR_AGE])
        self.assertTrue(events[PLAYER_CLEAR_AGE].player_cleared)
        self.assertTrue(events[LIFE_DECREMENT_AGE].checkpoint_rebuild)
        self.assertTrue(events[RESPAWN_AGE].respawned)
        self.assertEqual(2, life.lives)
        self.assertTrue(life.active)
        self.assertEqual(0x80, life.invulnerability)

    def test_invulnerability_and_game_over(self) -> None:
        life = PlayerLifecycle(1)
        life.begin_death(1, 0x0600)
        last = None
        for _ in range(LIFE_DECREMENT_AGE):
            last = life.advance()
        self.assertTrue(last.game_over)
        self.assertEqual("game_over", life.state)
        self.assertFalse(life.begin_death(1, 0x0600))

        protected = PlayerLifecycle()
        protected.invulnerability = 2
        self.assertFalse(protected.begin_death(1, 0x0600))
        protected.advance()
        protected.advance()
        self.assertTrue(protected.collision_enabled)


class StageCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.display.set_mode((1, 1), flags=pygame.HIDDEN)

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_stage1_ring_is_rebuilt_from_rom_manifest(self) -> None:
        stage = Stage()
        old_vblank = stage.m72_scroll.vblank
        stage.reset_checkpoint(1, 2)
        oracle = M72WorldTerrain(1, 2)
        self.assertEqual(old_vblank, stage.m72_scroll.vblank)
        self.assertEqual(0x0A80, stage.m72_scroll.progression)
        self.assertEqual(0x0080, stage.m72_scroll.foreground_velocity)
        self.assertEqual(oracle.vram[0], stage.tilemaps.vram[0])
        self.assertEqual(oracle.vram[1], stage.tilemaps.vram[1])
        self.assertEqual(oracle.source, stage.tilemaps.source)

    def test_non_stage1_colour_renderer_is_not_silently_faked(self) -> None:
        stage = Stage()
        with self.assertRaises(ValueError):
            stage.reset_checkpoint(2, 0)


if __name__ == "__main__":
    unittest.main()
