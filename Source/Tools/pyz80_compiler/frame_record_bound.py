"""Fail-closed active-Python draw-record bound analysis.

The whole frame is deliberately *not* assigned the historical capacity 32.
This module derives the exact record-count equation from ``SpriteDrawPlanIR``
and derives all local structural bounds from the Python AST used by
``run_python.cmd``.  The streaming target adapter may drain any number of
fixed-size chunks without dropping records; a sound whole-frame upper bound
is still mandatory for the separate RAM_DL and timing certificate.

The companion reachability analyser joins the pool proof to the finite ROM
event DAG, one-shot spawn guards and transient state transitions.  The result
is a sound conservative whole-frame upper bound.  It need not be the exact
attainable maximum: RAM_DL sizing and worst-case timing require a proved upper
bound, not an attainability witness.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .draw_c_backend import DrawCBackendModel, build_draw_c_model
from .draw_plan import DrawExpr, SpriteDrawPlanIR, compile_active_enemy_draw_plan
from .frame_record_reachability import (
    FrameRecordReachabilityError,
    analyze_frame_record_reachability,
)


FRAME_RECORD_BOUND_FORMAT = "pyz80.frame-draw-record-bound.v2"
DEFAULT_STREAM_CHUNK_CAPACITY = 32
# Compatibility spelling for external diagnostics.  It is a per-chunk memory
# capacity, never a whole-frame gameplay limit.
LIVE_BATCH_RECORD_LIMIT = DEFAULT_STREAM_CHUNK_CAPACITY

__all__ = [
    "FRAME_RECORD_BOUND_FORMAT",
    "DEFAULT_STREAM_CHUNK_CAPACITY",
    "LIVE_BATCH_RECORD_LIMIT",
    "ClassRecordMultiplicity",
    "FrameRecordBoundError",
    "FrameRecordBoundReport",
    "ProofBlocker",
    "analyze_active_frame_record_bound",
]


class FrameRecordBoundError(ValueError):
    """An unsupported source shape which must stop bound generation."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ProofBlocker:
    code: str
    missing_invariant: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "missing_invariant": self.missing_invariant,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ClassRecordMultiplicity:
    class_name: str
    isinstance_tags: tuple[str, ...]
    max_records_per_object: int
    action_ordinals: tuple[int, ...]
    witness_fields: tuple[tuple[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "class_name": self.class_name,
            "isinstance_tags": list(self.isinstance_tags),
            "max_records_per_object": self.max_records_per_object,
            "action_ordinals": list(self.action_ordinals),
            "witness_fields": dict(self.witness_fields),
        }


@dataclass(frozen=True)
class FrameRecordBoundReport:
    payload: Mapping[str, object]

    @property
    def status(self) -> str:
        return str(self.payload["status"])

    @property
    def exact_max_records(self) -> int | None:
        value = self.payload["exact_max_records"]
        return None if value is None else int(value)

    @property
    def certified_frame_max_records(self) -> int | None:
        value = self.payload["certified_frame_max_records"]
        return None if value is None else int(value)

    @property
    def blockers(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self.payload["blockers"])  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, object]:
        # JSON round-tripping gives callers an ordinary detached mapping and
        # also asserts that every proof datum is serialisable.
        return json.loads(json.dumps(self.payload, sort_keys=True))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.payload, ensure_ascii=False, sort_keys=True, indent=indent,
        ) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ast_sha256(node: ast.AST) -> str:
    return _sha256_bytes(
        ast.dump(node, include_attributes=False).encode("utf-8"))


def _parse(source: str, path: str) -> ast.Module:
    try:
        return ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise FrameRecordBoundError(
            "PZFRB001", f"cannot parse {path}: {exc.msg}") from exc


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [item for item in tree.body
               if isinstance(item, ast.ClassDef) and item.name == name]
    if len(matches) != 1:
        raise FrameRecordBoundError(
            "PZFRB002", f"expected one class {name!r}, got {len(matches)}")
    return matches[0]


def _method(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [item for item in owner.body
               if isinstance(item, ast.FunctionDef) and item.name == name]
    if len(matches) != 1:
        raise FrameRecordBoundError(
            "PZFRB003",
            f"expected one method {owner.name}.{name}, got {len(matches)}")
    return matches[0]


def _top_level_literal(tree: ast.Module, name: str) -> object:
    matches: list[ast.AST] = []
    for item in tree.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = (item.targets if isinstance(item, ast.Assign)
                       else [item.target])
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in targets):
                matches.append(item.value)
    if len(matches) != 1:
        raise FrameRecordBoundError(
            "PZFRB004",
            f"expected one top-level literal {name!r}, got {len(matches)}")
    try:
        return ast.literal_eval(matches[0])
    except (TypeError, ValueError) as exc:
        raise FrameRecordBoundError(
            "PZFRB004", f"{name!r} is not a finite literal") from exc


def _const_int(node: ast.AST, detail: str) -> int:
    try:
        value = ast.literal_eval(node)
    except (TypeError, ValueError) as exc:
        raise FrameRecordBoundError(
            "PZFRB005", f"{detail} is not an integer literal") from exc
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrameRecordBoundError(
            "PZFRB005", f"{detail} is not an integer literal")
    return value


