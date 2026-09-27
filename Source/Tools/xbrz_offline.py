#!/usr/bin/env python3
"""Deterministic offline 384x256 -> 640x480 pixel-art conversion.

The conversion is intentionally a host build step, never an FT812 runtime
operation:

1. unmodified official xBRZ 1.9 expands the source by 6x;
2. Pillow Lanczos reduces the supersampled result to the exact target size;
3. the finished image can be packed as little-endian FT812 RGB565.

xBRZ is downloaded from its official SourceForge project, hash-checked, and
kept with its complete source archive and GPLv3 license next to the compiled
helper.  Generated image data is not xBRZ program code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Sequence

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = Path(__file__).with_name("xbrz_cli.cpp")
BUILD_WRAPPER = Path(__file__).with_name("build_xbrz_helper.cmd")
TOOL_ROOT = ROOT / "Build" / "Tools" / "xbrz-1.9"
SOURCE_ROOT = TOOL_ROOT / "source"
ARCHIVE = TOOL_ROOT / "xBRZ_1.9.zip"
EXE = TOOL_ROOT / "xbrz_cli.exe"
MANIFEST = TOOL_ROOT / "build_manifest.json"

XBRZ_VERSION = "1.9"
XBRZ_URL = (
    "https://master.dl.sourceforge.net/project/xbrz/xBRZ/"
    "xBRZ_1.9.zip?viasf=1"
)
XBRZ_ARCHIVE_SHA256 = (
    "b2dff73b3abd24a18a7cde78d5ff5ed8f0922296dce6ed734dce2264cd0a0fc9"
)
XBRZ_MEMBERS = {
    "License.txt",
    "xbrz.cpp",
    "xbrz.h",
    "xbrz_config.h",
    "xbrz_tools.h",
    "Changelog.txt",
}
DEFAULT_SOURCE_SIZE = (384, 256)
DEFAULT_TARGET_SIZE = (640, 480)
DEFAULT_FACTOR = 6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_archive() -> None:
    TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.is_file() and sha256(ARCHIVE) == XBRZ_ARCHIVE_SHA256:
        return
    request = urllib.request.Request(
        XBRZ_URL,
        headers={"User-Agent": "Wget/1.21.4 R-Type-VDAC2-build"},
    )
    partial = ARCHIVE.with_suffix(".zip.partial")
    with urllib.request.urlopen(request, timeout=60) as response, \
            partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = sha256(partial)
    if actual != XBRZ_ARCHIVE_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"xBRZ archive SHA-256 {actual}, expected {XBRZ_ARCHIVE_SHA256}")
    partial.replace(ARCHIVE)


def extract_source() -> None:
    download_archive()
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = set(archive.namelist())
        if names != XBRZ_MEMBERS:
            raise RuntimeError(
                f"unexpected xBRZ archive members: {sorted(names)}")
        for name in sorted(XBRZ_MEMBERS):
            target = SOURCE_ROOT / name
            data = archive.read(name)
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)


def find_vcvars64() -> Path:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        result = subprocess.run(
            [str(vswhere), "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            check=True, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        installation = result.stdout.strip()
        if installation:
            candidate = Path(installation) / "VC" / "Auxiliary" / "Build" / \
                "vcvars64.bat"
            if candidate.is_file():
                return candidate
    raise FileNotFoundError("Visual C++ vcvars64.bat not found")


def build_helper(force: bool = False) -> Path:
    extract_source()
    wrapper_hash = sha256(WRAPPER)
    build_wrapper_hash = sha256(BUILD_WRAPPER)
    driver_hash = sha256(Path(__file__))
    if not force and EXE.is_file() and MANIFEST.is_file():
        try:
            previous = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        if (previous.get("xbrz_archive_sha256") == XBRZ_ARCHIVE_SHA256 and
                previous.get("wrapper_sha256") == wrapper_hash and
                previous.get("build_wrapper_sha256") == build_wrapper_hash and
                previous.get("driver_sha256") == driver_hash and
                previous.get("executable_sha256") == sha256(EXE)):
            return EXE

    vcvars = find_vcvars64()
    TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        "cmd.exe", "/d", "/c", str(BUILD_WRAPPER.relative_to(ROOT)),
        "/nologo", "/std:c++23preview", "/O2", "/EHsc",
        f"/I{SOURCE_ROOT}", str(WRAPPER), str(SOURCE_ROOT / "xbrz.cpp"),
        f"/Fe:{EXE}", f"/Fo:{TOOL_ROOT}\\",
    ]
    environment = os.environ.copy()
    environment["RTYPE_VCVARS64"] = str(vcvars)
    completed = subprocess.run(
        command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False, env=environment,
    )
    if completed.returncode != 0 or not EXE.is_file():
        raise RuntimeError("xBRZ helper build failed:\n" + completed.stdout)

    build_data = {
        "format": 1,
        "xbrz_version": XBRZ_VERSION,
        "xbrz_url": XBRZ_URL,
        "xbrz_archive": str(ARCHIVE.relative_to(ROOT)),
        "xbrz_archive_sha256": XBRZ_ARCHIVE_SHA256,
        "wrapper": str(WRAPPER.relative_to(ROOT)),
        "wrapper_sha256": wrapper_hash,
        "build_wrapper": str(BUILD_WRAPPER.relative_to(ROOT)),
        "build_wrapper_sha256": build_wrapper_hash,
        "driver": str(Path(__file__).relative_to(ROOT)),
        "driver_sha256": driver_hash,
        "compiler_standard": "c++23preview",
        "executable": str(EXE.relative_to(ROOT)),
        "executable_sha256": sha256(EXE),
        "compiler_output": completed.stdout,
    }
    MANIFEST.write_text(
        json.dumps(build_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return EXE


def xbrz_expand(image: Image.Image, factor: int = DEFAULT_FACTOR) -> Image.Image:
    if factor < 2 or factor > 6:
        raise ValueError("xBRZ factor must be 2..6")
    source = image.convert("RGBA")
    width, height = source.size
    opaque = source.getchannel("A").getextrema() == (255, 255)
    helper = build_helper()
    with tempfile.TemporaryDirectory(prefix="rtype-xbrz-") as temp_name:
        temp = Path(temp_name)
        input_path = temp / "input.bgra"
        output_path = temp / "output.bgra"
        input_path.write_bytes(source.tobytes("raw", "BGRA"))
        completed = subprocess.run(
            [str(helper), str(input_path), str(width), str(height), str(factor),
             "rgb" if opaque else "argb", str(output_path)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("xBRZ conversion failed:\n" + completed.stdout)
        expected = width * height * factor * factor * 4
        data = output_path.read_bytes()
        if len(data) != expected:
            raise RuntimeError(
                f"xBRZ output is {len(data)} bytes, expected {expected}")
    return Image.frombytes(
        "RGBA", (width * factor, height * factor), data, "raw", "BGRA")


def upscale_image(image: Image.Image,
                  target_size: tuple[int, int] = DEFAULT_TARGET_SIZE,
                  factor: int = DEFAULT_FACTOR) -> Image.Image:
    expanded = xbrz_expand(image, factor)
    return expanded.resize(target_size, Image.Resampling.LANCZOS)


def pack_rgb565(image: Image.Image) -> bytes:
    if "A" in image.getbands() and image.getchannel("A").getextrema() != (255, 255):
        raise ValueError("RGB565 output requires a fully opaque image")
    rgb = image.convert("RGB")
    packed = bytearray(rgb.width * rgb.height * 2)
    pixels = (rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data")
              else rgb.getdata())
    for index, (red, green, blue) in enumerate(pixels):
        r5 = (red * 31 + 127) // 255
        g6 = (green * 63 + 127) // 255
        b5 = (blue * 31 + 127) // 255
        value = (r5 << 11) | (g6 << 5) | b5
        packed[index * 2] = value & 0xFF
        packed[index * 2 + 1] = value >> 8
    return bytes(packed)


def convert_file(input_path: Path, output_path: Path, rgb565_path: Path | None,
                 expected_source: tuple[int, int] | None,
                 target_size: tuple[int, int], factor: int) -> dict[str, object]:
    with Image.open(input_path) as loaded:
        source = loaded.convert("RGBA")
    if expected_source and source.size != expected_source:
        raise ValueError(
            f"source is {source.size[0]}x{source.size[1]}, expected "
            f"{expected_source[0]}x{expected_source[1]}")
    result = upscale_image(source, target_size, factor)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)

    outputs: dict[str, object] = {
        "png": {
            "path": str(output_path.resolve()),
            "size": output_path.stat().st_size,
            "sha256": sha256(output_path),
        }
    }
    if rgb565_path is not None:
        rgb565_path.parent.mkdir(parents=True, exist_ok=True)
        rgb565_path.write_bytes(pack_rgb565(result))
        outputs["rgb565"] = {
            "path": str(rgb565_path.resolve()),
            "size": rgb565_path.stat().st_size,
            "sha256": sha256(rgb565_path),
        }

    manifest = {
        "format": 1,
        "source": {
            "path": str(input_path.resolve()),
            "width": source.width,
            "height": source.height,
            "sha256": sha256(input_path),
        },
        "algorithm": {
            "stage1": "xBRZ 1.9",
            "factor": factor,
            "stage2": "Pillow Lanczos",
            "target_width": target_size[0],
            "target_height": target_size[1],
            "runtime_ft812_filter": "NEAREST (separate 640x480 -> 1024x768)",
        },
        "tool": json.loads(MANIFEST.read_text(encoding="utf-8")),
        "outputs": outputs,
    }
    sidecar = output_path.with_suffix(output_path.suffix + ".json")
    sidecar.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def size_arg(text: str) -> tuple[int, int]:
    try:
        width_text, height_text = text.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (ValueError, AttributeError) as error:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from error
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size must be positive")
    return width, height


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="download and compile xBRZ helper")
    build.add_argument("--force", action="store_true")

    convert = subparsers.add_parser("convert", help="convert one PNG offline")
    convert.add_argument("input", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--rgb565", type=Path)
    convert.add_argument("--source-size", type=size_arg,
                         default=DEFAULT_SOURCE_SIZE)
    convert.add_argument("--target-size", type=size_arg,
                         default=DEFAULT_TARGET_SIZE)
    convert.add_argument("--factor", type=int, default=DEFAULT_FACTOR,
                         choices=range(2, 7))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            helper = build_helper(args.force)
            print(f"xBRZ {XBRZ_VERSION} helper OK: {helper}")
            print(f"SHA-256: {sha256(helper)}")
        else:
            manifest = convert_file(
                args.input, args.output, args.rgb565, args.source_size,
                args.target_size, args.factor)
            print(
                f"offline upscale OK: {manifest['source']['width']}x"
                f"{manifest['source']['height']} -> "
                f"{manifest['algorithm']['target_width']}x"
                f"{manifest['algorithm']['target_height']}")
            for name, item in manifest["outputs"].items():
                print(f"{name}: {item['path']} ({item['sha256']})")
    except (FileNotFoundError, OSError, RuntimeError, ValueError,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
