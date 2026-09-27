"""Literal player Force object state machine from R-Type World ROM.

The permanent arcade record is ``DS:$0060``.  This module keeps its native
M72 coordinates and Q8 velocities; conversion to the 640x480 output happens
only in :class:`M72SpriteAtlas`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame

from .enemies import M72Rom, M72SpriteAtlas, read_descriptor


Q8 = 0x100
FORCE_RESOURCE_TYPE = 0x56
FORCE_LEVEL_HANDLERS = (0x2682, 0x26AD, 0x26D0, 0x26E9)
FORCE_HITBOX_POINTERS = (0x15C6, 0x15C6, 0x15CE, 0x15D6)

# `$3D7B…$3EA6`: five latch/setup groups used by the unattached matrix.
MATRIX_LATCH_CALLBACKS = frozenset((0x3D7B, 0x3DB7, 0x3DF3, 0x3E2F, 0x3E6B))
MATRIX_STRAIGHT_SETUPS = {
    0x3D81: (0x0D00, 0x0000, 0x203C),
    0x3D89: (0x0D00, 0x0000, 0x203C),
    0x3D91: (0x0D00, 0x0000, 0x203C),
    0x3DBD: (0x0C00, 0x0240, 0x2036),
    0x3DC5: (0x0C00, 0x0240, 0x2036),
    0x3DCD: (0x0C00, 0x0240, 0x2036),
    0x3DF9: (0x0C00, -0x0240, 0x2042),
    0x3E01: (0x0C00, -0x0240, 0x2042),
    0x3E09: (0x0C00, -0x0240, 0x2042),
    0x3E35: (0x0000, 0x0A00, 0x2030),
    0x3E3D: (0x0000, 0x0A00, 0x2030),
    0x3E45: (0x0000, 0x0A00, 0x2030),
    0x3E71: (0x0000, -0x0A00, 0x2048),
    0x3E79: (0x0000, -0x0A00, 0x2048),
    0x3E81: (0x0000, -0x0A00, 0x2048),
}


def _signed_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _u16(value: int) -> int:
    return value & 0xFFFF


@dataclass(frozen=True)
class ForceInput:
    """Inputs consumed by `$24CE/$2581`; direction is `$2F21&$0F`."""

    action_edge: bool = False
    direction: int = 0


@dataclass
class ForceProjectile:
    """One fixed matrix record `$0160…$0440` in common handler `$3EC4`."""

    slot: int
    x_q8: int
    y_q8: int
    velocity_x: int
    velocity_y: int
    descriptor: int
    resource_slot: int
    alive: bool = True

    @property
    def x(self) -> int:
        return _u16(self.x_q8 >> 8)

    @property
    def y(self) -> int:
        return _u16(self.y_q8 >> 8)

    def collision_rect(self) -> pygame.Rect:
        # `ES:$204E=(12,12,4,4)`, written by `$38F4` in `$3EC4`.
        left = round((self.x - 12 - 0x0140) * 5 / 3)
        right = round((self.x + 12 - 0x0140) * 5 / 3)
        top = round((0x0180 - (self.y + 4)) * 15 / 8)
        bottom = round((0x0180 - (self.y - 4)) * 15 / 8)
        return pygame.Rect(left, top, right - left, bottom - top)


@dataclass
class ForceRaySegment:
    """One attached type-$00 matrix segment (`$42B1/$4311` or `$448E/$44EE`)."""

    slot: int
    x: int
    y: int
    delay: int
    phase: int
    linked: bool
    power: int
    mirrored: bool
    state: str = "delay"
    lifetime: int = 0x70
    descriptor: int = 0x26FE
    resource_slot: int = 0xFF
    terminal_offset: int = 0x18


@dataclass
class ForceGridSegment:
    """One attached type-$02/$04 grid-chain record (`$4591…$4926`)."""

    slot: int
    x: int
    y: int
    delay: int
    direction: int
    orientation: int
    linked: bool
    power: int
    state: str = "delay"
    lifetime: int = 0x70
    descriptor: int = 0x26FE
    resource_slot: int = 0xFF
    history_x1: int = 0
    history_y1: int = 0
    history_x2: int = 0
    history_y2: int = 0
    terminal_offset: int = 0x18


@dataclass
class ForceBeam:
    """Four-descriptor attached type-$06` beam (`$4927/$4977/$49CF`)."""

    slot: int
    step_x: int
    expansion_base: int
    flight_base: int
    expansion_hitbox: int
    flight_hitbox: int
    return_handler: int
    x: int = 0
    y: int = 0
    frame: int = 0
    power: int = 5
    state: str = "expansion"
    resource_slot: int = 0xFF
    descriptors: tuple[int, ...] = ()


@dataclass
class ForceDart:
    """Small attached type-$06` projectile handled by `$4E0F…$4EAE`."""

    slot: int
    x: int
    y: int
    descriptor_base: int
    step_x: int
    state: str = "init"
    power: int = 2
    descriptor: int = 0x26FE
    resource_slot: int = 0xFF
    terminal_offset: int = 0x30


class Force:
    """Permanent Force record `$0060` and handlers `$24CE..$2CE4`."""

    def __init__(self, rom: M72Rom) -> None:
        self.rom = rom
        self.level = 0
        self.state = "hidden"
        self.x_q8 = 0x0080 * Q8
        self.y_q8 = 0x0020 * Q8
        self.velocity_x = 0
        self.velocity_y = 0
        self.behind = False              # object `+$0A/+$14`
        self.return_history = False      # object `+$0B`
        self.attached = False            # player `$003F`
        self.animation = 0               # object `+$13`
        self.animation_group = 0         # object `+$15`
        self.descriptor = 0x26FE
        self.old_x_q8 = self.x_q8         # object `+$2A` + fractional `+$34`
        self.last_vertical = 1           # object `+$3A`, initialised at level 1
        self.resource_slot = 0xFF
        self.projectiles: dict[int, ForceProjectile] = {}
        self.ray_segments: dict[int, ForceRaySegment] = {}
        self.grid_segments: dict[int, ForceGridSegment] = {}
        self.beams: dict[int, ForceBeam] = {}
        self.darts: dict[int, ForceDart] = {}

    @property
    def x(self) -> int:
        return _u16(self.x_q8 >> 8)

    @property
    def y(self) -> int:
        return _u16(self.y_q8 >> 8)

    @property
    def visible(self) -> bool:
        return self.level != 0 and self.resource_slot != 0xFF

    def sync_level(self, level: int,
                   acquire: Callable[[int], int],
                   release: Callable[[int], None]) -> bool:
        """Execute indirect level table `ES:$1430` exactly once per change.

        Return whether the level handler ran.  In the ROM `$24CE` jumps to
        `$26AD/$26D0/$26E9` and that handler returns directly to the object
        scheduler; the ordinary return/attached state therefore starts on the
        following pass, not after the level setup in the same pass.
        """
        level = max(0, min(3, level))
        if level == self.level:
            return False
        was_hidden = self.level == 0
        handler = FORCE_LEVEL_HANDLERS[level]
        if handler == 0x2682:
            self.x_q8 = 0x0080 * Q8
            self.y_q8 = 0x0020 * Q8
            release(self.resource_slot)
            self.resource_slot = 0xFF
            self.level = 0
            self.state = "hidden"
            self.animation = 0
            self.behind = False
            self.return_history = False
            self.attached = False
            for projectile in self.projectiles.values():
                release(projectile.resource_slot)
            self.projectiles.clear()
            for segment in self.ray_segments.values():
                release(segment.resource_slot)
            self.ray_segments.clear()
            for segment in self.grid_segments.values():
                release(segment.resource_slot)
            self.grid_segments.clear()
            for beam in self.beams.values():
                release(beam.resource_slot)
            self.beams.clear()
            for dart in self.darts.values():
                release(dart.resource_slot)
            self.darts.clear()
            return True

        # `$26AD/$26D0/$26E9` all release and reacquire resource type `$56`.
        release(self.resource_slot)
        self.resource_slot = acquire(FORCE_RESOURCE_TYPE)
        self.level = level
        self.animation = 0
        if handler == 0x26AD or was_hidden:
            self.y_q8 = 0x0100 * Q8
            self.last_vertical = 1
            self.state = "return"
        return True

    def update(self, player_native: tuple[int, int], history_native:
               tuple[tuple[int, int], ...], inputs: ForceInput,
               frame_counter: int,
               collision_codes: Callable[[int, int], tuple[int, int]],
               terrain_address: Callable[[int, int], int] | None = None,
               terrain_cell: Callable[[int], tuple[int, int]] | None = None,
               replace_terrain: Callable[[int, int, int], None] | None = None,
               scroll_delta: int = 0,
               play_sfx: Callable[[int], None] | None = None,
               background_address: Callable[[int, int], int] | None = None,
               background_cell: Callable[[int], tuple[int, int]] | None = None
               ) -> None:
        if not self.visible:
            return
        play_sfx = play_sfx or (lambda _name: None)
        if self.state == "attached":
            self._update_attached(player_native, inputs, frame_counter, play_sfx)
        elif self.state == "detached":
            self._update_detached(player_native, inputs, frame_counter,
                                  collision_codes, terrain_address,
                                  terrain_cell, replace_terrain, play_sfx)
        else:
            self._update_return(player_native, history_native, inputs,
                                frame_counter, collision_codes,
                                terrain_address, terrain_cell,
                                replace_terrain, scroll_delta, play_sfx,
                                background_address, background_cell)

    def _update_return(self, player: tuple[int, int],
                       history: tuple[tuple[int, int], ...],
                       inputs: ForceInput, frame: int,
                       collision_codes: Callable[[int, int], tuple[int, int]],
                       terrain_address: Callable[[int, int], int] | None,
                       terrain_cell: Callable[[int], tuple[int, int]] | None,
                       replace_terrain: Callable[[int, int, int], None] | None,
                       scroll_delta: int,
                       play_sfx: Callable[[int], None],
                       background_address: Callable[[int, int], int] | None,
                       background_cell: Callable[[int], tuple[int, int]] | None
                       ) -> None:
        # `$24D8..$24E1`: retain the complete previous integer/fractional X.
        self.old_x_q8 = self.x_q8
        if self.velocity_y:
            self.last_vertical = self.velocity_y
        if inputs.action_edge:
            self.return_history = True

        delayed_x, delayed_y = history[0] if history else player
        if self.return_history:
            target_x = delayed_x
        else:
            target_x = 0x01A0 if player[0] >= 0x01F8 else 0x0238
        self._horizontal_return(target_x, collision_codes, scroll_delta)
        self._vertical_return(
            delayed_y, target_x, collision_codes,
            terrain_address, terrain_cell,
            background_address, background_cell)
        self._clear_force_blocks(terrain_address, terrain_cell, replace_terrain)
        self.descriptor = self._return_descriptor(frame)

        half = _signed_word(self.rom.word(FORCE_HITBOX_POINTERS[self.level]))
        if (abs(self.x - player[0]) <= half + 8 and
                abs(self.y - player[1]) <= half + 6):
            # `$253F..$2564`: side is selected by unsigned Force.x-player.x.
            self.behind = self.x < player[0]
            self.attached = True
            self.state = "attached"
            play_sfx(0x37)                 # Команда звука ROM `$37`.

    def _update_attached(self, player: tuple[int, int], inputs: ForceInput,
                         frame: int, play_sfx: Callable[[int], None]) -> None:
        offset = -0x18 if self.behind else 0x18
        self.x_q8 = _u16(player[0] + offset) * Q8
        self.y_q8 = _u16(player[1]) * Q8
        self.descriptor = self._attached_descriptor(frame, inputs.direction)
        if not inputs.action_edge:
            return
        self.velocity_x = -0x0900 if self.behind else 0x0900
        self.return_history = False
        self.attached = False
        self.state = "detached"
        play_sfx(0x36)                     # Команда звука ROM `$36`.

    def _update_detached(self, player: tuple[int, int], inputs: ForceInput,
                         frame: int,
                         collision_codes: Callable[[int, int], tuple[int, int]],
                         terrain_address: Callable[[int, int], int] | None,
                         terrain_cell: Callable[[int], tuple[int, int]] | None,
                         replace_terrain: Callable[[int, int, int], None] | None,
                         play_sfx: Callable[[int], None]) -> None:
        del player, inputs, play_sfx
        self.x_q8 += self.velocity_x
        self._clear_force_blocks(terrain_address, terrain_cell, replace_terrain)
        # `$2632..$265D`: second X integration is only a terrain probe; the
        # saved position is restored before deciding whether return starts.
        probe_x = _u16((self.x_q8 + self.velocity_x) >> 8)
        fg, bg = collision_codes(probe_x, self.y)
        if not (fg >= 0x0DFC and bg >= 0x07D0 and
                0x0150 <= self.x < 0x02A0):
            self.state = "return"
        self.descriptor = self._detached_descriptor(frame)

    def _horizontal_return(self, target_x: int,
                           collision_codes: Callable[[int, int], tuple[int, int]],
                           scroll_delta: int) -> None:
        # `$2C94`: re-entry clamp, terrain probe, asymmetric Q8 steering.
        if self.x < 0x0120:
            self.x_q8 = 0x0128 * Q8
            self.y_q8 = 0x0100 * Q8
        fg, bg = collision_codes(_u16(self.x + 8), self.y)
        if fg < 0x0DFC or bg < 0x07D0:
            # `$2CE1..$2CE4` adds the signed *integer* native-pixel word
            # `$2ED0` to object `+$04`.  ``x_q8`` also carries the separate
            # ROM fraction byte, so scale that integer before combining it.
            self.x_q8 += _signed_word(scroll_delta) * Q8
            return
        delta = _signed_word(target_x - self.x)
        if delta == 0 or -2 <= delta < 2:
            return
        self.x_q8 += -0x0140 if delta < 0 else 0x0180

    def _vertical_return(
            self, target_y: int, target_x: int,
            collision_codes: Callable[[int, int], tuple[int, int]],
            terrain_address: Callable[[int, int], int] | None = None,
            terrain_cell: Callable[[int], tuple[int, int]] | None = None,
            background_address: Callable[[int, int], int] | None = None,
            background_cell: Callable[[int], tuple[int, int]] | None = None
            ) -> None:
        """Literal address-domain terrain avoidance from ROM `$2AB4`.

        `$2B0C…$2B4A` does not resample coordinates above and below Force.
        It walks the foreground/background VRAM address left by `$1EB5` in
        `$100`-byte row steps, including the first terminating empty cell in
        each byte counter.  That detail decides the sign at narrow edges.
        The coordinate fallback is retained only for isolated unit callers
        that do not provide tile-address accessors.
        """
        address_domain = all((terrain_address, terrain_cell,
                              background_address, background_cell))
        collision_layer = -1
        collision_x = self.x
        collision_address = 0
        # `$2ABD..$2AF8`: nine probes x-8,x,...,x+56.  Foreground wins,
        # then background, then the two adjacent foreground rows.
        for step in range(9):
            probe_x = _u16(self.x - 8 + step * 8)
            fg, bg = collision_codes(probe_x, self.y)
            foreground_address = (
                terrain_address(probe_x, self.y)
                if address_domain and terrain_address is not None else 0)
            if fg < 0x0DFC:
                collision_layer, collision_x = 0, probe_x
                collision_address = foreground_address
                break
            if bg < 0x07D0:
                collision_layer, collision_x = 1, probe_x
                collision_address = (
                    background_address(probe_x, self.y)
                    if background_address is not None else 0)
                break
            if address_domain and terrain_cell is not None:
                adjacent = (
                    terrain_cell((foreground_address + 0x100) & 0x3FFF)[0]
                    & 0x0FFF,
                    terrain_cell((foreground_address - 0x100) & 0x3FFF)[0]
                    & 0x0FFF,
                )
                adjacent_collision = any(code < 0x0DFC for code in adjacent)
            else:
                adjacent_collision = (
                    collision_codes(probe_x, _u16(self.y - 8))[0] < 0x0DFC or
                    collision_codes(probe_x, _u16(self.y + 8))[0] < 0x0DFC)
            if adjacent_collision:
                collision_layer, collision_x = 0, probe_x
                collision_address = foreground_address
                break

        if collision_layer >= 0:
            threshold = 0x0DFC if collision_layer == 0 else 0x07D0

            if address_domain:
                cell = terrain_cell if collision_layer == 0 else background_cell
                assert cell is not None
                low_count = 0
                high_count = 0
                edge = 0
                cursor = collision_address

                if collision_layer == 0:
                    while True:
                        cursor = (cursor - 0x100) & 0xFFFF
                        if cursor < 0x1000:
                            edge |= 0x01
                            break
                        low_count = (low_count + 1) & 0xFF
                        if (cell(cursor & 0x3FFF)[0] & 0x0FFF) >= threshold:
                            break

                    cursor = collision_address
                    while True:
                        cursor = (cursor + 0x100) & 0xFFFF
                        if cursor >= 0x2E00:
                            edge |= 0x10
                            break
                        high_count = (high_count + 1) & 0xFF
                        if (cell(cursor & 0x3FFF)[0] & 0x0FFF) >= threshold:
                            break

                    # Both address edges enter `$2B80`; with zero velocity
                    # that can still continue into the ordinary Y follower.
                    if edge != 0x11:
                        if edge:
                            self.velocity_y = (-0x0200 if edge & 1
                                               else 0x0200)
                        else:
                            self.velocity_y = (0x0200
                                               if low_count < high_count
                                               else -0x0200)
                        self.last_vertical = self.velocity_y
                        self.y_q8 += self.velocity_y
                        self._clamp_y()
                        return
                else:
                    # `$2BEF…$2C29`: background rows have no foreground
                    # playfield-edge guards.  Real maps always terminate;
                    # 256 is the exact byte-counter period and prevents a
                    # corrupt test map from hanging the host process.
                    cursor = collision_address
                    for _ in range(256):
                        cursor = (cursor - 0x100) & 0xFFFF
                        low_count = (low_count + 1) & 0xFF
                        if (cell(cursor & 0x3FFF)[0] & 0x0FFF) >= threshold:
                            break
                    cursor = collision_address
                    for _ in range(256):
                        cursor = (cursor + 0x100) & 0xFFFF
                        high_count = (high_count + 1) & 0xFF
                        if (cell(cursor & 0x3FFF)[0] & 0x0FFF) >= threshold:
                            break
                    self.velocity_y = (0x0200 if low_count < high_count
                                       else -0x0200)
                    self.last_vertical = self.velocity_y
                    self.y_q8 += self.velocity_y
                    self._clamp_y()
                    return

            else:
                # Compatibility path for unit callers without raw VRAM.
                # Production gameplay always takes the address-domain path.
                def solid(native_y: int) -> bool:
                    codes = collision_codes(collision_x, _u16(native_y))
                    return codes[collision_layer] < threshold

                above = 0
                sample_y = self.y + 8
                while sample_y <= 0x017F and solid(sample_y) and above < 48:
                    above += 1
                    sample_y += 8
                top_edge = sample_y > 0x017F
                below = 0
                sample_y = self.y - 8
                while sample_y >= 0x0080 and solid(sample_y) and below < 48:
                    below += 1
                    sample_y -= 8
                bottom_edge = sample_y < 0x0080
                if not (top_edge and bottom_edge):
                    if top_edge:
                        self.velocity_y = -0x0200
                    elif bottom_edge:
                        self.velocity_y = 0x0200
                    else:
                        self.velocity_y = (0x0200 if above < below
                                           else -0x0200)
                    self.last_vertical = self.velocity_y
                    self.y_q8 += self.velocity_y
                    self._clamp_y()
                    return

        # `$2B80..$2B97`: an avoidance velocity is cancelled as soon as its
        # opposite-side probe reaches empty space; integration occurred in the
        # collision branch above, exactly as in the ROM.
        if self.velocity_y:
            probe_y = _u16(self.y + (8 if self.velocity_y < 0 else -8))
            fg, bg = collision_codes(self.x, probe_y)
            if fg >= 0x0DFC and bg >= 0x07D0:
                self.velocity_y = 0
            self._clamp_y()
            return

        # `$2B9A..$2BD2`: Y history is followed only after X reached its
        # eight-native-pixel target window, unless `$24F5` latched return mode.
        within_target = 0 <= _signed_word(self.x + 4 - target_x) < 8
        if self.return_history or within_target:
            delta = _signed_word(target_y - self.y)
            if delta <= -3:
                self.velocity_y = -0x0200
            elif delta >= 3:
                self.velocity_y = 0x0200
            if self.velocity_y:
                self.last_vertical = self.velocity_y
                self.y_q8 += self.velocity_y
        self._clamp_y()

    def _clamp_y(self) -> None:
        self.y_q8 = min(max(self.y_q8, 0x0098 * Q8), 0x0178 * Q8)

    def _clear_force_blocks(self,
                            terrain_address: Callable[[int, int], int] | None,
                            terrain_cell: Callable[[int], tuple[int, int]] | None,
                            replace_terrain: Callable[[int, int, int], None] | None
                            ) -> None:
        """ROM `$2702/$2736`: erase four `$09F6` cells around Force."""
        if self.x < 0x0140 or not (terrain_address and terrain_cell and
                                  replace_terrain):
            return
        address = terrain_address(_u16(self.x + 4), _u16(self.y + 4))
        for offset in (0, 4, 0x104, 0x100):
            cell_address = (address + offset) & 0x3FFF
            code, _attribute = terrain_cell(cell_address)
            if code & 0x0FFF == 0x09F6:
                replace_terrain(cell_address, 0x0FA0, 0)

    def _return_descriptor(self, frame: int) -> int:
        if self.level == 1:
            if self.last_vertical and frame & 3 == 0:
                self.animation = (self.animation +
                                  (-1 if self.last_vertical < 0 else 1)) % 6
            return self.rom.word(0x144C + 2 * self.animation)
        if self.level == 2:
            if frame & 3 == 0:
                self.animation = (self.animation + 1) % 6
            base = (0x1458 if self.last_vertical < 0 else 0x1464)
            if not self.behind:
                base += 0x18
            return self.rom.word(base + 2 * self.animation)

        direction = 0
        if self.x_q8 != self.old_x_q8:
            direction |= 1 if self.x_q8 > self.old_x_q8 else 2
        if self.last_vertical:
            direction |= 8 if self.last_vertical >= 0 else 4
        if direction == 0:
            self.animation = 0
        self.animation_group = self.rom.byte(0x15AE + direction)
        if frame & 7 == 0:
            self.animation = (self.animation + 1) & 3
        table = self.rom.word(0x1488 + 2 * self.animation_group)
        return self.rom.word(table + 2 * self.animation)

    def _attached_descriptor(self, frame: int, direction: int) -> int:
        direction &= 0x0F
        if self.level == 3:
            group = self.rom.byte(0x15AE + direction)
            if frame & 7 == 0:
                self.animation = (self.animation + 1) & 3
            table = self.rom.word(0x1488 + 2 * group)
            return self.rom.word(table + 2 * self.animation)

        if frame & 3 == 0:
            delta = self.rom.byte(0x159E + direction)
            delta = delta - 0x100 if delta & 0x80 else delta
            self.animation = (self.animation + delta) % 6
        if self.level == 2:
            base = 0x1458 if self.behind else 0x1470
            return self.rom.word(base + 2 * self.animation)
        return self.rom.word(0x1440 + 2 * self.animation)

    def _detached_descriptor(self, frame: int) -> int:
        if self.level == 3:
            if frame & 1 == 0:
                self.animation = (self.animation + 1) & 3
            base = 0x149A + (8 if self.velocity_x < 0 else 0)
            return self.rom.word(base + 2 * self.animation)
        if frame & 1 == 0:
            self.animation = (self.animation + 1) % 6
        if self.level == 2:
            base = 0x1458 if self.behind else 0x1470
            return self.rom.word(base + 2 * self.animation)
        return self.rom.word(0x144C + 2 * self.animation)

    def draw(self, target: pygame.Surface, atlas: M72SpriteAtlas) -> None:
        if self.visible:
            atlas.draw(target, read_descriptor(self.rom, self.descriptor),
                       self.resource_slot, FORCE_RESOURCE_TYPE, self.x, self.y)
        for projectile in self.projectiles.values():
            atlas.draw(target, read_descriptor(self.rom, projectile.descriptor),
                       projectile.resource_slot, 0x02,
                       projectile.x, projectile.y)
        for segment in self.ray_segments.values():
            if segment.resource_slot != 0xFF and segment.descriptor != 0x26FE:
                atlas.draw(target, read_descriptor(self.rom, segment.descriptor),
                           segment.resource_slot, 0x3D,
                           segment.x, segment.y)
        for segment in self.grid_segments.values():
            if segment.resource_slot != 0xFF and segment.descriptor != 0x26FE:
                atlas.draw(target, read_descriptor(self.rom, segment.descriptor),
                           segment.resource_slot, 0x3D,
                           segment.x, segment.y)
        for beam in self.beams.values():
            if beam.resource_slot != 0xFF:
                for descriptor in beam.descriptors:
                    atlas.draw(target, read_descriptor(self.rom, descriptor),
                               beam.resource_slot, 0x3D, beam.x, beam.y)
        for dart in self.darts.values():
            if dart.resource_slot != 0xFF and dart.descriptor != 0x26FE:
                atlas.draw(target, read_descriptor(self.rom, dart.descriptor),
                           dart.resource_slot, 0x3D, dart.x, dart.y)

    def collision_rect(self) -> pygame.Rect:
        """Collision record written by `$38F4` from `ES:$15C6/$15CE/$15D6`."""
        left_native, right_native, lower_native, upper_native = (
            self.collision_bounds())
        logical_left = round((left_native - 0x0140) * 5 / 3)
        logical_right = round((right_native - 0x0140) * 5 / 3)
        logical_top = round((0x0180 - upper_native) * 15 / 8)
        logical_bottom = round((0x0180 - lower_native) * 15 / 8)
        return pygame.Rect(logical_left, logical_top,
                           logical_right - logical_left,
                           logical_bottom - logical_top)

    def collision_bounds(self) -> tuple[int, int, int, int]:
        """Native `$0078..$007E` endpoints consumed by enemy `$F493`."""
        pointer = FORCE_HITBOX_POINTERS[self.level]
        left_radius = self.rom.word(pointer)
        right_radius = self.rom.word(pointer + 2)
        lower_radius = self.rom.word(pointer + 4)
        upper_radius = self.rom.word(pointer + 6)
        return (self.x - left_radius, self.x + right_radius,
                self.y - lower_radius, self.y + upper_radius)

    def fire_unattached_matrix(self, weapon_type: int,
                               acquire: Callable[[int], int]) -> int:
        """Execute the 24 fixed wrappers and `$0099` latch for one fire event."""
        if not self.visible or self.attached:
            return 0
        latch = False
        spawned = 0
        weapon_type &= 6
        for slot in range(24):
            if slot in self.projectiles:
                # An active fixed record no longer executes its `$395A…` wrapper.
                continue
            base = 0x1B80 + slot * 0x30       # `$003F==0` front block
            callback = self.rom.word(base + 8 * (self.level - 1) + weapon_type)
            if callback in MATRIX_LATCH_CALLBACKS:
                latch = True
                continue
            setup = MATRIX_STRAIGHT_SETUPS.get(callback)
            if setup is None or not latch:
                continue
            latch = False
            velocity_x, velocity_y, descriptor = setup
            resource_slot = acquire(0x02)     # `$3EA7 → $51EE(AL=$02)`
            if resource_slot == 0xFF:
                continue
            self.projectiles[slot] = ForceProjectile(
                slot, self.x_q8, self.y_q8, velocity_x, velocity_y,
                descriptor, resource_slot)
            spawned += 1
        return spawned

    def fire_matrix(self, weapon_type: int,
                    acquire: Callable[[int], int],
                    shot_native: tuple[int, int] | None = None,
                    wave_native: tuple[int, int] | None = None) -> int:
        """Dispatch the same front/rear matrix selected by `$003F`."""
        if not self.attached:
            return self.fire_unattached_matrix(weapon_type, acquire)
        if (weapon_type & 6) == 0:
            return self._fire_attached_type0()
        if (weapon_type & 6) in (2, 4):
            return self._fire_attached_grid()
        if (weapon_type & 6) == 6:
            return self._fire_attached_type6(acquire, shot_native, wave_native)
        return 0

    def _fire_attached_type0(self) -> int:
        """Create the exact level-2/3 chains from callbacks `$3F28…$4293`."""
        spawned = 0
        length = 2 if self.level == 2 else (8 if self.level == 3 else 0)
        if not length:
            return 0
        link_pattern = (False, True, True, False, True, True, False, True)
        power_pattern = (2, 0, 0, 1, 0, 0, 1, 0)
        for group in range(3):
            first = group * 8
            # `$3F28/$4064/$41A0` scan all seven following active bytes.
            if (first in self.projectiles or first in self.ray_segments or
                    any(slot in self.ray_segments or slot in self.projectiles
                        for slot in range(first + 1, first + 8))):
                continue
            for index in range(length):
                slot = first + index
                if slot in self.ray_segments:
                    continue
                phase = 2 if group == 1 else 0
                self.ray_segments[slot] = ForceRaySegment(
                    slot, (self.x & 0xFFF8) + 4, (self.y & 0xFFF8) + 4,
                    1 + index * 2, phase, link_pattern[index],
                    power_pattern[index], group == 2)
                spawned += 1
        return spawned

    def _fire_attached_grid(self) -> int:
        """Create callbacks `$4591…$4744` for weapon types `$02/$04`."""
        length = 3 if self.level == 2 else (6 if self.level == 3 else 0)
        if not length:
            return 0
        spawned = 0
        anchor_x = (self.x & 0xFFF8) + 2
        anchor_y = (self.y & 0xFFF8) + 2
        delays = (1, 2, 4, 6, 8, 10)
        root_power = 2 if self.level == 2 else 4
        for first, direction, orientation in ((0, 0, 0), (8, 4, 2)):
            # Both root callbacks activate one complete contiguous chain.
            if any(slot in self.projectiles or slot in self.ray_segments or
                   slot in self.grid_segments
                   for slot in range(first, first + length)):
                continue
            for index in range(length):
                slot = first + index
                self.grid_segments[slot] = ForceGridSegment(
                    slot=slot, x=anchor_x, y=anchor_y,
                    delay=delays[index], direction=direction,
                    orientation=orientation + (4 if self.behind else 0),
                    linked=index != 0,
                    power=root_power if index == 0 else 0,
                    history_x1=anchor_x, history_y1=anchor_y,
                    history_x2=anchor_x, history_y2=anchor_y,
                )
                spawned += 1
        return spawned

    def _fire_attached_type6(
            self, acquire: Callable[[int], int],
            shot_native: tuple[int, int] | None,
            wave_native: tuple[int, int] | None) -> int:
        """Execute the fixed callbacks selected for matrix weapon type `$06`."""
        if self.level not in (2, 3):
            return 0
        spawned = 0
        step_x = -8 if self.behind else 8

        if self.level == 3:
            # `$4927`; `$4977` may use slot 8 only after slot 0 has left
            # `$49CF`, because it explicitly tests record `BP-$100`.
            beam_slot = None
            if 0 not in self.beams and not self._slot_used(0):
                beam_slot = 0
            elif (8 not in self.beams and not self._slot_used(8) and
                  self.beams.get(0) is not None and
                  self.beams[0].state != "expansion"):
                beam_slot = 8
            if beam_slot is not None:
                reverse = step_x < 0
                resource_slot = acquire(0x3D)
                if resource_slot == 0xFF:
                    beam_slot = None
                else:
                    self.beams[beam_slot] = ForceBeam(
                        slot=beam_slot, step_x=step_x,
                        expansion_base=0x241C if reverse else 0x21DC,
                        flight_base=0x259C if reverse else 0x235C,
                        expansion_hitbox=0x2664 if reverse else 0x265C,
                        flight_hitbox=0x2674 if reverse else 0x266C,
                        return_handler=0x3A96 if beam_slot == 8 else 0x395A,
                        resource_slot=resource_slot,
                    )
                    spawned += 1

        candidates: list[tuple[int, tuple[int, int] | None, int]] = [
            (1, shot_native, 0x267C),
            (2, wave_native, 0x2694),
        ]
        if self.level == 2:
            candidates.extend((
                (3, (_u16(self.x - 0x10), _u16(self.y + 8)), 0x267C),
                (4, (_u16(self.x - 0x10), _u16(self.y - 8)), 0x2694),
            ))
        for slot, source, descriptor in candidates:
            if source is None or self._slot_used(slot):
                continue
            self.darts[slot] = ForceDart(
                slot, source[0], source[1],
                descriptor + (0x0C if self.behind else 0), step_x)
            spawned += 1
        return spawned

    def _slot_used(self, slot: int) -> bool:
        return (slot in self.projectiles or slot in self.ray_segments or
                slot in self.grid_segments or slot in self.beams or
                slot in self.darts)

    @staticmethod
    def _ray_hitbox(segment: ForceRaySegment) -> pygame.Rect:
        # `ES:$210C`, consumed by `$4311/$44EE` when object `+$17 != 0`.
        left_radius = 12
        right_radius = 12
        lower_radius = 12
        upper_radius = 12
        left = round((segment.x - left_radius - 0x0140) * 5 / 3)
        right = round((segment.x + right_radius - 0x0140) * 5 / 3)
        top = round((0x0180 - (segment.y + upper_radius)) * 15 / 8)
        bottom = round((0x0180 - (segment.y - lower_radius)) * 15 / 8)
        return pygame.Rect(left, top, right - left, bottom - top)

    def update_ray_segments(
            self, scroll_delta: int,
            collision_codes: Callable[[int, int], tuple[int, int]],
            damage_at: Callable[[pygame.Rect, int], bool],
            acquire: Callable[[int], int], release: Callable[[int], None]
            ) -> None:
        """Execute `$42DD/$4311/$4467` and mirrored `$44BA/$44EE/$456A`."""
        active_at_start = {slot for slot, item in self.ray_segments.items()
                           if item.state == "active"}
        for slot, segment in tuple(self.ray_segments.items()):
            if segment.state == "terminal":
                segment.terminal_offset -= 6
                segment.descriptor = 0x20F4 + segment.terminal_offset
                if segment.terminal_offset == 0:
                    self._release_ray(slot, release)
                continue

            segment.x = _u16(segment.x + _signed_word(scroll_delta))
            if segment.state == "delay":
                segment.delay -= 1
                if segment.delay:
                    continue
                segment.resource_slot = acquire(0x3D)
                if segment.resource_slot == 0xFF:
                    del self.ray_segments[slot]
                    continue
                fg, bg = collision_codes(segment.x, segment.y)
                if fg < 0x0DFC or bg < 0x07D0:
                    self._release_ray(slot, release)
                    continue
                segment.state = "active"
                continue

            if segment.mirrored:
                self._update_mirrored_ray(segment, collision_codes)
            else:
                self._update_turning_ray(segment, collision_codes)

            if not (0x0120 <= segment.x < 0x02C0 and
                    0x0070 <= segment.y < 0x0190):
                self._release_ray(slot, release)
                continue
            segment.lifetime -= 1
            if segment.lifetime == 0:
                self._release_ray(slot, release)
                continue
            if segment.linked and (slot - 1) not in active_at_start:
                self._release_ray(slot, release)
                continue
            if segment.power and damage_at(self._ray_hitbox(segment),
                                           segment.power):
                # `$F560` clears collision record `+$01 == object+$17`.
                segment.power = 0
            if segment.power == 0 and not segment.linked:
                segment.state = "terminal"

    def _update_turning_ray(
            self, segment: ForceRaySegment,
            collision_codes: Callable[[int, int], tuple[int, int]]) -> None:
        phase = segment.phase & 6
        vector = 0x2086 + phase * 2
        segment.x = _u16(segment.x + _signed_word(self.rom.word(vector)))
        segment.y = _u16(segment.y + _signed_word(self.rom.word(vector + 2)))
        fg, bg = collision_codes(segment.x, segment.y)
        if segment.x >= 0x02C0 or (fg >= 0x0DFC and bg >= 0x07D0):
            segment.descriptor = self.rom.word(0x209A + phase)
            return

        record = 0x2056 + phase * 6
        first_dx = _signed_word(self.rom.word(record))
        first_dy = _signed_word(self.rom.word(record + 2))
        second_dx = _signed_word(self.rom.word(record + 6))
        second_dy = _signed_word(self.rom.word(record + 8))
        first_codes = collision_codes(_u16(segment.x + first_dx),
                                      _u16(segment.y + first_dy))
        if first_codes[0] >= 0x0DFC and first_codes[1] >= 0x07D0:
            segment.x = _u16(segment.x + first_dx)
            segment.y = _u16(segment.y + first_dy)
            segment.phase = (phase + 2) & 7
            segment.descriptor = self.rom.word(record + 4)
            return
        second_codes = collision_codes(_u16(segment.x + second_dx),
                                       _u16(segment.y + second_dy))
        if second_codes[0] >= 0x0DFC and second_codes[1] >= 0x07D0:
            segment.x = _u16(segment.x + second_dx)
            segment.y = _u16(segment.y + second_dy)
            segment.phase = (phase + 6) & 7
            segment.descriptor = self.rom.word(record + 10)
            return
        segment.x = _u16(segment.x + first_dx + second_dx)
        segment.y = _u16(segment.y + first_dy + second_dy)
        segment.phase = (phase + 4) & 7
        segment.descriptor = self.rom.word(0x209A + segment.phase)

    def _update_mirrored_ray(
            self, segment: ForceRaySegment,
            collision_codes: Callable[[int, int], tuple[int, int]]) -> None:
        phase = segment.phase & 2
        segment.x = _u16(segment.x + _signed_word(
            self.rom.word(0x2096 + phase)))
        fg, bg = collision_codes(segment.x, segment.y)
        if fg < 0x0DFC or bg < 0x07D0:
            segment.phase ^= 2
        segment.descriptor = self.rom.word(0x20A2 + segment.phase)

    def _release_ray(self, slot: int,
                     release: Callable[[int], None]) -> None:
        segment = self.ray_segments.pop(slot, None)
        if segment is not None:
            release(segment.resource_slot)

    @staticmethod
    def _grid_hitbox(segment: ForceGridSegment) -> pygame.Rect:
        # `ES:$21D4=(12,12,12,12)`, installed by `$48E8→$38F4`.
        left = round((segment.x - 12 - 0x0140) * 5 / 3)
        right = round((segment.x + 12 - 0x0140) * 5 / 3)
        top = round((0x0180 - (segment.y + 12)) * 15 / 8)
        bottom = round((0x0180 - (segment.y - 12)) * 15 / 8)
        return pygame.Rect(left, top, right - left, bottom - top)

    def update_grid_segments(
            self, frame_counter: int, scroll_x_delta: int,
            scroll_y_delta: int,
            collision_codes: Callable[[int, int], tuple[int, int]],
            damage_at: Callable[[pygame.Rect, int], bool],
            acquire: Callable[[int], int], release: Callable[[int], None]
            ) -> None:
        """Execute `$479B/$47C9/$4900` for attached types `$02/$04`."""
        active_at_start = {slot for slot, item in self.grid_segments.items()
                           if item.state == "active"}
        terminal_at_start = {slot for slot, item in self.grid_segments.items()
                             if item.state == "terminal"}
        for slot, segment in tuple(self.grid_segments.items()):
            if segment.state == "terminal":
                segment.terminal_offset -= 6
                segment.descriptor = 0x21BC + segment.terminal_offset
                if segment.terminal_offset == 0:
                    self._release_grid(slot, release)
                continue

            if segment.state == "delay":
                segment.delay -= 1
                if segment.delay:
                    continue
                segment.resource_slot = acquire(0x3D)
                if segment.resource_slot == 0xFF:
                    del self.grid_segments[slot]
                    continue
                segment.lifetime = 0x70
                fg, bg = collision_codes(segment.x, segment.y)
                if fg < 0x0DFC or bg < 0x07D0:
                    self._release_grid(slot, release)
                    continue
                segment.state = "active"
                continue

            if segment.linked:
                # `$47CF…$47F2`: two local history pairs followed by the
                # previous fixed record's current (+4,+8) coordinate.
                segment.x, segment.y = segment.history_x1, segment.history_y1
                segment.history_x1 = segment.history_x2
                segment.history_y1 = segment.history_y2
                previous = self.grid_segments.get(slot - 1)
                if previous is not None:
                    segment.history_x2, segment.history_y2 = previous.x, previous.y
                descriptor_base = 0x21A4
            else:
                self._move_grid_root(segment, scroll_x_delta,
                                     scroll_y_delta, collision_codes)
                descriptor_base = 0x218C

            animation_offset = frame_counter & 6
            # `$48B3`: JP keeps AX for even parity of `(object_index & 7)`.
            if (slot & 7).bit_count() & 1:
                animation_offset = (-animation_offset) & 6
            segment.descriptor = descriptor_base + animation_offset * 3

            if not (0x0120 <= segment.x < 0x02C0 and
                    0x0070 <= segment.y < 0x0190):
                self._release_grid(slot, release)
                continue
            segment.lifetime -= 1
            if segment.lifetime == 0:
                segment.state = "terminal"
                continue

            if segment.linked:
                previous_slot = slot - 1
                if previous_slot in terminal_at_start:
                    segment.state = "terminal"
                elif previous_slot not in active_at_start:
                    self._release_grid(slot, release)
                continue

            if segment.power and damage_at(self._grid_hitbox(segment),
                                           segment.power):
                segment.power = 0
            if segment.power == 0:
                segment.state = "terminal"

    def _move_grid_root(
            self, segment: ForceGridSegment, scroll_x_delta: int,
            scroll_y_delta: int,
            collision_codes: Callable[[int, int], tuple[int, int]]) -> None:
        segment.x = _u16(segment.x + _signed_word(scroll_x_delta))
        segment.y = _u16(segment.y + _signed_word(scroll_y_delta))

        direction = segment.direction & 6
        vector = 0x2114 + direction * 2
        dx = _signed_word(self.rom.word(vector))
        dy = _signed_word(self.rom.word(vector + 2))
        segment.x = _u16(segment.x + dx)
        segment.y = _u16(segment.y + dy)
        fg, bg = collision_codes(segment.x, segment.y)
        if fg < 0x0DFC or bg < 0x07D0:
            segment.x = _u16(segment.x - dx)
            segment.y = _u16(segment.y - dy)
            turn = self.rom.word(0x2124 + (segment.orientation & 6))
            segment.direction = (direction + turn) & 6

        # `$4854…$48A1`: one of 16 orientation/direction probes may
        # replace the direction only when the probed tile is empty.
        direction = segment.direction & 6
        probe = 0x212C + (segment.orientation & 6) * 12 + direction * 3
        probe_x = _u16(segment.x + _signed_word(self.rom.word(probe)))
        probe_y = _u16(segment.y + _signed_word(self.rom.word(probe + 2)))
        result_direction = self.rom.word(probe + 4) & 6
        fg, bg = collision_codes(probe_x, probe_y)
        if fg >= 0x0DFC and bg >= 0x07D0:
            segment.direction = result_direction

    def _release_grid(self, slot: int,
                      release: Callable[[int], None]) -> None:
        segment = self.grid_segments.pop(slot, None)
        if segment is not None:
            release(segment.resource_slot)

    @staticmethod
    def _native_hitbox(x: int, y: int, radii: tuple[int, int, int, int]
                       ) -> pygame.Rect:
        left_radius, right_radius, lower_radius, upper_radius = radii
        left = round((x - left_radius - 0x0140) * 5 / 3)
        right = round((x + right_radius - 0x0140) * 5 / 3)
        top = round((0x0180 - (y + upper_radius)) * 15 / 8)
        bottom = round((0x0180 - (y - lower_radius)) * 15 / 8)
        return pygame.Rect(left, top, right - left, bottom - top)

    def update_type6(
            self, frame_counter: int,
            collision_codes: Callable[[int, int], tuple[int, int]],
            damage_at: Callable[[pygame.Rect, int], bool],
            acquire: Callable[[int], int], release: Callable[[int], None],
            terrain_address: Callable[[int, int], int] | None = None,
            terrain_cell: Callable[[int], tuple[int, int]] | None = None,
            replace_terrain: Callable[[int, int, int], None] | None = None
            ) -> None:
        """Execute composite `$49CF/$4C6A` and dart `$4E0F/$4E42`."""
        for slot, beam in tuple(self.beams.items()):
            if beam.resource_slot == 0xFF:
                beam.resource_slot = acquire(0x3D)
                if beam.resource_slot == 0xFF:
                    del self.beams[slot]
                    continue
            if beam.state == "expansion":
                beam.x = _u16(self.x + (0x50 if beam.step_x > 0 else -0x50))
                beam.y = self.y
                base = beam.expansion_base + (beam.frame & 0x0F) * 24
                beam.descriptors = tuple(base + part * 6 for part in range(4))
                radii = tuple(_signed_word(self.rom.word(
                    beam.expansion_hitbox + index * 2)) for index in range(4))
                if beam.power and damage_at(
                        self._native_hitbox(beam.x, beam.y, radii), beam.power):
                    beam.power = 0
                if beam.frame == 0:
                    self._clear_beam_opening(
                        beam, terrain_address, terrain_cell, replace_terrain)
                obstructed = self._beam_strip_obstructed(beam, collision_codes)
                if beam.frame >= 7 and obstructed:
                    self._release_beam(slot, release)
                    continue
                beam.frame += 1
                if beam.frame == 0x10:
                    beam.state = "flight"
                    beam.frame = 0
                    beam.x = _u16(beam.x + (0x10 if beam.step_x > 0 else -0x10))
                continue

            beam.x = _u16(beam.x + beam.step_x)
            base = beam.flight_base + (beam.frame & 7) * 24
            beam.descriptors = tuple(base + part * 6 for part in range(4))
            beam.frame = _u16(beam.frame + 1)
            radii = tuple(_signed_word(self.rom.word(
                beam.flight_hitbox + index * 2)) for index in range(4))
            hit = beam.power and damage_at(
                self._native_hitbox(beam.x, beam.y, radii), beam.power)
            self._clear_09f6_around(
                beam.x, beam.y, terrain_address, terrain_cell, replace_terrain)
            fg, bg = collision_codes(beam.x, beam.y)
            outside = not (0x0120 <= beam.x < 0x02C0 and
                           0x0070 <= beam.y < 0x0190)
            if hit or beam.power == 0 or fg < 0x0DFC or bg < 0x07D0 or outside:
                self._release_beam(slot, release)

        for slot, dart in tuple(self.darts.items()):
            if dart.state == "terminal":
                dart.terminal_offset -= 6
                dart.descriptor = 0x26AC + dart.terminal_offset
                if dart.terminal_offset == 0:
                    self._release_dart(slot, release)
                continue
            if dart.state == "init":
                dart.resource_slot = acquire(0x3D)
                if dart.resource_slot == 0xFF:
                    del self.darts[slot]
                    continue
                dart.state = "active"
            dart.x = _u16(dart.x + dart.step_x)
            dart.descriptor = dart.descriptor_base + ((frame_counter & 4) * 3 // 2)
            hitbox = self._native_hitbox(dart.x, dart.y, (16, 16, 8, 8))
            hit = dart.power and damage_at(hitbox, dart.power)
            self._clear_09f6_cell(
                dart.x, dart.y, terrain_address, terrain_cell, replace_terrain)
            fg, bg = collision_codes(dart.x, dart.y)
            outside = not (0x0120 <= dart.x < 0x02C0 and
                           0x0070 <= dart.y < 0x0190)
            if hit or dart.power == 0 or fg < 0x0DFC or bg < 0x07D0 or outside:
                dart.state = "terminal"

    def _beam_strip_obstructed(
            self, beam: ForceBeam,
            collision_codes: Callable[[int, int], tuple[int, int]]) -> bool:
        sign = 1 if beam.step_x > 0 else -1
        start = beam.x - sign * 0x48
        for index in range(11):
            fg, bg = collision_codes(_u16(start + sign * index * 8), beam.y)
            if fg < 0x0DFC or bg < 0x07D0:
                return True
        return False

    def _clear_beam_opening(
            self, beam: ForceBeam,
            terrain_address: Callable[[int, int], int] | None,
            terrain_cell: Callable[[int], tuple[int, int]] | None,
            replace_terrain: Callable[[int, int, int], None] | None) -> None:
        sign = 1 if beam.step_x > 0 else -1
        offsets = ((-72, -12), (-72, 0), (-72, 12), (-60, 12),
                   (-60, 0), (-60, -12), (-48, 0), (-34, 0),
                   (-20, 0), (-6, 0), (8, 0))
        for dx, dy in offsets:
            self._clear_09f6_around(
                _u16(beam.x + sign * dx), _u16(beam.y + dy),
                terrain_address, terrain_cell, replace_terrain)

    @staticmethod
    def _clear_09f6_cell(
            x: int, y: int,
            terrain_address: Callable[[int, int], int] | None,
            terrain_cell: Callable[[int], tuple[int, int]] | None,
            replace_terrain: Callable[[int, int, int], None] | None) -> None:
        if x < 0x0140 or not (terrain_address and terrain_cell and
                              replace_terrain):
            return
        address = terrain_address(_u16(x - 4), _u16(y + 4))
        for offset in (0, 4, 0x104, 0x100):
            cell_address = (address + offset) & 0x3FFF
            code, _attribute = terrain_cell(cell_address)
            if code & 0x0FFF == 0x09F6:
                replace_terrain(cell_address, 0x0FA0, 0)

    def _clear_09f6_around(
            self, x: int, y: int,
            terrain_address: Callable[[int, int], int] | None,
            terrain_cell: Callable[[int], tuple[int, int]] | None,
            replace_terrain: Callable[[int, int, int], None] | None) -> None:
        for dx, dy in ((8, 8), (-8, 8), (-8, -8), (8, -8)):
            self._clear_09f6_cell(
                _u16(x + dx), _u16(y + dy),
                terrain_address, terrain_cell, replace_terrain)

    def _release_beam(self, slot: int,
                      release: Callable[[int], None]) -> None:
        beam = self.beams.pop(slot, None)
        if beam is not None:
            release(beam.resource_slot)

    def _release_dart(self, slot: int,
                      release: Callable[[int], None]) -> None:
        dart = self.darts.pop(slot, None)
        if dart is not None:
            release(dart.resource_slot)

    def update_projectiles(
            self, collision_codes: Callable[[int, int], tuple[int, int]],
            damage_at: Callable[[pygame.Rect, int], bool],
            release: Callable[[int], None],
            terrain_address: Callable[[int, int], int] | None = None,
            terrain_cell: Callable[[int], tuple[int, int]] | None = None,
            replace_terrain: Callable[[int, int, int], None] | None = None
            ) -> None:
        """Common `$3EC4` flight, terrain `$4FB9`, bounds and hit record."""
        for slot, projectile in tuple(self.projectiles.items()):
            projectile.x_q8 += projectile.velocity_x
            projectile.y_q8 += projectile.velocity_y
            fg, bg = collision_codes(projectile.x, projectile.y)
            if fg == 0x09F6 and terrain_address and terrain_cell and replace_terrain:
                address = terrain_address(projectile.x, projectile.y)
                code, _attribute = terrain_cell(address)
                if code & 0x0FFF == 0x09F6:
                    replace_terrain(address, 0x0FA0, 0)
                    fg = 0x0FA0
            outside = not (0x0130 <= projectile.x < 0x02C0 and
                           0x0078 <= projectile.y < 0x0188)
            hit = damage_at(projectile.collision_rect(), 1)
            if fg < 0x0DFC or bg < 0x07D0 or outside or hit:
                projectile.alive = False
                release(projectile.resource_slot)
                del self.projectiles[slot]
