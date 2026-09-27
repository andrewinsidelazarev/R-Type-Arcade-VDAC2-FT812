#!/usr/bin/env python3
"""Оффлайн-конверсия анимации R-9 и индикатора Beam из arcade ROM.

Коды $20..$24 выбираются оригиналом через ``pitch >> 3``. Полный аппаратный
кадр 32x16 сначала увеличивается xBRZ 1.9 в 6 раз, затем приводится Lanczos к
логическому масштабу 640x480. Во время игры готовые изображения не масштабируются.
"""
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
import m72_sprite_assets as assets
import m72_tile_atlas as tile_atlas
import xbrz_offline


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "player_up_trace"
BEAM_CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "beam_charge_trace"
BEAM_METER_CAPTURE = (
    ROOT / "Build" / "Arcade" / "MAME" / "beam_meter_exact_trace")
OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "Player"
FRAME = 1190
BEAM_BOX = (132, 242, 260, 247)
CHARGE_CODES = (0x220, 0x222, 0x224, 0x226, 0x230, 0x232, 0x234, 0x236)
HUD_NATIVE_Y = 240
HUD_NATIVE_H = 16
HUD_SCROLL_X = 0
HUD_SCROLL_Y = 0x90
HUD_SCORE_CODES = tuple(range(0x30, 0x3A))
HUD_P1_LABEL_CODES = (0x61, 0x62, 0x63, 0x64)
# `$F07B`: запас жизней — (жизни - 1) записей кода $006A с байта $0024 слоя 0;
# перед ними `$F061` заполняет поле пустым кодом $0019 с атрибутом $008F.
HUD_LIFE_CODES = (0x6A,)
HUD_LIFE_FIRST_RECORD = 0x0024
HUD_LIFE_MAX_RECORDS = 7
HUD_BLANK_CODE = 0x19


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    capture = scene.Capture.load(CAPTURE, FRAME, FRAME)
    graphics = scene.Graphics.load()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    blob = bytearray()
    records: list[dict[str, object]] = []

    def add_sprite(kind: str, name: str, code: int, attr: int,
                   extra: dict[str, object] | None = None) -> None:
        width = 1 << ((attr >> 14) & 3)
        height = 1 << ((attr >> 12) & 3)
        sprite = scene.SpriteObject(
            offset=0, code=code, attr=attr, color=attr & 15,
            sx=0, sy=0, flip_x=bool(attr & 0x0800),
            flip_y=bool(attr & 0x0400), width=width, height=height,
        )
        native = scene.sprite_object_image(sprite, graphics, capture.palette)
        target = (
            assets.round_ratio(native.width, 5, 3),
            assets.round_ratio(native.height, 15, 8),
        )
        logical_full = xbrz_offline.upscale_image(native, target, factor=6)
        bbox = logical_full.getchannel("A").getbbox()
        if bbox is None:
            raise ValueError(f"R-9 code ${code:04X} is transparent")
        logical = logical_full.crop(bbox)
        packed = assets.pack_argb4444(logical)
        while len(blob) & 3:
            blob.append(0)
        offset = len(blob)
        blob.extend(packed)
        png = f"{name}.png"
        logical.save(OUTPUT / png)
        record: dict[str, object] = {
            "kind": kind,
            "code": code,
            "attr": attr,
            "crop_left": bbox[0],
            "crop_top": bbox[1],
            "width": logical.width,
            "height": logical.height,
            "offset": offset,
            "length": len(packed),
            "png": png,
            "png_sha256": sha256((OUTPUT / png).read_bytes()),
            "argb4444_sha256": sha256(packed),
        }
        if extra:
            record.update(extra)
        records.append(record)

    for pitch_index, code in enumerate(range(0x20, 0x25)):
        add_sprite("pitch", f"R9_PITCH_{pitch_index}_C{code:04X}", code, 0x4000, {
            "pitch_index": pitch_index,
            "pitch_min": pitch_index * 8,
            "pitch_max": min(39, pitch_index * 8 + 7),
        })
    pitch_blob_size = len(blob)

    add_sprite("launch", "R9_LAUNCH_PLASMA_A_C0A23", 0x0A23, 0x4001,
               {"native_dx": -31, "native_dy": 2})
    add_sprite("launch", "R9_LAUNCH_EXHAUST_C0AA2", 0x0AA2, 0x5001,
               {"native_dx": -31, "native_dy": -6})
    add_sprite("launch", "R9_LAUNCH_EXHAUST_C0AA4", 0x0AA4, 0x5001,
               {"native_dx": -31, "native_dy": -6})
    add_sprite("launch", "R9_LAUNCH_EXHAUST_C0AA6", 0x0AA6, 0x5001,
               {"native_dx": -31, "native_dy": -6})
    charge_blob_start = len(blob)
    for phase, code in enumerate(CHARGE_CODES):
        add_sprite("charge", f"R9_CHARGE_{phase}_C{code:04X}", code, 0x5006, {
            "phase": phase, "native_dx": 32, "native_dy": -4,
        })
    charge_blob_end = len(blob)

    # `$4FD2…$50C9` строит полосу из отдельных full/partial tiles, а не
    # обрезает готовое полное изображение. Детерминированный MAME-прогон
    # хранит каждый реально достижимый even charge 0..$80; вся xBRZ/Lanczos
    # обработка остаётся offline и runtime выбирает одну готовую картинку.
    charge_frames: dict[int, int] = {}
    for workram in sorted(BEAM_METER_CAPTURE.glob("frame_*_workram.bin")):
        frame = int(workram.name[6:12])
        charge = workram.read_bytes()[0x003D]
        if charge <= 0x80 and not (charge & 1):
            charge_frames.setdefault(charge, frame)
    expected_charges = set(range(0, 0x81, 2))
    if set(charge_frames) != expected_charges:
        missing = sorted(expected_charges - set(charge_frames))
        raise ValueError(f"неполный Beam meter capture, missing={missing}")
    for charge in sorted(charge_frames):
        frame = charge_frames[charge]
        source = Image.open(BEAM_METER_CAPTURE /
                            f"frame_{frame:06d}_native.png").convert("RGBA")
        native = source.crop(BEAM_BOX)
        logical = xbrz_offline.upscale_image(native, (213, 9), factor=6)
        packed = assets.pack_argb4444(logical)
        while len(blob) & 3:
            blob.append(0)
        offset = len(blob)
        blob.extend(packed)
        png = f"BEAM_METER_C{charge:03d}.png"
        logical.save(OUTPUT / png)
        records.append({
            "kind": "beam_meter", "charge": charge,
            "reference_frame": frame,
            "native_box": BEAM_BOX, "width": logical.width,
            "height": logical.height, "offset": offset, "length": len(packed),
            "png": png, "png_sha256": sha256((OUTPUT / png).read_bytes()),
            "argb4444_sha256": sha256(packed),
        })

    # Последние 16 строк M72 выводит с отдельным raster-scroll: fg_x=0,
    # fg_y=$90. Это неподвижный HUD (BEAM, рамка, HI и счёт), который нельзя
    # брать из прокручиваемого слоя уровня. Pen 0 у тайлов остаётся прозрачным,
    # поэтому под буквами и рамкой продолжает быть видна нижняя декорация.
    hud_capture = scene.Capture.load(BEAM_CAPTURE, 1248, 1248)
    # Значки жизней захвата (два при трёх жизнях) — живые записи `$F07B`, как счёт
    # и `1P-`: в неподвижный HUD идёт то же поле, очищенное `$F061` кодом $0019.
    hud_vram = bytearray(hud_capture.vram0)
    for record in range(HUD_LIFE_FIRST_RECORD,
                        HUD_LIFE_FIRST_RECORD + HUD_LIFE_MAX_RECORDS * 4, 4):
        if int.from_bytes(hud_vram[record:record + 2], "little") in HUD_LIFE_CODES:
            hud_vram[record:record + 2] = HUD_BLANK_CODE.to_bytes(2, "little")
    hud_native = Image.new("RGBA", (scene.VISIBLE_WIDTH, HUD_NATIVE_H),
                           (0, 0, 0, 0))
    hud_pixels = hud_native.load()
    for hud_y in range(HUD_NATIVE_H):
        visible_y = HUD_NATIVE_Y + hud_y
        for x in range(scene.VISIBLE_WIDTH):
            pixel = scene.tile_pixel(
                bytes(hud_vram), graphics.tiles0, x, visible_y,
                HUD_SCROLL_X, HUD_SCROLL_Y,
            )
            if pixel.pen:
                hud_pixels[x, hud_y] = hud_capture.palette[pixel.palette_index]
    hud_logical = xbrz_offline.upscale_image(hud_native, (640, 30), factor=6)
    hud_png = "HUD_FIXED.png"
    hud_logical.save(OUTPUT / hud_png)
    hud_packed = assets.pack_argb4444(hud_logical)
    while len(blob) & 3:
        blob.append(0)
    hud_offset = len(blob)
    blob.extend(hud_packed)
    records.append({
        "kind": "hud", "native_y": HUD_NATIVE_Y,
        "native_height": HUD_NATIVE_H,
        "scroll_x": HUD_SCROLL_X, "scroll_y": HUD_SCROLL_Y,
        "width": hud_logical.width, "height": hud_logical.height,
        "offset": hud_offset, "length": len(hud_packed),
        "png": hud_png,
        "png_sha256": sha256((OUTPUT / hud_png).read_bytes()),
        "argb4444_sha256": sha256(hud_packed),
    })

    # Счёт, мигающий `1P-` и значки запаса жизней — живые записи слоя 0, а не часть
    # неподвижного HUD. Их тайлы с игровой палитрой $0F готовятся здесь; Python и FT812
    # только ставят готовые изображения 14x15.
    for kind, codes in (("hud_score", HUD_SCORE_CODES),
                        ("hud_p1_label", HUD_P1_LABEL_CODES),
                        ("hud_life", HUD_LIFE_CODES)):
        for ordinal, code in enumerate(codes):
            native = graphics.tiles0[code * 64:(code + 1) * 64]
            logical = tile_atlas.upscale_cell(
                native, 8, 8, hud_capture.palette,
                tile_atlas.TILE_PALETTE_BASE + 0x0F * 16,
                (tile_atlas.TILE_W, tile_atlas.TILE_H),
            )
            if kind == "hud_score":
                png = f"HUD_SCORE_{ordinal}_C{code:04X}_P15.png"
            elif kind == "hud_life":
                png = f"HUD_LIFE_C{code:04X}_P15.png"
            else:
                png = f"HUD_P1_LABEL_{ordinal}_C{code:04X}_P15.png"
            logical.save(OUTPUT / png)
            packed = assets.pack_argb4444(logical)
            while len(blob) & 3:
                blob.append(0)
            offset = len(blob)
            blob.extend(packed)
            records.append({
                "kind": kind, "ordinal": ordinal, "code": code,
                "palette": 0x0F, "width": logical.width,
                "height": logical.height, "offset": offset,
                "length": len(packed), "png": png,
                "png_sha256": sha256((OUTPUT / png).read_bytes()),
                "argb4444_sha256": sha256(packed),
            })

    binary = bytes(blob)
    (OUTPUT / "R9_PITCH_ARGB4444.bin").write_bytes(binary[:pitch_blob_size])
    (OUTPUT / "R9_PLAYER_ARGB4444.bin").write_bytes(binary)
    charge_binary = binary[charge_blob_start:charge_blob_end]
    (OUTPUT / "R9_CHARGE_ARGB4444.bin").write_bytes(charge_binary)
    manifest = {
        "format": 1,
        "source": "R-Type World arcade ROM through MAME 0.288 palette",
        "reference_capture": str(CAPTURE.resolve()),
        "reference_frame": FRAME,
        "algorithm": "xBRZ 1.9 6x, then Lanczos to 5/3 x 15/8",
        "selection": "sprite_code = 0x20 + (pitch >> 3), pitch clamped 0..39",
        "neutral_pitch": 20,
        "launch_reference_frames": [898, 1077],
        "beam": {
            "charge_first_visible": 10,
            "phase_duration": 4,
            "meter_native_box": BEAM_BOX,
            "meter_fill_pixels_per_frame": 2,
            "full_charge": 67,
            "meter_exact_charges": list(range(0, 0x81, 2)),
            "meter_reference_capture": str(BEAM_METER_CAPTURE.resolve()),
            "hud_native_y": HUD_NATIVE_Y,
            "hud_scroll": [HUD_SCROLL_X, HUD_SCROLL_Y],
        },
        "records": records,
        "binary": {
            "file": "R9_PLAYER_ARGB4444.bin",
            "size": len(binary),
            "sha256": sha256(binary),
        },
        "charge_binary": {
            "file": "R9_CHARGE_ARGB4444.bin",
            "source_offset": charge_blob_start,
            "size": len(charge_binary),
            "sha256": sha256(charge_binary),
        },
    }
    (OUTPUT / "r9_pitch.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"R-9 player assets: {len(records)}, blob={len(binary)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
