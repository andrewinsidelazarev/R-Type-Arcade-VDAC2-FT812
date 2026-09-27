"""Отдельный SPG: ограниченный AST→C профиль, без старой игровой ASM-логики."""
from __future__ import annotations
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

from translator_paths import ROOT, BUILD
CSRC = ROOT / 'Source/C/demo'
sys.path[:0] = [str(ROOT / 'Build/PythonDeps'), str(ROOT / 'Source/Python'), str(ROOT / 'Source/Tools')]
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
from pyz80_compiler.demo_projection import ScalarRecordEmitter, retain_writes
from pyz80_compiler.finite_expression import tabulate_i32
from pyz80_compiler.frontend import module_constants, lower_function
from pyz80_compiler.manifest import FunctionSpec
from pyz80_compiler.c_backend import emit_c
from pyz80_compiler.pipeline import _verify_oracle
from pyz80_compiler.analysis import analyze_function


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding='utf-8', newline='\n')
    else:
        path.write_bytes(data)


def command(args):
    env = os.environ.copy()
    env['PATH'] = 'E:/zx/sdcc/bin;' + env['PATH']
    proc = subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace')
    if proc.returncode:
        raise RuntimeError(proc.stdout)
    return proc.stdout


def method(tree, cls, name):
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)


def span(nodes):
    return [{'line': n.lineno, 'end': n.end_lineno,
             'ast_sha256': hashlib.sha256(ast.dump(n).encode()).hexdigest()}
            for n in nodes]


