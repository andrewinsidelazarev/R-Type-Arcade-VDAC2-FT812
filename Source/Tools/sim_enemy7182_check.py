#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle Stage 5 `$7182/$71C7`."""
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
    Enemy7182, EnemyProjectile, M72EnemyWorld,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

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


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          mark: object) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (mark, active, set(expected))
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, Enemy7182):
            assert memory[base] == 51, mark
            assert word(memory, base + 0x0A) == 0x8020, mark
            assert word(memory, base + 0x20) == enemy.fire_counter, mark
            assert word(memory, base + 0x22) == enemy.fire_a, mark
            assert word(memory, base + 0x24) == enemy.fire_b, mark
            assert word(memory, base + 0x26) == enemy.projectile_script, mark
            assert memory[base + 0x28] == enemy.direction, mark
            assert word(memory, base + 0x2A) == enemy.turn_reload, mark
            assert word(memory, base + 0x2C) == enemy.turn_counter, mark
            assert word(memory, base + 0x2E) == enemy.active_timer, mark
        elif isinstance(enemy, EnemyProjectile):
            assert memory[base] == 9, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
            assert word(memory, base + 0x2C) == enemy.phase_seed, mark
            assert word(memory, base + 0x2E) == enemy.burst_timer, mark
        else:
            raise AssertionError((mark, type(enemy).__name__))
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert memory[base + 0x10] == enemy.x_fraction, mark
        assert memory[base + 0x11] == enemy.y_fraction, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)

    world = M72EnemyWorld(stage=5, full_event_stream=True)
    command = 0x7852
    enemy = Enemy7182(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x7182)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, "init")
    assert (enemy.x, enemy.y, enemy.direction, enemy.turn_reload,
            enemy.active_timer, enemy.fire_a, enemy.fire_b,
            enemy.projectile_script) == (
                0x0278, 0x0188, 8, 0x10, 0x0280,
                0x0040, 0x0060, 0x9050)

    # `$71C7` вычисляет сектор по native-координатам R-9. Первый counter=1,
    # поэтому уже первый pass поворачивает 8->9 и загружает Q8-вектор ROM.
    machine.set_word(symbols["RTypePlayerNativeX"], world.player_native[0])
    machine.set_word(symbols["RTypePlayerNativeY"], world.player_native[1])
    machine.set_word(symbols["FrameCounter"], 0)
    machine.call(symbols["RTypeObjects_RunType"], a=51,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=9,
                 max_steps=8_000_000)
    world.update(0, 0, 0)
    check(machine, world, "first-turn")
    assert (enemy.direction, enemy.x_velocity, enemy.y_velocity,
            enemy.x, enemy.x_fraction, enemy.y, enemy.y_fraction,
            enemy.descriptor) == (
                9, -0x00C0, -0x01C0, 0x0277, 0x40,
                0x0186, 0x40, 0x324C)

    # Доводим `$F63A` до trigger без десятков пустых кадров. Общий `$E601`
    # обязан появиться в том же pass и совпасть с Python по RNG/Q8/descriptor.
    enemy.fire_counter = enemy.fire_a - 1
    base = POOL + pool_index(enemy.object_slot) * REC
    put_word(machine.mem.physical, base + 0x20, enemy.fire_counter)
    machine.set_word(symbols["FrameCounter"], 1)
    machine.call(symbols["RTypeObjects_RunType"], a=51,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=9,
                 max_steps=8_000_000)
    world.update(0, 0, 1)
    check(machine, world, "common-projectile")
    assert any(isinstance(item, EnemyProjectile) for item in world.enemies)

    # После `$0280` движение продолжается с последним вектором, но сектор
    # больше не пересчитывается. Проверяем это напрямую без долгого прогона.
    enemy.active_timer = 0
    put_word(machine.mem.physical, base + 0x2E, 0)
    old_direction = enemy.direction
    machine.set_word(symbols["RTypePlayerNativeX"], 0x02C8)
    machine.set_word(symbols["RTypePlayerNativeY"], 0x0080)
    machine.set_word(symbols["FrameCounter"], 2)
    machine.call(symbols["RTypeObjects_RunType"], a=51,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=9,
                 max_steps=8_000_000)
    world.player_native = (0x02C8, 0x0080)
    world.update(0, 0, 2)
    check(machine, world, "timer-expired")
    assert enemy.direction == old_direction

    print("$7182 init: position/fire/direction records и RNG mask exact")
    print("$71C7: one-sector turn, ROM Q8 vector и descriptor exact")
    print("$71C7->$F63A/$E601: same-pass projectile и active timeout exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
