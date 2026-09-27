"""Source-derived abstract reachability proof for enemy draw records.

This module deliberately proves an *upper bound*, not an observed maximum.
It combines four independently checked facts from the active Python/ROM pair:

* the dynamic object list is limited by the audited M72 object pool;
* the ROM event cursor traverses a finite acyclic stage graph;
* constructors with a draw multiplicity above the unbounded baseline have a
  finite source-derived lifetime instance count; and
* every transient producer belongs to a finite one-shot boss spawn tree and
  has a source-shaped one-shot emission transition.

No gameplay count is copied into this analyser.  Loop cardinalities, event
counts, transition targets, constructor origins, state guards and sprite
multiplicities are inputs derived from the active source and immutable ROM.
The resulting conservative bound is useful as a machine-checked sub-proof;
it is not promoted to the exact/attainable frame maximum.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


FRAME_RECORD_REACHABILITY_FORMAT = (
    "pyz80.frame-record-reachability-subproof.v1")
_MISSING = object()

__all__ = [
    "FRAME_RECORD_REACHABILITY_FORMAT",
    "FrameRecordReachabilityError",
    "FrameRecordReachabilityReport",
    "analyze_frame_record_reachability",
]


class FrameRecordReachabilityError(ValueError):
    """A source/ROM shape outside the proved abstract domain."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class FrameRecordReachabilityReport:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, sort_keys=True))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.payload, ensure_ascii=False, sort_keys=True, indent=indent,
        ) + "\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ast_sha256(node: ast.AST) -> str:
    return _sha256(ast.dump(node, include_attributes=False).encode("utf-8"))


def _path(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _literal(tree: ast.Module, name: str) -> object:
    values: list[ast.AST] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        if any(isinstance(target, ast.Name) and target.id == name
               for target in targets):
            values.append(statement.value)
    if len(values) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR001", f"expected one top-level {name}, got {len(values)}")
    try:
        return ast.literal_eval(values[0])
    except (TypeError, ValueError) as exc:
        raise FrameRecordReachabilityError(
            "PZFRR001", f"{name} is not a finite literal") from exc


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == name]
    if len(matches) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR002", f"expected one class {name}, got {len(matches)}")
    return matches[0]


def _method(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [node for node in owner.body
               if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR002",
            f"expected one method {owner.name}.{name}, got {len(matches)}")
    return matches[0]


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ast.unparse(node)


def _enemy_classes(tree: ast.Module) -> frozenset[str]:
    graph = {
        node.name: tuple(_base_name(base) for base in node.bases)
        for node in tree.body if isinstance(node, ast.ClassDef)
    }
    memo: dict[str, frozenset[str]] = {}

    def ancestors(name: str, visiting: frozenset[str] = frozenset()
                  ) -> frozenset[str]:
        if name in memo:
            return memo[name]
        if name in visiting:
            raise FrameRecordReachabilityError(
                "PZFRR003", f"class graph cycle at {name}")
        result = {name}
        for base in graph.get(name, ()):
            if base in graph:
                result.update(ancestors(base, visiting | {name}))
        memo[name] = frozenset(result)
        return memo[name]

    if "Enemy" not in graph:
        raise FrameRecordReachabilityError("PZFRR003", "Enemy is missing")
    return frozenset(
        name for name in graph if "Enemy" in ancestors(name))


def _derived_pool_capacity(tree: ast.Module) -> int:
    pool = _class(tree, "M72ObjectPool")
    assignments = []
    for statement in pool.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if any(isinstance(target, ast.Name) and target.id == "SLOTS"
               for target in targets):
            assignments.append(statement.value)
    if len(assignments) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR003", "M72ObjectPool.SLOTS assignment changed")
    value = assignments[0]
    if not (isinstance(value, ast.Call) and _path(value.func) == "tuple" and
            len(value.args) == 1 and not value.keywords and
            isinstance(value.args[0], ast.Call) and
            _path(value.args[0].func) == "range"):
        raise FrameRecordReachabilityError(
            "PZFRR003", "M72ObjectPool.SLOTS is not tuple(range(...))")
    try:
        arguments = [ast.literal_eval(item) for item in value.args[0].args]
    except (TypeError, ValueError) as exc:
        raise FrameRecordReachabilityError(
            "PZFRR003", "M72ObjectPool range is not literal") from exc
    if (not 1 <= len(arguments) <= 3 or
            any(isinstance(item, bool) or not isinstance(item, int)
                for item in arguments)):
        raise FrameRecordReachabilityError(
            "PZFRR003", "M72ObjectPool range arguments are invalid")
    slot_count = len(range(*arguments))
    init = _method(pool, "__init__")
    sentinel_counts = []
    for node in ast.walk(init):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "free"
                   for target in targets):
            continue
        candidate = node.value
        if (isinstance(candidate, ast.Subscript) and
                _path(candidate.value) == "self.SLOTS" and
                isinstance(candidate.slice, ast.Slice) and
                candidate.slice.lower is not None and
                candidate.slice.upper is None and candidate.slice.step is None):
            try:
                sentinel_counts.append(ast.literal_eval(candidate.slice.lower))
            except (TypeError, ValueError) as exc:
                raise FrameRecordReachabilityError(
                    "PZFRR003", "pool sentinel slice is not literal") from exc
    if (len(sentinel_counts) != 1 or isinstance(sentinel_counts[0], bool) or
            not isinstance(sentinel_counts[0], int) or
            not 0 <= sentinel_counts[0] < slot_count):
        raise FrameRecordReachabilityError(
            "PZFRR003", "pool sentinel count is invalid")
    return slot_count - sentinel_counts[0]


def _rom_path(tree: ast.Module, root: Path) -> Path:
    assignments: list[ast.AST] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target])
        if any(isinstance(target, ast.Name) and target.id == "ROM_PATH"
               for target in targets):
            assignments.append(statement.value)
    if len(assignments) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR004", "ROM_PATH must have one source assignment")

    def segments(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Name) and node.id == "ROOT":
            return ()
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and
                isinstance(node.right, ast.Constant) and
                isinstance(node.right.value, str)):
            return segments(node.left) + (node.right.value,)
        raise FrameRecordReachabilityError(
            "PZFRR004", "ROM_PATH must be ROOT / finite string segments")

    result = root.joinpath(*segments(assignments[0])).resolve()
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise FrameRecordReachabilityError(
            "PZFRR004", "ROM_PATH escapes the project root") from exc
    return result


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    result: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            result[child] = node
    return result


