#!/usr/bin/env python3
"""Emit the source-derived FT812 sprite-fragment envelope status."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from pyz80_compiler.frame_sprite_fragment_envelope import (
    DEFAULT_CHUNK_CAPACITY,
    FrameSpriteFragmentEnvelopeError,
    analyze_frame_sprite_fragment_envelope,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "Build" / "rtype_python_frame_sprite_fragment_envelope_status.json")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chunk-capacity", type=int, default=DEFAULT_CHUNK_CAPACITY,
        help="caller-owned bounded fast-record chunk (1..128)")
    parser.add_argument(
        "--status", action="store_true",
        help="write the fail-closed status even when HQT3 coverage is incomplete")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = analyze_frame_sprite_fragment_envelope(
            ROOT, chunk_capacity=args.chunk_capacity)
    except (FrameSpriteFragmentEnvelopeError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    output = args.output
    if args.status and output is None:
        output = DEFAULT_OUTPUT
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.to_json(), encoding="utf-8", newline="\n")
    value = report.as_dict()
    if not report.proof_complete:
        missing = sum(
            int(item.get("missing_template_count", 0))
            for item in value["blockers"]
            if isinstance(item, dict))
        print(
            "BLOCKED: reachable HQT3 join is incomplete; "
            f"missing_templates={missing}; status={report.status}",
            file=sys.stderr)
        return 1
    weighted = value["weighted_display_list"]
    records = value["record_envelope"]
    print(
        "OK (sizing only): "
        f"append_words={weighted['max_cmd_append_expanded_words']}; "
        f"chunks={records['max_chunks']}; status={report.status}; "
        "live/atomic remain disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
