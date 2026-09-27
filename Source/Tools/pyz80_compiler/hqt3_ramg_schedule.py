"""Physical per-scope HQT3/RAM_G sizing and source-derived load obligations.

This pass consumes the complete active-Python HQT3 inventory.  It does not
invent one all-resident sprite atlas.  Every catalogue scope is compiled as
an independent, relocatable, lossless FT812 cell pack and an exact HQT3 table.
The result proves isolated byte requirements and capacity classification only.

Event rows are then converted into upload-before-dispatch obligations.  A
candidate scope which disappears from the following event is deliberately not
declared evictable: active Python keeps objects across later ROM events, and
the inventory does not yet contain last-draw intervals.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import multiprocessing
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .assets import (
    AssetCompileError,
    CellBankSpec,
    CellKey,
    CellSourceKey,
)
from .ft812_assets import (
    FT812_ARGB4,
    FT812_PALETTED4444,
    FT812AssetPackBudget,
    FT812CellAssetPack,
    compile_ft812_cell_assets,
)
from .full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
    HQT3_MAX_CELLS,
    HQT3_MAX_RECORDS,
    HQT3_MAX_STATES,
)


HQT3_RAMG_SCHEDULE_FORMAT = "pyz80-hqt3-ramg-schedule-v1"
HQT3_RAMG_SCHEDULE_STATUS = (
    "EXACT_SCOPE_PACKS_TRANSITIONS_AND_LIFETIMES_BLOCKED")

FT812_RAM_G_BYTES = 0x100000
TSCONF_RAM_BYTES = 4 * 1024 * 1024
PACK_ALIGNMENT = 4
SPRITE_CELL_COUNT = 4096
NO_PALETTE = 0xFFFFFFFF
DL_BITMAP_LAYOUT = 0x07000000

_HQT3_HEADER = struct.Struct("<4sBBHIII")
_HQT3_RECORD = struct.Struct("<HBBHhhHBBHH")
_HQT3_STATE = struct.Struct("<II")
_HQT3_CELL = struct.Struct("<IhhB")

# Do not copy the catalogue's nominal constants here.  This physical pass is
# deliberately bound to the byte structs used by the real generator/checker.
HQT3_HEADER_BYTES = _HQT3_HEADER.size
HQT3_RECORD_BYTES = _HQT3_RECORD.size
HQT3_STATE_BYTES = _HQT3_STATE.size
HQT3_CELL_BYTES = _HQT3_CELL.size


class HQT3RAMGScheduleError(ValueError):
    """The physical scope pack cannot be proved without changing semantics."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise HQT3RAMGScheduleError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _inventory_semantic_sha256(inventory: Mapping[str, object]) -> str:
    semantic = dict(inventory)
    semantic.pop("status", None)
    semantic.pop("analysis_sha256", None)
    return _sha256_value(semantic)


def _source_key(bank: Mapping[str, object]) -> CellSourceKey:
    kind = bank.get("kind")
    value = bank.get("value")
    if not isinstance(value, int):
        raise HQT3RAMGScheduleError("template bank value is not an integer")
    if kind == "typed-resource" and 0 <= value <= 0xFF:
        return CellSourceKey("sprite", f"type{value:02X}")
    if kind == "palette-fallback" and 0 <= value <= 0x0F:
        return CellSourceKey("sprite", "palette-fallback", value)
    raise HQT3RAMGScheduleError(f"invalid template bank {bank!r}")


def _bank_path(root: Path, bank: Mapping[str, object]) -> Path:
    kind = bank.get("kind")
    value = bank.get("value")
    if not isinstance(value, int):
        raise HQT3RAMGScheduleError("template bank value is not an integer")
    arcade = root / "Assets" / "Converted" / "Arcade"
    if kind == "typed-resource" and 0 <= value <= 0xFF:
        return arcade / "ResourceHQ" / (
            f"RTYPE_SPRITES_TYPE{value:02X}_HQ_ARGB4444.bin")
    if kind == "palette-fallback" and 0 <= value <= 0x0F:
        return arcade / "FullHQ" / (
            f"RTYPE_SPRITES_PAL{value:02X}_HQ_ARGB4444.bin")
    raise HQT3RAMGScheduleError(f"invalid template bank {bank!r}")


def _encoded_bank(bank: Mapping[str, object]) -> int:
    encoded = bank.get("encoded_hqt3_key")
    if not isinstance(encoded, int) or not 0 <= encoded <= 0x1FF:
        raise HQT3RAMGScheduleError("encoded HQT3 bank key is invalid")
    kind = bank.get("kind")
    value = bank.get("value")
    expected = (
        0x100 | int(value) if kind == "typed-resource" else int(value)
        if kind == "palette-fallback" else -1)
    if encoded != expected:
        raise HQT3RAMGScheduleError("encoded HQT3 bank key is stale")
    return encoded


@dataclass(frozen=True)
class TemplateCell:
    key: CellKey
    cell_x: int
    cell_y: int


def _template_cells(template: Mapping[str, object]) -> tuple[TemplateCell, ...]:
    bank = template.get("bank")
    descriptor = template.get("descriptor")
    if not isinstance(bank, dict) or not isinstance(descriptor, dict):
        raise HQT3RAMGScheduleError("template bank/descriptor is missing")
    width = descriptor.get("width")
    height = descriptor.get("height")
    code = descriptor.get("code")
    flip_x = descriptor.get("flip_x")
    flip_y = descriptor.get("flip_y")
    if (width not in (1, 2, 4, 8) or height not in (1, 2, 4, 8) or
            not isinstance(code, int) or not isinstance(flip_x, bool) or
            not isinstance(flip_y, bool)):
        raise HQT3RAMGScheduleError("template descriptor geometry is invalid")
    source = _source_key(bank)
    cells: list[TemplateCell] = []
    for cell_x in range(width):
        for cell_y in range(height):
            source_x = width - 1 - cell_x if flip_x else cell_x
            source_y = height - 1 - cell_y if flip_y else cell_y
            cells.append(TemplateCell(
                CellKey(
                    source,
                    (code + 8 * source_x + source_y) & 0x0FFF,
                    flip_x,
                    flip_y,
                ),
                cell_x,
                cell_y,
            ))
    if template.get("cell_count") != len(cells):
        raise HQT3RAMGScheduleError("template cell count is stale")
    return tuple(cells)


