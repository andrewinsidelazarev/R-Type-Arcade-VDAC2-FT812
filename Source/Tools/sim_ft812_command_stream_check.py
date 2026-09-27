#!/usr/bin/env python3
"""Exercise the exact staging-end -> banked slot3 command-buffer boundary."""

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
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)
    machine.mem.pages[3] = 0x09
    object_base = 0x09 * 0x4000
    machine.mem.physical[object_base:object_base + 32] = b"\xA7" * 32
    initial_sp = machine.reg.SP

    ptr = sym["FT.Coprocessor.BufferPtr"]
    command_buffer = sym["RTypeFTCommandBufferStart"]
    command_limit = sym["RTypeFTCommandBufferEnd"]
    flush_count = sym["RTypePyCommandFlushCount"]
    machine.set_byte(flush_count, 0)
    machine.set_word(ptr, command_limit - 4)
    machine.call(
        sym["FT.Coprocessor.Command_BCDE"],
        b=0x11, c=0x22, d=0x33, e=0x44,
        max_steps=2_000_000)
    assert machine.get_word(ptr) == command_limit
    machine.call(
        sym["FT.Coprocessor.Command_BCDE"],
        b=0x55, c=0x66, d=0x77, e=0x88,
        max_steps=4_000_000)
    assert machine.get_word(ptr) == command_buffer + 4
    assert machine.get_byte(flush_count) == 1
    assert machine.get_memory(command_buffer, 4) == bytes((0x88, 0x77, 0x66, 0x55))
    assert machine.mem.physical[object_base:object_base + 32] == b"\xA7" * 32
    assert machine.reg.SP == initial_sp

    # A 20-byte translated sprite state must be moved as one aligned record,
    # never split by falling through the slot boundary.
    source = 0x2000
    payload = bytes(range(20))
    machine.mem.write_block_linear(source, payload)
    machine.set_word(ptr, command_limit - 16)
    machine.call(
        sym["FT.Coprocessor.Copy"],
        b=0, c=len(payload), h=source >> 8, l=source & 0xFF,
        max_steps=4_000_000)
    assert machine.get_word(ptr) == command_buffer + len(payload)
    assert machine.get_memory(command_buffer, len(payload)) == payload
    assert machine.get_byte(flush_count) == 2
    assert machine.mem.physical[object_base:object_base + 32] == b"\xA7" * 32
    assert machine.reg.SP == initial_sp

    print(
        "FT812 command streaming: staging boundary flushed, 20-byte sprite "
        "record stayed atomic, object page and Z80 SP unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
