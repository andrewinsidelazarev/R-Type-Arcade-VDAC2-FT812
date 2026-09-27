#!/usr/bin/env python3
"""Долгий машинный замер GAME: кадр, объекты и промахи sprite-cache."""

from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


OBJECT_PAGE = 0x09
OBJECT_WINDOW = OBJECT_PAGE * 0x4000
OBJECT_RECORD_SIZE = 64
OBJECT_COUNT = 96
OBJECT_TYPE = 0


def _physical_slot3(address: int) -> int:
    """Перевести адрес slot3 страницы #09 в физический адрес TS-Conf."""
    return OBJECT_WINDOW + address - 0xC000


def _active_objects(machine: TSConfFT812Machine) -> int:
    base = OBJECT_WINDOW
    return sum(
        machine.mem.physical[base + index * OBJECT_RECORD_SIZE + OBJECT_TYPE] != 0
        for index in range(2, OBJECT_COUNT)
    )


def _active_type_counts(machine: TSConfFT812Machine) -> Counter[int]:
    """Состав живого пула нужен, чтобы худший кадр был воспроизводим."""
    base = OBJECT_WINDOW
    return Counter(
        machine.mem.physical[base + index * OBJECT_RECORD_SIZE + OBJECT_TYPE]
        for index in range(2, OBJECT_COUNT)
        if machine.mem.physical[
            base + index * OBJECT_RECORD_SIZE + OBJECT_TYPE] != 0
    )