def _cell_inventory_name(cell: CellKey) -> str:
    source = cell.source
    if source.resource.startswith("type") and source.palette == -1:
        kind = "typed-resource"
        value = int(source.resource[4:], 16)
    elif source.resource == "palette-fallback" and source.palette >= 0:
        kind = "palette-fallback"
        value = source.palette
    else:
        raise HQT3RAMGScheduleError(
            f"cannot map cell source {source.stable_name} to inventory")
    return (
        f"{kind}:{value:02X}:{cell.code:03X}:"
        f"fx{int(cell.flip_x)}:fy{int(cell.flip_y)}")


def _pixel_pack_id(cells: Iterable[CellKey]) -> str:
    names = "\n".join(sorted({_cell_inventory_name(cell) for cell in cells}))
    return "sprite-" + hashlib.sha256(names.encode("utf-8")).hexdigest()[:24]


def _layout_word(format_code: int, stride: int, height: int) -> int:
    if format_code not in (FT812_ARGB4, FT812_PALETTED4444):
        raise HQT3RAMGScheduleError(
            f"unsupported physical FT812 format {format_code}")
    if not 0 <= stride <= 0x3FF or not 0 <= height <= 0x1FF:
        raise HQT3RAMGScheduleError("physical BITMAP_LAYOUT field overflow")
    return DL_BITMAP_LAYOUT | (format_code << 19) | (stride << 9) | height


def _scope_cells(
        scope: Mapping[str, object],
        templates: Sequence[Mapping[str, object]],
        ) -> tuple[CellKey, ...]:
    indices = scope.get("template_indices")
    if not isinstance(indices, list) or any(
            not isinstance(item, int) for item in indices):
        raise HQT3RAMGScheduleError("scope template index list is malformed")
    if indices != sorted(set(indices)):
        raise HQT3RAMGScheduleError("scope template indices are not canonical")
    try:
        selected = tuple(templates[index] for index in indices)
    except IndexError as exc:
        raise HQT3RAMGScheduleError(
            "scope template index is outside the global catalogue") from exc
    cells = tuple(sorted({
        item.key for template in selected for item in _template_cells(template)
    }))
    if scope.get("template_count") != len(selected):
        raise HQT3RAMGScheduleError("scope template count is inconsistent")
    reference_count = sum(len(_template_cells(item)) for item in selected)
    if scope.get("template_cell_reference_count") != reference_count:
        raise HQT3RAMGScheduleError("scope HQT3 cell count is inconsistent")
    if scope.get("unique_logical_cell_count") != len(cells):
        raise HQT3RAMGScheduleError("scope logical cell count is inconsistent")
    if scope.get("pixel_pack_id") != _pixel_pack_id(cells):
        raise HQT3RAMGScheduleError("scope pixel pack identity is inconsistent")
    return cells


def _compile_pixel_pack(
        root: Path,
        cells: Sequence[CellKey],
        width: int,
        height: int,
        ) -> FT812CellAssetPack | None:
    if not cells:
        return None
    cell_bytes = width * height * 2
    sources = sorted({cell.source for cell in cells})
    banks: list[CellBankSpec] = []
    for source in sources:
        if source.resource.startswith("type") and source.palette == -1:
            bank = {
                "kind": "typed-resource",
                "value": int(source.resource[4:], 16),
            }
        elif source.resource == "palette-fallback" and source.palette >= 0:
            bank = {
                "kind": "palette-fallback",
                "value": source.palette,
            }
        else:
            raise HQT3RAMGScheduleError(
                f"unknown sprite source {source.stable_name}")
        path = _bank_path(root, bank)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise HQT3RAMGScheduleError(
                f"sprite bank is unavailable: {path}: {exc}") from exc
        expected = SPRITE_CELL_COUNT * cell_bytes
        if size != expected:
            raise HQT3RAMGScheduleError(
                f"sprite bank {path} has {size} bytes, expected {expected}")
        banks.append(CellBankSpec(
            source, path, width, height, SPRITE_CELL_COUNT))
    raw_ceiling = len(cells) * cell_bytes
    try:
        return compile_ft812_cell_assets(
            cells,
            banks,
            FT812AssetPackBudget(
                max_logical_entries=len(cells),
                max_unique_cells=len(cells),
                max_palettes=len(cells),
                # Measurement ceiling only.  The resulting size is compared
                # with RAM_G after compilation, never accepted by this value.
                max_bytes=raw_ceiling + len(cells) * 516,
                alignment=PACK_ALIGNMENT,
            ),
            project_root=root,
        )
    except AssetCompileError as exc:
        raise HQT3RAMGScheduleError(
            f"lossless FT812 scope pack failed: {exc}") from exc


def _compile_pixel_pack_task(
        task: tuple[str, str, tuple[CellKey, ...], int, int],
        ) -> tuple[str, FT812CellAssetPack | None]:
    """Spawn-safe worker for one immutable exact pixel-key pack."""
    root_value, pack_id, cells, width, height = task
    return pack_id, _compile_pixel_pack(
        Path(root_value), cells, width, height)


