"""Начальное состояние программы для Z80: байты резидентной памяти и страниц окна 2.

Объекты, заголовки контейнеров и строки размещаются по абсолютным адресам
резидентных диапазонов; крупные массивы данных — на страницах окна #8000.
Указатели разрешаются при сборке, поэтому C-инициализаторы и копирование
данных при старте не нужны: SPG загружает готовые страницы.
"""
from __future__ import annotations

import dataclasses
import struct
import types as pytypes

from .errors import TranslationError
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, DequeT, DictT, ExtT, FnT, FontT, ImageT, IntT, ListT, NoneT,
    ObjT, OptT, SetT, StrT, T, TargetT, TupleT, ValT, VoidT, has_references, is_int_like, is_pointer,
)
from .z80layout import (
    BUF_HEADER, DEQUE_HEADER, DICT_HEADER, FN_SIZE, LIST_HEADER, POINTER, STR_HEADER, Z80Layout,
)

PAGE_SIZE = 0x4000
WINDOW = 0xC000
P2C_CLS_STR = 252
P2C_CLS_BUF = 253


class Ref:
    """Отложенная ссылка на размещаемый объект."""

    def __init__(self, key: tuple) -> None:
        self.key = key


class Z80Image:
    def __init__(self, compiler, crepr, layout, image_id, resident_ranges: list[tuple[int, int]],
                 first_page: int, page_threshold: int = 512) -> None:
        self.c = compiler
        self.p = compiler.program
        self.r = crepr
        self.layout = layout
        self.z = Z80Layout(compiler, crepr, layout)
        self.image_id = image_id
        self.ranges = list(resident_ranges)
        self.range_index = 0
        self.cursor = self.ranges[0][0]
        self.first_page = first_page
        self.next_page = first_page
        self.small_page: dict[bool, int | None] = {False: None, True: None}
        self.small_cursor: dict[bool, int] = {False: 0, True: 0}
        self.mutable_pages: set[int] = set()
        self.page_threshold = page_threshold
        self.resident: dict[int, int] = {}          # адрес -> байт
        self.pages: dict[int, bytearray] = {}
        self.addresses: dict[tuple, int] = {}       # ключ размещения -> адрес
        self.symbols: dict[str, int] = {}
        self.alive: list[object] = []
        self.statics: list[int] = []
        self.work: list = []
        self.root_values: dict[str, object] = {}

    # --- размещение --------------------------------------------------------------

    def allocate(self, size: int) -> int:
        size = max(1, size)
        while True:
            start, end = self.ranges[self.range_index]
            if self.cursor + size <= end:
                address = self.cursor
                self.cursor += size
                return address
            self.range_index += 1
            if self.range_index >= len(self.ranges):
                raise TranslationError(f'резидентная память исчерпана при размещении {size} байт')
            self.cursor = self.ranges[self.range_index][0]

    def allocate_paged(self, size: int, mutable: bool) -> tuple[int, int]:
        """Логическая страница и адрес в окне страниц: крупный блок — с начала собственных
        страниц, мелкие массивы делят текущую страницу своего вида (изменяемые отдельно:
        неизменяемые страницы с одинаковым содержимым потом делят физическую страницу)."""
        if size >= PAGE_SIZE // 2:
            page = self.next_page
            pages = (size + PAGE_SIZE - 1) // PAGE_SIZE
            for index in range(pages):
                self.pages[page + index] = bytearray(PAGE_SIZE)
                if mutable:
                    self.mutable_pages.add(page + index)
            self.next_page = page + pages
            self.check_page_space()
            return page, WINDOW
        if self.small_page[mutable] is None or self.small_cursor[mutable] + size > PAGE_SIZE:
            self.small_page[mutable] = self.next_page
            self.pages[self.next_page] = bytearray(PAGE_SIZE)
            if mutable:
                self.mutable_pages.add(self.next_page)
            self.next_page += 1
            self.small_cursor[mutable] = 0
            self.check_page_space()
        address = WINDOW + self.small_cursor[mutable]
        self.small_cursor[mutable] += size
        return self.small_page[mutable], address

    def check_page_space(self) -> None:
        if self.next_page > 0x100:
            raise TranslationError('логические страницы данных исчерпаны')

    def physical_pages(self, first_physical: int) -> tuple[dict[int, int], dict[int, bytes]]:
        """Физические страницы: неизменяемые страницы с одинаковым содержимым общие."""
        mapping: dict[int, int] = {}
        content: dict[int, bytes] = {}
        shared: dict[bytes, int] = {}
        physical = first_physical
        for logical in sorted(self.pages):
            data = bytes(self.pages[logical])
            if logical not in self.mutable_pages and data in shared:
                mapping[logical] = shared[data]
                continue
            mapping[logical] = physical
            content[physical] = data
            if logical not in self.mutable_pages:
                shared[data] = physical
            physical += 1
        return mapping, content

    def write(self, address: int, data: bytes) -> None:
        for offset, byte in enumerate(data):
            self.resident[address + offset] = byte

    def write_paged(self, page: int, address: int, data: bytes) -> None:
        offset = address - WINDOW
        position = 0
        while position < len(data):
            chunk = min(len(data) - position, PAGE_SIZE - offset)
            self.pages[page][offset:offset + chunk] = data[position:position + chunk]
            position += chunk
            page += 1
            offset = 0

    # --- значения ----------------------------------------------------------------------

    @staticmethod
    def word(value: int) -> bytes:
        return struct.pack('<H', value & 0xFFFF)

    def encode(self, t: T, value: object, where: str) -> bytes:
        """Байты значения поля формы t (указатели — адреса размещённых объектов)."""
        t = self.z.resolved(t)
        if isinstance(t, IntT):
            cint = self.r.cint(t)
            number = int(value)
            if not cint.holds(number):
                raise TranslationError(f'{where}: {number} вне {cint.c()}')
            return number.to_bytes(cint.bits // 8, 'little', signed=cint.signed)
        if isinstance(t, BoolT):
            return bytes([1 if value else 0])
        if isinstance(t, NoneT):
            return b'\0'
        if isinstance(t, OptT):
            inner = t.inner
            if is_pointer(inner):
                return self.word(0) if value is None else self.encode(inner, value, where)
            if isinstance(inner, FnT):
                return b'\0\0\0' if value is None else self.encode(inner, value, where)
            size = self.z.sizeof(t)
            if value is None:
                return bytes(size)
            return b'\1' + self.encode(self.r.normalized(t).inner, value, where)
        if isinstance(t, StrT):
            return self.word(self.string_address(value))
        if isinstance(t, ObjT):
            return self.word(self.object_address(value, where))
        if isinstance(t, (ListT, ArrayT)):
            return self.word(self.list_address(t, value, where))
        if isinstance(t, DequeT):
            return self.word(self.deque_address(t, value, where))
        if isinstance(t, (DictT, SetT)):
            return self.word(self.dict_address(t, value, where))
        if isinstance(t, BytesT):
            return self.word(self.bytes_address(value, where))
        if isinstance(t, TupleT):
            normalized = self.r.normalized(t)
            if not isinstance(value, tuple) or len(value) != len(normalized.items):
                raise TranslationError(f'{where}: {value!r:.40} вместо кортежа')
            return b''.join(self.encode(item_t, item, f'{where}[{index}]')
                            for index, (item_t, item) in enumerate(zip(normalized.items, value)))
        if isinstance(t, ValT):
            if t.cls == 'Rect':
                return struct.pack('<4i', value.x, value.y, value.w, value.h)
            return b''.join(self.encode(field_t, getattr(value, name), f'{where}.{name}')
                            for name, _offset, _size, field_t in self.z.value_members(t.cls))
        if isinstance(t, ImageT):
            return self.word(self.image_id(value))
        if isinstance(t, FnT):
            return self.function_bytes(value, where)
        if isinstance(t, (ExtT, FontT, TargetT)):
            return self.word(0)
        raise TranslationError(f'{where}: Z80-кодирование {t} не поддержано')

    def function_bytes(self, value: object, where: str) -> bytes:
        if isinstance(value, pytypes.MethodType):
            key = ('extern', type(value.__self__).__name__, value.__func__.__name__)
            number = self.c.fn_values.get(key)
            if number is None:
                raise TranslationError(f'{where}: вызываемое без номера')
            return bytes([number]) + self.word(0)
        raise TranslationError(f'{where}: вызываемое {value!r:.40} в снимке')

    # --- объекты и контейнеры ----------------------------------------------------------

    def object_address(self, value: object, where: str) -> int:
        key = ('obj', id(value))
        if key in self.addresses:
            return self.addresses[key]
        info = self.p.class_of(value)
        if info is None or info.frozen:
            raise TranslationError(f'{where}: {type(value).__name__} не объект кучи')
        root = self.p.root(info.name)
        layout = self.layout.roots.get(root)
        # Размер экземпляра класса (до последнего слота класса), как P2C_SIZE_<класс> при выделении.
        size = 2 if layout is None else self.z.object_size(info.name)
        address = self.allocate(size)
        self.addresses[key] = address
        self.alive.append(value)
        self.statics.append(address)
        self.work.append(('object', value, address, where))
        return address

    def fill_object(self, value: object, address: int, where: str) -> None:
        info = self.p.class_of(value)
        root = self.p.root(info.name)
        layout = self.layout.roots.get(root)
        data = bytearray()
        class_id = self.layout.class_ids[info.name]
        if layout is None:
            self.write(address, bytes([class_id, 0]))
            return
        presence, slots, total = self.z.root_layout(root)
        data = bytearray(max(total, self.z.object_size(info.name)))
        attributes = vars(value)
        if layout.list_based:
            elem_t = self.list_items_type(info.name)
            items = list(value)
            data_address, page = self.list_data(elem_t, items, f'{where}[]', mutable=True)
            header = bytes([class_id, 0]) + self.word(len(items)) + self.word(len(items)) + \
                self.word(data_address) + bytes([page])
            data[0:LIST_HEADER] = header
        else:
            data[0] = class_id
        if presence >= 0:
            mask = 0
            for attr, bit in layout.presence_bits.items():
                if attr in attributes:
                    mask |= 1 << bit
            data[presence:presence + 2] = self.word(mask)
        for attr, slot in layout.attribute_slot.items():
            if attr not in attributes or slot not in layout.class_slots.get(info.name, set()):
                continue
            field_t = self.c.field_type(info.name, attr)
            encoded = self.encode(field_t, attributes[attr], f'{where}.{attr}')
            offset = slots[slot]
            data[offset:offset + len(encoded)] = encoded
        self.write(address, bytes(data[:self.z.object_size(info.name)]))

    def list_items_type(self, class_name: str) -> T:
        from .annotations import parse_annotation
        cell = self.c.field_cell(class_name, '<items>')
        if not isinstance(cell.t, BottomT):
            return cell.t
        info = self.p.classes[class_name]
        return parse_annotation(self.c, self.p.list_base_of(class_name), info.module, info.filename)

    def list_data(self, elem_t: T, items: list, where: str, mutable: bool) -> tuple[int, int]:
        """Адрес данных элементов и страница (0 — резидентно)."""
        if not items:
            return 0, 0
        size = self.z.sizeof(elem_t) * len(items)
        # Ссылки внутри элементов обходит сборщик: на страницы уходят только крупные
        # массивы без ссылок. Рост страничного списка рантайм запрещает (отказ).
        paged = size > self.page_threshold and not has_references(elem_t)
        if paged:
            page, address = self.allocate_paged(size, mutable)
        else:
            page, address = 0, self.allocate(size)
        self.work.append(('elements', elem_t, list(items), address, page, where))
        return address, page

    def fill_elements(self, elem_t: T, items: list, address: int, page: int, where: str) -> None:
        data = b''.join(self.encode(elem_t, item, f'{where}[{index}]') for index, item in enumerate(items))
        if page:
            self.write_paged(page, address, data)
        else:
            self.write(address, data)

    def list_address(self, t: T, value: object, where: str) -> int:
        key = ('list', id(value))
        if key in self.addresses:
            return self.addresses[key]
        address = self.allocate(LIST_HEADER)
        self.addresses[key] = address
        self.alive.append(value)
        self.statics.append(address)
        items = list(value)
        data_address, page = self.list_data(t.elem, items, where, mutable=isinstance(t, ListT))
        class_symbol = self.layout.container_class_symbol(t)
        class_id = self.class_number(class_symbol)
        self.write(address, bytes([class_id, 0]) + self.word(len(items)) + self.word(len(items)) +
                   self.word(data_address) + bytes([page]))
        return address

    def class_number(self, symbol: str) -> int:
        for number, name, _key in self.layout.container_classes.values():
            if name == symbol:
                return number
        raise TranslationError(f'нет номера класса {symbol}')

    def deque_address(self, t: DequeT, value: object, where: str) -> int:
        key = ('deque', id(value))
        if key in self.addresses:
            return self.addresses[key]
        address = self.allocate(DEQUE_HEADER)
        self.addresses[key] = address
        self.alive.append(value)
        self.statics.append(address)
        items = list(value)
        size = self.z.sizeof(t.elem) * len(items)
        data_address = self.allocate(size) if items else 0
        if items:
            self.work.append(('elements', t.elem, items, data_address, 0, where))
        class_id = self.class_number(self.layout.container_class_symbol(t))
        self.write(address, bytes([class_id, 0]) + self.word(len(items)) + self.word(len(items)) +
                   self.word(0) + self.word(data_address) + bytes([0]))
        return address

    def dict_address(self, t: T, value: object, where: str) -> int:
        key = ('dict', id(value))
        if key in self.addresses:
            return self.addresses[key]
        address = self.allocate(DICT_HEADER)
        self.addresses[key] = address
        self.alive.append(value)
        self.statics.append(address)
        if isinstance(t, SetT):
            keys = list(value)
            key_t, value_t, values = t.elem, None, None
        else:
            keys = list(value.keys())
            values = list(value.values())
            key_t, value_t = t.k, t.v
        count = len(keys)
        key_size = self.z.sizeof(key_t)
        value_size = self.z.sizeof(value_t) if value_t is not None else 0
        live = keys_address = values_address = 0
        if count:
            live = self.allocate(count)
            self.write(live, bytes([1]) * count)
            keys_address = self.allocate(key_size * count)
            self.work.append(('elements', key_t, keys, keys_address, 0, where + '.keys'))
            if values is not None:
                values_address = self.allocate(value_size * count)
                self.work.append(('elements', value_t, values, values_address, 0, where + '.values'))
        class_id = self.class_number(self.layout.container_class_symbol(t))
        self.write(address, bytes([class_id, 0]) + self.word(count) + self.word(count) + self.word(count) +
                   bytes([key_size, value_size]) + self.word(live) + self.word(keys_address) +
                   self.word(values_address))
        return address

    def bytes_address(self, value: object, where: str) -> int:
        key = ('bytes', id(value))
        if key in self.addresses:
            return self.addresses[key]
        address = self.allocate(BUF_HEADER)
        self.addresses[key] = address
        self.alive.append(value)
        self.statics.append(address)
        data = bytes(value)
        if len(data) > self.page_threshold:
            page, data_address = self.allocate_paged(len(data), isinstance(value, bytearray))
            self.write_paged(page, data_address, data)
        elif data:
            page, data_address = 0, self.allocate(len(data))
            self.write(data_address, data)
        else:
            page, data_address = 0, 0
        self.write(address, bytes([P2C_CLS_BUF, 0]) + struct.pack('<I', len(data)) +
                   struct.pack('<I', len(data)) + self.word(data_address) + bytes([page]))
        return address

    def string_address(self, text: str) -> int:
        number = self.c.intern(text)
        symbol = f'p2c_str_{number}'
        if symbol in self.symbols:
            return self.symbols[symbol]
        data = text.encode('utf-8')
        address = self.allocate(STR_HEADER + len(data))
        self.write(address, bytes([P2C_CLS_STR, 0]) + self.word(len(data)) +
                   self.word(address + STR_HEADER) + data)
        self.symbols[symbol] = address
        return address

    # --- сборка -------------------------------------------------------------------

    def drain(self) -> None:
        while self.work:
            item = self.work.pop()
            if item[0] == 'object':
                _, value, address, where = item
                self.fill_object(value, address, where)
            else:
                _, elem_t, items, address, page, where = item
                self.fill_elements(elem_t, items, address, page, where)

    def build(self, roots: dict[str, object]) -> None:
        self.root_values = dict(roots)
        for name, value in roots.items():
            self.symbols[f'p2c_root_{name}'] = self.object_address(value, name)
            self.drain()
        for text, number in sorted(self.c.strings.items(), key=lambda item: item[1]):
            self.string_address(text)
        for number, symbol in sorted(self.layout.constant_symbols.items(), key=lambda item: item[1]):
            value, t = self.c.constants[number]
            if is_int_like(t):
                continue
            if isinstance(t, (ListT, ArrayT)):
                self.symbols[symbol] = self.list_address(t, value, symbol)
            elif isinstance(t, (DictT, SetT)):
                self.symbols[symbol] = self.dict_address(t, value, symbol)
            elif isinstance(t, BytesT):
                self.symbols[symbol] = self.bytes_address(value, symbol)
            else:
                encoded = self.encode(t, value, symbol)
                address = self.allocate(len(encoded))
                self.write(address, encoded)
                self.symbols[symbol] = address
            self.drain()
        roots_table = self.allocate(POINTER * len(roots))
        self.write(roots_table, b''.join(self.word(self.symbols[f'p2c_root_{name}']) for name in roots))
        self.symbols['p2c_roots'] = roots_table
        count = self.allocate(2)
        self.write(count, self.word(len(roots)))
        self.symbols['p2c_root_count'] = count
        statics = sorted(set(self.statics))
        table = self.allocate(POINTER * max(1, len(statics)))
        self.write(table, b''.join(self.word(address) for address in statics) or self.word(0))
        self.symbols['p2c_statics'] = table
        count = self.allocate(2)
        self.write(count, self.word(len(statics)))
        self.symbols['p2c_static_count'] = count

    def resident_blocks(self) -> list[tuple[int, bytes]]:
        """Непрерывные резидентные блоки для загрузки."""
        blocks = []
        for start, end in self.ranges:
            used = [address for address in self.resident if start <= address < end]
            if not used:
                continue
            last = max(used)
            data = bytearray(last - start + 1)
            for address in used:
                data[address - start] = self.resident[address]
            blocks.append((start, bytes(data)))
        return blocks

    def symbol_asm(self) -> str:
        lines = ['; Сгенерировано p2c: адреса данных начального состояния для компоновщика SDCC.',
                 '\t.module p2c_data_symbols']
        for name, address in sorted(self.symbols.items()):
            lines.append(f'\t.globl _{name}')
            lines.append(f'_{name} = 0x{address:04X}')
        return '\n'.join(lines) + '\n'