def _scope(node: ast.AST, parents: Mapping[ast.AST, ast.AST]
           ) -> tuple[ast.ClassDef | None, ast.FunctionDef | None]:
    owner: ast.ClassDef | None = None
    function: ast.FunctionDef | None = None
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if function is None and isinstance(cursor, ast.FunctionDef):
            function = cursor
        if isinstance(cursor, ast.ClassDef):
            owner = cursor
            break
    return owner, function


def _contains(container: Sequence[ast.stmt], node: ast.AST) -> bool:
    return any(statement is node or node in ast.walk(statement)
               for statement in container)


def _handler_test(node: ast.AST) -> int | None:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and
            isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1):
        return None
    left, right = node.left, node.comparators[0]
    if _path(left) == "event.handler" and isinstance(right, ast.Constant):
        value = right.value
    elif _path(right) == "event.handler" and isinstance(left, ast.Constant):
        value = left.value
    else:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class _DispatchBranch:
    handler: int
    line: int
    body: tuple[ast.stmt, ...]


def _dispatch_branches(world: ast.ClassDef) -> tuple[_DispatchBranch, ...]:
    dispatch = _method(world, "_dispatch")
    roots = [statement for statement in dispatch.body
             if isinstance(statement, ast.If)]
    if len(roots) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR005", "_dispatch must contain one if/elif root")
    result: list[_DispatchBranch] = []
    cursor = roots[0]
    while True:
        handler = _handler_test(cursor.test)
        if handler is None:
            break
        result.append(_DispatchBranch(
            handler, cursor.lineno, tuple(cursor.body)))
        if len(cursor.orelse) != 1 or not isinstance(cursor.orelse[0], ast.If):
            break
        cursor = cursor.orelse[0]
    if not result or len({item.handler for item in result}) != len(result):
        raise FrameRecordReachabilityError(
            "PZFRR005", "dispatch handler chain is empty or duplicated")
    return tuple(result)


def _walk_body(body: Sequence[ast.stmt]):
    for statement in body:
        yield from ast.walk(statement)


def _pending_constructor_calls(
        branch: _DispatchBranch, enemy_classes: frozenset[str],
        ) -> tuple[tuple[str, ast.Call], ...]:
    result: list[tuple[str, ast.Call]] = []
    seen: set[int] = set()
    for node in _walk_body(branch.body):
        if id(node) in seen or not isinstance(node, ast.Call):
            continue
        seen.add(id(node))
        if not (_path(node.func) in ("self.pending.append",
                                     "world.pending.append") and
                len(node.args) == 1 and isinstance(node.args[0], ast.Call) and
                isinstance(node.args[0].func, ast.Name)):
            continue
        constructor = node.args[0]
        name = constructor.func.id
        if name in enemy_classes:
            result.append((name, constructor))
    return tuple(result)


def _eval_expr(node: ast.AST, env: Mapping[str, int], rom_word) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if _path(node) == "event.command":
        return env["event.command"]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_expr(node.operand, env, rom_word)
    if isinstance(node, ast.BinOp):
        left = _eval_expr(node.left, env, rom_word)
        right = _eval_expr(node.right, env, rom_word)
        operations = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.BitAnd: lambda a, b: a & b,
            ast.BitOr: lambda a, b: a | b,
            ast.LShift: lambda a, b: a << b,
            ast.RShift: lambda a, b: a >> b,
        }
        operation = operations.get(type(node.op))
        if operation is not None:
            return operation(left, right)
    if (isinstance(node, ast.Call) and _path(node.func) == "self.rom.word" and
            len(node.args) == 1 and not node.keywords):
        return rom_word(_eval_expr(node.args[0], env, rom_word))
    raise FrameRecordReachabilityError(
        "PZFRR006", f"unsupported transition expression: {ast.unparse(node)}")


def _transition_branch(
        branches: Sequence[_DispatchBranch],
        ) -> tuple[_DispatchBranch, ast.AST]:
    matches: list[tuple[_DispatchBranch, ast.AST]] = []
    for branch in branches:
        for node in _walk_body(branch.body):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Tuple):
                    continue
                paths = tuple(_path(item) for item in target.elts)
                if paths != ("self.event_pointer", "self.event_last"):
                    continue
                value = node.value
                if not (isinstance(value, ast.Subscript) and
                        _path(value.value) == "STAGE_EVENT_RANGES"):
                    raise FrameRecordReachabilityError(
                        "PZFRR006", "event reset is not STAGE_EVENT_RANGES[index]")
                matches.append((branch, value.slice))
    if len(matches) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR006", f"expected one stage transition reset, got {len(matches)}")
    return matches[0]


def _transition_target(
        branch: _DispatchBranch, target_expr: ast.AST, command: int, rom_word,
        ) -> int:
    env: dict[str, int] = {"event.command": command}
    target_line = max(
        node.lineno for node in _walk_body(branch.body)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and
        any(isinstance(target, ast.Tuple) and
            tuple(_path(item) for item in target.elts) ==
            ("self.event_pointer", "self.event_last")
            for target in (node.targets if isinstance(node, ast.Assign)
                           else [node.target])))
    assignments = sorted(
        (node for node in _walk_body(branch.body)
         if isinstance(node, (ast.Assign, ast.AnnAssign)) and
         node.lineno < target_line), key=lambda item: item.lineno)
    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        try:
            env[targets[0].id] = _eval_expr(node.value, env, rom_word)
        except FrameRecordReachabilityError:
            # Sound/resource assignments in the same branch are irrelevant
            # to the expression selecting STAGE_EVENT_RANGES.
            continue
    return _eval_expr(target_expr, env, rom_word)


