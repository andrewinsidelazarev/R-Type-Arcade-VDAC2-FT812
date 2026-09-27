#!/usr/bin/env python3
"""Офлайн-конверсия всех tile/sprite-cell R-Type в логический масштаб 640×480.

Каждый ROM-примитив и каждый из 16 аппаратных номеров палитры проходит
неизменный тракт проекта: xBRZ 1.9 ×6, затем Pillow Lanczos. Между ячейками
есть прозрачный бордюр, поэтому соседний код атласа не влияет на xBRZ.
Готовые ARGB4444-блоки предназначены одновременно для Python-эталона и FT812.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade
import m72_scene
import xbrz_offline


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PALETTE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_invincible_trace"
OUT = ROOT / "Assets" / "Converted" / "Arcade" / "FullHQ"
PADDING = 4


def pack_argb4444(image: Image.Image) -> bytes:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    a = (rgba[:, :, 3] * 15 + 127) // 255
    r = (rgba[:, :, 0] * 15 + 127) // 255
    g = (rgba[:, :, 1] * 15 + 127) // 255
    b = (rgba[:, :, 2] * 15 + 127) // 255
    words = ((a << 12) | (r << 8) | (g << 4) | b).astype("<u2")
    return words.tobytes()


def richest_palettes(capture: Path) -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
    """Выбрать для каждого банка реальный кадр с наибольшим числом цветов."""
    candidates: list[tuple[int, np.ndarray]] = []
    for path0 in sorted(capture.glob("frame_*_palette0.bin")):
        frame = int(path0.name.split("_")[1])
        path1 = capture / f"frame_{frame:06d}_palette1.bin"
        if not path1.is_file():
            continue
        colors = np.asarray(m72_scene.palette_from_ram(
            path0.read_bytes(), path1.read_bytes()), dtype=np.uint8)
        candidates.append((frame, colors))
    if not candidates:
        raise FileNotFoundError(f"в каталоге нет пар палитр: {capture}")
    banks = [np.empty((16, 16, 4), dtype=np.uint8),
             np.empty((16, 16, 4), dtype=np.uint8)]
    frames = [[0] * 16, [0] * 16]
    for hardware_bank in range(2):
        base = hardware_bank * 256
        for color in range(16):
            best_frame, best = max(
                candidates,
                key=lambda item: len({tuple(value) for value in
                                      item[1][base + color * 16:base + color * 16 + 16]}))
            banks[hardware_bank][color] = best[base + color * 16:base + color * 16 + 16]
            frames[hardware_bank][color] = best_frame
    return banks[0], banks[1], frames


def padded_cell(indices: np.ndarray, colors: np.ndarray) -> Image.Image:
    rgba = colors[indices].copy()
    rgba[indices == 0, 3] = 0
    cell = Image.fromarray(rgba, "RGBA")
    result = Image.new("RGBA", (cell.width + PADDING * 2,
                                cell.height + PADDING * 2))
    result.paste(cell, (PADDING, PADDING))
    return result


def convert_bank(name: str, cells: np.ndarray, colors: np.ndarray,
                 target: tuple[int, int], chunk: int,
                 output: Path) -> dict[str, object]:
    source_h, source_w = cells.shape[1:]
    padded_w = source_w + PADDING * 2
    padded_h = source_h + PADDING * 2
    columns = int(math.sqrt(chunk))
    columns = max(1, columns)
    blob = bytearray()
    chunks = 0
    for first in range(0, len(cells), chunk):
        last = min(first + chunk, len(cells))
        count = last - first
        rows = math.ceil(count / columns)
        sheet = Image.new("RGBA", (columns * padded_w, rows * padded_h))
        for local, code in enumerate(range(first, last)):
            x = (local % columns) * padded_w
            y = (local // columns) * padded_h
            sheet.paste(padded_cell(cells[code], colors),
                        (x, y))
        expanded = xbrz_offline.xbrz_expand(sheet, 6)
        for local in range(count):
            x = (local % columns) * padded_w
            y = (local // columns) * padded_h
            left = (x + PADDING) * 6
            top = (y + PADDING) * 6
            logical = expanded.crop((left, top, left + source_w * 6,
                                     top + source_h * 6)).resize(
                                         target, Image.Resampling.LANCZOS)
            blob += pack_argb4444(logical)
        chunks += 1
    output.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    print(f"{name}: {len(cells)} ячеек, {len(blob)} Б, SHA256 {digest}", flush=True)
    return {
        "path": str(output.relative_to(ROOT)),
        "cells": len(cells),
        "cell_size": list(target),
        "cell_bytes": target[0] * target[1] * 2,
        "chunks": chunks,
        "size": len(blob),
        "sha256": digest,
    }


def build_mix_map(palettes: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Для каждого RGB444 найти пару исходных pens и вес их смешения."""
    result_a = np.empty((16, 4096), dtype=np.uint8)
    result_b = np.empty((16, 4096), dtype=np.uint8)
    result_w = np.empty((16, 4096), dtype=np.uint8)
    values = np.arange(4096, dtype=np.int16)
    targets = np.stack(((values >> 8) & 15, (values >> 4) & 15, values & 15), axis=1)
    for bank in range(16):
        source = ((palettes[bank, :, :3].astype(np.int16) * 15 + 127) // 255)
        candidate_colors = []
        candidate_a = []
        candidate_b = []
        candidate_w = []
        for a in range(16):
            for b in range(16):
                for weight in range(16):
                    candidate_colors.append(
                        (source[a] * (15 - weight) + source[b] * weight + 7) // 15)
                    candidate_a.append(a)
                    candidate_b.append(b)
                    candidate_w.append(weight)
        candidates = np.asarray(candidate_colors, dtype=np.int16)
        best = np.empty(4096, dtype=np.int32)
        for first in range(0, 4096, 128):
            delta = targets[first:first + 128, None, :] - candidates[None, :, :]
            distance = np.sum(delta * delta, axis=2)
            best[first:first + 128] = np.argmin(distance, axis=1)
        result_a[bank] = np.asarray(candidate_a, dtype=np.uint8)[best]
        result_b[bank] = np.asarray(candidate_b, dtype=np.uint8)[best]
        result_w[bank] = np.asarray(candidate_w, dtype=np.uint8)[best]
    return result_a, result_b, result_w


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, default=DEFAULT_PALETTE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--tile-chunk", type=int, default=4096)
    parser.add_argument("--sprite-chunk", type=int, default=1024)
    args = parser.parse_args()

    m72_arcade.require_verified()
    graphics = m72_scene.Graphics.load()
    sources = {
        "TILES0": (np.frombuffer(graphics.tiles0, dtype=np.uint8).reshape(-1, 8, 8),
                   1, (14, 15), args.tile_chunk),
        "TILES1": (np.frombuffer(graphics.tiles1, dtype=np.uint8).reshape(-1, 8, 8),
                   1, (14, 15), args.tile_chunk),
        "SPRITES": (np.frombuffer(graphics.sprites, dtype=np.uint8).reshape(-1, 16, 16),
                    0, (27, 30), args.sprite_chunk),
    }
    sprite_palettes, tile_palettes, palette_frames = richest_palettes(args.capture)
    palette_sets = (sprite_palettes, tile_palettes)
    args.out.mkdir(parents=True, exist_ok=True)
    assets: dict[str, object] = {}
    for source_name, (cells, hardware_bank, target, chunk) in sources.items():
        for color in range(16):
            name = f"RTYPE_{source_name}_PAL{color:02X}_HQ_ARGB4444.bin"
            assets[name] = convert_bank(
                f"{source_name}/PAL{color:02X}", cells,
                palette_sets[hardware_bank][color], target, chunk, args.out / name)

    sprite_a, sprite_b, sprite_w = build_mix_map(sprite_palettes)
    tile_a, tile_b, tile_w = build_mix_map(tile_palettes)
    recolor_path = args.out / "RTYPE_HQ_RECOLOR_MAPS.npz"
    np.savez_compressed(recolor_path, sprite_a=sprite_a, sprite_b=sprite_b,
                        sprite_w=sprite_w, tile_a=tile_a, tile_b=tile_b,
                        tile_w=tile_w)

    manifest = {
        "format": 1,
        "source": "Arcade/rtype World ROM; exact decoded pen indices",
        "palette_capture": str(args.capture.relative_to(ROOT)),
        "palette_frames": {"sprites": palette_frames[0], "tiles": palette_frames[1]},
        "algorithm": "isolated transparent primitive -> xBRZ 1.9 x6 -> Pillow Lanczos",
        "logical_scale": {"x": "5/3", "y": "15/8"},
        "tile_cell": [14, 15],
        "sprite_cell": [27, 30],
        "format_ft812": "ARGB4444 little-endian",
        "recolor_map": str(recolor_path.relative_to(ROOT)),
        "assets": assets,
    }
    manifest_path = args.out / "full_hq_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(f"Манифест: {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
