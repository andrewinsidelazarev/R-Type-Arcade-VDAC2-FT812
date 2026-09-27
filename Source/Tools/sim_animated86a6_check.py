#!/usr/bin/env python3
"""Oracle stationary shooter `$86A6/$86D3/$86EA`."""
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

from rtype_port.enemies import Animated86A6, EnemyProjectile, M72EnemyWorld  # noqa: E402
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


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // 0x40


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          frame: int) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC]}
    assert active == set(expected), frame
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, Animated86A6):
            assert memory[base] == 17, frame
            assert word(memory, base + 2) == enemy.x, frame
            assert word(memory, base + 4) == enemy.y, frame
            assert word(memory, base + 6) == enemy.descriptor, frame
            assert memory[base + 8] == enemy.palette, frame
            assert word(memory, base + 0x20) == enemy.fire_counter, frame
            assert word(memory, base + 0x22) == enemy.fire_a, frame
            assert word(memory, base + 0x24) == enemy.fire_b, frame
            assert word(memory, base + 0x26) == enemy.projectile_script, frame
            assert word(memory, base + 0x2C) == enemy.descriptor_base, frame
        elif isinstance(enemy, EnemyProjectile):
            assert memory[base] == 9, frame
            assert word(memory, base + 2) == enemy.x, frame
            assert word(memory, base + 4) == enemy.y, frame
            assert word(memory, base + 6) == enemy.descriptor, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
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
    command = 0x2811
    shooter = Animated86A6(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(shooter, slot)
    world.enemies = [shooter]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x86A6)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check(machine, world, 0)

    # Common-fire уже отдельно проверен естественными длинными trace. Здесь
    # подводим оба oracle к equality branch, чтобы компактно проверить связь
    # `$86EA->$F63A->$E601`, сохранив точное состояние после initializer RNG.
    shooter.fire_counter = shooter.fire_a - 1
    base = POOL + 2 * REC
    machine.mem.physical[base + 0x20:base + 0x22] = (
        shooter.fire_counter.to_bytes(2, "little"))

    seen_projectile = False
    for frame in range(1, 41):
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], frame & 1)
        machine.call(symbols["RTypeObjects_RunType"], a=17,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=9,
                     max_steps=5_000_000)
        world.update(0, frame & 1, frame)
        seen_projectile |= any(isinstance(enemy, EnemyProjectile)
                               for enemy in world.enemies)
        check(machine, world, frame)

    assert seen_projectile
    print("$86A6 init: Y table/fire table/RNG/resource exact")
    print("$86D3: 16-VBlank direction descriptor cadence exact")
    print("$86EA->$F63A/$E601 projectile path exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
