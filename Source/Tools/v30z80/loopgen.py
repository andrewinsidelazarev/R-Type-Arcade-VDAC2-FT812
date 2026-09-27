"""Быстрые версии циклов: прямой доступ к памяти через IX/IY и заранее вычисленные адреса.

Регистры V30 остаются в памяти резидента, как в обычном коде. Быстрая версия отличается
только обращениями к памяти V30:
  указатель — регистр с постоянным положительным шагом за проход: в IX/IY лежит адрес
    окна, соответствующий текущему значению регистра; каждая запись регистра в теле
    (inc/dec/add/sub константы) сдвигает IX/IY на то же значение; обращение [reg+d] —
    `(ix+d)`;
  ячейка — регистр, не меняющийся в теле: адрес окна [reg+d] вычисляется один раз в
    LOOP_SLOTn;
  абсолютный адрес — адрес окна известен при переводе.
Все страницы, кроме рабочего ОЗУ (окно W1), обязаны совпасть: окно W2 отображается один
раз при входе.

Проверка при входе (метка G_<заголовок>) вычисляет диапазоны исполнительных адресов всех
обращений за все проходы и требует, чтобы каждый диапазон не переходил через 64 КБ и лежал
в одной странице V30. Число проходов ограничено либо счётчиком: все обратные переходы —
LOOP, CX уменьшается ровно на 1 за проход и больше не меняется (проходов не больше CX при
входе), — либо заголовком `cmp R,imm` с выходом `jae`: в теле R < imm. При неудаче
исполняется обычная версия цикла (метка A_<заголовок>).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .decode import Imm, Mem, Reg
from .loops import Loop, constant_delta, reads, writes

WORK_PAGE = 0x10
WORK_SEGMENT = 0x4000
VIDEO_PAGES = frozenset((0x32, 0x33, 0x34, 0x36))     # страницы с пометками изменений (codegen)
HOMES = ('ix', 'iy')
SLOT_COUNT = 8
REG16 = ['V_AX', 'V_CX', 'V_DX', 'V_BX', 'V_SP', 'V_BP', 'V_SI', 'V_DI']


@dataclass
class Pointer:
    register: int
    home: str
    segment: int
    step: int
    lo: int = 1 << 20          # минимум (смещение регистра + disp)
    hi: int = -(1 << 20)       # максимум (смещение регистра + disp + ширина - 1)
    restored: bool = False     # регистр восстанавливается `pop`: нужно смещение окна


@dataclass
class Slot:
    name: str
    register: int
    segment: int
    disp: int
    width: int


@dataclass
class Plan:
    loop: Loop
    bound: tuple                                   # ('count',) | ('limit', регистр, наибольшее значение)
    pointers: dict[int, Pointer] = field(default_factory=dict)
    slots: dict[tuple, Slot] = field(default_factory=dict)
    access: dict[tuple, tuple] = field(default_factory=dict)    # (адрес, Mem) → вид обращения
    static_w2: int | None = None
    count: int | None = None                       # число проходов, известное при переводе
    reentrant: bool = False                        # обратный переход обычной версии — на проверку
    lifted: set[int] = field(default_factory=set)  # указатели без записи в V_R на шагах (V_R = IX/IY − смещение)
    values: dict[int, str] = field(default_factory=dict)   # регистр → свободный IX/IY со значением регистра
    bc_counter: bool = False                       # CX — в регистре BC
    limit_counter: bool = False                    # BC — оставшиеся проходы цикла `cmp R,imm` / `jae`
    # Записи, которые могут попасть в VRAM или палитры: указатели, ячейки и абсолютные адреса
    # (страница, адрес окна, ширина) — их диапазоны за все проходы помечает проверка при входе.
    video_pointers: set[int] = field(default_factory=set)
    video_slots: set[tuple] = field(default_factory=set)
    video_absolute: set[tuple] = field(default_factory=set)

    def label(self, address: int) -> str:
        return f'F_{self.loop.header:05X}_{address:05X}'

    @property
    def guard_label(self) -> str:
        return f'G_{self.loop.header:05X}'


def hex16(value: int) -> str:
    return f'#{value & 0xFFFF:04X}'


def signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def power_of_two(value: int) -> int | None:
    if value > 0 and value & (value - 1) == 0:
        return value.bit_length() - 1
    return None


def memory_written(instruction, position: int) -> bool:
    """Операнд-память с номером position изменяется инструкцией."""
    if instruction.mnemonic == 'xchg':
        return True
    return position == 0 and instruction.mnemonic not in ('cmp', 'test', 'push', 'jmp', 'call')


def video_segment(segment: int) -> bool:
    """Сегмент (64 КБ от базы) может задевать VRAM или палитры."""
    base_page = (segment << 4) >> 14
    return any(base_page + index in VIDEO_PAGES for index in range(4))


def plan_loop(generator, loop: Loop) -> Plan | str:
    """План быстрой версии цикла или причина отказа."""
    program = generator.program
    instructions = program.instructions
    if not loop.supported:
        return 'цикл не пригоден'
    segments = generator.seg_values.get(loop.header)
    body = loop.fast_body
    if segments is None or any(generator.seg_values.get(address) != segments for address in body):
        return 'значения сегментов неизвестны или меняются'
    if any(address in loop.body for address in generator.idle_points):
        return 'точка простоя'
    # Вызов в теле: только редкий по трассе (не чаще раза на 8 проходов), иначе проверка при
    # каждом возвращении в цикл дороже выигрыша.
    counts = generator.instruction_counts
    if loop.calls:
        header_count = counts.get(loop.header, 0)
        if not header_count or any(counts.get(address, 0) * 8 > header_count for address in loop.calls):
            return 'частый вызов в теле'
    header = instructions[loop.header]
    written = set()
    for address in body:
        written |= writes(instructions[address])

    # Граница числа проходов: CX уменьшается ровно на 1 за проход (анализ смещений учитывает
    # push/pop и свёрнутые вложенные циклы), все обратные переходы — LOOP.
    bound = None
    back = [instructions[address] for address in loop.back_edges]
    if all(item.mnemonic == 'loop' for item in back) and loop.steps.get(1) == (-1, -1):
        bound = ('count',)
    elif (header.mnemonic == 'cmp' and isinstance(header.operands[0], Reg) and header.operands[0].width == 2 and
          isinstance(header.operands[1], Imm)):
        following = instructions.get(header.next)
        register = header.operands[0].index
        step = loop.steps.get(register)
        if (following is not None and following.mnemonic == 'jcc' and following.condition == 'ae' and
                following.address in loop.body and following.target not in loop.body and
                following.next in loop.body and step is not None and step[0] > 0 and
                0 < header.operands[1].value <= 0xFFFF):
            bound = ('limit', register, header.operands[1].value - 1)

    plan = Plan(loop, bound)
    # Число проходов известно, если единственный внешний вход — `mov cx,imm` прямо перед
    # заголовком (диспетчеризация приходит на A_ после проверки и идёт обычной версией).
    plan.reentrant = bool(loop.calls)
    if bound == ('count',) and loop.count is not None and loop.header not in program.entries and not plan.reentrant:
        plan.count = loop.count
    slot_index = 0
    for address in sorted(body):
        instruction = instructions[address]
        if address in loop.strings:
            continue                    # строковая команда — обычный код
        for position, operand in enumerate(instruction.operands):
            if not isinstance(operand, Mem):
                continue
            segment = segments[operand.segment]
            width = operand.width or instruction.width or 1
            if segment is None:
                return 'сегмент обращения неизвестен'
            key = (address, operand)
            write = memory_written(instruction, position)
            if not operand.bases:
                linear = ((segment << 4) + operand.disp) & 0xFFFFF
                page, offset = linear >> 14, linear & 0x3FFF
                if offset + width > 0x4000:
                    return 'абсолютное обращение на границе страницы'
                if page != WORK_PAGE:
                    if plan.static_w2 not in (None, page):
                        return 'две страницы W2'
                    plan.static_w2 = page
                if write and page in VIDEO_PAGES:
                    plan.video_absolute.add((page, offset, width))
                plan.access[key] = ('abs', (0x4000 if page == WORK_PAGE else 0x8000) + offset)
                continue
            if len(operand.bases) != 1:
                return 'два базовых регистра'
            register = operand.bases[0]
            disp = signed16(operand.disp)
            if register not in written:
                slot_key = (register, segment, disp, width)
                if slot_key not in plan.slots:
                    if slot_index >= SLOT_COUNT:
                        return 'много ячеек'
                    plan.slots[slot_key] = Slot(f'LOOP_SLOT{slot_index}', register, segment, disp, width)
                    slot_index += 1
                if write and segment != WORK_SEGMENT and video_segment(segment):
                    plan.video_slots.add(slot_key)
                plan.access[key] = ('slot', plan.slots[slot_key].name)
                continue
            step = loop.steps.get(register)
            offset = loop.offsets.get(register, {}).get(address)
            if step is None or step[0] != step[1] or step[0] <= 0 or offset is None:
                return f'указатель {register} без постоянного шага'
            if bound is None or (bound[0] == 'limit' and bound[1] != register):
                return 'нет границы числа проходов'
            if not -128 <= disp <= 127 - (width - 1):
                return 'смещение вне (ix+d)'
            pointer = plan.pointers.get(register)
            if pointer is None:
                if len(plan.pointers) >= len(HOMES):
                    return 'больше двух указателей'
                pointer = Pointer(register, HOMES[len(plan.pointers)], segment, step[0])
                plan.pointers[register] = pointer
            elif pointer.segment != segment:
                return 'указатель в двух сегментах'
            pointer.lo = min(pointer.lo, offset[0] + disp)
            pointer.hi = max(pointer.hi, offset[1] + disp + width - 1)
            if write and segment != WORK_SEGMENT and video_segment(segment):
                plan.video_pointers.add(register)
            plan.access[key] = ('ptr', pointer.home, disp)
    if not plan.access:
        return 'нет обращений к памяти'
    # Строковые команды и возврат через проверку: окно W2 цикла не должно понадобиться (обычный
    # код может сменить W2), указатели не меняются строковыми командами.
    needs_w2 = plan.static_w2 is not None or any(pointer.segment != WORK_SEGMENT for pointer in plan.pointers.values())
    needs_w2 = needs_w2 or any(slot.segment != WORK_SEGMENT for slot in plan.slots.values())
    if (loop.strings or plan.reentrant) and needs_w2:
        return 'обычный код в быстрой версии при окне W2'
    for address in loop.strings & body:
        if writes(instructions[address]) & set(plan.pointers):
            return 'строковая команда меняет указатель'
    # Записи указателей: константой (сдвиг IX/IY; флаги такой инструкции не должны идти в
    # слитый переход — add меняет CF) или `pop` сохранённого в теле значения (IX/IY заново из
    # значения регистра через смещение окна LOOP_BIAS_*).
    for address in body:
        instruction = instructions[address]
        if address in loop.calls:
            continue                    # вызов уходит из быстрой версии
        for register in writes(instruction):
            if register not in plan.pointers:
                continue
            delta = constant_delta(instruction, register)
            if delta is None:
                following = loop.offsets.get(register, {}).get(instruction.next)
                if instruction.mnemonic != 'pop' or (following is None and instruction.next in loop.body):
                    return 'указатель меняется не константой'
                plan.pointers[register].restored = True
            elif abs(delta) > 3 and address in generator.fusion:
                return 'сдвиг указателя в слитом переходе'
    choose_lifting(generator, plan)
    return plan


def self_step(generator, instruction, register: int) -> bool:
    """Инструкция — только шаг регистра константой без нужных флагов (inc/dec/add/sub imm)."""
    operands = instruction.operands
    return (instruction.mnemonic in ('inc', 'dec', 'add', 'sub') and isinstance(operands[0], Reg) and
            operands[0].width == 2 and operands[0].index == register and
            (len(operands) == 1 or isinstance(operands[1], Imm)) and
            instruction.address not in generator.fusion and not generator.flags_needed(instruction))


def value_reads(plan: Plan, instruction) -> set[int]:
    """Регистры, значения которых нужны шаблону быстрой версии (базы обращений по плану — нет)."""
    values, _bases = reads(instruction)
    for operand in instruction.operands:
        if isinstance(operand, Mem) and (instruction.address, operand) not in plan.access:
            values.update(operand.bases)
    return values


def limit_header(generator, plan: Plan) -> int | None:
    """Шаг регистра границы, если заголовок `cmp R,imm` слит только с `jae` без нужных флагов,
    R — указатель с единственным шагом-степенью двойки в теле: тогда число проходов считается
    в BC при входе."""
    loop = plan.loop
    if plan.bound[0] != 'limit':
        return None
    register = plan.bound[1]
    header = generator.program.instructions[loop.header]
    chain = generator.fusion.get(loop.header)
    if (register not in plan.pointers or not chain or len(chain) != 1 or chain[0].condition != 'ae' or
            generator.flags_needed(header)):
        return None
    instructions = generator.program.instructions
    steps = [address for address in loop.fast_body if self_step(generator, instructions[address], register)]
    if len(steps) != 1 or constant_delta(instructions[steps[0]], register) != plan.pointers[register].step:
        return None
    if power_of_two(plan.pointers[register].step) is None:
        return None
    return plan.pointers[register].step


def choose_lifting(generator, plan: Plan) -> None:
    """Подъём регистров. Указатель, у которого шагов (с весом вложенности) больше, чем чтений
    значения, не пишется в V_R на шагах. Регистр вне указателей с шагами-константами — в
    свободном IX/IY. CX при границе по счётчику — в BC; при границе `cmp R,imm` — BC считает
    оставшиеся проходы. Выходы из тела в слитые переходы не допускаются: восстановление
    регистров меняет флаги Z80."""
    loop = plan.loop
    instructions = generator.program.instructions
    if any(target in generator.fused_jumps for _source, target in loop.exits):
        return
    plan.limit_counter = limit_header(generator, plan) is not None

    counts = generator.instruction_counts
    traced = counts.get(loop.header, 0) > 0

    def weight(address: int) -> int:
        # Вес — число исполнений по трассе (у REP — исполнений команды, а не повторов), без
        # трассы — вложенность циклов.
        if not traced:
            return loop.weights.get(address, 1)
        instruction = instructions[address]
        count = counts.get(address, 0)
        if instruction.rep:
            count = min(count, counts.get(instruction.next, count))
        return count

    def balance(register: int) -> int:
        steps = uses = 0
        for address in loop.fast_body:
            instruction = instructions[address]
            if self_step(generator, instruction, register):
                steps += weight(address)
                continue
            if plan.limit_counter and address == loop.header and register == plan.bound[1]:
                continue
            if register in value_reads(plan, instruction) or register in writes(instruction):
                uses += weight(address)
        return steps - uses
    for register in plan.pointers:
        if balance(register) > 0:
            plan.lifted.add(register)
    free = [home for home in HOMES if home not in {pointer.home for pointer in plan.pointers.values()}]
    if plan.bound == ('count',) and 1 not in plan.pointers:
        loops_count = sum(weight(address) for address in loop.fast_body if instructions[address].mnemonic == 'loop')
        uses = sum(weight(address) for address in loop.fast_body
                   if instructions[address].mnemonic != 'loop' and 1 in value_reads(plan, instructions[address]))
        plan.bc_counter = loops_count > uses and not plan.limit_counter
    written = {}
    for address in loop.fast_body:
        for register in writes(instructions[address]):
            written.setdefault(register, []).append(address)
    candidates = []
    for register, addresses in written.items():
        if register in plan.pointers or register == 4 or (register == 1 and (plan.bc_counter or plan.limit_counter)):
            continue
        if not any(self_step(generator, instructions[address], register) for address in addresses):
            continue
        gain = balance(register)
        if gain > 0:
            candidates.append((-gain, register))
    for (_gain, register), home in zip(sorted(candidates), free):
        plan.values[register] = home


def materialize_lines(plan: Plan, keep_bc: bool = False) -> list[str]:
    """V_R поднятых регистров из IX/IY и V_CX из BC — перед выходом из быстрой версии
    (keep_bc — BC испорчен шаблоном, V_CX уже записан)."""
    lines = []
    for register in sorted(plan.lifted):
        lines += materialize_pointer(plan, register)
    for register, home in sorted(plan.values.items()):
        lines.append(f'ld ({REG16[register]}),{home}')
    if plan.bc_counter and not keep_bc:
        lines.append('ld (V_CX),bc')
    return lines


def materialize_pointer(plan: Plan, register: int) -> list[str]:
    pointer = plan.pointers[register]
    home = pointer.home
    name = home.upper()
    if pointer.segment == WORK_SEGMENT:
        return [f'ld (LOOP_{name}),{home}', f'ld hl,(LOOP_{name})', 'ld de,#C000', 'add hl,de',
                f'ld ({REG16[register]}),hl']
    return [f'ld (LOOP_{name}),{home}', f'ld hl,(LOOP_{name})', f'ld de,(LOOP_BIAS_{name})', 'or a', 'sbc hl,de',
            f'ld ({REG16[register]}),hl']


def multiply_count(lines: list[str], factor: int, fail: str) -> None:
    """HL = (LOOP_N1) · factor без переполнения 16 бит (иначе fail): удвоения со сложением по
    битам множителя от старшего. Портит DE."""
    bits = bin(factor)[2:]
    lines += ['ld hl,(LOOP_N1)']
    if bits.count('1') > 1:
        lines += ['ld d,h', 'ld e,l']
    for bit in bits[1:]:
        lines += ['add hl,hl', f'jp c,{fail}']
        if bit == '1':
            lines += ['add hl,de', f'jp c,{fail}']


def value_check(lines: list[str], constant: int, fail: str) -> None:
    """HL += constant (со знаком) без выхода за 0…#FFFF."""
    constant = signed16(constant)
    if constant == 0:
        return
    lines += [f'ld de,{hex16(constant)}', 'add hl,de', f'jp {"c" if constant > 0 else "nc"},{fail}']


