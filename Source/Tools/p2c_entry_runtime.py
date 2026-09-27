"""Кадр программы для трансляции p2c: цикл main Python-версии `rtype_port.app` с полным
runtime World ROM (`rtype_port.full_runtime.FullRuntimeGame`).

Порядок действий кадра — как в теле цикла app.main: ветвь `game is None` (title.update,
title.render, создание FullRuntimeGame, request_start, advance_title / advance_start),
пробуждение штатной демо-игры (`is_attract_demo` и любая клавиша), возврат к титулу
(`return_to_custom_title`), иначе `update` и `render`. Управление машиной — как в
FullRuntimeGame. Отличия только в границах платформы:
  * машина M72 (RTypeM72Machine: баланс, загрузка, кадр ROM, память, вывод кадра) — объект
    платформы MachinePort (класс задаёт среда: на ПК — модель сверки, на Z80 — внешние функции):
    boot() — новая машина с балансом и загрузкой, step(mask, start1, coin1, render) —
    _step_machine (render — подготовить вывод кадра), word(address) — слово рабочего ОЗУ, show() —
    FullRuntimeGame.render, reset_session() — sound.reset_session и held_input.clear_actions;
  * мышь — источник координат R-9 (вход платформы, у M72 мыши нет; как в первых версиях порта):
    mouse() перед шагом кадра игры переносит смещение мыши кадра в позицию корабля; в штатной
    демо-игре не вызывается;
  * первый шаг конструктора FullRuntimeGame (render=True) не выводится ни на ПК, ни на VDAC2
    (кадр не показан), поэтому передаётся без вывода;
  * события pygame и удерживаемые кнопки (RuntimeInput, _keydown_actions) — адаптер ввода:
    FrameEvents (нажатия за кадр) и GameButtons (кнопки с импульсами fire/force);
  * `launch_age is None` хранится как -1.
"""
from __future__ import annotations

from dataclasses import dataclass

from rtype_port.title import TitleAssets, TitleScreen

PLAYER_LAUNCH_HANDLERS = (0x1F3D, 0x2027)
ARCADE_PRESENTATION_ENTRY = 0x076C
# Демо аттракта: ROM ведёт её состоянием директора $0A8B. Замер аркады покадрово (MAME,
# 20 000 кадров, 2026-09-20): цикл $07DA 0.6 с → $085A 3.8 с → $094A 4.7 с → $0A8B демо 33…36 с
# → $0AE7 0.6 с → $0B9E 4.1 с, этапы демо по кругу 4 → 2 → 3. Состояний $076C и $124F в этом
# цикле нет вовсе, поэтому конец демо по ним не ловился и демо шла без конца.
ATTRACT_DEMO_HANDLER = 0x0A8B
GAME_OVER_DELAY_HANDLER = 0x124F
COIN_PULSE_FRAMES = (0, 1)
START_PULSE_FRAMES = (30, 31)
PLAYER_HANDLER_ADDRESS = 0x40020
DIRECTOR_HANDLER_ADDRESS = 0x40000
DIRECTOR_TIMER_ADDRESS = 0x4001E


@dataclass
class FrameEvents:
    """События кадра app.main: title_start, system_start, coin, demo_wake."""

    title_start: bool = False
    system_start: bool = False
    coin: bool = False
    demo_wake: bool = False


@dataclass
class GameButtons:
    """Кнопки `_input_mask`: клавиши движения, `held.fire or fire_pulse`, `held.force or force_pulse`."""

    right: bool = False
    left: bool = False
    down: bool = False
    up: bool = False
    fire: bool = False
    force: bool = False


def input_mask(buttons: GameButtons) -> int:
    """Байт ввода как app._input_mask."""
    return ((0x01 if buttons.right else 0) |
            (0x02 if buttons.left else 0) |
            (0x04 if buttons.down else 0) |
            (0x08 if buttons.up else 0) |
            (0x10 if buttons.fire else 0) |
            (0x20 if buttons.force else 0))


