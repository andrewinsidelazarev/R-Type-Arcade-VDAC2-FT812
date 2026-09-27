"""Исполнение нового SPG в Z80-модели и покадровая сверка подмножества Python."""
from pathlib import Path
import hashlib
import json
import os
import sys
import logging

from translator_paths import ROOT, BUILD
sys.path[:0]=[str(ROOT/'Source/Tools'),str(ROOT/'Source/Python'),str(ROOT/'Build/PythonDeps')]
os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
from sim_boot_check import TSConfFT812Machine,parse_sym


class StrictDemoMachine(TSConfFT812Machine):
    """HALT завершается только настоящим входом в разрешённый IM2-обработчик."""
    irq_mask=0
    frame_irqs=0

    def _write_ref(self,ref,value):
        if ref==0x042a and self.fmaddr_enabled:
            self.irq_mask=value
        return super()._write_ref(ref,value)

    def _write_tsconf_register(self,reg,value):
        if reg==0x2a:
            self.irq_mask=value
        return super()._write_tsconf_register(reg,value)

    def run_until_pc(self,pc,max_steps=2000000):
        for steps in range(max_steps):
            if self.reg.PC==pc:
                return steps
            if self.mem.read(self.reg.PC)==0x76:
                if not self.reg.IFF or not (self.irq_mask&1) or self.reg.IM!=2:
                    raise RuntimeError(f'Необратимый HALT: PC={self.reg.PC:04X}, '
                                       f'IFF={self.reg.IFF}, IM={self.reg.IM}, mask={self.irq_mask}')
                resume=(self.reg.PC+1)&65535
                self.reg.SP=(self.reg.SP-2)&65535
                self.mem.write(self.reg.SP,resume&255)
                self.mem.write((self.reg.SP+1)&65535,resume>>8)
                vector=(self.reg.I<<8)|255
                self.reg.PC=self.mem.read(vector)|(self.mem.read((vector+1)&65535)<<8)
                self.reg.IFF=False
                self.reg.IFF2=False
                self.frame_irqs+=1
            else:
                self.step()
        raise TimeoutError(f'PC={self.reg.PC:04X}, ожидается {pc:04X}')


def main():
    logging.getLogger().setLevel(logging.ERROR)
    sym=parse_sym(BUILD/'demo.sym')
    # Отрицательная проверка: запрещено считать DI/HALT успешным ожиданием.
    broken=StrictDemoMachine(ROOT)
    broken.mem.write_block_linear(0x8000,b'\xf3\x76')
    broken.reg.PC=0x8000
    try:
        broken.run_until_pc(0x8002,max_steps=4)
    except RuntimeError as error:
        assert 'HALT' in str(error)
    else:
        raise AssertionError('Проверка ошибочно пропустила DI/HALT')
    m=StrictDemoMachine(ROOT,spgbld_path=BUILD/'demo.ini',sym_path=BUILD/'demo.sym',load_spg=True)
    m.run_until_pc(sym['MainLoop'],max_steps=20000000)
    print('boot reached MainLoop',flush=True)
    blob=(BUILD/'graphics.bin').read_bytes()
    assert bytes(m.ft.ram_g[:len(blob)])==blob,'RAM_G отличается от упакованных HQ-ресурсов'
    build_report=json.loads((BUILD/'build_report.json').read_text(encoding='utf-8'))
    stage=build_report.get('stage_kernel')
    if stage:
        assert m.mem.read_physical(stage['physical_page'],0,16384)==(BUILD/'stage_kernel.bin').read_bytes()
        assert m.mem.pages[3]==6,'Кодовый банк не восстановлен после init'
        assert not build_report['timing_replay_linked']
        assert 'timing.bin' not in (BUILD/'demo.ini').read_text()
    table_bytes=0
    for page,name in build_report.get('table_pages',[]):
        expected=(BUILD/name).read_bytes()
        assert m.mem.read_physical(page,0,len(expected))==expected,('Страница таблицы повреждена в SPG',page)
        table_bytes+=len(expected)
    assert m.get_byte(sym['demo_fault'])==0
    frames=[]
    frame_tstates=[]
    for tick in range(1,8):
        before=m.tstates
        m.step()
        m.run_until_pc(sym['MainLoop'],max_steps=2000000)
        frame_tstates.append(m.tstates-before)
        fault=m.get_byte(sym['demo_fault'])
        assert not fault,(tick,fault)
        assert m.mem.pages[3]==6,'Кодовый банк не восстановлен после кадра'
        frames.append(m.get_byte(sym['frame'])|m.get_byte(sym['frame']+1)<<8)
    assert frames==list(range(0x293,0x29a)),frames
    dl_bytes=m.get_word(sym['demo_dl_bytes'])
    dl=m.get_memory(0x1000,dl_bytes)
    words=[int.from_bytes(dl[i:i+4],'little') for i in range(0,len(dl),4)]
    formats=[(w>>19)&31 for w in words if w>>24==7]
    assert formats and set(formats)=={6},('Ожидается ARGB4444, не L8',formats)
    print('seven complete Z80/FT frames:',frames,flush=True)
    report={'boot':True,'ram_g_bytes_exact':len(blob),'table_bytes_exact':table_bytes,'frames':frames,
            'frame_z80_tstates':frame_tstates,
            'rejects_di_halt':True,'bitmap_formats':sorted(set(formats)),
            'frame_irqs_during_boot':m.frame_irqs,
            'stack_canary':m.get_byte(0x3c00),'spg_sha256':hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()}
    assert report['stack_canary']==0xa5
    (BUILD/'verified_ram_dl.bin').write_bytes(dl)
    (BUILD/'z80_check.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__': main()
