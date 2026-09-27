#!/usr/bin/env python3
"""Выгрузить ландшафт всех восьми stages напрямую из World ROM R-Type.

Файл не делает видеозахват и не восстанавливает карту по картинке. Он исполняет
формат `$EA95/$EB02`: пять metatile descriptors образуют одну полосу 8x30
tiles. Результат пригоден Python-модели и будущему ASM/FT812 без runtime scale.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from m72_stage_event_map import HANDLER_NAMES, STAGE_RANGES


ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUT = ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" / "Terrain"
MANIFEST = OUT / "all_stage_terrain.json"

WORLD_BASE = 0x10000
METATILE_BASE = 0x30000
CHECKPOINT_TABLE = 0x87FA
CHECKPOINT_COUNT = 17
DISPATCH_TABLE = 0xB92D
LAYER_RANGES = ((0xC627, 0xD68F), (0xD68F, 0xEB07))
LAYER_BIASES = (0x39D9, 0x2971)
LAYER_NAMES = ("foreground", "background")
BLANK_CODE = 0x0FA0
STRIP_ROWS = 30
STRIP_COLUMNS = 8
STRIP_SOURCE_BYTES = 10


def word(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def world_word(rom: bytes, address: int) -> int:
    return word(rom, WORLD_BASE + address)


def checkpoints(rom: bytes) -> list[dict[str, int]]:
    result = []
    for index in range(CHECKPOINT_COUNT):
        values = struct.unpack_from("<7H", rom,
                                    WORLD_BASE + CHECKPOINT_TABLE + index * 14)
        result.append({
            "index": index,
            "progression": values[0],
            "foreground_source": values[1],
            "background_source": values[2],
            "foreground_velocity_q8": values[3],
            "background_velocity_q8": values[4],
            "packed_resource_music": values[5],
            "stage": values[6],
        })
    return result


def stage_events(rom: bytes, stage: int, first: int,
                 last: int) -> list[dict[str, int | str]]:
    result = []
    for address in range(first, last + 1, 4):
        threshold, command = struct.unpack_from("<HH", rom,
                                                 WORLD_BASE + address)
        dispatch_offset = (command >> 9) & 0x7E
        handler = world_word(rom, DISPATCH_TABLE + dispatch_offset)
        result.append({
            "address": address,
            "threshold": threshold,
            "command": command,
            "opcode": dispatch_offset // 2,
            "handler": handler,
            "meaning": HANDLER_NAMES[handler],
        })
    if result[0]["threshold"] != first_stage_progression(stage):
        raise ValueError(f"Stage {stage}: неверный первый progression")
    return result


def first_stage_progression(stage: int) -> int:
    return (0x0600, 0x1500, 0x1F80, 0x2A00,
            0x3480, 0x3F00, 0x4980, 0x5400)[stage - 1]


def decode_strip(rom: bytes, layer: int, source: int) -> bytes:
    """Вернуть 30x8 пар `(u16 code, u16 attribute)` в экранном порядке."""
    if layer not in (0, 1):
        raise ValueError("слой должен быть 0 или 1")
    descriptor_address = (source - LAYER_BIASES[layer]) & 0xFFFF
    rows: list[list[tuple[int, int]]] = []
    for metatile_index in range(5):
        descriptor = world_word(rom, descriptor_address + metatile_index * 2)
        metatile = descriptor & 0x3FFF
        if metatile >= 256:
            raise ValueError(f"metatile index ${metatile:04X} вне банка")
        flip_x = bool(descriptor & 0x4000)
        flip_y = bool(descriptor & 0x8000)
        cells: list[list[tuple[int, int]]] = []
        cursor = METATILE_BASE + metatile * 144
        for _row in range(6):
            row = []
            for _column in range(8):
                code = word(rom, cursor)
                attribute = word(rom, cursor + 2)
                cursor += 3
                if flip_x:
                    code ^= 0x4000
                if flip_y:
                    code ^= 0x8000
                row.append((code, attribute))
            cells.append(row)
        if flip_x:
            cells = [list(reversed(row)) for row in cells]
        if flip_y:
            cells.reverse()
        rows.extend(cells)
    if len(rows) != STRIP_ROWS or any(len(row) != STRIP_COLUMNS for row in rows):
        raise AssertionError("полоса не равна 8x30 tiles")
    return b"".join(struct.pack("<HH", code, attribute)
                    for row in rows for code, attribute in row)


def blank_vram(layer: int) -> bytearray:
    result = bytearray(0x4000)
    first = 0x0200 if layer == 0 else 0
    for offset in range(first, 0x4000, 4):
        struct.pack_into("<HH", result, offset, BLANK_CODE, 0)
    return result


def apply_strip(vram: bytearray, destination: int, strip: bytes) -> None:
    cells = tuple(struct.iter_unpack("<HH", strip))
    if len(cells) != STRIP_ROWS * STRIP_COLUMNS:
        raise ValueError("неверный размер декодированной полосы")
    base = ((destination * 2) + 0x1020) & 0x10FF
    for row in range(STRIP_ROWS):
        output = base + row * 0x100
        for column in range(STRIP_COLUMNS):
            struct.pack_into("<HH", vram, output + column * 4,
                             *cells[row * STRIP_COLUMNS + column])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_source_bounds(all_checkpoints: list[dict[str, int]],
                        stage: int, layer_name: str) -> tuple[int, int]:
    field = layer_name + "_source"
    start = next(item[field] for item in all_checkpoints
                 if item["stage"] == stage)
    if stage < 8:
        end = next(item[field] for item in all_checkpoints
                   if item["stage"] == stage + 1)
    else:
        layer = LAYER_NAMES.index(layer_name)
        start_address, end_address = LAYER_RANGES[layer]
        end = end_address - start_address
    if start % STRIP_SOURCE_BYTES or end % STRIP_SOURCE_BYTES or end < start:
        raise ValueError(f"Stage {stage} {layer_name}: неверные source bounds")
    return start, end


def build(*, write_outputs: bool = True) -> dict[str, object]:
    rom = ROM_PATH.read_bytes()
    if len(rom) != 0x100000:
        raise ValueError("неверный размер RTYPE_MAINCPU_REGION.bin")
    all_checkpoints = checkpoints(rom)
    if tuple(item["stage"] for item in all_checkpoints) != (
            1, 1, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 1):
        raise ValueError("checkpoint stage sequence изменилась")

    if write_outputs:
        OUT.mkdir(parents=True, exist_ok=True)
    stages = []
    for stage, event_first, event_last in STAGE_RANGES:
        stage_directory = OUT / f"Stage{stage}"
        if write_outputs:
            stage_directory.mkdir(parents=True, exist_ok=True)
        layer_entries = {}
        for layer, layer_name in enumerate(LAYER_NAMES):
            source_start, source_end = stage_source_bounds(
                all_checkpoints, stage, layer_name)
            strips = [decode_strip(rom, layer, source)
                      for source in range(source_start, source_end,
                                          STRIP_SOURCE_BYTES)]
            stream = b"".join(strips)
            stream_path = stage_directory / f"stage{stage}_{layer_name}_strips.bin"
            if write_outputs:
                stream_path.write_bytes(stream)

            initial_vram = blank_vram(layer)
            for index, strip in enumerate(strips[:7]):
                apply_strip(initial_vram, index * 0x10, strip)
            initial_path = stage_directory / f"stage{stage}_{layer_name}_initial_vram.bin"
            if write_outputs:
                initial_path.write_bytes(initial_vram)

            final_vram = bytearray(initial_vram)
            for index, strip in enumerate(strips[7:], 7):
                apply_strip(final_vram, (index * 0x10) & 0xFF, strip)
            final_path = stage_directory / f"stage{stage}_{layer_name}_final_ring.bin"
            if write_outputs:
                final_path.write_bytes(final_vram)
            layer_entries[layer_name] = {
                "descriptor_range": [LAYER_RANGES[layer][0],
                                     LAYER_RANGES[layer][1] - 1],
                "source_start": source_start,
                "source_end_exclusive": source_end,
                "strip_count": len(strips),
                "strip_bytes": len(strips[0]) if strips else 0,
                "stream": str(stream_path.relative_to(ROOT)).replace("\\", "/"),
                "stream_sha256": sha256(stream),
                "initial_vram": str(initial_path.relative_to(ROOT)).replace("\\", "/"),
                "initial_vram_sha256": sha256(initial_vram),
                "final_ring": str(final_path.relative_to(ROOT)).replace("\\", "/"),
                "final_ring_sha256": sha256(final_vram),
            }

        stage_checkpoints = [item for item in all_checkpoints
                             if item["stage"] == stage]
        # Последняя запись повторяет Stage 1 и является loop sentinel.
        if stage == 1:
            stage_checkpoints = stage_checkpoints[:-1]
        stages.append({
            "stage": stage,
            "event_range": [event_first, event_last],
            "events": stage_events(rom, stage, event_first, event_last),
            "checkpoints": stage_checkpoints,
            "layers": layer_entries,
        })

    return {
        "schema": 1,
        "source_rom": str(ROM_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_rom_sha256": sha256(rom),
        "format": {
            "strip": "30 rows x 8 columns x (u16 code,u16 attribute), little-endian",
            "tile_size_native": [8, 8],
            "strip_size_native": [64, 240],
            "runtime_scaling": False,
        },
        "stage_count": len(stages),
        "event_count": sum(len(item["events"]) for item in stages),
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="проверить воспроизводимость существующих файлов")
    args = parser.parse_args()
    manifest = build(write_outputs=not args.check)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != text:
            raise SystemExit("all-stage terrain manifest не воспроизводится")
        for stage in manifest["stages"]:
            for layer in stage["layers"].values():
                for path_key, hash_key in (
                        ("stream", "stream_sha256"),
                        ("initial_vram", "initial_vram_sha256"),
                        ("final_ring", "final_ring_sha256")):
                    path = ROOT / layer[path_key]
                    if not path.is_file() or sha256(path.read_bytes()) != layer[hash_key]:
                        raise SystemExit(f"не совпадает generated terrain file: {path}")
    else:
        MANIFEST.write_text(text, encoding="utf-8")
    print(f"Stages: {manifest['stage_count']}")
    print(f"Events: {manifest['event_count']}")
    for item in manifest["stages"]:
        fg = item["layers"]["foreground"]["strip_count"]
        bg = item["layers"]["background"]["strip_count"]
        print(f"Stage {item['stage']}: FG {fg} strips, BG {bg} strips, "
              f"events {len(item['events'])}")
    print(MANIFEST)
    if args.check:
        print("AUTOCHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
