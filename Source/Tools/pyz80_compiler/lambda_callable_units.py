"""Source-sealed callable units for lambdas found by callable-value flow.

This layer deliberately stops before reachability or runtime integration.  It
turns each exact lambda value inventoried by :mod:`active_callable_flow` into
a target-neutral signature/closure/body-SSA contract.  Non-lambda callable
values remain references to their already existing callable identities.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import inspect
import json
import operator
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .active_call_graph import (
    analyze_active_call_graph,
    validate_active_call_graph_report,
)
from .active_callable_flow import (
    analyze_active_callable_flow,
    validate_active_callable_flow_report,
)
from .frontend import lower_object_expression


LAMBDA_CALLABLE_UNITS_FORMAT = "pyz80.lambda-callable-units.v1"
LAMBDA_CALLABLE_UNITS_STATUS = (
    "LAMBDA_CALLABLE_UNITS_MATERIALIZED_LIVE_BLOCKED")
LAMBDA_CALLABLE_UNITS_ENCODING_MAGIC = b"PZLU"
LAMBDA_CALLABLE_UNITS_ENCODING_VERSION = 1

_ENCODING_HEADER = struct.Struct("<4sHHI32s")

__all__ = [
    "LAMBDA_CALLABLE_UNITS_FORMAT",
    "LAMBDA_CALLABLE_UNITS_STATUS",
    "LAMBDA_CALLABLE_UNITS_ENCODING_MAGIC",
    "LAMBDA_CALLABLE_UNITS_ENCODING_VERSION",
    "LambdaCallableUnitError",
    "analyze_lambda_callable_units",
    "validate_lambda_callable_units_report",
    "encode_lambda_callable_units",
    "decode_lambda_callable_units",
    "evaluate_lambda_definition_defaults_oracle",
    "bind_lambda_call_oracle",
    "execute_lambda_unit_oracle",
]


class LambdaCallableUnitError(ValueError):
    """Fail-closed diagnostic for callable-unit analysis and its oracle."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_sha256(value: object) -> str:
    return _sha256(_json_bytes(value))


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(
        node, include_attributes=False).encode("utf-8"))


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload.pop("semantic_sha256", None)
    return payload


