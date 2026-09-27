"""Portable C lowering for :mod:`pyz80_compiler.draw_plan`.

This is deliberately a layer *above* every Z80 object layout.  The generated
C consumes a normalized object view, a normalized transient tuple view and
two total resolver callbacks.  A later target adapter is responsible for
turning the live game's storage into this ABI.

The backend is fail closed.  It derives class tags, object fields, string
state tags, loop order and record actions from ``SpriteDrawPlanIR``; there is
no handwritten action table.  Only expression forms whose Python semantics
are implemented by both the oracle and the C emitter are accepted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableSequence, Sequence

from .draw_plan import (
    DRAW_PLAN_FORMAT,
    DrawExpr,
    DrawLoopIR,
    DrawRecordActionIR,
    SpriteDrawPlanIR,
    compile_active_enemy_draw_plan,
)


BACKEND_FORMAT = "pyz80.sprite-draw-c-backend.v1"
RECORD_SIZE = 8

__all__ = [
    "BACKEND_FORMAT",
    "DrawCArtifacts",
    "DrawCBackendError",
    "DrawCBackendModel",
    "FieldSpec",
    "LiteralDrawRecord",
    "NormalizedObjectView",
    "NormalizedTransientView",
    "ProducerStatus",
    "build_draw_c_model",
    "emit_draw_c_backend",
    "interpret_draw_plan",
    "produce_draw_records_oracle",
    "validate_resolver_domains",
    "write_draw_c_backend",
]


class DrawCBackendError(ValueError):
    """Deterministic rejection of an IR construct without exact lowering."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class ProducerStatus(IntEnum):
    OK = 0
    INVALID_INPUT = 1
    CAPACITY = 2
    RANGE = 3


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    c_type: str
    string_values: tuple[str, ...] = ()
    getattr_default: bool | int | str | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "name": self.name,
            "kind": self.kind,
            "c_type": self.c_type,
        }
        if self.string_values:
            result["string_values"] = list(self.string_values)
            result["other_tag"] = 0
        if self.getattr_default is not None:
            result["normalized_getattr_default"] = self.getattr_default
        return result


@dataclass(frozen=True)
class _LoopSpec:
    loop_id: str
    kind: str
    bound_names: tuple[str, ...]
    iterable_attribute: str
    action_ordinals: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "loop_id": self.loop_id,
            "kind": self.kind,
            "bound_names": list(self.bound_names),
            "iterable_attribute": self.iterable_attribute,
            "action_ordinals": list(self.action_ordinals),
        }


@dataclass(frozen=True)
class DrawCBackendModel:
    plan: SpriteDrawPlanIR
    prefix: str
    macro_prefix: str
    class_tags: tuple[str, ...]
    class_memberships: tuple[tuple[str, tuple[str, ...]], ...]
    class_graph_sha256: str
    fields: tuple[FieldSpec, ...]
    loops: tuple[_LoopSpec, ...]

    @property
    def class_bit_bytes(self) -> int:
        return (len(self.class_tags) + 7) // 8

    @property
    def object_bound_names(self) -> frozenset[str]:
        return frozenset(
            name
            for loop in self.loops if loop.kind == "objects"
            for name in loop.bound_names
        )


@dataclass(frozen=True)
class DrawCArtifacts:
    header_name: str
    source_name: str
    manifest_name: str
    header: str
    source: str
    manifest: str


@dataclass(frozen=True)
class NormalizedObjectView:
    """Python-side normalized object used by the semantic oracle.

    ``classes`` contains every generated class name for which Python
    ``isinstance`` would be true.  This is intentionally a set rather than a
    single concrete tag, so inheritance and multiple inheritance retain exact
    Python semantics.  The C ABI represents the same set as a bit vector.
    """

    classes: frozenset[str]
    fields: Mapping[str, int | bool | str]


@dataclass(frozen=True)
class NormalizedTransientView:
    descriptor: int
    palette: int
    resource_type: int
    x: int
    y: int


@dataclass(frozen=True)
class LiteralDrawRecord:
    bank_key: int
    descriptor: int
    anchor_x: int
    anchor_y: int


_SUPPORTED_OPS = frozenset({
    "constant",
    "name",
    "attribute",
    "subscript",
    "not",
    "all",
    "add",
    "equal",
    "not_equal",
    "select",
    "getattr",
    "type_is",
    "types",
    "type",
})

_FIXED_ARITY: Mapping[str, int] = {
    "constant": 0,
    "name": 0,
    "attribute": 1,
    "subscript": 2,
    "not": 1,
    "add": 2,
    "equal": 2,
    "not_equal": 2,
    "select": 3,
    "type_is": 2,
    "type": 0,
}

