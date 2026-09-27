"""Перепись ячеек спрайтов, которые запрашивает M72SpriteAtlas.cell за прогон app.main.

Прогоны автопилота Stage 1 (с неуязвимостью до босса и со случайным вводом)
перечисляют ключи (банк, код, отражения). По ним сборка Z80 готовит сжатые
изображения для FT812; ключ вне переписи адаптер считает отсутствующим.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import p2c_app  # noqa: E402


class NullTarget:
    def get_width(self) -> int:
        return 640

    def get_height(self) -> int:
        return 480

    def fill(self, *args, **kwargs) -> None:
        pass

    def blit(self, *args, **kwargs) -> None:
        pass


def run(frames: int, seed: int, chaos: bool, invulnerable: bool, keys: set) -> None:
    app, _sound = p2c_app.build_snapshot()
    from rtype_port.autopilot import Stage1Autopilot
    from rtype_port.enemies import M72SpriteAtlas
    from rtype_port.game import InputState
    original = M72SpriteAtlas.cell

    def cell(self, palette, resource_type, code, flip_x, flip_y):
        bank_key, _path = self._asset(palette, resource_type)
        keys.add((bank_key[0], bank_key[1], code & 0x0FFF, bool(flip_x), bool(flip_y)))
        return original(self, palette, resource_type, code, flip_x, flip_y)

    M72SpriteAtlas.cell = cell
    pilot = Stage1Autopilot()
    rng = random.Random(seed)
    chaos_left = 0
    chaos_input = None
    target = NullTarget()
    started = time.perf_counter()
    try:
        for frame in range(1, frames + 1):
            game = app.game
            if game is not None:
                planned = pilot.next(game)
                if chaos:
                    if chaos_left == 0 and rng.random() < 0.004:
                        chaos_left = rng.randint(20, 240)
                    if chaos_left:
                        if chaos_input is None or rng.random() < 0.08:
                            chaos_input = {name: rng.random() < 0.3 for name in p2c_app.INPUT_FIELDS}
                        planned = InputState(**chaos_input)
                        chaos_left -= 1
                if invulnerable and game.lifecycle.active:
                    game.lifecycle.invulnerability = max(game.lifecycle.invulnerability, 2)
                if game.lifecycle.lives < 3:
                    game.lifecycle.lives = 8
            else:
                planned = InputState()
            app.frame(frame == 320, planned, target)
            if frame % 2000 == 0:
                print(f'кадр {frame}: ячеек {len(keys)}, {frame / (time.perf_counter() - started):.0f} к/с', flush=True)
    finally:
        M72SpriteAtlas.cell = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=20000)
    parser.add_argument('--output', default=str(ROOT / 'Build' / 'P2cZ80' / 'sprite_cells.json'))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    keys: set = set()
    path = Path(args.output)
    if path.is_file():
        keys |= {tuple(item) for item in json.loads(path.read_text(encoding='utf-8'))['cells']}
    run(args.frames, 1, chaos=False, invulnerable=True, keys=keys)
    run(args.frames // 2, 7, chaos=True, invulnerable=False, keys=keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'cells': sorted(keys)}, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'ячеек спрайтов: {len(keys)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
