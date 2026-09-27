#!/usr/bin/env python3
"""Проектный адаптер точных HQ-ресурсов активной Python-версии R-Type."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pyz80_compiler.assets import (
    ARGB4444_LE,
    AssetCompileError,
    AssetPackBudget,
    CellBankSpec,
    CellKey,
    CellSourceKey,
    compile_cell_assets,
)
from pyz80_compiler.ft812_assets import (
    FT812_ARGB4,
    FT812_PALETTED4444,
    FT812AssetPackBudget,
    compile_ft812_cell_assets,
)


ASSET_PLAN_FORMAT = "rtype-python-hq-assets-v2"
TERRAIN_CELL = (14, 15)
SPRITE_CELL = (27, 30)
TERRAIN_CELL_BYTES = TERRAIN_CELL[0] * TERRAIN_CELL[1] * 2
SPRITE_CELL_BYTES = SPRITE_CELL[0] * SPRITE_CELL[1] * 2
SPRITE_TEMPLATE_HEADER = struct.Struct("<4sBBHIII")
SPRITE_TEMPLATE_RECORD = struct.Struct("<HBBHhhHBBHH")
SPRITE_TEMPLATE_STATE = struct.Struct("<II")
SPRITE_TEMPLATE_CELL = struct.Struct("<IhhB")
SPRITE_LOOKUP_RECORD = struct.Struct("<HBBHIIHBB")
SPRITE_BANK_TYPED = 1
SPRITE_BANK_FALLBACK = 0
SPRITE_NO_PALETTE = 0xFFFFFFFF
DL_BITMAP_SOURCE = 0x01000000
DL_BITMAP_LAYOUT = 0x07000000
DL_PALETTE_SOURCE = 0x2A000000
DL_VERTEX2F = 0x40000000


def encode_sprite_bank_key(kind: int, value: int) -> int:
    """Pack active Python ``(kind, value)`` bank identity into uint16."""
    if kind not in (SPRITE_BANK_FALLBACK, SPRITE_BANK_TYPED):
        raise AssetCompileError(f"unknown Python sprite bank kind {kind}")
    if not 0 <= value <= 0xFF:
        raise AssetCompileError(f"Python sprite bank value {value} is not uint8")
    if kind == SPRITE_BANK_FALLBACK and value > 0x0F:
        raise AssetCompileError("fallback sprite bank value is not a palette slot")
    return (kind << 8) | value


@dataclass(frozen=True)
class SpriteTemplateSource:
    """One descriptor/resource pair selected by active Python preload."""

    descriptor_address: int
    bank_key: int
    resource_type: int
    dx: int
    dy: int
    code: int
    width: int
    height: int
    flip_x: bool
    flip_y: bool

    def __post_init__(self) -> None:
        if not 0 <= self.descriptor_address <= 0xFFFF:
            raise AssetCompileError("sprite descriptor address is not uint16")
        if not 0 <= self.bank_key <= 0x01FF:
            raise AssetCompileError("sprite bank key is not typed/fallback uint16")
        bank_kind = self.bank_key >> 8
        bank_value = self.bank_key & 0xFF
        encode_sprite_bank_key(bank_kind, bank_value)
        if not 0 <= self.resource_type <= 0xFF:
            raise AssetCompileError("sprite resource type is not uint8")
        if not -0x8000 <= self.dx <= 0x7FFF or not -0x8000 <= self.dy <= 0x7FFF:
            raise AssetCompileError("sprite descriptor delta is not int16")
        if not 0 <= self.code <= 0xFFFF:
            raise AssetCompileError("sprite descriptor code is not uint16")
        if not 1 <= self.width <= 0xFF or not 1 <= self.height <= 0xFF:
            raise AssetCompileError("sprite descriptor dimensions are not uint8")


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _atomic_text(path: Path, text: str) -> None:
    _atomic_bytes(path, text.encode("utf-8"))


def _logical_vertex(value: int) -> int:
    """Logical 640-wide coordinate -> VERTEX_FORMAT(3), nearest rational."""
    return _logical_vertex_signed(value) & 0xFFFF


def _logical_vertex_signed(value: int) -> int:
    """Signed form of the exact Python-logical FT812 vertex coordinate."""
    magnitude = (abs(value) * 64 + 2) // 5
    return -magnitude if value < 0 else magnitude


def _bitmap_layout_word(format_code: int, stride: int, height: int) -> int:
    if format_code not in (FT812_ARGB4, FT812_PALETTED4444):
        raise AssetCompileError(f"unsupported FT812 sprite format {format_code}")
    if not 0 <= stride <= 0x3FF or not 0 <= height <= 0x1FF:
        raise AssetCompileError("sprite BITMAP_LAYOUT exceeds FT812 low fields")
    return (DL_BITMAP_LAYOUT | (format_code << 19) |
            (stride << 9) | height)


def _append_cell_words(
        cells: list[dict[str, int]], phase_x: int, phase_y: int,
        ) -> list[int]:
    """Emit the minimal self-contained state stream for one descriptor."""
    words: list[int] = []
    current_layout: int | None = None
    current_palette: int | None = None
    origin_x = _logical_vertex_signed(phase_x)
    origin_y = _logical_vertex_signed(phase_y)
    for cell in cells:
        format_code = int(cell["format"])
        layout = _bitmap_layout_word(
            format_code, int(cell["stride"]), int(cell["height"]))
        if layout != current_layout:
            words.append(layout)
            current_layout = layout
        palette_ram_g = int(cell["palette_ram_g"])
        if format_code == FT812_PALETTED4444:
            if (palette_ram_g == SPRITE_NO_PALETTE or
                    palette_ram_g & 1 or
                    not 0 <= palette_ram_g <= 0x003FFFFF):
                raise AssetCompileError(
                    "PALETTED4444 sprite has invalid PALETTE_SOURCE")
            if palette_ram_g != current_palette:
                words.append(DL_PALETTE_SOURCE | palette_ram_g)
                current_palette = palette_ram_g
        elif palette_ram_g != SPRITE_NO_PALETTE:
            raise AssetCompileError("ARGB4 sprite unexpectedly has a palette")

        ram_g = int(cell["ram_g"])
        if not 0 <= ram_g <= 0x003FFFFF:
            raise AssetCompileError("sprite BITMAP_SOURCE exceeds RAM_G")
        local_x = int(cell["local_x"])
        local_y = int(cell["local_y"])
        relative_x = (
            _logical_vertex_signed(phase_x + local_x) - origin_x)
        relative_y = (
            _logical_vertex_signed(phase_y + local_y) - origin_y)
        if not (-0x4000 <= relative_x < 0x4000 and
                -0x4000 <= relative_y < 0x4000):
            raise AssetCompileError(
                "CMD_APPEND relative vertex exceeds signed 15-bit")
        words.extend((
            DL_BITMAP_SOURCE | ram_g,
            DL_VERTEX2F |
            ((relative_x & 0x7FFF) << 15) |
            (relative_y & 0x7FFF),
        ))
    return words


def _build_append_template_pack(
        records: list[dict[str, object]], ram_g_base: int,
        ) -> tuple[bytes, list[int], list[dict[str, object]]]:
    """Build phase-exact pure-DL sprite templates for FT812 CMD_APPEND.

    With VERTEX_FORMAT(3), a VERTEX2F raw unit is two 1/16-pixel units.
    VERTEX_TRANSLATE is expressed directly in 1/16-pixel units.  Therefore
    the immutable blob stores ``F(base + local) - F(base)`` and the producer
    emits ``2 * F(base)`` as translation, where F(q)=round(q*64/5).  F(q+5)
    is F(q)+64, so only the Python remainders base_x%5/base_y%5 are needed.
    """
    unique: list[bytes] = []
    index_by_blob: dict[bytes, int] = {}
    mapping: list[int] = []
    for record in records:
        cells = record["cells"]
        if not isinstance(cells, list):
            raise AssetCompileError("HQ template cells must be a list")
        for phase_x in range(5):
            for phase_y in range(5):
                words = _append_cell_words(cells, phase_x, phase_y)
                payload = struct.pack(f"<{len(words)}I", *words)
                blob_index = index_by_blob.get(payload)
                if blob_index is None:
                    blob_index = len(unique)
                    if blob_index > 0xFF:
                        raise AssetCompileError(
                            "CMD_APPEND template id does not fit uint8")
                    index_by_blob[payload] = blob_index
                    unique.append(payload)
                mapping.append(blob_index)
    if len(mapping) != len(records) * 25:
        raise AssetCompileError("CMD_APPEND phase mapping is incomplete")

    packed = bytearray()
    blob_records: list[dict[str, object]] = []
    for payload in unique:
        if len(packed) & 3:
            raise AssetCompileError("CMD_APPEND blob lost 4-byte alignment")
        offset = len(packed)
        packed += payload
        blob_records.append({
            "ram_g": ram_g_base + offset,
            "offset": offset,
            "size": len(payload),
            "word_count": len(payload) // 4,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return bytes(packed), mapping, blob_records


def _emit_sprite_template_c(
        root: Path, records: list[dict[str, object]],
        bitmap_states: list[dict[str, int]],
        append_mapping: list[int],
        append_blobs: list[dict[str, object]],
        typed_resource_types: tuple[int, ...],
        ) -> dict[str, object]:
    """Emit immutable compiler-bank tables used by the C queue producer."""
    generated = root / "Source" / "C" / "generated"
    header_path = generated / "rtype_python_hq_templates.h"
    source_path = generated / "rtype_python_hq_templates.c"
    cells = [cell for record in records for cell in record["cells"]]
    batch_geometry: list[tuple[int, int, int, int, int, int]] = []
    for record in records:
        x_bias = int(record["dx"]) - 320
        y_bias = (384 - int(record["dy"]) -
                  int(record["height"]) * 16)
        x_min = max(-0x8000, -1535 - x_bias)
        x_max = min(0x7FFF, 1535 - x_bias)
        y_min = max(-0x8000, y_bias - 1365)
        y_max = min(0x7FFF, y_bias + 1365)
        if x_min > x_max:
            x_min, x_max = 1, 0
        if y_min > y_max:
            y_min, y_max = 1, 0
        batch_geometry.append(
            (x_min, x_max, x_bias & 0xFFFF,
             y_min, y_max, y_bias & 0xFFFF))
    # The batch producer resolves each literal Python (bank, descriptor) pair
    # once during fail-before-publication preflight, then emits only from its
    # private cache. A binary search is disproportionately expensive on Z80,
    # so generate a bounded open-address table. The hash is deliberately
    # byte-only (four XORs); widening the power-of-two table until every
    # generated key has at most four preceding probes keeps lookup time bounded
    # without embedding any game-specific decision tree in the C/ASM backend.
    if len(records) >= 0xFFFF:
        raise AssetCompileError("HQT3 template hash exceeds uint16 indices")
    hash_slot_count = 2
    while hash_slot_count < max(2, len(records) * 2):
        hash_slot_count <<= 1
    while True:
        hash_slots = [0] * hash_slot_count
        hash_max_probe = 0
        for template_index, record in enumerate(records):
            bank_key = int(record["bank_key"])
            descriptor = int(record["descriptor_address"])
            slot = (bank_key ^ (bank_key >> 8) ^ descriptor ^
                    (descriptor >> 8)) & (hash_slot_count - 1)
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
            raise AssetCompileError("HQT3 template hash cannot be bounded")
    header = f"""/* Generated from active Python M72SpriteAtlas preload. */
