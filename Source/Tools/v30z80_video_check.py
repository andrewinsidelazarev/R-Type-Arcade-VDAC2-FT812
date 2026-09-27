"""Проверка видеоадаптера FT812 переведённой программы World ROM на модели.

Z80 (модель TS-Config) исполняет SPG-раскладку с хуками платформы (HOST_PRESENT = 1) и
моделью VDAC2 (v30z80_ft812.py); эталонная машина M72 (unicorn) идёт покадрово тем же
вводом. Display list, переключённый после шага s, должен изображать FrameState шага s:
картинка модели FT812 (1024×768) сравнивается с M72HqRenderer (640×480, растянутым как
аппаратный масштаб 8/5). Печатаются такты хуков, слова display list, счётчики адаптера,
ошибки модели FT812 и доля заметно отличных пикселей; --png сохраняет пары кадров.
Ячейки графики адаптер читает с модели SD-карты (образ --sd с паком RTYPELVL.PAC; модель
Card и Z-Controller проекта драйвера FAT32, записи в образ не сохраняются).
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
sys.path.insert(0, str(ROOT / 'Source' / 'Python'))

import v30z80  # noqa: E402,F401
from v30z80 import snapshot  # noqa: E402
from p2c_z80_check import TSConfModel  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=300)
    parser.add_argument('--build', type=Path, default=BUILD, help='каталог проверяемой сборки (можно изолированную копию)')
    parser.add_argument('--profile', type=int, default=0, help='шаг выборки PC в тактах; 0 — без профиля')
    parser.add_argument('--profile-from', type=int, default=0, help='первый кадр профиля')
    parser.add_argument('--ticks', default='', help='JSON с тактами фаз каждого кадра и профилем')
    parser.add_argument('--coin-frame', type=int, default=120)
    parser.add_argument('--seed', type=int, default=3)
    parser.add_argument('--render-every', type=int, default=25, help='сравнивать картинку каждые N кадров')
    parser.add_argument('--render-from', type=int, default=0)
    parser.add_argument('--png', default='', help='каталог для PNG пар кадров (модель | эталон)')
    parser.add_argument('--budget', type=int, default=400_000_000)
    parser.add_argument('--dl-record', default='', help='файл JSON: хеши display list каждого кадра')
    parser.add_argument('--dl-dump', default='', help='каталог: сохранить слова показанного display list кадров --dl-dump-frames')
    parser.add_argument('--dl-dump-frames', default='', help='кадры выгрузки display list через запятую')
    parser.add_argument('--dl-compare', default='', help='сверить хеши display list с записанными')
    parser.add_argument('--sd', default=str(BUILD / 'rtype_sd.img'), help='образ SD-карты с паком уровней')
    parser.add_argument('--corner', action='store_true',
                        help='выборка текстуры по углу пикселя (как эмулятор FT812 в Unreal)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    import numpy as np
    from v30z80_ft812 import Ft812Model
    from rtype_loader_check import sd_controller

    report = json.loads((args.build / 'build_report.json').read_text(encoding='utf-8'))
    symbols = report['symbols']
    pages = {int(path.stem.split('_')[1], 16): path.read_bytes() for path in (args.build / 'pages').glob('page_*.bin')}
    model = TSConfModel(pages, set(pages), 0)
    model.map_all([report['res_page'], report['v30_page_base'] + 0x10, 0, report['first_code_page']])
    sd, card = sd_controller(Path(args.sd))
    ft = Ft812Model(model, sd, corner=args.corner)
    cpu = model.cpu
    cpu.pc = symbols['Start']
    cpu.sp = 0x3FFE
    model.memory[symbols['HOST_PRESENT']] = 1
    hooks = {symbols[name]: name for name in ('INPUT_HOOK', 'FRAME_HOOK', 'MISS_HOOK', 'FAULT_HOOK', 'FrameLoop')}
    for address in hooks:
        cpu.set_breakpoint(address)

    # Только метки процедур из исходников, без EQU портов/констант, совпадающих с адресами кода.
    profile_labels = {}
    for filename, page in (('v30z80_runtime.asm', -1), ('v30z80_flags.inc', -1), ('v30z80_kernels.asm', -1), ('v30z80_ring.asm', -1),
                           ('v30z80_host.asm', 0x0C), ('v30z80_sound.asm', 0x5E)):
        source = (ROOT / 'Source' / 'ASM' / filename).read_text(encoding='utf-8')
        names = re.findall(r'^([A-Za-z_][\w]*):', source, flags=re.MULTILINE)
        profile_labels.setdefault(page, []).extend((symbols[name], name) for name in names if name in symbols)
    for labels in profile_labels.values():
        labels.sort()
    profile = {}
    profiling = False

    def sample(ticks: int) -> None:
        page = model.windows[3] if cpu.pc >= 0xC000 else -1
        labels = profile_labels.get(page, [])
        index = bisect.bisect_right(labels, (cpu.pc, '\uffff')) - 1
        name = labels[index][1] if index >= 0 else f'page_{page:02X}'
        profile[name] = profile.get(name, 0) + ticks

    def word(address: int) -> int:
        return model.memory[address] | (model.memory[address + 1] << 8)

    def host_word(name: str) -> int:
        address = symbols[name]
        return model.page_bytes(0x0C)[address - 0xC000] | (model.page_bytes(0x0C)[address - 0xC000 + 1] << 8)

    def step_over() -> None:
        pc = cpu.pc
        cpu.clear_breakpoint(pc)
        cpu.ticks_to_stop = 1
        cpu.run()
        cpu.set_breakpoint(pc)

    def run_to(wanted: str) -> int:
        spent = 0
        while True:
            if hooks.get(cpu.pc) == wanted:
                return spent
            quantum = min(args.profile, args.budget - spent) if profiling else args.budget - spent
            cpu.ticks_to_stop = quantum
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            used = quantum - remaining
            spent += used
            if profiling:
                sample(used)
            name = hooks.get(cpu.pc)
            if name == wanted:
                return spent
            if name in ('MISS_HOOK', 'FAULT_HOOK'):
                raise SystemExit(f'{name}: IP V30 #{word(symbols["MISS_IP"]):04X}')
            if name is not None:
                step_over()
                continue
            if spent >= args.budget:
                raise SystemExit(f'больше {args.budget} тактов без точки кадра, PC #{cpu.pc:04X} окна {model.windows}')

    from rtype_m72.hq_renderer import M72HqRenderer
    from v30z80.scenario import Scenario
    renderer = M72HqRenderer()
    machine = snapshot.new_reference_machine()
    scenario = Scenario(args.seed, args.coin_frame)
    png_dir = Path(args.png) if args.png else None
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)
    rows = np.arange(768) * 5 // 8
    columns = np.arange(1024) * 5 // 8
    run_to('FrameLoop')
    before_ticks = run_to('INPUT_HOOK')
    started = time.perf_counter()
    stats = []
    dump_dir = Path(args.dl_dump) if args.dl_dump else None
    dump_frames = {int(v) for v in args.dl_dump_frames.split(',') if v.strip()} if dump_dir else set()
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
    dl_hashes: list[str] = []
    expected_hashes = json.loads(Path(args.dl_compare).read_text(encoding='utf-8')) if args.dl_compare else None
    for frame in range(args.frames):
        profiling = bool(args.profile) and frame >= args.profile_from
        mask, start, coin = scenario.inputs(frame)
        scenario.apply(machine, mask, start, coin)
        for name, value in (('IN0', machine.inputs.in0), ('IN1', machine.inputs.in1)):
            model.memory[symbols[name]] = value & 0xFF
            model.memory[symbols[name] + 1] = (value >> 8) & 0xFF
        step_over()
        frame_ticks = run_to('FRAME_HOOK')
        state = machine.step_frame()
        step_over()
        swaps = ft.swaps
        dma_before = ft.dma_ops
        after_ticks = run_to('FrameLoop')
        next_before = run_to('INPUT_HOOK')
        if ft.swaps != swaps + 1:
            print(f'кадр {frame}: display list не переключён ({ft.swaps - swaps})')
            return 1
        words = len(ft.words())
        if frame in dump_frames:
            # Сырые слова показанного списка: их разбирает ft812_line_cost.py (цена строки развёртки).
            (dump_dir / f'frame_{frame:05d}.dl').write_bytes(ft.shown_dl[:words * 4])
        line = {'frame': frame, 'before': before_ticks, 'v30': frame_ticks, 'after': after_ticks, 'words': words,
                'bursts': ft.dma_ops - dma_before}
        # Хеш показанного списка и RAM_G: переделка адаптера без изменения вывода их не меняет.
        digest = hashlib.sha1(ft.shown_dl[:words * 4] + bytes(ft.ram_g)).hexdigest()
        dl_hashes.append(digest)
        if expected_hashes is not None and frame < len(expected_hashes) and expected_hashes[frame] != digest:
            print(f'кадр {frame}: display list или RAM_G отличаются от записанных')
            return 1
        before_ticks = next_before
        if ft.errors:
            print(f'кадр {frame}: ошибки FT812: {ft.errors[:5]}')
            return 1
        if frame >= args.render_from and (frame - args.render_from) % args.render_every == 0:
            image, parse = ft.render()
            expected = renderer.render(state)
            reference = np.asarray(expected.convert('RGB'))[rows][:, columns]
            difference = np.abs(image.astype(np.int16) - reference.astype(np.int16)).max(axis=2)
            line['diff'] = round(float((difference > 48).mean()) * 100, 3)
            line['mean'] = round(float(difference.mean()), 2)
            line['unknown'] = parse['unknown']
            if png_dir:
                from PIL import Image
                pair = np.concatenate([image, reference], axis=1)
                Image.fromarray(pair).save(png_dir / f'frame_{frame:05d}.png')
            line['missing'] = host_word('VIDEO_MISSING')
            line['dropped'] = host_word('VIDEO_DROPPED')
            line['overflow'] = host_word('VIDEO_OVERFLOW')
            line['uploads'] = host_word('VIDEO_UPLOADS')
            line['faults'] = host_word('VIDEO_FAULTS')
            # зеркальные слова матрицы (A или E = −160): вывод отражённых ячеек
            line['mirrors'] = sum(1 for value in ft.words() if value >> 24 in (0x15, 0x19) and value & 0x10000)
            line['data'] = host_word('DATA_STATUS') & 0xFF
            line['sd_reads'] = sum(1 for command in card.commands if command[0] in (17, 18))
            print(json.dumps(line, ensure_ascii=False), flush=True)
        stats.append(line)
    elapsed = time.perf_counter() - started
    if args.dl_record:
        Path(args.dl_record).write_text(json.dumps(dl_hashes) + '\n', encoding='utf-8')
    if args.ticks:
        Path(args.ticks).write_text(json.dumps({'frames': stats, 'profile': profile}, ensure_ascii=False) + '\n',
                                    encoding='utf-8')
    if profile:
        total = sum(profile.values())
        print('Профиль Z80 (такты инструкций; задержки DMA/FT812 модель не воспроизводит):')
        for name, ticks in sorted(profile.items(), key=lambda item: -item[1])[:35]:
            print(f'  {name:>28} {100 * ticks / total:5.1f}%')
    befores = sorted(item['before'] for item in stats)
    afters = sorted(item['after'] for item in stats)
    words = sorted(item['words'] for item in stats)
    diffs = [item['diff'] for item in stats if 'diff' in item]
    print(json.dumps({'frames': len(stats), 'before_median': befores[len(befores) // 2], 'before_max': befores[-1],
                      'after_median': afters[len(afters) // 2], 'after_max': afters[-1],
                      'words_median': words[len(words) // 2], 'words_max': words[-1],
                      'diff_max': max(diffs) if diffs else None, 'inflates': ft.inflates,
                      'seconds': round(elapsed)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