def compile_pixel_packs(
        root: Path,
        cells_by_pack: Mapping[str, tuple[CellKey, ...]],
        width: int,
        height: int,
        *,
        max_workers: int = 1,
        ) -> dict[str, FT812CellAssetPack | None]:
    """Compile independent packs on processes and collect in key order.

    Only immutable inputs/results cross the process boundary.  ``map`` keeps
    the sorted task order, so a different worker completion order cannot alter
    the generated report or any of its hashes.
    """
    if isinstance(max_workers, bool) or max_workers < 1:
        raise HQT3RAMGScheduleError("max_workers must be >= 1")
    tasks = [
        (str(root), pack_id, tuple(cells_by_pack[pack_id]), width, height)
        for pack_id in sorted(cells_by_pack)
    ]
    if max_workers == 1 or len(tasks) <= 1:
        results = [_compile_pixel_pack_task(task) for task in tasks]
    else:
        context = multiprocessing.get_context("spawn")
        try:
            with concurrent.futures.ProcessPoolExecutor(
                    max_workers=min(max_workers, len(tasks)),
                    mp_context=context) as pool:
                results = list(pool.map(
                    _compile_pixel_pack_task, tasks, chunksize=1))
        except Exception as exc:
            raise HQT3RAMGScheduleError(
                f"parallel FT812 pixel-pack compilation failed: {exc}"
            ) from exc
    if [pack_id for pack_id, _pack in results] != [
            task[1] for task in tasks]:
        raise HQT3RAMGScheduleError(
            "parallel FT812 pixel-pack result order changed")
    return dict(results)


def _pack_measurement(
        pack_id: str,
        cells: Sequence[CellKey],
        pack: FT812CellAssetPack | None,
        cell_bytes: int,
        ) -> dict[str, object]:
    logical_count = len(cells)
    if pack is None:
        if cells:
            raise HQT3RAMGScheduleError("non-empty scope has no pixel pack")
        return {
            "pack_id": pack_id,
            "logical_cell_count": 0,
            "selected_logical_argb4444_bytes": 0,
            "content_unique_cell_count": 0,
            "content_unique_argb4444_bytes": 0,
            "ft812_payload_bytes": 0,
            "lossless_saved_vs_selected_bytes": 0,
            "palette_count": 0,
            "format_counts": {"ARGB4": 0, "PALETTED4444": 0},
            "relocatable_payload_sha256": hashlib.sha256(b"").hexdigest(),
            "entry_binding_sha256": _sha256_value([]),
            "palette_binding_sha256": _sha256_value([]),
            "pixel_roundtrip_complete": True,
        }
    if len(pack.entries) != logical_count:
        raise HQT3RAMGScheduleError("FT812 pack lost logical cell keys")
    if {entry.key for entry in pack.entries} != set(cells):
        raise HQT3RAMGScheduleError("FT812 pack key set differs from scope")
    entry_rows = [{
        "key": _cell_inventory_name(entry.key),
        "offset": entry.offset,
        "size": entry.size,
        "width": entry.width,
        "height": entry.height,
        "format_code": entry.format_code,
        "stride": entry.stride,
        "palette_offset": entry.palette_offset,
        "decoded_sha256": entry.decoded_sha256,
        "payload_sha256": entry.payload_sha256,
        "source_path": entry.source_path,
        "source_sha256": entry.source_sha256,
        "source_offset": entry.source_offset,
    } for entry in pack.entries]
    palette_rows = [palette.as_dict() for palette in pack.palettes]
    format_counts = {"ARGB4": 0, "PALETTED4444": 0}
    for entry in pack.entries:
        format_counts[entry.pixel_format] += 1
        # ``compile_ft812_cell_assets`` already performs this proof, but the
        # digest is re-read here so a future backend cannot skip it silently.
        if hashlib.sha256(pack.decode(entry)).hexdigest() != entry.decoded_sha256:
            raise HQT3RAMGScheduleError("FT812 pixel round-trip changed a cell")
    selected = logical_count * cell_bytes
    if pack.raw_argb4444_bytes != pack.unique_cells * cell_bytes:
        raise HQT3RAMGScheduleError(
            "content-unique ARGB4444 byte count is inconsistent")
    return {
        "pack_id": pack_id,
        "logical_cell_count": logical_count,
        "selected_logical_argb4444_bytes": selected,
        "content_unique_cell_count": pack.unique_cells,
        "content_unique_argb4444_bytes": pack.raw_argb4444_bytes,
        "ft812_payload_bytes": len(pack.data),
        "lossless_saved_vs_selected_bytes": selected - len(pack.data),
        "palette_count": len(pack.palettes),
        "format_counts": format_counts,
        "relocatable_payload_sha256": pack.sha256,
        "entry_binding_sha256": _sha256_value(entry_rows),
        "palette_binding_sha256": _sha256_value(palette_rows),
        "pixel_roundtrip_complete": True,
    }