#ifndef RTYPE_PYTHON_HQ_TEMPLATES_H
#define RTYPE_PYTHON_HQ_TEMPLATES_H

#include <stdint.h>

#define PYZ80_FT_HQ_TEMPLATE_COUNT {len(records)}u
#define PYZ80_FT_ASM_HQ_TEMPLATE_COUNT {len(records)}
#define PYZ80_FT_HQ_TEMPLATE_CELL_COUNT {len(cells)}u
#define PYZ80_FT_HQ_BITMAP_STATE_COUNT {len(bitmap_states)}u
#define PYZ80_FT_HQ_APPEND_PHASE_COUNT 5u
#define PYZ80_FT_HQ_APPEND_ENTRY_COUNT {len(append_mapping)}u
#define PYZ80_FT_HQ_APPEND_BLOB_COUNT {len(append_blobs)}u
#define PYZ80_FT_ASM_HQ_APPEND_BLOB_COUNT {len(append_blobs)}
#define PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS {hash_slot_count}u
#define PYZ80_FT_HQ_TEMPLATE_HASH_MASK 0x{hash_slot_count - 1:04X}u
#define PYZ80_FT_HQ_TEMPLATE_HASH_MAX_PROBE {hash_max_probe}u
#define PYZ80_FT_TYPED_RESOURCE_BYTES 32u
#define PYZ80_FT_BANK_TYPED 0x0100u
#define PYZ80_FT_BANK_FALLBACK 0x0000u
#define PYZ80_FT_BITMAP_ARGB4 {FT812_ARGB4}u
#define PYZ80_FT_BITMAP_PALETTED4444 {FT812_PALETTED4444}u
#define PYZ80_FT_NO_PALETTE 0xFFFFFFFFul

