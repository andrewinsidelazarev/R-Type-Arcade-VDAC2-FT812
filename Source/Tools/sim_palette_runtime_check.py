#!/usr/bin/env python3
"""Проверить предвычисленные палитры, DMA и `$5526/$5596` на Z80-модели."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"
))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE_SIZE = 0x4000
OBJECT_PAGE = 0x09
OBJECT_WINDOW = 0xC000
TILE_PALETTE_RAMG = 0x01C000
SPRITE_PALETTE_RAMG = 0x01C400
TYPE_BYTES = 32
TILE_ALPHA_OFFSET = 0x1000
SPRITE_OFFSET = 0x2000


def set_word(machine: TSConfFT812Machine, address: int, value: int) -> None:
    machine.set_byte(address, value & 0xFF)
    machine.set_byte(address + 1, (value >> 8) & 0xFF)


def physical_object(symbols: dict[str, int], name: str) -> int:
    return OBJECT_PAGE * PAGE_SIZE + symbols[name] - OBJECT_WINDOW


def expected_argb4444(maincpu: bytes, bank: int, resource_type: int,
                      transparent_pen0: bool) -> bytes:
    result = bytearray()
    source = 0x3B000 + bank + resource_type * 48
    for pen in range(16):
        red, green, blue = maincpu[source + pen * 3:source + pen * 3 + 3]
        red4 = (red * 15 + 15) // 31
        green4 = (green * 15 + 15) // 31
        blue4 = (blue * 15 + 15) // 31
        alpha = 0 if transparent_pen0 and pen == 0 else 15
        value = (alpha << 12) | (red4 << 8) | (green4 << 4) | blue4
        result += value.to_bytes(2, "little")
    return bytes(result)


def record_words(machine: TSConfFT812Machine, address: int) -> tuple[int, ...]:
    data = bytes(machine.mem.physical[address:address + 12])
    return tuple(int.from_bytes(data[index:index + 2], "little")
                 for index in range(0, 12, 2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sym", type=Path, default=ROOT / "Build" / "rtype.sym",
        help="таблица символов, соответствующая текущим бинарным страницам",
    )
    args = parser.parse_args()
    symbols = parse_sym(args.sym)
    manifest = json.loads(
        (ROOT / "Build" / "rtype_target_pack.json").read_text(encoding="utf-8")
    )
    pack = (ROOT / "Build" / "rtype_target_pack.bin").read_bytes()
    maincpu = (
        ROOT / "Assets" / "Converted" / "Arcade" /
        "RTYPE_MAINCPU_REGION.bin"
    ).read_bytes()
    palette = manifest["globals"]["palettes"]
    base = int(palette["offset"])
    table = pack[base:base + int(palette["size"])]
    assert len(table) == PAGE_SIZE

    # Несколько краевых type доказывают обе M72 RGB ROM области и alpha pen 0.
    for resource_type in (0x00, 0x17, 0x55, 0x7B, 0x7F):
        start = resource_type * TYPE_BYTES
        assert table[start:start + TYPE_BYTES] == expected_argb4444(
            maincpu, 0x2400, resource_type, False)
        assert table[TILE_ALPHA_OFFSET + start:
                     TILE_ALPHA_OFFSET + start + TYPE_BYTES] == expected_argb4444(
            maincpu, 0x2400, resource_type, True)
    for resource_type in (0x00, 0x57, 0x7F, 0x80, 0xFF):
        start = SPRITE_OFFSET + resource_type * TYPE_BYTES
        assert table[start:start + TYPE_BYTES] == expected_argb4444(
            maincpu, 0x0000, resource_type, True)

    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=args.sym,
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    # Title_Init использует `$4300…$46FF` как копию M72 sprite RAM. Реальный
    # вход в GAME после reset всегда повторно вызывает RTypeTarget_Init.
    machine.call(symbols["RTypeTarget_Init"], max_steps=1_000_000)

    # Транслятор заменяет лежащую за границей `$8000` обёртку на JP в
    # постоянно отображённую page 0. Возврат после bank4 больше не зависит
    # от строки кэша, которую вытеснил код обработчика.
    wrapper = symbols["RTypeObjectBank4_InitPaletteControl"]
    bridge = symbols[
        "RTypePyBridge_RTypeObjectBank4_InitPaletteControl"]
    wrapper_physical = 0x06 * PAGE_SIZE + wrapper - 0x8000
    assert bytes(machine.mem.physical[
        wrapper_physical:wrapper_physical + 3]) == bytes((
            0xC3, bridge & 0xFF, bridge >> 8))

    # Первый acquire загружает sprite palette в назначенный slot одним DMA.
    for slot, resource_type in enumerate((0x57, 0x59, 0x5A, 0xFE)):
        machine.call(symbols["RTypeResources_Acquire"], a=resource_type,
                     max_steps=1_000_000)
        assert machine.reg.A == slot
        expected = table[
            SPRITE_OFFSET + resource_type * TYPE_BYTES:
            SPRITE_OFFSET + (resource_type + 1) * TYPE_BYTES
        ]
        actual = bytes(machine.ft.ram_g[
            SPRITE_PALETTE_RAMG + slot * TYPE_BYTES:
            SPRITE_PALETTE_RAMG + (slot + 1) * TYPE_BYTES
        ])
        assert actual == expected, (slot, resource_type)

    # Прямой `$54E4`-эквивалент обновляет обе FT812 tile palette копии и
    # сохраняет точные шесть words управляющей записи `$2DF4`.
    machine.call(symbols["RTypePalette_SetTile"], a=0x17, c=7, d=0, e=0x0F,
                 max_steps=1_000_000)
    for destination, source in (
        (TILE_PALETTE_RAMG + 7 * TYPE_BYTES, 0x17 * TYPE_BYTES),
        (TILE_PALETTE_RAMG + 512 + 7 * TYPE_BYTES,
         TILE_ALPHA_OFFSET + 0x17 * TYPE_BYTES),
    ):
        assert bytes(machine.ft.ram_g[destination:destination + TYPE_BYTES]) == (
            table[source:source + TYPE_BYTES]
        )
    records = physical_object(symbols, "RTYPE_PALETTE_BANK2_RECORDS")
    assert record_words(machine, records + 7 * 12) == (
        0x8017, 0, 1, 0, 0x000F, 0x001F)

    # `$5526` index 9 берёт буквальную пару `(slot=$0F,type=$0F)`.
    set_word(machine, symbols["RTypeWorldLastHandler"], 0x5526)
    set_word(machine, symbols["RTypeWorldLastCommand"], 0x6009)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=2_000_000)
    assert record_words(machine, records + 15 * 12) == (
        0x800F, 0, 1, 0, 0x000F, 0x001F)

    # Именно `$6004` оставался последней командой в живом дампе зависания.
    # После resident-моста он возвращается в Core page #06 с прежним SP.
    set_word(machine, symbols["RTypeWorldLastHandler"], 0x5526)
    set_word(machine, symbols["RTypeWorldLastCommand"], 0x6004)
    stack_before = machine.reg.SP
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=2_000_000)
    assert machine.reg.SP == stack_before
    assert machine.mem.pages[2] == 0x06
    assert record_words(machine, records + 10 * 12) == (
        0x8000, 0, 1, 0, 0x000F, 0x001F)

    # `$5596` активирует ровно первые 15 slots и не трогает служебный slot 15.
    before_slot15 = bytes(machine.mem.physical[records + 15 * 12:records + 16 * 12])
    set_word(machine, symbols["RTypeWorldLastHandler"], 0x5596)
    set_word(machine, symbols["RTypeWorldLastCommand"], 0x6800)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=8_000_000)
    for slot in range(15):
        assert record_words(machine, records + slot * 12) == (
            0x8000, 0, 1, 0, 0x0003, 0x001F)
    assert bytes(machine.mem.physical[
        records + 15 * 12:records + 16 * 12]) == before_slot15

    print(
        "palette runtime: RGB ROM→ARGB4444, sprite acquire DMA, "
        "$54E4/$5526/$5596 — OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
