#!/usr/bin/env python3
"""Точный покадровый поток вылета R-9 из защёлкнутого Sprite RAM M72."""
from __future__ import annotations

import hashlib
import csv
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "Build" / "Arcade" / "MAME" / "launch_boundary_probe"
OUTPUT = ROOT / "Assets" / "Converted" / "Arcade" / "Player"
SNAPSHOT_FRAME = 700
BASE_FRAME = 852
END_FRAME = 1078
PLAYER_OFFSET = 0x0C0
EXHAUST_OFFSET = 0x0D0
EVENT = struct.Struct("<hhBBhh")
# Готовая для Z80 запись не требует ни деления координат, ни обратного
# вычисления native anchor во время VBlank. Поля:
#   logical player X/Y Q0, body index, effect kind, logical effect X/Y,
#   native player anchor X/Y для enemy handlers и collision.
LOGICAL_EVENT = struct.Struct("<hhBBhhHH")
EXHAUST_KIND = {0x001F: 0, 0x0A23: 1, 0x0AA2: 2, 0x0AA4: 3, 0x0AA6: 4}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def read_writes(path: Path) -> dict[int, list[tuple[int, int, int]]]:
    """Прочитать word write-tap MAME; генератор не зависит от title pipeline."""
    result: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    with path.open(newline="", encoding="ascii") as source:
        for row in csv.DictReader(source):
            result[int(row["frame"])].append(
                (int(row["address"], 16), int(row["data"], 16),
                 int(row["mask"], 16)))
    return result


def apply_writes(memory: bytearray,
                 writes: list[tuple[int, int, int]], base: int) -> None:
    """Применить byte-mask так же, как 16-битная шина Sprite RAM M72."""
    for address, data, mask in writes:
        offset = address - base
        if not 0 <= offset + 1 < len(memory):
            raise ValueError(
                f"write {address:05X} outside {base:05X}+{len(memory):X}")
        old = memory[offset] | (memory[offset + 1] << 8)
        value = (old & ~mask) | (data & mask)
        memory[offset] = value & 0xFF
        memory[offset + 1] = (value >> 8) & 0xFF


def decode_object(memory: bytes | bytearray, offset: int) -> tuple[int, int, int]:
    raw_y, code, attr, raw_x = struct.unpack_from("<HHHH", memory, offset)
    height = 1 << ((attr >> 12) & 3)
    # Горизонтальный visible-area M72 начинается с raw X=320.
    x = (raw_x & 0x3FF) - 320
    y = 384 - (raw_y & 0x1FF) - 16 * height
    return code, x, y


def verify_snapshot_replay(sprite: bytearray,
                           writes: dict[int, list[tuple[int, int, int]]]) -> None:
    replay = bytearray(sprite)
    for frame in range(SNAPSHOT_FRAME, 1000):
        apply_writes(replay, writes.get(frame, []), 0xC0000)
    expected = (CAPTURE / "frame_001000_spriteram.bin").read_bytes()
    if replay != expected:
        raise ValueError(
            "Sprite RAM replay mismatch at frame 1000: "
            f"{sha256(replay)} != {sha256(expected)}"
        )


