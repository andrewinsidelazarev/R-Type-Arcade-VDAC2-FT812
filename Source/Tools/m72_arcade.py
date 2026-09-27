#!/usr/bin/env python3
"""Проверка и детерминированное извлечение данных arcade R-Type (Irem M72).

Единственный источник игровых байтов — ``Arcade/rtype``.  Схема размещения ROM
и planar gfx layout зафиксированы по официальному MAME 0.288:

* src/mame/irem/m72.cpp, tag mame0288;
* src/mame/irem/m72_v.cpp, tag mame0288;
* src/emu/drawgfx.cpp, tag mame0288 (MSB-first ``readbit``).

Команды:

``verify``
    Проверить размер, SHA-1 и SHA-256 каждого предоставленного ROM.

``decode``
    Собрать MAME regions, декодировать 4bpp 8x8 tiles и 16x16 sprites,
    сохранить packed index data и диагностические PNG-atlas.

``stage-mame``
    Создать отдельный каталог ``rtype`` с MAME-именами файлов.  Опциональные
    нулевые PROM/PLD placeholders нужны только для диагностического запуска
    при отсутствии общих M72 chips; они всегда явно помечаются как неверные.

Скрипт ничего не скачивает и никогда не изменяет исходный ROM-каталог.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
ROM_DIR = ROOT / "Arcade" / "rtype"
CONVERTED_DIR = ROOT / "Assets" / "Converted" / "Arcade"
BUILD_DIR = ROOT / "Build" / "Arcade"

MAME_TAG = "mame0288"
MAME_COMMIT = "2c38dc6e555e17560bbf6f5531c3e86cf8570f54"


@dataclass(frozen=True)
class RomSpec:
    local_name: str
    mame_name: str
    size: int
    sha1: str
    sha256: str
    region: str


ROMS: tuple[RomSpec, ...] = (
    RomSpec("rt_b-a0.3c", "rt_b-a0.ic20", 0x8000,
            "687061ecade2ebd0bd1343c9c4a831791853f79c",
            "2c4f6575d4efcc53368ef90b5a748552b3b6191043fd58df6248ecdb5991327e", "tiles0"),
    RomSpec("rt_b-a1.3d", "rt_b-a1.ic22", 0x8000,
            "130bf6af521f13247a739a95eab4bdaa24b2ac10",
            "6e125fe23c78836f3d90f687d653d53543ccbe09273eb8d282ea7d48494ddd3a", "tiles0"),
    RomSpec("rt_b-a2.3a", "rt_b-a2.ic20", 0x8000,
            "95c3b64f50e6f673b2bf9b40642c152da5009d25",
            "43cab5d36600a33dd7aa648fcaeaab79fa5a2f3bf786f6c9827ee9c04a87a864", "tiles0"),
    RomSpec("rt_b-a3.3e", "rt_b-a3.ic23", 0x8000,
            "9529ecdedd30e2a0400fb1083117992cc18b5158",
            "9293d850e023e3a7e5f25f505c61c255066e00166efb855cb2145b92bbd2b777", "tiles0"),
    RomSpec("rt_b-b0.3j", "rt_b-b0.ic26", 0x8000,
            "5b390770e56ba2d35e108534d7eda8dca996fdf7",
            "37d3947528bf1b575175b6c2829127a3ab6ec6a9d151e208b8665477bf8b7495", "tiles1"),
    RomSpec("rt_b-b1.3k", "rt_b-b1.ic27", 0x8000,
            "700905a3e9661e0874939f54da2909e1396ce596",
            "3137e05b9639b16c29edcdc8ec23fbdded3547a8188931cb168160768f671e92", "tiles1"),
    RomSpec("rt_b-b2.3h", "rt_b-b2.ic25", 0x8000,
            "14222eaa3e67e5a7f80eafcf22bac4eb2d485a9a",
            "84fc12dc8d42254641df7ba80ff7e0d3b8cbbe70a95a85aca1284348c2b8d72f", "tiles1"),
    RomSpec("rt_b-b3.3f", "rt_b-b3.ic24", 0x8000,
            "e2683d0e7415f3abd147e518bf6c87e44744cd4f",
            "c2273b91710f3f47d20dec45f0c78efb182bc13752e3e88d094c9c4c95ba88e8", "tiles1"),
    RomSpec("rt_r-00.1h", "rt_r-00.1h", 0x10000,
            "1e3bc498861946278a0b1fe24259f5d224e265d7",
            "49ebe76b7e41773be1466577471ac9eab8f259ab92da04ef89cfafe9945d32d0", "sprites"),
    RomSpec("rt_r-01.1j", "rt_r-01.1j", 0x8000,
            "6741eb7f2d9d985b5a89eefc73ea44c3e38de6f7",
            "920f2861ca7d10a00b2b2d6b0c8a2d00497311142094bc831ba341e6112f4fe4", "sprites"),
    RomSpec("rt_r-10.1k", "rt_r-10.1k", 0x10000,
            "d2873d05aa3b257e7699c188880ac3daad672fa5",
            "fe0e69e84902a30abf751944aa1e2927dbdca14db0d6f7d2ae242bf245366e26", "sprites"),
    RomSpec("rt_r-11.1l", "rt_r-11.1l", 0x8000,
            "5239a97222212ac9c019177771cb2b5096b7bc17",
            "caac2be5f38ee6a3d7909d9b0046305bd22bcaabd5d4e256331063999781fdb3", "sprites"),
    RomSpec("rt_r-20.3h", "rt_r-20.3h", 0x10000,
            "01cf0a60f47fa5e2ed430a3f075e69e6cb762a48",
            "3c6cc71c5d8040ce879cf67359290060d77e6cb10c7b53158e4006818634e01b", "sprites"),
    RomSpec("rt_r-21.3j", "rt_r-21.3j", 0x8000,
            "7e55a9a11fcd989db39bce6be48821b747c7d97f",
            "e186153a0249131bc69a31e99f8537ef75312ef3d0582399e384947c0e1bff9d", "sprites"),
    RomSpec("rt_r-30.3k", "rt_r-30.3k", 0x10000,
            "60a394ab53afdcbbf9e88083b8dbe8c897170d77",
            "b942284603ac803026088c45b4d02908204cc96b4e56d3fa9430ec6f1032ce1f", "sprites"),
    RomSpec("rt_r-31.3l", "rt_r-31.3l", 0x8000,
            "b5467d1f22f6e5f90c5d8a8ac2d55974f287d589",
            "efb9469173d9dfb12983b05b76b41d8c5196a0cf432dff68f3afdd0b1e69242b", "sprites"),
    RomSpec("rt_r-h0-b.1b", "rt_r-h0-b.1b", 0x10000,
            "0b9d5474bc5963224923126cf84d74a39b8270cc",
            "b6fcea2b6e6aaa8a55a614dcf65b514e0222faf5eaf8e52bce4bc79b761beeac", "maincpu"),
    RomSpec("rt_r-h1-b.1c", "rt_r-h1-b.1c", 0x10000,
            "008d1dc289df2ae2ba8f93d319c2b2c108cb9b89",
            "5daf4d7c37669ff210315dbd267f84fa743b6eb98154ad7c68b7a5e454d8629e", "maincpu"),
    RomSpec("rt_r-l0-b.3b", "rt_r-l0-b.3b", 0x10000,
            "3001c1b87cd1d441ba1226fb5b9dd6268458c0e8",
            "ed84f9fb849d6ad1b325534530293c8abe442f8cf284e7e84e0f833649144df1", "maincpu"),
    RomSpec("rt_r-l1-b.3c", "rt_r-l1-b.3c", 0x10000,
            "0144c846fd0bdb3e4d790f6cb7bb64829e931b76",
            "c5071b91ddafbabcb41939f6cf12118d12f553f6f16641908dd184ba6657c164", "maincpu"),
)

SPEC_BY_LOCAL = {spec.local_name: spec for spec in ROMS}


@dataclass(frozen=True)
class MissingM72Chip:
    name: str
    size: int
    sha1: str
    kind: str


MISSING_M72_CHIPS: tuple[MissingM72Chip, ...] = (
    MissingM72Chip("m72_a-8l-.ic66", 0x100,
                   "00e20cf754b6fd5138ee4d2f6ec28dff9e292fe6", "PROM"),
    MissingM72Chip("m72_a-9l-.ic75", 0x100,
                   "f13b0a4b52dcc6704063b676f09d83dcba170133", "PROM"),
    MissingM72Chip("m72_a-3d-.ic11", 0x117,
                   "6e3039e7dc424cbef7156312fa1ce67d7b082d30", "PLD"),
    MissingM72Chip("m72_a-4d-.ic19", 0x117,
                   "a66c589845f9995c673325f1161c687eb90d68c1", "PLD"),
    MissingM72Chip("m72_r-3a-.3a", 0x117,
                   "740d860df45109710e082d79c534ec0eeaa779f2", "PLD"),
)


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_roms(rom_dir: Path = ROM_DIR, *, quiet: bool = False) -> list[str]:
    """Return all manifest errors; never accept a partial or modified set."""
    errors: list[str] = []
    for spec in ROMS:
        path = rom_dir / spec.local_name
        if not path.is_file():
            errors.append(f"MISSING {spec.local_name}")
            continue
        size = path.stat().st_size
        if size != spec.size:
            errors.append(
                f"SIZE {spec.local_name}: {size}, expected {spec.size}")
            continue
        actual_sha1 = digest(path, "sha1")
        actual_sha256 = digest(path, "sha256")
        if actual_sha1 != spec.sha1:
            errors.append(
                f"SHA1 {spec.local_name}: {actual_sha1}, expected {spec.sha1}")
        if actual_sha256 != spec.sha256:
            errors.append(
                f"SHA256 {spec.local_name}: {actual_sha256}, expected {spec.sha256}")
        if not quiet and actual_sha1 == spec.sha1 and actual_sha256 == spec.sha256:
            print(f"OK  {spec.local_name:14s} {size:6d}  SHA1 {actual_sha1}")
    return errors


def require_verified(rom_dir: Path = ROM_DIR) -> None:
    errors = verify_roms(rom_dir, quiet=True)
    if errors:
        raise ValueError("ROM manifest failed:\n  " + "\n  ".join(errors))


def _read(name: str, rom_dir: Path) -> bytes:
    return (rom_dir / name).read_bytes()


def _load16_byte(region: bytearray, data: bytes, offset: int) -> None:
    end = offset + len(data) * 2
    if end > len(region) + 1:
        raise ValueError("interleaved ROM exceeds region")
    region[offset:end:2] = data


def assemble_regions(rom_dir: Path = ROM_DIR) -> dict[str, bytes]:
    """Reproduce the R-Type ``ROM_START`` regions from MAME 0.288."""
    require_verified(rom_dir)

    maincpu = bytearray(0x100000)
    h0 = _read("rt_r-h0-b.1b", rom_dir)
    l0 = _read("rt_r-l0-b.3b", rom_dir)
    h1 = _read("rt_r-h1-b.1c", rom_dir)
    l1 = _read("rt_r-l1-b.3c", rom_dir)
    _load16_byte(maincpu, h0, 0x00001)
    _load16_byte(maincpu, l0, 0x00000)
    _load16_byte(maincpu, h1, 0x20001)
    _load16_byte(maincpu, l1, 0x20000)
    # Reset vector window is a ROM_RELOAD of bank 1.
    _load16_byte(maincpu, h1, 0xE0001)
    _load16_byte(maincpu, l1, 0xE0000)

    sprites = bytearray(0x80000)
    sprite_loads: tuple[tuple[str, int, tuple[int, ...]], ...] = (
        ("rt_r-00.1h", 0x00000, ()),
        ("rt_r-01.1j", 0x10000, (0x18000,)),
        ("rt_r-10.1k", 0x20000, ()),
        ("rt_r-11.1l", 0x30000, (0x38000,)),
        ("rt_r-20.3h", 0x40000, ()),
        ("rt_r-21.3j", 0x50000, (0x58000,)),
        ("rt_r-30.3k", 0x60000, ()),
        ("rt_r-31.3l", 0x70000, (0x78000,)),
    )
    for name, offset, reloads in sprite_loads:
        data = _read(name, rom_dir)
        sprites[offset:offset + len(data)] = data
        for reload in reloads:
            sprites[reload:reload + len(data)] = data

    tiles0 = b"".join(_read(name, rom_dir) for name in
                      ("rt_b-a0.3c", "rt_b-a1.3d", "rt_b-a2.3a", "rt_b-a3.3e"))
    tiles1 = b"".join(_read(name, rom_dir) for name in
                      ("rt_b-b0.3j", "rt_b-b1.3k", "rt_b-b2.3h", "rt_b-b3.3f"))

    assert len(maincpu) == 0x100000
    assert len(sprites) == 0x80000
    assert len(tiles0) == 0x20000
    assert len(tiles1) == 0x20000
    return {
        "maincpu": bytes(maincpu),
        "sprites": bytes(sprites),
        "tiles0": tiles0,
        "tiles1": tiles1,
    }


def decode_tile(region: bytes, code: int) -> bytes:
    """Decode one M72 8x8 tile to 64 pen indices, row-major."""
    quarter = len(region) // 4
    total = quarter // 8
    if len(region) % 4 or not 0 <= code < total:
        raise IndexError(f"tile code {code} outside 0..{total - 1}")
    base = code * 8
    pixels = bytearray(8 * 8)
    for y in range(8):
        for x in range(8):
            pen = 0
            mask = 0x80 >> x  # MAME drawgfx.cpp::readbit is MSB-first.
            for plane in range(4):
                if region[plane * quarter + base + y] & mask:
                    pen |= 1 << plane
            pixels[y * 8 + x] = pen
    return bytes(pixels)


def decode_sprite(region: bytes, code: int) -> bytes:
    """Decode one M72 16x16 sprite cell to 256 pen indices, row-major."""
    quarter = len(region) // 4
    total = quarter // 32
    if len(region) % 4 or not 0 <= code < total:
        raise IndexError(f"sprite code {code} outside 0..{total - 1}")
    base = code * 32
    pixels = bytearray(16 * 16)
    for y in range(16):
        for x in range(16):
            # MAME x offsets: STEP8(0,1), STEP8(16*8,1).
            byte_offset = base + y + (16 if x >= 8 else 0)
            mask = 0x80 >> (x & 7)
            pen = 0
            for plane in range(4):
                if region[plane * quarter + byte_offset] & mask:
                    pen |= 1 << plane
            pixels[y * 16 + x] = pen
    return bytes(pixels)


def pack_nibbles(pixels: Iterable[int]) -> bytes:
    """Pack left/even pixel in high nibble, right/odd in low nibble."""
    values = list(pixels)
    if len(values) & 1:
        raise ValueError("4bpp stream must contain an even number of pixels")
    out = bytearray(len(values) // 2)
    for index in range(0, len(values), 2):
        left, right = values[index], values[index + 1]
        if not 0 <= left < 16 or not 0 <= right < 16:
            raise ValueError("pen index outside 0..15")
        out[index // 2] = (left << 4) | right
    return bytes(out)


def unpack_nibbles(data: bytes) -> bytes:
    out = bytearray(len(data) * 2)
    for index, value in enumerate(data):
        out[index * 2] = value >> 4
        out[index * 2 + 1] = value & 0x0F
    return bytes(out)


# A diagnostic palette only. Actual colors are runtime M72 palette RAM and are
# captured separately from MAME; no palette is invented for game assets here.
DIAGNOSTIC_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0), (32, 32, 32), (180, 30, 30), (255, 90, 40),
    (35, 140, 40), (80, 220, 70), (180, 160, 30), (255, 230, 70),
    (30, 70, 170), (60, 150, 255), (145, 60, 190), (235, 100, 255),
    (30, 175, 180), (90, 245, 245), (185, 185, 185), (255, 255, 255),
)


def _palette_bytes() -> list[int]:
    values: list[int] = []
    for color in DIAGNOSTIC_COLORS:
        values.extend(color)
    values.extend([0] * (768 - len(values)))
    return values


def build_atlas(cells: Sequence[bytes], cell_w: int, cell_h: int,
                columns: int, label: str) -> Image.Image:
    rows = (len(cells) + columns - 1) // columns
    atlas = Image.new("P", (columns * cell_w, rows * cell_h), 0)
    atlas.putpalette(_palette_bytes())
    for code, pixels in enumerate(cells):
        cell = Image.frombytes("P", (cell_w, cell_h), pixels)
        cell.putpalette(_palette_bytes())
        atlas.paste(cell, ((code % columns) * cell_w, (code // columns) * cell_h))
    # Metadata is also embedded in the PNG text-free filename/manifest. Drawing
    # labels over pixels would destroy the atlas as a pixel-reference.
    atlas.info["Description"] = label
    return atlas


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_all(rom_dir: Path = ROM_DIR, converted_dir: Path = CONVERTED_DIR,
               build_dir: Path = BUILD_DIR) -> dict[str, object]:
    regions = assemble_regions(rom_dir)
    converted_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    tile0_cells = [decode_tile(regions["tiles0"], code) for code in range(4096)]
    tile1_cells = [decode_tile(regions["tiles1"], code) for code in range(4096)]
    sprite_cells = [decode_sprite(regions["sprites"], code) for code in range(4096)]

    tile0_packed = pack_nibbles(b"".join(tile0_cells))
    tile1_packed = pack_nibbles(b"".join(tile1_cells))
    sprite_packed = pack_nibbles(b"".join(sprite_cells))

    outputs: dict[str, bytes] = {
        "RTYPE_MAINCPU_REGION.bin": regions["maincpu"],
        "RTYPE_TILES0_INDEX4.bin": tile0_packed,
        "RTYPE_TILES1_INDEX4.bin": tile1_packed,
        "RTYPE_SPRITES_INDEX4.bin": sprite_packed,
    }
    output_manifest: dict[str, dict[str, object]] = {}
    for name, data in outputs.items():
        path = converted_dir / name
        path.write_bytes(data)
        output_manifest[name] = {
            "size": len(data),
            "sha256": _sha256_bytes(data),
            "path": str(path.relative_to(ROOT)),
        }

    tile0_atlas = build_atlas(tile0_cells, 8, 8, 64, "M72 tiles0 diagnostic pens")
    tile1_atlas = build_atlas(tile1_cells, 8, 8, 64, "M72 tiles1 diagnostic pens")
    sprite_atlas = build_atlas(sprite_cells, 16, 16, 64, "M72 sprites diagnostic pens")
    tile0_atlas.save(build_dir / "tiles0_indices.png")
    tile1_atlas.save(build_dir / "tiles1_indices.png")
    sprite_atlas.save(build_dir / "sprites_indices.png")

    manifest: dict[str, object] = {
        "format": 1,
        "source": {
            "rom_dir": str(rom_dir.relative_to(ROOT)),
            "mame_tag": MAME_TAG,
            "mame_commit": MAME_COMMIT,
            "roms": [asdict(spec) for spec in ROMS],
        },
        "regions": {
            name: {"size": len(data), "sha256": _sha256_bytes(data)}
            for name, data in regions.items()
        },
        "decoded": {
            "tiles0": {"count": 4096, "width": 8, "height": 8},
            "tiles1": {"count": 4096, "width": 8, "height": 8},
            "sprites": {"count": 4096, "width": 16, "height": 16},
            "packing": "two pixels per byte; left/even high nibble",
            "palette": "diagnostic pen indices only; runtime RGB not inferred",
        },
        "outputs": output_manifest,
    }
    manifest_path = build_dir / "arcade_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"M72 regions: maincpu={len(regions['maincpu'])}, sprites={len(regions['sprites'])}, "
          f"tiles0={len(regions['tiles0'])}, tiles1={len(regions['tiles1'])}")
    for name, item in output_manifest.items():
        print(f"OUT {name:27s} {item['size']:7d}  SHA256 {item['sha256']}")
    print(f"manifest: {manifest_path}")
    return manifest


def stage_mame(target: Path, rom_dir: Path = ROM_DIR,
               *, diagnostic_placeholders: bool = False) -> Path:
    require_verified(rom_dir)
    set_dir = target if target.name.lower() == "rtype" else target / "rtype"
    set_dir.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, object]] = []
    for spec in ROMS:
        source = rom_dir / spec.local_name
        destination = set_dir / spec.mame_name
        shutil.copy2(source, destination)
        staged.append({
            "name": spec.mame_name,
            "source": spec.local_name,
            "size": spec.size,
            "sha1": spec.sha1,
            "placeholder": False,
        })
        print(f"COPY {spec.local_name} -> {destination.name}")

    if diagnostic_placeholders:
        print("WARNING: creating zero-filled MAME-only PROM/PLD placeholders; "
              "their checksums are intentionally wrong")
        for chip in MISSING_M72_CHIPS:
            destination = set_dir / chip.name
            destination.write_bytes(bytes(chip.size))
            staged.append({
                "name": chip.name,
                "size": chip.size,
                "expected_sha1": chip.sha1,
                "actual_sha1": digest(destination, "sha1"),
                "kind": chip.kind,
                "placeholder": True,
            })
            print(f"DUMMY {chip.name:16s} {chip.size:4d} bytes (MAME diagnostic only)")

    stage_manifest = {
        "format": 1,
        "mame_tag": MAME_TAG,
        "set": "rtype",
        "diagnostic_placeholders": diagnostic_placeholders,
        "files": staged,
    }
    (set_dir / "STAGING_MANIFEST.json").write_text(
        json.dumps(stage_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return set_dir


def command_verify(args: argparse.Namespace) -> int:
    errors = verify_roms(args.rom_dir)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"ROM manifest OK: {len(ROMS)} files, arcade set rtype (World)")
    return 0


def command_decode(args: argparse.Namespace) -> int:
    try:
        decode_all(args.rom_dir, args.converted_dir, args.build_dir)
    except ValueError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


def command_stage_mame(args: argparse.Namespace) -> int:
    try:
        set_dir = stage_mame(args.target, args.rom_dir,
                             diagnostic_placeholders=args.diagnostic_placeholders)
    except ValueError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"MAME set staged at: {set_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(rom_dir=ROM_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="verify every source ROM")
    verify.add_argument("--rom-dir", type=Path, default=ROM_DIR)
    verify.set_defaults(func=command_verify)

    decode = sub.add_parser("decode", help="assemble regions and decode planar gfx")
    decode.add_argument("--rom-dir", type=Path, default=ROM_DIR)
    decode.add_argument("--converted-dir", type=Path, default=CONVERTED_DIR)
    decode.add_argument("--build-dir", type=Path, default=BUILD_DIR)
    decode.set_defaults(func=command_decode)

    stage = sub.add_parser("stage-mame", help="stage a directory for MAME rtype")
    stage.add_argument("target", type=Path,
                       help="rompath directory or its final rtype directory")
    stage.add_argument("--rom-dir", type=Path, default=ROM_DIR)
    stage.add_argument("--diagnostic-placeholders", action="store_true",
                       help="create explicitly invalid zero PROM/PLD files")
    stage.set_defaults(func=command_stage_mame)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
