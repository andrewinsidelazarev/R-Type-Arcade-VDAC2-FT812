"""Модель загрузчика SPG релиза (VDAC2+, 2026-09-27): SPG и образ SD → страницы игры и кадры экрана загрузки.

Z80 (TSConfModel) исполняет rtype_boot.asm с начала SPG: блоки SPG — в страницы по Build/V30Z80/rtype_spg.ini, прочее
ОЗУ — шум (как неочищенное при включении); SD — модель Z-Controller над Build/V30Z80/rtype_sd.img (RTYPECOD.PAC ищет
загрузчик пака); FT812 — v30z80_ft812 (RAM_G, RAM_DL, DMA ОЗУ→SPI и SPI→ОЗУ); REG_FRAMES — по тактам (59,08 Гц, DMA SD —
10 тактов на байт, как у модели реального времени). Platform_Init (запуск FT812 с ожиданием кадровых IRQ) пропускается;
таблицы шрифтов ПЗУ FT812 в модели нет — ширины знаков нулевые, знаки надписи только считаются.

Проверки: переход в резидент кода p2c; страницы игры. С 2026-09-27 загрузчик после кода зовёт машину (вызовы 0, 5 —
пак уровней, 10 — звуки), поэтому страницы сверяются с эталонным прогоном тех же вызовов на чистой машине (страницы
сборки, нулевые — нули, загрузчик пака — из SPG, та же карта и та же модель платы GS): страницы машины, кода p2c,
переключения и нулевые — целиком, кроме страниц загрузчика пака (рабочее состояние), стека драйвера резидента
(#3E00…#3FFF) и слова BootSp страницы переключения; прочие страницы (тайлы кольца, буфер мелодий) — там, где их
записал эталон. Итог вызовов: пак уровней открыт (DATA_STATUS, LOADER_READY), звуки загружены. Фазы загрузки — такты
до нулевых страниц (код), до первого вызова 10 (пак уровней) и до конца звуков: по ним — доли шкалы BAR_* загрузчика.
RAM_G — страницы-носители заставки подряд с адреса 0. Кадры экрана загрузки (первый, средний, последний) — своей
раскладкой display list (слова FT81x по спецификации: четыре прохода pseudo-DXT1 с альфой кадра, шкала в ножницах) → PNG;
заставка вне шкалы и надписи сверяется с предпросмотром vdac2p_splash.py (та же арифметика). Настоящий FT812 — эмулятор
в Unreal и плата.

Запуск: vdac2p_boot_check.py [--no-gs] [--png каталог].
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
from p2c_z80_check import TSConfModel  # noqa: E402
import v30z80_ft812  # noqa: E402
from v30z80_ft812 import Ft812Model  # noqa: E402
from rtype_loader_check import sd_controller  # noqa: E402

MACHINE = ROOT / 'Build' / 'V30Z80'
P2C = ROOT / 'Build' / 'P2cRuntime'
T_REFRESH = round(14_000_000 / 59.08)
DMA_SPI_TICKS = 10
TICK_LIMIT = 600_000_000                    # ≈43 с машины — дольше загрузка идти не должна
STACK_AREA = (0x3E00, 0x4000)               # стек драйвера резидента машины (вызовы API)


def spg_pages() -> dict[int, bytearray]:
    """Блоки SPG (rtype_spg.ini: «Block = адрес, страница, файл») → содержимое страниц."""
    pages: dict[int, bytearray] = {}
    for line in (MACHINE / 'rtype_spg.ini').read_text(encoding='utf-8').splitlines():
        match = re.match(r'Block = #([0-9A-Fa-f]+), #([0-9A-Fa-f]+), (.+)$', line)
        if not match:
            continue
        data = (ROOT / match[3]).read_bytes()
        target = pages.setdefault(int(match[2], 16), bytearray(0x4000))
        offset = int(match[1], 16) & 0x3FFF
        target[offset:offset + len(data)] = data
    return pages


def sjasm_symbols(path: Path) -> dict[str, int]:
    return {match[1]: int(match[2], 16) for match in
            re.finditer(r'^([A-Za-z_][\w.]*):\s+EQU\s+0x([0-9A-Fa-f]+)', path.read_text(encoding='latin1'), re.M)}


class BootFt(Ft812Model):
    """FT812 модели загрузки: REG_FRAMES по тактам, ПЗУ шрифтов — нули, журнал показанных списков."""

    def __init__(self, model, sd) -> None:
        super().__init__(model, sd)
        self.ticks = 0
        self.shown: list[bytes] = []

    def read(self, address: int) -> int:
        address &= 0x3FFFFF
        if v30z80_ft812.REG_FRAMES <= address < v30z80_ft812.REG_FRAMES + 4:
            return ((self.ticks // T_REFRESH) >> (8 * (address - v30z80_ft812.REG_FRAMES))) & 0xFF
        if 0x200000 <= address < 0x300000:
            return 0
        return super().read(address)

    def write(self, address: int, value: int) -> None:
        super().write(address, value)
        if address & 0x3FFFFF == v30z80_ft812.REG_DLSWAP and value:
            self.shown.append(bytes(self.shown_dl))

    def dma_spi_read(self) -> None:
        super().dma_spi_read()
        self.ticks += DMA_SPI_TICKS * (self.dma['num'] + 1) * (self.dma['len'] + 1) * 2


def render(dl: bytes, ram_g: bytes) -> tuple[np.ndarray, list[tuple[int, int]], list[tuple[int, int, int, int]]]:
    """Раскладка списка FT81x (слова — по спецификации, без кода загрузчика): кадр RGB, вершины знаков шрифтов ПЗУ
    (handle ≥ 16) и прямоугольники битмапов с прозрачностью (шкалы)."""
    frame = np.zeros((768, 1024, 4), dtype=np.float64)
    handles = {h: {'source': 0, 'format': 0, 'stride': 0, 'height': 0, 'w': 0, 'h': 0} for h in range(32)}
    handle = 0
    color = [255.0, 255.0, 255.0, 255.0]
    clear_rgb, clear_a = (0, 0, 0), 0
    mask = [1, 1, 1, 1]
    blend = (2, 4)
    transform = [256, 0, 0, 0, 256, 0]
    scissor = [0, 0, 2048, 2048]
    vertex_shift = 4
    glyphs: list[tuple[int, int]] = []
    overlays: list[tuple[int, int, int, int]] = []
    words = struct.unpack_from(f'<{len(dl) // 4}I', dl)
    ram = np.frombuffer(ram_g, dtype=np.uint8)

    def factor(code: int, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
        one = np.ones(src.shape[:-1] + (1,))
        return {0: 0 * one, 1: one, 2: src[..., 3:4] / 255, 3: dst[..., 3:4] / 255,
                4: 1 - src[..., 3:4] / 255, 5: 1 - dst[..., 3:4] / 255}[code]

    def draw(x: int, y: int) -> None:
        state = handles[handle]
        if handle >= 16:
            glyphs.append((x, y))
            return
        x0, y0 = max(x, scissor[0], 0), max(y, scissor[1], 0)
        x1 = min(x + state['w'], scissor[0] + scissor[2], 1024)
        y1 = min(y + state['h'], scissor[1] + scissor[3], 768)
        if x0 >= x1 or y0 >= y1:
            return
        px = np.arange(x0, x1) - x
        py = np.arange(y0, y1) - y
        u = np.floor((px + 0.5) * transform[0] / 256).astype(np.int64)
        v = np.floor((py + 0.5) * transform[4] / 256).astype(np.int64)
        uu, vv = np.meshgrid(u, v)
        fmt, stride, base = state['format'], state['stride'], state['source']
        if fmt == 1:                                            # L1: бит 7 байта — левый пиксель
            byte = ram[base + vv * stride + (uu >> 3)]
            lum = ((byte >> (7 - (uu & 7))) & 1) * 255.0
            src = np.stack([np.full(lum.shape, color[0]), np.full(lum.shape, color[1]),
                            np.full(lum.shape, color[2]), lum * color[3] / 255], axis=-1)
        elif fmt in (0, 7):                                     # ARGB1555, RGB565
            offset = base + vv * stride + uu * 2
            value = ram[offset].astype(np.int64) | (ram[offset + 1].astype(np.int64) << 8)
            if fmt == 7:
                r, g, b = (value >> 11) & 31, (value >> 5) & 63, value & 31
                rgb = [(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)]
                alpha = np.full(value.shape, 255.0)
            else:
                r, g, b = (value >> 10) & 31, (value >> 5) & 31, value & 31
                rgb = [(r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)]
                alpha = ((value >> 15) & 1) * 255.0
                overlays.append((x0, y0, x1, y1))
            src = np.stack([rgb[0] * color[0] / 255, rgb[1] * color[1] / 255, rgb[2] * color[2] / 255,
                            alpha * color[3] / 255], axis=-1)
        else:
            raise SystemExit(f'формат битмапа {fmt} раскладкой не поддержан')
        dst = frame[y0:y1, x0:x1]
        out = np.clip(src * factor(blend[0], src, dst) + dst * factor(blend[1], src, dst), 0, 255)
        for channel in range(4):
            if mask[channel]:
                dst[..., channel] = out[..., channel]

    begin = 0
    corner: list[tuple[int, int]] = []

    def rect(a: tuple[int, int], b: tuple[int, int]) -> None:
        # RECTS: прямоугольник между вершинами включительно (толщина линии — пиксель), цвет и альфа — текущие.
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        dst = frame[max(y0, 0):min(y1 + 1, 768), max(x0, 0):min(x1 + 1, 1024)]
        src = np.empty(dst.shape)
        src[...] = color
        out = np.clip(src * factor(blend[0], src, dst) + dst * factor(blend[1], src, dst), 0, 255)
        for channel in range(4):
            if mask[channel]:
                dst[..., channel] = out[..., channel]

    for word in words:
        if word == 0:
            break
        opcode = word >> 24
        if word >> 30 == 1:                                     # VERTEX2F
            x = (word >> 15) & 0x7FFF
            y = word & 0x7FFF
            x = x - 0x8000 if x & 0x4000 else x
            y = y - 0x8000 if y & 0x4000 else y
            point = (x >> vertex_shift if vertex_shift else x, y >> vertex_shift if vertex_shift else y)
            if begin == 1:
                draw(*point)
            elif begin == 9:
                corner.append(point)
                if len(corner) == 2:
                    rect(*corner)
                    corner.clear()
            continue
        if word >> 30 == 2:
            raise SystemExit('VERTEX2II в списке загрузчика не ожидается')
        if opcode == 0x02:
            clear_rgb = ((word >> 16) & 255, (word >> 8) & 255, word & 255)
        elif opcode == 0x0F:
            clear_a = word & 255
        elif opcode == 0x26:
            if word & 4:
                frame[..., 0:3] = clear_rgb
                frame[..., 3] = clear_a
        elif opcode == 0x05:
            handle = word & 31
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
            state['w'] = (state['w'] & ~511) | ((word >> 9) & 511)
            state['h'] = (state['h'] & ~511) | (word & 511)
        elif opcode == 0x29:
            state = handles[handle]
            state['w'] = (state['w'] & 511) | (((word >> 2) & 3) << 9)
            state['h'] = (state['h'] & 511) | ((word & 3) << 9)
        elif 0x15 <= opcode <= 0x1A:
            transform[opcode - 0x15] = word & 0xFFFFFF
        elif opcode == 0x0B:
            blend = ((word >> 3) & 7, word & 7)
        elif opcode == 0x20:
            mask = [(word >> 3) & 1, (word >> 2) & 1, (word >> 1) & 1, word & 1]
        elif opcode == 0x10:
            color[3] = word & 255
        elif opcode == 0x04:
            color[0:3] = [(word >> 16) & 255, (word >> 8) & 255, word & 255]
        elif opcode == 0x1B:
            scissor[0], scissor[1] = (word >> 11) & 2047, word & 2047
        elif opcode == 0x1C:
            scissor[2], scissor[3] = (word >> 12) & 4095, word & 4095
        elif opcode == 0x27:
            vertex_shift = word & 7
        elif opcode == 0x1F:
            begin = word & 15
            corner.clear()
        elif opcode == 0x21:
            begin = 0
        elif opcode == 0x06:
            pass                                                # CELL: у битмапов загрузчика — 0
        else:
            raise SystemExit(f'команда #{word:08X} раскладкой не поддержана')
    return np.clip(np.rint(frame[..., 0:3]), 0, 255).astype(np.uint8), glyphs, overlays


def run_until(model: TSConfModel, ft: BootFt, stops: set[int], limit: int) -> int | None:
    """Z80 модели — до одной из точек остановки stops (адрес PC); такты — в ft.ticks. None — предел тактов."""
    cpu = model.cpu
    for address in stops:
        cpu.set_breakpoint(address)
    try:
        while ft.ticks < limit:
            cpu.ticks_to_stop = 200_000
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little', signed=True)
            ft.ticks += 200_000 - remaining
            if cpu.pc in stops:
                return cpu.pc
        return None
    finally:
        for address in stops:
            cpu.clear_breakpoint(address)


def step_over(model: TSConfModel, ft: BootFt) -> None:
    """Одна команда с места остановки (точка остановки на нём снята)."""
    model.cpu.ticks_to_stop = 1
    model.cpu.run()
    ft.ticks += 1


def reference_calls(pages: dict[int, bytes], zero: set[int], machine: dict, spg: dict, no_gs: bool,
                    apis: list[int]) -> tuple[TSConfModel, dict[int, bytes], list[int]]:
    """Эталон: те же вызовы машины на чистой машине — окна как у BootCall (резидент, рабочее ОЗУ V30, страница
    переключения в W3, стек драйвера), возврат — на пустое место страницы переключения. Вызовы 0 и 5 — по разу, 10 —
    пока результат не 0. Возврат: модель, страницы до вызовов (все 256), результаты вызовов 10."""
    model = TSConfModel(pages, zero, seed=7, general_sound=not no_gs)
    sd, _card = sd_controller(MACHINE / 'rtype_sd.img')
    ft = BootFt(model, sd)
    before = {page: bytes(model.page(page)) for page in range(256)}
    symbols = machine['symbols']
    back = 0xC0FE                                   # пустое место страницы переключения
    results: list[int] = []
    queue = list(apis)
    windows = [machine['res_page'], machine['v30_page_base'] + 0x10, 0x00, spg['switch_page']]
    model.map_all(windows)
    while queue:
        api = queue.pop(0)
        for window, page in enumerate(windows):
            if window != 2 and model.windows[window] != page:
                model.map(window, page)             # с сохранением окна: записи прошлого вызова не теряются
        cpu = model.cpu
        cpu.sp = symbols['STACK_TOP'] - 2
        model.memory[cpu.sp] = back & 0xFF
        model.memory[cpu.sp + 1] = back >> 8
        cpu.a = api
        cpu.pc = 0x0003
        if run_until(model, ft, {back}, ft.ticks + 200_000_000) is None or model.windows[3] != spg['switch_page']:
            raise SystemExit(f'эталон: вызов {api} не вернулся')
        if api == 10:
            results.append(cpu.de)
            if cpu.de:
                queue.append(10)
    return model, before, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--no-gs', action='store_true', help='модель без платы General Sound')
    parser.add_argument('--png', type=Path, default=MACHINE / 'boot_check')
    parser.add_argument('--title', action='store_true',
                        help='после перехода в игру — до первого показанного списка кода p2c (пауза перед титулом)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    spg = json.loads((MACHINE / 'rtype_spg.json').read_text(encoding='utf-8'))
    machine = json.loads((MACHINE / 'build_report.json').read_text(encoding='utf-8'))
    p2c = json.loads((P2C / 'build_report.json').read_text(encoding='utf-8'))
    boot = sjasm_symbols(MACHINE / 'rtype_boot.sym')
    switch = sjasm_symbols(MACHINE / 'rtype_switch.sym')
    loader = json.loads((MACHINE / 'rtype_loader.json').read_text(encoding='utf-8'))
    symbols = machine['symbols']
    pages = spg_pages()
    model = TSConfModel(pages, set(), seed=1, general_sound=not args.no_gs)
    sd, card = sd_controller(MACHINE / 'rtype_sd.img')
    ft = BootFt(model, sd)
    model.map_all([0x00, 0x05, 0x00, 0x00])
    cpu = model.cpu
    cpu.pc = 0x5000
    cpu.sp = 0x3FFF
    start, failure, platform = p2c['entry'], boot['Failure'], boot['Platform_Init']
    marks = {boot['ZeroPages']: 'нулевые', boot['MachineCall']: 'вызов', boot['Start.sounded']: 'звуки'}
    stops = {start, failure, platform} | set(marks)
    outcome = None
    events: list[tuple[int, str, int]] = []
    while True:
        pc = run_until(model, ft, stops, TICK_LIMIT)
        if pc is None:
            break
        if pc == platform and model.windows[1] == 0x05:
            back = model.word(cpu.sp)                           # Platform_Init — пропуск (RET)
            cpu.sp = (cpu.sp + 2) & 0xFFFF
            cpu.pc = back
            continue
        if pc == failure and model.windows[1] == 0x05:
            outcome = 'ошибка'
            break
        if pc == start and model.windows[0] == p2c['page_resident']:
            outcome = 'переход в игру'
            break
        if pc in marks and model.windows[1] == 0x05:
            events.append((ft.ticks, marks[pc], cpu.a))
        cpu.clear_breakpoint(pc)
        step_over(model, ft)
    print(f'итог: {outcome or "не дошёл"}, {ft.ticks / 14_000_000:.2f} с машины (DMA SD — {DMA_SPI_TICKS} тактов на '
          f'байт), кадров списка {len(ft.shown)}, ошибок FT812 {len(ft.errors)}')
    if ft.errors:
        print('   ', ft.errors[:5])
    if outcome == 'переход в игру' and args.title:
        # Пауза перед титулом: от перехода в резидент p2c до первых показанных им списков (DLSWAP).
        jump, shown = ft.ticks, len(ft.shown)
        cpu.clear_breakpoint(start)
        moments = []
        while len(moments) < 12 and ft.ticks < jump + 20 * 14_000_000:
            cpu.ticks_to_stop = 20_000
            cpu.run()
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little', signed=True)
            ft.ticks += 20_000 - remaining
            while len(ft.shown) > shown + len(moments):
                moments.append(ft.ticks - jump)
        print('списки кода p2c после перехода, с: ' + ', '.join(f'{ticks / 14_000_000:.2f}' for ticks in moments))
        return 0
    if outcome != 'переход в игру':
        if outcome == 'ошибка':
            text = model.word(boot['TextPointer'])
            print('    надпись:', bytes(model.memory[text:text + 32]).split(b'\0')[0].decode('ascii', 'replace'))
        return 1
    # Фазы загрузки: код (до нулевых страниц), пак уровней (вызовы 0 и 5), звуки (вызовы 10).
    calls = [(ticks, api) for ticks, name, api in events if name == 'вызов']
    zero_at = next(ticks for ticks, name, _ in events if name == 'нулевые')
    sound_at = next(ticks for ticks, api in calls if api == 10)
    done_at = next(ticks for ticks, name, _ in events if name == 'звуки')
    open_at = calls[0][0]
    phases = {'код': zero_at, 'нулевые и решение о плате': open_at - zero_at, 'пак уровней': sound_at - open_at,
              'звуки': done_at - sound_at}
    total = zero_at + (sound_at - open_at) + (done_at - sound_at)
    print('фазы: ' + ', '.join(f'{name} {ticks / 14_000_000:.2f} с' for name, ticks in phases.items())
          + f'; вызовов машины {len(calls)} ({", ".join(str(api) for _, api in calls[:3])}…)')
    print(f'доли шкалы по тактам: код {zero_at / total:.1%}, конец пака {(zero_at + sound_at - open_at) / total:.1%}')
    # Эталон: те же вызовы на чистой машине.
    expected: dict[int, bytes] = {}
    for page in spg['machine_pages'] + [spg['switch_page']]:
        path = MACHINE / 'pages' / f'page_{page:02x}.bin'
        expected[page] = path.read_bytes() if path.is_file() else bytes(0x4000)
    for page in spg['p2c_pages']:
        expected[page] = (P2C / 'pages' / f'page_{page:02x}.bin').read_bytes()
    for page in spg['zero_pages']:
        expected[page] = bytes(0x4000)
    sound = symbols['SOUND_PAGE']
    reference_pages = dict(expected)
    for page in spg['loader_pages']:
        reference_pages[page] = bytes(pages[page])
    first = bytearray(reference_pages[sound])
    first[symbols['GS_DETECTED'] - 0xC000] = 1
    first[symbols['GS_PRESENT'] - 0xC000] = 0 if args.no_gs else 1
    reference_pages[sound] = bytes(first)
    apis = [api for _, api in calls if api != 10] + [10]
    reference, before, results = reference_calls(reference_pages, set(spg['zero_pages']), machine, spg, args.no_gs, apis)
    boot_sound_calls = sum(1 for _, api in calls if api == 10)
    print(f'эталон: вызовов 10 — {len(results)} (у загрузчика {boot_sound_calls}), секторов звука {sum(results)}')
    skip_pages = set(spg['loader_pages']) | {loader['loader_page'], symbols.get('DATA_BUF_PAGE', 0x5D)}
    skip_pages |= set(loader.get('pages', []))
    bad = []
    for page, data in sorted(expected.items()):
        if page in skip_pages:
            continue
        actual = bytearray(model.page_bytes(page))
        wanted = bytearray(reference.page_bytes(page))
        if page == machine['res_page']:
            lo, hi = STACK_AREA
            actual[lo:hi] = wanted[lo:hi]
            at = symbols['API_ARG']                     # HL вызова: у загрузчика и эталона разный, машине не нужен
            actual[at:at + 2] = wanted[at:at + 2]
        if page == spg['switch_page']:
            at = switch['BootSp'] - 0xC000
            actual[at:at + 2] = wanted[at:at + 2]
        if actual != wanted:
            differ = [index for index in range(0x4000) if actual[index] != wanted[index]]
            bad.append(f'#{page:02X}: {len(differ)} байт иначе (первый #{differ[0]:04X})')
    extra = 0
    for page in range(256):
        if page in expected or page in skip_pages:
            continue
        wanted = reference.page_bytes(page)
        mask = np.frombuffer(wanted, dtype=np.uint8) != np.frombuffer(before[page], dtype=np.uint8)
        if not mask.any():
            continue
        extra += 1
        actual = np.frombuffer(model.page_bytes(page), dtype=np.uint8)
        wrong = np.flatnonzero(mask & (actual != np.frombuffer(wanted, dtype=np.uint8)))
        if len(wrong):
            bad.append(f'#{page:02X}: записанное эталоном иначе — {len(wrong)} байт, #{wrong[0]:04X}…#{wrong[-1]:04X}')
    host = model.page_bytes(symbols['HOST_PAGE'])
    sound_page = model.page_bytes(sound)
    loader_ready = model.page_bytes(loader['loader_page'])[loader['symbols']['LOADER_READY'] - 0x8000]
    state = {'DATA_STATUS': host[symbols['DATA_STATUS'] - 0xC000], 'RING_ON': host[symbols['RING_ON'] - 0xC000],
             'LOADER_READY': loader_ready, 'GS_STATE': sound_page[symbols['GS_STATE'] - 0xC000],
             'GS_PRELOAD': sound_page[symbols['GS_PRELOAD'] - 0xC000],
             'AY_LOADED': sound_page[symbols['AY_LOADED'] - 0xC000]}
    ready = state['DATA_STATUS'] == 1 and state['LOADER_READY'] == 1 and (
        state['AY_LOADED'] == 1 if args.no_gs else state['GS_STATE'] == 2 and state['GS_PRELOAD'] == 1)
    print(f'страниц игры сверено с эталоном {len(expected) - len(skip_pages & set(expected))}, прочих записанных '
          f'{extra}, расхождений {len(bad)}' + (f': {bad[:6]}' if bad else '') + f'; состояние {state}')
    # RAM_G: страницы-носители заставки подряд с адреса 0.
    carriers = b''.join((MACHINE / 'splash_pages' / f'page_{page:02x}.bin').read_bytes() for page in spg['splash_pages'])
    ram_ok = bytes(ft.ram_g[:len(carriers)]) == carriers
    print(f'RAM_G заставки ({len(carriers)} байт): {"как носители" if ram_ok else "ИНАЧЕ"}')
    # Кадры экрана загрузки.
    args.png.mkdir(parents=True, exist_ok=True)
    preview = np.asarray(Image.open(ROOT / 'Assets' / 'Converted' / 'Splash' / 'splash_dxt_preview.png').convert('RGB'))
    # Кадры ухода в чёрное — со словом BEGIN(RECTS); до них — экран загрузки.
    def listed(dl: bytes) -> list[int]:
        words = struct.unpack_from(f'<{len(dl) // 4}I', dl)
        return list(words[:words.index(0) + 1]) if 0 in words else list(words)
    fading = [index for index, dl in enumerate(ft.shown) if 0x1F000009 in listed(dl)]
    plain = fading[0] if fading else len(ft.shown) - 1
    picks = sorted({0, plain // 2, plain - 1})
    for index in picks:
        image, glyphs, overlays = render(ft.shown[index], bytes(ft.ram_g))
        Image.fromarray(image).save(args.png / f'boot_frame_{index:03d}.png')
        outside = np.ones((768, 1024), dtype=bool)
        for x0, y0, x1, y1 in overlays:
            outside[y0:y1, x0:x1] = False
        differ = int((np.abs(image.astype(int) - preview.astype(int)).sum(axis=2)[outside] > 0).sum())
        print(f'кадр {index}: знаков надписи {len(glyphs) // 2}, заставка вне шкалы — пикселей не как предпросмотр '
              f'{differ}')
    if fading:
        levels = []
        for index in (fading[0], fading[len(fading) // 2], fading[-1]):
            image, _glyphs, _overlays = render(ft.shown[index], bytes(ft.ram_g))
            Image.fromarray(image).save(args.png / f'boot_fade_{index:03d}.png')
            levels.append(round(float(image.mean()), 1))
        print(f'уход в чёрное: кадров {len(fading)}, средняя яркость первого, среднего, последнего — {levels}')
    return 0 if not bad and ram_ok and ready and len(results) == boot_sound_calls else 1


if __name__ == '__main__':
    raise SystemExit(main())
