#!/usr/bin/env python3
"""Проверить перенесённые Beam meter/orb renderer-ы в собранном Z80 SPG."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


CHARGE_RAMG = 0x02C000
ATLAS_RAMG = 0x020000
GLYPH_BYTES = 14 * 15 * 2


def commands(machine: TSConfFT812Machine, symbols: dict[str, int],
             routine: str) -> bytes:
    command_buffer = symbols["RTypeFTCommandBufferStart"]
    command_end = symbols["RTypeFTCommandBufferEnd"]
    machine.set_word(symbols["FT.Coprocessor.BufferPtr"], command_buffer)
    machine.call(symbols[routine], max_steps=500_000)
    end = machine.get_word(symbols["FT.Coprocessor.BufferPtr"])
    assert command_buffer <= end < command_end, hex(end)
    return bytes(machine.get_byte(address)
                 for address in range(command_buffer, end))


def words(data: bytes) -> list[int]:
    assert not len(data) & 3
    return [int.from_bytes(data[offset:offset + 4], "little")
            for offset in range(0, len(data), 4)]


def bitmap_sources(data: bytes) -> list[int]:
    return [word & 0x3FFFFF for word in words(data) if word >> 24 == 1]


def vertices(data: bytes) -> list[tuple[int, int]]:
    return [((word >> 15) & 0x7FFF, word & 0x7FFF)
            for word in words(data) if word >> 30 == 1]


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)

    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "Player" /
        "r9_pitch.json").read_text(encoding="utf-8"))
    charge_info = manifest["charge_binary"]
    charge_blob = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Player" /
        charge_info["file"]).read_bytes()
    charge_records = sorted(
        (record for record in manifest["records"]
         if record["kind"] == "charge"), key=lambda record: record["phase"])

    machine.call(symbols["RTypePyChargeAssetsUpload"], max_steps=5_000_000)
    assert bytes(machine.ft.ram_g[
        CHARGE_RAMG:CHARGE_RAMG + len(charge_blob)]) == charge_blob

    machine.set_word(symbols["ArcadeIntroFrame"], 226)
    machine.set_byte(symbols["ArcadeFireHeld"], 1)
    machine.set_byte(symbols["ArcadeWaveCharge"], 0x80)
    machine.set_word(symbols["ArcadePlayerX"] + 1, 233)
    machine.set_word(symbols["ArcadePlayerY"] + 1, 192)
    source_offset = int(charge_info["source_offset"])
    for phase, frame in enumerate(range(0, 32, 4)):
        machine.set_word(symbols["FrameCounter"], frame)
        data = commands(machine, symbols, "RTypePyRenderChargeOrb")
        expected = CHARGE_RAMG + int(charge_records[phase]["offset"]) - source_offset
        assert bitmap_sources(data) == [expected], (phase, bitmap_sources(data), expected)
        assert len(vertices(data)) == 1

    machine.set_word(symbols["ArcadeIntroFrame"], 225)
    assert commands(machine, symbols, "RTypePyRenderChargeOrb") == b""
    machine.set_word(symbols["ArcadeIntroFrame"], 226)
    beam_blob = (ROOT / "Build" / "rtype_python_beam_commands.bin").read_bytes()
    atlas_bytes = (ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" /
                   "TILE_ATLAS_ARGB4444.bin").read_bytes()
    assert len(beam_blob) == 65 * 17 * 8

    for charge in (0, 0x40, 0x80):
        machine.set_byte(symbols["ArcadeWaveCharge"], charge)
        data = commands(machine, symbols, "RTypePyRenderBeamMeterBody")
        state_offset = (charge // 2) * 17 * 8
        strip = beam_blob[state_offset:state_offset + 17 * 8]
        strip_words = words(strip)
        expected_sources = [word & 0x3FFFFF for word in strip_words[0::2]]
        assert bitmap_sources(data) == expected_sources
        points = vertices(data)
        expected_points = [((word >> 15) & 0x7FFF, word & 0x7FFF)
                           for word in strip_words[1::2]]
        assert points == expected_points
        assert points[0][1] == 720 * 8 and points[-1][1] == 720 * 8
        for source in expected_sources:
            assert ATLAS_RAMG <= source < ATLAS_RAMG + len(atlas_bytes)
            cell = machine.ft.ram_g[source:source + GLYPH_BYTES]
            pixels = [int.from_bytes(cell[offset:offset + 2], "little")
                      for offset in range(0, len(cell), 2)]
            assert any(pixel & 0xF000 for pixel in pixels)

    machine.set_word(symbols["ArcadeIntroFrame"], 225)
    assert commands(machine, symbols, "RTypePyRenderBeamMeterBody") == b""
    print(
        "Beam renderer: 8 charge phases and 65-state tile-strip selector; "
        "RAM_G upload/source/17 vertices exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
