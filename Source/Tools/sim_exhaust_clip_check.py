#!/usr/bin/env python3
"""Проверить постепенную обрезку выхлопа R-9 у логического левого края.

Для каждой граничной позиции запускается собранный renderer и проверяются
смещение источника FT812, ширина и неотрицательная вершина. Это host-проверка
display list, а не доказательство на физическом VDAC2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from sim_frame_png import DLRenderer  # noqa: E402

PLAYER_X = 0x4203
POSITIONS = (50, 40, 20, 0)


def signed15(value: int) -> int:
    return value - 0x8000 if value & 0x4000 else value


def bitmap_draws(data: bytes) -> list[dict[str, int]]:
    source = 0
    width_hi = 0
    width = 0
    primitive = -1
    draws: list[dict[str, int]] = []
    for offset in range(0, len(data), 4):
        word = int.from_bytes(data[offset:offset + 4], "little")
        op = word >> 24
        if op == 0x01:
            source = word & 0xFFFFF
        elif op == 0x29:
            width_hi = (word >> 2) & 3
        elif op == 0x08:
            width = ((word >> 9) & 0x1FF) | (width_hi << 9)
        elif op == 0x1F:
            primitive = word & 0x0F
        elif op == 0x21:
            primitive = -1
        elif op & 0xC0 == 0x40 and primitive == 1:
            draws.append({
                "source": source,
                "width": width,
                "x_units": signed15((word >> 15) & 0x7FFF),
                "y_units": signed15(word & 0x7FFF),
            })
    return draws


def main() -> int:
    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites" /
        "frame_000900_sprite_assets.json"
    ).read_text(encoding="utf-8"))
    dynamic = manifest["dynamic_instances"]
    exhaust = manifest["assets"][dynamic["exhaust"]["asset_index"]]
    body = manifest["assets"][dynamic["r9"]["asset_index"]]
    left_limit = (dynamic["r9"]["logical_x"]
                  - dynamic["exhaust"]["logical_x"])

    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)
    machine.set_byte(sym["GameMode"], 1)

    for player_x in POSITIONS:
        machine.set_byte(PLAYER_X, 0)
        machine.set_word(PLAYER_X + 1, player_x)
        machine.ft.cmd_read_ptr = 0
        machine.ft.cmd_write_ptr = 0
        machine.call(sym["Render_Frame"], max_steps=2_000_000)
        assert machine.ft.cmd_write_ptr > 0
        data = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
        draws = bitmap_draws(data)
        assert len(draws) >= 2

        crop = max(0, left_limit - player_x)
        expected_source = exhaust["offset"] + crop * 2
        tail = [draw for draw in draws if draw["source"] == expected_source][-1]
        ship = [draw for draw in draws if draw["source"] == body["offset"]][-1]
        expected_width = ((exhaust["width"] - crop) * 8 + 4) // 5
        expected_x = 0 if crop else ((player_x - left_limit) * 64 + 2) // 5
        assert tail["source"] == expected_source
        assert tail["width"] == expected_width
        assert tail["x_units"] == expected_x
        assert ship["source"] == body["offset"]

        renderer = DLRenderer(bytes(machine.ft.ram_g))
        renderer.run(data)
        output = ROOT / "Build" / f"exhaust_clip_x{player_x:03d}.png"
        renderer.img.save(output)
        print(
            f"X={player_x:2d}: crop={crop:2d}, source=${tail['source']:05X}, "
            f"width={tail['width']:2d}, vertex={tail['x_units']:4d} -> {output.name}")

    print("Обрезка выхлопа: OK, у левого края нет отрицательной вершины")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
