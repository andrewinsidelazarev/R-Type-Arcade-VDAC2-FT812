#!/usr/bin/env python3
"""Проверка Z80 runtime replay девяти MAME VRAM-пакетов Stage 1."""
from __future__ import annotations

import struct
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from sim_frame_png import DLRenderer  # noqa: E402
from sim_player_shot_check import bitmap_draws, vertex_units  # noqa: E402


def decode_stream(data: bytes, page_size: int = 0x4000
                  ) -> list[tuple[int, list[tuple[int, int]],
                                  list[tuple[int, int]]]]:
    result = []
    offset = 0
    while True:
        frame, fg_count, bg_count = struct.unpack_from("<HBB", data, offset)
        offset += 4
        if frame == 0xFFFF:
            return result
        if frame == 0xFFFE:
            offset = (offset + page_size - 1) // page_size * page_size
            continue
        layers = []
        for count in (fg_count, bg_count):
            records = []
            for _ in range(count):
                index, slot = struct.unpack_from("<HH", data, offset)
                offset += 4
                records.append((index, slot))
            layers.append(records)
        result.append((frame, layers[0], layers[1]))


def apply(records: list[tuple[int, int]], target: bytearray) -> None:
    for index, slot in records:
        struct.pack_into("<H", target, index * 2, slot)


def render(machine: TSConfFT812Machine, symbols: dict[str, int],
           name: str) -> tuple[Path, bytes]:
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=5_000_000)
    assert machine.ft.cmd_write_ptr < 4096
    commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
    renderer = DLRenderer(bytes(machine.ft.ram_g))
    renderer.run(commands)
    path = ROOT / "Build" / name
    renderer.img.save(path)
    return path, commands


def assert_player_draws(commands: bytes, assets: list[dict[str, int]],
                        x: int, y: int) -> None:
    draws = bitmap_draws(commands)
    body_asset = assets[0]
    exhaust_asset = assets[1]
    body = [draw for draw in draws
            if draw["source"] == body_asset["offset"]
            and draw["width"] == body_asset["physical_width"]
            and draw["height"] == body_asset["physical_height"]]
    exhaust = [draw for draw in draws
               if draw["source"] == exhaust_asset["offset"]
               and draw["width"] == exhaust_asset["physical_width"]
               and draw["height"] == exhaust_asset["physical_height"]]
    assert body and exhaust
    assert body[-1]["x_units"] == vertex_units(x)
    assert body[-1]["y_units"] == vertex_units(y)
    assert exhaust[-1]["x_units"] == vertex_units(x - 50)
    assert exhaust[-1]["y_units"] == vertex_units(y + 3)


def assert_page_crossing(machine: TSConfFT812Machine,
                         symbols: dict[str, int], fg_page: int,
                         bg_page: int) -> None:
    """Принудительно провести два пакета через marker $FFFE и две страницы."""
    stream_pages = (0xF0, 0xF1)
    fg_old = struct.unpack("<H", machine.mem.read_physical(fg_page, 0, 2))[0]
    bg_old = struct.unpack("<H", machine.mem.read_physical(bg_page, 2, 2))[0]
    fg_new = 0x0123
    bg_new = 0x0345
    first = (struct.pack("<HBBHH", 600, 1, 0, 0, fg_new)
             + struct.pack("<HBB", 0xFFFE, 0, 0))
    second = (struct.pack("<HBBHH", 601, 0, 1, 1, bg_new)
              + struct.pack("<HBB", 0xFFFF, 0, 0))
    machine.mem.write_physical(stream_pages[0], 0, first)
    machine.mem.write_physical(stream_pages[1], 0, second)
    table = machine.get_word(symbols["M72StageEventTablePtr"])
    for offset, value in enumerate((stream_pages[0], len(first), 0,
                                    stream_pages[1], len(second), 0)):
        machine.set_byte(table + offset, value)

    machine.call(symbols["M72StageEvents_Reset"], max_steps=100_000)
    machine.set_word(symbols["ArcadeStageFrame"], 600)
    machine.call(symbols["M72StageEvents_Update"], max_steps=1_000_000)
    assert machine.get_byte(symbols["M72StageEventPageIndex"]) == 1
    assert struct.unpack("<H", machine.mem.read_physical(fg_page, 0, 2))[0] == fg_new
    assert struct.unpack("<H", machine.mem.read_physical(bg_page, 2, 2))[0] == bg_old

    machine.set_word(symbols["ArcadeStageFrame"], 601)
    machine.call(symbols["M72StageEvents_Update"], max_steps=1_000_000)
    assert struct.unpack("<H", machine.mem.read_physical(bg_page, 2, 2))[0] == bg_new
    assert machine.get_byte(symbols["M72StageEventDone"]) == 1


