"""Оптимизация сгенерированного текста Z80: повторные загрузки и мёртвые пересылки.

Прямой проход идёт по тексту страницы кода и для каждого 8-битного регистра Z80 хранит
множество известных равенств: байт переменной резидента (после `ld hl,(V_BX)`,
`ld (V_BX),hl`, `ld a,(V_FL)`…) или константа. Загрузка, результат которой уже в регистре,
удаляется; загрузка байта или пары, значения которых лежат в других регистрах, заменяется
пересылками регистров; запись в переменную того же значения удаляется. Равенства
сбрасываются на метках, в которые можно попасть не только сверху (цели переходов и входы
диспетчеризации), после вызовов подпрограмм и на любой команде, влияние которой проход не
знает. Локальные метки фрагментов (переходы только вперёд) получают пересечение равенств
всех переходов на них.

Обратный проход удаляет записи регистров V30 в резиденте, не читаемые до перезаписи, и
пересылки в регистры Z80 (`ld`), значение которых не читается до перезаписи. Переход на
нелокальную метку, вызов подпрограммы и незнакомая команда считают живыми все регистры Z80.

Запись через указатель ((hl), (de), (bc), (ix+d)) считается записью в окна данных V30,
кроме пары, загруженной символическим адресом (`ld hl,V_FL`): тогда сбрасывается всё.
"""
from __future__ import annotations

import re

R8 = ('a', 'b', 'c', 'd', 'e', 'h', 'l')
PAIRS = {'hl': ('h', 'l'), 'de': ('d', 'e'), 'bc': ('b', 'c')}       # (старший, младший)
LABEL = re.compile(r'^(\.?[A-Za-z_][\w.]*):')
SYMBOL = re.compile(r'^([A-Za-z_]\w*)(?:\+(\d+))?$')
NUMBER = re.compile(r'^(?:#[0-9A-Fa-f]+|\d+)$')
# Смещения регистров V30 от V_AX (DW подряд): V_BX+1 и V_AX+7 — один байт.
V30_OFFSETS = {name: 2 * index for index, name in enumerate(
    ('V_AX', 'V_CX', 'V_DX', 'V_BX', 'V_SP', 'V_BP', 'V_SI', 'V_DI', 'V_ES', 'V_CS', 'V_SS', 'V_DS', 'V_FL', 'V_IP'))}
V30_OFFSETS.update({'V_REG': 0, 'V_SREG': 16})
INPUT_OFFSETS = {'IN0': 0, 'IN1': 2, 'DSW': 4}


def symbol(text: str) -> tuple[str, int] | None:
    match = SYMBOL.match(text.strip())
    if not match:
        return None
    return match[1], int(match[2] or 0)


def number(text: str) -> int | None:
    if not NUMBER.match(text):
        return None
    return int(text[1:], 16) if text.startswith('#') else int(text)


def place_of(name: str, offset: int) -> tuple:
    """Байт переменной резидента с учётом совпадающих адресов разных имён."""
    if name in V30_OFFSETS:
        return ('V', V30_OFFSETS[name] + offset)
    if name in INPUT_OFFSETS:
        return ('IN', INPUT_OFFSETS[name] + offset)
    return (name, offset)


def memory_place(operand: str) -> tuple | None:
    """`(имя+смещение)` — байт переменной резидента; окна V30 (`(#6EC1)`), регистры — None."""
    if not (operand.startswith('(') and operand.endswith(')')):
        return None
    inner = operand[1:-1].strip()
    if inner in ('hl', 'de', 'bc', 'sp', 'c') or inner.startswith(('ix', 'iy', '#')) or number(inner) is not None:
        return None
    parsed = symbol(inner)
    if parsed is None:
        return None
    return place_of(*parsed)


def next_place(place: tuple) -> tuple:
    return (place[0], place[1] + 1)


def parse(text: str) -> tuple[str, list[str]]:
    parts = text.split(None, 1)
    mnemonic = parts[0]
    operands = [item.strip() for item in parts[1].split(',')] if len(parts) > 1 else []
    return mnemonic, operands


