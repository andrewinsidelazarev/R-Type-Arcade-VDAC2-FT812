"""Декодер программы звукового Z80 R-Type (Irem M72, World): команды, части, байт-код дорожек, инструменты.

Реверс-инжиниринг 2026-09-16 по образу Build/Analysis/rtype_sound_upload.bin (32 КиБ, загружается V30 в ОЗУ
звукового Z80), дизассемблер и трасса исполнения в оракуле rtype_m72.sound.

Устройство драйвера:
  * такт — прерывание таймера A YM2151 (RST $28, `$0076`): регистр $10 = $C8, TA = 800, период 64·(1024−800)
    тактов Z80 = 224 сэмпла YM2151 (≈ 249.7 Гц); главный цикл (`$02E8`) на каждый такт проходит 16 дорожек;
  * команда latch ($00…$7F после AND $7F, `$0068`): указатель в таблице `$1000`; заголовок — старшие 4 бита тип
    ($00 обычная, $10 привязана к голосу другой команды и заменяет его дорожки, $20 затухание), младшие 3 бита —
    частей − 1; у типа $10 затем байт голоса; дальше слова-указатели частей; первый байт части — приоритет
    (меньше — важнее: мелодии 1), за ним байт-код;
  * дорожка — 16 байт в `$FF00 + 16·n`: +0 приоритет (0 свободна, $80/$81 — служебные модуляция/портаменто),
    +1 команда, +2 канал YM2151, +3 номер части (бит 7 — ждёт снятия ноты, бит 6 — громкость со сдвигом),
    +4 глубина стека вызовов, +5 темп, +6 гейт (G — младший, H — старший полубайт), +7 октава (старший) и маска
    несущих (младший), +8 длина по умолчанию, +9/+10 указатель байт-кода, +11 служебная дорожка, +12/+13 такты до
    снятия ноты, +14/+15 такты до следующего опкода;
  * опкод: группа — старшие 5 бит (таблица переходов `$035E`), см. OPCODES.

Длина ноты (`$0422`): байт длины (из данных у опкода $01/$09, иначе +8): биты 0…5 дают 4·темп, 2·темп, темп, темп/2,
темп/4, темп/8 тактов (сдвиги целочисленные, накопительно), бит 7 — деление итога на 3. Гейт: G = 0 — нота
держится до следующего опкода; иначе снятие через итог // G · H тактов. KC ноты (`$03CD`) = (октава << 4 | байт
ноты) − 2. Перед нотой при флаге `$F872` (опкод LFO) пишется регистр 1 = 2, затем 0 — сброс фазы LFO.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE_PATH = ROOT / 'Build' / 'Analysis' / 'rtype_sound_upload.bin'
COMMAND_TABLE = 0x1000
INSTRUMENT_TABLE = 0x134C          # 29 байт на инструмент
INSTRUMENT_SIZE = 29
VOLUME_TABLE = 0x1678              # 4 байта TL на запись
MODULATION_TABLE = 0x19A4          # 4 байта на запись
TICK_SAMPLES = 224                 # сэмплов YM2151 (3 579 545 / 64 Гц) на такт драйвера
TICK_RATE = 3_579_545 / 64 / TICK_SAMPLES

OPCODES = {
    0x00: 'нота', 0x08: 'пауза', 0x10: 'громкость', 0x18: 'длина', 0x20: 'октава', 0x28: 'гейт',
    0x30: 'инструмент', 0x38: 'регистр', 0x40: 'LFO', 0x48: 'модуляция', 0x50: 'без модуляции',
    0x58: 'вызов', 0x60: 'возврат', 0x68: 'темп', 0x70: 'переход', 0x78: 'октава+', 0x80: 'октава−',
    0x88: 'портаменто',
}


@dataclass
class Command:
    number: int
    kind: int
    parts: list[int]              # адреса частей (байт приоритета)
    voice: int | None = None


@dataclass
class Event:
    tick: int
    kind: str
    data: tuple = ()


@dataclass
class TrackState:
    pc: int
    octave: int = 0
    carriers: int = 0
    tempo: int = 0
    gate: int = 0
    default_length: int = 0
    stack: list[int] = field(default_factory=list)
    lfo_sync: int = 0


class Driver:
    def __init__(self, image: bytes | None = None) -> None:
        self.image = image if image is not None else IMAGE_PATH.read_bytes()

    def byte(self, address: int) -> int:
        return self.image[address & 0xFFFF]

    def word(self, address: int) -> int:
        return self.byte(address) | (self.byte(address + 1) << 8)

    def command(self, number: int) -> Command:
        number &= 0x7F
        pointer = self.word(COMMAND_TABLE + number * 2)
        header = self.byte(pointer)
        kind = header & 0xF0
        count = (header & 7) + 1
        at = pointer + 1
        voice = None
        if kind == 0x10:
            voice = self.byte(at)
            at += 1
        parts = []
        if kind in (0x00, 0x10):
            for _ in range(count):
                parts.append(self.word(at))
                at += 2
        return Command(number, kind, parts, voice)

    def instrument(self, index: int) -> bytes:
        start = INSTRUMENT_TABLE + index * INSTRUMENT_SIZE
        return self.image[start:start + INSTRUMENT_SIZE]

    @staticmethod
    def length_ticks(length: int, tempo: int) -> int:
        """`$0428…$0446`: сумма долей темпа по битам 0…5, бит 7 — деление на 3."""
        de = (tempo * 4) & 0xFFFF
        total = 0
        bits = length & 0x7F
        for _ in range(6):
            if bits & 1:
                total = (total + de) & 0xFFFF
            bits >>= 1
            de >>= 1
        if length & 0x80:
            total //= 3
        return total

    def simulate(self, part_address: int, max_ticks: int, max_ops: int = 200_000,
                 on_jump=None) -> list[Event]:
        """События одной части: нажатия (KC), снятия, инструменты, LFO и прочее — в тактах от запуска.

        on_jump(такт, адрес перехода, состояние) вызывается на каждом опкоде перехода; True — остановить разбор."""
        state = TrackState(pc=part_address + 1)
        events: list[Event] = []
        tick = 0
        ops = 0
        while tick < max_ticks and ops < max_ops:
            op = self.byte(state.pc)
            group = op & 0xF8
            ops += 1
            address = state.pc
            state.pc += 1
            if group in (0x00, 0x08, 0x88):
                if group == 0x88:
                    # `$06EF`: два байта — начальный и конечный KC плюс 2 (без октавы дорожки), третий — длина
                    start_kc = (self.byte(state.pc) - 2) & 0xFF
                    end_kc = (self.byte(state.pc + 1) - 2) & 0xFF
                    length = self.byte(state.pc + 2)
                    state.pc += 3
                    if state.lfo_sync:
                        events.append(Event(tick, 'сброс LFO'))
                    events.append(Event(tick, 'нажатие', (start_kc,)))
                    events.append(Event(tick, 'портаменто', (start_kc, end_kc)))
                else:
                    kc = None
                    if group == 0x00:
                        note = self.byte(state.pc)
                        state.pc += 1
                        kc = ((state.octave << 4) | note) - 2 & 0xFF
                    if op & 7 == 1:
                        length = self.byte(state.pc)
                        state.pc += 1
                    else:
                        length = state.default_length
                    if kc is not None:
                        if state.lfo_sync:
                            events.append(Event(tick, 'сброс LFO'))
                        events.append(Event(tick, 'нажатие', (kc,)))
                total = self.length_ticks(length, state.tempo)
                g, h = state.gate & 0x0F, state.gate >> 4
                if g and group != 0x08:
                    off = (total // g) * h
                    events.append(Event(tick + off, 'снятие'))
                tick += max(total, 1)
                continue
            if group == 0x10:
                events.append(Event(tick, 'громкость', (self.byte(state.pc),)))
                state.pc += 1
            elif group == 0x18:
                state.default_length = self.byte(state.pc) & 0x7F
                state.pc += 1
            elif group == 0x20:
                state.octave = self.byte(state.pc) & 0x0F
                state.pc += 1
            elif group == 0x28:
                state.gate = ((self.byte(state.pc) & 0x0F) << 4) | (self.byte(state.pc + 1) & 0x0F)
                state.pc += 2
            elif group == 0x30:
                index = self.byte(state.pc)
                state.pc += 1
                record = self.instrument(index)
                algorithm = record[1] & 7
                state.carriers = (0x08, 0x08, 0x08, 0x08, 0x0C, 0x0E, 0x0E, 0x0F)[algorithm]
                events.append(Event(tick, 'инструмент', (index,)))
            elif group == 0x38:
                events.append(Event(tick, 'регистр', (self.byte(state.pc), self.byte(state.pc + 1))))
                state.pc += 2
            elif group == 0x40:
                params = tuple(self.byte(state.pc + k) for k in range(5))
                state.lfo_sync = params[4]
                state.pc += 5
                events.append(Event(tick, 'LFO', params))
            elif group == 0x48:
                events.append(Event(tick, 'модуляция', (self.byte(state.pc),)))
                state.pc += 1
            elif group == 0x50:
                events.append(Event(tick, 'без модуляции'))
            elif group == 0x58:
                offset = self.word(state.pc)
                state.stack.append(state.pc + 2)
                state.pc = (address + offset) & 0xFFFF
            elif group == 0x60:
                if not state.stack:
                    events.append(Event(tick, 'конец', ('возврат без вызова',)))
                    break
                state.pc = state.stack.pop()
            elif group == 0x68:
                state.tempo = self.byte(state.pc)
                state.pc += 1
            elif group == 0x70:
                offset = self.word(state.pc)
                target = (address + offset) & 0xFFFF
                events.append(Event(tick, 'переход', (address, target)))
                if on_jump is not None and on_jump(tick, target, state):
                    break
                state.pc = target
            elif group == 0x78:
                state.octave = (state.octave + 1) & 0x0F
            elif group == 0x80:
                state.octave = (state.octave - 1) & 0x0F
            else:
                events.append(Event(tick, 'конец', (op,)))
                break
        return events

    def part_shape(self, part_address: int, max_ticks: int = 1_000_000) -> tuple[str, int]:
        """('петля', период в тактах) — на переходе повторилось состояние дорожки (адрес, октава, темп, гейт,
        длина, несущие, стек вызовов, флаг LFO); ('конец', такт опкода конца)."""
        seen: dict[tuple, int] = {}
        period: list[int] = []

        def on_jump(tick: int, target: int, state: TrackState) -> bool:
            key = (target, state.octave, state.carriers, state.tempo, state.gate, state.default_length,
                   tuple(state.stack), state.lfo_sync)
            if key in seen:
                period.append(tick - seen[key])
                return True
            seen[key] = tick
            return False

        events = self.simulate(part_address, max_ticks, max_ops=2_000_000, on_jump=on_jump)
        if period:
            return 'петля', period[0]
        ends = [event.tick for event in events if event.kind == 'конец']
        if not ends:
            raise ValueError(f'часть ${part_address:04X}: ни петли, ни конца за {max_ticks} тактов')
        return 'конец', ends[-1]

    def command_shape(self, number: int) -> tuple[str, int]:
        """Мелодия целиком: ('петля', НОК периодов частей) или ('конец', такт конца последней части).
        Часть, дошедшая до конца, петлю не прерывает: после конца она молчит."""
        shapes = [self.part_shape(address) for address in self.command(number).parts]
        periods = [value for kind, value in shapes if kind == 'петля']
        if periods:
            return 'петля', math.lcm(*periods)
        return 'конец', max((value for _, value in shapes), default=0)

    def listing(self, part_address: int, count: int = 60) -> list[str]:
        """Линейный листинг байт-кода части (без переходов)."""
        lines = []
        pc = part_address + 1
        sizes = {0x10: 1, 0x18: 1, 0x20: 1, 0x28: 2, 0x30: 1, 0x38: 2, 0x40: 5, 0x48: 1, 0x58: 2, 0x68: 1, 0x70: 2,
                 0x88: 3}
        for _ in range(count):
            op = self.byte(pc)
            group = op & 0xF8
            if group in (0x00, 0x08):
                size = (1 if group == 0x00 else 0) + (1 if op & 7 == 1 else 0)
            elif group >= 0x90:
                lines.append(f'${pc:04X}: {op:02X} конец')
                break
            else:
                size = sizes.get(group, 0)
            data = ' '.join(f'{self.byte(pc + 1 + k):02X}' for k in range(size))
            lines.append(f'${pc:04X}: {op:02X} {data:<15} {OPCODES.get(group, "?")}')
            pc += 1 + size
        return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', type=lambda v: int(v, 0))
    parser.add_argument('--listing', type=int, default=40)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    driver = Driver()
    cmd = driver.command(args.command)
    print(f'команда ${cmd.number:02X}: тип ${cmd.kind:02X}, голос {cmd.voice}, частей {len(cmd.parts)}')
    for index, address in enumerate(cmd.parts):
        print(f'часть {index} (${address:04X}, приоритет {driver.byte(address)}):')
        for line in driver.listing(address, args.listing):
            print('  ' + line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
