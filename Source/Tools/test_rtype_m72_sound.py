#!/usr/bin/env python3
"""Regression checks for the complete M72 sound path."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
for search_dir in (ROOT / "Source" / "Python", ROOT / "Build" / "PythonDeps"):
    if str(search_dir) not in sys.path:
        sys.path.insert(0, str(search_dir))

from rtype_m72.sound import M72SoundSystem


class SoundSystemTests(unittest.TestCase):
    def test_shot_latch_reaches_original_driver(self) -> None:
        sound = M72SoundSystem(output=False)
        try:
            sound.command(0x30)
            pcm = sound.render_seconds(0.75)
            self.assertGreater(int(np.max(np.abs(pcm.astype(np.int32)))), 100)
            self.assertFalse(sound._latch_irq)
            self.assertEqual(0x30, sound.cpu.memory[0xF8A1])
        finally:
            sound.close()

    def test_all_latch_bytes_are_forwarded_without_name_filter(self) -> None:
        sound = M72SoundSystem(output=False)
        try:
            sound.command(0x55)
            sound.render_seconds(0.05)
            self.assertFalse(sound._latch_irq)
            self.assertEqual(0x55, sound.cpu.memory[0xF8A1])
        finally:
            sound.close()

    def test_frame_sample_count_is_rationally_clocked(self) -> None:
        sound = M72SoundSystem(output=False)
        try:
            counts = [len(sound.step_frame()) for _ in range(55)]
            expected = (sound.sample_rate * 512 * 284 * 55) // 8_000_000
            self.assertEqual(expected, sum(counts))
            self.assertLessEqual(max(counts) - min(counts), 1)
        finally:
            sound.close()


if __name__ == "__main__":
    unittest.main()