_TRANSIENT_FIELDS = (
    ("descriptor", "uint16_t"),
    ("palette", "uint16_t"),
    ("resource_type", "uint16_t"),
    ("x", "int16_t"),
    ("y", "int16_t"),
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"


def _identifier(value: str, *, upper: bool = False) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    result = re.sub(r"_+", "_", result).strip("_")
    if not result or result[0].isdigit():
        result = "v_" + result
    return result.upper() if upper else result.lower()


def _walk(value: DrawExpr) -> Iterable[DrawExpr]:
    yield value
    for argument in value.arguments:
        yield from _walk(argument)


def _all_expressions(plan: SpriteDrawPlanIR) -> Iterable[DrawExpr]:
    for loop in plan.loops:
        yield loop.iterable
        for item in loop.continue_predicates:
            yield item.predicate
    for action in plan.actions:
        yield from action.conditions
        yield action.descriptor
        yield action.palette
        yield action.resource_type
        yield action.anchor_x
        yield action.anchor_y


def _validate_expr(value: DrawExpr) -> None:
    if value.op not in _SUPPORTED_OPS:
        raise DrawCBackendError(
            "PZDPC001", f"unsupported DrawExpr op {value.op!r}")
    fixed = _FIXED_ARITY.get(value.op)
    if fixed is not None and len(value.arguments) != fixed:
        raise DrawCBackendError(
            "PZDPC002",
            f"DrawExpr {value.op!r} has arity {len(value.arguments)}, "
            f"expected {fixed}")
    if value.op in ("all", "types") and not value.arguments:
        raise DrawCBackendError(
            "PZDPC002", f"DrawExpr {value.op!r} must not be empty")
    if value.op == "getattr" and len(value.arguments) not in (2, 3):
        raise DrawCBackendError(
            "PZDPC002", "getattr must have two or three arguments")
    for argument in value.arguments:
        _validate_expr(argument)


def _name_is(value: DrawExpr, name: str) -> bool:
    return value.op == "name" and value.value == name


def _object_attribute(
        value: DrawExpr, object_names: frozenset[str],
        ) -> str | None:
    if (value.op == "attribute" and isinstance(value.value, str) and
            len(value.arguments) == 1 and
            value.arguments[0].op == "name" and
            value.arguments[0].value in object_names):
        return value.value
    if (value.op == "getattr" and len(value.arguments) in (2, 3) and
            value.arguments[0].op == "name" and
            value.arguments[0].value in object_names and
            value.arguments[1].op == "constant" and
            isinstance(value.arguments[1].value, str)):
        return value.arguments[1].value
    return None


def _iterable_attribute(loop: DrawLoopIR) -> str:
    value = loop.iterable
    if (value.op != "attribute" or len(value.arguments) != 1 or
            not isinstance(value.value, str) or
            not _name_is(value.arguments[0], "self")):
        raise DrawCBackendError(
            "PZDPC003",
            f"loop {loop.loop_id} iterable is not one normalized self view")
    return value.value


def _class_tags(plan: SpriteDrawPlanIR) -> tuple[str, ...]:
    names = sorted({
        str(node.value)
        for expression in _all_expressions(plan)
        for node in _walk(expression)
        if node.op == "type"
    })
    if not names:
        raise DrawCBackendError("PZDPC004", "draw plan has no isinstance tags")
    identifiers: dict[str, str] = {}
    for name in names:
        encoded = _identifier(name, upper=True)
        prior = identifiers.setdefault(encoded, name)
        if prior != name:
            raise DrawCBackendError(
                "PZDPC005",
                f"class tag identifier collision: {prior!r} and {name!r}")
    if len(names) > 0xFFFF:
        raise DrawCBackendError("PZDPC005", "more than 65535 class tags")
    return tuple(names)


def _plan_source(plan: SpriteDrawPlanIR, source_text: str | None) -> str:
    if source_text is None:
        relative = Path(plan.source_path)
        candidates = (
            relative,
            Path(__file__).resolve().parents[3] / relative,
        )
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            raise DrawCBackendError(
                "PZDPC022",
                "source text is required to derive the isinstance class graph")
        source_text = path.read_bytes().decode("utf-8")
    actual = _sha256_text(source_text)
    if actual != plan.source_sha256:
        raise DrawCBackendError(
            "PZDPC023",
            "class-graph source hash does not match SpriteDrawPlanIR: "
            f"{actual} != {plan.source_sha256}")
    return source_text


def _class_memberships(
        plan: SpriteDrawPlanIR, class_tags: tuple[str, ...],
        source_text: str | None,
        ) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str]:
    """Derive every local concrete-class bitset from the source AST.

    A normalized layout adapter therefore consumes a generated inheritance
    table rather than maintaining a handwritten ``isinstance`` switch.  The
    representation still permits an adapter to set several bits, preserving
    Python inheritance and multiple-inheritance semantics exactly.
    """
    text = _plan_source(plan, source_text)
    try:
        tree = ast.parse(text, filename=plan.source_path)
    except SyntaxError as exc:
        raise DrawCBackendError(
            "PZDPC024", f"cannot parse class-graph source: {exc.msg}") from exc
    graph: dict[str, tuple[str, ...]] = {}
    for item in tree.body:
        if not isinstance(item, ast.ClassDef):
            continue
        bases: list[str] = []
        for base in item.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
            elif isinstance(base, ast.Subscript):
                # Generic containers such as ``list[Enemy]`` are external
                # bases; retain the AST-derived base token for the manifest,
                # but only local class names participate in tag closure.
                root = base.value
                if isinstance(root, ast.Name):
                    bases.append(root.id)
                elif isinstance(root, ast.Attribute):
                    bases.append(root.attr)
                else:
                    bases.append(ast.unparse(base))
            else:
                bases.append(ast.unparse(base))
        graph[item.name] = tuple(bases)
    missing = sorted(set(class_tags) - set(graph))
    if missing:
        raise DrawCBackendError(
            "PZDPC026",
            "isinstance tags missing from the local AST class graph: "
            + ", ".join(missing))

    visiting: set[str] = set()
    memo: dict[str, frozenset[str]] = {}

    def ancestors(name: str) -> frozenset[str]:
        known = memo.get(name)
        if known is not None:
            return known
        if name in visiting:
            raise DrawCBackendError(
                "PZDPC027", f"cycle in AST class graph at {name!r}")
        visiting.add(name)
        result = {name}
        for base in graph.get(name, ()):
            if base in graph:
                result.update(ancestors(base))
        visiting.remove(name)
        frozen = frozenset(result)
        memo[name] = frozen
        return frozen

    tags = set(class_tags)
    memberships = tuple(
        (name, tuple(sorted(ancestors(name) & tags)))
        for name in sorted(graph)
    )
    graph_payload = {
        "classes": [
            {"name": name, "bases": list(graph[name]),
             "isinstance_tags": list(bits)}
            for name, bits in memberships
        ],
    }
    return memberships, _sha256_text(_json_text(graph_payload))


def _loop_specs(plan: SpriteDrawPlanIR) -> tuple[_LoopSpec, ...]:
    result: list[_LoopSpec] = []
    object_count = 0
    transient_count = 0
    seen_actions: list[int] = []
    for loop in plan.loops:
        attribute = _iterable_attribute(loop)
        if len(loop.bound_names) == 1:
            kind = "objects"
            object_count += 1
        elif len(loop.bound_names) == 5:
            kind = "transients"
            transient_count += 1
        else:
            raise DrawCBackendError(
                "PZDPC006",
                f"loop {loop.loop_id} binding arity {len(loop.bound_names)} "
                "has no normalized view")
        result.append(_LoopSpec(
            loop_id=loop.loop_id,
            kind=kind,
            bound_names=loop.bound_names,
            iterable_attribute=attribute,
            action_ordinals=loop.action_ordinals,
        ))
        seen_actions.extend(loop.action_ordinals)
    if object_count != 1 or transient_count != 1:
        raise DrawCBackendError(
            "PZDPC006",
            "normalized ABI requires exactly one object loop and one "
            f"transient loop, got {object_count}/{transient_count}")
    if seen_actions != list(range(len(plan.actions))):
        raise DrawCBackendError(
            "PZDPC007",
            "loop action ordinals do not cover the plan exactly in Python order")
    return tuple(result)


def _mark_fields(
        value: DrawExpr, object_names: frozenset[str], roles: dict[str, set[str]],
        role: str,
        ) -> None:
    field = _object_attribute(value, object_names)
    if field is not None:
        roles.setdefault(field, set()).add(role)
        return
    if value.op == "not":
        _mark_fields(value.arguments[0], object_names, roles, "bool")
        return
    if value.op == "all":
        for item in value.arguments:
            _mark_fields(item, object_names, roles, "bool")
        return
    if value.op in ("equal", "not_equal"):
        for item in value.arguments:
            if _object_attribute(item, object_names) is not None:
                _mark_fields(item, object_names, roles, "comparison")
            else:
                _mark_fields(item, object_names, roles, "scalar")
        return
    if value.op == "select":
        _mark_fields(value.arguments[0], object_names, roles, "bool")
        _mark_fields(value.arguments[1], object_names, roles, role)
        _mark_fields(value.arguments[2], object_names, roles, role)
        return
    if value.op == "type_is":
        return
    for item in value.arguments:
        _mark_fields(item, object_names, roles, role)


def _field_specs(
        plan: SpriteDrawPlanIR, loops: tuple[_LoopSpec, ...],
        ) -> tuple[FieldSpec, ...]:
    object_names = frozenset(
        loop.bound_names[0] for loop in loops if loop.kind == "objects")
    roles: dict[str, set[str]] = {}
    string_values: dict[str, set[str]] = {}
    getattr_defaults: dict[str, bool | int | str] = {}

    for expression in _all_expressions(plan):
        for node in _walk(expression):
            field = _object_attribute(node, object_names)
            if field is not None:
                roles.setdefault(field, set()).add("scalar")
            if node.op == "getattr" and field is not None:
                if len(node.arguments) == 3:
                    default = node.arguments[2]
                    if (default.op != "constant" or
                            not isinstance(default.value, (bool, int, str))):
                        raise DrawCBackendError(
                            "PZDPC008",
                            f"getattr default for {field!r} is not normalized")
                    prior = getattr_defaults.setdefault(field, default.value)
                    if prior != default.value:
                        raise DrawCBackendError(
                            "PZDPC008",
                            f"conflicting getattr defaults for {field!r}")
            if node.op in ("equal", "not_equal"):
                left, right = node.arguments
                pairs = ((left, right), (right, left))
                for candidate, literal in pairs:
                    string_field = _object_attribute(candidate, object_names)
                    if (string_field is not None and
                            literal.op == "constant" and
                            isinstance(literal.value, str)):
                        string_values.setdefault(string_field, set()).add(
                            literal.value)

    for action in plan.actions:
        for condition in action.conditions:
            _mark_fields(condition, object_names, roles, "bool")
        _mark_fields(action.descriptor, object_names, roles, "u16")
        _mark_fields(action.palette, object_names, roles, "u16")
        _mark_fields(action.resource_type, object_names, roles, "u16")
        _mark_fields(action.anchor_x, object_names, roles, "i16")
        _mark_fields(action.anchor_y, object_names, roles, "i16")

    result: list[FieldSpec] = []
    for name in sorted(roles):
        field_roles = roles[name]
        values = tuple(sorted(string_values.get(name, ())))
        default = getattr_defaults.get(name)
        if values:
            if field_roles & {"u16", "i16", "bool"}:
                raise DrawCBackendError(
                    "PZDPC009",
                    f"string state field {name!r} also has scalar role "
                    f"{sorted(field_roles)!r}")
            kind, c_type = "string_state", "uint16_t"
        elif field_roles <= {"scalar", "comparison", "bool"} and (
                "bool" in field_roles or isinstance(default, bool)):
            kind, c_type = "boolean", "uint8_t"
        elif "i16" in field_roles and "u16" not in field_roles:
            kind, c_type = "signed_scalar", "int16_t"
        elif "u16" in field_roles and "i16" not in field_roles:
            kind, c_type = "unsigned_scalar", "uint16_t"
        else:
            kind, c_type = "scalar", "int32_t"
        result.append(FieldSpec(
            name=name, kind=kind, c_type=c_type,
            string_values=values, getattr_default=default))

    if not result:
        raise DrawCBackendError("PZDPC010", "object view has no read fields")
    encoded: dict[str, str] = {}
    for field in result:
        token = _identifier(field.name)
        prior = encoded.setdefault(token, field.name)
        if prior != field.name:
            raise DrawCBackendError(
                "PZDPC011",
                f"object field identifier collision: {prior!r}/{field.name!r}")
        state_tokens: dict[str, str] = {}
        for value in field.string_values:
            state_token = _identifier(value, upper=True)
            state_prior = state_tokens.setdefault(state_token, value)
            if state_prior != value:
                raise DrawCBackendError(
                    "PZDPC011",
                    f"state tag collision for {field.name!r}: "
                    f"{state_prior!r}/{value!r}")
    return tuple(result)


