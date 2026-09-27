"""C-модуль для TS-Config: резидентные объекты с кодовой инициализацией и страницы.

SDCC без CRT не копирует инициализаторы, поэтому начальное состояние снимка
задаёт сгенерированная функция `py2c_init()`. Крупные массивы и буферы лежат
на физических страницах и читаются через окно 2; изменяемые получают рабочую
страницу и исходную копию для повторной инициализации.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cmodule import (
    array_accessors, c_decl, field_decl, membership_functions, prototype,
    unique_array_types,
)
from .ctypes_model import (
    ArrayType, BoolType, BufferType, ClassType, ImageType, IntType,
    OptionalIntType, TranslationError,
)
from .heap import DataEmitter, Heap
from .translate import Translator, cname

PAGE_SIZE = 0x4000


@dataclass
class PagePlacement:
    symbol: str
    page: int
    pages: int
    pristine: int | None
    payload: bytes
    offset: int = 0


@dataclass
class Z80Module:
    header: str
    source: str
    placements: list[PagePlacement] = field(default_factory=list)
    emitter: DataEmitter | None = None
    manifest: dict = field(default_factory=dict)


def build_z80_module(translator: Translator, heap: Heap, roots: dict[str, tuple[str, list[str]]],
                     first_page: int, stem: str, image_ids: dict[int, int] | None = None) -> Z80Module:
    emitter = DataEmitter(heap)
    if image_ids is not None:
        # Номера изображений задаёт аппаратный адаптер (handle/cell FT812).
        emitter.fixed_images = image_ids
    data = emitter.emit_roots()
    placements: list[PagePlacement] = []
    page = first_page
    # Многостраничные буферы — каждый с начала своих страниц; остальные данные
    # плотно упаковываются: изменяемые и неизменяемые в разные страницы.
    packs = {False: [None, 0], True: [None, 0]}     # изменяемость → [страница, занято]
    for record in emitter.records:
        if record['kind'] not in ('buffer', 'array') or not record['external']:
            continue
        payload = record['data'] if record['kind'] == 'buffer' else record['payload']
        count = max(1, (len(payload) + PAGE_SIZE - 1) // PAGE_SIZE)
        if count > 1:
            if record['kind'] == 'array' or record['mutable']:
                raise TranslationError(f'{record["where"]}: изменяемые данные или массив больше страницы')
            placements.append(PagePlacement(record['symbol'], page, count, None, payload))
            page += count
            continue
        pack = packs[record['mutable']]
        if pack[0] is None or pack[1] + len(payload) > PAGE_SIZE:
            pack[0] = page
            pack[1] = 0
            page += 2 if record['mutable'] else 1
        placement = PagePlacement(record['symbol'], pack[0], 1,
                                  pack[0] + 1 if record['mutable'] else None, payload, pack[1])
        pack[1] += len(payload)
        placements.append(placement)
    if page > 0x100:
        raise TranslationError(f'страницы данных кончились: нужно до {page:#x}')

    header = [f'/* Сгенерировано py2c для TS-Config. Не править вручную. */',
              f'#ifndef PY2C_{stem.upper()}_H', f'#define PY2C_{stem.upper()}_H',
              '#include "py2c_platform.h"', '#include "py2c_runtime.h"', '']
    class_names = list(heap.fields)
    for name in class_names:
        header.append(f'typedef struct {name} {name};')
    for array_type in unique_array_types(heap):
        header.append(f'typedef struct {{ {array_type.element_c()} *data; uint16_t length; '
                      f'uint16_t capacity; uint8_t page; }} {array_type.struct_name()};')
    for name in class_names:
        header.append(f'struct {name} {{')
        for attribute, field_type in heap.fields[name].items():
            header.append(f'    {field_decl(field_type, attribute)};')
        if not heap.fields[name]:
            header.append('    uint8_t py2c_empty;')
        header.append('};')
    for root_name, symbol in data.root_symbols.items():
        class_name = roots[root_name][0]
        header.append(f'extern {class_name} {symbol};')
        header.append(f'#define PY2C_ROOT_{root_name.upper()} (&{symbol})')
    header.append('void py2c_init(void);')
    for plan in translator.queue:
        header.append(prototype(plan) + ';')
    header += ['#endif', '']

    out = [f'/* Сгенерировано py2c для TS-Config. Не править вручную. */',
           f'#include "{stem}.h"', '#include <string.h>', '']
    used_text = '\n'.join(line for plan in translator.queue for line in plan.lines)
    out.extend(array_accessors(heap, used_text))
    out.extend(membership_functions(translator))
    for symbol, array_type, value in translator.const_arrays.values():
        body = ', '.join(str(item) for item in value) or '0'
        out.append(f'static const {array_type.element.c()} {symbol}_const[{max(1, len(value))}] = {{ {body} }};')
        out.append(f'static {array_type.struct_name()} {symbol};')
    placement_of = {item.symbol: item for item in placements}
    init: list[str] = ['void py2c_init(void) {']
    # Рабочие страницы изменяемых данных восстанавливаются из исходных копий.
    for work, pristine in sorted({(item.page, item.pristine) for item in placements
                                  if item.pristine is not None}):
        init.append(f'    py2c_page_copy({work}, {pristine});')
    for symbol, array_type, value in translator.const_arrays.values():
        init.append(f'    {symbol}.data = ({array_type.element.c()} *){symbol}_const; '
                    f'{symbol}.length = {len(value)}; {symbol}.capacity = {len(value)}; {symbol}.page = 0;')
    for record in emitter.records:
        symbol = record['symbol']
        if record['kind'] == 'object':
            out.append(f'{record["class"]} {symbol};')
            for attribute, field_type, initializer in record['fields']:
                if isinstance(field_type, OptionalIntType):
                    value, present = initializer.strip('{}').split(',')
                    init.append(f'    {symbol}.{attribute}.value = {value.strip()}; '
                                f'{symbol}.{attribute}.present = {present.strip()};')
                else:
                    init.append(f'    {symbol}.{attribute} = {initializer};')
        elif record['kind'] == 'buffer':
            out.append(f'Py2cBuffer {symbol};')
            if record['external']:
                placement = placement_of[symbol]
                init.append(f'    {symbol}.data = (uint8_t *)0x{0x8000 + placement.offset:04X}u; '
                            f'{symbol}.length = {record["length"]}UL; {symbol}.page = {placement.page};')
            else:
                length = max(1, record['length'])
                body = ', '.join(str(byte) for byte in record['data']) or '0'
                out.append(f'static const uint8_t {symbol}_const[{length}] = {{ {body} }};')
                if record['mutable']:
                    out.append(f'static uint8_t {symbol}_data[{length}];')
                    init.append(f'    memcpy({symbol}_data, {symbol}_const, {length});')
                    init.append(f'    {symbol}.data = {symbol}_data;')
                else:
                    init.append(f'    {symbol}.data = (uint8_t *){symbol}_const;')
                init.append(f'    {symbol}.length = {record["length"]}UL; {symbol}.page = 0;')
        else:
            array_type: ArrayType = record['type']
            struct = array_type.struct_name()
            element_c = array_type.element_c()
            out.append(f'{struct} {symbol};')
            if record['external']:
                placement = placement_of[symbol]
                init.append(f'    {symbol}.data = ({element_c} *)0x{0x8000 + placement.offset:04X}u; '
                            f'{symbol}.length = {record["length"]}; {symbol}.capacity = {record["capacity"]}; '
                            f'{symbol}.page = {placement.page};')
                continue
            capacity = record['capacity']
            initializers = record['initializers'] or ['0']
            const_type = element_c if not element_c.endswith('*') else element_c + ' const'
            out.append(f'static {"const " if not element_c.endswith("*") else ""}{const_type} '
                       f'{symbol}_const[{max(1, len(initializers))}] = {{ {", ".join(initializers)} }};')
            if record['mutable']:
                out.append(f'static {element_c} {symbol}_data[{capacity}];')
                if record['length']:
                    init.append(f'    memcpy({symbol}_data, {symbol}_const, sizeof({symbol}_const));')
                init.append(f'    {symbol}.data = {symbol}_data;')
            else:
                init.append(f'    {symbol}.data = ({element_c} *){symbol}_const;')
            init.append(f'    {symbol}.length = {record["length"]}; {symbol}.capacity = {capacity}; '
                        f'{symbol}.page = 0;')
    init.append('}')
    out.append('')
    for plan in translator.queue:
        out.append(prototype(plan) + ' {')
        for name, value_type in plan.locals.items():
            out.append(f'    {c_decl(value_type, cname(name))};')
        for name, value_type in plan.temps.items():
            if isinstance(value_type, tuple):
                element = value_type[2]
                out.append(f'    {element.c()} {name}_data[{value_type[1]}];')
                out.append(f'    {ArrayType(element, False).struct_name()} {name};')
            else:
                out.append(f'    {c_decl(value_type, name)};')
        out.extend(plan.lines)
        out.append('}')
        out.append('')
    out.extend(init)
    manifest = {
        'placements': [{'symbol': item.symbol, 'page': item.page, 'pages': item.pages, 'offset': item.offset,
                        'pristine': item.pristine, 'bytes': len(item.payload)} for item in placements],
        'raise_messages': translator.raise_messages,
        'images': len(heap.images),
        'root_symbols': data.root_symbols,
        'last_page': page - 1,
    }
    return Z80Module('\n'.join(header) + '\n', '\n'.join(out) + '\n', placements, emitter, manifest)
