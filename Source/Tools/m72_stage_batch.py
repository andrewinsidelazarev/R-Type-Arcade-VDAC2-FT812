#!/usr/bin/env python3
"""Batch-xBRZ анализ полного tile-потока Stage 1.

Тысячи M72 8x8 primitives раскладываются на два padded sheet на слой.
Прозрачные тайлы идут через ARGB/OobReaderTransparent, полностью
непрозрачные — через RGB/OobReaderDuplicate. Это побитно повторяет
автоматический выбор xbrz_offline.xbrz_expand для одиночного тайла, но
создаёт всего два helper-процесса вместо тысяч.
Результат нужен для разбиения полного уровня на секционные RAM_G-атласы.
Release-ассеты этот инструмент пока не заменяет.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import m72_scene as scene
import m72_stage_stream as stream
import m72_stage_tiles as stage
import m72_tile_atlas as atlas
import xbrz_offline

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_full_trace"
PALETTE_TRACE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_invincible_trace"
OUT = ROOT / "Build" / "Arcade" / "Stage1Batch"
ASSET_OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Sections"
INC = ROOT / "Source" / "ASM" / "generated_m72_stage_sections.inc"
BASE_FRAME = 898
LAST_FRAME = 18000
MAP_FIRST_CELL = 16 * 64
MAP_LAST_CELL = 48 * 64
SECTION_STARTS = (898, 3500, 6500, 9500, 12500, 15000)
SECTION_END = LAST_FRAME + 1
PADDING = 4
SHEET_COLUMNS = 64


def native_state(code: int, attribute: int, graphics: bytes,
                 masks: tuple[int, ...],
                 palette: list[tuple[int, int, int, int]]) -> Image.Image | None:
    image = Image.new("RGBA", (8, 8))
    pixels = image.load()
    pens = m72.decode_tile(graphics, code & 0x3FFF)
    flip_x = bool(code & 0x4000)
    flip_y = bool(code & 0x8000)
    mask = masks[(attribute >> 6) & 3]
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
    return image if any_pixel else None


def transparent_pad(tile: Image.Image, padding: int) -> Image.Image:
    """Окружить 8x8 прозрачностью, как ARGB OOB одиночного xBRZ image."""
    width, height = tile.size
    result = Image.new("RGBA", (width + padding * 2, height + padding * 2))
    result.paste(tile, (padding, padding))
    return result


def duplicate_pad(tile: Image.Image, padding: int) -> Image.Image:
    """Повторить край RGB-тайла, как OobReaderDuplicate."""
    width, height = tile.size
    result = Image.new("RGBA", (width + padding * 2, height + padding * 2),
                       (0, 0, 0, 255))
    result.paste(tile, (padding, padding))
    left = tile.crop((0, 0, 1, height)).resize(
        (padding, height), Image.Resampling.NEAREST)
    right = tile.crop((width - 1, 0, width, height)).resize(
        (padding, height), Image.Resampling.NEAREST)
    result.paste(left, (0, padding))
    result.paste(right, (padding + width, padding))
    top = result.crop((0, padding, result.width, padding + 1)).resize(
        (result.width, padding), Image.Resampling.NEAREST)
    bottom = result.crop((0, padding + height - 1,
                          result.width, padding + height)).resize(
        (result.width, padding), Image.Resampling.NEAREST)
    result.paste(top, (0, 0))
    result.paste(bottom, (0, padding + height))
    return result


def palette_snapshots() -> dict[int, list[tuple[int, int, int, int]]]:
    return {
        frame: scene.palette_from_ram(
            (PALETTE_TRACE / f"frame_{frame:06d}_palette0.bin").read_bytes(),
            (PALETTE_TRACE / f"frame_{frame:06d}_palette1.bin").read_bytes(),
        )
        for frame in stream.PALETTE_CHECKPOINTS
    }


def palette_frame(frame: int) -> int:
    return max(value for value in stream.PALETTE_CHECKPOINTS if value <= frame)


def collect_states() -> tuple[list[dict], list[list[set[tuple[int, int]]]]]:
    regions = m72.assemble_regions()
    palettes = palette_snapshots()
    passes = [
        {
            "name": "FG_FRONT", "base": 0xD0000,
            "vram": bytearray((TRACE / "frame_000898_vram0.bin").read_bytes()),
            "graphics": regions["tiles0"], "masks": scene.FG_LAYER0_MASK,
            "states": {},
        },
        {
            "name": "BG_BACK", "base": 0xD8000,
            "vram": bytearray((TRACE / "frame_000898_vram1.bin").read_bytes()),
            "graphics": regions["tiles1"], "masks": scene.BG_LAYER1_MASK,
            "states": {},
        },
    ]
    section_states = [[set() for _ in SECTION_STARTS] for _ in passes]

    def remember(layer: int, state: tuple[int, int], frame: int,
                 section: int) -> None:
        item = passes[layer]
        item["states"].setdefault(state, (frame, palette_frame(frame)))
        section_states[layer][section].add(state)

    def snapshot_section(section: int, frame: int) -> None:
        for layer, item in enumerate(passes):
            for cell in range(MAP_FIRST_CELL, MAP_LAST_CELL):
                remember(layer, stream.state_at(item["vram"], cell), frame, section)

    snapshot_section(0, BASE_FRAME)
    current_section = 0
    current_frame = None
    touched = [set(), set()]

    def flush(frame: int | None) -> None:
        if frame is None:
            return
        for layer, cells in enumerate(touched):
            for cell in cells:
                remember(layer, stream.state_at(passes[layer]["vram"], cell),
                         frame, current_section)
            cells.clear()

    with (TRACE / "vram_writes.csv").open(newline="", encoding="ascii") as source:
        for row in csv.DictReader(source):
            frame = int(row["frame"])
            if frame < BASE_FRAME:
                continue
            if frame > LAST_FRAME:
                break
            if current_frame is not None and frame != current_frame:
                flush(current_frame)
                while (current_section + 1 < len(SECTION_STARTS) and
                       frame >= SECTION_STARTS[current_section + 1]):
                    current_section += 1
                    snapshot_section(current_section, SECTION_STARTS[current_section])
            current_frame = frame
            layer = int(row["layer"])
            item = passes[layer]
            offset = int(row["address"], 16) - item["base"]
            old = struct.unpack_from("<H", item["vram"], offset)[0]
            data = int(row["data"], 16)
            mask = int(row["mask"], 16)
            struct.pack_into("<H", item["vram"], offset,
                             (old & (~mask & 0xFFFF)) | (data & mask))
            cell = offset // 4
            if MAP_FIRST_CELL <= cell < MAP_LAST_CELL:
                touched[layer].add(cell)
    flush(current_frame)

    for item in passes:
        item["palettes"] = palettes
    return passes, section_states


def render_batch(item: dict) -> tuple[dict[tuple[int, int], int], bytes, dict]:
    ordered = sorted(item["states"].items(), key=lambda pair: (pair[1], pair[0]))
    visible: list[tuple[tuple[int, int], Image.Image, int, int]] = []
    state_to_slot: dict[tuple[int, int], int] = {}
    empty = 0
    for state, (first_frame, palette_at) in ordered:
        native = native_state(state[0], state[1], item["graphics"], item["masks"],
                              item["palettes"][palette_at])
        if native is None:
            state_to_slot[state] = 0xFFFF
            empty += 1
        else:
            visible.append((state, native, first_frame, palette_at))

    OUT.mkdir(parents=True, exist_ok=True)
    cell = 8 + PADDING * 2
    groups = {
        "argb": [(index, record) for index, record in enumerate(visible)
                 if record[1].getchannel("A").getextrema() != (255, 255)],
        "rgb": [(index, record) for index, record in enumerate(visible)
                if record[1].getchannel("A").getextrema() == (255, 255)],
    }
    logical_by_index: dict[int, Image.Image] = {}
    sheet_stats = {}
    for mode, members in groups.items():
        if not members:
            continue
        rows = math.ceil(len(members) / SHEET_COLUMNS)
        fill = (0, 0, 0, 0) if mode == "argb" else (0, 0, 0, 255)
        sheet = Image.new("RGBA", (SHEET_COLUMNS * cell, rows * cell), fill)
        for local_index, (_, (_, native, _, _)) in enumerate(members):
            x = (local_index % SHEET_COLUMNS) * cell
            y = (local_index // SHEET_COLUMNS) * cell
            padded = (transparent_pad(native, PADDING) if mode == "argb"
                      else duplicate_pad(native, PADDING))
            sheet.paste(padded, (x, y))
        sheet_path = OUT / f"{item['name']}_{mode}_native_sheet.png"
        sheet.save(sheet_path)
        expanded = xbrz_offline.xbrz_expand(sheet, 6)
        for local_index, (original_index, _) in enumerate(members):
            x = (local_index % SHEET_COLUMNS) * cell
            y = (local_index // SHEET_COLUMNS) * cell
            left = (x + PADDING) * 6
            top = (y + PADDING) * 6
            logical_by_index[original_index] = expanded.crop(
                (left, top, left + 48, top + 48)).resize(
                    (stage.GLYPH_W, stage.GLYPH_H), Image.Resampling.LANCZOS)
        sheet_stats[mode] = {
            "states": len(members), "size": list(sheet.size),
            "sha256": hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
        }

    packed_to_slot: dict[bytes, int] = {}
    blob = bytearray()
    records = []
    for index, (state, _, first_frame, palette_at) in enumerate(visible):
        logical = logical_by_index[index]
        packed = atlas.pack_argb4444(logical)
        slot = packed_to_slot.get(packed)
        if slot is None:
            slot = len(blob) // stage.GLYPH_BYTES
            packed_to_slot[packed] = slot
            blob += packed
        state_to_slot[state] = slot
        records.append({
            "code": state[0], "attribute": state[1], "slot": slot,
            "first_frame": first_frame, "palette_frame": palette_at,
        })

    # Доказать batch-эквивалентность отдельно для ARGB и RGB:
    # xBRZ использует для них разные OOB-reader.
    sample_indices = set()
    for members in groups.values():
        if members:
            sample_indices.update((members[0][0], members[len(members) // 2][0],
                                   members[-1][0]))
    sample_indices = sorted(sample_indices)
    for index in sample_indices:
        state, _, _, palette_at = visible[index]
        isolated = stream.render_state(
            state[0], state[1], item["graphics"], item["masks"],
            item["palettes"][palette_at])
        slot = state_to_slot[state]
        assert isolated == blob[slot * stage.GLYPH_BYTES:(slot + 1) * stage.GLYPH_BYTES], (
            item["name"], index, state)

    blob_path = OUT / f"{item['name']}_dedup_argb4444.bin"
    blob_path.write_bytes(blob)
    records_path = OUT / f"{item['name']}_states.json"
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return state_to_slot, bytes(blob), {
        "states": len(ordered), "nonempty_states": len(visible), "empty_states": empty,
        "dedup_glyphs": len(blob) // stage.GLYPH_BYTES,
        "dedup_bytes": len(blob), "sheets": sheet_stats,
        "blob_sha256": hashlib.sha256(blob).hexdigest(),
    }


def emit_section_assets(passes: list[dict], section_states: list[list[set]],
                        mappings: list[dict[tuple[int, int], int]],
                        blobs: list[bytes]) -> list[dict]:
    """Выпустить независимые атласы, начальные карты и delta-потоки."""
    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    local_maps: list[list[dict[int, int]]] = [[], []]
    local_blobs: list[list[bytes]] = [[], []]
    for layer in range(2):
        for section in range(len(SECTION_STARTS)):
            global_slots = sorted({
                mappings[layer][state]
                for state in section_states[layer][section]
                if mappings[layer][state] != 0xFFFF
            })
            slot_map = {slot: local for local, slot in enumerate(global_slots)}
            local_maps[layer].append(slot_map)
            local_blobs[layer].append(b"".join(
                blobs[layer][slot * stage.GLYPH_BYTES:(slot + 1) * stage.GLYPH_BYTES]
                for slot in global_slots
            ))

    def local_slot(layer: int, section: int, state: tuple[int, int]) -> int:
        global_slot = mappings[layer][state]
        if global_slot == 0xFFFF:
            return 0xFFFF
        return local_maps[layer][section][global_slot]

    vram = [bytearray((TRACE / "frame_000898_vram0.bin").read_bytes()),
            bytearray((TRACE / "frame_000898_vram1.bin").read_bytes())]
    initial_maps: list[list[list[int] | None]] = [
        [None for _ in SECTION_STARTS] for _ in passes]
    working_maps: list[list[int]] = [[], []]
    events: list[list[tuple[int, list[tuple[int, int]],
                                 list[tuple[int, int]]]]] = [
        [] for _ in SECTION_STARTS]
    current_section = 0
    current_frame: int | None = None
    touched = [set(), set()]

    def begin_section(section: int) -> None:
        for layer in range(2):
            values = []
            for index in range(stage.MAP_COLS * stage.MAP_ROWS):
                row = index // stage.MAP_COLS + stage.MAP_Y_TILE
                cell = row * stage.MAP_COLS + index % stage.MAP_COLS
                values.append(local_slot(layer, section,
                                         stream.state_at(vram[layer], cell)))
            initial_maps[layer][section] = values.copy()
            working_maps[layer] = values

    def flush(frame: int | None) -> None:
        if frame is None:
            return
        records: list[list[tuple[int, int]]] = [[], []]
        for layer in range(2):
            for cell in sorted(touched[layer]):
                index = ((cell // stage.MAP_COLS - stage.MAP_Y_TILE) *
                         stage.MAP_COLS + cell % stage.MAP_COLS)
                slot = local_slot(layer, current_section,
                                  stream.state_at(vram[layer], cell))
                if working_maps[layer][index] != slot:
                    working_maps[layer][index] = slot
                    records[layer].append((index, slot))
            touched[layer].clear()
        if records[0] or records[1]:
            runtime_frame = frame - BASE_FRAME + 1
            longest = max(len(records[0]), len(records[1]))
            for first in range(0, longest, 255):
                events[current_section].append((
                    runtime_frame, records[0][first:first + 255],
                    records[1][first:first + 255]))

    begin_section(0)
    with (TRACE / "vram_writes.csv").open(newline="", encoding="ascii") as source:
        for row in csv.DictReader(source):
            frame = int(row["frame"])
            if frame < BASE_FRAME:
                continue
            if frame > LAST_FRAME:
                break
            if current_frame is not None and frame != current_frame:
                flush(current_frame)
                while (current_section + 1 < len(SECTION_STARTS) and
                       frame >= SECTION_STARTS[current_section + 1]):
                    current_section += 1
                    begin_section(current_section)
            current_frame = frame
            layer = int(row["layer"])
            offset = int(row["address"], 16) - passes[layer]["base"]
            old = struct.unpack_from("<H", vram[layer], offset)[0]
            data = int(row["data"], 16)
            mask = int(row["mask"], 16)
            struct.pack_into("<H", vram[layer], offset,
                             (old & (~mask & 0xFFFF)) | (data & mask))
            cell = offset // 4
            if MAP_FIRST_CELL <= cell < MAP_LAST_CELL:
                touched[layer].add(cell)
    flush(current_frame)

    result = []
    for section, start in enumerate(SECTION_STARTS):
        end = (SECTION_STARTS[section + 1]
               if section + 1 < len(SECTION_STARTS) else SECTION_END)
        prefix = f"STAGE1_S{section}"
        layer_data = {}
        for layer, short in ((0, "FG"), (1, "BG")):
            blob = local_blobs[layer][section]
            values = initial_maps[layer][section]
            assert values is not None
            map_blob = struct.pack(f"<{len(values)}H", *values)
            atlas_path = ASSET_OUT / f"{prefix}_{short}_ATLAS_ARGB4444.bin"
            map_path = ASSET_OUT / f"{prefix}_{short}_MAP.bin"
            atlas_path.write_bytes(blob)
            map_path.write_bytes(map_blob)
            layer_data[short.lower()] = {
                "glyphs": len(blob) // stage.GLYPH_BYTES,
                "atlas_size": len(blob),
                "atlas_sha256": hashlib.sha256(blob).hexdigest(),
                "map_sha256": hashlib.sha256(map_blob).hexdigest(),
            }
        event_blob = stream.pack_stream(events[section])
        event_path = ASSET_OUT / f"{prefix}_EVENTS.bin"
        event_path.write_bytes(event_blob)
        result.append({
            "index": section, "start_frame": start, "end_frame": end,
            "runtime_start": start - BASE_FRAME + 1,
            "runtime_end": end - BASE_FRAME,
            "events": len(events[section]), "event_size": len(event_blob),
            "event_pages": math.ceil(len(event_blob) / stream.STREAM_PAGE_SIZE),
            "event_sha256": hashlib.sha256(event_blob).hexdigest(),
            **layer_data,
        })
    inc_lines = [
        "; Сгенерировано m72_stage_batch.py; вручную не редактировать.",
        f"M72_STAGE_SECTION_COUNT EQU {len(result)}",
        "M72StageSectionRuntimeStarts:",
    ]
    for item in result:
        inc_lines.append(f"                DEFW {item['runtime_start']}")
    inc_lines.append("")
    INC.write_text("\n".join(inc_lines), encoding="utf-8")
    return result


def main() -> int:
    m72.require_verified()
    passes, section_states = collect_states()
    mappings = []
    blobs = []
    layer_stats = []
    for item in passes:
        mapping, blob, stats = render_batch(item)
        mappings.append(mapping)
        blobs.append(blob)
        layer_stats.append(stats)
        print(f"{item['name']}: {stats['states']} states -> "
              f"{stats['dedup_glyphs']} glyphs / {stats['dedup_bytes']} Б")

    section_assets = emit_section_assets(
        passes, section_states, mappings, blobs)

    sections = []
    for number, start in enumerate(SECTION_STARTS):
        end = (SECTION_STARTS[number + 1]
               if number + 1 < len(SECTION_STARTS) else SECTION_END)
        counts = []
        for layer in range(2):
            slots = {mappings[layer][state] for state in section_states[layer][number]}
            slots.discard(0xFFFF)
            counts.append(len(slots))
        total_bytes = sum(counts) * stage.GLYPH_BYTES
        sections.append({
            "index": number, "start_frame": start, "end_frame": end,
            "foreground_glyphs": counts[0], "background_glyphs": counts[1],
            "atlas_bytes": total_bytes,
            "asset": section_assets[number],
        })
        print(f"section {number} {start}..{end - 1}: "
              f"FG {counts[0]} + BG {counts[1]} = {total_bytes} Б")

    manifest = {
        "format": 1, "source": str((TRACE / "vram_writes.csv").relative_to(ROOT)),
        "base_frame": BASE_FRAME, "last_frame": LAST_FRAME,
        "algorithm": "ARGB transparent + RGB duplicate padded sheets -> xBRZ 1.9 x6 -> per-cell Lanczos",
        "padding": PADDING, "columns": SHEET_COLUMNS,
        "batch_equivalence_samples_per_layer": 3,
        "layers": layer_stats, "sections": sections,
        "combined_dedup_bytes": sum(len(blob) for blob in blobs),
    }
    (OUT / "stage1_batch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {OUT / 'stage1_batch_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