def _attribute_path(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


@dataclass(frozen=True)
class _PoolFacts:
    slot_count: int
    reserved_sentinel_count: int
    allocatable_record_count: int
    checkpoint_free_count: int
    checkpoint_allocated_count: int
    checkpoint_accounted_slots: int
    slot_first: int
    slot_stop_exclusive: int
    slot_stride: int
    allocator_ast_sha256: str
    pending_append_ast_sha256: str
    enemy_mutations: tuple[tuple[int, str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "slot_count": self.slot_count,
            "slot_first": self.slot_first,
            "slot_stop_exclusive": self.slot_stop_exclusive,
            "slot_stride": self.slot_stride,
            "reserved_sentinel_count": self.reserved_sentinel_count,
            "allocatable_record_count": self.allocatable_record_count,
            "checkpoint_free_count": self.checkpoint_free_count,
            "checkpoint_allocated_count": self.checkpoint_allocated_count,
            "checkpoint_accounted_slots": self.checkpoint_accounted_slots,
            "allocator_ast_sha256": self.allocator_ast_sha256,
            "pending_append_ast_sha256": self.pending_append_ast_sha256,
            "enemy_list_mutations": [
                {"line": line, "kind": kind, "source": source}
                for line, kind, source in self.enemy_mutations
            ],
            "proved_invariant": (
                "every active self.enemies member is backed by one distinct "
                "non-sentinel M72ObjectPool slot"),
        }


def _slot_assignment(pool: ast.ClassDef) -> ast.AST:
    matches: list[ast.AST] = []
    for item in pool.body:
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
        if any(isinstance(target, ast.Name) and target.id == "SLOTS"
               for target in targets):
            matches.append(item.value)
    if len(matches) != 1:
        raise FrameRecordBoundError(
            "PZFRB005", f"expected one M72ObjectPool.SLOTS, got {len(matches)}")
    return matches[0]


def _pool_slots(pool: ast.ClassDef) -> tuple[tuple[int, ...], tuple[int, int, int]]:
    value = _slot_assignment(pool)
    if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and
            value.func.id == "tuple" and len(value.args) == 1 and
            not value.keywords):
        raise FrameRecordBoundError(
            "PZFRB005", "M72ObjectPool.SLOTS must be tuple(range(...))")
    range_call = value.args[0]
    if not (isinstance(range_call, ast.Call) and
            isinstance(range_call.func, ast.Name) and
            range_call.func.id == "range" and not range_call.keywords and
            len(range_call.args) == 3):
        raise FrameRecordBoundError(
            "PZFRB005", "M72ObjectPool.SLOTS must use three-argument range")
    start, stop, step = (
        _const_int(node, "M72ObjectPool.SLOTS range argument")
        for node in range_call.args)
    if step <= 0 or start < 0 or stop <= start:
        raise FrameRecordBoundError(
            "PZFRB005", "M72ObjectPool.SLOTS range is not positive/ascending")
    slots = tuple(range(start, stop, step))
    if not slots:
        raise FrameRecordBoundError("PZFRB005", "M72ObjectPool.SLOTS is empty")
    return slots, (start, stop, step)


def _fresh_sentinel_count(pool_init: ast.FunctionDef) -> int:
    slices: list[ast.Slice] = []
    for node in ast.walk(pool_init):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "free"
                   for target in targets):
            continue
        value = node.value
        if (isinstance(value, ast.Subscript) and
                _attribute_path(value.value) == "self.SLOTS" and
                isinstance(value.slice, ast.Slice)):
            slices.append(value.slice)
    if len(slices) != 1:
        raise FrameRecordBoundError(
            "PZFRB006",
            "fresh object-pool free list must contain one self.SLOTS[n:] slice")
    item = slices[0]
    if item.lower is None or item.upper is not None or item.step is not None:
        raise FrameRecordBoundError(
            "PZFRB006", "fresh object-pool slice must be self.SLOTS[n:]")
    count = _const_int(item.lower, "object-pool sentinel count")
    if count < 0:
        raise FrameRecordBoundError(
            "PZFRB006", "object-pool sentinel count is negative")
    return count


def _checkpoint_slots(tree: ast.Module) -> tuple[set[int], int]:
    particles = _top_level_literal(tree, "STAGE1_CHECKPOINT_PARTICLES")
    cycles = _top_level_literal(tree, "STAGE1_CHECKPOINT_PALETTE_CYCLES")
    if not isinstance(particles, tuple) or not isinstance(cycles, tuple):
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint record tables must be tuples")
    try:
        record_slots = {int(item[0]) for item in (*particles, *cycles)}
    except (IndexError, TypeError, ValueError) as exc:
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint record table lacks a literal slot") from exc
    world_init = _method(_class(tree, "M72EnemyWorld"), "__init__")
    uninitialized_slots = [
        _const_int(node.value, "checkpoint uninitialized object slot")
        for node in ast.walk(world_init)
        if isinstance(node, ast.Assign) and
        any(_attribute_path(target) == "uninitialized.object_slot"
            for target in node.targets)
    ]
    owner_slots: list[int] = []
    for node in ast.walk(world_init):
        if not (isinstance(node, ast.Call) and
                _attribute_path(node.func) == "ParticleControllerE4A5"):
            continue
        if len(node.args) < 6:
            raise FrameRecordBoundError(
                "PZFRB007", "checkpoint particle controller has no slot")
        owner_slots.append(_const_int(
            node.args[-1], "checkpoint particle-controller slot"))
    if len(uninitialized_slots) != 1 or len(owner_slots) != 1:
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint must expose one uninitialized and one owner slot")
    record_slots.update(uninitialized_slots)
    record_slots.update(owner_slots)
    return record_slots, len(particles) + len(cycles) + 2


