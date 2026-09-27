"""Равносильность BoxX (нативная страница) и BoxTest (резидент) на случайных и граничных входах: CF и V_AX, а также
BoxEdges (KC_XR, KC_XL) и сохранность BC, DE, IX у BoxX. Образы страниц — из сборки (Build/<каталог>/pages)."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, 'E:/zx/R-Type VDAC2/Build/PythonDeps')
from z80 import Z80Machine  # noqa: E402

BUILD = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / 'Build' / 'V30Z80')
CASES = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
report = json.loads((BUILD / 'build_report.json').read_text(encoding='utf-8'))
sym = report['symbols']
cpu = Z80Machine()
mem = cpu.memory
resident = (BUILD / 'pages' / 'page_08.bin').read_bytes()
native = (BUILD / 'pages' / f'page_{report["native_pages"][0]:02x}.bin').read_bytes()
mem[0:0x4000] = resident[:0x4000]
mem[0xC000:0x10000] = native[:0x4000]
STOP = 0xBF00
cpu.set_breakpoint(STOP)


def w16(address, value):
    mem[address] = value & 0xFF
    mem[address + 1] = (value >> 8) & 0xFF


def r16(address):
    return mem[address] | (mem[address + 1] << 8)


def call(address, **regs):
    sp = 0x3E00                                        # стек — область HELPER_TOP резидента
    w16(sp - 2, STOP)
    cpu.sp = sp - 2
    for name, value in regs.items():
        setattr(cpu, name, value)
    cpu.pc = address
    for _ in range(100):
        cpu.ticks_to_stop = 100000
        cpu.run()
        if cpu.pc == STOP:
            return
    raise RuntimeError(f'не вернулась: PC #{cpu.pc:04X}')


rng = random.Random(25092026)
EDGE = [0, 1, 2, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFE, 0xFFFF]


def value(base=None):
    choice = rng.random()
    if base is not None and choice < 0.6:
        return (base + rng.randint(-40, 40)) & 0xFFFF
    if choice < 0.75:
        return rng.choice(EDGE)
    return rng.randint(0, 0xFFFF)


def extent():
    choice = rng.random()
    if choice < 0.7:
        return rng.randint(-40, 40) & 0xFFFF
    if choice < 0.85:
        return rng.choice(EDGE)
    return rng.randint(0, 0xFFFF)


records = [0x56, 0x76, 0x136, 0xF6, 0x176, 0x456, 0x4F6, 0x516, 0xA8]
mismatch = 0
hits = 0
paths = {}
for case in range(CASES):
    x, y = value(), value()
    hb = [extent() for _ in range(4)]
    record = rng.choice(records)
    base = 0x4000 + record
    fields = [value(x), value(x), value(y), value(y)]
    for index, field in enumerate(fields):
        w16(base + 2 + index * 2, field)
    w16(sym['KC_X'], x)
    w16(sym['KC_Y'], y)
    for index, name in enumerate(('KC_HB0', 'KC_HB2', 'KC_HB4', 'KC_HB6')):
        w16(sym[name], hb[index])
    call(sym['BoxEdges'])
    assert r16(sym['KC_XR']) == (x + hb[0]) & 0xFFFF and r16(sym['KC_XL']) == (x + hb[1]) & 0xFFFF, 'края'
    w16(sym['V_AX'], 0x5A5A)
    call(sym['BoxTest'], ix=base)
    cf_ref, ax_ref = cpu.f & 1, r16(sym['V_AX'])
    w16(sym['V_AX'], 0xA5A5)
    call(sym['BoxX'], hl=base + 2, bc=x, de=r16(sym['KC_XR']), ix=0x1234)
    cf, ax = cpu.f & 1, r16(sym['V_AX'])
    kept = cpu.bc == x and cpu.de == r16(sym['KC_XR']) and cpu.ix == 0x1234
    hits += cf_ref
    if (cf, ax) != (cf_ref, ax_ref) or not kept:
        mismatch += 1
        if mismatch <= 10:
            print(f'расхождение: X {x:04X} Y {y:04X} hb {[f"{v:04X}" for v in hb]} запись #{record:X} '
                  f'{[f"{v:04X}" for v in fields]}: BoxTest CF {cf_ref} AX {ax_ref:04X}, BoxX CF {cf} AX {ax:04X}, '
                  f'BC/DE/IX сохранены: {kept}')
print(f'случаев {CASES}, пересечений {hits}, расхождений {mismatch}')
