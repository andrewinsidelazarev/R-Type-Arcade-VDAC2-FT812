"""Host-модели целевых Z80/FT812 узлов активного Python-runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pygame


LOGICAL_WIDTH = 640
LOGICAL_HEIGHT = 480
PHYSICAL_WIDTH = 1024
PHYSICAL_HEIGHT = 768
RAM_G_SIZE = 1024 * 1024
VERTEX_FORMAT = 3
FT_ARGB4 = 6


def _eve_word(opcode: int, value: int = 0) -> int:
    return ((opcode & 0xFF) << 24) | (value & 0xFFFFFF)


def _physical_size(value: int) -> int:
    return (value * 8 + 2) // 5


def _vertex_units(value: int) -> int:
    return (value * 64 + 2) // 5


def _argb4444(surface: pygame.Surface) -> tuple[bytes, pygame.Surface]:
    """Квантовать Surface тем же форматом, который хранится в RAM_G."""
    width, height = surface.get_size()
    rgba = np.frombuffer(
        pygame.image.tobytes(surface, "RGBA"), dtype=np.uint8
    ).reshape(-1, 4)
    nibbles = rgba >> 4
    values = (
        (nibbles[:, 3].astype(np.uint16) << 12) |
        (nibbles[:, 0].astype(np.uint16) << 8) |
        (nibbles[:, 1].astype(np.uint16) << 4) |
        nibbles[:, 2].astype(np.uint16)
    )
    packed = values.astype("<u2", copy=False).tobytes()
    decoded = (nibbles * 17).astype(np.uint8, copy=False).tobytes()
    image = pygame.image.frombytes(
        decoded, (width, height), "RGBA").convert_alpha()
    return packed, image


@dataclass(frozen=True)
class Ft812Bitmap:
    """Один неизменяемый ARGB4444 bitmap, загруженный в RAM_G."""

    source: int
    width: int
    height: int
    stride: int
    surface: pygame.Surface


class Ft812CommandSurface:
    """Минимальный Surface-интерфейс, превращающий fill/blit в FT812 DL."""

    def __init__(self, display: "Ft812Display") -> None:
        self._display = display

    def fill(self, color: pygame.Color | str | Sequence[int],
             rect: pygame.Rect | Sequence[int] | None = None
             ) -> pygame.Rect:
        return self._display.fill(color, rect)

    def blit(self, source: pygame.Surface,
             destination: pygame.Rect | Sequence[int]) -> pygame.Rect:
        return self._display.blit(source, destination)

    def invalidate(self, source: pygame.Surface) -> None:
        """Пометить изменяемый framebuffer для повторной загрузки в RAM_G."""
        self._display.invalidate(source)

    def blit_argb4444(self, source: pygame.Surface, packed: bytes,
                      destination: pygame.Rect | Sequence[int]) -> pygame.Rect:
        """Загрузить уже готовые FT812 ARGB4 words без повторной квантизации."""
        return self._display.blit_argb4444(source, packed, destination)

    def get_width(self) -> int:
        return LOGICAL_WIDTH

    def get_height(self) -> int:
        return LOGICAL_HEIGHT

    def get_size(self) -> tuple[int, int]:
        return LOGICAL_WIDTH, LOGICAL_HEIGHT


class Ft812Display:
    """FT812 RAM_G и display-list с выводом в логический pygame-экран."""

    def __init__(self) -> None:
        self.ram_g = bytearray(RAM_G_SIZE)
        self.logical = pygame.Surface(
            (LOGICAL_WIDTH, LOGICAL_HEIGHT), flags=pygame.SRCALPHA, depth=32
        ).convert_alpha()
        self.surface = Ft812CommandSurface(self)
        self.words: list[int] = []
        self._encoded: dict[int, tuple[bytes, pygame.Surface, int, int]] = {}
        self._frame_assets: dict[int, Ft812Bitmap] = {}
        self._ram_write = 0
        self.begin_frame()

    def begin_frame(self) -> Ft812CommandSurface:
        self.words.clear()
        self._frame_assets.clear()
        self._ram_write = 0
        self.logical.fill((0, 0, 0, 255))
        self.words.extend((
            _eve_word(0x02, 0x000000),
            _eve_word(0x26, 0x000007),
            _eve_word(0x27, VERTEX_FORMAT),
            _eve_word(0x15, 160),
            _eve_word(0x19, 160),
        ))
        return self.surface

    def invalidate(self, source: pygame.Surface) -> None:
        """Удалить только host-кэш указанного изменяемого bitmap."""
        self._encoded.pop(id(source), None)

    def _upload(self, source: pygame.Surface) -> Ft812Bitmap:
        key = id(source)
        current = self._frame_assets.get(key)
        if current is not None:
            return current
        encoded = self._encoded.get(key)
        width, height = source.get_size()
        if encoded is None or encoded[2:] != (width, height):
            packed, decoded = _argb4444(source)
            encoded = packed, decoded, width, height
            self._encoded[key] = encoded
        packed, decoded, width, height = encoded
        aligned = (self._ram_write + 3) & ~3
        end = aligned + len(packed)
        if end > RAM_G_SIZE:
            raise MemoryError(
                f"кадр FT812 требует больше RAM_G: {end} из {RAM_G_SIZE}")
        self.ram_g[aligned:end] = packed
        bitmap = Ft812Bitmap(aligned, width, height, width * 2, decoded)
        self._frame_assets[key] = bitmap
        self._ram_write = end
        return bitmap

    def fill(self, color: pygame.Color | str | Sequence[int],
             rect: pygame.Rect | Sequence[int] | None = None
             ) -> pygame.Rect:
        parsed = pygame.Color(color)
        target = (pygame.Rect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT)
                  if rect is None else pygame.Rect(rect))
        self.logical.fill(parsed, target)
        if target == pygame.Rect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT):
            rgb = (parsed.r << 16) | (parsed.g << 8) | parsed.b
            self.words.extend((_eve_word(0x02, rgb), _eve_word(0x26, 7)))
        else:
            rgb = (parsed.r << 16) | (parsed.g << 8) | parsed.b
            self.words.extend((
                _eve_word(0x04, rgb),
                _eve_word(0x1F, 9),
                self._vertex(target.left, target.top),
                self._vertex(target.right, target.bottom),
                _eve_word(0x21),
            ))
        return target

    @staticmethod
    def _vertex(x: int, y: int) -> int:
        x_units = _vertex_units(x) & 0x7FFF
        y_units = _vertex_units(y) & 0x7FFF
        return 0x40000000 | (x_units << 15) | y_units

    def blit(self, source: pygame.Surface,
             destination: pygame.Rect | Sequence[int]) -> pygame.Rect:
        bitmap = self._upload(source)
        return self._blit_bitmap(bitmap, destination)

    def blit_argb4444(self, source: pygame.Surface, packed: bytes,
                      destination: pygame.Rect | Sequence[int]) -> pygame.Rect:
        """Разместить динамический framebuffer, уже представленный ARGB4."""
        width, height = source.get_size()
        expected = width * height * 2
        if len(packed) != expected:
            raise ValueError(
                f"ARGB4 framebuffer: {len(packed)} bytes вместо {expected}")
        aligned = (self._ram_write + 3) & ~3
        end = aligned + len(packed)
        if end > RAM_G_SIZE:
            raise MemoryError(
                f"кадр FT812 требует больше RAM_G: {end} из {RAM_G_SIZE}")
        self.ram_g[aligned:end] = packed
        self._ram_write = end
        bitmap = Ft812Bitmap(aligned, width, height, width * 2, source)
        return self._blit_bitmap(bitmap, destination, fast_alpha=True)

    def _blit_bitmap(self, bitmap: Ft812Bitmap,
                     destination: pygame.Rect | Sequence[int], *,
                     fast_alpha: bool = False) -> pygame.Rect:
        if isinstance(destination, pygame.Rect):
            x, y = destination.x, destination.y
        else:
            x, y = int(destination[0]), int(destination[1])
        target = pygame.Rect(x, y, bitmap.width, bitmap.height)
        self.logical.blit(
            bitmap.surface, target,
            special_flags=(pygame.BLEND_ALPHA_SDL2 if fast_alpha else 0))
        physical_width = _physical_size(bitmap.width)
        physical_height = _physical_size(bitmap.height)
        self.words.extend((
            _eve_word(0x01, bitmap.source),
            _eve_word(0x28, ((bitmap.stride >> 10) << 2) |
                      (bitmap.height >> 9)),
            _eve_word(0x07, (FT_ARGB4 << 19) |
                      ((bitmap.stride & 0x3FF) << 9) |
                      (bitmap.height & 0x1FF)),
            _eve_word(0x29, ((physical_width >> 9) << 2) |
                      (physical_height >> 9)),
            _eve_word(0x08, (1 << 20) |
                      ((physical_width & 0x1FF) << 9) |
                      (physical_height & 0x1FF)),
            _eve_word(0x1F, 1),
            self._vertex(x, y),
            _eve_word(0x21),
        ))
        return target

    @property
    def ram_g_used(self) -> int:
        return self._ram_write

    @property
    def display_list(self) -> bytes:
        words = self.words + [_eve_word(0x00)]
        return b"".join(word.to_bytes(4, "little") for word in words)

    def present(self, screen: pygame.Surface) -> None:
        screen.blit(self.logical, (0, 0))


class Z80TargetMachine:
    """Исполняемый Z80-диспетчер кадра с 64-КБ памятью и портами."""

    FRAME_COUNTER = 0x4200
    INPUT_STATE = 0x4202
    GAME_MODE = 0x4271
    PROGRAM = 0x8000
    FRAME_LOOP = 0x8004
    PORT_ROUTINE = 0x8040

    _FRAME_PROGRAM = bytes((
        0xF3,                         # Запрет прерываний.
        0x31, 0xFE, 0xFF,             # Установка стека $FFFE.
        0x2A, 0x00, 0x42,             # Чтение счётчика кадра.
        0x23,                         # Прибавление единицы.
        0x22, 0x00, 0x42,             # Сохранение счётчика кадра.
        0x3A, 0x02, 0x42,             # Чтение байта ввода.
        0xD3, 0xFE,                   # Вывод ввода в порт $FE.
        0x3A, 0x71, 0x42,             # Чтение номера сцены.
        0xD3, 0xFD,                   # Вывод сцены в порт $FD.
        0x76,                         # Граница кадра.
    ))

    def __init__(self) -> None:
        try:
            import z80
        except ImportError as error:  # pragma: no cover - ошибка установки
            raise RuntimeError("для целевого диспетчера нужен пакет z80") from error
        self.cpu = z80.Z80Machine()
        self.cpu.memory[:] = bytes(0x10000)
        self.cpu.set_memory_block(self.PROGRAM, self._FRAME_PROGRAM)
        self.cpu.pc = self.PROGRAM
        self.cpu.sp = 0xFFFE
        self.cpu.set_output_callback(self._output)
        self.memory = self.cpu.memory
        self.out_log: list[tuple[int, int]] = []
        self._first_frame = True

    def _output(self, port: int, value: int) -> None:
        self.out_log.append((port & 0xFFFF, value & 0xFF))

    def read_byte(self, address: int) -> int:
        return self.memory[address & 0xFFFF]

    def write_byte(self, address: int, value: int) -> None:
        self.memory[address & 0xFFFF] = value & 0xFF

    def read_word(self, address: int) -> int:
        return self.read_byte(address) | (self.read_byte(address + 1) << 8)

    def write_word(self, address: int, value: int) -> None:
        self.write_byte(address, value)
        self.write_byte(address + 1, value >> 8)

    def next_frame(self, input_mask: int, game_mode: int) -> int:
        self.write_byte(self.INPUT_STATE, input_mask)
        self.write_byte(self.GAME_MODE, game_mode)
        if self._first_frame:
            # До первого VBlank звук уже может выполнить отдельный OUT.
            # Поэтому reset entry задаётся здесь повторно, а не полагается
            # на PC, оставшийся после конструктора.
            self.cpu.pc = self.PROGRAM
        else:
            self.cpu.pc = self.FRAME_LOOP
        self.cpu.halted = False
        self._first_frame = False
        self.cpu.ticks_to_stop = 1000
        self.cpu.run()
        if not self.cpu.halted:
            raise RuntimeError("Z80 не дошёл до границы кадра")
        return self.read_word(self.FRAME_COUNTER)

    def out_port(self, port: int, value: int) -> None:
        routine = bytes((
            0x01, port & 0xFF, (port >> 8) & 0xFF,  # Адрес порта в BC.
            0x3E, value & 0xFF,                    # Значение в A.
            0xED, 0x79,                            # Портовая запись.
            0x76,                                  # Граница транзакции.
        ))
        self.cpu.set_memory_block(self.PORT_ROUTINE, routine)
        self.cpu.halted = False
        self.cpu.pc = self.PORT_ROUTINE
        self.cpu.ticks_to_stop = 1000
        self.cpu.run()
        if not self.cpu.halted:
            raise RuntimeError("Z80 не завершил портовую транзакцию")


Z80TargetState = Z80TargetMachine
