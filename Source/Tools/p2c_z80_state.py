"""Сверка состояния: граф объектов CPython против памяти модели Z80 (раскладка SDCC).

Смещения полей берутся из той же раскладки, что и образ начального состояния
(z80layout), страничные данные читаются из страниц модели TS-Config.
"""
from __future__ import annotations

import struct

from p2c.ptypes import (
    ArrayT, BoolT, BottomT, BytesT, DequeT, DictT, ExtT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT,
    OptT, SetT, StrT, TargetT, TupleT, ValT, is_pointer,
)
from p2c.z80layout import Z80Layout

WINDOW = 0xC000
PAGE = 0x4000
# Неизменяемые ресурсы: сравниваются только длины (содержимое проверено образом).
SKIP_CONTENT = frozenset({
    ('M72Rom', 'data'), ('Stage', 'sections'), ('Stage', 'checkpoint_terrain'),
    ('TitleAssets', 'logos'), ('TitleAssets', 'text'), ('M72Tilemaps', 'rom'),
})


class Z80StateComparer:
    def __init__(self, model, compiler, crepr, layout, image_ids: dict[int, int],
                 page_map: dict[int, int] | None = None) -> None:
        self.model = model
        self.page_map = page_map or {}
        self.c = compiler
        self.p = compiler.program
        self.r = crepr
        self.layout = layout
        self.z = Z80Layout(compiler, crepr, layout)
        self.image_ids = image_ids
        self.class_names = {number: name for name, number in layout.class_ids.items()}
        self.seen: dict[int, int] = {}
        # Список для сбора всех расхождений полей объектов (None — остановка на первом).
        self.collect: list[str] | None = None

    # --- чтение памяти -------------------------------------------------------------

    def read(self, address: int, size: int) -> bytes:
        return bytes(self.model.memory[address:address + size])

    def read_data(self, data: int, page: int, offset: int, size: int) -> bytes:
        if not page:
            return self.read(data + offset, size)
        position = (data - WINDOW) + offset
        out = bytearray()
        while len(out) < size:
            logical = page + (position >> 14)
            number = self.page_map.get(logical, logical)
            within = position & (PAGE - 1)
            chunk = min(size - len(out), PAGE - within)
            out += self.model.page_bytes(number)[within:within + chunk]
            position += chunk
        return bytes(out)

    def word(self, address: int) -> int:
        return struct.unpack('<H', self.read(address, 2))[0]

    @staticmethod
    def resolved(t):
        from p2c.compiler import int_empty
        if isinstance(t, IntT) and int_empty(t):
            return IntT(-(1 << 31), (1 << 31) - 1)
        return t

    def int_of(self, t, data: bytes) -> int:
        cint = self.r.cint(self.resolved(t))
        return int.from_bytes(data[:cint.bits // 8], 'little', signed=cint.signed)

    # --- сравнение ----------------------------------------------------------------------

    def compare_root(self, value: object, pointer: int, path: str = 'app') -> str | None:
        self.seen = {}
        return self.compare_object(value, pointer, path)

    def compare_object(self, value: object, pointer: int, path: str) -> str | None:
        if value is None:
            return None if pointer == 0 else f'{path}: CPython None, Z80 объект #{pointer:04X}'
        if pointer == 0:
            return f'{path}: Z80 NULL, CPython {type(value).__name__}'
        known = self.seen.get(id(value))
        if known is not None:
            return None if known == pointer else f'{path}: другая идентичность объекта'
        self.seen[id(value)] = pointer
        class_id = self.model.memory[pointer]
        class_name = self.class_names.get(class_id)
        if class_name != type(value).__name__:
            return f'{path}: класс Z80 {class_name or class_id} вместо {type(value).__name__} (#{pointer:04X})'
        root = self.p.root(class_name)
        layout = self.layout.roots.get(root)
        if layout is None:
            return None
        _presence, slots, _total = self.z.root_layout(root)
        attributes = vars(value)
        for attr, slot in sorted(layout.attribute_slot.items(), key=lambda item: item[1]):
            if slot not in layout.class_slots.get(class_name, set()) or attr not in attributes:
                continue
            if (class_name, attr) in SKIP_CONTENT:
                continue
            field_t = self.c.field_type(class_name, attr)
            found = self.compare_value(attributes[attr], pointer + slots[slot], field_t, f'{path}.{attr}')
            if found:
                if self.collect is None:
                    return found
                self.collect.append(found)
        if layout.list_based:
            from p2c.annotations import parse_annotation
            cell = self.c.field_cell(class_name, '<items>')
            elem = cell.t if not isinstance(cell.t, BottomT) else parse_annotation(
                self.c, self.p.list_base_of(class_name), self.p.classes[class_name].module,
                self.p.classes[class_name].filename)
            return self.compare_list(list(value), pointer, elem, path)
        return None

    def compare_list(self, items: list, pointer: int, elem, path: str) -> str | None:
        length = self.word(pointer + 2)
        if length != len(items):
            return f'{path}: длина Z80 {length} CPython {len(items)}'
        data = self.word(pointer + 6)
        page = self.model.memory[pointer + 8]
        size = self.z.sizeof(elem)
        for index, item in enumerate(items):
            raw = self.read_data(data, page, index * size, size)
            found = self.compare_bytes(item, raw, elem, f'{path}[{index}]')
            if found:
                if self.collect is None:
                    return found
                self.collect.append(found)
        return None

    def compare_value(self, value: object, address: int, t, path: str) -> str | None:
        size = self.z.sizeof(t)
        return self.compare_bytes(value, self.read(address, size), t, path)

    def compare_bytes(self, value: object, raw: bytes, t, path: str) -> str | None:
        t = self.resolved(t)
        if isinstance(t, IntT):
            number = self.int_of(t, raw)
            if not isinstance(value, (int, bool)) or int(value) != number:
                return f'{path}: Z80 {number} CPython {value!r}'
            return None
        if isinstance(t, BoolT):
            if bool(raw[0]) != bool(value):
                return f'{path}: Z80 {raw[0]} CPython {value!r}'
            return None
        if isinstance(t, NoneT):
            return None if value is None else f'{path}: CPython {value!r} вместо None'
        if isinstance(t, OptT):
            inner = t.inner
            if is_pointer(inner):
                pointer = struct.unpack('<H', raw[:2])[0]
                if value is None:
                    return None if pointer == 0 else f'{path}: Z80 значение вместо None'
                return self.compare_bytes(value, raw, inner, path)
            if isinstance(inner, FnT):
                if (value is None) != (raw[0] == 0):
                    return f'{path}: вызываемое Z80 id {raw[0]} CPython {value!r}'
                return None
            if value is None:
                return None if raw[0] == 0 else f'{path}: Z80 значение вместо None'
            if raw[0] == 0:
                return f'{path}: Z80 None вместо {value!r}'
            return self.compare_bytes(value, raw[1:], self.r.normalized(t).inner, path)
        if isinstance(t, StrT):
            pointer = struct.unpack('<H', raw[:2])[0]
            if pointer == 0:
                return None if value is None else f'{path}: Z80 NULL вместо строки'
            length = self.word(pointer + 2)
            text = self.read(self.word(pointer + 4), length).decode('utf-8', 'replace')
            return None if text == value else f'{path}: Z80 {text!r} CPython {value!r}'
        if isinstance(t, ObjT):
            return self.compare_object(value, struct.unpack('<H', raw[:2])[0], path)
        if isinstance(t, (ListT, ArrayT)):
            pointer = struct.unpack('<H', raw[:2])[0]
            if value is None:
                return None if pointer == 0 else f'{path}: Z80 список вместо None'
            if pointer == 0:
                return f'{path}: Z80 NULL вместо списка'
            known = self.seen.get(id(value))
            if known is not None:
                return None
            self.seen[id(value)] = pointer
            return self.compare_list(list(value), pointer, t.elem, path)
        if isinstance(t, DequeT):
            pointer = struct.unpack('<H', raw[:2])[0]
            length = self.word(pointer + 2)
            capacity = self.word(pointer + 4)
            head = self.word(pointer + 6)
            data = self.word(pointer + 8)
            items = list(value)
            if length != len(items):
                return f'{path}: длина очереди Z80 {length} CPython {len(items)}'
            size = self.z.sizeof(t.elem)
            for index, item in enumerate(items):
                position = (head + index) % capacity
                found = self.compare_bytes(item, self.read(data + position * size, size), t.elem, f'{path}[{index}]')
                if found:
                    return found
            return None
        if isinstance(t, (DictT, SetT)):
            pointer = struct.unpack('<H', raw[:2])[0]
            if pointer == 0:
                return None if value is None else f'{path}: Z80 NULL вместо словаря'
            length = self.word(pointer + 2)
            used = self.word(pointer + 4)
            key_size = self.model.memory[pointer + 8]
            if length != len(value):
                key_t = t.elem if isinstance(t, SetT) else t.k
                live = self.word(pointer + 10)
                keys = self.word(pointer + 12)
                extra = ''
                if isinstance(self.resolved(key_t), IntT):
                    z80_keys = {self.int_of(key_t, self.read(keys + index * key_size, key_size))
                                for index in range(used) if self.model.memory[live + index]}
                    python_keys = set(value)
                    extra = f'; только Z80 {sorted(z80_keys - python_keys)}, только CPython {sorted(python_keys - z80_keys)}'
                return f'{path}: размер Z80 {length} CPython {len(value)}{extra}'
            value_size = self.model.memory[pointer + 9]
            live = self.word(pointer + 10)
            keys = self.word(pointer + 12)
            values = self.word(pointer + 14)
            entries = [index for index in range(used) if self.model.memory[live + index]]
            key_t = t.elem if isinstance(t, SetT) else t.k
            if isinstance(t, SetT):
                z80_keys = sorted(self.int_of(key_t, self.read(keys + index * key_size, key_size))
                                  for index in entries) if isinstance(key_t, IntT) else None
                if z80_keys is not None and z80_keys != sorted(value):
                    return f'{path}: множество Z80 {z80_keys} CPython {sorted(value)}'
                return None
            for (key, item), index in zip(value.items(), entries):
                found = self.compare_bytes(key, self.read(keys + index * key_size, key_size), t.k, f'{path}{{ключ}}')
                if found:
                    return found
                found = self.compare_bytes(item, self.read(values + index * value_size, value_size), t.v,
                                           f'{path}[{key!r}]')
                if found:
                    return found
            return None
        if isinstance(t, BytesT):
            pointer = struct.unpack('<H', raw[:2])[0]
            if pointer == 0:
                return None if value is None else f'{path}: Z80 NULL вместо bytes'
            length = struct.unpack('<I', self.read(pointer + 2, 4))[0]
            if length != len(value):
                return f'{path}: длина bytes Z80 {length} CPython {len(value)}'
            if length > 65536:
                return None
            data = self.word(pointer + 10)
            page = self.model.memory[pointer + 12]
            content = self.read_data(data, page, 0, length)
            if content != bytes(value):
                first = next(index for index in range(length) if content[index] != value[index])
                return f'{path}[{first}]: Z80 {content[first]} CPython {value[first]}'
            return None
        if isinstance(t, TupleT):
            offset = 0
            for index, (item_t, item) in enumerate(zip(self.r.normalized(t).items, value)):
                size = self.z.sizeof(item_t)
                found = self.compare_bytes(item, raw[offset:offset + size], item_t, f'{path}[{index}]')
                if found:
                    return found
                offset += size
            return None
        if isinstance(t, ValT):
            if t.cls == 'Rect':
                numbers = struct.unpack('<4i', raw[:16])
                actual = (value.x, value.y, value.w, value.h)
                return None if numbers == actual else f'{path}: Z80 {numbers} CPython {actual}'
            for name, offset, size, field_t in self.z.value_members(t.cls):
                found = self.compare_bytes(getattr(value, name), raw[offset:offset + size], field_t, f'{path}.{name}')
                if found:
                    return found
            return None
        if isinstance(t, ImageT):
            number = struct.unpack('<H', raw[:2])[0]
            expected = self.image_ids.get(id(value))
            if expected is not None and expected != number:
                return f'{path}: изображение Z80 {number} CPython {expected}'
            return None
        if isinstance(t, FnT):
            if (value is None) != (raw[0] == 0):
                return f'{path}: вызываемое Z80 id {raw[0]} CPython {value!r}'
            return None
        if isinstance(t, (ExtT, FontT, TargetT)):
            return None
        return None
