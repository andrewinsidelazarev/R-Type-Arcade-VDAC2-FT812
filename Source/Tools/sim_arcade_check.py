#!/usr/bin/env python3
"""Машинная проверка живого arcade-состояния в собранной реализации Z80.

Это host-симуляция, не Unreal и не реальное железо. Она исполняет настоящий код
SPG и подставляет уже объединённый InputState в той же точке, где опрос
клавиатуры, джойстика и Kempston Mouse передаёт управление игровой логике.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

INPUT_LEFT = 0x01
INPUT_RIGHT = 0x02
INPUT_UP = 0x04
INPUT_DOWN = 0x08
INPUT_FIRE = 0x10
INPUT_RELEASE = 0x20

PLAYER_X = 0x4203
PLAYER_Y = 0x4206
FORCE_DETACHED = 0x420F
WAVE_CHARGE = 0x4211
WAVE_POWER = 0x4212
WAVE_PENDING = 0x4213
INPUT_STATE = 0x4202
GS_PRESENT = 0x4214
GS_LOADED = 0x4215
GS_LAST_ERROR = 0x4218


def q16_8(machine: TSConfFT812Machine, address: int) -> int:
    return (machine.get_word(address + 1) << 8) | machine.get_byte(address)


def logical(machine: TSConfFT812Machine, address: int) -> int:
    return machine.get_word(address + 1)


def set_q16_8(machine: TSConfFT812Machine, address: int, value: int) -> None:
    machine.set_byte(address, value & 0xFF)
    machine.set_byte(address + 1, (value >> 8) & 0xFF)
    machine.set_byte(address + 2, (value >> 16) & 0xFF)


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=40_000_000)
    # Общая модель TS-Config/FT812 возвращает #FF для неизвестных портов GS.
    # Старт обязан штатно завершить тайм-аут и оставить игру доступной без GS.
    assert machine.get_byte(GS_PRESENT) == 0
    assert machine.get_byte(GS_LOADED) == 0
    assert machine.get_byte(GS_LAST_ERROR) == 1
    # Этот тест покрывает ручное управление уже активным R-9. Самостоятельный
    # 226-кадровый вылет проверяет sim_player_intro_check.py.
    machine.set_word(sym["ArcadeIntroFrame"], 226)
    machine.set_byte(sym["ArcadeIntroEffectKind"], 0)

    def frame(mask: int) -> None:
        machine.set_byte(INPUT_STATE, mask)
        # После добавления титула MainLoop законно не вызывает игровое
        # обновление до START. Здесь проверяется именно игровая логика, поэтому
        # вызываем её настоящую Z80-подпрограмму напрямую; display list
        # независимо покрывают sim_player_shot/sim_wave/sim_exhaust.
        machine.call(sym["ArcadeGame_Update"], max_steps=2_000_000)

    assert logical(machine, PLAYER_X) == 233
    assert logical(machine, PLAYER_Y) == 192

    for _ in range(10):
        frame(INPUT_RIGHT)
    expected_x_q = 233 * 256 + 10 * 853
    assert q16_8(machine, PLAYER_X) == expected_x_q

    # Force в буквальной модели скрыт до первого power-up. Для изолированной
    # проверки ПКМ создаём именно штатное attached-состояние, а не возвращаем
    # старую синтетическую Force, которая была видна сразу после старта.
    machine.set_byte(sym["ArcadeForceLevel"], 1)
    machine.set_byte(sym["ArcadeForceRequestedLevel"], 1)
    machine.set_byte(sym["ArcadeForceState"], 2)
    machine.set_byte(sym["ArcadeForcePalette"], 0)
    machine.set_byte(sym["ArcadeForceAttached"], 1)

    # Глобальный ПКМ — фронт, а не уровень с автоповтором.
    frame(INPUT_RELEASE)
    assert machine.get_byte(FORCE_DETACHED) == 1
    frame(INPUT_RELEASE)
    frame(INPUT_RELEASE)
    assert machine.get_byte(FORCE_DETACHED) == 1
    frame(0)
    assert machine.get_byte(sym["ArcadeReleasePrev"]) == 0

    # Нативные fixed-выстрел и Wave имеют собственные byte-exact проверки
    # sim_player_shot_check.py и sim_wave_shot_check.py. Здесь остаётся общая
    # игровая оболочка: управление, границы и фронт кнопки Force.
    set_q16_8(machine, PLAYER_X, 586 * 256)
    frame(INPUT_RIGHT)
    assert q16_8(machine, PLAYER_X) == 587 * 256
    set_q16_8(machine, PLAYER_X, 1 * 256)
    frame(INPUT_LEFT)
    assert q16_8(machine, PLAYER_X) == 0

    set_q16_8(machine, PLAYER_Y, 421 * 256)
    frame(INPUT_DOWN)
    assert q16_8(machine, PLAYER_Y) == 422 * 256
    set_q16_8(machine, PLAYER_Y, 1 * 256)
    frame(INPUT_UP)
    assert q16_8(machine, PLAYER_Y) == 0

    print("Собранная arcade-логика: OK")
    print("Движение: Q16.8, 640x480; X 0..587, Y 0..422")
    print("Глобальный ПКМ: одно переключение на фронт")
    print("Fixed-выстрел и Wave проверяются отдельными native/display-list oracle")
    print("Без GS: ограниченный тайм-аут, игра продолжает работу")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