def _event_graph(
        tree: ast.Module, game_tree: ast.Module, root: Path,
        branches: Sequence[_DispatchBranch],
        ) -> tuple[dict[str, object], dict[int, int], dict[int, int],
                   dict[int, int], bytes]:
    ranges = _literal(tree, "STAGE_EVENT_RANGES")
    base = _literal(tree, "ES_FILE_BASE")
    dispatch_table = _literal(tree, "DISPATCH_TABLE")
    if (not isinstance(ranges, dict) or not ranges or
            not isinstance(base, int) or not isinstance(dispatch_table, int)):
        raise FrameRecordReachabilityError(
            "PZFRR007", "event constants are not finite integers/ranges")
    rom_path = _rom_path(tree, root)
    rom = rom_path.read_bytes()

    def word(address: int) -> int:
        offset = base + (address & 0xFFFF)
        if offset < 0 or offset + 2 > len(rom):
            raise FrameRecordReachabilityError(
                "PZFRR007", f"ROM word ${address & 0xFFFF:04X} is out of range")
        return struct.unpack_from("<H", rom, offset)[0]

    records: list[tuple[int, int, int, int]] = []
    addresses: set[int] = set()
    stage_record_counts: dict[int, int] = {}
    handler_counts: dict[int, int] = {}
    handler_counts_by_stage: dict[int, dict[int, int]] = {}
    for raw_stage, pair in sorted(ranges.items()):
        if (isinstance(raw_stage, bool) or not isinstance(raw_stage, int) or
                not isinstance(pair, tuple) or len(pair) != 2 or
                any(isinstance(value, bool) or not isinstance(value, int)
                    for value in pair)):
            raise FrameRecordReachabilityError(
                "PZFRR007", "invalid STAGE_EVENT_RANGES entry")
        first, last = pair
        if last < first or (last - first) % 4:
            raise FrameRecordReachabilityError(
                "PZFRR007", f"stage {raw_stage} range is not 4-byte aligned")
        count = 0
        per_stage: dict[int, int] = {}
        for address in range(first, last + 1, 4):
            if address in addresses:
                raise FrameRecordReachabilityError(
                    "PZFRR007", "stage event ranges overlap")
            addresses.add(address)
            threshold = word(address)
            command = word(address + 2)
            handler = word(dispatch_table + ((command >> 9) & 0x7E))
            records.append((raw_stage, address, command, handler))
            handler_counts[handler] = handler_counts.get(handler, 0) + 1
            per_stage[handler] = per_stage.get(handler, 0) + 1
            count += 1
        stage_record_counts[raw_stage] = count
        handler_counts_by_stage[raw_stage] = per_stage

    transition, target_expr = _transition_branch(branches)
    edges: dict[int, int] = {}
    transition_commands: dict[int, int] = {}
    for stage, _address, command, handler in records:
        if handler != transition.handler:
            continue
        if stage in edges:
            raise FrameRecordReachabilityError(
                "PZFRR008", f"stage {stage} has multiple cursor resets")
        target = _transition_target(transition, target_expr, command, word)
        if target not in ranges:
            raise FrameRecordReachabilityError(
                "PZFRR008", f"stage {stage} transitions outside the table")
        edges[stage] = target
        transition_commands[stage] = command

    def visit(stage: int, visiting: frozenset[int], done: set[int]) -> None:
        if stage in visiting:
            raise FrameRecordReachabilityError(
                "PZFRR008", f"stage transition cycle reaches {stage}")
        if stage in done:
            return
        if stage in edges:
            visit(edges[stage], visiting | {stage}, done)
        done.add(stage)

    done: set[int] = set()
    for stage in ranges:
        visit(stage, frozenset(), done)

    world = _class(tree, "M72EnemyWorld")
    cursor_sites: list[tuple[int, str]] = []
    for node in ast.walk(world):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_path(target) == "self.event_pointer" for target in targets):
                cursor_sites.append((node.lineno, "initialize"))
            if any(isinstance(target, ast.Tuple) and
                   tuple(_path(item) for item in target.elts) ==
                   ("self.event_pointer", "self.event_last")
                   for target in targets):
                cursor_sites.append((node.lineno, "stage-reset"))
        elif (isinstance(node, ast.AugAssign) and
              _path(node.target) == "self.event_pointer"):
            if not (isinstance(node.op, ast.Add) and
                    isinstance(node.value, ast.Constant) and node.value.value == 4):
                raise FrameRecordReachabilityError(
                    "PZFRR009", "event cursor step is not literal +4")
            cursor_sites.append((node.lineno, "advance-four"))
    kinds = {kind: sum(item[1] == kind for item in cursor_sites)
             for kind in ("initialize", "advance-four", "stage-reset")}
    if kinds != {"initialize": 1, "advance-four": 1, "stage-reset": 1}:
        raise FrameRecordReachabilityError(
            "PZFRR009", f"event cursor mutation inventory changed: {kinds}")

    external = []
    game_parents = _parents(game_tree)
    for node in ast.walk(game_tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any((_path(target) or "").endswith("enemy_world.event_pointer")
                   for target in targets):
            continue
        owner, function = _scope(node, game_parents)
        external.append((node, owner, function))
    if len(external) != 1 or external[0][2] is None:
        raise FrameRecordReachabilityError(
            "PZFRR009", "active Game event-pointer mutation inventory changed")
    assignment, _owner, function = external[0]
    new_world_lines = sorted(
        node.lineno for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and
        any((_path(target) or "").endswith("self.enemy_world")
            for target in (node.targets if isinstance(node, ast.Assign)
                           else [node.target])) and
        isinstance(node.value, ast.Call) and
        _path(node.value.func) == "M72EnemyWorld")
    if len(new_world_lines) != 1 or new_world_lines[0] >= assignment.lineno:
        raise FrameRecordReachabilityError(
            "PZFRR009", "checkpoint cursor mutation is not on a fresh world")

    return ({
        "scope": "one active M72EnemyWorld instance",
        "stage_record_counts": {
            str(stage): count for stage, count in sorted(stage_record_counts.items())
        },
        "total_distinct_event_records": len(records),
        "transition_handler": transition.handler,
        "transition_edges": {
            str(stage): target for stage, target in sorted(edges.items())
        },
        "transition_commands": {
            str(stage): command
            for stage, command in sorted(transition_commands.items())
        },
        "acyclic": True,
        "cursor_mutations": [
            {"line": line, "kind": kind} for line, kind in sorted(cursor_sites)
        ],
        "checkpoint_cursor_targets_fresh_world": True,
        "rom_path": rom_path.relative_to(root).as_posix(),
        "rom_sha256": _sha256(rom),
    }, handler_counts, {item.handler: item.line for item in branches},
            {stage: sum(handler_counts_by_stage[stage].values())
             for stage in handler_counts_by_stage}, rom)


def _literal_iterable_length(node: ast.AST) -> int:
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return len(node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ("enumerate", "reversed") and len(node.args) == 1:
            return _literal_iterable_length(node.args[0])
        if node.func.id == "range" and 1 <= len(node.args) <= 3:
            try:
                values = [ast.literal_eval(argument) for argument in node.args]
            except (TypeError, ValueError) as exc:
                raise FrameRecordReachabilityError(
                    "PZFRR010", "spawn range is not literal") from exc
            if any(isinstance(value, bool) or not isinstance(value, int)
                   for value in values):
                raise FrameRecordReachabilityError(
                    "PZFRR010", "spawn range is not integer-valued")
            return len(range(*values))
    raise FrameRecordReachabilityError(
        "PZFRR010", f"spawn iterable is not finite: {ast.unparse(node)}")


def _expression_target_calls(node: ast.AST | None, target: str) -> int:
    if node is None:
        return 0
    return sum(isinstance(item, ast.Call) and
               isinstance(item.func, ast.Name) and item.func.id == target
               for item in ast.walk(node))


def _block_target_bound(statements: Sequence[ast.stmt], target: str) -> int:
    total = 0
    for statement in statements:
        if isinstance(statement, ast.If):
            total += _expression_target_calls(statement.test, target)
            total += max(_block_target_bound(statement.body, target),
                         _block_target_bound(statement.orelse, target))
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            cardinality = _literal_iterable_length(statement.iter)
            total += _expression_target_calls(statement.iter, target)
            total += cardinality * _block_target_bound(statement.body, target)
            total += _block_target_bound(statement.orelse, target)
        elif isinstance(statement, ast.While):
            if (_expression_target_calls(statement.test, target) or
                    _block_target_bound(statement.body, target) or
                    _block_target_bound(statement.orelse, target)):
                raise FrameRecordReachabilityError(
                    "PZFRR010", f"{target} constructor occurs in while loop")
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            total += sum(_expression_target_calls(item.context_expr, target)
                         for item in statement.items)
            total += _block_target_bound(statement.body, target)
        elif isinstance(statement, ast.Try):
            # Sum is conservative: a try body and at most one handler run,
            # but the looser finite sum avoids encoding exception semantics.
            total += _block_target_bound(statement.body, target)
            total += sum(_block_target_bound(handler.body, target)
                         for handler in statement.handlers)
            total += _block_target_bound(statement.orelse, target)
            total += _block_target_bound(statement.finalbody, target)
        else:
            total += _expression_target_calls(statement, target)
    return total


def _guard_value(node: ast.AST) -> tuple[str, object] | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        path = _path(node.operand)
        if path is not None and path.startswith("self."):
            return path[5:], False
    path = _path(node)
    if path is not None and path.startswith("self."):
        return path[5:], True
    if (isinstance(node, ast.Compare) and len(node.ops) == 1 and
            len(node.comparators) == 1 and isinstance(node.ops[0], ast.Eq)):
        left, right = node.left, node.comparators[0]
        left_path, right_path = _path(left), _path(right)
        if (left_path is not None and left_path.startswith("self.") and
                isinstance(right, ast.Constant)):
            return left_path[5:], right.value
        if (right_path is not None and right_path.startswith("self.") and
                isinstance(left, ast.Constant)):
            return right_path[5:], left.value
    return None


def _assigned_literal(node: ast.AST, path: str) -> object:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _MISSING
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if not any(_path(target) == path for target in targets):
        return _MISSING
    try:
        return ast.literal_eval(node.value)
    except (TypeError, ValueError):
        return _MISSING


def _assigns_path(node: ast.AST, path: str) -> bool:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(_path(target) == path for target in targets)
    return isinstance(node, ast.AugAssign) and _path(node.target) == path


def _audit_literal_state_field(owner: ast.ClassDef, field: str) -> None:
    path = f"self.{field}"
    for node in ast.walk(owner):
        if _assigns_path(node, path) and _assigned_literal(node, path) is _MISSING:
            raise FrameRecordReachabilityError(
                "PZFRR011", f"{owner.name}.{field} has a non-literal mutation")
        if not (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name) and node.func.id == "setattr" and
                len(node.args) >= 2 and _path(node.args[0]) == "self"):
            continue
        try:
            target_field = ast.literal_eval(node.args[1])
        except (TypeError, ValueError):
            target_field = _MISSING
        if target_field is _MISSING or target_field == field:
            raise FrameRecordReachabilityError(
                "PZFRR011", f"{owner.name}.{field} may be mutated by setattr")


def _prove_one_shot_method(
        owner: ast.ClassDef, method: ast.FunctionDef,
        parents: Mapping[ast.AST, ast.AST],
        ) -> dict[str, object]:
    invocations = [
        node for node in ast.walk(owner)
        if isinstance(node, ast.Call) and
        _path(node.func) == f"self.{method.name}"
    ]
    if len(invocations) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"{owner.name}.{method.name} has {len(invocations)} calls")
    invocation = invocations[0]
    call_owner, caller = _scope(invocation, parents)
    if call_owner is not owner or caller is None:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"cannot locate {owner.name}.{method.name} caller")
    cursor: ast.AST = invocation
    guard: tuple[str, object] | None = None
    while cursor in parents and cursor is not caller:
        cursor = parents[cursor]
        if isinstance(cursor, (ast.For, ast.AsyncFor, ast.While)):
            raise FrameRecordReachabilityError(
                "PZFRR011", f"{owner.name}.{method.name} call is looped")
        if isinstance(cursor, ast.If) and _contains(cursor.body, invocation):
            candidate = _guard_value(cursor.test)
            if candidate is not None:
                guard = candidate
                break
    if guard is None:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"{owner.name}.{method.name} has no literal guard")
    field, entry_value = guard
    _audit_literal_state_field(owner, field)
    init = _method(owner, "__init__")
    initial = [
        _assigned_literal(node, f"self.{field}") for node in ast.walk(init)
        if _assigned_literal(node, f"self.{field}") is not _MISSING
    ]
    if initial != [entry_value]:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"{owner.name}.{field} initial guard value changed")
    posts = [
        _assigned_literal(statement, f"self.{field}")
        for statement in method.body
        if _assigned_literal(statement, f"self.{field}") is not _MISSING
    ]
    if len(posts) != 1 or posts[0] == entry_value:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"{owner.name}.{method.name} does not close its guard")
    resets = []
    for function in (item for item in owner.body
                     if isinstance(item, ast.FunctionDef) and item is not init):
        for node in ast.walk(function):
            if _assigned_literal(node, f"self.{field}") == entry_value:
                resets.append((function.name, node.lineno))
    if resets:
        raise FrameRecordReachabilityError(
            "PZFRR011", f"{owner.name}.{field} resets its one-shot guard")
    return {
        "owner_class": owner.name,
        "method": method.name,
        "caller": caller.name,
        "call_line": invocation.lineno,
        "guard_field": field,
        "guard_entry_value": entry_value,
        "guard_closed_value": posts[0],
        "method_ast_sha256": _ast_sha256(method),
    }