def assert_high_slot_source(machine: TSConfFT812Machine,
                            symbols: dict[str, int], fg_page: int,
                            bg_page: int) -> None:
    slot = 300
    base = (machine.get_word(symbols["M72StageFgAtlasLo"]) |
            machine.get_byte(symbols["M72StageFgAtlasHi"]) << 16)
    foreground = bytearray(b"\xFF" * 4096)
    struct.pack_into("<H", foreground, 8 * 2, slot)
    machine.mem.write_physical(fg_page, 0, foreground)
    machine.mem.write_physical(bg_page, 0, b"\xFF" * 4096)
    machine.set_word(symbols["M72_ScrollFgX"], 0)
    machine.set_word(symbols["M72_ScrollBgX"], 0)
    machine.ft.cmd_write_ptr = 0
    machine.call(symbols["Render_Frame"], max_steps=5_000_000)
    commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
    expected = base + slot * 420
    assert any(draw["source"] == expected for draw in bitmap_draws(commands))


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=60_000_000)
    machine.set_byte(symbols["GameMode"], 1)

    section_dir = (ROOT / "Assets" / "Converted" / "Arcade" /
                   "Stage1" / "Sections")
    runtime_starts = [1, 2603, 5603, 8603, 11603, 14103]
    manifest = json.loads((ROOT / "Assets" / "Converted" / "Arcade" /
                           "Sprites" /
                           "frame_000900_sprite_assets.json").read_text(
                               encoding="utf-8"))
    sprite_blob = (ROOT / "Assets" / "Converted" / "Arcade" / "Sprites" /
                   "RTYPE_M72_FRAME900_ARGB4444.bin").read_bytes()
    before_path, before_commands = render(
        machine, symbols, "stage_event_host_before.png")
    assert_player_draws(before_commands, manifest["assets"], 233, 192)
    total_packets = 0
    page_counts = []
    for section, runtime_start in enumerate(runtime_starts):
        if section:
            machine.set_word(symbols["ArcadeStageFrame"], runtime_start)
            machine.call(symbols["M72StageSections_Update"],
                         max_steps=40_000_000)
        assert machine.get_byte(symbols["M72StageSectionIndex"]) == section
        bg_page = machine.get_byte(symbols["M72StageBgMapPage"])
        fg_page = machine.get_byte(symbols["M72StageFgMapPage"])
        table = machine.get_word(symbols["M72StageEventTablePtr"])
        event_page = machine.get_byte(table)
        assert event_page not in (bg_page, fg_page)
        prefix = f"STAGE1_S{section}"
        initial_bg = bytearray((section_dir / f"{prefix}_BG_MAP.bin").read_bytes())
        initial_fg = bytearray((section_dir / f"{prefix}_FG_MAP.bin").read_bytes())
        assert machine.mem.read_physical(bg_page, 0, 4096) == initial_bg
        assert machine.mem.read_physical(fg_page, 0, 4096) == initial_fg

        bg_atlas = (section_dir /
                    f"{prefix}_BG_ATLAS_ARGB4444.bin").read_bytes()
        fg_atlas = (section_dir /
                    f"{prefix}_FG_ATLAS_ARGB4444.bin").read_bytes()
        bg_base = (machine.get_word(symbols["M72StageBgAtlasLo"]) |
                   machine.get_byte(symbols["M72StageBgAtlasHi"]) << 16)
        fg_base = (machine.get_word(symbols["M72StageFgAtlasLo"]) |
                   machine.get_byte(symbols["M72StageFgAtlasHi"]) << 16)
        assert bytes(machine.ft.ram_g[bg_base:bg_base + len(bg_atlas)]) == bg_atlas
        assert bytes(machine.ft.ram_g[fg_base:fg_base + len(fg_atlas)]) == fg_atlas
        assert fg_base == bg_base + len(bg_atlas)
        assert bytes(machine.ft.ram_g[:len(sprite_blob)]) == sprite_blob, (
            section, "section upload damaged resident M72 sprites")

        stream_blob = (section_dir / f"{prefix}_EVENTS.bin").read_bytes()
        packets = decode_stream(stream_blob)
        total_packets += len(packets)
        page_counts.append((len(stream_blob) + 0x3FFF) // 0x4000)
        by_frame: dict[int, list[tuple[list[tuple[int, int]],
                                       list[tuple[int, int]]]]] = {}
        for frame, foreground, background in packets:
            by_frame.setdefault(frame, []).append((foreground, background))
        expected_bg = initial_bg.copy()
        expected_fg = initial_fg.copy()
        frames = list(by_frame)
        checkpoints = sorted({frames[len(frames) // 3],
                              frames[(len(frames) * 2) // 3], frames[-1]})
        applied = 0
        for frame in checkpoints:
            while applied < len(frames) and frames[applied] <= frame:
                for foreground, background in by_frame[frames[applied]]:
                    apply(foreground, expected_fg)
                    apply(background, expected_bg)
                applied += 1
            machine.set_word(symbols["ArcadeStageFrame"], frame)
            machine.call(symbols["M72StageEvents_Update"], max_steps=20_000_000)
            assert machine.mem.read_physical(fg_page, 0, 4096) == expected_fg, (
                section, frame, "foreground")
            assert machine.mem.read_physical(bg_page, 0, 4096) == expected_bg, (
                section, frame, "background")
        assert machine.get_byte(symbols["M72StageEventDone"]) == 1

    machine.set_word(symbols["M72_ScrollBgX"], 175 + 17103)
    machine.set_word(symbols["M72_ScrollFgX"], 87 + 17103 // 2)
    after_path, after_commands = render(
        machine, symbols, "stage_event_host_after.png")
    assert_player_draws(after_commands, manifest["assets"], 233, 192)
    assert before_path.read_bytes() != after_path.read_bytes()
    assert_page_crossing(machine, symbols, fg_page, bg_page)
    assert_high_slot_source(machine, symbols, fg_page, bg_page)
    print(f"Stage 1 VRAM-delta: 6 секций / {total_packets} пакетов byte-exact — OK")
    print(f"страницы потоков по секциям: {page_counts}; финал events=${event_page:02X}, "
          f"BG=${bg_page:02X}, FG=${fg_page:02X}")
    print(f"display list: до={len(before_commands)}, после={len(after_commands)} байт")
    print("страничный marker $FFFE: переход $F0->$F1 — OK")
    print("16-битный slot 300: BITMAP_SOURCE — OK")
    print(f"кадры: {before_path.name}, {after_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
