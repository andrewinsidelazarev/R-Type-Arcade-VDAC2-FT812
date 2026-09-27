"""Связать все методы M72Tilemaps, сохранив ресурсную и AST-части раздельными."""
import ast
import hashlib
import json

from build_stage_record import ROOT, OUTPUT, main as build_scroll
from build_translator_demo import write
from build_tilemap_buffer import main as build_decoder
from pyz80_compiler.aggregate_backend import compile_aggregate
from pyz80_compiler.frozen_constructor import freeze_constructor
from rtype_port.stage import ROM_PATH

BUILD=ROOT/'Build/TilemapAggregate'
FIELDS={'rom':'bytes','vram':'list[bytearray]','target':2,'tracker':2,'source':2}


def main():
    build_scroll();build_decoder()
    source=(ROOT/'Source/Python/rtype_port/stage.py').read_text(encoding='utf-8')
    scroll=json.loads((ROOT/'Build/StageRecord/record_manifest.json').read_text(encoding='utf-8'))
    records={'M72Scroll':dict(c_type='StageScroll',header='stage_scroll_generated.h',
                            fields=[name for name,kind in scroll['fields'].items() if kind=='int32_t'])}
    artifact=compile_aggregate(source,'M72Tilemaps','TilemapState',fields=FIELDS,
        providers={'__init__':'frozen no-argument constructor with immutable ROM',
                   '_draw_strip':'complete buffer backend, optional verified write table'},records=records)
    write(OUTPUT/'tilemap_state_generated.h',artifact.header)
    write(OUTPUT/'tilemap_state_generated.c','#include "tilemap_state_generated.h"\n'+artifact.code)
    # Сам конструктор не переписывается: его результат при фиксированном ROM
    # является начальным ресурсом. Два независимых объекта не разделяют списки.
    first,proof=freeze_constructor(source,'M72Tilemaps',resources={'ROM_PATH':ROM_PATH.read_bytes()},fields=FIELDS)
    if [len(data) for data in first['vram']]!=[16384,16384]:
        raise ValueError('Банковая связка требует двух 16-КБ карт; новую схему нельзя молча обрезать')
    BUILD.mkdir(parents=True,exist_ok=True)
    blob=b''.join(first['vram'])
    (BUILD/'initial_vram.bin').write_bytes(blob)
    initial={name:list(first[name]) for name,kind in FIELDS.items() if isinstance(kind,int)}
    artifact.manifest['constructor']=dict(immutable_sha256={'rom':hashlib.sha256(first['rom']).hexdigest()},
        initial=initial,vram_sizes=[len(data) for data in first['vram']],proof=proof,
        vram_sha256=hashlib.sha256(blob).hexdigest(),independent_instances=True,
        contract='fixed ROM, no constructor arguments; runtime binding restores resource and fresh integer arrays')
    write(BUILD/'manifest.json',json.dumps(artifact.manifest,ensure_ascii=False,indent=2)+'\n')
    write(BUILD/'initial.json',json.dumps(initial)+'\n')
    binding_header='''#ifndef TILEMAP_BINDING_H
#define TILEMAP_BINDING_H
#include "tilemap_state_generated.h"
typedef struct {
    PyBufferView initial,table;
    PyBufferSpan scratch;
    uint32_t hits,misses;
} TilemapResources;
extern TilemapResources tilemap_resources;
uint8_t Tilemap_ApplyTable(TilemapState *record,int32_t layer,int32_t source,int32_t destination,uint8_t *error);
uint8_t Tilemap_ApplyDecoder(PyBufferFault *fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination);
#endif
'''
    write(OUTPUT/'tilemap_binding_generated.h',binding_header)
    binding='''/* Ресурсная связка; вычисления игры находятся в AST-модулях. */
#include "tilemap_binding_generated.h"
TilemapResources tilemap_resources;
PY_AGGREGATE_API uint8_t TilemapState___init__(PyBufferFault *fault,TilemapState *record) {
    uint8_t i,error;
    uint16_t position,chunk;
    PyBufferView *target;
    fault->error=0; fault->line=0;
    if(record->vram.size!=2 || !record->vram.items || !tilemap_resources.initial.transfer ||
       tilemap_resources.initial.size!=32768UL || !tilemap_resources.scratch.data ||
       tilemap_resources.scratch.size<240 || !tilemap_resources.scratch.writable)
        return PyBuf_Fail(fault,PYBUF_BACKING,310);
    for(i=0;i<2;++i) {
        target=&record->vram.items[i];
        if(target->size!=16384UL || !target->writable || !target->transfer)
            return PyBuf_Fail(fault,PYBUF_BACKING,310);
    }
    for(i=0;i<2;++i) {
        target=&record->vram.items[i]; position=0;
        while(position<16384u) {
            chunk=16384u-position;
            if(chunk>240) chunk=240;
            error=tilemap_resources.initial.transfer(tilemap_resources.initial.context,
                (uint32_t)i*16384UL+position,tilemap_resources.scratch.data,(uint8_t)chunk,0);
            if(error) return PyBuf_Fail(fault,error,310);
            error=target->transfer(target->context,position,tilemap_resources.scratch.data,(uint8_t)chunk,1);
            if(error) return PyBuf_Fail(fault,error,310);
            position+=chunk; /* ADD: следующая часть образа начального состояния. */
        }
    }
INITIAL_FIELDS
    tilemap_resources.hits=0; tilemap_resources.misses=0;
    return 1;
}
PY_AGGREGATE_API uint8_t TilemapState__draw_strip(PyBufferFault *fault,TilemapState *record,
    int32_t layer,int32_t source,int32_t destination) {
    uint8_t error,status;
    fault->error=0; fault->line=0;
    status=Tilemap_ApplyTable(record,layer,source,destination,&error);
    if(status==1) { ++tilemap_resources.hits; return 1; }
    if(status==2) return PyBuf_Fail(fault,error,361);
    ++tilemap_resources.misses;
    return Tilemap_ApplyDecoder(fault,record,layer,source,destination);
}
'''
    binding=binding.replace('INITIAL_FIELDS','\n'.join(f'    record->{name}[{i}]={value}L;'
        for name,values in initial.items() for i,value in enumerate(values)))
    lines={method['name']:method['source_lines'][0] for method in artifact.manifest['methods']}
    binding=binding.replace(',310)',','+str(lines['__init__'])+')').replace(',361)',','+str(lines['_draw_strip'])+')')
    write(OUTPUT/'tilemap_binding_generated.c',binding)
    print('M72Tilemaps: четыре AST-метода, полный байтовый метод и ресурсный конструктор',flush=True)
    return artifact


if __name__=='__main__': main()
