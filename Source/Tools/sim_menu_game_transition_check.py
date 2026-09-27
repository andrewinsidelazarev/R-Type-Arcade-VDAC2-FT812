#!/usr/bin/env python3
"""Verify the real TITLE input edge and the FT812-safe switch to GAME."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import (  # noqa: E402
    RAM_DL_BASE,
    REG_DLSWAP,
    TSConfFT812Machine,
    parse_sym,
)


INPUT_FIRE = 0x10


def words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i:i + 4], "little")
            for i in range(0, len(data), 4)]


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)
    assert machine.get_byte(sym["GameMode"]) == 0

    # Advance the exact title state machine without fabricating a direct GAME
    # entry. Input stays released until Python TitleScreen.ready is true.
    machine.set_byte(sym["InputState"], 0)
    while machine.get_word(sym["M72_TitleTimer"]) < 316:
        machine.call(sym["Application_Update"], max_steps=4_000_000)

    events: list[str] = []
    original_write = machine._write_ft_addr

    def traced_write(addr: int, value: int) -> None:
        if addr == REG_DLSWAP and value:
            events.append("swap")
        elif 0 <= addr < RAM_DL_BASE:
            events.append("ram_g")
        original_write(addr, value)

    machine._write_ft_addr = traced_write  # type: ignore[method-assign]
    machine.set_byte(sym["InputState"], INPUT_FIRE)
    machine.call(sym["Application_Update"], max_steps=80_000_000)

    assert machine.get_byte(sym["GameMode"]) == 1
    assert machine.get_byte(sym["RTypeTargetValid"]) == 1
    assert machine.get_byte(sym["RTypeTargetStage"]) == 1
    assert machine.get_byte(sym["ArcadeLives"]) == sym["RTYPEPY_INITIAL_LIVES"]
    assert machine.get_byte(sym["ArcadePlayerVisible"]) == 1
    assert "swap" in events and "ram_g" in events
    assert events.index("swap") < events.index("ram_g"), events[:20]

    # No GAME list has been submitted yet: RAM_DL must still contain the
    # protective black list while overlapping title ranges are overwritten.
    blank = words(bytes(machine.ft.ram_dl[:12]))
    assert blank == [0x02000000, 0x26000007, 0x00000000], blank

    machine.call(sym["Application_Update"], max_steps=20_000_000)
    machine.call(sym["Render_Frame"], max_steps=20_000_000)
    command_buffer = sym["RTypeFTCommandBufferStart"]
    command_limit = sym["RTypeFTCommandBufferEnd"]
    command_end = machine.get_word(sym["FT.Coprocessor.BufferPtr"])
    assert command_buffer <= command_end <= command_limit
    assert machine.get_byte(sym["RTypePyStackFault"]) == 0

    print(
        "TITLE->GAME: black DLSWAP precedes RAM_G DMA; "
        f"mode=GAME stage=1 lives={machine.get_byte(sym['ArcadeLives'])} "
        f"R-9 visible=1 first GAME chunk={command_end - command_buffer} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
