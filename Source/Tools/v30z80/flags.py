"""Живость флагов V30 по графу переходов: какие флаги инструкция обязана записать в V_FL.

Флаги: C P A Z S O (биты 1, 2, 4, 8, 16, 32). Инструкция материализует флаги, если хотя бы
один из её записываемых флагов жив после неё.

Межпроцедурно: после RET живы флаги, живые в местах возврата всех известных вызовов
функций, которым RET принадлежит (прямые CALL и косвенные с известными целями). Все флаги
живыми считаются после IRET, дальнего перехода, косвенного перехода с неизвестными
целями и RET функции, у которой вызовы известны не полностью: нет известных вызовов, вход
задан константой и не входит в известные цели косвенных вызовов, или функция снимает свой
адрес возврата (двойной возврат).
"""
from __future__ import annotations

from .decode import Imm, Instruction

C, P, A, Z, S, O = 1, 2, 4, 8, 16, 32
ALL = 63
CONDITION_READS = {
    'o': O, 'no': O, 'b': C, 'ae': C, 'e': Z, 'ne': Z, 'be': C | Z, 'a': C | Z,
    's': S, 'ns': S, 'p': P, 'np': P, 'l': S | O, 'ge': S | O, 'le': Z | S | O, 'g': Z | S | O,
}


def shift_count(instruction: Instruction) -> int | None:
    """Счётчик сдвига из непосредственного операнда (None — по CL)."""
    if len(instruction.operands) < 2:
        return 1
    count = instruction.operands[1]
    if isinstance(count, Imm):
        return count.value if count.width else 1
    return None


def effect(instruction: Instruction, idle_points: set[int]) -> tuple[int, int]:
    """(читает, записывает) флаги."""
    mnemonic = instruction.mnemonic
    if instruction.address in idle_points:
        return ALL, 0
    if mnemonic in ('add', 'sub', 'cmp', 'neg', 'and', 'or', 'xor', 'test'):
        return 0, ALL
    if mnemonic in ('adc', 'sbb'):
        return C, ALL
    if mnemonic in ('inc', 'dec'):
        return 0, P | A | Z | S | O
    if mnemonic in ('shl', 'sal', 'shr', 'sar'):
        count = shift_count(instruction)
        if count is None:
            return ALL, 0
        return (0, ALL) if count & 0x1F else (0, 0)
    if mnemonic in ('rol', 'ror'):
        count = shift_count(instruction)
        if count is None:
            return ALL, 0
        return (0, C | O) if count & 0x1F else (0, 0)
    if mnemonic in ('rcl', 'rcr'):
        count = shift_count(instruction)
        if count is None:
            return ALL, 0
        return (C, C | O) if count & 0x1F else (0, 0)
    if mnemonic in ('clc', 'stc'):
        return 0, C
    if mnemonic == 'cmc':
        return C, C
    if mnemonic == 'jcc':
        return CONDITION_READS[instruction.condition], 0
    if mnemonic in ('daa', 'das'):
        return C | A, ALL
    if mnemonic == 'add4s':
        return 0, C | Z
    if mnemonic in ('pushf', 'int', 'far'):
        return ALL, 0
    if mnemonic in ('popf', 'iret'):
        return 0, ALL
    return 0, 0


def return_sites(program, functions, analysis) -> dict[int, set[int] | None]:
    """Для каждого RET — места возврата известных вызовов (None — все флаги живы)."""
    indirect_targets = set()
    for targets in program.indirect.values():
        indirect_targets |= targets
    constant_entries = getattr(program, 'constant_entries', set())
    sites_of: dict[int, set[int] | None] = {}
    for entry in functions.entries:
        callers = functions.callers.get(entry)
        summary = analysis.summaries.get(entry) if analysis is not None else None
        if (not callers or (entry in constant_entries and entry not in indirect_targets) or
                (summary is not None and summary.double is not None)):
            sites_of[entry] = None
            continue
        sites_of[entry] = {program.instructions[caller].next for caller in callers}
    result: dict[int, set[int] | None] = {}
    for entry, returns in functions.returns.items():
        for address in returns:
            sites = sites_of.get(entry)
            if address in result and result[address] is None:
                continue
            if sites is None:
                result[address] = None
            else:
                result.setdefault(address, set()).update(sites)
    return result


def liveness(program, idle_points: set[int], functions=None, analysis=None) -> dict[int, int]:
    """Живые после инструкции флаги для каждого адреса."""
    instructions = program.instructions
    effects = {address: effect(instruction, idle_points) for address, instruction in instructions.items()}
    returns = return_sites(program, functions, analysis) if functions is not None else {}
    live_in = {address: 0 for address in instructions}
    live_out = {address: 0 for address in instructions}
    order = sorted(instructions, reverse=True)
    changed = True
    while changed:
        changed = False
        for address in order:
            instruction = instructions[address]
            mnemonic = instruction.mnemonic
            out = 0
            if mnemonic in ('iret', 'far', 'retf', 'hlt'):
                out = ALL
            elif mnemonic == 'ret':
                sites = returns.get(address)
                if sites is None:
                    out = ALL
                else:
                    for site in sites:
                        out |= live_in.get(site, ALL)
            elif mnemonic in ('jmp', 'call') and instruction.target is None:
                targets = program.indirect.get(address)
                if not targets:
                    out = ALL
                else:
                    for target in targets:
                        out |= live_in.get(target, ALL)
            elif mnemonic == 'call':
                out = live_in.get(instruction.target, ALL)
            else:
                for successor in program.successors(instruction):
                    out |= live_in.get(successor, ALL)
            reads, writes = effects[address]
            value = reads | (out & ~writes)
            if out != live_out[address] or value != live_in[address]:
                live_out[address] = out
                live_in[address] = value
                changed = True
    return live_out


def materialize(instruction: Instruction, live_out: int, idle_points: set[int]) -> bool:
    _reads, writes = effect(instruction, idle_points)
    return bool(writes & live_out)
