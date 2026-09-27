"""Те же общие форматы и оптимизации, но после SDCC на инструкциях Z80."""
import hashlib
import json
import logging
import random
import re
import struct

from test_buffer_backend import BufferTests
from build_translator_demo import ROOT,command,validate_layout,write
from check_translator_demo import StrictDemoMachine


def main():
    logging.getLogger().setLevel(logging.ERROR)
    BufferTests.setUpClass();build=BufferTests.build
    bridge='''/* Тестовое отображение окон, без дублирования преобразования байтов. */
#include "cases.c"
void Buffer_Dispatch(void) {
    PyBufferSpan src,dst;
    PyBufferFault fault;
    int32_t read=(int16_t)*(volatile uint16_t *)0x2142;
    int32_t write=(int16_t)*(volatile uint16_t *)0x2144;
    uint8_t result=0;
    src.data=(uint8_t *)0x3000; src.size=64; src.writable=0;
    dst.data=(uint8_t *)(*(volatile uint8_t *)0x2141?0x3000:0x3100); dst.size=64; dst.writable=1;
    switch(*(volatile uint8_t *)0x2140) {
'''
    bridge+='\n'.join(f'    case {i}: result=transfer{i}(&fault,&src,&dst,read,write); break;' for i in range(5))
    bridge+='''
    case 5: result=copy_fast(&fault,&src,&dst,read,write); break;
    case 6: result=loop(&fault,&dst); break;
    case 7: result=put(&fault,&dst,*(volatile int32_t *)0x2148,write); break;
    default: fault.error=255; fault.line=0; break;
    }
    *(volatile uint8_t *)0x2130=result;
    *(volatile uint8_t *)0x2131=fault.error;
}
'''
    write(build/'bridge.c',bridge)
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed',
           '-I'+str(ROOT/'Source/C/python_vm')]
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200',build/'bridge.c','-o',build/'cases.ihx'])
    mapping=(build/'cases.map').read_text(encoding='latin1');layout=validate_layout(mapping,require_data=False)
    entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_Buffer_Dispatch\b',mapping,re.M)[1],16)
    command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',build/'cases.ihx',build/'cases.bin'])
    binary=(build/'cases.bin').read_bytes()
    m=StrictDemoMachine(ROOT);m.mem.pages[:]=[0,5,0x30,0xa3];m.reg.SP=0x3fff
    m.mem.write_physical(0xa3,0,binary);m.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    rng=random.Random(1234);cases=0
    namespace={'struct':struct};exec(BufferTests.copy_source,namespace);copy=namespace['copy_loop']
    def execute(op,raw,target,read=0,write_at=0,alias=False,value=0):
        nonlocal cases
        m.mem.write_block_linear(0x3000,raw);m.mem.write_block_linear(0x3100,target)
        m.mem.write_block_linear(0x2140,struct.pack('<BBhhHi',op,int(alias),read,write_at,0,value))
        m.call(entry)
        assert m.reg.SP==0x3fff and m.get_byte(0x3c00)==0xa5
        cases+=1
        return bool(m.get_byte(0x2130)),m.get_memory(0x3000 if alias else 0x3100,64)
    for index,fmt in enumerate(BufferTests.formats):
        for _ in range(10):
            raw=rng.randbytes(64);target=rng.randbytes(64);expected=bytearray(target)
            size=struct.calcsize(fmt);read=rng.randrange(65-size);write_at=rng.randrange(65-size)
            if rng.randrange(2): read-=64
            if rng.randrange(2): write_at-=64
            struct.pack_into(fmt,expected,write_at,*struct.unpack_from(fmt,raw,read))
            ok,actual=execute(index,raw,target,read,write_at)
            assert ok and actual==expected,(fmt,read,write_at,actual,expected)
    for alias in (False,True):
        for read,write_at in ((0,32),(32,0),(-32,0),(0,-32),(0,1),(4,0),(-16,0),(0,60),(65,0)):
            raw=bytearray(rng.randbytes(64));target=raw if alias else bytearray(rng.randbytes(64))
            reference_raw=bytearray(raw);expected=reference_raw if alias else bytearray(target);good=True
            try: copy(reference_raw,expected,read,write_at)
            except struct.error: good=False
            ok,actual=execute(5,raw,target,read,write_at,alias)
            assert ok==good and actual==expected,('copy',alias,read,write_at,ok,good)
    ok,actual=execute(6,bytes(64),bytes(64));assert ok and actual[:8]==struct.pack('<4H',0,1,2,7)
    for value in (-32769,-32768,-1,0,32767,32768):
        ok,actual=execute(7,bytes(64),bytes(64),write_at=-2,value=value)
        assert ok==(-32768<=value<=32767)
        if ok: assert actual[-2:]==struct.pack('<h',value)
    result=dict(cases=cases,byte_mismatches=0,stack_guard=True,formats=list(BufferTests.formats),
                memory_layout=layout,binary_sha256=hashlib.sha256(binary).hexdigest(),
                copied_format_fallback_checked=True,negative_offsets_checked=True)
    write(build/'z80_check.json',json.dumps(result,indent=2)+'\n');print(result,flush=True)

if __name__=='__main__': main()
