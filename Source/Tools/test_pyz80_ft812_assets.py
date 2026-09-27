#!/usr/bin/env python3
"""Exactness and budget tests for the generic FT812 hybrid packer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Source.Tools.sim_frame_png import DLRenderer
from pyz80_compiler.assets import (
    AssetCompileError,
    CellBankSpec,
    CellKey,
    CellSourceKey,
)
from pyz80_compiler.ft812_assets import (
    FT812_ARGB4,
    FT812_PALETTED4444,
    FT812_PALETTE_BYTES,
    FT812AssetPackBudget,
    compile_ft812_cell_assets,
)


def _words(values: list[int]) -> bytes:
    return b"".join(value.to_bytes(2, "little") for value in values)


class FT812AssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _bank(self, name: str, cells: list[bytes], width: int,
              height: int) -> CellBankSpec:
        path = self.root / f"{name}.argb4444"
        path.write_bytes(b"".join(cells))
        return CellBankSpec(
            CellSourceKey("test", name), path,
            width, height, len(cells))

    @staticmethod
    def _budget(**changes: int) -> FT812AssetPackBudget:
        values = {
            "max_logical_entries": 32,
            "max_unique_cells": 32,
            "max_palettes": 8,
            "max_bytes": 0x10000,
            "alignment": 4,
        }
        values.update(changes)
        return FT812AssetPackBudget(**values)

    def test_shared_paletted4444_is_byte_exact_and_smaller(self) -> None:
        first = _words([0x0000, 0xF123] * 512)
        second = _words([0x0000, 0xF456] * 512)
        bank = self._bank("shared", [first, second], 32, 32)
        keys = [CellKey(bank.key, 0), CellKey(bank.key, 1)]

        result = compile_ft812_cell_assets(keys, [bank], self._budget())

        self.assertEqual(len(result.palettes), 1)
        self.assertEqual(
            {entry.format_code for entry in result.entries},
            {FT812_PALETTED4444})
        self.assertEqual(
            {entry.palette_offset for entry in result.entries},
            {result.palettes[0].offset})
        self.assertEqual([result.decode(entry) for entry in result.entries],
                         [first, second])
        self.assertLess(len(result.data), result.raw_argb4444_bytes)
        self.assertEqual(result.palettes[0].offset % 2, 0)

    def test_cell_above_256_colours_remains_argb4(self) -> None:
        cell = _words(list(range(17 * 17)))
        bank = self._bank("many-colours", [cell], 17, 17)

        result = compile_ft812_cell_assets(
            [CellKey(bank.key, 0)], [bank], self._budget())

        self.assertEqual(result.entries[0].format_code, FT812_ARGB4)
        self.assertIsNone(result.entries[0].palette_offset)
        self.assertEqual(result.decode(result.entries[0]), cell)
        self.assertEqual(result.data, cell)

    def test_tiny_unprofitable_palette_group_remains_argb4(self) -> None:
        cell = _words([0x0000, 0xF111, 0xF222, 0xF333])
        bank = self._bank("tiny", [cell], 2, 2)

        result = compile_ft812_cell_assets(
            [CellKey(bank.key, 0)], [bank], self._budget())

        self.assertEqual(result.entries[0].format_code, FT812_ARGB4)
        self.assertEqual(result.palettes, ())

    def test_flip_alias_and_input_order_are_deterministic(self) -> None:
        pixels = [0x0000, 0xF123] * 512
        cell = _words(pixels)
        bank_a = self._bank("a", [cell], 32, 32)
        bank_b = self._bank("b", [cell], 32, 32)
        requests = [
            CellKey(bank_b.key, 0),
            CellKey(bank_a.key, 0, flip_x=True),
            CellKey(bank_a.key, 0),
        ]

        first = compile_ft812_cell_assets(
            requests, [bank_b, bank_a], self._budget())
        second = compile_ft812_cell_assets(
            reversed(requests), [bank_a, bank_b], self._budget())

        self.assertEqual(first.data, second.data)
        self.assertEqual(first.entries, second.entries)
        self.assertEqual(first.unique_cells, 2)
        for entry in first.entries:
            expected = cell
            if entry.key.flip_x:
                rows = [pixels[row * 32:(row + 1) * 32]
                        for row in range(32)]
                expected = _words([
                    value for row in rows for value in reversed(row)])
            self.assertEqual(first.decode(entry), expected)

    def test_palette_and_resident_byte_limits_fail_closed(self) -> None:
        # Disjoint 256-colour cells cannot share a PALETTED4444 table.
        a = _words(list(range(256)) * 4)
        b = _words(list(range(0x100, 0x200)) * 4)
        bank = self._bank("limits", [a, b], 32, 32)
        keys = [CellKey(bank.key, 0), CellKey(bank.key, 1)]

        with self.assertRaisesRegex(AssetCompileError, "needs 2 palettes"):
            compile_ft812_cell_assets(
                keys, [bank], self._budget(max_palettes=1))

        full = compile_ft812_cell_assets(keys, [bank], self._budget())
        with self.assertRaisesRegex(AssetCompileError, "asset pack needs"):
            compile_ft812_cell_assets(
                keys, [bank], self._budget(max_bytes=len(full.data) - 1))

    def test_report_exposes_hardware_state_and_exact_savings(self) -> None:
        cell = _words([0x0000, 0xFFFF] * 512)
        bank = self._bank("report", [cell], 32, 32)
        result = compile_ft812_cell_assets(
            [CellKey(bank.key, 0)], [bank], self._budget(),
            project_root=self.root)
        report = result.report()

        self.assertEqual(report["format"], "pyz80-ft812-cell-pack-v1")
        self.assertEqual(report["palette_count"], 1)
        self.assertEqual(report["format_counts"]["PALETTED4444"], 1)
        self.assertEqual(report["entries"][0]["format_code"], 15)
        self.assertEqual(report["entries"][0]["stride"], 32)
        self.assertEqual(report["palettes"][0]["size"],
                         FT812_PALETTE_BYTES)
        self.assertGreater(report["saved_bytes"], 0)

    def test_real_ft812_dl_state_renders_both_exact_storage_formats(self) -> None:
        paletted = _words([0xF123, 0xF456] * 512)
        direct_words = [0xF000 + value for value in range(17 * 17)]
        direct = _words(direct_words)
        paletted_bank = self._bank("hardware-paletted", [paletted], 32, 32)
        direct_bank = self._bank("hardware-direct", [direct], 17, 17)
        keys = [CellKey(paletted_bank.key, 0), CellKey(direct_bank.key, 0)]
        result = compile_ft812_cell_assets(
            keys, [direct_bank, paletted_bank], self._budget())
        entries = {entry.key: entry for entry in result.entries}
        self.assertEqual(entries[keys[0]].format_code, FT812_PALETTED4444)
        self.assertEqual(entries[keys[1]].format_code, FT812_ARGB4)

        ram_g_base = 0x2000
        ram_g = bytearray(0x100000)
        ram_g[ram_g_base:ram_g_base + len(result.data)] = result.data

        def op(code: int, value: int = 0) -> int:
            return (code << 24) | value

        def draw(entry, x: int) -> list[int]:
            words = [op(0x01, ram_g_base + entry.offset)]
            if entry.palette_offset is not None:
                words.append(op(0x2A, ram_g_base + entry.palette_offset))
            words.extend((
                op(0x07, (entry.format_code << 19) |
                   (entry.stride << 9) | entry.height),
                op(0x08, (entry.width << 9) | entry.height),
                op(0x1F, 1),
                0x40000000 | ((x * 16) << 15),
                op(0x21),
            ))
            return words

        dl_words = [op(0x02), op(0x26, 4)]
        dl_words += draw(entries[keys[0]], 0)
        dl_words += draw(entries[keys[1]], 40)
        dl_words.append(0)
        renderer = DLRenderer(bytes(ram_g))
        renderer.run(b"".join(
            word.to_bytes(4, "little") for word in dl_words))

        self.assertEqual(renderer.img.getpixel((0, 0)), (17, 34, 51))
        self.assertEqual(renderer.img.getpixel((1, 0)), (68, 85, 102))
        for index in (0, 1, 16, 17, 288):
            word = direct_words[index]
            expected = (
                ((word >> 8) & 0xF) * 17,
                ((word >> 4) & 0xF) * 17,
                (word & 0xF) * 17,
            )
            self.assertEqual(
                renderer.img.getpixel((40 + index % 17, index // 17)),
                expected)


if __name__ == "__main__":
    unittest.main()
