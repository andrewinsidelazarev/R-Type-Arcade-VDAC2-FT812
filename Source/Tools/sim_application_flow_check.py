#!/usr/bin/env python3
"""Регрессия верхнего автомата текущего app.py: TITLE → GAME."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HMM2_TOOLS = (ROOT.parent / "HMM2" / "Pre-releases" /
              "v020-2026-07-16-adventure-ui-battle-ai-reference" /
              "Source" / "Tools")
sys.path.insert(0, str(HMM2_TOOLS))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    assert "APP_SCENE_DEMO" not in sym
    assert "ApplicationDemo_Update" not in sym

    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=60_000_000)
    assert machine.get_byte(sym["GameMode"]) == sym["APP_SCENE_TITLE"]
    assert machine.get_word(sym["M72_TitleTimer"]) == 1
    assert machine.get_byte(sym["TsfmMusic_Active"]) == 0

    # У текущего app.py нет автоматической третьей сцены: title ждёт ввода.
    machine.set_word(sym["M72_TitleTimer"], 504)
    machine.set_byte(sym["M72TitleEventDone"], 1)
    machine.set_byte(sym["InputState"], 0)
    machine.call(sym["Title_Update"], max_steps=200_000)
    assert machine.get_byte(sym["GameMode"]) == sym["APP_SCENE_TITLE"]
    assert machine.get_word(sym["M72_TitleTimer"]) == 505

    # KEYDOWN до ready теряется, как start_pressed в одном Python-кадре.
    machine.set_word(sym["M72_TitleTimer"], 314)
    machine.set_byte(sym["M72_TitleInputArmed"], 0)
    machine.set_byte(sym["InputState"], sym["INPUT_FIRE"])
    machine.call(sym["Title_Update"], max_steps=200_000)
    machine.call(sym["Title_Update"], max_steps=200_000)
    assert machine.get_byte(sym["GameMode"]) == sym["APP_SCENE_TITLE"]

    # После отпускания отдельный новый фронт начинает подготовленную игру.
    machine.set_byte(sym["InputState"], 0)
    machine.call(sym["Title_Update"], max_steps=200_000)
    machine.set_byte(sym["InputState"], sym["INPUT_FIRE"])
    machine.call(sym["Title_Update"], max_steps=80_000_000)
    assert machine.get_byte(sym["GameMode"]) == sym["APP_SCENE_GAME"]
    assert machine.get_byte(sym["TsfmMusic_Active"]) == 1

    print("application flow: current app.py TITLE -> GAME, edge start — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
