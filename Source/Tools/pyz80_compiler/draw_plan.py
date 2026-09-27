"""Target-neutral, fail-closed sprite draw-plan extraction.

The module lowers a deliberately small, structurally checked subset of a
Python ``draw`` method to ordered draw-record actions.  It does not know
anything about a Z80 object layout, FT812 handles, RAM pages, or the eventual
packed C ABI.  Values and predicates stay as expression trees, so a backend
can choose its own representation without recovering relationships from a
Cartesian product of independently collected values.

``compile_active_enemy_draw_plan`` is the pinned entry point for the Python
program launched by ``run_python.cmd``.  ``compile_sprite_draw_plan`` is the
reusable frontend: another draw method can use it with its own semantic
contract after focused tests establish the intended source surface.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from .diagnostics import SourceSpan


DRAW_PLAN_FORMAT = "pyz80.sprite-draw-plan.v1"
ACTIVE_DRAW_MODULE = "rtype_port.enemies"
ACTIVE_DRAW_CLASS = "M72EnemyWorld"
ACTIVE_DRAW_METHOD = "draw"

__all__ = [
    "ACTIVE_DRAW_CLASS",
    "ACTIVE_DRAW_METHOD",
    "ACTIVE_DRAW_MODULE",
    "ACTIVE_ENEMY_DRAW_CONTRACT",
    "ContinuePredicateIR",
    "DRAW_PLAN_FORMAT",
    "DrawExpr",
    "DrawLoopIR",
    "DrawPlanCompileError",
    "DrawPlanContract",
    "DrawRecordActionIR",
    "SinkOccurrenceIR",
    "SpriteDrawPlanIR",
    "compile_active_enemy_draw_plan",
    "compile_sprite_draw_plan",
    "cross_check_coverage_sinks",
    "validate_draw_plan_contract",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(node, include_attributes=False).encode("utf-8"))


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _semantic_sha256(value: object) -> str:
    return _sha256(_json_bytes(value))


@dataclass(frozen=True)
class DrawExpr:
    """One backend-independent expression.

    ``value`` is used only for scalar/name/operator metadata.  Child
    expressions are always ordered.  In particular, ``all`` and ``select``
    retain Python short-circuit/branch order.
    """

    op: str
    arguments: tuple["DrawExpr", ...] = ()
    value: int | str | bool | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"op": self.op}
        if self.value is not None or self.op == "constant":
            result["value"] = self.value
        if self.arguments:
            result["arguments"] = [item.as_dict() for item in self.arguments]
        return result

    def semantic_key(self) -> object:
        return (
            self.op,
            self.value,
            tuple(item.semantic_key() for item in self.arguments),
        )


def _logical_not(value: DrawExpr) -> DrawExpr:
    return DrawExpr("not", (value,))


@dataclass(frozen=True)
class ContinuePredicateIR:
    ordinal: int
    predicate: DrawExpr
    span: SourceSpan
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "predicate": self.predicate.as_dict(),
            "span": self.span.__dict__,
            "ast_sha256": self.ast_sha256,
        }


@dataclass(frozen=True)
class SinkOccurrenceIR:
    """One lexical ``atlas.draw`` call before finite-loop expansion."""

    ordinal: int
    receiver: str
    arguments: tuple[str, ...]
    coverage_id: str
    control_sha256: str
    span: SourceSpan
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "receiver": self.receiver,
            "arguments": list(self.arguments),
            "coverage_id": self.coverage_id,
            "control_sha256": self.control_sha256,
            "span": self.span.__dict__,
            "ast_sha256": self.ast_sha256,
        }


@dataclass(frozen=True)
class DrawRecordActionIR:
    """One ordered runtime record template.

    A source call in a finite literal loop produces several actions with the
    same ``sink_ordinal`` and increasing ``expansion_ordinal``.  Conditions
    include both the inverse of preceding ``continue`` filters and the exact
    enclosing branch/finite-sequence predicates.
    """

    ordinal: int
    loop_id: str
    sink_ordinal: int
    expansion_ordinal: int
    conditions: tuple[DrawExpr, ...]
    descriptor: DrawExpr
    palette: DrawExpr
    resource_type: DrawExpr
    anchor_x: DrawExpr
    anchor_y: DrawExpr
    span: SourceSpan
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "loop_id": self.loop_id,
            "sink_ordinal": self.sink_ordinal,
            "expansion_ordinal": self.expansion_ordinal,
            "conditions": [item.as_dict() for item in self.conditions],
            "record": {
                "descriptor": self.descriptor.as_dict(),
                "palette": self.palette.as_dict(),
                "resource_type": self.resource_type.as_dict(),
                "anchor_x": self.anchor_x.as_dict(),
                "anchor_y": self.anchor_y.as_dict(),
            },
            "span": self.span.__dict__,
            "ast_sha256": self.ast_sha256,
        }

    def semantic_key(self) -> object:
        return {
            "loop_id": self.loop_id,
            "sink_ordinal": self.sink_ordinal,
            "expansion_ordinal": self.expansion_ordinal,
            "conditions": [item.semantic_key() for item in self.conditions],
            "descriptor": self.descriptor.semantic_key(),
            "palette": self.palette.semantic_key(),
            "resource_type": self.resource_type.semantic_key(),
            "anchor_x": self.anchor_x.semantic_key(),
            "anchor_y": self.anchor_y.semantic_key(),
        }


@dataclass(frozen=True)
class DrawLoopIR:
    loop_id: str
    iteration_target: str
    bound_names: tuple[str, ...]
    iterable: DrawExpr
    continue_predicates: tuple[ContinuePredicateIR, ...]
    action_ordinals: tuple[int, ...]
    span: SourceSpan
    ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "loop_id": self.loop_id,
            "iteration_target": self.iteration_target,
            "bound_names": list(self.bound_names),
            "iterable": self.iterable.as_dict(),
            "continue_predicates": [
                item.as_dict() for item in self.continue_predicates
            ],
            "action_ordinals": list(self.action_ordinals),
            "span": self.span.__dict__,
            "ast_sha256": self.ast_sha256,
        }

    def semantic_key(self) -> object:
        return {
            "loop_id": self.loop_id,
            "iteration_target": self.iteration_target,
            "bound_names": list(self.bound_names),
            "iterable": self.iterable.semantic_key(),
            "continue_predicates": [
                item.predicate.semantic_key()
                for item in self.continue_predicates
            ],
            "action_ordinals": list(self.action_ordinals),
        }


@dataclass(frozen=True)
class SpriteDrawPlanIR:
    format: str
    module: str
    class_name: str
    method_name: str
    source_path: str
    source_sha256: str
    method_ast_sha256: str
    sink_inventory_sha256: str
    sink_order_sha256: str
    semantic_sha256: str
    loops: tuple[DrawLoopIR, ...]
    sink_occurrences: tuple[SinkOccurrenceIR, ...]
    actions: tuple[DrawRecordActionIR, ...]

    @property
    def symbol(self) -> str:
        return f"{self.module}.{self.class_name}.{self.method_name}"

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "symbol": self.symbol,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "method_ast_sha256": self.method_ast_sha256,
            "sink_inventory_sha256": self.sink_inventory_sha256,
            "sink_order_sha256": self.sink_order_sha256,
            "semantic_sha256": self.semantic_sha256,
            "loops": [item.as_dict() for item in self.loops],
            "sink_occurrences": [
                item.as_dict() for item in self.sink_occurrences
            ],
            "actions": [item.as_dict() for item in self.actions],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True, indent=indent,
        ) + "\n"

    def report(self) -> dict[str, object]:
        """Small deterministic build/report payload without losing proofs."""
        return {
            "format": self.format,
            "symbol": self.symbol,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "method_ast_sha256": self.method_ast_sha256,
            "sink_inventory_sha256": self.sink_inventory_sha256,
            "sink_order_sha256": self.sink_order_sha256,
            "semantic_sha256": self.semantic_sha256,
            "loop_count": len(self.loops),
            "continue_predicate_count": sum(
                len(item.continue_predicates) for item in self.loops
            ),
            "sink_occurrence_count": len(self.sink_occurrences),
            "record_action_count": len(self.actions),
            "loop_action_counts": {
                item.loop_id: len(item.action_ordinals) for item in self.loops
            },
            "coverage_sink_ids": sorted(
                item.coverage_id for item in self.sink_occurrences
            ),
        }


@dataclass(frozen=True)
class DrawPlanContract:
    """Pinned semantic surface for one source method."""

    module: str
    class_name: str
    method_name: str
    method_ast_sha256: str
    sink_occurrence_count: int
    record_action_count: int
    sink_inventory_sha256: str
    sink_order_sha256: str
    semantic_sha256: str


class CoverageReportLike(Protocol):
    owned_sink_ids: Iterable[str]


class DrawPlanCompileError(ValueError):
    """A deterministic hard failure containing source coordinates and hashes."""

    def __init__(
            self, code: str, detail: str, *, span: SourceSpan,
            source_sha256: str, method_ast_sha256: str,
            node_ast_sha256: str) -> None:
        self.code = code
        self.detail = detail
        self.span = span
        self.source_sha256 = source_sha256
        self.method_ast_sha256 = method_ast_sha256
        self.node_ast_sha256 = node_ast_sha256
        super().__init__(
            f"{span.render()}: {code}: {detail}; "
            f"source_sha256={source_sha256}; "
            f"method_ast_sha256={method_ast_sha256}; "
            f"node_ast_sha256={node_ast_sha256}")


@dataclass
class _LoopDraft:
    loop_id: str
    iteration_target: str
    bound_names: tuple[str, ...]
    iterable: DrawExpr
    continue_predicates: list[ContinuePredicateIR]
    action_ordinals: list[int]
    node: ast.For


@dataclass
class _SinkDraft:
    ordinal: int
    receiver: str
    arguments: tuple[str, ...]
    control_key: object
    node: ast.Call

    def shape_key(self, module: str, qualname: str) -> object:
        return (module, qualname, self.receiver, self.arguments, ())

    def shape_digest(self, module: str, qualname: str) -> str:
        return _sha256(repr(self.shape_key(module, qualname)).encode("utf-8"))[:16]


class _DrawPlanCompiler:
    _BINOPS: Mapping[type[ast.operator], str] = {
        ast.Add: "add",
        ast.Sub: "subtract",
        ast.BitAnd: "bit_and",
        ast.BitOr: "bit_or",
        ast.BitXor: "bit_xor",
        ast.LShift: "shift_left",
        ast.RShift: "shift_right",
    }
    _CMPOPS: Mapping[type[ast.cmpop], str] = {
        ast.Eq: "equal",
        ast.NotEq: "not_equal",
        ast.Lt: "less_than",
        ast.LtE: "less_or_equal",
        ast.Gt: "greater_than",
        ast.GtE: "greater_or_equal",
        ast.Is: "is",
        ast.IsNot: "is_not",
    }

    def __init__(
            self, source: str, source_path: str, module: str,
            class_name: str, method_name: str,
            atlas_receiver: str | None,
            target_argument: str | None) -> None:
        self.source = source
        self.source_path = source_path.replace("\\", "/")
        self.path = Path(self.source_path)
        self.module = module
        self.class_name = class_name
        self.method_name = method_name
        self.qualname = f"{class_name}.{method_name}"
        self.source_hash = _sha256(source.encode("utf-8"))
        self.method: ast.FunctionDef | None = None
        self.method_hash = "unavailable"
        self.atlas_receiver = atlas_receiver
        self.target_argument = target_argument
        self.loops: list[_LoopDraft] = []
        self.actions: list[DrawRecordActionIR] = []
        self.sinks: list[_SinkDraft] = []
        self.sink_by_node: dict[int, int] = {}
        self.sink_expansions: Counter[int] = Counter()

    def _span(self, node: ast.AST) -> SourceSpan:
        return SourceSpan.from_node(self.path, node)

    def _fail(self, code: str, detail: str, node: ast.AST) -> "None":
        raise DrawPlanCompileError(
            code, detail, span=self._span(node),
            source_sha256=self.source_hash,
            method_ast_sha256=self.method_hash,
            node_ast_sha256=_ast_sha256(node))

    def _find_method(self, tree: ast.Module) -> ast.FunctionDef:
        classes = [
            item for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == self.class_name
        ]
        if len(classes) != 1:
            node: ast.AST = classes[0] if classes else tree
            self._fail(
                "PZDP002",
                f"expected exactly one class {self.class_name}, got {len(classes)}",
                node)
        methods = [
            item for item in classes[0].body
            if isinstance(item, ast.FunctionDef) and item.name == self.method_name
        ]
        if len(methods) != 1:
            self._fail(
                "PZDP003",
                f"expected exactly one method {self.qualname}, got {len(methods)}",
                classes[0])
        return methods[0]

    def _bound_names(self, node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.Tuple, ast.List)):
            result: list[str] = []
            for item in node.elts:
                result.extend(self._bound_names(item))
            if len(result) != len(set(result)):
                self._fail("PZDP004", "duplicate loop binding", node)
            return tuple(result)
        self._fail(
            "PZDP004", "unsupported loop binding (starred/dynamic target)", node)

    def _bind_pattern(
            self, target: ast.expr, value: DrawExpr,
            environment: dict[str, DrawExpr]) -> None:
        if isinstance(target, ast.Name):
            environment[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if value.op != "tuple" or len(target.elts) != len(value.arguments):
                self._fail(
                    "PZDP005",
                    "finite loop destructuring does not match tuple value",
                    target)
            for child, child_value in zip(target.elts, value.arguments):
                self._bind_pattern(child, child_value, environment)
            return
        self._fail("PZDP004", "unsupported loop binding", target)

    def _types(self, node: ast.expr) -> tuple[DrawExpr, ...]:
        nodes = node.elts if isinstance(node, ast.Tuple) else (node,)
        result: list[DrawExpr] = []
        for item in nodes:
            if not isinstance(item, ast.Name):
                self._fail(
                    "PZDP006", "isinstance type must be a local class name", item)
            result.append(DrawExpr("type", value=item.id))
        if not result:
            self._fail("PZDP006", "empty isinstance type tuple", node)
        return tuple(result)

    def _expr(
            self, node: ast.expr,
            environment: Mapping[str, DrawExpr]) -> DrawExpr:
        if isinstance(node, ast.Constant):
            if not (node.value is None or isinstance(
                    node.value, (bool, int, str))):
                self._fail(
                    "PZDP006",
                    f"unsupported constant type {type(node.value).__name__}", node)
            return DrawExpr("constant", value=node.value)
        if isinstance(node, ast.Name):
            value = environment.get(node.id)
            if value is None:
                return DrawExpr("name", value=node.id)
            if self._contains_undefined(value):
                self._fail(
                    "PZDP009",
                    f"compiler-local name {node.id!r} is not defined on every "
                    "control-flow path", node)
            return value
        if isinstance(node, ast.Attribute):
            return DrawExpr(
                "attribute", (self._expr(node.value, environment),), node.attr)
        if isinstance(node, ast.Tuple):
            return DrawExpr(
                "tuple", tuple(self._expr(item, environment)
                               for item in node.elts))
        if isinstance(node, ast.List):
            return DrawExpr(
                "list", tuple(self._expr(item, environment)
                              for item in node.elts))
        if isinstance(node, ast.Subscript):
            return DrawExpr(
                "subscript",
                (self._expr(node.value, environment),
                 self._expr(node.slice, environment)))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return _logical_not(self._expr(node.operand, environment))
            if isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
                operation = {
                    ast.USub: "negate",
                    ast.UAdd: "positive",
                    ast.Invert: "bit_not",
                }[type(node.op)]
                return DrawExpr(
                    operation, (self._expr(node.operand, environment),))
            self._fail("PZDP006", "unsupported unary operator", node)
        if isinstance(node, ast.BoolOp):
            operation = "all" if isinstance(node.op, ast.And) else "any"
            if not isinstance(node.op, (ast.And, ast.Or)):
                self._fail("PZDP006", "unsupported boolean operator", node)
            return DrawExpr(
                operation,
                tuple(self._expr(item, environment) for item in node.values))
        if isinstance(node, ast.BinOp):
            operation = self._BINOPS.get(type(node.op))
            if operation is None:
                self._fail("PZDP006", "unsupported binary operator", node)
            return DrawExpr(
                operation,
                (self._expr(node.left, environment),
                 self._expr(node.right, environment)))
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                self._fail("PZDP006", "chained comparison is unsupported", node)
            operation = self._CMPOPS.get(type(node.ops[0]))
            if operation is None:
                self._fail("PZDP006", "unsupported comparison operator", node)
            return DrawExpr(
                operation,
                (self._expr(node.left, environment),
                 self._expr(node.comparators[0], environment)))
        if isinstance(node, ast.IfExp):
            return DrawExpr(
                "select",
                (self._expr(node.test, environment),
                 self._expr(node.body, environment),
                 self._expr(node.orelse, environment)))
        if isinstance(node, ast.Call):
            if node.keywords:
                self._fail("PZDP006", "keyword expression call is unsupported", node)
            if (isinstance(node.func, ast.Attribute) and
                    node.func.attr == "values" and not node.args):
                return DrawExpr(
                    "mapping_values",
                    (self._expr(node.func.value, environment),))
            if (isinstance(node.func, ast.Name) and
                    node.func.id == "isinstance" and len(node.args) == 2):
                return DrawExpr(
                    "type_is",
                    (self._expr(node.args[0], environment),
                     DrawExpr("types", self._types(node.args[1]))))
            if (isinstance(node.func, ast.Name) and
                    node.func.id == "getattr" and len(node.args) in (2, 3)):
                if (not isinstance(node.args[1], ast.Constant) or
                        not isinstance(node.args[1].value, str)):
                    self._fail(
                        "PZDP006", "getattr attribute must be a string literal",
                        node.args[1])
                return DrawExpr(
                    "getattr",
                    tuple(self._expr(item, environment) for item in node.args))
            self._fail(
                "PZDP006", "unsupported expression call: " + ast.unparse(node),
                node)
        self._fail(
            "PZDP006", f"unsupported expression node {type(node).__name__}", node)

    def _contains_undefined(self, value: DrawExpr) -> bool:
        return (value.op == "undefined" or any(
            self._contains_undefined(item) for item in value.arguments))

    def _assignment(
            self, node: ast.Assign | ast.AnnAssign,
            environment: dict[str, DrawExpr]) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if node.value is None or len(targets) != 1:
            self._fail("PZDP007", "assignment shape is unsupported", node)
        target = targets[0]
        if not isinstance(target, ast.Name):
            self._fail(
                "PZDP007", "only compiler-local name assignment is supported",
                target)
        environment[target.id] = self._expr(node.value, environment)

    def _register_sink(
            self, node: ast.Call,
            conditions: tuple[DrawExpr, ...]) -> int:
        known = self.sink_by_node.get(id(node))
        if known is not None:
            return known
        receiver = ast.unparse(node.func.value)  # type: ignore[union-attr]
        draft = _SinkDraft(
            ordinal=len(self.sinks), receiver=receiver,
            arguments=tuple(ast.unparse(item) for item in node.args),
            control_key=tuple(item.semantic_key() for item in conditions),
            node=node)
        self.sinks.append(draft)
        self.sink_by_node[id(node)] = draft.ordinal
        return draft.ordinal

    def _draw(
            self, node: ast.Call, environment: Mapping[str, DrawExpr],
            conditions: tuple[DrawExpr, ...], loop: _LoopDraft) -> None:
        if (not isinstance(node.func, ast.Attribute) or
                node.func.attr != "draw"):
            self._fail("PZDP008", "expression is not an atlas.draw sink", node)
        receiver = ast.unparse(node.func.value)
        if self.atlas_receiver is None:
            self.atlas_receiver = receiver
        if receiver != self.atlas_receiver:
            self._fail(
                "PZDP008",
                f"new/changed draw receiver {receiver!r}; expected "
                f"{self.atlas_receiver!r}", node)
        if node.keywords or len(node.args) != 6:
            self._fail(
                "PZDP008", "draw sink must have exactly six positional arguments",
                node)
        if ast.unparse(node.args[0]) != self.target_argument:
            self._fail(
                "PZDP008", "draw target no longer matches the method target",
                node.args[0])
        descriptor_call = node.args[1]
        if (not isinstance(descriptor_call, ast.Call) or
                not isinstance(descriptor_call.func, ast.Name) or
                descriptor_call.func.id != "read_descriptor" or
                len(descriptor_call.args) != 2 or descriptor_call.keywords or
                ast.unparse(descriptor_call.args[0]) != "self.rom"):
            self._fail(
                "PZDP008",
                "descriptor must be read_descriptor(self.rom, address)",
                descriptor_call)
        sink_ordinal = self._register_sink(node, conditions)
        expansion_ordinal = self.sink_expansions[sink_ordinal]
        self.sink_expansions[sink_ordinal] += 1
        action = DrawRecordActionIR(
            ordinal=len(self.actions), loop_id=loop.loop_id,
            sink_ordinal=sink_ordinal,
            expansion_ordinal=expansion_ordinal,
            conditions=conditions,
            descriptor=self._expr(descriptor_call.args[1], environment),
            palette=self._expr(node.args[2], environment),
            resource_type=self._expr(node.args[3], environment),
            anchor_x=self._expr(node.args[4], environment),
            anchor_y=self._expr(node.args[5], environment),
            span=self._span(node), ast_sha256=_ast_sha256(node))
        self.actions.append(action)
        loop.action_ordinals.append(action.ordinal)

    def _merge_environments(
            self, before: Mapping[str, DrawExpr],
            then_environment: Mapping[str, DrawExpr],
            else_environment: Mapping[str, DrawExpr], test: DrawExpr,
            node: ast.If) -> dict[str, DrawExpr]:
        result: dict[str, DrawExpr] = dict(before)
        names = sorted(set(then_environment) | set(else_environment))
        for name in names:
            prior = before.get(name)
            undefined = DrawExpr("undefined", value=name)
            then_value = then_environment.get(
                name, prior if prior is not None else undefined)
            else_value = else_environment.get(
                name, prior if prior is not None else undefined)
            if then_value == else_value:
                result[name] = then_value
            else:
                result[name] = DrawExpr(
                    "select", (test, then_value, else_value))
        return result

    def _finite_sequences(
            self, value: DrawExpr, node: ast.expr,
            guards: tuple[DrawExpr, ...] = (),
            ) -> tuple[tuple[tuple[DrawExpr, ...], tuple[DrawExpr, ...]], ...]:
        if value.op in ("tuple", "list"):
            return ((guards, value.arguments),)
        if value.op == "select" and len(value.arguments) == 3:
            test, when_true, when_false = value.arguments
            return (
                self._finite_sequences(
                    when_true, node, guards + (test,)) +
                self._finite_sequences(
                    when_false, node, guards + (_logical_not(test),))
            )
        self._fail(
            "PZDP010",
            "nested draw loop must have a finite literal/conditional sequence",
            node)

    def _assigned_names(self, statements: Iterable[ast.stmt]) -> set[str]:
        result: set[str] = set()
        for statement in statements:
            for node in ast.walk(statement):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (node.targets if isinstance(node, ast.Assign)
                               else [node.target])
                    for target in targets:
                        if isinstance(target, ast.Name):
                            result.add(target.id)
                        else:
                            result.add("<unsupported>")
        return result

    def _sequence(
            self, statements: list[ast.stmt],
            environment: dict[str, DrawExpr],
            conditions: tuple[DrawExpr, ...], loop: _LoopDraft,
            *, allow_continue_filter: bool = False,
            ) -> dict[str, DrawExpr]:
        active_conditions = conditions
        current = dict(environment)
        for statement in statements:
            if isinstance(statement, ast.If):
                is_continue = (
                    not statement.orelse and len(statement.body) == 1 and
                    isinstance(statement.body[0], ast.Continue)
                )
                if is_continue:
                    if not allow_continue_filter:
                        self._fail(
                            "PZDP011",
                            "continue filter is supported only in the runtime "
                            "loop's straight-line prologue", statement)
                    predicate = self._expr(statement.test, current)
                    item = ContinuePredicateIR(
                        ordinal=len(loop.continue_predicates),
                        predicate=predicate, span=self._span(statement.test),
                        ast_sha256=_ast_sha256(statement.test))
                    loop.continue_predicates.append(item)
                    active_conditions += (_logical_not(predicate),)
                    continue

                test = self._expr(statement.test, current)
                then_environment = self._sequence(
                    statement.body, dict(current),
                    active_conditions + (test,), loop)
                else_environment = self._sequence(
                    statement.orelse, dict(current),
                    active_conditions + (_logical_not(test),), loop)
                current = self._merge_environments(
                    current, then_environment, else_environment,
                    test, statement)
                continue

            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                self._assignment(statement, current)
                continue

            if isinstance(statement, ast.Expr):
                if not isinstance(statement.value, ast.Call):
                    self._fail(
                        "PZDP012", "unsupported expression statement", statement)
                self._draw(
                    statement.value, current, active_conditions, loop)
                continue

            if isinstance(statement, ast.For):
                if statement.orelse:
                    self._fail("PZDP013", "for-else is unsupported", statement)
                assigned = self._assigned_names(statement.body)
                if assigned:
                    self._fail(
                        "PZDP013",
                        "finite draw-loop body may not assign names: " +
                        ", ".join(sorted(assigned)), statement)
                iterable = self._expr(statement.iter, current)
                alternatives = self._finite_sequences(iterable, statement.iter)
                for guards, values in alternatives:
                    for value in values:
                        nested_environment = dict(current)
                        self._bind_pattern(
                            statement.target, value, nested_environment)
                        self._sequence(
                            statement.body, nested_environment,
                            active_conditions + guards, loop)
                continue

            if isinstance(statement, ast.Pass):
                continue
            self._fail(
                "PZDP014",
                f"unsupported draw statement {type(statement).__name__}",
                statement)
        return current

    def compile(self) -> SpriteDrawPlanIR:
        try:
            tree = ast.parse(self.source, filename=self.source_path)
        except SyntaxError as exc:
            span = SourceSpan(
                self.source_path, exc.lineno or 1,
                max(0, (exc.offset or 1) - 1), exc.end_lineno or exc.lineno or 1,
                max(1, exc.end_offset or exc.offset or 1))
            raise DrawPlanCompileError(
                "PZDP001", f"cannot parse source: {exc.msg}", span=span,
                source_sha256=self.source_hash,
                method_ast_sha256="unavailable",
                node_ast_sha256="unavailable") from exc

        self.method = self._find_method(tree)
        self.method_hash = _ast_sha256(self.method)
        arguments = (
            list(self.method.args.posonlyargs) + list(self.method.args.args)
        )
        if (len(arguments) < 2 or arguments[0].arg != "self" or
                self.method.args.vararg is not None or
                self.method.args.kwarg is not None or
                self.method.args.kwonlyargs):
            self._fail(
                "PZDP003",
                "draw method must have self, a target, and only fixed "
                "positional parameters",
                self.method)
        argument_names = tuple(item.arg for item in arguments)
        if self.target_argument is None:
            self.target_argument = arguments[1].arg
        elif (self.target_argument == "self" or
              self.target_argument not in argument_names):
            self._fail(
                "PZDP003",
                f"configured target argument {self.target_argument!r} is not "
                "a method parameter", self.method)
        if self.method.decorator_list:
            self._fail("PZDP003", "decorated draw method is unsupported", self.method)

        for statement in self.method.body:
            if not isinstance(statement, ast.For):
                self._fail(
                    "PZDP014", "method body must consist of runtime draw loops",
                    statement)
            if statement.orelse:
                self._fail("PZDP013", "runtime for-else is unsupported", statement)
            environment: dict[str, DrawExpr] = {}
            loop = _LoopDraft(
                loop_id=f"loop_{len(self.loops)}",
                iteration_target=ast.unparse(statement.target),
                bound_names=self._bound_names(statement.target),
                iterable=self._expr(statement.iter, environment),
                continue_predicates=[], action_ordinals=[], node=statement)
            self.loops.append(loop)
            self._sequence(
                statement.body, environment, (), loop,
                allow_continue_filter=True)

        if not self.loops:
            self._fail("PZDP014", "draw method has no runtime loops", self.method)
        if not self.sinks:
            self._fail("PZDP008", "draw method has no atlas.draw sinks", self.method)

        shape_counts: Counter[object] = Counter()
        sink_items: list[SinkOccurrenceIR] = []
        shape_sequence: list[object] = []
        for draft in self.sinks:
            shape = draft.shape_key(self.module, self.qualname)
            shape_sequence.append(shape)
            shape_ordinal = shape_counts[shape]
            shape_counts[shape] += 1
            coverage_id = (
                f"{self.module}:{self.qualname}:"
                f"{draft.shape_digest(self.module, self.qualname)}:"
                f"{shape_ordinal}")
            sink_items.append(SinkOccurrenceIR(
                ordinal=draft.ordinal, receiver=draft.receiver,
                arguments=draft.arguments, coverage_id=coverage_id,
                control_sha256=_semantic_sha256(draft.control_key),
                span=self._span(draft.node),
                ast_sha256=_ast_sha256(draft.node)))

        loop_items = tuple(DrawLoopIR(
            loop_id=item.loop_id,
            iteration_target=item.iteration_target,
            bound_names=item.bound_names,
            iterable=item.iterable,
            continue_predicates=tuple(item.continue_predicates),
            action_ordinals=tuple(item.action_ordinals),
            span=self._span(item.node), ast_sha256=_ast_sha256(item.node),
        ) for item in self.loops)
        inventory = sorted(
            ((repr(shape), count) for shape, count in shape_counts.items()),
            key=lambda item: item[0])
        inventory_hash = _semantic_sha256(inventory)
        order_hash = _semantic_sha256([
            {
                "shape": repr(shape),
                "control": draft.control_key,
            }
            for shape, draft in zip(shape_sequence, self.sinks)
        ])
        semantic = {
            "loops": [item.semantic_key() for item in loop_items],
            "actions": [item.semantic_key() for item in self.actions],
        }
        return SpriteDrawPlanIR(
            format=DRAW_PLAN_FORMAT, module=self.module,
            class_name=self.class_name, method_name=self.method_name,
            source_path=self.source_path, source_sha256=self.source_hash,
            method_ast_sha256=self.method_hash,
            sink_inventory_sha256=inventory_hash,
            sink_order_sha256=order_hash,
            semantic_sha256=_semantic_sha256(semantic), loops=loop_items,
            sink_occurrences=tuple(sink_items), actions=tuple(self.actions))


def _contract_error(
        plan: SpriteDrawPlanIR, code: str, detail: str,
        *, occurrence: SinkOccurrenceIR | None = None,
        ) -> "None":
    if occurrence is None:
        first_loop = plan.loops[0]
        span = first_loop.span
        node_hash = first_loop.ast_sha256
    else:
        span = occurrence.span
        node_hash = occurrence.ast_sha256
    raise DrawPlanCompileError(
        code, detail, span=span, source_sha256=plan.source_sha256,
        method_ast_sha256=plan.method_ast_sha256,
        node_ast_sha256=node_hash)


def validate_draw_plan_contract(
        plan: SpriteDrawPlanIR, contract: DrawPlanContract) -> None:
    """Fail before any backend consumes a changed active-Python surface."""
    expected_symbol = (
        contract.module, contract.class_name, contract.method_name)
    actual_symbol = (plan.module, plan.class_name, plan.method_name)
    if actual_symbol != expected_symbol:
        _contract_error(
            plan, "PZDP015",
            f"contract symbol {expected_symbol!r} does not match {actual_symbol!r}")
    if len(plan.sink_occurrences) != contract.sink_occurrence_count:
        extra = (plan.sink_occurrences[contract.sink_occurrence_count]
                 if len(plan.sink_occurrences) > contract.sink_occurrence_count
                 else None)
        _contract_error(
            plan, "PZDP016",
            "new/missing atlas.draw sink: expected "
            f"{contract.sink_occurrence_count}, got {len(plan.sink_occurrences)}",
            occurrence=extra)
    if plan.sink_inventory_sha256 != contract.sink_inventory_sha256:
        _contract_error(
            plan, "PZDP017",
            "atlas.draw sink shape inventory changed: "
            f"expected {contract.sink_inventory_sha256}, got "
            f"{plan.sink_inventory_sha256}")
    if plan.sink_order_sha256 != contract.sink_order_sha256:
        _contract_error(
            plan, "PZDP018",
            "atlas.draw source order changed: "
            f"expected {contract.sink_order_sha256}, got "
            f"{plan.sink_order_sha256}")
    if len(plan.actions) != contract.record_action_count:
        _contract_error(
            plan, "PZDP019",
            "finite record expansion changed: expected "
            f"{contract.record_action_count}, got {len(plan.actions)}")
    if plan.semantic_sha256 != contract.semantic_sha256:
        _contract_error(
            plan, "PZDP020",
            "draw-plan predicates/records changed: "
            f"expected {contract.semantic_sha256}, got {plan.semantic_sha256}")
    if plan.method_ast_sha256 != contract.method_ast_sha256:
        _contract_error(
            plan, "PZDP021",
            "draw method AST changed outside the owned plan: "
            f"expected {contract.method_ast_sha256}, got "
            f"{plan.method_ast_sha256}")


def cross_check_coverage_sinks(
        plan: SpriteDrawPlanIR, report: CoverageReportLike) -> None:
    """Cheaply join with an already-produced public coverage report.

    This function never invokes the expensive eight-stage analyser.  Build
    orchestration can pass its existing ``CoverageReport`` and prove that the
    source occurrences owned here are the same occurrences in the global
    active-program inventory.
    """
    prefix = f"{plan.module}:{plan.class_name}.{plan.method_name}:"
    covered = tuple(sorted(
        item for item in report.owned_sink_ids if item.startswith(prefix)))
    current = tuple(sorted(
        item.coverage_id for item in plan.sink_occurrences))
    if covered != current:
        _contract_error(
            plan, "PZDP022",
            "public sprite coverage sink inventory disagrees with draw plan: "
            f"coverage={len(covered)}, plan={len(current)}")


def compile_sprite_draw_plan(
        source: str, *, source_path: str, module: str,
        class_name: str, method_name: str = "draw",
        atlas_receiver: str | None = None,
        target_argument: str | None = None,
        contract: DrawPlanContract | None = None,
        coverage_report: CoverageReportLike | None = None,
        ) -> SpriteDrawPlanIR:
    """Compile one method without importing or executing the source module."""
    compiler = _DrawPlanCompiler(
        source, source_path, module, class_name, method_name, atlas_receiver,
        target_argument)
    plan = compiler.compile()
    if contract is not None:
        validate_draw_plan_contract(plan, contract)
    if coverage_report is not None:
        cross_check_coverage_sinks(plan, coverage_report)
    return plan


# Filled from the AST-derived IR, never from a handwritten list of draws.
# The four independent hashes make a source change fail with a useful class
# (sink count, sink shape, source order, record semantics, or ignored AST).
ACTIVE_ENEMY_DRAW_CONTRACT = DrawPlanContract(
    module=ACTIVE_DRAW_MODULE,
    class_name=ACTIVE_DRAW_CLASS,
    method_name=ACTIVE_DRAW_METHOD,
    method_ast_sha256="25b4446b52c9b84bdfd9fd6f61bf660b8ff3e539444d4a84023a9bfad0429f99",
    sink_occurrence_count=16,
    record_action_count=34,
    sink_inventory_sha256="0c2c9ce22480089860c7e1d5510444054ad701ebf34811c7786d9c64f70101b8",
    sink_order_sha256="357de96084aa3239e1cc2579ba31fd72d3895a0a8365451a8f5ecfe696c651a9",
    semantic_sha256="8deb7410b166f70abea16a78a5cb472952871c068dde1d17efde1de9356119c8",
)


def compile_active_enemy_draw_plan(
        project_root: Path | str, *, source_override: str | None = None,
        coverage_report: CoverageReportLike | None = None,
        ) -> SpriteDrawPlanIR:
    """Compile the exact ``rtype_port.enemies`` used by ``run_python.cmd``."""
    root = Path(project_root)
    command_path = root / "run_python.cmd"
    command = command_path.read_bytes().decode("utf-8")
    # Keep this check local and cheap: resolving the whole import graph belongs
    # to sprite_coverage, whose report can optionally be joined above.
    import re
    match = re.search(r"(?:^|\s)-m\s+([A-Za-z_][\w.]*)", command, re.MULTILINE)
    if match is None or match.group(1) != "rtype_port.app":
        source_hash = _sha256(command.encode("utf-8"))
        span = SourceSpan("run_python.cmd", 1, 0, 1, 1)
        raise DrawPlanCompileError(
            "PZDP023", "run_python.cmd no longer launches rtype_port.app",
            span=span, source_sha256=source_hash,
            method_ast_sha256="unavailable",
            node_ast_sha256="unavailable")
    source_path = (
        root / "Source" / "Python" / "rtype_port" / "enemies.py")
    source = (source_override if source_override is not None
              else source_path.read_bytes().decode("utf-8"))
    plan = compile_sprite_draw_plan(
        source, source_path="Source/Python/rtype_port/enemies.py",
        module=ACTIVE_DRAW_MODULE, class_name=ACTIVE_DRAW_CLASS,
        method_name=ACTIVE_DRAW_METHOD, atlas_receiver="self.atlas",
        target_argument="target",
        contract=ACTIVE_ENEMY_DRAW_CONTRACT,
        coverage_report=coverage_report)
    return plan
