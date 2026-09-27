"""Полный World runtime, выведенный через целевые Z80/FT812/audio границы."""
from __future__ import annotations

from typing import Callable

import pygame

from rtype_m72.hq_renderer import HEIGHT, WIDTH, M72HqRenderer
from rtype_m72.machine import FrameState, RTypeM72Machine

from .player_lifecycle import INITIAL_LIVES, MAX_LIVES


PLAYER_LAUNCH_HANDLERS = frozenset((0x1F3D, 0x2027))
ARCADE_PRESENTATION_ENTRY = 0x076C
# Демо аттракта: ROM ведёт её состоянием директора $0A8B. Замер аркады покадрово (MAME,
# 20 000 кадров, 2026-09-20): цикл $07DA 0.6 с → $085A 3.8 с → $094A 4.7 с → $0A8B демо 33…36 с
# → $0AE7 0.6 с → $0B9E 4.1 с, этапы демо по кругу 4 → 2 → 3. Состояний $076C и $124F в этом
# цикле нет вовсе, поэтому конец демо по ним не ловится и демо шло без конца.
ATTRACT_DEMO_HANDLER = 0x0A8B
GAME_OVER_DELAY_HANDLER = 0x124F
COIN_PULSE_FRAMES = frozenset((0, 1))
START_PULSE_FRAMES = frozenset((30, 31))
DSW_LIVES_TABLE_ADDRESS = 0x10400
LIVES_CAP_IMMEDIATE_ADDRESS = 0x0ED58
BONUS_LIFE_TABLES = (
    (0x186B4, (25_000, 75_000, 125_000, 200_000, 300_000)),
    (0x186CC, (50_000, 100_000, 175_000, 250_000, 350_000)),
)
# Старший байт immediate `MOV word [SI+4],$0200` (0040:0AA6) в attract controller
# `$0A8B`: X надписи GAME OVER (visual `$23C8`), которую ROM создаёт в демо.
ATTRACT_GAME_OVER_X_HIGH_ADDRESS = 0x00EAA


