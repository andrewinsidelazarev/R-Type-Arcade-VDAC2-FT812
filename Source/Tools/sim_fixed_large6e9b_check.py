#!/usr/bin/env python3
"""Machine-vs-Python oracle fixed Stage 7 object `$6E9B/$6EC4`."""
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
    ExplosionEffect, FixedLarge6E9B, M72EnemyWorld,
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


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def fill_collision(machine: TSConfFT812Machine,
                   foreground: int, background: int) -> None:
    for page, code in ((PAGE7, foreground), (PAGE8, background)):
        cell = bytes((code & 0xFF, (code >> 8) & 0xFF, 0, 0))
        machine.mem.physical[page:page + 0x4000] = cell * (0x4000 // 4)


def check_live(machine: TSConfFT812Machine, world: M72EnemyWorld,
               enemy: FixedLarge6E9B, mark: object) -> None:
    memory = machine.mem.physical
    index = pool_index(enemy.object_slot)
    base = POOL + index * REC
    assert memory[base] == 55, mark
    assert word(memory, base + 0x02) == enemy.x, mark
    assert word(memory, base + 0x04) == enemy.y, mark
    assert word(memory, base + 0x06) == enemy.descriptor, mark
    assert memory[base + 0x08] == enemy.palette, mark
    assert word(memory, base + 0x0A) == 0xA000, mark
    assert memory[base + 0x10] == enemy.x_fraction, mark
    assert memory[base + 0x2F] == enemy.hp, mark
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark


def run_frame(machine: TSConfFT812Machine, symbols: dict[str, int],
              world: M72EnemyWorld, frame: int,
              foreground: int, background: int, delta: int) -> None:
    fill_collision(machine, foreground, background)
    machine.set_word(symbols["FrameCounter"], frame)
    machine.set_word(symbols["RTypeWorldFgDelta"], delta & 0xFFFF)
    machine.call(symbols["RTypeObjects_RunType"], a=55,
                 max_steps=10_000_000)
    world.update(
        0, delta, frame,
        terrain_code=lambda _x, _y: foreground,
        collision_codes=lambda _x, _y: (foreground, background))


def damage(machine: TSConfFT812Machine, symbols: dict[str, int],
           enemy: FixedLarge6E9B, amount: int) -> None:
    index = pool_index(enemy.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=1_000_000)
    machine.call(symbols["RTypeObjectBank3_DamageFixedLarge6E9B"],
                 a=amount, max_steps=20_000_000)
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
    for name in ("RTypeWorldFgScrollQ8", "RTypeWorldFgYScrollQ8",
                 "RTypeWorldBgScrollQ8", "RTypeWorldBgYScrollQ8"):
        machine.set_byte(symbols[name], 0)
        machine.set_byte(symbols[name] + 1, 0)
        machine.set_byte(symbols[name] + 2, 0)

    world = M72EnemyWorld(stage=7, full_event_stream=True)
    enemy = FixedLarge6E9B(world)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(enemy, slot)
    world.enemies = [enemy]
    world.event_pointer = world.event_last
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x6E9B)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0x9800)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=8_000_000)
    check_live(machine, world, enemy, "init")
    assert (enemy.x, enemy.y, enemy.hp, enemy.descriptor) == (
        0x0110, 0x0108, 0xC8, 0x3042)

    # Обе карты свободны: после scroll -1 выполняется Q8 `+$00C0`.
    run_frame(machine, symbols, world, 0, 0x0FFF, 0x07D0, -1)
    check_live(machine, world, enemy, "free-probe")
    assert (enemy.x, enemy.x_fraction) == (0x010F, 0xC0)

    # Solid foreground блокирует Q8, но integer scroll продолжает двигать X.
    run_frame(machine, symbols, world, 1, 0x0001, 0x07D0, -1)
    check_live(machine, world, enemy, "blocked-probe")
    assert (enemy.x, enemy.x_fraction) == (0x010E, 0xC0)

    # Нефатальное повреждение меняет только буквальный byte HP.
    enemy.take_damage(world, 1)
    damage(machine, symbols, enemy, 1)
    check_live(machine, world, enemy, "damage")
    assert enemy.hp == 0xC7

    # Фатальная ветка использует overlapping windows `(word[i],word[i+1])`:
    # 18 `$F000/$E7B6`, затем текущий slot становится `$A000/$E817`.
    enemy.take_damage(world, 0xC7)
    damage(machine, symbols, enemy, 0xC7)
    debris = [item for item in world.pending
              if isinstance(item, ExplosionEffect)]
    assert len(debris) == 18
    memory = machine.mem.physical
    active = [index for index in range(2, 96)
              if memory[POOL + index * REC] != 0]
    assert len(active) == 19
    parent_base = POOL + pool_index(slot) * REC
    assert memory[parent_base] == 31
    assert word(memory, parent_base + 0x0A) == 0xA000
    assert word(memory, parent_base + 0x20) == 0x85FA
    assert memory[parent_base + 0x09] == 0x01
    for blast in debris:
        base = POOL + pool_index(blast.object_slot) * REC
        assert memory[base] == 31
        assert word(memory, base + 0x02) == blast.x
        assert word(memory, base + 0x04) == blast.y
        assert word(memory, base + 0x0A) == 0xF000
        assert word(memory, base + 0x20) == 0x8506
    assert memory[TYPES] == 0x01 and memory[REFS] == 19

    print("$6E9B init: fixed coordinates, 200 HP и resource `$54` exact")
    print("$6EC4: FG/BG gate, scroll и Q8 `+$00C0` exact")
    print("$6F32: `$E817` + 18 overlapping `$F000/$E7B6` records exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
