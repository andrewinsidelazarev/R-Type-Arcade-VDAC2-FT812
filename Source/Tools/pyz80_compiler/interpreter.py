"""Эталонный исполнитель IR для differential-проверки против CPython."""

from __future__ import annotations

from typing import Any

from .diagnostics import fail
from .ir import FunctionIR, Instruction


def _execute_instruction(instruction: Instruction, locals_: dict[str, int],
                         values: dict[str, int]) -> None:
    op = instruction.op
    args = instruction.arguments
    result: int | None = None
    if op == "const":
        result = int(args[0])
    elif op == "load_local":
        result = int(locals_[str(args[0])])
    elif op == "store_local":
        locals_[str(args[0])] = int(values[str(args[1])])
    elif op == "unary":
        value = values[str(args[1])]
        result = {
            "pos": lambda: +value,
            "neg": lambda: -value,
            "invert": lambda: ~value,
            "not": lambda: int(not value),
        }[str(args[0])]()
    elif op == "binary":
        left = values[str(args[1])]
        right = values[str(args[2])]
        result = {
            "add": lambda: left + right,
            "sub": lambda: left - right,
            "mul": lambda: left * right,
            "floordiv": lambda: left // right,
            "mod": lambda: left % right,
            "lshift": lambda: left << right,
            "rshift": lambda: left >> right,
            "bitand": lambda: left & right,
            "bitor": lambda: left | right,
            "bitxor": lambda: left ^ right,
        }[str(args[0])]()
    elif op == "compare":
        left = values[str(args[1])]
        right = values[str(args[2])]
        result = int({
            "eq": lambda: left == right,
            "ne": lambda: left != right,
            "lt": lambda: left < right,
            "le": lambda: left <= right,
            "gt": lambda: left > right,
            "ge": lambda: left >= right,
        }[str(args[0])]())
    elif op == "select":
        result = values[str(args[1])] if values[str(args[0])] else values[str(args[2])]
    elif op == "intrinsic":
        left = values[str(args[1])]
        right = values[str(args[2])]
        result = min(left, right) if args[0] == "min" else max(left, right)
    else:
        fail("PZ4001", f"IR interpreter не знает {op}", instruction.span)
    if instruction.destination is not None:
        assert result is not None
        values[instruction.destination] = result


def execute(function: FunctionIR, arguments: tuple[int, ...],
            *, maximum_blocks: int = 1_000_000) -> int:
    if len(arguments) != len(function.parameters):
        raise ValueError("неверное число аргументов IR")
    locals_ = {item.name: int(value)
               for item, value in zip(function.parameters, arguments)}
    values: dict[str, int] = {}
    block_name = function.entry
    for _ in range(maximum_blocks):
        block = function.blocks[block_name]
        for instruction in block.instructions:
            _execute_instruction(instruction, locals_, values)
        term = block.terminator
        assert term is not None
        if term.op == "return":
            return values[str(term.arguments[0])]
        if term.op == "jump":
            block_name = term.targets[0]
            continue
        if term.op == "branch":
            block_name = term.targets[0 if values[str(term.arguments[0])] else 1]
            continue
        fail("PZ4002", f"IR interpreter не знает terminator {term.op}", term.span)
    fail("PZ4003", f"превышен предел blocks в {function.symbol}")
