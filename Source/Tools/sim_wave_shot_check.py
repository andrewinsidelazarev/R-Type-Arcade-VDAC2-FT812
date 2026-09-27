#!/usr/bin/env python3
"""Проверка Wave Cannon в собранном Z80 и списке вывода FT812.

Это моделирование на компьютере, не Unreal и не реальное железо. Исполняется
настоящий код SPG: 66 кадров заряда не дают Wave, 67 кадров создают его через
два кадра, после чего сверяются обе подлинные графические фазы M72.
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
from sim_player_shot_check import (  # noqa: E402
    bitmap_draws, native_vertex_units, vertex_units,
)

INPUT_STATE = 0x4202
INPUT_FIRE = 0x10
WAVE_PENDING = 0x4213
WAVE_ACTIVE = 0x423C
WAVE_DELAY = 0x423D
WAVE_ANIM = 0x423E
WAVE_X = 0x423F
WAVE_Y = 0x4241
WAVE_RELEASE_X = 0x4243
WAVE_RELEASE_Y = 0x4245
WAVE_LOGICAL_Y = 0x4247
WAVE_POWER = 0x4212
PLAYER_START_X = 233
PLAYER_START_Y = 192
WAVE_MIN_CHARGE = 0x18
WAVE_HOLD_FRAMES = WAVE_MIN_CHARGE // 2
WAVE_NATIVE_VX = 8


def render_commands(
        machine: TSConfFT812Machine, symbols: dict[str, int],
) -> bytes:
    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=2_000_000)
    return bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])


def main() -> int:
    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
        / "frame_000900_sprite_assets.json"
    ).read_text(encoding="utf-8"))
    wave = manifest["dynamic_player_wave"]
    assets = [manifest["assets"][index] for index in wave["asset_indices"]]
    release_assets = [
        manifest["assets"][index]
        for index in wave["release_asset_indices"]
    ]
    assert wave["phase_codes"] == [[0x0054, 0x0055, 0x0016],
                                   [0x0056, 0x0057, 0x0017]]
    assert wave["native_width"] == 80 and wave["native_height"] == 16
    assert wave["native_velocity_x"] == 8
    assert wave["appear_delay"] == 2
    assert wave["release_codes"] == [0x0013, 0x0043, 0x0044, 0x0045]
    assert wave["release_durations"] == [2, 2, 2, 1]

    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.set_byte(symbols["GameMode"], 1)
    # Зарядка Wave относится к активной игре после точного launch-сценария.
    machine.set_word(symbols["ArcadeIntroFrame"], 226)
    machine.set_byte(symbols["ArcadeIntroEffectKind"], 0)

    for _ in range(WAVE_HOLD_FRAMES):
        machine.set_byte(INPUT_STATE, INPUT_FIRE)
        machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
    machine.set_byte(INPUT_STATE, 0)
    machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)

    expected_x = machine.get_word(symbols["RTypePlayerNativeX"]) + 8
    expected_y = machine.get_word(symbols["RTypePlayerNativeY"])
    expected_logical_y = PLAYER_START_Y + 3
    assert machine.get_byte(WAVE_PENDING) == 1
    assert machine.get_byte(WAVE_ACTIVE) == 1
    assert machine.get_byte(WAVE_DELAY) == 2
    assert machine.get_byte(WAVE_POWER) == 4
    assert machine.get_word(WAVE_X) == expected_x
    assert machine.get_word(WAVE_Y) == expected_y
    assert machine.get_word(WAVE_RELEASE_X) == expected_x
    assert machine.get_word(WAVE_RELEASE_Y) == expected_y
    assert machine.get_word(WAVE_LOGICAL_Y) == expected_logical_y

    # Два обновления реализуют измеренную задержку M72 после отпускания.
    for expected_delay in (1, 0):
        machine.set_byte(INPUT_STATE, 0)
        machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
        assert machine.get_byte(WAVE_DELAY) == expected_delay
    assert machine.get_byte(WAVE_ANIM) == 0

    commands_a = render_commands(machine, symbols)
    draws_a = bitmap_draws(commands_a)
    release_draw_a = [
        draw for draw in draws_a if draw["source"] == release_assets[0]["offset"]
    ][-1]
    draw_a = [draw for draw in draws_a if draw["source"] == assets[0]["offset"]][-1]
    assert release_draw_a["source"] == release_assets[0]["offset"]
    assert draw_a["source"] == assets[0]["offset"]
    assert draw_a["width"] == assets[0]["physical_width"]
    assert draw_a["height"] == assets[0]["physical_height"]
    assert draw_a["x_units"] == native_vertex_units(expected_x - 0x0148)
    assert draw_a["y_units"] == vertex_units(expected_logical_y)
    renderer_a = DLRenderer(bytes(machine.ft.ram_g))
    renderer_a.run(commands_a)
    output_a = ROOT / "Build" / "wave_shot_host_phase_a.png"
    renderer_a.img.save(output_a)

    # Через два шага движения выбирается вторая двухкадровая фаза.
    for _ in range(2):
        machine.set_byte(INPUT_STATE, 0)
        machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
    assert machine.get_byte(WAVE_ANIM) == 2
    assert machine.get_word(WAVE_X) == expected_x + 2 * WAVE_NATIVE_VX
    commands_b = render_commands(machine, symbols)
    draws_b = bitmap_draws(commands_b)
    release_draw_b = [
        draw for draw in draws_b if draw["source"] == release_assets[1]["offset"]
    ][-1]
    draw_b = [draw for draw in draws_b if draw["source"] == assets[1]["offset"]][-1]
    assert release_draw_b["source"] == release_assets[1]["offset"]
    assert draw_b["source"] == assets[1]["offset"]
    assert draw_b["x_units"] == native_vertex_units(
        expected_x + 2 * WAVE_NATIVE_VX - 0x0148)
    renderer_b = DLRenderer(bytes(machine.ft.ram_g))
    renderer_b.run(commands_b)
    output_b = ROOT / "Build" / "wave_shot_host_phase_b.png"
    renderer_b.img.save(output_b)

    print("Wave Cannon: собранное состояние и обе фазы FT812 — OK")
    print(
        f"M72 codes={wave['phase_codes']}, RAM_G="
        f"${assets[0]['offset']:05X}/${assets[1]['offset']:05X}"
    )
    print(
        f"порог counter=${WAVE_MIN_CHARGE:02X} ({WAVE_HOLD_FRAMES} VBlank), "
        f"задержка=2, скорость native={WAVE_NATIVE_VX}, "
        f"кадры={output_a.name}, {output_b.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
