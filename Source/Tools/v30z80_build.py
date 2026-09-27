"""Сборка переведённой программы World ROM (V30 → Z80): код, таблицы, страницы TS-Config.

Шаги: состояние машины после загрузки (эталон), поиск кода, функции, значения сегментных
регистров, живость флагов, ассемблер Z80, sjasmplus. Результат —
Build/V30Z80/pages/page_XX.bin, отчёт build_report.json и segments.json (значения ES, CS, SS,
DS перед инструкциями — для проверки на эталоне).
Страницы: #08 резидент (окно #0000), #0C хост адаптеров ввода и видео, SOUND_PAGE — звуковой адаптер
(обе — окно #C000), #10..#6F код (окно #C000), #70..#7F — прямая таблица IP → код (окно #C000 на время
поиска),
SPRITE_BUFFER_PAGE — буфер спрайтов, V30_PAGE_BASE.. — 64 страницы памяти V30.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))

import v30z80  # noqa: E402,F401
from v30z80 import codegen, flags, functions, segments, snapshot  # noqa: E402
from v30z80.discover import discover, vector_targets  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
ASM = ROOT / 'Source' / 'ASM'
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
SPGBLD = Path('E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe')
BOOT_PAGE = 0x05
RES_PAGE = 0x08
SPRITE_BUFFER_PAGE = 0x0B
HOST_PAGE = 0x0C
SWITCH_PAGE = 0x0E              # страница переключения на машину из кода p2c (rtype_spg.py)
SOUND_PAGE = 0x5E               # звуковой адаптер (окно #C000), за ней страницы буфера мелодии
SOUND_TRACK_PAGES = 7           # rtype_sound.TRACK_PAGES
# Таблицы ядер (v30z80_kernels.asm): цели палитр групп 0 и 1 — байты ROM 3B00:тип·48 и 3B00:$2400+тип·48.
PAL_TARGET_PAGE0 = 0x66
PAL_TARGET_PAGE1 = 0x67
KERNEL_PAGES = (PAL_TARGET_PAGE0, PAL_TARGET_PAGE1)
PRISTINE_RESIDENT = 0x0F        # копия резидента после загрузки (новая машина)
PRISTINE_V30_PAGE0 = 0x42       # копии страниц V30 #10 #30 #32 #33 #34 #36 и буфера спрайтов
PRISTINE_V30_PAGES = (0x10, 0x30, 0x32, 0x33, 0x34, 0x36)
CODE_FIRST = 0x10
CODE_LAST = 0x6F
DISPATCH_BASE = 0x70
V30_PAGE_BASE = 0x80
IDLE_POINTS = {0x004D6: (0x42ED8, 0x42EDA)}
# Страницы нативного кода VDAC2+ (Source/ASM/vdac2p_native.asm, окно #C000): свободные в раскладке SPG VDAC2
# (#4A…#4E; кэш секторов загрузчика — #00…#07, #EF, #F9…#FF — их не задевает).
NATIVE_PAGES = (0x4A, 0x4D)     # #4D — вторая нативная страница (модуль n2, vdac2p_native2_gen.py), с 2026-09-26
# Вторая страница хоста VDAC2+ (Source/ASM/vdac2p_host2.asm, окно #C000 на время вызова из хоста через переходники
# резидента): ранняя подгрузка ячеек и ранняя сборка строк групп — в резиденте и странице хоста места нет.
HOST2_PAGE = 0x4B
# Каталог спрайтов объектами (vdac2p_objects.asm): страница только времени работы — читается с SD при первом объекте;
# в SPG её нет (нулевая), пересечение с частью p2c проверяет rtype_spg.py (object_pages).
OBJ_DIR_PAGE = 0x4C


def boot_state(refresh: bool) -> snapshot.MachineState:
    path = BUILD / 'boot_state.pickle'
    if path.is_file() and not refresh:
        state = pickle.loads(path.read_bytes())
    else:
        state = snapshot.capture(snapshot.new_reference_machine())
        BUILD.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(state))
    return patch_memory(state)


def patch_memory(state: snapshot.MachineState) -> snapshot.MachineState:
    """Диагностические правки образа памяти V30 перед трансляцией: переменная среды RTYPE_V30_PATCH,
    пары «линейный адрес=байт» через запятую в hex (например 025D3=EB — чит бессмертия MAME, он же в
    mame_reference.lua: условный переход в проверке столкновения игрока делается безусловным).
    Вторая известная правка — 1B9DA=BC: у события этапа 1 `ES:$B9D7` (порог progression $06FC,
    команда $6C04) старший байт команды меняется на $BC, и обработчик из таблицы `ES:$B92D` берётся
    по смещению $5E — это `$EEAB`, то есть создание объекта конечных титров. Так титры показываются
    через пару секунд после старта, без прохождения восьми этапов (диагностика глюка титров).
    Каталог Arcade не трогается: правится только копия образа в памяти сборки."""
    patches = os.environ.get('RTYPE_V30_PATCH', '')
    if not patches.strip():
        return state
    memory = bytearray(state.memory)
    for item in patches.split(','):
        if not item.strip():
            continue
        address, value = item.split('=')
        offset, byte = int(address, 16), int(value, 16)
        print(f'правка образа V30: #{offset:05X}: #{memory[offset]:02X} → #{byte:02X}')
        memory[offset] = byte
    state.memory = bytes(memory)
    return state


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8', newline='\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--refresh-state', action='store_true')
    parser.add_argument('--entries', default='', help='дополнительные линейные адреса точек входа через запятую (hex)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    # Таблицы видеоадаптера (video.inc), звук (потоки TSFM — раздел 2 пака, rtype_sound.inc; эффекты
    # General Sound — раздел 3, rtype_gs.inc; порядок обязателен: rtype_gs.py дописывает раздел 3 после
    # раздела 2) и загрузчик пака уровней с SD (rtype_loader.inc, адреса входов) — до ассемблирования
    # страниц хоста и звука. Ячейки пака RTYPELVL.PAC собирает rtype_data.py.
    if not (BUILD / 'rtype_data.json').is_file():
        print('нет Build/V30Z80/rtype_data.json: сначала rtype_data.py (пак уровней RTYPELVL.PAC)')
        return 1
    # Эффекты на простом AY (rtype_ay_sfx.py --pack) кладутся в хвост пака после кольца: сам подбор
    # регистров считается отдельно и надолго, здесь только укладка готового Build/V30Z80/rtype_ay.bin. За ними —
    # картинки спрайтов объектами (vdac2p_objects.py: список Assets/Converted/sprite_objects.json).
    for script, *arguments in (('v30z80_video_assets.py',), ('rtype_sound.py',), ('rtype_gs.py',),
                               ('rtype_ring.py',), ('rtype_ay_sfx.py', '--pack'), ('vdac2p_objects.py',),
                               ('rtype_loader.py',)):
        result = subprocess.run([sys.executable, str(ROOT / 'Source' / 'Tools' / script), *arguments],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            print(result.stdout[-3000:] + result.stderr[-3000:])
            return 1
        print(result.stdout.strip().splitlines()[-1], flush=True)
    state = boot_state(args.refresh_state)
    extra = [int(value, 16) for value in args.entries.split(',') if value]
    program = discover(state.memory, BUILD / 'trace.json', extra + list(IDLE_POINTS), state.pic[0],
                       snapshot.patch_second_bytes(), ROOT / 'Build' / 'Analysis' / 'rtype_world_rom_complete.json')
    # Исполнение начинается в точке простоя с сегментами после загрузки.
    start = next(iter(IDLE_POINTS))
    vectors = vector_targets(state.memory, state.pic[0])
    start_segments = tuple(state.registers[name] for name in snapshot.SEGMENTS)
    function_map = functions.build(program, {start} | set(vectors))
    analysis = segments.Analysis(program, function_map, {start: start_segments})
    analysis.run()
    stack_segment = segments.constant_stack_segment(program, analysis, start_segments)
    if stack_segment is None:
        print('SS после загрузки не доказан постоянным: входы без контекста сохраняют FAULT на стеке')
    seg_values = segments.concrete(program, function_map, analysis, start, start_segments, vectors,
                                   set(IDLE_POINTS), stack_segment)
    write(BUILD / 'segments.json', json.dumps({f'{address:05X}': list(values)
                                               for address, values in sorted(seg_values.items())}) + '\n')
    live_out = flags.liveness(program, set(IDLE_POINTS), function_map, analysis)
    trace = json.loads((BUILD / 'trace.json').read_text(encoding='utf-8'))
    memory_pages = {int(address, 16): {int(page, 16): count for page, count in pages.items()}
                    for address, pages in trace.get('memory_pages', {}).items()}
    instruction_counts = {int(address, 16): item[3] for address, item in trace['instructions'].items()}
    code, page_of = codegen.generate(program, live_out, IDLE_POINTS, CODE_FIRST, CODE_LAST, seg_values,
                                     memory_pages, instruction_counts, function_map)
    code_pages = sorted(set(page_of.values()))
    if code_pages[-1] >= PRISTINE_V30_PAGE0:
        raise SystemExit(f'страницы кода до #{code_pages[-1]:02X} заходят на копии состояния #{PRISTINE_V30_PAGE0:02X}')
    print(f'инструкций {len(program.instructions)}, страниц кода {len(code_pages)} '
          f'(#{code_pages[0]:02X}..#{code_pages[-1]:02X})', flush=True)

    registers = state.registers
    config = [
        '; Сгенерировано v30z80_build.py.',
        f'RES_PAGE EQU #{RES_PAGE:02X}', f'DISPATCH_BASE EQU #{DISPATCH_BASE:02X}',
        f'SPRITE_BUFFER_PAGE EQU #{SPRITE_BUFFER_PAGE:02X}', f'HOST_PAGE EQU #{HOST_PAGE:02X}',
        f'SOUND_PAGE EQU #{SOUND_PAGE:02X}',
        f'PAL_TARGET_PAGE0 EQU #{PAL_TARGET_PAGE0:02X}', f'PAL_TARGET_PAGE1 EQU #{PAL_TARGET_PAGE1:02X}',
        f'SWITCH_PAGE EQU #{SWITCH_PAGE:02X}', f'PRISTINE_RESIDENT EQU #{PRISTINE_RESIDENT:02X}',
        f'PRISTINE_V30_PAGE0 EQU #{PRISTINE_V30_PAGE0:02X}',
        f'V30_PAGE_BASE EQU #{V30_PAGE_BASE:02X}', 'PALETTE_V30_PAGE0 EQU #32', 'SPRITE_V30_PAGE EQU #30',
        f'NATIVE_PAGE0 EQU #{NATIVE_PAGES[0]:02X}', f'NATIVE_PAGE1 EQU #{NATIVE_PAGES[1]:02X}',
        f'HOST2_PAGE EQU #{HOST2_PAGE:02X}',
        f'OBJ_DIR_PAGE EQU #{OBJ_DIR_PAGE:02X}',
    ]
    for name in snapshot.REGISTERS + snapshot.SEGMENTS:
        config.append(f'INIT_{name.upper()} EQU #{registers[name]:04X}')
    video = state.video
    in0, in1, dsw = state.inputs
    raster_raw = (video['raster'] + 128) & 0x1FF
    config += [
        f'INIT_FL EQU #{state.flags:04X}', f'INIT_IP EQU #{state.ip:04X}',
        f'INIT_IN0 EQU #{in0:04X}', f'INIT_IN1 EQU #{in1:04X}', f'INIT_DSW EQU #{dsw:04X}',
        f'INIT_PIC_BASE EQU #{state.pic[0]:02X}', f'INIT_PIC_MASK EQU #{state.pic[1]:02X}',
        f'INIT_PIC_STEP EQU {state.pic[2]}',
        f'INIT_VID_FLIP EQU {4 if video["flip"] else 0}', f'INIT_VID_OFF EQU {8 if video["video_off"] else 0}',
        f'INIT_SCROLL_Y0 EQU #{video["scroll_y"][0]:04X}', f'INIT_SCROLL_X0 EQU #{video["scroll_x"][0]:04X}',
        f'INIT_SCROLL_Y1 EQU #{video["scroll_y"][1]:04X}', f'INIT_SCROLL_X1 EQU #{video["scroll_x"][1]:04X}',
        f'INIT_RASTER_RAW EQU #{raster_raw:04X}', f'INIT_DMA EQU {video["dma"]}',
    ]
    write(BUILD / 'config.inc', '\n'.join(config) + '\n')
    parity = [f'\tDB #{0x04 if bin(value).count("1") % 2 == 0 else 0x00:02X}' for value in range(256)]
    write(BUILD / 'parity.inc', '\n'.join(parity) + '\n')
    write(BUILD / 'code.asm', code)
    pages_dir = BUILD / 'pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    saves = [f'\tSAVEDEV "pages/page_{page:02x}.bin",{page},0,16384'
             for page in [RES_PAGE, HOST_PAGE, SOUND_PAGE] + code_pages + list(NATIVE_PAGES) + [HOST2_PAGE]]
    top = ['\tDEVICE ZXSPECTRUM4096', '\tINCLUDE "config.inc"', f'\tMMU #0000,{RES_PAGE}',
           '\tINCLUDE "v30z80_runtime.asm"', '\tINCLUDE "code.asm"', f'\tMMU #C000,{HOST_PAGE}',
           '\tINCLUDE "v30z80_host.asm"', f'\tMMU #C000,{SOUND_PAGE}', '\tINCLUDE "v30z80_sound.asm"',
           # Нативная страница — с адреса #C000 (MMU со сменой адреса): до 2026-09-25 её код продолжал адрес за кодом
           # звука (#D164), и 4,4 КБ страницы пустовали.
           f'\tMMU #C000,{NATIVE_PAGES[0]},#C000', '\tINCLUDE "vdac2p_native.asm"',
           # Вторая нативная страница: модуль n2 — свой код и копии нужных блоков первой (vdac2p_native2_gen.py).
           f'\tMMU #C000,{NATIVE_PAGES[1]},#C000', '\tINCLUDE "vdac2p_native2.inc"',
           f'\tMMU #C000,{HOST2_PAGE}', '\tINCLUDE "vdac2p_host2.asm"'] + saves
    write(BUILD / 'program.asm', '\n'.join(top) + '\n')
    generated = subprocess.run([sys.executable, str(ROOT / 'Source' / 'Tools' / 'vdac2p_native2_gen.py'),
                                str(BUILD / 'vdac2p_native2.inc')], capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
    print(generated.stdout.strip(), flush=True)
    if generated.returncode:
        print(generated.stderr[-3000:])
        return 1
    # Диагностические ветки (ifdef) включаются переменной среды RTYPE_ASM_DEFINES: имена через запятую,
    # например RTYPE_INVINCIBLE. В обычной сборке переменной нет и ни одна ветка не собирается.
    defines = [f'-D{name.strip()}' for name in os.environ.get('RTYPE_ASM_DEFINES', '').split(',') if name.strip()]
    result = subprocess.run([str(SJASMPLUS), '--nologo', '--msg=war', '-Wno-rdlow', f'-i{ASM}', f'-i{BUILD}'] + defines +
                            [f'--sym={BUILD / "program.sym"}', f'--lst={BUILD / "program.lst"}', 'program.asm'],
                            cwd=BUILD, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout[-6000:] + result.stderr[-3000:])
        return 1
    # Страницы памяти V30, зеркала палитры и буфер спрайтов — из состояния после загрузки.
    for page in range(64):
        (pages_dir / f'page_{V30_PAGE_BASE + page:02x}.bin').write_bytes(state.memory[page << 14:(page + 1) << 14])
    sprites = bytearray(0x4000)
    sprites[0:len(state.sprite_buffer)] = state.sprite_buffer
    (pages_dir / f'page_{SPRITE_BUFFER_PAGE:02x}.bin').write_bytes(bytes(sprites))
    # Цели палитр для ядра менеджера палитр: 256 типов по 48 байт из ROM (у группы 1 — со смещения $2400).
    for page, base in ((PAL_TARGET_PAGE0, 0x3B000), (PAL_TARGET_PAGE1, 0x3B000 + 0x2400)):
        table = bytearray(0x4000)
        table[0:256 * 48] = state.memory[base:base + 256 * 48]
        (pages_dir / f'page_{page:02x}.bin').write_bytes(bytes(table))
    symbols = {}
    for line in (BUILD / 'program.sym').read_text(encoding='latin1').splitlines():
        match = re.match(r'^([A-Za-z_][\w.]*):\s+EQU\s+0x([0-9A-Fa-f]+)', line)
        if match:
            symbols[match[1]] = int(match[2], 16)
    dispatch_entries = program.entries | program.call_targets
    for index, data in enumerate(codegen.dispatch_pages(page_of, dispatch_entries, symbols, program, NATIVE_PAGES[0],
                                                        HOST2_PAGE, NATIVE_PAGES[1])):
        (pages_dir / f'page_{DISPATCH_BASE + index:02x}.bin').write_bytes(data)
    # Начальный кэш диспетчеризации: для каждого младшего байта IP — два самых частых по трассе
    # входа с этим байтом (первый и второй путь); без входов — останов MISS.
    trace_counts = json.loads((BUILD / 'trace.json').read_text(encoding='utf-8'))['instructions']
    resident = bytearray((pages_dir / f'page_{RES_PAGE:02x}.bin').read_bytes())
    ranked: dict[int, list[tuple[int, int]]] = {}
    for address in dispatch_entries:
        if address not in page_of:
            continue
        ip = (address - codegen.CODE_BASE) & 0xFFFF
        count = trace_counts.get(f'{address:05X}', [0, 0, 0, 0])[3]
        ranked.setdefault(ip & 0xFF, []).append((-count, address))
    for way, base in enumerate((symbols['RC_IPH'], symbols['RC2_IPH'])):
        for low in range(256):
            candidates = sorted(ranked.get(low, []))
            if len(candidates) > way:
                address = candidates[way][1]
                ip = (address - codegen.CODE_BASE) & 0xFFFF
                page, target = codegen.dispatch_target(program, address, page_of, symbols, NATIVE_PAGES[0], HOST2_PAGE,
                                                       NATIVE_PAGES[1])
            elif candidates:
                address = candidates[0][1]
                ip = (address - codegen.CODE_BASE) & 0xFFFF
                page, target = codegen.dispatch_target(program, address, page_of, symbols, NATIVE_PAGES[0], HOST2_PAGE,
                                                       NATIVE_PAGES[1])
            else:
                ip, target, page = 0, symbols['MISS'], code_pages[0]
            resident[base + low] = ip >> 8
            resident[base + 256 + low] = page
            resident[base + 512 + low] = target & 0xFF
            resident[base + 768 + low] = target >> 8
    (pages_dir / f'page_{RES_PAGE:02x}.bin').write_bytes(bytes(resident))
    # Копии состояния после загрузки для новой машины (ApiReboot).
    (pages_dir / f'page_{PRISTINE_RESIDENT:02x}.bin').write_bytes(bytes(resident))
    for index, page in enumerate(PRISTINE_V30_PAGES):
        (pages_dir / f'page_{PRISTINE_V30_PAGE0 + index:02x}.bin').write_bytes(state.memory[page << 14:(page + 1) << 14])
    (pages_dir / f'page_{PRISTINE_V30_PAGE0 + len(PRISTINE_V30_PAGES):02x}.bin').write_bytes(bytes(sprites))
    report = {
        'res_page': RES_PAGE, 'dispatch_base': DISPATCH_BASE,
        'sprite_buffer_page': SPRITE_BUFFER_PAGE, 'v30_page_base': V30_PAGE_BASE,
        'sound_pages': [SOUND_PAGE + index for index in range(1 + SOUND_TRACK_PAGES)],
        'kernel_pages': list(KERNEL_PAGES), 'native_pages': list(NATIVE_PAGES), 'host2_pages': [HOST2_PAGE],
        'object_pages': [OBJ_DIR_PAGE],
        'code_pages': code_pages, 'first_code_page': code_pages[0], 'instructions': len(program.instructions),
        'symbols': symbols, 'page_of': {f'{address:05X}': page for address, page in page_of.items()},
    }
    write(BUILD / 'build_report.json', json.dumps(report, ensure_ascii=False, indent=0) + '\n')
    print(f'сборка: резидент до #{symbols.get("STACK_TOP", 0):04X}, хост до #{symbols.get("HOST_END", 0):04X}, '
          f'звук до #{symbols.get("SOUND_END", 0):04X}, {time.perf_counter() - started:.0f} с')
    # Страницы видеоадаптера (состояние, потоки, тени, пары и карты слотов) — v30z80_video_assets.py;
    # драйвер FAT32 и загрузчик пака уровней — rtype_loader.py.
    video_pages = json.loads((BUILD / 'video_catalog.json').read_text(encoding='utf-8'))['pages']
    loader_pages = json.loads((BUILD / 'rtype_loader.json').read_text(encoding='utf-8'))['pages']
    return build_spg(symbols, [RES_PAGE, HOST_PAGE, SPRITE_BUFFER_PAGE] + code_pages +
                     [DISPATCH_BASE + index for index in range(16)] + [V30_PAGE_BASE + page for page in range(64)] +
                     video_pages + loader_pages + list(KERNEL_PAGES) + list(NATIVE_PAGES) + [HOST2_PAGE])


def build_spg(symbols: dict[str, int], pages: list[int]) -> int:
    """SPG `rtype_vdac2.spg` в Build/V30Z80: загрузчик v30z80_boot.asm (страница BOOT_PAGE) и
    страницы программы; нулевые страницы в SPG не входят — их обнуляет загрузчик."""
    contents = {page: (BUILD / 'pages' / f'page_{page:02x}.bin').read_bytes() for page in pages}
    zero_pages = sorted(page for page, data in contents.items() if not any(data))
    lines = ['; Сгенерировано v30z80_build.py: страницы и вход резидента для загрузчика SPG.',
             f'V30Z80_RES_PAGE EQU #{RES_PAGE:02X}', f'V30Z80_START EQU #{symbols["Start"]:04X}',
             f'V30Z80_HOST_PRESENT EQU #{symbols["HOST_PRESENT"]:04X}',
             '                MACRO V30Z80_ZERO_PAGE_LIST']
    lines += [f'                DB {", ".join(f"#{page:02X}" for page in zero_pages[start:start + 16])}'
              for start in range(0, len(zero_pages), 16)]
    lines += ['                DB 0', '                ENDM', '']
    write(BUILD / 'boot.inc', '\n'.join(lines))
    result = subprocess.run([str(SJASMPLUS), '--nologo', '--msg=war', str(ASM / 'v30z80_boot.asm'), '--syntax=ab',
                             f'--lst={BUILD / "boot.lst"}', f'--sym={BUILD / "boot.sym"}'],
                            cwd=ASM, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout[-6000:] + result.stderr[-3000:])
        return 1
    blocks = [f'Block = #5000, #{BOOT_PAGE:02X}, {(BUILD / "boot.bin").relative_to(ROOT).as_posix()}']
    blocks += [f'Block = #0000, #{page:02X}, {(BUILD / "pages" / f"page_{page:02x}.bin").relative_to(ROOT).as_posix()}'
               for page in pages if page not in zero_pages]
    ini = ['Desc = R-Type World ROM (V30 -> Z80)', 'Start = 0x5000', 'Stack = 0x3FFF', 'Resident = 0x4F00',
           'Page3 = 0', 'Clock = 2', 'INT = 0', 'Pager = 0', 'Compression = 0', ''] + blocks
    write(BUILD / 'spg.ini', '\n'.join(ini) + '\n')
    result = subprocess.run([str(SPGBLD), '-b', str(BUILD / 'spg.ini'), str(BUILD / 'rtype_vdac2.spg')], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        print(result.stdout[-3000:] + result.stderr[-3000:])
        return 1
    spg = (BUILD / 'rtype_vdac2.spg').read_bytes()
    print(f'SPG: {BUILD / "rtype_vdac2.spg"} {len(spg)} байт, блоков {len(blocks)}, нулевых страниц '
          f'{len(zero_pages)}, SHA-256 {hashlib.sha256(spg).hexdigest()[:16]}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
