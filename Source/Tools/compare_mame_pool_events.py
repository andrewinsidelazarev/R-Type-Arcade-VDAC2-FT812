#!/usr/bin/env python3
"""Compare exact M72 dynamic-object allocation/release streams.

The World ROM writes a new handler word from ``$03C4`` after taking a slot
from the free list and clears that word from ``$03FD`` when returning the
slot.  Keeping only those writes gives a compact, deterministic description
of pool ownership without loading multi-hundred-megabyte traces into memory.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


POOL_FIRST = 0x40540
POOL_LAST = 0x41D00
POOL_STRIDE = 0x40
ALLOC_PC = 0x003C4
RELEASE_PC = 0x003FD


@dataclass(frozen=True)
class PoolEvent:
    frame: int
    address: int
    handler: int
    pc: int

    @property
    def slot(self) -> int:
        return (self.address - POOL_FIRST) // POOL_STRIDE

    def display(self) -> str:
        action = "alloc" if self.pc == ALLOC_PC else "free "
        return (
            f"frame={self.frame:5d} {action} slot={self.slot:02d} "
            f"address=${self.address:05X} handler=${self.handler:04X}"
        )


def matching_lines(path: Path, pattern: str) -> Iterator[str]:
    """Use ripgrep to avoid decoding millions of irrelevant CSV writes."""
    ripgrep = shutil.which("rg")
    if ripgrep is None:
        with path.open("r", encoding="utf-8", newline="") as source:
            next(source, None)
            yield from source
        return
    process = subprocess.Popen(
        [ripgrep, "--no-line-number", "--no-filename",
         pattern, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    yield from process.stdout
    stderr = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()
    if return_code not in (0, 1):
        raise RuntimeError(f"rg failed for {path}: {stderr.strip()}")


def _candidate_lines(path: Path) -> Iterator[str]:
    yield from matching_lines(path, r",(003C4|003FD)\r?$")


def events(path: Path) -> Iterator[PoolEvent]:
    with path.open("r", encoding="utf-8", newline="") as source:
        header = source.readline().strip().split(",")
    required = ("frame", "address", "data", "mask", "pc")
    if tuple(header) != required:
        raise ValueError(f"{path}: expected columns {required}, got {header}")
    for line in _candidate_lines(path):
        frame_text, address_text, data_text, _mask_text, pc_text = (
            line.rstrip("\r\n").split(","))
        pc = int(pc_text, 16)
        if pc not in (ALLOC_PC, RELEASE_PC):
            continue
        address = int(address_text, 16)
        if not POOL_FIRST <= address <= POOL_LAST:
            continue
        if (address - POOL_FIRST) % POOL_STRIDE:
            continue
        yield PoolEvent(
            frame=int(frame_text),
            address=address,
            handler=int(data_text, 16),
            pc=pc,
        )


def compare(left_path: Path, right_path: Path) -> int:
    left = events(left_path)
    right = events(right_path)
    matched = 0
    while True:
        left_event = next(left, None)
        right_event = next(right, None)
        if left_event is None or right_event is None:
            if left_event is None and right_event is None:
                print(f"EXACT {matched} events")
                return 0
            print(f"COMMON PREFIX {matched} events")
            print("left : " + ("EOF" if left_event is None else left_event.display()))
            print("right: " + ("EOF" if right_event is None else right_event.display()))
            return 1
        if left_event != right_event:
            print(f"FIRST MISMATCH after {matched} events")
            print("left : " + left_event.display())
            print("right: " + right_event.display())
            return 1
        matched += 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return compare(args.left, args.right)


if __name__ == "__main__":
    raise SystemExit(main())
