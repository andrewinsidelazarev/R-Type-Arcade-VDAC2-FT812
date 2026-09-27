#!/usr/bin/env python3
"""Emit the finite source/ROM frame-record reachability sub-proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pyz80_compiler.frame_record_bound import (
    FrameRecordBoundError,
    analyze_active_frame_record_bound,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "Build" / "rtype_python_frame_record_reachability_status.json")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = analyze_active_frame_record_bound(ROOT).as_dict()
    except FrameRecordBoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    proof = report.get("abstract_reachability")
    if not isinstance(proof, dict) or not proof.get(
            "proof_complete_for_conservative_certification"):
        print("FAIL: finite abstract reachability proof is missing", file=sys.stderr)
        return 1
    encoded = json.dumps(
        proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "OK: finite abstract frame bound "
        f"{proof['frame_records']['finite_upper_bound']} records; "
        "exact maximum remains a separate obligation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
