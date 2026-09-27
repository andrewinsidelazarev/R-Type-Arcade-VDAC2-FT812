#!/usr/bin/env python3
"""Сборка подлинных спрайтов M72 из детерминированного захвата MAME.

Каждый составной объект декодируется из предоставленного arcade ROM по точной
разметке sprite RAM M72. Изображение RGBA аппаратного размера заранее проходит
xBRZ 1.9 в 6x и Lanczos до логического масштаба 640x480, обрезается, упаковывается
в FT812 ARGB4444 и дедуплицируется. FT812 затем выполняет только финальный
NEAREST-масштаб 640x480 -> 1024x768.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import m72_scene as scene
import xbrz_offline


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "timing_probe"
DEFAULT_SHOT_CAPTURE = (
    ROOT / "Build" / "Arcade" / "Audio" / "wave_shot" / "fire"
)
DEFAULT_WAVE_CAPTURE = (
    ROOT / "Build" / "Arcade" / "Audio" / "wave_shot" / "wave"
)
DEFAULT_ENEMY_CAPTURE = (
    ROOT / "Build" / "Arcade" / "MAME" / "stage1_perframe_ref"
)
DEFAULT_ENEMY_FRAME = 1500
DEFAULT_SHOT_FRAME = 1253
DEFAULT_SHOT_NEXT_FRAME = 1254
DEFAULT_WAVE_FRAME = 1319
DEFAULT_WAVE_NEXT_FRAME = 1320
DEFAULT_OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
DEFAULT_INCLUDE = ROOT / "Source" / "ASM" / "generated_m72_sprites.inc"
PLAYER_OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "Player"
FT_ARGB4 = 6
M72_R9_CODE = 0x0022
M72_R9_PALETTE = 0
M72_PLAYER_SHOT_CODE = 0x08F8
M72_PLAYER_SHOT_PALETTE = 0
M72_WAVE_PALETTE = 8
M72_WAVE_PHASE_CODES = (
    (0x0054, 0x0055, 0x0016),
    (0x0056, 0x0057, 0x0017),
)
M72_WAVE_RELEASE_CODES = (0x0013, 0x0043, 0x0044, 0x0045)
M72_WAVE_RELEASE_OFFSETS = (0, 2, 4, 6)
M72_WAVE_RELEASE_DURATIONS = (2, 2, 2, 1)
M72_WAVE_MIN_CHARGE_FRAMES = 67
M72_WAVE_APPEAR_DELAY = 2
M72_SCREEN_STATE_DELAY = 2
M72_STAGE1_ENEMIES = (
    ("PATROL", 0x0132, 7),
    ("RED", 0x00F4, 5),
    ("RED_FLIP", 0x0161, 5),
    ("WALKER", 0x0100, 8),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def round_ratio(value: int, numerator: int, denominator: int) -> int:
    magnitude = (abs(value) * numerator + denominator // 2) // denominator
    return magnitude if value >= 0 else -magnitude


def ceil_ratio(value: int, numerator: int, denominator: int) -> int:
    return (value * numerator + denominator - 1) // denominator


def pack_argb4444(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA").tobytes()
    packed = bytearray(len(rgba) // 2)
    out = 0
    for offset in range(0, len(rgba), 4):
        red, green, blue, alpha = rgba[offset:offset + 4]
        a4 = (alpha * 15 + 127) // 255
        r4 = (red * 15 + 127) // 255
        g4 = (green * 15 + 127) // 255
        b4 = (blue * 15 + 127) // 255
        value = (a4 << 12) | (r4 << 8) | (g4 << 4) | b4
        struct.pack_into("<H", packed, out, value)
        out += 2
    return bytes(packed)


def object_visible(sprite: scene.SpriteObject) -> bool:
    return (
        sprite.visible_x < scene.VISIBLE_WIDTH
        and sprite.visible_x + sprite.pixel_width > 0
        and sprite.sy < scene.VISIBLE_HEIGHT
        and sprite.sy + sprite.pixel_height > 0
    )


def checker(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGBA", size, (38, 38, 38, 255))
    draw = ImageDraw.Draw(image)
    step = 8
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if ((x // step) ^ (y // step)) & 1:
                draw.rectangle((x, y, x + step - 1, y + step - 1),
                               fill=(70, 70, 70, 255))
    return image


def contact_sheet(objects: Sequence[dict[str, object]], output: Path) -> None:
    columns = 4
    cell_w, cell_h = 230, 150
    rows = (len(objects) + columns - 1) // columns
    sheet = checker((columns * cell_w, max(1, rows) * cell_h))
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(objects):
        col, row = index % columns, index // columns
        x0, y0 = col * cell_w, row * cell_h
        sprite = item["sprite"]
        assert isinstance(sprite, scene.SpriteObject)
        image = item["native"]
        assert isinstance(image, Image.Image)
        preview = image.copy()
        preview.thumbnail((210, 105), Image.Resampling.NEAREST)
        sheet.alpha_composite(preview, (x0 + 10, y0 + 28))
        draw.text((x0 + 5, y0 + 4),
                  f"off {sprite.offset:03X} code {sprite.code:04X} "
                  f"pal {sprite.color:X} {sprite.pixel_width}x{sprite.pixel_height}",
                  fill=(255, 255, 255, 255))
        draw.text((x0 + 5, y0 + 132),
                  f"visible ({sprite.visible_x},{sprite.sy}) "
                  f"flip {int(sprite.flip_x)}{int(sprite.flip_y)}",
                  fill=(210, 220, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(output)


def command_words(asset: dict[str, object]) -> list[int]:
    address = int(asset["offset"])
    stride = int(asset["stride"])
    height = int(asset["height"])
    physical_width = int(asset["physical_width"])
    physical_height = int(asset["physical_height"])
    return [
        0x01000000 | address,
        0x28000000 | (((stride >> 10) & 3) << 2) | ((height >> 9) & 3),
        0x07000000 | (FT_ARGB4 << 19) | ((stride & 0x3FF) << 9) | (height & 0x1FF),
        0x29000000 | (((physical_width >> 9) & 3) << 2)
        | ((physical_height >> 9) & 3),
        0x08000000 | ((physical_width & 0x1FF) << 9)
        | (physical_height & 0x1FF),
    ]


def register_asset(sprite: scene.SpriteObject, native: Image.Image,
                   assets: list[dict[str, object]],
                   asset_by_key: dict[tuple[tuple[int, int], str], int],
                   blob: bytearray, output: Path,
                   *, name_override: str | None = None) -> int:
    """Преобразовать объект M72 и вернуть индекс дедуплицированного ассета."""
    native_bytes = native.tobytes()
    key = (native.size, sha256_bytes(native_bytes))
    existing = asset_by_key.get(key)
    if existing is not None:
        return existing

    target = (
        round_ratio(native.width, 5, 3),
        round_ratio(native.height, 15, 8),
    )
    logical_full = xbrz_offline.upscale_image(native, target, factor=6)
    alpha_bbox = logical_full.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise ValueError(f"M72 object ${sprite.code:04X} is fully transparent")
    logical = logical_full.crop(alpha_bbox)
    packed = pack_argb4444(logical)
    while len(blob) & 3:
        blob.append(0)
    offset = len(blob)
    blob.extend(packed)
    asset_index = len(assets)
    asset_by_key[key] = asset_index
    name = name_override or (
        f"c{sprite.code:04x}_p{sprite.color:x}_"
        f"{sprite.pixel_width}x{sprite.pixel_height}_"
        f"f{int(sprite.flip_x)}{int(sprite.flip_y)}"
    )
    png_path = output / f"asset_{asset_index:02d}_{name}.png"
    logical.save(png_path)
    assets.append({
        "index": asset_index,
        "name": name,
        "representative_spriteram_offset": sprite.offset,
        "code": sprite.code,
        "attr": sprite.attr,
        "palette": sprite.color,
        "native_width": native.width,
        "native_height": native.height,
        "native_rgba_sha256": key[1],
        "logical_full_width": logical_full.width,
        "logical_full_height": logical_full.height,
        "crop_left": alpha_bbox[0],
        "crop_top": alpha_bbox[1],
        "crop_right": alpha_bbox[2],
        "crop_bottom": alpha_bbox[3],
        "width": logical.width,
        "height": logical.height,
        "stride": logical.width * 2,
        "physical_width": ceil_ratio(logical.width, 8, 5),
        "physical_height": ceil_ratio(logical.height, 8, 5),
        "offset": offset,
        "length": len(packed),
        "png": str(png_path.resolve()),
        "png_sha256": sha256_file(png_path),
        "argb4444_sha256": sha256_bytes(packed),
    })
    return asset_index


def register_logical_asset(image: Image.Image, name: str,
                           assets: list[dict[str, object]],
                           blob: bytearray, output: Path) -> int:
    """Добавить уже увеличенный Python-ассет без повторного xBRZ/Lanczos."""
    logical = image.convert("RGBA")
    if logical.getchannel("A").getbbox() is None:
        raise ValueError(f"готовый ассет {name} полностью прозрачен")
    packed = pack_argb4444(logical)
    while len(blob) & 3:
        blob.append(0)
    offset = len(blob)
    blob.extend(packed)
    asset_index = len(assets)
    png_path = output / f"asset_{asset_index:02d}_{name}.png"
    logical.save(png_path)
    assets.append({
        "index": asset_index,
        "name": name,
        "representative_spriteram_offset": None,
        "code": None,
        "attr": None,
        "palette": None,
        "native_width": None,
        "native_height": None,
        "native_rgba_sha256": None,
        "logical_full_width": logical.width,
        "logical_full_height": logical.height,
        "crop_left": 0,
        "crop_top": 0,
        "crop_right": logical.width,
        "crop_bottom": logical.height,
        "width": logical.width,
        "height": logical.height,
        "stride": logical.width * 2,
        "physical_width": ceil_ratio(logical.width, 8, 5),
        "physical_height": ceil_ratio(logical.height, 8, 5),
        "offset": offset,
        "length": len(packed),
        "png": str(png_path.resolve()),
        "png_sha256": sha256_file(png_path),
        "argb4444_sha256": sha256_bytes(packed),
    })
    return asset_index


def register_exact_player_assets(assets: list[dict[str, object]],
                                 blob: bytearray, output: Path
                                 ) -> dict[str, object]:
    """Включить пять наклонов R-9 и четыре launch-эффекта из Python."""
    manifest_path = PLAYER_OUTPUT / "r9_pitch.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["records"]
    pitch_records = sorted(
        (record for record in records if record["kind"] == "pitch"),
        key=lambda record: int(record["pitch_index"]),
    )
    launch_code_order = (0x0A23, 0x0AA2, 0x0AA4, 0x0AA6)
    launch_by_code = {
        int(record["code"]): record
        for record in records if record["kind"] == "launch"
    }
    if (len(pitch_records) != 5 or
            set(launch_by_code) != set(launch_code_order)):
        raise ValueError(
            "r9_pitch.json не содержит 5 pitch и 4 launch записей")

    def add(record: dict[str, object], name: str) -> int:
        source = PLAYER_OUTPUT / str(record["png"])
        if sha256_file(source) != str(record["png_sha256"]):
            raise ValueError(f"контрольная сумма готового R-9 ассета: {source}")
        image = Image.open(source).convert("RGBA")
        if image.size != (int(record["width"]), int(record["height"])):
            raise ValueError(f"размер готового R-9 ассета: {source}")
        return register_logical_asset(image, name, assets, blob, output)

    pitch_indices = [
        add(record, f"r9_pitch_{int(record['pitch_index'])}_exact")
        for record in pitch_records
    ]
    launch_indices = [
        add(launch_by_code[code], f"r9_launch_{code:04x}_exact")
        for code in launch_code_order
    ]
    return {
        "pitch_asset_indices": pitch_indices,
        "pitch_crop_top": [int(record["crop_top"])
                           for record in pitch_records],
        "launch_asset_indices": launch_indices,
        "launch_codes": list(launch_code_order),
        "manifest": str(manifest_path.resolve()),
    }


def unique_object(capture: scene.Capture, code: int, palette: int,
                  label: str) -> scene.SpriteObject:
    matches = [
        sprite for sprite in scene.sprite_objects(capture.spriteram)
        if sprite.code == code and sprite.color == palette
        and object_visible(sprite)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {label} code=${code:04X}/palette={palette}, "
            f"found {len(matches)}"
        )
    return matches[0]


def compose_horizontal_objects(
        capture: scene.Capture, graphics: scene.Graphics,
        codes: Sequence[int], palette: int, label: str,
) -> tuple[scene.SpriteObject, Image.Image, int, int, list[scene.SpriteObject]]:
    """Собрать соседние аппаратные объекты M72 в один прозрачный ряд."""
    objects = [
        unique_object(capture, code, palette, f"{label} ${code:04X}")
        for code in codes
    ]
    if any(sprite.flip_x or sprite.flip_y for sprite in objects):
        raise ValueError(f"{label}: неожиданное отражение составного объекта")
    native_x = min(sprite.visible_x for sprite in objects)
    native_y = min(sprite.sy for sprite in objects)
    native_right = max(
        sprite.visible_x + sprite.pixel_width for sprite in objects)
    native_bottom = max(
        sprite.sy + sprite.pixel_height for sprite in objects)
    expected_x = native_x
    for sprite in objects:
        if sprite.sy != native_y or sprite.visible_x != expected_x:
            raise ValueError(f"{label}: части не образуют непрерывный ряд")
        expected_x += sprite.pixel_width
    image = Image.new(
        "RGBA", (native_right - native_x, native_bottom - native_y),
        (0, 0, 0, 0),
    )
    for sprite in objects:
        part = scene.sprite_object_image(sprite, graphics, capture.palette)
        image.alpha_composite(
            part, (sprite.visible_x - native_x, sprite.sy - native_y))
    return objects[0], image, native_x, native_y, objects


def generate_include(assets: Sequence[dict[str, object]],
                     instances: Sequence[dict[str, object]],
                     dynamic: dict[str, dict[str, object]],
                     player: dict[str, object],
                     shot: dict[str, object], wave: dict[str, object],
                     enemies: dict[str, dict[str, object]],
                     blob_size: int,
                     path: Path) -> None:
    lines = [
        "; Сгенерировано m72_sprite_assets.py; вручную не редактировать.",
        "; Подлинные объекты M72: предварительные xBRZ6 + Lanczos, FT812 ARGB4444.",
        "M72_SPR_BLOB_BASE      EQU $000000",
        f"M72_SPR_BLOB_SIZE      EQU {blob_size}",
        f"M72_SPR_ASSET_COUNT    EQU {len(assets)}",
        "M72_SPRITE_REC_SIZE    EQU 20",
        "M72SpriteTable:",
    ]
    for asset in assets:
        lines.append(
            f"                ; ассет {asset['index']}: {asset['name']} "
            f"{asset['width']}x{asset['height']}")
        for word in command_words(asset):
            # Адреса источника относительны M72_SPR_BLOB_BASE (сейчас 0),
            # но выражение оставляем явным как часть контракта RAM_G.
            if word >> 24 == 0x01:
                lines.append(
                    f"                DEFD $01000000 | "
                    f"(M72_SPR_BLOB_BASE + ${int(asset['offset']):06X})")
            else:
                lines.append(f"                DEFD ${word:08X}")

    if any(int(asset["width"]) > 255 for asset in assets):
        raise ValueError("логическая ширина sprite asset не помещается в DEFB")
    lines.extend([
        "",
        "; Ширина нужна только редкой точной обрезке launch-объекта у X<0.",
        "M72SpriteLogicalWidthTable:",
        "                DEFB " + ", ".join(
            str(int(asset["width"])) for asset in assets),
    ])

    lines.extend([
        "",
        "; R-9: пять наклонов и четыре эффекта вылета взяты из готового Python-runtime.",
        "; Эффект не является постоянным выхлопом: его выбирает только 226-кадровая таблица.",
        f"M72_R9_ASSET            EQU {player['pitch_asset_indices'][2]}",
        "M72_R9_PITCH_ASSET_COUNT EQU 5",
        "M72R9PitchAssetTable:",
        "                DEFB " + ", ".join(
            str(value) for value in player["pitch_asset_indices"]),
        "M72R9PitchCropTopTable:",
        "                DEFB " + ", ".join(
            str(value) for value in player["pitch_crop_top"]),
        "M72_R9_LAUNCH_ASSET_COUNT EQU 4",
        "M72R9LaunchAssetTable:",
        "                DEFB " + ", ".join(
            str(value) for value in player["launch_asset_indices"]),
        f"M72_R9_SHOT_ASSET       EQU {shot['asset_index']}",
        f"M72_R9_SHOT_DX_Q8       EQU {shot['spawn_dx_q8']}",
        f"M72_R9_SHOT_DY_Q8       EQU {shot['spawn_dy_q8']}",
        f"M72_R9_SHOT_VX_Q8       EQU {shot['velocity_x_q8']}",
        f"M72_R9_WAVE_ASSET_A     EQU {wave['asset_indices'][0]}",
        f"M72_R9_WAVE_ASSET_B     EQU {wave['asset_indices'][1]}",
        f"M72_R9_WAVE_DX_Q8       EQU {wave['spawn_dx_q8']}",
        f"M72_R9_WAVE_DY_Q8       EQU {wave['spawn_dy_q8']}",
        f"M72_R9_WAVE_VX_Q8       EQU {wave['velocity_x_q8']}",
        f"M72_R9_WAVE_MIN_CHARGE  EQU {wave['min_charge_frames']}",
        f"M72_R9_WAVE_DELAY       EQU {wave['appear_delay']}",
        f"M72_R9_WAVE_RELEASE_0   EQU {wave['release_asset_indices'][0]}",
        f"M72_R9_WAVE_RELEASE_1   EQU {wave['release_asset_indices'][1]}",
        f"M72_R9_WAVE_RELEASE_2   EQU {wave['release_asset_indices'][2]}",
        f"M72_R9_WAVE_RELEASE_3   EQU {wave['release_asset_indices'][3]}",
        f"M72_R9_WAVE_RELEASE_DX_Q8 EQU {wave['release_spawn_dx_q8']}",
        f"M72_R9_WAVE_RELEASE_DY_Q8 EQU {wave['release_spawn_dy_q8']}",
        "",
        "; Противники Stage 1 взяты из MAME frame 1500 и декодированы из ROM.",
    ])
    for label, _, _ in M72_STAGE1_ENEMIES:
        enemy = enemies[label]
        lines.extend([
            f"M72_ENEMY_{label}_ASSET EQU {enemy['asset_index']}",
            f"M72_ENEMY_{label}_W     EQU {enemy['width']}",
            f"M72_ENEMY_{label}_H     EQU {enemy['height']}",
        ])
    lines.extend([
        "",
        "; Остальные захваченные объекты в точном порядке вывода MAME.",
        "M72_SCENE_INSTANCE_REC_SIZE EQU 5",
        f"M72_SCENE_INSTANCE_COUNT EQU {len(instances)}",
        "M72SceneInstanceTable:",
    ])
    for instance in instances:
        lines.append(
            f"                DEFB {instance['asset_index']}  "
            f"; ОЗУ спрайтов ${int(instance['spriteram_offset']):03X}")
        lines.append(f"                DEFW ${int(instance['x_units']) & 0xFFFF:04X}")
        lines.append(f"                DEFW ${int(instance['y_units']) & 0xFFFF:04X}")
    lines.extend([
        "",
        "; логический пиксель -> VERTEX2F для VERTEX_FORMAT 3 и физического x8/5.",
        "M72LogicalToVertexTable:",
    ])
    for start in range(0, 641, 8):
        values = [round_ratio(value, 64, 5)
                  for value in range(start, min(start + 8, 641))]
        lines.append("                DEFW " + ", ".join(str(value) for value in values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_assets(capture_dir: Path, frame: int, state_frame: int, output: Path,
                 include: Path, shot_capture_dir: Path, shot_frame: int,
                 shot_next_frame: int, wave_capture_dir: Path, wave_frame: int,
                 wave_next_frame: int, enemy_capture_dir: Path,
                 enemy_frame: int) -> dict[str, object]:
    capture = scene.Capture.load(capture_dir, frame, state_frame)
    graphics = scene.Graphics.load()
    visible: list[dict[str, object]] = []
    for sprite in scene.sprite_objects(capture.spriteram):
        if not object_visible(sprite):
            continue
        native = scene.sprite_object_image(sprite, graphics, capture.palette)
        if native.getchannel("A").getbbox() is None:
            continue
        visible.append({"sprite": sprite, "native": native})

    output.mkdir(parents=True, exist_ok=True)
    sheet_path = output / f"frame_{frame:06d}_sprite_objects.png"
    contact_sheet(visible, sheet_path)

    assets: list[dict[str, object]] = []
    asset_by_key: dict[tuple[tuple[int, int], str], int] = {}
    object_asset: dict[int, int] = {}
    blob = bytearray()

    for item in visible:
        sprite = item["sprite"]
        native = item["native"]
        assert isinstance(sprite, scene.SpriteObject)
        assert isinstance(native, Image.Image)
        asset_index = register_asset(
            sprite, native, assets, asset_by_key, blob, output
        )
        object_asset[sprite.offset] = asset_index

    # Не брать один случайный R-9 и один кадр плазмы из frame 900. Python уже
    # содержит полный точный набор корпуса/вылета, подготовленный тем же
    # ROM/MAME pipeline; добавляем эти изображения напрямую, без второго scale.
    player = register_exact_player_assets(assets, blob, output)

    # MAME рисует от конца sprite RAM к началу.
    instances = []
    by_offset = {int(item["sprite"].offset): item for item in visible}
    for offset in reversed([int(item["sprite"].offset) for item in visible]):
        item = by_offset[offset]
        sprite = item["sprite"]
        assert isinstance(sprite, scene.SpriteObject)
        asset = assets[object_asset[offset]]
        logical_x = round_ratio(sprite.visible_x, 5, 3) + int(asset["crop_left"])
        logical_y = round_ratio(sprite.sy, 15, 8) + int(asset["crop_top"])
        instances.append({
            "spriteram_offset": offset,
            "asset_index": int(asset["index"]),
            "native_x": sprite.visible_x,
            "native_y": sprite.sy,
            "logical_x": logical_x,
            "logical_y": logical_y,
            "x_units": round_ratio(logical_x, 64, 5),
            "y_units": round_ratio(logical_y, 64, 5),
        })

    by_instance_offset = {
        int(instance["spriteram_offset"]): instance for instance in instances
    }
    required_dynamic = {"r9": 0x060, "exhaust": 0x068}
    missing = [name for name, offset in required_dynamic.items()
               if offset not in by_instance_offset]
    if missing:
        raise ValueError(f"required dynamic M72 objects missing: {missing}")
    dynamic = {
        name: by_instance_offset[offset]
        for name, offset in required_dynamic.items()
    }
    static_instances = [
        instance for instance in instances
        if int(instance["spriteram_offset"]) not in required_dynamic.values()
    ]

    # Первый игровой срез использует реальные типы врагов, уже присутствующие
    # в детерминированном захвате Stage 1. Берём только форму/палитру объекта;
    # положение и жизненный цикл ниже задаёт живое игровое состояние Z80.
    enemy_capture = scene.Capture.load(
        enemy_capture_dir, enemy_frame, enemy_frame
    )
    enemies: dict[str, dict[str, object]] = {}
    for label, code, palette in M72_STAGE1_ENEMIES:
        candidates = [
            sprite for sprite in scene.sprite_objects(enemy_capture.spriteram)
            if sprite.code == code and sprite.color == palette
        ]
        if not candidates:
            raise ValueError(
                f"enemy {label}: code=${code:04X}/palette={palette} not found"
            )
        # Для варианта RED_FLIP нужен реально наблюдавшийся flip-Y объект.
        if label == "RED_FLIP":
            candidates = [sprite for sprite in candidates if sprite.flip_y]
        else:
            candidates = [sprite for sprite in candidates if not sprite.flip_y]
        if not candidates:
            raise ValueError(f"enemy {label}: required flip state not found")
        sprite = candidates[0]
        native = scene.sprite_object_image(
            sprite, graphics, enemy_capture.palette
        )
        asset_index = register_asset(
            sprite, native, assets, asset_by_key, blob, output,
            name_override=f"stage1_{label.lower()}_c{code:04x}_p{palette}",
        )
        asset = assets[asset_index]
        enemies[label] = {
            "asset_index": asset_index,
            "code": code,
            "palette": palette,
            "frame": enemy_frame,
            "width": int(asset["width"]),
            "height": int(asset["height"]),
        }

    # Короткое детерминированное окно P1 Button 1 в MAME создаёт обычный снаряд
    # R-9. Первые два состояния задают подлинный объект ROM и исходную
    # горизонтальную скорость 16 нативных пикселей/кадр.
    shot_capture = scene.Capture.load(
        shot_capture_dir, shot_frame, shot_frame
    )
    shot_next_capture = scene.Capture.load(
        shot_capture_dir, shot_next_frame, shot_next_frame
    )
    shot_sprite = unique_object(
        shot_capture, M72_PLAYER_SHOT_CODE, M72_PLAYER_SHOT_PALETTE,
        "R-9 normal shot",
    )
    shot_next_sprite = unique_object(
        shot_next_capture, M72_PLAYER_SHOT_CODE, M72_PLAYER_SHOT_PALETTE,
        "R-9 normal shot next frame",
    )
    shot_body = unique_object(
        shot_capture, M72_R9_CODE, M72_R9_PALETTE, "R-9 body"
    )
    native_velocity_x = shot_next_sprite.visible_x - shot_sprite.visible_x
    native_velocity_y = shot_next_sprite.sy - shot_sprite.sy
    if (native_velocity_x, native_velocity_y) != (16, 0):
        raise ValueError(
            "unexpected M72 normal-shot velocity: "
            f"({native_velocity_x}, {native_velocity_y})"
        )
    shot_native = scene.sprite_object_image(
        shot_sprite, graphics, shot_capture.palette
    )
    shot_asset_index = register_asset(
        shot_sprite, shot_native, assets, asset_by_key, blob, output
    )
    shot_asset = assets[shot_asset_index]
    body_asset = assets[int(dynamic["r9"]["asset_index"])]
    shot_logical_x = (
        round_ratio(shot_sprite.visible_x, 5, 3)
        + int(shot_asset["crop_left"])
    )
    shot_logical_y = (
        round_ratio(shot_sprite.sy, 15, 8)
        + int(shot_asset["crop_top"])
    )
    body_logical_x = (
        round_ratio(shot_body.visible_x, 5, 3)
        + int(body_asset["crop_left"])
    )
    body_logical_y = (
        round_ratio(shot_body.sy, 15, 8)
        + int(body_asset["crop_top"])
    )
    shot = {
        "asset_index": shot_asset_index,
        "code": shot_sprite.code,
        "palette": shot_sprite.color,
        "spriteram_offset": shot_sprite.offset,
        "state_frame": shot_frame,
        "next_state_frame": shot_next_frame,
        "native_x": shot_sprite.visible_x,
        "native_y": shot_sprite.sy,
        "native_velocity_x": native_velocity_x,
        "native_velocity_y": native_velocity_y,
        "logical_x": shot_logical_x,
        "logical_y": shot_logical_y,
        "spawn_dx": shot_logical_x - body_logical_x,
        "spawn_dy": shot_logical_y - body_logical_y,
        # Сохраняем горизонтальную фазу 1/3 пикселя из нативных 32 * 5/3.
        "spawn_dx_q8": (
            round_ratio(shot_sprite.visible_x - shot_body.visible_x,
                        5 * 256, 3)
            + (int(shot_asset["crop_left"])
               - int(body_asset["crop_left"])) * 256
        ),
        # Отрисовщик использует целую Y; берём наблюдаемые начала после обрезки.
        "spawn_dy_q8": (shot_logical_y - body_logical_y) * 256,
        "velocity_x_q8": round_ratio(native_velocity_x, 5 * 256, 3),
    }

    # Полный заряд в 67 кадров создаёт Wave через два кадра после отпускания.
    # Две соседние фазы состоят из трёх непрерывных аппаратных объектов M72.
    wave_captures = [
        scene.Capture.load(
            wave_capture_dir, wave_frame + M72_SCREEN_STATE_DELAY, wave_frame
        ),
        scene.Capture.load(
            wave_capture_dir,
            wave_next_frame + M72_SCREEN_STATE_DELAY,
            wave_next_frame,
        ),
    ]
    wave_rows = [
        compose_horizontal_objects(
            capture_item, graphics, codes, M72_WAVE_PALETTE,
            f"фаза {phase} Wave Cannon",
        )
        for phase, (capture_item, codes) in enumerate(
            zip(wave_captures, M72_WAVE_PHASE_CODES, strict=True)
        )
    ]
    if any(row[1].size != (80, 16) for row in wave_rows):
        raise ValueError("неожиданный нативный размер Wave Cannon")
    wave_native_velocity_x = wave_rows[1][2] - wave_rows[0][2]
    wave_native_velocity_y = wave_rows[1][3] - wave_rows[0][3]
    if (wave_native_velocity_x, wave_native_velocity_y) != (8, 0):
        raise ValueError(
            "неожиданная скорость Wave Cannon M72: "
            f"({wave_native_velocity_x}, {wave_native_velocity_y})"
        )
    wave_asset_indices = []
    for phase, row in enumerate(wave_rows):
        representative, native, native_x, native_y, objects = row
        asset_index = register_asset(
            representative, native, assets, asset_by_key, blob, output,
            name_override=f"wave_{phase}_p8_80x16",
        )
        asset = assets[asset_index]
        asset["composite_codes"] = [sprite.code for sprite in objects]
        asset["native_origin_x"] = native_x
        asset["native_origin_y"] = native_y
        wave_asset_indices.append(asset_index)

    wave_body = unique_object(
        wave_captures[0], M72_R9_CODE, M72_R9_PALETTE, "корпус R-9 для Wave"
    )
    if (wave_body.visible_x, wave_body.sy) != (
            shot_body.visible_x, shot_body.sy):
        raise ValueError("положение R-9 изменилось между эталонами оружия")

    # Вспышка у носа остаётся на месте семь кадров: 2+2+2+1.
    # Для каждой записи ОЗУ спрайтов берётся экранная палитра двумя кадрами позже.
    release_asset_indices = []
    release_sprites = []
    for phase, (state_offset, code) in enumerate(zip(
            M72_WAVE_RELEASE_OFFSETS, M72_WAVE_RELEASE_CODES, strict=True)):
        release_state_frame = wave_frame + state_offset
        release_capture = scene.Capture.load(
            wave_capture_dir,
            release_state_frame + M72_SCREEN_STATE_DELAY,
            release_state_frame,
        )
        release_sprite = unique_object(
            release_capture, code, M72_WAVE_PALETTE,
            f"вспышка {phase} Wave Cannon",
        )
        if (release_sprite.visible_x, release_sprite.sy) != (155, 104):
            raise ValueError("вспышка Wave Cannon сместилась относительно R-9")
        release_native = scene.sprite_object_image(
            release_sprite, graphics, release_capture.palette
        )
        release_asset_index = register_asset(
            release_sprite, release_native, assets, asset_by_key, blob, output,
            name_override=(
                f"wave_release_{phase}_c{code:04x}_p8_"
                f"{release_native.width}x{release_native.height}"
            ),
        )
        release_asset_indices.append(release_asset_index)
        release_sprites.append(release_sprite)

    wave_asset = assets[wave_asset_indices[0]]
    wave_logical_x = (
        round_ratio(wave_rows[0][2], 5, 3)
        + int(wave_asset["crop_left"])
    )
    wave_logical_y = (
        round_ratio(wave_rows[0][3], 15, 8)
        + int(wave_asset["crop_top"])
    )
    release_asset = assets[release_asset_indices[0]]
    release_logical_x = (
        round_ratio(release_sprites[0].visible_x, 5, 3)
        + int(release_asset["crop_left"])
    )
    release_logical_y = (
        round_ratio(release_sprites[0].sy, 15, 8)
        + int(release_asset["crop_top"])
    )
    wave = {
        "asset_indices": wave_asset_indices,
        "phase_codes": [list(codes) for codes in M72_WAVE_PHASE_CODES],
        "palette": M72_WAVE_PALETTE,
        "state_frames": [wave_frame, wave_next_frame],
        "native_x": wave_rows[0][2],
        "native_y": wave_rows[0][3],
        "native_width": wave_rows[0][1].width,
        "native_height": wave_rows[0][1].height,
        "native_velocity_x": wave_native_velocity_x,
        "native_velocity_y": wave_native_velocity_y,
        "logical_x": wave_logical_x,
        "logical_y": wave_logical_y,
        "spawn_dx_q8": (
            round_ratio(wave_rows[0][2] - wave_body.visible_x,
                        5 * 256, 3)
            + (int(wave_asset["crop_left"])
               - int(body_asset["crop_left"])) * 256
        ),
        "spawn_dy_q8": (wave_logical_y - body_logical_y) * 256,
        "velocity_x_q8": round_ratio(
            wave_native_velocity_x, 5 * 256, 3),
        "min_charge_frames": M72_WAVE_MIN_CHARGE_FRAMES,
        "appear_delay": M72_WAVE_APPEAR_DELAY,
        "release_asset_indices": release_asset_indices,
        "release_codes": list(M72_WAVE_RELEASE_CODES),
        "release_state_frames": [
            wave_frame + offset for offset in M72_WAVE_RELEASE_OFFSETS
        ],
        "release_durations": list(M72_WAVE_RELEASE_DURATIONS),
        "release_logical_x": release_logical_x,
        "release_logical_y": release_logical_y,
        "release_spawn_dx_q8": (
            round_ratio(release_sprites[0].visible_x - wave_body.visible_x,
                        5 * 256, 3)
            + (int(release_asset["crop_left"])
               - int(body_asset["crop_left"])) * 256
        ),
        "release_spawn_dy_q8": (
            release_logical_y - body_logical_y
        ) * 256,
    }

    # Следующий фон RGB565 начинается в RAM_G сразу после этого блока.
    # Адрес остаётся выровненным по dword для FT812 и сгенерированных команд.
    while len(blob) & 3:
        blob.append(0)
    blob_path = output / f"RTYPE_M72_FRAME{frame}_ARGB4444.bin"
    blob_path.write_bytes(blob)
    generate_include(
        assets, static_instances, dynamic, player, shot, wave, enemies,
        len(blob), include
    )

    decoded_sprite_path = (
        ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_SPRITES_INDEX4.bin")
    manifest = {
        "format": 1,
        "frame": frame,
        "state_frame": state_frame,
        "capture": str(capture_dir.resolve()),
        "source": {
            "rom_set": "rtype World",
            "mame_tag": m72.MAME_TAG,
            "mame_commit": m72.MAME_COMMIT,
            "spriteram": {
                "path": str((capture_dir / f"frame_{state_frame:06d}_spriteram.bin").resolve()),
                "sha256": sha256_file(
                    capture_dir / f"frame_{state_frame:06d}_spriteram.bin"),
            },
            "palette": {
                "path": str((capture_dir / f"frame_{frame:06d}_palette_argb8888_le.bin").resolve()),
                "sha256": sha256_file(
                    capture_dir / f"frame_{frame:06d}_palette_argb8888_le.bin"),
            },
            "player_shot": {
                "capture": str(shot_capture_dir.resolve()),
                "code": M72_PLAYER_SHOT_CODE,
                "palette": M72_PLAYER_SHOT_PALETTE,
                "state_frames": [shot_frame, shot_next_frame],
                "spriteram_sha256": [
                    sha256_file(shot_capture_dir / f"frame_{value:06d}_spriteram.bin")
                    for value in (shot_frame, shot_next_frame)
                ],
                "palette_sha256": sha256_file(
                    shot_capture_dir
                    / f"frame_{shot_frame:06d}_palette_argb8888_le.bin"
                ),
            },
            "player_wave": {
                "capture": str(wave_capture_dir.resolve()),
                "palette": M72_WAVE_PALETTE,
                "min_charge_frames": M72_WAVE_MIN_CHARGE_FRAMES,
                "state_frames": [wave_frame, wave_next_frame],
                "screen_frames": [
                    wave_frame + M72_SCREEN_STATE_DELAY,
                    wave_next_frame + M72_SCREEN_STATE_DELAY,
                ],
                "screen_state_delay_frames": M72_SCREEN_STATE_DELAY,
                "phase_codes": [
                    list(codes) for codes in M72_WAVE_PHASE_CODES
                ],
                "release_codes": list(M72_WAVE_RELEASE_CODES),
                "release_state_frames": [
                    wave_frame + offset for offset in M72_WAVE_RELEASE_OFFSETS
                ],
                "spriteram_sha256": [
                    sha256_file(
                        wave_capture_dir
                        / f"frame_{value:06d}_spriteram.bin"
                    )
                    for value in (wave_frame, wave_next_frame)
                ],
                "palette_sha256": sha256_file(
                    wave_capture_dir
                    / f"frame_{wave_frame + M72_SCREEN_STATE_DELAY:06d}_palette_argb8888_le.bin"
                ),
            },
            "decoded_sprite_rom": {
                "path": str(decoded_sprite_path.resolve()),
                "sha256": sha256_file(decoded_sprite_path),
            },
        },
        "algorithm": {
            "native_to_logical": "xBRZ 1.9 6x then Pillow Lanczos",
            "native_scale_x": "5/3",
            "native_scale_y": "15/8",
            "runtime_ft812": "NEAREST 8/5 only",
            "format": "little-endian ARGB4444",
        },
        "visible_object_count": len(visible),
        "supplemental_visible_object_count": 20,
        "unique_asset_count": len(assets),
        "assets": assets,
        "instances_in_mame_draw_order": instances,
        "dynamic_instances": dynamic,
        "exact_player_assets": player,
        "dynamic_player_shot": shot,
        "dynamic_player_wave": wave,
        "stage1_enemies": enemies,
        "static_instances_in_mame_draw_order": static_instances,
        "outputs": {
            "blob": {
                "path": str(blob_path.resolve()),
                "size": len(blob),
                "sha256": sha256_file(blob_path),
            },
            "include": {
                "path": str(include.resolve()),
                "sha256": sha256_file(include),
            },
            "contact_sheet": {
                "path": str(sheet_path.resolve()),
                "sha256": sha256_file(sheet_path),
            },
        },
    }
    manifest_path = output / f"frame_{frame:06d}_sprite_assets.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"visible M72 objects: {len(visible)}")
    print(f"unique HQ assets: {len(assets)}")
    print(
        "M72 player shot: "
        f"code=${shot_sprite.code:04X}, asset={shot_asset_index}, "
        f"velocity={native_velocity_x} native px/frame"
    )
    print(
        "M72 Wave Cannon: "
        f"codes={M72_WAVE_PHASE_CODES}, assets={wave_asset_indices}, "
        f"velocity={wave_native_velocity_x} native px/frame"
    )
    print(f"ARGB4444 blob: {len(blob)} bytes, sha256={sha256_file(blob_path)}")
    print(f"contact sheet: {sheet_path}")
    print(f"manifest: {manifest_path}")
    print(f"include: {include}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--frame", type=int, default=900,
                        help="MAME screen/palette frame")
    parser.add_argument("--state-frame", type=int, default=898,
                        help="paired per-frame sprite RAM state")
    parser.add_argument("--shot-capture", type=Path,
                        default=DEFAULT_SHOT_CAPTURE)
    parser.add_argument("--shot-frame", type=int, default=DEFAULT_SHOT_FRAME)
    parser.add_argument("--shot-next-frame", type=int,
                        default=DEFAULT_SHOT_NEXT_FRAME)
    parser.add_argument("--wave-capture", type=Path,
                        default=DEFAULT_WAVE_CAPTURE)
    parser.add_argument("--wave-frame", type=int, default=DEFAULT_WAVE_FRAME)
    parser.add_argument("--wave-next-frame", type=int,
                        default=DEFAULT_WAVE_NEXT_FRAME)
    parser.add_argument("--enemy-capture", type=Path,
                        default=DEFAULT_ENEMY_CAPTURE)
    parser.add_argument("--enemy-frame", type=int,
                        default=DEFAULT_ENEMY_FRAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include", type=Path, default=DEFAULT_INCLUDE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        build_assets(args.capture, args.frame, args.state_frame,
                     args.output, args.include, args.shot_capture,
                     args.shot_frame, args.shot_next_frame,
                     args.wave_capture, args.wave_frame, args.wave_next_frame,
                     args.enemy_capture, args.enemy_frame)
    except (FileNotFoundError, IndexError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