def _call_count(node: ast.AST, path: str) -> int:
    return sum(
        isinstance(item, ast.Call) and
        (_attribute_path(item.func) == path or ast.unparse(item.func) == path)
        for item in ast.walk(node))


def _audit_pending_allocator(tree: ast.Module) -> str:
    method = _method(_class(tree, "M72PendingList"), "append")
    required = {
        "self.world.object_pool.take": 1,
        "self.world.object_pool.bind": 1,
        "super().append": 1,
    }
    actual = {name: _call_count(method, name) for name in required}
    if actual != required:
        raise FrameRecordBoundError(
            "PZFRB008", f"pending allocator shape changed: {actual!r}")
    none_failure_returns = 0
    for node in ast.walk(method):
        if not isinstance(node, ast.If):
            continue
        if "slot is None" == ast.unparse(node.test) and any(
                isinstance(item, ast.Return) for item in node.body):
            none_failure_returns += 1
    if none_failure_returns != 1:
        raise FrameRecordBoundError(
            "PZFRB008", "pending allocation failure no longer returns before append")
    return _ast_sha256(method)


def _enemy_mutations(tree: ast.Module) -> tuple[tuple[int, str, str], ...]:
    owner = _class(tree, "M72EnemyWorld")
    result: list[tuple[int, str, str]] = []
    for node in ast.walk(owner):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_attribute_path(target) == "self.enemies" for target in targets):
                value = node.value
                if isinstance(value, ast.List) and not value.elts:
                    kind = "initialize-empty"
                elif (isinstance(value, ast.List) and value.elts and
                      any(isinstance(item, ast.Starred) for item in value.elts)):
                    kind = "checkpoint-seed"
                elif isinstance(value, ast.Name) and value.id == "survivors":
                    kind = "filtered-survivors"
                else:
                    raise FrameRecordBoundError(
                        "PZFRB009", "unsupported self.enemies assignment at "
                        f"line {node.lineno}: {ast.unparse(node)}")
                result.append((node.lineno, kind, ast.unparse(node)))
        elif isinstance(node, ast.Call):
            path = _attribute_path(node.func)
            if path not in ("self.enemies.append", "self.enemies.extend"):
                continue
            argument = node.args[0] if len(node.args) == 1 else None
            if path.endswith(".append") and isinstance(argument, ast.Name):
                method = next((parent for parent in owner.body
                               if isinstance(parent, ast.FunctionDef) and
                               node in ast.walk(parent)), None)
                if method is None or _call_count(
                        method, "self.object_pool.bind") < 1:
                    raise FrameRecordBoundError(
                        "PZFRB009", "direct enemy append lacks pool bind")
                kind = "append-after-bind"
            elif (path.endswith(".extend") and
                  _attribute_path(argument) == "self.pending"):
                kind = "extend-allocating-pending"
            elif (path.endswith(".extend") and isinstance(argument, ast.Name)):
                # ``spawned`` is a materialised slice of M72PendingList, whose
                # append override has already allocated every member.
                definitions = [item.value for item in ast.walk(owner)
                               if isinstance(item, ast.Assign) and
                               any(isinstance(target, ast.Name) and
                                   target.id == argument.id
                                   for target in item.targets)]
                if not any("self.pending" in ast.unparse(value)
                           for value in definitions):
                    raise FrameRecordBoundError(
                        "PZFRB009", "enemy extend source is not pending-backed")
                kind = "extend-pending-slice"
            else:
                raise FrameRecordBoundError(
                    "PZFRB009", f"unsupported enemy mutation: {ast.unparse(node)}")
            result.append((node.lineno, kind, ast.unparse(node)))
    result.sort()
    expected_kinds = {
        "initialize-empty": 1,
        "checkpoint-seed": 1,
        "filtered-survivors": 1,
        "append-after-bind": 1,
        "extend-allocating-pending": 1,
        "extend-pending-slice": 1,
    }
    actual = {kind: sum(item[1] == kind for item in result)
              for kind in expected_kinds}
    if actual != expected_kinds:
        raise FrameRecordBoundError(
            "PZFRB009", f"enemy-list mutation inventory changed: {actual!r}")
    return tuple(result)


