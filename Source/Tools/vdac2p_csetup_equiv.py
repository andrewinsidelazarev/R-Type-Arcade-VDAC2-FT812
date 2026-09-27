"""Равносильность CollideSetup двух сборок (прежней и новой) на случайных входах: CF, KC_X, KC_Y, KC_HB0…6, KC_BX,
KC_BXNEW, KC_XR, KC_XL, W2_PAGE и записи в порты страниц. Память — плоские 64 КБ: резидент, нативная страница, рабочее
ОЗУ (окно W1) и окно W2 со случайными байтами; окно W2 у обеих сборок одинаковое, как и отображение портами."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, 'E:/zx/R-Type VDAC2/Build/PythonDeps')
from z80 import Z80Machine  # noqa: E402

OLD = Path(sys.argv[1])
NEW = Path(sys.argv[2])
CASES = int(sys.argv[3]) if len(sys.argv) > 3 else 100000
STOP = 0xBF00


class Machine:
    def __init__(self, build: Path):
        report = json.loads((build / 'build_report.json').read_text(encoding='utf-8'))
        self.sym = report['symbols']
        self.cpu = Z80Machine()
        self.mem = self.cpu.memory
        self.mem[0:0x4000] = (build / 'pages' / 'page_08.bin').read_bytes()[:0x4000]
        self.mem[0xC000:0x10000] = (build / 'pages' / f'page_{report["native_pages"][0]:02x}.bin').read_bytes()[:0x4000]
        self.cpu.set_breakpoint(STOP)
        self.ports = []
        self.cpu.set_output_callback(lambda port, value: self.ports.append((port, value)))

    def w16(self, address, value):
        self.mem[address] = value & 0xFF
        self.mem[address + 1] = (value >> 8) & 0xFF

    def r16(self, address):
        return self.mem[address] | (self.mem[address + 1] << 8)

    def call(self, address, hl):
        self.ports.clear()
        sp = 0x3E00                                    # стек — область HELPER_TOP резидента: процедура её не читает
        self.w16(sp - 2, STOP)
        self.cpu.sp = sp - 2
        self.cpu.hl = hl
        self.cpu.pc = address
        for _ in range(100):
            self.cpu.ticks_to_stop = 100000
            self.cpu.run()
            if self.cpu.pc == STOP:
                return
        raise RuntimeError('не вернулась')


old, new = Machine(OLD), Machine(NEW)
rng = random.Random(925)
window_all = bytes(rng.getrandbits(8) for _ in range(0x4000))
for machine in (old, new):
    machine.mem[0x8000:0xC000] = window_all
NAMES = ('KC_X', 'KC_Y', 'KC_HB0', 'KC_HB2', 'KC_HB4', 'KC_HB6', 'KC_BX', 'KC_BXNEW', 'KC_XR', 'KC_XL')
mismatch = 0
ok_cases = 0
for case in range(CASES):
    work = bytes(rng.getrandbits(8) for _ in range(64))
    window = bytes(rng.getrandbits(8) for _ in range(64))
    ds = 0x4000 if rng.random() < 0.9 else rng.choice([0x4001, 0x3000, 0x0000, 0xC000])
    bp = (rng.randint(0, 0x1FF) * 0x20) if rng.random() < 0.85 else rng.randint(0, 0xFFFF)
    es = 0x1000 if rng.random() < 0.8 else rng.choice([0x0000, 0x2000, 0x1400, 0xC000, rng.randint(0, 0xFFFF)])
    bx = rng.randint(0, 0xFFFF)
    cached = rng.choice([bx, 0xFFFF, rng.randint(0, 0xFFFF)])
    hb_prev = [rng.randint(0, 0xFFFF) for _ in range(4)]
    results = []
    for machine in (old, new):
        sym = machine.sym
        machine.w16(sym['V_DS'], ds)
        machine.w16(sym['V_BP'], bp)
        machine.w16(sym['V_ES'], es)
        machine.w16(sym['KC_BX'], cached)
        for index, name in enumerate(('KC_HB0', 'KC_HB2', 'KC_HB4', 'KC_HB6')):
            machine.w16(sym[name], hb_prev[index])
        # объект: [bp+4…9] в окне W1; окно W2 — одни и те же байты у обеих сборок
        if bp < 0x3F00:
            for index in range(10):
                machine.mem[0x4000 + bp + index] = work[index]
        machine.mem[sym['W2_PAGE']] = 0x77
        machine.call(sym['CollideSetup'], bx)
        cf = machine.cpu.f & 1
        values = tuple(machine.r16(sym[name]) for name in NAMES) if not cf else ()
        results.append((cf, values, machine.mem[sym['W2_PAGE']] if not cf else None, tuple(machine.ports) if not cf else ()))
    ok_cases += results[0][0] == 0
    if results[0] != results[1]:
        mismatch += 1
        if mismatch <= 10:
            print(f'расхождение: DS {ds:04X} BP {bp:04X} ES {es:04X} BX {bx:04X} кэш {cached:04X}:\n  прежняя {results[0]}\n'
                  f'  новая   {results[1]}')
print(f'случаев {CASES}, принятых ядром {ok_cases}, расхождений {mismatch}')
