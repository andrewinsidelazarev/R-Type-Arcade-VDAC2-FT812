#!/usr/bin/env python3
"""Извлечь управляющий поток штатной attract-demo из готового Python-runtime.

World ROM остаётся oracle: до входа player handler ``$2027`` runtime идёт
скрыто ровно тем же путём, что активное Python-приложение. Затем каждый уже
обработанный байт demo-ввода из DS:$2040 переводится в битовую раскладку Z80 и
сохраняется в ОЗУ-таблицу. В целевой машине это обычное линейное чтение одного
байта за кадр, без V30, ветвления и вычисления траектории ввода.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_SOURCE = ROOT / "Source" / "Python"
PYTHON_DEPS = ROOT / "Build" / "PythonDeps"
for search_path in (PYTHON_DEPS, PYTHON_SOURCE):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from rtype_port.full_runtime import (  # noqa: E402
    ARCADE_PRESENTATION_ENTRY,
    FullRuntimeGame,
)


OUT = ROOT / "Assets" / "Converted" / "Arcade" / "Attract" / "RTYPE_DEMO_INPUT.bin"
M72_PROCESSED_INPUT = 0x42040
EXPECTED_HIDDEN_FRAMES = 504
EXPECTED_DEMO_FRAMES = 2107


def _target_mask(source: int) -> int:
    """M72 active-high: R,L,D,U,B1,B2 -> target L,R,U,D,FIRE,FORCE."""
    return (((source & 0x02) >> 1) |
            ((source & 0x01) << 1) |
            ((source & 0x08) >> 1) |
            ((source & 0x04) << 1) |
            ((source & 0x80) >> 3) |
            ((source & 0x40) >> 1))


def build_stream(out: Path = OUT) -> bytes:
    game = FullRuntimeGame(lambda _command: None, enable_renderer=False)
    hidden_frames = 0
    while not game.advance_title():
        hidden_frames += 1
    hidden_frames += 1
    if hidden_frames != EXPECTED_HIDDEN_FRAMES:
        raise RuntimeError(
            f"граница attract-demo сдвинулась: {hidden_frames} вместо "
            f"{EXPECTED_HIDDEN_FRAMES}")

    result = bytearray()
    while not game.return_to_custom_title:
        source = game.machine.cpu.mem_read(M72_PROCESSED_INPUT, 1)[0]
        result.append(_target_mask(source))
        game.update(0)
    if len(result) != EXPECTED_DEMO_FRAMES:
        raise RuntimeError(
            f"длина attract-demo сдвинулась: {len(result)} вместо "
            f"{EXPECTED_DEMO_FRAMES}")
    if game._director_handler() != ARCADE_PRESENTATION_ENTRY:
        raise RuntimeError("attract-demo завершилась не перед arcade presentation")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result)
    checksum = hashlib.sha256(result).hexdigest()
    print(
        f"Python attract-demo: hidden={hidden_frames}, visible={len(result)}, "
        f"sha256={checksum}")
    return bytes(result)


def main() -> int:
    build_stream()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
