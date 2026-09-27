#!/usr/bin/env python3
"""Цена строки развёртки FT812 по выгруженному display list.

Вход — сырые слова показанного списка (`v30z80_video_check.py --dl-dump`). Модель стоимости та же,
что зафиксирована в проекте по замерам на эмуляторе: растеризатор проходит список для каждой из 768
строк, поэтому **команда стоит такт на каждой строке**, а закрашивание в PALETTED4444 с NEAREST идёт
**8 пикселей за такт** (BILINEAR — 2, но он у нас запрещён). Итог строки = число команд списка +
сумма ширин примитивов, попавших в строку, делённая на 8.

Подпрограммы (`CALL`/`RETURN`) раскрываются: их содержимое растеризатор читает при каждом проходе,
поэтому вызов подпрограммы дважды (проходы A и B) стоит вдвое и по командам, и по пикселям.

Печатается разбивка: сколько тактов уходит на команды, сколько на пиксели, худшая и медианная строка,
и самые дорогие примитивы — чтобы видеть, за что платим.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

LINES = 768                      # строк физической развёртки VM_1024_768_59Hz
WIDTH = 1024
PIXELS_PER_TICK = 8              # PALETTED4444, NEAREST


NAMES = {0x01: 'BITMAP_SOURCE', 0x02: 'CLEAR_COLOR_RGB', 0x04: 'COLOR_RGB', 0x05: 'BITMAP_HANDLE',
         0x06: 'CELL', 0x07: 'BITMAP_LAYOUT', 0x08: 'BITMAP_SIZE', 0x0B: 'BLEND_FUNC', 0x0D: 'POINT_SIZE',
         0x10: 'COLOR_A', 0x15: 'TRANSFORM_A', 0x16: 'TRANSFORM_B', 0x17: 'TRANSFORM_C', 0x18: 'TRANSFORM_D',
         0x19: 'TRANSFORM_E', 0x1A: 'TRANSFORM_F', 0x1B: 'SCISSOR_XY', 0x1C: 'SCISSOR_SIZE', 0x1D: 'CALL',
         0x1E: 'JUMP', 0x1F: 'BEGIN', 0x21: 'END', 0x22: 'SAVE_CONTEXT', 0x23: 'RESTORE_CONTEXT',
         0x24: 'RETURN', 0x26: 'CLEAR', 0x27: 'VERTEX_FORMAT', 0x28: 'BITMAP_LAYOUT_H', 0x29: 'BITMAP_SIZE_H',
         0x2A: 'PALETTE_SOURCE', 0x2B: 'VERTEX_TRANSLATE_X', 0x2C: 'VERTEX_TRANSLATE_Y', 0x2D: 'NOP'}


def clip(first: int, last: int, width: int, kind: str, scissor_y: int, scissor_h: int, scissor_w: int,
         left: int = 0) -> tuple[int, int, int, str, int]:
    """Примитив в пределах ножниц: строки обрезаются окном, ширина — его шириной; left — левый край."""
    return (max(first, scissor_y), min(last, scissor_y + scissor_h), min(width, scissor_w), kind, left)


def parse(words: list[int], sizes: dict[int, tuple[int, int]] | None = None,
          kinds: dict[str, int] | None = None) -> tuple[int, list[tuple[int, int, int, str]]]:
    """Список слов → (число прочитанных команд, примитивы [первая строка, последняя+1, ширина, вид]).

    Состояние FT81x держится между словами: размер битмапа (`BITMAP_SIZE`), масштаб (`BITMAP_TRANSFORM_A/E`,
    256 = 1:1), сдвиг вершин (`VERTEX_TRANSLATE_X/Y`), текущий примитив (`BEGIN`). Координаты — в единицах
    1/8 пикселя (`VERTEX_FORMAT 3`), как во всём порте.
    """
    commands = 0
    vertex_format = 4               # единица VERTEX2F — 1/2^format пикселя; сброс списка даёт 4 (1/16)
    primitives: list[tuple[int, int, int, str]] = []
    sizes = {} if sizes is None else sizes      # handle → размер отрисовки: FT812 хранит его между кадрами,
                                                # список кадра задаёт размеры только после сброса видео
    handle = 0
    scale_a = scale_e = 256
    translate_x = translate_y = 0
    begin = 'BITMAPS'
    point_size = 16
    scissor_y, scissor_h = 0, LINES             # ножницы отсекают примитивы по строкам: полоса слоя рисуется
    scissor_x, scissor_w = 0, WIDTH             # только в своём диапазоне, иначе цена строки завышается
    stack: list[int] = []
    index = 0
    guard = 0
    while 0 <= index < len(words):
        guard += 1
        if guard > 400000:
            break
        word = words[index]
        commands += 1
        opcode = word >> 24
        if kinds is not None:
            kinds['VERTEX' if word >> 31 or word >> 30 == 1 else NAMES.get(opcode, f'#{opcode:02X}')] =                 kinds.get('VERTEX' if word >> 31 or word >> 30 == 1 else NAMES.get(opcode, f'#{opcode:02X}'), 0) + 1
        if word >> 30 == 1:                                     # VERTEX2F
            x = ((word >> 15) & 0x7FFF)
            y = word & 0x7FFF
            x = x - 0x8000 if x >= 0x4000 else x
            y = y - 0x8000 if y >= 0x4000 else y
            # VERTEX2F — единицы 1/2^VERTEX_FORMAT пикселя (у нас кольцо идёт при умолчании 4, спрайты и
            # полосы — VERTEX2II), а VERTEX_TRANSLATE — всегда 1/16.
            px = x // (1 << vertex_format) + translate_x // 16
            py = y // (1 << vertex_format) + translate_y // 16
            if begin == 'POINTS':
                radius = max(1, point_size // 16)
                primitives.append(clip(py - radius, py + radius, 2 * radius, 'точка',
                                       scissor_y, scissor_h, scissor_w, px))
            else:
                out_w, out_h = sizes.get(handle, (0, 0))
                primitives.append(clip(py, py + out_h, out_w, f'handle {handle}',
                                       scissor_y, scissor_h, scissor_w, px))
        elif word >> 30 == 2:                                   # VERTEX2II — координаты 9 бит, поэтому
            y = ((word >> 12) & 0x1FF) + translate_y // 16      # позиция на экране задаётся сдвигом вершин
            hnd = (word >> 7) & 31
            out_w, out_h = sizes.get(hnd, (0, 0))
            primitives.append(clip(y, y + out_h, out_w, f'handle {hnd}', scissor_y, scissor_h, scissor_w,
                                   ((word >> 21) & 0x1FF) + translate_x // 16))
        elif opcode == 0x05:                                    # BITMAP_HANDLE
            handle = word & 31
        elif opcode == 0x08:                                    # BITMAP_SIZE — размер отрисовки текущего handle
            width, height = (word >> 9) & 0x1FF, word & 0x1FF
            high_w, high_h = sizes.get(handle, (0, 0))
            sizes[handle] = (width | (high_w & ~0x1FF), height | (high_h & ~0x1FF))
        elif opcode == 0x29:                                    # BITMAP_SIZE_H — старшие биты размера
            width, height = sizes.get(handle, (0, 0))
            sizes[handle] = ((width & 0x1FF) | (((word >> 2) & 3) << 9), (height & 0x1FF) | ((word & 3) << 9))
        elif opcode == 0x15:                                    # BITMAP_TRANSFORM_A
            scale_a = word & 0x1FFFF
        elif opcode == 0x19:                                    # BITMAP_TRANSFORM_E
            scale_e = word & 0x1FFFF
        elif opcode == 0x2B:                                    # VERTEX_TRANSLATE_X — 17 бит со знаком, 1/16 px
            translate_x = (word & 0x1FFFF) - (0x20000 if word & 0x10000 else 0)
        elif opcode == 0x2C:                                    # VERTEX_TRANSLATE_Y
            translate_y = (word & 0x1FFFF) - (0x20000 if word & 0x10000 else 0)
        elif opcode == 0x27:                                    # VERTEX_FORMAT — единица VERTEX2F
            vertex_format = word & 7
        elif opcode == 0x0D:                                    # POINT_SIZE
            point_size = word & 0x1FFF
        elif opcode == 0x1F:                                    # BEGIN
            begin = {1: 'BITMAPS', 2: 'POINTS', 3: 'LINES', 9: 'RECTS'}.get(word & 15, 'BITMAPS')
        elif opcode == 0x1B:                                    # SCISSOR_XY — левый верхний угол окна
            scissor_x, scissor_y = (word >> 11) & 0x7FF, word & 0x7FF
        elif opcode == 0x1C:                                    # SCISSOR_SIZE — размер окна вывода
            scissor_w, scissor_h = (word >> 12) & 0xFFF, word & 0xFFF
        elif opcode == 0x26:                                    # CLEAR — только в пределах ножниц
            primitives.append((scissor_y, min(LINES, scissor_y + scissor_h), min(WIDTH, scissor_w),
                               'очистка', scissor_x))
        elif opcode == 0x1D:                                    # CALL
            stack.append(index + 1)
            index = word & 0xFFFF
            continue
        elif opcode == 0x24:                                    # RETURN
            index = stack.pop() if stack else len(words)
            continue
        elif opcode == 0x1E:                                    # JUMP
            index = word & 0xFFFF
            continue
        elif opcode == 0x00:                                    # DISPLAY
            break
        index += 1
    return commands, primitives


def report(name: str, words: list[int], sizes: dict[int, tuple[int, int]]) -> None:
    kinds_count: dict[str, int] = {}
    commands, primitives = parse(words, sizes, kinds_count)
    pixels = [0] * LINES
    for first, last, width, _, _left in primitives:
        for line in range(max(0, first), min(LINES, last)):
            pixels[line] += width
    ticks = [commands + value // PIXELS_PER_TICK for value in pixels]
    worst = max(range(LINES), key=lambda i: ticks[i])
    ordered = sorted(ticks)
    print(f'{name}: слов {len(words)}, команд при проходе строки {commands}, примитивов {len(primitives)}')
    print(f'  такты строки: медиана {ordered[LINES // 2]}, 90 % {ordered[int(LINES * 0.9)]}, максимум {ticks[worst]}'
          f' (строка {worst}); из них команды {commands}, пиксели худшей строки {pixels[worst] // PIXELS_PER_TICK}')
    kinds: dict[str, int] = {}
    for first, last, width, kind, _left in primitives:
        covered = max(0, min(LINES, last) - max(0, first))
        kinds[kind] = kinds.get(kind, 0) + covered * width // PIXELS_PER_TICK
    total = sum(kinds.values()) or 1
    for kind, value in sorted(kinds.items(), key=lambda item: -item[1]):
        print(f'  пиксели по видам: {kind:10} {value * 100 // total:3} % ({value // LINES} тактов на строку в среднем)')
    top = sorted(kinds_count.items(), key=lambda item: -item[1])[:10]
    print('  команды на строку: ' + ', '.join(f'{k} {v}' for k, v in top))
    # Состав худшей строки: за что платим в пике развёртки.
    worst_kinds: dict[str, int] = {}
    for first, last, width, kind, _left in primitives:
        if first <= worst < last:
            worst_kinds[kind] = worst_kinds.get(kind, 0) + width // PIXELS_PER_TICK
    print(f'  худшая строка {worst}: ' + ', '.join(
        f'{k} {v}' for k, v in sorted(worst_kinds.items(), key=lambda item: -item[1])))
    # Перекрытие в худшей строке: сколько раз закрашивается каждый столбец экрана.
    cover = [0] * WIDTH
    for first, last, width, kind, left in primitives:
        if first <= worst < last and kind != 'очистка':
            for column in range(max(0, left), min(WIDTH, left + width)):
                cover[column] += 1
    busy = [c for c in cover if c]
    if busy:
        print(f'  перекрытие в худшей строке: среднее {sum(busy) / len(busy):.1f}, максимум {max(busy)}, '
              f'закрашено столбцов {len(busy)} из {WIDTH}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files', nargs='+', type=Path, help='файлы .dl из --dl-dump')
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    # Размеры отрисовки handle FT812 задаёт таблица первого списка после сброса видео, а дальше чип помнит
    # их сам, поэтому в списке игрового кадра их нет: берём ту же таблицу из генератора ассетов.
    sizes: dict[int, tuple[int, int]] = {}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import v30z80_video_assets as assets
    parse(assets.dl_handles(assets.layout()), sizes)
    for path in args.files:
        raw = path.read_bytes()
        words = [struct.unpack_from('<I', raw, offset)[0] for offset in range(0, len(raw) - 3, 4)]
        report(path.name, words, sizes)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
