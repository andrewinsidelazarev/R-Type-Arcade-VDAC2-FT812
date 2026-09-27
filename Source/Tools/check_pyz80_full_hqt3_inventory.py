#!/usr/bin/env python3
"""Write and validate the active full HQT3/load-scope inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pyz80_compiler.full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
    FullHQT3InventoryError,
    analyze_full_hqt3_inventory,
)
from pyz80_compiler.sprite_coverage import SpriteCoverageError


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "Build" / "rtype_python_full_hqt3_inventory_status.json"


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def validate_report(report: dict[str, object]) -> None:
    if report.get("format") != FULL_HQT3_INVENTORY_FORMAT:
        raise FullHQT3InventoryError("full HQT3 report format changed")
    if report.get("status") != FULL_HQT3_INVENTORY_STATUS:
        raise FullHQT3InventoryError("full HQT3 report status changed")
    if report.get("inventory_complete") is not True:
        raise FullHQT3InventoryError("full template catalogue is incomplete")
    if report.get("live") is not False:
        raise FullHQT3InventoryError(
            "inventory checker must not claim live integration")
    global_catalog = report.get("global_catalog")
    load_plan = report.get("load_plan")
    bootstrap = report.get("current_bootstrap_hqt3")
    boundaries = report.get("proof_boundaries")
    if not all(isinstance(item, dict) for item in (
            global_catalog, load_plan, bootstrap, boundaries)):
        raise FullHQT3InventoryError("full HQT3 report sections are missing")
    assert isinstance(global_catalog, dict)
    assert isinstance(load_plan, dict)
    assert isinstance(bootstrap, dict)
    assert isinstance(boundaries, dict)
    template_count = global_catalog.get("template_count")
    templates = global_catalog.get("templates")
    if (not isinstance(template_count, int) or template_count <= 0 or
            not isinstance(templates, list) or len(templates) != template_count):
        raise FullHQT3InventoryError("global template count is inconsistent")
    indices = [item.get("template_index") for item in templates
               if isinstance(item, dict)]
    if indices != list(range(template_count)):
        raise FullHQT3InventoryError("global template indices are not dense")
    scopes = load_plan.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise FullHQT3InventoryError("load plan has no scopes")
    covered = {
        index
        for scope in scopes if isinstance(scope, dict)
        for index in scope.get("template_indices", [])
        if isinstance(index, int)
    }
    if covered != set(range(template_count)):
        raise FullHQT3InventoryError(
            "load-scope union does not cover the global catalogue")
    if load_plan.get("resident_combinations") != []:
        raise FullHQT3InventoryError(
            "unproved resident combinations appeared in inventory")
    if (load_plan.get("whole_inventory_resident") is not False or
            load_plan.get("whole_stage_union_resident") is not False):
        raise FullHQT3InventoryError("all-resident fiction appeared in plan")
    current_count = bootstrap.get("record_count")
    if (not isinstance(current_count, int) or current_count <= 0 or
            current_count > template_count):
        raise FullHQT3InventoryError(
            "current preload HQT3 record count is outside the full catalogue")
    if bootstrap.get("full_template_count") != template_count:
        raise FullHQT3InventoryError(
            "bootstrap comparison is not bound to the global catalogue")
    if bootstrap.get("complete_semantic_manifest") is not False:
        raise FullHQT3InventoryError(
            "40-record warm-up cache was mistaken for a semantic manifest")
    expected_boundaries = {
        "complete_template_key_inventory": True,
        "complete_descriptor_decoder_witness": True,
        "complete_asset_bank_resolution_witness": True,
        "exact_template_record_and_cell_byte_counts": True,
        "physical_bitmap_state_table_bound": False,
        "ram_g_residency_bound": False,
        "load_transition_bound": False,
    }
    if boundaries != expected_boundaries:
        raise FullHQT3InventoryError("proof boundary flags changed")
    blockers = report.get("blockers")
    if not isinstance(blockers, list) or {
            item.get("code") for item in blockers if isinstance(item, dict)
            } != {"PZHQT201", "PZHQT202", "PZHQT203", "PZHQT204"}:
        raise FullHQT3InventoryError("full HQT3 blocker set changed")
    crosscheck = report.get("frame_sprite_fragment_envelope_crosscheck")
    if not isinstance(crosscheck, dict):
        raise FullHQT3InventoryError("weighted frame-envelope cross-check missing")
    if (crosscheck.get(
            "missing_current_identities_present_in_full_catalog") is not True or
            crosscheck.get("empty_draw_action_domains_resolved") is not True or
            crosscheck.get(
                "unresolved_empty_draw_action_domain_count") != 0 or
            not isinstance(crosscheck.get(
                "source_proved_nonrendering_witness_count"), int) or
            int(crosscheck[
                "source_proved_nonrendering_witness_count"]) <= 0):
        raise FullHQT3InventoryError(
            "weighted frame-envelope blockers were hidden by the catalogue")


def probe(project_root: Path = ROOT) -> dict[str, object]:
    report = analyze_full_hqt3_inventory(project_root)
    validate_report(report)
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build complete active-Python HQT3 template inventory")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-live", action="store_true",
        help="fail while lifetime/load/physical placement proof is incomplete")
    arguments = parser.parse_args(argv)
    try:
        report = probe(arguments.project_root.resolve())
        _atomic_json(arguments.output.resolve(), report)
    except (FullHQT3InventoryError, SpriteCoverageError, OSError) as exc:
        parser.error(str(exc))
    catalog = report["global_catalog"]
    bootstrap = report["current_bootstrap_hqt3"]
    load_plan = report["load_plan"]
    assert isinstance(catalog, dict)
    assert isinstance(bootstrap, dict)
    assert isinstance(load_plan, dict)
    print(
        "Full HQT3 inventory: "
        f"{catalog['template_count']} templates/"
        f"{catalog['template_cell_reference_count']} template cells, "
        f"{len(load_plan['scopes'])} load scopes; current bootstrap "
        f"{bootstrap['record_count']}/{bootstrap['full_template_count']}; "
        f"status {report['status']}")
    return int(arguments.require_live and report.get("live") is not True)


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["DEFAULT_OUTPUT", "probe", "validate_report"]
