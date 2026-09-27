#!/usr/bin/env python3
"""Machine-vs-Python oracle позднего boss `$B7FB…$C0A8`."""
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
    BossB7FBController, BossB7FBCore, BossB7FBCoreChild,
    BossB7FBMissile, BossB7FBMissileSpawner, BossB7FBRandomChild,
    BossB7FBRandomSpawner, BossB7FBSegment, ExplosionEffect, M72EnemyWorld,
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


def base_of(enemy: object) -> int:
    slot = getattr(enemy, "object_slot")
    assert slot is not None
    return POOL + pool_index(slot) * REC


def terrain_cell(payload: bytearray, address: int) -> tuple[int, int]:
    address &= 0x3FFF
    return word(payload, address), word(payload, (address + 2) & 0x3FFF)


def replace_terrain(payload: bytearray, address: int,
                    code: int, attribute: int) -> None:
    address &= 0x3FFF
    put_word(payload, address, code)
    put_word(payload, (address + 2) & 0x3FFF, attribute)


def check_resources(memory: bytearray, world: M72EnemyWorld,
                    mark: object) -> None:
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def check_root(memory: bytearray, root: BossB7FBController,
               mark: object) -> None:
    base = base_of(root)
    state = {"active": 0, "exit": 1}[root.state]
    assert memory[base] == 64, mark
    assert word(memory, base + 0x0A) == root.scheduler_priority, mark
    assert memory[base + 0x0E] == state, mark
    assert word(memory, base + 0x20) == root.timer, mark
    assert memory[base + 0x22] == int(root.defeated), mark
    assert word(memory, base + 0x24) == root.exit_timer, mark


def check_segment(memory: bytearray, segment: BossB7FBSegment,
                  root: BossB7FBController, mark: object) -> None:
    base = base_of(segment)
    assert memory[base] == 65, mark
    assert word(memory, base + 0x02) == segment.x, mark
    assert word(memory, base + 0x04) == segment.y, mark
    assert word(memory, base + 0x06) == segment.descriptor, mark
    assert memory[base + 0x08] == segment.palette, mark
    assert word(memory, base + 0x0A) == segment.scheduler_priority, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert word(memory, base + 0x22) == segment.threshold, mark
    assert word(memory, base + 0x24) == segment.timer, mark
    assert memory[base + 0x26] == int(segment.reverse), mark
    assert memory[base + 0x27] == segment.damage_accumulator, mark


def check_random_spawner(memory: bytearray, item: BossB7FBRandomSpawner,
                         root: BossB7FBController, mark: object) -> None:
    base = base_of(item)
    assert memory[base] == 66, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert word(memory, base + 0x22) == item.timer, mark
    assert word(memory, base + 0x24) == item.x_pointer, mark
    assert word(memory, base + 0x26) == item.cadence, mark
    assert word(memory, base + 0x28) == item.reload, mark
    assert word(memory, base + 0x2A) == item.ramp_timer, mark


def check_random_child(memory: bytearray, item: BossB7FBRandomChild,
                       root: BossB7FBController, mark: object) -> None:
    base = base_of(item)
    assert memory[base] == 67, mark
    assert word(memory, base + 0x02) == item.x, mark
    assert word(memory, base + 0x04) == item.y, mark
    assert word(memory, base + 0x06) == item.descriptor, mark
    assert memory[base + 0x08] == item.palette, mark
    assert word(memory, base + 0x14) == item.y_velocity & 0xFFFF, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert memory[base + 0x21] == int(item.animated), mark
    assert memory[base + 0x22] == item.hp, mark


def check_missile_spawner(memory: bytearray, item: BossB7FBMissileSpawner,
                          root: BossB7FBController, mark: object) -> None:
    base = base_of(item)
    assert memory[base] == 68, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert word(memory, base + 0x22) == item.timer, (
        mark, "timer", word(memory, base + 0x22), item.timer)
    assert word(memory, base + 0x24) == item.pointer, (
        mark, "pointer", word(memory, base + 0x24), item.pointer)


def check_missile(memory: bytearray, item: BossB7FBMissile,
                  root: BossB7FBController, mark: object) -> None:
    base = base_of(item)
    assert memory[base] == 69, mark
    assert word(memory, base + 0x02) == item.x, mark
    assert word(memory, base + 0x04) == item.y, mark
    assert word(memory, base + 0x06) == item.descriptor, mark
    assert memory[base + 0x08] == item.palette, mark
    assert word(memory, base + 0x26) == item.projectile_script, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert word(memory, base + 0x22) == item.timer, mark
    assert word(memory, base + 0x24) == item.hp, mark


