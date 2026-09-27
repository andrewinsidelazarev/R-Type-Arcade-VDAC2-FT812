"""Файл данных уровней на SD-карте `RTYPELVL.PAC`: HQ-ячейки тайлов и спрайтов всех палитр.

Ячейки те же, что у M72HqRenderer (HQ-атласы проекта и карты смешения перьев), в кодировке
видеоадаптера FT812 (v30z80_video_assets.encode, двухпроходные PALETTED4444): проход A — перо A
с уровнем альфы, проход B — перо B (у спрайтов с 2026-09-25 у непрозрачного пикселя в A — главное перо смеси,
m72_ft812_compositor.encode_cell, dominant_a; у фона с того же дня перо 0 прозрачно — фон ячейками выводится
только в высоком проходе). В файле все коды 0…4095 трёх наборов (передний слой, фон,
спрайты) во всех 16 палитрах, неотражённые: отражение выполняет FT812 матрицей
BITMAP_TRANSFORM при выводе. Одинаковые изображения хранятся один раз (на них указывают
несколько записей индекса).

Раскладка для простого чтения секторами 512 байт при объёме в пределах образа SD 32 МБ:
заголовок и индекс выровнены по секторам, запись индекса — постоянной длины и сразу даёт первый
сектор ячейки, смещение потока в нём и длину, так что ячейка — одно чтение подряд идущих
секторов; сами ячейки идут подряд с выравниванием по 4 байта.

Формат (little-endian):
  сектор 0 — заголовок: +0 «RTYPEDAT», +8 версия (слово), +10 число разделов (слово),
    +12 разделы по 8 байт (первый сектор, число секторов — двойные слова): 0 — индекс ячеек,
    1 — ячейки, 2 — музыка TSFM (пока пуст), 3 — эффекты GS (пока пуст); +44 секторов в файле.
  индекс — с сектора 1, блок из 64 секторов на (набор·16 + палитра), запись 8 байт на код:
    сектор = 1 + (набор·16 + палитра)·64 + код >> 6, смещение в секторе (код & 63)·8.
    Запись: +0 первый сектор ячейки (двойное слово; 0 — пустая ячейка), +4 смещение потока в
    первом секторе (биты 0…8; бит 14 — есть проход A, бит 15 — есть проход B), +6 длина потока
    zlib в байтах (кратна 4).
  ячейка — поток zlib для CMD_INFLATE: байты прохода A и сразу за ними прохода B (в RAM_G слоты
    A и B соседние), дополненный нулями до кратного 4.

Результат — Build/V30Z80/RTYPELVL.PAC и отчёт rtype_data.json (разделы, число ячеек, SHA-256).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
sys.path.insert(0, str(ROOT / 'Source' / 'Python'))

import v30z80  # noqa: E402,F401  (до numpy: порядок импорта numba)
import numpy as np  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
SECTOR = 512
MAGIC = b'RTYPEDAT'
VERSION = 3
SETS = ('tiles0', 'tiles1', 'sprites')
CELL_SIZE = {'tiles0': 14 * 15, 'tiles1': 14 * 15, 'sprites': 27 * 30}
INDEX_SECTOR = 1
ENTRY = 8
INDEX_BLOCK_SECTORS = 4096 * ENTRY // SECTOR
FLAG_A = 1 << 14
FLAG_B = 1 << 15
FILE_LIMIT = 31 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', default=str(BUILD / 'RTYPELVL.PAC'))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    import m72_ft812_compositor as compositor
    import v30z80_video_assets as assets
    cells = compositor.load_cells()
    # Ячейками фон выводится только в высоком проходе приоритета (низкий — кольцо фона, v30z80_ring.asm; PASS_TABLE
    # хоста): у M72 перо 0 фона там прозрачно (BG_LAYER0, BG_PRIORITY MAME m72_v.cpp) — маска пера 0, как у переднего
    # слоя (2026-09-25: фон группы 2 перешёл в высокий проход, и непрозрачное перо 0 закрывало бы спрайты). Без кольца
    # (сбой чтения родных тайлов, диагностика RTYPE_NO_RING) перо 0 фона — прозрачно, под ним — цвет очистки.
    cells['tiles1'] = dataclasses.replace(cells['tiles1'], pen0_masked=True, cache={})

    index_sectors = len(SETS) * 16 * INDEX_BLOCK_SECTORS
    index = bytearray(index_sectors * SECTOR)
    first_cell_sector = INDEX_SECTOR + index_sectors
    streams = bytearray()
    known: dict[tuple[int, bytes], tuple[int, int]] = {}
    counts = {'cells': 0, 'empty': 0, 'images': 0, 'shared': 0, 'longest': 0}
    for set_number, name in enumerate(SETS):
        size = CELL_SIZE[name]
        atlas = cells[name].atlases
        present = ((atlas >> 12) & 15).reshape(16, 4096, -1).any(axis=2)
        for palette in range(16):
            for code in range(4096):
                counts['cells'] += 1
                position = (set_number * 16 + palette) * INDEX_BLOCK_SECTORS * SECTOR + code * ENTRY
                if not present[palette, code]:
                    counts['empty'] += 1
                    continue
                pass_a, pass_b, _solid = assets.encode(cells, name, palette, code, 0, 0)
                if pass_a is None and pass_b is None:
                    counts['empty'] += 1
                    continue
                pixels = np.zeros(size * 2, dtype=np.uint8)
                if pass_a is not None:
                    pixels[:size] = pass_a.reshape(-1)
                if pass_b is not None:
                    pixels[size:] = pass_b.reshape(-1)
                raw = pixels.tobytes()
                key = (set_number, hashlib.sha1(raw).digest())
                found = known.get(key)
                if found is None:
                    packed = zlib.compress(raw, 9)
                    packed += bytes((-len(packed)) % 4)
                    start = first_cell_sector * SECTOR + len(streams)
                    streams += packed
                    found = (start, len(packed))
                    known[key] = found
                    counts['images'] += 1
                    counts['longest'] = max(counts['longest'], len(packed))
                else:
                    counts['shared'] += 1
                start, length = found
                flags = (FLAG_A if pass_a is not None else 0) | (FLAG_B if pass_b is not None else 0)
                struct.pack_into('<IHH', index, position, start // SECTOR, (start % SECTOR) | flags, length)
            cells[name].cache.clear()
        print(f'{name}: изображений {counts["images"]}, общих записей {counts["shared"]}, '
              f'{time.perf_counter() - started:.0f} с', flush=True)
    streams += bytes((-len(streams)) % SECTOR)
    sectors = first_cell_sector + len(streams) // SECTOR
    if sectors * SECTOR > FILE_LIMIT:
        raise SystemExit(f'файл {sectors * SECTOR} байт больше {FILE_LIMIT}: не помещается в образ SD 32 МБ')
    header = bytearray(SECTOR)
    header[0:8] = MAGIC
    sections = [(INDEX_SECTOR, index_sectors), (first_cell_sector, len(streams) // SECTOR), (sectors, 0), (sectors, 0)]
    struct.pack_into('<HH', header, 8, VERSION, len(sections))
    for number, (first, count) in enumerate(sections):
        struct.pack_into('<II', header, 12 + number * 8, first, count)
    struct.pack_into('<I', header, 44, sectors)
    output = Path(args.output)
    digest = hashlib.sha256()
    with output.open('wb') as out:
        for part in (header, index, streams):
            out.write(part)
            digest.update(part)
    report = {'file': output.name, 'size': sectors * SECTOR, 'sectors': sectors, 'sha256': digest.hexdigest(),
              'sections': {'index': sections[0], 'cells': sections[1], 'music': sections[2], 'effects': sections[3]},
              **counts}
    (BUILD / 'rtype_data.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{output}: {sectors * SECTOR} байт ({sectors} секторов), изображений {counts["images"]} (общих записей '
          f'{counts["shared"]}, пустых {counts["empty"]}), самый длинный поток {counts["longest"]} байт, '
          f'{time.perf_counter() - started:.0f} с')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
