#!/usr/bin/env python3
"""Покадровый oracle для Stage 2 handler `$6F89/$6FD0/$7048/$7106`."""
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
    Enemy6F89, M72EnemyWorld, _direction_offset)
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


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          enemy: Enemy6F89, frame: tuple[int, int]) -> None:
    memory = machine.mem.physical
    if enemy.alive:
        index = pool_index(enemy.object_slot)
        base = POOL + index * REC
        active = {i for i in range(2, 96)
                  if memory[POOL + i * REC] != 0}
        assert active == {index}, frame
        assert memory[base] == 35, frame
        assert word(memory, base + 0x02) == enemy.x, frame
        assert word(memory, base + 0x04) == enemy.y, frame
        assert word(memory, base + 0x06) == enemy.descriptor, frame
        assert memory[base + 0x08] == enemy.palette, frame
        assert memory[base + 0x0E] == (0 if enemy.state == "waiting" else 1), frame
        assert memory[base + 0x10] == enemy.x_fraction, frame
        assert memory[base + 0x11] == enemy.y_fraction, frame
        assert word(memory, base + 0x20) == enemy.primary_x & 0xFFFF, frame
        assert word(memory, base + 0x22) == enemy.primary_y & 0xFFFF, frame
        assert word(memory, base + 0x24) == enemy.secondary_x & 0xFFFF, frame
        assert word(memory, base + 0x26) == enemy.secondary_y & 0xFFFF, frame
        assert word(memory, base + 0x28) == enemy.descriptor_table, frame
        assert word(memory, base + 0x2A) == enemy.target_direction, frame
        assert word(memory, base + 0x2C) == enemy.wait_value, frame
        assert word(memory, base + 0x2E) == enemy.animation, frame
        assert memory[base + 0x30] == enemy.flash_palette, frame
        assert memory[base + 0x31] == enemy.flash_timer, frame
        assert word(memory, base + 0x32) == enemy.previous_damage, frame
        assert word(memory, base + 0x34) == enemy.hp, frame
        assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, frame
    else:
        assert not any(memory[POOL + i * REC] for i in range(2, 96)), frame
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame


def matching_player(enemy: Enemy6F89) -> tuple[int, int]:
    for dx, dy in ((-0x100, -0x100), (0, -0x100), (0x100, -0x100),
                   (-0x100, 0), (0x100, 0), (-0x100, 0x100),
                   (0, 0x100), (0x100, 0x100)):
        target = ((enemy.x + dx) & 0xFFFF, (enemy.y + dy) & 0xFFFF)
        if _direction_offset(enemy.x, enemy.y, *target) == enemy.target_direction:
            return target
    raise AssertionError(hex(enemy.target_direction))


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)

    for variant in range(4):
        machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
        command = variant | (variant << 2)
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        enemy = Enemy6F89(world, command)
        slot = world.object_pool.take()
        assert slot is not None
        world.object_pool.bind(enemy, slot)
        world.enemies = [enemy]
        world.event_pointer = world.event_last
        machine.set_word(symbols["RTypeWorldLastHandler"], 0x6F89)
        machine.set_word(symbols["RTypeWorldLastCommand"], command)
        machine.call(symbols["RTypeObjects_DispatchEvent"],
                     max_steps=5_000_000)

        if variant == 0:
            player = matching_player(enemy)
        else:
            enemy.wait_value = 2
            put_word(machine.mem.physical, POOL + 2 * REC + 0x2C, 2)
            player = world.player_native
        world.player_native = player
        machine.set_word(symbols["RTypePlayerNativeX"], player[0])
        machine.set_word(symbols["RTypePlayerNativeY"], player[1])
        check(machine, world, enemy, (variant, 0))

        terrain_value = 0x0FA0
        for frame in range(1, 10):
            if frame == 4:
                terrain_value = 0x0100
            if frame == 5:
                enemy.flash_timer = 3
                base = POOL + pool_index(enemy.object_slot) * REC
                machine.mem.physical[base + 0x31] = 3
            if frame == 8:
                enemy.x = 0x012B
                base = POOL + pool_index(enemy.object_slot) * REC
                put_word(machine.mem.physical, base + 0x02, enemy.x)
            cell = (terrain_value & 0xFFFF).to_bytes(2, "little") + b"\0\0"
            machine.mem.physical[PAGE7:PAGE7 + 0x4000] = (
                cell * (0x4000 // 4))
            machine.set_word(symbols["FrameCounter"], frame)
            machine.set_word(symbols["RTypeWorldFgDelta"], 0)
            machine.call(symbols["RTypeObjects_RunType"], a=35,
                         max_steps=5_000_000)
            world.update(0, 0, frame,
                         terrain_code=lambda _x, _y, v=terrain_value: v)
            check(machine, world, enemy, (variant, frame))
            if not enemy.alive:
                break

    print("$6F89: 4 ROM records, directional/countdown wait exact")
    print("$7048/$7106: primary/secondary Q8, animation и flash freeze exact")
    print("$1D6B cleanup: normal+flash resources и FIFO release exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