typedef struct PyZ80FtHQTemplate {{
    uint16_t bank_key;
    uint8_t flags;
    uint8_t resource_hint;
    uint16_t descriptor_address;
    int16_t dx;
    int16_t dy;
    uint16_t code;
    uint8_t width;
    uint8_t height;
    uint16_t cell_first;
    uint16_t cell_count;
}} PyZ80FtHQTemplate;

typedef struct PyZ80FtHQTemplateCell {{
    uint32_t ram_g;
    int16_t local_x;
    int16_t local_y;
    uint8_t state_index;
}} PyZ80FtHQTemplateCell;

typedef struct PyZ80FtHQBitmapState {{
    uint32_t layout;
    uint32_t palette_ram_g;
}} PyZ80FtHQBitmapState;

/* Exact anchor-domain guard and modulo-16-bit bias for the assembly batch
 * preflight. Passing the bounds proves that the biased result is inside the
 * public native-coordinate domain, so the low word is the exact result. */
typedef struct PyZ80FtHQBatchGeometry {{
    int16_t anchor_x_min;
    int16_t anchor_x_max;
    uint16_t native_x_bias;
    int16_t anchor_y_min;
    int16_t anchor_y_max;
    uint16_t native_y_bias;
}} PyZ80FtHQBatchGeometry;

_Static_assert(sizeof(PyZ80FtHQTemplate) == 18,
               "HQ template ABI changed");
_Static_assert(sizeof(PyZ80FtHQTemplateCell) == 9,
               "HQ template cell ABI changed");
_Static_assert(sizeof(PyZ80FtHQBitmapState) == 8,
               "HQ bitmap state ABI changed");
_Static_assert(sizeof(PyZ80FtHQBatchGeometry) == 12,
               "HQ batch geometry ABI changed");

extern const PyZ80FtHQTemplate
    PyZ80FT_HQTemplates[PYZ80_FT_HQ_TEMPLATE_COUNT];
/* Entry zero is empty; every other entry is template_index + 1. */
extern const uint16_t
    PyZ80FT_HQTemplateHash[PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS];
extern const uint8_t
    PyZ80FT_TypedResources[PYZ80_FT_TYPED_RESOURCE_BYTES];
extern const PyZ80FtHQTemplateCell
    PyZ80FT_HQTemplateCells[PYZ80_FT_HQ_TEMPLATE_CELL_COUNT];
extern const PyZ80FtHQBitmapState
    PyZ80FT_HQBitmapStates[PYZ80_FT_HQ_BITMAP_STATE_COUNT];
