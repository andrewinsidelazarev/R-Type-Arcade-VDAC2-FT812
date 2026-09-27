#!/usr/bin/env python3
"""Render the exact two-YM2203 TSFM stream to a lightweight runtime asset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.tsfm import DEFAULT_STREAM, FRAME_RATE, TsfmEmulator


DEFAULT_OUTPUT = ROOT / "Audio" / "Converted" / "RTYPE_STAGE1_TSFM_S16_44100.raw"


def render(output: Path, loops: int = 2) -> dict[str, object]:
    emulator = TsfmEmulator(DEFAULT_STREAM)
    captured: list[np.ndarray] = []
    for cycle in range(loops):
        for second_start in range(0, emulator.frame_count, FRAME_RATE):
            frame_count = min(FRAME_RATE, emulator.frame_count - second_start)
            native = np.concatenate(list(emulator.frames(frame_count)))
            block = resample_poly(native.astype(np.float64), 441, 4375,
                                  window=("kaiser", 8.6))
            if cycle == loops - 1:
                captured.append(block.astype(np.float32))
        print(f"TSFM emulation pass {cycle + 1}/{loops}", flush=True)
    audio = np.concatenate(captured)
    peak = float(np.max(np.abs(audio))) or 1.0
    pcm = np.rint(np.clip(audio * (30_000.0 / peak), -32768, 32767)).astype("<i2")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pcm.tobytes())
    wav_path = output.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44_100)
        wav.writeframes(pcm.tobytes())
    metadata = {
        "source": str(DEFAULT_STREAM.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(DEFAULT_STREAM.read_bytes()).hexdigest(),
        "renderer": "ymfm-py: two YM2203 at 1.75 MHz",
        "stream_frames": emulator.frame_count,
        "frame_rate": FRAME_RATE,
        "sample_rate": 44_100,
        "samples": int(pcm.size),
        "duration_seconds": pcm.size / 44_100,
        "normalization_source_peak": peak,
        "pcm_sha256": hashlib.sha256(pcm.tobytes()).hexdigest(),
        "preroll_loops": max(0, loops - 1),
    }
    output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--loops", type=int, default=2)
    args = parser.parse_args()
    if args.loops < 1:
        parser.error("--loops must be positive")
    metadata = render(args.output, args.loops)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