def _constructor_bounds(
        tree: ast.Module, branches: Sequence[_DispatchBranch],
        handler_counts: Mapping[int, int], enemy_classes: frozenset[str],
        ) -> tuple[dict[str, int], list[dict[str, object]],
                   dict[int, tuple[int, str]]]:
    parents = _parents(tree)
    direct_nodes: dict[int, tuple[int, str]] = {}
    direct_totals: dict[str, int] = {}
    for branch in branches:
        for name, constructor in _pending_constructor_calls(
                branch, enemy_classes):
            direct_nodes[id(constructor)] = (branch.handler, name)
            direct_totals[name] = (
                direct_totals.get(name, 0) + handler_counts.get(branch.handler, 0))

    sites: dict[str, list[ast.Call]] = {name: [] for name in enemy_classes}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                node.func.id in enemy_classes):
            sites[node.func.id].append(node)

    bounds: dict[str, int] = {}
    for name, nodes in sites.items():
        if nodes and all(id(node) in direct_nodes for node in nodes):
            bounds[name] = direct_totals.get(name, 0)

    one_shot_reports: dict[tuple[str, str], dict[str, object]] = {}
    changed = True
    while changed:
        changed = False
        for name, nodes in sites.items():
            if name in bounds or not nodes:
                continue
            total = direct_totals.get(name, 0)
            groups: dict[tuple[str, str], tuple[ast.ClassDef, ast.FunctionDef]] = {}
            supported = True
            for node in nodes:
                if id(node) in direct_nodes:
                    continue
                owner, method = _scope(node, parents)
                if owner is None or method is None or owner.name not in bounds:
                    supported = False
                    break
                groups[(owner.name, method.name)] = (owner, method)
            if not supported or not groups:
                continue
            try:
                contributions = 0
                for key, (owner, method) in groups.items():
                    report = one_shot_reports.get(key)
                    if report is None:
                        report = _prove_one_shot_method(owner, method, parents)
                        one_shot_reports[key] = report
                    per_parent = _block_target_bound(method.body, name)
                    if per_parent <= 0:
                        raise FrameRecordReachabilityError(
                            "PZFRR012", f"lost constructor {name} in {key}")
                    contributions += bounds[owner.name] * per_parent
                total += contributions
            except FrameRecordReachabilityError:
                continue
            bounds[name] = total
            changed = True

    return bounds, [one_shot_reports[key]
                    for key in sorted(one_shot_reports)], direct_nodes