extern const PyZ80FtHQBatchGeometry
    PyZ80FT_HQBatchGeometry[PYZ80_FT_HQ_TEMPLATE_COUNT];
/* Map order is template, Python-positive x%5, Python-positive y%5. */
extern const uint8_t
    PyZ80FT_HQAppendMap[PYZ80_FT_HQ_APPEND_ENTRY_COUNT];
extern const uint32_t
    PyZ80FT_HQAppendAddress[PYZ80_FT_HQ_APPEND_BLOB_COUNT];
extern const uint16_t
    PyZ80FT_HQAppendSize[PYZ80_FT_HQ_APPEND_BLOB_COUNT];

#endif
"""
    lines = [
        "/* Generated from active Python M72SpriteAtlas.draw. */",
        '#include "rtype_python_hq_templates.h"',
        "",
        "const uint8_t",
        "PyZ80FT_TypedResources[PYZ80_FT_TYPED_RESOURCE_BYTES] = {",
    ]
    typed_set = set(typed_resource_types)
    typed_bytes = [
        sum(1 << bit for bit in range(8) if byte * 8 + bit in typed_set)
        for byte in range(32)
    ]
    for start in range(0, len(typed_bytes), 16):
        lines.append("    " + ", ".join(
            f"0x{value:02X}u" for value in typed_bytes[start:start + 16]
        ) + ",")
    lines.extend([
        "};",
        "",
        "const PyZ80FtHQTemplate",
        "PyZ80FT_HQTemplates[PYZ80_FT_HQ_TEMPLATE_COUNT] = {",
    ])
    for record in records:
        lines.append(
            "    { "
            f"0x{int(record['bank_key']):04X}u, "
            f"0x{int(record['flags']):02X}u, "
            f"0x{int(record['resource_type']):02X}u, "
            f"0x{int(record['descriptor_address']):04X}u, "
            f"{int(record['dx'])}, {int(record['dy'])}, "
            f"0x{int(record['code']):04X}u, "
            f"{int(record['width'])}u, {int(record['height'])}u, "
            f"{int(record['cell_first'])}u, {int(record['cell_count'])}u }},")
    lines.extend([
        "};",
        "",
        "const uint16_t",
        "PyZ80FT_HQTemplateHash[PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS] = {",
    ])
    for start in range(0, len(hash_slots), 16):
        lines.append("    " + ", ".join(
            f"{value}u" for value in hash_slots[start:start + 16]
        ) + ",")
    lines.extend([
        "};",
        "",
        "const PyZ80FtHQBatchGeometry",
        "PyZ80FT_HQBatchGeometry[PYZ80_FT_HQ_TEMPLATE_COUNT] = {",
    ])
    for x_min, x_max, x_bias, y_min, y_max, y_bias in batch_geometry:
        lines.append(
            "    { "
            f"{x_min}, {x_max}, 0x{x_bias:04X}u, "
            f"{y_min}, {y_max}, 0x{y_bias:04X}u }},")
    lines.extend([
        "};",
        "",
        "const PyZ80FtHQBitmapState",
        "PyZ80FT_HQBitmapStates[PYZ80_FT_HQ_BITMAP_STATE_COUNT] = {",
    ])
    for state in bitmap_states:
        lines.append(
            "    { "
            f"0x{int(state['layout']):08X}ul, "
            f"0x{int(state['palette_ram_g']):08X}ul }},")
    lines.extend([
        "};",
        "",
        "const PyZ80FtHQTemplateCell",
        "PyZ80FT_HQTemplateCells[PYZ80_FT_HQ_TEMPLATE_CELL_COUNT] = {",
    ])
    for cell in cells:
        lines.append(
            "    { "
            f"0x{int(cell['ram_g']):06X}ul, "
            f"{int(cell['local_x'])}, {int(cell['local_y'])}, "
            f"{int(cell['state_index'])}u }},")
    lines.extend([
        "};",
        "",
        "const uint8_t",
        "PyZ80FT_HQAppendMap[PYZ80_FT_HQ_APPEND_ENTRY_COUNT] = {",
    ])
    for start in range(0, len(append_mapping), 20):
        lines.append("    " + ", ".join(
            f"{value}u" for value in append_mapping[start:start + 20]
        ) + ",")
    lines.extend([
        "};",
        "",
        "const uint32_t",
        "PyZ80FT_HQAppendAddress[PYZ80_FT_HQ_APPEND_BLOB_COUNT] = {",
    ])
    for start in range(0, len(append_blobs), 6):
        lines.append("    " + ", ".join(
            f"0x{int(item['ram_g']):06X}ul"
            for item in append_blobs[start:start + 6]
        ) + ",")
    lines.extend([
        "};",
        "",
        "const uint16_t",
        "PyZ80FT_HQAppendSize[PYZ80_FT_HQ_APPEND_BLOB_COUNT] = {",
    ])
    for start in range(0, len(append_blobs), 12):
        lines.append("    " + ", ".join(
            f"{int(item['size'])}u"
            for item in append_blobs[start:start + 12]
        ) + ",")
    lines.extend(["};", ""])
    source = "\n".join(lines)
    _atomic_text(header_path, header)
    _atomic_text(source_path, source)

    def c_record(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        return {
            "path": path.resolve().relative_to(root.resolve()).as_posix(),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    return {
        "header": c_record(header_path),
        "source": c_record(source_path),
        "resolver_hash": {
            "algorithm": "xor-u16-bytes-open-address-v1",
            "seed": 0,
            "slot_count": hash_slot_count,
            "entry_bytes": 2,
            "table_bytes": hash_slot_count * 2,
            "batch_geometry_bytes": len(batch_geometry) * 12,
            "load_count": len(records),
            "max_preceding_probes": hash_max_probe,
            "max_lookup_probes": hash_max_probe + 1,
            "empty_entry": 0,
            "stored_value": "template_index_plus_one",
        },
    }


def _artifact_record(path: Path, root: Path, report: dict[str, object]
                     ) -> dict[str, object]:
    result = dict(report)
    result["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    return result


def _terrain_paths(root: Path, section: int, mode: str) -> tuple[Path, Path]:
    base = root / "Assets" / "Converted" / "Arcade" / "Stage1" / "Sections"
    prefix = f"STAGE1_S{section}"
    if mode == "base":
        suffix = "ATLAS_ARGB4444.bin"
    elif mode == "boss":
        suffix = "NORMAL9501_ATLAS_ARGB4444.bin"
    elif mode == "flash":
        suffix = "FLASH9500_ATLAS_ARGB4444.bin"
    else:
        raise AssetCompileError(f"неизвестный terrain mode {mode}")
    return tuple(base / f"{prefix}_{layer}_{suffix}" for layer in ("BG", "FG"))


def _compile_terrain_set(
        root: Path, output_directory: Path, section: int, mode: str,
        ) -> dict[str, object]:
    banks: list[CellBankSpec] = []
    requested: list[CellKey] = []
    for layer, path in zip(("bg", "fg"), _terrain_paths(root, section, mode)):
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise AssetCompileError(
                f"не читается Python terrain atlas {path}: {exc}"
            ) from exc
        if size % TERRAIN_CELL_BYTES:
            raise AssetCompileError(
                f"{path}: размер {size} не кратен {TERRAIN_CELL_BYTES}"
            )
        count = size // TERRAIN_CELL_BYTES
        source = CellSourceKey(
            "terrain", f"stage1_s{section}_{mode}_{layer}")
        banks.append(CellBankSpec(
            source, path, TERRAIN_CELL[0], TERRAIN_CELL[1], count))
        requested.extend(CellKey(source, code) for code in range(count))

    pack = compile_cell_assets(
        requested,
        banks,
        AssetPackBudget(
            max_logical_entries=2048,
            max_unique_cells=2048,
            max_bytes=0x100000,
            alignment=4,
        ),
        project_root=root,
    )
    output = output_directory / f"stage1_s{section}_{mode}_terrain.argb4444"
    _atomic_bytes(output, pack.data)
    record = _artifact_record(output, root, pack.report())
    record.update({
        "kind": "terrain-section-working-set",
        "stage": 1,
        "section": section,
        "mode": mode,
    })
    return record


def _sprite_bank(
        root: Path, palette: int, resource_type: int,
        typed_resource_types: frozenset[int],
        ) -> tuple[int, CellSourceKey, Path]:
    arcade = root / "Assets" / "Converted" / "Arcade"
    resource_type &= 0xFF
    typed = arcade / "ResourceHQ" / (
        f"RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin")
    if resource_type in typed_resource_types:
        if not typed.is_file():
            raise AssetCompileError(
                f"active Python selected missing typed sprite bank {typed}")
        return (encode_sprite_bank_key(SPRITE_BANK_TYPED, resource_type),
                CellSourceKey("sprite", f"type{resource_type:02X}"), typed)
    palette &= 0x0F
    fallback = arcade / "FullHQ" / (
        f"RTYPE_SPRITES_PAL{palette:02X}_HQ_ARGB4444.bin")
    if not fallback.is_file():
        raise AssetCompileError(
            f"active Python selected missing fallback sprite bank {fallback}")
    return (encode_sprite_bank_key(SPRITE_BANK_FALLBACK, palette),
            CellSourceKey("sprite", "palette-fallback", palette), fallback)


def _compile_sprite_bootstrap(
        root: Path,
        output_directory: Path,
        requests: Iterable[tuple[int, int, int, bool, bool]],
        templates: Iterable[SpriteTemplateSource],
        typed_resource_types: tuple[int, ...],
        ) -> dict[str, object]:
    typed_set = frozenset(typed_resource_types)
    keys: list[CellKey] = []
    source_paths: dict[CellSourceKey, Path] = {}
    bank_keys_by_source: dict[CellSourceKey, int] = {}
    for palette, resource_type, code, flip_x, flip_y in requests:
        bank_key, source, path = _sprite_bank(
            root, palette, resource_type, typed_set)
        previous = source_paths.setdefault(source, path)
        if previous.resolve() != path.resolve():
            raise AssetCompileError(
                f"{source.stable_name}: неоднозначный Python sprite bank"
            )
        previous_bank = bank_keys_by_source.setdefault(source, bank_key)
        if previous_bank != bank_key:
            raise AssetCompileError(
                f"{source.stable_name}: неоднозначный Python bank key")
        keys.append(CellKey(source, code & 0x0FFF, flip_x, flip_y))
    banks = [
        CellBankSpec(source, path, SPRITE_CELL[0], SPRITE_CELL[1], 4096)
        for source, path in sorted(source_paths.items())
    ]
    pack = compile_ft812_cell_assets(
        keys,
        banks,
        FT812AssetPackBudget(
            max_logical_entries=1024,
            max_unique_cells=1024,
            max_palettes=256,
            max_bytes=0x040000,
            alignment=4,
        ),
        project_root=root,
    )
    output = output_directory / "stage1_bootstrap_sprites.ft812"
    _atomic_bytes(output, pack.data)
    pack_report = pack.report()
    for packed_entry, report_entry in zip(pack.entries, pack_report["entries"]):
        report_entry.update({
            "namespace": packed_entry.key.source.namespace,
            "resource": packed_entry.key.source.resource,
            "palette": packed_entry.key.source.palette,
            "code": packed_entry.key.code,
            "flip_x": packed_entry.key.flip_x,
            "flip_y": packed_entry.key.flip_y,
        })
    record = _artifact_record(output, root, pack_report)
    ram_g_base = 0x0C0000
    lookup_rows: list[
        tuple[int, int, int, int, int, int, int, int, int]
    ] = []
    for entry in pack.entries:
        try:
            bank_key = bank_keys_by_source[entry.key.source]
        except KeyError as exc:
            raise AssetCompileError(
                "bootstrap sprite lookup lost active Python bank key") from exc
        flags = int(entry.key.flip_x) | (int(entry.key.flip_y) << 1)
        palette_offset = (
            SPRITE_NO_PALETTE
            if entry.palette_offset is None else entry.palette_offset)
        lookup_rows.append((
            bank_key, flags, entry.format_code, entry.key.code,
            entry.offset, palette_offset, entry.stride,
            entry.width, entry.height))
    lookup_rows.sort()
    if len(lookup_rows) != len(set((row[0], row[1], row[3])
                                   for row in lookup_rows)):
        raise AssetCompileError("bootstrap sprite lookup содержит повторный ключ")
    lookup = bytearray(struct.pack(
        "<4sBBHII", b"HQA3", 3, SPRITE_LOOKUP_RECORD.size,
        len(lookup_rows), len(pack.data), 0))
    for (bank_key, flags, format_code, code, offset, palette_offset,
         stride, width, height) in lookup_rows:
        lookup += SPRITE_LOOKUP_RECORD.pack(
            bank_key, flags, format_code, code, offset, palette_offset,
            stride, width, height)
    lookup_path = output_directory / "stage1_bootstrap_sprites.lookup"
    _atomic_bytes(lookup_path, bytes(lookup))

    packed_by_key = {
        (bank_key, flags, code): (
            offset, palette_offset, stride, format_code, width, height)
        for (bank_key, flags, format_code, code, offset, palette_offset,
             stride, width, height) in lookup_rows
    }
    template_sources = tuple(sorted(
        set(templates),
        key=lambda item: (item.bank_key, item.descriptor_address),
    ))
    if len(template_sources) != len({
            (item.bank_key, item.descriptor_address)
            for item in template_sources}):
        raise AssetCompileError("sprite template key is not unique")
    template_records = bytearray()
    template_cells = bytearray()
    bitmap_states: list[dict[str, int]] = []
    bitmap_state_index: dict[tuple[int, int], int] = {}
    template_report: list[dict[str, object]] = []
    used_keys: set[tuple[int, int, int]] = set()
    cell_first = 0
    for item in template_sources:
        resolved_key, _source, _path = _sprite_bank(
            root, 0, item.resource_type, typed_set)
        if resolved_key != item.bank_key:
            raise AssetCompileError(
                "sprite template bank key differs from active Python preload")
        flags = int(item.flip_x) | (int(item.flip_y) << 1)
        cells: list[dict[str, int]] = []
        for cell_x in range(item.width):
            for cell_y in range(item.height):
                source_x = item.width - 1 - cell_x if item.flip_x else cell_x
                source_y = item.height - 1 - cell_y if item.flip_y else cell_y
                code = (item.code + 8 * source_x + source_y) & 0x0FFF
                key = (item.bank_key, flags, code)
                try:
                    (offset, palette_offset, stride, format_code,
                     cell_width, cell_height) = packed_by_key[key]
                except KeyError as exc:
                    raise AssetCompileError(
                        "sprite template references a cell absent from HQA3: "
                        f"{key}"
                    ) from exc
                used_keys.add(key)
                local_x = round(cell_x * 16 * 5 / 3)
                local_y = cell_y * SPRITE_CELL[1]
                absolute = ram_g_base + offset
                cell_size = stride * cell_height
                if absolute + cell_size > ram_g_base + len(pack.data):
                    raise AssetCompileError("sprite template exceeds RAM_G cache")
                palette_absolute = (
                    SPRITE_NO_PALETTE if palette_offset == SPRITE_NO_PALETTE
                    else ram_g_base + palette_offset)
                if (palette_absolute != SPRITE_NO_PALETTE and
                        palette_absolute + 512 > ram_g_base + len(pack.data)):
                    raise AssetCompileError(
                        "sprite template palette exceeds RAM_G cache")
                layout = _bitmap_layout_word(
                    format_code, stride, cell_height)
                state_key = (layout, palette_absolute)
                state_index = bitmap_state_index.get(state_key)
                if state_index is None:
                    state_index = len(bitmap_states)
                    if state_index > 0xFF:
                        raise AssetCompileError(
                            "HQT3 bitmap state index exceeds uint8")
                    bitmap_state_index[state_key] = state_index
                    bitmap_states.append({
                        "layout": layout,
                        "palette_ram_g": palette_absolute,
                    })
                template_cells += SPRITE_TEMPLATE_CELL.pack(
                    absolute, local_x, local_y, state_index)
                cells.append({
                    "bank_key": item.bank_key,
                    "resource_type": item.resource_type,
                    "flags": flags,
                    "code": code,
                    "ram_g": absolute,
                    "palette_ram_g": palette_absolute,
                    "format": format_code,
                    "stride": stride,
                    "width": cell_width,
                    "height": cell_height,
                    "layout": layout,
                    "state_index": state_index,
                    "local_x": local_x,
                    "local_y": local_y,
                })
        cell_count = item.width * item.height
        template_records += SPRITE_TEMPLATE_RECORD.pack(
            item.bank_key,
            flags,
            item.resource_type,
            item.descriptor_address,
            item.dx,
            item.dy,
            item.code,
            item.width,
            item.height,
            cell_first,
            cell_count,
        )
        template_report.append({
            "bank_key": item.bank_key,
            "resource_type": item.resource_type,
            "flags": flags,
            "descriptor_address": item.descriptor_address,
            "dx": item.dx,
            "dy": item.dy,
            "code": item.code,
            "width": item.width,
            "height": item.height,
            "cell_first": cell_first,
            "cell_count": cell_count,
            "cells": cells,
        })
        cell_first += cell_count
    if used_keys != set(packed_by_key):
        missing = sorted(set(packed_by_key) - used_keys)
        raise AssetCompileError(
            f"HQA3 contains {len(missing)} cells not owned by a Python template"
        )
    template_states = b"".join(
        SPRITE_TEMPLATE_STATE.pack(
            int(state["layout"]), int(state["palette_ram_g"]))
        for state in bitmap_states)
    template_blob = bytearray(SPRITE_TEMPLATE_HEADER.pack(
        b"HQT3", 3, SPRITE_TEMPLATE_RECORD.size, len(template_sources),
        cell_first, SPRITE_TEMPLATE_CELL.size, len(bitmap_states)))
    template_blob += template_records
    template_blob += template_states
    template_blob += template_cells
    template_path = output_directory / "stage1_bootstrap_sprite_templates.bin"
    _atomic_bytes(template_path, bytes(template_blob))
    template_info: dict[str, object] = {
        "path": template_path.resolve().relative_to(root.resolve()).as_posix(),
        "format": (
            "HQT3 sorted <bank_key:u16,flags:u8,resource_hint:u8,"
            "descriptor:u16,dx:i16,dy:i16,code:u16,width:u8,height:u8,"
            "cell_first:u16,cell_count:u16>; "
            "states <BITMAP_LAYOUT:u32,palette_ram_g:u32>; "
            "cells <ram_g:u32,local_x:i16,local_y:i16,state_index:u8>"
        ),
        "size": len(template_blob),
        "sha256": hashlib.sha256(template_blob).hexdigest(),
        "record_count": len(template_sources),
        "record_size": SPRITE_TEMPLATE_RECORD.size,
        "cell_count": cell_first,
        "cell_record_size": SPRITE_TEMPLATE_CELL.size,
        "state_count": len(bitmap_states),
        "state_record_size": SPRITE_TEMPLATE_STATE.size,
        "states": bitmap_states,
        "records": template_report,
    }
    append_ram_g = (ram_g_base + len(pack.data) + 3) & ~3
    append_blob, append_mapping, append_blobs = _build_append_template_pack(
        template_report, append_ram_g)
    if append_ram_g + len(append_blob) > 0x100000:
        raise AssetCompileError("CMD_APPEND templates exceed FT812 RAM_G")
    append_path = output_directory / "stage1_bootstrap_sprite_dl_templates.bin"
    _atomic_bytes(append_path, append_blob)
    mapping_bytes = bytes(append_mapping)
    append_info: dict[str, object] = {
        "path": append_path.resolve().relative_to(root.resolve()).as_posix(),
        "format": (
            "deduplicated self-contained FT812 DL with minimal "
            "BITMAP_LAYOUT/PALETTE_SOURCE changes in source cell order, "
            "BITMAP_SOURCE+relative VERTEX2F; "
            "map[template][positive_x_mod5][positive_y_mod5]"
        ),
        "ram_g_base": append_ram_g,
        "alignment": 4,
        "size": len(append_blob),
        "sha256": hashlib.sha256(append_blob).hexdigest(),
        "phase_count": 5,
        "mapping_count": len(append_mapping),
        "mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
        "blob_count": len(append_blobs),
        "blobs": append_blobs,
    }
    template_info["append"] = append_info
    emitted_c = _emit_sprite_template_c(
        root, template_report, bitmap_states, append_mapping, append_blobs,
        typed_resource_types)
    template_info["resolver_hash"] = emitted_c.pop("resolver_hash")
    template_info["c_tables"] = emitted_c

    append_padding = append_ram_g - (ram_g_base + len(pack.data))
    inflate_payload = pack.data + bytes(append_padding) + append_blob
    zlib_stream = zlib.compress(inflate_payload, level=9)
    compressed = zlib_stream + bytes((-len(zlib_stream)) & 3)
    compressed_path = output_directory / "stage1_bootstrap_sprites.zlib"
    _atomic_bytes(compressed_path, compressed)

    record.update({
        "kind": "sprite-bootstrap-working-set",
        "stage": 1,
        "cache_policy": (
            "lossless hybrid section preload plus exact on-demand cells"),
        "ram_g_base": ram_g_base,
        "ram_g_limit": 0x100000,
        "compressed": {
            "path": compressed_path.resolve().relative_to(root.resolve()).as_posix(),
            "encoding": "zlib",
            "size": len(compressed),
            "zlib_size": len(zlib_stream),
            "sha256": hashlib.sha256(compressed).hexdigest(),
            "raw_size": len(inflate_payload),
            "pixel_raw_size": len(pack.data),
        },
        "lookup": {
            "path": lookup_path.resolve().relative_to(root.resolve()).as_posix(),
            "format": (
                "HQA3 sorted <bank_key:u16,flags:u8,format:u8,code:u16,"
                "source_offset:u32,palette_offset:u32,stride:u16,"
                "width:u8,height:u8>"),
            "record_size": SPRITE_LOOKUP_RECORD.size,
            "record_count": len(lookup_rows),
            "size": len(lookup),
            "sha256": hashlib.sha256(lookup).hexdigest(),
        },
        "bank_resolution": {
            "format": "active Python _asset: typed=(1,resource), fallback=(0,palette)",
            "typed_resource_types": list(typed_resource_types),
            "typed_resource_count": len(typed_resource_types),
            "typed_bitset_sha256": hashlib.sha256(bytes(
                sum(1 << bit for bit in range(8)
                    if byte * 8 + bit in typed_set)
                for byte in range(32))).hexdigest(),
        },
        "templates": template_info,
    })
    return record


def compile_rtype_hq_asset_plan(
        root: Path,
        sprite_bootstrap_requests: Iterable[
            tuple[int, int, int, bool, bool]],
        sprite_bootstrap_templates: Iterable[SpriteTemplateSource],
        typed_resource_types: Iterable[int],
        *,
        terrain_cell: tuple[int, int],
        sprite_cell: tuple[int, int],
        source_ast_sha256: str,
        ) -> dict[str, object]:
    """Собрать точные рабочие наборы, выбранные активным Python-runtime."""
    if terrain_cell != TERRAIN_CELL:
        raise AssetCompileError(
            f"Python terrain cell {terrain_cell}, ожидалось {TERRAIN_CELL}"
        )
    if sprite_cell != SPRITE_CELL:
        raise AssetCompileError(
            f"Python sprite cell {sprite_cell}, ожидалось {SPRITE_CELL}"
        )
    if len(source_ast_sha256) != 64:
        raise AssetCompileError("HQ asset AST fingerprint должен быть SHA-256")
    bootstrap_requests = tuple(sprite_bootstrap_requests)
    typed_source = tuple(int(item) for item in typed_resource_types)
    typed_resources = tuple(sorted(set(typed_source)))
    if (not all(0 <= item <= 0xFF for item in typed_resources) or
            len(typed_resources) != len(typed_source)):
        raise AssetCompileError(
            "active Python typed-resource availability is invalid")
    output_directory = root / "Build" / "PythonAssets"
    artifacts: list[dict[str, object]] = []
    for section in range(6):
        artifacts.append(_compile_terrain_set(
            root, output_directory, section, "base"))
    for section in (2, 3):
        artifacts.append(_compile_terrain_set(
            root, output_directory, section, "boss"))
        artifacts.append(_compile_terrain_set(
            root, output_directory, section, "flash"))
    artifacts.append(_compile_sprite_bootstrap(
        root, output_directory, bootstrap_requests,
        sprite_bootstrap_templates, typed_resources))

    report: dict[str, object] = {
        "format": ASSET_PLAN_FORMAT,
        "source": "active run_python.cmd import graph",
        "source_ast_sha256": source_ast_sha256,
        "sprite_bootstrap_requests": len(set(bootstrap_requests)),
        "pixel_format": ARGB4444_LE,
        "offline_scale": "xBRZ 1.9 x6 then Pillow Lanczos",
        "runtime_scale": "FT812 NEAREST 640x480 to 1024x768",
        "terrain_cell": list(terrain_cell),
        "sprite_cell": list(sprite_cell),
        "artifacts": artifacts,
        "totals": {
            "bytes": sum(int(artifact["size"]) for artifact in artifacts),
            "logical_entries": sum(
                int(artifact["logical_entries"]) for artifact in artifacts),
            "unique_cells": sum(
                int(artifact["unique_cells"]) for artifact in artifacts),
        },
        "target_policy": {
            "resident": "only current section and active sprite cache",
            "level_loading": "remaining artifacts stay outside resident 4 MiB",
            "pixel_mutation": False,
        },
    }
    manifest = root / "Build" / "rtype_python_assets.json"
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8")
    _atomic_bytes(manifest, encoded)
    return report
