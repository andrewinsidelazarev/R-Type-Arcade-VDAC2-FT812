#!/usr/bin/env python3
"""Machine-vs-Python oracle семейства `$A71D…$B1D7`."""
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
    AttachedAC4C, DebrisAEFB, ExplosionEffect, Handler5CEAShot,
    M72EnemyWorld, MultipartA71DBody, MultipartA71DController,
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


def check_controller(memory: bytearray, controller: MultipartA71DController,
                     mark: object) -> None:
    base = POOL + pool_index(controller.object_slot) * REC
    state = {"spawn": 0, "active": 1, "exit": 2}[controller.state]
    assert memory[base] == 60, (mark, memory[base], pool_index(
        controller.object_slot))
    assert word(memory, base + 0x0A) == controller.scheduler_priority, mark
    assert word(memory, base + 0x20) == controller.selector, mark
    assert memory[base + 0x22] == controller.completed_mask, mark
    assert memory[base + 0x23] == controller.arrived_mask, mark
    assert memory[base + 0x24] == int(controller.advance_signal), mark
    assert memory[base + 0x0E] == state, mark
    assert word(memory, base + 0x26) == controller.exit_timer, mark


def check_body(memory: bytearray, body: MultipartA71DBody,
               mark: object) -> None:
    base = POOL + pool_index(body.object_slot) * REC
    kind = {"upper": 0, "middle": 1, "lower": 2}[body.body_kind]
    state = {"active": 0, "debris": 1}[body.state]
    assert memory[base] == 61, mark
    assert word(memory, base + 0x02) == body.x, mark
    assert word(memory, base + 0x04) == body.y, mark
    assert word(memory, base + 0x06) == body.descriptor, mark
    assert memory[base + 0x08] == body.palette, mark
    assert word(memory, base + 0x0A) == body.scheduler_priority, mark
    assert memory[base + 0x0E] == state, mark
    assert memory[base + 0x10] == body.x_fraction, mark
    assert memory[base + 0x11] == body.y_fraction, mark
    assert word(memory, base + 0x12) == body.x_velocity & 0xFFFF, mark
    assert word(memory, base + 0x14) == body.y_velocity & 0xFFFF, mark
    assert memory[base + 0x20] == pool_index(body.controller.object_slot), mark
    assert memory[base + 0x21] == kind, mark
    assert memory[base + 0x22] == body.bit, mark
    assert word(memory, base + 0x24) == body.route_list, mark
    assert word(memory, base + 0x26) == body.motion_pointer, mark
    assert word(memory, base + 0x28) == body.motion_timer, mark
    assert memory[base + 0x2A] == body.phase, mark
    assert memory[base + 0x2B] == body.flash_timer, mark
    assert memory[base + 0x2C] == body.alt_palette, mark
    assert memory[base + 0x2D] == body.fire_reload, mark
    assert memory[base + 0x2E] == body.fire_timer, mark
    assert word(memory, base + 0x30) == body.debris_root, mark
    assert word(memory, base + 0x32) == body.debris_pointer, mark
    assert word(memory, base + 0x34) == body.debris_timer, mark
    assert word(memory, base + 0x36) == body.pair_timer, mark
    assert word(memory, base + 0x38) == body.hp & 0xFFFF, mark


def check_attachment(memory: bytearray, item: AttachedAC4C,
                     mark: object) -> None:
    base = POOL + pool_index(item.object_slot) * REC
    assert memory[base] == 62, mark
    assert word(memory, base + 0x02) == item.x, mark
    assert word(memory, base + 0x04) == item.y, mark
    assert word(memory, base + 0x06) == item.descriptor, mark
    assert memory[base + 0x08] == item.palette, mark
    assert word(memory, base + 0x20) == item.fire_counter, mark
    assert word(memory, base + 0x22) == item.fire_a, mark
    assert word(memory, base + 0x24) == item.fire_b, mark
    assert word(memory, base + 0x26) == item.projectile_script, mark
    assert memory[base + 0x28] == pool_index(item.source.object_slot), mark
    assert word(memory, base + 0x2A) == item.dx & 0xFFFF, mark
    assert word(memory, base + 0x2C) == item.dy & 0xFFFF, mark
    assert word(memory, base + 0x2E) == item.orientation, mark
    assert memory[base + 0x30] == item.alt_palette, mark