def _is_resources_types(value: DrawExpr) -> bool:
    return (
        value.op == "attribute" and value.value == "types" and
        len(value.arguments) == 1 and
        value.arguments[0].op == "attribute" and
        value.arguments[0].value == "resources" and
        len(value.arguments[0].arguments) == 1 and
        _name_is(value.arguments[0].arguments[0], "self")
    )


def _validate_normalized_shapes(model: DrawCBackendModel) -> None:
    object_names = model.object_bound_names
    transient_names = {
        name
        for loop in model.loops if loop.kind == "transients"
        for name in loop.bound_names
    }
    field_names = {item.name for item in model.fields}
    class_names = set(model.class_tags)
    for expression in _all_expressions(model.plan):
        for node in _walk(expression):
            if node.op == "name":
                if node.value not in object_names | transient_names | {"self"}:
                    raise DrawCBackendError(
                        "PZDPC012", f"unbound normalized name {node.value!r}")
            elif node.op == "attribute":
                field = _object_attribute(node, object_names)
                if field is not None:
                    if field not in field_names:
                        raise DrawCBackendError(
                            "PZDPC013", f"unmodelled object field {field!r}")
                elif not (
                    (len(node.arguments) == 1 and
                     _name_is(node.arguments[0], "self")) or
                    _is_resources_types(node)
                ):
                    # ``self.resources`` is allowed only as the middle of the
                    # exact ``self.resources.types[palette]`` shape.
                    if not (
                        node.value == "resources" and
                        len(node.arguments) == 1 and
                        _name_is(node.arguments[0], "self")
                    ):
                        raise DrawCBackendError(
                            "PZDPC013",
                            f"attribute shape has no normalized ABI: "
                            f"{node.as_dict()!r}")
            elif node.op == "getattr":
                field = _object_attribute(node, object_names)
                if field is None or field not in field_names:
                    raise DrawCBackendError(
                        "PZDPC013", "getattr is not on a normalized object field")
            elif node.op == "type":
                if node.value not in class_names:
                    raise DrawCBackendError(
                        "PZDPC014", f"unregistered class tag {node.value!r}")
            elif node.op == "subscript":
                if not _is_resources_types(node.arguments[0]):
                    raise DrawCBackendError(
                        "PZDPC015",
                        "only self.resources.types[palette] has a C resolver")

    # The five-column normalized transient ABI is positional, like the Python
    # tuple destructuring.  Every transient action may still reorder/use the
    # bound names through its IR expressions.
    for loop in model.loops:
        if loop.kind == "transients" and len(loop.bound_names) != 5:
            raise DrawCBackendError("PZDPC006", "bad transient tuple arity")


def build_draw_c_model(
        plan: SpriteDrawPlanIR, *, prefix: str = "rtype_python_draw_plan",
        source_text: str | None = None,
        ) -> DrawCBackendModel:
    """Validate and normalize one target-neutral draw plan for C lowering."""
    if plan.format != DRAW_PLAN_FORMAT:
        raise DrawCBackendError(
            "PZDPC016", f"unsupported plan format {plan.format!r}")
    clean_prefix = _identifier(prefix)
    if clean_prefix != prefix or not re.fullmatch(r"[a-z_][a-z0-9_]*", prefix):
        raise DrawCBackendError(
            "PZDPC017", f"C symbol prefix is not normalized: {prefix!r}")
    for expression in _all_expressions(plan):
        _validate_expr(expression)
    loops = _loop_specs(plan)
    tags = _class_tags(plan)
    memberships, graph_hash = _class_memberships(
        plan, tags, source_text)
    model = DrawCBackendModel(
        plan=plan,
        prefix=prefix,
        macro_prefix=prefix.upper(),
        class_tags=tags,
        class_memberships=memberships,
        class_graph_sha256=graph_hash,
        fields=_field_specs(plan, loops),
        loops=loops,
    )
    _validate_normalized_shapes(model)
    return model


