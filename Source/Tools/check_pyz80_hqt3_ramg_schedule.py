#!/usr/bin/env python3
"""Build and validate physical per-scope HQT3/RAM_G measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from pyz80_compiler.hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_CELL_BYTES,
    HQT3_HEADER_BYTES,
    HQT3_RAMG_SCHEDULE_FORMAT,
    HQT3_RAMG_SCHEDULE_STATUS,
    HQT3_RECORD_BYTES,
    HQT3_STATE_BYTES,
    HQT3RAMGScheduleError,
    TSCONF_RAM_BYTES,
    analyze_hqt3_ramg_schedule,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "Build" / "rtype_python_hqt3_ramg_schedule_status.json")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _require_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HQT3RAMGScheduleError(f"{name} is missing")
    return value


def _require_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise HQT3RAMGScheduleError(f"{name} is missing")
    return value


def validate_report(report: dict[str, object]) -> None:
    if report.get("format") != HQT3_RAMG_SCHEDULE_FORMAT:
        raise HQT3RAMGScheduleError("HQT3/RAM_G report format changed")
    if report.get("status") != HQT3_RAMG_SCHEDULE_STATUS:
        raise HQT3RAMGScheduleError("HQT3/RAM_G report status changed")
    if (report.get("scope_pack_proof_complete") is not True or
            report.get("load_schedule_complete") is not False or
            report.get("live") is not False):
        raise HQT3RAMGScheduleError("HQT3/RAM_G proof boundary changed")
    semantic = dict(report)
    actual_hash = semantic.pop("analysis_sha256", None)
    if not isinstance(actual_hash, str) or _sha256_value(semantic) != actual_hash:
        raise HQT3RAMGScheduleError("HQT3/RAM_G analysis hash differs")

    capacities = _require_dict(report.get("capacities"), "capacities")
    if (capacities.get("ft812_ram_g_bytes") != FT812_RAM_G_BYTES or
            capacities.get("tsconf_ram_bytes") != TSCONF_RAM_BYTES or
            capacities.get("storage_domains_are_separate") is not True or
            capacities.get("pack_alignment") != 4):
        raise HQT3RAMGScheduleError("target memory capacities changed")
    width = capacities.get("sprite_cell_width")
    height = capacities.get("sprite_cell_height")
    cell_bytes = capacities.get("sprite_cell_argb4444_bytes")
    if (not isinstance(width, int) or not isinstance(height, int) or
            cell_bytes != width * height * 2):
        raise HQT3RAMGScheduleError("sprite cell byte geometry is invalid")

    census = _require_dict(report.get("scope_pack_census"), "scope census")
    scopes = _require_list(report.get("scope_packs"), "scope packs")
    if census.get("scope_count") != len(scopes) or not scopes:
        raise HQT3RAMGScheduleError("scope pack census differs")
    scope_by_id: dict[str, Mapping[str, object]] = {}
    ramg_nonfit: list[str] = []
    ts_nonfit: list[str] = []
    ts_raw_nonfit: list[str] = []
    index_nonfit: list[str] = []
    pack_ids: set[str] = set()
    for value in scopes:
        scope = _require_dict(value, "scope pack row")
        scope_id = scope.get("scope_id")
        pack_id = scope.get("pixel_pack_id")
        if not isinstance(scope_id, str) or scope_id in scope_by_id:
            raise HQT3RAMGScheduleError("scope identity is missing/duplicated")
        if not isinstance(pack_id, str):
            raise HQT3RAMGScheduleError("scope pixel pack identity is missing")
        scope_by_id[scope_id] = scope
        pack_ids.add(pack_id)
        if (scope.get("resident") is not False or
                scope.get("loadable_scope_only") is not True):
            raise HQT3RAMGScheduleError("an unproved resident scope appeared")
        pixel = _require_dict(scope.get("pixel_pack"), "pixel pack")
        hqt3 = _require_dict(scope.get("hqt3"), "HQT3 layout")
        capacity = _require_dict(scope.get("capacity"), "scope capacity")
        logical = pixel.get("logical_cell_count")
        selected = pixel.get("selected_logical_argb4444_bytes")
        payload = pixel.get("ft812_payload_bytes")
        unique = pixel.get("content_unique_cell_count")
        unique_argb = pixel.get("content_unique_argb4444_bytes")
        if (not all(isinstance(item, int) for item in (
                logical, selected, payload, unique, unique_argb)) or
                logical < 0 or unique < 0 or unique > logical or
                selected != logical * cell_bytes or
                unique_argb != unique * cell_bytes or payload < 0 or
                pixel.get("pixel_roundtrip_complete") is not True):
            raise HQT3RAMGScheduleError(
                f"scope {scope_id} pixel byte arithmetic differs")
        records = hqt3.get("record_count")
        cells = hqt3.get("cell_reference_count")
        states = hqt3.get("state_count")
        total = hqt3.get("total_bytes")
        if (not all(isinstance(item, int) for item in (
                records, cells, states, total)) or
                hqt3.get("record_bytes") != records * HQT3_RECORD_BYTES or
                hqt3.get("cell_bytes") != cells * HQT3_CELL_BYTES or
                hqt3.get("state_bytes") != states * HQT3_STATE_BYTES or
                hqt3.get("header_bytes") != HQT3_HEADER_BYTES or
                total != HQT3_HEADER_BYTES + records * HQT3_RECORD_BYTES +
                cells * HQT3_CELL_BYTES + states * HQT3_STATE_BYTES):
            raise HQT3RAMGScheduleError(
                f"scope {scope_id} HQT3 byte arithmetic differs")
        ramg_fit = payload <= FT812_RAM_G_BYTES
        compiled_bundle = payload + total
        raw_bundle = selected + total
        if (capacity.get("ram_g_payload_bytes") != payload or
                capacity.get("ram_g_isolated_fit") != ramg_fit or
                capacity.get("ram_g_isolated_headroom_bytes") !=
                FT812_RAM_G_BYTES - payload or
                capacity.get("ram_g_gameplay_profile_fit_proved") is not False or
                capacity.get("ts_staging_compiled_payload_plus_hqt3_bytes") !=
                compiled_bundle or
                capacity.get("ts_staging_compiled_isolated_fit") !=
                (compiled_bundle <= TSCONF_RAM_BYTES) or
                capacity.get("ts_staging_raw_argb4444_plus_hqt3_bytes") !=
                raw_bundle or
                capacity.get("ts_staging_raw_argb4444_isolated_fit") !=
                (raw_bundle <= TSCONF_RAM_BYTES) or
                capacity.get("ts_whole_machine_allocation_fit_proved") is not False or
                capacity.get("classification_is_isolated_scope_only") is not True):
            raise HQT3RAMGScheduleError(
                f"scope {scope_id} capacity classification differs")
        if not ramg_fit:
            ramg_nonfit.append(scope_id)
        if compiled_bundle > TSCONF_RAM_BYTES:
            ts_nonfit.append(scope_id)
        if raw_bundle > TSCONF_RAM_BYTES:
            ts_raw_nonfit.append(scope_id)
        if hqt3.get("uint16_record_cell_and_uint8_state_indices_fit") is not True:
            index_nonfit.append(scope_id)
    if census.get("unique_pixel_pack_count") != len(pack_ids):
        raise HQT3RAMGScheduleError("unique pixel pack census differs")
    comparisons = (
        ("ram_g_isolated_nonfit_scope_ids", sorted(ramg_nonfit)),
        ("ts_compiled_isolated_nonfit_scope_ids", sorted(ts_nonfit)),
        ("ts_raw_argb4444_isolated_nonfit_scope_ids", sorted(ts_raw_nonfit)),
        ("hqt3_index_width_nonfit_scope_ids", sorted(index_nonfit)),
    )
    for key, expected in comparisons:
        if census.get(key) != expected:
            raise HQT3RAMGScheduleError(f"scope census {key} differs")
    if (census.get("ram_g_isolated_fit_count") != len(scopes) - len(ramg_nonfit) or
            census.get("ram_g_isolated_nonfit_count") != len(ramg_nonfit) or
            census.get("ts_compiled_isolated_fit_count") != len(scopes) - len(ts_nonfit) or
            census.get("ts_compiled_isolated_nonfit_count") != len(ts_nonfit) or
            census.get("ts_raw_argb4444_isolated_nonfit_count") != len(ts_raw_nonfit) or
            census.get("hqt3_index_width_nonfit_count") != len(index_nonfit)):
        raise HQT3RAMGScheduleError("scope fit counts differ")

    transitions = _require_dict(
        report.get("event_transitions"), "event transitions")
    obligations = _require_list(
        transitions.get("obligations"), "event obligations")
    if transitions.get("event_obligation_count") != len(obligations):
        raise HQT3RAMGScheduleError("event obligation count differs")
    exact = 0
    ambiguous = 0
    event_pack_ids: set[str] = set()
    unmatched_event_pack_ids: set[str] = set()
    unmatched_event_count = 0
    for value in obligations:
        row = _require_dict(value, "event obligation")
        ids = row.get("required_before_dispatch_scope_ids")
        if not isinstance(ids, list) or any(item not in scope_by_id for item in ids):
            raise HQT3RAMGScheduleError("event obligation references unknown scope")
        if (row.get("disappeared_scope_eviction_permitted") is not False or
                row.get("required_scope_union_residency_proved") is not False or
                row.get("same_frame_dispatch_upload_order_proved") is not False or
                row.get("transition_byte_cost") is not None):
            raise HQT3RAMGScheduleError(
                "event obligation invented a residency/eviction schedule")
        is_exact = row.get("to_event_correlation_exact")
        event_pack_id = row.get("to_event_pixel_pack_id")
        pair_sha256 = row.get("to_event_pair_sha256")
        matching = row.get("matching_independent_scope_ids")
        if (not isinstance(is_exact, bool) or
                not isinstance(event_pack_id, str) or
                not isinstance(pair_sha256, str) or len(pair_sha256) != 64 or
                not isinstance(matching, list) or
                any(item not in scope_by_id for item in matching)):
            raise HQT3RAMGScheduleError("event correlation flag is missing")
        matches = bool(matching)
        if row.get("event_pixel_pack_matches_independent_scope") != matches:
            raise HQT3RAMGScheduleError("event pixel pack match flag differs")
        event_pack_ids.add(event_pack_id)
        if not matches:
            unmatched_event_count += 1
            unmatched_event_pack_ids.add(event_pack_id)
        exact += int(is_exact)
        ambiguous += int(not is_exact)
    if (transitions.get("event_correlation_exact_count") != exact or
            transitions.get("event_correlation_ambiguous_count") != ambiguous or
            transitions.get("unique_event_pixel_pack_count") !=
            len(event_pack_ids) or
            transitions.get("event_count_without_independent_scope_pack") !=
            unmatched_event_count or
            transitions.get("unique_event_pixel_packs_without_independent_scope")
            != sorted(unmatched_event_pack_ids) or
            transitions.get("event_scope_eviction_never_inferred_from_next_event")
            is not True or
            transitions.get("common_combination_residency_proved") is not False or
            transitions.get("force_epoch_at_most_one_live") is not True or
            transitions.get("force_epoch_switch_timeline_proved") is not False):
        raise HQT3RAMGScheduleError("event transition proof flags differ")

    if (report.get("resident_combinations") != [] or
            report.get("whole_inventory_resident") is not False or
            report.get("whole_stage_union_resident") is not False):
        raise HQT3RAMGScheduleError("all-resident fiction appeared")
    blockers = _require_list(report.get("blockers"), "blockers")
    codes = {
        item.get("code") for item in blockers if isinstance(item, dict)}
    expected_codes = {"PZRG303", "PZRG304", "PZRG305", "PZRG306", "PZRG308"}
    if ramg_nonfit:
        expected_codes.add("PZRG301")
    if ts_nonfit:
        expected_codes.add("PZRG302")
    if index_nonfit:
        expected_codes.add("PZRG307")
    if codes != expected_codes:
        raise HQT3RAMGScheduleError("HQT3/RAM_G blocker set differs")
    boundaries = _require_dict(
        report.get("proof_boundaries"), "proof boundaries")
    expected_boundaries = {
        "active_inventory_and_source_binding": True,
        "all_scope_lossless_pixel_packs_measured": True,
        "exact_hqt3_record_cell_state_bytes": True,
        "upstream_inventory_fixed_hqt3_layout_matches_physical": True,
        "isolated_ft812_ram_g_fit_classified": True,
        "isolated_4mb_ts_staging_fit_classified_separately": True,
        "event_source_order_obligations_derived": True,
        "ambiguous_event_correlation_resolved": False,
        "cross_event_lifetimes_proved": False,
        "gameplay_ram_g_co_residency_allocated": False,
        "whole_4mb_ts_allocation_proved": False,
        "upload_eviction_display_list_fence_proved": False,
    }
    if boundaries != expected_boundaries:
        raise HQT3RAMGScheduleError("HQT3/RAM_G proof boundaries differ")


def probe(project_root: Path = ROOT) -> dict[str, object]:
    report = analyze_hqt3_ramg_schedule(project_root)
    validate_report(report)
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure active-Python HQT3/RAM_G scope packs")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-live", action="store_true",
        help="fail while lifetime/allocation/upload proofs remain incomplete")
    arguments = parser.parse_args(argv)
    try:
        report = probe(arguments.project_root.resolve())
        _atomic_json(arguments.output.resolve(), report)
    except (HQT3RAMGScheduleError, OSError) as exc:
        parser.error(str(exc))
    census = report["scope_pack_census"]
    assert isinstance(census, dict)
    print(
        "HQT3/RAM_G scopes: "
        f"{census['scope_count']} measured, "
        f"RAM_G fit/non-fit {census['ram_g_isolated_fit_count']}/"
        f"{census['ram_g_isolated_nonfit_count']}, worst "
        f"{census['worst_ram_g_payload_bytes']} bytes; "
        f"status {report['status']}")
    return int(arguments.require_live and report.get("live") is not True)


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["DEFAULT_OUTPUT", "probe", "validate_report"]
