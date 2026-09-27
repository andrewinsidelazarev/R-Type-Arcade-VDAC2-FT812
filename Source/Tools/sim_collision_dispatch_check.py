#!/usr/bin/env python3
"""Исполнить собранный bank #E5 и проверить fixed collision без Unreal.

Проверяются четыре независимые границы: ordinary shot прекращает scan после
первого target, Wave наносит полный damage и вычитает прежний HP, hostile
projectile запускает штатную смерть R-9, а packed-BCD score пересекает
поделенные пополам пороги 25k/75k без превышения лимита восьми жизней.
Объект помещается прямо в физическую page #09, поэтому тест не подменяет
Z80 collision реализацией на Python.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE9 = 0x09 * 0x4000
REC = 0x40
INDEX = 2
SCHED_NEXT = PAGE9 + 0x1A00
SCHED_PREV = PAGE9 + 0x1A60
SCHED_HEAD = PAGE9 + 0x1AC0
SCHED_TAIL = PAGE9 + 0x1AC1

SHOT_TABLE = 0x4220
SHOT_STATE = 0
SHOT_X = 1
SHOT_Y = 3
SHOT_FLIGHT = 2
SHOT_SPENT = 3

WAVE_ACTIVE = 0x423C
WAVE_DELAY = 0x423D
WAVE_X = 0x423F
WAVE_Y = 0x4241
WAVE_POWER = 0x4212

PLAYER_VISIBLE = 0x4251
LIFE_STATE = 0x424D
INVULNERABILITY = 0x4250
LIVES = 0x424C
SCORE = 0x4254
BONUS_INDEX = 0x4258


def put_word(memory: bytearray, address: int, value: int) -> None:
    memory[address] = value & 0xFF
    memory[address + 1] = (value >> 8) & 0xFF


def get_word(memory: bytearray, address: int) -> int:
    return memory[address] | (memory[address + 1] << 8)


def install_single_object(
        machine: TSConfFT812Machine, obj_type: int, x: int, y: int,
        *, palette: int = 0) -> int:
    """Создать один элемент точного live scheduler `(priority,-serial)`."""
    memory = machine.mem.physical
    base = PAGE9 + INDEX * REC
    memory[base:base + REC] = bytes(REC)
    memory[base] = obj_type
    memory[base + 8] = palette
    put_word(memory, base + 2, x)
    put_word(memory, base + 4, y)
    memory[SCHED_NEXT + INDEX] = 0xFF
    memory[SCHED_PREV + INDEX] = 0xFF
    memory[SCHED_HEAD] = INDEX
    memory[SCHED_TAIL] = INDEX
    return base


def clear_fixed_weapons(machine: TSConfFT812Machine) -> None:
    for address in range(SHOT_TABLE, SHOT_TABLE + 3 * 9):
        machine.set_byte(address, 0)
    machine.set_byte(WAVE_ACTIVE, 0)
    machine.set_byte(WAVE_POWER, 0)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    machine.set_byte(PLAYER_VISIBLE, 0)

    # Enemy `$6F89`: collision ES:$31EE=(-18,+18,-18,+18), HP word +$34.
    target_x, target_y = 0x0200, 0x0100
    base = install_single_object(machine, 35, target_x, target_y)
    put_word(machine.mem.physical, base + 0x34, 10)
    machine.set_byte(SHOT_TABLE + SHOT_STATE, SHOT_FLIGHT)
    machine.set_word(SHOT_TABLE + SHOT_X, target_x)
    machine.set_word(SHOT_TABLE + SHOT_Y, target_y)
    machine.call(symbols["RTypeCollision_Update"], max_steps=2_000_000)
    assert machine.get_byte(SHOT_TABLE + SHOT_STATE) == SHOT_SPENT, (
        machine.get_byte(SHOT_TABLE + SHOT_STATE),
        get_word(machine.mem.physical, base + 0x34),
        machine.mem.physical[SCHED_HEAD],
        machine.mem.physical[0x6B * 0x4000 +
                             symbols["RTypeCollision_TargetType"] - 0x8000],
        machine.mem.physical[0x6B * 0x4000 +
                             symbols["RTypeCollision_ScanIndex"] - 0x8000],
        tuple(get_word(
            machine.mem.physical,
            0x6B * 0x4000 + symbols[name] - 0x8000) for name in (
            "RTypeCollision_SourceLeft", "RTypeCollision_SourceRight",
            "RTypeCollision_TargetLeft", "RTypeCollision_TargetRight",
        )),
    )
    assert get_word(machine.mem.physical, base + 0x34) == 9
    assert machine.mem.physical[base + 0x31] == 0x10

    # Тот же target и Wave power=4: damage=4, но цена — прежние 10 HP,
    # поэтому borrow немедленно завершает Wave.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    clear_fixed_weapons(machine)
    base = install_single_object(machine, 35, target_x, target_y)
    put_word(machine.mem.physical, base + 0x34, 10)
    machine.set_byte(WAVE_ACTIVE, 1)
    machine.set_byte(WAVE_DELAY, 0)
    machine.set_byte(WAVE_POWER, 4)
    machine.set_word(WAVE_X, target_x)
    machine.set_word(WAVE_Y, target_y)
    machine.call(symbols["RTypeCollision_Update"], max_steps=2_000_000)
    assert get_word(machine.mem.physical, base + 0x34) == 6
    assert machine.get_byte(WAVE_ACTIVE) == 0
    assert machine.get_byte(WAVE_POWER) == 0

    # Common `$E601` projectile не принимает ordinary/Wave, но остаётся
    # hostile для R-9 и запускает `$22CD` при точном native overlap.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    clear_fixed_weapons(machine)
    player_x = machine.get_word(symbols["RTypePlayerNativeX"])
    player_y = machine.get_word(symbols["RTypePlayerNativeY"])
    install_single_object(machine, 9, player_x, player_y, palette=0)
    machine.set_byte(PLAYER_VISIBLE, 1)
    machine.set_byte(LIFE_STATE, 0)
    machine.set_byte(INVULNERABILITY, 0)
    machine.call(symbols["RTypeCollision_Update"], max_steps=2_000_000)
    assert machine.get_byte(LIFE_STATE) == 1

    # `$3AF6` (type 17) — одноударный target с ROM score-index 1 = 100.
    # 24 900 + 100 пересекает первый пользовательский порог 25 000:
    # жизнь возрастает 7->8, а индекс следующего порога становится 1.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    clear_fixed_weapons(machine)
    install_single_object(machine, 17, target_x, target_y)
    for offset, value in enumerate((0x00, 0x49, 0x02, 0x00)):
        machine.set_byte(SCORE + offset, value)
    machine.set_byte(BONUS_INDEX, 0)
    machine.set_byte(LIVES, 7)
    machine.set_byte(SHOT_TABLE + SHOT_STATE, SHOT_FLIGHT)
    machine.set_word(SHOT_TABLE + SHOT_X, target_x)
    machine.set_word(SHOT_TABLE + SHOT_Y, target_y)
    machine.call(symbols["RTypeCollision_Update"], max_steps=2_000_000)
    assert tuple(machine.get_byte(SCORE + i) for i in range(4)) == (
        0x00, 0x50, 0x02, 0x00)
    assert machine.get_byte(BONUS_INDEX) == 1
    assert machine.get_byte(LIVES) == 8

    # На 74 900 следующий kill достигает 75 000. Порог обязан считаться
    # пройденным, но cap запрещает скрытый переход 8->9.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    clear_fixed_weapons(machine)
    install_single_object(machine, 17, target_x, target_y)
    for offset, value in enumerate((0x00, 0x49, 0x07, 0x00)):
        machine.set_byte(SCORE + offset, value)
    machine.set_byte(BONUS_INDEX, 1)
    machine.set_byte(LIVES, 8)
    machine.set_byte(SHOT_TABLE + SHOT_STATE, SHOT_FLIGHT)
    machine.set_word(SHOT_TABLE + SHOT_X, target_x)
    machine.set_word(SHOT_TABLE + SHOT_Y, target_y)
    machine.call(symbols["RTypeCollision_Update"], max_steps=2_000_000)
    assert tuple(machine.get_byte(SCORE + i) for i in range(4)) == (
        0x00, 0x50, 0x07, 0x00)
    assert machine.get_byte(BONUS_INDEX) == 2
    assert machine.get_byte(LIVES) == 8

    # `$5811/$5947`: carrier type 10 не исчезает как generic death. Он остаётся
    # pickup type 0, создаёт отдельный explosion slot, затем при контакте пишет
    # pending `$0037`; только следующий fixed-player pass повышает Force level.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    clear_fixed_weapons(machine)
    base = install_single_object(machine, 10, target_x, target_y)
    machine.mem.physical[base + 0x20] = 0      # pickup_index 0
    machine.mem.physical[PAGE9 + 0x1970] = 0x0F
    machine.mem.physical[PAGE9 + 0x1980] = 1
    machine.mem.physical[PAGE9 + 0x1960] = 1   # allocator пропускает live slot 2
    machine.mem.physical[PAGE9 + 0x1962] = 93
    for offset in range(4):
        machine.set_byte(SCORE + offset, 0)
    machine.set_byte(SHOT_TABLE + SHOT_STATE, SHOT_FLIGHT)
    machine.set_word(SHOT_TABLE + SHOT_X, target_x)
    machine.set_word(SHOT_TABLE + SHOT_Y, target_y)
    machine.call(symbols["RTypeCollision_Update"], max_steps=5_000_000)
    assert machine.mem.physical[base] == 10
    assert machine.mem.physical[base + 0x0E] == 5
    assert machine.mem.physical[base + 0x21] == 0
    assert tuple(machine.get_byte(SCORE + i) for i in range(4)) == (
        0x00, 0x02, 0x00, 0x00)
    assert machine.mem.physical[SCHED_NEXT + INDEX] == 3

    machine.set_word(symbols["RTypePlayerNativeX"], target_x)
    machine.set_word(symbols["RTypePlayerNativeY"], target_y)
    machine.set_word(symbols["RTypeWorldFgDelta"], 0)
    machine.set_word(symbols["FrameCounter"], 1)
    machine.set_byte(symbols["RTypeObjects_CurrentIndex"], INDEX)
    # LoadScratch получает индекс в A; одной записи CurrentIndex недостаточно.
    # Это соответствует scheduler, который перед каждым handler сохраняет
    # индекс и тем же A копирует физическую запись page #09 в общий scratch.
    machine.call(symbols["RTypeObjects_LoadScratch"], a=INDEX,
                 max_steps=500_000)
    assert machine.get_byte(symbols["RTYPE_OBJECT_SCRATCH"] + 0x0E) == 5, (
        "pickup scratch was not restored",
        machine.get_byte(symbols["RTYPE_OBJECT_SCRATCH"]),
        machine.get_byte(symbols["RTYPE_OBJECT_SCRATCH"] + 0x0E),
        machine.get_word(symbols["RTYPE_OBJECT_SCRATCH"] + 2),
        machine.get_word(symbols["RTYPE_OBJECT_SCRATCH"] + 4),
    )
    machine.call(symbols["RTypeObjectBank1_UpdateTerrainBound"],
                 max_steps=5_000_000)
    assert machine.get_byte(symbols["ArcadeWeaponPickupPending"]) == 1, (
        machine.get_byte(symbols["ArcadeWeaponPickupPending"]),
        machine.get_byte(symbols["RTYPE_OBJECT_SCRATCH"]),
        machine.get_byte(symbols["RTYPE_OBJECT_SCRATCH"] + 0x0E),
        machine.get_word(symbols["RTYPE_OBJECT_SCRATCH"] + 2),
        machine.get_word(symbols["RTYPE_OBJECT_SCRATCH"] + 4),
        tuple(machine.get_byte(SCORE + i) for i in range(4)),
        machine.get_byte(symbols["RTYPE_LAST_SOUND_COMMAND"]),
    )
    assert machine.get_byte(symbols["ArcadeWeaponType"]) == 0
    assert tuple(machine.get_byte(SCORE + i) for i in range(4)) == (
        0x00, 0x06, 0x00, 0x00)
    machine.set_byte(symbols["InputState"], 0)
    machine.call(symbols["ArcadeForce_Update"], max_steps=5_000_000)
    assert machine.get_byte(symbols["ArcadeWeaponPickupPending"]) == 0
    assert machine.get_byte(symbols["ArcadeForceRequestedLevel"]) == 1
    assert machine.get_byte(symbols["ArcadeForceLevel"]) == 1

    print(
        "Collision bank #E5: shot, Wave, hostile, pickup, BCD score и cap=8 — OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
