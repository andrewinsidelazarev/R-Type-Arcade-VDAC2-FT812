"""Source-derived compact render order for the active Python enemy list.

``M72EnemyWorld.draw`` consumes ``self.enemies`` in list order.  A physical
Z80 object-pool scan is therefore not an equivalent lowering: allocation,
stable survivor filtering and same-record handler replacement can all make
list order differ from address order.  This module audits the complete list
mutation inventory already proved by :mod:`frame_record_bound`, derives the
checkpoint seed from the active Python AST, and emits a small target-neutral C
container keyed by normalized object-pool slot indices.

The generated container is deliberately generic.  It knows no enemy classes
or gameplay handlers.  Live object-field/class sidecars and target hooks are
separate adapters and remain fail-closed blockers in the manifest.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .frame_record_bound import (
    FrameRecordBoundError,
    _attribute_path,
    _ast_sha256,
    _class,
    _const_int,
    _method,
    _parse,
    _pool_facts,
    _top_level_literal,
)


RENDER_ORDER_BACKEND_FORMAT = "pyz80.render-order-backend.v1"
DEFAULT_PREFIX = "rtype_python_render_order"
NONE_SLOT = 0xFF

__all__ = [
    "RENDER_ORDER_BACKEND_FORMAT",
    "DEFAULT_PREFIX",
    "NONE_SLOT",
    "RenderOrderArtifacts",
    "RenderOrderBackendError",
    "RenderOrderModel",
    "build_render_order_model",
    "emit_render_order_backend",
    "write_render_order_backend",
]


class RenderOrderBackendError(ValueError):
    """An unsupported source shape which must stop code generation."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class RenderOrderModel:
    """All source-derived constants needed by the generic C container."""

    source_sha256: str
    launcher_sha256: str
    slot_count: int
    reserved_sentinel_count: int
    capacity: int
    slot_first: int
    slot_stop_exclusive: int
    slot_stride: int
    checkpoint_physical_slots: tuple[int, ...]
    checkpoint_slot_indices: tuple[int, ...]
    allocator_ast_sha256: str
    pending_append_ast_sha256: str
    checkpoint_seed_ast_sha256: str
    draw_loop_ast_sha256: str
    enemy_mutations: tuple[tuple[int, str, str], ...]
    semantic_sha256: str

    @property
    def keep_mask_bytes(self) -> int:
        return (self.slot_count + 7) // 8

    @property
    def state_bytes(self) -> int:
        # uint8 count + compact order + one uint8 position/membership cell per
        # physical pool slot.  All fields have byte alignment on the target.
        return 1 + self.capacity + self.slot_count


