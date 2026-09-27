#!/usr/bin/env python3
"""Build and validate the source-derived HQT3/RAM_G partition proof."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from pyz80_compiler.hqt3_partition_solver import (
    AMBIGUOUS_FACTS,
    HQT3_PARTITION_SOLVER_FORMAT,
    HQT3_PARTITION_SOLVER_STATUS,
    HQT3PartitionSolverError,
    PROBLEM_SCOPE_IDS,
    analyze_hqt3_partition_solver,
)
from pyz80_compiler.hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_CELL_BYTES,
    HQT3_HEADER_BYTES,
    HQT3_RECORD_BYTES,
    HQT3_STATE_BYTES,
    TSCONF_RAM_BYTES,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "Build" / "rtype_python_hqt3_partition_solver_status.json")

EXPECTED_ORIGINALS = {
    "stage:2:class:Child8D85": (854872, 283, False),
    "stage:2:class:Enemy6F89": (2266568, 283, False),
    "stage:2:class:Multipart915BChild": (1050676, 158, True),
    "stage:5:class:Formation78F8Child": (2339476, 384, False),
}
EXPECTED_HQT_SOLVED = [
    "stage:2:class:Child8D85",
    "stage:2:class:Enemy6F89",
    "stage:5:class:Formation78F8Child",
]


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


def _dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HQT3PartitionSolverError(f"{name} is missing")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise HQT3PartitionSolverError(f"{name} is missing")
    return value


def _validate_hqt3(value: object, name: str) -> tuple[int, int]:
    hqt3 = _dict(value, name)
    records = hqt3.get("record_count")
    cells = hqt3.get("cell_reference_count")
    states = hqt3.get("state_count")
    total = hqt3.get("total_bytes")
    if (not all(isinstance(item, int) for item in
                (records, cells, states, total)) or
            hqt3.get("header_bytes") != HQT3_HEADER_BYTES or
            hqt3.get("record_bytes") != records * HQT3_RECORD_BYTES or
            hqt3.get("cell_bytes") != cells * HQT3_CELL_BYTES or
            hqt3.get("state_bytes") != states * HQT3_STATE_BYTES or
            total != HQT3_HEADER_BYTES + records * HQT3_RECORD_BYTES +
            cells * HQT3_CELL_BYTES + states * HQT3_STATE_BYTES):
        raise HQT3PartitionSolverError(f"{name} byte arithmetic differs")
    encodable = records <= 0xFFFF and cells <= 0xFFFF and states <= 256
    if hqt3.get("uint16_record_cell_and_uint8_state_indices_fit") != encodable:
        raise HQT3PartitionSolverError(f"{name} index-width classification differs")
    return int(total), int(states)


def _validate_cost(value: object, name: str) -> dict[str, int | bool]:
    cost = _dict(value, name)
    pixel = _dict(cost.get("pixel"), f"{name} pixel")
    capacity = _dict(cost.get("capacity"), f"{name} TS capacity")
    targets = _dict(cost.get("partition_targets"), f"{name} targets")
    payload = pixel.get("ft812_payload_bytes")
    if (not isinstance(payload, int) or payload < 0 or
            pixel.get("pixel_roundtrip_complete") is not True):
        raise HQT3PartitionSolverError(f"{name} pixel proof differs")
    hqt_bytes, states = _validate_hqt3(cost.get("hqt3"), f"{name} HQT3")
    compiled = capacity.get("ts_staging_compiled_payload_plus_hqt3_bytes")
    if compiled != payload + hqt_bytes:
        raise HQT3PartitionSolverError(f"{name} compiled staging arithmetic differs")
    hqt = _dict(cost.get("hqt3"), f"{name} HQT3")
    expected = {
        "ram_g_strictly_below_1mib": payload < FT812_RAM_G_BYTES,
        "hqt3_state_count_at_most_256": states <= 256,
        "hqt3_record_and_cell_uint16_fit":
            hqt["uint16_record_cell_and_uint8_state_indices_fit"] is True,
        "compiled_ts_staging_at_most_4mib": compiled <= TSCONF_RAM_BYTES,
    }
    expected["all_targets_pass"] = all(expected.values())
    if targets != expected:
        raise HQT3PartitionSolverError(f"{name} target classification differs")
    return {
        "ram_g_bytes": payload,
        "hqt3_bytes": hqt_bytes,
        "hqt3_state_count": states,
        "compiled_ts_staging_bytes": compiled,
        "all_partition_targets_pass": expected["all_targets_pass"],
    }


def _validate_cost_reference(
        value: object,
        requirement_id: str,
        cost: Mapping[str, object],
        summary: Mapping[str, int | bool],
        name: str,
        ) -> None:
    reference = _dict(value, name)
    expected = {
        "requirement_id": requirement_id,
        "union_cost_sha256": _sha256_value(cost),
        **summary,
    }
    if reference != expected:
        raise HQT3PartitionSolverError(f"{name} is not bound to exact union cost")


def validate_report(report: dict[str, object]) -> None:
    if report.get("format") != HQT3_PARTITION_SOLVER_FORMAT:
        raise HQT3PartitionSolverError("partition solver format changed")
    if report.get("status") != HQT3_PARTITION_SOLVER_STATUS:
        raise HQT3PartitionSolverError("partition solver status changed")
    if (report.get("structural_partition_proof_complete") is not True or
            report.get("ram_g_runtime_paging_complete") is not False or
            report.get("live") is not False):
        raise HQT3PartitionSolverError("partition proof boundary changed")
    semantic = dict(report)
    stored_hash = semantic.pop("analysis_sha256", None)
    if not isinstance(stored_hash, str) or _sha256_value(semantic) != stored_hash:
        raise HQT3PartitionSolverError("partition analysis hash differs")

    binding = _dict(report.get("input_binding"), "input binding")
    for key in (
            "inventory_file_sha256", "inventory_analysis_sha256",
            "schedule_file_sha256", "schedule_analysis_sha256"):
        digest = binding.get(key)
        if not isinstance(digest, str) or len(digest) != 64:
            raise HQT3PartitionSolverError("partition input binding differs")

    evidence = _dict(report.get("source_evidence"), "source evidence")
    expected_facts = {
        "formation_parent_appends_linked_children": True,
        "multipart_parent_appends_linked_children": True,
        "enemy7d68_can_append_multiple_child8d85_instances": True,
        "enemy6f89_has_no_source_proved_singleton_guard": True,
        "world_retains_survivors_across_event_dispatch": True,
    }
    if evidence.get("facts") != expected_facts:
        raise HQT3PartitionSolverError("source-derived lifetime facts differ")
    witnesses = _dict(evidence.get("ast_witnesses"), "AST witnesses")
    if set(witnesses) != {
            "formation_linked_children", "multipart_linked_children",
            "child8d85_multiple_timer_spawns",
            "enemy6f89_direct_unguarded_dispatch",
            "cross_event_survivor_retention"}:
        raise HQT3PartitionSolverError("source AST witness set differs")
    child_witness = _dict(
        witnesses["child8d85_multiple_timer_spawns"], "Child8D85 witness")
    enemy6_witness = _dict(
        witnesses["enemy6f89_direct_unguarded_dispatch"], "Enemy6F89 witness")
    survivor_witness = _dict(
        witnesses["cross_event_survivor_retention"], "survivor witness")
    if (child_witness.get("distinct_timer_values") != [0x80, 0xC0] or
            enemy6_witness.get("singleton_guard_in_handler_branch") is not False or
            survivor_witness.get("live_enemies_retained") is not True):
        raise HQT3PartitionSolverError("source AST lifetime witness differs")

    axes = _list(report.get("allowed_partition_axes"), "allowed axes")
    forbidden = _list(report.get("forbidden_partition_axes"), "forbidden axes")
    if ("exact ROM descriptor" not in axes or
            "arbitrary byte threshold" not in forbidden or
            "next-event-implies-eviction" not in forbidden):
        raise HQT3PartitionSolverError("semantic partition policy differs")

    problems = _list(report.get("problem_scopes"), "problem scopes")
    if report.get("problem_scope_count") != 4 or len(problems) != 4:
        raise HQT3PartitionSolverError("problem scope count differs")
    by_scope: dict[str, Mapping[str, object]] = {}
    for raw in problems:
        scope = _dict(raw, "problem scope")
        scope_id = scope.get("scope_id")
        if not isinstance(scope_id, str) or scope_id in by_scope:
            raise HQT3PartitionSolverError("problem scope identity differs")
        by_scope[scope_id] = scope
        original = _dict(scope.get("original"), f"{scope_id} original")
        expected_bytes, expected_states, expected_fit = EXPECTED_ORIGINALS.get(
            scope_id, (-1, -1, False))
        if original != {
            "ram_g_bytes": expected_bytes,
            "ram_g_strict_fit": expected_bytes < FT812_RAM_G_BYTES,
            "hqt3_state_count": expected_states,
            "hqt3_state_fit": expected_fit,
        }:
            raise HQT3PartitionSolverError(f"{scope_id} original cost differs")

        pages = _list(scope.get("descriptor_pages"), f"{scope_id} pages")
        page_ids: set[str] = set()
        hqt_total = 0
        full_ramg_total = 0
        full_ts_total = 0
        max_states = 0
        for raw_page in pages:
            page = _dict(raw_page, f"{scope_id} page")
            page_id = page.get("partition_id")
            if not isinstance(page_id, str) or page_id in page_ids:
                raise HQT3PartitionSolverError(f"{scope_id} page identity differs")
            page_ids.add(page_id)
            if (page.get("axis") != "exact-bank-plus-rom-descriptor" or
                    page.get("template_atomic") is not True or
                    page.get("arbitrary_size_cut") is not False or
                    page.get("runtime_eviction_permitted") is not False):
                raise HQT3PartitionSolverError(
                    f"{scope_id} contains a non-semantic page")
            full = _validate_cost(
                page.get("full_page_cost"), f"{scope_id}/{page_id} full page")
            shared_bytes, shared_states = _validate_hqt3(
                page.get("shared_pixel_hqt3"),
                f"{scope_id}/{page_id} shared HQT3")
            if full["all_partition_targets_pass"] is not True:
                raise HQT3PartitionSolverError(f"{scope_id} page misses a target")
            full_ramg_total += int(full["ram_g_bytes"])
            full_ts_total += int(full["compiled_ts_staging_bytes"])
            hqt_total += shared_bytes
            max_states = max(max_states, shared_states)

        summary = _dict(
            scope.get("descriptor_page_summary"), f"{scope_id} page summary")
        expected_summary = {
            "partition_count": len(pages),
            "axis": "exact-bank-plus-rom-descriptor",
            "all_templates_atomic": True,
            "arbitrary_size_cut": False,
            "all_full_pages_individually_meet_targets": True,
            "full_pages_ram_g_sum_bytes": full_ramg_total,
            "full_pages_ram_g_simultaneous_fit":
                full_ramg_total < FT812_RAM_G_BYTES,
            "full_pages_compiled_ts_sum_bytes": full_ts_total,
            "shared_pixel_hqt3_total_bytes": hqt_total,
            "shared_pixel_hqt3_max_state_count": max_states,
            "shared_pixel_hqt3_all_state_indices_fit": max_states <= 256,
        }
        if summary != expected_summary:
            raise HQT3PartitionSolverError(f"{scope_id} page summary differs")

        metadata = _dict(
            scope.get("hqt_metadata_sharding"), f"{scope_id} HQT sharding")
        shared_ts = expected_bytes + hqt_total
        if metadata != {
            "semantics_safe": True,
            "all_pages_resident_in_ts": True,
            "shared_pixel_pack_ram_g_bytes": expected_bytes,
            "all_hqt_pages_total_bytes": hqt_total,
            "combined_compiled_ts_staging_bytes": shared_ts,
            "state_overflow_removed": True,
            "requires_python_semantic_change": False,
            "requires_multi_table_target_resolver": True,
        }:
            raise HQT3PartitionSolverError(f"{scope_id} HQT sharding differs")
        accepted = expected_bytes < FT812_RAM_G_BYTES and shared_ts <= TSCONF_RAM_BYTES
        if (scope.get("all_partition_targets_met_without_pixel_eviction") != accepted or
                scope.get("accepted_partition_plan") != (
                    "shared-resident-pixel-pack-plus-all-resident-descriptor-hqt-pages"
                    if accepted else None)):
            raise HQT3PartitionSolverError(f"{scope_id} accepted plan differs")

        paging = _dict(scope.get("full_pixel_paging"), f"{scope_id} paging")
        if (paging.get("each_descriptor_page_meets_targets") is not True or
                paging.get("all_pages_simultaneous_ram_g_bytes") != full_ramg_total or
                paging.get("all_pages_simultaneous_fit") !=
                (full_ramg_total < FT812_RAM_G_BYTES) or
                paging.get("source_exclusivity_proved") is not False or
                paging.get("eviction_permitted") is not False or
                paging.get("semantics_safe_runtime_plan") is not False):
            raise HQT3PartitionSolverError(f"{scope_id} pixel paging proof differs")
    if sorted(by_scope) != sorted(PROBLEM_SCOPE_IDS):
        raise HQT3PartitionSolverError("problem scope set differs")

    requirements = _list(
        report.get("event_union_requirements"), "event union requirements")
    requirement_by_id: dict[str, tuple[Mapping[str, object], dict[str, int | bool]]] = {}
    all_requirement_events: set[str] = set()
    for raw in requirements:
        requirement = _dict(raw, "event union requirement")
        requirement_id = requirement.get("requirement_id")
        if (not isinstance(requirement_id, str) or
                requirement_id in requirement_by_id):
            raise HQT3PartitionSolverError("event requirement identity differs")
        keys_computable = requirement.get("union_keys_computable")
        cost = requirement.get("union_cost")
        if keys_computable is True:
            summary = _validate_cost(cost, requirement_id)
            if requirement.get("union_cost_sha256") != _sha256_value(cost):
                raise HQT3PartitionSolverError("event union cost hash differs")
        elif keys_computable is False and cost is None:
            summary = {}
        else:
            raise HQT3PartitionSolverError("unproved event union has a cost")
        event_ids = requirement.get("event_ids")
        if (not isinstance(event_ids, list) or not event_ids or
                any(not isinstance(item, str) for item in event_ids) or
                all_requirement_events.intersection(event_ids)):
            raise HQT3PartitionSolverError("event requirement membership differs")
        all_requirement_events.update(event_ids)
        requirement_by_id[requirement_id] = (requirement, summary)

    exact = _list(
        report.get("exact_event_partition_obligations"), "exact obligations")
    ambiguous = _list(
        report.get("ambiguous_event_partition_obligations"),
        "ambiguous obligations")
    event_rows: list[Mapping[str, object]] = []
    seen_events: set[str] = set()
    union_events = 0
    union_pack_ids: set[str] = set()
    exact_nonfit_events = 0
    exact_nonfit_requirements: set[str] = set()
    required_fact_ids = [item["fact_id"] for item in AMBIGUOUS_FACTS]
    for semantic_exact, rows in ((True, exact), (False, ambiguous)):
        for raw in rows:
            row = _dict(raw, "event obligation")
            event_id = row.get("event_id")
            requirement_id = row.get("requirement_id")
            if (not isinstance(event_id, str) or event_id in seen_events or
                    not isinstance(requirement_id, str) or
                    requirement_id not in requirement_by_id):
                raise HQT3PartitionSolverError("event obligation identity differs")
            seen_events.add(event_id)
            requirement, summary = requirement_by_id[requirement_id]
            if event_id not in requirement["event_ids"]:
                raise HQT3PartitionSolverError("event requirement reference differs")
            if (row.get("union_keys_computable") is not True or
                    row.get("union_cost_exact_for_listed_keys") is not True or
                    row.get("eviction_permitted") is not False or
                    row.get("prior_event_residency_combination_proved") is not False or
                    row.get("semantic_event_relation_exact") is not semantic_exact):
                raise HQT3PartitionSolverError("event semantic boundary differs")
            reference_name = (
                "semantic_selected_cost" if semantic_exact
                else "conservative_candidate_union_cost")
            _validate_cost_reference(
                row.get(reference_name), requirement_id,
                _dict(requirement["union_cost"], "union cost"), summary,
                f"{event_id} {reference_name}")
            if semantic_exact:
                if (not isinstance(row.get("concrete_partition_obligation"), str) or
                        row.get("single_union_partition_meets_targets") !=
                        summary["all_partition_targets_pass"]):
                    raise HQT3PartitionSolverError("exact event obligation is absent")
                if summary["all_partition_targets_pass"] is not True:
                    exact_nonfit_events += 1
                    exact_nonfit_requirements.add(requirement_id)
            else:
                if (row.get("semantic_selected_cost") is not None or
                        row.get("minimum_required_fact_ids") != required_fact_ids):
                    raise HQT3PartitionSolverError(
                        "ambiguous event did not fail closed")
            if row.get("union_only_pixel_pack") is True:
                union_events += 1
                union_pack_ids.add(str(requirement["pixel_pack_id"]))
            event_rows.append(row)

    census = _dict(report.get("event_cost_census"), "event cost census")
    expected_census = {
        "event_count": len(event_rows),
        "unique_requirement_count": len(requirements),
        "unique_pixel_pack_count": len({
            str(item[0]["pixel_pack_id"]) for item in requirement_by_id.values()}),
        "union_key_computable_event_count": len(event_rows),
        "union_event_count": union_events,
        "union_only_pixel_pack_count": len(union_pack_ids),
        "union_only_pixel_pack_ids": sorted(union_pack_ids),
        "exact_event_count": len(exact),
        "exact_event_nonfit_count": exact_nonfit_events,
        "exact_event_nonfit_requirement_count": len(exact_nonfit_requirements),
        "exact_event_nonfit_requirement_ids": sorted(exact_nonfit_requirements),
        "ambiguous_event_count": len(ambiguous),
    }
    if census != expected_census or len(seen_events) != len(all_requirement_events):
        raise HQT3PartitionSolverError("event cost census differs")
    if (len(event_rows), len(exact), len(ambiguous), union_events,
            len(union_pack_ids), len(requirements)) != (788, 125, 663, 77, 13, 37):
        raise HQT3PartitionSolverError("active event relation census differs")

    facts = report.get("ambiguous_minimum_required_facts")
    if facts != list(AMBIGUOUS_FACTS):
        raise HQT3PartitionSolverError("ambiguous minimum facts differ")
    resolution = _dict(report.get("blocker_resolution"), "blocker resolution")
    ramg = _dict(resolution.get("PZRG301"), "PZRG301 resolution")
    hqt = _dict(resolution.get("PZRG307"), "PZRG307 resolution")
    if (ramg.get("can_eliminate_by_structural_paging_without_python_semantic_change")
            is not False or ramg.get("structurally_solved_scope_ids") != []):
        raise HQT3PartitionSolverError("PZRG301 was eliminated without lifetimes")
    if (hqt.get("can_eliminate_by_structural_hqt_sharding_without_python_semantic_change")
            is not True or hqt.get("structurally_solved_scope_ids") !=
            EXPECTED_HQT_SOLVED or
            hqt.get("target_multi_table_resolver_still_required") is not True):
        raise HQT3PartitionSolverError("PZRG307 structural result differs")
    if report.get("resident_combinations") != [] or report.get("eviction_inferences") != []:
        raise HQT3PartitionSolverError("resident/eviction inference appeared")
    blockers = _list(report.get("blockers"), "blockers")
    if {item.get("code") for item in blockers if isinstance(item, dict)} != {
            "PZPART401", "PZPART402", "PZPART403", "PZPART404",
            "PZPART405", "PZPART406"}:
        raise HQT3PartitionSolverError("partition blocker set differs")
    expected_boundaries = {
        "event_union_keys_and_physical_costs_computed": True,
        "all_125_exact_event_obligations_concrete": True,
        "all_663_ambiguous_events_fail_closed": True,
        "descriptor_pages_are_semantic_not_size_cuts": True,
        "descriptor_page_individual_capacity_proved": True,
        "hqt_state_overflow_structurally_shardable": True,
        "ram_g_page_exclusivity_proved": False,
        "cross_event_last_draw_intervals_proved": False,
        "pixel_eviction_permitted": False,
        "target_multi_hqt_resolver_bound": False,
    }
    if report.get("proof_boundaries") != expected_boundaries:
        raise HQT3PartitionSolverError("partition proof boundaries differ")


def probe(project_root: Path = ROOT) -> dict[str, object]:
    report = analyze_hqt3_partition_solver(project_root)
    validate_report(report)
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove semantic HQT3 sharding and RAM_G paging boundaries")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-live", action="store_true",
        help="fail while RAM_G lifetimes and target resolver remain blocked")
    arguments = parser.parse_args(argv)
    try:
        report = probe(arguments.project_root.resolve())
        _atomic_json(arguments.output.resolve(), report)
    except (HQT3PartitionSolverError, OSError) as exc:
        parser.error(str(exc))
    census = report["event_cost_census"]
    assert isinstance(census, dict)
    print(
        "HQT3 partition solver: "
        f"{report['problem_scope_count']} problem scopes, "
        f"events exact/ambiguous {census['exact_event_count']}/"
        f"{census['ambiguous_event_count']}; status {report['status']}")
    return int(arguments.require_live and report.get("live") is not True)


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["DEFAULT_OUTPUT", "probe", "validate_report"]
