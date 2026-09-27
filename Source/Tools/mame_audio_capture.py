#!/usr/bin/env python3
"""Получение звука выстрела R-Type из двух детерминированных запусков MAME.

Базовый запуск и запуск с огнём различаются только окном P1 Button 1. Разность
выровненных потоков PCM выделяет оригинальный аркадный звук без заимствования
из другого порта. Результат пересчитывается оконным sinc-фильтром на 64 отвода
и хранится как беззнаковое 8-битное моно для General Sound. Это offline-этап
сборки; на Z80 преобразование звука не выполняется.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72


ROOT = Path(__file__).resolve().parents[2]
# Закреплённый MAME лежит В ПРОЕКТЕ: раньше путь указывал в %LOCALAPPDATA%\Temp,
# и после очистки временных файлов шаг захвата звука переставал собираться.
# Переменная RTYPE_MAME позволяет указать другой экземпляр, не трогая скрипт.
DEFAULT_MAME = Path(os.environ.get("RTYPE_MAME") or
                    ROOT / "Tools" / "mame0288" / "mame.exe")
DEFAULT_ROMPATH = ROOT / "Build" / "Arcade" / "MAME" / "roms"
LUA_SCRIPT = ROOT / "Source" / "Tools" / "mame_reference.lua"
DEFAULT_OUT = ROOT / "Build" / "Arcade" / "Audio" / "wave_shot"
ORIGINAL_AUDIO_OUT = ROOT / "Audio" / "Original"
CONVERTED_AUDIO_OUT = ROOT / "Audio" / "Converted"
ASSET_OUT = CONVERTED_AUDIO_OUT / "RTYPE_WAVE_SHOT_U8_11025.raw"
PREVIEW_OUT = ASSET_OUT.with_suffix(".wav")
MAME_SHA256 = "dcf8677fce188e8e2625d4a2928005565652930d3f85d930f5d49d939535b182"
MAME_RATE = 48_000
GS_RATE = 11_025
FIRE_START = 1250
FIRE_END = 1260
EXIT_FRAME = 1380
CAPTURE_SECONDS = 0.320
WAVE_MIN_CHARGE_FRAMES = 67
WAVE_APPEAR_DELAY = 2
MAME_SCREEN_STATE_DELAY = 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_ascii(path: Path) -> str:
    text = str(path.resolve().relative_to(ROOT.resolve()))
    text.encode("ascii")
    return text


def run_variant(name: str, out: Path, mame: Path, rompath: Path,
                *, firing: bool, fire_start: int, fire_end: int,
                exit_frame: int, fire_button: str,
                snap_frames: Sequence[int]) -> tuple[Path, list[str], str]:
    variant = out / name
    variant.mkdir(parents=True, exist_ok=True)
    ORIGINAL_AUDIO_OUT.mkdir(parents=True, exist_ok=True)
    wav_path = ORIGINAL_AUDIO_OUT / f"{name}.wav"
    environment = os.environ.copy()
    environment.update({
        "RTYPE_MAME_MODE": "stage1",
        "RTYPE_MAME_OUT": relative_ascii(variant),
        "RTYPE_MAME_SNAP_FRAMES": ",".join(
            str(frame) for frame in snap_frames
        ),
        "RTYPE_MAME_EXIT_FRAME": str(exit_frame),
        "RTYPE_MAME_DISABLE_PERIODIC_FIRE": "1",
        "RTYPE_MAME_FIRE_START": str(fire_start if firing else 0),
        "RTYPE_MAME_FIRE_END": str(fire_end if firing else 0),
        "RTYPE_MAME_FIRE_BUTTON": fire_button,
    })
    command = [
        str(mame), "rtype",
        "-rompath", str(rompath.resolve()),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-samplerate", str(MAME_RATE), "-wavwrite", relative_ascii(wav_path),
        "-nothrottle", "-noautoframeskip", "-frameskip", "0",
        "-seconds_to_run", str(math.ceil(exit_frame / 55.0) + 10),
        "-autoboot_script", str(LUA_SCRIPT.resolve()),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120, check=False,
    )
    log_path = variant / "mame_stdout.txt"
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode or not wav_path.is_file():
        raise RuntimeError(
            f"MAME audio variant {name} failed ({completed.returncode}); "
            f"see {log_path}")
    return wav_path, command, sha256(log_path)


def read_pcm(path: Path) -> tuple[int, int, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if width != 2:
        raise ValueError(f"expected signed 16-bit MAME WAV, got {width * 8}-bit")
    pcm = np.frombuffer(raw, dtype="<i2").reshape(-1, channels).astype(np.float64)
    return rate, channels, pcm / 32768.0


def sinc_resample(source: np.ndarray, input_rate: int, output_rate: int,
                  radius: int = 32) -> np.ndarray:
    """Моно-ресемплер с ограничением полосы и 64-отводным sinc-окном Ханна."""
    output_count = round(len(source) * output_rate / input_rate)
    positions = np.arange(output_count, dtype=np.float64) * input_rate / output_rate
    output = np.empty(output_count, dtype=np.float64)
    cutoff = min(1.0, output_rate / input_rate) * 0.94
    taps = np.arange(-radius + 1, radius + 1)
    for index, position in enumerate(positions):
        center = math.floor(position)
        sample_indices = center + taps
        distance = position - sample_indices
        weights = cutoff * np.sinc(cutoff * distance)
        window = 0.5 + 0.5 * np.cos(np.pi * distance / radius)
        window[np.abs(distance) >= radius] = 0.0
        weights *= window
        valid = (sample_indices >= 0) & (sample_indices < len(source))
        weights = weights[valid]
        if not len(weights) or abs(weights.sum()) < 1e-12:
            output[index] = 0.0
        else:
            output[index] = np.dot(source[sample_indices[valid]], weights) / weights.sum()
    return output


def write_preview(path: Path, pcm_u8: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(rate)
        wav.writeframes(pcm_u8)


def build(args: argparse.Namespace) -> dict[str, object]:
    mame = args.mame.resolve()
    if not mame.is_file() or sha256(mame) != MAME_SHA256:
        raise ValueError("pinned MAME 0.288 executable is missing or changed")
    m72.stage_mame(args.rompath, diagnostic_placeholders=True)
    args.out.mkdir(parents=True, exist_ok=True)

    # Короткое окно сохраняет прежний звуковой эталон и обычный снаряд.
    shot_frames = [args.fire_start + 3, args.fire_start + 4, args.exit_frame]
    baseline_path, baseline_command, baseline_log_hash = run_variant(
        "baseline", args.out, mame, args.rompath, firing=False,
        fire_start=args.fire_start, fire_end=args.fire_end,
        exit_frame=args.exit_frame, fire_button=args.fire_button,
        snap_frames=shot_frames)
    fire_path, fire_command, fire_log_hash = run_variant(
        "fire", args.out, mame, args.rompath, firing=True,
        fire_start=args.fire_start, fire_end=args.fire_end,
        exit_frame=args.exit_frame, fire_button=args.fire_button,
        snap_frames=shot_frames)

    # Отдельный запуск держит кнопку ровно 67 кадров. Он не участвует в
    # разности PCM и нужен только для воспроизводимых фаз Wave Cannon и
    # короткой вспышки у носа R-9.
    wave_fire_end = args.fire_start + WAVE_MIN_CHARGE_FRAMES
    wave_state_start = wave_fire_end + WAVE_APPEAR_DELAY
    wave_frames = list(range(wave_state_start, wave_state_start + 10))
    wave_frames.append(args.exit_frame)
    wave_path, wave_command, wave_log_hash = run_variant(
        "wave", args.out, mame, args.rompath, firing=True,
        fire_start=args.fire_start, fire_end=wave_fire_end,
        exit_frame=args.exit_frame, fire_button=args.fire_button,
        snap_frames=wave_frames)
    base_rate, base_channels, baseline = read_pcm(baseline_path)
    fire_rate, fire_channels, fire = read_pcm(fire_path)
    if (base_rate, base_channels, baseline.shape) != (
            fire_rate, fire_channels, fire.shape):
        raise ValueError("baseline/fire WAV formats or lengths differ")

    difference = fire - baseline
    mono = difference.mean(axis=1)
    active = np.flatnonzero(np.max(np.abs(difference), axis=1) > (1.0 / 32768.0))
    if not len(active):
        raise ValueError("fire input produced no deterministic audio difference")
    margin = round(base_rate * 0.015)
    start = max(0, int(active[0]) - margin)
    # Игровое событие может развести последующий тайминг команд FM/DAC даже в
    # остальных детерминированных запусках. Поэтому сохраняем документированное
    # ограниченное окно возле первого изменившегося отсчёта, чтобы случайно не
    # включить позднюю музыку или звук попадания в короткий звук оружия.
    capture_samples = round(args.capture_seconds * base_rate)
    stop = min(len(mono), int(active[-1]) + margin + 1,
               int(active[0]) + capture_samples + margin)
    isolated = mono[start:stop].copy()
    peak = float(np.max(np.abs(isolated)))
    if peak <= 0:
        raise ValueError("isolated fire PCM is silent")
    isolated *= 0.92 / peak
    fade = min(round(base_rate * 0.005), len(isolated) // 2)
    if fade:
        isolated[:fade] *= np.linspace(0.0, 1.0, fade, endpoint=False)
        isolated[-fade:] *= np.linspace(1.0, 0.0, fade, endpoint=False)

    resampled = np.clip(sinc_resample(isolated, base_rate, GS_RATE), -1.0, 1.0)
    pcm_u8 = np.rint(128.0 + resampled * 127.0).clip(0, 255).astype(np.uint8).tobytes()
    # GS может округлить длину вверх; чтение за концом должно дать тишину 0x80.
    padded_size = ((len(pcm_u8) + 64 + 511) // 512) * 512
    pcm_u8 += bytes([0x80]) * (padded_size - len(pcm_u8))

    ASSET_OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSET_OUT.write_bytes(pcm_u8)
    write_preview(PREVIEW_OUT, pcm_u8, GS_RATE)
    manifest = {
        "format": 1,
        "source": "deterministic difference of MAME baseline and one-fire runs",
        "mame": {"path": str(mame), "sha256": sha256(mame), "tag": m72.MAME_TAG},
        "input": {
            "fire_start_frame": args.fire_start,
            "fire_end_frame": args.fire_end,
            "fire_button": args.fire_button,
            "exit_frame": args.exit_frame,
            "player_shot_state_frames": [
                args.fire_start + 3,
                args.fire_start + 4,
            ],
            "wave_min_charge_frames": WAVE_MIN_CHARGE_FRAMES,
            "wave_state_frames": [
                wave_fire_end + WAVE_APPEAR_DELAY,
                wave_fire_end + WAVE_APPEAR_DELAY + 1,
            ],
            "wave_screen_frames": [
                wave_fire_end + WAVE_APPEAR_DELAY + MAME_SCREEN_STATE_DELAY,
                wave_fire_end + WAVE_APPEAR_DELAY + MAME_SCREEN_STATE_DELAY + 1,
            ],
            "wave_release_effect_state_frames": [
                wave_state_start + offset for offset in (0, 2, 4, 6)
            ],
            "screen_state_delay_frames": MAME_SCREEN_STATE_DELAY,
        },
        "baseline": {
            "path": str(baseline_path.resolve()), "sha256": sha256(baseline_path),
            "command": baseline_command, "stdout_sha256": baseline_log_hash,
        },
        "fire": {
            "path": str(fire_path.resolve()), "sha256": sha256(fire_path),
            "command": fire_command, "stdout_sha256": fire_log_hash,
        },
        "wave_reference": {
            "path": str(wave_path.resolve()), "sha256": sha256(wave_path),
            "command": wave_command, "stdout_sha256": wave_log_hash,
        },
        "isolation": {
            "source_rate": base_rate, "channels": base_channels,
            "first_changed_frame": int(active[0]),
            "last_changed_frame": int(active[-1]),
            "trim_start": start, "trim_stop": stop,
            "bounded_capture_seconds": args.capture_seconds,
            "peak_before_normalization": peak,
        },
        "conversion": {
            "method": "64-tap Hann-windowed sinc, cutoff 0.94 Nyquist",
            "rate": GS_RATE, "format": "unsigned 8-bit mono",
            "silence_padding": "0x80 to 512-byte boundary with 64-byte guard",
        },
        "outputs": {
            "raw": {"path": str(ASSET_OUT.resolve()), "size": len(pcm_u8),
                    "sha256": sha256(ASSET_OUT)},
            "preview_wav": {"path": str(PREVIEW_OUT.resolve()),
                            "sha256": sha256(PREVIEW_OUT)},
        },
    }
    manifest_path = args.out / "wave_shot_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"MAME WAV difference: samples {active[0]}..{active[-1]} at {base_rate} Hz")
    print(f"GS wave shot: {ASSET_OUT} ({len(pcm_u8)} bytes, sha256={sha256(ASSET_OUT)})")
    print(f"preview: {PREVIEW_OUT}")
    print(f"manifest: {manifest_path}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mame", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--rompath", type=Path, default=DEFAULT_ROMPATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fire-start", type=int, default=FIRE_START)
    parser.add_argument("--fire-end", type=int, default=FIRE_END)
    parser.add_argument("--fire-button", default="P1_BUTTON1")
    parser.add_argument("--exit-frame", type=int, default=EXIT_FRAME)
    parser.add_argument("--capture-seconds", type=float, default=CAPTURE_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not (0 <= args.fire_start < args.fire_end < args.exit_frame):
            raise ValueError("require 0 <= fire-start < fire-end < exit-frame")
        if args.fire_start + 4 >= args.fire_end:
            raise ValueError("fire window must contain the +3/+4 projectile snapshots")
        if (args.fire_start + WAVE_MIN_CHARGE_FRAMES + WAVE_APPEAR_DELAY
                + MAME_SCREEN_STATE_DELAY + 1 >= args.exit_frame):
            raise ValueError("exit frame must follow both Wave snapshots")
        if not (0.05 <= args.capture_seconds <= 2.0):
            raise ValueError("capture-seconds must be in range 0.05..2.0")
        build(args)
    except (FileNotFoundError, OSError, RuntimeError, ValueError,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
