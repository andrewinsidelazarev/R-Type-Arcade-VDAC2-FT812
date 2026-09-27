"""Сверка самостоятельной игры rtype_port.Game с полным runtime (ROM World + баланс).

Оба исполняются без окна с одинаковым вводом (автопилот Stage 1 ведёт самостоятельную
игру, та же маска подаётся ROM). Полный runtime стартует штатной последовательностью
coin → start до запуска R-9; кадр 0 самостоятельной игры сопоставляется с ним по
изображению. По кадрам сравниваются: картинка 640×480, жизни, очки, звуковые команды.
Первые расхождения сохраняются в Build/Parity парами PNG.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Build' / 'PythonDeps', ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import numpy as np  # noqa: E402
import pygame  # noqa: E402

OUT = ROOT / 'Build' / 'Parity'
WORK_RAM = 0x40000


def mask_of(inputs) -> int:
    return ((0x01 if inputs.right else 0) | (0x02 if inputs.left else 0) | (0x04 if inputs.down else 0) |
            (0x08 if inputs.up else 0) | (0x10 if inputs.fire else 0) | (0x20 if inputs.force_action else 0))


def packed_bcd(data: bytes) -> int:
    value = 0
    for byte in reversed(data):
        value = value * 100 + ((byte >> 4) & 15) * 10 + (byte & 15)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--align-window', type=int, default=3000)
    parser.add_argument('--tolerance', type=int, default=48, help='порог суммы |dR|+|dG|+|dB| пикселя')
    parser.add_argument('--save', type=int, default=6, help='сколько пар кадров с расхождением сохранить')
    parser.add_argument('--idle', action='store_true', help='без ввода вместо автопилота')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    pygame.init()
    pygame.display.set_mode((640, 480))
    from rtype_port.autopilot import Stage1Autopilot
    from rtype_port.full_runtime import FullRuntimeGame
    from rtype_port.game import Game, InputState

    full_sounds: list[int] = []
    port_sounds: list[int] = []

    def new_pair():
        full = FullRuntimeGame(full_sounds.append)
        full.request_start()
        steps = 0
        while not full.advance_start():
            steps += 1
        return full, Game(port_sounds.append), steps

    target = pygame.Surface((640, 480))
    scratch = pygame.Surface((640, 480))

    def full_image(full) -> np.ndarray:
        return np.frombuffer(full.renderer.rgba, dtype=np.uint8).reshape(480, 640, 4)[:, :, :3].astype(np.int16)

    def port_image() -> np.ndarray:
        return pygame.surfarray.array3d(target).transpose(1, 0, 2).astype(np.int16)

    def differing(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.abs(a - b).sum(axis=2) > args.tolerance

    # Проход 1: кадр ROM после запуска R-9, где состояние скроллера (RAM $2EC0 передний
    # аккумулятор, $2F4A прогресс, по 24 бита) равно состоянию самостоятельной игры после кадра 0.
    def rom_scroll(full) -> tuple[int, int]:
        foreground = int.from_bytes(full.machine.cpu.mem_read(WORK_RAM + 0x2EC0, 3), 'little')
        progression = int.from_bytes(full.machine.cpu.mem_read(WORK_RAM + 0x2F4A, 3), 'little')
        return foreground, progression

    full, game, start_frames = new_pair()
    pilot = Stage1Autopilot()
    first = InputState() if args.idle else pilot.next(game)
    game.update(first)
    scroll = game.stage.m72_scroll
    wanted = (scroll.foreground_accumulator, scroll.progression_accumulator)
    offset = None
    seen = []
    for step in range(args.align_window + 1):
        state = rom_scroll(full)
        if len(seen) < 8 or state == wanted:
            seen.append((step, hex(state[0]), hex(state[1])))
        if state == wanted:
            offset = step
            break
        full.update(0)
    print(f'самостоятельная игра после кадра 0: скроллер {hex(wanted[0])}/{hex(wanted[1])}; '
          f'ROM после запуска R-9 (coin/start {start_frames} кадров): {seen}', flush=True)
    if offset is None:
        raise SystemExit('в окне сопоставления ROM не дошёл до того же состояния скроллера')
    # Проход 2: заново, ROM продвигается до найденного кадра, затем одинаковый ввод.
    full_sounds.clear()
    port_sounds.clear()
    full, game, _steps = new_pair()
    pilot = Stage1Autopilot()
    for _ in range(offset):
        full.update(0)
        full.render(scratch)
    full_sounds.clear()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'start_frames': start_frames, 'offset': offset, 'frames': []}
    saved = 0
    for frame in range(args.frames):
        inputs = InputState() if args.idle else pilot.next(game)
        game.update(inputs)
        game.render(target)
        if frame:
            full.update(mask_of(inputs))
            full.render(scratch)
        image = full_image(full)
        port = port_image()
        diff = differing(image, port)
        count = int(diff.sum())
        full_lives = int.from_bytes(full.machine.cpu.mem_read(WORK_RAM + 0x2F32, 2), 'little')
        full_score = packed_bcd(bytes(full.machine.cpu.mem_read(WORK_RAM + 0x2F34, 4)))
        port_lives, port_score = game.lifecycle.lives, game.enemy_world.score
        record = {'frame': frame, 'pixels': count}
        if count:
            ys, xs = np.nonzero(diff)
            record['bbox'] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        if (full_lives, full_score) != (port_lives, port_score):
            record['state'] = {'rom': [full_lives, full_score], 'port': [port_lives, port_score]}
        if full_sounds != port_sounds:
            record['sound'] = {'rom': list(full_sounds), 'port': list(port_sounds)}
        full_sounds.clear()
        port_sounds.clear()
        if count or 'state' in record or 'sound' in record:
            report['frames'].append(record)
            if saved < args.save and count:
                pygame.image.save(pygame.surfarray.make_surface(image.astype(np.uint8).transpose(1, 0, 2)),
                                  str(OUT / f'rom_{frame:05d}.png'))
                pygame.image.save(target, str(OUT / f'port_{frame:05d}.png'))
                saved += 1
        if frame % 100 == 0:
            print(f'кадр {frame}: пикселей {count} {record.get("bbox", "")}, ROM жизни/очки {full_lives}/{full_score}, '
                  f'порт {port_lives}/{port_score}', flush=True)
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=0) + '\n', encoding='utf-8')
    differing = [record for record in report['frames'] if record.get('pixels')]
    print(json.dumps({'кадров': args.frames, 'с расхождением картинки': len(differing),
                      'с расхождением жизней/очков': sum('state' in r for r in report['frames']),
                      'со звуком': sum('sound' in r for r in report['frames'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
