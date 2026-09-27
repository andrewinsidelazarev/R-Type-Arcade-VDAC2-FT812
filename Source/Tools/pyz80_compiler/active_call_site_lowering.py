"""Source-sealed lowering inventory for reachable Python call sites.

This module does not lower a call into target code.  It binds every
``python-call`` occurrence already present in the reachable callable CFGs to
the corresponding source call-site row from :mod:`active_call_graph`.  The
result is the deterministic hand-off contract a later PZVT backend can
consume without repeating Python name or receiver inference.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .active_call_graph import (
    analyze_active_call_graph,
    validate_active_call_graph_report,
)


ACTIVE_CALL_SITE_LOWERING_FORMAT = (
    "pyz80.active-call-site-lowering-inventory.v1")
ACTIVE_CALL_SITE_LOWERING_STATUS = (
    "ACTIVE_CALL_SITE_LOWERING_PLANNED_LIVE_BLOCKED")

__all__ = [
    "ACTIVE_CALL_SITE_LOWERING_FORMAT",
    "ACTIVE_CALL_SITE_LOWERING_STATUS",
    "ActiveCallSiteLoweringError",
    "analyze_active_call_site_lowering",
    "validate_active_call_site_lowering_report",
]


class ActiveCallSiteLoweringError(ValueError):
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


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(
        node, include_attributes=False).encode("utf-8"))


def _norm(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload.pop("semantic_sha256", None)
    return payload


def _dotted(expression: ast.expr) -> str | None:
    parts: list[str] = []
    cursor: ast.expr = expression
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    return ".".join(reversed(parts))


def _module_sources(
        project_root: Path, active_graph: Mapping[str, Any],
        ) -> tuple[dict[str, tuple[str, str, ast.Module]],
                   dict[str, str]]:
    result: dict[str, tuple[str, str, ast.Module]] = {}
    module_paths: dict[str, str] = {}
    for row in active_graph["source_graph"]["modules"]:
        module = str(row["module"])
        relative = _norm(str(row["path"]))
        path = project_root / relative
        source = path.read_text(encoding="utf-8")
        if _sha256(source.encode("utf-8")) != row["sha256"]:
            # ``read_bytes`` is authoritative when newline conversion could
            # matter.  The active graph validator has already checked it.
            source = path.read_bytes().decode("utf-8")
        result[module] = (relative, source, ast.parse(
            source, filename=relative, type_comments=True))
        module_paths[module] = relative
    return result, module_paths


def _parameter_row(
        argument: ast.arg, kind: str, default: ast.expr | None,
        ) -> dict[str, Any]:
    return {
        "name": argument.arg,
        "kind": kind,
        "has_default": default is not None,
        "default_ast_sha256": (
            _ast_sha256(default) if default is not None else None),
    }


def _signature_row(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    positional = list(node.args.posonlyargs) + list(node.args.args)
    default_offset = len(positional) - len(node.args.defaults)
    positional_defaults: list[ast.expr | None] = [None] * default_offset + list(
        node.args.defaults)
    parameters = [
        _parameter_row(
            argument,
            "positional-only" if index < len(node.args.posonlyargs) else
            "positional-or-keyword",
            positional_defaults[index],
        )
        for index, argument in enumerate(positional)
    ]
    if node.args.vararg is not None:
        parameters.append(_parameter_row(
            node.args.vararg, "var-positional", None))
    parameters.extend(
        _parameter_row(argument, "keyword-only", default)
        for argument, default in zip(
            node.args.kwonlyargs, node.args.kw_defaults)
    )
    if node.args.kwarg is not None:
        parameters.append(_parameter_row(
            node.args.kwarg, "var-keyword", None))
    decorators = [
        _dotted(item.func if isinstance(item, ast.Call) else item)
        for item in node.decorator_list
    ]
    return {
        "parameters": parameters,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "is_classmethod": "classmethod" in decorators,
        "is_staticmethod": "staticmethod" in decorators,
        "has_var_positional": node.args.vararg is not None,
        "has_var_keyword": node.args.kwarg is not None,
    }


def _source_indexes(
        project_root: Path, active_graph: Mapping[str, Any],
        ) -> tuple[dict[str, str], dict[str, dict[str, Any]],
                   dict[tuple[str, int, int, int, int, str], list[ast.Call]]]:
    modules, module_paths = _module_sources(project_root, active_graph)
    signatures: dict[str, dict[str, Any]] = {}
    source_calls: dict[
        tuple[str, int, int, int, int, str], list[ast.Call]
    ] = defaultdict(list)

    callable_rows = active_graph["callable_inventory"]["callables"]
    callable_keys: dict[tuple[str, int, str], list[str]] = defaultdict(list)
    for row in callable_rows:
        callable_keys[(
            str(row["module"]), int(row["definition_line"]),
            str(row["ast_sha256"]),
        )].append(str(row["callable_id"]))

    for module, (relative, source, tree) in modules.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = (module, int(node.lineno), _ast_sha256(node))
                identifiers = callable_keys.get(key, ())
                if len(identifiers) == 1:
                    signatures[identifiers[0]] = _signature_row(node)
            if isinstance(node, ast.Call):
                key = (
                    relative, int(node.lineno), int(node.col_offset),
                    int(node.end_lineno or node.lineno),
                    int(node.end_col_offset or node.col_offset + 1),
                    _ast_sha256(node),
                )
                source_calls[key].append(node)

    missing = sorted(
        str(row["callable_id"]) for row in callable_rows
        if str(row["callable_id"]) not in signatures)
    if missing:
        raise ActiveCallSiteLoweringError(
            "PZCSL003", f"{len(missing)} callable signature(s) do not "
            "match the source AST")

    # Seal call source/callee text against the parsed source.  This rejects a
    # re-signed active graph whose descriptive call fields were altered.
    callable_by_id = {
        str(row["callable_id"]): row for row in callable_rows}
    for row in active_graph["call_graph"]["call_sites"]:
        caller = str(row["caller"])
        callable_row = callable_by_id[caller]
        path = module_paths[str(callable_row["module"])]
        key = (
            path, int(row["line"]), int(row["column"]),
            int(row["end_line"]), int(row["end_column"]),
            str(row["ast_sha256"]),
        )
        matches = source_calls.get(key, ())
        if len(matches) != 1:
            raise ActiveCallSiteLoweringError(
                "PZCSL004", f"call site {row['call_site_id']} resolves to "
                f"{len(matches)} source AST calls")
        node = matches[0]
        if (ast.get_source_segment(modules[str(callable_row["module"])][1],
                                   node) != row["source"] or
                ast.get_source_segment(
                    modules[str(callable_row["module"])][1], node.func) !=
                row["callee_source"]):
            raise ActiveCallSiteLoweringError(
                "PZCSL004", f"call site {row['call_site_id']} source text "
                "does not match its source AST")
    return module_paths, signatures, source_calls


def _walk_python_calls(
        value: Any, path: tuple[str | int, ...] = (),
        ) -> Iterable[tuple[tuple[str | int, ...], Mapping[str, Any]]]:
    """Walk one CFG JSON tree in its emitted order."""
    if isinstance(value, Mapping):
        if value.get("op") == "python-call":
            yield path, value
            return
        for key, nested in value.items():
            yield from _walk_python_calls(nested, path + (str(key),))
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_python_calls(nested, path + (index,))


def _path_context(
        cfg: Mapping[str, Any], path: tuple[str | int, ...],
        ) -> tuple[str | None, str | None]:
    program_id: str | None = None
    block_name: str | None = None
    for index, item in enumerate(path):
        if (item == "expression_programs" and index + 1 < len(path) and
                isinstance(path[index + 1], int)):
            program_index = int(path[index + 1])
            programs = cfg.get("expression_programs", [])
            if 0 <= program_index < len(programs):
                program_id = str(programs[program_index].get("program_id"))
        if (item == "blocks" and index + 1 < len(path) and
                isinstance(path[index + 1], int)):
            block_index = int(path[index + 1])
            if program_id is None:
                blocks = cfg.get("blocks", [])
            else:
                program_index = int(path[path.index("expression_programs") + 1])
                blocks = cfg.get("expression_programs", [])[program_index].get(
                    "blocks", [])
            if 0 <= block_index < len(blocks):
                block_name = str(blocks[block_index].get(
                    "name", blocks[block_index].get("block_id", block_index)))
    return program_id, block_name


def _layout_rows(instruction: Mapping[str, Any]) -> list[dict[str, Any]]:
    attributes = instruction.get("attributes")
    arguments = instruction.get("arguments")
    if not isinstance(attributes, Mapping) or not isinstance(arguments, list):
        raise ActiveCallSiteLoweringError(
            "PZCSL005", "python-call instruction has malformed operands")
    raw_layout = attributes.get("argument_layout")
    argument_count = attributes.get("argument_count")
    if (not isinstance(raw_layout, (list, tuple)) or
            not isinstance(argument_count, int) or
            argument_count != len(raw_layout) or
            len(arguments) != argument_count + 1):
        raise ActiveCallSiteLoweringError(
            "PZCSL005", "python-call argument layout/count mismatch")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw_layout):
        if (not isinstance(item, (list, tuple)) or len(item) != 2 or
                item[0] not in {
                    "positional", "keyword", "star-positional",
                    "star-keyword",
                } or
                (item[0] == "keyword" and not isinstance(item[1], str))):
            raise ActiveCallSiteLoweringError(
                "PZCSL005", "python-call argument layout entry malformed")
        result.append({
            "argument_index": index,
            "kind": str(item[0]),
            "keyword": item[1],
            "value": arguments[index + 1],
        })
    return result


def _classification(resolution: Mapping[str, Any]) -> str:
    kind = str(resolution["kind"])
    targets = resolution["targets"]
    if (kind == "exact-generated-dataclass-init" and
            resolution["proven"] is True):
        return "proven-core-generated-dataclass-init"
    if resolution["proven"] is True and len(targets) == 1:
        return "proven-single-internal"
    if kind == "finite-dynamic-dispatch":
        return "finite-non-proven"
    if kind == "host-boundary":
        return "host-boundary"
    if kind.startswith("unresolved-"):
        return "unresolved"
    return "invalid-proven-target-arity"


def _call_node_from_source(source: str) -> ast.Call | None:
    try:
        expression = ast.parse(source, mode="eval").body
    except SyntaxError:
        return None
    return expression if isinstance(expression, ast.Call) else None


def _binding_mode(
        call_site: Mapping[str, Any],
        signatures: Mapping[str, Mapping[str, Any]],
        ) -> str:
    resolution = call_site["resolution"]
    kind = str(resolution["kind"])
    if kind == "exact-generated-dataclass-init":
        return "generated-dataclass-init"
    if kind == "exact-internal-constructor" or "constructed_class" in resolution:
        return "constructor"
    if kind == "exact-super-method" or str(
            call_site["callee_source"]).startswith("super("):
        return "super"
    if kind == "exact-common-dispatch":
        return "common-dispatch"
    if kind == "exact-nested-function":
        return "nested"
    if kind == "exact-internal-class-method" and len(
            resolution["targets"]) == 1:
        signature = signatures.get(str(resolution["targets"][0]), {})
        return "bound-method" if signature.get("is_classmethod") else "free"
    if kind == "exact-internal-method":
        return "bound-method"
    node = _call_node_from_source(str(call_site["source"]))
    if node is not None and isinstance(node.func, ast.Attribute):
        return "bound-method"
    return "free"


def _target_argument_plan(
        target: str, signature: Mapping[str, Any], binding_mode: str,
        layout: list[dict[str, Any]],
        ) -> dict[str, Any]:
    parameters = list(signature["parameters"])
    positional = [row for row in parameters if row["kind"] in {
        "positional-only", "positional-or-keyword"}]
    implicit_count = 1 if binding_mode in {
        "bound-method", "constructor", "super", "common-dispatch",
        "generated-dataclass-init"} else 0
    if signature.get("is_staticmethod"):
        implicit_count = 0
    implicit_parameters = [row["name"] for row in positional[:implicit_count]]
    available = positional[implicit_count:]
    star_positional = any(row["kind"] == "star-positional" for row in layout)
    star_keyword = any(row["kind"] == "star-keyword" for row in layout)
    if star_positional or star_keyword:
        return {
            "target": target,
            "implicit_parameters": implicit_parameters,
            "binding_is_static": False,
            "runtime_star_binding_required": True,
            "defaulted_parameters": [],
            "missing_required_parameters": [],
            "unexpected_keywords": [],
            "duplicate_parameters": [],
        }

    provided: set[str] = set()
    duplicate: set[str] = set()
    positional_values = [row for row in layout if row["kind"] == "positional"]
    extra_positional = max(0, len(positional_values) - len(available))
    for row in available[:len(positional_values)]:
        provided.add(str(row["name"]))
    keyword_names = [str(row["keyword"]) for row in layout
                     if row["kind"] == "keyword"]
    by_name = {str(row["name"]): row for row in parameters}
    unexpected: list[str] = []
    has_var_keyword = bool(signature.get("has_var_keyword"))
    for name in keyword_names:
        parameter = by_name.get(name)
        if parameter is None:
            if not has_var_keyword:
                unexpected.append(name)
            continue
        if parameter["kind"] == "positional-only":
            unexpected.append(name)
            continue
        if name in provided:
            duplicate.add(name)
        provided.add(name)
    bindable = [row for row in parameters if row["kind"] not in {
        "var-positional", "var-keyword"}]
    bindable = [row for row in bindable
                if row["name"] not in implicit_parameters]
    defaulted = sorted(
        str(row["name"]) for row in bindable
        if row["name"] not in provided and row["has_default"])
    missing = sorted(
        str(row["name"]) for row in bindable
        if row["name"] not in provided and not row["has_default"])
    if extra_positional and not signature.get("has_var_positional"):
        missing.append(f"<extra-positional:{extra_positional}>")
    return {
        "target": target,
        "implicit_parameters": implicit_parameters,
        "binding_is_static": True,
        "runtime_star_binding_required": False,
        "defaulted_parameters": defaulted,
        "missing_required_parameters": missing,
        "unexpected_keywords": sorted(unexpected),
        "duplicate_parameters": sorted(duplicate),
    }


def _obligations(
        call_site: Mapping[str, Any], binding_mode: str,
        layouts: list[list[dict[str, Any]]],
        signatures: Mapping[str, Mapping[str, Any]],
        ) -> dict[str, Any]:
    canonical_layout = layouts[0] if layouts else []
    layout_hashes = sorted({_json_sha256(layout) for layout in layouts})
    resolution = call_site["resolution"]
    targets = [str(item) for item in resolution["targets"]]
    if binding_mode == "generated-dataclass-init":
        schema = resolution.get("generated_dataclass_init", {})
        signature = {
            "parameters": list(schema.get("parameters", ())),
            "is_staticmethod": False,
            "has_var_positional": False,
            "has_var_keyword": False,
        }
        target_plans = [_target_argument_plan(
            str(schema.get("class_id", "<generated-dataclass-init>")),
            signature, binding_mode, canonical_layout)]
    else:
        target_plans = [
            _target_argument_plan(
                target, signatures[target], binding_mode, canonical_layout)
            for target in targets if target in signatures
        ]
    keyword_names = [row["keyword"] for row in canonical_layout
                     if row["kind"] == "keyword"]
    star_kinds = sorted({row["kind"] for row in canonical_layout
                         if row["kind"].startswith("star-")})
    return {
        "implicit_receiver_binding": binding_mode in {
            "bound-method", "super", "common-dispatch",
            "generated-dataclass-init"},
        "nested_closure_binding": binding_mode == "nested",
        "constructor_allocation": binding_mode == "constructor",
        "constructor_init_receiver_binding": binding_mode == "constructor",
        "default_argument_binding": {
            "mode": ("per-source-target-signature" if target_plans else
                     "runtime-signature-unknown"),
            "target_plans": target_plans,
            "required": (not target_plans or any(
                row["defaulted_parameters"] or
                row["runtime_star_binding_required"]
                for row in target_plans)),
        },
        "keyword_binding": {
            "required": bool(keyword_names) or "star-keyword" in star_kinds,
            "names_in_evaluation_order": keyword_names,
        },
        "star_argument_expansion": {
            "required": bool(star_kinds),
            "kinds": star_kinds,
        },
        "cfg_layout_variant_count": len(layout_hashes),
        "cfg_layout_semantic_sha256": layout_hashes,
    }


def _site_blockers(
        classification: str, obligations: Mapping[str, Any],
        represented: bool,
        ) -> list[str]:
    result: list[str] = []
    if classification == "finite-non-proven":
        result.append("PZCSL201")
    elif classification == "host-boundary":
        result.append("PZCSL202")
    elif classification in {"unresolved", "invalid-proven-target-arity"}:
        result.append("PZCSL203")
    if not represented:
        result.append("PZCSL204")
    if obligations["implicit_receiver_binding"]:
        result.append("PZCSL205")
    if obligations["constructor_allocation"]:
        result.append("PZCSL206")
    if obligations["default_argument_binding"]["required"]:
        result.append("PZCSL207")
    if obligations["keyword_binding"]["required"]:
        result.append("PZCSL208")
    if obligations["star_argument_expansion"]["required"]:
        result.append("PZCSL209")
    return result


_BLOCKER_DETAILS = {
    "PZCSL201": "finite non-proven dispatch requires runtime selection",
    "PZCSL202": "host boundary requires an explicit target adapter",
    "PZCSL203": "callable identity is unresolved or has invalid target arity",
    "PZCSL204": "reachable graph call has no CFG python-call occurrence",
    "PZCSL205": "bound receiver injection is not implemented by a backend",
    "PZCSL206": "constructor allocation/init sequencing is not implemented",
    "PZCSL207": "default argument binding is not implemented",
    "PZCSL208": "keyword argument binding is not implemented",
    "PZCSL209": "star argument expansion is not implemented",
    "PZCSL210": "no PZVT backend consumes this lowering inventory",
}


def _site_source_key(
        row: Mapping[str, Any], path: str,
        ) -> tuple[Any, ...]:
    return (
        path, int(row["line"]), int(row["column"]),
        int(row["end_line"]), int(row["end_column"]),
        str(row["caller"]), str(row["call_site_id"]),
    )


def _build_report(
        project_root: Path, active_graph: Mapping[str, Any],
        ) -> dict[str, Any]:
    module_paths, signatures, _source_calls = _source_indexes(
        project_root, active_graph)
    callable_rows = {
        str(row["callable_id"]): row
        for row in active_graph["callable_inventory"]["callables"]
    }
    reachable = [str(item) for item in
                 active_graph["call_graph"]["proven_reachable_callable_ids"]]
    reachable_set = set(reachable)
    graph_sites = [
        row for row in active_graph["call_graph"]["call_sites"]
        if str(row["caller"]) in reachable_set
    ]

    graph_by_key: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(
        list)
    source_sorted: list[tuple[tuple[Any, ...], Mapping[str, Any]]] = []
    for row in graph_sites:
        callable_row = callable_rows[str(row["caller"])]
        path = module_paths[str(callable_row["module"])]
        key = (
            str(row["caller"]), path, int(row["line"]), int(row["column"]),
            int(row["end_line"]), int(row["end_column"]),
        )
        graph_by_key[key].append(row)
        source_sorted.append((_site_source_key(row, path), row))
    source_sorted.sort(key=lambda item: item[0])
    if len(source_sorted) > 0xFFFF:
        raise ActiveCallSiteLoweringError(
            "PZCSL006", "reachable call-site count exceeds 16-bit PZVT id")
    numeric_ids = {
        str(row["call_site_id"]): index
        for index, (_key, row) in enumerate(source_sorted, start=1)
    }

    occurrences: list[dict[str, Any]] = []
    occurrences_by_site: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for caller in reachable:
        callable_row = callable_rows[caller]
        cfg = callable_row.get("cfg")
        if cfg is None:
            continue
        if not isinstance(cfg, Mapping):
            raise ActiveCallSiteLoweringError(
                "PZCSL005", f"CFG for {caller} is malformed")
        expected_path = module_paths[str(callable_row["module"])]
        for cfg_path, instruction in _walk_python_calls(cfg):
            span = instruction.get("span")
            if not isinstance(span, Mapping):
                raise ActiveCallSiteLoweringError(
                    "PZCSL005", "python-call span is malformed")
            key = (
                caller, _norm(str(span.get("path", ""))),
                int(span.get("line", -1)), int(span.get("column", -1)),
                int(span.get("end_line", -1)),
                int(span.get("end_column", -1)),
            )
            if key[1] != expected_path:
                raise ActiveCallSiteLoweringError(
                    "PZCSL005", f"python-call path {key[1]} does not match "
                    f"callable source {expected_path}")
            matches = graph_by_key.get(key, ())
            if len(matches) != 1:
                raise ActiveCallSiteLoweringError(
                    "PZCSL007", f"CFG python-call {caller}:{key[2]}:{key[3]} "
                    f"matches {len(matches)} active graph call sites")
            call_site = matches[0]
            layout = _layout_rows(instruction)
            program_id, block_name = _path_context(cfg, cfg_path)
            occurrence = {
                "cfg_occurrence_index": len(occurrences),
                "numeric_call_site_id": numeric_ids[str(
                    call_site["call_site_id"])],
                "call_site_id": str(call_site["call_site_id"]),
                "caller": caller,
                "cfg_path": [item for item in cfg_path],
                "program_id": program_id,
                "block_name": block_name,
                "instruction_sequence": int(instruction.get("sequence", -1)),
                "span": {
                    "path": key[1], "line": key[2], "column": key[3],
                    "end_line": key[4], "end_column": key[5],
                },
                "callable_value": instruction["arguments"][0],
                "argument_layout": layout,
                "destination": instruction.get("destination"),
                "evaluation_order": instruction["attributes"].get(
                    "evaluation_order"),
            }
            occurrences.append(occurrence)
            occurrences_by_site[str(call_site["call_site_id"])].append(
                occurrence)

    represented_sites: list[dict[str, Any]] = []
    unrepresented_sites: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    for source_order_index, (source_key, call_site) in enumerate(source_sorted):
        site_id = str(call_site["call_site_id"])
        site_occurrences = occurrences_by_site.get(site_id, [])
        classification = _classification(call_site["resolution"])
        mode = _binding_mode(call_site, signatures)
        layouts = [row["argument_layout"] for row in site_occurrences]
        obligations = _obligations(
            call_site, mode, layouts, signatures)
        blockers = _site_blockers(
            classification, obligations, bool(site_occurrences))
        blocker_counts.update(blockers)
        common = {
            "source_order_index": source_order_index,
            "numeric_call_site_id": numeric_ids[site_id],
            "call_site_id": site_id,
            "caller": str(call_site["caller"]),
            "span": {
                "path": source_key[0],
                "line": int(call_site["line"]),
                "column": int(call_site["column"]),
                "end_line": int(call_site["end_line"]),
                "end_column": int(call_site["end_column"]),
            },
            "source": str(call_site["source"]),
            "callee_source": str(call_site["callee_source"]),
            "classification": classification,
            "binding_mode": mode,
            "resolution_kind": str(call_site["resolution"]["kind"]),
            "proven": bool(call_site["resolution"]["proven"]),
            "targets": list(call_site["resolution"]["targets"]),
            "resolution_evidence": str(
                call_site["resolution"].get("evidence", "")),
            "boundary": call_site["resolution"].get("boundary"),
            "external_target": call_site["resolution"].get(
                "external_target"),
            "generated_dataclass_init": call_site["resolution"].get(
                "generated_dataclass_init"),
            "receiver_parameter": call_site["resolution"].get(
                "receiver_parameter"),
            "obligations": obligations,
            "blocker_codes": blockers,
        }
        if site_occurrences:
            common.update({
                "cfg_occurrence_count": len(site_occurrences),
                "cfg_occurrence_indexes": [
                    row["cfg_occurrence_index"] for row in site_occurrences],
            })
            represented_sites.append(common)
        else:
            node = _call_node_from_source(str(call_site["source"]))
            common.update({
                "reason": "no reachable CFG python-call has this full span",
                "source_argument_layout": ([
                    ["star-positional" if isinstance(argument, ast.Starred)
                     else "positional", None]
                    for argument in node.args
                ] + [
                    ["keyword" if keyword.arg is not None else
                     "star-keyword", keyword.arg]
                    for keyword in node.keywords
                ] if node is not None else None),
            })
            unrepresented_sites.append(common)

    duplicates = {
        site_id: rows for site_id, rows in occurrences_by_site.items()
        if len(rows) > 1
    }
    classification_counts = Counter(
        row["classification"]
        for row in represented_sites + unrepresented_sites)
    live_blockers = [{
        "code": code,
        "count": int(count),
        "detail": _BLOCKER_DETAILS[code],
    } for code, count in sorted(blocker_counts.items())]
    live_blockers.append({
        "code": "PZCSL210", "count": 1,
        "detail": _BLOCKER_DETAILS["PZCSL210"],
    })

    report: dict[str, Any] = {
        "format": ACTIVE_CALL_SITE_LOWERING_FORMAT,
        "status": ACTIVE_CALL_SITE_LOWERING_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": active_graph["semantic_sha256"],
        "entrypoint": active_graph["entrypoint"],
        "numeric_id_contract": {
            "width_bits": 16,
            "zero_is_reserved": True,
            "first_assigned_id": 1 if source_sorted else None,
            "highest_assigned_id": len(source_sorted),
            "assignment_order": (
                "source-path,line,column,end-line,end-column,caller,"
                "graph-call-site-id"),
            "duplicate_cfg_occurrences_share_numeric_id": True,
        },
        "mapping": {
            "reachable_callable_count": len(reachable),
            "reachable_graph_call_site_count": len(graph_sites),
            "represented_graph_call_site_count": len(represented_sites),
            "unrepresented_graph_call_site_count": len(unrepresented_sites),
            "cfg_python_call_occurrence_count": len(occurrences),
            "unique_mapped_call_site_count": len(occurrences_by_site),
            "duplicate_cfg_occurrence_count": sum(
                len(rows) - 1 for rows in duplicates.values()),
            "call_sites_with_duplicate_cfg_occurrences": len(duplicates),
            "missing_cfg_to_graph_match_count": 0,
            "ambiguous_cfg_to_graph_match_count": 0,
            "classification_counts": dict(sorted(
                classification_counts.items())),
        },
        "sites_in_source_order": represented_sites,
        "cfg_occurrences_in_cfg_order": occurrences,
        "unrepresented_graph_sites_in_source_order": unrepresented_sites,
        "target_signatures": {
            target: signatures[target]
            for target in sorted({
                str(target)
                for row in represented_sites + unrepresented_sites
                for target in row["targets"]
            })
        },
        "blocker_site_counts": dict(sorted(blocker_counts.items())),
        "live_blockers": live_blockers,
        "proof": {
            "active_call_graph_validated_in_memory": True,
            "cfg_mapping_uses_caller_and_full_source_span": True,
            "every_reachable_cfg_python_call_maps_exactly_once": True,
            "duplicate_cfg_occurrences_share_graph_and_numeric_site_id": True,
            "finite_candidates_never_become_proven": True,
            "source_and_cfg_orders_are_preserved_separately": True,
            "unrepresented_graph_sites_are_not_hidden": True,
            "argument_layout_is_copied_from_cfg_without_reordering": True,
            "backend_consumer_bound": False,
        },
    }
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    return report


def analyze_active_call_site_lowering(
        project_root: Path | str, *,
        active_graph: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    """Build and validate the reachable call-site lowering inventory."""
    root = Path(project_root).resolve()
    graph = (analyze_active_call_graph(root)
             if active_graph is None else active_graph)
    validate_active_call_graph_report(root, graph)
    report = _build_report(root, graph)
    validate_active_call_site_lowering_report(
        root, report, active_graph=graph)
    return report


def validate_active_call_site_lowering_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        active_graph: Mapping[str, Any],
        ) -> None:
    """Reject stale, reordered or promoted lowering claims fail-closed."""
    root = Path(project_root).resolve()
    validate_active_call_graph_report(root, active_graph)
    if report.get("format") != ACTIVE_CALL_SITE_LOWERING_FORMAT:
        raise ActiveCallSiteLoweringError("PZCSL401", "format mismatch")
    if (report.get("status") != ACTIVE_CALL_SITE_LOWERING_STATUS or
            report.get("live") is not False):
        raise ActiveCallSiteLoweringError(
            "PZCSL402", "status/live claim mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get(
            "semantic_sha256"):
        raise ActiveCallSiteLoweringError(
            "PZCSL403", "semantic hash mismatch")
    if report.get("active_call_graph_semantic_sha256") != active_graph.get(
            "semantic_sha256"):
        raise ActiveCallSiteLoweringError(
            "PZCSL404", "active call graph binding mismatch")
    for row in (list(report.get("sites_in_source_order", ())) +
                list(report.get(
                    "unrepresented_graph_sites_in_source_order", ()))):
        if not isinstance(row, Mapping):
            raise ActiveCallSiteLoweringError(
                "PZCSL405", "call-site row is malformed")
        if (row.get("classification") == "finite-non-proven" and
                (row.get("proven") is not False or not row.get("targets"))):
            raise ActiveCallSiteLoweringError(
                "PZCSL405", "finite dispatch was promoted or lost targets")
        if (row.get("classification") == "proven-single-internal" and
                (row.get("proven") is not True or
                 len(row.get("targets", ())) != 1)):
            raise ActiveCallSiteLoweringError(
                "PZCSL405", "proven single-target classification mismatch")
    expected = _build_report(root, active_graph)
    if _semantic_payload(report) != _semantic_payload(expected):
        raise ActiveCallSiteLoweringError(
            "PZCSL406", "lowering inventory differs from source/CFG proof")
