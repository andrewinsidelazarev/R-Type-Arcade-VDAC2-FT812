"""Проверка SPG порта на модели: цикл app.main (код p2c) с машиной World ROM (v30z80) и VDAC2.

Z80 (модель TS-Config) исполняет раскладку rtype_vdac2.spg с состояния после загрузчика; ввод —
клавиши ZX по сценарию. Параллельно CPython исполняет тот же цикл (p2c_entry_runtime.RuntimeApp
с эталонной машиной M72) с теми же событиями ввода (зеркало адаптера p2c_z80_runtime_cold.c).
Конец кадра Z80 — p2c_z80_hook. Каждый кадр сравнивается число показанных display list; на
выбранных кадрах картинка модели FT812 сравнивается с эталоном: кадр титула — поверхность
pygame, кадр игры — M72HqRenderer последнего шага; --png сохраняет пары. Пак уровней с ячейками
графики и потоками мелодий машина читает с модели SD-карты (образ --sd, как в v30z80_video_check).
Звук: команды мелодий эталонной машины идут в rtype_port.audio.TurboSoundFm (микшер-заглушка, записи
портов TSFM — журнал), шаг кадра звука — после кадра, как в app.main; каждый кадр сравниваются записи
событий потока (точка SOUND_EVENT_HOOK звукового адаптера) и состояние: текущая мелодия, владелец,
затухание, наличие потока.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import v30z80  # noqa: E402,F401
from p2c_z80_check import TSConfModel  # noqa: E402

MACHINE = ROOT / 'Build' / 'V30Z80'
P2C = ROOT / 'Build' / 'P2cRuntime'


class InputMirror:
    """Зеркало p2c_z80_runtime_cold.c: события кадра и кнопки игры из нажатых клавиш PS/2 (v30z80_ft812.PS2_CODES:
    клавиши ZX по именам, стрелки «right», «left», «down», «up», правый Alt «altgr» — игра с 28.09.2026 берёт клавиши
    только из очереди скан-кодов AVR, p2c_ft_keyboard), кнопок мыши («lmb», «rmb», «mmb»); движение мыши
    («mouse_right», «mouse_left», «mouse_down», «mouse_up» — MOUSE_COUNTS отсчётов за кадр, как у модели v30z80_ft812) —
    смещение кадра mouse_dx / mouse_dy (вправо и вверх — плюс) для вызова машины 9; средняя кнопка по фронту нажатия
    переключает чувствительность 1 ↔ 1/2 (при 1/2 смещение делится пополам с переносом остатка оси, как
    p2c_rt_mouse_scale). Нажатие Esc («esc», p2c_kb_esc) — по экрану прошлого кадра screen (p2c_rt_screen, его
    ставит end_frame): на титуле переключает развёртку 59 ↔ 55 Гц (vsync55: у машины и эталона следов нет, только
    регистр FT812 и надпись титула), в игре — шаг R-9 от клавиш и джойстика ×1 ↔ ×2 (keys_double, p2c_rt_keys_double;
    эталону его прибавляют ловушки install_keys_double), в демо — только пробуждение."""

    MOUSE_JUMP = 63

    def __init__(self) -> None:
        self.ps2_previous: set[str] = set()        # клавиши PS/2 прошлого кадра
        self.fire_previous = False
        self.force_previous = False
        self.start_previous = False                # восьмая кнопка Kempston прошлого кадра
        self.blocked = 0
        self.mouse_ready = False
        self.mouse_dx = 0
        self.mouse_dy = 0
        self.mouse_half = False
        self.mmb_previous = False
        self.mouse_rest = [0, 0]
        self.keys_double = False                   # шаг клавиш и джойстика ×2 (Esc в игре)
        self.vsync55 = False                       # развёртка 55 Гц (Esc на титуле)
        self.screen = 0                            # экран прошлого кадра: 0 — титул, 1 — демо, 2 — игра

    def frame(self, keys: set[str]):
        from p2c_entry_runtime import FrameEvents, GameButtons
        from v30z80_ft812 import MOUSE_COUNTS, PS2_CODES
        ps2 = {name for name in keys if name in PS2_CODES}
        wake = bool(ps2 - self.ps2_previous)       # нажата клавиша PS/2 (p2c_kb_wake)
        if 'esc' in ps2 and 'esc' not in self.ps2_previous:   # нажатие Esc (p2c_kb_esc)
            if self.screen == 0:
                self.vsync55 = not self.vsync55
            elif self.screen == 2:
                self.keys_double = not self.keys_double
        mmb = 'mmb' in keys
        if mmb and not self.mmb_previous:
            self.mouse_half = not self.mouse_half
            self.mouse_rest = [0, 0]
        self.mmb_previous = mmb
        self.mouse_dx = self.mouse_dy = 0
        if self.mouse_ready:
            dx = MOUSE_COUNTS * (('mouse_right' in keys) - ('mouse_left' in keys))
            dy = MOUSE_COUNTS * (('mouse_up' in keys) - ('mouse_down' in keys))
            deltas = [dx if abs(dx) <= self.MOUSE_JUMP else 0, dy if abs(dy) <= self.MOUSE_JUMP else 0]
            if self.mouse_half:
                for axis in range(2):
                    total = deltas[axis] + self.mouse_rest[axis]
                    deltas[axis] = total >> 1              # арифметический сдвиг — округление вниз, как SRA
                    self.mouse_rest[axis] = total & 1
            self.mouse_dx, self.mouse_dy = deltas
        self.mouse_ready = True
        fire = bool({'space', 'enter', 'lmb', 'joy_fire'} & keys)     # Space, Enter, ЛКМ, Kempston
        force = bool({'altgr', 'rmb', 'joy_force'} & keys)             # правый Alt, ПКМ, бит 5 Kempston
        start = 'joy_start' in keys                 # бит 7 Kempston — только старт игры
        if fire and not self.fire_previous:
            wake = True
        bits = 0
        if {'right', 'p', 'joy_right'} & keys:     # стрелки и P O A Q — как p2c_kb_moves
            bits |= 1
        if {'left', 'o', 'joy_left'} & keys:
            bits |= 2
        if {'down', 'a', 'joy_down'} & keys:
            bits |= 4
        if {'up', 'q', 'joy_up'} & keys:
            bits |= 8
        held =(16 if fire else 0) | (32 if force else 0)
        self.blocked &= held
        bits |= held & ~self.blocked
        fire_new = fire and not self.fire_previous
        start_new = start and not self.start_previous
        if fire_new:
            bits |= 16
        if force and not self.force_previous:
            bits |= 32
        # Клавиш монеты и старта системы у порта нет (управление CLAUDE.md): system_start и coin всегда False.
        # Бит 7 Kempston стартует игру наравне с огнём, но в кнопки игры и в пробуждение демо не идёт.
        events = FrameEvents(title_start=bool(fire_new or start_new), system_start=False, coin=False,
                             demo_wake=wake)
        buttons = GameButtons(right=bool(bits & 1), left=bool(bits & 2), down=bool(bits & 4), up=bool(bits & 8),
                              fire=bool(bits & 16), force=bool(bits & 32))
        self.ps2_previous = ps2
        self.fire_previous = fire
        self.force_previous = force
        self.start_previous = start
        return events, buttons

    def clear(self) -> None:
        self.blocked = 48

    def end_frame(self, shown: bool, game: bool) -> None:
        """Экран кадра для Esc следующего (p2c_rt_frame_end): кадр не показывала машина — показан список титула (0);
        показала — с ходом игрока (MachinePort.mouse) игра (2), без него демо (1)."""
        self.screen = (2 if game else 1) if shown else 0


# Оси R-9 для мыши (ApiMouse, v30z80_runtime.asm): адрес дробного байта позиции 24 бита Q8, пикселей M72 на отсчёт
# в Q8, рамки целой части обработчика $2027.
MOUSE_AXES = ((0x40023, 307, 0x015C, 0x02A0), (0x40027, 273, 0x009A, 0x0174))


RING_HANDLE = 14                 # Build/V30Z80/rtype_ring.inc: handle кольца фона
RING_LUT = 0x099A80              # там же: 256 записей палитры кольца в RAM_G
RING_BASE = 0x079A80             # там же: кольцо 512×256 текселей PALETTED4444 (байт на тексел)
RING_BYTES = 512 * 256
CELL_BASE = 0x004000             # Build/V30Z80/video.inc: пул ячеек тайлов (CELLS по TILE_CELL_BYTES)
CELL_BYTES = 96 * 420


def signed(value: int, bits: int) -> int:
    """Поле команды FT812 в дополнительном коде → целое со знаком."""
    return value - (1 << bits) if value >> (bits - 1) & 1 else value


def ring_visible_digest(words: list[int], dl: bytes, ram_g, cells_free: bool = False, exact: bool = False) -> str:
    """Хеш вывода кадра «видимое | всё»: слева — список FT812, RAM_G вне кольца фона и только те тексели кольца,
    которые выбирают его полосы; справа — прежний хеш списка и всей RAM_G.

    VDAC2+ откладывает запись столбцов кольца вне поля зрения (RingDefer, RingCatchUp в v30z80_ring.asm): RAM_G
    кольца там отличается от сборки без отложенной записи, а видимое совпадать обязано. Полоса — блок RingEmit:
    BITMAP_HANDLE кольца, BITMAP_SOURCE = RING_BASE, затем до VERTEX2F — размер и матрица. Тексели полосы:
    u = (A·x + C) >> 8 для 1024 пикселей строки, v = (E·y + F) >> 8 для высоты BITMAP_SIZE, повтор 512×256;
    запас в тексел с каждой стороны покрывает правило центра пикселя растеризатора (строже, не мягче).
    exact — без запаса: выборка по центрам пикселей ((2A·x + A + 2C) >> 9, (2E·y + E + 2F) >> 9) — правило, под
    которое рассчитаны матрицы вывода (RingEmit, ячейки и картинки хоста). Запас в тексел захватывал столбец за краем
    экрана, чья запись зависит от бюджета перестройки невидимых групп (ложные расхождения при ранней подгрузке ячеек,
    2026-09-23).
    """
    import numpy as np
    ring = np.frombuffer(bytes(ram_g[RING_BASE:RING_BASE + RING_BYTES]), dtype=np.uint8).reshape(256, 512)
    visible = hashlib.sha256(dl[:len(words) * 4])
    if cells_free:
        # Пул ячеек тайлов — только источники сборки картинок и полос (список кадра на него не ссылается): ранняя
        # подгрузка ячеек (была 23.09, снята 24.09) меняла его содержимое и занятость, а не вывод.
        visible.update(bytes(ram_g[:CELL_BASE]))
        visible.update(bytes(ram_g[CELL_BASE + CELL_BYTES:RING_BASE]))
    else:
        visible.update(bytes(ram_g[:RING_BASE]))
    visible.update(bytes(ram_g[RING_BASE + RING_BYTES:]))
    bands = 0
    for index, word in enumerate(words):
        if word != 0x05000000 | RING_HANDLE or index + 1 >= len(words) or words[index + 1] != 0x01000000 | RING_BASE:
            continue
        state = {}
        for command in words[index + 2:]:
            if command >> 30 == 1:                      # VERTEX2F — полоса нарисована
                break
            state[command >> 24] = command & 0xFFFFFF
        else:
            raise AssertionError('блок кольца без VERTEX2F')
        height = ((state[0x29] & 3) << 9) | (state[0x08] & 0x1FF)
        a, e = signed(state[0x15] & 0x1FFFF, 17), signed(state[0x19] & 0x1FFFF, 17)
        c, f = signed(state[0x17], 24), signed(state[0x1A], 24)
        xs = np.arange(1024, dtype=np.int64)
        ys = np.arange(height, dtype=np.int64)
        us = (a * xs + c) >> 8
        vs = (e * ys + f) >> 8
        if exact:
            us = np.unique(((2 * a * xs + a + 2 * c) >> 9) & 511)
            vs = np.unique(((2 * e * ys + e + 2 * f) >> 9) & 255)
        else:
            us = np.unique(np.concatenate((us - 1, us, us + 1)) & 511)
            vs = np.unique(np.concatenate((vs - 1, vs, vs + 1)) & 255)
        visible.update(ring[np.ix_(vs, us)].tobytes())
        bands += 1
    visible.update(bytes([bands]))
    whole = hashlib.sha256(dl[:len(words) * 4] + bytes(ram_g)).hexdigest()
    return f'{visible.hexdigest()}|{whole}'


def ring_audit(words: list[int], ram_g) -> tuple[bool, int, bool]:
    """Кадр без очистки безопасен? → (есть очистка, строк под кольцом во всю ширину, палитра непрозрачна).

    Очистку кадра из заголовка списка сняли: кольцо фона непрозрачно (альфа 15 у всех записей палитры —
    `RingService` и `RingLutPen` пишут её с `or #F0`) и полосами закрывает все 768 строк, поэтому CLEAR
    под ним не виден, а стоит 128 тактов каждой строке развёртки. Здесь это проверяется покадрово.
    Список разбирает `ft812_line_cost.parse`: он исполняет JUMP/CALL/RETURN, как сам растеризатор, —
    линейный проход считал бы состоянием тела подпрограмм и давал ложные срабатывания.
    """
    import ft812_line_cost as cost
    _commands, primitives = cost.parse(list(words), {}, None)
    covered = bytearray(768)
    clear = False
    ring = f'handle {RING_HANDLE}'
    for first, last, width, kind, _left in primitives:
        if kind == 'очистка':
            clear = True
        elif kind == ring and width >= cost.WIDTH:
            for line in range(max(0, first), min(768, last)):
                covered[line] = 1
    lut = ram_g[RING_LUT:RING_LUT + 512]
    opaque = all(lut[index * 2 + 1] >= 0xF0 for index in range(256))
    return clear, sum(covered), opaque


def drawn_digest(ft, skip_sprite_b: bool = False) -> str:
    """Хеш вывода кадра «нарисованное | всё»: слева — только то, что рисует показанный список, как его исполняет
    растеризатор модели (v30z80_ft812.Ft812Model.render: CALL/JUMP/RETURN, состояние handle, матрица, сдвиг,
    ножницы, палитра): для каждой вершины BITMAPS — параметры вывода, байты ячейки битмапа (BITMAP_SOURCE + ячейка
    · шаг · высота) и таблица палитры PALETTED4444; у кольца фона (повтор 512×256) — только тексели, которые выбирают
    пиксели по центрам (как ring_visible_digest с exact). Очистки и цвет очистки — тоже. Справа — хеш списка и всей
    RAM_G. Не зависит от того, в каких слотах пулов лежат картинки, полосы и ячейки и что лежит в невидимых
    (ранняя подгрузка ячеек и ранняя сборка строк меняют сроки перестройки невидимых групп, 2026-09-23); сверено с
    --render-hash. Сроки выделения в полном пуле картинок меняют и то, какой класс пойдёт полосами (швы тайлов чуть
    иные), — такие кадры собирает --dl-continue. skip_sprite_b (--drawn-no-sprite-b): вершины прохода B спрайтов в
    основной части списка — ячеек (handle SPRITE_HANDLE_B и + 1) и объектов (нечётные ячейки handle классов объектов,
    vdac2p_objects.asm) — в хеш не идут: сверка защиты строки FT812 (vdac2p_guard.asm), в перегруженном кадре она
    выбрасывает только их."""
    import copy
    import struct
    import numpy as np
    from v30z80_ft812 import RAM_G_SIZE, RAM_DL_SIZE, PALETTED4444, ARGB4
    from v30z80_video_assets import STRIP_HANDLE_B, IMAGE_HANDLE_B, PASS_B_ROWS, SPRITE_HANDLE_B, OBJ_CLASS_HANDLES
    pass_b_aliases = (STRIP_HANDLE_B, IMAGE_HANDLE_B)
    sprite_b = (SPRITE_HANDLE_B, SPRITE_HANDLE_B + 1) if skip_sprite_b else ()
    object_b = set(OBJ_CLASS_HANDLES) if skip_sprite_b else set()
    pending_b: list[bytes] = []
    handles = copy.deepcopy(ft.handles)
    ram_g = ft.ram_g
    out = hashlib.sha256()
    words = [struct.unpack_from('<I', ft.shown_dl, offset)[0] for offset in range(0, RAM_DL_SIZE, 4)]
    scissor = [0, 0, 1024, 768]
    handle = cell = palette = primitive = 0
    translate = [0, 0]
    vertex_shift = 4
    transform = [256, 0, 0, 0, 256, 0]
    clear_color = 0
    pc, stack, steps = 0, [], 0
    while pc < len(words) and steps < 20000:
        word = words[pc]
        pc += 1
        steps += 1
        if word == 0:
            break
        opcode = word >> 24
        if opcode == 0x1D:
            stack.append(pc)
            pc = word & 0xFFFF
            continue
        if opcode == 0x1E:
            pc = word & 0xFFFF
            continue
        if opcode == 0x24:
            if not stack:
                break
            pc = stack.pop()
            if not stack:
                for record in pending_b:            # проход B подпрограммы слоя — после её прохода A
                    out.update(record)
                pending_b.clear()
            continue
        kind = word >> 30
        if kind in (1, 2):
            if kind == 2:
                x = ((word >> 21) & 511) * 16
                y = ((word >> 12) & 511) * 16
                draw_handle, draw_cell = (word >> 7) & 31, word & 127
            else:
                x = (word >> 15) & 0x7FFF
                y = word & 0x7FFF
                x = (x - 0x8000 if x & 0x4000 else x) << (4 - vertex_shift) if vertex_shift <= 4 else 0
                y = (y - 0x8000 if y & 0x4000 else y) << (4 - vertex_shift) if vertex_shift <= 4 else 0
                draw_handle, draw_cell = handle, cell
            if primitive != 1:
                continue
            if not stack and (draw_handle in sprite_b or (draw_handle in object_b and draw_cell & 1)):
                continue                            # проход B спрайтов — не в хеш (--drawn-no-sprite-b)
            # Проход B полос и картинок handle-псевдонимом (VDAC2+, 2026-09-24): его вершина идёт в подпрограмме слоя
            # сразу за вершиной прохода A, а раньше подпрограмма вызывалась второй раз при F = 30·256. Хеш — как у
            # прежнего вывода: вершина псевдонима считается вершиной основного handle при F + 30·256 и дописывается
            # после возврата из подпрограммы (порядок «весь проход A, затем весь B»); сам псевдоним сверяется с
            # основным handle — всё то же, источник на PASS_B_ROWS строк дальше.
            alias = draw_handle in pass_b_aliases and bool(stack)
            view = transform
            record = bytearray()
            if alias:
                main_state, own = handles[draw_handle - 2], handles[draw_handle]
                if (any(own[key] != main_state[key] for key in main_state if key != 'source') or
                        own['source'] != main_state['source'] + PASS_B_ROWS * main_state['stride']):
                    record += b'alias-mismatch'
                draw_handle -= 2
                view = transform[:5] + [transform[5] + PASS_B_ROWS * 256]
            state = handles[draw_handle]
            record += struct.pack('<9i', x + translate[0], y + translate[1], state['format'], state['stride'],
                                  state['height'], state['width_px'], state['height_px'],
                                  state['wrapx'] * 2 + state['wrapy'], state['filter'])
            record += struct.pack('<6i4i', *view, *scissor)
            if state['format'] in (PALETTED4444, ARGB4) and state['stride'] and state['height']:
                if draw_handle == RING_HANDLE and state['source'] == RING_BASE:
                    a, c, e, f = view[0], view[2], view[4], view[5]
                    xs = np.arange(1024, dtype=np.int64)
                    ys = np.arange(state['height_px'], dtype=np.int64)
                    us = np.unique(((2 * a * xs + a + 2 * c) >> 9) & 511)
                    vs = np.unique(((2 * e * ys + e + 2 * f) >> 9) & 255)
                    ring = np.frombuffer(bytes(ram_g[RING_BASE:RING_BASE + RING_BYTES]),
                                         dtype=np.uint8).reshape(256, 512)
                    record += ring[np.ix_(vs, us)].tobytes()
                else:
                    size = state['stride'] * state['height']
                    base = state['source'] + draw_cell * size
                    block = bytes(ram_g[base:min(base + size, RAM_G_SIZE)]) if base < RAM_G_SIZE else b''
                    block += bytes(size - len(block))
                    # Только строки текселей, которые выбирают пиксели по центрам (как у кольца): у псевдонимов
                    # прохода B (handle ячейки со сдвигом источника на проход) раскладка выше рисуемого, и за строками
                    # прохода лежит проход A соседней ячейки пула — хеш зависел бы от соседа по слоту (2026-09-24).
                    e, f = view[4], view[5]
                    ys = np.arange(state['height_px'], dtype=np.int64)
                    vs = (2 * e * ys + e + 2 * f) >> 9
                    vs = np.unique(vs % state['height']) if state['wrapy'] else np.unique(vs)
                    stride = state['stride']
                    record += b''.join(block[v * stride:(v + 1) * stride] for v in vs.tolist()
                                       if 0 <= v < state['height'])
                if state['format'] == PALETTED4444:
                    record += bytes(ram_g[palette:palette + 512])
            if alias:
                pending_b.append(bytes(record))
            else:
                out.update(record)
            continue
        if opcode == 0x02:
            clear_color = word & 0xFFFFFF
        elif opcode == 0x26:
            out.update(struct.pack('<I5i', word, clear_color, *scissor))
        elif opcode == 0x1B:
            scissor[0], scissor[1] = (word >> 11) & 2047, word & 2047
        elif opcode == 0x1C:
            scissor[2], scissor[3] = (word >> 12) & 4095, word & 4095
        elif opcode == 0x05:
            handle = word & 31
        elif opcode == 0x06:
            cell = word & 127
        elif opcode == 0x01:
            handles[handle]['source'] = word & 0x3FFFFF
        elif opcode == 0x07:
            state = handles[handle]
            state['format'] = (word >> 19) & 31
            state['stride'] = (state['stride'] & ~1023) | ((word >> 9) & 1023)
            state['height'] = (state['height'] & ~511) | (word & 511)
        elif opcode == 0x28:
            state = handles[handle]
            state['stride'] = (state['stride'] & 1023) | (((word >> 2) & 3) << 10)
            state['height'] = (state['height'] & 511) | ((word & 3) << 9)
        elif opcode == 0x08:
            state = handles[handle]
            state['filter'] = (word >> 20) & 1
            state['wrapx'] = (word >> 19) & 1
            state['wrapy'] = (word >> 18) & 1
            state['width_px'] = (state['width_px'] & ~511) | ((word >> 9) & 511)
            state['height_px'] = (state['height_px'] & ~511) | (word & 511)
        elif opcode == 0x29:
            state = handles[handle]
            state['width_px'] = (state['width_px'] & 511) | (((word >> 2) & 3) << 9)
            state['height_px'] = (state['height_px'] & 511) | ((word & 3) << 9)
        elif 0x15 <= opcode <= 0x1A:
            value = word & 0xFFFFFF
            value = value - 0x1000000 if value & 0x800000 else value
            transform[opcode - 0x15] = value if opcode in (0x17, 0x1A) else (value & 0x1FFFF) - (
                0x20000 if value & 0x10000 else 0)
        elif opcode == 0x2A:
            palette = word & 0x3FFFFF
        elif opcode == 0x2B:
            value = word & 0x1FFFF
            translate[0] = value - 0x20000 if value & 0x10000 else value
        elif opcode == 0x2C:
            value = word & 0x1FFFF
            translate[1] = value - 0x20000 if value & 0x10000 else value
        elif opcode == 0x27:
            vertex_shift = word & 7
        elif opcode == 0x1F:
            primitive = word & 15
        else:
            out.update(struct.pack('<I', word))      # прочие команды (цвет, альфа, тег…) — как есть
    whole = hashlib.sha256(ft.shown_dl[:len(ft.words()) * 4] + bytes(ram_g)).hexdigest()
    return f'{out.hexdigest()}|{whole}'


def apply_mouse(machine, dx: int, dy: int) -> None:
    """Зеркало ApiMouse: смещение мыши кадра — к позиции R-9 со штатным обработчиком без автопилота, в рамки."""
    cpu = machine.cpu
    if int.from_bytes(bytes(cpu.mem_read(0x40020, 2)), 'little') != 0x2027 or bytes(cpu.mem_read(0x42FC1, 1))[0]:
        return
    for (address, scale, low, high), counts in zip(MOUSE_AXES, (dx, dy)):
        position = (int.from_bytes(bytes(cpu.mem_read(address, 3)), 'little') + counts * scale) & 0xFFFFFF
        integer = min(max(position >> 8, low), high)
        cpu.mem_write(address, ((integer << 8) | (position & 0xFF)).to_bytes(3, 'little'))


# Шаг R-9 от клавиш и джойстика ×2 (Esc, n2.NKeys2x): точки обработчика $2027 сразу после вызовов $0672 и $0689
# (линейные адреса IP $2102 и $2109 при CS = $0040) и смещение 24-битной координаты Q8 от BP (X — [bp+3], Y — [bp+7]).
KEYS_DOUBLE_POINTS = ((0x02502, 3), (0x02509, 7))
ATTRACT_DEMO_HANDLER = b'\x8B\x0A'       # обработчик директора [DS:0] = $0A8B — демо аттракта: ROM ведёт корабль записью


def install_keys_double(machine, mirror) -> None:
    """Зеркало n2.NKeys2x на эталоне: при шаге клавиш ×2 (mirror.keys_double) тот же шаг AX ещё раз прибавляется к
    координате — повторный $0672 / $0689 перед рамками поля; кроме демо аттракта и автопилота [$2FC1] (у Z80 он идёт
    переводом, без удвоения)."""
    from unicorn.unicorn_const import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BP, UC_X86_REG_SS

    def hook(uc, _address, _size, offset) -> None:
        if not mirror.keys_double or bytes(uc.mem_read(0x40000, 2)) == ATTRACT_DEMO_HANDLER or \
                uc.mem_read(0x42FC1, 1)[0]:
            return
        step = uc.reg_read(UC_X86_REG_AX)
        at = (uc.reg_read(UC_X86_REG_SS) << 4) + ((uc.reg_read(UC_X86_REG_BP) + offset) & 0xFFFF)
        value = int.from_bytes(bytes(uc.mem_read(at, 3)), 'little') + step - ((step & 0x8000) << 1)
        uc.mem_write(at, (value & 0xFFFFFF).to_bytes(3, 'little'))

    for address, offset in KEYS_DOUBLE_POINTS:
        machine.cpu.hook_add(UC_HOOK_CODE, hook, offset, address, address)


def schedule(frame: int, script: list[tuple[int, int, str]]) -> set[str]:
    keys = set()
    for first, last, key in script:
        if first <= frame <= last:
            keys.update(key.split('+'))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=900)
    parser.add_argument('--build', type=Path, default=MACHINE, help='каталог машины проверяемой сборки')
    parser.add_argument('--profile', type=int, default=0, help='шаг выборки PC в тактах (0 — без профиля)')
    parser.add_argument('--profile-from', type=int, default=400, help='первый кадр профиля')
    parser.add_argument('--procedures', default='', help='точная стоимость процедур с вложенными вызовами: имена через запятую')
    parser.add_argument('--ticks', default='', help='JSON: такты кадров и профиль')
    parser.add_argument('--dl-record', default='', help='JSON: хеши списка FT812 и RAM_G каждого кадра')
    parser.add_argument('--dl-compare', default='', help='сверить хеши вывода с прежней сборкой')
    parser.add_argument('--ring-visible', action='store_true',
                        help='хеши вывода «видимое | всё»: сверяется только видимая часть кольца фона')
    parser.add_argument('--drawn', action='store_true',
                        help='хеш вывода по тому, что рисуется: битмапы, их ячейки и палитры (без слотов пулов)')
    parser.add_argument('--drawn-no-sprite-b', action='store_true',
                        help='с --drawn: без вершин прохода B спрайтов (сверка защиты строки FT812)')
    parser.add_argument('--render-hash', default='',
                        help='«С:ПО» — в этих кадрах видимое в хеше вывода — отрисовка кадра моделью FT812 (медленно)')
    parser.add_argument('--ring-exact', action='store_true',
                        help='с --ring-visible: тексели кольца — точно те, что выбирают полосы (без запаса в тексел)')
    parser.add_argument('--cells-free', action='store_true',
                        help='с --ring-visible: видимое — без пула ячеек тайлов RAM_G (ранняя подгрузка ячеек)')
    parser.add_argument('--stage-log', default='', help='JSON: кадр смены этапа игры (слово ROM $2FCD)')
    parser.add_argument('--ring-audit', action='store_true',
                        help='каждый кадр: экран закрыт непрозрачным кольцом фона либо в списке есть очистка')
    parser.add_argument('--object-profile', action='store_true',
                        help='с --profile: такты по текущему объекту V30 (слово +0 записи по BP — обработчик)')
    parser.add_argument('--rebuild-log', default='',
                        help='JSON: полные перестройки строк карты (кадр, слой, строка, группа, 64 байта тайлов)')
    parser.add_argument('--object-log', default='',
                        help='JSON: записи sprite RAM на входе SpriteEntry (кадр, 8 байт) — повторяемость объектов')
    parser.add_argument('--sprite-trace', default='',
                        help='JSON: обращения SpriteCell по кадрам (палитра, код) — проигрыш политик кэша')
    parser.add_argument('--ft-load-log', default='',
                        help='JSON: нагрузка на FT812 по кадрам (байты SPI в RAM_G/RAM_DL/очередь, MEMCPY, INFLATE)')
    parser.add_argument('--hook-points', default='', help='метка[+смещение] через запятую: ловушки для --hook-log')
    parser.add_argument('--hook-log', default='', help='JSON: кадр, точка, A, HL, страница W3 в ловушках --hook-points')
    parser.add_argument('--dl-continue', default='',
                        help='с --dl-compare: не останавливаться на расхождении, кадры расхождений — в этот JSON')
    parser.add_argument('--image-log', default='',
                        help='JSON: входы ImageAlloc и удачные выделения по кадрам (отказы — класс полосами)')
    parser.add_argument('--load-log', default='',
                        help='JSON: подгрузки ячеек (CellEnsure.load) — кадр, набор·16 + палитра, код')
    parser.add_argument('--palette-log', default='',
                        help='JSON: сколько перьев палитр ROM меняется по кадрам (цена пересчёта LUT)')
    parser.add_argument('--dl-dump', default='', help='каталог: слова показанного display list кадров --dl-dump-frames')
    parser.add_argument('--dl-dump-light', action='store_true',
                        help='с --dl-dump: только слова показанного списка (цена строки по многим кадрам)')
    parser.add_argument('--dl-dump-pages', action='store_true',
                        help='с --dl-dump: ещё страница хоста и страницы видеоадаптера (сверка состояния хоста)')
    parser.add_argument('--dl-dump-frames', default='', help='кадры выгрузки display list через запятую')
    parser.add_argument('--cache-probe', default='', help='аудит кэша на кадрах первый:последний (включительно)')
    parser.add_argument('--keys', default='330:331:space',
                        help='нажатия «первый:последний:клавиши» через запятую (клавиши через +)')
    parser.add_argument('--render', default='1,100,320,340,400,600,800', help='кадры сравнения картинки')
    parser.add_argument('--png', default='')
    parser.add_argument('--budget', type=int, default=200_000_000)
    parser.add_argument('--trace', default='', help='«первый:последний» — печатать ввод и вызовы машины кадров')
    parser.add_argument('--random', type=int, default=None,
                        help='сид случайного ввода: удерживаемые клавиши игры меняются, огонь нажимается и отпускается')
    parser.add_argument('--sd', default=str(MACHINE / 'rtype_sd.img'), help='образ SD-карты с паком уровней')
    parser.add_argument('--autofire', type=int, default=None,
                        help='с этого кадра огонь (пробел) нажат 4 кадра из 8 — прохождение без игрока')
    parser.add_argument('--no-gs', action='store_true',
                        help='машина без платы General Sound: эффекты на AY, музыки нет '
                             '(сверка звука с эталоном отключается — у эталона плата есть)')
    parser.add_argument('--ay-log', default='', help='JSON: записи в порты AY по кадрам (с --no-gs)')
    parser.add_argument('--no-tsfm-check', action='store_true',
                        help='без эмуляции TSFM у эталона и без сверки мелодий: ymfm не освобождает буфер на каждый '
                             'вызов (утечка до 30 ГБ за 70 000 кадров) — так пошаговая сверка памяти V30 и картинки '
                             'проходит всю игру (2026-09-25)')
    parser.add_argument('--dump-work', default='',
                        help='«кадр:файл» — рабочее ОЗУ V30 (16 КБ) модели после шага этого кадра (разбор объектов)')
    parser.add_argument('--invincible', action='store_true',
                        help='только для прогона: неуязвимость записью DS:$2FC6 = 1 в обе машины перед каждым кадром')
    parser.add_argument('--collide-watch', default='',
                        help='JSON: записи в поля записей столкновений во время цикла списка объектов IRQ0 на эталоне '
                             '(rtype_collide_watch.py; вопрос кэша столкновений, 2026-09-26)')
    args = parser.parse_args()
    if args.profile < 0:
        parser.error('--profile должен быть неотрицательным')
    if args.cache_probe:
        try:
            cache_first, cache_last = map(int, args.cache_probe.split(':'))
        except ValueError:
            parser.error('--cache-probe: нужны первый:последний')
        if not 1 <= cache_first <= cache_last <= args.frames:
            parser.error('--cache-probe должен задавать непустой диапазон внутри 1…--frames')
    sys.stdout.reconfigure(encoding='utf-8')
    import numpy as np
    import pygame
    from v30z80_ft812 import Ft812Model
    from rtype_loader_check import sd_controller
    import p2c_runtime_app

    from v30z80 import snapshot
    spg = json.loads((args.build / 'rtype_spg.json').read_text(encoding='utf-8'))
    machine_report = json.loads((args.build / 'build_report.json').read_text(encoding='utf-8'))
    p2c = json.loads((P2C / 'build_report.json').read_text(encoding='utf-8'))
    pages = {}
    # RTYPE_PAGES_DIR — страницы машины другой сборки (сравнение с прежней: страницы из `spgbld -u`).
    pages_dir = Path(os.environ.get('RTYPE_PAGES_DIR', str(args.build / 'pages')))
    for page in spg['machine_pages'] + [spg['switch_page']]:
        path = pages_dir / f'page_{page:02x}.bin'
        if path.is_file():
            pages[page] = path.read_bytes()
    for page in spg['p2c_pages']:
        pages[page] = (P2C / 'pages' / f'page_{page:02x}.bin').read_bytes()
    zero = set(spg['zero_pages'])
    for page in zero:
        pages[page] = bytes(0x4000)
    model = TSConfModel(pages, zero, 7, general_sound=not args.no_gs)
    ay_writes: list[tuple[int, int, int]] = []      # (кадр, регистр, значение) для --ay-log
    gs_commands: list[tuple[int, int]] = []         # (кадр, команда) в порт платы GS
    if args.ay_log:
        # Плеер AY пишет регистр в #FFFD, значение в #BFFD — перехватываем прямо на выходе модели.
        model_output = model.output
        ay_register = [0]

        def output_with_ay(address: int, value: int) -> None:
            if address == 0xFFFD:
                ay_register[0] = value
            elif address == 0xBFFD:
                ay_writes.append((current_frame[0], ay_register[0], value))
            elif address & 0xFF == 0xBB:
                gs_commands.append((current_frame[0], value))
            model_output(address, value)
        model.output = output_with_ay
    model.map_all([p2c['page_resident'], p2c['page_data1'], p2c['page_data2'], p2c['first_bank']])
    sd, card = sd_controller(Path(args.sd))
    sd_reads_total = 0
    ft = Ft812Model(model, sd)
    stage_marks: list[dict] = []
    stage_seen = (-1, -1, -1, -1)
    dump_dir = Path(args.dl_dump) if args.dl_dump else None
    dump_frames = {int(v) for v in args.dl_dump_frames.split(',') if v.strip()} if dump_dir else set()
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
    cpu = model.cpu
    cpu.pc = p2c['entry']
    cpu.sp = 0x3FFF
    cpu.a = p2c['first_bank']
    symbols = p2c['symbols']
    hook = symbols['_p2c_z80_hook']
    fault = symbols['_p2c_raise']
    switch_call = symbols['_p2c_switch_call']
    # Команда после `ld (_p2c_port_result),de` в _p2c_switch_return: DE — результат вызова.
    switch_result = p2c['switch_return'] + 9
    show_entry = symbols['_p2c_port_show']
    reset_entry = symbols['_p2c_port_reset_session']
    machine_symbols = machine_report['symbols']
    profile_labels = {}
    # Файлы, подключаемые INCLUDE, — тоже (иначе их время ложится на последнюю метку перед ними; до 2026-09-25 так
    # защита строки и спрайты объектами числились за SpStripRow).
    for filename, page in (('v30z80_runtime.asm', -1), ('v30z80_flags.inc', -1), ('v30z80_kernels.asm', -1), ('v30z80_ring.asm', -1),
                           ('vdac2p_early.asm', -1), ('vdac2p_sprites.asm', -1), ('v30z80_host.asm', 0x0C),
                           ('v30z80_sound.asm', 0x5E), ('v30z80_gs.asm', 0x5E), ('v30z80_ay.asm', 0x5E),
                           ('vdac2p_native.asm', 0x4A), ('vdac2p_host2.asm', 0x4B), ('vdac2p_guard.asm', 0x4B),
                           ('vdac2p_objects.asm', 0x4B),
                                 ('vdac2p_sprclear.asm', 0x4B), ('vdac2p_palettes.asm', 0x4B), ('vdac2p_native_h2.asm', 0x4B)):
        source = (ROOT / 'Source' / 'ASM' / filename).read_text(encoding='utf-8')
        names = re.findall(r'^([A-Za-z_][\w]*):', source, flags=re.MULTILINE)
        profile_labels.setdefault(page, []).extend((machine_symbols[name], name) for name in names
                                                   if name in machine_symbols)
    # Метки загрузчика (своя страница в окне W2): без них промах ячейки в профиле — чёрный ящик.
    loader_report = json.loads((MACHINE / 'rtype_loader.json').read_text(encoding='utf-8'))
    profile_labels.setdefault(loader_report['loader_page'], []).extend(
        (address, name) for name, address in loader_report['symbols'].items()
        if isinstance(address, int) and '.' not in name and 0x8000 <= address < 0xC000)
    for labels in profile_labels.values():
        labels.sort()
    code_profile_labels = {}
    for key, page in machine_report['page_of'].items():
        code_profile_labels.setdefault(page, []).append((machine_symbols[f'A_{key}'], f'A_{key}'))
    for labels in code_profile_labels.values():
        labels.sort()
    profile = {}
    object_profile: dict[int, int] = {}
    profiling = False
    frame_ticks = []
    ring_bad: list[int] = []                 # кадры без очистки и без полного покрытия кольцом
    palette_rows: list[list[int]] = []       # по кадрам: [перьев банка 0, палитр банка 0,
                                             # перьев банка 1, палитр банка 1, палитр в списке кадра]
    palette_previous: list = [None, None]
    ring_cleared = 0                         # кадры, где очистка в списке есть
    dl_hashes = []
    expected_hashes = json.loads(Path(args.dl_compare).read_text(encoding='utf-8')) if args.dl_compare else None
    dl_mismatches: list[int] = []
    render_range = tuple(int(value) for value in args.render_hash.split(':')) if args.render_hash else None
    cache_range = [int(value) for value in args.cache_probe.split(':')] if args.cache_probe else None
    cache_probe = None
    cache_report = None

    def sample(ticks: int) -> None:
        if model.windows[0] == p2c['page_resident']:
            name = 'app/title'
        else:
            # Код в окне W2 (загрузчик пака) — метки своей страницы, а не резидента: иначе его время ложится на
            # последнюю метку резидента (SCRIPT_DY).
            if cpu.pc >= 0xC000:
                page = model.windows[3]
            elif cpu.pc >= 0x8000:
                page = model.windows[2]
            elif cpu.pc >= 0x4000:
                page = model.windows[1]
            else:
                page = -1 if model.windows[0] == machine_report['res_page'] else model.windows[0]
            labels = profile_labels.get(page, code_profile_labels.get(page, []))
            index = bisect.bisect_right(labels, (cpu.pc, '\uffff')) - 1
            name = labels[index][1] if index >= 0 else f'page_{page:02X}'
        profile[name] = profile.get(name, 0) + ticks
        # Только логика машины: вывод (страница хоста в W3), звук и оболочку к объектам не относим.
        if (args.object_profile and model.windows[0] == machine_report['res_page']
                and not (cpu.pc >= 0xC000 and model.windows[3] in (0x0C, sound_page))):
            # Текущий объект: BP V30 (V_BP в резиденте) → запись в рабочем ОЗУ $40000 (страница V30 #10);
            # слово +0 — текущий обработчик. Для кода не объектов BP случаен — такие выборки дают шум.
            bp = model.memory[machine_symbols['V_BP']] | (model.memory[machine_symbols['V_BP'] + 1] << 8)
            if bp < 0x3FFE:
                work = model.page_bytes(machine_report['v30_page_base'] + 0x10)
                handler = work[bp] | (work[bp + 1] << 8)
                object_profile[handler] = object_profile.get(handler, 0) + ticks
    sound_page = machine_report['sound_pages'][0]
    sound_hook = machine_symbols['SOUND_EVENT_HOOK']
    sound_events: list[tuple[int, int, int]] = []
    stops = (hook, fault, switch_call, switch_result, show_entry, reset_entry, sound_hook)
    # Вход p2c_app_frame (банк): события и кнопки кадра — байты стека SP+5 и SP+6.
    app_frame = symbols['_p2c_app_frame']
    trace = [int(value) for value in args.trace.split(':')] if args.trace else None
    if trace:
        stops += (app_frame & 0xFFFF,)
    # Подгрузка ячейки с SD: вход ветки .load в CellEnsure (страница хоста в окне W3). Номер ячейки и набор с
    # палитрой к этому месту уже записаны в CELL_CODE и CELL_SETPAL.
    load_hook = machine_symbols['CellEnsure.load'] if args.load_log else None
    # Пул картинок: вход ImageAlloc и удачный исход (.take); разность — отказы (класс строки идёт полосами).
    image_hooks = ((machine_symbols['ImageAlloc'], machine_symbols['ImageAlloc.take']) if args.image_log else ())
    image_events: dict[int, list[int]] = {}
    # --hook-log: точки «метка+смещение» (метки сборки, страница — окно W3 при исполнении) → кадр, A, HL.
    hook_points = {}
    for item in (args.hook_points.split(',') if args.hook_points else []):
        label, _, delta = item.partition('+')
        address = machine_symbols[label] + (int(delta, 0) if delta else 0)
        hook_points[address] = item
    hook_events: list = []
    image_states: list = []
    # Вход SpriteCell: HL — код ячейки, палитра — SPRITE_PALETTE (страница хоста в окне W3).
    cell_hook = machine_symbols['SpriteCell'] if args.sprite_trace else None
    # Полная перестройка строки: метка .changed в StripRowRebuild — TILE_TEMP уже держит 64 байта двух строк.
    rebuild_hook = machine_symbols['StripRowRebuild.changed'] if args.rebuild_log else None
    rebuild_events: list = []
    # Объект из нескольких ячеек: вход SpriteEntry, HL → 8 байт записи sprite RAM.
    object_hook = machine_symbols['SpriteEntry'] if args.object_log else None
    object_events: list = []
    for extra in (rebuild_hook, object_hook):
        if extra is not None:
            stops += (extra,)
    cell_events: list[tuple[int, int, int]] = []
    if cell_hook is not None:
        stops += (cell_hook,)
    load_events: list[tuple[int, int, int]] = []
    load_frame = [0]
    if load_hook is not None:
        stops += (load_hook,)
    stops += image_hooks
    stops += tuple(hook_points)
    for address in stops:
        cpu.set_breakpoint(address)
    procedure_profile = None
    if args.procedures:
        from z80_procedure_profile import ProcedureProfile
        locations = {name: (machine_report['res_page'] if page == -1 else page, address)
                     for page, labels in profile_labels.items() for address, name in labels}
        # Переведённые процедуры ROM (A_адрес) — на своих страницах кода.
        locations.update({name: (page, address) for page, labels in code_profile_labels.items()
                          for address, name in labels})
        procedure_profile = ProcedureProfile(model, {locations[name]: name for name in args.procedures.split(',')}, stops)

    def step_over() -> None:
        pc = cpu.pc
        cpu.clear_breakpoint(pc)
        cpu.ticks_to_stop = 1
        cpu.run()
        if procedure_profile:
            procedure_profile.clock += 1 - int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
        cpu.set_breakpoint(pc)

    def run_frame(calls: list) -> int:
        """Кадр Z80 до p2c_z80_hook; calls — вызовы машины в кодировке журнала MachinePort."""
        spent = 0
        while True:
            if procedure_profile:
                procedure_profile.observe()
            quantum = min(args.profile, args.budget - spent) if profiling else args.budget - spent
            cpu.ticks_to_stop = quantum
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            used = quantum - remaining
            spent += used
            if procedure_profile:
                procedure_profile.clock += used
            if profiling:
                sample(used)
            pc = cpu.pc
            if trace and pc == app_frame & 0xFFFF and model.windows[3] == app_frame >> 16:
                calls.append(['input', model.memory[cpu.sp + 5], model.memory[cpu.sp + 6],
                              bytes(model.memory[cpu.sp:cpu.sp + 12]).hex(' '), f'SP #{cpu.sp:04X}'])
            if pc == sound_hook and model.windows[3] == sound_page:
                sound_events.append((cpu.a, cpu.de & 0xFF, cpu.de >> 8))
            if rebuild_hook is not None and pc == rebuild_hook and model.windows[3] == 0x0C:
                base = machine_symbols['TILE_TEMP']
                # Причина и окно: ROW_FORCE (каскад или повтор), окно слоя (LayerWindow), остатки бюджетов,
                # RETRY_ANY, VIDEO_FORCE, скролл слоёв TOP_SCROLL (sy, sx слоя 0 и слоя 1).
                extra = {name: model.memory[machine_symbols[name]]
                         for name in ('ROW_FORCE', 'VIS_GROUPS', 'VIS_ROW', 'VIS_ROW2', 'VIS_ROWS2', 'TILE_LEFT',
                                      'LAZY_LEFT', 'CELL_LEFT', 'RETRY_ANY', 'VIDEO_FORCE')}
                scroll = machine_symbols['TOP_SCROLL']
                extra['scroll'] = [model.word(scroll + 2 * index) for index in range(4)]
                rebuild_events.append((load_frame[0], model.memory[machine_symbols['TILE_LAYER']],
                                       model.memory[machine_symbols['TILE_ROW']], model.memory[machine_symbols['TILE_GROUP']],
                                       bytes(model.memory[base:base + 64]).hex(), extra))
            if object_hook is not None and pc == object_hook and model.windows[3] == 0x0C:
                object_events.append((load_frame[0], bytes(model.memory[cpu.hl:cpu.hl + 8]).hex()))
            if cell_hook is not None and pc == cell_hook and model.windows[3] == 0x0C:
                cell_events.append((load_frame[0], model.memory[machine_symbols['SPRITE_PALETTE']], cpu.hl))
            if pc in hook_points:
                hook_events.append((load_frame[0], hook_points[pc], cpu.a, cpu.hl, model.windows[3]))
            if image_hooks and pc in image_hooks and model.windows[3] == 0x0C:
                image_events.setdefault(load_frame[0], [0, 0])[image_hooks.index(pc)] += 1
                if pc == image_hooks[0]:
                    # Состояние пула на входе ImageAlloc: занятые, со ссылками, отпущенные в этом кадре; ранняя сборка?
                    tiles = model.page_bytes(0xD4)
                    frame_now = model.memory[machine_symbols['VIDEO_FRAME']]     # резидент (VDAC2+, 2026-09-25)
                    entries = [tiles[0x2A00 + 40 * index:0x2A00 + 40 * index + 40] for index in range(53)]
                    free = sum(1 for e in entries if not e[39] or (not (e[36] | e[37]) and e[38] != frame_now))
                    image_states.append((load_frame[0], free, model.memory[machine_symbols['ROW_SPEC']]))
            if load_hook is not None and pc == load_hook and model.windows[3] == 0x0C:
                setpal = model.memory[machine_symbols['CELL_SETPAL']]
                code = model.memory[machine_symbols['CELL_CODE']] | (model.memory[machine_symbols['CELL_CODE'] + 1] << 8)
                load_events.append((load_frame[0], setpal, code))
            if pc in stops and model.windows[0] == p2c['page_resident']:
                if pc == hook:
                    step_over()
                    return spent
                if pc == fault:
                    raise SystemExit(f'отказ p2c: код #{cpu.hl:04X}')
                if pc == switch_call:
                    api = cpu.hl & 0xFF
                    arg = model.word(symbols['_p2c_port_arg'])
                    flags = model.memory[symbols['_p2c_port_flags']]
                    if api == 1:
                        calls.append(['step', arg if arg < 0x8000 else arg - 0x10000, flags & 3, flags >> 7, None])
                    elif api == 2:
                        calls.append(['word', arg + 0x40000, 0, 0, None])
                    elif api == 3:
                        calls.append(['boot', 0, 0, 0, None])
                    elif api == 5:
                        calls.append(['data', 0, 0, 0, None])
                    elif api == 6:
                        calls.append(['fade', 0, 0, 0, None])
                    elif api == 7:
                        calls.append(['sound', 0, 0, 0, None])
                    elif api == 8:
                        calls.append(['sound_reset', 0, 0, 0, None])
                    elif api == 9:
                        calls.append(['mouse', (arg & 0xFF) - ((arg & 0x80) << 1), (arg >> 8) - ((arg & 0x8000) >> 7),
                                      0, None])
                    elif api != 4 or not calls or calls[-1][0] != 'video':
                        calls.append(['video' if api == 4 else f'api{api}', 0, 0, 0, None])
                elif pc == switch_result:
                    if calls and calls[-1][0] == 'word':
                        calls[-1][4] = cpu.de
                elif pc == show_entry:
                    calls.append(['show', 0, 0, 0, None])
                elif pc == reset_entry:
                    calls.append(['reset_session', 0, 0, 0, None])
                step_over()
                continue
            if pc in stops:
                step_over()
                continue
            if spent >= args.budget:
                raise SystemExit(f'больше {args.budget} тактов без конца кадра, PC #{pc:04X} окна {model.windows}')

    # Эталон CPython: цикл app.main с машиной M72; последний шаг хранит FrameState.
    pygame.init()
    pygame.display.set_mode((640, 480))

    from rtype_port import audio

    class SilentMixer:
        """Микшер эталона без вывода: TurboSoundFm шагает эмулятор чипов, PCM отбрасывается."""

        def reset_music(self) -> None:
            pass

        def push_music(self, samples, gain: float = 1.0) -> None:
            pass

        def stop_gs(self) -> None:
            pass

    tsfm_ports: list[tuple[int, int]] = []
    tsfm = audio.TurboSoundFm(SilentMixer(), enabled=not args.no_tsfm_check,
                              port_writer=lambda port, value: tsfm_ports.append((port, value)))
    sound_log: list[str] = []               # команды TSFM эталона: «кадр:$команда»
    effect_log: list[tuple[int, int]] = []  # эффекты $30…$FF эталона: (кадр, команда)
    current_frame = [0]

    class Port(p2c_runtime_app.MachinePort):
        def __init__(self) -> None:
            super().__init__()
            self.state = None
            self.mirror = None
            self.game_frame = False                # в кадре был ход игрока (mouse) — экран «игра» для Esc

        def boot(self) -> None:
            from v30z80 import snapshot as machine_snapshot
            self.machine = machine_snapshot.new_reference_machine(self.sound_command)
            if self.mirror is not None:
                install_keys_double(self.machine, self.mirror)
            self.calls.append(('boot', 0, 0, 0, None))

        @staticmethod
        def sound_command(command: int) -> None:
            # Эффекты $30…$FF — журнал для --ay-log (та же машина шлёт их и Z80 в тот же кадр).
            if command & 0xFF >= 0x30:
                effect_log.append((current_frame[0], command & 0xFF))
            # TargetAudio.command: мелодии и их control-команды — TSFM.
            if command & 0xFF < 0x30:
                if command & 0xFF:
                    sound_log.append(f'{current_frame[0]}:${command & 0xFF:02X}')
                tsfm.command(command)

        def step(self, mask, start1, coin1, render) -> None:
            from v30z80.scenario import Scenario
            Scenario.apply(self.machine, mask, bool(start1), bool(coin1))
            self.state = self.machine.step_frame()
            self.calls.append(('step', mask, int(bool(start1)) | (int(bool(coin1)) << 1), int(bool(render)), None))

        def reset_session(self) -> None:
            super().reset_session()
            tsfm.reset()
            if self.mirror is not None:
                self.mirror.clear()

        def mouse(self) -> None:
            # Вызов машины 9 — только при движении мыши кадра (p2c_port_mouse); сам вызов метода — кадр игры игрока.
            self.game_frame = True
            dx, dy = self.mirror.mouse_dx, self.mirror.mouse_dy
            if dx or dy:
                apply_mouse(self.machine, dx, dy)
                self.calls.append(('mouse', dx, dy, 0, None))

    def sound_state() -> tuple:
        sound = model.page_bytes(sound_page)

        def byte(name: str) -> int:
            return sound[machine_symbols[name] - 0xC000]
        ours = (None if byte('MUSIC_CURRENT') == 0xFF else byte('MUSIC_CURRENT'),
                None if byte('MUSIC_OWNER') == 0xFF else byte('MUSIC_OWNER'), byte('MUSIC_FADE'),
                bool(byte('MUSIC_ACTIVE')))
        theirs = (tsfm.current_command, tsfm.owner_command, tsfm.fade_remaining, tsfm.emulator is not None)
        return ours, theirs

    from p2c_entry_runtime import RuntimeApp
    from rtype_port.title import TitleAssets
    from rtype_m72.hq_renderer import M72HqRenderer
    port = Port()
    collide_watch = None
    if args.collide_watch:
        from rtype_collide_watch import CollideWatch
        collide_watch = CollideWatch()
    mirror = InputMirror()
    port.mirror = mirror
    app = RuntimeApp(TitleAssets(), port)
    renderer = M72HqRenderer()
    surface = pygame.Surface((640, 480))
    script = []
    for item in args.keys.split(','):
        if item:
            first, last, key = item.split(':')
            script.append((int(first), int(last), key))
    render_frames = {int(value) for value in args.render.split(',') if value}
    png = Path(args.png) if args.png else None
    if png:
        png.mkdir(parents=True, exist_ok=True)
    rows_index = np.arange(768) * 5 // 8
    columns_index = np.arange(1024) * 5 // 8

    def compare(frame: int, reference: np.ndarray, kind: str) -> dict:
        image, _stats = ft.render()
        expected = reference[rows_index][:, columns_index]
        difference = np.abs(image.astype(np.int16) - expected.astype(np.int16)).max(axis=2)
        if png:
            from PIL import Image
            Image.fromarray(np.concatenate([image, expected], axis=1)).save(png / f'rtype_{frame:05d}_{kind}.png')
        return {'diff': round(float((difference > 48).mean()) * 100, 3), 'mean': round(float(difference.mean()), 2)}

    started = time.perf_counter()
    z80_calls: list = []
    ticks = run_frame(z80_calls)             # первичная отрисовка титула
    app.title.render(surface)
    if 0 in render_frames:
        print(json.dumps({'frame': 0, 'kind': 'title', 'ticks': ticks,
                          **compare(0, pygame.surfarray.array3d(surface).transpose(1, 0, 2), 'title')}))
    # Конструктор RuntimeApp (новая машина и шаг) на Z80 исполняется после первичного кадра.
    pending = [list(call) for call in port.calls]
    port.calls.clear()
    swaps = ft.swaps
    import random
    rng = random.Random(args.random) if args.random is not None else None
    held: set[str] = set()
    scroll_log: list = []
    ft_load_rows: list = []
    for frame in range(1, args.frames + 1):
        if args.ft_load_log:
            # Нагрузка на FT812 до кадра (счётчики модели с начала работы): разность соседних строк — кадр.
            ft_load_rows.append([frame, ft.load_counters()])
        load_frame[0] = frame
        if args.rebuild_log:
            # Скролл слоёв перед кадром (переменная хоста TOP_SCROLL: sy, sx слоя 0, sy, sx слоя 1).
            host = model.page_bytes(0x0C)
            offset = machine_symbols['TOP_SCROLL'] - 0xC000
            scroll_log.append([frame] + [host[offset + 2 * index] | (host[offset + 2 * index + 1] << 8)
                                         for index in range(4)])
            # Пулы хоста перед кадром (страница тайлов VIDEO_TILE_PAGE #D4): картинки — записи с IMAGE_TABLE по 40 байт
            # (+36 ссылок, +39 занята), полосы — с 0 по 12 байт (+7 ссылок, +10 занята); по каждому — занятых и
            # со ссылками.
            tiles = model.page_bytes(0xD4)
            images = [tiles[0x2A00 + 40 * index:0x2A00 + 40 * index + 40] for index in range(74)]
            strips = [tiles[12 * index:12 * index + 12] for index in range(105)]
            scroll_log[-1] += [sum(1 for entry in images if entry[39]),
                               sum(1 for entry in images if entry[36] | entry[37]),
                               sum(1 for entry in strips if entry[10]),
                               sum(1 for entry in strips if entry[7] | entry[8])]
        profiling = bool(args.profile) and frame >= args.profile_from
        if procedure_profile:
            procedure_profile.enabled = frame >= args.profile_from
            procedure_profile.refresh()
        if cache_range and frame == cache_range[0]:
            from tsconf_cache_probe import CacheProbe
            cache_probe = CacheProbe(model)
        if cache_probe is not None:
            cache_probe.frame = frame
        current_frame[0] = frame
        keys = schedule(frame, script)
        if args.autofire is not None and frame >= args.autofire and frame % 8 < 4:
            keys.add('space')
        # С кадра 2: машину конструктора RuntimeApp эталон создал до цикла, Z80 — в кадре 1.
        if args.invincible and frame >= 2 and port.machine is not None:
            port.machine.cpu.mem_write(0x42FC6, b'\x01')
            model.poke((machine_report['v30_page_base'] + 0x10) * 0x4000 + 0x2FC6, 1)
        if rng is not None:
            if rng.random() < 0.05:
                held = set(rng.sample(['q', 'a', 'o', 'p', 'space', 'altgr', 'enter', 'rmb', 'lmb', 'mmb', 'mouse_up',
                                       'mouse_right', 'mouse_down', 'mouse_left', 'joy_fire', 'joy_force', 'joy_start',
                                       'joy_up', 'joy_right',
                                       'joy_down', 'joy_left'], rng.randrange(0, 3)))
            keys |= held
        ft.keys = set(keys)
        ft.frames = frame                    # кадр развёртки FT812 на кадр игры: один шаг потока мелодии
        z80_calls = []
        sound_events.clear()
        if collide_watch is not None:
            collide_watch.frame = frame
        ticks = run_frame(z80_calls)
        if collide_watch is not None and port.machine is not None:
            collide_watch.install(port.machine)
        if cache_probe is not None and frame == cache_range[1]:
            cache_report = cache_probe.close()
            cache_probe = None
            print('Кэш TS-Conf: ' + json.dumps(cache_report, ensure_ascii=False), flush=True)
        frame_ticks.append(ticks)
        if args.stage_log:
            # Границы уровней и контрольных точек в кадрах прогона — таблица для прицельных проверок,
            # чтобы не искать нужное место перебором. Этап — $2FCD рабочего ОЗУ; контрольная точка, с
            # которой ROM возрождает игрока после смерти, — $2F42 (её же дублирует $2F2D), прогресс
            # внутри этапа — слово $2F4B.
            block = port.machine.memory(slice(0x42F2D, 0x42FCE))
            stage_now = (block[0x2FCD - 0x2F2D], block[0x2F42 - 0x2F2D], block[0],
                         block[0x2F4B - 0x2F2D] | (block[0x2F4C - 0x2F2D] << 8))
            if stage_now != stage_seen:                # смена этапа, контрольной точки или прогресса
                stage_marks.append({'frame': frame, 'stage': int(stage_now[0]),
                                    'checkpoint': int(stage_now[1]), 'checkpoint2': int(stage_now[2]),
                                    'progress': int(stage_now[3])})
                stage_seen = stage_now
        if frame in dump_frames:
            # Сырые слова показанного списка: их разбирает ft812_line_cost.py (цена строки развёртки).
            (dump_dir / f'frame_{frame:05d}.dl').write_bytes(ft.shown_dl[:len(ft.words()) * 4])
        if frame in dump_frames and not args.dl_dump_light:
            (dump_dir / f'frame_{frame:05d}.ramg').write_bytes(bytes(ft.ram_g))
            # Резидент и рабочая страница кольца фона (отложенные столбцы RING_DEF — RingCatchUp).
            (dump_dir / f'frame_{frame:05d}_res.bin').write_bytes(bytes(model.page_bytes(machine_report['res_page'])))
            (dump_dir / f'frame_{frame:05d}_ringwork.bin').write_bytes(bytes(model.page_bytes(0xF8)))
            # VRAM слоёв A и B (страницы V30 #34, #36) — что сейчас в карте.
            for vram in (0x34, 0x36):
                (dump_dir / f'frame_{frame:05d}_vram{vram:02x}.bin').write_bytes(
                    bytes(model.page_bytes(machine_report['v30_page_base'] + vram)))
            # Страница хоста и страницы видеоадаптера (состояние, потоки, тени, позиции, тайлы, картинки) — для
            # сверки состояния хоста двух сборок (ранняя сборка строк групп, 2026-09-24); с --dl-dump-pages.
            for page in ([0x0C] + list(range(0xC0, 0xD5)) + [0x68]) if args.dl_dump_pages else ():
                (dump_dir / f'frame_{frame:05d}_page{page:02x}.bin').write_bytes(bytes(model.page_bytes(page)))
            # Для разбора вывода спрайтов: состояние handle модели FT812 и кадр эталона (палитры, спрайты).
            (dump_dir / f'frame_{frame:05d}_handles.json').write_text(
                json.dumps({str(k): v for k, v in ft.handles.items()} if isinstance(ft.handles, dict)
                           else list(ft.handles), ensure_ascii=False), encoding='utf-8')
            if port.state is not None:
                for field in ('palette0', 'palette1', 'spriteram'):
                    value = getattr(port.state, field, None)
                    if value is not None:
                        (dump_dir / f'frame_{frame:05d}_{field}.bin').write_bytes(bytes(value))
        if args.palette_log and port.state is not None:
            # Цена отказа от прохода B — пересчёт LUT смешанных цветов при смене палитры ROM. Считаем,
            # сколько перьев (записей палитры) изменилось за кадр и сколько палитр это задело: у M72 два
            # банка по 16 палитр, перо хранится словом в каждой из трёх плоскостей (R, G, B).
            row = []
            for index, field in enumerate(('palette0', 'palette1')):
                current = bytes(getattr(port.state, field, b'') or b'')
                before = palette_previous[index]
                pens = palettes = 0
                if before is not None and len(before) == len(current) and current != before:
                    touched = set()
                    for plane in range(3):
                        base = plane * 0x400
                        for entry in range(256):
                            offset = base + entry * 2
                            if current[offset:offset + 2] != before[offset:offset + 2]:
                                touched.add(entry)
                    pens = len(touched)
                    palettes = len({entry // 16 for entry in touched})
                palette_previous[index] = current
                row += [pens, palettes]
            row.append(len({word & 0x3FFFFF for word in ft.words() if word >> 24 == 0x2A}))
            palette_rows.append(row)
        if args.ring_audit:
            clear, lines, opaque = ring_audit(ft.words(), ft.ram_g)
            if clear:
                ring_cleared += 1
            elif lines < 768 or not opaque:
                ring_bad.append(frame)
                if len(ring_bad) <= 10:
                    print(f'кадр {frame}: очистки нет, кольцо закрыло {lines} строк из 768, палитра '
                          f'{"непрозрачна" if opaque else "с прозрачными записями"}', flush=True)
        if args.dl_record or expected_hashes is not None:
            if render_range and render_range[0] <= frame <= render_range[1]:
                # Видимое — сама отрисовка кадра моделью FT812 (768×1024 RGB): не зависит от того, в каких слотах пулов
                # лежат картинки, полосы и ячейки и что в невидимых. Правая часть — прежний хеш списка и всей RAM_G.
                image, _stats = ft.render()
                whole = hashlib.sha256(ft.shown_dl[:len(ft.words()) * 4] + bytes(ft.ram_g)).hexdigest()
                digest = f'{hashlib.sha256(image.tobytes()).hexdigest()}|{whole}'
            elif args.drawn:
                digest = drawn_digest(ft, args.drawn_no_sprite_b)
            elif args.ring_visible:
                digest = ring_visible_digest(ft.words(), ft.shown_dl, ft.ram_g, args.cells_free, args.ring_exact)
            else:
                digest = hashlib.sha256(ft.shown_dl[:len(ft.words()) * 4] + bytes(ft.ram_g)).hexdigest()
            dl_hashes.append(digest)
            if args.dl_record and frame % 5000 == 0:
                # Промежуточная запись: долгий прогон может не дожить до конца (утечка памяти вне Python).
                Path(args.dl_record).write_text(json.dumps(dl_hashes) + '\n', encoding='utf-8')
            if expected_hashes is not None and frame == len(expected_hashes) + 1:
                # Опорные хеши короче прогона (запись прервана: память машины) — дальше сверяется только память V30.
                print(f'кадр {frame}: опорные хеши вывода кончились, дальше вывод не сверяется', flush=True)
            if expected_hashes is not None and frame <= len(expected_hashes):
                # С --ring-visible сверяется левая часть «видимое | всё»; правая различается и должна.
                expected = expected_hashes[frame - 1]
                if args.ring_visible or args.drawn or render_range:
                    expected, digest_seen = expected.split('|')[0], digest.split('|')[0]
                else:
                    digest_seen = digest
                if expected != digest_seen:
                    if args.dl_continue:
                        # Сдвиг сроков выделения в полном пуле картинок меняет, какой класс идёт полосами (швы тайлов
                        # чуть иные): такие кадры собираются и сверяются потом картинкой (vdac2p_seams.py).
                        dl_mismatches.append(frame)
                    else:
                        print(f'кадр {frame}: список FT812 или RAM_G отличаются от прежней сборки')
                        return 1
        events, buttons = mirror.frame(keys)
        port.game_frame = False
        app.frame(events, buttons, surface)
        tsfm.step_frame()
        py_calls = pending + [list(call) for call in port.calls]
        pending = []
        port.calls.clear()
        shown = any(call[0] == 'show' for call in py_calls)
        mirror.end_frame(shown, port.game_frame)
        # Записи портов эталона: выбор чипа, регистр, значение.
        if len(tsfm_ports) % 3 or any(port_value[0] != (0xFFFD, 0xFFFD, 0xBFFD)[index % 3]
                                      for index, port_value in enumerate(tsfm_ports)):
            print(f'кадр {frame}: неожиданные записи портов TSFM эталона {tsfm_ports[:6]}')
            return 1
        reference_events = [(tsfm_ports[index][1] & 1, tsfm_ports[index + 1][1], tsfm_ports[index + 2][1])
                            for index in range(0, len(tsfm_ports), 3)]
        tsfm_ports.clear()
        if sound_events != reference_events and not args.no_gs and not args.no_tsfm_check:
            index = next((i for i in range(min(len(sound_events), len(reference_events)))
                          if sound_events[i] != reference_events[i]), min(len(sound_events), len(reference_events)))
            print(f'кадр {frame}: записи TSFM расходятся с записи {index}: Z80 {len(sound_events)} '
                  f'{sound_events[index:index + 4]}, эталон {len(reference_events)} {reference_events[index:index + 4]}')
            return 1
        ours, theirs = sound_state()
        if ours != theirs and not args.no_gs and not args.no_tsfm_check:
            print(f'кадр {frame}: состояние мелодии (текущая, владелец, затухание, поток) Z80 {ours}, эталон {theirs}')
            return 1
        if reference_events and trace and trace[0] <= frame <= trace[1]:
            print(f'кадр {frame}: записей TSFM {len(reference_events)}, состояние {theirs}')
        # Сброс видеоадаптера, открытие пака уровней, затемнение кадра машины перед титулом и вызовы
        # звукового адаптера — вызовы платформы, у эталона их нет.
        z80_compare = [call for call in z80_calls
                       if call[0] not in ('video', 'input', 'data', 'fade', 'sound', 'sound_reset')]
        if trace and trace[0] <= frame <= trace[1]:
            from p2c_runtime_app import BUTTON_FIELDS, EVENT_FIELDS, bits
            print(f'кадр {frame}: клавиши {sorted(keys)}, CPython ввод {bits(events, EVENT_FIELDS)}/'
                  f'{bits(buttons, BUTTON_FIELDS)} {py_calls}\n  Z80 {z80_calls}', flush=True)
        if z80_compare != py_calls:
            print(f'кадр {frame}: вызовы машины расходятся\n  CPython {py_calls}\n  Z80     {z80_calls}')
            return 1
        if args.dump_work and frame == int(args.dump_work.split(':')[0]):
            Path(args.dump_work.split(':', 1)[1]).write_bytes(bytes(model.page_bytes(machine_report['v30_page_base'] + 0x10)))
        if any(call[0] == 'step' for call in py_calls):
            # Память V30 после шага: 64 страницы машины и буфер спрайтов (как v30z80_check).
            from unicorn import x86_const
            stack_pointer = port.machine.cpu.reg_read(x86_const.UC_X86_REG_SP) & 0xFFFF
            for page in range(64):
                ours = bytearray(model.page_bytes(machine_report['v30_page_base'] + page))
                theirs = bytearray(port.machine.memory(slice(page << 14, (page + 1) << 14)))
                snapshot.restore_board_bytes(port.machine, theirs, page << 14)
                snapshot.mask_stack_garbage(ours, theirs, page << 14, stack_pointer)
                if ours != theirs:
                    index = next(i for i in range(0x4000) if ours[i] != theirs[i])
                    count = sum(1 for i in range(0x4000) if ours[i] != theirs[i])
                    print(f'кадр {frame}: память #{(page << 14) + index:05X}: Z80 #{ours[index]:02X} эталон '
                          f'#{theirs[index]:02X} (в странице отличий {count}), вызовы {z80_calls}')
                    # Все отличия страницы (до 24) — для разбора расхождения.
                    shown = [f'#{(page << 14) + i:05X}: {ours[i]:02X}/{theirs[i]:02X}'
                             for i in range(0x4000) if ours[i] != theirs[i]][:24]
                    print('  отличия (Z80/эталон): ' + ', '.join(shown))
                    return 1
            if model.page_bytes(machine_report['sprite_buffer_page'])[0:0x400] != bytes(port.machine.buffered_sprite_ram):
                print(f'кадр {frame}: буфер спрайтов расходится')
                return 1
        new_swaps = ft.swaps - swaps
        swaps = ft.swaps
        if ft.errors:
            print(f'кадр {frame}: ошибки FT812 {ft.errors[:4]}')
            return 1
        # Затемнение кадра машины перед титулом переключает список на каждом шаге альфы.
        fading = any(call[0] == 'fade' for call in z80_calls)
        if new_swaps != 1 and not (fading and new_swaps > 1):
            print(f'кадр {frame}: показано display list {new_swaps}, вызовы {z80_calls}')
            return 1
        if frame in render_frames:
            if shown:
                reference = np.asarray(renderer.render(port.state).convert('RGB'))
                kind = 'game'
            else:
                reference = pygame.surfarray.array3d(surface).transpose(1, 0, 2)
                kind = 'title'
            line = {'frame': frame, 'kind': kind, 'ticks': ticks, **compare(frame, reference, kind)}
            if kind == 'game':
                host = model.page_bytes(0x0C)
                for name in ('VIDEO_MISSING', 'VIDEO_DROPPED', 'VIDEO_OVERFLOW', 'VIDEO_UPLOADS', 'VIDEO_FAULTS'):
                    offset = machine_report['symbols'][name] - 0xC000
                    line[name[6:].lower()] = host[offset] | (host[offset + 1] << 8)
                line['data'] = host[machine_report['symbols']['DATA_STATUS'] - 0xC000]
                line['sd_reads'] = sd_reads_total + sum(1 for command in card.commands if command[0] in (17, 18))
            print(json.dumps(line), flush=True)
        if frame % 100 == 0:
            print(f'кадр {frame}: тактов {ticks}, {frame / (time.perf_counter() - started):.1f} к/с', flush=True)
        if os.environ.get('RTYPE_LEAK') and frame in (800, 2400):
            # Диагностика памяти прогона: снимки tracemalloc на кадрах 800 и 2400, печать роста.
            import tracemalloc
            if frame == 800:
                tracemalloc.start(8)
                leak_snapshot = tracemalloc.take_snapshot()
            else:
                for stat in tracemalloc.take_snapshot().compare_to(leak_snapshot, 'traceback')[:5]:
                    print('рост памяти:', stat, flush=True)
                    for line in stat.traceback.format()[-8:]:
                        print('   ', line, flush=True)
        # Журналы, которые никто здесь не читает, растут весь прогон (70 000 кадров — десятки гигабайт): журнал
        # портов и защёлки звука эталонной машины, команды модели SD-карты (счёт чтений — накопительный).
        if getattr(port, 'machine', None) is not None:
            port.machine.port_log.clear()
            port.machine.sound_latch.clear()
        sd_reads_total += sum(1 for command in card.commands if command[0] in (17, 18))
        card.commands.clear()
    if args.ay_log:
        # Заодно кладём флаги звукового адаптера: видно, опрошена ли плата и прочитан ли блок AY.
        sound = model.page_bytes(sound_page)
        flags = {name: sound[machine_symbols[name] - 0xC000]
                 for name in ('GS_DETECTED', 'GS_PRESENT', 'AY_LOADED', 'AY_ACTIVE', 'GS_PRELOAD',
                              'MUSIC_CURRENT', 'MUSIC_ACTIVE')
                 if name in machine_symbols}
        words = {name: sound[machine_symbols[name] - 0xC000] | (sound[machine_symbols[name] - 0xBFFF] << 8)
                 for name in ('AY_CALLS', 'AY_STARTS') if name in machine_symbols}
        print('флаги звука:', flags, words, flush=True)
        print(f'команд в порт GS: {len(gs_commands)}'
              + (f', первые {gs_commands[:6]}' if gs_commands else ''), flush=True)
        Path(args.ay_log).write_text(json.dumps(
            {'frame_rate': 59.08, 'flags': flags, 'writes': [list(item) for item in ay_writes],
             'effects': [list(item) for item in effect_log]},
            ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'записей в порты AY: {len(ay_writes)} → {args.ay_log}', flush=True)
    print(f'команды TSFM эталона (кроме $00): {" ".join(sound_log)}')
    if args.ticks:
        Path(args.ticks).write_text(json.dumps({'ticks': frame_ticks, 'profile': profile, 'cache': cache_report,
                                              'procedures': procedure_profile.report() if procedure_profile else {}}, ensure_ascii=False) + '\n',
                                   encoding='utf-8')
    if args.object_profile and object_profile:
        total_obj = sum(profile.values()) or 1
        print(f'Такты логики по текущему объекту (обработчик — слово +0 записи по BP); логика всего — '
              f'{sum(object_profile.values()) * 100 / total_obj:.1f} % профиля:')
        for handler, value in sorted(object_profile.items(), key=lambda kv: -kv[1])[:25]:
            print(f'  ${handler:04X}  {value * 100 / total_obj:5.1f} %')
    if args.rebuild_log:
        columns = model.page_bytes(0xED)
        Path(args.rebuild_log).write_text(json.dumps({'events': rebuild_events, 'scroll': scroll_log,
                                                      'columns': columns.hex()}), encoding='utf-8')
        print(f'перестроек строк: {len(rebuild_events)}, разного содержимого '
              f'{len({(e[1], e[4]) for e in rebuild_events})}')
    if args.object_log:
        Path(args.object_log).write_text(json.dumps(object_events), encoding='utf-8')
        print(f'входов SpriteEntry: {len(object_events)}')
    if args.sprite_trace:
        Path(args.sprite_trace).write_text(json.dumps(cell_events), encoding='utf-8')
        print(f'трасса SpriteCell: {len(cell_events)} обращений')
    if args.ft_load_log:
        Path(args.ft_load_log).write_text(json.dumps(ft_load_rows), encoding='utf-8')
    if args.hook_log:
        Path(args.hook_log).write_text(json.dumps(hook_events), encoding='utf-8')
    if collide_watch is not None:
        collide_watch.report(args.collide_watch)
    if args.dl_continue:
        Path(args.dl_continue).write_text(json.dumps(dl_mismatches) + '\n', encoding='utf-8')
        print(f'кадров с другим выводом: {len(dl_mismatches)}, первые {dl_mismatches[:20]}', flush=True)
    if args.image_log:
        failed = {frame: calls - taken for frame, (calls, taken) in image_events.items() if calls > taken}
        Path(args.image_log).write_text(json.dumps({'events': image_events, 'failed': failed, 'states': image_states}),
                                        encoding='utf-8')
        print(f'выделений картинок: {sum(c for c, _ in image_events.values())}, отказов: {sum(failed.values())} '
              f'в {len(failed)} кадрах, первые {sorted(failed)[:12]}')
    if args.load_log:
        from collections import Counter
        Path(args.load_log).write_text(json.dumps(load_events), encoding='utf-8')
        cells = Counter((setpal, code) for _frame, setpal, code in load_events)
        repeated = sum(count - 1 for count in cells.values())
        sprites = sum(1 for _f, setpal, _c in load_events if setpal >= 32)
        print(f'подгрузки ячеек: всего {len(load_events)} (спрайтов {sprites}), разных ячеек {len(cells)}, '
              f'повторных подгрузок {repeated} ({repeated * 100 // max(1, len(load_events))} %)')
        for (setpal, code), count in cells.most_common(8):
            print(f'   набор {setpal >> 4}, палитра {setpal & 15}, код #{code:03X}: {count} раз')
    if args.palette_log:
        import statistics
        Path(args.palette_log).write_text(json.dumps(palette_rows), encoding='utf-8')
        for index, name in ((0, 'банк 0'), (2, 'банк 1')):
            pens = sorted(row[index] for row in palette_rows)
            quiet = sum(1 for value in pens if value == 0)
            print(f'палитры, {name}: кадров без изменений {quiet * 100 // max(1, len(pens))} %, '
                  f'медиана изменённых перьев {pens[len(pens) // 2]}, 90 % {pens[int(len(pens) * 0.9)]}, '
                  f'максимум {pens[-1]}, палитр за кадр в среднем '
                  f'{statistics.mean(row[index + 1] for row in palette_rows):.2f}')
        used = sorted(row[4] for row in palette_rows)
        print(f'палитр в списке кадра: медиана {used[len(used) // 2]}, максимум {used[-1]}')
    if args.ring_audit:
        print(f'аудит кольца: кадров с очисткой {ring_cleared}, кадров без очистки и без полного '
              f'покрытия {len(ring_bad)}' + (f' (первые: {ring_bad[:10]})' if ring_bad else ''))
    if args.dl_record:
        Path(args.dl_record).write_text(json.dumps(dl_hashes) + '\n', encoding='utf-8')
    if args.stage_log:
        Path(args.stage_log).write_text(json.dumps(stage_marks, ensure_ascii=False, indent=1), encoding='utf-8')
        print('этапы и контрольные точки:', flush=True)
        for m in stage_marks:
            print(f"  кадр {m['frame']:>6}: этап {m['stage']}, точка {m['checkpoint']} "
                  f"(дубль {m['checkpoint2']}), прогресс #{m['progress']:04X}", flush=True)
    if profile:
        total = sum(profile.values())
        print('Профиль Z80 (такты инструкций без аппаратных задержек DMA/FT812):')
        for name, ticks in sorted(profile.items(), key=lambda item: -item[1])[:30]:
            print(f'  {name:>28} {100 * ticks / total:5.1f}%')
    if procedure_profile:
        print('Включающая стоимость процедур (такты модели, вложенные строки не суммировать):')
        for name, row in sorted(procedure_profile.report().items(), key=lambda item: -item[1]['ticks']):
            print(f'  {name:>28} {row}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
