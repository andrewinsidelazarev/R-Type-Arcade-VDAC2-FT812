#!/usr/bin/env python3
"""Live 55 Hz player for the coordinate/cell FT812 title model."""
from __future__ import annotations

import argparse
import time
import tkinter as tk
from pathlib import Path

from PIL import ImageDraw, ImageTk

import m72_title_preview as preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path,
                        default=preview.ROOT / "Build" / "Arcade" / "MAME" / "title_all_native")
    parser.add_argument("--compare", action="store_true",
                        help="show MAME reference next to the Python model")
    args = parser.parse_args()

    stream = (preview.ATLAS / "TITLE_EVENTS.bin").read_bytes()
    if len(stream) != preview.PACKET_SIZE * preview.FRAME_COUNT:
        raise ValueError("TITLE_EVENTS.bin has the wrong size")
    logos, text = preview.load_cells()

    root = tk.Tk()
    root.title("R-Type — Python FT812 cell/coordinate model")
    root.configure(background="black")
    label = tk.Label(root, borderwidth=0, background="black")
    label.pack()

    state = {"index": 0, "deadline": time.perf_counter()}

    def tick() -> None:
        index = state["index"]
        packet = stream[index * preview.PACKET_SIZE:(index + 1) * preview.PACKET_SIZE]
        model = preview.render_packet(packet, logos, text)
        if args.compare:
            reference = preview.reference_frame(args.capture, index)
            image = preview.comparison_frame(model, reference, index, half_size=True)
        else:
            image = model
            draw = ImageDraw.Draw(image)
            draw.text((8, 8), f"Python FT812 model — 55 Hz — MAME frame {preview.BASE_MAME_FRAME + index}",
                      fill="#00ffff")
        photo = ImageTk.PhotoImage(image)
        label.configure(image=photo)
        label.image = photo

        state["index"] = (index + 1) % preview.FRAME_COUNT
        state["deadline"] += 1.0 / 55.0
        delay = max(1, round((state["deadline"] - time.perf_counter()) * 1000))
        root.after(delay, tick)

    root.after(0, tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