class Facts:
    """Регистр Z80 → множество равенств: ('V', смещение) / (имя, смещение) — байт переменной,
    ('k', байт) — константа, ('sym', текст) — байт символического адреса; байт переменной →
    известная константа (mem)."""

    def __init__(self) -> None:
        self.reg: dict[str, frozenset] = {register: frozenset() for register in R8}
        self.mem: dict[tuple, int] = {}

    def copy(self) -> 'Facts':
        other = Facts()
        other.reg = dict(self.reg)
        other.mem = dict(self.mem)
        return other

    def intersect(self, other: 'Facts') -> None:
        for register in R8:
            self.reg[register] = self.reg[register] & other.reg[register]
        self.mem = {place: value for place, value in self.mem.items() if other.mem.get(place) == value}

    def clear(self) -> None:
        for register in R8:
            self.reg[register] = frozenset()
        self.mem.clear()

    def kill(self, *registers: str) -> None:
        for register in registers:
            self.reg[register] = frozenset()

    def kill_place(self, place: tuple) -> None:
        self.mem.pop(place, None)
        for register in R8:
            if place in self.reg[register]:
                self.reg[register] = self.reg[register] - {place}

    def constant(self, register: str) -> int | None:
        return next((token[1] for token in self.reg[register] if token[0] == 'k'), None)

    def store(self, place: tuple, register: str) -> bool:
        """Запись регистра в байт переменной; True — там уже это значение."""
        value = self.constant(register)
        if place in self.reg[register] or (value is not None and self.mem.get(place) == value):
            self.reg[register] = self.reg[register] | {place}
            return True
        self.kill_place(place)
        self.reg[register] = self.reg[register] | {place}
        if value is not None:
            self.mem[place] = value
        return False

    def source(self, place: tuple, target: str):
        """Откуда взять байт переменной в регистр target: target (уже там), другой регистр,
        ('k', константа) или None."""
        if place in self.reg[target]:
            return target
        holder = self.holder(place)
        if holder is not None:
            return holder
        value = self.mem.get(place)
        if value is None:
            return None
        token = ('k', value)
        if token in self.reg[target]:
            return target
        holder = self.holder(token)
        return holder if holder is not None else token

    def holder(self, token: tuple, exclude: tuple = ()) -> str | None:
        for register in ('a', 'e', 'd', 'l', 'h', 'c', 'b'):
            if register not in exclude and token in self.reg[register]:
                return register
        return None

    def pointer_to_resident(self, pair: str) -> bool:
        high, low = PAIRS[pair]
        return any(token[0] == 'sym' for token in self.reg[high] | self.reg[low])


