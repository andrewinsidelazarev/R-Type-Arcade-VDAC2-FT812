"""Каталог изображений программы для адаптера FT812 сборки Z80.

Изображения берутся из снимка (поверхности, которые транслированная программа
выводит blit), из ячеек спрайтов переписи M72SpriteAtlas.cell и из глифов шрифта
отладочной строки. Пиксели ARGB4444 (формат FT812 ARGB4) одинакового
содержимого объединяются в одну запись; запись хранит сжатые zlib данные
для CMD_INFLATE. Страницы Z80 с записями, таблицами и данными раскладываются
подряд с заданной физической страницы.
"""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PAGE_SIZE = 0x4000
ENTRIES_PER_PAGE = 1024
ENTRY_SIZE = 16
A_SIZE = (14, 15)
B_SIZE = (27, 30)
A_SLOTS = 768
ZONE_A_SLOTS = 64                # слотов A в чужой зоне RAM_G не меньше (титул выводит до 32 глифов)
RAM_G = 1 << 20
C_BYTES = 300_000
TEXT_CHARACTERS = range(32, 128)


def surface_argb4444(surface) -> tuple[int, int, bytes]:
    import pygame
    width, height = surface.get_size()
    raw = pygame.image.tobytes(surface, 'RGBA')
    out = bytearray(width * height * 2)
    for index in range(width * height):
        r, g, b, a = raw[index * 4:index * 4 + 4]
        value = ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        out[index * 2] = value & 0xFF
        out[index * 2 + 1] = value >> 8
    return width, height, bytes(out)


def flip_argb4444(data: bytes, width: int, height: int, flip_x: bool, flip_y: bool) -> bytes:
    rows = [data[row * width * 2:(row + 1) * width * 2] for row in range(height)]
    if flip_y:
        rows.reverse()
    if flip_x:
        rows = [b''.join(row[(width - 1 - column) * 2:(width - column) * 2] for column in range(width))
                for row in rows]
    return b''.join(rows)


@dataclass
class Entry:
    width: int
    height: int
    pixels: bytes
    compressed: bytes = b''
    page: int = 0
    offset: int = 0

    @property
    def cls(self) -> int:
        size = (self.width, self.height)
        return 0 if size == A_SIZE else 1 if size == B_SIZE else 2

    @property
    def solid_black(self) -> bool:
        return all(self.pixels[index] == 0x00 and self.pixels[index + 1] == 0xF0
                   for index in range(0, len(self.pixels), 2))


@dataclass
class Catalog:
    entries: list[Entry] = field(default_factory=lambda: [Entry(0, 0, b'')])
    by_content: dict[bytes, int] = field(default_factory=dict)
    image_entry: dict[int, int] = field(default_factory=dict)       # номер статического изображения -> запись
    cell_entry: dict[tuple, int] = field(default_factory=dict)       # (банк, отражения, код) -> запись
    bank_of_type: list[int] = field(default_factory=lambda: [0xFF] * 256)
    text_glyphs: list[int] = field(default_factory=lambda: [0] * (96 * 2))
    text_advance: list[int] = field(default_factory=lambda: [0] * 96)
    pages: dict[int, bytes] = field(default_factory=dict)
    defines: dict[str, int] = field(default_factory=dict)
    cell_pages: list[int] = field(default_factory=list)
    cell_offsets: list[int] = field(default_factory=list)

    def entry_for(self, width: int, height: int, pixels: bytes) -> int:
        key = struct.pack('<HH', width, height) + pixels
        index = self.by_content.get(key)
        if index is None:
            index = len(self.entries)
            self.entries.append(Entry(width, height, pixels))
            self.by_content[key] = index
        return index