def _pending_linearity(
        tree: ast.Module, enemy_classes: frozenset[str],
        ) -> dict[str, object]:
    """Prove that pending append sites publish fresh object identities once."""
    parents = _parents(tree)
    if any(isinstance(item, ast.FunctionDef) and item.name == "__new__"
           for name in enemy_classes
           for item in _class(tree, name).body):
        raise FrameRecordReachabilityError(
            "PZFRR012", "Enemy subclass overrides identity construction")
    append_sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and
        _path(node.func) in ("self.pending.append", "world.pending.append")
    ]
    direct: list[tuple[int, str]] = []
    indirect_groups: dict[
        tuple[int, str], tuple[ast.FunctionDef, list[ast.Call]]] = {}
    for call in append_sites:
        if len(call.args) != 1 or call.keywords:
            raise FrameRecordReachabilityError(
                "PZFRR012", f"pending append signature changed at {call.lineno}")
        argument = call.args[0]
        if (isinstance(argument, ast.Call) and
                isinstance(argument.func, ast.Name) and
                argument.func.id in enemy_classes):
            direct.append((call.lineno, argument.func.id))
            continue
        argument_path = _path(argument)
        owner, function = _scope(call, parents)
        if argument_path is None or function is None:
            raise FrameRecordReachabilityError(
                "PZFRR012", f"pending append is not fresh at {call.lineno}")
        key = (id(function), argument_path)
        if key not in indirect_groups:
            indirect_groups[key] = (function, [])
        indirect_groups[key][1].append(call)

    indirect: list[dict[str, object]] = []
    for (_function_id, argument_path), (function, calls) in indirect_groups.items():
        definitions: list[tuple[int, str]] = []
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(_path(target) == argument_path for target in targets):
                    continue
                value = node.value
                if not (isinstance(value, ast.Call) and
                        isinstance(value.func, ast.Name) and
                        value.func.id in enemy_classes):
                    raise FrameRecordReachabilityError(
                        "PZFRR012", f"{function.name}.{argument_path} is not "
                        "always freshly constructed")
                definitions.append((node.lineno, value.func.id))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                if _path(node.target) != argument_path:
                    continue
                iterable = node.iter
                if not isinstance(iterable, (ast.Tuple, ast.List)):
                    raise FrameRecordReachabilityError(
                        "PZFRR012", f"{function.name}.{argument_path} loop "
                        "source is not a finite fresh-constructor tuple")
                constructors = []
                for element in iterable.elts:
                    if not (isinstance(element, ast.Call) and
                            isinstance(element.func, ast.Name) and
                            element.func.id in enemy_classes):
                        raise FrameRecordReachabilityError(
                            "PZFRR012", f"{function.name}.{argument_path} loop "
                            "contains a non-constructor identity")
                    constructors.append(element.func.id)
                definitions.append((node.lineno, "|".join(constructors)))
        if not definitions or len(calls) > len(definitions):
            raise FrameRecordReachabilityError(
                "PZFRR012", f"{function.name}.{argument_path} may be appended "
                "more than once per fresh definition")
        for call in calls:
            if not any(line <= call.lineno for line, _name in definitions):
                raise FrameRecordReachabilityError(
                    "PZFRR012", f"{function.name}.{argument_path} append "
                    "precedes its fresh definition")
        indirect.append({
            "function": function.name,
            "argument": argument_path,
            "append_lines": sorted(call.lineno for call in calls),
            "fresh_definition_lines": sorted(line for line, _name in definitions),
            "constructor_classes": sorted({
                name for _line, joined in definitions for name in joined.split("|")
            }),
        })

    inventory = {
        "pending_append_site_count": len(append_sites),
        "direct_fresh_constructor_sites": [
            {"line": line, "class_name": name}
            for line, name in sorted(direct)
        ],
        "local_fresh_identity_sites": sorted(
            indirect, key=lambda item: (str(item["function"]), str(item["argument"]))),
        "duplicate_publication_rejected": True,
    }
    inventory["inventory_sha256"] = _sha256(json.dumps(
        inventory, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return inventory


def _audit_premium_constructor_references(
        tree: ast.Module, names: frozenset[str],
        ) -> str:
    """Reject aliases/subclasses which could bypass constructor accounting."""
    parents = _parents(tree)
    inventory: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id not in names:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            inventory.append((node.lineno, node.id, "constructor"))
            continue

        cursor: ast.AST = node
        annotation = False
        type_check = False
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, ast.AnnAssign) and node in ast.walk(cursor.annotation):
                annotation = True
                break
            if isinstance(cursor, ast.arg) and cursor.annotation is not None and (
                    node is cursor.annotation or node in ast.walk(cursor.annotation)):
                annotation = True
                break
            if isinstance(cursor, ast.Call):
                if (isinstance(cursor.func, ast.Name) and
                        cursor.func.id == "isinstance" and len(cursor.args) >= 2 and
                        (node is cursor.args[1] or node in ast.walk(cursor.args[1]))):
                    type_check = True
                break
            if isinstance(cursor, (ast.stmt, ast.ClassDef, ast.FunctionDef)):
                break
        if annotation:
            inventory.append((node.lineno, node.id, "annotation"))
        elif type_check:
            inventory.append((node.lineno, node.id, "isinstance"))
        else:
            raise FrameRecordReachabilityError(
                "PZFRR012", f"unaccounted reference to premium class "
                f"{node.id} at line {node.lineno}")
    encoded = json.dumps(sorted(inventory), separators=(",", ":")).encode("utf-8")
    return _sha256(encoded)


def _entry_exclusion(method: ast.FunctionDef, field: str) -> object:
    for statement in method.body:
        if not isinstance(statement, ast.If):
            continue
        if not any(isinstance(node, ast.Return) for node in statement.body):
            continue
        test = statement.test
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and
                len(test.comparators) == 1):
            continue
        left, right = test.left, test.comparators[0]
        if _path(left) != f"self.{field}" or not isinstance(right, ast.Constant):
            continue
        if isinstance(test.ops[0], (ast.NotEq, ast.IsNot)):
            return right.value
    return _MISSING


