#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle Stage 6 `$5EED/$5F3C`."""
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

from rtype_port.enemies import Enemy5EED, M72EnemyWorld  # noqa: E402
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


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def fill_terrain(machine: TSConfFT812Machine, code: int) -> None:
    cell = bytes((code & 0xFF, (code >> 8) & 0xFF, 0, 0))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = cell * (0x4000 // 4)


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          mark: object) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (mark, active, set(expected))
    for index, enemy in expected.items():
        assert isinstance(enemy, Enemy5EED), (mark, type(enemy).__name__)
        base = POOL + index * REC
        assert memory[base] == 50, mark
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert word(memory, base + 0x0A) == 0x4030, mark
        assert memory[base + 0x10] == enemy.x_fraction, mark
        assert memory[base + 0x11] == enemy.y_fraction, mark
        assert memory[base + 0x20] == enemy.direction, mark
        assert word(memory, base + 0x22) == enemy.speed_offset, mark
        assert bool(memory[base + 0x24]) == enemy.turn_clockwise, mark
        assert bool(memory[base + 0x25]) == enemy.mirrored, mark
        assert memory[base + 0x26] == enemy.flash_palette, mark
        assert memory[base + 0x27] == enemy.flash_timer, mark
        assert word(memory, base + 0x28) == enemy.hp, mark
        assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int],
                command: int) -> tuple[M72EnemyWorld, Enemy5EED]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)
    world = M72EnemyWorld(stage=6, full_event_stream=True)
    enemy = Enemy5EED(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x5EED)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, ("init", command))
    return world, enemy


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int,
              terrain_code: int, delta: int = 0) -> None:
    fill_terrain(machine, terrain_code)
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.call(symbols["RTypeObjects_RunType"], a=50,
                 max_steps=8_000_000)
    world.update(0, delta, frame,
                 terrain_code=lambda _x, _y: terrain_code)


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: Enemy5EED, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_DamageEnemy5EED"],
                 a=amount, max_steps=2_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=1_000_000)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    world, enemy = create_case(machine, symbols, 0x2022)
    assert (enemy.x, enemy.y, enemy.direction, enemy.turn_clockwise,
            enemy.mirrored, enemy.speed_offset, enemy.hp) == (
                0x02C8, 0x0108, 2, False, False, 0x20, 10)
    run_frame(machine, symbols, world, 0, 0x0FFF, -1)
    check(machine, world, "free-ray")
    assert (enemy.x, enemy.y, enemy.y_fraction,
            enemy.direction, enemy.descriptor) == (
                0x02C5, 0x0108, 0, 2, 0x2AC0)

    # Первый solid sample поворачивает против часовой стрелки 2->1.
    run_frame(machine, symbols, world, 1, 0x0001)
    check(machine, world, "counter-clockwise")
    assert enemy.direction == 1

    # Bit8 + bit6 выбирают clockwise и mirrored tables: 1->2.
    world, mirrored = create_case(machine, symbols, 0x216F)
    assert mirrored.turn_clockwise and mirrored.mirrored
    assert mirrored.direction == 1
    run_frame(machine, symbols, world, 0, 0x0001)
    check(machine, world, "clockwise-mirrored")
    assert mirrored.direction == 2

    # Nonfatal damage: HP 10->9 и 31 flash ticks, paired renderer выбирает
    # `$51` по уже уменьшенному timer bit2.
    mirrored.take_damage(world, 1)
    damage(machine, symbols, mirrored, 1)
    check(machine, world, "damage")
    assert mirrored.hp == 9 and mirrored.flash_timer == 0x1F
    run_frame(machine, symbols, world, 1, 0x0FFF)
    check(machine, world, "flash")

    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run_frame(machine, symbols, world, 2, 0x0FFF)
    check(machine, world, "cleanup")
    assert mirrored.object_slot is None

    print("$5EED init: 6-byte records, command flags и speed offset exact")
    print("$5F3C: Q8/scroll, paired mirror animation и flash exact")
    print("$5FD5: 3-sample ray, CW/CCW turn и cleanup exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
