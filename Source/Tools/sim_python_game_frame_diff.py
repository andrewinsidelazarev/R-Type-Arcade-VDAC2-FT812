#!/usr/bin/env python3
"""Find the first per-frame state divergence between active Python and Z80."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

import pygame  # noqa: E402

from rtype_port.game import Game, InputState  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


POOL = 0x09 * 0x4000
RECORD_SIZE = 0x40
OBJECT_COUNT = 96


def word(data: bytearray, offset: int) -> int:
    return data[offset] | data[offset + 1] << 8


def pool_index(slot: int) -> int:
    return (slot - 0x0540) // RECORD_SIZE


def python_slots(game: Game) -> dict[int, object]:
    result: dict[int, object] = {}
    owners = tuple(game.enemy_world.resource_owners) + tuple(
        game.enemy_world.enemies)
    for owner in owners:
        slot = getattr(owner, "object_slot", None)
        if slot is not None:
            result[pool_index(slot)] = owner
    return result


def z80_slots(memory: bytearray) -> set[int]:
    return {
        index for index in range(2, OBJECT_COUNT)
        if memory[POOL + index * RECORD_SIZE] != 0
    }


def describe(owner: object) -> str:
    fields = [getattr(owner, "kind", type(owner).__name__)]
    if hasattr(owner, "x") and hasattr(owner, "y"):
        fields.append(
            f"xy=#{getattr(owner, 'x') & 0xFFFF:04X},"
            f"#{getattr(owner, 'y') & 0xFFFF:04X}")
    if hasattr(owner, "state"):
        fields.append(f"state={getattr(owner, 'state')}")
    return " ".join(fields)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=2400)
    parser.add_argument("--trace-events", action="store_true")
    args = parser.parse_args()

    pygame.init()
    pygame.display.set_mode((1, 1))
    try:
        symbols = parse_sym(ROOT / "Build" / "rtype.sym")
        machine = TSConfFT812Machine(
            ROOT,
            spgbld_path=ROOT / "spgbld_rtype.ini",
            sym_path=ROOT / "Build" / "rtype.sym",
            load_spg=True,
        )
        machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
        machine.call(symbols["Application_StartGame"], max_steps=80_000_000)
        game = Game()
        inputs = InputState()

        if args.trace_events:
            print(
                "before updates: "
                f"index={machine.get_word(symbols['RTypeTargetEventIndex'])} "
                f"page=#{machine.get_byte(symbols['RTypeTargetEventPage']):02X} "
                f"ptr=#{machine.get_word(symbols['RTypeTargetEventPtr']):04X}")

        for frame in range(args.frames):
            machine.call(symbols["Application_Update"], max_steps=20_000_000)
            game.update(inputs)

            if args.trace_events and (frame < 3 or frame >= 253):
                print(
                    f"event frame={frame}: "
                    f"index={machine.get_word(symbols['RTypeTargetEventIndex'])} "
                    f"ptr=#{machine.get_word(symbols['RTypeTargetEventPtr']):04X} "
                    f"handler=#{machine.get_word(symbols['RTypeWorldLastHandler']):04X} "
                    f"python=#{game.enemy_world.event_pointer:04X}")

            z80_counter = machine.get_word(symbols["FrameCounter"])
            if z80_counter != game.m72_frame_counter:
                raise AssertionError(
                    f"frame {frame}: counter Z80=#{z80_counter:04X} "
                    f"Python=#{game.m72_frame_counter:04X}")

            expected = python_slots(game)
            actual = z80_slots(machine.mem.physical)
            if actual != set(expected):
                missing = sorted(set(expected) - actual)
                extra = sorted(actual - set(expected))
                print(
                    f"FIRST DIVERGENCE frame={frame} "
                    f"counter=#{z80_counter:04X} "
                    f"progress Z80=#{machine.get_word(symbols['RTypeWorldProgressQ8'] + 1):04X} "
                    f"Python=#{game.stage.m72_scroll.progression:04X} "
                    f"dispatch=#{game.stage.m72_scroll.dispatch_progression:04X} "
                    f"velocity Z80=#{machine.get_word(symbols['RTypeWorldFgVelocity']):04X} "
                    f"Python=#{game.stage.m72_scroll.foreground_velocity:04X} "
                    f"event-index={machine.get_word(symbols['RTypeTargetEventIndex'])} "
                    f"event-page=#{machine.get_byte(symbols['RTypeTargetEventPage']):02X} "
                    f"event-ptr=#{machine.get_word(symbols['RTypeTargetEventPtr']):04X} "
                    f"last-command=#{machine.get_word(symbols['RTypeWorldLastCommand']):04X} "
                    f"last-handler=#{machine.get_word(symbols['RTypeWorldLastHandler']):04X} "
                    f"Python-event=#{game.enemy_world.event_pointer:04X}")
                for index in missing:
                    print(f"missing slot={index}: {describe(expected[index])}")
                for index in extra:
                    base = POOL + index * RECORD_SIZE
                    print(
                        f"extra slot={index}: type={machine.mem.physical[base]} "
                        f"xy=#{word(machine.mem.physical, base + 2):04X},"
                        f"#{word(machine.mem.physical, base + 4):04X}")
                return 1

            for index, owner in expected.items():
                if not (hasattr(owner, "x") and hasattr(owner, "y")):
                    continue
                base = POOL + index * RECORD_SIZE
                if getattr(owner, "kind", "") == "background_particle_e5cd":
                    expected_particle = (
                        getattr(owner, "x_fraction") & 0xFF,
                        getattr(owner, "y_fraction") & 0xFF,
                        getattr(owner, "x_velocity") & 0xFFFF,
                        int(getattr(owner, "initialized")),
                        int(getattr(owner, "render_ready")),
                    )
                    actual_particle = (
                        machine.mem.physical[base + 0x10],
                        machine.mem.physical[base + 0x11],
                        word(machine.mem.physical, base + 0x12),
                        machine.mem.physical[base + 0x0E],
                        machine.mem.physical[base + 0x0F],
                    )
                    if actual_particle != expected_particle:
                        print(
                            f"FIRST DIVERGENCE frame={frame} slot={index} "
                            f"counter=#{z80_counter:04X} particle-state "
                            f"Python={expected_particle} Z80={actual_particle}")
                        return 1
                actual_xy = (
                    word(machine.mem.physical, base + 2),
                    word(machine.mem.physical, base + 4),
                )
                expected_xy = (
                    getattr(owner, "x") & 0xFFFF,
                    getattr(owner, "y") & 0xFFFF,
                )
                if actual_xy != expected_xy:
                    details = ""
                    if hasattr(owner, "x_fraction"):
                        z80_fraction = machine.mem.physical[base + 0x10]
                        z80_velocity = word(machine.mem.physical, base + 0x12)
                        scheduler_next_base = POOL + (
                            symbols["RTYPE_SCHED_NEXT"] - 0xC000)
                        scheduler_prev_base = POOL + (
                            symbols["RTYPE_SCHED_PREV"] - 0xC000)
                        scheduler_head = machine.mem.physical[
                            POOL + (symbols["RTYPE_SCHED_HEAD"] - 0xC000)]
                        details = (
                            f" fraction=#{getattr(owner, 'x_fraction') & 0xFF:02X}"
                            f"/Z80#{z80_fraction:02X}"
                            f" velocity=#{getattr(owner, 'x_velocity') & 0xFFFF:04X}"
                            f"/Z80#{z80_velocity:04X}"
                            f" state={machine.mem.physical[base + 0x0E]}"
                            f" ready={machine.mem.physical[base + 0x0F]}"
                            f" sched=head{scheduler_head}"
                            f",prev{machine.mem.physical[scheduler_prev_base + index]}"
                            f",next{machine.mem.physical[scheduler_next_base + index]}")
                    print(
                        f"FIRST DIVERGENCE frame={frame} slot={index} "
                        f"counter=#{z80_counter:04X} {describe(owner)} "
                        f"Z80xy=#{actual_xy[0]:04X},#{actual_xy[1]:04X}"
                        f"{details}")
                    return 1

            if frame and frame % 100 == 0:
                print(f"exact through frame {frame}", flush=True)
        print(f"Python/Z80 object lifecycle exact: {args.frames} frames")
        return 0
    finally:
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
