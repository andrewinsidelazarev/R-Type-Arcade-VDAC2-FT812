"""Полный объект карт и скроллер: непрерывная сверка без подачи состояния с ПК."""
import ctypes as ct
import hashlib
import json
import random
import struct

from build_tilemap_aggregate import ROOT,OUTPUT,BUILD,FIELDS,main as build
from build_tilemap_table import BUILD as TABLE_BUILD,main as build_table
from build_translator_demo import command,write
from check_tilemap_buffer import View,Views,Transfer,Fault
from check_terrain_buffer import Span
from rtype_port.stage import M72Tilemaps,M72Scroll,ROM_PATH


class State(ct.Structure):
    _fields_=[('rom',View),('vram',Views),('target',ct.c_int32*2),('tracker',ct.c_int32*2),('source',ct.c_int32*2)]


class Resources(ct.Structure):
    _fields_=[('initial',View),('table',View),('scratch',Span),('hits',ct.c_uint32),('misses',ct.c_uint32)]


def main():
    build();build_table()
    bridge='''#include "tilemap_binding_generated.h"
#include "tilemap_table_generated.h"
#include "tilemap_buffer_generated.h"
uint8_t Tilemap_ApplyTable(TilemapState *record,int32_t layer,int32_t source,int32_t destination,uint8_t *error) {
    return Tilemaps_TryTable(&tilemap_resources.table,&record->vram,&tilemap_resources.scratch,layer,source,destination,error);
}
uint8_t Tilemap_ApplyDecoder(PyBufferFault *fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination) {
    return Tilemaps_DrawStrip(fault,&record->rom,&record->vram,layer,source,destination);
}
PY_AGGREGATE_API TilemapResources *Tilemap_GetResources(void) { return &tilemap_resources; }
'''
    write(OUTPUT/'tilemap_host_bridge_generated.c',bridge)
    names=['tilemap_state','tilemap_binding','tilemap_table','tilemap_buffer','tilemap_host_bridge','stage_scroll']
    command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_AGGREGATE_API=__declspec(dllexport)',
             '-DPY_RECORD_API=__declspec(dllexport)','-I'+str(OUTPUT),'-I'+str(ROOT/'Source/C/python_vm'),
             *[OUTPUT/(name+'_generated.c') for name in names],'-o',BUILD/'aggregate.dll'])
    dll=ct.CDLL(str(BUILD/'aggregate.dll'))
    fields=json.loads((ROOT/'Build/StageRecord/record_manifest.json').read_text(encoding='utf-8'))['fields']
    class Maybe(ct.Structure):
        _fields_=[('value',ct.c_int32),('present',ct.c_uint8)]
    class Scroll(ct.Structure):
        _fields_=[(name,Maybe if kind=='PyRecordMaybeI32' else ct.c_int32) for name,kind in fields.items()]
    dll.Tilemap_GetResources.restype=ct.POINTER(Resources)
    resources=dll.Tilemap_GetResources().contents
    def transfer(context,position,data,size,writing):
        if writing: ct.memmove(context+position,data,size)
        else: ct.memmove(data,context+position,size)
        return 0
    callback=Transfer(transfer)
    buffers=[]
    def view(data,writable=0):
        raw=(ct.c_uint8*len(data)).from_buffer_copy(data);buffers.append(raw)
        return View(len(data),writable,ct.addressof(raw),callback)
    resources.initial=view((BUILD/'initial_vram.bin').read_bytes())
    resources.table=view((TABLE_BUILD/'records.bin').read_bytes())
    staging=(ct.c_uint8*960)();resources.scratch=Span(staging,960,1)
    rng=random.Random(72812)
    targets=(View*2)(*(view(rng.randbytes(16384),1) for _ in range(2)))
    actual=State(view(ROM_PATH.read_bytes()),Views(targets,2))
    state_functions={}
    for name,extra in [('__init__',[]),('_pump',[]),('advance',[ct.POINTER(Scroll)]),
                       ('_crossing',[ct.c_int32]*3),('_draw_strip',[ct.c_int32]*3),
                       ('state',[ct.c_int32]*3+[ct.POINTER(ct.c_int32)])]:
        fn=getattr(dll,'TilemapState_'+name)
        fn.argtypes=[ct.POINTER(Fault),ct.POINTER(State),*extra];fn.restype=ct.c_uint8
        state_functions[name]=fn
    for name in ('init','advance','queue_stage_transition_reset'):
        fn=getattr(dll,'StageScroll_'+name);fn.argtypes=[ct.POINTER(Scroll)];fn.restype=None
    dll.StageScroll_queue_object_velocity_write.argtypes=[ct.POINTER(Scroll),ct.POINTER(Maybe),ct.POINTER(Maybe)]
    dll.StageScroll_queue_object_velocity_write.restype=None
    fault=Fault();reference=M72Tilemaps();scroll=M72Scroll();native_scroll=Scroll()
    dll.StageScroll_init(ct.byref(native_scroll))
    def call(name,*args):
        result=state_functions[name](ct.byref(fault),ct.byref(actual),*args)
        assert result and not fault.error,(name,args,fault.error,fault.line)
    def compare(label):
        for name,kind in FIELDS.items():
            if isinstance(kind,int): assert list(getattr(actual,name))==getattr(reference,name),(label,name)
        assert all(ct.string_at(targets[i].context,16384)==reference.vram[i] for i in range(2)),(label,'VRAM')
    call('__init__');compare('constructor')
    states=0
    for frame in range(5000):
        if frame%401==0:
            fg=rng.choice([None,0,64,128,256]);bg=rng.choice([None,0,128,256])
            scroll.queue_object_velocity_write(fg,bg)
            a,b=Maybe(fg or 0,fg is not None),Maybe(bg or 0,bg is not None)
            dll.StageScroll_queue_object_velocity_write(ct.byref(native_scroll),ct.byref(a),ct.byref(b))
        if frame%709==0:
            scroll.queue_stage_transition_reset();dll.StageScroll_queue_stage_transition_reset(ct.byref(native_scroll))
        scroll.advance();dll.StageScroll_advance(ct.byref(native_scroll))
        reference.advance(scroll);call('advance',ct.byref(native_scroll));compare(frame)
        for name,kind in fields.items():
            value=getattr(native_scroll,name)
            value=(value.value if value.present else None) if kind=='PyRecordMaybeI32' else value
            assert value==getattr(scroll,name),(frame,name)
        if frame%17==0:
            args=(rng.randrange(-2,2),rng.randrange(30),rng.randrange(64))
            output=(ct.c_int32*2)();call('state',*args,output)
            assert tuple(output)==reference.state(*args);states+=1
    print('ПК: 5000 кадров полного объекта, оба VRAM и все поля совпали',flush=True)
    for args in [(0,1,0),(1,5120,16),(-1,0,240)]:
        reference._draw_strip(*args);call('_draw_strip',*args);compare(('fallback',args))
    for args in [(-1,0,16384),(-2,16384,0)]:
        reference._crossing(*args);call('_crossing',*args);compare(('negative',args))
    before=list(actual.target)
    assert not state_functions['_crossing'](ct.byref(fault),ct.byref(actual),2,0,16384) and fault.error==6
    assert list(actual.target)==before
    hits,misses=resources.hits,resources.misses
    reference=M72Tilemaps();call('__init__');compare('reinit')
    report=dict(frames=5000,state_queries=states,cache_hits=hits,cache_misses=misses,byte_mismatches=0,
        scalar_mismatches=0,negative_indices=True,index_fault=True,reinitialisation=True,
        state_injected_from_python=False,all_methods_linked=True,spg_linked=False,
        source_sha256=hashlib.sha256((ROOT/'Source/Python/rtype_port/stage.py').read_bytes()).hexdigest())
    write(BUILD/'host_check_report.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report,flush=True)


if __name__=='__main__': main()