# Регистры V30 в резиденте: записи в них, не читаемые до перезаписи, удаляются.
TRACKED = ('V_AX', 'V_CX', 'V_DX', 'V_BX', 'V_SP', 'V_BP', 'V_SI', 'V_DI')
ALL_BYTES = frozenset((name, offset) for name in TRACKED for offset in (0, 1))
ALL_Z80 = frozenset(('r', register) for register in R8)
ALL_LIVE = ALL_BYTES | ALL_Z80
# Какие регистры V30 читают подпрограммы резидента (остальные вызовы — все регистры).
CALL_READS = {
    **{f'{kind}_{seg}': () for kind in ('RB', 'RW', 'WB', 'WW') for seg in ('ES', 'CS', 'SS', 'DS')},
    **{f'SEGSET_{seg}': () for seg in ('ES', 'CS', 'SS', 'DS')},
    'FLG_AR8': (), 'FLG_LOG8': (), 'FLG_INC8': (), 'FLG_AR16': (), 'FLG_LOG16': (), 'FLG_INC16': (),
    'COND_SF_XOR_OF': (), 'COND_LE': (), 'SET_FLAGS': (), 'PORT_IN': (), 'PORT_OUT': (),
    **{f'SH_{kind}{width}': () for kind in ('SHL', 'SHR', 'SAR', 'RCL', 'RCR') for width in (8, 16)},
    'DAA_OP': ('V_AX',), 'DAS_OP': ('V_AX',), 'ADD4S': ('V_CX', 'V_SI', 'V_DI'),
    'REP_MOVSW_FAST': ('V_AX', 'V_CX', 'V_SI', 'V_DI'),
    'VIDEO_W2_MARK1': (), 'VIDEO_W2_MARK2': (), 'VIDEO_W2_MARK2BC': (), 'VIDEO_MARK_DE': (),
}
# Подпрограммы, не меняющие V_AX…V_DI (пишут окна данных V30, W2_PAGE, LIN_PAGE, V_xS, V_FL
# и свои переменные): константы этих регистров переживают вызов.
CALLS_KEEPING_REGISTERS = frozenset(
    [f'{kind}_{seg}' for kind in ('RB', 'RW', 'WB', 'WW', 'SEGSET') for seg in ('ES', 'CS', 'SS', 'DS')] +
    ['FLG_AR8', 'FLG_LOG8', 'FLG_INC8', 'FLG_AR16', 'FLG_LOG16', 'FLG_INC16', 'FLG_SHIFT16', 'FLG_SHIFT8',
     'SET_OF_B', 'STORE_LOW_PE', 'RC_FLAGS', 'COND_SF_XOR_OF', 'COND_LE', 'SET_FLAGS',
     'SH_SHL16', 'SH_SHR16', 'SH_SAR16', 'SH_SHL8', 'SH_SHR8', 'SH_RCL8', 'SH_RCR8',
     'VIDEO_W2_MARK1', 'VIDEO_W2_MARK2', 'VIDEO_W2_MARK2BC', 'VIDEO_MARK_DE'])
# Подпрограммы пометок видеопамяти: регистры и переменные регистров V30 не меняются.
CALLS_PRESERVING_ALL = frozenset(('VIDEO_W2_MARK1', 'VIDEO_W2_MARK2', 'VIDEO_W2_MARK2BC'))
STORE = re.compile(r'^ld \((V_[A-Z]{2})(?:\+(\d))?\),(hl|de|bc|a)$')
LOAD = re.compile(r'^ld (hl|de|bc|a),\((V_[A-Z]{2})(?:\+(\d))?\)$')
# 8-битные операции над A: читают A и второй операнд, пишут A (кроме cp).
A_OPERATIONS = {'add', 'adc', 'sub', 'sbc', 'and', 'or', 'xor', 'cp'}
SHIFTS = {'srl', 'sra', 'sla', 'sll', 'rl', 'rr', 'rlc', 'rrc'}
ACCUMULATOR = {'rla', 'rra', 'rlca', 'rrca', 'cpl', 'neg', 'daa'}


