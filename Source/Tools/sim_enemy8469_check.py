#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle Stage 7 `$8469/$8490`."""
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

from rtype_port.enemies import Enemy8469, M72EnemyWorld  # noqa: E402
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
        assert isinstance(enemy, Enemy8469), (mark, type(enemy).__name__)
        base = POOL + index * REC
        assert memory[base] == 46, mark
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert word(memory, base + 0x0A) == 0x8020, mark
        assert memory[base + 0x10] == enemy.x_fraction, mark
        assert memory[base + 0x11] == enemy.y_fraction, mark
        assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
        assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
        assert word(memory, base + 0x20) == enemy.fire_counter, mark
        assert word(memory, base + 0x22) == enemy.fire_a, mark
        assert word(memory, base + 0x24) == enemy.fire_b, mark
        assert word(memory, base + 0x26) == enemy.projectile_script, mark
        assert word(memory, base + 0x28) == enemy.pause_timer, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int]
                ) -> tuple[M72EnemyWorld, Enemy8469]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)
    world = M72EnemyWorld(stage=7, full_event_stream=True)
    enemy = Enemy8469(world, 0x483A)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x8469)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x483A)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, "init")
    assert (enemy.x, enemy.y, enemy.fire_a, enemy.fire_b,
            enemy.projectile_script, enemy.fire_counter) == (
                0x02C8, 0x00E0, 0x0080, 0x00C0, 0x9010, 0x0010)
    return world, enemy


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int,
              terrain_code: int, delta: int = 0) -> None:
    fill_terrain(machine, terrain_code)
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.call(symbols["RTypeObjects_RunType"], a=46,
                 max_steps=8_000_000)
    world.update(0, delta, frame,
                 terrain_code=lambda _x, _y: terrain_code)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    # Solid слева останавливает X и на чётном кадре выбирает движение вниз.
    # Первый свободный pass уже интегрирует Y, но только уменьшает pause 8->7.
    world, enemy = create_case(machine, symbols)
    run_frame(machine, symbols, world, 0, 0x0001)
    check(machine, world, "solid-entry")
    assert (enemy.x, enemy.x_velocity, enemy.y_velocity,
            enemy.pause_timer) == (0x02C6, 0, -0x0100, 8)
    run_frame(machine, symbols, world, 1, 0x0FFF)
    check(machine, world, "first-free")
    assert (enemy.x, enemy.y, enemy.x_velocity, enemy.y_velocity,
            enemy.pause_timer) == (0x02C6, 0x00DF, 0, -0x0100, 7)

    # Solid vertical probe `$y-$18` отражает signed Q8 скорость, не меняя
    # восьмикадровый pause counter.
    world, enemy = create_case(machine, symbols)
    run_frame(machine, symbols, world, 0, 0x0001)
    run_frame(machine, symbols, world, 1, 0x0001)
    check(machine, world, "vertical-bounce")
    assert enemy.y_velocity == 0x0100 and enemy.pause_timer == 8

    # После стены ровно восемь свободных pass доводят timer до нуля; только
    # девятый восстанавливает `vx=-$0200, vy=0`.
    for frame in range(2, 11):
        run_frame(machine, symbols, world, frame, 0x0FFF)
        check(machine, world, ("pause", frame))
    assert enemy.pause_timer == 0
    assert enemy.x_velocity == -0x0200 and enemy.y_velocity == 0

    # Natural left bound освобождает `$18`; общий cleanup делает то же без
    # исполнения terrain state-machine.
    world, enemy = create_case(machine, symbols)
    enemy.x = 0x0140
    base = POOL + pool_index(enemy.object_slot) * REC
    put_word(machine.mem.physical, base + 0x02, enemy.x)
    run_frame(machine, symbols, world, 0, 0x0FFF)
    check(machine, world, "left-bound")
    assert not enemy.alive and enemy.object_slot is None

    world, enemy = create_case(machine, symbols)
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run_frame(machine, symbols, world, 0, 0x0FFF)
    check(machine, world, "cleanup")
    assert not enemy.alive and enemy.object_slot is None

    print("$8469 init: Y/fire tables, RNG mask и priority `$8020` exact")
    print("$8490: wall entry, vertical reflection и 8-pass pause exact")
    print("$8490 bounds/cleanup: resource `$18` и FIFO release exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
