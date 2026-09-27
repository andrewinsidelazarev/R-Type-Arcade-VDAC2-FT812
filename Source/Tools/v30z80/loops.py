"""Естественные циклы переведённой программы: заголовок, тело, выходы, индукционные регистры.

Цикл — заголовок H и тело: инструкции, из которых по переходам внутри функции достижим
обратный переход на H, не проходя через H. Цикл пригоден для отдельной версии кода, если
в тело нельзя попасть иначе как через H (кроме самого тела) и в нём нет возвратов,
косвенных переходов и вызовов, портов, записи сегментных регистров и точек простоя.
Прямой вызов допускается: быстрая версия уходит в вызываемую функцию обычным кодом, возврат
продолжает обычную версию тела (быстрое тело — инструкции, достижимые от H без вызовов).
Строковые команды MOVS/STOS/LODS допускаются как обычный код внутри быстрой версии.

Для каждого цикла вычисляются приращения 16-битных регистров за один проход тела
(интервал по всем путям от H до обратных переходов) и смещения регистров перед каждой
инструкцией тела — основа проверки диапазонов указателей при входе в цикл. Абстрактный
стек сопоставляет `pop` с `push` внутри тела. Вложенный цикл с постоянным счётчиком (перед
заголовком `mov cx,imm`, все обратные переходы — LOOP, единственный выход — проход после
LOOP, стек сбалансирован) сворачивается: смещения внутри — вход + [0, (c-1)·шаг] + смещение
внутри вложенного, после выхода — вход + c·шаг.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .decode import Imm, Mem, Reg, SReg

UNSUPPORTED = {'ret', 'retf', 'iret', 'far', 'hlt', 'in', 'out', 'int', 'pusha', 'popa', 'pushf', 'popf',
               'cmpsb', 'cmpsw', 'scasb', 'scasw', 'add4s', 'daa', 'das', 'mul', 'imul', 'div', 'idiv', 'cli', 'sti',
               'std', 'cld', 'enter', 'leave', 'xlat', 'lahf', 'sahf'}
STRING = {'movsb', 'movsw', 'stosb', 'stosw', 'lodsb', 'lodsw'}


@dataclass
class Loop:
    header: int
    body: set[int]
    back_edges: set[int]
    exits: set[tuple[int, int]] = field(default_factory=set)       # (инструкция тела, цель вне тела)
    entries: set[int] = field(default_factory=set)                 # внешние предшественники заголовка
    reasons: list[str] = field(default_factory=list)               # почему цикл не пригоден
    steps: dict[int, tuple[int, int] | None] = field(default_factory=dict)   # регистр → (мин, макс) за проход
    # Регистр → инструкция тела → (мин, макс) значения относительно значения в заголовке этого прохода.
    offsets: dict[int, dict[int, tuple[int, int] | None]] = field(default_factory=dict)
    count: int | None = None                                       # постоянное число проходов (или None)
    stack_ok: bool = False                                         # стек сбалансирован за проход
    calls: set[int] = field(default_factory=set)                   # прямые CALL тела
    strings: set[int] = field(default_factory=set)                 # строковые команды тела
    fast_body: set[int] = field(default_factory=set)               # достижимое от H без вызовов
    weights: dict[int, int] = field(default_factory=dict)          # проходов инструкции на проход цикла

    @property
    def supported(self) -> bool:
        return not self.reasons


def local_successors(instruction) -> list[int]:
    """Переходы внутри функции (без входа в вызываемые)."""
    mnemonic = instruction.mnemonic
    if mnemonic in ('ret', 'retf', 'iret', 'far', 'hlt'):
        return []
    if mnemonic == 'jmp':
        return [instruction.target] if instruction.target is not None else []
    result = [instruction.next]
    if instruction.target is not None and mnemonic != 'call':
        result.append(instruction.target)
    return result


def find_loops(program) -> list[Loop]:
    instructions = program.instructions
    predecessors: dict[int, set[int]] = {}
    for address, instruction in instructions.items():
        for successor in local_successors(instruction):
            predecessors.setdefault(successor, set()).add(address)
    # Обратные переходы: цель не больше источника (циклы ROM идут назад по адресам).
    headers: dict[int, set[int]] = {}
    for address, instruction in instructions.items():
        for successor in local_successors(instruction):
            if successor in instructions and successor <= address and instruction.target == successor:
                headers.setdefault(successor, set()).add(address)
    loops = []
    for header, back_edges in sorted(headers.items()):
        body = {header}
        pending = list(back_edges)
        while pending:
            address = pending.pop()
            if address in body:
                continue
            body.add(address)
            pending.extend(predecessors.get(address, ()))
        loop = Loop(header, body, set(back_edges))
        returns = {instructions[address].next for address in body if instructions[address].mnemonic == 'call'}
        for address in body:
            instruction = instructions[address]
            for successor in local_successors(instruction):
                if successor not in body:
                    loop.exits.add((address, successor))
            if address != header:
                outside = {source for source in predecessors.get(address, ()) if source not in body}
                if outside or not predecessors.get(address):
                    loop.reasons.append(f'вход в тело {address:05X}')
                if address < header:
                    loop.reasons.append(f'тело ниже заголовка {address:05X}')
            if address != header and address not in returns and (
                    (address in program.entries and address not in program.constant_only) or
                    address in program.call_targets):
                loop.reasons.append(f'вход диспетчеризации в тело {address:05X}')
            if instruction.mnemonic in UNSUPPORTED:
                loop.reasons.append(instruction.mnemonic)
            if instruction.mnemonic == 'call':
                if instruction.target is None:
                    loop.reasons.append('косвенный call')
                else:
                    loop.calls.add(address)
            if instruction.mnemonic in STRING:
                loop.strings.add(address)
            if instruction.mnemonic == 'jmp' and instruction.target is None:
                loop.reasons.append('косвенный jmp')
            if any(isinstance(operand, SReg) for operand in instruction.operands[:1]) or (
                    instruction.mnemonic == 'pop' and isinstance(instruction.operands[0], SReg)):
                loop.reasons.append('запись сегментного регистра')
        loop.entries = {source for source in predecessors.get(header, ()) if source not in body}
        fast = {header}
        pending = [header]
        while pending:
            address = pending.pop()
            if instructions[address].mnemonic == 'call':
                continue
            for successor in local_successors(instructions[address]):
                if successor in body and successor not in fast:
                    fast.add(successor)
                    pending.append(successor)
        loop.fast_body = fast
        loops.append(loop)
    # Внутренние циклы анализируются первыми: их свёртка нужна внешним.
    analyzed: list[Loop] = []
    for loop in sorted(loops, key=lambda item: len(item.body)):
        inner = [other for other in analyzed if other.header in loop.body and other.header != loop.header
                 and other.body < loop.body]
        loop.steps, loop.offsets, loop.stack_ok = register_steps(program, loop, inner)
        loop.count = static_count(program, loop)
        # Вес инструкции — произведение чисел проходов вложенных циклов (неизвестное — 4).
        loop.weights = {address: 1 for address in loop.body}
        for other in inner:
            for address in other.body:
                loop.weights[address] *= other.count if other.count else 4
        analyzed.append(loop)
    return loops


def static_count(program, loop: Loop) -> int | None:
    """Число проходов, если оно постоянно: вход — только `mov cx,imm` прямо перед заголовком,
    все обратные переходы — LOOP, CX за проход уменьшается ровно на 1."""
    instructions = program.instructions
    if len(loop.entries) != 1 or loop.steps.get(1) != (-1, -1):
        return None
    if not all(instructions[address].mnemonic == 'loop' for address in loop.back_edges):
        return None
    previous = instructions[next(iter(loop.entries))]
    operands = previous.operands
    if (previous.next == loop.header and previous.mnemonic == 'mov' and len(operands) == 2 and
            isinstance(operands[0], Reg) and operands[0].width == 2 and operands[0].index == 1 and
            isinstance(operands[1], Imm) and 0 < operands[1].value <= 0xFFFF):
        return operands[1].value
    return None


def foldable(loop: Loop) -> bool:
    """Вложенный цикл сворачивается: постоянный счётчик, единственный выход — после LOOP."""
    return (loop.supported and not loop.calls and loop.count is not None and loop.stack_ok and
            len(loop.exits) == 1 and next(iter(loop.exits))[0] in loop.back_edges)


def join_interval(a, b):
    if a is None or b is None:
        return None
    return (min(a[0], b[0]), max(a[1], b[1]))


def shift_interval(value, delta_low: int, delta_high: int):
    if value is None:
        return None
    return (value[0] + delta_low, value[1] + delta_high)


def join_frame(a, b):
    """Объединение состояний (регистры, стек)."""
    registers = tuple(join_interval(x, y) for x, y in zip(a[0], b[0]))
    if a[1] is None or b[1] is None or len(a[1]) != len(b[1]):
        stack = None
    else:
        stack = tuple((x[0] if x[0] == y[0] else None, join_interval(x[1], y[1]) if x[0] == y[0] else None)
                      for x, y in zip(a[1], b[1]))
    return registers, stack


def register_steps(program, loop: Loop, inner: list[Loop] | None = None) -> tuple[dict, dict, bool]:
    """Смещения 16-битных регистров относительно значений в заголовке прохода.

    Результат: приращение за проход (мин, макс) или None; смещения перед инструкциями тела;
    признак сбалансированного стека за проход.
    """
    instructions = program.instructions
    folded = {item.header: item for item in (inner or []) if foldable(item)}
    zero = (0, 0)
    start = (tuple(zero for _ in range(8)), ())
    states: dict[int, tuple] = {loop.header: start}
    at_back = None
    pending = [loop.header]
    visits = 0
    while pending:
        visits += 1
        if visits > 50000:
            return {index: None for index in range(8)}, {index: {} for index in range(8)}, False
        address = pending.pop()
        registers, stack = states[address]
        instruction = instructions[address]
        if address in folded and address != loop.header:
            nested = folded[address]
            count = nested.count
            outputs = []
            for index in range(8):
                step = nested.steps.get(index, (0, 0)) if index in nested.steps else (0, 0)
                if registers[index] is None or step is None or step[0] != step[1]:
                    outputs.append(None)
                    continue
                outputs.append(shift_interval(registers[index], count * step[0], count * step[0]))
                # Смещения внутри вложенного цикла.
            for body_address in nested.body:
                inner_registers = []
                for index in range(8):
                    step = nested.steps.get(index, (0, 0)) if index in nested.steps else (0, 0)
                    inner_offset = nested.offsets.get(index, {}).get(body_address, zero) if index in nested.offsets \
                        else zero
                    if registers[index] is None or step is None or step[0] != step[1] or inner_offset is None:
                        inner_registers.append(None)
                        continue
                    span = (count - 1) * step[0]
                    low, high = min(0, span), max(0, span)
                    inner_registers.append((registers[index][0] + low + inner_offset[0],
                                            registers[index][1] + high + inner_offset[1]))
                old = states.get(body_address)
                new = (tuple(inner_registers), None)
                states[body_address] = new if old is None else join_frame(old, new)
            exit_target = next(iter(nested.exits))[1]
            # CX после вложенного цикла равен 0 — не смещение относительно заголовка.
            outputs[1] = None
            successors = [(exit_target, (tuple(outputs), stack))]
        else:
            successors = []
            new_registers = list(registers)
            new_stack = list(stack) if stack is not None else None
            mnemonic = instruction.mnemonic
            operands = instruction.operands
            if mnemonic == 'push':
                operand = operands[0]
                if new_stack is not None:
                    if isinstance(operand, Reg) and operand.width == 2:
                        new_stack.append((operand.index, registers[operand.index]))
                    else:
                        new_stack.append((None, None))
                new_registers[4] = shift_interval(registers[4], -2, -2)
            elif mnemonic == 'pop':
                operand = operands[0]
                entry = new_stack.pop() if new_stack else None
                if not stack:
                    new_stack = None
                new_registers[4] = shift_interval(registers[4], 2, 2)
                if isinstance(operand, Reg) and operand.width == 2:
                    same = entry is not None and entry[0] == operand.index
                    new_registers[operand.index] = entry[1] if same else None
            else:
                for index in writes(instruction):
                    delta = constant_delta(instruction, index)
                    new_registers[index] = None if delta is None else shift_interval(registers[index], delta, delta)
            frame = (tuple(new_registers), tuple(new_stack) if new_stack is not None else None)
            # Вызов уводит из быстрой версии: путь дальше не продолжается.
            for successor in ([] if mnemonic == 'call' else local_successors(instruction)):
                successors.append((successor, frame))
        for successor, frame in successors:
            if successor == loop.header:
                at_back = frame if at_back is None else join_frame(at_back, frame)
                continue
            if successor not in loop.body:
                continue
            old = states.get(successor)
            new = frame if old is None else join_frame(old, frame)
            if any(value is not None and (abs(value[0]) > 0x10000 or abs(value[1]) > 0x10000) for value in new[0]):
                new = (tuple(None if value is not None and (abs(value[0]) > 0x10000 or abs(value[1]) > 0x10000)
                             else value for value in new[0]), new[1])
            if old is None or new != old:
                states[successor] = new
                pending.append(successor)
    steps: dict[int, tuple[int, int] | None] = {}
    offsets: dict[int, dict[int, tuple[int, int] | None]] = {}
    written = set()
    for address in loop.body:
        written |= writes(instructions[address])
    for index in range(8):
        if index in written:
            steps[index] = at_back[0][index] if at_back is not None else None
        offsets[index] = {address: frame[0][index] for address, frame in states.items()}
    stack_ok = at_back is not None and at_back[1] == () and at_back[0][4] == (0, 0)
    return steps, offsets, stack_ok


def writes(instruction) -> set[int]:
    """16-битные регистры, которые инструкция может изменить."""
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    result = set()
    if mnemonic in ('loop', 'loope', 'loopne'):
        result.add(1)
    if mnemonic in ('cbw',):
        result.add(0)
    if mnemonic in ('cwd',):
        result.add(2)
    if mnemonic in STRING:
        result |= {7} if mnemonic.startswith('stos') else {6} if mnemonic.startswith('lods') else {6, 7}
        if mnemonic.startswith('lods'):
            result.add(0)
        if instruction.rep:
            result.add(1)
        return result
    if mnemonic in ('push', 'pop', 'call', 'ret'):
        result.add(4)
    if mnemonic == 'pop' and isinstance(operands[0], Reg):
        result.add(operands[0].index)
    if mnemonic == 'xchg':
        for operand in operands:
            if isinstance(operand, Reg):
                result.add(operand.index if operand.width == 2 else operand.index % 4)
    elif (operands and isinstance(operands[0], Reg) and
          mnemonic not in ('cmp', 'test', 'push', 'jcc', 'jmp', 'loop', 'out')):
        result.add(operands[0].index if operands[0].width == 2 else operands[0].index % 4)
    return result


def reads(instruction) -> tuple[set[int], set[int]]:
    """16-битные регистры, значение которых инструкция читает: (как значения, как базы
    обращений к памяти). Непосредственный приёмник mov/pop/lea/in значением не читается."""
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    values: set[int] = set()
    bases: set[int] = set()
    for position, operand in enumerate(operands):
        if isinstance(operand, Reg):
            if position == 0 and len(operands) > 1 and mnemonic in ('mov', 'lea', 'in', 'les', 'lds'):
                continue
            if position == 0 and mnemonic == 'pop':
                continue
            values.add(operand.index if operand.width == 2 else operand.index % 4)
        elif isinstance(operand, Mem):
            bases.update(operand.bases)
    if mnemonic in ('loop', 'loope', 'loopne', 'jcxz') or instruction.rep:
        values.add(1)
    if mnemonic in STRING:
        values |= {7, 0} if mnemonic.startswith('stos') else {6} if mnemonic.startswith('lods') else {6, 7}
    if mnemonic in ('cbw', 'cwd', 'lahf', 'sahf'):
        values.add(0)
    if mnemonic in ('mul', 'imul', 'div', 'idiv'):
        values |= {0, 2}
    if mnemonic == 'xlat':
        values |= {0, 3}
    if mnemonic in ('push', 'pop', 'call', 'ret', 'retf', 'iret', 'int', 'pushf', 'popf', 'enter', 'leave'):
        values.add(4)
    if mnemonic in ('pusha', 'popa'):
        values |= set(range(8))
    return values, bases


def constant_delta(instruction, register: int) -> int | None:
    """Изменение регистра инструкцией: константа или None."""
    if register not in writes(instruction):
        return 0
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    if mnemonic in ('loop', 'loope', 'loopne') and register == 1:
        return -1
    if mnemonic in ('inc', 'dec') and isinstance(operands[0], Reg) and operands[0].width == 2:
        return 1 if mnemonic == 'inc' else -1
    if (mnemonic in ('add', 'sub') and isinstance(operands[0], Reg) and operands[0].width == 2 and
            isinstance(operands[1], Imm)):
        value = operands[1].value & 0xFFFF
        signed = value - 0x10000 if value >= 0x8000 else value
        return signed if mnemonic == 'add' else -signed
    if register == 4 and mnemonic == 'push':
        return -2
    if register == 4 and mnemonic == 'pop':
        return 2
    return None