def page_index(lines: list[str], remainder: int) -> None:
    """HL = адрес в сегменте → A = номер страницы от базы сегмента (0…4), HL = остаток + адрес."""
    if remainder:
        lines += [f'ld de,{hex16(remainder)}', 'add hl,de', 'ld a,0', 'adc a,a', 'add a,a', 'add a,a', 'ld b,a',
                  'ld a,h', 'rlca', 'rlca', 'and 3', 'or b']
    else:
        lines += ['ld a,h', 'rlca', 'rlca', 'and 3']


def page_accept(lines: list[str], segment: int, fail: str, first_w2: list[bool]) -> None:
    """A = номер страницы от базы сегмента (не рабочего ОЗУ): страница базы + номер — общая
    страница W2 цикла (LOOP_W2), рабочее ОЗУ через W2 не допускается."""
    base_page = (segment << 4) >> 14
    lines += [f'add a,#{base_page:02X}', f'cp #{WORK_PAGE:02X}', f'jp z,{fail}']
    if first_w2[0]:
        lines += ['ld (LOOP_W2),a']
        first_w2[0] = False
    else:
        lines += ['ld b,a', 'ld a,(LOOP_W2)', 'cp b', f'jp nz,{fail}']


def window_check(lines: list[str], length: int, fail: str) -> None:
    """HL = остаток + адрес начала диапазона: диапазон длины length+1 не выходит за страницу
    ((HL & #3FFF) + length <= #3FFF). Портит HL, DE."""
    if length == 0:
        return
    lines += ['ld a,h', 'and #3F', 'ld h,a', f'ld de,{hex16(0x4000 - length)}', 'or a', 'sbc hl,de',
              f'jp nc,{fail}']


