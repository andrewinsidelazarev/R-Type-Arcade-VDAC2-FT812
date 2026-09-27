"""Генерация ассемблера Z80 (sjasmplus) из инструкций V30.

Каждая инструкция — метка `A_<линейный адрес>` и фрагмент по шаблону её формы.
Регистры V30 лежат в резидентной части (V_AX..V_DI, V_ES..V_DS, V_FL); флаги
записываются в V_FL, только если живы.

Память. Если значение сегмента перед инструкцией известно (анализ segments.py), страница
V30 байта вычисляется без базы сегмента: рабочее ОЗУ (#10) всегда в окне W1 (#4000) —
для DS/SS = #4000 при смещении < #4000; иначе страница = страница базы + старшие 2 бита
(смещение + остаток базы), она отображается в W2 (#8000) с проверкой W2_PAGE. Обращение
идёт напрямую через (HL); слово на границе страницы, перенос за 64 КБ, сегмент, чьи 4
страницы задевают рабочее ОЗУ, и неизвестный сегмент — через подпрограммы резидента
RB/RW/WB/WW. Память палитры — обычные страницы: ROM не пишет в зеркальные адреса палитры, и
канонические палитры эталона совпадают с ней (это проверяет сверка). Стек при SS = #4000 — напрямую при чётном SP < #4000.

Стек. При SS = #4000 указатель стека Z80 — это SP V30 со смещением #4000: PUSH/POP V30 —
команды push/pop Z80 (строки с пометкой `; v30`), слово ложится в рабочее ОЗУ по x86.
Подпрограммам резидента и сохранению F нужен свой стек: такие строки фрагмента
окружаются переключением на HELPER_TOP (`switch_stack`), иначе адрес возврата Z80 испортил
бы память V30 ниже SP. Стековые команды при другом SS — отказ (в ROM их не исполняют).

Циклы: у пригодных циклов (loopgen.py) перед обычной версией стоит проверка G_<заголовок> и
быстрая версия F_<заголовок>_<адрес> с прямым доступом к памяти через IX/IY; внешние переходы
на заголовок идут на проверку, обратные переходы обычной версии — на A_<заголовок>.

Слияние флагов: условный переход сразу за cmp/sub/add/test/and/or/xor/inc/dec/neg, в
который нельзя попасть иначе, проверяет флаги Z80 после операции; в V_FL пишутся только
флаги, живые после перехода.

Код раскладывается по страницам окна #C000 по оценке размера фрагментов; переход в
другую страницу — через FARJP резидента.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .decode import CODE_BASE, Imm, Instruction, Mem, Reg, SReg
from .discover import NO_FALLTHROUGH
from . import loopgen, loops, peephole
from .flags import O as FLAG_O
from .flags import effect, materialize

REG16 = ['V_AX', 'V_CX', 'V_DX', 'V_BX', 'V_SP', 'V_BP', 'V_SI', 'V_DI']
REG8 = ['V_AX', 'V_CX', 'V_DX', 'V_BX', 'V_AX+1', 'V_CX+1', 'V_DX+1', 'V_BX+1']
SEG = ['ES', 'CS', 'SS', 'DS']
SREG = ['V_ES', 'V_CS', 'V_SS', 'V_DS']
PAGE_LIMIT = 15200
WORK_PAGE = 0x10                 # рабочее ОЗУ #40000..#43FFF — окно W1
# Ядра резидента (Source/ASM/v30z80_kernels.asm): вход процедуры ROM → нативная реализация с теми же
# записями в память V30; регистры на выходе у этих процедур не живут либо ядро ставит их как ROM (оговорено у ядра).
KERNELS = {
    0x0EF02: 'KERNEL_METATILE_B',               # метатайл 6×8 в VRAM слоя B (IP $EB02)
    0x0EE95: 'KERNEL_METATILE_A',               # метатайл 6×8 в VRAM слоя A (IP $EA95)
    0x01FCC: 'KERNEL_SPRITE_ADD',               # вывод спрайта объекта в память спрайтов (IP $1BCC)
    0x01FE9: 'KERNEL_SPRITE_PUT',               # его продолжение с готовым SI (IP $1BE9)
    0x0F978: 'KERNEL_COLLIDE_78',               # прямоугольник объекта против записи DS:SI (IP $F578)
    0x0F885: 'KERNEL_COLLIDE_85',               # сканы записей столкновений (IP $F485 … $F560)
    0x0F893: 'KERNEL_COLLIDE_93',
    0x0F8AA: 'KERNEL_COLLIDE_AA',
    0x0F8BF: 'KERNEL_COLLIDE_BF',
    0x0F948: 'KERNEL_COLLIDE_48',
    0x0F960: 'KERNEL_COLLIDE_60',
    0x0FA94: 'KERNEL_COLLIDE_A94',              # цепочка сканов для объекта с BX = DI (IP $F694)
    0x00657: 'KERNEL_OBJECTS_A',                # цикл слотов объектов (IP $0257): CALL [bp]
    0x00666: 'KERNEL_OBJECTS_B',                # цикл списка объектов (IP $0266): CALL [bp]
    0x0065C: 'KERNEL_OBJECTS_A_RET',            # возврат обработчика в цикл слотов (IP $025C)
    0x0066A: 'KERNEL_OBJECTS_B_RET',            # возврат обработчика в цикл списка (IP $026A)
    0x0F9C1: 'KERNEL_SCRIPT',                   # скрипт движения объекта (IP $F5C1)
    0x0FA3A: 'KERNEL_COUNTER',                  # счётчик периода объекта (IP $F63A)
    0x0226C: 'KERNEL_TERRAIN_A',                # тайл VRAM слоя A под точкой объекта (IP $1E6C; AX, BX, CX живут)
    0x022B5: 'KERNEL_TERRAIN_AB',               # тайлы слоёв A и B (IP $1EB5; AX, BX, CX, DI живут)
    0x03CF4: 'KERNEL_HITBOX',                   # прямоугольник объекта из таблицы ES:SI (IP $38F4; AX…SI живут)
    0x03D24: 'KERNEL_HITBOX_FIXED',             # прямоугольник объекта #80…#82 (IP $3924)
}
# Нативные процедуры VDAC2+ (Source/ASM/vdac2p_native.asm, свои страницы окна #C000): вход процедуры ROM → нативная
# реализация. Переход в неё — FARJP (A = страница метки, HL = метка); возврат — адрес возврата V30 со стека и DISPATCH,
# как у RET. K_ за переходом — обычный перевод с того же места (нативная процедура уходит туда, если случай не её).
# Процедура оставляет память V30, регистры и живые после RET флаги (V_FL) такими же, как ROM.
NATIVE: dict[int, str] = {
    0x0201B: 'N_1C1B',                          # пара спрайтов объекта в память спрайтов (IP $1C1B)
    0x02B36: 'n2.N_2736',                          # разрушаемые тайлы у точки объекта (IP $2736)
    0x02EB4: 'n2.N_2AB4',                          # Force у рельефа (IP $2AB4)
    0x0216B: 'N_1D6B',                          # объект на поле? (IP $1D6B)
    0x00867: 'N_0467',                          # четыре интегратора прокрутки (IP $0467)
    0x053D2: 'n2.N_4FD2',                          # полоса заряда BEAM в VRAM (IP $4FD2)
    0x0997C: 'n2.N_957C',                          # спрайт звена составного объекта (IP $957C)
    0x0FADA: 'N_F6DA',
    0x0FB5F: 'N_F75F',                          # урон с четвёртым сканом $F525 (2026-09-25)
    0x055EE: 'N_51EE',
    0x02B02: 'n2.N_2702',
    0x007A6: 'N_03A6',
    0x042C4: 'n2.N_3EC4',
    0x05340: 'n2.N_4F40',
    0x00703: 'N_0303',
    0x02189: 'N_1D89',
    0x073D0: 'N_6FD0',
    0x07448: 'N_7048',
    0x07506: 'N_7106',
    0x0EA03: 'N_E603',
    0x05E2B: 'N_5A2B',
    0x028CE: 'N_24CE',
    0x03150: 'n2.N_2D50',
    0x02427: 'n2.N_2027',
    0x08C61: 'N_8861',
    0x0E557: 'N_E157',                          # турели этапа 3 (обработчики объекта, 2026-09-25)
    0x0E6AA: 'N_E2AA',
    0x0CBC3: 'N_C7C3',                          # часть линкора этапа 3 (2026-09-26)
    0x0EBD4: 'n2.N_E7D4',                          # взрыв, все этапы (2026-09-26)
    0x08DB0: 'N_89B0',                          # враг этапов 4 и 7, два состояния (2026-09-26)
    0x08EEE: 'N_8AEE',
    0x07902: 'N_7502',                          # семейство врагов этапа 7 и снаряд (2026-09-26)
    0x0799F: 'N_759F',
    0x07A54: 'N_7654',
    0x07AAC: 'N_76AC',
    0x07B19: 'N_7719',
    0x07C0E: 'N_780E',
    0x0FFED: 'n2.N_FBED',                          # таймер вспышки палитры этапа 6 (2026-09-26)
    0x0EAC0: 'N_E6C0',                          # снаряд врага этапов 3, 5 (2026-09-26)
    0x04157: 'n2.N_3D57',                          # кадры вспышки оружия (2026-09-26)
    0x09386: 'n2.N_8F86',                       # пожиратель блоков этапа 4: два состояния и продолжения
    0x09396: 'n2.N_8F96',                       # после сканов $F694 (2026-09-26)
    0x094A2: 'n2.N_90A2',
    0x094AE: 'n2.N_90AE',
    0x0C8BC: 'n2.N_C4BC',                       # управление линкором этапа 3 (2026-09-26)
    0x00663: 'n2.N_0263',                       # цикл списка объектов IRQ0: начало и конец — кэш столкновений
    0x00677: 'n2.N_0277',                       # (2026-09-26)
    0x004FE: 'n2.N_00FE',                       # IRQ0: вход до переноса палитр (2026-09-26)
    0x00553: 'n2.N_0153',                       # IRQ0: продолжение до директора
    0x006EE: 'n2.N_02EE',                       # IRQ2: прокрутка второй половины кадра
    0x0F07B: 'n2.N_EC7B',                       # печать панели целиком (2026-09-26)
    0x0F061: 'n2.N_EC61',                          # заливка ячеек панели при уничтожении (2026-09-26)
    0x037A1: 'n2.N_33A1',                       # ракеты игрока — вторая нативная страница (2026-09-26)
    0x03912: 'n2.N_3512',
    0x03A0A: 'n2.N_360A',
    0x03A6D: 'n2.N_366D',
    0x03BDC: 'n2.N_37DC',
    0x03CD4: 'n2.N_38D4',
    0x01FA7: 'n2.N_1BA7',                       # сценарий уровня, общий путь без порождения (2026-09-26)
    0x052D8: 'n2.N_4ED8',                       # ожидание пуска оружия, след, объект запуска (2026-09-26)
    0x03470: 'n2.N_3070',
    0x032A6: 'n2.N_2EA6',
    0x0BD97: 'N_B997',                          # враги этапов 7, 5, 2, 6 со столкновениями (2026-09-26)
    0x0BDFD: 'N_B9FD',
    0x07DC1: 'N_79C1',
    0x09215: 'N_8E15',
    0x05FA4: 'N_5BA4',
    0x0603E: 'N_5C3E',
    0x020A6: 'N_1CA6',                          # три спрайта объекта (2026-09-26)
    0x0D7C9: 'N_D3C9',                          # часть линкора этапа 3 (2026-09-26)
    0x06DB4: 'N_69B4',                          # враги этапов 4, 6, 3 со столкновениями (2026-09-26)
    0x07835: 'N_7435',
    0x0DF02: 'N_DB02',
    0x0633C: 'N_5F3C',                          # враги этапа 6 (2026-09-25)
    0x076D2: 'N_72D2',                          # враг этапа 6 (2026-09-25)
    0x0771E: 'N_731E',                          # его продолжение после выстрела (2026-09-26)
    0x07FFC: 'N_7BFC',                          # звено червя этапа 5: следование и уход (2026-09-25)
    0x080D3: 'N_7CD3',
    0x0DFB5: 'N_DBB5',                          # части линкора этапа 3 (2026-09-25)
    0x0DD0E: 'N_D90E',
    0x0CD3F: 'N_C93F',                          # столкновения части линкора: четыре скана за одну подготовку
    0x0EC65: 'KERNEL_VRAM_FILL_A200',           # заливка VRAM слоя A с DI = #200 (IP $E865; из ядер резидента)
    0x0EC83: 'KERNEL_VRAM_FILL_A',              # заливка всей VRAM слоя A (IP $E883)
    0x0ECA0: 'KERNEL_VRAM_FILL_B',              # заливка всей VRAM слоя B (IP $E8A0)
    0x0565A: 'KERNEL_PAL_TRANSFER',             # перенос палитр в память палитр (IP $525A, из IRQ0 $0550; из ядер резидента)
    0x05701: 'KERNEL_PALETTES',                 # менеджер палитр (IP $5301, из IRQ0 $068C; из ядер резидента)
    0x00A53: 'KERNEL_SPRITE_CLEAR',             # обнуление свободных записей памяти спрайтов (IP $0653; вторая
                                                # страница хоста — NATIVE_HOST2)
}
# Входы NATIVE не в нативной странице, а во второй странице хоста (vdac2p_host2.asm): диспетчеризация ведёт их туда
# (dispatch_target, host2_page); заглушка перевода берёт страницу метки сама ($$).
NATIVE_HOST2 = frozenset({'KERNEL_SPRITE_CLEAR', 'KERNEL_VRAM_FILL_A200', 'KERNEL_VRAM_FILL_A', 'KERNEL_VRAM_FILL_B',
                          'KERNEL_PAL_TRANSFER', 'KERNEL_PALETTES',     # заливки и палитры — с 2026-09-25
                          'N_1D6B', 'N_0467', 'N_51EE', 'N_03A6'})      # vdac2p_native_h2.asm — с 2026-09-25
# Хвосты нативных процедур (NTAIL/NSUBTAIL A_xxxxx в vdac2p_native.asm) входят в перевод не сверху: регистры Z80,
# флаги и страница W2 в этих точках неизвестны, как у цели перехода. Без этого перевод держал DL в A через метку
# (A_02492: inc a после A_02488), и хвост автопилота $2027 портил выбор цели.
NATIVE_SOURCE = Path(__file__).resolve().parents[2] / 'ASM' / 'vdac2p_native.asm'
# Вторая нативная страница (2026-09-26): её код — vdac2p_native2.asm, модуль n2 (метки входов NATIVE — n2.N_…).
NATIVE2_SOURCE = NATIVE_SOURCE.with_name('vdac2p_native2.asm')
NATIVE2_PREFIX = 'n2.'


def native_tail_targets() -> set[int]:
    """Линейные адреса меток A_ из текста нативных процедур (пусто, если файла нет)."""
    targets = set()
    for source in (NATIVE_SOURCE, NATIVE2_SOURCE):
        if source.exists():
            text = source.read_text(encoding='utf-8')
            targets |= {int(match, 16) for match in re.findall(r'\bA_([0-9A-F]{5})\b', text)}
    return targets
# Страницы V30 с пометками изменений для адаптера FT812: палитры #C8000, #CC000 и VRAM #D0000, #D8000.
VIDEO_PAGES = frozenset((0x32, 0x33, 0x34, 0x36))
STACK_SEGMENT = 0x4000

CONDITION = {
    'e': ('and #40', 'nz', 'z'), 'ne': ('and #40', 'z', 'nz'),
    'b': ('rra', 'c', 'nc'), 'ae': ('rra', 'nc', 'c'),
    'be': ('and #41', 'nz', 'z'), 'a': ('and #41', 'z', 'nz'),
    's': ('and #80', 'nz', 'z'), 'ns': ('and #80', 'z', 'nz'),
    'p': ('and #04', 'nz', 'z'), 'np': ('and #04', 'z', 'nz'),
}


# Условный переход по флагам Z80 после операции: шаги ('j', условие Z80 или None — всегда),
# ('skip', условие или None, метка), ('label', метка). Вид операции: arith — add/adc/sub/sbb/
# cmp/neg (S Z C V как у x86), logic8 — and/or/xor/test над байтом (S Z P, C = 0),
# inc8 — inc/dec байта (S Z V; CF x86 не меняется), test16 — после проверки HL: Z (`ld a,h`,
# `or l`) или S (`bit 7,h`).
ARITH_FUSED = {
    'e': [('j', 'z')], 'ne': [('j', 'nz')], 'b': [('j', 'c')], 'ae': [('j', 'nc')],
    's': [('j', 'm')], 'ns': [('j', 'p')], 'o': [('j', 'pe')], 'no': [('j', 'po')],
    'be': [('j', 'c'), ('j', 'z')], 'a': [('skip', 'c', 'x'), ('j', 'nz'), ('label', 'x')],
    'l': [('skip', 'po', 'v'), ('j', 'p'), ('skip', None, 'x'), ('label', 'v'), ('j', 'm'), ('label', 'x')],
    'ge': [('skip', 'po', 'v'), ('j', 'm'), ('skip', None, 'x'), ('label', 'v'), ('j', 'p'), ('label', 'x')],
    'le': [('j', 'z'), ('skip', 'po', 'v'), ('j', 'p'), ('skip', None, 'x'), ('label', 'v'), ('j', 'm'),
           ('label', 'x')],
    'g': [('skip', 'z', 'x'), ('skip', 'po', 'v'), ('j', 'm'), ('skip', None, 'x'), ('label', 'v'), ('j', 'p'),
          ('label', 'x')],
}
FUSED = {
    'arith': ARITH_FUSED,
    'logic8': {
        'e': [('j', 'z')], 'ne': [('j', 'nz')], 's': [('j', 'm')], 'ns': [('j', 'p')], 'p': [('j', 'pe')],
        'np': [('j', 'po')], 'b': [], 'ae': [('j', None)], 'o': [], 'no': [('j', None)], 'be': [('j', 'z')],
        'a': [('j', 'nz')], 'l': [('j', 'm')], 'ge': [('j', 'p')], 'le': [('j', 'z'), ('j', 'm')],
        'g': [('skip', 'z', 'x'), ('j', 'p'), ('label', 'x')],
    },
    'inc8': {key: ARITH_FUSED[key] for key in ('e', 'ne', 's', 'ns', 'o', 'no', 'l', 'ge', 'le', 'g')},
    # 16-битная логика: CF = OF = 0.
    'logic16': {'e': 'z', 'ne': 'nz', 'be': 'z', 'a': 'nz', 's': 's', 'ns': 'ns', 'l': 's', 'ge': 'ns',
                'b': 'never', 'ae': 'always', 'o': 'never', 'no': 'always'},
    'inc16': {'e': 'z', 'ne': 'nz', 's': 's', 'ns': 'ns'},
}
TEST16 = {
    'z': (['ld a,h', 'or l'], [('j', 'z')]), 'nz': (['ld a,h', 'or l'], [('j', 'nz')]),
    's': (['bit 7,h'], [('j', 'nz')]), 'ns': (['bit 7,h'], [('j', 'z')]),
    'never': ([], []), 'always': ([], [('j', None)]),
}
Z80_INVERSE = {'z': 'nz', 'nz': 'z', 'c': 'nc', 'nc': 'c', 'm': 'p', 'p': 'm', 'pe': 'po', 'po': 'pe'}


class CodegenError(Exception):
    pass


def label(address: int) -> str:
    return f'A_{address:05X}'


def hex16(value: int) -> str:
    return f'#{value & 0xFFFF:04X}'


def hex8(value: int) -> str:
    return f'#{value & 0xFF:02X}'


# Размеры строк для раскладки по страницам (с запасом).
SIZE_RULES = [
    (re.compile(r'^(ld|add|adc|sbc|sub|and|or|xor|cp) [abcdehl],[abcdehl]$'), 1),
    (re.compile(r'^(ld (hl|de|bc),#)'), 3),
    (re.compile(r'^ld hl,\('), 3),
    (re.compile(r'^ld \([^)]*\),hl$'), 3),
    (re.compile(r'^ld (de|bc|sp),\('), 4),
    (re.compile(r'^ld \([^)]*\),(de|bc|sp)$'), 4),
    (re.compile(r'^ld a,\([^h]'), 3),
    (re.compile(r'^ld \([^h][^)]*\),a$'), 3),
    (re.compile(r'^ld [abcdehl],#'), 2),
    (re.compile(r'^ld [abcdehl],\(hl\)$'), 1),
    (re.compile(r'^ld \(hl\),[abcdehl]$'), 1),
    (re.compile(r'^ld a,\(bc\)$|^ld \(bc\),a$'), 1),
    (re.compile(r'^ld a,\$\$'), 2),
    (re.compile(r'^ld hl,A_'), 3),
    (re.compile(r'^(call|jp) '), 3),
    (re.compile(r'^jr '), 2),
    (re.compile(r'^(adc|sbc) hl,'), 2),
    (re.compile(r'^(add hl,|inc hl|dec hl|inc de|dec de|ex de,hl|push|pop|or a|cpl|rra|rla|rlca|rrca|scf|ccf)'), 1),
    (re.compile(r'^(and|or|xor|sub|cp|add a,|adc a,|sbc a,) ?#'), 2),
    (re.compile(r'^(and|or|xor|sub|cp|add a,|adc a,|sbc a,) ?[abcdehl]$'), 1),
    (re.compile(r'^(inc|dec) [abcdehl]$'), 1),
    (re.compile(r'^(bit|set|res) '), 2),
]


def line_size(text: str) -> int:
    text = text.split(';')[0].strip()
    if not text or text.endswith(':') or text.startswith(';'):
        return 0
    for pattern, size in SIZE_RULES:
        if pattern.search(text):
            return size
    return 4


@dataclass
class Fragment:
    instruction: Instruction
    lines: list[str] = field(default_factory=list)
    jumps: list[tuple[str, int, str | None]] = field(default_factory=list)   # (метка-заглушка, цель, условие)
    counter: int = 0
    materialized: bool = False      # быстрая версия: регистры уже восстановлены перед выходом
    bc_saved: bool = False          # быстрая версия: шаблон портит BC, V_CX записан до него

    def local(self) -> int:
        self.counter += 1
        return self.counter


class Generator:
    def __init__(self, program, live_out: dict[int, int], idle_points: dict[int, tuple[int, int]],
                 seg_values: dict[int, tuple] | None = None, memory_pages: dict[int, dict[int, int]] | None = None,
                 instruction_counts: dict[int, int] | None = None, function_map=None) -> None:
        self.program = program
        # Карта функций (functions.build): места вызова и RET — для предсказания возврата (op_ret).
        self.function_map = function_map
        # Число исполнений инструкций по трассе эталона (адрес → число).
        self.instruction_counts = instruction_counts or {}
        self.live_out = live_out
        self.idle_points = idle_points
        self.seg_values = seg_values or {}
        # Страницы V30 обращений инструкции к данным по трассе эталона (адрес → страница → число).
        self.memory_pages = memory_pages or {}
        # Пары (операция → условный переход сразу за ней, достижимый только из неё). Входы
        # только из констант сюда не входят: диспетчеризация на них идёт через заглушки —
        # копии кода от входа до точки слияния; место, где заглушка возвращается в основной
        # код, считается достижимым не только сверху.
        reachable_otherwise = (set(program.labels) | (set(program.entries) - program.constant_only) |
                               set(idle_points) | (native_tail_targets() & set(program.instructions)))
        self.stub_runs: dict[int, list[int]] = {}
        stops = set(reachable_otherwise)
        for entry in sorted(program.constant_only):
            if entry in idle_points or entry not in program.instructions:
                continue
            run = []
            address = entry
            while address in program.instructions and (address == entry or address not in stops):
                instruction = program.instructions[address]
                if len(run) >= self.STUB_LIMIT and instruction.mnemonic != 'jcc':
                    break
                run.append(address)
                if instruction.mnemonic in NO_FALLTHROUGH:
                    address = None
                    break
                address = instruction.next
            self.stub_runs[entry] = run
            if address is not None:
                reachable_otherwise.add(address)
        fallthrough_count: dict[int, int] = {}
        for instruction in program.instructions.values():
            if instruction.mnemonic not in NO_FALLTHROUGH:
                fallthrough_count[instruction.next] = fallthrough_count.get(instruction.next, 0) + 1
        self.reachable_otherwise = reachable_otherwise
        self.fallthrough_count = fallthrough_count
        # Известная страница окна W2 в текущей точке генерации (None — неизвестна) и
        # предыдущая сгенерированная инструкция: состояние переходит только по проходу сверху.
        self.w2: int | None = None
        self.previous: Instruction | None = None
        # План быстрой версии цикла, для которого сейчас генерируется тело (или None).
        self.loop_plan: loopgen.Plan | None = None
        # Цепочка: несколько условных переходов подряд (у логики и inc/dec над словом — один).
        self.fusion: dict[int, list[Instruction]] = {}
        self.fused_jumps: dict[int, str] = {}

        def only_from_previous(jump) -> bool:
            return (jump is not None and jump.mnemonic == 'jcc' and jump.address not in reachable_otherwise
                    and fallthrough_count.get(jump.address, 0) == 1)

        for address, instruction in program.instructions.items():
            if address in idle_points:
                continue
            kind = self.fusion_kind(instruction)
            if kind is None:
                continue
            chain = []
            following = program.instructions.get(instruction.next)
            while only_from_previous(following) and following.condition in FUSED[kind]:
                chain.append(following)
                if kind in ('logic16', 'inc16'):
                    break
                following = program.instructions.get(following.next)
            if chain:
                self.fusion[address] = chain
                for jump in chain:
                    self.fused_jumps[jump.address] = kind

    # --- адрес и доступ к памяти -----------------------------------------------------------
    @staticmethod
    def ea_lines(memory: Mem) -> list[str]:
        """HL = исполнительный адрес; портит BC."""
        if not memory.bases:
            return [f'ld hl,{hex16(memory.disp)}']
        lines = [f'ld hl,({REG16[memory.bases[0]]})']
        if len(memory.bases) == 2:
            lines += [f'ld bc,({REG16[memory.bases[1]]})', 'add hl,bc']
        disp = memory.disp & 0xFFFF
        if disp in (1, 2):
            lines += ['inc hl'] * disp
        elif disp in (0xFFFF, 0xFFFE):
            lines += ['dec hl'] * (0x10000 - disp)
        elif disp:
            lines += [f'ld bc,{hex16(disp)}', 'add hl,bc']
        return lines

    def segment_value(self, instruction: Instruction, segment: int) -> int | None:
        return self.seg_values.get(instruction.address, (None,) * 4)[segment]

    def classify(self, instruction: Instruction, memory: Mem, width: int, write: bool) -> tuple:
        """('dyn',) — подпрограммы; ('abs', страница, адрес Z80); ('work',) — окно W1 при
        смещении < #4000; ('pages', страница базы, остаток базы) — W2 по вычисленной странице;
        ('segdyn',) — сегмент известен только при исполнении, по трассе обращения вне рабочего
        ОЗУ: страница из значения сегмента без остатка базы, иначе подпрограммы."""
        value = self.segment_value(instruction, memory.segment)
        if value is None:
            counts = self.memory_pages.get(instruction.address, {})
            if memory.bases and counts and WORK_PAGE not in counts:
                return ('segdyn',)
            return ('dyn',)
        base = value << 4
        if not memory.bases:
            linear = (base + memory.disp) & 0xFFFFF
            page, offset = linear >> 14, linear & 0x3FFF
            if offset + width > 0x4000:
                return ('dyn',)
            return ('abs', page, (0x4000 if page == WORK_PAGE else 0x8000) + offset)
        page = base >> 14
        if page == WORK_PAGE and not base & 0x3FFF:
            return ('work',)
        pages = range(page, page + 4)
        if page + 3 > 63:
            return ('dyn',)
        # Рабочее ОЗУ (оно в W1) в пределах сегмента — только через подпрограммы: быстрый
        # путь ограничен смещением (с остатком базы) до этой страницы.
        limit = next((index for index, item in enumerate(pages) if item == WORK_PAGE), 4)
        if limit == 0:
            return ('dyn',)
        # Быстрый путь — самая частая по трассе страница из допустимых.
        counts = self.memory_pages.get(instruction.address, {})
        best = max(range(limit), key=lambda index: (counts.get(page + index, 0), -index))
        return ('pages', page, base & 0x3FFF, limit, best)

    def map_page(self, fragment: Fragment, page: int) -> list[str]:
        """Страница V30 в W2 (кроме рабочего ОЗУ): проверка W2_PAGE, либо ничего, если страница
        уже известна по предыдущим инструкциям. Сохраняет HL, DE; портит A, BC."""
        if page == WORK_PAGE:
            return []
        if self.w2 == page:
            return [f'; w2 need {hex8(page)}']
        n = fragment.local()
        self.w2 = page
        return (['ld a,(W2_PAGE)', f'cp {hex8(page)}', f'jr z,.m{n}', f'ld a,{hex8(page)}'] + MAP_W2_LINES +
                [f'.m{n}:', f'; w2 set {hex8(page)}'])

    def layout(self, fragment: Fragment, kind: tuple, width: int, n: int) -> dict:
        """Части обращения по смещению в HL.

        checks — проверки: неудача → .s{n}, основная страница → .f{n}; other — путь остальных
        страниц сегмента (после проверок, заканчивается переходом на .g{n}); restore — HL снова
        смещение в начале медленного пути; main — после .f{n}: W2 и перевод смещения в окно;
        need — строки-пометки опоры на известную W2; after — W2 после обращения (или None).
        """
        size = '#40' if width == 1 else '#3F'
        if kind[0] == 'work':
            # Слово: смещения #3F00..#3FFF — медленный путь (граница страницы).
            return {'checks': ['ld a,h', f'cp {size}', f'jr c,.f{n}'], 'other': [], 'restore': [],
                    'main': ['set 6,h'], 'need': [], 'after': self.w2}
        _, page, remainder, limit, best = kind
        checks = []
        restore = []
        if remainder:
            checks += [f'ld bc,{hex16(remainder)}', 'add hl,bc', f'jr c,.s{n}']
            restore = [f'ld bc,{hex16(remainder)}', 'or a', 'sbc hl,bc']
        if limit < 4:
            # Смещение с остатком базы не дальше `limit` страниц (дальше — рабочее ОЗУ).
            checks += ['ld a,h', f'cp {hex8(limit << 6)}', f'jr nc,.s{n}']
        # Основная страница — base + best: старшие биты смещения, W2 и перевод в окно #8000.
        checks += (['ld a,h', f'cp {size}'] if best == 0 else ['ld a,h', f'sub {hex8(best << 6)}', f'cp {size}'])
        checks.append(f'jr c,.f{n}')
        window = {0: ['set 7,h'], 1: ['res 6,h', 'set 7,h'], 2: [], 3: ['res 6,h']}[best]
        target = page + best
        need = []
        if self.w2 == target:
            need = [f'; w2 need {hex8(target)}']
            main = list(window)
        else:
            main = (['ld a,(W2_PAGE)', f'cp {hex8(target)}', f'jr z,.q{n}', f'ld a,{hex8(target)}'] + MAP_W2_LINES +
                    [f'.q{n}:'] + window)
        other = []
        if limit > 1:
            if width == 2:
                other += ['ld a,h', 'and #3F', 'cp #3F', f'jr z,.s{n}']
            other += (['ld a,h', 'rlca', 'rlca', 'and 3', f'add a,{hex8(page)}', 'ld b,a', 'ld a,(W2_PAGE)', 'cp b',
                       f'jr z,.m{n}', 'ld a,b'] + MAP_W2_LINES + [f'.m{n}:', 'ld a,h', 'or #C0', 'xor #40', 'ld h,a',
                                                                  f'jr .g{n}'])
        return {'checks': checks, 'other': other, 'restore': restore, 'main': main, 'need': need,
                'after': target if limit == 1 else None}

    def emit_access(self, fragment: Fragment, instruction: Instruction, memory: Mem, width: int, write: bool,
                    fast: list[str], slow: list[str], absolute, form: str) -> list[str]:
        """Обращение к памяти: fast — через (HL), slow — подпрограммами при HL = смещение,
        absolute(адрес Z80) — строки при известном адресе. Медленный путь — сразу за
        проверками, быстрый — после перехода на .f (без обходного перехода). В быстрой
        версии цикла — прямое обращение по плану (form: read16, read8, write16, write8)."""
        if self.loop_plan is not None and (instruction.address, memory) in self.loop_plan.access:
            return loopgen.direct_access(self.loop_plan.access[(instruction.address, memory)], form)
        kind = self.classify(instruction, memory, width, write)
        if kind[0] == 'dyn':
            self.w2 = None
            return self.ea_lines(memory) + slow + ['; w2 lost']
        marks = self.video_marks(fragment, kind, form, width)
        if kind[0] == 'abs':
            return self.map_page(fragment, kind[1]) + absolute(hex16(kind[2])) + marks
        if kind[0] == 'segdyn':
            return self.segdyn_access(fragment, memory, width, fast + marks, slow)
        n = fragment.local()
        parts = self.layout(fragment, kind, width, n)
        after = parts['after']
        if after is not None:
            # Подпрограммы могут сменить W2: медленный путь возвращает её, как у быстрого
            # (A и F сохраняются: MAP_W2_LINES не меняют флагов).
            slow_lines = [line + ' ; w2 keep' if line.startswith('call ') else line for line in slow]
            slow_lines += ['push af', f'ld a,{hex8(after)}'] + MAP_W2_LINES + ['pop af']
        else:
            slow_lines = list(slow)
        if (marks and kind[0] == 'pages' and parts['other'] and kind[1] + kind[4] not in VIDEO_PAGES and
                not any(line.endswith(':') for line in fast)):
            # Основная страница — не видео: пометка изменения только на пути остальных страниц
            # сегмента (своя копия записи вместо общего хвоста .g).
            lines = (parts['need'] + self.ea_lines(memory) + parts['checks'] + parts['other'][:-1] + fast + marks +
                     [f'jr .d{n}', f'.s{n}:'] + parts['restore'] + slow_lines + [f'jr .d{n}', f'.f{n}:'] +
                     parts['main'] + fast + [f'.d{n}:'])
        else:
            fast = fast + marks
            lines = (parts['need'] + self.ea_lines(memory) + parts['checks'] + parts['other'] + [f'.s{n}:'] +
                     parts['restore'] + slow_lines + [f'jr .d{n}', f'.f{n}:'] + parts['main'] +
                     ([f'.g{n}:'] if parts['other'] else []) + fast + [f'.d{n}:'])
        self.w2 = after
        lines.append(f'; w2 set {hex8(after)}' if after is not None else '; w2 lost')
        return lines

    def video_marks(self, fragment: Fragment, kind: tuple, form: str, width: int) -> list[str]:
        """Пометка изменения VRAM или палитры для адаптера FT812 после записи быстрого пути
        (медленный путь помечают подпрограммы записи). AF, BC, DE, HL сохраняются, кроме DE у
        абсолютной записи."""
        if form not in ('write16', 'write8', 'rmw'):
            return []
        if kind[0] == 'abs':
            page = kind[1]
            if page not in VIDEO_PAGES:
                return []
            offset = kind[2] & 0x3FFF
            lines = ["ex af,af'", f'ld a,{hex8(page)}']
            for byte in range(width):
                lines += [f'ld de,{hex16(offset + byte)}', 'call VIDEO_MARK_DE']
            return lines + ["ex af,af'"]
        if kind[0] == 'pages':
            _, page, _remainder, limit, _best = kind
            if not any(page + index in VIDEO_PAGES for index in range(limit)):
                return []
        elif kind[0] != 'segdyn':
            return []
        n = fragment.local()
        if width == 2:
            marker = 'VIDEO_W2_MARK2BC' if form == 'rmw' else 'VIDEO_W2_MARK2'
        else:
            marker = 'VIDEO_W2_MARK1'
        return ["ex af,af'", 'ld a,(W2_PAGE)', 'cp #32', f'jr c,.v{n}', 'cp #37', f'jr nc,.v{n}', f'call {marker}',
                f'.v{n}:', "ex af,af'"]

    def segdyn_access(self, fragment: Fragment, memory: Mem, width: int, fast: list[str],
                      slow: list[str]) -> list[str]:
        """Обращение при сегменте, известном только при исполнении. База без остатка (сегмент
        кратен #400: младший байт 0, в старшем биты 0–1 равны 0) — страница V30 = сегмент >> 10 +
        старшие биты смещения; не рабочее ОЗУ и не граница страницы у слова — W2 и (HL);
        иначе подпрограммы. HL = смещение до проверок; портит A, BC."""
        n = fragment.local()
        name = SREG[memory.segment]
        checks = [f'ld a,({name})', 'or a', f'jr nz,.s{n}', f'ld a,({name}+1)', 'ld c,a', 'and #03', f'jr nz,.s{n}']
        if width == 2:
            checks += ['ld a,h', 'and #3F', 'cp #3F', f'jr z,.s{n}']
        checks += (['ld a,h', 'rlca', 'rlca', 'and 3', 'ld b,a', 'ld a,c', 'rrca', 'rrca', 'add a,b', 'and 63',
                    f'cp {hex8(WORK_PAGE)}', f'jr z,.s{n}', 'ld b,a', 'ld a,(W2_PAGE)', 'cp b', f'jr z,.m{n}',
                    'ld a,b'] + MAP_W2_LINES + [f'.m{n}:', 'ld a,h', 'and #3F', 'or #80', 'ld h,a'])
        self.w2 = None
        return (self.ea_lines(memory) + checks + fast + [f'jr .d{n}', f'.s{n}:'] + slow +
                [f'.d{n}:', '; w2 lost'])

    def read16(self, fragment: Fragment, instruction: Instruction, memory: Mem) -> list[str]:
        """DE = слово памяти; портит A, BC, HL."""
        seg = SEG[memory.segment]
        return self.emit_access(fragment, instruction, memory, 2, False, ['ld e,(hl)', 'inc hl', 'ld d,(hl)'],
                                [f'call RW_{seg}'], lambda address: [f'ld de,({address})'], 'read16')

    def read8(self, fragment: Fragment, instruction: Instruction, memory: Mem) -> list[str]:
        """A = байт памяти; портит BC, HL; DE сохраняется."""
        seg = SEG[memory.segment]
        return self.emit_access(fragment, instruction, memory, 1, False, ['ld a,(hl)'], [f'call RB_{seg}'],
                                lambda address: [f'ld a,({address})'], 'read8')

    def write16(self, fragment: Fragment, instruction: Instruction, memory: Mem) -> list[str]:
        """Слово DE в память; портит A, BC, HL."""
        seg = SEG[memory.segment]
        return self.emit_access(fragment, instruction, memory, 2, True, ['ld (hl),e', 'inc hl', 'ld (hl),d'],
                                [f'call WW_{seg}'], lambda address: [f'ld ({address}),de'], 'write16')

    def write8(self, fragment: Fragment, instruction: Instruction, memory: Mem) -> list[str]:
        """Байт E в память; портит A, BC, HL."""
        seg = SEG[memory.segment]
        return self.emit_access(fragment, instruction, memory, 1, True, ['ld (hl),e'], ['ld a,e', f'call WB_{seg}'],
                                lambda address: ['ld a,e', f'ld ({address}),a'], 'write8')

    def rmw16(self, fragment: Fragment, instruction: Instruction, memory: Mem, compute: list[str],
              keep: bool = False) -> list[str]:
        """Слово памяти → HL, `compute` (DE — второй операнд, BC не трогать) → HL, запись HL
        обратно. DE загружен до вызова. keep — F после compute сохраняется до конца."""
        if self.loop_plan is not None and (instruction.address, memory) in self.loop_plan.access:
            return loopgen.direct_rmw16(self.loop_plan.access[(instruction.address, memory)], compute)
        seg = SEG[memory.segment]
        write = ['push af', f'call WW_{seg}', 'pop af'] if keep else [f'call WW_{seg}']
        slow = (['ld (TEMP_EA),hl', 'push de', f'call RW_{seg}', 'ex de,hl', 'pop de'] + compute +
                ['ex de,hl', 'ld hl,(TEMP_EA)'] + write)
        fast = (['ld b,h', 'ld c,l', 'ld a,(hl)', 'inc hl', 'ld h,(hl)', 'ld l,a'] + compute +
                ['ld a,l', 'ld (bc),a', 'inc bc', 'ld a,h', 'ld (bc),a'])
        return self.emit_access(fragment, instruction, memory, 2, True, fast, slow,
                                lambda address: [f'ld hl,({address})'] + compute + [f'ld ({address}),hl'], 'rmw')

    def rmw8(self, fragment: Fragment, instruction: Instruction, memory: Mem, compute, keep: bool = False) -> list[str]:
        """Байт памяти → A, `compute(fast)` (E — второй операнд) → A, запись A обратно.
        compute — функция: fast=True — HL указывает на байт и должен сохраниться.
        keep — F после compute сохраняется до конца."""
        if self.loop_plan is not None and (instruction.address, memory) in self.loop_plan.access:
            return loopgen.direct_rmw8(self.loop_plan.access[(instruction.address, memory)], compute)
        seg = SEG[memory.segment]
        write = ['push af', f'call WB_{seg}', 'pop af'] if keep else [f'call WB_{seg}']
        slow = (['ld (TEMP_EA),hl', 'push de', f'call RB_{seg}', 'pop de'] + compute(False) +
                ['ld hl,(TEMP_EA)'] + write)
        fast = ['ld a,(hl)'] + compute(True) + ['ld (hl),a']
        return self.emit_access(fragment, instruction, memory, 1, True, fast, slow,
                                lambda address: [f'ld a,({address})'] + compute(False) + [f'ld ({address}),a'], 'rmw')

    # --- стек -------------------------------------------------------------------------------
    def stack_direct(self, instruction: Instruction) -> bool:
        return self.segment_value(instruction, 2) == STACK_SEGMENT

    def push_de(self, fragment: Fragment, instruction: Instruction) -> list[str]:
        """Слово DE в стек V30 (стек Z80)."""
        if not self.stack_direct(instruction):
            return [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']
        return ['push de ; v30']

    def pop_de(self, fragment: Fragment, instruction: Instruction) -> list[str]:
        """Слово из стека V30 (стек Z80) → DE."""
        if not self.stack_direct(instruction):
            return [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']
        return ['pop de ; v30']

    @staticmethod
    def segset_lines(index: int) -> list[str]:
        """HL = значение сегментного регистра."""
        return [f'ld (V_{SEG[index]}),hl']

    # --- операнды ------------------------------------------------------------------------
    def load16_de(self, fragment: Fragment, instruction: Instruction, operand) -> list[str]:
        """Значение 16-битного операнда → DE (портит HL, A, BC)."""
        if isinstance(operand, Reg):
            return [f'ld de,({REG16[operand.index]})']
        if isinstance(operand, SReg):
            return [f'ld de,({SREG[operand.index]})']
        if isinstance(operand, Imm):
            return [f'ld de,{hex16(operand.value)}']
        if isinstance(operand, Mem):
            return self.read16(fragment, instruction, operand)
        raise CodegenError(f'операнд {operand}')

    def load8_a(self, fragment: Fragment, instruction: Instruction, operand) -> list[str]:
        """Значение 8-битного операнда → A (портит HL, BC; DE сохраняется)."""
        if isinstance(operand, Reg):
            return [f'ld a,({REG8[operand.index]})']
        if isinstance(operand, Imm):
            return [f'ld a,{hex8(operand.value)}']
        if isinstance(operand, Mem):
            return self.read8(fragment, instruction, operand)
        raise CodegenError(f'операнд {operand}')

    @staticmethod
    def load8_e(operand) -> list[str]:
        """Регистр или константа → E (портит A)."""
        if isinstance(operand, Reg):
            return [f'ld a,({REG8[operand.index]})', 'ld e,a']
        if isinstance(operand, Imm):
            return [f'ld e,{hex8(operand.value)}']
        raise CodegenError(f'операнд {operand}')

    # --- генерация -------------------------------------------------------------------------
    def fragment(self, instruction: Instruction) -> Fragment:
        fragment = Fragment(instruction)
        lines = fragment.lines
        handler = getattr(self, 'op_' + instruction.mnemonic, None)
        if handler is None:
            raise CodegenError(f'{instruction.address:05X}: нет шаблона {instruction.text}')
        previous = self.previous
        if (previous is None or previous.next != instruction.address or previous.mnemonic in NO_FALLTHROUGH
                or instruction.address in self.reachable_otherwise
                or self.fallthrough_count.get(instruction.address, 0) != 1):
            self.w2 = None
        start_w2 = self.w2
        if instruction.address in KERNELS:
            # Вход процедуры с нативным ядром; K_ — обычный перевод с того же места для случаев, которые ядро
            # не берёт (ядро переходит сюда до своих записей в память V30 либо в точке, где они совпадают с ROM).
            lines += [f'jp {KERNELS[instruction.address]}', f'K_{instruction.address:05X}:']
            self.w2 = None
        if instruction.address in NATIVE:
            # У инструкции бывает несколько фрагментов (копии D_ для других сегментов): метка перевода K_ — только у
            # первого, отказ нативной процедуры ведёт туда.
            label = NATIVE[instruction.address]
            lines += [f'ld a,$${label}', f'ld hl,{label}', 'jp FARJP']
            emitted = self.__dict__.setdefault('native_fallbacks', set())
            if instruction.address not in emitted:
                emitted.add(instruction.address)
                lines.append(f'K_{instruction.address:05X}:')
            self.w2 = None
        if instruction.address in self.idle_points:
            # Очередь задач: оба слова в рабочем ОЗУ (окно W1).
            head, tail = self.idle_points[instruction.address]
            if head >> 14 != WORK_PAGE or tail >> 14 != WORK_PAGE:
                raise CodegenError('точка простоя читает не рабочее ОЗУ')
            lines += [f'ld hl,({hex16(0x4000 + (head & 0x3FFF))})', f'ld de,({hex16(0x4000 + (tail & 0x3FFF))})',
                      'or a', 'sbc hl,de', 'jr nz,.run', f'ld de,{hex16(instruction.ip)}', 'jp IDLE_EXIT', '.run:']
        handler(instruction, fragment)
        self.w2 = verify_w2(fragment.lines, start_w2, instruction)
        self.previous = instruction
        fragment.lines[:] = switch_stack(fragment.lines)
        return fragment

    STUB_LIMIT = 8

    def stub_fragments(self, entry: int) -> list[Fragment]:
        """Заглушка входа только из констант: копия проходов от входа с неизвестным состоянием
        (W2, регистры) до естественной точки слияния, безусловного перехода или STUB_LIMIT
        инструкций (цепочка условных переходов дописывается). Условный переход на самом входе
        читает флаги из V_FL."""
        instructions = self.program.instructions
        result = []
        saved = self.fused_jumps.pop(entry, None)
        self.previous = None
        self.w2 = None
        try:
            for address in self.stub_runs[entry]:
                result.append(self.fragment(instructions[address]))
        finally:
            if saved is not None:
                self.fused_jumps[entry] = saved
            self.previous = None
            self.w2 = None
        return result

    def loop_fragment(self, plan: loopgen.Plan, instruction: Instruction) -> Fragment:
        """Инструкция тела цикла в быстрой версии: обычный шаблон с прямыми обращениями и
        сдвигом IX/IY после записи регистра-указателя. Поднятый регистр: шаг константой —
        только IX/IY (и BC при счёте проходов), перед чтением значения V_R восстанавливается,
        после записи — загружается снова. CX в BC: LOOP — `dec bc`, `mov cx,imm` — `ld bc`;
        шаблон, трогающий B/C или вызывающий подпрограммы, окружён `ld (V_CX),bc` и
        `ld bc,(V_CX)`. Прямой CALL уходит из быстрой версии: регистры восстанавливаются до
        шаблона."""
        fragment = Fragment(instruction)
        lines = fragment.lines
        operands = instruction.operands
        mnemonic = instruction.mnemonic
        for register in plan.lifted | set(plan.values):
            if loopgen.self_step(self, instruction, register):
                if register in plan.values:
                    lines += loopgen.step_lines(plan.values[register], loops.constant_delta(instruction, register))
                else:
                    lines += loopgen.pointer_update_lines(plan, instruction)
                if plan.limit_counter and register == plan.bound[1]:
                    lines.append('dec bc')
                return fragment
        if plan.limit_counter and instruction.address == plan.loop.header:
            # cmp R,imm: CF Z80 = (BC ≠ 0) — слитый jae (jp nc) выходит, когда проходов нет.
            lines += ['ld a,b', 'or c', 'add a,#FF']
            return fragment
        if plan.bc_counter and mnemonic == 'loop':
            lines += ['dec bc', 'ld a,b', 'or c']
            self.jump(fragment, instruction.target, 'nz')
            return fragment
        if (plan.bc_counter and mnemonic == 'mov' and isinstance(operands[0], Reg) and operands[0].width == 2 and
                operands[0].index == 1 and isinstance(operands[1], Imm)):
            lines.append(f'ld bc,{hex16(operands[1].value)}')
            return fragment
        values = loopgen.value_reads(plan, instruction)
        pre: list[str] = []
        if mnemonic == 'call':
            pre += loopgen.materialize_lines(plan)
            fragment.materialized = True
        else:
            for register in sorted(plan.lifted & values):
                pre += loopgen.materialize_pointer(plan, register)
            for register in sorted(set(plan.values) & values):
                pre.append(f'ld ({REG16[register]}),{plan.values[register]}')
        handler = getattr(self, 'op_' + mnemonic)
        self.loop_plan = plan
        self.w2 = None
        try:
            handler(instruction, fragment)
        finally:
            self.loop_plan = None
            self.w2 = None
            self.previous = None
        template = switch_stack(fragment.lines)
        written = loops.writes(instruction)
        post = loopgen.pointer_update_lines(plan, instruction)
        for register in sorted(set(plan.values) & written):
            post.append(f'ld {plan.values[register]},({REG16[register]})')
        if plan.bc_counter and mnemonic != 'call':
            touches = bc_touched(template)
            if 1 in values or touches:
                pre.append('ld (V_CX),bc')
            if 1 in written or touches:
                post.append('ld bc,(V_CX)')
            fragment.bc_saved = touches
        fragment.lines[:] = pre + template + post
        return fragment

    @staticmethod
    def fusion_kind(instruction: Instruction) -> str | None:
        mnemonic = instruction.mnemonic
        width = instruction.operands[0].width if instruction.operands and hasattr(instruction.operands[0], 'width') \
            else 0
        if mnemonic in ('add', 'adc', 'sub', 'sbb', 'cmp', 'neg') and width in (1, 2):
            return 'arith'
        if mnemonic in ('and', 'or', 'xor', 'test') and width in (1, 2):
            return 'logic8' if width == 1 else 'logic16'
        if mnemonic in ('inc', 'dec') and width in (1, 2):
            return 'inc8' if width == 1 else 'inc16'
        return None

    def live_in(self, address: int) -> int:
        instruction = self.program.instructions.get(address)
        if instruction is None:
            return 63
        reads, writes = effect(instruction, set(self.idle_points))
        return reads | (self.live_out.get(address, 63) & ~writes)

    def flag_live(self, instruction: Instruction) -> int:
        """Живые флаги после инструкции, а при слиянии — на выходах цепочки переходов
        (цели всех переходов и продолжение за последним)."""
        chain = self.fusion.get(instruction.address)
        if not chain:
            return self.live_out.get(instruction.address, 63)
        live = self.live_out.get(chain[-1].address, 63)
        for jump in chain[:-1]:
            live |= self.live_in(jump.target)
        return live

    def flags_needed(self, instruction: Instruction) -> bool:
        """Флаги надо записать в V_FL: хотя бы один записываемый жив."""
        return materialize(instruction, self.flag_live(instruction), set(self.idle_points))

    # Замер 2026-09-19 (scratchpad flag_cost.py, flag_why.py): короткая запись V_FL прямо из регистра F
    # (у Z80 CF и ZF стоят в тех же битах, что в младшем байте FLAGS x86) выигрыша не дала — самые горячие
    # сравнения и так идут по короткому пути, потому что у них слиты два перехода и после цепочки флаги
    # мертвы. Из 42 мест с FLG_AR16 короткая форма подошла 18 холодным, кадр не изменился (−52 такта).
    # Остальные места держат живыми все шесть флагов, там подпрограмма нужна.

    def test16(self, instruction: Instruction) -> list[str]:
        """Проверка HL = результат для слитого перехода после 16-битной логики или inc/dec."""
        chain = self.fusion.get(instruction.address)
        if not chain:
            return []
        fused = chain[0]
        return TEST16[FUSED[self.fused_jumps[fused.address]][fused.condition]][0]

    def jump(self, fragment: Fragment, target: int | None, condition: str | None = None) -> None:
        """Переход на адрес V30; условие — код условия Z80 для перехода."""
        fragment.jumps.append((f'J{len(fragment.jumps)}', target, condition))
        fragment.lines.append(f'@JUMP {len(fragment.jumps) - 1}')

    # --- пересылки ---------------------------------------------------------------------------
    def op_mov(self, instruction: Instruction, fragment: Fragment) -> None:
        dst, src = instruction.operands
        lines = fragment.lines
        if isinstance(dst, SReg):
            lines += self.load16_de(fragment, instruction, src) + ['ex de,hl'] + self.segset_lines(dst.index)
        elif isinstance(dst, Reg) and dst.width == 2:
            if isinstance(src, Imm):
                lines += [f'ld hl,{hex16(src.value)}', f'ld ({REG16[dst.index]}),hl']
            elif isinstance(src, (Reg, SReg)):
                name = REG16[src.index] if isinstance(src, Reg) else SREG[src.index]
                lines += [f'ld hl,({name})', f'ld ({REG16[dst.index]}),hl']
            else:
                lines += self.read16(fragment, instruction, src) + [f'ld ({REG16[dst.index]}),de']
        elif isinstance(dst, Reg):
            lines += self.load8_a(fragment, instruction, src) + [f'ld ({REG8[dst.index]}),a']
        elif isinstance(dst, Mem) and dst.width == 2:
            if isinstance(src, (Imm, Reg, SReg)):
                lines += self.load16_de(fragment, instruction, src)
            else:
                raise CodegenError(instruction.text)
            lines += self.write16(fragment, instruction, dst)
        elif isinstance(dst, Mem):
            kind = self.classify(instruction, dst, 1, True)
            if kind[0] == 'abs':
                lines += self.map_page(fragment, kind[1]) + self.load8_a(fragment, instruction, src)
                lines.append(f'ld ({hex16(kind[2])}),a')
            else:
                lines += self.load8_e(src) + self.write8(fragment, instruction, dst)
        else:
            raise CodegenError(instruction.text)

    def op_xchg(self, instruction: Instruction, fragment: Fragment) -> None:
        first, second = instruction.operands
        lines = fragment.lines
        if isinstance(first, Mem) and isinstance(second, Reg) and first.width == 2:
            name = REG16[second.index]
            lines += [f'ld de,({name})'] + self.rmw16(fragment, instruction, first, [f'ld ({name}),hl', 'ex de,hl'])
        elif isinstance(first, Reg) and isinstance(second, Reg) and first.width == 1 == second.width:
            lines += [f'ld a,({REG8[first.index]})', 'ld c,a', f'ld a,({REG8[second.index]})',
                      f'ld ({REG8[first.index]}),a', 'ld a,c', f'ld ({REG8[second.index]}),a']
        elif isinstance(first, Reg) and isinstance(second, Reg) and first.width == 2 == second.width:
            lines += [f'ld hl,({REG16[first.index]})', f'ld de,({REG16[second.index]})',
                      f'ld ({REG16[first.index]}),de', f'ld ({REG16[second.index]}),hl']
        else:
            raise CodegenError(instruction.text)

    def op_push(self, instruction: Instruction, fragment: Fragment) -> None:
        operand = instruction.operands[0]
        if isinstance(operand, (Reg, SReg, Imm)) and self.stack_direct(instruction):
            # Регистр и константа — через HL (ld hl,(nn) короче и быстрее ld de,(nn)).
            if isinstance(operand, Imm):
                source = f'ld hl,{hex16(operand.value)}'
            else:
                source = f'ld hl,({REG16[operand.index] if isinstance(operand, Reg) else SREG[operand.index]})'
            fragment.lines += [source, 'push hl ; v30']
            return
        fragment.lines += (self.load16_de(fragment, instruction, operand) +
                           self.push_de(fragment, instruction))

    def op_pop(self, instruction: Instruction, fragment: Fragment) -> None:
        operand = instruction.operands[0]
        lines = fragment.lines
        if isinstance(operand, (Reg, SReg)) and self.stack_direct(instruction):
            lines.append('pop hl ; v30')
            if isinstance(operand, Reg):
                lines.append(f'ld ({REG16[operand.index]}),hl')
            else:
                lines += self.segset_lines(operand.index)
            return
        lines += self.pop_de(fragment, instruction)
        if isinstance(operand, Reg):
            lines.append(f'ld ({REG16[operand.index]}),de')
        elif isinstance(operand, SReg):
            lines += ['ex de,hl'] + self.segset_lines(operand.index)
        elif isinstance(operand, Mem):
            lines += self.write16(fragment, instruction, operand)
        else:
            raise CodegenError(instruction.text)

    def op_pusha(self, instruction: Instruction, fragment: Fragment) -> None:
        if not self.stack_direct(instruction):
            fragment.lines += [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']
            return
        # SP до PUSHA кладётся пятым, как у x86.
        lines = fragment.lines
        lines += ['ld hl,#C000', 'add hl,sp', 'ld (TEMP_EA),hl']
        for name in ('V_AX', 'V_CX', 'V_DX', 'V_BX', 'TEMP_EA', 'V_BP', 'V_SI', 'V_DI'):
            lines += [f'ld de,({name})', 'push de ; v30']

    def op_popa(self, instruction: Instruction, fragment: Fragment) -> None:
        if not self.stack_direct(instruction):
            fragment.lines += [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']
            return
        lines = fragment.lines
        for name in ('V_DI', 'V_SI', 'V_BP', None, 'V_BX', 'V_DX', 'V_CX', 'V_AX'):
            lines.append('pop de ; v30')
            if name:
                lines.append(f'ld ({name}),de')

    def op_cbw(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines += ['ld a,(V_AX)', 'rla', 'sbc a,a', 'ld (V_AX+1),a']

    def op_cwd(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines += ['ld a,(V_AX+1)', 'rla', 'sbc a,a', 'ld (V_DX),a', 'ld (V_DX+1),a']

    def op_nop(self, instruction: Instruction, fragment: Fragment) -> None:
        pass

    # --- арифметика и логика ---------------------------------------------------------------------
    OP8 = {'add': 'add a,e', 'adc': 'adc a,e', 'sub': 'sub e', 'sbb': 'sbc a,e', 'cmp': 'sub e',
           'and': 'and e', 'test': 'and e', 'or': 'or e', 'xor': 'xor e'}

    def binary(self, instruction: Instruction, fragment: Fragment, operation: str) -> None:
        dst, src = instruction.operands
        lines = fragment.lines
        flags = self.flags_needed(instruction)
        keep = instruction.address in self.fusion
        store = operation not in ('cmp', 'test')
        logic = operation in ('and', 'or', 'xor', 'test')
        if instruction.width == 1:
            carry = ['ld c,a', 'ld a,(V_FL)', 'rra', 'ld a,c'] if operation in ('adc', 'sbb') else []
            op8 = [self.OP8[operation]]
            if isinstance(src, Imm):
                op8 = [OP8_IMM[operation].format(hex8(src.value))]
            routine = flag_routine('FLG_LOG8' if logic else 'FLG_AR8', keep) if flags else []
            if (isinstance(dst, Reg) and dst == src and operation in ('xor', 'sub') and not flags
                    and not keep):
                lines += ['xor a', f'ld ({REG8[dst.index]}),a']
            elif isinstance(dst, Reg):
                if isinstance(src, Imm):
                    lines += [f'ld a,({REG8[dst.index]})'] + carry + op8
                else:
                    lines += (self.load8_a(fragment, instruction, src) + ['ld e,a', f'ld a,({REG8[dst.index]})'] +
                              carry + op8)
                if store:
                    lines.append(f'ld ({REG8[dst.index]}),a')
                lines += routine
            elif isinstance(dst, Mem):
                if not isinstance(src, Imm):
                    lines += self.load8_e(src)
                if store:
                    lines += self.rmw8(fragment, instruction, dst, lambda fast: carry + op8, flags or keep)
                else:
                    lines += self.read8(fragment, instruction, dst) + op8
                lines += routine
            else:
                raise CodegenError(instruction.text)
            return
        # 16 бит
        if not flags:
            quick = self.quick_zero_test16(instruction, fragment, operation, dst, src)
            if quick is not None:
                lines += quick
                return
        if isinstance(dst, Reg) and not flags and not keep and store:
            quick = self.quick16(instruction, fragment, operation, dst, src)
            if quick is not None:
                lines += quick
                return
        # TEST с маской #FFFF результата не меняет: проверяется само значение.
        identity = operation == 'test' and isinstance(src, Imm) and src.value & 0xFFFF == 0xFFFF
        if logic:
            op16 = {'and': 'and', 'test': 'and', 'or': 'or', 'xor': 'xor'}[operation]
            body = [] if identity else ['ld a,h', f'{op16} d', 'ld h,a', 'ld a,l', f'{op16} e', 'ld l,a']
        else:
            prefix = ['ld a,(V_FL)', 'rra'] if operation in ('adc', 'sbb') else ['or a']
            body = prefix + ['adc hl,de' if operation in ('add', 'adc') else 'sbc hl,de']
        pre_flags = ['ld a,l', 'xor e', 'ld (FLG_X),a'] if flags and not logic else []
        post_result = ['ld (FLG_R),hl'] if flags else []
        if logic:
            # Проверка для слитого перехода — после подпрограммы флагов (она портит F и HL).
            test = self.test16(instruction)
            routine = (['call FLG_LOG16'] + (['ld hl,(FLG_R)'] + test if test else [])) if flags else []
            inline_test = [] if flags else test
            keep_write = bool(inline_test)
        else:
            routine = flag_routine('FLG_AR16', keep) if flags else []
            inline_test = []
            keep_write = flags or keep
        if isinstance(dst, Reg):
            lines += ([] if identity else self.load16_de(fragment, instruction, src)) + [f'ld hl,({REG16[dst.index]})']
            lines += pre_flags + body
            lines += post_result
            if store:
                lines.append(f'ld ({REG16[dst.index]}),hl')
            lines += inline_test + routine
        elif isinstance(dst, Mem):
            if store:
                lines += self.load16_de(fragment, instruction, src)
                lines += self.rmw16(fragment, instruction, dst, pre_flags + body + post_result + inline_test,
                                    keep_write)
            else:
                lines += self.read16(fragment, instruction, dst) + ['ex de,hl']
                if not identity:
                    lines += self.load16_de(fragment, instruction, src)
                lines += pre_flags + body + post_result + inline_test
            lines += routine
        else:
            raise CodegenError(instruction.text)

    def quick_zero_test16(self, instruction: Instruction, fragment: Fragment, operation: str, dst, src) -> list[str] | None:
        """CMP/TEST слова, когда жив только ZF для слитых JE/JNE, а флаги после них мертвы.

        CMP 0/FFFF — OR/AND байтов; TEST с маской в одном байте — AND этого байта.
        Чтение памяти остаётся полным словом через прежний адаптер, в том числе на границе страницы.
        Регистры V30 и память не меняются. Знаковые переходы и живые флаги используют общий шаблон.
        """
        chain = self.fusion.get(instruction.address)
        if not chain or any(jump.condition not in ('e', 'ne') for jump in chain) or not isinstance(src, Imm):
            return None
        value = src.value & 0xFFFF
        if operation == 'cmp':
            if value not in (0, 0xFFFF):
                return None
        elif operation == 'test':
            if value & 255 and value >> 8:
                return None
        else:
            return None
        if isinstance(dst, Reg):
            name = REG16[dst.index]
            if operation == 'test':
                offset, mask = (1, value >> 8) if value >> 8 else (0, value)
                if mask == 0:
                    return ['xor a']
                target = f'{name}+1' if offset else name
                return [f'ld a,({target})', f'and {hex8(mask)}']
            load, high, low = [f'ld hl,({name})'], 'h', 'l'
        elif isinstance(dst, Mem):
            load, high, low = self.read16(fragment, instruction, dst), 'd', 'e'
        else:
            return None
        if operation == 'test':
            byte, mask = (high, value >> 8) if value >> 8 else (low, value)
            return load + [f'ld a,{byte}', f'and {hex8(mask)}']
        return load + ([f'ld a,{high}', f'or {low}'] if value == 0 else
                       [f'ld a,{high}', f'and {low}', 'inc a'])

    def quick16(self, instruction: Instruction, fragment: Fragment, operation: str, dst: Reg, src) -> list[str] | None:
        """16-битная операция над регистром без живых флагов."""
        name = REG16[dst.index]
        if operation in ('xor', 'sub') and src == dst:
            return ['ld hl,#0000', f'ld ({name}),hl']
        if operation in ('add', 'sub') and isinstance(src, Imm):
            value = src.value if operation == 'add' else -src.value
            value &= 0xFFFF
            if value in (1, 2, 3):
                body = ['inc hl'] * value
            elif value in (0xFFFF, 0xFFFE, 0xFFFD):
                body = ['dec hl'] * (0x10000 - value)
            else:
                body = [f'ld de,{hex16(value)}', 'add hl,de']
            return [f'ld hl,({name})'] + body + [f'ld ({name}),hl']
        if operation == 'add':
            return self.load16_de(fragment, instruction, src) + [f'ld hl,({name})', 'add hl,de', f'ld ({name}),hl']
        if operation in ('and', 'or', 'xor') and isinstance(src, Imm):
            lines = []
            for offset, byte in ((0, src.value & 0xFF), (1, src.value >> 8)):
                target = f'{name}+{offset}' if offset else name
                if (operation == 'and' and byte == 0xFF) or (operation != 'and' and byte == 0):
                    continue
                if operation == 'and' and byte == 0:
                    lines += ['xor a', f'ld ({target}),a']
                elif operation == 'or' and byte == 0xFF:
                    lines += ['ld a,#FF', f'ld ({target}),a']
                else:
                    lines += [f'ld a,({target})', f'{operation} {hex8(byte)}', f'ld ({target}),a']
            return lines
        return None

    def op_add(self, i, f):
        self.binary(i, f, 'add')

    def op_adc(self, i, f):
        self.binary(i, f, 'adc')

    def op_sub(self, i, f):
        self.binary(i, f, 'sub')

    def op_sbb(self, i, f):
        self.binary(i, f, 'sbb')

    def op_cmp(self, i, f):
        self.binary(i, f, 'cmp')

    def op_and(self, i, f):
        self.binary(i, f, 'and')

    def op_or(self, i, f):
        self.binary(i, f, 'or')

    def op_xor(self, i, f):
        self.binary(i, f, 'xor')

    def op_test(self, i, f):
        self.binary(i, f, 'test')

    def incdec(self, instruction: Instruction, fragment: Fragment, increment: bool) -> None:
        operand = instruction.operands[0]
        lines = fragment.lines
        flags = self.flags_needed(instruction)
        keep = instruction.address in self.fusion
        op = 'inc' if increment else 'dec'
        if operand.width == 2:
            test = self.test16(instruction)
            inline_test = [] if flags else test
            routine = ([f'ld e,{1 if increment else 0}', 'call FLG_INC16'] +
                       (['ld hl,(FLG_R)'] + test if test else [])) if flags else []
            if isinstance(operand, Reg):
                lines += [f'ld hl,({REG16[operand.index]})', f'{op} hl', f'ld ({REG16[operand.index]}),hl']
                if flags:
                    lines += ['ld (FLG_R),hl']
                lines += inline_test
            else:
                lines += self.rmw16(fragment, instruction, operand,
                                    [f'{op} hl'] + (['ld (FLG_R),hl'] if flags else []) + inline_test,
                                    bool(inline_test))
            lines += routine
            return
        routine = flag_routine('FLG_INC8', keep) if flags else []
        if isinstance(operand, Reg):
            lines += [f'ld a,({REG8[operand.index]})', f'{op} a', f'ld ({REG8[operand.index]}),a'] + routine
        else:
            lines += self.rmw8(fragment, instruction, operand, lambda fast: [f'{op} a'], flags or keep) + routine

    def op_inc(self, i, f):
        self.incdec(i, f, True)

    def op_dec(self, i, f):
        self.incdec(i, f, False)

    def op_neg(self, instruction: Instruction, fragment: Fragment) -> None:
        operand = instruction.operands[0]
        flags = self.flags_needed(instruction)
        keep = instruction.address in self.fusion
        lines = fragment.lines
        if operand.width == 2:
            compute = ['ex de,hl', 'ld hl,#0000'] + (['ld a,e', 'ld (FLG_X),a'] if flags else []) + ['or a', 'sbc hl,de']
            compute += ['ld (FLG_R),hl'] if flags else []
            if isinstance(operand, Reg):
                lines += [f'ld hl,({REG16[operand.index]})'] + compute + [f'ld ({REG16[operand.index]}),hl']
            else:
                lines += self.rmw16(fragment, instruction, operand, compute, flags or keep)
            lines += flag_routine('FLG_AR16', keep) if flags else []
            return
        routine = flag_routine('FLG_AR8', keep) if flags else []
        if isinstance(operand, Reg):
            lines += [f'ld a,({REG8[operand.index]})', 'neg', f'ld ({REG8[operand.index]}),a'] + routine
        else:
            lines += self.rmw8(fragment, instruction, operand, lambda fast: ['neg'], flags or keep) + routine

    def op_not(self, instruction: Instruction, fragment: Fragment) -> None:
        operand = instruction.operands[0]
        lines = fragment.lines
        if operand.width == 2:
            compute = ['ld a,h', 'cpl', 'ld h,a', 'ld a,l', 'cpl', 'ld l,a']
            if isinstance(operand, Reg):
                lines += [f'ld hl,({REG16[operand.index]})'] + compute + [f'ld ({REG16[operand.index]}),hl']
            else:
                lines += self.rmw16(fragment, instruction, operand, compute)
            return
        if isinstance(operand, Reg):
            lines += [f'ld a,({REG8[operand.index]})', 'cpl', f'ld ({REG8[operand.index]}),a']
        else:
            lines += self.rmw8(fragment, instruction, operand, lambda fast: ['cpl'])

    def shift(self, instruction: Instruction, fragment: Fragment, kind: str) -> None:
        operand = instruction.operands[0]
        count = instruction.operands[1] if len(instruction.operands) > 1 else Imm(1, 0)
        lines = fragment.lines
        if isinstance(count, Imm) and not self.flags_needed(instruction):
            value = count.value if count.width else 1
            quick = self.quick_shift(fragment, instruction, operand, kind, value)
            if quick is not None:
                lines += quick
                return
        if (kind in ('rcl', 'rcr') and isinstance(count, Imm) and operand.width == 1 and
                (count.value if count.width else 1) & 0x1F == 1 and
                not self.live_out.get(instruction.address, 63) & FLAG_O):
            lines += self.carry_shift(fragment, instruction, operand, kind)
            return
        if isinstance(count, Imm):
            load_count = [f'ld b,{hex8(count.value if count.width else 1)}']
        elif isinstance(count, Reg) and count.width == 1 and count.index == 1:
            load_count = ['ld c,a', 'ld a,(V_CX)', 'ld b,a', 'ld a,c']
        else:
            raise CodegenError(instruction.text)
        routine = f'SH_{kind.upper()}{8 * operand.width}'
        if operand.width == 2:
            if isinstance(operand, Reg):
                lines += load_count + [f'ld hl,({REG16[operand.index]})', f'call {routine}',
                                       f'ld ({REG16[operand.index]}),hl']
            else:
                raise CodegenError(instruction.text)
        else:
            if isinstance(operand, Reg):
                lines += [f'ld a,({REG8[operand.index]})'] + load_count + [f'call {routine}',
                                                                           f'ld ({REG8[operand.index]}),a']
            elif isinstance(operand, Mem):
                def compute(fast: bool) -> list[str]:
                    body = load_count + [f'call {routine}']
                    return ['push hl'] + body + ['pop hl'] if fast else body
                lines += self.rmw8(fragment, instruction, operand, compute)
            else:
                raise CodegenError(instruction.text)

    def quick_shift(self, fragment: Fragment, instruction: Instruction, operand, kind: str, value: int) -> list[str] | None:
        """Сдвиг на константу без живых флагов (у RCL/RCR — только CF на входе)."""
        masked = value & 0x1F
        if masked == 0:
            return []
        if operand.width == 2:
            limit = 16 if kind in ('shl', 'shr', 'sar') else 1
            if masked > min(limit, 8) or not isinstance(operand, Reg):
                return None
            step = {'shl': ['add hl,hl'], 'shr': ['srl h', 'rr l'], 'sar': ['sra h', 'rr l'],
                    'rcl': ['adc hl,hl'], 'rcr': ['rr h', 'rr l']}[kind]
            carry = ['ld a,(V_FL)', 'rra'] if kind in ('rcl', 'rcr') else []
            name = REG16[operand.index]
            return carry + [f'ld hl,({name})'] + step * masked + [f'ld ({name}),hl']
        if kind in ('rcl', 'rcr'):
            masked %= 9
            if masked == 0:
                return []
        if masked > 8:
            return None
        step = {'shl': 'add a,a', 'shr': 'srl a', 'sar': 'sra a', 'rcl': 'rla', 'rcr': 'rra'}[kind]
        body = [step] * masked
        if kind in ('rcl', 'rcr'):
            def with_carry(fast: bool) -> list[str]:
                return ['ld c,a', 'ld a,(V_FL)', 'rra', 'ld a,c'] + body
        else:
            def with_carry(fast: bool) -> list[str]:
                return body
        if isinstance(operand, Reg):
            name = REG8[operand.index]
            return [f'ld a,({name})'] + with_carry(False) + [f'ld ({name}),a']
        return self.rmw8(fragment, instruction, operand, with_carry)

    def carry_shift(self, fragment: Fragment, instruction: Instruction, operand, kind: str) -> list[str]:
        """RCL/RCR байта на 1 при живом CF и мёртвом OF: перенос Z80 — CF, запись CF в V_FL."""
        step = 'rla' if kind == 'rcl' else 'rra'
        n = fragment.local()
        store = ['ld hl,V_FL', 'res 0,(hl)', f'jr nc,.c{n}', 'set 0,(hl)', f'.c{n}:']
        if isinstance(operand, Reg):
            name = REG8[operand.index]
            return ['ld a,(V_FL)', 'rra', f'ld a,({name})', step, f'ld ({name}),a'] + store

        def compute(fast: bool) -> list[str]:
            return ['ld c,a', 'ld a,(V_FL)', 'rra', 'ld a,c', step]
        return self.rmw8(fragment, instruction, operand, compute, True) + store

    def op_shl(self, i, f):
        self.shift(i, f, 'shl')

    def op_shr(self, i, f):
        self.shift(i, f, 'shr')

    def op_sar(self, i, f):
        self.shift(i, f, 'sar')

    def op_rcl(self, i, f):
        self.shift(i, f, 'rcl')

    def op_rcr(self, i, f):
        self.shift(i, f, 'rcr')

    def op_daa(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines.append('call DAA_OP')

    def op_das(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines.append('call DAS_OP')

    def op_add4s(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines.append('call ADD4S')

    # --- флаги-команды -------------------------------------------------------------------------
    def op_clc(self, i, f):
        f.lines += ['ld hl,V_FL', 'res 0,(hl)']

    def op_stc(self, i, f):
        f.lines += ['ld hl,V_FL', 'set 0,(hl)']

    def op_cld(self, i, f):
        f.lines += ['ld hl,V_FL+1', 'res 2,(hl)']

    def op_std(self, i, f):
        f.lines += ['ld hl,V_FL+1', 'set 2,(hl)']

    def op_cmc(self, i, f):
        f.lines += ['ld a,(V_FL)', 'xor #01', 'ld (V_FL),a']

    def op_cli(self, i, f):
        f.lines += ['ld hl,V_FL+1', 'res 1,(hl)']

    def op_sti(self, i, f):
        f.lines += ['ld hl,V_FL+1', 'set 1,(hl)']

    # --- строки -----------------------------------------------------------------------------------
    def string(self, instruction: Instruction, fragment: Fragment, name: str) -> None:
        source = [operand for operand in instruction.operands if isinstance(operand, Mem)]
        segment = 'DS'
        for operand in source:
            if operand.bases == (6,):
                segment = SEG[operand.segment]
        if not instruction.rep and name in ('movsw', 'movsb', 'stosw', 'stosb', 'lodsw') and segment == 'DS':
            self.inline_string(instruction, fragment, name)
            return
        rep = '_REP' if instruction.rep else ''
        if name == 'movsw' and instruction.rep and segment == 'DS':
            pages = [self.segment_value(instruction, index) for index in (3, 0)]
            if all(value is not None and not (value << 4) & 0x3FFF for value in pages):
                source_page, target_page = ((value << 4) >> 14 for value in pages)
                fragment.lines += [f'ld a,{hex8(source_page)}', 'ld (MV_SRC),a', f'ld a,{hex8(target_page)}',
                                   'ld (MV_DST),a', 'call REP_MOVSW_FAST']
                return
        fragment.lines.append(f'call {name.upper()}{rep}_{segment}')

    def inline_string(self, instruction: Instruction, fragment: Fragment, name: str) -> None:
        """Одиночная строковая команда без REP: обращения как у обычных операндов, шаг SI/DI
        при DF = 0; при DF = 1 — подпрограмма."""
        n = fragment.local()
        lines = fragment.lines
        width = 2 if name.endswith('w') else 1
        target = next((operand for operand in instruction.operands if isinstance(operand, Mem) and
                       operand.bases == (7,)), None)
        source = next((operand for operand in instruction.operands if isinstance(operand, Mem) and
                       operand.bases == (6,)), None)
        # Путь подпрограммы уходит на .e (там W2 неизвестна): пометка keep лишь для проверки
        # пометок идущего следом прямого пути.
        lines += ['ld a,(V_FL+1)', 'and 4', f'jr z,.i{n}', f'call {name.upper()}_DS ; w2 keep', f'jp .e{n}', f'.i{n}:']
        if name == 'movsw':
            lines += self.read16(fragment, instruction, source) + self.write16(fragment, instruction, target)
        elif name == 'movsb':
            lines += self.read8(fragment, instruction, source) + ['ld e,a'] + self.write8(fragment, instruction, target)
        elif name == 'stosw':
            lines += ['ld de,(V_AX)'] + self.write16(fragment, instruction, target)
        elif name == 'stosb':
            lines += ['ld a,(V_AX)', 'ld e,a'] + self.write8(fragment, instruction, target)
        else:
            lines += self.read16(fragment, instruction, source) + ['ld (V_AX),de']
        step = ['inc hl'] * width
        if source is not None:
            lines += ['ld hl,(V_SI)'] + step + ['ld (V_SI),hl']
        if target is not None:
            lines += ['ld hl,(V_DI)'] + step + ['ld (V_DI),hl']
        lines += [f'.e{n}:', '; w2 lost']
        self.w2 = None

    def op_movsb(self, i, f):
        self.string(i, f, 'movsb')

    def op_movsw(self, i, f):
        self.string(i, f, 'movsw')

    def op_stosb(self, i, f):
        self.string(i, f, 'stosb')

    def op_stosw(self, i, f):
        self.string(i, f, 'stosw')

    def op_lodsw(self, i, f):
        self.string(i, f, 'lodsw')

    # --- порты ------------------------------------------------------------------------------------
    def op_in(self, instruction: Instruction, fragment: Fragment) -> None:
        dst, port = instruction.operands
        lines = fragment.lines
        if isinstance(port, Imm) and port.value <= 5:
            # Порты 0..5 — слова IN0, IN1, DSW; байт порта base — младший, base+1 — старший.
            base = f'IN0+{(port.value >> 1) * 2}'
            if dst.width == 2:
                lines += [f'ld hl,({base})', 'ld (V_AX),hl']
            else:
                lines += [f'ld a,({base}+{port.value & 1})', 'ld (V_AX),a']
            return
        lines.append(f'ld hl,{hex16(port.value)}' if isinstance(port, Imm) else 'ld hl,(V_DX)')
        lines += [f'ld a,{dst.width}', 'call PORT_IN']
        lines.append('ld (V_AX),hl' if dst.width == 2 else 'ld a,l')
        if dst.width == 1:
            lines.append('ld (V_AX),a')

    def op_out(self, instruction: Instruction, fragment: Fragment) -> None:
        port, src = instruction.operands
        lines = fragment.lines
        if isinstance(port, Imm):
            # Постоянный порт (VDAC2+ 2026-09-26, скорость: 9 выводов в порты на шаг, по ≈330 тактов через PORT_OUT со
            # сменой стека): частые порты — без PORT_OUT, с той же записью в состояние платы, что у него
            # (v30z80_runtime.asm, PORT_OUT). У байтового OUT старший байт значения — 0, как там (`ld d,0`).
            value = port.value & 0xFFFF
            if 0x80 <= value <= 0x86 and not value & 1:
                # Прокрутка: слово SCROLL_Y0 + (порт − #80) — Y0, X0, Y1, X1.
                slot = 'SCROLL_Y0' if value == 0x80 else f'SCROLL_Y0+{value - 0x80}'
                if src.width == 2:
                    lines += ['ld hl,(V_AX)', f'ld ({slot}),hl']
                else:
                    lines += ['ld a,(V_AX)', 'ld l,a', 'ld h,0', f'ld ({slot}),hl']
                return
            if value == 2:
                # Видео: бит 2 — VID_FLIP, бит 3 — VID_OFF.
                lines += ['ld a,(V_AX)', 'ld l,a', 'and 4', 'ld (VID_FLIP),a', 'ld a,l', 'and 8', 'ld (VID_OFF),a']
                return
            if value in (6, 7):
                # Растр: RASTER_RAW — 9 бит значения.
                if src.width == 2:
                    lines += ['ld hl,(V_AX)', 'ld a,h', 'and 1', 'ld h,a', 'ld (RASTER_RAW),hl']
                else:
                    lines += ['ld a,(V_AX)', 'ld l,a', 'ld h,0', 'ld (RASTER_RAW),hl']
                return
            if value == 4:
                # Спрайты: DMA памяти спрайтов в буфер (значение не читается).
                lines.append('call SPRITE_DMA')
                return
        lines.append('ld de,(V_AX)')
        lines.append(f'ld hl,{hex16(port.value)}' if isinstance(port, Imm) else 'ld hl,(V_DX)')
        lines += [f'ld a,{src.width}', 'call PORT_OUT']

    # --- переходы --------------------------------------------------------------------------------
    def op_jmp(self, instruction: Instruction, fragment: Fragment) -> None:
        if instruction.target is not None:
            self.jump(fragment, instruction.target)
            return
        fragment.lines += self.load16_de(fragment, instruction, instruction.operands[0]) + ['jp DISPATCH']

    def op_call(self, instruction: Instruction, fragment: Fragment) -> None:
        lines = fragment.lines
        next_ip = (instruction.next - CODE_BASE) & 0xFFFF
        if instruction.target is not None:
            lines += [f'ld de,{hex16(next_ip)}'] + self.push_de(fragment, instruction)
            self.jump(fragment, instruction.target)
            return
        if self.stack_direct(instruction):
            # Цель читается до записи адреса возврата (как у V30); адрес возврата — через HL.
            lines += self.load16_de(fragment, instruction, instruction.operands[0])
            lines += [f'ld hl,{hex16(next_ip)}', 'push hl ; v30', 'jp DISPATCH']
            return
        lines += self.load16_de(fragment, instruction, instruction.operands[0]) + ['ld (TARGET_IP),de',
                                                                                   f'ld de,{hex16(next_ip)}']
        lines += self.push_de(fragment, instruction) + ['ld de,(TARGET_IP)', 'jp DISPATCH']

    # Предсказание возврата: не больше RETURN_CANDIDATES мест, покрывающих по трассе не меньше RETURN_COVERAGE вызовов;
    # только у RET, исполненных по трассе не меньше RETURN_MIN_COUNT раз (≈100 RET из 268 исполнявшихся покрывают 98 %
    # возвратов трассы — код остальных не растёт).
    RETURN_CANDIDATES = 3
    RETURN_COVERAGE = 0.8
    RETURN_MIN_COUNT = 1000

    def return_candidates(self, instruction: Instruction) -> list[int]:
        """Места возврата RET по статическим местам вызова функций, которым принадлежит RET (functions.owners и
        callers): инструкции за CALL, исполнявшиеся по трассе, по убыванию числа вызовов. Пусто — если нет карты
        функций, мест нет или несколько самых частых мест не покрывают RETURN_COVERAGE вызовов (сверка с каждым
        местом стоит тактов и на промахе)."""
        functions_map = self.function_map
        if functions_map is None or self.instruction_counts.get(instruction.address, 0) < self.RETURN_MIN_COUNT:
            return []
        weights: dict[int, int] = {}
        for entry in functions_map.owners.get(instruction.address, ()):
            for site in functions_map.callers.get(entry, ()):
                call = self.program.instructions.get(site)
                if call is None or call.mnemonic != 'call':
                    continue
                continuation = call.next
                if continuation not in self.program.instructions or continuation in self.program.constant_only:
                    continue
                weights[continuation] = weights.get(continuation, 0) + self.instruction_counts.get(site, 0)
        total = sum(weights.values())
        if not total:
            return []
        ranked = sorted((item for item in weights.items() if item[1]), key=lambda item: (-item[1], item[0]))
        covered = 0
        for count_taken, (_address, count) in enumerate(ranked[:self.RETURN_CANDIDATES], start=1):
            covered += count
            if covered >= self.RETURN_COVERAGE * total:
                return [address for address, _count in ranked[:count_taken]]
        return []

    def op_ret(self, instruction: Instruction, fragment: Fragment) -> None:
        """RET: адрес возврата со стека V30 (DE). Совпал с одним из предсказанных мест возврата — переход прямо на метку
        продолжения (та же метка, что у диспетчеризации: места за CALL не бывают входами только из констант); иначе —
        DISPATCH."""
        lines = fragment.lines
        lines += self.pop_de(fragment, instruction)
        if instruction.operands:
            lines += [f'ld hl,{hex16(instruction.operands[0].value)}', 'add hl,sp', 'ld sp,hl']
        for index, continuation in enumerate(self.return_candidates(instruction)):
            ip = (continuation - CODE_BASE) & 0xFFFF
            lines += ['ld a,e', f'cp {hex8(ip)}', f'jr nz,.r{index}', 'ld a,d', f'cp {hex8(ip >> 8)}']
            self.jump(fragment, continuation, 'z')
            lines.append(f'.r{index}:')
        lines.append('jp DISPATCH')

    def op_iret(self, instruction: Instruction, fragment: Fragment) -> None:
        if not self.stack_direct(instruction):
            fragment.lines += [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']
            return
        # FLAGS со стека — как SET_FLAGS резидента, без вызова и смены стека (VDAC2+ 2026-09-26): младший байт & #D5 | 2,
        # старший & #7F.
        fragment.lines += (['pop de ; v30', 'ld (TARGET_IP),de', 'pop hl ; v30'] + self.segset_lines(1) +
                           ['pop de ; v30', 'ld a,e', 'and #D5', 'or #02', 'ld (V_FL),a', 'ld a,d', 'and #7F',
                            'ld (V_FL+1),a', 'ld de,(TARGET_IP)', 'jp DISPATCH'])

    def op_far(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines += [f'ld de,{hex16(instruction.ip)}', 'jp FAULT']

    def op_jcc(self, instruction: Instruction, fragment: Fragment) -> None:
        condition = instruction.condition
        lines = fragment.lines
        kind = self.fused_jumps.get(instruction.address)
        if kind is not None:
            steps = FUSED[kind][condition]
            if kind in ('logic16', 'inc16'):
                steps = TEST16[steps][1]
            for step in steps:
                if step[0] == 'j':
                    self.jump(fragment, instruction.target, step[1])
                elif step[0] == 'skip':
                    _, cond, name = step
                    if cond is None:
                        lines.append(f'jr .f{name}')
                    elif cond in ('z', 'nz', 'c', 'nc'):
                        lines.append(f'jr {cond},.f{name}')
                    else:
                        lines.append(f'jp {cond},.f{name}')
                else:
                    lines.append(f'.f{step[1]}:')
            return
        if condition in CONDITION:
            test, taken, _not_taken = CONDITION[condition]
            lines += ['ld a,(V_FL)', test]
            self.jump(fragment, instruction.target, taken)
        elif condition in ('o', 'no'):
            lines += ['ld a,(V_FL+1)', 'and #08']
            self.jump(fragment, instruction.target, 'nz' if condition == 'o' else 'z')
        elif condition in ('l', 'ge'):
            lines += ['call COND_SF_XOR_OF']
            self.jump(fragment, instruction.target, 'nz' if condition == 'l' else 'z')
        elif condition in ('le', 'g'):
            lines += ['call COND_LE']
            self.jump(fragment, instruction.target, 'nz' if condition == 'le' else 'z')
        else:
            raise CodegenError(instruction.text)

    def op_loop(self, instruction: Instruction, fragment: Fragment) -> None:
        fragment.lines += ['ld hl,(V_CX)', 'dec hl', 'ld (V_CX),hl', 'ld a,h', 'or l']
        self.jump(fragment, instruction.target, 'nz')


OP8_IMM = {'add': 'add a,{}', 'adc': 'adc a,{}', 'sub': 'sub {}', 'sbb': 'sbc a,{}', 'cmp': 'sub {}',
           'and': 'and {}', 'test': 'and {}', 'or': 'or {}', 'xor': 'xor {}'}
# Отображение страницы V30 из A в окно W2 без вызова: портит BC и A, флаги не меняет
# (V30_PAGE_BASE = #80, страницы V30 < #40: `set 7,a` вместо сложения).
MAP_W2_LINES = ['ld (W2_PAGE),a', 'set 7,a', 'ld bc,PORT_PAGE2', 'out (c),a']
# Подпрограммы, не меняющие окно W2.
W2_SAFE_CALLS = {'FLG_AR8', 'FLG_LOG8', 'FLG_INC8', 'FLG_AR16', 'FLG_LOG16', 'FLG_INC16', 'COND_SF_XOR_OF',
                 'COND_LE', 'SET_FLAGS', 'DAA_OP', 'DAS_OP', 'PORT_IN', 'VIDEO_W2_MARK1', 'VIDEO_W2_MARK2',
                 'VIDEO_W2_MARK2BC', 'VIDEO_MARK_DE'} | {
    f'SH_{kind}{width}' for kind in ('SHL', 'SHR', 'SAR', 'RCL', 'RCR') for width in (8, 16)}


def verify_w2(lines: list[str], state: int | None, instruction: Instruction) -> int | None:
    """Состояние W2 в конце фрагмента по пометкам `; w2 …` и вызовам; опора на известную W2
    (`; w2 need`) обязана совпадать с состоянием, иначе — ошибка генератора."""
    for line in lines:
        text = line.strip()
        if text.startswith('; w2 need '):
            if state != int(text.split('#')[1], 16):
                raise CodegenError(f'{instruction.address:05X}: W2 не известна для {text}')
        elif text.startswith('; w2 set '):
            state = int(text.split('#')[1], 16)
        elif text.startswith('; w2 lost'):
            state = None
        elif text.startswith('call '):
            name = text[5:].split(';')[0].split(',')[-1].strip()
            if name not in W2_SAFE_CALLS and '; w2 keep' not in text:
                state = None
        elif text.startswith(('jp DISPATCH', 'jp FARJP', 'jp IDLE_EXIT', 'jp FAULT')):
            state = None
    return state
BREAK_PREFIXES = ('jr ', 'jp ', 'djnz ', '@JUMP', 'ret')


def flag_routine(name: str, keep: bool) -> list[str]:
    """F → B/C для подпрограммы флагов; keep — F восстанавливается для слитого перехода."""
    return ['push af'] + (['push af'] if keep else []) + ['pop bc', f'call {name}'] + (['pop af'] if keep else [])


def uses_helper_stack(line: str) -> bool:
    text = line.strip()
    return not text.endswith('; v30') and text.startswith(('call ', 'push ', 'pop ', 'ex (sp)', 'rst '))


def switch_stack(lines: list[str]) -> list[str]:
    """Участки фрагмента без меток и переходов, где нужен стек Z80 (call/push/pop не V30),
    исполняются на стеке помощников: SP V30 сохраняется в V30_SP_SAVE."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        marks = [index for index, line in enumerate(run) if uses_helper_stack(line)]
        if marks:
            first, last = marks[0], marks[-1]
            balance = 0
            for line in run[first:last + 1]:
                text = line.strip()
                balance += 1 if text.startswith('push ') else -1 if text.startswith('pop ') else 0
            if balance:
                raise CodegenError(f'несбалансированный стек помощников: {run}')
            out.extend(run[:first] + ['ld (V30_SP_SAVE),sp', 'ld sp,HELPER_TOP'] + run[first:last + 1] +
                       ['ld sp,(V30_SP_SAVE)'] + run[last + 1:])
        else:
            out.extend(run)
        run.clear()

    for line in lines:
        text = line.strip()
        if text.endswith(':') or text.startswith(BREAK_PREFIXES) or text.endswith('; v30'):
            flush()
            out.append(line)
        else:
            run.append(line)
    flush()
    return out


def indent(lines: list[str]) -> list[str]:
    return [line if line.endswith(':') else '\t' + line for line in lines]


def render_jump(target: int | None, condition: str | None, page_of: dict[int, int], page: int,
                instruction: Instruction, index: int, name=None) -> list[str]:
    """Переход на адрес V30; name(адрес) — метка (по умолчанию A_<адрес>)."""
    if name is None:
        name = label

    def skip() -> str:
        inverse = Z80_INVERSE[condition]
        return f'jr {inverse},.n{index}' if condition in ('z', 'nz', 'c', 'nc') else f'jp {inverse},.n{index}'
    if target is None or target not in page_of:
        body = [f'ld de,{hex16((target or 0) - CODE_BASE)}', 'jp DISPATCH']
        if condition is None:
            return body
        return [skip()] + body + [f'.n{index}:']
    if page_of[target] == page:
        return [f'jp {condition},{name(target)}' if condition else f'jp {name(target)}']
    body = [f'ld a,$${name(target)}', f'ld hl,{name(target)}', 'jp FARJP']
    if condition is None:
        return body
    return [skip()] + body + [f'.n{index}:']


FAR_JUMP_SIZE = 10


def bc_touched(lines: list[str]) -> bool:
    """Строки трогают B/C или вызывают подпрограммы (они портят BC)."""
    for line in lines:
        text = line.split(';')[0].strip()
        if not text or text.endswith(':') or text.startswith('@JUMP') or text == 'ex de,hl':
            continue
        if text.startswith(('call ', 'rst ', 'exx', 'ld sp,', 'ld (V30_SP_SAVE)')):
            return True
        uses = peephole.register_uses(text)
        if uses is None:
            if text.startswith(('jp ', 'jr ', 'djnz')):
                continue
            return True
        reads, writes_, _removable = uses
        if {('r', 'b'), ('r', 'c')} & (reads | writes_):
            return True
    return False


def generate(program, live_out: dict[int, int], idle_points: dict[int, tuple[int, int]],
             first_page: int, last_page: int, seg_values: dict[int, tuple] | None = None,
             memory_pages: dict[int, dict[int, int]] | None = None,
             instruction_counts: dict[int, int] | None = None, function_map=None) -> tuple[str, dict[int, int]]:
    """Текст страниц кода и страница каждой инструкции."""
    generator = Generator(program, live_out, idle_points, seg_values, memory_pages, instruction_counts, function_map)
    # Быстрые версии циклов: сначала внешние (одна проверка на весь вложенный цикл); цикл,
    # пересекающийся с уже взятым, не берётся.
    plans: dict[int, loopgen.Plan] = {}
    for loop in sorted(loops.find_loops(program), key=lambda item: (-len(item.body), item.header)):
        if any(plan.loop.header in loop.body or loop.header in plan.loop.body for plan in plans.values()):
            continue
        result = loopgen.plan_loop(generator, loop)
        if isinstance(result, loopgen.Plan):
            plans[loop.header] = result
    # Выход из быстрой версии приходит в обычный код с другим состоянием W2.
    for plan in plans.values():
        for _source, target in plan.loop.exits:
            generator.reachable_otherwise.add(target)
    fragments = []
    loop_parts: dict[int, tuple[list[str], list[Fragment]]] = {}
    errors = []
    for address in sorted(program.instructions):
        try:
            fragments.append(generator.fragment(program.instructions[address]))
        except CodegenError as error:
            errors.append(str(error))
    for header, plan in sorted(plans.items()):
        try:
            body = [generator.loop_fragment(plan, program.instructions[address])
                    for address in sorted(plan.loop.fast_body)]
            guard = loopgen.guard_lines(plan, label(header))
            loop_parts[header] = (guard, body)
        except CodegenError as error:
            errors.append(str(error))
    if errors:
        raise CodegenError('нет шаблонов:\n' + '\n'.join(errors))

    def fragment_size(fragment: Fragment) -> int:
        size = sum(line_size(line) for line in fragment.lines if not line.startswith('@JUMP'))
        return size + len(fragment.jumps) * FAR_JUMP_SIZE + FAR_JUMP_SIZE

    # Заглушки входов только из констант (после основного кода: состояние W2 и предыдущей
    # инструкции генератора сбрасываются).
    stubs: dict[int, list[Fragment]] = {}
    for entry in sorted(generator.stub_runs):
        try:
            stubs[entry] = generator.stub_fragments(entry)
        except CodegenError as error:
            errors.append(str(error))
    if errors:
        raise CodegenError('нет шаблонов:\n' + '\n'.join(errors))

    page_of: dict[int, int] = {}
    page = first_page
    used = 0
    for fragment in fragments:
        size = fragment_size(fragment)                              # запас на переход при смене страницы
        if fragment.instruction.address in loop_parts:
            guard, body = loop_parts[fragment.instruction.address]
            size += sum(line_size(line) for line in guard) + sum(fragment_size(item) for item in body)
            plan = plans[fragment.instruction.address]
            if plan.lifted or plan.values or plan.bc_counter or plan.limit_counter:
                size += 24 * len(body)          # восстановление регистров на выходах и заглушки X_
        if fragment.instruction.address in stubs:
            size += sum(fragment_size(item) for item in stubs[fragment.instruction.address])
        if used + size > PAGE_LIMIT:
            page += 1
            used = 0
            if page > last_page:
                raise CodegenError('не хватает страниц кода')
        page_of[fragment.instruction.address] = page
        used += size
    def entry_name(source: Instruction):
        """Метка перехода из обычного кода: на заголовок взятого цикла снаружи — проверка."""
        def name(target: int) -> str:
            plan = plans.get(target)
            if plan is not None and (source.address not in plan.loop.body or
                                     (plan.reentrant and source.address in plan.loop.back_edges)):
                return plan.guard_label
            return label(target)
        return name

    def emit_lines(fragment: Fragment, page: int, name) -> None:
        for line in fragment.lines:
            if line.startswith('@JUMP'):
                index = int(line.split()[1])
                _name, target, condition = fragment.jumps[index]
                out.extend(indent(render_jump(target, condition, page_of, page, fragment.instruction, index, name)))
            elif line.endswith(':'):
                out.append(line)
            else:
                out.append('\t' + line)

    out: list[str] = []
    current = None
    pending_stubs: list[int] = []

    def flush_stubs() -> None:
        """Заглушки страницы — после её последнего фрагмента (он кончается переходом)."""
        for entry in pending_stubs:
            items = stubs[entry]
            for index, item in enumerate(items):
                out.append(f'D_{entry:05X}_{item.instruction.address:05X}:\t\t; {item.instruction.text}')
                emit_lines(item, current, entry_name(item.instruction))
                if item.instruction.mnemonic not in NO_FALLTHROUGH and index + 1 == len(items):
                    out.extend(indent(render_jump(item.instruction.next, None, page_of, current, item.instruction,
                                                  98, entry_name(item.instruction))))
        pending_stubs.clear()

    for position, fragment in enumerate(fragments):
        instruction = fragment.instruction
        page = page_of[instruction.address]
        if page != current:
            flush_stubs()
            out += ['', f'\tMMU #C000,{page}', '\tORG #C000']
            current = page
        if instruction.address in stubs:
            pending_stubs.append(instruction.address)
        if instruction.address in loop_parts:
            plan = plans[instruction.address]
            guard, body = loop_parts[instruction.address]
            out += indent(guard)
            body_page = {address: page for address in plan.loop.fast_body}

            def fast_name(target: int, plan=plan) -> str:
                return plan.label(target) if target in plan.loop.fast_body else label(target)
            fast_pages = dict(page_of)
            fast_pages.update(body_page)
            exit_stubs: list[str] = []

            def exit_jump(target, condition, item, jump, plan=plan, exit_stubs=exit_stubs):
                """Переход из быстрой версии: внутри тела — как есть; наружу — через
                восстановление поднятых регистров (условный — через заглушку X_)."""
                restore = loopgen.materialize_lines(plan, item.bc_saved)
                if target in plan.loop.fast_body or not restore or item.materialized:
                    return render_jump(target, condition, fast_pages, page, item.instruction, jump, fast_name)
                if condition is None:
                    return restore + render_jump(target, None, fast_pages, page, item.instruction, jump, fast_name)
                stub = f'X_{plan.loop.header:05X}_{item.instruction.address:05X}_{jump}'
                exit_stubs.extend([f'{stub}:'] + indent(restore + render_jump(target, None, fast_pages, page,
                                                                          item.instruction, jump, fast_name)))
                return [f'jp {condition},{stub}']
            for index, item in enumerate(body):
                out.append(f'{plan.label(item.instruction.address)}:\t\t; {item.instruction.text}')
                for line in item.lines:
                    if line.startswith('@JUMP'):
                        jump = int(line.split()[1])
                        _name, target, condition = item.jumps[jump]
                        out.extend(indent(exit_jump(target, condition, item, jump)))
                    elif line.endswith(':'):
                        out.append(line)
                    else:
                        out.append('\t' + line)
                if item.instruction.mnemonic not in NO_FALLTHROUGH:
                    following = item.instruction.next
                    upcoming = body[index + 1].instruction.address if index + 1 < len(body) else None
                    if upcoming != following:
                        out += indent(exit_jump(following, None, item, 98))
            out += exit_stubs
        out.append(f'{label(instruction.address)}:\t\t; {instruction.text}')
        emit_lines(fragment, page, entry_name(instruction))
        # Переход на следующую инструкцию, если в тексте за этой идёт не она (перекрытие,
        # пропуск), она на другой странице или отсутствует.
        if instruction.mnemonic not in NO_FALLTHROUGH:
            following = instruction.next
            upcoming = fragments[position + 1].instruction.address if position + 1 < len(fragments) else None
            if upcoming != following or page_of[upcoming] != page:
                out += indent(render_jump(following, None, page_of, page, instruction, 98, entry_name(instruction)))
            elif following in loop_parts and instruction.address not in plans[following].loop.body:
                # Проход сверху в заголовок взятого цикла попадает на проверку G_ (она стоит перед A_).
                pass
    flush_stubs()
    entry_labels = {label(address) for address in (set(program.entries) - program.constant_only) |
                    set(program.labels) | set(idle_points) | native_tail_targets()}
    merge_labels, backward = peephole.merge_points(out, entry_labels)
    out = peephole.optimize(out, merge_labels, backward)
    out = peephole.dead_stores(out, backward)
    return '\n'.join(out) + '\n', page_of


def dispatch_label(program, address: int) -> str:
    """Метка входа диспетчеризации: у входов только из констант — заглушка."""
    if address in program.constant_only and address in program.instructions:
        return f'D_{address:05X}_{address:05X}'
    return label(address)


def dispatch_target(program, address: int, page_of: dict[int, int], symbols: dict[str, int],
                    native_page: int | None = None, host2_page: int | None = None,
                    native_page2: int | None = None) -> tuple[int, int]:
    """(страница, адрес) входа диспетчеризации. Вход нативной процедуры VDAC2+ (NATIVE) — сразу она на своей странице:
    заглушка перевода там только переходит в неё (FARJP), так DISPATCH экономит заглушку и второй переход. Метки модуля
    n2 (n2.N_…) — вторая нативная страница (vdac2p_native2.asm, с 2026-09-26)."""
    if native_page is not None and address in NATIVE:
        if NATIVE[address] in NATIVE_HOST2:
            assert host2_page is not None
            return host2_page, symbols[NATIVE[address]]
        if NATIVE[address].startswith(NATIVE2_PREFIX):
            assert native_page2 is not None
            return native_page2, symbols[NATIVE[address]]
        return native_page, symbols[NATIVE[address]]
    return page_of[address], symbols[dispatch_label(program, address)]


def dispatch_pages(page_of: dict[int, int], entries: set[int], symbols: dict[str, int], program,
                   native_page: int | None = None, host2_page: int | None = None,
                   native_page2: int | None = None) -> list[bytes]:
    """Прямая таблица диспетчеризации: 16 страниц по 4 байта на IP (страница кода, адрес, 0);
    входы — возвраты из CALL, цели косвенных переходов, векторы и начала подпрограмм."""
    pages = [bytearray(b'\xFF' * 0x4000) for _ in range(16)]
    for address in entries:
        if address not in page_of:
            continue
        ip = (address - CODE_BASE) & 0xFFFF
        page, target = dispatch_target(program, address, page_of, symbols, native_page, host2_page, native_page2)
        offset = (ip & 0xFFF) * 4
        pages[ip >> 12][offset:offset + 4] = bytes((page, target & 0xFF, target >> 8, 0))
    return [bytes(page) for page in pages]
