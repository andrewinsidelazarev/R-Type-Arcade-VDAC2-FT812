#!/usr/bin/env python3
"""Machine-vs-Python oracle `$5CEA/$5D2D/$5D9A` и общего `$E6AB`."""
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
    Enemy5CEA, Handler5CEAShot, M72EnemyWorld)
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
        if isinstance(enemy, Enemy5CEA):
            assert memory[base] == 49, mark
            assert word(memory, base + 0x0A) == 0x8020, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x28) == enemy.random_delay, mark
            assert word(memory, base + 0x30) == enemy.fire_reload, mark
            assert word(memory, base + 0x32) == enemy.shot_velocity & 0xFFFF, mark
            assert word(memory, base + 0x34) == enemy.fire_counter, mark
        elif isinstance(enemy, Handler5CEAShot):
            assert memory[base] == 47, mark
            assert word(memory, base + 0x0A) == 0x6000, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
        else:
            raise AssertionError((mark, type(enemy).__name__))
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
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
    parent = Enemy5CEA(world, 0x4C0A)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x5CEA)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x4C0A)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, "init")
    assert (parent.x, parent.y, parent.x_velocity, parent.shot_velocity,
            parent.fire_reload, parent.random_delay) == (
                0x02C8, 0x00E0, -0x0200, -0x0600, 0x30, 0x34)

    # Доводим countdown до последнего pass без 47 пустых интерпретаций; само
    # начальное значение `$0030` и сохранённый RNG side effect уже проверены.
    parent.fire_counter = 1
    base = POOL + pool_index(parent.object_slot) * REC
    put_word(machine.mem.physical, base + 0x34, 1)
    machine.set_word(symbols["FrameCounter"], 0)
    machine.call(symbols["RTypeObjects_RunType"], a=47,
                 max_steps=5_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=49,
                 max_steps=8_000_000)
    world.update(0, 0, 0)
    check(machine, world, "spawn")
    shots = [enemy for enemy in world.enemies
             if isinstance(enemy, Handler5CEAShot)]
    assert len(shots) == 1
    shot = shots[0]
    assert (shot.x, shot.y, shot.x_velocity) == (
        parent.x, parent.y, -0x0600)
    assert parent.fire_counter == 0x30

    # На следующем кадре child первым проходит Q8 и paired `$84CE` stream.
    machine.set_word(symbols["FrameCounter"], 1)
    machine.call(symbols["RTypeObjects_RunType"], a=47,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=49,
                 max_steps=8_000_000)
    world.update(0, 0, 1)
    check(machine, world, "child-first-pass")

    # Global cleanup должен снять оба независимых resources `$02/$0E`.
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    machine.call(symbols["RTypeObjects_RunType"], a=47,
                 max_steps=5_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=49,
                 max_steps=5_000_000)
    world.update(0, 0, 2)
    check(machine, world, "cleanup")
    assert parent.object_slot is None and shot.object_slot is None

    print("$5CEA init: Y/difficulty records, RNG delay и `$0E` resource exact")
    print("$5D2D/$5D9A: 8 phases, `$0030` cadence и child allocation exact")
    print("$E6AB: priority `$6000`, Q8/paired animation и cleanup exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
