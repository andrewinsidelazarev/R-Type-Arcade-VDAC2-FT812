"""Сверка ROM-декодирования полосы: целый Python-метод, C и банковый Z80."""
import ctypes as ct
import hashlib
import json
import logging
import random
import re
import struct

from build_tilemap_buffer import ROOT,OUTPUT,BUILD,main as build
from build_translator_demo import command,write,validate_layout
from check_translator_demo import StrictDemoMachine
from check_terrain_buffer import Fault
from rtype_port.stage import M72Tilemaps,ROM_PATH
from pyz80_compiler.buffer_backend import compile_buffer_function


Transfer=ct.CFUNCTYPE(ct.c_uint8,ct.c_void_p,ct.c_uint32,ct.POINTER(ct.c_uint8),ct.c_uint8,ct.c_uint8)


class View(ct.Structure):
    _fields_=[('size',ct.c_uint32),('writable',ct.c_uint8),('context',ct.c_void_p),('transfer',Transfer)]


class Views(ct.Structure):
    _fields_=[('items',ct.POINTER(View)),('size',ct.c_uint16)]


def main():
    logging.getLogger().setLevel(logging.ERROR)
    build()
    include=ROOT/'Source/C/python_vm'
    command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_BUFFER_API=__declspec(dllexport)',
             '-I'+str(include),'-I'+str(OUTPUT),OUTPUT/'tilemap_buffer_generated.c','-o',BUILD/'tilemap.dll'])
    dll=ct.CDLL(str(BUILD/'tilemap.dll'));fn=dll.Tilemaps_DrawStrip
    fn.argtypes=[ct.POINTER(Fault),ct.POINTER(View),ct.POINTER(Views),ct.c_int32,ct.c_int32,ct.c_int32]
    fn.restype=ct.c_uint8
    rom=ROM_PATH.read_bytes();assert len(rom)==0x100000
    c_rom=(ct.c_uint8*len(rom)).from_buffer_copy(rom)
    rng=random.Random(81272)
    layers=[bytearray(rng.randbytes(0x4000)) for _ in range(2)]
    c_layers=[(ct.c_uint8*0x4000).from_buffer_copy(data) for data in layers]
    def transfer(context,position,data,size,writing):
        if writing: ct.memmove(context+position,data,size)
        else: ct.memmove(data,context+position,size)
        return 0
    callback=Transfer(transfer)
    source=View(len(rom),0,ct.addressof(c_rom),callback)
    array=(View*2)(*(View(0x4000,1,ct.addressof(data),callback) for data in c_layers))
    vram=Views(array,2);fault=Fault()
    reference=M72Tilemaps.__new__(M72Tilemaps)
    reference.rom=rom;reference.vram=layers
    cases=[(layer,index*10,(index*16)&255) for layer in range(2) for index in range(96)]
    for layer,offset,destination in cases:
        reference._draw_strip(layer,offset,destination)
        ok=fn(ct.byref(fault),ct.byref(source),ct.byref(vram),layer,offset,destination)
        assert ok and not fault.error,(layer,offset,destination,fault.error,fault.line)
        assert all(bytes(a)==b for a,b in zip(c_layers,layers)),(layer,offset,destination,'host VRAM')
    # Индекс массива буферов должен иметь Python-семантику, включая отрицательные.
    reference._draw_strip(-1,0,0)
    assert fn(ct.byref(fault),ct.byref(source),ct.byref(vram),-1,0,0)
    assert all(bytes(a)==b for a,b in zip(c_layers,layers))
    assert not fn(ct.byref(fault),ct.byref(source),ct.byref(vram),2,0,0) and fault.error==6
    print('ПК: 193 полосы, оба VRAM совпадают побайтно',flush=True)
    probe=compile_buffer_function('''def probe(src:bytes,dst:bytearray,read:int,write:int)->None:
    value=struct.unpack_from('<i',src,read)[0]
    struct.pack_into('>i',dst,write,value)
''','probe','Buffer_CopyWord',memory='view')
    write(OUTPUT/'tilemap_buffer_probe_generated.h',probe.header)
    write(OUTPUT/'tilemap_buffer_probe_generated.c','#include "tilemap_buffer_probe_generated.h"\n'+probe.code)
    bridge='''/* ABI теста; игровой алгоритм находится только в сгенерированном методе. */
#include "tilemap_buffer_generated.h"
#include "tilemap_buffer_probe_generated.h"
#include "pyz80_tsconf_buffer.h"
static PyTSBuffer rom_backing,layer_backing[2];
static PyBufferView rom_view,layer_views[2];
static PyBufferViewArray layers;
void Tilemap_Dispatch(void) {
    PyBufferFault fault;
    uint8_t i;
    rom_backing.first_page=0x40; rom_backing.pages=64; rom_backing.restore_page=0x30;
    rom_view.size=0x100000UL; rom_view.writable=0; rom_view.context=&rom_backing; rom_view.transfer=PyTSBuffer_Transfer;
    for(i=0;i<2;++i) {
        layer_backing[i].first_page=0xa4+i; layer_backing[i].pages=1; layer_backing[i].restore_page=0x30;
        layer_views[i].size=0x4000; layer_views[i].writable=1;
        layer_views[i].context=&layer_backing[i]; layer_views[i].transfer=PyTSBuffer_Transfer;
    }
    layers.items=layer_views; layers.size=2;
    *(volatile uint8_t *)0x2130=Tilemaps_DrawStrip(&fault,&rom_view,&layers,
        *(volatile int16_t *)0x2140,*(volatile uint16_t *)0x2142,*(volatile uint16_t *)0x2144);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
void Tilemap_Probe(void) {
    PyBufferFault fault;
    layer_backing[0].pages=2; layer_views[0].size=0x8000;
    *(volatile uint8_t *)0x2130=Buffer_CopyWord(&fault,&rom_view,&layer_views[0],
        *(volatile int32_t *)0x2150,*(volatile int32_t *)0x2154);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
'''
    write(OUTPUT/'tilemap_buffer_bridge_generated.c',bridge)
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed',
           '-I'+str(include),'-I'+str(OUTPUT)]
    for name in ('tilemap_buffer','tilemap_buffer_bridge','tilemap_buffer_probe'):
        command([*flags,'-c',OUTPUT/(name+'_generated.c'),'-o',BUILD/(name+'.rel')])
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200','-Wl-b_HOME=0xF000',
             BUILD/'tilemap_buffer.rel',BUILD/'tilemap_buffer_bridge.rel',BUILD/'tilemap_buffer_probe.rel','-o',BUILD/'tilemap.ihx'])
    map_text=(BUILD/'tilemap.map').read_text(encoding='latin1')
    layout=validate_layout(map_text)
    entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_Tilemap_Dispatch\b',map_text,re.M)[1],16)
    probe_entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_Tilemap_Probe\b',map_text,re.M)[1],16)
    command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',BUILD/'tilemap.ihx',BUILD/'tilemap.bin'])
    binary=(BUILD/'tilemap.bin').read_bytes()
    machine=StrictDemoMachine(ROOT)
    machine.mem.pages[:]=[0,5,0x30,0xa3];machine.reg.SP=0x3fff;machine.fmaddr_enabled=True
    machine.mem.write_physical(0xa3,0,binary)
    machine.mem.write_physical(0x40,0,rom)
    for i,data in enumerate(layers): machine.mem.write_physical(0xa4+i,0,data)
    machine.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    timings=[]
    for layer,offset,destination in ((0,0,0),(1,0,0),(0,70,240),(1,120,16),(-1,10,128)):
        reference._draw_strip(layer,offset,destination)
        machine.mem.write_block_linear(0x2140,struct.pack('<hHH',layer,offset,destination))
        before=machine.tstates;machine.call(entry,max_steps=10000000);timings.append(machine.tstates-before)
        assert machine.get_byte(0x2130)==1 and machine.get_byte(0x2131)==0,(layer,offset,machine.get_memory(0x2130,4))
        assert all(machine.mem.read_physical(0xa4+i,0,0x4000)==data for i,data in enumerate(layers)),(layer,offset,'Z80 VRAM')
        assert machine.mem.pages[2]==0x30,'Окно ROM не восстановлено'
        assert machine.reg.SP==0x3fff and machine.get_byte(0x3c00)==0xa5
        print('Z80: полоса',layer,offset,destination,'тактов',timings[-1],flush=True)
    combined=bytearray().join(layers)
    probes=((0x3fff,0x3fff),(0xffff,0x3ffe),(0x7ffff,0x7ffc),(-4,-4),(-0x100001,0),(0x100000,0),(0,0x7ffe))
    for read,destination in probes:
        valid=True
        try: struct.pack_into('>i',combined,destination,struct.unpack_from('<i',rom,read)[0])
        except struct.error: valid=False
        machine.mem.write_block_linear(0x2150,struct.pack('<ii',read,destination))
        machine.call(probe_entry)
        assert bool(machine.get_byte(0x2130))==valid,(read,destination,'результат')
        assert machine.get_byte(0x2131)==(0 if valid else 2),(read,destination,'ошибка')
        assert machine.mem.read_physical(0xa4,0,0x8000)==combined,(read,destination,'стык страниц')
        assert machine.mem.pages[2]==0x30 and machine.reg.SP==0x3fff and machine.get_byte(0x3c00)==0xa5
    assert machine.mem.read_physical(0x40,0,len(rom))==rom,'Read-only ROM был изменён'
    canary=machine.get_memory(0x3c00,0x3f0)
    used_stack=next((len(canary)-i+16 for i,byte in enumerate(canary) if byte!=0xa5),16)
    manifest=json.loads((BUILD/'manifest.json').read_text(encoding='utf-8'))
    result=dict(host_strips=193,z80_strips=len(timings),vram_bytes=32768,rom_bytes=len(rom),
                byte_mismatches=0,source_sha256=manifest['source_sha256'],complete_method=True,
                bank_restored=True,stack_guard=True,max_stack_bytes=used_stack,
                bank_boundary_probes=len(probes),readonly_rom_unchanged=True,memory_layout=layout,
                worst_tstates=max(timings),binary_sha256=hashlib.sha256(binary).hexdigest(),spg_linked=False)
    dependencies=[ROOT/'Source/Tools/pyz80_compiler/buffer_backend.py',
                  include/'pyz80_buffer_view.h',include/'pyz80_buffer_span.h',include/'pyz80_tsconf_buffer.h']
    result['implementation_sha256']={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in dependencies}
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__': main()