@dataclass(frozen=True)
class RenderOrderArtifacts:
    header_name: str
    source_name: str
    manifest_name: str
    header: str
    source: str
    manifest: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_text(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n"


def _identifier(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or result[0].isdigit():
        result = "_" + result
    return result


def _assignment_values(
        method: ast.FunctionDef, local_name: str,
        ) -> tuple[ast.AST, ...]:
    result: list[ast.AST] = []
    for node in ast.walk(method):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == local_name
               for target in targets):
            result.append(node.value)
    return tuple(result)


def _checkpoint_seed(
        tree: ast.Module,
        ) -> tuple[tuple[int, ...], str]:
    """Derive ``[uninitialized, *particles, *cycles]`` without class names."""
    init = _method(_class(tree, "M72EnemyWorld"), "__init__")
    seeds: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(init):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if (any(_attribute_path(target) == "self.enemies"
                for target in targets) and
                isinstance(node.value, ast.List) and node.value.elts and
                any(isinstance(item, ast.Starred)
                    for item in node.value.elts)):
            seeds.append(node)
    if len(seeds) != 1:
        raise RenderOrderBackendError(
            "PZRO002", "expected one starred self.enemies checkpoint seed, "
            f"got {len(seeds)}")
    seed = seeds[0]
    assert isinstance(seed.value, ast.List)
    physical: list[int] = []
    for item in seed.value.elts:
        if isinstance(item, ast.Name):
            object_slot_assignments = [
                node.value
                for node in ast.walk(init)
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and
                any(_attribute_path(target) == f"{item.id}.object_slot"
                    for target in (node.targets if isinstance(node, ast.Assign)
                                   else [node.target]))
            ]
            if len(object_slot_assignments) != 1:
                raise RenderOrderBackendError(
                    "PZRO003", f"checkpoint local {item.id!r} does not have "
                    "exactly one literal object_slot")
            physical.append(_const_int(
                object_slot_assignments[0],
                f"checkpoint {item.id}.object_slot"))
            continue
        if not (isinstance(item, ast.Starred) and
                isinstance(item.value, ast.Name)):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint seed entries must be one local or "
                "starred materialised record lists")
        local_name = item.value.id
        definitions = _assignment_values(init, local_name)
        if len(definitions) != 1 or not isinstance(definitions[0], ast.ListComp):
            raise RenderOrderBackendError(
                "PZRO004", f"checkpoint starred local {local_name!r} is not "
                "one list comprehension")
        comprehension = definitions[0]
        if len(comprehension.generators) != 1:
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint list comprehension is no longer a "
                "single reversed record stream")
        generator = comprehension.generators[0]
        if generator.ifs or generator.is_async or not isinstance(
                generator.target, ast.Name):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint record stream gained filtering or "
                "asynchronous iteration")
        iterator = generator.iter
        if not (isinstance(iterator, ast.Call) and
                isinstance(iterator.func, ast.Name) and
                iterator.func.id == "reversed" and
                len(iterator.args) == 1 and not iterator.keywords and
                isinstance(iterator.args[0], ast.Name)):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint record stream is not reversed(NAME)")
        element = comprehension.elt
        if not (isinstance(element, ast.Call) and len(element.args) == 1 and
                not element.keywords and isinstance(element.args[0], ast.Name) and
                element.args[0].id == generator.target.id and
                isinstance(element.func, ast.Attribute) and
                element.func.attr == "from_stage1_checkpoint"):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint records no longer pass unchanged to "
                "from_stage1_checkpoint")
        records = _top_level_literal(tree, iterator.args[0].id)
        if not isinstance(records, tuple):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint record source is not a finite tuple")
        try:
            slots = tuple(
                value[0] for value in records
                if (not isinstance(value[0], bool) and
                    isinstance(value[0], int)))
        except (IndexError, TypeError) as exc:
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint record lacks a literal first slot") from exc
        if len(slots) != len(records):
            raise RenderOrderBackendError(
                "PZRO004", "checkpoint record first slot is not an integer")
        physical.extend(reversed(slots))
    return tuple(physical), _ast_sha256(seed)


def _draw_loop_hash(tree: ast.Module) -> str:
    """Prove that the renderer's outer loop is the list itself, unsorted."""
    draw = _method(_class(tree, "M72EnemyWorld"), "draw")
    if not draw.body or not isinstance(draw.body[0], ast.For):
        raise RenderOrderBackendError(
            "PZRO010", "M72EnemyWorld.draw must start with its object loop")
    loop = draw.body[0]
    if (not isinstance(loop.target, ast.Name) or loop.target.id != "enemy" or
            _attribute_path(loop.iter) != "self.enemies" or loop.orelse):
        raise RenderOrderBackendError(
            "PZRO010", "M72EnemyWorld.draw no longer iterates self.enemies "
            "directly in Python list order")
    return _ast_sha256(loop)


def _normalize_slot(model_values: Mapping[str, int], slot: int) -> int:
    first = model_values["slot_first"]
    stop = model_values["slot_stop_exclusive"]
    stride = model_values["slot_stride"]
    if slot < first or slot >= stop or (slot - first) % stride:
        raise RenderOrderBackendError(
            "PZRO005", f"checkpoint physical slot 0x{slot:04X} is outside "
            "M72ObjectPool.SLOTS")
    return (slot - first) // stride