class _CExprEmitter:
    def __init__(
            self, model: DrawCBackendModel, loop: _LoopSpec,
            *, object_var: str = "object", transient_var: str = "transient",
            helpers: Mapping[object, str] | None = None,
            suppress_helper_key: object | None = None,
            ) -> None:
        self.model = model
        self.loop = loop
        self.object_var = object_var
        self.transient_var = transient_var
        self.helpers = helpers or {}
        self.suppress_helper_key = suppress_helper_key
        self.object_names = model.object_bound_names
        self.field_by_name = {item.name: item for item in model.fields}
        self.transient_bindings = dict(zip(
            loop.bound_names, (name for name, _ in _TRANSIENT_FIELDS)))

    def _field(self, value: DrawExpr) -> FieldSpec | None:
        name = _object_attribute(value, self.object_names)
        return self.field_by_name.get(name) if name is not None else None

    def _state_macro(self, field: FieldSpec, value: str) -> str:
        if value not in field.string_values:
            return f"{self.model.macro_prefix}_STATE_{_identifier(field.name, upper=True)}_OTHER"
        return (
            f"{self.model.macro_prefix}_STATE_"
            f"{_identifier(field.name, upper=True)}_"
            f"{_identifier(value, upper=True)}")

    def _string_compare(self, value: DrawExpr) -> str | None:
        if value.op not in ("equal", "not_equal"):
            return None
        left, right = value.arguments
        for candidate, literal, reverse in (
                (left, right, False), (right, left, True)):
            field = self._field(candidate)
            if (field is None or field.kind != "string_state" or
                    literal.op != "constant" or
                    not isinstance(literal.value, str)):
                continue
            operator = "==" if value.op == "equal" else "!="
            field_expr = self.emit(candidate)
            literal_expr = self._state_macro(field, literal.value)
            if reverse:
                return f"({literal_expr} {operator} {field_expr})"
            return f"({field_expr} {operator} {literal_expr})"
        return None

    def emit(self, value: DrawExpr) -> str:
        key = value.semantic_key()
        helper = self.helpers.get(key)
        if helper is not None and key != self.suppress_helper_key:
            row = self.object_var if self.loop.kind == "objects" else self.transient_var
            return f"{helper}({row}, input)"
        string_compare = self._string_compare(value)
        if string_compare is not None:
            return string_compare
        op = value.op
        if op == "constant":
            if isinstance(value.value, bool):
                return "1" if value.value else "0"
            if isinstance(value.value, int) and not isinstance(value.value, bool):
                return str(value.value)
            raise DrawCBackendError(
                "PZDPC018",
                f"constant {value.value!r} has no scalar C representation")
        if op == "name":
            if value.value in self.object_names:
                raise DrawCBackendError(
                    "PZDPC019", "whole normalized object used as scalar")
            field = self.transient_bindings.get(str(value.value))
            if field is not None:
                return f"((int32_t){self.transient_var}->{field})"
            raise DrawCBackendError(
                "PZDPC019", f"name {value.value!r} has no scalar C binding")
        if op in ("attribute", "getattr"):
            field = self._field(value)
            if field is None:
                raise DrawCBackendError(
                    "PZDPC020", "non-object attribute used as a scalar")
            return (
                f"((int32_t){self.object_var}->field_"
                f"{_identifier(field.name)})")
        if op == "not":
            return f"(!({self.emit(value.arguments[0])}))"
        if op == "all":
            return "(" + " && ".join(
                f"({self.emit(item)})" for item in value.arguments) + ")"
        if op == "add":
            return (
                f"(({self.emit(value.arguments[0])}) + "
                f"({self.emit(value.arguments[1])}))")
        if op in ("equal", "not_equal"):
            operator = "==" if op == "equal" else "!="
            return (
                f"(({self.emit(value.arguments[0])}) {operator} "
                f"({self.emit(value.arguments[1])}))")
        if op == "select":
            return (
                f"(({self.emit(value.arguments[0])}) ? "
                f"({self.emit(value.arguments[1])}) : "
                f"({self.emit(value.arguments[2])}))")
        if op == "type_is":
            subject, types = value.arguments
            if not (subject.op == "name" and
                    subject.value in self.object_names and
                    types.op == "types"):
                raise DrawCBackendError(
                    "PZDPC021", "type_is subject/types have no normalized ABI")
            tests: list[str] = []
            for item in types.arguments:
                if item.op != "type" or not isinstance(item.value, str):
                    raise DrawCBackendError("PZDPC021", "invalid type tag")
                tests.append(
                    f"{self.model.prefix}_object_is({self.object_var}, "
                    f"{self.model.macro_prefix}_CLASS_"
                    f"{_identifier(item.value, upper=True)})")
            return "(" + " || ".join(tests) + ")"
        if op == "subscript":
            base, index = value.arguments
            if not _is_resources_types(base):
                raise DrawCBackendError(
                    "PZDPC015", "subscript does not use the resource resolver")
            return (
                "((int32_t)input->resolve_resource_type("
                "input->resource_context, (uint16_t)("
                f"{self.emit(index)})))")
        raise DrawCBackendError(
            "PZDPC001", f"unsupported scalar DrawExpr op {op!r}")


def _condition(emitter: _CExprEmitter, action: DrawRecordActionIR) -> str:
    if not action.conditions:
        return "1"
    return " && ".join(f"({emitter.emit(item)})" for item in action.conditions)


def _record_values(
        emitter: _CExprEmitter, action: DrawRecordActionIR,
        ) -> tuple[str, str, str, str, str]:
    return (
        emitter.emit(action.descriptor),
        emitter.emit(action.palette),
        emitter.emit(action.resource_type),
        emitter.emit(action.anchor_x),
        emitter.emit(action.anchor_y),
    )


_HELPER_OPS = frozenset({
    "not", "all", "add", "equal", "not_equal", "select", "getattr",
    "type_is", "subscript",
})


def _loop_helper_expressions(
        model: DrawCBackendModel, loop: _LoopSpec,
        ) -> tuple[tuple[object, DrawExpr, str], ...]:
    counts: Counter[object] = Counter()
    values: dict[object, DrawExpr] = {}
    for ordinal in loop.action_ordinals:
        action = model.plan.actions[ordinal]
        for expression in (
                *action.conditions, action.descriptor, action.palette,
                action.resource_type, action.anchor_x, action.anchor_y):
            for node in _walk(expression):
                key = node.semantic_key()
                counts[key] += 1
                values.setdefault(key, node)

    def depth(value: DrawExpr) -> int:
        return 1 + max((depth(item) for item in value.arguments), default=0)

    selected = [
        (key, values[key]) for key, count in counts.items()
        if count > 1 and values[key].op in _HELPER_OPS
    ]
    selected.sort(key=lambda item: (
        depth(item[1]), repr(item[0])))
    kind = "object" if loop.kind == "objects" else "transient"
    return tuple(
        (key, value, f"{model.prefix}_{kind}_expr_{index}")
        for index, (key, value) in enumerate(selected)
    )


def _helper_lines(
        model: DrawCBackendModel, loop: _LoopSpec,
        helpers: tuple[tuple[object, DrawExpr, str], ...],
        ) -> list[str]:
    if not helpers:
        return []
    mapping = {key: name for key, _value, name in helpers}
    row_type = (
        f"{model.prefix}_object_view"
        if loop.kind == "objects"
        else f"{model.prefix}_transient_view")
    row_name = "object" if loop.kind == "objects" else "transient"
    lines: list[str] = []
    for _key, _value, name in helpers:
        lines.extend([
            f"static int32_t {name}(",
            f"    const {row_type} *{row_name},",
            f"    const {model.prefix}_input *input);",
        ])
    lines.append("")
    for key, value, name in helpers:
        emitter = _CExprEmitter(
            model, loop, helpers=mapping, suppress_helper_key=key)
        lines.extend([
            f"static int32_t {name}(",
            f"    const {row_type} *{row_name},",
            f"    const {model.prefix}_input *input)",
            "{",
            f"    return (int32_t)({emitter.emit(value)});",
            "}",
            "",
        ])
    return lines


def _header(model: DrawCBackendModel, header_name: str) -> str:
    prefix = model.prefix
    macro = model.macro_prefix
    guard = f"{macro}_H"
    lines = [
        "/* Generated from SpriteDrawPlanIR. Do not edit. */",
        f"/* plan semantic SHA-256: {model.plan.semantic_sha256} */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        f"#define {macro}_CLASS_TAG_COUNT {len(model.class_tags)}u",
        f"#define {macro}_CLASS_BIT_BYTES {model.class_bit_bytes}u",
    ]
    for index, name in enumerate(model.class_tags):
        lines.append(
            f"#define {macro}_CLASS_{_identifier(name, upper=True)} {index}u")
    lines.append("")
    for field in model.fields:
        if not field.string_values:
            continue
        field_token = _identifier(field.name, upper=True)
        lines.append(f"#define {macro}_STATE_{field_token}_OTHER 0u")
        for index, value in enumerate(field.string_values, 1):
            lines.append(
                f"#define {macro}_STATE_{field_token}_"
                f"{_identifier(value, upper=True)} {index}u")
    if any(item.string_values for item in model.fields):
        lines.append("")
    lines.extend([
        f"typedef struct {prefix}_object_view {{",
        f"    uint8_t class_bits[{macro}_CLASS_BIT_BYTES];",
    ])
    for field in model.fields:
        lines.append(
            f"    {field.c_type} field_{_identifier(field.name)};")
    lines.extend([
        f"}} {prefix}_object_view;",
        "",
        f"typedef struct {prefix}_transient_view {{",
    ])
    for name, c_type in _TRANSIENT_FIELDS:
        lines.append(f"    {c_type} {name};")
    lines.extend([
        f"}} {prefix}_transient_view;",
        "",
        f"typedef struct {prefix}_record {{",
        "    uint16_t bank_key;",
        "    uint16_t descriptor;",
        "    int16_t anchor_x;",
        "    int16_t anchor_y;",
        f"}} {prefix}_record;",
        "",
        f"typedef uint16_t (*{prefix}_resource_type_resolver)(",
        "    void *context, uint16_t palette);",
        f"typedef uint16_t (*{prefix}_bank_key_resolver)(",
        "    void *context, uint16_t palette, uint16_t resource_type);",
        f"typedef uint8_t (*{prefix}_record_emitter)(",
        f"    void *context, const {prefix}_record *record);",
        "",
        f"typedef struct {prefix}_input {{",
        f"    const {prefix}_object_view *objects;",
        "    uint16_t object_count;",
        f"    const {prefix}_transient_view *transients;",
        "    uint16_t transient_count;",
        f"    {prefix}_resource_type_resolver resolve_resource_type;",
        "    void *resource_context;",
        f"    {prefix}_bank_key_resolver resolve_bank_key;",
        "    void *bank_context;",
        f"}} {prefix}_input;",
        "",
        f"typedef enum {prefix}_status {{",
        f"    {macro}_OK = 0,",
        f"    {macro}_INVALID_INPUT = 1,",
        f"    {macro}_CAPACITY = 2,",
        f"    {macro}_RANGE = 3,",
        f"    {macro}_EMITTER = 4",
        f"}} {prefix}_status;",
        "",
        "/*",
        " * Callbacks are total and deterministic.  The preflight pass invokes",
        " * neither callback.  On every non-OK return the output buffer and",
        " * *output_count are unchanged; in particular CAPACITY is atomic.",
        " */",
        f"{prefix}_status {prefix}_produce(",
        f"    const {prefix}_input *input,",
        f"    {prefix}_record *output, uint16_t capacity,",
        "    uint16_t *output_count);",
        "",
        "/*",
        " * Streaming form for bounded target adapters.  It performs the same",
        " * callback-free count/range preflight, then visits every record in",
        " * strict Python order without requiring a frame-sized record array.",
        " * A zero emitter result stops immediately with EMITTER; in that case",
        " * *output_count is the number of records accepted before the failure.",
        " */",
        f"{prefix}_status {prefix}_stream(",
        f"    const {prefix}_input *input,",
        f"    {prefix}_record_emitter emit_record, void *emit_context,",
        "    uint16_t *output_count);",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        f"#endif /* {guard} */",
        "",
    ])
    return "\n".join(lines)