def _pool_facts(tree: ast.Module) -> _PoolFacts:
    pool = _class(tree, "M72ObjectPool")
    pool_init = _method(pool, "__init__")
    slots, (start, stop, step) = _pool_slots(pool)
    sentinels = _fresh_sentinel_count(pool_init)
    if sentinels >= len(slots):
        raise FrameRecordBoundError(
            "PZFRB006", "sentinels consume the entire object pool")
    checkpoint_free = _top_level_literal(tree, "STAGE1_CHECKPOINT_FREE_SLOTS")
    if not isinstance(checkpoint_free, tuple) or any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in checkpoint_free):
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint free-slot table is not an integer tuple")
    if len(set(checkpoint_free)) != len(checkpoint_free):
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint free-slot table contains duplicates")
    slot_set = set(slots)
    if not set(checkpoint_free) <= slot_set:
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint free slot lies outside M72ObjectPool.SLOTS")
    occupied = slot_set - set(checkpoint_free)
    checkpoint_slots, checkpoint_accounted = _checkpoint_slots(tree)
    accounted = checkpoint_slots | set(slots[:sentinels])
    if occupied != accounted or len(accounted) != checkpoint_accounted + sentinels:
        raise FrameRecordBoundError(
            "PZFRB007", "checkpoint occupied slots are not exactly accounted")
    return _PoolFacts(
        slot_count=len(slots), reserved_sentinel_count=sentinels,
        allocatable_record_count=len(slots) - sentinels,
        checkpoint_free_count=len(checkpoint_free),
        checkpoint_allocated_count=len(occupied),
        checkpoint_accounted_slots=len(accounted),
        slot_first=start, slot_stop_exclusive=stop, slot_stride=step,
        allocator_ast_sha256=_ast_sha256(pool_init),
        pending_append_ast_sha256=_audit_pending_allocator(tree),
        enemy_mutations=_enemy_mutations(tree),
    )


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ast.unparse(node)


def _enemy_classes(tree: ast.Module) -> tuple[str, ...]:
    graph = {
        item.name: tuple(_base_name(base) for base in item.bases)
        for item in tree.body if isinstance(item, ast.ClassDef)
    }
    memo: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def ancestors(name: str) -> frozenset[str]:
        if name in memo:
            return memo[name]
        if name in visiting:
            raise FrameRecordBoundError(
                "PZFRB010", f"cycle in class graph at {name!r}")
        visiting.add(name)
        result = {name}
        for base in graph.get(name, ()):
            if base in graph:
                result.update(ancestors(base))
        visiting.remove(name)
        memo[name] = frozenset(result)
        return memo[name]

    if "Enemy" not in graph:
        raise FrameRecordBoundError("PZFRB010", "Enemy class is missing")
    return tuple(sorted(
        name for name in graph if "Enemy" in ancestors(name)))


def _walk_expr(value: DrawExpr) -> Iterable[DrawExpr]:
    yield value
    for argument in value.arguments:
        yield from _walk_expr(argument)


def _condition_field(value: DrawExpr, object_names: frozenset[str]) -> str | None:
    if (value.op == "attribute" and len(value.arguments) == 1 and
            value.arguments[0].op == "name" and
            str(value.arguments[0].value) in object_names):
        return str(value.value)
    if (value.op == "getattr" and len(value.arguments) in (2, 3) and
            value.arguments[0].op == "name" and
            str(value.arguments[0].value) in object_names and
            value.arguments[1].op == "constant" and
            isinstance(value.arguments[1].value, str)):
        return value.arguments[1].value
    return None


def _other_scalar(constants: set[object]) -> int:
    for candidate in (0, 1, 2, 0x7FFF):
        if candidate not in constants:
            return candidate
    raise AssertionError("finite candidate set exhausted")


def _condition_domains(
        plan: SpriteDrawPlanIR, model: DrawCBackendModel,
        ) -> tuple[tuple[str, tuple[object, ...]], ...]:
    object_names = model.object_bound_names
    referenced: set[str] = set()
    compared: dict[str, set[object]] = {}
    for action in plan.actions:
        for condition in action.conditions:
            for node in _walk_expr(condition):
                field = _condition_field(node, object_names)
                if field is not None:
                    referenced.add(field)
                if node.op not in ("equal", "not_equal"):
                    continue
                left, right = node.arguments
                left_field = _condition_field(left, object_names)
                right_field = _condition_field(right, object_names)
                if left_field is not None and right.op == "constant":
                    compared.setdefault(left_field, set()).add(right.value)
                if right_field is not None and left.op == "constant":
                    compared.setdefault(right_field, set()).add(left.value)
    specs = {item.name: item for item in model.fields}
    missing = sorted(referenced - set(specs))
    if missing:
        raise FrameRecordBoundError(
            "PZFRB011", "condition fields absent from normalized model: " +
            ", ".join(missing))
    result: list[tuple[str, tuple[object, ...]]] = []
    for name in sorted(referenced):
        spec = specs[name]
        literals = compared.get(name, set())
        if spec.kind == "boolean":
            values: tuple[object, ...] = (False, True)
        elif spec.kind == "string_state":
            strings = {item for item in literals if isinstance(item, str)}
            strings.update(spec.string_values)
            other = "__pyz80_other_state__"
            if other in strings:
                raise FrameRecordBoundError(
                    "PZFRB011", "reserved state witness collides with source")
            values = (*sorted(strings), other)
        elif spec.kind in ("unsigned_scalar", "signed_scalar"):
            if any(isinstance(item, bool) or not isinstance(item, int)
                   for item in literals):
                raise FrameRecordBoundError(
                    "PZFRB011", f"non-integer comparison for {name!r}")
            values = (*sorted(literals), _other_scalar(literals))
        else:
            raise FrameRecordBoundError(
                "PZFRB011", f"unsupported condition field kind {spec.kind!r}")
        result.append((name, values))
    return tuple(result)


