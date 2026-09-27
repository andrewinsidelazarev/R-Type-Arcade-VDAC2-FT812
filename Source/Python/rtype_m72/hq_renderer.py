"""Композиция готовых офлайн-HQ примитивов непосредственно в 640×480."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from numba import njit
from PIL import Image

from .machine import FrameState


ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "FullHQ"
WIDTH = 640
HEIGHT = 480
PLAYFIELD_HEIGHT = 450
FG_LAYER0 = np.asarray((0xFFFF, 0x00FF, 0x0001, 0x0001), dtype=np.uint16)
FG_LAYER1 = np.asarray((0x0001, 0xFF01, 0xFFFF, 0xFFFF), dtype=np.uint16)
BG_PRIORITY = np.asarray((0xFFFF, 0x00FF, 0x0001, 0x0001), dtype=np.uint16)
BG_LAYER0 = np.asarray((0xFFFF, 0x00FF, 0xFFFF, 0x0001), dtype=np.uint16)
BG_LAYER1 = np.asarray((0x0000, 0xFF00, 0x0000, 0xFFFE), dtype=np.uint16)


@njit(cache=True)
def _round_ratio(value: int, numerator: int, denominator: int) -> int:
    scaled = value * numerator
    if scaled >= 0:
        return (scaled + denominator // 2) // denominator
    return -((-scaled + denominator // 2) // denominator)


@njit(cache=True)
def _blend(target: np.ndarray, y: int, x: int, source: int) -> None:
    alpha = (source >> 12) & 15
    if alpha == 0:
        return
    if alpha == 15:
        target[y, x] = source | 0xF000
        return
    old = int(target[y, x])
    inverse = 15 - alpha
    red = (((source >> 8) & 15) * alpha + ((old >> 8) & 15) * inverse + 7) // 15
    green = (((source >> 4) & 15) * alpha + ((old >> 4) & 15) * inverse + 7) // 15
    blue = ((source & 15) * alpha + (old & 15) * inverse + 7) // 15
    target[y, x] = 0xF000 | (red << 8) | (green << 4) | blue


@njit(cache=True)
def _draw_tile_layer(target: np.ndarray, blocked: np.ndarray,
                     atlas: np.ndarray, vram: np.ndarray,
                     map_a: np.ndarray, map_b: np.ndarray, map_w: np.ndarray,
                     colors: np.ndarray, masks: np.ndarray,
                     block_masks: np.ndarray, mark_blocked: bool,
                     scroll_x: int, scroll_y: int,
                     clip_top: int, clip_bottom: int) -> None:
    for row in range(64):
        native_y = ((row * 8 - 128 - scroll_y + 8) & 511) - 8
        if native_y >= 256 or native_y + 8 <= 0:
            continue
        top = _round_ratio(native_y, 15, 8)
        for column in range(64):
            native_x = ((column * 8 - 64 - scroll_x + 8) & 511) - 8
            if native_x >= 384 or native_x + 8 <= 0:
                continue
            left = _round_ratio(native_x, 5, 3)
            tile_index = row * 64 + column
            code_word = int(vram[tile_index * 2])
            attribute = int(vram[tile_index * 2 + 1])
            code = code_word & 0x3FFF
            palette = attribute & 15
            flip_x = bool(code_word & 0x4000)
            flip_y = bool(code_word & 0x8000)
            for local_y in range(15):
                dest_y = top + local_y
                if dest_y < clip_top or dest_y >= clip_bottom or dest_y < 0 or dest_y >= HEIGHT:
                    continue
                source_y = 14 - local_y if flip_y else local_y
                for local_x in range(14):
                    dest_x = left + local_x
                    if dest_x < 0 or dest_x >= WIDTH:
                        continue
                    source_x = 13 - local_x if flip_x else local_x
                    source = int(atlas[palette, code, source_y, source_x])
                    alpha = (source >> 12) & 15
                    if alpha == 0:
                        continue
                    rgb = source & 0x0FFF
                    pen_a = int(map_a[palette, rgb])
                    pen_b = int(map_b[palette, rgb])
                    weight_b = int(map_w[palette, rgb])
                    weight_a = 15 - weight_b
                    group = (attribute >> 6) & 3
                    if mark_blocked:
                        block_mask = int(block_masks[group])
                        if ((weight_a and not (block_mask & (1 << pen_a))) or
                                (weight_b and not (block_mask & (1 << pen_b)))):
                            blocked[dest_y, dest_x] = True
                    mask = int(masks[group])
                    if mask & (1 << pen_a):
                        weight_a = 0
                    if mask & (1 << pen_b):
                        weight_b = 0
                    total = weight_a + weight_b
                    if total == 0:
                        continue
                    alpha = (alpha * total + 7) // 15
                    red = (int(colors[palette, pen_a, 0]) * weight_a +
                           int(colors[palette, pen_b, 0]) * weight_b + total // 2) // total
                    green = (int(colors[palette, pen_a, 1]) * weight_a +
                             int(colors[palette, pen_b, 1]) * weight_b + total // 2) // total
                    blue = (int(colors[palette, pen_a, 2]) * weight_a +
                            int(colors[palette, pen_b, 2]) * weight_b + total // 2) // total
                    _blend(target, dest_y, dest_x,
                           (alpha << 12) | (red << 8) | (green << 4) | blue)


@njit(cache=True)
def _mark_tile_blocked(blocked: np.ndarray, atlas: np.ndarray, vram: np.ndarray,
                       map_a: np.ndarray, map_b: np.ndarray, map_w: np.ndarray,
                       masks: np.ndarray, scroll_x: int, scroll_y: int,
                       clip_top: int, clip_bottom: int) -> None:
    for row in range(64):
        native_y = ((row * 8 - 128 - scroll_y + 8) & 511) - 8
        if native_y >= 256 or native_y + 8 <= 0:
            continue
        top = _round_ratio(native_y, 15, 8)
        for column in range(64):
            native_x = ((column * 8 - 64 - scroll_x + 8) & 511) - 8
            if native_x >= 384 or native_x + 8 <= 0:
                continue
            left = _round_ratio(native_x, 5, 3)
            tile_index = row * 64 + column
            code_word = int(vram[tile_index * 2])
            attribute = int(vram[tile_index * 2 + 1])
            code = code_word & 0x3FFF
            palette = attribute & 15
            flip_x = bool(code_word & 0x4000)
            flip_y = bool(code_word & 0x8000)
            mask = int(masks[(attribute >> 6) & 3])
            for local_y in range(15):
                dest_y = top + local_y
                if dest_y < clip_top or dest_y >= clip_bottom or dest_y < 0 or dest_y >= HEIGHT:
                    continue
                source_y = 14 - local_y if flip_y else local_y
                for local_x in range(14):
                    dest_x = left + local_x
                    if dest_x < 0 or dest_x >= WIDTH:
                        continue
                    source_x = 13 - local_x if flip_x else local_x
                    source = int(atlas[palette, code, source_y, source_x])
                    if ((source >> 12) & 15) == 0:
                        continue
                    rgb = source & 0x0FFF
                    pen_a = int(map_a[palette, rgb])
                    pen_b = int(map_b[palette, rgb])
                    weight_b = int(map_w[palette, rgb])
                    weight_a = 15 - weight_b
                    if weight_a and not (mask & (1 << pen_a)):
                        blocked[dest_y, dest_x] = True
                    if weight_b and not (mask & (1 << pen_b)):
                        blocked[dest_y, dest_x] = True


@njit(cache=True)
def _draw_sprites(target: np.ndarray, atlas: np.ndarray,
                  recolor: np.ndarray, blocked: np.ndarray,
                  sprite_words: np.ndarray) -> None:
    offsets = np.empty(128, dtype=np.int32)
    count = 0
    offset = 0
    while offset < len(sprite_words):
        offsets[count] = offset
        count += 1
        width = 1 << ((int(sprite_words[offset + 2]) >> 14) & 3)
        offset += width * 4
    for item in range(count - 1, -1, -1):
        offset = offsets[item]
        code = int(sprite_words[offset + 1])
        attribute = int(sprite_words[offset + 2])
        palette = attribute & 15
        width = 1 << ((attribute >> 14) & 3)
        height = 1 << ((attribute >> 12) & 3)
        flip_x = bool(attribute & 0x0800)
        flip_y = bool(attribute & 0x0400)
        native_x = -256 + (int(sprite_words[offset + 3]) & 0x3FF) - 64
        native_y = 384 - (int(sprite_words[offset]) & 0x1FF) - 16 * height
        for cell_x in range(width):
            for cell_y in range(height):
                cell_code = code
                cell_code += 8 * (width - 1 - cell_x if flip_x else cell_x)
                cell_code += height - 1 - cell_y if flip_y else cell_y
                cell_code &= 0x0FFF
                left = _round_ratio(native_x + cell_x * 16, 5, 3)
                top = _round_ratio(native_y + cell_y * 16, 15, 8)
                for local_y in range(30):
                    dest_y = top + local_y
                    # Аппаратное игровое поле заканчивается перед нижним HUD.
                    if dest_y < 0 or dest_y >= PLAYFIELD_HEIGHT:
                        continue
                    source_y = 29 - local_y if flip_y else local_y
                    for local_x in range(27):
                        dest_x = left + local_x
                        if dest_x < 0 or dest_x >= WIDTH or blocked[dest_y, dest_x]:
                            continue
                        source_x = 26 - local_x if flip_x else local_x
                        source = int(atlas[palette, cell_code, source_y, source_x])
                        source = ((source & 0xF000) |
                                  int(recolor[palette, source & 0x0FFF]))
                        _blend(target, dest_y, dest_x, source)


@njit(cache=True)
def _words_to_rgba(words: np.ndarray, rgba: np.ndarray) -> None:
    for y in range(HEIGHT):
        for x in range(WIDTH):
            value = int(words[y, x])
            rgba[y, x, 0] = ((value >> 8) & 15) * 17
            rgba[y, x, 1] = ((value >> 4) & 15) * 17
            rgba[y, x, 2] = (value & 15) * 17
            rgba[y, x, 3] = 255


@njit(cache=True)
def _build_recolor(map_a: np.ndarray, map_b: np.ndarray, map_w: np.ndarray,
                   colors: np.ndarray, result: np.ndarray) -> None:
    for palette in range(16):
        for rgb in range(4096):
            a = int(map_a[palette, rgb])
            b = int(map_b[palette, rgb])
            weight = int(map_w[palette, rgb])
            red = (int(colors[palette, a, 0]) * (15 - weight) +
                   int(colors[palette, b, 0]) * weight + 7) // 15
            green = (int(colors[palette, a, 1]) * (15 - weight) +
                     int(colors[palette, b, 1]) * weight + 7) // 15
            blue = (int(colors[palette, a, 2]) * (15 - weight) +
                    int(colors[palette, b, 2]) * weight + 7) // 15
            result[palette, rgb] = (red << 8) | (green << 4) | blue


class M72HqRenderer:
    """Рисует 640×480 только готовыми xBRZ6+Lanczos ARGB4444-ячейками."""

    def __init__(self, asset_dir: Path = ASSET_DIR) -> None:
        manifest_path = asset_dir / "full_hq_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"HQ-атласы ещё не собраны: {manifest_path}")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.tiles0 = self._load_set(asset_dir, "TILES0", 15, 14)
        self.tiles1 = self._load_set(asset_dir, "TILES1", 15, 14)
        self.sprites = self._load_set(asset_dir, "SPRITES", 30, 27)
        maps = np.load(asset_dir / "RTYPE_HQ_RECOLOR_MAPS.npz")
        self.sprite_map = (maps["sprite_a"], maps["sprite_b"], maps["sprite_w"])
        self.tile_map = (maps["tile_a"], maps["tile_b"], maps["tile_w"])
        self.sprite_recolor = np.empty((16, 4096), dtype=np.uint16)
        self._last_sprite_palette: bytes | None = None
        self.words = np.full((HEIGHT, WIDTH), 0xF000, dtype=np.uint16)
        self.blocked = np.zeros((HEIGHT, WIDTH), dtype=np.bool_)
        self.rgba = np.empty((HEIGHT, WIDTH, 4), dtype=np.uint8)

    @staticmethod
    def _load_set(asset_dir: Path, name: str, height: int, width: int) -> np.ndarray:
        result = np.empty((16, 4096, height, width), dtype=np.uint16)
        expected = 4096 * height * width
        for palette in range(16):
            path = asset_dir / f"RTYPE_{name}_PAL{palette:02X}_HQ_ARGB4444.bin"
            words = np.fromfile(path, dtype="<u2")
            if len(words) != expected:
                raise ValueError(f"неверный размер HQ-атласа: {path}")
            result[palette] = words.reshape(4096, height, width)
        return result

    def render(self, frame: FrameState) -> Image.Image:
        self.words.fill(0xF000)
        self.blocked.fill(False)
        if frame.video_off:
            return Image.new("RGB", (WIDTH, HEIGHT), "black")
        vram0 = np.frombuffer(frame.vram0, dtype="<u2")
        vram1 = np.frombuffer(frame.vram1, dtype="<u2")
        if frame.palette0 != self._last_sprite_palette:
            _build_recolor(*self.sprite_map, self._palette4(frame.palette0),
                           self.sprite_recolor)
            self._last_sprite_palette = frame.palette0
        tile_colors = self._palette4(frame.palette1)
        tile_a, tile_b, tile_w = self.tile_map
        rows = frame.row_scroll
        first = 0
        while first < 256:
            state = rows[first]
            last = first + 1
            while last < 256 and rows[last] == state:
                last += 1
            clip_top = _round_ratio(first, 15, 8)
            clip_bottom = _round_ratio(last, 15, 8)
            _draw_tile_layer(self.words, self.blocked, self.tiles1, vram1,
                             tile_a, tile_b, tile_w, tile_colors, BG_LAYER1,
                             BG_LAYER1, False,
                             int(state[2]), int(state[3]), clip_top, clip_bottom)
            _draw_tile_layer(self.words, self.blocked, self.tiles0, vram0,
                             tile_a, tile_b, tile_w, tile_colors, FG_LAYER1,
                             FG_LAYER1, False,
                             int(state[0]), int(state[1]), clip_top, clip_bottom)
            _draw_tile_layer(self.words, self.blocked, self.tiles1, vram1,
                             tile_a, tile_b, tile_w, tile_colors, BG_LAYER0,
                             BG_PRIORITY, True,
                             int(state[2]), int(state[3]), clip_top, clip_bottom)
            _draw_tile_layer(self.words, self.blocked, self.tiles0, vram0,
                             tile_a, tile_b, tile_w, tile_colors, FG_LAYER0,
                             FG_LAYER0, True,
                             int(state[0]), int(state[1]), clip_top, clip_bottom)
            first = last
        _draw_sprites(self.words, self.sprites, self.sprite_recolor, self.blocked,
                      np.frombuffer(frame.spriteram, dtype="<u2"))
        _words_to_rgba(self.words, self.rgba)
        return Image.fromarray(self.rgba, "RGBA")

    @staticmethod
    def _palette4(data: bytes) -> np.ndarray:
        words = np.frombuffer(data, dtype="<u2")
        colors = np.empty((16, 16, 3), dtype=np.uint8)
        for palette in range(16):
            first = palette * 16
            for pen in range(16):
                index = first + pen
                colors[palette, pen, 0] = ((int(words[index]) & 31) * 15 + 15) // 31
                colors[palette, pen, 1] = ((int(words[index + 0x200]) & 31) * 15 + 15) // 31
                colors[palette, pen, 2] = ((int(words[index + 0x400]) & 31) * 15 + 15) // 31
        return colors
