#!/usr/bin/env python3
"""Verify the Python Stage-1 object-pool lifecycle against a MAME trace.

This deliberately compares allocator-visible ROM behaviour, not screenshots:
every dynamic `$03A6` allocation and `$03EC` release from VBlank 852 onward
must occur on the same VBlank and use the same FIFO slot.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
PYTHON_SOURCE = ROOT / "Source" / "Python"
if str(PYTHON_SOURCE) not in sys.path:
    sys.path.insert(0, str(PYTHON_SOURCE))

from compare_mame_pool_events import (
    ALLOC_PC,
    POOL_FIRST,
    POOL_LAST,
    POOL_STRIDE,
    RELEASE_PC,
    matching_lines,
)
from rtype_port.enemies import M72EnemyWorld
from rtype_port.game import (
    Game,
    InputState,
    StageExitAutopilot,
    shot_collision_rect,
)
import rtype_port.stage as stage_module
from rtype_port.stage import M72Scroll, M72Tilemaps, Stage


FIRST_VBLANK = 852


@dataclass(frozen=True)
class LifecycleEvent:
    frame: int
    action: str
    slot: int
    source_frame: int | None = field(default=None, compare=False)
    detail: str = field(default="", compare=False)

    def display(self) -> str:
        source = ("" if self.source_frame in (None, self.frame) else
                  f" (MAME display={self.source_frame})")
        return (
            f"frame={self.frame:5d}{source} {self.action:5s} "
            f"slot=${self.slot:04X}"
            f"{(' ' + self.detail) if self.detail else ''}"
        )


class LightweightStage:
    """Collision/tile mutation surface of :class:`Stage` without atlases."""

    def __init__(self) -> None:
        self.m72_scroll = M72Scroll(stage1_no_fire_reference=True)
        self.tilemaps = M72Tilemaps()

    terrain_code = Stage.terrain_code
    terrain_address = Stage.terrain_address
    background_address = Stage.background_address
    erase_foreground = Stage.erase_foreground
    replace_foreground = Stage.replace_foreground
    foreground_cell = Stage.foreground_cell
    background_cell = Stage.background_cell
    collision_snapshot = Stage.collision_snapshot
    collision_codes = Stage.collision_codes

    def update(self) -> None:
        self.m72_scroll.advance()
        self.tilemaps.advance(self.m72_scroll)


def expected_events(path: Path, last_frame: int) -> list[LifecycleEvent]:
    """Read pool events and attach them to their enclosing ROM main pass."""
    result = []
    current_main_frame = FIRST_VBLANK - 1
    pattern = r"(,42ED0,[0-9A-F]{4},FFFF,00493|,(003C4|003FD))\r?$"
    for line in matching_lines(path, pattern):
        fields = line.rstrip("\r\n").split(",")
        if len(fields) != 5:
            continue
        source_frame = int(fields[0])
        if source_frame > last_frame:
            break
        address = int(fields[1], 16)
        pc = int(fields[4], 16)
        if address == 0x42ED0 and pc == 0x00493:
            current_main_frame = source_frame
            continue
        if source_frame < FIRST_VBLANK or pc not in (ALLOC_PC, RELEASE_PC):
            continue
        if not POOL_FIRST <= address <= POOL_LAST:
            continue
        if (address - POOL_FIRST) % POOL_STRIDE:
            continue
        result.append(LifecycleEvent(
            current_main_frame,
            "alloc" if pc == ALLOC_PC else "free",
            address & 0xFFFF,
            source_frame,
        ))
    return result


def active_main_frames(path: Path, last_frame: int) -> frozenset[int]:
    """Frames where IRQ `$0219` reached integrator `$0467/$0493`.

    A no-fire, invincible reference can saturate the 96-slot object pool and
    make the original V30 miss whole display frames.  Those CPU-load stalls
    are properties of this capture, not fixed Stage-1 timeline events, so the
    verifier derives them from the trace instead of hard-coding them into the
    FT812 port.
    """
    result = set()
    pattern = r",42ED0,[0-9A-F]{4},FFFF,00493\r?$"
    for line in matching_lines(path, pattern):
        fields = line.rstrip("\r\n").split(",")
        if len(fields) != 5 or fields[1] != "42ED0" or fields[4] != "00493":
            continue
        frame = int(fields[0])
        if FIRST_VBLANK <= frame <= last_frame:
            result.add(frame)
    return frozenset(result)


def replay(last_frame: int, active_frames: frozenset[int] | None = None,
           *, watch_slot: int | None = None, watch_from: int = 0,
           watch_to: int | None = None
           ) -> tuple[list[LifecycleEvent], M72EnemyWorld]:
    if active_frames is None:
        active_frames = frozenset(range(FIRST_VBLANK, last_frame + 1))
    missing_frames = frozenset(
        frame for frame in range(FIRST_VBLANK, last_frame + 1)
        if frame not in active_frames)
    original_integrator_missing = stage_module.M72_INTEGRATOR_MISSING
    original_scroll_stalls = stage_module.M72_SCROLL_STALLS
    stage_module.M72_INTEGRATOR_MISSING = missing_frames
    stage_module.M72_SCROLL_STALLS = frozenset(
        frame + 1 for frame in missing_frames)
    try:
        stage = LightweightStage()
        world = M72EnemyWorld()
        actual: list[LifecycleEvent] = []
        current_frame = FIRST_VBLANK - 1
        pool = world.object_pool
        original_take = pool.take
        original_bind = pool.bind
        original_release = pool.release

        def traced_take() -> int | None:
            slot = original_take()
            if slot is not None:
                cursor = world._scheduler_cursor_priority
                detail = ("dispatcher" if cursor is None else
                          f"cursor=${cursor:04X}")
                actual.append(LifecycleEvent(
                    current_frame, "alloc", slot, detail=detail))
            return slot

        def traced_bind(enemy: object, slot: int) -> None:
            original_bind(enemy, slot)
            if (actual and actual[-1].frame == current_frame and
                    actual[-1].action == "alloc" and
                    actual[-1].slot == slot):
                detail = actual[-1].detail
                kind = getattr(enemy, "kind", type(enemy).__name__)
                priority = getattr(enemy, "scheduler_priority", None)
                detail += f" owner={kind}"
                if isinstance(priority, int):
                    detail += f" priority=${priority & 0xFFFF:04X}"
                actual[-1] = LifecycleEvent(
                    actual[-1].frame, actual[-1].action,
                    actual[-1].slot, actual[-1].source_frame, detail)

        def traced_release(slot: int | None,
                           owner: object | None = None) -> None:
            was_allocated = slot is not None and slot in pool.allocated
            original_release(slot, owner)
            if was_allocated:
                detail = ""
                if owner is not None:
                    kind = getattr(owner, "kind", type(owner).__name__)
                    state = getattr(owner, "state", None)
                    x = getattr(owner, "x", None)
                    y = getattr(owner, "y", None)
                    detail = f"owner={kind}"
                    if state is not None:
                        detail += f" state={state}"
                    if isinstance(x, int) and isinstance(y, int):
                        detail += f" xy=${x & 0xFFFF:04X},${y & 0xFFFF:04X}"
                actual.append(LifecycleEvent(
                    current_frame, "free", int(slot), detail=detail))

        pool.take = traced_take  # type: ignore[method-assign]
        pool.bind = traced_bind  # type: ignore[method-assign]
        pool.release = traced_release  # type: ignore[method-assign]

        frame_counter = 0x0293
        exit_player = StageExitAutopilot(0x01CB00, 0x011000)
        for frame in range(FIRST_VBLANK, last_frame + 1):
            current_frame = frame
            stage.update()
            if frame not in active_frames:
                continue
            scroll = stage.m72_scroll
            if world.player_exit_latch:
                exit_player.latch = world.player_exit_latch
                exit_player.advance()
            world.update(
                scroll.dispatch_progression,
                scroll.dispatch_foreground_delta,
                frame_counter,
                stage.terrain_code,
                stage.collision_codes,
                player_native=exit_player.native,
                background_delta=scroll.dispatch_background_delta,
                terrain_address=stage.terrain_address,
                erase_terrain=stage.erase_foreground,
                replace_terrain=stage.replace_foreground,
                terrain_cell=stage.foreground_cell,
            )
            foreground_velocity, background_velocity = (
                world.take_scroll_velocity_commands())
            stage_init = world.take_stage_init_scroll_command()
            if stage_init is not None:
                scroll.queue_stage_init(*stage_init)
            if world.take_scroll_reset_command():
                scroll.queue_stage_transition_reset()
            scroll.queue_object_velocity_write(
                foreground_velocity, background_velocity)
            if (watch_slot is not None and frame >= watch_from and
                    (watch_to is None or frame <= watch_to)):
                owner = next((enemy for enemy in world.enemies
                              if enemy.object_slot == watch_slot), None)
                if owner is not None:
                    fields = [
                        f"watch frame={frame:5d} slot=${watch_slot:04X}",
                        f"owner={getattr(owner, 'kind', type(owner).__name__)}",
                        f"xy=${getattr(owner, 'x', 0) & 0xFFFF:04X},"
                        f"${getattr(owner, 'y', 0) & 0xFFFF:04X}",
                    ]
                    owner_x = getattr(owner, "x", None)
                    owner_y = getattr(owner, "y", None)
                    if isinstance(owner_x, int) and isinstance(owner_y, int):
                        fields.append(
                            f"terrain=${world.terrain_at(owner_x, owner_y):04X}")
                        fields.append(
                            f"vram=${world.terrain_address(owner_x, owner_y):04X}")
                    if hasattr(owner, "x_fraction") or hasattr(owner, "y_fraction"):
                        fields.append(
                            f"frac=${getattr(owner, 'x_fraction', 0) & 0xFF:02X},"
                            f"${getattr(owner, 'y_fraction', 0) & 0xFF:02X}")
                    if hasattr(owner, "x_velocity") or hasattr(owner, "y_velocity"):
                        fields.append(
                            f"vel=${getattr(owner, 'x_velocity', 0) & 0xFFFF:04X},"
                            f"${getattr(owner, 'y_velocity', 0) & 0xFFFF:04X}")
                    if hasattr(owner, "direction"):
                        fields.append(
                            f"dir=${getattr(owner, 'direction') & 0xFFFF:04X}")
                    if hasattr(owner, "move_timer"):
                        fields.append(
                            f"move=${getattr(owner, 'move_timer') & 0xFFFF:04X}")
                    if hasattr(owner, "life_timer"):
                        fields.append(
                            f"life=${getattr(owner, 'life_timer') & 0xFFFF:04X}")
                    if hasattr(owner, "homing"):
                        fields.append(f"homing={int(bool(owner.homing))}")
                    if hasattr(owner, "state"):
                        fields.append(f"state={getattr(owner, 'state')}")
                    if hasattr(owner, "burst_timer"):
                        fields.append(f"burst={getattr(owner, 'burst_timer')}")
                    if hasattr(owner, "fire_counter"):
                        fields.append(
                            f"fire=${getattr(owner, 'fire_counter') & 0xFFFF:04X}/"
                            f"${getattr(owner, 'fire_a', 0) & 0xFFFF:04X}/"
                            f"${getattr(owner, 'fire_b', 0) & 0xFFFF:04X}")
                    if hasattr(owner, "anchors_remaining"):
                        fields.append(
                            f"anchors={getattr(owner, 'anchors_remaining')}")
                    if hasattr(owner, "timeout"):
                        fields.append(
                            f"timeout=${getattr(owner, 'timeout') & 0xFFFF:04X}")
                    if hasattr(owner, "end_timer"):
                        fields.append(
                            f"end=${getattr(owner, 'end_timer') & 0xFFFF:04X}")
                    fields.append(
                        f"scrollvel=${scroll.foreground_velocity & 0xFFFF:04X},"
                        f"${scroll.background_velocity & 0xFFFF:04X}")
                    motion = getattr(owner, "motion", None)
                    if motion is not None:
                        fields.append(
                            f"motion=${getattr(motion, 'pointer', 0) & 0xFFFF:04X}"
                            f":${getattr(motion, 'phase', 0) & 0xFF:02X}")
                    print(" ".join(fields))
            frame_counter = (frame_counter + 1) & 0xFFFF
        return actual, world
    finally:
        stage_module.M72_INTEGRATOR_MISSING = original_integrator_missing
        stage_module.M72_SCROLL_STALLS = original_scroll_stalls


def replay_mame_default_inputs(
        last_frame: int,
        active_frames: frozenset[int], *, watch_slot: int | None = None,
        watch_from: int = 0, watch_to: int | None = None
        ) -> tuple[list[LifecycleEvent], M72EnemyWorld]:
    """Replay the deterministic inputs built into ``mame_reference.lua``.

    This path uses the complete :class:`Game` weapon pipeline.  It is kept
    separate from the lightweight no-fire oracle so player shots, Wave and
    enemy damage cannot silently contaminate that established reference.
    """
    missing_frames = frozenset(
        frame for frame in range(FIRST_VBLANK, last_frame + 1)
        if frame not in active_frames)
    original_integrator_missing = stage_module.M72_INTEGRATOR_MISSING
    original_scroll_stalls = stage_module.M72_SCROLL_STALLS
    stage_module.M72_INTEGRATOR_MISSING = missing_frames
    stage_module.M72_SCROLL_STALLS = frozenset(
        frame + 1 for frame in missing_frames)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    # pygame has already been imported by the port modules, but SDL is not
    # initialized until here; the dummy driver therefore remains effective.
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))
    try:
        game = Game()
        world = game.enemy_world
        actual: list[LifecycleEvent] = []
        current_frame = FIRST_VBLANK - 1
        pool = world.object_pool
        original_take = pool.take
        original_bind = pool.bind
        original_release = pool.release

        def traced_take() -> int | None:
            slot = original_take()
            if slot is not None:
                cursor = world._scheduler_cursor_priority
                detail = ("dispatcher" if cursor is None else
                          f"cursor=${cursor:04X}")
                actual.append(LifecycleEvent(
                    current_frame, "alloc", slot, detail=detail))
            return slot

        def traced_bind(enemy: object, slot: int) -> None:
            original_bind(enemy, slot)
            if (actual and actual[-1].frame == current_frame and
                    actual[-1].action == "alloc" and
                    actual[-1].slot == slot):
                detail = actual[-1].detail
                kind = getattr(enemy, "kind", type(enemy).__name__)
                priority = getattr(enemy, "scheduler_priority", None)
                detail += f" owner={kind}"
                if isinstance(priority, int):
                    detail += f" priority=${priority & 0xFFFF:04X}"
                actual[-1] = LifecycleEvent(
                    actual[-1].frame, actual[-1].action,
                    actual[-1].slot, actual[-1].source_frame, detail)

        def traced_release(slot: int | None,
                           owner: object | None = None) -> None:
            was_allocated = slot is not None and slot in pool.allocated
            original_release(slot, owner)
            if was_allocated:
                detail = ""
                if owner is not None:
                    kind = getattr(owner, "kind", type(owner).__name__)
                    state = getattr(owner, "state", None)
                    detail = f"owner={kind}"
                    if state is not None:
                        detail += f" state={state}"
                actual.append(LifecycleEvent(
                    current_frame, "free", int(slot), detail=detail))

        pool.take = traced_take  # type: ignore[method-assign]
        pool.bind = traced_bind  # type: ignore[method-assign]
        pool.release = traced_release  # type: ignore[method-assign]

        for frame in range(FIRST_VBLANK, last_frame + 1):
            current_frame = frame
            if frame not in active_frames:
                # The M72 V30 occasionally fails to reach the main handler
                # before the next display frame when the object FIFO is busy.
                # Video/VBlank state still advances, while `$2EB6`, player
                # weapons and the object scheduler do not.  This is the same
                # split used by the established no-fire oracle above.
                game.stage.update()
                continue
            # Literal default stage1 inputs at mame_reference.lua:158…168.
            # The fire edge on 1080 is consumed by fixed handler `$4ED8` on
            # 1081, allocating the one-pass `$4EAF` visual in the same FIFO.
            game.update(InputState(
                down=840 <= frame < 900,
                fire=frame >= 800 and (frame % 36) < 5,
            ))
            if (watch_slot is not None and frame >= watch_from and
                    (watch_to is None or frame <= watch_to)):
                owner = next((enemy for enemy in world.enemies
                              if enemy.object_slot == watch_slot), None)
                if owner is None:
                    print(f"watch frame={frame:5d} slot=${watch_slot:04X} free")
                else:
                    box = owner.hitbox(world.rom)
                    force_probes = []
                    for step in range(9):
                        probe_x = (game.force.x - 8 + step * 8) & 0xFFFF
                        address = game.stage.terrain_address(
                            probe_x, game.force.y)
                        cells = tuple(
                            game.stage.foreground_cell(
                                (address + offset) & 0x3FFF)[0] & 0x0FFF
                            for offset in (0, 0x100, -0x100)
                        )
                        force_probes.append(
                            f"${probe_x:04X}@${address:04X}:"
                            f"${cells[0]:03X}/${cells[1]:03X}/${cells[2]:03X}")
                    shots = ",".join(
                        f"${shot.x // 256:04X},${shot.y // 256:04X}:"
                        f"n=${(shot.native_x or 0) & 0xFFFF:04X},"
                        f"${(shot.native_y or 0) & 0xFFFF:04X}:"
                        f"{shot.state}:{shot_collision_rect(shot)}"
                        for shot in game.shots)
                    matrix = ",".join(
                        f"{slot}:${projectile.x:04X},${projectile.y:04X}"
                        for slot, projectile in game.force.projectiles.items())
                    print(
                        f"watch frame={frame:5d} slot=${watch_slot:04X} "
                        f"owner={owner.kind} alive={int(owner.alive)} "
                        f"xy=${owner.x & 0xFFFF:04X},${owner.y & 0xFFFF:04X} "
                        f"player=${world.player_native[0] & 0xFFFF:04X},"
                        f"${world.player_native[1] & 0xFFFF:04X} "
                        f"box={box} shots=[{shots}] "
                        f"force={game.force.state}:${game.force.x:04X},"
                        f"${game.force.y:04X} matrix=[{matrix}] "
                        f"fgx=${game.stage.m72_scroll.foreground_x:03X}/"
                        f"${game.stage.m72_scroll.dispatch_foreground_x:03X} "
                        f"force_cells=[{','.join(force_probes)}] "
                        f"state={getattr(owner, 'state', getattr(owner, 'ballistic_state', '-'))} "
                        f"hp=${getattr(owner, 'hp', 0) & 0xFFFF:04X} "
                        f"fire=${getattr(owner, 'fire_counter', 0) & 0xFFFF:04X}/"
                        f"${getattr(owner, 'fire_a', 0) & 0xFFFF:04X}/"
                        f"${getattr(owner, 'fire_b', 0) & 0xFFFF:04X} "
                        f"frac=${getattr(owner, 'x_fraction', 0) & 0xFF:02X},"
                        f"${getattr(owner, 'y_fraction', 0) & 0xFF:02X} "
                        f"ord=${getattr(owner, 'ordinal', 0) & 0xFFFF:04X} "
                        f"local=${getattr(owner, 'local_timer', 0) & 0xFFFF:04X} "
                        f"center={int(bool(getattr(getattr(owner, 'parent', None), 'center_destroyed', False)))} "
                        f"expl=${getattr(owner, 'explosion_pointer', 0) & 0xFFFF:04X}/"
                        f"${getattr(owner, 'explosion_timer', 0) & 0xFF:02X} "
                        f"seq=${getattr(owner, 'sequence_pointer', 0) & 0xFFFF:04X}/"
                        f"${getattr(owner, 'sequence_timer', 0) & 0xFF:02X} "
                        f"vel=${getattr(owner, 'x_velocity', 0) & 0xFFFF:04X},"
                        f"${getattr(owner, 'y_velocity', 0) & 0xFFFF:04X}")
        return actual, world
    finally:
        pygame.quit()
        stage_module.M72_INTEGRATOR_MISSING = original_integrator_missing
        stage_module.M72_SCROLL_STALLS = original_scroll_stalls


def verify(trace: Path, last_frame: int, *, watch_slot: int | None = None,
           watch_from: int = 0, watch_to: int | None = None,
           mame_default_inputs: bool = False) -> int:
    expected = expected_events(trace, last_frame)
    active_frames = active_main_frames(trace, last_frame)
    if mame_default_inputs:
        actual, world = replay_mame_default_inputs(
            last_frame, active_frames, watch_slot=watch_slot,
            watch_from=watch_from, watch_to=watch_to)
    else:
        actual, world = replay(
            last_frame, active_frames, watch_slot=watch_slot,
            watch_from=watch_from, watch_to=watch_to)
    common = min(len(expected), len(actual))
    mismatch = next(
        (index for index in range(common) if expected[index] != actual[index]),
        common,
    )
    if mismatch == len(expected) == len(actual):
        print(f"EXACT {len(actual)} events through VBlank {last_frame}")
        print(
            f"pool allocated/free={len(world.object_pool.allocated)}/"
            f"{len(world.object_pool.free)} event_pointer=${world.event_pointer:04X} "
            f"rng=${world.rng.a:02X},${world.rng.b:02X},${world.rng.c:02X}"
        )
        print(
            f"main-loop frames active/skipped={len(active_frames)}/"
            f"{last_frame - FIRST_VBLANK + 1 - len(active_frames)}"
        )
        return 0

    print(f"FIRST MISMATCH after {mismatch} exact events")
    print("MAME  : " + (
        expected[mismatch].display() if mismatch < len(expected) else "EOF"))
    print("Python: " + (
        actual[mismatch].display() if mismatch < len(actual) else "EOF"))
    for label, stream in (("MAME", expected), ("Python", actual)):
        print(label + " context:")
        for event in stream[max(0, mismatch - 3):mismatch + 4]:
            print("  " + event.display())
    print(
        f"replay end: pool allocated/free={len(world.object_pool.allocated)}/"
        f"{len(world.object_pool.free)} event_pointer=${world.event_pointer:04X} "
        f"rng=${world.rng.a:02X},${world.rng.b:02X},${world.rng.c:02X}"
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--last-frame", type=int, required=True)
    parser.add_argument("--watch-slot", type=lambda value: int(value, 0))
    parser.add_argument("--watch-from", type=int, default=0)
    parser.add_argument("--watch-to", type=int)
    parser.add_argument(
        "--mame-default-inputs", action="store_true",
        help="replay mame_reference.lua periodic fire through full Game logic")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.last_frame < FIRST_VBLANK:
        raise SystemExit(f"--last-frame must be >= {FIRST_VBLANK}")
    return verify(
        args.trace, args.last_frame, watch_slot=args.watch_slot,
        watch_from=args.watch_from, watch_to=args.watch_to,
        mame_default_inputs=args.mame_default_inputs)


if __name__ == "__main__":
    raise SystemExit(main())
