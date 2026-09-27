#!/usr/bin/env python3
"""Проверить собранный семизначный HUD без визуальных догадок в Unreal.

Исполняется настоящий `Render_M72Hud` из Core page #06. Счётчик выданных
bitmap-глифов доказывает правило `$191B`: гаснут только ведущие нули первых
шести ячеек, а последняя нулевая цифра остаётся видимой.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)

    cases = (
        ((0x00, 0x00, 0x00, 0x00), 1),       # 0
        ((0x00, 0x45, 0x01, 0x00), 5),       # 14 500
        ((0x99, 0x99, 0x99, 0x09), 7),       # 9 999 999
    )
    for packed_bcd, expected_glyphs in cases:
        for offset, value in enumerate(packed_bcd):
            machine.set_byte(symbols["ArcadeScore"] + offset, value)
        machine.set_byte(symbols["M72Video_EmitCount"], 0)
        machine.call(symbols["Render_M72Hud"], max_steps=1_000_000)
        assert machine.get_byte(symbols["M72Video_EmitCount"]) == expected_glyphs
        assert machine.get_byte(symbols["Render_M72Hud.column"]) == 14
        assert machine.get_byte(symbols["Render_M72Hud.digitsRemaining"]) == 0
        assert machine.get_word(
            symbols["M72Video_DrawTileLayer.screenY"]) == 744 * 8

    print("HUD: 7 цифр, ведущие нули и последняя видимая 0 — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