def _packed_bcd_score(value: int) -> bytes:
    """Упаковать восьмизначное значение очков младшими парами вперёд."""
    if not 0 <= value <= 99_999_999:
        raise ValueError("packed-BCD score должен быть восьмизначным")
    result = bytearray()
    for _ in range(4):
        pair = value % 100
        result.append(((pair // 10) << 4) | (pair % 10))
        value //= 100
    return bytes(result)


def _bonus_life_table(thresholds: tuple[int, ...]) -> bytes:
    """Собрать ROM-таблицу порогов, где каждая запись на единицу меньше."""
    return (b"".join(_packed_bcd_score(threshold - 1)
                     for threshold in thresholds) + b"\xFF" * 4)


class FullRuntimeGame:
    """Совместимый полный автомат Canonical с целевым видеовыходом.

    V30 World ROM остаётся исполнимым источником всех восьми stages и
    системных экранов. Каждый его кадр одновременно проходит через реальный
    Z80-диспетчер владельца приложения, а итоговый 640×480 framebuffer
    загружается в RAM_G и выводится display list FT812.
    """

    def __init__(self, sound_command: Callable[[int], None], *,
                 enable_renderer: bool = True,
                 renderer: M72HqRenderer | None = None) -> None:
        if renderer is not None and not enable_renderer:
            raise ValueError("готовый renderer несовместим с выключенным выводом")
        self.machine = RTypeM72Machine(sound_command)
        self._apply_balance()
        self._apply_fixes()
        self.machine.boot()
        self.renderer = ((renderer if renderer is not None else M72HqRenderer())
                         if enable_renderer else None)
        self.frame_state: FrameState | None = None
        self.surface: pygame.Surface | None = None
        self.machine_frames = 0
        self.launch_age: int | None = None
        self.ready = False
        self._step_machine(0, False, False, render=enable_renderer)

    def _apply_balance(self) -> None:
        """Наложить пользовательский баланс только на память этого runtime."""
        # Все четыре DSW-варианта исходных 2/3/4/5 теперь дают восемь жизней.
        self.machine.cpu.mem_write(
            DSW_LIVES_TABLE_ADDRESS, bytes((INITIAL_LIVES,)) * 4)
        # ROM сравнивал lives с `$FFFF`; новый immediate запрещает девятую жизнь
        # до INC и потому не проигрывает ложный звук награды при полном запасе.
        self.machine.cpu.mem_write(
            LIVES_CAP_IMMEDIATE_ADDRESS, bytes((MAX_LIVES,)))
        for address, thresholds in BONUS_LIFE_TABLES:
            self.machine.cpu.mem_write(address, _bonus_life_table(thresholds))

    def _apply_fixes(self) -> None:
        """Исправить логические нестыковки ROM по решению пользователя."""
        # 2026-09-14: демо дважды (таймер `$40` и `$80`) пишет GAME OVER, хотя игры
        # ещё не было. Объект `$23C8` по-прежнему создаётся — слоты, ресурсы и
        # таймеры те же, — но с X=$0000 все буквы уходят за экран. Настоящий
        # GAME OVER создают `$23A8` и `$EFED` со своими X=$0200: он остаётся.
        self.machine.cpu.mem_write(ATTRACT_GAME_OVER_X_HIGH_ADDRESS, b"\x00")

    def _player_handler(self) -> int:
        data = self.machine.cpu.mem_read(0x40020, 2)
        return int.from_bytes(data, "little")

    def _director_handler(self) -> int:
        data = self.machine.cpu.mem_read(0x40000, 2)
        return int.from_bytes(data, "little")

    def _director_timer(self) -> int:
        data = self.machine.cpu.mem_read(0x4001E, 2)
        return int.from_bytes(data, "little")

    @property
    def return_to_custom_title(self) -> bool:
        """Сессия закончена до CONTINUE/INSERT COIN и arcade title.

        `$124F` выдерживает последний штатный GAME OVER. При timer=1 следующий
        step уже прыгает в `$1446…$12E2`, где ROM строит CONTINUE, INSERT COIN
        и CREDIT. Запасной `$076C` закрывает остальные terminal-пути до первого
        кадра аркадной презентации.
        """
        if not self.ready:
            return False
        handler = self._director_handler()
        return ((handler == GAME_OVER_DELAY_HANDLER and
                 self._director_timer() <= 1) or
                handler == ARCADE_PRESENTATION_ENTRY)

    @property
    def attract_demo_finished(self) -> bool:
        """Демо аттракта закончилась: ROM вышел из состояния $0A8B в презентацию цикла."""
        return (self.ready and self.launch_age is None and
                self._director_handler() != ATTRACT_DEMO_HANDLER)

    @property
    def is_attract_demo(self) -> bool:
        """Сейчас показана штатная демо-игра без пользовательского старта."""
        return self.ready and self.launch_age is None

    def _step_machine(self, input_mask: int, start1: bool, coin1: bool,
                      *, render: bool) -> None:
        self.machine.inputs.set_player(
            right=bool(input_mask & 0x01),
            left=bool(input_mask & 0x02),
            down=bool(input_mask & 0x04),
            up=bool(input_mask & 0x08),
            button1=bool(input_mask & 0x10),
            button2=bool(input_mask & 0x20),
        )
        self.machine.inputs.set_system(start1=start1, coin1=coin1)
        self.frame_state = self.machine.step_frame()
        self.machine_frames += 1
        if render:
            self._render_frame_state()

    def _render_frame_state(self) -> None:
        if self.renderer is None or self.frame_state is None:
            return
        self.renderer.render(self.frame_state)
        if self.surface is None:
            self.surface = pygame.image.frombuffer(
                self.renderer.rgba, (WIDTH, HEIGHT), "RGBA")

    def advance_title(self) -> bool:
        """Продвинуть скрытый title и открыть штатную демо-игру при её старте."""
        if self.launch_age is not None or self.ready:
            return self.ready
        self._step_machine(0, False, False, render=False)
        if self._player_handler() in PLAYER_LAUNCH_HANDLERS:
            self.ready = True
            self._render_frame_state()
        return self.ready

    def request_start(self) -> None:
        """Начать штатную arcade-последовательность coin → start один раз."""
        if self.launch_age is None and not self.ready:
            self.launch_age = 0

    def advance_start(self) -> bool:
        """Продвинуть скрытый переход, сохраняя текущий title до R-9 launch."""
        if self.ready:
            return True
        if self.launch_age is None:
            return False
        age = self.launch_age
        self._step_machine(
            0,
            start1=age in START_PULSE_FRAMES,
            coin1=age in COIN_PULSE_FRAMES,
            render=False,
        )
        self.launch_age += 1
        if self._player_handler() in PLAYER_LAUNCH_HANDLERS:
            self.ready = True
            self._render_frame_state()
        return self.ready

    def update(self, input_mask: int, *, start1: bool = False,
               coin1: bool = False) -> None:
        if not self.ready:
            raise RuntimeError("полный runtime ещё не дошёл до R-9 launch")
        self._step_machine(input_mask, start1, coin1, render=True)

    def render(self, target: object) -> None:
        if self.surface is None:
            raise RuntimeError("полный runtime не имеет готового framebuffer")
        direct = getattr(target, "blit_argb4444", None)
        if direct is not None and self.renderer is not None:
            packed = self.renderer.words.astype("<u2", copy=False).tobytes()
            direct(self.surface, packed, (0, 0))
            return
        invalidate = getattr(target, "invalidate", None)
        if invalidate is not None:
            invalidate(self.surface)
        target.blit(self.surface, (0, 0))