def _action_preflight_lines(
        model: DrawCBackendModel, loop: _LoopSpec,
        action: DrawRecordActionIR,
        helpers: Mapping[object, str],
        ) -> list[str]:
    emitter = _CExprEmitter(model, loop, helpers=helpers)
    descriptor, palette, _resource, anchor_x, anchor_y = _record_values(
        emitter, action)
    condition = _condition(emitter, action)
    return [
        f"        /* IR action {action.ordinal}, source sink "
        f"{action.sink_ordinal}, expansion {action.expansion_ordinal}. */",
        f"        if ({condition}) {{",
        f"            const int32_t descriptor_value = {descriptor};",
        f"            const int32_t palette_value = {palette};",
        f"            const int32_t anchor_x_value = {anchor_x};",
        f"            const int32_t anchor_y_value = {anchor_y};",
        "            if (descriptor_value < 0 || descriptor_value > 65535L ||",
        "                    palette_value < 0 || palette_value > 65535L ||",
        "                    anchor_x_value < -32768L || anchor_x_value > 32767L ||",
        "                    anchor_y_value < -32768L || anchor_y_value > 32767L) {",
        f"                return {model.macro_prefix}_RANGE;",
        "            }",
        "            ++needed;",
        "            if (needed > 65535UL) {",
        f"                return {model.macro_prefix}_CAPACITY;",
        "            }",
        "        }",
    ]


def _action_emit_lines(
        model: DrawCBackendModel, loop: _LoopSpec,
        action: DrawRecordActionIR,
        helpers: Mapping[object, str],
        ) -> list[str]:
    emitter = _CExprEmitter(model, loop, helpers=helpers)
    descriptor, palette, resource, anchor_x, anchor_y = _record_values(
        emitter, action)
    condition = _condition(emitter, action)
    return [
        f"        /* IR action {action.ordinal}, strict Python order. */",
        f"        if ({condition}) {{",
        f"            const uint16_t descriptor_value = (uint16_t)({descriptor});",
        f"            const uint16_t palette_value = (uint16_t)({palette});",
        f"            const uint16_t resource_type_value = (uint16_t)({resource});",
        f"            const int16_t anchor_x_value = (int16_t)({anchor_x});",
        f"            const int16_t anchor_y_value = (int16_t)({anchor_y});",
        f"            {model.prefix}_record record_value;",
        "            record_value.bank_key = input->resolve_bank_key(",
        "                input->bank_context, palette_value, resource_type_value);",
        "            record_value.descriptor = descriptor_value;",
        "            record_value.anchor_x = anchor_x_value;",
        "            record_value.anchor_y = anchor_y_value;",
        "            if (emit_record(emit_context, &record_value) == 0u) {",
        "                *emitted_count = write_index;",
        f"                return {model.macro_prefix}_EMITTER;",
        "            }",
        "            ++write_index;",
        "        }",
    ]


def _loop_lines(
        model: DrawCBackendModel, loop: _LoopSpec, *, preflight: bool,
        helpers: Mapping[object, str],
        ) -> list[str]:
    plan_actions = model.plan.actions
    if loop.kind == "objects":
        lines = [
            "    for (item_index = 0; item_index < input->object_count; ++item_index) {",
            f"        const {model.prefix}_object_view *object =",
            "            &input->objects[item_index];",
        ]
    else:
        lines = [
            "    for (item_index = 0; item_index < input->transient_count; ++item_index) {",
            f"        const {model.prefix}_transient_view *transient =",
            "            &input->transients[item_index];",
        ]
    for ordinal in loop.action_ordinals:
        action = plan_actions[ordinal]
        lines.extend(
            _action_preflight_lines(model, loop, action, helpers)
            if preflight else _action_emit_lines(
                model, loop, action, helpers))
    lines.append("    }")
    return lines


