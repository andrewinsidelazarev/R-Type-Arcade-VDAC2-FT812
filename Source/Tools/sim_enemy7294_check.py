#!/usr/bin/env python3
"""Покадровый machine-vs-Python oracle `$7294/$72D2/$7435`."""
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
    Enemy7294, M72EnemyWorld, Projectile7435,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

PAGE7 = 0x07 * 0x4000
PAGE8 = 0x08 * 0x4000
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


def fill_collision(machine: TSConfFT812Machine,
                   foreground: int, background: int = 0x0FFF) -> None:
    for page, code in ((PAGE7, foreground), (PAGE8, background)):
        cell = bytes((code & 0xFF, (code >> 8) & 0xFF, 0, 0))
        machine.mem.physical[page:page + 0x4000] = cell * (0x4000 // 4)


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
        if isinstance(enemy, Enemy7294):
            assert memory[base] == 52, mark
            assert word(memory, base + 0x0A) == 0x4020, mark
            assert word(memory, base + 0x20) == enemy.fire_counter, mark
            assert word(memory, base + 0x22) == enemy.fire_a, mark
            assert word(memory, base + 0x24) == enemy.fire_b, mark
            assert word(memory, base + 0x26) == enemy.projectile_script, mark
            assert memory[base + 0x28] == enemy.direction, (
                mark, "direction", memory[base + 0x28], enemy.direction)
            assert word(memory, base + 0x2A) == enemy.animation, mark
            assert memory[base + 0x2C] == enemy.flash_palette, mark
            assert memory[base + 0x2D] == enemy.flash_timer, mark
            assert word(memory, base + 0x2E) == enemy.hp, mark
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, mark
        elif isinstance(enemy, Projectile7435):
            assert memory[base] == 53, mark
            assert word(memory, base + 0x0A) == 0xA000, mark
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, mark
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, mark
            assert word(memory, base + 0x2C) == enemy.phase_seed, mark
            assert word(memory, base + 0x2E) == enemy.burst_timer, mark
            assert memory[base + 0x32] == enemy.terrain_delay, mark
        else:
            raise AssertionError((mark, type(enemy).__name__))
        assert word(memory, base + 0x02) == enemy.x, mark
        assert word(memory, base + 0x04) == enemy.y, mark
        assert word(memory, base + 0x06) == enemy.descriptor, mark
        assert memory[base + 0x08] == enemy.palette, mark
        assert memory[base + 0x10] == enemy.x_fraction, mark
        assert memory[base + 0x11] == enemy.y_fraction, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int,
              foreground: int, delta: int = 0,
              background: int = 0x0FFF) -> None:
    fill_collision(machine, foreground, background)
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.call(symbols["RTypeObjects_RunType"], a=52,
                 max_steps=10_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=53,
                 max_steps=10_000_000)
    world.update(0, delta, frame,
                 terrain_code=lambda _x, _y: foreground,
                 collision_codes=lambda _x, _y: (foreground, background))


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: Enemy7294, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_DamageEnemy7294"],
                 a=amount, max_steps=2_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=1_000_000)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)

    world = M72EnemyWorld(stage=6, full_event_stream=True)
    command = 0x7D41
    enemy = Enemy7294(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x7294)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=6_000_000)
    check(machine, world, "init")
    assert (enemy.x, enemy.y, enemy.direction, enemy.fire_a,
            enemy.fire_b, enemy.projectile_script) == (
                0x02C8, 0x0150, 2, 0x0040, 0x0080, 0x9050)

    # Свободный probe вне native bounds инвертирует только младший direction
    # bit. Одновременно проверяем порядок scroll->Q8 и frame-0 animation.
    run_frame(machine, symbols, world, 0, 0x0FFF, -1)
    check(machine, world, "outside-reflect")
    assert (enemy.x, enemy.y, enemy.y_fraction,
            enemy.direction, enemy.animation, enemy.descriptor) == (
                0x02C7, 0x0150, 0xE0, 3, 6, 0x3326)

    # Trigger `$F63A` создаёт `$7435` в том же scheduler pass. Кадр нечётный,
    # поэтому его восьмитактовая terrain delay пока остаётся равной восьми.
    enemy.direction = 2
    enemy.fire_counter = enemy.fire_a - 1
    base = POOL + pool_index(enemy.object_slot) * REC
    machine.mem.physical[base + 0x28] = 2
    put_word(machine.mem.physical, base + 0x20, enemy.fire_counter)
    run_frame(machine, symbols, world, 1, 0x0001)
    check(machine, world, "special-shot")
    shots = [item for item in world.enemies if isinstance(item, Projectile7435)]
    assert len(shots) == 1 and shots[0].terrain_delay == 8
    shot = shots[0]

    # На чётном VBlank projectile делает один Q8 pass и только уменьшает
    # terrain delay; solid карты ещё не переводят его в `$E686`.
    run_frame(machine, symbols, world, 2, 0x0001)
    check(machine, world, "delayed-probe")
    assert shot.terrain_delay == 7 and shot.burst_timer == 0

    # Нулевая delay на чётном кадре активирует обе threshold-проверки. Solid
    # foreground должен начать десятикадровый общий breakup немедленно.
    shot.terrain_delay = 0
    shot_base = POOL + pool_index(shot.object_slot) * REC
    machine.mem.physical[shot_base + 0x32] = 0
    run_frame(machine, symbols, world, 4, 0x0001)
    check(machine, world, "terrain-burst")
    assert shot.burst_timer == 0x0A

    # Нефатальный hit хранит HP=1 и `$0C` flash countdown; cleanup снимает
    # normal/flash владельца и отдельный `$56` projectile resource.
    enemy.take_damage(world, 1)
    damage(machine, symbols, enemy, 1)
    check(machine, world, "damage")
    assert enemy.hp == 1 and enemy.flash_timer == 0x0C
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run_frame(machine, symbols, world, 5, 0x0FFF)
    check(machine, world, "cleanup")
    assert enemy.object_slot is None and shot.object_slot is None

    print("$7294 init: fire/position/direction records и resources exact")
    print("$72D2: scroll/Q8, 5-phase animation и double terrain reflect exact")
    print("$73DB/$7435: same-pass shot, 8-even-pass delay и `$E686` exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
