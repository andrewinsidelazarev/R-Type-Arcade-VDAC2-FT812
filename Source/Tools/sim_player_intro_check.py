#!/usr/bin/env python3
"""Проверить точный вылет/корпус R-9 и отсутствие постоянного синего хвоста.

Host-модель исполняет собранные Z80-процедуры чтения 226-кадровой таблицы и
выдачи display list. Для каждого кадра сверяются координаты, native anchor,
выбранный RAM_G-ассет и число bitmap-примитивов. После intro допустим ровно
один bitmap корпуса; захваченный frame-900 exhaust не должен встречаться.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from sim_frame_png import DLRenderer  # noqa: E402


EVENT = struct.Struct("<hhBBhhHH")
INTRO_FRAMES = 226


def render_commands(machine: TSConfFT812Machine,
                    symbols: dict[str, int]) -> bytes:
    command_buffer = symbols["RTypeFTCommandBufferStart"]
    command_end = symbols["RTypeFTCommandBufferEnd"]
    machine.set_word(symbols["FT.Coprocessor.BufferPtr"], command_buffer)
    machine.call(symbols["Render_M72DynamicPlayer"], max_steps=100_000)
    end = machine.get_word(symbols["FT.Coprocessor.BufferPtr"])
    if not command_buffer <= end < command_end:
        raise AssertionError(f"неверный конец display list: ${end:04X}")
    return bytes(machine.get_byte(address)
                 for address in range(command_buffer, end))


def bitmap_sources(commands: bytes) -> list[int]:
    return [
        word & 0x3FFFFF
        for word in (int.from_bytes(commands[offset:offset + 4], "little")
                     for offset in range(0, len(commands), 4))
        if word >> 24 == 0x01
    ]


def vertex_count(commands: bytes) -> int:
    return sum(
        1 for offset in range(0, len(commands), 4)
        if int.from_bytes(commands[offset:offset + 4], "little") >> 30 == 1
    )


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites" /
        "frame_000900_sprite_assets.json"
    ).read_text(encoding="utf-8"))
    assets = manifest["assets"]
    exact = manifest["exact_player_assets"]
    pitch_sources = [int(assets[index]["offset"])
                     for index in exact["pitch_asset_indices"]]
    pitch_widths = [int(assets[index]["width"])
                    for index in exact["pitch_asset_indices"]]
    effect_sources = [int(assets[index]["offset"])
                      for index in exact["launch_asset_indices"]]
    effect_widths = [int(assets[index]["width"])
                     for index in exact["launch_asset_indices"]]
    wrong_exhaust_source = int(assets[
        manifest["dynamic_instances"]["exhaust"]["asset_index"]]["offset"])
    events = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Player" /
        "R9_LAUNCH_LOGICAL.bin"
    ).read_bytes()
    if len(events) != INTRO_FRAMES * EVENT.size:
        raise AssertionError("неверный размер логической launch-таблицы")

    machine.set_byte(symbols["ArcadePlayerVisible"], 1)
    for frame in range(INTRO_FRAMES):
        expected = EVENT.unpack_from(events, frame * EVENT.size)
        player_x, player_y, body_index, effect_kind, effect_x, effect_y, \
            native_x, native_y = expected
        machine.set_word(symbols["ArcadeIntroFrame"], frame)
        machine.call(symbols["ArcadePlayer_IntroUpdate"], max_steps=20_000)
        assert machine.get_word(symbols["ArcadeIntroFrame"]) == frame + 1
        assert machine.get_word(symbols["ArcadePlayerX"] + 1) == player_x & 0xFFFF
        assert machine.get_word(symbols["ArcadePlayerY"] + 1) == player_y & 0xFFFF
        assert machine.get_byte(symbols["ArcadePlayerPitch"]) == body_index << 3
        assert machine.get_byte(symbols["ArcadeIntroEffectKind"]) == effect_kind
        assert machine.get_word(symbols["ArcadeIntroEffectX"]) == effect_x & 0xFFFF
        assert machine.get_word(symbols["ArcadeIntroEffectY"]) == effect_y & 0xFFFF
        assert machine.get_word(symbols["RTypePlayerNativeX"]) == native_x
        assert machine.get_word(symbols["RTypePlayerNativeY"]) == native_y

        commands = render_commands(machine, symbols)
        expected_sources: list[int] = []
        if effect_kind:
            effect_index = effect_kind - 1
            if effect_x + effect_widths[effect_index] > 0:
                expected_sources.append(
                    effect_sources[effect_index] + max(0, -effect_x) * 2)
        if player_x + pitch_widths[body_index] > 0:
            expected_sources.append(
                pitch_sources[body_index] + max(0, -player_x) * 2)
        actual_sources = bitmap_sources(commands)
        assert actual_sources == expected_sources, (
            frame, actual_sources, expected_sources)
        assert vertex_count(commands) == len(expected_sources)
        assert wrong_exhaust_source not in actual_sources

    # Состояние активной игры после intro: нейтральный R-9 и ни одного
    # launch/exhaust bitmap. Это прямая регрессия синего шлейфа со снимка.
    machine.set_byte(symbols["ArcadeIntroEffectKind"], 0)
    machine.set_byte(symbols["ArcadePlayerPitch"], 20)
    machine.set_byte(symbols["ArcadePlayerX"], 0)
    machine.set_word(symbols["ArcadePlayerX"] + 1, 233)
    machine.set_byte(symbols["ArcadePlayerY"], 0)
    machine.set_word(symbols["ArcadePlayerY"] + 1, 192)
    commands = render_commands(machine, symbols)
    assert bitmap_sources(commands) == [pitch_sources[2]]
    assert vertex_count(commands) == 1

    sprite_blob = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Sprites" /
        "RTYPE_M72_FRAME900_ARGB4444.bin"
    ).read_bytes()
    machine.ft.ram_g[:len(sprite_blob)] = sprite_blob
    renderer = DLRenderer(bytes(machine.ft.ram_g))
    renderer.vertex_format = 3
    renderer.transform_a = 160
    renderer.transform_e = 160
    renderer.run(commands)
    full_output = ROOT / "Build" / "player_r9_exact_host.png"
    crop_output = ROOT / "Build" / "player_r9_exact_crop.png"
    renderer.img.save(full_output)
    renderer.img.crop((350, 285, 470, 365)).save(crop_output)

    print(
        "R-9 intro: 226 таблиц/координат/ассетов FT812 — OK; "
        "после intro ровно один корпус, постоянного хвоста нет"
    )
    print(f"host-кроп: {crop_output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
