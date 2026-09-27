"""Трасса исполнения World ROM в эталонной машине M72 (unicorn): какие инструкции V30 исполняются.

Сценарии (добавляются к уже собранной трассе Build/V30Z80/trace.json):
  app     — как полный runtime: скрытый титул, штатный старт coin/start, игра со случайным вводом;
  machine — как сверка v30z80_check: машина после загрузки, простой, coin/start, случайный ввод.
Для каждого адреса — байты и разбор инструкции, число исполнений; для RET, IRET и переходов
по регистру/памяти — фактические цели. С --memory — ещё страницы V30 (адрес >> 14), к
которым инструкция обращалась за данными: по ним генератор выбирает быстрый путь.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Build' / 'PythonDeps', ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

from capstone import CS_ARCH_X86, CS_MODE_16, Cs  # noqa: E402
from unicorn.unicorn_const import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE  # noqa: E402

OUT = ROOT / 'Build' / 'V30Z80'
BRANCH_GROUPS = {'jmp', 'call'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scenario', choices=('app', 'machine'), default='machine')
    parser.add_argument('--title-frames', type=int, default=900)
    parser.add_argument('--frames', type=int, default=6000)
    parser.add_argument('--seed', type=int, default=3)
    parser.add_argument('--coin-frame', type=int, default=120)
    parser.add_argument('--memory', action='store_true', help='записывать страницы обращений к данным')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    path = OUT / 'trace.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {
        'instructions': {}, 'indirect_targets': {}}
    memory_pages: dict[int, Counter] = defaultdict(Counter)
    for address, pages in previous.get('memory_pages', {}).items():
        memory_pages[int(address, 16)].update({int(page, 16): count for page, count in pages.items()})
    executed: Counter[int] = Counter()
    decoded: dict[int, tuple[str, str, str]] = {}
    targets: dict[int, set[int]] = defaultdict(set)
    for address, (code, mnemonic, operands, count) in previous['instructions'].items():
        executed[int(address, 16)] = count
        decoded[int(address, 16)] = (code, mnemonic, operands)
    for address, found in previous['indirect_targets'].items():
        targets[int(address, 16)].update(int(target, 16) for target in found)

    md = Cs(CS_ARCH_X86, CS_MODE_16)
    last = [None]

    def memory_hook(uc, _access, address, _size, _value, _user):
        if last[0] is not None:
            memory_pages[last[0]][address >> 14] += 1

    def hook(uc, address, size, _user):
        executed[address] += 1
        previous_address = last[0]
        if previous_address is not None:
            _code, mnemonic, operands = decoded[previous_address]
            if (mnemonic in BRANCH_GROUPS and not operands.startswith('0x')) or mnemonic in ('ret', 'retf', 'iret'):
                targets[previous_address].add(address)
        if address not in decoded:
            code = bytes(uc.mem_read(address, 8))
            insn = next(md.disasm(code, address), None)
            decoded[address] = ((code[:2].hex(), '(не разобрано)', '') if insn is None
                                else (insn.bytes.hex(), insn.mnemonic, insn.op_str))
        last[0] = address

    if args.scenario == 'machine':
        import v30z80  # noqa: F401
        from v30z80 import snapshot
        from v30z80.scenario import Scenario
        machine = snapshot.new_reference_machine()
        machine.cpu.hook_add(UC_HOOK_CODE, hook)
        if args.memory:
            machine.cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, memory_hook)
        scenario = Scenario(args.seed, args.coin_frame)
        for frame in range(args.frames):
            last[0] = None
            mask, start, coin = scenario.inputs(frame)
            scenario.apply(machine, mask, start, coin)
            machine.step_frame()
    else:
        import pygame
        pygame.init()
        pygame.display.set_mode((640, 480))
        from rtype_port.full_runtime import FullRuntimeGame
        full = FullRuntimeGame(lambda command: None, enable_renderer=False)
        full.machine.cpu.hook_add(UC_HOOK_CODE, hook)
        if args.memory:
            full.machine.cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, memory_hook)
        for _ in range(args.title_frames):
            if full.advance_title():
                break
        full.request_start()
        while not full.advance_start():
            pass
        rng = random.Random(args.seed)
        mask = 0
        for frame in range(args.frames):
            if rng.random() < 0.05:
                mask = rng.choice((0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x11, 0x12, 0x14, 0x18, 0x30))
            full.update(mask, start1=(frame % 300) in (30, 31), coin1=(frame % 300) in (0, 1))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        'instructions': {f'{address:05X}': [decoded[address][0], decoded[address][1], decoded[address][2], count]
                         for address, count in sorted(executed.items())},
        'indirect_targets': {f'{address:05X}': sorted(f'{target:05X}' for target in found)
                             for address, found in sorted(targets.items())},
        'memory_pages': {f'{address:05X}': {f'{page:02X}': count for page, count in sorted(pages.items())}
                         for address, pages in sorted(memory_pages.items())},
    }
    path.write_text(json.dumps(report, ensure_ascii=False) + '\n', encoding='utf-8')
    new = len(executed) - len(previous['instructions'])
    print(f'адресов в трассе {len(executed)} (новых {new}), всего исполнений {sum(executed.values())}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
