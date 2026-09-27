#!/usr/bin/env python3
"""Атлас примитивов M72: тайлы 8×8 и спрайтовые ячейки 16×16 из ROM.

Порт рисует не готовые кадры, а примитивы — иначе не будет ни анимации, ни
мигающего текста, ни счётчика кредитов. Слой спрайтов сначала собирается в
нативных 384×256 целиком, затем офлайн увеличивается в 640×480 максимально
качественным алгоритмом (xBRZ 1.9 ×6, затем Lanczos) и лишь после этого снова
разрезается на ячейки атласа. Так xBRZ видит экранных соседей и не создаёт
полос на стыках объектов. FT812 выполняет только финальный аппаратный 8/5
NEAREST в 1024×768.

Арифметика сетки. По вертикали 480 / 32 тайла = 15 пикселей ровно. По
горизонтали 640 / 48 = 13.333 — нецелое, поэтому тайл разворачивается в 14
пикселей и ставится с шагом 40/3. VERTEX_FORMAT 3 даёт разрешение 1/8 пикселя,
позиция считается абсолютно (round(tx × 106.67)), так что ошибка не
накапливается и не превышает 1/16 пикселя, а лишний столбец перекрывается
соседом, который рисуется поверх: видимая ширина остаётся ровно 13.333.

Спрайтовая ячейка 16×16 по той же причине разворачивается в 27×30.

xBRZ смотрит на соседние пиксели, а у отдельного элемента атласа соседей нет.
Чтобы края не разъезжались, элемент перед масштабированием расширяется
повторением краевого пикселя, а после — обрезается обратно.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import xbrz_offline

ROOT = Path(__file__).resolve().parents[2]

# Логический экран и сетка.
LOG_W, LOG_H = 640, 480
NATIVE_W, NATIVE_H = 384, 256
TILE_COLS, TILE_ROWS = 48, 32
PHYS_W, PHYS_H = 1024, 768
# Шаг тайла в 1/8 пикселя: 640 / 48 × 8 = 106.667.
TILE_STEP_EIGHTHS = PHYS_W * 8 / TILE_COLS   # 170.667
# Все примитивы пекутся в ЛОГИЧЕСКОМ пространстве 640×480. FT812 выполняет
# только последний NEAREST 8/5 до 1024×768 — тот же путь обязан использоваться
# у титула и у игры. Лишний столбец перекрывает дробный шаг соседней ячейки.
TILE_W, TILE_H = 14, 15            # 8 × 640/384, 8 × 480/256
SPRITE_W, SPRITE_H = 27, 30        # 16 × 640/384, 16 × 480/256
BORDER = 2                         # запас для xBRZ, снимается после Lanczos
SPRITE_LOOKUP_INC = ROOT / "Source" / "ASM" / "generated_m72_sprites_atlas.inc"
TILE_LOOKUP_INC = ROOT / "Source" / "ASM" / "generated_m72_atlas.inc"
BEAM_METER_CAPTURE = (
    ROOT / "Build" / "Arcade" / "MAME" / "beam_meter_exact_trace")
BEAM_METER_TILE_CODES = (
    0x06AD, 0x06AE, 0x06B0, 0x06B2, 0x06B4, 0x06B6,
    0x06B8, 0x06BA, 0x06BB, 0x06BC, 0x06BD, 0x06BE, 0x06BF,
)


def upscale_cell(pixels: bytes, src_w: int, src_h: int,
                 palette: list[tuple[int, int, int, int]], palette_base: int,
                 target: tuple[int, int]) -> Image.Image:
    """Индексы пенов -> цветной элемент атласа нужного размера.

    Пен 0 у M72 прозрачен. Прозрачность обязана пережить масштабирование, иначе
    вокруг спрайтов появится кайма, поэтому изображение остаётся RGBA, а xBRZ
    вызывается в alpha-aware режиме.
    """
    image = Image.new("RGBA", (src_w, src_h))
    put = image.load()
    for y in range(src_h):
        for x in range(src_w):
            pen = pixels[y * src_w + x]
            if pen == 0:
                put[x, y] = (0, 0, 0, 0)
                continue
            red, green, blue, _ = palette[palette_base + pen]
            put[x, y] = (red, green, blue, 255)

    # Бордюр повторением края: у отдельного элемента нет соседей, а xBRZ на них
    # опирается — без запаса края «съедаются».
    padded = Image.new("RGBA", (src_w + BORDER * 2, src_h + BORDER * 2))
    padded.paste(image, (BORDER, BORDER))
    for i in range(BORDER):
        padded.paste(image.crop((0, 0, 1, src_h)).resize((1, src_h)), (i, BORDER))
        padded.paste(image.crop((src_w - 1, 0, src_w, src_h)), (src_w + BORDER + i, BORDER))
    for i in range(BORDER):
        strip = padded.crop((0, BORDER, padded.width, BORDER + 1))
        padded.paste(strip, (0, i))
        strip = padded.crop((0, BORDER + src_h - 1, padded.width, BORDER + src_h))
        padded.paste(strip, (0, BORDER + src_h + i))

    scale_x = target[0] / src_w
    scale_y = target[1] / src_h
    big = xbrz_offline.xbrz_expand(padded, 6)
    wanted = (round(padded.width * scale_x), round(padded.height * scale_y))
    big = big.resize(wanted, Image.Resampling.LANCZOS)
    left = round(BORDER * scale_x)
    top = round(BORDER * scale_y)
    return big.crop((left, top, left + target[0], top + target[1]))


def pack_argb4444(image: Image.Image) -> bytes:
    """ARGB4444 little-endian — формат объектов порта на FT812."""
    rgba = image.convert("RGBA")
    out = bytearray(rgba.width * rgba.height * 2)
    for index, (red, green, blue, alpha) in enumerate(rgba.getdata()):
        value = (((alpha + 8) // 17) << 12 | ((red + 8) // 17) << 8
                 | ((green + 8) // 17) << 4 | ((blue + 8) // 17))
        out[index * 2] = value & 0xFF
        out[index * 2 + 1] = value >> 8
    return bytes(out)


# Разбор тайловой памяти — по m72_v.cpp (см. tile_pixel в m72_scene.py):
# карта 64×64 тайла, НА ТАЙЛ ДВА СЛОВА (код и атрибут), видимая область начинается
# с X=64, а по Y смещена на +128. Палитра тайлов начинается с индекса 256.
TILEMAP_SIZE = 512
RAW_VISIBLE_X = 64
TILE_SCROLL_DY = -128
TILE_PALETTE_BASE = 256
FG_BACK_MASK = (0x0001, 0xFF01, 0xFFFF, 0xFFFF)
FG_FRONT_MASK = (0xFFFF, 0x00FF, 0x0001, 0x0001)


def collect_tiles(vram: bytes, scroll_x: int, scroll_y: int,
                  cols: int, rows: int) -> tuple[list[list[int]], dict]:
    """Карта экрана и список уникальных (код, палитра, отражения)."""
    unique: dict[tuple[int, int, int, int, int], int] = {}
    cells = []
    for ty in range(rows):
        row = []
        source_y = (ty * 8 - TILE_SCROLL_DY + scroll_y) & (TILEMAP_SIZE - 1)
        for tx in range(cols):
            source_x = (tx * 8 + RAW_VISIBLE_X + scroll_x) & (TILEMAP_SIZE - 1)
            index = (source_y >> 3) * 64 + (source_x >> 3)
            code = struct.unpack_from("<H", vram, index * 4)[0]
            attribute = struct.unpack_from("<H", vram, index * 4 + 2)[0]
            key = (code & 0x3FFF, attribute & 0x0F,
                   (code >> 14) & 1, (code >> 15) & 1,
                   (attribute >> 6) & 3)
            if key not in unique:
                unique[key] = len(unique)
            row.append(unique[key])
        cells.append(row)
    return cells, unique


def write_tile_lookup(entries: list[dict]) -> None:
    """Записать воспроизводимое соответствие M72 tile -> слот атласа."""
    by_key = {
        (int(entry["code"]), int(entry["palette"]),
         int(entry["flip_x"]), int(entry["flip_y"]),
         int(entry["group"])): int(entry["back_slot"])
        for entry in entries
    }
    lines = [
        "; ═══ СГЕНЕРИРОВАНО — не редактировать вручную ═══",
        "; Соответствие (код, палитра, отражения) -> слот HQ-атласа.",
        "M72_GLYPH_SKIP      EQU #FF",
        f"M72_GLYPH_COUNT     EQU {len(entries)}",
    ]
    for digit in range(10):
        lines.append(
            f"M72_DIGIT_{digit}_GLYPH   EQU {by_key[(48 + digit, 6, 0, 0, 0)]}"
        )
    for code in BEAM_METER_TILE_CODES:
        lines.append(
            f"M72_BEAM_{code:04X}_GLYPH EQU {by_key[(code, 0x0F, 0, 0, 2)]}"
        )
    lines.extend(["", "M72GlyphLookup:"])
    for entry in entries:
        lines.append(
            f"                DEFW {entry['code']} : "
            f"DEFB {entry['palette']}, {entry['group']}, "
            f"{entry['back_slot'] if entry['back_opaque'] else 0xFF}, "
            f"{entry['front_slot'] if entry['front_opaque'] else 0xFF}"
        )
    lines.append("")
    TILE_LOOKUP_INC.write_text("\n".join(lines), encoding="utf-8")


def collect_sprites(spriteram: bytes, m72_scene,
                    cell_count: int) -> tuple[list[dict], dict, dict]:
    """Объекты spriteram -> список ячеек 16×16 и уникальные (код, палитра, флипы).

    Объект M72 составной: ширина и высота в ячейках берутся степенями двойки из
    атрибута. Разложение на ячейки обязательно — атлас хранит именно ячейки, а
    список отображения собирает из них объект любого размера.
    """
    unique: dict[int, int] = {}
    positions: dict[tuple[int, int, int, int], tuple[int, int]] = {}
    objects = []
    for sprite in m72_scene.sprite_objects(spriteram):
        if not sprite.code and not sprite.attr:
            continue                                  # пустая запись
        cells = []
        for cell_x in range(sprite.width):
            for cell_y in range(sprite.height):
                # Адресация ячеек как в железе: шаг по горизонтали — восемь
                # кодов, по вертикали — один; отражение меняет порядок.
                code = sprite.code
                code += 8 * (sprite.width - 1 - cell_x if sprite.flip_x else cell_x)
                code += (sprite.height - 1 - cell_y if sprite.flip_y else cell_y)
                code %= cell_count
                key = (code, sprite.color, int(sprite.flip_x), int(sprite.flip_y))
                if key not in unique:
                    unique[key] = len(unique)
                    positions[key] = (sprite.visible_x + cell_x * 16,
                                      sprite.sy + cell_y * 16)
                cells.append({"cell": unique[key], "cx": cell_x, "cy": cell_y})
        objects.append({
            "x": sprite.visible_x, "y": sprite.sy,
            "width": sprite.width, "height": sprite.height,
            "cells": cells,
        })
    return objects, unique, positions


def sprite_layer_rgba(spriteram: bytes, m72_scene, region: bytes,
                      cell_count: int,
                      palette: list[tuple[int, int, int, int]]) -> Image.Image:
    """Собрать прозрачный слой спрайтов M72 в нативных 384×256.

    Масштабировать каждую ячейку отдельно нельзя: xBRZ видит за границей код,
    соседний в ROM, но он не обязательно соседний на экране. Именно так в
    титуле появлялись вертикальные полосы между объектами логотипа.
    """
    layer = Image.new("RGBA", (NATIVE_W, NATIVE_H))
    for sprite in m72_scene.sprite_objects(spriteram):
        if not sprite.code and not sprite.attr:
            continue
        width, height = sprite.width * 16, sprite.height * 16
        pens = sprite_object_pixels(
            sprite.code, sprite.flip_x, sprite.flip_y,
            sprite.width, sprite.height, region, cell_count)
        image = Image.new("RGBA", (width, height))
        out = image.load()
        palette_base = sprite.color * 16
        for y in range(height):
            for x in range(width):
                pen = pens[y * width + x]
                if pen:
                    red, green, blue, _ = palette[palette_base + pen]
                    out[x, y] = (red, green, blue, 255)
        layer.alpha_composite(image, (sprite.visible_x, sprite.sy))
    return layer


def write_sprite_lookup(entries: list[dict], logo_first: int,
                        logo_last: int) -> None:
    """Сгенерировать code -> slot и размеры логической ячейки."""
    lines = [
        "; ═══ СГЕНЕРИРОВАНО — не редактировать вручную ═══",
        "; Спрайтовые ячейки титульного экрана: код ячейки -> номер в атласе.",
        "; Размеры заданы в 640×480; FT812 масштабирует их NEAREST 8/5.",
        "",
        f"M72_SPRITE_W        EQU {SPRITE_W}",
        f"M72_SPRITE_H        EQU {SPRITE_H}",
        f"M72_SPRITE_BYTES    EQU {SPRITE_W * SPRITE_H * 2}",
        f"M72_SPRITE_COUNT    EQU {len(entries)}",
        f"M72_TITLE_LOGO_FIRST_OBJ EQU {logo_first}",
        f"M72_TITLE_LOGO_LAST_OBJ  EQU {logo_last}",
        "",
        "M72SpriteLookup:",
    ]
    for entry in entries:
        lines.append(
            f"                DEFW {entry['code']}    : "
            f"DEFB {entry['palette']}, {entry['index']}")
    lines.append("")
    SPRITE_LOOKUP_INC.write_text("\n".join(lines), encoding="utf-8")


def cell_with_context(code: int, region: bytes, cell_count: int,
                      border: int) -> tuple[bytes, int, int]:
    """Ячейка 16×16 плюс бордюр из НАСТОЯЩИХ соседей по спрайтовой сетке.

    xBRZ опирается на окружение пикселя. Если масштабировать ячейку отдельно,
    на стыках внутри крупного объекта (буквы логотипа, корпус корабля) появятся
    швы. Соседи берутся по той же адресации, что использует железо: шаг по
    горизонтали — восемь кодов, по вертикали — один. Бордюр после
    масштабирования срезается, поэтому атлас остаётся поячеечным, как в
    оригинале.
    """
    size = 16 + border * 2
    out = bytearray(size * size)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            neighbour = (code + dx * 8 + dy) % cell_count
            pixels = m72.decode_sprite(region, neighbour)
            for y in range(16):
                ty = y + dy * 16 + border
                if not 0 <= ty < size:
                    continue
                for x in range(16):
                    tx = x + dx * 16 + border
                    if 0 <= tx < size:
                        out[ty * size + tx] = pixels[y * 16 + x]
    return bytes(out), size, size


def sprite_object_pixels(code: int, flip_x: int, flip_y: int,
                         width: int, height: int,
                         region: bytes, cell_count: int) -> bytes:
    """Собрать пены составного объекта в один буфер width*16 × height*16.

    Порядок ячеек по m72_v.cpp: шаг по столбцу — ВОСЕМЬ кодов, а не высота
    объекта, и при отражении порядок зеркалится вместе с самими пикселями.
    """
    pixel_w, pixel_h = width * 16, height * 16
    out = bytearray(pixel_w * pixel_h)
    for cell_x in range(width):
        for cell_y in range(height):
            cell_code = code
            cell_code += 8 * (width - 1 - cell_x if flip_x else cell_x)
            cell_code += (height - 1 - cell_y if flip_y else cell_y)
            cell_code %= cell_count
            pixels = m72.decode_sprite(region, cell_code)
            for local_y in range(16):
                source_y = 15 - local_y if flip_y else local_y
                for local_x in range(16):
                    source_x = 15 - local_x if flip_x else local_x
                    pen = pixels[source_y * 16 + source_x]
                    if pen:
                        out[(cell_y * 16 + local_y) * pixel_w
                            + cell_x * 16 + local_x] = pen
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path,
                        default=ROOT / "Build" / "Arcade" / "MAME" / "title_menu_trace",
                        help="каталог снимка MAME (нужны vram/palette)")
    parser.add_argument("--frame", type=int, default=630)
    parser.add_argument("--initial-frame", type=int, default=330,
                        help="исходное состояние меню до первого шага потока")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "Assets" / "Converted" / "Arcade" / "Atlas")
    parser.add_argument("--scroll-x", type=lambda s: int(s, 0), default=0)
    parser.add_argument("--scroll-y", type=lambda s: int(s, 0), default=0)
    parser.add_argument("--png-out", type=Path, default=ROOT / "Assets" / "Original",
                        help="куда складывать апскейленные PNG оригиналов")
    parser.add_argument("--group", default="Title",
                        help="подгруппа внутри Assets/Original")
    parser.add_argument("--limit", type=int, default=0,
                        help="ограничить число элементов (для быстрой проверки)")
    args = parser.parse_args()

    m72.require_verified()
    regions = m72.assemble_regions()

    prefix = args.capture / f"frame_{args.frame:06d}"
    palette0 = (prefix.parent / f"frame_{args.frame:06d}_palette0.bin").read_bytes()
    palette1 = (prefix.parent / f"frame_{args.frame:06d}_palette1.bin").read_bytes()
    sys.path.insert(0, str(TOOLS))
    import m72_scene
    palette = m72_scene.palette_from_ram(palette0, palette1)

    # Python's 65 exact Beam-meter states use palette $0F.  Bake their tile
    # primitives into the same HQ atlas, but stop if the gameplay capture and
    # title palette ever diverge instead of silently recolouring the meter.
    beam_palette = m72_scene.palette_from_ram(
        (BEAM_METER_CAPTURE / "frame_001248_palette0.bin").read_bytes(),
        (BEAM_METER_CAPTURE / "frame_001248_palette1.bin").read_bytes(),
    )
    beam_palette_first = TILE_PALETTE_BASE + 0x0F * 16
    if (palette[beam_palette_first:beam_palette_first + 16] !=
            beam_palette[beam_palette_first:beam_palette_first + 16]):
        raise ValueError("palette $0F Beam meter отличается от HQ tile atlas")

    vram0 = (prefix.parent / f"frame_{args.frame:06d}_vram0.bin").read_bytes()
    # Титул не скроллится — проверено перебором: fg_x=0 даёт 100.000 %.
    cells, unique = collect_tiles(vram0, args.scroll_x, args.scroll_y,
                                  TILE_COLS, TILE_ROWS)
    # HUD использует тот же оригинальный шрифт M72. Не все цифры встречаются
    # на одном титульном кадре, поэтому полный диапазон 0..9 включается явно.
    for code in range(48, 58):
        key = (code, 6, 0, 0, 0)
        if key not in unique:
            unique[key] = len(unique)
    # `_draw_beam_meter` chooses exact tilemap states.  Only thirteen distinct
    # ROM cells are needed, so FT812 composes all 65 states from HQ primitives
    # instead of storing 250 КБ almost-identical full strips.
    for code in BEAM_METER_TILE_CODES:
        key = (code, 0x0F, 0, 0, 2)
        if key not in unique:
            unique[key] = len(unique)
    print(f"карта экрана: {TILE_COLS}×{TILE_ROWS} тайлов, "
          f"уникальных элементов: {len(unique)}")

    region = regions["tiles0"] if "tiles0" in regions else regions[
        next(k for k in regions if "tile" in k.lower())]

    order = sorted(unique.items(), key=lambda kv: kv[1])
    if args.limit:
        order = order[:args.limit]
    blob = bytearray()
    tile_entries = []
    png_tiles = args.png_out / args.group / "Tiles"
    png_tiles.mkdir(parents=True, exist_ok=True)
    for (code, pal, flip_x, flip_y, group), index in order:
        pixels = m72.decode_tile(region, code)
        if flip_x or flip_y:
            image = Image.frombytes("L", (8, 8), pixels)
            if flip_x:
                image = image.transpose(Image.FLIP_LEFT_RIGHT)
            if flip_y:
                image = image.transpose(Image.FLIP_TOP_BOTTOM)
            pixels = image.tobytes()
        variants = []
        for pass_name, mask in (("back", FG_BACK_MASK[group]),
                                ("front", FG_FRONT_MASK[group])):
            filtered = bytes(pen if not (mask & (1 << pen)) else 0
                             for pen in pixels)
            cell = upscale_cell(filtered, 8, 8, palette,
                                TILE_PALETTE_BASE + pal * 16, (TILE_W, TILE_H))
            cell.save(png_tiles / f"tile_{index:03d}_{code:04X}_p{pal}_g{group}_{pass_name}"
                                  f"{'_fx' if flip_x else ''}{'_fy' if flip_y else ''}.png")
            variants.append(cell)
            blob += pack_argb4444(cell)
        back, front = variants
        tile_entries.append({
            "code": code, "palette": pal, "flip_x": flip_x,
            "flip_y": flip_y, "group": group,
            "back_slot": index * 2, "front_slot": index * 2 + 1,
            "back_opaque": back.getchannel("A").getbbox() is not None,
            "front_opaque": front.getchannel("A").getbbox() is not None,
        })

    args.out.mkdir(parents=True, exist_ok=True)
    blob_path = args.out / "TILE_ATLAS_ARGB4444.bin"
    blob_path.write_bytes(bytes(blob))
    write_tile_lookup(tile_entries)

    # Спрайты: логотип титульного экрана, корабль, враги — всё из ячеек 16×16.
    spriteram = (prefix.parent / f"frame_{args.frame:06d}_spriteram.bin").read_bytes()
    cell_count = len(regions["sprites"]) // 128
    all_sprite_objects = m72_scene.sprite_objects(spriteram)
    logo_ordinals = [
        ordinal for ordinal, sprite in enumerate(all_sprite_objects, 1)
        if (sprite.code or sprite.attr)
        and sprite.visible_x < NATIVE_W
        and sprite.visible_x + sprite.pixel_width > 0
        and sprite.sy < NATIVE_H
        and sprite.sy + sprite.pixel_height > 0
    ]
    if not logo_ordinals:
        raise RuntimeError("в TITLE_SPRITERAM не найдены видимые объекты логотипа")

    objects, sprite_unique, sprite_positions = collect_sprites(
        spriteram, m72_scene, cell_count)
    sprite_order = sorted(sprite_unique.items(), key=lambda kv: kv[1])
    # Единый высококачественный офлайн-апскейл нативного слоя до логических
    # 640×480. Нарезка после апскейла сохраняет правильное окружение xBRZ и
    # непрерывность штрихов между разными sprite RAM objects.
    native_sprite_layer = sprite_layer_rgba(
        spriteram, m72_scene, regions["sprites"], cell_count, palette)
    logical_sprite_layer = xbrz_offline.xbrz_expand(native_sprite_layer, 6)
    logical_sprite_layer = logical_sprite_layer.resize(
        (LOG_W, LOG_H), Image.Resampling.LANCZOS)
    logical_sprite_layer.save(args.png_out / args.group /
                              "title_sprites_logical_640x480.png")
    sprite_blob = bytearray()
    sprite_entries = []
    png_sprites = args.png_out / args.group / "Sprites"
    png_sprites.mkdir(parents=True, exist_ok=True)
    for (code, pal, flip_x, flip_y), index in sprite_order:
        source_x, source_y = sprite_positions[(code, pal, flip_x, flip_y)]
        left = round(source_x * LOG_W / NATIVE_W)
        top = round(source_y * LOG_H / NATIVE_H)
        cell = logical_sprite_layer.crop(
            (left, top, left + SPRITE_W, top + SPRITE_H))
        cell.save(png_sprites / f"cell_{index:03d}_{code:04X}_p{pal}"
                                f"{'_fx' if flip_x else ''}{'_fy' if flip_y else ''}.png")
        sprite_entries.append({
            "index": index, "code": code, "palette": pal,
            "flip_x": flip_x, "flip_y": flip_y,
            "offset": len(sprite_blob),
        })
        sprite_blob += pack_argb4444(cell)
    sprite_path = args.out / "SPRITE_ATLAS_ARGB4444.bin"
    sprite_path.write_bytes(bytes(sprite_blob))
    initial_prefix = args.capture / f"frame_{args.initial_frame:06d}"
    (args.out / "TITLE_VRAM0.bin").write_bytes(
        initial_prefix.with_name(initial_prefix.name + "_vram0.bin").read_bytes())
    (args.out / "TITLE_SPRITERAM.bin").write_bytes(
        initial_prefix.with_name(initial_prefix.name + "_spriteram.bin").read_bytes())
    write_sprite_lookup(sprite_entries, min(logo_ordinals), max(logo_ordinals))
    print(f"спрайты: {len(objects)} объектов на экране, "
          f"{len(sprite_order)} уникальных, {len(sprite_blob)} Б "
          f"({len(sprite_blob)/1024:.1f} КБ)")
    manifest = {
        "tile_size": [TILE_W, TILE_H],
        "tile_step_eighths": TILE_STEP_EIGHTHS,
        "grid": [TILE_COLS, TILE_ROWS],
        "unique": len(order),
        "blob_bytes": len(blob),
        "sha256": hashlib.sha256(bytes(blob)).hexdigest(),
        "map": cells,
        "sprite_size": [SPRITE_W, SPRITE_H],
        "sprite_scale": [PHYS_W / NATIVE_W, PHYS_H / NATIVE_H],
        "sprite_entries": sprite_entries,
        "sprite_blob_bytes": len(sprite_blob),
        "sprites": objects,
    }
    (args.out / "tile_atlas.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"атлас: {len(order)} элементов {TILE_W}×{TILE_H}, "
          f"{len(blob)} Б ({len(blob)/1024:.1f} КБ)")
    print(f"шаг тайла: {TILE_STEP_EIGHTHS:.3f}/8 px = {TILE_STEP_EIGHTHS/8:.4f} px")
    print(f"blob: {blob_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
