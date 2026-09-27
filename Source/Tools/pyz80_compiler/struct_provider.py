"""Общий планировщик форматов struct и заготовка провайдера объектной VM.

format_plan используется статическим buffer_backend: pack_into/unpack_from
проверены на ПК и Z80. Bootstrap/таблицы ниже в объектную VM НЕ подключены;
CONTRACT описывает именно её будущий провайдер, не готовое полное API struct.
Семантика сверяется с https://docs.python.org/3.12/library/struct.html и CPython.
"""
import ast
from pathlib import Path
import re
import struct
import sysconfig

EXPORTS = ('pack', 'pack_into', 'unpack', 'unpack_from', 'calcsize')
INTRINSICS = {'_pyz80_struct_function': 'struct-function'}
SYMBOLS = EXPORTS
CONTRACT = {
    'exports': list(EXPORTS),
    'formats': 'sealed string constants; explicit < > !; b B h H i I l L x and decimal repeats',
    'layout': 'compiler parses formats and verifies sizes with pinned CPython struct; numeric runs live in banked field words',
    'values': 'native bytes/bytearray; bool/int32; unsigned 32-bit results above INT32_MAX fail without wrapping',
    'budget': 'at most one payload byte per VM step; no runtime string parser or recursive VM execution',
    'pending': ['iter_unpack and Struct objects', 'native alignment/endian formats', 'dynamic format strings/bytes formats',
                'float/64-bit/string/Pascal/bool fields', 'custom buffer and __index__ protocols',
                'keyword calls', 'catchable struct.error', 'final banked heap/stack/frame-time proof'],
}


def source_path() -> Path:
    return (Path(sysconfig.get_path('stdlib')) / 'struct.py').resolve()


def is_provider_source(name: str, path: Path, source: str) -> bool:
    if name != 'struct' or path.resolve() != source_path():
        return False
    if source != path.read_text(encoding='utf-8'):
        raise ValueError('struct source changed before specialization')
    return True


def bootstrap(source: str) -> str:
    return repr(ast.get_docstring(ast.parse(source), clean=False)) + '\n' + '''def _pyz80_struct_function(index):
    raise NotImplementedError('struct-function')
''' + ''.join(f'{name} = _pyz80_struct_function({i})\n' for i, name in enumerate(EXPORTS))


def format_plan(value: str):
    """Коды 0=x, 1/2=u8/i8, 3/4=u16/i16, 5/6=u32/i32; бит 7=big endian."""
    if not isinstance(value, str) or (value and value[0] not in '<>!'):
        return None
    try:
        expected = struct.calcsize(value)
    except (struct.error, UnicodeError):
        return None
    if expected > 65535:
        return None
    big = bool(value and value[0] in '>!')
    cursor, size, values, runs = int(bool(value)), 0, 0, []
    types = {'x': (0, 1), 'B': (1, 1), 'b': (2, 1), 'H': (3, 2),
             'h': (4, 2), 'I': (5, 4), 'L': (5, 4), 'i': (6, 4), 'l': (6, 4)}
    while cursor < len(value):
        if value[cursor] in ' \t\n\r\v\f':
            cursor += 1
            continue
        match = re.match(r'([0-9]*)([xBbHhILil])', value[cursor:])
        if not match:
            return None
        count = int(match[1]) if match[1] else 1
        code, width = types[match[2]]
        if count:
            runs.append((count, code | (128 if big else 0)))
            size += count * width
            values += count if code else 0
        cursor += len(match[0])
    if size != expected or size > 65535 or values > 65535:
        return None
    return {'bytes': size, 'values': values, 'runs': runs}


def append_format_tables(symbols, field_keys):
    records = []
    for value, symbol in symbols.items():
        plan = format_plan(value)
        if plan is None:
            continue
        start = len(field_keys)
        for repeat, code in plan['runs']:
            field_keys.extend((repeat, code))
        if len(field_keys) > 65535:
            raise ValueError('struct format words exceed uint16 bank table')
        records.append((symbol, start, len(plan['runs']), plan['bytes'], plan['values']))
    return records
