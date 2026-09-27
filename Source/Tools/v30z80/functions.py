"""Функции переведённой программы: входы, тела, места вызова.

Вход функции — цель прямого CALL, цель косвенного CALL (карта ROM, трасса), вектор IRQ,
точка начала исполнения. Тело — инструкции, достижимые от входа без захода в вызываемые:
по прямым и условным переходам, LOOP, следующей инструкции и известным целям косвенного
JMP; после CALL путь продолжается следующей инструкцией. RET, IRET и дальний переход
завершают путь.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL = {'ret', 'iret', 'retf', 'far', 'hlt'}


@dataclass
class Functions:
    entries: set[int] = field(default_factory=set)
    bodies: dict[int, list[int]] = field(default_factory=dict)          # вход → инструкции тела
    owners: dict[int, set[int]] = field(default_factory=dict)           # инструкция → входы
    callers: dict[int, set[int]] = field(default_factory=dict)          # вход → адреса CALL
    returns: dict[int, list[int]] = field(default_factory=dict)         # вход → адреса RET


def call_targets(program, instruction) -> set[int] | None:
    """Цели CALL/JMP: прямая, известные косвенные или None (неизвестны)."""
    if instruction.target is not None:
        return {instruction.target}
    targets = program.indirect.get(instruction.address)
    return set(targets) if targets else None


def intraprocedural_successors(program, instruction) -> list[int]:
    mnemonic = instruction.mnemonic
    if mnemonic in TERMINAL:
        return []
    if mnemonic == 'call':
        return [instruction.next]
    if mnemonic == 'jmp':
        targets = call_targets(program, instruction)
        return sorted(targets) if targets else []
    result = [instruction.next]
    if instruction.target is not None:
        result.append(instruction.target)
    return result


def build(program, roots: set[int]) -> Functions:
    functions = Functions()
    instructions = program.instructions
    entries = set(address for address in roots if address in instructions)
    for instruction in instructions.values():
        if instruction.mnemonic == 'call':
            targets = call_targets(program, instruction)
            for target in targets or ():
                if target in instructions:
                    entries.add(target)
                    functions.callers.setdefault(target, set()).add(instruction.address)
    functions.entries = entries
    for entry in sorted(entries):
        seen = set()
        pending = [entry]
        returns = []
        while pending:
            address = pending.pop()
            if address in seen or address not in instructions:
                continue
            seen.add(address)
            instruction = instructions[address]
            if instruction.mnemonic in ('ret', 'retf'):
                returns.append(address)
            pending.extend(intraprocedural_successors(program, instruction))
        body = sorted(seen)
        functions.bodies[entry] = body
        functions.returns[entry] = returns
        for address in body:
            functions.owners.setdefault(address, set()).add(entry)
    return functions
