#!/usr/bin/env python3
"""Oracle four-probe seeker `$897E/$89B0/$8AEE`."""
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
    EnemyProjectile, M72EnemyWorld, TerrainAware897E,
)
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


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // 0x40


def fill_foreground(machine: TSConfFT812Machine, solid: bool) -> None:
    payload = (bytes(0x4000) if solid else
               bytes((0xA0, 0x0F, 0, 0)) * (0x4000 // 4))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = payload


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          frame: int) -> None:
    memory = machine.mem.physical
    expected = {
        pool_index(enemy.object_slot): enemy
        for enemy in world.enemies if enemy.object_slot is not None
    }
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC]}
    assert active == set(expected), (
        frame, active,
        {i: type(enemy).__name__ for i, enemy in expected.items()})
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, TerrainAware897E):
            assert memory[base] == 16, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x20) == enemy.fire_counter, frame
            assert word(memory, base + 0x22) == enemy.fire_a, frame
            assert word(memory, base + 0x24) == enemy.fire_b, frame
            assert word(memory, base + 0x26) == enemy.projectile_script, frame
            assert memory[base + 0x2C] == enemy.direction_flags, frame
            assert word(memory, base + 0x2D) == enemy.direction_counter, frame
            assert word(memory, base + 0x2F) == enemy.direction_mask, frame
            assert bool(memory[base + 0x31]) == enemy.reverse_vertical, frame
            assert word(memory, base + 0x32) == enemy.escape_counter, frame
        elif isinstance(enemy, EnemyProjectile):
            assert memory[base] == 9, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert word(memory, base + 0x2C) == enemy.phase_seed, frame
            assert word(memory, base + 0x2E) == enemy.burst_timer, frame
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
    machine.call(symbols["RTypeWorld_ClearMaps"], max_steps=2_000_000)

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    command = 0x1824                    # nonzero common-fire table
    seeker = TerrainAware897E(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(seeker, slot)
    world.enemies = [seeker]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x897E)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, 0)

    seen_reverse = False
    seen_projectile = False
    for frame in range(1, 126):
        # Один fully blocked pass переводит `$89B0->$8AEE`; следующая пустая
        # карта проверяет сокращение escape counter через unselected branch.
        solid = frame == 20
        fill_foreground(machine, solid)
        terrain = (lambda _x, _y, value=solid:
                   0x0000 if value else 0x0FFF)
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], frame & 1)
        machine.call(symbols["RTypeObjects_RunType"], a=16,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=9,
                     max_steps=5_000_000)
        world.update(0, frame & 1, frame, terrain_code=terrain)
        seen_reverse |= seeker.reverse_vertical
        seen_projectile |= any(isinstance(enemy, EnemyProjectile)
                               for enemy in world.enemies)
        check(machine, world, frame)

    assert seen_reverse and seen_projectile
    print("$897E init: fire table/RNG/mask и FIFO fractions exact")
    print("$89B0: four probes, Q8 integration и descriptor cadence exact")
    print("$8AEE: blocked/reverse/escape-counter transitions exact")
    print("Terrain seeker -> `$F63A/$E601` same-pass projectile exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
