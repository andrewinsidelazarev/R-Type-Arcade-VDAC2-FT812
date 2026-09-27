#!/usr/bin/env python3
"""Записать в образ SD `Build/V30Z80/rtype_sd.img` свежие `RTYPELVL.PAC`, `RTYPECOD.PAC` и `rtype_vdac2.spg`.

Образ — обычный FAT32 (его готовит мастер-карта пользователя), файлы игры лежат в
`GAMES/R-Type VDAC2`. Загрузчик `rtype_loader.asm` адресует пак секторами от его начала, поэтому
файл обязан лежать **подряд**: файлы перекладываются непрерывными цепочками, прежние цепочки
освобождаются. Меняются только записи каталога этих файлов и FAT; остальные файлы образа
(WC, BOOT.$C и прочее) не трогаются. Кода игры RTYPECOD.PAC (с 2026-09-27, загрузчик SPG релиза) в образе ещё может не
быть — его короткая запись создаётся в каталоге пака уровней.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'Build' / 'V30Z80'
IMAGE = BUILD / 'rtype_sd.img'
FILES = (('RTYPELVLPAC', BUILD / 'RTYPELVL.PAC'), ('RTYPECODPAC', BUILD / 'RTYPECOD.PAC'),
         ('RTYPE_~1SPG', BUILD / 'rtype_vdac2.spg'))
FREE, END = 0x00000000, 0x0FFFFFFF


class Fat32:
    """Разбор и правка образа FAT32 в памяти."""

    def __init__(self, image: bytearray) -> None:
        self.image = image
        boot = image[:512]
        self.sector = struct.unpack_from('<H', boot, 11)[0]
        self.per_cluster = boot[13]
        self.reserved = struct.unpack_from('<H', boot, 14)[0]
        self.fats = boot[16]
        self.fat_sectors = struct.unpack_from('<I', boot, 36)[0]
        self.root = struct.unpack_from('<I', boot, 44)[0]
        self.data_start = self.reserved + self.fats * self.fat_sectors
        self.cluster_bytes = self.sector * self.per_cluster
        self.clusters = (len(image) // self.sector - self.data_start) // self.per_cluster + 2

    def fat_offset(self, copy: int, cluster: int) -> int:
        return (self.reserved + copy * self.fat_sectors) * self.sector + cluster * 4

    def get(self, cluster: int) -> int:
        return struct.unpack_from('<I', self.image, self.fat_offset(0, cluster))[0] & 0x0FFFFFFF

    def set(self, cluster: int, value: int) -> None:
        for copy in range(self.fats):
            offset = self.fat_offset(copy, cluster)
            high = struct.unpack_from('<I', self.image, offset)[0] & 0xF0000000
            struct.pack_into('<I', self.image, offset, high | (value & 0x0FFFFFFF))

    def offset(self, cluster: int) -> int:
        return (self.data_start + (cluster - 2) * self.per_cluster) * self.sector

    def chain(self, cluster: int) -> list[int]:
        result = []
        while 2 <= cluster < 0x0FFFFFF8:
            result.append(cluster)
            cluster = self.get(cluster)
        return result

    def entries(self, cluster: int):
        """Короткие записи каталога: имя 8.3, атрибут, первый кластер, размер, смещение записи."""
        while 2 <= cluster < 0x0FFFFFF8:
            base = self.offset(cluster)
            for index in range(0, self.cluster_bytes, 32):
                entry = self.image[base + index:base + index + 32]
                if entry[0] == 0:
                    return
                if entry[0] == 0xE5 or entry[11] == 0x0F:
                    continue
                first = (struct.unpack_from('<H', entry, 20)[0] << 16) | struct.unpack_from('<H', entry, 26)[0]
                yield (entry[:11].decode('ascii', 'replace'), entry[11], first,
                       struct.unpack_from('<I', entry, 28)[0], base + index)
            cluster = self.get(cluster)

    def find(self, name: str) -> tuple[int, int, int] | None:
        """Запись файла в дереве по имени 8.3: (первый кластер, размер, смещение записи)."""
        def walk(cluster: int):
            for item, attribute, first, size, offset in list(self.entries(cluster)):
                if attribute & 0x10:
                    if item.strip() not in ('.', '..'):
                        found = walk(first)
                        if found:
                            return found
                elif item == name:
                    return first, size, offset
            return None
        return walk(self.root)

    def add_entry(self, name: str, near: int) -> int:
        """Короткая запись файла name (8.3 без точки, 11 знаков) в кластере каталога, где лежит запись near; вернуть её
        смещение. Свободное место — удалённая запись или конец каталога (за ним в кластере — снова конец)."""
        cluster = (near // self.sector - self.data_start) // self.per_cluster + 2
        base = self.offset(cluster)
        for index in range(0, self.cluster_bytes, 32):
            offset = base + index
            if self.image[offset] in (0x00, 0xE5):
                if self.image[offset] == 0x00 and index + 32 < self.cluster_bytes:
                    self.image[offset + 32] = 0x00       # конец каталога — за новой записью
                entry = bytearray(32)
                entry[0:11] = name.encode('ascii')
                entry[11] = 0x20                         # архивный
                self.image[offset:offset + 32] = entry
                return offset
        raise SystemExit(f'в кластере каталога нет места для записи {name}')

    def free_chain(self, cluster: int) -> None:
        for item in self.chain(cluster):
            self.set(item, FREE)

    def write_contiguous(self, entry_offset: int, first: int, data: bytes) -> int:
        """Положить файл подряд с кластера first, вернуть первый свободный кластер за ним."""
        count = max(1, (len(data) + self.cluster_bytes - 1) // self.cluster_bytes)
        if first + count > self.clusters:
            raise SystemExit(f'в образе нет места: нужно {count} кластеров с {first}, всего {self.clusters}')
        base = self.offset(first)
        self.image[base:base + len(data)] = data
        padding = count * self.cluster_bytes - len(data)
        if padding:
            self.image[base + len(data):base + count * self.cluster_bytes] = bytes(padding)
        for index in range(count):
            self.set(first + index, END if index == count - 1 else first + index + 1)
        struct.pack_into('<H', self.image, entry_offset + 20, (first >> 16) & 0xFFFF)
        struct.pack_into('<H', self.image, entry_offset + 26, first & 0xFFFF)
        struct.pack_into('<I', self.image, entry_offset + 28, len(data))
        return first + count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--image', type=Path, default=IMAGE)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    image = bytearray(args.image.read_bytes())
    fat = Fat32(image)
    places = []
    missing = []
    for name, path in FILES:
        found = fat.find(name)
        if not found:
            missing.append((name, path))
            continue
        places.append((name, path, *found))
    if not places:
        raise SystemExit('в образе нет файлов игры')
    for name, path in missing:
        if name != 'RTYPECODPAC':
            raise SystemExit(f'в образе нет файла {name}')
        near = next(offset for item, _, _, _, offset in places if item == 'RTYPELVLPAC')
        places.insert(1, (name, path, 0, 0, fat.add_entry(name, near)))
    # Освобождаем прежние цепочки и кладём файлы подряд с прежнего начала пака.
    start = min(first for _, _, first, _, _ in places if first >= 2)
    for _, _, first, _, _ in places:
        if first >= 2:
            fat.free_chain(first)
    cursor = start
    for name, path, _, old_size, entry in places:
        data = path.read_bytes()
        cursor = fat.write_contiguous(entry, cursor, data)
        print(f'{name}: было {old_size} байт, стало {len(data)}, '
              f'SHA-256 {hashlib.sha256(data).hexdigest()[:16]}')
    args.image.write_bytes(bytes(image))
    print(f'{args.image}: {len(image)} байт, SHA-256 {hashlib.sha256(image).hexdigest()[:16]}, '
          f'занято по кластер {cursor - 1} из {fat.clusters - 1}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
