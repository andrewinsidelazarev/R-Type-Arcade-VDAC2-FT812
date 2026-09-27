"""Таблицы и раскладка видеоадаптера FT812 переведённой программы World ROM.

Ячейки HQ (кодировка encode — двухпроходные PALETTED4444, как m72_ft812_compositor.encode_cell:
проход A — перо A с уровнем альфы, проход B — перо B; у спрайтов с 2026-09-25 у непрозрачного пикселя в A — главное
перо смеси, чтобы защита строки без прохода B не делала спрайты полыми) лежат на SD-карте в паке уровней
RTYPELVL.PAC (rtype_data.py) и загружаются адаптером при первом выводе ячейки (загрузчик
rtype_loader.asm). Здесь — страницы TS-Config адаптера и таблицы video.inc.

Тайлы выводятся картинками групп и полосами. Строка группы — 8 столбцов группы × строки карты 2k и 2k+1 (16
тайлов). Класс — непустые тайлы строки группы с одинаковыми палитрой, проходом приоритета и горизонтальным
отражением; класс из IMAGE_MIN тайлов и больше — одна картинка 107×60 (проход A — строки 0…29, проход B — 30…59):
тайл столбца k — с тексела IMAGE_OFFSETS[k] = round(40·k/3) (шаг тайлов 13⅓ тексела), вертикальное отражение —
строки в обратном порядке, горизонтальное — матрицей всей картинки (тайлы класса fx лежат в картинке зеркально:
с тексела 93 − IMAGE_OFFSETS[k]). Остальные тайлы — вертикальные полосы из двух тайлов, как раньше: полоса 14×60,
пара тайлов столбца одного класса — одна полоса. Картинку собирает сопроцессор FT812: ячейка тайла копируется в
ячейку сборки слота (IMAGE_CELLS), затем готовый блок из 30 команд CMD_MEMCPY (image_templates: страница шаблонов
по fx класса, блок по fy тайла и слоту) раскладывает её строки в картинку сборки (IMAGE_STAGE), а готовая
картинка копируется на своё место. Ячейки тайлов 14×30 (проходы A и B подряд, как их пишет CMD_INFLATE); у
полосы вертикальное отражение — копированием строк в обратном порядке, горизонтальное — матрицей при выводе.
Проход B — та же подпрограмма display list при BITMAP_TRANSFORM_F = 30·256.

Отступление на аппаратном пределе FT812 (строка рендера успевает за 1344 такта только при коротком display list:
цена строки растёт с числом исполняемых команд): тайлы картинки стоят с шагом целых текселей внутри картинки, а
не в целых физических пикселях столбцов; в столбце нахлёста соседних тайлов картинки правый тайл заменяет тексел
левого целиком (у эталона — ложится поверх со смешением); картинки слоя-прохода выводятся раньше его полос.

Страницы (выше памяти V30 #80..#BF):
  STATE_PAGE — заголовки потоков полос, копия буфера спрайтов, владельцы и кадры ячеек спрайтов, сырая
    тень и цвета палитр, таблицы сдвигов (TX, TY, X спрайтов), слова спрайтов (окно W1);
  STREAM_PAGE0.. — потоки полос (по 6 на страницу); SHADOW_PAGE0, +1 — тени VRAM слоёв 0 и 1;
  POSITION_PAGE — ссылки позиций (слой, строка полос, столбец) на полосы (до двух);
  TILE_PAGE — таблицы полос и картинок (ключ, цепочка хеша, ссылки, кадр освобождения), корзины хеша,
    владельцы ячеек тайлов;
  IMAGE_PAGE — ссылки строк групп (слой, строка полос, группа) на картинки (до IMAGE_REFS), заголовки потоков
    картинок;
  ISTREAM_PAGE0.. — потоки картинок (по ISTREAMS_PER_PAGE на страницу);
  TEMPLATE_PAGE0, +1 — блоки команд сборки картинок (image_templates) для fx класса 0 и 1;
  SLOTMAP_PAGE0.. — 24 страницы: слово на (набор·16 + палитра, код): 0 — неизвестна,
    EMPTY_CELL — пустая, иначе признаки проходов A (бит 14), B (бит 15) и номер ячейки тайла или
    слот спрайта (биты 0…11; #FFF — признаки известны, ячейка не загружена);
  COLUMN_PAGE — по sx (0…511) маска видимых групп слоя и их VERTEX_TRANSLATE_X (column_table);
  CACHE_PAGE — нулевая рабочая страница кэша подпрограмм слоёв display list (SPG её не пишет, обнуляет загрузчик).

RAM_G: таблицы палитр 0…#3FFF; ячейки тайлов (источники сборки, без handle); картинка и ячейки сборки; полосы —
handle 0; картинки — handle 1; места спрайтов 27×60 — ячейки handle 6, 7, проход B — handle 8, 9 (источник + 810).

Спрайты объектами (VDAC2+, 2026-09-25): многоклеточная запись sprite RAM выводится одной картинкой из пака
(vdac2p_objects.py) — две вершины (проходы A и B) вместо двух на ячейку. Пул общий: 256 мест по SPRITE_CELL_BYTES
делят одиночные ячейки (место — ячейка) и объекты (2×1, 1×2 — два места, 2×2, 1×4 — четыре, 2×4 — восемь; место
кратно размеру). Первый вариант (64 ячейки и 96 мест объектов отдельно) не выдерживал босса этапа 4 и конец этапа 2
(жалоба пользователя «большие спрайты глючат»). У класса объектов свой handle с источником в начале пула: ячейка
handle — проход объекта (строка 27·ширина, высота 30·высота текселей), объект на месте n (в своих размерах) — ячейки
2n (A) и 2n + 1 (B). Ячейка VERTEX2II — 7 бит, поэтому объекты в два места — только в первых 128 местах.

Размеры — по замеру всей игры на эталоне (прогон с неуязвимостью только для замера, кадры через 64): при
IMAGE_MIN = 5 картинок этого и прошлого кадра по всей карте обоих слоёв до 82 (99% — 72), полос до 67 (на смене
сцены модель SPG просила больше 89 — полос 105, ячеек тайлов 96); ячеек спрайтов в этом и прошлом кадре до 226.
Исполняемых команд display list на модели SPG: демо до 793 (полосами было 1963), прогон с неуязвимостью до 903 (было
3382). Картинке не хватило места — её класс выводится полосами. RAM_G занята почти вся. RAM_G делят машина и титул
(p2c_z80_catalog): изображения титула — в верхних TITLE_BYTES пула картинок. В двух кадрах после сброса
видеоадаптера (на экране ещё титул) адаптер берёт только картинки ниже зоны титула (GUARD_IMAGES) — показанный
титул цел до первого кадра игры. Перед выводом титула после игры показанный кадр машины гаснет в чёрное
(HostVideoFade): загрузка титула в картинки кадра игры не видна.
Ячейки неотражённые: отражение спрайтов — матрица BITMAP_TRANSFORM (A = E = −160 и C, F =
размер·256 дают точное зеркало при масштабе 8/5).

Результат в Build/V30Z80: страницы pages/page_XX.bin, video.inc, video_catalog.json.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
sys.path.insert(0, str(ROOT / 'Source' / 'Python'))

import v30z80  # noqa: E402,F401  (до numpy: порядок импорта numba)
import numpy as np  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
PAGE = 0x4000
SETS = ('tiles0', 'tiles1', 'sprites')
STATE_PAGE = 0xC0
STREAM_PAGE0 = 0xC1
STREAM_PAGES = 16
STREAMS_PER_PAGE = 6
STREAM_CAPACITY = 2400          # байт потока
SHADOW_PAGE0 = 0xD1              # тени VRAM слоёв 0 и 1
POSITION_PAGE = 0xD3
TILE_PAGE = 0xD4
SLOTMAP_PAGE0 = 0xD5
SLOTMAP_PAGES = 24               # по две палитры (8 КБ) на страницу
COLUMN_PAGE = SLOTMAP_PAGE0 + SLOTMAP_PAGES  # геометрия столбцов слоя по sx (column_table)
LAST_PAGE = COLUMN_PAGE          # выше #ED не заходить: SPG с блоками #EF…#F6 на реальной Ево висел при запуске (15.09) —
                                 # по карте памяти Wild Commander #E8…#EF — расширения ядра, #F0…#FF — сам Commander,
                                 # а блоки SPG пишутся, пока его загрузчик работает (в Unreal эти страницы свободны)
# Кэш подпрограмм слоёв (хост, CacheReplay): страница без блока SPG — её обнуляет наш загрузчик уже после Wild
# Commander, как нулевую #EE сборки, проверенной на реальной Ево 15.09. Слот подпрограммы (проход·4 + полоса·2 +
# (слой = 0)) — CACHE_SLOT байт: слова display list, затем записи сдвигов.
CACHE_PAGE = COLUMN_PAGE + 1
CACHE_SLOT = 0x800
CACHE_DL_BYTES = 0x600           # слов подпрограммы (замер: до 820 байт) — остальное записи сдвигов
# Страницы картинок — в свободном промежутке #68…#6F между кодом машины (звук, ядра — до #67) и таблицей
# диспетчеризации (#70); пересечение с частью p2c проверяет rtype_spg.py.
IMAGE_PAGE = 0x68                # ссылки строк групп на картинки, заголовки потоков картинок
ISTREAM_PAGE0 = IMAGE_PAGE + 1
ISTREAM_PAGES = 5
ISTREAMS_PER_PAGE = 20
ISTREAM_CAPACITY = 800           # байт потока картинок: 11 строк по IMAGE_REFS картинок (палитра, матрица, вершина)
TEMPLATE_PAGE0 = ISTREAM_PAGE0 + ISTREAM_PAGES
IMAGE_PAGES_END = TEMPLATE_PAGE0 + 2  # первая страница после страниц картинок (#70 — диспетчеризация)
IHEADER_OFFSET = 0x1000          # в IMAGE_PAGE: заголовки потоков картинок (до — ссылки строк групп)
ILOC_OFFSET = 0x1E00             # в IMAGE_PAGE: места потоков картинок (image_page)
# Страница тайлов (tile_page): с TILE_DATA_OFFSET — рабочие записи адаптера (слоты, ключи, буферы строк), с
# CELL_ADDRESSES_OFFSET — таблицы адресов.
TILE_DATA_OFFSET = 0x3700
CELL_ADDRESSES_OFFSET = 0x3B00
IMAGE_ADDRESSES_OFFSET = 0x3C80
STAGE_CELL_ADDRESSES_OFFSET = 0x3D60
TEMPLATE_OFFSETS_OFFSET = 0x3D90
COLUMN_ENTRY = 1 + 8 * 3         # маска видимых групп и VERTEX_TRANSLATE_X восьми групп
ROW_RANGE_OFFSET = 0x3200         # в COLUMN_PAGE: биты строк полос куска по (первая·12 + строк)
TILE_SIZE = (14, 15)
SPRITE_SIZE = (27, 30)
CELL_BASE = 0x004000
CELLS = 96                       # ячейки тайлов 14×30 (только источники сборки полос и картинок)
STRIP_HANDLE = 0
STRIPS = 105                     # полосы 14×60 (замер при IMAGE_MIN = 5 — до 67; запас на смену сцены)
IMAGE_HANDLE = 1
# Проход B полос и картинок (VDAC2+, 2026-09-24): handle-псевдонимы со сдвигом источника на 30 строк (как у спрайтов) —
# вершина прохода B идёт в подпрограмме слоя сразу за вершиной прохода A (слово вершины + #100: handle + 2), и
# подпрограмма слоя исполняется растеризатором один раз, а не дважды (при F = 0 и F = 30·256): её слова состояния
# (палитры, сдвиги, матрица отражения) больше не стоят на каждой строке развёртки вдвое.
STRIP_HANDLE_B = STRIP_HANDLE + 2
IMAGE_HANDLE_B = IMAGE_HANDLE + 2
PASS_B_ROWS = 30                 # строк прохода A в ячейке полосы и картинки (TILE_SIZE[1]·2)
IMAGES = 74                      # картинки групп 107×60 (замер при IMAGE_MIN = 5 — до 82, 99% — 72)
IMAGE_MIN = 5                    # тайлов класса строки группы для картинки
IMAGE_REFS = 4                   # картинок на строку группы: классов от IMAGE_MIN тайлов не больше 16 // IMAGE_MIN
IMAGE_REFS_BYTES = 2 * 32 * 8 * IMAGE_REFS * 2  # ссылки: слой, строка полос, группа — IMAGE_REFS слов
IMAGE_COLUMNS = 8
IMAGE_OFFSETS = [round(40 * column / 3) for column in range(IMAGE_COLUMNS)]  # 0, 13, 27, 40, 53, 67, 80, 93
IMAGE_WIDTH = IMAGE_OFFSETS[-1] + TILE_SIZE[0]
IMAGE_TEMPLATE = 30 * 16         # байт блока шаблона: 30 CMD_MEMCPY строк слота
# Зона титула — верх пула картинок: 7 изображений 107×120 (179 760 байт, область C) и 64 слота глифов 14×15
# (прежние 247 полос по 840 байт); p2c_z80_catalog проверяет, что изображения титула в неё помещаются.
TITLE_BYTES = 247 * 840
SPRITE_HANDLE0 = 6
SPRITE_HANDLE_B = SPRITE_HANDLE0 + 2   # проход B ячейки — псевдоним (слот + 256: handle + 2)
SPRITE_CELLS = 256                     # места пула спрайтов: одиночные ячейки и объекты (общий пул)
# Классы объектов: handle (0 — 2×2, 1 — 2×4, 2 — 2×1, 3 — 1×2, 4 — 1×4) и ширина, высота в ячейках.
OBJ_CLASS_HANDLES = (5, 4, 11, 12, 10)
OBJ_CLASS_SHAPES = ((2, 2), (2, 4), (2, 1), (1, 2), (1, 4))
EMPTY_CELL = 0x3FFF
REGION_STRIPS = (11, 11, 10)     # строки полос областей FT812 (строки карты 0–21, 22–43, 44–63)
# Страница состояния: смещения таблиц сдвигов (адреса в окне W1 — #4000 + смещение).
TX_OFFSET = 0x2000
TY_OFFSET = 0x2400
SPRITE_XS_OFFSET = 0x2800
STREAM_LOC_OFFSET = 0x2B40       # места потоков полос (stream_locations): 96 по 3 байта
DL_HANDLES_OFFSET = 0x2C60       # слова handle первого display list (dl_handles), до SPRITE_WORDS
SPRITE_WORDS_OFFSET = 0x2DA0     # слова спрайтов кадра (хост, SPRITE_WORDS) — до #3FF0
# Таблицы вывода спрайтов в странице хоста (sprite_tables): формы, Y по 256 байт, X по 512 байт, отражения. Код хоста —
# до SPRITE_TABLES; выше SPRITE_TABLES_END (до #FFFF) ничего нет: прерывания Z80 в игре выключены (загрузчик — DI).
SPRITE_TABLES = 0xF400
SPRITE_YT = 0xF600
SPRITE_XT = 0xF900
SPRITE_FLIPS_AT = 0xFF00
HEADER_SIZE = 36                 # начала 11 строк полос и конец (слова) + палитры 12 строк


def encode(cells, name: str, palette: int, code: int, fx: int, fy: int):
    """Байты проходов A и B (или None), признак однородной ячейки пера 0."""
    index_a, index_b = cells[name].cell(palette, code)
    passes = []
    for index in (index_a, index_b):
        if index is None:
            passes.append(None)
            continue
        data = index[::-1] if fy else index
        data = data[:, ::-1] if fx else data
        data = np.where((data & 15) == 0, 0, data).astype(np.uint8)
        passes.append(data if (data & 15).any() else None)
    # Однородная ячейка: одно перо с полной альфой во всех пикселях, без прохода B.
    solid = None
    if passes[1] is None and passes[0] is not None and (passes[0] & 15 == 15).all():
        pens = np.unique(passes[0] >> 4)
        if len(pens) == 1:
            solid = int(pens[0])
    return passes[0], passes[1], solid


def layout() -> dict[str, int]:
    """RAM_G: палитры, ячейки тайлов, картинка и ячейки сборки, полосы, картинки, ячейки спрайтов."""
    tile_cell = TILE_SIZE[0] * TILE_SIZE[1] * 2
    strip = TILE_SIZE[0] * TILE_SIZE[1] * 4
    image = IMAGE_WIDTH * TILE_SIZE[1] * 4
    sprite_cell = SPRITE_SIZE[0] * SPRITE_SIZE[1] * 2
    image_stage = CELL_BASE + CELLS * tile_cell
    image_cells = image_stage + image
    strip_base = image_cells + 2 * IMAGE_COLUMNS * tile_cell
    image_base = strip_base + STRIPS * strip
    sprite_base = image_base + IMAGES * image
    top = sprite_base + SPRITE_CELLS * sprite_cell
    title_base = sprite_base - TITLE_BYTES
    assert top <= 0x100000, f'RAM_G: #{top:06X}'
    assert STRIPS <= 128 and IMAGES <= 128 and IMAGE_REFS >= 16 // IMAGE_MIN and title_base >= image_base
    return {'tile_cell': tile_cell, 'strip': strip, 'image': image, 'sprite_cell': sprite_cell,
            'image_stage': image_stage, 'image_cells': image_cells, 'strip_base': strip_base,
            'image_base': image_base, 'sprite_base': sprite_base, 'top': top,
            'title_base': title_base,
            'title_bytes': TITLE_BYTES, 'guard_images': (title_base - image_base) // image}


def region_of_strip(strip: int) -> int:
    return (strip >= REGION_STRIPS[0]) + (strip >= REGION_STRIPS[0] + REGION_STRIPS[1])


def region_of_column(column: int) -> int:
    return (column >= 24) + (column >= 48)


def table_lines(sizes: dict[str, int]) -> list[str]:
    """Таблицы адаптера (метки в странице хоста): handle FT812, координаты, потоки."""

    def data(label: str, directive: str, values: list[int], per_line: int = 16) -> list[str]:
        result = [f'{label}:']
        for start in range(0, len(values), per_line):
            chunk = values[start:start + per_line]
            result.append(f'                {directive} ' + ', '.join(f'#{value:0{2 if directive == "DB" else 4}X}'
                                                                   for value in chunk))
        return result

    lines = [f'CELL_BASE EQU #{CELL_BASE:06X}', f'CELLS EQU {CELLS}',
             f'STRIP_BASE EQU #{sizes["strip_base"]:06X}', f'STRIPS EQU {STRIPS}',
             f'STRIP_SLOT0 EQU {STRIP_HANDLE * 128}',
             f'STRIP_HANDLE_B EQU {STRIP_HANDLE_B}', f'IMAGE_HANDLE_B EQU {IMAGE_HANDLE_B}',
             f'IMAGE_BASE EQU #{sizes["image_base"]:06X}', f'IMAGES EQU {IMAGES}',
             f'GUARD_IMAGES EQU {sizes["guard_images"]}', f'IMAGE_SLOT0 EQU {IMAGE_HANDLE * 128}',
             f'IMAGE_MIN EQU {IMAGE_MIN}', f'IMAGE_REFS EQU {IMAGE_REFS}', f'IMAGE_BYTES EQU {sizes["image"]}',
             f'IMAGE_WIDTH EQU {IMAGE_WIDTH}', f'IMAGE_STAGE EQU #{sizes["image_stage"]:06X}',
             f'IMAGE_CELLS EQU #{sizes["image_cells"]:06X}', f'IMAGE_TEMPLATE EQU {IMAGE_TEMPLATE}',
             f'VIDEO_IMAGE_PAGE EQU #{IMAGE_PAGE:02X}', f'VIDEO_TEMPLATE_PAGE0 EQU #{TEMPLATE_PAGE0:02X}',
             f'ISTREAM_CAPACITY EQU {ISTREAM_CAPACITY}',
             f'SPRITE_BASE EQU #{sizes["sprite_base"]:06X}',
             f'SPRITE_HANDLE0 EQU {SPRITE_HANDLE0}', f'SPRITE_HANDLE_B EQU {SPRITE_HANDLE_B}',
             f'SPRITE_CELLS EQU {SPRITE_CELLS}',
             *[f'OBJ_HANDLE{cls} EQU {handle}' for cls, handle in enumerate(OBJ_CLASS_HANDLES)],
             f'SPRITE_SLOT0 EQU {SPRITE_HANDLE0 * 128}', f'EMPTY_CELL EQU #{EMPTY_CELL:04X}',
             f'TILE_CELL_BYTES EQU {sizes["tile_cell"]}', f'STRIP_BYTES EQU {sizes["strip"]}',
             f'SPRITE_CELL_BYTES EQU {sizes["sprite_cell"]}',
             f'TILE_CELL_W EQU {TILE_SIZE[0]}', f'TILE_CELL_H EQU {TILE_SIZE[1]}',
             f'SPRITE_CELL_W EQU {SPRITE_SIZE[0]}', f'SPRITE_CELL_H EQU {SPRITE_SIZE[1]}',
             f'TX_TABLE EQU #{0x4000 + TX_OFFSET:04X}', f'TY_TABLE EQU #{0x4000 + TY_OFFSET:04X}',
             f'SPRITE_XS EQU #{0x4000 + SPRITE_XS_OFFSET:04X}',
             f'SPRITE_XS_OFFSET_END EQU #{SPRITE_XS_OFFSET + 400 * 2:04X}',
             f'SPRITE_WORDS EQU #{SPRITE_WORDS_OFFSET:04X}']
    assert SPRITE_CELLS == 256
    # Слова handle и места потоков полос — в странице состояния (state_page): адреса окна W1.
    handles = dl_handles(sizes)
    lines += [f'DL_HANDLES EQU #{0x4000 + DL_HANDLES_OFFSET:04X}',
              f'DL_HANDLES_END EQU #{0x4000 + DL_HANDLES_OFFSET + 4 * len(handles):04X}',
              f'STREAM_LOC EQU #{0x4000 + STREAM_LOC_OFFSET:04X}']
    lines += data('COLOR4', 'DB', [(value * 15 + 15) // 31 for value in range(32)])
    lines += data('REGION_ROWS', 'DB', list(REGION_STRIPS))
    lines += data('REGION_FIRST', 'DB', [0, REGION_STRIPS[0], REGION_STRIPS[0] + REGION_STRIPS[1]])
    lines += data('STRIP_REGION', 'DB', [region_of_strip(strip) for strip in range(32)])
    starts = (0, REGION_STRIPS[0], REGION_STRIPS[0] + REGION_STRIPS[1])
    lines += data('STRIP_INDEX', 'DB', [strip - starts[region_of_strip(strip)] for strip in range(32)])
    # Y вершины полосы в области: 24·(строка карты) − 512·область (строка карты = 2·строка полос).
    ys = [48 * strip - 512 * region_of_strip(strip) for strip in range(32)]
    assert all(0 <= y < 512 for y in ys)
    lines += data('STRIP_Y1', 'DB', [(y & 15) << 4 for y in ys])
    lines += data('STRIP_Y2', 'DB', [y >> 4 for y in ys])
    xs = [(64 * column * 2 + 3) // 6 - 512 * region_of_column(column) for column in range(64)]
    assert all(0 <= x < 512 for x in xs)
    lines += data('COL_X2', 'DB', [(x & 7) << 5 for x in xs])
    lines += data('COL_X3', 'DB', [0x80 | (x >> 3) for x in xs])
    lines += data('GROUP_REGION', 'DB', [region_of_column(group * 8) for group in range(8)])
    # Заголовок потока n: в странице состояния (окно W1) — #4000 + n·HEADER_SIZE, картинок — в странице картинок
    # с IHEADER_OFFSET.
    assert 96 * HEADER_SIZE <= 0x0E00
    lines += [f'STREAM_CAPACITY EQU {STREAM_CAPACITY}']
    # Таблицы в страницах данных (адреса окна W1): места потоков картинок — в странице картинок; адреса RAM_G ячеек
    # тайлов, картинок, ячеек сборки слотов и смещения блоков шаблона — в странице тайлов (tile_page, image_page).
    lines += [f'IHEADER_OFFSET EQU #{IHEADER_OFFSET:04X}', f'ISTREAM_LOC EQU #{0x4000 + ILOC_OFFSET:04X}',
              f'CELL_ADDRESSES EQU #{0x4000 + CELL_ADDRESSES_OFFSET:04X}',
              f'IMAGE_ADDRESSES EQU #{0x4000 + IMAGE_ADDRESSES_OFFSET:04X}',
              f'STAGE_CELL_ADDRESSES EQU #{0x4000 + STAGE_CELL_ADDRESSES_OFFSET:04X}',
              f'TEMPLATE_OFFSETS EQU #{0x4000 + TEMPLATE_OFFSETS_OFFSET:04X}',
              f'TILE_DATA_OFFSET EQU #{TILE_DATA_OFFSET:04X}', f'TILE_TABLES_OFFSET EQU #{CELL_ADDRESSES_OFFSET:04X}']
    return lines


def dl_handles(sizes: dict[str, int]) -> list[int]:
    """Слова handle первого display list после сброса видеоадаптера: полосы (0), картинки (1), их проход B (2, 3 —
    источник + 30 строк), ячейки спрайтов (6, 7) и их проход B (8, 9), классы объектов (4, 5, 10, 11, 12 — источник в
    начале пула спрайтов, ячейка — проход объекта). Параметры: PALETTED4444 (15), вывод NEAREST/BORDER размером
    (w·8 + 4) / 5 × (h·8 + 4) / 5."""
    handles = []

    def handle_words(handle: int, source: int, width: int, height: int, cell_height: int) -> list[int]:
        size_w, size_h = (width * 8 + 4) // 5, (cell_height * 8 + 4) // 5
        return [0x05000000 | handle, 0x01000000 | source, 0x07000000 | (15 << 19) | (width << 9) | height,
                0x28000000, 0x08000000 | (size_w << 9) | size_h, 0x29000000]

    handles += handle_words(STRIP_HANDLE, sizes['strip_base'], TILE_SIZE[0], TILE_SIZE[1] * 4, TILE_SIZE[1] * 2)
    handles += handle_words(IMAGE_HANDLE, sizes['image_base'], IMAGE_WIDTH, TILE_SIZE[1] * 4, TILE_SIZE[1] * 2)
    assert PASS_B_ROWS == TILE_SIZE[1] * 2
    handles += handle_words(STRIP_HANDLE_B, sizes['strip_base'] + PASS_B_ROWS * TILE_SIZE[0], TILE_SIZE[0],
                            TILE_SIZE[1] * 4, TILE_SIZE[1] * 2)
    handles += handle_words(IMAGE_HANDLE_B, sizes['image_base'] + PASS_B_ROWS * IMAGE_WIDTH, IMAGE_WIDTH,
                            TILE_SIZE[1] * 4, TILE_SIZE[1] * 2)
    for index in range(2):
        base = sizes['sprite_base'] + index * 128 * sizes['sprite_cell']
        handles += handle_words(SPRITE_HANDLE0 + index, base, SPRITE_SIZE[0], SPRITE_SIZE[1] * 2, SPRITE_SIZE[1])
    for index in range(2):
        base = sizes['sprite_base'] + index * 128 * sizes['sprite_cell'] + SPRITE_SIZE[0] * SPRITE_SIZE[1]
        handles += handle_words(SPRITE_HANDLE_B + index, base, SPRITE_SIZE[0], SPRITE_SIZE[1] * 2, SPRITE_SIZE[1])
    for handle, (columns, rows) in zip(OBJ_CLASS_HANDLES, OBJ_CLASS_SHAPES):
        width, height = SPRITE_SIZE[0] * columns, SPRITE_SIZE[1] * rows
        assert (width * height * 2) % (2 * sizes['sprite_cell']) == 0        # объект — целые места пула
        handles += handle_words(handle, sizes['sprite_base'], width, height, height)
    # Ячейки VERTEX2II (7 бит): 2×4 (8 мест) — до 2·31 + 1, 2×2 и 1×4 (4 места) — до 2·63 + 1, в два места — места
    # 0…127 (ячейки до 127).
    assert SPRITE_CELLS // 8 * 2 <= 128 and SPRITE_CELLS // 4 * 2 <= 128
    return handles


def stream_locations() -> bytes:
    """Места потоков полос n: страница STREAM_PAGE0 + n // 6, смещение (n % 6)·STREAM_CAPACITY — по 3 байта."""
    assert STREAMS_PER_PAGE * STREAM_PAGES >= 96 and STREAMS_PER_PAGE * STREAM_CAPACITY <= PAGE
    location = []
    for number in range(96):
        offset = (number % STREAMS_PER_PAGE) * STREAM_CAPACITY
        location += [STREAM_PAGE0 + number // STREAMS_PER_PAGE, offset & 0xFF, offset >> 8]
    return bytes(location)


def tile_page(sizes: dict[str, int]) -> bytes:
    """Страница тайлов: таблицы адресов RAM_G (по 3 байта) ячеек тайлов, картинок и ячеек сборки слотов, смещения
    блоков шаблона (fy·16 + слот) — остальное адаптер заполняет сам."""
    page = bytearray(PAGE)
    cells = b''.join((CELL_BASE + cell * sizes['tile_cell']).to_bytes(3, 'little') for cell in range(CELLS))
    images = b''.join((sizes['image_base'] + image * sizes['image']).to_bytes(3, 'little') for image in range(IMAGES))
    stage = b''.join((sizes['image_cells'] + slot * sizes['tile_cell']).to_bytes(3, 'little')
                     for slot in range(2 * IMAGE_COLUMNS))
    offsets = struct.pack(f'<{4 * IMAGE_COLUMNS}H', *[index * IMAGE_TEMPLATE for index in range(4 * IMAGE_COLUMNS)])
    for offset, table in ((CELL_ADDRESSES_OFFSET, cells), (IMAGE_ADDRESSES_OFFSET, images),
                          (STAGE_CELL_ADDRESSES_OFFSET, stage), (TEMPLATE_OFFSETS_OFFSET, offsets)):
        page[offset:offset + len(table)] = table
    assert CELL_ADDRESSES_OFFSET + len(cells) <= IMAGE_ADDRESSES_OFFSET
    assert IMAGE_ADDRESSES_OFFSET + len(images) <= STAGE_CELL_ADDRESSES_OFFSET
    assert STAGE_CELL_ADDRESSES_OFFSET + len(stage) <= TEMPLATE_OFFSETS_OFFSET and TEMPLATE_OFFSETS_OFFSET + len(offsets) <= PAGE
    return bytes(page)


def image_page() -> bytes:
    """Страница картинок: места потоков картинок n (страница ISTREAM_PAGE0 + n // ISTREAMS_PER_PAGE, смещение
    (n % ISTREAMS_PER_PAGE)·ISTREAM_CAPACITY) с ILOC_OFFSET; ссылки и заголовки адаптер заполняет сам."""
    assert IHEADER_OFFSET >= IMAGE_REFS_BYTES and IHEADER_OFFSET + 96 * HEADER_SIZE <= ILOC_OFFSET
    assert ISTREAMS_PER_PAGE * ISTREAM_PAGES >= 96 and ISTREAMS_PER_PAGE * ISTREAM_CAPACITY <= PAGE
    page = bytearray(PAGE)
    location = []
    for number in range(96):
        offset = (number % ISTREAMS_PER_PAGE) * ISTREAM_CAPACITY
        location += [ISTREAM_PAGE0 + number // ISTREAMS_PER_PAGE, offset & 0xFF, offset >> 8]
    page[ILOC_OFFSET:ILOC_OFFSET + len(location)] = bytes(location)
    return bytes(page)


def image_templates(sizes: dict[str, int]) -> list[bytes]:
    """Страницы блоков сборки картинки (для fx класса 0 и 1): блок (fy·16 + слот) — 30 CMD_MEMCPY строк ячейки сборки
    слота в картинку сборки. Слот s — столбец s // 2 (тексел IMAGE_OFFSETS, у fx — IMAGE_WIDTH − 14 − IMAGE_OFFSETS),
    строка карты s % 2 (строки картинки 15·(s % 2) прохода A и 30 + 15·(s % 2) прохода B); fy — строки ячейки в
    обратном порядке."""
    width, rows = TILE_SIZE
    pages = []
    for fx in (0, 1):
        page = bytearray()
        for fy in (0, 1):
            for slot in range(2 * IMAGE_COLUMNS):
                column, row = slot // 2, slot % 2
                x = IMAGE_OFFSETS[column] if not fx else IMAGE_WIDTH - width - IMAGE_OFFSETS[column]
                for pass_number in (0, 1):
                    for line in range(rows):
                        target = 2 * rows * pass_number + rows * row + (rows - 1 - line if fy else line)
                        dest = sizes['image_stage'] + target * IMAGE_WIDTH + x
                        source = sizes['image_cells'] + slot * sizes['tile_cell'] + (rows * pass_number + line) * width
                        page += struct.pack('<IIII', 0xFFFFFF1D, dest, source, width)
        assert len(page) == 4 * IMAGE_COLUMNS * IMAGE_TEMPLATE <= PAGE
        pages.append(bytes(page) + bytes(PAGE - len(page)))
    return pages


def region_bytes(physical: int) -> tuple[int, int]:
    """Область FT812 по 512 пикселей (−1, 0, 1) и координата в ней — как у VERTEX2II с VERTEX_TRANSLATE."""
    region = -1 if physical < 0 else (0 if physical < 512 else 1)
    value = physical - 512 * region
    assert 0 <= value < 512
    return region & 0xFF, value


def sprite_tables() -> list[str]:
    """Таблицы вывода спрайтов в конце страницы хоста (с SPRITE_TABLES): по байту индекса — без вычислений в
    цикле ячеек. Адреса таблиц по 256 и 512 байт кратны 256: индекс — младший байт (и бит 8) адреса."""

    def rows(values: list[int]) -> list[str]:
        return [f'                DB ' + ', '.join(f'#{value:02X}' for value in values[start:start + 16])
                for start in range(0, len(values), 16)]

    lines = ['; Сгенерировано v30z80_video_assets.py: таблицы вывода спрайтов (страница хоста).',
             f'SPRITE_TABLES EQU #{SPRITE_TABLES:04X}', f'                ORG #{SPRITE_TABLES:04X}']
    # Форма по старшему байту атрибута >> 2 (биты 7, 6 — log2 столбцов, 5, 4 — log2 строк, 3 — fx, 2 — fy):
    # столбцов, строк, смещение кода первого столбца и шаг, первой строки и шаг, отражение (режим матрицы:
    # бит 0 — fx, бит 2 — fy), 16·строк. Код ячейки = код + 8·(fx ? w − 1 − cx : cx) + (fy ? h − 1 − cy : cy).
    shapes = []
    for index in range(64):
        columns, height = 1 << (index >> 4), 1 << ((index >> 2) & 3)
        fx, fy = (index >> 1) & 1, index & 1
        shapes += [columns, height, 8 * (columns - 1) if fx else 0, 0xF8 if fx else 8,
                   height - 1 if fy else 0, 0xFF if fy else 1, fx | (fy << 2), 16 * height]
    lines += ['SPRITE_SHAPES:'] + rows(shapes) + ['SPRITE_SHAPES_END:']
    # Y ячейки: по i = y + 16 (0…255) физический y = 3·i − 48. VDAC2+ (2026-09-24): два перекрывающихся окна
    # VERTEX_TRANSLATE_Y вместо областей по 512 пикселей — верхнее (сдвиг −48 px, вершина 3·i, годится при 3·i ≤ 511) и
    # нижнее (сдвиг 208 px, вершина 3·i − 256, при 3·i ≥ 256): ячейка в перекрытии годится обоим, и сдвиг меняется,
    # только когда ячейка в текущее окно не входит (на тяжёлых кадрах этапа 2 — 5–8 сдвигов вместо 35–46). Таблицы:
    # окна ячейки (бит 0 — верхнее, бит 1 — нижнее), байт 1 вершины (y & 15) << 4 | 3 (старший полубайт слота ячеек
    # спрайтов SPRITE_SLOT0 = #300 … #3FF; у обоих окон одинаков — сдвиги отличаются на 256), y >> 4 верхнего окна
    # (у нижнего на 16 меньше).
    windows = [(1 if 3 * index <= 511 else 0) | (2 if 3 * index >= 256 else 0) for index in range(256)]
    assert all(windows)
    assert SPRITE_HANDLE0 * 128 >> 8 == 3 and (SPRITE_HANDLE0 * 128 + SPRITE_CELLS - 1) >> 8 == 3
    lines += [f'                ORG #{SPRITE_YT:04X}', 'SPRITE_YT_RY:'] + rows(windows)
    lines += ['SPRITE_YT_LOW:'] + rows([((3 * index & 15) << 4) | 3 for index in range(256)])
    lines += ['SPRITE_YT_HIGH:'] + rows([3 * index >> 4 for index in range(256)])
    # X ячейки: по x + 16 (0…399; до 511 — нули) физический x = round(8·x/3); область, байт 2 вершины
    # (x & 7) << 5, байт 3 — #80 | x >> 3.
    xs = [region_bytes((16 * (index - 16) + 3) // 6) if index < 400 else (0, 0) for index in range(512)]
    lines += [f'                ORG #{SPRITE_XT:04X}', 'SPRITE_XT_RX:'] + rows([region for region, _ in xs])
    lines += ['SPRITE_XT_B2:'] + rows([(value & 7) << 5 for _, value in xs])
    lines += ['SPRITE_XT_B3:'] + rows([0x80 | (value >> 3) for _, value in xs]) + ['SPRITE_XT_END:']
    # Отражение записи 1×1 по битам 3, 2 старшего байта атрибута (индекс — атрибут >> 2 & 3) — режим матрицы
    # SpriteTransform: бит 0 — fx, бит 2 — fy. Прежде таблица стояла перед формами, и 516 байт форм заходили на 4 байта
    # в таблицу Y (у формы 8×8 с обоими отражениями последние 4 байта были затёрты).
    lines += [f'                ORG #{SPRITE_FLIPS_AT:04X}', 'SPRITE_FLIPS:']
    lines += rows([(index >> 1) | ((index & 1) << 2) for index in range(4)])
    lines += ['SPRITE_TABLES_END:',
              '                ASSERT SPRITE_SHAPES_END <= SPRITE_YT_RY && SPRITE_YT_HIGH+256 <= SPRITE_XT_RX',
              '                ASSERT SPRITE_YT_LOW == SPRITE_YT_RY+256 && SPRITE_YT_HIGH == SPRITE_YT_RY+512',
              '                ASSERT SPRITE_XT_B2 == SPRITE_XT_RX+512 && SPRITE_XT_B3 == SPRITE_XT_RX+1024',
              '                ASSERT SPRITE_XT_END <= SPRITE_FLIPS',
              '                ASSERT low SPRITE_FLIPS == 0 && low SPRITE_YT_RY == 0 && low SPRITE_XT_RX == 0',
              '                ASSERT SPRITE_TABLES_END <= #10000']
    assert 64 * 8 + SPRITE_TABLES <= SPRITE_YT and SPRITE_YT + 768 <= SPRITE_XT and SPRITE_XT + 1536 <= SPRITE_FLIPS_AT
    return lines


def object_tables(sizes: dict[str, int]) -> list[str]:
    """Таблицы вывода объектов на второй странице хоста (vdac2p_objects.asm), по 512 байт подряд с границы 256:
    X — по X − 256 (X — слово 3 записи & #3FF, у видимой записи 273…703; nx = X − 320): область FT812, байт 2 вершины
    (x & 7) << 5, байт 3 — #80 | x >> 3 при физическом x = round(8·nx/3), как у ячеек;
    Y — по i + 64 (i = y + 16 первой строки записи, −63…255): окна (бит 0 — верхнее, вершина 3i; бит 1 — нижнее, 3i −
    256; бит 2 — окно выше поля, 3i + 256: сдвиг −304 пикселя), байт 1 вершины (3i & 15) << 4 и (3i + 256) >> 4 (у
    верхнего окна на 16 меньше, у нижнего — на 32);
    места пула объект получает от SpriteCellAddress хоста (как ячейка)."""

    def rows(values: list[int]) -> list[str]:
        return [f'                DB ' + ', '.join(f'#{value:02X}' for value in values[start:start + 16])
                for start in range(0, len(values), 16)]

    xs = [region_bytes((16 * (index - 64) + 3) // 6) if index < 448 else (0, 0) for index in range(512)]
    ys = []
    for index in range(512):
        i = index - 64
        if i > 255:
            ys.append((0, 0, 0))
            continue
        windows = ((1 if 0 <= 3 * i <= 511 else 0) | (2 if 256 <= 3 * i <= 767 else 0) |
                   (4 if -256 <= 3 * i <= 255 else 0))
        ys.append((windows, ((3 * i) & 15) << 4, (3 * i + 256) >> 4))
    assert all(ys[index][0] for index in range(1, 320)) and all(0 <= y[2] < 64 for y in ys)
    lines = ['; Сгенерировано v30z80_video_assets.py: таблицы вывода объектов (вторая страница хоста).',
             '                ALIGN 256']
    lines += ['OBJ_XT_RX:'] + rows([region for region, _ in xs])
    lines += ['OBJ_XT_B2:'] + rows([(value & 7) << 5 for _, value in xs])
    lines += ['OBJ_XT_B3:'] + rows([0x80 | (value >> 3) for _, value in xs])
    lines += ['OBJ_YT_W:'] + rows([y[0] for y in ys])
    lines += ['OBJ_YT_L:'] + rows([y[1] for y in ys])
    lines += ['OBJ_YT_H4:'] + rows([y[2] for y in ys])
    lines += ['                ASSERT low OBJ_XT_RX == 0 && OBJ_XT_B2 == OBJ_XT_RX+512 && OBJ_XT_B3 == OBJ_XT_RX+1024',
              '                ASSERT OBJ_YT_W == OBJ_XT_RX+1536 && OBJ_YT_L == OBJ_YT_W+512 && OBJ_YT_H4 == OBJ_YT_W+1024']
    return lines


def column_table() -> bytes:
    """Геометрия столбцов слоя для каждого sx (0…511), как у прежнего ColumnsSetup хоста: base_x = (−64 − sx) & 511,
    первый столбец c0, число видимых столбцов, у группы g — первый видимый столбец и VERTEX_TRANSLATE_X =
    TX[sx] + 8192·область + 21845·перенос (24 бита). Запись: маска видимых групп, затем по 3 байта на группу
    (у невидимой — нули; вывод их не читает)."""
    tx_table = [(-(((64 + sx) * 256 + 3) // 6)) & 0xFFFF for sx in range(512)]
    regions = [region_of_column(group * 8) for group in range(8)]
    table = bytearray()
    for sx in range(512):
        base_x = (-(sx + 64)) & 0x1FF

        def column_x(column: int) -> int:
            value = (8 * column + base_x + 8) & 0x1FF
            return (value - 8) & 0xFFFF

        first = (((-base_x) & 0xFFFF) & 0x1FF) >> 3 & 63
        count = ((((383 - column_x(first)) & 0xFFFF) >> 3) + 1) & 0xFF
        count = count if count < 50 else 49
        mask = 0
        translates = bytearray(24)
        for group in range(8):
            visible = next((column for column in range(8 * group, 8 * group + 8)
                            if ((column - first) & 63) < count), None)
            if visible is None:
                continue
            mask |= 1 << group
            carry_rows = (((column_x(visible) - ((8 * visible - 64 - sx) & 0xFFFF)) & 0xFFFF) >> 9) & 3
            high = regions[group] * 32 + (tx_table[sx] >> 8)
            value = ((0xFF + (high >> 8)) & 0xFF) << 16 | (high & 0xFF) << 8 | (tx_table[sx] & 0xFF)
            value = (value + 21845 * carry_rows) & 0xFFFFFF
            translates[group * 3:group * 3 + 3] = value.to_bytes(3, 'little')
        table += bytes([mask]) + translates
    assert len(table) == 512 * COLUMN_ENTRY <= ROW_RANGE_OFFSET
    table += bytes(ROW_RANGE_OFFSET - len(table))
    # Биты видимых строк полос куска (как цикл VisibilityUpdate): первая строка s (0…31), строк n (0…11) → 4 байта
    # (байт (строка >> 3) & 3, бит строка & 7).
    for first in range(32):
        for rows in range(12):
            bits = bytearray(4)
            for row in range(first, first + rows):
                bits[(row >> 3) & 3] |= 1 << (row & 7)
            table += bits
    assert len(table) <= PAGE
    return bytes(table) + bytes(PAGE - len(table))


def state_page(sizes: dict[str, int]) -> bytes:
    """Страница состояния с таблицами сдвигов, местами потоков полос и словами handle (остальное адаптер обнуляет
    при инициализации)."""
    page = bytearray(PAGE)
    # Сдвиг скролла в 1/16 пикселя: X — −round((64 + sx)·128/3), Y — −((128 + sy) & 511)·48. Y — по модулю высоты
    # карты (512): строки окна до её склейки кладутся без поправки, после склейки — +24576 (PIECE_WRAP, PiecesSetup).
    # До 2026-09-25 здесь было −(128 + sy)·48: при sy ≥ 384 все строки окна уходили на 512 строк M72 вверх, за экран.
    # Передний слой такого sy в игре не получает, фон выводит кольцо своей формулой, но фоновые тайлы высокого прохода
    # (группа 2 — корпус линкора этапа 3 при sy фона 506) — ячейками, и корпус не закрывал двигатель.
    struct.pack_into('<512H', page, TX_OFFSET, *[(-(((64 + sx) * 256 + 3) // 6)) & 0xFFFF for sx in range(512)])
    struct.pack_into('<512H', page, TY_OFFSET, *[(-(((128 + sy) & 511) * 48)) & 0xFFFF for sy in range(512)])
    # Спрайт: физический x = round(8·nx/3) для nx = −16…383.
    struct.pack_into('<400H', page, SPRITE_XS_OFFSET, *[((16 * nx + 3) // 6) & 0xFFFF for nx in range(-16, 384)])
    locations = stream_locations()
    handles = dl_handles(sizes)
    assert SPRITE_XS_OFFSET + 800 <= STREAM_LOC_OFFSET and STREAM_LOC_OFFSET + len(locations) <= DL_HANDLES_OFFSET
    assert DL_HANDLES_OFFSET + 4 * len(handles) + 6 <= SPRITE_WORDS_OFFSET   # за словами handle — блок GUARD_ARGS
    page[STREAM_LOC_OFFSET:STREAM_LOC_OFFSET + len(locations)] = locations
    struct.pack_into(f'<{len(handles)}I', page, DL_HANDLES_OFFSET, *handles)
    return bytes(page)


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    sizes = layout()
    templates = image_templates(sizes)
    pages = ([STATE_PAGE] + [STREAM_PAGE0 + n for n in range(STREAM_PAGES)] + [SHADOW_PAGE0, SHADOW_PAGE0 + 1] +
             [POSITION_PAGE, TILE_PAGE] + [SLOTMAP_PAGE0 + n for n in range(SLOTMAP_PAGES)] + [COLUMN_PAGE] +
             [IMAGE_PAGE] + [ISTREAM_PAGE0 + n for n in range(ISTREAM_PAGES)] +
             [TEMPLATE_PAGE0 + n for n in range(len(templates))] + [CACHE_PAGE])
    # Страница с данными (блок SPG) — не выше LAST_PAGE; выше — только нулевая страница кэша.
    assert len(set(pages)) == len(pages) and max(set(pages) - {CACHE_PAGE}) <= LAST_PAGE and IMAGE_PAGES_END <= 0x70
    assert CACHE_PAGE <= 0xEE and 8 * CACHE_SLOT == PAGE and CACHE_DL_BYTES % 256 == 0
    assert TEMPLATE_PAGE0 + len(templates) == IMAGE_PAGES_END
    pages_dir = BUILD / 'pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        data = state_page(sizes) if page == STATE_PAGE else (column_table() if page == COLUMN_PAGE else bytes(PAGE))
        if TEMPLATE_PAGE0 <= page < TEMPLATE_PAGE0 + len(templates):
            data = templates[page - TEMPLATE_PAGE0]
        elif page == TILE_PAGE:
            data = tile_page(sizes)
        elif page == IMAGE_PAGE:
            data = image_page()
        (pages_dir / f'page_{page:02x}.bin').write_bytes(data)
    lines = [
        '; Сгенерировано v30z80_video_assets.py: страницы и константы видеоадаптера FT812.',
        f'VIDEO_STATE_PAGE EQU #{STATE_PAGE:02X}',
        f'VIDEO_STREAM_PAGE0 EQU #{STREAM_PAGE0:02X}',
        f'VIDEO_SHADOW_PAGE0 EQU #{SHADOW_PAGE0:02X}',
        f'VIDEO_POSITION_PAGE EQU #{POSITION_PAGE:02X}',
        f'VIDEO_TILE_PAGE EQU #{TILE_PAGE:02X}',
        f'VIDEO_SLOTMAP_PAGE0 EQU #{SLOTMAP_PAGE0:02X}',
        f'VIDEO_SLOTMAP_PAGES EQU {SLOTMAP_PAGES}',
        f'VIDEO_COLUMN_PAGE EQU #{COLUMN_PAGE:02X}',
        f'VIDEO_CACHE_PAGE EQU #{CACHE_PAGE:02X}',
        f'CACHE_SLOT EQU #{CACHE_SLOT:04X}',
        f'CACHE_DL_BYTES EQU #{CACHE_DL_BYTES:04X}',
        f'COLUMN_ENTRY EQU {COLUMN_ENTRY}',
        f'ROW_RANGE_OFFSET EQU #{ROW_RANGE_OFFSET:04X}',
    ]
    lines += table_lines(sizes)
    (BUILD / 'video.inc').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    (BUILD / 'video_tables.inc').write_text('\n'.join(sprite_tables()) + '\n', encoding='utf-8', newline='\n')
    (BUILD / 'video_objects.inc').write_text('\n'.join(object_tables(sizes)) + '\n', encoding='utf-8', newline='\n')
    summary = {'pages': pages, 'ram_g': sizes}
    (BUILD / 'video_catalog.json').write_text(json.dumps(summary, indent=1) + '\n', encoding='utf-8')
    print(f'видеоадаптер: страниц {len(pages)}, RAM_G до #{sizes["top"]:06X}, таблицы video.inc, '
          f'{time.perf_counter() - started:.1f} с')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
