#!/usr/bin/env python3
"""Run pinned MAME reference capture and render its indexed frames to PNG.

The Lua side captures native 384x256 palette indices and runtime memory.  This
host wrapper provides a hard timeout, logs the exact command/version/hash, and
creates explicitly separate reference and port views:

* logical-nearest 640x480, retained only as a diagnostic comparison;
* logical 640x480, precomputed with xBRZ 1.9 6x then Lanczos;
* physical 1024x768, the exact FT812 NEAREST 8/5 presentation of the stored
  high-quality logical image.

These images are reference evidence.  They are not embedded as game assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72
import xbrz_offline as upscale


ROOT = Path(__file__).resolve().parents[2]
# Закреплённый MAME лежит В ПРОЕКТЕ (см. mame_audio_capture.py): путь во временную
# папку не переживал очистку %TEMP%. RTYPE_MAME переопределяет расположение.
DEFAULT_MAME = Path(os.environ.get("RTYPE_MAME") or
                    ROOT / "Tools" / "mame0288" / "mame.exe")
DEFAULT_ROMPATH = ROOT / "Build" / "Arcade" / "MAME" / "roms"
LUA_SCRIPT = ROOT / "Source" / "Tools" / "mame_reference.lua"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def load_palette(path: Path) -> list[tuple[int, int, int, int]]:
    data = path.read_bytes()
    if len(data) % 4:
        raise ValueError(f"invalid palette size: {path}")
    colors: list[tuple[int, int, int, int]] = []
    for offset in range(0, len(data), 4):
        value = int.from_bytes(data[offset:offset + 4], "little")
        colors.append(((value >> 16) & 0xFF, (value >> 8) & 0xFF,
                       value & 0xFF, (value >> 24) & 0xFF))
    return colors


def render_frame(pixel_path: Path, *, native_only: bool = False) -> dict[str, object]:
    match = re.fullmatch(r"frame_(\d{6})_pixels_u32le\.bin", pixel_path.name)
    if not match:
        raise ValueError(f"unexpected frame filename: {pixel_path.name}")
    frame = int(match.group(1))
    prefix = pixel_path.with_name(f"frame_{frame:06d}")
    info = parse_key_values(prefix.with_name(prefix.name + "_pixels.txt"))
    width, height = int(info["width"]), int(info["height"])
    raw = pixel_path.read_bytes()
    if len(raw) != width * height * 4:
        raise ValueError(
            f"{pixel_path.name}: {len(raw)} bytes, expected {width * height * 4}")
    palette_path = prefix.with_name(prefix.name + "_palette_argb8888_le.bin")
    colors = load_palette(palette_path)

    rgba = bytearray(width * height * 4)
    max_index = 0
    direct_rgb = False
    for pixel in range(width * height):
        value = int.from_bytes(raw[pixel * 4:pixel * 4 + 4], "little")
        if value < len(colors):
            red, green, blue, alpha = colors[value]
            max_index = max(max_index, value)
        else:
            # Direct RGB screens are also supported by the MAME API, although
            # R-Type is expected to be indexed.
            direct_rgb = True
            red, green, blue, alpha = ((value >> 16) & 0xFF,
                                       (value >> 8) & 0xFF,
                                       value & 0xFF, 0xFF)
        rgba[pixel * 4:pixel * 4 + 4] = bytes((red, green, blue, alpha))

    native = Image.frombytes("RGBA", (width, height), bytes(rgba)).convert("RGB")
    outputs = {
        "native": prefix.with_name(prefix.name + "_native.png"),
    }
    native.save(outputs["native"])
    if not native_only:
        logical_nearest = native.resize((640, 480), Image.Resampling.NEAREST)
        logical = upscale.upscale_image(native.convert("RGBA"), (640, 480), factor=6)
        physical = logical.resize((1024, 768), Image.Resampling.NEAREST)
        outputs.update({
            "logical_nearest_reference": prefix.with_name(
                prefix.name + "_logical_640x480_nearest_reference.png"),
            "logical": prefix.with_name(
                prefix.name + "_logical_640x480_xbrz6_lanczos.png"),
            "physical": prefix.with_name(
                prefix.name + "_physical_1024x768_nearest.png"),
        })
        logical_nearest.save(outputs["logical_nearest_reference"])
        logical.save(outputs["logical"])
        physical.save(outputs["physical"])
    frame_memory = {}
    expected_sizes = {
        "workram.bin": 0x4000,
        "spriteram.bin": 0x400,
        "palette0.bin": 0xC00,
        "palette1.bin": 0xC00,
        "vram0.bin": 0x4000,
        "vram1.bin": 0x4000,
    }
    for suffix, expected_size in expected_sizes.items():
        path = prefix.with_name(prefix.name + "_" + suffix)
        if not path.is_file() or path.stat().st_size != expected_size:
            actual = path.stat().st_size if path.is_file() else "missing"
            raise ValueError(
                f"{path.name}: size {actual}, expected {expected_size}")
        frame_memory[suffix] = {
            "path": str(path.relative_to(ROOT)),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    return {
        "frame": frame,
        "native_size": [width, height],
        "max_palette_index": max_index,
        "direct_rgb": direct_rgb,
        "source_sha256": sha256(pixel_path),
        "palette_sha256": sha256(palette_path),
        "outputs": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in outputs.items()
        },
        "runtime_memory": frame_memory,
    }


def relative_ascii_path(path: Path) -> str:
    """MAME's embedded Lua io.open rejects the Cyrillic absolute user path."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError("capture output must be inside the project") from error
    text = str(relative)
    try:
        text.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("capture path components must be ASCII for MAME Lua") from error
    return text


