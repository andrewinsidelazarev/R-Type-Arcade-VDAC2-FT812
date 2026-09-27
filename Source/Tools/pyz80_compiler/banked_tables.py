"""Serialize core adapter tables independently of host/Z80 pointer layout.

The small C descriptor holds only hot symbol tables, proof, CRC and binder.
PZTB bytes belong in paged RAM, never in a giant near-pointer C initializer.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
import zlib

HEADER_BYTES = 104
TABLES = (
    ('specs', 'BBH'), ('field_keys', 'H'), ('dispatch_functions', 'H'),
    ('arities', 'H'), ('positional_call_flags', 'B'), ('call_signatures', 'HBBBB'),
    ('parameter_names', 'H'), ('call_layout_offsets', 'H'),
    ('call_layout_keys', 'H'), ('class_body_flags', 'B'),
)


def _operation_values() -> dict[str, int]:
    # C ABI is the authority. Only explicit integral enum assignments qualify;
    # unknown/changed spellings fail, never silently map to operation zero.
    header = Path(__file__).resolve().parents[2] / 'C/python_vm/pyz80_target_object_runtime.h'
    text = header.read_text(encoding='utf-8')
    body = re.search(r'enum PyZ80TargetOperation\s*\{([^}]+)\}', text)
    if not body:
        raise ValueError('missing target operation ABI')
    return {name:int(value) for name,value in re.findall(r'(PYZ80_TARGET_\w+)\s*=\s*(\d+)', body[1])}


def build_banked_tables(plan: dict, arities: list[int], proof: str) -> tuple[bytes, str, str, dict]:
    if not isinstance(proof, str) or not re.fullmatch('[0-9a-f]{64}', proof):
        raise ValueError('PZTB requires an exact SHA-256 proof')
    functions = plan['function_count']
    if type(functions) is not int or not 0 <= functions <= 65535:
        raise ValueError('invalid function count')
    adapters = len(plan['specs'])
    values = dict(plan, arities=arities)
    for name, expected in [('arities',functions), ('call_signatures',functions),
                           ('class_body_flags',functions), ('call_layout_offsets',adapters),
                           ('positional_call_flags',adapters)]:
        if len(values[name]) != expected:
            raise ValueError(f'PZTB {name} count differs from source plan')
    operations = _operation_values()
    payload, directory, rows = bytearray(), bytearray(), []
    offset = HEADER_BYTES
    for index, (name, fmt) in enumerate(TABLES):
        records = values[name]
        if len(records) > 65535:
            raise ValueError(f'PZTB {name} exceeds its 16-bit record index')
        wire = struct.Struct('<'+fmt)
        start = len(payload)
        for record in records:
            fields = list(record) if len(fmt)>1 else [record]
            if name == 'specs':
                if fields[0] not in operations:
                    raise ValueError(f'unknown target operation {fields[0]!r}')
                fields[0] = operations[fields[0]]
            if any(type(value) is not int for value in fields):
                raise ValueError(f'non-integral {name} record')
            try:
                payload.extend(wire.pack(*fields))
            except (struct.error, TypeError) as exc:
                raise ValueError(f'out-of-range {name} record') from exc
        extent = len(payload)-start
        directory.extend(struct.pack('<IH', offset, len(records)))
        rows.append({'id':index,'name':name,'offset':offset,'count':len(records),
                     'record_bytes':wire.size,'bytes':extent})
        offset += extent
    if offset > 4*1024*1024:
        raise ValueError('PZTB exceeds 4 MiB memory budget')
    blob = struct.pack('<4sBBHI32s', b'PZTB',1,len(TABLES),HEADER_BYTES,offset,bytes.fromhex(proof)) + directory + payload
    crc = zlib.crc32(blob)
    header = '''/* Generated small resident descriptor; large records live in PZTB. */
#ifndef PYZ80_TARGET_BANKED_PLAN_GENERATED_H
#define PYZ80_TARGET_BANKED_PLAN_GENERATED_H
#include "pyz80_target_banked_tables.h"
uint8_t PyZ80Generated_BindBanked(PyZ80TargetContext *, PyZ80VM *,
    PyZ80TargetBankedTables *, PyZ80VMRead, void *, uint16_t *, uint16_t);
'''+f'#define PYZ80_GENERATED_ADAPTER_COUNT {adapters}u\n#define PYZ80_GENERATED_BANKED_BYTES {len(blob)}UL\n#endif\n'
    source = ['/* Generated: immutable hot symbols + sealed banked image identity. */',
              '#include "pyz80_target_banked_plan_generated.h"',
              'static const uint8_t proof[32] = {'+','.join(map(str,bytes.fromhex(proof)))+'};',
              'static const PyZ80TargetOperatorSpec operators[] = {',
              ','.join(f'{{{symbol}u,{op},0u}}' for symbol,op in plan['operators']) or '{0u,0u,0u}', '};',
              'static const PyZ80TargetBuiltinSpec builtins[] = {',
              ','.join(f'{{{symbol}u,{op}}}' for symbol,op in plan['builtin_symbols']) or '{0u,0u}', '};',
              'static const uint16_t class_symbols[] = {'+','.join(map(str,plan['class_symbols']))+'};',
              'uint8_t PyZ80Generated_BindBanked(PyZ80TargetContext *objects, PyZ80VM *vm,',
              '    PyZ80TargetBankedTables *state, PyZ80VMRead read, void *context, uint16_t *keys, uint16_t capacity)', '{',
              f'    PyZ80VMImage image; image.read=read; image.context=context; image.size={len(blob)}UL; image.expected_proof_sha256=proof;',
              f'    if(!PyZ80Target_AttachBankedTables(objects,vm,state,&image,{crc}UL,keys,capacity)) return 0u;',
              f'    objects->operators=operators;objects->operator_count={len(plan["operators"])}u;',
              f'    objects->builtin_symbols=builtins;objects->builtin_symbol_count={len(plan["builtin_symbols"])}u;',
              '    objects->class_symbols=class_symbols;', '    return 1u;', '}', '']
    report = {'format':'pyz80.banked-core-tables.v1','bytes':len(blob),'payload_bytes':len(payload),
              'sha256':hashlib.sha256(blob).hexdigest(),'crc32':f'{crc:08x}', 'proof_semantic_sha256':proof,
              'pages_16k':(len(blob)+16383)//16384,'address_bits':32,'tables':rows,
              'resident_hot_data_bytes_sdcc':32+max(1,len(plan['operators']))*4+max(1,len(plan['builtin_symbols']))*3+len(plan['class_symbols'])*2,
              'scope':'core adapter records only; import/dataclass plans and VM heap/code banking remain separate',
              'live':False}
    return bytes(blob), header, '\n'.join(source), report
