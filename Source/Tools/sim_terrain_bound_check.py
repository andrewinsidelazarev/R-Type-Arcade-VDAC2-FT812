#!/usr/bin/env python3
"""Побайтовый oracle `$55E9` для banked TS-Config object handler."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from rtype_port.enemies import M72EnemyWorld, TerrainBound55E9  # noqa: E402
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE7 = 0x07 * 0x4000
PAGE9 = 0x09 * 0x4000
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def fill_foreground(machine: TSConfFT812Machine, solid: bool) -> None:
    """Сделать всю foreground ring-карту однородной для state transition."""
    if solid:
        payload = bytes(0x4000)             # tile code `$0000` < `$0DFC`
    else:
        payload = bytes((0xA0, 0x0F, 0, 0)) * (0x4000 // 4)
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = payload


def compare(machine: TSConfFT812Machine, symbols: dict[str, int],
            enemy: TerrainBound55E9, expected_alive: bool,
    world: M72EnemyWorld, frame: int) -> None:
    memory = machine.mem.physical
    base = symbols["RTYPE_OBJECT_SCRATCH"]
    record = bytearray(machine.get_byte(base + offset) for offset in range(0x40))
    if not expected_alive:
        assert record[symbols["RTYPE_OBJ_TYPE"]] == 0, frame
        return
    states = {
        "script": 0,
        "air_step": 1,
        "land": 2,
        "walk": 3,
        "turn": 4,
        "pickup": 5,
        "speed_indicator": 6,
    }
    assert record[symbols["RTYPE_OBJ_TYPE"]] == 10, frame
    assert word(record, 0x02) == enemy.x, frame
    assert word(record, 0x04) == enemy.y, frame
    assert word(record, 0x06) == enemy.descriptor, frame
    assert record[0x08] == enemy.palette, frame
    assert record[0x0E] == states[enemy.state], frame
    assert record[0x10] == enemy.x_fraction, frame
    assert record[0x11] == enemy.y_fraction, frame
    assert word(record, 0x16) == enemy.motion.script, frame
    assert word(record, 0x18) == enemy.motion.pointer, frame
    assert record[0x1A] == enemy.motion.commands, frame
    assert word(record, 0x1B) == enemy.motion.phase, (
        frame, word(record, 0x1B), enemy.motion.phase, enemy.state)
    assert word(record, 0x1D) == enemy.timer, frame
    assert record[0x20] == enemy.pickup_index, frame
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame


def run_case(*, turn_flip: bool) -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    machine.call(symbols["RTypeWorld_ClearMaps"], max_steps=2_000_000)

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    command = 0x1006
    enemy = TerrainBound55E9(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)

    machine.set_word(symbols["RTypeWorldLastHandler"], 0x55E9)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    compare(machine, symbols, enemy, True, world, 0)

    # Двенадцать чистых passes проверяют `$F5C1`; затем принудительно выбираем
    # `$5620`, чтобы отдельно проверить унаследованную Y fraction и шаг -1.
    solid = False
    turn_entry_phase: int | None = None
    for frame in range(1, 90):
        if frame == 13:
            enemy.state = "air_step"
            machine.set_byte(
                symbols["RTYPE_OBJECT_SCRATCH"] + symbols["RTYPE_OBJ_STATE"], 1)
        if frame == 14:
            solid = True                    # lower probe -> land
        elif enemy.state == "land":
            solid = False
        elif enemy.state == "walk":
            solid = turn_flip               # second solid probe flips phase
        elif enemy.state == "turn":
            solid = False
        fill_foreground(machine, solid)
        world._terrain_code = (lambda _x, _y, value=solid:
                               0x0000 if value else 0x0FFF)
        delta = frame & 1
        world.frame_counter = frame
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], delta)
        machine.call(symbols["RTypeObjectBank1_UpdateTerrainBound"],
                     max_steps=5_000_000)
        enemy.update(world, delta)
        compare(machine, symbols, enemy, enemy.alive, world, frame)
        if enemy.state == "turn" and turn_entry_phase is None:
            turn_entry_phase = enemy.motion.phase

        # После первого walking pass state уже обязан стать turn; далее карта
        # снова пустая и 31-кадровый `$577B` доходит до нового script root.
        if frame > 14 and enemy.state == "script" and enemy.timer == 0:
            break
    else:
        raise AssertionError("`$55E9` не завершил land/walk/turn trace")

    # Trampoline обязан вернуть page2 #06: иначе следующий resident CALL
    # исполнился бы из bank payload. Безопасный scratch clear служит probe.
    machine.call(symbols["RTypeObjects_ClearScratch"], max_steps=100_000)
    assert turn_entry_phase is not None
    return turn_entry_phase


def main() -> int:
    ordinary_phase = run_case(turn_flip=False)
    flipped_phase = run_case(turn_flip=True)
    assert ordinary_phase ^ flipped_phase == 8
    print("$55E9 init: ROM coordinates/resource/Q8 residue exact")
    print("$5629/$5620: ScriptedMotion и air-step exact")
    print("$568F/$5704/$577B: land/walk/both turn branches exact")
    print("Object bank #0A: page2 restore exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
