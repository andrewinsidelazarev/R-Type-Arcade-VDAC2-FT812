#!/usr/bin/env python3
"""Исполнить Z80 stage selector на каждом отдельном RTZ2-файле."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))

from rtype_port.world_terrain import M72WorldTerrain  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE_SIZE = 0x4000
OLD_PACK_PAGES = 154


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    manifest = json.loads(
        (ROOT / "Build" / "rtype_stage_packs.json").read_text(encoding="utf-8")
    )
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    machine.set_byte(symbols["GameMode"], 0)  # тестируем RAM, не RAM_G texture path
    first = symbols["RTYPE_TARGET_PACK_BASE_PAGE"] * PAGE_SIZE
    last = first + OLD_PACK_PAGES * PAGE_SIZE
    for entry in manifest["stages"]:
        stage = int(entry["stage"])
        payload = (ROOT / "Build" / "SD" / "RType" /
                   str(entry["filename"])).read_bytes()
        machine.mem.physical[first:last] = bytes(last - first)
        machine.mem.physical[first:first + len(payload)] = payload
        steps = machine.call(
            symbols["RTypeTarget_SelectStage"], a=stage, max_steps=5_000_000
        )
        assert machine.get_byte(symbols["RTypeTargetValid"]) == 1, (stage, steps)
        assert machine.get_byte(symbols["RTypeTargetStage"]) == stage, stage
        oracle = M72WorldTerrain(stage)
        foreground = bytes(machine.mem.physical[0x07 * PAGE_SIZE:0x08 * PAGE_SIZE])
        background = bytes(machine.mem.physical[0x08 * PAGE_SIZE:0x09 * PAGE_SIZE])
        assert foreground == bytes(oracle.vram[0]), f"stage {stage}: foreground"
        assert background == bytes(oracle.vram[1]), f"stage {stage}: background"
        print(f"stage {stage}: Z80 SelectStage OK ({steps} instructions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