def run_capture(args: argparse.Namespace) -> dict[str, object]:
    mame = args.mame.resolve()
    if not mame.is_file():
        raise FileNotFoundError(f"MAME executable not found: {mame}")
    if sha256(mame).lower() != args.mame_sha256.lower():
        raise ValueError(f"unexpected MAME SHA-256: {sha256(mame)}")
    m72.stage_mame(args.rompath, diagnostic_placeholders=True)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    out_for_lua = relative_ascii_path(out)
    frames = sorted(set(args.frames + [args.exit_frame]))
    environment = os.environ.copy()
    environment.update({
        "RTYPE_MAME_MODE": args.mode,
        "RTYPE_MAME_OUT": out_for_lua,
        "RTYPE_MAME_SNAP_FRAMES": ",".join(str(frame) for frame in frames),
        "RTYPE_MAME_EXIT_FRAME": str(args.exit_frame),
    })
    if args.disable_periodic_fire:
        environment["RTYPE_MAME_DISABLE_PERIODIC_FIRE"] = "1"
    if args.disable_stage_autoplay:
        environment["RTYPE_MAME_DISABLE_STAGE_AUTOPLAY"] = "1"
    if args.fire_start is not None and args.fire_end is not None:
        environment["RTYPE_MAME_FIRE_START"] = str(args.fire_start)
        environment["RTYPE_MAME_FIRE_END"] = str(args.fire_end)
        environment["RTYPE_MAME_FIRE_BUTTON"] = args.fire_button
    if args.move_start is not None and args.move_end is not None:
        environment["RTYPE_MAME_MOVE_START"] = str(args.move_start)
        environment["RTYPE_MAME_MOVE_END"] = str(args.move_end)
        environment["RTYPE_MAME_MOVE_BUTTON"] = args.move_button
    if args.vram_writes or args.vram_pc:
        environment["RTYPE_MAME_LOG_VRAM_WRITES"] = "1"
    if args.vram_pc:
        environment["RTYPE_MAME_LOG_VRAM_PC"] = "1"
    if args.palette_writes:
        environment["RTYPE_MAME_LOG_PALETTE_WRITES"] = "1"
    if args.sprite_writes:
        environment["RTYPE_MAME_LOG_SPRITERAM_WRITES"] = "1"
    if args.player_writes:
        environment["RTYPE_MAME_LOG_PLAYER_WRITES"] = "1"
    if args.object_writes:
        environment["RTYPE_MAME_LOG_OBJECT_WRITES"] = "1"
    if args.scroll_state_writes:
        environment["RTYPE_MAME_LOG_SCROLL_STATE_WRITES"] = "1"
    if args.rng_calls:
        environment["RTYPE_MAME_LOG_RNG_CALLS"] = "1"
    if args.invincible:
        environment["RTYPE_MAME_INVINCIBLE"] = "1"
    if args.credits_frame is not None:
        environment["RTYPE_MAME_CREDITS_FRAME"] = str(args.credits_frame)
    if args.credits_event:
        environment["RTYPE_MAME_CREDITS_EVENT"] = "1"
    if args.director_log:
        environment["RTYPE_MAME_LOG_DIRECTOR"] = "1"
    if args.sound_log:
        environment["RTYPE_MAME_LOG_SOUND"] = "1"
    safety_seconds = math.ceil(args.exit_frame / 55.0) + 10
    command = [
        str(mame), "rtype",
        "-rompath", str(args.rompath.resolve()),
        "-skip_gameinfo", "-video", "none", "-sound", "none",
        "-nothrottle", "-noautoframeskip", "-frameskip", "0",
        "-seconds_to_run", str(safety_seconds),
        "-autoboot_script", str(LUA_SCRIPT.resolve()),
    ]
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=args.timeout, check=False,
    )
    log_path = out / "mame_stdout.txt"
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"MAME returned {completed.returncode}; see {log_path}")
    if f"RUNTIME_DUMP frame={args.exit_frame}" not in completed.stdout:
        raise RuntimeError(
            f"MAME exited without requested runtime dump; see {log_path}")
    if "RTYPE_LUA_ERROR" in completed.stdout:
        raise RuntimeError(f"Lua capture error; see {log_path}")

    rendered = [render_frame(path, native_only=args.native_only) for path in
                sorted(out.glob("frame_*_pixels_u32le.bin"))]
    captured_frames = [item["frame"] for item in rendered]
    if captured_frames != frames:
        raise RuntimeError(
            f"captured frames {captured_frames}, requested {frames}")

    runtime_files = {}
    for name in ("workram.bin", "spriteram.bin", "palette0.bin", "palette1.bin",
                 "vram0.bin", "vram1.bin", "soundram.bin",
                 "palette_argb8888_le.bin", "scroll_writes.csv", "runtime.txt"):
        path = out / name
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.vram_writes:
        path = out / "vram_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.palette_writes:
        path = out / "palette_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.sprite_writes:
        path = out / "spriteram_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.player_writes:
        path = out / "player_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.object_writes:
        path = out / "object_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.scroll_state_writes:
        path = out / "scroll_state_writes.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    if args.rng_calls:
        path = out / "rng_calls.csv"
        if not path.is_file():
            raise RuntimeError(f"runtime output missing: {path}")
        runtime_files[path.name] = {
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }

    manifest = {
        "format": 1,
        "mode": args.mode,
        "invincible": args.invincible,
        "credits_frame": args.credits_frame,
        "credits_event": args.credits_event,
        "director_log": args.director_log,
        "sound_log": args.sound_log,
        "set": "rtype",
        "mame": {
            "version": "0.288",
            "path": str(mame),
            "size": mame.stat().st_size,
            "sha256": sha256(mame),
        },
        "command": command,
        "input_policy": {
            "disable_periodic_fire": args.disable_periodic_fire,
            "disable_stage_autoplay": args.disable_stage_autoplay,
            "fire_start": args.fire_start,
            "fire_end": args.fire_end,
            "fire_button": args.fire_button,
            "move_start": args.move_start,
            "move_end": args.move_end,
            "move_button": args.move_button,
        },
        "frames": rendered,
        "runtime_files": runtime_files,
        "known_audit_boundary": (
            "game ROMs match; two M72 PROMs and three PLDs are zero MAME-only "
            "placeholders with intentionally wrong checksums"),
        "presentation_pipeline": {
            "native": [384, 256],
            "offline_stage": "xBRZ 1.9 6x then Pillow Lanczos to 640x480",
            "stored_virtual": [640, 480],
            "runtime_stage": "FT812 NEAREST 8/5",
            "physical": [1024, 768],
            "xbrz_archive_sha256": upscale.XBRZ_ARCHIVE_SHA256,
        },
        "stdout_sha256": sha256(log_path),
    }
    manifest_path = out / "capture_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return manifest


