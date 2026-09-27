"""Проба бюджета строки FT812 на реальной плате: Build/V30Z80/ft812_probe.spg.

Итоги на реале (фото пользователя 15.09). Проба 1 (≈1060 команд display list): рвётся только полоса со 120
ячейками 43×48 на строке (5160 px), целы 100 ячеек (4300 px), 240 выводов 8×8, 5 битмапов по 1024 px и 100
ячеек 27×30 с масштабом 8/5. Проба 2 (настоящие полосы тайлов игры, подпрограммы вызываются дважды: ≈2320
исполняемых команд) — рвутся все строки, даже со 150 px. Гипотеза: рендер FT812 проходит весь список на
каждой строке, и цена строки — прежде всего число команд списка, а не пиксели.

Эта проба (3) проверяет гипотезу: картинка одна и та же — 12 полос по 20 ячеек 43×48 (860 px на строку), а
списки отличаются только хвостом пустых команд после всех выводов. Списки сменяются сами каждые ≈5 с, клавиши
1…6 выбирают список сразу:
  1 — без хвоста; 2 — +600 NOP; 3 — +900 NOP; 4 — +1200 NOP; 5 — +900 вершин за экраном; 6 — +900 PALETTE_SOURCE.
Номер списка — подпись последней полосы «L1»…«L6» (шрифт ROM, handle 28). Программа — Source/ASM/ft812_probe.asm.
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'Build' / 'V30Z80'
ASM = ROOT / 'Source' / 'ASM'
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
SPGBLD = Path('E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe')
PAGE = 0x4000
BOOT_PAGE = 0x05
DATA_PAGE = 0x10
DL_PAGE0 = 0x11
PALETTED4444 = 15
BAND = 64
LABEL_HANDLE = 28
CELL = (43, 48)
CELLS_PER_BAND = 20
# Хвосты списков: (вид, число команд).
TAILS = [('nop', 0), ('nop', 600), ('nop', 900), ('nop', 1200), ('vertex', 900), ('palette', 900)]


def word(opcode: int, value: int = 0) -> int:
    return (opcode << 24) | value


def vertex2f(x: int, y: int) -> int:
    return (1 << 30) | ((x & 0x7FFF) << 15) | (y & 0x7FFF)


def content() -> bytes:
    """Таблица палитры (0 — прозрачный, остальные — оттенки по кругу) и ячейка 43×48 с кольцами."""
    data = bytearray()
    for index in range(256):
        if index == 0:
            data += struct.pack('<H', 0)
            continue
        hue = (index - 1) * 6 / 255
        sector, fraction = int(hue) % 6, hue - int(hue)
        rise, fall = int(15 * fraction), int(15 * (1 - fraction))
        red, green, blue = [(15, rise, 0), (fall, 15, 0), (0, 15, rise), (0, fall, 15), (rise, 0, 15),
                            (15, 0, fall)][sector]
        data += struct.pack('<H', (15 << 12) | (red << 8) | (green << 4) | blue)
    width, height = CELL
    for y in range(height):
        for x in range(width):
            distance = (x - 21) ** 2 + (y - 24) ** 2
            data.append((1 + distance // 6 % 250) if distance < 21 * 21 else 0)
    while len(data) % 4:
        data.append(0)
    return bytes(data)


def display_list(number: int, tail: tuple[str, int]) -> list[int]:
    width, height = CELL
    words = [word(2, 0), word(38, 7), word(39, 0), word(42, 0), word(4, 0xFFFFFF), word(0x1F, 1),
             word(5, 1), word(1, 512), word(7, (PALETTED4444 << 19) | (width << 9) | height), word(40, 0),
             word(8, (width << 9) | height), word(41, 0)]                   # NEAREST, BORDER — как в игре
    for band in range(12):
        top = band * BAND
        # У полос — номер, у последней вместо номера — номер списка («L4»): так видно, какая клавиша нажата.
        label = f'L{number + 1}' if band == 11 else f'{band + 1}'
        words.append(word(5, LABEL_HANDLE))
        for position, char in enumerate(label):
            words += [word(6, ord(char)), vertex2f(4 + position * 16, top + 18)]
        words += [word(5, 1), word(6, 0)]
        span = 1024 - 60 - width
        words += [vertex2f(60 + span * index // (CELLS_PER_BAND - 1), top + 8) for index in range(CELLS_PER_BAND)]
    kind, count = tail
    if kind == 'nop':
        words += [word(45)] * count
    elif kind == 'vertex':
        words += [vertex2f(0, 900)] * count                                 # вершины за экраном
    else:
        words += [word(42, 0)] * count                                      # PALETTE_SOURCE тот же адрес
    words += [word(0x21), word(0)]                                          # END, DISPLAY
    assert len(words) * 4 <= 8176, len(words)
    return words


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    data = content()
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'probe_data.bin').write_bytes(data + bytes(PAGE - len(data)))
    sizes = []
    for number, tail in enumerate(TAILS):
        words = display_list(number, tail)
        dl = b''.join(struct.pack('<I', value) for value in words)
        (BUILD / f'probe_dl{number}.bin').write_bytes(dl + bytes(PAGE - len(dl)))
        sizes.append(len(dl))
    for stale in ('probe_dl.bin', 'probe_dla.bin', 'probe_dlb.bin', 'probe_dlc.bin'):
        (BUILD / stale).unlink(missing_ok=True)
    include = ['; Сгенерировано ft812_probe.py: страницы данных пробы и размеры списков.',
               f'PROBE_DATA_PAGE EQU #{DATA_PAGE:02X}', f'PROBE_DATA_BYTES EQU {len(data)}',
               f'PROBE_DL_PAGE0 EQU #{DL_PAGE0:02X}', f'PROBE_LISTS EQU {len(TAILS)}', 'PROBE_DL_BYTES:']
    include += [f'                DW {size}' for size in sizes] + ['']
    (BUILD / 'ft812_probe.inc').write_text('\n'.join(include), encoding='utf-8', newline='\n')
    result = subprocess.run([str(SJASMPLUS), '--nologo', '--msg=war', str(ASM / 'ft812_probe.asm'), '--syntax=ab'],
                            cwd=ASM, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout[-3000:] + result.stderr[-3000:])
        return 1
    ini = ['Desc = FT812 line budget probe', 'Start = 0x5000', 'Stack = 0x3FFF', 'Resident = 0x4F00', 'Page3 = 0',
           'Clock = 2', 'INT = 0', 'Pager = 0', 'Compression = 0', '',
           f'Block = #5000, #{BOOT_PAGE:02X}, Build/V30Z80/ft812_probe.bin',
           f'Block = #0000, #{DATA_PAGE:02X}, Build/V30Z80/probe_data.bin']
    ini += [f'Block = #0000, #{DL_PAGE0 + number:02X}, Build/V30Z80/probe_dl{number}.bin'
            for number in range(len(TAILS))] + ['']
    (BUILD / 'ft812_probe.ini').write_text('\n'.join(ini), encoding='utf-8', newline='\n')
    result = subprocess.run([str(SPGBLD), '-b', str(BUILD / 'ft812_probe.ini'), str(BUILD / 'ft812_probe.spg')],
                            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout[-3000:] + result.stderr[-3000:])
        return 1
    print(f'проба: {BUILD / "ft812_probe.spg"}')
    for number, (tail, size) in enumerate(zip(TAILS, sizes)):
        print(f'  клавиша {number + 1}: хвост {tail[0]} × {tail[1]}, команд в списке {size // 4}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
