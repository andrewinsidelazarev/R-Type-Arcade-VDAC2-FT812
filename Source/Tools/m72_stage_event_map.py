"""Сформировать документ точных event streams всех 8 stages R-Type World."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_MAINCPU_REGION.bin"
OUTPUT = ROOT / "Docs" / "RTYPE_WORLD_ALL_STAGE_EVENTS.md"
ES_FILE_BASE = 0x10000
DISPATCH_TABLE = 0xB92D
# Последнее слово dispatch table — ES:$B98F=$0800 (handler opcode $31).
# Первая четырёхбайтная event-запись Stage 1 начинается с ES:$B993.
STAGE_RANGES = (
    (1, 0xB993, 0xBC13),
    (2, 0xBC17, 0xBCBF),
    (3, 0xBCC3, 0xBCFB),
    (4, 0xBCFF, 0xBF2B),
    (5, 0xBF2F, 0xC067),
    (6, 0xC06B, 0xC253),
    (7, 0xC257, 0xC517),
    # Финальный stage заканчивается `$FFFF,0`, а не `$F01B`.
    (8, 0xC51B, 0xC5DF),
)

HANDLER_NAMES = {
    0x0800: "общий descriptor/object-table initializer",
    0xE430: "stage resource owner",
    0xF0F3: "stage speed/config",
    0xF461: "stage control",
    0xF429: "stop X scroll",
    0x55E9: "terrain-bound enemy",
    0x5A02: "ground walker",
    0x897E: "terrain-aware enemy",
    0x78F8: "enemy entry: priority из ES:$34AE, runtime $7935",
    0x5EED: "enemy entry $4030/$5F3C с direction из command",
    0x5DC8: "patrol formation parent",
    0x596D: "red scripted flyer",
    0x86A6: "animated enemy",
    0x60BA: "player-tracking enemy",
    0x5526: "collision/terrain table control",
    0x6A9B: "foreground terrain parent",
    0x74B4: "large terrain enemy",
    0x80E3: "player-targeting enemy",
    0x6E9B: "fixed large object $A000/$6EC4 at ($0110,$0108)",
    0x98FD: "Dobkeratops multipart parent",
    0x5596: "boss arena collision-table setup",
    0xF130: "stop all scroll velocities",
    0xF01B: "next-stage init",
    0x6F89: "post-boss/stage object",
    0x696E: "enemy entry $8010/$69B4, position/animation decoders",
    0x875D: "fixed object $8000/$8798 at ($02C0,$0120)",
    0x8C12: "timed random stage-control object $DFFF/$8C2E",
    0x8469: "enemy entry $8020/$8490, initial X velocity -$0200",
    0x5CEA: "enemy entry $8020/$5D2D, difficulty parameters",
    0x8F5E: "enemy entry $8230/$8F86, table ES:$3F76",
    0xC46E: "stage-control object $FF00/$C4BC",
    0xA22E: "boss/stage controller $3800/$A290; stops all scroll",
    0x915B: "multipart object root $1800/$91CC",
    0x7182: "enemy entry $8020/$71C7, fire table + ES:$31FE",
    0x7294: "enemy entry $4020/$72D2, command direction",
    0xFB9C: "stage resource/control event",
    0xF366: "stage transition control",
    0xB0E1: "boss/stage controller $1000/$B111; stops all scroll",
    0xA71D: "randomized stage object $1000/$A762",
    0x7D68: "enemy entry $A000/$7DBB, two command variants",
    0xB1D8: "boss/stage controller $7D00/$B1FA",
    0xB7FB: "stage object $A200/$B805",
    0x9660: "enemy entry $2000/$9674 with $FA90/$FAA5 setup",
    0xC0A9: "final-stage controller $C800/$C0CA",
    0x8561: "enemy entry $8020/$85B0, difficulty table",
    0xFB10: "six-object stage controller from ES:$945C",
    0xEEAB: "final-stage object $0100/$EEB5",
    0xEE0B: "final-stage scroll/state reset object $0200/$EE3C",
}


def word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def build_markdown(rom: bytes) -> tuple[str, int]:
    lines = [
        "# R-Type World — event streams всех 8 stages",
        "",
        "Сгенерировано `Source/Tools/m72_stage_event_map.py` напрямую из World ROM.",
        "Запись имеет вид `threshold word, command word`. Процедура `$1BA7`",
        "сравнивает threshold с `RAM:$2F4B`, затем вычисляет offset обработчика",
        "как `((CH >> 1) & $7E)` в таблице `ES:$B92D`.",
        "",
        "MAME frames в таблице отсутствуют намеренно: trigger — progression ROM,",
        "а не номер кадра.",
        "",
        "| ES | File | HEX | Threshold | Command | Opcode | Handler | Смысл |",
        "|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    event_count = 0
    for stage, first, last in STAGE_RANGES:
        lines.extend(["", f"## Stage {stage}: `ES:${first:04X}..${last:04X}`", ""])
        for address in range(first, last + 1, 4):
            file_offset = ES_FILE_BASE + address
            raw = rom[file_offset:file_offset + 4]
            threshold = word(raw, 0)
            command = word(raw, 2)
            offset = ((command >> 9) & 0x7E)
            opcode = offset // 2
            handler = word(rom, ES_FILE_BASE + DISPATCH_TABLE + offset)
            meaning = HANDLER_NAMES[handler]
            lines.append(
                f"| `${address:04X}` | `${file_offset:05X}` | `{raw.hex(' ')}` | "
                f"`${threshold:04X}` | `${command:04X}` | `${opcode:02X}` | "
                f"`${handler:04X}` | {meaning} |"
            )
            event_count += 1

    return "\n".join(lines) + "\n", event_count


def main() -> int:
    rom = ROM_PATH.read_bytes()
    if len(rom) != 0x100000:
        raise ValueError("неверный размер RTYPE_MAINCPU_REGION.bin")
    markdown, event_count = build_markdown(rom)
    OUTPUT.write_text(markdown, encoding="utf-8")
    print(f"All-stage events: {event_count}")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
