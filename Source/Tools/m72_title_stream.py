#!/usr/bin/env python3
"""Собрать покадровое состояние самостоятельного Python-title для Z80.

Python-runtime намеренно не показывает CREDIT и INSERT COIN. Этот генератор
берёт координатный автомат непосредственно из активного ``rtype_port.title``
и сохраняет только готовые таблицы состояний. На Z80 не остаётся ни
интерполяции, ни раскладки строк: кадр за один LDIR попадает в резидентный
буфер, а FT812 выводит уже подготовленные bitmap cells.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_SOURCE = ROOT / "Source" / "Python"
PYTHON_DEPS = ROOT / "Build" / "PythonDeps"
for search_path in (PYTHON_DEPS, PYTHON_SOURCE):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from rtype_port.title import LOGO_COUNT, _logo_state  # noqa: E402


DEFAULT_OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas"
PACKET_SIZE = 423
GLYPH_STATE_SIZE = 35
MAX_TEXT_GLYPHS = 96
LAST_STORED_FRAME = 315
TITLE_LINES = (
    (217, "BLAST OFF AND STRIKE", 25, 4, 0),
    (229, "THE EVIL BYDO EMPIRE!", 25, 5, 0),
    (245, "START GAME", 27, 7, 0),
    (308, "1987 BY IREM CORP.", 24, 28, 0),
)


def digest(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def _glyph_state(frame: int) -> bytes:
    """Семь записей visible/native-X/native-Y из Python-автомата."""
    result = bytearray()
    for glyph in range(LOGO_COUNT):
        visible, x, y = _logo_state(frame, glyph)
        result += struct.pack("<Bhh", int(visible), x, y)
    if len(result) != GLYPH_STATE_SIZE:
        raise AssertionError(len(result))
    return bytes(result)


def _visible_text(frame: int) -> bytes:
    """Готовые cell/style/column/row для уже появившихся символов."""
    records: list[tuple[int, int, int, int]] = []
    for first_frame, value, column, row, style in TITLE_LINES:
        remaining = max(0, (frame - first_frame + 1) * 3)
        for offset, character in enumerate(value):
            if character == " ":
                continue
            if remaining <= 0:
                break
            code = ord(character) - 32
            if not 0 <= code < 96:
                raise ValueError(f"символ {character!r} не помещается в ROM-шрифт")
            records.append((code, style, column + offset, row))
            remaining -= 1
    if len(records) > MAX_TEXT_GLYPHS:
        raise ValueError(f"в title {len(records)} глифов, предел {MAX_TEXT_GLYPHS}")
    result = bytearray((len(records),))
    for record in records:
        result += bytes(record)
    result += bytes((MAX_TEXT_GLYPHS - len(records)) * 4)
    return bytes(result)


def build_stream(out: Path = DEFAULT_OUT) -> bytes:
    """Записать кадры 0…315; дальше композиция статична, мигает лишь prompt."""
    packets = bytearray()
    for frame in range(LAST_STORED_FRAME + 1):
        packet = bytearray(_glyph_state(frame))
        packet += _visible_text(frame)
        # Три прежних palette-byte сохраняют неизменный формат packet. Сам
        # ARGB4444-атлас уже содержит цвет; Z80 эти байты не интерпретирует.
        packet += bytes((31, 0, 0))
        if len(packet) != PACKET_SIZE:
            raise AssertionError(f"неверный размер title packet: {len(packet)}")
        packets += packet

    out.mkdir(parents=True, exist_ok=True)
    path = out / "TITLE_EVENTS.bin"
    path.write_bytes(packets)
    print(
        f"Python title: {LAST_STORED_FRAME + 1} кадров, {len(packets)} байт, "
        f"sha256={digest(packets)}")
    print(f"glyph state: {GLYPH_STATE_SIZE} байт; packet: {PACKET_SIZE} байт")
    return bytes(packets)


def main() -> int:
    build_stream()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
