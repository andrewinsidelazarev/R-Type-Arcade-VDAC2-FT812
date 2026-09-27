"""Вторая нативная страница VDAC2+ (NATIVE_PAGE1, окно #C000): модуль n2 из своего исходника и копий помощников.

Код второй страницы — Source/ASM/vdac2p_native2.asm (свои обработчики; им в первой странице места нет). Он зовёт
подпрограммы первой нативной страницы (vdac2p_native.asm: спрайты, рельеф, сложение координат, возврат NRet и т. п.),
а в окне W3 при его исполнении — вторая страница: вызов в первую невозможен. Поэтому генератор кладёт в модуль копии
всех нужных блоков vdac2p_native.asm — замыкание ссылок кода второй страницы (блок — от метки с двоеточием или метки
данных DB/DW/DS до следующей такой метки), в прежнем порядке, и следом весь vdac2p_native2.asm. В MODULE sjasmplus
метки становятся n2.<имя>; ссылка без префикса ищется сначала в модуле, затем среди глобальных (резидент, EQU) — копии
закрыты от первой страницы. Переменные копий — свои (рабочие ячейки и кэш описаний спрайтов второй страницы
независимы от первой). Определения MACRO в копию не входят (макросы глобальны, первая страница их уже определила).
Первым идёт блок с выравниванием (кэш описаний DESC_CACHE, если нужен): модуль начинается с #C000.

Нельзя класть во вторую страницу код, который зовёт CollideSetup и сканы столкновений: CollideSetup отображает в W3
первую нативную страницу (генератор такой вызов находит и останавливает сборку), а также переходники резидента,
отображающие первую страницу (NC60Far, NC48Far, WeaponIdleFar, WormFar).

Запуск: vdac2p_native2_gen.py выходной.inc — пишет файл и печатает объём; запрещённая ссылка — код возврата 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'Source' / 'ASM' / 'vdac2p_native.asm'
NATIVE2 = ROOT / 'Source' / 'ASM' / 'vdac2p_native2.asm'
MODULE = 'n2'
LABEL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)(?::|\s+(?:DB|DW|DS|DEFB|DEFW|DEFS)\b)', re.I)
TOKEN = re.compile(r'(?<![\w.$])([A-Za-z_][A-Za-z0-9_]*)')
# Процедуры резидента, которые отображают в W3 первую нативную страницу: из второй их звать нельзя.
FORBIDDEN = ('CollideSetup', 'CollideA94', 'NC60Far', 'NC48Far', 'WeaponIdleFar', 'WormFar', 'Collide85', 'Collide93',
             'CollideAA', 'CollideBF', 'KERNEL_COLLIDE_A94')


def blocks(lines: list[str]):
    """Блоки меток: (имя, первая строка, конец) и номера строк определений макросов."""
    macro_lines: set[int] = set()
    in_macro = False
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith('MACRO '):
            in_macro = True
        if in_macro:
            macro_lines.add(index)
            if upper == 'ENDM':
                in_macro = False
    starts = [(match.group(1), index) for index, line in enumerate(lines)
              if index not in macro_lines for match in [LABEL.match(line)] if match]
    parts = [(name, start, starts[number + 1][1] if number + 1 < len(starts) else len(lines))
             for number, (name, start) in enumerate(starts)]
    return parts, macro_lines


def references(lines: list[str], start: int, end: int, macro_lines: set[int]) -> set[str]:
    found = set()
    for index in range(start, end):
        if index in macro_lines:
            continue
        code = lines[index].split(';')[0]
        code = re.sub(r'^[A-Za-z_.][A-Za-z0-9_.]*:', '', code)
        if re.match(r'\s*ASSERT\b', code, re.I):
            continue                            # проверки выравнивания — не ссылки (их правит вывод ниже)
        found.update(TOKEN.findall(code))
    return found


def main() -> int:
    out = Path(sys.argv[1])
    lines = NATIVE.read_text(encoding='utf-8').split('\n')
    own = NATIVE2.read_text(encoding='utf-8').split('\n')
    parts, macro_lines = blocks(lines)
    names = {name for name, _, _ in parts}
    refs = {name: references(lines, start, end, macro_lines) & names - {name} for name, start, end in parts}
    own_parts, own_macros = blocks(own)
    own_names = {name for name, _, _ in own_parts}
    clash = own_names & names
    if clash:
        print('метки второй страницы совпадают с метками первой:', sorted(clash))
        return 1
    wanted = references(own, 0, len(own), own_macros)
    bad = sorted(wanted & set(FORBIDDEN))
    closure: set[str] = set()
    stack = sorted(wanted & names)
    while stack:
        name = stack.pop()
        if name not in closure:
            closure.add(name)
            stack.extend(refs[name])
    for name, start, end in parts:
        if name in closure:
            bad += sorted(references(lines, start, end, macro_lines) & set(FORBIDDEN))
    if bad:
        print('код второй нативной страницы зовёт процедуры, отображающие первую:', sorted(set(bad)))
        return 1
    text = ['; Сгенерировано vdac2p_native2_gen.py — не править. Вторая нативная страница (окно #C000): копии блоков',
            f'; vdac2p_native.asm ({len(closure)} меток — замыкание ссылок) и vdac2p_native2.asm, модуль {MODULE}.',
            f'                MODULE {MODULE}']
    ordered = [part for part in parts if part[0] in closure]
    # Блоки с выравниванием (ASSERT low … == 0) — в начало модуля (#C000).
    ordered.sort(key=lambda part: 0 if any('ASSERT low' in lines[index] for index in range(part[1], part[2])) else 1)
    for name, start, end in ordered:
        for index in range(start, end):
            if index in macro_lines:
                continue
            line = lines[index]
            if 'ASSERT low WEAPON_IDLE' in line:
                line = '                ASSERT low DESC_CACHE == 0'
            text.append(line)
    text += [line for index, line in enumerate(own) if index not in own_macros]
    text += ['NATIVE2_END:', '                ASSERT NATIVE2_END <= #10000', '                ENDMODULE', '']
    out.write_text('\n'.join(text), encoding='utf-8', newline='\n')
    print(f'вторая нативная страница: копий {len(closure)} меток первой, своих {len(own_names)}; {out.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
