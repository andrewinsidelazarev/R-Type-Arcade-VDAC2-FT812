#!/usr/bin/env python3
"""Компактный replay изменений tilemap Stage 1 из полной MAME-трассы.

Исходная карта и атласы создаются ``m72_stage_tiles.py`` из frame 898. Этот
шаг сворачивает повторяющиеся состояния ``code+attribute`` в общие слоты,
добавляет новые ROM-тайлы из точной MAME VRAM-трассы и выпускает поток пакетов
для Z80. По умолчанию собирается подтверждённый первый сегмент; полная трасса
до босса включается RTYPE_STAGE_LAST_FRAME=18000 для batch-atlas разработки.
Ни одного экранного кадра поток не хранит.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import m72_scene as scene
import m72_stage_tiles as stage
import m72_tile_atlas as atlas
import xbrz_offline

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_full_trace"
PALETTE_TRACE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_invincible_trace"
OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Tiles"
INC = ROOT / "Source" / "ASM" / "generated_m72_stage_stream.inc"
BASE_FRAME = 898
# Release пока использует подтверждённый первый сегмент. Полная непрерывная
# трасса до босса уже снята; для анализа/следующего batch-atlas шага задаётся
# RTYPE_STAGE_LAST_FRAME=18000 без изменения исходника.
LAST_FRAME = int(os.getenv("RTYPE_STAGE_LAST_FRAME", "1426"))
MAP_FIRST_ROW = 16
MAP_ROWS = 32
MAP_COLS = 64
STREAM_NAME = "STAGE1_VRAM_EVENTS.bin"
STREAM_PAGE_SIZE = 0x4000
PAGE_JUMP = struct.pack("<HBB", 0xFFFE, 0, 0)
STREAM_END = struct.pack("<HBB", 0xFFFF, 0, 0)
PALETTE_CHECKPOINTS = (898, 3500, 4500, 6500, 7500, 9500, 10500)


def pack_stream(events: list[tuple[int, list[tuple[int, int]],
                                        list[tuple[int, int]]]],
                page_size: int = STREAM_PAGE_SIZE) -> bytes:
    """Упаковать целые пакеты в 16К-страницы со служебным page-jump."""
    if page_size < 8:
        raise ValueError("страница потока слишком мала")
    stream = bytearray()
    for runtime_frame, foreground, background in events:
        packet = bytearray(struct.pack(
            "<HBB", runtime_frame, len(foreground), len(background)))
        for index, slot in foreground + background:
            packet += struct.pack("<HH", index, slot)
        if len(packet) + len(STREAM_END) > page_size:
            raise ValueError(
                f"пакет frame {runtime_frame} не помещается в страницу")
        offset = len(stream) % page_size
        if offset + len(packet) + len(STREAM_END) > page_size:
            stream += PAGE_JUMP
            stream += bytes((-len(stream)) % page_size)
        stream += packet
    offset = len(stream) % page_size
    if offset + len(STREAM_END) > page_size:
        stream += PAGE_JUMP
        stream += bytes((-len(stream)) % page_size)
    stream += STREAM_END
    return bytes(stream)


def state_at(vram: bytes | bytearray, cell: int) -> tuple[int, int]:
    return struct.unpack_from("<HH", vram, cell * 4)


def render_state(code: int, attribute: int, graphics: bytes,
                 masks: tuple[int, ...],
                 palette: list[tuple[int, int, int, int]]) -> bytes | None:
    """Один настоящий M72 8x8 primitive через тот же xBRZ6+Lanczos."""
    native = Image.new("RGBA", (8, 8))
    pixels = native.load()
    pens = m72.decode_tile(graphics, code & 0x3FFF)
    flip_x = bool(code & 0x4000)
    flip_y = bool(code & 0x8000)
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
            pixels[x, y] = palette[256 + (attribute & 15) * 16 + pen]
            any_pixel = True
    if not any_pixel:
        return None
    expanded = xbrz_offline.xbrz_expand(native, 6)
    logical = expanded.resize(
        (stage.GLYPH_W, stage.GLYPH_H), Image.Resampling.LANCZOS
    )
    return atlas.pack_argb4444(logical)


def initial_pass(name: str, vram: bytearray,
                 palette: list[tuple[int, int, int, int]]) -> tuple[
                     bytearray, list[int], dict[tuple, int]]:
    blob_path = OUT / f"STAGE1_{name}_ATLAS_ARGB4444.bin"
    map_path = OUT / f"STAGE1_{name}_MAP.bin"
    old_blob = blob_path.read_bytes()
    old_map_data = map_path.read_bytes()
    if len(old_map_data) != MAP_COLS * MAP_ROWS * 2:
        raise RuntimeError(f"{name}: неверный размер исходной карты")
    old_map = list(struct.unpack(f"<{MAP_COLS * MAP_ROWS}H", old_map_data))
    new_blob = bytearray()
    new_map = [0xFFFF] * len(old_map)
    # Один state получает один слот. Его изображение берётся из уже
    # апскейленного целого слоя, поэтому первый экран сохраняет HQ-контекст.
    state_to_slot: dict[tuple, int] = {}
    for row in range(MAP_ROWS):
        for column in range(MAP_COLS):
            index = row * MAP_COLS + column
            old_slot = old_map[index]
            if old_slot == 0xFFFF:
                continue
            cell = (MAP_FIRST_ROW + row) * 64 + column
            state = state_at(vram, cell)
            slot = state_to_slot.get(state)
            if slot is None:
                slot = len(new_blob) // stage.GLYPH_BYTES
                if slot >= 0xFFFF:
                    raise RuntimeError(f"{name}: атлас не помещается в word slot")
                begin = old_slot * stage.GLYPH_BYTES
                new_blob += old_blob[begin:begin + stage.GLYPH_BYTES]
                state_to_slot[state] = slot
            new_map[index] = slot
    blob_path.write_bytes(new_blob)
    map_path.write_bytes(struct.pack(f"<{len(new_map)}H", *new_map))
    return new_blob, new_map, state_to_slot


def main() -> int:
    m72.require_verified()
    trace_csv = TRACE / "vram_writes.csv"
    if not trace_csv.is_file():
        raise SystemExit("нет stage1_full_trace/vram_writes.csv")
    regions = m72.assemble_regions()
    palette0 = (TRACE / f"frame_{BASE_FRAME:06d}_palette0.bin").read_bytes()
    palette1 = (TRACE / f"frame_{BASE_FRAME:06d}_palette1.bin").read_bytes()
    palette = scene.palette_from_ram(palette0, palette1)
    checkpoint_palettes = {
        frame: scene.palette_from_ram(
            (PALETTE_TRACE / f"frame_{frame:06d}_palette0.bin").read_bytes(),
            (PALETTE_TRACE / f"frame_{frame:06d}_palette1.bin").read_bytes(),
        )
        for frame in PALETTE_CHECKPOINTS
    }

    passes = {
        0: {
            "name": "FG_FRONT", "base": 0xD0000,
            "vram": bytearray((TRACE / f"frame_{BASE_FRAME:06d}_vram0.bin").read_bytes()),
            "graphics": regions["tiles0"], "masks": scene.FG_LAYER0_MASK,
        },
        1: {
            "name": "BG_BACK", "base": 0xD8000,
            "vram": bytearray((TRACE / f"frame_{BASE_FRAME:06d}_vram1.bin").read_bytes()),
            "graphics": regions["tiles1"], "masks": scene.BG_LAYER1_MASK,
        },
    }
    for item in passes.values():
        blob, cell_map, lookup = initial_pass(
            item["name"], item["vram"], palette)
        item["blob"] = blob
        item["map"] = cell_map
        item["lookup"] = lookup
        item["packed_to_slot"] = {
            bytes(blob[offset:offset + stage.GLYPH_BYTES]): offset // stage.GLYPH_BYTES
            for offset in range(0, len(blob), stage.GLYPH_BYTES)
        }

    writes: dict[int, dict[int, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    with trace_csv.open(newline="", encoding="ascii") as source:
        for row in csv.DictReader(source):
            frame = int(row["frame"])
            if BASE_FRAME <= frame <= LAST_FRAME:
                writes[frame][int(row["layer"])].append(row)

    events: list[tuple[int, list[tuple[int, int]], list[tuple[int, int]]]] = []
    for frame in range(BASE_FRAME, LAST_FRAME + 1):
        if frame in checkpoint_palettes:
            palette = checkpoint_palettes[frame]
        layer_records: dict[int, list[tuple[int, int]]] = {0: [], 1: []}
        for layer, item in passes.items():
            touched: set[int] = set()
            vram = item["vram"]
            for row in writes.get(frame, {}).get(layer, []):
                offset = int(row["address"], 16) - item["base"]
                old = struct.unpack_from("<H", vram, offset)[0]
                data = int(row["data"], 16)
                mask = int(row["mask"], 16)
                struct.pack_into("<H", vram, offset,
                                 (old & (~mask & 0xFFFF)) | (data & mask))
                cell = offset // 4
                map_row = cell // MAP_COLS
                if MAP_FIRST_ROW <= map_row < MAP_FIRST_ROW + MAP_ROWS:
                    touched.add(cell)
            for cell in sorted(touched):
                state = state_at(vram, cell)
                slot = item["lookup"].get(state)
                if slot is None:
                    packed = render_state(
                        state[0], state[1], item["graphics"], item["masks"], palette
                    )
                    if packed is None:
                        slot = 0xFFFF
                    else:
                        slot = item["packed_to_slot"].get(packed)
                        if slot is None:
                            slot = len(item["blob"]) // stage.GLYPH_BYTES
                            if slot >= 0xFFFF:
                                raise RuntimeError(
                                    f"{item['name']}: больше 65534 слотов после трассы"
                                )
                            item["blob"] += packed
                            item["packed_to_slot"][packed] = slot
                    item["lookup"][state] = slot
                map_index = (cell // MAP_COLS - MAP_FIRST_ROW) * MAP_COLS + cell % MAP_COLS
                if item["map"][map_index] != slot:
                    item["map"][map_index] = slot
                    layer_records[layer].append((map_index, slot))
        if layer_records[0] or layer_records[1]:
            runtime_frame = frame - BASE_FRAME + 1
            longest = max(len(layer_records[0]), len(layer_records[1]))
            for first in range(0, longest, 255):
                events.append((runtime_frame,
                               layer_records[0][first:first + 255],
                               layer_records[1][first:first + 255]))

    stream = pack_stream(events)

    # На диске карты должны оставаться НАЧАЛЬНЫМИ; runtime применит пакеты сам.
    # Поэтому повторно строим только начальные word maps, а изменённые рабочие
    # копии выше использовались для проверки индексов.
    for item in passes.values():
        (OUT / f"STAGE1_{item['name']}_ATLAS_ARGB4444.bin").write_bytes(item["blob"])
    # initial_pass уже записал начальные карты и после этого они не менялись на диске.
    stream_path = OUT / STREAM_NAME
    stream_path.write_bytes(stream)

    counts = {item["name"]: len(item["blob"]) // stage.GLYPH_BYTES
              for item in passes.values()}
    stage_inc = stage.INC.read_text(encoding="utf-8")
    stage_inc = re.sub(r"M72_STAGE_BG_COUNT\s+EQU\s+\d+",
                       f"M72_STAGE_BG_COUNT     EQU {counts['BG_BACK']}", stage_inc)
    stage_inc = re.sub(r"M72_STAGE_FG_COUNT\s+EQU\s+\d+",
                       f"M72_STAGE_FG_COUNT     EQU {counts['FG_FRONT']}", stage_inc)
    stage.INC.write_text(stage_inc, encoding="utf-8")
    lines = [
        "; Сгенерировано m72_stage_stream.py; вручную не редактировать.",
        f"M72_STAGE_EVENT_COUNT       EQU {len(events)}",
        f"M72_STAGE_EVENT_STREAM_SIZE EQU {len(stream)}",
        f"M72_STAGE_EVENT_PAGE_COUNT  EQU {(len(stream) + STREAM_PAGE_SIZE - 1) // STREAM_PAGE_SIZE}",
        f"M72_STAGE_EVENT_MAX_RECORDS EQU {max(max(len(fg), len(bg)) for _, fg, bg in events)}",
        "",
    ]
    INC.write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "format": 3, "base_frame": BASE_FRAME, "last_frame": LAST_FRAME,
        "map_slot_bits": 16, "record_size": 4,
        "palette_checkpoints": list(PALETTE_CHECKPOINTS),
        "palette_model": "first appearance of each code+attribute at section checkpoint",
        "palette_only_animation": "pending runtime effect; geometry replay is complete",
        "page_size": STREAM_PAGE_SIZE, "page_jump": "0xFFFE",
        "source": str(trace_csv.relative_to(ROOT)),
        "events": [
            {"runtime_frame": runtime, "foreground": len(fg), "background": len(bg)}
            for runtime, fg, bg in events
        ],
        "atlas_counts": counts,
        "atlas_sha256": {
            item["name"]: hashlib.sha256(item["blob"]).hexdigest()
            for item in passes.values()
        },
        "stream_size": len(stream),
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
    }
    (OUT / "stage1_stream.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Stage 1 stream: {len(events)} пакетов / {len(stream)} Б; "
        f"BG {counts['BG_BACK']} слотов, FG {counts['FG_FRONT']} слотов"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
