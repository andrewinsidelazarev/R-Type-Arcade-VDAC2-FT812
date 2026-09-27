#!/usr/bin/env python3
"""Build and validate the frame-local HQT3/RAM_G page proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from pyz80_compiler.hqt3_frame_page_solver import (
    DISPLAY_LIST_GENERATIONS,
    EXACT_NONFIT_EVENT_ID,
    EXACT_NONFIT_REQUIREMENT_ID,
    FRAME_RATE_HZ,
    FRAME_RECORD_LIMIT,
    HQT3_FRAME_PAGE_SOLVER_FORMAT,
    HQT3_FRAME_PAGE_SOLVER_STATUS,
    HQT3FramePageSolverError,
    RAMG_OVERSIZED_SCOPE_IDS,
    analyze_hqt3_frame_page_solver,
)
from pyz80_compiler.hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    TSCONF_RAM_BYTES,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "Build" / "rtype_python_hqt3_frame_page_solver_status.json")

EXPECTED_SCOPE_COUNTS = {
    "stage:2:class:Child8D85": 213,
    "stage:2:class:Enemy6F89": 680,
    "stage:2:class:Multipart915BChild": 554,
    "stage:5:class:Formation78F8Child": 1173,
}
EXPECTED_BLOCKERS = {f"PZPAGE{value}" for value in range(501, 509)}
EXPECTED_FACTS = {f"PZPAGE-F0{value}" for value in range(1, 7)}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _value_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HQT3FramePageSolverError(f"{name} is missing")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise HQT3FramePageSolverError(f"{name} is missing")
    return value


def _validate_digest(value: object, name: str) -> None:
    if (not isinstance(value, str) or len(value) != 64 or
            any(character not in "0123456789abcdef" for character in value)):
        raise HQT3FramePageSolverError(f"{name} digest differs")


def _validate_atom(atom: Mapping[str, object], name: str) -> int:
    if (atom.get("semantic_axis") != "exact-bank-plus-rom-descriptor" or
            atom.get("arbitrary_size_cut") is not False or
            atom.get("eviction_inferred") is not False or
            atom.get("hqt3_indices_fit") is not True):
        raise HQT3FramePageSolverError(f"{name} semantic boundary differs")
    integer_fields = (
        "template_index", "bank_key", "descriptor_address", "ram_g_bytes",
        "hqt3_bytes", "hqt3_records", "hqt3_cells", "hqt3_states",
    )
    if any(not isinstance(atom.get(key), int) or int(atom[key]) < 0
           for key in integer_fields):
        raise HQT3FramePageSolverError(f"{name} integer field differs")
    if (int(atom["ram_g_bytes"]) >= FT812_RAM_G_BYTES or
            int(atom["hqt3_records"]) > 0xFFFF or
            int(atom["hqt3_cells"]) > 0xFFFF or
            int(atom["hqt3_states"]) > 256):
        raise HQT3FramePageSolverError(f"{name} physical limit differs")
    _validate_digest(atom.get("pixel_sha256"), f"{name} pixel")
    return int(atom["ram_g_bytes"])


def _validate_summary(
        summary: Mapping[str, object],
        expected_count: int,
        *,
        rows: Sequence[Mapping[str, object]] | None = None,
        ) -> None:
    scope_id = summary.get("scope_id")
    if (summary.get("page_atom_count") != expected_count or
            summary.get("all_atoms_semantic") is not True or
            summary.get("all_atoms_individually_strict_ram_g_fit") is not True or
            summary.get("upper_estimate_is_reachability_tight") is not False or
            summary.get("exact_per_frame_page_set_proved") is not False):
        raise HQT3FramePageSolverError(f"{scope_id} page summary differs")
    count = summary.get("page_reference_upper_bound")
    one = summary.get("one_generation_sum_of_largest_distinct_atoms_bytes")
    two = summary.get("two_generation_sum_without_cross_frame_dedup_bytes")
    if (not isinstance(count, int) or not 0 < count <= FRAME_RECORD_LIMIT or
            not isinstance(one, int) or one <= 0 or
            two != DISPLAY_LIST_GENERATIONS * one):
        raise HQT3FramePageSolverError(f"{scope_id} frame upper estimate differs")
    _validate_digest(
        summary.get("page_atom_domain_sha256"), f"{scope_id} atom domain")
    if rows is not None:
        if len(rows) != expected_count:
            raise HQT3FramePageSolverError(f"{scope_id} atom row count differs")
        sizes = [_validate_atom(row, f"{scope_id} atom") for row in rows]
        if (summary.get("page_atom_domain_sha256") != _value_sha256(list(rows)) or
                summary.get("minimum_atom_bytes") != min(sizes) or
                summary.get("maximum_atom_bytes") != max(sizes)):
            raise HQT3FramePageSolverError(f"{scope_id} atom extrema differ")


def validate_report(report: dict[str, object]) -> None:
    if report.get("format") != HQT3_FRAME_PAGE_SOLVER_FORMAT:
        raise HQT3FramePageSolverError("frame-page format changed")
    if report.get("status") != HQT3_FRAME_PAGE_SOLVER_STATUS:
        raise HQT3FramePageSolverError("frame-page status changed")
    if (report.get("live") is not False or
            report.get("physical_feasibility_decision") !=
            "UNDECIDED_LIFETIME_AND_BANDWIDTH_BLOCKED"):
        raise HQT3FramePageSolverError("frame-page live boundary changed")
    semantic = dict(report)
    stored = semantic.pop("analysis_sha256", None)
    if not isinstance(stored, str) or _value_sha256(semantic) != stored:
        raise HQT3FramePageSolverError("frame-page analysis hash differs")

    bindings = _dict(report.get("input_binding"), "input binding")
    expected_bindings = {
        "inventory", "schedule", "partition", "frame_record_bound",
        "frame_sprite_fragment_envelope", "active_call_graph", "active_rom",
        "page_compiler_modules",
    }
    if set(bindings) != expected_bindings:
        raise HQT3FramePageSolverError("input binding set differs")
    for key in expected_bindings - {"page_compiler_modules"}:
        binding = _dict(bindings[key], f"{key} binding")
        _validate_digest(binding.get("file_sha256", binding.get("sha256")), key)
    modules = _dict(bindings["page_compiler_modules"], "compiler modules")
    if set(modules) != {"hqt3_partition_solver.py", "hqt3_ramg_schedule.py"}:
        raise HQT3FramePageSolverError("page compiler module set differs")
    for name, digest in modules.items():
        _validate_digest(digest, name)

    hardware = _dict(report.get("hardware_contract"), "hardware contract")
    if (hardware.get("frame_rate_hz") != FRAME_RATE_HZ or
            hardware.get("ft812_ram_g_capacity_bytes") != FT812_RAM_G_BYTES or
            hardware.get("ft812_ram_g_strict_max_payload_bytes") !=
            FT812_RAM_G_BYTES - 1 or
            hardware.get("tsconf_ram_capacity_bytes") != TSCONF_RAM_BYTES or
            hardware.get("display_list_generations_retained_for_safe_publication")
            != DISPLAY_LIST_GENERATIONS or
            hardware.get("displayed_page_overwrite_before_retirement_permitted")
            is not False):
        raise HQT3FramePageSolverError("hardware contract differs")

    frame = _dict(report.get("frame_record_contract"), "frame record contract")
    if (frame.get("certified_frame_max_records") != FRAME_RECORD_LIMIT or
            frame.get("object_records") != 206 or
            frame.get("transient_records") != 22 or
            frame.get("record_bound_proof_complete") is not True or
            frame.get("one_record_selects_at_most_one_descriptor_page") is not True or
            frame.get("maximum_distinct_page_references_per_frame") !=
            FRAME_RECORD_LIMIT or
            frame.get("exact_page_identity_sequence_proved") is not False):
        raise HQT3FramePageSolverError("frame record/page boundary differs")

    source = _dict(report.get("source_evidence"), "source evidence")
    witness = _dict(source.get("bcab_rom_witness"), "BCAB ROM witness")
    if (witness.get("event_address") != 0xBCAB or
            witness.get("command") != 0x7404 or
            witness.get("handler") != 0x915B or
            witness.get("parent_sequence") != 0x40C6 or
            witness.get("parent_timer") != 1 or
            witness.get("first_initializer") != 0x9246 or
            witness.get("first_delay_frames") != 10 or
            witness.get("first_child_resource_type") != 0x40 or
            witness.get("first_child_descriptor") != 0x419E or
            witness.get("allocation_success_required") is not True):
        raise HQT3FramePageSolverError("BCAB source/ROM witness differs")
    callables = [_dict(row, "callable witness") for row in
                 _list(source.get("active_callable_witnesses"),
                       "callable witnesses")]
    if (len(callables) != 9 or
            source.get("active_call_graph_exactly_reaches_complete_child_chain")
            is not False or
            not any(row.get("proven_reachable_by_exact_call_edges") is False
                    for row in callables)):
        raise HQT3FramePageSolverError("active call-graph fail-closed fact differs")

    scopes = [_dict(row, "scope page summary") for row in
              _list(report.get("problem_scope_page_catalogs"),
                    "problem page catalogues")]
    if {str(row.get("scope_id")) for row in scopes} != set(EXPECTED_SCOPE_COUNTS):
        raise HQT3FramePageSolverError("problem scope catalogue set differs")
    oversized = set()
    for row in scopes:
        scope_id = str(row["scope_id"])
        _validate_summary(row, EXPECTED_SCOPE_COUNTS[scope_id])
        if row.get("ram_g_oversized_scope") is True:
            oversized.add(scope_id)
        if (row.get("original_scope_ram_g_fit") is not
                (int(row["original_scope_ram_g_bytes"]) < FT812_RAM_G_BYTES)):
            raise HQT3FramePageSolverError(f"{scope_id} original fit differs")
    if oversized != set(RAMG_OVERSIZED_SCOPE_IDS):
        raise HQT3FramePageSolverError("three oversized scope identities differ")

    bcab = _dict(report.get("exact_bcab_page_catalog"), "BCAB page catalogue")
    atoms = [_dict(row, "BCAB page atom") for row in
             _list(bcab.get("page_atoms"), "BCAB page atoms")]
    _validate_summary(bcab, 596, rows=atoms)
    if (bcab.get("scope_id") != EXACT_NONFIT_EVENT_ID or
            bcab.get("requirement_id") != EXACT_NONFIT_REQUIREMENT_ID or
            bcab.get("template_count") != 596 or
            bcab.get("union_ram_g_bytes") != 1263796 or
            bcab.get("union_hqt3_bytes") != 34568 or
            bcab.get("union_compiled_ts_staging_bytes") != 1298364 or
            bcab.get("union_ram_g_overflow_bytes") != 215220 or
            bcab.get("single_union_strict_ram_g_fit") is not False):
        raise HQT3FramePageSolverError("exact BCAB non-fit cost differs")

    lower = _dict(report.get("strict_lower_bounds"), "strict lower bounds")
    if lower.get("catalog_cache_capability_floor_bytes") != 74704:
        raise HQT3FramePageSolverError("catalogue atom capacity floor differs")
    first = _dict(lower.get("bcab_first_child"), "BCAB first-child floor")
    if (first.get("conditional_on_event_and_successful_object_allocation")
            is not True or
            first.get("descriptor_address") != 0x419E or
            first.get("resource_type") != 0x40 or
            first.get("palette_slot_candidates") != list(range(16)) or
            first.get("cold_miss_upload_min_bytes") != 3760 or
            first.get("cold_miss_upload_max_bytes") != 5296 or
            first.get("cold_miss_minimum_average_bytes_per_second_at_55hz") !=
            3760 * FRAME_RATE_HZ or
            first.get("cold_miss_maximum_average_bytes_per_second_at_55hz") !=
            5296 * FRAME_RATE_HZ):
        raise HQT3FramePageSolverError("BCAB cold-miss lower bound differs")

    double = _dict(report.get("double_buffer_capacity"), "double buffer")
    if (double.get("retirement_fence_required_before_overwrite") is not True or
            double.get("event_order_used_as_eviction_proof") is not False or
            double.get("exact_two_generation_union_bytes") is not None or
            double.get("strict_fit_proved") is not False or
            double.get("conservative_upper_estimates_are_not_residency_plans")
            is not True):
        raise HQT3FramePageSolverError("double-buffer fail-closed boundary differs")
    bandwidth = _dict(report.get("upload_bandwidth"), "upload bandwidth")
    if (bandwidth.get("frame_rate_hz") != FRAME_RATE_HZ or
            bandwidth.get("transport_measured_bytes_per_second") is not None or
            bandwidth.get("transport_setup_latency_microseconds") is not None or
            bandwidth.get("transport_available_window_microseconds") is not None or
            bandwidth.get("deadline_proved") is not False):
        raise HQT3FramePageSolverError("upload bandwidth claim differs")

    widths = _dict(report.get("hqt_width_contract"), "HQT width contract")
    if (widths.get("global_template_count") != 10776 or
            widths.get("global_template_id_uint16_fit") is not True or
            widths.get("page_atom_record_count_max") != 1 or
            widths.get("page_atom_cell_count_max") != 64 or
            widths.get("page_atom_state_count_max") != 47 or
            widths.get("all_page_atom_indices_fit") is not True or
            widths.get("frame_record_count_uint8_fit") is not True):
        raise HQT3FramePageSolverError("HQT integer-width contract differs")
    staging = _dict(report.get("tsconf_staging"), "TS staging")
    if (staging.get("bcab_compiled_bundle_bytes") != 1298364 or
            staging.get("bcab_compiled_bundle_isolated_fit") is not True or
            staging.get("all_schedule_scopes_compiled_isolated_fit") is not True or
            staging.get("whole_machine_code_audio_state_and_staging_fit_proved")
            is not False):
        raise HQT3FramePageSolverError("TS staging boundary differs")

    facts = [_dict(row, "missing fact") for row in
             _list(report.get("minimum_missing_facts"), "missing facts")]
    blockers = [_dict(row, "blocker") for row in
                _list(report.get("blockers"), "blockers")]
    if {row.get("fact_id") for row in facts} != EXPECTED_FACTS:
        raise HQT3FramePageSolverError("minimum missing fact set differs")
    if {row.get("code") for row in blockers} != EXPECTED_BLOCKERS:
        raise HQT3FramePageSolverError("frame-page blocker set differs")
    if report.get("resident_combinations") != [] or report.get(
            "eviction_inferences") != []:
        raise HQT3FramePageSolverError("unproved residency/eviction was inferred")
    proof = _dict(report.get("proof_boundaries"), "proof boundaries")
    required_true = {
        "active_python_rom_and_call_graph_bound",
        "three_ram_g_oversized_scopes_identified",
        "exact_bcab_nonfit_union_reproduced_losslessly",
        "descriptor_bank_pages_are_semantic_not_size_cuts",
        "all_measured_page_atoms_individually_fit_ram_g",
        "hqt_page_index_widths_fit",
        "frame_record_upper_bound_228_bound",
        "conditional_bcab_first-child_cold-miss_floor_proved",
    }
    required_false = {
        "exact_per_frame_page_sets_proved",
        "two_generation_ram_g_fit_proved",
        "upload_deadline_proved",
        "pixel_eviction_permitted",
        "active_call_graph_complete_child_chain_proved",
        "whole_tsconf_allocation_proved",
    }
    if (any(proof.get(key) is not True for key in required_true) or
            any(proof.get(key) is not False for key in required_false)):
        raise HQT3FramePageSolverError("proof boundary flags differ")


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate_only:
            value = json.loads(args.output.read_text(encoding="utf-8"))
        else:
            value = analyze_hqt3_frame_page_solver(ROOT)
            _atomic_json(args.output, value)
        if not isinstance(value, dict):
            raise HQT3FramePageSolverError("status is not a JSON object")
        validate_report(value)
    except (OSError, UnicodeError, json.JSONDecodeError,
            HQT3FramePageSolverError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "OK: exact BCAB 596 semantic pages; 1,263,796-byte union remains "
        "215,220 bytes over RAM_G; conditional first-child cold miss is "
        "3,760..5,296 bytes; frame/lifetime/fence/bandwidth proof remains BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
