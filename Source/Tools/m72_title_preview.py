#!/usr/bin/env python3
"""Render the FT812 title command stream without running Z80 or Unreal.

This is deliberately a model of the port, not another MAME renderer: it reads
the exact binary font and TITLE_EVENTS.bin consumed by the assembly and draws
only bitmap CELL commands at the coordinates carried by each packet.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas"
DEFAULT_OUT = ROOT / "Build" / "TitlePreview"

PACKET_SIZE = 423
FRAME_COUNT = 459
BASE_MAME_FRAME = 331
LOGO_COUNT = 7
LOGO_W, LOGO_H = 107, 120
TEXT_W, TEXT_H = 14, 15
TEXT_COUNT = 96
TEXT_STYLES = 3
LOGICAL_SIZE = (640, 480)
OUTPUT_SIZE = (1024, 768)


def unpack_argb4444(data: bytes, width: int, height: int) -> Image.Image:
    if len(data) != width * height * 2:
        raise ValueError(f"ARGB4444 cell size {len(data)}, expected {width*height*2}")
    image = Image.new("RGBA", (width, height))
    pixels = []
    for value, in struct.iter_unpack("<H", data):
        a = ((value >> 12) & 15) * 17
        r = ((value >> 8) & 15) * 17
        g = ((value >> 4) & 15) * 17
        b = (value & 15) * 17
        pixels.append((r, g, b, a))
    image.putdata(pixels)
    return image


def load_cells() -> tuple[list[Image.Image], list[list[Image.Image]]]:
    blob = (ATLAS / "TITLE_FONT_ARGB4444.bin").read_bytes()
    logo_bytes = LOGO_W * LOGO_H * 2
    text_bytes = TEXT_W * TEXT_H * 2
    expected = LOGO_COUNT * logo_bytes + TEXT_STYLES * TEXT_COUNT * text_bytes
    if len(blob) != expected:
        raise ValueError(f"font blob {len(blob)}, expected {expected}")
    offset = 0
    logos = []
    for _ in range(LOGO_COUNT):
        logos.append(unpack_argb4444(blob[offset:offset + logo_bytes], LOGO_W, LOGO_H))
        offset += logo_bytes
    text = []
    for _ in range(TEXT_STYLES):
        style = []
        for _ in range(TEXT_COUNT):
            style.append(unpack_argb4444(blob[offset:offset + text_bytes], TEXT_W, TEXT_H))
            offset += text_bytes
        text.append(style)
    return logos, text


def native_x(value: int) -> int:
    return round(value * 640 / 384)


def native_y(value: int) -> int:
    return round(value * 480 / 256)


def render_packet(packet: bytes, logos: list[Image.Image],
                  text: list[list[Image.Image]]) -> Image.Image:
    if len(packet) != PACKET_SIZE:
        raise ValueError(len(packet))
    frame = Image.new("RGBA", LOGICAL_SIZE, (0, 0, 0, 255))
    offset = 0
    for cell in range(LOGO_COUNT):
        visible, x, y = struct.unpack_from("<Bhh", packet, offset)
        offset += 5
        if visible and x >= 0 and y >= 0:
            frame.alpha_composite(logos[cell], (native_x(x), native_y(y)))
    count = packet[offset]
    offset += 1
    if count > 96:
        raise ValueError(f"bad text count {count}")
    for index in range(count):
        cell, style, column, row = struct.unpack_from("BBBB", packet, offset + index * 4)
        if cell >= TEXT_COUNT or style >= TEXT_STYLES:
            raise ValueError(f"bad text record {index}: {cell}, {style}")
        frame.alpha_composite(text[style][cell],
                              (round(column * 640 / 48), row * TEXT_H))
    return frame.resize(OUTPUT_SIZE, Image.Resampling.NEAREST)


def reference_frame(capture: Path, index: int) -> Image.Image:
    mame_frame = BASE_MAME_FRAME + index
    path = capture / f"frame_{mame_frame:06d}_native.png"
    return Image.open(path).convert("RGBA").resize(OUTPUT_SIZE, Image.Resampling.NEAREST)


def comparison_frame(model: Image.Image, reference: Image.Image, index: int,
                     *, half_size: bool) -> Image.Image:
    size = (512, 384) if half_size else OUTPUT_SIZE
    left = reference.resize(size, Image.Resampling.NEAREST)
    right = model.resize(size, Image.Resampling.NEAREST)
    result = Image.new("RGBA", (size[0] * 2, size[1] + 24), (24, 24, 24, 255))
    result.alpha_composite(left, (0, 24))
    result.alpha_composite(right, (size[0], 24))
    draw = ImageDraw.Draw(result)
    draw.text((8, 5), f"MAME frame {BASE_MAME_FRAME + index}", fill="white")
    draw.text((size[0] + 8, 5), f"Python FT812 model, packet {index}", fill="white")
    return result


def make_contact_sheet(images: list[tuple[int, Image.Image]], path: Path,
                       capture: Path | None = None) -> None:
    thumb_size = (512, 384)
    columns = 1 if capture else 2
    item_width = thumb_size[0] * (2 if capture else 1)
    sheet = Image.new("RGB", (item_width * columns, (thumb_size[1] + 28) * ((len(images) + columns - 1) // columns)), "#202020")
    draw = ImageDraw.Draw(sheet)
    for slot, (index, image) in enumerate(images):
        x = (slot % columns) * item_width
        y = (slot // columns) * (thumb_size[1] + 28)
        if capture:
            reference = reference_frame(capture, index).resize(thumb_size, Image.Resampling.NEAREST)
            sheet.paste(reference.convert("RGB"), (x, y))
            sheet.paste(image.resize(thumb_size, Image.Resampling.NEAREST).convert("RGB"),
                        (x + thumb_size[0], y))
        else:
            sheet.paste(image.resize(thumb_size, Image.Resampling.NEAREST).convert("RGB"), (x, y))
        draw.text((x + 8, y + thumb_size[1] + 6),
                  f"packet {index}, MAME {BASE_MAME_FRAME + index}", fill="white")
    sheet.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", default="0,15,30,60,90,119,149,179,209,239,269,299,329,359,389,419,449,458")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--gif", action="store_true", help="also write a 55 fps animated preview")
    parser.add_argument("--compare", type=Path,
                        help="MAME native capture; produces reference/model pairs")
    args = parser.parse_args()

    stream = (ATLAS / "TITLE_EVENTS.bin").read_bytes()
    if len(stream) != PACKET_SIZE * FRAME_COUNT:
        raise ValueError(f"event stream {len(stream)}, expected {PACKET_SIZE*FRAME_COUNT}")
    indices = [int(value) for value in args.frames.split(",")]
    if any(not 0 <= value < FRAME_COUNT for value in indices):
        raise ValueError("preview frame outside stream")
    args.out.mkdir(parents=True, exist_ok=True)
    logos, text = load_cells()
    selected = []
    for index in indices:
        packet = stream[index * PACKET_SIZE:(index + 1) * PACKET_SIZE]
        image = render_packet(packet, logos, text)
        image.save(args.out / f"title_{index:03d}_mame_{BASE_MAME_FRAME + index:03d}.png")
        selected.append((index, image))
    make_contact_sheet(selected, args.out / "contact_sheet.png", args.compare)
    if args.gif:
        animation = []
        for index in range(FRAME_COUNT):
            packet = stream[index * PACKET_SIZE:(index + 1) * PACKET_SIZE]
            model = render_packet(packet, logos, text)
            if args.compare:
                model = comparison_frame(model, reference_frame(args.compare, index),
                                         index, half_size=True)
            else:
                model = model.resize((512, 384), Image.Resampling.NEAREST)
            animation.append(model)
        gif_name = "title_compare.gif" if args.compare else "title_preview.gif"
        animation[0].save(args.out / gif_name, save_all=True,
                          append_images=animation[1:], duration=18, loop=0,
                          disposal=2, optimize=False)
    print(f"rendered {len(selected)} key frames to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
