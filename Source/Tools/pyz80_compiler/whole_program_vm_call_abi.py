"""Per-call numeric ABI proof for the whole-program Python VM inventory.

The existing CFG deliberately keeps Python calls as protocol operations.  This
module prepares, but does not implement, their target ABI.  Every represented
call occurrence receives its own descriptor; callable SSA provenance,
receiver preservation, target IDs and argument binding remain visible and
fail closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cfg_ssa import CFGSSAError, DominatingDefinitions

from .active_call_graph import (
    analyze_active_call_graph,
    validate_active_call_graph_report,
)
from .active_call_site_lowering import (
    analyze_active_call_site_lowering,
    validate_active_call_site_lowering_report,
)


WHOLE_PROGRAM_VM_CALL_ABI_FORMAT = "pyz80.whole-program-vm-call-abi.v1"
WHOLE_PROGRAM_VM_CALL_ABI_STATUS = (
    "WHOLE_PROGRAM_VM_CALL_ABI_PLANNED_LIVE_BLOCKED")

__all__ = [
    "WHOLE_PROGRAM_VM_CALL_ABI_FORMAT",
    "WHOLE_PROGRAM_VM_CALL_ABI_STATUS",
    "WholeProgramVMCallABIError",
    "analyze_whole_program_vm_call_abi",
    "validate_whole_program_vm_call_abi_report",
    "execute_call_binding_oracle",
]


class WholeProgramVMCallABIError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload.pop("semantic_sha256", None)
    return payload


def _lookup_path(value: Any, path: Sequence[str | int]) -> Any:
    cursor = value
    for item in path:
        if isinstance(item, int):
            if not isinstance(cursor, list) or not (0 <= item < len(cursor)):
                raise WholeProgramVMCallABIError(
                    "PZCABI003", f"CFG path index is invalid: {path}")
            cursor = cursor[item]
        else:
            if not isinstance(cursor, Mapping) or item not in cursor:
                raise WholeProgramVMCallABIError(
                    "PZCABI003", f"CFG path key is invalid: {path}")
            cursor = cursor[item]
    return cursor


def _instruction_context(
        cfg: Mapping[str, Any], cfg_path: Sequence[str | int],
        ) -> tuple[list[Mapping[str, Any]], int, Mapping[str, Any]]:
    try:
        marker = list(cfg_path).index("instructions")
    except ValueError as error:
        raise WholeProgramVMCallABIError(
            "PZCABI003", "python-call path has no instruction list") from error
    if marker + 1 >= len(cfg_path) or not isinstance(cfg_path[marker + 1], int):
        raise WholeProgramVMCallABIError(
            "PZCABI003", "python-call path has no instruction index")
    raw_instructions = _lookup_path(cfg, cfg_path[:marker + 1])
    if not isinstance(raw_instructions, list):
        raise WholeProgramVMCallABIError(
            "PZCABI003", "CFG instruction container is malformed")
    instructions: list[Mapping[str, Any]] = []
    for row in raw_instructions:
        if not isinstance(row, Mapping):
            raise WholeProgramVMCallABIError(
                "PZCABI003", "CFG instruction row is malformed")
        instructions.append(row)
    index = int(cfg_path[marker + 1])
    if not (0 <= index < len(instructions)):
        raise WholeProgramVMCallABIError(
            "PZCABI003", "python-call instruction index is out of range")
    instruction = instructions[index]
    if instruction.get("op") != "python-call":
        raise WholeProgramVMCallABIError(
            "PZCABI003", "lowering occurrence no longer points to python-call")
    return instructions, index, instruction


def _definition_map(
        cfg: Mapping[str, Any], cfg_path: Sequence[str | int],
        instructions: Sequence[Mapping[str, Any]], stop: int,
        cache: dict[int, DominatingDefinitions] | None = None,
        ) -> dict[str, list[Mapping[str, Any]]]:
    """Collect definitions from CFG blocks that dominate this instruction."""
    try:
        block_marker = list(cfg_path).index("blocks")
        block_index = cfg_path[block_marker + 1]
    except (ValueError, IndexError) as error:
        raise WholeProgramVMCallABIError(
            "PZCABI003", "python-call path has no CFG block") from error
    unit = _lookup_path(cfg, cfg_path[:block_marker])
    if not isinstance(unit, Mapping) or not isinstance(block_index, int):
        raise WholeProgramVMCallABIError(
            "PZCABI003", "python-call CFG block context is malformed")
    try:
        index = cache.get(id(unit)) if cache is not None else None
        if index is None:
            index = DominatingDefinitions(unit)
            if cache is not None:
                cache[id(unit)] = index
        return index.at(block_index, stop)
    except CFGSSAError as error:
        raise WholeProgramVMCallABIError("PZCABI003", str(error)) from error


def _instruction_proof(instruction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "op": instruction.get("op"),
        "sequence": instruction.get("sequence"),
        "destination": instruction.get("destination"),
        "arguments": list(instruction.get("arguments", ())),
        "span": dict(instruction.get("span", {})),
    }


def _trace_value(
        value: Any, definitions: Mapping[str, list[Mapping[str, Any]]], *,
        seen: frozenset[str] = frozenset(), depth: int = 0,
        ) -> dict[str, Any]:
    if not isinstance(value, str) or not value.startswith("%"):
        return {"value": value, "kind": "literal-or-name"}
    matches = definitions.get(value, ())
    if len(matches) != 1:
        return {
            "value": value, "kind": "ambiguous-ssa-definition",
            "definition_count": len(matches),
        }
    if value in seen or depth >= 32:
        return {"value": value, "kind": "ssa-cycle-or-depth-limit"}
    definition = matches[0]
    arguments = list(definition.get("arguments", ()))
    return {
        "value": value,
        "kind": "ssa-definition",
        "definition": _instruction_proof(definition),
        "inputs": [
            _trace_value(argument, definitions,
                         seen=seen | {value}, depth=depth + 1)
            for argument in arguments
            if isinstance(argument, str) and argument.startswith("%")
        ],
    }


def _trace_is_unambiguous(trace: Mapping[str, Any]) -> bool:
    if trace.get("kind") == "literal-or-name":
        return True
    if trace.get("kind") != "ssa-definition":
        return False
    return all(_trace_is_unambiguous(item)
               for item in trace.get("inputs", ()))


def _callable_ssa_provenance(
        instruction: Mapping[str, Any],
        definitions: Mapping[str, list[Mapping[str, Any]]],
        ) -> dict[str, Any]:
    arguments = instruction.get("arguments")
    if not isinstance(arguments, list) or not arguments:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "detail": "python-call has no callable operand",
        }
    callable_value = arguments[0]
    require_matches = definitions.get(str(callable_value), ())
    if len(require_matches) != 1 or require_matches[0].get(
            "op") != "require-callable":
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "definition_count": len(require_matches),
            "detail": "callable operand has no unique require-callable",
        }
    require = require_matches[0]
    require_arguments = list(require.get("arguments", ()))
    if len(require_arguments) != 1:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "require_callable": _instruction_proof(require),
            "detail": "require-callable does not have one source value",
        }
    source_value = require_arguments[0]
    source_matches = definitions.get(str(source_value), ())
    if len(source_matches) != 1:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "require_callable": _instruction_proof(require),
            "callable_source_value": source_value,
            "source_definition_count": len(source_matches),
            "detail": "require-callable source has no unique SSA definition",
        }
    source = source_matches[0]
    source_arguments = list(source.get("arguments", ()))
    result: dict[str, Any] = {
        "status": "exact",
        "callable_value": callable_value,
        "require_callable": _instruction_proof(require),
        "callable_source_value": source_value,
        "callable_source": _instruction_proof(source),
        "source_operation": source.get("op"),
    }
    if source.get("op") == "load-attribute" and len(source_arguments) >= 2:
        receiver = source_arguments[0]
        receiver_provenance = _trace_value(receiver, definitions)
        result.update({
            "source_kind": "attribute",
            "receiver_value": receiver,
            "attribute_name": source_arguments[1],
            "receiver_provenance": receiver_provenance,
            "receiver_status": (
                "exact" if _trace_is_unambiguous(receiver_provenance)
                else "ambiguous"),
        })
    elif source.get("op") == "load-name" and len(source_arguments) == 1:
        result.update({
            "source_kind": "name",
            "loaded_name": source_arguments[0],
        })
    else:
        result.update({
            "status": "ambiguous",
            "blocker": "PZCABI201",
            "source_kind": "other-expression",
            "detail": "callable source is neither load-name nor "
            "load-attribute",
        })
    return result


def _function_table(active_graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    reachable = [str(item) for item in active_graph[
        "call_graph"]["proven_reachable_callable_ids"]]
    inventory = [str(row["callable_id"]) for row in active_graph[
        "callable_inventory"]["callables"]]
    remaining = sorted(set(inventory) - set(reachable))
    ordered = reachable + remaining
    if len(ordered) != len(set(ordered)) or len(ordered) > 0xFFFF:
        raise WholeProgramVMCallABIError(
            "PZCABI004", "numeric function table is duplicate or too large")
    reachable_ids = {identifier: index
                     for index, identifier in enumerate(reachable)}
    return [{
        "numeric_function_id": index,
        "callable_id": identifier,
        "proven_reachable": identifier in reachable_ids,
        "current_pzvt_function_id": reachable_ids.get(identifier),
    } for index, identifier in enumerate(ordered)]


def _effective_binding_mode(
        site: Mapping[str, Any], signature: Mapping[str, Any] | None,
        ) -> str:
    mode = str(site["binding_mode"])
    if site["resolution_kind"] == "exact-generated-dataclass-init":
        return "generated-dataclass-init"
    if site["resolution_kind"] == "exact-internal-class-method":
        if signature is not None and signature.get("is_classmethod"):
            return "classmethod"
        return "free"  # staticmethod or an explicitly unbound function
    return mode


def _parameter_binding_plan(
        signature: Mapping[str, Any], binding_mode: str,
        argument_layout: Sequence[Mapping[str, Any]], *,
        receiver_value: Any | None,
        ) -> dict[str, Any]:
    parameters = [dict(row) for row in signature["parameters"]]
    positional = [row for row in parameters if row["kind"] in {
        "positional-only", "positional-or-keyword"}]
    implicit = binding_mode in {
        "bound-method", "common-dispatch", "super", "classmethod",
        "constructor", "generated-dataclass-init",
    }
    if signature.get("is_staticmethod"):
        implicit = False
    entries: list[dict[str, Any]] = []
    blockers: list[str] = []
    supplied: set[str] = set()
    positional_cursor = 1 if implicit else 0
    if implicit:
        if not positional:
            blockers.append("PZCABI208")
        else:
            parameter = str(positional[0]["name"])
            supplied.add(parameter)
            if binding_mode == "constructor":
                source_kind = "allocated-object"
                source_value = "$allocated-object"
            else:
                source_kind = "receiver"
                source_value = receiver_value
                if receiver_value is None:
                    blockers.append("PZCABI202")
            entries.append({
                "evaluation_index": -1,
                "destination_parameter": parameter,
                "destination_kind": positional[0]["kind"],
                "source_kind": source_kind,
                "source_value": source_value,
            })

    var_positional = next((row for row in parameters
                           if row["kind"] == "var-positional"), None)
    var_keyword = next((row for row in parameters
                        if row["kind"] == "var-keyword"), None)
    by_name = {str(row["name"]): row for row in parameters}
    for evaluation_index, argument in enumerate(argument_layout):
        kind = str(argument["kind"])
        source_value = argument["value"]
        if kind == "positional":
            if positional_cursor < len(positional):
                destination = positional[positional_cursor]
                positional_cursor += 1
                parameter = str(destination["name"])
                if parameter in supplied:
                    blockers.append("PZCABI208")
                supplied.add(parameter)
                destination_kind = str(destination["kind"])
            elif var_positional is not None:
                parameter = str(var_positional["name"])
                destination_kind = "var-positional-item"
            else:
                parameter = None
                destination_kind = "unexpected-positional"
                blockers.append("PZCABI208")
            entries.append({
                "evaluation_index": evaluation_index,
                "destination_parameter": parameter,
                "destination_kind": destination_kind,
                "source_kind": "argument",
                "source_value": source_value,
            })
            continue
        if kind == "keyword":
            name = str(argument["keyword"])
            destination = by_name.get(name)
            if destination is not None and destination["kind"] != \
                    "positional-only":
                parameter = name
                destination_kind = str(destination["kind"])
                if parameter in supplied:
                    blockers.append("PZCABI208")
                supplied.add(parameter)
            elif var_keyword is not None:
                parameter = str(var_keyword["name"])
                destination_kind = "var-keyword-item"
            else:
                parameter = None
                destination_kind = "unexpected-keyword"
                blockers.append("PZCABI208")
            entries.append({
                "evaluation_index": evaluation_index,
                "destination_parameter": parameter,
                "destination_kind": destination_kind,
                "keyword": name,
                "source_kind": "argument",
                "source_value": source_value,
            })
            continue
        if kind in {"star-positional", "star-keyword"}:
            entries.append({
                "evaluation_index": evaluation_index,
                "destination_parameter": None,
                "destination_kind": "runtime-star-expansion",
                "star_kind": kind,
                "source_kind": "argument",
                "source_value": source_value,
            })
            blockers.append("PZCABI207")
            continue
        blockers.append("PZCABI208")

    for parameter in parameters:
        name = str(parameter["name"])
        if parameter["kind"] in {"var-positional", "var-keyword"} or \
                name in supplied:
            continue
        if parameter["has_default"]:
            literal_default = (
                binding_mode == "generated-dataclass-init" and
                parameter.get("default_value_proven") is True)
            entries.append({
                "evaluation_index": None,
                "destination_parameter": name,
                "destination_kind": parameter["kind"],
                "source_kind": ("literal-default" if literal_default
                                else "default"),
                "source_value": (parameter.get("default_value")
                                 if literal_default else
                                 parameter["default_ast_sha256"]),
            })
            if not literal_default:
                blockers.append("PZCABI209")
        else:
            entries.append({
                "evaluation_index": None,
                "destination_parameter": name,
                "destination_kind": parameter["kind"],
                "source_kind": "missing-required",
                "source_value": None,
            })
            blockers.append("PZCABI208")
    return {
        "binding_mode": binding_mode,
        "parameter_destination_map": entries,
        "blocker_codes": sorted(set(blockers)),
        "explicit_argument_evaluation_order": [
            row["source_value"] for row in entries
            if isinstance(row["evaluation_index"], int) and
            row["evaluation_index"] >= 0
        ],
    }


def _constructor_sequence(
        graph_site: Mapping[str, Any],
        target_descriptors: Sequence[Mapping[str, Any]],
        ) -> list[dict[str, Any]]:
    constructed_class = graph_site["resolution"].get("constructed_class")
    target_ids = [row["numeric_function_id"] for row in target_descriptors]
    return [
        {"step": 0, "operation": "allocate-instance",
         "constructed_class": constructed_class,
         "result": "$allocated-object"},
        {"step": 1, "operation": "bind-init-self",
         "value": "$allocated-object"},
        {"step": 2, "operation": "invoke-__init__",
         "target_numeric_function_ids": target_ids,
         "required_return": None},
        {"step": 3, "operation": "return-allocated-instance",
         "value": "$allocated-object"},
    ]


_BLOCKER_DETAILS = {
    "PZCABI201": "callable SSA provenance is not unique",
    "PZCABI202": "a bound receiver SSA value is not source-proven",
    "PZCABI203": "a target callable has no numeric ABI function ID",
    "PZCABI204": "finite dispatch remains runtime-guarded and non-proven",
    "PZCABI205": "host boundary requires a target adapter",
    "PZCABI206": "callable identity remains unresolved",
    "PZCABI207": "star argument expansion requires runtime binding",
    "PZCABI208": "parameter binding can raise or is not statically complete",
    "PZCABI209": "default expression application requires runtime support",
    "PZCABI210": "nested callable requires its lexical environment",
    "PZCABI212": "candidate target is outside the proven PZVT function table",
    "PZCABI213": "the current VM/backend does not consume this ABI inventory",
    "PZCABI214": (
        "a super proxy cannot be passed as the target method self receiver"),
    "PZCABI215": (
        "call-site lowering has reachable graph sites without CFG occurrences"),
}


def _build_report(
        active_graph: Mapping[str, Any],
        call_lowering: Mapping[str, Any],
        ) -> dict[str, Any]:
    callable_rows = {
        str(row["callable_id"]): row
        for row in active_graph["callable_inventory"]["callables"]
    }
    graph_sites = {
        str(row["call_site_id"]): row
        for row in active_graph["call_graph"]["call_sites"]
    }
    lowering_sites = {
        str(row["call_site_id"]): row
        for row in call_lowering["sites_in_source_order"]
    }
    signature_rows = call_lowering["target_signatures"]
    function_table = _function_table(active_graph)
    function_by_callable = {
        row["callable_id"]: row for row in function_table}

    occurrence_descriptors: list[dict[str, Any]] = []
    blockers: Counter[str] = Counter()
    definition_indexes: dict[int, DominatingDefinitions] = {}
    for occurrence in call_lowering["cfg_occurrences_in_cfg_order"]:
        caller = str(occurrence["caller"])
        callable_row = callable_rows[caller]
        cfg = callable_row["cfg"]
        instructions, instruction_index, instruction = _instruction_context(
            cfg, occurrence["cfg_path"])
        if (dict(instruction.get("span", {})) != occurrence["span"] or
                instruction.get("destination") != occurrence["destination"]):
            raise WholeProgramVMCallABIError(
                "PZCABI005", "lowering occurrence differs from its CFG call")
        definitions = _definition_map(
            cfg, occurrence["cfg_path"], instructions, instruction_index,
            definition_indexes)
        provenance = _callable_ssa_provenance(instruction, definitions)
        site_id = str(occurrence["call_site_id"])
        site = lowering_sites[site_id]
        graph_site = graph_sites[site_id]
        generated_mode = (site.get("binding_mode") ==
                          "generated-dataclass-init")
        receiver_value = (site.get("receiver_parameter") if generated_mode
                          else provenance.get("receiver_value"))

        target_descriptors: list[dict[str, Any]] = []
        descriptor_blockers: list[str] = []
        if provenance.get("status") != "exact":
            descriptor_blockers.append(str(provenance["blocker"]))
        if generated_mode:
            schema = site.get("generated_dataclass_init")
            if not isinstance(schema, Mapping):
                descriptor_blockers.append("PZCABI203")
            else:
                signature = {
                    "parameters": list(schema.get("parameters", ())),
                    "is_staticmethod": False,
                }
                plan = _parameter_binding_plan(
                    signature, "generated-dataclass-init",
                    occurrence["argument_layout"],
                    receiver_value=receiver_value)
                post_init = schema.get("post_init_target")
                function = (function_by_callable.get(str(post_init))
                            if isinstance(post_init, str) else None)
                if isinstance(post_init, str) and function is None:
                    descriptor_blockers.append("PZCABI203")
                if function is not None and not function["proven_reachable"]:
                    descriptor_blockers.append("PZCABI212")
                descriptor_blockers.extend(plan["blocker_codes"])
                target_descriptors.append({
                    "callable_id": post_init,
                    "numeric_function_id": (function["numeric_function_id"]
                                            if function is not None else None),
                    "current_pzvt_function_id": (
                        function["current_pzvt_function_id"]
                        if function is not None else None),
                    "proven_reachable": (function["proven_reachable"]
                                         if function is not None else True),
                    "binding_mode": "generated-dataclass-init",
                    "generated_dataclass_init": dict(schema),
                    "parameter_destination_map": plan[
                        "parameter_destination_map"],
                    "explicit_argument_evaluation_order": plan[
                        "explicit_argument_evaluation_order"],
                    "lexical_owner": None,
                    "blocker_codes": plan["blocker_codes"],
                })
        else:
            for target in site["targets"]:
                target = str(target)
                function = function_by_callable.get(target)
                signature = signature_rows.get(target)
                if function is None or signature is None:
                    descriptor_blockers.append("PZCABI203")
                    continue
                mode = _effective_binding_mode(site, signature)
                plan = _parameter_binding_plan(
                    signature, mode, occurrence["argument_layout"],
                    receiver_value=receiver_value)
                lexical_parent = callable_rows[target].get("lexical_parent_id")
                lexical_owner = (function_by_callable.get(str(lexical_parent))
                                 if lexical_parent is not None else None)
                if mode == "nested" and lexical_owner is None:
                    descriptor_blockers.append("PZCABI210")
                if not function["proven_reachable"]:
                    descriptor_blockers.append("PZCABI212")
                descriptor_blockers.extend(plan["blocker_codes"])
                target_descriptors.append({
                    "callable_id": target,
                    "numeric_function_id": function["numeric_function_id"],
                    "current_pzvt_function_id": function[
                        "current_pzvt_function_id"],
                    "proven_reachable": function["proven_reachable"],
                    "binding_mode": mode,
                    "parameter_destination_map": plan[
                        "parameter_destination_map"],
                    "explicit_argument_evaluation_order": plan[
                        "explicit_argument_evaluation_order"],
                    "lexical_owner": ({
                        "callable_id": lexical_parent,
                        "numeric_function_id": lexical_owner[
                            "numeric_function_id"],
                        "current_pzvt_function_id": lexical_owner[
                            "current_pzvt_function_id"],
                    } if lexical_owner is not None else None),
                    "blocker_codes": plan["blocker_codes"],
                })

        classification = str(site["classification"])
        if classification == "finite-non-proven":
            descriptor_blockers.append("PZCABI204")
        elif classification == "host-boundary":
            descriptor_blockers.append("PZCABI205")
        elif classification in {"unresolved", "invalid-proven-target-arity"}:
            descriptor_blockers.append("PZCABI206")
        mode = str(site["binding_mode"])
        effective_modes = sorted({row["binding_mode"]
                                  for row in target_descriptors})
        effective_mode = effective_modes[0] if len(effective_modes) == 1 else mode
        receiver_required = effective_mode in {
            "bound-method", "common-dispatch", "super", "classmethod",
            "generated-dataclass-init"}
        if receiver_required and (
                provenance.get("status") != "exact" or
                provenance.get("source_kind") != "attribute" or
                provenance.get("receiver_status") != "exact" or
                receiver_value is None):
            descriptor_blockers.append("PZCABI202")
        if effective_mode == "nested":
            descriptor_blockers.append("PZCABI210")
        if effective_mode == "super":
            descriptor_blockers.append("PZCABI214")
        descriptor_blockers = sorted(set(descriptor_blockers))
        blockers.update(descriptor_blockers)

        finite_dispatch = None
        if classification == "finite-non-proven":
            finite_dispatch = {
                "proven": False,
                "runtime_identity_guard_required": True,
                "candidate_set_is_not_a_reachability_edge": True,
                "entries": [{
                    "callable_id": row["callable_id"],
                    "numeric_function_id": row["numeric_function_id"],
                    "current_pzvt_function_id": row[
                        "current_pzvt_function_id"],
                } for row in target_descriptors],
            }
        constructor_sequence = (_constructor_sequence(
            graph_site, target_descriptors)
            if effective_mode == "constructor" else None)
        descriptor = {
            "numeric_abi_descriptor_id": len(occurrence_descriptors),
            "numeric_call_site_id": int(occurrence["numeric_call_site_id"]),
            "cfg_occurrence_index": int(occurrence[
                "cfg_occurrence_index"]),
            "call_site_id": site_id,
            "caller": caller,
            "caller_numeric_function_id": function_by_callable[caller][
                "numeric_function_id"],
            "span": dict(occurrence["span"]),
            "classification": classification,
            "proven": bool(site["proven"]),
            "resolution_kind": str(site["resolution_kind"]),
            "resolution_evidence": str(site["resolution_evidence"]),
            "binding_mode": effective_mode,
            "callable_ssa_provenance": provenance,
            "receiver_value": receiver_value,
            "generated_dataclass_init": (dict(site[
                "generated_dataclass_init"])
                if isinstance(site.get("generated_dataclass_init"), Mapping)
                else None),
            "argument_evaluation_order": [{
                "evaluation_index": index,
                "kind": row["kind"],
                "keyword": row["keyword"],
                "source_value": row["value"],
            } for index, row in enumerate(occurrence["argument_layout"])],
            "target_descriptors": target_descriptors,
            "target_numeric_function_ids": [
                row["numeric_function_id"] for row in target_descriptors
                if isinstance(row.get("numeric_function_id"), int)],
            "finite_dispatch_table": finite_dispatch,
            "constructor_sequence": constructor_sequence,
            "blocker_codes": descriptor_blockers,
        }
        occurrence_descriptors.append(descriptor)

    descriptors_by_site: dict[int, list[int]] = defaultdict(list)
    for row in occurrence_descriptors:
        descriptors_by_site[int(row["numeric_call_site_id"])].append(
            int(row["numeric_abi_descriptor_id"]))
    site_descriptors = [{
        "numeric_call_site_id": int(site["numeric_call_site_id"]),
        "call_site_id": str(site["call_site_id"]),
        "source_order_index": int(site["source_order_index"]),
        "classification": str(site["classification"]),
        "proven": bool(site["proven"]),
        "target_numeric_function_ids": sorted({
            target_id
            for descriptor_id in descriptors_by_site[int(
                site["numeric_call_site_id"])]
            for target_id in occurrence_descriptors[descriptor_id][
                "target_numeric_function_ids"]
        }),
        "numeric_abi_descriptor_ids": descriptors_by_site[int(
            site["numeric_call_site_id"])],
    } for site in call_lowering["sites_in_source_order"]]

    unrepresented_sites = [
        dict(site)
        for site in call_lowering["unrepresented_graph_sites_in_source_order"]
    ]
    unrepresented_classification_counts = Counter(
        str(site["classification"]) for site in unrepresented_sites)
    lowering_prerequisites = {
        "unrepresented_graph_call_site_count": len(unrepresented_sites),
        "unrepresented_numeric_call_site_ids_in_source_order": [
            int(site["numeric_call_site_id"]) for site in unrepresented_sites],
        "unrepresented_call_site_ids_in_source_order": [
            str(site["call_site_id"]) for site in unrepresented_sites],
        "unrepresented_classification_counts": dict(sorted(
            unrepresented_classification_counts.items())),
        "unrepresented_graph_sites_in_source_order": unrepresented_sites,
    }

    category_counts = Counter(
        row["classification"] for row in occurrence_descriptors)
    binding_counts = Counter(
        row["binding_mode"] for row in occurrence_descriptors)
    live_blocker_counts = Counter(blockers)
    live_blocker_counts["PZCABI213"] += 1
    if unrepresented_sites:
        live_blocker_counts["PZCABI215"] += len(unrepresented_sites)
    live_blockers = [{
        "code": code, "count": int(count),
        "detail": _BLOCKER_DETAILS[code],
    } for code, count in sorted(live_blocker_counts.items())]

    report: dict[str, Any] = {
        "format": WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
        "status": WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": active_graph[
            "semantic_sha256"],
        "call_site_lowering_semantic_sha256": call_lowering[
            "semantic_sha256"],
        "function_id_contract": {
            "width_bits": 16,
            "first_id": 0,
            "proven_reachable_prefix_matches_current_pzvt_order": True,
            "candidate_only_functions_are_not_current_pzvt_functions": True,
            "function_count": len(function_table),
        },
        "function_id_table": function_table,
        "call_site_lowering_prerequisites": lowering_prerequisites,
        "census": {
            "represented_call_site_count": len(site_descriptors),
            "unrepresented_graph_call_site_count": len(unrepresented_sites),
            "call_occurrence_descriptor_count": len(occurrence_descriptors),
            "duplicate_occurrence_descriptor_count": (
                len(occurrence_descriptors) - len(site_descriptors)),
            "classification_counts": dict(sorted(category_counts.items())),
            "unrepresented_graph_call_site_classification_counts": dict(
                sorted(unrepresented_classification_counts.items())),
            "binding_mode_counts": dict(sorted(binding_counts.items())),
            "blocker_descriptor_counts": dict(sorted(blockers.items())),
            "prerequisite_blocker_counts": ({
                "PZCABI215": len(unrepresented_sites),
            } if unrepresented_sites else {}),
            "exact_callable_ssa_provenance_count": sum(
                row["callable_ssa_provenance"].get("status") == "exact"
                for row in occurrence_descriptors),
            "ambiguous_callable_ssa_provenance_count": sum(
                row["callable_ssa_provenance"].get("status") != "exact"
                for row in occurrence_descriptors),
        },
        "site_abi_descriptors_in_source_order": site_descriptors,
        "occurrence_abi_descriptors_in_cfg_order": occurrence_descriptors,
        "live_blockers": live_blockers,
        "proof": {
            "active_call_graph_and_lowering_validated_in_memory": True,
            "one_numeric_descriptor_per_represented_cfg_occurrence": True,
            "callable_ssa_chain_is_traced_without_receiver_invention": True,
            "finite_dispatch_tables_remain_non_proven": True,
            "constructor_sequence_is_allocate_bind_init_return": True,
            "argument_evaluation_order_is_not_reordered": True,
            "parameter_destination_map_is_per_occurrence_and_target": True,
            "nested_lexical_owner_is_explicit": True,
            "unrepresented_graph_sites_are_explicit_lowering_prerequisites":
                True,
            "backend_must_address_numeric_abi_descriptor_id_and_cfg_occurrence":
                True,
            "numeric_call_site_id_alone_is_not_backend_dispatch_identity": True,
            "current_vm_backend_consumes_call_abi": False,
        },
    }
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    return report


def analyze_whole_program_vm_call_abi(
        project_root: Path | str, *,
        active_graph: Mapping[str, Any] | None = None,
        call_site_lowering: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    """Build and validate the per-occurrence numeric call ABI proof."""
    root = Path(project_root).resolve()
    graph = (analyze_active_call_graph(root)
             if active_graph is None else active_graph)
    validate_active_call_graph_report(root, graph)
    lowering = (analyze_active_call_site_lowering(
        root, active_graph=graph) if call_site_lowering is None else
        call_site_lowering)
    report = _build_report(graph, lowering)
    # The final validator below validates both inputs before rebuilding this
    # report independently.  Repeating lowering validation here rebuilt the
    # full occurrence inventory twice without adding a distinct proof.
    validate_whole_program_vm_call_abi_report(
        root, report, active_graph=graph, call_site_lowering=lowering)
    return report


def validate_whole_program_vm_call_abi_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        active_graph: Mapping[str, Any],
        call_site_lowering: Mapping[str, Any],
        ) -> None:
    root = Path(project_root).resolve()
    validate_active_call_graph_report(root, active_graph)
    validate_active_call_site_lowering_report(
        root, call_site_lowering, active_graph=active_graph)
    if report.get("format") != WHOLE_PROGRAM_VM_CALL_ABI_FORMAT:
        raise WholeProgramVMCallABIError("PZCABI401", "format mismatch")
    if (report.get("status") != WHOLE_PROGRAM_VM_CALL_ABI_STATUS or
            report.get("live") is not False):
        raise WholeProgramVMCallABIError(
            "PZCABI402", "status/live claim mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get(
            "semantic_sha256"):
        raise WholeProgramVMCallABIError(
            "PZCABI403", "semantic hash mismatch")
    if (report.get("active_call_graph_semantic_sha256") !=
            active_graph.get("semantic_sha256") or
            report.get("call_site_lowering_semantic_sha256") !=
            call_site_lowering.get("semantic_sha256")):
        raise WholeProgramVMCallABIError(
            "PZCABI404", "input semantic binding mismatch")
    for row in report.get("occurrence_abi_descriptors_in_cfg_order", ()):
        if not isinstance(row, Mapping):
            raise WholeProgramVMCallABIError(
                "PZCABI405", "occurrence ABI descriptor is malformed")
        finite = row.get("finite_dispatch_table")
        if finite is not None and (
                not isinstance(finite, Mapping) or
                finite.get("proven") is not False or
                finite.get("runtime_identity_guard_required") is not True):
            raise WholeProgramVMCallABIError(
                "PZCABI405", "finite dispatch was promoted")
    expected = _build_report(active_graph, call_site_lowering)
    if _semantic_payload(report) != _semantic_payload(expected):
        raise WholeProgramVMCallABIError(
            "PZCABI406", "call ABI differs from graph/CFG proof")


_MISSING = object()


def execute_call_binding_oracle(
        descriptor: Mapping[str, Any], values: Mapping[str, Any], *,
        defaults: Mapping[str, Any] | None = None,
        finite_target_numeric_function_id: int | None = None,
        allocated_object: Any = _MISSING,
        lexical_environment: Any = _MISSING,
        ) -> dict[str, Any]:
    """Execute only descriptor selection and argument binding semantics.

    No target function is called.  The oracle is intentionally strict: host,
    unresolved and unselected finite dispatches fail instead of guessing.
    """
    if descriptor.get("binding_mode") == "super":
        raise WholeProgramVMCallABIError(
            "PZCABI214", _BLOCKER_DETAILS["PZCABI214"])
    classification = descriptor.get("classification")
    targets = list(descriptor.get("target_descriptors", ()))
    if classification == "finite-non-proven":
        if finite_target_numeric_function_id is None:
            raise WholeProgramVMCallABIError(
                "PZCABI301", "finite dispatch requires guarded selection")
        matches = [row for row in targets if row.get("numeric_function_id") ==
                   finite_target_numeric_function_id]
        if len(matches) != 1:
            raise WholeProgramVMCallABIError(
                "PZCABI301", "finite selection is outside candidate table")
        target = matches[0]
    elif classification in {
            "proven-single-internal",
            "proven-core-generated-dataclass-init"}:
        if len(targets) != 1:
            raise WholeProgramVMCallABIError(
                "PZCABI302", "proven call does not have one target")
        target = targets[0]
    else:
        raise WholeProgramVMCallABIError(
            "PZCABI302", "host/unresolved call has no executable ABI target")

    if descriptor.get("binding_mode") == "nested" and \
            lexical_environment is _MISSING:
        raise WholeProgramVMCallABIError(
            "PZCABI303", "nested call requires lexical environment")
    if descriptor.get("binding_mode") == "constructor" and \
            allocated_object is _MISSING:
        allocated_object = {
            "oracle_allocated_for_call_site": descriptor.get(
                "numeric_call_site_id")}
    default_values = defaults or {}
    bound: dict[str, Any] = {}
    varargs: dict[str, list[Any]] = defaultdict(list)
    varkw: dict[str, dict[str, Any]] = defaultdict(dict)
    evaluation_trace: list[Any] = []
    for row in target.get("parameter_destination_map", ()):
        source_kind = row.get("source_kind")
        parameter = row.get("destination_parameter")
        destination_kind = row.get("destination_kind")
        if source_kind == "receiver":
            source_value = row.get("source_value")
            if source_value not in values:
                raise WholeProgramVMCallABIError(
                    "PZCABI304", f"receiver SSA is absent: {source_value}")
            value = values[source_value]
        elif source_kind == "allocated-object":
            value = allocated_object
        elif source_kind == "argument":
            source_value = row.get("source_value")
            if source_value not in values:
                raise WholeProgramVMCallABIError(
                    "PZCABI304", f"argument SSA is absent: {source_value}")
            value = values[source_value]
            evaluation_trace.append(source_value)
        elif source_kind == "default":
            if parameter not in default_values:
                raise WholeProgramVMCallABIError(
                    "PZCABI305", f"default value is absent: {parameter}")
            value = default_values[str(parameter)]
        elif source_kind == "literal-default":
            value = row.get("source_value")
        elif source_kind == "missing-required":
            raise WholeProgramVMCallABIError(
                "PZCABI306", f"required parameter is absent: {parameter}")
        else:
            raise WholeProgramVMCallABIError(
                "PZCABI307", "star/unknown binding is not executable")
        if destination_kind == "var-positional-item":
            varargs[str(parameter)].append(value)
        elif destination_kind == "var-keyword-item":
            varkw[str(parameter)][str(row.get("keyword"))] = value
        elif parameter is not None:
            if str(parameter) in bound:
                raise WholeProgramVMCallABIError(
                    "PZCABI306", f"parameter is bound twice: {parameter}")
            bound[str(parameter)] = value
    bound.update({name: tuple(items) for name, items in varargs.items()})
    bound.update({name: dict(items) for name, items in varkw.items()})
    return {
        "numeric_function_id": target["numeric_function_id"],
        "callable_id": target.get("callable_id"),
        "bound_parameters": bound,
        "explicit_argument_evaluation_trace": evaluation_trace,
        "lexical_environment": (None if lexical_environment is _MISSING else
                                lexical_environment),
        "allocated_object": (None if allocated_object is _MISSING else
                             allocated_object),
        "return_value": (allocated_object if descriptor.get(
            "binding_mode") == "constructor" else None),
        "generated_field_state": ({
            str(row["name"]): bound[str(row["name"])]
            for row in descriptor.get("generated_dataclass_init", {}).get(
                "fields", ())
        } if descriptor.get("binding_mode") == "generated-dataclass-init"
            else None),
        "finite_selection_was_runtime_guarded": (
            classification == "finite-non-proven"),
    }
