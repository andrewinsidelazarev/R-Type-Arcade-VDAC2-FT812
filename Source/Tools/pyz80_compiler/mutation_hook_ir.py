"""Target-neutral lowering contract for draw-state mutations.

This pass is deliberately earlier than both the C and Z80 backends.  It does
not patch the active Python gameplay module and it does not emit target code.
Instead it proves that every source construct which can affect the compact
draw VM has one explicit lowering rule:

* ordinary attribute stores become ``sync-if-bound`` hooks which reuse the
  already evaluated receiver and store value;
* dataclass field declarations become inputs to the atomic bind snapshot;
* derived properties become small expression programs evaluated when an
  object view is loaded, so nested dependencies cannot become stale;
* finite dynamic ``setattr`` names are resolved by a string-set lattice;
* pool identity operations become bind/clear/replace hooks or proved call
  edges to the instrumented pool primitive.

The result is source-derived and fail-closed.  ``live`` remains false until a
future object-aware frontend and backend consume these hooks and a linked
stack/tstate certificate covers them.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .draw_state_backend import DrawStateModel, build_draw_state_model
from .render_order_backend import build_render_order_model


MUTATION_HOOK_IR_FORMAT = "pyz80.mutation-hook-ir.v1"

__all__ = [
    "MUTATION_HOOK_IR_FORMAT",
    "DerivedExpression",
    "DerivedProgram",
    "MutationHookIRError",
    "MutationHookPlan",
    "build_mutation_hook_ir",
    "evaluate_derived_expression",
    "write_mutation_hook_report",
]


class MutationHookIRError(ValueError):
    """The active source no longer admits a complete, sound hook plan."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _ast_sha256(value: ast.AST) -> str:
    return _sha256_text(ast.dump(value, include_attributes=False))


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _json_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"


def _semantic_sha256(value: object) -> str:
    return _sha256_bytes(_json_bytes(value))


@dataclass(frozen=True)
class DerivedExpression:
    """Small, serializable expression tree independent of a target ABI."""

    op: str
    arguments: tuple["DerivedExpression", ...] = ()
    value: object | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"op": self.op}
        if self.arguments:
            result["arguments"] = [item.as_dict() for item in self.arguments]
        if self.value is not None:
            result["value"] = (list(self.value)
                               if isinstance(self.value, tuple)
                               else self.value)
        return result


@dataclass(frozen=True)
class DerivedProgram:
    program_id: int
    field_name: str
    field_id: int
    owner_class: str
    line: int
    getter_ast_sha256: str
    expression: DerivedExpression
    dependency_paths: tuple[tuple[str, ...], ...]
    applies_to_class_ids: tuple[int, ...]
    semantic_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "field": self.field_name,
            "field_id": self.field_id,
            "owner_class": self.owner_class,
            "line": self.line,
            "getter_ast_sha256": self.getter_ast_sha256,
            "expression": self.expression.as_dict(),
            "dependency_paths": [list(item)
                                 for item in self.dependency_paths],
            "applies_to_class_ids": list(self.applies_to_class_ids),
            "semantic_sha256": self.semantic_sha256,
            "evaluation_point": "provider-object-view-load",
            "cached_value": False,
        }


@dataclass(frozen=True)
class MutationHookPlan:
    source_path: str
    source_sha256: str
    launcher_sha256: str
    draw_state_semantic_sha256: str
    analyzer_sha256: str
    compiler_input_sha256: tuple[tuple[str, str], ...]
    slot_normalization: dict[str, object]
    fields: tuple[dict[str, object], ...]
    mutation_hooks: tuple[dict[str, object], ...]
    derived_programs: tuple[DerivedProgram, ...]
    derived_dispatch: tuple[int, ...]
    derived_reads: tuple[dict[str, object], ...]
    dynamic_setattrs: tuple[dict[str, object], ...]
    lifecycle_hooks: tuple[dict[str, object], ...]
    coverage: dict[str, object]
    semantic_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "format": MUTATION_HOOK_IR_FORMAT,
            "status": "TARGET_NEUTRAL_HOOK_IR_COMPLETE_LIVE_BLOCKED",
            "live": False,
            "source": {
                "path": self.source_path,
                "sha256": self.source_sha256,
                "launcher": "run_python.cmd",
                "launcher_sha256": self.launcher_sha256,
                "entrypoint": "rtype_port.app",
            },
            "pinned_draw_state_semantic_sha256": (
                self.draw_state_semantic_sha256),
            "analyzer": {
                "path": "Source/Tools/pyz80_compiler/mutation_hook_ir.py",
                "sha256": self.analyzer_sha256,
            },
            "compiler_integration_inputs": [
                {"path": path, "sha256": digest}
                for path, digest in self.compiler_input_sha256
            ],
            "slot_normalization": self.slot_normalization,
            "semantic_sha256": self.semantic_sha256,
            "field_schema": list(self.fields),
            "mutation_hooks": list(self.mutation_hooks),
            "derived_fields": {
                "strategy": "evaluate-at-provider-load",
                "reason": (
                    "nested source dependencies remain authoritative; no "
                    "derived-value cache can become stale"),
                "programs": [item.as_dict()
                             for item in self.derived_programs],
                "class_id_to_program_id": list(self.derived_dispatch),
                "dispatch_derivation": (
                    "active Python class graph plus guarded isinstance set"),
                "manual_object_type_switch": False,
                "read_sites": list(self.derived_reads),
            },
            "dynamic_setattrs": list(self.dynamic_setattrs),
            "lifecycle_hooks": list(self.lifecycle_hooks),
            "coverage": self.coverage,
            "frontend_integration_contract": {
                "attribute_store": [
                    "evaluate RHS once using Python order",
                    "evaluate lvalue receiver once",
                    "perform the original gameplay store",
                    "emit draw-sync-if-bound with the same receiver/value SSA temps",
                ],
                "augmented_attribute_store": [
                    "evaluate receiver once and load old value once",
                    "evaluate RHS once and compute the Python result once",
                    "store once, then reuse the result temp for draw-sync-if-bound",
                ],
                "bind": (
                    "one generic source-derived class-id table plus an atomic "
                    "snapshot; no object-kind switch"),
                "derived_read": (
                    "static program id or generated class-id dispatch table; "
                    "the provider evaluates it before the compact VM reads "
                    "the normalized field"),
                "pipeline_gate": (
                    "compile/link hook support only after the object-aware "
                    "frontend consumes every hook id and target layout, stack, "
                    "queue and tstate certificates all pass"),
                "current_frontend_supports_object_store_fragments": True,
                "current_frontend_supports_full_object_gameplay_cfg": False,
                "current_pipeline_consumes_this_ir": False,
            },
            "live_blockers": [
                "object stores have effect SSA but the complete gameplay "
                "class/CFG frontend is not lowered",
                "target object layout and slot-to-object resolver are not lowered",
                "the C backend does not consume draw-sync/bind/clear/replace ops",
                "the VM provider does not yet evaluate derived getter programs",
                "linked stack, tstate and frame-queue certificates exclude hooks",
            ],
        }


