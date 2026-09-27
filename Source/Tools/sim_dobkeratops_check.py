#!/usr/bin/env python3
"""Покадровый host-oracle для Dobkeratops `$98FD/$9B26/$A035/$E700`."""
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
    DobkeratopsArenaAnchor,
    DobkeratopsBack,
    DobkeratopsBody,
    DobkeratopsDebrisE700,
    DobkeratopsOrb,
    DobkeratopsOrbTrail,
    DobkeratopsRoot,
    DobkeratopsTentacle,
    EnemyProjectile,
    ExplosionEffect,
    M72EnemyWorld,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE7 = 0x07 * 0x4000
PAGE9 = 0x09 * 0x4000
PAGE11 = 0x0B * 0x4000
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


def bank11_address(symbols: dict[str, int], name: str) -> int:
    return PAGE11 + (symbols[name] - 0x8000)


def terrain_address(x: int, y: int) -> int:
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
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (
        frame, active,
        {index: type(enemy).__name__ for index, enemy in expected.items()})

    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, DobkeratopsRoot):
            assert memory[base] == 24, frame
            state = 2 if enemy.cleanup else (1 if enemy.initialized else 0)
            assert memory[base + 0x0E] == state, frame
            assert word(memory, base + 0x20) == enemy.timeout, frame
            assert memory[base + 0x22] == enemy.anchors_remaining, frame
            assert word(memory, base + 0x24) == enemy.end_timer, frame
            assert bool(memory[base + 0x26]) == enemy.defeated, frame
            assert bool(memory[base + 0x27]) == enemy.body_destroyed, frame
        elif isinstance(enemy, DobkeratopsBack):
            assert memory[base] == 25, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, (
                frame, "back descriptor", hex(word(memory, base + 0x06)),
                hex(enemy.descriptor), hex(word(memory, base + 0x20)),
                hex(enemy.timer))
            assert memory[base + 0x08] == enemy.palette, frame
            state = (0 if enemy.explosion_state is None else
                     (2 if enemy.explosion_state == "init" else 3))
            assert memory[base + 0x0E] == state, frame
            if state == 0:
                assert word(memory, base + 0x20) == enemy.timer, frame
            elif state == 3:
                assert word(memory, base + 0x20) == enemy.explosion_pointer, frame
                assert word(memory, base + 0x22) == enemy.explosion_timer, frame
        elif isinstance(enemy, DobkeratopsBody):
            states = {"intro": 0, "emerge": 1, "active": 2, "death": 3}
            assert memory[base] == 26, frame
            assert word(memory, base + 0x02) == enemy.x, (
                frame, "body x", index, hex(word(memory, base + 0x02)),
                hex(enemy.x))
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == states[enemy.state], frame
            assert word(memory, base + 0x20) == enemy.timer, frame
            assert memory[base + 0x22] == enemy.flash_palette, frame
            assert memory[base + 0x23] == enemy.flash_timer, frame
            assert word(memory, base + 0x24) == enemy.death_pointer, frame
            assert word(memory, base + 0x26) == enemy.hp & 0xFFFF, frame
            assert bool(memory[base + 0x01] & 2) == enemy.flash_visible, frame
        elif isinstance(enemy, DobkeratopsArenaAnchor):
            states = {"wait": 0, "active": 1, "erase": 2}
            assert memory[base] == 27, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert memory[base + 0x0E] == states[enemy.state], frame
            assert word(memory, base + 0x20) == enemy.path, frame
            assert word(memory, base + 0x22) == enemy.activation_timer, frame
            assert word(memory, base + 0x24) == enemy.timeout, frame
            assert word(memory, base + 0x26) == enemy.tile_offset, frame
        elif isinstance(enemy, DobkeratopsTentacle):
            state = {
                "intro": 0, "active": 1, "cleanup_wait": 2,
                "cleanup_explosion": 3, "cleanup_explosion_active": 4,
            }[enemy.state]
            assert memory[base] == 28, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == state, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            if state == 4:
                assert word(memory, base + 0x20) == enemy.explosion_pointer, frame
                assert word(memory, base + 0x22) == enemy.explosion_timer, frame
            else:
                assert word(memory, base + 0x20) == enemy.fixed_descriptor, frame
                assert word(memory, base + 0x22) == enemy.script_start, frame
                assert word(memory, base + 0x24) == enemy.script_pointer, frame
                assert word(memory, base + 0x26) == enemy.intro_timer, frame
                assert word(memory, base + 0x28) == enemy.cleanup_timer, frame
                assert word(memory, base + 0x2A) == enemy.step_timer, frame
                assert bool(memory[base + 0x2C]) == enemy.tip, frame
                if enemy.tip:
                    assert word(memory, base + 0x2D) == enemy.fire_counter, frame
                    assert word(memory, base + 0x2F) == enemy.fire_a, frame
                    assert word(memory, base + 0x31) == enemy.fire_b, frame
                    assert word(memory, base + 0x33) == enemy.projectile_script, frame
                if state == 1:
                    assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
                    assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
        elif isinstance(enemy, DobkeratopsOrbTrail):
            assert memory[base] == 30, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == (1 if enemy.state == "9f18" else 0), frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert word(memory, base + 0x22) == enemy.straight_timer, frame
            assert word(memory, base + 0x24) == enemy.acceleration & 0xFFFF, frame
            assert memory[base + 0x26] == enemy.acceleration_timer, frame
            assert word(memory, base + 0x2B) == enemy.phase_offset, frame
            if enemy.parent.object_slot is not None:
                assert memory[base + 0x2D] == pool_index(
                    enemy.parent.object_slot), frame
        elif isinstance(enemy, DobkeratopsOrb):
            assert memory[base] == 29, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == (1 if enemy.state == "9e78" else 0), frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert word(memory, base + 0x20) == enemy.trail_timer, frame
            assert word(memory, base + 0x22) == enemy.straight_timer, frame
            assert word(memory, base + 0x24) == enemy.acceleration & 0xFFFF, frame
            assert memory[base + 0x26] == enemy.acceleration_timer, frame
            assert word(memory, base + 0x27) == enemy.origin_x, frame
            assert word(memory, base + 0x29) == enemy.origin_y, frame
        elif isinstance(enemy, DobkeratopsDebrisE700):
            assert memory[base] == 31, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x0E] == (2 if enemy.initialized else 1), frame
            assert word(memory, base + 0x20) == enemy.sequence_pointer, frame
            assert word(memory, base + 0x22) == enemy.sequence_timer, frame
            assert word(memory, base + 0x24) == enemy.terrain_timer, frame
            assert word(memory, base + 0x26) == enemy.terrain_path, frame
        elif isinstance(enemy, EnemyProjectile):
            assert memory[base] == 9, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert memory[base + 0x10] == enemy.x_fraction, frame
            assert memory[base + 0x11] == enemy.y_fraction, frame
            assert word(memory, base + 0x12) == enemy.x_velocity & 0xFFFF, frame
            assert word(memory, base + 0x14) == enemy.y_velocity & 0xFFFF, frame
            assert word(memory, base + 0x2C) == enemy.phase_seed, frame
        elif isinstance(enemy, ExplosionEffect):
            expected_type = {0xEF00: 31, 0xF280: 32, 0xFE00: 34}[
                enemy.scheduler_priority]
            assert memory[base] == expected_type, frame
            assert word(memory, base + 0x02) == enemy.x, frame
            assert word(memory, base + 0x04) == enemy.y, frame
            assert word(memory, base + 0x06) == enemy.descriptor, frame
            assert memory[base + 0x08] == enemy.palette, frame
            assert word(memory, base + 0x20) == enemy.sequence_pointer, frame
            assert word(memory, base + 0x22) == enemy.sequence_timer, frame
        else:
            raise AssertionError(type(enemy).__name__)

    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, frame
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, frame
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), frame
    assert memory[PAGE7:PAGE7 + 0x4000] == expected_map, frame


