"""Исходный метод против табличного C/Z80: все ключи, банки, отказы и такты."""
import ctypes as ct
import hashlib
import itertools
import json
import logging
import random
import re
import struct

from build_tilemap_table import ROOT, OUTPUT, BUILD, main as build
from build_tilemap_buffer import main as build_fallback
from build_translator_demo import command, write, validate_layout
from check_tilemap_buffer import Transfer, View, Views, Fault
from check_terrain_buffer import Span
from check_translator_demo import StrictDemoMachine
from rtype_port.stage import M72Tilemaps, ROM_PATH


def main():
    logging.getLogger().setLevel(logging.ERROR)
    table=build()
    build_fallback()
    include=ROOT/'Source/C/python_vm'
    command(['E:/zx/tcc-0.9.27/tcc/tcc.exe', '-shared', '-DPY_BUFFER_API=__declspec(dllexport)',
             '-I'+str(include), '-I'+str(OUTPUT), OUTPUT/'tilemap_table_generated.c',
             OUTPUT/'tilemap_buffer_generated.c', '-o', BUILD/'table.dll'])
    dll=ct.CDLL(str(BUILD/'table.dll'))
    fn=dll.Tilemaps_TryTable
    fn.argtypes=[ct.POINTER(View),ct.POINTER(Views),ct.POINTER(Span),
                 ct.c_int32,ct.c_int32,ct.c_int32,ct.POINTER(ct.c_uint8)]
    fn.restype=ct.c_uint8
    fallback=dll.Tilemaps_DrawStrip
    fallback.argtypes=[ct.POINTER(Fault),ct.POINTER(View),ct.POINTER(Views),ct.c_int32,ct.c_int32,ct.c_int32]
    fallback.restype=ct.c_uint8
    rng=random.Random(812328)
    layers=[bytearray(rng.randbytes(16384)) for _ in range(2)]
    native=[(ct.c_uint8*16384).from_buffer_copy(data) for data in layers]
    raw=(ct.c_uint8*len(table.records)).from_buffer_copy(table.records)
    rom=ROM_PATH.read_bytes()
    raw_rom=(ct.c_uint8*len(rom)).from_buffer_copy(rom)
    scratch_data=(ct.c_uint8*table.manifest['payload_bytes'])()
    scratch=Span(scratch_data,len(scratch_data),1)
    failing=set()
    def transfer(context,position,data,size,writing):
        if context in failing:
            return 5
        if writing: ct.memmove(context+position,data,size)
        else: ct.memmove(data,context+position,size)
        return 0
    callback=Transfer(transfer)
    resource=View(len(raw),0,ct.addressof(raw),callback)
    original_rom=View(len(raw_rom),0,ct.addressof(raw_rom),callback)
    views=(View*2)(*(View(16384,1,ct.addressof(data),callback) for data in native))
    targets=Views(views,2)
    reference=M72Tilemaps.__new__(M72Tilemaps)
    reference.rom=rom; reference.vram=layers
    error=ct.c_uint8()
    comparisons=0
    for layer,source,destination in itertools.product(range(2),range(0,5120,10),range(0,256,16)):
        reference._draw_strip(layer,source,destination)
        result=fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),layer,source,destination,ct.byref(error))
        assert result==1 and error.value==0,(layer,source,destination,result,error.value)
        assert all(bytes(actual)==expected for actual,expected in zip(native,layers)),(layer,source,destination)
        comparisons+=1
    print('ПК: все',comparisons,'комбинаций совпали с полным методом',flush=True)
    # Промах не пишет ничего; результат достигается обычным полным backend.
    misses=[(-1,0,0),(0,1,0),(1,5120,16),(0,0,1),(0,0,-16),(0,-1,0)]
    for layer,source,destination in misses:
        before=[bytes(data) for data in native]
        assert fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),layer,source,destination,ct.byref(error))==0
        assert before==[bytes(data) for data in native]
        fault=Fault()
        try:
            reference._draw_strip(layer,source,destination)
            valid=True
        except (struct.error,IndexError):
            valid=False
        ok=fallback(ct.byref(fault),ct.byref(original_rom),ct.byref(targets),layer,source,destination)
        assert bool(ok)==valid
        assert all(bytes(actual)==expected for actual,expected in zip(native,layers))
    # Все предварительные отказы оставляют VRAM неизменным.
    before=[bytes(data) for data in native]
    checks=[(views[0],'writable',0),(views[0],'size',1),(views[0],'size',16385),(resource,'size',1),
            (scratch,'size',1),(scratch,'writable',0),(targets,'size',0),(targets,'size',3)]
    for obj,field,value in checks:
        old=getattr(obj,field);setattr(obj,field,value)
        assert fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),0,0,0,ct.byref(error))==0
        assert before==[bytes(data) for data in native]
        setattr(obj,field,old)
    for context in (ct.addressof(raw),ct.addressof(native[0])):
        failing.add(context)
        assert fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),0,0,0,ct.byref(error))==2
        assert error.value==5
        failing.clear()
    assert bytes(raw)==table.records and bytes(raw_rom)==rom
    bridge='''/* Аппаратная связка теста: игровые формулы отсутствуют. */
#include "tilemap_table_generated.h"
#include "pyz80_tsconf_bulk.h"
static PyTSBuffer table_backing,layer_backing[2];
static PyBufferView table_view,layer_views[2];
static PyBufferViewArray layers;
static uint8_t staging[PAYLOAD_BYTES];
static PyBufferSpan scratch;
void Table_Dispatch(void) {
    uint8_t i,error;
    table_backing.first_page=0x40; table_backing.pages=TABLE_PAGES; table_backing.restore_page=0x30;
    table_view.size=TABLE_BYTES; table_view.writable=0;
    table_view.context=&table_backing; table_view.transfer=PyTSBuffer_BulkTransfer;
    for(i=0;i<2;++i) {
        layer_backing[i].first_page=0xa4+i; layer_backing[i].pages=1; layer_backing[i].restore_page=0x30;
        layer_views[i].size=16384; layer_views[i].writable=1;
        layer_views[i].context=&layer_backing[i]; layer_views[i].transfer=PyTSBuffer_BulkTransfer;
    }
    layers.items=layer_views; layers.size=2;
    scratch.data=staging; scratch.size=sizeof(staging); scratch.writable=1;
    *(volatile uint8_t *)0x2130=Tilemaps_TryTable(&table_view,&layers,&scratch,
        *(volatile int16_t *)0x2140,*(volatile int16_t *)0x2142,*(volatile int16_t *)0x2144,&error);
    *(volatile uint8_t *)0x2131=error;
}
void Table_BoundaryProbe(void) {
    uint8_t error;
    layer_backing[0].pages=2;
    error=PyTSBuffer_BulkTransfer(&table_backing,*(volatile uint32_t *)0x2150,staging,255,0);
    if(!error) error=PyTSBuffer_BulkTransfer(&layer_backing[0],*(volatile uint32_t *)0x2154,staging,255,1);
    *(volatile uint8_t *)0x2131=error;
}
'''.replace('PAYLOAD_BYTES',str(len(scratch_data))).replace('TABLE_PAGES',str((len(raw)+16383)//16384)).replace('TABLE_BYTES',str(len(raw))+'UL')
    write(OUTPUT/'tilemap_table_bridge_generated.c',bridge)
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed',
           '-I'+str(include),'-I'+str(OUTPUT)]
    for name in ('tilemap_table','tilemap_table_bridge'):
        command([*flags,'-c',OUTPUT/(name+'_generated.c'),'-o',BUILD/(name+'.rel')])
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200','-Wl-b_HOME=0xF800',
             BUILD/'tilemap_table.rel',BUILD/'tilemap_table_bridge.rel','-o',BUILD/'table.ihx'])
    map_text=(BUILD/'table.map').read_text(encoding='latin1')
    layout=validate_layout(map_text)
    def address(name):
        return int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_'+name+r'\b',map_text,re.M)[1],16)
    command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',BUILD/'table.ihx',BUILD/'table.bin'])
    binary=(BUILD/'table.bin').read_bytes()
    machine=StrictDemoMachine(ROOT)
    machine.mem.pages[:]=[0,5,0x30,0xa3];machine.reg.SP=0x3fff;machine.fmaddr_enabled=True
    machine.mem.write_physical(0xa3,0,binary)
    machine.mem.write_physical(0x40,0,table.records)
    for i,data in enumerate(layers): machine.mem.write_physical(0xa4+i,0,data)
    machine.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    timings=[]
    cases=[(0,0,0),(1,0,0),(0,70,240),(1,120,16),(0,5110,128),(1,5110,240)]
    for layer,source,destination in cases:
        reference._draw_strip(layer,source,destination)
        machine.mem.write_block_linear(0x2140,struct.pack('<hhh',layer,source,destination))
        before=machine.tstates;machine.call(address('Table_Dispatch'));timings.append(machine.tstates-before)
        assert machine.get_byte(0x2130)==1 and machine.get_byte(0x2131)==0
        assert all(machine.mem.read_physical(0xa4+i,0,16384)==data for i,data in enumerate(layers))
        assert machine.mem.pages[2]==0x30 and machine.reg.SP==0x3fff and machine.get_byte(0x3c00)==0xa5
        print('Z80:',layer,source,destination,'тактов',timings[-1],flush=True)
    for args in misses:
        before=machine.mem.read_physical(0xa4,0,32768)
        machine.mem.write_block_linear(0x2140,struct.pack('<hhh',*args))
        machine.call(address('Table_Dispatch'))
        assert machine.get_byte(0x2130)==0 and before==machine.mem.read_physical(0xa4,0,32768)
    combined=bytearray().join(layers)
    probes=[(0x3fff,0x3ff0),(0xffff,0x3fff),(0x10000,0),(len(raw)-255,0x7f00)]
    for source,destination in probes:
        machine.mem.write_block_linear(0x2150,struct.pack('<II',source,destination))
        machine.call(address('Table_BoundaryProbe'))
        combined[destination:destination+255]=table.records[source:source+255]
        assert machine.get_byte(0x2131)==0
        assert machine.mem.read_physical(0xa4,0,32768)==combined
        assert machine.mem.pages[2]==0x30 and machine.reg.SP==0x3fff and machine.get_byte(0x3c00)==0xa5
    assert machine.mem.read_physical(0x40,0,len(raw))==table.records
    canary=machine.get_memory(0x3c00,0x3f0)
    stack=next((len(canary)-i+16 for i,byte in enumerate(canary) if byte!=0xa5),16)
    dependencies=[ROOT/'Source/Tools/pyz80_compiler/write_table.py',ROOT/'Source/Tools/build_tilemap_table.py',
                  ROOT/'Source/Tools/check_tilemap_table.py',include/'pyz80_write_table.h',include/'pyz80_tsconf_bulk.h',
                  include/'pyz80_tsconf_buffer.h',include/'pyz80_buffer_view.h',include/'pyz80_buffer_span.h',
                  ROOT/'Source/Tools/pyz80_compiler/buffer_backend.py']
    result=dict(host_cases=comparisons,z80_cases=len(cases),cache_misses=len(misses),
                guard_cases=len(checks),backing_faults=2,bank_boundary_probes=len(probes),
                byte_mismatches=0,bank_restored=True,stack_guard=True,max_stack_bytes=stack,
                worst_tstates=max(timings),timings=timings,memory_layout=layout,
                binary_sha256=hashlib.sha256(binary).hexdigest(),
                manifest_sha256=hashlib.sha256((BUILD/'manifest.json').read_bytes()).hexdigest(),
                implementation_sha256={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                                       for path in dependencies},spg_linked=False)
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__': main()
