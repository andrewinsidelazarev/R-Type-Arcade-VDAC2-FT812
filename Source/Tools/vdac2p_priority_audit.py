"""Аудит приоритета тайлов и спрайтов по всей игре: какой источник виден в каждом пикселе игрового поля у аркады и
у вывода порта FT812. Жалоба пользователя 2026-09-25 («в уровне 3 Z-index двигателя корабля неверный», «проверь всю
игру на подобные ошибки»): двигатель линкора этапа 3 у аркады под корпусом, у порта — поверх.

Идёт только эталонная машина M72 (без Z80, как у rtype_check: RuntimeApp, тот же ввод — сценарий автоогня или
случайный), каждые --every кадров — состояние кадра (FrameState: VRAM слоёв, построчный скролл, sprite RAM).
Сравнение — в родном разрешении 384×240 (поле без панели), по перьям ячеек ROM (index4):

- аркада — MAME m72_v.cpp (маски set_transmask, как m72_scene.py и M72HqRenderer): задний проход фона (BG_LAYER1) и
  переднего слоя (FG_LAYER1); спрайты там, где тайлы не закрывают (BG_PRIORITY у фона, FG_LAYER0 у переднего слоя);
  передний проход фона (BG_LAYER0) и переднего слоя (FG_LAYER0);
- порт — хост v30z80_host.asm: кольцо (весь фон, перо 0 непрозрачно), тайлы переднего слоя низкого прохода, спрайты,
  тайлы высокого прохода фона и переднего слоя. Проход тайла — PASS_TABLE по группе атрибута (биты 6, 7), ячейка
  целиком; перо 0 переднего слоя прозрачно всегда, фона в высоком проходе — по ключу --bg-pen0.

Источник пикселя: 1 — фон, 2 — передний слой, 3 — спрайт. Расхождения считаются парами «аркада → порт»: спрайт
виден зря (1→3, 2→3), спрайт спрятан зря (3→1, 3→2), тайлы не в том порядке (1↔2). Итог — JSON по кадрам и этапам и
картинки худших кадров (--png): красный — спрайт виден зря, синий — спрятан зря, жёлтый — порядок тайлов, серые —
источник аркады.

Запуск: vdac2p_priority_audit.py --frames 70000 --every 10 [--pass-table 0111,0101] [--bg-pen0 opaque|transparent]
[--json файл] [--png каталог] [--invincible --autofire 400 | --random N].
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python'):
    sys.path.insert(0, str(extra))

import v30z80  # noqa: E402,F401  (до numpy: порядок импорта numba)
import numpy as np  # noqa: E402

FIELD_H, FIELD_W = 240, 384
# set_transmask(группа, маска прохода): бит пера = 1 — перо прозрачно (MAME m72_v.cpp; m72_scene.py).
FG_LAYER0 = (0xFFFF, 0x00FF, 0x0001, 0x0001)
FG_LAYER1 = (0x0001, 0xFF01, 0xFFFF, 0xFFFF)
BG_PRIORITY = (0xFFFF, 0x00FF, 0x0001, 0x0001)
BG_LAYER0 = (0xFFFF, 0x00FF, 0xFFFF, 0x0001)
BG_LAYER1 = (0x0000, 0xFF00, 0x0000, 0xFFFE)
CATEGORIES = {(1, 3): 'спрайт виден поверх фона', (2, 3): 'спрайт виден поверх переднего слоя',
              (3, 1): 'спрайт спрятан фоном', (3, 2): 'спрайт спрятан передним слоем',
              (1, 2): 'передний слой вместо фона', (2, 1): 'фон вместо переднего слоя'}


def load_pens(name: str, size: int) -> np.ndarray:
    """Перья ячеек ROM (index4: два пера в байте, старшее первым) → (коды, size, size)."""
    raw = np.fromfile(ROOT / 'Assets' / 'Converted' / 'Arcade' / f'RTYPE_{name}_INDEX4.bin', dtype=np.uint8)
    pens = np.empty(raw.size * 2, dtype=np.uint8)
    pens[0::2] = raw >> 4
    pens[1::2] = raw & 15
    return pens.reshape(-1, size, size)


def drawn(masks: tuple, group: np.ndarray, pen: np.ndarray) -> np.ndarray:
    """Перо рисуется маской прохода своей группы: бит пера в маске = 0."""
    table = np.array(masks, dtype=np.int32)[group]
    return ((table >> pen.astype(np.int32)) & 1) == 0


def layer_pixels(vram: bytes, pens: np.ndarray, scroll_x: np.ndarray, scroll_y: np.ndarray):
    """Перо и группа пикселя слоя на поле 240×384 по построчному скроллу (как m72_scene.tile_pixel)."""
    words = np.frombuffer(vram, dtype='<u2')
    x = np.arange(FIELD_W)[None, :]
    y = np.arange(FIELD_H)[:, None]
    u = (x + 64 + scroll_x[:, None]) & 511
    v = (y + 128 + scroll_y[:, None]) & 511
    tile = (v >> 3) * 64 + (u >> 3)
    code = words[tile * 2].astype(np.int32)
    attr = words[tile * 2 + 1].astype(np.int32)
    px = np.where(code & 0x4000, 7 - (u & 7), u & 7)
    py = np.where(code & 0x8000, 7 - (v & 7), v & 7)
    pen = pens[(code & 0x3FFF) % len(pens), py, px]
    return pen, (attr >> 6) & 3


def sprite_opaque(spriteram: bytes, pens: np.ndarray) -> np.ndarray:
    """Непрозрачные пиксели спрайтов на поле (разбор sprite RAM как MAME m72 draw_sprites / M72HqRenderer)."""
    words = np.frombuffer(spriteram, dtype='<u2').astype(np.int32)
    out = np.zeros((FIELD_H, FIELD_W), dtype=bool)
    offset = 0
    while offset < len(words):
        attribute = int(words[offset + 2])
        width = 1 << ((attribute >> 14) & 3)
        height = 1 << ((attribute >> 12) & 3)
        code = int(words[offset + 1])
        flip_x, flip_y = bool(attribute & 0x0800), bool(attribute & 0x0400)
        native_x = -256 + (int(words[offset + 3]) & 0x3FF) - 64
        native_y = 384 - (int(words[offset]) & 0x1FF) - 16 * height
        for cell_x in range(width):
            for cell_y in range(height):
                cell = code + 8 * (width - 1 - cell_x if flip_x else cell_x) + (height - 1 - cell_y if flip_y else cell_y)
                block = pens[cell & 0x0FFF]
                if flip_y:
                    block = block[::-1]
                if flip_x:
                    block = block[:, ::-1]
                left, top = native_x + 16 * cell_x, native_y + 16 * cell_y
                x0, y0 = max(0, left), max(0, top)
                x1, y1 = min(FIELD_W, left + 16), min(FIELD_H, top + 16)
                if x0 < x1 and y0 < y1:
                    out[y0:y1, x0:x1] |= block[y0 - top:y1 - top, x0 - left:x1 - left] != 0
        offset += width * 4
    return out


def audit(state, tiles0, tiles1, sprites, pass_table, bg_pen0_transparent: bool):
    """Источник пикселя у аркады и у порта (1 — фон, 2 — передний слой, 3 — спрайт)."""
    rows = np.array(state.row_scroll[:FIELD_H], dtype=np.int32)
    fg_pen, fg_group = layer_pixels(state.vram0, tiles0, rows[:, 0], rows[:, 1])
    bg_pen, bg_group = layer_pixels(state.vram1, tiles1, rows[:, 2], rows[:, 3])
    sprite = sprite_opaque(state.spriteram, sprites)
    arcade = np.zeros((FIELD_H, FIELD_W), dtype=np.uint8)
    arcade[drawn(BG_LAYER1, bg_group, bg_pen)] = 1
    arcade[drawn(FG_LAYER1, fg_group, fg_pen)] = 2
    blocked = drawn(BG_PRIORITY, bg_group, bg_pen) | drawn(FG_LAYER0, fg_group, fg_pen)
    arcade[sprite & ~blocked] = 3
    arcade[drawn(BG_LAYER0, bg_group, bg_pen)] = 1
    arcade[drawn(FG_LAYER0, fg_group, fg_pen)] = 2
    port = np.ones((FIELD_H, FIELD_W), dtype=np.uint8)            # кольцо: весь фон
    fg_high = np.array(pass_table[0])[fg_group] == 1
    bg_high = np.array(pass_table[1])[bg_group] == 1
    port[~fg_high & (fg_pen != 0)] = 2
    port[sprite] = 3
    port[bg_high & ((bg_pen != 0) | (not bg_pen0_transparent))] = 1
    port[fg_high & (fg_pen != 0)] = 2
    return arcade, port


def picture(arcade: np.ndarray, port: np.ndarray):
    from PIL import Image
    grey = np.array([(0, 0, 0), (60, 60, 60), (120, 120, 120), (200, 200, 200)], dtype=np.uint8)
    image = grey[arcade].copy()
    image[(arcade != 3) & (port == 3)] = (255, 40, 40)
    image[(arcade == 3) & (port != 3)] = (60, 120, 255)
    image[(arcade != port) & (arcade != 3) & (port != 3)] = (255, 220, 0)
    return Image.fromarray(image).resize((FIELD_W * 2, FIELD_H * 2), Image.NEAREST)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=70000)
    parser.add_argument('--every', type=int, default=10)
    parser.add_argument('--pass-table', default='0111,0101', help='PASS_TABLE хоста: передний слой, фон (по группам)')
    parser.add_argument('--bg-pen0', choices=('opaque', 'transparent'), default='opaque',
                        help='перо 0 фона в высоком проходе порта')
    parser.add_argument('--keys', default='330:331:space')
    parser.add_argument('--autofire', type=int, default=None)
    parser.add_argument('--invincible', action='store_true')
    parser.add_argument('--random', type=int, default=None)
    parser.add_argument('--json', default='')
    parser.add_argument('--png', default='')
    parser.add_argument('--png-count', type=int, default=12)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    pass_table = [[int(c) for c in part] for part in args.pass_table.split(',')]
    tiles0, tiles1, sprites = load_pens('TILES0', 8), load_pens('TILES1', 8), load_pens('SPRITES', 16)

    import pygame
    pygame.init()
    pygame.display.set_mode((640, 480))
    import p2c_runtime_app
    from p2c_entry_runtime import RuntimeApp
    from rtype_port.title import TitleAssets
    from rtype_check import InputMirror, apply_mouse, install_keys_double, schedule

    class Port(p2c_runtime_app.MachinePort):
        def __init__(self) -> None:
            super().__init__()
            self.state = None
            self.mirror = None

        def boot(self) -> None:
            super().boot()
            install_keys_double(self.machine, self.mirror)     # шаг клавиш ×2 (Esc), как у машины Z80

        def step(self, mask, start1, coin1, render) -> None:
            from v30z80.scenario import Scenario
            Scenario.apply(self.machine, mask, bool(start1), bool(coin1))
            self.state = self.machine.step_frame()
            self.calls.append(('step', mask, 0, 0, None))

        def mouse(self) -> None:
            self.game_frame = True                              # кадр игры игрока — экран «игра» для Esc
            dx, dy = self.mirror.mouse_dx, self.mirror.mouse_dy
            if dx or dy:
                apply_mouse(self.machine, dx, dy)

    port = Port()
    mirror = InputMirror()
    port.mirror = mirror
    app = RuntimeApp(TitleAssets(), port)
    surface = pygame.Surface((640, 480))
    script = [(int(a), int(b), key) for a, b, key in (item.split(':') for item in args.keys.split(',') if item)]
    import random
    rng = random.Random(args.random) if args.random is not None else None
    held: set[str] = set()
    rows = []
    totals: dict = {}
    by_stage: dict = {}
    worst: list = []
    png = Path(args.png) if args.png else None
    if png:
        png.mkdir(parents=True, exist_ok=True)
    for frame in range(1, args.frames + 1):
        keys = schedule(frame, script)
        if args.autofire is not None and frame >= args.autofire and frame % 8 < 4:
            keys.add('space')
        if args.invincible and frame >= 2 and port.machine is not None:
            port.machine.cpu.mem_write(0x42FC6, b'\x01')
        if rng is not None:
            if rng.random() < 0.05:
                held = set(rng.sample(['q', 'a', 'o', 'p', 'space', 'altgr', 'enter', 'rmb', 'lmb', 'mmb', 'mouse_up',
                                       'mouse_right', 'mouse_down', 'mouse_left', 'joy_fire', 'joy_force', 'joy_start',
                                       'joy_up', 'joy_right', 'joy_down', 'joy_left'], rng.randrange(0, 3)))
            keys |= held
        events, buttons = mirror.frame(keys)
        port.game_frame = False
        app.frame(events, buttons, surface)
        mirror.end_frame(any(call[0] == 'show' for call in port.calls), port.game_frame)   # экран кадра для Esc
        port.calls.clear()
        if frame % args.every or port.state is None or port.state.video_off:
            continue
        arcade, ported = audit(port.state, tiles0, tiles1, sprites, pass_table, args.bg_pen0 == 'transparent')
        counts = {}
        for (a, b), _name in CATEGORIES.items():
            number = int(((arcade == a) & (ported == b)).sum())
            if number:
                counts[f'{a}{b}'] = number
        stage = int(bytes(port.machine.cpu.mem_read(0x42FCD, 1))[0])
        rows.append([frame, stage, counts])
        for key, number in counts.items():
            totals[key] = totals.get(key, 0) + number
            stage_counts = by_stage.setdefault(stage, {})
            stage_counts[key] = stage_counts.get(key, 0) + number
        sprite_errors = sum(counts.get(key, 0) for key in ('13', '23', '31', '32'))
        if png and sprite_errors:
            worst.append((sprite_errors, frame))
            worst.sort(reverse=True)
            if len(worst) > args.png_count:
                dropped = worst.pop()
                old = png / f'prio_{dropped[1]:05d}.png'
                if old.exists():
                    old.unlink()
            if (sprite_errors, frame) in worst:
                picture(arcade, ported).save(png / f'prio_{frame:05d}.png')
        if frame % 5000 == 0:
            print(f'кадр {frame}: этап {stage}, итог {totals}', flush=True)
    audited = len(rows)
    print(f'проверено кадров: {audited} (каждый {args.every}-й из {args.frames}); PASS_TABLE {args.pass_table}, перо 0 '
          f'фона в высоком проходе — {args.bg_pen0}')
    for key, name in ((f'{a}{b}', name) for (a, b), name in CATEGORIES.items()):
        frames_with = sum(1 for row in rows if key in row[2])
        print(f'  {name}: пикселей {totals.get(key, 0)}, кадров {frames_with}')
    for stage in sorted(by_stage):
        print(f'  этап {stage}: ' + ', '.join(f'{CATEGORIES[(int(k[0]), int(k[1]))]} {v}'
                                             for k, v in sorted(by_stage[stage].items())))
    if args.json:
        Path(args.json).write_text(json.dumps({'rows': rows, 'totals': totals, 'by_stage': by_stage},
                                              ensure_ascii=False) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