def build_catalog(image_surfaces: dict[int, object], census_path: Path | None, font, first_page: int,
                  typed_types: list[int], ram_zone: tuple[int, int] | None = None) -> Catalog:
    """census_path и font могут быть None (программа без ячеек спрайтов и отладочной строки,
    например титул с циклом app.main полного runtime). ram_zone — (начало, байт) RAM_G, которую
    программе отдаёт видеоадаптер другой программы того же SPG; без неё программе принадлежит
    вся RAM_G."""
    catalog = Catalog()
    for number, surface in sorted(image_surfaces.items()):
        width, height, pixels = surface_argb4444(surface)
        catalog.image_entry[number] = catalog.entry_for(width, height, pixels)

    # Банки ячеек: 0..15 — палитровые FullHQ, далее типовые ресурсы Stage 1.
    for index, resource_type in enumerate(typed_types):
        catalog.bank_of_type[resource_type] = 16 + index
    bank_count = 16 + len(typed_types)
    census = json.loads(census_path.read_text(encoding='utf-8'))['cells'] if census_path is not None else []
    if census:
        from rtype_port.enemies import FULL_HQ, RESOURCE_HQ, SPRITE_CELL_BYTES, SPRITE_CELL_H, SPRITE_CELL_W
    bank_data: dict[int, bytes] = {}
    for typed, bank_value, code, flip_x, flip_y in census:
        bank = catalog.bank_of_type[bank_value] if typed else bank_value
        if bank not in bank_data:
            path = (RESOURCE_HQ / f'RTYPE_SPRITES_TYPE{bank_value:02X}_HQ_ARGB4444.bin' if typed
                    else FULL_HQ / f'RTYPE_SPRITES_PAL{bank_value:02X}_HQ_ARGB4444.bin')
            bank_data[bank] = path.read_bytes()
        cell = bank_data[bank][code * SPRITE_CELL_BYTES:(code + 1) * SPRITE_CELL_BYTES]
        pixels = flip_argb4444(cell, SPRITE_CELL_W, SPRITE_CELL_H, bool(flip_x), bool(flip_y))
        flips = (2 if flip_x else 0) | (1 if flip_y else 0)
        catalog.cell_entry[(bank, flips, code)] = catalog.entry_for(SPRITE_CELL_W, SPRITE_CELL_H, pixels)

    # Глифы отладочной строки: белый и чёрный, без сглаживания, как font.render(text, False, color).
    import pygame
    for character in (TEXT_CHARACTERS if font is not None else ()):
        text = chr(character)
        for black in (0, 1):
            surface = pygame.font.Font.render(font, text, False, (0, 0, 0) if black else (255, 255, 255))
            width, height, pixels = surface_argb4444(surface)
            if width and height:
                catalog.text_glyphs[((character - 32) << 1) | black] = catalog.entry_for(width, height, pixels)
        metrics = font.metrics(text)[0]
        catalog.text_advance[character - 32] = metrics[4] if metrics else 0

    # Раскладка RAM_G: прочие изображения, слоты A, слоты B.
    if ram_zone is None:
        a_bytes = A_SLOTS * 420
        b_slots = min((RAM_G - C_BYTES - a_bytes) // 1620, 128 * (15 - (A_SLOTS + 127) // 128))
        catalog.defines.update(
            P2C_FT_C_BASE=0, P2C_FT_C_END=C_BYTES, P2C_FT_A_BASE=C_BYTES, P2C_FT_A_SLOTS=A_SLOTS,
            P2C_FT_A_HANDLES=(A_SLOTS + 127) // 128, P2C_FT_B_BASE=C_BYTES + a_bytes, P2C_FT_B_SLOTS=b_slots,
            P2C_FT_B_HANDLES=(b_slots + 127) // 128)
    else:
        # Зона RAM_G: область C вмещает все изображения класса C сразу (адаптер начинает её со
        # смещения 4 и не вытесняет), за ней слоты A до конца зоны; слотов B нет.
        zone_base, zone_bytes = ram_zone
        if any(entry.cls == 1 for entry in catalog.entries[1:]):
            raise RuntimeError('в зоне RAM_G нет слотов B для ячеек 27×30')
        c_bytes = 4 + sum((entry.width * entry.height * 2 + 3) & ~3 for entry in catalog.entries[1:] if entry.cls == 2)
        a_base = zone_base + ((c_bytes + 3) & ~3)
        a_slots = min(A_SLOTS, (zone_base + zone_bytes - a_base) // 420)
        if a_slots < ZONE_A_SLOTS:
            raise RuntimeError(f'в зоне RAM_G #{zone_base:06X}+{zone_bytes}: слотов A {a_slots}, нужно {ZONE_A_SLOTS}')
        catalog.defines.update(
            P2C_FT_C_BASE=zone_base, P2C_FT_C_END=zone_base + c_bytes, P2C_FT_A_BASE=a_base, P2C_FT_A_SLOTS=a_slots,
            P2C_FT_A_HANDLES=(a_slots + 127) // 128, P2C_FT_B_BASE=a_base + a_slots * 420, P2C_FT_B_SLOTS=0,
            P2C_FT_B_HANDLES=0)
    if catalog.defines['P2C_FT_A_HANDLES'] + catalog.defines['P2C_FT_B_HANDLES'] > 15:
        raise RuntimeError('BITMAP_HANDLE слотов больше 15')

    # Страницы: записи, номера изображений, таблицы ячеек, вершины, слоты, сжатые данные.
    page = first_page
    entry_pages = (len(catalog.entries) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE
    catalog.defines['P2C_FT_ENTRY_PAGE'] = page
    page += entry_pages
    image_count = max(catalog.image_entry, default=0) + 1
    if image_count > 0x8000:
        raise RuntimeError('номеров изображений больше #7FFF')
    image_pages = (image_count * 2 + PAGE_SIZE - 1) // PAGE_SIZE
    catalog.defines['P2C_FT_IMAGE_PAGE'] = page
    image_table = bytearray(image_pages * PAGE_SIZE)
    for number, entry in catalog.image_entry.items():
        struct.pack_into('<H', image_table, number * 2, entry)
    for part in range(image_pages):
        catalog.pages[page + part] = bytes(image_table[part * PAGE_SIZE:(part + 1) * PAGE_SIZE])
    page += image_pages
    tables: dict[int, bytearray] = {}
    for (bank, flips, code), entry in catalog.cell_entry.items():
        table = tables.setdefault(bank * 4 + flips, bytearray(4096 * 2))
        struct.pack_into('<H', table, code * 2, entry)
    catalog.cell_pages = [0] * (bank_count * 4)
    catalog.cell_offsets = [0] * (bank_count * 4)
    for position, key in enumerate(sorted(tables)):
        table_page = page + position // 2
        offset = (position % 2) * 0x2000
        catalog.pages.setdefault(table_page, bytes(PAGE_SIZE))
        data = bytearray(catalog.pages[table_page])
        data[offset:offset + 0x2000] = tables[key]
        catalog.pages[table_page] = bytes(data)
        catalog.cell_pages[key] = table_page
        catalog.cell_offsets[key] = offset
    page += (len(tables) + 1) // 2
    catalog.defines['P2C_FT_TABLE_PAGE'] = page
    vertex = bytearray(PAGE_SIZE)
    for x in range(-320, 640):
        units = (x * 64) // 5 + 4096
        vertex[(x + 320) * 3:(x + 320) * 3 + 3] = bytes([0x40 | ((units >> 9) & 0x3F), (units >> 1) & 0xFF,
                                                         (units & 1) << 7])
    for y in range(-320, 480):
        units = (y * 64) // 5 + 4096
        vertex[0x1000 + (y + 320) * 2:0x1000 + (y + 320) * 2 + 2] = bytes([(units >> 8) & 0x7F, units & 0xFF])
    catalog.pages[page] = bytes(vertex)
    page += 1
    catalog.defines['P2C_FT_SLOT_PAGE'] = page
    catalog.pages[page] = bytes(PAGE_SIZE)
    page += 1
    # Сжатые данные подряд через границы страниц: запись хранит страницу и смещение начала.
    stream = bytearray()
    for entry in catalog.entries[1:]:
        entry.compressed = zlib.compress(entry.pixels, 9)
        entry.page = page + len(stream) // PAGE_SIZE
        entry.offset = len(stream) % PAGE_SIZE
        stream += entry.compressed
    data_pages = max(1, (len(stream) + PAGE_SIZE - 1) // PAGE_SIZE)
    for part in range(data_pages):
        catalog.pages[page + part] = bytes(stream[part * PAGE_SIZE:(part + 1) * PAGE_SIZE]).ljust(PAGE_SIZE, b'\0')
    last_page = page + data_pages - 1
    records = bytearray(entry_pages * PAGE_SIZE)
    records[0] = 0xFF
    for index, entry in enumerate(catalog.entries[1:], start=1):
        flags = 1 if entry.solid_black else 0
        struct.pack_into('<BBHHBBHH', records, index * ENTRY_SIZE, entry.cls, flags, entry.width, entry.height,
                         entry.page, 0, entry.offset, len(entry.compressed))
    for part in range(entry_pages):
        catalog.pages[catalog.defines['P2C_FT_ENTRY_PAGE'] + part] = bytes(
            records[part * PAGE_SIZE:(part + 1) * PAGE_SIZE])
    catalog.defines['P2C_FT_LAST_PAGE'] = last_page
    catalog.defines['P2C_FT_BANKS'] = bank_count
    catalog.defines['P2C_FT_ENTRIES'] = len(catalog.entries)
    return catalog


def tables_source(catalog: Catalog) -> tuple[str, str]:
    """Резидентные таблицы ячеек и банковые таблицы глифов отладочной строки."""
    def array(ctype: str, name: str, values: list[int]) -> str:
        return f'const {ctype} {name}[{len(values)}] = {{ ' + ', '.join(str(value) for value in values) + ' };'

    hot = '\n'.join([
        array('uint8_t', 'p2c_ft_bank_of_type', catalog.bank_of_type),
        array('uint8_t', 'p2c_ft_cell_pages', catalog.cell_pages),
        array('uint16_t', 'p2c_ft_cell_offsets', catalog.cell_offsets), ''])
    cold = '\n'.join([
        array('uint16_t', 'p2c_ft_text_glyphs', catalog.text_glyphs),
        array('uint8_t', 'p2c_ft_text_advance', catalog.text_advance), ''])
    return hot, cold


def config_lines(catalog: Catalog) -> list[str]:
    lines = [f'#define {name} {value}UL' if name.endswith(('BASE', 'END')) else f'#define {name} {value}u'
             for name, value in sorted(catalog.defines.items())]
    return lines + [
        'extern const uint8_t p2c_ft_bank_of_type[256];',
        f'extern const uint8_t p2c_ft_cell_pages[{len(catalog.cell_pages)}];',
        f'extern const uint16_t p2c_ft_cell_offsets[{len(catalog.cell_offsets)}];',
        'extern const uint16_t p2c_ft_text_glyphs[192];',
        'extern const uint8_t p2c_ft_text_advance[96];']


def model_description(catalog: Catalog) -> dict:
    """Сведения для модели проверки: хэши пикселей записей и соответствия номеров."""
    return {
        'pixels': [hashlib.sha1(entry.pixels).hexdigest() for entry in catalog.entries],
        'sizes': [(entry.width, entry.height) for entry in catalog.entries],
        'solid_black': [entry.solid_black for entry in catalog.entries],
        'image_entry': catalog.image_entry,
        'cell_entry': {f'{bank},{flips},{code}': entry for (bank, flips, code), entry in catalog.cell_entry.items()},
        'typed_banks': catalog.bank_of_type,
        'text_glyphs': catalog.text_glyphs,
        'text_advance': catalog.text_advance,
        'defines': catalog.defines,
    }
