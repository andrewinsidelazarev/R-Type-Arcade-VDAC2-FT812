"""Байтовая сверка целого исходного загрузчика полосы на ПК и настоящем Z80."""
import ctypes as ct
import hashlib
import json
import logging
import random
import re
import struct

from build_terrain_buffer import ROOT,OUTPUT,BUILD,main as build
from build_translator_demo import command,write,validate_layout
from check_translator_demo import StrictDemoMachine
from rtype_port.world_terrain import _apply_strip,STRIP_BYTES


class Span(ct.Structure):
    _fields_=[('data',ct.POINTER(ct.c_uint8)),('size',ct.c_uint16),('writable',ct.c_uint8)]

class Fault(ct.Structure):
    _fields_=[('error',ct.c_uint8),('line',ct.c_uint16)]


def main():
    logging.getLogger().setLevel(logging.ERROR)
    build()
    include=ROOT/'Source/C/python_vm'
    command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_BUFFER_API=__declspec(dllexport)',
             '-I'+str(include),'-I'+str(OUTPUT),OUTPUT/'terrain_buffer_generated.c','-o',BUILD/'terrain.dll'])
    dll=ct.CDLL(str(BUILD/'terrain.dll'))
    fn=dll.Terrain_ApplyStrip
    fn.argtypes=[ct.POINTER(Fault),ct.POINTER(Span),ct.c_int32,ct.POINTER(Span)];fn.restype=ct.c_uint8
    rng=random.Random(7212)
    data=bytearray(rng.randbytes(0x4000));raw=rng.randbytes(STRIP_BYTES)
    cdata=(ct.c_uint8*len(data)).from_buffer_copy(data)
    craw=(ct.c_uint8*len(raw)).from_buffer_copy(raw)
    vram=Span(cdata,len(data),1);strip=Span(craw,len(raw),0);fault=Fault()
    for destination in range(-256,512):
        _apply_strip(data,destination,raw)
        assert fn(ct.byref(fault),ct.byref(vram),destination,ct.byref(strip))==1
        assert bytes(cdata)==data,(destination,'host bytes')
    # Исключения не маскируются успешным вызовом и не пишут за границу окна.
    previous=bytes(cdata);strip.size=959
    assert fn(ct.byref(fault),ct.byref(vram),0,ct.byref(strip))==0 and fault.error==1
    assert bytes(cdata)==previous
    strip.size=960;vram.writable=0
    assert fn(ct.byref(fault),ct.byref(vram),0,ct.byref(strip))==0 and fault.error==3
    vram.writable=1;vram.size=4
    assert fn(ct.byref(fault),ct.byref(vram),0,ct.byref(strip))==0 and fault.error==2
    assert bytes(cdata)==previous
    print('ПК: 768 полос, каждый байт VRAM совпал',flush=True)
    bridge='''/* Только отображение памяти и ABI; алгоритм полосы сгенерирован. */
#include "terrain_buffer_generated.h"
void Terrain_Dispatch(void) {
    PyBufferSpan vram,strip;
    PyBufferFault fault;
    vram.data=(uint8_t *)0x8000; vram.size=0x4000; vram.writable=1;
    strip.data=(uint8_t *)0x3200; strip.size=*(volatile uint16_t *)0x2142; strip.writable=0;
    *(volatile uint8_t *)0x2130=Terrain_ApplyStrip(&fault,&vram,*(volatile uint16_t *)0x2140,&strip);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
'''
    write(OUTPUT/'terrain_buffer_bridge_generated.c',bridge)
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed',
           '-I'+str(include),'-I'+str(OUTPUT)]
    for name in ('terrain_buffer','terrain_buffer_bridge'):
        command([*flags,'-c',OUTPUT/(name+'_generated.c'),'-o',BUILD/(name+'.rel')])
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200',
             BUILD/'terrain_buffer.rel',BUILD/'terrain_buffer_bridge.rel','-o',BUILD/'terrain.ihx'])
    map_text=(BUILD/'terrain.map').read_text(encoding='latin1')
    layout=validate_layout(map_text,require_data=False)
    entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_Terrain_Dispatch\b',map_text,re.M)[1],16)
    command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',BUILD/'terrain.ihx',BUILD/'terrain.bin'])
    binary=(BUILD/'terrain.bin').read_bytes()
    m=StrictDemoMachine(ROOT);m.mem.pages[:]=[0,5,0xa4,0xa3];m.reg.SP=0x3fff
    m.mem.write_physical(0xa3,0,binary)
    data=bytearray(rng.randbytes(0x4000));m.mem.write_physical(0xa4,0,data)
    m.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    m.mem.write_block_linear(0x3200,raw)
    timings=[]
    for destination in (*range(0,256,16),127,128,255,65535):
        _apply_strip(data,destination,raw)
        m.mem.write_block_linear(0x2140,struct.pack('<HH',destination,960))
        before=m.tstates;m.call(entry);timings.append(m.tstates-before)
        assert m.get_byte(0x2130)==1 and m.get_byte(0x2131)==0
        actual=m.get_memory(0x8000,0x4000)
        assert actual==data,(destination,'Z80 bytes',[(i,a,b) for i,(a,b) in enumerate(zip(actual,data)) if a!=b][:16])
        assert m.reg.SP==0x3fff and m.get_byte(0x3c00)==0xa5
    m.mem.write_block_linear(0x2140,struct.pack('<HH',0,959));m.call(entry)
    assert m.get_byte(0x2130)==0 and m.get_byte(0x2131)==1
    assert m.get_memory(0x8000,0x4000)==data
    manifest=json.loads((BUILD/'manifest.json').read_text(encoding='utf-8'))
    result=dict(host_strips=768,z80_strips=len(timings),compared_vram_bytes=0x4000,
        byte_mismatches=0,invalid_size_rejected=True,readonly_rejected=True,out_of_bounds_rejected=True,
        stack_guard=True,source_sha256=manifest['source_sha256'],memory_layout=layout,
        binary_sha256=hashlib.sha256(binary).hexdigest(),worst_tstates=max(timings),
        spg_linked=False,exception_scope='проверены ABI ошибки, не перехват исключений Python')
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)

if __name__=='__main__': main()
