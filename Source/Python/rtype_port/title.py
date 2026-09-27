"""Стартовый экран, воспроизводимый без исполнения аркадного ROM."""
from __future__ import annotations

import struct
from pathlib import Path

import pygame


ROOT = Path(__file__).resolve().parents[3]
FONT_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_FONT_ARGB4444.bin"

LOGO_W, LOGO_H = 107, 120
TEXT_W, TEXT_H = 14, 15
LOGO_COUNT = 7
TEXT_COUNT = 96
TEXT_STYLES = 3
# Кадр, с которого титул принимает FIRE: строки экрана к нему дорисованы. Приглашение зажигается ровно
# с него. Раньше оно горело с 276-го кадра, и первая его вспышка (32 кадра) целиком лежала в мёртвой
# зоне: игрок видел «PRESS FIRE», жал — нажатие не принималось, а кадр готовности приходился уже на
# погашенную фазу. Решение пользователя 22.09.2026: надпись появляется позже, зато всегда честная.
READY_FRAME = 315
PROMPT_FIRST_FRAME = READY_FRAME
PROMPT_BLINK_PERIOD = 64
PROMPT_VISIBLE_FRAMES = 32

# Координаты финальной композиции в исходном растре M72.
LOGO_X = (16, 87, 119, 184, 247, 311, 344)
LOGO_Y = (128, 128, 128, 128, 128, 128, 184)
COLLAPSED_X = (16, 32, 16, 16, 16, 16)
SPREAD_STEP_Q8 = (0, 296, 552, 896, 1236, 1576)


def _argb4444_surface(data: bytes, width: int, height: int) -> pygame.Surface:
    rgba = bytearray(width * height * 4)
    for index, (value,) in enumerate(struct.iter_unpack("<H", data)):
        rgba[index * 4 + 0] = ((value >> 8) & 15) * 17
        rgba[index * 4 + 1] = ((value >> 4) & 15) * 17
        rgba[index * 4 + 2] = (value & 15) * 17
        rgba[index * 4 + 3] = ((value >> 12) & 15) * 17
    return pygame.image.frombytes(bytes(rgba), (width, height), "RGBA").convert_alpha()


class TitleAssets:
    """Офлайн-масштабированные глифы логотипа и ROM-шрифта."""

    def __init__(self) -> None:
        blob = FONT_PATH.read_bytes()
        logo_bytes = LOGO_W * LOGO_H * 2
        text_bytes = TEXT_W * TEXT_H * 2
        expected = LOGO_COUNT * logo_bytes + TEXT_STYLES * TEXT_COUNT * text_bytes
        if len(blob) != expected:
            raise ValueError(f"неверный размер титульного атласа: {len(blob)} вместо {expected}")
        offset = 0
        self.logos: list[pygame.Surface] = []
        for _ in range(LOGO_COUNT):
            self.logos.append(_argb4444_surface(blob[offset:offset + logo_bytes], LOGO_W, LOGO_H))
            offset += logo_bytes
        self.text: list[list[pygame.Surface]] = []
        for _ in range(TEXT_STYLES):
            style: list[pygame.Surface] = []
            for _ in range(TEXT_COUNT):
                style.append(_argb4444_surface(blob[offset:offset + text_bytes], TEXT_W, TEXT_H))
                offset += text_bytes
            self.text.append(style)


def _native_x(value: int) -> int:
    return round(value * 640 / 384)


def _native_y(value: int) -> int:
    return round(value * 480 / 256)


