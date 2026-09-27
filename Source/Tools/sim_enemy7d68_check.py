#!/usr/bin/env python3
"""Покадровый oracle для parent `$7D68…$8035` и child `$8D85…$8E15`."""
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

from rtype_port.enemies import Child8D85, Enemy7D68, M72EnemyWorld  # noqa: E402
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980
RNG = PAGE9 + 0x1990
STATE_7D = {"approach": 0, "rise": 1, "open": 2,
            "hold": 3, "close": 4, "retreat": 5}
STATE_8D = {"scripted": 0, "terminal": 1, "active": 2}


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
        if isinstance(enemy, Enemy7D68):
            assert memory[base] == 38, mark
            assert memory[base + 0x0E] == STATE_7D[enemy.state], mark
            assert word(memory, base + 0x1D) == enemy.timer, mark
            assert word(memory, base + 0x20) == enemy.variant, mark
            assert word(memory, base + 0x22) == enemy.animation_seed, (
                mark, "animation_seed", hex(word(memory, base + 0x22)),
                hex(enemy.animation_seed), tuple(memory[RNG:RNG + 3]))
            assert memory[base + 0x24] == enemy.flash_palette, mark
            assert memory[base + 0x25] == enemy.flash_timer, mark
            assert word(memory, base + 0x26) == enemy.hp, mark
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
        elif isinstance(enemy, Child8D85):
            assert memory[base] == 39, mark
            assert memory[base + 0x0E] == STATE_8D[enemy.state], mark
            assert memory[base + 0x10] == enemy.x_fraction, mark
            assert memory[base + 0x11] == enemy.y_fraction, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
            assert word(memory, base + 0x16) == enemy.motion.script, mark
            assert word(memory, base + 0x18) == enemy.motion.pointer, mark
            assert memory[base + 0x1A] == enemy.motion.commands, mark
            assert word(memory, base + 0x1B) == enemy.motion.phase, mark
            assert word(memory, base + 0x1D) == enemy.timer, mark
            assert word(memory, base + 0x20) == enemy.fire_counter, mark
            assert word(memory, base + 0x22) == enemy.fire_a, mark
            assert word(memory, base + 0x24) == enemy.fire_b, mark
            assert word(memory, base + 0x26) == enemy.projectile_script, mark
            assert word(memory, base + 0x28) == enemy.animation, mark
            assert bool(memory[base + 0x2A]) == enemy.target_player_next, mark
            assert bool(memory[base + 0x2B]) == enemy.fixed_descriptor, mark
            assert memory[base + 0x2C] == enemy.flash_palette, mark
            assert memory[base + 0x2D] == enemy.flash_timer, mark
            assert word(memory, base + 0x2E) == enemy.hp, mark
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
        else:
            raise AssertionError(type(enemy).__name__)
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def sync_parent(machine: TSConfFT812Machine, parent: Enemy7D68) -> None:
    base = POOL + pool_index(parent.object_slot) * REC
    machine.mem.physical[base + 0x0E] = STATE_7D[parent.state]
    put_word(machine.mem.physical, base + 0x02, parent.x)
    put_word(machine.mem.physical, base + 0x04, parent.y)
    put_word(machine.mem.physical, base + 0x1D, parent.timer)


def sync_child(machine: TSConfFT812Machine, child: Child8D85) -> None:
    base = POOL + pool_index(child.object_slot) * REC
    machine.mem.physical[base + 0x0E] = STATE_8D[child.state]
    put_word(machine.mem.physical, base + 0x02, child.x)
    put_word(machine.mem.physical, base + 0x04, child.y)
    put_word(machine.mem.physical, base + 0x12, child.x_velocity)
    put_word(machine.mem.physical, base + 0x14, child.y_velocity)
    put_word(machine.mem.physical, base + 0x1D, child.timer)
    put_word(machine.mem.physical, base + 0x2E, child.hp)


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: Enemy7D68 | Child8D85, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    entry = ("RTypeObjectBank3_DamageEnemy7D68"
             if isinstance(enemy, Enemy7D68)
             else "RTypeObjectBank3_DamageChild8D85")
    machine.call(symbols[entry], a=amount, max_steps=2_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=1_000_000)


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int, delta: int = 0) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.call(symbols["RTypeObjects_RunType"], a=39,
                 max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=38,
                 max_steps=8_000_000)
    world.update(0, delta, frame)


