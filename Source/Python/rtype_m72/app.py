"""Интерактивный запуск оригинального игрового процесса R-Type в Python."""
from __future__ import annotations

import argparse
import time

import pygame

from .hq_renderer import HEIGHT, WIDTH, M72HqRenderer
from .machine import FRAME_RATE, RTypeM72Machine
from .sound import M72SoundSystem


class SoundRouter:
    """Feeds every V30 latch byte to the original Z80/YM2151 runtime."""

    def __init__(self, enabled: bool) -> None:
        self.system = M72SoundSystem(output=enabled)

    def command(self, value: int) -> None:
        self.system.command(value)

    def step_frame(self) -> None:
        self.system.step_frame()

    def close(self) -> None:
        self.system.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mute", action="store_true")
    args = parser.parse_args()

    sound = SoundRouter(not args.mute)
    machine = RTypeM72Machine(sound.command)
    machine.boot()

    renderer = M72HqRenderer()

    pygame.init()
    pygame.display.set_caption("R-Type M72 — Python HQ 640×480")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), flags=pygame.DOUBLEBUF)
    pulse_coin = 0
    pulse_start = 0
    deadline = time.perf_counter()
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_5:
                        pulse_coin = 2
                    elif event.key == pygame.K_1:
                        pulse_start = 2
            if not running:
                break

            keys = pygame.key.get_pressed()
            machine.inputs.set_player(
                right=keys[pygame.K_RIGHT], left=keys[pygame.K_LEFT],
                down=keys[pygame.K_DOWN], up=keys[pygame.K_UP],
                button1=(keys[pygame.K_SPACE] or keys[pygame.K_z] or
                         keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]),
                button2=(keys[pygame.K_x] or keys[pygame.K_LALT] or
                         keys[pygame.K_RALT]))
            machine.inputs.set_system(start1=pulse_start > 0, coin1=pulse_coin > 0)
            pulse_start = max(0, pulse_start - 1)
            pulse_coin = max(0, pulse_coin - 1)

            renderer.render(machine.step_frame())
            sound.step_frame()
            surface = pygame.image.frombuffer(renderer.rgba.data, (WIDTH, HEIGHT), "RGBA")
            screen.blit(surface, (0, 0))
            pygame.display.flip()

            deadline += 1.0 / FRAME_RATE
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            elif remaining < -0.25:
                deadline = time.perf_counter()
    finally:
        sound.close()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