def register_uses(text: str) -> tuple[frozenset, frozenset, bool] | None:
    """(читает, пишет, удаляемая пересылка) для регистров Z80 или None — команда незнакома."""
    mnemonic, operands = parse(text)

    def reads_of(operand: str) -> set:
        if operand in R8:
            return {operand}
        if operand in PAIRS:
            return set(PAIRS[operand])
        if operand in ('(hl)', '(de)', '(bc)'):
            return set(PAIRS[operand[1:-1]])
        return set()

    def pack(reads, writes, removable=False):
        return (frozenset(('r', item) for item in reads), frozenset(('r', item) for item in writes), removable)

    if mnemonic == 'ld' and len(operands) == 2:
        dst, src = operands
        if dst in R8:
            return pack(reads_of(src), {dst}, True)
        if dst in PAIRS:
            return pack(reads_of(src) if src in PAIRS else set(), set(PAIRS[dst]), True)
        if dst in ('sp', 'ix', 'iy'):
            return pack(reads_of(src), set())
        # Запись в память: читает приёмник-указатель и источник.
        return pack(reads_of(dst) | reads_of(src), set())
    if mnemonic == 'ex' and operands == ['de', 'hl']:
        return None                     # обрабатывается отдельно
    if mnemonic == 'push':
        return pack(reads_of(operands[0]) | ({'a'} if operands[0] == 'af' else set()), set())
    if mnemonic == 'pop':
        return pack(set(), set(PAIRS[operands[0]]) if operands[0] in PAIRS else ({'a'} if operands[0] == 'af' else set()))
    if mnemonic in ('add', 'adc', 'sbc') and len(operands) == 2 and operands[0] in ('hl', 'ix', 'iy'):
        reads = reads_of(operands[1])
        if operands[0] == 'hl':
            return pack(reads | {'h', 'l'}, {'h', 'l'})
        return pack(reads, set())
    if mnemonic in A_OPERATIONS:
        source = operands[-1] if operands else 'a'
        if mnemonic in ('xor', 'sub') and source == 'a':
            return pack(set(), {'a'})
        return pack({'a'} | reads_of(source), set() if mnemonic == 'cp' else {'a'})
    if mnemonic in ACCUMULATOR:
        return pack({'a'}, {'a'})
    if mnemonic in ('inc', 'dec') and operands:
        target = operands[0]
        if target in R8:
            return pack({target}, {target})
        if target in PAIRS:
            return pack(set(PAIRS[target]), set(PAIRS[target]))
        return pack(reads_of(target), set())
    if mnemonic in SHIFTS and operands:
        target = operands[0]
        if target in R8:
            return pack({target}, {target})
        return pack(reads_of(target), set())
    if mnemonic in ('set', 'res', 'bit') and len(operands) == 2:
        target = operands[1]
        if target in R8:
            return pack({target}, set() if mnemonic == 'bit' else {target})
        return pack(reads_of(target), set())
    if mnemonic == 'out':
        return pack({'a', 'b', 'c'}, set())
    if mnemonic == 'in':
        return pack({'b', 'c'}, {operands[0]} if operands and operands[0] in R8 else set())
    if mnemonic in ('scf', 'ccf', 'nop'):
        return pack(set(), set())
    if mnemonic == 'ex' and operands == ['af', "af'"]:
        return pack({'a'}, {'a'})
    return None


def dead_stores(lines: list[str], backward: set[str] = frozenset()) -> list[str]:
    """Обратный проход: удаляются запись регистра V30, которую до перезаписи не читает ни одна
    строка, ни подпрограмма (по CALL_READS), ни переход за пределы текста, и пересылка в
    регистры Z80, значение которых не читается до перезаписи."""
    scopes = []
    scope = ''
    for raw in lines:
        text = raw.split(';')[0].strip()
        label = LABEL.match(text)
        if label and not label[1].startswith('.'):
            scope = label[1]
        scopes.append(scope)
    live: set = set(ALL_LIVE)
    at_label: dict[str, frozenset] = {}
    keep = [True] * len(lines)
    for index in range(len(lines) - 1, -1, -1):
        text = lines[index].split(';')[0].strip()
        if not text:
            continue
        label = LABEL.match(text)
        if label:
            name = label[1]
            if name.startswith('.'):
                at_label[scopes[index] + name] = frozenset(live)
            continue
        mnemonic, operands = parse(text)
        if mnemonic in ('jp', 'jr', 'djnz'):
            target = operands[-1] if operands else ''
            conditional = len(operands) == 2 or mnemonic == 'djnz'
            key = scopes[index] + target
            if target == '(hl)':
                target_live = ALL_LIVE
            elif target.startswith('.') and key in at_label and key not in backward:
                target_live = at_label[key]
            else:
                target_live = ALL_LIVE
            live = set(target_live) | (live if conditional else set())
            if mnemonic == 'djnz':
                live.add(('r', 'b'))
            continue
        if mnemonic == 'ret':
            live = set(ALL_LIVE)
            continue
        if mnemonic == 'call':
            name = operands[-1] if operands else ''
            reads = CALL_READS.get(name)
            if reads is None:
                live = set(ALL_LIVE)
            else:
                live |= {(item, offset) for item in reads for offset in (0, 1)}
                live |= ALL_Z80
            continue
        if mnemonic == 'ex' and operands == ['de', 'hl']:
            swapped = set()
            for item in live:
                if item[0] == 'r' and item[1] in 'dehl':
                    swapped.add(('r', {'d': 'h', 'h': 'd', 'e': 'l', 'l': 'e'}[item[1]]))
                else:
                    swapped.add(item)
            live = swapped
            continue
        store = STORE.match(text)
        if store and store[1] in TRACKED:
            name, offset, source = store[1], int(store[2] or 0), store[3]
            written = {(name, offset)} if source == 'a' else {(name, offset), (name, offset + 1)}
            if not written & live:
                keep[index] = False
                continue
            live -= written
            live |= {('r', item) for item in (PAIRS[source] if source in PAIRS else (source,))}
            continue
        uses = register_uses(text)
        if uses is not None:
            reads, writes, removable = uses
            if removable and writes and not writes & live:
                keep[index] = False
                continue
            live -= writes
            live |= reads
        else:
            live |= ALL_Z80
        load = LOAD.match(text)
        if load and load[2] in TRACKED:
            name, offset, target = load[2], int(load[3] or 0), load[1]
            live |= {(name, offset)} if target == 'a' else {(name, offset), (name, offset + 1)}
            continue
        if 'V_' in text or mnemonic in ('MMU', 'ORG'):
            for item in TRACKED:
                if item in text:
                    live |= {(item, 0), (item, 1)}
            if mnemonic in ('MMU', 'ORG'):
                live = set(ALL_LIVE)
    return [line for line, kept in zip(lines, keep) if kept]


