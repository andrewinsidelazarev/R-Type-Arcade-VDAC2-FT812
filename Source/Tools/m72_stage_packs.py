#!/usr/bin/env python3
"""Разделить монолитный RTZ2 на восемь загружаемых stage-pack.

Каждый файл сохраняет неизменными общие страницы (заголовок, World ROM,
сжатый sprite-ROM, предвычисленные палитры и глобальные checkpoints), после
чего содержит данные ровно одного уровня. Выбранная 72-байтная запись каталога
переписывается на новые компактные offsets; остальные записи обнуляются.
Поэтому любой PAK можно читать прямо в одно виртуальное окно TS RAM,
начинающееся с page #49.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "Build"
SOURCE_PACK = BUILD / "rtype_target_pack.bin"
SOURCE_MANIFEST = BUILD / "rtype_target_pack.json"
OUTPUT_DIR = BUILD / "SD" / "RType"
OUTPUT_MANIFEST = BUILD / "rtype_stage_packs.json"
OUTPUT_INC = ROOT / "Source" / "ASM" / "generated_stage_packs.inc"
PAGE_SIZE = 0x4000
PACK_BASE_PAGE = 0x49
DIRECTORY_OFFSET = 0x40
STAGE_RECORD_SIZE = 72


def align_page(blob: bytearray) -> None:
    padding = (-len(blob)) % PAGE_SIZE
    if padding:
        blob.extend(bytes(padding))


def append_section(blob: bytearray, source: bytes, offset: int, size: int) -> int:
    align_page(blob)
    destination = len(blob)
    blob.extend(source[offset:offset + size])
    return destination


def section(stage: dict[str, Any], name: str) -> tuple[int, int]:
    item = stage[name]
    return int(item["offset"]), int(item["size"])


def build_one(
        source: bytes, stage: dict[str, Any], common_end: int
) -> tuple[bytes, dict[str, Any]]:
    stage_number = int(stage["stage"])
    result = bytearray(source[:common_end])
    result[DIRECTORY_OFFSET:DIRECTORY_OFFSET + 8 * STAGE_RECORD_SIZE] = bytes(
        8 * STAGE_RECORD_SIZE
    )

    control_offset = append_section(
        result, source, int(stage["control_offset"]), int(stage["control_size"])
    )
    foreground_offset = append_section(result, source, *section(stage, "foreground"))
    background_offset = append_section(result, source, *section(stage, "background"))
    fg_texture_offset = append_section(
        result, source, *section(stage, "foreground_texture")
    )
    bg_texture_offset = append_section(
        result, source, *section(stage, "background_texture")
    )
    palette_offset = append_section(result, source, *section(stage, "tile_palette"))
    align_page(result)

    foreground = stage["foreground"]
    background = stage["background"]
    fg_texture = stage["foreground_texture"]
    bg_texture = stage["background_texture"]
    palette = stage["tile_palette"]
    record_offset = DIRECTORY_OFFSET + (stage_number - 1) * STAGE_RECORD_SIZE
    event_delta = int(stage["event_offset"]) - int(stage["control_offset"])
    struct.pack_into(
        "<BB5H8I",
        result,
        record_offset,
        stage_number,
        int(stage["checkpoint_count"]),
        int(foreground["strip_count"]),
        int(background["strip_count"]),
        int(stage["event_count"]),
        int(stage["foreground_source_start"]),
        int(stage["background_source_start"]),
        control_offset,
        int(stage["control_size"]),
        control_offset,
        control_offset + event_delta,
        foreground_offset,
        int(foreground["size"]),
        background_offset,
        int(background["size"]),
    )
    struct.pack_into(
        "<4I2H",
        result,
        record_offset + 44,
        fg_texture_offset,
        int(fg_texture["size"]),
        bg_texture_offset,
        int(bg_texture["size"]),
        int(fg_texture["record_count"]),
        int(bg_texture["record_count"]),
    )
    struct.pack_into(
        "<II", result, record_offset + 64, palette_offset, int(palette["size"])
    )
    struct.pack_into("<I", result, 0x0C, len(result))
    payload = bytes(result)
    return payload, {
        "stage": stage_number,
        "filename": f"RTYPE{stage_number:02d}.PAK",
        "size": len(payload),
        "sectors": len(payload) // 512,
        "pages": len(payload) // PAGE_SIZE,
        "base_page": PACK_BASE_PAGE,
        "last_page": PACK_BASE_PAGE + len(payload) // PAGE_SIZE - 1,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def generated_inc(entries: list[dict[str, Any]]) -> str:
    lines = [
        "; Сгенерировано m72_stage_packs.py; вручную не редактировать.",
        f"RTYPE_STAGE_PACK_BASE_PAGE EQU #{PACK_BASE_PAGE:02X}",
        f"RTYPE_STAGE_PACK_COUNT     EQU {len(entries)}",
        "RTypeStagePackSectorTable:",
    ]
    lines.extend(f"                DEFW {entry['sectors']}" for entry in entries)
    lines.append("RTypeStagePackPageTable:")
    lines.extend(f"                DEFB {entry['pages']}" for entry in entries)
    lines.append("RTypeStagePackNameTable:")
    lines.extend(
        f"                DEFB \"{entry['filename']}\", 0" for entry in entries
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    source = SOURCE_PACK.read_bytes()
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    common_end = min(int(stage["control_offset"]) for stage in manifest["stages"])
    if common_end % PAGE_SIZE or len(source) < common_end or source[:4] != b"RTZ2":
        raise ValueError("исходный RTZ2 target-pack повреждён")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for stage in manifest["stages"]:
        payload, entry = build_one(source, stage, common_end)
        (OUTPUT_DIR / entry["filename"]).write_bytes(payload)
        entries.append(entry)
    report = {
        "format": "RTZ2-stage-pack-v1",
        "common_pages": common_end // PAGE_SIZE,
        "base_page": PACK_BASE_PAGE,
        "stages": entries,
    }
    OUTPUT_MANIFEST.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    OUTPUT_INC.write_text(generated_inc(entries), encoding="utf-8")
    for entry in entries:
        print(
            f"Stage {entry['stage']}: {entry['filename']} — "
            f"{entry['pages']} pages, #{entry['base_page']:02X}…#{entry['last_page']:02X}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