def _hqt3_for_scope(
        scope: Mapping[str, object],
        templates: Sequence[Mapping[str, object]],
        pack: FT812CellAssetPack | None,
        ) -> dict[str, object]:
    indices = scope["template_indices"]
    assert isinstance(indices, list)
    selected = tuple(templates[int(index)] for index in indices)
    entries = {} if pack is None else {entry.key: entry for entry in pack.entries}
    records = bytearray()
    cells = bytearray()
    record_rows: list[dict[str, object]] = []
    cell_rows: list[dict[str, object]] = []
    states: list[tuple[int, int]] = []
    state_index: dict[tuple[int, int], int] = {}
    cell_first = 0
    for template in selected:
        bank = template.get("bank")
        descriptor = template.get("descriptor")
        if not isinstance(bank, dict) or not isinstance(descriptor, dict):
            raise HQT3RAMGScheduleError("scope template is malformed")
        template_cells = _template_cells(template)
        flags = int(bool(descriptor["flip_x"])) | (
            int(bool(descriptor["flip_y"])) << 1)
        resource_hint = template.get("resource_hint")
        if not isinstance(resource_hint, int) or not 0 <= resource_hint <= 0xFF:
            raise HQT3RAMGScheduleError("template resource hint is invalid")
        record_values = (
            _encoded_bank(bank), flags, resource_hint,
            int(descriptor["address"]), int(descriptor["dx"]),
            int(descriptor["dy"]), int(descriptor["code"]),
            int(descriptor["width"]), int(descriptor["height"]),
            cell_first, len(template_cells),
        )
        try:
            records.extend(_HQT3_RECORD.pack(*record_values))
        except struct.error as exc:
            raise HQT3RAMGScheduleError(
                "scope HQT3 record field overflow") from exc
        record_rows.append({
            "template_index": template["template_index"],
            "values": list(record_values),
        })
        for item in template_cells:
            try:
                entry = entries[item.key]
            except KeyError as exc:
                raise HQT3RAMGScheduleError(
                    "scope HQT3 cell is absent from its pixel pack") from exc
            palette = (
                NO_PALETTE if entry.palette_offset is None
                else entry.palette_offset)
            state = (_layout_word(
                entry.format_code, entry.stride, entry.height), palette)
            index = state_index.get(state)
            if index is None:
                index = len(states)
                state_index[state] = index
                states.append(state)
            # Same nearest-rational placement as the active generator.
            local_x = round(item.cell_x * 16 * 5 / 3)
            local_y = item.cell_y * entry.height
            cell_values = (entry.offset, local_x, local_y, index)
            cell_rows.append({
                "key": _cell_inventory_name(item.key),
                "values": list(cell_values),
            })
            if index < HQT3_MAX_STATES:
                cells.extend(_HQT3_CELL.pack(*cell_values))
            cell_first += 1

    record_count = len(selected)
    cell_count = len(cell_rows)
    state_count = len(states)
    state_bytes = b"".join(_HQT3_STATE.pack(*state) for state in states)
    encodable = (
        record_count <= HQT3_MAX_RECORDS and
        cell_count <= HQT3_MAX_CELLS and
        state_count <= HQT3_MAX_STATES)
    total_bytes = (
        HQT3_HEADER_BYTES + record_count * HQT3_RECORD_BYTES +
        state_count * HQT3_STATE_BYTES + cell_count * HQT3_CELL_BYTES)
    expected_fixed = scope.get("hqt3_fixed_layout")
    if not isinstance(expected_fixed, dict):
        raise HQT3RAMGScheduleError("scope fixed HQT3 layout is missing")
    upstream_layout_matches_physical = (
        expected_fixed.get("header_bytes") != HQT3_HEADER_BYTES or
        expected_fixed.get("record_count") != record_count or
        expected_fixed.get("record_bytes") != record_count * HQT3_RECORD_BYTES or
        expected_fixed.get("cell_count") != cell_count or
        expected_fixed.get("cell_bytes") != cell_count * HQT3_CELL_BYTES or
        expected_fixed.get("state_record_bytes") != HQT3_STATE_BYTES or
        expected_fixed.get("fixed_bytes_excluding_state_table") !=
        HQT3_HEADER_BYTES + record_count * HQT3_RECORD_BYTES +
        cell_count * HQT3_CELL_BYTES
    ) is False
    if not upstream_layout_matches_physical:
        raise HQT3RAMGScheduleError(
            f"scope {scope.get('scope_id')} inventory HQT3 layout does not "
            "match the real generator structs")

    relocatable_sha: str | None = None
    if encodable:
        header = _HQT3_HEADER.pack(
            b"HQT3", 3, HQT3_RECORD_BYTES, record_count,
            cell_count, HQT3_CELL_BYTES, state_count)
        blob = header + records + state_bytes + cells
        if len(blob) != total_bytes:
            raise HQT3RAMGScheduleError(
                f"scope {scope.get('scope_id')} HQT3 binary size is "
                f"{len(blob)}, expected {total_bytes}; records={len(records)}, "
                f"states={len(state_bytes)}, cells={len(cells)}")
        relocatable_sha = hashlib.sha256(blob).hexdigest()
    return {
        "record_count": record_count,
        "record_bytes": record_count * HQT3_RECORD_BYTES,
        "cell_reference_count": cell_count,
        "cell_bytes": cell_count * HQT3_CELL_BYTES,
        "state_count": state_count,
        "state_bytes": state_count * HQT3_STATE_BYTES,
        "header_bytes": HQT3_HEADER_BYTES,
        "total_bytes": total_bytes,
        "uint16_record_cell_and_uint8_state_indices_fit": encodable,
        "relocation_base": 0,
        "relocation_semantics": (
            "add chosen aligned RAM_G base to cell source and non-FFFFFFFF "
            "palette offsets; HQT3 itself remains TS/CPU metadata"),
        "relocatable_hqt3_sha256": relocatable_sha,
        "record_binding_sha256": _sha256_value(record_rows),
        "cell_binding_sha256": _sha256_value(cell_rows),
        "relative_state_rows_sha256": _sha256_value([
            {"layout": layout, "palette_offset": palette}
            for layout, palette in states
        ]),
        "physical_struct_sizes": {
            "header": HQT3_HEADER_BYTES,
            "record": HQT3_RECORD_BYTES,
            "state": HQT3_STATE_BYTES,
            "cell": HQT3_CELL_BYTES,
        },
    }


def _scope_capacity(
        pixel: Mapping[str, object],
        hqt3: Mapping[str, object],
        ) -> dict[str, object]:
    payload = int(pixel["ft812_payload_bytes"])
    selected = int(pixel["selected_logical_argb4444_bytes"])
    metadata = int(hqt3["total_bytes"])
    target_bundle = payload + metadata
    source_bundle = selected + metadata
    return {
        "ft812_ram_g_capacity_bytes": FT812_RAM_G_BYTES,
        "ram_g_payload_bytes": payload,
        "ram_g_isolated_headroom_bytes": FT812_RAM_G_BYTES - payload,
        "ram_g_isolated_fit": payload <= FT812_RAM_G_BYTES,
        "ram_g_gameplay_profile_fit_proved": False,
        "tsconf_ram_capacity_bytes": TSCONF_RAM_BYTES,
        "ts_staging_compiled_payload_plus_hqt3_bytes": target_bundle,
        "ts_staging_compiled_isolated_headroom_bytes": (
            TSCONF_RAM_BYTES - target_bundle),
        "ts_staging_compiled_isolated_fit": target_bundle <= TSCONF_RAM_BYTES,
        "ts_staging_raw_argb4444_plus_hqt3_bytes": source_bundle,
        "ts_staging_raw_argb4444_isolated_fit": source_bundle <= TSCONF_RAM_BYTES,
        "ts_whole_machine_allocation_fit_proved": False,
        "hqt3_storage_domain": "TS/CPU metadata, not FT812 RAM_G",
        "classification_is_isolated_scope_only": True,
    }


