#!/usr/bin/env python3
"""Исполнить последние `$A22E/$B0E1/$B1D8/$C0A9` автоматы на Z80."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"
))

from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE_SIZE = 0x4000
OBJECT_PAGE = 0x09
OBJECT_BASE = OBJECT_PAGE * PAGE_SIZE
RECORD_SIZE = 0x40
SCRATCH = 0x4300


def word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address:address + 2] = (value & 0xFFFF).to_bytes(2, "little")


def record_base(index: int) -> int:
    return OBJECT_BASE + index * RECORD_SIZE


def reset(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    machine.call(symbols["RTypeTarget_Init"], max_steps=1_000_000)


def dispatch(machine: TSConfFT812Machine, symbols: dict[str, int],
             handler: int, command: int = 0) -> None:
    machine.set_word(symbols["RTypeWorldLastHandler"], handler)
    machine.set_word(symbols["RTypeWorldLastCommand"], command)
    machine.call(symbols["RTypeObjects_DispatchEvent"], max_steps=20_000_000)


def load(machine: TSConfFT812Machine, symbols: dict[str, int], index: int) -> None:
    machine.set_byte(symbols["RTypeObjects_CurrentIndex"], index)
    machine.call(symbols["RTypeObjects_LoadScratch"], a=index,
                 max_steps=500_000)


def store(machine: TSConfFT812Machine, symbols: dict[str, int], index: int) -> None:
    machine.call(symbols["RTypeObjects_StoreScratch"], a=index,
                 max_steps=500_000)


def update(machine: TSConfFT812Machine, symbols: dict[str, int], index: int,
           trampoline: str, max_steps: int = 20_000_000) -> None:
    load(machine, symbols, index)
    machine.call(symbols[trampoline], max_steps=max_steps)
    if machine.get_byte(SCRATCH + symbols["RTYPE_OBJ_TYPE"]):
        store(machine, symbols, index)


def check_a22(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    reset(machine, symbols)
    dispatch(machine, symbols, 0xA22E)
    memory = machine.mem.physical
    root = record_base(2)
    assert memory[root] == symbols["RTYPE_OBJ_STAGE_CONTROLLER"]
    assert memory[root + symbols["RTYPE_OBJ_CTRL_KIND"]] == 1
    assert word(memory, root + 0x0A) == 0x3800
    assert machine.get_word(symbols["RTypeWorldFgVelocity"]) == 0
    assert machine.get_word(symbols["RTypeWorldStageControllerHandler"]) == 0xA290

    # Первый multipart появляется ровно при исчерпании `$0164`.
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_TIMER"], 1)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert memory[record_base(3)] == symbols["RTYPE_OBJ_MULTIPART_915B_PARENT"]
    assert word(memory, root + symbols["RTYPE_OBJ_CTRL_TIMER"]) == 0x03C0
    assert machine.get_word(symbols["RTypeWorldLastCommand"]) == 2

    # Threshold `$0038` переносит готовый terrain rectangle и сдвигает cursor.
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x0038)
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_TIMER"], 2)
    before = bytes(memory[0x07 * PAGE_SIZE:0x08 * PAGE_SIZE])
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    after = bytes(memory[0x07 * PAGE_SIZE:0x08 * PAGE_SIZE])
    assert after != before

    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x173F)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert machine.get_byte(symbols["RTypeFinalPlayerExitLatch"]) == 0xFF
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x177F)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert machine.get_byte(SCRATCH) == 0
    assert machine.get_word(symbols["RTypeWorldFgVelocity"]) == 0x0080


def check_b0(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    reset(machine, symbols)
    dispatch(machine, symbols, 0xB0E1)
    memory = machine.mem.physical
    root = record_base(2)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert memory[record_base(3)] == symbols["RTYPE_OBJ_ENEMY_5EED"]
    assert machine.get_word(symbols["RTypeWorldLastCommand"]) == 0x2020
    assert word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"]) == 1

    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x07FF)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert memory[root + symbols["RTYPE_OBJ_CTRL_PHASE"]] == 1
    assert word(memory, root + symbols["RTYPE_OBJ_CTRL_EXIT_TIMER"]) == 0x0090
    cleanup = OBJECT_BASE + (symbols["RTYPE_CLEANUP_ACTIVE"] - 0xC000)
    assert memory[cleanup] == 0xFF
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_EXIT_TIMER"], 0x0081)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert machine.get_byte(symbols["RTypeFinalPlayerExitLatch"]) == 0xFF
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_EXIT_TIMER"], 1)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert machine.get_byte(SCRATCH) == 0
    assert machine.get_word(symbols["RTypeWorldFgVelocity"]) == 0x0080


def check_b1(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    reset(machine, symbols)
    dispatch(machine, symbols, 0xB1D8)
    memory = machine.mem.physical
    root = record_base(2)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateBossB1D8Root",
           max_steps=100_000_000)
    assert memory[root] == symbols["RTYPE_OBJ_B1D8_ROOT"]
    assert memory[root + symbols["RTYPE_OBJ_STATE"]] == 1
    children = [index for index in range(3, 96)
                if memory[record_base(index)] == symbols["RTYPE_OBJ_B1D8_CHILD"]]
    assert len(children) == 37
    assert word(memory, root + 0x02) == 0x0260
    assert word(memory, root + 0x04) == 0x0060
    assert word(memory, root + 0x06) == 0x6082
    assert memory[root + symbols["RTYPE_OBJ_B1_REMAINING"]] == 37
    first = record_base(children[0])
    assert memory[first + symbols["RTYPE_OBJ_B1_CHILD_ROOT"]] == 2
    assert word(memory, first + 0x06) == 0x608E

    # Child follows root с шагом 2 и сохраняет готовый descriptor cycle.
    old_x = word(memory, first + 0x02)
    put_word(memory, root + 0x02, 0x0270)
    update(machine, symbols, children[0],
           "RTypeObjectBank4_UpdateBossB1D8Child")
    assert word(memory, first + 0x02) in (old_x - 2, old_x, old_x + 2)
    assert word(memory, first + 0x06) in (0x608E, 0x6094, 0x609A, 0x60A0)

    # Root становится уязвимым после 26 parts и входит в `$0100` exit.
    memory[root + symbols["RTYPE_OBJ_B1_REMAINING"]] = 11
    memory[root + symbols["RTYPE_OBJ_B1_DAMAGE"]] = 0x29
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateBossB1D8Root")
    assert memory[root + symbols["RTYPE_OBJ_STATE"]] == 3
    assert word(memory, root + symbols["RTYPE_OBJ_B1_EXIT_TIMER"]) == 0x0100
    put_word(memory, root + symbols["RTYPE_OBJ_B1_EXIT_TIMER"], 0x0081)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateBossB1D8Root")
    assert machine.get_byte(symbols["RTypeFinalPlayerExitLatch"]) == 0xFF


def check_c0(machine: TSConfFT812Machine, symbols: dict[str, int]) -> None:
    reset(machine, symbols)
    dispatch(machine, symbols, 0xC0A9)
    memory = machine.mem.physical
    root = record_base(2)
    assert memory[root + symbols["RTYPE_OBJ_CTRL_KIND"]] == 3

    # `$0340/$9758` создаёт первую видимую форму `$983B`.
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x033F)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    forms = [index for index in range(3, 96)
             if memory[record_base(index)] == symbols["RTYPE_OBJ_C0_FINAL_SPRITE"]]
    assert len(forms) == 1
    assert word(memory, record_base(forms[0]) + 0x02) == 0x0278
    assert word(memory, record_base(forms[0]) + 0x04) == 0x0090

    # Нестандартный ROM-порядок `$0AC0`, затем `$0A80` сохраняется: сначала
    # terrain child, на следующем pass delayed `$F366`.
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x0ABF)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert any(memory[record_base(index)] == symbols["RTYPE_OBJ_C0_TERRAIN_CHILD"]
               for index in range(3, 96))
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    assert any(memory[record_base(index)] == symbols["RTYPE_OBJ_TIMED_CONTROL_F3C1"]
               for index in range(3, 96))

    # `$0B42/$C30A` переносит один готовый 8x8 map block.
    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x0B41)
    before = bytes(memory[0x08 * PAGE_SIZE:0x09 * PAGE_SIZE])
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController")
    after = bytes(memory[0x08 * PAGE_SIZE:0x09 * PAGE_SIZE])
    assert after != before

    put_word(memory, root + symbols["RTYPE_OBJ_CTRL_COUNTER"], 0x1FFF)
    update(machine, symbols, 2, "RTypeObjectBank4_UpdateStageController",
           max_steps=40_000_000)
    assert memory[root + symbols["RTYPE_OBJ_CTRL_PHASE"]] == 1
    assert word(memory, root + symbols["RTYPE_OBJ_CTRL_EXIT_TIMER"]) == 0x0180


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True)
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    install_texture_coprocessor(machine)
    check_a22(machine, symbols)
    check_b0(machine, symbols)
    check_b1(machine, symbols)
    check_c0(machine, symbols)
    print(
        "$A22E/$B0E1/$B1D8/$C0A9: timelines, 37-part boss, terrain tables, "
        "resources и exits — OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
