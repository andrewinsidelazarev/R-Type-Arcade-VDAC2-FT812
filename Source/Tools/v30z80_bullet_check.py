"""Сверка ядра пачки пуль двух сборок Z80: арифметика, границы и выход на общий перевод."""
from __future__ import annotations

import argparse
import json
import random
import struct
from pathlib import Path

from p2c_z80_check import TSConfModel


class BulletRunner:
    def __init__(self, build: Path):
        report = json.loads((build / 'build_report.json').read_text(encoding='utf-8'))
        self.symbols = report['symbols']
        self.resident = report['res_page']
        self.base = report['v30_page_base']
        self.pages = {self.resident: (build / 'pages' / f'page_{self.resident:02x}.bin').read_bytes(),
                      self.base + 0x10: bytes(0x4000), self.base + 0x30: bytes(0x4000),
                      self.base + 4: bytes(0x4000)}
        self.model = TSConfModel(self.pages, set(self.pages))
        self.model.map_all([self.resident, self.base + 0x10, self.base + 0x30, self.base + 4])
        self.model.cpu.set_breakpoint(0x3F00)
        self.model.cpu.set_breakpoint(self.symbols['HandlerBail'])

    def run(self, objects, sprite_fill, global_kill, description, es, first_bp, initial):
        s, model = self.symbols, self.model
        model.map_all([self.resident, self.base + 0x10, self.base + 0x30, self.base + 4])
        mem = model.memory
        mem[0x4000:0x8000] = bytes(0x4000)
        mem[0x8000:0xC000] = bytes([0xA5]) * 0x4000
        mem[0xC000:0x10000] = bytes(0x4000)
        for name, value in initial.items():
            mem[s[name]:s[name] + 2] = struct.pack('<H', value)
        for name, value in (('V_ES', es), ('V_BP', first_bp), ('V_DS', 0x4000)):
            mem[s[name]:s[name] + 2] = struct.pack('<H', value)
        mem[s['BB_W3']] = 255
        mem[s['W2_PAGE']] = 0x30
        mem[0x6EFC:0x6EFE] = struct.pack('<H', sprite_fill)
        mem[0x6FC4] = global_kill
        for index, (x, velocity, right, next_bp, bx) in enumerate(objects):
            at = 0x5000 + index * 0x40
            mem[at:at + 2] = struct.pack('<H', s['NATIVE_IP0'])
            mem[at + 3:at + 6] = x.to_bytes(3, 'little')
            mem[at + 6] = index + 3
            mem[at + 8:at + 10] = struct.pack('<H', 0x123 + index)
            mem[at + 0x1C:at + 0x1E] = struct.pack('<H', next_bp)
            struct.pack_into('<hHH', mem, at + 0x30, velocity, 0x832C if right else 0, bx)
            if bx <= 0x3FFA:
                shape = description[bx] if isinstance(description, dict) else description
                mem[0xC000 + bx:0xC000 + bx + 6] = shape
        cpu = model.cpu
        cpu.pc, cpu.sp = s['BulletBatch.body'], 0x3FE0
        mem[0x3FE0:0x3FE2] = b'\x00\x3F'
        spent, budget = 0, 1_000_000
        while spent < budget:
            quantum = budget - spent
            cpu.ticks_to_stop = quantum
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            spent += quantum - remaining
            if cpu.pc in (0x3F00, s['HandlerBail']):
                break
        if cpu.pc not in (0x3F00, s['HandlerBail']):
            raise AssertionError(f'Пачка не завершилась: PC={cpu.pc:04X}')
        result = (cpu.pc == s['HandlerBail'], cpu.a if cpu.pc == 0x3F00 else None, cpu.sp,
                  tuple(model.word(s[name]) for name in initial),
                  bytes(mem[0x4000:0xC000]), mem[s['BB_W3']], mem[s['W2_PAGE']])
        return result, spent