def translated_code():
    path = ROOT / 'Source/Python/rtype_port/game.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    constants = module_constants(tree)
    update = method(tree, 'Game', 'update')
    pure = []
    tested = 0
    for name, args in [
        ('advance_pitch', [('pitch','u8',0,39),('up','bool',0,1),('down','bool',0,1)]),
        ('advance_wave_charge', [('charge','u8',0,128)]),
        ('wave_power', [('charge','u8',0,128)]),
        ('wave_power_tier', [('power','u8',0,20)]),
        ('beam_animation_phase', [('m72_frame_counter','u16',0,65535)]),
    ]:
        spec = FunctionSpec.from_json({'symbol':'rtype_port.game.'+name, 'export':name,
            'parameters':[dict(name=n,type=t,minimum=a,maximum=b) for n,t,a,b in args],
            'return':'u8', 'exhaustive':True})
        ir, located = lower_function(ROOT/'Source/Python', spec)
        analyze_function(ir,stack_budget=768,isr_reserve=64)
        tested += _verify_oracle(ir, located, spec)
        pure.append(ir)
    generated = emit_c(tuple(pure), ())
    write(CSRC/'demo_scalar_generated.c', generated)
    prototypes = '\n'.join(re.findall(r'^uint8_t .*?__sdcccall\(0\)', generated, re.M))
    prototypes = prototypes.replace('\n', ';\n') + ';\n'
    prefix = '#include "demo_platform.h"\n' + prototypes
    wave_class=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Wave')
    wave_fields=[n for n in wave_class.body if isinstance(n,ast.AnnAssign)]
    wave_aliases={'self.wave':'wave.active', **{'self.wave.'+n.target.id:'wave.'+n.target.id for n in wave_fields}}
    aliases = {'self':'p', 'inputs':'in', **wave_aliases}
    emitter = ScalarRecordEmitter(constants, aliases)
    move_if = next(n for n in update.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'exit_player_native is None')
    movement = list(move_if.body)
    start = update.body.index(move_if)
    movement += update.body[start+1:start+4]
    prefix += emitter.function('void translated_move(Player *p, Inputs *in)', movement)

    native = method(tree,'Game','_logical_player_native').body[-1].value
    tables=[]; table_pages=[]
    def bind_table(expression,argument,stop,page,owner,index_expression,proof):
        data,record=tabulate_i32(expression,argument,stop,constants)
        record.update(first_page=page,domain_proof=proof)
        tables.append(record)
        for i in range((len(data)+16383)//16384):
            filename=f'table_{page+i:02x}.bin'
            write(BUILD/filename,data[i*16384:(i+1)*16384])
            table_pages.append((page+i,filename))
        owner.aliases[ast.unparse(expression)]=f'demo_table_i32({index_expression}, {page})'
    # Эти координаты уже ограничены исходным min/max в translated_move.
    # Таблица индексируется логическим пикселем, а не дробной частью Q8.
    bind_table(native.elts[0],'self.player_x // Q8',640,0xa0,emitter,'(uint16_t)(p->player_x >> 8)',
               'Game.update: 0 <= player_x <= (640 - PLAYER_W) * Q8 до вызова')
    bind_table(native.elts[1],'self.player_y // Q8',480,0xa1,emitter,'(uint16_t)(p->player_y >> 8)',
               'Game.update: 0 <= player_y <= (PLAYFIELD_H - PLAYER_H) * Q8 до вызова')
    def round_call(n, e):
        ratio = n.args[0]
        if not isinstance(ratio, ast.BinOp) or not isinstance(ratio.op, ast.Div):
            raise ValueError('round: нужен доказанный рациональный аргумент')
        return f'py_round_ratio({e.expr(ratio.left)}, {e.expr(ratio.right)})'
    emitter.calls = {'round':round_call}
    for label, expr in zip(('x','y'), native.elts):
        ret = ast.copy_location(ast.Return(value=expr), expr)
        prefix += emitter.function(f'int32_t translated_native_{label}(Player *p)', [ret])

    fire_at = next(i for i,n in enumerate(update.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == 'fire')
    # Явный профиль: заряд, обычный выстрел и Wave, без Force и звуковых вызовов.
    fields = {'fire', 'power', 'self.wave', 'self.fire_held', 'self.wave_charge', 'self.pending_shot_spawn'}
    fire = retain_writes(update.body[fire_at:fire_at+2], fields)
    def wave_construct(n,e):
        if len(n.args)!=4 or [k.arg for k in n.keywords]!=['power']:
            raise ValueError('Изменилась сигнатура создания Wave: обновить связывание записей')
        return 'demo_wave_spawn('+', '.join(e.expr(a) for a in [*n.args,n.keywords[0].value])+')'
    emitter.calls['Wave']=wave_construct
    prefix += emitter.function('void translated_fire(Player *p, Inputs *in, int32_t occupied_shot_slots)', fire,
                               parameters=('occupied_shot_slots',))
    # Очередь и координаты нового снаряда — точный блок Game.update.
    pending = next(n for n in update.body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.pending_shot_spawn')
    pending = copy.deepcopy(pending)
    class NativeTuple(ast.NodeTransformer):
        def visit_Assign(self,n):
            if isinstance(n.targets[0],ast.Tuple) and ast.unparse(n.value)=='self._logical_player_native()':
                return [ast.copy_location(ast.Assign(targets=[t], value=x),n) for t,x in zip(n.targets[0].elts,native.elts)]
            return n
    pending = NativeTuple().visit(pending)
    emitter.calls['self.shots.append'] = lambda n,e: 'demo_spawn(' + ', '.join(e.expr(x) for x in n.args[0].args) + ')'
    prefix += 'void demo_spawn(int32_t x, int32_t y, int32_t nx, int32_t ny);\n'
    prefix += emitter.function('void translated_pending(Player *p, int32_t occupied_shot_slots)', [pending],
                               parameters=('occupied_shot_slots',))
    # Коллизии отключены явно: оставить два нативных шага и итоговую координату.
    advance = method(tree,'Game','_advance_native_shot')
    loop = copy.deepcopy(next(n for n in advance.body if isinstance(n,ast.For)))
    loop.body = loop.body[:1]
    shot_nodes = [loop, advance.body[-2], advance.body[-1]]
    se = ScalarRecordEmitter(constants, {'shot':'s'})
    normalization=loop.body[0].value
    if not (isinstance(normalization,ast.BinOp) and isinstance(normalization.op,ast.BitAnd)
            and isinstance(normalization.right,ast.Constant) and normalization.right.value==65535):
        raise ValueError('Не доказан u16-аргумент таблицы обычного выстрела')
    bind_table(advance.body[-2].value,'shot.native_x',65536,0x90,se,'(uint16_t)s->native_x',
               'Перед выражением оба шага записывают (shot.native_x + 8) & 0xFFFF')
    prefix += se.function('uint8_t translated_shot(Projectile *s)',shot_nodes)
    lifetime = next(n for n in ast.walk(update) if isinstance(n, ast.Compare) and ast.unparse(n)=='shot.native_x < 696')
    lifetime_x = next(n for n in ast.walk(update) if isinstance(n, ast.Compare) and ast.unparse(n)=='shot.x < 640 * Q8')
    prefix += 'uint8_t translated_shot_alive(Projectile *s) { return ' + se.expr(lifetime) + ' && ' + se.expr(lifetime_x) + '; }\n'
    init = method(tree,'Game','__init__')
    initial = retain_writes(init.body, {'self.player_x','self.player_y','self.player_pitch','self.wave_charge','self.fire_held','self.pending_shot_spawn'})
    prefix += emitter.function('void translated_init(Player *p)', initial)

    # Значения по умолчанию и __post_init__ берутся из dataclass, не из C-заглушки.
    constructor_parameters=('x','y','release_x','release_y','power')
    ctor=[]
    for field in wave_fields:
        value=ast.Name(id=field.target.id,ctx=ast.Load()) if field.target.id in constructor_parameters else field.value
        if value is None: raise ValueError('Не связан обязательный аргумент Wave: '+field.target.id)
        assignment=ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr=field.target.id,ctx=ast.Store())],value=value)
        ctor.append(ast.copy_location(assignment,field))
    ctor+=method(tree,'Wave','__post_init__').body
    we=ScalarRecordEmitter(constants,{'self':'w'})
    prefix+=we.function('void translated_wave_init(Wave *w, '+', '.join('int32_t '+p for p in constructor_parameters)+')',ctor,parameters=constructor_parameters)
    wave_update=next(n for n in update.body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.wave is not None')
    we=ScalarRecordEmitter(constants,wave_aliases,{'self.enemy_world.damage_wave_at':lambda n,e:'0L'})
    prefix+=we.function('void translated_wave_update(void)',[wave_update])
    draw=method(tree,'Game','render')
    wave_draw=next(n for n in draw.body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.wave is not None and self.wave.delay == 0')
    def wave_blit(n,e):
        name=ast.unparse(n.args[0])
        if name=='self.wave_release_images[release_index]':
            image='IMG_RELEASE0 + release_index'
        elif name=='self.wave_images[self.wave.render_power][phase]':
            image='wave_images[wave.render_power][phase]'
        else: raise ValueError('Не связан ресурс Wave: '+name)
        return 'demo_wave_blit('+image+', '+', '.join(e.expr(a) for a in n.args[1].elts)+')'
    we.calls={'target.blit':wave_blit}
    prefix+='#include "demo_images_generated.h"\nvoid demo_wave_blit(uint8_t image,int16_t x,int16_t y);\n'
    prefix+=we.function('void translated_wave_draw(void)',[wave_draw])

    et = ast.parse((ROOT/'Source/Python/rtype_port/enemies.py').read_text(encoding='utf-8'))
    motion = method(et,'ScriptedMotion','update')
    me = ScalarRecordEmitter({}, {'self':'m','owner':'o'}, {
        'rom.byte':lambda n,e:'rom_byte('+e.expr(n.args[0])+')',
        'rom.word':lambda n,e:'rom_word('+e.expr(n.args[0])+')'})
    prefix += me.function('uint8_t translated_motion(Motion *m, Enemy *o)', motion.body,
                          prefix=('    uint16_t fuel = 256;',))
    red = method(et,'RedFlyer','update')
    red_emitter = ScalarRecordEmitter({}, {'self':'e', 'self.motion.phase':'e->motion.phase', 'world.frame_counter':'frame'}, {
        'self.motion.update':lambda n,e:'translated_motion(&e->motion, e)'})
    prefix += red_emitter.function('void translated_enemy(Enemy *e, int32_t foreground_delta)',red.body[:-1],
                          parameters=('foreground_delta',))
    write(CSRC/'demo_logic_generated.c',prefix)
    return dict(oracle_scalar_cases=tested,finite_tables=tables,table_pages=table_pages,projection={
        'movement':span(movement), 'fire':span(fire), 'pending':span([pending]),
        'shot_empty_space':span(shot_nodes), 'motion':span(motion.body), 'red_flyer_no_fire':span(red.body[:-1]),
        'wave_constructor':span(ctor),'wave_empty_space':span([wave_update]),'wave_draw':span([wave_draw])})


def assets_and_scenario():
    import pygame
    from rtype_port import game
    from rtype_port.enemies import M72EnemyWorld, RedFlyer, read_descriptor
    from rtype_port.stage import M72Scroll
    pygame.init()
    pygame.display.set_mode((1,1))
    blob = bytearray()
    records = []
    names = {}
    def add(name,surface):
        idx = len(records)
        width,height = surface.get_size()
        offset = len(blob)
        raw = pygame.image.tobytes(surface,'RGBA')
        for r,g,b,a in zip(raw[0::4],raw[1::4],raw[2::4],raw[3::4]):
            blob.extend(struct.pack('<H',((a>>4)<<12)|((r>>4)<<8)|((g>>4)<<4)|(b>>4)))
        while len(blob)&3:
            blob.append(0)
        records.append((offset,width,height))
        names[name] = idx
        return idx
    player_dir = game.PLAYER_DIR
    for i in range(5):
        add('PITCH'+str(i), pygame.image.load(str(player_dir/f'R9_PITCH_{i}_C{0x20+i:04X}.png')))
    for i,code in enumerate((0x220,0x222,0x224,0x226,0x230,0x232,0x234,0x236)):
        add('CHARGE'+str(i),pygame.image.load(str(player_dir/f'R9_CHARGE_{i}_C{code:04X}.png')))
    for charge in range(0,129,2):
        add('METER'+str(charge//2),pygame.image.load(str(player_dir/f'BEAM_METER_C{charge:03d}.png')))
    add('SHOT',pygame.image.load(str(game.SPRITE_DIR/'asset_10_c08f8_p0_16x16_f00.png')))
    for power in game.WAVE_POWER_TABLE[1:]:
        for phase in range(2):
            add(f'WAVE{power}_{phase}',pygame.image.load(str(game.SPRITE_DIR/'WavePower'/f'wave_power_{power:02d}_phase_{phase}.png')))
    # Имена исходных ресурсов извлекаются из конструктора Game.
    gt=ast.parse((ROOT/'Source/Python/rtype_port/game.py').read_text(encoding='utf-8'))
    release_assignment=next(n for n in method(gt,'Game','__init__').body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='release_names')
    for i,name in enumerate(ast.literal_eval(release_assignment.value)):
        add('RELEASE'+str(i),pygame.image.load(str(game.SPRITE_DIR/name)))
    hud=pygame.image.load(str(player_dir/'HUD_FIXED.png'))
    add('HUD_BEAM',hud.subsurface((136,0,300,15)).copy())
    font = pygame.font.Font(None,20)
    add('NOTICE',font.render('TRANSLATOR DEMO | NO COLLISIONS / NO AUDIO',True,'white'))
    for i in range(16):
        add('DIGIT'+str(i),font.render(format(i,'X'),False,'white'))
    add('FRAME',font.render('FRAME',False,'white'))
    add('DIST',font.render('DIST',False,'white'))
    from rtype_port.player_lifecycle import INITIAL_LIVES
    add('LIVES',font.render(f'LIVES {INITIAL_LIVES}',False,'white'))

    world = M72EnemyWorld()
    red_offsets = []
    red_origin = []
    for i in range(8):
        d = read_descriptor(world.rom,0x28e2+6*i)
        surface=pygame.Surface((128,128),pygame.SRCALPHA)
        ax,ay=340,360
        world.atlas.draw(surface,d,0,0x0d,ax,ay)
        rect = surface.get_bounding_rect()
        add('RED'+str(i),surface.subsurface(rect).copy())
        red_offsets.append((rect.x-round((ax-320)*5/3),rect.y-round((384-ay)*15/8)))
        base_x=round((ax+d.dx-320)*5/3)
        base_y=round((384-ay-d.dy-16*d.height)*15/8)
        origin=(d.dx-320,384-d.dy-16*d.height,rect.x-base_x,rect.y-base_y)
        # Доказать отсечение за границами LUT по фактическим размерам ресурса.
        assert round(-512*5/3)+origin[2]+rect.width<=0
        assert round(512*5/3)+origin[2]>=640
        assert round(-512*15/8)+origin[3]+rect.height<=0
        assert round(512*15/8)+origin[3]>=480
        red_origin.append(origin)
    # Только независимые от игрока красные автоматы первых 1100 тактов.
    scroll = M72Scroll()
    seen = set()
    spawns=[]
    timing=[]
    peak_reds=0
    for tick in range(1,1101):
        scroll.advance()
        frame_counter = 0x0292 + tick
        world.update(scroll.dispatch_progression, scroll.dispatch_foreground_delta, frame_counter,
                     background_delta=scroll.dispatch_background_delta)
        peak_reds=max(peak_reds,sum(isinstance(e,RedFlyer) and e.alive for e in world.enemies))
        delta = ((scroll.dispatch_foreground_delta + 32768) & 65535) - 32768
        timing.append((delta, scroll.progression))
        for enemy in world.enemies:
            if isinstance(enemy,RedFlyer) and enemy.scheduler_serial not in seen:
                seen.add(enemy.scheduler_serial)
                spawns.append((tick,enemy.x,enemy.y,enemy.descriptor,enemy.motion.script,
                               enemy.motion.pointer,enemy.motion.commands,enemy.motion.phase))
    if not spawns:
        raise RuntimeError('Нет красных врагов в исходном начальном сценарии')
    # ROM-страница для исполняемого интерпретатора, не снимки траекторий.
    rombytes=bytes(world.rom.byte(i) for i in range(0x8000,0xc000))
    write(BUILD/'rom.bin',rombytes)
    if len(blob)>1024*1024:
        raise RuntimeError(f'RAM_G переполнен: {len(blob)}')
    write(BUILD/'graphics.bin',blob)
    out=['/* Сгенерировано из готовых HQ-ресурсов Python. */', '#ifndef DEMO_ASSETS_H','#define DEMO_ASSETS_H',
         'typedef struct { uint32_t commands[5]; uint16_t width,height,physical_width,physical_height; } DemoBitmap;',
         f'#define DEMO_FRAMES {len(timing)}',f'#define DEMO_SPAWNS {len(spawns)}',
         f'#define DEMO_ENEMY_CAPACITY {len(spawns)}',
         'typedef struct { uint16_t tick,x,y,descriptor,script,pointer,commands,phase; } DemoSpawn;']
    image_header=['/* Связывание ресурсов для сгенерированных вызовов blit. */',
                  '#ifndef DEMO_IMAGES_H','#define DEMO_IMAGES_H']
    image_header += [f'#define IMG_{name} {i}' for name,i in names.items()]
    wave_rows=['{0,0}']*(max(game.WAVE_POWER_TABLE)+1)
    for power in game.WAVE_POWER_TABLE[1:]:
        wave_rows[power]='{'+','.join(str(names[f'WAVE{power}_{phase}']) for phase in range(2))+'}'
    image_header+=['static const uint8_t wave_images[][2] = {'+','.join(wave_rows)+'};','#endif']
    write(CSRC/'demo_images_generated.h','\n'.join(image_header)+'\n')
    out+=['#include "demo_images_generated.h"']
    out += ['static const DemoBitmap bitmaps[] = {']
    for o,w,h in records:
        pw,ph=(w*8+4)//5,(h*8+4)//5
        words=[0x01000000|o,0x07000000|(6<<19)|((w*2)<<9)|(h&511),
               0x28000000|(((w*2)>>10)<<2)|(h>>9),
               0x08000000|((pw&511)<<9)|(ph&511),0x29000000|((pw>>9)<<2)|(ph>>9)]
        out.append('{{'+','.join(f'0x{n:08x}ul' for n in words)+f'}},{w},{h},{pw},{ph}'+'},')
    out += ['};']
    out += ['static const DemoSpawn spawns[] = {']+[ '{'+','.join(map(str,r))+'},' for r in spawns]+['};']
    out += ['static const int8_t red_offsets[8][2] = {']+['{'+','.join(map(str,r))+'},' for r in red_offsets]+['};']
    out += ['static const int16_t red_origin[8][4] = {']+['{'+','.join(map(str,r))+'},' for r in red_origin]+['};']
    phase_table=[255]*43
    for phase in range(8): phase_table[6*phase]=phase
    out += ['#define DEMO_RED_FIRST 0x28e2L','#define DEMO_RED_LAST 0x290cL',
            'static const uint8_t red_phase[] = {'+','.join(map(str,phase_table))+'};']
    out += ['#define DEMO_NATIVE_X_LUT 0x8a00', '#define DEMO_NATIVE_Y_LUT 0x9200']
    out += ['static const int8_t pitch_crop[] = {'+','.join(map(str,game.PITCH_CROP_TOP))+'};',
            'static const int8_t charge_left[] = {'+','.join(map(str,game.CHARGE_CROP_LEFT))+'};',
            'static const int8_t charge_top[] = {'+','.join(map(str,game.CHARGE_CROP_TOP))+'};',
            '#endif']
    write(CSRC/'demo_assets_generated.h','\n'.join(out)+'\n')
    # timing остаётся только контрольным эталоном отчёта. В SPG его нет:
    # скроллер исполняется отдельным банком, сгенерированным из всего класса.
    # Точное целочисленное масштабирование вершин вместо делений Z80 на каждом blit.
    coords=b''.join(struct.pack('<h',(x*64)//5) for x in range(-256,1024))
    coords+=b''.join(struct.pack('<h',round(x*5/3)) for x in range(-512,512))
    coords+=b''.join(struct.pack('<h',round(y*15/8)) for y in range(-512,512))
    write(BUILD/'coordinates.bin',coords)
    pygame.quit()
    return dict(ram_g_bytes=len(blob),sprites=len(records),spawns=spawns,frames=len(timing),
                enemy_offsets=red_offsets, timing=timing,peak_reds=peak_reds,
                enemy_capacity=len(spawns),enemy_origins=red_origin,bitmaps=records,image_ids=names)


def build_target(table_pages):
    from build_stage_kernel import main as build_stage, BUILD as STAGE_BUILD
    build_stage()
    stage=json.loads((STAGE_BUILD/'kernel_manifest.json').read_text(encoding='utf-8'))
    write(CSRC/'demo_stage_generated.h',
          '/* Аппаратные точки входа банка, связанного из полного класса. */\n'
          '#define STAGE_KERNEL_THUNK 0x4e00\n'
          '#define STAGE_REQUEST 0x2140\n'
          '#define STAGE_ERROR 0x2130\n'+''.join(
          f'#define STAGE_{name.upper()} (0x2120+{i*2})\n'
          for i,name in enumerate(stage['abi']['outputs'])))
    sdcc=Path('E:/zx/sdcc/bin/sdcc.exe')
    for stem in ('demo_scalar_generated','demo_logic_generated','demo_runtime'):
        command([sdcc,'-mz80','--std-c11','--sdcccall','1','--opt-code-speed','--no-c-code-in-asm',
                 '-I'+str(CSRC),'-c',CSRC/(stem+'.c'),'-o',BUILD/(stem+'.rel')])
    command([sdcc,'-mz80','--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200',
             '-Wl-b_HOME=0xF000',
             '-o',BUILD/'demo.ihx',*[BUILD/(s+'.rel') for s in ('demo_scalar_generated','demo_logic_generated','demo_runtime')]])
    map_text=(BUILD/'demo.map').read_text(encoding='latin1')
    layout=validate_layout(map_text)
    for name,region in layout.items():
        if name=='_DATA':
            other=stage['memory_layout']['_DATA']
            if region['start']<other['end'] and other['start']<region['end']:
                raise RuntimeError('Данные главного и stage-банка пересекаются')
    def symbol(name):
        match=re.search(r'^\s*([0-9A-Fa-f]{8})\s+_'+name+r'\b',map_text,re.M)
        if not match: raise RuntimeError('Нет символа '+name)
        return int(match[1],16)
    command([sdcc.with_name('makebin.exe'),'-s','65536','-o','49152',BUILD/'demo.ihx',BUILD/'code.bin'])
    code_end=symbol('demo_code_end')
    if code_end>=0xff00: raise RuntimeError('Код не помещается в страницу')
    write(BUILD/'symbols.inc','; Связано из нового C-кода.\n'+ '\n'.join(
        f'{name} EQU #{symbol(name):04X}' for name in ('Demo_Init','Demo_Tick','Demo_Render','demo_dl_bytes','frame','demo_fault'))+
        f'\nSTAGE_KERNEL_ENTRY EQU #{stage["entry"]:04X}\nSTAGE_KERNEL_PAGE EQU #{stage["physical_page"]:02X}\n')
    blob=(BUILD/'graphics.bin').read_bytes()
    def block(address,page,path):
        return f'Block = #{address:04X}, #{page:02X}, {path.relative_to(ROOT).as_posix()}'
    blocks=[block(0x4e00,0x05,BUILD/'boot.bin'),block(0,0x06,BUILD/'code.bin'),
            block(0,0x30,BUILD/'rom.bin'),block(0,0x32,BUILD/'coordinates.bin')]
    pages=(len(blob)+16383)//16384
    for i in range(pages):
        filename=f'graphics_{i:02d}.bin'
        write(BUILD/filename,blob[i*16384:(i+1)*16384].ljust(16384,b'\0'))
        blocks.append(block(0,0x40+i,BUILD/filename))
    occupied={0x05,0x06,0x30,0x32,*range(0x40,0x40+pages)}
    if stage['physical_page'] in occupied:
        raise RuntimeError('Страница stage занята')
    occupied.add(stage['physical_page'])
    write(BUILD/'stage_kernel.bin',(STAGE_BUILD/'stage_kernel.bin').read_bytes())
    blocks.append(block(0,stage['physical_page'],BUILD/'stage_kernel.bin'))
    for page,filename in table_pages:
        if page in occupied or not 0<=page<256:
            raise RuntimeError(f'Конфликт физических страниц: {page:02X}')
        occupied.add(page)
        blocks.append(block(0,page,BUILD/filename))
    write(BUILD/'assets.inc',f'; Страничная загрузка готовых битмапов.\nDEMO_GFX_PAGES EQU {pages}\n')
    template=ROOT/'Source/ASM/translator_demo.asm'
    def include_path(match):
        path=(template.parent/match[1]).resolve()
        if path.parent==ROOT/'Build/TranslatorDemo': path=BUILD/path.name
        return 'include "'+path.as_posix()+'"'
    boot=re.sub(r'include "([^"]+)"',include_path,template.read_text(encoding='utf-8'))
    boot=boot.replace('"Build/TranslatorDemo/boot.bin"','"'+(BUILD/'boot.bin').as_posix()+'"')
    write(BUILD/'boot_generated.asm',boot)
    command(['E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe', BUILD/'boot_generated.asm','--syntax=ab',
             '--lst='+str(BUILD/'demo.lst'),'--sym='+str(BUILD/'demo.sym')])
    write(BUILD/'demo.ini','\n'.join(['Desc = New translator interactive demo','Start = 0x5000','Stack = 0x3FFF',
        'Resident = 0x4F00','Page3 = 0','Clock = 2','INT = 0','Pager = 0','Compression = 0','',*blocks])+'\n')
    command(['E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe','-b',BUILD/'demo.ini',BUILD/'rtype_vdac2.spg'])
    stage['spg_linked']=True
    return dict(c_entry=symbol('Demo_Init'),code_end=code_end,memory_layout=layout,stage_kernel=stage,
                timing_replay_linked=False,
                spg_sha256=hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest())


def validate_layout(map_text, *, require_data=True):
    """Проверить ВСЕ секции до упаковки; символ конца функции не задаёт конец банка."""
    sections={name:(int(address,16),int(size,16)) for name,address,size in re.findall(
        r'^(_\w+)\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s+=',map_text,re.M)}
    regions=[]
    for name,(address,size) in sections.items():
        if not size: continue
        end=address+size
        if name in ('_CODE','_HOME'):
            if not 0xc000<=address<end<=0x10000:
                raise RuntimeError(f'{name} вне кодовой страницы: {address:04X}..{end:05X}')
        elif name=='_DATA':
            if not 0x2200<=address<end<=0x3c00:
                raise RuntimeError(f'{name} пересекает зарезервированный стек: {address:04X}..{end:04X}')
        else:
            raise RuntimeError(f'Не поддержана непустая секция без CRT: {name}')
        for other,start,stop in regions:
            if address<stop and start<end:
                raise RuntimeError(f'Пересечение секций {name} и {other}')
        regions.append((name,address,end))
    if not ({'_CODE','_DATA'} if require_data else {'_CODE'})<=sections.keys():
        raise RuntimeError('Неполная карта памяти SDCC')
    return {name:{'start':start,'end':end,'bytes':end-start} for name,start,end in regions}


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    report=translated_code()
    print('AST -> C:',report['oracle_scalar_cases'],'scalar cases',flush=True)
    report['assets']=assets_and_scenario()
    print('assets/scenario ready',flush=True)
    report.update(build_target(report['table_pages']))
    report['excluded']=['terrain','enemy/player collisions','death','Force','Bits','audio','menu','other enemy types']
    report['legacy_gameplay_linked']=False
    report['ordered_list_provider']={'collections':['Game.shots','M72EnemyWorld.enemies'],
        'semantics':'append и стабильное удаление; физический слот не задаёт порядок blit'}
    report['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'Source/Python/rtype_port').glob('*.py')}
    implementation=[*CSRC.glob('*.c'),*CSRC.glob('*.h'),Path(__file__),
        ROOT/'Source/Tools/pyz80_compiler/demo_projection.py',ROOT/'Source/Tools/pyz80_compiler/finite_expression.py',
        ROOT/'Source/ASM/translator_demo.asm',ROOT/'Source/ASM/input.asm',
        ROOT/'Source/Tools/translator_paths.py',ROOT/'Source/Tools/build_stage_record.py',
        ROOT/'Source/C/python_vm/pyz80_ordered_slots.h',
        ROOT/'Source/Tools/build_stage_kernel.py',ROOT/'Source/Tools/pyz80_compiler/record_backend.py',
        *sorted((ROOT/'Source/C/generated').glob('stage_*generated.*'))]
    report['implementation_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in implementation}
    write(BUILD/'build_report.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(str(BUILD/'rtype_vdac2.spg'),report['spg_sha256'],flush=True)


if __name__=='__main__':
    main()
