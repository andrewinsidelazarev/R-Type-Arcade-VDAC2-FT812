"""Конечная специализация целого байтового метода по неизменяемым ресурсам.

Таблица хранит результат вычислений, а не кадры игры. Каждый ключ и каждое
размещение выполняются исходным Python. Чтение изменяемой памяти, повторная
запись одного байта и зависимость данных от размещения запрещают оптимизацию.
За пределами доказанного декартова произведения вызывающий использует backend.
"""
import ast
import copy
import hashlib
import itertools
import struct
from dataclasses import dataclass
from types import SimpleNamespace

from .buffer_backend import compile_buffer_function


class NotTableable(ValueError):
    pass


class WriteOnly:
    def __init__(self, slot, size):
        self.slot = slot
        self.size = size
        self.writes = {}


class StructTrace:
    @staticmethod
    def unpack_from(fmt, data, offset=0):
        if type(data) is not bytes:
            raise NotTableable('Таблица не может читать изменяемое состояние')
        return struct.unpack_from(fmt, data, offset)

    @staticmethod
    def pack_into(fmt, target, offset, *values):
        if not isinstance(target, WriteOnly):
            raise NotTableable('Не связан получатель записи')
        data = struct.pack(fmt, *values)
        if offset < 0:
            offset += target.size
        if offset < 0 or offset + len(data) > target.size:
            raise struct.error('Запись вне целевого буфера')
        for address, byte in enumerate(data, offset):
            if address in target.writes:
                raise NotTableable('Повторная запись: перестановка ещё не доказана')
            target.writes[address] = byte

    calcsize = staticmethod(struct.calcsize)


def compact_writes(targets):
    active = [target for target in targets if target.writes]
    if len(active) != 1:
        raise NotTableable('Нужен ровно один записанный буфер')
    target = active[0]
    runs = []
    payload = bytearray()
    for address in sorted(target.writes):
        if runs and runs[-1][0] + runs[-1][1] == address:
            runs[-1][1] += 1
        else:
            runs.append([address, 1])
        payload.append(target.writes[address])
    return target.slot, runs, bytes(payload)


@dataclass
class WriteTable:
    records: bytes
    lookup: list
    slots: list
    placements: list
    manifest: dict


def compile_write_table(source, owner, method, *, immutable_fields, target_field,
                        target_count, target_bytes, key_domains, placement, placements):
    fields = {'self.' + name: 'bytes' for name in immutable_fields}
    fields['self.' + target_field] = 'list[bytearray]'
    checked = compile_buffer_function(source, method, owner=owner, fields=fields, memory='view')
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    original = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    # Не исполнять модуль/конструктор и произвольные Python-провайдеры на ПК.
    allowed_calls = {'range', 'bool', 'int', 'min', 'max', 'struct.unpack_from',
                     'struct.pack_into', 'struct.calcsize'}
    for node in ast.walk(original):
        if isinstance(node, ast.Call) and ast.unparse(node.func) not in allowed_calls:
            raise NotTableable('Вызов не разрешён для специализации: ' + ast.unparse(node.func))
    if any(type(value) is not bytes for value in immutable_fields.values()):
        raise NotTableable('Ресурс должен быть неизменяемым bytes')
    parameters = [arg.arg for arg in original.args.args[1:]]
    if set(parameters) != {*key_domains, placement}:
        raise NotTableable('Все параметры должны иметь явный конечный домен')
    domains = [list(values) for values in key_domains.values()]
    placements = list(placements)
    if not 1 <= target_count <= 255 or not 1 <= target_bytes <= 65535:
        raise NotTableable('Размеры целевого ABI вне поддержанного диапазона')
    if not placements or any(not domain for domain in domains):
        raise NotTableable('Пустой домен')
    for domain in [*domains, placements]:
        if len(set(domain)) != len(domain) or any(type(v) is not int or not -2**31 <= v < 2**31 for v in domain):
            raise NotTableable('Нужны уникальные i32-ключи')
    function = copy.deepcopy(original)
    namespace = {'__builtins__': {}, 'struct': StructTrace, 'int': int, 'bool': bool,
                 'range': range, 'min': min, 'max': max}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<write-table>', 'exec'), namespace)
    fn = namespace[method]
    records = []
    record_ids = {}
    lookup = []
    slots = []
    layouts = None
    failures = []
    evaluations = 0
    for values in itertools.product(*domains):
        key = dict(zip(key_domains, values))
        first = None
        key_layouts = []
        failed = False
        for position in placements:
            targets = [WriteOnly(i, target_bytes) for i in range(target_count)]
            instance = SimpleNamespace(**immutable_fields, **{target_field: targets})
            arguments = {**key, placement: position}
            evaluations += 1
            try:
                result = fn(instance, *(arguments[name] for name in parameters))
            except (struct.error, IndexError) as error:
                failures.append({'key': list(values), placement: position, 'error': type(error).__name__})
                failed = True
                break
            if result is not None:
                raise NotTableable('Возвращаемое значение не связано')
            slot, runs, payload = compact_writes(targets)
            if first is None:
                first = slot, payload
            if first != (slot, payload):
                raise NotTableable('Данные или получатель зависят от размещения')
            key_layouts.append(runs)
        if failed:
            lookup.append(65535)
            slots.append(255)
            continue
        if layouts is None:
            layouts = key_layouts
        if layouts != key_layouts:
            raise NotTableable('Адреса зависят от ключа данных')
        slot, payload = first
        if records and len(payload) != len(records[0]):
            raise NotTableable('Размер записи непостоянен')
        if payload not in record_ids:
            record_ids[payload] = len(records)
            records.append(payload)
        lookup.append(record_ids[payload])
        slots.append(slot)
    if not records or len(records) >= 65535:
        raise NotTableable('Нет записей или слишком много записей')
    payload_bytes = len(records[0])
    stride = 1 << (payload_bytes - 1).bit_length()
    if stride > 16384 or any(size > 255 for runs in layouts for _, size in runs):
        raise NotTableable('Нужна поддержка более крупных записей/серий')
    blob = b''.join(record + bytes(stride - len(record)) for record in records)
    manifest = dict(checked.manifest, optimisation='finite-immutable-write-table',
        immutable_sha256={name: hashlib.sha256(data).hexdigest() for name, data in immutable_fields.items()},
        key_domains=dict(zip(key_domains, domains)), placement=placement, placement_domain=placements,
        target_count=target_count, target_bytes=target_bytes, payload_bytes=payload_bytes,
        record_stride=stride, unique_records=len(records), table_bytes=len(blob),
        table_sha256=hashlib.sha256(blob).hexdigest(), evaluated_calls=evaluations,
        cached_keys=sum(v != 65535 for v in lookup), missed_keys=failures,
        proof='exhaustive finite domain; no mutable reads; disjoint writes; identical payload at every placement',
        contract='resources bound by hash at build/load; stable disjoint backing; miss must use original backend',
        spg_linked=False)
    return WriteTable(blob, lookup, slots, layouts, manifest)


