#!/usr/bin/env python3
"""Проверка нативного fixed-выстрела R-9 в Z80 и display list FT812.

Это host-симуляция, не Unreal и не реальное железо. Проверка исполняет настоящий
код SPG, создаёт снаряд фронтом FIRE и сверяет его M72-состояние, подлинный
адрес ARGB4444, размер и координаты в командах FT812.
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

INPUT_STATE = 0x4202
INPUT_FIRE = 0x10
SHOT_TABLE = 0x4220
SHOT_ACTIVE = 0
SHOT_X = 1
SHOT_Y = 3
SHOT_LOGICAL_Y = 5
SHOT_WAIT = 1
SHOT_FLIGHT = 2
SHOT_NATIVE_VX = 16
PLAYER_START_X = 233
PLAYER_START_Y = 192


def value24(machine: TSConfFT812Machine, address: int) -> int:
    return (machine.get_byte(address) |
            (machine.get_byte(address + 1) << 8) |
            (machine.get_byte(address + 2) << 16))


def signed15(value: int) -> int:
    return value - 0x8000 if value & 0x4000 else value


def bitmap_draws(data: bytes) -> list[dict[str, int]]:
    source = 0
    width_hi = 0
    height_hi = 0
    width = 0
    height = 0
    primitive = -1
    draws: list[dict[str, int]] = []
    for offset in range(0, len(data), 4):
        word = int.from_bytes(data[offset:offset + 4], "little")
        operation = word >> 24
        if operation == 0x01:
            source = word & 0xFFFFF
        elif operation == 0x29:
            width_hi = (word >> 2) & 3
            height_hi = word & 3
        elif operation == 0x08:
            width = ((word >> 9) & 0x1FF) | (width_hi << 9)
            height = (word & 0x1FF) | (height_hi << 9)
        elif operation == 0x1F:
            primitive = word & 0x0F
        elif operation == 0x21:
            primitive = -1
        elif operation & 0xC0 == 0x40 and primitive == 1:
            draws.append({
                "source": source,
                "width": width,
                "height": height,
                "x_units": signed15((word >> 15) & 0x7FFF),
                "y_units": signed15(word & 0x7FFF),
            })
    return draws


def vertex_units(logical: int) -> int:
    return (logical * 64 + 2) // 5


def native_vertex_units(native: int) -> int:
    """Точный `round(native*64/3)` из RTypeSprite_NativeXToVertex."""
    return (native * 64 + 1) // 3


def main() -> int:
    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
        / "frame_000900_sprite_assets.json"
    ).read_text(encoding="utf-8"))
    shot_info = manifest["dynamic_player_shot"]
    shot_asset = manifest["assets"][shot_info["asset_index"]]
    assert shot_info["code"] == 0x08F8
    assert shot_info["native_velocity_x"] == 16

    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    # Host-тест входит в игровую сцену без внешнего ввода Unreal: воспроизводим
    # ту же часть START-перехода, которая меняет режим.
    machine.set_byte(symbols["GameMode"], 1)
    # Обычный выстрел доступен после штатного 226-кадрового появления R-9.
    # Сам поток появления независимо проверяет sim_player_intro_check.py.
    machine.set_word(symbols["ArcadeIntroFrame"], 226)
    machine.set_byte(symbols["ArcadeIntroEffectKind"], 0)

    machine.set_byte(INPUT_STATE, INPUT_FIRE)
    machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
    player_native_x = machine.get_word(symbols["RTypePlayerNativeX"])
    player_native_y = machine.get_word(symbols["RTypePlayerNativeY"])
    expected_x = player_native_x + 8
    expected_y = player_native_y
    expected_logical_y = PLAYER_START_Y + 12
    assert machine.get_byte(SHOT_TABLE + SHOT_ACTIVE) == SHOT_WAIT
    assert machine.get_word(SHOT_TABLE + SHOT_X) == expected_x
    assert machine.get_word(SHOT_TABLE + SHOT_Y) == expected_y
    assert machine.get_word(SHOT_TABLE + SHOT_LOGICAL_Y) == expected_logical_y

    # Новый fixed slot впервые исполняет `$4F40` на следующем pass.
    machine.call(symbols["ArcadeShots_Update"], max_steps=500_000)
    expected_x += SHOT_NATIVE_VX
    assert machine.get_byte(SHOT_TABLE + SHOT_ACTIVE) == SHOT_FLIGHT
    assert machine.get_word(SHOT_TABLE + SHOT_X) == expected_x

    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=2_000_000)
    commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
    draws = bitmap_draws(commands)
    assert draws
    shot_draws = [draw for draw in draws if draw["source"] == shot_asset["offset"]]
    assert shot_draws
    shot_draw = shot_draws[-1]
    assert shot_draw["source"] == shot_asset["offset"]
    assert shot_draw["width"] == shot_asset["physical_width"]
    assert shot_draw["height"] == shot_asset["physical_height"]
    assert shot_draw["x_units"] == native_vertex_units(expected_x - 0x0148)
    assert shot_draw["y_units"] == vertex_units(expected_logical_y)

    renderer = DLRenderer(bytes(machine.ft.ram_g))
    renderer.run(commands)
    output = ROOT / "Build" / "player_shot_host.png"
    renderer.img.save(output)

    machine.call(symbols["ArcadeShots_Update"], max_steps=500_000)
    assert machine.get_word(SHOT_TABLE + SHOT_X) == expected_x + SHOT_NATIVE_VX

    # Hardware mouse is only a binding to Python's boolean right direction:
    # one arbitrarily large host delta may advance exactly one MOVE_X tick,
    # never farther than the translated SHOT_VX in the same game tick.
    player_q8 = symbols["ArcadePlayerX"]
    before_mouse = value24(machine, player_q8)
    machine.reg.IX = player_q8 + 1
    machine.call(
        symbols["RTypePyPlayer_ApplyMouseDelta"], h=0, l=63,
        max_steps=500_000)
    mouse_delta = value24(machine, player_q8) - before_mouse
    assert mouse_delta == symbols["RTYPE_PY_MOVE_X_Q8"]
    assert mouse_delta < symbols["RTYPE_PY_SHOT_VX_Q8"]

    print("Обычный выстрел R-9: собранное состояние и display list FT812 — OK")
    print(
        f"M72 code=$08F8, RAM_G=${shot_asset['offset']:05X}, "
        f"размер={shot_asset['width']}x{shot_asset['height']} logical"
    )
    print(
        f"старт native=${expected_x - SHOT_NATIVE_VX:04X}, "
        f"скорость native={SHOT_NATIVE_VX}, "
        f"host-кадр={output.name}"
    )
    print(
        f"Mouse X={mouse_delta}/256 px за tick; "
        f"Python SHOT_VX={symbols['RTYPE_PY_SHOT_VX_Q8']}/256 px за tick")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
