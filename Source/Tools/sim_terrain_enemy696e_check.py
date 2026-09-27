#!/usr/bin/env python3
"""Покадровый oracle `$696E/$69B4/$6A78`, включая terrain replacement."""
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

from rtype_port.enemies import (  # noqa: E402
    EnemyProjectile, M72EnemyWorld, TerrainEnemy696E)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

PAGE7 = 0x07 * 0x4000
PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980
RNG = PAGE9 + 0x1990


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def terrain_address(x: int, y: int) -> int:
    horizontal = ((x - 0x0140) & 0xFFFF) >> 1
    horizontal &= 0xFFFC
    address = (0x1020 + horizontal) & 0x10FF
    vertical = 0x017F - y
    if vertical < 0:
        vertical = 0
    return (address + ((vertical & 0xFFF8) << 5)) & 0x3FFF


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          expected_map: bytearray, mark: object) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (mark, active, set(expected))
    for index, enemy in expected.items():
        base = POOL + index * REC
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        if isinstance(enemy, TerrainEnemy696E):
            assert memory[base] == 44, mark
            assert word(memory, base + 0x16) == enemy.motion.script, mark
            assert word(memory, base + 0x18) == enemy.motion.pointer, mark
            assert memory[base + 0x1A] == enemy.motion.commands, mark
            assert word(memory, base + 0x1B) == enemy.motion.phase, mark
            assert word(memory, base + 0x20) == enemy.fire_counter, mark
            assert word(memory, base + 0x22) == enemy.fire_a, mark
            assert word(memory, base + 0x24) == enemy.fire_b, mark
            assert word(memory, base + 0x26) == enemy.projectile_script, mark
            assert memory[base + 0x28] == enemy.flash_palette, mark
            assert memory[base + 0x29] == enemy.flash_timer, mark
            assert word(memory, base + 0x2A) == enemy.hp, mark
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
        elif isinstance(enemy, EnemyProjectile):
            assert memory[base] == 9, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert memory[base + 0x11] == enemy.y_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
            assert word(memory, base + 0x2C) == enemy.phase_seed, mark
            assert word(memory, base + 0x2E) == enemy.burst_timer, mark
        else:
            raise AssertionError(type(enemy).__name__)
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map, mark


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: TerrainEnemy696E, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_DamageTerrainEnemy696E"],
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
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)

    expected_map = bytearray(bytes((0xA0, 0x0F, 0, 0)) * (0x4000 // 4))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map
    world = M72EnemyWorld(stage=4, full_event_stream=True)
    command = 0x12
    enemy = TerrainEnemy696E(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x696E)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"],
                 max_steps=5_000_000)
    check(machine, world, expected_map, "init")

    def terrain_code(x: int, y: int) -> int:
        return word(expected_map, terrain_address(x, y)) & 0x0FFF

    def replace(address: int, code: int, attribute: int) -> None:
        put_word(expected_map, address & 0x3FFF, code)
        put_word(expected_map, (address + 2) & 0x3FFF, attribute)

    # Trigger `$F63A` equality branch on the first pass.
    enemy.fire_counter = (enemy.fire_a - 1) & 0xFFFF
    put_word(machine.mem.physical,
             POOL + pool_index(enemy.object_slot) * REC + 0x20,
             enemy.fire_counter)
    for frame in range(1, 6):
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        machine.call(symbols["RTypeObjects_RunType"], a=44,
                     max_steps=10_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=9,
                     max_steps=8_000_000)
        world.update(0, 0, frame, terrain_code=terrain_code,
                     terrain_address=terrain_address,
                     replace_terrain=replace)
        check(machine, world, expected_map, ("motion", frame))
        if frame == 1:
            # Difficulty-zero `$9294` record is all-zero: `$F63A` advances,
            # but zero projectile_script deliberately suppresses allocation.
            assert not any(isinstance(item, EnemyProjectile)
                           for item in world.enemies)
            enemy.take_damage(world, 1)
            damage(machine, symbols, enemy, 1)
            check(machine, world, expected_map, "damage")

    # Глобальный cleanup обязан снять normal `$2A` и flash `$55`.
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    machine.call(symbols["RTypeObjects_RunType"], a=44,
                 max_steps=3_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=9,
                 max_steps=3_000_000)
    world.update(0, 0, 6, terrain_code=terrain_code,
                 terrain_address=terrain_address, replace_terrain=replace)
    check(machine, world, expected_map, "cleanup")

    print("$696E init: position, variable-command `$F5C1` и fire record exact")
    print("$69B4: motion/phase, zero-script `$F63A` и flash exact")
    print("$6A78: probe `$2D90`, cell `$09F6/$0082` и cleanup exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
