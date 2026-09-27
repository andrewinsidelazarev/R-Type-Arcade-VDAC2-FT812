#!/usr/bin/env python3
"""Покадровый oracle для `$875D/$8798/$8817` и child `$8861/$893E`."""
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
    M72EnemyWorld, Spawner875D, Spawner875DChild)
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
          frame: int) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (frame, active, set(expected))
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, Spawner875D):
            assert memory[base] == 36, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x20) == enemy.script_pointer, frame
            assert word(memory, base + 0x22) == enemy.counter, frame
            assert word(memory, base + 0x24) == enemy.spawn_reload, frame
            assert word(memory, base + 0x26) == enemy.spawn_timer, frame
            assert word(memory, base + 0x28) == enemy.delay_reload, frame
            assert word(memory, base + 0x2A) == enemy.delay_timer, frame
            assert word(memory, base + 0x2C) == enemy.target_y, frame
            assert word(memory, base + 0x2E) == enemy.life, frame
        elif isinstance(enemy, Spawner875DChild):
            assert memory[base] == 37, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == (1 if enemy.state == "aimed" else 0), frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            if enemy.parent.object_slot is not None:
                assert memory[base + 0x20] == pool_index(
                    enemy.parent.object_slot), frame
            assert word(memory, base + 0x21) == enemy.delay, frame
            assert memory[base + 0x23] == enemy.oscillator, frame
            assert word(memory, base + 0x24) == enemy.animation, frame
            assert word(memory, base + 0x26) == enemy.descriptor_base, frame
            assert word(memory, base + 0x28) == enemy.parent.target_y, frame
        else:
            raise AssertionError(type(enemy).__name__)
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)

    world = M72EnemyWorld(stage=2, full_event_stream=True)
    parent = Spawner875D(world)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x875D)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)

    # В первый pass одновременно пересекаем threshold=8, создаём child и
    # проходим delay_timer RNG-ветку: порядок двух RNG становится наблюдаемым.
    parent.counter = 7
    parent.spawn_timer = 1
    parent.delay_timer = 1
    base = POOL + pool_index(parent.object_slot) * REC
    put_word(machine.mem.physical, base + 0x22, 7)
    put_word(machine.mem.physical, base + 0x26, 1)
    put_word(machine.mem.physical, base + 0x2A, 1)
    check(machine, world, 0)

    seen_wavy = seen_aimed = False
    for frame in range(1, 10):
        if frame == 2:
            child = next(enemy for enemy in world.enemies
                         if isinstance(enemy, Spawner875DChild))
            child.delay = 2
            put_word(machine.mem.physical,
                     POOL + pool_index(child.object_slot) * REC + 0x21, 2)
        elif frame == 5:
            parent.counter = 15
            put_word(machine.mem.physical,
                     POOL + pool_index(parent.object_slot) * REC + 0x22, 15)
        elif frame == 7:
            child = next(enemy for enemy in world.enemies
                         if isinstance(enemy, Spawner875DChild))
            child.x = 0x012B
            put_word(machine.mem.physical,
                     POOL + pool_index(child.object_slot) * REC + 0x02,
                     child.x)
        elif frame == 8:
            parent.life = 1
            put_word(machine.mem.physical,
                     POOL + pool_index(parent.object_slot) * REC + 0x2E, 1)

        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        machine.call(symbols["RTypeObjects_RunType"], a=37,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=36,
                     max_steps=5_000_000)
        world.update(0, 0, frame)
        seen_wavy |= any(isinstance(enemy, Spawner875DChild) and
                         enemy.state == "wavy" for enemy in world.enemies)
        seen_aimed |= any(isinstance(enemy, Spawner875DChild) and
                          enemy.state == "aimed" for enemy in world.enemies)
        check(machine, world, frame)

    assert seen_wavy and seen_aimed
    print("$875D/$8798: script thresholds, reloads и target_y exact")
    print("$8817: equal-priority delayed allocation и два RNG exact")
    print("$8861/$893E: wavy/aimed Q8, descriptor и bounds exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
