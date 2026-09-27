#!/usr/bin/env python3
"""Сверка первого ROM-кластера Stage 1 между Python oracle и Z80."""
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
    BackgroundParticleE5CD,
    CleanupTimerF477,
    EnemyProjectile,
    FormationChild,
    FormationParent,
    GroundWalker,
    M72EnemyWorld,
    PaletteCycleFBED,
    RedFlyer,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40
TYPES = PAGE9 + 0x1970
REFS = PAGE9 + 0x1980
RNG = PAGE9 + 0x1990
SCHED_NEXT = PAGE9 + 0x1A00
SCHED_HEAD = PAGE9 + 0x1AC0


def word(data: bytearray, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // 0x40


def check_frame(machine: TSConfFT812Machine, world: M72EnemyWorld,
                frame: int) -> None:
    memory = machine.mem.physical
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame
    resource_snapshot = (
        list(memory[TYPES:TYPES + 16]), list(memory[REFS:REFS + 16]))

    expected: dict[int, object] = {}
    for owner in world.resource_owners:
        assert owner.object_slot is not None
        expected[pool_index(owner.object_slot)] = owner
    for enemy in world.enemies:
        if enemy.object_slot is not None:
            expected[pool_index(enemy.object_slot)] = enemy

    active = {
        index for index in range(2, 96)
        if memory[POOL + index * REC] != 0
    }
    chain: list[int] = []
    cursor = memory[SCHED_HEAD]
    while cursor != 0xFF and cursor not in chain and len(chain) < 96:
        chain.append(cursor)
        cursor = memory[SCHED_NEXT + cursor]
    assert active == set(expected), (
        frame, active, chain,
        {index: memory[POOL + index * REC] for index in sorted(active)},
        {index: type(owner).__name__ for index, owner in expected.items()})

    for index, owner in expected.items():
        base = POOL + index * REC
        kind = memory[base]
        if isinstance(owner, RedFlyer):
            assert kind == 1
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x06) == owner.descriptor
            assert memory[base + 0x08] == owner.palette, (
                frame, index, memory[base + 0x08], owner.palette,
                owner.descriptor, owner.velocity_table)
            assert word(memory, base + 0x16) == owner.motion.script
            assert word(memory, base + 0x18) == owner.motion.pointer
            assert memory[base + 0x1A] == owner.motion.commands
            assert memory[base + 0x1B] == (owner.motion.phase & 0xFF), (
                frame, index, memory[base + 0x1B], owner.motion.phase)
            assert word(memory, base + 0x20) == owner.fire_counter
            assert word(memory, base + 0x22) == owner.fire_a
            assert word(memory, base + 0x24) == owner.fire_b
            assert word(memory, base + 0x26) == owner.projectile_script
        elif isinstance(owner, PaletteCycleFBED):
            assert kind == 2
            assert word(memory, base + 0x20) == owner.palette_index
            assert word(memory, base + 0x22) == owner.first_resource
            assert word(memory, base + 0x24) == owner.second_resource
            assert word(memory, base + 0x26) == owner.remaining
            assert word(memory, base + 0x28) == owner.mode
            assert word(memory, base + 0x2A) == owner.mask
            assert word(memory, base + 0x2C) == owner.phase
        elif isinstance(owner, BackgroundParticleE5CD):
            assert kind == 4
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x06) == owner.descriptor
            assert memory[base + 0x08] == owner.palette, (
                frame, index, memory[base + 0x08], owner.palette,
                owner.descriptor, owner.velocity_table)
            assert memory[base + 0x10] == owner.x_fraction
            assert word(memory, base + 0x12) == owner.x_velocity & 0xFFFF
            assert bool(memory[base + 0x0E]) == owner.initialized
            assert bool(memory[base + 0x0F]) == owner.render_ready
            assert word(memory, base + 0x16) == owner.velocity_table
        elif isinstance(owner, CleanupTimerF477):
            assert kind == 5
            assert word(memory, base + 0x1D) == owner.timer
        elif isinstance(owner, FormationParent):
            assert kind == 6
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x16) == owner.script
            assert word(memory, base + 0x20) == owner.sequence
            assert word(memory, base + 0x22) == owner.remaining
            assert word(memory, base + 0x24) == owner.sequence_index
            assert word(memory, base + 0x26) == owner.spawn_timer
            assert word(memory, base + 0x28) == owner.phase
        elif isinstance(owner, FormationChild):
            assert kind == 7
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x06) == owner.descriptor
            assert memory[base + 0x08] == owner.palette
            assert word(memory, base + 0x16) == owner.motion.script
            assert word(memory, base + 0x18) == owner.motion.pointer
            assert memory[base + 0x1A] == owner.motion.commands
            assert word(memory, base + 0x1B) == owner.motion.phase, (
                frame, index, word(memory, base + 0x1B), owner.motion.phase)
            assert word(memory, base + 0x20) == owner.fire_counter
            assert word(memory, base + 0x22) == owner.fire_a
            assert word(memory, base + 0x24) == owner.fire_b
            assert word(memory, base + 0x26) == owner.projectile_script
        elif isinstance(owner, GroundWalker):
            assert kind == 8
            states = {
                "falling": 0, "landing": 1, "turning": 2,
                "scripted": 3, "edge": 4, "walking": 5,
            }
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x06) == owner.descriptor
            assert memory[base + 0x08] == owner.palette
            assert memory[base + 0x01] & 1 == owner.direction
            assert memory[base + 0x0E] == states[owner.state]
            assert memory[base + 0x10] == owner.x_fraction
            assert word(memory, base + 0x20) == owner.fire_counter
            assert word(memory, base + 0x22) == owner.fire_a
            assert word(memory, base + 0x24) == owner.fire_b
            assert word(memory, base + 0x26) == owner.projectile_script
            assert memory[base + 0x2C] == owner.secondary_palette
            assert word(memory, base + 0x2E) == owner.animation_pointer
            assert word(memory, base + 0x30) == owner.animation_timer
        elif isinstance(owner, EnemyProjectile):
            assert kind == 9
            assert word(memory, base + 0x02) == owner.x
            assert word(memory, base + 0x04) == owner.y
            assert word(memory, base + 0x06) == owner.descriptor
            assert memory[base + 0x08] == owner.palette
            assert memory[base + 0x10] == owner.x_fraction
            assert memory[base + 0x11] == owner.y_fraction
            assert word(memory, base + 0x12) == owner.x_velocity & 0xFFFF
            assert word(memory, base + 0x14) == owner.y_velocity & 0xFFFF
            assert word(memory, base + 0x2C) == owner.phase_seed
            assert word(memory, base + 0x2E) == owner.burst_timer
        else:
            # ParticleControllerE4A5 — dataclass, не Enemy.
            assert kind == 3
            assert word(memory, base + 0x20) == owner.remaining
            assert word(memory, base + 0x22) == owner.velocity_table
            assert word(memory, base + 0x24) == owner.cadence
            assert word(memory, base + 0x26) == owner.spawn_counter
            assert tuple(memory[base + 0x28:base + 0x2C]) == owner.slots
    assert resource_snapshot[0] == world.resources.types, (
        frame, resource_snapshot[0], world.resources.types)
    assert resource_snapshot[1] == world.resources.refs, (
        frame, resource_snapshot[1], world.resources.refs)


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

    # Progression `$0776` пропускает первые 27 записей: ранний кластер,
    # formation и первый `$5A02`. Очищенная `$0FA0` карта эквивалентна
    # fallback `$0FFF` oracle для falling probe (оба кода >= `$0DFC`).
    # Жизненный цикл ранних объектов короче окна проверки: к последнему кадру
    # некоторые из них уже обязаны освободить запись. Поэтому запоминаем факт
    # появления каждого класса по всему trace, а не требуем, чтобы все классы
    # одновременно оставались живы на кадре 47.
    seen_types: set[type[object]] = set()
    for frame in range(48):
        progression = 0x0776
        foreground_delta = 1 if frame & 1 else 0
        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], foreground_delta)
        machine.call(symbols["RTypeObjects_Update"], max_steps=5_000_000)
        event = world.current_event()
        if event is not None and progression >= event.threshold:
            machine.set_word(symbols["RTypeWorldLastCommand"], event.command)
            machine.set_word(symbols["RTypeWorldLastHandler"], event.handler)
            machine.call(symbols["RTypeObjects_DispatchEvent"],
                         max_steps=5_000_000)
        world.update(progression, foreground_delta, frame)
        check_frame(machine, world, frame)
        seen_types.update(type(enemy) for enemy in world.enemies)

    assert RedFlyer in seen_types
    assert BackgroundParticleE5CD in seen_types
    assert FormationChild in seen_types
    assert GroundWalker in seen_types
    assert EnemyProjectile in seen_types
    print("Stage 1 events 0…26: one-event-per-VBlank exact")
    print("$E430/$E568/$E5CD particles и resource refs exact")
    print("$FB9C/$FBED palette-cycle state и RNG exact")
    print("$596D/$F5C1 Red Flyer motion/animation/fire state exact")
    print("$5DC8/$5E22 formation parent/children exact")
    print("$5A02/$5BA4 Ground Walker falling/terrain state exact")
    print("$F63A/$E601 aimed projectile allocation/immediate Q8 pass exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
