#!/usr/bin/env python3
"""Tests for semantic-domain FT812 resident planning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyz80_compiler import (
    AssetCompileError,
    CellBankSpec,
    CellKey,
    CellSourceKey,
    FT812AssetPackBudget,
    FT812WorkingSetSpec,
    compile_ft812_working_sets,
)


def _cell(first: int, second: int) -> bytes:
    words = [first, second] * 512
    return b"".join(word.to_bytes(2, "little") for word in words)


class WorkingSetPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "cells.bin"
        self.cells = [
            _cell(0x0000, 0xF111),
            _cell(0x0000, 0xF222),
            _cell(0x0000, 0xF333),
        ]
        self.path.write_bytes(b"".join(self.cells))
        self.source = CellSourceKey("sprite", "active-python")
        self.bank = CellBankSpec(
            self.source, self.path, 32, 32, len(self.cells))
        self.budget = FT812AssetPackBudget(16, 16, 8, 0x10000)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_compiles_overlapping_frontend_combinations_exactly(self) -> None:
        domains = {
            "common": [CellKey(self.source, 0)],
            "stage1": [CellKey(self.source, 1)],
            "beam": [CellKey(self.source, 2)],
        }
        specs = [
            FT812WorkingSetSpec("s1-beam", ("beam", "common", "stage1")),
            FT812WorkingSetSpec("s1-core", ("common", "stage1")),
        ]

        plan = compile_ft812_working_sets(
            domains, [self.bank], specs, self.budget,
            project_root=self.root)

        self.assertEqual(
            [working_set.name for working_set in plan.sets],
            ["s1-beam", "s1-core"])
        expected_codes = {
            "s1-beam": {0, 1, 2},
            "s1-core": {0, 1},
        }
        for working_set in plan.sets:
            self.assertEqual(
                {entry.key.code for entry in working_set.pack.entries},
                expected_codes[working_set.name])
            for entry in working_set.pack.entries:
                self.assertEqual(
                    working_set.pack.decode(entry), self.cells[entry.key.code])
        self.assertEqual(plan.report()["domain_counts"], {
            "beam": 1, "common": 1, "stage1": 1})

    def test_unknown_uncovered_empty_and_duplicate_domains_fail_closed(self) -> None:
        domains = {
            "common": [CellKey(self.source, 0)],
            "stage1": [CellKey(self.source, 1)],
        }
        with self.assertRaisesRegex(AssetCompileError, "unknown domains"):
            compile_ft812_working_sets(
                domains, [self.bank],
                [FT812WorkingSetSpec("bad", ("missing",))], self.budget)
        with self.assertRaisesRegex(AssetCompileError, "no resident working set"):
            compile_ft812_working_sets(
                domains, [self.bank],
                [FT812WorkingSetSpec("base", ("common",))], self.budget)
        with self.assertRaisesRegex(AssetCompileError, "has no cells"):
            compile_ft812_working_sets(
                {"empty": []}, [self.bank],
                [FT812WorkingSetSpec("empty", ("empty",))], self.budget)
        with self.assertRaisesRegex(AssetCompileError, "duplicate"):
            compile_ft812_working_sets(
                {"common": [CellKey(self.source, 0)]}, [self.bank],
                [FT812WorkingSetSpec("same", ("common",)),
                 FT812WorkingSetSpec("same", ("common",))], self.budget)

    def test_named_combination_reports_resident_overflow(self) -> None:
        domains = {
            "common": [CellKey(self.source, 0)],
            "stage1": [CellKey(self.source, 1)],
        }
        full = compile_ft812_working_sets(
            domains, [self.bank],
            [FT812WorkingSetSpec("s1", ("common", "stage1"))],
            self.budget)
        needed = len(full.sets[0].pack.data)

        with self.assertRaisesRegex(
                AssetCompileError, "working set 's1'.*asset pack needs"):
            compile_ft812_working_sets(
                domains, [self.bank],
                [FT812WorkingSetSpec("s1", ("common", "stage1"))],
                FT812AssetPackBudget(16, 16, 8, needed - 1))

    def test_spec_requires_sorted_unique_domain_names(self) -> None:
        with self.assertRaisesRegex(AssetCompileError, "unique/sorted"):
            FT812WorkingSetSpec("bad", ("z", "a", "a"))


if __name__ == "__main__":
    unittest.main()