def main() -> int:
    player_manifest = json.loads(
        (OUTPUT / "r9_pitch.json").read_text(encoding="utf-8"))
    launch_crops = {
        int(record["code"]): (int(record["crop_left"]),
                              int(record["crop_top"]))
        for record in player_manifest["records"]
        if record["kind"] == "launch"
    }
    expected_launch_codes = set(EXHAUST_KIND) - {0x001F}
    if set(launch_crops) != expected_launch_codes:
        raise ValueError(
            "r9_pitch.json не содержит четыре точных launch-ассета")

    writes = read_writes(CAPTURE / "spriteram_writes.csv")
    sprite = bytearray(
        (CAPTURE / f"frame_{SNAPSHOT_FRAME:06d}_spriteram.bin").read_bytes()
    )
    verify_snapshot_replay(sprite, writes)
    for frame in range(SNAPSHOT_FRAME, BASE_FRAME):
        apply_writes(sprite, writes.get(frame, []), 0xC0000)
    packed = bytearray()
    logical_packed = bytearray()
    rows: list[dict[str, int]] = []
    previous: tuple[int, int, int, int, int, int] | None = None

    for frame in range(BASE_FRAME, END_FRAME):
        body_code, player_x, player_y = decode_object(sprite, PLAYER_OFFSET)
        exhaust_code, exhaust_x, exhaust_y = decode_object(sprite, EXHAUST_OFFSET)
        if not 0x20 <= body_code <= 0x24:
            raise ValueError(f"frame {frame}: unexpected R-9 code ${body_code:04X}")
        if exhaust_code not in EXHAUST_KIND:
            raise ValueError(
                f"frame {frame}: unexpected exhaust code ${exhaust_code:04X}"
            )
        event = (
            player_x, player_y, body_code - 0x20,
            EXHAUST_KIND[exhaust_code], exhaust_x, exhaust_y,
        )
        packed += EVENT.pack(*event)

        # Эти выражения буквально повторяют Game._update_intro/render из
        # канонической Python-версии. Деления с округлением выполняются здесь,
        # на ПК; Z80 получает уже готовые логические и native координаты.
        logical_player_x = round(player_x * 5 / 3)
        logical_player_y = round(player_y * 15 / 8) + 1
        native_player_x = round(logical_player_x * 3 / 5) + 0x0150
        native_player_y = 0x0176 - round(logical_player_y * 8 / 15)
        effect_kind = EXHAUST_KIND[exhaust_code]
        if effect_kind:
            crop_left, crop_top = launch_crops[exhaust_code]
            logical_effect_x = round(exhaust_x * 5 / 3) + crop_left
            logical_effect_y = round(exhaust_y * 15 / 8) + crop_top
        else:
            logical_effect_x = 0
            logical_effect_y = 0
        logical_packed += LOGICAL_EVENT.pack(
            logical_player_x, logical_player_y,
            body_code - 0x20, effect_kind,
            logical_effect_x, logical_effect_y,
            native_player_x, native_player_y,
        )
        if event != previous:
            rows.append({
                "frame": frame, "player_x": player_x, "player_y": player_y,
                "body_code": body_code, "exhaust_code": exhaust_code,
                "exhaust_x": exhaust_x, "exhaust_y": exhaust_y,
            })
            previous = event
        apply_writes(sprite, writes.get(frame, []), 0xC0000)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    binary_path = OUTPUT / "R9_LAUNCH_EVENTS.bin"
    binary_path.write_bytes(packed)
    logical_binary_path = OUTPUT / "R9_LAUNCH_LOGICAL.bin"
    logical_binary_path.write_bytes(logical_packed)
    manifest = {
        "format": 1,
        "source": "R-Type World M72 latched Sprite RAM",
        "capture": str(CAPTURE.resolve()),
        "base_frame": BASE_FRAME,
        "end_frame_exclusive": END_FRAME,
        "frame_count": END_FRAME - BASE_FRAME,
        "event_format": "<hhBBhh: player x/y, body index, exhaust kind/x/y",
        "player_spriteram_offset": PLAYER_OFFSET,
        "exhaust_spriteram_offset": EXHAUST_OFFSET,
        "exhaust_kinds": {
            "0": "none/$001F", "1": "$0A23", "2": "$0AA2",
            "3": "$0AA4", "4": "$0AA6",
        },
        "transitions": rows,
        "binary": {
            "file": binary_path.name,
            "size": len(packed),
            "sha256": sha256(packed),
        },
        "logical_binary": {
            "file": logical_binary_path.name,
            "record_format": "<hhBBhhHH",
            "record_size": LOGICAL_EVENT.size,
            "size": len(logical_packed),
            "sha256": sha256(logical_packed),
        },
    }
    (OUTPUT / "r9_launch_events.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"R-9 launch: {END_FRAME - BASE_FRAME} exact frames, "
        f"native={len(packed)} bytes, logical={len(logical_packed)} bytes, "
        f"{len(rows)} transitions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
