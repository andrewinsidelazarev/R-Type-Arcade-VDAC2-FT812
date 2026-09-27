#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle `$8561/$85B0/$865E/$E6AB`."""
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
    Enemy8561, ExplosionEffect, Handler5CEAShot, M72EnemyWorld)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

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
        if isinstance(enemy, Enemy8561):
            assert memory[base] == 48, mark
            assert word(memory, base + 0x0A) == 0x8020, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x20) == enemy.animation_bias, mark
            assert memory[base + 0x2F] == enemy.hp, mark
            assert word(memory, base + 0x30) == enemy.fire_reload, mark
            assert word(memory, base + 0x32) == enemy.shot_velocity & 0xFFFF, mark
            assert word(memory, base + 0x34) == enemy.fire_counter, mark
            assert word(memory, base + 0x36) == enemy.shot_y_phase, mark
            assert memory[base + 0x3E] == enemy.flash_palette, mark
            assert memory[base + 0x3F] == enemy.flash_timer, mark
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
        elif isinstance(enemy, Handler5CEAShot):
            assert memory[base] == 47, mark
            # Python class omits ROM scheduler metadata, но взаимный порядок
            # тот же; target хранит буквальный allocator priority `$6000`.
            assert word(memory, base + 0x0A) == 0x6000, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
        elif isinstance(enemy, ExplosionEffect):
            assert memory[base] == 31, mark
        else:
            raise AssertionError((mark, type(enemy).__name__))
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int]
                ) -> tuple[M72EnemyWorld, Enemy8561]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    world = M72EnemyWorld(stage=5, full_event_stream=True)
    enemy = Enemy8561(world, 0xB40D)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x8561)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0xB40D)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, "init")
    assert (enemy.x, enemy.y, enemy.shot_velocity,
            enemy.fire_reload, enemy.hp) == (
                0x02C8, 0x00C8, -0x02C0, 0x0036, 0x1E)
    return world, enemy


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.call(symbols["RTypeObjects_RunType"], a=47,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=48,
                 max_steps=8_000_000)
    world.update(0, 0, frame)


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: Enemy8561, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_DamageEnemy8561"],
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

    # `$0036` pass: parent проходит восемь paired animation phases и только
    # на нуле создаёт child в пятиточечной последовательности Y-offset.
    world, parent = create_case(machine, symbols)
    for frame in range(parent.fire_reload):
        run_frame(machine, symbols, world, frame)
        check(machine, world, ("fire", frame))
    shots = [enemy for enemy in world.enemies
             if isinstance(enemy, Handler5CEAShot)]
    assert len(shots) == 1
    shot = shots[0]
    assert (shot.x, shot.y, shot.x_velocity) == (
        0x0282, 0x00C8, -0x02C0)
    assert parent.shot_y_phase == 2 and parent.fire_counter == 0x36

    # На следующем VBlank child уже находится перед parent в scheduler и
    # выполняет первый Q8/paired-animation pass.
    run_frame(machine, symbols, world, parent.fire_reload)
    check(machine, world, "child-first-pass")

    # Nonfatal hit оставляет 29 HP и семь flash ticks. Кадр 0 включает `$55`
    # даже после decrement 7->6, как ROM `$85D3…$85E9`.
    world, parent = create_case(machine, symbols)
    parent.take_damage(world, 1)
    damage(machine, symbols, parent, 1)
    check(machine, world, "damage")
    assert parent.hp == 0x1D and parent.flash_timer == 7
    run_frame(machine, symbols, world, 0)
    check(machine, world, "flash-frame-0")
    assert parent.flash_visible
    run_frame(machine, symbols, world, 1)
    check(machine, world, "flash-frame-1")
    assert not parent.flash_visible

    # Fatal hit снимает `$19/$55` и ставит paired `$E817` с resource `$01`.
    world, parent = create_case(machine, symbols)
    parent.hp = 1
    base = POOL + pool_index(parent.object_slot) * REC
    machine.mem.physical[base + 0x2F] = 1
    parent.take_damage(world, 1)
    damage(machine, symbols, parent, 1)
    world.update(0, 0, 0)
    check(machine, world, "fatal-e817")
    assert isinstance(world.enemies[0], ExplosionEffect)
    assert world.resources.types[world.enemies[0].palette] == 0x01

    print("$8561 init: Y/difficulty records, 30 HP и `$55/$19` resources exact")
    print("$85B0: 8 paired phases, flash и 54-pass cadence exact")
    print("$865E/$E6AB: 5 Y offsets, child Q8/paired stream и `$E817` exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
