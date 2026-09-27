#!/usr/bin/env python3
"""Покадровый oracle для `$60BA/$663E/$6715/$68EE`."""
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
    Handler60BA,
    Handler60BAChild,
    Handler60BAProjectile,
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


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


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
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (
        frame, active,
        {index: type(enemy).__name__ for index, enemy in expected.items()})

    states = {
        "610d": 0, "61e3": 1, "652f": 2, "62bd": 3,
        "6243": 4, "631b": 5, "6392": 6, "6374": 7,
        "638c": 8, "6380": 9, "6459": 10, "657c": 11,
    }
    next_states = {"6243": 4, "631b": 5}
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, Handler60BA):
            assert memory[base] == 21, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, (
                frame, "parent descriptor", hex(word(memory, base + 0x06)),
                hex(enemy.descriptor), enemy.state, hex(enemy.timer),
                hex(enemy.landing_table), "target_state/timer/table",
                memory[base + 0x0E], hex(word(memory, base + 0x27)),
                hex(word(memory, base + 0x2C)))
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert memory[base + 0x20] == enemy.phase, frame
            assert word(memory, base + 0x22) == enemy.fire_reload, frame
            assert word(memory, base + 0x24) == enemy.fire_counter, frame
            assert bool(memory[base + 0x26]) == enemy.facing_right, frame
            assert word(memory, base + 0x27) == enemy.timer, frame
            assert memory[base + 0x29] == next_states[enemy.next_state], frame
            assert word(memory, base + 0x2A) == enemy.next_timer, frame
            assert word(memory, base + 0x2C) == enemy.landing_table, frame
            assert memory[base + 0x2E] == enemy.flash_palette, frame
            assert memory[base + 0x2F] == enemy.flash_timer, frame
            assert memory[base + 0x0E] == states[enemy.state], frame
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, frame
        elif isinstance(enemy, Handler60BAProjectile):
            state = (0 if enemy.state == "flight" else
                     (3 if enemy.explosion_initialized else 2))
            assert memory[base] == 22, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == state, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            if state == 3:
                assert word(memory, base + 0x20) == enemy.sequence_pointer, frame
                assert word(memory, base + 0x22) == enemy.sequence_timer, frame
        elif isinstance(enemy, Handler60BAChild):
            state = (2 if enemy.explosion_pending else
                     (3 if enemy.exploding else (1 if enemy.homing else 0)))
            assert memory[base] == 23, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == state, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            if state < 2:
                assert memory[base + 0x20] == enemy.direction, frame
                assert word(memory, base + 0x22) == enemy.turn_reload, frame
                assert word(memory, base + 0x24) == enemy.move_timer, frame
                assert word(memory, base + 0x26) == enemy.life_timer, frame
                assert word(memory, base + 0x2A) == enemy.overlay_descriptor, frame
                assert word(memory, base + 0x2C) == enemy.overlay_x, frame
                assert word(memory, base + 0x2E) == enemy.overlay_y, frame
            elif state == 3:
                assert word(memory, base + 0x20) == enemy.sequence_pointer, frame
                assert word(memory, base + 0x22) == enemy.sequence_timer, frame
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

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    command = 0x2C07
    parent = Handler60BA(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x60BA)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check_frame(machine, world, 0)

    seen_shot = False
    seen_shot_explosion = False
    seen_children = False
    seen_homing = False
    seen_child_explosion = False
    for frame in range(1, 131):
        # Frame 1 с solid map переводит `$610D` в первую landing-анимацию.
        # Frame 5 сталкивает уже летящий `$66C8` с terrain. Frame 104 делает
        # то же после подтверждённого перехода спутников в homing.
        solid = frame in (1, 5, 104)
        fill_foreground(machine, solid)
        terrain = (lambda _x, _y, value=solid:
                   0x0000 if value else 0x0FA0)

        if frame == 2:
            # Гарантировать единственный компактный `$663E` equality-shot.
            parent.x = 0x0200
            parent.y = world.player_native[1]
            parent.facing_right = False
            parent.fire_counter = parent.fire_reload - 1
            base = POOL + pool_index(parent.object_slot) * REC
            put_word(machine.mem.physical, base + 0x02, parent.x)
            put_word(machine.mem.physical, base + 0x04, parent.y)
            machine.mem.physical[base + 0x26] = 0
            put_word(machine.mem.physical, base + 0x24, parent.fire_counter)
        elif frame == 3:
            # После первого выстрела исключить дополнительные projectile,
            # не изменяя уже проверенный reload/equality branch.
            parent.fire_reload = 0xFFFF
            base = POOL + pool_index(parent.object_slot) * REC
            put_word(machine.mem.physical, base + 0x22, parent.fire_reload)

        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        machine.call(symbols["RTypeObjects_RunType"], a=23,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=22,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=21,
                     max_steps=5_000_000)
        world.update(0, 0, frame, terrain_code=terrain)

        seen_shot |= any(isinstance(enemy, Handler60BAProjectile)
                         for enemy in world.enemies)
        seen_shot_explosion |= any(
            isinstance(enemy, Handler60BAProjectile) and
            enemy.state == "explosion"
            for enemy in world.enemies)
        seen_children |= any(isinstance(enemy, Handler60BAChild)
                             for enemy in world.enemies)
        seen_homing |= any(isinstance(enemy, Handler60BAChild) and enemy.homing
                           for enemy in world.enemies)
        seen_child_explosion |= any(
            isinstance(enemy, Handler60BAChild) and
            (enemy.explosion_pending or enemy.exploding)
            for enemy in world.enemies)
        check_frame(machine, world, frame)

    assert (seen_shot and seen_shot_explosion and seen_children and
            seen_homing and seen_child_explosion), (
                seen_shot, seen_shot_explosion, seen_children,
                seen_homing, seen_child_explosion)
    print("$60BA/$610D…$6243: parent states, timers, RNG и descriptors exact")
    print("$663E/$66C8->$E7AE: delayed shot, Q8 и in-place explosion exact")
    print("$6715/$67D5: 4-child FIFO, vectors и slot residues exact")
    print("$687D/$68EE: slot-AX homing, turn и overlay geometry exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
