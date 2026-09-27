"""Кадр программы для трансляции p2c: титул до старта, затем самостоятельная игра rtype_port.

Порядок действий кадра — как в цикле main самостоятельной версии (`title.update`,
`title.render`, старт по FIRE после готовности титула с `start_music`, затем
`game.update`/`game.render`). Опрос событий pygame и темп кадров — адаптер ПК.
"""
from __future__ import annotations

import pygame

from rtype_port.audio import TargetAudio
from rtype_port.game import Game, InputState
from rtype_port.title import TitleScreen


class App:
    """Один кадр цикла main: титул до старта, затем игра."""

    def __init__(self, title: TitleScreen, game: Game, sound: TargetAudio) -> None:
        self.title = title
        self.game: Game | None = None
        self.prepared_game: Game | None = game
        self.sound = sound

    def frame(self, start_pressed: bool, inputs: InputState,
              target: pygame.Surface) -> None:
        if self.game is None:
            self.title.update()
            self.title.render(target)
            if self.title.ready and start_pressed:
                self.game = self.prepared_game
                self.prepared_game = None
                self.sound.start_music()
        else:
            self.game.update(inputs)
            self.game.render(target)