def _logo_state(frame: int, glyph: int) -> tuple[bool, int, int]:
    """Координатная анимация из подтверждённого титульного прогона."""
    if frame <= 0:
        return False, -320, 368
    if glyph < 6:
        if frame <= 64:
            return True, COLLAPSED_X[glyph] + (64 - frame) * 6, 72
        if frame <= 80:
            return True, COLLAPSED_X[glyph], 72
        if frame <= 128:
            step = frame - 80
            x = COLLAPSED_X[glyph] + (SPREAD_STEP_Q8[glyph] * step >> 8)
            return True, min(x, LOGO_X[glyph]), 72
        if frame <= 176:
            return True, LOGO_X[glyph], 72
        if frame <= 204:
            return True, LOGO_X[glyph], 72 + (frame - 176) * 2
        return True, LOGO_X[glyph], LOGO_Y[glyph]

    if frame < 123:
        return False, -20, -28
    if frame <= 148:
        step = frame - 122
        x = -20 + step * 14
        y = -28 + step * 6
        return frame >= 126, x, y
    if frame <= 176:
        return True, 344, 128
    if frame <= 204:
        return True, 344, 128 + (frame - 176) * 2
    return True, 344, 184


def prompt_visible(frame: int) -> bool:
    """Мерцание приглашения: 32 кадра видно, 32 кадра скрыто."""
    if frame < PROMPT_FIRST_FRAME:
        return False
    phase = (frame - PROMPT_FIRST_FRAME) % PROMPT_BLINK_PERIOD
    return phase < PROMPT_VISIBLE_FRAMES


def _draw_text(target: pygame.Surface, assets: TitleAssets, text: str,
               column: int, row: int, style: int, visible_chars: int | None = None,
               y_offset: int = 0) -> None:
    """y_offset — сдвиг строки вниз в логических пикселях от её строки сетки."""
    remaining = len(text.replace(" ", "")) if visible_chars is None else visible_chars
    for offset, character in enumerate(text):
        if character == " ":
            continue
        if remaining <= 0:
            break
        code = ord(character) - 32
        if 0 <= code < TEXT_COUNT:
            x = round((column + offset) * 640 / 48)
            target.blit(assets.text[style][code], (x, row * TEXT_H + y_offset))
        remaining -= 1


class TitleScreen:
    """Процедурное состояние стартового экрана без кредитов и монет."""

    def __init__(self, assets: TitleAssets) -> None:
        self.assets = assets
        self.frame = 0
        # Старт игры запрошен (FIRE на готовом титуле): до первого кадра игры вместо приглашения — «GAME STARTING».
        self.starting = False

    @property
    def ready(self) -> bool:
        return self.frame >= READY_FRAME

    def update(self) -> None:
        self.frame += 1

    def render(self, target: pygame.Surface) -> None:
        target.fill("black")
        for glyph in range(LOGO_COUNT):
            visible, x, y = _logo_state(self.frame, glyph)
            if visible:
                target.blit(self.assets.logos[glyph], (_native_x(x), _native_y(y)))

        # Скорость появления строк повторяет исходный экран: до трёх знаков за кадр.
        # Поля: первый кадр, текст, столбец, строка сетки, стиль, сдвиг вниз в логических пикселях.
        lines = (
            (217, "BLAST OFF AND STRIKE", 25, 4, 0, 0),
            (229, "THE EVIL BYDO EMPIRE!", 25, 5, 0, 0),
            (245, "START GAME", 27, 7, 0, 0),
            (308, "1987 BY IREM CORP.", 24, 28, 0, 0),
            # Строка автора порта (решение пользователя 2026-09-15): тем же шрифтом под строкой 1987,
            # «2026» под «1987», на 3 пикселя ниже соседней строки сетки, появляется сразу после неё.
            (314, "2026 BY ANDREW LAZAREV", 24, 29, 0, 3),
        )
        for first_frame, text, column, row, style, y_offset in lines:
            visible = max(0, (self.frame - first_frame + 1) * 3)
            _draw_text(target, self.assets, text, column, row, style, visible, y_offset)

        # На ZX начало игры задаётся FIRE/ENTER, поэтому кредитной строки здесь нет.
        # После FIRE скрытый старт машины и первый кадр игры идут несколько секунд: на месте приглашения горит
        # «GAME STARTING» (решение пользователя 2026-09-15), тем же стилем, по центру той же строки.
        if self.starting:
            _draw_text(target, self.assets, "GAME STARTING", 31, 10, 1)
        elif prompt_visible(self.frame):
            _draw_text(target, self.assets, "PRESS FIRE", 32, 10, 1)
