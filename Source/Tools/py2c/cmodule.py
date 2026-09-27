"""Сборка одного C-модуля и манифеста из результатов трансляции."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .ctypes_model import (
    ArrayType, BoolType, BufferType, ClassType, CType, ImageType, IntType,
    OptionalIntType, TargetType, TranslationError, TupleType,
)
from .heap import DataEmitter, EmittedData, Heap
from .translate import Translator, cname


def c_decl(value_type: CType, name: str) -> str:
    if isinstance(value_type, IntType):
        return f'{value_type.c()} {name}'
    if isinstance(value_type, BoolType):
        return f'uint8_t {name}'
    if isinstance(value_type, OptionalIntType):
        return f'Py2cOptI32 {name}'
    if isinstance(value_type, ClassType):
        return f'{value_type.name} *{name}'
    if isinstance(value_type, ArrayType):
        return f'{value_type.struct_name()} *{name}'
    if isinstance(value_type, BufferType):
        return f'Py2cBuffer *{name}'
    if isinstance(value_type, ImageType):
        return f'uint16_t {name}'
    if isinstance(value_type, TupleType):
        return f'{value_type.c()} {name}'
    if isinstance(value_type, TargetType):
        return f'void *{name}'
    raise TranslationError(f'нет объявления для {value_type}')


def field_decl(value_type: CType, name: str) -> str:
    """Поле структуры хранит заявленную ширину."""
    if isinstance(value_type, IntType):
        return f'{value_type.c()} {name}'
    return c_decl(value_type, name)


@dataclass
class CModule:
    source: str
    manifest: dict
    data: EmittedData
    emitter: DataEmitter


def build_module(translator: Translator, heap: Heap, header_name: str,
                 roots: dict[str, tuple[str, list[str]]]) -> CModule:
    """roots: имя корня снимка → (класс, список методов-точек входа)."""
    emitter = DataEmitter(heap)
    data = emitter.emit_roots()
    out: list[str] = [
        '/* Сгенерировано py2c из AST активной Python-игры. Не править вручную. */',
        f'#include "{header_name}"',
        '#include "py2c_runtime.h"',
        '',
    ]
    class_names = list(heap.fields)
    for name in class_names:
        out.append(f'typedef struct {name} {name};')
    for array_type in unique_array_types(heap):
        out.append(f'typedef struct {{ {array_type.element_c()} *data; uint16_t length; '
                   f'uint16_t capacity; uint8_t page; }} {array_type.struct_name()};')
    for tuple_type in sorted(heap.tuple_types, key=lambda item: item.key()):
        fields = ' '.join(field_decl(element, f'v{index}') + ';'
                          for index, element in enumerate(tuple_type.elements))
        out.append(f'typedef struct {{ {fields} }} {tuple_type.c()};')
    out.append('')
    for name in class_names:
        out.append(f'struct {name} {{')
        for attribute, field_type in heap.fields[name].items():
            out.append(f'    {field_decl(field_type, attribute)};')
        if not heap.fields[name]:
            out.append('    uint8_t py2c_empty;')
        out.append('};')
    out.append('')
    used_text = chr(10).join(line for plan in translator.queue for line in plan.lines)
    out.extend(array_accessors(heap, used_text))
    out.extend(membership_functions(translator))
    for symbol, array_type, value in translator.const_arrays.values():
        body = ', '.join(str(item) for item in value) or '0'
        out.append(f'static {array_type.element.c()} {symbol}_data[{max(1, len(value))}] = {{ {body} }};')
        out.append(f'static {array_type.struct_name()} {symbol} = '
                   f'{{ {symbol}_data, {len(value)}, {len(value)}, 0 }};')
    out.append('')
    out.extend(data.declarations)
    out.extend(data.definitions)
    out.append('')
    plans = translator.queue
    for plan in plans:
        out.append(prototype(plan) + ';')
    out.append('')
    for plan in plans:
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
    manifest_roots = {}
    for root_name, (class_name, methods) in roots.items():
        symbol = data.root_symbols[root_name]
        for method in methods:
            plan = translator.plans[(class_name, method)]
            extra = ', 0' if len(plan.params) == 2 else ''
            if len(plan.params) > 2:
                raise TranslationError('точка входа с параметрами кроме цели вывода')
            entry = f'py2c_entry_{root_name}_{method.lstrip("_")}'
            out.append(f'PY2C_EXPORT void {entry}(void) {{ {plan.c_name}(&{symbol}{extra}); }}')
            manifest_roots.setdefault(root_name, {})[method] = entry
    out.append('')
    dump_lines, layout = dump_function(emitter, heap)
    out.extend(dump_lines)
    out.extend(external_binder(data))
    manifest = {
        'roots': manifest_roots,
        'externals': [{'symbol': item.symbol, 'kind': item.kind, 'length': item.length,
                       'element': item.element.key() if item.element else 'u8',
                       'mutable': item.mutable, 'bytes': len(item.payload)}
                      for item in data.externals],
        'images': len(heap.images),
        'functions': [{'owner': plan.owner, 'name': plan.name, 'c': plan.c_name,
                       'line': plan.node.lineno, 'file': plan.filename.rsplit('\\', 1)[-1],
                       'pure': plan.pure} for plan in plans],
        'raise_messages': translator.raise_messages,
        'dump_layout': layout,
    }
    return CModule('\n'.join(out) + '\n', manifest, data, emitter)


def prototype(plan) -> str:
    params = ', '.join(c_decl(value_type, cname(name))
                       for name, value_type in plan.params) or 'void'
    returns = plan.returns
    if isinstance(returns, IntType):
        result = returns.c()
    elif isinstance(returns, TupleType):
        result = returns.c()
    elif hasattr(returns, 'c') and returns.key() != 'void':
        result = c_decl(returns, '').strip()
    else:
        result = 'void'
    return f'{result} {plan.c_name}({params})'


def unique_array_types(heap: Heap) -> list[ArrayType]:
    """Один C-тип на ключ; вложенные массивы после своих элементов."""
    unique: dict[str, ArrayType] = {}
    for array_type in heap.array_types:
        unique.setdefault(array_type.key(), array_type)

    def depth(value_type: CType) -> int:
        return 1 + depth(value_type.element) if isinstance(value_type, ArrayType) else 0
    return sorted(unique.values(), key=lambda item: (depth(item), item.key()))


def array_accessors(heap: Heap, used_text: str | None = None) -> list[str]:
    """Методы доступа к массивам; при used_text — только упомянутые в коде функций."""
    lines = []
    for array_type in unique_array_types(heap):
        key = array_type.key()
        if used_text is not None:
            wanted = {name for name in (f'py2c_get_{key}', f'py2c_get_{key}_any', f'py2c_set_{key}',
                                        f'py2c_set_{key}_any', f'py2c_append_{key}')
                      if re.search(r'\b' + name + r'\(', used_text)}
            if f'py2c_get_{key}_any' in wanted:
                wanted.add(f'py2c_get_{key}')
            if f'py2c_set_{key}_any' in wanted:
                wanted.add(f'py2c_set_{key}')
            lines.extend(_accessor_lines(array_type, wanted))
        else:
            lines.extend(_accessor_lines(array_type, None))
    return lines


def _accessor_lines(array_type: ArrayType, wanted: set[str] | None) -> list[str]:
    struct = array_type.struct_name()
    element = array_type.element_c()
    key = array_type.key()
    store = element
    if isinstance(array_type.element, IntType):
        conversion = ('(int32_t)' if array_type.element.bits < 32 or not array_type.element.signed
                      else '')
        result = 'int32_t'
    else:
        conversion = ''
        result = element
    bodies = {
        f'py2c_get_{key}': [
            f'{result} py2c_get_{key}(const {struct} *array, int32_t index) {{',
            '    index = PY2C_INDEX_NN(index, array->length);',
            '    PY2C_MAP(array->page);',
            f'    return {conversion}array->data[(uint16_t)index];',
            '}'],
        f'py2c_get_{key}_any': [
            f'{result} py2c_get_{key}_any(const {struct} *array, int32_t index) {{',
            f'    return py2c_get_{key}(array, py2c_index(index, array->length));',
            '}'],
        f'py2c_set_{key}': [
            f'void py2c_set_{key}({struct} *array, int32_t index, {store} value) {{',
            '    index = PY2C_INDEX_NN(index, array->length);',
            '    PY2C_MAP(array->page);',
            '    array->data[(uint16_t)index] = value;',
            '}'],
        f'py2c_set_{key}_any': [
            f'void py2c_set_{key}_any({struct} *array, int32_t index, {store} value) {{',
            f'    py2c_set_{key}(array, py2c_index(index, array->length), value);',
            '}'],
        f'py2c_append_{key}': [
            f'void py2c_append_{key}({struct} *array, {store} value) {{',
            '    if (array->length >= array->capacity) { py2c_raise(PY2C_E_CAPACITY); return; }',
            '    PY2C_MAP(array->page);',
            '    array->data[array->length++] = value;',
            '}'],
    }
    lines: list[str] = []
    for name, body in bodies.items():
        if wanted is None or name in wanted:
            lines.extend(body)
    return lines


def membership_functions(translator: Translator) -> list[str]:
    lines = []
    for values, name in translator.membership.items():
        if not values:
            lines.append(f'uint8_t {name}(int32_t value) {{ (void)value; return 0; }}')
            continue
        low, high = values[0], values[-1]
        # Битовая карта только если она не больше отсортированного массива.
        if high - low < 16384 and (high - low + 8) // 8 <= 4 * len(values):
            bits = bytearray((high - low + 8) // 8)
            for value in values:
                bits[(value - low) >> 3] |= 1 << ((value - low) & 7)
            lines += [
                f'static const uint8_t {name}_bits[{len(bits)}] = {{ {", ".join(map(str, bits))} }};',
                f'uint8_t {name}(int32_t value) {{',
                '    uint16_t offset;',
                f'    if (value < {low}L || value > {high}L) return 0;',
                f'    offset = (uint16_t)(value - {low}L);',
                f'    return ({name}_bits[offset >> 3] >> (offset & 7)) & 1;',
                '}',
            ]
        else:
            items = ', '.join(f'{value}L' for value in values)
            lines += [
                f'static const int32_t {name}_items[{len(values)}] = {{ {items} }};',
                f'uint8_t {name}(int32_t value) {{',
                f'    uint16_t low = 0, high = {len(values)};',
                '    while (low < high) {',
                '        uint16_t middle = (uint16_t)((low + high) >> 1);',
                f'        if ({name}_items[middle] < value) low = middle + 1; else high = middle;',
                '    }',
                f'    return low < {len(values)} && {name}_items[low] == value;',
                '}',
            ]
    return lines


def dump_function(emitter: DataEmitter, heap: Heap) -> tuple[list[str], list[dict]]:
    """Выгрузка изменяемого состояния в байты; тот же порядок строит сверщик на Python."""
    objects = []
    for key, symbol in emitter.symbols.items():
        objects.append(symbol)
    by_symbol = {symbol: None for symbol in objects}
    python_objects = {id_: obj for obj in emitter.alive for id_ in [id(obj)]}
    layout = []
    lines = [
        'static uint8_t *py2c_dump_cursor;',
        'static void py2c_dump_byte(uint8_t value) { *py2c_dump_cursor++ = value; }',
        'static void py2c_dump_i32(int32_t value) {',
        '    py2c_dump_byte((uint8_t)value); py2c_dump_byte((uint8_t)(value >> 8));',
        '    py2c_dump_byte((uint8_t)(value >> 16)); py2c_dump_byte((uint8_t)(value >> 24));',
        '}',
        'PY2C_EXPORT uint32_t py2c_dump(uint8_t *output) {',
        '    uint16_t index;',
        '    py2c_dump_cursor = output;',
    ]
    symbol_of = {object_id: symbol for object_id, symbol in emitter.symbols.items()}
    for object_id, symbol in emitter.symbols.items():
        value = python_objects[object_id]
        info = heap.program.class_of(value)
        if info is not None:
            for attribute, field_type in heap.fields.get(info.name, {}).items():
                access = f'{symbol}.{attribute}'
                entry = {'symbol': symbol, 'object': object_id, 'field': attribute}
                if isinstance(field_type, (IntType, BoolType)):
                    lines.append(f'    py2c_dump_i32((int32_t){access});')
                    entry['kind'] = 'int'
                elif isinstance(field_type, OptionalIntType):
                    lines.append(f'    py2c_dump_i32({access}.present ? {access}.value : 0);')
                    lines.append(f'    py2c_dump_byte({access}.present);')
                    entry['kind'] = 'opt'
                elif isinstance(field_type, (ClassType, ArrayType, BufferType)):
                    # Ссылка сравнивается как имя объекта снимка.
                    targets = [s for oid, s in symbol_of.items()
                               if _compatible(python_objects[oid], field_type, heap)]
                    lines.append(f'    index = 0xFFFF;')
                    for position, target in enumerate(targets):
                        lines.append(f'    if ((void *){access} == (void *)&{target}) index = {position};')
                    lines.append('    py2c_dump_byte((uint8_t)index); py2c_dump_byte((uint8_t)(index >> 8));')
                    entry['kind'] = 'ref'
                    entry['targets'] = targets
                elif isinstance(field_type, ImageType):
                    lines.append(f'    py2c_dump_i32({access});')
                    entry['kind'] = 'image'
                else:
                    raise TranslationError(f'выгрузка поля {info.name}.{attribute} не поддержана')
                layout.append(entry)
        elif isinstance(value, (bytearray, list)):
            entry = {'symbol': symbol, 'object': object_id}
            if isinstance(value, bytearray):
                entry['kind'] = 'buffer'
                external = any(item.symbol == symbol for item in emitter.output.externals)
                lines.append(f'    py2c_dump_i32((int32_t){symbol}.length);')
                lines.append(f'    for (py2c_dump_index = 0; py2c_dump_index < {symbol}.length; ++py2c_dump_index)')
                lines.append(f'        py2c_dump_byte(PY2C_BUF_READ(&{symbol}, py2c_dump_index));')
                entry['external'] = external
            else:
                array_type = _array_type_of(emitter, symbol, heap)
                entry['kind'] = 'array'
                entry['element'] = array_type.element.key()
                lines.append(f'    py2c_dump_i32((int32_t){symbol}.length);')
                if isinstance(array_type.element, IntType):
                    lines.append(f'    PY2C_MAP({symbol}.page);')
                    lines.append(f'    for (py2c_dump_index = 0; py2c_dump_index < {symbol}.length; ++py2c_dump_index)')
                    lines.append(f'        py2c_dump_i32((int32_t){symbol}.data[py2c_dump_index]);')
                else:
                    targets = [s for oid, s in symbol_of.items()
                               if _compatible(python_objects[oid], array_type.element, heap)]
                    entry['targets'] = targets
                    lines.append(f'    for (py2c_dump_index = 0; py2c_dump_index < {symbol}.length; ++py2c_dump_index) {{')
                    lines.append('        index = 0xFFFF;')
                    for position, target in enumerate(targets):
                        lines.append(f'        if ((void *){symbol}.data[py2c_dump_index] == (void *)&{target}) index = {position};')
                    lines.append('        py2c_dump_byte((uint8_t)index); py2c_dump_byte((uint8_t)(index >> 8));')
                    lines.append('    }')
            layout.append(entry)
    lines.append('    return (uint32_t)(py2c_dump_cursor - output);')
    lines.append('}')
    lines.insert(0, 'static uint32_t py2c_dump_index;')
    del by_symbol
    return lines, layout


def _array_type_of(emitter: DataEmitter, symbol: str, heap: Heap) -> ArrayType:
    return emitter.array_types[symbol]


def _compatible(value: object, field_type: CType, heap: Heap) -> bool:
    if isinstance(field_type, ClassType):
        info = heap.program.class_of(value)
        return info is not None and info.name == field_type.name
    if isinstance(field_type, BufferType):
        return isinstance(value, (bytes, bytearray))
    if isinstance(field_type, ArrayType):
        return isinstance(value, (list, tuple))
    return False


def external_binder(data: EmittedData) -> list[str]:
    lines = ['PY2C_EXPORT void py2c_bind_external(uint16_t index, void *pointer) {', '    switch (index) {']
    for position, item in enumerate(data.externals):
        target = f'{item.symbol}.data'
        cast = '(uint8_t *)' if item.kind == 'buffer' else f'({item.element.c()} *)'
        lines.append(f'    case {position}: {target} = {cast}pointer; break;')
    lines += ['    default: py2c_raise(PY2C_E_INDEX);', '    }', '}',
              f'PY2C_EXPORT uint16_t py2c_external_count(void) {{ return {len(data.externals)}; }}']
    return lines


def write_manifest(path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n',
                    encoding='utf-8', newline='\n')