REFERENCE = re.compile(r'\b([AFG]_[0-9A-F]{5}(?:_[0-9A-F]{5})?)\b')


def merge_points(lines: list[str], entries: set[str]) -> tuple[set[str], set[str]]:
    """(метки инструкций с переходами на них, локальные метки с переходом назад)."""
    labels = set(entries)
    backward = set()
    scope = ''
    defined = set()
    for raw in lines:
        text = raw.split(';')[0].strip()
        label = LABEL.match(text)
        if label:
            name = label[1]
            if name.startswith('.'):
                defined.add(scope + name)
            else:
                scope = name
            continue
        labels.update(REFERENCE.findall(text))
        parts = text.split(None, 1)
        if parts and parts[0] in ('jr', 'jp', 'djnz') and len(parts) > 1:
            target = parts[1].split(',')[-1].strip()
            if target.startswith('.') and scope + target in defined:
                backward.add(scope + target)
    return labels, backward


def optimize(lines: list[str], merge_labels: set[str], backward: set[str] = frozenset()) -> list[str]:
    """Текст страницы кода → текст без повторных загрузок. merge_labels — метки, в которые
    приходят переходы извне порядка текста (цели переходов, входы); backward — локальные
    метки, на которые есть переход назад."""
    out: list[str] = []
    facts = Facts()
    pending: dict[str, Facts] = {}      # локальные метки: пересечение равенств переходов
    reachable = True                    # текущая строка достижима сверху
    scope = ''
    for raw in lines:
        text = raw.split(';')[0].strip()
        if not text:
            out.append(raw)
            continue
        label = LABEL.match(text)
        if label:
            name = label[1]
            if not name.startswith('.'):
                scope = name
                key = name
            else:
                key = scope + name
            if name.startswith('.'):
                incoming = pending.pop(key, None)
                if key in backward:
                    facts = Facts()
                elif not reachable:
                    facts = incoming.copy() if incoming is not None else Facts()
                elif incoming is not None:
                    facts.intersect(incoming)
            elif name in merge_labels or not reachable:
                facts.clear()
            reachable = True
            out.append(raw)
            continue
        if not reachable:
            out.append(raw)
            continue
        replacement = transfer(text, facts, pending, scope)
        if replacement is None:
            out.append(raw)
        else:
            out.extend('\t' + line for line in replacement)
        mnemonic = text.split()[0]
        if mnemonic in ('jp', 'jr') and ',' not in text or text.startswith(('jp (hl)', 'ret')):
            reachable = False
    return out


