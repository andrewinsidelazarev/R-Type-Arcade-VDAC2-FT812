"""Byte-exact rollback for translator-owned generated outputs.

The Python-to-target pipeline materialises several independent artifacts.  An
individual file is written atomically by its producer, but a later failure can
otherwise leave a mixture of generations.  ``GenerationTransaction`` takes a
bounded snapshot of declared generated files/directories and restores that
snapshot if the body raises.

This is deliberately not a general filesystem transaction.  Callers must
declare only output surfaces they own completely; source directories are not
valid transaction roots.  Existing files are restored through a temporary
sibling plus ``os.replace``.  Files newly created inside an owned surface are
removed during rollback.  Successful bodies keep their outputs unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Iterable


class GenerationTransactionError(RuntimeError):
    """Invalid output ownership or a failed byte-exact rollback."""


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    data: bytes | None


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".rollback", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class GenerationTransaction:
    """Restore declared generated outputs when a generation step fails."""

    def __init__(
            self, *, files: Iterable[Path | str] = (),
            directories: Iterable[Path | str] = ()) -> None:
        self._files = tuple(Path(item).resolve() for item in files)
        self._directories = tuple(Path(item).resolve() for item in directories)
        if len(set(self._files)) != len(self._files):
            raise GenerationTransactionError("duplicate owned output file")
        if len(set(self._directories)) != len(self._directories):
            raise GenerationTransactionError("duplicate owned output directory")
        for directory in self._directories:
            if directory.exists() and not directory.is_dir():
                raise GenerationTransactionError(
                    f"owned output directory is not a directory: {directory}")
            if directory.is_symlink():
                raise GenerationTransactionError(
                    f"owned output directory may not be a symlink: {directory}")
        for first_index, first in enumerate(self._directories):
            for second in self._directories[first_index + 1:]:
                if first in second.parents or second in first.parents:
                    raise GenerationTransactionError(
                        "owned output directories may not contain each other")
        self._snapshot: tuple[_Snapshot, ...] | None = None

    def _owned_paths(self) -> tuple[Path, ...]:
        paths = set(self._files)
        for directory in self._directories:
            if not directory.exists():
                continue
            for candidate in directory.rglob("*"):
                if candidate.is_symlink():
                    raise GenerationTransactionError(
                        f"symlink inside owned output surface: {candidate}")
                if candidate.is_file():
                    paths.add(candidate.resolve())
        return tuple(sorted(paths, key=lambda item: str(item).casefold()))

    def __enter__(self) -> "GenerationTransaction":
        if self._snapshot is not None:
            raise GenerationTransactionError(
                "generation transaction cannot be entered twice")
        snapshots: list[_Snapshot] = []
        for path in self._owned_paths():
            if path.exists() and not path.is_file():
                raise GenerationTransactionError(
                    f"owned output file is not a regular file: {path}")
            snapshots.append(_Snapshot(
                path=path,
                data=path.read_bytes() if path.is_file() else None,
            ))
        self._snapshot = tuple(snapshots)
        return self

    def _current_directory_files(self) -> set[Path]:
        result: set[Path] = set()
        for directory in self._directories:
            if not directory.exists():
                continue
            for candidate in directory.rglob("*"):
                if candidate.is_symlink():
                    raise GenerationTransactionError(
                        f"symlink appeared inside owned output surface: {candidate}")
                if candidate.is_file():
                    result.add(candidate.resolve())
        return result

    def rollback(self) -> None:
        if self._snapshot is None:
            raise GenerationTransactionError(
                "generation transaction was not entered")
        previous = {item.path: item.data for item in self._snapshot}
        current = self._current_directory_files() | set(self._files)

        # Restore old content first.  A new file is removed only after every
        # previous file has been made byte-exact again.
        for path, data in previous.items():
            if data is not None:
                _atomic_replace(path, data)
        for path in sorted(current - {
                item.path for item in self._snapshot if item.data is not None
                }, key=lambda item: str(item).casefold(), reverse=True):
            if path.exists():
                if not path.is_file() or path.is_symlink():
                    raise GenerationTransactionError(
                        f"refusing to remove non-regular generated output: {path}")
                path.unlink()

        # Remove only empty directories below declared generated roots.
        for directory in self._directories:
            if not directory.exists():
                continue
            descendants = sorted(
                (item for item in directory.rglob("*") if item.is_dir()),
                key=lambda item: len(item.parts), reverse=True)
            for descendant in descendants:
                try:
                    descendant.rmdir()
                except OSError:
                    pass

        for path, data in previous.items():
            if data is None:
                if path.exists():
                    raise GenerationTransactionError(
                        f"new output survived rollback: {path}")
            elif not path.is_file() or path.read_bytes() != data:
                raise GenerationTransactionError(
                    f"output was not restored byte-exactly: {path}")

    def __exit__(self, exception_type, exception, traceback) -> bool:
        if exception_type is not None:
            try:
                self.rollback()
            except Exception as rollback_error:
                raise GenerationTransactionError(
                    "translator failed and generated outputs could not be "
                    "restored byte-exactly") from rollback_error
        return False


__all__ = [
    "GenerationTransaction",
    "GenerationTransactionError",
]
