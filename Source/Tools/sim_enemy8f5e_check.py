#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle `$8F5E/$8F86/$90A2/$90E0`."""
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

from rtype_port.enemies import Enemy8F5E, M72EnemyWorld  # noqa: E402
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

PAGE7 = 0x07 * 0x4000
PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def terrain_address(x: int, y: int) -> int:
    """Точная `$1E6C`-арифметика для нулевых X/Y scroll в этом тесте."""
    horizontal = ((x - 0x0140) & 0xFFFF) >> 1
    horizontal &= 0xFFFC
    address = (0x1020 + horizontal) & 0x10FF
    vertical = 0x017F - y
    if vertical < 0:
        vertical = 0
    return (address + ((vertical & 0xFFF8) << 5)) & 0x3FFF


def terrain_cell(expected_map: bytearray, address: int) -> tuple[int, int]:
    address &= 0x3FFF
    return (word(expected_map, address),
            word(expected_map, (address + 2) & 0x3FFF))


def replace_terrain(expected_map: bytearray, address: int,
                    code: int, attribute: int) -> None:
    address &= 0x3FFF
    put_word(expected_map, address, code)
    put_word(expected_map, (address + 2) & 0x3FFF, attribute)


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          expected_map: bytearray, mark: object) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (mark, active, set(expected))
    for index, enemy in expected.items():
        assert isinstance(enemy, Enemy8F5E), (mark, type(enemy).__name__)
        base = POOL + index * REC
        assert memory[base] == 45, mark
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert word(memory, base + 0x0A) == 0x8230, mark
        assert memory[base + 0x10] == enemy.x_fraction, mark
        assert memory[base + 0x11] == enemy.y_fraction, mark
        assert memory[base + 0x20] == enemy.direction, mark
        assert memory[base + 0x21] == enemy.next_direction, mark
        assert word(memory, base + 0x22) == enemy.turn_timer, mark
        assert word(memory, base + 0x24) == enemy.turn_table, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map, mark


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int]
                ) -> tuple[M72EnemyWorld, Enemy8F5E, bytearray]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)

    # Верхний nibble `$1` доказывает обязательный mask `$0FFF`; attr `$0082`
    # должен быть обнулён вместе с tile code, а не остаться от старой cell.
    expected_map = bytearray(bytes((0xF6, 0x19, 0x82, 0x00)) *
                             (0x4000 // 4))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map
    world = M72EnemyWorld(stage=4, full_event_stream=True)
    enemy = Enemy8F5E(world, 0x5000)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x8F5E)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x5000)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, expected_map, "init")
    return world, enemy, expected_map


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, expected_map: bytearray,
              frame: int, delta: int,
              player: tuple[int, int]) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.set_word(symbols["RTypePlayerNativeX"], player[0])
    machine.set_word(symbols["RTypePlayerNativeY"], player[1])
    machine.call(symbols["RTypeObjects_RunType"], a=45,
                 max_steps=8_000_000)
    world.update(
        0, delta, frame, player_native=player,
        terrain_address=terrain_address,
        terrain_cell=lambda address: terrain_cell(expected_map, address),
        replace_terrain=lambda address, code, attr: replace_terrain(
            expected_map, address, code, attr))


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    # Обычная branch: Q8 movement, один foreground delta, animation и четыре
    # terrain replacements. Player далеко, поэтому turn не начинается.
    world, enemy, expected_map = create_case(machine, symbols)
    before = bytes(expected_map)
    run_frame(machine, symbols, world, expected_map, 0, -1, (0, 0))
    check(machine, world, expected_map, "normal")
    changed = [index for index in range(0, 0x4000, 4)
               if before[index:index + 4] != expected_map[index:index + 4]]
    assert len(changed) == 4, changed
    assert (enemy.x, enemy.y, enemy.descriptor) == (0x0197, 0x0187, 0x404E)

    # Entry-frame разворота применяет delta дважды. Все 31 updates turn-state
    # пропускают `$90E0` и bounds; map должна остаться буквально неизменной.
    world, enemy, expected_map = create_case(machine, symbols)
    untouched = bytes(expected_map)
    run_frame(machine, symbols, world, expected_map,
              0, -1, (0x0200, 0x018B))
    check(machine, world, expected_map, "turn-entry")
    assert (enemy.x, enemy.y, enemy.direction, enemy.next_direction,
            enemy.turn_timer, enemy.descriptor) == (
                0x0196, 0x0187, 3, 0, 0x1E, 0x4072)
    assert bytes(expected_map) == untouched
    for frame in range(1, 31):
        run_frame(machine, symbols, world, expected_map,
                  frame, -8, (0x0200, 0x018B))
        check(machine, world, expected_map, ("turn", frame))
        assert bytes(expected_map) == untouched, frame
    assert enemy.turn_timer == 0 and enemy.direction == 0

    # Объект уже ушёл левее `$012C`, но был жив до конца дуги. Лишь следующий
    # normal pass выполняет terrain mutation, bounds и natural release.
    run_frame(machine, symbols, world, expected_map, 31, 0, (0, 0))
    check(machine, world, expected_map, "post-turn-bounds")
    assert not enemy.alive and enemy.object_slot is None

    # Общий cleanup снимает единственный resource `$2E` без запуска handler-а.
    world, cleanup_enemy, expected_map = create_case(machine, symbols)
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run_frame(machine, symbols, world, expected_map, 1, 0, (0, 0))
    check(machine, world, expected_map, "cleanup")
    assert not cleanup_enemy.alive and cleanup_enemy.object_slot is None

    print("$8F5E init/Q8: position, direction `$3F76` и priority `$8230` exact")
    print("$8F86/$90A2: double foreground delta и 31-update turn exact")
    print("$90E0: четыре `$09F6->$0FA0/0` cells и delayed bounds exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