def _enclosing_state_guard(
        node: ast.AST, method: ast.FunctionDef, field: str,
        parents: Mapping[ast.AST, ast.AST],
        ) -> object:
    cursor = node
    while cursor in parents and cursor is not method:
        cursor = parents[cursor]
        if not isinstance(cursor, ast.If) or not _contains(cursor.body, node):
            continue
        guard = _guard_value(cursor.test)
        if guard is not None and guard[0] == field:
            return guard[1]
    return _entry_exclusion(method, field)


def _direct_emitter_one_shot(
        owner: ast.ClassDef, method: ast.FunctionDef, emitter: ast.Call,
        parents: Mapping[ast.AST, ast.AST],
        ) -> dict[str, object]:
    candidates: list[tuple[str, object, ast.AST]] = []
    for node in ast.walk(method):
        if getattr(node, "lineno", -1) <= emitter.lineno:
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            path = _path(target)
            if path is None or not path.startswith("self."):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                continue
            candidates.append((path[5:], value, node))
    for field, post, transition in candidates:
        pre = _entry_exclusion(method, field)
        if pre is _MISSING or pre == post:
            continue
        _audit_literal_state_field(owner, field)
        graph: dict[object, set[object]] = {}
        unknown_to_pre = False
        init = _method(owner, "__init__")
        for function in (item for item in owner.body
                         if isinstance(item, ast.FunctionDef) and item is not init):
            for node in ast.walk(function):
                target = _assigned_literal(node, f"self.{field}")
                if target is _MISSING:
                    continue
                source = _enclosing_state_guard(node, function, field, parents)
                if source is _MISSING:
                    if target == pre:
                        unknown_to_pre = True
                    continue
                graph.setdefault(source, set()).add(target)
        if unknown_to_pre:
            continue
        reachable = {post}
        work = [post]
        while work:
            source = work.pop()
            for target in graph.get(source, ()):
                if target not in reachable:
                    reachable.add(target)
                    work.append(target)
        if pre in reachable:
            continue
        return {
            "owner_class": owner.name,
            "method": method.name,
            "emit_line": emitter.lineno,
            "guard_field": field,
            "entry_value": pre,
            "closed_value": post,
            "state_edges": {
                repr(source): sorted((repr(item) for item in targets))
                for source, targets in sorted(graph.items(), key=lambda item: repr(item[0]))
            },
            "method_ast_sha256": _ast_sha256(method),
        }
    raise FrameRecordReachabilityError(
        "PZFRR013", f"transient site {owner.name}.{method.name}:{emitter.lineno} "
        "has no closed one-shot state transition")


