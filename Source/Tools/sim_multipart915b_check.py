#!/usr/bin/env python3
"""Machine-vs-Python oracle для `$915B/$9246…$95F1` Stage 2 chain."""
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
    ExplosionEffect, M72EnemyWorld, Multipart915BChild,
    Multipart915BParent, Radial95F1)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980
RNG = PAGE9 + 0x1990
STATE = {"first": 0, "second": 1, "main": 2,
         "hit": 3, "late": 4, "terminal": 5}


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
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert word(memory, base + 0x0A) == enemy.scheduler_priority, mark
        if isinstance(enemy, Multipart915BParent):
            assert memory[base] == 40, mark
            assert word(memory, base + 0x1D) == enemy.timer, mark
            assert word(memory, base + 0x20) == enemy.motion_root, mark
            assert word(memory, base + 0x22) == enemy.base_timer, mark
            assert word(memory, base + 0x24) == enemy.sequence, mark
            assert word(memory, base + 0x26) == enemy.priority, mark
            assert word(memory, base + 0x28) == enemy.cleanup_ordinal, mark
            expected_head = (0xFF if enemy.head is None else
                             pool_index(enemy.head.object_slot))
            assert memory[base + 0x2A] == expected_head, mark
        elif isinstance(enemy, Multipart915BChild):
            assert memory[base] == 41, mark
            assert memory[base + 0x0E] == STATE[enemy.state], mark
            assert word(memory, base + 0x16) == enemy.motion.script, mark
            assert word(memory, base + 0x18) == enemy.motion.pointer, mark
            assert memory[base + 0x1A] == enemy.motion.commands, mark
            assert word(memory, base + 0x1B) == enemy.motion.phase, mark
            if enemy.previous is None:
                previous = 0xFF
            elif hasattr(enemy.previous, "_test_pool_index"):
                previous = enemy.previous._test_pool_index
            else:
                previous = pool_index(enemy.previous.object_slot)
            assert memory[base + 0x20] == previous, mark
            assert word(memory, base + 0x21) == enemy.priority, mark
            assert word(memory, base + 0x23) == enemy.cleanup_counter, mark
            assert word(memory, base + 0x25) == enemy.pulse_timer, mark
            assert word(memory, base + 0x27) == enemy.pulse_reload, mark
            assert word(memory, base + 0x29) == enemy.pulse, mark
            assert memory[base + 0x2B] == enemy.flash_palette, mark
            assert word(memory, base + 0x2C) == enemy.hp, mark
            assert bool(memory[base + 0x01] & 2) == (
                enemy.root.controller_flash), mark
        elif isinstance(enemy, Radial95F1):
            assert memory[base] == 42, mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert memory[base + 0x11] == enemy.y_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
        elif isinstance(enemy, ExplosionEffect):
            assert memory[base] == 31, mark
            assert word(memory, base + 0x20) == enemy.sequence_pointer, mark
            assert word(memory, base + 0x22) == enemy.sequence_timer, mark
        else:
            raise AssertionError(type(enemy).__name__)
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def create_parent(machine: TSConfFT812Machine, symbols: dict[str, int]
                  ) -> tuple[M72EnemyWorld, Multipart915BParent]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    world = M72EnemyWorld(stage=2, full_event_stream=True)
    parent = Multipart915BParent(world, 0x7404)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x915B)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x7404)
    machine.call(symbols["RTypeObjects_DispatchEvent"],
                 max_steps=5_000_000)
    check(machine, world, "init")
    return world, parent


def spawn_one(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, parent: Multipart915BParent,
              mark: object) -> None:
    index = pool_index(parent.object_slot)
    parent.timer = 1
    put_word(machine.mem.physical, POOL + index * REC + 0x1D, 1)
    machine.call(symbols["RTypeObjects_RunType"], a=40,
                 max_steps=8_000_000)
    parent.update(world, 0)
    if world.pending:
        world.enemies.extend(world.pending)
        world.pending.clear()
    for enemy in world.enemies:
        if (enemy.object_slot is not None and
                not hasattr(enemy, "_test_pool_index")):
            enemy._test_pool_index = pool_index(enemy.object_slot)
    if not parent.alive:
        world.object_pool.release(parent.object_slot, parent)
        world.enemies.remove(parent)
    check(machine, world, mark)


