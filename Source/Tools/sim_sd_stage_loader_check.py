#!/usr/bin/env python3
"""End-to-end: FAT32/CMD17 → staging RAM → TS DMA → active stage pack."""
from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HMM2 = ROOT.parent / "HMM2" / "Pre-releases"
# В v021 есть точная SD-модель, а vendored Z80 core лежит в v020.
sys.path.insert(0, str(HMM2 /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools" / "_z80_lib_cburbridge" / "src"))
sys.path.insert(0, str(HMM2 /
                       "v021-2026-07-26-battle-runtime-input-recruitment-reference" /
                       "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


PAGE_SIZE = 0x4000


def install_ram_dma(machine: TSConfFT812Machine) -> list[tuple[int, str, int]]:
    """Дополнить HMM2 host-модель режимом DMA_RAM (#01)."""
    original = machine._start_dma
    events: list[tuple[int, str, int]] = []

    def start(self: TSConfFT812Machine, mode: int) -> None:
        events.append((mode & 0xFF, self.spi_target, self.sd.reads))
        assert self.spi_target != "sd", "DMA запущена до завершения SD-фазы"
        if (mode & 0x87) != 0x01:
            original(mode)
            return
        self.dma.status = 0x80
        src_off = ((self.dma.src_h << 8) | self.dma.src_l) & (PAGE_SIZE - 1)
        dst_off = ((self.dma.dst_h << 8) | self.dma.dst_l) & (PAGE_SIZE - 1)
        source = (self.dma.src_x & 0xFF) * PAGE_SIZE + src_off
        target = (self.dma.dst_x & 0xFF) * PAGE_SIZE + dst_off
        count = (self.dma.number + 1) * (self.dma.length + 1) * 2
        self.mem.physical[target:target + count] = bytes(
            self.mem.physical[source:source + count]
        )
        self.dma.status = 0

    machine._start_dma = types.MethodType(start, machine)
    return events


def active_bytes(machine: TSConfFT812Machine, base_page: int, size: int) -> bytes:
    first = base_page * PAGE_SIZE
    return bytes(machine.mem.physical[first:first + size])


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    events = install_ram_dma(machine)
    base_page = symbols["RTYPE_TARGET_PACK_BASE_PAGE"]
    # В текущей v021 SD-модели поле reads объявлено, но CMD17 его не увеличивает.
    # Обёртка нужна только для диагностического счётчика и не меняет данные.
    original_sd_exec = machine.sd._exec
    def counted_sd_exec(self, command: list[int]) -> None:
        if (command[0] & 0x3F) == 17:
            self.reads += 1
        original_sd_exec(command)
    machine.sd._exec = types.MethodType(counted_sd_exec, machine.sd)
    machine.load_sd_image(ROOT / "Build" / "SD" / "rtype_test.img")
    steps = machine.run_until_pc(symbols["MainLoop"], max_steps=80_000_000)
    stage1 = (ROOT / "Build" / "SD" / "RType" / "RTYPE01.PAK").read_bytes()
    assert machine.get_byte(symbols["RTypeStageStorageAvailable"]) == 1
    assert machine.get_byte(symbols["RTypeTargetStage"]) == 1
    assert active_bytes(machine, base_page, len(stage1)) == stage1
    ram_events = [event for event in events if (event[0] & 0x87) == 0x01]
    assert len(ram_events) == len(stage1) // PAGE_SIZE
    assert len({event[2] for event in ram_events}) == 1
    assert any((event[0] & 0x87) == 0x82 for event in events), "нет DMA в FT812"
    print(f"stage 1 SD->RAM->DMA: OK ({steps} instructions, {machine.sd.reads} CMD17)")

    before_events = len(ram_events)
    machine.set_byte(symbols["GameMode"], 0)
    steps = machine.call(
        symbols["RTypeStage_LoadAndSelect"], a=2, max_steps=80_000_000
    )
    stage2 = (ROOT / "Build" / "SD" / "RType" / "RTYPE02.PAK").read_bytes()
    assert machine.get_byte(symbols["RTypeTargetStage"]) == 2
    assert active_bytes(machine, base_page, len(stage2)) == stage2
    ram_events = [event for event in events if (event[0] & 0x87) == 0x01]
    second = ram_events[before_events:]
    assert len(second) == len(stage2) // PAGE_SIZE
    assert len({event[2] for event in second}) == 1
    print(f"stage 2 SD->RAM->DMA: OK ({steps} instructions, {machine.sd.reads} CMD17 total)")
    print("SD/DMA phase audit: no DMA while SD chip-select is active - OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
