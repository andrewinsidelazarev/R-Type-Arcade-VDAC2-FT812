"""ROM-driven stage event and enemy objects for the standalone port.

The module reads immutable tables from the verified R-Type World main-CPU
region.  MAME captures are test oracles only and are never runtime inputs.
"""
from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from .title import _argb4444_surface


ROOT = Path(__file__).resolve().parents[3]
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
FULL_HQ = ROOT / "Assets" / "Converted" / "Arcade" / "FullHQ"
RESOURCE_HQ = ROOT / "Assets" / "Converted" / "Arcade" / "ResourceHQ"
ES_FILE_BASE = 0x10000
EVENT_FIRST = 0xB9B3
EVENT_LAST = 0xBC13
# Exact event-stream bounds discovered from the table following `$B92D`.
# Stage 1 normally enters the Python checkpoint after its five setup records;
# `full_event_stream=True` exposes those records for ROM-level verification.
STAGE_EVENT_RANGES: dict[int, tuple[int, int]] = {
    1: (0xB993, 0xBC13),
    2: (0xBC17, 0xBCBF),
    3: (0xBCC3, 0xBCFB),
    4: (0xBCFF, 0xBF2B),
    5: (0xBF2F, 0xC067),
    6: (0xC06B, 0xC253),
    7: (0xC257, 0xC517),
    8: (0xC51B, 0xC5DF),
}
DISPATCH_TABLE = 0xB92D
SPRITE_CELL_W = 27
SPRITE_CELL_H = 30
SPRITE_CELL_BYTES = SPRITE_CELL_W * SPRITE_CELL_H * 2
SCORE_INCREMENT_FIRST = 0x86E4
SCORE_INCREMENT_LAST = 0x8720
SCORE_BCD_MAX = bytes((0x99, 0x99, 0x99, 0x09))
# Слово DSW `$2F2B` текущей сборки (как у `p1_label_visible`).
DSW_OPTIONS = 0x0204
# Пороги призовых жизней с балансом полного runtime (`full_runtime.BONUS_LIFE_TABLES`)
# вместо таблиц World ROM: `$1292…$12A0` берёт `ES:$86CC`, при бите 3 DSW — `ES:$86B4`.
BONUS_LIFE_THRESHOLDS = ((25_000, 75_000, 125_000, 200_000, 300_000) if DSW_OPTIONS & 0x0008
                         else (50_000, 100_000, 175_000, 250_000, 350_000))

# Standalone gameplay begins at the exact state immediately before MAME
# VBlank 852.  `$03A6/$03EC` use a 96-entry FIFO of 64-byte records; neither
# allocation nor deletion clears the Q8 fraction bytes at `+$03/+$07`.
# These values are the literal DS snapshot after VBlank 851, not inferred
# object positions or frame-number suppressions.
STAGE1_CHECKPOINT_FREE_SLOTS = (
    0x12C0, 0x1300, 0x1340, 0x1380, 0x13C0, 0x1400, 0x1440, 0x1480,
    0x14C0, 0x1500, 0x1540, 0x1580, 0x15C0, 0x1600, 0x1640, 0x1680,
    0x16C0, 0x1700, 0x1740, 0x1780, 0x17C0, 0x1800, 0x1840, 0x1880,
    0x18C0, 0x1900, 0x1940, 0x1980, 0x19C0, 0x1A00, 0x1A40, 0x1A80,
    0x1AC0, 0x1B00, 0x1B40, 0x1B80, 0x1BC0, 0x1C00, 0x1C40, 0x1C80,
    0x1CC0, 0x1D00, 0x07C0, 0x0800, 0x0840, 0x0880, 0x08C0, 0x0900,
    0x0940, 0x0780, 0x0B00, 0x0740, 0x0AC0, 0x0700, 0x0A80, 0x06C0,
    0x0A40, 0x0680, 0x0A00, 0x0640, 0x09C0, 0x0600, 0x0980, 0x05C0,
    0x0BC0, 0x0B80,
)
STAGE1_CHECKPOINT_SLOT_RESIDUE = {
    0x0640: (0x80, 0x00), 0x0680: (0x80, 0x00),
    0x0700: (0xC0, 0x00), 0x0740: (0x80, 0x00),
    0x0E40: (0xC0, 0x00), 0x0EC0: (0x80, 0x00),
    0x0FC0: (0x40, 0x00), 0x1000: (0x80, 0x00),
    0x10C0: (0xC0, 0x00),
}
STAGE1_CHECKPOINT_PARTICLES = (
    (0x0D80, 0x0159, 0x00, 0x0148, 0x00, 0x05, 0xFD00, 0x8484),
    (0x0E00, 0x0241, 0x00, 0x0123, 0x00, 0x03, 0xFF00, 0x8478),
    (0x0E40, 0x01C8, 0xC0, 0x0154, 0x00, 0x04, 0xFDC0, 0x848A),
    (0x0E80, 0x018F, 0x00, 0x014A, 0x00, 0x04, 0xFD00, 0x848A),
    (0x0EC0, 0x0226, 0x80, 0x00D5, 0x00, 0x03, 0xFE80, 0x848A),
    (0x0F00, 0x0259, 0x00, 0x00B3, 0x00, 0x03, 0xFF00, 0x8472),
    (0x0F40, 0x01C5, 0x00, 0x0125, 0x00, 0x02, 0xFD00, 0x8472),
    (0x0F80, 0x01D7, 0x00, 0x0122, 0x00, 0x03, 0xFD00, 0x8472),
    (0x0FC0, 0x027B, 0x40, 0x016B, 0x00, 0x05, 0xFF40, 0x8484),
    (0x1000, 0x0253, 0x80, 0x0176, 0x00, 0x02, 0xFE80, 0x8472),
    (0x1040, 0x0277, 0x00, 0x0122, 0x00, 0x02, 0xFF00, 0x8472),
    (0x1080, 0x021F, 0x00, 0x0169, 0x00, 0x02, 0xFD00, 0x8472),
    (0x10C0, 0x024F, 0xC0, 0x00C9, 0x00, 0x03, 0xFDC0, 0x8478),
    (0x1100, 0x0289, 0x00, 0x012F, 0x00, 0x02, 0xFF00, 0x8472),
    (0x1140, 0x0255, 0x00, 0x00A8, 0x00, 0x03, 0xFD00, 0x8478),
    (0x1180, 0x0267, 0x00, 0x00DF, 0x00, 0x05, 0xFD00, 0x8484),
    (0x11C0, 0x0279, 0x00, 0x00E8, 0x00, 0x04, 0xFD00, 0x848A),
    (0x1200, 0x028B, 0x00, 0x00FE, 0x00, 0x02, 0xFD00, 0x8472),
    (0x1240, 0x029D, 0x00, 0x0175, 0x00, 0x03, 0xFD00, 0x848A),
)
STAGE1_CHECKPOINT_PALETTE_CYCLES = (
    (0x0B40, 0x000E, 0x0009, 0x0000, 0xFF3B, 0x0000, 0x001F, 0x0418),
    (0x0C40, 0x0009, 0x0019, 0x001A, 0x010A, 0x0001, 0x007F, 0x0C10),
    (0x0C80, 0x000A, 0x001B, 0x001C, 0x010B, 0x0000, 0x001F, 0x0418),
    (0x0CC0, 0x000B, 0x001D, 0x001E, 0x010C, 0x0000, 0x001F, 0x1424),
    (0x0D00, 0x000C, 0x0001, 0x0002, 0x010D, 0x0000, 0x003F, 0x1028),
    (0x0D40, 0x000D, 0x0003, 0x0003, 0x010E, 0x0000, 0x003F, 0x183C),
    (0x0DC0, 0x000E, 0x0005, 0x0005, 0x010F, 0x0000, 0x003F, 0x244C),
)


def _u16(value: int) -> int:
    return value & 0xFFFF


