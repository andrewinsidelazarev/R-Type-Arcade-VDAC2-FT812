"""Literal two-Bit player-owned state machines from R-Type World ROM."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pygame

from .enemies import M72Rom, M72SpriteAtlas, read_descriptor


Q8 = 0x100


def _u16(value: int) -> int:
    return value & 0xFFFF


def _s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


@dataclass
class BitObject:
    """Fixed record `$0120` or `$0140` and its private history arrays."""

    index: int
    x_q8: int
    y_q8: int
    resource_slot: int
    animation: int = 0
    strength: int = 0
    idle_counter: int = 0
    write_cursor: int = 2
    read_cursor: int = 0
    descriptor: int = 0x26FE
    history_x: list[int] = field(default_factory=list)
    history_y: list[int] = field(default_factory=list)

    @property
    def x(self) -> int:
        return _u16(self.x_q8 >> 8)

    @property
    def y(self) -> int:
        return _u16(self.y_q8 >> 8)


class PlayerBits:
    """Idle/active handlers `$2CE5…$3066` for both fixed Bit records."""

    def __init__(self, rom: M72Rom) -> None:
        self.rom = rom
        self.objects: dict[int, BitObject] = {}
        self.last_direction = 0

    def sync_and_update(
            self, count: int, player_native: tuple[int, int], direction: int,
            frame_counter: int, acquire: Callable[[int], int],
            release: Callable[[int], None],
            terrain_address: Callable[[int, int], int] | None = None,
            terrain_cell: Callable[[int], tuple[int, int]] | None = None,
            replace_terrain: Callable[[int, int, int], None] | None = None
            ) -> None:
        """Run the two idle records and every active record once per VBlank."""
        count &= 0xFF
        direction &= 0x0F
        changed_direction = direction if direction != self.last_direction else 0
        self.last_direction = direction

        if count >= 1 and 0 not in self.objects:
            self.objects[0] = self._activate(0, player_native, acquire)
        if count >= 2 and 1 not in self.objects:
            self.objects[1] = self._activate(1, player_native, acquire)

        for index, bit in tuple(self.objects.items()):
            # Both active handlers test `(word[$0033] & $00FF)==0`; the
            # second Bit therefore remains until the count reaches zero.
            if count == 0:
                release(bit.resource_slot)
                del self.objects[index]
                continue
            self._update_one(bit, player_native, direction,
                             changed_direction, frame_counter)
            self._clear_09f6(bit.x, bit.y, terrain_address, terrain_cell,
                             replace_terrain)

    def _activate(self, index: int, player: tuple[int, int],
                  acquire: Callable[[int], int]) -> BitObject:
        x, y = player
        history_y = _u16(y + (0x10 if index == 0 else -0x10))
        return BitObject(
            index=index, x_q8=x * Q8, y_q8=y * Q8,
            resource_slot=acquire(0x56),
            history_x=[x] * 16, history_y=[history_y] * 16,
        )

    def _update_one(self, bit: BitObject, player: tuple[int, int],
                    direction: int, changed_direction: int,
                    frame: int) -> None:
        if changed_direction and bit.strength < 0xE0:
            bit.strength = (bit.strength + 5) & 0xFF
        bit.strength = max(0, bit.strength - 1)

        if (frame & 7) == 0:
            if bit.idle_counter >= 7:
                bit.strength = 0
            bit.idle_counter = 0
        if changed_direction == 0:
            bit.idle_counter = (bit.idle_counter + 1) & 0xFF

        coarse = (bit.strength >> 6) & 7
        offset_record = 0x15DE + coarse * 0x40 + direction * 4
        target_x = _u16(player[0] + _s16(self.rom.word(offset_record)))
        vertical_bias = 0x20 if bit.index == 0 else -0x20
        target_y = _u16(player[1] + vertical_bias +
                        _s16(self.rom.word(offset_record + 2)))
        write_index = (bit.write_cursor & 0x1E) >> 1
        bit.history_x[write_index] = target_x
        bit.history_y[write_index] = target_y
        bit.write_cursor = (bit.write_cursor + 2) & 0x1F

        speed_table = 0x16DE if bit.index == 0 else 0x171E
        speed_index = ((bit.strength >> 3) & 0x1F) if direction else 0
        speed = self.rom.word(speed_table + speed_index * 2)
        tolerance = (speed >> 8) & 0xFF
        read_index = (bit.read_cursor & 0x1E) >> 1
        velocity_x = self._axis_velocity(
            bit.history_x[read_index], bit.x, speed, tolerance)
        velocity_y = self._axis_velocity(
            bit.history_y[read_index], bit.y, speed, tolerance)
        bit.x_q8 += velocity_x
        bit.y_q8 += velocity_y
        bit.read_cursor = (bit.read_cursor + 2) & 0x1F

        if (frame & 3) == 0:
            bit.animation = (bit.animation + 1) % 12
        descriptor_base = 0x175E if bit.index == 0 else 0x17A6
        bit.descriptor = descriptor_base + bit.animation * 6

    @staticmethod
    def _axis_velocity(target: int, current: int,
                       speed: int, tolerance: int) -> int:
        # Exact unsigned window used by `$2E02…$2E19/$2E3C…$2E53`.
        if target < _u16(current + tolerance):
            if target < _u16(current - tolerance):
                return -speed
            return 0
        return speed

    @staticmethod
    def _clear_09f6(
            x: int, y: int,
            terrain_address: Callable[[int, int], int] | None,
            terrain_cell: Callable[[int], tuple[int, int]] | None,
            replace_terrain: Callable[[int, int, int], None] | None) -> None:
        """`$2736`: four exact cells after the `(-4,+4)` coordinate probe."""
        if x < 0x0140 or not (terrain_address and terrain_cell and
                              replace_terrain):
            return
        address = terrain_address(_u16(x - 4), _u16(y + 4))
        for offset in (0, 4, 0x104, 0x100):
            cell_address = (address + offset) & 0x3FFF
            code, _attribute = terrain_cell(cell_address)
            if code & 0x0FFF == 0x09F6:
                replace_terrain(cell_address, 0x0FA0, 0)

    def draw(self, target: pygame.Surface, atlas: M72SpriteAtlas) -> None:
        for bit in self.objects.values():
            if bit.resource_slot != 0xFF:
                atlas.draw(target, read_descriptor(self.rom, bit.descriptor),
                           bit.resource_slot, 0x56, bit.x, bit.y)

    def collision_rects(self) -> tuple[pygame.Rect, ...]:
        # `$17EE=(12,12,12,12)`, installed by `$38F4` in both handlers.
        result = []
        for left_native, right_native, lower_native, upper_native in (
                self.collision_bounds()):
            left = round((left_native - 0x0140) * 5 / 3)
            right = round((right_native - 0x0140) * 5 / 3)
            top = round((0x0180 - upper_native) * 15 / 8)
            bottom = round((0x0180 - lower_native) * 15 / 8)
            result.append(pygame.Rect(left, top, right - left, bottom - top))
        return tuple(result)

    def collision_bounds(self) -> tuple[tuple[int, int, int, int], ...]:
        """Native `$0138..$013E/$0158..$015E` endpoint records."""
        return tuple(
            (bit.x - 12, bit.x + 12, bit.y - 12, bit.y + 12)
            for bit in self.objects.values()
        )