def check_core(memory: bytearray, core: BossB7FBCore,
               root: BossB7FBController, mark: object) -> None:
    base = base_of(core)
    state = 1 if getattr(core, "state", "active") == "exploding" else 0
    assert memory[base] == 70, mark
    assert word(memory, base + 0x02) == core.x, mark
    assert word(memory, base + 0x04) == core.y, mark
    assert word(memory, base + 0x06) == core.descriptor, mark
    assert memory[base + 0x08] == core.palette, mark
    assert memory[base + 0x0E] == state, mark
    assert memory[base + 0x10] == core.x_fraction, mark
    assert memory[base + 0x20] == pool_index(root.object_slot), mark
    assert word(memory, base + 0x22) == core.timer, mark
    assert word(memory, base + 0x24) == core.phase, mark
    assert memory[base + 0x26] == core.flash_palette, mark
    assert memory[base + 0x27] == core.flash_timer, mark
    if state == 0:
        assert word(memory, base + 0x28) == core.hp & 0xFFFF, mark


def check_core_child(memory: bytearray, child: BossB7FBCoreChild,
                     mark: object) -> None:
    base = base_of(child)
    state = 0 if child.state == "out" else 1
    assert memory[base] == 71, mark
    assert word(memory, base + 0x02) == child.x, mark
    assert word(memory, base + 0x04) == child.y, mark
    assert word(memory, base + 0x06) == child.descriptor, mark
    assert memory[base + 0x08] == child.palette, mark
    assert memory[base + 0x0E] == state, mark
    assert word(memory, base + 0x16) == child.motion.script, mark
    assert word(memory, base + 0x18) == child.motion.pointer, mark
    assert memory[base + 0x1A] == child.motion.commands, mark


