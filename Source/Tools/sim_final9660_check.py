#!/usr/bin/env python3
"""Machine-vs-Python oracle финального spawner-а `$9660/$96E9`."""
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
    ExplosionEffect, FinalProjectile9660, FinalSpawner9660, M72EnemyWorld,
)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

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


def check_resources(memory: bytearray, world: M72EnemyWorld,
                    mark: object) -> None:
    assert list(memory[TYPES:TYPES + 16]) == world.resources.types, mark
    assert list(memory[REFS:REFS + 16]) == world.resources.refs, mark
    assert tuple(memory[RNG:RNG + 3]) == (
        world.rng.a, world.rng.b, world.rng.c), mark


def check_spawner(memory: bytearray, spawner: FinalSpawner9660,
                  mark: object) -> None:
    base = POOL + pool_index(spawner.object_slot) * REC
    assert memory[base] == 58, mark
    assert word(memory, base + 0x02) == spawner.x, mark
    assert word(memory, base + 0x04) == spawner.y, mark
    assert word(memory, base + 0x0A) == spawner.scheduler_priority, mark
    assert word(memory, base + 0x20) == spawner.period, mark
    assert word(memory, base + 0x22) == spawner.timer, (
        mark, hex(word(memory, base + 0x22)), hex(spawner.timer))
    assert memory[base + 0x08] == 0xFF, mark
    assert memory[base + 0x09] == 0xFF, mark


def check_child(memory: bytearray, child: FinalProjectile9660,
                mark: object) -> None:
    base = POOL + pool_index(child.object_slot) * REC
    assert memory[base] == 59, mark
    assert word(memory, base + 0x02) == child.x, mark
    assert word(memory, base + 0x04) == child.y, mark
    assert word(memory, base + 0x06) == child.descriptor, mark
    assert word(memory, base + 0x0A) == child.scheduler_priority, mark
    assert memory[base + 0x10] == child.x_fraction, mark
    assert memory[base + 0x11] == child.y_fraction, mark
    assert word(memory, base + 0x12) == child.x_velocity & 0xFFFF, mark
    assert word(memory, base + 0x14) == child.y_velocity & 0xFFFF, mark
    assert word(memory, base + 0x20) == child.descriptor_base, mark
    assert world_resource_type(memory, base + 0x08) == 0x60, mark


def world_resource_type(memory: bytearray, palette_address: int) -> int:
    palette = memory[palette_address]
    return memory[TYPES + palette] if palette < 16 else 0xFF


def update_child(machine: TSConfFT812Machine, symbols: dict[str, int],
                 child: FinalProjectile9660) -> None:
    index = pool_index(child.object_slot)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=500_000)
    machine.call(symbols["RTypeObjectBank3_UpdateFinalProjectile96E9"],
                 max_steps=2_000_000)
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

    world = M72EnemyWorld(stage=8, full_event_stream=True)
    spawner = FinalSpawner9660(world, 0xAC12)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(spawner, slot)
    world.enemies = [spawner]
    machine.set_word(symbols["RTypeWorldLastHandler"], 0x9660)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0xAC12)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=4_000_000)
    memory = machine.mem.physical
    check_spawner(memory, spawner, "init")
    check_resources(memory, world, "init-resources")

    # На spawn-pass background delta применяется раньше timer. Направление
    # считается уже из сдвинутой позиции к тем же native-координатам R-9.
    world.background_delta = -1
    spawner.timer = 1
    base = POOL + pool_index(spawner.object_slot) * REC
    machine.set_word(symbols["RTypeWorldBgDelta"], 0xFFFF)
    machine.set_word(symbols["RTypePlayerNativeX"], world.player_native[0])
    machine.set_word(symbols["RTypePlayerNativeY"], world.player_native[1])
    put_word(memory, base + 0x22, 1)
    machine.call(symbols["RTypeObjects_RunType"], a=58,
                 max_steps=2_000_000)
    spawner.update(world, 0)
    check_spawner(memory, spawner, "spawn-parent")
    assert len(world.pending) == 1
    child = world.pending[0]
    assert isinstance(child, FinalProjectile9660)
    check_child(memory, child, "spawn-child")
    assert (child.x_velocity, child.y_velocity,
            child.descriptor_base) == (-0x0250, 0x0100, 0x4348)
    check_resources(memory, world, "spawn-resources")

    machine.set_word(symbols["FrameCounter"], 8)
    world.frame_counter = 8
    update_child(machine, symbols, child)
    child.update(world, 0)
    check_child(memory, child, "q8-animation")
    assert (child.x, child.x_fraction, child.y, child.y_fraction,
            child.descriptor) == (0x02BC, 0xB0, 0x009D, 0, 0x434E)

    # Один weapon hit заменяет запись in-place. После одного общего `$E7D4`
    # pass machine и Python должны удерживать resource `$6B` и timer=1.
    child_index = pool_index(child.object_slot)
    child.take_damage(world, 1)
    world.pending.clear()
    world.enemies = [child]
    world.update(0, 0, 8)
    explosion = world.enemies[0]
    assert isinstance(explosion, ExplosionEffect)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=child_index,
                 max_steps=500_000)
    machine.call(symbols["RTypeObjectBank3_DamageFinalProjectile96E9"], a=1,
                 max_steps=2_000_000)
    machine.call(symbols["RTypeObjects_StoreScratch"], a=child_index,
                 max_steps=500_000)
    machine.set_word(symbols["RTypeWorldFgDelta"], 0)
    machine.call(symbols["RTypeObjects_RunType"], a=31,
                 max_steps=2_000_000)
    base = POOL + child_index * REC
    assert memory[base] == 31
    assert word(memory, base + 0x02) == explosion.x
    assert word(memory, base + 0x04) == explosion.y
    assert word(memory, base + 0x06) == explosion.descriptor
    assert word(memory, base + 0x20) == explosion.sequence_pointer
    assert word(memory, base + 0x22) == explosion.sequence_timer
    assert world_resource_type(memory, base + 0x08) == 0x6B
    check_resources(memory, world, "death-resource-6b")

    print("$9660/$9674: command Y, `$943C` period, RNG mask и BG delta exact")
    print("$96E9/$9703: `$1D89`, difficulty-zero Q8 и two-frame descriptor exact")
    print("$973F/$E7D4: in-place resource `$60->$6B` explosion exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