def create_case(machine: TSConfFT812Machine, symbols: dict[str, int],
                variant: int, timer: int) -> tuple[M72EnemyWorld,
                                                   Enemy7D68, Child8D85]:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    world = M72EnemyWorld(stage=2, full_event_stream=True)
    machine.set_word(symbols["FrameCounter"], world.frame_counter)
    parent = Enemy7D68(world, variant)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x7D68)
    machine.set_word(symbols["RTypeWorldLastCommand"], variant)
    machine.call(symbols["RTypeObjects_DispatchEvent"],
                 max_steps=5_000_000)
    check(machine, world, (variant, timer, "init"))

    parent.state = "hold"
    parent.timer = timer
    sync_parent(machine, parent)
    run_frame(machine, symbols, world, 1)
    children = [enemy for enemy in world.enemies
                if isinstance(enemy, Child8D85)]
    assert len(children) == 1, (variant, timer, len(children))
    expected_script = {(0, 0xC0): 0xA434, (0, 0x80): 0xA45A,
                       (1, 0xC0): 0xA484, (1, 0x80): 0xA4B8}
    assert children[0].motion.script == expected_script[(variant, timer)]
    check(machine, world, (variant, timer, "spawn"))
    return world, parent, children[0]


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)

    deep: tuple[M72EnemyWorld, Enemy7D68, Child8D85] | None = None
    for variant in (0, 1):
        for timer in (0xC0, 0x80):
            case = create_case(machine, symbols, variant, timer)
            if (variant, timer) == (0, 0xC0):
                deep = case
    assert deep is not None

    # Повторно создаём deep-case, потому что следующие reset уже заменили его
    # физический pool. Два scripted pass сверяют phase/stream pointer.
    world, parent, child = create_case(machine, symbols, 0, 0xC0)
    for frame in (2, 3):
        run_frame(machine, symbols, world, frame)
        check(machine, world, ("scripted", frame))

    # Попадание в scripted state не уменьшает HP и сразу ставит terminal.
    child.take_damage(world, 1)
    damage(machine, symbols, child, 1)
    check(machine, world, "scripted-hit")
    child.timer = 2
    sync_child(machine, child)
    for frame in (4, 5):
        run_frame(machine, symbols, world, frame)
        check(machine, world, ("terminal", frame))
    assert child.state == "active" and child.hp == 4

    # Первый active pass выбирает ROM target и формирует signed Q8 velocity.
    run_frame(machine, symbols, world, 6)
    check(machine, world, "active-target")
    child.take_damage(world, 1)
    damage(machine, symbols, child, 1)
    check(machine, world, "active-hit")
    parent.take_damage(world, 1)
    damage(machine, symbols, parent, 1)
    check(machine, world, "parent-hit")
    for frame in range(7, 11):
        run_frame(machine, symbols, world, frame)
        check(machine, world, ("flash", frame))

    # Natural child bounds и retreat parent освобождают normal+flash slots.
    child.x = 0x012B
    child.x_velocity = child.y_velocity = 0
    child.timer = 0x40
    sync_child(machine, child)
    run_frame(machine, symbols, world, 11)
    check(machine, world, "child-bounds")
    parent.state = "retreat"
    parent.x = 0x012F
    sync_parent(machine, parent)
    run_frame(machine, symbols, world, 12)
    check(machine, world, "parent-retreat")
    assert not world.enemies

    print("$7D68: обе разновидности, 6 states и `$C0/$80` spawn exact")
    print("$8D85: 4 script roots, terminal, active Q8 target и flash exact")
    print("damage/bounds: normal+flash resources и FIFO release exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
