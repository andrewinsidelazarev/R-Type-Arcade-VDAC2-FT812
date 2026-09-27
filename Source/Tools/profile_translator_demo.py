"""Профиль C-вывода на Z80 для состояния, полученного исполнением Python."""
from bisect import bisect_right
from collections import Counter
import json
import logging
import re
import struct
from types import SimpleNamespace

from check_translator_demo_scenario import ROOT,BUILD,StrictDemoMachine,source_blocks,new_player,controls
from rtype_port import game
from rtype_port.enemies import M72EnemyWorld,RedFlyer
from rtype_port.stage import M72Scroll


def main():
    logging.getLogger().setLevel(logging.ERROR)
    report=json.loads((BUILD/'build_report.json').read_text(encoding='utf-8'))
    sym={name:int(address,16) for address,name in re.findall(r'^\s*([0-9A-Fa-f]{8})\s+_(\w+)\b',
               (BUILD/'demo.map').read_text(encoding='latin1'),re.M)}
    labels={value:name for name,value in sym.items() if value>=0xc000}
    for unit,entry in (('demo_runtime','Demo_Render'),('demo_logic_generated','translated_move'),('demo_scalar_generated','advance_pitch')):
        local={name:int(value,16) for value,name in re.findall(r'^\s*([0-9A-Fa-f]{8})\s+\d+\s+_(\w+)::?$',
            (BUILD/(unit+'.lst')).read_text(encoding='utf-8'),re.M)}
        offset=sym[entry]-local[entry]
        funcs=re.findall(r'; Function (\w+)\s*$',(BUILD/(unit+'.asm')).read_text(encoding='utf-8'),re.M)
        labels.update({local[name]+offset:name for name in funcs})
    addresses=sorted(labels)
    m=StrictDemoMachine(ROOT,spgbld_path=BUILD/'demo.ini',sym_path=BUILD/'demo.sym',load_spg=True)
    m.mem.pages[:]=[0,5,0x30,6]; m.reg.SP=0x3fff; m.fmaddr_enabled=True; m.call(sym['Demo_Init'])
    blocks=source_blocks(); p=new_player(blocks); world=M72EnemyWorld(); scroll=M72Scroll()
    old_mouse=(0,0); empty=SimpleNamespace(collision_codes=lambda x,y:(0xffff,0xffff))
    for tick in range(1,1101):
        scroll.advance()
        world.update(scroll.dispatch_progression,scroll.dispatch_foreground_delta,0x292+tick,background_delta=scroll.dispatch_background_delta)
        flags,mx,my=controls(tick)
        if (mx,my)!=old_mouse: p.player_x=mx*256; p.player_y=my*256; old_mouse=(mx,my)
        inp=game.InputState(bool(flags&1),bool(flags&2),bool(flags&4),bool(flags&8),bool(flags&16))
        blocks['move'](p,inp); blocks['wave'](p)
        for shot in p.shots: game.Game._advance_native_shot(p,shot,empty,lambda *a:None)
        p.shots=[s for s in p.shots if s.native_x<0x2b8 and s.x<640*256]
        blocks['pending'](p,inp,len(p.shots)); blocks['fire'](p,inp,len(p.shots))
    m.mem.write_block_linear(sym['player'],struct.pack('<6i',*(int(getattr(p,f)) for f in blocks['fields'])))
    reds=[e for e in world.enemies if isinstance(e,RedFlyer) and e.alive]
    for i,e in enumerate(reds):
        m.mem.write_block_linear(sym['enemies']+32*i,struct.pack('<8i',e.x,e.y,e.descriptor,1,e.motion.script,e.motion.pointer,e.motion.commands,e.motion.phase))
    for i,s in enumerate(p.shots):
        m.mem.write_block_linear(sym['shots']+20*i,struct.pack('<5i',s.x,s.y,s.native_x,s.native_y,1))
    if p.wave:
        m.mem.write_block_linear(sym['wave'],struct.pack('<9i',*(getattr(p.wave,f) for f in ('x','y','release_x','release_y','power','delay','animation','render_power')),1))
    m.set_word(sym['frame'],0x292+1100)
    m.mem.pages[2]=0x32
    histogram=Counter(); step=m.step
    def profiled_step():
        pc=m.reg.PC
        cycles=step()
        histogram[labels[addresses[bisect_right(addresses,pc)-1]]]+=cycles
        return cycles
    m.step=profiled_step
    m.call(sym['Demo_Render'])
    print('Render at Python tick 1100:',sum(histogram.values()),'T',flush=True)
    print(histogram.most_common(),flush=True)
    print('fault',m.get_byte(sym['demo_fault']),flush=True)


if __name__=='__main__': main()
