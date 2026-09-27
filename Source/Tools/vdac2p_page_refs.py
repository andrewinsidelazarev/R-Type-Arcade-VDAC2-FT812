"""Ссылки кода окна W3 на метки чужих страниц окна W3 (2026-09-25): метка из файла страницы X, использованная в
файле страницы Y ≠ X, где обе — страницы окна #C000 (нативная #4A, вторая хоста #4B, хост #0C, звук #5E), — ошибка:
в миг исполнения в окне W3 другая страница, и чтение, запись или переход попадут в чужие байты. Так 25.09 перенос
$03A6 во вторую страницу хоста оставил его переменные N_SLOT, N_INDEX, N_NODE в нативной — запись портила код $0467.
Метки резидента (окно W0) и константы EQU не проверяются. Запуск: vdac2p_page_refs.py [каталог сборки]."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASM = ROOT / 'Source' / 'ASM'
sys.stdout.reconfigure(encoding='utf-8')
# Файлы кода окна W3 и их страницы (как у сборки: INCLUDE в program.asm и vdac2p_host2.asm).
PAGE_FILES = {
    0x4A: ('vdac2p_native.asm',),
    0x4B: ('vdac2p_host2.asm', 'vdac2p_guard.asm', 'vdac2p_objects.asm', 'vdac2p_sprclear.asm',
           'vdac2p_palettes.asm', 'vdac2p_native_h2.asm'),
    0x0C: ('v30z80_host.asm',),
}
LABEL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)(?::|\s+(?:DB|DW|DS|DEFB|DEFW|DEFS|EQU|=)\b)', re.M | re.I)
TOKEN = re.compile(r'(?<![\w.$#])([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)?')


def main() -> int:
    build = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Build' / 'V30Z80'
    symbols = json.loads((build / 'build_report.json').read_text(encoding='utf-8'))['symbols']
    owner: dict[str, int] = {}
    equ: set[str] = set()
    texts: dict[str, str] = {}
    for page, files in PAGE_FILES.items():
        for name in files:
            text = (ASM / name).read_text(encoding='utf-8')
            texts[name] = text
            for match in re.finditer(r'^([A-Za-z_][A-Za-z0-9_]*)\s+EQU\b', text, re.M | re.I):
                equ.add(match.group(1))
            for match in LABEL.finditer(text):
                label = match.group(1)
                if label in equ:
                    continue
                address = symbols.get(label)
                if isinstance(address, int) and address >= 0xC000:
                    owner.setdefault(label, page)
    problems = 0
    for page, files in PAGE_FILES.items():
        for name in files:
            for number, line in enumerate(texts[name].split('\n'), 1):
                code = line.split(';')[0]
                code = re.sub(r'^[A-Za-z_.][A-Za-z0-9_.]*:', '', code)
                if re.match(r'\s*(MACRO|ENDM|INCLUDE|ASSERT)\b', code, re.I):
                    continue
                for token in TOKEN.findall(code):
                    other = owner.get(token)
                    if other is not None and other != page:
                        # $$метка — номер страницы (для FARJP и т. п.) — законная ссылка на чужую страницу
                        if re.search(r'\$\$' + re.escape(token) + r'\b', code):
                            continue
                        # HostCall второй страницы хоста: IX — процедура страницы хоста, переходник меняет страницу
                        if page == 0x4B and other == 0x0C and re.search(r'\bld\s+ix\s*,\s*' + re.escape(token), code,
                                                                       re.I):
                            continue
                        print(f'{name}:{number}: метка {token} страницы #{other:02X} в коде страницы #{page:02X}: '
                              f'{line.strip()[:90]}')
                        problems += 1
    # Вторая нативная страница (#4D): модуль n2 из сгенерированного файла сборки. Метки модуля — свои (n2.*); прочие
    # метки страниц окна W3 из его кода — ошибка (генератор копирует замыкание, но проверим и итог).
    module = build / 'vdac2p_native2.inc'
    if module.exists():
        text = module.read_text(encoding='utf-8')
        own = {match.group(1) for match in LABEL.finditer(text)}
        for number, line in enumerate(text.split('\n'), 1):
            code = line.split(';')[0]
            code = re.sub(r'^[A-Za-z_.][A-Za-z0-9_.]*:', '', code)
            if re.match(r'\s*(MACRO|ENDM|INCLUDE|ASSERT|MODULE|ENDMODULE)\b', code, re.I):
                continue
            for token in TOKEN.findall(code):
                if token in own:
                    continue
                other = owner.get(token)
                if other is not None and not re.search(r'\$\$' + re.escape(token) + r'\b', code):
                    print(f'{module.name}:{number}: метка {token} страницы #{other:02X} в коде второй нативной страницы: '
                          f'{line.strip()[:90]}')
                    problems += 1
    print(f'ссылок на чужие страницы окна W3: {problems}')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
