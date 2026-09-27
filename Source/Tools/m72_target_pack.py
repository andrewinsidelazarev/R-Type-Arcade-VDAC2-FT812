#!/usr/bin/env python3
"""Собрать полный ROM-derived пакет данных для целевого Z80 runtime."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TERRAIN_ROOT = ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" / "Terrain"
TERRAIN_MANIFEST = TERRAIN_ROOT / "all_stage_terrain.json"
ARCADE_ROOT = ROOT / "Assets" / "Converted" / "Arcade"
MAINCPU = ARCADE_ROOT / "RTYPE_MAINCPU_REGION.bin"
TILES0 = ARCADE_ROOT / "RTYPE_TILES0_INDEX4.bin"
TILES1 = ARCADE_ROOT / "RTYPE_TILES1_INDEX4.bin"
SPRITES = ARCADE_ROOT / "RTYPE_SPRITES_INDEX4.bin"
OUTPUT = ROOT / "Build" / "rtype_target_pack.bin"
OUTPUT_MANIFEST = ROOT / "Build" / "rtype_target_pack.json"
OUTPUT_INC = ROOT / "Source" / "ASM" / "generated_target_pack.inc"

MAGIC = b"RTZ2"
VERSION = 6
PAGE_SIZE = 0x4000
HEADER_SIZE = 0x0400
DIRECTORY_OFFSET = 0x0040
STAGE_RECORD_SIZE = 72
STAGE_COUNT = 8
CHECKPOINT_RECORD_SIZE = 14
EVENT_RECORD_SIZE = 6
STRIP_BYTES = 30 * 8 * 4
STRIPS_PER_PAGE = PAGE_SIZE // STRIP_BYTES
TEXTURE_MAGIC = b"TXS4"
TEXTURE_HEADER_SIZE = 16
TEXTURE_RECORD_SIZE = 6
TEXTURE_STRIP_BYTES = 64 * 240
TILE_TEXTURE_MASKS = (0x0000, 0x0001)  # BG opaque; FG pen 0 transparent
SPRITE_TEXTURE_MASK = 0x0001
SPRITE_TEXTURE_MAGIC = b"SPZ1"
SPRITE_TEXTURE_HEADER_SIZE = 16
SPRITE_TEXTURE_RECORD_SIZE = 6
SPRITE_TEXTURE_CHUNK_SIZE = 0x2000
PALETTE_TILE_TYPE_COUNT = 128
PALETTE_SPRITE_TYPE_COUNT = 256
PALETTE_TYPE_BYTES = 32
PALETTE_TILE_OPAQUE_OFFSET = 0
PALETTE_TILE_TRANSPARENT_OFFSET = (
    PALETTE_TILE_OPAQUE_OFFSET + PALETTE_TILE_TYPE_COUNT * PALETTE_TYPE_BYTES
)
PALETTE_SPRITE_OFFSET = (
    PALETTE_TILE_TRANSPARENT_OFFSET
    + PALETTE_TILE_TYPE_COUNT * PALETTE_TYPE_BYTES
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _align_page(target: bytearray) -> None:
    remainder = len(target) % PAGE_SIZE
    if remainder:
        target.extend(bytes(PAGE_SIZE - remainder))


def _append_aligned(target: bytearray, data: bytes) -> tuple[int, int]:
    _align_page(target)
    offset = len(target)
    target.extend(data)
    return offset, len(data)


def _pack_strips(data: bytes) -> bytes:
    """Разложить полосы так, чтобы запись 960 байт не пересекала страницу."""
    if len(data) % STRIP_BYTES:
        raise ValueError("terrain stream не кратен одной полосе")
    count = len(data) // STRIP_BYTES
    result = bytearray()
    for first in range(0, count, STRIPS_PER_PAGE):
        last = min(first + STRIPS_PER_PAGE, count)
        result.extend(data[first * STRIP_BYTES:last * STRIP_BYTES])
        result.extend(bytes(PAGE_SIZE - (last - first) * STRIP_BYTES))
    return bytes(result)


def _checkpoint_bytes(records: list[dict[str, int]]) -> bytes:
    result = bytearray()
    for record in records:
        result += struct.pack(
            "<7H",
            int(record["index"]),
            int(record["progression"]),
            int(record["foreground_source"]),
            int(record["background_source"]),
            int(record["foreground_velocity_q8"]) & 0xFFFF,
            int(record["background_velocity_q8"]) & 0xFFFF,
            int(record["packed_resource_music"]),
        )
    return bytes(result)


def _event_bytes(records: list[dict[str, int | str]]) -> bytes:
    result = bytearray()
    for record in records:
        result += struct.pack(
            "<3H",
            int(record["threshold"]),
            int(record["command"]),
            int(record["handler"]),
        )
    return bytes(result)


def _unpack_index4(data: bytes) -> bytes:
    """Развернуть два M72 pen в два байта, сохранив порядок nibble ROM."""
    result = bytearray(len(data) * 2)
    for index, value in enumerate(data):
        result[index * 2] = value >> 4
        result[index * 2 + 1] = value & 0x0F
    return bytes(result)


def _texture_strip(raw: bytes, graphics: bytes) -> bytes:
    """Развернуть одну 8x30 tile-полосу в contiguous index8 bitmap 64x240."""
    if len(raw) != STRIP_BYTES:
        raise ValueError("неверный размер исходной terrain-полосы")
    output = bytearray()
    for tile_row in range(30):
        cells: list[bytes] = []
        for column in range(8):
            offset = (tile_row * 8 + column) * 4
            code_word, attribute = struct.unpack_from("<HH", raw, offset)
            code = code_word & 0x3FFF
            cell = bytearray(graphics[code * 64:(code + 1) * 64])
            if len(cell) != 64:
                raise ValueError(f"tile code ${code:04X} вне graphics bank")
            if code_word & 0x4000:
                cell = bytearray(
                    value for row in range(8)
                    for value in reversed(cell[row * 8:(row + 1) * 8]))
            if code_word & 0x8000:
                cell = bytearray(
                    value for row in reversed(range(8))
                    for value in cell[row * 8:(row + 1) * 8])
            palette = (attribute & 15) << 4
            cells.append(bytes(palette | pen for pen in cell))
        for pixel_row in range(8):
            for cell in cells:
                output += cell[pixel_row * 8:pixel_row * 8 + 8]
    if len(output) != TEXTURE_STRIP_BYTES:
        raise AssertionError("texture strip не равна 64x240")
    return bytes(output)


def _texture_stream(raw: bytes, packed_tiles: bytes) -> tuple[bytes, dict[str, object]]:
    """Собрать page-safe zlib records для FT812 CMD_INFLATE."""
    graphics = _unpack_index4(packed_tiles)
    count = len(raw) // STRIP_BYTES
    compressed = [zlib.compress(
        _texture_strip(raw[index * STRIP_BYTES:(index + 1) * STRIP_BYTES], graphics),
        level=9) for index in range(count)]
    directory_bytes = TEXTURE_HEADER_SIZE + count * TEXTURE_RECORD_SIZE
    result = bytearray(directory_bytes)
    records: list[dict[str, int | str]] = []
    for index, data in enumerate(compressed):
        in_page = len(result) % PAGE_SIZE
        if in_page + len(data) > PAGE_SIZE:
            result.extend(bytes(PAGE_SIZE - in_page))
        offset = len(result)
        result.extend(data)
        records.append({
            "index": index, "offset": offset, "size": len(data),
            "sha256": _sha256(data),
        })
        struct.pack_into("<IH", result,
                         TEXTURE_HEADER_SIZE + index * TEXTURE_RECORD_SIZE,
                         offset, len(data))
    struct.pack_into("<4sHHII", result, 0, TEXTURE_MAGIC, count,
                     TEXTURE_RECORD_SIZE, directory_bytes, len(result))
    blob = bytes(result)
    return blob, {
        "record_count": count,
        "record_size": TEXTURE_RECORD_SIZE,
        "size": len(blob),
        "sha256": _sha256(blob),
        "records": records,
    }


def _sprite_texture_stream(packed_sprites: bytes) -> tuple[bytes, dict[str, object]]:
    """Собрать 8-КБ page/FIFO-safe zlib-блоки полного sprite index8 atlas."""
    graphics = _unpack_index4(packed_sprites)
    if len(graphics) % SPRITE_TEXTURE_CHUNK_SIZE:
        raise ValueError("sprite index8 atlas не кратен 64-КБ блоку")
    chunks = [
        zlib.compress(graphics[offset:offset + SPRITE_TEXTURE_CHUNK_SIZE], 9)
        for offset in range(0, len(graphics), SPRITE_TEXTURE_CHUNK_SIZE)
    ]
    result = bytearray(
        SPRITE_TEXTURE_HEADER_SIZE + len(chunks) * SPRITE_TEXTURE_RECORD_SIZE)
    records: list[dict[str, int | str]] = []
    for index, data in enumerate(chunks):
        in_page = len(result) % PAGE_SIZE
        if in_page + len(data) > PAGE_SIZE:
            result.extend(bytes(PAGE_SIZE - in_page))
        offset = len(result)
        result.extend(data)
        records.append({
            "index": index, "offset": offset, "size": len(data),
            "sha256": _sha256(data),
        })
        struct.pack_into(
            "<IH", result,
            SPRITE_TEXTURE_HEADER_SIZE + index * SPRITE_TEXTURE_RECORD_SIZE,
            offset, len(data))
    struct.pack_into(
        "<4sHHII", result, 0, SPRITE_TEXTURE_MAGIC, len(chunks),
        SPRITE_TEXTURE_RECORD_SIZE, len(graphics), len(result))
    blob = bytes(result)
    return blob, {
        "encoding": "page-safe-zlib-index8",
        "record_count": len(chunks),
        "record_size": SPRITE_TEXTURE_RECORD_SIZE,
        "raw_size": len(graphics),
        "raw_sha256": _sha256(graphics),
        "packed_index4_sha256": _sha256(packed_sprites),
        "size": len(blob),
        "sha256": _sha256(blob),
        "records": records,
    }


def _tile_palette_tables(maincpu: bytes, config_index: int) -> bytes:
    """BG/FG tile и sprite alpha-наборы из двух физических RGB ROM bank."""
    if not 0 <= config_index < 16:
        raise ValueError("индекс stage palette-list вне 0..15")
    list_pointer = struct.unpack_from(
        "<H", maincpu, 0x10000 + 0x8C20 + config_index * 2)[0]
    resource_types = [
        struct.unpack_from(
            "<H", maincpu, 0x10000 + list_pointer + slot * 2)[0] & 0xFF
        for slot in range(15)
    ] + [0x1F]
    def colors(rgb_bank_offset: int) -> list[int]:
        result: list[int] = []
        for resource_type in resource_types:
            source = 0x3B000 + rgb_bank_offset + resource_type * 48
            for pen in range(16):
                red, green, blue = maincpu[
                    source + pen * 3:source + pen * 3 + 3]
                if max(red, green, blue) > 31:
                    raise ValueError(
                        "palette RGB ROM содержит компонент больше 5 бит")
                red4 = (red * 15 + 15) // 31
                green4 = (green * 15 + 15) // 31
                blue4 = (blue * 15 + 15) // 31
                result.append((red4 << 8) | (green4 << 4) | blue4)
        return result

    tile_colors = colors(0x2400)
    sprite_colors = colors(0x0000)
    result = bytearray()
    for mask in TILE_TEXTURE_MASKS:
        for index, color in enumerate(tile_colors):
            pen = index & 15
            alpha = 0 if mask & (1 << pen) else 15
            result += struct.pack("<H", (alpha << 12) | color)
    for index, color in enumerate(sprite_colors):
        pen = index & 15
        alpha = 0 if SPRITE_TEXTURE_MASK & (1 << pen) else 15
        result += struct.pack("<H", (alpha << 12) | color)
    return bytes(result)


def _palette_resource_tables(maincpu: bytes) -> bytes:
    """Предвычислить все аппаратно допустимые палитры для DMA во время игры."""
    result = bytearray()

    def append_bank(bank_offset: int, type_count: int,
                    transparent_pen0: bool) -> None:
        for resource_type in range(type_count):
            source = 0x3B000 + bank_offset + resource_type * 48
            palette = maincpu[source:source + 48]
            if len(palette) != 48 or max(palette) > 31:
                raise ValueError(
                    f"palette type ${resource_type:02X} bank ${bank_offset:04X} "
                    "выходит за RGB ROM"
                )
            for pen in range(16):
                red, green, blue = palette[pen * 3:pen * 3 + 3]
                red4 = (red * 15 + 15) // 31
                green4 = (green * 15 + 15) // 31
                blue4 = (blue * 15 + 15) // 31
                alpha = 0 if transparent_pen0 and pen == 0 else 15
                result.extend(struct.pack(
                    "<H", (alpha << 12) | (red4 << 8) | (green4 << 4) | blue4
                ))

    # Второй M72 bank обслуживает tile palettes. Две копии различаются только
    # alpha pen 0, поэтому FT812 не должен менять прозрачность во время fade.
    append_bank(0x2400, PALETTE_TILE_TYPE_COUNT, False)
    append_bank(0x2400, PALETTE_TILE_TYPE_COUNT, True)
    # Первый M72 bank обслуживает аппаратные спрайты; вместе с двумя tile-
    # таблицами все типы занимают ровно одну 16-КБ страницу TS-Config.
    append_bank(0x0000, PALETTE_SPRITE_TYPE_COUNT, True)
    if len(result) != PAGE_SIZE:
        raise AssertionError("таблица palette resources должна занимать одну страницу")
    return bytes(result)


def build_target_pack() -> tuple[bytes, dict[str, object]]:
    """Вернуть пакет и проверочный манифест без изменения рабочего дерева."""
    source = json.loads(TERRAIN_MANIFEST.read_text(encoding="utf-8"))
    if source.get("stage_count") != STAGE_COUNT:
        raise ValueError("all-stage manifest не содержит восемь уровней")
    if source.get("event_count") != 788:
        raise ValueError("all-stage manifest не содержит 788 событий")

    maincpu = MAINCPU.read_bytes()
    if len(maincpu) != 0x100000:
        raise ValueError("собранный maincpu region должен занимать 1 МБ")
    tile_sources = (TILES0.read_bytes(), TILES1.read_bytes())
    world_rom = maincpu[0x10000:0x20000]
    packed_sprites = SPRITES.read_bytes()
    sprite_texture, sprite_texture_manifest = _sprite_texture_stream(
        packed_sprites)
    globals_data = {
        "world_rom": world_rom,
        "sprites": sprite_texture,
        "palettes": _palette_resource_tables(maincpu),
    }
    expected_sizes = {
        "world_rom": 0x10000,
    }
    if tuple(map(len, tile_sources)) != (0x20000, 0x20000):
        raise ValueError("оба tile graphics bank должны занимать по 128 КБ")
    for name, expected in expected_sizes.items():
        if len(globals_data[name]) != expected:
            raise ValueError(f"неверный размер секции {name}")

    pack = bytearray(HEADER_SIZE)
    global_sections: dict[str, dict[str, int | str]] = {}
    for name, data in globals_data.items():
        offset, size = _append_aligned(pack, data)
        global_sections[name] = {
            "offset": offset, "size": size, "sha256": _sha256(data),
        }
    global_sections["sprites"].update(sprite_texture_manifest)

    all_checkpoints = sorted(
        (record for stage in source["stages"] for record in stage["checkpoints"]),
        key=lambda record: int(record["index"]),
    )
    if [int(record["index"]) for record in all_checkpoints] != list(range(16)):
        raise ValueError("глобальные checkpoint-записи должны иметь индексы 0…15")
    global_checkpoint_data = _checkpoint_bytes(all_checkpoints)
    global_checkpoint_offset, global_checkpoint_size = _append_aligned(
        pack, global_checkpoint_data)

    stage_sections: list[dict[str, object]] = []
    total_checkpoints = 0
    for expected_stage, stage in enumerate(source["stages"], start=1):
        if int(stage["stage"]) != expected_stage:
            raise ValueError("уровни в all-stage manifest идут не по порядку")
        checkpoints = stage["checkpoints"]
        events = stage["events"]
        checkpoint_data = _checkpoint_bytes(checkpoints)
        event_data = _event_bytes(events)
        control_data = checkpoint_data + event_data
        if len(control_data) > PAGE_SIZE:
            raise ValueError(f"управляющие записи Stage {expected_stage} не помещаются в страницу")
        control_offset, control_size = _append_aligned(pack, control_data)

        layer_sections: dict[str, dict[str, int | str]] = {}
        layer_raw: dict[str, bytes] = {}
        for layer_name in ("foreground", "background"):
            definition = stage["layers"][layer_name]
            raw = (ROOT / definition["stream"]).read_bytes()
            strip_count = int(definition["strip_count"])
            if len(raw) != strip_count * STRIP_BYTES:
                raise ValueError(
                    f"Stage {expected_stage} {layer_name}: повреждён поток полос")
            encoded = _pack_strips(raw)
            layer_raw[layer_name] = raw
            offset, size = _append_aligned(pack, encoded)
            layer_sections[layer_name] = {
                "offset": offset,
                "size": size,
                "strip_count": strip_count,
                "raw_size": len(raw),
                "raw_sha256": _sha256(raw),
            }

        texture_sections: dict[str, dict[str, object]] = {}
        for layer_index, layer_name in enumerate(("foreground", "background")):
            texture_data, texture_manifest = _texture_stream(
                layer_raw[layer_name], tile_sources[layer_index])
            texture_offset, texture_size = _append_aligned(pack, texture_data)
            texture_manifest.update({"offset": texture_offset,
                                     "size": texture_size})
            texture_sections[layer_name] = texture_manifest
        config_index = int(checkpoints[0]["packed_resource_music"]) & 0x0F
        palette_data = _tile_palette_tables(maincpu, config_index)
        palette_offset, palette_size = _append_aligned(pack, palette_data)
        palette_manifest = {
            "config_index": config_index,
            "offset": palette_offset,
            "size": palette_size,
            "sha256": _sha256(palette_data),
        }

        total_checkpoints += len(checkpoints)
        stage_sections.append({
            "stage": expected_stage,
            "checkpoint_count": len(checkpoints),
            "event_count": len(events),
            "control_offset": control_offset,
            "control_size": control_size,
            "checkpoint_offset": control_offset,
            "event_offset": control_offset + len(checkpoint_data),
            "foreground_source_start": int(
                stage["layers"]["foreground"]["source_start"]),
            "background_source_start": int(
                stage["layers"]["background"]["source_start"]),
            "foreground": layer_sections["foreground"],
            "background": layer_sections["background"],
            "foreground_texture": texture_sections["foreground"],
            "background_texture": texture_sections["background"],
            "tile_palette": palette_manifest,
        })

    _align_page(pack)
    if total_checkpoints != 16:
        raise ValueError("общая checkpoint-таблица должна содержать 16 записей")

    struct.pack_into("<4sHBBHHII", pack, 0,
                     MAGIC, VERSION, STAGE_COUNT, STAGE_RECORD_SIZE,
                     int(source["event_count"]), total_checkpoints,
                     len(pack), DIRECTORY_OFFSET)
    global_header_offsets = {
        "world_rom": 0x14,
        "palettes": 0x1C,
        "sprites": 0x2C,
    }
    for name, header_offset in global_header_offsets.items():
        section = global_sections[name]
        struct.pack_into("<II", pack, header_offset,
                         int(section["offset"]), int(section["size"]))
    struct.pack_into("<HH", pack, 0x34, STRIPS_PER_PAGE, STRIP_BYTES)
    struct.pack_into("<II", pack, 0x38,
                     global_checkpoint_offset, global_checkpoint_size)

    for index, stage in enumerate(stage_sections):
        foreground = stage["foreground"]
        background = stage["background"]
        offset = DIRECTORY_OFFSET + index * STAGE_RECORD_SIZE
        struct.pack_into(
            "<BB5H8I",
            pack,
            offset,
            int(stage["stage"]),
            int(stage["checkpoint_count"]),
            int(foreground["strip_count"]),
            int(background["strip_count"]),
            int(stage["event_count"]),
            int(stage["foreground_source_start"]),
            int(stage["background_source_start"]),
            int(stage["control_offset"]),
            int(stage["control_size"]),
            int(stage["checkpoint_offset"]),
            int(stage["event_offset"]),
            int(foreground["offset"]),
            int(foreground["size"]),
            int(background["offset"]),
            int(background["size"]),
        )
        foreground_texture = stage["foreground_texture"]
        background_texture = stage["background_texture"]
        struct.pack_into("<4I2H", pack, offset + 44,
                         int(foreground_texture["offset"]),
                         int(foreground_texture["size"]),
                         int(background_texture["offset"]),
                         int(background_texture["size"]),
                         int(foreground_texture["record_count"]),
                         int(background_texture["record_count"]))
        palette = stage["tile_palette"]
        struct.pack_into("<II", pack, offset + 64,
                         int(palette["offset"]), int(palette["size"]))

    result = bytes(pack)
    manifest = {
        "format": VERSION,
        "magic": MAGIC.decode("ascii"),
        "page_size": PAGE_SIZE,
        "size": len(result),
        "page_count": len(result) // PAGE_SIZE,
        "sha256": _sha256(result),
        "stage_count": STAGE_COUNT,
        "event_count": int(source["event_count"]),
        "checkpoint_count": total_checkpoints,
        "strip_bytes": STRIP_BYTES,
        "strips_per_page": STRIPS_PER_PAGE,
        "globals": global_sections,
        "global_checkpoints": {
            "offset": global_checkpoint_offset,
            "size": global_checkpoint_size,
            "count": len(all_checkpoints),
            "sha256": _sha256(global_checkpoint_data),
        },
        "stages": stage_sections,
    }
    return result, manifest


def _generated_inc(manifest: dict[str, object]) -> str:
    world = manifest["globals"]["world_rom"]
    palettes = manifest["globals"]["palettes"]
    return "\n".join((
        "; Сгенерировано m72_target_pack.py; вручную не редактировать.",
        f"RTYPE_TARGET_MAGIC_0        EQU ${MAGIC[0]:02X}",
        f"RTYPE_TARGET_MAGIC_1        EQU ${MAGIC[1]:02X}",
        f"RTYPE_TARGET_MAGIC_2        EQU ${MAGIC[2]:02X}",
        f"RTYPE_TARGET_MAGIC_3        EQU ${MAGIC[3]:02X}",
        f"RTYPE_TARGET_VERSION        EQU {VERSION}",
        f"RTYPE_TARGET_STAGE_COUNT    EQU {STAGE_COUNT}",
        f"RTYPE_TARGET_STAGE_REC_SIZE EQU {STAGE_RECORD_SIZE}",
        f"RTYPE_TARGET_STAGE_DIR      EQU ${DIRECTORY_OFFSET:04X}",
        f"RTYPE_TARGET_CHECKPOINT_REC EQU {CHECKPOINT_RECORD_SIZE}",
        f"RTYPE_TARGET_EVENT_REC      EQU {EVENT_RECORD_SIZE}",
        f"RTYPE_TARGET_STRIP_BYTES    EQU {STRIP_BYTES}",
        f"RTYPE_TARGET_STRIPS_PAGE    EQU {STRIPS_PER_PAGE}",
        f"RTYPE_TARGET_TEXTURE_REC    EQU {TEXTURE_RECORD_SIZE}",
        f"RTYPE_TARGET_TEXTURE_HEAD   EQU {TEXTURE_HEADER_SIZE}",
        f"RTYPE_TARGET_TEXTURE_BYTES  EQU {TEXTURE_STRIP_BYTES}",
        f"RTYPE_TARGET_TILE_PAL_SIZE  EQU {(len(TILE_TEXTURE_MASKS) + 1) * 512}",
        f"RTYPE_TARGET_SPRITE_PAL_OFF EQU {len(TILE_TEXTURE_MASKS) * 512}",
        f"RTYPE_TARGET_SPRITE_MAGIC_0 EQU ${SPRITE_TEXTURE_MAGIC[0]:02X}",
        f"RTYPE_TARGET_SPRITE_MAGIC_1 EQU ${SPRITE_TEXTURE_MAGIC[1]:02X}",
        f"RTYPE_TARGET_SPRITE_MAGIC_2 EQU ${SPRITE_TEXTURE_MAGIC[2]:02X}",
        f"RTYPE_TARGET_SPRITE_MAGIC_3 EQU ${SPRITE_TEXTURE_MAGIC[3]:02X}",
        f"RTYPE_TARGET_SPRITE_HEAD    EQU {SPRITE_TEXTURE_HEADER_SIZE}",
        f"RTYPE_TARGET_SPRITE_REC     EQU {SPRITE_TEXTURE_RECORD_SIZE}",
        f"RTYPE_TARGET_SPRITE_COUNT   EQU {0x100000 // SPRITE_TEXTURE_CHUNK_SIZE}",
        f"RTYPE_TARGET_PALETTE_OFFSET EQU ${int(palettes['offset']):08X}",
        f"RTYPE_TARGET_PALETTE_SIZE   EQU {int(palettes['size'])}",
        f"RTYPE_TARGET_PAL_TILE_TYPES EQU {PALETTE_TILE_TYPE_COUNT}",
        f"RTYPE_TARGET_PAL_SPR_TYPES  EQU {PALETTE_SPRITE_TYPE_COUNT}",
        f"RTYPE_TARGET_PAL_TYPE_BYTES EQU {PALETTE_TYPE_BYTES}",
        f"RTYPE_TARGET_PAL_TILE_OPAQUE EQU ${PALETTE_TILE_OPAQUE_OFFSET:04X}",
        f"RTYPE_TARGET_PAL_TILE_ALPHA  EQU ${PALETTE_TILE_TRANSPARENT_OFFSET:04X}",
        f"RTYPE_TARGET_PAL_SPRITE      EQU ${PALETTE_SPRITE_OFFSET:04X}",
        f"RTYPE_TARGET_WORLD_OFFSET   EQU ${int(world['offset']):08X}",
        "RTYPE_TARGET_STAGE3_PATH     EQU $6F8A",
        "",
    ))


def main() -> int:
    pack, manifest = build_target_pack()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(pack)
    OUTPUT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUTPUT_INC.write_text(_generated_inc(manifest), encoding="utf-8")
    print(
        f"Target pack: {len(pack)} Б / {len(pack) // PAGE_SIZE} страниц, "
        f"8 stages, 788 событий, SHA256 {manifest['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
