"""Живой программный рендерер видеосостояния Irem M72."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from numba import njit
from PIL import Image

from .machine import FrameState


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "Source" / "Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import m72_scene


WIDTH = 384
HEIGHT = 256
PLAYFIELD_HEIGHT = 240
RAW_VISIBLE_X = 64
FG_LAYER0 = np.asarray(m72_scene.FG_LAYER0_MASK, dtype=np.uint16)
FG_LAYER1 = np.asarray(m72_scene.FG_LAYER1_MASK, dtype=np.uint16)
BG_PRIORITY = np.asarray(m72_scene.BG_PRIORITY_LAYER0_MASK, dtype=np.uint16)
BG_LAYER0 = np.asarray(m72_scene.BG_LAYER0_MASK, dtype=np.uint16)
BG_LAYER1 = np.asarray(m72_scene.BG_LAYER1_MASK, dtype=np.uint16)


@njit(cache=True)
def _render_indices(vram0: np.ndarray, vram1: np.ndarray,
                    tiles0: np.ndarray, tiles1: np.ndarray,
                    sprites: np.ndarray, sprite_words: np.ndarray,
                    scroll: np.ndarray, pixels: np.ndarray,
                    blocked: np.ndarray) -> None:
    """Скомпилированная композиция M72 без масштабирования кадра."""
    fg_l0 = (0xFFFF, 0x00FF, 0x0001, 0x0001)
    fg_l1 = (0x0001, 0xFF01, 0xFFFF, 0xFFFF)
    bg_pri = (0xFFFF, 0x00FF, 0x0001, 0x0001)
    bg_l0 = (0xFFFF, 0x00FF, 0xFFFF, 0x0001)
    bg_l1 = (0x0000, 0xFF00, 0x0000, 0xFFFE)
    for y in range(HEIGHT):
        fg_y = (y + 128 + scroll[y, 1]) & 511
        bg_y = (y + 128 + scroll[y, 3]) & 511
        for x in range(WIDTH):
            fg_x = (x + RAW_VISIBLE_X + scroll[y, 0]) & 511
            bg_x = (x + RAW_VISIBLE_X + scroll[y, 2]) & 511

            fg_index = (fg_y >> 3) * 64 + (fg_x >> 3)
            fg_code = int(vram0[fg_index * 2])
            fg_attr = int(vram0[fg_index * 2 + 1])
            fg_px = fg_x & 7
            fg_py = fg_y & 7
            if fg_code & 0x4000:
                fg_px = 7 - fg_px
            if fg_code & 0x8000:
                fg_py = 7 - fg_py
            fg_pen = int(tiles0[(fg_code & 0x3FFF) % len(tiles0), fg_py, fg_px])
            fg_group = (fg_attr >> 6) & 3
            fg_color = 256 + (fg_attr & 15) * 16 + fg_pen

            bg_index = (bg_y >> 3) * 64 + (bg_x >> 3)
            bg_code = int(vram1[bg_index * 2])
            bg_attr = int(vram1[bg_index * 2 + 1])
            bg_px = bg_x & 7
            bg_py = bg_y & 7
            if bg_code & 0x4000:
                bg_px = 7 - bg_px
            if bg_code & 0x8000:
                bg_py = 7 - bg_py
            bg_pen = int(tiles1[(bg_code & 0x3FFF) % len(tiles1), bg_py, bg_px])
            bg_group = (bg_attr >> 6) & 3
            bg_color = 256 + (bg_attr & 15) * 16 + bg_pen

            value = 0
            if not (bg_l1[bg_group] & (1 << bg_pen)):
                value = bg_color
            if not (fg_l1[fg_group] & (1 << fg_pen)):
                value = fg_color
            if not (bg_l0[bg_group] & (1 << bg_pen)):
                value = bg_color
            if not (fg_l0[fg_group] & (1 << fg_pen)):
                value = fg_color
            pixels[y, x] = value
            blocked[y, x] = bool(
                not (bg_pri[bg_group] & (1 << bg_pen)) or
                not (fg_l0[fg_group] & (1 << fg_pen)))

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
        attr = int(sprite_words[offset + 2])
        color = attr & 15
        width = 1 << ((attr >> 14) & 3)
        height = 1 << ((attr >> 12) & 3)
        flip_x = bool(attr & 0x0800)
        flip_y = bool(attr & 0x0400)
        x0 = -256 + (int(sprite_words[offset + 3]) & 0x3FF) - RAW_VISIBLE_X
        y0 = 384 - (int(sprite_words[offset]) & 0x1FF) - 16 * height
        for cell_x in range(width):
            for cell_y in range(height):
                cell_code = code
                cell_code += 8 * (width - 1 - cell_x if flip_x else cell_x)
                cell_code += height - 1 - cell_y if flip_y else cell_y
                cell_code %= len(sprites)
                for local_y in range(16):
                    dest_y = y0 + cell_y * 16 + local_y
                    # Последние 16 строк принадлежат HUD, а не игровым спрайтам.
                    if dest_y < 0 or dest_y >= PLAYFIELD_HEIGHT:
                        continue
                    source_y = 15 - local_y if flip_y else local_y
                    for local_x in range(16):
                        dest_x = x0 + cell_x * 16 + local_x
                        if dest_x < 0 or dest_x >= WIDTH or blocked[dest_y, dest_x]:
                            continue
                        source_x = 15 - local_x if flip_x else local_x
                        pen = int(sprites[cell_code, source_y, source_x])
                        if pen:
                            pixels[dest_y, dest_x] = color * 16 + pen


def _mask_draws(masks: np.ndarray, group: np.ndarray, pen: np.ndarray) -> np.ndarray:
    return (masks[group] & (np.uint16(1) << pen.astype(np.uint16))) == 0


class M72Renderer:
    """Преобразует VRAM, палитру и sprite RAM в нативный кадр 384×256."""

    def __init__(self) -> None:
        graphics = m72_scene.Graphics.load()
        self.tiles0 = np.frombuffer(graphics.tiles0, dtype=np.uint8).reshape(-1, 8, 8)
        self.tiles1 = np.frombuffer(graphics.tiles1, dtype=np.uint8).reshape(-1, 8, 8)
        self.sprites = np.frombuffer(graphics.sprites, dtype=np.uint8).reshape(-1, 16, 16)
        self.screen_x = np.arange(WIDTH, dtype=np.int32)[None, :]
        self.screen_y = np.arange(HEIGHT, dtype=np.int32)[:, None]
        self.pixels = np.zeros((HEIGHT, WIDTH), dtype=np.uint16)
        self.blocked = np.zeros((HEIGHT, WIDTH), dtype=np.bool_)

    @staticmethod
    def _palette(bank0: bytes, bank1: bytes) -> np.ndarray:
        colors = np.empty((512, 4), dtype=np.uint8)
        for bank_index, data in enumerate((bank0, bank1)):
            words = np.frombuffer(data, dtype="<u2")
            base = bank_index * 256
            for channel, offset in enumerate((0x000, 0x200, 0x400)):
                values = words[offset:offset + 256] & 0x1F
                colors[base:base + 256, channel] = (values << 3) | (values >> 2)
            colors[base:base + 256, 3] = 255
        return colors

    def _tile_layer(self, vram_words: np.ndarray, graphics: np.ndarray,
                    scroll_x: np.ndarray, scroll_y: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        source_x = (self.screen_x + RAW_VISIBLE_X + scroll_x[:, None]) & 511
        source_y = (self.screen_y + 128 + scroll_y[:, None]) & 511
        tile_index = (source_y >> 3) * 64 + (source_x >> 3)
        code = vram_words[tile_index * 2]
        attr = vram_words[tile_index * 2 + 1]
        pixel_x = source_x & 7
        pixel_y = source_y & 7
        pixel_x = np.where((code & 0x4000) != 0, 7 - pixel_x, pixel_x)
        pixel_y = np.where((code & 0x8000) != 0, 7 - pixel_y, pixel_y)
        pen = graphics[(code & 0x3FFF) % len(graphics), pixel_y, pixel_x]
        return pen, (attr >> 6) & 3, 256 + (attr & 0x0F) * 16 + pen

    def render(self, frame: FrameState) -> Image.Image:
        if frame.video_off:
            return Image.new("RGB", (WIDTH, HEIGHT), "black")
        vram0 = np.frombuffer(frame.vram0, dtype="<u2")
        vram1 = np.frombuffer(frame.vram1, dtype="<u2")
        scroll = np.asarray(frame.row_scroll, dtype=np.int32)
        sprite_words = np.frombuffer(frame.spriteram, dtype="<u2")
        _render_indices(vram0, vram1, self.tiles0, self.tiles1, self.sprites,
                        sprite_words, scroll, self.pixels, self.blocked)
        rgba = self._palette(frame.palette0, frame.palette1)[self.pixels]
        return Image.fromarray(rgba, "RGBA").convert("RGB")

    def _draw_sprites(self, pixels: np.ndarray, blocked: np.ndarray, data: bytes) -> None:
        words = np.frombuffer(data, dtype="<u2")
        offsets: list[int] = []
        offset = 0
        while offset < len(words):
            offsets.append(offset)
            width = 1 << ((int(words[offset + 2]) >> 14) & 3)
            offset += width * 4
        for offset in reversed(offsets):
            code = int(words[offset + 1])
            attr = int(words[offset + 2])
            color = attr & 0x0F
            width = 1 << ((attr >> 14) & 3)
            height = 1 << ((attr >> 12) & 3)
            flip_x = bool(attr & 0x0800)
            flip_y = bool(attr & 0x0400)
            x0 = -256 + (int(words[offset + 3]) & 0x3FF) - RAW_VISIBLE_X
            y0 = 384 - (int(words[offset]) & 0x1FF) - 16 * height
            for cell_x in range(width):
                for cell_y in range(height):
                    cell_code = code
                    cell_code += 8 * (width - 1 - cell_x if flip_x else cell_x)
                    cell_code += height - 1 - cell_y if flip_y else cell_y
                    cell = self.sprites[cell_code % len(self.sprites)]
                    if flip_x:
                        cell = cell[:, ::-1]
                    if flip_y:
                        cell = cell[::-1, :]
                    dx0, dy0 = x0 + cell_x * 16, y0 + cell_y * 16
                    dx1, dy1 = max(0, dx0), max(0, dy0)
                    dx2, dy2 = min(WIDTH, dx0 + 16), min(HEIGHT, dy0 + 16)
                    if dx1 >= dx2 or dy1 >= dy2:
                        continue
                    source = cell[dy1 - dy0:dy2 - dy0, dx1 - dx0:dx2 - dx0]
                    visible = (source != 0) & ~blocked[dy1:dy2, dx1:dx2]
                    target = pixels[dy1:dy2, dx1:dx2]
                    target[visible] = color * 16 + source[visible]
