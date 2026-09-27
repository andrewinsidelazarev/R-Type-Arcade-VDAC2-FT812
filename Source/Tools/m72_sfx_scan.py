#!/usr/bin/env python3
"""Каталог звуковых эффектов аркадного R-Type.

Игра адресует звуковому Z80 команды через io-порт V30 $00. Скрипт перебирает
диапазон команд, каждую подаёт в тишине (после POST, до монеты) и записывает
результат. Так получается полный банк подлинных SFX без вычитаний и без
угадывания: что звучит — то и есть эффект, что молчит — служебная команда.

Выход: Build/Arcade/Audio/scan/cmd_XX.wav и catalog.json со сводкой.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAME = Path(os.environ.get("RTYPE_MAME") or ROOT / "Tools" / "mame0288" / "mame.exe")
DEFAULT_ROMPATH = ROOT / "Build" / "Arcade" / "MAME" / "roms"
LUA_SCRIPT = ROOT / "Source" / "Tools" / "mame_sound_command.lua"
OUT_DIR = ROOT / "Build" / "Arcade" / "Audio" / "scan"
SILENT_FRAME = 420
EXIT_FRAME = 620          # запас, чтобы длинные эффекты успели отзвучать
THRESHOLD = 40.0          # порог активности в единицах 16-битного PCM


def capture(command: int, mame: Path, rompath: Path) -> Path:
    wav_path = OUT_DIR / f"cmd_{command:02X}.wav"
    environment = os.environ.copy()
    environment.update({
        "RTYPE_SND_CMD": str(command),
        "RTYPE_SND_FRAME": str(SILENT_FRAME),
        "RTYPE_SND_EXIT": str(EXIT_FRAME),
    })
    args = [
        str(mame), "rtype", "-rompath", str(rompath.resolve()),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-samplerate", "48000", "-wavwrite", str(wav_path.relative_to(ROOT)),
        "-nothrottle", "-noautoframeskip", "-frameskip", "0",
        "-seconds_to_run", str(math.ceil(EXIT_FRAME / 55.0) + 4),
        "-autoboot_script", str(LUA_SCRIPT.resolve()),
    ]
    subprocess.run(args, cwd=ROOT, env=environment, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    return wav_path


def analyse(path: Path) -> dict[str, float] | None:
    with wave.open(str(path)) as handle:
        rate, channels = handle.getframerate(), handle.getnchannels()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    data = data.astype(float)
    window = rate // 100
    smooth = np.convolve(np.abs(data), np.ones(window) / window, mode="same")
    loud = np.flatnonzero(smooth > THRESHOLD)
    if not len(loud):
        return None
    segment = data[loud[0]:loud[-1] + 1]
    spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
    freqs = np.fft.rfftfreq(len(segment), 1 / rate)
    return {
        "start_seconds": float(loud[0] / rate),
        "duration_seconds": float((loud[-1] - loud[0]) / rate),
        "peak": float(np.abs(segment).max()),
        "rms": float(np.sqrt((segment ** 2).mean())),
        "high_ratio": float(spectrum[freqs > 2000].sum() / max(spectrum.sum(), 1e-9)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=lambda v: int(v, 0), default=0x20)
    parser.add_argument("--last", type=lambda v: int(v, 0), default=0xFF)
    parser.add_argument("--mame", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--rompath", type=Path, default=DEFAULT_ROMPATH)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog_path = OUT_DIR / "catalog.json"
    if catalog_path.is_file():
        previous = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog: dict[str, dict[str, float]] = dict(previous["sounding"])
        silent = set(previous["silent"])
    else:
        catalog = {}
        silent: set[str] = set()
    # Частичный повторный scan заменяет только выбранный диапазон, не стирая
    # уже проверенные команды из остальных частей аппаратного байта.
    for command in range(args.first, args.last + 1):
        key = f"0x{command:02X}"
        catalog.pop(key, None)
        silent.discard(key)
    for command in range(args.first, args.last + 1):
        try:
            wav_path = capture(command, args.mame, args.rompath)
        except subprocess.SubprocessError as error:
            print(f"0x{command:02X}: прогон не удался ({error})")
            continue
        info = analyse(wav_path)
        if info is None:
            silent.add(f"0x{command:02X}")
            wav_path.unlink(missing_ok=True)
            continue
        catalog[f"0x{command:02X}"] = info
        print(f"0x{command:02X}: {info['duration_seconds']:.3f} с, пик {info['peak']:.0f}, "
              f"RMS {info['rms']:.0f}, ВЧ {info['high_ratio']:.2f}")

    (OUT_DIR / "catalog.json").write_text(
        json.dumps({
            "sounding": dict(sorted(catalog.items())),
            "silent": sorted(silent),
        }, indent=2, ensure_ascii=False)
        + "\n", encoding="utf-8")
    print(f"\nзвучащих команд: {len(catalog)}, беззвучных: {len(silent)}")
    print(f"каталог: {OUT_DIR / 'catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
