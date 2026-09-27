#!/usr/bin/env python3
"""Verify parallel HQT3 analyzers against the published deterministic reports."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from pyz80_compiler.hqt3_partition_solver import (
    analyze_hqt3_partition_solver,
)
from pyz80_compiler.hqt3_ramg_schedule import analyze_hqt3_ramg_schedule


ROOT = Path(__file__).resolve().parents[2]


def _published(name: str) -> dict[str, object]:
    path = ROOT / "Build" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"published report is not an object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs", type=int, default=max(1, os.cpu_count() or 1))
    arguments = parser.parse_args()
    if arguments.jobs < 1:
        parser.error("--jobs must be >= 1")

    schedule_expected = _published(
        "rtype_python_hqt3_ramg_schedule_status.json")
    started = time.perf_counter()
    schedule_actual = analyze_hqt3_ramg_schedule(
        ROOT, max_workers=arguments.jobs)
    schedule_seconds = time.perf_counter() - started
    if schedule_actual != schedule_expected:
        raise RuntimeError("parallel HQT3 RAM_G schedule differs")
    print(
        f"parallel HQT3 RAM_G schedule: exact, {schedule_seconds:.2f}s",
        flush=True,
    )

    partition_expected = _published(
        "rtype_python_hqt3_partition_solver_status.json")
    started = time.perf_counter()
    partition_actual = analyze_hqt3_partition_solver(
        ROOT, max_workers=arguments.jobs)
    partition_seconds = time.perf_counter() - started
    if partition_actual != partition_expected:
        raise RuntimeError("parallel HQT3 partition solver differs")
    print(
        f"parallel HQT3 partition solver: exact, {partition_seconds:.2f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
