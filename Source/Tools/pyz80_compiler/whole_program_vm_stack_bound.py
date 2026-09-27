"""Fail-closed stack and caller-owned arena proof for the compact PZVT VM.

The proof deliberately keeps two different memories separate:

* the Z80 hardware call stack used by compiled C, reader/adapter callbacks and
  an interrupt which may pre-empt them;
* the caller-owned PZVT arena containing iterative VM frames, locals,
  suspended generators and argument scratch.

Only the second memory has a source-level size formula.  A finite source call
depth is reported only when the validated active call graph is acyclic and
has no reachable unresolved or finite-dynamic dispatch site.  Otherwise the
longest path through the *proven* subgraph is retained as a useful lower bound
and an explicit blocker is emitted.  No recursion, dynamic target depth or
generator-lifetime maximum is guessed.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

from .whole_program_vm_backend import (
    WholeProgramVMArtifact,
    WholeProgramVMError,
    decode_compact_target_vm,
    decode_whole_program_vm,
)


WHOLE_PROGRAM_VM_STACK_BOUND_FORMAT = (
    "pyz80.whole-program-vm-stack-bound.v1")
RUNTIME_SOURCE_PATHS = (
    "Source/C/python_vm/pyz80_whole_program_vm.h",
    "Source/C/python_vm/pyz80_whole_program_vm.c",
)
_UINT8_LIMIT = 0xFF
_UINT16_LIMIT = 0xFFFF
_LOCAL_ID_LIMIT = 0x7FFF


class WholeProgramVMStackBoundError(ValueError):
    """A malformed input or an invalid/tampered stack certificate."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical(value))


