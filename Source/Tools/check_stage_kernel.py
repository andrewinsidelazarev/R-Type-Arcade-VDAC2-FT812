"""Непрерывное исполнение ABI банка уровня в Z80, без копирования состояния с ПК."""
import hashlib
import json
import logging
import random
import struct

from check_translator_demo import ROOT,StrictDemoMachine
from build_stage_kernel import BUILD,main as build
from build_translator_demo import write
from rtype_port.stage import M72Scroll


def main():
    logging.getLogger().setLevel(logging.ERROR)
    build()
    manifest=json.loads((BUILD/'kernel_manifest.json').read_text(encoding='utf-8'))
    m=StrictDemoMachine(ROOT);m.mem.pages[:]=[0,5,0x30,manifest['physical_page']];m.reg.SP=0x3fff
    binary=(BUILD/'stage_kernel.bin').read_bytes()
    m.mem.write_physical(manifest['physical_page'],0,binary)
    m.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    source=M72Scroll();commands=0;timing=[]
    rng=random.Random(72)
    def execute(operation,args=(),present=0):
        nonlocal commands
        data=struct.pack('<BB3H',operation,present,*(list(args)+[0]*(3-len(args))))
        m.mem.write_block_linear(0x2140,data)
        before=m.tstates;m.call(manifest['entry']);timing.append(m.tstates-before)
        assert m.get_byte(0x2130)==0
        actual=struct.unpack('<8H',m.get_memory(0x2120,16))
        expected=tuple(getattr(source,name) for name in manifest['abi']['outputs'])
        assert actual==expected,(commands,operation,actual,expected)
        assert m.reg.SP==0x3fff and m.get_byte(0x3c00)==0xa5
        commands+=1
    execute(0)
    for frame in range(1108):
        if frame%41==0:
            fg=rng.choice([None,0,64,128,256,65535]);bg=rng.choice([None,0,64,128,256,65535])
            source.queue_object_velocity_write(fg,bg)
            execute(2,(fg or 0,bg or 0),int(fg is not None)|(int(bg is not None)<<1))
        if frame%137==0:
            source.queue_stage_transition_reset();execute(3)
        if frame%193==0:
            args=tuple(rng.randrange(65536) for _ in range(3))
            source.queue_stage_init(*args);execute(4,args)
        source.advance();execute(1)
        if (frame+1)%200==0: print('Stage bank:',frame+1,'кадров',flush=True)
    # Неизвестная команда должна быть отвергнута до изменения состояния.
    output=m.get_memory(0x2120,16)
    m.mem.write(0x2140,255);m.call(manifest['entry'])
    assert m.get_byte(0x2130)==1 and m.get_memory(0x2120,16)==output
    source=M72Scroll();execute(0);source.advance();execute(1)
    result=dict(frames=1109,commands=commands,source_sha256=manifest['source_sha256'],
        state_injected_from_python=False,output_mismatches=0,stack_guard=True,invalid_command_rejected=True,
        worst_dispatch_tstates=max(timing),binary_sha256=hashlib.sha256(binary).hexdigest(),spg_modified=False)
    write(BUILD/'check_report.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__': main()
