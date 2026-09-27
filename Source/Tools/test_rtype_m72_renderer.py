"""Проверка границ активного поля полного M72-рендерера."""
from __future__ import annotations

import unittest

import numpy as np

from rtype_m72.hq_renderer import (
    HEIGHT, PLAYFIELD_HEIGHT, WIDTH, _draw_sprites,
)


class RendererClipTests(unittest.TestCase):
    def test_game_sprite_is_clipped_before_hud(self) -> None:
        target = np.full((HEIGHT, WIDTH), 0xF000, dtype=np.uint16)
        blocked = np.zeros((HEIGHT, WIDTH), dtype=np.bool_)
        atlas = np.full((1, 1, 30, 27), 0xFFFF, dtype=np.uint16)
        recolor = np.zeros((1, 4096), dtype=np.uint16)
        recolor[0, 0x0FFF] = 0x0FFF

        # Нативный верх Y=235 пересекает границу HUD Y=240.
        sprite_words = np.asarray((133, 0, 0, 320), dtype=np.uint16)
        _draw_sprites(target, atlas, recolor, blocked, sprite_words)

        self.assertTrue(np.any(target[PLAYFIELD_HEIGHT - 1] != 0xF000))
        self.assertTrue(np.all(target[PLAYFIELD_HEIGHT:] == 0xF000))


if __name__ == "__main__":
    unittest.main()
