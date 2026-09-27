#!/usr/bin/env python3
"""Исполнить Z80-перенос финального event `$FB10` и runtime `$FB53`."""
from __future__ import annotations

import struct
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
OBJECT_BASE = OBJECT_PAGE * PAGE_SIZE
RECORD_SIZE = 0x40
SCRATCH = 0x4300


def set_word(machine: TSConfFT812Machine, address: int, value: int) -> None:
    machine.set_byte(address, value & 0xFF)
    machine.set_byte(address + 1, value >> 8)


def word(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    pack = (ROOT / "Build" / "rtype_target_pack.bin").read_bytes()
    world = pack[0x4000:0x14000]
    source_records: list[tuple[int, int, int]] = []
    cursor = 0x945C
    while True:
        record = struct.unpack_from("<3H", world, cursor)
        cursor += 6
        if record[0] == 0:
            break
        source_records.append(record)
    assert len(source_records) == 18

    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeTarget_Init"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=2_000_000)
    free_before = machine.get_byte(symbols["RTYPE_OBJECT_FREE_COUNT"])

    set_word(machine, symbols["RTypeWorldLastHandler"], 0xFB10)
    set_word(machine, symbols["RTypeWorldLastCommand"], 0xB800)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=20_000_000)

    expected_slots: dict[int, int] = {}
    for index, (stream, y, resource) in enumerate(source_records, start=2):
        expected_slots.setdefault(resource & 0xFF, len(expected_slots))
        record = bytes(machine.mem.physical[
            OBJECT_BASE + index * RECORD_SIZE:
            OBJECT_BASE + (index + 1) * RECORD_SIZE
        ])
        assert record[0] == symbols["RTYPE_OBJ_FINAL_STREAM_FB53"]
        assert word(record, 0x02) == 0x0120
        assert word(record, 0x04) == y
        assert word(record, 0x06) == struct.unpack_from("<H", world, stream + 6)[0]
        assert record[0x08] == expected_slots[resource & 0xFF]
        assert record[0x09] == (resource & 0xFF)
        assert word(record, 0x0A) == 0xFF70
        assert word(record, 0x20) == stream
        assert word(record, 0x22) == 0
    # Последнее чтение terminating word оставляет в slot3 страницу World ROM.
    # Поэтому allocator-state проверяется по физической object-page, а не через
    # текущий CPU mapping `$C000…$FFFF`.
    free_count = machine.mem.physical[
        OBJECT_BASE + (symbols["RTYPE_OBJECT_FREE_COUNT"] - 0xC000)
    ]
    assert free_count == free_before - 18

    # Первый timeline `$94CA` держит нулевую скорость до cumulative `$03C0`.
    # На граничном update pointer становится `$94D2`, затем применяется
    # `(vx=$0140,vy=0,descriptor=$96E2)` с Q8 fraction `$40`.
    machine.call(symbols["RTypeObjects_LoadScratch"], a=2, max_steps=200_000)
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FB_ELAPSED"], 0x03BF)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalStreamFB53"],
                 max_steps=5_000_000)
    assert word(bytes(machine.mem.read(SCRATCH + i) for i in range(64)),
                symbols["RTYPE_OBJ_FB_STREAM"]) == 0x94D2
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_X_FRACTION"]) == 0x40
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_X"]) == 0x21
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_X"] + 1) == 0x01
    assert word(bytes(machine.mem.read(SCRATCH + i) for i in range(64)),
                symbols["RTYPE_OBJ_DESCRIPTOR"]) == 0x96E2

    print(
        "$FB10/$FB53: 18 ROM objects, resource slots, cumulative timeline "
        "и Q8 boundary — OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
