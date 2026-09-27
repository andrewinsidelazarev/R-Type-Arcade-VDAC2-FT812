"""Non-mutating call-graph overlay for source-sealed lambda candidates.

The base active graph is immutable evidence.  This module adds a separate,
candidate-only view over unresolved local-callback sites; it never re-signs a
base call site and never turns a finite candidate set into proven reachability.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .active_call_graph import (
    analyze_active_call_graph,
    validate_active_call_graph_report,
)
from .active_callable_flow import (
    analyze_active_callable_flow,
    validate_active_callable_flow_report,
)
from .lambda_callable_units import (
    analyze_lambda_callable_units,
    validate_lambda_callable_units_report,
)


ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT = (
    "pyz80.active-lambda-graph-extension.v1")
ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS = (
    "ACTIVE_LAMBDA_GRAPH_EXTENSION_INVENTORIED_LIVE_BLOCKED")

__all__ = [
    "ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT",
    "ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS",
    "ActiveLambdaGraphExtensionError",
    "analyze_active_lambda_graph_extension",
    "validate_active_lambda_graph_extension_report",
]


class ActiveLambdaGraphExtensionError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload.pop("semantic_sha256", None)
    return payload


def _candidate_function_id(identity: Mapping[str, Any]) -> str:
    return "lambda-overlay-candidate:" + _json_sha256(identity)


def _base_call_site_index(
        active_graph: Mapping[str, Any],
        ) -> dict[str, Mapping[str, Any]]:
    rows = active_graph["call_graph"]["call_sites"]
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        site_id = str(row["call_site_id"])
        if site_id in result:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO401", f"duplicate base call site: {site_id}")
        result[site_id] = row
    return result


def _base_callable_index(
        active_graph: Mapping[str, Any],
        ) -> dict[str, Mapping[str, Any]]:
    rows = active_graph["callable_inventory"]["callables"]
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        callable_id = str(row["callable_id"])
        if callable_id in result:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO401", f"duplicate base callable: {callable_id}")
        result[callable_id] = row
    return result


def _base_site_matches_flow(
        base: Mapping[str, Any], flow: Mapping[str, Any]) -> bool:
    return (
        str(base.get("caller")) == str(flow.get("caller")) and
        int(base.get("line", -1)) == int(flow["span"]["line"]) and
        int(base.get("column", -1)) == int(flow["span"]["column"]) and
        int(base.get("end_line", -1)) == int(flow["span"]["end_line"]) and
        int(base.get("end_column", -1)) == int(flow["span"]["end_column"]) and
        str(base.get("source")) == str(flow.get("source")) and
        isinstance(base.get("resolution"), Mapping) and
        base["resolution"].get("kind") == "unresolved-local-callable")


def _candidate_inventory(
        active_graph: Mapping[str, Any],
        lambda_units: Mapping[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    base_callables = _base_callable_index(active_graph)
    proven_reachable = set(active_graph["call_graph"][
        "proven_reachable_callable_ids"])
    rows: list[dict[str, Any]] = []

    for unit in lambda_units["lambda_callable_units_in_source_order"]:
        identity = {
            "candidate_kind": "lambda-callable",
            "source_callable_value_id": unit["source_callable_value_id"],
            "lambda_callable_id": unit["lambda_callable_id"],
            "lexical_owner": unit["lexical_owner"],
            "span": unit["span"],
            "ast_sha256": unit["ast_sha256"],
        }
        rows.append({
            "candidate_function_id": _candidate_function_id(identity),
            **identity,
            "base_target_callable_id": None,
            "base_target_present": False,
            "base_target_proven_reachable": False,
            "signature": unit["signature"],
            "closure_obligation": unit["closure"],
            "definition_default_obligation": unit[
                "definition_time_default_evaluation"],
            "body": {
                "span": unit["body"]["span"],
                "ast_sha256": unit["body"]["ast_sha256"],
                "expression_cfg": unit["body"]["expression_cfg"],
                "protocol_operations": unit["body"][
                    "protocol_operations"],
                "return_semantics": unit["return_semantics"],
            },
            "binding_obligation": {
                "mode": "lambda-closure",
                "bind_lexical_owner_environment": True,
                "bind_closure_cell_identities": bool(unit[
                    "closure"]["captured_names"]),
                "evaluate_and_store_defaults_at_definition": bool(unit[
                    "definition_time_default_evaluation"]["entries"]),
            },
            "candidate_only": True,
            "proven": False,
            "graph_reachable": False,
            "runtime_integrated": False,
        })

    for reference in lambda_units[
            "existing_callable_references_in_source_order"]:
        target = str(reference["target_callable_id"])
        if target not in base_callables:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO402", f"bound candidate target absent: {target}")
        target_row = base_callables[target]
        target_cfg = target_row.get("cfg")
        if not isinstance(target_cfg, Mapping):
            raise ActiveLambdaGraphExtensionError(
                "PZLGO402", f"bound candidate target has no CFG: {target}")
        identity = {
            "candidate_kind": "existing-bound-method-reference",
            "source_callable_value_id": reference[
                "source_callable_value_id"],
            "base_target_callable_id": target,
            "lexical_owner": reference["expression_owner"],
            "span": reference["span"],
        }
        rows.append({
            "candidate_function_id": _candidate_function_id(identity),
            **identity,
            "lambda_callable_id": None,
            "ast_sha256": target_row["ast_sha256"],
            "base_target_present": True,
            "base_target_proven_reachable": target in proven_reachable,
            "base_target_cfg_semantic_sha256": target_cfg[
                "semantic_sha256"],
            "signature": reference["signature"],
            "closure_obligation": None,
            "definition_default_obligation": None,
            "body": None,
            "binding_obligation": {
                "mode": "bound-method",
                "receiver_proof": reference["receiver_proof"],
                "preserve_receiver_value_identity": True,
                "bind_first_parameter": reference["signature"][
                    "parameters"][0]["name"],
            },
            "candidate_only": True,
            "proven": False,
            "graph_reachable": False,
            "runtime_integrated": False,
        })

    rows.sort(key=lambda row: (
        str(row["span"]["path"]), int(row["span"]["line"]),
        int(row["span"]["column"]), str(row["candidate_function_id"])))
    rows = [{"numeric_candidate_function_id": index, **row}
            for index, row in enumerate(rows, start=1)]
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = str(row["source_callable_value_id"])
        if source_id in by_source:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO403", f"duplicate candidate source: {source_id}")
        by_source[source_id] = row
    return rows, by_source


def _site_overlay_rows(
        active_graph: Mapping[str, Any],
        callable_flow: Mapping[str, Any],
        candidates: Mapping[str, Mapping[str, Any]],
        ) -> list[dict[str, Any]]:
    base_sites = _base_call_site_index(active_graph)
    reachable = set(active_graph["call_graph"][
        "proven_reachable_callable_ids"])
    rows: list[dict[str, Any]] = []
    finite_index = 0
    for flow in callable_flow["unresolved_local_sites_in_source_order"]:
        site_id = str(flow["call_site_id"])
        base = base_sites.get(site_id)
        if base is None or not _base_site_matches_flow(base, flow):
            raise ActiveLambdaGraphExtensionError(
                "PZLGO404", f"flow/base site mismatch: {site_id}")
        if str(flow["caller"]) not in reachable:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO404", f"overlay site caller is not reachable: {site_id}")
        candidate_rows: list[dict[str, Any]] = []
        for source_id in flow["candidate_callable_value_ids"]:
            candidate = candidates.get(str(source_id))
            if candidate is None:
                raise ActiveLambdaGraphExtensionError(
                    "PZLGO405", f"inventoried candidate is absent: {source_id}")
            candidate_rows.append({
                "numeric_candidate_function_id": candidate[
                    "numeric_candidate_function_id"],
                "candidate_function_id": candidate[
                    "candidate_function_id"],
                "source_callable_value_id": source_id,
                "candidate_kind": candidate["candidate_kind"],
                "proven": False,
                "candidate_only": True,
            })
        complete = bool(flow["incoming_candidates_complete"])
        if complete and not candidate_rows:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO406", f"complete site has no candidate: {site_id}")
        if complete and flow["dynamic_source_ids"]:
            raise ActiveLambdaGraphExtensionError(
                "PZLGO406", f"complete site retains dynamic source: {site_id}")
        if complete:
            finite_index += 1
            kind = "finite-candidate-table"
            table_id = "lambda-overlay-table:" + _json_sha256({
                "base_call_site_id": site_id,
                "candidate_function_ids": [row["candidate_function_id"]
                                           for row in candidate_rows],
            })
        else:
            kind = "incomplete-dynamic-unresolved"
            table_id = None
        rows.append({
            "source_order_index": len(rows),
            "base_call_site_id": site_id,
            "caller": flow["caller"],
            "span": flow["span"],
            "source": flow["source"],
            "callee_name": flow["callee_name"],
            "base_resolution_kind": base["resolution"]["kind"],
            "base_resolution_evidence": base["resolution"]["evidence"],
            "base_graph_call_site_preserved": True,
            "overlay_resolution_kind": kind,
            "numeric_finite_candidate_table_id": (
                finite_index if complete else None),
            "finite_candidate_table_id": table_id,
            "incoming_candidates_complete": complete,
            "candidate_count": len(candidate_rows),
            "candidates": candidate_rows,
            "dynamic_source_ids": list(flow["dynamic_source_ids"]),
            "incompleteness_reasons": list(flow[
                "incompleteness_reasons"]),
            "proven": False,
            "promotion_permitted": False,
            "dispatch_integrated": False,
        })
    return rows


def _build_report(
        active_graph: Mapping[str, Any],
        callable_flow: Mapping[str, Any],
        lambda_units: Mapping[str, Any],
        ) -> dict[str, Any]:
    base_snapshot_sha256 = _json_sha256(active_graph)
    candidate_rows, candidates = _candidate_inventory(
        active_graph, lambda_units)
    site_rows = _site_overlay_rows(active_graph, callable_flow, candidates)
    if _json_sha256(active_graph) != base_snapshot_sha256:
        raise ActiveLambdaGraphExtensionError(
            "PZLGO407", "overlay construction mutated the base graph")

    finite_rows = [row for row in site_rows
                   if row["overlay_resolution_kind"] ==
                   "finite-candidate-table"]
    incomplete_rows = [row for row in site_rows
                       if row["overlay_resolution_kind"] ==
                       "incomplete-dynamic-unresolved"]
    lambda_rows = [row for row in candidate_rows
                   if row["candidate_kind"] == "lambda-callable"]
    bound_rows = [row for row in candidate_rows
                  if row["candidate_kind"] ==
                  "existing-bound-method-reference"]
    blocker_counts: Counter[str] = Counter({
        "PZLGO201": len(lambda_rows),
        "PZLGO202": len(finite_rows),
        "PZLGO203": sum(bool(row["closure_obligation"]["captured_names"])
                         for row in lambda_rows),
        "PZLGO204": sum(bool(row["definition_default_obligation"]["entries"])
                         for row in lambda_rows),
        "PZLGO205": len(bound_rows),
        "PZLGO206": len(incomplete_rows),
        "PZLGO207": sum(bool(row["body"]["protocol_operations"])
                         for row in lambda_rows),
        "PZLGO208": 1,
    })
    blocker_counts = Counter({key: value for key, value in
                              blocker_counts.items() if value})
    details = {
        "PZLGO201": "lambda candidate functions are not proven reachable",
        "PZLGO202": "finite tables are candidate-only dispatch obligations",
        "PZLGO203": "lambda closure cells require runtime binding",
        "PZLGO204": "lambda defaults require definition-time storage",
        "PZLGO205": "bound method candidate requires receiver binding",
        "PZLGO206": "dynamic getattr callback remains incomplete/unresolved",
        "PZLGO207": "lambda body retains Python protocol operations",
        "PZLGO208": "base graph/backend does not consume this overlay",
    }
    candidate_ref_count = sum(row["candidate_count"] for row in site_rows)
    report: dict[str, Any] = {
        "format": ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT,
        "status": ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS,
        "live": False,
        "input_bindings": {
            "active_call_graph_semantic_sha256": active_graph[
                "semantic_sha256"],
            "active_call_graph_content_sha256": base_snapshot_sha256,
            "base_call_graph_semantic_sha256": active_graph[
                "call_graph"]["semantic_sha256"],
            "active_callable_flow_semantic_sha256": callable_flow[
                "semantic_sha256"],
            "lambda_callable_units_semantic_sha256": lambda_units[
                "semantic_sha256"],
        },
        "census": {
            "candidate_function_count": len(candidate_rows),
            "lambda_candidate_function_count": len(lambda_rows),
            "existing_bound_method_candidate_count": len(bound_rows),
            "mapped_base_call_site_count": len(site_rows),
            "finite_candidate_table_site_count": len(finite_rows),
            "incomplete_unresolved_site_count": len(incomplete_rows),
            "candidate_reference_count": candidate_ref_count,
            "unique_candidate_function_reference_count": len({
                item["candidate_function_id"] for row in site_rows
                for item in row["candidates"]}),
            "dynamic_source_reference_count": sum(len(row[
                "dynamic_source_ids"]) for row in site_rows),
            "blocker_counts": dict(sorted(blocker_counts.items())),
        },
        "candidate_functions_in_source_order": candidate_rows,
        "base_call_site_overlay_in_source_order": site_rows,
        "live_blockers": [{
            "code": code, "count": count, "detail": details[code],
        } for code, count in sorted(blocker_counts.items())],
        "proof": {
            "all_three_inputs_validated_in_memory": True,
            "all_nine_flow_sites_map_to_exact_base_call_site_ids": True,
            "complete_flow_sites_have_finite_candidate_tables": True,
            "incomplete_flow_sites_remain_unresolved": True,
            "candidate_sets_never_become_proven_edges": True,
            "lambda_units_never_become_base_graph_callables": True,
            "base_graph_content_sha256_before_after_equal": True,
            "base_graph_mutated_or_resigned": False,
            "overlay_consumed_by_base_graph_or_backend": False,
        },
    }
    normalized = json.loads(_json_bytes(report).decode("utf-8"))
    normalized["semantic_sha256"] = _json_sha256(
        _semantic_payload(normalized))
    return normalized


def analyze_active_lambda_graph_extension(
        project_root: Path | str, *,
        active_graph: Mapping[str, Any] | None = None,
        callable_flow: Mapping[str, Any] | None = None,
        lambda_units: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    """Build a candidate-only overlay over a validated immutable base graph."""
    root = Path(project_root).resolve()
    graph = (analyze_active_call_graph(root)
             if active_graph is None else active_graph)
    validate_active_call_graph_report(root, graph)
    flow = (analyze_active_callable_flow(root, active_graph=graph)
            if callable_flow is None else callable_flow)
    validate_active_callable_flow_report(root, flow, active_graph=graph)
    units = (analyze_lambda_callable_units(
        root, active_graph=graph, callable_flow=flow)
        if lambda_units is None else lambda_units)
    validate_lambda_callable_units_report(
        root, units, active_graph=graph, callable_flow=flow)
    report = _build_report(graph, flow, units)
    validate_active_lambda_graph_extension_report(
        root, report, active_graph=graph, callable_flow=flow,
        lambda_units=units)
    return report


def _validate_seal(report: Mapping[str, Any]) -> None:
    if report.get("format") != ACTIVE_LAMBDA_GRAPH_EXTENSION_FORMAT:
        raise ActiveLambdaGraphExtensionError("PZLGO408", "format mismatch")
    if (report.get("status") != ACTIVE_LAMBDA_GRAPH_EXTENSION_STATUS or
            report.get("live") is not False):
        raise ActiveLambdaGraphExtensionError(
            "PZLGO409", "status/live mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get(
            "semantic_sha256"):
        raise ActiveLambdaGraphExtensionError(
            "PZLGO410", "semantic hash mismatch")
    for row in report.get("candidate_functions_in_source_order", ()):
        if (not isinstance(row, Mapping) or
                row.get("candidate_only") is not True or
                row.get("proven") is not False or
                row.get("graph_reachable") is not False or
                row.get("runtime_integrated") is not False):
            raise ActiveLambdaGraphExtensionError(
                "PZLGO411", "candidate function was promoted")
    for row in report.get("base_call_site_overlay_in_source_order", ()):
        if (not isinstance(row, Mapping) or
                row.get("base_graph_call_site_preserved") is not True or
                row.get("proven") is not False or
                row.get("promotion_permitted") is not False or
                row.get("dispatch_integrated") is not False):
            raise ActiveLambdaGraphExtensionError(
                "PZLGO411", "overlay call site was promoted")
        for candidate in row.get("candidates", ()):
            if (not isinstance(candidate, Mapping) or
                    candidate.get("proven") is not False or
                    candidate.get("candidate_only") is not True):
                raise ActiveLambdaGraphExtensionError(
                    "PZLGO411", "overlay candidate was promoted")


def validate_active_lambda_graph_extension_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        active_graph: Mapping[str, Any],
        callable_flow: Mapping[str, Any],
        lambda_units: Mapping[str, Any],
        ) -> None:
    """Validate inputs, semantic seal and exact overlay re-derivation."""
    root = Path(project_root).resolve()
    # The deepest validator transitively validates the callable-flow and base
    # graph reports as well as re-reading every lambda source/CFG seal.
    validate_lambda_callable_units_report(
        root, lambda_units, active_graph=active_graph,
        callable_flow=callable_flow)
    _validate_seal(report)
    bindings = report.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ActiveLambdaGraphExtensionError(
            "PZLGO412", "input bindings are absent")
    expected_bindings = {
        "active_call_graph_semantic_sha256": active_graph[
            "semantic_sha256"],
        "active_call_graph_content_sha256": _json_sha256(active_graph),
        "base_call_graph_semantic_sha256": active_graph[
            "call_graph"]["semantic_sha256"],
        "active_callable_flow_semantic_sha256": callable_flow[
            "semantic_sha256"],
        "lambda_callable_units_semantic_sha256": lambda_units[
            "semantic_sha256"],
    }
    if dict(bindings) != expected_bindings:
        raise ActiveLambdaGraphExtensionError(
            "PZLGO412", "input semantic/content binding mismatch")
    expected = _build_report(active_graph, callable_flow, lambda_units)
    if _semantic_payload(report) != _semantic_payload(expected):
        raise ActiveLambdaGraphExtensionError(
            "PZLGO413", "lambda graph overlay differs from input proof")
