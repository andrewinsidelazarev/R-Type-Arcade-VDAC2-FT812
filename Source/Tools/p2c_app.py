"""Трансляция программы от app.main (титул -> игра) в C и покадровая сверка на ПК.

Снимок объектов строится так же, как в app.main: TitleScreen(TitleAssets()),
TargetAudio, Game(sound.play), App(title, game, sound). Корни трансляции —
первичная отрисовка титула и App.frame. Сгенерированный C собирается tcc в
DLL с проверками; каждый кадр сравниваются команды вывода и звука с CPython.
"""
from __future__ import annotations

import argparse
import ctypes
import dataclasses
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame  # noqa: E402

from p2c.cgen import CModule  # noqa: E402
from p2c.compiler import Compiler, ExternMethod, INT_EMPTY  # noqa: E402
from p2c.crepr import CRepr  # noqa: E402
from p2c.program import Program  # noqa: E402
from p2c.ptypes import BOOL, IMAGE, TARGET, VOID, IntT, ObjT, ValT  # noqa: E402

BUILD = ROOT / 'Build' / 'P2cApp'
C_DIR = ROOT / 'Source' / 'C' / 'p2c'
TCC = Path('E:/zx/tcc-0.9.27/tcc/tcc.exe')
MODULES = ['title', 'stage', 'world_terrain', 'enemies', 'force', 'bits', 'player_lifecycle', 'game']
# Кадр программы (титул -> игра) — в инструментах: app.py пакета запускает полный runtime.
EXTRA_MODULES = ('p2c_entry',)
INPUT_FIELDS = ('left', 'right', 'up', 'down', 'fire', 'force_action')


class TargetAudio:
    """Звук для сверки: записывает команды вместо GS/TSFM (тот же интерфейс, что audio.TargetAudio)."""

    def __init__(self) -> None:
        self.commands: list[int] = []

    def play(self, command: int) -> None:
        self.commands.append(command)

    def start_music(self) -> None:
        self.commands.append(-1)


class RecordingFont(pygame.font.Font):
    """Шрифт отладочной строки: запоминает текст созданных поверхностей."""

    texts: dict[int, tuple] = {}

    def render(self, text, antialias, color, background=None):  # noqa: D401
        surface = super().render(text, antialias, color)
        RecordingFont.texts[id(surface)] = (text, bool(antialias), tuple(color), surface)
        return surface


class Recorder:
    """Цель отрисовки CPython: команды в кодировке адаптера ПК."""

    def __init__(self, image_ids: dict[int, int], atlas) -> None:
        self.image_ids = image_ids
        self.atlas = atlas
        self.commands: list[tuple] = []

    def get_width(self) -> int:
        return 640

    def get_height(self) -> int:
        return 480

    def fill(self, color, rect=None, special_flags=0) -> None:
        if color != 'black' or rect is not None:
            raise RuntimeError('fill поддержан только для "black"')
        self.commands.append((0xFFFFFFFF, 0, 0))

    def blit(self, source, dest, area=None, special_flags=0) -> None:
        number = self.image_ids.get(id(source))
        if number is None:
            number = self.cell_number(source)
        if number is None and id(source) in RecordingFont.texts:
            text, antialias, color, _surface = RecordingFont.texts[id(source)]
            number = ('text', text, antialias, color[:3])
        if number is None:
            raise RuntimeError(f'неизвестная поверхность в blit {source}')
        self.commands.append((number, dest[0], dest[1]))

    def cell_number(self, surface) -> int | None:
        if self.atlas is None:
            return None
        for key, cached in self.atlas._cells.items():
            if cached is surface:
                (typed, bank), code, flip_x, flip_y = key
                return (0x80000000 | (typed << 30) | (bank << 16) | ((code & 0x0FFF) << 2) |
                        (int(flip_x) << 1) | int(flip_y))
        return None


def build_snapshot():
    pygame.init()
    pygame.display.set_mode((640, 480))
    from p2c_entry import App
    from rtype_port.game import Game
    from rtype_port.title import TitleAssets, TitleScreen
    title = TitleScreen(TitleAssets())
    sound = TargetAudio()
    game = Game(sound.play)
    game.debug_distance_font = RecordingFont(None, 20)
    app = App(title, game, sound)
    return app, sound