def derive_event_transition_obligations(
        events: Sequence[Mapping[str, object]],
        scope_rows: Mapping[str, Mapping[str, object]],
        ambient_scope_ids: Sequence[str],
        common_scope_ids: Sequence[str],
        force_epoch_scope_ids: Sequence[str],
        ) -> dict[str, object]:
    """Convert exact inventory order into conservative load obligations."""
    by_stage: dict[int, list[Mapping[str, object]]] = {
        stage: [] for stage in range(1, 9)}
    for event in events:
        stage = event.get("stage")
        if not isinstance(stage, int) or stage not in by_stage:
            raise HQT3RAMGScheduleError("event stage is outside 1..8")
        by_stage[stage].append(event)
    ambient_by_stage: dict[int, list[str]] = {stage: [] for stage in by_stage}
    for scope_id in ambient_scope_ids:
        scope = scope_rows.get(scope_id)
        if scope is None:
            raise HQT3RAMGScheduleError(
                f"ambient scope {scope_id!r} is absent")
        stage = scope.get("stage")
        if not isinstance(stage, int) or stage not in ambient_by_stage:
            raise HQT3RAMGScheduleError("ambient scope stage is invalid")
        ambient_by_stage[stage].append(scope_id)

    obligations: list[dict[str, object]] = []
    stage_rows: list[dict[str, object]] = []
    ambiguous = 0
    event_pack_ids: set[str] = set()
    unmatched_event_pack_ids: set[str] = set()
    unmatched_event_count = 0
    scope_pack_owners: dict[str, list[str]] = {}
    for scope_id, scope in scope_rows.items():
        pack_id = scope.get("pixel_pack_id")
        if isinstance(pack_id, str):
            scope_pack_owners.setdefault(pack_id, []).append(scope_id)
    for stage in range(1, 9):
        ordered = by_stage[stage]
        addresses = [event.get("address") for event in ordered]
        if (any(not isinstance(address, int) for address in addresses) or
                addresses != sorted(addresses) or
                len(addresses) != len(set(addresses))):
            raise HQT3RAMGScheduleError(
                f"stage {stage} event addresses are not strict source order")
        previous_ids: tuple[str, ...] = ()
        previous_event: str | None = None
        for ordinal, event in enumerate(ordered):
            event_id = event.get("event_id")
            ids = event.get("class_scope_ids")
            exact = event.get("correlation_exact")
            event_pack_id = event.get("pack_id")
            pair_sha256 = event.get("pair_sha256")
            ambiguous_classes = event.get("ambiguous_classes")
            if (not isinstance(event_id, str) or not isinstance(ids, list) or
                    any(not isinstance(item, str) for item in ids) or
                    ids != sorted(set(ids)) or not isinstance(exact, bool)):
                raise HQT3RAMGScheduleError("event relation row is malformed")
            if (not isinstance(event_pack_id, str) or
                    not isinstance(pair_sha256, str) or
                    len(pair_sha256) != 64 or
                    not isinstance(ambiguous_classes, list) or
                    any(not isinstance(item, str) for item in ambiguous_classes)):
                raise HQT3RAMGScheduleError(
                    "event pack/relation binding is malformed")
            for scope_id in ids:
                scope = scope_rows.get(scope_id)
                if scope is None or scope.get("stage") != stage:
                    raise HQT3RAMGScheduleError(
                        f"event {event_id} references a foreign scope")
            current_ids = tuple(ids)
            previous_set = set(previous_ids)
            current_set = set(current_ids)
            candidate_new = sorted(current_set - previous_set)
            candidate_carry = sorted(current_set & previous_set)
            candidate_disappeared = sorted(previous_set - current_set)
            isolated_fits = [
                bool(scope_rows[scope_id]["capacity"]["ram_g_isolated_fit"])
                for scope_id in current_ids
            ]
            pack_owners = sorted(scope_pack_owners.get(event_pack_id, ()))
            event_pack_ids.add(event_pack_id)
            if not pack_owners:
                unmatched_event_count += 1
                unmatched_event_pack_ids.add(event_pack_id)
            obligations.append({
                "transition_id": f"stage:{stage}:before-event:{ordinal:03d}",
                "stage": stage,
                "ordinal": ordinal,
                "from_event_id": previous_event,
                "to_event_id": event_id,
                "to_event_address": event["address"],
                "to_event_correlation_exact": exact,
                "to_event_pair_sha256": pair_sha256,
                "to_event_pixel_pack_id": event_pack_id,
                "to_event_ambiguous_classes": list(ambiguous_classes),
                "event_pixel_pack_matches_independent_scope": bool(pack_owners),
                "matching_independent_scope_ids": pack_owners,
                "required_before_dispatch_scope_ids": list(current_ids),
                "required_scope_semantics": (
                    "exact" if exact else
                    "conservative candidate union; per-event selector ambiguous"),
                "candidate_new_scope_ids": candidate_new,
                "candidate_carry_scope_ids": candidate_carry,
                "candidate_disappeared_scope_ids": candidate_disappeared,
                "disappeared_scope_eviction_permitted": False,
                "all_required_scopes_individually_fit_ram_g": all(isolated_fits),
                "required_scope_union_residency_proved": False,
                "upload_before_first_draw_required": bool(current_ids),
                "same_frame_dispatch_upload_order_proved": False,
                "transition_byte_cost": None,
            })
            ambiguous += int(not exact)
            previous_ids = current_ids
            previous_event = event_id
        stage_rows.append({
            "stage": stage,
            "event_count": len(ordered),
            "first_event_id": (
                None if not ordered else ordered[0]["event_id"]),
            "last_event_id": (
                None if not ordered else ordered[-1]["event_id"]),
            "ambient_scope_ids": sorted(ambient_by_stage[stage]),
            "ambient_upload_before_first_possible_spawn_required": True,
            "ambient_residency_combination_proved": False,
            "stage_exit_eviction_permitted": False,
        })
    return {
        "source_order": "inventory stage/event address order",
        "event_obligation_count": len(obligations),
        "event_correlation_exact_count": len(obligations) - ambiguous,
        "event_correlation_ambiguous_count": ambiguous,
        "unique_event_pixel_pack_count": len(event_pack_ids),
        "event_count_without_independent_scope_pack": unmatched_event_count,
        "unique_event_pixel_packs_without_independent_scope": sorted(
            unmatched_event_pack_ids),
        "obligations": obligations,
        "stages": stage_rows,
        "common_scope_ids": sorted(common_scope_ids),
        "common_combination_residency_proved": False,
        "force_epoch_scope_ids": sorted(force_epoch_scope_ids),
        "force_epoch_at_most_one_live": True,
        "force_epoch_switch_upload_before_first_draw_required": True,
        "force_epoch_switch_timeline_proved": False,
        "event_scope_eviction_never_inferred_from_next_event": True,
    }


