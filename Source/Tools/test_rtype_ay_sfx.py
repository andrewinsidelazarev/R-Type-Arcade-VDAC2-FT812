#!/usr/bin/env python3
"""Проверки генератора эффектов AY: формат строки и таблица команд."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))

import rtype_ay_sfx as ay                                      # noqa: E402
import rtype_gs                                                # noqa: E402


class RowFormat(unittest.TestCase):
    def test_row_is_counter_and_eleven_registers(self):
        state = ay.FrameState(periods=(0x123, 0x0FF, 1), noise=17, mixer=0x38, volumes=(15, 7, 0))
        row = ay.state_to_row(3, state)
        self.assertEqual(len(row), ay.ROW_SIZE)
        self.assertEqual(row[0], 3)                            # кадров держать состояние
        self.assertEqual((row[1], row[2]), (0x23, 0x01))       # период A: младший и старший
        self.assertEqual(row[7], 17)                           # регистр 6 — период шума
        self.assertEqual(row[8], 0x38)                         # регистр 7 — микшер
        self.assertEqual((row[9], row[10], row[11]), (15, 7, 0))

    def test_mixer_bits_disable_unused_sources(self):
        # Регистр 7: единица запрещает источник. Биты 0…2 — тон каналов A…C, 3…5 — шум.
        # Канал A тоном: бит 0 = 0, бит 3 = 1. Канал B шумом: бит 1 = 1, бит 4 = 0. Канал C молчит.
        self.assertEqual(ay.mixer_for_modes(['tone', 'noise', 'sil']), 0b101110)
        # Канал A тоном и шумом сразу: оба бита нули, остальные каналы закрыты.
        self.assertEqual(ay.mixer_for_modes(['both', 'sil', 'sil']), 0b110110)
        self.assertEqual(ay.mixer_for_modes(['sil', 'sil', 'sil']), ay.MIXER_SILENT)

    def test_volume_levels_are_three_decibel_steps(self):
        self.assertAlmostEqual(float(ay.VOLUME_LEVELS[15]), 1.0)
        self.assertAlmostEqual(float(ay.VOLUME_LEVELS[13]) / float(ay.VOLUME_LEVELS[15]), 0.5, places=3)
        self.assertEqual(ay.level_to_volume(1.0), 15)
        self.assertEqual(ay.level_to_volume(0.0), 0)


class Blob(unittest.TestCase):
    def test_table_covers_every_rom_command(self):
        blob = (ROOT / 'Audio' / 'Converted' / 'RTYPE_AY_SFX.bin').read_bytes()
        table = len(rtype_gs.ROM_COMMANDS) * ay.RECORD_SIZE
        self.assertGreater(len(blob), table)
        for index in range(len(rtype_gs.ROM_COMMANDS)):
            offset = int.from_bytes(blob[index * ay.RECORD_SIZE:(index + 1) * ay.RECORD_SIZE], 'little')
            self.assertLess(offset, len(blob), f'запись {index} указывает за блок')
            if offset:                                          # у звучащих команд поток непустой
                self.assertNotEqual(blob[offset], 0)

    def test_every_stream_ends_with_zero_counter(self):
        blob = (ROOT / 'Audio' / 'Converted' / 'RTYPE_AY_SFX.bin').read_bytes()
        seen = 0
        for index in range(len(rtype_gs.ROM_COMMANDS)):
            offset = int.from_bytes(blob[index * ay.RECORD_SIZE:(index + 1) * ay.RECORD_SIZE], 'little')
            if not offset:
                continue
            while blob[offset]:
                offset += ay.ROW_SIZE
            seen += 1
        self.assertGreater(seen, 40)                            # 46 звучащих команд из 48


if __name__ == '__main__':
    unittest.main()
