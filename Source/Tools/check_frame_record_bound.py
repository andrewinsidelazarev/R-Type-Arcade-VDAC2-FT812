#!/usr/bin/env python3
"""Emit or gate the active-Python per-frame draw-record bound proof."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from pyz80_compiler.frame_record_bound import (
    DEFAULT_STREAM_CHUNK_CAPACITY,
    FrameRecordBoundError,
    analyze_active_frame_record_bound,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "Build" / "rtype_python_frame_record_bound_status.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stream-chunk-capacity", type=int,
        default=DEFAULT_STREAM_CHUNK_CAPACITY,
        help="bounded temporary record buffer; not a whole-frame limit")
    parser.add_argument(
        "--status", action="store_true",
        help="write/print the proof status even when the live bound is blocked")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = analyze_active_frame_record_bound(
            ROOT, stream_chunk_capacity=args.stream_chunk_capacity)
    except FrameRecordBoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    value = report.as_dict()
    if (report.certified_frame_max_records is None or
            value.get("proof_complete") is not True or
            value.get("can_certify_frame_budget") is not True):
        print(
            "FAIL: sound active-Python frame record upper bound is not proved; "
            f"status={report.status}", file=sys.stderr)
        return 1
    encoded = report.to_json()
    output = args.output
    if args.status and output is None:
        output = DEFAULT_OUTPUT
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "OK: certified conservative active-Python frame bound "
        f"{report.certified_frame_max_records} records; "
        f"status={report.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