def run_bands(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    # Только bands, реально занятые изолированным Dobkeratops. Порядок тот же,
    # что в resident `RTypeObjects_Update`, включая equal-priority trail/orb.
    for object_type in (24, 25, 26, 27, 9, 31, 30, 29, 32, 34, 28):
        machine.call(symbols["RTypeObjects_RunType"], a=object_type,
                     max_steps=8_000_000)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)

    # Разные attributes делают проверку writer-ов чувствительной не только к
    # адресу/code `$0FA0`, но и к требованию сохранить два старших байта cell.
    expected_map = bytearray(0x4000)
    for address in range(0, 0x4000, 4):
        code = 0x0100 | ((address >> 2) & 0xFF)
        attribute = 0xA000 | ((address >> 4) & 0x0FFF)
        put_word(expected_map, address, code)
        put_word(expected_map, address + 2, attribute)
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)

    world = M72EnemyWorld(stage=2, full_event_stream=True)
    root = DobkeratopsRoot(world)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(root, slot)
    world.enemies = [root]
    world.event_pointer = world.event_last
    world.checkpoint_flag = 1

    machine.set_word(symbols["RTypeWorldLastHandler"], 0x98FD)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=5_000_000)
    machine.mem.physical[
        bank11_address(symbols, "RTypeBank2_CheckpointFlag")] = 1
    check_frame(machine, world, expected_map, 0)

    def erase(address: int) -> None:
        put_word(expected_map, address & 0x3FFF, 0x0FA0)

    def replace(address: int, code: int, attribute: int) -> None:
        address &= 0x3FFF
        put_word(expected_map, address, code)
        put_word(expected_map, address + 2, attribute)

    def terrain_cell(address: int) -> tuple[int, int]:
        address &= 0x3FFF
        return word(expected_map, address), word(expected_map, address + 2)

    seen_orb = seen_trail = seen_projectile = False
    seen_debris = seen_cut = seen_component_explosion = False
    death_frame = 30
    for frame in range(1, 91):
        # Ускоряем только длинные ожидания, симметрично в Python и физическом
        # пуле. Сами transition branches, RNG и nested allocations остаются
        # буквальными и после каждой инъекции проверяются покадрово.
        if frame == 2:
            back = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBack))
            body = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBody))
            back.timer = 0
            body.timer = 0x0061
            put_word(machine.mem.physical,
                     POOL + pool_index(back.object_slot) * REC + 0x20, 0)
            put_word(machine.mem.physical,
                     POOL + pool_index(body.object_slot) * REC + 0x20,
                     body.timer)
            for enemy in world.enemies:
                base = POOL + pool_index(enemy.object_slot) * REC
                if isinstance(enemy, DobkeratopsArenaAnchor):
                    enemy.activation_timer = 2
                    put_word(machine.mem.physical, base + 0x22, 2)
                elif isinstance(enemy, DobkeratopsTentacle):
                    enemy.intro_timer = 2
                    put_word(machine.mem.physical, base + 0x26, 2)
        elif frame == 3:
            body = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBody))
            body.timer = 1
            put_word(machine.mem.physical,
                     POOL + pool_index(body.object_slot) * REC + 0x20, 1)
        elif frame == 4:
            body = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBody))
            body.timer = 2
            put_word(machine.mem.physical,
                     POOL + pool_index(body.object_slot) * REC + 0x20, 2)
            tip = next(enemy for enemy in world.enemies
                       if isinstance(enemy, DobkeratopsTentacle) and enemy.tip)
            tip.fire_counter = (tip.fire_a - 1) & 0xFFFF
            put_word(machine.mem.physical,
                     POOL + pool_index(tip.object_slot) * REC + 0x2D,
                     tip.fire_counter)
        elif frame == 6:
            body = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBody))
            body.timer = 0x0031
            put_word(machine.mem.physical,
                     POOL + pool_index(body.object_slot) * REC + 0x20,
                     body.timer)
        if frame == death_frame:
            body = next(enemy for enemy in world.enemies
                        if isinstance(enemy, DobkeratopsBody))
            for enemy in world.enemies:
                if not isinstance(enemy, DobkeratopsTentacle):
                    continue
                enemy.cleanup_timer = 2 + (pool_index(enemy.object_slot) % 5)
                put_word(machine.mem.physical,
                         POOL + pool_index(enemy.object_slot) * REC + 0x28,
                         enemy.cleanup_timer)
            body.take_damage(world, 0xFFFF)
            index = pool_index(body.object_slot)
            machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                         max_steps=500_000)
            machine.set_byte(symbols["RTypeObjects_CurrentIndex"], index)
            machine.call(symbols["RTypeObjectBank2_BeginDobBodyDeath"],
                         max_steps=1_000_000)
            machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                         max_steps=500_000)

        machine.set_word(symbols["FrameCounter"], frame)
        machine.set_word(symbols["RTypeWorldFgDelta"], 0)
        machine.set_word(symbols["RTypeWorldBgDelta"], 0)
        run_bands(machine, symbols)
        terrain_code = lambda x, y: (  # noqa: E731
            word(expected_map, terrain_address(x, y)) & 0x0FFF)
        world.update(
            0, 0, frame, background_delta=0,
            terrain_code=terrain_code,
            collision_codes=lambda x, y: (terrain_code(x, y), 0),
            terrain_address=terrain_address,
            erase_terrain=erase,
            replace_terrain=replace,
            terrain_cell=terrain_cell,
        )

        seen_orb |= any(isinstance(enemy, DobkeratopsOrb)
                        for enemy in world.enemies)
        seen_trail |= any(isinstance(enemy, DobkeratopsOrbTrail)
                          for enemy in world.enemies)
        seen_projectile |= any(isinstance(enemy, EnemyProjectile)
                               for enemy in world.enemies)
        seen_debris |= any(isinstance(enemy, DobkeratopsDebrisE700)
                           for enemy in world.enemies)
        seen_cut |= any(
            isinstance(enemy, DobkeratopsDebrisE700) and
            enemy.terrain_timer == 0xFFFF
            for enemy in world.enemies)
        seen_component_explosion |= any(
            isinstance(enemy, DobkeratopsTentacle) and
            enemy.state == "cleanup_explosion_active"
            for enemy in world.enemies)
        check_frame(machine, world, expected_map, frame)

    assert (seen_orb and seen_trail and seen_projectile and seen_debris and
            seen_cut and seen_component_explosion), (
                seen_orb, seen_trail, seen_projectile, seen_debris,
                seen_cut, seen_component_explosion)
    print("$98FD/$9915: root, 25 parts, FIFO/resources/RNG exact")
    print("$9B26/$9C70/$9D9E: back, body, orb и equal-priority trails exact")
    print("$A035…$A22D: 18 links, tip aim/fire и delayed cleanup exact")
    print("$9D30/$E700/$9FE9: death records и terrain writers exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
