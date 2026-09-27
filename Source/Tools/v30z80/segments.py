"""Значения сегментных регистров перед каждой инструкцией (межпроцедурный анализ).

Внутри функции значения символьные: константа ('c', v), значение сегмента на входе
('s', n), значение 16-битного регистра на входе ('r', n), None — неизвестно. Стек
моделируется списком символьных значений, чтобы `push ds … pop ds` восстанавливал DS;
снятие слова с пустого стека функции считается снятием адреса возврата (счётчик `under`).

Сводка функции — состояния на её RET через значения входа:
  обычный возврат — стек функции пуст, адрес возврата не снимался;
  двойной возврат — функция сняла свой адрес возврата (`pop bx` на пути без `push`,
    как у #F366) и RET уходит из вызвавшей: для вызвавшей это её возврат с места вызова;
  нерегулярный — иначе (стек неизвестен).
Вызов подставляет состояние места вызова в сводки вызываемых.

Затем значения на входах функций становятся конкретными: точка начала исполнения
получает состояние после загрузки, векторы IRQ — состояние в точке простоя (прерывание
в модели эталона подаётся только там), остальные входы — объединение по местам вызова.
Результат: для инструкции — значения ES, CS, SS, DS (int или None).
"""
from __future__ import annotations

from .decode import CODE_SEGMENT, Imm, Reg, SReg
from .functions import Functions, call_targets

ES, CS, SS, DS = 0, 1, 2, 3
AX, CX, DX, BX, SP, BP, SI, DI = range(8)
STACK_LIMIT = 64
UNKNOWN_REGS = (None,) * 8
UNKNOWN_SEGS = (None, ('c', CODE_SEGMENT), None, None)

# Мнемоники, пишущие регистр-приёмник (первый операнд), и неявные записи регистров.
DEST_WRITES = {'add', 'adc', 'sub', 'sbb', 'and', 'or', 'xor', 'inc', 'dec', 'neg', 'not', 'shl', 'sal', 'shr',
               'sar', 'rol', 'ror', 'rcl', 'rcr', 'in', 'lea', 'xchg', 'imul'}
IMPLICIT_WRITES = {
    'cbw': (AX,), 'cwd': (DX,), 'mul': (AX, DX), 'imul': (AX, DX), 'div': (AX, DX), 'idiv': (AX, DX),
    'movsb': (SI, DI, CX), 'movsw': (SI, DI, CX), 'stosb': (DI, CX), 'stosw': (DI, CX),
    'lodsb': (AX, SI, CX), 'lodsw': (AX, SI, CX), 'cmpsb': (SI, DI, CX), 'cmpsw': (SI, DI, CX),
    'scasb': (DI, CX), 'scasw': (DI, CX), 'loop': (CX,), 'loope': (CX,), 'loopne': (CX,), 'in': (AX,),
    'daa': (AX,), 'das': (AX,), 'aam': (AX,), 'aad': (AX,), 'xlatb': (AX,),
}
NO_WRITES = {'mov', 'push', 'pop', 'pusha', 'popa', 'pushf', 'popf', 'call', 'ret', 'retf', 'iret', 'jmp', 'jcc',
             'jcxz', 'cmp', 'test', 'nop', 'clc', 'stc', 'cmc', 'cld', 'std', 'cli', 'sti', 'out', 'add4s',
             'far', 'hlt'}

NORMAL_STACK = ((), 0)
DOUBLE_STACK = ((), 1)


def join_value(a, b):
    return a if a == b else None


def join_stack(a, b):
    if a is None or b is None or a[1] != b[1] or len(a[0]) != len(b[0]):
        return None
    return tuple(join_value(x, y) for x, y in zip(a[0], b[0])), a[1]