def guard_lines(plan: Plan, fail: str) -> list[str]:
    """Код проверки при входе: диапазоны, страницы, IX/IY, ячейки, W2."""
    lines: list[str] = [f'{plan.guard_label}:']
    first_w2 = [True]
    runtime_count = plan.bound[0] == 'count' and plan.count is None
    if runtime_count:
        lines += ['ld hl,(V_CX)', 'ld a,h', 'or l', f'jp z,{fail}', 'dec hl', 'ld (LOOP_N1),hl']
    for register, pointer in sorted(plan.pointers.items()):
        name = REG16[register]
        remainder = (pointer.segment << 4) & 0x3FFF
        work = pointer.segment == WORK_SEGMENT
        window = 0x4000 if work else 0x8000
        span = None
        if plan.bound[0] == 'count' and plan.count is not None:
            span = (plan.count - 1) * pointer.step
        if span is not None and pointer.hi - pointer.lo + span >= 0x4000:
            lines += [f'jp {fail}']
            return lines
        # Нижняя граница диапазона: значение при входе + наименьшее смещение.
        lines += [f'ld hl,({name})']
        value_check(lines, pointer.lo, fail)
        if work:
            if span is not None:
                # Длина диапазона известна: верх = низ + длина.
                length = pointer.hi - pointer.lo + span
                lines += [f'ld de,{hex16(length)}', 'add hl,de', f'jp c,{fail}', 'ld a,h', 'cp #40', f'jp nc,{fail}']
            else:
                lines += ['ld a,h', 'cp #40', f'jp nc,{fail}']
                if runtime_count:
                    multiply_count(lines, pointer.step, fail)
                    lines += [f'ld de,({name})', 'add hl,de', f'jp c,{fail}']
                else:
                    lines += [f'ld hl,{hex16(plan.bound[2])}']
                value_check(lines, pointer.hi, fail)
                lines += ['ld a,h', 'cp #40', f'jp nc,{fail}']
            lines += [f'ld hl,({name})', f'ld de,{hex16(window)}', 'add hl,de', f'ld (LOOP_{pointer.home.upper()}),hl']
            if pointer.restored:
                lines += [f'ld hl,{hex16(window)}', f'ld (LOOP_BIAS_{pointer.home.upper()}),hl']
            continue
        if span is not None:
            # Верх диапазона без переноса за #FFFF, затем та же страница, что у низа.
            length = pointer.hi - pointer.lo + span
            lines += ['ld d,h', 'ld e,l', f'ld bc,{hex16(length)}', 'add hl,bc', f'jp c,{fail}', 'ex de,hl']
        page_index(lines, remainder)
        lines += ['ld (LOOP_PAGE),a']
        if span is not None:
            window_check(lines, length, fail)
        else:
            if runtime_count:
                multiply_count(lines, pointer.step, fail)
                lines += [f'ld de,({name})', 'add hl,de', f'jp c,{fail}']
            else:
                lines += [f'ld hl,{hex16(plan.bound[2])}']
            value_check(lines, pointer.hi, fail)
            page_index(lines, remainder)
            lines += ['ld b,a', 'ld a,(LOOP_PAGE)', 'cp b', f'jp nz,{fail}']
        lines += ['ld a,(LOOP_PAGE)']
        page_accept(lines, pointer.segment, fail, first_w2)
        # IX/IY = адрес окна для значения регистра при входе.
        lines += [f'ld hl,({name})', f'ld de,{hex16(remainder)}', 'add hl,de', 'ld a,(LOOP_PAGE)', 'and 3', 'rrca',
                  'rrca', 'ld b,a', 'ld a,h', 'sub b', 'ld h,a', f'ld de,{hex16(window)}', 'add hl,de',
                  f'ld (LOOP_{pointer.home.upper()}),hl']
        if pointer.restored or register in plan.lifted:
            lines += [f'ld de,({name})', 'or a', 'sbc hl,de', f'ld (LOOP_BIAS_{pointer.home.upper()}),hl']
    for (register, segment, disp, width), slot in sorted(plan.slots.items(), key=lambda item: item[1].name):
        remainder = (segment << 4) & 0x3FFF
        name = REG16[register]
        if segment == WORK_SEGMENT:
            # Адрес окна = #4000 + адрес; диапазон [адрес, адрес + ширина - 1] ниже #4000.
            lines += [f'ld hl,({name})']
            value_check(lines, disp, fail)
            lines += [f'ld de,{hex16(0x4000)}', 'add hl,de', 'ld a,h', 'cp #40', f'jp c,{fail}', 'cp #80',
                      f'jp nc,{fail}', f'ld ({slot.name}),hl']
            if width > 1:
                lines += [f'ld de,{hex16(width - 1)}', 'add hl,de', 'ld a,h', 'cp #80', f'jp nc,{fail}']
            continue
        lines += [f'ld hl,({name})']
        value_check(lines, disp, fail)
        if width > 1:
            lines += ['ld a,h', 'and l', 'inc a', f'jp z,{fail}']
        page_index(lines, remainder)
        lines += ['ld c,a']
        lines += ['ld a,h', 'and #3F', f'or #{0x80:02X}', 'ld (LOOP_SLOTH),a', 'ld a,l', 'ld (LOOP_SLOTL),a']
        window_check(lines, width - 1, fail)
        lines += ['ld a,c']
        page_accept(lines, segment, fail, first_w2)
        lines += ['ld a,(LOOP_SLOTL)', 'ld l,a', 'ld a,(LOOP_SLOTH)', 'ld h,a', f'ld ({slot.name}),hl']
    if plan.static_w2 is not None:
        if first_w2[0]:
            lines += [f'ld a,#{plan.static_w2:02X}', 'ld (LOOP_W2),a']
            first_w2[0] = False
        else:
            lines += ['ld a,(LOOP_W2)', f'cp #{plan.static_w2:02X}', f'jp nz,{fail}']
    lines += video_mark_lines(plan)
    if not first_w2[0]:
        lines += ['ld a,(LOOP_W2)', 'ld (W2_PAGE),a', 'set 7,a', 'ld bc,PORT_PAGE2', 'out (c),a']
    for pointer in plan.pointers.values():
        lines += [f'ld {pointer.home},(LOOP_{pointer.home.upper()})']
    for register, home in sorted(plan.values.items()):
        lines.append(f'ld {home},({REG16[register]})')
    if plan.bc_counter:
        lines.append('ld bc,(V_CX)')
    if plan.limit_counter:
        # BC = проходов до R >= imm: (imm − R + шаг − 1) >> log2(шаг), при R >= imm — 0.
        register, limit = plan.bound[1], plan.bound[2] + 1
        step = plan.pointers[register].step
        lines += [f'ld hl,{hex16(limit)}', f'ld de,({REG16[register]})', 'or a', 'sbc hl,de', 'jr nc,.limit',
                  'ld hl,#0000', '.limit:']
        if step > 1:
            lines += [f'ld de,{hex16(step - 1)}', 'add hl,de', f'jp c,{fail}'] + ['srl h', 'rr l'] * power_of_two(step)
        lines += ['ld b,h', 'ld c,l']
    return lines


