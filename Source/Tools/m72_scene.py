#!/usr/bin/env python3
"""Reconstruct an M72 R-Type frame from captured VRAM/palette/sprite RAM.

The implementation follows MAME 0.288 m72_v.cpp.  Its purpose is asset
separation, not emulation: tile layers can be converted offline without baking
dynamic sprites into the stored FT812 background.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72


ROOT = Path(__file__).resolve().parents[2]
CONVERTED = ROOT / "Assets" / "Converted" / "Arcade"
VISIBLE_WIDTH = 384
VISIBLE_HEIGHT = 256
RAW_VISIBLE_X = 64
TILEMAP_SIZE = 512
TILE_SCROLL_DY = -128

# set_transmask(group, layer0/front mask, layer1/back mask), MAME m72_v.cpp.
FG_LAYER0_MASK = (0xFFFF, 0x00FF, 0x0001, 0x0001)
FG_LAYER1_MASK = (0x0001, 0xFF01, 0xFFFF, 0xFFFF)
BG_PRIORITY_LAYER0_MASK = (0xFFFF, 0x00FF, 0x0001, 0x0001)
BG_LAYER0_MASK = (0xFFFF, 0x00FF, 0xFFFF, 0x0001)
BG_LAYER1_MASK = (0x0000, 0xFF00, 0x0000, 0xFFFE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_u16(data: bytes, word_index: int) -> int:
    offset = word_index * 2
    return data[offset] | (data[offset + 1] << 8)


def pal5bit(value: int) -> int:
    value &= 0x1F
    return (value << 3) | (value >> 2)


def palette_from_ram(palette0: bytes, palette1: bytes) -> list[tuple[int, int, int, int]]:
    if len(palette0) != 0xC00 or len(palette1) != 0xC00:
        raise ValueError("M72 palette RAM banks must each be 0xC00 bytes")
    colors: list[tuple[int, int, int, int]] = []
    for bank in (palette0, palette1):
        for color in range(256):
            red = read_u16(bank, color + 0x000)
            green = read_u16(bank, color + 0x200)
            blue = read_u16(bank, color + 0x400)
            colors.append((pal5bit(red), pal5bit(green), pal5bit(blue), 255))
    return colors


def palette_from_argb_file(path: Path) -> list[tuple[int, int, int, int]]:
    data = path.read_bytes()
    if len(data) != 512 * 4:
        raise ValueError(f"MAME palette must be 2048 bytes: {path}")
    result = []
    for value, in struct.iter_unpack("<I", data):
        result.append(((value >> 16) & 0xFF, (value >> 8) & 0xFF,
                       value & 0xFF, (value >> 24) & 0xFF))
    return result


def screen_indices(path: Path) -> list[int]:
    data = path.read_bytes()
    expected = VISIBLE_WIDTH * VISIBLE_HEIGHT * 4
    if len(data) != expected:
        raise ValueError(f"screen pixels are {len(data)} bytes, expected {expected}")
    return [value[0] for value in struct.iter_unpack("<I", data)]


@dataclass(frozen=True)
class ScrollState:
    fg_x: int
    fg_y: int
    bg_x: int
    bg_y: int


@dataclass
class Graphics:
    tiles0: bytes
    tiles1: bytes
    sprites: bytes

    @classmethod
    def load(cls) -> "Graphics":
        paths = {
            "tiles0": CONVERTED / "RTYPE_TILES0_INDEX4.bin",
            "tiles1": CONVERTED / "RTYPE_TILES1_INDEX4.bin",
            "sprites": CONVERTED / "RTYPE_SPRITES_INDEX4.bin",
        }
        if not all(path.is_file() for path in paths.values()):
            m72.decode_all()
        return cls(**{
            name: m72.unpack_nibbles(path.read_bytes())
            for name, path in paths.items()
        })


@dataclass
class Capture:
    root: Path
    vram0: bytes
    vram1: bytes
    spriteram: bytes
    palette0: bytes
    palette1: bytes
    screen: list[int]
    palette: list[tuple[int, int, int, int]]

    @classmethod
    def load(cls, root: Path, frame: int, state_frame: int | None = None) -> "Capture":
        prefix = f"frame_{frame:06d}"
        state_prefix = f"frame_{state_frame if state_frame is not None else frame:06d}"

        def frame_or_final(frame_name: str, final_name: str) -> Path:
            candidate = root / f"{state_prefix}_{frame_name}"
            return candidate if candidate.is_file() else root / final_name

        return cls(
            root=root,
            vram0=frame_or_final("vram0.bin", "vram0.bin").read_bytes(),
            vram1=frame_or_final("vram1.bin", "vram1.bin").read_bytes(),
            spriteram=frame_or_final("spriteram.bin", "spriteram.bin").read_bytes(),
            palette0=frame_or_final("palette0.bin", "palette0.bin").read_bytes(),
            palette1=frame_or_final("palette1.bin", "palette1.bin").read_bytes(),
            screen=screen_indices(root / f"{prefix}_pixels_u32le.bin"),
            palette=palette_from_argb_file(
                root / f"{prefix}_palette_argb8888_le.bin"),
        )


@dataclass(frozen=True)
class TilePixel:
    palette_index: int
    pen: int
    group: int


def tile_pixel(vram: bytes, graphics: bytes, visible_x: int, visible_y: int,
               scroll_x: int, scroll_y: int) -> TilePixel:
    source_x = (visible_x + RAW_VISIBLE_X + scroll_x) & (TILEMAP_SIZE - 1)
    # effective_colscroll = dy - scrolly, so source = screen - effective.
    source_y = (visible_y - TILE_SCROLL_DY + scroll_y) & (TILEMAP_SIZE - 1)
    tile_index = (source_y >> 3) * 64 + (source_x >> 3)
    code = read_u16(vram, tile_index * 2)
    attr = read_u16(vram, tile_index * 2 + 1)
    pixel_x = source_x & 7
    pixel_y = source_y & 7
    if code & 0x4000:
        pixel_x = 7 - pixel_x
    if code & 0x8000:
        pixel_y = 7 - pixel_y
    code &= 0x3FFF
    cell_count = len(graphics) // 64
    code %= cell_count
    pen = graphics[code * 64 + pixel_y * 8 + pixel_x]
    return TilePixel(256 + (attr & 0x0F) * 16 + pen,
                     pen, (attr >> 6) & 3)


def mask_draws(mask: int, pen: int) -> bool:
    return not bool(mask & (1 << pen))


def render_tiles(capture: Capture, graphics: Graphics,
                 row_states: Sequence[ScrollState]) -> tuple[list[int], list[bool]]:
    if len(row_states) != VISIBLE_HEIGHT:
        raise ValueError("one scroll state is required per visible row")
    pixels = [0] * (VISIBLE_WIDTH * VISIBLE_HEIGHT)
    sprite_blocked = [False] * len(pixels)
    for y, state in enumerate(row_states):
        row = y * VISIBLE_WIDTH
        for x in range(VISIBLE_WIDTH):
            bg = tile_pixel(capture.vram1, graphics.tiles1, x, y,
                            state.bg_x, state.bg_y)
            fg = tile_pixel(capture.vram0, graphics.tiles0, x, y,
                            state.fg_x, state.fg_y)

            # Final tile/tile order from screen_update(): background back,
            # foreground back, background front, foreground front.
            value = 0
            if mask_draws(BG_LAYER1_MASK[bg.group], bg.pen):
                value = bg.palette_index
            if mask_draws(FG_LAYER1_MASK[fg.group], fg.pen):
                value = fg.palette_index
            if mask_draws(BG_LAYER0_MASK[bg.group], bg.pen):
                value = bg.palette_index
            if mask_draws(FG_LAYER0_MASK[fg.group], fg.pen):
                value = fg.palette_index
            pixels[row + x] = value

            # The preliminary layer-0 pass sets priority bit 1.  Sprites use
            # primask ~1 and therefore stay behind these tile pixels.
            sprite_blocked[row + x] = (
                mask_draws(BG_PRIORITY_LAYER0_MASK[bg.group], bg.pen) or
                mask_draws(FG_LAYER0_MASK[fg.group], fg.pen)
            )
    return pixels, sprite_blocked


def sprite_offsets(spriteram: bytes) -> list[int]:
    if len(spriteram) != 0x400:
        raise ValueError("M72 sprite RAM must be 0x400 bytes")
    words = len(spriteram) // 2
    result = []
    offset = 0
    while offset < words:
        result.append(offset)
        width = 1 << ((read_u16(spriteram, offset + 2) >> 14) & 3)
        offset += width * 4
    return result


@dataclass(frozen=True)
class SpriteObject:
    """One composite M72 sprite-RAM object in raw-screen coordinates."""

    offset: int
    code: int
    attr: int
    color: int
    sx: int
    sy: int
    flip_x: bool
    flip_y: bool
    width: int
    height: int

    @property
    def visible_x(self) -> int:
        return self.sx - RAW_VISIBLE_X

    @property
    def pixel_width(self) -> int:
        return self.width * 16

    @property
    def pixel_height(self) -> int:
        return self.height * 16


def sprite_objects(spriteram: bytes) -> list[SpriteObject]:
    result = []
    for offset in sprite_offsets(spriteram):
        code = read_u16(spriteram, offset + 1)
        attr = read_u16(spriteram, offset + 2)
        width = 1 << ((attr >> 14) & 3)
        height = 1 << ((attr >> 12) & 3)
        sx = -256 + (read_u16(spriteram, offset + 3) & 0x3FF)
        sy = 384 - (read_u16(spriteram, offset + 0) & 0x1FF) - 16 * height
        result.append(SpriteObject(
            offset=offset,
            code=code,
            attr=attr,
            color=attr & 0x0F,
            sx=sx,
            sy=sy,
            flip_x=bool(attr & 0x0800),
            flip_y=bool(attr & 0x0400),
            width=width,
            height=height,
        ))
    return result


def sprite_object_indices(sprite: SpriteObject, graphics: Graphics) -> list[int]:
    """Render an object into its own hardware-sized transparent index buffer."""
    indices = [-1] * (sprite.pixel_width * sprite.pixel_height)
    cell_count = len(graphics.sprites) // 256
    for cell_x in range(sprite.width):
        for cell_y in range(sprite.height):
            cell_code = sprite.code
            cell_code += 8 * (
                sprite.width - 1 - cell_x if sprite.flip_x else cell_x)
            cell_code += (
                sprite.height - 1 - cell_y if sprite.flip_y else cell_y)
            cell_code %= cell_count
            base = cell_code * 256
            for local_y in range(16):
                source_y = 15 - local_y if sprite.flip_y else local_y
                dest_y = cell_y * 16 + local_y
                for local_x in range(16):
                    source_x = 15 - local_x if sprite.flip_x else local_x
                    pen = graphics.sprites[base + source_y * 16 + source_x]
                    if pen:
                        dest_x = cell_x * 16 + local_x
                        indices[dest_y * sprite.pixel_width + dest_x] = (
                            sprite.color * 16 + pen)
    return indices


def sprite_object_image(sprite: SpriteObject, graphics: Graphics,
                        palette: Sequence[tuple[int, int, int, int]]) -> Image.Image:
    rgba = bytearray(sprite.pixel_width * sprite.pixel_height * 4)
    for index, palette_index in enumerate(sprite_object_indices(sprite, graphics)):
        color = (0, 0, 0, 0) if palette_index < 0 else palette[palette_index]
        rgba[index * 4:index * 4 + 4] = bytes(color)
    return Image.frombytes(
        "RGBA", (sprite.pixel_width, sprite.pixel_height), bytes(rgba))


def draw_sprites(tile_pixels: Sequence[int], blocked: Sequence[bool],
                  spriteram: bytes, graphics: Graphics) -> tuple[list[int], list[int]]:
    pixels = list(tile_pixels)
    sprite_only = [-1] * len(pixels)
    cell_count = len(graphics.sprites) // 256
    for sprite in reversed(sprite_objects(spriteram)):

        for cell_x in range(sprite.width):
            for cell_y in range(sprite.height):
                cell_code = sprite.code
                cell_code += 8 * (
                    sprite.width - 1 - cell_x if sprite.flip_x else cell_x)
                cell_code += (
                    sprite.height - 1 - cell_y if sprite.flip_y else cell_y)
                cell_code %= cell_count
                base = cell_code * 256
                dest_x0 = sprite.visible_x + 16 * cell_x
                dest_y0 = sprite.sy + 16 * cell_y
                for local_y in range(16):
                    dest_y = dest_y0 + local_y
                    if not 0 <= dest_y < VISIBLE_HEIGHT:
                        continue
                    source_y = 15 - local_y if sprite.flip_y else local_y
                    for local_x in range(16):
                        dest_x = dest_x0 + local_x
                        if not 0 <= dest_x < VISIBLE_WIDTH:
                            continue
                        source_x = 15 - local_x if sprite.flip_x else local_x
                        pen = graphics.sprites[base + source_y * 16 + source_x]
                        if pen == 0:
                            continue
                        index = dest_y * VISIBLE_WIDTH + dest_x
                        palette_index = sprite.color * 16 + pen
                        sprite_only[index] = palette_index
                        if not blocked[index]:
                            pixels[index] = palette_index
    return pixels, sprite_only


def indices_to_image(indices: Sequence[int],
                     palette: Sequence[tuple[int, int, int, int]],
                     *, transparent_negative: bool = False) -> Image.Image:
    rgba = bytearray(len(indices) * 4)
    for index, palette_index in enumerate(indices):
        if palette_index < 0 and transparent_negative:
            color = (0, 0, 0, 0)
        else:
            color = palette[palette_index]
        rgba[index * 4:index * 4 + 4] = bytes(color)
    return Image.frombytes("RGBA", (VISIBLE_WIDTH, VISIBLE_HEIGHT), bytes(rgba))


def argb_to_rgba(value: int) -> tuple[int, int, int, int]:
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF,
            value & 0xFF, (value >> 24) & 0xFF)


def comparison(expected: Sequence[int], actual: Sequence[int],
               palette: Sequence[tuple[int, int, int, int]]) -> dict[str, object]:
    if len(expected) != len(actual):
        raise ValueError("comparison buffers differ in size")
    matches = sum(argb_to_rgba(left) == palette[right]
                  for left, right in zip(expected, actual))
    return {
        "pixels": len(expected),
        "exact_color_matches": matches,
        "exact_color_percent": matches * 100.0 / len(expected),
    }


def choose_rows(capture: Capture, graphics: Graphics,
                candidates: Sequence[ScrollState]) -> tuple[list[ScrollState], list[dict[str, int]]]:
    rendered = []
    for state in candidates:
        pixels, _ = render_tiles(capture, graphics, [state] * VISIBLE_HEIGHT)
        rendered.append(pixels)
    chosen: list[ScrollState] = []
    scores: list[dict[str, int]] = []
    for y in range(VISIBLE_HEIGHT):
        start = y * VISIBLE_WIDTH
        stop = start + VISIBLE_WIDTH
        row_expected = capture.screen[start:stop]
        row_scores = []
        for pixels in rendered:
            score = sum(argb_to_rgba(expected) == capture.palette[actual]
                        for expected, actual in zip(row_expected, pixels[start:stop])
                        )
            row_scores.append(score)
        winner = max(range(len(candidates)), key=row_scores.__getitem__)
        chosen.append(candidates[winner])
        scores.append({str(index): score for index, score in enumerate(row_scores)})
    return chosen, scores


def parse_int(text: str) -> int:
    return int(text, 0)


def render_command(args: argparse.Namespace) -> dict[str, object]:
    capture = Capture.load(args.capture, args.frame, args.state_frame)
    graphics = Graphics.load()
    decoded_palette = palette_from_ram(capture.palette0, capture.palette1)
    palette_equal = decoded_palette == capture.palette

    gameplay = ScrollState(args.fg_x, args.fg_y, args.bg_x, args.bg_y)
    hud = ScrollState(args.hud_fg_x, args.hud_fg_y, args.bg_x, args.bg_y)
    candidates = [gameplay, hud]
    if args.auto_rows:
        row_states, row_scores = choose_rows(capture, graphics, candidates)
    else:
        row_states = [gameplay if y < args.split else hud
                      for y in range(VISIBLE_HEIGHT)]
        row_scores = []

    tile_pixels, blocked = render_tiles(capture, graphics, row_states)
    final_pixels, sprite_only = draw_sprites(
        tile_pixels, blocked, capture.spriteram, graphics)
    metrics = comparison(capture.screen, final_pixels, capture.palette)
    tile_metrics = comparison(capture.screen, tile_pixels, capture.palette)
    if getattr(args, "require_exact", False) and (
            metrics["exact_color_matches"] != metrics["pixels"]):
        raise ValueError(
            "M72 reconstruction is not pixel-exact: "
            f"{metrics['exact_color_matches']}/{metrics['pixels']}")

    args.output.mkdir(parents=True, exist_ok=True)
    prefix = args.output / f"frame_{args.frame:06d}"
    outputs = {
        "tiles_native": prefix.with_name(prefix.name + "_tiles_native.png"),
        "sprites_native": prefix.with_name(prefix.name + "_sprites_native.png"),
        "reconstructed_native": prefix.with_name(
            prefix.name + "_reconstructed_native.png"),
    }
    indices_to_image(tile_pixels, capture.palette).save(outputs["tiles_native"])
    indices_to_image(sprite_only, capture.palette,
                     transparent_negative=True).save(outputs["sprites_native"])
    indices_to_image(final_pixels, capture.palette).save(
        outputs["reconstructed_native"])

    manifest = {
        "format": 1,
        "mame_source": {
            "tag": m72.MAME_TAG,
            "commit": m72.MAME_COMMIT,
            "video": "src/mame/irem/m72_v.cpp",
        },
        "capture": str(args.capture.resolve()),
        "frame": args.frame,
        "state_frame": args.state_frame if args.state_frame is not None else args.frame,
        "palette_ram_matches_mame_palette": palette_equal,
        "scroll_candidates": [state.__dict__ for state in candidates],
        "auto_rows": args.auto_rows,
        "selected_rows": [0 if state == gameplay else 1 for state in row_states],
        "row_scores": row_scores,
        "metrics_with_sprites": metrics,
        "metrics_tiles_only": tile_metrics,
        "outputs": {
            name: {"path": str(path.resolve()), "sha256": sha256(path)}
            for name, path in outputs.items()
        },
    }
    manifest_path = prefix.with_name(prefix.name + "_scene.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"palette RAM == MAME palette: {palette_equal}")
    print(f"tile exact color: {tile_metrics['exact_color_percent']:.3f}%")
    print(f"with sprites exact color: {metrics['exact_color_percent']:.3f}%")
    print(f"manifest: {manifest_path}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--state-frame", type=int,
                        help="per-frame VRAM/sprite/palette state to pair with screenshot")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "Build" / "Arcade" / "Scenes")
    parser.add_argument("--fg-x", type=parse_int, default=0x176)
    parser.add_argument("--fg-y", type=parse_int, default=0)
    parser.add_argument("--bg-x", type=parse_int, default=0x0ED)
    parser.add_argument("--bg-y", type=parse_int, default=0)
    parser.add_argument("--hud-fg-x", type=parse_int, default=0)
    parser.add_argument("--hud-fg-y", type=parse_int, default=0x90)
    parser.add_argument("--split", type=int, default=240)
    parser.add_argument("--auto-rows", action="store_true")
    parser.add_argument("--require-exact", action="store_true",
                        help="fail unless reconstructed frame matches every pixel")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        render_command(args)
    except (FileNotFoundError, OSError, ValueError, IndexError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