def _source(
        model: DrawCBackendModel, header_name: str,
        ) -> str:
    prefix = model.prefix
    macro = model.macro_prefix
    helper_rows = {
        loop.loop_id: _loop_helper_expressions(model, loop)
        for loop in model.loops
    }
    helper_maps = {
        loop_id: {key: name for key, _value, name in values}
        for loop_id, values in helper_rows.items()
    }
    lines = [
        "/* Generated from SpriteDrawPlanIR. Do not edit. */",
        f"/* source: {model.plan.source_path} */",
        f"/* plan semantic SHA-256: {model.plan.semantic_sha256} */",
        f'#include "{header_name}"',
        "#include <stddef.h>",
        "",
        f"typedef char {prefix}_assert_record_size[",
        f"    (sizeof({prefix}_record) == {RECORD_SIZE}) ? 1 : -1];",
        f"typedef char {prefix}_assert_bank_key_offset[",
        f"    (offsetof({prefix}_record, bank_key) == 0) ? 1 : -1];",
        f"typedef char {prefix}_assert_descriptor_offset[",
        f"    (offsetof({prefix}_record, descriptor) == 2) ? 1 : -1];",
        f"typedef char {prefix}_assert_anchor_x_offset[",
        f"    (offsetof({prefix}_record, anchor_x) == 4) ? 1 : -1];",
        f"typedef char {prefix}_assert_anchor_y_offset[",
        f"    (offsetof({prefix}_record, anchor_y) == 6) ? 1 : -1];",
        "",
        f"static uint8_t {prefix}_object_is(",
        f"        const {prefix}_object_view *object, uint16_t class_tag)",
        "{",
        "    const uint8_t mask = (uint8_t)(1u << (class_tag & 7u));",
        "    return (uint8_t)((object->class_bits[class_tag >> 3] & mask) != 0u);",
        "}",
        "",
    ]
    for loop in model.loops:
        lines.extend(_helper_lines(
            model, loop, helper_rows[loop.loop_id]))
    lines.extend([
        f"static uint8_t {prefix}_input_valid(",
        f"        const {prefix}_input *input)",
        "{",
        "    return (uint8_t)(input != NULL &&",
        "            input->resolve_resource_type != NULL &&",
        "            input->resolve_bank_key != NULL &&",
        "            (input->object_count == 0u || input->objects != NULL) &&",
        "            (input->transient_count == 0u || input->transients != NULL));",
        "}",
        "",
        f"static {prefix}_status {prefix}_preflight(",
        f"        const {prefix}_input *input, uint16_t *needed_out)",
        "{",
        "    uint32_t needed = 0;",
        "    uint16_t item_index;",
        "",
        "    /* Pass one: exact count and all fallible range checks, no writes. */",
    ])
    for loop in model.loops:
        lines.extend(_loop_lines(
            model, loop, preflight=True,
            helpers=helper_maps[loop.loop_id]))
    lines.extend([
        "",
        "    *needed_out = (uint16_t)needed;",
        f"    return {macro}_OK;",
        "}",
        "",
        f"static {prefix}_status {prefix}_emit_ordered(",
        f"        const {prefix}_input *input,",
        f"        {prefix}_record_emitter emit_record, void *emit_context,",
        "        uint16_t *emitted_count)",
        "{",
        "    uint16_t item_index;",
        "    uint16_t write_index = 0;",
        "",
        "    /* Pass two: emit the already-proved records in Python loop order. */",
    ])
    for loop in model.loops:
        lines.extend(_loop_lines(
            model, loop, preflight=False,
            helpers=helper_maps[loop.loop_id]))
    lines.extend([
        "",
        "    *emitted_count = write_index;",
        f"    return {macro}_OK;",
        "}",
        "",
        f"typedef struct {prefix}_buffer_sink {{",
        f"    {prefix}_record *next;",
        f"}} {prefix}_buffer_sink;",
        "",
        f"static uint8_t {prefix}_emit_to_buffer(",
        f"        void *context, const {prefix}_record *record)",
        "{",
        f"    {prefix}_buffer_sink *sink = ({prefix}_buffer_sink *)context;",
        "    *sink->next = *record;",
        "    ++sink->next;",
        "    return 1u;",
        "}",
        "",
        f"{prefix}_status {prefix}_produce(",
        f"        const {prefix}_input *input,",
        f"        {prefix}_record *output, uint16_t capacity,",
        "        uint16_t *output_count)",
        "{",
        f"    {prefix}_status status;",
        f"    {prefix}_buffer_sink sink;",
        "    uint16_t needed;",
        "    uint16_t emitted;",
        "",
        f"    if (output_count == NULL || !{prefix}_input_valid(input)) {{",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        f"    status = {prefix}_preflight(input, &needed);",
        f"    if (status != {macro}_OK) {{",
        "        return status;",
        "    }",
        "    if (needed > capacity) {",
        f"        return {macro}_CAPACITY;",
        "    }",
        "    if (needed != 0u && output == NULL) {",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        "    sink.next = output;",
        f"    status = {prefix}_emit_ordered(",
        f"        input, {prefix}_emit_to_buffer, &sink, &emitted);",
        f"    if (status != {macro}_OK) {{",
        "        return status;",
        "    }",
        "    if (emitted != needed) {",
        f"        return {macro}_EMITTER;",
        "    }",
        "    *output_count = emitted;",
        f"    return {macro}_OK;",
        "}",
        "",
        f"{prefix}_status {prefix}_stream(",
        f"        const {prefix}_input *input,",
        f"        {prefix}_record_emitter emit_record, void *emit_context,",
        "        uint16_t *output_count)",
        "{",
        f"    {prefix}_status status;",
        "    uint16_t needed;",
        "    uint16_t emitted = 0;",
        "",
        f"    if (output_count == NULL || !{prefix}_input_valid(input)) {{",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        f"    status = {prefix}_preflight(input, &needed);",
        f"    if (status != {macro}_OK) {{",
        "        return status;",
        "    }",
        "    if (needed != 0u && emit_record == NULL) {",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        "    if (needed != 0u) {",
        f"        status = {prefix}_emit_ordered(",
        "            input, emit_record, emit_context, &emitted);",
        f"        if (status == {macro}_EMITTER) {{",
        "            *output_count = emitted;",
        "            return status;",
        "        }",
        f"        if (status != {macro}_OK || emitted != needed) {{",
        "            return status;",
        "        }",
        "    }",
        "    *output_count = emitted;",
        f"    return {macro}_OK;",
        "}",
        "",
    ])
    return "\n".join(lines)


def _manifest(
        model: DrawCBackendModel, header_name: str, source_name: str,
        header: str, source: str,
        ) -> str:
    helper_count = sum(
        len(_loop_helper_expressions(model, loop)) for loop in model.loops)
    value = {
        "format": BACKEND_FORMAT,
        "plan": {
            "format": model.plan.format,
            "symbol": model.plan.symbol,
            "source_path": model.plan.source_path,
            "source_sha256": model.plan.source_sha256,
            "method_ast_sha256": model.plan.method_ast_sha256,
            "semantic_sha256": model.plan.semantic_sha256,
            "sink_order_sha256": model.plan.sink_order_sha256,
            "action_count": len(model.plan.actions),
        },
        "normalized_abi": {
            "class_identity": {
                "encoding": "isinstance-bitset-lsb0",
                "bit_bytes": model.class_bit_bytes,
                "ast_class_graph_sha256": model.class_graph_sha256,
                "tags": [
                    {"name": name, "tag": index}
                    for index, name in enumerate(model.class_tags)
                ],
                "local_class_memberships": [
                    {
                        "concrete_class": name,
                        "isinstance_tags": list(tags),
                    }
                    for name, tags in model.class_memberships
                ],
                "adapter_precondition": (
                    "set every tag bit listed for the concrete class; "
                    "unknown runtime classes fail target-layout adaptation"),
            },
            "object_view": {
                "layout_owner": "target-layout-adapter",
                "fields": [item.as_dict() for item in model.fields],
            },
            "resources": {
                "operation": "palette-to-resource-type",
                "callback": (
                    "uint16_t (*)(void *context, uint16_t palette)"),
                "abi_precondition": "total, deterministic, nonmutating",
            },
            "transient_tuple_view": {
                "fields": [
                    {"name": name, "c_type": c_type}
                    for name, c_type in _TRANSIENT_FIELDS
                ],
            },
            "bank_identity": {
                "operation": "palette-resource-type-to-bank-key",
                "callback": (
                    "uint16_t (*)(void *context, uint16_t palette, "
                    "uint16_t resource_type)"),
                "abi_precondition": "total, deterministic, nonmutating",
                "host_validation": {
                    "required_before_target_build": True,
                    "domain_source": "target-layout-adapter manifest",
                    "proof_function": "validate_resolver_domains",
                    "checks": [
                        "every declared palette",
                        "every declared palette/resource_type pair",
                        "uint16 result range",
                        "repeat-call determinism",
                    ],
                },
            },
            "output_record": {
                "size": RECORD_SIZE,
                "byte_order": "target-native-u16-fields",
                "fields": [
                    {"name": "bank_key", "c_type": "uint16_t", "offset": 0},
                    {"name": "descriptor", "c_type": "uint16_t", "offset": 2},
                    {"name": "anchor_x", "c_type": "int16_t", "offset": 4},
                    {"name": "anchor_y", "c_type": "int16_t", "offset": 6},
                ],
            },
            "failure_atomicity": {
                "preflight": "count-and-range-without-callbacks-or-writes",
                "non_ok_output_unchanged": True,
                "capacity_failure_atomic": True,
            },
            "streaming": {
                "function": f"{model.prefix}_stream",
                "record_array_required": False,
                "order": "strict-active-Python-loop-order",
                "preflight_before_first_emission": True,
                "bounded_adapter_contract": (
                    "emitter may drain fixed-size chunks; zero return stops "
                    "without visiting later records"),
                "emitter_failure_reports_accepted_prefix": True,
            },
        },
        "lowering": {
            "loop_order": [item.as_dict() for item in model.loops],
            "action_ordinals": [item.ordinal for item in model.plan.actions],
            "source_sink_ordinals": [
                item.sink_ordinal for item in model.plan.actions
            ],
            "expression_cse": {
                "algorithm": "semantic-key-pure-helper-functions",
                "helper_count": helper_count,
                "preserves_short_circuit": True,
                "callbacks_in_conditions": False,
            },
        },
        "verification_contract": {
            "host_semantics": {
                "required": True,
                "method": "compile-run-and-compare-entire-record-array-to-ir-oracle",
            },
            "pinned_sdcc_target_neutral_abi": {
                "scope": "generated-header-syntax-and-codegen-smoke",
                "flags": [
                    "-mz80", "--std-c11", "--sdcccall", "1",
                    "--nolospre", "--nolabelopt", "--noinvariant",
                    "--noinduction", "--noloopreverse", "--no-peep",
                ],
            },
            "live_target_performance_and_size_certified": False,
            "certification_blocker": (
                "requires the separate Z80 object-layout adapter and live "
                "FT812 integration; this backend intentionally owns neither"),
        },
        "artifacts": {
            "header": {
                "name": header_name,
                "sha256": _sha256_text(header),
            },
            "source": {
                "name": source_name,
                "sha256": _sha256_text(source),
                "utf8_bytes": len(source.encode("utf-8")),
            },
        },
    }
    return _json_text(value)