def build_render_order_model(
        project_root: Path | str, *, enemy_source_override: str | None = None,
        ) -> RenderOrderModel:
    """Audit active Python and return a deterministic generic order model."""
    root = Path(project_root).resolve()
    enemy_path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
    source = (enemy_source_override if enemy_source_override is not None
              else enemy_path.read_bytes().decode("utf-8"))
    launcher = (root / "run_python.cmd").read_bytes()
    try:
        launcher_text = launcher.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenderOrderBackendError(
            "PZRO006", "run_python.cmd is not UTF-8") from exc
    if "-m rtype_port.app" not in launcher_text:
        raise RenderOrderBackendError(
            "PZRO006", "run_python.cmd no longer launches rtype_port.app")
    try:
        tree = _parse(source, "Source/Python/rtype_port/enemies.py")
        pool = _pool_facts(tree)
    except FrameRecordBoundError as exc:
        raise RenderOrderBackendError(
            "PZRO001", "active list/pool audit rejected source: "
            f"{exc.code}: {exc.detail}") from exc
    if pool.slot_count > NONE_SLOT:
        raise RenderOrderBackendError(
            "PZRO007", f"slot count {pool.slot_count} cannot use compact uint8")
    if pool.allocatable_record_count > NONE_SLOT:
        raise RenderOrderBackendError(
            "PZRO007", "render-order capacity cannot use compact uint8")
    physical, checkpoint_hash = _checkpoint_seed(tree)
    draw_loop_hash = _draw_loop_hash(tree)
    pool_values = {
        "slot_first": pool.slot_first,
        "slot_stop_exclusive": pool.slot_stop_exclusive,
        "slot_stride": pool.slot_stride,
    }
    indices = tuple(_normalize_slot(pool_values, slot) for slot in physical)
    if len(indices) > pool.allocatable_record_count:
        raise RenderOrderBackendError(
            "PZRO008", "checkpoint seed exceeds allocatable pool capacity")
    if len(set(indices)) != len(indices):
        raise RenderOrderBackendError(
            "PZRO008", "checkpoint seed contains duplicate object slots")
    if any(index < pool.reserved_sentinel_count for index in indices):
        raise RenderOrderBackendError(
            "PZRO008", "checkpoint seed contains a reserved sentinel slot")
    semantic_payload = {
        "format": RENDER_ORDER_BACKEND_FORMAT,
        "source_sha256": _sha256_text(source),
        "pool": {
            "slot_count": pool.slot_count,
            "reserved_sentinel_count": pool.reserved_sentinel_count,
            "capacity": pool.allocatable_record_count,
            "slot_first": pool.slot_first,
            "slot_stop_exclusive": pool.slot_stop_exclusive,
            "slot_stride": pool.slot_stride,
            "allocator_ast_sha256": pool.allocator_ast_sha256,
            "pending_append_ast_sha256": pool.pending_append_ast_sha256,
        },
        "checkpoint": {
            "physical_slots": physical,
            "slot_indices": indices,
            "seed_ast_sha256": checkpoint_hash,
        },
        "enemy_mutations": pool.enemy_mutations,
        "draw_loop_ast_sha256": draw_loop_hash,
    }
    semantic_sha256 = _sha256_text(json.dumps(
        semantic_payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")))
    return RenderOrderModel(
        source_sha256=_sha256_text(source),
        launcher_sha256=_sha256_bytes(launcher),
        slot_count=pool.slot_count,
        reserved_sentinel_count=pool.reserved_sentinel_count,
        capacity=pool.allocatable_record_count,
        slot_first=pool.slot_first,
        slot_stop_exclusive=pool.slot_stop_exclusive,
        slot_stride=pool.slot_stride,
        checkpoint_physical_slots=physical,
        checkpoint_slot_indices=indices,
        allocator_ast_sha256=pool.allocator_ast_sha256,
        pending_append_ast_sha256=pool.pending_append_ast_sha256,
        checkpoint_seed_ast_sha256=checkpoint_hash,
        draw_loop_ast_sha256=draw_loop_hash,
        enemy_mutations=pool.enemy_mutations,
        semantic_sha256=semantic_sha256,
    )


def _macro(prefix: str) -> str:
    return prefix.upper()


def _header(model: RenderOrderModel, prefix: str, header_name: str) -> str:
    macro = _macro(prefix)
    guard = _identifier(header_name.upper().replace(".", "_"))
    return f"""/* Generated from active Python AST.  Do not hand-edit. */
#ifndef {guard}
#define {guard}

#include <stdint.h>

#ifdef __cplusplus
extern "C" {{
#endif

#define {macro}_SLOT_COUNT {model.slot_count}u
#define {macro}_RESERVED_SENTINELS {model.reserved_sentinel_count}u
#define {macro}_CAPACITY {model.capacity}u
#define {macro}_NONE 0xFFu
#define {macro}_KEEP_MASK_BYTES {model.keep_mask_bytes}u
#define {macro}_CHECKPOINT_COUNT {len(model.checkpoint_slot_indices)}u
#define {macro}_STATE_BYTES {model.state_bytes}u

typedef enum {{
    {macro}_OK = 0,
    {macro}_NULL = 1,
    {macro}_INVALID_SLOT = 2,
    {macro}_DUPLICATE_SLOT = 3,
    {macro}_CAPACITY_EXCEEDED = 4,
    {macro}_NOT_MEMBER = 5
}} {prefix}_status;

typedef struct {{
    uint8_t count;
    uint8_t order[{macro}_CAPACITY];
    /* 0xFF means absent; otherwise this is the direct order position. */
    uint8_t position[{macro}_SLOT_COUNT];
}} {prefix}_state;

void {prefix}_reset({prefix}_state *state);
{prefix}_status {prefix}_seed(
    {prefix}_state *state, const uint8_t *slots, uint8_t count);
{prefix}_status {prefix}_seed_checkpoint({prefix}_state *state);
{prefix}_status {prefix}_append({prefix}_state *state, uint8_t slot);
{prefix}_status {prefix}_extend(
    {prefix}_state *state, const uint8_t *slots, uint8_t count);
{prefix}_status {prefix}_remove({prefix}_state *state, uint8_t slot);
{prefix}_status {prefix}_filter(
    {prefix}_state *state,
    const uint8_t keep_mask[{macro}_KEEP_MASK_BYTES]);
{prefix}_status {prefix}_replace_same_slot(
    {prefix}_state *state, uint8_t slot);

/* O(1) accessors for the compact draw-VM object loader. */
uint8_t {prefix}_slot_at(
    const {prefix}_state *state, uint8_t order_position);
uint8_t {prefix}_position_of(
    const {prefix}_state *state, uint8_t slot);
uint8_t {prefix}_contains(
    const {prefix}_state *state, uint8_t slot);

#ifdef __cplusplus
}}
#endif

#endif
"""


def _source(model: RenderOrderModel, prefix: str, header_name: str) -> str:
    macro = _macro(prefix)
    seed = ", ".join(f"{value}u" for value in model.checkpoint_slot_indices)
    return f"""/* Generated from active Python AST.  Do not hand-edit. */
#include "{header_name}"

static const uint8_t {prefix}_checkpoint_slots[
        {macro}_CHECKPOINT_COUNT] = {{ {seed} }};

static uint8_t {prefix}_valid_slot(uint8_t slot)
{{
    return (uint8_t)(slot >= {macro}_RESERVED_SENTINELS &&
                     slot < {macro}_SLOT_COUNT);
}}

static uint8_t {prefix}_kept(const uint8_t *mask, uint8_t slot)
{{
    return (uint8_t)((mask[slot >> 3] >> (slot & 7u)) & 1u);
}}

void {prefix}_reset({prefix}_state *state)
{{
    uint8_t index;
    if (state == 0) return;
    state->count = 0u;
    for (index = 0u; index < {macro}_CAPACITY; ++index)
        state->order[index] = {macro}_NONE;
    for (index = 0u; index < {macro}_SLOT_COUNT; ++index)
        state->position[index] = {macro}_NONE;
}}

{prefix}_status {prefix}_seed(
        {prefix}_state *state, const uint8_t *slots, uint8_t count)
{{
    uint8_t index;
    uint8_t other;
    uint8_t slot;
    if (state == 0 || (count != 0u && slots == 0)) return {macro}_NULL;
    if (count > {macro}_CAPACITY) return {macro}_CAPACITY_EXCEEDED;
    for (index = 0u; index < count; ++index) {{
        slot = slots[index];
        if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
        for (other = 0u; other < index; ++other)
            if (slots[other] == slot) return {macro}_DUPLICATE_SLOT;
    }}
    {prefix}_reset(state);
    for (index = 0u; index < count; ++index) {{
        slot = slots[index];
        state->order[index] = slot;
        state->position[slot] = index;
    }}
    state->count = count;
    return {macro}_OK;
}}

{prefix}_status {prefix}_seed_checkpoint({prefix}_state *state)
{{
    return {prefix}_seed(state, {prefix}_checkpoint_slots,
                         {macro}_CHECKPOINT_COUNT);
}}

{prefix}_status {prefix}_append({prefix}_state *state, uint8_t slot)
{{
    uint8_t position;
    if (state == 0) return {macro}_NULL;
    if (state->count >= {macro}_CAPACITY)
        return {macro}_CAPACITY_EXCEEDED;
    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
    if (state->position[slot] != {macro}_NONE)
        return {macro}_DUPLICATE_SLOT;
    position = state->count;
    state->order[position] = slot;
    state->position[slot] = position;
    state->count = (uint8_t)(position + 1u);
    return {macro}_OK;
}}

{prefix}_status {prefix}_extend(
        {prefix}_state *state, const uint8_t *slots, uint8_t count)
{{
    uint8_t index;
    uint8_t other;
    uint8_t slot;
    uint8_t position;
    if (state == 0 || (count != 0u && slots == 0)) return {macro}_NULL;
    if ((uint16_t)state->count + (uint16_t)count > {macro}_CAPACITY)
        return {macro}_CAPACITY_EXCEEDED;
    for (index = 0u; index < count; ++index) {{
        slot = slots[index];
        if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
        if (state->position[slot] != {macro}_NONE)
            return {macro}_DUPLICATE_SLOT;
        for (other = 0u; other < index; ++other)
            if (slots[other] == slot) return {macro}_DUPLICATE_SLOT;
    }}
    position = state->count;
    for (index = 0u; index < count; ++index) {{
        slot = slots[index];
        state->order[position] = slot;
        state->position[slot] = position;
        ++position;
    }}
    state->count = position;
    return {macro}_OK;
}}

{prefix}_status {prefix}_remove({prefix}_state *state, uint8_t slot)
{{
    uint8_t position;
    uint8_t next;
    if (state == 0) return {macro}_NULL;
    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
    position = state->position[slot];
    if (position == {macro}_NONE) return {macro}_NOT_MEMBER;
    for (; (uint8_t)(position + 1u) < state->count; ++position) {{
        next = state->order[(uint8_t)(position + 1u)];
        state->order[position] = next;
        state->position[next] = position;
    }}
    --state->count;
    state->order[state->count] = {macro}_NONE;
    state->position[slot] = {macro}_NONE;
    return {macro}_OK;
}}

{prefix}_status {prefix}_filter(
        {prefix}_state *state,
        const uint8_t keep_mask[{macro}_KEEP_MASK_BYTES])
{{
    uint8_t slot;
    uint8_t read_position;
    uint8_t write_position = 0u;
    uint8_t old_count;
    if (state == 0 || keep_mask == 0) return {macro}_NULL;
    for (slot = 0u; slot < {macro}_SLOT_COUNT; ++slot) {{
        if (!{prefix}_kept(keep_mask, slot)) continue;
        if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
        if (state->position[slot] == {macro}_NONE)
            return {macro}_NOT_MEMBER;
    }}
    old_count = state->count;
    for (read_position = 0u; read_position < old_count; ++read_position) {{
        slot = state->order[read_position];
        if ({prefix}_kept(keep_mask, slot)) {{
            state->order[write_position] = slot;
            state->position[slot] = write_position;
            ++write_position;
        }} else {{
            state->position[slot] = {macro}_NONE;
        }}
    }}
    for (read_position = write_position; read_position < old_count;
            ++read_position)
        state->order[read_position] = {macro}_NONE;
    state->count = write_position;
    return {macro}_OK;
}}

{prefix}_status {prefix}_replace_same_slot(
        {prefix}_state *state, uint8_t slot)
{{
    if (state == 0) return {macro}_NULL;
    if (!{prefix}_valid_slot(slot)) return {macro}_INVALID_SLOT;
    if (state->position[slot] == {macro}_NONE) return {macro}_NOT_MEMBER;
    /* Object identity/class sidecars change; list position deliberately does not. */
    return {macro}_OK;
}}

uint8_t {prefix}_slot_at(
        const {prefix}_state *state, uint8_t order_position)
{{
    if (state == 0 || order_position >= state->count) return {macro}_NONE;
    return state->order[order_position];
}}

uint8_t {prefix}_position_of(
        const {prefix}_state *state, uint8_t slot)
{{
    if (state == 0 || !{prefix}_valid_slot(slot)) return {macro}_NONE;
    return state->position[slot];
}}

uint8_t {prefix}_contains(
        const {prefix}_state *state, uint8_t slot)
{{
    return (uint8_t)({prefix}_position_of(state, slot) != {macro}_NONE);
}}
"""


def _manifest(
        model: RenderOrderModel, prefix: str, header_name: str,
        source_name: str, header: str, source: str,
        ) -> str:
    mutation_counts = {
        kind: sum(item[1] == kind for item in model.enemy_mutations)
        for kind in sorted({item[1] for item in model.enemy_mutations})
    }
    value: dict[str, object] = {
        "format": RENDER_ORDER_BACKEND_FORMAT,
        "status": "TARGET_NEUTRAL_GENERATED_LIVE_BLOCKED",
        "live": False,
        "semantic_sha256": model.semantic_sha256,
        "active_source": {
            "launcher": "run_python.cmd",
            "launcher_sha256": model.launcher_sha256,
            "module": "Source/Python/rtype_port/enemies.py",
            "module_sha256": model.source_sha256,
            "entrypoint": "rtype_port.app",
        },
        "source_derived_pool": {
            "slot_count": model.slot_count,
            "reserved_sentinel_count": model.reserved_sentinel_count,
            "allocatable_capacity": model.capacity,
            "physical_first": model.slot_first,
            "physical_stop_exclusive": model.slot_stop_exclusive,
            "physical_stride": model.slot_stride,
            "normalization": "(physical_slot - physical_first) / physical_stride",
            "allocator_ast_sha256": model.allocator_ast_sha256,
            "pending_append_ast_sha256": model.pending_append_ast_sha256,
        },
        "checkpoint_seed": {
            "count": len(model.checkpoint_slot_indices),
            "physical_slots": list(model.checkpoint_physical_slots),
            "normalized_slot_indices": list(model.checkpoint_slot_indices),
            "preserves_python_list_order": True,
            "ast_sha256": model.checkpoint_seed_ast_sha256,
        },
        "draw_order": {
            "source_expression": "for enemy in self.enemies",
            "direct_python_list_order": True,
            "outer_loop_ast_sha256": model.draw_loop_ast_sha256,
        },
        "audited_mutation_inventory": {
            "count": len(model.enemy_mutations),
            "kind_counts": mutation_counts,
            "sites": [
                {"line": line, "kind": kind, "source": expression}
                for line, kind, expression in model.enemy_mutations
            ],
            "unexpected_mutation_policy": "generation fails closed",
        },
        "normalized_abi": {
            "state": {
                "target_bytes": model.state_bytes,
                "count_bytes": 1,
                "ordered_slot_index_bytes": model.capacity,
                "membership_position_bytes": model.slot_count,
                "none_value": NONE_SLOT,
                "full_object_copy_required": False,
            },
            "operations": {
                "checkpoint_seed": "source-derived order",
                "append": "preserves Python append order",
                "extend": "atomic and preserves iterable order",
                "filter": "stable survivor filter by membership mask",
                "remove": "stable single-slot removal",
                "replace_same_slot": "keeps the exact list position",
                "slot_at": "O(1) direct VM-loader lookup",
                "position_of": "O(1) membership/position lookup",
            },
            "failure_atomicity": {
                "seed": ["invalid slot", "duplicate slot", "capacity"],
                "extend": ["invalid slot", "duplicate slot", "capacity"],
                "filter": ["invalid slot", "non-member slot"],
                "append_remove_replace": "validate before mutation",
            },
        },
        "verification_contract": {
            "host_randomized_differential": {
                "required": True,
                "oracle": "Python list of normalized slot indices",
                "checks_after_every_operation": [
                    "entire list-order hash", "count", "slot_at",
                    "membership", "position",
                ],
            },
            "pinned_sdcc_size_status": (
                "Build/rtype_python_render_order_size_status.json"),
            "live_target_hooks_present": False,
            "live_blockers": [
                "object fields and class tags are not mapped to target sidecars",
                "pool allocation/release/replacement sites are not hooked",
                "draw VM loader is not connected to slot_at",
                "linked target size, stack bytes and tstates are not certified",
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
        "prefix": prefix,
    }
    return _json_text(value)


def emit_render_order_backend(
        project_root: Path | str, *, prefix: str = DEFAULT_PREFIX,
        stem: str | None = None, enemy_source_override: str | None = None,
        ) -> RenderOrderArtifacts:
    """Return deterministic C/header/manifest artifacts."""
    if _identifier(prefix) != prefix:
        raise RenderOrderBackendError(
            "PZRO009", f"C prefix is not normalized: {prefix!r}")
    artifact_stem = stem or prefix
    if _identifier(artifact_stem) != artifact_stem:
        raise RenderOrderBackendError(
            "PZRO009", f"artifact stem is not normalized: {artifact_stem!r}")
    model = build_render_order_model(
        project_root, enemy_source_override=enemy_source_override)
    header_name = artifact_stem + ".h"
    source_name = artifact_stem + ".c"
    manifest_name = artifact_stem + ".json"
    header = _header(model, prefix, header_name)
    source = _source(model, prefix, header_name)
    manifest = _manifest(
        model, prefix, header_name, source_name, header, source)
    return RenderOrderArtifacts(
        header_name=header_name,
        source_name=source_name,
        manifest_name=manifest_name,
        header=header,
        source=source,
        manifest=manifest,
    )


def write_render_order_backend(
        project_root: Path | str, output_dir: Path | str, *,
        prefix: str = DEFAULT_PREFIX, stem: str | None = None,
        enemy_source_override: str | None = None,
        ) -> RenderOrderArtifacts:
    """Write deterministic artifacts to ``output_dir``."""
    artifacts = emit_render_order_backend(
        project_root, prefix=prefix, stem=stem,
        enemy_source_override=enemy_source_override)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (
            (artifacts.header_name, artifacts.header),
            (artifacts.source_name, artifacts.source),
            (artifacts.manifest_name, artifacts.manifest)):
        (destination / name).write_text(
            value, encoding="utf-8", newline="\n")
    return artifacts
