"""Запуск самостоятельного Python-переноса R-Type."""
from __future__ import annotations

import time

import pygame

from .audio import TargetAudio
from .full_runtime import FullRuntimeGame
from .hardware import Ft812Display, Z80TargetMachine
from .title import TitleAssets, TitleScreen


WIDTH, HEIGHT = 640, 480
FRAME_RATE = 55.0
FIRE_KEYS = frozenset((pygame.K_SPACE, pygame.K_z,
                       pygame.K_LCTRL, pygame.K_RCTRL))
FORCE_KEYS = frozenset((pygame.K_x, pygame.K_RALT))
SYSTEM_START_KEYS = frozenset((pygame.K_RETURN, pygame.K_1))


def _keydown_actions(key: int) -> tuple[bool, bool, bool, bool]:
    """Разделить title-start, системный START, FIRE и действие Force."""
    fire = key in FIRE_KEYS
    system_start = key in SYSTEM_START_KEYS
    return fire or system_start, system_start, fire, key in FORCE_KEYS


def _wakes_from_demo(event: pygame.event.Event) -> bool:
    """Любое экранное управление возвращает демо к главному экрану."""
    return (event.type == pygame.KEYDOWN or
            (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
            event.type == pygame.JOYBUTTONDOWN)


class RuntimeInput:
    """Удерживаемые игровые кнопки с обязательным сбросом потери фокуса."""

    def __init__(self) -> None:
        self.keys: set[int] = set()
        self.mouse_buttons: set[int] = set()
        self.focused = True

    def clear_actions(self) -> None:
        """Снять игровые кнопки при смене сессии или потере фокуса."""
        self.keys.clear()
        self.mouse_buttons.clear()

    def process(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in FIRE_KEYS or event.key in FORCE_KEYS:
                self.keys.add(event.key)
        elif event.type == pygame.KEYUP:
            self.keys.discard(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button in (1, 3):
                self.mouse_buttons.add(event.button)
        elif event.type == pygame.MOUSEBUTTONUP:
            self.mouse_buttons.discard(event.button)
        elif event.type == pygame.WINDOWFOCUSLOST:
            self.clear_actions()
            self.focused = False
        elif event.type == pygame.WINDOWFOCUSGAINED:
            self.focused = True

    @property
    def fire(self) -> bool:
        return bool(self.keys & FIRE_KEYS or 1 in self.mouse_buttons)

    @property
    def force(self) -> bool:
        return bool(self.keys & FORCE_KEYS or 3 in self.mouse_buttons)


def _input_mask(keys: pygame.key.ScancodeWrapper,
                held: RuntimeInput, *, fire_pulse: bool = False,
                force_pulse: bool = False) -> int:
    """Собрать байт ввода целевого Z80 из клавиатуры и мыши."""
    if not held.focused:
        return 0
    return ((0x01 if keys[pygame.K_RIGHT] else 0) |
            (0x02 if keys[pygame.K_LEFT] else 0) |
            (0x04 if keys[pygame.K_DOWN] else 0) |
            (0x08 if keys[pygame.K_UP] else 0) |
            (0x10 if held.fire or fire_pulse else 0) |
            (0x20 if held.force or force_pulse else 0))


def main() -> int:
    pygame.init()
    joysticks = {
        joystick.get_instance_id(): joystick
        for joystick in (pygame.joystick.Joystick(index)
                         for index in range(pygame.joystick.get_count()))
    }
    pygame.display.set_caption("R-Type — Python port 640×480")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), flags=pygame.DOUBLEBUF)
    display = Ft812Display()
    z80 = Z80TargetMachine()
    title_assets = TitleAssets()
    title = TitleScreen(title_assets)
    game: FullRuntimeGame | None = None
    sound = TargetAudio(port_writer=z80.out_port)
    # Первый title-кадр показывается до тяжёлой загрузки полного HQ-atlas.
    target = display.begin_frame()
    title.render(target)
    display.present(screen)
    pygame.display.flip()
    prepared_game: FullRuntimeGame | None = FullRuntimeGame(sound.command)
    reusable_renderer = None
    held_input = RuntimeInput()
    deadline = time.perf_counter()
    running = True
    try:
        while running:
            title_start_pressed = False
            system_start_pressed = False
            coin_pressed = False
            fire_pressed = False
            force_pressed = False
            demo_wake_pressed = False
            for event in pygame.event.get():
                demo_wake_pressed |= _wakes_from_demo(event)
                held_input.process(event)
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.JOYDEVICEADDED:
                    joystick = pygame.joystick.Joystick(event.device_index)
                    joysticks[joystick.get_instance_id()] = joystick
                elif event.type == pygame.JOYDEVICEREMOVED:
                    joysticks.pop(event.instance_id, None)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        title_start, system_start, fire, force = (
                            _keydown_actions(event.key))
                        title_start_pressed |= title_start
                        system_start_pressed |= system_start
                        fire_pressed |= fire
                        force_pressed |= force
                        if event.key == pygame.K_5:
                            coin_pressed = True
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    title_start_pressed = True
                    fire_pressed = True
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    force_pressed = True
                elif event.type == pygame.JOYBUTTONDOWN:
                    title_start_pressed = True
                    fire_pressed = True
            if not running:
                break

            keys = pygame.key.get_pressed()
            target = display.begin_frame()
            if game is None:
                title.update()
                title.render(target)
                if prepared_game is None:
                    prepared_game = FullRuntimeGame(
                        sound.command, renderer=reusable_renderer)
                    reusable_renderer = None
                if (title.ready and title_start_pressed and
                        prepared_game.launch_age is None):
                    prepared_game.request_start()
                    title.starting = True
                if prepared_game.launch_age is None:
                    if prepared_game.advance_title():
                        game = prepared_game
                elif prepared_game.advance_start():
                    game = prepared_game
            elif game.attract_demo_finished:
                # Демо кончилась сама, как в аркаде: ROM ушёл из состояния $0A8B в презентацию
                # цикла (замер покадрово: демо 33…36 с, затем заставка и логотип). Машину не
                # перезапускаем, иначе ROM начнёт аттракт сначала и покажет ту же первую демо.
                sound.reset_session()
                held_input.clear_actions()
                title = TitleScreen(title_assets)
                game.ready = False
                prepared_game = game
                game = None
                title.render(target)
            elif game.is_attract_demo and demo_wake_pressed:
                # Any Key, ЛКМ или кнопка джойстика только будят главный экран.
                # Машина остаётся прежней: иначе ROM начнёт аттракт сначала и
                # покажет ту же первую демо вместо следующей по циклу.
                sound.reset_session()
                held_input.clear_actions()
                title = TitleScreen(title_assets)
                game.ready = False
                prepared_game = game
                game = None
                title.render(target)
            elif game.return_to_custom_title:
                # После GAME OVER либо завершившейся демо скрыть системный
                # INSERT COIN и снова показать самостоятельный title. После
                # своей игры машина перезапускается, после демо — продолжает
                # цикл аттракта ROM: в аркаде демо идут разные (замер по MAME).
                played = game.launch_age is not None
                sound.reset_session()
                held_input.clear_actions()
                title = TitleScreen(title_assets)
                if played:
                    reusable_renderer = game.renderer
                    prepared_game = None
                else:
                    game.ready = False
                    prepared_game = game
                game = None
                title.render(target)
            else:
                input_mask = _input_mask(
                    keys, held_input, fire_pulse=fire_pressed,
                    force_pulse=force_pressed)
                game.update(
                    input_mask,
                    start1=system_start_pressed,
                    coin1=coin_pressed)
                game.render(target)
            z80.next_frame(_input_mask(
                keys, held_input, fire_pulse=fire_pressed,
                force_pulse=force_pressed),
                           1 if game is not None else 0)
            display.present(screen)
            sound.step_frame()
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
