#!/usr/bin/env python3
"""Oracle для event `$F366` и невидимого timer `$F3C1`."""
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
    M72EnemyWorld, StageEvent, TimedControlF3C1)
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

PAGE9 = 0x09 * 0x4000
POOL = PAGE9
REC = 0x40


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // REC


def dispatch(machine: TSConfFT812Machine, symbols: dict[str, int],
             world: M72EnemyWorld) -> TimedControlF3C1:
    event = StageEvent(0, 0, 0, 0xF366)
    world._dispatch(event)
    world.enemies.extend(world.pending)
    world.pending.clear()
    machine.set_word(symbols["RTypeWorldLastHandler"], 0xF366)
    machine.set_word(symbols["RTypeWorldLastCommand"], 0)
    machine.call(symbols["RTypeObjects_DispatchEvent"],
                 max_steps=3_000_000)
    return next(enemy for enemy in world.enemies
                if isinstance(enemy, TimedControlF3C1))


def check(machine: TSConfFT812Machine, symbols: dict[str, int],
          world: M72EnemyWorld, timer: TimedControlF3C1 | None,
          mark: object) -> None:
    memory = machine.mem.physical
    active = [index for index in range(2, 96)
              if memory[POOL + index * REC] != 0]
    expected = [pool_index(enemy.object_slot) for enemy in world.enemies
                if enemy.object_slot is not None]
    assert active == expected, (mark, active, expected)
    if timer is not None and timer.alive:
        base = POOL + pool_index(timer.object_slot) * REC
        assert memory[base] == 43, mark
        assert word(memory, base + 0x0A) == 0x1000, mark
        assert word(memory, base + 0x10) == timer.timer, mark
        assert word(memory, base + 0x12) == timer.sound_command, (
            mark, "sound", hex(word(memory, base + 0x12)),
            hex(timer.sound_command))
    assert machine.get_byte(symbols["RTYPE_ACTIVE_PLAYER"]) == (
        1 if world.active_player else 0), mark
    assert [machine.get_byte(symbols["RTYPE_TRANSITION_FLAGS"] + i)
            for i in range(2)] == world.stage_transition_flags, mark
    assert machine.get_byte(symbols["RTYPE_TRANSITION_SOUND_INDEX"]) == (
        world.transition_sound_index & 0xFF), mark
    assert machine.get_byte(symbols["RTYPE_LAST_SOUND_COMMAND"]) == (
        world.sound_commands[-1] & 0xFF), mark


def run(machine: TSConfFT812Machine, symbols: dict[str, int],
        world: M72EnemyWorld, frame: int) -> None:
    machine.set_word(symbols["FrameCounter"], frame)
    machine.call(symbols["RTypeObjects_RunType"], a=43,
                 max_steps=3_000_000)
    world.update(0, 0, frame)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    world = M72EnemyWorld(stage=2, full_event_stream=True)
    world.event_pointer = world.event_last

    first = dispatch(machine, symbols, world)
    check(machine, symbols, world, first, "first-dispatch")
    assert (first.timer, first.sound_command) == (0x0180, 0x20)
    first.timer = 2
    put_word(machine.mem.physical,
             POOL + pool_index(first.object_slot) * REC + 0x10, 2)
    run(machine, symbols, world, 1)
    check(machine, symbols, world, first, "first-wait")
    run(machine, symbols, world, 2)
    check(machine, symbols, world, None, "first-finish")

    world.transition_sound_index = 3
    machine.set_byte(symbols["RTYPE_TRANSITION_SOUND_INDEX"], 3)
    repeat = dispatch(machine, symbols, world)
    check(machine, symbols, world, repeat, "repeat-dispatch")
    assert repeat.timer == 0x0100
    world.cleanup_active = True
    machine.set_byte(symbols["RTYPE_CLEANUP_ACTIVE"], 1)
    run(machine, symbols, world, 3)
    check(machine, symbols, world, None, "cleanup-forced-send")

    print("$F366: per-player first/repeat flags и две ROM sound tables exact")
    print("$F3C1: `$0180/$0100` countdown и cleanup-forced send exact")
    print("TSFM/arcade-SFX routing остаётся отдельной real-hardware границей")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