def video_mark_lines(plan: Plan) -> list[str]:
    """Пометки для адаптера FT812 при входе в быструю версию: все байты, которые могут быть
    записаны за все проходы через указатели и ячейки на странице VRAM или палитры (страница —
    общая W2 цикла, проверена выше), и абсолютные записи. Лишние пометки (ранний выход из
    цикла, чтение) безопасны. Портит AF, DE, HL."""
    lines: list[str] = []
    targets: list[list[str]] = []
    for register in sorted(plan.video_pointers):
        pointer = plan.pointers[register]
        remainder = (pointer.segment << 4) & 0x3FFF
        name = REG16[register]
        # DE = адрес последнего байта, HL = адрес первого (с остатком базы сегмента).
        if plan.bound[0] == 'count' and plan.count is not None:
            end = [f'ld hl,({name})', f'ld de,{hex16(pointer.hi + remainder + (plan.count - 1) * pointer.step)}',
                   'add hl,de']
        elif plan.bound[0] == 'count':
            bits = bin(pointer.step)[2:]
            end = ['ld hl,(LOOP_N1)'] + (['ld d,h', 'ld e,l'] if bits.count('1') > 1 else [])
            for bit in bits[1:]:
                end += ['add hl,hl'] + (['add hl,de'] if bit == '1' else [])
            end += [f'ld de,({name})', 'add hl,de', f'ld de,{hex16(pointer.hi + remainder)}', 'add hl,de']
        else:
            end = [f'ld hl,{hex16(plan.bound[2] + pointer.hi + remainder)}']
        targets.append(end + ['push hl', f'ld hl,({name})', f'ld de,{hex16(pointer.lo + remainder)}', 'add hl,de',
                              'pop de'])
    for register, segment, disp, width in sorted(plan.video_slots):
        remainder = (segment << 4) & 0x3FFF
        targets.append([f'ld hl,({REG16[register]})', f'ld de,{hex16(disp + remainder)}', 'add hl,de', 'ld d,h',
                        'ld e,l'] + ['inc de'] * (width - 1))
    # Подпрограммы и push/pop — на стеке помощников (стек Z80 — это стек V30).
    if targets:
        lines += ['ld a,(LOOP_W2)', 'cp #32', 'jr c,.vmark', 'cp #37', 'jr nc,.vmark',
                  'ld (V30_SP_SAVE),sp', 'ld sp,HELPER_TOP']
        for target in targets:
            lines += target + ['ld a,h', 'and #3F', 'ld h,a', 'ld a,d', 'and #3F', 'ld d,a', 'ld a,(LOOP_W2)',
                               'call VIDEO_MARK_RANGE']
        lines += ['ld sp,(V30_SP_SAVE)', '.vmark:']
    if plan.video_absolute:
        lines += ['ld (V30_SP_SAVE),sp', 'ld sp,HELPER_TOP']
        for page, offset, width in sorted(plan.video_absolute):
            lines += [f'ld a,#{page:02X}', f'ld hl,{hex16(offset)}', f'ld de,{hex16(offset + width - 1)}',
                      'call VIDEO_MARK_RANGE']
        lines += ['ld sp,(V30_SP_SAVE)']
    return lines