def remove_parent(machine: TSConfFT812Machine, symbols: dict[str, int],
                  world: M72EnemyWorld, parent: Multipart915BParent) -> None:
    index = pool_index(parent.object_slot)
    machine.call(symbols["RTypeObjects_Release"], a=index,
                 max_steps=1_000_000)
    world.object_pool.release(parent.object_slot, parent)
    world.enemies.remove(parent)


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], 0)
    machine.call(symbols["RTypeObjects_RunType"], a=42,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=41,
                 max_steps=12_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=31,
                 max_steps=8_000_000)
    world.update(0, 0, frame)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    # Ускоряем только parent delay: каждый вызов остаётся буквальным `$91CC`,
    # а дочерние state machines не исполняются во время проверки списка.
    world, parent = create_parent(machine, symbols)
    for ordinal in range(22):
        spawn_one(machine, symbols, world, parent, ("chain", ordinal))
    children = [enemy for enemy in world.enemies
                if isinstance(enemy, Multipart915BChild)]
    assert [child.state for child in children] == (
        ["first", "second"] + ["main"] * 18 + ["terminal", "late"])
    assert children[0].priority == 0x201E
    assert children[-1].priority == 0x2009
    assert children[-1].cleanup_counter == 44

    # Отдельная короткая цепь проверяет newest-first pulse propagation,
    # восьмикратный radial spawn, controller flash и `$A523` cleanup.
    world, parent = create_parent(machine, symbols)
    for ordinal in range(3):
        spawn_one(machine, symbols, world, parent, ("short", ordinal))
    remove_parent(machine, symbols, world, parent)
    children = [enemy for enemy in world.enemies
                if isinstance(enemy, Multipart915BChild)]
    first, second, main_part = children
    first.pulse_timer = 1
    put_word(machine.mem.physical,
             POOL + pool_index(first.object_slot) * REC + 0x25, 1)
    world.player_native = (0x0100, 0x0080)
    machine.set_word(symbols["RTypePlayerNativeX"], 0x0100)
    machine.set_word(symbols["RTypePlayerNativeY"], 0x0080)

    for frame in (1, 2, 3):
        run_frame(machine, symbols, world, frame)
        check(machine, world, ("pulse", frame))
    radial = [enemy for enemy in world.enemies
              if isinstance(enemy, Radial95F1)]
    assert len(radial) == 8
    assert (radial[0].x_velocity, radial[0].y_velocity) == (0, 0x01E0)

    # Even VBlank выполняет Q8/animation, но намеренно не collision/bounds.
    run_frame(machine, symbols, world, 4)
    check(machine, world, "radial-q8")

    world.stage_controller_handler = 0xA3B3
    machine.set_word(symbols["RTypeWorldStageControllerHandler"], 0xA3B3)
    run_frame(machine, symbols, world, 5)
    check(machine, world, "controller-flash")
    assert main_part.root.controller_flash

    world.stage_controller_handler = 0xA523
    machine.set_word(symbols["RTypeWorldStageControllerHandler"], 0xA523)
    first.cleanup_counter = 2
    put_word(machine.mem.physical,
             POOL + pool_index(first.object_slot) * REC + 0x23, 2)
    run_frame(machine, symbols, world, 6)
    check(machine, world, "cleanup-1")
    run_frame(machine, symbols, world, 7)
    check(machine, world, "cleanup-explosion")
    assert any(isinstance(enemy, ExplosionEffect) and enemy.effect == "e7b6"
               for enemy in world.enemies)

    print("$915B/$91CC: 22 records, payload `$201E…$2009` и links exact")
    print("$9246…$957C: newest-first pulse, flash и `$A523` cleanup exact")
    print("$95A3/$95F1: 8-way ROM Q8 allocation и delayed first pass exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
