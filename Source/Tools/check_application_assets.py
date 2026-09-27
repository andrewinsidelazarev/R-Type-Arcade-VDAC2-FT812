#!/usr/bin/env python3
"""Побитовая проверка таблиц title/attract против активного Python-контракта."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(ROOT / "Source" / "Python"))

import m72_title_stream as title_stream  # noqa: E402
from rtype_port.title import prompt_visible  # noqa: E402


TITLE_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_EVENTS.bin"
DEMO_PATH = ROOT / "Assets" / "Converted" / "Arcade" / "Attract" / "RTYPE_DEMO_INPUT.bin"
TITLE_SHA256 = "1e5d73d79f1558440597821b91c24579d9fd4fd0925c8736dfe0216605fe2900"
DEMO_SHA256 = "aec381d7e6150242a61021efbfd3c0ef38728e9eafc940a24538e8037631b742"


def expected_title() -> bytes:
    packets = bytearray()
    for frame in range(title_stream.LAST_STORED_FRAME + 1):
        packet = bytearray(title_stream._glyph_state(frame))
        packet += title_stream._visible_text(frame)
        packet += bytes((31, 0, 0))
        assert len(packet) == title_stream.PACKET_SIZE
        packets += packet
    return bytes(packets)


def main() -> int:
    title = TITLE_PATH.read_bytes()
    expected = expected_title()
    assert title == expected, "TITLE_EVENTS.bin расходится с rtype_port.title"
    assert hashlib.sha256(title).hexdigest() == TITLE_SHA256
    assert len(title) == 316 * 423

    # Границы prompt дублируют константы, по которым ASM проверяет timer-1.
    assert not prompt_visible(275)
    assert prompt_visible(276)
    assert prompt_visible(307)
    assert not prompt_visible(308)
    assert not prompt_visible(339)
    assert prompt_visible(340)

    demo = DEMO_PATH.read_bytes()
    assert len(demo) == 2107
    assert hashlib.sha256(demo).hexdigest() == DEMO_SHA256
    assert not any(value & 0xC0 for value in demo), "в demo есть неизвестные target-биты"

    split = (ROOT / "Build" / "rtype_demo_input_p00.bin").read_bytes()
    assert split == demo, "SPG-страница demo не совпала с исходной таблицей"
    generated = (ROOT / "Source" / "ASM" / "generated_spritepages.inc").read_text(
        encoding="utf-8")
    assert "M72_TITLE_FRAME_COUNT EQU 316" in generated
    assert "RTYPE_DEMO_INPUT_SIZE       EQU 2107" in generated
    print(
        "application assets: Python title 316/316, prompt boundaries, "
        "attract input 2107/2107 — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
