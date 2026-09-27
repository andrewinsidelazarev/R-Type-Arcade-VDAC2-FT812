#!/usr/bin/env python3
"""Проверка восьми компактных RTZ2-файлов перед сборкой и SD-загрузкой.

Проверяется не только заголовок: каталог, все переписанные offsets и каждый
перенесённый блок должны побайтно совпасть с монолитным эталоном. Так ошибка
упаковщика не сможет проявиться уже на реальном ZX Evolution.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "Build"
SOURCE = (BUILD / "rtype_target_pack.bin").read_bytes()
SOURCE_MANIFEST = json.loads(
    (BUILD / "rtype_target_pack.json").read_text(encoding="utf-8")
)
PACK_MANIFEST = json.loads(
    (BUILD / "rtype_stage_packs.json").read_text(encoding="utf-8")
)
PACK_DIR = BUILD / "SD" / "RType"
PAGE_SIZE = 0x4000
DIRECTORY_OFFSET = 0x40
RECORD_SIZE = 72


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def source_bytes(stage: dict, name: str) -> bytes:
    section = stage[name]
    first = int(section["offset"])
    return SOURCE[first:first + int(section["size"])]


def check_one(stage: dict, entry: dict) -> None:
    number = int(stage["stage"])
    path = PACK_DIR / str(entry["filename"])
    payload = path.read_bytes()
    require(payload[:4] == b"RTZ2", f"stage {number}: нет magic RTZ2")
    require(len(payload) % PAGE_SIZE == 0, f"stage {number}: размер не по страницам")
    require(struct.unpack_from("<I", payload, 0x0C)[0] == len(payload),
            f"stage {number}: неверный размер в заголовке")
    require(len(payload) == int(entry["size"]), f"stage {number}: размер manifest")
    require(hashlib.sha256(payload).hexdigest() == entry["sha256"],
            f"stage {number}: sha256 manifest")

    # World ROM, SPZ1 и глобальные checkpoints находятся в общей части и не
    # переписываются упаковщиком уровней.
    for name in ("world_rom", "sprites"):
        section = SOURCE_MANIFEST["globals"][name]
        first, size = int(section["offset"]), int(section["size"])
        require(payload[first:first + size] == SOURCE[first:first + size],
                f"stage {number}: повреждён общий блок {name}")
    checkpoint = SOURCE_MANIFEST["global_checkpoints"]
    first, size = int(checkpoint["offset"]), int(checkpoint["size"])
    require(payload[first:first + size] == SOURCE[first:first + size],
            f"stage {number}: повреждены checkpoints")

    selected = DIRECTORY_OFFSET + (number - 1) * RECORD_SIZE
    for candidate in range(1, 9):
        first = DIRECTORY_OFFSET + (candidate - 1) * RECORD_SIZE
        record = payload[first:first + RECORD_SIZE]
        if candidate == number:
            require(record[0] == number, f"stage {number}: неверная запись каталога")
        else:
            require(record == bytes(RECORD_SIZE),
                    f"stage {number}: лишняя запись stage {candidate}")

    values = struct.unpack_from("<BB5H8I4I2HII", payload, selected)
    (stage_no, checkpoint_count, fg_count, bg_count, event_count,
     fg_source, bg_source, control_offset, control_size, checkpoint_offset,
     event_offset, fg_offset, fg_size, bg_offset, bg_size, fg_tex_offset,
     fg_tex_size, bg_tex_offset, bg_tex_size, fg_tex_count, bg_tex_count,
     palette_offset, palette_size) = values
    require(stage_no == number, f"stage {number}: номер")
    require(checkpoint_count == int(stage["checkpoint_count"]),
            f"stage {number}: checkpoint count")
    require((fg_count, bg_count, event_count, fg_source, bg_source) == (
        int(stage["foreground"]["strip_count"]),
        int(stage["background"]["strip_count"]),
        int(stage["event_count"]),
        int(stage["foreground_source_start"]),
        int(stage["background_source_start"])), f"stage {number}: metadata")

    moved = (
        ("control", control_offset, control_size,
         SOURCE[int(stage["control_offset"]):
                int(stage["control_offset"]) + int(stage["control_size"])]),
        ("foreground", fg_offset, fg_size, source_bytes(stage, "foreground")),
        ("background", bg_offset, bg_size, source_bytes(stage, "background")),
        ("foreground_texture", fg_tex_offset, fg_tex_size,
         source_bytes(stage, "foreground_texture")),
        ("background_texture", bg_tex_offset, bg_tex_size,
         source_bytes(stage, "background_texture")),
        ("tile_palette", palette_offset, palette_size,
         source_bytes(stage, "tile_palette")),
    )
    for name, offset, size, expected in moved:
        require(offset % PAGE_SIZE == 0, f"stage {number}: {name} не выровнен")
        require(offset + size <= len(payload), f"stage {number}: {name} вне файла")
        require(size == len(expected), f"stage {number}: размер {name}")
        require(payload[offset:offset + size] == expected,
                f"stage {number}: данные {name}")
    require(checkpoint_offset == control_offset, f"stage {number}: checkpoints offset")
    require(event_offset - control_offset ==
            int(stage["event_offset"]) - int(stage["control_offset"]),
            f"stage {number}: events offset")
    require(payload[fg_tex_offset:fg_tex_offset + 4] == b"TXS4",
            f"stage {number}: foreground texture magic")
    require(payload[bg_tex_offset:bg_tex_offset + 4] == b"TXS4",
            f"stage {number}: background texture magic")
    require((fg_tex_count, bg_tex_count) == (
        int(stage["foreground_texture"]["record_count"]),
        int(stage["background_texture"]["record_count"])),
        f"stage {number}: texture counts")


def main() -> int:
    entries = PACK_MANIFEST["stages"]
    require(len(entries) == 8, "должно быть восемь stage packs")
    for stage, entry in zip(SOURCE_MANIFEST["stages"], entries, strict=True):
        check_one(stage, entry)
    sizes = ", ".join(str(int(entry["pages"])) for entry in entries)
    print(f"stage-pack audit OK: 8 packs, pages = {sizes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