def _validate_active_bindings(root: Path, inventory: Mapping[str, object]) -> None:
    source = inventory.get("source_binding")
    if not isinstance(source, dict):
        raise HQT3RAMGScheduleError("inventory source binding is missing")
    hashes = source.get("coverage_source_hashes")
    if not isinstance(hashes, dict):
        raise HQT3RAMGScheduleError("inventory source hashes are missing")
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise HQT3RAMGScheduleError("inventory source hash row is malformed")
        if name == "run_python.cmd":
            path = root / name
        elif name.startswith("rtype_port."):
            path = root / "Source" / "Python" / Path(
                *name.split(".")).with_suffix(".py")
        else:
            raise HQT3RAMGScheduleError(
                f"inventory source path is outside active Python: {name}")
        if _sha256_file(path) != expected:
            raise HQT3RAMGScheduleError(f"inventory is stale for {name}")
    rom_path = source.get("rom_path")
    rom_sha = source.get("rom_sha256")
    if not isinstance(rom_path, str) or not isinstance(rom_sha, str):
        raise HQT3RAMGScheduleError("inventory ROM binding is malformed")
    if _sha256_file(root / Path(rom_path)) != rom_sha:
        raise HQT3RAMGScheduleError("inventory is stale for active World ROM")
    asset_witnesses = inventory.get("asset_resolution_witnesses")
    if not isinstance(asset_witnesses, dict):
        raise HQT3RAMGScheduleError("inventory asset witnesses are missing")
    files = asset_witnesses.get("used_bank_files")
    if not isinstance(files, list) or not files:
        raise HQT3RAMGScheduleError("inventory has no active sprite banks")
    for value in files:
        if not isinstance(value, dict):
            raise HQT3RAMGScheduleError("inventory sprite bank row is malformed")
        relative = value.get("path")
        size = value.get("size")
        expected = value.get("sha256")
        if (not isinstance(relative, str) or not isinstance(size, int) or
                not isinstance(expected, str)):
            raise HQT3RAMGScheduleError(
                "inventory sprite bank binding is malformed")
        path = root / Path(relative)
        try:
            actual_size = path.stat().st_size
        except OSError as exc:
            raise HQT3RAMGScheduleError(
                f"inventory sprite bank is unavailable: {path}: {exc}") from exc
        if actual_size != size or _sha256_file(path) != expected:
            raise HQT3RAMGScheduleError(
                f"inventory is stale for active sprite bank {relative}")


