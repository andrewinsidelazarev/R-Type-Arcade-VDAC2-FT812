#!/usr/bin/env python3
"""Build every ROM-defined Wave Cannon power/phase as an offline 640x480 asset."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_scene as scene
import xbrz_offline


ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "Sprites" / "WavePower"
REFERENCE = ROOT / "Build" / "Arcade" / "Audio" / "wave_shot" / "wave"

POWER_TABLE_ES = 0x188C
DESCRIPTOR_POINTERS_ES = 0x1898
DESCRIPTOR_RECORDS = 3
PALETTE = 8
POWERS = (4, 8, 12, 16, 20)
REFERENCE_SCREEN_FRAMES = (1321, 1322)
REFERENCE_STATE_FRAMES = (1319, 1320)
REFERENCE_MAX_PNGS = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
    / "asset_15_wave_0_p8_80x16.png",
    ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
    / "asset_16_wave_1_p8_80x16.png",
)


def es_u16(rom: bytes, address: int) -> int:
    offset = 0x10000 + address
    return rom[offset] | rom[offset + 1] << 8


def signed_byte(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def round_ratio(value: int, numerator: int, denominator: int) -> int:
    return (value * numerator + denominator // 2) // denominator


def descriptor_objects(rom: bytes, pointer: int) -> list[tuple[int, int, scene.SpriteObject]]:
    """Decode the three six-byte entries consumed by the ROM sprite compositor."""
    objects: list[tuple[int, int, scene.SpriteObject]] = []
    for index in range(DESCRIPTOR_RECORDS):
        offset = 0x10000 + pointer + index * 6
        dx = signed_byte(rom[offset])
        dy = signed_byte(rom[offset + 1])
        code = rom[offset + 2] | rom[offset + 3] << 8
        raw_attr = rom[offset + 4] | rom[offset + 5] << 8
        attr = raw_attr | PALETTE
        width = 1 << ((attr >> 14) & 3)
        height = 1 << ((attr >> 12) & 3)
        objects.append((dx, dy, scene.SpriteObject(
            offset=index * 4,
            code=code,
            attr=attr,
            color=attr & 0x0F,
            sx=scene.RAW_VISIBLE_X + dx,
            sy=dy,
            flip_x=bool(attr & 0x0800),
            flip_y=bool(attr & 0x0400),
            width=width,
            height=height,
        )))
    return objects


def render_descriptor(
        objects: list[tuple[int, int, scene.SpriteObject]],
        graphics: scene.Graphics,
        palette: list[tuple[int, int, int, int]],
) -> tuple[Image.Image, tuple[int, int], list[int]]:
    # `$001F` is the transparent placeholder used by the smaller powers.
    visible = [(dx, dy, obj) for dx, dy, obj in objects if obj.code != 0x001F]
    left = min(dx for dx, _, _ in visible)
    top = min(dy for _, dy, _ in visible)
    right = max(dx + obj.pixel_width for dx, _, obj in visible)
    bottom = max(dy + obj.pixel_height for _, dy, obj in visible)
    native = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    for dx, dy, obj in visible:
        native.alpha_composite(
            scene.sprite_object_image(obj, graphics, palette),
            (dx - left, dy - top),
        )
    return native, (left, top), [obj.code for _, _, obj in visible]


def main() -> int:
    rom = ROM_PATH.read_bytes()
    if len(rom) != 0x100000:
        raise ValueError("unexpected R-Type maincpu region size")
    powers = tuple(es_u16(rom, POWER_TABLE_ES + index * 2) for index in range(1, 6))
    if powers != POWERS:
        raise ValueError(f"unexpected ES:$188C power table: {powers}")

    graphics = scene.Graphics.load()
    captures = [scene.Capture.load(REFERENCE, screen, state)
                for screen, state in zip(REFERENCE_SCREEN_FRAMES,
                                         REFERENCE_STATE_FRAMES, strict=True)]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for power_index, power in enumerate(POWERS):
        table_offset = (power - 1) & 0x1C
        for phase in range(2):
            pointer = es_u16(
                rom, DESCRIPTOR_POINTERS_ES + table_offset + phase * 2)
            objects = descriptor_objects(rom, pointer)
            native, origin, codes = render_descriptor(
                objects, graphics, captures[phase].palette)
            target = (round_ratio(native.width, 5, 3),
                      round_ratio(native.height, 15, 8))
            logical = xbrz_offline.upscale_image(native, target, factor=6)
            name = f"wave_power_{power:02d}_phase_{phase}.png"
            path = OUTPUT / name
            logical.save(path)
            records.append({
                "power": power,
                "phase": phase,
                "descriptor_pointer": pointer,
                "codes": codes,
                "native_origin": list(origin),
                "native_size": list(native.size),
                "logical_size": list(logical.size),
                "rgba_sha256": sha256(logical.tobytes()),
                "path": str(path.resolve()),
            })

            if power_index == len(POWERS) - 1:
                reference = Image.open(REFERENCE_MAX_PNGS[phase]).convert("RGBA")
                if logical.size != reference.size or logical.tobytes() != reference.tobytes():
                    raise ValueError(
                        f"generated maximum Wave phase {phase} differs from existing MAME asset")

    manifest = {
        "format": 1,
        "source": str(ROM_PATH.resolve()),
        "power_table": {"es": POWER_TABLE_ES, "values": list(POWERS)},
        "descriptor_pointer_table_es": DESCRIPTOR_POINTERS_ES,
        "palette_capture": str(REFERENCE.resolve()),
        "conversion": "xBRZ 1.9 6x, then Lanczos to 640x480 logical scale",
        "records": records,
    }
    manifest_path = OUTPUT / "wave_power_assets.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wave powers {POWERS}, {len(records)} exact phase assets -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