class _ConditionEvaluator:
    def __init__(
            self, object_names: frozenset[str], classes: frozenset[str],
            fields: Mapping[str, object]) -> None:
        self.object_names = object_names
        self.classes = classes
        self.fields = fields

    def evaluate(self, value: DrawExpr) -> object:
        op = value.op
        if op == "constant":
            return value.value
        if op == "name":
            if str(value.value) in self.object_names:
                return self
            raise FrameRecordBoundError(
                "PZFRB012", f"unbound condition name {value.value!r}")
        if op == "attribute":
            owner = self.evaluate(value.arguments[0])
            if owner is not self:
                raise FrameRecordBoundError(
                    "PZFRB012", "condition attribute owner is not loop object")
            try:
                return self.fields[str(value.value)]
            except KeyError as exc:
                raise FrameRecordBoundError(
                    "PZFRB012", f"missing condition field {value.value!r}") from exc
        if op == "getattr":
            owner = self.evaluate(value.arguments[0])
            name = self.evaluate(value.arguments[1])
            if owner is not self or not isinstance(name, str):
                raise FrameRecordBoundError("PZFRB012", "invalid getattr condition")
            if name in self.fields:
                return self.fields[name]
            if len(value.arguments) == 3:
                return self.evaluate(value.arguments[2])
            raise FrameRecordBoundError(
                "PZFRB012", f"missing getattr condition field {name!r}")
        if op == "not":
            return not bool(self.evaluate(value.arguments[0]))
        if op == "all":
            return all(bool(self.evaluate(item)) for item in value.arguments)
        if op in ("equal", "not_equal"):
            left = self.evaluate(value.arguments[0])
            right = self.evaluate(value.arguments[1])
            return left == right if op == "equal" else left != right
        if op == "type_is":
            subject = self.evaluate(value.arguments[0])
            types = value.arguments[1]
            if subject is not self or types.op != "types":
                raise FrameRecordBoundError("PZFRB012", "invalid type_is condition")
            return any(str(item.value) in self.classes
                       for item in types.arguments)
        raise FrameRecordBoundError(
            "PZFRB012", f"unsupported draw condition op {op!r}")


def _class_multiplicities(
        tree: ast.Module, plan: SpriteDrawPlanIR, model: DrawCBackendModel,
        ) -> tuple[ClassRecordMultiplicity, ...]:
    memberships = dict(model.class_memberships)
    classes = _enemy_classes(tree)
    missing = sorted(set(classes) - set(memberships))
    if missing:
        raise FrameRecordBoundError(
            "PZFRB010", "normalized class graph lost Enemy subclasses: " +
            ", ".join(missing))
    domains = _condition_domains(plan, model)
    domain_names = tuple(item[0] for item in domains)
    domain_values: Sequence[tuple[object, ...]] = tuple(item[1] for item in domains)
    result: list[ClassRecordMultiplicity] = []
    object_loop = next((item for item in plan.loops
                        if len(item.bound_names) == 1), None)
    if object_loop is None:
        raise FrameRecordBoundError("PZFRB013", "object draw loop is missing")
    actions = tuple(plan.actions[index] for index in object_loop.action_ordinals)
    for class_name in classes:
        tags = frozenset(memberships[class_name])
        best_count = -1
        best_actions: tuple[int, ...] = ()
        best_fields: tuple[tuple[str, object], ...] = ()
        for values in itertools.product(*domain_values):
            fields = dict(zip(domain_names, values))
            evaluator = _ConditionEvaluator(
                model.object_bound_names, tags, fields)
            enabled = tuple(
                action.ordinal for action in actions
                if all(bool(evaluator.evaluate(condition))
                       for condition in action.conditions))
            if len(enabled) > best_count:
                best_count = len(enabled)
                best_actions = enabled
                best_fields = tuple(sorted(fields.items()))
        if best_count < 0:
            raise AssertionError("empty condition-domain product")
        result.append(ClassRecordMultiplicity(
            class_name=class_name,
            isinstance_tags=tuple(sorted(tags)),
            max_records_per_object=best_count,
            action_ordinals=best_actions,
            witness_fields=best_fields,
        ))
    return tuple(result)


