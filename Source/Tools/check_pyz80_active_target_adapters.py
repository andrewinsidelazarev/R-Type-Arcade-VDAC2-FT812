#!/usr/bin/env python3
"""Generate and validate active Python -> TS-Config adapter obligations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from pyz80_compiler.active_target_adapters import (
    ActiveTargetAdaptersError,
    analyze_active_target_adapters,
    validate_active_target_adapters_report,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "Build" / "rtype_python_active_call_graph_status.json"
DEFAULT_OUTPUT = ROOT / "Build" / "rtype_python_active_target_adapters_status.json"


def probe(project_root: Path | str = ROOT,
          active_call_graph: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report = analyze_active_target_adapters(
        root, active_call_graph or root / "Build" /
        "rtype_python_active_call_graph_status.json")
    validate_report(root, report)
    return report


def validate_report(project_root: Path | str,
                    report: Mapping[str, Any]) -> None:
    validate_active_target_adapters_report(Path(project_root).resolve(), report)


def write_report(report: Mapping[str, Any], output: Path | str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--active-call-graph", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = probe(args.root, args.active_call_graph)
        write_report(report, args.output)
    except (ActiveTargetAdaptersError, OSError, ValueError) as error:
        print(f"active target adapters FAILED: {error}")
        return 1
    inventory = report["inventory"]
    print(
        "active target adapters: "
        f"{inventory['site_count']} boundary/unresolved sites, "
        f"{inventory['exact_callable_semantics_count']} exact semantics, "
        f"{inventory['unresolved_callable_semantics_count']} unresolved, "
        f"{inventory['provider_capability_match_site_count']} narrow capability matches; "
        f"live={report['live']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
