#!/usr/bin/env python3
"""Oracle parent `$74B4` и ballistic child `$780E/$E7AE`."""
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
    LargeTerrain74B4,
    LargeTerrainChild780E,
    M72EnemyWorld,
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
        if isinstance(enemy, LargeTerrain74B4):
            states = {
                "bootstrap": 0, "move": 1, "wait": 2,
                "open": 3, "shoot": 4, "close": 5,
            }
            assert memory[base] == 14, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == states[enemy.state], frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x20) == enemy.cooldown_reload, frame
            assert word(memory, base + 0x22) == enemy.cooldown, frame
            assert word(memory, base + 0x24) == enemy.state_timer, frame
            assert word(memory, base + 0x26) == enemy.animation, frame
            assert word(memory, base + 0x28) == enemy.open_descriptor_base, frame
            assert word(memory, base + 0x2A) == enemy.shoot_descriptor_base, frame
            assert memory[base + 0x2C] == enemy.flash_palette, frame
            assert memory[base + 0x2D] == enemy.flash_timer, frame
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, frame
        elif isinstance(enemy, LargeTerrainChild780E):
            states = {"rise": 0, "fall": 1, "explosion": 2}
            assert memory[base] == 15, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == states[enemy.ballistic_state], (
                frame, index, memory[base + 0x0E], enemy.ballistic_state,
                word(memory, base + 0x02), enemy.x,
                word(memory, base + 0x04), enemy.y)
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            if enemy.ballistic_state == "explosion":
                assert word(memory, base + 0x20) == enemy.explosion_pointer, frame
                assert word(memory, base + 0x22) == enemy.explosion_timer, frame
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
    command = 0x5408
    parent = LargeTerrain74B4(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last

    machine.set_word(symbols["RTypeWorldLastHandler"], 0x74B4)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check_frame(machine, world, 0)

    seen_child = False
    seen_explosion = False
    seen_close = False
    for frame in range(1, 401):
        # Первый child рождается на 225-м pass. Solid только в этот VBlank:
        # parent в shoot terrain не проверяет, а новый `$780E` сразу входит
        # в in-place `$E7AE` и затем проигрывает весь explosion stream.
        solid = frame == 225
        fill_foreground(machine, solid)
        terrain_code = (lambda _x, _y, value=solid:
                        0x0000 if value else 0x0FFF)
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        # `$8230` parent раньше `$C000` child: newborn исполняется в тот же pass.
        machine.call(symbols["RTypeObjects_RunType"], a=14,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=15,
                     max_steps=5_000_000)
        world.update(0, 0, frame, terrain_code=terrain_code)
        seen_child |= any(isinstance(enemy, LargeTerrainChild780E)
                          for enemy in world.enemies)
        seen_explosion |= any(
            isinstance(enemy, LargeTerrainChild780E) and
            enemy.ballistic_state == "explosion"
            for enemy in world.enemies)
        seen_close |= parent.state == "close"
        check_frame(machine, world, frame)

    assert seen_child and seen_explosion and seen_close
    print("$74B4/$7607: bootstrap/move/wait/direction/cooldown exact")
    print("$759F/$7654/$76AC/$7719: open/shoot/close trace exact")
    print("$77C1/$780E: same-pass child FIFO, RNG и Q8 ballistic exact")
    print("$7875->$E7AE: in-place resource swap/explosion stream exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