def emit_write_table(table, prefix):
    """C-диспетчер не содержит формул исходного метода: только ключи и копирование."""
    manifest = table.manifest
    domains = manifest['key_domains']
    placement = manifest['placement']
    all_domains = {**domains, placement: manifest['placement_domain']}
    aliases = {name: 'pywt_arg'+str(index) for index,name in enumerate(all_domains)}
    params = ','.join('int32_t ' + aliases[name] for name in all_domains)
    signature = (f'uint8_t {prefix}(PyBufferView *table,PyBufferViewArray *targets,'
                 f'PyBufferSpan *scratch,{params},uint8_t *error)')
    header = '#include "pyz80_write_table.h"\n#ifndef PY_BUFFER_API\n#define PY_BUFFER_API\n#endif\n'
    header += 'PY_BUFFER_API ' + signature + ';\n'
    def array(kind, name, values):
        return f'static const {kind} {name}[]={{' + ','.join(map(str, values)) + '};\n'
    code = 'PY_BUFFER_API ' + signature + ' {\n    uint16_t key=0,record,position;\n'
    code += array('uint16_t', 'record_ids', table.lookup)
    code += array('uint8_t', 'target_slots', table.slots)
    flattened = [value for runs in table.placements for run in runs for value in run]
    code += array('uint16_t', 'write_runs', flattened)
    code += '    *error=0;\n'
    code += f'    if(targets->size!={manifest["target_count"]}u || !targets->items) return 0;\n'
    def literal(value):
        return '(-2147483647L-1L)' if value == -2147483648 else str(value)+'L'
    for name, domain in all_domains.items():
        argument = aliases[name]
        step = domain[1] - domain[0] if len(domain) > 1 else 1
        if step <= 0 or domain != list(range(domain[0], domain[-1] + 1, step)):
            raise NotTableable('C-диспетчеру пока нужен возрастающий арифметический домен')
        code += f'    if({argument}<{literal(domain[0])} || {argument}>{literal(domain[-1])}) return 0;\n'
        # SUB в u32 после CMP: разность крайних i32 может не помещаться в i32.
        difference = f'((uint32_t){argument}-(uint32_t){literal(domain[0])})'
        if step != 1:
            code += f'    if({difference}%{step}UL) return 0;\n'
        value = f'(uint16_t)({difference}/{step}UL)'
        if name == placement:
            code += f'    position={value};\n'
        else:
            code += f'    key=key*{len(domain)}u+{value}; /* MUL/ADD: индекс конечного домена. */\n'
    if len(table.lookup) > 65535:
        raise NotTableable('Индекс ключа шире u16')
    run_count = len(table.placements[0])
    if len(flattened) > 65535 or manifest['record_stride'] * manifest['unique_records'] > 2147483647:
        raise NotTableable('Адрес таблицы не помещается в целевой ABI')
    if any(len(runs) != run_count for runs in table.placements):
        raise NotTableable('Непостоянное число серий')
    code += '    record=record_ids[key];\n    if(record==65535u || target_slots[key]>=targets->size) return 0;\n'
    # Отрицательные Python-индексы нормализованы при вычислении таблицы.
    # Другой размер списка/буфера требует полного метода, а не этих адресов.
    code += f'    if(targets->items[target_slots[key]].size!={manifest["target_bytes"]}UL) return 0;\n'
    code += f'    return PyWriteTable_Apply(table,(uint32_t)record*{manifest["record_stride"]}UL,\n'
    code += f'        &targets->items[target_slots[key]],scratch,&write_runs[position*{run_count*2}u],\n'
    code += f'        {run_count}u,{manifest["payload_bytes"]}u,error);\n}}\n'
    return header, code
