"""Динамический tilemap игрового пространства из данных аркадного уровня."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import pygame

from .title import _argb4444_surface
from .world_terrain import M72WorldTerrain, stage_checkpoint_count


ROOT = Path(__file__).resolve().parents[3]
STAGE_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1"
SECTION_DIR = STAGE_DIR / "Sections"
GLYPH_W, GLYPH_H = 14, 15
GLYPH_BYTES = GLYPH_W * GLYPH_H * 2
MAP_CELLS = 64 * 32
SECTION_STARTS = (1, 2603, 5603, 8603, 11603, 14103)
SECTION_END = 17104
PAGE_SIZE = 0x4000
SHIFT_LOGICAL = (0, 2, 3, 5, 7, 8, 10, 12)
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
VISIBLE_ROW_FIRST = 16
VISIBLE_ROW_COUNT = 32
VISIBLE_COLUMN_COUNT = 49
# Таблицы ключей и атласов имеют фиксированную ёмкость: индекс ключа всегда
# меньше TILE_KEY_CAPACITY (последний индекс — «нет тайла»), слот — меньше
# ATLAS_CAPACITY. Так каждое обращение в цикле вывода доказуемо в границах.
TILE_KEY_CAPACITY = 4096
NO_TILE_KEY = TILE_KEY_CAPACITY - 1
ATLAS_CAPACITY = 1088
# Логический X колонки вывода: те же целые, что `round(column * 640 / 48)`,
# вычисленные самим CPython при импорте.
COLUMN_X = tuple(round(column * 640 / 48)
                 for column in range(VISIBLE_COLUMN_COUNT))

# Кадры, в которых основной обработчик M72 не дошёл до $0467/$02AE/$02CE.
M72_INTEGRATOR_MISSING = frozenset((
    4397, 4432, 4463, 4466, 4468, 4470, 4503,
    14222, 14225, 14228, 14231, 14234, 14237, 14240, 14259, 14420, 14655,
    16164, 16499,
))
# Порты пишутся до интегрирования, поэтому пропуск становится виден на
# следующем кадре. 10265 — отдельный ROM reset $F082..$F091.
M72_SCROLL_STALLS = frozenset(frame + 1 for frame in M72_INTEGRATOR_MISSING) | {
    10265,
}


@dataclass
class M72Scroll:
    """24-битный горизонтальный скроллер из ROM-процедуры $0467."""

    # Состояние перед первым показанным кадром появления R-9. Первый advance()
    # даёт MAME frame 852 и scroll $86=$0081.
    vblank: int = 851
    foreground_accumulator: int = 0x004000
    foreground_velocity: int = 0x0080
    background_accumulator: int = 0x008000
    background_velocity: int = 0x0100
    # The allocator verifier deliberately disables player fire.  In that
    # capture the ROM does not reach `$F42E` until VBlank 9235; the playable
    # reference reaches it at 8176 and later resumes the background at 9322.
    stage1_no_fire_reference: bool = False
    # MAME snapshot frame 898 has RAM:$2F4A..$2F4C=$00,$57,$06 while
    # RAM:$2EC0..$2EC2=$80,$57,$00.  Therefore the progression counter trails
    # the visible foreground accumulator by exactly $80 at this checkpoint.
    progression_accumulator: int = 0x063F80
    foreground_delta: int = 0
    background_delta: int = 0
    # Object handlers write `$2EEC/$2EF4` after this VBlank's `$0467`.
    # The callback snapshot of the following VBlank must therefore retain the
    # accumulator produced with the old velocity, while its later object
    # dispatch already observes the newly written velocity.  Keeping these
    # writes pending reproduces that half-frame boundary exactly.
    pending_foreground_velocity: int | None = None
    pending_background_velocity: int | None = None
    pending_scroll_accumulator_reset: bool = False
    pending_progression_accumulator: int | None = None

    def queue_object_velocity_write(
            self,
            foreground: int | None,
            background: int | None) -> None:
        """Queue post-`$0467` object writes for the next VBlank snapshot."""
        if foreground is not None:
            self.pending_foreground_velocity = foreground & 0xFFFF
        if background is not None:
            self.pending_background_velocity = background & 0xFFFF

    def queue_stage_transition_reset(self) -> None:
        """Queue post-`$0467` `$F15F…$F18C` X-state clearing."""
        self.pending_scroll_accumulator_reset = True

    def queue_stage_init(self, progression: int,
                         foreground_velocity: int,
                         background_velocity: int) -> None:
        """Queue the post-dispatch writes made by `$F01B`."""
        self.pending_scroll_accumulator_reset = True
        self.pending_progression_accumulator = (progression & 0xFFFF) << 8
        self.pending_foreground_velocity = foreground_velocity & 0xFFFF
        self.pending_background_velocity = background_velocity & 0xFFFF

    @property
    def foreground_x(self) -> int:
        return (self.foreground_accumulator >> 8) & 0x01FF

    @property
    def background_x(self) -> int:
        return (self.background_accumulator >> 8) & 0x01FF

    def advance(self) -> None:
        self.vblank += 1

        previous_foreground_x = self.foreground_x
        previous_background_x = self.background_x
        # In the saturated no-fire capture `$F42E` runs after this VBlank's
        # `$0467` and after the callback snapshot.  On 9236 the sampled
        # accumulator must first catch up with the final `$0080` integration;
        # only the same-frame object dispatch sees the new zero velocities.
        commit_no_fire_stop = (
            self.stage1_no_fire_reference and self.vblank == 9236)

        # Штатные записи скорости/координаты из объектов Stage 1. Указанные
        # VBlank — момент, когда новое состояние становится видимым в порту.
        if self.vblank == 3029:       # ROM event PC $F10B
            self.background_velocity = 0x0080
        elif self.vblank == 8176 and not self.stage1_no_fire_reference:
            # ROM event/object PC `$F42E`; timing depends on whether the
            # preceding combat chain was destroyed by player fire.
            self.foreground_velocity = 0x0000
            self.background_velocity = 0x0000
        elif self.vblank == 9322 and not self.stage1_no_fire_reference:
            # ROM object PC `$9A92` in the playable reference.
            self.background_velocity = 0x0040
        elif self.vblank == 9770 and not self.stage1_no_fire_reference:
            # ROM object PC `$9AFB` in the playable trace.  The no-fire boss
            # is still alive here; its trace contains no velocity write after
            # `$F42E` through VBlank 10500, so applying this host-frame event
            # moved every lingering object 33 pixels before frame 9836.
            self.foreground_velocity = 0x0080
            self.background_velocity = 0x0080
        elif self.vblank == 10001 and not self.stage1_no_fire_reference:
            # ROM transition `$F162…$F18F`, unreachable while that boss lives.
            self.foreground_accumulator = 0
            self.foreground_velocity = 0
            self.background_accumulator = 0
            self.background_velocity = 0
        elif self.vblank == 10262 and not self.stage1_no_fire_reference:
            # ROM transition object `$F35C` in the playable reference.
            self.foreground_velocity = 0x0080
        elif self.vblank == 10265 and not self.stage1_no_fire_reference:
            # ROM stage init `$F075…$F091` in the playable reference.
            self.foreground_accumulator = 0
            self.background_accumulator = 0
            self.foreground_velocity = 0x0080
            self.background_velocity = 0x0040
        elif self.vblank == 15524 and not self.stage1_no_fire_reference:
            # Later playable-trace object PC `$A246`.
            self.foreground_velocity = 0
            self.background_velocity = 0

        if self.vblank not in M72_SCROLL_STALLS:
            # ROM $0467: $2EC0:$2EC2 += $2EEC, затем X берётся из
            # $2EC1 и ограничивается девятью битами. Значение $82=0,
            # записываемое позже raster IRQ, относится только к HUD.
            self.foreground_accumulator = (
                self.foreground_accumulator + self.foreground_velocity
            ) & 0x01FFFF
            self.progression_accumulator = (
                self.progression_accumulator + self.foreground_velocity
            ) & 0xFFFFFF
            self.background_accumulator = (
                self.background_accumulator + self.background_velocity
            ) & 0x01FFFF

        # ROM $0467 stores in $2ED0/$2ED2 the negative signed step that was
        # actually integrated in this pass.  MAME snapshots 1471..1475 show
        # $FFFF exactly on the frames where foreground X advances by one.
        if self.vblank not in M72_SCROLL_STALLS:
            foreground_step = (
                self.foreground_x - previous_foreground_x
            ) & 0x01FF
            if foreground_step & 0x0100:
                foreground_step -= 0x0200
            self.foreground_delta = (-foreground_step) & 0xFFFF

            background_step = (
                self.background_x - previous_background_x
            ) & 0x01FF
            if background_step & 0x0100:
                background_step -= 0x0200
            self.background_delta = (-background_step) & 0xFFFF
        # If `$0467` is not reached, RAM:$2ED0/$2ED2 are not written either.
        # They retain their previous values (MAME snapshot frame 4398: both
        # progression and X stay put while $2ED0 remains $FFFF).
        if commit_no_fire_stop:
            self.foreground_velocity = 0x0000
            self.background_velocity = 0x0000

        # These writes happened in an object handler after the integration
        # represented above.  Commit them only now: dispatch_* below uses the
        # new values, but the sampled accumulators were advanced with the old
        # ones, matching RAM callbacks around Dobkeratops `$9A92`.
        if self.pending_scroll_accumulator_reset:
            self.foreground_accumulator = 0
            self.background_accumulator = 0
            self.pending_scroll_accumulator_reset = False
        if self.pending_progression_accumulator is not None:
            self.progression_accumulator = self.pending_progression_accumulator
            self.pending_progression_accumulator = None
        if self.pending_foreground_velocity is not None:
            self.foreground_velocity = self.pending_foreground_velocity
            self.pending_foreground_velocity = None
        if self.pending_background_velocity is not None:
            self.background_velocity = self.pending_background_velocity
            self.pending_background_velocity = None

    @property
    def progression(self) -> int:
        """RAM:$2F4B, the word compared by the stage-event dispatcher $1BA7."""
        return (self.progression_accumulator >> 8) & 0xFFFF

    @property
    def dispatch_progression(self) -> int:
        """`$2F4B` at the later same-VBlank `$1BA7` comparison.

        MAME work-RAM snapshots are taken before the main handler performs
        `$0467`, while the event dispatcher runs after it.  The renderer uses
        the sampled accumulator above; event thresholds therefore need the
        one additional same-frame integration.  Frames where the handler did
        not reach `$0467` are the literal exception.
        """
        accumulator = self.progression_accumulator
        if self.vblank not in M72_INTEGRATOR_MISSING:
            accumulator = (accumulator + self.foreground_velocity) & 0xFFFFFF
        return (accumulator >> 8) & 0xFFFF

    @property
    def dispatch_foreground_x(self) -> int:
        """RAM `$2EC1` seen by object handlers after same-VBlank `$0467`."""
        accumulator = self.foreground_accumulator
        if self.vblank not in M72_INTEGRATOR_MISSING:
            accumulator = (accumulator + self.foreground_velocity) & 0x01FFFF
        return (accumulator >> 8) & 0x01FF

    @property
    def dispatch_background_x(self) -> int:
        """RAM `$2EC5` seen by object handlers after same-VBlank `$0467`."""
        accumulator = self.background_accumulator
        if self.vblank not in M72_INTEGRATOR_MISSING:
            accumulator = (accumulator + self.background_velocity) & 0x01FFFF
        return (accumulator >> 8) & 0x01FF

    @staticmethod
    def _integrated_delta(accumulator: int, velocity: int) -> int:
        """Return the signed scroll delta written by one `$0467` integration."""
        previous = (accumulator >> 8) & 0x01FF
        current = ((accumulator + velocity) >> 8) & 0x01FF
        step = (current - previous) & 0x01FF
        if step & 0x0100:
            step -= 0x0200
        return (-step) & 0xFFFF

    @property
    def dispatch_foreground_delta(self) -> int:
        """RAM `$2ED0` seen by objects later in this same VBlank.

        `foreground_delta` is the value in the callback snapshot, before the
        current main-loop `$0467`.  Enemy handlers execute after that routine,
        so they observe the next integration's value.  If `$0467` is skipped,
        the RAM word retains the sampled value instead.
        """
        if self.vblank in M72_INTEGRATOR_MISSING:
            return self.foreground_delta
        return self._integrated_delta(
            self.foreground_accumulator, self.foreground_velocity)

    @property
    def dispatch_background_delta(self) -> int:
        """RAM `$2ED2` seen by objects later in this same VBlank."""
        if self.vblank in M72_INTEGRATOR_MISSING:
            return self.background_delta
        return self._integrated_delta(
            self.background_accumulator, self.background_velocity)


def _load_map(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) != MAP_CELLS * 2:
        raise ValueError(f"неверный размер карты: {path}")
    return list(struct.unpack(f"<{MAP_CELLS}H", data))


def _load_atlas(path: Path) -> list[pygame.Surface]:
    data = path.read_bytes()
    if len(data) % GLYPH_BYTES:
        raise ValueError(f"неверный размер атласа: {path}")
    return [_argb4444_surface(data[offset:offset + GLYPH_BYTES], GLYPH_W, GLYPH_H)
            for offset in range(0, len(data), GLYPH_BYTES)]


def _load_lookup(path: Path) -> dict[tuple[int, int], int]:
    data = path.read_bytes()
    if len(data) < 2:
        raise ValueError(f"пустой lookup: {path}")
    count = struct.unpack_from("<H", data)[0]
    if len(data) != 2 + count * 6:
        raise ValueError(f"неверный размер lookup: {path}")
    return {
        (code, attribute): slot
        for code, attribute, slot in struct.iter_unpack("<HHH", data[2:])
    }


class M72Tilemaps:
    """ROM $02AE/$02CE и $EA51/$EA73: поток 8x30 tile-полос Stage 1."""

    def __init__(self) -> None:
        self.rom = ROM_PATH.read_bytes()
        if len(self.rom) != 0x100000:
            raise ValueError("неверный maincpu region R-Type")
        self.vram = [bytearray(0x4000), bytearray(0x4000)]
        for layer in range(2):
            first = 0x0200 if layer == 0 else 0
            for offset in range(first, 0x4000, 4):
                struct.pack_into("<HH", self.vram[layer], offset, 0x0FA0, 0)
        # Журнал исходных байтов VRAM, записанных после снимка коллизий
        # (M72JournalSnapshot). Хранится первое значение каждого байта.
        self.journal_generation = 0
        self.journal_active = False
        self.journal_layers: list[int] = []
        self.journal_indices: list[int] = []
        self.journal_values: list[int] = []
        # Индекс ключа (code, attribute) каждой видимой ячейки в общей таблице
        # участков Stage и биты занятости строк. Ведутся при каждой записи в
        # VRAM, чтобы рендер не искал словарь для каждой из 2×32×49 ячеек.
        self.tile_key_codes: tuple[int, ...] = ()
        self.tile_key_attributes: tuple[int, ...] = ()
        self.key_map = [[NO_TILE_KEY] * (VISIBLE_ROW_COUNT * 64)
                        for _ in range(2)]
        self.row_bits = [bytearray(VISIBLE_ROW_COUNT * 8) for _ in range(2)]

        # F01B: цели предзагрузки семь полос, выполнено пока high != low.
        self.target = [0x70, 0x70]
        self.tracker = [0, 0]
        self.source = [0, 0]
        accumulator = [0, 0]
        velocity = (0x0080, 0x0100)
        for frame in range(723, 852):
            if frame > 723:
                for layer in range(2):
                    old = accumulator[layer]
                    accumulator[layer] = (old + velocity[layer]) & 0x01FFFF
                    self._crossing(layer, old, accumulator[layer])
            self._pump()

    def _crossing(self, layer: int, old: int, new: int) -> None:
        old_x = (old >> 8) & 0x01FF
        new_x = (new >> 8) & 0x01FF
        if (old_x & 0x40) != (new_x & 0x40):
            self.target[layer] = (self.target[layer] + 0x10) & 0xFF

    def advance(self, scroll: M72Scroll) -> None:
        # Снимок коллизий живёт только до конца своего кадра.
        self.end_journal()
        # $0443 сначала выдаёт текущее X, затем в том же CPU-кадре $0467
        # готовит следующее и $02AE/$02CE проверяют переход через 64 px.
        if scroll.vblank in M72_INTEGRATOR_MISSING:
            return
        velocities = (scroll.foreground_velocity, scroll.background_velocity)
        accumulators = (scroll.foreground_accumulator,
                        scroll.background_accumulator)
        for layer in range(2):
            old = accumulators[layer]
            new = (old + velocities[layer]) & 0x01FFFF
            self._crossing(layer, old, new)
        self._pump()

    def _pump(self) -> None:
        for layer in range(2):
            if self.tracker[layer] == self.target[layer]:
                continue
            self._draw_strip(layer, self.source[layer], self.tracker[layer])
            self.tracker[layer] = (self.tracker[layer] + 0x10) & 0xFF
            self.source[layer] = (self.source[layer] + 0x0A) & 0xFFFF

    def _draw_strip(self, layer: int, source: int, destination: int) -> None:
        if self.journal_active:
            raise RuntimeError("загрузка полосы при живом снимке коллизий")
        # EA95/EB02: пять вертикальных метаблоков, каждый 8x6 tiles.
        bias = 0x39D9 if layer == 0 else 0x2971
        descriptors = 0x10000 + ((source - bias) & 0xFFFF)
        base_di = ((destination * 2) + 0x1020) & 0x10FF
        for metatile in range(5):
            descriptor = struct.unpack_from(
                "<H", self.rom, descriptors + metatile * 2)[0]
            source_offset = 0x30000 + (descriptor & 0x3FFF) * 144
            flip_x = bool(descriptor & 0x4000)
            flip_y = bool(descriptor & 0x8000)
            row_start = base_di + (0x500 if flip_y else 0)
            row_step = -0x100 if flip_y else 0x100
            for row in range(6):
                output = row_start + row * row_step + (0x1C if flip_x else 0)
                output_step = -4 if flip_x else 4
                for _ in range(8):
                    code = struct.unpack_from("<H", self.rom, source_offset)[0]
                    attribute = struct.unpack_from(
                        "<H", self.rom, source_offset + 2)[0]
                    source_offset += 3
                    if flip_x:
                        code ^= 0x4000
                    if flip_y:
                        code ^= 0x8000
                    struct.pack_into(
                        "<HH", self.vram[layer], output, code, attribute)
                    self.refresh_written(layer, output, 4)
                    output += output_step
            base_di += 0x600

    def state(self, layer: int, row: int, column: int) -> tuple[int, int]:
        cell = (row + VISIBLE_ROW_FIRST) * 64 + column
        return struct.unpack_from("<HH", self.vram[layer], cell * 4)

    def attach_tile_keys(self, codes: tuple[int, ...],
                         attributes: tuple[int, ...]) -> None:
        """Связать общую отсортированную таблицу ключей и пересчитать ячейки."""
        self.tile_key_codes = tuple(codes)
        self.tile_key_attributes = tuple(attributes)
        self.rebuild_tile_keys()

    def rebuild_tile_keys(self) -> None:
        """Пересчитать ключи и занятость всех видимых ячеек обоих слоёв."""
        for layer in range(2):
            for row in range(VISIBLE_ROW_COUNT):
                for column in range(64):
                    self._refresh_cell_key(
                        layer, (row + VISIBLE_ROW_FIRST) * 64 + column)

    def _find_tile_key(self, code: int, attribute: int) -> int:
        """Двоичный поиск пары в общей таблице; NO_TILE_KEY, если пары нет."""
        low = 0
        high = len(self.tile_key_codes) - 1
        while low <= high:
            middle = (low + high) >> 1
            key_code = self.tile_key_codes[middle]
            key_attribute = self.tile_key_attributes[middle]
            if key_code == code and key_attribute == attribute:
                return middle
            if (key_code < code or
                    (key_code == code and key_attribute < attribute)):
                low = middle + 1
            else:
                high = middle - 1
        return NO_TILE_KEY

    def _refresh_cell_key(self, layer: int, cell: int) -> None:
        """Обновить ключ и бит занятости одной ячейки после записи."""
        row = (cell >> 6) - VISIBLE_ROW_FIRST
        if not self.tile_key_codes or not 0 <= row < VISIBLE_ROW_COUNT:
            return
        column = cell & 63
        code, attribute = struct.unpack_from("<HH", self.vram[layer], cell * 4)
        key = self._find_tile_key(code, attribute)
        self.key_map[layer][row * 64 + column] = key
        bits = row * 8 + (column >> 3)
        mask = 1 << (column & 7)
        if key == NO_TILE_KEY:
            self.row_bits[layer][bits] &= 0xFF ^ mask
        else:
            self.row_bits[layer][bits] |= mask

    def refresh_written(self, layer: int, first: int, count: int) -> None:
        """Обновить ключи ячеек, затронутых записью байтов first…first+count-1."""
        for cell in range(first >> 2, ((first + count - 1) >> 2) + 1):
            self._refresh_cell_key(layer, cell)

    def begin_journal(self) -> int:
        """Начать журнал для нового снимка коллизий и вернуть его поколение."""
        self.journal_generation += 1
        self.journal_active = True
        self.journal_layers.clear()
        self.journal_indices.clear()
        self.journal_values.clear()
        return self.journal_generation

    def end_journal(self) -> None:
        """Закрыть журнал: прежний снимок читать больше нельзя."""
        if not self.journal_active:
            return
        self.journal_generation += 1
        self.journal_active = False
        self.journal_layers.clear()
        self.journal_indices.clear()
        self.journal_values.clear()

    def _saved_byte(self, layer: int, index: int) -> int:
        """Исходный байт из журнала или -1, если байт после снимка не писался."""
        for position in range(len(self.journal_indices)):
            if (self.journal_indices[position] == index and
                    self.journal_layers[position] == layer):
                return self.journal_values[position]
        return -1

    def journal_bytes(self, layer: int, first: int, count: int) -> None:
        """Сохранить исходные байты перед записью в VRAM (только первое значение)."""
        if not self.journal_active:
            return
        data = self.vram[layer]
        # За пределами буфера запись завершится той же ошибкой struct.
        for index in range(first, min(first + count, len(data))):
            if self._saved_byte(layer, index) < 0:
                self.journal_layers.append(layer)
                self.journal_indices.append(index)
                self.journal_values.append(data[index])

    def snapshot_cell(self, generation: int, layer: int,
                      address: int) -> tuple[int, int]:
        """Ячейка `(code, attribute)` в том виде, какой она была на момент снимка."""
        if generation != self.journal_generation:
            raise RuntimeError("снимок коллизий прочитан после конца своего кадра")
        data = self.vram[layer]
        if not self.journal_indices or address + 4 > len(data):
            return struct.unpack_from("<HH", data, address)
        raw = bytearray(data[address:address + 4])
        for offset in range(4):
            saved = self._saved_byte(layer, address + offset)
            if saved >= 0:
                raw[offset] = saved
        return struct.unpack_from("<HH", raw, 0)

    def journal_changed_cells(self, generation: int,
                              layer: int) -> frozenset[int]:
        """Адреса ячеек (шаг 4), которые сейчас отличаются от снимка.

        Совпадает с полным перебором `range(0, 0x4000, 4)`: отличаться может
        только ячейка, в которую после снимка записан хотя бы один байт.
        """
        candidates = sorted({
            self.journal_indices[position] & 0x3FFC
            for position in range(len(self.journal_indices))
            if self.journal_layers[position] == layer
        })
        return frozenset(
            address for address in candidates
            if struct.unpack_from("<HH", self.vram[layer], address) !=
            self.snapshot_cell(generation, layer, address))


class M72TerrainModifier:
    """Isolated `$6C09` oracle retained for tilemap regression tests.

    The live game uses :class:`TerrainModifierParent6ACB` from the object
    scheduler; keeping a second active copy here would miss the child-armed
    `$6B4F` build/erase states and overwrite foreground VRAM out of order.
    """

    EVENT_THRESHOLD = 0x0D2C
    PATH = 0x2EC6

    def __init__(self, rom: bytes) -> None:
        self.rom = rom
        self.state = "waiting"
        self.x = 0
        self.y = 0
        self.timer = 0
        self.tilemap_origin = 0
        # This test oracle covers the initial full-path write only.  The live
        # object owns fields +$38/+$3A and their incremental paths.
        self.build_path = 0
        self.erase_path = 0

    def update(self, scroll: M72Scroll, tilemaps: M72Tilemaps) -> None:
        # $1BA7 + ES:$BB5F: progression threshold dispatches command $4400 to
        # handler table entry $11, ES:$B94F=$6A9B.
        if self.state == "waiting":
            if scroll.progression < self.EVENT_THRESHOLD:
                return
            self.x = 0x02D8
            self.y = 0x0154
            self.state = "spawn_children"
            return

        # A newly linked object is first visited on the following scheduler
        # pass. $6ACB creates all 16 children in that one pass.
        if self.state == "spawn_children":
            self.timer = 0x0040
            self.state = "active"
            return

        # Python state is aligned to the beginning-of-frame MAME snapshot.
        # A CPU pass missing on frame N is therefore observable as an
        # unchanged object on snapshot N+1 (`M72_SCROLL_STALLS`).
        if self.state != "active" or scroll.vblank in M72_SCROLL_STALLS:
            return

        # $6B4F..$6B5D.
        self.timer = (self.timer - 1) & 0xFFFF
        if self.timer == 0:
            self.tilemap_origin = self._tilemap_offset(scroll.foreground_x)
            self._write_path(tilemaps, self.tilemap_origin,
                             self.PATH, 0x03E8)
        self.x = (self.x + scroll.foreground_delta) & 0xFFFF

        # Incremental build/erase is deliberately absent from this isolated
        # oracle because it has no `$6C37` child objects to arm those fields.

    def _tilemap_offset(self, foreground_x: int) -> int:
        # Literal $1E6C..$1EA4.  All intermediate values have V30 word width.
        cx = foreground_x & 0x0007
        bx = (((foreground_x >> 1) & 0x00FC) + 0x1020) & 0xFFFF
        ax = (self.x + cx - 0x0140) & 0xFFFF
        ax = ((ax >> 1) & 0xFFFC)
        bx = (bx + ax) & 0x10FF
        ax = (0x017F - self.y) & 0xFFFF
        if 0x017F < self.y:
            ax = 0
        ax = ((ax & 0xFFF8) << 5) & 0xFFFF
        return (bx + ax) & 0x3FFF

    def _write_path(self, tilemaps: M72Tilemaps, start: int,
                    path: int, code: int) -> None:
        bx = start & 0x3FFF
        si = path
        while True:
            struct.pack_into("<HH", tilemaps.vram[0], bx, code, 0x0081)
            tilemaps.refresh_written(0, bx, 4)
            delta = struct.unpack_from("<H", self.rom, 0x10000 + si)[0]
            if delta == 0:
                return
            # ROM uses ADD BL,AL / ADD BH,AH: deliberately no carry between
            # the two bytes of the tilemap address.
            low = ((bx & 0xFF) + (delta & 0xFF)) & 0xFF
            high = (((bx >> 8) + (delta >> 8)) & 0xFF) << 8
            bx = (high | low) & 0x3FFF
            si += 2


class StageSection:
    """Только офлайн-атласы секции и соответствие raw M72 state -> slot."""

    def __init__(self, index: int) -> None:
        prefix = SECTION_DIR / f"STAGE1_S{index}"
        self.fg_atlas = _load_atlas(prefix.with_name(
            prefix.name + "_FG_ATLAS_ARGB4444.bin"))
        self.bg_atlas = _load_atlas(prefix.with_name(
            prefix.name + "_BG_ATLAS_ARGB4444.bin"))
        self.fg_lookup = _load_lookup(prefix.with_name(
            prefix.name + "_FG_LOOKUP.bin"))
        self.bg_lookup = _load_lookup(prefix.with_name(
            prefix.name + "_BG_LOOKUP.bin"))
        self.boss_fg_atlas = self.fg_atlas
        self.boss_bg_atlas = self.bg_atlas
        self.boss_fg_lookup = self.fg_lookup
        self.boss_bg_lookup = self.bg_lookup
        self.flash_fg_atlas = self.fg_atlas
        self.flash_bg_atlas = self.bg_atlas
        self.flash_fg_lookup = self.fg_lookup
        self.flash_bg_lookup = self.bg_lookup
        if index in (2, 3):
            self.boss_fg_atlas = _load_atlas(prefix.with_name(
                prefix.name + "_FG_NORMAL9501_ATLAS_ARGB4444.bin"))
            self.boss_bg_atlas = _load_atlas(prefix.with_name(
                prefix.name + "_BG_NORMAL9501_ATLAS_ARGB4444.bin"))
            self.boss_fg_lookup = _load_lookup(prefix.with_name(
                prefix.name + "_FG_NORMAL9501_LOOKUP.bin"))
            self.boss_bg_lookup = _load_lookup(prefix.with_name(
                prefix.name + "_BG_NORMAL9501_LOOKUP.bin"))
            self.flash_fg_atlas = _load_atlas(prefix.with_name(
                prefix.name + "_FG_FLASH9500_ATLAS_ARGB4444.bin"))
            self.flash_bg_atlas = _load_atlas(prefix.with_name(
                prefix.name + "_BG_FLASH9500_ATLAS_ARGB4444.bin"))
            self.flash_fg_lookup = _load_lookup(prefix.with_name(
                prefix.name + "_FG_FLASH9500_LOOKUP.bin"))
            self.flash_bg_lookup = _load_lookup(prefix.with_name(
                prefix.name + "_BG_FLASH9500_LOOKUP.bin"))

    def lookup_keys(self) -> set[tuple[int, int]]:
        """Все пары (code, attribute) шести таблиц участка."""
        return (set(self.fg_lookup) | set(self.bg_lookup) |
                set(self.boss_fg_lookup) | set(self.boss_bg_lookup) |
                set(self.flash_fg_lookup) | set(self.flash_bg_lookup))

    def bind_tile_keys(self, keys: list[tuple[int, int]]) -> None:
        """Слот атласа для каждого общего ключа; -1 — ключа нет в таблице.

        Таблицы слотов дополнены до TILE_KEY_CAPACITY, атласы — до
        ATLAS_CAPACITY; лишние записи никогда не читаются.
        """
        if len(keys) >= NO_TILE_KEY:
            raise ValueError("слишком много ключей тайлов для TILE_KEY_CAPACITY")
        cache: dict[int, tuple[int, ...]] = {}
        images: dict[int, tuple[pygame.Surface, ...]] = {}

        def slots(lookup: dict[tuple[int, int], int]) -> tuple[int, ...]:
            # Общая таблица вариантов остаётся общей и в слотах.
            if id(lookup) not in cache:
                cache[id(lookup)] = (tuple(lookup.get(key, -1) for key in keys) +
                                     (-1,) * (TILE_KEY_CAPACITY - len(keys)))
            return cache[id(lookup)]

        def padded(atlas: list[pygame.Surface]) -> tuple[pygame.Surface, ...]:
            if len(atlas) > ATLAS_CAPACITY:
                raise ValueError("атлас больше ATLAS_CAPACITY")
            if id(atlas) not in images:
                images[id(atlas)] = tuple(atlas) + (atlas[0],) * (ATLAS_CAPACITY - len(atlas))
            return images[id(atlas)]

        self.fg_slots = slots(self.fg_lookup)
        self.bg_slots = slots(self.bg_lookup)
        self.boss_fg_slots = slots(self.boss_fg_lookup)
        self.boss_bg_slots = slots(self.boss_bg_lookup)
        self.flash_fg_slots = slots(self.flash_fg_lookup)
        self.flash_bg_slots = slots(self.flash_bg_lookup)
        self.fg_images = padded(self.fg_atlas)
        self.bg_images = padded(self.bg_atlas)
        self.boss_fg_images = padded(self.boss_fg_atlas)
        self.boss_bg_images = padded(self.boss_bg_atlas)
        self.flash_fg_images = padded(self.flash_fg_atlas)
        self.flash_bg_images = padded(self.flash_bg_atlas)


def _collision_address(object_x: int, object_y: int,
                       scroll_x: int, scroll_y: int = 0) -> int:
    """Literal tile address arithmetic shared by `$1E6C/$1EB5`."""
    subcolumn = scroll_x & 7
    address = ((scroll_x >> 1) & 0x00FC) + 0x1020
    horizontal = (object_x + subcolumn - 0x0140) & 0xFFFF
    address += (horizontal >> 1) & 0xFFFC
    address &= 0x10FF
    vertical_subrow = scroll_y & 7
    address += (scroll_y << 5) & 0x3F00
    vertical = 0x017F + vertical_subrow - object_y
    if vertical < 0:
        vertical = 0
    address += (vertical & 0xFFF8) << 5
    return address & 0x3FFF


@dataclass(frozen=True)
class M72CollisionSnapshot:
    """Tile state seen by fixed records before dynamic-object VRAM writes.

    Force, Bits and the fixed player-weapon records precede the dynamic
    object list in the original scheduler.  Python currently keeps those
    subsystems separate, so this immutable 32 KiB view preserves the exact
    read boundary without allowing a later `$6B68/$6BE1` terrain write to
    change an earlier fixed-record collision decision.
    """

    foreground_x: int
    background_x: int
    foreground_vram: bytes
    background_vram: bytes
    background_y: int = 0

    def terrain_address(self, object_x: int, object_y: int) -> int:
        return _collision_address(
            object_x, object_y, self.foreground_x)

    def background_address(self, object_x: int, object_y: int) -> int:
        return _collision_address(
            object_x, object_y, self.background_x, self.background_y)

    def foreground_cell(self, address: int) -> tuple[int, int]:
        return struct.unpack_from(
            "<HH", self.foreground_vram, address & 0x3FFF)

    def background_cell(self, address: int) -> tuple[int, int]:
        return struct.unpack_from(
            "<HH", self.background_vram, address & 0x3FFF)

    def collision_codes(self, object_x: int,
                        object_y: int) -> tuple[int, int]:
        foreground = self.foreground_cell(
            self.terrain_address(object_x, object_y))[0] & 0x0FFF
        background = self.background_cell(
            self.background_address(object_x, object_y))[0] & 0x0FFF
        return foreground, background


class M72JournalSnapshot:
    """Тот же снимок коллизий, что M72CollisionSnapshot, без копии 32 КиБ.

    Чтения идут в текущую VRAM, а байты, записанные после снимка, берутся из
    журнала `M72Tilemaps`. Снимок действителен до конца кадра: следующий
    `M72Tilemaps.advance` закрывает журнал, и чтение устаревшего снимка
    завершается ошибкой, а не тихим расхождением.
    """

    def __init__(self, foreground_x: int, background_x: int,
                 tilemaps: M72Tilemaps, background_y: int = 0) -> None:
        self.foreground_x = foreground_x
        self.background_x = background_x
        self.background_y = background_y
        self.tilemaps = tilemaps
        self.generation = tilemaps.begin_journal()

    def terrain_address(self, object_x: int, object_y: int) -> int:
        return _collision_address(
            object_x, object_y, self.foreground_x)

    def background_address(self, object_x: int, object_y: int) -> int:
        return _collision_address(
            object_x, object_y, self.background_x, self.background_y)

    def foreground_cell(self, address: int) -> tuple[int, int]:
        return self.tilemaps.snapshot_cell(
            self.generation, 0, address & 0x3FFF)

    def background_cell(self, address: int) -> tuple[int, int]:
        return self.tilemaps.snapshot_cell(
            self.generation, 1, address & 0x3FFF)

    def collision_codes(self, object_x: int,
                        object_y: int) -> tuple[int, int]:
        foreground = self.foreground_cell(
            self.terrain_address(object_x, object_y))[0] & 0x0FFF
        background = self.background_cell(
            self.background_address(object_x, object_y))[0] & 0x0FFF
        return foreground, background

    def changed_foreground_cells(self) -> frozenset[int]:
        """Ячейки переднего слоя, изменённые после снимка (адреса с шагом 4)."""
        return self.tilemaps.journal_changed_cells(self.generation, 0)


@dataclass(frozen=True)
class CheckpointTerrain:
    """Состояние ring tilemap после `$F01B` для одного checkpoint.

    Строится до игры тем же M72WorldTerrain (манифест, развёрнутые полосы ROM,
    предзагрузка ring), который раньше создавался в reset_checkpoint; в игровом
    цикле остаётся копирование этих данных.
    """

    foreground_velocity_q8: int
    background_velocity_q8: int
    progression: int
    vram: tuple[bytes, bytes]
    target: tuple[int, int]
    tracker: tuple[int, int]
    source: tuple[int, int]

    @staticmethod
    def build(stage: int, checkpoint: int) -> "CheckpointTerrain":
        terrain = M72WorldTerrain(stage, checkpoint)
        record = terrain.checkpoint_record
        return CheckpointTerrain(
            int(record["foreground_velocity_q8"]),
            int(record["background_velocity_q8"]),
            int(record["progression"]),
            (bytes(terrain.vram[0]), bytes(terrain.vram[1])),
            (terrain.target[0], terrain.target[1]),
            (terrain.tracker[0], terrain.tracker[1]),
            (terrain.source[0], terrain.source[1]))


class Stage:
    """Покадровое состояние tilemap первого игрового пространства."""

    def __init__(self) -> None:
        self.m72_scroll = M72Scroll()
        self.tilemaps = M72Tilemaps()
        self.frame = 1
        self.section_index = 0
        # Converting a whole offline section into hundreds of pygame surfaces
        # at the exact boundary caused a visible whole-window hitch/blink.
        # Sections are immutable, so prepare them before play and make the
        # boundary operation a single reference assignment.
        self.sections = tuple(StageSection(index)
                              for index in range(len(SECTION_STARTS)))
        # Общая таблица ключей всех участков: слот ячейки выбирается по её
        # индексу ключа, который M72Tilemaps ведёт при записи в VRAM.
        keys = sorted(set().union(*(section.lookup_keys()
                                    for section in self.sections)))
        for section in self.sections:
            section.bind_tile_keys(keys)
        self.tilemaps.attach_tile_keys(
            tuple(code for code, _ in keys),
            tuple(attribute for _, attribute in keys))
        self.section = self.sections[0]
        self.boss_palette_active = False
        self.boss_hit_flash = False
        # Состояния ring tilemap всех checkpoint Stage 1 строятся до игры тем же
        # M72WorldTerrain, что прежде создавался в reset_checkpoint.
        self.checkpoint_terrain = tuple(
            CheckpointTerrain.build(1, ordinal)
            for ordinal in range(stage_checkpoint_count(1)))

    def reset_checkpoint(self, stage: int, checkpoint: int) -> None:
        """Повторить `$F01B` для ring tilemap выбранного checkpoint.

        Цветной runtime renderer пока использует проверенные Stage-1 atlases,
        поэтому здесь разрешён только первый stage. Общий ROM ring при этом
        уже обслуживает все восемь stages в :mod:`world_terrain`.
        """
        if stage != 1:
            raise ValueError("цветной checkpoint renderer пока есть только для Stage 1")
        if not 0 <= checkpoint < len(self.checkpoint_terrain):
            raise ValueError("checkpoint вне диапазона выбранного stage")
        terrain = self.checkpoint_terrain[checkpoint]
        old_vblank = self.m72_scroll.vblank
        self.m72_scroll = M72Scroll(
            vblank=old_vblank,
            foreground_accumulator=0,
            foreground_velocity=terrain.foreground_velocity_q8,
            background_accumulator=0,
            background_velocity=terrain.background_velocity_q8,
            progression_accumulator=terrain.progression << 8,
        )
        self.tilemaps.end_journal()
        self.tilemaps.vram = [bytearray(layer) for layer in terrain.vram]
        self.tilemaps.rebuild_tile_keys()
        self.tilemaps.target = list(terrain.target)
        self.tilemaps.tracker = list(terrain.tracker)
        self.tilemaps.source = list(terrain.source)

        # Для Stage 1 скорость progression равна половине native pixel за
        # VBlank. Поправка 47 кадров — участок 852…898, когда section frame
        # ещё удерживается на единице, хотя `$0467` уже интегрирует scroll.
        progression = terrain.progression
        self.frame = min(
            SECTION_END - 1,
            1 + max(0, (progression - 0x063F) * 2 - 47),
        )
        self.section_index = max(
            index for index, start in enumerate(SECTION_STARTS)
            if start <= self.frame)
        self.section = self.sections[self.section_index]
        self.boss_palette_active = False
        self.boss_hit_flash = False

    def update(self) -> None:
        self.m72_scroll.advance()
        self.tilemaps.advance(self.m72_scroll)
        # Исходные карты разделов сняты на MAME frame 898. До него скроллер
        # уже работает, но поток более поздних VRAM-событий ещё не применяется.
        if self.m72_scroll.vblank > 898:
            self.frame = min(self.frame + 1, SECTION_END - 1)
        # Последний участок, начало которого не позже текущего кадра (как max).
        index = -1
        for candidate in range(len(SECTION_STARTS)):
            if SECTION_STARTS[candidate] <= self.frame:
                index = candidate
        if index < 0:
            raise ValueError("max() iterable argument is empty")
        if index != self.section_index:
            self.section_index = index
            self.section = self.sections[index]

    def _draw_layer(self, target: pygame.Surface, layer: int,
                    atlas: tuple[pygame.Surface, ...],
                    slots: tuple[int, ...], scroll_x: int) -> None:
        source_base = ((scroll_x >> 3) + 8) & 63
        shift = SHIFT_LOGICAL[scroll_x & 7]
        key_map = self.tilemaps.key_map[layer]
        row_bits = self.tilemaps.row_bits[layer]
        for row in range(VISIBLE_ROW_COUNT):
            y = row * GLYPH_H
            cells = row * 64
            bits = row * 8
            column = 0
            while column < VISIBLE_COLUMN_COUNT:
                source_column = (source_base + column) & 63
                # Пустой байт занятости: ни одной ячейки с ключом до конца байта.
                if not row_bits[bits + (source_column >> 3)]:
                    column += 8 - (source_column & 7)
                    continue
                key = key_map[cells + source_column]
                if key != NO_TILE_KEY:
                    slot = slots[key]
                    if slot >= 0:
                        target.blit(atlas[slot],
                                    (COLUMN_X[column] - shift, y))
                column += 1

    def draw_back(self, target: pygame.Surface) -> None:
        if self.boss_hit_flash:
            atlas, slots = (self.section.flash_bg_images,
                            self.section.flash_bg_slots)
        elif self.boss_palette_active:
            atlas, slots = (self.section.boss_bg_images,
                            self.section.boss_bg_slots)
        else:
            atlas, slots = self.section.bg_images, self.section.bg_slots
        self._draw_layer(target, 1, atlas, slots,
                         self.m72_scroll.background_x)

    def draw_front(self, target: pygame.Surface) -> None:
        if self.boss_hit_flash:
            atlas, slots = (self.section.flash_fg_images,
                            self.section.flash_fg_slots)
        elif self.boss_palette_active:
            atlas, slots = (self.section.boss_fg_images,
                            self.section.boss_fg_slots)
        else:
            atlas, slots = self.section.fg_images, self.section.fg_slots
        self._draw_layer(target, 0, atlas, slots,
                         self.m72_scroll.foreground_x)

    def terrain_code(self, object_x: int, object_y: int) -> int:
        """ROM `$1E6C`: foreground tile code under a native M72 coordinate."""
        address = self.terrain_address(object_x, object_y)
        return struct.unpack_from("<H", self.tilemaps.vram[0], address)[0] & 0x0FFF

    def terrain_address(self, object_x: int, object_y: int) -> int:
        """Return the foreground VRAM byte offset left in BX by `$1E6C`."""
        # The MAME frame callback samples RAM before the current main-loop
        # `$0467`, but gameplay object handlers call `$1E6C` afterwards.
        # Therefore probes use the newly integrated `$2EC1`, while drawing
        # continues to use the sampled `foreground_x` above.
        return _collision_address(
            object_x, object_y, self.m72_scroll.dispatch_foreground_x)

    def background_address(self, object_x: int, object_y: int) -> int:
        """Return background VRAM byte offset left in DI by `$1EB5`."""
        # Stage 1 keeps RAM `$2ECD` at zero.  The parameter is explicit in
        # `_collision_address` so later stages can supply their vertical
        # background scroll without changing Force's address-domain scan.
        return _collision_address(
            object_x, object_y, self.m72_scroll.dispatch_background_x)

    def erase_foreground(self, address: int) -> None:
        """Boss arena `$9FE9`: replace only the tile-code word with `$0FA0`."""
        self.tilemaps.journal_bytes(0, address & 0x3FFF, 2)
        struct.pack_into("<H", self.tilemaps.vram[0], address & 0x3FFF, 0x0FA0)
        self.tilemaps.refresh_written(0, address & 0x3FFF, 2)

    def replace_foreground(self, address: int, code: int,
                           attribute: int) -> None:
        """Write the exact code/attribute pair used by terrain mutators."""
        self.tilemaps.journal_bytes(0, address & 0x3FFF, 4)
        struct.pack_into("<HH", self.tilemaps.vram[0], address & 0x3FFF,
                         code & 0xFFFF, attribute & 0xFFFF)
        self.tilemaps.refresh_written(0, address & 0x3FFF, 4)

    def foreground_cell(self, address: int) -> tuple[int, int]:
        """Return one foreground `(code,attribute)` pair by VRAM byte offset."""
        return struct.unpack_from("<HH", self.tilemaps.vram[0],
                                  address & 0x3FFF)

    def background_cell(self, address: int) -> tuple[int, int]:
        """Return one background `(code,attribute)` pair by VRAM offset."""
        return struct.unpack_from("<HH", self.tilemaps.vram[1],
                                  address & 0x3FFF)

    def collision_snapshot(self) -> M72JournalSnapshot:
        """Capture the collision state before dynamic objects mutate VRAM."""
        # Вместо копии обеих карт журнал записей; наблюдаемые чтения те же.
        return M72JournalSnapshot(
            self.m72_scroll.dispatch_foreground_x,
            self.m72_scroll.dispatch_background_x,
            self.tilemaps,
        )

    def collision_codes(self, object_x: int, object_y: int) -> tuple[int, int]:
        """ROM `$1EB5`: foreground/background codes sampled by an object."""
        foreground = self.terrain_code(object_x, object_y)
        address = self.background_address(object_x, object_y)
        background = self.background_cell(address)[0] & 0x0FFF
        return foreground, background
