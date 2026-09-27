#!/usr/bin/env python3
"""Исполнение all-stage reader и event scheduler в собранном Z80."""
from __future__ import annotations

import json
import struct
import sys
import types
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from m72_target_pack import (  # noqa: E402
    SPRITE_TEXTURE_CHUNK_SIZE,
    TILES0,
    TILES1,
    _unpack_index4,
)
from rtype_port.world_terrain import (  # noqa: E402
    M72WorldTerrain,
    Stage3BackgroundController,
)


FT_CMD_INFLATE = 0xFFFFFF22
FT_CMD_MEMCPY = 0xFFFFFF1D
RAM_CMD_SIZE = 0x1000
TARGET_PACK_WINDOW_PAGES = 46


def install_stage_pack(machine: TSConfFT812Machine, stage: int) -> None:
    """Подменить bootstrap Stage 1 тем PAK, который на железе даёт SD-loader."""
    payload = (ROOT / "Build" / "SD" / "RType" /
               f"RTYPE{stage:02d}.PAK").read_bytes()
    first = machine.sym["RTYPE_TARGET_PACK_BASE_PAGE"] * 0x4000
    last = first + TARGET_PACK_WINDOW_PAGES * 0x4000
    machine.mem.physical[first:last] = bytes(last - first)
    machine.mem.physical[first:first + len(payload)] = payload


def value24(machine: TSConfFT812Machine, address: int) -> int:
    return (machine.get_byte(address) |
            (machine.get_byte(address + 1) << 8) |
            (machine.get_byte(address + 2) << 16))


def install_texture_coprocessor(machine: TSConfFT812Machine) -> None:
    """Добавить в host-модель две команды, используемые ring-текстурами."""
    assert machine.ft.cmd_read_ptr == machine.ft.cmd_write_ptr

    def process(self: TSConfFT812Machine) -> None:
        def fifo_bytes(position: int, size: int) -> bytes:
            return bytes(
                self.ft.ram_cmd[(position + index) & (RAM_CMD_SIZE - 1)]
                for index in range(size)
            )

        while True:
            read = self.ft.cmd_read_ptr & (RAM_CMD_SIZE - 1)
            write = self.ft.cmd_write_ptr & (RAM_CMD_SIZE - 1)
            available = (write - read) & (RAM_CMD_SIZE - 1)
            if available < 4:
                return
            command = struct.unpack("<I", fifo_bytes(read, 4))[0]
            if command == FT_CMD_INFLATE:
                if available < 8:
                    return
                destination = struct.unpack("<I", fifo_bytes(read + 4, 4))[0]
                payload = fifo_bytes(read + 8, available - 8)
                inflater = zlib.decompressobj()
                try:
                    output = inflater.decompress(payload)
                except zlib.error as error:
                    raise AssertionError("повреждён поток CMD_INFLATE") from error
                if not inflater.eof:
                    return
                consumed = len(payload) - len(inflater.unused_data)
                total = (8 + consumed + 3) & ~3
                if available < total:
                    return
                end = destination + len(output)
                assert 0 <= destination <= end <= len(self.ft.ram_g)
                self.ft.ram_g[destination:end] = output
                self.ft.cmd_read_ptr = (read + total) & (RAM_CMD_SIZE - 1)
                continue
            if command == FT_CMD_MEMCPY:
                if available < 16:
                    return
                destination, source, count = struct.unpack(
                    "<III", fifo_bytes(read + 4, 12))
                assert 0 <= source <= source + count <= len(self.ft.ram_g)
                assert 0 <= destination <= destination + count <= len(
                    self.ft.ram_g)
                data = bytes(self.ft.ram_g[source:source + count])
                self.ft.ram_g[destination:destination + count] = data
                self.ft.cmd_read_ptr = (read + 16) & (RAM_CMD_SIZE - 1)
                continue
            raise AssertionError(
                f"неожиданная FT812-команда в texture path: ${command:08X}")

    machine._process_cmd_fifo = types.MethodType(process, machine)


def ring_texture(vram: bytes, packed_tiles: bytes) -> bytes:
    """Развернуть активные 512x240 пикселей ring tilemap в index8."""
    graphics = _unpack_index4(packed_tiles)
    result = bytearray(512 * 240)
    for output_y, source_y in enumerate(range(128, 368)):
        tile_y, pixel_y = divmod(source_y, 8)
        for source_x in range(512):
            tile_x, pixel_x = divmod(source_x, 8)
            code_word, attribute = struct.unpack_from(
                "<HH", vram, tile_y * 0x100 + tile_x * 4)
            code = code_word & 0x3FFF
            if code_word & 0x4000:
                pixel_x = 7 - pixel_x
            if code_word & 0x8000:
                pixel_y = 7 - pixel_y
            pen = graphics[code * 64 + pixel_y * 8 + pixel_x]
            result[output_y * 512 + source_x] = ((attribute & 15) << 4) | pen
    return bytes(result)


