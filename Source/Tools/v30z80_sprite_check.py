"""Побайтовая сверка SpriteEntry двух сборок Z80 на границах экрана и случайных записях.

Ячейки заранее загружены: проверяется горячий путь вывода, включая отражения,
формы 1…8 ячеек, оба прохода, смену палитры и переполнение буфера. Холодную загрузку
с SD проверяет полный rtype_check.py. Исходные страницы сборок не изменяются.
"""
from __future__ import annotations

import argparse
import json
import random
import struct
from pathlib import Path

from p2c_z80_check import TSConfModel


class SpriteRunner:
    def __init__(self, build: Path):
        self.symbols = json.loads((build / 'build_report.json').read_text(encoding='utf-8'))['symbols']
        s = self.symbols
        pages = {page: (build / 'pages' / f'page_{page:02x}.bin').read_bytes()
                 for page in (s['HOST_PAGE'], s['VIDEO_STATE_PAGE'])}
        pages[0] = bytes(0x4000)
        self.model = TSConfModel(pages)
        self.model.map_all([0, s['VIDEO_STATE_PAGE'], s['VIDEO_SLOTMAP_PAGE0'] + 16, s['HOST_PAGE']])
        self.model.cpu.set_breakpoint(0x0100)
        self.pass_mask = None
        # С 19.09.2026 запись 1×1 отличает просмотр SpritesBuild, и цикл вывода зовёт Sprite1 напрямую
        # (на стеке — адрес байта 5). В прежних сборках эту развилку делал сам SpriteEntry: он начинался
        # с `ld a,l` (#7D), теперь — с `ld e,(hl)` (#5E). По этому байту выбираем точку входа сборки.
        self.entry_dispatches = pages[s['HOST_PAGE']][s['SpriteEntry'] - 0xC000] == 0x7D

    def run(self, x: int, y: int, attr: int, code: int, palette: int,
            passes: int, fill: int, previous: tuple[int, int, int, int], buffer: bytes | None = None):
        s, model = self.symbols, self.model
        if self.pass_mask != passes:
            # Слово карты: слот #300…#3FF и наличие проходов A/B в битах 14/15.
            half = b''.join(struct.pack('<H', 0x300 | (cell & 255) | (passes << 8))
                            for cell in range(4096))
            for page in range(s['VIDEO_SLOTMAP_PAGE0'] + 16, s['VIDEO_SLOTMAP_PAGE0'] + 24):
                model.write_block(page * 0x4000, half + half)
            self.pass_mask = passes
        mem = model.memory

        def byte(name, value):
            mem[s[name]] = value

        def word(name, value):
            mem[s[name]:s[name] + 2] = struct.pack('<H', value)

        byte('SE_SLOT_PAL', 255)
        byte('VIDEO_FRAME', 37)
        for name, value in zip(('SPRITE_PAL', 'SPRITE_FLIP', 'SPRITE_RX', 'SPRITE_RY'), previous):
            byte(name, value)
        word('SPRITE_FILL', fill)
        word('VIDEO_OVERFLOW', 0)
        start = 0x4000 + s['SPRITE_WORDS']
        end = 0x4000 + s['SPRITE_WORDS_END']
        mem[start:end] = bytes([0xA5]) * (end - start)
        used = 0x4000 + s['SLOT_USED']
        mem[used:used + 256] = bytes(256)
        entry = 0x4000 + s['SPRITE_TEMP']
        mem[entry:entry + 8] = struct.pack('<HHHH', y, code, (attr << 8) | palette, x)
        cpu = model.cpu
        cpu.sp = 0x3FF0
        if attr & 0xF0 or self.entry_dispatches:
            cpu.hl, cpu.pc = entry, s['SpriteEntry']
        else:
            cpu.hl, cpu.pc = entry + 5, s['Sprite1']    # как зовёт цикл вывода SpritesBuild
        if buffer is not None:
            model.write_block(s['SPRITE_BUFFER_PAGE'] * 0x4000, buffer)
            cpu.pc = s['SpritesBuild']
        mem[0x3FF0:0x3FF2] = b'\x00\x01'
        budget = 1_000_000
        spent = 0
        while spent < budget:
            quantum = budget - spent
            cpu.ticks_to_stop = quantum
            cpu.run()
            # Ядро возвращает управление и на границе своего кадра, не только на точке останова.
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            spent += quantum - remaining
            if cpu.pc == 0x0100:
                break
        if cpu.pc != 0x0100 or cpu.sp != 0x3FF2:
            raise AssertionError(f'SpriteEntry не вернулся: PC={cpu.pc:04X}, SP={cpu.sp:04X}')
        result = (bytes(mem[start:end]), bytes(mem[used:used + 256]), model.word(s['SPRITE_FILL']),
                  model.word(s['VIDEO_OVERFLOW']),
                  tuple(mem[s[name]] for name in ('SPRITE_PAL', 'SPRITE_FLIP', 'SPRITE_RX', 'SPRITE_RY')),
                  model.word(s['SPRITE_BYTES']) if buffer is not None else None)
        return result, spent