def parse_frames(text: str) -> list[int]:
    values = [int(item) for item in text.split(",") if item.strip()]
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("frames must be positive comma-separated integers")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inventory", "attract", "stage1"),
                        default="stage1")
    parser.add_argument("--frames", type=parse_frames,
                        default=parse_frames("1,60,120,180,240,300,420,600,900"))
    parser.add_argument("--exit-frame", type=int, default=900)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "Build" / "Arcade" / "MAME" / "stage1_ref")
    parser.add_argument("--rompath", type=Path, default=DEFAULT_ROMPATH)
    parser.add_argument("--mame", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--mame-sha256",
                        default="dcf8677fce188e8e2625d4a2928005565652930d3f85d930f5d49d939535b182")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--vram-writes", action="store_true",
                        help="record both M72 tilemap write streams")
    parser.add_argument("--vram-pc", action="store_true",
                        help="record tilemap writes with the executing V30 PC")
    parser.add_argument("--palette-writes", action="store_true",
                        help="record both M72 palette RAM write streams")
    parser.add_argument("--sprite-writes", action="store_true",
                        help="record M72 sprite RAM write stream")
    parser.add_argument("--player-writes", action="store_true",
                        help="record writes to the first player state block with V30 PC")
    parser.add_argument("--object-writes", action="store_true",
                        help="record writes to the M72 object pool with V30 PC")
    parser.add_argument("--scroll-state-writes", action="store_true",
                        help="record M72 scroll state writes with V30 PC")
    parser.add_argument("--rng-calls", action="store_true",
                        help="record exact callers of ROM RNG `$EDE9`")
    parser.add_argument("--disable-periodic-fire", action="store_true",
                        help="do not apply the capture script's periodic P1 fire")
    parser.add_argument("--disable-stage-autoplay", action="store_true",
                        help="disable both scripted stage movement and periodic fire")
    parser.add_argument("--fire-start", type=int,
                        help="first reference-capture frame with held fire")
    parser.add_argument("--fire-end", type=int,
                        help="first frame after held fire")
    parser.add_argument("--fire-button", default="P1_BUTTON1",
                        choices=("P1_BUTTON1", "P1_BUTTON2", "P1_BUTTON3", "P1_BUTTON4"))
    parser.add_argument("--move-start", type=int,
                        help="first reference-capture frame with held movement")
    parser.add_argument("--move-end", type=int,
                        help="first frame after held movement")
    parser.add_argument("--move-button",
                        choices=("P1_UP", "P1_DOWN", "P1_LEFT", "P1_RIGHT"),
                        default="P1_DOWN")
    parser.add_argument("--invincible", action="store_true",
                        help="capture-only rtype World invincibility patch")
    parser.add_argument("--sound-log", action="store_true",
                        help="писать команды звуковой защёлки (порт I/O $00) в sound_writes.csv")
    parser.add_argument("--director-log", action="store_true",
                        help="писать состояние директора каждый кадр в director.csv "
                             "(последовательность экранов аттракта)")
    parser.add_argument("--credits-event", action="store_true",
                        help="событие этапа 1 создаёт объект конечных титров "
                             "(правка образа 1B9DA=BC, как в сборке порта)")
    parser.add_argument("--credits-frame", type=int,
                        help="кадр диагностического прыжка в конечные титры "
                             "(обработчик директора $40000 → $EEB5, ROM не меняется)")
    parser.add_argument("--native-only", action="store_true",
                        help="render native PNG only; skip expensive xBRZ reference views")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.exit_frame <= 0:
        raise SystemExit("--exit-frame must be positive")
    if (args.move_start is None) != (args.move_end is None):
        raise SystemExit("--move-start and --move-end must be used together")
    if args.move_start is not None and not 0 <= args.move_start < args.move_end:
        raise SystemExit("movement window must satisfy 0 <= start < end")
    if (args.fire_start is None) != (args.fire_end is None):
        raise SystemExit("--fire-start and --fire-end must be used together")
    if args.fire_start is not None and not 0 <= args.fire_start < args.fire_end:
        raise SystemExit("fire window must satisfy 0 <= start < end")
    if args.disable_periodic_fire and args.fire_start is not None:
        raise SystemExit("explicit fire window conflicts with --disable-periodic-fire")
    try:
        manifest = run_capture(args)
    except (FileNotFoundError, ValueError, RuntimeError,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"MAME reference OK: {len(manifest['frames'])} frames, "
          f"runtime dump at frame {args.exit_frame}")
    print(f"capture: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
