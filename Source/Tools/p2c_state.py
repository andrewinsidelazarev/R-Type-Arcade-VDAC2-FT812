"""Сверка состояния: граф объектов CPython против памяти транслированной C-программы.

Раскладку полей даёт таблица p2c_field_table из сгенерированного C (offsetof и
описания представлений), поэтому чтение не зависит от догадок о выравнивании.
"""
from __future__ import annotations

import ctypes
import dataclasses
import struct
from collections import deque

INT_FORMATS = {'u8': 'B', 'i8': 'b', 'u16': 'H', 'i16': 'h', 'i32': 'i', 'b': 'B'}
POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)
# Неизменяемые ресурсы: сравниваются только длины (содержимое проверено снимком).
SKIP_CONTENT = frozenset({
    ('M72Rom', 'data'), ('Stage', 'sections'), ('Stage', 'checkpoint_terrain'),
    ('TitleAssets', 'logos'), ('TitleAssets', 'text'),
})


class FieldTableRow(ctypes.Structure):
    _fields_ = [('owner', ctypes.c_char_p), ('name', ctypes.c_char_p), ('offset', ctypes.c_uint32),
                ('size', ctypes.c_uint32), ('desc', ctypes.c_char_p)]


def split_braces(text: str) -> tuple[str, str]:
    """`{a}rest` -> (a, rest) с учётом вложенных скобок."""
    if not text.startswith('{'):
        raise ValueError(text)
    depth = 0
    for index, char in enumerate(text):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[1:index], text[index + 1:]
    raise ValueError(text)


