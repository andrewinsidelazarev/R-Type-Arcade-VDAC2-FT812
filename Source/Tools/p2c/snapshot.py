"""C-данные начального состояния: объекты снимка, константы модулей, строки."""
from __future__ import annotations

import dataclasses
from collections import deque

import pygame

from .errors import TranslationError
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, DequeT, DictT, ExtT, FnT, FontT, ImageT, IntT, ListT, NoneT,
    ObjT, OptT, SetT, StrT, T, TargetT, TupleT, ValT, VoidT, is_int_like, is_pointer,
)


def c_string(data: bytes) -> str:
    parts = []
    for byte in data:
        if 32 <= byte < 127 and chr(byte) not in '"\\?':
            parts.append(chr(byte))
        else:
            parts.append(f'\\{byte:03o}')
    return '"' + ''.join(parts) + '"'


class DataEmitter:
    """Статические C-определения графа объектов с учётом раскладки."""

    def __init__(self, compiler, crepr, layout, image_id) -> None:
        self.c = compiler
        self.p = compiler.program
        self.r = crepr
        self.layout = layout
        self.image_id = image_id
        self.symbols: dict[int, str] = {}
        self.alive: list[object] = []
        self.declarations: list[str] = []
        self.definitions: list[str] = []
        self.counter = 0

    def _name(self, prefix: str) -> str:
        self.counter += 1
        return f'p2c_{prefix}{self.counter}'

    # --- значения ---------------------------------------------------------------

    def initializer(self, t: T, value: object, where: str) -> str:
        if isinstance(t, IntT):
            if type(value) not in (int, bool):
                raise TranslationError(f'{where}: {value!r:.40} вместо целого')
            number = int(value)
            cint = self.r.cint(t)
            if not cint.holds(number):
                raise TranslationError(f'{where}: {number} вне {cint.c()}')
            if number == -(1 << 31):
                return '(-2147483647L - 1)'
            return f'{number}L' if cint.bits == 32 else str(number)
        if isinstance(t, BoolT):
            return '1' if value else '0'
        if isinstance(t, StrT):
            if not isinstance(value, str):
                raise TranslationError(f'{where}: {value!r:.40} вместо строки')
            return f'&p2c_str_{self.c.intern(value)}'
        if isinstance(t, OptT):
            inner = t.inner
            if value is None:
                if is_pointer(inner):
                    return 'NULL'
                if isinstance(inner, FnT):
                    return '{0, NULL}'
                return '{0}'
            code = self.initializer(inner, value, where)
            if is_pointer(inner) or isinstance(inner, FnT):
                return code
            return f'{{1, {code}}}'
        if isinstance(t, NoneT):
            return '0'
        if isinstance(t, ObjT):
            info = self.p.class_of(value)
            if info is None or info.frozen:
                raise TranslationError(f'{where}: {type(value).__name__} вместо объекта')
            return f'(P2cC_{self.p.root(info.name)} *)&{self.object_symbol(value, where)}' if t.cls != '*' else \
                f'(P2cObject *)&{self.object_symbol(value, where)}'
        if isinstance(t, ValT):
            if t.cls == 'Rect':
                return f'{{{value.x}, {value.y}, {value.w}, {value.h}}}'
            info = self.p.classes[t.cls]
            parts = []
            for item in dataclasses.fields(info.python):
                field_t = self.c.field_type(t.cls, item.name)
                parts.append(self.initializer(field_t, getattr(value, item.name), f'{where}.{item.name}'))
            return '{' + ', '.join(parts or ['0']) + '}'
        if isinstance(t, TupleT):
            if not isinstance(value, tuple) or len(value) != len(t.items):
                raise TranslationError(f'{where}: {value!r:.40} вместо кортежа из {len(t.items)}')
            return '{' + ', '.join(self.initializer(item_t, item, f'{where}[{index}]')
                                   for index, (item_t, item) in enumerate(zip(t.items, value))) + '}'
        if isinstance(t, (ListT, ArrayT)):
            return f'&{self.list_symbol(t, value, where)}'
        if isinstance(t, DequeT):
            return f'&{self.deque_symbol(t, value, where)}'
        if isinstance(t, (DictT, SetT)):
            return f'&{self.dict_symbol(t, value, where)}'
        if isinstance(t, BytesT):
            return f'&{self.bytes_symbol(value, where)}'
        if isinstance(t, ImageT):
            return f'{self.image_id(value)}UL'
        if isinstance(t, FnT):
            return self.function_initializer(value, where)
        if isinstance(t, (ExtT, FontT, TargetT)):
            return '0'
        raise TranslationError(f'{where}: нет инициализатора для {t}')

    def function_initializer(self, value: object, where: str) -> str:
        import types as pytypes
        if isinstance(value, pytypes.MethodType):
            owner = type(value.__self__).__name__
            key = ('extern', owner, value.__func__.__name__)
            number = self.c.fn_values.get(key)
            if number is None:
                raise TranslationError(f'{where}: вызываемое {owner}.{value.__func__.__name__} без номера')
            return f'{{{self.layout.fn_id_symbol(number)}, NULL}}'
        raise TranslationError(f'{where}: вызываемое значение {value!r:.40} в снимке не поддержано')

    # --- объекты ---------------------------------------------------------------

    def object_symbol(self, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        info = self.p.class_of(value)
        root = self.p.root(info.name)
        symbol = self._name('o')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        self.declarations.append(f'extern P2cC_{root} {symbol};')
        layout = self.layout.roots.get(root)
        parts = [f'.cls = {self.layout.class_id_symbol(info.name)}']
        attributes = vars(value)
        if layout is not None and layout.presence_bits:
            mask = 0
            for attr, bit in layout.presence_bits.items():
                if attr in attributes:
                    mask |= 1 << bit
            parts.append(f'.presence = 0x{mask:04X}u')
        if layout is not None:
            for attr, slot in sorted(layout.attribute_slot.items(), key=lambda item: item[1]):
                if attr not in attributes:
                    continue
                if slot not in layout.class_slots.get(info.name, set()):
                    continue
                field_t = self.c.field_type(info.name, attr)
                parts.append(f'.s{slot} = ' + self.initializer(field_t, attributes[attr], f'{where}.{attr}'))
        if self.p.list_base_of(info.name) is not None:
            elem_t = self.layout_items(info.name)
            data, length = self.list_data(elem_t, list(value), where)
            parts[0] = (f'.list = {{{self.layout.class_id_symbol(info.name)}, 0, {length}, {length}, '
                        f'(uint8_t *){data}}}')
        body = ',\n    '.join(parts)
        self.definitions.append(f'P2cC_{root} {symbol} = {{\n    {body}\n}};')
        return symbol

    def list_data(self, elem_t: T, items: list, where: str) -> tuple[str, int]:
        if not items:
            return 'NULL', 0
        symbol = self._name('d')
        ctype = self.r.ctype(elem_t)
        initializers = [self.initializer(elem_t, item, f'{where}[{index}]') for index, item in enumerate(items)]
        self.declarations.append(f'extern {ctype} {symbol}[{len(items)}];')
        body = ', '.join(initializers)
        self.definitions.append(f'{ctype} {symbol}[{len(items)}] = {{ {body} }};')
        return symbol, len(items)

    def list_symbol(self, t: T, value: object, where: str) -> str:
        key = (id(value), 'list')
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        if not isinstance(value, (list, tuple)):
            raise TranslationError(f'{where}: {type(value).__name__} вместо списка')
        symbol = self._name('l')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        data, length = self.list_data(t.elem, list(value), where)
        self.declarations.append(f'extern P2cList {symbol};')
        self.definitions.append(f'P2cList {symbol} = {{ {self.layout.container_class_symbol(t)}, 0, {length}, '
                                f'{length}, (uint8_t *){data} }};')
        return symbol

    def deque_symbol(self, t: DequeT, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        symbol = self._name('q')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        data, length = self.list_data(t.elem, list(value), where)
        self.declarations.append(f'extern P2cDeque {symbol};')
        self.definitions.append(f'P2cDeque {symbol} = {{ {self.layout.container_class_symbol(t)}, 0, {length}, '
                                f'{length}, 0, (uint8_t *){data} }};')
        return symbol

    def dict_symbol(self, t: T, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        symbol = self._name('m')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        if isinstance(t, SetT):
            keys = list(value)
            key_t, value_t = t.elem, None
            values = None
        else:
            keys = list(value.keys())
            values = list(value.values())
            key_t, value_t = t.k, t.v
        count = len(keys)
        key_c = self.r.ctype(key_t)
        if count:
            key_symbol, _ = self.list_data(key_t, keys, where + '.keys')
            live_symbol = self._name('d')
            self.declarations.append(f'extern uint8_t {live_symbol}[{count}];')
            self.definitions.append(f'uint8_t {live_symbol}[{count}] = {{ {", ".join("1" for _ in keys)} }};')
            if values is not None:
                value_symbol, _ = self.list_data(value_t, values, where + '.values')
            else:
                value_symbol = 'NULL'
        else:
            key_symbol = live_symbol = value_symbol = 'NULL'
        value_size = f'sizeof({self.r.ctype(value_t)})' if value_t is not None else '0'
        self.declarations.append(f'extern P2cDict {symbol};')
        self.definitions.append(
            f'P2cDict {symbol} = {{ {self.layout.container_class_symbol(t)}, 0, {count}, {count}, {count}, '
            f'sizeof({key_c}), {value_size}, (uint8_t *){live_symbol}, (uint8_t *){key_symbol}, '
            f'(uint8_t *){value_symbol} }};')
        return symbol

    def bytes_symbol(self, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        if not isinstance(value, (bytes, bytearray)):
            raise TranslationError(f'{where}: {type(value).__name__} вместо bytes')
        symbol = self._name('b')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        data = bytes(value)
        self.declarations.append(f'extern P2cBuf {symbol};')
        if data:
            data_symbol = self._name('d')
            self.declarations.append(f'extern uint8_t {data_symbol}[{len(data)}];')
            rows = []
            for offset in range(0, len(data), 64):
                rows.append(','.join(str(byte) for byte in data[offset:offset + 64]))
            self.definitions.append(f'uint8_t {data_symbol}[{len(data)}] = {{\n' + ',\n'.join(rows) + '\n};')
        else:
            data_symbol = 'NULL'
        self.definitions.append(f'P2cBuf {symbol} = {{ P2C_CLS_BUF, 0, {len(data)}UL, {len(data)}UL, '
                                f'(uint8_t *){data_symbol}, 0 }};')
        return symbol

    # --- строки и константы ---------------------------------------------------------

    def strings(self) -> list[str]:
        lines = []
        for text, number in sorted(self.c.strings.items(), key=lambda item: item[1]):
            data = text.encode('utf-8')
            lines.append(f'const P2cStr p2c_str_{number} = {{ P2C_CLS_STR, 0, {len(data)}, '
                         f'(const uint8_t *){c_string(data)} }};')
        return lines

    def constants(self) -> list[str]:
        lines = []
        for number, symbol in sorted(self.layout.constant_symbols.items(), key=lambda item: item[1]):
            value, t = self.c.constants[number]
            if isinstance(t, (ListT, ArrayT)):
                self.symbols.pop(id(value), None)
                data, length = self.list_data(t.elem, list(value), symbol)
                lines.append(f'P2cList {symbol} = {{ {self.layout.container_class_symbol(t)}, 0, {length}, '
                             f'{length}, (uint8_t *){data} }};')
            elif isinstance(t, (DictT, SetT)):
                inner = self.dict_symbol(t, value, symbol)
                lines.append(f'#define {symbol} {inner}')
            elif isinstance(t, BytesT):
                inner = self.bytes_symbol(value, symbol)
                lines.append(f'#define {symbol} {inner}')
            else:
                lines.append(f'const {self.r.ctype(t)} {symbol} = {self.initializer(t, value, symbol)};')
        return lines

    def layout_items(self, class_name: str):
        """Форма элементов наследника list: потоки или аннотация базы."""
        from .annotations import parse_annotation
        cell = self.c.field_cell(class_name, '<items>')
        if not isinstance(cell.t, BottomT):
            return cell.t
        info = self.p.classes[class_name]
        return parse_annotation(self.c, self.p.list_base_of(class_name), info.module, info.filename)

    def static_objects(self) -> list[str]:
        """Таблица статических объектов с заголовком (сброс отметок при смене эпохи)."""
        prefixes = ('p2c_o', 'p2c_l', 'p2c_q', 'p2c_m', 'p2c_b')
        names = [symbol for symbol in self.symbols.values() if symbol.startswith(prefixes)]
        lines = ['P2cObject *const p2c_statics[] = {']
        lines.extend(f'    (P2cObject *)&{name},' for name in names)
        if not names:
            lines.append('    NULL,')
        lines.append('};')
        lines.append(f'const uint16_t p2c_static_count = {len(names)};')
        return lines