def analyze(app, entries: list[str]):
    """Анализ программы от корней app.main: компилятор с выведенными формами и точки входа."""
    program = Program('rtype_port', MODULES, EXTRA_MODULES)
    externs = {'TargetAudio': {
        'play': ExternMethod('p2c_sound_play', (IntT(-(1 << 31), (1 << 31) - 1),), VOID),
        'start_music': ExternMethod('p2c_sound_start_music', (), VOID),
    }}
    extern_methods = {('M72SpriteAtlas', 'cell'): ExternMethod(
        'p2c_sprite_cell', (IntT(-(1 << 31), (1 << 31) - 1), IntT(-(1 << 31), (1 << 31) - 1),
                            IntT(-(1 << 31), (1 << 31) - 1), BOOL, BOOL), IMAGE)}
    compiler = Compiler(program, {'app': app}, externs, extern_methods)
    for name in INPUT_FIELDS:
        cell = compiler.field_cell('InputState', name)
        cell.t = BOOL
        cell.used = True
        cell.classes.add('InputState')
    crepr = CRepr(compiler)
    title_render = compiler.request_method('TitleScreen', 'render')
    title_render.params[0].t = ObjT('TitleScreen')
    title_render.params[1].t = TARGET
    frame = None
    if 'frame' in entries:
        frame = compiler.request_method('App', 'frame')
        frame.params[0].t = ObjT('App')
        frame.params[1].t = BOOL
        frame.params[2].t = ValT('InputState')
        frame.params[3].t = TARGET
    else:
        update = compiler.request_method('TitleScreen', 'update')
        update.params[0].t = ObjT('TitleScreen')
    started = time.perf_counter()
    roots = [title_render, frame if frame is not None else update]
    compiler.analyze(crepr, roots)
    compiler.purity()
    print(f'анализ: функций {len(compiler.queue)}, проходов {compiler.iteration + 1}, '
          f'{time.perf_counter() - started:.1f} с', flush=True)
    entry_list = [('p2c_title_render', 'app_title', 'TitleScreen', 'render', ['target'])]
    if frame is not None:
        entry_list.append(('p2c_app_frame', 'app', 'App', 'frame', ['bool', ('value', 'InputState'), 'target']))
    else:
        entry_list.append(('p2c_title_update', 'app_title', 'TitleScreen', 'update', []))
    return compiler, entry_list


def translate(app, entries: list[str]):
    started = time.perf_counter()
    compiler, entry_list = analyze(app, entries)
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
    source = source.replace('#include "p2c_runtime.h"', '#include "p2c_runtime.h"\n' + input_converter(module))
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / 'p2c_app.c').write_text(source, encoding='utf-8', newline='\n')
    print(f'C: {len(source) // 1024} КБ, {time.perf_counter() - started:.1f} с', flush=True)
    return compiler, module, image_ids, alive


def input_converter(module) -> str:
    return ('struct P2cInputBits;\n#define P2C_INPUT_FIELDS ' + str(len(INPUT_FIELDS)) + '\n')


def compile_host() -> Path:
    # Отдельная DLL на процесс: параллельные прогоны сверки не блокируют файл друг друга.
    output = BUILD / f'p2c_app_host_{os.getpid()}.dll'
    command = [str(TCC), '-shared', '-Wall', '-I', str(C_DIR / 'host'), '-I', str(C_DIR),
               '-o', str(output), str(BUILD / 'p2c_app.c'), str(C_DIR / 'p2c_runtime.c'),
               str(C_DIR / 'host' / 'p2c_host.c')]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise RuntimeError('tcc:\n' + (result.stdout + result.stderr)[:6000])
    return output


class HostCommand(ctypes.Structure):
    _fields_ = [('image', ctypes.c_uint32), ('x', ctypes.c_int32), ('y', ctypes.c_int32)]


