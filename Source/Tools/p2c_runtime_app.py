"""Трансляция цикла app.main текущей Python-версии (титул + полный runtime World ROM) в C и
покадровая сверка на ПК.

Снимок: TitleScreen(TitleAssets()) и RuntimeApp из p2c_entry_runtime с портом машины
MachinePort. Корни трансляции — первичная отрисовка титула и RuntimeApp.frame. На ПК порт —
эталонная машина M72 (unicorn, баланс FullRuntimeGame) с журналом вызовов; в C вызовы порта
записываются, а слова рабочего ОЗУ берутся из журнала CPython. Каждый кадр сравниваются
команды вывода титула и последовательность вызовов порта (новая машина, шаг с вводом, чтение
слова, показ кадра, сброс сессии).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import v30z80  # noqa: E402,F401  (numba до numpy)
import p2c_app  # noqa: E402
from p2c.cgen import CModule  # noqa: E402
from p2c.compiler import Compiler, ExternMethod  # noqa: E402
from p2c.crepr import CRepr  # noqa: E402
from p2c.program import Program  # noqa: E402
from p2c.ptypes import BOOL, TARGET, VOID, IntT, ObjT, ValT  # noqa: E402

BUILD = ROOT / 'Build' / 'P2cApp'
MODULES = ['title']
EXTRA_MODULES = ('p2c_entry_runtime',)
EVENT_FIELDS = ('title_start', 'system_start', 'coin', 'demo_wake')
BUTTON_FIELDS = ('right', 'left', 'down', 'up', 'fire', 'force')
PORT_KINDS = {1: 'boot', 2: 'step', 3: 'word', 4: 'show', 5: 'reset_session', 6: 'mouse'}


class MachinePort:
    """Порт машины на ПК: эталонная M72 и журнал вызовов (kind, a, b, c, результат)."""

    def __init__(self) -> None:
        self.machine = None
        self.calls: list[tuple] = []

    def boot(self) -> None:
        from v30z80 import snapshot
        self.machine = snapshot.new_reference_machine()
        self.calls.append(('boot', 0, 0, 0, None))

    def step(self, mask: int, start1: bool, coin1: bool, render: bool) -> None:
        from v30z80.scenario import Scenario
        Scenario.apply(self.machine, mask, bool(start1), bool(coin1))
        self.machine.step_frame()
        self.calls.append(('step', mask, int(bool(start1)) | (int(bool(coin1)) << 1), int(bool(render)), None))

    def word(self, address: int) -> int:
        value = int.from_bytes(bytes(self.machine.cpu.mem_read(address, 2)), 'little')
        self.calls.append(('word', address, 0, 0, value))
        return value

    def show(self) -> None:
        self.calls.append(('show', 0, 0, 0, None))

    def reset_session(self) -> None:
        self.calls.append(('reset_session', 0, 0, 0, None))

    def mouse(self) -> None:
        # Мыши у сверки на ПК нет: только запись вызова.
        self.calls.append(('mouse', 0, 0, 0, None))


def build_snapshot():
    import pygame
    pygame.init()
    pygame.display.set_mode((640, 480))
    from p2c_entry_runtime import RuntimeApp
    from rtype_port.title import TitleAssets
    port = MachinePort()
    app = RuntimeApp(TitleAssets(), port)
    return app, port


def analyze(app):
    program = Program('rtype_port', MODULES, EXTRA_MODULES)
    int32 = IntT(-(1 << 31), (1 << 31) - 1)
    externs = {'MachinePort': {
        'boot': ExternMethod('p2c_port_boot', (), VOID),
        'step': ExternMethod('p2c_port_step', (int32, BOOL, BOOL, BOOL), VOID),
        'word': ExternMethod('p2c_port_word', (int32,), IntT(0, 0xFFFF)),
        'show': ExternMethod('p2c_port_show', (), VOID),
        'reset_session': ExternMethod('p2c_port_reset_session', (), VOID),
        'mouse': ExternMethod('p2c_port_mouse', (), VOID),
    }}
    compiler = Compiler(program, {'app': app}, externs, {})
    for class_name, fields in (('FrameEvents', EVENT_FIELDS), ('GameButtons', BUTTON_FIELDS)):
        for name in fields:
            cell = compiler.field_cell(class_name, name)
            cell.t = BOOL
            cell.used = True
            cell.classes.add(class_name)
    crepr = CRepr(compiler)
    title_render = compiler.request_method('TitleScreen', 'render')
    title_render.params[0].t = ObjT('TitleScreen')
    title_render.params[1].t = TARGET
    frame = compiler.request_method('RuntimeApp', 'frame')
    frame.params[0].t = ObjT('RuntimeApp')
    frame.params[1].t = ValT('FrameEvents')
    frame.params[2].t = ValT('GameButtons')
    frame.params[3].t = TARGET
    started = time.perf_counter()
    compiler.analyze(crepr, [title_render, frame])
    compiler.purity()
    print(f'анализ: функций {len(compiler.queue)}, проходов {compiler.iteration + 1}, '
          f'{time.perf_counter() - started:.1f} с', flush=True)
    entry_list = [('p2c_title_render', 'app_title', 'TitleScreen', 'render', ['target']),
                  ('p2c_app_frame', 'app', 'RuntimeApp', 'frame',
                   [('value', 'FrameEvents'), ('value', 'GameButtons'), 'target'])]
    return compiler, entry_list


def translate(app):
    started = time.perf_counter()
    compiler, entry_list = analyze(app)
    image_ids: dict[int, int] = {}
    alive = []

    def image_id(surface) -> int:
        if id(surface) not in image_ids:
            image_ids[id(surface)] = len(image_ids) + 1
            alive.append(surface)
        return image_ids[id(surface)]

    roots = {'app': app, 'app_title': app.title}
    module = CModule(compiler, image_id, roots, entry_list)
    source = module.build()
    source = source.replace('#include "p2c_runtime.h"', '#include "p2c_runtime.h"\n' + p2c_app.input_converter(module))
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'p2c_app.c').write_text(source, encoding='utf-8', newline='\n')
    print(f'C: {len(source) // 1024} КБ, {time.perf_counter() - started:.1f} с', flush=True)
    return compiler, module, image_ids, alive


class PortCall(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_int32), ('a', ctypes.c_int32), ('b', ctypes.c_int32), ('c', ctypes.c_int32)]


def bits(value, fields) -> int:
    return sum(int(bool(getattr(value, name))) << index for index, name in enumerate(fields))


def lockstep(host, app, port: MachinePort, image_ids: dict[int, int], frames: int, seed: int,
             start_frames: set[int], wake_frames: set[int]) -> dict:
    from p2c_entry_runtime import FrameEvents, GameButtons
    host.dll.p2c_host_port_data.restype = ctypes.POINTER(PortCall)
    recorder = p2c_app.Recorder(image_ids, None)
    app.title.render(recorder)
    host.call('p2c_title_render')
    difference = p2c_app.first_difference(recorder.commands, host.commands())
    if difference:
        return {'result': 'diverged', 'frame': 0, 'stage': 'title-render', 'difference': difference}
    rng = random.Random(seed)
    buttons = GameButtons()
    shown = 0
    started = time.perf_counter()
    for frame in range(1, frames + 1):
        events = FrameEvents()
        events.title_start = frame in start_frames
        events.demo_wake = frame in wake_frames
        if app.game is not None and rng.random() < 0.05:
            for name in BUTTON_FIELDS:
                setattr(buttons, name, rng.random() < 0.3)
        recorder.commands.clear()
        port.calls.clear()
        app.frame(events, buttons, recorder)
        words = [call[4] for call in port.calls if call[0] == 'word']
        array = (ctypes.c_int32 * max(1, len(words)))(*words)
        host.dll.p2c_host_set_words(array, len(words))
        host.call('p2c_app_frame', bits(events, EVENT_FIELDS), bits(buttons, BUTTON_FIELDS))
        difference = p2c_app.first_difference(recorder.commands, host.commands())
        if difference:
            return {'result': 'diverged', 'frame': frame, 'stage': 'frame', 'difference': difference}
        data = host.dll.p2c_host_port_data()
        c_calls = [(PORT_KINDS.get(data[index].kind, '?'), data[index].a, data[index].b, data[index].c)
                   for index in range(host.dll.p2c_host_port_total())]
        py_calls = [call[:4] for call in port.calls]
        if c_calls != py_calls:
            return {'result': 'diverged', 'frame': frame, 'stage': 'port',
                    'difference': f'CPython={py_calls} C={c_calls}'}
        shown += sum(1 for call in py_calls if call[0] == 'show')
        if frame % 500 == 0:
            print(f'кадр {frame}: показано кадров игры {shown}, игра {"есть" if app.game else "нет"}, '
                  f'{frame / (time.perf_counter() - started):.1f} к/с', flush=True)
    return {'result': 'identical', 'frames': frames, 'shown': shown}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=3000)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--start', default='320', help='кадры нажатия FIRE на титуле через запятую')
    parser.add_argument('--wake', default='', help='кадры пробуждения демо-игры через запятую')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    app, port = build_snapshot()
    compiler, module, image_ids, alive = translate(app)
    dll_path = p2c_app.compile_host()
    host = p2c_app.Host(dll_path)
    starts = {int(value) for value in args.start.split(',') if value}
    wakes = {int(value) for value in args.wake.split(',') if value}
    report = lockstep(host, app, port, image_ids, args.frames, args.seed, starts, wakes)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['result'] == 'identical' else 1


if __name__ == '__main__':
    raise SystemExit(main())
