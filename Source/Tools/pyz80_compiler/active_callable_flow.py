"""Source-proven callable-value flow for unresolved local call sites.

The active call graph intentionally does not make lambdas or carried bound
method values into reachability edges.  This module inventories those values
and their flow without changing that rule.  Candidate sets are useful input
for a later callable-unit/dispatch implementation, but are always non-proven
here.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .active_call_graph import (
    analyze_active_call_graph,
    validate_active_call_graph_report,
)


ACTIVE_CALLABLE_FLOW_FORMAT = "pyz80.active-callable-flow.v1"
ACTIVE_CALLABLE_FLOW_STATUS = "ACTIVE_CALLABLE_FLOW_INVENTORIED_LIVE_BLOCKED"

__all__ = [
    "ACTIVE_CALLABLE_FLOW_FORMAT",
    "ACTIVE_CALLABLE_FLOW_STATUS",
    "ActiveCallableFlowError",
    "analyze_active_callable_flow",
    "validate_active_callable_flow_report",
]


class ActiveCallableFlowError(ValueError):
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


def _signature(node: ast.Lambda | ast.FunctionDef |
               ast.AsyncFunctionDef) -> dict[str, Any]:
    arguments = node.args
    positional = list(arguments.posonlyargs) + list(arguments.args)
    default_offset = len(positional) - len(arguments.defaults)
    defaults: list[ast.expr | None] = [None] * default_offset + list(
        arguments.defaults)
    rows = [{
        "name": argument.arg,
        "kind": ("positional-only"
                 if index < len(arguments.posonlyargs)
                 else "positional-or-keyword"),
        "has_default": defaults[index] is not None,
        "default_ast_sha256": (_ast_sha256(defaults[index])
                               if defaults[index] is not None else None),
    } for index, argument in enumerate(positional)]
    if arguments.vararg is not None:
        rows.append({
            "name": arguments.vararg.arg, "kind": "var-positional",
            "has_default": False, "default_ast_sha256": None,
        })
    rows.extend({
        "name": argument.arg, "kind": "keyword-only",
        "has_default": default is not None,
        "default_ast_sha256": (_ast_sha256(default)
                               if default is not None else None),
    } for argument, default in zip(
        arguments.kwonlyargs, arguments.kw_defaults))
    if arguments.kwarg is not None:
        rows.append({
            "name": arguments.kwarg.arg, "kind": "var-keyword",
            "has_default": False, "default_ast_sha256": None,
        })
    return {"parameters": rows}


def _parameter_names(node: ast.Lambda | ast.FunctionDef |
                     ast.AsyncFunctionDef) -> set[str]:
    arguments = node.args
    return {
        item.arg for item in (
            list(arguments.posonlyargs) + list(arguments.args) +
            list(arguments.kwonlyargs) +
            ([arguments.vararg] if arguments.vararg is not None else []) +
            ([arguments.kwarg] if arguments.kwarg is not None else []))
    }


def _lambda_captures(node: ast.Lambda) -> list[str]:
    parameters = _parameter_names(node)
    loaded = {item.id for item in ast.walk(node.body)
              if isinstance(item, ast.Name) and
              isinstance(item.ctx, ast.Load)}
    return sorted(loaded - parameters - set(dir(builtins)))


@dataclass
class _Assignment:
    owner: str
    target: ast.expr
    value: ast.expr | None
    conditional: bool


class _ScopeIndex(ast.NodeVisitor):
    def __init__(self, owner: str,
                 root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.owner = owner
        self.assignments: list[_Assignment] = []
        self.dynamic_setattrs: list[ast.Call] = []
        self._conditional_depth = 0
        for statement in root.body:
            self.visit(statement)

    def _record(self, target: ast.expr, value: ast.expr | None) -> None:
        self.assignments.append(_Assignment(
            self.owner, target, value, self._conditional_depth > 0))

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self._record(target, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self._record(node.target, node.value)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self._record(node.target, None)
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        self._record(node.target, node.value)
        self.visit(node.value)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.visit(node.test)
        self._conditional_depth += 1
        for statement in node.body + node.orelse:
            self.visit(statement)
        self._conditional_depth -= 1

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.visit(node.iter)
        self._conditional_depth += 1
        for statement in node.body + node.orelse:
            self.visit(statement)
        self._conditional_depth -= 1

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.visit(node.test)
        self._conditional_depth += 1
        for statement in node.body + node.orelse:
            self.visit(statement)
        self._conditional_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self._conditional_depth += 1
        for statement in node.body + node.orelse + node.finalbody:
            self.visit(statement)
        for handler in node.handlers:
            for statement in handler.body:
                self.visit(statement)
        self._conditional_depth -= 1

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        for item in node.items:
            self.visit(item.context_expr)
        self._conditional_depth += 1
        for statement in node.body:
            self.visit(statement)
        self._conditional_depth -= 1

    visit_AsyncWith = visit_With

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (isinstance(node.func, ast.Name) and node.func.id == "setattr" and
                len(node.args) >= 3):
            self.dynamic_setattrs.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        # Defaults execute in this scope; the body belongs to the lambda.
        for expression in list(node.args.defaults):
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)


@dataclass
class _Incoming:
    caller: str
    call_site_id: str
    expression: ast.expr | None
    complete: bool
    reason: str | None = None


@dataclass
class _Flow:
    candidates: set[str] = field(default_factory=set)
    dynamic_sources: set[str] = field(default_factory=set)
    complete: bool = True
    reasons: set[str] = field(default_factory=set)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, other: "_Flow") -> "_Flow":
        self.candidates.update(other.candidates)
        self.dynamic_sources.update(other.dynamic_sources)
        self.complete &= other.complete
        self.reasons.update(other.reasons)
        self.trace.extend(other.trace)
        return self


class _Context:
    def __init__(self, project_root: Path,
                 active_graph: Mapping[str, Any]) -> None:
        self.root = project_root
        self.graph = active_graph
        self.reachable = set(active_graph[
            "call_graph"]["proven_reachable_callable_ids"])
        self.callable_rows = {
            str(row["callable_id"]): row
            for row in active_graph["callable_inventory"]["callables"]
        }
        self.class_rows = {
            str(row["class_id"]): row
            for row in active_graph["class_inventory"]["classes"]
        }
        self.modules: dict[str, tuple[str, str, ast.Module]] = {}
        for row in active_graph["source_graph"]["modules"]:
            module = str(row["module"])
            path = _norm(str(row["path"]))
            source = (project_root / path).read_bytes().decode("utf-8")
            self.modules[module] = (
                path, source, ast.parse(source, filename=path,
                                        type_comments=True))

        nodes: dict[tuple[str, int, str], list[ast.AST]] = defaultdict(list)
        for module, (_path, _source, tree) in self.modules.items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.Call)):
                    nodes[(module, int(node.lineno),
                           _ast_sha256(node))].append(node)
        self.function_nodes: dict[
            str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for identifier, row in self.callable_rows.items():
            matches = nodes.get((str(row["module"]),
                                 int(row["definition_line"]),
                                 str(row["ast_sha256"])), ())
            if len(matches) != 1 or not isinstance(
                    matches[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
                raise ActiveCallableFlowError(
                    "PZCFLOW003", f"callable source mismatch: {identifier}")
            self.function_nodes[identifier] = matches[0]
        self.scope_indexes = {
            identifier: _ScopeIndex(identifier, node)
            for identifier, node in self.function_nodes.items()
        }
        self.call_nodes: dict[str, ast.Call] = {}
        for row in active_graph["call_graph"]["call_sites"]:
            caller = str(row["caller"])
            module = str(self.callable_rows[caller]["module"])
            matches = nodes.get((module, int(row["line"]),
                                 str(row["ast_sha256"])), ())
            matches = [node for node in matches if isinstance(node, ast.Call)
                       and int(node.col_offset) == int(row["column"])
                       and int(node.end_lineno or node.lineno) ==
                       int(row["end_line"])
                       and int(node.end_col_offset or node.col_offset + 1) ==
                       int(row["end_column"])]
            if len(matches) != 1:
                raise ActiveCallableFlowError(
                    "PZCFLOW004", f"call source mismatch: "
                    f"{row['call_site_id']}")
            self.call_nodes[str(row["call_site_id"])] = matches[0]

        self.graph_sites = {
            str(row["call_site_id"]): row
            for row in active_graph["call_graph"]["call_sites"]
        }
        self.incoming: dict[tuple[str, str], list[_Incoming]] = defaultdict(list)
        self.nonproven_incoming: set[tuple[str, str]] = set()
        self._build_incoming()
        self.local_assignments: dict[tuple[str, str], list[_Assignment]] = (
            defaultdict(list))
        self.attr_assignments: dict[
            tuple[str, str], list[_Assignment]] = defaultdict(list)
        self.dynamic_attr_classes: set[str] = set()
        self._build_assignments()
        self.units: dict[str, dict[str, Any]] = {}
        self.dynamic_sources: dict[str, dict[str, Any]] = {}
        self.name_memo: dict[tuple[str, str], _Flow] = {}
        self.attr_memo: dict[tuple[str, str], _Flow] = {}

    def path_for_owner(self, owner: str) -> str:
        module = str(self.callable_rows[owner]["module"])
        return self.modules[module][0]

    def source_for_owner(self, owner: str) -> str:
        module = str(self.callable_rows[owner]["module"])
        return self.modules[module][1]

    def _skip_implicit(self, resolution_kind: str,
                       target: str) -> bool:
        node = self.function_nodes[target]
        decorators = {
            item.id for item in node.decorator_list
            if isinstance(item, ast.Name)}
        if resolution_kind == "exact-internal-constructor":
            return True
        if resolution_kind in {
                "exact-internal-method", "exact-common-dispatch",
                "exact-super-method"}:
            return "staticmethod" not in decorators
        if resolution_kind == "exact-internal-class-method":
            return "classmethod" in decorators
        return False

    def _actual_map(
            self, call: ast.Call, target: str, resolution_kind: str,
            ) -> tuple[dict[str, ast.expr | None], bool]:
        node = self.function_nodes[target]
        positional = list(node.args.posonlyargs) + list(node.args.args)
        if self._skip_implicit(resolution_kind, target) and positional:
            positional = positional[1:]
        result: dict[str, ast.expr | None] = {
            item.arg: None for item in positional}
        result.update({item.arg: None for item in node.args.kwonlyargs})
        complete = not any(isinstance(item, ast.Starred)
                           for item in call.args) and not any(
            item.arg is None for item in call.keywords)
        if not complete:
            return result, False
        for parameter, actual in zip(positional, call.args):
            result[parameter.arg] = actual
        for keyword in call.keywords:
            if keyword.arg in result:
                result[str(keyword.arg)] = keyword.value
        return result, True

    def _build_incoming(self) -> None:
        for row in self.graph["call_graph"]["call_sites"]:
            if str(row["caller"]) not in self.reachable:
                continue
            resolution = row["resolution"]
            for target in resolution["targets"]:
                target = str(target)
                if target not in self.function_nodes:
                    continue
                if resolution["proven"] is not True:
                    for parameter in _parameter_names(
                            self.function_nodes[target]):
                        self.nonproven_incoming.add((target, parameter))
                    continue
                actuals, complete = self._actual_map(
                    self.call_nodes[str(row["call_site_id"])], target,
                    str(resolution["kind"]))
                for parameter, expression in actuals.items():
                    self.incoming[(target, parameter)].append(_Incoming(
                        caller=str(row["caller"]),
                        call_site_id=str(row["call_site_id"]),
                        expression=expression,
                        complete=complete,
                        reason=(None if complete else
                                "star-argument-prevents-exact-actual-map"),
                    ))

    def _build_assignments(self) -> None:
        for owner, index in self.scope_indexes.items():
            class_id = self.callable_rows[owner].get("class_id")
            for assignment in index.assignments:
                target = assignment.target
                if isinstance(target, ast.Name):
                    self.local_assignments[(owner, target.id)].append(
                        assignment)
                elif (class_id is not None and
                      isinstance(target, ast.Attribute) and
                      isinstance(target.value, ast.Name) and
                      target.value.id == "self"):
                    self.attr_assignments[(str(class_id), target.attr)].append(
                        assignment)
            if class_id is None:
                continue
            for call in index.dynamic_setattrs:
                receiver, attribute = call.args[0], call.args[1]
                if not (isinstance(receiver, ast.Name) and
                        receiver.id == "self"):
                    continue
                if isinstance(attribute, ast.Constant) and isinstance(
                        attribute.value, str):
                    synthetic = _Assignment(
                        owner, ast.Attribute(
                            value=receiver, attr=attribute.value,
                            ctx=ast.Store()), call.args[2], True)
                    self.attr_assignments[(
                        str(class_id), attribute.value)].append(synthetic)
                else:
                    self.dynamic_attr_classes.add(str(class_id))

    def _method_lookup(self, class_id: str, method: str,
                       seen: set[str] | None = None) -> str | None:
        visited = set() if seen is None else seen
        if class_id in visited or class_id not in self.class_rows:
            return None
        visited.add(class_id)
        row = self.class_rows[class_id]
        if method in row["methods"]:
            return str(row["methods"][method])
        targets = {
            target for base in row["internal_bases"]
            for target in [self._method_lookup(str(base), method, visited)]
            if target is not None
        }
        return next(iter(targets)) if len(targets) == 1 else None

    def _constructor_class(self, owner: str, expression: ast.Call) -> str | None:
        for site_id, node in self.call_nodes.items():
            if node is not expression:
                continue
            row = self.graph_sites[site_id]
            if str(row["caller"]) != owner:
                continue
            constructed = row["resolution"].get("constructed_class")
            return str(constructed) if constructed is not None else None
        return None

    def _receiver_proof(
            self, owner: str, expression: ast.expr,
            stack: frozenset[tuple[str, str]],
            ) -> dict[str, Any]:
        class_id = self.callable_rows[owner].get("class_id")
        if isinstance(expression, ast.Name) and expression.id == "self" and \
                class_id is not None:
            return {
                "complete": True, "kind": "method-self",
                "class_ids": [str(class_id)], "value": "self",
                "evidence": "owner callable has exact class identity",
            }
        if isinstance(expression, ast.Name):
            assignments = self.local_assignments.get(
                (owner, expression.id), ())
            classes: set[str] = set()
            evidence: list[dict[str, Any]] = []
            complete = bool(assignments)
            for assignment in assignments:
                rhs = assignment.value
                if isinstance(rhs, ast.Call):
                    constructed = self._constructor_class(owner, rhs)
                    if constructed is not None:
                        classes.add(constructed)
                        evidence.append({
                            "kind": "local-constructor-assignment",
                            "span": _span(self.path_for_owner(owner), rhs),
                            "constructed_class": constructed,
                        })
                        continue
                complete = False
            return {
                "complete": complete and len(classes) == 1,
                "kind": "local-constructor" if classes else
                "unresolved-local-value",
                "class_ids": sorted(classes),
                "value": expression.id,
                "evidence": evidence,
            }
        return {
            "complete": False, "kind": "receiver-expression-unresolved",
            "class_ids": [],
            "value": ast.get_source_segment(
                self.source_for_owner(owner), expression) or ast.unparse(
                    expression),
            "evidence": type(expression).__name__,
        }

    def _lambda_unit(self, owner: str, node: ast.Lambda) -> str:
        path = self.path_for_owner(owner)
        identity = {
            "kind": "lambda", "module": self.callable_rows[owner]["module"],
            "lexical_owner": owner, "span": _span(path, node),
            "ast_sha256": _ast_sha256(node),
        }
        unit_id = "lambda:" + _json_sha256(identity)
        self.units.setdefault(unit_id, {
            "callable_value_id": unit_id,
            **identity,
            "signature": _signature(node),
            "closure": {
                "lexical_owner": owner,
                "captured_names": _lambda_captures(node),
            },
            "callable_unit_integrated": False,
            "proven_reachability_edge": False,
        })
        return unit_id

    def _bound_method_unit(
            self, owner: str, node: ast.Attribute, target: str,
            receiver_proof: Mapping[str, Any],
            ) -> str:
        path = self.path_for_owner(owner)
        identity = {
            "kind": "bound-method", "target_callable_id": target,
            "expression_owner": owner, "span": _span(path, node),
            "receiver_proof_sha256": _json_sha256(receiver_proof),
        }
        unit_id = "bound-method:" + _json_sha256(identity)
        signature = _signature(self.function_nodes[target])
        parameters = signature["parameters"]
        self.units.setdefault(unit_id, {
            "callable_value_id": unit_id,
            **identity,
            "receiver_proof": dict(receiver_proof),
            "signature": signature,
            "bound_parameter": (parameters[0]["name"]
                                if parameters else None),
            "callable_unit_integrated": False,
            "proven_reachability_edge": False,
        })
        return unit_id

    def _dynamic_getattr(
            self, owner: str, node: ast.Call,
            stack: frozenset[tuple[str, str]],
            ) -> str:
        path = self.path_for_owner(owner)
        receiver = (self._receiver_proof(owner, node.args[0], stack)
                    if node.args else {
                        "complete": False, "kind": "missing-receiver",
                        "class_ids": []})
        attribute: str | None = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and \
                isinstance(node.args[1].value, str):
            attribute = node.args[1].value
        identity = {
            "kind": "dynamic-getattr", "owner": owner,
            "span": _span(path, node), "ast_sha256": _ast_sha256(node),
        }
        source_id = "dynamic-getattr:" + _json_sha256(identity)
        reasons = []
        if not receiver.get("complete"):
            reasons.append("getattr-receiver-class-not-source-proven")
        if attribute is None:
            reasons.append("getattr-attribute-name-not-literal")
        reasons.append("getattr-result-descriptor-presence-is-runtime-dynamic")
        self.dynamic_sources.setdefault(source_id, {
            "dynamic_source_id": source_id,
            **identity,
            "attribute_name": attribute,
            "receiver_proof": receiver,
            "default_argument_present": len(node.args) >= 3,
            "complete": False,
            "reasons": reasons,
        })
        return source_id

    def _class_attr_flow(
            self, class_id: str, attribute: str,
            stack: frozenset[tuple[str, str]],
            ) -> _Flow:
        key = (class_id, attribute)
        if key in self.attr_memo:
            return self.attr_memo[key]
        if key in stack:
            return _Flow(complete=False, reasons={
                "class-attribute-flow-cycle"})
        assignments = self.attr_assignments.get(key, ())
        if not assignments:
            return _Flow(complete=False, reasons={
                "class-attribute-has-no-inventoried-assignment"})
        flow = _Flow()
        for assignment in assignments:
            if assignment.value is None:
                flow.complete = False
                flow.reasons.add("class-attribute-assignment-value-unknown")
                continue
            nested = self._expr_flow(
                assignment.owner, assignment.value, stack | {key})
            flow.merge(nested)
            flow.trace.append({
                "operation": "class-attribute-assignment",
                "owner": assignment.owner,
                "conditional": assignment.conditional,
                "span": _span(self.path_for_owner(
                    assignment.owner), assignment.target),
            })
            if assignment.conditional:
                flow.complete = False
                flow.reasons.add("conditional-class-attribute-write")
        if class_id in self.dynamic_attr_classes:
            flow.complete = False
            flow.reasons.add("class-has-dynamic-setattr-write")
        self.attr_memo[key] = flow
        return flow

    def _name_flow(
            self, owner: str, name: str,
            stack: frozenset[tuple[str, str]],
            ) -> _Flow:
        key = (owner, name)
        if key in self.name_memo:
            return self.name_memo[key]
        if key in stack:
            return _Flow(complete=False, reasons={"local-alias-flow-cycle"})
        node = self.function_nodes[owner]
        is_parameter = name in _parameter_names(node)
        base = _Flow()
        if is_parameter:
            incoming = self.incoming.get(key, ())
            if not incoming:
                base.complete = False
                base.reasons.add("parameter-has-no-proven-incoming-actual")
            for item in incoming:
                if item.expression is None:
                    base.complete = False
                    base.reasons.add(
                        item.reason or "parameter-actual-omitted-or-unknown")
                    continue
                nested = self._expr_flow(
                    item.caller, item.expression, stack | {key})
                base.merge(nested)
                base.trace.append({
                    "operation": "proven-parameter-actual",
                    "caller": item.caller,
                    "call_site_id": item.call_site_id,
                    "complete_argument_map": item.complete,
                })
            if key in self.nonproven_incoming:
                base.complete = False
                base.reasons.add("parameter-has-non-proven-incoming-dispatch")
        assignments = self.local_assignments.get(key, ())
        if not is_parameter and not assignments:
            base.complete = False
            base.reasons.add("local-name-has-no-callable-source-binding")
        result = _Flow().merge(base)
        for assignment in assignments:
            if assignment.value is None:
                result.complete = False
                result.reasons.add("local-assignment-value-unknown")
                continue
            nested = self._expr_flow(
                owner, assignment.value, stack | {key},
                overrides={key: base})
            result.merge(nested)
            result.trace.append({
                "operation": "local-assignment-or-alias",
                "conditional": assignment.conditional,
                "span": _span(self.path_for_owner(owner),
                              assignment.target),
            })
            if assignment.conditional:
                result.complete = False
                result.reasons.add("conditional-local-write")
        self.name_memo[key] = result
        return result

    def _expr_flow(
            self, owner: str, expression: ast.expr,
            stack: frozenset[tuple[str, str]] = frozenset(), *,
            overrides: Mapping[tuple[str, str], _Flow] | None = None,
            ) -> _Flow:
        if isinstance(expression, ast.Lambda):
            unit = self._lambda_unit(owner, expression)
            return _Flow(candidates={unit}, trace=[{
                "operation": "lambda-value", "callable_value_id": unit}])
        if isinstance(expression, ast.Constant):
            return _Flow(trace=[{
                "operation": "non-callable-constant",
                "value_kind": type(expression.value).__name__,
            }])
        if isinstance(expression, ast.Name):
            key = (owner, expression.id)
            if overrides is not None and key in overrides:
                return _Flow().merge(overrides[key])
            return self._name_flow(owner, expression.id, stack)
        if isinstance(expression, (ast.BoolOp, ast.IfExp)):
            values = (expression.values if isinstance(expression, ast.BoolOp)
                      else [expression.body, expression.orelse])
            result = _Flow()
            for value in values:
                result.merge(self._expr_flow(
                    owner, value, stack, overrides=overrides))
            result.trace.append({
                "operation": ("conditional-alias-union"
                              if isinstance(expression, ast.IfExp)
                              else "short-circuit-alias-union"),
                "branch_count": len(values),
            })
            return result
        if isinstance(expression, ast.Attribute):
            receiver = self._receiver_proof(owner, expression.value, stack)
            classes = list(receiver.get("class_ids", ()))
            if (isinstance(expression.value, ast.Name) and
                    expression.value.id == "self" and len(classes) == 1 and
                    (classes[0], expression.attr) in self.attr_assignments):
                return self._class_attr_flow(
                    classes[0], expression.attr, stack)
            targets = {
                target for class_id in classes
                for target in [self._method_lookup(class_id, expression.attr)]
                if target is not None
            }
            if receiver.get("complete") and len(targets) == 1:
                target = next(iter(targets))
                unit = self._bound_method_unit(
                    owner, expression, target, receiver)
                return _Flow(candidates={unit}, trace=[{
                    "operation": "bound-method-value",
                    "callable_value_id": unit,
                    "target_callable_id": target,
                }])
            reasons = {"bound-method-receiver-or-target-not-exact"}
            if not receiver.get("complete"):
                reasons.add("receiver-class-not-source-proven")
            return _Flow(complete=False, reasons=reasons, trace=[{
                "operation": "unresolved-attribute-callable-value",
                "receiver_proof": receiver,
                "attribute": expression.attr,
            }])
        if isinstance(expression, ast.Call):
            if (isinstance(expression.func, ast.Name) and
                    expression.func.id == "getattr"):
                source = self._dynamic_getattr(owner, expression, stack)
                return _Flow(
                    dynamic_sources={source}, complete=False,
                    reasons=set(self.dynamic_sources[source]["reasons"]),
                    trace=[{"operation": "dynamic-getattr-value",
                            "dynamic_source_id": source}])
            return _Flow(complete=False, reasons={
                "call-result-callable-identity-not-source-proven"})
        return _Flow(complete=False, reasons={
            f"unsupported-callable-value-expression:{type(expression).__name__}"})


def _build_report(
        project_root: Path, active_graph: Mapping[str, Any],
        ) -> dict[str, Any]:
    context = _Context(project_root, active_graph)
    unresolved = [
        row for row in active_graph["call_graph"]["call_sites"]
        if str(row["caller"]) in context.reachable and
        row["resolution"]["kind"] == "unresolved-local-callable"
    ]
    site_flows: list[tuple[Mapping[str, Any], _Flow, str]] = []
    for row in unresolved:
        node = context.call_nodes[str(row["call_site_id"])]
        if not isinstance(node.func, ast.Name):
            flow = _Flow(complete=False, reasons={
                "unresolved-local-callee-is-not-a-name"})
            name = ast.unparse(node.func)
        else:
            name = node.func.id
            flow = context._name_flow(str(row["caller"]), name, frozenset())
        site_flows.append((row, flow, name))

    units = sorted(context.units.values(), key=lambda row: (
        row["span"]["path"], row["span"]["line"],
        row["span"]["column"], row["kind"], row["callable_value_id"]))
    numeric_units = {
        str(row["callable_value_id"]): index
        for index, row in enumerate(units, start=1)
    }
    unit_rows = [{
        "numeric_callable_value_id": numeric_units[str(
            row["callable_value_id"])],
        **row,
    } for row in units]
    dynamic_rows = sorted(context.dynamic_sources.values(), key=lambda row: (
        row["span"]["path"], row["span"]["line"],
        row["span"]["column"], row["dynamic_source_id"]))
    dynamic_numeric = {
        str(row["dynamic_source_id"]): index
        for index, row in enumerate(dynamic_rows, start=1)}
    dynamic_rows = [{
        "numeric_dynamic_source_id": dynamic_numeric[str(
            row["dynamic_source_id"])],
        **row,
    } for row in dynamic_rows]

    site_rows: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    for row, flow, name in sorted(site_flows, key=lambda item: (
            context.path_for_owner(str(item[0]["caller"])),
            int(item[0]["line"]), int(item[0]["column"]),
            str(item[0]["call_site_id"]))):
        blockers = ["PZCFLOW201"]
        if not flow.complete:
            blockers.append("PZCFLOW202")
        if flow.dynamic_sources:
            blockers.append("PZCFLOW205")
        candidate_kinds = Counter(
            context.units[candidate]["kind"]
            for candidate in flow.candidates)
        if candidate_kinds.get("lambda"):
            blockers.append("PZCFLOW203")
        if candidate_kinds.get("bound-method"):
            blockers.append("PZCFLOW204")
        blockers = sorted(set(blockers))
        blocker_counts.update(blockers)
        site_rows.append({
            "source_order_index": len(site_rows),
            "call_site_id": str(row["call_site_id"]),
            "caller": str(row["caller"]),
            "span": {
                "path": context.path_for_owner(str(row["caller"])),
                "line": int(row["line"]), "column": int(row["column"]),
                "end_line": int(row["end_line"]),
                "end_column": int(row["end_column"]),
            },
            "source": str(row["source"]),
            "callee_name": name,
            "graph_resolution_evidence": str(
                row["resolution"]["evidence"]),
            "incoming_candidates_complete": flow.complete,
            "candidate_count": len(flow.candidates),
            "candidate_callable_value_ids": sorted(flow.candidates),
            "candidate_numeric_callable_value_ids": sorted(
                numeric_units[item] for item in flow.candidates),
            "candidate_kind_counts": dict(sorted(candidate_kinds.items())),
            "dynamic_source_ids": sorted(flow.dynamic_sources),
            "dynamic_numeric_source_ids": sorted(
                dynamic_numeric[item] for item in flow.dynamic_sources),
            "incompleteness_reasons": sorted(flow.reasons),
            "flow_trace": flow.trace,
            "proven": False,
            "promotion_permitted": False,
            "blocker_codes": blockers,
        })

    callee_counts = Counter(row["callee_name"] for row in site_rows)
    unit_kind_counts = Counter(row["kind"] for row in unit_rows)
    live_blockers = [{
        "code": code, "count": int(count),
        "detail": {
            "PZCFLOW201": "candidate values are not proven reachability edges",
            "PZCFLOW202": "incoming callable candidate set is incomplete",
            "PZCFLOW203": "lambda has no integrated callable CFG unit",
            "PZCFLOW204": "bound method receiver storage/dispatch is unbound",
            "PZCFLOW205": "dynamic getattr callable identity is unresolved",
        }[code],
    } for code, count in sorted(blocker_counts.items())]
    live_blockers.append({
        "code": "PZCFLOW206", "count": 1,
        "detail": "active graph/backend does not consume callable-flow units",
    })
    report: dict[str, Any] = {
        "format": ACTIVE_CALLABLE_FLOW_FORMAT,
        "status": ACTIVE_CALLABLE_FLOW_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": active_graph["semantic_sha256"],
        "census": {
            "reachable_unresolved_local_callable_site_count": len(site_rows),
            "callee_name_counts": dict(sorted(callee_counts.items())),
            "complete_incoming_candidate_site_count": sum(
                row["incoming_candidates_complete"] for row in site_rows),
            "incomplete_incoming_candidate_site_count": sum(
                not row["incoming_candidates_complete"] for row in site_rows),
            "callable_value_unit_count": len(unit_rows),
            "callable_value_kind_counts": dict(sorted(
                unit_kind_counts.items())),
            "dynamic_source_count": len(dynamic_rows),
            "candidate_reference_count": sum(
                row["candidate_count"] for row in site_rows),
            "blocker_site_counts": dict(sorted(blocker_counts.items())),
        },
        "callable_value_units_in_source_order": unit_rows,
        "dynamic_sources_in_source_order": dynamic_rows,
        "unresolved_local_sites_in_source_order": site_rows,
        "live_blockers": live_blockers,
        "proof": {
            "active_call_graph_validated_in_memory": True,
            "lambda_ids_bind_source_span_ast_and_lexical_owner": True,
            "bound_methods_require_exact_receiver_class_and_method": True,
            "conditional_and_alias_sources_are_unioned": True,
            "dynamic_getattr_never_creates_a_candidate_target": True,
            "candidate_sets_never_drive_proven_reachability": True,
            "callable_units_and_dispatch_integrated": False,
        },
    }
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    return report


def analyze_active_callable_flow(
        project_root: Path | str, *,
        active_graph: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
    root = Path(project_root).resolve()
    graph = (analyze_active_call_graph(root)
             if active_graph is None else active_graph)
    validate_active_call_graph_report(root, graph)
    report = _build_report(root, graph)
    validate_active_callable_flow_report(root, report, active_graph=graph)
    return report


def validate_active_callable_flow_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        active_graph: Mapping[str, Any],
        ) -> None:
    root = Path(project_root).resolve()
    validate_active_call_graph_report(root, active_graph)
    if report.get("format") != ACTIVE_CALLABLE_FLOW_FORMAT:
        raise ActiveCallableFlowError("PZCFLOW401", "format mismatch")
    if (report.get("status") != ACTIVE_CALLABLE_FLOW_STATUS or
            report.get("live") is not False):
        raise ActiveCallableFlowError(
            "PZCFLOW402", "status/live claim mismatch")
    if _json_sha256(_semantic_payload(report)) != report.get(
            "semantic_sha256"):
        raise ActiveCallableFlowError(
            "PZCFLOW403", "semantic hash mismatch")
    if report.get("active_call_graph_semantic_sha256") != active_graph.get(
            "semantic_sha256"):
        raise ActiveCallableFlowError(
            "PZCFLOW404", "active graph binding mismatch")
    for row in report.get("unresolved_local_sites_in_source_order", ()):
        if (not isinstance(row, Mapping) or row.get("proven") is not False or
                row.get("promotion_permitted") is not False):
            raise ActiveCallableFlowError(
                "PZCFLOW405", "callable candidates were promoted")
    for row in report.get("callable_value_units_in_source_order", ()):
        if (not isinstance(row, Mapping) or
                row.get("proven_reachability_edge") is not False or
                row.get("callable_unit_integrated") is not False):
            raise ActiveCallableFlowError(
                "PZCFLOW405", "callable unit integration claim is invalid")
    expected = _build_report(root, active_graph)
    if _semantic_payload(report) != _semantic_payload(expected):
        raise ActiveCallableFlowError(
            "PZCFLOW406", "callable flow differs from source proof")

