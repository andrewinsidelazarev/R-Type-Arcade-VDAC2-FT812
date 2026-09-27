"""Трансляция Stage (скролл, карты, оба слоя) и сверка сгенерированного C с CPython.

Сгенерированный C собирается на ПК (tcc, все проверки включены) и идёт в lockstep
с объектом Stage активного rtype_port: после каждого кадра сравниваются все
использованные поля, VRAM, ключи ячеек и список команд вывода обоих слоёв.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
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

from py2c.cmodule import build_module, write_manifest  # noqa: E402
from py2c.heap import Heap  # noqa: E402
from py2c.program import Program  # noqa: E402
from py2c.translate import Translator  # noqa: E402

BUILD = ROOT / 'Build' / 'Py2cStage'
GENERATED = ROOT / 'Source' / 'C' / 'generated' / 'py2c_stage.c'
C_DIR = ROOT / 'Source' / 'C' / 'py2c'
TCC = Path('E:/zx/tcc-0.9.27/tcc/tcc.exe')
ROOTS = {'stage': ('Stage', ['update', 'draw_back', 'draw_front'])}


def translate(stage: object):
    program = Program('rtype_port', ['stage'])
    heap = Heap(program, {'stage': stage})
    translator = Translator(program, heap)
    translator.translate([(class_name, method)
                          for class_name, methods in ROOTS.values() for method in methods])
    module = build_module(translator, heap, 'py2c_platform.h', ROOTS)
    return program, heap, translator, module


def build_host(module) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    GENERATED.write_text(module.source, encoding='utf-8', newline='\n')
    write_manifest(BUILD / 'manifest.json', module.manifest)
    output = BUILD / 'stage_host.dll'
    command = [str(TCC), '-shared', '-Wall', '-I', str(C_DIR / 'host'), '-I', str(C_DIR),
               str(GENERATED), str(C_DIR / 'py2c_runtime.c'), str(C_DIR / 'host' / 'py2c_host.c'),
               '-o', str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('tcc:\n' + result.stdout + result.stderr)
    if result.stdout.strip() or result.stderr.strip():
        print('tcc:', (result.stdout + result.stderr).strip()[:2000])
    return output


class HostModule:
    """Загруженная DLL сгенерированного C с привязанными внешними данными."""

    def __init__(self, path: Path, module) -> None:
        self.dll = ctypes.CDLL(str(path))
        self.module = module
        self._buffers = []
        for index, item in enumerate(module.data.externals):
            buffer = ctypes.create_string_buffer(item.payload, len(item.payload))
            self._buffers.append(buffer)
            self.dll.py2c_bind_external(ctypes.c_uint16(index), buffer)
        self.dll.py2c_host_blit_data.restype = ctypes.POINTER(ctypes.c_int32)
        self.dll.py2c_host_fault.restype = ctypes.c_int32
        self.dll.py2c_dump.restype = ctypes.c_uint32
        self.dump_buffer = ctypes.create_string_buffer(8 << 20)

    def call(self, root: str, method: str) -> None:
        getattr(self.dll, self.module.manifest['roots'][root][method])()
        if self.dll.py2c_host_faults():
            code = self.dll.py2c_host_fault()
            messages = self.module.manifest['raise_messages']
            text = messages[code - 1] if 0 < code <= len(messages) else f'код {code}'
            raise RuntimeError(f'отказ C в {root}.{method}: {text}')

    def dump(self) -> bytes:
        length = self.dll.py2c_dump(self.dump_buffer)
        return self.dump_buffer.raw[:length]

    def blits(self) -> list[tuple[int, int, int]]:
        count = self.dll.py2c_host_blits()
        data = self.dll.py2c_host_blit_data()
        return [(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]) for i in range(count)]


def python_dump(layout: list[dict], objects: dict[int, object], symbols: dict[str, int],
                image_ids: dict[int, int]) -> bytes:
    """Та же выгрузка, что py2c_dump, но по объектам CPython."""
    out = bytearray()
    for entry in layout:
        owner = objects[entry['object']]
        kind = entry['kind']
        if kind in ('int', 'opt', 'ref', 'image'):
            value = getattr(owner, entry['field'])
            if kind == 'int':
                out += struct.pack('<i', int(value))
            elif kind == 'opt':
                out += struct.pack('<iB', 0 if value is None else value, 0 if value is None else 1)
            elif kind == 'image':
                out += struct.pack('<i', image_ids[id(value)])
            else:
                ids = [symbols[target] for target in entry['targets']]
                out += struct.pack('<H', ids.index(id(value)) if id(value) in ids else 0xFFFF)
        elif kind == 'buffer':
            out += struct.pack('<i', len(owner)) + bytes(owner)
        elif kind == 'array':
            out += struct.pack('<i', len(owner))
            if 'targets' in entry:
                ids = [symbols[target] for target in entry['targets']]
                out += b''.join(struct.pack('<H', ids.index(id(item)) if id(item) in ids else 0xFFFF)
                                for item in owner)
            else:
                out += struct.pack(f'<{len(owner)}i', *owner)
    return bytes(out)


class Recorder:
    def __init__(self, image_ids: dict[int, int]) -> None:
        self.image_ids = image_ids
        self.commands: list[tuple[int, int, int]] = []

    def blit(self, surface, position) -> None:
        self.commands.append((self.image_ids[id(surface)], position[0], position[1]))


def first_dump_difference(expected: bytes, actual: bytes, layout: list[dict]) -> str:
    """Имя поля, в котором впервые расходятся выгрузки."""
    position = next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
                    min(len(expected), len(actual)))
    return f'байт {position} из {len(expected)}/{len(actual)}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=2000)
    parser.add_argument('--render-every', type=int, default=1)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    pygame.init()
    pygame.display.set_mode((64, 64))
    from rtype_port.stage import Stage
    started = time.perf_counter()
    stage = Stage()
    program, heap, translator, module = translate(stage)
    print(f'трансляция: функций {len(translator.queue)}, строк C {module.source.count(chr(10))}, '
          f'внешних данных {len(module.data.externals)}, изображений {len(heap.images)}, '
          f'{time.perf_counter() - started:.1f} с', flush=True)
    host = HostModule(build_host(module), module)
    from py2c.heap import DataEmitter  # noqa: F401
    emitter_objects = {id(obj): obj for obj in module_alive(module)}
    symbols = {symbol: object_id for object_id, symbol in module_symbols(module).items()}
    image_ids = module_image_ids(module)
    layout = module.manifest['dump_layout']

    def compare(frame: int, stage_name: str) -> None:
        expected = python_dump(layout, emitter_objects, symbols, image_ids)
        actual = host.dump()
        if expected != actual:
            raise SystemExit(f'РАСХОЖДЕНИЕ состояния на кадре {frame} ({stage_name}): '
                             f'{first_dump_difference(expected, actual, layout)}')

    compare(0, 'начало')
    frames_rendered = 0
    blits_max = 0
    for frame in range(1, args.frames + 1):
        stage.update()
        host.call('stage', 'update')
        compare(frame, 'update')
        if args.render_every and frame % args.render_every == 0:
            recorder = Recorder(image_ids)
            stage.draw_back(recorder)
            stage.draw_front(recorder)
            host.dll.py2c_host_reset()
            host.call('stage', 'draw_back')
            host.call('stage', 'draw_front')
            actual = host.blits()
            if recorder.commands != actual:
                index = next((i for i, (a, b) in enumerate(zip(recorder.commands, actual)) if a != b),
                             min(len(recorder.commands), len(actual)))
                raise SystemExit(f'РАСХОЖДЕНИЕ вывода на кадре {frame}: команда {index}, '
                                 f'CPython={recorder.commands[index:index + 1]} '
                                 f'C={actual[index:index + 1]}, длины {len(recorder.commands)}/{len(actual)}')
            frames_rendered += 1
            blits_max = max(blits_max, len(actual))
            compare(frame, 'render')
        if frame % 1000 == 0:
            print(f'кадр {frame}: совпадает, vblank {stage.m72_scroll.vblank}, участок {stage.section_index}, '
                  f'команд вывода до {blits_max}', flush=True)
    report = {'frames': args.frames, 'frames_rendered': frames_rendered, 'blits_max': blits_max,
              'functions': len(translator.queue), 'result': 'identical',
              'seconds': round(time.perf_counter() - started, 1)}
    (BUILD / 'host_lockstep.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0


def module_alive(module):
    return module.emitter.alive


def module_symbols(module):
    return module.emitter.symbols


def module_image_ids(module):
    return module.emitter.image_ids


if __name__ == '__main__':
    raise SystemExit(main())
