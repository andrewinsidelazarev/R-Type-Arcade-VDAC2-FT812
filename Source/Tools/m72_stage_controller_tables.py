"""Собрать неизменяемые таблицы поздних контроллеров напрямую из World ROM.

Runtime Z80 не должен разбирать крупные V30-структуры во время VBlank. Скрипт
один раз переносит доказанные ES-таблицы `$A22E/$B0E1/$B1D8/$C0A9` в bank #0D.
Получившийся include является обычным исходником сборки и не зависит от MAME.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUTPUT = ROOT / "Source" / "ASM" / "generated_stage_controller_tables.inc"
ES_BASE = 0x10000


def word(rom: bytes, address: int) -> int:
    offset = ES_BASE + (address & 0xFFFF)
    return int.from_bytes(rom[offset:offset + 2], "little")


def emit_words(lines: list[str], label: str, values: list[int],
               words_per_line: int = 8) -> None:
    lines.append(f"{label}:")
    for start in range(0, len(values), words_per_line):
        row = ", ".join(f"#{value:04X}" for value in
                        values[start:start + words_per_line])
        lines.append(f"                DEFW {row}")
    lines.append("")


def main() -> int:
    rom = ROM_PATH.read_bytes()
    if len(rom) != 0x100000:
        raise ValueError("неверный размер RTYPE_MAINCPU_REGION.bin")

    lines = [
        "; =============================================================================",
        "; Сгенерировано m72_stage_controller_tables.py из неизменяемого World ROM.",
        "; Не редактировать вручную: это готовые таблицы для page #0D, чтобы Z80",
        "; не разбирал исходные V30-структуры и не копировал их во время VBlank.",
        "; =============================================================================",
        "",
    ]

    # `$A5C5`: threshold и один из четырёх terrain-writer records.
    a22_terrain: list[int] = []
    address = 0x4D1C
    while True:
        threshold = word(rom, address)
        command = word(rom, address + 2)
        a22_terrain.extend((threshold, command))
        address += 4
        if threshold == 0xFFFF:
            break
    emit_words(lines, "RTypeBank4_A22TerrainTimeline", a22_terrain, 4)

    # `$A5A4`: command/reload, последний `$FFFF` запрещает новые multipart.
    a22_spawn: list[int] = []
    for address in range(0x4D62, 0x4D82, 4):
        a22_spawn.extend((word(rom, address), word(rom, address + 2)))
    emit_words(lines, "RTypeBank4_A22MultipartTimeline", a22_spawn, 4)

    # Четыре writer-а содержат две готовые фазы. Каждая cell — tile-code word;
    # target добавляет к ней неизменяемый attribute `$0088`.
    terrain_records: list[tuple[int, int, int, int, int, int]] = []
    for index in range(4):
        record = 0x4D82 + index * 10
        first = word(rom, record)
        second = word(rom, record + 2)
        shape = word(rom, record + 4)
        x = word(rom, record + 6)
        y = word(rom, record + 8)
        width = (shape >> 8) & 0xFF
        height = shape & 0xFF
        terrain_records.append((first, second, width, height, x, y))

    lines.append("RTypeBank4_A22TerrainRecords:")
    for index, (_first, _second, width, height, x, y) in enumerate(terrain_records):
        lines.append(
            f"                DEFW RTypeBank4_A22Pattern{index}A, "
            f"RTypeBank4_A22Pattern{index}B, #{width:02X}{height:02X}, "
            f"#{x:04X}, #{y:04X}")
    lines.append("")
    for index, (first, second, width, height, _x, _y) in enumerate(terrain_records):
        count = width * height
        emit_words(lines, f"RTypeBank4_A22Pattern{index}A",
                   [word(rom, first + offset * 2) for offset in range(count)])
        emit_words(lines, f"RTypeBank4_A22Pattern{index}B",
                   [word(rom, second + offset * 2) for offset in range(count)])

    # `$B111`: 16 порогов и команд. Terminal `$869F` хранится отдельно.
    b0_spawn: list[int] = []
    for address in range(0xC5E3, 0xC623, 4):
        b0_spawn.extend((word(rom, address), word(rom, address + 2)))
    b0_spawn.extend((0xFFFF, 0))
    emit_words(lines, "RTypeBank4_B0SpawnTimeline", b0_spawn, 4)

    # `$B1FA`: difficulty timers, 37 offsets children и 32 target points.
    emit_words(lines, "RTypeBank4_B1AnimationReload",
               [word(rom, 0x5F5C + index * 2) for index in range(4)], 4)
    b1_children: list[int] = []
    for address in range(0x5F6C, 0x6000, 4):
        b1_children.extend((word(rom, address), word(rom, address + 2)))
    emit_words(lines, "RTypeBank4_B1ChildOffsets", b1_children, 4)
    b1_targets: list[int] = []
    for address in range(0x6002, 0x6082, 4):
        b1_targets.extend((word(rom, address), word(rom, address + 2)))
    emit_words(lines, "RTypeBank4_B1Targets", b1_targets, 4)

    # `$C0CA`: callback address заменён компактным target opcode. Порядок ROM
    # (включая `$0AC0` перед `$0A80`) сохраняется буквально.
    callback_opcode = {
        0x9758: 1, 0x978D: 2, 0x97C7: 3, 0x9801: 4,
        0xC37F: 5, 0xF366: 6, 0xC30A: 7, 0xC2F6: 8,
        0xC2F0: 9, 0xC37A: 10, 0xC31B: 11, 0xC326: 12,
        0xC32C: 13, 0xC332: 14, 0xC315: 15, 0xC305: 16,
        0xFFF2: 0xFF,
    }
    c0_timeline: list[int] = []
    for address in range(0x6416, 0x64B6, 4):
        threshold = word(rom, address)
        callback = word(rom, address + 2)
        c0_timeline.extend((threshold, callback_opcode[callback]))
    emit_words(lines, "RTypeBank4_C0Timeline", c0_timeline, 4)

    # `$C30A…$C332`: пять полностью готовых 8x8 maps, четыре bytes/cell.
    for index, address in enumerate((0x64BC, 0x65BC, 0x66BC, 0x67BC, 0x68BC)):
        values = [word(rom, address + offset * 2) for offset in range(128)]
        emit_words(lines, f"RTypeBank4_C0TerrainPattern{index}", values)

    text = "\n".join(lines).rstrip() + "\n"
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(OUTPUT)
    print(f"bytes={len(text.encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
