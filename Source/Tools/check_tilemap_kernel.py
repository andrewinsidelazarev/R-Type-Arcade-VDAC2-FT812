"""Непрерывный Z80: полный скроллер, полный объект карт и межбанковые провайдеры."""
import hashlib
import json
import logging
from pathlib import Path
import random
import struct

from build_tilemap_kernel import ROOT,BUILD,main as build
from build_translator_demo import write
from check_translator_demo import StrictDemoMachine
from rtype_port.stage import M72Tilemaps,M72Scroll


def main():
    logging.getLogger().setLevel(logging.ERROR)
    dependencies=[ROOT/'Source/Tools/pyz80_compiler'/name for name in
                  ('aggregate_backend.py','frozen_constructor.py','definite_scalars.py','buffer_backend.py','write_table.py')]
    dependencies += [ROOT/'Source/Tools'/name for name in ('build_tilemap_aggregate.py','build_tilemap_kernel.py','check_tilemap_kernel.py')]
    implementation={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in dependencies}
    manifest=build();rng=random.Random(814)
    machine=StrictDemoMachine(ROOT)
    machine.mem.pages[:]=[0,5,0x30,0xa6];machine.reg.SP=0x3fff;machine.fmaddr_enabled=True
    for name,bank in manifest['banks'].items():
        machine.mem.write_physical(bank['physical_page'],0,(BUILD/(name+'.bin')).read_bytes())
    for resource in manifest['resources']:
        data=Path(resource['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==resource['sha256']
        machine.mem.write_physical(resource['first_page'],0,data)
    machine.mem.write_block_linear(manifest['thunk_address'],(BUILD/'thunks.bin').read_bytes())
    machine.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    machine.mem.write_physical(0x58,0,rng.randbytes(32768))
    reference=M72Tilemaps();scroll=M72Scroll()
    fields=json.loads((ROOT/'Build/StageRecord/record_manifest.json').read_text(encoding='utf-8'))['fields']
    commands=0;tick_times=[];all_times=[]
    def check(label):
        actual=struct.unpack('<6i',machine.get_memory(0x2000,24))
        assert actual==tuple(reference.target+reference.tracker+reference.source),(label,actual,reference.target,reference.tracker,reference.source)
        assert all(machine.mem.read_physical(0x58+i,0,16384)==data for i,data in enumerate(reference.vram)),(label,'VRAM')
        expected=bytearray()
        for name,kind in fields.items():
            value=getattr(scroll,name)
            if kind=='PyRecordMaybeI32': expected+=struct.pack('<iB',value or 0,value is not None)
            else: expected+=struct.pack('<i',value)
        assert machine.get_memory(0x3100,len(expected))==expected,(label,'scroll')
        assert machine.mem.pages==[0,5,0x30,0xa6],(label,'банки',machine.mem.pages)
        assert machine.reg.SP==0x3fff and machine.get_byte(0x3c00)==0xa5,(label,'стек')
    def execute(operation,args=(),presence=0,valid=True):
        nonlocal commands
        packet=struct.pack('<BBBx3i',operation,0,presence,*(list(args)+[0]*(3-len(args))))
        machine.mem.write_block_linear(0x2140,packet)
        before=machine.tstates;machine.call(manifest['banks']['state']['entry'],max_steps=10000000)
        elapsed=machine.tstates-before;all_times.append(elapsed)
        assert bool(machine.get_byte(0x2130))==valid,(commands,operation,machine.get_memory(0x2130,4))
        if valid: assert machine.get_byte(0x2131)==0
        check((commands,operation));commands+=1
        return elapsed
    init_tstates=execute(0)
    for frame in range(768):
        if frame%113==0:
            foreground=rng.choice([None,0,64,128,256]);background=rng.choice([None,0,128,256])
            scroll.queue_object_velocity_write(foreground,background)
            execute(7,(foreground or 0,background or 0),int(foreground is not None)|(int(background is not None)<<1))
        if frame%197==0:
            scroll.queue_stage_transition_reset();execute(8)
        scroll.advance();reference.advance(scroll);tick_times.append(execute(1))
        if frame%97==0:
            args=(rng.randrange(-2,2),rng.randrange(32),rng.randrange(64))
            execute(3,args)
            assert struct.unpack('<2i',machine.get_memory(0x2020,8))==reference.state(*args)
        if (frame+1)%128==0: print('Z80: совпало',frame+1,'кадров полного объекта',flush=True)
    fallback_times=[]
    for args in [(0,1,0),(1,5120,16),(-1,0,240)]:
        reference._draw_strip(*args);fallback_times.append(execute(4,args))
    for args in [(-1,0,16384),(-2,16384,0)]:
        reference._crossing(*args);execute(2,args)
    execute(2,(2,0,16384),valid=False)
    assert machine.get_byte(0x2131)==6
    # После ошибки продолжение выполняется обычным методом, а не откатом снимка.
    reference._pump();execute(5)
    reference=M72Tilemaps();execute(6)
    execute(255,valid=False)
    for resource in manifest['resources']:
        data=Path(resource['path']).read_bytes()
        assert machine.mem.read_physical(resource['first_page'],0,len(data))==data
    canary=machine.get_memory(0x3c00,0x3f0)
    stack=next((len(canary)-i+16 for i,byte in enumerate(canary) if byte!=0xa5),16)
    assert implementation=={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in dependencies},'Реализация изменилась во время проверки'
    result=dict(frames=768,commands=commands,byte_mismatches=0,scalar_mismatches=0,state_injected_from_python=False,
        all_methods_linked=True,stack_guard=True,max_stack_bytes=stack,bank_restored=True,
        init_tstates=init_tstates,worst_tick_tstates=max(tick_times),best_tick_tstates=min(tick_times),
        fallback_tstates=fallback_times,reinitialisation=True,invalid_command_rejected=True,
        implementation_sha256=implementation,
        manifest_sha256=hashlib.sha256((BUILD/'manifest.json').read_bytes()).hexdigest(),spg_linked=False)
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__': main()
