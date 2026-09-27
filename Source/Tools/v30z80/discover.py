"""Поиск исполнимого кода ROM и граф переходов.

Точки входа: адреса трассы эталонной машины, код полной карты ROM, векторы IRQ из памяти
после загрузки, цели косвенных переходов (трасса и таблицы карты ROM). От них рекурсивно
по прямым переходам и следующей инструкции. Цели возврата (инструкции после CALL) и цели
косвенных переходов попадают в таблицу диспетчеризации переведённой программы.

16-битные непосредственные константы, равные началу инструкции, тоже считаются целями
диспетчеризации: так ROM задаёт обработчики задач и объектов (`mov dx,#EA1F` перед вызовом
планировщика). Константа вне известного кода принимается за вход, если разбор от неё
за несколько инструкций сходится с известным кодом.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .decode import CODE_BASE, DecodeError, Decoder, Imm, Instruction

NO_FALLTHROUGH = {'jmp', 'ret', 'iret', 'retf', 'hlt', 'far'}
CODE_END = CODE_BASE + 0x10000
CONVERGE_LIMIT = 12
# Команды, из которых состоит код обработчиков ROM; редкие (строковые без префикса, порты,
# флаговые) в сходящемся разборе константы означают данные.
PLAUSIBLE = {'mov', 'push', 'pop', 'call', 'jmp', 'jcc', 'add', 'sub', 'cmp', 'inc', 'dec', 'xor', 'and',
             'or', 'test', 'shl', 'shr'}


@dataclass
class Program:
    instructions: dict[int, Instruction] = field(default_factory=dict)
    entries: set[int] = field(default_factory=set)            # цели диспетчеризации
    call_targets: set[int] = field(default_factory=set)
    labels: set[int] = field(default_factory=set)             # цели прямых переходов
    indirect: dict[int, set[int]] = field(default_factory=dict)   # косвенный CALL/JMP → цели
    constant_entries: set[int] = field(default_factory=set)       # входы из непосредственных констант
    # Входы только из констант (не места возврата, не цели косвенных переходов, не векторы):
    # диспетчеризация на них идёт через копию кода (заглушку) и не мешает оптимизации.
    constant_only: set[int] = field(default_factory=set)

    def successors(self, instruction: Instruction) -> list[int]:
        result = []
        if instruction.mnemonic not in NO_FALLTHROUGH:
            result.append(instruction.next)
        if instruction.target is not None:
            result.append(instruction.target)
        return result


def vector_targets(memory: bytes, vector_base: int) -> list[int]:
    targets = []
    for irq in range(8):
        vector = vector_base + irq
        entry = memory[vector * 4:vector * 4 + 4]
        ip = int.from_bytes(entry[0:2], 'little')
        cs = int.from_bytes(entry[2:4], 'little')
        linear = ((cs << 4) + ip) & 0xFFFFF
        if cs == CODE_BASE >> 4:
            targets.append(linear)
    return targets


def static_map(path: Path) -> tuple[list[int], dict[int, set[int]]]:
    """Код runtime V30 из полной карты ROM (m72_rom_complete_map.py): линейные адреса
    инструкций и цели косвенных переходов, выведенные из таблиц ROM."""
    if not path.is_file():
        return [], {}
    runtime = json.loads(path.read_text(encoding='utf-8'))['runtime_v30']
    instructions = [CODE_BASE + item['address'] for item in runtime['instructions']]
    edges: dict[int, set[int]] = {}
    for item in runtime['indirect_control_flow']:
        edges.setdefault(CODE_BASE + item['source'], set()).add(CODE_BASE + item['target'])
    return instructions, edges


def discover(memory: bytes, trace_path: Path, extra_entries: list[int], vector_base: int,
             not_instructions: set[int] = frozenset(), map_path: Path | None = None) -> Program:
    """`not_instructions` — адреса трассы, которые на плате не являются началом инструкции
    (второй байт патча эталона); `map_path` — полная карта ROM."""
    decoder = Decoder(memory)
    program = Program()
    trace = json.loads(trace_path.read_text(encoding='utf-8')) if trace_path.is_file() else {
        'instructions': {}, 'indirect_targets': {}}
    roots = [int(address, 16) for address in trace['instructions'] if int(address, 16) not in not_instructions]
    # Цели косвенных CALL/JMP трассы. У RET/IRET цели — места возврата после CALL (на
    # границе прерывания трасса видит вместо них вход следующего обработчика).
    for source, targets in trace['indirect_targets'].items():
        if trace['instructions'][source][1] in ('call', 'jmp'):
            program.indirect.setdefault(int(source, 16), set()).update(int(target, 16) for target in targets)
    vectors = vector_targets(memory, vector_base)
    static_instructions, static_edges = static_map(map_path) if map_path is not None else ([], {})
    roots += [address for address in static_instructions if address not in not_instructions]
    for source, targets in static_edges.items():
        program.indirect.setdefault(source, set()).update(targets)
    indirect = sorted({target for targets in program.indirect.values() for target in targets})
    program.entries.update(indirect)
    program.entries.update(vectors)
    program.entries.update(extra_entries)

    def explore(pending: list[int]) -> None:
        while pending:
            address = pending.pop()
            if address in program.instructions:
                continue
            instruction = decoder.decode(address)
            program.instructions[address] = instruction
            if instruction.mnemonic == 'call':
                program.entries.add(instruction.next)
                if instruction.target is not None:
                    program.call_targets.add(instruction.target)
            if instruction.target is not None:
                program.labels.add(instruction.target)
            for successor in program.successors(instruction):
                if successor not in program.instructions:
                    pending.append(successor)

    explore(sorted(set(roots) | set(indirect) | set(vectors) | set(extra_entries)))

    covered = {address + offset for address, instruction in program.instructions.items()
               for offset in range(instruction.size)}

    def converges(address: int) -> bool:
        """Разбор от адреса за CONVERGE_LIMIT инструкций приходит в начало известной инструкции,
        не задевая байтов известного кода (разбор с середины инструкции x86 тоже быстро
        сходится, поэтому байты должны лежать в промежутке между известными инструкциями)."""
        for _ in range(CONVERGE_LIMIT):
            if address in program.instructions:
                return True
            if not CODE_BASE <= address < CODE_END:
                return False
            try:
                instruction = decoder.decode(address)
            except DecodeError:
                return False
            if any(address + offset in covered for offset in range(instruction.size)):
                return False
            if instruction.mnemonic not in PLAUSIBLE:
                return False
            if instruction.mnemonic in ('far', 'hlt', 'iret', 'retf', 'ret'):
                return False
            if instruction.mnemonic == 'jmp':
                return instruction.target is not None and instruction.target in program.instructions
            address = instruction.next
        return False

    # Непосредственные 16-битные константы — возможные обработчики.
    before_constants = set(program.entries)
    constants = set()
    for instruction in list(program.instructions.values()):
        for operand in instruction.operands:
            if isinstance(operand, Imm) and operand.width == 2:
                constants.add(CODE_BASE + operand.value)
    for address in sorted(constants):
        if address in program.instructions:
            program.entries.add(address)
            program.constant_entries.add(address)
        elif CODE_BASE <= address < CODE_END and converges(address):
            program.entries.add(address)
            program.constant_entries.add(address)
            explore([address])
    returns = {instruction.next for instruction in program.instructions.values() if instruction.mnemonic == 'call'}
    program.constant_only = {address for address in program.constant_entries
                             if address not in before_constants and address not in returns
                             and address not in program.labels}
    return program
