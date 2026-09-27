"""Дифференциальная проверка всего скроллера: CPython, host C и SDCC/Z80."""
import ast
import ctypes
import hashlib
import json
import logging
import random
import re
import struct

from build_translator_demo import ROOT,command,write
from build_stage_record import main as generate
from check_translator_demo import StrictDemoMachine
from rtype_port.stage import M72Scroll,M72_INTEGRATOR_MISSING,M72_SCROLL_STALLS

BUILD=ROOT/'Build/StageRecord'
CSRC=ROOT/'Source/C/generated'


def main():
    logging.getLogger().setLevel(logging.ERROR)
    generate()
    manifest=json.loads((BUILD/'record_manifest.json').read_text(encoding='utf-8'))
    fields=manifest['fields']; properties=[n['name'] for n in manifest['methods'] if n['kind']=='property']
    class Maybe(ctypes.Structure):
        _fields_=[('value',ctypes.c_int32),('present',ctypes.c_uint8)]
    class Record(ctypes.Structure):
        _fields_=[(name,Maybe if kind=='PyRecordMaybeI32' else ctypes.c_int32) for name,kind in fields.items()]
    write(BUILD/'host.c','#define PY_RECORD_API __declspec(dllexport)\n#include "stage_scroll_generated.c"\n')
    command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-I'+str(CSRC),BUILD/'host.c','-o',BUILD/'record.dll'])
    dll=ctypes.CDLL(str(BUILD/'record.dll'))
    functions={}
    for name in ['init',*[n['name'] for n in manifest['methods']]]:
        fn=getattr(dll,'StageScroll_'+name)
        if name=='_integrated_delta': fn.argtypes=[ctypes.c_int32,ctypes.c_int32]
        elif name=='queue_object_velocity_write': fn.argtypes=[ctypes.POINTER(Record),ctypes.POINTER(Maybe),ctypes.POINTER(Maybe)]
        elif name=='queue_stage_init': fn.argtypes=[ctypes.POINTER(Record),ctypes.c_int32,ctypes.c_int32,ctypes.c_int32]
        else: fn.argtypes=[ctypes.POINTER(Record)]
        fn.restype=ctypes.c_int32 if name in properties or name=='_integrated_delta' else None
        functions[name]=fn
    def snapshot(p): return [getattr(p,name) for name in fields]
    def compare(p,c,label):
        for name,kind in fields.items():
            value=getattr(c,name)
            if kind=='PyRecordMaybeI32': value=value.value if value.present else None
            assert value==getattr(p,name),(label,name,value,getattr(p,name))
        for name in properties:
            actual=functions[name](ctypes.byref(c))
            assert actual==getattr(p,name),(label,name,actual,getattr(p,name))
    events={3029,8176,9236,9322,9770,10001,10262,10265,15524,*M72_INTEGRATOR_MISSING,*M72_SCROLL_STALLS}
    near={x+d for x in events for d in range(-2,3)}
    probes=[]; frames=0; randomizer=random.Random(812)
    for scenario in range(3):
        p=M72Scroll(stage1_no_fire_reference=scenario==1)
        c=Record(); functions['init'](ctypes.byref(c)); c.stage1_no_fire_reference=scenario==1
        compare(p,c,('init',scenario))
        for frame in range(17000):
            if scenario==2 and frame%101==0:
                foreground=randomizer.choice([None,0,64,128,256,65535])
                background=randomizer.choice([None,0,64,128,256,65535])
                before=snapshot(p)
                p.queue_object_velocity_write(foreground,background)
                a,b=Maybe(foreground or 0,foreground is not None),Maybe(background or 0,background is not None)
                functions['queue_object_velocity_write'](ctypes.byref(c),ctypes.byref(a),ctypes.byref(b))
                compare(p,c,('queue',frame))
                probes.append((before,1,(foreground,background),snapshot(p),[getattr(p,n) for n in properties]))
            if scenario==2 and frame%1093==0:
                before=snapshot(p); p.queue_stage_transition_reset()
                functions['queue_stage_transition_reset'](ctypes.byref(c));compare(p,c,('reset',frame))
                probes.append((before,2,(),snapshot(p),[getattr(p,n) for n in properties]))
            if scenario==2 and frame%1291==0:
                args=(randomizer.randrange(65536),randomizer.randrange(65536),randomizer.randrange(65536))
                before=snapshot(p);p.queue_stage_init(*args)
                functions['queue_stage_init'](ctypes.byref(c),*args);compare(p,c,('stage',frame))
                probes.append((before,3,args,snapshot(p),[getattr(p,n) for n in properties]))
            before=snapshot(p);p.advance();functions['advance'](ctypes.byref(c));frames+=1
            compare(p,c,(scenario,p.vblank))
            if p.vblank in near or frame<3 or (scenario==2 and frame%101<2):
                probes.append((before,0,(),snapshot(p),[getattr(p,n) for n in properties]))
        print('CPython = C:',scenario,17000,'кадров',flush=True)
    # Единый тестовый mailbox исключает зависимость теста от layout optional на ПК/Z80.
    bridge=['#include "stage_scroll_generated.h"','int32_t mailbox[96];','StageScroll record;',
            'void StageRecord_Run(void) {','    PyRecordMaybeI32 a,b;']
    for i,(name,kind) in enumerate(fields.items()):
        if kind=='PyRecordMaybeI32':
            bridge += [f'    record.{name}.value=mailbox[{2*i}];',f'    record.{name}.present=(uint8_t)mailbox[{2*i+1}];']
        else: bridge.append(f'    record.{name}=mailbox[{2*i}];')
    bridge += ['    a.value=mailbox[26]; a.present=(uint8_t)mailbox[27];',
               '    b.value=mailbox[28]; b.present=(uint8_t)mailbox[29];',
               '    switch(mailbox[32]) {',
               '    case 0: StageScroll_advance(&record); break;',
               '    case 1: StageScroll_queue_object_velocity_write(&record,&a,&b); break;',
               '    case 2: StageScroll_queue_stage_transition_reset(&record); break;',
               '    case 3: StageScroll_queue_stage_init(&record,mailbox[26],mailbox[28],mailbox[30]); break;',
               '    }']
    for i,(name,kind) in enumerate(fields.items()):
        if kind=='PyRecordMaybeI32':
            bridge += [f'    mailbox[{40+2*i}]=record.{name}.present ? record.{name}.value : 0;',f'    mailbox[{41+2*i}]=record.{name}.present;']
        else: bridge += [f'    mailbox[{40+2*i}]=record.{name};',f'    mailbox[{41+2*i}]=1;']
    bridge += [f'    mailbox[{66+i}]=StageScroll_{name}(&record);' for i,name in enumerate(properties)]
    bridge+=['}']
    assert len(fields)==13 and len(properties)<=30
    write(BUILD/'bridge.c','\n'.join(bridge)+'\n')
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed','-I'+str(CSRC)]
    command([*flags,'-c',CSRC/'stage_scroll_generated.c','-o',BUILD/'record.rel'])
    command([*flags,'-c',BUILD/'bridge.c','-o',BUILD/'bridge.rel'])
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200',
             BUILD/'record.rel',BUILD/'bridge.rel','-o',BUILD/'record.ihx'])
    map_text=(BUILD/'record.map').read_text(encoding='latin1')
    labels={name:int(address,16) for address,name in re.findall(r'^\s*([0-9A-Fa-f]{8})\s+_(\w+)\b',map_text,re.M)}
    from build_translator_demo import validate_layout
    layout=validate_layout(map_text)
    m=StrictDemoMachine(ROOT);m.mem.pages[:]=[0,5,0x30,6];m.reg.SP=0x3fff
    for line in (BUILD/'record.ihx').read_text().splitlines():
        data=bytes.fromhex(line[1:])
        if data[3]==0: m.mem.write_block_linear(int.from_bytes(data[1:3],'big'),data[4:4+data[0]])
    m.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    for index,(before,operation,arguments,after,expected_properties) in enumerate(probes):
        words=[0]*96
        for i,value in enumerate(before): words[2*i]=int(value or 0);words[2*i+1]=int(value is not None)
        for i,value in enumerate(arguments): words[26+2*i]=int(value or 0);words[27+2*i]=int(value is not None)
        words[32]=operation
        m.mem.write_block_linear(labels['mailbox'],struct.pack('<96i',*words))
        m.call(labels['StageRecord_Run'])
        result=struct.unpack('<96i',m.get_memory(labels['mailbox'],384))
        actual=[result[40+2*i] if result[41+2*i] else None for i in range(len(fields))]
        assert actual==after,(index,'Z80 state',actual,after)
        assert list(result[66:66+len(properties)])==expected_properties,(index,'Z80 properties')
        assert m.reg.SP==0x3fff and m.get_byte(0x3c00)==0xa5
        if (index+1)%200==0: print('Z80:',index+1,'состояний',flush=True)
    result=dict(host_frames=frames,z80_probes=len(probes),state_mismatches=0,property_mismatches=0,
        complete_declared_methods=len(manifest['methods']),memory_layout=layout,
        source_sha256=manifest['source_sha256'],spg_modified=False,
        generated_c_sha256=hashlib.sha256((CSRC/'stage_scroll_generated.c').read_bytes()).hexdigest())
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__': main()