def _decorator_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Call):
        return _decorator_name(value.func)
    return None


def _attribute_path(value: ast.AST) -> tuple[str, ...] | None:
    result: list[str] = []
    cursor = value
    while isinstance(cursor, ast.Attribute):
        result.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    result.append(cursor.id)
    return tuple(reversed(result))


def _contains(container: ast.AST, child: ast.AST) -> bool:
    return any(item is child for item in ast.walk(container))


def _same_suite_precedes(
        tree: ast.AST, first: ast.stmt, second: ast.stmt,
        ) -> bool:
    """True only when both statements share one ordered AST statement list."""
    for owner in ast.walk(tree):
        for _name, value in ast.iter_fields(owner):
            if not isinstance(value, list):
                continue
            try:
                first_index = next(index for index, item in enumerate(value)
                                   if item is first)
                second_index = next(index for index, item in enumerate(value)
                                    if item is second)
            except StopIteration:
                continue
            return first_index < second_index
    return False


class _SourceInventory(ast.NodeVisitor):
    """Independent AST census used to cross-check the sidecar inventory."""

    def __init__(self, source: str, fields: Iterable[str]) -> None:
        self.source = source
        self.fields = frozenset(fields)
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.mutations: list[dict[str, object]] = []
        self.derived: list[dict[str, object]] = []
        self.dynamic: list[tuple[ast.Call, str | None, str | None]] = []
        self.identities: list[dict[str, object]] = []

    @property
    def class_name(self) -> str | None:
        return self.class_stack[-1] if self.class_stack else None

    @property
    def function_name(self) -> str | None:
        return self.function_stack[-1] if self.function_stack else None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if (self.class_name and node.name in self.fields and
                any(_decorator_name(item) == "property"
                    for item in node.decorator_list)):
            self.derived.append({
                "field": node.name,
                "class": self.class_name,
                "line": node.lineno,
                "ast_sha256": _ast_sha256(node),
                "node": node,
            })
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _mutation(
            self, target: ast.AST, statement: ast.AST, kind: str,
            value: ast.AST | None,
            ) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._mutation(item, statement, kind, value)
            return
        if not isinstance(target, ast.Attribute) or target.attr not in self.fields:
            return
        source_text = (ast.get_source_segment(self.source, statement) or
                       ast.unparse(statement))
        extra = ((ast.dump(value, include_attributes=False)
                  if value is not None else "") + "\n" + source_text)
        payload = {
            "statement": ast.dump(statement, include_attributes=False),
            "target": ast.dump(target, include_attributes=False),
            "field": target.attr,
            "kind": kind,
            "line": getattr(target, "lineno", statement.lineno),
            "column": getattr(target, "col_offset", 0),
            "extra": extra,
        }
        self.mutations.append({
            "field": target.attr,
            "kind": kind,
            "line": int(payload["line"]),
            "column": int(payload["column"]),
            "class": self.class_name,
            "function": self.function_name,
            "receiver": ast.unparse(target.value),
            "statement_ast_sha256": _ast_sha256(statement),
            "site_ast_sha256": _semantic_sha256(payload),
        })

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self._mutation(target, node, "assign", node.value)
        self._identity_assignment(node, node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if (isinstance(node.target, ast.Name) and self.class_name and
                node.target.id in self.fields):
            source_text = (ast.get_source_segment(self.source, node) or
                           ast.unparse(node))
            extra = ((ast.dump(node.value, include_attributes=False)
                      if node.value is not None
                      else "required-constructor-value") + "\n" + source_text)
            payload = {
                "statement": ast.dump(node, include_attributes=False),
                "target": ast.dump(node.target, include_attributes=False),
                "field": node.target.id,
                "kind": "class-field-initializer",
                "line": node.target.lineno,
                "column": node.target.col_offset,
                "extra": extra,
            }
            self.mutations.append({
                "field": node.target.id,
                "kind": "class-field-initializer",
                "line": node.target.lineno,
                "column": node.target.col_offset,
                "class": self.class_name,
                "function": self.function_name,
                "receiver": self.class_name,
                "statement_ast_sha256": _ast_sha256(node),
                "site_ast_sha256": _semantic_sha256(payload),
            })
        else:
            self._mutation(node.target, node, "annassign", node.value)
        self._identity_assignment(node, (node.target,), node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self._mutation(node.target, node, "augassign", node.value)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:  # noqa: N802
        for target in node.targets:
            self._mutation(target, node, "delete", None)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (isinstance(node.func, ast.Name) and node.func.id == "setattr" and
                len(node.args) >= 2):
            name = node.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                if name.value in self.fields:
                    synthetic = ast.Attribute(
                        value=node.args[0], attr=name.value, ctx=ast.Store(),
                        lineno=node.lineno, col_offset=node.col_offset)
                    self._mutation(
                        synthetic, node, "setattr-literal",
                        node.args[2] if len(node.args) >= 3 else None)
            else:
                self.dynamic.append(
                    (node, self.class_name, self.function_name))
        if isinstance(node.func, ast.Attribute):
            receiver = ast.unparse(node.func.value)
            kind: str | None = None
            if (node.func.attr == "bind" and
                    (receiver == "object_pool" or
                     receiver.endswith(".object_pool"))):
                kind = "pool-bind"
            elif (node.func.attr == "release" and
                  (receiver == "object_pool" or
                   receiver.endswith(".object_pool"))):
                kind = "pool-release"
            if kind is not None:
                self.identities.append(self._identity(kind, node))
        self.generic_visit(node)

    def _identity_assignment(
            self, node: ast.Assign | ast.AnnAssign,
            targets: Iterable[ast.expr], value: ast.expr | None,
            ) -> None:
        if not any(isinstance(target, ast.Attribute) and
                   target.attr == "object_slot" for target in targets):
            return
        if isinstance(value, ast.Attribute) and value.attr == "object_slot":
            kind = "same-slot-object-replacement"
        elif isinstance(value, ast.Constant) and value.value is None:
            kind = ("same-slot-old-owner-detach" if
                    self.class_name == "M72EnemyWorld" and
                    self.function_name == "update" else
                    "pool-release-assignment")
        elif (self.class_name == "M72ObjectPool" and
              self.function_name == "bind"):
            kind = "pool-bind-assignment"
        else:
            kind = "checkpoint-bind-assignment"
        self.identities.append(self._identity(kind, node))

    def _identity(self, kind: str, node: ast.AST) -> dict[str, object]:
        return {
            "kind": kind,
            "line": node.lineno,
            "class": self.class_name,
            "function": self.function_name,
            "ast_sha256": _ast_sha256(node),
            "node": node,
        }


def _class_nodes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body
            if isinstance(node, ast.ClassDef)}


def _local_bases(node: ast.ClassDef, classes: Mapping[str, ast.ClassDef]) -> tuple[str, ...]:
    result: list[str] = []
    for base in node.bases:
        name = (base.id if isinstance(base, ast.Name) else
                base.attr if isinstance(base, ast.Attribute) else None)
        if name in classes:
            result.append(name)
    return tuple(result)


def _lineages(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    classes = _class_nodes(tree)
    memo: dict[str, tuple[str, ...]] = {}
    visiting: set[str] = set()

    def visit(name: str) -> tuple[str, ...]:
        known = memo.get(name)
        if known is not None:
            return known
        if name in visiting:
            raise MutationHookIRError(
                "PZMH001", f"cycle in active class graph at {name!r}")
        visiting.add(name)
        bases = _local_bases(classes[name], classes)
        if len(bases) > 1:
            raise MutationHookIRError(
                "PZMH001", f"multiple local inheritance is not lowered for {name!r}")
        result = (name,) + (visit(bases[0]) if bases else ())
        visiting.remove(name)
        memo[name] = result
        return result

    for name in classes:
        visit(name)
    return memo


def _lower_expression(node: ast.expr) -> DerivedExpression:
    path = _attribute_path(node)
    if path is not None and path[0] == "self" and len(path) > 1:
        return DerivedExpression("load-path", value=path[1:])
    if isinstance(node, ast.Constant) and isinstance(
            node.value, (bool, int, str, type(None))):
        return DerivedExpression("constant", value=node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        values: list[object] = []
        for item in node.elts:
            if not isinstance(item, ast.Constant) or not isinstance(
                    item.value, (bool, int, str, type(None))):
                raise MutationHookIRError(
                    "PZMH002", "derived tuple/list is not literal")
            values.append(item.value)
        return DerivedExpression("constant-sequence", value=tuple(values))
    if isinstance(node, ast.IfExp):
        return DerivedExpression("select", (
            _lower_expression(node.test), _lower_expression(node.body),
            _lower_expression(node.orelse)))
    if isinstance(node, ast.BoolOp):
        operator = {ast.And: "and", ast.Or: "or"}.get(type(node.op))
        if operator is None or len(node.values) < 2:
            raise MutationHookIRError("PZMH002", "unsupported derived boolop")
        return DerivedExpression(
            "boolop", tuple(_lower_expression(item) for item in node.values),
            operator)
    if isinstance(node, ast.BinOp):
        operator = {
            ast.BitAnd: "bitand", ast.BitOr: "bitor", ast.BitXor: "bitxor",
            ast.Add: "add", ast.Sub: "sub", ast.LShift: "lshift",
            ast.RShift: "rshift",
        }.get(type(node.op))
        if operator is None:
            raise MutationHookIRError(
                "PZMH002", f"unsupported derived binary {type(node.op).__name__}")
        return DerivedExpression(
            "binary", (_lower_expression(node.left),
                       _lower_expression(node.right)), operator)
    if isinstance(node, ast.UnaryOp):
        operator = {ast.Not: "not", ast.Invert: "invert",
                    ast.USub: "neg", ast.UAdd: "pos"}.get(type(node.op))
        if operator is None:
            raise MutationHookIRError("PZMH002", "unsupported derived unary")
        return DerivedExpression("unary", (_lower_expression(node.operand),),
                                 operator)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(
            node.comparators) == 1:
        operator = {
            ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le",
            ast.Gt: "gt", ast.GtE: "ge", ast.In: "in",
            ast.NotIn: "not-in", ast.Is: "is", ast.IsNot: "is-not",
        }.get(type(node.ops[0]))
        if operator is None:
            raise MutationHookIRError("PZMH002", "unsupported derived compare")
        return DerivedExpression(
            "compare", (_lower_expression(node.left),
                        _lower_expression(node.comparators[0])), operator)
    raise MutationHookIRError(
        "PZMH002", f"unsupported derived expression {ast.unparse(node)!r}")


def _lower_getter(node: ast.FunctionDef) -> DerivedExpression:
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr) and
            isinstance(body[0].value, ast.Constant) and
            isinstance(body[0].value.value, str)):
        body.pop(0)

    def sequence(statements: list[ast.stmt]) -> DerivedExpression:
        if len(statements) == 1 and isinstance(statements[0], ast.Return):
            if statements[0].value is None:
                raise MutationHookIRError("PZMH003", "derived getter returns None")
            return _lower_expression(statements[0].value)
        if statements and isinstance(statements[0], ast.If):
            branch = statements[0]
            if len(branch.body) != 1 or not isinstance(branch.body[0], ast.Return):
                raise MutationHookIRError(
                    "PZMH003", "derived getter branch is not one return")
            when_true = branch.body[0].value
            if when_true is None:
                raise MutationHookIRError("PZMH003", "derived branch returns None")
            if branch.orelse:
                when_false = sequence(list(branch.orelse))
                if len(statements) != 1:
                    raise MutationHookIRError(
                        "PZMH003", "code follows a complete derived if/else")
            else:
                when_false = sequence(statements[1:])
            return DerivedExpression(
                "select", (_lower_expression(branch.test),
                           _lower_expression(when_true), when_false))
        raise MutationHookIRError(
            "PZMH003", f"getter {node.name} has unsupported control flow")

    return sequence(body)


def _dependency_paths(expression: DerivedExpression) -> tuple[tuple[str, ...], ...]:
    result: set[tuple[str, ...]] = set()

    def walk(value: DerivedExpression) -> None:
        if value.op == "load-path":
            assert isinstance(value.value, tuple)
            result.add(tuple(str(item) for item in value.value))
        for item in value.arguments:
            walk(item)

    walk(expression)
    return tuple(sorted(result))


def evaluate_derived_expression(
        expression: DerivedExpression,
        values: Mapping[tuple[str, ...], object],
        ) -> object:
    """Reference interpreter used by differential tests and later backends."""
    if expression.op == "load-path":
        assert isinstance(expression.value, tuple)
        return values[tuple(str(item) for item in expression.value)]
    if expression.op in ("constant", "constant-sequence"):
        return expression.value
    if expression.op == "select":
        condition = evaluate_derived_expression(expression.arguments[0], values)
        selected = expression.arguments[1] if condition else expression.arguments[2]
        return evaluate_derived_expression(selected, values)
    if expression.op == "boolop":
        if expression.value == "and":
            result: object = True
            for item in expression.arguments:
                result = evaluate_derived_expression(item, values)
                if not result:
                    return result
            return result
        if expression.value == "or":
            result = False
            for item in expression.arguments:
                result = evaluate_derived_expression(item, values)
                if result:
                    return result
            return result
    if expression.op == "binary":
        left = evaluate_derived_expression(expression.arguments[0], values)
        right = evaluate_derived_expression(expression.arguments[1], values)
        operations = {
            "bitand": lambda: int(left) & int(right),
            "bitor": lambda: int(left) | int(right),
            "bitxor": lambda: int(left) ^ int(right),
            "add": lambda: int(left) + int(right),
            "sub": lambda: int(left) - int(right),
            "lshift": lambda: int(left) << int(right),
            "rshift": lambda: int(left) >> int(right),
        }
        action = operations.get(str(expression.value))
        if action is not None:
            return action()
    if expression.op == "unary":
        value = evaluate_derived_expression(expression.arguments[0], values)
        operations = {
            "not": lambda: not value, "invert": lambda: ~int(value),
            "neg": lambda: -int(value), "pos": lambda: +int(value),
        }
        action = operations.get(str(expression.value))
        if action is not None:
            return action()
    if expression.op == "compare":
        left = evaluate_derived_expression(expression.arguments[0], values)
        right = evaluate_derived_expression(expression.arguments[1], values)
        operations = {
            "eq": lambda: left == right, "ne": lambda: left != right,
            "lt": lambda: left < right, "le": lambda: left <= right,
            "gt": lambda: left > right, "ge": lambda: left >= right,
            "in": lambda: left in right, "not-in": lambda: left not in right,
            "is": lambda: left is right, "is-not": lambda: left is not right,
        }
        action = operations.get(str(expression.value))
        if action is not None:
            return action()
    raise MutationHookIRError(
        "PZMH004", f"cannot interpret derived op {expression.op!r}")


def _bound_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(name for item in target.elts for name in _bound_names(item))
    return ()


def _string_definitions(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> dict[str, tuple[ast.expr | None, ...]]:
    """All local reaching values, with ``None`` as an unknown-write marker."""
    result: dict[str, list[ast.expr | None]] = {}
    arguments = (function.args.posonlyargs + function.args.args +
                 function.args.kwonlyargs)
    for argument in arguments:
        result.setdefault(argument.arg, []).append(None)
    if function.args.vararg is not None:
        result.setdefault(function.args.vararg.arg, []).append(None)
    if function.args.kwarg is not None:
        result.setdefault(function.args.kwarg.arg, []).append(None)

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            if node is function:
                for statement in node.body:
                    self.visit(statement)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, _node: ast.ClassDef) -> None:  # noqa: N802
            return

        def visit_Lambda(self, _node: ast.Lambda) -> None:  # noqa: N802
            return

        def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
            for target in node.targets:
                names = _bound_names(target)
                for name in names:
                    result.setdefault(name, []).append(
                        node.value if isinstance(target, ast.Name) else None)
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
            for name in _bound_names(node.target):
                result.setdefault(name, []).append(
                    node.value if isinstance(node.target, ast.Name) else None)
            if node.value is not None:
                self.visit(node.value)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
            for name in _bound_names(node.target):
                result.setdefault(name, []).append(
                    node.value if isinstance(node.target, ast.Name) else None)
            self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
            for name in _bound_names(node.target):
                result.setdefault(name, []).append(None)
            self.visit(node.value)

        def visit_For(self, node: ast.For) -> None:  # noqa: N802
            for name in _bound_names(node.target):
                result.setdefault(name, []).append(None)
            self.generic_visit(node)

        visit_AsyncFor = visit_For

        def visit_With(self, node: ast.With) -> None:  # noqa: N802
            for item in node.items:
                if item.optional_vars is not None:
                    for name in _bound_names(item.optional_vars):
                        result.setdefault(name, []).append(None)
            self.generic_visit(node)

        visit_AsyncWith = visit_With

        def visit_Delete(self, node: ast.Delete) -> None:  # noqa: N802
            for target in node.targets:
                for name in _bound_names(target):
                    result.setdefault(name, []).append(None)

    Visitor().visit(function)
    return {name: tuple(values) for name, values in result.items()}


def _finite_strings(
        node: ast.expr,
        definitions: Mapping[str, tuple[ast.expr | None, ...]],
        constants: Mapping[str, str], visiting: frozenset[str] = frozenset(),
        ) -> frozenset[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return frozenset((node.value,))
    if isinstance(node, ast.IfExp):
        return (_finite_strings(node.body, definitions, constants, visiting) |
                _finite_strings(node.orelse, definitions, constants, visiting))
    if isinstance(node, ast.Name):
        if node.id in constants:
            return frozenset((constants[node.id],))
        if node.id in visiting or node.id not in definitions:
            raise MutationHookIRError(
                "PZMH005", f"dynamic attribute name {node.id!r} is not finite")
        candidates = definitions[node.id]
        if any(item is None for item in candidates):
            raise MutationHookIRError(
                "PZMH005", f"dynamic attribute name {node.id!r} has an "
                "unknown parameter/control-flow write")
        values = frozenset().union(*(
            _finite_strings(item, definitions, constants,
                            visiting | frozenset((node.id,)))
            for item in candidates if item is not None))
        if not values:
            raise MutationHookIRError(
                "PZMH005", f"dynamic attribute name {node.id!r} is empty")
        return values
    raise MutationHookIRError(
        "PZMH005", f"dynamic attribute name is not a finite string set: "
        f"{ast.unparse(node)!r}")


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    definitions: dict[str, list[object]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                for name in _bound_names(target):
                    value: object = statement.value
                    definitions.setdefault(name, []).append(value)
        elif isinstance(statement, ast.AnnAssign):
            for name in _bound_names(statement.target):
                definitions.setdefault(name, []).append(statement.value)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            for name in _bound_names(statement.target):
                definitions.setdefault(name, []).append(None)
    result: dict[str, str] = {}
    for name, values in definitions.items():
        if (len(values) == 1 and isinstance(values[0], ast.Constant) and
                isinstance(values[0].value, str)):
            result[name] = values[0].value
    return result


def _guard_classes(node: ast.expr, receiver: ast.expr) -> tuple[str, ...] | None:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
            node.func.id == "isinstance" and len(node.args) == 2 and
            not node.keywords and
            ast.dump(node.args[0], include_attributes=False) ==
            ast.dump(receiver, include_attributes=False)):
        return None
    classes = node.args[1].elts if isinstance(node.args[1], ast.Tuple) else (
        node.args[1],)
    if not all(isinstance(item, ast.Name) for item in classes):
        return None
    return tuple(item.id for item in classes if isinstance(item, ast.Name))


def _method_contexts(tree: ast.Module) -> list[tuple[int, int, str, str, ast.AST]]:
    result: list[tuple[int, int, str, str, ast.AST]] = []
    for class_node in tree.body:
        if not isinstance(class_node, ast.ClassDef):
            continue
        for function in class_node.body:
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append((
                    function.lineno,
                    getattr(function, "end_lineno", function.lineno),
                    class_node.name, function.name, function))
    return result


def _field_encoding(field: object, field_id: int) -> dict[str, object]:
    if field.kind == "string_state":
        encoding = "generated-string-tag-other-zero"
    elif field.kind == "boolean":
        encoding = "python-truth-to-u8"
    elif field.c_type == "int16_t":
        encoding = "low16-two-complement-i16"
    elif field.c_type == "uint16_t":
        encoding = "low16-u16"
    elif field.c_type == "uint8_t":
        encoding = "low8-u8"
    else:
        raise MutationHookIRError(
            "PZMH006", f"field {field.name!r} has unsupported ABI {field.c_type}")
    result: dict[str, object] = {
        "field_id": field_id,
        "name": field.name,
        "kind": field.kind,
        "c_type": field.c_type,
        "value_encoding": encoding,
    }
    if field.string_values:
        result["string_tags"] = {
            value: index + 1 for index, value in enumerate(field.string_values)}
        result["other_tag"] = 0
    if field.getattr_default is not None:
        result["getattr_default"] = field.getattr_default
    return result


def _cross_check_inventory(model: DrawStateModel, inventory: _SourceInventory) -> None:
    independent = sorted(
        inventory.mutations,
        key=lambda item: (int(item["line"]), int(item["column"]),
                          str(item["field"]), str(item["kind"])))
    expected = [{
        "field": item.field_name,
        "kind": item.kind,
        "line": item.line,
        "column": item.column,
        "class": item.class_name,
        "function": item.function_name,
        "receiver": item.receiver,
        "statement_ast_sha256": item.statement_ast_sha256,
        "site_ast_sha256": item.site_ast_sha256,
    } for item in model.mutation_sites]
    if independent != expected:
        raise MutationHookIRError(
            "PZMH007", "independent mutation census differs from draw sidecar")

    actual_derived = sorted(
        ({key: item[key] for key in ("field", "class", "line", "ast_sha256")}
         for item in inventory.derived),
        key=lambda item: (int(item["line"]), str(item["class"])))
    expected_derived = [{
        "field": item.field_name, "class": item.class_name,
        "line": item.line, "ast_sha256": item.ast_sha256,
    } for item in model.derived_field_sites]
    if actual_derived != expected_derived:
        raise MutationHookIRError(
            "PZMH007", "independent derived-field census differs from sidecar")

    actual_dynamic = sorted(
        ((node.lineno, class_name, function_name, _ast_sha256(node))
         for node, class_name, function_name in inventory.dynamic))
    expected_dynamic = sorted(
        (item.line, item.class_name, item.function_name, item.ast_sha256)
        for item in model.dynamic_write_sites)
    if actual_dynamic != expected_dynamic:
        raise MutationHookIRError(
            "PZMH007", "independent dynamic-setattr census differs from sidecar")

    actual_identities = sorted(
        ({key: item[key] for key in
          ("kind", "line", "class", "function", "ast_sha256")}
         for item in inventory.identities),
        key=lambda item: (int(item["line"]), str(item["kind"])))
    expected_identities = [{
        "kind": item.kind, "line": item.line, "class": item.class_name,
        "function": item.function_name, "ast_sha256": item.ast_sha256,
    } for item in model.identity_sites]
    if actual_identities != expected_identities:
        raise MutationHookIRError(
            "PZMH007", "independent identity census differs from sidecar")


def build_mutation_hook_ir(
        project_root: Path | str, *, state_model: DrawStateModel | None = None,
        ) -> MutationHookPlan:
    """Build a complete target-neutral hook plan from the active source."""
    root = Path(project_root).resolve()
    source_path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode("utf-8")
    tree = ast.parse(source, filename=str(source_path), type_comments=True)
    active_model = build_draw_state_model(root)
    order_model = build_render_order_model(root)
    compiler_inputs = tuple(
        (path, _sha256_bytes((root / path).read_bytes()))
        for path in (
            "Source/Tools/pyz80_compiler/frontend.py",
            "Source/Tools/pyz80_compiler/ir.py",
            "Source/Tools/pyz80_compiler/pipeline.py",
        ))
    analyzer_sha256 = _sha256_bytes(Path(__file__).read_bytes())
    model = state_model or active_model
    for name in ("source_sha256", "launcher_sha256", "semantic_sha256"):
        if getattr(model, name) != getattr(active_model, name):
            raise MutationHookIRError(
                "PZMH008", f"provided draw-state model differs at {name}")
    if model.source_sha256 != _sha256_bytes(source_bytes):
        raise MutationHookIRError(
            "PZMH008", "draw-state model is not bound to active source bytes")
    if (order_model.source_sha256 != model.source_sha256 or
            order_model.semantic_sha256 != model.render_order_semantic_sha256):
        raise MutationHookIRError(
            "PZMH008", "render-order slot model differs from draw-state input")
    slot_normalization: dict[str, object] = {
        "python_representation": "physical 64-byte object-record address",
        "hook_representation": "compact uint8 slot index",
        "physical_first": order_model.slot_first,
        "physical_stop_exclusive": order_model.slot_stop_exclusive,
        "physical_stride": order_model.slot_stride,
        "slot_count": order_model.slot_count,
        "formula": "(physical_slot - physical_first) / physical_stride",
        "checks": ["not-none", "range", "stride-alignment"],
        "source_derived": True,
    }

    field_names = tuple(item.name for item in model.fields)
    field_ids = {name: index for index, name in enumerate(field_names)}
    inventory = _SourceInventory(source, field_names)
    inventory.visit(tree)
    _cross_check_inventory(model, inventory)

    fields = tuple(_field_encoding(field, index)
                   for index, field in enumerate(model.fields))
    mutation_hooks: list[dict[str, object]] = []
    for site in model.mutation_sites:
        schema = site.kind == "class-field-initializer"
        mutation_hooks.append({
            "site_id": site.ordinal,
            "site_ast_sha256": site.site_ast_sha256,
            "statement_ast_sha256": site.statement_ast_sha256,
            "line": site.line,
            "column": site.column,
            "class": site.class_name,
            "function": site.function_name,
            "receiver": site.receiver,
            "field": site.field_name,
            "field_id": field_ids[site.field_name],
            "source_kind": site.kind,
            "hook_op": ("bind-schema-field" if schema
                        else "draw-sync-if-bound"),
            "runtime_hook_required": not schema,
            "insertion_phase": (
                "atomic-bind-snapshot" if schema else "immediately-after-store"),
            "reuse_lowered_receiver_temp": not schema,
            "reuse_lowered_value_temp": not schema,
            "rhs_evaluated_once": True,
            "receiver_evaluated_once": True,
            "slot_lookup": "receiver.object_slot then checked normalization",
        })

    classes = _class_nodes(tree)
    lineages = _lineages(tree)
    getter_nodes: dict[str, ast.FunctionDef] = {}
    for item in inventory.derived:
        owner = str(item["class"])
        node = item["node"]
        assert isinstance(node, ast.FunctionDef)
        if owner in getter_nodes:
            raise MutationHookIRError(
                "PZMH009", f"duplicate derived getter in {owner!r}")
        getter_nodes[owner] = node

    # Find the source guard which makes the dynamic property access valid.
    parents = {child: parent for parent in ast.walk(tree)
               for child in ast.iter_child_nodes(parent)}
    active_reads = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute) and
                    isinstance(node.ctx, ast.Load) and
                    node.attr == "active_palette"]
    guarded_classes: set[str] = set()
    guard_hashes: set[str] = set()
    for read in active_reads:
        if isinstance(read.value, ast.Name) and read.value.id == "self":
            continue
        cursor: ast.AST | None = read
        matched = False
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.IfExp) and _contains(cursor.body, read):
                names = _guard_classes(cursor.test, read.value)
                if names is not None:
                    guarded_classes.update(names)
                    guard_hashes.add(_ast_sha256(cursor.test))
                    matched = True
                    break
        if not matched:
            raise MutationHookIRError(
                "PZMH010", f"dynamic active_palette read at line "
                f"{read.lineno} lacks a source-derived isinstance guard")

    # Every guarded concrete class resolves its property through the active
    # single-inheritance graph.  The table is generated, not handwritten.
    owner_for_class: dict[str, str] = {}
    for concrete in model.concrete_classes:
        lineage = lineages.get(concrete.name)
        if lineage is None:
            raise MutationHookIRError(
                "PZMH011", f"sidecar class {concrete.name!r} left AST graph")
        guarded = any(name in guarded_classes for name in lineage)
        owners = [name for name in lineage if name in getter_nodes]
        if guarded:
            if not owners:
                raise MutationHookIRError(
                    "PZMH011", f"guarded class {concrete.name!r} has no getter")
            owner_for_class[concrete.name] = owners[0]
        elif owners:
            # A source getter which cannot be reached by the draw guard would
            # make the sidecar field ambiguous and must be reviewed.
            raise MutationHookIRError(
                "PZMH011", f"getter-bearing class {concrete.name!r} is absent "
                "from the active draw guard")

    owners = sorted(getter_nodes, key=lambda name: getter_nodes[name].lineno)
    program_ids = {name: index for index, name in enumerate(owners)}
    class_ids_by_owner: dict[str, list[int]] = {name: [] for name in owners}
    dispatch: list[int] = []
    for concrete in model.concrete_classes:
        owner = owner_for_class.get(concrete.name)
        program_id = program_ids[owner] if owner is not None else -1
        dispatch.append(program_id)
        if owner is not None:
            class_ids_by_owner[owner].append(concrete.class_id)

    derived_programs: list[DerivedProgram] = []
    for owner in owners:
        node = getter_nodes[owner]
        expression = _lower_getter(node)
        payload = {
            "field": node.name,
            "field_id": field_ids[node.name],
            "owner": owner,
            "getter_ast_sha256": _ast_sha256(node),
            "expression": expression.as_dict(),
            "dependencies": [list(item)
                             for item in _dependency_paths(expression)],
            "class_ids": class_ids_by_owner[owner],
        }
        derived_programs.append(DerivedProgram(
            program_id=program_ids[owner], field_name=node.name,
            field_id=field_ids[node.name], owner_class=owner,
            line=node.lineno, getter_ast_sha256=_ast_sha256(node),
            expression=expression,
            dependency_paths=_dependency_paths(expression),
            applies_to_class_ids=tuple(class_ids_by_owner[owner]),
            semantic_sha256=_semantic_sha256(payload),
        ))
    if any(not item.applies_to_class_ids for item in derived_programs):
        raise MutationHookIRError(
            "PZMH011", "one or more derived programs have no concrete class")

    contexts = _method_contexts(tree)
    derived_reads: list[dict[str, object]] = []
    for read_id, read in enumerate(sorted(
            active_reads, key=lambda item: (item.lineno, item.col_offset))):
        matches = [item for item in contexts if item[0] <= read.lineno <= item[1]]
        if len(matches) != 1:
            raise MutationHookIRError(
                "PZMH012", f"active_palette read at {read.lineno} lacks method")
        _start, _end, class_name, function_name, _function = matches[0]
        if isinstance(read.value, ast.Name) and read.value.id == "self":
            candidates = [name for name in lineages[class_name]
                          if name in getter_nodes]
            if not candidates:
                raise MutationHookIRError(
                    "PZMH012", f"static read in {class_name} has no getter")
            dispatch_kind = "static-program-id"
            program_id: int | None = program_ids[candidates[0]]
        else:
            dispatch_kind = "generated-class-id-table"
            program_id = None
        derived_reads.append({
            "read_id": read_id,
            "line": read.lineno,
            "column": read.col_offset,
            "class": class_name,
            "function": function_name,
            "receiver": ast.unparse(read.value),
            "ast_sha256": _ast_sha256(read),
            "dispatch": dispatch_kind,
            "program_id": program_id,
            "runtime_hook_required": True,
        })

    functions = {node: _string_definitions(node)
                 for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    module_strings = _module_string_constants(tree)
    dynamic_setattrs: list[dict[str, object]] = []
    for dynamic_id, (node, class_name, function_name) in enumerate(sorted(
            inventory.dynamic, key=lambda item: (item[0].lineno,
                                                  item[0].col_offset))):
        containing = [function for function in functions
                      if function.lineno <= node.lineno <=
                      getattr(function, "end_lineno", function.lineno)]
        if not containing:
            raise MutationHookIRError(
                "PZMH013", f"dynamic setattr at {node.lineno} lacks function")
        function = max(containing, key=lambda item: item.lineno)
        possible = tuple(sorted(_finite_strings(
            node.args[1], functions[function], module_strings)))
        overlap = tuple(name for name in possible if name in field_ids)
        dynamic_setattrs.append({
            "dynamic_site_id": dynamic_id,
            "line": node.lineno,
            "column": node.col_offset,
            "class": class_name,
            "function": function_name,
            "ast_sha256": _ast_sha256(node),
            "name_expression_ast_sha256": _ast_sha256(node.args[1]),
            "possible_attribute_names": list(possible),
            "draw_field_intersection": list(overlap),
            "lowering": ("generated-field-id-dispatch" if overlap
                         else "proved-disjoint-no-hook"),
            "runtime_hook_required": bool(overlap),
            "proof": "finite-string-set-lattice",
        })

    identities = sorted(
        inventory.identities,
        key=lambda item: (int(item["line"]), str(item["kind"])))
    authoritative = {
        "pool-bind-assignment": ("bind-snapshot", "after-slot-store"),
        "pool-release-assignment": ("clear-captured-slot", "after-slot-store"),
        "checkpoint-bind-assignment": ("bind-snapshot", "after-slot-store"),
        "same-slot-object-replacement": (
            "replace-same-slot-snapshot", "after-slot-store"),
        "same-slot-old-owner-detach": (
            "proved-replacement-detach-no-op", "after-slot-store"),
    }
    bind_primitive = next((item for item in identities
                           if item["kind"] == "pool-bind-assignment"), None)
    release_primitive = next((item for item in identities
                              if item["kind"] == "pool-release-assignment"), None)
    replace_site = next((item for item in identities
                         if item["kind"] == "same-slot-object-replacement"), None)
    detach_site = next((item for item in identities
                        if item["kind"] == "same-slot-old-owner-detach"), None)
    if bind_primitive is None or release_primitive is None:
        raise MutationHookIRError(
            "PZMH014", "pool bind/release primitive assignment is missing")
    if (replace_site is None) != (detach_site is None):
        raise MutationHookIRError(
            "PZMH014", "same-slot replacement/detach pair is incomplete")
    if replace_site is not None and detach_site is not None:
        replace_node = replace_site["node"]
        detach_node = detach_site["node"]
        if not (isinstance(replace_node, ast.Assign) and
                isinstance(detach_node, ast.Assign) and
                replace_site["class"] == detach_site["class"] ==
                "M72EnemyWorld" and
                replace_site["function"] == detach_site["function"] ==
                "update" and int(replace_site["line"]) < int(detach_site["line"])):
            raise MutationHookIRError(
                "PZMH014", "replacement does not lexically precede old detach")
        replace_target = _attribute_path(replace_node.targets[0])
        replace_value = _attribute_path(replace_node.value)
        detach_target = _attribute_path(detach_node.targets[0])
        if not (_same_suite_precedes(tree, replace_node, detach_node) and
                replace_target == ("explosion", "object_slot") and
                replace_value == ("enemy", "object_slot") and
                detach_target == replace_value and
                isinstance(detach_node.value, ast.Constant) and
                detach_node.value.value is None):
            raise MutationHookIRError(
                "PZMH014", "old-owner detach is not dominated by the exact "
                "same-suite replacement")

    lifecycle_hooks: list[dict[str, object]] = []
    for identity_id, item in enumerate(identities):
        kind = str(item["kind"])
        if kind == "pool-bind":
            operation, phase = "delegate-to-pool-bind-primitive", "call-edge"
            authority_line = int(bind_primitive["line"])
        elif kind == "pool-release":
            operation, phase = "delegate-to-pool-release-primitive", "call-edge"
            authority_line = int(release_primitive["line"])
        else:
            try:
                operation, phase = authoritative[kind]
            except KeyError as exc:
                raise MutationHookIRError(
                    "PZMH014", f"identity kind {kind!r} has no lowering") from exc
            authority_line = int(item["line"])
        lifecycle_hooks.append({
            "identity_site_id": identity_id,
            "kind": kind,
            "line": item["line"],
            "class": item["class"],
            "function": item["function"],
            "ast_sha256": item["ast_sha256"],
            "hook_op": operation,
            "insertion_phase": phase,
            "authoritative_primitive_line": authority_line,
            "capture_slot_before_store": kind in (
                "pool-release-assignment", "same-slot-object-replacement"),
            "slot_normalization_required": kind != "same-slot-old-owner-detach",
            "source_covered": True,
        })

    direct_runtime = sum(bool(item["runtime_hook_required"])
                         for item in mutation_hooks)
    schema_count = len(mutation_hooks) - direct_runtime
    coverage: dict[str, object] = {
        "complete_ast_coverage": True,
        "independent_census_matches_draw_state": True,
        "counts": {
            "direct_and_implicit_candidates": len(model.mutation_sites),
            "direct_runtime_sync_hooks": direct_runtime,
            "implicit_bind_schema_fields": schema_count,
            "direct_and_implicit_lowered": len(mutation_hooks),
            "derived_getter_candidates": len(model.derived_field_sites),
            "derived_getter_programs": len(derived_programs),
            "derived_read_candidates": len(active_reads),
            "derived_reads_lowered": len(derived_reads),
            "dynamic_setattr_candidates": len(model.dynamic_write_sites),
            "dynamic_setattrs_lowered": len(dynamic_setattrs),
            "dynamic_setattrs_proved_disjoint": sum(
                not bool(item["runtime_hook_required"])
                for item in dynamic_setattrs),
            "lifecycle_identity_candidates": len(model.identity_sites),
            "lifecycle_identities_lowered": len(lifecycle_hooks),
        },
        "guard_class_names": sorted(guarded_classes),
        "guard_ast_sha256": sorted(guard_hashes),
        "all_mutation_site_ids_unique": (
            len({item["site_id"] for item in mutation_hooks}) ==
            len(mutation_hooks)),
        "all_derived_program_ids_unique": (
            len({item.program_id for item in derived_programs}) ==
            len(derived_programs)),
        "derived_dispatch_entries": len(dispatch),
        "concrete_class_count": len(model.concrete_classes),
        "manual_object_type_switch": False,
        "physical_slot_normalization_source_derived": True,
        "gameplay_source_modified": False,
        "runtime_hooks_installed": False,
        "live_claimed": False,
    }
    counts = coverage["counts"]
    assert isinstance(counts, dict)
    if not (
            counts["direct_and_implicit_candidates"] ==
            counts["direct_and_implicit_lowered"] and
            counts["derived_getter_candidates"] ==
            counts["derived_getter_programs"] and
            counts["derived_read_candidates"] ==
            counts["derived_reads_lowered"] and
            counts["dynamic_setattr_candidates"] ==
            counts["dynamic_setattrs_lowered"] and
            counts["lifecycle_identity_candidates"] ==
            counts["lifecycle_identities_lowered"]):
        raise MutationHookIRError("PZMH015", "hook coverage is incomplete")

    payload = {
        "format": MUTATION_HOOK_IR_FORMAT,
        "source_sha256": model.source_sha256,
        "draw_state": model.semantic_sha256,
        "analyzer_sha256": analyzer_sha256,
        "compiler_inputs": compiler_inputs,
        "slot_normalization": slot_normalization,
        "fields": fields,
        "mutations": mutation_hooks,
        "derived_programs": [item.as_dict() for item in derived_programs],
        "dispatch": dispatch,
        "derived_reads": derived_reads,
        "dynamic": dynamic_setattrs,
        "identity": lifecycle_hooks,
        "coverage": coverage,
    }
    return MutationHookPlan(
        source_path=model.plan.source_path,
        source_sha256=model.source_sha256,
        launcher_sha256=model.launcher_sha256,
        draw_state_semantic_sha256=model.semantic_sha256,
        analyzer_sha256=analyzer_sha256,
        compiler_input_sha256=compiler_inputs,
        slot_normalization=slot_normalization,
        fields=fields,
        mutation_hooks=tuple(mutation_hooks),
        derived_programs=tuple(derived_programs),
        derived_dispatch=tuple(dispatch),
        derived_reads=tuple(derived_reads),
        dynamic_setattrs=tuple(dynamic_setattrs),
        lifecycle_hooks=tuple(lifecycle_hooks),
        coverage=coverage,
        semantic_sha256=_semantic_sha256(payload),
    )


def write_mutation_hook_report(
        project_root: Path | str, output_path: Path | str,
        ) -> MutationHookPlan:
    """Write the deterministic audit report; no C/ASM output is produced."""
    plan = build_mutation_hook_ir(project_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_text(_json_text(plan.as_dict()), encoding="utf-8")
    temporary.replace(path)
    return plan
