"""Compact portable C VM lowering for the active-Python sprite draw IR.

The older :mod:`pyz80_compiler.draw_c_backend` deliberately emits readable,
fully unrolled C.  That is a useful semantic oracle, but it is much too large
for a Z80 page.  This module consumes the *same* validated
``SpriteDrawPlanIR`` and emits a small table program plus one target-neutral C
interpreter.  It contains no handwritten action or gameplay table.

The compact format is intentionally bounded.  Node, condition-pack and action
identifiers are one byte.  Plans which do not fit are rejected rather than
silently truncated.  The manifest records every bound and the exact logical
table payload.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .draw_c_backend import (
    RECORD_SIZE,
    DrawCArtifacts,
    DrawCBackendError,
    DrawCBackendModel,
    FieldSpec,
    _TRANSIENT_FIELDS,
    _identifier,
    _is_resources_types,
    _object_attribute,
    build_draw_c_model,
)
from .draw_plan import DrawExpr, SpriteDrawPlanIR


VM_BACKEND_FORMAT = "pyz80.sprite-draw-vm-backend.v2"
VM_NODE_BYTES = 4
VM_ACTION_BYTES = 6
VM_CONDITION_PACK_BYTES = 2
VM_LOOP_BYTES = 3
VM_ID_LIMIT = 255
VM_OBJECT_VIEW_BYTES = 28

__all__ = [
    "VM_BACKEND_FORMAT",
    "VM_OBJECT_VIEW_BYTES",
    "DrawVMBackendError",
    "DrawVMProgram",
    "build_draw_vm_program",
    "emit_draw_vm_backend",
    "write_draw_vm_backend",
]


class DrawVMBackendError(DrawCBackendError):
    """Fail-closed compact-lowering error."""


@dataclass(frozen=True)
class _VMNode:
    op: str
    a: int = 0
    b: int = 0
    c: int = 0


@dataclass(frozen=True)
class _VMAction:
    condition_pack: int
    descriptor: int
    palette: int
    resource_type: int
    anchor_x: int
    anchor_y: int


@dataclass(frozen=True)
class _VMLoop:
    kind: str
    first_action: int
    action_count: int


@dataclass(frozen=True)
class DrawVMProgram:
    """Deterministic compact program derived only from validated draw IR."""

    model: DrawCBackendModel
    constants: tuple[int, ...]
    class_masks: tuple[tuple[int, ...], ...]
    nodes: tuple[_VMNode, ...]
    condition_ids: tuple[int, ...]
    condition_packs: tuple[tuple[int, int], ...]
    actions: tuple[_VMAction, ...]
    loops: tuple[_VMLoop, ...]
    max_eval_depth: int
    callback_node_ids: tuple[int, ...]

    @property
    def table_payload_bytes(self) -> int:
        return (
            len(self.constants) * 4 +
            len(self.class_masks) * self.model.class_bit_bytes +
            len(self.nodes) * VM_NODE_BYTES +
            len(self.condition_ids) +
            len(self.condition_packs) * VM_CONDITION_PACK_BYTES +
            len(self.actions) * VM_ACTION_BYTES +
            len(self.loops) * VM_LOOP_BYTES
        )


_OPCODE_ORDER = (
    "CONST",
    "OBJECT_FIELD",
    "TRANSIENT_FIELD",
    "CLASS_ANY",
    "NOT",
    "AND",
    "ADD",
    "EQUAL",
    "NOT_EQUAL",
    "SELECT",
    "RESOURCE_TYPE",
)
_OPCODE = {name: index for index, name in enumerate(_OPCODE_ORDER)}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"


def _contains_resource(
        node_id: int, nodes: tuple[_VMNode, ...] | list[_VMNode],
        memo: dict[int, bool],
        ) -> bool:
    cached = memo.get(node_id)
    if cached is not None:
        return cached
    node = nodes[node_id]
    if node.op == "RESOURCE_TYPE":
        result = True
    elif node.op in ("NOT",):
        result = _contains_resource(node.a, nodes, memo)
    elif node.op in ("AND", "ADD", "EQUAL", "NOT_EQUAL"):
        result = (
            _contains_resource(node.a, nodes, memo) or
            _contains_resource(node.b, nodes, memo)
        )
    elif node.op == "SELECT":
        result = any(_contains_resource(item, nodes, memo)
                     for item in (node.a, node.b, node.c))
    else:
        result = False
    memo[node_id] = result
    return result


class _ProgramBuilder:
    def __init__(self, model: DrawCBackendModel) -> None:
        self.model = model
        self.constants: list[int] = []
        self.constant_index: dict[int, int] = {}
        self.class_masks: list[tuple[int, ...]] = []
        self.class_mask_index: dict[tuple[int, ...], int] = {}
        self.nodes: list[_VMNode] = []
        self.node_index: dict[_VMNode, int] = {}
        self.condition_ids: list[int] = []
        self.condition_packs: list[tuple[int, int]] = []
        self.condition_pack_index: dict[tuple[int, ...], int] = {}
        self.field_index = {
            item.name: index for index, item in enumerate(model.fields)
        }
        self.field_by_name = {item.name: item for item in model.fields}
        self.class_index = {
            name: index for index, name in enumerate(model.class_tags)
        }

    @staticmethod
    def _bounded_count(label: str, count: int) -> None:
        if count > VM_ID_LIMIT:
            raise DrawVMBackendError(
                "PZDVM001",
                f"{label} count {count} exceeds compact uint8 limit "
                f"{VM_ID_LIMIT}")

    def _constant(self, value: int) -> int:
        if value < -0x80000000 or value > 0x7FFFFFFF:
            raise DrawVMBackendError(
                "PZDVM002", f"constant {value} does not fit int32")
        index = self.constant_index.get(value)
        if index is None:
            self._bounded_count("constant", len(self.constants) + 1)
            index = len(self.constants)
            self.constants.append(value)
            self.constant_index[value] = index
        return self._node(_VMNode("CONST", index))

    def _mask(self, names: Iterable[str]) -> int:
        row = [0] * self.model.class_bit_bytes
        for name in names:
            try:
                tag = self.class_index[name]
            except KeyError as exc:
                raise DrawVMBackendError(
                    "PZDVM003", f"unknown isinstance tag {name!r}") from exc
            row[tag >> 3] |= 1 << (tag & 7)
        value = tuple(row)
        index = self.class_mask_index.get(value)
        if index is None:
            self._bounded_count("class mask", len(self.class_masks) + 1)
            index = len(self.class_masks)
            self.class_masks.append(value)
            self.class_mask_index[value] = index
        return index

    def _node(self, value: _VMNode) -> int:
        index = self.node_index.get(value)
        if index is None:
            self._bounded_count("expression node", len(self.nodes) + 1)
            index = len(self.nodes)
            self.nodes.append(value)
            self.node_index[value] = index
        return index

    def _object_field(self, value: DrawExpr) -> FieldSpec | None:
        name = _object_attribute(value, self.model.object_bound_names)
        return self.field_by_name.get(name) if name is not None else None

    def _string_compare(
            self, value: DrawExpr, loop: object,
            ) -> int | None:
        if value.op not in ("equal", "not_equal"):
            return None
        left, right = value.arguments
        for candidate, literal in ((left, right), (right, left)):
            field = self._object_field(candidate)
            if (field is None or field.kind != "string_state" or
                    literal.op != "constant" or
                    not isinstance(literal.value, str)):
                continue
            try:
                state_tag = field.string_values.index(literal.value) + 1
            except ValueError:
                state_tag = 0
            field_node = self.expression(candidate, loop)
            constant_node = self._constant(state_tag)
            op = "EQUAL" if value.op == "equal" else "NOT_EQUAL"
            return self._node(_VMNode(op, field_node, constant_node))
        return None

    def expression(self, value: DrawExpr, loop: object) -> int:
        special = self._string_compare(value, loop)
        if special is not None:
            return special
        op = value.op
        if op == "constant":
            if isinstance(value.value, bool):
                return self._constant(1 if value.value else 0)
            if isinstance(value.value, int):
                return self._constant(value.value)
            raise DrawVMBackendError(
                "PZDVM004",
                f"constant {value.value!r} has no compact scalar encoding")
        if op == "name":
            bindings = dict(zip(
                loop.bound_names,
                (name for name, _c_type in _TRANSIENT_FIELDS),
            )) if loop.kind == "transients" else {}
            field = bindings.get(str(value.value))
            if field is not None:
                return self._node(_VMNode(
                    "TRANSIENT_FIELD",
                    next(index for index, (name, _c_type) in enumerate(
                        _TRANSIENT_FIELDS) if name == field),
                ))
            raise DrawVMBackendError(
                "PZDVM005", f"name {value.value!r} is not a scalar binding")
        if op in ("attribute", "getattr"):
            field = self._object_field(value)
            if field is None:
                raise DrawVMBackendError(
                    "PZDVM006", "non-object attribute used as scalar")
            return self._node(_VMNode(
                "OBJECT_FIELD", self.field_index[field.name]))
        if op == "not":
            return self._node(_VMNode(
                "NOT", self.expression(value.arguments[0], loop)))
        if op == "all":
            children = [self.expression(item, loop)
                        for item in value.arguments]
            if not children:
                raise DrawVMBackendError("PZDVM007", "empty all expression")
            result = children[0]
            for child in children[1:]:
                result = self._node(_VMNode("AND", result, child))
            return result
        if op in ("add", "equal", "not_equal"):
            left = self.expression(value.arguments[0], loop)
            right = self.expression(value.arguments[1], loop)
            encoded = {
                "add": "ADD", "equal": "EQUAL",
                "not_equal": "NOT_EQUAL",
            }[op]
            return self._node(_VMNode(encoded, left, right))
        if op == "select":
            return self._node(_VMNode(
                "SELECT",
                self.expression(value.arguments[0], loop),
                self.expression(value.arguments[1], loop),
                self.expression(value.arguments[2], loop),
            ))
        if op == "type_is":
            subject, types = value.arguments
            if not (subject.op == "name" and
                    subject.value in self.model.object_bound_names and
                    types.op == "types"):
                raise DrawVMBackendError(
                    "PZDVM008", "type_is shape has no normalized VM ABI")
            names: list[str] = []
            for item in types.arguments:
                if item.op != "type" or not isinstance(item.value, str):
                    raise DrawVMBackendError(
                        "PZDVM008", "invalid type tag in type_is")
                names.append(item.value)
            return self._node(_VMNode("CLASS_ANY", self._mask(names)))
        if op == "subscript":
            base, index = value.arguments
            if not _is_resources_types(base):
                raise DrawVMBackendError(
                    "PZDVM009", "subscript has no resource resolver")
            return self._node(_VMNode(
                "RESOURCE_TYPE", self.expression(index, loop)))
        raise DrawVMBackendError(
            "PZDVM010", f"unsupported compact scalar op {op!r}")

    def condition_pack(self, values: Iterable[DrawExpr], loop: object) -> int:
        key = tuple(self.expression(item, loop) for item in values)
        index = self.condition_pack_index.get(key)
        if index is None:
            self._bounded_count(
                "condition pack", len(self.condition_packs) + 1)
            if len(self.condition_ids) + len(key) > VM_ID_LIMIT:
                raise DrawVMBackendError(
                    "PZDVM001", "condition-id stream exceeds uint8 offset")
            index = len(self.condition_packs)
            start = len(self.condition_ids)
            self.condition_ids.extend(key)
            self.condition_packs.append((start, len(key)))
            self.condition_pack_index[key] = index
        return index


def _node_depth(node_id: int, nodes: tuple[_VMNode, ...], memo: dict[int, int]) -> int:
    cached = memo.get(node_id)
    if cached is not None:
        return cached
    node = nodes[node_id]
    if node.op in ("NOT", "RESOURCE_TYPE"):
        children = (node.a,)
    elif node.op in ("AND", "ADD", "EQUAL", "NOT_EQUAL"):
        children = (node.a, node.b)
    elif node.op == "SELECT":
        children = (node.a, node.b, node.c)
    else:
        children = ()
    result = 1 + max((_node_depth(item, nodes, memo)
                      for item in children), default=0)
    memo[node_id] = result
    return result


def _c_type_interval(c_type: str) -> tuple[int, int]:
    try:
        return {
            "uint8_t": (0, 0xFF),
            "uint16_t": (0, 0xFFFF),
            "int16_t": (-0x8000, 0x7FFF),
            "int32_t": (-0x80000000, 0x7FFFFFFF),
        }[c_type]
    except KeyError as exc:
        raise DrawVMBackendError(
            "PZDVM016", f"no interval model for C type {c_type!r}") from exc


def _node_interval(
        node_id: int, nodes: tuple[_VMNode, ...],
        constants: tuple[int, ...], model: DrawCBackendModel,
        memo: dict[int, tuple[int, int]],
        ) -> tuple[int, int]:
    """Prove every generated int32 operation free of signed C overflow."""
    cached = memo.get(node_id)
    if cached is not None:
        return cached
    node = nodes[node_id]
    if node.op == "CONST":
        result = (constants[node.a], constants[node.a])
    elif node.op == "OBJECT_FIELD":
        result = _c_type_interval(model.fields[node.a].c_type)
    elif node.op == "TRANSIENT_FIELD":
        result = _c_type_interval(_TRANSIENT_FIELDS[node.a][1])
    elif node.op in ("CLASS_ANY", "NOT", "AND", "EQUAL", "NOT_EQUAL"):
        result = (0, 1)
    elif node.op == "RESOURCE_TYPE":
        result = (0, 0xFFFF)
    elif node.op == "ADD":
        left = _node_interval(node.a, nodes, constants, model, memo)
        right = _node_interval(node.b, nodes, constants, model, memo)
        result = (left[0] + right[0], left[1] + right[1])
        if result[0] < -0x80000000 or result[1] > 0x7FFFFFFF:
            raise DrawVMBackendError(
                "PZDVM016",
                f"node {node_id} int32 addition interval {result} may overflow")
    elif node.op == "SELECT":
        when_true = _node_interval(
            node.b, nodes, constants, model, memo)
        when_false = _node_interval(
            node.c, nodes, constants, model, memo)
        result = (min(when_true[0], when_false[0]),
                  max(when_true[1], when_false[1]))
    else:
        raise DrawVMBackendError(
            "PZDVM016", f"node {node_id} has unknown interval op {node.op!r}")
    memo[node_id] = result
    return result


def build_draw_vm_program(
        plan: SpriteDrawPlanIR, *, prefix: str = "rtype_python_draw_vm",
        source_text: str | None = None,
        ) -> DrawVMProgram:
    """Validate ``plan`` and derive a compact immutable VM program."""
    model = build_draw_c_model(
        plan, prefix=prefix, source_text=source_text)
    object_storage_bytes = model.class_bit_bytes + sum({
        "uint8_t": 1,
        "uint16_t": 2,
        "int16_t": 2,
        "int32_t": 4,
    }[item.c_type] for item in model.fields)
    if object_storage_bytes != VM_OBJECT_VIEW_BYTES:
        raise DrawVMBackendError(
            "PZDVM018",
            "normalized object view changed from the proved 28-byte target "
            f"ABI to {object_storage_bytes} bytes")
    builder = _ProgramBuilder(model)
    loop_by_id = {item.loop_id: item for item in model.loops}
    actions: list[_VMAction] = []
    for expected_ordinal, action in enumerate(plan.actions):
        if action.ordinal != expected_ordinal:
            raise DrawVMBackendError(
                "PZDVM011", "action ordinals are not dense Python order")
        loop = loop_by_id[action.loop_id]
        actions.append(_VMAction(
            condition_pack=builder.condition_pack(action.conditions, loop),
            descriptor=builder.expression(action.descriptor, loop),
            palette=builder.expression(action.palette, loop),
            resource_type=builder.expression(action.resource_type, loop),
            anchor_x=builder.expression(action.anchor_x, loop),
            anchor_y=builder.expression(action.anchor_y, loop),
        ))
    builder._bounded_count("action", len(actions))

    loops: list[_VMLoop] = []
    expected_first = 0
    for loop in model.loops:
        ordinals = tuple(loop.action_ordinals)
        expected = tuple(range(expected_first, expected_first + len(ordinals)))
        if ordinals != expected:
            raise DrawVMBackendError(
                "PZDVM012",
                f"loop {loop.loop_id} action list is not one ordered range")
        builder._bounded_count(
            f"loop {loop.loop_id} action", len(ordinals))
        loops.append(_VMLoop(loop.kind, expected_first, len(ordinals)))
        expected_first += len(ordinals)
    builder._bounded_count("loop", len(loops))

    nodes = tuple(builder.nodes)
    resource_memo: dict[int, bool] = {}
    callback_ids = tuple(index for index in range(len(nodes))
                         if _contains_resource(index, nodes, resource_memo))
    # Preflight evaluates conditions and every output except resource_type.
    # Resolver reachability there would violate the atomic ABI, so reject it.
    for ordinal, action in enumerate(actions):
        start, count = builder.condition_packs[action.condition_pack]
        preflight_roots = (
            *builder.condition_ids[start:start + count],
            action.descriptor, action.palette,
            action.anchor_x, action.anchor_y,
        )
        if any(_contains_resource(item, nodes, resource_memo)
               for item in preflight_roots):
            raise DrawVMBackendError(
                "PZDVM013",
                f"action {ordinal} resolver is reachable during preflight")

    depth_memo: dict[int, int] = {}
    max_depth = max(
        (_node_depth(index, nodes, depth_memo)
         for index in range(len(nodes))), default=0)
    if max_depth > VM_ID_LIMIT:
        raise DrawVMBackendError(
            "PZDVM014", f"evaluation depth {max_depth} exceeds VM bound")

    interval_memo: dict[int, tuple[int, int]] = {}
    for index, node in enumerate(nodes):
        children = (
            (node.a,) if node.op in ("NOT", "RESOURCE_TYPE") else
            (node.a, node.b) if node.op in (
                "AND", "ADD", "EQUAL", "NOT_EQUAL") else
            (node.a, node.b, node.c) if node.op == "SELECT" else ()
        )
        if any(child >= index for child in children):
            raise DrawVMBackendError(
                "PZDVM017",
                f"node {index} is not a topological DAG row: {children!r}")
        _node_interval(
            index, nodes, tuple(builder.constants), model, interval_memo)

    return DrawVMProgram(
        model=model,
        constants=tuple(builder.constants),
        class_masks=tuple(builder.class_masks),
        nodes=nodes,
        condition_ids=tuple(builder.condition_ids),
        condition_packs=tuple(builder.condition_packs),
        actions=tuple(actions),
        loops=tuple(loops),
        max_eval_depth=max_depth,
        callback_node_ids=callback_ids,
    )


def _header(program: DrawVMProgram, header_name: str) -> str:
    model = program.model
    prefix, macro = model.prefix, model.macro_prefix
    lines = [
        "/* Generated from SpriteDrawPlanIR. Do not edit. */",
        "/* Compact target-neutral draw VM ABI. */",
        f"/* plan semantic SHA-256: {model.plan.semantic_sha256} */",
        f"#ifndef {macro}_H",
        f"#define {macro}_H",
        "",
        "#include <stdint.h>",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        f"#define {macro}_CLASS_TAG_COUNT {len(model.class_tags)}u",
        f"#define {macro}_CLASS_BIT_BYTES {model.class_bit_bytes}u",
        f"#define {macro}_MAX_EVAL_DEPTH {program.max_eval_depth}u",
        f"#define {macro}_OBJECT_VIEW_BYTES {VM_OBJECT_VIEW_BYTES}u",
    ]
    for index, name in enumerate(model.class_tags):
        lines.append(
            f"#define {macro}_CLASS_{_identifier(name, upper=True)} {index}u")
    lines.append("")
    for field in model.fields:
        if not field.string_values:
            continue
        token = _identifier(field.name, upper=True)
        lines.append(f"#define {macro}_STATE_{token}_OTHER 0u")
        for index, value in enumerate(field.string_values, 1):
            lines.append(
                f"#define {macro}_STATE_{token}_"
                f"{_identifier(value, upper=True)} {index}u")
    if any(item.string_values for item in model.fields):
        lines.append("")
    lines.extend([
        f"typedef struct {prefix}_object_view {{",
        f"    uint8_t class_bits[{macro}_CLASS_BIT_BYTES];",
    ])
    for field in model.fields:
        lines.append(f"    {field.c_type} field_{_identifier(field.name)};")
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
        f"typedef uint8_t (*{prefix}_object_loader)(",
        f"    void *context, uint16_t object_index,",
        f"    {prefix}_object_view *object_out);",
        "",
        f"typedef struct {prefix}_input {{",
        f"    const {prefix}_object_view *objects;",
        "    uint16_t object_count;",
        f"    {prefix}_object_loader load_object;",
        "    void *object_context;",
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
        f"    {macro}_EMITTER = 4,",
        f"    {macro}_OBJECT_LOADER = 5",
        f"}} {prefix}_status;",
        "",
        "/* Preflight invokes only load_object; no resolver, emitter or write. */",
        f"{prefix}_status {prefix}_produce(",
        f"    const {prefix}_input *input,",
        f"    {prefix}_record *output, uint16_t capacity,",
        "    uint16_t *output_count);",
        "",
        "/* Strict Python record order, with no frame-sized output required. */",
        f"{prefix}_status {prefix}_stream(",
        f"    const {prefix}_input *input,",
        f"    {prefix}_record_emitter emit_record, void *emit_context,",
        "    uint16_t *output_count);",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
        f"#endif /* {macro}_H */",
        "",
    ])
    return "\n".join(lines)


def _rows(values: Iterable[str], *, indent: str = "    ") -> list[str]:
    return [indent + item + "," for item in values]


def _source(program: DrawVMProgram, header_name: str) -> str:
    model = program.model
    prefix, macro = model.prefix, model.macro_prefix
    constants = program.constants or (0,)
    masks = program.class_masks or ((0,) * model.class_bit_bytes,)
    condition_ids = program.condition_ids or (0,)
    lines = [
        "/* Generated from SpriteDrawPlanIR. Do not edit. */",
        "/* Compact table program; no handwritten gameplay semantics. */",
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
        "#ifdef __SDCC",
        f"typedef char {prefix}_assert_object_view_size[",
        f"    (sizeof({prefix}_object_view) ==",
        f"        {macro}_OBJECT_VIEW_BYTES) ? 1 : -1];",
        "#endif",
        "",
    ]
    for name, value in _OPCODE.items():
        lines.append(f"#define {macro}_OP_{name} {value}u")
    lines.extend([
        f"#define {macro}_LOOP_OBJECTS 0u",
        f"#define {macro}_LOOP_TRANSIENTS 1u",
        f"#define {macro}_NODE_COUNT {len(program.nodes)}u",
        f"#define {macro}_ACTION_COUNT {len(program.actions)}u",
        f"#define {macro}_LOOP_COUNT {len(program.loops)}u",
        "",
        f"typedef struct {prefix}_node {{",
        "    uint8_t op, a, b, c;",
        f"}} {prefix}_node;",
        f"typedef char {prefix}_assert_node_size[",
        f"    (sizeof({prefix}_node) == {VM_NODE_BYTES}) ? 1 : -1];",
        "",
        f"typedef struct {prefix}_condition_pack {{",
        "    uint8_t first, count;",
        f"}} {prefix}_condition_pack;",
        f"typedef char {prefix}_assert_condition_pack_size[",
        f"    (sizeof({prefix}_condition_pack) == {VM_CONDITION_PACK_BYTES}) ? 1 : -1];",
        "",
        f"typedef struct {prefix}_action {{",
        "    uint8_t condition_pack, descriptor, palette;",
        "    uint8_t resource_type, anchor_x, anchor_y;",
        f"}} {prefix}_action;",
        f"typedef char {prefix}_assert_action_size[",
        f"    (sizeof({prefix}_action) == {VM_ACTION_BYTES}) ? 1 : -1];",
        "",
        f"typedef struct {prefix}_loop {{",
        "    uint8_t kind, first_action, action_count;",
        f"}} {prefix}_loop;",
        f"typedef char {prefix}_assert_loop_size[",
        f"    (sizeof({prefix}_loop) == {VM_LOOP_BYTES}) ? 1 : -1];",
        "",
        f"static const int32_t {prefix}_constants[] = {{",
    ])
    lines.extend(_rows(f"{value}L" for value in constants))
    lines.extend([
        "};",
        "",
        f"static const uint8_t {prefix}_class_masks[][",
        f"        {macro}_CLASS_BIT_BYTES] = {{",
    ])
    lines.extend(_rows(
        "{ " + ", ".join(f"0x{value:02X}u" for value in row) + " }"
        for row in masks))
    lines.extend([
        "};",
        "",
        f"static const {prefix}_node {prefix}_nodes[] = {{",
    ])
    lines.extend(_rows(
        f"{{ {macro}_OP_{node.op}, {node.a}u, {node.b}u, {node.c}u }}"
        for node in program.nodes))
    lines.extend([
        "};",
        "",
        f"static const uint8_t {prefix}_condition_ids[] = {{",
    ])
    lines.extend(_rows(str(value) + "u" for value in condition_ids))
    lines.extend([
        "};",
        "",
        f"static const {prefix}_condition_pack {prefix}_condition_packs[] = {{",
    ])
    lines.extend(_rows(
        f"{{ {first}u, {count}u }}"
        for first, count in program.condition_packs))
    lines.extend([
        "};",
        "",
        f"static const {prefix}_action {prefix}_actions[] = {{",
    ])
    lines.extend(_rows(
        "{ %du, %du, %du, %du, %du, %du }" % (
            action.condition_pack, action.descriptor, action.palette,
            action.resource_type, action.anchor_x, action.anchor_y)
        for action in program.actions))
    lines.extend([
        "};",
        "",
        f"static const {prefix}_loop {prefix}_loops[] = {{",
    ])
    lines.extend(_rows(
        f"{{ {macro}_LOOP_"
        f"{'OBJECTS' if loop.kind == 'objects' else 'TRANSIENTS'}, "
        f"{loop.first_action}u, {loop.action_count}u }}"
        for loop in program.loops))
    lines.extend([
        "};",
        "",
        f"typedef struct {prefix}_eval_context {{",
        f"    const {prefix}_input *input;",
        f"    const {prefix}_object_view *object;",
        f"    const {prefix}_transient_view *transient;",
        f"}} {prefix}_eval_context;",
        "",
        f"static int32_t {prefix}_object_field(",
        f"        const {prefix}_object_view *object, uint8_t field)",
        "{",
        "    switch (field) {",
    ])
    for index, field in enumerate(model.fields):
        lines.append(
            f"    case {index}u: return (int32_t)object->field_"
            f"{_identifier(field.name)};")
    lines.extend([
        "    default: return 0L;",
        "    }",
        "}",
        "",
        f"static int32_t {prefix}_transient_field(",
        f"        const {prefix}_transient_view *transient, uint8_t field)",
        "{",
        "    switch (field) {",
    ])
    for index, (name, _c_type) in enumerate(_TRANSIENT_FIELDS):
        lines.append(
            f"    case {index}u: return (int32_t)transient->{name};")
    lines.extend([
        "    default: return 0L;",
        "    }",
        "}",
        "",
        f"static int32_t {prefix}_eval(",
        f"        const {prefix}_eval_context *context, uint8_t node_id)",
        "{",
        f"    const {prefix}_node *node = &{prefix}_nodes[node_id];",
        "    int32_t left, right;",
        "    uint8_t index;",
        "    switch (node->op) {",
        f"    case {macro}_OP_CONST:",
        f"        return {prefix}_constants[node->a];",
        f"    case {macro}_OP_OBJECT_FIELD:",
        f"        return {prefix}_object_field(context->object, node->a);",
        f"    case {macro}_OP_TRANSIENT_FIELD:",
        f"        return {prefix}_transient_field(context->transient, node->a);",
        f"    case {macro}_OP_CLASS_ANY:",
        f"        for (index = 0u; index < {macro}_CLASS_BIT_BYTES; ++index) {{",
        "            if ((context->object->class_bits[index] &",
        f"                    {prefix}_class_masks[node->a][index]) != 0u) {{",
        "                return 1L;",
        "            }",
        "        }",
        "        return 0L;",
        f"    case {macro}_OP_NOT:",
        f"        return {prefix}_eval(context, node->a) == 0L;",
        f"    case {macro}_OP_AND:",
        f"        left = {prefix}_eval(context, node->a);",
        f"        return left != 0L ? ({prefix}_eval(context, node->b) != 0L) : 0L;",
        f"    case {macro}_OP_ADD:",
        f"        left = {prefix}_eval(context, node->a);",
        f"        right = {prefix}_eval(context, node->b);",
        "        return left + right;",
        f"    case {macro}_OP_EQUAL:",
        f"        left = {prefix}_eval(context, node->a);",
        f"        right = {prefix}_eval(context, node->b);",
        "        return left == right;",
        f"    case {macro}_OP_NOT_EQUAL:",
        f"        left = {prefix}_eval(context, node->a);",
        f"        right = {prefix}_eval(context, node->b);",
        "        return left != right;",
        f"    case {macro}_OP_SELECT:",
        f"        return {prefix}_eval(context, node->a) != 0L ?",
        f"            {prefix}_eval(context, node->b) :",
        f"            {prefix}_eval(context, node->c);",
        f"    case {macro}_OP_RESOURCE_TYPE:",
        "        return (int32_t)context->input->resolve_resource_type(",
        "            context->input->resource_context,",
        f"            (uint16_t){prefix}_eval(context, node->a));",
        "    default:",
        "        return 0L;",
        "    }",
        "}",
        "",
        f"static uint8_t {prefix}_conditions(",
        f"        const {prefix}_eval_context *context, uint8_t pack_id)",
        "{",
        f"    const {prefix}_condition_pack *pack =",
        f"        &{prefix}_condition_packs[pack_id];",
        "    uint8_t index;",
        "    for (index = 0u; index < pack->count; ++index) {",
        f"        if ({prefix}_eval(context,",
        f"                {prefix}_condition_ids[pack->first + index]) == 0L) {{",
        "            return 0u;",
        "        }",
        "    }",
        "    return 1u;",
        "}",
        "",
        f"static uint8_t {prefix}_input_valid(const {prefix}_input *input)",
        "{",
        "    return (uint8_t)(input != NULL &&",
        "            input->resolve_resource_type != NULL &&",
        "            input->resolve_bank_key != NULL &&",
        "            (input->object_count == 0u ||",
        "                input->load_object != NULL || input->objects != NULL) &&",
        "            (input->transient_count == 0u || input->transients != NULL));",
        "}",
        "",
        f"static {prefix}_status {prefix}_walk(",
        f"        const {prefix}_input *input, uint8_t emitting,",
        f"        {prefix}_record_emitter emit_record, void *emit_context,",
        "        uint16_t *count_out)",
        "{",
        f"    {prefix}_eval_context context;",
        f"    {prefix}_object_view loaded_object;",
        "    uint32_t needed = 0UL;",
        "    uint16_t emitted = 0u;",
        "    uint16_t item_index, item_count;",
        "    uint8_t loop_index, action_offset;",
        "    context.input = input;",
        "    context.object = NULL;",
        "    context.transient = NULL;",
        f"    for (loop_index = 0u; loop_index < {macro}_LOOP_COUNT; ++loop_index) {{",
        f"        const {prefix}_loop *loop = &{prefix}_loops[loop_index];",
        f"        item_count = loop->kind == {macro}_LOOP_OBJECTS ?",
        "            input->object_count : input->transient_count;",
        "        for (item_index = 0u; item_index < item_count; ++item_index) {",
        f"            if (loop->kind == {macro}_LOOP_OBJECTS) {{",
        "                if (input->load_object != NULL) {",
        "                    if (input->load_object(input->object_context,",
        "                            item_index, &loaded_object) == 0u) {",
        "                        *count_out = emitted;",
        f"                        return {macro}_OBJECT_LOADER;",
        "                    }",
        "                    context.object = &loaded_object;",
        "                } else {",
        "                    context.object = &input->objects[item_index];",
        "                }",
        "                context.transient = NULL;",
        "            } else {",
        "                context.object = NULL;",
        "                context.transient = &input->transients[item_index];",
        "            }",
        "            for (action_offset = 0u;",
        "                    action_offset < loop->action_count; ++action_offset) {",
        f"                const {prefix}_action *action = &{prefix}_actions[",
        "                    loop->first_action + action_offset];",
        f"                if ({prefix}_conditions(&context,",
        "                        action->condition_pack) != 0u) {",
        f"                    const int32_t descriptor = {prefix}_eval(",
        "                        &context, action->descriptor);",
        f"                    const int32_t palette = {prefix}_eval(",
        "                        &context, action->palette);",
        f"                    const int32_t anchor_x = {prefix}_eval(",
        "                        &context, action->anchor_x);",
        f"                    const int32_t anchor_y = {prefix}_eval(",
        "                        &context, action->anchor_y);",
        "                    if (emitting == 0u) {",
        "                        if (descriptor < 0L || descriptor > 65535L ||",
        "                                palette < 0L || palette > 65535L ||",
        "                                anchor_x < -32768L || anchor_x > 32767L ||",
        "                                anchor_y < -32768L || anchor_y > 32767L) {",
        f"                            return {macro}_RANGE;",
        "                        }",
        "                        ++needed;",
        "                        if (needed > 65535UL) {",
        f"                            return {macro}_CAPACITY;",
        "                        }",
        "                    } else {",
        f"                        {prefix}_record record;",
        "                        const uint16_t resource_type = (uint16_t)",
        f"                            {prefix}_eval(&context, action->resource_type);",
        "                        record.bank_key = input->resolve_bank_key(",
        "                            input->bank_context, (uint16_t)palette,",
        "                            resource_type);",
        "                        record.descriptor = (uint16_t)descriptor;",
        "                        record.anchor_x = (int16_t)anchor_x;",
        "                        record.anchor_y = (int16_t)anchor_y;",
        "                        if (emit_record(emit_context, &record) == 0u) {",
        "                            *count_out = emitted;",
        f"                            return {macro}_EMITTER;",
        "                        }",
        "                        ++emitted;",
        "                    }",
        "                }",
        "            }",
        "        }",
        "    }",
        "    *count_out = emitting != 0u ? emitted : (uint16_t)needed;",
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
        f"    {prefix}_buffer_sink sink;",
        f"    {prefix}_status status;",
        "    uint16_t needed, emitted;",
        f"    if (output_count == NULL || !{prefix}_input_valid(input)) {{",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        f"    status = {prefix}_walk(input, 0u, NULL, NULL, &needed);",
        f"    if (status != {macro}_OK) return status;",
        f"    if (needed > capacity) return {macro}_CAPACITY;",
        f"    if (needed != 0u && output == NULL) return {macro}_INVALID_INPUT;",
        "    sink.next = output;",
        f"    status = {prefix}_walk(input, 1u, {prefix}_emit_to_buffer,",
        "        &sink, &emitted);",
        f"    if (status != {macro}_OK) return status;",
        f"    if (emitted != needed) return {macro}_EMITTER;",
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
        "    uint16_t needed, emitted = 0u;",
        f"    if (output_count == NULL || !{prefix}_input_valid(input)) {{",
        f"        return {macro}_INVALID_INPUT;",
        "    }",
        f"    status = {prefix}_walk(input, 0u, NULL, NULL, &needed);",
        f"    if (status != {macro}_OK) return status;",
        f"    if (needed != 0u && emit_record == NULL) return {macro}_INVALID_INPUT;",
        "    if (needed != 0u) {",
        f"        status = {prefix}_walk(input, 1u, emit_record, emit_context,",
        "            &emitted);",
        f"        if (status == {macro}_EMITTER ||",
        f"                status == {macro}_OBJECT_LOADER) {{",
        "            *output_count = emitted;",
        "            return status;",
        "        }",
        f"        if (status != {macro}_OK) return status;",
        f"        if (emitted != needed) return {macro}_EMITTER;",
        "    }",
        "    *output_count = emitted;",
        f"    return {macro}_OK;",
        "}",
        "",
    ])
    return "\n".join(lines)


def _manifest(
        program: DrawVMProgram, header_name: str, source_name: str,
        header: str, source: str,
        ) -> str:
    model = program.model
    value = {
        "format": VM_BACKEND_FORMAT,
        "plan": {
            "format": model.plan.format,
            "symbol": model.plan.symbol,
            "source_path": model.plan.source_path,
            "source_sha256": model.plan.source_sha256,
            "method_ast_sha256": model.plan.method_ast_sha256,
            "sink_order_sha256": model.plan.sink_order_sha256,
            "semantic_sha256": model.plan.semantic_sha256,
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
                    {"concrete_class": name, "isinstance_tags": list(tags)}
                    for name, tags in model.class_memberships
                ],
            },
            "object_view": {
                "layout_owner": "target-layout-adapter",
                "fields": [item.as_dict() for item in model.fields],
                "input_shape": "provider-or-contiguous-normalized-array",
                "field_storage_bytes_without_target_padding": (
                    model.class_bit_bytes + sum({
                        "uint8_t": 1, "uint16_t": 2,
                        "int16_t": 2, "int32_t": 4,
                    }[item.c_type] for item in model.fields)),
                "exact_target_size_bytes": VM_OBJECT_VIEW_BYTES,
                "working_view_count": 1,
                "working_view_bytes": VM_OBJECT_VIEW_BYTES,
                "full_pool_materialization_required": False,
                "provider": {
                    "callback": (
                        "uint8_t (*)(void *context, uint16_t object_index, "
                        f"{model.prefix}_object_view *object_out)"),
                    "selection": (
                        "load_object when non-null, otherwise contiguous "
                        "objects fallback"),
                    "successful_calls_per_preflight_pass": "object_count",
                    "successful_calls_per_emission_pass": "object_count",
                    "successful_calls_per_produce_or_stream": (
                        "2 * object_count"),
                    "calls_per_item_per_pass": 1,
                    "failure_attempts_for_index_i_during_preflight": "i + 1",
                    "failure_before_first_output": True,
                    "resolver_or_emitter_calls_before_preflight_failure": 0,
                    "abi_precondition": (
                        "deterministic and stable for both passes; does not "
                        "mutate resolver or emitter behavior"),
                },
                "single_working_view_abi_certified": True,
                "live_materialization_certified": False,
                "live_target_layout_mapping_certified": False,
                "live_adapter_requirement": (
                    "implement the source-derived target object mapping "
                    "behind load_object; never materialize the whole pool"),
            },
            "transient_tuple_view": {
                "fields": [
                    {"name": name, "c_type": c_type}
                    for name, c_type in _TRANSIENT_FIELDS
                ],
            },
            "resolvers": {
                "resource_type": {
                    "operation": "palette-to-resource-type",
                    "callback": (
                        "uint16_t (*)(void *context, uint16_t palette)"),
                    "abi_precondition": "total, deterministic, nonmutating",
                },
                "bank_key": {
                    "operation": "palette-resource-type-to-bank-key",
                    "callback": (
                        "uint16_t (*)(void *context, uint16_t palette, "
                        "uint16_t resource_type)"),
                    "abi_precondition": "total, deterministic, nonmutating",
                },
                "evaluation_order": "left-to-right-before-bank-key",
            },
            "output_record": {
                "size": RECORD_SIZE,
                "fields": [
                    {"name": "bank_key", "offset": 0, "c_type": "uint16_t"},
                    {"name": "descriptor", "offset": 2, "c_type": "uint16_t"},
                    {"name": "anchor_x", "offset": 4, "c_type": "int16_t"},
                    {"name": "anchor_y", "offset": 6, "c_type": "int16_t"},
                ],
            },
            "failure_atomicity": {
                "preflight": (
                    "count-and-range with one object-loader call per object; "
                    "without resolvers, emitters or output writes"),
                "preflight_expression_callback_node_count": 0,
                "preflight_object_loader_calls": "object_count-on-success",
                "capacity_failure_atomic": True,
                "object_loader_failure_during_preflight_atomic": True,
                "produce_non_ok_output_buffer_unchanged": True,
            },
            "streaming": {
                "function": f"{model.prefix}_stream",
                "record_array_required": False,
                "order": "strict-active-Python-loop-order",
                "preflight_before_first_emission": True,
                "emitter_failure_reports_accepted_prefix": True,
                "emitter_precondition": (
                    "does not mutate input views or resolver behavior"),
            },
        },
        "vm": {
            "encoding": "fixed-4-byte-dag-nodes-u8-identifiers",
            "opcodes": [
                {"name": name, "opcode": index}
                for index, name in enumerate(_OPCODE_ORDER)
            ],
            "limits": {
                "max_each_u8_inventory": VM_ID_LIMIT,
                "fail_closed": True,
            },
            "counts": {
                "constants": len(program.constants),
                "class_masks": len(program.class_masks),
                "nodes": len(program.nodes),
                "condition_ids": len(program.condition_ids),
                "condition_packs": len(program.condition_packs),
                "actions": len(program.actions),
                "loops": len(program.loops),
                "callback_reachable_nodes": len(program.callback_node_ids),
            },
            "logical_table_bytes": {
                "constants": len(program.constants) * 4,
                "class_masks": (
                    len(program.class_masks) * model.class_bit_bytes),
                "nodes": len(program.nodes) * VM_NODE_BYTES,
                "condition_ids": len(program.condition_ids),
                "condition_packs": (
                    len(program.condition_packs) * VM_CONDITION_PACK_BYTES),
                "actions": len(program.actions) * VM_ACTION_BYTES,
                "loops": len(program.loops) * VM_LOOP_BYTES,
                "total": program.table_payload_bytes,
            },
            "max_recursive_eval_depth": program.max_eval_depth,
            "integer_semantics": {
                "evaluation_type": "int32_t",
                "all_additions_interval_proved_no_signed_overflow": True,
            },
            "short_circuit": ["AND", "SELECT", "condition-pack"],
            "condition_pack_deduplication": True,
            "class_mask_deduplication": True,
        },
        "lowering": {
            "loop_order": [
                {
                    "loop_id": source.loop_id,
                    "kind": compact.kind,
                    "first_action": compact.first_action,
                    "action_count": compact.action_count,
                    "action_ordinals": list(source.action_ordinals),
                }
                for source, compact in zip(model.loops, program.loops)
            ],
            "actions": [
                {
                    "ordinal": action.ordinal,
                    "sink_ordinal": action.sink_ordinal,
                    "expansion_ordinal": action.expansion_ordinal,
                    "condition_pack": compact.condition_pack,
                }
                for action, compact in zip(model.plan.actions, program.actions)
            ],
        },
        "verification_contract": {
            "host_semantics": {
                "required": True,
                "method": (
                    "compile-run and compare entire record stream plus all "
                    "34 action coverage against SpriteDrawPlanIR oracle"),
            },
            "pinned_sdcc": {
                "required_before_live_use": True,
                "scope": "generated source code/data section measurement",
            },
            "logical_recursion_depth_is_not_stack_byte_certificate": True,
            "pinned_sdcc_stack_bytes": None,
            "live_z80_tstates": None,
            "live_target_performance_and_size_certified": False,
            "certification_blockers": [
                "source-derived target object fields are not mapped into the provider",
                "pinned SDCC stack-byte bound is not proved",
                "live FT812 integration timing is not proved",
            ],
        },
        "artifacts": {
            "header": {
                "name": header_name,
                "sha256": _sha256_text(header),
                "utf8_bytes": len(header.encode("utf-8")),
            },
            "source": {
                "name": source_name,
                "sha256": _sha256_text(source),
                "utf8_bytes": len(source.encode("utf-8")),
            },
        },
    }
    return _json_text(value)


def emit_draw_vm_backend(
        plan: SpriteDrawPlanIR, *, prefix: str = "rtype_python_draw_vm",
        stem: str | None = None, source_text: str | None = None,
        ) -> DrawCArtifacts:
    """Return deterministic compact C, header and manifest artifacts."""
    program = build_draw_vm_program(
        plan, prefix=prefix, source_text=source_text)
    artifact_stem = stem or prefix
    if _identifier(artifact_stem) != artifact_stem:
        raise DrawVMBackendError(
            "PZDVM015", f"artifact stem is not normalized: {artifact_stem!r}")
    header_name = artifact_stem + ".h"
    source_name = artifact_stem + ".c"
    manifest_name = artifact_stem + ".json"
    header = _header(program, header_name)
    source = _source(program, header_name)
    manifest = _manifest(
        program, header_name, source_name, header, source)
    return DrawCArtifacts(
        header_name=header_name,
        source_name=source_name,
        manifest_name=manifest_name,
        header=header,
        source=source,
        manifest=manifest,
    )


def write_draw_vm_backend(
        plan: SpriteDrawPlanIR, output_dir: Path, *,
        prefix: str = "rtype_python_draw_vm", stem: str | None = None,
        source_text: str | None = None,
        ) -> DrawCArtifacts:
    """Write compact artifacts with deterministic bytes."""
    artifacts = emit_draw_vm_backend(
        plan, prefix=prefix, stem=stem, source_text=source_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
            (artifacts.header_name, artifacts.header),
            (artifacts.source_name, artifacts.source),
            (artifacts.manifest_name, artifacts.manifest)):
        (output_dir / name).write_text(
            value, encoding="utf-8", newline="\n")
    return artifacts
