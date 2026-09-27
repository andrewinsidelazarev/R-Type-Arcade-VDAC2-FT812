"""Общий ROM-derived ring tilemap для ландшафтов всех восьми stages."""
from __future__ import annotations

import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TERRAIN_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" / "Terrain"
MANIFEST_PATH = TERRAIN_DIR / "all_stage_terrain.json"
BLANK_CODE = 0x0FA0
STRIP_BYTES = 30 * 8 * 4
FG_X, FG_Y, BG_X, BG_Y = range(4)
STAGE3_BACKGROUND_PATH = 0x6F8A


def _signed8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


class Stage3BackgroundController:
    """Буквальный scroll-script объекта `$C46E/$C4BC/$C5F8`.

    Трёхбайтная запись имеет `(signed BG-Y, signed BG-X, duration)`. Оба
    direction byte превращаются в signed Q16.8 velocity сдвигом влево на 4;
    `$80` в duration является terminal sentinel.
    """

    def __init__(self, world_rom: bytes) -> None:
        self.rom = world_rom
        self.pointer = STAGE3_BACKGROUND_PATH
        self.direction_y = 0
        self.direction_x = 0
        self.timer = 0
        self.state = "path"
        self.terminal_timer = 0
        if not self._load_record():
            raise ValueError("первый record Stage 3 scroll path является sentinel")

    def _load_record(self) -> bool:
        y, x, duration = self.rom[self.pointer:self.pointer + 3]
        if len((y, x, duration)) != 3:
            raise EOFError("оборван Stage 3 background path")
        self.direction_y = _signed8(y)
        self.direction_x = _signed8(x)
        if duration == 0x80:
            return False
        self.timer = duration
        self.pointer += 3
        return True

    def update(self, terrain: "M72WorldTerrain") -> None:
        if self.state == "path":
            terrain.velocity[BG_X] = self.direction_x << 4
            terrain.velocity[BG_Y] = self.direction_y << 4
            self.timer = (self.timer - 1) & 0xFFFF
            if self.timer == 0 and not self._load_record():
                # `$C55D/$C562/$C564`: terminal branch immediately stops FG X
                # and enters `$C57D` with countdown `$0180`.
                terrain.velocity[FG_X] = 0
                self.state = "terminal"
                self.terminal_timer = 0x0180
        elif self.state == "terminal":
            # `$C57D…$C58F`: ship/background leaves vertically for 384 VBlank.
            terrain.velocity[BG_X] = 0
            terrain.velocity[BG_Y] = -0x40
            self.terminal_timer -= 1
            if self.terminal_timer == 0:
                terrain.velocity[FG_X] = 0
                terrain.velocity[BG_X] = 0
                terrain.velocity[BG_Y] = 0
                terrain.transition_requested = True
                self.state = "done"