def strip_slot_texture(ring: bytes) -> bytes:
    """Разложить 512x240 Python ring в восемь FT812 slots 64x512."""
    assert len(ring) == 512 * 240
    result = bytearray(8 * 64 * 512)
    for slot in range(8):
        for row in range(240):
            source = row * 512 + slot * 64
            destination = slot * 64 * 512 + (128 + row) * 64
            result[destination:destination + 64] = ring[source:source + 64]
    return bytes(result)


def assert_slot_texture(name: str, actual: bytes, expected_ring: bytes) -> None:
    expected = strip_slot_texture(expected_ring)
    compared = [
        slot * 64 * 512 + row * 64 + column
        for slot in range(8)
        for row in range(128, 368)
        for column in range(64)
    ]
    mismatches = [
        index for index in compared if actual[index] != expected[index]
    ]
    if not mismatches:
        return
    mismatch = mismatches[0]
    slot, inside = divmod(mismatch, 64 * 512)
    row, column = divmod(inside, 64)
    raise AssertionError(
        f"{name}: first mismatch slot={slot} x={column} y={row}; "
        f"RAM_G=${actual[mismatch]:02X}, oracle=${expected[mismatch]:02X}")


def assert_texture(name: str, actual: bytes, expected: bytes) -> None:
    """Выдать компактную геометрию первого расхождения RAM_G с oracle."""
    if actual == expected:
        return
    mismatches = [
        index for index, (left, right) in enumerate(zip(actual, expected))
        if left != right
    ]
    first = mismatches[0]
    last = mismatches[-1]
    columns = sorted({index % 512 for index in mismatches})
    rows = sorted({index // 512 for index in mismatches})
    strip_counts = [
        sum(1 for index in mismatches if strip * 64 <= index % 512 <
            (strip + 1) * 64)
        for strip in range(8)
    ]
    raise AssertionError(
        f"{name}: {len(mismatches)} несовпадений; "
        f"первое x={first % 512}, y={first // 512}, "
        f"RAM_G=${actual[first]:02X}, oracle=${expected[first]:02X}; "
        f"последнее x={last % 512}, y={last // 512}; "
        f"диапазон x={columns[0]}..{columns[-1]}, y={rows[0]}..{rows[-1]}; "
        f"по 64px-полосам={strip_counts}")


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    source = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" /
        "Terrain" / "all_stage_terrain.json"
    ).read_text(encoding="utf-8"))
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    assert machine.get_byte(symbols["RTypeTargetValid"]) == 1
    assert machine.get_byte(symbols["RTypeTargetStage"]) == 1

    # Диагностическая autostart-сборка может уже находиться в игровом режиме.
    # Проверку восьми raw tilemap выполняем без FT812 texture path; ниже он
    # включается отдельно после установки точной модели двух coprocessor-команд.
    machine.set_byte(symbols["GameMode"], 0)
    for stage, definition in enumerate(source["stages"], start=1):
        install_stage_pack(machine, stage)
        steps = machine.call(
            symbols["RTypeTarget_SelectStage"], a=stage, max_steps=5_000_000)
        checkpoint = definition["checkpoints"][0]
        assert machine.get_byte(symbols["RTypeTargetValid"]) == 1
        assert machine.get_byte(symbols["RTypeTargetStage"]) == stage, (
            stage, machine.get_byte(symbols["RTypeTargetStage"]), steps,
            machine.reg.SP)
        assert machine.get_word(symbols["RTypeTargetEventCount"]) == len(
            definition["events"])
        assert machine.get_word(symbols["RTypeWorldProgressQ8"] + 1) == int(
            checkpoint["progression"])
        assert machine.get_word(symbols["RTypeWorldFgVelocity"]) == (
            int(checkpoint["foreground_velocity_q8"]) & 0xFFFF)
        assert machine.get_word(symbols["RTypeWorldBgVelocity"]) == (
            int(checkpoint["background_velocity_q8"]) & 0xFFFF)
        terrain = M72WorldTerrain(stage)
        foreground = bytes(machine.mem.physical[
            0x07 * 0x4000:0x08 * 0x4000])
        background = bytes(machine.mem.physical[
            0x08 * 0x4000:0x09 * 0x4000])
        assert foreground == bytes(terrain.vram[0])
        assert background == bytes(terrain.vram[1])
        assert machine.get_byte(symbols["RTypeWorldFgTracker"]) == 0x70
        assert machine.get_byte(symbols["RTypeWorldBgTracker"]) == 0x70

    install_texture_coprocessor(machine)
    expected_sprites = _unpack_index4(
        (ROOT / "Assets" / "Converted" / "Arcade" /
         "RTYPE_SPRITES_INDEX4.bin").read_bytes())
    cell_bytes = 16 * 16
    for first_code in range(0, 4096, 1024):
        machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
        for code in range(first_code, first_code + 1024):
            if code in (first_code, first_code + 512):
                before = machine.get_word(symbols["RTypeSpriteCacheNextSlot"])
                machine.call(symbols["RTypeSpriteCache_BeginFrame"],
                             max_steps=500_000)
                assert machine.get_word(
                    symbols["RTypeSpriteCacheNextSlot"]) == before
            machine.call(
                symbols["RTypeSpriteCache_LoadCell"],
                h=code >> 8, l=code & 0xFF, max_steps=500_000)
            assert not machine.reg.F & 1, code
            slot = (machine.reg.H << 8) | machine.reg.L
            first = slot * cell_bytes
            actual = bytes(machine.ft.ram_g[
                0x0C0000 + first:0x0C0000 + first + cell_bytes])
            expected = expected_sprites[
                code * cell_bytes:(code + 1) * cell_bytes]
            assert actual == expected, (code, slot)
        before = machine.get_word(symbols["RTypeSpriteCacheNextSlot"])
        machine.call(symbols["RTypeSpriteCache_BeginFrame"], max_steps=500_000)
        machine.call(
            symbols["RTypeSpriteCache_LoadCell"],
            h=first_code >> 8, l=first_code & 0xFF, max_steps=500_000)
        assert machine.get_word(symbols["RTypeSpriteCacheNextSlot"]) == before
        assert ((machine.reg.H << 8) | machine.reg.L) == 0
    machine.set_byte(symbols["GameMode"], 1)
    install_stage_pack(machine, 1)
    machine.reg.A = 1
    machine.call(symbols["RTypeTarget_SelectStage"], max_steps=5_000_000)
    oracle = M72WorldTerrain(1)
    for _ in range(130):
        machine.call(symbols["RTypeWorld_Update"], max_steps=200_000)
        oracle.advance()
    first_event = source["stages"][0]["events"][0]
    self_events = sum(
        int(event["threshold"]) <= oracle.progression
        for event in source["stages"][0]["events"])
    assert machine.get_word(symbols["RTypeTargetEventIndex"]) == self_events
    self_last = source["stages"][0]["events"][self_events - 1]
    assert machine.get_word(symbols["RTypeWorldLastCommand"]) == int(
        self_last["command"])
    assert machine.get_word(symbols["RTypeWorldLastHandler"]) == int(
        self_last["handler"])
    assert value24(machine, symbols["RTypeWorldProgressQ8"]) == (
        oracle.progression_accumulator & 0xFFFFFF)
    assert value24(machine, symbols["RTypeWorldFgScrollQ8"]) == (
        oracle.accumulator[0] & 0xFFFFFF)
    assert value24(machine, symbols["RTypeWorldBgScrollQ8"]) == (
        oracle.accumulator[2] & 0xFFFFFF)
    assert bytes(machine.mem.physical[0x07 * 0x4000:0x08 * 0x4000]) == bytes(
        oracle.vram[0])
    assert bytes(machine.mem.physical[0x08 * 0x4000:0x09 * 0x4000]) == bytes(
        oracle.vram[1])
    expected_foreground = ring_texture(bytes(oracle.vram[0]), TILES0.read_bytes())
    expected_background = ring_texture(bytes(oracle.vram[1]), TILES1.read_bytes())
    actual_foreground = bytes(machine.ft.ram_g[0x080000:0x0C0000])
    actual_background = bytes(machine.ft.ram_g[0x040000:0x080000])
    assert_slot_texture("foreground", actual_foreground, expected_foreground)
    assert_slot_texture("background", actual_background, expected_background)
    target_manifest = json.loads(
        (ROOT / "Build" / "rtype_target_pack.json").read_text(
            encoding="utf-8"))
    target_pack = (ROOT / "Build" / "rtype_target_pack.bin").read_bytes()
    palette = target_manifest["stages"][0]["tile_palette"]
    palette_first = int(palette["offset"])
    palette_size = int(palette["size"])
    # Первые 1024 байта — две неизменные terrain-палитры. Последние 512 байт
    # являются рабочим sprite-слотом: object automata законно заменяют его уже
    # на первых кадрах, поэтому сравнивать весь исходный stage blob неверно.
    terrain_palette_size = symbols["RTYPE_TARGET_SPRITE_PAL_OFF"]
    actual_palette = bytes(
        machine.ft.ram_g[0x01C000:0x01C000 + terrain_palette_size])
    expected_palette = target_pack[
        palette_first:palette_first + terrain_palette_size]
    mismatch = next((index for index, pair in enumerate(
        zip(actual_palette, expected_palette)) if pair[0] != pair[1]), None)
    assert actual_palette == expected_palette, (
        mismatch,
        actual_palette[mismatch:mismatch + 16].hex() if mismatch is not None else "",
        expected_palette[mismatch:mismatch + 16].hex() if mismatch is not None else "",
        machine.errors[-8:])

    # Изолированно пройти весь `$C46E/$C4BC/$C5F8` path. Здесь texture path
    # отключён: проверяются именно ROM direction/duration, signed Q8 velocity,
    # terminal sentinel и точный 384-VBlank обратный отсчёт.
    machine.set_byte(symbols["GameMode"], 0)
    install_stage_pack(machine, 3)
    machine.call(symbols["RTypeTarget_SelectStage"], a=3, max_steps=5_000_000)
    machine.call(symbols["RTypeWorld_Stage3Start"], max_steps=200_000)
    world_rom = (
        ROOT / "Assets" / "Converted" / "Arcade" /
        "RTYPE_MAINCPU_REGION.bin"
    ).read_bytes()[0x10000:0x20000]
    controller = Stage3BackgroundController(world_rom)
    terrain = M72WorldTerrain(3)
    terrain.stage3_background = controller
    for step in range(9664):
        machine.call(symbols["RTypeWorld_Stage3Update"], max_steps=20_000)
        controller.update(terrain)
        assert machine.get_word(symbols["RTypeWorldFgVelocity"]) == (
            terrain.velocity[0] & 0xFFFF)
        assert machine.get_word(symbols["RTypeWorldBgVelocity"]) == (
            terrain.velocity[2] & 0xFFFF)
        assert machine.get_word(symbols["RTypeWorldBgYVelocity"]) == (
            terrain.velocity[3] & 0xFFFF)
        if step == 9279:
            assert machine.get_byte(symbols["RTypeWorldStage3State"]) == 1
            assert machine.get_word(symbols["RTypeWorldStage3Terminal"]) == 0x0180
    assert controller.state == "done"
    assert machine.get_byte(symbols["RTypeWorldStage3Active"]) == 0
    assert machine.get_byte(symbols["RTypeWorldTransition"]) == 1

    # Семь `$F01B` записей должны переключать stage по stage byte глобальной
    # checkpoint-таблицы, не по придуманному `current+1`.
    for command, expected_stage in (
            (0x6404, 2), (0x6406, 3), (0x6407, 4), (0x6409, 5),
            (0x640B, 6), (0x640D, 7), (0x640F, 8)):
        install_stage_pack(machine, expected_stage)
        machine.set_word(symbols["RTypeWorldLastCommand"], command)
        machine.set_word(symbols["RTypeWorldLastHandler"], 0xF01B)
        machine.call(symbols["RTypeWorld_DispatchGlobal"], max_steps=5_000_000)
        assert machine.get_byte(symbols["RTypeTargetStage"]) == expected_stage

    print("Z80 target pack: magic/version и 8 stage records — OK")
    print("Checkpoint progression/FG/BG velocity: 8/8 exact")
    print("Начальные FG/BG ring tilemap: 8/8 byte-exact")
    print("Stage 1: 130 VBlank progression/scroll/events/strip pump exact")
    print("Stage 1: direct CMD_INFLATE и 8x64x512 RAM_G slots byte-exact")
    print("Все 4096 M72 sprite cells пакетами 1024 и palette byte-exact")
    print("Stage 3: ROM vertical path 9280+384 VBlank exact")
    print("Stage 1->8: семь `$F01B` checkpoint-переходов exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
