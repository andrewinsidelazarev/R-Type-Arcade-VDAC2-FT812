#!/usr/bin/env python3
"""Два динамических tilemap-прохода Stage 1 для FT812.

Исходник — ROM M72 и timing-paired state frame 898 / palette frame 900.
Каждый полный слой 512x256 сначала собирается в нативном пространстве, затем
целиком проходит xBRZ6 + Lanczos. Только после этого он режется на логические
14x15-ячейки, поэтому соседство тайлов участвует в качественном апскейле.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import m72_scene as scene
import m72_tile_atlas as atlas
import xbrz_offline

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "timing_probe"
OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Tiles"
INC = ROOT / "Source" / "ASM" / "generated_m72_stage.inc"
FRAME = 900
STATE_FRAME = 898
MAP_COLS = 64
MAP_ROWS = 32
MAP_Y_TILE = 16
LOGICAL_MAP_W = 853
LOGICAL_MAP_H = 480
GLYPH_W = 14
GLYPH_H = 15
GLYPH_BYTES = GLYPH_W * GLYPH_H * 2


def build_pass(name: str, vram: bytes, graphics: bytes,
               masks: tuple[int, ...], palette: list[tuple[int, int, int, int]]) -> dict:
    native = Image.new("RGBA", (512, 256))
    pixels = native.load()
    nonempty: list[bool] = []
    for row in range(MAP_ROWS):
        map_row = (MAP_Y_TILE + row) & 63
        for column in range(MAP_COLS):
            offset = (map_row * 64 + column) * 4
            code = struct.unpack_from("<H", vram, offset)[0]
            attribute = struct.unpack_from("<H", vram, offset + 2)[0]
            flip_x = bool(code & 0x4000)
            flip_y = bool(code & 0x8000)
            pens = m72.decode_tile(graphics, code & 0x3FFF)
            group = (attribute >> 6) & 3
            mask = masks[group]
            any_pixel = False
            for y in range(8):
                source_y = 7 - y if flip_y else y
                for x in range(8):
                    source_x = 7 - x if flip_x else x
                    pen = pens[source_y * 8 + source_x]
                    if pen == 0 or mask & (1 << pen):
                        continue
                    pixels[column * 8 + x, row * 8 + y] = palette[
                        256 + (attribute & 15) * 16 + pen
                    ]
                    any_pixel = True
            nonempty.append(any_pixel)

    expanded = xbrz_offline.xbrz_expand(native, 6)
    logical = expanded.resize(
        (LOGICAL_MAP_W, LOGICAL_MAP_H), Image.Resampling.LANCZOS
    )
    # Карта циклическая по X; добавка начала устраняет особый crop колонки 63.
    wrapped = Image.new("RGBA", (LOGICAL_MAP_W + GLYPH_W, LOGICAL_MAP_H))
    wrapped.alpha_composite(logical, (0, 0))
    wrapped.alpha_composite(logical.crop((0, 0, GLYPH_W, LOGICAL_MAP_H)),
                            (LOGICAL_MAP_W, 0))

    blob = bytearray()
    cell_slots = [0xFFFF] * (MAP_COLS * MAP_ROWS)
    slot = 0
    for row in range(MAP_ROWS):
        for column in range(MAP_COLS):
            index = row * MAP_COLS + column
            if not nonempty[index]:
                continue
            if slot >= 0xFFFF:
                raise RuntimeError(f"{name}: число ячеек не помещается в word")
            left = round(column * LOGICAL_MAP_W / MAP_COLS)
            top = row * GLYPH_H
            cell = wrapped.crop((left, top, left + GLYPH_W, top + GLYPH_H))
            blob += atlas.pack_argb4444(cell)
            cell_slots[index] = slot
            slot += 1

    OUT.mkdir(parents=True, exist_ok=True)
    native_path = OUT / f"STAGE1_{name}_NATIVE.png"
    logical_path = OUT / f"STAGE1_{name}_LOGICAL.png"
    blob_path = OUT / f"STAGE1_{name}_ATLAS_ARGB4444.bin"
    map_path = OUT / f"STAGE1_{name}_MAP.bin"
    native.save(native_path)
    logical.save(logical_path)
    blob_path.write_bytes(blob)
    cell_map = struct.pack(f"<{len(cell_slots)}H", *cell_slots)
    map_path.write_bytes(cell_map)
    return {
        "name": name, "cells": slot, "blob": blob_path, "map": map_path,
        "blob_size": len(blob), "blob_sha256": hashlib.sha256(blob).hexdigest(),
        "map_sha256": hashlib.sha256(cell_map).hexdigest(),
    }


def main() -> int:
    m72.require_verified()
    regions = m72.assemble_regions()
    capture = scene.Capture.load(CAPTURE, FRAME, STATE_FRAME)
    palette = scene.palette_from_ram(capture.palette0, capture.palette1)
    back = build_pass(
        "BG_BACK", capture.vram1, regions["tiles1"],
        scene.BG_LAYER1_MASK, palette,
    )
    front = build_pass(
        "FG_FRONT", capture.vram0, regions["tiles0"],
        scene.FG_LAYER0_MASK, palette,
    )
    lines = [
        "; Сгенерировано m72_stage_tiles.py; вручную не редактировать.",
        f"M72_STAGE_GLYPH_W      EQU {GLYPH_W}",
        f"M72_STAGE_GLYPH_H      EQU {GLYPH_H}",
        f"M72_STAGE_GLYPH_BYTES  EQU {GLYPH_BYTES}",
        f"M72_STAGE_BG_COUNT     EQU {back['cells']}",
        f"M72_STAGE_FG_COUNT     EQU {front['cells']}",
        "M72_STAGE_MAP_SKIP     EQU #FFFF",
        "",
    ]
    INC.write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "format": 2, "frame": FRAME, "state_frame": STATE_FRAME,
        "map_slot_bits": 16,
        "source": "M72 World ROM + timing-paired MAME state",
        "native_full_layer": [512, 256],
        "offline": "xBRZ 1.9 x6 then Pillow Lanczos",
        "logical_full_layer": [LOGICAL_MAP_W, LOGICAL_MAP_H],
        "runtime": "FT812 NEAREST 8/5",
        "passes": [back, front],
    }
    # Path не сериализуется; в манифесте достаточно относительных имён.
    for item in manifest["passes"]:
        item["blob"] = str(Path(item["blob"]).relative_to(ROOT))
        item["map"] = str(Path(item["map"]).relative_to(ROOT))
    (OUT / "stage1_tiles.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Stage 1 tiles: BG back {back['cells']} / {back['blob_size']} Б, "
        f"FG front {front['cells']} / {front['blob_size']} Б"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
