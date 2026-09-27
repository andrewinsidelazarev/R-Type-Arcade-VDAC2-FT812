#!/usr/bin/env python3
"""Run the standalone port through ordinary inputs and report ROM coverage."""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from rtype_port.autopilot import Stage1Autopilot
from rtype_port.game import Game


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vblank", type=int, default=2500)
    parser.add_argument("--out", type=Path,
                        help="optional 640x480 final-frame PNG")
    args = parser.parse_args()
    pygame.init()
    pygame.display.set_mode((1, 1))
    try:
        game = Game()
        pilot = Stage1Autopilot()
        hits = 0
        collision_kinds: collections.Counter[str] = collections.Counter()
        collision_frames: dict[str, list[int]] = collections.defaultdict(list)
        while game.stage.m72_scroll.vblank < args.vblank:
            game.update(pilot.next(game))
            hits += int(game.player_hit)
            if game.player_hit:
                player_rect = game.player_collision_rect()
                native_left = round((game.player_x // 256) * 3 / 5)
                native_top = round((game.player_y // 256) * 8 / 15)
                fg, bg = game.stage.collision_codes(
                    native_left + 0x0150, 0x0176 - native_top)
                kinds = set()
                if fg < 0x0DFC or bg < 0x07D0:
                    kinds.add("terrain")
                kinds.update(
                    enemy.kind for enemy in game.enemy_world.enemies
                    if enemy.palette != 0xFF and
                    player_rect.colliderect(enemy.hitbox(
                        game.enemy_world.rom))
                )
                for kind in kinds or {"unclassified"}:
                    collision_kinds[kind] += 1
                    collision_frames[kind].append(
                        game.stage.m72_scroll.vblank)
        unsupported = collections.Counter(
            f"${event.handler:04X}" for event in game.enemy_world.unsupported_events)
        active = collections.Counter(enemy.kind
                                     for enemy in game.enemy_world.enemies)
        print(f"vblank={game.stage.m72_scroll.vblank}")
        print(f"progression=${game.stage.m72_scroll.progression:04X}")
        print(f"event_pointer=${game.enemy_world.event_pointer:04X}")
        print(f"active={dict(active)}")
        print(f"unsupported={dict(unsupported)}")
        print(f"player_collision_frames={hits}")
        print(f"collision_kinds={dict(collision_kinds)}")
        print("collision_frames=" + repr(dict(collision_frames)))
        print(f"projectile_spawn_requests={game.enemy_world.projectile_spawns}")
        print(f"score={game.enemy_world.score:07d}")
        print("score_awards=" + repr([
            f"${pointer:04X}" for pointer in game.enemy_world.score_awards]))
        print(f"boss_defeated={game.enemy_world.boss_defeated}")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            surface = pygame.Surface((640, 480), pygame.SRCALPHA)
            game.render(surface)
            pygame.image.save(surface, str(args.out))
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
