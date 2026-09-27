#!/usr/bin/env python3
"""Построить raw M72 code+attribute -> локальный slot секционного атласа."""
from __future__ import annotations

import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "Build" / "Arcade" / "Stage1Batch"
SECTIONS = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Sections"
GLYPH_BYTES = 14 * 15 * 2


def emit(layer_name: str, short: str, section: int) -> int:
    records = json.loads((BATCH / f"{layer_name}_states.json").read_text(
        encoding="utf-8"))
    global_blob = (BATCH / f"{layer_name}_dedup_argb4444.bin").read_bytes()
    global_chunks = {
        global_blob[offset:offset + GLYPH_BYTES]: offset // GLYPH_BYTES
        for offset in range(0, len(global_blob), GLYPH_BYTES)
    }
    local_path = SECTIONS / f"STAGE1_S{section}_{short}_ATLAS_ARGB4444.bin"
    local_blob = local_path.read_bytes()
    local_by_global: dict[int, int] = {}
    for offset in range(0, len(local_blob), GLYPH_BYTES):
        chunk = local_blob[offset:offset + GLYPH_BYTES]
        local_by_global[global_chunks[chunk]] = offset // GLYPH_BYTES

    lookup = sorted(
        (int(item["code"]), int(item["attribute"]),
         local_by_global[int(item["slot"])])
        for item in records if int(item["slot"]) in local_by_global
    )
    blob = struct.pack("<H", len(lookup)) + b"".join(
        struct.pack("<HHH", *item) for item in lookup)
    output = SECTIONS / f"STAGE1_S{section}_{short}_LOOKUP.bin"
    output.write_bytes(blob)
    print(f"{output.name}: {len(lookup)} states, {len(blob)} bytes")
    return len(lookup)


def main() -> int:
    for section in range(6):
        emit("FG_FRONT", "FG", section)
        emit("BG_BACK", "BG", section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
