#!/usr/bin/env python3
"""Покадровый oracle для `$6A9B/$6ACB/$6C37/$6E27`."""
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
    TerrainModifierChild6C37,
    TerrainModifierParent6ACB,
    TerrainModifierProjectile6E27,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE7 = 0x07 * 0x4000
PAGE9 = 0x09 * 0x4000
PAGE10 = 0x0A * 0x4000
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


def bank10_address(symbols: dict[str, int], name: str) -> int:
    """Перевести CPU-адрес `$8000..$BFFF` в physical page #0A."""
    return PAGE10 + (symbols[name] - 0x8000)


def terrain_address(x: int, y: int) -> int:
    """Буквальная `$1E6C`-адресация при нулевых FG X/Y scroll."""
    horizontal = ((x - 0x0140) & 0xFFFF) >> 1
    horizontal &= 0xFFFC
    address = (0x1020 + horizontal) & 0x10FF
    vertical = 0x017F - y
    if vertical < 0:
        vertical = 0
    return (address + ((vertical & 0xFFF8) << 5)) & 0x3FFF


def check_frame(machine: TSConfFT812Machine, world: M72EnemyWorld,
                expected_map: bytearray, frame: int) -> None:
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
        if isinstance(enemy, TerrainModifierParent6ACB):
            assert memory[base] == 18, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert memory[base + 0x0E] == (
                0 if enemy.state == "spawn_children" else 1), frame
            assert word(memory, base + 0x20) == enemy.record_pointer, frame
            assert word(memory, base + 0x22) == enemy.child_count, frame
            assert word(memory, base + 0x24) == enemy.timer, frame
            assert bool(memory[base + 0x26]) == enemy.center_destroyed, frame
            assert word(memory, base + 0x27) == enemy.build_path, frame
            assert word(memory, base + 0x29) == enemy.erase_path, frame
            assert word(memory, base + 0x2B) == enemy.path_origin, frame
            assert word(memory, base + 0x2D) == enemy.build_cursor, frame
            assert word(memory, base + 0x2F) == enemy.erase_cursor, frame
        elif isinstance(enemy, TerrainModifierChild6C37):
            assert memory[base] == 19, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert word(memory, base + 0x18) == enemy.motion.pointer, frame
            assert memory[base + 0x1A] == enemy.motion.commands, frame
            assert word(memory, base + 0x1B) == enemy.motion.phase, frame
            assert word(memory, base + 0x20) == enemy.fire_counter, frame
            assert word(memory, base + 0x22) == enemy.fire_a, frame
            assert word(memory, base + 0x24) == enemy.fire_b, frame
            assert word(memory, base + 0x26) == enemy.projectile_script, frame
            assert memory[base + 0x2C] == enemy.ordinal, frame
            assert word(memory, base + 0x2D) == enemy.local_timer, (
                frame, index, word(memory, base + 0x2D), enemy.local_timer,
                enemy.ordinal)
        elif isinstance(enemy, TerrainModifierProjectile6E27):
            assert memory[base] == 20, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert word(memory, base + 0x2E) == enemy.burst_timer, frame
        else:
            raise AssertionError(type(enemy).__name__)

    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map, frame


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

    # Изолированный тест не запускает scroll integrator: обнуляем обе Q16.8
    # координаты и задаём известную пустую collision-map с кодом `$0FA0`.
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)
    empty_cell = bytes((0xA0, 0x0F, 0x00, 0x00))
    expected_map = bytearray(empty_cell * (0x4000 // 4))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    parent = TerrainModifierParent6ACB()
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(parent, slot)
    world.enemies = [parent]
    world.event_pointer = world.event_last

    machine.set_word(symbols["RTypeWorldLastHandler"], 0x6A9B)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x4400)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    check_frame(machine, world, expected_map, 0)

    def replace(address: int, code: int, attribute: int) -> None:
        address &= 0x3FFF
        put_word(expected_map, address, code)
        put_word(expected_map, address + 2, attribute)

    def terrain_code(x: int, y: int) -> int:
        address = terrain_address(x, y)
        return word(expected_map, address) & 0x0FFF

    seen_shot = False
    seen_burst = False
    for frame in range(1, 101):
        # После полной `$6C09`-записи запускаем build на один шаг раньше erase.
        # Так два курсора намеренно расходятся и тест ловит их случайное
        # объединение в один bank-global temporary.
        if frame == 71:
            parent.build_path = 1
            parent.erase_path = 0
            parent_base = POOL + pool_index(parent.object_slot) * REC
            put_word(machine.mem.physical, parent_base + 0x27, 1)
            put_word(machine.mem.physical, parent_base + 0x29, 0)
            put_word(machine.mem.physical,
                     bank10_address(symbols, "RTypeBank1_ModBuildPath"), 1)
            put_word(machine.mem.physical,
                     bank10_address(symbols, "RTypeBank1_ModErasePath"), 0)
        elif frame == 72:
            parent.erase_path = 1
            parent_base = POOL + pool_index(parent.object_slot) * REC
            put_word(machine.mem.physical, parent_base + 0x29, 1)
            put_word(machine.mem.physical,
                     bank10_address(symbols, "RTypeBank1_ModErasePath"), 1)

        # Подводим один живой link к equality-ветке fire, а parent переносим
        # левее R-9. Это компактно проверяет allocation, унаследованные Q8
        # fractions, velocity table и первый `$6E27` pass без 300 VBlank.
        if frame == 81:
            parent.x = 0x0180
            parent_base = POOL + pool_index(parent.object_slot) * REC
            put_word(machine.mem.physical, parent_base + 0x02, parent.x)
            source = next(
                enemy for enemy in world.enemies
                if isinstance(enemy, TerrainModifierChild6C37)
                and enemy.projectile_script and enemy.fire_a)
            source.x = 0x0200
            source.y = 0x0100
            source.fire_counter = (source.fire_a - 1) & 0xFFFF
            source_base = POOL + pool_index(source.object_slot) * REC
            put_word(machine.mem.physical, source_base + 0x02, source.x)
            put_word(machine.mem.physical, source_base + 0x04, source.y)
            put_word(machine.mem.physical, source_base + 0x20,
                     source.fire_counter)
        elif frame == 85:
            # На четыре кадра позже делаем карту сплошной: живой `$6E27`
            # обязан войти в десятипроходный `$E686`, а не исчезнуть сразу.
            expected_map[:] = bytes(0x4000)
            machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map

        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        machine.call(symbols["RTypeObjects_RunType"], a=18,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=19,
                     max_steps=5_000_000)
        machine.call(symbols["RTypeObjects_RunType"], a=20,
                     max_steps=5_000_000)
        world.update(
            0, 0, frame,
            terrain_code=terrain_code,
            terrain_address=terrain_address,
            replace_terrain=replace,
        )
        seen_shot |= any(isinstance(enemy, TerrainModifierProjectile6E27)
                         for enemy in world.enemies)
        seen_burst |= any(
            isinstance(enemy, TerrainModifierProjectile6E27)
            and enemy.burst_timer
            for enemy in world.enemies)
        check_frame(machine, world, expected_map, frame)

    assert parent.path_origin == terrain_address(0x02D8, 0x0154)
    assert seen_shot and seen_burst
    print("$6A9B/$6ACB: parent, 16-link FIFO и same-pass init exact")
    print("$6B68/$6C09: full/build/erase terrain paths и два cursor exact")
    print("$6C37: motion/fire/descriptor/resource/RNG trace exact")
    print("$6E27: inherited Q8, velocity, terrain burst и release exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
