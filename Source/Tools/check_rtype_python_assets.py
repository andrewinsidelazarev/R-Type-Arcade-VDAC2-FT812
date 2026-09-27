#!/usr/bin/env python3
"""Проверить точные HQ-артефакты, сгенерированные из активного Python."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "Build" / "rtype_python_assets.json"
SPRITE_CELL_BYTES = 27 * 30 * 2
TEMPLATE_HEADER = struct.Struct("<4sBBHIII")
TEMPLATE_RECORD = struct.Struct("<HBBHhhHBBHH")
TEMPLATE_STATE = struct.Struct("<II")
TEMPLATE_CELL = struct.Struct("<IhhB")
LOOKUP_RECORD = struct.Struct("<HBBHIIHBB")
FT812_ARGB4 = 6
FT812_PALETTED4444 = 15
NO_PALETTE = 0xFFFFFFFF
DL_BITMAP_SOURCE = 0x01000000
DL_BITMAP_LAYOUT = 0x07000000
DL_PALETTE_SOURCE = 0x2A000000
DL_VERTEX2F = 0x40000000


def _project_file(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"путь HQ artifact вышел за проект: {relative}") from exc
    return path


def _checked_bytes(record: dict[str, object]) -> bytes:
    path = _project_file(str(record["path"]))
    data = path.read_bytes()
    if len(data) != int(record["size"]):
        raise ValueError(f"{path}: размер не совпал с manifest")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"{path}: SHA-256 не совпал с manifest")
    return data


def _flip_argb4444(data: bytes, width: int, height: int,
                   flip_x: bool, flip_y: bool) -> bytes:
    if len(data) != width * height * 2:
        raise ValueError("ARGB4444 cell имеет неверный размер")
    rows = [
        [data[(y * width + x) * 2:(y * width + x + 1) * 2]
         for x in range(width)]
        for y in range(height)
    ]
    if flip_x:
        rows = [list(reversed(row)) for row in rows]
    if flip_y:
        rows.reverse()
    return b"".join(pixel for row in rows for pixel in row)


def _decode_ft812_entry(raw: bytes, entry: dict[str, object]) -> bytes:
    offset = int(entry["offset"])
    size = int(entry["size"])
    width = int(entry["width"])
    height = int(entry["height"])
    stride = int(entry["stride"])
    format_code = int(entry["format_code"])
    if offset < 0 or size < 0 or offset + size > len(raw):
        raise ValueError("FT812 sprite payload вышел за pack")
    payload = raw[offset:offset + size]
    if format_code == FT812_ARGB4:
        if (stride != width * 2 or size != stride * height or
                entry.get("palette_offset") is not None):
            raise ValueError("ARGB4 metadata не соответствует FT812")
        decoded = payload
    elif format_code == FT812_PALETTED4444:
        palette_offset = entry.get("palette_offset")
        if (stride != width or size != stride * height or
                palette_offset is None):
            raise ValueError("PALETTED4444 metadata не соответствует FT812")
        palette_at = int(palette_offset)
        if palette_at < 0 or palette_at + 512 > len(raw):
            raise ValueError("FT812 palette вышла за pack")
        palette = raw[palette_at:palette_at + 512]
        decoded = b"".join(
            palette[index * 2:index * 2 + 2] for index in payload)
    else:
        raise ValueError(f"неподдерживаемый FT812 bitmap format {format_code}")
    if hashlib.sha256(decoded).hexdigest() != entry["decoded_sha256"]:
        raise ValueError("FT812 sprite decoded SHA-256 не совпал")
    if hashlib.sha256(payload).hexdigest() != entry["payload_sha256"]:
        raise ValueError("FT812 sprite payload SHA-256 не совпал")
    return decoded


def _atomic_manifest_write(manifest: dict[str, object]) -> None:
    """Replace the manifest only after a complete deterministic refresh."""
    encoded = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=MANIFEST.parent,
                prefix=MANIFEST.name + ".", suffix=".tmp") as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, MANIFEST)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(*, refresh_generated_tables: bool = False) -> int:
    manifest_source = MANIFEST.read_bytes()
    manifest = json.loads(manifest_source.decode("utf-8"))
    if manifest.get("format") != "rtype-python-hq-assets-v2":
        raise ValueError("неверный формат Python HQ asset manifest")
    if manifest.get("pixel_format") != "ARGB4444 little-endian":
        raise ValueError("Python HQ assets должны оставаться ARGB4444 little-endian")
    if manifest.get("terrain_cell") != [14, 15]:
        raise ValueError("изменена Python terrain cell 14×15")
    if manifest.get("sprite_cell") != [27, 30]:
        raise ValueError("изменена Python sprite cell 27×30")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 11:
        raise ValueError("ожидалось десять terrain sets и один sprite set")
    checked_bytes = 0
    sprite_record: dict[str, object] | None = None
    for artifact in artifacts:
        data = _checked_bytes(artifact)
        checked_bytes += len(data)
        kind = artifact.get("kind")
        if kind == "terrain-section-working-set":
            if len(data) > 0x100000 or len(data) % (14 * 15 * 2):
                raise ValueError("terrain working set нарушил размер ячейки/секции")
        elif kind == "sprite-bootstrap-working-set":
            if sprite_record is not None:
                raise ValueError("повторный sprite bootstrap")
            sprite_record = artifact
            if len(data) > 0x040000 or len(data) % 4:
                raise ValueError("sprite bootstrap не помещается в RAM_G cache")
        else:
            raise ValueError(f"неизвестный HQ artifact kind: {kind}")
    if sprite_record is None:
        raise ValueError("нет sprite bootstrap")

    raw = _checked_bytes(sprite_record)
    if (sprite_record.get("format") != "pyz80-ft812-cell-pack-v1" or
            int(sprite_record.get("alignment", 0)) != 4 or
            int(sprite_record.get("raw_argb4444_bytes", -1)) !=
            int(sprite_record.get("unique_cells", -1)) *
            SPRITE_CELL_BYTES or
            int(sprite_record.get("saved_bytes", -1)) !=
            int(sprite_record["raw_argb4444_bytes"]) - len(raw)):
        raise ValueError("неверный lossless hybrid FT812 pack manifest")
    palette_rows = sprite_record.get("palettes")
    if (not isinstance(palette_rows, list) or
            len(palette_rows) != int(sprite_record.get("palette_count", -1))):
        raise ValueError("FT812 palette table потеряна")
    for palette in palette_rows:
        offset = int(palette["offset"])
        size = int(palette["size"])
        if (size != 512 or offset & 1 or offset + size > len(raw) or
                hashlib.sha256(raw[offset:offset + size]).hexdigest() !=
                palette["sha256"] or
                not 1 <= int(palette["color_count"]) <= 256):
            raise ValueError("FT812 palette record повреждён")

    entry_rows = sprite_record.get("entries")
    if not isinstance(entry_rows, list):
        raise ValueError("FT812 sprite entries отсутствуют")
    format_counts = {"ARGB4": 0, "PALETTED4444": 0}
    decoded_by_key: dict[tuple[int, int, int], bytes] = {}
    entry_by_key: dict[tuple[int, int, int], dict[str, object]] = {}
    for entry in entry_rows:
        decoded = _decode_ft812_entry(raw, entry)
        source = _project_file(str(entry["source_path"]))
        source_data = source.read_bytes()
        if hashlib.sha256(source_data).hexdigest() != entry["source_sha256"]:
            raise ValueError(f"{source}: source SHA-256 изменён")
        source_at = int(entry["source_offset"])
        source_cell = source_data[source_at:source_at + SPRITE_CELL_BYTES]
        expected_decoded = _flip_argb4444(
            source_cell, int(entry["width"]), int(entry["height"]),
            bool(entry["flip_x"]), bool(entry["flip_y"]))
        if decoded != expected_decoded:
            raise ValueError("FT812 hybrid cell не даёт exact source pixels")
        format_name = str(entry["format"])
        if format_name not in format_counts:
            raise ValueError("FT812 format name повреждён")
        format_counts[format_name] += 1
        resource = str(entry["resource"])
        if resource.startswith("type") and len(resource) == 6:
            bank_key = 0x0100 | int(resource[4:], 16)
        elif resource == "palette-fallback":
            bank_key = int(entry["palette"]) & 0x0F
        else:
            raise ValueError(f"неизвестный Python sprite bank {resource}")
        key = (
            bank_key,
            int(bool(entry["flip_x"])) |
            (int(bool(entry["flip_y"])) << 1),
            int(entry["code"]),
        )
        if key in decoded_by_key:
            raise ValueError("повторный logical key в FT812 pack")
        decoded_by_key[key] = decoded
        entry_by_key[key] = entry
    if (format_counts != sprite_record.get("format_counts") or
            sum(format_counts.values()) !=
            int(sprite_record.get("logical_entries", -1))):
        raise ValueError("FT812 hybrid format counts не совпали")

    compressed_info = sprite_record["compressed"]
    compressed = _checked_bytes(compressed_info)
    zlib_size = int(compressed_info["zlib_size"])
    inflated = zlib.decompress(compressed[:zlib_size])
    if len(compressed) & 3 or inflated[:len(raw)] != raw:
        raise ValueError("FT812 zlib stream не восстанавливает точный sprite pack")

    lookup_info = sprite_record["lookup"]
    lookup = _checked_bytes(lookup_info)
    magic, version, record_size, count, raw_size, reserved = struct.unpack_from(
        "<4sBBHII", lookup)
    if count != int(lookup_info["record_count"]):
        raise ValueError("число записей HQ lookup не совпало")
    rows = [
        LOOKUP_RECORD.unpack_from(lookup, 16 + index * record_size)
        for index in range(count)
    ]
    if ((magic, version, record_size, raw_size, reserved) !=
            (b"HQA3", 3, LOOKUP_RECORD.size, len(raw), 0)):
        raise ValueError("повреждён заголовок HQ sprite lookup HQA3")
    if len(lookup) != 16 + count * LOOKUP_RECORD.size:
        raise ValueError("размер HQA3 не совпал с числом records")
    logical_rows = [(row[0], row[1], row[3]) for row in rows]
    if (logical_rows != sorted(logical_rows) or
            len(set(logical_rows)) != count):
        raise ValueError("HQ lookup должен быть сортированным и уникальным")
    expected: dict[tuple[int, int, int], tuple[int, ...]] = {}
    for entry in entry_rows:
        resource = str(entry["resource"])
        bank_key = (0x0100 | int(resource[4:], 16)
                    if resource.startswith("type") and len(resource) == 6
                    else int(entry["palette"]) & 0x0F)
        palette_offset = entry.get("palette_offset")
        expected[(bank_key,
                  int(bool(entry["flip_x"])) |
                  (int(bool(entry["flip_y"])) << 1),
                  int(entry["code"]))] = (
            int(entry["format_code"]), int(entry["offset"]),
            NO_PALETTE if palette_offset is None else int(palette_offset),
            int(entry["stride"]), int(entry["width"]), int(entry["height"]),
        )
    actual = {
        (bank_key, flags, code):
        (format_code, offset, palette_offset, stride, width, height)
        for (bank_key, flags, format_code, code, offset, palette_offset,
             stride, width, height) in rows
    }
    if actual != expected:
        raise ValueError("HQ lookup не соответствует Python logical keys")

    bank_resolution = sprite_record.get("bank_resolution")
    if not isinstance(bank_resolution, dict):
        raise ValueError("manifest не содержит active Python bank resolution")
    typed_directory = (
        ROOT / "Assets" / "Converted" / "Arcade" / "ResourceHQ")
    typed_actual = sorted(
        int(path.stem[len("RTYPE_SPRITES_TYPE"):len("RTYPE_SPRITES_TYPE") + 2],
            16)
        for path in typed_directory.glob(
            "RTYPE_SPRITES_TYPE??_HQ_ARGB4444.bin")
    )
    typed_report = bank_resolution.get("typed_resource_types")
    typed_bitset = bytes(
        sum(1 << bit for bit in range(8)
            if byte * 8 + bit in typed_actual)
        for byte in range(32))
    if (typed_report != typed_actual or
            int(bank_resolution.get("typed_resource_count", -1)) !=
            len(typed_actual) or
            bank_resolution.get("typed_bitset_sha256") !=
            hashlib.sha256(typed_bitset).hexdigest()):
        raise ValueError("typed availability не соответствует actual asset paths")

    template_info = sprite_record["templates"]
    templates = _checked_bytes(template_info)
    c_tables = template_info.get("c_tables")
    expected_c_paths = {
        "header": "Source/C/generated/rtype_python_hq_templates.h",
        "source": "Source/C/generated/rtype_python_hq_templates.c",
    }
    if not isinstance(c_tables, dict) or set(c_tables) != set(expected_c_paths):
        raise ValueError("manifest HQ templates не содержит обе C-таблицы")
    c_table_bytes: dict[str, bytes] = {}
    refreshed_c_tables: dict[str, dict[str, object]] = {}
    for table_name, expected_path in expected_c_paths.items():
        table_record = c_tables[table_name]
        if not isinstance(table_record, dict):
            raise ValueError(f"manifest C-table {table_name} повреждён")
        if table_record.get("path") != expected_path:
            raise ValueError(
                f"manifest C-table {table_name} указывает не в generated")
        if refresh_generated_tables:
            table_path = _project_file(expected_path)
            table_data = table_path.read_bytes()
            c_table_bytes[table_name] = table_data
            refreshed_c_tables[table_name] = {
                "path": expected_path,
                "size": len(table_data),
                "sha256": hashlib.sha256(table_data).hexdigest(),
            }
        else:
            c_table_bytes[table_name] = _checked_bytes(table_record)
    (template_magic, template_version, template_record_size,
     template_count, template_cell_count,
     template_cell_size, template_state_count) = \
        TEMPLATE_HEADER.unpack_from(templates)
    if (template_magic, template_version, template_record_size,
            template_count, template_cell_count, template_cell_size,
            template_state_count) != (
            b"HQT3", 3, TEMPLATE_RECORD.size,
            int(template_info["record_count"]),
            int(template_info["cell_count"]), TEMPLATE_CELL.size,
            int(template_info["state_count"])):
        raise ValueError("повреждён заголовок HQ sprite templates")
    template_rows = [
        TEMPLATE_RECORD.unpack_from(
            templates, TEMPLATE_HEADER.size + index * TEMPLATE_RECORD.size)
        for index in range(template_count)
    ]
    if [(row[0], row[3]) for row in template_rows] != sorted(
            (row[0], row[3]) for row in template_rows):
        raise ValueError("HQ sprite templates не сортированы по bank/address")

    # Rebuild the same deterministic bounded open-address resolver used by
    # the generator. This checks both manifest metadata and the literal C
    # table; a stale/colliding stored index cannot silently become a match
    # because lookup is proved using the complete bank+descriptor key.
    hash_slot_count = 2
    while hash_slot_count < max(2, template_count * 2):
        hash_slot_count <<= 1
    while True:
        hash_slots = [0] * hash_slot_count
        hash_max_probe = 0
        for template_index, row in enumerate(template_rows):
            bank_key = int(row[0])
            descriptor_address = int(row[3])
            slot = (
                bank_key ^ (bank_key >> 8) ^ descriptor_address ^
                (descriptor_address >> 8)
            ) & (hash_slot_count - 1)
            probe = 0
            while hash_slots[slot] != 0:
                slot = (slot + 1) & (hash_slot_count - 1)
                probe += 1
            hash_slots[slot] = template_index + 1
            hash_max_probe = max(hash_max_probe, probe)
        if hash_max_probe <= 4:
            break
        hash_slot_count <<= 1
        if hash_slot_count > 0x8000:
            raise ValueError("HQT3 resolver hash не удаётся ограничить")
    expected_resolver_hash = {
        "algorithm": "xor-u16-bytes-open-address-v1",
        "seed": 0,
        "slot_count": hash_slot_count,
        "entry_bytes": 2,
        "table_bytes": hash_slot_count * 2,
        "batch_geometry_bytes": template_count * 12,
        "load_count": template_count,
        "max_preceding_probes": hash_max_probe,
        "max_lookup_probes": hash_max_probe + 1,
        "empty_entry": 0,
        "stored_value": "template_index_plus_one",
    }
    if (not refresh_generated_tables and
            template_info.get("resolver_hash") != expected_resolver_hash):
        raise ValueError(
            "manifest HQT3 resolver hash не детерминирован из records")
    source_text = c_table_bytes["source"].decode("utf-8")
    hash_match = re.search(
        r"PyZ80FT_HQTemplateHash\[PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS\]"
        r"\s*=\s*\{(.*?)\};", source_text, re.DOTALL)
    if hash_match is None:
        raise ValueError("generated C source потерял HQT3 resolver hash")
    source_hash_slots = [
        int(value) for value in re.findall(r"\b(\d+)u\b", hash_match.group(1))
    ]
    if source_hash_slots != hash_slots:
        raise ValueError("generated C resolver hash не равен HQT3 records")
    header_text = c_table_bytes["header"].decode("utf-8")
    for macro, value in (
            ("PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS", hash_slot_count),
            ("PYZ80_FT_HQ_TEMPLATE_HASH_MAX_PROBE", hash_max_probe)):
        if f"#define {macro} {value}u" not in header_text:
            raise ValueError(f"generated C header потерял {macro}")
    for template_index, row in enumerate(template_rows):
        bank_key = int(row[0])
        descriptor_address = int(row[3])
        slot = (
            bank_key ^ (bank_key >> 8) ^ descriptor_address ^
            (descriptor_address >> 8)
        ) & (hash_slot_count - 1)
        resolved = None
        for _probe in range(hash_max_probe + 1):
            stored = hash_slots[slot]
            if stored == 0 or stored - 1 >= template_count:
                break
            candidate = template_rows[stored - 1]
            if ((int(candidate[0]), int(candidate[3])) ==
                    (bank_key, descriptor_address)):
                resolved = stored - 1
                break
            slot = (slot + 1) & (hash_slot_count - 1)
        if resolved != template_index:
            raise ValueError(
                "generated HQT3 hash/full-key resolver не покрывает records")
    state_base = TEMPLATE_HEADER.size + template_count * TEMPLATE_RECORD.size
    cell_base = state_base + template_state_count * TEMPLATE_STATE.size
    if len(templates) != cell_base + template_cell_count * TEMPLATE_CELL.size:
        raise ValueError("размер HQ sprite templates не совпал с таблицами")
    state_rows = [
        TEMPLATE_STATE.unpack_from(
            templates, state_base + index * TEMPLATE_STATE.size)
        for index in range(template_state_count)
    ]
    state_report = template_info.get("states")
    if (not isinstance(state_report, list) or
            len(state_report) != template_state_count or
            int(template_info.get("state_record_size", 0)) !=
            TEMPLATE_STATE.size):
        raise ValueError("manifest HQT3 bitmap states повреждён")
    expected_states = [
        (int(state["layout"]), int(state["palette_ram_g"]))
        for state in state_report
    ]
    if state_rows != expected_states or len(set(state_rows)) != len(state_rows):
        raise ValueError("binary/manifest HQT3 bitmap states mismatch")
    for layout, palette_ram_g in state_rows:
        format_code = (layout >> 19) & 0x1F
        stride = (layout >> 9) & 0x3FF
        height = layout & 0x1FF
        if ((layout & 0xFF000000) != DL_BITMAP_LAYOUT or height == 0 or
                format_code not in (FT812_ARGB4, FT812_PALETTED4444)):
            raise ValueError("HQT3 содержит неверный BITMAP_LAYOUT")
        if ((format_code == FT812_ARGB4) !=
                (palette_ram_g == NO_PALETTE)):
            raise ValueError("HQT3 format/palette state несовместимы")
        if stride == 0:
            raise ValueError("HQT3 bitmap stride равен нулю")
    report_rows = template_info.get("records")
    if not isinstance(report_rows, list) or len(report_rows) != template_count:
        raise ValueError("manifest HQ templates не содержит все records")
    covered_keys: set[tuple[int, int, int]] = set()
    next_cell = 0
    for binary, report_row in zip(template_rows, report_rows):
        expected_row = (
            int(report_row["bank_key"]), int(report_row["flags"]),
            int(report_row["resource_type"]),
            int(report_row["descriptor_address"]), int(report_row["dx"]),
            int(report_row["dy"]), int(report_row["code"]),
            int(report_row["width"]), int(report_row["height"]),
            int(report_row["cell_first"]), int(report_row["cell_count"]),
        )
        if binary != expected_row or binary[9] != next_cell:
            raise ValueError("binary/manifest HQ template record mismatch")
        (bank_key, flags, _resource_hint, _address, _dx, _dy, code,
         width, height, first, cells) = binary
        if cells != width * height:
            raise ValueError("HQ template cell count не равен width×height")
        report_cells = report_row.get("cells")
        if not isinstance(report_cells, list) or len(report_cells) != cells:
            raise ValueError("manifest HQ template потерял cells")
        for ordinal, report_cell in enumerate(report_cells):
            cell_x, cell_y = divmod(ordinal, height)
            source_x = width - 1 - cell_x if flags & 1 else cell_x
            source_y = height - 1 - cell_y if flags & 2 else cell_y
            cell_code = (code + 8 * source_x + source_y) & 0x0FFF
            key = (bank_key, flags, cell_code)
            covered_keys.add(key)
            try:
                (expected_format, expected_offset, expected_palette_offset,
                 expected_stride, expected_width, expected_height) = actual[key]
            except KeyError as exc:
                raise ValueError(f"HQ template key отсутствует в HQA3: {key}") from exc
            expected_ramg = int(sprite_record["ram_g_base"]) + expected_offset
            expected_palette_ramg = (
                NO_PALETTE if expected_palette_offset == NO_PALETTE else
                int(sprite_record["ram_g_base"]) + expected_palette_offset)
            expected_layout = (
                DL_BITMAP_LAYOUT | (expected_format << 19) |
                (expected_stride << 9) | expected_height)
            try:
                expected_state_index = state_rows.index(
                    (expected_layout, expected_palette_ramg))
            except ValueError as exc:
                raise ValueError("HQA3 cell state отсутствует в HQT3") from exc
            expected_cell = (
                expected_ramg,
                round(cell_x * 16 * 5 / 3),
                cell_y * 30,
                expected_state_index,
            )
            packed_at = cell_base + (first + ordinal) * TEMPLATE_CELL.size
            binary_cell = TEMPLATE_CELL.unpack_from(templates, packed_at)
            report_tuple = (
                int(report_cell["ram_g"]), int(report_cell["local_x"]),
                int(report_cell["local_y"]), int(report_cell["state_index"]),
            )
            if binary_cell != expected_cell or report_tuple != expected_cell:
                raise ValueError("HQ template cell не соответствует Python draw")
            if (int(report_cell["format"]) != expected_format or
                    int(report_cell["stride"]) != expected_stride or
                    int(report_cell["width"]) != expected_width or
                    int(report_cell["height"]) != expected_height or
                    int(report_cell["layout"]) != expected_layout or
                    int(report_cell["palette_ram_g"]) !=
                    expected_palette_ramg or key not in entry_by_key):
                raise ValueError("HQT3 expanded cell metadata не равно HQA3")
        next_cell += cells
    if next_cell != template_cell_count or covered_keys != set(actual):
        raise ValueError("HQ templates не покрывают HQA3 ровно один working set")

    append_info = template_info.get("append")
    if not isinstance(append_info, dict):
        raise ValueError("manifest HQ templates не содержит CMD_APPEND pack")
    append_pack = _checked_bytes(append_info)
    append_base = (int(sprite_record["ram_g_base"]) + len(raw) + 3) & ~3
    if (int(append_info.get("ram_g_base", -1)) != append_base or
            int(append_info.get("alignment", 0)) != 4):
        raise ValueError("CMD_APPEND pack не следует сразу за HQ pixels")

    def logical_vertex(value: int) -> int:
        magnitude = (abs(value) * 64 + 2) // 5
        return -magnitude if value < 0 else magnitude

    def signed15(value: int) -> int:
        return value - 0x8000 if value & 0x4000 else value

    unique: list[bytes] = []
    unique_index: dict[bytes, int] = {}
    mapping: list[int] = []
    for report_row in report_rows:
        report_cells = report_row["cells"]
        for phase_x in range(5):
            for phase_y in range(5):
                words: list[int] = []
                current_layout: int | None = None
                current_palette: int | None = None
                for report_cell in report_cells:
                    layout = int(report_cell["layout"])
                    format_code = int(report_cell["format"])
                    palette_ram_g = int(report_cell["palette_ram_g"])
                    if layout != current_layout:
                        words.append(layout)
                        current_layout = layout
                    if (format_code == FT812_PALETTED4444 and
                            palette_ram_g != current_palette):
                        words.append(DL_PALETTE_SOURCE | palette_ram_g)
                        current_palette = palette_ram_g
                    local_x = int(report_cell["local_x"])
                    local_y = int(report_cell["local_y"])
                    relative_x = (
                        logical_vertex(phase_x + local_x) -
                        logical_vertex(phase_x))
                    relative_y = (
                        logical_vertex(phase_y + local_y) -
                        logical_vertex(phase_y))
                    words.extend((
                        DL_BITMAP_SOURCE |
                        (int(report_cell["ram_g"]) & 0x003FFFFF),
                        DL_VERTEX2F |
                        ((relative_x & 0x7FFF) << 15) |
                        (relative_y & 0x7FFF),
                    ))
                blob = struct.pack(f"<{len(words)}I", *words)
                blob_index = unique_index.get(blob)
                if blob_index is None:
                    blob_index = len(unique)
                    unique_index[blob] = blob_index
                    unique.append(blob)
                mapping.append(blob_index)

                # Prove the phase decomposition against direct coordinates on
                # both sides of zero, not merely against its own pack bytes.
                for base_x, base_y in (
                        (phase_x - 505, phase_y - 505),
                        (phase_x + 500, phase_y + 500)):
                    expanded: list[int] = []
                    for word in words:
                        if word & 0xC0000000 == DL_VERTEX2F:
                            relative_x = signed15((word >> 15) & 0x7FFF)
                            relative_y = signed15(word & 0x7FFF)
                            word = (DL_VERTEX2F |
                                    (((relative_x + logical_vertex(base_x)) &
                                      0x7FFF) << 15) |
                                    ((relative_y + logical_vertex(base_y)) &
                                     0x7FFF))
                        expanded.append(word)
                    direct: list[int] = []
                    current_layout = None
                    current_palette = None
                    for report_cell in report_cells:
                        layout = int(report_cell["layout"])
                        format_code = int(report_cell["format"])
                        palette_ram_g = int(report_cell["palette_ram_g"])
                        if layout != current_layout:
                            direct.append(layout)
                            current_layout = layout
                        if (format_code == FT812_PALETTED4444 and
                                palette_ram_g != current_palette):
                            direct.append(DL_PALETTE_SOURCE | palette_ram_g)
                            current_palette = palette_ram_g
                        direct.extend((
                            DL_BITMAP_SOURCE |
                            (int(report_cell["ram_g"]) & 0x003FFFFF),
                            DL_VERTEX2F |
                            ((logical_vertex(base_x +
                                int(report_cell["local_x"])) & 0x7FFF) << 15) |
                            (logical_vertex(base_y +
                                int(report_cell["local_y"])) & 0x7FFF),
                        ))
                    if expanded != direct:
                        raise ValueError(
                            "CMD_APPEND phase/translate не равен direct HQT3")

    expected_pack = b"".join(unique)
    mapping_bytes = bytes(mapping)
    if (append_pack != expected_pack or
            int(append_info.get("phase_count", -1)) != 5 or
            int(append_info.get("mapping_count", -1)) != len(mapping) or
            append_info.get("mapping_sha256") !=
            hashlib.sha256(mapping_bytes).hexdigest() or
            int(append_info.get("blob_count", -1)) != len(unique)):
        raise ValueError("CMD_APPEND pack/map не воспроизводится из HQT3")
    blob_rows = append_info.get("blobs")
    if not isinstance(blob_rows, list) or len(blob_rows) != len(unique):
        raise ValueError("manifest CMD_APPEND потерял blob records")
    offset = 0
    for blob, blob_row in zip(unique, blob_rows):
        expected_blob_row = {
            "ram_g": append_base + offset,
            "offset": offset,
            "size": len(blob),
            "word_count": len(blob) // 4,
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        if blob_row != expected_blob_row:
            raise ValueError("manifest CMD_APPEND blob record не совпал")
        offset += len(blob)
    padding = append_base - (int(sprite_record["ram_g_base"]) + len(raw))
    expected_inflate = raw + bytes(padding) + append_pack
    if (inflated != expected_inflate or
            int(compressed_info.get("raw_size", -1)) != len(inflated) or
            int(compressed_info.get("pixel_raw_size", -1)) != len(raw)):
        raise ValueError("CMD_INFLATE не содержит pixels+CMD_APPEND pack")

    # This proof is intentionally independent of active Python coverage.
    # Re-emit generated tables into a temporary root solely from the already
    # verified HQT3/manifest records and compare every byte. Refresh mode may
    # bless new size/SHA metadata only after this same strict proof; normal
    # checker mode therefore also detects any hand-edited generated table.
    sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
    sys.path.insert(0, str(ROOT / "Source" / "Tools"))
    from rtype_python_assets import _emit_sprite_template_c

    with tempfile.TemporaryDirectory(
            prefix="rtype-hqt-manifest-refresh-") as temporary_root_text:
        temporary_root = Path(temporary_root_text)
        emitted = _emit_sprite_template_c(
            temporary_root,
            report_rows,
            state_report,
            mapping,
            blob_rows,
            tuple(int(item) for item in typed_report),
        )
        if emitted.get("resolver_hash") != expected_resolver_hash:
            raise ValueError(
                "temporary HQT3 generator changed resolver metadata")
        for table_name, relative_path in expected_c_paths.items():
            expected_bytes = (temporary_root / relative_path).read_bytes()
            if c_table_bytes[table_name] != expected_bytes:
                actual_lines = c_table_bytes[table_name].decode(
                    "utf-8").splitlines()
                expected_lines = expected_bytes.decode("utf-8").splitlines()
                first_difference = next(
                    (index for index, pair in enumerate(zip(
                        actual_lines, expected_lines), start=1)
                     if pair[0] != pair[1]),
                    min(len(actual_lines), len(expected_lines)) + 1)
                raise ValueError(
                    f"generated C-table {table_name} не воспроизводится "
                    "из зафиксированного HQT3: первая разница в строке "
                    f"{first_difference}; actual/expected SHA256 "
                    f"{hashlib.sha256(c_table_bytes[table_name]).hexdigest()}/"
                    f"{hashlib.sha256(expected_bytes).hexdigest()}")

    totals = manifest.get("totals", {})
    if int(totals.get("bytes", -1)) != checked_bytes:
        raise ValueError("итоговый размер HQ artifacts не совпал")
    if refresh_generated_tables:
        if MANIFEST.read_bytes() != manifest_source:
            raise ValueError(
                "asset manifest изменился во время deterministic refresh")
        for table_name, relative_path in expected_c_paths.items():
            if _project_file(relative_path).read_bytes() != c_table_bytes[table_name]:
                raise ValueError(
                    f"generated C-table {table_name} изменилась во время refresh")
        # Match the common generator's insertion order as well as its values,
        # so a later full translation does not create a formatting-only diff.
        template_info.pop("resolver_hash", None)
        template_info.pop("c_tables", None)
        template_info["resolver_hash"] = expected_resolver_hash
        template_info["c_tables"] = refreshed_c_tables
        _atomic_manifest_write(manifest)
        print(
            "Refreshed generated HQT3 manifest metadata atomically: "
            f"{MANIFEST}")
    print(
        "Python HQ assets: "
        f"{len(artifacts)} sets, {checked_bytes} bytes, "
        f"sprite {len(raw)} -> {len(compressed)} bytes, {count} keys, "
        f"{template_count} templates/{template_cell_count} cells, "
        f"CMD_APPEND {len(unique)} blobs/{len(append_pack)} bytes"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-generated-tables", action="store_true",
        help=(
            "атомарно обновить только metadata generated HQT3 .h/.c после "
            "их byte-exact воспроизведения из существующего manifest"),
    )
    arguments = parser.parse_args()
    raise SystemExit(main(
        refresh_generated_tables=arguments.refresh_generated_tables))
