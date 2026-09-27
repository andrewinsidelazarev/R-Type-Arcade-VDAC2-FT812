#!/usr/bin/env python3
"""Machine-vs-Python oracle terrain controller `$8C12…$8D54`."""
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
    ExplosionEffect, M72EnemyWorld, StageObject8C12,
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


def terrain_address(x: int, y: int) -> int:
    """Буквальная `$1E6C`-адресация при нулевых FG X/Y scroll."""
    horizontal = ((x - 0x0140) & 0xFFFF) >> 1
    horizontal &= 0xFFFC
    address = (0x1020 + horizontal) & 0x10FF
    vertical = 0x017F - y
    if vertical < 0:
        vertical = 0
    return (address + ((vertical & 0xFFF8) << 5)) & 0x3FFF


def replace_terrain(expected_map: bytearray, address: int,
                    code: int, attribute: int) -> None:
    address &= 0x3FFF
    put_word(expected_map, address, code)
    put_word(expected_map, (address + 2) & 0x3FFF, attribute)


def check(machine: TSConfFT812Machine, world: M72EnemyWorld,
          expected_map: bytearray, mark: object) -> None:
    memory = machine.mem.physical
    expected = {pool_index(enemy.object_slot): enemy for enemy in world.enemies
                if enemy.object_slot is not None}
    active = {index for index in range(2, 96)
              if memory[POOL + index * REC] != 0}
    assert active == set(expected), (mark, active, set(expected))
    for index, enemy in expected.items():
        base = POOL + index * REC
        if isinstance(enemy, StageObject8C12):
            assert memory[base] == 54, mark
            assert word(memory, base + 0x02) == enemy.x, mark
            assert word(memory, base + 0x04) == enemy.y, mark
            assert word(memory, base + 0x20) == enemy.terrain_path, mark
            assert word(memory, base + 0x22) == enemy.timer, mark
            assert memory[base + 0x24] == enemy.phase, mark
        elif isinstance(enemy, ExplosionEffect):
            assert memory[base] == 31, mark
            assert word(memory, base + 0x02) == enemy.x, mark
            assert word(memory, base + 0x04) == enemy.y, mark
            assert word(memory, base + 0x06) == enemy.descriptor, mark
            assert memory[base + 0x08] == enemy.palette, mark
            assert word(memory, base + 0x0A) == 0x8010, mark
            assert word(memory, base + 0x20) == enemy.sequence_pointer, mark
            assert word(memory, base + 0x22) == enemy.sequence_timer, mark
            expected_resource = 0x63 if enemy.effect == "e80c" else 0x01
            assert memory[base + 0x09] == expected_resource, mark
        else:
            raise AssertionError((mark, type(enemy).__name__))
    assert machine.mem.physical[PAGE7:PAGE7 + 0x4000] == expected_map, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, expected_map: bytearray,
              frame: int, delta: int) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    # Explosion `$8010` уже прошёл, когда controller `$DFFF` создаёт новый.
    machine.call(symbols["RTypeObjects_RunType"], a=31,
                 max_steps=10_000_000)
    machine.call(symbols["RTypeObjects_RunType"], a=54,
                 max_steps=10_000_000)
    world.update(
        0, delta, frame,
        terrain_code=lambda _x, _y: 0x0FFF,
        terrain_address=terrain_address,
        replace_terrain=lambda address, code, attr: replace_terrain(
            expected_map, address, code, attr))


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)
    expected_map = bytearray(
        bytes((0xFF, 0x0F, 0, 0)) * (0x4000 // 4))
    machine.mem.physical[PAGE7:PAGE7 + 0x4000] = expected_map

    world = M72EnemyWorld(stage=7, full_event_stream=True)
    command = 0x4000
    control = StageObject8C12(world, command)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(control, slot)
    world.enemies = [control]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x8C12)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=6_000_000)
    check(machine, world, expected_map, "init")
    assert (control.x, control.y, control.terrain_path, control.timer) == (
        0x02C0, 0x009C, 0x3C5E, 8)

    # Восемь pass одновременно сдвигают anchor скроллом. Только восьмой
    # создаёт первый `$E7BE` и ставит interval `$0010`.
    for frame in range(8):
        run_frame(machine, symbols, world, expected_map, frame, -1)
        check(machine, world, expected_map, ("countdown", frame))
    blasts = [item for item in world.enemies
              if isinstance(item, ExplosionEffect)]
    assert len(blasts) == 1
    assert (control.phase, control.timer,
            blasts[0].x, blasts[0].y, blasts[0].effect) == (
                1, 0x10, 0x02B4, 0x00AA, "e7be")

    # Прямо выбираем последнюю фазу: интервалы предыдущих фаз уже проверены
    # как записываемые literals, а здесь важны `$E80C` и bytewise ring path.
    control.phase = 3
    control.timer = 1
    base = POOL + pool_index(control.object_slot) * REC
    machine.mem.physical[base + 0x24] = 3
    put_word(machine.mem.physical, base + 0x22, 1)
    run_frame(machine, symbols, world, expected_map, 8, 0)
    check(machine, world, expected_map, "terrain-path")
    effects = sorted(item.effect for item in world.enemies
                     if isinstance(item, ExplosionEffect))
    assert effects == ["e7be", "e80c"]
    assert control.phase == 4 and control.timer == 0x20

    # Общий cleanup освобождает оба explosion resources и невидимый owner.
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run_frame(machine, symbols, world, expected_map, 9, 0)
    check(machine, world, expected_map, "cleanup")
    assert not world.enemies

    print("$8C12 init: `$93C4`, doubled RNG timer и priority `$DFFF` exact")
    print("$8C2E: four-phase offsets/intervals и `$E7BE/$E80C` allocation exact")
    print("$8D54: bytewise delta, 14-bit ring mask и attribute `$000A` exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