def _transient_bound(
        tree: ast.Module, instance_bounds: Mapping[str, int],
        ) -> dict[str, object]:
    parents = _parents(tree)
    world = _class(tree, "M72EnemyWorld")
    update = _method(world, "update")
    clear_sites = [
        node for node in ast.walk(update)
        if isinstance(node, ast.Call) and
        _path(node.func) == "self.transient_sprites.clear"
    ]
    append_sites = [
        node for node in ast.walk(world)
        if isinstance(node, ast.Call) and
        _path(node.func) == "self.transient_sprites.append"
    ]
    other_mutations = [
        node for node in ast.walk(world)
        if isinstance(node, ast.Call) and
        (_path(node.func) or "").startswith("self.transient_sprites.") and
        _path(node.func) not in (
            "self.transient_sprites.clear", "self.transient_sprites.append")
    ]
    if len(clear_sites) != 1 or len(append_sites) != 1 or other_mutations:
        raise FrameRecordReachabilityError(
            "PZFRR013", "transient list clear/append mutation inventory changed")
    emitter_method = _method(world, "emit_transient_sprite")
    if not (append_sites[0] in ast.walk(emitter_method) and
            clear_sites[0].lineno < min(
                node.lineno for node in ast.walk(update)
                if isinstance(node, (ast.For, ast.While)) or
                (isinstance(node, ast.Call) and
                 _path(node.func) == "self._dispatch"))):
        raise FrameRecordReachabilityError(
            "PZFRR013", "transient clear no longer precedes update scheduling")
    emitters = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and
        _path(node.func) == "world.emit_transient_sprite"
    ]
    if not emitters:
        raise FrameRecordReachabilityError(
            "PZFRR013", "active source has no transient emitter")
    module_emitters: list[tuple[ast.FunctionDef, ast.Call]] = []
    direct_emitters: list[tuple[ast.ClassDef, ast.FunctionDef, ast.Call]] = []
    for emitter in emitters:
        owner, method = _scope(emitter, parents)
        if method is None:
            raise FrameRecordReachabilityError(
                "PZFRR013", "transient emitter is outside a function")
        if owner is None:
            module_emitters.append((method, emitter))
        else:
            direct_emitters.append((owner, method, emitter))
    if len(module_emitters) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR013", "expected one shared module transient helper")

    helper, helper_emit = module_emitters[0]
    enclosing = None
    cursor: ast.AST = helper_emit
    while cursor in parents and cursor is not helper:
        cursor = parents[cursor]
        if isinstance(cursor, ast.If) and _contains(cursor.body, helper_emit):
            enclosing = cursor
            break
    if enclosing is None:
        raise FrameRecordReachabilityError(
            "PZFRR013", "shared transient emitter lacks terminal branch")
    kills = [
        node for node in ast.walk(enclosing)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and
        _assigned_literal(node, "enemy.alive") is False and
        node.lineno > helper_emit.lineno
    ]
    if len(kills) != 1:
        raise FrameRecordReachabilityError(
            "PZFRR013", "shared transient helper does not kill its owner once")

    helper_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
        node.func.id == helper.name
    ]
    helper_owners: set[str] = set()
    helper_sites: list[dict[str, object]] = []
    for call in helper_calls:
        owner, method = _scope(call, parents)
        if owner is None or method is None or method.name != "update":
            raise FrameRecordReachabilityError(
                "PZFRR013", "shared transient helper has a non-update caller")
        helper_owners.add(owner.name)
        helper_sites.append({
            "owner_class": owner.name, "method": method.name,
            "line": call.lineno,
        })

    per_instance: dict[str, int] = {name: 1 for name in helper_owners}
    direct_reports: list[dict[str, object]] = []
    for owner, method, emitter in direct_emitters:
        direct_reports.append(
            _direct_emitter_one_shot(owner, method, emitter, parents))
        per_instance[owner.name] = per_instance.get(owner.name, 0) + 1

    missing = sorted(name for name in per_instance if name not in instance_bounds)
    if missing:
        raise FrameRecordReachabilityError(
            "PZFRR014", "transient owner instance bound is missing: " +
            ", ".join(missing))
    contributions = {
        name: instance_bounds[name] * emissions
        for name, emissions in sorted(per_instance.items())
    }
    finite = sum(contributions.values())
    if finite <= 0:
        raise FrameRecordReachabilityError(
            "PZFRR014", "derived transient upper bound is not positive")
    return {
        "producer_site_count": len(emitters),
        "clear_line": clear_sites[0].lineno,
        "emitter_append_line": append_sites[0].lineno,
        "list_mutation_inventory_closed": True,
        "shared_helper": helper.name,
        "shared_helper_ast_sha256": _ast_sha256(helper),
        "shared_helper_emit_line": helper_emit.lineno,
        "shared_helper_kills_owner": True,
        "shared_helper_callers": sorted(
            helper_sites, key=lambda item: (str(item["owner_class"]), int(item["line"]))),
        "direct_one_shot_proofs": sorted(
            direct_reports, key=lambda item: int(item["emit_line"])),
        "lifetime_emissions_per_instance": per_instance,
        "lifetime_instance_upper_bounds": {
            name: instance_bounds[name] for name in sorted(per_instance)
        },
        "lifetime_emission_contributions": contributions,
        "finite_per_frame_upper_bound": finite,
        "derivation": (
            "the list is cleared at update entry; a whole-world cumulative "
            "one-shot emission bound is therefore also a per-frame bound"),
        "exact_simultaneous_maximum": None,
    }