def join_state(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (tuple(join_value(x, y) for x, y in zip(a[0], b[0])),
            tuple(join_value(x, y) for x, y in zip(a[1], b[1])),
            join_stack(a[2], b[2]))


def join_pair(a, b):
    """Объединение пар (segs, regs)."""
    if a is None:
        return b
    return (tuple(join_value(x, y) for x, y in zip(a[0], b[0])),
            tuple(join_value(x, y) for x, y in zip(a[1], b[1])))


def substitute(value, context):
    """Символьное значение через состояние (segs, regs) места вызова."""
    if value is None or value[0] == 'c':
        return value
    if value[0] == 's':
        return context[0][value[1]]
    return context[1][value[1]]


class Summary:
    def __init__(self) -> None:
        self.normal = None          # (segs, regs) обычного возврата
        self.pops: set = set()      # слов, снимаемых RET N обычного возврата
        self.double = None          # (segs, regs) двойного возврата
        self.irregular = False

    def key(self):
        return self.normal, frozenset(self.pops), self.double, self.irregular

    def add(self, state, pops: int | None) -> None:
        segs, regs, stack = state
        if stack == NORMAL_STACK and pops is not None:
            self.normal = join_pair(self.normal, (segs, regs))
            self.pops.add(pops)
        elif stack == DOUBLE_STACK and pops == 0:
            self.double = join_pair(self.double, (segs, regs))
        else:
            self.irregular = True


class Analysis:
    def __init__(self, program, functions: Functions, concrete_roots: dict[int, tuple] | None = None) -> None:
        self.program = program
        self.functions = functions
        # Входы с известными значениями сегментов (начало исполнения): анализ сразу в константах.
        self.concrete_roots = concrete_roots or {}
        self.summaries: dict[int, Summary | None] = {entry: None for entry in functions.entries}
        self.states: dict[int, dict[int, tuple]] = {}

    @staticmethod
    def value16(operand, state):
        segs, regs, _stack = state
        if isinstance(operand, Reg) and operand.width == 2:
            return regs[operand.index]
        if isinstance(operand, SReg):
            return segs[operand.index]
        if isinstance(operand, Imm):
            return ('c', operand.value & 0xFFFF)
        return None

    def apply_call(self, state, targets):
        """(состояние после CALL или None, состояния возврата вызывающей)."""
        segs, regs, stack = state
        context = (segs, regs)
        after = None
        returns = []
        for target in targets:
            summary = self.summaries.get(target)
            if summary is None:
                continue
            if summary.normal is not None:
                new_segs = tuple(substitute(value, context) for value in summary.normal[0])
                new_regs = tuple(substitute(value, context) for value in summary.normal[1])
                if stack is None or summary.irregular or len(summary.pops) != 1:
                    new_stack = None
                else:
                    pops = next(iter(summary.pops))
                    values, under = stack
                    if len(values) >= pops:
                        new_stack = (values[:len(values) - pops], under)
                    else:
                        new_stack = ((), under + pops - len(values))
                after = join_state(after, (new_segs, new_regs, new_stack))
            elif summary.irregular:
                after = join_state(after, (UNKNOWN_SEGS, UNKNOWN_REGS, None))
            if summary.double is not None:
                # Вызываемая сняла свой адрес возврата: RET уходит из вызывающей с этого места.
                returns.append((tuple(substitute(value, context) for value in summary.double[0]),
                                tuple(substitute(value, context) for value in summary.double[1]), stack))
        return after, returns

    def transfer(self, instruction, state):
        """(список (преемник, состояние), список (состояние возврата, слов RET N))."""
        segs, regs, stack = state
        mnemonic = instruction.mnemonic
        operands = instruction.operands
        regs = list(regs)
        segs = list(segs)
        values = list(stack[0]) if stack is not None else None
        under = stack[1] if stack is not None else 0

        def push(value):
            nonlocal values
            if values is None:
                return
            if under:
                values = None           # запись поверх снятого адреса возврата
                return
            values.append(value)
            if len(values) > STACK_LIMIT:
                values = None

        def pop():
            nonlocal values, under
            if values is None:
                return None
            if values:
                return values.pop()
            under += 1
            return None

        def invalidate_stack():
            nonlocal values
            values = None

        if mnemonic == 'mov':
            dst, src = operands
            if isinstance(dst, SReg):
                segs[dst.index] = self.value16(src, state)
            elif isinstance(dst, Reg):
                if dst.width == 2:
                    regs[dst.index] = self.value16(src, state)
                    if dst.index == SP:
                        invalidate_stack()
                else:
                    regs[dst.index % 4] = None
        elif mnemonic == 'push':
            push(self.value16(operands[0], state))
        elif mnemonic == 'pop':
            value = pop()
            operand = operands[0]
            if isinstance(operand, SReg):
                segs[operand.index] = value
            elif isinstance(operand, Reg):
                regs[operand.index] = value
                if operand.index == SP:
                    invalidate_stack()
        elif mnemonic == 'pusha':
            for index in (AX, CX, DX, BX, SP, BP, SI, DI):
                push(None if index == SP else regs[index])
        elif mnemonic == 'popa':
            for index in (DI, SI, BP, SP, BX, DX, CX, AX):
                value = pop()
                if index != SP:
                    regs[index] = value
        elif mnemonic == 'pushf':
            push(None)
        elif mnemonic == 'popf':
            pop()
        elif mnemonic in ('xor', 'sub') and len(operands) == 2 and operands[0] == operands[1] \
                and isinstance(operands[0], Reg):
            if operands[0].width == 2:
                regs[operands[0].index] = ('c', 0)
            else:
                regs[operands[0].index % 4] = None
        elif mnemonic == 'xchg' and all(isinstance(o, Reg) and o.width == 2 for o in operands):
            a, b = operands
            regs[a.index], regs[b.index] = regs[b.index], regs[a.index]
            if SP in (a.index, b.index):
                invalidate_stack()
        elif mnemonic not in NO_WRITES:
            if mnemonic in DEST_WRITES or mnemonic in IMPLICIT_WRITES:
                written = set(IMPLICIT_WRITES.get(mnemonic, ()))
                destinations = operands if mnemonic == 'xchg' else operands[:1] if mnemonic in DEST_WRITES else []
                for operand in destinations:
                    if isinstance(operand, Reg):
                        written.add(operand.index if operand.width == 2 else operand.index % 4)
            else:
                # Неизвестная команда: все регистры и стек неизвестны.
                written = set(range(8))
            for index in written:
                regs[index] = None
            if SP in written:
                invalidate_stack()

        after = (tuple(segs), tuple(regs), (tuple(values), under) if values is not None else None)
        if mnemonic in ('ret', 'retf'):
            count = instruction.operands[0].value if instruction.operands else 0
            return [], [(after, count // 2 if count % 2 == 0 else None)]
        if mnemonic in ('iret', 'far', 'hlt'):
            return [], []
        if mnemonic == 'call':
            targets = call_targets(self.program, instruction)
            if targets is None:
                return [(instruction.next, (UNKNOWN_SEGS, UNKNOWN_REGS, after[2]))], []
            state_after, returns = self.apply_call(after, targets)
            successors = [(instruction.next, state_after)] if state_after is not None else []
            return successors, [(item, 0) for item in returns]
        if mnemonic == 'jmp':
            targets = call_targets(self.program, instruction)
            if targets is None:
                return [], [((UNKNOWN_SEGS, UNKNOWN_REGS, None), None)]
            return [(target, after) for target in sorted(targets)], []
        successors = [(instruction.next, after)]
        if instruction.target is not None:
            successors.append((instruction.target, after))
        return successors, []

    def entry_state(self, entry: int):
        if entry in self.concrete_roots:
            return tuple(('c', value) for value in self.concrete_roots[entry]), UNKNOWN_REGS, NORMAL_STACK
        return ((('s', ES), ('c', CODE_SEGMENT), ('s', SS), ('s', DS)), tuple(('r', i) for i in range(8)),
                NORMAL_STACK)

    def analyze_function(self, entry: int) -> Summary | None:
        instructions = self.program.instructions
        states: dict[int, tuple] = {entry: self.entry_state(entry)}
        pending = [entry]
        summary = Summary()
        returned = False
        while pending:
            address = pending.pop()
            if address not in instructions:
                continue
            successors, returns = self.transfer(instructions[address], states[address])
            for state, pops in returns:
                summary.add(state, pops)
                returned = True
            for target, state in successors:
                if target not in instructions:
                    continue
                old = states.get(target)
                new = join_state(old, state) if old is not None else state
                if new != old:
                    states[target] = new
                    pending.append(target)
        self.states[entry] = states
        return summary if returned else None

    def run(self) -> None:
        changed = True
        while changed:
            changed = False
            for entry in sorted(self.functions.entries):
                summary = self.analyze_function(entry)
                old = self.summaries[entry]
                if (summary.key() if summary else None) != (old.key() if old else None):
                    self.summaries[entry] = summary
                    changed = True


def constant_stack_segment(program, analysis: Analysis, start_segs: tuple) -> tuple[int, int] | None:
    """(SS, адрес последней записи SS), если SS после загрузки постоянен: каждая запись SS в программе —
    `MOV SS, …` значением SS начала исполнения (или самим SS). Иначе None.

    Нужно входам, контекст которых анализ не выводит (обработчики объектов, чей адрес ROM хранит только
    константой в поле объекта): без SS их стековые команды переводились остановом FAULT."""
    value = start_segs[SS]
    last = None
    for address, instruction in program.instructions.items():
        operands = instruction.operands
        if not operands or not isinstance(operands[0], SReg) or operands[0].index != SS:
            continue
        if instruction.mnemonic != 'mov':
            return None
        found = False
        for states in analysis.states.values():
            state = states.get(address)
            if state is None:
                continue
            found = True
            if Analysis.value16(operands[1], state) not in (('c', value), ('s', SS)):
                return None
        if not found:
            return None
        last = address if last is None else max(last, address)
    return (value, -1 if last is None else last)


def concrete(program, functions: Functions, analysis: Analysis, start: int, start_segs: tuple,
             vectors: list[int], idle_points: set[int], stack_segment: tuple[int, int] | None = None
             ) -> dict[int, tuple]:
    """Конкретные значения (ES, CS, SS, DS) перед каждой инструкцией. stack_segment — результат
    constant_stack_segment: инструкциям после последней записи SS без выведенного SS он и ставится, CS —
    сегмент кода (DS и ES таких инструкций остаются неизвестными)."""
    entry_values: dict[int, tuple] = {}

    def context_join(entry, segs, regs):
        old = entry_values.get(entry)
        new = (segs, regs) if old is None else join_pair(old, (segs, regs))
        if new != old:
            entry_values[entry] = new
            return True
        return False

    start_context = (tuple(('c', value) for value in start_segs), UNKNOWN_REGS)
    for entry in functions.entries:
        if start in functions.bodies.get(entry, ()):
            context_join(entry, *start_context)
    changed = True
    while changed:
        changed = False
        for entry in sorted(entry_values):
            context = entry_values[entry]
            for address, symbolic in analysis.states.get(entry, {}).items():
                instruction = program.instructions[address]
                segs = tuple(substitute(value, context) for value in symbolic[0])
                regs = tuple(substitute(value, context) for value in symbolic[1])
                if instruction.mnemonic == 'call':
                    for target in call_targets(program, instruction) or ():
                        if target in functions.entries:
                            changed |= context_join(target, segs, regs)
                if address in idle_points:
                    for vector in vectors:
                        if vector in functions.entries:
                            changed |= context_join(vector, segs, UNKNOWN_REGS)
    result: dict[int, tuple] = {}
    for entry, context in entry_values.items():
        for address, symbolic in analysis.states.get(entry, {}).items():
            segs = tuple(substitute(value, context) for value in symbolic[0])
            values = tuple(value[1] if value is not None and value[0] == 'c' else None for value in segs)
            old = result.get(address)
            result[address] = values if old is None else tuple(join_value(a, b) for a, b in zip(old, values))
    if stack_segment is not None:
        # Код до последней записи SS — начальная загрузка (стеком она до записи не пользуется).
        value, last_write = stack_segment
        for address in program.instructions:
            if address <= last_write:
                continue
            es, cs, ss, ds = result.get(address, (None, CODE_SEGMENT, None, None))
            if ss is None or cs is None:
                result[address] = (es, CODE_SEGMENT if cs is None else cs, value if ss is None else ss, ds)
    return result
