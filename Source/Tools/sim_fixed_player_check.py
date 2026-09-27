#!/usr/bin/env python3
"""Покадровый oracle собранного Z80-банка Force/Bits против активного Python."""
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

from rtype_port.bits import PlayerBits  # noqa: E402
from rtype_port.enemies import M72EnemyWorld  # noqa: E402
from rtype_port.force import Force, ForceInput  # noqa: E402
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


BIT_ACTIVE = 0
BIT_X_Q8 = 1
BIT_Y_Q8 = 4
BIT_PALETTE = 7
BIT_ANIMATION = 8
BIT_STRENGTH = 9
BIT_IDLE = 10
BIT_WRITE = 11
BIT_READ = 12
BIT_DESCRIPTOR = 13
BIT_HISTORY_X = 15
BIT_HISTORY_Y = 47


def word(machine: TSConfFT812Machine, address: int) -> int:
    return machine.get_byte(address) | (machine.get_byte(address + 1) << 8)


def q8(machine: TSConfFT812Machine, address: int) -> int:
    return (word(machine, address + 1) << 8) | machine.get_byte(address)


def compare_force(machine: TSConfFT812Machine, sym: dict[str, int],
                  force: Force, frame: int) -> None:
    states = {"hidden": 0, "return": 1, "attached": 2, "detached": 3}
    assert machine.get_byte(sym["ArcadeForceLevel"]) == force.level, frame
    assert machine.get_byte(sym["ArcadeForceState"]) == states[force.state], frame
    assert q8(machine, sym["ArcadeForceXQ8"]) == (force.x_q8 & 0xFFFFFF), frame
    assert q8(machine, sym["ArcadeForceYQ8"]) == (force.y_q8 & 0xFFFFFF), frame
    assert word(machine, sym["ArcadeForceVelocityX"]) == (force.velocity_x & 0xFFFF), frame
    assert word(machine, sym["ArcadeForceVelocityY"]) == (force.velocity_y & 0xFFFF), frame
    assert bool(machine.get_byte(sym["ArcadeForceBehind"])) == force.behind, frame
    assert bool(machine.get_byte(sym["ArcadeForceReturnHistory"])) == force.return_history, frame
    assert bool(machine.get_byte(sym["ArcadeForceAttached"])) == force.attached, frame
    assert machine.get_byte(sym["ArcadeForceAnimation"]) == force.animation, frame
    assert word(machine, sym["ArcadeForceDescriptor"]) == force.descriptor, frame
    assert q8(machine, sym["ArcadeForceOldXQ8"]) == (force.old_x_q8 & 0xFFFFFF), frame
    assert word(machine, sym["ArcadeForceLastVertical"]) == (force.last_vertical & 0xFFFF), frame
    assert machine.get_byte(sym["ArcadeForcePalette"]) == force.resource_slot, frame


def compare_bits(machine: TSConfFT812Machine, sym: dict[str, int],
                 bits: PlayerBits, frame: int) -> None:
    for index, label in enumerate(("ArcadeBit0Record", "ArcadeBit1Record")):
        base = sym[label]
        expected = bits.objects.get(index)
        assert bool(machine.get_byte(base + BIT_ACTIVE)) == (expected is not None), frame
        if expected is None:
            continue
        assert q8(machine, base + BIT_X_Q8) == (expected.x_q8 & 0xFFFFFF), frame
        assert q8(machine, base + BIT_Y_Q8) == (expected.y_q8 & 0xFFFFFF), frame
        assert machine.get_byte(base + BIT_PALETTE) == expected.resource_slot, frame
        assert machine.get_byte(base + BIT_ANIMATION) == expected.animation, frame
        assert machine.get_byte(base + BIT_STRENGTH) == expected.strength, frame
        assert machine.get_byte(base + BIT_IDLE) == expected.idle_counter, frame
        assert machine.get_byte(base + BIT_WRITE) == expected.write_cursor, frame
        assert machine.get_byte(base + BIT_READ) == expected.read_cursor, frame
        assert word(machine, base + BIT_DESCRIPTOR) == expected.descriptor, frame
        actual_x = [word(machine, base + BIT_HISTORY_X + item * 2)
                    for item in range(16)]
        actual_y = [word(machine, base + BIT_HISTORY_Y + item * 2)
                    for item in range(16)]
        assert actual_x == expected.history_x, frame
        assert actual_y == expected.history_y, frame


