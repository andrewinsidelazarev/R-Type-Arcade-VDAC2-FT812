#!/usr/bin/env python3
"""Собрать управляемый PCM звука накопления Beam из команды M72 `$32`.

Входной WAV снят в полной тишине прямой записью `$32` в soundlatch. Начало
совмещается с первым отсчётом мгновенной команды `$30`, поэтому сохраняется
реальная задержка Z80/YM2151 между `$32` и слышимым звуком. Ресемплинг выполняет
тот же 64-отводный оконный sinc, что и остальные PCM проекта.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mame_audio_capture import read_pcm, sinc_resample, write_preview


DEFAULT_REFERENCE = ROOT / "Build" / "Arcade" / "Audio" / "scan" / "cmd_30.wav"
DEFAULT_CAPTURE = ROOT / "Build" / "Arcade" / "Audio" / "charge" / "cmd_32_hold.wav"
DEFAULT_OUTPUT = ROOT / "Audio" / "Converted" / "RTYPE_SFX_CHARGE_U8_22050.raw"
OUTPUT_RATE = 22_050


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_nonzero(path: Path) -> tuple[int, int]:
    rate, channels, pcm = read_pcm(path)
    active = np.flatnonzero(np.max(np.abs(pcm), axis=1) > 0.0)
    if not len(active):
        raise ValueError(f"в эталоне нет звука: {path}")
    return rate, int(active[0])


def build(reference: Path, capture: Path, output: Path) -> dict[str, object]:
    reference_rate, command_sample = first_nonzero(reference)
    rate, channels, pcm = read_pcm(capture)
    if rate != reference_rate or channels != 1:
        raise ValueError("ожидался mono PCM16 MAME с общей частотой")
    if command_sample >= len(pcm):
        raise ValueError("capture короче точки подачи команды")
    mono = pcm[command_sample:, 0]
    resampled = sinc_resample(mono, rate, OUTPUT_RATE)
    peak = float(np.max(np.abs(resampled)))
    if peak <= 0:
        raise ValueError("команда $32 не дала звука")
    # Существующие `$30/$31` PCM нормализованы перед квантованием; применяем
    # ту же схему, иначе `$32` оказался бы примерно в восемь раз тише их.
    normalized = resampled / peak
    pcm_u8 = np.rint(128.0 + np.clip(normalized, -1.0, 1.0) * 126.0)
    raw = pcm_u8.clip(0, 255).astype(np.uint8).tobytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    preview = output.with_suffix(".wav")
    write_preview(preview, raw, OUTPUT_RATE)
    active = np.flatnonzero(np.abs(mono) > 0.0)
    manifest = {
        "command": "0x32",
        "stop_command": "0x33",
        "source": str(capture.relative_to(ROOT)),
        "source_sha256": sha256(capture),
        "command_reference": str(reference.relative_to(ROOT)),
        "command_sample_48000": command_sample,
        "audible_delay_seconds": float(active[0] / rate),
        "rate": OUTPUT_RATE,
        "samples": len(raw),
        "duration_seconds": len(raw) / OUTPUT_RATE,
        "raw_sha256": sha256(output),
    }
    manifest_path = output.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build(args.reference, args.capture, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
