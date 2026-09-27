#!/usr/bin/env python3
"""Generate and validate the active launcher whole-program call/CFG graph."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from pyz80_compiler.active_call_graph import (
    ActiveCallGraphError,
    analyze_active_call_graph,
    validate_active_call_graph_report,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "Build" / "rtype_python_active_call_graph_status.json"


def probe(project_root: Path | str = ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report = analyze_active_call_graph(root)
    validate_report(root, report)
    return report


def validate_report(project_root: Path | str,
                    report: Mapping[str, Any]) -> None:
    validate_active_call_graph_report(Path(project_root).resolve(), report)


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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = probe(args.root)
        write_report(report, args.output)
    except (ActiveCallGraphError, OSError, ValueError) as error:
        print(f"active call graph FAILED: {error}")
        return 1
    graph = report["call_graph"]
    cfg = report["callable_inventory"]
    print(
        "active call graph: "
        f"{cfg['callable_count']} functions, "
        f"{graph['proven_reachable_callable_count']} proven reachable, "
        f"{graph['reachable_unresolved_call_site_count']} reachable unresolved, "
        f"{cfg['unsupported_lowering_blocker_count']} CFG blockers; "
        f"live={report['live']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
