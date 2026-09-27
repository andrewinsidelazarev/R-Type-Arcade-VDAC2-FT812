#!/usr/bin/env python3
"""Собрать минимальный FAT32 superfloppy с восемью RTYPE??.PAK для теста SD."""
from __future__ import annotations

import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "Build"
PACK_DIR = BUILD / "SD" / "RType"
OUTPUT = BUILD / "SD" / "rtype_test.img"
SECTOR = 512
TOTAL_SECTORS = 32768                 # 16 МиБ, достаточно для всех packs
SECTORS_PER_CLUSTER = 8              # 4 КиБ
RESERVED_SECTORS = 32
FAT_SECTORS = 32
DATA_START = RESERVED_SECTORS + FAT_SECTORS
CLUSTER_BYTES = SECTOR * SECTORS_PER_CLUSTER


def short_name(filename: str) -> bytes:
    stem, suffix = filename.upper().split(".", 1)
    if len(stem) > 8 or len(suffix) > 3:
        raise ValueError(f"не 8.3 имя: {filename}")
    return stem.encode("ascii").ljust(8) + suffix.encode("ascii").ljust(3)


def main() -> int:
    manifest = json.loads(
        (BUILD / "rtype_stage_packs.json").read_text(encoding="utf-8")
    )
    image = bytearray(TOTAL_SECTORS * SECTOR)
    boot = memoryview(image)[:SECTOR]
    boot[0:3] = b"\xEB\x58\x90"
    boot[3:11] = b"RTYPEVD2"
    struct.pack_into("<H", boot, 11, SECTOR)
    boot[13] = SECTORS_PER_CLUSTER
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)
    boot[16] = 1                         # одна FAT
    struct.pack_into("<H", boot, 17, 0)
    struct.pack_into("<H", boot, 19, 0)
    boot[21] = 0xF8
    struct.pack_into("<H", boot, 22, 0)
    struct.pack_into("<H", boot, 24, 63)
    struct.pack_into("<H", boot, 26, 255)
    struct.pack_into("<I", boot, 28, 0)
    struct.pack_into("<I", boot, 32, TOTAL_SECTORS)
    struct.pack_into("<I", boot, 36, FAT_SECTORS)
    struct.pack_into("<H", boot, 40, 0)
    struct.pack_into("<H", boot, 42, 0)
    struct.pack_into("<I", boot, 44, 2)  # root cluster
    struct.pack_into("<H", boot, 48, 1)
    struct.pack_into("<H", boot, 50, 6)
    boot[64] = 0x80
    boot[66] = 0x29
    struct.pack_into("<I", boot, 67, 0x52545950)
    boot[71:82] = b"RTYPE VDAC2"
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xAA"

    fat = memoryview(image)[RESERVED_SECTORS * SECTOR:
                            (RESERVED_SECTORS + FAT_SECTORS) * SECTOR]
    struct.pack_into("<I", fat, 0, 0x0FFFFFF8)
    struct.pack_into("<I", fat, 4, 0x0FFFFFFF)
    struct.pack_into("<I", fat, 8, 0x0FFFFFFF)  # root cluster 2
    root_offset = DATA_START * SECTOR
    next_cluster = 3

    for index, entry in enumerate(manifest["stages"]):
        filename = str(entry["filename"])
        payload = (PACK_DIR / filename).read_bytes()
        clusters = (len(payload) + CLUSTER_BYTES - 1) // CLUSTER_BYTES
        first_cluster = next_cluster
        for cluster in range(first_cluster, first_cluster + clusters):
            following = (cluster + 1 if cluster + 1 < first_cluster + clusters
                         else 0x0FFFFFFF)
            struct.pack_into("<I", fat, cluster * 4, following)
        data_offset = (DATA_START +
                       (first_cluster - 2) * SECTORS_PER_CLUSTER) * SECTOR
        image[data_offset:data_offset + len(payload)] = payload

        directory = root_offset + index * 32
        image[directory:directory + 11] = short_name(filename)
        image[directory + 11] = 0x20
        struct.pack_into("<H", image, directory + 20, first_cluster >> 16)
        struct.pack_into("<H", image, directory + 26, first_cluster & 0xFFFF)
        struct.pack_into("<I", image, directory + 28, len(payload))
        next_cluster += clusters

    if DATA_START + (next_cluster - 2) * SECTORS_PER_CLUSTER > TOTAL_SECTORS:
        raise ValueError("FAT32 test image переполнен")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(image)
    print(f"FAT32 SD image: {OUTPUT} ({len(image)} bytes, {next_cluster-3} data clusters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
