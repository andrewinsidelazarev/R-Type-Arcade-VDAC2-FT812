"""Страницы загрузчика данных уровней с SD (Source/ASM/rtype_loader.asm) и драйвера FAT32.

Драйвер — сборка проекта E:\\zx\\FAT32 Driver (build/fat32.bin — код, окно W1 #4000;
build/fat32-work.bin — рабочая страница, окно W0). Обработчики порта SD-ZC на #3900 — своя копия VDAC2+
(Source/ASM/vdac2p_sdzc.asm: те же четыре входа драйвера и пятый — чтение сектора через DMA SPI→RAM), собирается здесь
же вместо build/port_sdzc.bin драйвера. Адреса состояния драйвера, нужные загрузчику (найденная запись каталога, начало
раздела), берутся из build/fat32.sym.

Результат в Build/V30Z80: pages/page_XX.bin (рабочая страница драйвера, код драйвера,
загрузчик, буфер данных), rtype_loader.inc (константы загрузчика), rtype_loader_entry.inc (адреса
входов загрузчика для хоста видеоадаптера), rtype_loader.json.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'Build' / 'V30Z80'
ASM = ROOT / 'Source' / 'ASM'
DRIVER = Path('E:/zx/FAT32 Driver')
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
PAGE = 0x4000
# Страницы TS-Config: рабочая драйвера, код драйвера, загрузчик, буфер данных.
FAT_WORK_PAGE = 0x5A
FAT_CODE_PAGE = 0x5B
LOADER_PAGE = 0x5C
DATA_BUF_PAGE = 0x5D
HOST_W0_PAGE = 0x08                     # резидент машины (v30z80_build.RES_PAGE)
HOST_W3_PAGE = 0x0C                     # страница хоста видеоадаптера (v30z80_build.HOST_PAGE)
# Кэш секторов пака (rtype_loader.asm, CacheSector) — страницы только времени работы: в SPG их нет, загрузчик SPG их
# не обнуляет (метки слотов ставит LoaderInit). Свободны после старта SPG: #00…#04, #06, #07 (#05 — страница
# загрузчика SPG, там же его стек в #00 — только до перехода в игру), #EF и #F9…#FF (по карте памяти Wild Commander
# #E8…#EF — расширения ядра WC, #F0…#FF — сам Commander: заняты, пока работает загрузчик WC; #F0…#F8 во время игры —
# кольцо фона rtype_ring.py, так же проверено на Ево). Банки кода p2c #49…#4E не берутся: p2c_runtime_z80 занимает
# их по мере роста кода. Пересечения проверяют build() (кольцо) и rtype_spg.py (страницы SPG).
CACHE_PAGES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0xEF, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF)


def cell_sectors_max() -> int:
    """Наибольшее число секторов, на которые ложится поток одной ячейки пака (размер таблицы кусков LOADER_PIECES)."""
    pack = (BUILD / 'RTYPELVL.PAC').read_bytes()
    first, sectors = struct.unpack_from('<II', pack, 12)          # раздел 0 — индекс ячеек
    longest = 0
    for position in range(first * 512, (first + sectors) * 512, 8):
        start, within, length = struct.unpack_from('<IHH', pack, position)
        if start:
            longest = max(longest, ((within & 511) + length + 511) >> 9)
    return longest


def record_sectors_max(cells: int) -> int:
    """Секторов на поток записи LOADER_RECORD — наибольшее из ячеек и картинок объектов (vdac2p_objects.py)."""
    report = BUILD / 'rtype_objects.json'
    objects = json.loads(report.read_text(encoding='utf-8'))['longest_sectors'] if report.is_file() else 0
    return max(cells, objects)


def ring_pages() -> set[int]:
    """Страницы кольца фона (rtype_ring.inc): тайлы и рабочая."""
    values = dict(re.findall(r'^(RING_TILE_PAGE0|RING_TILE_PAGES|RING_WORK_PAGE) EQU (#?[0-9A-Fa-f]+)',
                             (BUILD / 'rtype_ring.inc').read_text(encoding='utf-8'), re.M))
    number = {name: int(text[1:], 16) if text.startswith('#') else int(text) for name, text in values.items()}
    return set(range(number['RING_TILE_PAGE0'], number['RING_TILE_PAGE0'] + number['RING_TILE_PAGES'])) | \
        {number['RING_WORK_PAGE']}


def driver_symbols() -> dict[str, int]:
    text = (DRIVER / 'build' / 'fat32.sym').read_text(encoding='latin1')
    return {match[1]: int(match[2], 16) for match in re.finditer(r'^([^:\s]+):\s+EQU\s+0x([0-9A-Fa-f]+)', text, re.M)}


def build() -> dict:
    symbols = driver_symbols()
    work = bytearray(PAGE)
    work_image = (DRIVER / 'build' / 'fat32-work.bin').read_bytes()
    work[0:len(work_image)] = work_image
    port_bin = BUILD / 'vdac2p_sdzc.bin'
    result = subprocess.run([str(SJASMPLUS), '--nologo', '--msg=war', f'--raw={port_bin}', str(ASM / 'vdac2p_sdzc.asm')],
                            cwd=ASM, capture_output=True, text=True, encoding='utf-8', errors='replace')
    output = result.stdout + result.stderr
    if result.returncode or 'error' in output.lower():
        raise SystemExit(output[-4000:])
    port = port_bin.read_bytes()
    if 0x3900 + len(port) > 0x4000:
        raise SystemExit('обработчик SD-ZC не помещается в рабочую страницу драйвера до #4000')
    work[0x3900:0x3900 + len(port)] = port
    code = bytearray(PAGE)
    code_image = (DRIVER / 'build' / 'fat32.bin').read_bytes()
    code[0:len(code_image)] = code_image
    pack = json.loads((BUILD / 'rtype_data.json').read_text(encoding='utf-8'))
    if pack['sectors'] > 0x10000:
        raise SystemExit('пак длиннее 65536 секторов: таблица CacheModulo загрузчика — на 2048 значений s >> 5')
    overlap = set(CACHE_PAGES) & (ring_pages() | {FAT_WORK_PAGE, FAT_CODE_PAGE, LOADER_PAGE, DATA_BUF_PAGE,
                                                   HOST_W0_PAGE, HOST_W3_PAGE})
    if overlap:
        raise SystemExit(f'страницы кэша секторов заняты: {sorted(hex(page) for page in overlap)}')
    pieces = cell_sectors_max()
    record_pieces = record_sectors_max(pieces)
    include = '\n'.join([
        '; Сгенерировано rtype_loader.py: страницы загрузчика и адреса состояния драйвера FAT32.',
        f'FAT_WORK_PAGE EQU #{FAT_WORK_PAGE:02X}',
        f'FAT_CODE_PAGE EQU #{FAT_CODE_PAGE:02X}',
        f'LOADER_PAGE EQU #{LOADER_PAGE:02X}',
        f'DATA_BUF_PAGE EQU #{DATA_BUF_PAGE:02X}',
        f'HOST_W0_PAGE EQU #{HOST_W0_PAGE:02X}',
        f'HOST_W3_PAGE EQU #{HOST_W3_PAGE:02X}',
        f'APPEND_ENTRY EQU #{symbols["WDOS_EXT.APPEND_ENTRY"]:04X}',
        f'WDOS_ADDTOP EQU #{symbols["WDOS.ADDTOP"]:04X}',
        f'PACK_SIZE EQU {pack["size"]}                  ; размер RTYPELVL.PAC: поиск на карте по имени и размеру',
        f'CELL_SECTORS_MAX EQU {pieces}                 ; секторов на поток ячейки, наибольшее по индексу пака',
        f'RECORD_SECTORS_MAX EQU {record_pieces}               ; то же у записи LOADER_RECORD (картинки объектов)',
        f'CACHE_PAGE_COUNT EQU {len(CACHE_PAGES)}',
        '                MACRO CACHE_PAGE_LIST',
        f'                DB {", ".join(f"#{page:02X}" for page in CACHE_PAGES)}',
        '                ENDM',
        ''])
    (BUILD / 'rtype_loader.inc').write_text(include, encoding='utf-8', newline='\n')
    loader_bin = BUILD / 'rtype_loader.bin'
    result = subprocess.run([str(SJASMPLUS), '--nologo', '--msg=war', f'-i{BUILD}', f'-i{DRIVER / "include"}',
                             f'--raw={loader_bin}', f'--sym={BUILD / "rtype_loader.sym"}', str(ASM / 'rtype_loader.asm')],
                            cwd=ASM, capture_output=True, text=True, encoding='utf-8', errors='replace')
    output = result.stdout + result.stderr
    if result.returncode or 'error' in output.lower():
        raise SystemExit(output[-4000:])
    loader = bytearray(PAGE)
    raw = loader_bin.read_bytes()
    loader[0:len(raw)] = raw
    loader_symbols = {match[1]: int(match[2], 16) for match in
                      re.finditer(r'^([A-Za-z_][\w.]*):\s+EQU\s+0x([0-9A-Fa-f]+)',
                                  (BUILD / 'rtype_loader.sym').read_text(encoding='latin1'), re.M)}
    entries = ('LOADER_INIT', 'LOADER_CELL', 'LOADER_READ', 'LOADER_READ_DMA', 'LOADER_RECORD', 'LOADER_OPEN',
               'LOADER_HOST_W1', 'LOADER_READY', 'LOADER_HOST_W3', 'LOADER_PIECES')
    (BUILD / 'rtype_loader_entry.inc').write_text('\n'.join(
        ['; Сгенерировано rtype_loader.py: входы загрузчика (страница LOADER_PAGE в окне W2).'] +
        [f'{name} EQU #{loader_symbols[name]:04X}' for name in entries] +
        [f'LOADER_PIECES_BYTES EQU {pieces * 2}          ; куски потока ячейки: страница и старший байт смещения',
         f'LOADER_RECORD_BYTES EQU {record_pieces * 2}          ; куски потока записи LOADER_RECORD']) +
        '\n', encoding='utf-8', newline='\n')
    pages_dir = BUILD / 'pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page, content in ((FAT_WORK_PAGE, work), (FAT_CODE_PAGE, code), (LOADER_PAGE, loader),
                          (DATA_BUF_PAGE, bytearray(PAGE))):
        (pages_dir / f'page_{page:02x}.bin').write_bytes(bytes(content))
    report = {'pages': [FAT_WORK_PAGE, FAT_CODE_PAGE, LOADER_PAGE, DATA_BUF_PAGE], 'fat_work_page': FAT_WORK_PAGE,
              'fat_code_page': FAT_CODE_PAGE, 'loader_page': LOADER_PAGE, 'data_buf_page': DATA_BUF_PAGE,
              'cache_pages': list(CACHE_PAGES), 'cell_sectors_max': pieces, 'record_sectors_max': record_pieces,
              'loader_size': len(raw), 'symbols': loader_symbols}
    (BUILD / 'rtype_loader.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = build()
    print(f'загрузчик: {report["loader_size"]} байт, страницы {", ".join(f"#{p:02X}" for p in report["pages"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