class Host:
    """Обёртка DLL сверки: кадр, команды вывода, звук, отказы."""

    def __init__(self, path: Path) -> None:
        self.dll = ctypes.CDLL(str(path))
        self.dll.p2c_host_command_data.restype = ctypes.POINTER(HostCommand)
        self.dll.p2c_host_sound_data.restype = ctypes.POINTER(ctypes.c_int32)
        self.dll.p2c_host_fault_message.restype = ctypes.c_char_p
        self.dll.p2c_host_fault_place.restype = ctypes.c_char_p
        self.dll.p2c_host_text_data.restype = ctypes.POINTER(ctypes.c_uint8)
        self.metric_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int32,
                                            ctypes.c_int32, ctypes.c_int32)
        self.font = None
        self.metric = self.metric_type(self._metric)
        self.dll.p2c_host_set_text_metric(self.metric)

    def _metric(self, data, length, antialias, which) -> int:
        # Размеры поверхности, которую создал бы font.render на ПК (адаптер отладочного текста).
        text = bytes(data[:length]).decode('utf-8')
        surface = pygame.font.Font.render(self.font, text, bool(antialias), (255, 255, 255))
        return surface.get_size()[which]

    def call(self, name: str, *arguments) -> None:
        self.dll.p2c_host_begin_frame()
        getattr(self.dll, name)(*arguments)
        code = self.dll.p2c_host_fault_code()
        if code:
            message = self.dll.p2c_host_fault_message(code).decode('utf-8', 'replace') if code > 0 else ''
            place = self.dll.p2c_host_fault_place().decode('utf-8', 'replace')
            raise RuntimeError(f'отказ C: код {code} в {place} {message}')

    def commands(self) -> list[tuple]:
        count = self.dll.p2c_host_command_total()
        data = self.dll.p2c_host_command_data()
        result = []
        for index in range(count):
            item = data[index]
            image = item.image
            if (image & 0xC0000000) == 0x40000000:
                length = ctypes.c_int32()
                antialias = ctypes.c_int32()
                color_value = ctypes.c_uint32()
                pointer = self.dll.p2c_host_text_data(image & 63, ctypes.byref(length), ctypes.byref(antialias),
                                                      ctypes.byref(color_value))
                text = bytes(pointer[:length.value]).decode('utf-8')
                color = color_value.value
                image = ('text', text, bool(antialias.value), ((color >> 16) & 255, (color >> 8) & 255, color & 255))
            result.append((image, item.x, item.y))
        return result

    def sounds(self) -> list[int]:
        count = self.dll.p2c_host_sound_total()
        data = self.dll.p2c_host_sound_data()
        return [data[index] for index in range(count)]


def first_difference(left: list, right: list) -> str | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return f'команда {index}: CPython={a} C={b}'
    if len(left) != len(right):
        return f'длины {len(left)} (CPython) и {len(right)} (C)'
    return None


def lockstep_title(host: Host, app, image_ids: dict[int, int], frames: int) -> dict:
    title = app.title
    recorder = Recorder(image_ids, None)
    title.render(recorder)
    host.call('p2c_title_render')
    difference = first_difference(recorder.commands, host.commands())
    if difference:
        return {'result': 'diverged', 'frame': 0, 'difference': difference}
    for frame in range(1, frames + 1):
        title.update()
        recorder.commands.clear()
        title.render(recorder)
        host.call('p2c_title_update')
        host.call('p2c_title_render')
        difference = first_difference(recorder.commands, host.commands())
        if difference:
            return {'result': 'diverged', 'frame': frame, 'difference': difference}
    return {'result': 'identical', 'frames': frames}


def input_bits(inputs) -> int:
    return sum(int(bool(getattr(inputs, name))) << index for index, name in enumerate(INPUT_FIELDS))


