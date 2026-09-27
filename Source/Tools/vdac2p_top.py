"""Топ меток профиля VDAC2+ (rtype_check --ticks): доля меток с их категорией, без разбора процедур ROM.

Запуск: vdac2p_top.py профиль.json [число строк] [префикс-фильтр]. Категории — как у vdac2p_costmap.py: A_ — перевод,
N/W… из vdac2p_native.asm — натив, KERNEL_/ядра — ядра, прочее — по файлу, где метка определена.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding='utf-8')
ASM = ROOT / 'Source' / 'ASM'
LABEL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):', re.M)


def label_files() -> dict[str, str]:
    """Глобальная метка → имя файла исходника (без расширения)."""
    owners: dict[str, str] = {}
    for path in ASM.glob('*.asm'):
        for name in LABEL.findall(path.read_text(encoding='utf-8', errors='replace')):
            owners.setdefault(name, path.stem)
    return owners


def main() -> int:
    path = Path(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    prefix = sys.argv[3] if len(sys.argv) > 3 else ''
    profile = json.loads(path.read_text(encoding='utf-8'))['profile']
    total = sum(profile.values())
    owners = label_files()
    by_file: dict[str, int] = {}
    for name, ticks in profile.items():
        owner = 'перевод' if re.match(r'[AFGDK]_', name) else owners.get(name, '?')
        by_file[owner] = by_file.get(owner, 0) + ticks
    print('по файлам: ' + ', '.join(f'{name} {ticks * 100 / total:.1f} %'
                                    for name, ticks in sorted(by_file.items(), key=lambda item: -item[1])[:14]))
    shown = 0
    for name, ticks in sorted(profile.items(), key=lambda item: -item[1]):
        if not name.startswith(prefix):
            continue
        owner = 'перевод' if re.match(r'[AFGDK]_', name) else owners.get(name, '?')
        print(f'{ticks * 100 / total:6.2f} %  {name:28} {owner}')
        shown += 1
        if shown >= count:
            break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
