"""Модель реального времени SPG: часы развёртки FT812 по тактам Z80 (14 МГц, ≈55 Гц — период T_REFRESH тактов),
REG_FRAMES — число прошедших периодов, запрошенный DLSWAP завершается на ближайшем кадровом импульсе (до него
REG_DLSWAP читается 2). Считаются шаги игры (кадры p2c в игре) и показанные display list за отрезок.

Аргументы: FRAMES FROM TO [режимы через запятую: noskip — HostVideoSkip всегда «выводить»; oldwait — ожидание показа
в начале каждого кадра p2c, как до переноса в p2c_dl_flush] [AUTOFIRE].
Переменная RT_PROFILE=файл.json — профиль на отрезке замера (выборки PC каждые 101 такт, метки как у rtype_check; формат
{'profile': {метка: такты}} — для vdac2p_top.py): доли логики и вывода с пропуском вывода, как на железе.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', Path('E:/zx/R-Type VDAC2/Build/PythonDeps')):
    sys.path.insert(0, str(extra))
sys.stdout.reconfigure(encoding='utf-8')
import v30z80  # noqa: E402,F401
from p2c_z80_check import TSConfModel  # noqa: E402
from rtype_check import schedule  # noqa: E402
import v30z80_ft812  # noqa: E402
from v30z80_ft812 import Ft812Model  # noqa: E402
from rtype_loader_check import sd_controller  # noqa: E402

import os
MACHINE = Path(os.environ.get('RT_MACHINE', str(ROOT / 'Build' / 'V30Z80')))
P2C = ROOT / 'Build' / 'P2cRuntime'
frames_total, first, last = (int(v) for v in sys.argv[1:4])
modes = set(sys.argv[4].split(',')) if len(sys.argv) > 4 and sys.argv[4] != '-' else set()
autofire = int(sys.argv[5]) if len(sys.argv) > 5 else 720
T_REFRESH = round(14_000_000 / 59.08)
# Отрезок cpu.run() вне профиля (RT_QUANTUM, по умолчанию 50 млн тактов — до ловушки кадра).
QUANTUM = int(os.environ.get('RT_QUANTUM', '50000000'))
# DMA SPI→RAM с SD (чтение сектора загрузчиком): такты 14 МГц на байт. Оценка: SPI Z-Controller TS-Conf — 8 тактов на
# байт при частоте SPI, равной частоте процессора, плюс доля на слова DMA; у INIR — 21 такт на байт (считает модель CPU).
DMA_SPI_TICKS = int(os.environ.get('RT_DMA_SPI_TICKS', '10'))
# RT_DLDUMP=каталог,первый,последний — показанные списки кадров этого отрезка (цена строки при пропусках вывода).
DL_DUMP = None
if os.environ.get('RT_DLDUMP'):
    _dump_dir, _dump_first, _dump_last = os.environ['RT_DLDUMP'].split(',')
    DL_DUMP = (Path(_dump_dir), int(_dump_first), int(_dump_last))
    DL_DUMP[0].mkdir(parents=True, exist_ok=True)
current_frame = [0]
# RT_STAGELOG=файл — JSON [[кадр, этап], …]: кадры смены этапа игры (байт $2FCD рабочего ОЗУ V30, как --stage-log
# у rtype_check) — чтобы раскладывать замеры по этапам.
STAGE_LOG = os.environ.get('RT_STAGELOG', '')
stage_marks: list = []
stage_stats: dict = {}
# Промежутки между показами (2026-09-27): кадров развёртки от прошлой смены списка на экране — плавность при пропусках
# вывода. Гистограмма по отрезку first…last и наибольший промежуток — в итоге прогона.
swap_gaps: dict = {}
swap_last_due = [None]
# RT_DRAWN=опорные.json (2026-09-27) — каждый показанный кадр отрезка first…last сверяется с опорными хешами «нарисованное
# | всё» (rtype_check --drawn --dl-record; шаг модели N — кадр сверки N): при пропусках вывода работа хоста копится
# иначе, чем в сверке (там вывод на каждом шаге), — так видно, что показанное совпадает с выводом того же шага без
# пропусков. Хеш — в миг записи REG_DLSWAP: список, RAM_G и handle — как их оставил шаг. Для сверки нумерации — совпадения
# и с соседними кадрами опорных (сдвиг −1 и +1). RT_DRAWN_OUT=файл — JSON кадров с расхождением (картинкой — RT_RENDER).
DRAWN_PATH = os.environ.get('RT_DRAWN', '')
DRAWN_OUT = os.environ.get('RT_DRAWN_OUT', '')
drawn_expected = json.loads(Path(DRAWN_PATH).read_text(encoding='utf-8')) if DRAWN_PATH else None
drawn_stats: dict = {'shown': 0, 'shift': {-1: 0, 0: 0, 1: 0}, 'other': []}
drawn_step = [None]                             # список, отданный на показ в этом шаге (RT_DRAWN)
# RT_DRAWN_SAVE=каталог,кадр[,кадр…] — с RT_DRAWN: список, RAM_G и handle этих кадров (после шага) — в каталог.
DRAWN_SAVE_DIR = None
DRAWN_SAVE_FRAMES: set = set()
if os.environ.get('RT_DRAWN_SAVE'):
    _save_dir, *_save_frames = os.environ['RT_DRAWN_SAVE'].split(',')
    DRAWN_SAVE_DIR = Path(_save_dir)
    DRAWN_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    DRAWN_SAVE_FRAMES = {int(value) for value in _save_frames if value}
# RT_PIXELS=файл — с RT_DRAWN: кадры с расхождением хеша отрисовываются моделью FT812, в файл — JSON {кадр: хеш пикселей};
# RT_PIXELS_FRAMES=список.json — вместо этого отрисовать кадры списка (прогон noskip — те же кадры без пропусков, для
# сверки картинкой: класс строки ушёл полосами — швы тайлов чуть иные); RT_PIXELS_PNG=каталог — ещё и PNG.
PIXELS_OUT = os.environ.get('RT_PIXELS', '')
PIXELS_FRAMES = (set(json.loads(Path(os.environ['RT_PIXELS_FRAMES']).read_text(encoding='utf-8')))
                 if os.environ.get('RT_PIXELS_FRAMES') else None)
PIXELS_PNG = Path(os.environ['RT_PIXELS_PNG']) if os.environ.get('RT_PIXELS_PNG') else None
if PIXELS_PNG:
    PIXELS_PNG.mkdir(parents=True, exist_ok=True)
pixels_rows: dict = {}
# RT_GUARDLOG=файл — JSON [[кадр, оценка, слов, кадров без проверки, удержание, годна], …] по кадрам с выводом: переменные
# защиты строки FT812 (vdac2p_guard.asm, страница #4B) после кадра — сверка оценки Z80 с ft812_line_cost.
GUARD_LOG = os.environ.get('RT_GUARDLOG', '')
guard_rows: list = []
# RT_RENDER=кадр[,кадр…]:каталог — показанный список этих кадров отрисовывается моделью FT812 (PNG 1024×768) в трёх
# видах: как собран; без вершин прохода B спрайтов (handle 8, 9 — защита строки); без них только у спрайтов, задевающих
# строки дороже RENDER_LIMIT тактов (частичная защита). Вершины заменяются NOP — адреса CALL/JUMP не сдвигаются.
# Рядом — цена строк (ft812_line_cost) каждого вида.
# RT_SPRITES=кадр[,кадр…]:каталог — после шага кадра: копия буфера спрайтов хоста (SPRITE_TEMP страницы состояния, записи
# sprite RAM M72 по 8 байт) и слова спрайтов (SPRITE_WORDS, длина SPRITE_BYTES) — разбор объектов кадра.
SPRITE_FRAMES: set = set()
SPRITE_DIR = None
if os.environ.get('RT_SPRITES'):
    _sprite_frames, _sprite_dir = os.environ['RT_SPRITES'].split(':', 1)
    SPRITE_FRAMES = {int(value) for value in _sprite_frames.split(',') if value}
    SPRITE_DIR = Path(_sprite_dir)
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
# RT_OBJECTS=файл — JSON-перепись многоклеточных спрайтов (спрайты объектами, 2026-09-25): каждый кадр — записи копии
# буфера спрайтов хоста (SPRITE_TEMP), видимые на поле, как их отбирает SpritesBuild.
OBJECTS_PATH = os.environ.get('RT_OBJECTS', '')
object_census: dict = {'objects': {}, 'frames': []}


def census_frame(frame: int) -> None:
    import struct
    words = struct.unpack('<512H', model.page_bytes(0xC0)[0x0E00:0x1200])
    offset = 0
    singles = set()
    classes: dict = {}
    while offset < 512:
        y, code, attr, x = words[offset:offset + 4]
        width, height = 1 << ((attr >> 14) & 3), 1 << ((attr >> 12) & 3)
        offset += width * 4
        native_x = (x & 0x3FF) - 320
        native_y = 384 - (y & 0x1FF) - 16 * height
        if not (-16 * width < native_x < 384 and -16 * height < native_y < 240):
            continue
        palette = attr & 15
        if width * height == 1:
            singles.add((palette, code & 0x0FFF))
            continue
        key = f'{palette},{code & 0x0FFF},{width},{height}'
        entry = object_census['objects'].setdefault(key, [0, frame])
        entry[0] += 1
        classes.setdefault(f'{width}x{height}', set()).add(key)
    object_census['frames'].append([frame, len(singles), {name: len(keys) for name, keys in classes.items()}])


# RT_GUARDHIST=каталог,первый,последний — сверка защиты строки по полосам: в миг, когда LineGuard построила гистограмму
# (метка LineGuard.estimated, вторая страница хоста в W3), — гистограмма (LG_WL, LG_WH), записанное в RAM_DL (слова
# слоёв), слова спрайтов страницы состояния и блок GUARD_ARGS (место JUMP, DL_SENT, байт спрайтов).
# RT_HOSTVARS=файл — счётчики хоста VIDEO_MISSING (ячейка спрайта не выведена: нет данных или места в пуле),
# VIDEO_OVERFLOW (буфер слов спрайтов полон), VIDEO_UPLOADS (загрузки в RAM_G) — по кадрам, где они выросли:
# [кадр, прирост missing, overflow, uploads].
HOSTVARS_PATH = os.environ.get('RT_HOSTVARS', '')
hostvar_rows: list = []
hostvar_last = [None]
# RT_PEEK=страница:смещение:длина[,…] (2026-09-27, отладка) — после каждого шага отрезка first…last печатать байты
# страниц машины (страница и смещение — шестнадцатеричные, длина — десятичная): история записей пулов хоста.
PEEKS = [(int(page, 16), int(offset, 16), int(length)) for page, offset, length in
         (item.split(':') for item in os.environ.get('RT_PEEK', '').split(',') if item)]
GUARD_HIST = None
if os.environ.get('RT_GUARDHIST'):
    _hist_dir, _hist_first, _hist_last = os.environ['RT_GUARDHIST'].split(',')
    GUARD_HIST = (Path(_hist_dir), int(_hist_first), int(_hist_last))
    GUARD_HIST[0].mkdir(parents=True, exist_ok=True)
# RT_OBJSEQ=файл:первый:последний — модель пула объектов (vdac2p_objects.asm): по кадрам вывода (VIDEO_FRAME сменился —
# SpritesBuild переписал SPRITE_TEMP) записи с формой в порядке вывода (от последней видимой к первой): палитра, код,
# ширина, высота; записи с последней строкой ниже поля (их выводят ячейки) — с высотой 0.
OBJSEQ_PATH, OBJSEQ_FIRST, OBJSEQ_LAST = '', 0, -1
if os.environ.get('RT_OBJSEQ'):
    OBJSEQ_PATH, _objseq_first, _objseq_last = os.environ['RT_OBJSEQ'].rsplit(':', 2)
    OBJSEQ_FIRST, OBJSEQ_LAST = int(_objseq_first), int(_objseq_last)
objseq_rows: list = []
objseq_seen = [None]


def objseq_frame(frame: int) -> None:
    import struct
    shown = model.page_bytes(report['res_page'])[report['symbols']['VIDEO_FRAME']]
    if shown == objseq_seen[0]:
        return
    objseq_seen[0] = shown
    words = struct.unpack('<512H', model.page_bytes(0xC0)[0x0E00:0x1200])
    offset = 0
    visible = []
    while offset < 512:
        y, code, attr, x = words[offset:offset + 4]
        width, height = 1 << ((attr >> 14) & 3), 1 << ((attr >> 12) & 3)
        offset += width * 4
        native_x = (x & 0x3FF) - 320
        native_y = 384 - (y & 0x1FF) - 16 * height
        if not (-16 * width < native_x < 384 and -16 * height < native_y < 240) or width * height == 1:
            continue
        rows = height if native_y + 16 + 16 * (height - 1) < 256 else 0
        visible.append([attr & 15, code & 0x0FFF, width, rows])
    objseq_rows.append([frame, visible[::-1]])


RENDER_FRAMES: set = set()
RENDER_DIR = None
RENDER_LIMIT = 1200
if os.environ.get('RT_RENDER'):
    _render_frames, _render_dir = os.environ['RT_RENDER'].split(':', 1)
    RENDER_FRAMES = {int(value) for value in _render_frames.split(',') if value}
    RENDER_DIR = Path(_render_dir)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)


def render_variants(ft, frame: int) -> None:
    import struct
    import numpy as np
    from PIL import Image
    import ft812_line_cost as cost
    import v30z80_video_assets as assets
    sizes: dict = {}
    cost.parse(assets.dl_handles(assets.layout()), sizes)
    shown = bytes(ft.shown_dl)
    words = [struct.unpack_from('<I', shown, offset)[0] for offset in range(0, len(shown) // 4 * 4, 4)]

    def line_ticks(dl_words: list) -> np.ndarray:
        commands, primitives = cost.parse(dl_words, dict(sizes))
        diff = np.zeros(cost.LINES + 1, dtype=np.int64)
        for first, last, width, _kind, _left in primitives:
            lo, hi = max(0, first), min(cost.LINES, last)
            if lo < hi:
                diff[lo] += width
                diff[hi] -= width
        return commands + np.cumsum(diff)[:cost.LINES] // 8

    # Вершины прохода B спрайтов основной части: индекс слова и строки (VERTEX_TRANSLATE_Y учитывается).
    sprite_b = []
    translate_y = 0
    pc, stack, steps = 0, [], 0
    while 0 <= pc < len(words) and steps < 20000:
        word = words[pc]
        steps += 1
        if word == 0:
            break
        opcode = word >> 24
        if opcode == 0x1D:
            stack.append(pc + 1)
            pc = word & 0xFFFF
            continue
        if opcode == 0x24:
            if not stack:
                break
            pc = stack.pop()
            continue
        if opcode == 0x1E:
            pc = word & 0xFFFF
            continue
        if opcode == 0x2C:
            value = word & 0x1FFFF
            translate_y = value - 0x20000 if value & 0x10000 else value
        elif word >> 30 == 2 and not stack and ((word >> 7) & 31) in (8, 9):
            top = ((word >> 12) & 511) + translate_y // 16
            sprite_b.append((pc, top, top + 48))
        pc += 1
    full = line_ticks(words)
    over = full > RENDER_LIMIT
    nop = 0x2D000000
    guard = list(words)
    for index, _top, _bottom in sprite_b:
        guard[index] = nop
    partial = list(words)
    dropped = 0
    for index, top, bottom in sprite_b:
        if over[max(0, top):min(cost.LINES, bottom)].any():
            partial[index] = nop
            dropped += 1
    report = {'frame': frame, 'sprite_b': len(sprite_b), 'partial_dropped': dropped}
    for name, variant in (('full', words), ('guard', guard), ('partial', partial)):
        data = b''.join(struct.pack('<I', value) for value in variant)
        saved = ft.shown_dl
        ft.shown_dl = bytearray(data + bytes(len(saved) - len(data))) if len(data) < len(saved) else bytearray(data)
        image, _stats = ft.render()
        ft.shown_dl = saved
        Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(RENDER_DIR / f'frame_{frame:05d}_{name}.png')
        ticks = line_ticks(variant)
        report[name] = {'max': int(ticks.max()), 'line': int(ticks.argmax()), 'over_1200': int((ticks > 1200).sum()),
                        'over_1300': int((ticks > 1300).sum())}
        np.save(RENDER_DIR / f'frame_{frame:05d}_{name}_ticks.npy', ticks)
    (RENDER_DIR / f'frame_{frame:05d}.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

spg = json.loads((MACHINE / 'rtype_spg.json').read_text(encoding='utf-8'))
import os
PAGES = Path(os.environ.get('PAGES_DIR', str(MACHINE / 'pages')))
report = json.loads(((PAGES / 'build_report.json') if (PAGES / 'build_report.json').is_file() else (MACHINE / 'build_report.json')).read_text(encoding='utf-8'))
p2c = json.loads((P2C / 'build_report.json').read_text(encoding='utf-8'))
pages = {}
for page in spg['machine_pages'] + [spg['switch_page']]:
    path = PAGES / f'page_{page:02x}.bin'
    if path.is_file():
        pages[page] = bytearray(path.read_bytes())
for page in spg['p2c_pages']:
    pages[page] = bytearray((P2C / 'pages' / f'page_{page:02x}.bin').read_bytes())
if 'noskip' in modes:
    at = report['symbols']['HostVideoSkip'] - 0xC000
    pages[0x0C][at:at + 2] = b'\xAF\xC9'           # xor a / ret: всегда вывод
for mode in modes:
    if mode.startswith('skip') and mode[4:].isdigit():
        # SKIP_MAX: операнд `cp SKIP_MAX` (FE 01, затем jr nc — 30) в HostVideoSkip.
        start = report['symbols']['HostVideoSkip'] - 0xC000
        at = pages[0x0C].find(b'\xFE\x01\x30', start, start + 64)
        assert at > 0
        pages[0x0C][at + 1] = int(mode[4:])
zero = set(spg['zero_pages'])
for page in zero:
    pages[page] = bytes(0x4000)
model = TSConfModel({k: bytes(v) for k, v in pages.items()}, zero, 7)
model.map_all([p2c['page_resident'], p2c['page_data1'], p2c['page_data2'], p2c['first_bank']])
sd, card = sd_controller(MACHINE / 'rtype_sd.img')
cpu = model.cpu
clock = {'base': 0, 'budget': 0, 'offset': 0, 'swap_due': None}


def now() -> int:
    if not clock['budget']:
        return clock['base'] + clock['offset']     # вне run(): остаток бюджета уже учтён в base
    remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little', signed=True)
    return clock['base'] + clock['budget'] - remaining + clock['offset']


# RT_HAZARD=файл — порча показываемого (2026-09-25, «большие спрайты глючат» на плате): запись в RAM_G области спрайтов
# (ячейки и объекты) по месту, которое выводит показанный сейчас список или список, ждущий показа. FT812 выводит
# показанный список всё время до следующего переключения, поэтому такая запись видна на экране (снимки модели в миг
# переключения её не показывают). События: [кадр, адрес, байт, «показан»/«ждёт», handle, ячейка].
HAZARD_PATH = os.environ.get('RT_HAZARD', '')
hazard_rows: list = []


def sprite_ranges(ft, dl: bytes) -> list:
    """Места RAM_G, которые выводят вершины спрайтов (handle 4…13) списка: [начало, конец, handle, ячейка]."""
    import struct
    out = []
    for offset in range(0, len(dl) - 3, 4):
        word = struct.unpack_from('<I', dl, offset)[0]
        if word == 0:
            break
        if word >> 30 != 2:
            continue
        handle, cell = (word >> 7) & 31, word & 127
        if not 4 <= handle <= 13:
            continue
        state = ft.handles[handle]
        start = state['source'] + cell * state['stride'] * state['height']
        # Выводятся только строки текселей размера BITMAP_SIZE (масштаб 8/5): у ячейки 27×60 — 30 строк прохода.
        rows = min(state['height'], (state['height_px'] * 5 + 7) // 8)
        out.append((start, start + state['stride'] * rows, handle, cell))
    return out


def check_drawn(ft, dl: bytes) -> None:
    """RT_DRAWN: левая часть drawn_digest списка dl, который шаг отдал на показ, против опорной того же кадра. Зовётся
    после шага, как хеш сверки: RAM_G — со всеми записями шага, в том числе после REG_DLSWAP."""
    import copy
    from rtype_check import drawn_digest
    view = copy.copy(ft)
    view.shown_dl = dl
    view.handles = copy.deepcopy(ft.handles)
    Ft812Model.apply_handles(view)              # handle после этого списка — как в сверке после REG_DLSWAP
    digest = drawn_digest(view).split('|')[0]
    frame = current_frame[0]
    if frame in DRAWN_SAVE_FRAMES:
        # RT_DRAWN_SAVE: список, RAM_G и handle кадра — разбор расхождения по записям drawn_digest.
        (DRAWN_SAVE_DIR / f'dl_{frame:05d}.bin').write_bytes(dl)
        (DRAWN_SAVE_DIR / f'ramg_{frame:05d}.bin').write_bytes(bytes(ft.ram_g))
        (DRAWN_SAVE_DIR / f'handles_{frame:05d}.json').write_text(json.dumps(view.handles) + '\n', encoding='utf-8')
    drawn_stats['shown'] += 1
    same = False
    for shift in (-1, 0, 1):
        index = frame - 1 + shift
        if 0 <= index < len(drawn_expected) and drawn_expected[index].split('|')[0] == digest:
            drawn_stats['shift'][shift] += 1
            same = same or shift == 0
        elif shift == 0:
            drawn_stats['other'].append(frame)
    if PIXELS_OUT and (frame in PIXELS_FRAMES if PIXELS_FRAMES is not None else not same):
        # RT_PIXELS: сама отрисовка кадра моделью FT812 — хеш пикселей (и PNG) для сверки картинкой.
        import hashlib
        image, _stats = view.render()
        pixels_rows[frame] = hashlib.sha256(image.tobytes()).hexdigest()
        if PIXELS_PNG:
            import numpy as np
            from PIL import Image
            Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(PIXELS_PNG / f'frame_{frame:05d}.png')


class WatchedRam(bytearray):
    """RAM_G с проверкой записи в область спрайтов против мест показанного и ждущего списков."""
    owner = None
    low = high = 0

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            first, last = key.start or 0, key.stop if key.stop is not None else len(self)
        else:
            first, last = key, key + 1
        if last > self.low and first < self.high and self.owner is not None:
            self.owner.check_hazard(first, last)
        super().__setitem__(key, value)


class RealtimeFt(Ft812Model):
    shown_ranges: list = []
    pending_ranges: list = []

    def check_hazard(self, first: int, last: int) -> None:
        for name, ranges in (('показан', self.shown_ranges), ('ждёт', self.pending_ranges)):
            for start, end, handle, cell in ranges:
                if first < end and last > start:
                    hazard_rows.append([current_frame[0], first, last - first, name, handle, cell])
                    return

    def read(self, address: int) -> int:
        address &= 0x3FFFFF
        t = now()
        if v30z80_ft812.REG_DLSWAP <= address < v30z80_ft812.REG_DLSWAP + 4:
            due = clock['swap_due']
            if due is not None and t >= due:
                self.finish_swap()
            return 2 if clock['swap_due'] is not None and address == v30z80_ft812.REG_DLSWAP else 0
        if v30z80_ft812.REG_FRAMES <= address < v30z80_ft812.REG_FRAMES + 4:
            return ((t // T_REFRESH) >> (8 * (address - v30z80_ft812.REG_FRAMES))) & 0xFF
        return super().read(address)

    def write(self, address: int, value: int) -> None:
        address &= 0x3FFFFF
        if address == v30z80_ft812.REG_DLSWAP:
            if value:
                if clock['swap_due'] is not None:
                    self.finish_swap()
                self.pending_dl = bytes(self.ram_dl)
                if drawn_expected is not None and first <= current_frame[0] <= last:
                    drawn_step[0] = self.pending_dl     # сверка — после шага (check_drawn)
                if HAZARD_PATH:
                    self.pending_ranges = sprite_ranges(self, self.pending_dl)
                clock['swap_due'] = (now() // T_REFRESH + 1) * T_REFRESH
            return
        super().write(address, value)

    def dma_spi_read(self) -> None:
        # Процессор ждёт конца DMA (опрос DMASTATUS): время — байты × DMA_SPI_TICKS тактов 14 МГц.
        super().dma_spi_read()
        clock['offset'] += DMA_SPI_TICKS * (self.dma['num'] + 1) * (self.dma['len'] + 1) * 2

    def finish_swap(self) -> None:
        due = clock['swap_due']
        if due is not None:
            # Смена на экране — по кадровому импульсу swap_due (кратен T_REFRESH).
            if swap_last_due[0] is not None and first <= current_frame[0] <= last:
                gap = (due - swap_last_due[0]) // T_REFRESH
                swap_gaps[gap] = swap_gaps.get(gap, 0) + 1
            swap_last_due[0] = due
        self.shown_dl = self.pending_dl
        self.swaps += 1
        self.apply_handles()
        clock['swap_due'] = None
        if HAZARD_PATH:
            self.shown_ranges = self.pending_ranges
            self.pending_ranges = []
        if DL_DUMP and DL_DUMP[1] <= current_frame[0] <= DL_DUMP[2]:
            # Показанный список (слова до DISPLAY) — для цены строки (ft812_line_cost.py) в режиме пропусков вывода.
            words = self.words(self.shown_dl)
            (DL_DUMP[0] / f'frame_{current_frame[0]:05d}_{self.swaps:06d}.dl').write_bytes(self.shown_dl[:len(words) * 4])
        if current_frame[0] in RENDER_FRAMES:
            render_variants(self, current_frame[0])


ft = RealtimeFt(model, sd)
if HAZARD_PATH:
    ft.ram_g = WatchedRam(ft.ram_g)
    ft.ram_g.owner = ft
    ft.ram_g.low = report['symbols']['SPRITE_BASE']
    ft.ram_g.high = report['symbols']['SPRITE_BASE'] + 256 * report['symbols']['SPRITE_CELL_BYTES']
cpu.pc = p2c['entry']
cpu.sp = 0x3FFF
cpu.a = p2c['first_bank']
symbols = p2c['symbols']
hook = symbols['_p2c_z80_hook']
begin = symbols['_p2c_ft_frame_begin']
cpu.set_breakpoint(hook)
if 'oldwait' in modes:
    cpu.set_breakpoint(begin & 0xFFFF)


def step_over() -> None:
    pc = cpu.pc
    cpu.clear_breakpoint(pc)
    clock['budget'] = 1
    cpu.ticks_to_stop = 1
    cpu.run()
    clock['base'] += 1
    clock['budget'] = 0
    cpu.set_breakpoint(pc)


script = [(330, 331, 'space')]
stats = {'ticks': 0, 'frames': 0, 'swaps': 0}
# RT_COUNT=Метка1,… — входы в процедуры резидента машины (окно W0 — страница резидента) за кадр, для трассы.
count_names = [name for name in os.environ.get('RT_COUNT', '').split(',') if name]
# RT_CALLERS=Метка1,… (метки резидента, они же в RT_COUNT) — у каждого входа адрес возврата со стека: итог — вызовы по
# вызывающей процедуре (метка резидента или страницы окна W3) на шаг игры в отрезке замера (2026-09-25: столкновения).
caller_names = set(name for name in os.environ.get('RT_CALLERS', '').split(',') if name)
STACK_WALK = os.environ.get('RT_STACKWALK', '') == '1'
CODE_PAGES_SET = set(report.get('code_pages', []))
# RT_OBJLOG=1 (2026-09-25) — загрузки объектов в пул RAM_G (вход ObjLoad): ключ (код, палитра, класс) и кадр; итог —
# сколько загрузок повторные (тот же ключ уже загружался в отрезке — его вытеснили) и через сколько кадров.
obj_log = [] if os.environ.get('RT_OBJLOG', '') == '1' else None
# RT_DESCLOG=1 (2026-09-26) — описания спрайтов (входы NDescriptor6/NDescriptor12: ES, BX) в отрезке замера; итог —
# доля попаданий прямого кэша описаний по BX (ES = #1000) разного размера: цена кэша в нативной странице.
desc_log = [] if os.environ.get('RT_DESCLOG', '') == '1' else None
# RT_OBJMEMO=1 (2026-09-25) — вызовы ObjEntry: доля записей, у которых ключ (код, палитра, атрибут — байты +2…+5) тот
# же, что у той же записи sprite RAM в прошлый раз, и доля уже встречавшихся ключей — оценка памяти ключей по записи.
obj_memo = {'calls': 0, 'same': 0, 'any': 0, 'last': {}, 'keys': set()} if os.environ.get('RT_OBJMEMO') == '1' else None
if obj_memo is not None:
    caller_names.add('ObjEntry')
if obj_log is not None:
    caller_names.add('ObjLoad')
if desc_log is not None:
    caller_names.update(('NDescriptor6', 'NDescriptor12'))
count_names += [name for name in sorted(caller_names) if name not in count_names]
caller_hist: dict = {}
count_at = {report['symbols'][name]: name for name in count_names}
# Страница окна W3 у меток выше #C000 (2026-09-25): процедуры страниц хоста (#0C) и второй страницы хоста (#4B, файлы
# vdac2p_host2/guard/objects/sprclear) — вход считается только при своей странице в W3; иначе адрес совпадает с кодом
# других страниц окна.
count_page: dict[int, int] = {}
if any(address >= 0xC000 for address in count_at):
    import re as _re
    for _filename, _page in (('v30z80_host.asm', 0x0C), ('vdac2p_native.asm', 0x4A), ('vdac2p_host2.asm', 0x4B),
                             ('vdac2p_guard.asm', 0x4B),
                             ('vdac2p_objects.asm', 0x4B), ('vdac2p_sprclear.asm', 0x4B), ('vdac2p_palettes.asm', 0x4B), ('vdac2p_native_h2.asm', 0x4B)):
        _names = set(_re.findall(r'^([A-Za-z_][\w]*):', (ROOT / 'Source' / 'ASM' / _filename).read_text(encoding='utf-8'),
                                 flags=_re.MULTILINE))
        for _address, _name in count_at.items():
            if _address >= 0xC000 and _name.split('.')[0] in _names:
                count_page[_address] = _page
    # Модуль второй нативной страницы (n2.…, 2026-09-26).
    for _address, _name in count_at.items():
        if _name.startswith('n2.') and len(report.get('native_pages', [])) > 1:
            count_page[_address] = report['native_pages'][1]
    # Переведённый код (метки A_/K_ с адресом ROM, 2026-09-25): страница кода — из page_of отчёта сборки.
    for _address, _name in count_at.items():
        _root = _name.split('.')[0]
        if _address >= 0xC000 and _root[:2] in ('A_', 'K_') and _root[2:] in report['page_of']:
            count_page[_address] = report['page_of'][_root[2:]]
counts: dict[str, int] = {name: 0 for name in count_names}
for address in count_at:
    cpu.set_breakpoint(address)
guard_hist_at = report['symbols'].get('LineGuard.estimated') if GUARD_HIST else None
if guard_hist_at is not None:
    cpu.set_breakpoint(guard_hist_at)
# RT_RINGLOG=1 (с RingBuild в RT_COUNT) — к трассе: вызовы RingBuild за кадр по вызывающему (метка резидента по адресу
# возврата) — число вызовов и тайлов RING_N; чем занято кольцо фона в тяжёлых кадрах.
ring_log = os.environ.get('RT_RINGLOG', '') == '1'
ring_calls: dict[str, list[int]] = {}
resident_labels = sorted((address, name) for name, address in report['symbols'].items()
                         if isinstance(address, int) and address < 0x4000 and '.' not in name
                         and not name.startswith(('A_', 'F_', 'G_', 'D_', 'K_')) and name[:1].isupper()
                         and not name.isupper())
# RT_RINGUNIFORM=файл.json (с RingBuild в RT_COUNT) — сколько тайлов RingBuild одноцветные (все 64 пикселя одним пером,
# по родным тайлам набора 1 из ROM): по кадрам с записью кольца — [тайлов, одноцветных, из них пера 0].
ring_uniform_path = os.environ.get('RT_RINGUNIFORM', '')
ring_uniform_frames: dict[int, list[int]] = {}
if ring_uniform_path:
    import m72_arcade
    _regions = m72_arcade.assemble_regions(m72_arcade.ROM_DIR)
    UNIFORM_PEN = []
    for _code in range(4096):
        _pens = m72_arcade.decode_tile(_regions['tiles1'], _code)
        UNIFORM_PEN.append(_pens[0] if all(pen == _pens[0] for pen in _pens) else -1)
profile_path = os.environ.get('RT_PROFILE', '')
profile: dict[str, int] = {}
if profile_path:
    import bisect
    p2c_labels = sorted((address, name) for name, address in p2c['symbols'].items()
                        if isinstance(address, int) and address < 0x4000 and not name.startswith(('l__', 's__')))
    # Банки кода оболочки: полные адреса символов из карты компоновки (Build/P2cRuntime/program.noi: страница·#10000 +
    # адрес окна #C000).
    p2c_bank_labels: dict = {}
    for line in (P2C / 'program.noi').read_text(encoding='latin1').splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'DEF' and parts[1].startswith('_'):
            value = int(parts[2], 16)
            if value >= 0x10000 and value & 0xFFFF >= 0xC000:
                p2c_bank_labels.setdefault(value >> 16, []).append((value & 0xFFFF, parts[1]))
    for labels in p2c_bank_labels.values():
        labels.sort()
    import re
    machine_symbols = report['symbols']
    labels_by_page: dict[int, list] = {}
    # Файлы, подключаемые INCLUDE, — тоже: без них время их процедур ложится на последнюю метку перед ними (так до
    # 2026-09-25 защита строки и спрайты объектами числились за SpStripRow, выделение мест спрайтов — за Host2Back).
    for filename, label_page in (('v30z80_runtime.asm', -1), ('v30z80_flags.inc', -1), ('v30z80_kernels.asm', -1),
                                 ('v30z80_ring.asm', -1), ('v30z80_host.asm', 0x0C), ('v30z80_sound.asm', 0x5E),
                                 ('v30z80_gs.asm', 0x5E), ('v30z80_ay.asm', 0x5E),
                                 ('vdac2p_native.asm', 0x4A), ('vdac2p_early.asm', -1), ('vdac2p_sprites.asm', -1),
                                 ('vdac2p_host2.asm', 0x4B), ('vdac2p_guard.asm', 0x4B), ('vdac2p_objects.asm', 0x4B),
                                 ('vdac2p_sprclear.asm', 0x4B), ('vdac2p_palettes.asm', 0x4B), ('vdac2p_native_h2.asm', 0x4B)):
        source = (ROOT / 'Source' / 'ASM' / filename).read_text(encoding='utf-8')
        names = re.findall(r'^([A-Za-z_][\w]*):', source, flags=re.MULTILINE)
        labels_by_page.setdefault(label_page, []).extend((machine_symbols[name], name) for name in names
                                                         if name in machine_symbols)
    # Вторая нативная страница: метки модуля n2 (без локальных) — на своей странице.
    for page2 in report.get('native_pages', [])[1:2]:
        labels_by_page.setdefault(page2, []).extend(
            (address, name) for name, address in machine_symbols.items()
            if name.startswith('n2.') and name.count('.') == 1 and isinstance(address, int))
    loader_report = json.loads((MACHINE / 'rtype_loader.json').read_text(encoding='utf-8'))
    labels_by_page.setdefault(loader_report['loader_page'], []).extend(
        (address, name) for name, address in loader_report['symbols'].items()
        if isinstance(address, int) and '.' not in name and 0x8000 <= address < 0xC000)
    # RT_PROFILE_LOCAL=Метка1,Метка2 — ещё и локальные метки этих процедур (Метка.ветка) на странице самой процедуры.
    for parent in filter(None, os.environ.get('RT_PROFILE_LOCAL', '').split(',')):
        for label_page, labels in labels_by_page.items():
            if any(name == parent for _, name in labels):
                labels.extend((address, name) for name, address in machine_symbols.items()
                              if name.startswith(parent + '.') and isinstance(address, int))
    for labels in labels_by_page.values():
        labels.sort()
    translated_pages = set(report['page_of'].values())
    # Метки инструкций переведённого кода (A_линейный адрес) на своих страницах — профиль разбирает vdac2p_costmap.py.
    code_labels: dict[int, list] = {}
    for key, code_page in report['page_of'].items():
        code_labels.setdefault(code_page, []).append((machine_symbols[f'A_{key}'], f'A_{key}'))
    for labels in code_labels.values():
        labels.sort()


def sample(ticks: int) -> None:
    """Выборка PC: метка по странице окна, где сейчас PC (как sample в rtype_check)."""
    windows = model.windows
    if windows[0] == p2c['page_resident']:
        # Оболочка p2c (2026-09-25): метка её символа (функции C) по PC в окне W0; код в других окнах — страница.
        pc = cpu.pc
        if pc < 0x4000:
            index = bisect.bisect_right(p2c_labels, (pc, chr(0xFFFF))) - 1
            name = 'p2c:' + (p2c_labels[index][1] if index >= 0 else 'app/title')
        else:
            page = windows[pc >> 14]
            labels = p2c_bank_labels.get(page) if pc >= 0xC000 else None
            if labels:
                index = bisect.bisect_right(labels, (pc, chr(0xFFFF))) - 1
                name = 'p2c:' + (labels[index][1] if index >= 0 else f'page_{page:02X}')
            else:
                name = f'p2c:page_{page:02X}'
    else:
        pc = cpu.pc
        if pc >= 0xC000:
            page = windows[3]
        elif pc >= 0x8000:
            page = windows[2]
        elif pc >= 0x4000:
            page = windows[1]
        else:
            page = -1 if windows[0] == report['res_page'] else windows[0]
        labels = labels_by_page.get(page)
        if labels:
            index = bisect.bisect_right(labels, (pc, '\uffff')) - 1
            name = labels[index][1] if index >= 0 else f'page_{page:02X}'
        elif page in code_labels:
            labels = code_labels[page]
            index = bisect.bisect_right(labels, (pc, '\uffff')) - 1
            name = labels[index][1] if index >= 0 else f'page_{page:02X}'
        else:
            name = f'page_{page:02X}'
    profile[name] = profile.get(name, 0) + ticks
    if object_profile is not None and windows[0] == report['res_page'] and windows[3] not in HOST_W3_PAGES:
        # Логика машины: такты — обработчику текущего объекта V30 (слово [bp] при BP, кратном #20, < #3F00).
        bp = model.word(report['symbols']['V_BP'])
        key = f'IP {model.word(0x4000 + bp):04X}' if bp % 0x20 == 0 and bp < 0x3F00 else 'вне объектов'
        object_profile[key] = object_profile.get(key, 0) + ticks
        if key in OBJECT_FOCUS:
            focus = focus_profile.setdefault(key, {})
            focus[name] = focus.get(name, 0) + ticks


# RT_OBJPROFILE=файл.json (2026-09-25, с RT_PROFILE) — такты логики машины по обработчику текущего объекта: окно W0 —
# резидент машины, W3 — не хост, не вторая страница хоста и не звук (как --object-profile у rtype_check).
OBJECT_PROFILE_PATH = os.environ.get('RT_OBJPROFILE', '')
object_profile = {} if OBJECT_PROFILE_PATH else None
# RT_OBJFOCUS='IP 55E8,IP 5E8E' (2026-09-25, с RT_OBJPROFILE) — такты этих ключей ещё и по процедурам (метки профиля):
# что дорого внутри обработчика или контекста (IP 55E8 — задачи главного цикла, BP = #3060).
OBJECT_FOCUS = [key for key in os.environ.get('RT_OBJFOCUS', '').split(',') if key]
focus_profile: dict[str, dict[str, int]] = {}
HOST_W3_PAGES = {0x0C, 0x4B} | set(range(0x5E, 0x66))
for frame in range(frames_total + 1):
    current_frame[0] = frame
    ft.keys = schedule(frame, script)
    if frame >= autofire and frame % 8 < 4:
        ft.keys.add('space')
    # Неуязвимость — латч ROM $2FC6 рабочего ОЗУ V30 перед каждым кадром. RT_OWN_INVINCIBLE=1 — не подставлять: сверка
    # сборки RTYPE_ASM_DEFINES=RTYPE_INVINCIBLE (латч взводит сам резидент) — прогон должен дойти до этапа 8.
    if frame >= 2 and not os.environ.get('RT_OWN_INVINCIBLE'):
        model.poke((report['v30_page_base'] + 0x10) * 0x4000 + 0x2FC6, 1)
    start_time = now()
    start_swaps = ft.swaps
    start_commands = len(card.commands)
    start_dma = ft.dma_spi_reads
    profiling = bool(profile_path) and first <= frame <= last
    while True:
        clock['budget'] = 101 if profiling else QUANTUM
        cpu.ticks_to_stop = clock['budget']
        cpu.run()
        remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little', signed=True)
        clock['base'] += clock['budget'] - remaining
        if profiling:
            sample(clock['budget'] - remaining)
        clock['budget'] = 0
        pc = cpu.pc
        if pc == hook and model.windows[0] == p2c['page_resident']:
            step_over()
            break
        if pc in count_at and model.windows[0] == report['res_page'] and count_page.get(pc, model.windows[3]) == model.windows[3]:
            counts[count_at[pc]] += 1
            if count_at[pc] in caller_names and first <= frame <= last:
                back = model.word(cpu.sp)
                if STACK_WALK and back < 0xC000 and model.windows[3] in CODE_PAGES_SET:
                    # RT_STACKWALK=1 (2026-09-26): у помощников перевода — первый адрес возврата в странице кода W3
                    # (переведённая инструкция, которая начала цепочку помощников), до 8 слов стека.
                    for _depth in range(1, 9):
                        _word = model.word(cpu.sp + 2 * _depth)
                        if _word >= 0xC000:
                            back = _word
                            break
                key = (count_at[pc], model.windows[3] if back >= 0xC000 else -1, back)
                caller_hist[key] = caller_hist.get(key, 0) + 1
            if obj_memo is not None and count_at[pc] == 'ObjEntry' and first <= frame <= last:
                record = cpu.de
                key = bytes(model.memory[record + 2:record + 6])
                index = (record - (0x4000 + report['symbols']['SPRITE_TEMP'])) // 8
                obj_memo['calls'] += 1
                obj_memo['same'] += obj_memo['last'].get(index) == key
                obj_memo['any'] += key in obj_memo['keys']
                obj_memo['last'][index] = key
                obj_memo['keys'].add(key)
            if desc_log is not None and count_at[pc] in ('NDescriptor6', 'NDescriptor12') and first <= frame <= last:
                sym = report['symbols']
                desc_log.append((model.word(sym['V_ES']), model.word(sym['V_BX']), count_at[pc] == 'NDescriptor12'))
            if obj_log is not None and count_at[pc] == 'ObjLoad' and first <= frame <= last:
                sym = report['symbols']
                obj_log.append((frame, model.word(sym['OBJ_CODE']), model.memory[sym['OBJ_PAL']],
                                model.memory[sym['OBJ_CLASS']]))
            if ring_log and count_at[pc] == 'RingBuild':
                import bisect
                back = model.word(cpu.sp)
                index = bisect.bisect_right(resident_labels, (back, '\uffff')) - 1
                caller = resident_labels[index][1] if index >= 0 else f'#{back:04X}'
                entry = ring_calls.setdefault(caller, [0, 0])
                entry[0] += 1
                entry[1] += model.memory[report['symbols']['RING_N']]
            if ring_uniform_path and count_at[pc] == 'RingBuild':
                source = model.word(report['symbols']['RING_TSRC'])
                row = ring_uniform_frames.setdefault(frame, [0, 0, 0])
                for tile in range(model.memory[report['symbols']['RING_N']]):
                    code = model.word(source + tile * 4) & 0x0FFF
                    row[0] += 1
                    if UNIFORM_PEN[code] >= 0:
                        row[1] += 1
                        row[2] += UNIFORM_PEN[code] == 0
            step_over()
            continue
        if pc in count_at:
            step_over()
            continue
        if pc == guard_hist_at and model.windows[3] == 0x4B:
            if GUARD_HIST[1] <= frame <= GUARD_HIST[2]:
                host2 = model.page_bytes(0x4B)
                state = model.page_bytes(0xC0)
                sym = report['symbols']
                at = sym['LG_WL'] - 0xC000
                args = sym['GUARD_ARGS'] - 0x4000
                sprite_bytes = state[args + 4] | (state[args + 5] << 8)
                words_at = sym['SPRITE_WORDS']
                (GUARD_HIST[0] / f'hist_{frame:05d}.bin').write_bytes(host2[at:at + 512])
                (GUARD_HIST[0] / f'args_{frame:05d}.bin').write_bytes(state[args:args + 6])
                (GUARD_HIST[0] / f'dl_{frame:05d}.bin').write_bytes(bytes(ft.ram_dl))
                (GUARD_HIST[0] / f'sprites_{frame:05d}.bin').write_bytes(state[words_at:words_at + sprite_bytes])
            step_over()
            continue
        if 'oldwait' in modes and pc == begin & 0xFFFF and model.windows[3] == begin >> 16:
            # Прежний p2c_ft_frame_begin: опрос REG_DLSWAP до кадрового импульса.
            if clock['swap_due'] is not None:
                t = now()
                clock['offset'] += max(0, clock['swap_due'] - t)
                ft.finish_swap()
        if pc in (hook, begin & 0xFFFF):
            step_over()
    if clock['swap_due'] is not None and now() >= clock['swap_due']:
        ft.finish_swap()
    if drawn_step[0] is not None:
        check_drawn(ft, drawn_step[0])
        drawn_step[0] = None
    if 'trace' in modes and first <= frame <= last:
        # Чтения секторов SD за кадр (CMD17) и байт, пришедших через DMA SPI→RAM.
        reads = sum(1 for command in card.commands[start_commands:] if command[0] == 17)
        print(f'кадр {frame}: тактов {now() - start_time}, показано {ft.swaps - start_swaps}, время {now() / 14_000_000:.2f} с, '
              f'SD {reads}, DMA {ft.dma_spi_reads - start_dma}' +
              ''.join(f', {name} {counts[name]}' for name in count_names) +
              ''.join(f', {caller} {calls}×/{tiles} т' for caller, (calls, tiles) in sorted(ring_calls.items())),
              flush=True)
    ring_calls.clear()
    for name in count_names:
        counts[name] = 0
    if GUARD_LOG and ft.swaps != start_swaps:
        host2 = model.page_bytes(0x4B)
        sym = report['symbols']

        def guard_word(name: str) -> int:
            at = sym[name] - 0xC000
            return host2[at] | (host2[at + 1] << 8)

        guard_rows.append([frame, guard_word('LG_LAST_E'), guard_word('LG_LAST_C'),
                           host2[sym['LG_SINCE'] - 0xC000], host2[sym['LG_HOLD'] - 0xC000],
                           host2[sym['LG_VALID'] - 0xC000], guard_word('LG_COMMANDS')])
    if OBJECTS_PATH and frame >= 2:
        census_frame(frame)
    if HOSTVARS_PATH:
        host_page = model.page_bytes(0x0C)
        values = []
        for name in ('VIDEO_MISSING', 'VIDEO_OVERFLOW', 'VIDEO_UPLOADS'):
            at = report['symbols'][name] - 0xC000
            values.append(host_page[at] | (host_page[at + 1] << 8))
        if hostvar_last[0] is not None:
            deltas = [(value - old) & 0xFFFF for value, old in zip(values, hostvar_last[0])]
            if deltas[0] or deltas[1]:
                hostvar_rows.append([frame] + deltas)
        hostvar_last[0] = values
    if PEEKS and first <= frame <= last:
        print(f'кадр {frame}: ' + ' | '.join(f'{page:02X}:{offset:04X} ' +
                                           model.page_bytes(page)[offset:offset + length].hex()
                                           for page, offset, length in PEEKS), flush=True)
    if OBJSEQ_FIRST <= frame <= OBJSEQ_LAST:
        objseq_frame(frame)
    if frame in SPRITE_FRAMES:
        state_page = model.page_bytes(0xC0)
        host_page = model.page_bytes(0x0C)
        at = report['symbols']['SPRITE_BYTES'] - 0xC000
        sprite_bytes = host_page[at] | (host_page[at + 1] << 8)
        words_at = report['symbols']['SPRITE_WORDS']
        (SPRITE_DIR / f'sprite_temp_{frame:05d}.bin').write_bytes(state_page[0x0E00:0x1200])
        (SPRITE_DIR / f'sprite_words_{frame:05d}.bin').write_bytes(state_page[words_at:words_at + sprite_bytes])
    if STAGE_LOG:
        stage_page = report['v30_page_base'] + 0x10      # V30 #40000…#43FFF — страница рабочего ОЗУ
        stage = next((model.memory[window * 0x4000 + 0x2FCD] for window, mapped in enumerate(model.windows)
                      if mapped == stage_page), None)
        if stage is None:
            stage = model.page(stage_page)[0x2FCD]
        if not stage_marks or stage_marks[-1][1] != stage:
            stage_marks.append([frame, int(stage)])
    if first <= frame <= last:
        stats['ticks'] += now() - start_time
        stats['frames'] += 1
        stats['swaps'] += ft.swaps - start_swaps
        if STAGE_LOG and stage_marks:
            # По этапам (RT_STAGELOG): такты и шаги этапа — скорость каждого этапа в итоге прогона.
            per = stage_stats.setdefault(stage_marks[-1][1], [0, 0, 0])
            per[0] += now() - start_time
            per[1] += 1
            per[2] += ft.swaps - start_swaps
if ring_uniform_path:
    Path(ring_uniform_path).write_text(json.dumps(ring_uniform_frames) + '\n', encoding='utf-8')
if STAGE_LOG:
    Path(STAGE_LOG).write_text(json.dumps(stage_marks) + '\n', encoding='utf-8')
if GUARD_LOG:
    Path(GUARD_LOG).write_text(json.dumps(guard_rows) + '\n', encoding='utf-8')
if OBJECTS_PATH:
    Path(OBJECTS_PATH).write_text(json.dumps(object_census) + '\n', encoding='utf-8')
if OBJSEQ_PATH:
    Path(OBJSEQ_PATH).write_text(json.dumps(objseq_rows) + '\n', encoding='utf-8')
if HOSTVARS_PATH:
    Path(HOSTVARS_PATH).write_text(json.dumps(hostvar_rows) + '\n', encoding='utf-8')
if HAZARD_PATH:
    Path(HAZARD_PATH).write_text(json.dumps(hazard_rows) + '\n', encoding='utf-8')
seconds = stats['ticks'] / 14_000_000
print(f'режимы {sorted(modes) or ["как собрано"]}: кадры {first}…{last} — {seconds:.1f} с реального времени, '
      f'шагов игры {stats["frames"] / seconds:.1f}/с ({stats["frames"] / seconds / 55.017 * 100:.0f}% скорости M72), '
      f'показано кадров {stats["swaps"] / seconds:.1f}/с')
if drawn_expected is not None:
    shifts = drawn_stats['shift']
    print(f'показанное против опорных (RT_DRAWN): кадров {drawn_stats["shown"]}, совпало {shifts[0]}, '
          f'иных {len(drawn_stats["other"])}, первые {drawn_stats["other"][:12]}; совпадений со сдвигом −1 и +1: '
          f'{shifts[-1]}, {shifts[1]}')
    if DRAWN_OUT:
        Path(DRAWN_OUT).write_text(json.dumps(drawn_stats['other']) + '\n', encoding='utf-8')
    if PIXELS_OUT:
        Path(PIXELS_OUT).write_text(json.dumps(pixels_rows) + '\n', encoding='utf-8')
if swap_gaps:
    gaps_total = sum(swap_gaps.values())
    print('промежутки между показами, кадров развёртки: ' +
          ', '.join(f'{gap}: {count * 100 / gaps_total:.1f}%' for gap, count in sorted(swap_gaps.items())) +
          f'; наибольший {max(swap_gaps)}')
if caller_hist:
    import bisect
    import re as _re
    pages_labels: dict = {}
    for filename, label_page in (('v30z80_runtime.asm', -1), ('v30z80_kernels.asm', -1), ('v30z80_ring.asm', -1),
                                 ('vdac2p_early.asm', -1), ('vdac2p_sprites.asm', -1), ('vdac2p_native.asm', 0x4A),
                                 ('vdac2p_host2.asm', 0x4B), ('vdac2p_guard.asm', 0x4B), ('vdac2p_objects.asm', 0x4B),
                                 ('vdac2p_sprclear.asm', 0x4B), ('vdac2p_palettes.asm', 0x4B), ('vdac2p_native_h2.asm', 0x4B), ('v30z80_host.asm', 0x0C)):
        text = (ROOT / 'Source' / 'ASM' / filename).read_text(encoding='utf-8')
        for name in _re.findall(r'^([A-Za-z_][\w]*):', text, flags=_re.MULTILINE):
            if name in report['symbols']:
                pages_labels.setdefault(label_page, []).append((report['symbols'][name], name))
    # Переведённый код (2026-09-26): вызов из страницы кода — метка A_ инструкции (прежде — ближайшая метка резидента).
    for _key, _code_page in report['page_of'].items():
        _name = f'A_{_key}'
        if _name in report['symbols']:
            pages_labels.setdefault(_code_page, []).append((report['symbols'][_name], _name))
    for _page2 in report.get('native_pages', [])[1:2]:
        pages_labels.setdefault(_page2, []).extend(
            (address, name) for name, address in report['symbols'].items()
            if name.startswith('n2.') and name.count('.') == 1 and isinstance(address, int))
    for labels in pages_labels.values():
        labels.sort()
    grouped: dict = {}
    for (name, page, back), calls in caller_hist.items():
        labels = pages_labels.get(page if page in pages_labels else -1, [])
        index = bisect.bisect_right(labels, (back, chr(0xFFFF))) - 1
        caller = labels[index][1] if index >= 0 else f'#{back:04X}'
        grouped[(name, caller)] = grouped.get((name, caller), 0) + calls
    steps = max(1, stats['frames'])
    for (name, caller), calls in sorted(grouped.items(), key=lambda item: -item[1])[:40]:
        print(f'  {name} ← {caller}: {calls / steps:.1f} на шаг')
if obj_memo is not None and obj_memo['calls']:
    print(f"ObjEntry: вызовов {obj_memo['calls']}, ключ той же записи как в прошлый раз — "
          f"{obj_memo['same'] * 100 / obj_memo['calls']:.1f} %, ключ уже встречался — {obj_memo['any'] * 100 / obj_memo['calls']:.1f} %")
if obj_log is not None:
    seen: dict = {}
    repeats = []
    for frame_at, code, pal, klass in obj_log:
        key = (code, pal, klass)
        if key in seen:
            repeats.append(frame_at - seen[key])
        seen[key] = frame_at
    repeats.sort()
    print(f'загрузок объектов: {len(obj_log)}, ключей {len(seen)}, повторных {len(repeats)}' +
          (f' (через кадров: медиана {repeats[len(repeats) // 2]}, 10 % — {repeats[len(repeats) // 10]}, '
           f'90 % — {repeats[len(repeats) * 9 // 10]})' if repeats else ''))
    by_class: dict = {}
    for _, _, _, klass in obj_log:
        by_class[klass] = by_class.get(klass, 0) + 1
    print('  по классам: ' + ', '.join(f'{klass}: {count}' for klass, count in sorted(by_class.items())))
if desc_log:
    calls = len(desc_log)
    rom = [(bx, pair) for es, bx, pair in desc_log if es == 0x1000]
    print(f'описания: {calls} вызовов, ES = #1000 — {len(rom)}, различных BX — {len(set(bx for bx, _ in rom))}')
    for entries in (32, 64, 128, 256):
        for name, hash_of in (('L+H', lambda bx: (bx & 0xFF) + (bx >> 8)), ('BX/2', lambda bx: bx >> 1),
                              ('BX/6', lambda bx: bx // 6)):
            tags = {}
            hits = 0
            for bx, pair in rom:
                keys = (bx, bx + 6) if pair else (bx,)
                for key in keys:
                    index = hash_of(key) % entries
                    if tags.get(index) == key:
                        hits += 1
                    else:
                        tags[index] = key
            total = sum(2 if pair else 1 for _, pair in rom)
            print(f'  кэш {entries:3} записей, индекс {name}: попаданий {hits * 100 / max(total, 1):.1f} %')
if stage_stats:
    print('по этапам, шагов/с: ' + ', '.join(f'{stage}: {count / (ticks / 14_000_000):.1f}'
                                          for stage, (ticks, count, _) in sorted(stage_stats.items()) if stage and ticks))
    print('по этапам, показано кадров/с: ' + ', '.join(f'{stage}: {swaps / (ticks / 14_000_000):.1f}'
                                                     for stage, (ticks, _, swaps) in sorted(stage_stats.items())
                                                     if stage and ticks))
if profile_path:
    Path(profile_path).write_text(json.dumps({'profile': profile}, ensure_ascii=False) + '\n', encoding='utf-8')
if object_profile is not None:
    Path(OBJECT_PROFILE_PATH).write_text(json.dumps(object_profile, ensure_ascii=False) + '\n', encoding='utf-8')
    total_ticks = sum(profile.values()) or 1
    print('по обработчикам объектов (доля всех тактов): ' + ', '.join(
        f'{key} {value * 100 / total_ticks:.1f} %' for key, value in sorted(object_profile.items(),
                                                                            key=lambda item: -item[1])[:16]))
    if OBJECT_FOCUS:
        # Полная разбивка ключей — рядом с профилем объектов (файл .focus.json): для подсчёта доли перевода по обработчику.
        Path(OBJECT_PROFILE_PATH + '.focus.json').write_text(
            json.dumps({'total': total_ticks, 'focus': focus_profile}, ensure_ascii=False) + '\n', encoding='utf-8')
    for focus_key in OBJECT_FOCUS:
        print(f'{focus_key} по процедурам (доля всех тактов): ' + ', '.join(
            f'{key} {value * 100 / total_ticks:.2f} %' for key, value in sorted(focus_profile.get(focus_key, {}).items(),
                                                                                key=lambda item: -item[1])[:24]))