def lockstep_app(host: Host, app, sound: TargetAudio, image_ids: dict[int, int], frames: int,
                 seed: int, chaos: bool, start_frame: int, collect_every: int, state_every: int,
                 invulnerable: bool = False, keep_lives: bool = False) -> dict:
    """Кадры app.main: титул, нажатие FIRE, игра с автопилотом и случайным вводом."""
    from p2c_state import StateComparer
    from rtype_port.autopilot import Stage1Autopilot
    comparer = StateComparer(host.dll, image_ids)
    from rtype_port.enemies import RESOURCE_HQ
    from rtype_port.game import InputState
    for resource_type in range(256):
        typed = (RESOURCE_HQ / f'RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin').is_file()
        host.dll.p2c_host_set_typed_bank(resource_type, int(typed))
    game = app.prepared_game
    recorder = Recorder(image_ids, game.enemy_world.atlas)
    app.title.render(recorder)
    host.call('p2c_title_render')
    difference = first_difference(recorder.commands, host.commands())
    if difference:
        return {'result': 'diverged', 'frame': 0, 'stage': 'title-render', 'difference': difference}
    pilot = Stage1Autopilot()
    rng = random.Random(seed)
    chaos_left = 0
    chaos_input = None
    started = time.perf_counter()
    for frame in range(1, frames + 1):
        start_pressed = frame == start_frame
        if app.game is not None:
            planned = pilot.next(app.game)
            if chaos:
                if chaos_left == 0 and rng.random() < 0.004:
                    chaos_left = rng.randint(20, 240)
                if chaos_left:
                    if chaos_input is None or rng.random() < 0.08:
                        chaos_input = {name: rng.random() < 0.3 for name in INPUT_FIELDS}
                    planned = InputState(**chaos_input)
                    chaos_left -= 1
        else:
            planned = InputState()
        recorder.atlas = (app.game or app.prepared_game).enemy_world.atlas
        recorder.commands.clear()
        sound.commands.clear()
        if invulnerable and app.game is not None and app.game.lifecycle.active:
            # Одинаковая неуязвимость обеих версий: прогон доходит до босса.
            app.game.lifecycle.invulnerability = max(app.game.lifecycle.invulnerability, 2)
            lifecycle = comparer.object_path(['game', 'lifecycle'])
            current = comparer.read_field_int(lifecycle, 'invulnerability')
            comparer.write_int(lifecycle, 'invulnerability', max(current, 2))
        if keep_lives and app.game is not None and app.game.lifecycle.lives < 3:
            app.game.lifecycle.lives = 8
            comparer.write_int(comparer.object_path(['game', 'lifecycle']), 'lives', 8)
        app.frame(start_pressed, planned, recorder)
        host.call('p2c_app_frame', int(start_pressed), input_bits(planned))
        difference = first_difference(recorder.commands, host.commands())
        if difference:
            return {'result': 'diverged', 'frame': frame, 'stage': 'frame', 'difference': difference}
        if sound.commands != host.sounds():
            return {'result': 'diverged', 'frame': frame, 'stage': 'sound',
                    'difference': f'CPython={sound.commands} C={host.sounds()}'}
        if state_every and frame % state_every == 0:
            found = comparer.compare_root(app, 0)
            if found:
                return {'result': 'diverged', 'frame': frame, 'stage': 'state', 'difference': found}
        if collect_every and frame % collect_every == 0:
            host.dll.p2c_host_collect()
            code = host.dll.p2c_host_fault_code()
            if code:
                return {'result': 'fault', 'frame': frame, 'stage': 'collect', 'code': code}
        if frame % 500 == 0:
            game_now = app.game
            progression = game_now.stage.m72_scroll.progression if game_now is not None else 0
            census = (ctypes.c_uint32 * 256)()
            host.dll.p2c_host_heap_census(census)
            top = sorted(((census[index], comparer.class_names[index] or str(index)) for index in range(256)
                          if census[index]), reverse=True)[:6]
            print(f'кадр {frame}: progression ${progression:04X}, куча {host.dll.p2c_host_heap_used()} '
                  f'(пик {host.dll.p2c_host_heap_peak()}), {frame / (time.perf_counter() - started):.1f} к/с, '
                  f'классы {top}', flush=True)
    return {'result': 'identical', 'frames': frames}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--entries', default='title', help='title — только титул; frame — App.frame')
    parser.add_argument('--frames', type=int, default=400)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--chaos', action='store_true')
    parser.add_argument('--start-frame', type=int, default=320, help='кадр нажатия FIRE на титуле')
    parser.add_argument('--collect-every', type=int, default=1, help='сборка мусора каждые N кадров')
    parser.add_argument('--state-every', type=int, default=0, help='сверка состояния объектов каждые N кадров')
    parser.add_argument('--invulnerable', action='store_true')
    parser.add_argument('--keep-lives', action='store_true')
    parser.add_argument('--report', default=None)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    app, sound = build_snapshot()
    compiler, module, image_ids, alive = translate(app, args.entries.split(','))
    dll_path = compile_host()
    print('DLL собрана', flush=True)
    host = Host(dll_path)
    host.font = app.prepared_game.debug_distance_font
    if 'frame' not in args.entries:
        report = lockstep_title(host, app, image_ids, args.frames)
    else:
        report = lockstep_app(host, app, sound, image_ids, args.frames, args.seed, args.chaos,
                              args.start_frame, args.collect_every, args.state_every,
                              args.invulnerable, args.keep_lives)
        report.update(seed=args.seed, chaos=args.chaos, invulnerable=args.invulnerable,
                      keep_lives=args.keep_lives, frames_requested=args.frames)
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8', newline='\n')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['result'] == 'identical' else 1


if __name__ == '__main__':
    raise SystemExit(main())