def _profile_call(
        machine: TSConfFT812Machine, address: int,
) -> tuple[int, Counter[int], Counter[tuple[int, int]]]:
    """Исполнить CALL и разложить t-states по физическим TS pages кода."""
    marker = 0xFFFE
    sp = (machine.reg.SP - 2) & 0xFFFF
    machine.set_word(sp, marker)
    machine.reg.SP = sp
    machine.reg.PC = address & 0xFFFF
    before_total = machine.tstates
    pages: Counter[int] = Counter()
    pcs: Counter[tuple[int, int]] = Counter()
    steps = 0
    while machine.reg.PC != marker:
        if steps >= 20_000_000:
            raise TimeoutError(f"profile timeout at PC=#{machine.reg.PC:04X}")
        pc = machine.reg.PC
        page = machine.mem.pages[pc >> 14]
        before = machine.tstates
        machine.step()
        ticks = machine.tstates - before
        pages[page] += ticks
        pcs[(page, pc)] += ticks
        steps += 1
    return machine.tstates - before_total, pages, pcs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=1800)
    parser.add_argument("--render-from", type=int, default=0)
    parser.add_argument("--profile-frame", type=int, default=-1)
    parser.add_argument("--profile-render-frame", type=int, default=-1)
    parser.add_argument("--trace-from", type=int, default=-1)
    parser.add_argument(
        "--sym", type=Path, default=ROOT / "Build" / "rtype.sym",
        help="таблица символов, соответствующая текущим бинарным страницам",
    )
    args = parser.parse_args()
    symbols = parse_sym(args.sym)
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=args.sym,
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.call(symbols["Application_StartGame"], max_steps=80_000_000)

    next_slot = symbols["RTypeSpriteCacheNextSlot"]
    worst_update = (0, 0, 0)
    worst_types: Counter[int] = Counter()
    worst_render = (0, 0, 0)
    worst_full = (0, 0, 0)
    worst_command_chunk = (0, 0, 0)
    flushed_frames: list[tuple[int, int]] = []
    render_miss_frames: list[tuple[int, int]] = []

    # Первые 1800 кадров Stage 1 захватывают плотные группы противников,
    # Force/выстрелы и несколько смен наборов графики, а не только пустой старт.
    for frame in range(args.frames):
        machine.call(symbols["RTypeSpriteCache_BeginFrame"],
                     max_steps=2_000_000)
        before = machine.tstates
        profile_pages: Counter[int] | None = None
        profile_pcs: Counter[tuple[int, int]] | None = None
        if frame == args.profile_frame:
            update_t, profile_pages, profile_pcs = _profile_call(
                machine, symbols["Application_Update"])
        else:
            machine.call(symbols["Application_Update"], max_steps=20_000_000)
            update_t = machine.tstates - before
        active = _active_objects(machine)
        if update_t > worst_update[0]:
            worst_update = (update_t, frame, active)
            worst_types = _active_type_counts(machine)
        if profile_pages is not None:
            print(
                "profile pages: " + ", ".join(
                    f"#{page:02X}={ticks}t"
                    for page, ticks in profile_pages.most_common()),
                flush=True)
            print(
                "profile hot PC: " + ", ".join(
                    f"#{page:02X}:#{pc:04X}={ticks}t"
                    for (page, pc), ticks in profile_pcs.most_common(24)),
                flush=True)
            profile_bands = Counter()
            for (page, pc), ticks in profile_pcs.items():
                profile_bands[(page, pc & 0xFF00)] += ticks
            print(
                "profile hot 256-byte bands: " + ", ".join(
                    f"#{page:02X}:#{base:04X}={ticks}t"
                    for (page, base), ticks in profile_bands.most_common(24)),
                flush=True)

        if frame >= args.render_from:
            slot_before = machine.get_word(next_slot)
            before = machine.tstates
            if frame == args.profile_render_frame:
                render_t, render_pages, render_pcs = _profile_call(
                    machine, symbols["Render_Frame"])
                print(
                    "render profile pages: " + ", ".join(
                        f"#{page:02X}={ticks}t"
                        for page, ticks in render_pages.most_common()),
                    flush=True)
                print(
                    "render hot PC: " + ", ".join(
                        f"#{page:02X}:#{pc:04X}={ticks}t"
                        for (page, pc), ticks in render_pcs.most_common(32)),
                    flush=True)
                render_bands = Counter()
                for (page, pc), ticks in render_pcs.items():
                    render_bands[(page, pc & 0xFF00)] += ticks
                print(
                    "render hot 256-byte bands: " + ", ".join(
                        f"#{page:02X}:#{base:04X}={ticks}t"
                        for (page, base), ticks in render_bands.most_common(24)),
                    flush=True)
            else:
                machine.call(symbols["Render_Frame"], max_steps=20_000_000)
                render_t = machine.tstates - before
            command_buffer = symbols["RTypeFTCommandBufferStart"]
            command_limit = symbols["RTypeFTCommandBufferEnd"]
            command_end = machine.get_word(symbols["FT.Coprocessor.BufferPtr"])
            if not command_buffer <= command_end <= command_limit:
                raise AssertionError(
                    f"frame {frame}: FT command pointer escaped staging window: "
                    f"#{command_end:04X}")
            command_chunk = command_end - command_buffer
            if command_chunk > worst_command_chunk[0]:
                worst_command_chunk = (command_chunk, frame, active)
            flushes = machine.get_byte(symbols["RTypePyCommandFlushCount"])
            if flushes:
                flushed_frames.append((frame, flushes))
            slot_after = machine.get_word(next_slot)
            if render_t > worst_render[0]:
                worst_render = (render_t, frame, active)
            full_t = update_t + render_t
            if full_t > worst_full[0]:
                worst_full = (full_t, frame, active)
            misses = slot_after - slot_before
            if args.trace_from >= 0 and frame >= args.trace_from:
                print(
                    f"frame {frame}: update={update_t}t render={render_t}t "
                    f"total={full_t}t objects={active} cache+={misses}",
                    flush=True)
            if misses:
                render_miss_frames.append((frame, misses))
        if frame and frame % 100 == 0:
            print(f"пройдено {frame}/{args.frames} кадров", flush=True)

    print(
        f"GAME {args.frames} кадров: "
        f"update max={worst_update[0]}t на {worst_update[1]} "
        f"({worst_update[2]} объектов), "
        f"render max={worst_render[0]}t на {worst_render[1]} "
        f"({worst_render[2]} объектов), "
        f"total max={worst_full[0]}t на {worst_full[1]} "
        f"({worst_full[2]} объектов)")
    print(
        f"FT812 staging max={worst_command_chunk[0]} bytes на "
        f"{worst_command_chunk[1]} ({worst_command_chunk[2]} объектов); "
        f"streamed frames={len(flushed_frames)}, первые={flushed_frames[:12]}")
    print(
        "Типы объектов худшего update: " +
        ", ".join(f"{kind}:{count}" for kind, count in sorted(worst_types.items())))
    print(
        "GAME state: "
        f"mode={machine.get_byte(symbols['GameMode'])} "
        f"target_valid={machine.get_byte(symbols['RTypeTargetValid'])} "
        f"stage={machine.get_byte(symbols['RTypeTargetStage'])} "
        f"events={machine.get_word(symbols['RTypeTargetEventIndex'])}/"
        f"{machine.get_word(symbols['RTypeTargetEventCount'])} "
        f"event_page=#{machine.get_byte(symbols['RTypeTargetEventPage']):02X} "
        f"event_ptr=#{machine.get_word(symbols['RTypeTargetEventPtr']):04X} "
        f"progress={machine.get_word(symbols['RTypeWorldProgressQ8'] + 1)} "
        f"fg_velocity=#{machine.get_word(symbols['RTypeWorldFgVelocity']):04X}")
    print(
        "R-9 state: "
        f"visible={machine.get_byte(symbols['ArcadePlayerVisible'])} "
        f"intro={machine.get_word(symbols['ArcadeIntroFrame'])} "
        f"x={machine.get_word(symbols['ArcadePlayerX'] + 1)} "
        f"y={machine.get_word(symbols['ArcadePlayerY'] + 1)} "
        f"pitch={machine.get_byte(symbols['ArcadePlayerPitch'])}")
    if render_miss_frames:
        print(
            f"Промахи sprite-cache внутри Render_Frame: "
            f"{len(render_miss_frames)} кадров; первые {render_miss_frames[:12]}")
        return 1
    print("Промахов sprite-cache внутри Render_Frame нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
