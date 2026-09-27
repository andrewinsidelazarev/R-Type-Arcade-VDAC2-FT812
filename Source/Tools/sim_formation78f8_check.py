#!/usr/bin/env python3
"""Machine-vs-Python oracle formation `$78F8/$7935/$799C…$7D45`."""
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
    Formation78F8Child, Formation78F8Parent, M72EnemyWorld,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980
RNG = PAGE9 + 0x1990

STATE = {
    "first": 0, "main": 1, "terminal": 2,
    "main_follow": 3, "terminal_follow": 4, "escape": 5,
}


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def check_child(memory: bytearray, child: Formation78F8Child,
                mark: object) -> None:
    base = POOL + pool_index(child.object_slot) * REC
    assert memory[base] == 57, mark
    assert word(memory, base + 0x02) == child.x, mark
    assert word(memory, base + 0x04) == child.y, mark
    assert word(memory, base + 0x06) == child.descriptor, mark
    assert memory[base + 0x08] == child.palette, mark
    assert word(memory, base + 0x0A) == child.priority, mark
    assert memory[base + 0x0E] == STATE[child.state], mark
    assert memory[base + 0x10] == child.x_fraction, mark
    assert memory[base + 0x11] == child.y_fraction, mark
    assert word(memory, base + 0x12) == child.x_velocity & 0xFFFF, mark
    assert word(memory, base + 0x14) == child.y_velocity & 0xFFFF, mark
    assert word(memory, base + 0x16) == child.motion.script, mark
    assert word(memory, base + 0x18) == child.motion.pointer, mark
    assert memory[base + 0x1A] == child.motion.commands, mark
    assert word(memory, base + 0x1B) == child.motion.phase, mark
    previous = 0xFF if child.previous is None else pool_index(
        child.previous.object_slot)
    assert memory[base + 0x20] == previous, mark
    assert word(memory, base + 0x22) == child.priority, mark
    assert word(memory, base + 0x24) == child.motion_timer, mark
    assert word(memory, base + 0x26) == child.delay, mark
    assert memory[base + 0x28] == child.state_flag, mark
    assert memory[base + 0x29] == child.flash_palette, mark
    assert memory[base + 0x2A] == child.flash_timer, mark
    assert memory[base + 0x2B] == child.hp, mark
    assert word(memory, base + 0x2C) == child.animation_seed, mark


def check_case(machine: TSConfFT812Machine, world: M72EnemyWorld,
               parent: Formation78F8Parent, mark: object) -> None:
    memory = machine.mem.physical
    children = list(world.pending)
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    expected = {pool_index(child.object_slot) for child in children}
    if parent.alive:
        expected.add(pool_index(parent.object_slot))
        base = POOL + pool_index(parent.object_slot) * REC
        assert memory[base] == 56, mark
        assert word(memory, base + 0x02) == parent.x, mark
        assert word(memory, base + 0x04) == parent.y, mark
        scheduler_priority = (children[0].priority
                              if children else parent.priority)
        assert word(memory, base + 0x0A) == scheduler_priority, mark
        assert word(memory, base + 0x20) == parent.motion_root, mark
        assert word(memory, base + 0x22) == parent.sequence, mark
        assert word(memory, base + 0x24) == parent.timer, mark
        assert word(memory, base + 0x26) == parent.priority, mark
    assert active == expected, (mark, active, expected)
    for child in children:
        check_child(memory, child, mark)
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int],
                command: int) -> tuple[M72EnemyWorld, Formation78F8Parent]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    world = M72EnemyWorld(stage=5, full_event_stream=True)
    parent = Formation78F8Parent(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x78F8)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=8_000_000)
    check_case(machine, world, parent, "init")
    return world, parent


def force_parent_tick(machine: TSConfFT812Machine,
                      symbols: dict[str, int],
                      parent: Formation78F8Parent) -> None:
    base = POOL + pool_index(parent.object_slot) * REC
    parent.timer = 1
    put_word(machine.mem.physical, base + 0x24, 1)
    machine.call(symbols["RTypeObjects_RunType"], a=56,
                 max_steps=500_000)


def update_one_child(machine: TSConfFT812Machine,
                     symbols: dict[str, int],
                     child: Formation78F8Child) -> None:
    index = pool_index(child.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_UpdateFormation78Child"],
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=1_000_000)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    cases = ((0x1C26, 0x4400, 0x34B6, 0xA112, 11),
             (0x1E1A, 0x4200, 0x34E2, 0xA0EA, 17))
    for command, priority, sequence, motion_root, count in cases:
        world, parent = create_case(machine, symbols, command)
        assert (parent.priority, parent.sequence,
                parent.motion_root, parent.timer) == (
                    priority, sequence, motion_root, 1)
        while parent.alive:
            force_parent_tick(machine, symbols, parent)
            parent.update(world, 0)
            check_case(machine, world, parent,
                       ("spawn", command, len(world.pending)))
        spawned = list(world.pending)
        assert len(spawned) == count
        assert (spawned[0].state, spawned[0].hp,
                world.resources.types[spawned[0].palette],
                spawned[0].priority) == (
                    "first", 0x0E, 0x25, priority)
        assert (spawned[-1].state, spawned[-1].hp,
                world.resources.types[spawned[-1].palette]) == (
                    "terminal", 6, 0x25)

    # Два первых child-а достаточны для обеих link-веток: flag2 копирует
    # delay+4/commands=3, flag1 включает escape velocity из `$8FD0`.
    world, parent = create_case(machine, symbols, 0x1C26)
    force_parent_tick(machine, symbols, parent)
    parent.update(world, 0)
    first = world.pending[0]
    force_parent_tick(machine, symbols, parent)
    parent.update(world, 0)
    second = world.pending[1]
    assert isinstance(first, Formation78F8Child)
    assert isinstance(second, Formation78F8Child)

    first.state_flag = 2
    first.delay = 7
    first_base = POOL + pool_index(first.object_slot) * REC
    machine.mem.physical[first_base + 0x28] = 2
    put_word(machine.mem.physical, first_base + 0x26, 7)
    machine.set_word(symbols["FrameCounter"], 0)
    update_one_child(machine, symbols, second)
    second.update(world, 0)
    check_child(machine.mem.physical, second, "chain")
    assert (second.state_flag, second.delay, second.motion.commands) == (
        2, 11, 3)

    second.state_flag = 0
    second.delay = 0
    first.state_flag = 1
    second_base = POOL + pool_index(second.object_slot) * REC
    machine.mem.physical[second_base + 0x28] = 0
    put_word(machine.mem.physical, second_base + 0x26, 0)
    machine.mem.physical[first_base + 0x28] = 1
    update_one_child(machine, symbols, second)
    second.update(world, 0)
    check_child(machine.mem.physical, second, "escape-entry")
    assert (second.state, second.state_flag,
            second.x_velocity, second.y_velocity) == (
                "escape", 1, -0x00D0, 0x0200)
    x_before, y_before = second.x, second.y
    update_one_child(machine, symbols, second)
    second.update(world, 0)
    check_child(machine.mem.physical, second, "escape-q8")
    assert (second.x, second.x_fraction,
            second.y, second.y_fraction) == (
                x_before - 1, 0x30, y_before + 2, 0)

    print("$78F8/$7935: exact `$4400/$4200` roots и 11/17 linked parts")
    print("$799C/$7A1E/$7AD9: resources, HP, motion roots и priorities exact")
    print("$7A58/$7B13/$7C9E: flag2 delay-chain и flag1 escape Q8 exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
