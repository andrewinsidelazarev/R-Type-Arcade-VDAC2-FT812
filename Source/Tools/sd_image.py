"""Образ SD-карты FAT32 для игры: файлы в каталоге GAMES\\<игра>\\, как у Zuma Deluxe VDAC2.

Основа — готовый образ (Wild Commander и загрузчик BOOT.$C), копируется в выходной образ;
затем удаляются заданные каталоги и файлы (со всем содержимым) и записываются файлы игры.
Длинные имена записываются как в Windows: записи LFN (UTF-16) перед короткой записью 8.3 с
псевдонимом «~N», если имя не короткое. Каталоги создаются с записями «.» и «..». Кластеры
файла — из самых длинных свободных отрезков (файл ложится немногими кусками), цепочки — во все
копии FAT. Совпадающий по размеру и содержимому файл не переписывается. Пока запущен
Unreal.exe, образ не пишется (эмулятор может держать его открытым).
Разметка: том с сектора 0 или первый раздел MBR с типом #0B/#0C; сектор 512 байт.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import subprocess
import sys
from pathlib import Path

SECTOR = 512
END_OF_CHAIN = 0x0FFFFFFF
ATTR_DIRECTORY = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F
SHORT_ALLOWED = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&\'()-@^_`{}~')


class Volume:
    def __init__(self, handle) -> None:
        self.handle = handle
        self.start = 0
        boot = self.read_sectors(0, 1)
        if struct.unpack_from('<H', boot, 11)[0] != SECTOR or boot[82:87] != b'FAT32':
            for entry in range(4):
                if boot[446 + entry * 16 + 4] in (0x0B, 0x0C):
                    self.start = struct.unpack_from('<I', boot, 446 + entry * 16 + 8)[0]
                    break
            boot = self.read_sectors(0, 1)
        if struct.unpack_from('<H', boot, 11)[0] != SECTOR or boot[82:87] != b'FAT32':
            raise SystemExit('образ не содержит тома FAT32 с сектором 512 байт')
        self.spc = boot[13]
        self.reserved = struct.unpack_from('<H', boot, 14)[0]
        self.fats = boot[16]
        self.total = struct.unpack_from('<I', boot, 32)[0]
        self.fat_sectors = struct.unpack_from('<I', boot, 36)[0]
        self.root = struct.unpack_from('<I', boot, 44)[0]
        self.fsinfo = struct.unpack_from('<H', boot, 48)[0]
        self.data_start = self.reserved + self.fats * self.fat_sectors
        self.clusters = (self.total - self.data_start) // self.spc
        raw = self.read_sectors(self.reserved, self.fat_sectors)
        self.fat = list(struct.unpack_from(f'<{self.clusters + 2}I', raw, 0))
        self.dirty_fat: set[int] = set()

    # --- сектора и FAT ------------------------------------------------------------------------
    def read_sectors(self, sector: int, count: int) -> bytes:
        self.handle.seek((self.start + sector) * SECTOR)
        return self.handle.read(count * SECTOR)

    def write_sectors(self, sector: int, data: bytes) -> None:
        assert len(data) % SECTOR == 0
        self.handle.seek((self.start + sector) * SECTOR)
        self.handle.write(data)

    def cluster_bytes(self) -> int:
        return self.spc * SECTOR

    def cluster_sector(self, cluster: int) -> int:
        return self.data_start + (cluster - 2) * self.spc

    def chain(self, first: int) -> list[int]:
        result = []
        cluster = first
        while 2 <= cluster < self.clusters + 2:
            if len(result) > self.clusters:
                raise SystemExit('цикл в цепочке FAT')
            result.append(cluster)
            cluster = self.fat[cluster] & 0x0FFFFFFF
        return result

    def set_fat(self, cluster: int, value: int) -> None:
        self.fat[cluster] = (self.fat[cluster] & 0xF0000000) | value
        self.dirty_fat.add(cluster // (SECTOR // 4))

    def free_runs(self) -> list[tuple[int, int]]:
        runs = []
        start = None
        for cluster in range(2, self.clusters + 2):
            if self.fat[cluster] & 0x0FFFFFFF == 0:
                if start is None:
                    start = cluster
            elif start is not None:
                runs.append((start, cluster - start))
                start = None
        if start is not None:
            runs.append((start, self.clusters + 2 - start))
        return runs

    def allocate(self, count: int) -> list[int]:
        chosen = []
        for start, length in sorted(self.free_runs(), key=lambda run: (-run[1], run[0])):
            take = min(length, count - len(chosen))
            chosen += range(start, start + take)
            if len(chosen) == count:
                break
        if len(chosen) < count:
            raise SystemExit(f'на томе нет {count} свободных кластеров')
        chosen.sort()
        for index, cluster in enumerate(chosen):
            self.set_fat(cluster, chosen[index + 1] if index + 1 < len(chosen) else END_OF_CHAIN)
        return chosen

    def free_chain(self, first: int) -> int:
        chain = self.chain(first) if first >= 2 else []
        for cluster in chain:
            self.set_fat(cluster, 0)
        return len(chain)

    def flush(self) -> None:
        per_sector = SECTOR // 4
        for number in sorted(self.dirty_fat):
            values = self.fat[number * per_sector:(number + 1) * per_sector]
            values += [0] * (per_sector - len(values))
            data = struct.pack(f'<{per_sector}I', *values)
            for copy in range(self.fats):
                self.write_sectors(self.reserved + copy * self.fat_sectors + number, data)
        self.dirty_fat.clear()
        info = bytearray(self.read_sectors(self.fsinfo, 1))
        if info[0:4] == b'RRaA' and info[484:488] == b'rrAa':
            free = sum(1 for cluster in range(2, self.clusters + 2) if self.fat[cluster] & 0x0FFFFFFF == 0)
            struct.pack_into('<II', info, 488, free, 0xFFFFFFFF)
            self.write_sectors(self.fsinfo, bytes(info))

    # --- каталоги -----------------------------------------------------------------------------
    def read_directory(self, cluster: int) -> tuple[list[int], bytearray]:
        clusters = self.chain(cluster)
        data = bytearray(b''.join(self.read_sectors(self.cluster_sector(c), self.spc) for c in clusters))
        return clusters, data

    def write_directory(self, clusters: list[int], data: bytes) -> None:
        size = self.cluster_bytes()
        for index, cluster in enumerate(clusters):
            self.write_sectors(self.cluster_sector(cluster), data[index * size:(index + 1) * size])

    def entries(self, cluster: int) -> list[dict]:
        """Записи каталога: имя (длинное или короткое), короткое, атрибут, кластер, размер,
        позиция короткой записи и первой записи LFN."""
        _clusters, data = self.read_directory(cluster)
        result = []
        pending: list[bytes] = []
        first_lfn = None
        for position in range(0, len(data), 32):
            entry = bytes(data[position:position + 32])
            if entry[0] == 0:
                break
            if entry[0] == 0xE5:
                pending, first_lfn = [], None
                continue
            if entry[11] == ATTR_LFN:
                if not pending:
                    first_lfn = position
                pending.append(entry)
                continue
            short = entry[0:11]
            name = None
            if pending and all(item[13] == lfn_checksum(short) for item in pending):
                chunks = b''.join(item[1:11] + item[14:26] + item[28:32] for item in reversed(pending))
                name = chunks.decode('utf-16-le', 'replace').split('\x00')[0].rstrip('￿')
            if name is None:
                stem, extension = short[0:8].decode('cp866').rstrip(), short[8:11].decode('cp866').rstrip()
                name = stem + ('.' + extension if extension else '')
            result.append({'name': name, 'short': short, 'attr': entry[11], 'position': position,
                           'first': first_lfn if pending else position,
                           'cluster': struct.unpack_from('<H', entry, 26)[0] |
                           (struct.unpack_from('<H', entry, 20)[0] << 16),
                           'size': struct.unpack_from('<I', entry, 28)[0]})
            pending, first_lfn = [], None
        return result

    def find(self, cluster: int, name: str) -> dict | None:
        for entry in self.entries(cluster):
            if entry['name'] not in ('.', '..') and entry['name'].casefold() == name.casefold():
                return entry
        return None

    def add_entry(self, directory: int, name: str, attr: int, first: int, size: int) -> None:
        existing = {entry['short'] for entry in self.entries(directory)}
        short = short_alias(name, existing)
        records = lfn_records(name, short) if not is_short(name) else []
        record = bytearray(32)
        record[0:11] = short
        record[11] = attr
        struct.pack_into('<H', record, 20, first >> 16)
        struct.pack_into('<H', record, 26, first & 0xFFFF)
        struct.pack_into('<I', record, 28, size)
        records.append(bytes(record))
        clusters, data = self.read_directory(directory)
        needed = len(records)
        position = None
        run = 0
        for offset in range(0, len(data), 32):
            if data[offset] in (0x00, 0xE5):
                run += 1
                if run == needed:
                    position = offset - (needed - 1) * 32
                    break
            else:
                run = 0
        end_marker = False
        if position is None:
            end = next((offset for offset in range(0, len(data), 32) if data[offset] == 0), len(data))
            while len(data) - end < needed * 32:
                extra = self.allocate(1)[0]
                self.set_fat(clusters[-1], extra)
                clusters.append(extra)
                data += bytes(self.cluster_bytes())
            position = end
        end_marker = data[position + (needed - 1) * 32] == 0
        for index, item in enumerate(records):
            data[position + index * 32:position + (index + 1) * 32] = item
        after = position + needed * 32
        if end_marker and after < len(data) and data[after] != 0:
            data[after] = 0
        self.write_directory(clusters, bytes(data))

    def remove_entry(self, directory: int, entry: dict) -> None:
        clusters, data = self.read_directory(directory)
        for position in range(entry['first'], entry['position'] + 32, 32):
            data[position] = 0xE5
        self.write_directory(clusters, bytes(data))

    def remove_tree(self, directory: int, entry: dict) -> int:
        freed = 0
        if entry['attr'] & ATTR_DIRECTORY and entry['cluster'] >= 2:
            for child in self.entries(entry['cluster']):
                if child['name'] in ('.', '..'):
                    continue
                freed += self.remove_tree(entry['cluster'], child)
        freed += self.free_chain(entry['cluster'])
        self.remove_entry(directory, entry)
        return freed

    def make_directory(self, parent: int, name: str) -> int:
        cluster = self.allocate(1)[0]
        block = bytearray(self.cluster_bytes())
        for index, (short, target) in enumerate(((b'.          ', cluster),
                                                 (b'..         ', 0 if parent == self.root else parent))):
            record = bytearray(32)
            record[0:11] = short
            record[11] = ATTR_DIRECTORY
            struct.pack_into('<H', record, 20, target >> 16)
            struct.pack_into('<H', record, 26, target & 0xFFFF)
            block[index * 32:(index + 1) * 32] = record
        self.write_sectors(self.cluster_sector(cluster), bytes(block))
        self.add_entry(parent, name, ATTR_DIRECTORY, cluster, 0)
        return cluster

    def resolve(self, path: str, create: bool) -> int:
        cluster = self.root
        for part in [item for item in path.replace('\\', '/').split('/') if item]:
            entry = self.find(cluster, part)
            if entry is None:
                if not create:
                    raise SystemExit(f'нет каталога {part}')
                cluster = self.make_directory(cluster, part)
            elif not entry['attr'] & ATTR_DIRECTORY:
                raise SystemExit(f'{part} — не каталог')
            else:
                cluster = entry['cluster']
        return cluster

    def write_file(self, directory: int, name: str, data: bytes) -> str:
        entry = self.find(directory, name)
        if entry is not None:
            chain = self.chain(entry['cluster']) if entry['cluster'] else []
            if entry['size'] == len(data):
                stored = b''.join(self.read_sectors(self.cluster_sector(c), self.spc) for c in chain)[:len(data)]
                if hashlib.sha256(stored).digest() == hashlib.sha256(data).digest():
                    return f'{name} уже записан'
            self.free_chain(entry['cluster'])
            self.remove_entry(directory, entry)
        size = self.cluster_bytes()
        count = max(1, (len(data) + size - 1) // size)
        chain = self.allocate(count)
        padded = data + bytes(count * size - len(data))
        extents = 0
        start = 0
        for index in range(1, len(chain) + 1):
            if index == len(chain) or chain[index] != chain[index - 1] + 1:
                self.write_sectors(self.cluster_sector(chain[start]), padded[start * size:index * size])
                extents += 1
                start = index
        self.add_entry(directory, name, ATTR_ARCHIVE, chain[0], len(data))
        return f'{name}: {len(data)} байт, кластеров {len(chain)}, кусков {extents}'


def is_short(name: str) -> bool:
    stem, dot, extension = name.partition('.')
    return (name == name.upper() and 1 <= len(stem) <= 8 and len(extension) <= 3 and '.' not in extension and
            all(char in SHORT_ALLOWED for char in stem + extension))


def short_alias(name: str, existing: set[bytes]) -> bytes:
    if is_short(name):
        stem, _, extension = name.partition('.')
        short = stem.ljust(8).encode('ascii') + extension.ljust(3).encode('ascii')
        if short in existing:
            raise SystemExit(f'короткое имя {name} уже занято')
        return short
    base, _, extension = name.rpartition('.') if '.' in name else (name, '', '')
    clean = ''.join(char for char in base.upper() if char in SHORT_ALLOWED)
    ext = ''.join(char for char in extension.upper() if char in SHORT_ALLOWED)[:3]
    for number in range(1, 10000):
        tail = f'~{number}'
        short = (clean[:8 - len(tail)] + tail).ljust(8).encode('ascii') + ext.ljust(3).encode('ascii')
        if short not in existing:
            return short
    raise SystemExit(f'нет свободного псевдонима для {name}')


def lfn_checksum(short: bytes) -> int:
    total = 0
    for byte in short:
        total = (((total & 1) << 7) + (total >> 1) + byte) & 0xFF
    return total


def lfn_records(name: str, short: bytes) -> list[bytes]:
    units = name.encode('utf-16-le')
    count = (len(units) // 2 + 12) // 13
    padded = units + (b'\x00\x00' if len(units) // 2 % 13 else b'')
    padded += b'\xFF\xFF' * (count * 13 - len(padded) // 2)
    checksum = lfn_checksum(short)
    records = []
    for sequence in range(count, 0, -1):
        chunk = padded[(sequence - 1) * 26:sequence * 26]
        record = bytearray(32)
        record[0] = sequence | (0x40 if sequence == count else 0)
        record[1:11] = chunk[0:10]
        record[11] = ATTR_LFN
        record[13] = checksum
        record[14:26] = chunk[10:22]
        record[28:32] = chunk[22:26]
        records.append(bytes(record))
    return records


def emulator_running() -> bool:
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Unreal.exe', '/NH'], capture_output=True, text=True,
                            encoding='cp866', errors='replace')
    return 'Unreal.exe' in result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--image', required=True, help='выходной образ')
    parser.add_argument('--base', default='', help='образ-основа: копируется в --image перед изменениями')
    parser.add_argument('--remove', action='append', default=[], help='путь каталога или файла для удаления')
    parser.add_argument('--put', action='append', default=[], help='«исходный файл=путь в образе»')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    if emulator_running():
        print('Unreal.exe запущен: образ SD может быть занят эмулятором, запись отложена')
        return 2
    image = Path(args.image)
    if args.base:
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(Path(args.base).read_bytes())
    with image.open('r+b') as handle:
        volume = Volume(handle)
        for path in args.remove:
            parent, _, name = path.replace('\\', '/').rstrip('/').rpartition('/')
            directory = volume.resolve(parent, create=False) if parent else volume.root
            entry = volume.find(directory, name)
            if entry is None:
                print(f'{path}: нет в образе')
                continue
            print(f'{path}: удалён, освобождено кластеров {volume.remove_tree(directory, entry)}')
        for item in args.put:
            source, _, target = item.partition('=')
            parent, _, name = target.replace('\\', '/').rpartition('/')
            directory = volume.resolve(parent, create=True) if parent else volume.root
            print(volume.write_file(directory, name or Path(source).name, Path(source).read_bytes()))
        volume.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