def _norm(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _span(path: str, node: ast.AST) -> dict[str, Any]:
    return {
        "path": path,
        "line": int(getattr(node, "lineno", 0)),
        "column": int(getattr(node, "col_offset", 0)),
        "end_line": int(getattr(node, "end_lineno", 0) or
                        getattr(node, "lineno", 0)),
        "end_column": int(getattr(node, "end_col_offset", 0) or
                          getattr(node, "col_offset", 0) + 1),
    }


def _source_segment(source_text: str, node: ast.AST) -> str:
    return ast.get_source_segment(source_text, node) or ast.unparse(node)


def _parameter_nodes(arguments: ast.arguments) -> list[
        tuple[ast.arg, str, ast.expr | None]]:
    positional = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [
        None] * (len(positional) - len(arguments.defaults)) + list(
            arguments.defaults)
    rows: list[tuple[ast.arg, str, ast.expr | None]] = []
    for index, (argument, default) in enumerate(zip(
            positional, positional_defaults)):
        rows.append((
            argument,
            "positional-only" if index < len(arguments.posonlyargs)
            else "positional-or-keyword",
            default,
        ))
    if arguments.vararg is not None:
        rows.append((arguments.vararg, "var-positional", None))
    rows.extend((argument, "keyword-only", default)
                for argument, default in zip(
                    arguments.kwonlyargs, arguments.kw_defaults))
    if arguments.kwarg is not None:
        rows.append((arguments.kwarg, "var-keyword", None))
    return rows


def _captured_names(node: ast.Lambda) -> list[str]:
    parameters = {argument.arg for argument, _, _ in _parameter_nodes(
        node.args)}
    loaded = {item.id for item in ast.walk(node.body)
              if isinstance(item, ast.Name) and
              isinstance(item.ctx, ast.Load)}
    return sorted(loaded - parameters - set(dir(builtins)))


def _signature_descriptor(
        node: ast.Lambda, *, source_path: str, source_text: str,
        callable_id: str,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    default_rows: list[dict[str, Any]] = []
    default_index = 0
    for argument, kind, default in _parameter_nodes(node.args):
        descriptor = {
            "name": argument.arg,
            "kind": kind,
            "span": _span(source_path, argument),
            "has_default": default is not None,
            "default_ast_sha256": (_ast_sha256(default)
                                   if default is not None else None),
        }
        parameters.append(descriptor)
        if default is None:
            continue
        program_id = f"{callable_id}:default:{default_index:03d}"
        program = lower_object_expression(
            default, source_path=Path(source_path), source_text=source_text,
            program_id=program_id)
        default_rows.append({
            "evaluation_index": default_index,
            "parameter": argument.arg,
            "parameter_kind": kind,
            "source": _source_segment(source_text, default),
            "span": _span(source_path, default),
            "ast_sha256": _ast_sha256(default),
            "expression_cfg": program.to_json(),
            "evaluate_in": "lexical-owner-environment",
            "store_value_in_callable_object": True,
            "reevaluate_at_call_time": False,
        })
        default_index += 1

    signature = {
        "parameters": parameters,
        "positional_only_count": len(node.args.posonlyargs),
        "positional_or_keyword_count": len(node.args.args),
        "keyword_only_count": len(node.args.kwonlyargs),
        "var_positional_parameter": (
            node.args.vararg.arg if node.args.vararg is not None else None),
        "var_keyword_parameter": (
            node.args.kwarg.arg if node.args.kwarg is not None else None),
        "argument_binding": "python-signature-exact",
    }
    defaults = {
        "phase": "callable-definition",
        "evaluation_order": (
            "positional-defaults-left-to-right-then-keyword-only-"
            "defaults-left-to-right"),
        "entries": default_rows,
        "evaluated_value_storage_required": bool(default_rows),
        "call_time_reevaluation_forbidden": True,
    }
    return signature, defaults


def _lambda_identity(flow_unit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "lambda-callable",
        "source_callable_value_id": str(flow_unit["callable_value_id"]),
        "module": str(flow_unit["module"]),
        "lexical_owner": str(flow_unit["lexical_owner"]),
        "span": dict(flow_unit["span"]),
        "ast_sha256": str(flow_unit["ast_sha256"]),
    }


def _find_exact_lambda(
        root: Path, flow_unit: Mapping[str, Any],
        source_cache: dict[str, tuple[str, ast.Module]],
        ) -> tuple[ast.Lambda, str, str]:
    span = flow_unit.get("span")
    if not isinstance(span, Mapping):
        raise LambdaCallableUnitError("PZLCU401", "lambda span is absent")
    relative_path = _norm(str(span.get("path", "")))
    candidate = (root / Path(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise LambdaCallableUnitError(
            "PZLCU401", f"lambda path escapes project root: {relative_path}") \
            from error
    if not candidate.is_file():
        raise LambdaCallableUnitError(
            "PZLCU401", f"lambda source is absent: {relative_path}")
    if relative_path not in source_cache:
        source_text = candidate.read_text(encoding="utf-8")
        source_cache[relative_path] = (
            source_text,
            ast.parse(source_text, filename=relative_path, type_comments=True),
        )
    source_text, tree = source_cache[relative_path]
    coordinate = (
        int(span.get("line", -1)), int(span.get("column", -1)),
        int(span.get("end_line", -1)), int(span.get("end_column", -1)),
    )
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)
               and (node.lineno, node.col_offset, node.end_lineno,
                    node.end_col_offset) == coordinate]
    if len(matches) != 1:
        raise LambdaCallableUnitError(
            "PZLCU402", f"lambda span resolves to {len(matches)} AST nodes")
    node = matches[0]
    if _ast_sha256(node) != flow_unit.get("ast_sha256"):
        raise LambdaCallableUnitError(
            "PZLCU403", "lambda AST differs from callable-flow proof")
    return node, source_text, relative_path


def _materialize_lambda_node(
        node: ast.Lambda, *, source_text: str, source_path: str,
        flow_unit: Mapping[str, Any], numeric_id: int,
        ) -> dict[str, Any]:
    identity = _lambda_identity(flow_unit)
    callable_id = "lambda-callable:" + _json_sha256(identity)
    if _span(source_path, node) != identity["span"]:
        raise LambdaCallableUnitError(
            "PZLCU402", "materialized lambda span differs from flow unit")
    if _ast_sha256(node) != identity["ast_sha256"]:
        raise LambdaCallableUnitError(
            "PZLCU403", "materialized lambda AST differs from flow unit")
    captured_names = _captured_names(node)
    flow_closure = flow_unit.get("closure", {})
    if (not isinstance(flow_closure, Mapping) or
            captured_names != list(flow_closure.get("captured_names", ())) or
            flow_closure.get("lexical_owner") != identity["lexical_owner"]):
        raise LambdaCallableUnitError(
            "PZLCU404", "lambda closure differs from callable-flow proof")

    signature, default_evaluation = _signature_descriptor(
        node, source_path=source_path, source_text=source_text,
        callable_id=callable_id)
    flow_signature = flow_unit.get("signature", {})
    if [
        {key: row[key] for key in (
            "name", "kind", "has_default", "default_ast_sha256")}
        for row in signature["parameters"]
    ] != list(flow_signature.get("parameters", ())):
        raise LambdaCallableUnitError(
            "PZLCU405", "lambda signature differs from callable-flow proof")

    body_program = lower_object_expression(
        node.body, source_path=Path(source_path), source_text=source_text,
        program_id=f"{callable_id}:body")
    body_ops = [instruction["op"]
                for block in body_program.to_json()["blocks"]
                for instruction in block["instructions"]]
    protocol_ops = sorted({op for op in body_ops if (
        op.startswith("python-") or op in {
            "load-attribute", "load-subscript", "require-callable"})})
    blockers = ["PZLCU201"]
    if captured_names:
        blockers.append("PZLCU202")
    if default_evaluation["entries"]:
        blockers.append("PZLCU203")
    if protocol_ops:
        blockers.append("PZLCU204")
    return {
        "numeric_lambda_callable_id": numeric_id,
        "lambda_callable_id": callable_id,
        **identity,
        "source_file_sha256": _sha256(source_text.encode("utf-8")),
        "source": _source_segment(source_text, node),
        "signature": signature,
        "definition_time_default_evaluation": default_evaluation,
        "closure": {
            "lexical_owner": identity["lexical_owner"],
            "captured_names": captured_names,
            "capture_at_definition": "cell-identity-by-name",
            "captured_values_are_late_bound": True,
            "unbound_capture_is_fatal": True,
        },
        "body": {
            "source": _source_segment(source_text, node.body),
            "span": _span(source_path, node.body),
            "ast_sha256": _ast_sha256(node.body),
            "expression_cfg": body_program.to_json(),
            "protocol_operations": protocol_ops,
        },
        "return_semantics": {
            "kind": "return-expression-result",
            "body_evaluated_once_per_call": True,
            "result_returned_without_coercion": True,
            "exceptions_propagate": True,
            "implicit_none_only_if_body_result_is_none": True,
        },
        "callable_unit_materialized": True,
        "graph_reachability_edge": False,
        "runtime_integrated": False,
        "blocker_codes": sorted(blockers),
    }


def _build_report(
        root: Path, active_graph: Mapping[str, Any],
        callable_flow: Mapping[str, Any],
        ) -> dict[str, Any]:
    source_cache: dict[str, tuple[str, ast.Module]] = {}
    flow_units = list(callable_flow[
        "callable_value_units_in_source_order"])
    lambda_flow_units = [row for row in flow_units
                         if row.get("kind") == "lambda"]
    lambda_flow_units.sort(key=lambda row: (
        str(row["span"]["path"]), int(row["span"]["line"]),
        int(row["span"]["column"]), str(row["callable_value_id"])))
    units: list[dict[str, Any]] = []
    for numeric_id, flow_unit in enumerate(lambda_flow_units, start=1):
        node, source_text, source_path = _find_exact_lambda(
            root, flow_unit, source_cache)
        units.append(_materialize_lambda_node(
            node, source_text=source_text, source_path=source_path,
            flow_unit=flow_unit, numeric_id=numeric_id))

    nonlambda = [row for row in flow_units if row.get("kind") != "lambda"]
    nonlambda.sort(key=lambda row: (
        str(row["span"]["path"]), int(row["span"]["line"]),
        int(row["span"]["column"]), str(row["callable_value_id"])))
    references = [{
        "numeric_existing_callable_reference_id": index,
        "source_callable_value_id": str(row["callable_value_id"]),
        "kind": str(row["kind"]),
        "target_callable_id": row.get("target_callable_id"),
        "expression_owner": row.get("expression_owner"),
        "span": dict(row["span"]),
        "receiver_proof": row.get("receiver_proof"),
        "signature": row.get("signature"),
        "materialized_as_lambda": False,
        "graph_reachability_edge": False,
        "runtime_integrated": False,
        "blocker_codes": ["PZLCU205"],
    } for index, row in enumerate(nonlambda, start=1)]

    blocker_counts: Counter[str] = Counter()
    for row in units:
        blocker_counts.update(row["blocker_codes"])
    for row in references:
        blocker_counts.update(row["blocker_codes"])
    blocker_counts["PZLCU206"] += 1
    body_op_counts = Counter(
        instruction["op"] for row in units
        for block in row["body"]["expression_cfg"]["blocks"]
        for instruction in block["instructions"])
    site_candidates = {
        str(candidate)
        for site in callable_flow["unresolved_local_sites_in_source_order"]
        for candidate in site["candidate_callable_value_ids"]
    }
    materialized_source_ids = {
        str(row["source_callable_value_id"]) for row in units}
    referenced_source_ids = {
        str(row["source_callable_value_id"]) for row in references}
    if not site_candidates.issubset(
            materialized_source_ids | referenced_source_ids):
        raise LambdaCallableUnitError(
            "PZLCU406", "callable-flow candidate lacks unit/reference")

    blocker_detail = {
        "PZLCU201": (
            "materialized lambda is deliberately not a graph reachability "
            "edge or runtime callable"),
        "PZLCU202": (
            "closure cell identity/storage must be bound by a later runtime"),
        "PZLCU203": (
            "definition-time default evaluation/storage needs a later runtime"),
        "PZLCU204": (
            "body retains target-neutral Python protocol operations"),
        "PZLCU205": (
            "non-lambda callable value remains an existing-callable reference"),
        "PZLCU206": (
            "active graph/backend does not consume lambda callable units"),
    }
    report: dict[str, Any] = {
        "format": LAMBDA_CALLABLE_UNITS_FORMAT,
        "status": LAMBDA_CALLABLE_UNITS_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": active_graph["semantic_sha256"],
        "active_callable_flow_semantic_sha256": callable_flow[
            "semantic_sha256"],
        "census": {
            "flow_lambda_candidate_unit_count": len(lambda_flow_units),
            "materialized_lambda_callable_unit_count": len(units),
            "existing_callable_reference_count": len(references),
            "default_expression_count": sum(len(row[
                "definition_time_default_evaluation"]["entries"])
                for row in units),
            "captured_name_reference_count": sum(len(row[
                "closure"]["captured_names"]) for row in units),
            "lambda_body_operation_counts": dict(sorted(
                body_op_counts.items())),
            "callable_flow_candidate_reference_count": sum(
                int(row["candidate_count"]) for row in callable_flow[
                    "unresolved_local_sites_in_source_order"]),
            "blocker_counts": dict(sorted(blocker_counts.items())),
        },
        "lambda_callable_units_in_source_order": units,
        "existing_callable_references_in_source_order": references,
        "live_blockers": [{
            "code": code, "count": count, "detail": blocker_detail[code],
        } for code, count in sorted(blocker_counts.items())],
        "encoding_contract": {
            "magic_ascii": LAMBDA_CALLABLE_UNITS_ENCODING_MAGIC.decode(
                "ascii"),
            "version": LAMBDA_CALLABLE_UNITS_ENCODING_VERSION,
            "payload": "canonical-json-utf8",
            "payload_integrity": "sha256-in-header",
            "numeric_ids": "one-based-deterministic-source-order",
        },
        "proof": {
            "active_call_graph_validated_in_memory": True,
            "active_callable_flow_validated_in_memory": True,
            "every_flow_lambda_unit_materialized": (
                len(units) == len(lambda_flow_units)),
            "lambda_identity_binds_owner_span_and_ast": True,
            "body_cfg_is_source_sealed_target_neutral_ssa": True,
            "default_expressions_are_definition_order_cfgs": True,
            "bound_methods_are_not_reclassified_as_lambdas": True,
            "candidate_sets_remain_non_proven": True,
            "graph_reachability_changed": False,
            "runtime_integrated": False,
        },
    }
    # ObjectExpressionIR attributes are immutable tuples internally.  Reports
    # and their binary envelope are a JSON contract, so normalize those values
    # before sealing; encode/decode must preserve object equality as well as
    # semantic equality.
    normalized = json.loads(_json_bytes(report).decode("utf-8"))
    normalized["semantic_sha256"] = _json_sha256(
        _semantic_payload(normalized))
    return normalized


def analyze_lambda_callable_units(
        project_root: Path | str, *,
        active_graph: Mapping[str, Any] | None = None,
        callable_flow: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    """Materialize source-sealed lambda units without changing reachability."""
    root = Path(project_root).resolve()
    graph = (analyze_active_call_graph(root)
             if active_graph is None else active_graph)
    validate_active_call_graph_report(root, graph)
    flow = (analyze_active_callable_flow(root, active_graph=graph)
            if callable_flow is None else callable_flow)
    validate_active_callable_flow_report(root, flow, active_graph=graph)
    report = _build_report(root, graph, flow)
    validate_lambda_callable_units_report(
        root, report, active_graph=graph, callable_flow=flow)
    return report


def _validate_report_seal(report: Mapping[str, Any]) -> None:
    if report.get("format") != LAMBDA_CALLABLE_UNITS_FORMAT:
        raise LambdaCallableUnitError("PZLCU407", "format mismatch")
    if (report.get("status") != LAMBDA_CALLABLE_UNITS_STATUS or
            report.get("live") is not False):
        raise LambdaCallableUnitError("PZLCU408", "status/live mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get(
            "semantic_sha256"):
        raise LambdaCallableUnitError("PZLCU409", "semantic hash mismatch")
    for row in report.get("lambda_callable_units_in_source_order", ()):
        if (not isinstance(row, Mapping) or
                row.get("callable_unit_materialized") is not True or
                row.get("graph_reachability_edge") is not False or
                row.get("runtime_integrated") is not False):
            raise LambdaCallableUnitError(
                "PZLCU410", "lambda integration/reachability claim invalid")
    for row in report.get(
            "existing_callable_references_in_source_order", ()):
        if (not isinstance(row, Mapping) or
                row.get("materialized_as_lambda") is not False or
                row.get("graph_reachability_edge") is not False or
                row.get("runtime_integrated") is not False):
            raise LambdaCallableUnitError(
                "PZLCU410", "existing callable was promoted/reclassified")


def validate_lambda_callable_units_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        active_graph: Mapping[str, Any],
        callable_flow: Mapping[str, Any],
        ) -> None:
    """Re-derive the report from source and reject resigned tampering."""
    root = Path(project_root).resolve()
    validate_active_call_graph_report(root, active_graph)
    validate_active_callable_flow_report(
        root, callable_flow, active_graph=active_graph)
    _validate_report_seal(report)
    if report.get("active_call_graph_semantic_sha256") != active_graph.get(
            "semantic_sha256"):
        raise LambdaCallableUnitError(
            "PZLCU411", "active call graph binding mismatch")
    if report.get("active_callable_flow_semantic_sha256") != callable_flow.get(
            "semantic_sha256"):
        raise LambdaCallableUnitError(
            "PZLCU412", "callable-flow binding mismatch")
    expected = _build_report(root, active_graph, callable_flow)
    if _semantic_payload(report) != _semantic_payload(expected):
        raise LambdaCallableUnitError(
            "PZLCU413", "lambda callable units differ from source proof")


def encode_lambda_callable_units(report: Mapping[str, Any]) -> bytes:
    """Encode the exact report with a deterministic checksummed envelope."""
    _validate_report_seal(report)
    payload = _json_bytes(report)
    return _ENCODING_HEADER.pack(
        LAMBDA_CALLABLE_UNITS_ENCODING_MAGIC,
        LAMBDA_CALLABLE_UNITS_ENCODING_VERSION, 0, len(payload),
        hashlib.sha256(payload).digest(),
    ) + payload


def decode_lambda_callable_units(encoded: bytes) -> dict[str, Any]:
    """Decode an envelope, rejecting header, length, hash and report tamper."""
    if len(encoded) < _ENCODING_HEADER.size:
        raise LambdaCallableUnitError("PZLCU414", "encoding is truncated")
    magic, version, flags, size, digest = _ENCODING_HEADER.unpack_from(encoded)
    payload = encoded[_ENCODING_HEADER.size:]
    if (magic != LAMBDA_CALLABLE_UNITS_ENCODING_MAGIC or
            version != LAMBDA_CALLABLE_UNITS_ENCODING_VERSION or flags != 0):
        raise LambdaCallableUnitError("PZLCU415", "encoding header mismatch")
    if size != len(payload):
        raise LambdaCallableUnitError("PZLCU414", "payload length mismatch")
    if hashlib.sha256(payload).digest() != digest:
        raise LambdaCallableUnitError("PZLCU416", "payload hash mismatch")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LambdaCallableUnitError(
            "PZLCU417", "payload is not canonical JSON") from error
    if not isinstance(decoded, dict) or _json_bytes(decoded) != payload:
        raise LambdaCallableUnitError(
            "PZLCU417", "payload is not canonical JSON")
    _validate_report_seal(decoded)
    return decoded


_BINARY_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.LShift: operator.lshift, ast.RShift: operator.rshift,
    ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
    ast.MatMult: operator.matmul,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos, ast.USub: operator.neg,
    ast.Invert: operator.invert, ast.Not: operator.not_,
}
_COMPARE_OPERATORS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def _oracle_expression(node: ast.expr, environment: Mapping[str, Any]) -> Any:
    """Evaluate a bounded expression subset with ordinary Python operators."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in environment:
            raise LambdaCallableUnitError(
                "PZLCU503", f"oracle name is unbound: {node.id}")
        return environment[node.id]
    if isinstance(node, ast.Tuple):
        return tuple(_oracle_expression(item, environment)
                     for item in node.elts)
    if isinstance(node, ast.List):
        return [_oracle_expression(item, environment) for item in node.elts]
    if isinstance(node, ast.Set):
        return {_oracle_expression(item, environment) for item in node.elts}
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                result.update(_oracle_expression(value, environment))
            else:
                result[_oracle_expression(key, environment)] = (
                    _oracle_expression(value, environment))
        return result
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return _BINARY_OPERATORS[type(node.op)](
            _oracle_expression(node.left, environment),
            _oracle_expression(node.right, environment))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](
            _oracle_expression(node.operand, environment))
    if isinstance(node, ast.BoolOp):
        values = iter(node.values)
        result = _oracle_expression(next(values), environment)
        if isinstance(node.op, ast.And):
            for value in values:
                if not result:
                    return result
                result = _oracle_expression(value, environment)
            return result
        if isinstance(node.op, ast.Or):
            for value in values:
                if result:
                    return result
                result = _oracle_expression(value, environment)
            return result
    if isinstance(node, ast.Compare):
        left = _oracle_expression(node.left, environment)
        for operation_node, comparator in zip(node.ops, node.comparators):
            operation = _COMPARE_OPERATORS.get(type(operation_node))
            if operation is None:
                break
            right = _oracle_expression(comparator, environment)
            if not operation(left, right):
                return False
            left = right
        else:
            return True
    if isinstance(node, ast.IfExp):
        branch = node.body if _oracle_expression(
            node.test, environment) else node.orelse
        return _oracle_expression(branch, environment)
    if isinstance(node, ast.Attribute):
        return getattr(_oracle_expression(node.value, environment), node.attr)
    if isinstance(node, ast.Subscript):
        container = _oracle_expression(node.value, environment)
        if isinstance(node.slice, ast.Slice):
            index = slice(*(
                _oracle_expression(item, environment) if item is not None
                else None for item in (
                    node.slice.lower, node.slice.upper, node.slice.step)))
        else:
            index = _oracle_expression(node.slice, environment)
        return container[index]
    if isinstance(node, ast.Call):
        callable_value = _oracle_expression(node.func, environment)
        positional: list[Any] = []
        for argument in node.args:
            if isinstance(argument, ast.Starred):
                positional.extend(_oracle_expression(
                    argument.value, environment))
            else:
                positional.append(_oracle_expression(argument, environment))
        keywords: dict[str, Any] = {}
        for keyword in node.keywords:
            value = _oracle_expression(keyword.value, environment)
            if keyword.arg is None:
                keywords.update(value)
            elif keyword.arg in keywords:
                raise LambdaCallableUnitError(
                    "PZLCU505", f"duplicate oracle keyword: {keyword.arg}")
            else:
                keywords[keyword.arg] = value
        return callable_value(*positional, **keywords)
    raise LambdaCallableUnitError(
        "PZLCU506", f"oracle expression is unsupported: {type(node).__name__}")


def _parse_oracle_expression(source: str) -> ast.expr:
    try:
        return ast.parse(source, mode="eval").body
    except SyntaxError as error:
        raise LambdaCallableUnitError(
            "PZLCU507", "sealed oracle expression does not parse") from error


def evaluate_lambda_definition_defaults_oracle(
        unit: Mapping[str, Any], environment: Mapping[str, Any],
        ) -> dict[str, Any]:
    """Evaluate defaults once, in the exact lambda-definition order."""
    result: dict[str, Any] = {}
    rows = unit["definition_time_default_evaluation"]["entries"]
    if [int(row["evaluation_index"]) for row in rows] != list(range(
            len(rows))):
        raise LambdaCallableUnitError(
            "PZLCU501", "default evaluation order is malformed")
    for row in rows:
        result[str(row["parameter"])] = _oracle_expression(
            _parse_oracle_expression(str(row["source"])), environment)
    return result


def _oracle_signature(
        unit: Mapping[str, Any], definition_defaults: Mapping[str, Any],
        ) -> inspect.Signature:
    kinds = {
        "positional-only": inspect.Parameter.POSITIONAL_ONLY,
        "positional-or-keyword": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "var-positional": inspect.Parameter.VAR_POSITIONAL,
        "keyword-only": inspect.Parameter.KEYWORD_ONLY,
        "var-keyword": inspect.Parameter.VAR_KEYWORD,
    }
    parameters: list[inspect.Parameter] = []
    default_names = {str(row["parameter"]) for row in unit[
        "definition_time_default_evaluation"]["entries"]}
    for row in unit["signature"]["parameters"]:
        name = str(row["name"])
        kind = kinds.get(str(row["kind"]))
        if kind is None:
            raise LambdaCallableUnitError(
                "PZLCU501", f"unknown parameter kind: {row['kind']}")
        default: Any = inspect.Parameter.empty
        if bool(row["has_default"]):
            if name not in default_names or name not in definition_defaults:
                raise LambdaCallableUnitError(
                    "PZLCU502", f"definition-time default missing: {name}")
            default = definition_defaults[name]
        parameters.append(inspect.Parameter(name, kind, default=default))
    if set(definition_defaults) != default_names:
        raise LambdaCallableUnitError(
            "PZLCU502", "definition-time default set differs from signature")
    try:
        return inspect.Signature(parameters)
    except ValueError as error:
        raise LambdaCallableUnitError(
            "PZLCU501", "lambda signature is malformed") from error


def bind_lambda_call_oracle(
        unit: Mapping[str, Any], positional: Sequence[Any] = (), *,
        keywords: Mapping[str, Any] | None = None,
        definition_defaults: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    """Bind one call with Python's own signature binder."""
    signature = _oracle_signature(unit, definition_defaults or {})
    try:
        bound = signature.bind(*tuple(positional), **dict(keywords or {}))
    except TypeError as error:
        raise LambdaCallableUnitError(
            "PZLCU504", f"lambda argument binding failed: {error}") from error
    bound.apply_defaults()
    return dict(bound.arguments)


def execute_lambda_unit_oracle(
        unit: Mapping[str, Any], positional: Sequence[Any] = (), *,
        keywords: Mapping[str, Any] | None = None,
        definition_defaults: Mapping[str, Any] | None = None,
        closure: Mapping[str, Any] | None = None,
        ) -> Any:
    """Execute the sealed body for tests; runtime integration is not implied."""
    closure_values = dict(closure or {})
    required_captures = set(unit["closure"]["captured_names"])
    missing = sorted(required_captures - set(closure_values))
    if missing:
        raise LambdaCallableUnitError(
            "PZLCU503", "unbound closure captures: " + ", ".join(missing))
    if set(closure_values) != required_captures:
        raise LambdaCallableUnitError(
            "PZLCU503", "closure capture set differs from sealed unit")
    bound = bind_lambda_call_oracle(
        unit, positional, keywords=keywords,
        definition_defaults=definition_defaults)
    environment = {**closure_values, **bound}
    return _oracle_expression(
        _parse_oracle_expression(str(unit["body"]["source"])), environment)
