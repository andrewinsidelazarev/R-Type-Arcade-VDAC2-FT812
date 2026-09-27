"""Все кадры профиля: CPython-блоки исходника против настоящих инструкций SDCC/Z80.

Game.update целиком пока не переносится: адаптеры пустой сцены выключают только
внешние эффекты исключённых подсистем. Сами проверяемые Python-блоки не режутся
проекцией C-генератора. Красные враги сверяются с полным M72EnemyWorld.update.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
import logging
import re
import struct
from types import SimpleNamespace

from check_translator_demo import ROOT, BUILD, StrictDemoMachine, parse_sym
from rtype_port import game
from rtype_port.enemies import M72EnemyWorld, RedFlyer, read_descriptor
from rtype_port.stage import M72Scroll


def source_blocks():
    tree=ast.parse((ROOT/'Source/Python/rtype_port/game.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Game')
    methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    body=methods['update'].body
    def compile_block(nodes):
        fn=ast.parse('def run(self, inputs=None, occupied_shot_slots=0, target=None): pass').body[0]
        fn.body=copy.deepcopy(nodes)
        module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
        namespace=dict(vars(game))
        exec(compile(module,'<неизменённые блоки Game>','exec'),namespace)
        return namespace['run']
    move=next(i for i,n in enumerate(body) if isinstance(n,ast.If) and ast.unparse(n.test)=='exit_player_native is None')
    fire=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='fire')
    pending=next(n for n in body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.pending_shot_spawn')
    wave=next(n for n in body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.wave is not None')
    wave_draw=next(n for n in methods['render'].body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.wave is not None and self.wave.delay == 0')
    fields=('player_x','player_y','player_pitch','fire_held','wave_charge','pending_shot_spawn')
    initial=[n for n in methods['__init__'].body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) in {'self.'+f for f in fields}]
    assert len(initial)==len(fields)
    return dict(init=compile_block(initial),move=compile_block(body[move].body+body[move+1:move+4]),
                fire=compile_block(body[fire:fire+2]),pending=compile_block([pending]),
                wave=compile_block([wave]),wave_draw=compile_block([wave_draw]),fields=fields)


def new_player(blocks):
    p=game.Game.__new__(game.Game)
    blocks['init'](p)
    p.wave=None; p.shots=[]
    p.play_sfx=lambda code: None
    p.enemy_world=SimpleNamespace(weapon_type=0,request_player_shot_visual=lambda:None,
                                 damage_wave_at=lambda rect,power:0)
    return p


def controls(tick):
    # Короткие нажатия, каждый уровень мощности, насыщение заряда и клавиши вместе с мышью.
    holds=(1,11,13,25,37,41,53,65,85)
    age=(tick-1)%sum(h+12 for h in holds)
    for hold in holds:
        if age<hold+12:
            fire=age<hold
            break
        age-=hold+12
    flags=((tick//23)&15)|(16 if fire else 0)
    return flags,((tick//97)*149)%590,((tick//71)*113)%420


def records(machine,address,count,width):
    return list(struct.iter_unpack('<'+'i'*width,machine.get_memory(address,count*width*4)))


def dl_jobs(machine,sym,assets):
    data=machine.get_memory(0x1000,machine.get_word(sym['demo_dl_bytes']))
    images={r[0]:i for i,r in enumerate(assets['bitmaps'])}
    source=None; jobs=[]
    for (word,) in struct.iter_unpack('<I',data):
        if word>>24==1: source=word&0x3fffff
        if word>>30==1:
            x=(word>>15)&32767; y=word&32767
            if x&16384: x-=32768
            if y&16384: y-=32768
            jobs.append((images[source],x,y))
    # Независимый медленный точный расчёт по всем 768 строкам на ПК.
    cost=[0]*768
    for image,x,y in jobs:
        _,width,height=assets['bitmaps'][image]
        pw,ph=(width*8+4)//5,(height*8+4)//5
        for row in range(max(0,y//8),min(768,y//8+ph)):
            cost[row]+=pw+18
    return jobs,max(cost)


def source_draw_jobs(player,names,red_jobs,visible,counter):
    # Game.render исполняется целиком. Ресурсы представлены идентификаторами;
    # исключённые Force/Bits/ландшафт/подписи HUD ничего не рисуют.
    nothing=lambda *args:None
    player.stage=SimpleNamespace(draw_back=nothing,draw_front=nothing)
    player.force=SimpleNamespace(draw=nothing)
    player.bits=SimpleNamespace(draw=nothing)
    result=[]
    player.enemy_world.draw=lambda target:result.extend(red_jobs)
    player.enemy_world.atlas=None
    player.intro_frame=game.INTRO_FRAMES
    player.launch_frames=()
    player.lifecycle=SimpleNamespace(dying=False,active=True)
    player.m72_frame_counter=counter
    player.player_images=[names['PITCH'+str(i)] for i in range(5)]
    player.shot_image=names['SHOT']
    player.charge_images=[names['CHARGE'+str(i)] for i in range(8)]
    player.beam_meter_images=[names['METER'+str(i)] for i in range(65)]
    # HUD_FIXED обрезан провайдером ресурсов демо; его позицию здесь не подменяем.
    player.hud_image=None
    player._draw_player_label=nothing
    player._draw_score=nothing
    player._draw_debug_distance=nothing
    def blit(image,xy):
        x,y=xy
        if image is not None and visible(image,x,y):
            result.append((image,x*64//5,y*64//5))
    game.Game.render(player,SimpleNamespace(fill=nothing,blit=blit))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--frames',type=int,default=1100)
    parser.add_argument('--render-from',type=int,default=1)
    parser.add_argument('--render-to',type=int,default=0)
    parser.add_argument('--report-name',default='scenario_check.json')
    args=parser.parse_args()
    logging.getLogger().setLevel(logging.ERROR)
    report=json.loads((BUILD/'build_report.json').read_text(encoding='utf-8'))
    assets=report['assets']; names=assets['image_ids']
    sealed=hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()
    assert sealed==report['spg_sha256']
    sym=parse_sym(BUILD/'demo.sym')
    sym.update({name:int(address,16) for address,name in re.findall(r'^\s*([0-9A-Fa-f]{8})\s+_(\w+)\b',
               (BUILD/'demo.map').read_text(encoding='latin1'),re.M)})
    m=StrictDemoMachine(ROOT,spgbld_path=BUILD/'demo.ini',sym_path=BUILD/'demo.sym',load_spg=True)
    m.mem.pages[:]=[0,5,0x30,6]; m.reg.SP=0x3fff
    m.fmaddr_enabled=True
    m.mem.write_block_linear(0x3c00,b'\xa5'*0x3f0)
    m.call(sym['Demo_Init'])
    blocks=source_blocks(); p=new_player(blocks)
    world=M72EnemyWorld(); scroll=M72Scroll()
    empty=SimpleNamespace(collision_codes=lambda x,y:(0xffff,0xffff))
    timing=[]; high_cost=0; old_mouse=(0,0); wave_tiers=set(); frames_with_wave=0
    largest_stack=0
    for absolute_tick in range(1,args.frames+1):
        tick=(absolute_tick-1)%assets['frames']+1
        flags,mx,my=controls(absolute_tick)
        if tick==1 and absolute_tick>1:
            p=new_player(blocks); world=M72EnemyWorld(); scroll=M72Scroll()
            old_mouse=(mx,my); high_cost=0
        scroll.advance()
        counter=0x0292+tick
        world.update(scroll.dispatch_progression,scroll.dispatch_foreground_delta,counter,
                     background_delta=scroll.dispatch_background_delta)
        if (mx,my)!=old_mouse:
            p.player_x=mx*game.Q8; p.player_y=my*game.Q8
            old_mouse=(mx,my)
        inp=game.InputState(bool(flags&1),bool(flags&2),bool(flags&4),bool(flags&8),bool(flags&16))
        blocks['move'](p,inp)
        blocks['wave'](p)
        for shot in p.shots:
            game.Game._advance_native_shot(p,shot,empty,lambda *a:None)
        p.shots=[s for s in p.shots if s.native_x<0x2b8 and s.x<640*game.Q8]
        blocks['pending'](p,inp,len(p.shots))
        blocks['fire'](p,inp,len(p.shots))
        delta=((scroll.dispatch_foreground_delta+32768)&65535)-32768
        m.mem.pages[2]=0x30
        # Координаты/кнопки — единственные входы. В старые timing-ячейки пишется
        # яд, чтобы обнаружить случайно оставшееся чтение эталонной траектории.
        m.mem.write_block_linear(0x2100,struct.pack('<BBHHhH',flags,0,mx,my,-12345,0xdead))
        before=m.tstates; m.call(sym['Demo_Tick']); logic=m.tstates-before
        assert m.get_word(0x2106)==(delta&65535) and m.get_word(0x2108)==scroll.progression
        assert m.mem.pages[3]==6
        assert m.reg.SP==0x3fff,(absolute_tick,'SP после логики',m.reg.SP)
        assert not m.get_byte(sym['demo_fault']),(absolute_tick,'fault',m.get_byte(sym['demo_fault']))
        actual=records(m,sym['player'],1,6)[0]
        expected=tuple(int(getattr(p,f)) for f in blocks['fields'])
        assert actual==expected,(absolute_tick,'player',actual,expected)
        actual=sorted(r[:4] for r in records(m,sym['shots'],3,5) if r[4])
        expected=sorted((s.x,s.y,s.native_x,s.native_y) for s in p.shots)
        assert actual==expected,(absolute_tick,'shots',actual,expected)
        actual=records(m,sym['wave'],1,9)[0]
        expected=None if p.wave is None else tuple(getattr(p.wave,f) for f in ('x','y','release_x','release_y','power','delay','animation','render_power'))
        assert (actual[:8] if actual[8] else None)==expected,(absolute_tick,'wave',actual,expected)
        if p.wave:
            wave_tiers.add(p.wave.power); frames_with_wave+=1
        actual=sorted(r[:3]+r[4:] for r in records(m,sym['enemies'],assets['enemy_capacity'],8) if r[3])
        reds=[e for e in world.enemies if isinstance(e,RedFlyer) and e.alive]
        expected=sorted((e.x,e.y,e.descriptor,e.motion.script,e.motion.pointer,e.motion.commands,e.motion.phase) for e in reds)
        assert actual==expected,(absolute_tick,'enemies',actual,expected)
        assert m.get_word(sym['frame'])==counter
        assert m.get_word(0x210a)==tick
        # Каждый процесс исполняет всю логику непрерывно. Только независимая
        # аппаратная подготовка кадров разделена на непересекающиеся участки.
        if not args.render_from<=absolute_tick<=(args.render_to or args.frames):
            continue
        state_regions=((sym['player'],24),(sym['enemies'],assets['enemy_capacity']*32),
                       (sym['shots'],60),(sym['wave'],36))
        before_state=[m.get_memory(a,n) for a,n in state_regions]
        m.mem.pages[2]=0x32
        before=m.tstates; m.call(sym['Demo_Render']); render=m.tstates-before
        assert not m.get_byte(sym['demo_fault']),(absolute_tick,'render fault',m.get_byte(sym['demo_fault']))
        assert before_state==[m.get_memory(a,n) for a,n in state_regions],(absolute_tick,'Render изменил игровое состояние')
        jobs,peak=dl_jobs(m,sym,assets)
        high_cost=max(high_cost,peak)
        assert m.get_word(0x210c)==high_cost,(absolute_tick,'line peak',m.get_word(0x210c),high_cost)
        def visible(image,x,y):
            _,width,height=assets['bitmaps'][image]
            return x<640 and y<480 and x+width>0 and y+height>0
        red_jobs=[]
        for e in reds:
            phase=(e.descriptor-0x28e2)//6
            d=read_descriptor(world.rom,e.descriptor)
            x=round((e.x+d.dx-320)*5/3)+assets['enemy_origins'][phase][2]
            y=round((384-e.y-d.dy-16*d.height)*15/8)+assets['enemy_origins'][phase][3]
            image=names['RED'+str(phase)]
            if visible(image,x,y): red_jobs.append((image,x*64//5,y*64//5))
        red_ids={names['RED'+str(i)] for i in range(8)}
        # blit — последовательность наложений, а не множество спрайтов.
        actual_red_jobs=[j for j in jobs if j[0] in red_ids]
        assert actual_red_jobs==red_jobs,(absolute_tick,'red draw order',actual_red_jobs,red_jobs)
        p.wave_release_images=[names['RELEASE'+str(i)] for i in range(4)]
        p.wave_images={power:[names[f'WAVE{power}_{i}'] for i in range(2)] for power in game.WAVE_POWER_TABLE[1:]}
        wave_jobs=[]
        def blit(image,xy):
            x,y=xy
            if visible(image,x,y): wave_jobs.append((image,x*64//5,y*64//5))
        blocks['wave_draw'](p,target=SimpleNamespace(blit=blit))
        wave_ids={v for k,v in names.items() if k.startswith(('WAVE','RELEASE'))}
        assert [j for j in jobs if j[0] in wave_ids]==wave_jobs,(absolute_tick,'wave vertices')
        expected_draw=source_draw_jobs(p,names,red_jobs,visible,counter)
        selected_ids=red_ids|wave_ids|{names['SHOT']}|{
            value for name,value in names.items() if name.startswith(('PITCH','CHARGE','METER'))}
        actual_draw=[j for j in jobs if j[0] in selected_ids]
        assert actual_draw==expected_draw,(absolute_tick,'Game.render painter order',actual_draw,expected_draw)
        assert m.reg.SP==0x3fff
        canary=m.get_memory(0x3c00,0x3f0)
        used=next((len(canary)-i+16 for i,b in enumerate(canary) if b!=0xa5),16)
        largest_stack=max(largest_stack,used)
        assert canary[0]==0xa5
        timing.append(dict(tick=absolute_tick,logic=logic,render=render,enemies=len(reds),line_peak=peak))
        if tick%100==0: print(f'{absolute_tick}: состояние, вершины, строки и стек совпадают',flush=True)
    assert hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()==sealed,'Сборка изменена во время теста'
    result=dict(frames=args.frames,spg_sha256=sealed,source_sha256=report['source_sha256'],
        rendered_frames=len(timing),render_range=[args.render_from,args.render_to or args.frames],
        state_mismatches=0,red_vertex_mismatches=0,red_draw_order_mismatches=0,wave_vertex_mismatches=0,
        painter_order_mismatches=0,
        wave_powers=sorted(wave_tiers),frames_with_wave=frames_with_wave,
        max_line_cost=max(t['line_peak'] for t in timing),max_stack_bytes=largest_stack,
        worst_logic_tstates=max(t['logic'] for t in timing),worst_render_tstates=max(t['render'] for t in timing),
        worst_combined_tstates=max(t['logic']+t['render'] for t in timing),timing=timing,
        scope='C/Z80 Tick+Render, без платформенного ввода, SPI и ожидания swap; отдельный boot-check обязателен')
    destination=(BUILD/args.report_name).resolve()
    if not destination.is_relative_to(BUILD.resolve()): raise ValueError('Отчёт вне каталога сборки')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in result.items() if k not in ('timing','source_sha256')},flush=True)


if __name__=='__main__': main()
