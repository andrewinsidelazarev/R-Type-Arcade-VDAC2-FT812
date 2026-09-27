#!/usr/bin/env python3
"""Build immutable HQ sprite banks for stable Stage 1 resource types.

Geometry comes from the complete offline xBRZ6+Lanczos atlas.  The hardware
pen colors are taken once from an original M72 palette-RAM checkpoint where
the ROM resource table identifies the type/slot pair.  Runtime never reads a
MAME capture and performs neither scaling nor recoloring.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_full_hq_assets
import m72_scene


FULL_HQ = ROOT / "Assets" / "Converted" / "Arcade" / "FullHQ"
OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "ResourceHQ"
CAPTURES = (
    ROOT / "Build" / "Arcade" / "MAME" / "stage1_invincible_trace",
    # Exact `$55E9 -> $586A` carrier/drop capture; supplies resource type $0A.
    ROOT / "Build" / "Arcade" / "MAME" / "powerup_pickup_exact",
)
STABLE_TYPES = (
    0x01, 0x02, 0x09, 0x0A, 0x0C, 0x0D, 0x0F, 0x10, 0x13, 0x14,
    0x15, 0x16, 0x17,
    0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x2B, 0x2C, 0x3C, 0x3F,
    0x55, 0x56, 0x59, 0x5C,
)


def sprite_palette(data: bytes, slot: int) -> np.ndarray:
    """Return the literal 16-pen sprite palette as RGBA8888.

    Resource banks used to be recoloured from a finished HQ palette bank.
    That inverse operation is ambiguous whenever two hardware pens had the
    same RGB value in the source checkpoint.  Dobkeratops type `$17` exposed
    the bug: the opaque centre pen of cells `$175..$177` was reconstructed as
    green.  Building from decoded pen indices keeps the identity of every pen
    through xBRZ and makes the conversion lossless with respect to the ROM.
    """
    words = np.frombuffer(data, dtype="<u2")
    colors = np.empty((16, 4), dtype=np.uint8)
    for pen in range(16):
        index = slot * 16 + pen
        red = int(words[index]) & 31
        green = int(words[index + 0x200]) & 31
        blue = int(words[index + 0x400]) & 31
        colors[pen] = (
            (red << 3) | (red >> 2),
            (green << 3) | (green >> 2),
            (blue << 3) | (blue >> 2),
            255,
        )
    return colors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--types", nargs="*", type=lambda value: int(value, 0),
        help="optional resource types to rebuild (default: every stable type)")
    parser.add_argument("--sprite-chunk", type=int, default=1024)
    args = parser.parse_args()
    selected_types = tuple(STABLE_TYPES if args.types is None else args.types)
    unknown = set(selected_types) - set(STABLE_TYPES)
    if unknown:
        raise ValueError(f"неподдерживаемые resource types: {sorted(unknown)}")

    occurrences: dict[int, tuple[int, int, Path, Path]] = {}
    for capture in CAPTURES:
        for workram_path in sorted(capture.glob("frame_*_workram.bin")):
            frame = int(workram_path.name.split("_")[1])
            palette_path = capture / f"frame_{frame:06d}_palette0.bin"
            if not palette_path.is_file():
                continue
            workram = workram_path.read_bytes()
            for slot in range(16):
                resource_type = workram[0x2114 + slot * 2]
                if (resource_type in STABLE_TYPES and
                        resource_type not in occurrences):
                    occurrences[resource_type] = (
                        frame, slot, workram_path, palette_path)

    missing = set(selected_types) - set(occurrences)
    if missing:
        raise ValueError(f"resource types отсутствуют в checkpoint: {sorted(missing)}")
    graphics = m72_scene.Graphics.load()
    sprite_cells = np.frombuffer(
        graphics.sprites, dtype=np.uint8).reshape(-1, 16, 16)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "stage1_resource_hq_manifest.json"
    if args.types is not None and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"types": {}}
    manifest.update({
        "format": 2,
        "geometry": (
            "decoded M72 sprite pens -> isolated xBRZ 1.9 x6 -> "
            "Pillow Lanczos"),
        "color_source": (
            "original M72 palette RAM paired with ROM resource table; "
            "direct pen-index conversion"),
        "cell_size": [27, 30],
        "cell_format": "ARGB4444 little-endian",
    })
    type_manifest = manifest.setdefault("types", {})
    for resource_type in selected_types:
        frame, slot, workram_path, palette_path = occurrences[resource_type]
        path = OUTPUT / f"RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin"
        conversion = m72_full_hq_assets.convert_bank(
            f"SPRITES/TYPE{resource_type:02X}", sprite_cells,
            sprite_palette(palette_path.read_bytes(), slot),
            (27, 30), args.sprite_chunk, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        type_manifest[f"{resource_type:02X}"] = {
            "path": str(path.relative_to(ROOT)),
            "frame": frame,
            "slot": slot,
            "conversion": "direct decoded pen indices",
            "workram_sha256": hashlib.sha256(workram_path.read_bytes()).hexdigest(),
            "palette_sha256": hashlib.sha256(palette_path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "sha256": digest,
            "chunks": conversion["chunks"],
        }
        print(f"type ${resource_type:02X}: frame {frame}, slot {slot}, {digest}")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
