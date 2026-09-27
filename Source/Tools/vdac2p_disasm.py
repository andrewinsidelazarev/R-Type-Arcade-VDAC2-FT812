"""Листинг процедуры ROM для нативной переписи VDAC2+: тело функции (functions.build транслятора) с текстом
инструкций V30 и пометками карты ROM (Docs/RTYPE_WORLD_ROM_MAP.md). Аргументы — входы (линейный hex или
IP с префиксом «ip»: ip1C1B = $0201B)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))

from vdac2p_costmap import load_function_map  # noqa: E402


def rom_notes() -> dict[int, str]:
    notes = {}
    text = (ROOT / 'Docs' / 'RTYPE_WORLD_ROM_MAP.md').read_text(encoding='utf-8')
    for line in text.splitlines():
        match = re.match(r'^\| `\$([0-9A-F]{4,5})` \| (.*)$', line)
        if match:
            notes.setdefault(int(match[1], 16), match[2][:300])
    return notes


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    program, fmap, live = load_function_map(with_flags=True)
    notes = rom_notes()
    show_sites = '--sites' in sys.argv
    if len(sys.argv) >= 4 and sys.argv[1] == 'range':
        # Диапазон линейных адресов: range начало конец (hex) — все известные инструкции подряд.
        first, last = int(sys.argv[2], 16), int(sys.argv[3], 16)
        for address in sorted(a for a in program.instructions if first <= a <= last):
            instruction = program.instructions[address]
            print(f'  {address:05X} ({address - 0x400:04X})  {instruction.text}')
        return 0
    for argument in [item for item in sys.argv[1:] if not item.startswith('--')]:
        entry = int(argument[2:], 16) + 0x400 if argument.lower().startswith('ip') else int(argument, 16)
        body = fmap.bodies.get(entry)
        if body is None:
            print(f'${entry:05X}: не вход функции')
            continue
        callers = sorted(fmap.callers.get(entry, ()))
        print(f'=== ${entry:05X} (IP ${entry - 0x400:04X}): инструкций {len(body)}, мест вызова {len(callers)}')
        if entry - 0x400 in notes:
            print(f'  карта ROM: {notes[entry - 0x400]}')
        previous = None
        for address in body:
            instruction = program.instructions[address]
            if previous is not None and address != previous:
                print('  ...')
            owners = fmap.owners.get(address, set())
            shared = '' if len(owners) <= 1 else f'  [общая с {len(owners) - 1}]'
            tail = ''
            if instruction.mnemonic in ('ret', 'call'):
                mask = live.get(address, 0)
                names = ''.join(name for bit, name in ((0, 'C'), (1, 'P'), (2, 'A'), (3, 'Z'), (4, 'S'), (5, 'O'))
                                if mask & (1 << bit))
                tail = f'   ; живые флаги после: {names or "нет"}'
            print(f'  {address:05X} ({address - 0x400:04X})  {instruction.text}{shared}{tail}')
            previous = address + instruction.size
        if show_sites:
            # Места вызова и по 6 инструкций после каждого — чтобы видеть, какие регистры вызывающий читает дальше.
            for site in callers[:12]:
                owners = sorted(fmap.owners.get(site, ()))
                print(f'  -- вызов из {site:05X} ({site - 0x400:04X}), функции {[f"{o - 0x400:04X}" for o in owners]}')
                address = program.instructions[site].next
                for _ in range(6):
                    instruction = program.instructions.get(address)
                    if instruction is None:
                        break
                    print(f'       {address:05X} ({address - 0x400:04X})  {instruction.text}')
                    if instruction.mnemonic in ('ret', 'jmp', 'iret', 'retf'):
                        break
                    address = instruction.next
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