def analyze_hqt3_ramg_schedule(
        project_root: Path,
        *,
        inventory_path: Path | None = None,
        max_workers: int = 1,
        ) -> dict[str, object]:
    """Measure all catalogue scopes and derive fail-closed load obligations."""
    root = Path(project_root).resolve()
    path = (
        root / "Build" / "rtype_python_full_hqt3_inventory_status.json"
        if inventory_path is None else Path(inventory_path).resolve())
    try:
        raw = path.read_bytes()
        inventory = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HQT3RAMGScheduleError(
            f"cannot read full HQT3 inventory {path}: {exc}") from exc
    if not isinstance(inventory, dict):
        raise HQT3RAMGScheduleError("full HQT3 inventory is not an object")
    if (inventory.get("format") != FULL_HQT3_INVENTORY_FORMAT or
            inventory.get("status") != FULL_HQT3_INVENTORY_STATUS or
            inventory.get("inventory_complete") is not True or
            inventory.get("live") is not False):
        raise HQT3RAMGScheduleError("full HQT3 inventory identity changed")
    stored_analysis = inventory.get("analysis_sha256")
    if (not isinstance(stored_analysis, str) or
            _inventory_semantic_sha256(inventory) != stored_analysis):
        raise HQT3RAMGScheduleError("full HQT3 inventory semantic hash differs")
    _validate_active_bindings(root, inventory)

    catalog = inventory.get("global_catalog")
    load_plan = inventory.get("load_plan")
    source = inventory.get("source_binding")
    if not isinstance(catalog, dict) or not isinstance(load_plan, dict) or not isinstance(source, dict):
        raise HQT3RAMGScheduleError("inventory catalogue/load plan is missing")
    templates_value = catalog.get("templates")
    scopes_value = load_plan.get("scopes")
    events_value = load_plan.get("events")
    if (not isinstance(templates_value, list) or
            not isinstance(scopes_value, list) or
            not isinstance(events_value, list)):
        raise HQT3RAMGScheduleError("inventory template/scope/event rows missing")
    templates: tuple[Mapping[str, object], ...] = tuple(
        item for item in templates_value if isinstance(item, dict))
    scopes: tuple[Mapping[str, object], ...] = tuple(
        item for item in scopes_value if isinstance(item, dict))
    events: tuple[Mapping[str, object], ...] = tuple(
        item for item in events_value if isinstance(item, dict))
    if (len(templates) != len(templates_value) or
            len(scopes) != len(scopes_value) or
            len(events) != len(events_value)):
        raise HQT3RAMGScheduleError("inventory contains non-object rows")
    if [item.get("template_index") for item in templates] != list(range(len(templates))):
        raise HQT3RAMGScheduleError("global template indices are not dense")
    width = source.get("sprite_cell_width")
    height = source.get("sprite_cell_height")
    cell_bytes = source.get("sprite_cell_argb4444_bytes")
    if (not isinstance(width, int) or not isinstance(height, int) or
            width <= 0 or height <= 0 or cell_bytes != width * height * 2):
        raise HQT3RAMGScheduleError("active sprite cell geometry is invalid")

    cells_by_pack: dict[str, tuple[CellKey, ...]] = {}
    measurement_by_id: dict[str, dict[str, object]] = {}
    for scope in scopes:
        scope_id = scope.get("scope_id")
        pack_id = scope.get("pixel_pack_id")
        if not isinstance(scope_id, str) or not isinstance(pack_id, str):
            raise HQT3RAMGScheduleError("scope identity is malformed")
        cells = _scope_cells(scope, templates)
        previous = cells_by_pack.setdefault(pack_id, cells)
        if previous != cells:
            raise HQT3RAMGScheduleError(
                f"pixel pack digest collision for {pack_id}")
    pack_by_id = compile_pixel_packs(
        root, cells_by_pack, width, height, max_workers=max_workers)
    for pack_id in sorted(cells_by_pack):
        cells = cells_by_pack[pack_id]
        pack = pack_by_id[pack_id]
        measurement_by_id[pack_id] = _pack_measurement(
            pack_id, cells, pack, cell_bytes)

    scope_rows: list[dict[str, object]] = []
    for scope in scopes:
        scope_id = str(scope["scope_id"])
        pack_id = str(scope["pixel_pack_id"])
        pixel = measurement_by_id[pack_id]
        if pixel["selected_logical_argb4444_bytes"] != scope.get(
                "selected_argb4444_bytes"):
            raise HQT3RAMGScheduleError(
                f"scope {scope_id} ARGB4444 byte proof changed")
        hqt3 = _hqt3_for_scope(scope, templates, pack_by_id[pack_id])
        capacity = _scope_capacity(pixel, hqt3)
        scope_rows.append({
            "scope_id": scope_id,
            "kind": scope.get("kind"),
            "stage": scope.get("stage"),
            "class_name": scope.get("class_name"),
            "pixel_pack_id": pack_id,
            "pixel_pack": pixel,
            "hqt3": hqt3,
            "capacity": capacity,
            "resident": False,
            "loadable_scope_only": True,
        })
    scope_rows.sort(key=lambda item: str(item["scope_id"]))
    scope_by_id = {str(item["scope_id"]): item for item in scope_rows}
    if len(scope_by_id) != len(scope_rows):
        raise HQT3RAMGScheduleError("scope identity is not unique")

    common = load_plan.get("common_scope_ids")
    ambient = load_plan.get("ambient_stage_scope_ids")
    force = load_plan.get("force_palette_epochs")
    if (not isinstance(common, list) or not isinstance(ambient, list) or
            not isinstance(force, dict) or
            not isinstance(force.get("candidate_scope_ids"), list) or
            force.get("at_most_one_live_epoch") is not True):
        raise HQT3RAMGScheduleError("inventory load-domain evidence is missing")
    transitions = derive_event_transition_obligations(
        events,
        scope_by_id,
        [str(item) for item in ambient],
        [str(item) for item in common],
        [str(item) for item in force["candidate_scope_ids"]],
    )

    ramg_nonfit = [
        str(item["scope_id"]) for item in scope_rows
        if item["capacity"]["ram_g_isolated_fit"] is not True]
    ts_compiled_nonfit = [
        str(item["scope_id"]) for item in scope_rows
        if item["capacity"]["ts_staging_compiled_isolated_fit"] is not True]
    ts_raw_nonfit = [
        str(item["scope_id"]) for item in scope_rows
        if item["capacity"]["ts_staging_raw_argb4444_isolated_fit"] is not True]
    state_nonfit = [
        str(item["scope_id"]) for item in scope_rows
        if item["hqt3"]["uint16_record_cell_and_uint8_state_indices_fit"]
        is not True]
    worst_ramg = max(
        scope_rows, key=lambda item: int(
            item["capacity"]["ram_g_payload_bytes"]))
    worst_hqt3 = max(
        scope_rows, key=lambda item: int(item["hqt3"]["total_bytes"]))
    worst_ts = max(
        scope_rows, key=lambda item: int(item["capacity"]
            ["ts_staging_compiled_payload_plus_hqt3_bytes"]))

    blockers: list[dict[str, object]] = []
    if ramg_nonfit:
        blockers.append({
            "code": "PZRG301",
            "scope": "isolated-scope-ft812-ram-g-capacity",
            "reason": (
                f"{len(ramg_nonfit)} source-derived scopes exceed the exact "
                "1 MiB FT812 RAM_G capacity even after lossless packing"),
            "scope_ids": ramg_nonfit,
        })
    if ts_compiled_nonfit:
        blockers.append({
            "code": "PZRG302",
            "scope": "isolated-scope-4mb-ts-staging-capacity",
            "reason": (
                f"{len(ts_compiled_nonfit)} compiled scope bundles exceed "
                "4 MiB before accounting for code/game state"),
            "scope_ids": ts_compiled_nonfit,
        })
    blockers.extend((
        {
            "code": "PZRG303",
            "scope": "event-to-scope-correlation",
            "reason": (
                f"{transitions['event_correlation_ambiguous_count']} event "
                "obligations still carry conservative class candidates"),
        },
        {
            "code": "PZRG304",
            "scope": "cross-event-object-lifetimes",
            "reason": (
                "the next ROM event does not terminate objects from earlier "
                "events; no source-derived last-draw intervals exist"),
        },
        {
            "code": "PZRG305",
            "scope": "gameplay-ram-g-co-residency",
            "reason": (
                "isolated scope fit does not allocate terrain, HUD, common, "
                "Force epoch, append fragments and live event scopes together"),
        },
        {
            "code": "PZRG306",
            "scope": "upload-eviction-and-display-list-fence",
            "reason": (
                "upload-before-first-draw, eviction-after-last-displayed-list "
                "and same-frame spawn ordering are not yet target-bound"),
        },
        {
            "code": "PZRG308",
            "scope": "whole-4mb-ts-allocation",
            "reason": (
                "per-scope TS staging checks exclude resident code, stacks, "
                "game state, audio and concurrent/double-buffered transfers"),
        },
    ))
    if state_nonfit:
        blockers.append({
            "code": "PZRG307",
            "scope": "hqt3-index-width",
            "reason": (
                f"{len(state_nonfit)} scopes exceed HQT3 record/cell/state "
                "field widths"),
            "scope_ids": state_nonfit,
        })

    inventory_binding = {
        "path": path.resolve().relative_to(root).as_posix(),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "analysis_sha256": stored_analysis,
        "source_binding_sha256": inventory.get("source_binding_sha256"),
        "global_template_rows_sha256": catalog.get("template_rows_sha256"),
        "template_count": len(templates),
        "scope_count": len(scope_rows),
        "event_count": len(events),
    }
    report: dict[str, object] = {
        "format": HQT3_RAMG_SCHEDULE_FORMAT,
        "status": HQT3_RAMG_SCHEDULE_STATUS,
        "scope_pack_proof_complete": True,
        "load_schedule_complete": False,
        "live": False,
        "inventory_binding": inventory_binding,
        "capacities": {
            "ft812_ram_g_bytes": FT812_RAM_G_BYTES,
            "tsconf_ram_bytes": TSCONF_RAM_BYTES,
            "storage_domains_are_separate": True,
            "pack_alignment": PACK_ALIGNMENT,
            "sprite_cell_width": width,
            "sprite_cell_height": height,
            "sprite_cell_argb4444_bytes": cell_bytes,
        },
        "scope_pack_census": {
            "scope_count": len(scope_rows),
            "unique_pixel_pack_count": len(measurement_by_id),
            "ram_g_isolated_fit_count": len(scope_rows) - len(ramg_nonfit),
            "ram_g_isolated_nonfit_count": len(ramg_nonfit),
            "ram_g_isolated_nonfit_scope_ids": ramg_nonfit,
            "ts_compiled_isolated_fit_count": (
                len(scope_rows) - len(ts_compiled_nonfit)),
            "ts_compiled_isolated_nonfit_count": len(ts_compiled_nonfit),
            "ts_compiled_isolated_nonfit_scope_ids": ts_compiled_nonfit,
            "ts_raw_argb4444_isolated_nonfit_count": len(ts_raw_nonfit),
            "ts_raw_argb4444_isolated_nonfit_scope_ids": ts_raw_nonfit,
            "hqt3_index_width_nonfit_count": len(state_nonfit),
            "hqt3_index_width_nonfit_scope_ids": state_nonfit,
            "worst_ram_g_scope_id": worst_ramg["scope_id"],
            "worst_ram_g_payload_bytes": worst_ramg["capacity"]
                ["ram_g_payload_bytes"],
            "worst_hqt3_scope_id": worst_hqt3["scope_id"],
            "worst_hqt3_bytes": worst_hqt3["hqt3"]["total_bytes"],
            "worst_ts_compiled_scope_id": worst_ts["scope_id"],
            "worst_ts_compiled_bundle_bytes": worst_ts["capacity"]
                ["ts_staging_compiled_payload_plus_hqt3_bytes"],
        },
        "scope_packs": scope_rows,
        "event_transitions": transitions,
        "resident_combinations": [],
        "whole_inventory_resident": False,
        "whole_stage_union_resident": False,
        "blockers": blockers,
        "proof_boundaries": {
            "active_inventory_and_source_binding": True,
            "all_scope_lossless_pixel_packs_measured": True,
            "exact_hqt3_record_cell_state_bytes": True,
            "upstream_inventory_fixed_hqt3_layout_matches_physical": True,
            "isolated_ft812_ram_g_fit_classified": True,
            "isolated_4mb_ts_staging_fit_classified_separately": True,
            "event_source_order_obligations_derived": True,
            "ambiguous_event_correlation_resolved": False,
            "cross_event_lifetimes_proved": False,
            "gameplay_ram_g_co_residency_allocated": False,
            "whole_4mb_ts_allocation_proved": False,
            "upload_eviction_display_list_fence_proved": False,
        },
    }
    semantic = dict(report)
    report["analysis_sha256"] = _sha256_value(semantic)
    return report


__all__ = [
    "FT812_RAM_G_BYTES",
    "HQT3_CELL_BYTES",
    "HQT3_HEADER_BYTES",
    "HQT3_RAMG_SCHEDULE_FORMAT",
    "HQT3_RAMG_SCHEDULE_STATUS",
    "HQT3_RECORD_BYTES",
    "HQT3_STATE_BYTES",
    "HQT3RAMGScheduleError",
    "TSCONF_RAM_BYTES",
    "analyze_hqt3_ramg_schedule",
    "compile_pixel_packs",
    "derive_event_transition_obligations",
]