def call_record(machine: TSConfFT812Machine, symbols: dict[str, int],
                slot: int, trampoline: str, *, a: int | None = None) -> None:
    index = pool_index(slot)
    machine.set_byte(symbols["RTypeObjects_CurrentIndex"], index)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=500_000)
    machine.call(symbols[trampoline], a=a, max_steps=4_000_000)
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

    world = M72EnemyWorld(stage=5, full_event_stream=True)
    controller = MultipartA71DController(world)
    slot = world.object_pool.take()
    assert slot is not None
    world.object_pool.bind(controller, slot)
    world.enemies = [controller]
    machine.set_word(symbols["RTypePlayerNativeX"], world.player_native[0])
    machine.set_word(symbols["RTypePlayerNativeY"], world.player_native[1])
    machine.set_word(symbols["RTypeWorldLastHandler"], 0xA71D)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=4_000_000)
    memory = machine.mem.physical
    check_controller(memory, controller, "controller-init")
    check_resources(memory, world, "controller-init-resources")

    machine.call(symbols["RTypeObjects_RunType"], a=60,
                 max_steps=8_000_000)
    controller.update(world, 0)
    children = list(world.pending)
    bodies = [item for item in children if isinstance(item, MultipartA71DBody)]
    attachments = [item for item in children if isinstance(item, AttachedAC4C)]
    assert len(bodies) == 3 and len(attachments) == 3
    check_controller(memory, controller, "spawn-controller")
    for item in bodies:
        check_body(memory, item, ("spawn-body", item.body_kind))
    for item in attachments:
        check_attachment(memory, item, ("spawn-attachment", item.dx, item.dy))
    check_resources(memory, world, "spawn-resources")
    assert tuple(item.route_list for item in bodies) == (
        0x5B0E, 0x5B2C, 0x5B4A)
    assert tuple(item.motion_pointer for item in bodies) == (
        0x5B54, 0x5B54, 0x5B54)
    world.pending.clear()
    upper, middle, lower = bodies

    call_record(machine, symbols, upper.object_slot,
                "RTypeObjectBank3_UpdateMultipartA71DBody")
    upper.update(world, 0)
    check_body(memory, upper, "upper-q8")
    assert (upper.x, upper.x_fraction, upper.motion_timer) == (
        0x0101, 0, 0x015F)

    # Все три timer=0 устанавливают arrived mask; controller после них даёт
    # общий advance_signal ровно на один проход.
    for body in bodies:
        body.motion_timer = 0
        base = POOL + pool_index(body.object_slot) * REC
        put_word(memory, base + 0x28, 0)
        call_record(machine, symbols, body.object_slot,
                    "RTypeObjectBank3_UpdateMultipartA71DBody")
        body.update(world, 0)
    check_controller(memory, controller, "arrived-mask")
    machine.call(symbols["RTypeObjects_RunType"], a=60,
                 max_steps=2_000_000)
    controller.update(world, 0)
    check_controller(memory, controller, "advance-signal")
    assert controller.advance_signal
    call_record(machine, symbols, upper.object_slot,
                "RTypeObjectBank3_UpdateMultipartA71DBody")
    upper.update(world, 0)
    check_body(memory, upper, "upper-next-route")
    check_controller(memory, controller, "controller-after-route")
    assert (upper.motion_pointer, upper.x_velocity,
            upper.y_velocity, upper.motion_timer) == (
                0x5DCC, -0x0180, 0, 0x0080)

    # Прямой shot верхнего тела использует difficulty-zero `$0300`.
    upper.fire_timer = 1
    upper_base = POOL + pool_index(upper.object_slot) * REC
    memory[upper_base + 0x2E] = 1
    world.player_native = (0x0200, upper.y)
    machine.set_word(symbols["RTypePlayerNativeX"], 0x0200)
    machine.set_word(symbols["RTypePlayerNativeY"], upper.y)
    call_record(machine, symbols, upper.object_slot,
                "RTypeObjectBank3_UpdateMultipartA71DBody")
    upper.update(world, 0)
    shots = [item for item in world.pending if isinstance(item, Handler5CEAShot)]
    assert len(shots) == 1
    shot = shots[0]
    shot_base = POOL + pool_index(shot.object_slot) * REC
    assert memory[shot_base] == 47
    assert word(memory, shot_base + 0x02) == shot.x
    assert word(memory, shot_base + 0x04) == shot.y
    assert word(memory, shot_base + 0x12) == shot.x_velocity & 0xFFFF
    assert shot.x_velocity == 0x0300
    check_controller(memory, controller, "controller-after-fire")
    check_resources(memory, world, "straight-shot")
    world.pending.clear()

    # Fatal hit переводит body в 64-pass debris state и отмечает completed.
    call_record(machine, symbols, upper.object_slot,
                "RTypeObjectBank3_DamageMultipartA71DBody", a=0x28)
    upper.take_damage(world, 0x28)
    check_body(memory, upper, "fatal-body-hit")
    check_controller(memory, controller, "fatal-completed")
    assert (upper.state, upper.debris_timer, upper.palette) == (
        "debris", 0x40, 0xFF)
    check_resources(memory, world, "fatal-resources")

    machine.set_word(symbols["FrameCounter"], 2)
    world.frame_counter = 2
    call_record(machine, symbols, upper.object_slot,
                "RTypeObjectBank3_UpdateMultipartA71DBody")
    upper.update(world, 0)
    effects = [item for item in world.pending if isinstance(item, ExplosionEffect)]
    assert len(effects) == 1
    effect = effects[0]
    effect_base = POOL + pool_index(effect.object_slot) * REC
    assert memory[effect_base] == 31
    assert word(memory, effect_base + 0x02) == effect.x
    assert word(memory, effect_base + 0x04) == effect.y
    assert word(memory, effect_base + 0x20) == effect.sequence_pointer
    check_resources(memory, world, "body-explosion")
    world.pending.clear()

    # Lower timer `$0F->$10` создаёт две RNG-баллистики с phase 0/6.
    lower.y = 0x00A0
    lower.pair_timer = 0x0F
    lower_base = POOL + pool_index(lower.object_slot) * REC
    put_word(memory, lower_base + 0x04, lower.y)
    put_word(memory, lower_base + 0x36, lower.pair_timer)
    call_record(machine, symbols, lower.object_slot,
                "RTypeObjectBank3_UpdateMultipartA71DBody")
    lower.update(world, 0)
    pairs = [item for item in world.pending if isinstance(item, DebrisAEFB)]
    assert len(pairs) == 2
    for item in pairs:
        base = POOL + pool_index(item.object_slot) * REC
        assert memory[base] == 63
        assert word(memory, base + 0x02) == item.x
        assert word(memory, base + 0x04) == item.y
        assert word(memory, base + 0x06) == item.descriptor + item.phase_offset
        assert word(memory, base + 0x12) == item.x_velocity & 0xFFFF
        assert word(memory, base + 0x14) == item.y_velocity & 0xFFFF
        assert word(memory, base + 0x22) == item.phase_offset
    check_resources(memory, world, "paired-debris")

    print("$A71D/$A762: selector, three routed bodies и three `$AC4C` exact")
    print("$AA0F/$AB62/$ACE7: Q8 route barrier, straight fire и fatal debris exact")
    print("$AEFB/$AF6F: paired RNG velocities, resources и phase roots exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
