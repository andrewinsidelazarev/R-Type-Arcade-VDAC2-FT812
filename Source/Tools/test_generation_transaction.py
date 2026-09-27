#!/usr/bin/env python3
"""Focused tests for byte-exact translator output rollback."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pyz80_compiler.generation_transaction import (
    GenerationTransaction,
    GenerationTransactionError,
)


class GenerationTransactionTests(unittest.TestCase):
    def test_success_keeps_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "generated"
            generated.mkdir()
            output = generated / "result.bin"
            output.write_bytes(b"old")
            with GenerationTransaction(directories=(generated,)):
                output.write_bytes(b"new")
                (generated / "second.bin").write_bytes(b"second")
            self.assertEqual(output.read_bytes(), b"new")
            self.assertEqual((generated / "second.bin").read_bytes(), b"second")

    def test_failure_restores_complete_owned_surface_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "generated"
            nested = generated / "nested"
            nested.mkdir(parents=True)
            first = generated / "first.bin"
            second = nested / "second.bin"
            explicit = root / "report.json"
            unowned = root / "source.py"
            first.write_bytes(b"first-before")
            second.write_bytes(b"second-before")
            explicit.write_bytes(b"report-before")
            unowned.write_bytes(b"source-before")

            with self.assertRaisesRegex(RuntimeError, "late failure"):
                with GenerationTransaction(
                        files=(explicit,), directories=(generated,)):
                    first.write_bytes(b"first-after")
                    second.unlink()
                    explicit.write_bytes(b"report-after")
                    (generated / "new.bin").write_bytes(b"new")
                    added = generated / "added"
                    added.mkdir()
                    (added / "newer.bin").write_bytes(b"newer")
                    unowned.write_bytes(b"source-user-change")
                    raise RuntimeError("late failure")

            self.assertEqual(first.read_bytes(), b"first-before")
            self.assertEqual(second.read_bytes(), b"second-before")
            self.assertEqual(explicit.read_bytes(), b"report-before")
            self.assertFalse((generated / "new.bin").exists())
            self.assertFalse((generated / "added").exists())
            self.assertEqual(unowned.read_bytes(), b"source-user-change")

    def test_new_explicit_file_is_removed_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new.json"
            with self.assertRaises(ValueError):
                with GenerationTransaction(files=(output,)):
                    output.write_text("partial", encoding="utf-8")
                    raise ValueError("fail")
            self.assertFalse(output.exists())

    def test_rejects_nested_owned_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(GenerationTransactionError):
                GenerationTransaction(
                    directories=(root, root / "nested"))


if __name__ == "__main__":
    unittest.main()
