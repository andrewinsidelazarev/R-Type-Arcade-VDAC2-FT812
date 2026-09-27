#!/usr/bin/env python3
"""Проверка живой волны врагов Stage 1, столкновения и FT812-вывода."""
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
from sim_player_shot_check import bitmap_draws, vertex_units  # noqa: E402

INPUT_STATE = 0x4202
STAGE_FRAME = 0x4279
SCORE = 0x427B
ENEMY_TABLE = 0x4280
ENEMY_ACTIVE = 0
ENEMY_TYPE = 1
ENEMY_X = 2
ENEMY_Y = 4
ENEMY_HP = 6
SHOT_TABLE = 0x4220
SHOT_ACTIVE = 0
SHOT_X = 1
SHOT_Y = 4


def set_q16_8(machine: TSConfFT812Machine, address: int, value: int) -> None:
    machine.set_byte(address, value & 0xFF)
    machine.set_byte(address + 1, (value >> 8) & 0xFF)
    machine.set_byte(address + 2, (value >> 16) & 0xFF)


def main() -> int:
    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites"
        / "frame_000900_sprite_assets.json"
    ).read_text(encoding="utf-8"))
    patrol_info = manifest["stage1_enemies"]["PATROL"]
    patrol_asset = manifest["assets"][patrol_info["asset_index"]]
    assert patrol_info["code"] == 0x0132
    assert patrol_info["palette"] == 7

    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.set_byte(symbols["GameMode"], 1)
    # В этой регрессии нужен активный fixed player; вылет имеет отдельную
    # покадровую проверку и не должен съедать первый enemy pass.
    machine.set_word(symbols["ArcadeIntroFrame"], 226)
    machine.set_byte(symbols["ArcadeIntroEffectKind"], 0)

    # На 64-м кадре возникает первая ROM-derived патрульная машина и сразу
    # проходит штатный шаг движения: X 639->636, Y 100->101.
    machine.set_word(STAGE_FRAME, 63)
    machine.set_byte(INPUT_STATE, 0)
    machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
    assert machine.get_byte(ENEMY_TABLE + ENEMY_ACTIVE) == 1
    assert machine.get_byte(ENEMY_TABLE + ENEMY_TYPE) == 0
    assert machine.get_word(ENEMY_TABLE + ENEMY_X) == 636
    assert machine.get_word(ENEMY_TABLE + ENEMY_Y) == 101

    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=2_000_000)
    commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
    draws = bitmap_draws(commands)
    matching = [draw for draw in draws if draw["source"] == patrol_asset["offset"]]
    assert matching
    assert matching[-1]["x_units"] == vertex_units(636)
    assert matching[-1]["y_units"] == vertex_units(101)

    # Снаряд сначала делает измеренный M72-шаг, затем сталкивается с bbox.
    # Враг стоит в X=300, поэтому старт X=270 после шага попадает в него.
    machine.set_word(STAGE_FRAME, 0)
    machine.set_word(ENEMY_TABLE + ENEMY_X, 300)
    machine.set_word(ENEMY_TABLE + ENEMY_Y, 100)
    machine.set_byte(ENEMY_TABLE + ENEMY_HP, 1)
    machine.set_byte(SHOT_TABLE + SHOT_ACTIVE, 1)
    set_q16_8(machine, SHOT_TABLE + SHOT_X, 270 * 256)
    set_q16_8(machine, SHOT_TABLE + SHOT_Y, 100 * 256)
    machine.call(symbols["ArcadeGame_Update"], max_steps=2_000_000)
    assert machine.get_byte(SHOT_TABLE + SHOT_ACTIVE) == 0
    assert machine.get_byte(ENEMY_TABLE + ENEMY_ACTIVE) == 0
    assert bytes(machine.get_byte(SCORE + index) for index in range(3)) == bytes((0, 1, 0))

    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=2_000_000)
    commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
    draws = bitmap_draws(commands)
    atlas_base = symbols["M72_ATLAS_RAMG"]
    glyph_bytes = symbols["M72_GLYPH_BYTES"]
    digit_source = {
        digit: atlas_base + symbols[f"M72_DIGIT_{digit}_GLYPH"] * glyph_bytes
        for digit in range(10)
    }
    hud_draws = [
        draw for draw in draws
        if atlas_base <= draw["source"] < atlas_base + symbols["M72_ATLAS_SIZE"]
    ][-6:]
    expected_hud = [digit_source[digit] for digit in (0, 0, 0, 1, 0, 0)]
    assert [draw["source"] for draw in hud_draws] == expected_hud, (
        [draw["source"] for draw in hud_draws], expected_hud,
        len(draws), len(commands), atlas_base,
    )
    assert all(draw["y_units"] == 192 for draw in hud_draws)

    print("Stage 1: живая волна врагов, столкновение и счёт — OK")
    print(
        f"M72 patrol code=$0132/pal7, asset={patrol_info['asset_index']}, "
        f"RAM_G=${patrol_asset['offset']:05X}"
    )
    print("spawn frame=64, X=636/Y=101; попадание начисляет 100, HUD=000100")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