def step_lines(home: str, delta: int) -> list[str]:
    if abs(delta) <= 3:
        return [f'{"inc" if delta > 0 else "dec"} {home}'] * abs(delta)
    return [f'ld de,{hex16(delta)}', f'add {home},de']


def pointer_update_lines(plan: Plan, instruction) -> list[str]:
    """Сдвиг IX/IY вслед за записью регистра-указателя."""
    lines = []
    for register in sorted(writes(instruction)):
        pointer = plan.pointers.get(register)
        if pointer is None:
            continue
        delta = constant_delta(instruction, register)
        if delta is None:
            home = pointer.home.upper()
            lines += [f'ld hl,({REG16[register]})', f'ld de,(LOOP_BIAS_{home})', 'add hl,de', f'ld (LOOP_{home}),hl',
                      f'ld {pointer.home},(LOOP_{home})']
            continue
        if abs(delta) <= 3:
            lines += [f'{"inc" if delta > 0 else "dec"} {pointer.home}'] * abs(delta)
        else:
            lines += [f'ld de,{hex16(delta)}', f'add {pointer.home},de']
    return lines


def direct_access(entry: tuple, form: str) -> list[str]:
    """Обращение быстрой версии: form — read16, read8, write16, write8 (значение в DE/A/E)."""
    kind = entry[0]
    if kind == 'ptr':
        _, home, disp = entry
        first, second = f'({home}{disp:+d})', f'({home}{disp + 1:+d})'
        return {'read16': [f'ld e,{first}', f'ld d,{second}'], 'read8': [f'ld a,{first}'],
                'write16': [f'ld {first},e', f'ld {second},d'], 'write8': [f'ld {first},e']}[form]
    if kind == 'slot':
        prefix = [f'ld hl,({entry[1]})']
        return prefix + {'read16': ['ld e,(hl)', 'inc hl', 'ld d,(hl)'], 'read8': ['ld a,(hl)'],
                         'write16': ['ld (hl),e', 'inc hl', 'ld (hl),d'], 'write8': ['ld (hl),e']}[form]
    address = hex16(entry[1])
    return {'read16': [f'ld de,({address})'], 'read8': [f'ld a,({address})'],
            'write16': [f'ld ({address}),de'], 'write8': ['ld a,e', f'ld ({address}),a']}[form]