@dataclass(frozen=True)
class _TransientFacts:
    producer_sites: tuple[tuple[int, str, str], ...]
    clear_sites: tuple[int, ...]
    append_sites_in_emitter: tuple[int, ...]
    emitter_ast_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "list_kind": "unbounded Python list",
            "cleared_at_start_of_world_update": len(self.clear_sites) == 1,
            "clear_lines": list(self.clear_sites),
            "emitter_append_lines": list(self.append_sites_in_emitter),
            "emitter_ast_sha256": self.emitter_ast_sha256,
            "producer_count": len(self.producer_sites),
            "producers": [
                {"line": line, "owner": owner, "function": function}
                for line, owner, function in self.producer_sites
            ],
            "exact_per_frame_bound": None,
        }


def _transient_facts(tree: ast.Module) -> _TransientFacts:
    world = _class(tree, "M72EnemyWorld")
    update = _method(world, "update")
    clear_sites = tuple(sorted(
        node.lineno for node in ast.walk(update)
        if isinstance(node, ast.Call) and
        _attribute_path(node.func) == "self.transient_sprites.clear"))
    if len(clear_sites) != 1:
        raise FrameRecordBoundError(
            "PZFRB014", "world update must clear transient_sprites exactly once")
    emitter = _method(world, "emit_transient_sprite")
    append_sites = tuple(sorted(
        node.lineno for node in ast.walk(emitter)
        if isinstance(node, ast.Call) and
        _attribute_path(node.func) == "self.transient_sprites.append"))
    if len(append_sites) != 1:
        raise FrameRecordBoundError(
            "PZFRB014", "transient emitter must append exactly one tuple")

    producer_sites: list[tuple[int, str, str]] = []
    for top in tree.body:
        if isinstance(top, ast.ClassDef):
            for function in top.body:
                if not isinstance(function, ast.FunctionDef):
                    continue
                for node in ast.walk(function):
                    if (isinstance(node, ast.Call) and
                            _attribute_path(node.func) ==
                            "world.emit_transient_sprite"):
                        producer_sites.append(
                            (node.lineno, top.name, function.name))
        elif isinstance(top, ast.FunctionDef):
            for node in ast.walk(top):
                if (isinstance(node, ast.Call) and
                        _attribute_path(node.func) ==
                        "world.emit_transient_sprite"):
                    producer_sites.append((node.lineno, "<module>", top.name))
    producer_sites.sort()
    if not producer_sites:
        raise FrameRecordBoundError(
            "PZFRB014", "no transient producer is visible to the AST")
    return _TransientFacts(
        producer_sites=tuple(producer_sites), clear_sites=clear_sites,
        append_sites_in_emitter=append_sites,
        emitter_ast_sha256=_ast_sha256(emitter),
    )


def _event_scheduler_facts(tree: ast.Module) -> dict[str, object]:
    world = _class(tree, "M72EnemyWorld")
    update = _method(world, "update")
    dispatch_calls = [node for node in ast.walk(update)
                      if isinstance(node, ast.Call) and
                      _attribute_path(node.func) == "self._dispatch"]
    pointer_steps = [node for node in ast.walk(update)
                     if isinstance(node, ast.AugAssign) and
                     _attribute_path(node.target) == "self.event_pointer"]
    if len(dispatch_calls) != 1 or len(pointer_steps) != 1 or not (
            isinstance(pointer_steps[0].op, ast.Add) and
            _const_int(pointer_steps[0].value, "event pointer step") == 4):
        raise FrameRecordBoundError(
            "PZFRB015", "one-record event dispatcher shape changed")
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(update):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    cursor: ast.AST | None = dispatch_calls[0]
    while cursor is not None and cursor is not update:
        if isinstance(cursor, (ast.For, ast.AsyncFor, ast.While)):
            raise FrameRecordBoundError(
                "PZFRB015", "event dispatch is nested in a runtime loop")
        cursor = parent.get(cursor)

    ranges = _top_level_literal(tree, "STAGE_EVENT_RANGES")
    if not isinstance(ranges, dict) or not ranges:
        raise FrameRecordBoundError(
            "PZFRB015", "STAGE_EVENT_RANGES is not a finite dictionary")
    stage_counts: dict[str, int] = {}
    for stage, pair in sorted(ranges.items()):
        if (isinstance(stage, bool) or not isinstance(stage, int) or
                not isinstance(pair, tuple) or len(pair) != 2 or
                any(isinstance(item, bool) or not isinstance(item, int)
                    for item in pair)):
            raise FrameRecordBoundError(
                "PZFRB015", "invalid STAGE_EVENT_RANGES entry")
        first, last = pair
        if last < first or (last - first) % 4:
            raise FrameRecordBoundError(
                "PZFRB015", f"stage {stage} event range is not 4-byte aligned")
        stage_counts[str(stage)] = (last - first) // 4 + 1

    pending_append = _method(_class(tree, "M72PendingList"), "append")
    immediate_updates = _call_count(pending_append, "enemy.update")
    if immediate_updates != 1:
        raise FrameRecordBoundError(
            "PZFRB015", "pending same-pass child update shape changed")
    scheduled_snapshots = sum(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
        node.func.id == "tuple" and len(node.args) == 1 and
        _attribute_path(node.args[0]) == "self.enemies"
        for node in ast.walk(update))
    if scheduled_snapshots != 1:
        raise FrameRecordBoundError(
            "PZFRB015", "scheduler no longer has one self.enemies snapshot")
    return {
        "one_event_dispatch_site_per_world_update": True,
        "event_pointer_step_bytes": 4,
        "stage_event_record_counts": stage_counts,
        "scheduler_snapshot_count": scheduled_snapshots,
        "pending_same_pass_update_sites": immediate_updates,
        "world_update_ast_sha256": _ast_sha256(update),
        "proved": (
            "finite event tables and one lexical dispatch do not by themselves "
            "bound overlap of live objects spawned on earlier frames"),
    }


