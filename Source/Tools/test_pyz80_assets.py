#!/usr/bin/env python3
"""Проверки точного универсального упаковщика растровых ячеек."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from pyz80_compiler.assets import (
    ARGB4444_LE,
    AssetCompileError,
    AssetPackBudget,
    CellBankSpec,
    CellKey,
    CellSourceKey,
    compile_cell_assets,
)


def _pixel(value: int) -> bytes:
    return value.to_bytes(2, "little")


class PyZ80AssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _bank(self, name: str, cells: list[bytes], width: int = 2,
              height: int = 2) -> CellBankSpec:
        path = self.root / f"{name}.bin"
        path.write_bytes(b"".join(cells))
        return CellBankSpec(
            key=CellSourceKey("sprite", name, 3),
            path=path,
            cell_width=width,
            cell_height=height,
            cell_count=len(cells),
        )

    @staticmethod
    def _budget(**overrides: int) -> AssetPackBudget:
        values = {
            "max_logical_entries": 16,
            "max_unique_cells": 16,
            "max_bytes": 4096,
            "alignment": 4,
        }
        values.update(overrides)
        return AssetPackBudget(**values)

    def test_selects_only_requested_source_bytes(self) -> None:
        cells = [bytes([index]) * 8 for index in range(4)]
        bank = self._bank("typed20", cells)
        key = CellKey(bank.key, 2)
        result = compile_cell_assets(
            [key], [bank], self._budget(), project_root=self.root)

        self.assertEqual(result.data, cells[2])
        self.assertEqual(result.entries[0].source_offset, 16)
        self.assertEqual(result.entries[0].source_path, "typed20.bin")
        self.assertEqual(result.entries[0].pixel_format, ARGB4444_LE)
        self.assertEqual(result.entries[0].payload_sha256,
                         hashlib.sha256(cells[2]).hexdigest())

    def test_materializes_horizontal_and_vertical_flip_by_whole_pixels(self) -> None:
        cell = b"".join(_pixel(value) for value in (1, 2, 3, 4))
        bank = self._bank("flip", [cell])
        keys = [
            CellKey(bank.key, 0, flip_x=True),
            CellKey(bank.key, 0, flip_y=True),
            CellKey(bank.key, 0, flip_x=True, flip_y=True),
        ]
        result = compile_cell_assets(keys, [bank], self._budget())
        payloads = {
            entry.key: result.data[entry.offset:entry.offset + entry.size]
            for entry in result.entries
        }

        self.assertEqual(payloads[keys[0]], b"".join(
            _pixel(value) for value in (2, 1, 4, 3)))
        self.assertEqual(payloads[keys[1]], b"".join(
            _pixel(value) for value in (3, 4, 1, 2)))
        self.assertEqual(payloads[keys[2]], b"".join(
            _pixel(value) for value in (4, 3, 2, 1)))

    def test_deduplicates_only_identical_payload_and_is_deterministic(self) -> None:
        same = bytes.fromhex("1032547698badcfe")
        bank_a = self._bank("a", [same])
        bank_b = self._bank("b", [same])
        requests = [CellKey(bank_b.key, 0), CellKey(bank_a.key, 0)]

        first = compile_cell_assets(requests, [bank_b, bank_a], self._budget())
        second = compile_cell_assets(reversed(requests), [bank_a, bank_b], self._budget())

        self.assertEqual(first.data, same)
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.entries, second.entries)
        self.assertEqual(first.unique_cells, 1)
        self.assertEqual({entry.offset for entry in first.entries}, {0})
        self.assertEqual(first.report()["deduplicated_entries"], 1)

    def test_rejects_malformed_bank_size(self) -> None:
        path = self.root / "broken.bin"
        path.write_bytes(bytes(7))
        source = CellSourceKey("terrain", "s0_fg")
        bank = CellBankSpec(source, path, 2, 2, 1)
        with self.assertRaisesRegex(AssetCompileError, "размер 7"):
            compile_cell_assets(
                [CellKey(source, 0)], [bank], self._budget())

    def test_rejects_logical_unique_and_byte_budget_overflow(self) -> None:
        cells = [bytes([index]) * 8 for index in range(3)]
        bank = self._bank("budget", cells)
        requests = [CellKey(bank.key, index) for index in range(3)]

        with self.assertRaisesRegex(AssetCompileError, "логических ячеек"):
            compile_cell_assets(
                requests, [bank], self._budget(max_logical_entries=2))
        with self.assertRaisesRegex(AssetCompileError, "уникальных ячеек"):
            compile_cell_assets(
                requests, [bank], self._budget(max_unique_cells=2))
        with self.assertRaisesRegex(AssetCompileError, "требуется 16 байт"):
            compile_cell_assets(
                requests[:2], [bank], self._budget(max_bytes=15))

    def test_report_contains_complete_provenance(self) -> None:
        cell = bytes.fromhex("0011223344556677")
        bank = self._bank("report", [cell])
        result = compile_cell_assets(
            [CellKey(bank.key, 0)], [bank], self._budget(),
            project_root=self.root)
        report = result.report()

        self.assertEqual(report["format"], "pyz80-cell-pack-v1")
        self.assertEqual(report["size"], 8)
        self.assertEqual(report["logical_entries"], 1)
        self.assertEqual(report["unique_cells"], 1)
        self.assertEqual(report["sources"][0]["path"], "report.bin")
        self.assertEqual(report["entries"][0]["width"], 2)
        self.assertEqual(report["entries"][0]["height"], 2)


if __name__ == "__main__":
    unittest.main()