def direct_rmw16(entry: tuple, compute: list[str]) -> list[str]:
    kind = entry[0]
    if kind == 'ptr':
        _, home, disp = entry
        return ([f'ld l,({home}{disp:+d})', f'ld h,({home}{disp + 1:+d})'] + compute +
                [f'ld ({home}{disp:+d}),l', f'ld ({home}{disp + 1:+d}),h'])
    if kind == 'slot':
        return ([f'ld hl,({entry[1]})', 'ld a,(hl)', 'inc hl', 'ld h,(hl)', 'ld l,a'] + compute +
                ['ex de,hl', f'ld hl,({entry[1]})', 'ld (hl),e', 'inc hl', 'ld (hl),d'])
    address = hex16(entry[1])
    return [f'ld hl,({address})'] + compute + [f'ld ({address}),hl']


def direct_rmw8(entry: tuple, compute) -> list[str]:
    kind = entry[0]
    if kind == 'ptr':
        _, home, disp = entry
        return [f'ld a,({home}{disp:+d})'] + compute(False) + [f'ld ({home}{disp:+d}),a']
    if kind == 'slot':
        return [f'ld hl,({entry[1]})', 'ld a,(hl)'] + compute(True) + ['ld (hl),a']
    address = hex16(entry[1])
    return [f'ld a,({address})'] + compute(False) + [f'ld ({address}),a']