def emit_draw_c_backend(
        plan: SpriteDrawPlanIR, *, prefix: str = "rtype_python_draw_plan",
        stem: str | None = None,
        source_text: str | None = None,
        ) -> DrawCArtifacts:
    """Return deterministic C, header and manifest artifacts."""
    model = build_draw_c_model(
        plan, prefix=prefix, source_text=source_text)
    artifact_stem = stem or prefix
    if _identifier(artifact_stem) != artifact_stem:
        raise DrawCBackendError(
            "PZDPC017", f"artifact stem is not normalized: {artifact_stem!r}")
    header_name = artifact_stem + ".h"
    source_name = artifact_stem + ".c"
    manifest_name = artifact_stem + ".json"
    header = _header(model, header_name)
    source = _source(model, header_name)
    manifest = _manifest(
        model, header_name, source_name, header, source)
    return DrawCArtifacts(
        header_name=header_name,
        source_name=source_name,
        manifest_name=manifest_name,
        header=header,
        source=source,
        manifest=manifest,
    )


def write_draw_c_backend(
        plan: SpriteDrawPlanIR, output_directory: Path | str, *,
        prefix: str = "rtype_python_draw_plan", stem: str | None = None,
        source_text: str | None = None,
        ) -> DrawCArtifacts:
    """Materialize deterministic generated artifacts in one directory."""
    artifacts = emit_draw_c_backend(
        plan, prefix=prefix, stem=stem, source_text=source_text)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, contents in (
        (artifacts.header_name, artifacts.header),
        (artifacts.source_name, artifacts.source),
        (artifacts.manifest_name, artifacts.manifest),
    ):
        (directory / name).write_text(contents, encoding="utf-8", newline="\n")
    return artifacts


class _OracleEvaluator:
    def __init__(
            self, model: DrawCBackendModel, loop: _LoopSpec,
            environment: Mapping[str, object],
            resource_type_resolver: Callable[[int], int],
            ) -> None:
        self.model = model
        self.loop = loop
        self.environment = environment
        self.resource_type_resolver = resource_type_resolver

    def evaluate(self, value: DrawExpr) -> object:
        op = value.op
        if op == "constant":
            return value.value
        if op == "name":
            if value.value == "self":
                return _ORACLE_SELF
            try:
                return self.environment[str(value.value)]
            except KeyError as exc:
                raise DrawCBackendError(
                    "PZDPC030", f"oracle name {value.value!r} is unbound") from exc
        if op == "attribute":
            owner = self.evaluate(value.arguments[0])
            if isinstance(owner, NormalizedObjectView):
                try:
                    return owner.fields[str(value.value)]
                except KeyError as exc:
                    raise DrawCBackendError(
                        "PZDPC031",
                        f"normalized object lacks field {value.value!r}") from exc
            if owner is _ORACLE_SELF:
                return _OraclePath(str(value.value))
            if isinstance(owner, _OraclePath):
                return owner.child(str(value.value))
            raise DrawCBackendError(
                "PZDPC031", f"oracle cannot read attribute {value.value!r}")
        if op == "getattr":
            owner = self.evaluate(value.arguments[0])
            name = self.evaluate(value.arguments[1])
            if not isinstance(owner, NormalizedObjectView) or not isinstance(name, str):
                raise DrawCBackendError("PZDPC032", "invalid oracle getattr")
            if name in owner.fields:
                return owner.fields[name]
            if len(value.arguments) == 3:
                return self.evaluate(value.arguments[2])
            raise DrawCBackendError(
                "PZDPC031", f"normalized object lacks field {name!r}")
        if op == "not":
            return not bool(self.evaluate(value.arguments[0]))
        if op == "all":
            for item in value.arguments:
                if not bool(self.evaluate(item)):
                    return False
            return True
        if op == "add":
            return int(self.evaluate(value.arguments[0])) + int(
                self.evaluate(value.arguments[1]))
        if op in ("equal", "not_equal"):
            left = self.evaluate(value.arguments[0])
            right = self.evaluate(value.arguments[1])
            return left == right if op == "equal" else left != right
        if op == "select":
            branch = value.arguments[1] if bool(
                self.evaluate(value.arguments[0])) else value.arguments[2]
            return self.evaluate(branch)
        if op == "type_is":
            subject = self.evaluate(value.arguments[0])
            types = value.arguments[1]
            if not isinstance(subject, NormalizedObjectView) or types.op != "types":
                raise DrawCBackendError("PZDPC033", "invalid oracle type_is")
            return any(str(item.value) in subject.classes
                       for item in types.arguments)
        if op == "subscript":
            base = self.evaluate(value.arguments[0])
            index = int(self.evaluate(value.arguments[1]))
            if base != _OraclePath("resources.types"):
                raise DrawCBackendError("PZDPC034", "invalid oracle subscript")
            return self.resource_type_resolver(index)
        raise DrawCBackendError(
            "PZDPC001", f"unsupported oracle DrawExpr op {op!r}")


@dataclass(frozen=True)
class _OraclePath:
    value: str

    def child(self, name: str) -> "_OraclePath":
        return _OraclePath(self.value + "." + name)


_ORACLE_SELF = object()


def _check_record_ranges(
        descriptor: object, palette: object, resource_type: object,
        anchor_x: object, anchor_y: object,
        ) -> tuple[int, int, int, int, int]:
    values = tuple(int(item) for item in (
        descriptor, palette, resource_type, anchor_x, anchor_y))
    d, p, r, x, y = values
    if not (0 <= d <= 0xFFFF and 0 <= p <= 0xFFFF and
            0 <= r <= 0xFFFF and -0x8000 <= x <= 0x7FFF and
            -0x8000 <= y <= 0x7FFF):
        raise OverflowError(values)
    return d, p, r, x, y