def cases(count):
    rng = random.Random(19092026)
    names = ('V_AX', 'V_BX', 'V_CX', 'V_DX', 'V_SI', 'V_DI', 'V_BP', 'V_ES', 'V_DS', 'V_FL')
    positions = (0, 0x13F00, 0x13FFF, 0x14000, 0x14001, 0x1FFFF, 0x20000,
                 0x2BFFF, 0x2C000, 0x2C001, 0xFFFF00, 0xFFFFFF)
    speeds = (-32768, -257, -256, -1, 0, 1, 255, 256, 32767)
    for case in range(count):
        objects = []
        length = 1 + case % 8
        for index in range(length):
            last = index == length - 1
            x = rng.choice(positions) if case % 2 else rng.randrange(0x14000, 0x2C000)
            next_bp = rng.choice((0xFFFF, 0x3F00, 0x1800, 0x1001)) if last else 0x1040 + index * 0x40
            objects.append((x, rng.choice(speeds), bool(rng.randrange(2)), next_bp,
                            rng.choice((0x100, 0x100, 0x200, 0x3FFA, 0x3FFB))))
        yield (objects, rng.choice((0, 8, 0x3B0, 0x3B8, 0x3C0, 0x3C8, 0x3EF8, 0x3F00, 0xFFFF)),
               int(case % 17 == 0), bytes((rng.randrange(256), rng.randrange(256), 0xCD, 0xAB, 0, rng.randrange(256))),
               0x4000 if case % 19 == 0 else 0x1000, 0x1001 if case % 23 == 0 else 0x1000,
               {name: rng.randrange(65536) for name in names})


def batch_cases():
    """Длинный быстрый путь и выход с каждой позиции: полный буфер, другое описание, уничтожение."""
    names = ('V_AX', 'V_BX', 'V_CX', 'V_DX', 'V_SI', 'V_DI', 'V_BP', 'V_ES', 'V_DS', 'V_FL')
    initial = {name: 0x1234 + index * 37 for index, name in enumerate(names)}
    for length in (1, 2, 8, 16, 32, 64):
        for fill in (0, 8, 0xF8, 0x3A0, 0x3B8, 0x3C0):
            for cut in range(length):
                for variant in ('plain', 'wide', 'destroy', 'other', 'unaligned'):
                    objects = []
                    for index in range(length):
                        point = index == cut
                        link = 0xFFFF if index == length - 1 else 0x1040 + index * 0x40
                        if point and variant in ('other', 'unaligned'):
                            link = 0x2000 if variant == 'other' else 0x1001
                        objects.append((0x13F00 if point and variant == 'destroy' else 0x20080,
                                        -257, False, link, 0x200 if point and variant == 'wide' else 0x100))
                    yield (objects, fill, 0, {0x100: bytes.fromhex('f2fcf30a0000'),
                                             0x200: bytes.fromhex('017f12340040')},
                           0x1000, 0x1000, initial)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, default=Path('Build/V30Z80'))
    parser.add_argument('--cases', type=int, default=10000)
    args = parser.parse_args()
    before, after = BulletRunner(args.before), BulletRunner(args.after)
    totals, exits = [0, 0], {}
    from itertools import chain
    for count, case in enumerate(chain(cases(args.cases), batch_cases()), 1):
        old, old_ticks = before.run(*case)
        new, new_ticks = after.run(*case)
        if old != new:
            raise AssertionError(f'Случай {count}: {case}; различаются части '
                                 f'{[i for i, (a, b) in enumerate(zip(old, new)) if a != b]}')
        totals[0] += old_ticks
        totals[1] += new_ticks
        key = 'destroy' if old[0] else str(old[1])
        exits[key] = exits.get(key, 0) + 1
    print(json.dumps({'cases': count, 'before_ticks': totals[0], 'after_ticks': totals[1], 'exits': exits,
                      'saved_percent': round(100 * (1 - totals[1] / totals[0]), 3)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
