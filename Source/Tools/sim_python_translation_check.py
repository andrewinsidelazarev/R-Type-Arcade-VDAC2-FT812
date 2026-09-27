#!/usr/bin/env python3
"""Проверка сгенерированных Python LUT внутри настоящего кода Z80/SPG."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HMM2_TOOLS = (ROOT.parent / "HMM2" / "Pre-releases" /
              "v020-2026-07-16-adventure-ui-battle-ai-reference" /
              "Source" / "Tools")
sys.path.insert(0, str(HMM2_TOOLS))

from pyz80_compiler.frontend import lower_function  # noqa: E402
from pyz80_compiler.interpreter import execute  # noqa: E402
from pyz80_compiler.manifest import CompilerManifest  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


def table(report: dict[str, object], name: str) -> dict[str, object]:
    for record in report["tables"]:  # type: ignore[index]
        if record["asm_name"] == name:
            return record
    raise AssertionError(f"в отчёте нет таблицы {name}")


def main() -> int:
    report = json.loads((ROOT / "Build" / "rtype_python_translation.json")
                        .read_text(encoding="utf-8"))
    blob = (ROOT / "Build" / "python_translation_tables.bin").read_bytes()
    logo_record = table(report, "RTypePyTitleLogoState")
    charge_record = table(report, "RTypePyAdvanceWaveCharge")
    power_record = table(report, "RTypePyWavePower")

    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=60_000_000)

    logo_offset = int(logo_record["offset"])
    for frame in (0, 1, 64, 125, 176, 204, 276, 315, 400):
        expected_frame = min(frame, 315)
        expected = blob[
            logo_offset + expected_frame * 35:
            logo_offset + expected_frame * 35 + 35
        ]
        machine.set_word(sym["M72_TitleTimer"], frame + 1)
        machine.call(sym["RTypePythonTitle_LoadCurrent"], max_steps=100_000)
        actual = machine.get_memory(sym["M72TitleGlyphState"], 35)
        assert actual == expected, f"title frame {frame} отличается от Python LUT"

    compiler_manifest = CompilerManifest.load(
        ROOT / "Source" / "Tools" / "rtype_python_compiler.json")
    pitch_spec = next(
        item for item in compiler_manifest.functions
        if item.symbol == "rtype_port.game.advance_pitch")
    pitch_ir, _ = lower_function(ROOT / "Source" / "Python", pitch_spec)
    for pitch in range(40):
        for up in range(2):
            for down in range(2):
                input_state = ((sym["INPUT_UP"] if up else 0) |
                               (sym["INPUT_DOWN"] if down else 0))
                masked = input_state & (sym["INPUT_UP"] | sym["INPUT_DOWN"])
                expected = execute(pitch_ir, (
                    pitch,
                    int(masked == sym["INPUT_UP"]),
                    int(masked == sym["INPUT_DOWN"]),
                ))
                machine.set_byte(sym["ArcadePlayerPitch"], pitch)
                machine.set_byte(sym["InputState"], input_state)
                machine.call(sym["ArcadePlayer_UpdatePitch"], max_steps=10_000)
                assert machine.get_byte(sym["ArcadePlayerPitch"]) == expected
                assert machine.mem.pages[2] == sym["CorePage"] + 1

    charge_offset = int(charge_record["offset"])
    for charge in range(129):
        machine.set_byte(sym["ArcadeFireHeld"], 1)
        machine.set_byte(sym["ArcadeWaveCharge"], charge)
        machine.set_byte(sym["InputState"], sym["INPUT_FIRE"])
        machine.call(sym["ArcadeWave_Update"], max_steps=10_000)
        assert machine.get_byte(sym["ArcadeWaveCharge"]) == blob[
            charge_offset + charge]

    power_offset = int(power_record["offset"])
    for charge in range(129):
        machine.set_byte(sym["ArcadeFireHeld"], 1)
        machine.set_byte(sym["ArcadeWaveCharge"], charge)
        machine.set_byte(sym["ArcadeWaveShotPower"], 0)
        machine.set_byte(sym["ArcadeWaveShotPending"], 0)
        machine.set_byte(sym["InputState"], 0)
        machine.call(sym["ArcadeWave_Update"], max_steps=10_000)
        expected_power = blob[power_offset + charge]
        assert machine.get_byte(sym["ArcadeWaveShotPower"]) == expected_power
        assert machine.get_byte(sym["ArcadeWaveShotPending"]) == bool(expected_power)

    print(
        "Python translation in SPG: title 9 frames, compiled pitch 160 states, "
        "charge/power 258 states — byte exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
