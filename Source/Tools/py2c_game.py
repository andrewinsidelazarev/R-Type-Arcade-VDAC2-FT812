"""Трансляция Game (update/render) от снимка объекта, созданного как в app.main.

Первый этап — только трансляция: транслятор сообщает первую неподдержанную
конструкцию с файлом и строкой. Хост-сверка с CPython добавляется, когда весь
достижимый код переводится.
"""
from __future__ import annotations

import os
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

from py2c.heap import Heap  # noqa: E402
from py2c.program import Program  # noqa: E402
from py2c.translate import Translator  # noqa: E402

MODULES = ['title', 'stage', 'world_terrain', 'enemies', 'force', 'bits', 'player_lifecycle', 'game']
ROOTS = [('Game', 'update'), ('Game', 'render')]


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    pygame.init()
    pygame.display.set_mode((640, 480))
    from rtype_port.game import Game
    started = time.perf_counter()
    sounds: list[int] = []
    game = Game(sounds.append)
    program = Program('rtype_port', MODULES)
    heap = Heap(program, {'game': game}, external_threshold=256)
    translator = Translator(program, heap)
    translator.translate(ROOTS)
    print(f'трансляция Game: функций {len(translator.queue)}, {time.perf_counter() - started:.1f} с')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
