"""Поиск и снятие музыкальных треков аркадного R-Type в чистом виде.

Партитура, снятая из attract-режима, непригодна: там идёт демо-игра, а у M72
музыка и эффекты играются одним YM2151. В такой лог вперемешку попадают
выстрелы и взрывы, и перенесённая мелодия после верного начала превращается в
набор эффектов.

Здесь каждая команда подаётся звуковому Z80 в тишине (между окончанием POST и
вставкой монеты игра молчит), поэтому в логе остаётся ровно один трек. Режим
probe прогоняет коротким окном и по числу нот и задействованных каналов
отличает музыку от эффекта; режим capture снимает выбранный трек целиком.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAME = Path(os.environ.get("RTYPE_MAME") or ROOT / "Tools" / "mame0288" / "mame.exe")
DEFAULT_ROMPATH = ROOT / "Build" / "Arcade" / "MAME" / "roms"
LUA_SCRIPT = ROOT / "Source" / "Tools" / "mame_music_log.lua"
COIN_FRAME = 650            # вставка монеты: с кредитом автомат не крутит демо
SILENT_FRAME = 700          # автомат затих (последняя его команда — кадр 654)
FPS = 55.0                  # частота кадров M72


def run(command: int, exit_frame: int, out_dir: Path,
        mame: Path, rompath: Path) -> Path:
    """Подать одну команду в тишине и снять регистровый лог YM2151."""
    out_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "RTYPE_MUS_CMD": str(command),
        "RTYPE_MUS_COIN": str(COIN_FRAME),
        "RTYPE_MUS_FRAME": str(SILENT_FRAME),
        "RTYPE_MUS_EXIT": str(SILENT_FRAME + exit_frame),
        # Путь только относительный: io.open в Lua не открывает файлы по
        # путям с кириллицей, а профиль пользователя здесь именно такой.
        # MAME запускается из корня проекта, поэтому относительный путь верен.
        "RTYPE_MUS_OUT": out_dir.resolve().relative_to(ROOT).as_posix(),
    })
    args = [
        str(mame), "rtype", "-rompath", str(rompath.resolve()),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-nothrottle", "-noautoframeskip", "-frameskip", "0",
        "-seconds_to_run", str(math.ceil((SILENT_FRAME + exit_frame) / FPS) + 4),
        "-autoboot_script", str(LUA_SCRIPT.resolve()),
    ]
    subprocess.run(args, cwd=ROOT, env=environment, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
    return out_dir / "ym2151_writes.csv"


def summarize(csv_path: Path) -> dict:
    """Признаки, по которым музыка отличается от эффекта."""
    keyons = []
    channels = set()
    with csv_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            register = int(row["register"], 16)
            value = int(row["value"], 16)
            if register == 0x08 and value & 0x78:      # key-on со слотами
                keyons.append(int(row["frame"]))
                channels.add(value & 0x07)
    return {
        "notes": len(keyons),
        "channels": len(channels),
        "last": keyons[-1] if keyons else 0,
    }


def detect_loop(csv_path: Path) -> tuple[int, int] | None:
    """Найти точку зацикливания: трек повторяет ту же последовательность нот.

    Сравнивается цепочка (канал, key-on-маска) — при повторе она совпадает с
    началом. Возвращает (кадр начала повтора, длина цикла в кадрах).
    """
    events = []
    with csv_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["register"], 16) == 0x08:
                events.append((int(row["frame"]), int(row["value"], 16)))
    if len(events) < 200:
        return None
    head = [value for _, value in events[:64]]
    for start in range(64, len(events) - 64):
        if [value for _, value in events[start:start + 64]] == head:
            return events[start][0], events[start][0] - events[0][0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commands", default="0x22,0x25,0x28,0x2B,0x32,0x4C,0x4D,0x4E,0x4F",
                        help="коды команд через запятую")
    parser.add_argument("--probe-frames", type=int, default=1100,
                        help="окно короткого прогона (кадры)")
    parser.add_argument("--capture", type=lambda s: int(s, 0), default=None,
                        help="снять один трек целиком этой командой")
    parser.add_argument("--capture-frames", type=int, default=9000)
    parser.add_argument("--out", type=Path, default=ROOT / "Build" / "Arcade" / "Music")
    parser.add_argument("--mame", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--rompath", type=Path, default=DEFAULT_ROMPATH)
    args = parser.parse_args()

    if args.capture is not None:
        path = run(args.capture, args.capture_frames, args.out, args.mame, args.rompath)
        info = summarize(path)
        loop = detect_loop(path)
        print(f"команда 0x{args.capture:02X}: {info['notes']} нот, "
              f"{info['channels']} каналов, конец на {info['last'] / FPS:.1f} с")
        if loop:
            print(f"зацикливание: кадр {loop[0]} ({loop[0] / FPS:.1f} с), "
                  f"длина цикла {loop[1] / FPS:.1f} с")
        else:
            print("зацикливания в окне не найдено")
        print(f"лог: {path}")
        return

    probe_dir = args.out / "probe"
    print(f"{'команда':>8} {'нот':>5} {'каналов':>8} {'конец, с':>9}  вывод")
    for token in args.commands.split(","):
        command = int(token.strip(), 0)
        path = run(command, args.probe_frames, probe_dir, args.mame, args.rompath)
        info = summarize(path)
        target = probe_dir / f"cmd_{command:02X}.csv"
        path.replace(target)
        # Музыка: играет всё окно и держит несколько каналов. Эффект: короткий.
        is_music = info["channels"] >= 3 and info["last"] > args.probe_frames * 0.7
        print(f"    0x{command:02X} {info['notes']:5d} {info['channels']:8d} "
              f"{info['last'] / FPS:9.1f}  {'МУЗЫКА' if is_music else 'эффект'}")


if __name__ == "__main__":
    main()