def call_record(machine: TSConfFT812Machine, symbols: dict[str, int],
                slot: int, trampoline: str, *, a: int | None = None) -> None:
    index = pool_index(slot)
    machine.set_byte(symbols["RTypeObjects_CurrentIndex"], index)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=500_000)
    machine.call(symbols[trampoline], a=a, max_steps=8_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=500_000)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    memory = machine.mem.physical

    # Инициализируем map легко различимыми code/attribute words. Это делает
    # ошибки шага +4 и очистки старшего attribute byte наблюдаемыми побайтно.
    expected_map = bytearray(0x4000)
    for address in range(0, 0x4000, 4):
        put_word(expected_map, address, (0x0200 + address // 4) & 0x0FFF)
        put_word(expected_map, address + 2, 0xAB03)
    # Boss использует намеренно смещённый на два byte domain `$1002+n*4`.
    # Перезаполняем именно его, чтобы ожидаемый attribute был однозначным.
    for index in range(0x800):
        address = 0x1002 + index * 4
        put_word(expected_map, address, index & 0x0FFF)
        put_word(expected_map, address + 2, 0xAB03)
    memory[PAGE7:PAGE7 + 0x4000] = expected_map

    world = M72EnemyWorld(stage=7, full_event_stream=True)
    world._terrain_cell = lambda address: terrain_cell(expected_map, address)
    world._replace_terrain = lambda address, code, attr: replace_terrain(
        expected_map, address, code, attr)
    root = BossB7FBController(world)
    world.pending.append(root)
    parts = list(root.parts)
    segments = [item for item in parts if isinstance(item, BossB7FBSegment)]
    random_spawner = next(item for item in parts
                          if isinstance(item, BossB7FBRandomSpawner))
    missile_spawner = next(item for item in parts
                           if isinstance(item, BossB7FBMissileSpawner))
    core = next(item for item in parts if isinstance(item, BossB7FBCore))

    machine.set_word(symbols["RTypeWorldLastHandler"], 0xB7FB)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=12_000_000)
    assert tuple(pool_index(item.object_slot) for item in parts) == tuple(range(2, 10))
    assert pool_index(root.object_slot) == 10
    check_root(memory, root, "constructor-root")
    for segment in segments:
        check_segment(memory, segment, root, ("constructor-segment", segment.x))
    check_random_spawner(memory, random_spawner, root, "constructor-random")
    check_missile_spawner(memory, missile_spawner, root, "constructor-missile")
    check_core(memory, core, root, "constructor-core")
    check_resources(memory, world, "constructor-resources")
    world.pending.clear()

    # `$0300`: ровно 128 attributes получают bit 7, code words не меняются.
    root.timer = 0x02FF
    put_word(memory, base_of(root) + 0x20, root.timer)
    call_record(machine, symbols, root.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBRoot")
    root.update(world, 0)
    check_root(memory, root, "root-open")
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map
    assert terrain_cell(expected_map, 0x1002)[1] == 0xAB83
    assert terrain_cell(expected_map, 0x11FE)[1] == 0xAB83

    # Forward descriptors и byte-clamped damage accumulator.
    segment = segments[0]
    segment.timer = 0x03CE
    put_word(memory, base_of(segment) + 0x24, segment.timer)
    machine.set_word(symbols["RTypeWorldFgDelta"], 0xFFFF)
    call_record(machine, symbols, segment.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBSegment")
    segment.update(world, -1)
    check_segment(memory, segment, root, "segment-forward")
    call_record(machine, symbols, segment.object_slot,
                "RTypeObjectBank4_DamageBossB7FBSegment", a=0xFF)
    segment.take_damage(world, 0xFF)
    check_segment(memory, segment, root, "segment-damage-clamp")

    # Отрицательная reverse delta обязана выбирать `$610A`.
    segment.reverse = True
    segment.timer = 0
    memory[base_of(segment) + 0x26] = 1
    put_word(memory, base_of(segment) + 0x24, 0)
    machine.set_word(symbols["RTypeWorldFgDelta"], 0)
    call_record(machine, symbols, segment.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBSegment")
    segment.update(world, 0)
    check_segment(memory, segment, root, "segment-reverse-negative")
    assert segment.descriptor == 0x610A

    # `$BAA7`: cadence/ramp, два ROM tables и дополнительный RNG flip должны
    # породить один и тот же child и оставить одинаковое RNG state.
    random_spawner.timer = 0x035F
    random_spawner.reload = 1
    put_word(memory, base_of(random_spawner) + 0x22, 0x035F)
    put_word(memory, base_of(random_spawner) + 0x28, 1)
    call_record(machine, symbols, random_spawner.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBRandomSpawner")
    random_spawner.update(world, 0)
    random_child = next(item for item in world.pending
                        if isinstance(item, BossB7FBRandomChild))
    check_random_spawner(memory, random_spawner, root, "random-spawn-parent")
    check_random_child(memory, random_child, root, "random-spawn-child")
    check_resources(memory, world, "random-spawn-resources")
    world.pending.clear()

    # `$BD32`: первый word создаёт X=$0200, а HL обязан перейти на `$627E`.
    missile_spawner.timer = 0x037F
    put_word(memory, base_of(missile_spawner) + 0x22, 0x037F)
    call_record(machine, symbols, missile_spawner.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBMissileSpawner")
    missile_spawner.update(world, 0)
    missile = next(item for item in world.pending
                   if isinstance(item, BossB7FBMissile))
    check_missile_spawner(memory, missile_spawner, root, "missile-parent")
    check_missile(memory, missile, root, "missile-child")
    assert missile_spawner.pointer == 0x627E and missile.x == 0x0200
    check_resources(memory, world, "missile-resources")
    world.pending.clear()

    # Sentinel `$8000`, после которого лежит zero, не является координатой и
    # зацикливает command table обратно на `$627C`.
    missile_spawner.timer = 0x03FF
    missile_spawner.pointer = 0x629A
    put_word(memory, base_of(missile_spawner) + 0x22, 0x03FF)
    put_word(memory, base_of(missile_spawner) + 0x24, 0x629A)
    call_record(machine, symbols, missile_spawner.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBMissileSpawner")
    missile_spawner.update(world, 0)
    check_missile_spawner(memory, missile_spawner, root, "missile-wrap")
    assert missile_spawner.pointer == 0x627C and not world.pending

    # `$0500/$017F`: reset phase, Q8 X/table descriptor и новый scripted child.
    core.timer = 0x04FF
    put_word(memory, base_of(core) + 0x22, 0x04FF)
    machine.set_word(symbols["FrameCounter"], 0)
    world.frame_counter = 0
    call_record(machine, symbols, core.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBCore")
    core.update(world, 0)
    core_child = next(item for item in world.pending
                      if isinstance(item, BossB7FBCoreChild))
    check_core(memory, core, root, "core-phase-zero")
    check_core_child(memory, core_child, "core-child")
    check_resources(memory, world, "core-child-resources")
    world.pending.clear()

    # Fatal core hit: root flag и все 2048 attributes сохраняют только nibble.
    call_record(machine, symbols, core.object_slot,
                "RTypeObjectBank4_DamageBossB7FBCore", a=0x55)
    core.take_damage(world, 0x55)
    check_root(memory, root, "core-fatal-root")
    check_core(memory, core, root, "core-fatal")
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map
    assert all(terrain_cell(expected_map, 0x1002 + index * 4)[1] == 3
               for index in range(0x800))

    # Первый explosion pass при frame%4==0 обязан совпасть по RNG/X/Y/effect.
    call_record(machine, symbols, core.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBCore")
    core.update(world, 0)
    explosion = next(item for item in world.pending
                     if isinstance(item, ExplosionEffect))
    exp_base = base_of(explosion)
    assert memory[exp_base] == 31
    assert word(memory, exp_base + 0x02) == explosion.x
    assert word(memory, exp_base + 0x04) == explosion.y
    assert word(memory, exp_base + 0x06) == explosion.descriptor
    check_core(memory, core, root, "core-explosion-pass")
    check_resources(memory, world, "core-explosion-resources")

    # Defeated root начинает буквальный `$00C0` exit countdown.
    call_record(machine, symbols, root.object_slot,
                "RTypeObjectBank4_UpdateBossB7FBRoot")
    root.update(world, 0)
    check_root(memory, root, "root-exit")
    assert root.state == "exit" and root.exit_timer == 0x00C0

    print("PASS: `$B7FB/$B997`: 5 segments + 3 controllers, links и terrain `$0300` exact")
    print("PASS: `$BAA7/$BD32`: RNG child, cadence, missile cursor и sentinels exact")
    print("PASS: `$BE81/$BFCE/$C03F`: core tables, fatal 2048 cells и explosions exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