def cases(random_count):
    # Обе стороны порогов отсечения, границы областей FT812 и диапазонов младшего байта.
    xs = (0, 176, 177, 240, 241, 272, 273, 288, 289, 303, 304, 319, 320,
          495, 496, 511, 512, 687, 688, 703, 704, 767, 768, 1023)
    ys = (0, 16, 17, 80, 81, 112, 113, 128, 129, 143, 144, 255, 256,
          367, 368, 383, 384, 399, 400, 511)
    for passes in (0, 0x40, 0x80, 0xC0):
        for flip in range(4):
            for x in xs:
                for y in ys:
                    yield x, y, flip << 2, 0xFFFF, 15, passes, 0x6D00, (255, 0, 127, 127)
        for shape in range(64):
            for x, y in ((177, 17), (241, 81), (289, 129), (304, 384), (320, 256), (703, 399), (704, 400)):
                for fill in (0x6D00, 0x7FBC, 0x7FBD):
                    yield x, y, shape << 2, 0xFFF8, 0, passes, fill, (0, 5, 255, 1)
    rng = random.Random(19092026)
    for _ in range(random_count):
        yield (rng.randrange(1024), rng.randrange(512), rng.randrange(256), rng.randrange(65536),
               rng.randrange(16), rng.choice((0, 0x40, 0x80, 0xC0)), rng.choice((0x6D00, 0x7F00, 0x7FBC, 0x7FBD)),
               (rng.randrange(16), rng.choice((0, 1, 4, 5)), rng.choice((255, 0, 1)), rng.choice((255, 0, 1))))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, default=Path('Build/V30Z80'))
    parser.add_argument('--random', type=int, default=10000)
    args = parser.parse_args()
    before, after = SpriteRunner(args.before), SpriteRunner(args.after)
    totals = [0, 0]
    for count, case in enumerate(cases(args.random), 1):
        old, old_ticks = before.run(*case)
        new, new_ticks = after.run(*case)
        if old != new:
            raise AssertionError(f'Случай {count}: {case}; различаются части '
                                 f'{[i for i, (a, b) in enumerate(zip(old, new)) if a != b]}')
        totals[0] += old_ticks
        totals[1] += new_ticks
    # Полный сборщик: DMA, отсечение, хвост пустых записей и обратный порядок стека.
    rng = random.Random(19092027)
    for batch in range(1000):
        buffer = bytearray(1024)
        used = (0, 1, 2, 127, 128)[batch] if batch < 5 else rng.randrange(129)
        for index in range(used):
            if batch < 5:
                values = (256, index, 0, 320)
            else:
                values = (rng.randrange(512), rng.randrange(65536), rng.randrange(65536), rng.randrange(1024))
            struct.pack_into('<HHHH', buffer, 8 * index, *values)
        case = (0, 0, 0, 0, 0, rng.choice((0x40, 0x80, 0xC0)), 0x6D00, (255, 0, 127, 127), bytes(buffer))
        old, old_ticks = before.run(*case)
        new, new_ticks = after.run(*case)
        if old != new:
            raise AssertionError(f'Пачка {batch}: различаются части '
                                 f'{[i for i, (a, b) in enumerate(zip(old, new)) if a != b]}')
        totals[0] += old_ticks
        totals[1] += new_ticks
    print(json.dumps({'entries': count, 'batches': 1000, 'before_ticks': totals[0], 'after_ticks': totals[1],
                      'saved_percent': round(100 * (1 - totals[1] / totals[0]), 3)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