def interpret_draw_plan(
        plan: SpriteDrawPlanIR, *,
        objects: Sequence[NormalizedObjectView],
        transients: Sequence[NormalizedTransientView],
        resource_type_resolver: Callable[[int], int],
        bank_key_resolver: Callable[[int, int], int],
        prefix: str = "rtype_python_draw_plan",
        action_trace: MutableSequence[int] | None = None,
        ) -> tuple[LiteralDrawRecord, ...]:
    """Execute the accepted IR directly as the generated C semantic oracle."""
    model = build_draw_c_model(plan, prefix=prefix)
    result: list[LiteralDrawRecord] = []
    action_by_ordinal = model.plan.actions
    for loop in model.loops:
        if loop.kind == "objects":
            rows: Iterable[Mapping[str, object]] = (
                {loop.bound_names[0]: item} for item in objects)
        else:
            rows = (
                dict(zip(loop.bound_names, (
                    item.descriptor, item.palette, item.resource_type,
                    item.x, item.y)))
                for item in transients
            )
        for environment in rows:
            evaluator = _OracleEvaluator(
                model, loop, environment, resource_type_resolver)
            for ordinal in loop.action_ordinals:
                action = action_by_ordinal[ordinal]
                if not all(bool(evaluator.evaluate(item))
                           for item in action.conditions):
                    continue
                d, p, r, x, y = _check_record_ranges(
                    evaluator.evaluate(action.descriptor),
                    evaluator.evaluate(action.palette),
                    evaluator.evaluate(action.resource_type),
                    evaluator.evaluate(action.anchor_x),
                    evaluator.evaluate(action.anchor_y))
                bank_key = int(bank_key_resolver(p, r))
                if not 0 <= bank_key <= 0xFFFF:
                    raise OverflowError(bank_key)
                if action_trace is not None:
                    action_trace.append(action.ordinal)
                result.append(LiteralDrawRecord(bank_key, d, x, y))
    return tuple(result)


def _preflight_oracle_count(
        plan: SpriteDrawPlanIR, *,
        objects: Sequence[NormalizedObjectView],
        transients: Sequence[NormalizedTransientView],
        prefix: str,
        ) -> int:
    """Mirror the generated first pass without invoking either callback."""
    model = build_draw_c_model(plan, prefix=prefix)

    def forbidden_resource(_palette: int) -> int:
        raise AssertionError("resource callback reached oracle preflight")

    needed = 0
    for loop in model.loops:
        if loop.kind == "objects":
            rows: Iterable[Mapping[str, object]] = (
                {loop.bound_names[0]: item} for item in objects)
        else:
            rows = (
                dict(zip(loop.bound_names, (
                    item.descriptor, item.palette, item.resource_type,
                    item.x, item.y)))
                for item in transients
            )
        for environment in rows:
            evaluator = _OracleEvaluator(
                model, loop, environment, forbidden_resource)
            for ordinal in loop.action_ordinals:
                action = model.plan.actions[ordinal]
                if not all(bool(evaluator.evaluate(item))
                           for item in action.conditions):
                    continue
                descriptor = evaluator.evaluate(action.descriptor)
                palette = evaluator.evaluate(action.palette)
                anchor_x = evaluator.evaluate(action.anchor_x)
                anchor_y = evaluator.evaluate(action.anchor_y)
                if any(node.op == "subscript"
                       for node in _walk(action.resource_type)):
                    resource_type: object = 0
                else:
                    resource_type = evaluator.evaluate(action.resource_type)
                _check_record_ranges(
                    descriptor, palette, resource_type, anchor_x, anchor_y)
                needed += 1
                if needed > 0xFFFF:
                    return needed
    return needed


def produce_draw_records_oracle(
        plan: SpriteDrawPlanIR, *,
        objects: Sequence[NormalizedObjectView],
        transients: Sequence[NormalizedTransientView],
        resource_type_resolver: Callable[[int], int],
        bank_key_resolver: Callable[[int, int], int],
        output: MutableSequence[LiteralDrawRecord], capacity: int,
        prefix: str = "rtype_python_draw_plan",
        ) -> ProducerStatus:
    """Atomic list analogue of the generated producer.

    The supplied sequence is extended only after complete evaluation and the
    capacity check.  This makes the capacity-failure invariant directly
    testable without a target ABI or emulator.
    """
    if capacity < 0 or capacity > 0xFFFF:
        return ProducerStatus.INVALID_INPUT
    try:
        needed = _preflight_oracle_count(
            plan, objects=objects, transients=transients, prefix=prefix)
    except OverflowError:
        return ProducerStatus.RANGE
    if needed > capacity:
        return ProducerStatus.CAPACITY
    try:
        records = interpret_draw_plan(
            plan, objects=objects, transients=transients,
            resource_type_resolver=resource_type_resolver,
            bank_key_resolver=bank_key_resolver, prefix=prefix)
    except OverflowError:
        return ProducerStatus.RANGE
    if len(records) != needed:
        raise AssertionError("oracle preflight/emit record count diverged")
    output.extend(records)
    return ProducerStatus.OK


def validate_resolver_domains(
        *, palette_domain: Iterable[int], resource_type_domain: Iterable[int],
        resource_type_resolver: Callable[[int], int],
        bank_key_resolver: Callable[[int, int], int],
        ) -> dict[str, object]:
    """Exhaustively prove the total callback ABI over declared host domains.

    Target integration must obtain both finite domains from its generated
    layout/resource manifest and retain this compact hash proof.  Exceptions,
    out-of-range values, non-determinism and an incomplete resource-type
    domain all fail before C is compiled for the target.
    """
    palettes = tuple(sorted(set(palette_domain)))
    resource_types = tuple(sorted(set(resource_type_domain)))
    if not palettes or not resource_types:
        raise DrawCBackendError(
            "PZDPC040", "resolver proof domains must both be non-empty")
    for kind, values in (
            ("palette", palettes), ("resource_type", resource_types)):
        if any(isinstance(item, bool) or not isinstance(item, int) or
               not 0 <= item <= 0xFFFF for item in values):
            raise DrawCBackendError(
                "PZDPC040", f"{kind} proof domain is not uint16")
    type_set = set(resource_types)
    resource_rows: list[tuple[int, int]] = []
    for palette in palettes:
        try:
            first = resource_type_resolver(palette)
            second = resource_type_resolver(palette)
        except Exception as exc:
            raise DrawCBackendError(
                "PZDPC041",
                f"resource resolver is not total for palette {palette}") from exc
        if (isinstance(first, bool) or not isinstance(first, int) or
                not 0 <= first <= 0xFFFF or first != second):
            raise DrawCBackendError(
                "PZDPC042",
                f"resource resolver invalid/non-deterministic at {palette}")
        if first not in type_set:
            raise DrawCBackendError(
                "PZDPC043",
                f"resource resolver returned undeclared type {first} at "
                f"palette {palette}")
        resource_rows.append((palette, first))

    bank_rows: list[tuple[int, int, int]] = []
    for palette in palettes:
        for resource_type in resource_types:
            try:
                first = bank_key_resolver(palette, resource_type)
                second = bank_key_resolver(palette, resource_type)
            except Exception as exc:
                raise DrawCBackendError(
                    "PZDPC044",
                    "bank resolver is not total for "
                    f"({palette}, {resource_type})") from exc
            if (isinstance(first, bool) or not isinstance(first, int) or
                    not 0 <= first <= 0xFFFF or first != second):
                raise DrawCBackendError(
                    "PZDPC045",
                    "bank resolver invalid/non-deterministic at "
                    f"({palette}, {resource_type})")
            bank_rows.append((palette, resource_type, first))

    return {
        "format": "pyz80.draw-resolver-domain-proof.v1",
        "palette_count": len(palettes),
        "resource_type_count": len(resource_types),
        "palette_resource_pair_count": len(bank_rows),
        "palette_domain_sha256": _sha256_text(_json_text(palettes)),
        "resource_type_domain_sha256": _sha256_text(_json_text(resource_types)),
        "resource_mapping_sha256": _sha256_text(_json_text(resource_rows)),
        "bank_mapping_sha256": _sha256_text(_json_text(bank_rows)),
        "total": True,
        "deterministic": True,
        "uint16_results": True,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the portable SpriteDrawPlanIR C producer")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--prefix", default="rtype_python_draw_plan")
    parser.add_argument("--stem")
    arguments = parser.parse_args()
    plan = compile_active_enemy_draw_plan(arguments.project_root)
    artifacts = write_draw_c_backend(
        plan, arguments.output_directory, prefix=arguments.prefix,
        stem=arguments.stem)
    print(_json_text({
        "format": BACKEND_FORMAT,
        "semantic_sha256": plan.semantic_sha256,
        "artifacts": [
            artifacts.header_name,
            artifacts.source_name,
            artifacts.manifest_name,
        ],
    }), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
