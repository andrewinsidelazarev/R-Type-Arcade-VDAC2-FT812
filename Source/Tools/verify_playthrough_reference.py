#!/usr/bin/env python3
"""Привязать эталонное прохождение YouTube к точным кадрам MAME.

Видео не используется как источник игровой логики: оно только проверяет уже
перенесённый из ROM Python-runtime.  Сначала выполняется дешёвый поиск в
уменьшенном потоке с заданной частотой, затем найденное окно проверяется на
исходной частоте видео.  Результат сохраняется в JSON и пригоден для
последующего автоматического frame-diff, без ручного выбора таймкода.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "Reference" / "Playthrough" / "9qXHicrtLJU"
DEFAULT_VIDEO = REFERENCE_DIR / "9qXHicrtLJU.299.mp4"
DEFAULT_ANCHOR = (
    ROOT / "Build" / "Arcade" / "MAME" / "vram_delta_probe" /
    "frame_000898_native.png"
)
DEFAULT_REPORT = REFERENCE_DIR / "frame_alignment.json"
THUMBNAIL_SIZE = (96, 64)


@dataclass(frozen=True)
class Candidate:
    frame: int
    seconds: float
    mean_absolute_error: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _target_pixels(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image = image.resize(THUMBNAIL_SIZE, Image.Resampling.BOX)
    return np.asarray(image, dtype=np.int16)


def _raw_frames(video: Path, fps: float, *, start: float = 0.0,
                duration: float | None = None):
    width, height = THUMBNAIL_SIZE
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error"]
    if start:
        command += ["-ss", f"{start:.9f}"]
    command += ["-i", str(video)]
    if duration is not None:
        command += ["-t", f"{duration:.9f}"]
    command += [
        "-vf", f"fps={fps:.12g},scale={width}:{height}:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    assert process.stdout is not None
    frame_bytes = width * height * 3
    try:
        index = 0
        while True:
            data = process.stdout.read(frame_bytes)
            if not data:
                break
            if len(data) != frame_bytes:
                raise EOFError("ffmpeg вернул оборванный raw frame")
            yield index, np.frombuffer(data, dtype=np.uint8).reshape(
                height, width, 3)
            index += 1
    finally:
        process.stdout.close()
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, command)


def _best_candidates(video: Path, target: np.ndarray, fps: float,
                     *, start: float = 0.0, duration: float | None = None,
                     keep: int = 8) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, frame in _raw_frames(
            video, fps, start=start, duration=duration):
        error = float(np.mean(np.abs(frame.astype(np.int16) - target)))
        absolute_seconds = start + index / fps
        candidate = Candidate(
            frame=round(absolute_seconds * fps),
            seconds=absolute_seconds,
            mean_absolute_error=error,
        )
        candidates.append(candidate)
        candidates.sort(key=lambda item: item.mean_absolute_error)
        del candidates[keep:]
    return candidates


def align(video: Path, anchor: Path, scan_fps: float,
          source_fps: float) -> dict[str, object]:
    target = _target_pixels(anchor)
    coarse = _best_candidates(video, target, scan_fps)
    if not coarse:
        raise ValueError("видео не содержит кадров")
    window_start = max(0.0, coarse[0].seconds - 2.0)
    fine = _best_candidates(
        video, target, source_fps, start=window_start, duration=4.0,
        keep=16)
    best = fine[0]
    return {
        "video": str(video.relative_to(ROOT)),
        "video_sha256": sha256(video),
        "anchor": str(anchor.relative_to(ROOT)),
        "anchor_sha256": sha256(anchor),
        "scan_fps": scan_fps,
        "source_fps": source_fps,
        "best_video_frame": round(best.seconds * source_fps),
        "best_video_seconds": best.seconds,
        "mean_absolute_error_96x64_rgb": best.mean_absolute_error,
        "coarse_candidates": [item.__dict__ for item in coarse],
        "fine_candidates": [item.__dict__ for item in fine],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--anchor", type=Path, default=DEFAULT_ANCHOR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scan-fps", type=float, default=1.0)
    parser.add_argument("--source-fps", type=float, default=55.0)
    args = parser.parse_args()
    report = align(args.video, args.anchor, args.scan_fps, args.source_fps)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