def pair_copy(facts: Facts, pair: str, low_place: tuple) -> list[str] | None:
    """Пересылки и константы, дающие паре значение байтов low_place и следующего, если они
    известны; равенства пары обновляются."""
    high, low = PAIRS[pair]
    high_place = next_place(low_place)
    source_high = facts.source(high_place, high)
    source_low = facts.source(low_place, low)
    if source_high is None or source_low is None:
        return None
    if source_high == low and source_low == high:
        return None                     # обмен пересылками не выразить

    def value_of(source):
        return frozenset({source}) if isinstance(source, tuple) else facts.reg[source]
    new_high = value_of(source_high) | {high_place}
    new_low = value_of(source_low) | {low_place}
    lines = []
    if isinstance(source_high, tuple) and isinstance(source_low, tuple):
        lines = [f'ld {pair},#{(source_high[1] << 8) | source_low[1]:04X}']
    else:
        order = [(low, source_low), (high, source_high)] if source_low == high else \
            [(high, source_high), (low, source_low)]
        for target, source in order:
            if isinstance(source, tuple):
                lines.append(f'ld {target},#{source[1]:02X}')
            elif target != source:
                lines.append(f'ld {target},{source}')
    facts.reg[high], facts.reg[low] = new_high, new_low
    return lines


def transfer(text: str, facts: Facts, pending: dict[str, Facts], scope: str) -> list[str] | None:
    """Применить строку к равенствам; вернуть замену строки (список строк) или None — оставить."""
    mnemonic, operands = parse(text)

    if mnemonic in ('jr', 'jp', 'djnz'):
        if mnemonic == 'djnz':
            facts.kill('b')
        target = operands[-1] if operands else ''
        if target.startswith('.'):
            key = scope + target
            if key in pending:
                pending[key].intersect(facts)
            else:
                pending[key] = facts.copy()
        return None
    if mnemonic == 'ld' and len(operands) == 2:
        dst, src = operands
        if dst in R8:
            if src in R8:
                if facts.reg[dst] & facts.reg[src]:
                    return []
                facts.reg[dst] = facts.reg[src]
                return None
            value = number(src)
            if value is not None:
                token = ('k', value & 0xFF)
                if token in facts.reg[dst]:
                    return []
                facts.reg[dst] = frozenset({token})
                return None
            place = memory_place(src)
            if place is not None and dst == 'a':
                source = facts.source(place, 'a')
                if source == 'a':
                    facts.reg['a'] = facts.reg['a'] | {place}
                    return []
                if source is None:
                    facts.reg['a'] = frozenset({place})
                    return None
                if isinstance(source, tuple):
                    facts.reg['a'] = frozenset({source, place})
                    return [f'ld a,#{source[1]:02X}']
                facts.reg['a'] = facts.reg[source] | {place}
                return [f'ld a,{source}']
            facts.kill(dst)
            return None
        if dst in PAIRS:
            high, low = PAIRS[dst]
            value = number(src)
            if value is not None:
                tokens = (('k', (value >> 8) & 0xFF), ('k', value & 0xFF))
                if tokens[0] in facts.reg[high] and tokens[1] in facts.reg[low]:
                    return []
                facts.reg[high], facts.reg[low] = frozenset({tokens[0]}), frozenset({tokens[1]})
                return None
            place = memory_place(src)
            if place is not None:
                copy = pair_copy(facts, dst, place)
                if copy is not None:
                    return copy
                facts.reg[high] = frozenset({next_place(place)})
                facts.reg[low] = frozenset({place})
                return None
            facts.kill(high, low)
            if src in PAIRS:
                return None             # ld hl,de не бывает
            if symbol(src) is not None:
                facts.reg[high] = facts.reg[low] = frozenset({('sym', src)})
            return None
        if dst in ('sp', 'ix', 'iy'):
            return None
        place = memory_place(dst)
        if place is not None:
            if src == 'a':
                return [] if facts.store(place, 'a') else None
            if src in PAIRS:
                high, low = PAIRS[src]
                same_low = facts.store(place, low)
                same_high = facts.store(next_place(place), high)
                return [] if same_low and same_high else None
            facts.kill_place(place)
            facts.kill_place(next_place(place))
            return None
        if dst.startswith('(') and dst.endswith(')'):
            inner = dst[1:-1].strip()
            address = number(inner)
            if address is not None:
                if address < 0x4000:
                    facts.clear()       # переменная резидента по числовому адресу
                return None             # окно данных V30
            if inner in PAIRS:
                if facts.pointer_to_resident(inner):
                    facts.clear()
                return None
            if inner.startswith(('ix', 'iy')):
                return None
        facts.clear()
        return None
    if mnemonic == 'ex' and operands == ['de', 'hl']:
        reg = facts.reg
        reg['d'], reg['h'] = reg['h'], reg['d']
        reg['e'], reg['l'] = reg['l'], reg['e']
        return None
    if mnemonic == 'push':
        return None
    if mnemonic == 'pop':
        if operands[0] in PAIRS:
            facts.kill(*PAIRS[operands[0]])
        elif operands[0] == 'af':
            facts.kill('a')
        return None
    if mnemonic in A_OPERATIONS:
        source = operands[-1] if operands else 'a'
        if mnemonic == 'cp':
            return None
        if mnemonic in ('and', 'or') and source == 'a':
            return None
        if mnemonic in ('xor', 'sub') and source == 'a':
            facts.reg['a'] = frozenset({('k', 0)})
            return None
        if mnemonic in ('add', 'adc', 'sbc') and len(operands) == 2 and operands[0] != 'a':
            target = operands[0]
            if target in PAIRS:
                facts.kill(*PAIRS[target])
                return None
            if target in ('ix', 'iy', 'sp'):
                return None
            facts.clear()
            return None
        facts.kill('a')
        return None
    if mnemonic in ACCUMULATOR:
        facts.kill('a')
        return None
    if mnemonic in ('inc', 'dec') and operands:
        target = operands[0]
        if target in R8:
            facts.kill(target)
            return None
        if target in PAIRS:
            facts.kill(*PAIRS[target])
            return None
        if target in ('ix', 'iy', 'sp'):
            return None
        inner = target[1:-1] if target.startswith('(') else ''
        if inner in PAIRS and not facts.pointer_to_resident(inner) or inner.startswith(('ix', 'iy')):
            return None
        facts.clear()
        return None
    if mnemonic in SHIFTS and operands:
        target = operands[0]
        if target in R8:
            facts.kill(target)
            return None
        facts.clear()
        return None
    if mnemonic in ('set', 'res') and len(operands) == 2:
        target = operands[1]
        if target in R8:
            facts.kill(target)
            return None
        # (hl) при HL = адрес переменной (ld hl,V_FL) — запись в переменную.
        facts.clear()
        return None
    if mnemonic in ('bit', 'scf', 'ccf', 'nop', 'di', 'ei', 'out'):
        return None
    if mnemonic == 'in':
        if operands and operands[0] in R8:
            facts.kill(operands[0])
            return None
    if mnemonic == 'ex' and operands == ['af', "af'"]:
        facts.kill('a')
        return None
    if mnemonic == 'call' and operands and operands[-1] in CALLS_PRESERVING_ALL:
        return None                     # пометки видеопамяти сохраняют регистры и переменные
    if mnemonic == 'call' and operands and operands[-1] in CALLS_KEEPING_REGISTERS:
        # Подпрограммы памяти, сегментов и флагов не пишут регистры V30 общего назначения.
        kept = {place: value for place, value in facts.mem.items() if place[0] == 'V' and place[1] < 16}
        facts.clear()
        facts.mem.update(kept)
        return None
    # call, ldir, rst, exx и всё прочее — равенства неизвестны.
    facts.clear()
    return None
