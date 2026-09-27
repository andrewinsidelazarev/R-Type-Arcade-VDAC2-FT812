"""Воспроизводимый ввод для трассы и сверки: простой, coin/start, затем случайные нажатия."""
from __future__ import annotations

import random


class Scenario:
    def __init__(self, seed: int, coin_frame: int) -> None:
        self.rng = random.Random(seed)
        self.coin_frame = coin_frame
        self.mask = 0

    def inputs(self, frame: int) -> tuple[int, bool, bool]:
        """(маска игрока, start1, coin1) кадра; маска как у full_runtime._step_machine."""
        coin = frame in (self.coin_frame, self.coin_frame + 1)
        start = frame in (self.coin_frame + 30, self.coin_frame + 31)
        if frame > self.coin_frame + 60 and self.rng.random() < 0.05:
            self.mask = self.rng.choice((0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x11, 0x12, 0x14, 0x18, 0x30))
        return self.mask, start, coin

    @staticmethod
    def apply(machine, mask: int, start: bool, coin: bool) -> None:
        machine.inputs.set_player(right=bool(mask & 1), left=bool(mask & 2), down=bool(mask & 4),
                                  up=bool(mask & 8), button1=bool(mask & 0x10), button2=bool(mask & 0x20))
        machine.inputs.set_system(start1=start, coin1=coin)
