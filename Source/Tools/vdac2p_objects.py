#!/usr/bin/env python3
"""Спрайты объектами (VDAC2+, решение пользователя 2026-09-25 «да» на «собирать многоклеточные спрайты в одну картинку
офлайн»): раздел картинок объектов в хвосте пака RTYPELVL.PAC и каталог объектов для ОЗУ Z80.

Объект — многоклеточная запись sprite RAM M72: палитра, код, ширина × высота в ячейках 16×16 (2×2, 2×4, 2×1, 1×2, 1×4 —
других многоклеточных в игре нет). Его картинка складывается из ячеек самого пака (набор 2, та же палитра, код +
8·столбец + строка): проход A объекта — проходы A ячеек на местах (столбец·27, строка·30) текселей, проход B — так же.
Отражения не хранятся — их даёт матрица FT812, как у ячейки. Тексели — ровно те, что выводятся ячейками; отличие вывода
— только положение правого столбца: ячейки округляются до пикселя каждая, у объекта столбец на 27 текселей правее (у
эталона M72HqRenderer в одном положении из трёх — на 26).

Какие объекты — перепись модели реального времени (`RT_OBJECTS` vdac2p_realtime.py: все показанные кадры восьми
этапов сценария автоогня): список Assets/Converted/sprite_objects.json (палитра, код, ширина, высота, кадров с объектом)
по убыванию частоты. Объекты берутся по частоте, пока хватает места в образе SD (непрерывное свободное место за паком
и SPG — файлы лежат подряд, rtype_sd_image.py) или --budget. Остальные выводятся ячейками, как раньше.

Раздел — в хвосте пака, за эффектами AY (rtype_ay_sfx.py --pack; шаг пака последний перед rtype_loader.py):
  каталог — 32 сектора (страница Z80 16 КБ): 512 корзин по 2 байта (смещение первой записи в странице, 0 — пусто),
    с #0400 записи по 11 байт: +0 младший байт кода, +1 старшие 4 бита кода | класс << 4, +2 палитра, +3 следующая в
    корзине (слово: смещение, 0 — конец), +5 первый сектор потока (слово), +7 смещение потока в секторе / 4 (биты 0…6) |
    проход A (бит 7), +8 длина потока / 4 (биты 0…13) | проход B (бит 15), +10 четверть пула (#FF — не загружен; ставит
    Z80). Корзина — 9 бит: биты 0…7 — (код >> 1) & #FF ^ палитра·17 ^ CLASS_MIX[класс], бит 8 — (бит 9 кода ^ бит 0
    кода ^ класс) & 1; в корзине частые объекты первыми (замер списка: в среднем 1,22 записи на поиск, цепочки до 8).
  потоки — zlib для CMD_INFLATE: проход A объекта (ширина·27 × высота·30 байт по строкам), сразу за ним проход B;
    выравнивание по 4 байта; одинаковые картинки — один поток.
Классы: 0 — 2×2, 1 — 2×4, 2 — 2×1, 3 — 1×2, 4 — 1×4.
Заголовок пака: +48 «OBJ1», +52 первый сектор каталога, +56 секторов каталога, +60 первый сектор потоков, +64 секторов
потоков, +68 объектов (слово); +44 — секторов в файле. Повторный запуск снимает прежний раздел (пак режется за эффектами AY).

Результат: Build/V30Z80/RTYPELVL.PAC (дописан), rtype_objects.inc (константы Z80), rtype_objects.json (отчёт),
rtype_data.json (новый размер пака — по нему загрузчик ищет файл на карте).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'Build' / 'V30Z80'
PACK = BUILD / 'RTYPELVL.PAC'
OBJECT_LIST = ROOT / 'Assets' / 'Converted' / 'sprite_objects.json'
SECTOR = 512
MAGIC = b'OBJ1'
DIR_SECTORS = 32                                  # страница Z80 16 КБ
BUCKETS = 512
ENTRY = 11
ENTRIES_OFFSET = BUCKETS * 2                      # #0400: записи сразу за корзинами
CELL_W, CELL_H = 27, 30                          # тексели ячейки спрайта (проход)
# Классы размеров: номер в каталоге и в Z80 (handle, таблицы), ширина и высота в ячейках.
CLASSES = {(2, 2): 0, (2, 4): 1, (2, 1): 2, (1, 2): 3, (1, 4): 4}
CLASS_MIX = (0, 80, 160, 240, 64)                 # класс в хеше корзины (таблица Z80 OBJ_CLASS_MIX)
SPG_RESERVE = 128 * 1024                          # запас образа SD на рост SPG
# SPG и код игры RTYPECOD.PAC вместе (с 2026-09-27 — загрузчик SPG с заставкой ≈0,5 МБ и код ≈2,1 МБ; раньше весь код
# был в SPG, около 2 МБ).
SPG_FLOOR = 2600 * 1024


def bucket_of(code: int, palette: int, cls: int) -> int:
    """Корзина ключа (9 бит), Z80 считает так же (vdac2p_objects.asm, ObjFind)."""
    low = ((code >> 1) & 0xFF) ^ (palette * 17) ^ CLASS_MIX[cls]
    high = ((code >> 9) ^ code ^ cls) & 1
    return low | (high << 8)


def read_cell(pack: bytes, palette: int, code: int) -> tuple[bytes, bytes, bool, bool]:
    """Проходы A и B ячейки спрайта пака (по 810 байт) и признаки проходов."""
    position = (1 + (32 + palette) * 64 + (code >> 6)) * SECTOR + (code & 63) * 8
    first, within, length = struct.unpack_from('<IHH', pack, position)
    if not first:
        return bytes(CELL_W * CELL_H), bytes(CELL_W * CELL_H), False, False
    start = first * SECTOR + (within & 511)
    raw = zlib.decompress(pack[start:start + length])
    assert len(raw) == 2 * CELL_W * CELL_H, (palette, code, len(raw))
    return raw[:CELL_W * CELL_H], raw[CELL_W * CELL_H:], bool(within & 0x4000), bool(within & 0x8000)


def compose(pack: bytes, palette: int, code: int, width: int, height: int) -> tuple[bytes, bool, bool]:
    """Проходы A и B объекта подряд и признаки проходов."""
    out_w, out_h = width * CELL_W, height * CELL_H
    pass_a = bytearray(out_w * out_h)
    pass_b = bytearray(out_w * out_h)
    has_a = has_b = False
    for cx in range(width):
        for cy in range(height):
            cell_a, cell_b, flag_a, flag_b = read_cell(pack, palette, (code + 8 * cx + cy) & 0x0FFF)
            has_a |= flag_a
            has_b |= flag_b
            for row in range(CELL_H):
                target = (cy * CELL_H + row) * out_w + cx * CELL_W
                pass_a[target:target + CELL_W] = cell_a[row * CELL_W:(row + 1) * CELL_W]
                pass_b[target:target + CELL_W] = cell_b[row * CELL_W:(row + 1) * CELL_W]
    return bytes(pass_a) + bytes(pass_b), has_a, has_b


def image_room(base_bytes: int) -> int:
    """Байт на раздел объектов в образе SD: непрерывное место с начала пака (прежние цепочки пака и SPG освобождены)
    за паком без раздела, SPG и запасом на его рост — как их разложит rtype_sd_image.py."""
    sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
    from rtype_sd_image import FILES, Fat32  # noqa: E402
    fat = Fat32(bytearray((BUILD / 'rtype_sd.img').read_bytes()))
    places = [fat.find(name) for name, _path in FILES]
    if not places[0]:
        raise SystemExit('в образе SD нет пака уровней')
    places = [place for place in places if place]           # RTYPECOD.PAC в образе может ещё не быть
    start = min(first for first, _size, _entry in places)
    own = set()
    for first, _size, _entry in places:
        own.update(fat.chain(first))
    cluster = start
    while cluster < fat.clusters and (fat.get(cluster) == 0 or cluster in own):
        cluster += 1
    room = (cluster - start) * fat.cluster_bytes
    # SPG и RTYPECOD.PAC — прежней сборки (на этом шаге новых ещё нет), не меньше SPG_FLOOR.
    code_files = (BUILD / 'rtype_vdac2.spg', BUILD / 'RTYPECOD.PAC')
    spg = max(sum(path.stat().st_size for path in code_files if path.is_file()), SPG_FLOOR) + SPG_RESERVE
    spg = -(-spg // fat.cluster_bytes) * fat.cluster_bytes
    base = -(-base_bytes // fat.cluster_bytes) * fat.cluster_bytes
    return room - spg - base


def object_list(census_paths: list[str]) -> list[list[int]]:
    """Список объектов: из переписей RT_OBJECTS (записывается в Assets/Converted) или готовый."""
    if not census_paths:
        return json.loads(OBJECT_LIST.read_text(encoding='utf-8'))['objects']
    seen: dict[tuple[int, int, int, int], int] = {}
    for path in census_paths:
        census = json.loads(Path(path).read_text(encoding='utf-8'))
        for key, (frames, _first) in census['objects'].items():
            palette, code, width, height = (int(value) for value in key.split(','))
            if (width, height) in CLASSES:
                seen[(palette, code, width, height)] = seen.get((palette, code, width, height), 0) + frames
    objects = [[*key, frames] for key, frames in sorted(seen.items(), key=lambda item: (-item[1], item[0]))]
    OBJECT_LIST.parent.mkdir(parents=True, exist_ok=True)
    OBJECT_LIST.write_text(json.dumps({
        'source': 'vdac2p_realtime.py RT_OBJECTS: показанные кадры восьми этапов сценария автоогня',
        'fields': ['палитра', 'код', 'ширина', 'высота', 'кадров'],
        'objects': objects}, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    return objects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--census', nargs='*', default=[], help='переписи RT_OBJECTS (JSON): обновить список объектов')
    parser.add_argument('--budget', type=int, default=0, help='байт на раздел (по умолчанию — место в образе SD)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    objects = object_list(args.census)
    data_report = json.loads((BUILD / 'rtype_data.json').read_text(encoding='utf-8'))
    tail = data_report.get('ay_sfx')
    if tail is None:
        raise SystemExit('в отчёте пака нет эффектов AY: сначала rtype_ay_sfx.py --pack')
    pack = bytearray(PACK.read_bytes()[:(tail['sector'] + tail['sectors']) * SECTOR])
    pack[48:72] = bytes(24)                       # прежний раздел объектов снят
    budget = args.budget or image_room(len(pack))
    streams = bytearray()
    known: dict[bytes, tuple[int, int]] = {}
    records = []
    total_frames = sum(item[4] for item in objects)
    kept_frames = 0
    for palette, code, width, height, frames in objects:
        raw, has_a, has_b = compose(pack, palette, code, width, height)
        if not has_a and not has_b:
            continue                              # пустой объект: ячейки пустые, выводить нечего
        digest = hashlib.sha1(raw).digest()
        found = known.get(digest)
        grow = 0
        if found is None:
            packed = zlib.compress(raw, 9)
            packed += bytes((-len(packed)) % 4)
            grow = len(packed)
        if DIR_SECTORS * SECTOR + len(streams) + grow + SECTOR > budget or \
                ENTRIES_OFFSET + (len(records) + 1) * ENTRY > DIR_SECTORS * SECTOR:
            continue                              # не помещается: объект выводится ячейками
        if found is None:
            found = (len(streams), len(packed))
            known[digest] = found
            streams += packed
        records.append((palette, code, width, height, *found, has_a, has_b))
        kept_frames += frames
    streams += bytes((-len(streams)) % SECTOR)
    dir_first = len(pack) // SECTOR
    streams_first = dir_first + DIR_SECTORS
    directory = bytearray(DIR_SECTORS * SECTOR)
    heads: dict[int, int] = {}
    chains = [0] * BUCKETS
    longest_sectors = 0
    # Записи — по убыванию частоты; в корзину — с конца, так что в голове цепочки самый частый объект.
    for number in range(len(records) - 1, -1, -1):
        palette, code, width, height, start, length, has_a, has_b = records[number]
        cls = CLASSES[(width, height)]
        offset = ENTRIES_OFFSET + number * ENTRY
        absolute = streams_first * SECTOR + start
        sector, within = absolute // SECTOR, absolute % SECTOR
        assert sector < 0x10000 and within % 4 == 0 and length % 4 == 0 and length // 4 < 0x4000
        longest_sectors = max(longest_sectors, (within + length + SECTOR - 1) // SECTOR)
        bucket = bucket_of(code, palette, cls)
        struct.pack_into('<BBBHHBHB', directory, offset, code & 0xFF, (code >> 8) | (cls << 4), palette,
                         heads.get(bucket, 0), sector, (within // 4) | (0x80 if has_a else 0),
                         (length // 4) | (0x8000 if has_b else 0), 0xFF)
        heads[bucket] = offset
        chains[bucket] += 1
    for bucket, offset in heads.items():
        struct.pack_into('<H', directory, bucket * 2, offset)
    pack += directory
    pack += streams
    sectors = len(pack) // SECTOR
    if sectors >= 0x10000:
        raise SystemExit('пак длиннее 65535 секторов: номер сектора у загрузчика — слово')
    pack[48:52] = MAGIC
    struct.pack_into('<IIIIH', pack, 52, dir_first, DIR_SECTORS, streams_first, len(streams) // SECTOR, len(records))
    struct.pack_into('<I', pack, 44, sectors)
    PACK.write_bytes(pack)
    digest = hashlib.sha256(pack).hexdigest()
    data_report.update({'size': len(pack), 'sectors': sectors, 'sha256': digest,
                        'objects': {'sector': dir_first, 'sectors': DIR_SECTORS + len(streams) // SECTOR,
                                    'count': len(records)}})
    (BUILD / 'rtype_data.json').write_text(json.dumps(data_report, ensure_ascii=False, indent=1) + '\n',
                                           encoding='utf-8')
    used = [value for value in chains if value]
    classes = {f'{w}x{h}': sum(1 for r in records if (r[2], r[3]) == (w, h)) for (w, h) in CLASSES}
    report = {'objects': len(records), 'listed': len(objects), 'streams_shared': len(records) - len(known),
              'budget': budget, 'streams': len(streams),
              'frames_covered': round(kept_frames / max(1, total_frames), 5), 'classes': classes,
              'directory_first_sector': dir_first, 'streams_first_sector': streams_first,
              'longest_sectors': longest_sectors, 'bucket_max_chain': max(used, default=0),
              'bucket_mean_chain': round(sum(used) / max(1, len(used)), 2), 'pack_size': len(pack), 'sha256': digest}
    (BUILD / 'rtype_objects.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (BUILD / 'rtype_objects.inc').write_text('\n'.join([
        '; Сгенерировано vdac2p_objects.py: каталог картинок объектов (спрайты объектами) в хвосте пака.',
        f'OBJ_DIR_SECTOR EQU {dir_first}',
        f'OBJ_DIR_SECTORS EQU {DIR_SECTORS}',
        f'OBJ_COUNT EQU {len(records)}',
        f'OBJ_ENTRIES EQU #{ENTRIES_OFFSET:04X}',
        f'OBJ_ENTRY EQU {ENTRY}',
        f'OBJ_SECTORS_MAX EQU {longest_sectors}',
        '']), encoding='utf-8', newline='\n')
    print(f'объекты: {len(records)} из {len(objects)} (кадров с ними {kept_frames * 100 / max(1, total_frames):.2f} %), '
          f'потоки {len(streams) / 1048576:.2f} МБ (общих {len(records) - len(known)}), бюджет {budget / 1048576:.2f} МБ; '
          f'классы {classes}; корзины до {max(used, default=0)}, в среднем {report["bucket_mean_chain"]}; '
          f'поток до {longest_sectors} секторов; пак {len(pack)} байт')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
