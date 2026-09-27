#!/usr/bin/env python3
"""Fail-closed pinned-SDCC stack certificate for the compact draw VM.

The draw VM manifest exposes a *logical* expression-DAG depth.  It is not a
machine-stack measurement.  This tool regenerates the active-Python plan,
checks that the checked-in C/H/JSON files are byte exact, compiles the C with
the pinned SDCC flags, and performs stack abstract interpretation on the
emitted Z80 assembly.

Only the immutable expression DAG may bound recursion.  All other cycles must
have a stable stack depth.  Unknown direct calls, unknown indirect calls,
unsupported SP writes, or a growing stack cycle fail the certificate.

The four application callbacks are deliberately external contracts.  With no
contract file, the report gives the exact VM-internal bound up to each callback
entry and remains blocked.  A callback contract may supply
``maximum_additional_stack_bytes_from_entry_sp`` for each callback; this never
turns the report into a live-integration pass because adapter/link/timing work
is outside this certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from pyz80_compiler.draw_plan import compile_active_enemy_draw_plan
from pyz80_compiler.draw_vm_backend import (
    build_draw_vm_program,
    emit_draw_vm_backend,
)
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-vm-pinned-sdcc-stack-certificate-v1"
CALLBACK_CONTRACT_FORMAT = "pyz80-draw-vm-callback-stack-contracts-v1"
PINNED_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
)

_PREFIX = "rtype_python_draw_vm"
_FUNCTIONS = (
    f"_{_PREFIX}_object_field",
    f"_{_PREFIX}_transient_field",
    f"_{_PREFIX}_eval",
    f"_{_PREFIX}_conditions",
    f"_{_PREFIX}_input_valid",
    f"_{_PREFIX}_walk",
    f"_{_PREFIX}_emit_to_buffer",
    f"_{_PREFIX}_produce",
    f"_{_PREFIX}_stream",
)
_PUBLIC = (
    f"_{_PREFIX}_produce",
    f"_{_PREFIX}_stream",
)


class DrawVMStackError(RuntimeError):
    """The generated machine stack cannot be proved with this model."""


@dataclass(frozen=True)
class CallbackABI:
    name: str
    function: str
    indirect_ordinal: int
    stack_argument_bytes: int


_CALLBACK_ABIS = (
    CallbackABI("resolve_resource_type", f"_{_PREFIX}_eval", 0, 0),
    CallbackABI("load_object", f"_{_PREFIX}_walk", 0, 2),
    CallbackABI("resolve_bank_key", f"_{_PREFIX}_walk", 1, 2),
    CallbackABI("emit_record", f"_{_PREFIX}_walk", 2, 0),
)
_CALLBACK_BY_SITE = {
    (item.function, item.indirect_ordinal): item for item in _CALLBACK_ABIS
}


@dataclass(frozen=True)
class Instruction:
    source_line: int
    op: str
    args: str
    raw: str
    statement_index: int


@dataclass(frozen=True)
class FunctionAssembly:
    name: str
    instructions: tuple[Instruction, ...]
    label_to_instruction: Mapping[str, int]
    jump_tables: Mapping[int, tuple[int, ...]]


@dataclass(frozen=True)
class MachineState:
    depth: int
    ix_depth: int | None = None
    ix_constant: int | None = None
    iy_depth: int | None = None
    iy_constant: int | None = None


@dataclass(frozen=True)
class Peak:
    depth: int
    witness: tuple[str, ...]


@dataclass(frozen=True)
class FunctionSummary:
    name: str
    maximum_depth_from_entry_sp: int
    maximum_witness: tuple[str, ...]
    return_delta_bytes: int
    callback_entry_peaks: Mapping[str, Peak]
    bounded_recursive_edges: int
    explored_states: int


@dataclass(frozen=True)
class CallbackContract:
    maximum_additional_stack_bytes_from_entry_sp: int
    evidence: Mapping[str, object]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrawVMStackError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise DrawVMStackError(f"JSON root is not an object: {path}")
    return result


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    data = (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _normal_instruction(line: str) -> str | None:
    code = line.split(";", 1)[0].strip()
    if not code or code.startswith(".") or code.endswith(":"):
        return None
    code = re.sub(r"\s+", " ", code.lower())
    code = re.sub(r"\s*,\s*", ",", code)
    return code


def _validate_runtime_support(sdcc: Path) -> dict[str, object]:
    source_root = sdcc.parent.parent / "lib" / "src" / "z80"
    call_path = source_root / "__sdcc_call_iy.s"
    memcpy_path = source_root / "memcpy.s"
    try:
        call_bytes = call_path.read_bytes()
        memcpy_bytes = memcpy_path.read_bytes()
    except OSError as exc:
        raise DrawVMStackError(
            f"pinned SDCC runtime source is unavailable: {exc}") from exc

    call_lines = [
        item for item in (
            _normal_instruction(line)
            for line in call_bytes.decode("latin1").splitlines()
        ) if item is not None
    ]
    if call_lines != ["jp (iy)"]:
        raise DrawVMStackError(
            "___sdcc_call_iy is not the proved zero-extra-stack tail jump")

    memcpy_lines = [
        item for item in (
            _normal_instruction(line)
            for line in memcpy_bytes.decode("latin1").splitlines()
        ) if item is not None
    ]
    expected_memcpy = [
        "ex de,hl",
        "pop iy",
        "pop bc",
        "ld a,c",
        "or a,b",
        "jr z,end",
        "push de",
        "ldir",
        "pop de",
        "jp (iy)",
    ]
    if memcpy_lines != expected_memcpy:
        raise DrawVMStackError(
            "___memcpy differs from the proved sdcccall(1) stack summary")

    return {
        "indirect_tail_jump": {
            "path": call_path.as_posix(),
            "bytes": len(call_bytes),
            "sha256": _sha256(call_bytes),
            "symbol": "___sdcc_call_iy",
            "maximum_additional_stack_bytes_from_entry_sp": 0,
            "return_delta_bytes": "callback-defined",
            "proved_body": ["jp (iy)"],
        },
        "memcpy": {
            "path": memcpy_path.as_posix(),
            "bytes": len(memcpy_bytes),
            "sha256": _sha256(memcpy_bytes),
            "symbols": ["_memcpy", "___memcpy"],
            "maximum_additional_stack_bytes_from_entry_sp": 0,
            "return_delta_bytes": -4,
            "stack_argument_bytes": 2,
        },
    }


def _parse_int(text: str) -> int | None:
    value = text.strip().lower()
    value = value[1:] if value.startswith("#") else value
    try:
        return int(value, 0)
    except ValueError:
        return None


def _split_op(line: str) -> tuple[str, str] | None:
    code = line.split(";", 1)[0].strip()
    if not code or code.startswith("."):
        return None
    match = re.match(r"([A-Za-z][A-Za-z0-9_.]*)\s*(.*)$", code)
    if match is None:
        return None
    args = match.group(2).strip().lower()
    args = re.sub(r"\s*,\s*", ",", args)
    return match.group(1).lower(), args


def parse_sdcc_assembly(text: str) -> dict[str, FunctionAssembly]:
    """Parse just enough ASxxxx syntax to prove stack behaviour.

    The accepted subset is intentionally small.  A compiler code-generation
    change therefore blocks the certificate instead of silently weakening it.
    """
    lines = text.splitlines()
    starts: dict[str, int] = {}
    for number, line in enumerate(lines):
        match = re.match(r"\s*([_A-Za-z0-9.][\w.$]*):{1,2}\s*$", line)
        if match is not None and match.group(1) in _FUNCTIONS:
            starts[match.group(1)] = number
    missing = sorted(set(_FUNCTIONS) - set(starts))
    if missing:
        raise DrawVMStackError(
            f"pinned SDCC assembly lacks functions: {missing}")

    ordered = sorted((line, name) for name, line in starts.items())
    result: dict[str, FunctionAssembly] = {}
    for ordinal, (start, name) in enumerate(ordered):
        stop = ordered[ordinal + 1][0] if ordinal + 1 < len(ordered) else len(lines)
        statements: list[tuple[str, int, str]] = []
        for line_index in range(start, stop):
            raw = lines[line_index]
            code = raw.split(";", 1)[0].strip()
            if not code:
                continue
            label_match = re.match(
                r"([_A-Za-z0-9.][\w.$]*):{1,2}\s*(.*)$", code)
            if label_match is not None:
                statements.append(("label", line_index + 1,
                                   label_match.group(1)))
                code = label_match.group(2).strip()
                if not code:
                    continue
            if code.startswith("."):
                statements.append(("directive", line_index + 1, code))
                continue
            parsed = _split_op(code)
            if parsed is None:
                raise DrawVMStackError(
                    f"cannot parse assembly line {line_index + 1}: {raw}")
            statements.append((
                "instruction", line_index + 1,
                parsed[0] + (" " + parsed[1] if parsed[1] else ""),
            ))

        instructions: list[Instruction] = []
        statement_to_instruction: dict[int, int] = {}
        for statement_index, (kind, source_line, value) in enumerate(statements):
            if kind != "instruction":
                continue
            op, _, args = value.partition(" ")
            statement_to_instruction[statement_index] = len(instructions)
            instructions.append(Instruction(
                source_line=source_line,
                op=op,
                args=args,
                raw=value,
                statement_index=statement_index,
            ))

        def next_instruction(statement_index: int) -> int | None:
            for index in range(statement_index, len(statements)):
                found = statement_to_instruction.get(index)
                if found is not None:
                    return found
            return None

        labels: dict[str, int] = {}
        for statement_index, (kind, source_line, value) in enumerate(statements):
            if kind != "label":
                continue
            target = next_instruction(statement_index + 1)
            if target is None:
                continue
            if value in labels:
                raise DrawVMStackError(
                    f"duplicate label {value} in {name} at {source_line}")
            labels[value] = target

        jump_tables: dict[int, tuple[int, ...]] = {}
        for index, instruction in enumerate(instructions):
            if instruction.op != "jp" or instruction.args != "(hl)":
                continue
            table_labels: list[str] = []
            cursor = instruction.statement_index + 1
            while cursor < len(statements):
                kind, _, value = statements[cursor]
                if kind == "instruction":
                    break
                if kind == "directive" and value.lower().startswith(".dw"):
                    operands = value[3:].strip().split(",")
                    table_labels.extend(item.strip() for item in operands)
                cursor += 1
            if table_labels:
                targets: list[int] = []
                for label in table_labels:
                    if label not in labels:
                        raise DrawVMStackError(
                            f"jump table in {name} refers to {label!r}")
                    targets.append(labels[label])
                jump_tables[index] = tuple(targets)

        result[name] = FunctionAssembly(
            name=name,
            instructions=tuple(instructions),
            label_to_instruction=labels,
            jump_tables=jump_tables,
        )
    return result


_CONDITIONS = frozenset(("nz", "z", "nc", "c", "po", "pe", "p", "m"))


class StackAnalyzer:
    def __init__(
            self, functions: Mapping[str, FunctionAssembly],
            maximum_eval_depth: int,
            ) -> None:
        if maximum_eval_depth <= 0:
            raise DrawVMStackError("expression DAG has no positive depth bound")
        self.functions = functions
        self.maximum_eval_depth = maximum_eval_depth
        self._memo: dict[tuple[str, int], FunctionSummary] = {}
        self._active: set[tuple[str, int]] = set()

        indirect_counts: dict[str, int] = defaultdict(int)
        for name, function in functions.items():
            for instruction in function.instructions:
                if (instruction.op == "call" and
                        instruction.args == "___sdcc_call_iy"):
                    indirect_counts[name] += 1
        expected_counts: dict[str, int] = defaultdict(int)
        for item in _CALLBACK_ABIS:
            expected_counts[item.function] += 1
        if dict(indirect_counts) != dict(expected_counts):
            raise DrawVMStackError(
                "indirect callback call sites changed: "
                f"actual={dict(indirect_counts)}, expected={dict(expected_counts)}")

    @staticmethod
    def _better(left: Peak, right: Peak) -> Peak:
        if right.depth > left.depth:
            return right
        if right.depth == left.depth and right.witness < left.witness:
            return right
        return left

    @staticmethod
    def _with_depth(state: MachineState, depth: int) -> MachineState:
        return MachineState(
            depth=depth,
            ix_depth=state.ix_depth,
            ix_constant=state.ix_constant,
            iy_depth=state.iy_depth,
            iy_constant=state.iy_constant,
        )

    @staticmethod
    def _write_index_register(
            state: MachineState, register: str, constant: int | None,
            ) -> MachineState:
        if register == "ix":
            return MachineState(state.depth, None, constant,
                                state.iy_depth, state.iy_constant)
        return MachineState(state.depth, state.ix_depth, state.ix_constant,
                            None, constant)

    def _plain_effect(
            self, function: str, instruction: Instruction,
            state: MachineState,
            ) -> MachineState:
        op, args = instruction.op, instruction.args
        depth = state.depth
        if op == "push":
            depth += 2
        elif op == "pop":
            depth -= 2
            if args == "ix":
                state = MachineState(depth, None, None,
                                     state.iy_depth, state.iy_constant)
                return state
            if args == "iy":
                state = MachineState(depth, state.ix_depth, state.ix_constant,
                                     None, None)
                return state
        elif op == "inc" and args == "sp":
            depth -= 1
        elif op == "dec" and args == "sp":
            depth += 1
        elif op == "ld":
            destination, comma, source = args.partition(",")
            if comma and destination in ("ix", "iy"):
                return self._write_index_register(
                    state, destination, _parse_int(source))
            if destination == "sp":
                if source == "ix" and state.ix_depth is not None:
                    depth = state.ix_depth
                elif source == "iy" and state.iy_depth is not None:
                    depth = state.iy_depth
                else:
                    raise DrawVMStackError(
                        f"unsupported SP restore in {function}: "
                        f"line {instruction.source_line} {instruction.raw}")
        elif op == "add" and args in ("ix,sp", "iy,sp"):
            register = args[:2]
            constant = (state.ix_constant if register == "ix" else
                        state.iy_constant)
            if constant is None:
                raise DrawVMStackError(
                    f"non-affine frame setup in {function}: "
                    f"line {instruction.source_line} {instruction.raw}")
            address_depth = depth - constant
            if register == "ix":
                return MachineState(depth, address_depth, None,
                                    state.iy_depth, state.iy_constant)
            return MachineState(depth, state.ix_depth, state.ix_constant,
                                address_depth, None)
        elif re.search(r"\bsp\b", args):
            allowed = (
                op == "add" and args.endswith(",sp") or
                op == "ex" and "(sp)" in args
            )
            if not allowed:
                raise DrawVMStackError(
                    f"unsupported SP operation in {function}: "
                    f"line {instruction.source_line} {instruction.raw}")
        return self._with_depth(state, depth)

    @staticmethod
    def _branch_target(function: FunctionAssembly, label: str) -> int:
        target = function.label_to_instruction.get(label.strip())
        if target is None:
            raise DrawVMStackError(
                f"{function.name} branches to unresolved label {label!r}")
        return target

    def summary(self, name: str, eval_budget: int | None = None) -> FunctionSummary:
        budget = self.maximum_eval_depth if eval_budget is None else eval_budget
        key = (name, budget if name == f"_{_PREFIX}_eval" else
               self.maximum_eval_depth)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        if key in self._active:
            raise DrawVMStackError(
                f"unproved recursive call cycle at {name}, budget={budget}")
        if name not in self.functions:
            raise DrawVMStackError(f"unresolved generated call target {name}")
        self._active.add(key)
        try:
            result = self._analyze_function(name, budget)
            self._memo[key] = result
            return result
        finally:
            self._active.remove(key)

    def _analyze_function(self, name: str, eval_budget: int) -> FunctionSummary:
        function = self.functions[name]
        if not function.instructions:
            raise DrawVMStackError(f"function {name} has no instructions")
        queue: deque[tuple[int, MachineState, tuple[str, ...]]] = deque()
        queue.append((0, MachineState(0), (f"{name}:entry",)))
        seen: set[tuple[int, MachineState]] = set()
        states_per_instruction: dict[int, int] = defaultdict(int)
        exits: set[int] = set()
        peak = Peak(0, (f"{name}:entry",))
        callback_peaks: dict[str, Peak] = {}
        bounded_edges = 0
        indirect_ordinal_by_index: dict[int, int] = {}
        indirect_ordinal = 0
        for index, instruction in enumerate(function.instructions):
            if (instruction.op == "call" and
                    instruction.args == "___sdcc_call_iy"):
                indirect_ordinal_by_index[index] = indirect_ordinal
                indirect_ordinal += 1

        while queue:
            index, state, witness = queue.popleft()
            state_key = (index, state)
            if state_key in seen:
                continue
            seen.add(state_key)
            states_per_instruction[index] += 1
            if states_per_instruction[index] > 64 or len(seen) > 20000:
                raise DrawVMStackError(
                    f"growing/ambiguous stack cycle in {name} near "
                    f"assembly instruction {index}")
            if state.depth < -32 or state.depth > 4096:
                raise DrawVMStackError(
                    f"unbounded/invalid stack depth {state.depth} in {name}")

            instruction = function.instructions[index]
            location = f"{name}:asm:{instruction.source_line}:{instruction.raw}"
            peak = self._better(peak, Peak(state.depth, witness + (location,)))

            def enqueue(target: int, next_state: MachineState,
                        suffix: str | None = None) -> None:
                if target < 0 or target >= len(function.instructions):
                    raise DrawVMStackError(
                        f"control flow escapes {name} at {instruction.source_line}")
                next_witness = witness + ((location if suffix is None else
                                           location + ":" + suffix),)
                queue.append((target, next_state, next_witness[-80:]))

            if instruction.op == "call":
                target = instruction.args
                if target == "___sdcc_call_iy":
                    ordinal = indirect_ordinal_by_index[index]
                    abi = _CALLBACK_BY_SITE.get((name, ordinal))
                    if abi is None:
                        raise DrawVMStackError(
                            f"unresolved indirect call {name}#{ordinal}")
                    entry_depth = state.depth + 2
                    event = Peak(entry_depth, witness + (location, abi.name))
                    old_event = callback_peaks.get(abi.name, Peak(-1, ()))
                    callback_peaks[abi.name] = self._better(old_event, event)
                    peak = self._better(peak, event)
                    after = self._with_depth(
                        state, state.depth - abi.stack_argument_bytes)
                    if index + 1 >= len(function.instructions):
                        raise DrawVMStackError(
                            f"callback call falls off {name}")
                    enqueue(index + 1, after, "callback-return")
                    continue
                if target == "___memcpy":
                    call_peak = Peak(
                        state.depth + 2,
                        witness + (location, "___memcpy:entry"),
                    )
                    peak = self._better(peak, call_peak)
                    after = self._with_depth(state, state.depth - 2)
                    enqueue(index + 1, after, "memcpy-return")
                    continue
                if target not in self.functions:
                    raise DrawVMStackError(
                        f"unresolved direct call in {name}: {target}")
                if target == f"_{_PREFIX}_eval":
                    if name == target:
                        if eval_budget <= 1:
                            bounded_edges += 1
                            # This syntactic switch case is unreachable for a
                            # leaf DAG node.  The independent DAG proof below
                            # is the sole authority for this cut.
                            continue
                        callee = self.summary(target, eval_budget - 1)
                    else:
                        callee = self.summary(target, self.maximum_eval_depth)
                else:
                    callee = self.summary(target, self.maximum_eval_depth)
                call_base = state.depth + 2
                call_peak = Peak(
                    call_base + callee.maximum_depth_from_entry_sp,
                    witness + (location,) + callee.maximum_witness,
                )
                peak = self._better(peak, call_peak)
                for callback, child_peak in callee.callback_entry_peaks.items():
                    event = Peak(
                        call_base + child_peak.depth,
                        witness + (location,) + child_peak.witness,
                    )
                    callback_peaks[callback] = self._better(
                        callback_peaks.get(callback, Peak(-1, ())), event)
                bounded_edges += callee.bounded_recursive_edges
                after = self._with_depth(
                    state, call_base + callee.return_delta_bytes)
                enqueue(index + 1, after, "direct-return")
                continue

            if instruction.op in ("jp", "jr"):
                args = instruction.args
                parts = [item.strip() for item in args.split(",", 1)]
                conditional = len(parts) == 2 and parts[0] in _CONDITIONS
                target_text = parts[1] if conditional else parts[0]
                if target_text == "(hl)":
                    targets = function.jump_tables.get(index)
                    if targets:
                        for target in targets:
                            enqueue(target, state, "jump-table")
                    elif instruction.op == "jp":
                        exits.add(state.depth)
                    else:
                        raise DrawVMStackError(
                            f"unresolved indirect JR in {name}")
                elif target_text.startswith("("):
                    raise DrawVMStackError(
                        f"unresolved indirect jump in {name}: {instruction.raw}")
                else:
                    enqueue(self._branch_target(function, target_text),
                            state, "branch")
                if conditional:
                    if index + 1 >= len(function.instructions):
                        raise DrawVMStackError(
                            f"conditional branch falls off {name}")
                    enqueue(index + 1, state, "fallthrough")
                continue

            if instruction.op == "djnz":
                enqueue(self._branch_target(function, instruction.args),
                        state, "djnz-taken")
                enqueue(index + 1, state, "djnz-fallthrough")
                continue

            if instruction.op == "ret":
                parts = instruction.args.strip()
                if parts:
                    if parts not in _CONDITIONS:
                        raise DrawVMStackError(
                            f"unsupported RET in {name}: {instruction.raw}")
                    exits.add(state.depth - 2)
                    enqueue(index + 1, state, "ret-not-taken")
                else:
                    exits.add(state.depth - 2)
                continue

            next_state = self._plain_effect(name, instruction, state)
            next_peak = Peak(next_state.depth, witness + (location,))
            peak = self._better(peak, next_peak)
            if index + 1 >= len(function.instructions):
                raise DrawVMStackError(f"function {name} falls off its body")
            enqueue(index + 1, next_state)

        if not exits:
            raise DrawVMStackError(f"function {name} has no proved return")
        if len(exits) != 1:
            raise DrawVMStackError(
                f"function {name} has inconsistent return deltas: {sorted(exits)}")
        return FunctionSummary(
            name=name,
            maximum_depth_from_entry_sp=peak.depth,
            maximum_witness=peak.witness[-80:],
            return_delta_bytes=next(iter(exits)),
            callback_entry_peaks=dict(sorted(callback_peaks.items())),
            bounded_recursive_edges=bounded_edges,
            explored_states=len(seen),
        )


def _node_children(node: object) -> tuple[int, ...]:
    op = str(getattr(node, "op"))
    if op in ("NOT", "RESOURCE_TYPE"):
        return (int(getattr(node, "a")),)
    if op in ("AND", "ADD", "EQUAL", "NOT_EQUAL"):
        return (int(getattr(node, "a")), int(getattr(node, "b")))
    if op == "SELECT":
        return (int(getattr(node, "a")), int(getattr(node, "b")),
                int(getattr(node, "c")))
    return ()


def _prove_expression_dag(program: object) -> dict[str, object]:
    nodes = tuple(getattr(program, "nodes"))
    depths: list[int] = []
    edge_count = 0
    for index, node in enumerate(nodes):
        children = _node_children(node)
        edge_count += len(children)
        if any(child < 0 or child >= index for child in children):
            raise DrawVMStackError(
                f"expression node {index} is cyclic/not topological: {children}")
        depths.append(1 + max((depths[child] for child in children), default=0))
    maximum = max(depths, default=0)
    declared = int(getattr(program, "max_eval_depth"))
    if maximum != declared:
        raise DrawVMStackError(
            f"expression depth mismatch: independently={maximum}, declared={declared}")

    encoded = json.dumps([
        {
            "id": index,
            "op": str(getattr(node, "op")),
            "children": list(_node_children(node)),
            "depth": depths[index],
        }
        for index, node in enumerate(nodes)
    ], sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "node_count": len(nodes),
        "edge_count": edge_count,
        "maximum_simultaneous_eval_invocations": maximum,
        "logical_max_recursive_eval_depth": declared,
        "logical_depth_is_not_used_as_a_byte_count": True,
        "topological_child_before_parent": True,
        "node_graph_sha256": _sha256(encoded),
    }


def _load_callback_contracts(
        path: Path | None,
        ) -> tuple[dict[str, CallbackContract], dict[str, object] | None]:
    if path is None:
        return {}, None
    raw = path.read_bytes()
    value = _read_json(path)
    if value.get("format") != CALLBACK_CONTRACT_FORMAT:
        raise DrawVMStackError(
            f"callback contract format is not {CALLBACK_CONTRACT_FORMAT}")
    callbacks = value.get("callbacks")
    if not isinstance(callbacks, dict):
        raise DrawVMStackError("callback contract lacks callbacks object")
    expected = {item.name for item in _CALLBACK_ABIS}
    if set(callbacks) != expected:
        raise DrawVMStackError(
            f"callback contract names differ: {sorted(callbacks)} != "
            f"{sorted(expected)}")
    result: dict[str, CallbackContract] = {}
    for abi in _CALLBACK_ABIS:
        item = callbacks[abi.name]
        if not isinstance(item, dict):
            raise DrawVMStackError(f"callback {abi.name} contract is not an object")
        try:
            additional = int(
                item["maximum_additional_stack_bytes_from_entry_sp"])
            argument_bytes = int(item["abi_stack_argument_bytes"])
            return_bytes = int(item["return_address_bytes"])
            callee_cleans = item["callee_cleans_stack_arguments"] is True
            evidence = item["evidence"]
        except (KeyError, TypeError, ValueError) as exc:
            raise DrawVMStackError(
                f"callback {abi.name} contract schema is invalid") from exc
        if (additional < 0 or argument_bytes != abi.stack_argument_bytes or
                return_bytes != 2 or not callee_cleans or
                not isinstance(evidence, dict) or not evidence):
            raise DrawVMStackError(
                f"callback {abi.name} contract ABI/evidence is invalid")
        result[abi.name] = CallbackContract(additional, evidence)
    return result, {
        "path": path.resolve().as_posix(),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "format": CALLBACK_CONTRACT_FORMAT,
    }


def _artifact_record(path: str, data: bytes) -> dict[str, object]:
    return {"path": path, "bytes": len(data), "sha256": _sha256(data)}


def probe(
        root: Path, callback_contract_path: Path | None = None,
        ) -> dict[str, object]:
    root = root.resolve()
    plan = compile_active_enemy_draw_plan(root)
    program = build_draw_vm_program(plan)
    artifacts = emit_draw_vm_backend(plan)
    generated = root / "Source" / "C" / "generated"
    expected = {
        artifacts.source_name: artifacts.source.encode("utf-8"),
        artifacts.header_name: artifacts.header.encode("utf-8"),
        artifacts.manifest_name: artifacts.manifest.encode("utf-8"),
    }
    for name, data in expected.items():
        path = generated / name
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise DrawVMStackError(f"missing generated artifact {path}") from exc
        if actual != data:
            raise DrawVMStackError(
                f"generated artifact is stale/non-reproducible: {path}")

    manifest = json.loads(expected[artifacts.manifest_name].decode("utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("plan"), dict):
        raise DrawVMStackError("generated VM manifest has no plan object")
    manifest_plan = manifest["plan"]
    for key, expected_value in {
        "format": plan.format,
        "symbol": plan.symbol,
        "source_path": plan.source_path,
        "source_sha256": plan.source_sha256,
        "method_ast_sha256": plan.method_ast_sha256,
        "semantic_sha256": plan.semantic_sha256,
        "sink_order_sha256": plan.sink_order_sha256,
        "action_count": len(plan.actions),
    }.items():
        if manifest_plan.get(key) != expected_value:
            raise DrawVMStackError(
                f"generated manifest plan field {key} is stale")

    size_path = root / "Build" / "rtype_python_draw_vm_size_status.json"
    size_bytes = size_path.read_bytes()
    size_report = _read_json(size_path)
    try:
        size_plan = str(size_report["input"]["plan_semantic_sha256"])
        size_source_hash = str(size_report["input"]["source"]["sha256"])
        size_header_hash = str(size_report["input"]["header"]["sha256"])
        size_manifest_hash = str(size_report["input"]["manifest"]["sha256"])
    except (KeyError, TypeError) as exc:
        raise DrawVMStackError("draw VM size report schema is invalid") from exc
    if (
        size_plan != plan.semantic_sha256 or
        size_source_hash != _sha256(expected[artifacts.source_name]) or
        size_header_hash != _sha256(expected[artifacts.header_name]) or
        size_manifest_hash != _sha256(expected[artifacts.manifest_name])
    ):
        raise DrawVMStackError("draw VM size report is bound to other artifacts")

    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    sdcc_bytes = sdcc.read_bytes()
    runtime_support = _validate_runtime_support(sdcc)
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="pyz80-draw-vm-stack-") as temp:
        directory = Path(temp)
        (directory / artifacts.source_name).write_bytes(
            expected[artifacts.source_name])
        (directory / artifacts.header_name).write_bytes(
            expected[artifacts.header_name])
        command = [str(sdcc), *PINNED_ARGUMENTS, "-S", artifacts.source_name]
        completed = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if completed.returncode != 0:
            raise DrawVMStackError(
                f"pinned SDCC failed ({completed.returncode}):\n"
                f"{completed.stdout}")
        asm_path = directory / artifacts.source_name.replace(".c", ".asm")
        try:
            asm_bytes = asm_path.read_bytes()
        except OSError as exc:
            raise DrawVMStackError("pinned SDCC emitted no assembly") from exc

    expression_dag = _prove_expression_dag(program)
    functions = parse_sdcc_assembly(asm_bytes.decode("latin1"))
    analyzer = StackAnalyzer(functions, program.max_eval_depth)
    summaries = {
        name: analyzer.summary(name, program.max_eval_depth)
        for name in _FUNCTIONS
    }
    contracts, contract_source = _load_callback_contracts(
        callback_contract_path.resolve() if callback_contract_path else None)

    public: dict[str, object] = {}
    global_internal = Peak(-1, ())
    global_complete = Peak(-1, ())
    global_callback_entries: dict[str, int] = {
        item.name: -1 for item in _CALLBACK_ABIS
    }
    for name in _PUBLIC:
        summary = summaries[name]
        stack_arguments = -summary.return_delta_bytes - 2
        if stack_arguments < 0:
            raise DrawVMStackError(
                f"public function {name} has invalid return delta")
        internal_after_staging = 2 + summary.maximum_depth_from_entry_sp
        internal_including_args = stack_arguments + internal_after_staging
        complete = internal_including_args
        callback_rows: dict[str, object] = {}
        for callback, event in summary.callback_entry_peaks.items():
            boundary_after_staging = 2 + event.depth
            boundary_including_args = stack_arguments + boundary_after_staging
            global_callback_entries[callback] = max(
                global_callback_entries[callback], boundary_including_args)
            contract = contracts.get(callback)
            total = (None if contract is None else
                     boundary_including_args +
                     contract.maximum_additional_stack_bytes_from_entry_sp)
            if total is not None:
                complete = max(complete, total)
            callback_rows[callback] = {
                "maximum_bytes_to_callback_entry_including_public_arguments": (
                    boundary_including_args),
                "external_maximum_additional_stack_bytes": (
                    None if contract is None else
                    contract.maximum_additional_stack_bytes_from_entry_sp),
                "complete_path_bytes": total,
            }
        internal_peak = Peak(internal_including_args,
                             summary.maximum_witness)
        global_internal = StackAnalyzer._better(global_internal, internal_peak)
        if len(contracts) == len(_CALLBACK_ABIS):
            global_complete = StackAnalyzer._better(
                global_complete, Peak(complete, summary.maximum_witness))
        public[name.removeprefix("_")] = {
            "sdcccall": 1,
            "public_stack_argument_bytes": stack_arguments,
            "maximum_internal_bytes_from_sp_after_arguments_staged_before_call": (
                internal_after_staging),
            "maximum_internal_bytes_including_public_stack_arguments": (
                internal_including_args),
            "complete_with_callback_contracts_bytes": (
                complete if len(contracts) == len(_CALLBACK_ABIS) else None),
            "return_delta_from_function_entry_sp": summary.return_delta_bytes,
            "callback_boundaries": callback_rows,
            "maximum_witness": list(summary.maximum_witness),
        }

    callback_contract_rows: dict[str, object] = {}
    missing_callbacks: list[str] = []
    for abi in _CALLBACK_ABIS:
        contract = contracts.get(abi.name)
        if contract is None:
            missing_callbacks.append(abi.name)
        callback_contract_rows[abi.name] = {
            "function_pointer_abi": "sdcccall(1)",
            "return_address_bytes_already_counted_at_boundary": 2,
            "stack_argument_bytes_already_counted_at_boundary": (
                abi.stack_argument_bytes),
            "callee_cleans_stack_arguments": True,
            "maximum_internal_bytes_to_entry_including_public_arguments": (
                global_callback_entries[abi.name]),
            "maximum_additional_stack_bytes_from_entry_sp": (
                None if contract is None else
                contract.maximum_additional_stack_bytes_from_entry_sp),
            "evidence": None if contract is None else dict(contract.evidence),
            "status": ("MISSING_EXTERNAL_STACK_BOUND" if contract is None else
                       "EXTERNAL_STACK_BOUND_SUPPLIED"),
        }

    complete_certified = not missing_callbacks
    status = (
        "VM_PLUS_CALLBACK_STACK_BOUND_PASS_LIVE_INTEGRATION_BLOCKED"
        if complete_certified else
        "INTERNAL_STACK_BOUND_PASS_EXTERNAL_CALLBACKS_BLOCKED"
    )
    result: dict[str, object] = {
        "format": FORMAT,
        "status": status,
        "input": {
            "plan": dict(manifest_plan),
            "source": _artifact_record(
                "Source/C/generated/" + artifacts.source_name,
                expected[artifacts.source_name]),
            "header": _artifact_record(
                "Source/C/generated/" + artifacts.header_name,
                expected[artifacts.header_name]),
            "manifest": _artifact_record(
                "Source/C/generated/" + artifacts.manifest_name,
                expected[artifacts.manifest_name]),
            "size_report": {
                "path": "Build/rtype_python_draw_vm_size_status.json",
                "bytes": len(size_bytes),
                "sha256": _sha256(size_bytes),
                "format": size_report.get("format"),
                "status": size_report.get("status"),
            },
            "callback_contract_source": contract_source,
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "bytes": len(sdcc_bytes),
            "sha256": _sha256(sdcc_bytes),
            "arguments": [*PINNED_ARGUMENTS, "-S", artifacts.source_name],
            "assembly_bytes": len(asm_bytes),
            "assembly_sha256": _sha256(asm_bytes),
        },
        "runtime_support": runtime_support,
        "expression_dag": expression_dag,
        "analysis_method": {
            "kind": "pinned-SDCC-assembly-CFG-stack-abstract-interpretation",
            "stack_unit": "bytes",
            "push_bytes": 2,
            "call_return_address_bytes": 2,
            "frame_pointer_restores_are_modeled": True,
            "computed_switch_jumps_are_resolved_from_adjacent_dw_tables": True,
            "only_bounded_cycle": "rtype_python_draw_vm_eval over immutable topological node DAG",
            "unknown_call_policy": "fail",
            "unknown_indirect_jump_policy": "fail",
            "unsupported_sp_write_policy": "fail",
            "positive_or_state_exploding_cycle_policy": "fail",
        },
        "functions": {
            name.removeprefix("_"): {
                "maximum_depth_from_function_entry_sp": (
                    summary.maximum_depth_from_entry_sp),
                "return_delta_bytes": summary.return_delta_bytes,
                "bounded_recursive_edges_explored": (
                    summary.bounded_recursive_edges),
                "explored_abstract_states": summary.explored_states,
                "callback_entry_depths_from_function_entry_sp": {
                    callback: event.depth for callback, event in
                    summary.callback_entry_peaks.items()
                },
            }
            for name, summary in sorted(summaries.items())
        },
        "public_entries": public,
        "callback_contracts": callback_contract_rows,
        "result": {
            "maximum_internal_stack_bytes_including_public_arguments": (
                global_internal.depth),
            "maximum_internal_stack_witness": list(global_internal.witness),
            "missing_external_callback_bounds": missing_callbacks,
            "complete_vm_plus_callbacks_stack_bytes": (
                global_complete.depth if complete_certified else None),
            "internal_vm_stack_bound_certified": True,
            "complete_vm_plus_callbacks_stack_bound_certified": (
                complete_certified),
            "live_target_use_certified": False,
        },
        "checks": {
            "generated_artifacts_byte_exact": True,
            "size_report_same_artifacts": True,
            "compiler_and_flags_pinned": True,
            "sdcc_runtime_support_sources_bound_and_validated": True,
            "all_generated_direct_calls_resolved": True,
            "all_indirect_calls_classified": True,
            "expression_graph_independently_acyclic_and_bounded": True,
            "logical_depth_not_reported_as_stack_bytes": True,
            "public_return_cleanup_consistent": True,
            "internal_stack_bound_proved": True,
            "external_callback_stack_bounds_present": complete_certified,
        },
        "live_blockers": [
            *(
                ["external callback stack bounds are not supplied: " +
                 ", ".join(missing_callbacks)] if missing_callbacks else []
            ),
            "source-derived target object-layout provider is not linked",
            "complete adapter/runtime link placement is not certified",
            "live Z80 tstates and FT812 frame/scanline budget are not certified",
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_vm_stack_status.json"))
    parser.add_argument(
        "--callback-contracts", type=Path,
        help="optional explicit callback stack-contract JSON")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = arguments.output
    if not output.is_absolute():
        output = root / output
    contract = arguments.callback_contracts
    if contract is not None and not contract.is_absolute():
        contract = root / contract
    try:
        result = probe(root, contract)
        _atomic_json(output, result)
    except (DrawVMStackError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    internal = int(
        result["result"]["maximum_internal_stack_bytes_including_public_arguments"])
    missing = result["result"]["missing_external_callback_bounds"]
    print(
        f"Draw VM stack: internal <= {internal} bytes; "
        f"external callback bounds missing={len(missing)}; live remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
