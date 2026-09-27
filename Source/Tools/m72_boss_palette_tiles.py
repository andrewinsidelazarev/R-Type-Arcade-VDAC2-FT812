#!/usr/bin/env python3
"""Build the Stage-1 boss normal/hit-flash tile variants offline.

The tile code/attribute states are unchanged between adjacent MAME frames
9500 (blue hit flash) and 9501 (normal orange).  Only tile palette slot 6 in
bank 1 changes.  Both checkpoints go through the established batch
xBRZ6+Lanczos conversion.  Runtime switches immutable atlas/lookup files.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import m72_arcade as m72
import m72_scene as scene
import m72_stage_batch as batch


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Sections"
CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "boss_palette_probe"
VARIANTS = (("NORMAL9501", 9501), ("FLASH9500", 9500))
SECTIONS = (2, 3)


def read_states(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    count = struct.unpack_from("<H", data)[0]
    if len(data) != 2 + count * 6:
        raise ValueError(f"invalid lookup: {path}")
    return [(code, attribute)
            for code, attribute, _slot in struct.iter_unpack("<HHH", data[2:])]


def main() -> int:
    m72.require_verified()
    regions = m72.assemble_regions()
    for section in SECTIONS:
        manifest = {
            "format": 1,
            "section": section,
            "variants": {},
            "source": "R-Type World ROM geometry + original M72 palette RAM",
            "algorithm": "padded batch xBRZ 1.9 x6 + per-cell Lanczos",
        }
        for variant, frame in VARIANTS:
            palette = scene.palette_from_ram(
                (CAPTURE / f"frame_{frame:06d}_palette0.bin").read_bytes(),
                (CAPTURE / f"frame_{frame:06d}_palette1.bin").read_bytes())
            variant_record = {"palette_frame": frame, "layers": {}}
            manifest["variants"][variant.lower()] = variant_record
            for short, graphics, masks in (
                    ("FG", regions["tiles0"], scene.FG_LAYER0_MASK),
                    ("BG", regions["tiles1"], scene.BG_LAYER1_MASK)):
                source_lookup = ASSETS / f"STAGE1_S{section}_{short}_LOOKUP.bin"
                states = read_states(source_lookup)
                item = {
                    "name": f"S{section}_BOSS_{variant}_{short}",
                    "graphics": graphics,
                    "masks": masks,
                    "states": {state: (frame, frame) for state in states},
                    "palettes": {frame: palette},
                }
                mapping, blob, stats = batch.render_batch(item)
                lookup = bytearray(struct.pack("<H", len(states)))
                for state in states:
                    lookup += struct.pack("<HHH", state[0], state[1], mapping[state])
                atlas_path = ASSETS / (
                    f"STAGE1_S{section}_{short}_{variant}_ATLAS_ARGB4444.bin")
                lookup_path = ASSETS / (
                    f"STAGE1_S{section}_{short}_{variant}_LOOKUP.bin")
                atlas_path.write_bytes(blob)
                lookup_path.write_bytes(lookup)
                variant_record["layers"][short.lower()] = {
                    "states": len(states),
                    "glyphs": len(blob) // batch.stage.GLYPH_BYTES,
                    "atlas": str(atlas_path.relative_to(ROOT)),
                    "lookup": str(lookup_path.relative_to(ROOT)),
                    "atlas_sha256": hashlib.sha256(blob).hexdigest(),
                    "lookup_sha256": hashlib.sha256(lookup).hexdigest(),
                    "batch": stats,
                }
        path = ASSETS / f"STAGE1_S{section}_BOSS_PALETTE_manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