def _s8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def _signed_word(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class M72Rom:
    """Segment-aware access to the interleaved verified World ROM region."""

    def __init__(self) -> None:
        self.data = ROM_PATH.read_bytes()
        if len(self.data) != 0x100000:
            raise ValueError("неверный размер RTYPE_MAINCPU_REGION.bin")

    def byte(self, address: int) -> int:
        return self.data[ES_FILE_BASE + (address & 0xFFFF)]

    def word(self, address: int) -> int:
        return struct.unpack_from("<H", self.data,
                                  ES_FILE_BASE + (address & 0xFFFF))[0]


@dataclass(frozen=True)
class StageEvent:
    address: int
    threshold: int
    command: int
    handler: int


class M72Rng:
    """Three-byte generator initialized by ROM `$EDD9` and stepped by `$EDE9`."""

    def __init__(self, state: tuple[int, int, int] = (5, 1, 3)) -> None:
        self.a, self.b, self.c = (value & 0xFF for value in state)

    def reset(self) -> None:
        """Execute ROM `$EDD9`: restore the fixed `$03_01_05` seed."""
        self.a, self.b, self.c = 5, 1, 3

    def next(self) -> int:
        old_a, old_b, old_c = self.a, self.b, self.c
        self.a = (old_b + old_c) & 0xFF
        self.b = old_a
        self.c = old_b
        return self.a | (old_c << 8)


class M72ResourceManager:
    """Literal 16-entry acquire/release table from `$51EE/$523E`."""

    def __init__(self, stage1_checkpoint: bool = True) -> None:
        self.types = [0xFF] * 16
        self.refs = [0] * 16
        # State still alive at the Python entry checkpoint (VBlank 851).
        # Type $02 is the player; $09 and the four stage palettes were loaded
        # by the ROM events preceding EVENT_FIRST.
        if stage1_checkpoint:
            for resource_type in (0x02, 0x09, 0x57, 0x59, 0x5A, 0x5C):
                self.acquire(resource_type)

    def acquire(self, resource_type: int) -> int:
        free = -1
        for slot in range(15, -1, -1):
            if self.types[slot] == resource_type:
                self.refs[slot] = (self.refs[slot] + 1) & 0xFF
                return slot
            if self.types[slot] == 0xFF:
                free = slot
        if free < 0:
            return 0xFF
        self.types[free] = resource_type & 0xFF
        self.refs[free] = 1
        return free

    def release(self, slot: int) -> None:
        if slot == 0xFF or not 0 <= slot < 16 or self.refs[slot] == 0:
            return
        self.refs[slot] -= 1
        if self.refs[slot] == 0:
            self.types[slot] = 0xFF


class M72ObjectPool:
    """Literal 96-record FIFO allocator `$03A6/$03EC`."""

    SLOTS = tuple(range(0x0540, 0x1D40, 0x40))

    def __init__(self, stage1_checkpoint: bool) -> None:
        self.serial = 0
        if stage1_checkpoint:
            free = STAGE1_CHECKPOINT_FREE_SLOTS
            self.residue = {
                slot: STAGE1_CHECKPOINT_SLOT_RESIDUE.get(slot, (0, 0))
                for slot in self.SLOTS
            }
        else:
            # `$0540/$0580` are the permanent ordered-list sentinels.
            free = self.SLOTS[2:]
            self.residue = {slot: (0, 0) for slot in self.SLOTS}
        self.free: deque[int] = deque(free)
        self.allocated = set(self.SLOTS) - set(free)

    def take(self) -> int | None:
        if not self.free:
            return None
        slot = self.free.popleft()
        self.allocated.add(slot)
        return slot

    def bind(self, enemy: "Enemy", slot: int) -> None:
        enemy.object_slot = slot
        self.serial += 1
        enemy.scheduler_serial = self.serial
        x_fraction, y_fraction = self.residue[slot]
        if (enemy.inherit_slot_fractions and
                hasattr(enemy, "x_fraction")):
            enemy.x_fraction = x_fraction
        if (enemy.inherit_slot_fractions and
                hasattr(enemy, "y_fraction")):
            enemy.y_fraction = y_fraction

    def release(self, slot: int | None, owner: object | None = None) -> None:
        if slot is None or slot not in self.allocated:
            return
        old_x, old_y = self.residue[slot]
        x_fraction = getattr(owner, "x_fraction", old_x) & 0xFF
        y_fraction = getattr(owner, "y_fraction", old_y) & 0xFF
        self.residue[slot] = (x_fraction, y_fraction)
        self.allocated.remove(slot)
        self.free.append(slot)
        if owner is not None and hasattr(owner, "object_slot"):
            owner.object_slot = None


@dataclass
class ParticleControllerE4A5:
    """Live fields of the Stage particle controller `$E4A5`."""

    remaining: int
    slots: tuple[int, int, int, int]
    velocity_table: int
    cadence: int
    spawn_counter: int
    object_slot: int | None = None


@dataclass(frozen=True)
class SpriteDescriptor:
    dx: int
    dy: int
    code: int
    attr: int

    @property
    def width(self) -> int:
        return 1 << ((self.attr >> 14) & 3)

    @property
    def height(self) -> int:
        return 1 << ((self.attr >> 12) & 3)

    @property
    def flip_x(self) -> bool:
        return bool(self.attr & 0x0800)

    @property
    def flip_y(self) -> bool:
        return bool(self.attr & 0x0400)


class M72SpriteAtlas:
    """Lazy access to offline xBRZ+Lanczos sprite cells for all 16 palettes."""

    def __init__(self) -> None:
        self._banks: dict[tuple[int, int], bytes] = {}
        self._cells: dict[
            tuple[tuple[int, int], int, bool, bool], pygame.Surface
        ] = {}

    @staticmethod
    def _asset(palette: int, resource_type: int) -> tuple[tuple[int, int], Path]:
        """Resolve the immutable offline pixels behind one M72 palette slot.

        A typed Stage-1 bank already contains the palette belonging to the
        resource and is identical whichever of the sixteen live palette slots
        `$51EE` assigned to it.  Keying that data by the transient slot loaded
        the same multi-megabyte file again after palette reuse and caused
        visible frame stalls.  FullHQ fallback banks really are slot-specific.
        """
        palette &= 0x0F
        resource_type &= 0xFF
        typed = RESOURCE_HQ / (
            f"RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin")
        if typed.is_file():
            return (1, resource_type), typed
        return ((0, palette), FULL_HQ /
                f"RTYPE_SPRITES_PAL{palette:02X}_HQ_ARGB4444.bin")

    def cell(self, palette: int, resource_type: int, code: int, flip_x: bool,
             flip_y: bool) -> pygame.Surface:
        code &= 0x0FFF
        bank_key, path = self._asset(palette, resource_type)
        key = (bank_key, code, flip_x, flip_y)
        cached = self._cells.get(key)
        if cached is not None:
            return cached
        bank = self._banks.get(bank_key)
        if bank is None:
            bank = path.read_bytes()
            if len(bank) != 4096 * SPRITE_CELL_BYTES:
                raise ValueError(f"неверный полный sprite atlas: {path}")
            self._banks[bank_key] = bank
        offset = code * SPRITE_CELL_BYTES
        surface = _argb4444_surface(
            bank[offset:offset + SPRITE_CELL_BYTES],
            SPRITE_CELL_W, SPRITE_CELL_H)
        if flip_x or flip_y:
            surface = pygame.transform.flip(surface, flip_x, flip_y)
        self._cells[key] = surface
        return surface

    def preload_descriptor(self, rom: "M72Rom", address: int,
                           resource_type: int) -> None:
        """Convert every cell of a proven ROM descriptor before gameplay."""
        descriptor = read_descriptor(rom, address)
        for cell_x in range(descriptor.width):
            for cell_y in range(descriptor.height):
                source_x = (descriptor.width - 1 - cell_x
                            if descriptor.flip_x else cell_x)
                source_y = (descriptor.height - 1 - cell_y
                            if descriptor.flip_y else cell_y)
                code = descriptor.code + 8 * source_x + source_y
                # Typed assets do not depend on the transient palette slot;
                # slot zero is therefore sufficient for deterministic preload.
                self.cell(0, resource_type, code,
                          descriptor.flip_x, descriptor.flip_y)

    def preload_80e3(self, rom: "M72Rom") -> None:
        """Preconvert every `$80E3/$82D6/$8355` cell before Stage 1.

        Without this, the first normal composite and its first damage palette
        each crossed the 55 Hz frame budget, producing the two visible jerks
        near the first mini-boss.
        """
        body_pointers = {
            rom.word(table + offset)
            for table in (0x3866, 0x386E, 0x3876, 0x387E, 0x3886, 0x388E)
            for offset in (0, 2, 4, 6)
        }
        for address in body_pointers:
            for resource_type in (0x20, 0x55):
                self.preload_descriptor(rom, address, resource_type)
                self.preload_descriptor(rom, address + 6, resource_type)

        for root in (0x38F6, 0x390E):
            for offset in (0, 6, 12, 18):
                self.preload_descriptor(rom, root + offset, 0x09)
        for root in (0x3926, 0x3932, 0x393E, 0x394A):
            self.preload_descriptor(rom, root, 0x09)
            self.preload_descriptor(rom, root + 6, 0x09)

    def draw(self, target: pygame.Surface, descriptor: SpriteDescriptor,
             palette: int, resource_type: int,
             anchor_x: int, anchor_y: int) -> None:
        native_x = anchor_x + descriptor.dx - 320
        native_y = 384 - (anchor_y + descriptor.dy) - 16 * descriptor.height
        base_x = round(native_x * 5 / 3)
        base_y = round(native_y * 15 / 8)
        for cell_x in range(descriptor.width):
            for cell_y in range(descriptor.height):
                source_x = (descriptor.width - 1 - cell_x
                            if descriptor.flip_x else cell_x)
                source_y = (descriptor.height - 1 - cell_y
                            if descriptor.flip_y else cell_y)
                code = descriptor.code + 8 * source_x + source_y
                image = self.cell(palette, resource_type, code,
                                  descriptor.flip_x, descriptor.flip_y)
                x = base_x + round(cell_x * 16 * 5 / 3)
                y = base_y + cell_y * SPRITE_CELL_H
                target.blit(image, (x, y))


class ScriptedMotion:
    """State of the compressed movement interpreter at ROM `$F5C1`."""

    def __init__(self, rom: M72Rom, script: int, commands: int = 2) -> None:
        self.script = script
        self.pointer = rom.word(script)
        self.commands = commands
        self.phase = 0

    def update(self, rom: M72Rom, owner: "Enemy") -> bool:
        remaining = self.commands
        while remaining:
            value = rom.byte(self.pointer)
            if value & 0x80:
                self.phase = value & 0x1F
                # `$F603` jumps directly to `$F5EA`: bits 2..6 of a phase
                # command are data, not movement/end flags. INC CX cancels
                # the LOOP decrement, so it also does not consume a command.
                self.pointer = _u16(self.pointer + 1)
                continue
            if value & 0x40:
                if value & 0x20:
                    owner.x = _u16(owner.x - 1)
            elif value & 0x20:
                owner.x = _u16(owner.x + 1)
            if value & 0x10:
                if value & 0x08:
                    owner.y = _u16(owner.y - 1)
            elif value & 0x08:
                owner.y = _u16(owner.y + 1)
            if value & 0x04:
                while True:
                    self.script = _u16(self.script + 2)
                    word = rom.word(self.script)
                    if word == 0:
                        self.script = rom.word(self.script + 2)
                        self.pointer = rom.word(self.script)
                        return True
                    if word & 0xFF00 == 0xF000:
                        self.commands = word & 0xFF
                        continue
                    self.pointer = word
                    return False
            self.pointer = _u16(self.pointer + 1)
            remaining -= 1
        return False


@dataclass
class Enemy:
    kind: str
    x: int
    y: int
    palette: int
    descriptor: int
    hp: int = 1
    alive: bool = True
    # Event-created objects are linked after the current scheduler walk and
    # therefore first execute on the next pass.  The pending list already
    # supplies that one-pass delay; another countdown would add a false frame.
    start_delay: int = 0
    shootable: bool = True
    collision_table: int = 0
    hostile: bool = True
    # ROM handler installed after weapon destruction.  Natural removal at
    # bounds/script end leaves `destroyed` false and must not make a blast.
    death_effect: str | None = "e7be"
    destroyed: bool = False
    # One-hit `$F694` objects are destroyed by Force immediately.  Multi-hit
    # `$F6DA/$F75F` objects accept one Force point only each 16 VBlanks.
    force_damage_cadenced: bool | None = None
    # The common projectile `$E601` checks Force directly at `$E64E`, but it
    # is absent from the Wave/ordinary-shot scans used by enemy dispatchers.
    weapon_vulnerable: bool = True
    # `$E601` calls `$F578` once with `SI=$0076` (Force).  It does not call
    # `$F493`, whose three alternatives also include both Bits.
    force_collision_only: bool = False
    # Pointer into the sixteen packed-BCD increments at `ES:$86E4`.  A null
    # pointer is literal: projectiles, helper objects and natural cleanup do
    # not run the score task `$E8BD`.
    score_pointer: int | None = None
    # `$03A6` inserts objects into an ascending-priority scheduler.  This is
    # observable whenever two handlers consume the shared RNG in one VBlank.
    # Keep this distinct from object fields whose ROM payload itself is named
    # `priority` (notably `$78F8` and `$915B` linked chains).
    scheduler_priority: int = 0x8010
    object_slot: int | None = None
    scheduler_serial: int = 0
    inherit_slot_fractions: bool = False
    # Most handlers test global cleanup byte `$2FC4` themselves and release
    # immediately.  A small number first install a handler which deliberately
    # ignores that byte (Dobkeratops `$A107`, body death `$9D30`).  Those
    # records must remain schedulable after the root raises global cleanup.
    cleanup_passthrough: bool = False

    def __post_init__(self) -> None:
        if self.force_damage_cadenced is None:
            self.force_damage_cadenced = self.hp > 1

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        del world, foreground_delta

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        self.hp -= damage
        if self.hp <= 0:
            self.destroyed = True
            self.alive = False

    def hitbox(self, rom: M72Rom) -> pygame.Rect:
        if self.collision_table:
            left = _signed_word(rom.word(self.collision_table))
            right = _signed_word(rom.word(self.collision_table + 2))
            lower = _signed_word(rom.word(self.collision_table + 4))
            upper = _signed_word(rom.word(self.collision_table + 6))
            logical_left = round((self.x + left - 320) * 5 / 3)
            logical_right = round((self.x + right - 320) * 5 / 3)
            logical_top = round((384 - (self.y + upper)) * 15 / 8)
            logical_bottom = round((384 - (self.y + lower)) * 15 / 8)
            return pygame.Rect(logical_left, logical_top,
                               logical_right - logical_left,
                               logical_bottom - logical_top)
        desc = read_descriptor(rom, self.descriptor)
        x = round((self.x + desc.dx - 320) * 5 / 3)
        y = round((384 - (self.y + desc.dy) - 16 * desc.height) * 15 / 8)
        return pygame.Rect(x, y,
                           round(desc.width * 16 * 5 / 3),
                           desc.height * 30)

    def native_hitbox(self, rom: M72Rom) -> tuple[int, int, int, int]:
        """Exact `$F578` extent endpoints: left/right/lower/upper."""
        if self.collision_table:
            left = _signed_word(rom.word(self.collision_table))
            right = _signed_word(rom.word(self.collision_table + 2))
            lower = _signed_word(rom.word(self.collision_table + 4))
            upper = _signed_word(rom.word(self.collision_table + 6))
            return (self.x + left, self.x + right,
                    self.y + lower, self.y + upper)
        descriptor = read_descriptor(rom, self.descriptor)
        return (self.x + descriptor.dx,
                self.x + descriptor.dx + descriptor.width * 16,
                self.y + descriptor.dy,
                self.y + descriptor.dy + descriptor.height * 16)


def _f63a_trigger(source: Enemy) -> bool:
    """Advance the literal common enemy-fire counter `$F63A..$F650`.

    The equality branch at `$F643` jumps straight to projectile allocation and
    deliberately leaves `+$26` unchanged.  Only the upper-limit branch at
    `$F648/$F64B` clears the counter.  Keeping this in one routine prevents the
    two distinct ROM branches from being collapsed into a reset-on-every-shot
    approximation.
    """
    source.fire_counter = _u16(source.fire_counter + 1)
    if source.fire_counter == source.fire_a:
        return True
    if source.fire_counter >= source.fire_b:
        source.fire_counter = 0
        return True
    return False


def _run_f63a(world: "M72EnemyWorld", source: Enemy) -> None:
    """Run `$F63A` and create its common `$E601` projectile when requested."""
    if _f63a_trigger(source) and source.projectile_script:
        world.note_projectile_spawn(source)


class M72PendingList(list[Enemy]):
    """Objects linked after the current scheduler cursor by `$03A6`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        super().__init__()
        self.world = world

    def append(self, enemy: Enemy) -> None:
        if enemy.object_slot is None:
            slot = self.world.object_pool.take()
            if slot is None:
                self.world.allocation_failures.append(
                    (self.world.frame_counter, enemy.kind))
                return
            self.world.object_pool.bind(enemy, slot)
        super().append(enemy)
        # `$03A6` links the new record into the live priority list.  If its
        # priority is strictly after the handler currently being visited, the
        # scheduler reaches it later in this same pass.  Equal-priority records
        # are inserted before the current record (`JAE` at `$03CE`) and wait
        # until the next pass.  This distinction is visible for `$F63A`:
        # an `$8010` formation child creates an `$A000/$E601` projectile which
        # already performs its first Q8 step in the allocation VBlank.
        cursor = self.world._scheduler_cursor_priority
        if cursor is not None and enemy.scheduler_priority > cursor:
            enemy.update(self.world, self.world._scheduler_foreground_delta)


class BackgroundParticleE5CD(Enemy):
    """Literal two-state background particle `$E568/$E5CD`.

    Allocation installs `$E568`; that initializer runs on the following
    scheduler pass, consumes exactly three `$EDE9` values, and only then
    installs runtime handler `$E5CD`.  The first movement/render pass is one
    VBlank later still.
    """

    def __init__(self, velocity_table: int) -> None:
        super().__init__("background_particle_e5cd", 0, 0, 0xFF, 0,
                         scheduler_priority=0x0010)
        self.velocity_table = velocity_table
        self.x_velocity = 0
        self.x_fraction = 0
        self.y_fraction = 0
        self.initialized = False
        self.render_ready = False
        self.shootable = False
        self.hostile = False
        self.weapon_vulnerable = False
        self.death_effect = None
        self.inherit_slot_fractions = True

    @classmethod
    def from_stage1_checkpoint(
            cls, record: tuple[int, int, int, int, int, int, int, int]
            ) -> "BackgroundParticleE5CD":
        slot, x, x_fraction, y, y_fraction, palette, velocity, descriptor = record
        particle = cls(0x836C)
        particle.object_slot = slot
        particle.x = x
        particle.x_fraction = x_fraction
        particle.y = y
        particle.y_fraction = y_fraction
        particle.palette = palette
        particle.x_velocity = _signed_word(velocity)
        particle.descriptor = descriptor
        particle.initialized = True
        particle.render_ready = True
        return particle

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if not self.initialized:
            # `$E56D…$E57E`: low five bits choose one of 32 signed Q8
            # horizontal velocities from the controller-selected table.
            velocity_index = world.rng.next() & 0x1F
            self.x_velocity = _signed_word(world.rom.word(
                self.velocity_table + velocity_index * 2))

            # `$E581…$E59E`: a second independent low-five-bit choice reads
            # `(descriptor, resource type)` from `ES:$83AC`.
            sprite_index = world.rng.next() & 0x1F
            sprite_record = 0x83AC + sprite_index * 4
            self.descriptor = world.rom.word(sprite_record)
            resource_type = world.rom.word(sprite_record + 2) & 0xFF
            self.palette = world.resources.acquire(resource_type)

            # `$E5A1…$E5B7`: bits 1..5 select the Y-table word and bits
            # 0..2 add the exact 0..7 native-pixel jitter.
            vertical_random = world.rng.next()
            y_index = (vertical_random & 0x3E) >> 1
            self.y = _u16(world.rom.word(0x842C + y_index * 2) +
                          (vertical_random & 7))
            self.x = 0x013C if self.velocity_table == 0x832C else 0x02AC
            self.initialized = True
            return

        # `$E5D4/$0672`: signed Q8 X motion.  A freshly initialized particle
        # reaches this state only on its next scheduler pass.
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        self.render_ready = True

        # `$E5E0…$E5F7`: direction/table selects the unsigned exit edge.
        if self.velocity_table == 0x832C:
            if self.x >= 0x02C0:
                self.alive = False
        elif self.x < 0x0140:
            self.alive = False


class PaletteCycleFBED(Enemy):
    """Palette-cycle object allocated by event handler `$FB9C`.

    The sixteen records at `ES:$989C` are copied verbatim into object fields
    `+$20…+$2A`; `$FBE2` always consumes one RNG value for the four-times
    phase at `+$2C`.  Runtime `$FBED` submits the alternating palette request
    to `$54E4` until its record lifetime expires.
    """

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        record = 0x989C + (command & 0xFF) * 0x10
        super().__init__("palette_cycle_fbed", 0, 0, 0xFF, 0,
                         scheduler_priority=0xFF00)
        self.palette_index = world.rom.word(record)
        self.first_resource = world.rom.word(record + 2)
        self.second_resource = world.rom.word(record + 4)
        self.remaining = world.rom.word(record + 6)
        self.mode = world.rom.word(record + 8)
        self.mask = world.rom.word(record + 10)
        self.phase = _u16(world.rng.next() * 4)
        self.shootable = False
        self.hostile = False
        self.weapon_vulnerable = False
        self.death_effect = None

    @classmethod
    def from_stage1_checkpoint(
            cls, record: tuple[int, int, int, int, int, int, int, int]
            ) -> "PaletteCycleFBED":
        (slot, palette_index, first_resource, second_resource, remaining,
         mode, mask, phase) = record
        cycle = cls.__new__(cls)
        Enemy.__init__(cycle, "palette_cycle_fbed", 0, 0, 0xFF, 0,
                       shootable=False, hostile=False, death_effect=None,
                       weapon_vulnerable=False,
                       scheduler_priority=0xFF00, object_slot=slot)
        cycle.palette_index = palette_index
        cycle.first_resource = first_resource
        cycle.second_resource = second_resource
        cycle.remaining = remaining
        cycle.mode = mode
        cycle.mask = mask
        cycle.phase = phase
        return cycle

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.remaining = _u16(self.remaining - 1)
        if self.remaining == 0:
            self.alive = False
            return
        phase = _u16(world.frame_counter + self.phase)
        if self.mask & phase:
            return
        resource = (self.first_resource if not ((self.mask + 1) & phase)
                    else self.second_resource)
        world.palette_cycle_state[self.palette_index] = (resource, self.mode)


class CleanupTimerF477(Enemy):
    """Three-pass global object cleanup created by event `$F461`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        super().__init__("cleanup_timer_f477", 0, 0, 0xFF, 0,
                         shootable=False, hostile=False,
                         death_effect=None, weapon_vulnerable=False,
                         scheduler_priority=0x0100)
        self.timer = 3
        world.cleanup_active = True

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            world.cleanup_active = False
            self.alive = False


class InvulnerabilityTimerF44E(Enemy):
    """Literal `$F44E` 128-pass post-checkpoint invulnerability record."""

    def __init__(self, world: "M72EnemyWorld",
                 scheduler_priority: int = 0x0100) -> None:
        super().__init__(
            "invulnerability_timer_f44e", 0, 0, 0xFF, 0,
            shootable=False, hostile=False, death_effect=None,
            weapon_vulnerable=False, scheduler_priority=scheduler_priority)
        self.timer = 0x0080
        world.invulnerability_latch = True

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        world.invulnerability_latch = True
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            world.invulnerability_latch = False
            self.alive = False


class TimedControlF3C1(Enemy):
    """Delayed sound/control record allocated by event handler `$F366`.

    `$F3C1…$F3D7` owns no sprite or collision state.  It waits for the exact
    16-bit countdown stored at object `+$10`, unless global cleanup byte
    `$2FC4` becomes non-zero first, sends object word `+$12` through `$0303`,
    and returns its record through `$03EC`.
    """

    def __init__(self, timer: int, sound_command: int) -> None:
        super().__init__(
            "timed_control_f3c1", 0, 0, 0xFF, 0,
            shootable=False, hostile=False, death_effect=None,
            weapon_vulnerable=False, scheduler_priority=0x1000)
        self.timer = _u16(timer)
        self.sound_command = _u16(sound_command)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if not world.cleanup_active:
            self.timer = _u16(self.timer - 1)
            if self.timer != 0:
                return
        world.sound_commands.append(self.sound_command)
        self.alive = False


class StageTransitionF1BF(Enemy):
    """Post-boss queue barrier allocated by event handler `$F130`.

    `$F1BF` itself owns no sprite.  It remains at priority `$FF00` until the
    three VRAM/HUD jobs and two `$ED93` jobs queued by `$F153` have drained;
    the later `$F260/$F34D` score-reveal states keep this same pool record.
    Their task queue is modelled separately from object scheduling, so this
    record deliberately remains alive here while the queue is non-empty.
    """

    def __init__(self) -> None:
        super().__init__(
            "stage_transition_f1bf", 0, 0, 0xFF, 0,
            shootable=False, hostile=False, death_effect=None,
            weapon_vulnerable=False, scheduler_priority=0xFF00)
        # `$F153` queues exactly five jobs before returning: E865, E8A0,
        # EC7B and two ED93 records.  The task scheduler retires one record
        # per main pass; trace 13289..13293 exposes this barrier directly.
        self.queue_jobs = 5
        self.state = "f1bf"
        self.timer = 0
        self.result_digits = [0] * 8
        self.display_digits = [0xFF] * 8

    def _begin_score_reveal(self, world: "M72EnemyWorld") -> None:
        digits: list[int] = []
        for value in reversed(world.stage_score_bcd):
            digits.extend(((value >> 4) & 0x0F, value & 0x0F))
        # `$F244` intentionally starts at `$3059`: the highest eighth nibble
        # is outside the seven-character stage-result field.
        for index in range(1, 8):
            if digits[index] != 0:
                break
            digits[index] = 0xFF
        self.result_digits = digits
        self.display_digits = list(digits)
        self.timer = 0x00E0
        self.state = "f260"

    def _update_score_reveal(self, world: "M72EnemyWorld") -> None:
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            self.timer = 0x0020
            self.state = "f34d"
            return
        changed = False
        for index, threshold in enumerate(
                (0x10, 0x20, 0x30, 0x50, 0x70, 0x90, 0xA0), 1):
            if self.timer < threshold:
                continue
            value = self.result_digits[index]
            if self.timer == threshold:
                if value == 0xFF:
                    value = 0
                    self.result_digits[index] = 0
                self.display_digits[index] = value
                continue
            if value == 0xFF:
                continue
            random_digit = world.rng.next() & 0x0F
            if random_digit >= 10:
                random_digit &= 7
            self.display_digits[index] = random_digit
            changed = True
        if changed and not (world.frame_counter & 3):
            world.sound_commands.append(0x55)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.state == "f1bf":
            self.queue_jobs -= 1
            if self.queue_jobs == 0:
                self._begin_score_reveal(world)
            return
        if self.state == "f260":
            self._update_score_reveal(world)
            return
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            # `$F353…$F365`: release this very record, then resume only
            # foreground X and reset the 15 collision queue records.
            world.foreground_velocity_command = 0x0080
            self.alive = False


class PlayerShotVisual4EAF(Enemy):
    """One-pass ordinary-shot muzzle visual allocated by fixed slot `$4ED8`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        palette = world.resources.acquire(0x02)
        super().__init__("player_shot_visual_4eaf", 0, 0, palette, 0x26F2,
                         shootable=False, hostile=False,
                         death_effect=None, weapon_vulnerable=False,
                         scheduler_priority=0xFF00)

    def update(self, _world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.alive = False


class RedFlyer(Enemy):
    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        y = world.rom.word(0x8DB0 + index * 2)
        palette = world.resources.acquire(0x0D)
        super().__init__("red_flyer", 0x02C8, y, palette, 0x28E2,
                         score_pointer=0x86EC)
        self.collision_table = 0x2912
        self.motion = ScriptedMotion(world.rom, 0x9ACE, 2)
        fire_index = (command & 0xF0) >> 4
        table = 0x8E10 + fire_index * 6  # difficulty RAM:$2F2E is zero.
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        mask = _u16(self.fire_a - 1)
        # `$F8DC…$F8F4` calls `$EDE9` even when the selected six-byte
        # parameter record is all zero.  Skipping that call desynchronised
        # every later random object in Stage 1.
        self.fire_counter = (world.rng.next() * 4) & mask
        self.motion.phase = world.rng.next() & 0x1F

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.motion.update(world.rom, self):
            self.alive = False
            return
        self.x = _u16(self.x + foreground_delta)
        animation_offset = (world.frame_counter + self.motion.phase) & 0x1C
        self.descriptor = 0x28E2 + (animation_offset >> 2) * 6
        _run_f63a(world, self)


class FormationChild(Enemy):
    def __init__(self, world: "M72EnemyWorld", parent: "FormationParent",
                 movement_index: int) -> None:
        palette = world.resources.acquire(0x0C)
        super().__init__("patrol_child", parent.x, parent.y, palette, 0x29D2,
                         score_pointer=0x86EC)
        self.collision_table = 0x2A38
        self.motion = ScriptedMotion(world.rom, parent.script, 2)
        self.motion.phase = parent.phase
        # The parent creates this object while the scheduler has already
        # passed its priority bucket; unlike an event-created object it runs
        # on the next pass without an additional dispatcher delay.
        self.start_delay = 0
        table = 0x8E10 + (movement_index & 0x0F) * 6
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        mask = _u16(self.fire_a - 1)
        # `$F8A7/$F8E4` performs the normal first random initialization, but
        # this particular allocator immediately calls RNG again at `$5E5D`
        # and overwrites object `+$26` with `AX & $000F`.  `+$16` is copied
        # unchanged from the parent motion state; treating the second value
        # as a motion phase made formation children fire at VBlank 1447/1467
        # where the arcade allocates no `$E601` object.
        self.fire_counter = (world.rng.next() * 4) & mask
        self.fire_counter = world.rng.next() & 0x0F

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.motion.update(world.rom, self):
            self.alive = False
            return
        self.x = _u16(self.x + foreground_delta)
        self.descriptor = 0x29D2 + self.motion.phase * 6
        _run_f63a(world, self)

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        was_alive = self.alive
        super().take_damage(world, damage)
        # `$5ED0…$5EEC`: the one-hit formation child sends `$50`, queues
        # score `$86EC` and replaces its own handler with `$E7BE`.
        if was_alive and not self.alive:
            world.sound_commands.append(0x50)


class FormationParent(Enemy):
    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        parameter_index = (command >> 8) & 3  # `$F8F5`: CH & 3
        entry = 0x9250 + parameter_index * 4
        self.sequence = world.rom.word(entry)
        self.remaining = world.rom.word(entry + 2)
        animation_index = (command >> 4) & 0x0F  # `$F985`
        animation = world.rom.word(0x92EC + animation_index * 2)
        self.script = animation
        self.phase = world.rom.word(animation)
        self.sequence_index = 0
        self.spawn_timer = 2
        if 3 <= index < 9:
            x = _u16(x + 0x40)
        super().__init__("patrol_parent", x, y, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        if self.x < 0x0150:
            self.alive = False
            return
        self.spawn_timer -= 1
        if self.spawn_timer or not self.remaining:
            return
        self.spawn_timer = 0x10
        movement_index = world.rom.word(self.sequence + self.sequence_index * 2)
        world.pending.append(FormationChild(world, self, movement_index))
        self.sequence_index = (self.sequence_index + 1) % 5
        self.remaining -= 1
        if not self.remaining:
            self.alive = False


class GroundWalker(Enemy):
    """Literal six-state ground walker `$5A2B…$5CD7`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        self.direction = (command >> 8) & 1
        palette = world.resources.acquire(0x1E)
        self.secondary_palette = world.resources.acquire(0x1F)
        super().__init__("ground_walker", x, y, palette, 0x0100,
                         score_pointer=0x86EC,
                         scheduler_priority=0x8020,
                         inherit_slot_fractions=True)
        self.collision_table = 0x2982
        self.state = "falling"
        self.animation_pointer = 0
        self.animation_timer = 0
        self.motion: ScriptedMotion | None = None
        self.x_fraction = 0
        # Entry `$5A12` calls the common parameter decoder `$F8A7`.
        # The high nibble of CL selects one six-byte record at `ES:$8E10`:
        # first fire counter, upper counter limit, projectile velocity table.
        fire_index = (command & 0xF0) >> 4
        fire_table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(fire_table)
        self.fire_b = world.rom.word(fire_table + 2)
        self.projectile_script = world.rom.word(fire_table + 4)
        # `$F8DC…$F8F4` consumes RNG even for the all-zero record.
        self.fire_counter = ((world.rng.next() * 4) &
                             _u16(self.fire_a - 1))

    def _fire(self, world: "M72EnemyWorld") -> None:
        """Literal common projectile request `$F63A` used by every state."""
        _run_f63a(world, self)

    def _inside_native_bounds(self) -> bool:
        """Carry result of the common unsigned rectangle test `$1D6B`."""
        return (0x012C <= self.x < 0x02D4 and
                0x007C <= self.y < 0x0194)

    def _fall(self, world: "M72EnemyWorld", foreground_delta: int,
              *, fire: bool) -> None:
        """One literal `$5BA4` pass, also used by `$5B4D` fall-through."""
        if fire:
            self._fire(world)
        self.y = _u16(self.y - 3)
        if not self.direction:
            self.x = _u16(self.x + foreground_delta)
        table = 0x2970 if self.direction else 0x294C
        if not (world.frame_counter & 8):
            table += 6
        self.descriptor = table
        if not self._inside_native_bounds():
            self.alive = False
            return
        probe_x = _u16(self.x + (8 if self.direction else -8))
        probe_y = _u16(self.y - 0x10)
        if world.terrain_at(probe_x, probe_y) >= 0x0DFC:
            return
        self.y = _u16((self.y + 7) & 0xFFF8)
        self.animation_pointer = 0x2932 if self.direction else 0x292A
        self.animation_timer = 4
        self.state = "landing"

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        # `$5A2B/$5AE9/$5B4D/$5BA4/$5C3E/$5CA6` all begin with a call to
        # `$F63A`; firing therefore continues during fall/landing as well as
        # during the visible walking phase.
        self._fire(world)
        if self.state == "falling":
            # `_fire` already executed above; `$5BA4` does not receive a
            # second call except on the `$5B4D -> $5B9F` fall-through.
            self._fall(world, foreground_delta, fire=False)
            return
        if self.state == "landing":
            if not self.direction:
                self.x = _u16(self.x + foreground_delta)
            self.descriptor = world.rom.word(self.animation_pointer)
            self.animation_timer -= 1
            if self.animation_timer == 0:
                # `$5C6A` reloads +$22 before testing the next word for the
                # zero terminator; snapshot 1487 retains timer 4 in `$5A2B`.
                self.animation_timer = 4
                self.animation_pointer += 2
                if world.rom.word(self.animation_pointer) == 0:
                    self.state = "walking"
            return

        if self.state == "turning":
            # `$5AE9`: this is a second four-VBlank descriptor stream.  It is
            # not a pause invented by the port: its zero word selects one of
            # the two ROM motion roots and installs handler `$5B4D`.
            if not self.direction:
                self.x = _u16(self.x + foreground_delta)
            self.descriptor = world.rom.word(self.animation_pointer)
            self.animation_timer -= 1
            if self.animation_timer:
                return
            self.animation_pointer = _u16(self.animation_pointer + 2)
            if world.rom.word(self.animation_pointer):
                self.animation_timer = 4
                return
            script = 0x9B0A if self.direction else 0x9AF8
            self.motion = ScriptedMotion(world.rom, script, 2)
            self.state = "scripted"
            return

        if self.state == "scripted":
            # `$5B4D` runs `$F5C1` before drawing.  Carry falls through
            # `$5B9F` into `$5BA4` in the same dispatcher pass; consequently
            # `$F63A` is called a second time on precisely that transition.
            if self.motion is None:
                raise RuntimeError("ground walker entered $5B4D without motion")
            if self.motion.update(world.rom, self):
                self.state = "falling"
                self._fall(world, foreground_delta, fire=True)
                return
            if not self.direction:
                self.x = _u16(self.x + foreground_delta)
            table = 0x2970 if self.direction else 0x294C
            if not (world.frame_counter & 8):
                table += 6
            self.descriptor = table
            if not self._inside_native_bounds():
                self.alive = False
            return

        if self.state == "edge":
            # `$5CA6` is locked to the scrolling terrain.  It deliberately
            # has no independent X velocity and chooses its pose by the
            # unsigned relation between R-9 and the object.
            self.x = _u16(self.x + foreground_delta)
            player_x, _player_y = world.player_native
            self.descriptor = 0x293A if player_x < self.x else 0x295E
            if not self._inside_native_bounds():
                self.alive = False
            return

        # `$5A2B`: ordinary surface walk.  The two ROM terrain probes below
        # are what prevent a walker from carrying an obsolete Y coordinate
        # past a ledge and appearing suspended over the landscape.
        velocity = 0x00C0 if self.direction else -0x00C0
        if not self.direction:
            self.x = _u16(self.x + foreground_delta)
        coordinate = ((self.x << 8) | self.x_fraction) + velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        table = 0x2922 if self.direction else 0x291A
        offset = (world.frame_counter & 0x18) >> 2
        self.descriptor = world.rom.word(table + offset)
        # Literal `$1D6B`: CLC only inside the unsigned native rectangle
        # X=$012C..$02D3, Y=$007C..$0193.  The first no-fire walker is still
        # X=$012C in snapshot 1810 and is absent from snapshot 1811.
        if not self._inside_native_bounds():
            self.alive = False
            return

        first_x = _u16(self.x + (0x10 if self.direction else -0x10))
        first_y = _u16(self.y - 0x14)
        if world.terrain_at(first_x, first_y) >= 0x0DFC:
            self.animation_pointer = (0x2932 if self.direction else 0x292A)
            self.animation_timer = 4
            self.state = "turning"
            return

        second_x = _u16(self.x + (0x12 if self.direction else -0x12))
        second_y = _u16(self.y - 0x0C)
        if world.terrain_at(second_x, second_y) < 0x0DFC:
            self.state = "edge"

    @property
    def active_palette(self) -> int:
        return (self.secondary_palette
                if self.state in ("falling", "scripted") else self.palette)


class ExplosionEffect(Enemy):
    """Resource-$01 ROM explosion players `$E7A6…$E817`."""

    SEQUENCES = {
        "e7a6": (0x8574, 2),
        "e7ae": (0x8552, 2),
        "e7b6": (0x8506, 2),
        "e7be": (0x8530, 2),
        # `$973F…$9750` enters the common `$E7D4` player with the same
        # descriptor stream but resource type `$6B` instead of `$01`.
        "e7d4_6b": (0x8530, 2),
        "e80c": (0x85FA, 1),
        "e817": (0x85FA, 1),
    }

    def __init__(self, world: "M72EnemyWorld", x: int, y: int,
                 effect: str, *, scheduler_priority: int = 0x8010) -> None:
        self.sequence_pointer, self.sequence_timer = self.SEQUENCES[effect]
        self.effect = effect
        resource_type = (0x6B if effect == "e7d4_6b" else
                         0x63 if effect == "e80c" else 0x01)
        palette = world.resources.acquire(resource_type)
        super().__init__(f"explosion_{effect}", x, y, palette,
                         world.rom.word(self.sequence_pointer + 2),
                         shootable=False, hostile=False, death_effect=None,
                         scheduler_priority=scheduler_priority)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self.descriptor = world.rom.word(self.sequence_pointer + 2)
        self.sequence_timer -= 1
        if self.sequence_timer:
            return
        self.sequence_pointer += 4
        duration = world.rom.word(self.sequence_pointer)
        if duration == 0:
            self.alive = False
            return
        self.sequence_timer = duration & 0xFF


class ExplosionE7BE(ExplosionEffect):
    """Literal ordinary resource-$01 explosion `$E7BE/$E7D4`."""

    def __init__(self, world: "M72EnemyWorld", x: int, y: int) -> None:
        # The standalone `$5811` carrier-death allocation passes CX=`$A000`.
        # In-place weapon-death explosions use `ExplosionEffect` directly and
        # retain their source record's priority instead.
        super().__init__(world, x, y, "e7be", scheduler_priority=0xA000)


class DobkeratopsDebrisE700(ExplosionEffect):
    """Literal terrain-cutting body fragment `$E700/$E71C/$E75C`.

    Unlike the ordinary explosion entries, `$E700` returns after its
    initializer.  Its first sprite is therefore emitted on the following
    scheduler pass.  Sixteen passes later it replaces the ROM-selected
    terrain cells with tile `$0FA0` while preserving their attributes.
    """

    def __init__(self, world: "M72EnemyWorld", x: int, y: int) -> None:
        super().__init__(world, x, y, "e7b6", scheduler_priority=0xEF00)
        self.terrain_timer = 0x10
        self.terrain_path = 0x452E
        self.initialized = False
        self.render_ready = False

    def _cut_terrain(self, world: "M72EnemyWorld") -> None:
        address = world.terrain_address(
            _u16(self.x - 0x0C), _u16(self.y + 0x0C))
        while True:
            _code, attribute = world.terrain_cell(address)
            world.replace_terrain(address, 0x0FA0, attribute)
            delta = world.rom.word(self.terrain_path)
            self.terrain_path = _u16(self.terrain_path + 2)
            if delta == 0x8000:
                self.terrain_timer = 0xFFFF
                return
            low = ((address & 0xFF) + (delta & 0xFF)) & 0xFF
            high = (((address >> 8) + (delta >> 8)) & 0xFF) << 8
            address = (high | low) & 0x3FFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if not self.initialized:
            # `$E700…$E71B` installs `$E71C` and returns without drawing.
            self.initialized = True
            return
        self.render_ready = True
        self.terrain_timer = _u16(self.terrain_timer - 1)
        if self.terrain_timer == 0:
            self._cut_terrain(world)
        super().update(world, foreground_delta)


class Handler5CEAShot(Enemy):
    """Straight projectile `$E6AB/$E6C0` emitted by handler `$5CEA`."""

    def __init__(self, world: "M72EnemyWorld", x: int, y: int,
                 x_velocity: int) -> None:
        self.x_velocity = _signed_word(x_velocity & 0xFFFF)
        self.x_fraction = 0
        palette = world.resources.acquire(0x02)
        super().__init__("handler_5cea_shot", x, y, palette, 0x84CE,
                         shootable=False, death_effect=None)
        self.collision_table = 0x84FE

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        phase = (world.frame_counter & 6) >> 1
        self.descriptor = 0x84CE + phase * 12
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Enemy5CEA(Enemy):
    """Literal `$5CEA/$5D2D` horizontal shooter used by Stages 5 and 7."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        y = world.rom.word(0x8DB0 + (command & 0x0F) * 2)
        self.x_fraction = 0
        self.x_velocity = -0x0200
        self.shot_velocity = _signed_word(world.rom.word(0x298A))
        self.fire_reload = world.rom.word(0x298C)
        self.fire_counter = self.fire_reload
        self.random_delay = (world.rng.next() & 0x1F) + 0x30
        palette = world.resources.acquire(0x0E)
        super().__init__("enemy_5cea", 0x02C8, y, palette, 0x299A)
        self.collision_table = 0x29CA

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        phase = (world.frame_counter & 0x1C) >> 2
        self.descriptor = 0x299A + phase * 6

        self.fire_counter -= 1
        if self.fire_counter == 0:
            self.fire_counter = self.fire_reload
            world.projectile_spawns += 1
            world.pending.append(Handler5CEAShot(
                world, self.x, self.y, self.shot_velocity))
        if self.x < 0x0140:
            self.alive = False


class FinalProjectile9660(Enemy):
    """Aimed final-stage child `$96E9` created by spawner `$9674`."""

    def __init__(self, world: "M72EnemyWorld", x: int, y: int,
                 x_velocity: int, y_velocity: int,
                 descriptor: int) -> None:
        self.x_velocity = _signed_word(x_velocity & 0xFFFF)
        self.y_velocity = _signed_word(y_velocity & 0xFFFF)
        self.x_fraction = self.y_fraction = 0
        self.descriptor_base = descriptor
        palette = world.resources.acquire(0x60)
        super().__init__("final_projectile_9660", x, y, palette, descriptor,
                         death_effect="e7d4_6b")
        self.collision_table = 0x436C

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        self.descriptor = self.descriptor_base + (
            6 if world.frame_counter & 8 else 0)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class FinalSpawner9660(Enemy):
    """Invisible final-stage periodic spawner `$9660/$9674`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        y = 0x009C if command & 0x10 else 0x0174
        self.period = world.rom.word(0x943C + (command & 0x0F) * 2)
        self.timer = world.rng.next() & _u16(self.period - 1)
        super().__init__("final_spawner_9660", 0x02C0, y, 0xFF, 0,
                         shootable=False, hostile=False, death_effect=None)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.x = _u16(self.x + world.background_delta)
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            self.timer = self.period
            direction = _direction_offset(
                self.x, self.y, *world.player_native)
            velocity_table = world.rom.word(0x4284)  # difficulty zero.
            x_velocity = world.rom.word(velocity_table + direction)
            y_velocity = world.rom.word(velocity_table + direction + 2)
            descriptor = world.rom.word(0x428C + (direction >> 1))
            world.pending.append(FinalProjectile9660(
                world, self.x, self.y, x_velocity, y_velocity, descriptor))
            world.projectile_spawns += 1
        if self.x < 0x0140:
            self.alive = False


class TerrainBound55E9(Enemy):
    """Literal terrain state machine rooted at event handler `$55E9`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        palette = world.resources.acquire(0x0F)
        script = 0x9AB2 if x < 0x0150 else 0x9A96
        self.motion = ScriptedMotion(world.rom, script, 2)
        self.motion.phase = (command >> 4) & 7
        self.pickup_index = (command >> 4) & 7
        self.pickup_type = 0
        self.pickup_phase = 0
        self.state = "script"
        self.timer = 0
        # `$03A6` does not clear the Q8 residue at record bytes +$03/+$07.
        # Both `$0672` and `$0689` therefore inherit the fractions left by the
        # previous owner of the FIFO slot.
        self.x_fraction = 0
        self.y_fraction = 0
        super().__init__("terrain_bound_55e9", x, y, palette, 0x2826,
                         inherit_slot_fractions=True)
        self.collision_table = 0x28DA

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        if self.state == "pickup":
            return
        self.hp -= damage
        if self.hp > 0:
            return

        # `$5811`: retain this object record, but replace its carrier resource
        # and handler; the explosion is a separate `$A000/$E7BE` object.
        world.resources.release(self.palette)
        table = 0x27FE + self.pickup_index * 4
        if world.frame_counter & 2:
            table += 2
        resource_and_type = world.rom.word(table)
        resource_type = resource_and_type & 0xFF
        self.pickup_type = (resource_and_type >> 8) & 0xFF
        self.palette = world.resources.acquire(resource_type)
        self.pickup_phase = 0
        self.state = "pickup"
        self.shootable = False
        self.hostile = False
        self.collision_table = 0x2784
        self.descriptor = (0x27B6 if self.pickup_type == 8 else
                           0x278C + self.pickup_type * 6)
        # `$581A…$5820`: destruction of the carrier schedules `$E8BD` with
        # the packed-BCD increment at `ES:$86EC` before becoming a pickup.
        world.award_score_pointer(0x86EC)
        world.pending.append(ExplosionE7BE(world, self.x, self.y))

    @staticmethod
    def _overlaps_player(x: int, y: int,
                         player_x: int, player_y: int) -> bool:
        # Pickup table ES:$2784 = (-16,+14,-14,+14); R-9 `$2027` writes
        # (-7,+8,-1,+6). `$F578` is asymmetric: the target's negative
        # endpoint must be strictly before the player's positive endpoint,
        # while its positive endpoint may land exactly on the player's
        # negative endpoint (`JB` versus `JAE`).
        return (x - 16 < player_x + 8 and x + 14 >= player_x - 7 and
                y - 14 < player_y + 6 and y + 14 >= player_y - 1)

    def _collect(self, world: "M72EnemyWorld") -> None:
        pickup_type = self.pickup_type
        # `$5947`: every successful pickup sends the common collection SFX
        # before queuing its score task and branching by pickup type.
        world.sound_commands.append(0x3A)
        # `$594C…$5952`: collecting any power-up schedules `$E8BD/$86F4`.
        world.award_score_pointer(0x86F4)
        if pickup_type < 8:
            world.weapon_pickups = (world.weapon_pickups + 1) & 0xFF
            world.weapon_type = pickup_type
            # `$595C` only increments pending byte `$0037`.  Player handler
            # `$216D…$2182`, which precedes the Force record in the next
            # scheduler pass, consumes one pending byte and then increments
            # `$003E`.  Updating Force here starts it one pass too early.
        else:
            address = world.rom.word(0x281E + pickup_type - 8)
            if address == 0x0033:
                world.ram_0033 = (world.ram_0033 + 1) & 0xFF
            elif address == 0x0035:
                world.ram_0035 = (world.ram_0035 + 1) & 0xFF
            elif address == 0x0036:
                world.ram_0036 = (world.ram_0036 + 1) & 0xFF
                # `$58FC…$5914` does not delete the pickup record.  It turns
                # that same record into the 16-pass speed indicator, swaps
                # resource type `$0A` for `$09`, and immediately executes the
                # first `$5914` pass.
                world.resources.release(self.palette)
                self.palette = world.resources.acquire(0x09)
                self.timer = 0x10
                self.state = "speed_indicator"
                self._update_speed_indicator(world)
                return
        self.alive = False

    def _update_speed_indicator(self, world: "M72EnemyWorld") -> None:
        # `$5914…$5946`: anchor to R-9, select one of four six-byte
        # descriptors from the timer bits, then remove this record on zero.
        player_x, player_y = world.player_native
        self.x = _u16(player_x - 0x1F)
        self.y = player_y
        phase = self.timer & 0x0C
        self.descriptor = 0x28C2 + phase + (phase >> 1)
        self.timer = _u16(self.timer - 1)
        world.speed_indicator_timer = self.timer
        if self.timer == 0:
            self.alive = False

    def _update_pickup(self, world: "M72EnemyWorld",
                       foreground_delta: int) -> None:
        if (world.frame_counter & 7) == 0:
            self.pickup_phase = (self.pickup_phase + 1) % 12
        self.x = _u16(self.x + foreground_delta)
        if self.pickup_type == 8:
            self.descriptor = 0x27B6 + self.pickup_phase * 6
        else:
            self.descriptor = 0x278C + self.pickup_type * 6
        if self._overlaps_player(self.x, self.y, *world.player_native):
            self._collect(world)
            return
        if not (0x012C <= self.x < 0x02D4 and
                0x007C <= self.y < 0x0194):
            self.alive = False

    def _right_facing(self) -> bool:
        phase = self.motion.phase & 0x0C
        # JP after AND: even parity for $00/$0C selects the first table.
        return phase in (0x00, 0x0C)

    def _descriptor_pair(self, first: int, second: int) -> int:
        return first if self._right_facing() else second

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "speed_indicator":
            self._update_speed_indicator(world)
            return
        if self.state == "pickup":
            self._update_pickup(world, foreground_delta)
            return

        if self.state in ("script", "air_step"):
            if self.state == "script":
                # Handler `$5629` enters the compressed-motion interpreter.
                self.motion.update(world.rom, self)
            else:
                # Handler `$5620` calls `$0689` with AX=$FF00 and then jumps
                # to the shared body at `$562C`.  Crucially, it does *not*
                # restore `$5629`: it remains the active handler until one of
                # the terrain branches writes a different state.
                coordinate = ((self.y << 8) | self.y_fraction) - 0x0100
                self.y = _u16(coordinate >> 8)
                self.y_fraction = coordinate & 0xFF
            self.x = _u16(self.x + foreground_delta)
            self.descriptor = self._descriptor_pair(0x2826, 0x282C)
            # `$564C` runs the common unsigned bounds helper `$1D6B` before
            # any terrain probe.  Omitting it let the first carrier wrap from
            # X=$012B to `$FFFF` and occupy a FIFO slot for the rest of the
            # stage even though the arcade object had already called `$03EC`.
            if not (0x012C <= self.x < 0x02D4 and
                    0x007C <= self.y < 0x0194):
                self.alive = False
                return
            if world.terrain_at(self.x, _u16(self.y - 0x10)) < 0x0DFC:
                self.y = _u16((self.y + 7) & 0xFFF8)
                self.timer = 0x1F
                self.state = "land"
                return
            probe_x = _u16(self.x + (0x10 if self._right_facing() else -0x10))
            if (world.terrain_at(probe_x, self.y) < 0x0DFC or
                    world.terrain_at(self.x, _u16(self.y + 0x10)) < 0x0DFC):
                self.state = "air_step"
            return

        if self.state == "land":
            self.x = _u16(self.x + foreground_delta)
            phase = self.timer & 0x18
            offset = ((phase >> 1) + (phase >> 2))
            self.descriptor = self._descriptor_pair(0x2832, 0x284A) + offset
            self.timer -= 1
            if self.timer == 0:
                self.state = "walk"
            return

        if self.state == "walk":
            velocity = 0x0100 if self._right_facing() else -0x0100
            coordinate = ((self.x << 8) | self.x_fraction) + velocity
            self.x = _u16(coordinate >> 8)
            self.x_fraction = coordinate & 0xFF
            self.x = _u16(self.x + foreground_delta)
            phase = world.frame_counter & 0x18
            offset = ((phase >> 1) + (phase >> 2))
            self.descriptor = self._descriptor_pair(0x2862, 0x287A) + offset
            # `$5745` repeats `$1D6B` for the walking handler `$5704`.
            if not (0x012C <= self.x < 0x02D4 and
                    0x007C <= self.y < 0x0194):
                self.alive = False
                return
            ahead_x = _u16(self.x + (0x10 if self._right_facing() else -0x10))
            if world.terrain_at(ahead_x, _u16(self.y - 0x14)) >= 0x0DFC:
                self.timer = 0x1F
                self.state = "turn"
            elif world.terrain_at(
                    _u16(self.x + (0x12 if self._right_facing() else -0x12)),
                    _u16(self.y - 0x0E)) < 0x0DFC:
                self.motion.phase ^= 8
                self.timer = 0x1F
                self.state = "turn"
            return

        self.x = _u16(self.x + foreground_delta)
        phase = self.timer & 0x18
        offset = ((phase >> 1) + (phase >> 2))
        self.descriptor = self._descriptor_pair(0x2892, 0x28AA) + offset
        self.timer -= 1
        if self.timer == 0:
            script = 0x9AB2 if self._right_facing() else 0x9AA2
            self.motion = ScriptedMotion(world.rom, script, 2)
            self.y = _u16(self.y + 4)
            self.state = "script"


def _direction_offset(current_x: int, current_y: int,
                      target_x: int, target_y: int) -> int:
    """Return the 16-direction byte offset produced by ROM `$1D89`."""
    if current_y + 8 < target_y:
        if current_x + 8 < target_x:
            value = (target_x - current_x) - (target_y - current_y) + 0x20
            return 0x08 if 0 <= value < 0x40 else (0x04 if value < 0 else 0x0C)
        if current_x - 8 >= target_x:
            value = (current_x - target_x) - (target_y - current_y) + 0x20
            return 0x38 if 0 <= value < 0x40 else (0x3C if value < 0 else 0x34)
        return 0x00
    if current_y - 8 >= target_y:
        if current_x + 8 < target_x:
            value = (target_x - current_x) - (current_y - target_y) + 0x20
            return 0x18 if 0 <= value < 0x40 else (0x1C if value < 0 else 0x14)
        if current_x - 8 >= target_x:
            value = (current_x - target_x) - (current_y - target_y) + 0x20
            return 0x28 if 0 <= value < 0x40 else (0x24 if value < 0 else 0x2C)
        return 0x20
    return 0x10 if current_x < target_x else 0x30


class PlayerTargeting80E3(Enemy):
    """Two-state mini-boss `$80E3/$8138/$82D6`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        palette = world.resources.acquire(0x20)
        self.flash_palette = world.resources.acquire(0x55)
        player_x, player_y = world.player_native
        self.target_x = self.previous_target_x = _u16(player_x + 0xF0)
        self.target_y = self.previous_target_y = player_y
        self.x_velocity = 0
        self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        self.retarget_counter = 0xFFFF
        self.animation_offset = 0
        self.attack_delay = world.rng.next() & 0x1F
        self.activation_timer = 0x01C0
        self.state = "tracking"
        self.attack_timer = 0
        self.flash_timer = 0
        self.flash_visible = False
        super().__init__("player_targeting_80e3", x, y, palette, 0x38A2,
                         hp=0x1E, score_pointer=0x86F8,
                         scheduler_priority=0xA000,
                         inherit_slot_fractions=True)
        self.collision_table = 0x3956
        self.death_effect = "e817"

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False

        if self.state == "attack":
            self._update_attack(world)
            return
        self._update_tracking(world)

    def _update_tracking(self, world: "M72EnemyWorld") -> None:
        """Literal tracking handler `$8138…$82D5`."""
        self.retarget_counter = _u16(self.retarget_counter + 1)
        if (self.retarget_counter & 0x1F) == 0:
            self.previous_target_x = self.target_x
            self.previous_target_y = self.target_y
            player_x, player_y = world.player_native
            self.target_x = _u16(player_x + 0xA0)
            self.target_y = player_y
            direction = _direction_offset(
                self.x, self.y, self.target_x, self.target_y)
            self.x_velocity = _signed_word(world.rom.word(0x3966 + direction))
            self.y_velocity = _signed_word(world.rom.word(0x3968 + direction))

        # `$8176…$8182`: after the 448-update activation interval expires,
        # the ROM unconditionally replaces only X velocity with -$0100.
        # Y remains controlled by the last player-targeting calculation.
        if self.activation_timer == 0:
            self.x_velocity = -0x0100

        # `$8138` probes 48 native pixels ahead before applying each velocity.
        probe_x = _u16(self.x + (-0x30 if self.x_velocity < 0 else 0x30))
        fg, bg = world.collision_at(probe_x, self.y)
        if (fg >= 0x0DFC and bg >= 0x07D0 and
                (self.x < 0x02A0 or self.x_velocity < 0)):
            coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
            self.x = _u16(coordinate >> 8)
            self.x_fraction = coordinate & 0xFF
        probe_y = _u16(self.y + (-0x30 if self.y_velocity < 0 else 0x30))
        fg, bg = world.collision_at(self.x, probe_y)
        if fg >= 0x0DFC and bg >= 0x07D0:
            coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
            self.y = _u16(coordinate >> 8)
            self.y_fraction = coordinate & 0xFF

        player_x, player_y = world.player_native
        if player_x >= self.x:
            table = 0x3876
            if self.x_velocity < 0:
                self.animation_offset = min(0x3E, self.animation_offset + 1)
                table = 0x387E
        else:
            table = 0x3866
            if self.x_velocity < 0:
                self.animation_offset = min(0x3E, self.animation_offset + 1)
                table = 0x386E
        if self.x_velocity >= 0:
            self.animation_offset = 0
        pointer_offset = (self.animation_offset & 0x30) >> 3
        self.descriptor = world.rom.word(table + pointer_offset)

        # `$8236…$8267`: only vertical alignment advances the attack delay.
        # When it reaches zero the difficulty table reloads it and installs
        # the separate 31-update attack handler `$82D6`.
        upper = _u16(player_y + 0x18)
        lower = _u16(upper - 0x30)
        if lower < self.y <= upper:
            self.attack_delay = _u16(self.attack_delay - 1)
            if self.attack_delay == 0:
                self.attack_delay = world.rom.word(
                    0x3856 + world.difficulty * 2)
                self.attack_timer = 0x1F
                self.state = "attack"

        if self.activation_timer:
            self.activation_timer -= 1
        if self.x < 0x0130:
            self.alive = False

    def _update_attack(self, world: "M72EnemyWorld") -> None:
        """Literal lunge, two-child emission and return `$82D6…$8354`."""
        timer = self.attack_timer
        if timer < 0x0E:
            velocity = 0x0200 if timer >= 8 else -0x00C0
            coordinate = ((self.x << 8) | self.x_fraction) + velocity
            self.x = _u16(coordinate >> 8)
            self.x_fraction = coordinate & 0xFF

        player_x, _player_y = world.player_native
        table = 0x3886 if player_x < self.x else 0x388E
        self.descriptor = world.rom.word(
            table + ((timer & 0x18) >> 2))

        if timer == 0x10:
            world.pending.append(Targeting80E3Projectile(world, self))
            world.pending.append(Targeting80E3AttackFlash(world, self))

        self.attack_timer = _u16(timer - 1)
        if self.attack_timer == 0:
            self.state = "tracking"
        if self.x < 0x0130:
            self.alive = False

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        # `$826B/$831E` stores $10 after `$F6DA`; `$8409` then flashes when
        # the decremented counter has its low two bits clear.
        super().take_damage(world, damage)
        self.flash_timer = 0x10


class Targeting80E3AttackFlash(Enemy):
    """Stationary 15-count launch effect `$83DF`."""

    def __init__(self, world: "M72EnemyWorld",
                 parent: PlayerTargeting80E3) -> None:
        player_x, _player_y = world.player_native
        if player_x < parent.x:
            descriptor_root = 0x390E
            x = _u16(parent.x - 0x26)
        else:
            descriptor_root = 0x38F6
            x = _u16(parent.x + 0x32)
        self.descriptor_root = descriptor_root
        self.sequence_timer = 0x0F
        self.sequence_delay = 4
        self.visible = False
        palette = world.resources.acquire(0x09)
        super().__init__("player_targeting_80e3_attack_flash", x, parent.y,
                         palette, descriptor_root, shootable=False,
                         hostile=False, death_effect=None,
                         scheduler_priority=0x1F00)
        self.weapon_vulnerable = False

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.sequence_delay -= 1
        if self.sequence_delay:
            return
        # `$83E4` immediately changes the four-update startup delay to one;
        # the remaining fourteen descriptors therefore advance every VBlank.
        self.sequence_delay = 1
        self.sequence_timer -= 1
        if self.sequence_timer == 0:
            self.alive = False
            return
        offset = ((self.sequence_timer & 0x0C) * 3) // 2
        self.descriptor = self.descriptor_root + offset
        self.visible = True


class Targeting80E3Projectile(Enemy):
    """Difficulty-scaled two-sprite attack projectile `$842C`."""

    def __init__(self, world: "M72EnemyWorld",
                 parent: PlayerTargeting80E3) -> None:
        player_x, _player_y = world.player_native
        velocity = _signed_word(world.rom.word(
            0x385E + world.difficulty * 2))
        offset = -0x30
        if player_x >= parent.x:
            velocity = -velocity
            offset = 0x30
        self.x_velocity = velocity
        self.x_fraction = 0
        self.y_fraction = 0
        palette = world.resources.acquire(0x09)
        super().__init__("player_targeting_80e3_projectile",
                         _u16(parent.x + offset), parent.y,
                         palette, 0x3926, shootable=False,
                         death_effect=None, scheduler_priority=0x2000,
                         inherit_slot_fractions=True)
        self.weapon_vulnerable = False
        self.collision_table = 0x395E

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        descriptor = 0x3926
        if not (world.frame_counter & 4):
            descriptor += 0x18
        if self.x_velocity >= 0:
            descriptor += 0x0C
        self.descriptor = descriptor
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class EnemyProjectile(Enemy):
    """Projectile object created by `$F63A`, runtime handler `$E601`."""

    def __init__(self, world: "M72EnemyWorld", source: Enemy,
                 velocity_table: int) -> None:
        direction = _direction_offset(
            source.x, source.y, *world.player_native)
        self.x_velocity = _signed_word(world.rom.word(
            velocity_table + direction))
        self.y_velocity = _signed_word(world.rom.word(
            velocity_table + direction + 2))
        self.x_fraction = self.y_fraction = 0
        palette = world.resources.acquire(0x56)
        self.phase_seed = world.projectile_spawns * 8
        super().__init__("enemy_projectile", source.x, source.y,
                         palette, 0x84AE, scheduler_priority=0xA000,
                         inherit_slot_fractions=True)
        self.weapon_vulnerable = False
        self.force_collision_only = True
        self.collision_table = 0x84C6
        self.death_effect = None
        self.burst_timer = 0

    def _begin_burst(self) -> None:
        # `$E686`: ten-frame local projectile breakup; its resource remains
        # type $56 and it does not enter one of the $E7xx explosion players.
        self.burst_timer = 0x0A
        self.shootable = False
        self.hostile = False

    def take_damage(self, _world: "M72EnemyWorld", _damage: int) -> None:
        if not self.burst_timer:
            self._begin_burst()

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.burst_timer:
            offset = (self.burst_timer & 0x0E) * 3
            self.descriptor = 0x8490 + offset
            self.burst_timer -= 1
            if self.burst_timer == 0:
                self.alive = False
            return
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        phase = (world.frame_counter + self.phase_seed) & 0x18
        self.descriptor = 0x84AE + ((phase >> 1) + (phase >> 2))
        # `$E659..$E67B`: the common `$F63A` projectile does not probe the
        # tilemaps on every update.  Odd VBlanks return immediately; on an
        # even VBlank the ROM checks both foreground and background before
        # applying the shared object bounds.  Checking every frame made the
        # walking launcher's shot burst while it was still leaving its owner.
        # The frame callback samples `$2EB6` before IRQ `$0219` increments
        # it; object handler `$E659` reads the incremented value later in the
        # same VBlank.  At reference frame 1522 the sampled/Python value is
        # `$0531`, while `$E601` tests `$0532` and enters `$E686` immediately.
        if _u16(world.frame_counter + 1) & 1:
            return
        foreground, background = world.collision_at(self.x, self.y)
        if foreground < 0x0DFC or background < 0x07D0:
            self._begin_burst()
        elif (self.x < 0x012C or self.x >= 0x02D4 or
              self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class TerrainModifierProjectile6E27(Enemy):
    """Q8 projectile `$6E27` emitted by a rotating-snake link `$6C37`."""

    def __init__(self, world: "M72EnemyWorld",
                 source: "TerrainModifierChild6C37",
                 parent: "TerrainModifierParent6ACB") -> None:
        offset = (source.motion.phase & 0xFF) * 4
        self.x_velocity = _signed_word(world.rom.word(
            source.projectile_script + offset))
        self.y_velocity = _signed_word(world.rom.word(
            source.projectile_script + offset + 2))
        self.x_fraction = self.y_fraction = 0
        self.parent = parent
        self.burst_timer = 0
        palette = world.resources.acquire(0x56)
        super().__init__(
            "terrain_modifier_projectile_6e27",
            source.x, _u16(source.y + 0x0C), palette, 0,
            # `$6E61` calls the Force/Bit-only `$F493` path every update.
            # Wave and ordinary shots remain excluded by
            # ``weapon_vulnerable=False`` below.
            shootable=True, death_effect=None,
            scheduler_priority=0xA000,
            inherit_slot_fractions=True,
        )
        self.weapon_vulnerable = False
        self.collision_table = 0x2F06
        # `$6E33..$6E4F` selects one of four immutable descriptors at
        # ES:$2EEE from the object-slot phase and VBlank counter.
        self.render_ready = True

    def _begin_burst(self) -> None:
        self.burst_timer = 0x0A
        self.shootable = False
        self.hostile = False

    def take_damage(self, _world: "M72EnemyWorld", _damage: int) -> None:
        # `$6E64 -> $E686`: a Force/Bit hit enters the same ten-pass breakup
        # used by the common `$E601` projectile; it is not an immediate free.
        if not self.burst_timer:
            self._begin_burst()

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.burst_timer:
            self.burst_timer -= 1
            if self.burst_timer == 0:
                self.alive = False
            return
        coordinate = (((self.x << 8) | self.x_fraction) +
                      self.x_velocity)
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = (((self.y << 8) | self.y_fraction) +
                      self.y_velocity)
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

        slot_phase = ((self.object_slot or 0) >> 3) + world.frame_counter
        self.descriptor = 0x2EEE + ((slot_phase & 0x18) * 3 // 4)

        if world.terrain_at(self.x, self.y) < 0x0DFC:
            self._begin_burst()
            return
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False
            return
        parent_x = self.parent.x
        if parent_x >= self.x:
            self._begin_burst()
        elif _u16(parent_x + 0x00C0) < self.x:
            self.alive = False


class TerrainModifierChild6C37(Enemy):
    """One of the sixteen rotating-snake links created by `$6ACB`."""

    def __init__(self, world: "M72EnemyWorld",
                 parent: "TerrainModifierParent6ACB",
                 record: int, ordinal: int) -> None:
        # `$6B13…$6B2C` has a literal BX-lifetime quirk for ordinal four.
        # Its difficulty-dependent HP lookup leaves `BX=2*difficulty`, so the
        # following `MOV CX,ES:[BX+4]` does *not* read `record+$04`.  At
        # difficulty zero it reads `ES:$0004=$5E8B`, selecting F8A7 row 8.
        # Every other ordinal still reaches `$6B29` with BX=record.
        command = world.rom.word(
            4 + world.difficulty * 2 if ordinal == 4 else record + 4)
        self.parent = parent
        self.ordinal = ordinal
        self.motion = ScriptedMotion(world.rom, 0xA0BC, 1)
        self.motion.pointer = world.rom.word(record + 6)
        self.motion.phase = 0
        fire_index = (command & 0xF0) >> 4
        table = 0x8E10 + fire_index * 6 + world.difficulty * 0x60
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        self.fire_counter = ((world.rng.next() * 4) &
                             _u16(self.fire_a - 1))
        self.local_timer = ordinal * 4
        hp = (world.rom.word(0x2E3E + world.difficulty * 2) & 0xFF
              if ordinal == 4 else 1)
        palette = world.resources.acquire(0x13)
        super().__init__(
            "terrain_modifier_child_6c37",
            world.rom.word(record), world.rom.word(record + 2),
            palette, 0, hp=hp, score_pointer=0x86EC,
            force_damage_cadenced=True,
            scheduler_priority=0x8021,
        )
        self.collision_table = 0x2FD4
        self.state = "active"
        # `$6C43..$6C5E` indexes two literal 16-frame descriptor rings in
        # World ROM.  Ordinal four is the larger head/core bank ES:$2F6E;
        # all other links use ES:$2F0E.
        self.render_ready = True

    def _remove(self) -> None:
        if self.alive:
            self.parent.child_count = max(0, self.parent.child_count - 1)
            self.alive = False

    def _run_fire(self, world: "M72EnemyWorld") -> None:
        if self.parent.x >= world.player_native[0]:
            return
        self.fire_counter = _u16(self.fire_counter + 1)
        if self.fire_counter != self.fire_a:
            if self.fire_counter < self.fire_b:
                return
            self.fire_counter = 0
        if self.projectile_script:
            world.pending.append(TerrainModifierProjectile6E27(
                world, self, self.parent))

    def _link_terrain_paths(self) -> None:
        if self.x < 0x0140 or not (self.y & 0x0100) or self.y >= 0x0144:
            return
        if self.ordinal == 0x10 and self.parent.build_path == 0:
            if _u16(self.parent.x + 0x30) >= self.x:
                self.parent.build_path = 1
        elif self.ordinal == 1 and self.parent.erase_path == 0:
            if _u16(self.parent.x + 0x30) >= self.x:
                self.parent.erase_path = 1

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "death_6d15":
            # `$6D15`: the original child record survives as resource-$14
            # debris.  It continues the same `$F5C1` motion stream before
            # scroll/render/hit processing, keeps the end-cap terrain linkage
            # alive, and decrements the parent's live-child count only when
            # it finally leaves the native window.
            self.motion.update(world.rom, self)
            self.x = _u16(self.x + foreground_delta)
            self.descriptor = 0x2FCE
            self._link_terrain_paths()
            if self.x < 0x00E0 or world.cleanup_active:
                self._remove()
            return
        self.motion.update(world.rom, self)
        self._run_fire(world)
        self.x = _u16(self.x + foreground_delta)
        descriptor_base = 0x2F6E if self.ordinal == 4 else 0x2F0E
        self.descriptor = descriptor_base + (self.motion.phase & 0x0F) * 6
        self._link_terrain_paths()
        if self.parent.center_destroyed:
            self.local_timer = _u16(self.local_timer - 1)
            if self.local_timer == 0:
                self._remove()
                return
        if self.x < 0x00E0 or world.cleanup_active:
            self._remove()

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        # `$6C61…$6C83`: while the parent has not passed R-9, the child calls
        # `$F6DA` with a temporary threshold $80, then restores both its
        # accumulated damage and threshold.  The ammunition collision is
        # still consumed, but the child retains no damage from it.
        if self.parent.x >= world.player_native[0]:
            return
        # The complete `$6CCB/$6D15` post-hit state is irrelevant to the
        # no-fire lifecycle oracle, but damage accounting and the centre flag
        # must remain literal for interactive play.
        self.hp -= damage
        if self.hp > 0:
            return
        # `$6CCB…$6D14` does not replace this record with the common
        # explosion.  It awards the score, changes this same record to
        # resource-$14/$6D15, and allocates a *separate* `$E7BE` at priority
        # `$E000`, which initializes later in this scheduler pass.
        world.award_score_pointer(0x86EC)
        world.sound_commands.append(0x52)
        if self.ordinal == 4:
            self.parent.center_destroyed = True
        world.resources.release(self.palette)
        self.palette = world.resources.acquire(0x14)
        self.state = "death_6d15"
        self.hp = 0x7F
        self.shootable = True
        self.hostile = False
        self.death_effect = None
        self.destroyed = False
        world.pending.append(ExplosionEffect(
            world, self.x, self.y, "e7be", scheduler_priority=0xE000))


class TerrainModifierParent6ACB(Enemy):
    """Rotating snake: event `$6A9B`, spawn `$6ACB`, runtime `$6B4F`."""

    PATH = 0x2EC6

    def __init__(self) -> None:
        super().__init__(
            "terrain_modifier_parent_6acb", 0x02D8, 0x0154, 0xFF, 0,
            shootable=False, hostile=False, death_effect=None,
            weapon_vulnerable=False, scheduler_priority=0x8010,
        )
        self.state = "spawn_children"
        self.record_pointer = 0x2E46
        self.child_count = 0
        self.timer = 0
        self.center_destroyed = False
        self.build_path = 0
        self.erase_path = 0
        self.path_origin = 0
        self.build_cursor = 0
        self.erase_cursor = 0

    @staticmethod
    def _advance_path_cursor(cursor: int, delta: int) -> int:
        """Literal `ADD BL,AL / ADD BH,AH`: no carry between bytes."""
        low = ((cursor & 0xFF) + (delta & 0xFF)) & 0xFF
        high = (((cursor >> 8) + (delta >> 8)) & 0xFF) << 8
        return high | low

    def _write_full_path(self, world: "M72EnemyWorld") -> None:
        """`$6C09`: remember the origin and build the complete first path."""
        cursor = world.terrain_address(self.x, self.y) & 0x3FFF
        self.path_origin = cursor
        pointer = self.PATH
        while True:
            world.replace_terrain(cursor, 0x03E8, 0x0081)
            delta = world.rom.word(pointer)
            if delta == 0:
                return
            cursor = self._advance_path_cursor(cursor, delta)
            pointer = _u16(pointer + 2)

    # Пары полей build/erase выбираются явными ветвями вместо getattr/setattr
    # по вычисленному имени; порядок чтений и записей прежний.
    def _path_pointer(self, build: bool) -> int:
        return self.build_path if build else self.erase_path

    def _set_path_pointer(self, build: bool, value: int) -> None:
        if build:
            self.build_path = value
        else:
            self.erase_path = value

    def _path_cursor(self, build: bool) -> int:
        return self.build_cursor if build else self.erase_cursor

    def _set_path_cursor(self, build: bool, value: int) -> None:
        if build:
            self.build_cursor = value
        else:
            self.erase_cursor = value

    def _step_path(self, world: "M72EnemyWorld", *, build: bool) -> None:
        """One `$6B68…$6BEF` build/erase cell on an eighth VBlank."""
        pointer = self._path_pointer(build)
        if pointer == 0:
            return
        if pointer == 1:
            self._set_path_cursor(build, self.path_origin)
            pointer = self.PATH
            self._set_path_pointer(build, pointer)

        cursor = self._path_cursor(build)
        world.replace_terrain(
            cursor, 0x03E8 if build else 0x0FA0, 0x0081)
        delta = world.rom.word(pointer)
        if delta == 0:
            self._set_path_pointer(build, 0)
            return
        self._set_path_cursor(build,
                              self._advance_path_cursor(cursor, delta))
        self._set_path_pointer(build, _u16(pointer + 2))

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "spawn_children":
            for ordinal in range(1, 17):
                child = TerrainModifierChild6C37(
                    world, self, self.record_pointer, ordinal)
                world.pending.append(child)
                if child.object_slot is None:
                    break
                self.child_count += 1
                self.record_pointer = _u16(self.record_pointer + 8)
            self.timer = 0x40
            self.state = "active"
            return

        # `$6B4F…$6C08`: the full path is written before the parent receives
        # this pass's foreground delta.  The two incremental paths are then
        # serviced build-first on the VBlank cadence observed by the handler.
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            self._write_full_path(world)
        self.x = _u16(self.x + foreground_delta)
        # `frame_counter` is the pre-IRQ state sampled by the MAME callback;
        # `$6B5D` sees `$2EB6` after that IRQ increment.
        if (_u16(world.frame_counter + 1) & 7) == 0:
            self._step_path(world, build=True)
            self._step_path(world, build=False)
        if self.child_count == 0 or world.cleanup_active:
            self.alive = False


class TerrainAware897E(Enemy):
    """Four-probe player seeker from `$897E/$89B0/$8AEE`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        palette = world.resources.acquire(0x1D)
        fire_index = (command & 0xF0) >> 4
        fire_table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(fire_table)
        self.fire_b = world.rom.word(fire_table + 2)
        self.projectile_script = world.rom.word(fire_table + 4)
        mask = _u16(self.fire_a - 1)
        # `$F8A7/$F8E4` always consumes one RNG value, including the all-zero
        # six-byte fire record selected by command high nibble zero.
        self.fire_counter = (world.rng.next() * 4) & mask
        self.direction_flags = 0
        self.direction_counter = 0x007F
        self.direction_mask = world.rom.word(0x3C1A)  # difficulty zero
        self.reverse_vertical = False
        self.escape_counter = 0
        self.x_fraction = self.y_fraction = 0
        super().__init__("terrain_aware_897e", x, y, palette, 0x3C22,
                         score_pointer=0x86F0,
                         scheduler_priority=0x8030,
                         inherit_slot_fractions=True)
        self.collision_table = 0x3C56

    def _integrate_x(self, velocity: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF

    def _integrate_y(self, velocity: int) -> None:
        coordinate = ((self.y << 8) | self.y_fraction) + velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        _run_f63a(world, self)
        self.direction_counter += 1
        if ((self.direction_counter & self.direction_mask) == 0 and
                self.direction_counter < 0x0400):
            player_x, player_y = world.player_native
            if self.reverse_vertical:
                vertical = 1 if self.y >= player_y else 2
            else:
                vertical = 1 if self.y < player_y else 2
            horizontal = 4 if self.x >= player_x else 8
            self.direction_flags = vertical | horizontal

        applied = 0
        if (self.direction_flags & 1 and
                world.terrain_at(self.x, _u16(self.y + 0x18)) >= 0x0DFC):
            self._integrate_y(0x00C0)
            applied += 1
        elif self.reverse_vertical:
            # `$8B4D`: the alternate handler shortens its escape lifetime
            # whenever the requested downward move is unavailable (including
            # when bit 0 is not the selected vertical direction).
            self.escape_counter = 1
        if (self.direction_flags & 2 and
                world.terrain_at(self.x, _u16(self.y - 0x18)) >= 0x0DFC):
            self._integrate_y(-0x00C0)
            applied += 1
        elif self.reverse_vertical:
            # `$8B76`, symmetric with `$8B4D` above.
            self.escape_counter = 1
        if (self.direction_flags & 4 and
                world.terrain_at(_u16(self.x - 0x18), self.y) >= 0x0DFC):
            self._integrate_x(-0x00C0)
            applied += 1
        if (self.direction_flags & 8 and
                world.terrain_at(_u16(self.x + 0x18), self.y) >= 0x0DFC):
            self._integrate_x(0x00C0)
            applied += 1
        self.x = _u16(self.x + foreground_delta)
        table = 0x3C2A if self.direction_flags & 8 else 0x3C22
        pointer_offset = (world.frame_counter & 0x30) >> 3
        self.descriptor = world.rom.word(table + pointer_offset)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False
            return

        # `$89B0` changes to `$8AEE` only when neither requested axis could
        # move.  `$8AEE` is a distinct ROM state, not a boolean direction
        # toggle: it returns to `$89B0` when again fully blocked, or when its
        # `$03FF` lifetime expires.  In the normal one-vertical-bit case the
        # unselected vertical branch above writes 1, so a successful escape
        # also returns after this single pass (`$8C06…$8C11`).
        if not self.reverse_vertical:
            if applied == 0:
                self.reverse_vertical = True
                self.escape_counter = 0x03FF
        elif applied == 0:
            self.reverse_vertical = False
        else:
            self.escape_counter = _u16(self.escape_counter - 1)
            if self.escape_counter == 0:
                self.reverse_vertical = False


class Enemy8469(Enemy):
    """Literal Stage 7 wall-bouncing enemy `$8469/$8490`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        y = world.rom.word(0x8DB0 + (command & 0x0F) * 2)
        fire_index = (command & 0xF0) >> 4
        table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        mask = _u16(self.fire_a - 1)
        self.fire_counter = (world.rng.next() * 4) & mask
        self.x_velocity = -0x0200
        self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        self.pause_timer = 0
        palette = world.resources.acquire(0x18)
        super().__init__("enemy_8469", 0x02C8, y, palette, 0x39A6)
        self.collision_table = 0x39AC

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self._integrate()
        _run_f63a(world, self)

        solid_left = world.terrain_at(
            _u16(self.x - 0x20), self.y) < 0x0DFC
        if solid_left:
            if self.y_velocity == 0:
                self.x_velocity = 0
                self.y_velocity = (0x0100 if world.frame_counter & 1
                                   else -0x0100)
                self.pause_timer = 8
            else:
                probe_y = _u16(self.y + (
                    -0x18 if self.y_velocity < 0 else 0x18))
                if world.terrain_at(self.x, probe_y) < 0x0DFC:
                    self.y_velocity = -self.y_velocity
        elif self.pause_timer:
            self.pause_timer -= 1
        else:
            self.x_velocity = -0x0200
            self.y_velocity = 0

        if self.x < 0x0140:
            self.alive = False


class Enemy8561(Enemy):
    """Literal Stage 5 composite shooter `$8561/$85B0/$865E`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        y = world.rom.word(0x941C + (command & 0x0F) * 2)
        self.x_velocity = -0x0100
        self.x_fraction = 0
        self.shot_velocity = _signed_word(world.rom.word(0x39B4))
        self.fire_reload = world.rom.word(0x39B6)
        self.fire_counter = self.fire_reload
        self.shot_y_phase = 0
        self.animation_bias = 0
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(0x19)
        super().__init__("enemy_8561", 0x02C8, y, palette, 0x39CE,
                         hp=0x1E, death_effect="e817")
        self.collision_table = 0x3A2E

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 7

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        phase = ((world.frame_counter + self.animation_bias) & 0x70) >> 4
        self.descriptor = 0x39CE + phase * 12

        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (world.frame_counter & 3) == 0
        else:
            self.flash_visible = False

        self.fire_counter -= 1
        if self.fire_counter == 0:
            self.fire_counter = self.fire_reload
            y_offset = _signed_word(
                world.rom.word(0x39C4 + self.shot_y_phase))
            self.shot_y_phase += 2
            if self.shot_y_phase >= 10:
                self.shot_y_phase = 0
            world.pending.append(Handler5CEAShot(
                world, _u16(self.x - 0x10), _u16(self.y + y_offset),
                self.shot_velocity))
            world.projectile_spawns += 1
        if self.x < 0x0140:
            self.alive = False


class Enemy8F5E(Enemy):
    """Literal four-direction Stage 4 enemy `$8F5E/$8F86/$90A2`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        self.direction = world.rom.byte(0x3F76 + index)
        self.next_direction = self.direction
        self.x_fraction = self.y_fraction = 0
        self.turn_timer = 0
        self.turn_table = 0
        palette = world.resources.acquire(0x2E)
        super().__init__("enemy_8f5e", x, y, palette, 0x4006)
        self.collision_table = 0x407E

    def _integrate(self, world: "M72EnemyWorld") -> None:
        table = 0x3F86 + self.direction * 4  # difficulty zero block.
        x_velocity = _signed_word(world.rom.word(table))
        y_velocity = _signed_word(world.rom.word(table + 2))
        coordinate = ((self.x << 8) | self.x_fraction) + x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _begin_turn_if_near_player(self, world: "M72EnemyWorld") -> bool:
        player_x, player_y = world.player_native
        if not self.direction & 2:
            if _u16(self.x + 0x10 - player_x) >= 0x20:
                return False
            self.next_direction = 2 if self.y < player_y else 3
        else:
            if _u16(self.y + 4 - player_y) >= 8:
                return False
            self.next_direction = 0 if self.x < player_x else 1
        self.turn_timer = 0x1F
        matrix_index = self.direction * 4 + self.next_direction
        self.turn_table = world.rom.word(0x3FC6 + matrix_index * 2)
        return True

    def _turn_update(self, world: "M72EnemyWorld",
                     foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        offset = 2 if self.turn_timer & 0x10 else 0
        self.descriptor = world.rom.word(self.turn_table + offset)
        self.turn_timer -= 1
        if self.turn_timer == 0:
            self.direction = self.next_direction

    def _clear_four_cells(self, world: "M72EnemyWorld") -> None:
        address = world.terrain_address(
            _u16(self.x - 4), _u16(self.y + 4))
        right = ((address & 0xFF00) | ((address + 4) & 0xFF)) & 0x3FFF
        below_right = (right + 0x100) & 0x3FFF
        below_left = ((below_right & 0xFF00) |
                      ((below_right - 4) & 0xFF)) & 0x3FFF
        for cell in (address, right, below_right, below_left):
            if world.terrain_cell(cell)[0] & 0x0FFF == 0x09F6:
                world.replace_terrain(cell, 0x0FA0, 0)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.turn_timer:
            self._turn_update(world, foreground_delta)
            return
        self._integrate(world)
        self.x = _u16(self.x + foreground_delta)
        if self._begin_turn_if_near_player(world):
            # `$9075` jumps into `$90A2`; the transition-entry frame applies
            # foreground delta a second time exactly as the V30 code does.
            self._turn_update(world, foreground_delta)
            return
        frame = (world.frame_counter & 0x0C) >> 2
        self.descriptor = 0x4006 + self.direction * 24 + frame * 6
        self._clear_four_cells(world)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class TerrainEnemy696E(Enemy):
    """Literal Stage 4 terrain enemy `$696E/$69B4/$6A78`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = _u16(world.rom.word(0x8DD2 + index * 4) + 4)
        motion_index = (command & 0xF0) >> 2
        script = world.rom.word(0x92AC + motion_index)
        commands = world.rom.byte(0x92AE + motion_index)
        self.motion = ScriptedMotion(world.rom, script, commands)
        self.fire_a = world.rom.word(0x9294)
        self.fire_b = world.rom.word(0x9296)
        self.projectile_script = world.rom.word(0x9298)
        self.fire_counter = 0
        self.flash_timer = 0
        self.flash_visible = False
        palette = world.resources.acquire(0x2A)
        self.flash_palette = world.resources.acquire(0x55)
        hp = world.rom.byte(0x2D8C)  # difficulty RAM `$2F2E` is zero.
        super().__init__("terrain_enemy_696e", x, y, palette, 0x2DD0,
                         hp=hp)
        self.collision_table = 0x2E36

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 0x0C

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.motion.update(world.rom, self):
            # Carry from `$F5C1` takes the natural cleanup path `$6A42`.
            self.alive = False
            return
        self.x = _u16(self.x + foreground_delta)
        _run_f63a(world, self)

        direction = self.motion.phase & 0x0F
        self.descriptor = 0x2DD0 + direction * 6
        dx = _signed_word(world.rom.word(0x2D90 + direction * 4))
        dy = _signed_word(world.rom.word(0x2D92 + direction * 4))
        probe_x = _u16(self.x + dx)
        probe_y = _u16(self.y + dy)
        if world.terrain_at(probe_x, probe_y) == 0x0FA0:
            world.replace_terrain(
                world.terrain_address(probe_x, probe_y), 0x09F6, 0x0082)

        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False


class Enemy6F89(Enemy):
    """Literal Stage 2 object `$6F89/$6FD0/$7048/$7106`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        record = 0x9384 + (command & 3) * 14
        self.primary_x = _signed_word(world.rom.word(record + 2))
        self.primary_y = _signed_word(world.rom.word(record + 4))
        self.secondary_x = _signed_word(world.rom.word(record + 6))
        self.secondary_y = _signed_word(world.rom.word(record + 8))
        self.descriptor_table = world.rom.word(record + 10)
        self.target_direction = world.rom.word(record + 12)
        mode = (command >> 2) & 3
        self.wait_value = world.rom.word(0x93BC + mode * 2)
        self.animation = 0
        self.x_fraction = self.y_fraction = 0
        self.state = "waiting"
        self.flash_timer = 0
        self.flash_visible = False
        self.previous_damage = 0
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(0x27)
        initial_descriptor = world.rom.word(self.descriptor_table + 2)
        super().__init__("enemy_6f89", 0x02D0, world.rom.word(record),
                         palette, initial_descriptor, hp=10,
                         death_effect="e817")
        self.collision_table = 0x31EE

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        if self.alive and self.flash_timer == 0:
            self.flash_timer = 0x17
            self.previous_damage = self.hp + damage

    def _integrate(self, x_velocity: int, y_velocity: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _animated_descriptor(self, world: "M72EnemyWorld") -> int:
        offset = (self.animation & 0x3C) >> 1
        return world.rom.word(self.descriptor_table + offset)

    def _flash_update(self, world: "M72EnemyWorld",
                      foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self.flash_timer -= 1
        if self.flash_timer == 0:
            self.flash_visible = False
            return
        self.animation = _u16(self.animation + 1)
        self.descriptor = self._animated_descriptor(world)
        self.flash_visible = (self.flash_timer & 3) == 0

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.flash_timer:
            self._flash_update(world, foreground_delta)
            return
        self.flash_visible = False
        self.x = _u16(self.x + foreground_delta)

        if self.state == "waiting":
            if self.wait_value & 0x8000:
                ready = (_direction_offset(
                    self.x, self.y, *world.player_native) ==
                         self.target_direction)
            else:
                self.wait_value = _u16(self.wait_value - 1)
                ready = self.wait_value == 0
            if ready:
                self.state = "moving"
                return
            offset = 4 if not (self.wait_value & 0x8000) and (
                self.wait_value & 0x3F) == 0 else 2
            self.descriptor = world.rom.word(self.descriptor_table + offset)
        else:
            if world.terrain_at(self.x, self.y) == 0x0FA0:
                self._integrate(self.primary_x, self.primary_y)
                self.descriptor = world.rom.word(self.descriptor_table + 4)
            else:
                self._integrate(self.secondary_x, self.secondary_y)
                self.animation = _u16(self.animation + 1)
                self.descriptor = self._animated_descriptor(world)

        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Enemy7182(Enemy):
    """Literal 16-direction Stage 5 seeker `$7182/$71C7`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        fire_index = (command & 0xF0) >> 4
        fire_table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(fire_table)
        self.fire_b = world.rom.word(fire_table + 2)
        self.projectile_script = world.rom.word(fire_table + 4)
        mask = _u16(self.fire_a - 1)
        self.fire_counter = (world.rng.next() * 4) & mask
        self.direction = world.rom.byte(0x31FE + index)
        self.turn_reload = world.rom.word(0x31F6)  # difficulty zero.
        self.turn_counter = 1
        self.active_timer = 0x0280
        self.x_velocity = self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        palette = world.resources.acquire(0x44)
        super().__init__("enemy_7182", x, y, palette,
                         0x3216 + self.direction * 6)
        self.collision_table = 0x3276

    def _turn_one_step(self, target: int) -> None:
        current = self.direction
        if target < current:
            current -= 1
        elif target < 8 or target - 8 < current:
            current += 1
        else:
            current -= 1
        self.direction = current & 0x0F

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.active_timer:
            self.active_timer -= 1
            self.turn_counter -= 1
            if self.turn_counter == 0:
                target = _direction_offset(
                    self.x, self.y, *world.player_native) >> 2
                self._turn_one_step(target)
                velocity_table = world.rom.word(0x320E)
                offset = self.direction * 4
                self.x_velocity = _signed_word(
                    world.rom.word(velocity_table + offset))
                self.y_velocity = _signed_word(
                    world.rom.word(velocity_table + offset + 2))
                self.turn_counter = self.turn_reload

        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        self.descriptor = 0x3216 + self.direction * 6

        _run_f63a(world, self)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Projectile7435(EnemyProjectile):
    """Terrain-aware projectile `$7435` emitted by `$72D2/$73DB`."""

    def __init__(self, world: "M72EnemyWorld", source: Enemy,
                 velocity_table: int) -> None:
        super().__init__(world, source, velocity_table)
        self.kind = "projectile_7435"
        # `$7435/$7258` enters the full `$F694` weapon dispatcher.
        self.weapon_vulnerable = True
        self.phase_seed = world.projectile_spawns * 8
        self.terrain_delay = 8
        self.collision_table = 0x3296

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.burst_timer:
            super().update(world, 0)
            return
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        phase = ((world.frame_counter + self.phase_seed) & 0x18) >> 3
        self.descriptor = 0x327E + phase * 6
        if (world.frame_counter & 1) == 0:
            if self.terrain_delay:
                self.terrain_delay -= 1
            else:
                foreground, background = world.collision_at(self.x, self.y)
                if foreground < 0x0DFC or background < 0x07D0:
                    self._begin_burst()
                    return
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Enemy7294(Enemy):
    """Literal Stage 6 terrain-reflecting shooter `$7294/$72D2`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        fire_index = (command & 0xF0) >> 4
        fire_table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(fire_table)
        self.fire_b = world.rom.word(fire_table + 2)
        self.projectile_script = world.rom.word(fire_table + 4)
        mask = _u16(self.fire_a - 1)
        self.fire_counter = (world.rng.next() * 4) & mask
        index = command & 0x0F
        position = 0x93DC + index * 4
        x = world.rom.word(position)
        y = world.rom.word(position + 2)
        self.direction = ((command >> 8) & 1) * 2
        self.animation = 0
        self.x_fraction = self.y_fraction = 0
        self.flash_timer = 0
        self.flash_visible = False
        palette = world.resources.acquire(0x43)
        self.flash_palette = world.resources.acquire(0x55)
        descriptor_base = world.rom.word(0x32BE + self.direction * 2)
        super().__init__("enemy_7294", x, y, palette, descriptor_base,
                         hp=2)
        self.collision_table = 0x333E

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 0x0C

    def _integrate(self, world: "M72EnemyWorld") -> None:
        table = 0x329E + self.direction * 4
        x_velocity = _signed_word(world.rom.word(table))
        y_velocity = _signed_word(world.rom.word(table + 2))
        coordinate = ((self.x << 8) | self.x_fraction) + x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _terrain_reflect(self, world: "M72EnemyWorld") -> None:
        table = 0x32AE + self.direction * 4
        probe_x = _u16(self.x + _signed_word(world.rom.word(table)))
        probe_y = _u16(self.y + _signed_word(world.rom.word(table + 2)))
        outside = not (0x012C <= probe_x < 0x02D4 and
                       0x007C <= probe_y < 0x0194)
        if outside:
            self.direction ^= 1
        if world.terrain_at(probe_x, probe_y) >= 0x0DFC:
            self.direction ^= 1

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self._integrate(world)
        if (world.frame_counter & 7) == 0:
            self.animation += 6
            if self.animation == 0x1E:
                self.animation = 0
        descriptor_base = world.rom.word(0x32BE + self.direction * 2)
        self.descriptor = descriptor_base + self.animation

        if _f63a_trigger(self) and self.projectile_script:
            world.projectile_spawns += 1
            world.pending.append(Projectile7435(
                world, self, self.projectile_script))
        self._terrain_reflect(world)

        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Enemy5EED(Enemy):
    """Literal Stage 6 cardinal terrain enemy `$5EED/$5F3C`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        record = 0x9324 + index * 6
        x = world.rom.word(record)
        y = world.rom.word(record + 2)
        self.direction = world.rom.byte(record + 4) & 3
        self.turn_clockwise = bool(command & 0x0100)
        self.mirrored = bool(command & 0x0040)
        self.speed_offset = world.rom.word(0x931C +
                                           ((command >> 4) & 3) * 2)
        self.x_fraction = self.y_fraction = 0
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x51)
        palette = world.resources.acquire(0x28)
        descriptor = 0x2AF0 if self.mirrored else 0x2AC0
        super().__init__("enemy_5eed", x, y, palette, descriptor,
                         hp=10, death_effect="e817")

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 0x1F

    def _integrate(self, world: "M72EnemyWorld") -> None:
        table = 0x2A80 + self.speed_offset + self.direction * 4
        x_velocity = _signed_word(world.rom.word(table))
        y_velocity = _signed_word(world.rom.word(table + 2))
        coordinate = ((self.x << 8) | self.x_fraction) + x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _ray_blocked(self, world: "M72EnemyWorld") -> bool:
        table = 0x2A40 + (0x20 if self.mirrored else 0) + self.direction * 8
        x = _u16(self.x + _signed_word(world.rom.word(table)))
        y = _u16(self.y + _signed_word(world.rom.word(table + 2)))
        repeat_x = _signed_word(world.rom.word(table + 4))
        repeat_y = _signed_word(world.rom.word(table + 6))
        for _ in range(3):
            code = 0x0FA0
            if x < 0x02C0:
                code = world.terrain_at(x, y)
            x = _u16(x + repeat_x)
            y = _u16(y + repeat_y)
            if code < 0x0DFC:
                return True
        return False

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self._integrate(world)
        self.x = _u16(self.x + foreground_delta)
        base = 0x2AF0 if self.mirrored else 0x2AC0
        phase = (world.frame_counter & 0x18) >> 3
        self.descriptor = base + phase * 12
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 4) == 0
        else:
            self.flash_visible = False
        if self._ray_blocked(world):
            self.direction = ((self.direction + 1) & 3 if self.turn_clockwise
                              else (self.direction - 1) & 3)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class StageObject8C12(Enemy):
    """Literal four-blast terrain mutator `$8C12…$8D54` (Stage 7)."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        record = 0x93C4 + (command & 7) * 4
        y = world.rom.word(record)
        self.terrain_path = world.rom.word(record + 2)
        self.timer = (world.rng.next() & 0xFF) << 1
        self.phase = 0
        super().__init__("stage_object_8c12", 0x02C0, y, 0xFF, 0,
                         shootable=False, hostile=False, death_effect=None)

    def _blast(self, world: "M72EnemyWorld", dx: int, dy: int,
               effect: str = "e7be") -> None:
        world.pending.append(ExplosionEffect(
            world, _u16(self.x + dx), _u16(self.y + dy), effect))

    def _apply_terrain_path(self, world: "M72EnemyWorld") -> None:
        address = world.terrain_address(self.x, self.y)
        pointer = self.terrain_path
        while True:
            delta = world.rom.word(pointer)
            if delta == 0:
                return
            low = ((address & 0xFF) + (delta & 0xFF)) & 0xFF
            high = (((address >> 8) + (delta >> 8)) & 0xFF) << 8
            address = (high | low) & 0x3FFF
            code = world.rom.word(pointer + 2)
            world.replace_terrain(address, code, 0x000A)
            pointer += 4

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self.timer = _u16(self.timer - 1)
        if self.timer:
            return
        if self.phase == 0:
            self._blast(world, -4, 14)
            self.timer = 0x10
        elif self.phase == 1:
            self._blast(world, 0x10, 0)
            self.timer = 8
        elif self.phase == 2:
            self._blast(world, -4, -4)
            self.timer = 0x10
        elif self.phase == 3:
            self._blast(world, 0, 0, "e80c")
            self._apply_terrain_path(world)
            self.timer = 0x20
        else:
            self.alive = False
            return
        self.phase += 1


class FixedLarge6E9B(Enemy):
    """Literal fixed multipart Stage 7 object `$6E9B/$6EC4`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        palette = world.resources.acquire(0x54)
        super().__init__("fixed_large_6e9b", 0x0110, 0x0108,
                         palette, 0x3042, hp=0xC8,
                         death_effect="e817")
        self.collision_table = 0x3072
        self.x_fraction = 0

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        was_alive = self.alive
        super().take_damage(world, damage)
        if was_alive and not self.alive:
            pointer = 0x301C
            while True:
                dx = world.rom.word(pointer)
                if dx == 0x8000:
                    break
                dy = world.rom.word(pointer + 2)
                world.pending.append(ExplosionEffect(
                    world, _u16(self.x + _signed_word(dx)),
                    _u16(self.y + _signed_word(dy)), "e7b6"))
                pointer += 2

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        move = self.x >= 0x0280
        if not move:
            foreground, background = world.collision_at(
                _u16(self.x + 0x40), self.y)
            move = foreground >= 0x0DFC and background >= 0x07D0
        if move:
            coordinate = ((self.x << 8) | self.x_fraction) + 0x00C0
            self.x = _u16(coordinate >> 8)
            self.x_fraction = coordinate & 0xFF
        if self.x < 0x0108 or self.x >= 0x0300:
            self.alive = False


class Spawner875DChild(Enemy):
    """Spawned object `$8861/$893E` owned by `$875D`."""

    def __init__(self, world: "M72EnemyWorld", parent: "Spawner875D",
                 delay: int) -> None:
        self.parent = parent
        self.delay = delay
        self.state = "wavy"
        self.x_velocity = _signed_word(world.rom.word(0x3B2A))
        self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        self.oscillator = 0
        self.animation = 0
        self.descriptor_base = 0x3BB2
        palette = world.resources.acquire(0x2D)
        y = _u16(parent.y - 0x20 + (world.rng.next() & 0x3F))
        super().__init__("spawner_875d_child", parent.x, y, palette,
                         0x3BB2, death_effect="e7a6")
        self.collision_table = 0x3C12

    def _integrate(self, x_velocity: int, y_velocity: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _begin_aimed(self, world: "M72EnemyWorld") -> None:
        direction = _direction_offset(self.x, self.y, *world.player_native)
        velocity_table = world.rom.word(0x3B22)  # difficulty zero.
        self.x_velocity = _signed_word(world.rom.word(
            velocity_table + direction))
        self.y_velocity = _signed_word(world.rom.word(
            velocity_table + direction + 2))
        self.descriptor_base = world.rom.word(0x3B32 + (direction >> 1))
        self.state = "aimed"

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "aimed":
            self.x = _u16(self.x + foreground_delta)
            self._integrate(self.x_velocity, self.y_velocity)
            self.animation += 1
            phase = (self.animation & 0x0C) >> 2
            self.descriptor = self.descriptor_base + phase * 6
        else:
            self.x = _u16(self.x + foreground_delta)
            target = _u16(self.parent.target_y - 0x20 +
                          (world.rng.next() & 0x3F))
            toward = -0x0010 if self.y >= target else 0x0010
            self.oscillator = (self.oscillator + 1) & 0xFF
            oscillation = 0x0040 if not self.oscillator & 0x40 else -0x0040
            self._integrate(self.x_velocity, toward + oscillation)
            self.animation += 1
            phase = (self.animation & 0x0C) >> 2
            self.descriptor = 0x3BB2 + phase * 6
            if self.delay:
                self.delay -= 1
                if self.delay == 0:
                    self._begin_aimed(world)
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Spawner875D(Enemy):
    """Literal Stage 2 timed child spawner `$875D/$8798/$87BA/$8817`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        self.script_pointer = 0x3AFE
        self.counter = 0
        self.spawn_reload = 0x40
        self.spawn_timer = 0x40
        self.delay_reload = 4
        self.delay_timer = 4
        self.target_y = 0x0130
        self.life = 0x0600
        super().__init__("spawner_875d", 0x02C0, 0x0120, 0xFF, 0,
                         shootable=False, hostile=False, death_effect=None)

    def _update_parameters(self, world: "M72EnemyWorld") -> None:
        self.counter = _u16(self.counter + 1)
        self.spawn_reload = world.rom.word(0x3B12)
        self.delay_reload = world.rom.word(0x3B14)
        while self.counter >= world.rom.word(self.script_pointer):
            value = world.rom.word(self.script_pointer + 2)
            if value & 0x8000:
                self.spawn_reload = value & 0x0FFF
                self.spawn_timer = self.spawn_reload
            elif value & 0x4000:
                self.delay_reload = value & 0x0FFF
                self.delay_timer = self.delay_reload
            else:
                self.target_y = value & 0x0FFF
            self.script_pointer += 4

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.life -= 1
        if self.life == 0:
            self.alive = False
            return
        self._update_parameters(world)
        self.spawn_timer -= 1
        if self.spawn_timer:
            return
        self.spawn_timer = self.spawn_reload
        delay = 0
        self.delay_timer -= 1
        if self.delay_timer == 0:
            self.delay_timer = self.delay_reload
            delay = world.rng.next() & 0xFF
        world.pending.append(Spawner875DChild(world, self, delay))


class Formation78F8Parent(Enemy):
    """Stage 5 linked formation allocator `$78F8/$7935`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        variant = (command >> 8) & 3
        self.priority = world.rom.word(0x34AE + variant * 2)
        self.sequence = (0x34B6 if self.priority >= 0x4280 else 0x34E2)
        self.timer = 1
        self.head: Formation78F8Child | None = None
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        animation = (command >> 4) & 0x0F
        self.motion_root = world.rom.word(0x9274 + animation * 2)
        super().__init__("formation_78f8_parent", x, y, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.timer = _u16(self.timer - 1)
        if self.timer:
            return
        handler = world.rom.word(self.sequence)
        delay = world.rom.word(self.sequence + 2)
        child = Formation78F8Child(
            world, self, handler, self.priority, self.head)
        self.priority = _u16(self.priority - 1)
        self.head = child
        world.pending.append(child)
        self.timer = delay
        if delay == 0:
            self.alive = False
        else:
            self.sequence += 4


class Formation78F8Child(Enemy):
    """All linked child states `$799C…$7D45` of `$78F8`."""

    def __init__(self, world: "M72EnemyWorld",
                 parent: Formation78F8Parent, initializer: int,
                 priority: int,
                 previous: "Formation78F8Child | None") -> None:
        self.previous = previous
        self.priority = priority
        self.motion = ScriptedMotion(world.rom, parent.motion_root, 2)
        self.motion.phase = 0
        self.motion_timer = 0
        self.delay = 0
        self.state_flag = 0
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x55)
        self.animation_seed = 0
        self.x_velocity = self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        if initializer == 0x799C:
            resource_type = 0x25
            self.state = "first"
            hp = 0x0E
            descriptor = 0x3526
            collision = 0x37C6
        elif initializer == 0x7A1E:
            resource_type = 0x26
            self.state = "main"
            hp = 6
            descriptor = 0x3676
            collision = 0x37CE
        elif initializer == 0x7AD9:
            resource_type = 0x25
            self.state = "terminal"
            hp = 6
            descriptor = 0x371E
            collision = 0x37D6
        else:
            raise ValueError(f"неизвестный `$78F8` child initializer ${initializer:04X}")
        palette = world.resources.acquire(resource_type)
        super().__init__("formation_78f8_child", parent.x, parent.y,
                         palette, descriptor, hp=hp,
                         death_effect="e7be")
        self.collision_table = collision

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        if not self.shootable or not self.alive:
            return
        self.hp -= damage
        self.flash_timer = 0x0C
        if self.hp > 0:
            return
        self.state_flag = 1 if self.state == "first" else 2
        self.alive = False
        self.destroyed = True

    def _set_motion_state(self, world: "M72EnemyWorld",
                          state: str, root: int) -> None:
        commands = self.motion.commands
        phase = self.motion.phase
        self.motion = ScriptedMotion(world.rom, root, commands)
        self.motion.phase = phase
        self.state = state

    def _begin_escape(self, world: "M72EnemyWorld", base: int) -> None:
        self.state_flag = 1
        self.state = "escape"
        self.descriptor_base = base
        index = (self.priority & 0x0F) * 4
        self.x_velocity = _signed_word(world.rom.word(0x8FD0 + index))
        self.y_velocity = _signed_word(world.rom.word(0x8FD2 + index))
        self.animation_seed = world.rng.next()
        self.collision_table = 0x37CE

    def _linked_transition(self, world: "M72EnemyWorld",
                           escape_base: int) -> str | None:
        if self.previous is None:
            return None
        flags = self.previous.state_flag
        if flags & 2:
            self.state_flag = 2
            self.delay = _u16(self.previous.delay + 4)
            self.motion.commands = 3
            return "chain"
        if flags & 1:
            self._begin_escape(world, escape_base)
            return "escape"
        return None

    def _draw_phase(self, base: int, composite: bool = False) -> None:
        stride = 12 if composite else 6
        self.descriptor = base + self.motion.phase * stride

    def _update_flash(self) -> None:
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False

    def _motion_or_remove(self, world: "M72EnemyWorld") -> bool:
        if self.motion.update(world.rom, self):
            self.alive = False
            return False
        return True

    def _update_linked(self, world: "M72EnemyWorld", foreground_delta: int,
                       base: int, collision: int,
                       expiry_state: str) -> None:
        if self.delay:
            self.delay -= 1
            if self.delay == 0:
                root = 0xA3E6 if self.motion.phase < 9 else 0xA380
                self._set_motion_state(world, expiry_state, root)
                return
        else:
            transition = self._linked_transition(world, base)
            if transition == "escape":
                return
            if transition is None:
                self.motion.commands = 2
                self.motion_timer = (self.motion_timer + 1) & 0x7F
                if self.motion_timer < 0x1F:
                    self.motion.commands = 1
        if not self._motion_or_remove(world):
            return
        self._draw_phase(base)
        self.collision_table = collision

    def _integrate_escape(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "first":
            self.motion_timer = (self.motion_timer + 1) & 0x7F
            self.motion.commands = 1 if self.motion_timer < 0x1F else 2
            if not self._motion_or_remove(world):
                return
            self._draw_phase(0x3526, composite=True)
            self.shootable = True
        elif self.state == "main":
            self._update_linked(world, foreground_delta, 0x3676, 0x37CE,
                                "main_follow")
            self.shootable = ((world.frame_counter ^ self.priority) & 1) != 0
        elif self.state == "terminal":
            self._update_linked(world, foreground_delta, 0x371E, 0x37D6,
                                "terminal_follow")
            self.shootable = True
        elif self.state == "main_follow":
            if not self._motion_or_remove(world):
                return
            self._draw_phase(0x3676)
            self.shootable = True
        elif self.state == "terminal_follow":
            if not self._motion_or_remove(world):
                return
            self._draw_phase(0x371E)
            self.shootable = True
        else:
            self._integrate_escape()
            self.animation_seed = _u16(self.animation_seed + 1)
            phase = self.animation_seed & 0x1E
            self.descriptor = self.descriptor_base + phase * 3
            if (self.x < 0x012C or self.x >= 0x02D4 or
                    self.y < 0x007C or self.y >= 0x0194):
                self.alive = False
                return
            self.shootable = True
        self._update_flash()


class Multipart915BParent(Enemy):
    """Twenty-two-record Stage 2 allocator `$915B/$91CC`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 7
        record = 0x4086 + index * 6
        self.motion_root = world.rom.word(record)
        x = world.rom.word(record + 2)
        y = world.rom.word(record + 4)
        mode = (command & 0x30) >> 3
        if world.difficulty:
            mode += 8
        base_timer = world.rom.word(0x40B6 + mode)
        if command & 4:
            base_timer = 0x00C0
        self.base_timer = base_timer
        self.sequence = 0x40C6
        self.timer = 1
        self.priority = 0x201F
        self.cleanup_ordinal = 2
        self.head: Multipart915BChild | None = None
        self.controller_handler = 0
        self.controller_flash = False
        super().__init__("multipart_915b_parent", x, y, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.timer = _u16(self.timer - 1)
        if self.timer:
            return
        initializer = world.rom.word(self.sequence)
        delay = world.rom.word(self.sequence + 2)
        self.priority = _u16(self.priority - 1)
        child = Multipart915BChild(
            world, self, initializer, self.priority,
            self.cleanup_ordinal, self.head)
        self.cleanup_ordinal = _u16(self.cleanup_ordinal + 2)
        self.head = child
        world.pending.append(child)
        self.timer = delay
        if delay == 0:
            self.alive = False
        else:
            self.sequence += 4


class Radial95F1(Enemy):
    """One of eight literal radial children `$95A3/$95F1`."""

    def __init__(self, world: "M72EnemyWorld", source: Enemy,
                 record: int) -> None:
        self.x_velocity = _signed_word(world.rom.word(record + 2))
        self.y_velocity = _signed_word(world.rom.word(record + 4))
        self.x_fraction = self.y_fraction = 0
        palette = world.resources.acquire(0x3F)
        super().__init__("radial_95f1", source.x, source.y, palette,
                         0x417E, death_effect="e7ae")
        self.collision_table = 0x4196

    def player_contact(self, _world: "M72EnemyWorld") -> None:
        self.alive = False
        self.destroyed = True

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self._integrate()
        phase = world.frame_counter & 6
        self.descriptor = 0x417E + phase * 3
        if world.frame_counter & 1:
            foreground, background = world.collision_at(self.x, self.y)
            if foreground < 0x0DFC or background < 0x07D0:
                self.alive = False
                self.destroyed = True
                return
            if (self.x < 0x012C or self.x >= 0x02D4 or
                    self.y < 0x007C or self.y >= 0x0194):
                self.alive = False


class Multipart915BChild(Enemy):
    """All six linked part states `$9246…$957C`."""

    INITIALIZERS = {
        0x9246: ("first", 0x40, 0x419E),
        0x92C3: ("second", 0x40, 0x41FE),
        0x933C: ("main", 0x3F, 0x425E),
        0x9477: ("late", 0x40, 0x419E),
        0x94E1: ("terminal", 0x40, 0x41FE),
    }

    def __init__(self, world: "M72EnemyWorld",
                 parent: Multipart915BParent, initializer: int,
                 priority: int, cleanup_counter: int,
                 previous: "Multipart915BChild | None") -> None:
        try:
            state, resource_type, descriptor = self.INITIALIZERS[initializer]
        except KeyError as error:
            raise ValueError(
                f"неизвестный `$915B` initializer ${initializer:04X}") from error
        self.root = parent
        self.previous = previous
        self.state = state
        self.priority = priority
        self.cleanup_counter = cleanup_counter
        self.motion = ScriptedMotion(world.rom, parent.motion_root, 2)
        self.motion.phase = 0
        self.pulse_timer = parent.base_timer + 0x28
        self.pulse_reload = parent.base_timer
        self.pulse = 0
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(resource_type)
        super().__init__("multipart_915b_child", parent.x, parent.y,
                         palette, descriptor, hp=0x7FFF,
                         death_effect="e7b6")
        self.collision_table = 0x427C
        self.shootable = False

    @property
    def active_palette(self) -> int:
        if self.root.controller_flash:
            return self.flash_palette
        return self.palette

    def _controller_cleanup(self) -> None:
        if self.root.controller_handler != 0xA523:
            return
        self.cleanup_counter = _u16(self.cleanup_counter - 1)
        if self.cleanup_counter == 0:
            self.alive = False
            self.destroyed = True

    def _motion(self, world: "M72EnemyWorld") -> bool:
        if self.motion.update(world.rom, self):
            self.alive = False
            return False
        return True

    def _render_phase(self, base: int, phase: int | None = None) -> None:
        if phase is None:
            phase = self.motion.phase
        self.descriptor = base + phase * 6

    def _spawn_radial(self, world: "M72EnemyWorld") -> None:
        table = 0x414E if world.difficulty else 0x411E
        for index in range(8):
            world.pending.append(Radial95F1(world, self, table + index * 6))

    def player_contact(self, world: "M72EnemyWorld") -> None:
        if self.state != "main":
            return
        world.pending.append(ExplosionEffect(world, self.x, self.y, "e7be"))
        self.state = "hit"

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        # The shared renderer `$957C` flashes only while the owning Stage 2
        # controller is in `$A3B3`; parity is applied by active_palette below.
        self.root.controller_handler = world.stage_controller_handler
        self.root.controller_flash = (
            world.stage_controller_handler == 0xA3B3 and
            bool(world.frame_counter & 1))
        if not self._motion(world):
            return
        if self.state == "first":
            self.pulse = 0
            self.pulse_timer -= 1
            if self.pulse_timer == 0:
                self.pulse_timer = self.pulse_reload
                self.pulse = (world.rng.next() & 3) + 1
            self._render_phase(0x419E)
        elif self.state == "second":
            self.pulse = (self.previous.pulse
                          if self.previous is not None and
                          self.previous.state == "first" else 0)
            self._render_phase(0x41FE)
        elif self.state == "main":
            value = ((self.previous.pulse - 1)
                     if self.previous is not None else -1)
            if value == 0 and self.previous is not None and self.previous.state in (
                    "main", "hit", "second"):
                player_x, player_y = world.player_native
                distance = abs(player_x - self.x) + abs(player_y - self.y)
                if distance >= 0x90:
                    self._spawn_radial(world)
                    value = 0
            self.pulse = _u16(value)
            phase = (world.frame_counter & 0x18) >> 3
            self._render_phase(0x425E, phase)
        elif self.state == "hit":
            value = ((self.previous.pulse - 1)
                     if self.previous is not None else -1)
            self.pulse = 1 if value == 0 else _u16(value)
            self.descriptor = 0x4276
        elif self.state == "late":
            phase = (self.motion.phase + 8) & 0x0F
            self._render_phase(0x419E, phase)
        else:
            phase = (self.motion.phase + 8) & 0x0F
            self._render_phase(0x41FE, phase)
        self._controller_cleanup()


class MultipartA71DController(Enemy):
    """Stage 5 three-body synchronization controller `$A71D…$A9C1`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        player_x, player_y = world.player_native
        self.selector = ((world.rng.next() + player_y + player_x) & 7) * 8
        self.completed_mask = 0
        self.arrived_mask = 0
        self.advance_signal = False
        self.state = "spawn"
        self.exit_timer = 0
        self.done = False
        self.bodies: list[MultipartA71DBody] = []
        super().__init__("multipart_a71d_controller", 0, 0, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def _spawn(self, world: "M72EnemyWorld") -> None:
        for index, (bit, kind) in enumerate(((1, "upper"),
                                             (2, "middle"),
                                             (4, "lower"))):
            route_list = world.rom.word(
                0x5ABA + self.selector + index * 2)
            body = MultipartA71DBody(world, self, kind, bit, route_list)
            self.bodies.append(body)
            world.pending.append(body)
            if kind == "middle":
                world.pending.append(AttachedAC4C(
                    world, body, "middle", -0x20, -0x28, 3))
                world.pending.append(AttachedAC4C(
                    world, body, "middle", -0x18, -0x40, 4))
            elif kind == "lower":
                world.pending.append(AttachedAC4C(
                    world, body, "lower", -0x48, 0x18, 3))
        self.state = "active"

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.state == "spawn":
            self._spawn(world)
            return
        if self.state == "active":
            self.advance_signal = False
            if (self.completed_mask | self.arrived_mask) == 7:
                self.advance_signal = True
                self.arrived_mask = 0
            if (self.completed_mask & 7) == 7:
                self.state = "exit"
                self.exit_timer = 0x0100
            return
        self.exit_timer -= 1
        if self.exit_timer == 0:
            self.done = True
            self.alive = False


class AttachedAC4C(Enemy):
    """Aimed attached component `$AC4C` following middle/lower body."""

    def __init__(self, world: "M72EnemyWorld", source: "MultipartA71DBody",
                 expected_kind: str, dx: int, dy: int,
                 fire_index: int) -> None:
        self.source = source
        self.expected_kind = expected_kind
        self.dx = dx
        self.dy = dy
        table = 0x8E10 + fire_index * 6 + world.difficulty * 0x60
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        mask = _u16(self.fire_a - 1)
        self.fire_counter = (world.rng.next() * 4) & mask
        self.orientation = 0
        self.alt_palette = world.resources.acquire(0x53)
        palette = world.resources.acquire(0x42)
        super().__init__("attached_ac4c", _u16(source.x + dx),
                         _u16(source.y + dy), palette, 0x58C2,
                         shootable=False, death_effect="e7be")
        self.hostile = False

    @property
    def active_palette(self) -> int:
        return (self.alt_palette if self.source.flash_visible and
                (self.source.world_frame & 4) else self.palette)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if not self.source.alive or self.source.state != "active":
            self.alive = False
            self.destroyed = True
            return
        if self.orientation:
            _run_f63a(world, self)
        self.x = _u16(self.source.x + self.dx)
        self.y = _u16(self.source.y + self.dy)
        direction = _direction_offset(self.x, self.y, *world.player_native)
        self.orientation = world.rom.word(0x5870 + direction)
        self.descriptor = world.rom.word(0x5872 + direction)


class DebrisAEFB(Enemy):
    """Ballistic paired debris chain `$AEFB/$AF6F`."""

    def __init__(self, world: "M72EnemyWorld", source: Enemy,
                 x_offset: int, phase_index: int) -> None:
        self.x_fraction = self.y_fraction = 0
        self.x_velocity = 0
        self.y_velocity = 0
        self.gravity = 0x10
        self.phase_offset = (phase_index & 3) * 6
        self.state = "paired"
        palette = world.resources.acquire(0x56)
        super().__init__("debris_aefb", _u16(source.x + x_offset),
                         _u16(source.y + 0x38), palette, 0x58CE,
                         shootable=False, death_effect=None)
        random = world.rng.next()
        magnitude = ((random >> 8) & 0xFF) + 0x80
        self.x_velocity = -magnitude if random & 0x20 else magnitude
        self.y_velocity = ((world.rng.next() >> 8) & 0x1FF) + 0x280
        self.collision_table = 0x58E6

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def player_contact(self, _world: "M72EnemyWorld") -> None:
        self.alive = False

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self._integrate()
        self.descriptor = 0x58CE + self.phase_offset
        foreground, background = world.collision_at(self.x, self.y)
        if (foreground < 0x0DFC or background < 0x07D0 or
                self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False
            return
        self.y_velocity = _signed_word(_u16(self.y_velocity - self.gravity))
        if self.state == "paired" and self.y_velocity < 0:
            self.y_velocity = 0
            self.state = "falling"


class MultipartA71DBody(Enemy):
    """Upper/middle/lower body states `$AA0F/$AB62/$ACE7`."""

    CONFIG = {
        "upper": (1, 0x5A02, (0x5A26, 0x5A2E, 0x5A36, 0x5A3E),
                  0x58EE),
        "middle": (2, 0x5A46, (0x5A6A, 0x5A72, 0x5A7A), 0x594E),
        "lower": (4, 0x5A82, (0x5A9A, 0x5AA2, 0x5AAA, 0x5AB2),
                  0x59A6),
    }

    def __init__(self, world: "M72EnemyWorld",
                 controller: MultipartA71DController,
                 kind: str, bit: int, route_list: int) -> None:
        self.controller = controller
        self.body_kind = kind
        self.bit, self.render_root, collisions, self.debris_root = (
            self.CONFIG[kind])
        self.collision_roots = collisions
        self.route_list = route_list
        self.motion_pointer = world.rom.word(route_list)
        self.x_velocity = _signed_word(world.rom.word(self.motion_pointer))
        self.y_velocity = _signed_word(world.rom.word(self.motion_pointer + 2))
        self.motion_timer = world.rom.word(self.motion_pointer + 4)
        self.x_fraction = self.y_fraction = 0
        self.phase = 0
        self.state = "active"
        self.flash_timer = 0
        self.flash_visible = False
        self.world_frame = 0
        self.fire_reload = world.rom.byte(0x5844 + world.difficulty)
        self.fire_timer = self.fire_reload
        self.alt_palette = world.resources.acquire(0x53)
        palette = world.resources.acquire(0x41)
        super().__init__(f"multipart_a71d_{kind}", 0x0100, 0x0108,
                         palette, self.render_root, hp=0x28,
                         death_effect=None)
        self.collision_table = collisions[-1]
        self.debris_pointer = self.debris_root
        self.debris_timer = 0
        self.pair_timer = 0

    @property
    def active_palette(self) -> int:
        return (self.alt_palette if self.flash_visible and
                (self.world_frame & 4) else self.palette)

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _advance_path(self, world: "M72EnemyWorld") -> None:
        if self.motion_timer:
            self.motion_timer -= 1
            self._integrate()
            return
        self.controller.arrived_mask |= self.bit
        if not self.controller.advance_signal:
            return
        self.motion_pointer += 6
        if world.rom.word(self.motion_pointer) == 0x8000:
            self.route_list += 2
            next_stream = world.rom.word(self.route_list)
            if next_stream == 0:
                self.x_velocity = 0x0200
                self.y_velocity = 0
                self.controller.completed_mask |= self.bit
                self.route_list -= 2
                self.phase += 1
                return
            self.motion_pointer = next_stream
        self.x_velocity = _signed_word(
            _u16(world.rom.word(self.motion_pointer) * 2))
        self.y_velocity = _signed_word(
            _u16(world.rom.word(self.motion_pointer + 2) * 2))
        self.motion_timer = world.rom.word(self.motion_pointer + 4) >> 1

    def _fire_straight(self, world: "M72EnemyWorld",
                       x_offset: int, offsets: int, vertical_span: int) -> None:
        player_x, player_y = world.player_native
        if player_x < self.x:
            return
        delta = _u16(player_y + 0x10 - self.y)
        if delta >= vertical_span:
            return
        self.fire_timer -= 1
        if self.fire_timer:
            return
        self.fire_timer = self.fire_reload
        index = (world.rng.next() & 0x0E)
        y = _u16(self.y + world.rom.word(offsets + index))
        velocity = world.rom.word(0x5848 + world.difficulty * 2)
        world.pending.append(Handler5CEAShot(
            world, _u16(self.x + x_offset), y, velocity))
        world.projectile_spawns += 1

    def _begin_debris(self, world: "M72EnemyWorld") -> None:
        self.controller.completed_mask |= self.bit
        world.resources.release(self.palette)
        world.resources.release(self.alt_palette)
        self.palette = self.alt_palette = 0xFF
        self.shootable = False
        self.hostile = False
        self.state = "debris"
        self.debris_pointer = self.debris_root
        self.debris_timer = 0x40

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        if self.state != "active" or self.phase:
            return
        self.hp -= damage
        self.flash_timer = 0x1F
        if self.hp <= 0:
            self._begin_debris(world)

    def _update_debris(self, world: "M72EnemyWorld") -> None:
        if not (world.frame_counter & 1):
            if not (world.frame_counter & 3):
                world.rng.next()
            effect = "e817" if (world.rng.next() & 6) == 0 else "e7b6"
            dx = _signed_word(world.rom.word(self.debris_pointer))
            dy = _signed_word(world.rom.word(self.debris_pointer + 2))
            world.pending.append(ExplosionEffect(
                world, _u16(self.x + dx), _u16(self.y + dy), effect))
            self.debris_pointer += 4
            if world.rom.word(self.debris_pointer) == 0x8000:
                self.debris_pointer = self.debris_root
        self.debris_timer -= 1
        if self.debris_timer == 0:
            self.alive = False

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.world_frame = world.frame_counter
        if self.state == "debris":
            self._update_debris(world)
            return
        if self.controller.done:
            self.alive = False
            return
        if self.body_kind == "upper" and self.phase == 0:
            self._fire_straight(world, 0x50, 0x5850, 0x50)
        elif self.body_kind == "lower" and self.phase == 0:
            self._fire_straight(world, 0x10, 0x5860, 0x30)
            if self.y < 0x00B8:
                self.pair_timer += 1
                if self.pair_timer < 0x40 and not (self.pair_timer & 0x0F):
                    world.pending.append(DebrisAEFB(world, self, -8, 0))
                    world.pending.append(DebrisAEFB(world, self, -0x28, 1))
            else:
                self.pair_timer = 0
        self._advance_path(world)
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = True
        else:
            self.flash_visible = False
        if self.phase == 0x80:
            self.palette = self.alt_palette = 0xFF
            self.hostile = False


class BossB7FBController(Enemy):
    """Stage 7 late-boss root `$B7FB/$B805/$B8D5/$B950`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        self.timer = 0
        self.defeated = False
        self.exit_timer = 0
        self.state = "active"
        self.parts: list[Enemy] = []
        super().__init__("boss_b7fb_controller", 0, 0, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None
        x, threshold = 0x02D0, 0x03C0
        for _ in range(5):
            part = BossB7FBSegment(world, self, x, threshold)
            self.parts.append(part)
            world.pending.append(part)
            x += 0x40
            threshold -= 0x20
        for part in (BossB7FBRandomSpawner(world, self),
                     BossB7FBMissileSpawner(world, self),
                     BossB7FBCore(world, self)):
            self.parts.append(part)
            world.pending.append(part)

    def _open_terrain(self, world: "M72EnemyWorld") -> None:
        for index in range(0x80):
            address = 0x1002 + index * 4
            code, attribute = world.terrain_cell(address)
            world.replace_terrain(address, code, attribute | 0x80)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.state == "active":
            self.timer += 1
            if self.timer == 0x0300:
                self._open_terrain(world)
            if self.timer >= 0x1120:
                self.defeated = True
            if self.timer == 0x1160 or self.defeated:
                self.state = "exit"
                self.exit_timer = 0x00C0
        else:
            self.exit_timer -= 1
            if self.exit_timer == 0:
                self.alive = False


class BossB7FBSegment(Enemy):
    """One of five scrolling armour segments `$B997/$B9FD`."""

    def __init__(self, world: "M72EnemyWorld", root: BossB7FBController,
                 x: int, threshold: int) -> None:
        self.root = root
        self.threshold = threshold
        self.timer = 0
        self.reverse = False
        palette = world.resources.acquire(0x2F)
        super().__init__("boss_b7fb_segment", x, 0x0160, palette,
                         0x60E6, hp=0x7FFF, death_effect=None)
        self.damage_accumulator = 0
        self.collision_table = 0x6116

    def _select_descriptor(self) -> None:
        delta = self.timer - self.threshold
        if not self.reverse:
            self.descriptor = (0x60E6 if delta < 0 else
                               0x60F2 if delta < 0x10 else
                               0x60FE if delta < 0x20 else 0x610A)
        else:
            self.descriptor = (0x610A if delta < 0x10 else
                               0x60FE if delta < 0x20 else
                               0x60F2 if delta < 0x30 else 0x60E6)

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        # `$B9DC/$F75F` only accumulates the byte up to `$A0`; `$B997`
        # deliberately does not branch on it.  Armour retreats only when the
        # owning controller flag changes, so a segment cannot kill the boss.
        self.damage_accumulator = min(0xA0,
                                      self.damage_accumulator + damage)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        self.timer += 1
        self._select_descriptor()
        if self.root.defeated and not self.reverse:
            self.reverse = True
            self.timer = 0
        if self.reverse and self.x < 0x0120:
            self.alive = False


class BossB7FBRandomChild(Enemy):
    """Shared `$BC95` runtime for the `$612C` randomized constructors."""

    ROOTS = {
        0xBB40: (0x616C, 0x6244, 0x5F, 1, False),
        0xBB72: (0x6178, 0x6244, 0x5F, 1, False),
        0xBB7E: (0x6184, 0x6244, 0x5F, 1, False),
        0xBB8A: (0x6190, 0x6244, 0x5F, 1, False),
        0xBB96: (0x619C, 0x6244, 0x5F, 1, False),
        0xBBA2: (0x61A8, 0x6244, 0x5F, 1, False),
        0xBBAE: (0x61B4, 0x6254, 0x5F, 0x0C, False),
        0xBBC3: (0x61C0, 0x6244, 0x0F, 1, False),
        0xBC08: (0x61CC, 0x6244, 0x44, 1, True),
        0xBC31: (0x622C, 0x624C, 0x0C, 1, False),
        0xBC63: (0x6238, 0x6244, 0x2E, 1, False),
    }

    def __init__(self, world: "M72EnemyWorld", root: BossB7FBController,
                 handler: int, x: int, y: int, y_velocity: int) -> None:
        descriptor, collision, resource_type, hp, animated = self.ROOTS[handler]
        if handler in (0xBB40, 0xBC31, 0xBC63) and world.rng.next() & 2:
            descriptor += 6
        self.root = root
        self.y_velocity = y_velocity
        self.y_fraction = 0
        self.animated = animated
        palette = world.resources.acquire(resource_type)
        super().__init__("boss_b7fb_random_child", x, y, palette,
                         descriptor, hp=hp, death_effect="e7be")
        self.collision_table = collision

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        if self.animated:
            phase = ((world.frame_counter & 0x3C) * 3) >> 1
            self.descriptor = 0x61CC + phase
        if self.root.defeated or self.y < 0x00B0:
            self.alive = False


class BossB7FBRandomSpawner(Enemy):
    """Difficulty ramp and random constructor table `$BAA7`."""

    def __init__(self, world: "M72EnemyWorld",
                 root: BossB7FBController) -> None:
        self.root = root
        self.timer = 0
        self.x_pointer = 0x611E
        self.cadence = self.reload = self.ramp_timer = 0x20
        super().__init__("boss_b7fb_random_spawner", 0, 0, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.root.defeated:
            self.alive = False
            return
        self.timer += 1
        if self.timer < 0x0360:
            return
        self.ramp_timer -= 1
        if self.ramp_timer == 0:
            self.ramp_timer = 0x40
            self.cadence = max(8, self.cadence - 1)
        self.reload -= 1
        if self.reload:
            return
        self.reload = self.cadence
        handler = world.rom.word(0x612C + (world.rng.next() & 0x3E))
        x = world.rom.word(self.x_pointer)
        self.x_pointer += 2
        if world.rom.word(self.x_pointer) == 0x8000:
            self.x_pointer = 0x611E
        velocity = -_signed_word(0x0400 - self.cadence * 0x10)
        world.pending.append(BossB7FBRandomChild(
            world, self.root, handler, x, 0x0168, velocity))


class BossB7FBMissile(Enemy):
    """Vertical tracking missile `$BDB2/$BE43`."""

    def __init__(self, world: "M72EnemyWorld", root: BossB7FBController,
                 x: int) -> None:
        self.root = root
        self.timer = 0
        self.y_fraction = 0
        self.projectile_script = 0x9010
        palette = world.resources.acquire(0x21)
        super().__init__("boss_b7fb_missile", x, 0x0090, palette,
                         0x62FE, hp=2, death_effect="e7be")
        self.collision_table = 0x630A

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.root.defeated:
            self.alive = False
            return
        if self.timer >= 0xC0:
            self.y = _u16(self.y - 1)
        elif self.timer < 0x40:
            self.y = _u16(self.y + 1)
        if self.timer in (0x60, 0xA0):
            world.note_projectile_spawn(self)
        direction = _direction_offset(self.x, self.y, *world.player_native)
        self.descriptor = world.rom.word(0x625C + (direction >> 1))
        self.timer += 1
        if self.timer == 0x0100:
            self.alive = False


class BossB7FBMissileSpawner(Enemy):
    """Cyclic X-command launcher `$BD32`."""

    def __init__(self, world: "M72EnemyWorld",
                 root: BossB7FBController) -> None:
        self.root = root
        self.timer = 0
        self.pointer = 0x627C
        super().__init__("boss_b7fb_missile_spawner", 0, 0, 0xFF, 0)
        self.shootable = False
        self.hostile = False
        self.death_effect = None

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.root.defeated:
            self.alive = False
            return
        self.timer += 1
        if self.timer < 0x0360 or self.timer & 0x7F:
            return
        value = world.rom.word(self.pointer)
        self.pointer += 2
        if value != 0x8000:
            world.pending.append(BossB7FBMissile(world, self.root, value))
        if world.rom.word(self.pointer) == 0:
            self.pointer = 0x627C


class BossB7FBCore(Enemy):
    """Main animated core `$BE81/$BFE8`."""

    def __init__(self, world: "M72EnemyWorld",
                 root: BossB7FBController) -> None:
        self.root = root
        self.timer = 0
        self.phase = 0x017F
        self.x_fraction = 0
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(0x54)
        super().__init__("boss_b7fb_core", 0x02E8, 0x0110, palette,
                         0x63E6, hp=0x55, death_effect=None)
        self.collision_table = 0x63BE

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 5
        if not self.alive:
            self.alive = True
            self.destroyed = False
            self.shootable = False
            self.hostile = False
            self.root.defeated = True
            self.state = "exploding"
            self.timer = 0x80
            # `$BFCE…$BFE4`: preserve only palette nibble across 2048 cells.
            for index in range(0x800):
                address = 0x1002 + index * 4
                code, attribute = world.terrain_cell(address)
                world.replace_terrain(address, code, attribute & 0x000F)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if getattr(self, "state", "active") == "exploding":
            if not (world.frame_counter & 3):
                x = (world.rng.next() & 0x1FF) + 0x0140
                value = world.rng.next()
                y = (value & 0x7F) + 0x80 + (0xA0 if value & 0x80 else 0)
                effect = "e817" if value & 0x40 else "e7b6"
                world.pending.append(ExplosionEffect(world, x, y, effect))
            self.timer -= 1
            if self.timer == 0:
                self.alive = False
            return
        self.timer += 1
        if self.timer < 0x0500:
            return
        if self.phase >= 0x0100 and self.root.defeated:
            self.alive = False
            return
        self.phase += 1
        if self.phase >= 0x0180:
            self.phase = 0
            world.pending.append(BossB7FBCoreChild(world, self))
        if self.phase >= 0x0100:
            return
        velocity_index = (self.phase & 0xF0) >> 3
        velocity = _signed_word(world.rom.word(0x631A + velocity_index))
        coordinate = ((self.x << 8) | self.x_fraction) + velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        descriptor_index = (self.phase & 0xF8) >> 2
        self.descriptor = world.rom.word(0x633A + descriptor_index)
        self.collision_table = world.rom.word(0x637C + descriptor_index)
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = bool(world.frame_counter & 1)
        else:
            self.flash_visible = False


class BossB7FBCoreChild(Enemy):
    """Scripted core emission `$C03F/$C069`."""

    def __init__(self, world: "M72EnemyWorld", source: BossB7FBCore) -> None:
        self.motion = ScriptedMotion(world.rom, 0xA7FC, 1)
        self.state = "out"
        descriptor = world.rom.word(0x6312 + (world.rng.next() & 6))
        palette = world.resources.acquire(0x5F)
        super().__init__("boss_b7fb_core_child",
                         _u16(source.x - 0x30), _u16(source.y - 0x18),
                         palette, descriptor, shootable=False,
                         death_effect="e7be")
        self.collision_table = 0x6244

    def player_contact(self, _world: "M72EnemyWorld") -> None:
        self.alive = False
        self.destroyed = True

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.motion.update(world.rom, self):
            if self.state == "out":
                self.state = "return"
                self.motion.commands = 3
            else:
                self.alive = False


class Child8D85(Enemy):
    """Full child chain `$8D85/$8DC6/$8E15` spawned by `$7D68`."""

    def __init__(self, world: "M72EnemyWorld", parent: "Enemy7D68",
                 script: int, x_velocity: int, y_velocity: int) -> None:
        self.motion = ScriptedMotion(world.rom, script, 3)
        self.fire_a = world.rom.word(0x8E10 + 3 * 6)
        self.fire_b = world.rom.word(0x8E12 + 3 * 6)
        self.projectile_script = world.rom.word(0x8E14 + 3 * 6)
        self.fire_counter = ((world.rng.next() * 4) &
                             _u16(self.fire_a - 1))
        self.x_velocity = x_velocity
        self.y_velocity = y_velocity
        self.x_fraction = self.y_fraction = 0
        self.state = "scripted"
        self.timer = 0
        self.animation = 0
        self.target_player_next = False
        self.fixed_descriptor = False
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(0x3E)
        super().__init__("child_8d85", parent.x, parent.y, palette,
                         0x3F26, hp=1)
        self.collision_table = 0x3F6E

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def _begin_terminal(self) -> None:
        self.state = "terminal"
        self.timer = 0x1F
        self.shootable = True

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        if self.state in ("scripted", "terminal"):
            if self.state == "scripted":
                self._begin_terminal()
            return
        super().take_damage(world, damage)
        if self.alive:
            self.flash_timer = 0x0C
            self.x_velocity = 0
            self.y_velocity = -0x0300
            delta = _u16(self.y - 0x00B0)
            if delta < 0x8000:
                self.fixed_descriptor = True
                self.timer = (delta >> 1) + 1
            else:
                self.y_velocity = 0
                self.timer = 1

    def _choose_active_target(self, world: "M72EnemyWorld") -> None:
        self.fixed_descriptor = False
        if self.target_player_next:
            target_x, target_y = world.player_native
            self.target_player_next = False
        else:
            index = world.rng.next() & 0x0F
            if index < 4:
                self.target_player_next = True
            target_x = world.rom.word(0x3EE6 + index * 4)
            target_y = world.rom.word(0x3EE8 + index * 4)
        self.x_velocity = _signed_word(_u16(target_x - self.x) * 2 & 0xFFFF)
        self.y_velocity = _signed_word(_u16(target_y - self.y) * 2 & 0xFFFF)
        self.timer = 0x80

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "scripted":
            if self.motion.update(world.rom, self):
                self._begin_terminal()
                return
            self.x = _u16(self.x + foreground_delta)
            phase = ((world.frame_counter + self.motion.phase) & 0x0C) >> 2
            self.descriptor = 0x3F26 + phase * 6
            return
        if self.state == "terminal":
            phase = (self.timer & 0x18) >> 3
            self.descriptor = 0x3F3E + phase * 6
            self.timer -= 1
            if self.timer == 0:
                self.state = "active"
                self.hp = 4
                self.timer = 1
            return

        self.timer -= 1
        if self.timer == 0:
            self._choose_active_target(world)
        self._integrate()
        if self.fixed_descriptor:
            self.descriptor = 0x3F56
        else:
            phase = ((world.frame_counter + self.motion.phase) & 0x18) >> 3
            self.descriptor = 0x3F56 + phase * 6
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False
        if (self.x < 0x012C or self.x >= 0x02D4 or
                self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class Enemy7D68(Enemy):
    """Literal six-state Stage 2 object `$7D68…$7FAD`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        variant = command & 1
        self.variant = world.rom.word(0x37E0 + variant * 4)
        y = world.rom.word(0x37DE + variant * 4)
        self.state = "approach"
        self.timer = 0
        self.animation_seed = _u16(world.rng.next() + world.frame_counter)
        self.flash_timer = 0
        self.flash_visible = False
        self.flash_palette = world.resources.acquire(0x55)
        palette = world.resources.acquire(0x29)
        super().__init__("enemy_7d68", 0x02D0, y, palette,
                         0x37E6 + self.variant * 12,
                         hp=0x28, death_effect="e817")
        self.collision_table = 0x3846 + self.variant * 8

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        super().take_damage(world, damage)
        self.flash_timer = 0x10

    def _spawn_child(self, world: "M72EnemyWorld") -> None:
        if self.variant:
            choices = {0xC0: (0xA484, -0x0020, -0x0028),
                       0x80: (0xA4B8, -0x0018, -0x0040)}
        else:
            choices = {0xC0: (0xA434, -0x0020, -0x0028),
                       0x80: (0xA45A, -0x0018, -0x0040)}
        values = choices.get(self.timer)
        if values is None:
            return
        script, vx, vy = values
        world.pending.append(Child8D85(world, self, script, vx, vy))

    def _base_descriptor(self) -> int:
        return 0x37E6 + self.variant * 12

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        self.x = _u16(self.x + foreground_delta)
        base = self._base_descriptor()
        if self.state == "approach":
            self.descriptor = base
            if self.x < 0x0270:
                self.state = "rise"
                self.timer = 8
        elif self.state == "rise":
            self.y = _u16(self.y + self.variant * 4 - 2)
            self.descriptor = base
            self.timer -= 1
            if self.timer == 0:
                self.state = "open"
                self.timer = 0x3F
        elif self.state == "open":
            offset = ((-self.timer) & 0x30)
            self.descriptor = base + offset + (offset >> 1)
            self.timer -= 1
            if self.timer == 0:
                self.state = "hold"
                self.timer = 0xC0
        elif self.state == "hold":
            self.descriptor = 0x382E + self.variant * 12
            self._spawn_child(world)
            self.timer -= 1
            if self.timer == 0:
                self.state = "close"
                self.timer = 0x3F
        elif self.state == "close":
            offset = self.timer & 0x30
            self.descriptor = base + offset + (offset >> 1)
            self.timer -= 1
            if self.timer == 0:
                self.state = "retreat"
        else:
            self.descriptor = base

        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False
        if self.state == "retreat" and self.x < 0x0130:
            self.alive = False


def read_descriptor(rom: M72Rom, address: int) -> SpriteDescriptor:
    return SpriteDescriptor(
        _s8(rom.byte(address)), _s8(rom.byte(address + 1)),
        rom.word(address + 2), rom.word(address + 4))


class LargeTerrainChild780E(Enemy):
    """Ballistic child allocated by parent helper `$77C1`, runtime `$780E`."""

    @staticmethod
    def _swapped(value: int) -> int:
        return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)

    def __init__(self, world: "M72EnemyWorld",
                 parent: "LargeTerrain74B4") -> None:
        palette = world.resources.acquire(0x2C)
        vertical_random = self._swapped(world.rng.next())
        horizontal_random = self._swapped(world.rng.next())
        self.x_velocity = (horizontal_random & 0xFF) + 0x00C0
        if parent.shoot_descriptor_base == 0x33DE:
            self.x_velocity = -self.x_velocity
        self.y_velocity = (vertical_random & 0x01FF) + 0x0280
        # `$03A6` binding below replaces these with the recycled slot's
        # preserved `+$03/+$07` bytes before the first `$780E` pass.
        self.x_fraction = 0
        self.y_fraction = 0
        self.ballistic_state = "rise"
        super().__init__("large_terrain_child_780e", parent.x,
                         _u16(parent.y + 0x10), palette, 0x343A,
                         score_pointer=None, scheduler_priority=0xC000,
                         inherit_slot_fractions=True)
        self.collision_table = 0x34A6
        self.death_effect = "e7ae"

    def _move(self) -> None:
        # `$0672/$0689` integrate signed Q8 words.  The upward half of the
        # trajectory stores Y velocity as `$FFF0,$FFE0,...`; adding that word
        # as an unsigned Python integer moves the child down by 255 pixels and
        # makes `$1D6B` delete it on the first falling VBlank.
        coordinate = (((self.x << 8) | self.x_fraction) +
                      _signed_word(self.x_velocity & 0xFFFF))
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = (((self.y << 8) | self.y_fraction) +
                      _signed_word(self.y_velocity & 0xFFFF))
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _begin_explosion(self, world: "M72EnemyWorld") -> None:
        """Execute the in-place `$7875 -> $E7AE` handler transition.

        ROM keeps the same 64-byte object record: resource `$2C` is released,
        resource `$01` is acquired, and only the handler/animation fields are
        replaced.  Allocating a separate Python effect would incorrectly
        return this slot to the `$03A6/$03EC` FIFO for the duration of the
        explosion.
        """
        world.resources.release(self.palette)
        self.palette = world.resources.acquire(0x01)
        self.ballistic_state = "explosion"
        self.explosion_pointer = 0x8552
        self.explosion_timer = 2
        self.shootable = False
        self.hostile = False
        self.weapon_vulnerable = False
        self.death_effect = None

    def _update_explosion(self, world: "M72EnemyWorld",
                          foreground_delta: int) -> None:
        # Common player `$E7D4`: scroll, draw current descriptor, decrement
        # the byte timer, then advance to the next `(duration,descriptor)`
        # record.  A zero duration releases resource `$01` and the same slot.
        self.x = _u16(self.x + foreground_delta)
        self.descriptor = world.rom.word(self.explosion_pointer + 2)
        self.explosion_timer -= 1
        if self.explosion_timer:
            return
        self.explosion_pointer = _u16(self.explosion_pointer + 4)
        duration = world.rom.word(self.explosion_pointer)
        if duration == 0:
            self.alive = False
            return
        self.explosion_timer = duration & 0xFF

    def take_damage(self, world: "M72EnemyWorld", _damage: int) -> None:
        if self.ballistic_state != "explosion":
            self.destroyed = True
            self._begin_explosion(world)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.ballistic_state == "explosion":
            self._update_explosion(world, foreground_delta)
            return
        self._move()
        if self.ballistic_state == "rise":
            if self.y_velocity >= 0x0240:
                descriptor = 0x343A
            elif self.y_velocity >= 0x0180:
                descriptor = 0x3446
            elif self.y_velocity >= 0x0100:
                descriptor = 0x3452
            else:
                descriptor = 0x345E
            if self.x_velocity >= 0:
                descriptor += 6
            self.descriptor = descriptor

            if world.terrain_at(self.x, self.y) < 0x0DFC:
                self._begin_explosion(world)
                return
            if not (0x012C <= self.x < 0x02D4 and
                    0x007C <= self.y < 0x0194):
                self.alive = False
                return
            old_velocity = self.y_velocity
            self.y_velocity = _u16(self.y_velocity - 0x10)
            if old_velocity < 0x10:
                self.y_velocity = 0
                self.ballistic_state = "fall"
            return

        self.y_velocity = _u16(self.y_velocity - 0x10)
        # `$789D` chooses the falling frame after subtracting `$0010` from
        # the signed Q8 velocity.  Comparing the pre-subtraction value shifts
        # every descriptor transition by one VBlank.
        if self.y_velocity < 0xFDC0:
            descriptor = 0x346A
        elif self.y_velocity < 0xFE80:
            descriptor = 0x3476
        elif self.y_velocity < 0xFF00:
            descriptor = 0x3482
        elif self.y_velocity < 0xFF80:
            descriptor = 0x348E
        else:
            descriptor = 0x349A
        if self.x_velocity >= 0:
            descriptor += 6
        self.descriptor = descriptor
        if world.terrain_at(self.x, self.y) < 0x0DFC:
            self._begin_explosion(world)
            return
        if not (0x012C <= self.x < 0x02D4 and
                0x007C <= self.y < 0x0194):
            self.alive = False


class LargeTerrain74B4(Enemy):
    """Literal parent state chain `$7607,$7502,$759F,$7654,$76AC,$7719`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = _u16(world.rom.word(0x8DD2 + index * 4) - 8)
        palette = world.resources.acquire(0x2B)
        self.flash_palette = world.resources.acquire(0x55)
        self.cooldown_reload = world.rom.word(0x3346 + world.difficulty * 2)
        self.cooldown = self.cooldown_reload
        self.state_timer = 0x20
        self.animation = 0x80
        self.x_velocity = 0
        self.x_fraction = 0
        self.state = "bootstrap"
        self.open_descriptor_base = 0x33AE
        self.shoot_descriptor_base = 0x33DE
        self.flash_timer = 0
        self.flash_visible = False
        super().__init__("large_terrain_74b4", x, y, palette, 0x334E,
                         hp=6, score_pointer=0x86F8,
                         scheduler_priority=0x8230,
                         # `$74B4/$7607` never clears record byte `+$03`;
                         # every later `$0672` step begins with the pool
                         # slot's previous Q8 residue.
                         inherit_slot_fractions=True)
        self.collision_table = 0x3426

    def _inside_bounds(self) -> bool:
        return (0x012C <= self.x < 0x02D4 and
                0x007C <= self.y < 0x0194)

    def _choose_direction(self, world: "M72EnemyWorld") -> None:
        player_x, _player_y = world.player_native
        if player_x >= self.x:
            self.x_velocity = 0x0200
            self.state = "move"
        else:
            distance = self.x - player_x
            if distance <= 0x68:
                self.x_velocity = 0x0200
                self.state = "move"
            elif distance <= 0x7C:
                # `$7617` deliberately preserves the previous velocity.
                self.state = "wait"
            else:
                self.x_velocity = -0x0180
                self.state = "move"
        self.state_timer = 8

    def _begin_open(self, world: "M72EnemyWorld") -> None:
        self.state_timer = 0x1F
        self.state = "open"
        self.open_descriptor_base = 0x33AE
        self.shoot_descriptor_base = 0x33DE
        if world.player_native[0] >= self.x:
            self.open_descriptor_base = 0x33C6
            self.shoot_descriptor_base = 0x3402

    def _draw_move_descriptor(self, phased: bool) -> None:
        descriptor = 0x337E if self.x_velocity < 0 else 0x334E
        if phased:
            phase = self.animation & 0x1C
            descriptor += phase + (phase >> 1)
        self.descriptor = descriptor

    def _spawn_child(self, world: "M72EnemyWorld") -> None:
        object_slot = world.object_pool.take()
        if object_slot is None:
            world.allocation_failures.append(
                (world.frame_counter, "large_terrain_child_780e"))
            return
        child = LargeTerrainChild780E(world, self)
        world.object_pool.bind(child, object_slot)
        # Parent priority `$8230`, child priority `$C000`: `pending.append`
        # reaches the new runtime handler later in this same scheduler pass.
        world.pending.append(child)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False

        if self.state == "bootstrap":
            self.x_velocity = -0x0180
            self.state_timer = 8
            self.state = "move"
            return

        self.x = _u16(self.x + foreground_delta)

        if self.state == "move":
            self._draw_move_descriptor(phased=True)
            ahead = 0x10 if self.x_velocity >= 0 else -0x10
            if world.terrain_at(
                    _u16(self.x + ahead), _u16(self.y - 0x0C)) < 0x0DFC:
                self.state = "wait"
                self.state_timer = 8
                return
            coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
            self.x = _u16(coordinate >> 8)
            self.x_fraction = coordinate & 0xFF
            if not self._inside_bounds():
                self.alive = False
                return
            self.animation = _u16(self.animation + 1)
            self.cooldown = _u16(self.cooldown - 1)
            if self.cooldown == 0:
                self.cooldown = self.cooldown_reload
                self._begin_open(world)
                return
            self.state_timer = _u16(self.state_timer - 1)
            if self.state_timer == 0:
                self._choose_direction(world)
            return

        if self.state == "wait":
            self._draw_move_descriptor(phased=False)
            self.animation = _u16(self.animation + 1)
            self.cooldown = _u16(self.cooldown - 1)
            if self.cooldown == 0:
                self.cooldown = self.cooldown_reload
                self._begin_open(world)
                return
            self.state_timer = _u16(self.state_timer - 1)
            if self.state_timer == 0:
                self._choose_direction(world)
            return

        if self.state == "open":
            phase = self.state_timer & 0x18
            self.descriptor = (self.open_descriptor_base +
                               (phase >> 1) + (phase >> 2))
            if not self._inside_bounds():
                self.alive = False
                return
            self.animation = _u16(self.animation + 1)
            self.state_timer = _u16(self.state_timer - 1)
            if self.state_timer == 0:
                self.state = "shoot"
            return

        if self.state == "shoot":
            self.animation = _u16(self.animation + 1)
            self.descriptor = self.shoot_descriptor_base
            if self.animation & 8:
                self.descriptor += 6
            if (self.animation & 0x0F) == 0:
                self._spawn_child(world)
            if not self._inside_bounds():
                self.alive = False
                return
            self.state_timer = _u16(self.state_timer + 1)
            if self.state_timer >= 0x80:
                self.state_timer = 0x1F
                self.open_descriptor_base = self.shoot_descriptor_base + 0x0C
                self.state = "close"
            return

        phase = self.state_timer & 0x18
        self.descriptor = (self.open_descriptor_base +
                           (phase >> 1) + (phase >> 2))
        if not self._inside_bounds():
            self.alive = False
            return
        self.animation = _u16(self.animation + 1)
        self.state_timer = _u16(self.state_timer - 1)
        if self.state_timer == 0:
            self._choose_direction(world)

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        # `$7737` stores $0C; draw helper `$779E` decrements before selecting
        # the alternate resource slot on counter values 8, 4 and 0.
        super().take_damage(world, damage)
        self.flash_timer = 0x0C


class Animated86A6(Enemy):
    """Stationary direction-facing shooter `$86A6/$86D3/$86EA`."""

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        y = world.rom.word(0x930C + (command & 7) * 2)
        palette = world.resources.acquire(0x10)
        fire_index = (command & 0xF0) >> 4
        fire_table = 0x8E10 + fire_index * 6
        self.fire_a = world.rom.word(fire_table)
        self.fire_b = world.rom.word(fire_table + 2)
        self.projectile_script = world.rom.word(fire_table + 4)
        mask = _u16(self.fire_a - 1)
        self.fire_counter = (world.rng.next() * 4) & mask
        self.descriptor_base = 0x3A96 if y & 0x0100 else 0x3A36
        direction = _direction_offset(0x02C8, y, *world.player_native)
        descriptor = self.descriptor_base + direction + (direction >> 1)
        super().__init__("animated_86a6", 0x02C8, y, palette, descriptor,
                         score_pointer=0x86E8,
                         scheduler_priority=0x8020)
        self.collision_table = 0x3AF6

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        _run_f63a(world, self)
        self.x = _u16(self.x + foreground_delta)
        if (world.frame_counter & 0x0F) == 0:
            direction = _direction_offset(
                self.x, self.y, *world.player_native)
            self.descriptor = (self.descriptor_base + direction +
                               (direction >> 1))
        if self.x < 0x0140:
            self.alive = False


class Handler60BAProjectile(Enemy):
    """Horizontal projectile created by `$663E`, handler `$66C8`."""

    def __init__(self, world: "M72EnemyWorld", source: "Handler60BA") -> None:
        self.x_fraction = 0
        if source.facing_right:
            self.x_velocity = _signed_word(world.rom.word(0x2B48))
            descriptor = 0x2C7E
        else:
            self.x_velocity = -_signed_word(world.rom.word(0x2B50))
            descriptor = 0x2C78
        palette = world.resources.acquire(0x21)
        super().__init__("handler_60ba_projectile", source.x,
                         _u16(source.y + 0x0A), palette, descriptor,
                         collision_table=0x2C84,
                         scheduler_priority=0x6000)
        # `$6688/$6694` overwrite only integer coordinates.  The allocator
        # does not clear byte `+$03`, so X Q8 integration at `$66C8/$0672`
        # begins with the previous owner's residue in this pool record.
        self.inherit_slot_fractions = True
        self.death_effect = "e7ae"
        self.start_delay = 0
        self.state = "flight"
        self.explosion_initialized = False
        self.sequence_pointer = 0
        self.sequence_timer = 0

    def _begin_explosion(self, world: "M72EnemyWorld") -> None:
        # Terrain/weapon carry at `$66F4` does not release the object record.
        # It releases type `$21`, sends `$50`, and installs `$E7AE` in this
        # same slot.  `$E7AE` acquires type `$01` on the following pass.
        world.resources.release(self.palette)
        self.palette = 0xFF
        world.sound_commands.append(0x50)
        self.state = "explosion"
        self.explosion_initialized = False
        self.sequence_pointer = 0x8552
        self.sequence_timer = 2
        self.shootable = False
        self.hostile = False
        self.weapon_vulnerable = False
        self.death_effect = None
        self.destroyed = False

    def _update_explosion(self, world: "M72EnemyWorld",
                          foreground_delta: int) -> None:
        if not self.explosion_initialized:
            self.palette = world.resources.acquire(0x01)
            self.explosion_initialized = True
        self.x = _u16(self.x + foreground_delta)
        self.descriptor = world.rom.word(self.sequence_pointer + 2)
        self.sequence_timer -= 1
        if self.sequence_timer:
            return
        self.sequence_pointer += 4
        duration = world.rom.word(self.sequence_pointer)
        if duration == 0:
            self.alive = False
            return
        self.sequence_timer = duration & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "explosion":
            self._update_explosion(world, foreground_delta)
            return
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        if world.terrain_at(self.x, self.y) < 0x0DFC:
            self._begin_explosion(world)
        elif self.x < 0x012C or self.x >= 0x02D4:
            # `$6708`: leaving `$1D6B` bounds releases immediately, without
            # installing the explosion handler.
            self.death_effect = None
            self.alive = False

    def take_damage(self, world: "M72EnemyWorld", _damage: int) -> None:
        if self.state == "flight":
            self._begin_explosion(world)


class Handler60BAChild(Enemy):
    """One of four orbiting/homing children emitted by `$6715/$67D5`."""

    def __init__(self, world: "M72EnemyWorld", source: "Handler60BA",
                 table: int) -> None:
        self.x_velocity = _signed_word(world.rom.word(table))
        self.y_velocity = _signed_word(world.rom.word(table + 2))
        self.direction = world.rom.word(table + 4) & 0x0F
        # `$67B3…$67C2` mirrors every vector when the parent is left of R-9:
        # both horizontal Q8 velocity and the descriptor/sector word change.
        # Omitting this swapped the trajectories (and therefore terrain-hit
        # lifetimes) of equal-frame children while hiding behind an otherwise
        # correct FIFO allocation stream.
        if source.x < world.player_native[0]:
            self.x_velocity = -self.x_velocity
            self.direction = world.rom.word(table + 6) & 0x0F
        self.turn_reload = world.rom.word(0x2B58)
        self.move_timer = 0x20
        self.life_timer = 0x0800
        self.x_fraction = self.y_fraction = 0
        self.homing = False
        self.overlay_descriptor = 0x2D54
        self.overlay_x = source.x
        self.overlay_y = source.y
        self.explosion_pending = False
        self.exploding = False
        self.sequence_pointer = 0
        self.sequence_timer = 0
        palette = world.resources.acquire(0x3C)
        descriptor = 0x2CB4 + self.direction * 6
        super().__init__("handler_60ba_child", source.x, source.y,
                         palette, descriptor,
                         scheduler_priority=0x5000)
        # `$6788` writes only integer coordinates; bytes +$03/+$07 retain
        # the previous owner's Q8 residue in the recycled `$03A6` record.
        self.inherit_slot_fractions = True
        self.collision_table = 0x2D84
        self.death_effect = "e7ae"
        self.start_delay = 0

    def _integrate(self) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _turn_toward_player(self, world: "M72EnemyWorld") -> None:
        wanted = (_direction_offset(
            self.x, self.y, *world.player_native) >> 2) & 0x0F
        # Literal `$689B…$68BC`.  Equality deliberately takes the increment
        # path; the ROM therefore oscillates across an exact target sector.
        current = self.direction
        if wanted >= current:
            increment = wanted < 8 or (wanted - 8) < current
        else:
            increment = not (current < 8 or (current - 8) < wanted)
        if increment:
            self.direction = (self.direction + 1) & 0x0F
        else:
            self.direction = (self.direction - 1) & 0x0F
        velocity_table = world.rom.word(0x2C8C)  # difficulty zero
        self.x_velocity = _signed_word(world.rom.word(
            velocity_table + self.direction * 4))
        self.y_velocity = _signed_word(world.rom.word(
            velocity_table + self.direction * 4 + 2))
        self.move_timer = self.turn_reload

    def _inside_bounds(self) -> bool:
        return (0x012C <= self.x < 0x02D4 and
                0x007C <= self.y < 0x0194)

    def _begin_explosion(self, world: "M72EnemyWorld") -> None:
        # `$6869` releases resource $3C immediately and merely installs
        # `$E7AE`; that initializer runs on the next scheduler pass in the
        # same object-pool record.
        world.resources.release(self.palette)
        self.palette = 0xFF
        self.explosion_pending = True
        self.hostile = False
        self.shootable = False

    def _update_explosion(self, world: "M72EnemyWorld",
                          foreground_delta: int) -> None:
        if self.explosion_pending:
            self.explosion_pending = False
            self.exploding = True
            self.sequence_pointer = 0x8552
            self.sequence_timer = 2
            self.palette = world.resources.acquire(0x01)
        self.x = _u16(self.x + foreground_delta)
        self.descriptor = world.rom.word(self.sequence_pointer + 2)
        self.sequence_timer -= 1
        if self.sequence_timer:
            return
        self.sequence_pointer = _u16(self.sequence_pointer + 4)
        duration = world.rom.word(self.sequence_pointer)
        if duration == 0:
            self.alive = False
            return
        self.sequence_timer = duration & 0xFF

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.explosion_pending or self.exploding:
            self._update_explosion(world, foreground_delta)
            return
        if self.homing:
            # `$687D` really is `TEST [BP+$22],AX`: the linked-list
            # dispatcher leaves AX equal to this object's pool address.
            # Slot $10C0 therefore follows the zero branch for life $0800,
            # while slots $0F40/$18C0/$1C80 enter the steering branch.
            slot_ax = self.object_slot or 0
            if self.life_timer & slot_ax:
                self.life_timer = _u16(self.life_timer - 1)
                self.move_timer = _u16(self.move_timer - 1)
                if self.move_timer == 0:
                    self._turn_toward_player(world)
            elif not self._inside_bounds():
                self.death_effect = None
                self.alive = False
                return
        self._integrate()
        self.descriptor = 0x2CB4 + self.direction * 6
        offset_index = self.direction * 2
        self.overlay_x = _u16(self.x + _signed_word(
            world.rom.word(0x2D14 + offset_index * 2)))
        self.overlay_y = _u16(self.y + _signed_word(
            world.rom.word(0x2D16 + offset_index * 2)))
        self.overlay_descriptor = 0x2D54 + (world.frame_counter & 7) * 6
        if not self.homing:
            self.move_timer -= 1
            if self.move_timer == 0:
                self.homing = True
                self.move_timer = 1
        # `$694B` probes terrain only on odd post-IRQ frame-counter values.
        if ((_u16(world.frame_counter + 1) & 1) and
                world.terrain_at(self.x, self.y) < 0x0DFC):
            self._begin_explosion(world)
        elif not self._inside_bounds():
            self.death_effect = None
            self.alive = False


class Handler60BA(Enemy):
    """Literal Stage-1 multi-state enemy rooted at `$60BA`.

    State transitions and timers follow `$610D…$6619`; projectile and child
    creation follow `$663E…$68EE`.  The address-based name avoids assigning
    an enemy identity that has not yet been established from ROM data.
    """

    def __init__(self, world: "M72EnemyWorld", command: int) -> None:
        index = command & 0x0F
        x = world.rom.word(0x8DD0 + index * 4)
        y = world.rom.word(0x8DD2 + index * 4)
        palette = world.resources.acquire(0x21)
        self.flash_palette = world.resources.acquire(0x55)
        self.phase = world.rng.next() & 0x1F
        self.fire_reload = world.rom.word(0x2B40)
        self.fire_counter = 0
        world.rng.next()  # `$60FE`: consumed, masked, deliberately not stored.
        self.facing_right = False
        self.state = "610d"
        self.timer = 0
        self.next_state = "6243"
        self.next_timer = 0x50
        self.landing_table = 0x2B60
        self.x_fraction = self.y_fraction = 0
        self.flash_timer = 0
        self.flash_visible = False
        super().__init__("handler_60ba", x, y, palette, 0x2BC8, hp=0x1E,
                         collision_table=0x2C40, score_pointer=0x8704,
                         scheduler_priority=0x8020)
        self.death_effect = "e817"

    def _integrate_x(self, velocity: int) -> None:
        coordinate = ((self.x << 8) | self.x_fraction) + velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF

    def _integrate_y(self, velocity: int) -> None:
        coordinate = ((self.y << 8) | self.y_fraction) + velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def _face_player(self, world: "M72EnemyWorld") -> None:
        self.facing_right = world.player_native[0] >= self.x

    def _fall_descriptor(self, world: "M72EnemyWorld") -> int:
        base = 0x2C28 if self.facing_right else 0x2BC8
        return base + (0x0C if (world.frame_counter + self.phase) & 4 else 0)

    def _fire(self, world: "M72EnemyWorld") -> None:
        self.fire_counter += 1
        if self.fire_counter < self.fire_reload:
            return
        self.fire_counter = 0
        player_x, player_y = world.player_native
        if not (self.y - 0x18 < player_y <= self.y + 0x20):
            return
        if ((self.x >= player_x and not self.facing_right) or
                (self.x < player_x and self.facing_right)):
            world.pending.append(Handler60BAProjectile(world, self))

    def _spawn_children(self, world: "M72EnemyWorld") -> None:
        if self.x < world.player_native[0]:
            # `$6743` skips the second vector when the parent is left of R-9.
            tables = (0x2C94, 0x2CA4, 0x2CAC)
        else:
            tables = (0x2C94, 0x2C9C, 0x2CA4, 0x2CAC)
        for table in tables:
            world.pending.append(Handler60BAChild(world, self, table))

    def _show(self, world: "M72EnemyWorld", descriptor: int,
              fire: bool = True) -> None:
        self.descriptor = descriptor
        if fire:
            self._fire(world)

    def _begin_landing(self, exit_side: bool = False) -> None:
        self.y = _u16((self.y + 7) & 0xFFF8)
        self.timer = 0x0F
        self.x = _u16(self.x + (8 if self.facing_right else -8))
        self.landing_table = 0x2B68 if self.facing_right else 0x2B60
        self.state = "652f" if exit_side else "61e3"

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.flash_timer:
            self.flash_timer -= 1
            self.flash_visible = (self.flash_timer & 3) == 0
        else:
            self.flash_visible = False
        if self.state == "610d":
            self._face_player(world)
            self._integrate_x(-0x0080)
            self._integrate_y(-0x0100)
            self._show(world, self._fall_descriptor(world))
            if (world.terrain_at(_u16(self.x - 4), _u16(self.y - 0x18)) < 0x0DFC or
                    world.terrain_at(_u16(self.x - 0x18),
                                     _u16(self.y - 0x18)) < 0x0DFC):
                self._begin_landing()
            return

        if self.state in ("61e3", "652f"):
            self.x = _u16(self.x + foreground_delta)
            self._show(world, world.rom.word(
                self.landing_table + ((self.timer & 0x0C) >> 1)))
            self.timer -= 1
            if self.timer == 0:
                if self.state == "652f":
                    self.state = "657c"
                else:
                    # `$622A…$623D` explicitly clears +$2E and configures
                    # the first `$62BD` pause and its `$6243` continuation.
                    self.facing_right = False
                    self.state, self.timer = "62bd", 0x40
                    self.next_state, self.next_timer = "6243", 0x50
            return

        if self.state == "62bd":
            # `$62BD` calls `$6715` before applying foreground delta.
            if self.timer == 0x10:
                self._spawn_children(world)
            self.x = _u16(self.x + foreground_delta)
            self._show(world, 0x2BE0 if self.facing_right else 0x2B80)
            self.timer -= 1
            if self.timer == 0:
                self.state = self.next_state
                self.timer = self.next_timer
            return

        if self.state == "6243":
            self.x = _u16(self.x + foreground_delta)
            # Handler `$6243` calls the X integrator `$0672`, not Y helper
            # `$0689`: this is the 80-update leftward traverse between the
            # two `$62BD` pauses.
            self._integrate_x(-0x0100)
            table_offset = ((world.frame_counter + self.phase) & 0x38) >> 2
            self._show(world, world.rom.word(0x2B70 + table_offset))
            self.timer -= 1
            if self.timer == 0:
                self.state, self.timer = "62bd", 0x40
                self.next_state, self.next_timer = "631b", 0x0F
                self.landing_table = (
                    0x2B68 if world.player_native[0] >= self.x else 0x2B60)
            return

        if self.state == "631b":
            self.x = _u16(self.x + foreground_delta)
            self._show(world, world.rom.word(
                self.landing_table + ((self.timer & 0x0C) >> 1)), False)
            self.timer -= 1
            if self.timer == 0:
                self.state, self.timer = "6392", 0x48
            return

        if self.state in ("6392", "6374", "638c", "6380"):
            if self.state in ("6374", "6380") and self.timer == 0x10:
                self._spawn_children(world)
            if self.state == "6392":
                self._integrate_y(0x0100)
            elif self.state == "638c":
                self._integrate_x(0x0100)
            self._face_player(world)
            self._show(world, self._fall_descriptor(world))
            self.timer -= 1
            if self.timer == 0:
                if self.state == "6392":
                    self.state, self.timer = "6374", 0x40
                elif self.state == "6374":
                    self.state, self.timer = "638c", 0x80
                elif self.state == "638c":
                    self.state, self.timer = "6380", 0x40
                else:
                    self.state = "6459"
            return

        if self.state == "6459":
            self._face_player(world)
            self._integrate_x(0x0080)
            self._integrate_y(-0x0100)
            self._show(world, self._fall_descriptor(world))
            if (world.terrain_at(_u16(self.x + 4), _u16(self.y - 0x18)) < 0x0DFC or
                    world.terrain_at(_u16(self.x + 0x18),
                                     _u16(self.y - 0x18)) < 0x0DFC):
                self._begin_landing(True)
            return

        # Final handler `$657C` applies foreground delta and periodically
        # emits children until the object leaves `$1D6B` bounds.
        # `$657C…$6584` calls `$6715` before `$6597` adds `$2ED0` to X.
        # Child integer coordinates must therefore inherit the pre-scroll X.
        if (_u16(world.frame_counter + 1) & 0x7F) == 0:
            self._spawn_children(world)
        self.x = _u16(self.x + foreground_delta)
        self._face_player(world)
        self._show(world, 0x2C60 if self.facing_right else 0x2C48)
        if self.x < 0x012C or self.x >= 0x02D4:
            self.alive = False

    @property
    def active_palette(self) -> int:
        return self.flash_palette if self.flash_visible else self.palette

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        # Every `$60BA` state writes $0C after a changed `$F6DA` counter;
        # helper `$661A` uses the same decrement-and-low-two-bits rule.
        super().take_damage(world, damage)
        self.flash_timer = 0x0C


def _update_dobkeratops_e7be(
        enemy: Enemy, world: "M72EnemyWorld", foreground_delta: int) -> None:
    """Run the in-place `$E7BE/$E7D4` chain used by boss components."""
    if getattr(enemy, "explosion_state", None) == "init":
        enemy.palette = world.resources.acquire(0x01)
        enemy.explosion_pointer = 0x8530
        enemy.explosion_timer = 2
        enemy.explosion_state = "active"
        if getattr(enemy, "state", None) == "cleanup_explosion":
            enemy.state = "cleanup_explosion_active"

    enemy.x = _u16(enemy.x + foreground_delta)
    enemy.descriptor = world.rom.word(enemy.explosion_pointer + 2)
    enemy.explosion_timer -= 1
    terminal = False
    if enemy.explosion_timer == 0:
        enemy.explosion_pointer = _u16(enemy.explosion_pointer + 4)
        duration = world.rom.word(enemy.explosion_pointer)
        if duration == 0:
            terminal = True
        else:
            enemy.explosion_timer = duration & 0xFF
    if terminal or world.cleanup_active:
        # `$E7D4` has already called `$1BCC` in this pass.  The object and
        # resource disappear afterwards, but the emitted sprite remains in
        # hardware sprite RAM for the display frame.
        world.emit_transient_sprite(
            enemy.descriptor, enemy.palette, 0x01, enemy.x, enemy.y)
        enemy.alive = False
        enemy.death_effect = None


class DobkeratopsBack(Enemy):
    """Rear body object created at `$9920`, handlers `$9B26/$9B39`."""

    def __init__(self, world: "M72EnemyWorld", root: "DobkeratopsRoot") -> None:
        self.root = root
        self.timer = 0x0200
        self.explosion_state: str | None = None
        palette = world.resources.acquire(0x15)
        super().__init__("dobkeratops_back", 0x0328, 0x0128,
                         palette, 0x44AC, shootable=False,
                         scheduler_priority=0x3810)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.explosion_state is not None:
            _update_dobkeratops_e7be(self, world, _foreground_delta)
            return
        self.x = _u16(self.x + world.background_delta)
        if self.timer:
            self.timer -= 1
            self.descriptor = 0x44AC
        else:
            self.timer = (self.timer + 1) % 0x0180
            if self.timer < 0x00C0:
                self.descriptor = 0x44AC
            elif self.timer < 0x00D0 or self.timer >= 0x0170:
                self.descriptor = 0x44A0
            else:
                self.descriptor = 0x44A6
        if self.x < 0x0120:
            self.alive = False
            return
        if self.root.body_destroyed:
            # `$9B73…$9B9A` has already emitted this pass's body sprite.
            # Preserve it after releasing type `$15`, then let `$E7BE`
            # initialize on the following pass in this same object slot.
            world.emit_transient_sprite(
                self.descriptor, self.palette, 0x15, self.x, self.y)
            world.resources.release(self.palette)
            self.palette = 0xFF
            self.explosion_state = "init"


class DobkeratopsOrb(Enemy):
    """Mouth projectile `$9D9E/$9E07/$9E78`, resource type `$3F`."""

    def __init__(self, world: "M72EnemyWorld", body: "DobkeratopsBody") -> None:
        self.x_fraction = self.y_fraction = 0
        self.trail_timer = 0x40
        self.straight_timer = 0x20
        self.acceleration = 0
        self.y_velocity = 0
        self.acceleration_timer = 2
        self.state = "9e07"
        self.origin_x = _u16(body.x - 8)
        self.origin_y = _u16(body.y - 0x0C)
        palette = world.resources.acquire(0x3F)
        super().__init__("dobkeratops_orb", self.origin_x,
                         self.origin_y, palette, 0x44BA,
                         shootable=False, collision_table=0x44B2,
                         scheduler_priority=0xF000)
        # `$9DAF/$9DBB` write only integer coordinates into a recycled slot.
        self.inherit_slot_fractions = True
        self.start_delay = 0

    def _descriptor(self, frame_counter: int, phase_offset: int = 0) -> int:
        phase = (frame_counter + phase_offset) & 0x0C
        return 0x44BA + phase + (phase >> 1)

    def _begin_curve(self, world: "M72EnemyWorld") -> None:
        player_y = world.player_native[1]
        self.acceleration = (0x20 if player_y >= 0x0104 else
                             (-0x20 if player_y < 0x00F2 else 0))
        self.y_velocity = 0
        self.acceleration_timer = 2
        self.state = "9e78"

    def _integrate_curve_y(self) -> None:
        self.acceleration_timer -= 1
        if self.acceleration_timer == 0:
            self.acceleration_timer = 2
            self.y_velocity = _signed_word(
                _u16(self.y_velocity + self.acceleration))
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.state == "9e07":
            self.trail_timer = _u16(self.trail_timer - 1)
            if (self.trail_timer & 3) == 0:
                world.pending.append(DobkeratopsOrbTrail(
                    world, self, self.trail_timer))
            self.x = _u16(self.x - 4)
            self.descriptor = self._descriptor(world.frame_counter)
            self.straight_timer -= 1
            if self.straight_timer == 0:
                self._begin_curve(world)
            return

        self._integrate_curve_y()
        self.x = _u16(self.x - 4)
        self.descriptor = self._descriptor(world.frame_counter)
        if (self.x < 0x012C or self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class DobkeratopsOrbTrail(Enemy):
    """One equal-priority trail record `$9EC0/$9F18` from `$9DD9`."""

    def __init__(self, world: "M72EnemyWorld", parent: DobkeratopsOrb,
                 phase_offset: int) -> None:
        self.parent = parent
        self.phase_offset = _u16(phase_offset)
        self.straight_timer = 0x20
        self.acceleration = 0
        self.y_velocity = 0
        self.acceleration_timer = 2
        self.y_fraction = self.x_fraction = 0
        self.state = "9ec0"
        palette = world.resources.acquire(0x3F)
        super().__init__(
            "dobkeratops_orb_trail", parent.origin_x, parent.origin_y,
            palette, 0x44BA, shootable=False, collision_table=0x44B2,
            scheduler_priority=0xF000)
        self.inherit_slot_fractions = True

    def _descriptor(self, frame_counter: int) -> int:
        phase = (frame_counter + self.phase_offset) & 0x0C
        return 0x44BA + phase + (phase >> 1)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        if self.state == "9f18":
            self.acceleration_timer -= 1
            if self.acceleration_timer == 0:
                self.acceleration_timer = 2
                self.y_velocity = _signed_word(
                    _u16(self.y_velocity + self.acceleration))
            coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
            self.y = _u16(coordinate >> 8)
            self.y_fraction = coordinate & 0xFF

        self.x = _u16(self.x - 4)
        self.descriptor = self._descriptor(world.frame_counter)

        if self.state == "9ec0":
            self.straight_timer -= 1
            if self.straight_timer == 0:
                # `$9EF5…$9F08` copies the current acceleration from the
                # owning orb, clears Y velocity and installs `$9F18`.
                self.acceleration = self.parent.acceleration
                self.y_velocity = 0
                self.acceleration_timer = 2
                self.state = "9f18"
            return

        if (self.x < 0x012C or self.y < 0x007C or self.y >= 0x0194):
            self.alive = False


class DobkeratopsBody(Enemy):
    """Vulnerable body `$9B9B/$9C33/$9C70` of the first boss."""

    def __init__(self, world: "M72EnemyWorld", root: "DobkeratopsRoot") -> None:
        self.root = root
        self.state = "intro"
        self.timer = 0x0200
        self.flash_palette = 0xFF
        self.flash_timer = 0
        self.flash_visible = False
        self.death_pointer = 0x454E
        self.render_ready = True
        palette = world.resources.acquire(0x15)
        super().__init__("dobkeratops_body", 0x0358, 0x0100,
                         palette, 0x44D2, hp=0x1E, shootable=False,
                         collision_table=0x4526,
                         scheduler_priority=0x3818)

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        self.x = _u16(self.x + world.background_delta)
        if self.state == "intro":
            self.descriptor = 0x44D2
            self.timer -= 1
            if self.timer == 0x0060:
                # `$9BB9…$9BE7`: four independent `$E7B6` records at
                # priority `$F280`; each coordinate consumes its own RNG
                # value and applies the literal `&$1F - $10` displacement.
                for _ in range(4):
                    x = _u16(self.x + (world.rng.next() & 0x1F) - 0x10)
                    y = _u16(self.y + (world.rng.next() & 0x1F) - 0x10)
                    world.pending.append(ExplosionEffect(
                        world, x, y, "e7b6",
                        scheduler_priority=0xF280))
            if self.timer == 0:
                world.resources.release(self.palette)
                self.palette = world.resources.acquire(0x16)
                self.flash_palette = world.resources.acquire(0x55)
                self.state = "emerge"
                self.timer = 0x3F
            return
        if self.state == "emerge":
            offset = ((self.timer & 0x30) >> 2)
            offset += offset >> 1
            self.descriptor = 0x44DE + offset
            self.timer -= 1
            if self.timer == 0:
                self.state = "active"
                self.timer = 0x00C0
                self.shootable = True
                self.hp = 0x1E
            return
        if self.state == "active":
            self.timer = (self.timer - 1) & 0x7F
            offset = ((self.timer & 0x70) >> 2)
            offset += offset >> 1
            self.descriptor = 0x44F6 + offset
            if self.flash_timer:
                self.flash_timer -= 1
                self.flash_visible = (world.frame_counter & 4) == 0
            else:
                self.flash_visible = False
            if self.timer == 0x30:
                world.pending.append(DobkeratopsOrb(world, self))
            # `$9CE1…$9CEB`: an intact body that scrolls left of native
            # X=$0120 takes the shared `$9C1B` exit.  That path marks the
            # linked root and releases both palette slots and this record.
            if self.x < 0x0120:
                self.root.defeated = True
                self.alive = False
            return
        # `$9D30…$9D9D`: one ROM debris record is attempted whenever the
        # one-word delay expires.  Both RNG calls happen even if `$03A6`
        # cannot allocate a record; only a successful allocation advances
        # the six-byte record pointer.
        self.x = _u16(self.x + world.background_delta)
        self.timer = _u16(self.timer - 1)
        if self.timer == 0:
            sound = world.rng.next() & 3
            if sound:
                world.sound_commands.append(0x50 + sound)
            self.timer = (world.rng.next() & 1) | 1
            handler = world.rom.word(self.death_pointer + 4)
            x = _u16(self.x + _signed_word(
                world.rom.word(self.death_pointer)))
            y = _u16(self.y + _signed_word(
                world.rom.word(self.death_pointer + 2)))
            if handler == 0xE700:
                child: Enemy = DobkeratopsDebrisE700(world, x, y)
            else:
                effect = {
                    0xE7B6: "e7b6",
                    0xE7BE: "e7be",
                    0xE817: "e817",
                }[handler]
                child = ExplosionEffect(
                    world, x, y, effect, scheduler_priority=0xEF00)
            pending_before = len(world.pending)
            world.pending.append(child)
            if len(world.pending) != pending_before:
                self.death_pointer = _u16(self.death_pointer + 6)
            else:
                # Constructors acquire the resource before the Python pool
                # adapter can report `$03A6` failure.  ROM does not execute
                # the child initializer in that case, so undo the acquire.
                world.resources.release(child.palette)
                child.palette = 0xFF
        if world.rom.word(self.death_pointer) == 0x8000:
            self.alive = False

    def take_damage(self, world: "M72EnemyWorld", damage: int) -> None:
        if self.state != "active":
            return
        self.hp -= damage
        self.flash_timer = 0x10
        if self.hp <= 0:
            # `$9C70` drew the body before `$F75F` detected the fatal hit.
            # Retain that already-emitted sprite for the current display.
            world.emit_transient_sprite(
                self.descriptor, self.active_palette,
                world.resources.types[self.active_palette], self.x, self.y)
            self.hp = 0
            self.shootable = False
            self.state = "death"
            self.timer = 1
            self.death_pointer = 0x454E
            self.render_ready = False
            self.root.body_destroyed = True
            self.cleanup_passthrough = True
            # In the ROM the body `$9C70` executes `$F75F` at priority
            # `$3818`; all `$FF90…$FFA8` links are still ahead in that same
            # scheduler pass and see root `+$32=1`.  Python applies fixed
            # weapon scans after the dynamic pass, so install `$A107` here to
            # leave every link in the identical end-of-pass state.
            for enemy in world.enemies:
                if (isinstance(enemy, DobkeratopsTentacle) and
                        enemy.root is self.root):
                    enemy.begin_root_cleanup()
            # `$9D10…$9D16`: the boss body awards the `$8714` BCD record at
            # the exact transition into its death state.
            world.award_score_pointer(0x8714)

    @property
    def active_palette(self) -> int:
        if self.flash_palette != 0xFF and self.flash_visible:
            return self.flash_palette
        return self.palette


class DobkeratopsTentacle(Enemy):
    """One literal Dobkeratops segment/tip `$A035…$A22D`.

    The 18 body links and the aimed tip have independent Q8 motion scripts.
    On body destruction they do not disappear with global cleanup: each link
    waits its ROM `+$32` delay, emits the `$E7BE` first frame, and only then
    returns its pool record.
    """

    def __init__(self, world: "M72EnemyWorld", root: "DobkeratopsRoot",
                 record: int, tip: bool = False) -> None:
        self.root = root
        self.tip = tip
        if tip:
            x, y = 0x0277, 0x00BF
            descriptor = 0x4CC6
            script = 0x4C76
        else:
            x = world.rom.word(record)
            y = world.rom.word(record + 2)
            descriptor = world.rom.word(record + 4)
            script = world.rom.word(record + 6)
        scheduler_priority = (0xFFA8 if tip else
                              0xFF90 + (record - 0x43AC) // 10)
        self.fixed_descriptor = descriptor
        self.script_start = self.script_pointer = script
        self.intro_timer = 0x20
        self.cleanup_timer = (0x68 if tip else world.rom.word(record + 8))
        self.state = "intro"
        self.step_timer = 0
        self.x_velocity = self.y_velocity = 0
        self.x_fraction = self.y_fraction = 0
        if tip:
            # Root initializer `$9A5A…$9A72`; `$F8A7` replaces these fields
            # when the 32-frame `$A133` intro expires.
            self.fire_a = 0x0040
            self.fire_b = 0x0080
            self.projectile_script = 0x4460
            self.fire_counter = ((world.rng.next() * 4) &
                                 _u16(self.fire_a - 1))
        palette = world.resources.acquire(0x17)
        super().__init__("dobkeratops_tip" if tip else "dobkeratops_tentacle",
                         x, y, palette, descriptor, hp=0x80,
                         collision_table=0x4CBE,
                         scheduler_priority=scheduler_priority)
        # `$03A6` does not clear object bytes `+$03/+$07`; the exact residue
        # depends on the playthrough's FIFO history and cannot be hard-coded
        # from one no-fire capture.
        self.inherit_slot_fractions = True

    def _load_step(self, world: "M72EnemyWorld") -> None:
        pointer = self.script_pointer
        self.x_velocity = _signed_word(world.rom.word(pointer))
        self.y_velocity = -_signed_word(world.rom.word(pointer + 2))
        control = world.rom.word(pointer + 4)
        self.step_timer = control & 0x0FFF
        self.script_pointer = _u16(pointer + 6)
        if control & 0x8000:
            self.script_pointer = self.script_start

    def _setup_tip_fire(self, world: "M72EnemyWorld") -> None:
        """Execute `$A18E…$A1A2` including literal `$F8A7`."""
        table = 0x8E10 + 3 * 6 + world.difficulty * 0x60
        self.fire_a = world.rom.word(table)
        self.fire_b = world.rom.word(table + 2)
        self.projectile_script = world.rom.word(table + 4)
        self.fire_counter = ((world.rng.next() * 4) &
                             _u16(self.fire_a - 1))
        if world.checkpoint_flag == 0:
            self.projectile_script = 0

    def begin_root_cleanup(self) -> None:
        """Install delayed handler `$A107` after root field `+$32` changes."""
        if self.state not in ("cleanup_wait", "cleanup_explosion"):
            self.state = "cleanup_wait"
            self.cleanup_passthrough = True
            self.shootable = False
            self.hostile = False

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "cleanup_wait":
            # `$A107` decrements first.  The nonzero path alone scrolls and
            # draws; the zero path releases type `$17`, consumes RNG and
            # installs `$E7BE` without falling through to it.
            self.cleanup_timer = _u16(self.cleanup_timer - 1)
            if self.cleanup_timer:
                self.x = _u16(self.x + world.background_delta)
                return
            world.resources.release(self.palette)
            self.palette = 0xFF
            sound = world.rng.next() & 3
            if sound:
                world.sound_commands.append(0x50 + sound)
            self.state = "cleanup_explosion"
            return

        if self.state == "cleanup_explosion":
            self.explosion_state = "init"
            _update_dobkeratops_e7be(self, world, foreground_delta)
            return

        if self.state == "cleanup_explosion_active":
            _update_dobkeratops_e7be(self, world, foreground_delta)
            return

        if self.state == "active" and self.tip:
            _run_f63a(world, self)
        self.x = _u16(self.x + world.background_delta)
        if self.tip:
            direction = _direction_offset(self.x, self.y, *world.player_native)
            self.descriptor = world.rom.word(0x4CC6 + (direction >> 1))
        else:
            self.descriptor = self.fixed_descriptor
        if self.intro_timer:
            # Both `$A035` and `$A133` execute `$F75F` on every intro pass.
            self.shootable = True
            self.hostile = True
            self.intro_timer -= 1
            if self.intro_timer == 0:
                self._load_step(world)
                self.state = "active"
                if self.tip:
                    self._setup_tip_fire(world)
            return

        coordinate = ((self.x << 8) | self.x_fraction) + self.x_velocity
        self.x = _u16(coordinate >> 8)
        self.x_fraction = coordinate & 0xFF
        coordinate = ((self.y << 8) | self.y_fraction) + self.y_velocity
        self.y = _u16(coordinate >> 8)
        self.y_fraction = coordinate & 0xFF
        self.step_timer -= 1
        if self.step_timer == 0:
            self._load_step(world)

        # `$A0AB`: only odd-priority body links call `$F75F`, and only when
        # the already-incremented IRQ counter is odd.  The aimed tip calls it
        # unconditionally at `$A1D3`.
        collision_tick = _u16(world.frame_counter + 1)
        self.shootable = self.tip or bool(
            collision_tick & self.scheduler_priority & 1)
        self.hostile = self.shootable
        if getattr(self.root, "body_destroyed", False):
            self.begin_root_cleanup()

    def take_damage(self, _world: "M72EnemyWorld", _damage: int) -> None:
        # `$A035/$A08B` reload `$1F=0,$2F=$80` before `$F75F` every update:
        # player ammunition collides, but damage cannot accumulate.
        return


class DobkeratopsArenaAnchor(Enemy):
    """Invisible arena target/writer `$9F63/$9F84/$9FE9`."""

    def __init__(self, world: "M72EnemyWorld", root: "DobkeratopsRoot",
                 record: int) -> None:
        self.root = root
        self.path = world.rom.word(record + 4)
        self.activation_timer = 0x0280
        self.timeout = (world.rng.next() & 0x1F) + 0x0900
        self.tile_offset = 0
        self.state = "wait"
        super().__init__("dobkeratops_arena_anchor",
                         world.rom.word(record), world.rom.word(record + 2),
                         0xFF, 0, hp=1, shootable=False,
                         collision_table=0x46C4,
                         scheduler_priority=0x3821)

    def _begin_erase(self, world: "M72EnemyWorld") -> None:
        self.tile_offset = world.terrain_address(self.x, self.y)
        # `$9FAE…$9FDF`: entering the writer state first creates one
        # `$FE00/$E7B6` explosion at `(x+4,y-4)`.  Only a successful `$03A6`
        # is followed by sound `$52` and score task `$E8BD/$86F0`.
        pending_before = len(world.pending)
        world.pending.append(ExplosionEffect(
            world, _u16(self.x + 4), _u16(self.y - 4), "e7b6",
            scheduler_priority=0xFE00))
        if len(world.pending) != pending_before:
            world.sound_commands.append(0x52)
            world.award_score_pointer(0x86F0)
        self.state = "erase"
        self.shootable = False

    def take_damage(self, world: "M72EnemyWorld", _damage: int) -> None:
        if self.state == "active":
            self._begin_erase(world)

    def update(self, world: "M72EnemyWorld", foreground_delta: int) -> None:
        if self.state == "wait":
            self.x = _u16(self.x + foreground_delta)
            self.activation_timer -= 1
            if self.activation_timer == 0:
                self.state = "active"
                self.shootable = True
            return
        if self.state == "active":
            self.x = _u16(self.x + foreground_delta)
            self.timeout -= 1
            if (self.timeout == 0 or
                    (self.root.body is not None and
                     (0x1E - self.root.body.hp) >= 0x0F)):
                self._begin_erase(world)
            return
        # IRQ `$0219` increments `$2EB6` after the callback value supplied to
        # Python.  `$9FF0` tests the incremented value, hence `+1`; using the
        # sampled parity freed every arena writer one VBlank too early.
        if _u16(world.frame_counter + 1) & 1:
            return
        world.erase_terrain(self.tile_offset)
        delta = world.rom.word(self.path)
        self.path = _u16(self.path + 2)
        if delta == 0x8000:
            self.root.anchors_remaining -= 1
            self.alive = False
            return
        low = ((self.tile_offset & 0xFF) + (delta & 0xFF)) & 0xFF
        high = (((self.tile_offset >> 8) + (delta >> 8)) & 0xFF) << 8
        self.tile_offset = (high | low) & 0x3FFF


class DobkeratopsRoot(Enemy):
    """Multipart owner and boss completion controller `$98FD/$9915`."""

    def __init__(self, world: "M72EnemyWorld") -> None:
        self.defeated = False
        self.body_destroyed = False
        self.cleanup = False
        self.initialized = False
        self.end_timer = 0
        self.timeout = 0x1000
        self.anchors_remaining = 4
        self.body: DobkeratopsBody | None = None
        super().__init__("dobkeratops_root", 0, 0, 0xFF, 0,
                         shootable=False, scheduler_priority=0x3800)
        self.start_delay = 0

    def _spawn_parts(self, world: "M72EnemyWorld") -> None:
        """Execute initializer `$9915…$9A7F` on the root's first pass."""
        world.pending.append(DobkeratopsBack(world, self))
        self.body = DobkeratopsBody(world, self)
        world.pending.append(self.body)
        for index in range(4):
            world.pending.append(DobkeratopsArenaAnchor(
                world, self, 0x4394 + index * 6))
        for index in range(0x12):
            world.pending.append(DobkeratopsTentacle(
                world, self, 0x43AC + index * 10))
        world.pending.append(DobkeratopsTentacle(world, self, 0, tip=True))
        self.initialized = True

    def _begin_end(self, world: "M72EnemyWorld", *, global_cleanup: bool) -> None:
        # Root `+$24` enters `$9AAE` and raises `$2FC4`; destroyed-body flag
        # `+$32` and timeout `$9A83` jump directly to `$9AB3` and do not.
        if global_cleanup:
            world.cleanup_active = True
        world.sound_commands.append(0x1B)
        self.cleanup = True
        self.end_timer = 0x00C0

    def update(self, world: "M72EnemyWorld", _foreground_delta: int) -> None:
        # Event `$98FD` only allocates handler `$9915`.  The 25 component
        # records are allocated by that handler on the following scheduler
        # pass, after which it installs `$9A80` and returns without consuming
        # the new `$1000` timeout.
        if not self.initialized:
            self._spawn_parts(world)
            return
        if self.cleanup:
            self.end_timer -= 1
            if self.end_timer == 0x0010:
                world.sound_commands.extend((0x1A, 0x1C))
                # `$9ADE` sets `$2FC1=$FF`.  Fixed R-9 handler
                # `$2084…$2109` consumes this latch on the following main
                # pass and flies toward native target `(0200,00E0)`.
                world.player_exit_latch = 0xFF
            if self.end_timer == 0:
                world.foreground_velocity_command = 0x0080
                world.background_velocity_command = 0x0080
                world.boss_defeated = True
                self.alive = False
            return
        if self.defeated:
            self._begin_end(world, global_cleanup=True)
            return
        if self.body_destroyed:
            self._begin_end(world, global_cleanup=False)
            return
        self.timeout -= 1
        if self.timeout == 0:
            self._begin_end(world, global_cleanup=False)
            return
        # `$9A85…$9A97`: once the fourth arena writer has consumed its
        # `$8000` sentinel, root writes the background Q8 velocity `$0040`
        # on every pass.  The write happens after this VBlank's `$0467`, so
        # the scroll owner applies it to the next integration.
        if self.anchors_remaining == 0:
            world.background_velocity_command = 0x0040


class M72EnemyWorld:
    """One-event-per-VBlank dispatcher and active ROM enemy objects."""

    HANDLERS: dict[int, str] = {
        0x55E9: "terrain_bound_55e9",
        0x596D: "red_flyer",
        0x5A02: "ground_walker",
        0x5DC8: "patrol_formation",
        0x5CEA: "enemy_5cea",
        0x5EED: "enemy_5eed",
        0x60BA: "handler_60ba",
        0x696E: "terrain_enemy_696e",
        0x6A9B: "terrain_modifier_parent_6acb",
        0x6E9B: "fixed_large_6e9b",
        0x6F89: "enemy_6f89",
        0x7182: "enemy_7182",
        0x7294: "enemy_7294",
        0x74B4: "large_terrain_74b4",
        0x78F8: "formation_78f8",
        0x7D68: "enemy_7d68",
        0x80E3: "player_targeting_80e3",
        0x8469: "enemy_8469",
        0x8561: "enemy_8561",
        0x86A6: "animated_86a6",
        0x875D: "spawner_875d",
        0x897E: "terrain_aware_897e",
        0x8F5E: "enemy_8f5e",
        0x8C12: "stage_object_8c12",
        0xA71D: "multipart_a71d",
        0xB7FB: "boss_b7fb",
        0x9660: "final_spawner_9660",
        0x915B: "multipart_915b",
        0x98FD: "dobkeratops",
        0xF01B: "next_stage_init_f01b",
        0xF130: "stage_transition_f130",
        0xF366: "stage_transition_f366",
        0xFB9C: "palette_cycle_fbed",
    }

    # These handlers belong to scroll, terrain, resource and stage-control
    # subsystems.  Keeping their events separate prevents a missing enemy
    # implementation from being hidden among deliberately delegated commands.
    DELEGATED_HANDLERS = frozenset({
        0xF0F3, 0xF461, 0xF429, 0x5526, 0x5596,
        0xC46E, 0xA22E, 0xB0E1, 0xB1D8,
        0xC0A9, 0xFB10, 0xEE0B,
        0xEEAB,
    })

    def __init__(self, stage: int = 1,
                 full_event_stream: bool = False,
                 difficulty: int = 0,
                 preload_graphics: bool = False,
                 rom: M72Rom | None = None,
                 atlas: M72SpriteAtlas | None = None) -> None:
        if stage not in STAGE_EVENT_RANGES:
            raise ValueError(f"stage должен быть 1..8, получено {stage}")
        if not 0 <= difficulty <= 3:
            raise ValueError("difficulty должен быть 0..3")
        # Неизменяемый ROM и кэш офлайн-пикселей спрайтов можно передать от
        # прежнего мира: их содержимое не зависит от состояния игры.
        self.rom = rom if rom is not None else M72Rom()
        self.stage = stage
        self.difficulty = difficulty
        self.full_event_stream = full_event_stream
        stage_first, self.event_last = STAGE_EVENT_RANGES[stage]
        stage1_checkpoint = stage == 1 and not full_event_stream
        self.resources = M72ResourceManager(stage1_checkpoint)
        # The standalone Stage-1 entry is the state after MAME VBlank 851,
        # not a fresh `$EDD9` boot.  Reversing the three-byte recurrence from
        # the traced `$E568` calls at VBlank 852 gives this unique state.
        self.rng = M72Rng((0xB9, 0xB3, 0xDF) if stage1_checkpoint
                          else (5, 1, 3))
        self.atlas = atlas if atlas is not None else M72SpriteAtlas()
        if stage1_checkpoint and preload_graphics:
            # All pixels are already converted offline for FT812.  Construct
            # the small set of pygame surfaces here, outside the 55 Hz loop,
            # so `$80E3` cannot stall two gameplay frames on first use.
            self.atlas.preload_80e3(self.rom)
        self.event_pointer = (EVENT_FIRST if stage1_checkpoint else stage_first)
        self.frame_counter = 9
        self.object_pool = M72ObjectPool(stage1_checkpoint)
        self.allocation_failures: list[tuple[int, str]] = []
        self.pending: M72PendingList = M72PendingList(self)
        self.enemies: list[Enemy] = []
        if stage1_checkpoint:
            # Exact linked-list order at the checkpoint is newest first for
            # equal priorities (`JAE` at `$03CE`).
            uninitialized = BackgroundParticleE5CD(0x836C)
            uninitialized.object_slot = 0x1280
            particles = [BackgroundParticleE5CD.from_stage1_checkpoint(record)
                         for record in reversed(STAGE1_CHECKPOINT_PARTICLES)]
            for particle in particles:
                resource_type = self.resources.types[particle.palette]
                if self.resources.acquire(resource_type) != particle.palette:
                    raise AssertionError("checkpoint resource-slot mismatch")
            cycles = [PaletteCycleFBED.from_stage1_checkpoint(record)
                      for record in reversed(
                          STAGE1_CHECKPOINT_PALETTE_CYCLES)]
            self.enemies = [uninitialized, *particles, *cycles]
        # Snapshot-free continuation after that same VBlank-851 pass:
        # `$E4AC` has decremented `$00E9->$00E8` and `$E532` has reset the
        # six-frame spawn counter to zero.
        self.resource_owners: list[ParticleControllerE4A5] = (
            [ParticleControllerE4A5(
                0x00E8, (2, 3, 4, 5), 0x836C, 6, 0, 0x0C00)]
            if stage1_checkpoint else [])
        self.delegated_events: list[StageEvent] = []
        self.unsupported_events: list[StageEvent] = []
        self.projectile_spawns = 0
        # `$E8BD` keeps a four-byte packed-BCD total and a second per-stage
        # total.  Byte 3 has only one decimal digit, hence the ROM clamp at
        # 9,999,999 after `ADD4S` (`$E8F1…$E91D`).
        self.score_bcd = bytearray(4)
        self.stage_score_bcd = bytearray(4)
        self.score_awards: list[int] = []
        # `$2F46`: номер порога следующей призовой жизни (`$ED51` сдвигает указатель на 4).
        self.bonus_index = 0
        # Автомат жизней игрока со счётчиком `$2F32`; задаёт Game.
        self.lifecycle = None
        # `$ED89 → $F07B`: после задачи очков HUD перерисовывает поле запаса жизней.
        self.hud_refresh = False
        # Last exact `$54E4` request from each `$FBED` controller.  Applying
        # its 31-step hardware palette worker to the offline tile atlases is a
        # separate renderer concern; the ROM object state/timing stays here.
        self.palette_cycle_state: dict[int, tuple[int, int]] = {}
        self.ticks = 0
        self._terrain_code: Callable[[int, int], int] | None = None
        self._collision_codes: Callable[[int, int], tuple[int, int]] | None = None
        self.player_native = (0x01CB, 0x0110)
        self.background_delta = 0
        self.checkpoint_flag = 0          # byte `DS:$2F2D`
        self.boss_defeated = False
        self.cleanup_active = False       # byte `DS:$2FC4`
        self.player_exit_latch = 0        # byte `DS:$2FC1`
        # `$F366` selects `$2F44/$2F45` with `$2F20`, then uses `$2FC5`
        # as the byte index for its repeat-call sound tables.
        self.active_player = 0            # byte `DS:$2F20`: zero=P1
        self.stage_transition_flags = [0, 0]  # bytes `DS:$2F44/$2F45`
        self.transition_sound_index = 0   # byte `DS:$2FC5`
        self.sound_commands: list[int] = []  # literal calls to task `$0303`
        # Object handlers write the shared `$2EEC/$2EF4` velocities after the
        # scroll integrator.  The stage owner consumes these commands after
        # `M72EnemyWorld.update`, making them effective on the next VBlank.
        self.foreground_velocity_command: int | None = None
        self.background_velocity_command: int | None = None
        self.scroll_reset_command = False
        self.stage_init_scroll_command: tuple[int, int, int] | None = None
        self.invulnerability_latch = False  # byte `DS:$2FC6`
        self.player_shot_visual_requests = 0  # fixed-slot byte `DS:$0038`
        # Current handler of the external stage/boss controller referenced
        # through object field `+$36` by the `$915B` multipart chain.
        self.stage_controller_handler = 0
        # Raw player-weapon bytes affected by pickup handler `$5947`.
        self.ram_0033 = 0
        self.ram_0035 = 0
        self.ram_0036 = 0
        self.weapon_pickups = 0       # pending `$0037` writes
        self.weapon_type = 0          # `$003C`
        self.force_level = 0          # first exact pickup exposes `$003E=1`
        self.speed_indicator_timer = 0
        self._terrain_address: Callable[[int, int], int] | None = None
        self._erase_terrain: Callable[[int], None] | None = None
        self._replace_terrain: Callable[[int, int, int], None] | None = None
        self._terrain_cell: Callable[[int], tuple[int, int]] | None = None
        # Live `$03A6` insertion needs the priority currently visited by the
        # ROM scheduler.  `None` denotes controller/event code outside its
        # ordered object walk.
        self._scheduler_cursor_priority: int | None = None
        self._scheduler_foreground_delta = 0
        # Sprites emitted by a handler which frees its object later in the
        # same main pass remain in hardware sprite RAM for that display frame.
        # Keep those emissions separately from live pool records.
        self.transient_sprites: list[tuple[int, int, int, int, int]] = []

    def current_event(self) -> StageEvent | None:
        if self.event_pointer > self.event_last:
            return None
        address = self.event_pointer
        threshold = self.rom.word(address)
        command = self.rom.word(address + 2)
        offset = ((command >> 9) & 0x7E)
        handler = self.rom.word(DISPATCH_TABLE + offset)
        return StageEvent(address, threshold, command, handler)

    def update(self, progression: int, foreground_delta: int,
               frame_counter: int,
               terrain_code: Callable[[int, int], int] | None = None,
               collision_codes: Callable[[int, int], tuple[int, int]] | None = None,
               player_native: tuple[int, int] | None = None,
               background_delta: int = 0,
               terrain_address: Callable[[int, int], int] | None = None,
               erase_terrain: Callable[[int], None] | None = None,
               replace_terrain: Callable[[int, int, int], None] | None = None,
               terrain_cell: Callable[[int], tuple[int, int]] | None = None
               ) -> None:
        self.frame_counter = frame_counter
        self._terrain_code = terrain_code
        self._collision_codes = collision_codes
        if player_native is not None:
            self.player_native = player_native
        self.background_delta = _signed_word(background_delta)
        self._terrain_address = terrain_address
        self._erase_terrain = erase_terrain
        self._replace_terrain = replace_terrain
        self._terrain_cell = terrain_cell
        self._scheduler_foreground_delta = _signed_word(foreground_delta)
        self.transient_sprites.clear()
        self.ticks += 1
        # IRQ `$0219…$0225` increments `$2EB6` after the state sampled by the
        # MAME frame callback and reseeds RNG whenever its low nine bits wrap.
        # The Python counter passed here is that sampled value, hence `+1`.
        if (_u16(frame_counter + 1) & 0x01FF) == 0:
            self.rng.reset()
        if self.speed_indicator_timer:
            self.speed_indicator_timer -= 1
        # Launch effect resource type $09 is released with the ROM R-9 launch
        # object after its 226-frame script.
        if self.ticks == 226 and self.resources.types[1] == 0x09:
            self.resources.release(1)
        while self.player_shot_visual_requests:
            self.player_shot_visual_requests -= 1
            object_slot = self.object_pool.take()
            if object_slot is None:
                self.allocation_failures.append(
                    (self.frame_counter, "player_shot_visual_4eaf"))
                continue
            visual = PlayerShotVisual4EAF(self)
            self.object_pool.bind(visual, object_slot)
            self.enemies.append(visual)
        # The ROM scheduler walks ascending priorities.  `$E568/$E5CD`
        # particles are priority `$0010`; their initializer must therefore
        # consume RNG before controller `$E4A5` at `$1000`, and both precede
        # event-created gameplay objects (`$8010` and above).
        scheduled = sorted(
            enumerate(tuple(self.enemies)),
            key=lambda item: (item[1].scheduler_priority,
                              -item[1].scheduler_serial, item[0]))

        def run_priority_band(*, before_controller: bool) -> None:
            for _insertion_order, enemy in scheduled:
                if ((enemy.scheduler_priority < 0x1000) !=
                        before_controller):
                    continue
                if not enemy.alive:
                    if not (enemy.destroyed and
                            enemy.death_effect is not None):
                        self.object_pool.release(enemy.object_slot, enemy)
                    continue
                if (self.cleanup_active and not isinstance(
                        enemy, (CleanupTimerF477, InvulnerabilityTimerF44E,
                                TimedControlF3C1,
                                StageTransitionF1BF)) and
                        not enemy.cleanup_passthrough):
                    enemy.alive = False
                    self.object_pool.release(enemy.object_slot, enemy)
                    continue
                if enemy.start_delay:
                    enemy.start_delay -= 1
                else:
                    self._scheduler_cursor_priority = enemy.scheduler_priority
                    enemy.update(self, self._scheduler_foreground_delta)
                    self._scheduler_cursor_priority = None
                if not enemy.alive:
                    # `$03EC` returns the slot immediately, so a later
                    # priority bucket or the event dispatcher may reuse it in
                    # this same VBlank. Weapon-death paths which install an
                    # explosion handler in-place are the explicit exception.
                    if not (enemy.destroyed and
                            enemy.death_effect is not None):
                        self.object_pool.release(enemy.object_slot, enemy)

        # Priority `$0010` objects run before controller `$1000`.
        run_priority_band(before_controller=True)
        self._scheduler_cursor_priority = None
        self._update_resource_owners()
        # Ordinary objects start at `$8010`.  Sorting is stable, preserving
        # `$03A6` insertion order for equal priorities.
        run_priority_band(before_controller=False)
        self._scheduler_cursor_priority = None
        event = self.current_event()
        if event is not None and progression >= event.threshold:
            self.event_pointer += 4
            self._dispatch(event)
        if self.pending:
            self.enemies.extend(self.pending)
            self.pending.clear()
        survivors = []
        for enemy in self.enemies:
            if enemy.alive:
                survivors.append(enemy)
            else:
                # Weapon-death handlers do not return the pool record.  ROM
                # paths such as `$5ED0…$5EEC` release the old resource and
                # install `$E7BE` in this same record; `$E7BE` initializes the
                # explosion on the following pass.  Natural exits still use
                # `$03EC` immediately.
                in_place_effect = (
                    enemy.destroyed and enemy.death_effect is not None)
                if not in_place_effect:
                    self.object_pool.release(enemy.object_slot, enemy)
                self.resources.release(enemy.palette)
                if isinstance(enemy, GroundWalker):
                    self.resources.release(enemy.secondary_palette)
                elif isinstance(enemy, PlayerTargeting80E3):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, LargeTerrain74B4):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Handler60BA):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, TerrainEnemy696E):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Enemy8561):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Enemy6F89):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Enemy7294):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Enemy5EED):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Formation78F8Child):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, Multipart915BChild):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, AttachedAC4C):
                    self.resources.release(enemy.alt_palette)
                elif isinstance(enemy, MultipartA71DBody):
                    self.resources.release(enemy.alt_palette)
                elif isinstance(enemy, BossB7FBCore):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, (Enemy7D68, Child8D85)):
                    self.resources.release(enemy.flash_palette)
                elif isinstance(enemy, DobkeratopsBody):
                    self.resources.release(enemy.flash_palette)
                if enemy.destroyed and enemy.score_pointer is not None:
                    self.award_score_pointer(enemy.score_pointer)
                if in_place_effect:
                    explosion = ExplosionEffect(
                        self, enemy.x, enemy.y, enemy.death_effect,
                        scheduler_priority=enemy.scheduler_priority)
                    explosion.object_slot = enemy.object_slot
                    explosion.scheduler_serial = enemy.scheduler_serial
                    # `$E7xx` replaces only selected fields of the same
                    # 64-byte record.  Q8 residue bytes `+$03/+$07` survive
                    # the handler swap and later `$03EC`; a future allocator
                    # therefore inherits them.  A new Python object must carry
                    # those bytes explicitly even though `$E7D4` itself uses
                    # only integer scroll motion.
                    if hasattr(enemy, "x_fraction"):
                        explosion.x_fraction = enemy.x_fraction
                    if hasattr(enemy, "y_fraction"):
                        explosion.y_fraction = enemy.y_fraction
                    enemy.object_slot = None
                    # `$E7BE/$E7AE/$E7B6/$E7A6` fall straight through to
                    # `$E7D4` in their initializer pass; there is no RET
                    # between handler install and the first timer decrement.
                    explosion.update(self, self._scheduler_foreground_delta)
                    survivors.append(explosion)
        self.enemies = survivors

    def _dispatch(self, event: StageEvent) -> None:
        if event.handler == 0x596D:
            self.pending.append(RedFlyer(self, event.command))
        elif event.handler == 0x5A02:
            self.pending.append(GroundWalker(self, event.command))
        elif event.handler == 0x5DC8:
            self.pending.append(FormationParent(self, event.command))
        elif event.handler == 0x55E9:
            self.pending.append(TerrainBound55E9(self, event.command))
        elif event.handler == 0x80E3:
            self.pending.append(PlayerTargeting80E3(self, event.command))
        elif event.handler == 0x897E:
            self.pending.append(TerrainAware897E(self, event.command))
        elif event.handler == 0x74B4:
            self.pending.append(LargeTerrain74B4(self, event.command))
        elif event.handler == 0x86A6:
            self.pending.append(Animated86A6(self, event.command))
        elif event.handler == 0x875D:
            self.pending.append(Spawner875D(self))
        elif event.handler == 0x8469:
            self.pending.append(Enemy8469(self, event.command))
        elif event.handler == 0x8561:
            self.pending.append(Enemy8561(self, event.command))
        elif event.handler == 0x8F5E:
            self.pending.append(Enemy8F5E(self, event.command))
        elif event.handler == 0x8C12:
            self.pending.append(StageObject8C12(self, event.command))
        elif event.handler == 0x60BA:
            self.pending.append(Handler60BA(self, event.command))
        elif event.handler == 0x5CEA:
            self.pending.append(Enemy5CEA(self, event.command))
        elif event.handler == 0x5EED:
            self.pending.append(Enemy5EED(self, event.command))
        elif event.handler == 0x696E:
            self.pending.append(TerrainEnemy696E(self, event.command))
        elif event.handler == 0x6A9B:
            self.pending.append(TerrainModifierParent6ACB())
        elif event.handler == 0x6E9B:
            self.pending.append(FixedLarge6E9B(self))
        elif event.handler == 0x9660:
            self.pending.append(FinalSpawner9660(self, event.command))
        elif event.handler == 0x6F89:
            self.pending.append(Enemy6F89(self, event.command))
        elif event.handler == 0x7182:
            self.pending.append(Enemy7182(self, event.command))
        elif event.handler == 0x7294:
            self.pending.append(Enemy7294(self, event.command))
        elif event.handler == 0x78F8:
            self.pending.append(Formation78F8Parent(self, event.command))
        elif event.handler == 0x7D68:
            self.pending.append(Enemy7D68(self, event.command))
        elif event.handler == 0x915B:
            self.pending.append(Multipart915BParent(self, event.command))
        elif event.handler == 0xA71D:
            self.pending.append(MultipartA71DController(self))
        elif event.handler == 0xB7FB:
            self.pending.append(BossB7FBController(self))
        elif event.handler == 0x98FD:
            self.pending.append(DobkeratopsRoot(self))
        elif event.handler == 0xF366:
            player = 1 if self.active_player else 0
            if self.stage_transition_flags[player] == 0:
                # `$F378…$F397`: the first call marks this player, sends
                # `$21` now and schedules `$20` after `$0180` updates.
                self.stage_transition_flags[player] = 1
                self.sound_commands.append(0x21)
                self.pending.append(TimedControlF3C1(0x0180, 0x20))
            else:
                # `$F398…$F3C0`: subsequent calls select two literal byte
                # tables with unsigned `$2FC5` and use the shorter delay.
                index = self.transition_sound_index & 0xFF
                self.sound_commands.append(self.rom.byte(0x8C16 + index))
                self.pending.append(TimedControlF3C1(
                    0x0100, self.rom.byte(0x8C0C + index)))
        elif event.handler == 0xF130:
            # Normal fixed-player branch `$F153…$F1BE`.  All writes happen
            # after the current `$0467`: the scroll owner commits their zero
            # accumulator/velocity state at the following VBlank callback.
            self.cleanup_active = True
            self.scroll_reset_command = True
            self.foreground_velocity_command = 0
            self.background_velocity_command = 0
            self.pending.append(StageTransitionF1BF())
        elif event.handler == 0xF01B:
            # `$F020…$F0D8`: 14-byte checkpoint selected by command low
            # five bits.  It replaces progression, scroll velocities and the
            # next stage's event range before `$F43B` allocates `$F44E` at
            # caller-supplied priority `$FFFE`.
            index = event.command & 0x1F
            record = 0x87FA + index * 14
            progression = self.rom.word(record)
            foreground_velocity = self.rom.word(record + 6)
            background_velocity = self.rom.word(record + 8)
            packed_resource_music = self.rom.word(record + 10)
            stage_word = self.rom.word(record + 12)
            next_stage = stage_word & 0xFF
            self.transition_sound_index = (
                packed_resource_music >> 8) & 0x0F
            player = 1 if self.active_player else 0
            if self.stage_transition_flags[player] == 0:
                self.sound_commands.append(0x1F)
            else:
                self.sound_commands.append(self.rom.byte(
                    0x8C02 + self.transition_sound_index))
            self.stage = next_stage
            self.event_pointer, self.event_last = STAGE_EVENT_RANGES[next_stage]
            self.player_exit_latch = 0
            self.stage_init_scroll_command = (
                progression, foreground_velocity, background_velocity)
            self.pending.append(InvulnerabilityTimerF44E(
                self, scheduler_priority=0xFFFE))
        elif event.handler == 0xE430:
            object_slot = self.object_pool.take()
            if object_slot is None:
                self.allocation_failures.append(
                    (self.frame_counter, "particle_controller_e4a5"))
                return
            index = event.command & 3
            record = 0x8314 + index * 6
            remaining = self.rom.word(record)
            velocity_table = self.rom.word(record + 2)
            cadence = self.rom.word(record + 4)
            slots = tuple(self.resources.acquire(kind)
                          for kind in (0x57, 0x59, 0x5A, 0x5C))
            self.resource_owners.append(ParticleControllerE4A5(
                remaining, slots, velocity_table, cadence, 0,
                object_slot))
        elif event.handler == 0xFB9C:
            self.pending.append(PaletteCycleFBED(self, event.command))
        elif event.handler == 0xF461:
            self.pending.append(CleanupTimerF477(self))
        elif event.handler in self.DELEGATED_HANDLERS:
            self.delegated_events.append(event)
        else:
            self.unsupported_events.append(event)

    def _update_resource_owners(self) -> None:
        survivors: list[ParticleControllerE4A5] = []
        for owner in self.resource_owners:
            # `$E4AC/$E4AF`: cleanup happens immediately on the zero pass and
            # skips palette and particle work below.
            owner.remaining = _u16(owner.remaining - 1)
            if owner.remaining == 0:
                for slot in owner.slots:
                    self.resources.release(slot)
                self.object_pool.release(owner.object_slot, owner)
                continue

            # `$E532…$E567`: unsigned word counter and allocation cadence.
            # During the final 63 updates the ROM stores a random negative
            # word after every spawn; unsigned `JB` then makes the next update
            # spawn again, producing the literal end burst.
            owner.spawn_counter = _u16(owner.spawn_counter + 1)
            if owner.spawn_counter < owner.cadence:
                survivors.append(owner)
                continue
            owner.spawn_counter = 0
            if owner.remaining < 0x40:
                owner.spawn_counter = _u16(-((self.rng.next() & 7) + 6))
            self.pending.append(BackgroundParticleE5CD(owner.velocity_table))
            survivors.append(owner)
        self.resource_owners = survivors

    def note_projectile_spawn(self, _enemy: Enemy) -> None:
        self.projectile_spawns += 1
        velocity_table = getattr(_enemy, "projectile_script", 0)
        if velocity_table:
            self.pending.append(EnemyProjectile(self, _enemy, velocity_table))

    def emit_transient_sprite(self, descriptor: int, palette: int,
                              resource_type: int, x: int, y: int) -> None:
        """Remember one literal sprite-RAM emission after its object freed."""
        self.transient_sprites.append((
            descriptor & 0xFFFF, palette & 0xFF, resource_type & 0xFF,
            x & 0xFFFF, y & 0xFFFF))

    def request_player_shot_visual(self) -> None:
        """Set the one-byte `$0038` request consumed by fixed handler `$4ED8`."""
        self.player_shot_visual_requests = 1

    @staticmethod
    def _add_packed_bcd(target: bytearray, increment: bytes) -> None:
        """Execute the four-byte decimal result of NEC `ADD4S` at `$E8EF`."""
        carry = 0
        for nibble in range(8):
            shift = 4 * (nibble & 1)
            index = nibble >> 1
            value = ((target[index] >> shift) & 0x0F)
            value += ((increment[index] >> shift) & 0x0F) + carry
            if value >= 10:
                value -= 10
                carry = 1
            else:
                carry = 0
            target[index] &= ~(0x0F << shift)
            target[index] |= value << shift
        if target[3] & 0xF0:
            target[:] = SCORE_BCD_MAX

    def award_score_pointer(self, pointer: int) -> None:
        """Run the score-bearing part of task `$E8BD` for one ROM record."""
        if (pointer < SCORE_INCREMENT_FIRST or pointer > SCORE_INCREMENT_LAST
                or (pointer - SCORE_INCREMENT_FIRST) & 3):
            raise ValueError(f"неверный указатель BCD-награды ${pointer:04X}")
        increment = bytes(self.rom.byte(pointer + index) for index in range(4))
        self._add_packed_bcd(self.score_bcd, increment)
        self._add_packed_bcd(self.stage_score_bcd, increment)
        self.score_awards.append(pointer)
        # `$ED1F…$ED5F`: одна проверка за задачу — очки больше записи таблицы (порог
        # минус один). Указатель сдвигается и при полном запасе; жизнь прибавляется
        # только ниже предела (`$ED56`, патч баланса) со звуком `$38`.
        if (self.bonus_index < len(BONUS_LIFE_THRESHOLDS)
                and self.score >= BONUS_LIFE_THRESHOLDS[self.bonus_index]):
            self.bonus_index += 1
            if self.lifecycle is not None and self.lifecycle.award_life():
                self.sound_commands.append(0x38)
        self.hud_refresh = True

    def take_scroll_velocity_commands(self) -> tuple[int | None, int | None]:
        foreground = self.foreground_velocity_command
        background = self.background_velocity_command
        self.foreground_velocity_command = None
        self.background_velocity_command = None
        return foreground, background

    def take_scroll_reset_command(self) -> bool:
        reset = self.scroll_reset_command
        self.scroll_reset_command = False
        return reset

    def take_stage_init_scroll_command(self) -> tuple[int, int, int] | None:
        command = self.stage_init_scroll_command
        self.stage_init_scroll_command = None
        return command

    def take_sound_commands(self) -> tuple[int, ...]:
        """Забрать буквальные команды `$0303`, накопленные за проход."""
        commands = tuple(self.sound_commands)
        self.sound_commands.clear()
        return commands

    @staticmethod
    def _packed_bcd_value(value: bytes | bytearray) -> int:
        result = 0
        multiplier = 1
        for byte in value:
            result += (byte & 0x0F) * multiplier
            multiplier *= 10
            result += ((byte >> 4) & 0x0F) * multiplier
            multiplier *= 10
        return result

    @property
    def score(self) -> int:
        return self._packed_bcd_value(self.score_bcd)

    @property
    def stage_score(self) -> int:
        return self._packed_bcd_value(self.stage_score_bcd)

    def terrain_at(self, x: int, y: int) -> int:
        return self._terrain_code(x, y) if self._terrain_code is not None else 0x0FFF

    def collision_at(self, x: int, y: int) -> tuple[int, int]:
        if self._collision_codes is not None:
            return self._collision_codes(x, y)
        return self.terrain_at(x, y), 0x0FFF

    def terrain_address(self, x: int, y: int) -> int:
        return self._terrain_address(x, y) if self._terrain_address else 0

    def erase_terrain(self, address: int) -> None:
        if self._erase_terrain is not None:
            self._erase_terrain(address)

    def replace_terrain(self, address: int, code: int, attribute: int) -> None:
        if self._replace_terrain is not None:
            self._replace_terrain(address, code, attribute)

    def terrain_cell(self, address: int) -> tuple[int, int]:
        return (self._terrain_cell(address) if self._terrain_cell is not None
                else (0x0FFF, 0))

    def _damage_with_scheduler_cursor(self, enemy: Enemy, damage: int) -> None:
        """Apply a weapon hit at the target handler's live ROM cursor.

        Python performs the fixed-weapon scans after ``world.update``.  In
        the original, each enemy calls those scans from inside its own
        handler.  Restoring that priority while ``take_damage`` runs lets
        `$03A6` execute a higher-priority explosion/projectile immediately;
        promoting the resulting records now also makes them schedulable on
        the following VBlank instead of stranding them in ``pending`` for an
        extra pass.
        """
        pending_start = len(self.pending)
        previous_cursor = self._scheduler_cursor_priority
        self._scheduler_cursor_priority = enemy.scheduler_priority
        try:
            enemy.take_damage(self, damage)
        finally:
            self._scheduler_cursor_priority = previous_cursor
        spawned = list(self.pending[pending_start:])
        if spawned:
            del self.pending[pending_start:]
            self.enemies.extend(spawned)

    def damage_at(self, rect: pygame.Rect, damage: int = 1) -> bool:
        for enemy in self.enemies:
            # Every ordinary-shot dispatcher `$F694/$F6DA/$F75F/$F7E4`
            # returns immediately while object.X >= `$02B4`.  Objects may be
            # visible at the right edge before becoming weapon-active.
            if (enemy.alive and enemy.x < 0x02B4 and enemy.shootable and
                    enemy.weapon_vulnerable and
                    rect.colliderect(enemy.hitbox(self.rom))):
                self._damage_with_scheduler_cursor(enemy, damage)
                return True
        return False

    def consume_weapon_pickup(self) -> bool:
        """Execute the player-record `$216D…$2182` pending pickup step."""
        if not self.weapon_pickups:
            return False
        self.weapon_pickups = (self.weapon_pickups - 1) & 0xFF
        if self.force_level < 3:
            self.force_level += 1
        return True

    def damage_shot_native(
            self, bounds: tuple[int, int, int, int], damage: int = 1) -> bool:
        """Run one ordinary-shot `$F548/$F578` scan in scheduler order."""
        left, right, lower, upper = bounds
        scheduled = sorted(
            enumerate(self.enemies),
            key=lambda item: (item[1].scheduler_priority,
                              -item[1].scheduler_serial, item[0]))
        for _insertion_order, enemy in scheduled:
            if (not enemy.alive or enemy.x >= 0x02B4 or
                    not enemy.shootable or not enemy.weapon_vulnerable):
                continue
            enemy_left, enemy_right, enemy_lower, enemy_upper = (
                enemy.native_hitbox(self.rom))
            # `$F578` is deliberately asymmetric.  When the target anchor is
            # left/below the shot, adding its positive extent and landing
            # exactly on the shot edge succeeds (`JAE`).  The negative extent
            # must still lie strictly before the opposite edge (`JB`).
            if (left <= enemy_right and right > enemy_left and
                    lower <= enemy_upper and upper > enemy_lower):
                self._damage_with_scheduler_cursor(enemy, damage)
                return True
        return False

    def damage_force_at(
            self, rects: list[pygame.Rect] | tuple[pygame.Rect, ...],
            cadence_tick: bool) -> int:
        """Execute Force/Bit collision order used by `$F493/$F694/$F6DA`."""
        hits = 0
        for enemy in tuple(self.enemies):
            if (enemy.alive and enemy.shootable and
                    # `$E601` performs its Force-only `$E64E` check directly
                    # and does not pass through the enemy X gate.
                    (not enemy.weapon_vulnerable or enemy.x < 0x02B4) and
                    (cadence_tick or not enemy.force_damage_cadenced) and any(
                    rect.colliderect(enemy.hitbox(self.rom))
                    for rect in rects)):
                self._damage_with_scheduler_cursor(enemy, 1)
                hits += 1
        return hits

    def damage_force_native(
            self,
            bounds: list[tuple[int, int, int, int]] |
                    tuple[tuple[int, int, int, int], ...],
            cadence_tick: bool,
            force_bounds: tuple[tuple[int, int, int, int], ...] | None = None
            ) -> int:
        """Run `$F493/$F578` on unscaled native endpoint records.

        `$F578` accepts equality on the source-left/target-right and
        source-lower/target-upper comparisons.  Converting both records to
        640x480 pygame rectangles loses those edge contacts; the Stage-1
        `$74B4` object at VBlank 4935 is one literal case.
        """
        hits = 0
        for enemy in tuple(self.enemies):
            if (not enemy.alive or not enemy.shootable or
                    (enemy.weapon_vulnerable and enemy.x >= 0x02B4) or
                    (enemy.force_damage_cadenced and not cadence_tick)):
                continue
            enemy_left, enemy_right, enemy_lower, enemy_upper = (
                enemy.native_hitbox(self.rom))
            source_bounds = (force_bounds if enemy.force_collision_only and
                             force_bounds is not None else bounds)
            if not any(
                    left <= enemy_right and right > enemy_left and
                    lower <= enemy_upper and upper > enemy_lower
                    for left, right, lower, upper in source_bounds):
                continue
            self._damage_with_scheduler_cursor(enemy, 1)
            hits += 1
        return hits

    def damage_wave_at(self, rect: pygame.Rect, power: int) -> int:
        """Execute Wave accounting from `$F703…$F717` for every enemy.

        Each intersected enemy receives the current Wave power.  The Wave
        accumulator gets that enemy's HP still remaining before this hit;
        `$328A…$3294` subtracts the accumulated byte from Wave power later.
        """
        cost = 0
        for enemy in tuple(self.enemies):
            if (enemy.alive and enemy.x < 0x02B4 and enemy.shootable and
                    enemy.weapon_vulnerable and
                    rect.colliderect(enemy.hitbox(self.rom))):
                remaining_hp = max(0, enemy.hp)
                self._damage_with_scheduler_cursor(enemy, power)
                cost = (cost + remaining_hp) & 0xFF
        return cost

    def player_collision(self, rect: pygame.Rect) -> bool:
        for enemy in self.enemies:
            if (enemy.hostile and enemy.palette != 0xFF and
                    rect.colliderect(enemy.hitbox(self.rom))):
                contact = getattr(enemy, "player_contact", None)
                if contact is not None:
                    contact(self)
                return True
        return False

    def draw(self, target: pygame.Surface) -> None:
        for enemy in self.enemies:
            if enemy.palette == 0xFF:
                continue
            if not getattr(enemy, "render_ready", True):
                continue
            if (isinstance(enemy, BackgroundParticleE5CD) and
                    not enemy.render_ready):
                continue
            if (isinstance(enemy, Targeting80E3AttackFlash) and
                    not enemy.visible):
                continue
            palette = (enemy.active_palette if isinstance(
                enemy, (GroundWalker, PlayerTargeting80E3, LargeTerrain74B4,
                        Handler60BA, Enemy8561, TerrainEnemy696E,
                        Enemy6F89, Enemy7294, Enemy5EED,
                        Formation78F8Child,
                        Multipart915BChild,
                        AttachedAC4C, MultipartA71DBody,
                        BossB7FBCore,
                        Enemy7D68, Child8D85,
                        DobkeratopsBody))
                       else enemy.palette)
            resource_type = self.resources.types[palette]
            self.atlas.draw(target, read_descriptor(self.rom, enemy.descriptor),
                            palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, PlayerTargeting80E3):
                # `$80E3/$8138` is one logical enemy drawn by two adjacent
                # 6-byte ROM descriptors.  The first descriptor is the left
                # 32x64 half and the second (`+6`) is the right half.  Drawing
                # only the table pointer itself cut the first mini-boss in
                # half even though its movement/collision object was intact.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Targeting80E3Projectile):
                # `$842C` emits an adjacent descriptor pair via `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if (isinstance(enemy, ExplosionEffect) and
                    enemy.effect == "e817"):
                # `$E82D` calls the two-record emitter `$1C1B`, not the
                # one-record `$1BCC`: every `$85FA` frame is a 12-byte pair.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Handler5CEAShot):
                # `$E6DA` calls the two-record composite emitter `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Enemy8561):
                # `$85EF` uses the two-record composite emitter `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Enemy6F89):
                # All `$6FD0/$709F/$7123` render paths call `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Enemy5EED):
                # `$5FBB/$5FC4` uses the two-record composite emitter.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Handler60BA):
                # Every main `$610D…$6619` render path emits the adjacent
                # two-record composite.  These are the two Stage-1
                # mini-boss instances; drawing only the first descriptor
                # leaves exactly one 32x48 native half on screen.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if (isinstance(enemy, Formation78F8Child) and
                    enemy.state == "first"):
                # `$79FC/$7D45` emits the adjacent descriptor pair via `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, (Enemy7D68, Child8D85)):
                # `$8035` and all three `$8D85` drawing states use `$1C1B`.
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, MultipartA71DBody):
                if enemy.body_kind == "upper":
                    extra = (0x5A08, 0x5A0E, 0x5A14, 0x5A1A, 0x5A20)
                elif enemy.body_kind == "middle":
                    extra = (0x5A4C, 0x5A52, 0x5A58, 0x5A5E, 0x5A64)
                else:
                    extra = (0x5A88, 0x5A8E, 0x5A94)
                for descriptor in extra:
                    self.atlas.draw(
                        target, read_descriptor(self.rom, descriptor),
                        palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, (BossB7FBSegment, BossB7FBMissile,
                                  BossB7FBCore)):
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.descriptor + 6),
                    palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, FixedLarge6E9B):
                # `$6EEF…$6F04` emits four adjacent composite roots.
                for descriptor in (0x3048, 0x304E, 0x3054, 0x305A,
                                   0x3060, 0x3066, 0x306C):
                    self.atlas.draw(
                        target, read_descriptor(self.rom, descriptor),
                        palette, resource_type, enemy.x, enemy.y)
            if isinstance(enemy, Handler60BAChild):
                self.atlas.draw(
                    target, read_descriptor(self.rom, enemy.overlay_descriptor),
                    palette, resource_type, enemy.overlay_x, enemy.overlay_y)
        for descriptor, palette, resource_type, x, y in self.transient_sprites:
            self.atlas.draw(target, read_descriptor(self.rom, descriptor),
                            palette, resource_type, x, y)
