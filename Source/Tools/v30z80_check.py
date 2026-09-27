"""Покадровая сверка переведённой программы (Z80, модель TS-Config) с эталонной машиной M72 (unicorn).

После каждого кадра сравниваются: память V30 (1 МБ), регистры и FLAGS, IP точки простоя,
PIC, регистры видео, команды звука кадра, канонические палитры и буфер спрайтов. Ввод —
воспроизводимый: простой, затем coin/start и случайные нажатия. Первое расхождение
печатается с адресом.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))

import v30z80  # noqa: E402,F401
from v30z80 import snapshot  # noqa: E402
from p2c_z80_check import TSConfModel  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
REGISTER_NAMES = ('ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di', 'es', 'cs', 'ss', 'ds')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=300)
    parser.add_argument('--coin-frame', type=int, default=120)
    parser.add_argument('--seed', type=int, default=3)
    parser.add_argument('--budget', type=int, default=200_000_000, help='тактов Z80 на кадр до отказа')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--profile', type=int, default=0, help='шаг выборки PC в тактах (0 — без профиля)')
    parser.add_argument('--profile-from', type=int, default=0, help='первый кадр профиля')
    parser.add_argument('--samples', default='', help='файл сырых отсчётов профиля: окно W3, PC, такты')
    parser.add_argument('--ticks', default='', help='файл JSON: такты Z80 каждого кадра по порядку')
    parser.add_argument('--measure', default='', help='окно кадров замера тактов «первый:последний» '
                                                     '(по умолчанию — после старта игры)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    report = json.loads((BUILD / 'build_report.json').read_text(encoding='utf-8'))
    symbols = report['symbols']
    pages = {int(path.stem.split('_')[1], 16): path.read_bytes() for path in (BUILD / 'pages').glob('page_*.bin')}
    model = TSConfModel(pages, set(pages), 0)
    model.map_all([report['res_page'], report['v30_page_base'], report['v30_page_base'], report['first_code_page']])
    cpu = model.cpu
    cpu.pc = symbols['Start']
    cpu.sp = 0x3FFE
    hooks = {symbols[name]: name for name in ('INPUT_HOOK', 'FRAME_HOOK', 'MISS_HOOK', 'FAULT_HOOK')}
    for address in hooks:
        cpu.set_breakpoint(address)

    from unicorn import x86_const as X
    machine = snapshot.new_reference_machine()
    ureg = {'ax': X.UC_X86_REG_AX, 'cx': X.UC_X86_REG_CX, 'dx': X.UC_X86_REG_DX, 'bx': X.UC_X86_REG_BX,
            'sp': X.UC_X86_REG_SP, 'bp': X.UC_X86_REG_BP, 'si': X.UC_X86_REG_SI, 'di': X.UC_X86_REG_DI,
            'es': X.UC_X86_REG_ES, 'cs': X.UC_X86_REG_CS, 'ss': X.UC_X86_REG_SS, 'ds': X.UC_X86_REG_DS}

    def word(address: int) -> int:
        return model.memory[address] | (model.memory[address + 1] << 8)

    def step_over() -> None:
        pc = cpu.pc
        cpu.clear_breakpoint(pc)
        cpu.ticks_to_stop = 1
        cpu.run()
        cpu.set_breakpoint(pc)

    # Профиль: переведённая инструкция V30 (метка страницы кода) или процедура резидента.
    code_labels: dict[int, list[tuple[int, int]]] = {}
    for key, page in report['page_of'].items():
        code_labels.setdefault(page, []).append((symbols[f'A_{key}'], int(key, 16)))
    for entries in code_labels.values():
        entries.sort()
    skip = ('INIT_', 'PORT_', 'A_')
    constants = {'RES_PAGE', 'DISPATCH_BASE', 'SPRITE_BUFFER_PAGE', 'V30_PAGE_BASE',
                 'PALETTE_V30_PAGE0', 'SPRITE_V30_PAGE', 'STACK_TOP'}
    resident = sorted((value, name) for name, value in symbols.items()
                      if value < 0x4000 and '.' not in name and not name.startswith(skip) and name not in constants)
    exclusive: dict[str, int] = {}
    inclusive: dict[int, int] = {}
    profiling = [False]

    def v30_at(pc: int) -> int | None:
        entries = code_labels.get(model.windows[3], [])
        index = bisect.bisect_right(entries, (pc, 0xFFFFF)) - 1
        return entries[index][1] if index >= 0 else None

    raw_samples: dict[tuple[int, int], int] = {}

    def sample(used: int) -> None:
        pc = cpu.pc
        key = (model.windows[3] if pc >= 0xC000 else -1, pc)
        raw_samples[key] = raw_samples.get(key, 0) + used
        if pc >= 0xC000:
            v30 = v30_at(pc)
            exclusive[f'{v30:05X}' if v30 is not None else f'#{pc:04X}'] = exclusive.get(
                f'{v30:05X}' if v30 is not None else f'#{pc:04X}', 0) + used
        else:
            index = bisect.bisect_right(resident, (pc, '￿')) - 1
            name = resident[index][1] if index >= 0 else f'#{pc:04X}'
            exclusive[name] = exclusive.get(name, 0) + used
            # Вызвавшая инструкция V30 — первый адрес возврата в страницу кода на стеке Z80.
            v30 = None
            for sp in range(cpu.sp, 0x3FFE, 2):
                address = model.memory[sp] | (model.memory[sp + 1] << 8)
                if address >= 0xC000:
                    v30 = v30_at(address)
                    break
        if pc >= 0xC000 or v30 is not None:
            inclusive[v30] = inclusive.get(v30, 0) + used

    def run_to(wanted: str) -> int:
        spent = 0
        while True:
            # Ядро не останавливается на метке текущего PC при возобновлении: шаг через одну
            # точку (FRAME_HOOK: jp FrameLoop) может закончиться прямо на следующей.
            if hooks.get(cpu.pc) == wanted:
                return spent
            step = args.profile if profiling[0] else args.budget
            cpu.ticks_to_stop = step
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            spent += step - remaining
            if profiling[0]:
                sample(step - remaining)
            name = hooks.get(cpu.pc)
            if name == wanted:
                return spent
            if name in ('MISS_HOOK', 'FAULT_HOOK'):
                ip = word(symbols['MISS_IP'])
                raise SystemExit(f'{name}: IP V30 #{ip:04X} (линейный #{0x400 + ip:05X})')
            if args.verbose:
                print(f'  остановка: {name} PC #{cpu.pc:04X} тактов {spent}', flush=True)
            if name is not None:
                step_over()
                continue
            if spent >= args.budget and not profiling[0] or spent >= args.budget * 4:
                raise SystemExit(f'больше {args.budget} тактов без точки кадра, PC #{cpu.pc:04X}')

    from v30z80.scenario import Scenario
    scenario = Scenario(args.seed, args.coin_frame)
    run_to('INPUT_HOOK')
    # Пометки изменений VRAM и палитр (для адаптера FT812): у каждого тайла и пера, изменённых
    # (палитры — пометка всей палитры или бит пера ядра переноса)
    # эталоном за кадр, бит обязан стоять; после сверки пометки снимаются, как это делает адаптер.
    video_previous = {page: bytes(machine.memory(slice(page << 14, (page + 1) << 14)))
                      for page in (0x34, 0x36)}
    palette_previous = [bytes(machine.palette_ram[bank]) for bank in range(2)]
    dirty_tables = {0x34: symbols['VRAM_DIRTY0'], 0x36: symbols['VRAM_DIRTY1']}
    palette_tables = (symbols['PAL_DIRTY0'], symbols['PAL_DIRTY1'])
    pen_tables = (symbols['PEN_DIRTY0'], symbols['PEN_DIRTY1'])   # ядро переноса палитр: бит пера на палитру

    def check_video_marks() -> list[str]:
        missing = []
        for page, table in dirty_tables.items():
            current = bytes(machine.memory(slice(page << 14, (page + 1) << 14)))
            old = video_previous[page]
            if current != old:
                for tile in range(4096):
                    if current[tile * 4:tile * 4 + 4] != old[tile * 4:tile * 4 + 4]:
                        if not model.memory[table + (tile >> 3)] or not model.memory[table + 512 + (tile >> 6)]:
                            missing.append(f'нет пометки тайла #{tile:03X} страницы #{page:02X}')
                            break
            video_previous[page] = current
        for page, table in dirty_tables.items():
            model.memory[table:table + 576] = bytes(576)
        for bank in range(2):
            current = bytes(machine.palette_ram[bank])
            old = palette_previous[bank]
            if current != old:
                for word_index in range(0x600):
                    if current[word_index * 2:word_index * 2 + 2] != old[word_index * 2:word_index * 2 + 2]:
                        palette = (word_index & 0xFF) >> 4
                        pen = word_index & 15
                        pens = model.memory[pen_tables[bank] + palette * 2] | (model.memory[pen_tables[bank] + palette * 2 + 1] << 8)
                        if not model.memory[palette_tables[bank] + palette] and not pens >> pen & 1:
                            missing.append(f'нет пометки палитры {palette} (пера {pen}) банка {bank}')
                            break
            palette_previous[bank] = current
            model.memory[palette_tables[bank]:palette_tables[bank] + 16] = bytes(16)
            model.memory[pen_tables[bank]:pen_tables[bank] + 32] = bytes(32)
        return missing
    started = time.perf_counter()
    frame_ticks = []
    for frame in range(args.frames):
        profiling[0] = bool(args.profile) and frame >= args.profile_from
        mask, start, coin = scenario.inputs(frame)
        scenario.apply(machine, mask, start, coin)
        for name, value in (('IN0', machine.inputs.in0), ('IN1', machine.inputs.in1)):
            model.memory[symbols[name]] = value & 0xFF
            model.memory[symbols[name] + 1] = (value >> 8) & 0xFF
        # Шаг Z80: от INPUT_HOOK до FRAME_HOOK, затем до следующего INPUT_HOOK.
        step_over()
        ticks = run_to('FRAME_HOOK')
        step_over()
        run_to('INPUT_HOOK')
        frame_ticks.append(ticks)
        latch_before = len(machine.sound_latch)
        machine.step_frame()
        # IN1 эталона меняется портом 4 (бит 7): Z80 хранит своё значение.
        problems = []
        stack_pointer = machine.cpu.reg_read(ureg['sp']) & 0xFFFF
        for page in range(64):
            ours = bytearray(model.page_bytes(report['v30_page_base'] + page))
            theirs = bytearray(machine.memory(slice(page << 14, (page + 1) << 14)))
            snapshot.restore_board_bytes(machine, theirs, page << 14)
            snapshot.mask_stack_garbage(ours, theirs, page << 14, stack_pointer)
            if ours != theirs:
                index = next(i for i in range(0x4000) if ours[i] != theirs[i])
                count = sum(1 for i in range(0x4000) if ours[i] != theirs[i])
                problems.append(f'память #{(page << 14) + index:05X}: Z80 #{ours[index]:02X} эталон '
                                f'#{theirs[index]:02X} (в странице отличий {count})')
                break
        for index, name in enumerate(REGISTER_NAMES):
            ours = word(symbols['V_REG'] + index * 2)
            theirs = machine.cpu.reg_read(ureg[name]) & 0xFFFF
            if ours != theirs:
                problems.append(f'{name.upper()}: Z80 #{ours:04X} эталон #{theirs:04X}')
        ours = word(symbols['V_FL'])
        theirs = machine.cpu.reg_read(X.UC_X86_REG_EFLAGS) & 0xFFFF
        if ours != theirs:
            problems.append(f'FLAGS: Z80 #{ours:04X} эталон #{theirs:04X}')
        ours = word(symbols['V_IP'])
        theirs = machine.cpu.reg_read(X.UC_X86_REG_IP) & 0xFFFF
        if ours != theirs:
            problems.append(f'IP: Z80 #{ours:04X} эталон #{theirs:04X}')
        sounds = list(model.memory[symbols['SOUND_QUEUE']:symbols['SOUND_QUEUE'] + model.memory[symbols['SOUND_COUNT']]])
        if sounds != machine.sound_latch[latch_before:]:
            problems.append(f'звук: Z80 {sounds} эталон {machine.sound_latch[latch_before:]}')
        pic = (model.memory[symbols['PIC_BASE']], model.memory[symbols['PIC_MASK']], model.memory[symbols['PIC_STEP']])
        if pic != (machine.pic.vector_base, machine.pic.mask, machine.pic._icw_step):
            problems.append(f'PIC: Z80 {pic} эталон {(machine.pic.vector_base, machine.pic.mask, machine.pic._icw_step)}')
        scroll = [word(symbols['SCROLL_Y0']), word(symbols['SCROLL_X0']), word(symbols['SCROLL_Y1']),
                  word(symbols['SCROLL_X1'])]
        video = machine.video
        if scroll != [video.scroll_y[0], video.scroll_x[0], video.scroll_y[1], video.scroll_x[1]]:
            problems.append(f'скроллы: Z80 {scroll} эталон {[video.scroll_y[0], video.scroll_x[0], video.scroll_y[1], video.scroll_x[1]]}')
        raster = word(symbols['RASTER_RAW']) - 128
        if raster != video.raster_irq_position:
            problems.append(f'растр: Z80 {raster} эталон {video.raster_irq_position}')
        problems += check_video_marks()
        # Канонические палитры эталона равны памяти палитры (#C8000, #CC000): ROM не пишет в
        # зеркальные адреса; расхождение означало бы такую запись.
        for bank, page in ((0, 0x32), (1, 0x33)):
            if model.page_bytes(report['v30_page_base'] + page)[0:0xC00] != bytes(machine.palette_ram[bank]):
                problems.append(f'каноническая палитра {bank} не равна памяти палитры')
        sprites = model.page_bytes(report['sprite_buffer_page'])[0:0x400]
        if sprites != bytes(machine.buffered_sprite_ram):
            problems.append('буфер спрайтов расходится')
        if problems:
            print(f'кадр {frame}: ' + '; '.join(problems))
            return 1
        if frame % 20 == 0:
            rate = (frame + 1) / (time.perf_counter() - started)
            print(f'кадр {frame}: совпадает, тактов Z80 {ticks}, {rate:.1f} к/с', flush=True)
    if args.samples:
        Path(args.samples).write_text(json.dumps([[page, pc, ticks] for (page, pc), ticks in raw_samples.items()]),
                                      encoding='utf-8')
    if args.profile:
        total = sum(exclusive.values()) or 1
        print('исключительно (инструкция V30 / процедура резидента):')
        for name, ticks in sorted(exclusive.items(), key=lambda item: -item[1])[:40]:
            print(f'  {name:>20} {100 * ticks / total:5.1f}%')
        print('включительно по инструкциям V30 (с процедурами резидента):')
        instructions = json.loads((BUILD / 'trace.json').read_text(encoding='utf-8'))['instructions']
        for address, ticks in sorted(inclusive.items(), key=lambda item: -item[1])[:60]:
            info = instructions.get(f'{address:05X}') if address is not None else None
            text = f'{info[1]} {info[2]}' if info else ''
            print(f'  {address if address is None else format(address, "05X")} {100 * ticks / total:5.1f}% {text}')
        # По формам инструкций (мнемоника и вид операндов) включительно.
        import re as regex
        forms: dict[str, int] = {}
        for address, ticks in inclusive.items():
            info = instructions.get(f'{address:05X}') if address is not None else None
            if info is None:
                form = '?'
            else:
                operands = regex.sub(r'0x[0-9a-f]+', 'imm', info[2])
                operands = regex.sub(r'(byte|word) ptr (\w\w:)?\[[^\]]*\]', r' mem', operands)
                form = f'{info[1]} {operands}'
            forms[form] = forms.get(form, 0) + ticks
        print('по формам:')
        for form, ticks in sorted(forms.items(), key=lambda item: -item[1])[:40]:
            print(f'  {100 * ticks / total:5.1f}% {form}')
    if args.ticks:
        Path(args.ticks).write_text(json.dumps(frame_ticks), encoding='utf-8')
    if args.measure:
        first, last = (int(value) for value in args.measure.split(':'))
        game_ticks = sorted(frame_ticks[first:last])
    else:
        game_ticks = sorted(frame_ticks[args.coin_frame + 60:])
    frame_ticks.sort()
    summary = {'result': 'identical', 'frames': args.frames, 'ticks_median': frame_ticks[len(frame_ticks) // 2],
               'ticks_max': frame_ticks[-1]}
    if game_ticks:
        summary.update({'game_median': game_ticks[len(game_ticks) // 2],
                        'game_p90': game_ticks[len(game_ticks) * 9 // 10]})
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