class StateComparer:
    def __init__(self, dll, image_ids: dict[int, int]) -> None:
        self.dll = dll
        self.image_ids = image_ids
        count = ctypes.c_uint32.in_dll(dll, 'p2c_field_table_count').value
        table = (FieldTableRow * max(1, count)).in_dll(dll, 'p2c_field_table')
        self.fields: dict[str, list[tuple[str, int, int, str]]] = {}
        self.sizes: dict[str, int] = {}
        self.offsets: dict[tuple[str, str], int] = {}
        for index in range(count):
            row = table[index]
            owner = row.owner.decode()
            name = row.name.decode()
            if not name:
                self.sizes[owner] = row.size
                continue
            self.fields.setdefault(owner, []).append((name, row.offset, row.size, row.desc.decode()))
            self.offsets[(owner, name)] = row.offset
        names = (ctypes.c_char_p * 256).in_dll(dll, 'p2c_class_names')
        self.class_names = [(names[index] or b'').decode() for index in range(256)]
        dll.p2c_root_pointer.restype = ctypes.c_void_p

    # --- чтение памяти -------------------------------------------------------------

    @staticmethod
    def read(address: int, size: int) -> bytes:
        return ctypes.string_at(address, size)

    def read_int(self, address: int, kind: str) -> int:
        fmt = INT_FORMATS[kind]
        return struct.unpack('<' + fmt, self.read(address, struct.calcsize(fmt)))[0]

    def read_pointer(self, address: int) -> int:
        return struct.unpack('<Q' if POINTER_SIZE == 8 else '<I', self.read(address, POINTER_SIZE))[0]

    def member(self, struct_name: str, name: str) -> int:
        return self.offsets[(struct_name, name)]

    def desc_size(self, desc: str) -> int:
        if desc in INT_FORMATS:
            return struct.calcsize(INT_FORMATS[desc])
        if desc in ('o', 's', 'B') or desc[0] in 'LQSD':
            return POINTER_SIZE
        if desc.startswith(('T:', 'V:', 'N:')):
            return self.sizes[desc[2:]]
        if desc == 'R':
            return self.sizes['P2cRect']
        if desc == 'F':
            return self.sizes['P2cFn']
        if desc == 'I':
            return 4
        if desc == 'z':
            return 1
        raise ValueError(desc)

    # --- запись полей (одинаковые правки обеих версий в прогонах сверки) -------------

    def field_address(self, pointer: int, attr: str) -> tuple[int, str]:
        class_name = self.class_names[self.read_int(pointer, 'u8')]
        for name, offset, _size, desc in self.fields.get(class_name, []):
            if name == attr:
                return pointer + offset, desc
        raise KeyError(f'{class_name}.{attr}')

    def object_path(self, path: list[str]) -> int:
        """Указатель на объект по цепочке полей от корня app."""
        pointer = self.dll.p2c_root_pointer(0)
        for attr in path:
            address, desc = self.field_address(pointer, attr)
            pointer = self.read_pointer(address)
        return pointer

    def write_int(self, pointer: int, attr: str, value: int) -> None:
        address, desc = self.field_address(pointer, attr)
        fmt = INT_FORMATS[desc]
        ctypes.memmove(address, struct.pack('<' + fmt, value), struct.calcsize(fmt))

    def read_field_int(self, pointer: int, attr: str) -> int:
        address, desc = self.field_address(pointer, attr)
        return self.read_int(address, desc)

    # --- сравнение ----------------------------------------------------------------------

    def compare_root(self, python_root: object, index: int) -> str | None:
        self.seen: dict[int, int] = {}
        address = self.dll.p2c_root_pointer(index)
        return self.compare_object(python_root, address, 'app')

    def compare_object(self, value: object, pointer: int, path: str) -> str | None:
        if value is None:
            return None if pointer == 0 else f'{path}: CPython None, C объект'
        if pointer == 0:
            return f'{path}: C NULL, CPython {type(value).__name__}'
        known = self.seen.get(id(value))
        if known is not None:
            return None if known == pointer else f'{path}: другая идентичность объекта'
        self.seen[id(value)] = pointer
        class_id = self.read_int(pointer, 'u8')
        class_name = self.class_names[class_id]
        if class_name != type(value).__name__:
            return f'{path}: класс C {class_name or class_id} вместо {type(value).__name__}'
        attributes = vars(value)
        for name, offset, _size, desc in self.fields.get(class_name, []):
            if name not in attributes:
                continue
            if (class_name, name) in SKIP_CONTENT:
                continue
            found = self.compare_value(attributes[name], pointer + offset, desc, f'{path}.{name}')
            if found:
                return found
        if isinstance(value, list):
            items_desc = None
        return None

    def compare_value(self, value: object, address: int, desc: str, path: str) -> str | None:
        if desc in INT_FORMATS:
            number = self.read_int(address, desc)
            if desc == 'b':
                if bool(number) != bool(value) or not isinstance(value, (bool, int)):
                    return f'{path}: C {number} CPython {value!r}'
                return None
            if not isinstance(value, (int, bool)) or int(value) != number:
                return f'{path}: C {number} CPython {value!r}'
            return None
        if desc == 'o':
            return self.compare_object(value, self.read_pointer(address), path)
        if desc == 's':
            pointer = self.read_pointer(address)
            if value is None:
                return None if pointer == 0 else f'{path}: C строка вместо None'
            if pointer == 0:
                return f'{path}: C NULL вместо строки {value!r}'
            length = self.read_int(pointer + self.member('P2cStr', 'length'), 'u16')
            data = self.read_pointer(pointer + self.member('P2cStr', 'data'))
            text = self.read(data, length).decode('utf-8', 'replace')
            return None if text == value else f'{path}: C {text!r} CPython {value!r}'
        if desc.startswith('T:'):
            name = desc[2:]
            if not isinstance(value, tuple):
                return f'{path}: CPython {type(value).__name__} вместо кортежа'
            members = self.fields[name]
            if len(members) != len(value):
                return f'{path}: длина кортежа C {len(members)} CPython {len(value)}'
            for (member, offset, _size, member_desc), item in zip(members, value):
                found = self.compare_value(item, address + offset, member_desc, f'{path}[{member[1:]}]')
                if found:
                    return found
            return None
        if desc.startswith('V:'):
            name = desc[2:]
            for member, offset, _size, member_desc in self.fields[name]:
                found = self.compare_value(getattr(value, member), address + offset, member_desc,
                                           f'{path}.{member}')
                if found:
                    return found
            return None
        if desc.startswith('N:'):
            name = desc[2:]
            has = self.read_int(address + self.member(name, 'has'), 'u8')
            if value is None:
                return None if not has else f'{path}: C значение вместо None'
            if not has:
                return f'{path}: C None вместо {value!r}'
            inner_desc = next(item[3] for item in self.fields[name] if item[0] == 'v')
            return self.compare_value(value, address + self.member(name, 'v'), inner_desc, path)
        if desc == 'R':
            numbers = struct.unpack('<4i', self.read(address, 16))
            actual = (value.x, value.y, value.w, value.h)
            return None if numbers == actual else f'{path}: C {numbers} CPython {actual}'
        if desc[0] in 'LQ':
            element_desc, _ = split_braces(desc[1:])
            pointer = self.read_pointer(address)
            if value is None:
                return None if pointer == 0 else f'{path}: C контейнер вместо None'
            if pointer == 0:
                return f'{path}: C NULL вместо контейнера'
            struct_name = 'P2cList' if desc[0] == 'L' else 'P2cDeque'
            length = self.read_int(pointer + self.member(struct_name, 'length'), 'u16')
            items = list(value)
            if length != len(items):
                return f'{path}: длина C {length} CPython {len(items)}'
            if path.rsplit('.', 1)[-1] in ('logos', 'text', 'sections'):
                return None
            data = self.read_pointer(pointer + self.member(struct_name, 'data'))
            size = self.desc_size(element_desc)
            head = 0
            capacity = length
            if desc[0] == 'Q':
                head = self.read_int(pointer + self.member('P2cDeque', 'head'), 'u16')
                capacity = self.read_int(pointer + self.member('P2cDeque', 'capacity'), 'u16')
            for index, item in enumerate(items):
                position = (head + index) % capacity if desc[0] == 'Q' else index
                found = self.compare_value(item, data + position * size, element_desc, f'{path}[{index}]')
                if found:
                    return found
            return None
        if desc[0] in 'DS':
            key_desc, rest = split_braces(desc[1:])
            value_desc = split_braces(rest)[0] if desc[0] == 'D' else None
            pointer = self.read_pointer(address)
            if pointer == 0:
                return None if value is None else f'{path}: C NULL вместо словаря'
            length = self.read_int(pointer + self.member('P2cDict', 'length'), 'u16')
            if length != len(value):
                return f'{path}: размер C {length} CPython {len(value)}'
            used = self.read_int(pointer + self.member('P2cDict', 'used'), 'u16')
            live = self.read_pointer(pointer + self.member('P2cDict', 'live'))
            keys = self.read_pointer(pointer + self.member('P2cDict', 'keys'))
            values = self.read_pointer(pointer + self.member('P2cDict', 'values'))
            key_size = self.desc_size(key_desc)
            entries = [index for index in range(used) if self.read_int(live + index, 'u8')]
            if desc[0] == 'S':
                c_keys = sorted(self.read_int(keys + index * key_size, key_desc) for index in entries)
                return None if c_keys == sorted(value) else f'{path}: множество C {c_keys} CPython {sorted(value)}'
            value_size = self.desc_size(value_desc)
            for (key, item), index in zip(value.items(), entries):
                found = self.compare_value(key, keys + index * key_size, key_desc, f'{path}{{ключ}}')
                if found:
                    return found
                found = self.compare_value(item, values + index * value_size, value_desc, f'{path}[{key!r}]')
                if found:
                    return found
            return None
        if desc == 'B':
            pointer = self.read_pointer(address)
            length = self.read_int(pointer + self.member('P2cBuf', 'length'), 'i32')
            if length != len(value):
                return f'{path}: длина bytes C {length} CPython {len(value)}'
            if length > 65536:
                return None
            data = self.read_pointer(pointer + self.member('P2cBuf', 'data'))
            content = self.read(data, length)
            if content != bytes(value):
                first = next(index for index in range(length) if content[index] != value[index])
                return f'{path}[{first}]: C {content[first]} CPython {value[first]}'
            return None
        if desc == 'F':
            identifier = self.read_int(address + self.member('P2cFn', 'id'), 'u8')
            if (value is None) != (identifier == 0):
                return f'{path}: вызываемое C id {identifier} CPython {value!r}'
            return None
        if desc == 'z':
            return None if value is None else f'{path}: CPython {value!r} вместо None'
        return None
