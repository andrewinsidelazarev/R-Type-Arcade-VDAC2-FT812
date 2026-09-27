#!/usr/bin/env python3
"""Z80-oracle двух смертей для перенесённого Python lifecycle игрока."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


OBJECT_PAGE = 0x09
LIFE_ACTIVE = 0
LIFE_DEATH = 1


def physical(symbols: dict[str, int], name: str) -> int:
    return OBJECT_PAGE * 0x4000 + (symbols[name] & 0x3FFF)


def set_progression(machine: TSConfFT812Machine,
                    symbols: dict[str, int], progression: int) -> None:
    address = symbols["RTypeWorldProgressQ8"]
    machine.set_byte(address, 0)
    machine.set_word(address + 1, progression)


def stop_events(machine: TSConfFT812Machine,
                symbols: dict[str, int]) -> None:
    machine.set_word(
        symbols["RTypeTargetEventIndex"],
        machine.get_word(symbols["RTypeTargetEventCount"]),
    )


def dirty_player_state(machine: TSConfFT812Machine,
                       symbols: dict[str, int]) -> None:
    machine.set_byte(symbols["ArcadeReleasePrev"], 0x20)
    machine.set_byte(symbols["ArcadeForceDetached"], 1)
    machine.set_byte(symbols["ArcadeFireHeld"], 1)
    machine.set_byte(symbols["ArcadeWaveCharge"], 0x80)
    machine.set_byte(symbols["ArcadeWaveShotPower"], 20)
    machine.set_byte(symbols["ArcadeWaveShotPending"], 1)
    machine.set_byte(symbols["ArcadeShotTable"], 2)
    machine.set_byte(symbols["ArcadeWaveActive"], 1)
    machine.set_byte(symbols["ArcadeShotPending"], 1)
    machine.set_byte(symbols["ArcadeForceLevel"], 1)
    machine.set_byte(symbols["ArcadeForceRequestedLevel"], 1)
    machine.set_byte(symbols["ArcadeBitCount"], 2)
    machine.set_byte(symbols["ArcadeWeaponPickupPending"], 3)
    machine.set_byte(symbols["ArcadeWeaponType"], 4)
    machine.set_byte(symbols["ArcadePlayerRam0035"], 5)
    machine.set_byte(symbols["ArcadePlayerRam0036"], 6)
    machine.set_byte(symbols["ArcadeBit0Record"], 1)
    machine.set_byte(symbols["ArcadeBit1Record"], 1)


def assert_death_clear(machine: TSConfFT812Machine,
                       symbols: dict[str, int], ordinal: int) -> None:
    assert machine.get_byte(symbols["ArcadeLifeState"]) == LIFE_DEATH
    assert machine.get_word(symbols["ArcadeDeathAge"]) == 0
    assert machine.get_byte(symbols["RTypePyCheckpointOrdinal"]) == ordinal
    controls = bytes(machine.get_byte(symbols["ArcadeReleasePrev"] + offset)
                     for offset in range(6))
    assert controls == bytes(6), controls.hex()
    weapon_bytes = bytes(
        machine.get_byte(symbols["ArcadeShotTable"] + offset)
        for offset in range(
            symbols["ArcadeShotPending"] - symbols["ArcadeShotTable"] + 1))
    assert weapon_bytes == bytes(len(weapon_bytes)), weapon_bytes.hex()
    assert machine.get_byte(symbols["ArcadeForceLevel"]) == 0
    assert machine.get_byte(symbols["ArcadeForceRequestedLevel"]) == 0
    assert machine.get_byte(symbols["ArcadeBitCount"]) == 0
    assert machine.get_byte(symbols["ArcadeWeaponPickupPending"]) == 0
    assert machine.get_byte(symbols["ArcadeWeaponType"]) == 0
    assert machine.get_byte(symbols["ArcadeBit0Record"]) == 0
    assert machine.get_byte(symbols["ArcadeBit1Record"]) == 0
    assert machine.get_byte(symbols["RTypePyDeathPalette"]) != 0xFF
    assert machine.mem.physical[physical(
        symbols, "RTYPE_LAST_SOUND_COMMAND")] == 0x35


def run_death(machine: TSConfFT812Machine, symbols: dict[str, int],
              *, progression: int, ordinal: int, expected_lives: int,
              expected_source: tuple[int, int]) -> None:
    set_progression(machine, symbols, progression)
    dirty_player_state(machine, symbols)
    machine.call(symbols["ArcadeLifecycle_BeginDeath"], max_steps=3_000_000)
    assert_death_clear(machine, symbols, ordinal)

    machine.set_word(symbols["ArcadeDeathAge"], 116)
    machine.call(symbols["ArcadeLifecycle_Update"], max_steps=1_000_000)
    assert machine.get_byte(symbols["ArcadePlayerVisible"]) == 0
    assert machine.get_byte(symbols["RTypePyDeathPalette"]) == 0xFF

    stop_events(machine, symbols)
    machine.set_word(symbols["ArcadeDeathAge"], 179)
    machine.call(symbols["RTypePyLifecycle_DeathFrame"], max_steps=20_000_000)
    assert machine.get_byte(symbols["ArcadeLives"]) == expected_lives
    assert machine.mem.physical[physical(
        symbols, "RTYPE_CLEANUP_ACTIVE")] == 1

    machine.mem.physical[physical(symbols, "RTYPE_TRANSITION_FLAGS")] = 0x12
    machine.mem.physical[physical(symbols, "RTYPE_TRANSITION_FLAGS") + 1] = 0x34
    machine.mem.physical[physical(
        symbols, "RTYPE_TRANSITION_SOUND_INDEX")] = 0x56
    stop_events(machine, symbols)
    machine.set_word(symbols["ArcadeDeathAge"], 248)
    machine.call(symbols["RTypePyLifecycle_DeathFrame"], max_steps=80_000_000)

    assert machine.get_byte(symbols["ArcadeLifeState"]) == LIFE_ACTIVE
    assert machine.get_byte(symbols["ArcadeInvulnerability"]) == 0x80
    assert machine.get_byte(symbols["ArcadeLives"]) == expected_lives
    assert machine.get_word(symbols["ArcadePlayerX"] + 1) == 160
    assert machine.get_word(symbols["ArcadePlayerY"] + 1) == 221
    assert machine.get_word(symbols["RTypeWorldProgressQ8"] + 1) == (
        1536, 1728, 2688, 4032)[ordinal]
    assert machine.get_word(symbols["RTypeWorldFgSource"]) == expected_source[0]
    assert machine.get_word(symbols["RTypeWorldBgSource"]) == expected_source[1]
    assert machine.mem.physical[physical(
        symbols, "RTYPE_CLEANUP_ACTIVE")] == 0
    assert machine.mem.physical[physical(
        symbols, "RTYPE_TRANSITION_FLAGS")] == 0x12
    assert machine.mem.physical[physical(
        symbols, "RTYPE_TRANSITION_FLAGS") + 1] == 0x34
    assert machine.mem.physical[physical(
        symbols, "RTYPE_TRANSITION_SOUND_INDEX")] == 0x56

    event_page = machine.get_byte(symbols["RTypeTargetEventPage"])
    event_ptr = machine.get_word(symbols["RTypeTargetEventPtr"])
    event_at = event_page * 0x4000 + (event_ptr & 0x3FFF)
    threshold = (machine.mem.physical[event_at] |
                 (machine.mem.physical[event_at + 1] << 8))
    assert threshold == machine.get_word(symbols["RTypeWorldProgressQ8"] + 1)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    install_texture_coprocessor(machine)
    machine.set_byte(symbols["GameMode"], 1)
    machine.set_word(symbols["ArcadeIntroFrame"], 226)

    manifest = json.loads((
        ROOT / "Assets" / "Converted" / "Arcade" / "AllStages" /
        "Terrain" / "all_stage_terrain.json").read_text(encoding="utf-8"))
    checkpoints = manifest["stages"][0]["checkpoints"]
    assert [int(record["progression"]) for record in checkpoints] == [
        1536, 1728, 2688, 4032]

    run_death(machine, symbols, progression=2800, ordinal=2,
              expected_lives=7, expected_source=(180, 360))
    for _ in range(0x80):
        machine.call(symbols["ArcadeLifecycle_Update"], max_steps=100_000)
    assert machine.get_byte(symbols["ArcadeInvulnerability"]) == 0

    run_death(machine, symbols, progression=4100, ordinal=3,
              expected_lives=6, expected_source=(390, 570))

    print("PLAYER LIFECYCLE Z80/PYTHON OK: две смерти, checkpoints 2->3, жизни 8->7->6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