def _require_dict(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WholeProgramVMStackBoundError(
            "PZVSB001", f"{where} is not an object")
    return value


def _require_list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise WholeProgramVMStackBoundError(
            "PZVSB002", f"{where} is not a list")
    return value


def _require_string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise WholeProgramVMStackBoundError(
            "PZVSB003", f"{where} is not a non-empty string")
    return value


def _validate_semantic(value: Mapping[str, Any], where: str,
                       *, excluded: Sequence[str] = ("semantic_sha256",)
                       ) -> str:
    expected = value.get("semantic_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise WholeProgramVMStackBoundError(
            "PZVSB004", f"{where} has no semantic_sha256")
    payload = {key: item for key, item in value.items()
               if key not in excluded}
    actual = _sha256_json(payload)
    if actual != expected:
        raise WholeProgramVMStackBoundError(
            "PZVSB005",
            f"{where} semantic mismatch: {expected} != {actual}")
    return expected


@dataclasses.dataclass(frozen=True)
class _GraphProof:
    semantic_sha256: str
    call_graph_semantic_sha256: str
    reachable: tuple[str, ...]
    entrypoint: str
    edges: tuple[tuple[str, str, str], ...]
    unresolved_site_ids: tuple[str, ...]
    finite_dynamic_site_ids: tuple[str, ...]
    host_boundary_site_ids: tuple[str, ...]
    rows_by_id: Mapping[str, dict[str, Any]]


def _validated_graph(active_call_graph: Mapping[str, Any]) -> _GraphProof:
    raw_graph = _require_dict(dict(active_call_graph), "active call graph")
    try:
        graph = json.loads(_canonical(raw_graph).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WholeProgramVMStackBoundError(
            "PZVSB001",
            f"active call graph is not JSON representable: {exc}") from exc
    graph_semantic = _validate_semantic(
        graph, "active call graph",
        excluded=("semantic_sha256", "status", "live", "live_blockers"))
    call_graph = _require_dict(graph.get("call_graph"), "call_graph")
    call_graph_semantic = _validate_semantic(call_graph, "call_graph")
    reachable = tuple(_require_string(item, "reachable callable") for item in
                      _require_list(call_graph.get(
                          "proven_reachable_callable_ids"),
                          "proven_reachable_callable_ids"))
    if not reachable or len(set(reachable)) != len(reachable):
        raise WholeProgramVMStackBoundError(
            "PZVSB006", "reachable callable order is empty or duplicated")
    if call_graph.get("proven_reachable_callable_count") != len(reachable):
        raise WholeProgramVMStackBoundError(
            "PZVSB038",
            "proven_reachable_callable_count differs from callable IDs")
    reachable_set = set(reachable)
    entry_raw = call_graph.get("entrypoint")
    if not isinstance(entry_raw, str):
        top_entry = graph.get("entrypoint")
        entry_raw = (top_entry.get("callable_id")
                     if isinstance(top_entry, dict) else None)
    entrypoint = _require_string(entry_raw, "call graph entrypoint")
    if entrypoint not in reachable_set:
        raise WholeProgramVMStackBoundError(
            "PZVSB007", "entrypoint is not proven reachable")

    raw_edges = _require_list(
        call_graph.get("exact_internal_edges", []), "exact_internal_edges")
    edges: list[tuple[str, str, str]] = []
    for index, raw in enumerate(raw_edges):
        edge = _require_dict(raw, f"exact_internal_edges[{index}]")
        caller = _require_string(edge.get("caller"), "edge caller")
        callee = _require_string(edge.get("callee"), "edge callee")
        site = _require_string(edge.get("call_site_id"), "edge call_site_id")
        if caller in reachable_set:
            if callee not in reachable_set:
                raise WholeProgramVMStackBoundError(
                    "PZVSB008",
                    f"reachable edge leaves proven closure: {caller} -> {callee}")
            edges.append((caller, callee, site))
    declared_edge_count = call_graph.get("exact_internal_edge_count")
    if (not isinstance(declared_edge_count, int) or
            declared_edge_count != len(raw_edges)):
        raise WholeProgramVMStackBoundError(
            "PZVSB009", "exact_internal_edge_count differs from edge rows")

    def site_ids(key: str, count_key: str) -> tuple[str, ...]:
        raw = call_graph.get(key, [])
        values = tuple(_require_string(item, key)
                       for item in _require_list(raw, key))
        if len(set(values)) != len(values):
            raise WholeProgramVMStackBoundError(
                "PZVSB010", f"{key} contains duplicates")
        count = call_graph.get(count_key)
        if not isinstance(count, int) or count != len(values):
            raise WholeProgramVMStackBoundError(
                "PZVSB011", f"{count_key} differs from {key}")
        return values

    unresolved = site_ids(
        "reachable_unresolved_call_site_ids",
        "reachable_unresolved_call_site_count")
    finite_dynamic = site_ids(
        "reachable_finite_dynamic_dispatch_site_ids",
        "reachable_finite_dynamic_dispatch_site_count")
    host = site_ids(
        "reachable_host_boundary_call_site_ids",
        "reachable_host_boundary_call_site_count")

    inventory = _require_dict(
        graph.get("callable_inventory"), "callable_inventory")
    rows: dict[str, dict[str, Any]] = {}
    for raw in _require_list(inventory.get("callables"), "callables"):
        row = _require_dict(raw, "callable row")
        identifier = _require_string(row.get("callable_id"), "callable_id")
        if identifier in rows:
            raise WholeProgramVMStackBoundError(
                "PZVSB012", f"duplicate callable row {identifier}")
        rows[identifier] = row
    missing = [identifier for identifier in reachable if identifier not in rows]
    if missing:
        raise WholeProgramVMStackBoundError(
            "PZVSB013", f"reachable callable rows absent: {missing[:4]}")
    return _GraphProof(
        semantic_sha256=graph_semantic,
        call_graph_semantic_sha256=call_graph_semantic,
        reachable=reachable, entrypoint=entrypoint, edges=tuple(edges),
        unresolved_site_ids=unresolved,
        finite_dynamic_site_ids=finite_dynamic,
        host_boundary_site_ids=host,
        rows_by_id=rows)


def _validated_artifact(artifact: WholeProgramVMArtifact,
                        graph: _GraphProof) -> tuple[dict[str, Any],
                                                     dict[str, Any]]:
    if not isinstance(artifact, WholeProgramVMArtifact):
        raise WholeProgramVMStackBoundError(
            "PZVSB014", "artifact is not WholeProgramVMArtifact")
    document = _require_dict(artifact.document, "artifact.document")
    actual_semantic = _sha256_json(document)
    if actual_semantic != artifact.semantic_sha256:
        raise WholeProgramVMStackBoundError(
            "PZVSB015", "artifact document semantic hash mismatch")
    if _sha256_bytes(artifact.proof_bytecode) != artifact.proof_bytecode_sha256:
        raise WholeProgramVMStackBoundError(
            "PZVSB016", "artifact proof bytecode hash mismatch")
    if _sha256_bytes(artifact.target_bytecode) != artifact.target_bytecode_sha256:
        raise WholeProgramVMStackBoundError(
            "PZVSB017", "artifact target bytecode hash mismatch")
    if document.get("active_call_graph_semantic_sha256") != graph.semantic_sha256:
        raise WholeProgramVMStackBoundError(
            "PZVSB018", "artifact is not bound to this active call graph")
    if tuple(document.get("proven_reachable_callable_ids", ())) != graph.reachable:
        raise WholeProgramVMStackBoundError(
            "PZVSB019", "artifact callable order differs from call graph")
    try:
        decoded_proof = decode_whole_program_vm(artifact.proof_bytecode)
        decoded_target = decode_compact_target_vm(artifact.target_bytecode)
    except WholeProgramVMError as exc:
        raise WholeProgramVMStackBoundError(
            "PZVSB020", f"artifact bytecode validation failed: {exc}") from exc
    if decoded_proof != document:
        raise WholeProgramVMStackBoundError(
            "PZVSB021", "proof bytecode differs from artifact document")
    if decoded_target != artifact.compact_document:
        raise WholeProgramVMStackBoundError(
            "PZVSB022", "target bytecode differs from compact document")
    if decoded_target.get(
            "proof_document_semantic_sha256") != artifact.semantic_sha256:
        raise WholeProgramVMStackBoundError(
            "PZVSB023", "compact target proof binding mismatch")
    guarded_ids = tuple(document.get("guarded_callable_ids", ()))
    document_ids = tuple(
        str(row.get("callable_id")) for row in document.get("functions", ())
        if isinstance(row, dict))
    expected_ids = (*graph.reachable, *guarded_ids, *document.get("definition_callable_ids", ()))
    _, expected_units = _unit_labels(document)
    if (document_ids != expected_ids or
            tuple(decoded_target.get("functions", ())) != expected_units):
        raise WholeProgramVMStackBoundError(
            "PZVSB024",
            "compact function table differs from proved/guarded/definition contract")
    return document, decoded_target


@dataclasses.dataclass(frozen=True)
class _SCCProof:
    components: tuple[tuple[str, ...], ...]
    recursive: tuple[tuple[str, ...], ...]
    adjacency: Mapping[str, tuple[str, ...]]


def _scc(vertices: Sequence[str], edges: Sequence[tuple[str, str]]) -> _SCCProof:
    order = {name: index for index, name in enumerate(vertices)}
    adjacency_sets = {name: set() for name in vertices}
    for caller, callee in edges:
        adjacency_sets[caller].add(callee)
    adjacency = {
        name: tuple(sorted(targets, key=order.__getitem__))
        for name, targets in adjacency_sets.items()
    }
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(vertex: str) -> None:
        nonlocal index
        indices[vertex] = index
        low[vertex] = index
        index += 1
        stack.append(vertex)
        on_stack.add(vertex)
        for target in adjacency[vertex]:
            if target not in indices:
                visit(target)
                low[vertex] = min(low[vertex], low[target])
            elif target in on_stack:
                low[vertex] = min(low[vertex], indices[target])
        if low[vertex] == indices[vertex]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == vertex:
                    break
            components.append(tuple(sorted(component, key=order.__getitem__)))

    for vertex in vertices:
        if vertex not in indices:
            visit(vertex)
    components.sort(key=lambda item: min(order[name] for name in item))
    recursive = tuple(component for component in components if
                      len(component) > 1 or component[0] in
                      adjacency_sets[component[0]])
    return _SCCProof(tuple(components), recursive, adjacency)


def _longest_dag_path(vertices: Sequence[str], adjacency: Mapping[str,
                                                                  Sequence[str]],
                      roots: Sequence[str],
                      weights: Mapping[str, int] | None = None
                      ) -> tuple[int, tuple[str, ...]]:
    weight = {name: 1 for name in vertices}
    if weights is not None:
        weight.update(weights)
    visiting: set[str] = set()
    memo: dict[str, tuple[int, tuple[str, ...]]] = {}

    def solve(vertex: str) -> tuple[int, tuple[str, ...]]:
        if vertex in memo:
            return memo[vertex]
        if vertex in visiting:
            raise WholeProgramVMStackBoundError(
                "PZVSB025", "longest-path request contains recursion")
        visiting.add(vertex)
        suffixes = [solve(target) for target in adjacency[vertex]]
        visiting.remove(vertex)
        if suffixes:
            best = max(suffixes, key=lambda item: (item[0], item[1]))
            result = (weight[vertex] + best[0], (vertex,) + best[1])
        else:
            result = (weight[vertex], (vertex,))
        memo[vertex] = result
        return result

    candidates = [solve(root) for root in roots]
    return max(candidates, key=lambda item: (item[0], item[1]))


def _condensation_depth(vertices: Sequence[str], proof: _SCCProof,
                        entrypoint: str) -> tuple[int, tuple[tuple[str, ...], ...]]:
    component_by_vertex = {
        vertex: index for index, component in enumerate(proof.components)
        for vertex in component}
    names = tuple(f"scc:{index}" for index in range(len(proof.components)))
    edges = {
        (names[component_by_vertex[caller]],
         names[component_by_vertex[callee]])
        for caller in vertices for callee in proof.adjacency[caller]
        if component_by_vertex[caller] != component_by_vertex[callee]
    }
    adjacency = {name: [] for name in names}
    for caller, callee in sorted(edges):
        adjacency[caller].append(callee)
    start = names[component_by_vertex[entrypoint]]
    depth, path = _longest_dag_path(names, adjacency, (start,))
    return depth, tuple(proof.components[int(name.split(":", 1)[1])]
                        for name in path)


def _source_call_proof(graph: _GraphProof) -> dict[str, Any]:
    unique_edges = tuple(sorted(
        {(caller, callee) for caller, callee, _ in graph.edges},
        key=lambda edge: (graph.reachable.index(edge[0]),
                          graph.reachable.index(edge[1]))))
    proof = _scc(graph.reachable, unique_edges)
    recursive_rows = [{
        "callable_ids": list(component),
        "semantic_sha256": _sha256_json(list(component)),
    } for component in proof.recursive]
    condensation_depth, condensation_path = _condensation_depth(
        graph.reachable, proof, graph.entrypoint)
    if proof.recursive:
        depth: int | None = None
        path: tuple[str, ...] = ()
    else:
        depth, path = _longest_dag_path(
            graph.reachable, proof.adjacency, (graph.entrypoint,))
    return {
        "reachable_callable_count": len(graph.reachable),
        "reachable_exact_edge_row_count": len(graph.edges),
        "reachable_unique_proven_edge_count": len(unique_edges),
        "scc_count": len(proof.components),
        "recursive_scc_count": len(proof.recursive),
        "recursive_sccs": recursive_rows,
        "proven_entry_longest_path_depth": depth,
        "proven_entry_longest_path_callable_ids": list(path),
        "proven_entry_condensation_depth_lower_bound": condensation_depth,
        "proven_entry_condensation_path": [list(item)
                                            for item in condensation_path],
        "reachable_unresolved_call_site_count": len(
            graph.unresolved_site_ids),
        "reachable_finite_dynamic_dispatch_site_count": len(
            graph.finite_dynamic_site_ids),
        "reachable_host_boundary_call_site_count": len(
            graph.host_boundary_site_ids),
        "finite_whole_program_call_depth_proved": bool(
            not proof.recursive and
            not graph.unresolved_site_ids and
            not graph.finite_dynamic_site_ids),
        "analysis_scope": (
            "only exact_internal_edges; unresolved and finite-dynamic sites "
            "are never promoted to proven edges"),
        "_adjacency": proof.adjacency,
    }


def _unit_labels(document: Mapping[str, Any]) -> tuple[
        tuple[dict[str, Any], ...], tuple[int, ...]]:
    from .whole_program_vm_backend import _unit_specs
    from .lambda_lowering import materialize_lambda_definitions
    functions, units = _unit_specs(copy.deepcopy(dict(document)))
    # Regenerate definitions from the authenticated proof, never from supplied
    # target labels or an unproved reachability extension.
    materialize_lambda_definitions(functions, units)
    from .comprehension_lowering import materialize_list_comprehensions
    materialize_list_comprehensions(functions, units)
    return tuple({"kind": "function" if unit["kind"] == 1 else "expression",
                  "owner": functions[unit["owner"]]["callable_id"],
                  "name": unit["name"], "function_index": unit["owner"]}
                 for unit in units), tuple(row["unit"] for row in functions)


def _compact_core_proof(document: Mapping[str, Any], compact: Mapping[str, Any],
                        entrypoint: str, *,
                        compact_unit_labels: Sequence[Mapping[str, Any]] | None = None,
                        ) -> dict[str, Any]:
    units = _require_list(compact.get("units"), "compact units")
    functions = _require_list(compact.get("functions"), "compact functions")
    labels, expected_function_units = _unit_labels(document)
    if compact_unit_labels is not None:
        supplied = tuple(copy.deepcopy(dict(item))
                         for item in compact_unit_labels)
        if supplied[:len(labels)] != labels:
            raise WholeProgramVMStackBoundError(
                "PZVSB026", "compact unit label prefix differs from proof units")
        labels = supplied
    if len(labels) != len(units):
        raise WholeProgramVMStackBoundError(
            "PZVSB026", "compact unit table differs from proof units")
    if tuple(functions) != expected_function_units:
        raise WholeProgramVMStackBoundError(
            "PZVSB027", "compact function-to-unit table differs from proof")
    names = tuple(f"u{index}:{label['name']}" for index, label in enumerate(labels))
    edges: set[tuple[str, str]] = set()
    max_arguments = 0
    dynamic_closure_calls = 0
    ssa_local_counts: dict[str, int] = {}
    frame_slot_counts: dict[str, int] = {}
    for unit_index, raw_unit in enumerate(units):
        unit = _require_dict(raw_unit, f"compact unit {unit_index}")
        local_count = unit.get("local_count")
        if (not isinstance(local_count, int) or
                not 0 <= local_count <= _LOCAL_ID_LIMIT):
            raise WholeProgramVMStackBoundError(
                "PZVSB028",
                f"unit {unit_index} local_count exceeds the 15-bit local ID")
        frame_slot_count = unit.get("frame_slot_count")
        if (not isinstance(frame_slot_count, int) or
                not 0 <= frame_slot_count <= _UINT16_LIMIT):
            raise WholeProgramVMStackBoundError(
                "PZVSB036",
                f"unit {unit_index} frame_slot_count is not uint16")
        if frame_slot_count < local_count:
            raise WholeProgramVMStackBoundError(
                "PZVSB037",
                f"unit {unit_index} frame_slot_count is below local_count")
        ssa_local_counts[names[unit_index]] = local_count
        frame_slot_counts[names[unit_index]] = frame_slot_count
        for raw_block in _require_list(unit.get("blocks"), "compact blocks"):
            block = _require_dict(raw_block, "compact block")
            for raw_item in _require_list(
                    block.get("instructions"), "compact instructions"):
                item = _require_dict(raw_item, "compact instruction")
                if item.get("opcode") in (13, 15):
                    dynamic_closure_calls += 1
                arguments = item.get("arguments", [])
                if isinstance(arguments, list):
                    # Constructor arguments in PZVT exclude the synthesized
                    # allocated ``self`` value which occupies scratch slot 0.
                    argument_count = len(arguments) + (
                        1 if "allocation_adapter_id" in item else 0)
                    max_arguments = max(max_arguments, argument_count)
                if "function" in item:
                    target = item["function"]
                    if not isinstance(target, int) or not 0 <= target < len(functions):
                        raise WholeProgramVMStackBoundError(
                            "PZVSB029", "compact call target is invalid")
                    edges.add((names[unit_index], names[functions[target]]))
                if item.get("post_init_function_plus_one"):
                    target = item["post_init_function_plus_one"] - 1
                    if not isinstance(target, int) or not 0 <= target < len(functions):
                        raise WholeProgramVMStackBoundError(
                            "PZVSB029", "dataclass post-init target is invalid")
                    edges.add((names[unit_index], names[functions[target]]))
                candidates = item.get("candidates")
                if candidates is not None:
                    if not isinstance(candidates, list) or not candidates:
                        raise WholeProgramVMStackBoundError(
                            "PZVSB038", "guarded dispatch candidates are malformed")
                    for raw_candidate in candidates:
                        candidate = _require_dict(
                            raw_candidate, "guarded dispatch candidate")
                        target = candidate.get("function")
                        candidate_arguments = candidate.get("arguments")
                        if (not isinstance(target, int) or
                                not 0 <= target < len(functions) or
                                not isinstance(candidate_arguments, list)):
                            raise WholeProgramVMStackBoundError(
                                "PZVSB038", "guarded dispatch candidate is invalid")
                        lexical_owner = candidate.get(
                            "lexical_owner_function")
                        target_unit_index = functions[target]
                        target_unit = _require_dict(
                            units[target_unit_index],
                            "guarded dispatch target unit")
                        if ((lexical_owner is not None and (
                                not isinstance(lexical_owner, int) or
                                not 0 <= lexical_owner < len(functions))) or
                                bool(target_unit.get("lexical_parent_mode")) !=
                                (lexical_owner is not None)):
                            raise WholeProgramVMStackBoundError(
                                "PZVSB038",
                                "guarded lexical owner/unit contract differs")
                        edges.add((names[unit_index], names[functions[target]]))
                        max_arguments = max(
                            max_arguments, len(candidate_arguments) + (
                                1 if candidate.get(
                                    "runtime_bound_receiver_required") is True
                                else 0))
                if "unit" in item:
                    target = item["unit"]
                    if not isinstance(target, int) or not 0 <= target < len(units):
                        raise WholeProgramVMStackBoundError(
                            "PZVSB030", "compact expression target is invalid")
                    edges.add((names[unit_index], names[target]))
            term = _require_dict(block.get("terminator"), "compact terminator")
            arguments = term.get("arguments", [])
            if isinstance(arguments, list):
                max_arguments = max(max_arguments, len(arguments))
    max_arguments = max(1, max_arguments)
    if max_arguments > _UINT8_LIMIT:
        raise WholeProgramVMStackBoundError(
            "PZVSB031", "compact max argument count exceeds uint8")
    proof = _scc(names, tuple(edges))
    reachable_ids = tuple(document["proven_reachable_callable_ids"])
    all_function_ids = tuple(labels[index]["owner"] for index in functions)
    try:
        entry_function = reachable_ids.index(entrypoint)
    except ValueError as exc:
        raise WholeProgramVMStackBoundError(
            "PZVSB032", "compact entrypoint is absent") from exc
    entry_unit = names[functions[entry_function]]
    function_frame_slot_counts = {
        all_function_ids[index]: frame_slot_counts[names[unit_index]]
        for index, unit_index in enumerate(functions)}
    if proof.recursive or dynamic_closure_calls:
        entry_depth = None
        entry_path: tuple[str, ...] = ()
        weighted_slots = None
    else:
        entry_depth, entry_path = _longest_dag_path(
            names, proof.adjacency, (entry_unit,))
        weighted_slots, _ = _longest_dag_path(
            names, proof.adjacency, (entry_unit,), frame_slot_counts)
    return {
        "function_count": len(functions),
        "proven_reachable_function_count": len(reachable_ids),
        "guarded_callable_function_count": len(document.get("guarded_callable_ids", ())),
        "definition_only_function_count": len(all_function_ids) - len(reachable_ids) - len(document.get("guarded_callable_ids", ())),
        "unit_count": len(units),
        "core_push_edge_count": len(edges),
        "dynamic_closure_call_count": dynamic_closure_calls,
        "recursive_scc_count": len(proof.recursive),
        "recursive_sccs": [list(item) for item in proof.recursive],
        "entry_exact_core_call_depth": entry_depth,
        "entry_exact_core_path": list(entry_path),
        "max_ssa_local_count": max(ssa_local_counts.values(), default=0),
        "max_frame_slot_count": max(frame_slot_counts.values(), default=0),
        "max_argument_count": max_arguments,
        "entry_path_weighted_frame_slots": weighted_slots,
        "uniform_locals_per_frame": True,
        "unit_ssa_local_counts_semantic_sha256": _sha256_json(
            ssa_local_counts),
        "unit_frame_slot_counts_semantic_sha256": _sha256_json(
            frame_slot_counts),
        "finite_core_call_depth_proved": not proof.recursive and not dynamic_closure_calls,
        "_unit_labels": [dict(item) for item in labels],
        "_ssa_local_counts": ssa_local_counts,
        "_frame_slot_counts": frame_slot_counts,
        "_function_frame_slot_counts": function_frame_slot_counts,
    }


def _generator_proof(graph: _GraphProof) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for identifier in graph.reachable:
        cfg = graph.rows_by_id[identifier].get("cfg")
        if not isinstance(cfg, dict):
            continue
        signature = cfg.get("signature")
        signature = signature if isinstance(signature, dict) else {}
        blocks = cfg.get("blocks")
        blocks = blocks if isinstance(blocks, list) else []
        suspension_terms = [
            block.get("terminator", {}).get("op")
            for block in blocks if isinstance(block, dict) and
            isinstance(block.get("terminator"), dict) and
            "yield" in str(block["terminator"].get("op", ""))]
        is_generator = (signature.get("execution_kind") == "generator-frame" or
                        bool(suspension_terms))
        if not is_generator:
            continue
        frame = signature.get("frame")
        frame = frame if isinstance(frame, dict) else {}
        bounded_slots = frame.get("bounded_slot_count")
        bounded = bool(frame.get("bounded_by_source_ast")) and isinstance(
            bounded_slots, int) and bounded_slots >= 0
        rows.append({
            "callable_id": identifier,
            "source_suspension_count": signature.get(
                "source_suspension_count", len(suspension_terms)),
            "lowered_suspension_state_count": signature.get(
                "lowered_suspension_state_count", len(suspension_terms)),
            "bounded_frame_slots": bounded_slots if bounded else None,
            "bounded_by_source_ast": bounded,
            "suspension_terminators": suspension_terms,
        })
    any_generators = bool(rows)
    return {
        "reachable_generator_callable_count": len(rows),
        "generator_callables": rows,
        "simultaneously_resident_generator_lower_bound": 1 if rows else 0,
        "simultaneously_resident_generator_maximum": 0 if not rows else None,
        "simultaneous_residency_bound_proved": not any_generators,
        "all_source_generator_frame_slots_bounded": all(
            row["bounded_by_source_ast"] for row in rows),
        "max_source_generator_frame_slots": max(
            (row["bounded_frame_slots"] for row in rows
             if isinstance(row["bounded_frame_slots"], int)), default=0),
    }


def _strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _c_function_body(text: str, signature: str) -> str | None:
    start = text.find(signature)
    if start < 0:
        return None
    opening = text.find("{", start + len(signature))
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    return None


def _c_struct_unsigned_field_bits(text: str, struct_name: str,
                                  field_name: str) -> int | None:
    clean = _strip_c_comments(text)
    match = re.search(
        rf"typedef\s+struct\s+{re.escape(struct_name)}\s*\{{"
        rf"(?P<body>.*?)\}}\s*{re.escape(struct_name)}\s*;",
        clean, re.DOTALL)
    if match is None:
        return None
    field = re.search(
        rf"\buint(8|16|32)_t\s+{re.escape(field_name)}\s*;",
        match.group("body"))
    return int(field.group(1)) if field is not None else None


def _frame_slot_runtime_contract(c_source: str,
                                 header_source: str) -> dict[str, Any]:
    """Prove the narrowest C field which must hold a per-frame slot count."""
    fields = {
        "PyZ80VMLimits.locals_per_frame": _c_struct_unsigned_field_bits(
            header_source, "PyZ80VMLimits", "locals_per_frame"),
        "PyZ80VMFrame.local_count": _c_struct_unsigned_field_bits(
            header_source, "PyZ80VMFrame", "local_count"),
        "PyZ80VMGenerator.local_count": _c_struct_unsigned_field_bits(
            header_source, "PyZ80VMGenerator", "local_count"),
        "PZVTUnit.frame_slot_count": _c_struct_unsigned_field_bits(
            c_source, "PZVTUnit", "frame_slot_count"),
    }
    exact = all(isinstance(bits, int) for bits in fields.values())
    narrowest = min(fields.values()) if exact else None
    return {
        "source_proved": exact,
        "unsigned_field_bits": fields,
        "narrowest_field_bits": narrowest,
        "maximum_frame_slot_count": (
            (1 << narrowest) - 1 if isinstance(narrowest, int) else None),
    }


def _iterative_runtime_contract(c_source: str, header_source: str
                                ) -> dict[str, bool]:
    clean_c = _strip_c_comments(c_source)
    run_body = _c_function_body(clean_c, "uint8_t PyZ80VM_Run(")
    core_pushes_frame_without_run_reentry = bool(
        run_body is not None and "PyZ80VM_Run(" not in run_body and
        "return push_unit(" in clean_c and "++vm->call_depth" in clean_c)
    return {
        "run_loop_has_no_direct_self_call": bool(
            run_body is not None and "PyZ80VM_Run(" not in run_body),
        "core_call_pushes_arena_frame": core_pushes_frame_without_run_reentry,
        "callback_no_reentry_contract_declared": (
            "must not recursively call PyZ80VM_Run" in header_source),
        "iterative_vm_call_contract_source_proved":
            core_pushes_frame_without_run_reentry,
    }


def _arena_formula_contract(c_source: str) -> tuple[bool, int | None]:
    compact = re.sub(r"\s+", "", _strip_c_comments(c_source))
    start = compact.find("uint16_tPyZ80VM_ArenaBytes(")
    if start < 0:
        return False, None
    body = compact[start:start + 2200]
    local_formula = (
        "local_count=((uint32_t)limits->max_call_depth+"
        "limits->max_generators)*limits->locals_per_frame;")
    bytes_expression = (
        "bytes=(uint32_t)limits->max_call_depth*sizeof(PyZ80VMFrame)+"
        "(uint32_t)limits->max_generators*sizeof(PyZ80VMGenerator)+"
        "local_count*sizeof(PyZ80VMLocal)+"
        "(uint32_t)limits->max_arguments*sizeof(PyZ80VMValue)")
    match = re.search(
        re.escape(bytes_expression) + r"(?:\+([0-9]+)u)?;", body)
    return local_formula in body and match is not None, (
        int(match.group(1) or 0) if match else None)


def _locate_sdcc(root: Path) -> Path | None:
    configured = os.environ.get("PYZ80_SDCC", "").strip('" ')
    candidates = ([Path(configured)] if configured else []) + [
        root.parent / "sdcc" / "bin" / "sdcc.exe",
        Path("C:/Program Files/SDCC/bin/sdcc.exe"),
    ]
    return next((candidate.resolve() for candidate in candidates
                 if candidate.is_file()), None)


def _probe_sdcc_struct_sizes(root: Path, header: Path) -> dict[str, Any]:
    sdcc = _locate_sdcc(root)
    if sdcc is None:
        return {"exact": False, "reason": "pinned SDCC was not found"}
    names = {
        "value": "PyZ80VMValue",
        "local": "PyZ80VMLocal",
        "frame": "PyZ80VMFrame",
        "generator": "PyZ80VMGenerator",
        "limits": "PyZ80VMLimits",
        "vm": "PyZ80VM",
    }
    source_text = (
        '#include "pyz80_whole_program_vm.h"\n' +
        "\n".join(
            f"uint8_t pzvmsb_{name}[sizeof({ctype})];"
            for name, ctype in names.items()) + "\n")
    with tempfile.TemporaryDirectory(prefix="pyz80-vm-stack-abi-") as raw:
        directory = Path(raw)
        source = directory / "abi_probe.c"
        assembly = directory / "abi_probe.asm"
        source.write_text(source_text, encoding="utf-8", newline="\n")
        environment = os.environ.copy()
        environment["PATH"] = str(sdcc.parent) + os.pathsep + environment.get(
            "PATH", "")
        command = [
            str(sdcc), "-mz80", "--std-c11", "-S",
            "-I" + str(header.parent), "-o", str(assembly), str(source),
        ]
        completed = subprocess.run(
            command, cwd=directory, env=environment, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace")
        if completed.returncode or not assembly.is_file():
            return {
                "exact": False,
                "reason": "SDCC ABI probe failed",
                "diagnostic_sha256": _sha256_bytes(
                    completed.stdout.encode("utf-8")),
            }
        assembly_text = assembly.read_text(
            encoding="utf-8", errors="replace")
    sizes: dict[str, int] = {}
    for name in names:
        match = re.search(
            rf"(?ms)^_pzvmsb_{re.escape(name)}::?\s*$.*?"
            r"^\s*\.ds\s+([0-9A-Fa-fx]+)\s*$",
            assembly_text)
        if match is None:
            return {"exact": False,
                    "reason": f"SDCC ABI size symbol {name} was not emitted"}
        sizes[name] = int(match.group(1), 0)
    version = subprocess.run(
        [str(sdcc), "--version"], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace").stdout.strip()
    return {
        "exact": True,
        "target": "sdcc-z80",
        "struct_sizes_bytes": sizes,
        "compiler": {
            "name": sdcc.name,
            "sha256": _sha256_bytes(sdcc.read_bytes()),
            "version_sha256": _sha256_bytes(version.encode("utf-8")),
            "version_first_line": version.splitlines()[0] if version else "",
        },
        "probe_source_sha256": _sha256_bytes(source_text.encode("utf-8")),
        "probe_assembly_sha256": _sha256_bytes(
            assembly_text.encode("utf-8")),
    }


def _runtime_abi(root: Path) -> dict[str, Any]:
    sources = []
    payloads: dict[str, bytes] = {}
    for relative in RUNTIME_SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise WholeProgramVMStackBoundError(
                "PZVSB033", f"runtime source is absent: {relative}")
        payload = path.read_bytes()
        payloads[relative] = payload
        sources.append({"path": relative, "bytes": len(payload),
                        "sha256": _sha256_bytes(payload)})
    try:
        c_source = payloads[RUNTIME_SOURCE_PATHS[1]].decode("utf-8")
        header_source = payloads[RUNTIME_SOURCE_PATHS[0]].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WholeProgramVMStackBoundError(
            "PZVSB034", "runtime C is not UTF-8") from exc
    formula, tail = _arena_formula_contract(c_source)
    iterative = _iterative_runtime_contract(c_source, header_source)
    frame_slots = _frame_slot_runtime_contract(c_source, header_source)
    probe = _probe_sdcc_struct_sizes(
        root, root / RUNTIME_SOURCE_PATHS[0])
    exact = bool(formula and probe.get("exact"))
    return {
        "runtime_sources": sources,
        "arena_formula_source_proved": formula,
        "arena_formula_tail_bytes": tail,
        "target_abi_probe": probe,
        "iterative_runtime_contract": iterative,
        "frame_slot_runtime_contract": frame_slots,
        "exact_arena_byte_formula_available": exact,
    }


def _arena_bytes(call_depth: int, generators: int, locals_per_frame: int,
                 max_arguments: int, abi: Mapping[str, Any]) -> int | None:
    if not abi.get("exact_arena_byte_formula_available"):
        return None
    sizes = abi["target_abi_probe"]["struct_sizes_bytes"]
    tail = abi["arena_formula_tail_bytes"]
    result = (
        call_depth * sizes["frame"] +
        generators * sizes["generator"] +
        (call_depth + generators) * locals_per_frame * sizes["local"] +
        max_arguments * sizes["value"] + tail)
    return result


def _blocker(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def analyze_whole_program_vm_stack_bound(
        artifact: WholeProgramVMArtifact,
        active_call_graph: Mapping[str, Any], *, project_root: str | Path,
        ) -> dict[str, Any]:
    """Return a deterministic, fail-closed PZVT stack/arena certificate."""
    root = Path(project_root).resolve()
    graph = _validated_graph(active_call_graph)
    document, compact = _validated_artifact(artifact, graph)
    source = _source_call_proof(graph)
    labels = artifact.target_coverage.get("compact_unit_labels")
    core = _compact_core_proof(
        document, compact, graph.entrypoint,
        compact_unit_labels=(labels if isinstance(labels, list) else None))
    generators = _generator_proof(graph)
    abi = _runtime_abi(root)

    if not source["recursive_scc_count"]:
        weighted_slots, weighted_path = _longest_dag_path(
            graph.reachable, source["_adjacency"], (graph.entrypoint,),
            core["_function_frame_slot_counts"])
        source["proven_function_only_path_weighted_frame_slots"] = weighted_slots
        source["proven_function_only_weighted_path"] = list(weighted_path)
    else:
        source["proven_function_only_path_weighted_frame_slots"] = None
        source["proven_function_only_weighted_path"] = []

    blockers: list[dict[str, str]] = []
    if core["dynamic_closure_call_count"]:
        blockers.append(_blocker("PZVSBLIVE016",
            "runtime closure identities require a dynamic call-depth bound"))
    if source["recursive_scc_count"]:
        blockers.append(_blocker(
            "PZVSBLIVE001",
            "recursive SCCs prevent a finite source call-depth proof"))
    if source["reachable_unresolved_call_site_count"]:
        blockers.append(_blocker(
            "PZVSBLIVE002",
            "reachable unresolved call sites can add unknown target depth"))
    if source["reachable_finite_dynamic_dispatch_site_count"]:
        blockers.append(_blocker(
            "PZVSBLIVE013",
            "reachable finite-dynamic dispatch sites are not proven edges "
            "and can add unknown target depth"))
    if core["recursive_scc_count"]:
        blockers.append(_blocker(
            "PZVSBLIVE003",
            "compact core push graph contains recursion"))
    if not generators["simultaneous_residency_bound_proved"]:
        blockers.append(_blocker(
            "PZVSBLIVE004",
            "simultaneously resident generator-object maximum is unproved"))
    if not generators["all_source_generator_frame_slots_bounded"]:
        blockers.append(_blocker(
            "PZVSBLIVE005",
            "one or more generator frame slot layouts are not source-bounded"))
    if not abi["exact_arena_byte_formula_available"]:
        blockers.append(_blocker(
            "PZVSBLIVE006",
            "current C/H plus pinned SDCC do not prove exact target ABI sizes"))
    frame_slot_contract = abi["frame_slot_runtime_contract"]
    if not frame_slot_contract["source_proved"]:
        blockers.append(_blocker(
            "PZVSBLIVE014",
            "current runtime C/H does not prove every frame-slot count field"))
    elif core["max_frame_slot_count"] > frame_slot_contract[
            "maximum_frame_slot_count"]:
        blockers.append(_blocker(
            "PZVSBLIVE015",
            "decoded maximum frame_slot_count exceeds the current runtime "
            "field capacity"))
    if not abi["iterative_runtime_contract"][
            "iterative_vm_call_contract_source_proved"]:
        blockers.append(_blocker(
            "PZVSBLIVE012",
            "runtime source no longer proves iterative VM calls"))
    if artifact.adapter_table:
        blockers.append(_blocker(
            "PZVSBLIVE007",
            "adapter callback hardware-stack byte maximum is unproved"))
    blockers.append(_blocker(
        "PZVSBLIVE008",
        "banked image-reader callback hardware-stack byte maximum is unproved"))
    blockers.append(_blocker(
        "PZVSBLIVE009",
        "compiled/final-linked PZVT runtime hardware-stack maximum is unproved"))
    blockers.append(_blocker(
        "PZVSBLIVE010",
        "game ISR pre-emption stack composition is unproved"))

    proven_depth = source["proven_entry_longest_path_depth"]
    core_depth = core["entry_exact_core_call_depth"]
    condensation_depth = source[
        "proven_entry_condensation_depth_lower_bound"]
    depth_lower_bound = max(
        [value for value in (proven_depth, condensation_depth, core_depth)
         if isinstance(value, int)], default=1)
    generator_lower_bound = int(
        generators["simultaneously_resident_generator_lower_bound"])
    max_frame_slots = int(core["max_frame_slot_count"])
    max_arguments = int(core["max_argument_count"])
    arena_lower = _arena_bytes(
        depth_lower_bound, generator_lower_bound, max_frame_slots,
        max_arguments, abi)
    core_arena = (_arena_bytes(
        int(core_depth), 0, max_frame_slots, max_arguments, abi)
        if isinstance(core_depth, int) else None)
    local_bytes = None
    if abi["exact_arena_byte_formula_available"]:
        local_size = abi["target_abi_probe"]["struct_sizes_bytes"]["local"]
        local_bytes = max_frame_slots * local_size

    layout_issues = []
    if depth_lower_bound > 1 and max_frame_slots:
        uniform_slots = depth_lower_bound * max_frame_slots
        weighted_slots = source[
            "proven_function_only_path_weighted_frame_slots"]
        layout_issues.append({
            "code": "PZVSBW001",
            "detail": (
                "uniform locals_per_frame reserves the global maximum "
                "validated frame-slot count for every call frame"),
            "depth_lower_bound": depth_lower_bound,
            "frame_slots_per_frame": max_frame_slots,
            "max_ssa_local_count_census": core["max_ssa_local_count"],
            "uniform_local_slot_lower_bound": uniform_slots,
            "uniform_local_byte_lower_bound": (
                uniform_slots *
                abi["target_abi_probe"]["struct_sizes_bytes"]["local"]
                if abi["exact_arena_byte_formula_available"] else None),
            "proven_function_only_path_weighted_frame_slots": weighted_slots,
            "uniform_minus_function_only_weighted_slots": (
                uniform_slots - weighted_slots
                if isinstance(weighted_slots, int) else None),
            "note": (
                "function-only comparison excludes extra expression-CFG frames; "
                "it is a layout-pressure diagnostic, not an arena upper bound"),
        })
    if arena_lower is not None and arena_lower > _UINT16_LIMIT:
        blockers.append(_blocker(
            "PZVSBLIVE011",
            "even the proved arena lower bound exceeds uint16 arena_size"))

    source_public = {key: value for key, value in source.items()
                     if not key.startswith("_")}
    core_public = {key: value for key, value in core.items()
                   if not key.startswith("_")}
    binding = {
        "active_call_graph_semantic_sha256": graph.semantic_sha256,
        "call_graph_semantic_sha256": graph.call_graph_semantic_sha256,
        "artifact_semantic_sha256": artifact.semantic_sha256,
        "proof_bytecode_sha256": artifact.proof_bytecode_sha256,
        "target_bytecode_sha256": artifact.target_bytecode_sha256,
        "runtime_sources": abi["runtime_sources"],
        "target_abi_probe": abi["target_abi_probe"],
    }
    report: dict[str, Any] = {
        "format": WHOLE_PROGRAM_VM_STACK_BOUND_FORMAT,
        "binding": binding,
        "binding_sha256": _sha256_json(binding),
        "memory_domains": {
            "z80_hardware_call_stack": {
                "contains_vm_frames_or_locals": False,
                "iterative_vm_calls_use_c_recursion": (
                    False if abi["iterative_runtime_contract"][
                        "iterative_vm_call_contract_source_proved"] else None),
                "exact_byte_maximum": None,
                "callback_and_isr_composition_proved": False,
            },
            "caller_owned_vm_arena": {
                "contains_call_frames_locals_generators_and_argument_scratch": True,
                "z80_hardware_stack": False,
                "exact_formula_available": abi[
                    "exact_arena_byte_formula_available"],
            },
        },
        "source_call_graph": source_public,
        "compact_core": core_public,
        "generators": generators,
        "runtime_abi": abi,
        "arena": {
            "locals_per_frame_required": max_frame_slots,
            "frame_slots_per_frame_required": max_frame_slots,
            "max_ssa_local_count_census": core["max_ssa_local_count"],
            "local_bytes_per_uniform_frame": local_bytes,
            "max_arguments_required": max_arguments,
            "proved_call_depth_lower_bound": depth_lower_bound,
            "proved_generator_residency_lower_bound": generator_lower_bound,
            "whole_program_arena_lower_bound_bytes": arena_lower,
            "whole_program_arena_safe_upper_bound_bytes": None,
            "compact_executable_core_exact_arena_bytes_without_generators":
                core_arena,
            "uint16_arena_limit_bytes": _UINT16_LIMIT,
        },
        "layout_issues": layout_issues,
        "complete_bound_proved": False,
        "live": False,
        "live_blockers": sorted(blockers, key=lambda item: item["code"]),
    }
    report["semantic_sha256"] = _sha256_json(report)
    return report


def validate_whole_program_vm_stack_bound_report(
        artifact: WholeProgramVMArtifact,
        active_call_graph: Mapping[str, Any], report: Mapping[str, Any], *,
        project_root: str | Path) -> dict[str, Any]:
    """Recompute and validate a report against all current semantic inputs."""
    supplied = _require_dict(copy.deepcopy(dict(report)), "stack-bound report")
    _validate_semantic(supplied, "stack-bound report")
    expected = analyze_whole_program_vm_stack_bound(
        artifact, active_call_graph, project_root=project_root)
    if supplied != expected:
        raise WholeProgramVMStackBoundError(
            "PZVSB035", "stack-bound report is stale or tampered")
    return supplied


def render_whole_program_vm_stack_bound(
        artifact: WholeProgramVMArtifact,
        active_call_graph: Mapping[str, Any], *, project_root: str | Path,
        ) -> bytes:
    """Render deterministic status bytes without writing any output file."""
    return (json.dumps(
        analyze_whole_program_vm_stack_bound(
            artifact, active_call_graph, project_root=project_root),
        ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
