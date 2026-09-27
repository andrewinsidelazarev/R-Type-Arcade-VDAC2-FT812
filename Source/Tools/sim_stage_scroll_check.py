#!/usr/bin/env python3
"""Проверка двух проходов живого M72 tilemap scroll в собранном Z80."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from sim_frame_png import DLRenderer  # noqa: E402
from sim_player_shot_check import bitmap_draws  # noqa: E402


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT, spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym", load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=60_000_000)
    machine.set_byte(symbols["GameMode"], 1)

    bg_base = (machine.get_word(symbols["M72StageBgAtlasLo"]) |
               machine.get_byte(symbols["M72StageBgAtlasHi"]) << 16)
    fg_base = (machine.get_word(symbols["M72StageFgAtlasLo"]) |
               machine.get_byte(symbols["M72StageFgAtlasHi"]) << 16)
    bg_end = bg_base + symbols["M72_STAGE_S0_BG_ATLAS_SIZE"]
    fg_end = fg_base + symbols["M72_STAGE_S0_FG_ATLAS_SIZE"]
    results = []
    for suffix, scroll in (("a", 176), ("b", 177)):
        machine.set_word(symbols["M72_ScrollBgX"], scroll)
        machine.set_word(symbols["M72_ScrollFgX"], scroll)
        machine.ft.cmd_write_ptr = 0
        machine.call(symbols["Render_Frame"], max_steps=5_000_000)
        commands = bytes(machine.ft.ram_cmd[:machine.ft.cmd_write_ptr])
        draws = bitmap_draws(commands)
        bg = [draw for draw in draws if bg_base <= draw["source"] < bg_end]
        fg = [draw for draw in draws if fg_base <= draw["source"] < fg_end]
        assert 40 <= len(bg) <= 80, (scroll, len(bg), len(fg), len(commands))
        assert 140 <= len(fg) <= 260, (scroll, len(bg), len(fg), len(commands))
        renderer = DLRenderer(bytes(machine.ft.ram_g))
        renderer.run(commands)
        output = ROOT / "Build" / f"stage_scroll_host_{suffix}.png"
        renderer.img.save(output)
        results.append((commands, bg, fg, bytes(renderer.img.tobytes()), output))

    # При scroll 176->177 tile-base тот же, а вся сетка смещается влево на
    # round(64/3)=21 единицу VERTEX_FORMAT-3 (один нативный пиксель M72).
    first_a = min(results[0][1], key=lambda draw: draw["x_units"])
    same_source_b = [
        draw for draw in results[1][1] if draw["source"] == first_a["source"]
    ]
    assert same_source_b
    assert any(draw["x_units"] == first_a["x_units"] - 21
               for draw in same_source_b)
    assert results[0][3] != results[1][3]
    assert all(len(result[0]) < 4096 for result in results)

    print("Stage 1 dynamic tilemap: два priority-прохода и scroll — OK")
    print(
        f"scroll 176->177: back={len(results[0][1])}/{len(results[1][1])}, "
        f"front={len(results[0][2])}/{len(results[1][2])}, shift=-21/8 px"
    )
    print(f"кадры: {results[0][4].name}, {results[1][4].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