def analyze_frame_record_reachability(
        project_root: Path | str, *, enemy_source: str,
        game_source: str, pool_record_capacity: int,
        class_multiplicities: Mapping[str, int],
        pool_invariant_sha256: str,
        ) -> FrameRecordReachabilityReport:
    """Prove a conservative finite frame bound from active source and ROM.

    ``pool_record_capacity`` and ``class_multiplicities`` are not configuration
    constants.  The parent analyser passes its AST/IR-derived facts together
    with the hash of the pool invariant which justified them.
    """
    if (isinstance(pool_record_capacity, bool) or
            not isinstance(pool_record_capacity, int) or
            pool_record_capacity <= 0):
        raise FrameRecordReachabilityError(
            "PZFRR015", "pool_record_capacity is not a positive derived fact")
    if (not class_multiplicities or
            any(not isinstance(name, str) or isinstance(value, bool) or
                not isinstance(value, int) or value < 0
                for name, value in class_multiplicities.items())):
        raise FrameRecordReachabilityError(
            "PZFRR015", "class multiplicities are not finite derived facts")
    if len(pool_invariant_sha256) != 64:
        raise FrameRecordReachabilityError(
            "PZFRR015", "pool invariant hash is missing")

    root = Path(project_root).resolve()
    try:
        tree = ast.parse(enemy_source, filename="rtype_port/enemies.py")
        game_tree = ast.parse(game_source, filename="rtype_port/game.py")
    except SyntaxError as exc:
        raise FrameRecordReachabilityError(
            "PZFRR001", f"cannot parse active source: {exc.msg}") from exc
    enemy_classes = _enemy_classes(tree)
    source_pool_capacity = _derived_pool_capacity(tree)
    if pool_record_capacity != source_pool_capacity:
        raise FrameRecordReachabilityError(
            "PZFRR015", f"pool capacity input {pool_record_capacity} does not "
            f"match source-derived {source_pool_capacity}")
    if set(class_multiplicities) != set(enemy_classes):
        missing = sorted(enemy_classes - set(class_multiplicities))
        extra = sorted(set(class_multiplicities) - enemy_classes)
        raise FrameRecordReachabilityError(
            "PZFRR015", f"multiplicity/class graph mismatch; missing={missing}, "
            f"extra={extra}")
    world = _class(tree, "M72EnemyWorld")
    branches = _dispatch_branches(world)
    pending_linearity = _pending_linearity(tree, enemy_classes)
    event_graph, handler_counts, branch_lines, _stage_totals, _rom = (
        _event_graph(tree, game_tree, root, branches))
    bounds, one_shot_methods, direct_nodes = _constructor_bounds(
        tree, branches, handler_counts, enemy_classes)

    unbounded = sorted(enemy_classes - set(bounds))
    if not unbounded:
        baseline = 0
    else:
        baseline = max(class_multiplicities[name] for name in unbounded)
    global_multiplicity = max(class_multiplicities.values())
    premiums: list[dict[str, object]] = []
    premium_total = 0
    for name in sorted(bounds):
        multiplicity = class_multiplicities[name]
        if multiplicity <= baseline:
            continue
        premium = multiplicity - baseline
        contribution = premium * min(bounds[name], pool_record_capacity)
        premium_total += contribution
        premiums.append({
            "class_name": name,
            "records_per_instance": multiplicity,
            "lifetime_instance_upper_bound": bounds[name],
            "premium_over_baseline": premium,
            "record_bound_contribution": contribution,
        })
    if baseline >= global_multiplicity or not premiums:
        raise FrameRecordReachabilityError(
            "PZFRR016", "high-multiplicity constructors are not finitely "
            "bounded; refusing to publish a pool-only frame maximum")
    premium_reference_sha256 = _audit_premium_constructor_references(
        tree, frozenset(str(item["class_name"]) for item in premiums))
    object_bound = pool_record_capacity * baseline + premium_total
    transients = _transient_bound(tree, bounds)
    transient_bound = int(transients["finite_per_frame_upper_bound"])
    frame_bound = object_bound + transient_bound

    direct_event_bounds: list[dict[str, object]] = []
    for name in sorted(bounds):
        origins = [value for value in direct_nodes.values() if value[1] == name]
        if not origins:
            continue
        handlers = sorted({handler for handler, _name in origins})
        direct_event_bounds.append({
            "class_name": name,
            "handlers": handlers,
            "dispatch_lines": [branch_lines[handler] for handler in handlers],
            "event_record_count": sum(handler_counts.get(handler, 0)
                                      for handler in handlers),
            "lifetime_instance_upper_bound": bounds[name],
        })

    payload: dict[str, object] = {
        "format": FRAME_RECORD_REACHABILITY_FORMAT,
        "status": "PROVED_FINITE_ABSTRACT_BOUND",
        "proof_complete_for_finiteness": True,
        "proof_complete_for_conservative_certification": True,
        "proof_complete_for_exact_maximum": False,
        "source_bindings": {
            "Source/Python/rtype_port/enemies.py": _sha256(
                enemy_source.encode("utf-8")),
            "Source/Python/rtype_port/game.py": _sha256(
                game_source.encode("utf-8")),
            str(event_graph["rom_path"]): event_graph["rom_sha256"],
            "Source/Tools/pyz80_compiler/frame_record_reachability.py": (
                _sha256(Path(__file__).read_bytes())),
            "pool_invariant_ast": pool_invariant_sha256,
            "draw_ir_class_multiplicities": _sha256(json.dumps(
                dict(sorted(class_multiplicities.items())),
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")),
        },
        "event_cursor": event_graph,
        "spawn_reachability": {
            "pending_identity_linearity": pending_linearity,
            "direct_event_constructor_bounds": direct_event_bounds,
            "one_shot_spawn_methods": one_shot_methods,
            "finite_class_instance_upper_bounds": {
                name: bounds[name] for name in sorted(bounds)
            },
        },
        "object_records": {
            "pool_record_capacity": pool_record_capacity,
            "unbounded_class_baseline_records": baseline,
            "unbounded_baseline_class_count": len(unbounded),
            "bounded_premium_classes": premiums,
            "premium_constructor_reference_sha256": premium_reference_sha256,
            "base_pool_contribution": pool_record_capacity * baseline,
            "premium_contribution": premium_total,
            "finite_upper_bound": object_bound,
            "exact_maximum": None,
        },
        "transient_sprites": transients,
        "frame_records": {
            "equation": "object_record_upper_bound + transient_upper_bound",
            "bound_kind": "conservative_upper_bound",
            "finite_upper_bound": frame_bound,
            "exact_maximum": None,
            "eligible_as_exact_frame_max": False,
            "eligible_as_conservative_frame_max": True,
            "sound_for_ram_dl_and_worst_case_timing": True,
        },
        "residual_obligations": [
            {
                "code": "PZFRB101",
                "missing_invariant": (
                    "stage-local simultaneous occupancy/lifetime induction "
                    "tight enough to replace the conservative pool baseline "
                    "with the exact attainable object-record maximum"),
            },
            {
                "code": "PZFRB102",
                "missing_invariant": (
                    "same-update coincidence analysis for the already finite "
                    "one-shot transient producers, to replace the cumulative "
                    "lifetime bound with the exact simultaneous maximum"),
            },
        ],
    }
    return FrameRecordReachabilityReport(payload)
