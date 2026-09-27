#!/usr/bin/env python3
"""Исполнить Z80-перенос финальных event `$EEAB/$EE0B`."""
from __future__ import annotations

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


def word(machine: TSConfFT812Machine, address: int) -> int:
    return machine.get_byte(address) | (machine.get_byte(address + 1) << 8)


def set_word(machine: TSConfFT812Machine, address: int, value: int) -> None:
    machine.set_byte(address, value)
    machine.set_byte(address + 1, value >> 8)


def physical_record(machine: TSConfFT812Machine, index: int) -> bytes:
    start = OBJECT_BASE + index * RECORD_SIZE
    return bytes(machine.mem.physical[start:start + RECORD_SIZE])


def dispatch(machine: TSConfFT812Machine, symbols: dict[str, int],
             handler: int, command: int) -> None:
    set_word(machine, symbols["RTypeWorldLastHandler"], handler)
    set_word(machine, symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=20_000_000)


def fresh_machine(symbols: dict[str, int]) -> TSConfFT812Machine:
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeTarget_Init"], max_steps=1_000_000)
    return machine


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")

    # `$EE0B`: immediate stop, затем только восемь pass после strip barrier.
    machine = fresh_machine(symbols)
    for name in (
        "RTypeWorldFgScrollQ8", "RTypeWorldBgScrollQ8",
        "RTypeWorldFgYScrollQ8", "RTypeWorldBgYScrollQ8",
        "RTypeWorldFgVelocity", "RTypeWorldBgVelocity",
        "RTypeWorldFgYVelocity", "RTypeWorldBgYVelocity",
    ):
        machine.set_byte(symbols[name], 0x55)
        machine.set_byte(symbols[name] + 1, 0xAA)
    dispatch(machine, symbols, 0xEE0B, 0xC000)
    record = physical_record(machine, 2)
    assert record[0] == symbols["RTYPE_OBJ_FINAL_RESET_EE3C"]
    assert int.from_bytes(record[0x0A:0x0C], "little") == 0x0200
    assert int.from_bytes(
        record[symbols["RTYPE_OBJ_FINAL_TIMER"]:
               symbols["RTYPE_OBJ_FINAL_TIMER"] + 2], "little") == 8
    assert word(machine, symbols["RTypeWorldFgVelocity"]) == 0
    assert word(machine, symbols["RTypeWorldBgYVelocity"]) == 0

    machine.call(symbols["RTypeObjects_LoadScratch"], a=2, max_steps=200_000)
    machine.set_byte(symbols["RTypeWorldFgTracker"], 0x10)
    machine.set_byte(symbols["RTypeWorldFgTarget"], 0x20)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalResetEE3C"],
                 max_steps=1_000_000)
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"]) == 8
    machine.set_byte(symbols["RTypeWorldFgTracker"], 0x20)
    for _ in range(8):
        machine.call(symbols["RTypeObjectBank4_UpdateFinalResetEE3C"],
                     max_steps=20_000_000)
    assert machine.get_byte(SCRATCH) == 0
    assert machine.get_byte(symbols["RTypeTargetStage"]) == 1
    assert word(machine, symbols["RTypeWorldProgressQ8"] + 1) == 0x06C0
    assert machine.get_byte(symbols["RTypeFinalLoopCount"]) == 1

    # Первый финальный круг: `$0560` timeline → 128 + 64 palette passes.
    machine = fresh_machine(symbols)
    dispatch(machine, symbols, 0xEEAB, 0xBC00)
    record = physical_record(machine, 2)
    assert record[0] == symbols["RTYPE_OBJ_FINAL_SEQUENCE_EEB5"]
    assert int.from_bytes(record[0x0A:0x0C], "little") == 0x0100
    machine.call(symbols["RTypeObjects_LoadScratch"], a=2, max_steps=200_000)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 1
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TABLE"]) == 0x88E8
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_CADENCE"]) == 0x0030
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_LIFETIME"]) == 0x0560
    machine.set_byte(symbols["RTypeWorldFgTracker"], 0x70)
    machine.set_byte(symbols["RTypeWorldFgTarget"], 0x70)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 2
    assert word(machine, symbols["RTypeWorldFgYVelocity"]) == 0x0080
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_CADENCE"], 1)
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_LIFETIME"], 1)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=5_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 3
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"]) == 0x0080
    palette_base = OBJECT_BASE + (symbols["RTYPE_PALETTE_BANK2_RECORDS"] - 0xC000)
    slot1 = bytes(machine.mem.physical[palette_base + 12:palette_base + 24])
    assert slot1[0] == 0x10 and slot1[1] == 0x80
    assert slot1[4] == 1 and slot1[10] == 0x1F
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"], 1)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=10_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 4
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"]) == 0x0040
    for slot in range(15):
        palette = bytes(machine.mem.physical[
            palette_base + slot * 12:palette_base + (slot + 1) * 12
        ])
        assert palette[0] == 0 and palette[1] == 0x80 and palette[4] == 1
        assert int.from_bytes(palette[8:10], "little") == 3
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"], 1)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH) == 0
    assert word(machine, symbols["RTypeWorldFgVelocity"]) == 0x0080

    # Повторный круг выбирает `$EFAD…$F012`: player-exit и completion latch.
    machine = fresh_machine(symbols)
    machine.set_byte(symbols["RTypeFinalLoopCount"], 1)
    dispatch(machine, symbols, 0xEEAB, 0xBC00)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=2, max_steps=200_000)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    machine.set_byte(symbols["RTypeWorldFgTracker"], 0x70)
    machine.set_byte(symbols["RTypeWorldFgTarget"], 0x70)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_LIFETIME"], 1)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 5
    assert word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"]) == 0x0120
    set_word(machine, SCRATCH + symbols["RTYPE_OBJ_FINAL_TIMER"], 1)
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_STATE"]) == 6
    assert machine.get_byte(symbols["RTypeFinalPlayerExitLatch"]) == 0xFF
    sound_address = OBJECT_BASE + (symbols["RTYPE_LAST_SOUND_COMMAND"] - 0xC000)
    assert machine.mem.physical[sound_address] == 0x22
    machine.call(symbols["RTypeObjectBank4_UpdateFinalSequenceEEB5"],
                 max_steps=2_000_000)
    assert machine.get_byte(SCRATCH) == 0
    assert machine.get_byte(symbols["RTypeWorldTransition"]) == 2

    print(
        "$EEAB/$EE0B: strip barrier, `$0560` timeline, DMA palette phases, "
        "loop reset и player-exit — OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
