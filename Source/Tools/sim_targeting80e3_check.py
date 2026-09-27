#!/usr/bin/env python3
"""Oracle мини-босса `$80E3` и attack children `$83DF/$842C`."""
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
    M72EnemyWorld,
    PlayerTargeting80E3,
    Targeting80E3AttackFlash,
    Targeting80E3Projectile,
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


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // 0x40


def check_frame(machine: TSConfFT812Machine, world: M72EnemyWorld,
                frame: int) -> None:
    memory = machine.mem.physical
    expected = {
        pool_index(enemy.object_slot): enemy
        for enemy in world.enemies if enemy.object_slot is not None
    }
    active = {
        index for index in range(2, 96)
        if memory[POOL + index * REC] != 0
    }
    assert active == set(expected), (
        frame, active,
        {index: type(enemy).__name__ for index, enemy in expected.items()})

    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, PlayerTargeting80E3):
            assert memory[base] == 11, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert memory[base + 0x0E] == (1 if enemy.state == "attack" else 0)
            assert word(memory, base + 0x20) == enemy.target_x, frame
            assert word(memory, base + 0x22) == enemy.target_y, frame
            assert word(memory, base + 0x24) == enemy.previous_target_x, frame
            assert word(memory, base + 0x26) == enemy.previous_target_y, frame
            assert word(memory, base + 0x28) == enemy.retarget_counter, frame
            assert memory[base + 0x2A] == enemy.animation_offset, frame
            assert memory[base + 0x2B] == enemy.flash_palette, frame
            assert word(memory, base + 0x2C) == enemy.attack_delay, frame
            assert word(memory, base + 0x2E) == enemy.activation_timer, frame
            assert word(memory, base + 0x30) == enemy.attack_timer, frame
            assert word(memory, base + 0x32) == enemy.flash_timer, frame
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, frame
        elif isinstance(enemy, Targeting80E3AttackFlash):
            assert memory[base] == 12, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert word(memory, base + 0x20) == enemy.descriptor_root, frame
            assert word(memory, base + 0x22) == enemy.sequence_timer, frame
            assert word(memory, base + 0x24) == enemy.sequence_delay, frame
            assert bool(memory[base + 0x0F]) == enemy.visible, frame
        elif isinstance(enemy, Targeting80E3Projectile):
            assert memory[base] == 13, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
        else:
            raise AssertionError(type(enemy).__name__)

    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    machine.call(symbols["RTypeWorld_ClearMaps"], max_steps=2_000_000)

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    command = 0x9405
    root = PlayerTargeting80E3(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(root, slot)
    world.enemies = [root]
    world.event_pointer = world.event_last

    machine.set_word(symbols["RTypeWorldLastHandler"], 0x80E3)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check_frame(machine, world, 0)

    seen: set[type[object]] = {PlayerTargeting80E3}
    for frame in range(1, 56):
        machine.set_word(symbols["FrameCounter"], frame)
        # Эти три calls — ровно их priority order `$1F00,$2000,$A000`.
        for object_type in (12, 13, 11):
            machine.call(symbols["RTypeObjects_RunType"], a=object_type,
                         max_steps=5_000_000)
        world.update(0, 0, frame)
        seen.update(type(enemy) for enemy in world.enemies)
        check_frame(machine, world, frame)

    assert Targeting80E3Projectile in seen
    assert Targeting80E3AttackFlash in seen
    print("$80E3 init/first retarget: RNG, target и Q8 velocities exact")
    print("$8138: FG/BG probes, tracking animation и attack delay exact")
    print("$82D6: 31-count lunge и two-child FIFO allocation exact")
    print("$83DF/$842C: launch sequence/projectile lifetime exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
