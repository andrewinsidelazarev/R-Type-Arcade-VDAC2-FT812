"""Exact FT812-aware packing of translated ARGB4444 bitmap cells.

The source images remain the immutable ARGB4444 output of the host-side
upscaler. This module only changes their storage representation when that can
be reversed byte-for-byte:

* ``ARGB4`` stores the original little-endian words;
* ``PALETTED4444`` stores one eight-bit index per pixel and a 256-entry
  ARGB4444 palette selected with ``PALETTE_SOURCE``.

Palettes are shared deterministically when the union of their colours fits
the FT812 limit. A cell with more than 256 colours, or a palette group which
would not save space, stays ARGB4. Consequently this compiler never
quantises, rescales, drops, or invents pixels and is suitable as a generic
backend pass rather than an R-Type-specific asset list.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .assets import (
    AssetCompileError,
    AssetPackBudget,
    CellBankSpec,
    CellKey,
    PackedCell,
    compile_cell_assets,
)


FT812_HYBRID_PACK_FORMAT = "pyz80-ft812-cell-pack-v1"
FT812_ARGB4 = 6
FT812_PALETTED4444 = 15
FT812_PALETTE_COLORS = 256
FT812_PALETTE_BYTES = FT812_PALETTE_COLORS * 2


@dataclass(frozen=True)
class FT812AssetPackBudget:
    """Hard limits for one resident FT812 working set."""

    max_logical_entries: int
    max_unique_cells: int
    max_palettes: int
    max_bytes: int
    alignment: int = 4

    def __post_init__(self) -> None:
        if min(
                self.max_logical_entries,
                self.max_unique_cells,
                self.max_palettes,
                self.max_bytes,
                ) <= 0:
            raise AssetCompileError(
                "all FT812 asset-pack limits must be positive")
        if self.alignment <= 0 or self.alignment & (self.alignment - 1):
            raise AssetCompileError(
                "FT812 asset-pack alignment must be a power of two")


@dataclass(frozen=True)
class FT812Palette:
    """One exact 256-entry PALETTED4444 colour table in the output blob."""

    offset: int
    color_count: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "offset": self.offset,
            "size": FT812_PALETTE_BYTES,
            "color_count": self.color_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class FT812PackedCell:
    """Target-side bitmap state and complete source provenance for one key."""

    key: CellKey
    offset: int
    size: int
    width: int
    height: int
    format_code: int
    stride: int
    palette_index: int | None
    palette_offset: int | None
    decoded_sha256: str
    payload_sha256: str
    source_path: str
    source_sha256: str
    source_offset: int

    @property
    def pixel_format(self) -> str:
        if self.format_code == FT812_ARGB4:
            return "ARGB4"
        if self.format_code == FT812_PALETTED4444:
            return "PALETTED4444"
        raise AssertionError(f"unknown FT812 format {self.format_code}")

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key.stable_name,
            "offset": self.offset,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "format_code": self.format_code,
            "format": self.pixel_format,
            "stride": self.stride,
            "palette_index": self.palette_index,
            "palette_offset": self.palette_offset,
            "decoded_sha256": self.decoded_sha256,
            "payload_sha256": self.payload_sha256,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class FT812CellAssetPack:
    """A self-contained hybrid cell blob ready for RAM_G relocation."""

    data: bytes
    entries: tuple[FT812PackedCell, ...]
    palettes: tuple[FT812Palette, ...]
    unique_cells: int
    alignment: int
    raw_argb4444_bytes: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def decode(self, entry: FT812PackedCell) -> bytes:
        """Reverse one target representation to exact ARGB4444 bytes."""
        payload = self.data[entry.offset:entry.offset + entry.size]
        if len(payload) != entry.size:
            raise AssetCompileError("FT812 cell payload is outside its pack")
        if entry.format_code == FT812_ARGB4:
            result = payload
        elif entry.format_code == FT812_PALETTED4444:
            if entry.palette_offset is None:
                raise AssetCompileError("PALETTED4444 cell has no palette")
            palette_data = self.data[
                entry.palette_offset:entry.palette_offset + FT812_PALETTE_BYTES]
            if len(palette_data) != FT812_PALETTE_BYTES:
                raise AssetCompileError("FT812 palette is outside its pack")
            result = b"".join(
                palette_data[index * 2:index * 2 + 2]
                for index in payload
            )
        else:
            raise AssetCompileError(
                f"unsupported FT812 bitmap format {entry.format_code}")
        if hashlib.sha256(result).hexdigest() != entry.decoded_sha256:
            raise AssetCompileError(
                f"FT812 round-trip changed {entry.key.stable_name}")
        return result

    def report(self) -> dict[str, object]:
        format_counts = {"ARGB4": 0, "PALETTED4444": 0}
        for entry in self.entries:
            format_counts[entry.pixel_format] += 1
        return {
            "format": FT812_HYBRID_PACK_FORMAT,
            "pixel_policy": (
                "exact ARGB4444 round-trip; shared PALETTED4444 only when "
                "lossless and smaller; no quantisation or scaling"),
            "alignment": self.alignment,
            "size": len(self.data),
            "sha256": self.sha256,
            "raw_argb4444_bytes": self.raw_argb4444_bytes,
            "saved_bytes": self.raw_argb4444_bytes - len(self.data),
            "logical_entries": len(self.entries),
            "unique_cells": self.unique_cells,
            "palette_count": len(self.palettes),
            "format_counts": format_counts,
            "palettes": [palette.as_dict() for palette in self.palettes],
            "entries": [entry.as_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class _UniqueCell:
    """One materialised, already flipped ARGB4444 source cell."""

    identity: tuple[str, int, int]
    payload: bytes
    width: int
    height: int
    colors: frozenset[int]
    first_key_name: str

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


@dataclass
class _PaletteGroup:
    colors: set[int]
    cells: list[_UniqueCell]


def _align(output: bytearray, alignment: int) -> None:
    output.extend(bytes((-len(output)) & (alignment - 1)))


def _colors(payload: bytes) -> frozenset[int]:
    if len(payload) & 1:
        raise AssetCompileError("ARGB4444 payload has an odd byte count")
    return frozenset(
        payload[offset] | (payload[offset + 1] << 8)
        for offset in range(0, len(payload), 2)
    )


def _palette_groups(cells: Iterable[_UniqueCell]) -> list[_PaletteGroup]:
    """Deterministic best-fit grouping under the 256-colour hardware cap."""
    candidates = sorted(
        (cell for cell in cells
         if len(cell.colors) <= FT812_PALETTE_COLORS),
        key=lambda cell: (
            -len(cell.colors), -cell.pixel_count,
            cell.identity, cell.first_key_name,
        ),
    )
    groups: list[_PaletteGroup] = []
    for cell in candidates:
        fits: list[tuple[int, int, int]] = []
        for index, group in enumerate(groups):
            union_size = len(group.colors | cell.colors)
            if union_size <= FT812_PALETTE_COLORS:
                # Prefer the greatest reuse, then the tightest resulting
                # palette, then the stable earlier group.
                fits.append((
                    len(group.colors & cell.colors), -union_size, -index))
        if fits:
            _overlap, _negative_union, negative_index = max(fits)
            group = groups[-negative_index]
            group.colors.update(cell.colors)
            group.cells.append(cell)
        else:
            groups.append(_PaletteGroup(set(cell.colors), [cell]))

    # An index image uses one byte per pixel and its table is always 512
    # bytes. Groups which do not beat the original two-byte pixels stay
    # ARGB4; equality also stays ARGB4 to avoid needless state changes.
    return [
        group for group in groups
        if sum(len(cell.payload) for cell in group.cells) >
        sum(cell.pixel_count for cell in group.cells) + FT812_PALETTE_BYTES
    ]


def compile_ft812_cell_assets(
        requested: Iterable[CellKey],
        banks: Iterable[CellBankSpec],
        budget: FT812AssetPackBudget,
        *,
        project_root: Path | None = None,
        ) -> FT812CellAssetPack:
    """Compile an exact deterministic ARGB4/PALETTED4444 working set.

    Returned offsets are relative. A target adapter may relocate the entire
    blob to any suitably aligned RAM_G base and add that base to both
    ``BITMAP_SOURCE`` and ``PALETTE_SOURCE``.
    """
    request_tuple = tuple(requested)
    bank_tuple = tuple(banks)
    raw = compile_cell_assets(
        request_tuple,
        bank_tuple,
        AssetPackBudget(
            max_logical_entries=budget.max_logical_entries,
            max_unique_cells=budget.max_unique_cells,
            # This intermediate is a proof object. Only the final FT812
            # representation is constrained by the resident byte budget.
            max_bytes=(1 << 63) - 1,
            alignment=budget.alignment,
        ),
        project_root=project_root,
    )

    unique_by_identity: dict[tuple[str, int, int], _UniqueCell] = {}
    raw_entry_by_key: dict[CellKey, PackedCell] = {}
    identity_by_key: dict[CellKey, tuple[str, int, int]] = {}
    for entry in raw.entries:
        payload = raw.data[entry.offset:entry.offset + entry.size]
        identity = (entry.payload_sha256, entry.width, entry.height)
        previous = unique_by_identity.get(identity)
        if previous is not None and previous.payload != payload:
            raise AssetCompileError("SHA-256 collision in FT812 asset compiler")
        if previous is None:
            unique_by_identity[identity] = _UniqueCell(
                identity=identity,
                payload=payload,
                width=entry.width,
                height=entry.height,
                colors=_colors(payload),
                first_key_name=entry.key.stable_name,
            )
        raw_entry_by_key[entry.key] = entry
        identity_by_key[entry.key] = identity

    groups = _palette_groups(unique_by_identity.values())
    if len(groups) > budget.max_palettes:
        raise AssetCompileError(
            f"FT812 asset pack needs {len(groups)} palettes, "
            f"limit is {budget.max_palettes}")

    palette_for_identity: dict[tuple[str, int, int], int] = {}
    palette_words: list[tuple[int, ...]] = []
    for index, group in enumerate(groups):
        words = tuple(sorted(group.colors))
        if len(words) > FT812_PALETTE_COLORS:
            raise AssertionError("palette grouping exceeded FT812 limit")
        palette_words.append(words)
        for cell in group.cells:
            if cell.identity in palette_for_identity:
                raise AssertionError("cell assigned to two FT812 palettes")
            palette_for_identity[cell.identity] = index

    output = bytearray()
    packed_by_identity: dict[
        tuple[str, int, int], tuple[int, int, int, int, int | None]
    ] = {}
    for identity, cell in sorted(unique_by_identity.items()):
        _align(output, budget.alignment)
        offset = len(output)
        palette_index = palette_for_identity.get(identity)
        if palette_index is None:
            payload = cell.payload
            format_code = FT812_ARGB4
            stride = cell.width * 2
        else:
            words = palette_words[palette_index]
            index_by_word = {word: index for index, word in enumerate(words)}
            payload = bytes(
                index_by_word[
                    cell.payload[pos] | (cell.payload[pos + 1] << 8)]
                for pos in range(0, len(cell.payload), 2)
            )
            format_code = FT812_PALETTED4444
            stride = cell.width
        output.extend(payload)
        packed_by_identity[identity] = (
            offset, len(payload), format_code, stride, palette_index)

    palettes: list[FT812Palette] = []
    palette_offsets: list[int] = []
    for words in palette_words:
        # PALETTE_SOURCE requires two-byte alignment. The stronger pack
        # alignment is retained to simplify DMA relocation and CMD_APPEND.
        _align(output, budget.alignment)
        offset = len(output)
        encoded = bytearray()
        for word in words:
            encoded.extend(word.to_bytes(2, "little"))
        encoded.extend(bytes(FT812_PALETTE_BYTES - len(encoded)))
        output.extend(encoded)
        palette_offsets.append(offset)
        palettes.append(FT812Palette(
            offset=offset,
            color_count=len(words),
            sha256=hashlib.sha256(encoded).hexdigest(),
        ))

    if len(output) > budget.max_bytes:
        raise AssetCompileError(
            f"FT812 asset pack needs {len(output)} bytes, "
            f"limit is {budget.max_bytes}")

    entries: list[FT812PackedCell] = []
    for key in sorted(raw_entry_by_key):
        source = raw_entry_by_key[key]
        identity = identity_by_key[key]
        offset, size, format_code, stride, palette_index = (
            packed_by_identity[identity])
        palette_offset = (
            None if palette_index is None else palette_offsets[palette_index])
        payload = output[offset:offset + size]
        entries.append(FT812PackedCell(
            key=key,
            offset=offset,
            size=size,
            width=source.width,
            height=source.height,
            format_code=format_code,
            stride=stride,
            palette_index=palette_index,
            palette_offset=palette_offset,
            decoded_sha256=source.payload_sha256,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            source_path=source.source_path,
            source_sha256=source.source_sha256,
            source_offset=source.source_offset,
        ))

    result = FT812CellAssetPack(
        data=bytes(output),
        entries=tuple(entries),
        palettes=tuple(palettes),
        unique_cells=len(unique_by_identity),
        alignment=budget.alignment,
        raw_argb4444_bytes=len(raw.data),
    )
    # Prove every logical key, including aliases, before an adapter may emit
    # target metadata.
    for entry in result.entries:
        result.decode(entry)
    return result


__all__ = [
    "FT812_ARGB4",
    "FT812_HYBRID_PACK_FORMAT",
    "FT812_PALETTED4444",
    "FT812_PALETTE_BYTES",
    "FT812_PALETTE_COLORS",
    "FT812AssetPackBudget",
    "FT812CellAssetPack",
    "FT812PackedCell",
    "FT812Palette",
    "compile_ft812_cell_assets",
]