def main() -> None:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(sym["RTypeObjects_Reset"], max_steps=2_000_000)
    machine.call(sym["RTypeSpriteCache_Reset"], max_steps=2_000_000)
    machine.call(sym["RTypeWorld_ClearMaps"], max_steps=2_000_000)
    machine.call(sym["ArcadeFixedPlayer_Init"], max_steps=2_000_000)

    world = M72EnemyWorld(stage=1, full_event_stream=True)
    force = Force(world.rom)
    bits = PlayerBits(world.rom)
    history = [(0x01B0, 0x0100)] * 16
    player_x, player_y = 0x01B0, 0x0100
    held = False
    initial_recall_sent = False
    detached_once = False
    return_edge_sent = False

    blank_codes = lambda _x, _y: (0x0FA0, 0x0FA0)
    blank_cell = lambda _address: (0x0FA0, 0)
    address = lambda _x, _y: 0x1020
    no_write = lambda _address, _code, _attribute: None

    for frame in range(1, 321):
        # Детерминированный native маршрут проверяет все 16 direction nibble.
        phase = (frame // 11) & 15
        right = bool(phase & 1)
        left = bool(phase & 2)
        down = bool(phase & 4)
        up = bool(phase & 8)
        direction = phase
        # Anchor намеренно неподвижен: direction nibble всё равно проходит все
        # комбинации и раскачивает Bits, а Force гарантированно успевает пройти
        # return -> attached -> detached -> return без ухода цели.
        level = 1 if frame < 115 else (2 if frame < 215 else 3)
        bit_count = 0 if frame < 18 else (1 if frame < 95 else
                                         (2 if frame < 340 else 0))
        action = False
        if frame == 2:
            action = True                    # `$24F5`: возврат к history R-9
            initial_recall_sent = True
        elif force.state == "attached" and not detached_once:
            action = True
            detached_once = True
        elif (detached_once and force.state == "return" and
              not return_edge_sent and frame > 80):
            action = True
            return_edge_sent = True

        target_input = ((1 if left else 0) | (2 if right else 0) |
                        (4 if up else 0) | (8 if down else 0) |
                        (0x20 if action else 0))
        machine.set_word(sym["FrameCounter"], frame)
        machine.set_word(sym["RTypePlayerNativeX"], player_x)
        machine.set_word(sym["RTypePlayerNativeY"], player_y)
        machine.set_byte(sym["InputState"], target_input)
        machine.set_byte(sym["ArcadeForceRequestedLevel"], level)
        machine.set_byte(sym["ArcadeBitCount"], bit_count)
        machine.call(sym["ArcadeForce_Update"], max_steps=5_000_000)

        history.append((player_x, player_y))
        del history[0]
        edge = action and not held
        held = action
        changed = force.sync_level(
            level, world.resources.acquire, world.resources.release)
        if not changed:
            force.update(
                (player_x, player_y), tuple(history),
                ForceInput(edge, direction), frame, blank_codes,
                address, blank_cell, no_write, 0, None, address, blank_cell)
        bits.sync_and_update(
            bit_count, (player_x, player_y), direction, frame,
            world.resources.acquire, world.resources.release,
            address, blank_cell, no_write)

        compare_force(machine, sym, force, frame)
        compare_bits(machine, sym, bits, frame)
        assert machine.get_byte(sym["ArcadeBitsLastDirection"]) == bits.last_direction

    assert initial_recall_sent, "не проверен первый return-history edge"
    assert detached_once, "Force ни разу не пристыковался/не отделился"
    assert return_edge_sent, "не проверен action edge в return state"
    print("FIXED PLAYER Z80 ORACLE OK: 320 frames, Force levels 1/2/3, two Bits")


if __name__ == "__main__":
    main()
