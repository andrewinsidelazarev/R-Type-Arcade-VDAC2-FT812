#!/usr/bin/env python3
"""Преобразовать записи регистров скролла M72 в покадровые данные уровня."""
from __future__ import annotations

import csv
import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Build" / "Arcade" / "MAME" / "stage1_full_trace" / "scroll_writes.csv"
OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1"
BASE_FRAME = 898
LAST_FRAME = 18000


def main() -> int:
    states: dict[int, tuple[int, int]] = {}
    fg_x = 0
    bg_x = 0
    with SOURCE.open(newline="", encoding="ascii") as source:
        rows = list(csv.DictReader(source))
    by_frame: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_frame.setdefault(int(row["frame"]), []).append(row)
    for frame in range(0, LAST_FRAME + 1):
        foreground_written = False
        for row in by_frame.get(frame, ()):
            address = int(row["address"], 16)
            value = int(row["data"], 16) & 0xFFFF
            # M72 пишет $82 дважды: игровой скролл перед выводом поля и
            # ноль из raster IRQ перед HUD. Для геометрии уровня нужен
            # первый результат ROM $0443, а не поздний сброс интерфейса.
            if address == 0x82 and not foreground_written:
                fg_x = value
                foreground_written = True
            elif address == 0x86:
                bg_x = value
        if frame >= BASE_FRAME:
            states[frame] = (fg_x, bg_x)

    blob = b"".join(struct.pack("<HH", *states[frame])
                    for frame in range(BASE_FRAME, LAST_FRAME + 1))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "STAGE1_SCROLL_X.bin"
    path.write_bytes(blob)
    manifest = {
        "format": 1,
        "source": str(SOURCE.relative_to(ROOT)),
        "base_frame": BASE_FRAME,
        "last_frame": LAST_FRAME,
        "frames": LAST_FRAME - BASE_FRAME + 1,
        "record": "foreground_x_u16,background_x_u16",
        "size": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    (OUT / "stage1_scroll.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"скролл уровня: {manifest['frames']} кадров, {len(blob)} байт")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
