#!/usr/bin/env python3
"""Собрать нативные `$F578`-границы объектов из неизменяемого World ROM.

Таблица предназначена для code-bank #0F. Z80 не читает восемь слов из ROM
для каждого кандидата и каждого снаряда: четыре signed endpoint и постоянные
свойства объекта заранее извлекаются на ПК. Динамические hitbox-ы помечены
битом ``DESCRIPTOR`` и вычисляются из текущего sprite descriptor уже в игре.
"""

from __future__ import annotations

from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUT = ROOT / "Source" / "ASM" / "generated_collision_tables.inc"
ES_FILE_BASE = 0x10000

WEAPON = 0x01
HOSTILE = 0x02
DESCRIPTOR = 0x04
FORCE_ONLY = 0x08
CADENCED = 0x10

# type: (таблица границ или None, flags, индекс packed-BCD `$86E4`).
# Состав списка повторяет реальные классы готового Python-runtime, а не имя
# event handler. Невидимые controllers и владельцы ресурсов сюда не входят.
TYPES: dict[int, tuple[int | None, int, int]] = {
    1: (0x2912, WEAPON | HOSTILE, 2),
    7: (0x2A38, WEAPON | HOSTILE, 2),
    8: (0x2982, WEAPON | HOSTILE, 2),
    9: (0x84C6, HOSTILE | FORCE_ONLY, 0),
    10: (0x28DA, WEAPON | HOSTILE, 2),
    11: (0x3956, WEAPON | HOSTILE | CADENCED, 5),
    13: (0x395E, HOSTILE, 0),
    14: (0x3426, WEAPON | HOSTILE | CADENCED, 5),
    15: (0x34A6, HOSTILE, 0),
    16: (0x3C56, WEAPON | HOSTILE, 3),
    17: (0x3AF6, WEAPON | HOSTILE, 1),
    19: (0x2FD4, WEAPON | HOSTILE | CADENCED, 0),
    20: (0x2F06, HOSTILE, 0),
    21: (0x2C40, WEAPON | HOSTILE | CADENCED, 8),
    22: (0x2C84, HOSTILE, 0),
    23: (0x2D84, HOSTILE, 0),
    25: (None, HOSTILE | DESCRIPTOR, 0),
    26: (0x4526, WEAPON | HOSTILE | CADENCED, 0),
    27: (0x46C4, WEAPON | HOSTILE, 0),
    28: (0x4CBE, WEAPON | HOSTILE | CADENCED, 0),
    29: (0x44B2, HOSTILE, 0),
    30: (0x44B2, HOSTILE, 0),
    31: (0x58E6, HOSTILE, 0),
    35: (0x31EE, WEAPON | HOSTILE | CADENCED, 0),
    37: (0x3C12, WEAPON | HOSTILE, 0),
    38: (0x3846, WEAPON | HOSTILE | CADENCED, 0),
    39: (0x3F6E, WEAPON | HOSTILE | CADENCED, 0),
    41: (0x427C, HOSTILE, 0),
    42: (0x4196, WEAPON | HOSTILE, 0),
    44: (0x2E36, WEAPON | HOSTILE | CADENCED, 0),
    45: (0x407E, WEAPON | HOSTILE, 0),
    46: (0x39AC, WEAPON | HOSTILE, 0),
    47: (0x84FE, WEAPON | HOSTILE, 0),
    48: (0x3A2E, WEAPON | HOSTILE | CADENCED, 0),
    49: (0x29CA, WEAPON | HOSTILE, 0),
    50: (None, WEAPON | HOSTILE | DESCRIPTOR | CADENCED, 0),
    51: (0x3276, WEAPON | HOSTILE, 0),
    52: (0x333E, WEAPON | HOSTILE | CADENCED, 0),
    53: (0x3296, WEAPON | HOSTILE, 0),
    55: (0x3072, WEAPON | HOSTILE | CADENCED, 0),
    57: (0x37CE, WEAPON | HOSTILE | CADENCED, 0),
    59: (0x436C, WEAPON | HOSTILE, 0),
    61: (0x5A3E, WEAPON | HOSTILE | CADENCED, 0),
    63: (0x58E6, HOSTILE, 0),
    65: (0x6116, WEAPON | HOSTILE | CADENCED, 0),
    67: (0x6244, WEAPON | HOSTILE | CADENCED, 0),
    69: (0x630A, WEAPON | HOSTILE | CADENCED, 0),
    70: (0x63BE, WEAPON | HOSTILE | CADENCED, 0),
    71: (0x6244, HOSTILE, 0),
    75: (0x54EA, WEAPON | HOSTILE | CADENCED, 0),
    76: (0x60A6, WEAPON | HOSTILE | CADENCED, 0),
    77: (0x60AE, WEAPON | HOSTILE | CADENCED, 0),
    78: (0x64B4, WEAPON | HOSTILE | CADENCED, 0),
}


def main() -> None:
    data = ROM.read_bytes()
    rows: list[str] = []
    rows.append("; Автоматически создано Source/Tools/m72_collision_tables.py.\n")
    rows.append("; Формат: left,right,lower,upper,flags,score-index; 12 bytes/type.\n")
    rows.append("RTypeCollisionTypeTable:\n")
    for obj_type in range(80):
        address, flags, score = TYPES.get(obj_type, (None, 0, 0))
        if address is None:
            endpoints = (0, 0, 0, 0)
        else:
            offset = ES_FILE_BASE + address
            endpoints = struct.unpack_from("<hhhh", data, offset)
        words = ", ".join(f"#{value & 0xFFFF:04X}" for value in endpoints)
        rows.append(
            f"                DEFW {words}\n"
            f"                DEFB #{flags:02X}, #{score:02X}, 0, 0"
            f" ; type {obj_type:02d}"
            + (f", ES:${address:04X}\n" if address is not None else "\n")
        )
    rows.append("\n; Шестнадцать четырёхбайтных packed-BCD приращений `$86E4`.\n")
    rows.append("RTypeCollisionScoreIncrements:\n")
    for index in range(16):
        offset = ES_FILE_BASE + 0x86E4 + index * 4
        values = data[offset:offset + 4]
        rows.append(
            "                DEFB "
            + ", ".join(f"#{value:02X}" for value in values)
            + f" ; index {index}\n"
        )
    OUT.write_text("".join(rows), encoding="utf-8", newline="\n")
    print(f"collision table: {len(TYPES)} active types, {80 * 12} bytes -> {OUT}")


if __name__ == "__main__":
    main()
