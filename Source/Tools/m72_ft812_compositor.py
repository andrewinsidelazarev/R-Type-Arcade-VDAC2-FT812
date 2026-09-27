"""Модель вывода кадра M72 на FT812 двухпроходными палитровыми HQ-ячейками.

Источник графики — готовые HQ-атласы проекта (xBRZ 1.9 ×6 → Lanczos, логический масштаб
640×480) и карты смешения перьев RTYPE_HQ_RECOLOR_MAPS: каждый пиксель HQ-ячейки — смесь
перьев A и B с весом w (0…15) и альфой a (0…15), цвета перьев — живая палитра кадра, как
в M72HqRenderer.

FT812 не умеет смешивать два пера по индексу, поэтому ячейка выводится двумя битмапами
формата PALETTED4444 с одной таблицей палитры на (банк, палитра): запись таблицы
`перо·16 + уровень` = цвет пера с альфой «уровень». Проход A — перо A с уровнем a, проход
B — перо B с уровнем round(a·w/15). Для непрозрачных пикселей результат равен смеси
M72HqRenderer; на полупрозрачных краях — отступление аппаратного предела (двойное
смешение). Перо 0 переднего слоя всегда прозрачно (маски M72): вклад пера 0 в смесь
края там переносится в альфу второго пера, как у эталона.

Порядок вывода полосы растра: фон (слой 1) низкий проход, передний слой (слой 0) низкий
проход, спрайты (в обратном порядке sprite RAM), фон высокий проход, передний высокий —
приоритет тайлов над спрайтами выражается порядком (у непрозрачных пикселей — как маска
blocked эталона).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HQ_DIR = ROOT / 'Assets' / 'Converted' / 'Arcade' / 'FullHQ'
WIDTH, HEIGHT = 640, 480
PLAYFIELD_HEIGHT = 450
FG_LAYER0 = (0xFFFF, 0x00FF, 0x0001, 0x0001)
FG_LAYER1 = (0x0001, 0xFF01, 0xFFFF, 0xFFFF)
BG_LAYER0 = (0xFFFF, 0x00FF, 0xFFFF, 0x0001)
# Высокий проход фона у вывода порта (2026-09-25): перья, закрывающие спрайты, — BG_PRIORITY MAME (у группы 2
# тайл рисуется в заднем проходе, но перья 1…15 закрывают спрайты; хост: PASS_TABLE фона группы 2 = 1), перо 0 —
# прозрачно (у порта — маска пера 0 ячеек фона в паке, rtype_data.py; здесь — таблицей); под тайлом — задний проход.
BG_PRIORITY = (0xFFFF, 0x00FF, 0x0001, 0x0001)
BG_LAYER1 = (0x0000, 0xFF00, 0x0000, 0xFFFE)


def round_ratio(value: int, numerator: int, denominator: int) -> int:
    scaled = value * numerator
    if scaled >= 0:
        return (scaled + denominator // 2) // denominator
    return -((-scaled + denominator // 2) // denominator)


@dataclass
class CellSet:
    """Индексные ячейки банка: (палитра, код) → (индексы прохода A, прохода B или None)."""
    height: int
    width: int
    atlases: np.ndarray            # (16, 4096, h, w) ARGB4444 опорных атласов
    map_a: np.ndarray
    map_b: np.ndarray
    map_w: np.ndarray
    pen0_masked: bool
    cache: dict
    source: np.ndarray             # (4096, h, w) перья исходных ячеек ROM (index4)
    colours: np.ndarray | None = None   # (16 палитр, 16 перьев, 3) RGB444 опорной палитры атласа
    pen0_transparent: bool = True       # перо 0 набора прозрачно (спрайты, передний слой)
    dominant_a: bool = False            # у непрозрачного пикселя главное перо — в проходе A (спрайты, с 2026-09-25)

    def cell(self, palette: int, code: int) -> tuple[np.ndarray, np.ndarray | None]:
        key = (palette, code)
        found = self.cache.get(key)
        if found is None:
            found = encode_cell(self.atlases[palette, code], self.map_a[palette], self.map_b[palette],
                                self.map_w[palette], self.pen0_masked, self.source[code],
                                None if self.colours is None else self.colours[palette], self.pen0_transparent,
                                self.dominant_a)
            self.cache[key] = found
        return found


def source_pens(source: np.ndarray, height: int, width: int) -> np.ndarray:
    """Перья исходной ячейки ROM, растянутые на решётку HQ-ячейки (ближайший пиксель)."""
    rows = np.minimum(np.arange(height) * source.shape[0] // height, source.shape[0] - 1)
    columns = np.minimum(np.arange(width) * source.shape[1] // width, source.shape[1] - 1)
    return source[rows[:, None], columns[None, :]].astype(np.int32)


def constrained_pens(cell: np.ndarray, source: np.ndarray, colours: np.ndarray,
                     pen0_transparent: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Перья A, B и вес смешения каждого пикселя HQ-ячейки — только из перьев ROM рядом с ним.

    Атлас хранит цвета одной опорной палитры (m72_full_hq_assets.richest_palettes), а на экране у той же
    палитры M72 цвета другие. Общая карта «цвет → пара перьев» по одному цвету перья различить не может:
    у перьев с одинаковым опорным цветом декодер брал любое. Замер 2026-09-22 по всем спрайтам: даже
    внутри однородных областей одного пера 17,9 % пикселей получали чужое перо (палитра 2 — 16,5 %,
    13 — 62 %, 15 — 100 %); у врага #412 палитры 2 перо F, на экране светло-серое, в опорной палитре
    чёрное, как прозрачное перо 0, — и выходило чёрными точками.

    Перо пикселя от палитры не зависит, поэтому берём его у ROM: кандидаты — перья окрестности 3×3
    исходного пикселя, по цвету опорной палитры подбирается только смешение «перо под пикселем → перо
    соседа» с весом 0…15 (как у карт build_mix_map). При равном цвете выигрывает перо под пикселем и
    меньший вес — одинаковые по цвету перья больше не путаются. Форму и полутона даёт тот же
    xBRZ ×6 → Lanczos: меняется только то, какие перья эти полутона смешивают.

    Зовётся только для пикселей, где пара перьев общей карты неправдоподобна (encode_cell): там, где
    карта права, она точнее этого подбора — у него смешение обязано включать перо под пикселем.
    """
    height, width = cell.shape
    rows = np.minimum(np.arange(height) * source.shape[0] // height, source.shape[0] - 1)
    cols = np.minimum(np.arange(width) * source.shape[1] // width, source.shape[1] - 1)
    padded = np.pad(source.astype(np.int32), 1, constant_values=0)      # за краем ячейки — прозрачно
    offsets = [(0, 0)] + [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
    neigh = np.stack([padded[1 + dy:1 + dy + source.shape[0], 1 + dx:1 + dx + source.shape[1]]
                      for dy, dx in offsets], axis=-1)[rows[:, None], cols[None, :]]  # (h, w, 9), [0] — центр
    target = np.stack([(cell >> 8) & 15, (cell >> 4) & 15, cell & 15], axis=-1).astype(np.int32)
    colours = colours.astype(np.int32)
    centre = neigh[..., 0]
    huge = 1 << 30
    if pen0_transparent:
        # Под пикселем прозрачное перо, а xBRZ дорастил туда тело: основой берём ближайшее по цвету
        # непрозрачное перо окрестности.
        opaque_neigh = np.where(neigh > 0, neigh, -1)
        distance = np.where(opaque_neigh >= 0,
                            ((colours[np.maximum(opaque_neigh, 0)] - target[..., None, :]) ** 2).sum(-1), huge)
        nearest = np.take_along_axis(opaque_neigh, distance.argmin(-1)[..., None], -1)[..., 0]
        centre = np.where((centre == 0) & (nearest > 0), nearest, centre)
    weights = np.arange(16, dtype=np.int32)
    base = colours[centre][:, :, None, None, :]                            # (h, w, 1, 1, 3)
    other = colours[neigh][:, :, :, None, :]                               # (h, w, 9, 1, 3)
    mix = (base * (15 - weights)[None, None, None, :, None] + other * weights[None, None, None, :, None] + 7) // 15
    cost = ((mix - target[:, :, None, None, :]) ** 2).sum(-1)              # (h, w, 9, 16)
    if pen0_transparent:
        cost = np.where((neigh == 0)[..., None] & (weights > 0), huge, cost)   # прозрачное перо не смешиваем
    best = cost.reshape(height, width, -1).argmin(-1)                       # первым — центр с весом 0
    partner = np.take_along_axis(neigh, (best // 16)[..., None], -1)[..., 0]
    weight = best % 16
    partner = np.where(weight == 0, centre, partner)
    return centre, partner, weight


def encode_cell(cell: np.ndarray, map_a: np.ndarray, map_b: np.ndarray, map_w: np.ndarray,
                pen0_masked: bool, source: np.ndarray | None = None, colours: np.ndarray | None = None,
                pen0_transparent: bool = True, dominant_a: bool = False) -> tuple[np.ndarray, np.ndarray | None]:
    """ARGB4444 HQ-ячейка → индексы PALETTED4444 проходов A и B (B = None, если смешения нет).

    dominant_a (спрайты): у непрозрачного пикселя главное перо — в проходе A, см. конец функции."""
    alpha = ((cell >> 12) & 15).astype(np.int32)
    rgb = cell & 0x0FFF
    pen_a = map_a[rgb].astype(np.int32)
    pen_b = map_b[rgb].astype(np.int32)
    weight = map_w[rgb].astype(np.int32)
    if source is not None and colours is not None:
        # Общая карта точна, пока опорная палитра атласа совпадает с живой (этап 1 — по нему её и
        # снимали): там она подбирает лучшую пару перьев, и переделывать её нельзя — первая версия
        # правки, подбиравшая заново каждый пиксель, на краях зверей этапа 1 дала крапины (кадр 1300
        # модели против эталона, 2026-09-22). Поэтому подбор заново — только там, где пара перьев
        # неправдоподобна: перья нет в окрестности 3×3 исходного пикселя ROM, либо прозрачное перо 0
        # рисуется цветом (у спрайтов перо 0 не маскируется, и такой пиксель выходил чёрной точкой).
        height, width = cell.shape
        rows = np.minimum(np.arange(height) * source.shape[0] // height, source.shape[0] - 1)
        cols = np.minimum(np.arange(width) * source.shape[1] // width, source.shape[1] - 1)
        padded = np.pad(source.astype(np.int32), 1, constant_values=0)
        neigh = np.stack([padded[1 + dy:1 + dy + source.shape[0], 1 + dx:1 + dx + source.shape[1]]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=-1)[rows[:, None], cols[None, :]]
        uses_a = weight < 15
        uses_b = weight > 0
        plausible_a = ~uses_a | (neigh == pen_a[..., None]).any(-1)
        plausible_b = ~uses_b | (neigh == pen_b[..., None]).any(-1)
        if pen0_transparent and not pen0_masked:
            plausible_a &= ~uses_a | (pen_a != 0)
            plausible_b &= ~uses_b | (pen_b != 0)
        refit = (alpha > 0) & ~(plausible_a & plausible_b)
        if refit.any():
            fit_a, fit_b, fit_w = constrained_pens(cell, source, colours, pen0_transparent)
            pen_a = np.where(refit, fit_a, pen_a)
            pen_b = np.where(refit, fit_b, pen_b)
            weight = np.where(refit, fit_w, weight)
    weight_a = 15 - weight
    weight_b = weight.copy()
    if pen0_masked:
        weight_a = np.where(pen_a == 0, 0, weight_a)
        weight_b = np.where(pen_b == 0, 0, weight_b)
    # Эталон: при маске пера альфа = a·(сумма весов)/15, цвет — оставшееся перо.
    total = weight_a + weight_b
    level_a = np.where(weight_b == 0, (alpha * total + 7) // 15, alpha)
    level_a = np.where(weight_a == 0, 0, level_a)
    level_b = np.where(weight_a == 0, (alpha * total + 7) // 15, (alpha * weight_b + 7) // 15)
    level_b = np.where(weight_b == 0, 0, level_b)
    index_a = (pen_a * 16 + level_a).astype(np.uint8)
    index_b = (pen_b * 16 + level_b).astype(np.uint8)
    # Подбор пары перьев идёт по цвету, а цвета берутся из снятого состояния палитр. Если в той палитре
    # перо ячейки было чёрным, ближайшим оказывается перо 0 — прозрачное, и непрозрачный пиксель пропадал
    # совсем (замер 2026-09-20: у буквы «E» палитры 1 так терялось 57 пикселей тела из 129, надпись
    # «ENJOY THE BONUS GAME AGAIN ?» выходила рваной, тогда как аркада печатает её сплошной). Перо пикселя
    # от палитры не зависит: берём его у исходной ячейки ROM и выводим таким пиксель в проходе B.
    if source is not None:
        lost = (alpha > 0) & (level_a == 0) & (level_b == 0)
        if lost.any():
            pens = source_pens(source, cell.shape[0], cell.shape[1])
            restore = lost & (pens > 0)
            if restore.any():
                index_b = np.where(restore, (pens * 16 + alpha).astype(np.uint8), index_b)
                level_b = np.where(restore, alpha, level_b)
    if dominant_a:
        # Спрайты (2026-09-25): у непрозрачного пикселя главное перо (вес 8…15) — в проходе A с полной альфой,
        # второе — в проходе B с уровнем своего веса. Смесь та же: у непрозрачного пикселя проход A — перо с уровнем
        # 15, проход B — перо с уровнем своего веса, веса в сумме 15 (перо 0 у спрайтов не маскируется), и «B поверх
        # A с альфой w_B/15» = «A поверх B с альфой w_A/15». Зато один проход A — пиксель главным пером, а не пустое
        # место: защита строки FT812 (vdac2p_guard.asm) выбрасывает вершины B, а при прежней раскладке у 52,7 %
        # непрозрачных пикселей спрайтов главное перо было в B, у 38,2 % — всё тело (замер по 3000 ячейкам) —
        # спрайты выходили полыми (жалоба пользователя «большие спрайты глючат»: босс этапа 4, этап 2).
        # Полупрозрачные края — как были (у них две смеси не равны: двойное смешение).
        assert not pen0_masked
        swap = (alpha == 15) & (level_b >= 8)
        if swap.any():
            pen_first = (index_a >> 4).astype(np.int32)
            pen_second = (index_b >> 4).astype(np.int32)
            level_second = np.where(level_a == 0, 0, 15 - level_b)        # у пикселя только в B второго пера нет
            index_a = np.where(swap, pen_second * 16 + 15, index_a).astype(np.uint8)
            index_b = np.where(swap, pen_first * 16 + level_second, index_b).astype(np.uint8)
            level_b = np.where(swap, level_second, level_b)
    return index_a, (index_b if level_b.any() else None)


def load_index4(name: str, size: int) -> np.ndarray:
    """Перья исходных ячеек ROM: файл index4 — по два пера в байте, старшее первым."""
    raw = np.fromfile(ROOT / 'Assets' / 'Converted' / 'Arcade' / f'RTYPE_{name}_INDEX4.bin', dtype=np.uint8)
    pens = np.empty(raw.size * 2, dtype=np.uint8)
    pens[0::2] = raw >> 4
    pens[1::2] = raw & 15
    return pens.reshape(-1, size, size)


def load_cells() -> dict[str, CellSet]:
    maps = np.load(HQ_DIR / 'RTYPE_HQ_RECOLOR_MAPS.npz')
    # Цвета перьев опорных палитр атласа (RGB444): по ним декодер подбирает вес смешения перьев ROM.
    pens = np.load(HQ_DIR / 'RTYPE_HQ_PEN_COLOURS.npz')

    def atlas(name: str, height: int, width: int) -> np.ndarray:
        result = np.empty((16, 4096, height, width), dtype=np.uint16)
        for palette in range(16):
            words = np.fromfile(HQ_DIR / f'RTYPE_{name}_PAL{palette:02X}_HQ_ARGB4444.bin', dtype='<u2')
            result[palette] = words.reshape(4096, height, width)
        return result
    return {
        'tiles0': CellSet(15, 14, atlas('TILES0', 15, 14), maps['tile_a'], maps['tile_b'], maps['tile_w'], True, {},
                          load_index4('TILES0', 8), pens['tile'], True),
        'tiles1': CellSet(15, 14, atlas('TILES1', 15, 14), maps['tile_a'], maps['tile_b'], maps['tile_w'], False, {},
                          load_index4('TILES1', 8), pens['tile'], False),
        'sprites': CellSet(30, 27, atlas('SPRITES', 30, 27), maps['sprite_a'], maps['sprite_b'], maps['sprite_w'],
                           False, {}, load_index4('SPRITES', 16), pens['sprite'], True, True),
    }


def palette_tables(palette_ram: bytes) -> np.ndarray:
    """Таблицы PALETTED4444 банка: (16 палитр, 256 записей, 4 канала A R G B по 8 бит)."""
    words = np.frombuffer(palette_ram, dtype='<u2').astype(np.int32)
    tables = np.zeros((16, 256, 4), dtype=np.int32)
    for palette in range(16):
        for pen in range(16):
            index = palette * 16 + pen
            red = ((words[index] & 31) * 15 + 15) // 31
            green = ((words[index + 0x200] & 31) * 15 + 15) // 31
            blue = ((words[index + 0x400] & 31) * 15 + 15) // 31
            for level in range(16):
                tables[palette, pen * 16 + level] = (level * 17, red * 17, green * 17, blue * 17)
    return tables


class Ft812Compositor:
    """Кадр 640×480 RGB (8 бит) так, как его соберёт FT812 из двухпроходных ячеек."""

    def __init__(self) -> None:
        self.cells = load_cells()
        self.frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.int32)
        self.commands = 0

    def blit(self, indices: np.ndarray, table: np.ndarray, left: int, top: int, flip_x: bool, flip_y: bool,
             clip_top: int, clip_bottom: int) -> None:
        self.commands += 1
        height, width = indices.shape
        source = indices[::-1] if flip_y else indices
        source = source[:, ::-1] if flip_x else source
        y0, y1 = max(top, clip_top, 0), min(top + height, clip_bottom, HEIGHT)
        x0, x1 = max(left, 0), min(left + width, WIDTH)
        if y0 >= y1 or x0 >= x1:
            return
        patch = table[source[y0 - top:y1 - top, x0 - left:x1 - left]]
        alpha = patch[..., 0:1]
        region = self.frame[y0:y1, x0:x1]
        # FT812: dst = (src·α + dst·(255 − α)) / 255.
        region[:] = (patch[..., 1:] * alpha + region * (255 - alpha) + 127) // 255

    def draw_layer(self, name: str, vram: bytes, tables: np.ndarray, masks, scroll_x: int, scroll_y: int,
                   clip_top: int, clip_bottom: int) -> None:
        cells = self.cells[name]
        words = np.frombuffer(vram, dtype='<u2')
        for row in range(64):
            native_y = ((row * 8 - 128 - scroll_y + 8) & 511) - 8
            if native_y >= 256 or native_y + 8 <= 0:
                continue
            top = round_ratio(native_y, 15, 8)
            if top >= clip_bottom or top + 15 <= clip_top:
                continue
            for column in range(64):
                native_x = ((column * 8 - 64 - scroll_x + 8) & 511) - 8
                if native_x >= 384 or native_x + 8 <= 0:
                    continue
                index = row * 64 + column
                word = int(words[index * 2])
                attribute = int(words[index * 2 + 1])
                mask = masks[(attribute >> 6) & 3]
                if mask == 0xFFFF:
                    continue
                code = word & 0x3FFF
                palette = attribute & 15
                index_a, index_b = cells.cell(palette, code & 0x0FFF)
                if not index_a.any() and index_b is None:
                    continue
                left = round_ratio(native_x, 5, 3)
                # Маски отдельных перьев (кроме пера 0 переднего слоя) — отступление: ячейка
                # выводится целиком в проходе, где выводится большинство её перьев.
                if bin(mask & 0xFFFE).count('1') > 7:
                    continue
                table = tables[palette]
                self.blit(index_a, table, left, top, bool(word & 0x4000), bool(word & 0x8000), clip_top, clip_bottom)
                if index_b is not None:
                    self.blit(index_b, table, left, top, bool(word & 0x4000), bool(word & 0x8000), clip_top,
                              clip_bottom)

    def draw_sprites(self, spriteram: bytes, tables: np.ndarray) -> None:
        words = np.frombuffer(spriteram, dtype='<u2')
        offsets = []
        offset = 0
        while offset < len(words):
            offsets.append(offset)
            offset += (1 << ((int(words[offset + 2]) >> 14) & 3)) * 4
        cells = self.cells['sprites']
        for offset in reversed(offsets):
            code = int(words[offset + 1])
            attribute = int(words[offset + 2])
            palette = attribute & 15
            width = 1 << ((attribute >> 14) & 3)
            height = 1 << ((attribute >> 12) & 3)
            flip_x = bool(attribute & 0x0800)
            flip_y = bool(attribute & 0x0400)
            native_x = -256 + (int(words[offset + 3]) & 0x3FF) - 64
            native_y = 384 - (int(words[offset]) & 0x1FF) - 16 * height
            for cell_x in range(width):
                for cell_y in range(height):
                    cell_code = code + 8 * (width - 1 - cell_x if flip_x else cell_x)
                    cell_code += height - 1 - cell_y if flip_y else cell_y
                    cell_code &= 0x0FFF
                    left = round_ratio(native_x + cell_x * 16, 5, 3)
                    top = round_ratio(native_y + cell_y * 16, 15, 8)
                    index_a, index_b = cells.cell(palette, cell_code)
                    if not index_a.any() and index_b is None:
                        continue
                    table = tables[palette]
                    self.blit(index_a, table, left, top, flip_x, flip_y, 0, PLAYFIELD_HEIGHT)
                    if index_b is not None:
                        self.blit(index_b, table, left, top, flip_x, flip_y, 0, PLAYFIELD_HEIGHT)

    def render(self, state) -> np.ndarray:
        self.frame[:] = 0
        self.commands = 0
        if state.video_off:
            return self.frame.astype(np.uint8)
        sprite_tables = palette_tables(state.palette0)
        tile_tables = palette_tables(state.palette1)
        rows = state.row_scroll
        bands = []
        first = 0
        while first < 256:
            last = first + 1
            while last < 256 and rows[last] == rows[first]:
                last += 1
            bands.append((round_ratio(first, 15, 8), round_ratio(last, 15, 8), rows[first]))
            first = last
        for clip_top, clip_bottom, (fg_x, fg_y, bg_x, bg_y) in bands:
            self.draw_layer('tiles1', state.vram1, tile_tables, BG_LAYER1, bg_x, bg_y, clip_top, clip_bottom)
            self.draw_layer('tiles0', state.vram0, tile_tables, FG_LAYER1, fg_x, fg_y, clip_top, clip_bottom)
        self.draw_sprites(state.spriteram, sprite_tables)
        high_tables = tile_tables.copy()
        high_tables[:, 0:16, 0] = 0                 # перо 0 фона в высоком проходе — прозрачно
        for clip_top, clip_bottom, (fg_x, fg_y, bg_x, bg_y) in bands:
            self.draw_layer('tiles1', state.vram1, high_tables, BG_PRIORITY, bg_x, bg_y, clip_top, clip_bottom)
            self.draw_layer('tiles0', state.vram0, tile_tables, FG_LAYER0, fg_x, fg_y, clip_top, clip_bottom)
        return self.frame.astype(np.uint8)
