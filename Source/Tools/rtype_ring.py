"""Кольцо дальнего слоя: родные тайлы набора 1 — хвост пака RTYPELVL.PAC, константы кольца — Build/V30Z80/rtype_ring.inc.

Зачем (замер 2026-09-16, идея пользователя — фон картинкой низкого разрешения с апскейлом, «заодно эффект ГРИП»):
цена строки растра FT812 растёт с пикселями выводов, а HQ-ячейки тайлов выводятся двумя проходами (перо A с альфой,
перо B). Дальний слой закрывает всю ширину экрана, то есть 2064 px на строку только фоном. Во втором уровне худшие
строки набирали 6000…6360 px (у сцены босса — ещё 4298 px спрайтов), а на пробах реальной платы рвалась уже строка в
5160 px. Кольцо — слой M72 целиком (64×64 тайла, 512×512 текселей PALETTED4444, индекс палитра·16 + перо) в RAM_G,
выводится одним битмапом с повтором по обеим осям, фильтр только NEAREST (у PALETTED4444 BILINEAR рисуется вчетверо
медленнее — 2 пикселя за такт против 8 по FT81X Series Programmer Guide; разрывы второго уровня на реальной плате,
решение пользователя): 1024 px на строку и одна команда вывода на полосу растра вместо сотен; фон — крупными родными
пикселями, отступление по решению пользователя. Высота кольца
в RAM_G — 256 текселей (строка кольца хранит видимую из двух строк слоя, v30z80_ring.asm): кольцо 512×512 оставляло
пулу 33 картинки групп, а переднему слою их нужно до 52 (замер всей игры, 2026-09-16).

Родные тайлы — набор 1 M72 (tiles1, ПЗУ rt_b-b0…b3; MAME m72.cpp: слой фона берёт gfx3): 4096 тайлов 8×8,
32 байта на тайл — перья строками, в байте перо чётного столбца в старшем полубайте. Заголовок пака держит четыре
раздела (+44 — секторов в файле), поэтому тайлы не раздел, а хвост после раздела 3 (эффекты GS): его сектор и длина —
в rtype_ring.inc; хост читает его один раз при открытии пака: тайлы — в страницы RING_TILE_PAGE0… подряд.
VDAC2+: последний сектор хвоста — карта одноцветных тайлов (все 64 пикселя одним пером; 512 байт: байт — код & 511,
бит — код >> 9). Она читается отдельно в начало рабочей страницы RING_WORK_PAGE (RingTilesLoad) — рабочая не
следует за тайлами: между ними страница WC_PATHS_PAGE (#F7), где Wild Commander хранит пути панелей между сбросами
(просьба пользователя 28.09.2026: «при сбросе по F12 теряется путь в WC»), кольцо её не трогает. RingInit переносит
карту на место до таблиц палитры, а RingBuild
заливает такой тайл одним значением (замер 2026-09-23: 56 % тайлов записи кольца этапов 1–2 одноцветные, в кадре конца
этапа 1 — все 1472).

Кольцо и таблица его палитры лежат в верхней части пула картинок RAM_G (зона изображений титула: хост пишет туда,
когда титул уже не показан): картинок хосту остаётся RING_IMAGES.
Запускать после rtype_gs.py (тот пересобирает пак до раздела 3) и до rtype_loader.py (размер пака).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import m72_arcade                                               # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
PACK = BUILD / 'RTYPELVL.PAC'
VIDEO_INC = BUILD / 'video.inc'
SECTOR = 512
PAGE = 0x4000
TILES = 4096
TILE_BYTES = 32
RING_WIDTH = 512                        # 64 тайла × 8 текселей: весь слой M72 с переносом по скроллу
RING_HEIGHT = 256                       # окно кадра по вертикали: строка кольца — видимая из строк слоя r, r + 256
RING_LUT_BYTES = 512                    # 256 записей ARGB4444: палитра·16 + перо
RING_TILE_PAGE0 = 0xEF                  # страницы ОЗУ под тайлы (#EF…#F6): свободны после старта SPG (SPG — до #EE)
RING_WORK_PAGE = 0xF8                   # рабочая страница кольца — за страницей путей WC
WC_PATHS_PAGE = 0xF7                    # Wild Commander (MD20.ASM RPPG): пути панелей с #1000 и #2000 — не трогать
RING_HANDLE = 14                        # handle FT812 кольца (0…5 — тайлы, 6… — спрайты, 15 — сопроцессор)


def equs(path: Path) -> dict[str, int]:
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^(\w+)\s+EQU\s+(#[0-9A-Fa-f]+|\d+)', line)
        if match:
            text = match[2]
            values[match[1]] = int(text[1:], 16) if text.startswith('#') else int(text)
    return values


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    video = equs(VIDEO_INC)
    pool_end = video['IMAGE_BASE'] + video['IMAGES'] * video['IMAGE_BYTES']
    ring_images = (video['IMAGES'] * video['IMAGE_BYTES'] - RING_WIDTH * RING_HEIGHT - RING_LUT_BYTES) // video['IMAGE_BYTES']
    ring_base = video['IMAGE_BASE'] + ring_images * video['IMAGE_BYTES']
    ring_lut = ring_base + RING_WIDTH * RING_HEIGHT
    if ring_images < video['GUARD_IMAGES'] or ring_lut + RING_LUT_BYTES > pool_end:
        raise SystemExit(f'кольцо #{ring_base:06X}…#{ring_lut + RING_LUT_BYTES:06X} не в зоне титула пула картинок')

    regions = m72_arcade.assemble_regions(m72_arcade.ROM_DIR)
    tiles = bytearray()
    uniform = bytearray(512)                # карта одноцветных тайлов: байт — код & 511, бит — код >> 9
    for code in range(TILES):
        pens = m72_arcade.decode_tile(regions['tiles1'], code)
        for index in range(0, 64, 2):
            tiles.append((pens[index] << 4) | pens[index + 1])
        if all(pen == pens[0] for pen in pens):
            uniform[code & 511] |= 1 << (code >> 9)
    pages = (len(tiles) + PAGE - 1) // PAGE
    if len(tiles) != pages * PAGE:
        raise SystemExit('тайлы кольца не кратны странице: карта одноцветных не ляжет в начало рабочей страницы')
    work_page = RING_WORK_PAGE              # таблицы «байт тайла → тексели с палитрой» и строки текселей записи
    tile_pages = range(RING_TILE_PAGE0, RING_TILE_PAGE0 + pages)
    if tile_pages.stop > 0x100 or work_page in tile_pages:
        raise SystemExit('страницы кольца выходят за #FF или рабочая совпала со страницей тайлов')
    if WC_PATHS_PAGE in tile_pages or work_page == WC_PATHS_PAGE:
        raise SystemExit(f'кольцо задевает страницу #{WC_PATHS_PAGE:02X} — пути панелей Wild Commander')

    pack = bytearray(PACK.read_bytes())
    if pack[0:8] != b'RTYPEDAT':
        raise SystemExit(f'{PACK}: не пак RTYPEDAT')
    count = struct.unpack_from('<H', pack, 10)[0]
    sections = [struct.unpack_from('<II', pack, 12 + number * 8) for number in range(count)]
    if len(sections) != 4:
        raise SystemExit('в паке не четыре раздела: сначала rtype_gs.py')
    effects_end = sections[3][0] + sections[3][1]
    body = bytearray(pack[:effects_end * SECTOR])
    first = len(body) // SECTOR
    tail = bytes(tiles) + bytes(uniform)
    body += tail + bytes((-len(tail)) % SECTOR)
    sectors = (len(tail) + SECTOR - 1) // SECTOR
    total = len(body) // SECTOR
    struct.pack_into('<I', body, 44, total)
    if total > 0xFFFF:
        raise SystemExit('пак длиннее 65535 секторов: номер сектора файла у загрузчика — слово')
    PACK.write_bytes(bytes(body))

    report_path = BUILD / 'rtype_data.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    report.update(size=len(body), sectors=total, sha256=hashlib.sha256(body).hexdigest(),
                  ring_tiles={'sector': first, 'sectors': sectors, 'bytes': len(tail),
                              'uniform': sum(bin(byte).count('1') for byte in uniform)})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    lines = [
        '; Сгенерировано rtype_ring.py: кольцо дальнего слоя (родные тайлы набора 1, RAM_G кольца и его палитры).',
        f'RING_TILES_SECTOR EQU {first}          ; хвост пака после раздела 3',
        f'RING_TILES_SECTORS EQU {sectors}               ; последний — карта одноцветных тайлов (в начало рабочей страницы)',
        f'RING_TILE_PAGE0 EQU #{RING_TILE_PAGE0:02X}',
        f'RING_TILE_PAGES EQU {pages}',
        f'RING_WORK_PAGE EQU #{work_page:02X}',
        f'RING_BASE EQU #{ring_base:06X}               ; {RING_WIDTH}×{RING_HEIGHT} текселей PALETTED4444',
        f'RING_LUT EQU #{ring_lut:06X}                ; 256 записей: палитра·16 + перо',
        f'RING_IMAGES EQU {ring_images}',
        f'RING_HANDLE EQU {RING_HANDLE}',
    ]
    (BUILD / 'rtype_ring.inc').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'кольцо фона: тайлов {TILES} ({len(tiles)} байт, одноцветных {sum(bin(b).count("1") for b in uniform)}) — '
          f'секторы {first}…{total - 1}, страниц ОЗУ {pages}; '
          f'RAM_G кольца #{ring_base:06X}, палитры #{ring_lut:06X}, картинок хосту {ring_images}; пак {len(body)} байт')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
