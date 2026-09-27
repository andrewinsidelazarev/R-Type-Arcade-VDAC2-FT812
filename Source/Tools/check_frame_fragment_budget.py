#!/usr/bin/env python3
"""CLI gate for the whole-frame FT812 sprite-fragment budget certificate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pyz80_compiler.frame_fragment_budget import (
    FrameFragmentBudgetError,
    contract_requirements,
    current_budget_status,
    load_contract,
    prove_frame_fragment_budget,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RENDER = ROOT / "Source" / "ASM" / "render.asm"
DEFAULT_CONTRACT = ROOT / "Build" / "rtype_python_frame_budget.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove complete TITLE/GAME RAM_DL and 1209-cycle budgets around "
            "the translated C sprite fragment, bound to the source-derived "
            "active-Python Game.render plan."))
    parser.add_argument("--render", type=Path, default=DEFAULT_RENDER)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--define", action="append", default=[], metavar="SYMBOL",
        help="assembler define enabled for this build (repeatable)")
    parser.add_argument(
        "--requirements", action="store_true",
        help="print the exact translator certificate requirements and exit")
    parser.add_argument(
        "--status", action="store_true",
        help="emit a machine-readable current proof/blocker status and exit")
    parser.add_argument(
        "--output", type=Path,
        help="write --requirements/--status JSON to this file")
    parser.add_argument(
        "--json", action="store_true", help="print a compact JSON proof report")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    render = args.render.resolve()
    try:
        if args.requirements:
            value = contract_requirements(ROOT, render)
            encoded = json.dumps(value, ensure_ascii=False,
                                 indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(encoded, encoding="utf-8")
            else:
                print(encoded, end="")
            return 0
        if args.status:
            value = current_budget_status(
                ROOT, render, args.contract.resolve(), defines=args.define)
            encoded = json.dumps(value, ensure_ascii=False,
                                 indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(encoded, encoding="utf-8")
            else:
                print(encoded, end="")
            return 0
        contract = load_contract(args.contract.resolve())
        report = prove_frame_fragment_budget(
            ROOT, render, contract, defines=args.define)
    except FrameFragmentBudgetError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False,
                         indent=2, sort_keys=True))
    else:
        print(
            "PASS: FT812 frame fragment: "
            f"pre={report.prefix_before_fragment_words}, "
            f"tail+DISPLAY={report.mandatory_tail_words}, "
            f"remaining={report.remaining_dl_words}; "
            f"fragment<={report.fragment_max_expanded_dl_words} expanded/"
            f"{report.fragment_max_physical_command_words} physical words; "
            f"chunks<={report.fragment_max_chunks}x"
            f"{report.fragment_chunk_capacity}; "
            f"GAME={report.game.word_count} words, line "
            f"{report.game.worst_line}={report.game.worst_cycles}/"
            f"{report.safe_line_cycles}; TITLE={report.title.word_count} words, "
            f"line {report.title.worst_line}={report.title.worst_cycles}/"
            f"{report.safe_line_cycles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