def _active_order_facts(app_tree: ast.Module, game_tree: ast.Module) -> dict[str, object]:
    main_matches = [node for node in app_tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main"]
    if len(main_matches) != 1:
        raise FrameRecordBoundError("PZFRB016", "rtype_port.app.main is missing")
    main = main_matches[0]
    game_updates = sorted(
        node.lineno for node in ast.walk(main)
        if isinstance(node, ast.Call) and _attribute_path(node.func) == "game.update")
    game_renders = sorted(
        node.lineno for node in ast.walk(main)
        if isinstance(node, ast.Call) and _attribute_path(node.func) == "game.render")
    if len(game_updates) != 1 or len(game_renders) != 1 or not (
            game_updates[0] < game_renders[0]):
        raise FrameRecordBoundError(
            "PZFRB016", "app loop no longer has one update before one render")
    render = _method(_class(game_tree, "Game"), "render")
    world_draws = sorted(
        node.lineno for node in ast.walk(render)
        if isinstance(node, ast.Call) and
        _attribute_path(node.func) == "self.enemy_world.draw")
    if len(world_draws) != 1:
        raise FrameRecordBoundError(
            "PZFRB016", "Game.render must call enemy_world.draw exactly once")
    return {
        "app_update_line": game_updates[0],
        "app_render_line": game_renders[0],
        "enemy_world_draw_line": world_draws[0],
        "snapshot": "after Game.update and before M72EnemyWorld.draw",
        "app_main_ast_sha256": _ast_sha256(main),
        "game_render_ast_sha256": _ast_sha256(render),
    }


def _source(root: Path, relative: str, override: str | None) -> tuple[str, str]:
    text = (override if override is not None
            else (root / relative).read_bytes().decode("utf-8"))
    return text, _sha256_bytes(text.encode("utf-8"))


def analyze_active_frame_record_bound(
        project_root: Path | str, *,
        stream_chunk_capacity: int = DEFAULT_STREAM_CHUNK_CAPACITY,
        enemy_source_override: str | None = None,
        game_source_override: str | None = None,
        app_source_override: str | None = None,
        ) -> FrameRecordBoundReport:
    """Derive a sound conservative frame-record bound without guessing.

    ``stream_chunk_capacity`` is never copied into a frame maximum: it bounds
    temporary storage only.  ``exact_max_records`` remains null unless an
    attainability proof exists; ``certified_frame_max_records`` carries the
    conservative upper bound accepted for RAM_DL and worst-case timing.
    """
    if (isinstance(stream_chunk_capacity, bool) or
            not isinstance(stream_chunk_capacity, int) or
            stream_chunk_capacity <= 0):
        raise FrameRecordBoundError(
            "PZFRB017", "stream chunk capacity must be a positive integer")
    root = Path(project_root).resolve()
    enemy_text, enemy_hash = _source(
        root, "Source/Python/rtype_port/enemies.py", enemy_source_override)
    game_text, game_hash = _source(
        root, "Source/Python/rtype_port/game.py", game_source_override)
    app_text, app_hash = _source(
        root, "Source/Python/rtype_port/app.py", app_source_override)
    launcher = (root / "run_python.cmd").read_bytes()
    launcher_text = launcher.decode("utf-8")
    if "-m rtype_port.app" not in launcher_text:
        raise FrameRecordBoundError(
            "PZFRB018", "run_python.cmd no longer launches rtype_port.app")

    enemy_tree = _parse(enemy_text, "Source/Python/rtype_port/enemies.py")
    game_tree = _parse(game_text, "Source/Python/rtype_port/game.py")
    app_tree = _parse(app_text, "Source/Python/rtype_port/app.py")
    plan = compile_active_enemy_draw_plan(
        root, source_override=enemy_text)
    model = build_draw_c_model(plan, source_text=enemy_text)
    pool = _pool_facts(enemy_tree)
    multiplicities = _class_multiplicities(enemy_tree, plan, model)
    if not multiplicities:
        raise FrameRecordBoundError(
            "PZFRB013", "no Enemy class can reach the object draw loop")
    max_per_object = max(
        item.max_records_per_object for item in multiplicities)
    maximizers = tuple(sorted(
        item.class_name for item in multiplicities
        if item.max_records_per_object == max_per_object))
    object_ceiling = pool.allocatable_record_count * max_per_object
    transients = _transient_facts(enemy_tree)
    try:
        reachability = analyze_frame_record_reachability(
            root,
            enemy_source=enemy_text,
            game_source=game_text,
            pool_record_capacity=pool.allocatable_record_count,
            class_multiplicities={
                item.class_name: item.max_records_per_object
                for item in multiplicities
            },
            pool_invariant_sha256=_sha256_bytes(json.dumps(
                pool.as_dict(), sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")),
        )
    except FrameRecordReachabilityError as exc:
        raise FrameRecordBoundError(exc.code, exc.detail) from exc
    reachability_value = reachability.as_dict()
    abstract_object_bound = int(
        reachability_value["object_records"]["finite_upper_bound"])
    abstract_transient_bound = int(
        reachability_value["transient_sprites"][
            "finite_per_frame_upper_bound"])
    abstract_frame_bound = int(
        reachability_value["frame_records"]["finite_upper_bound"])
    object_loop = next(item for item in plan.loops if len(item.bound_names) == 1)
    transient_loop = next(item for item in plan.loops if len(item.bound_names) == 5)

    exact_equation = {
        "text": (
            "sum(action condition true for every object/action in object loop) "
            "+ len(transient_sprites)"),
        "object_action_ordinals": list(object_loop.action_ordinals),
        "transient_action_ordinals": list(transient_loop.action_ordinals),
        "object_action_count": len(object_loop.action_ordinals),
        "transient_records_per_tuple": len(transient_loop.action_ordinals),
        "semantic_sha256": plan.semantic_sha256,
        "exact_for_every_concrete_snapshot": True,
    }
    optional_tightening_gaps = (
        ProofBlocker(
            "PZFRB101",
            "A stage-local simultaneous occupancy/lifetime induction which "
            "tightens the proved finite abstract object-record bound to the "
            "exact attainable post-update/pre-draw maximum.",
            (
                f"source/ROM abstract proof bounds object records by "
                f"{abstract_object_bound}",
                "the remaining baseline assigns every otherwise-unbounded "
                "pool resident the largest unbounded-class IR multiplicity",
                "bounded high-multiplicity premiums use whole-world instance "
                "counts, not simultaneous stage-local occupancy",
            ),
        ),
        ProofBlocker(
            "PZFRB102",
            "A same-update coincidence proof which tightens the already "
            "finite transient bound to the exact simultaneous maximum.",
            (
                "transient_sprites is cleared once at world-update entry",
                f"all {len(transients.producer_sites)} AST producer sites have "
                "closed one-shot state proofs",
                f"the source-derived whole-lifetime sum proves at most "
                f"{abstract_transient_bound} entries in any frame",
                "producer timing/coincidence is not yet solved tightly",
            ),
        ),
    )
    payload: dict[str, object] = {
        "format": FRAME_RECORD_BOUND_FORMAT,
        "status": "READY_CONSERVATIVE_REACHABLE_STATE_BOUND",
        "proof_complete": True,
        "bound_kind": "conservative_upper_bound",
        "source_program": {
            "launcher": "run_python.cmd",
            "module": "rtype_port.app",
            "canonical": False,
        },
        "source_bindings": {
            "run_python.cmd": _sha256_bytes(launcher),
            "Source/Python/rtype_port/app.py": app_hash,
            "Source/Python/rtype_port/game.py": game_hash,
            "Source/Python/rtype_port/enemies.py": enemy_hash,
        },
        "exact_max_records": None,
        "certified_frame_max_records": abstract_frame_bound,
        "can_certify_frame_budget": True,
        "finite_abstract_bound_proved": True,
        "finite_abstract_upper_bound_records": abstract_frame_bound,
        "streaming_transport": {
            "record_array_required": False,
            "chunk_capacity_records": stream_chunk_capacity,
            "whole_frame_limited_to_one_chunk": False,
            "maximum_chunks_per_frame": None,
            "memory_safety_requires_exact_frame_max": False,
            "ram_dl_and_timing_require_exact_frame_max": False,
            "ram_dl_and_timing_require_sound_upper_bound": True,
        },
        "draw_plan": {
            **plan.report(),
            "class_graph_sha256": model.class_graph_sha256,
            "record_size_bytes": 8,
            "exact_counter_equation": exact_equation,
        },
        "active_frame_order": _active_order_facts(app_tree, game_tree),
        "object_pool": pool.as_dict(),
        "event_scheduler": _event_scheduler_facts(enemy_tree),
        "object_multiplicity": {
            "derivation": (
                "exhaustive finite evaluation of SpriteDrawPlanIR predicates "
                "over the AST-derived class graph and predicate literal domains"),
            "class_count": len(multiplicities),
            "max_records_per_pool_object": max_per_object,
            "maximizer_classes": list(maximizers),
            "pool_only_safe_object_upper_bound": object_ceiling,
            "is_live_reachability_bound": False,
            "source_derived_abstract_upper_bound": abstract_object_bound,
            "classes": [item.as_dict() for item in multiplicities],
        },
        "transients": {
            **transients.as_dict(),
            "source_derived_finite_upper_bound": abstract_transient_bound,
        },
        "abstract_reachability": reachability_value,
        "blockers": [],
        "optional_tightening_gaps": [
            item.as_dict() for item in optional_tightening_gaps
        ],
    }
    return FrameRecordBoundReport(payload)
