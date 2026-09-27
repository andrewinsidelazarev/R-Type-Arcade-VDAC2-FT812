"""Проверка CFG, диапазонов, вызовов и верхней границы стека."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .diagnostics import fail
from .ir import FunctionIR, Instruction
from .types import BOOL, Interval, ScalarType, storage_type


@dataclass(frozen=True)
class FunctionAnalysis:
    intervals: dict[str, Interval]
    return_interval: Interval
    frame_bytes: int
    call_bytes: int
    maximum_stack_bytes: int

    def to_json(self) -> dict[str, object]:
        return {
            "intervals": {
                name: [value.minimum, value.maximum]
                for name, value in sorted(self.intervals.items())
            },
            "return_interval": [self.return_interval.minimum,
                                self.return_interval.maximum],
            "frame_bytes": self.frame_bytes,
            "call_bytes": self.call_bytes,
            "maximum_stack_bytes": self.maximum_stack_bytes,
        }


def _references(instruction: Instruction) -> tuple[str, ...]:
    if instruction.op == "const":
        return ()
    if instruction.op == "load_local":
        return ()
    if instruction.op == "store_local":
        return (instruction.arguments[1],)
    if instruction.op == "unary":
        return (instruction.arguments[1],)
    if instruction.op in ("binary", "compare", "intrinsic"):
        return tuple(value for value in instruction.arguments[1:]
                     if isinstance(value, str) and value.startswith("%"))
    if instruction.op == "select":
        return tuple(instruction.arguments)
    fail("PZ3001", f"неизвестная IR-инструкция {instruction.op}", instruction.span)


def validate_function(function: FunctionIR) -> None:
    if function.entry not in function.blocks:
        fail("PZ3002", "entry block отсутствует")
    definitions: dict[str, tuple[str, int]] = {}
    successors: dict[str, tuple[str, ...]] = {}
    predecessors = {name: set() for name in function.blocks}
    for block_name, block in function.blocks.items():
        if block.terminator is None:
            fail("PZ3003", f"block {block_name} не имеет terminator")
        successors[block_name] = block.terminator.targets
        for target in block.terminator.targets:
            if target not in function.blocks:
                fail("PZ3004", f"block {block_name} ссылается на {target}",
                     block.terminator.span)
            predecessors[target].add(block_name)
        for index, instruction in enumerate(block.instructions):
            if instruction.destination is not None:
                if instruction.destination in definitions:
                    fail("PZ3005", f"повторное определение {instruction.destination}",
                         instruction.span)
                definitions[instruction.destination] = (block_name, index)

    reachable: set[str] = set()
    queue = [function.entry]
    while queue:
        block = queue.pop()
        if block in reachable:
            continue
        reachable.add(block)
        queue.extend(successors[block])
    unreachable = sorted(set(function.blocks) - reachable)
    if unreachable:
        fail("PZ3006", f"недостижимые blocks: {', '.join(unreachable)}")

    all_blocks = set(function.blocks)
    dominators = {
        name: ({name} if name == function.entry else set(all_blocks))
        for name in function.blocks
    }
    changed = True
    while changed:
        changed = False
        for name in sorted(function.blocks):
            if name == function.entry:
                continue
            incoming = predecessors[name]
            new = {name}
            if incoming:
                new |= set.intersection(*(dominators[item] for item in incoming))
            if new != dominators[name]:
                dominators[name] = new
                changed = True

    for block_name, block in function.blocks.items():
        for index, instruction in enumerate(block.instructions):
            for reference in _references(instruction):
                definition = definitions.get(reference)
                if definition is None:
                    fail("PZ3007", f"{reference} использован до определения",
                         instruction.span)
                def_block, def_index = definition
                if def_block == block_name and def_index >= index:
                    fail("PZ3008", f"{reference} использован до определения",
                         instruction.span)
                if def_block != block_name and def_block not in dominators[block_name]:
                    fail("PZ3009", f"определение {reference} не доминирует use",
                         instruction.span)
        term = block.terminator
        assert term is not None
        references = tuple(value for value in term.arguments
                           if isinstance(value, str) and value.startswith("%"))
        for reference in references:
            definition = definitions.get(reference)
            if definition is None or definition[0] not in dominators[block_name]:
                if definition is None or definition[0] != block_name:
                    fail("PZ3010", f"terminator использует недоступный {reference}",
                         term.span)


def _instruction_interval(instruction: Instruction,
                          locals_state: dict[str, Interval],
                          values: dict[str, Interval]) -> Interval | None:
    op = instruction.op
    args = instruction.arguments
    if op == "const":
        value = int(args[0])
        return Interval(value, value)
    if op == "load_local":
        name = str(args[0])
        if name not in locals_state:
            fail("PZ3011", f"local {name!r} не инициализирован", instruction.span)
        return locals_state[name]
    if op == "store_local":
        locals_state[str(args[0])] = values[str(args[1])]
        return None
    if op == "unary":
        value = values[str(args[1])]
        operator = str(args[0])
        if operator == "pos":
            return value
        if operator == "neg":
            return Interval(-value.maximum, -value.minimum)
        if operator == "not":
            return Interval(0, 1)
        if operator == "invert":
            return Interval(~value.maximum, ~value.minimum)
    if op == "binary":
        operator = str(args[0])
        left = values[str(args[1])]
        right = values[str(args[2])]
        if operator == "add":
            return left.add(right)
        if operator == "sub":
            return left.subtract(right)
        if operator == "mul":
            return left.multiply(right)
        if operator in ("floordiv", "mod"):
            if right.minimum <= 0 <= right.maximum:
                fail("PZ3012", "делитель может быть равен нулю", instruction.span)
            candidates = [
                a // b if operator == "floordiv" else a % b
                for a in (left.minimum, left.maximum)
                for b in (right.minimum, right.maximum)
            ]
            return Interval(min(candidates), max(candidates))
        if operator == "lshift":
            if right.minimum < 0 or right.maximum > 31:
                fail("PZ3013", "недоказанный диапазон левого shift", instruction.span)
            return Interval(left.minimum << right.minimum,
                            left.maximum << right.maximum)
        if operator == "rshift":
            if right.minimum < 0 or right.maximum > 31:
                fail("PZ3014", "недоказанный диапазон правого shift", instruction.span)
            candidates = [left.minimum >> right.minimum,
                          left.minimum >> right.maximum,
                          left.maximum >> right.minimum,
                          left.maximum >> right.maximum]
            return Interval(min(candidates), max(candidates))
        if operator in ("bitand", "bitor", "bitxor"):
            if left.minimum < 0 or right.minimum < 0:
                fail("PZ3015", "битовая операция с отрицательным диапазоном требует маски",
                     instruction.span)
            maximum = max(left.maximum, right.maximum)
            if operator == "bitand":
                maximum = min(left.maximum, right.maximum)
            return Interval(0, maximum)
    if op == "compare":
        left = values[str(args[1])]
        right = values[str(args[2])]
        instruction.attributes["signed"] = (
            left.minimum < 0 or right.minimum < 0)
        return Interval(0, 1)
    if op == "select":
        return values[str(args[1])].union(values[str(args[2])])
    if op == "intrinsic":
        left = values[str(args[1])]
        right = values[str(args[2])]
        instruction.attributes["signed"] = (
            left.minimum < 0 or right.minimum < 0)
        if args[0] == "min":
            return Interval(min(left.minimum, right.minimum),
                            min(left.maximum, right.maximum))
        if args[0] == "max":
            return Interval(max(left.minimum, right.minimum),
                            max(left.maximum, right.maximum))
    fail("PZ3016", f"нет range semantics для {op}", instruction.span)


def _refine_interval(interval: Interval, operator: str, constant: int,
                     truth: bool) -> Interval:
    minimum, maximum = interval.minimum, interval.maximum
    if operator == "lt":
        maximum = min(maximum, constant - 1) if truth else maximum
        minimum = minimum if truth else max(minimum, constant)
    elif operator == "le":
        maximum = min(maximum, constant) if truth else maximum
        minimum = minimum if truth else max(minimum, constant + 1)
    elif operator == "gt":
        minimum = max(minimum, constant + 1) if truth else minimum
        maximum = maximum if truth else min(maximum, constant)
    elif operator == "ge":
        minimum = max(minimum, constant) if truth else minimum
        maximum = maximum if truth else min(maximum, constant - 1)
    elif operator == "eq" and truth:
        minimum = maximum = constant
    elif operator == "ne" and not truth:
        minimum = maximum = constant
    if minimum > maximum:
        # Недостижимую ветвь удалит отдельный CFG pass; здесь оставляем исходный
        # диапазон, чтобы анализ не создавал фиктивное значение.
        return interval
    return Interval(minimum, maximum)


def _branch_state(state: dict[str, Interval], condition: str, truth: bool,
                  definitions: dict[str, Instruction]) -> dict[str, Interval]:
    result = dict(state)
    compare = definitions.get(condition)
    if compare is None or compare.op != "compare":
        return result
    operator, left_name, right_name = compare.arguments
    left = definitions.get(str(left_name))
    right = definitions.get(str(right_name))
    if left is None or right is None:
        return result
    if left.op == "load_local" and right.op == "const":
        local_name = str(left.arguments[0])
        constant = int(right.arguments[0])
    elif left.op == "const" and right.op == "load_local":
        local_name = str(right.arguments[0])
        constant = int(left.arguments[0])
        operator = {
            "lt": "gt", "le": "ge", "gt": "lt", "ge": "le",
            "eq": "eq", "ne": "ne",
        }[str(operator)]
    else:
        return result
    if local_name in result:
        result[local_name] = _refine_interval(
            result[local_name], str(operator), constant, truth)
    return result


def analyze_function(function: FunctionIR, *, stack_budget: int,
                     isr_reserve: int) -> FunctionAnalysis:
    validate_function(function)
    entry_state = {
        item.name: Interval(item.minimum, item.maximum)
        for item in function.parameters
    }
    in_states: dict[str, dict[str, Interval]] = {function.entry: entry_state}
    values: dict[str, Interval] = {}
    definitions = {
        instruction.destination: instruction
        for block in function.blocks.values()
        for instruction in block.instructions
        if instruction.destination is not None
    }
    returns: list[Interval] = []
    queue: deque[str] = deque([function.entry])
    visits: dict[str, int] = {}
    while queue:
        block_name = queue.popleft()
        visits[block_name] = visits.get(block_name, 0) + 1
        if visits[block_name] > 64:
            fail("PZ3017", f"range analysis не сходится в {block_name}")
        state = dict(in_states[block_name])
        block = function.blocks[block_name]
        for instruction in block.instructions:
            interval = _instruction_interval(instruction, state, values)
            if instruction.destination is not None:
                assert interval is not None
                previous = values.get(instruction.destination)
                merged = interval if previous is None else previous.union(interval)
                values[instruction.destination] = merged
                instruction.attributes["interval"] = [merged.minimum, merged.maximum]
                instruction.attributes["storage_type"] = (
                    BOOL.name if instruction.type == BOOL else storage_type(merged).name)
        term = block.terminator
        assert term is not None
        if term.op == "return":
            returns.append(values[str(term.arguments[0])])
            continue
        outgoing: list[tuple[str, dict[str, Interval]]] = []
        if term.op == "branch":
            condition = str(term.arguments[0])
            outgoing = [
                (term.targets[0], _branch_state(state, condition, True, definitions)),
                (term.targets[1], _branch_state(state, condition, False, definitions)),
            ]
        else:
            outgoing = [(target, dict(state)) for target in term.targets]
        for target, target_state in outgoing:
            previous = in_states.get(target)
            if previous is None:
                merged_state = dict(target_state)
            else:
                common = set(previous) & set(target_state)
                merged_state = {
                    name: previous[name].union(target_state[name]) for name in common
                }
            if previous != merged_state:
                in_states[target] = merged_state
                queue.append(target)
    if not returns:
        fail("PZ3018", "функция не имеет return")
    return_interval = returns[0]
    for interval in returns[1:]:
        return_interval = return_interval.union(interval)
    if not function.return_type.accepts(return_interval.minimum,
                                        return_interval.maximum):
        fail(
            "PZ3019",
            f"return {return_interval.minimum}…{return_interval.maximum} не помещается в "
            f"{function.return_type.name}",
        )

    # C backend хранит скаляры не шире 16 бит; оценка намеренно консервативна.
    local_count = len(function.local_types) + len(function.temporary_types)
    frame_bytes = local_count * 2
    call_bytes = 0
    maximum = frame_bytes + 2 + isr_reserve
    if maximum > stack_budget:
        fail("PZ3020", f"стек функции {function.symbol}: {maximum}>{stack_budget}")
    return FunctionAnalysis(
        intervals=values,
        return_interval=return_interval,
        frame_bytes=frame_bytes,
        call_bytes=call_bytes,
        maximum_stack_bytes=maximum,
    )
