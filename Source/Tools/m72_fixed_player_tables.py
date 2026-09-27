#!/usr/bin/env python3
"""Предсохранить таблицы Force и Bits из неизменяемого World ROM.

Целевой Z80 не должен каждый VBlank переключать slot3 ради коротких таблиц
fixed-player.  Генератор разворачивает косвенные descriptor-таблицы Force,
смещения и скорости Bits в линейные записи code-bank #E6.
"""

from __future__ import annotations

from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUT = ROOT / "Source" / "ASM" / "generated_fixed_player_tables.inc"
ES_FILE_BASE = 0x10000


def main() -> None:
    data = ROM.read_bytes()

    def byte(address: int) -> int:
        return data[ES_FILE_BASE + address]

    def word(address: int) -> int:
        return struct.unpack_from("<H", data, ES_FILE_BASE + address)[0]

    rows: list[str] = [
        "; Автоматически создано Source/Tools/m72_fixed_player_tables.py.\n",
        "; Все значения буквально извлечены из World ROM; runtime их не строит.\n\n",
    ]

    rows.append("RTypeForceHitboxTable:\n")
    for pointer in (0x15C6, 0x15C6, 0x15CE, 0x15D6):
        values = [word(pointer + offset) for offset in range(0, 8, 2)]
        rows.append("                DEFW " + ", ".join(
            f"#{value:04X}" for value in values) + f" ; ES:${pointer:04X}\n")

    def words(label: str, address: int, count: int) -> None:
        rows.append(f"\n{label}:\n")
        for start in range(0, count, 8):
            values = [word(address + index * 2)
                      for index in range(start, min(start + 8, count))]
            rows.append("                DEFW " + ", ".join(
                f"#{value:04X}" for value in values) + "\n")

    words("RTypeForceLevel1AttachedDescriptors", 0x1440, 6)
    words("RTypeForceLevel1ReturnDescriptors", 0x144C, 6)
    words("RTypeForceLevel2UpBehindDescriptors", 0x1458, 6)
    words("RTypeForceLevel2DownBehindDescriptors", 0x1464, 6)
    words("RTypeForceLevel2UpFrontDescriptors", 0x1470, 6)
    words("RTypeForceLevel2DownFrontDescriptors", 0x147C, 6)
    words("RTypeForceLevel3DetachedFrontDescriptors", 0x149A, 4)
    words("RTypeForceLevel3DetachedBehindDescriptors", 0x14A2, 4)

    rows.append("\n; direction 0…15, затем animation 0…3.\n")
    rows.append("RTypeForceLevel3DirectionDescriptors:\n")
    for direction in range(16):
        group = byte(0x15AE + direction)
        table = word(0x1488 + group * 2)
        values = [word(table + animation * 2) for animation in range(4)]
        rows.append("                DEFW " + ", ".join(
            f"#{value:04X}" for value in values) +
            f" ; direction #{direction:02X}, group {group}\n")

    rows.append("\nRTypeForceAttachedAnimationDelta:\n")
    rows.append("                DEFB " + ", ".join(
        f"#{byte(0x159E + direction):02X}" for direction in range(16)) + "\n")

    rows.append("\n; coarse strength 0…3, direction 0…15: signed X,Y.\n")
    rows.append("RTypeBitsOffsetTable:\n")
    for coarse in range(4):
        for direction in range(16):
            address = 0x15DE + coarse * 0x40 + direction * 4
            rows.append(
                f"                DEFW #{word(address):04X}, "
                f"#{word(address + 2):04X}"
                f" ; coarse {coarse}, direction #{direction:02X}\n")

    words("RTypeBit0SpeedTable", 0x16DE, 32)
    words("RTypeBit1SpeedTable", 0x171E, 32)

    OUT.write_text("".join(rows), encoding="utf-8", newline="\n")
    print(f"fixed-player tables: {OUT.stat().st_size} bytes source -> {OUT}")


if __name__ == "__main__":
    main()
