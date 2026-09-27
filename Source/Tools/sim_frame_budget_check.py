#!/usr/bin/env python3
"""Измерить реальную Z80/FT812 стоимость TITLE и GAME собранной SPG.

Это не оценка Python-кода: каждый замер исполняет настоящий ASM, считает
инструкции и t-states, а размер display list берётся из отправленного FT812
RAM_CMD. Скрипт нужен как регрессия против возврата к «слайд-шоу».
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
from pyz80_compiler.ft812_budget import (  # noqa: E402
    FT812Timing,
    analyze_display_list,
    expand_coprocessor_stream,
)
from pyz80_compiler.manifest import CompilerManifest  # noqa: E402


COMPILER_MANIFEST = CompilerManifest.load(
    ROOT / "Source" / "Tools" / "rtype_python_compiler.json")
FT_TARGET = COMPILER_MANIFEST.target.ft812
if FT_TARGET is None:
    raise RuntimeError("compiler manifest не содержит target.ft812")
FT_TIMING = FT812Timing(
    width=FT_TARGET.width,
    height=FT_TARGET.height,
    hcycle=FT_TARGET.hcycle,
    pclk=FT_TARGET.pclk,
    safety_utilization=FT_TARGET.safety_utilization,
)
if FT_TIMING.safe_line_cycles != FT_TARGET.safe_line_cycles:
    raise RuntimeError("расчёт безопасного лимита FT812 расходится с manifest")


def sent_display_list(machine: TSConfFT812Machine) -> bytes:
    ring = machine.ft.ram_cmd
    if len(ring) != FT_TARGET.cmd_fifo_bytes:
        raise AssertionError(
            f"RAM_CMD={len(ring)}, manifest={FT_TARGET.cmd_fifo_bytes}")
    mask = len(ring) - 1
    write = machine.ft.cmd_write_ptr & mask

    def word_at(position: int) -> int:
        return int.from_bytes(bytes(
            ring[(position + offset) & mask] for offset in range(4)),
            "little",
        )

    start = None
    for distance in range(4, len(ring) + 1, 4):
        position = (write - distance) & mask
        if word_at(position) == 0xFFFFFF00:
            start = position
            break
    if start is None:
        raise AssertionError("RAM_CMD ring не содержит CMD_DLSTART текущего кадра")
    size = (write - start) & mask
    if size > FT_TARGET.cmd_fifo_usable:
        raise AssertionError(
            f"RAM_CMD payload={size}, limit={FT_TARGET.cmd_fifo_usable}")
    return bytes(ring[(start + offset) & mask] for offset in range(size))


def ft812_budget(machine: TSConfFT812Machine):
    expansion = expand_coprocessor_stream(
        sent_display_list(machine), ram_g=machine.ft.ram_g)
    report = analyze_display_list(expansion.display_list, FT_TIMING)
    if report.word_count >= FT_TARGET.ram_dl_word_limit:
        raise AssertionError(
            f"RAM_DL={report.word_count}, должен быть меньше "
            f"{FT_TARGET.ram_dl_word_limit}")
    return expansion, report


def measure_call(machine: TSConfFT812Machine, address: int,
                 max_steps: int = 20_000_000) -> tuple[int, int]:
    before = machine.tstates
    steps = machine.call(address, max_steps=max_steps)
    return steps, machine.tstates - before


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)

    title_update = measure_call(machine, sym["Application_Update"])
    title_render = measure_call(machine, sym["Render_Frame"])
    title_expansion, title_ft = ft812_budget(machine)

    # Вход напрямую в штатный scene transition исключает 315 кадров ожидания,
    # но не пропускает ни инициализацию World, ни DMA/RAM_G загрузки уровня.
    enter_world = measure_call(
        machine, sym["Application_StartGame"], max_steps=80_000_000)
    game_rows: list[dict[str, int]] = []
    for _ in range(8):
        update_steps, update_t = measure_call(
            machine, sym["Application_Update"], max_steps=20_000_000)
        render_steps, render_t = measure_call(
            machine, sym["Render_Frame"], max_steps=20_000_000)
        expansion, ft_report = ft812_budget(machine)
        game_rows.append({
            "update_steps": update_steps,
            "update_t": update_t,
            "render_steps": render_steps,
            "render_t": render_t,
            "cmd_words": expansion.input_words,
            "dl_words": ft_report.word_count,
            "ft_worst_line": ft_report.worst_line,
            "ft_worst_cycles": ft_report.worst_cycles,
            "ft_headroom": ft_report.headroom_cycles,
        })

    max_update_t = max(row["update_t"] for row in game_rows)
    max_render_t = max(row["render_t"] for row in game_rows)
    max_commands = max(row["dl_words"] for row in game_rows)
    worst_ft = max(game_rows, key=lambda row: row["ft_worst_cycles"])
    # При 14 МГц один кадр 57 Гц даёт примерно 245 614 t-states. Update и
    # render должны укладываться вместе; запас оставлен под input/audio.
    print(
        f"TITLE update={title_update[1]}t render={title_render[1]}t "
        f"CMD={title_expansion.input_words} DL={title_ft.word_count} "
        f"FT line {title_ft.worst_line}={title_ft.worst_cycles}/"
        f"{title_ft.safe_line_cycles}")
    print(
        f"ENTER_WORLD={enter_world[1]}t; GAME max update={max_update_t}t "
        f"render={max_render_t}t DL={max_commands}; "
        f"FT line {worst_ft['ft_worst_line']}="
        f"{worst_ft['ft_worst_cycles']}/{FT_TARGET.safe_line_cycles} "
        f"headroom={worst_ft['ft_headroom']}")
    assert max_update_t + max_render_t < 230_000, (
        max_update_t, max_render_t, game_rows)
    print("Бюджет 57 FPS на 14 МГц — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
