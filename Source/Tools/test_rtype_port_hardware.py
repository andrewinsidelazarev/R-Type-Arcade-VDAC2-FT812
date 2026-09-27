"""Проверки целевого Z80/FT812-слоя активного Python-runtime."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from rtype_port.hardware import Ft812Display, RAM_G_SIZE, Z80TargetState
from rtype_port.title import prompt_visible


class TitlePromptBlinkTest(unittest.TestCase):
    def test_prompt_uses_complete_32_on_32_off_period(self) -> None:
        self.assertFalse(prompt_visible(275))
        self.assertTrue(prompt_visible(276))
        self.assertTrue(prompt_visible(307))
        self.assertFalse(prompt_visible(308))
        self.assertFalse(prompt_visible(339))
        self.assertTrue(prompt_visible(340))


class Ft812DisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.display.init()
        pygame.display.set_mode((1, 1))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.display.quit()

    def test_bitmap_is_quantized_uploaded_and_listed(self) -> None:
        display = Ft812Display()
        target = display.begin_frame()
        source = pygame.Surface((2, 1), pygame.SRCALPHA, 32).convert_alpha()
        source.set_at((0, 0), (0x12, 0x34, 0x56, 0x78))
        source.set_at((1, 0), (0xFE, 0xDC, 0xBA, 0x98))
        target.blit(source, (7, 9))

        self.assertEqual(4, display.ram_g_used)
        self.assertEqual(bytes((0x35, 0x71, 0xDB, 0x9F)),
                         bytes(display.ram_g[:4]))
        self.assertEqual((0x07, 0x17, 0x27, 0xFF),
                         display.logical.get_at((7, 9)))
        self.assertLessEqual(display.ram_g_used, RAM_G_SIZE)
        self.assertEqual(0, len(display.display_list) % 4)
        self.assertEqual(bytes(4), display.display_list[-4:])

    def test_same_surface_is_uploaded_once_per_frame(self) -> None:
        display = Ft812Display()
        target = display.begin_frame()
        source = pygame.Surface((8, 8), pygame.SRCALPHA, 32).convert_alpha()
        source.fill("white")
        target.blit(source, (0, 0))
        used = display.ram_g_used
        target.blit(source, (20, 20))
        self.assertEqual(used, display.ram_g_used)

    def test_invalidated_framebuffer_is_reencoded(self) -> None:
        display = Ft812Display()
        source = pygame.Surface((1, 1), pygame.SRCALPHA, 32).convert_alpha()
        source.fill((255, 0, 0, 255))
        target = display.begin_frame()
        target.blit(source, (0, 0))
        self.assertEqual(bytes((0x00, 0xFF)), bytes(display.ram_g[:2]))

        source.fill((0, 255, 0, 255))
        target = display.begin_frame()
        target.invalidate(source)
        target.blit(source, (0, 0))
        self.assertEqual(bytes((0xF0, 0xF0)), bytes(display.ram_g[:2]))

    def test_prepacked_argb4444_framebuffer_uses_supplied_words(self) -> None:
        display = Ft812Display()
        source = pygame.Surface((2, 1), pygame.SRCALPHA, 32).convert_alpha()
        source.set_at((0, 0), (17, 34, 51, 255))
        source.set_at((1, 0), (68, 85, 102, 255))
        target = display.begin_frame()
        target.blit_argb4444(source, bytes((0x23, 0xF1, 0x56, 0xF4)), (0, 0))
        self.assertEqual(bytes((0x23, 0xF1, 0x56, 0xF4)),
                         bytes(display.ram_g[:4]))
        self.assertEqual((17, 34, 51, 255), display.logical.get_at((0, 0)))


class Z80TargetStateTest(unittest.TestCase):
    def test_frame_and_address_space_wrap_like_z80(self) -> None:
        state = Z80TargetState()
        state.write_word(state.FRAME_COUNTER, 0xFFFF)
        self.assertEqual(0, state.next_frame(0xA5, 2))
        self.assertEqual(0xA5, state.read_byte(state.INPUT_STATE))
        self.assertEqual(2, state.read_byte(state.GAME_MODE))
        state.write_word(0xFFFF, 0x1234)
        self.assertEqual(0x34, state.read_byte(0xFFFF))
        self.assertEqual(0x12, state.read_byte(0x0000))
        state.out_port(0x1FFFD, 0x1F8)
        self.assertEqual((0xFFFD, 0xF8), state.out_log[-1])

    def test_port_transaction_before_first_vblank_does_not_steal_entry(self) -> None:
        state = Z80TargetState()
        state.out_port(0x00BB, 0x63)
        self.assertEqual(1, state.next_frame(0, 0))


if __name__ == "__main__":
    unittest.main()
