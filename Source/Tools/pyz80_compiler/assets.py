"""Детерминированная упаковка достижимых растровых ячеек Python для FT812.

Модуль не меняет цвет, размер или фильтрацию исходного растра. Он выбирает
только явно перечисленные логические ячейки из проверенных банков, при
необходимости материализует тот же flip, что выполняет Python, и удаляет лишь
побайтно одинаковые копии. Поэтому результат пригоден как общий нижний слой
для игровых трансляторов, не привязанный к R-Type или структуре его уровней.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


ASSET_PACK_FORMAT = "pyz80-cell-pack-v1"
ARGB4444_LE = "ARGB4444 little-endian"


class AssetCompileError(ValueError):
    """Ошибка, при которой продолжение сборки изменило бы пиксели или бюджет."""


@dataclass(frozen=True, order=True)
class CellSourceKey:
    """Логическое имя одного исходного банка одинаковой геометрии."""

    namespace: str
    resource: str = ""
    palette: int = -1

    def __post_init__(self) -> None:
        if not self.namespace:
            raise AssetCompileError("namespace банка не может быть пустым")
        if not -1 <= self.palette <= 0xFFFF:
            raise AssetCompileError("palette банка выходит за диапазон -1..65535")

    @property
    def stable_name(self) -> str:
        palette = "none" if self.palette < 0 else f"{self.palette:04X}"
        return f"{self.namespace}:{self.resource}:{palette}"


@dataclass(frozen=True, order=True)
class CellKey:
    """Идентификатор ячейки, наблюдаемой активным Python-runtime."""

    source: CellSourceKey
    code: int
    flip_x: bool = False
    flip_y: bool = False

    def __post_init__(self) -> None:
        if self.code < 0:
            raise AssetCompileError("code ячейки не может быть отрицательным")

    @property
    def stable_name(self) -> str:
        return (
            f"{self.source.stable_name}:{self.code:04X}:"
            f"fx{int(self.flip_x)}:fy{int(self.flip_y)}"
        )


@dataclass(frozen=True)
class CellBankSpec:
    """Описание неизменяемого файла с плотно уложенными ячейками."""

    key: CellSourceKey
    path: Path
    cell_width: int
    cell_height: int
    cell_count: int
    pixel_format: str = ARGB4444_LE

    def __post_init__(self) -> None:
        if self.pixel_format != ARGB4444_LE:
            raise AssetCompileError(
                f"{self.key.stable_name}: поддерживается только {ARGB4444_LE}"
            )
        if self.cell_width <= 0 or self.cell_height <= 0:
            raise AssetCompileError(
                f"{self.key.stable_name}: размеры ячейки должны быть положительными"
            )
        if self.cell_count <= 0:
            raise AssetCompileError(
                f"{self.key.stable_name}: число ячеек должно быть положительным"
            )

    @property
    def cell_bytes(self) -> int:
        return self.cell_width * self.cell_height * 2


@dataclass(frozen=True)
class AssetPackBudget:
    """Жёсткие пределы одного набора, загружаемого в память цели."""

    max_logical_entries: int
    max_unique_cells: int
    max_bytes: int
    alignment: int = 4

    def __post_init__(self) -> None:
        if min(self.max_logical_entries, self.max_unique_cells, self.max_bytes) <= 0:
            raise AssetCompileError("все пределы asset pack должны быть положительными")
        if self.alignment <= 0 or self.alignment & (self.alignment - 1):
            raise AssetCompileError("alignment asset pack должен быть степенью двойки")


@dataclass(frozen=True)
class PackedCell:
    """Проверяемое соответствие логической ячейки участку готового пакета."""

    key: CellKey
    offset: int
    size: int
    width: int
    height: int
    pixel_format: str
    payload_sha256: str
    source_path: str
    source_sha256: str
    source_offset: int

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key.stable_name,
            "namespace": self.key.source.namespace,
            "resource": self.key.source.resource,
            "palette": self.key.source.palette,
            "code": self.key.code,
            "flip_x": self.key.flip_x,
            "flip_y": self.key.flip_y,
            "offset": self.offset,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "format": self.pixel_format,
            "sha256": self.payload_sha256,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class CellAssetPack:
    """Готовые байты и полный отчёт о происхождении каждой ссылки."""

    data: bytes
    entries: tuple[PackedCell, ...]
    unique_cells: int
    alignment: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def report(self) -> dict[str, object]:
        sources: dict[tuple[str, str], dict[str, object]] = {}
        for entry in self.entries:
            source_key = (entry.source_path, entry.source_sha256)
            source = sources.setdefault(source_key, {
                "path": entry.source_path,
                "sha256": entry.source_sha256,
                "selected_entries": 0,
            })
            source["selected_entries"] = int(source["selected_entries"]) + 1
        return {
            "format": ASSET_PACK_FORMAT,
            "pixel_policy": "exact-source-bytes; optional exact cell flip; no scaling",
            "alignment": self.alignment,
            "size": len(self.data),
            "sha256": self.sha256,
            "logical_entries": len(self.entries),
            "unique_cells": self.unique_cells,
            "deduplicated_entries": len(self.entries) - self.unique_cells,
            "sources": [sources[key] for key in sorted(sources)],
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _display_path(path: Path, project_root: Path | None) -> str:
    resolved = path.resolve()
    if project_root is not None:
        try:
            resolved = resolved.relative_to(project_root.resolve())
        except ValueError:
            pass
    return resolved.as_posix()


def _flip_argb4444_le(
        payload: bytes, width: int, height: int, flip_x: bool, flip_y: bool,
        ) -> bytes:
    """Переставить целые 16-битные пиксели без изменения их значения."""
    if not flip_x and not flip_y:
        return payload
    rows = [
        [payload[(y * width + x) * 2:(y * width + x + 1) * 2]
         for x in range(width)]
        for y in range(height)
    ]
    if flip_y:
        rows.reverse()
    if flip_x:
        for row in rows:
            row.reverse()
    return b"".join(pixel for row in rows for pixel in row)


def compile_cell_assets(
        requested: Iterable[CellKey],
        banks: Iterable[CellBankSpec],
        budget: AssetPackBudget,
        *,
        project_root: Path | None = None,
        ) -> CellAssetPack:
    """Выбрать, проверить и детерминированно упаковать указанные ячейки."""
    requested_keys = tuple(sorted(set(requested)))
    if len(requested_keys) > budget.max_logical_entries:
        raise AssetCompileError(
            f"asset pack: {len(requested_keys)} логических ячеек больше предела "
            f"{budget.max_logical_entries}"
        )

    bank_map: dict[CellSourceKey, CellBankSpec] = {}
    for bank in banks:
        if bank.key in bank_map:
            raise AssetCompileError(
                f"повторное описание банка {bank.key.stable_name}"
            )
        bank_map[bank.key] = bank

    source_data: dict[CellSourceKey, bytes] = {}
    source_hashes: dict[CellSourceKey, str] = {}
    for source_key in sorted({key.source for key in requested_keys}):
        bank = bank_map.get(source_key)
        if bank is None:
            raise AssetCompileError(
                f"не описан банк {source_key.stable_name}"
            )
        try:
            data = bank.path.read_bytes()
        except OSError as exc:
            raise AssetCompileError(
                f"не читается банк {source_key.stable_name}: {exc}"
            ) from exc
        expected_size = bank.cell_count * bank.cell_bytes
        if len(data) != expected_size:
            raise AssetCompileError(
                f"{source_key.stable_name}: размер {len(data)}, ожидалось "
                f"{expected_size} ({bank.cell_count}×{bank.cell_bytes})"
            )
        source_data[source_key] = data
        source_hashes[source_key] = hashlib.sha256(data).hexdigest()

    output = bytearray()
    entries: list[PackedCell] = []
    # Геометрия входит в ключ: одинаковая последовательность байтов разных
    # форматов или размеров не должна случайно получить общий FT812 state.
    unique: dict[tuple[str, int, int, str], list[tuple[bytes, int]]] = {}
    for key in requested_keys:
        bank = bank_map[key.source]
        if key.code >= bank.cell_count:
            raise AssetCompileError(
                f"{key.stable_name}: code вне {bank.cell_count} ячеек банка"
            )
        source_offset = key.code * bank.cell_bytes
        payload = source_data[key.source][
            source_offset:source_offset + bank.cell_bytes]
        payload = _flip_argb4444_le(
            payload, bank.cell_width, bank.cell_height,
            key.flip_x, key.flip_y,
        )
        digest = hashlib.sha256(payload).hexdigest()
        identity = (digest, bank.cell_width, bank.cell_height, bank.pixel_format)
        offset: int | None = None
        for previous_payload, previous_offset in unique.get(identity, ()):
            if previous_payload == payload:
                offset = previous_offset
                break
        if offset is None:
            if sum(len(items) for items in unique.values()) >= budget.max_unique_cells:
                raise AssetCompileError(
                    f"asset pack: число уникальных ячеек больше предела "
                    f"{budget.max_unique_cells}"
                )
            padding = (-len(output)) & (budget.alignment - 1)
            projected = len(output) + padding + len(payload)
            if projected > budget.max_bytes:
                raise AssetCompileError(
                    f"asset pack: требуется {projected} байт, предел {budget.max_bytes}"
                )
            output.extend(bytes(padding))
            offset = len(output)
            output.extend(payload)
            unique.setdefault(identity, []).append((payload, offset))
        entries.append(PackedCell(
            key=key,
            offset=offset,
            size=len(payload),
            width=bank.cell_width,
            height=bank.cell_height,
            pixel_format=bank.pixel_format,
            payload_sha256=digest,
            source_path=_display_path(bank.path, project_root),
            source_sha256=source_hashes[key.source],
            source_offset=source_offset,
        ))

    unique_count = sum(len(items) for items in unique.values())
    return CellAssetPack(
        data=bytes(output),
        entries=tuple(entries),
        unique_cells=unique_count,
        alignment=budget.alignment,
    )