def stage_checkpoint_count(stage: int, manifest_path: Path = MANIFEST_PATH) -> int:
    """Число checkpoint выбранного stage в all-stage manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["stages"]:
        if item["stage"] == stage:
            return len(item["checkpoints"])
    raise ValueError("stage должен быть 1..8")


def _blank_vram(layer: int) -> bytearray:
    result = bytearray(0x4000)
    first = 0x0200 if layer == 0 else 0
    for offset in range(first, 0x4000, 4):
        struct.pack_into("<HH", result, offset, BLANK_CODE, 0)
    return result


def _apply_strip(vram: bytearray, destination: int, strip: bytes) -> None:
    if len(strip) != STRIP_BYTES:
        raise ValueError("неверный размер ROM-derived terrain strip")
    base = ((destination * 2) + 0x1020) & 0x10FF
    cursor = 0
    for row in range(30):
        output = base + row * 0x100
        for column in range(8):
            code, attribute = struct.unpack_from("<HH", strip, cursor)
            struct.pack_into("<HH", vram, output + column * 4,
                             code, attribute)
            cursor += 4


class M72WorldTerrain:
    """`$F01B/$02AE/$02CE/$EA51/$EA73` для выбранного stage/checkpoint.

    Полосы заранее развёрнуты из metatile ROM конвертером; в runtime остаются
    только исходные Q8 scroll accumulators, переход bit `$40` и запись в ring.
    События возвращаются вызывающему коду с исходными command/handler, без
    подмены ещё не перенесённых handlers придуманными действиями.
    """

    def __init__(self, stage: int, checkpoint: int = 0,
                 manifest_path: Path = MANIFEST_PATH) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["stage_count"] != 8 or manifest["event_count"] != 788:
            raise ValueError("неполный all-stage terrain manifest")
        try:
            self.definition = next(item for item in manifest["stages"]
                                   if item["stage"] == stage)
        except StopIteration as error:
            raise ValueError("stage должен быть 1..8") from error
        points = self.definition["checkpoints"]
        if not 0 <= checkpoint < len(points):
            raise ValueError("checkpoint вне диапазона выбранного stage")
        self.stage = stage
        self.manifest = manifest
        self.checkpoint = checkpoint
        self.checkpoint_record = points[checkpoint]
        self.events = self.definition["events"]
        self.event_index = next(
            index for index, event in enumerate(self.events)
            if event["threshold"] == self.checkpoint_record["progression"])

        self.vram = [_blank_vram(0), _blank_vram(1)]
        self.streams: list[bytes] = []
        self.stream_starts: list[int] = []
        for name in ("foreground", "background"):
            layer = self.definition["layers"][name]
            path = ROOT / layer["stream"]
            data = path.read_bytes()
            if len(data) != layer["strip_count"] * STRIP_BYTES:
                raise ValueError(f"повреждён terrain stream: {path}")
            self.streams.append(data)
            self.stream_starts.append(layer["source_start"])

        self.source = [self.checkpoint_record["foreground_source"],
                       self.checkpoint_record["background_source"]]
        self.target = [0x70, 0x70]
        self.tracker = [0, 0]
        # Exact `$0467` order: foreground X/Y, background X/Y. All four are
        # signed 24-bit Q16.8 integrators; only X crossings feed strip loaders.
        self.accumulator = [0, 0, 0, 0]
        self.velocity = [self.checkpoint_record["foreground_velocity_q8"],
                         0,
                         self.checkpoint_record["background_velocity_q8"],
                         0]
        self.delta = [0, 0, 0, 0]
        self.progression_accumulator = (
            self.checkpoint_record["progression"] << 8)
        self.transition_requested = False
        self.next_stage_init_seen = False
        self.stage3_background: Stage3BackgroundController | None = None
        self._pump_all_preload()

    @property
    def progression(self) -> int:
        return (self.progression_accumulator >> 8) & 0xFFFF

    @property
    def foreground_x(self) -> int:
        return (self.accumulator[FG_X] >> 8) & 0x01FF

    @property
    def foreground_y(self) -> int:
        return (self.accumulator[FG_Y] >> 8) & 0x01FF

    @property
    def background_x(self) -> int:
        return (self.accumulator[BG_X] >> 8) & 0x01FF

    @property
    def background_y(self) -> int:
        return (self.accumulator[BG_Y] >> 8) & 0x01FF

    def _strip(self, layer: int, source: int) -> bytes:
        relative = source - self.stream_starts[layer]
        if relative < 0 or relative % 10:
            raise ValueError("source не выровнен на ROM descriptor strip")
        offset = (relative // 10) * STRIP_BYTES
        result = self.streams[layer][offset:offset + STRIP_BYTES]
        if len(result) != STRIP_BYTES:
            raise EOFError(
                f"Stage {self.stage}: исчерпан {('FG', 'BG')[layer]} stream "
                f"на source ${source:04X}")
        return result

    def _pump_layer(self, layer: int) -> None:
        if self.tracker[layer] == self.target[layer]:
            return
        strip = self._strip(layer, self.source[layer])
        _apply_strip(self.vram[layer], self.tracker[layer], strip)
        self.tracker[layer] = (self.tracker[layer] + 0x10) & 0xFF
        self.source[layer] += 10

    def _pump_all_preload(self) -> None:
        while self.tracker != self.target:
            self._pump_layer(0)
            self._pump_layer(1)

    def advance(self) -> list[dict[str, int | str]]:
        """Выполнить один VBlank скролла и вернуть созревшие ROM events."""
        for axis in range(4):
            old = self.accumulator[axis]
            new = (old + self.velocity[axis]) & 0xFFFFFF
            old_x = (old >> 8) & 0x01FF
            new_x = (new >> 8) & 0x01FF
            self.accumulator[axis] = new
            step = (new_x - old_x) & 0x01FF
            if step & 0x0100:
                step -= 0x0200
            self.delta[axis] = (-step) & 0xFFFF
            if axis in (FG_X, BG_X) and (old_x & 0x40) != (new_x & 0x40):
                layer = 0 if axis == FG_X else 1
                self.target[layer] = (self.target[layer] + 0x10) & 0xFF
        self.progression_accumulator = (
            self.progression_accumulator + self.velocity[FG_X]) & 0xFFFFFF
        self._pump_layer(0)
        self._pump_layer(1)

        # Object scheduler follows `$0467` in the same VBlank. A controller
        # created by the event loop below therefore first executes next frame.
        if self.stage3_background is not None:
            self.stage3_background.update(self)

        ready = []
        while (self.event_index < len(self.events) and
               self.events[self.event_index]["threshold"] <= self.progression):
            event = self.events[self.event_index]
            ready.append(event)
            self.event_index += 1
            self._apply_terrain_event(event)
        return ready

    def _apply_terrain_event(self, event: dict[str, int | str]) -> None:
        """Исполнить только доказанные глобальные scroll handlers ROM."""
        handler = int(event["handler"])
        if handler == 0xF0F3:
            # `$F0F3`: low five command bits select the global 14-byte
            # checkpoint record; +0 resets progression, +6/+8 set FG/BG Q8.
            index = int(event["command"]) & 0x1F
            record = next(
                point
                for stage in self.manifest["stages"]
                for point in stage["checkpoints"]
                if point["index"] == index)
            self.progression_accumulator = int(record["progression"]) << 8
            self.velocity[FG_X] = int(record["foreground_velocity_q8"])
            self.velocity[BG_X] = int(record["background_velocity_q8"])
        elif handler == 0xF429:
            # `$F429…$F437`: zero all four words of the two X velocities.
            self.velocity[FG_X] = 0
            self.velocity[BG_X] = 0
        elif handler == 0xF130:
            # Both branches clear all four 24-bit velocities.
            self.velocity[:] = [0, 0, 0, 0]
            self.transition_requested = True
        elif handler == 0xC46E:
            if self.stage != 3:
                raise ValueError("handler `$C46E` встретился вне Stage 3")
            world_rom = (ROOT / "Assets" / "Converted" / "Arcade" /
                         "RTYPE_MAINCPU_REGION.bin").read_bytes()[0x10000:0x20000]
            self.stage3_background = Stage3BackgroundController(world_rom)
        elif handler == 0xF01B:
            # `$F01B` belongs to the following-stage/checkpoint initializer.
            # The caller must construct that exact stage instead of continuing
            # to consume the current descriptor stream.
            self.next_stage_init_seen = True