class RuntimeGame:
    """Управление машиной FullRuntimeGame."""

    def __init__(self, port) -> None:
        self.port = port
        port.boot()
        self.launch_age = -1
        self.ready = False
        port.step(0, False, False, False)

    def return_to_custom_title(self) -> bool:
        if not self.ready:
            return False
        handler = self.port.word(DIRECTOR_HANDLER_ADDRESS)
        return ((handler == GAME_OVER_DELAY_HANDLER and
                 self.port.word(DIRECTOR_TIMER_ADDRESS) <= 1) or
                handler == ARCADE_PRESENTATION_ENTRY)

    def is_attract_demo(self) -> bool:
        return self.ready and self.launch_age < 0

    def attract_demo_finished(self) -> bool:
        """Демо аттракта закончилась: ROM вышел из состояния $0A8B в презентацию цикла."""
        return (self.ready and self.launch_age < 0 and
                self.port.word(DIRECTOR_HANDLER_ADDRESS) != ATTRACT_DEMO_HANDLER)

    def advance_title(self) -> bool:
        if self.launch_age >= 0 or self.ready:
            return self.ready
        self.port.step(0, False, False, False)
        if self.port.word(PLAYER_HANDLER_ADDRESS) in PLAYER_LAUNCH_HANDLERS:
            self.ready = True
        return self.ready

    def request_start(self) -> None:
        if self.launch_age < 0 and not self.ready:
            self.launch_age = 0

    def advance_start(self) -> bool:
        if self.ready:
            return True
        if self.launch_age < 0:
            return False
        age = self.launch_age
        self.port.step(0, age in START_PULSE_FRAMES, age in COIN_PULSE_FRAMES, False)
        self.launch_age += 1
        if self.port.word(PLAYER_HANDLER_ADDRESS) in PLAYER_LAUNCH_HANDLERS:
            self.ready = True
        return self.ready

    def update(self, mask: int, start1: bool, coin1: bool) -> None:
        # Мышь — координаты R-9 до шага кадра; демо-игру ROM ведёт сам.
        if not self.is_attract_demo():
            self.port.mouse()
        self.port.step(mask, start1, coin1, True)


class RuntimeApp:
    """Тело цикла app.main."""

    def __init__(self, assets: TitleAssets, port) -> None:
        self.assets = assets
        self.port = port
        self.title = TitleScreen(assets)
        self.game: RuntimeGame | None = None
        self.prepared_game: RuntimeGame | None = RuntimeGame(port)

    def frame(self, events: FrameEvents, buttons: GameButtons, target) -> None:
        if self.game is None:
            self.title.update()
            self.title.render(target)
            if self.prepared_game is None:
                self.prepared_game = RuntimeGame(self.port)
            prepared = self.prepared_game
            if self.title.ready and events.title_start and prepared.launch_age < 0:
                prepared.request_start()
                self.title.starting = True
            if prepared.launch_age < 0:
                if prepared.advance_title():
                    self.game = prepared
            elif prepared.advance_start():
                self.game = prepared
        elif self.game.is_attract_demo() and (events.demo_wake or events.title_start):
            # Демо прервана кнопкой — уходим на свой титул, и машина перезапускается: новую готовит
            # ветка титула (prepared_game = None). Без перезапуска ROM продолжает ту же демо, обработчик
            # игрока в ней уже «в полёте», и титул сразу отдаёт экран обратно — со стороны выглядит,
            # будто огонь не работает (2026-09-20). Так это и работало до правки конца демо.
            self.port.reset_session()
            self.title = TitleScreen(self.assets)
            self.game = None
            self.prepared_game = None
            self.title.render(target)
        elif self.game.attract_demo_finished():
            # Демо кончилась сама, как в аркаде: ROM ушёл из $0A8B в презентацию цикла. Машину не
            # перезапускаем — иначе ROM начнёт аттракт сначала и покажет ту же первую демо; сброшенный
            # ready возвращает ожидание следующей демо того же цикла.
            self.port.reset_session()
            self.title = TitleScreen(self.assets)
            self.game.ready = False
            self.prepared_game = self.game
            self.game = None
            self.title.render(target)
        elif self.game.return_to_custom_title():
            # После своей игры машина перезапускается (новая сессия), после демо — продолжает цикл
            # аттракта ROM: в аркаде демо идут разные (замер 2026-09-20 по MAME без монеты: титул,
            # демо второго этапа, заставка, демо других этапов, снова титул с CREDIT 00).
            played = self.game.launch_age >= 0
            self.port.reset_session()
            self.title = TitleScreen(self.assets)
            if played:
                self.prepared_game = None
            else:
                self.game.ready = False
                self.prepared_game = self.game
            self.game = None
            self.title.render(target)
        else:
            self.game.update(input_mask(buttons), events.system_start, events.coin)
            self.port.show()
