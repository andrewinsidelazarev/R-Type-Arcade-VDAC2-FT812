"""Покадровая сверка Z80-сборки p2c с CPython в модели TS-Config (ядро Z80 kosarev).

Страницы сборки загружаются в модель памяти TS-Config (окна #0000–#FFFF,
переключение страниц портами #10AF–#13AF), программа исполняется до точки
останова конца кадра. Проверочный адаптер пишет команды вывода и звука в
страницы журнала; они переводятся в кодировку записи CPython (как у сверки
на ПК) и сравниваются с тем же кадром app.main. Считаются такты на кадр,
глубина стека и заполнение кучи.
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import re
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from z80 import Z80Machine  # noqa: E402

import p2c_app  # noqa: E402
import p2c_z80  # noqa: E402

BUILD = p2c_z80.BUILD
PAGE = 0x4000
STACK_PATTERN = 0xA5


class TSConfModel:
    """Z80 с памятью TS-Config: 4 окна по 16 КБ, страницы переключаются портами PAGE0–PAGE3."""

    def __init__(self, pages: dict[int, bytes], zero_pages: set[int] = frozenset(), seed: int = 0,
                 general_sound: bool = True) -> None:
        # Плата General Sound: по умолчанию считаем, что она есть, — это конфигурация, с которой
        # сверяется эталон (у него музыка и эффекты). general_sound=False моделирует машину без
        # платы: порт #BB не отвечает, порт переходит на эффекты AY и не играет музыку.
        self.general_sound = general_sound
        self.cpu = Z80Machine()
        self.pages: dict[int, bytearray] = {number: bytearray(data) for number, data in pages.items()}
        # Страница без блока SPG и вне списка обнуляемых загрузчиком — неочищенное ОЗУ.
        self.zero_pages = set(zero_pages)
        self.noise = random.Random(seed)
        self.windows = [0, 0, 0, 0]
        self.memory = self.cpu.memory
        self.switches = 0
        self.border = 0
        # Регистры DMA TS-Config (#1A..#1F адреса, #26 длина, #28 число пакетов).
        self.dma = {register: 0 for register in (0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x26, 0x28)}
        self.cpu.set_output_callback(self.output)
        self.cpu.set_input_callback(self.input)

    def page(self, number: int) -> bytearray:
        if number not in self.pages:
            self.pages[number] = (bytearray(PAGE) if number in self.zero_pages
                                  else bytearray(self.noise.randbytes(PAGE)))
        return self.pages[number]

    def map(self, window: int, number: int) -> None:
        base = window * PAGE
        current = self.windows[window]
        self.page(current)[:] = self.memory[base:base + PAGE]
        self.windows[window] = number
        self.memory[base:base + PAGE] = self.page(number)
        self.switches += 1

    def map_all(self, numbers: list[int]) -> None:
        for window, number in enumerate(numbers):
            self.windows[window] = number
            self.memory[window * PAGE:(window + 1) * PAGE] = self.page(number)

    def output(self, address: int, value: int) -> None:
        low = address & 0xFF
        if low == 0xAF:
            register = address >> 8
            if 0x10 <= register <= 0x13:
                self.map(register - 0x10, value)
            elif register == 0x0F:
                self.border = value
            elif register in self.dma:
                self.dma[register] = value
            elif register == 0x27 and value & 0x7F == 0x01:
                self.dma_ram()

    def input(self, address: int) -> int:
        # Состояние DMA (#27): копирование исполняется сразу при записи режима.
        if address & 0xFF == 0xAF and address >> 8 == 0x27:
            return 0x00
        # Статус General Sound (#BB): бит 0 — команда принята, бит 7 — в FIFO есть место. Плата
        # отвечает мгновенно; без платы шина даёт #FF, и адаптер уходит по таймауту.
        if self.general_sound and address & 0xFF == 0xBB:
            return 0x00
        return 0xFF

    def dma_ram(self) -> None:
        """DMA RAM → RAM: (длина + 1) · 2 байта в пакете, (число + 1) пакетов; адрес — страница и
        14 бит смещения, при переходе границы — следующая страница."""
        source = (self.dma[0x1C] << 14) | ((self.dma[0x1B] << 8 | self.dma[0x1A]) & 0x3FFF)
        target = (self.dma[0x1F] << 14) | ((self.dma[0x1E] << 8 | self.dma[0x1D]) & 0x3FFF)
        count = (self.dma[0x26] + 1) * 2 * (self.dma[0x28] + 1)
        if (source & 0x3FFF) + count <= PAGE and (target & 0x3FFF) + count <= PAGE and source >> 14 != target >> 14:
            self.write_block(target, self.read_block(source, count))
            return
        for index in range(count):
            self.poke(target + index, self.peek(source + index))

    def read_block(self, linear: int, count: int) -> bytes:
        number, offset = linear >> 14, linear & 0x3FFF
        for window, mapped in enumerate(self.windows):
            if mapped == number:
                return bytes(self.memory[window * PAGE + offset:window * PAGE + offset + count])
        return bytes(self.page(number)[offset:offset + count])

    def write_block(self, linear: int, data: bytes) -> None:
        number, offset = linear >> 14, linear & 0x3FFF
        written = False
        for window, mapped in enumerate(self.windows):
            if mapped == number:
                self.memory[window * PAGE + offset:window * PAGE + offset + len(data)] = data
                written = True
        if not written:
            self.page(number)[offset:offset + len(data)] = data

    def peek(self, linear: int) -> int:
        number, offset = linear >> 14, linear & 0x3FFF
        for window, mapped in enumerate(self.windows):
            if mapped == number:
                return self.memory[window * PAGE + offset]
        return self.page(number)[offset]

    def poke(self, linear: int, value: int) -> None:
        number, offset = linear >> 14, linear & 0x3FFF
        written = False
        for window, mapped in enumerate(self.windows):
            if mapped == number:
                self.memory[window * PAGE + offset] = value
                written = True
        if not written:
            self.page(number)[offset] = value

    def page_bytes(self, number: int) -> bytes:
        for window, mapped in enumerate(self.windows):
            if mapped == number:
                return bytes(self.memory[window * PAGE:(window + 1) * PAGE])
        return bytes(self.page(number))

    def word(self, address: int) -> int:
        return self.memory[address] | (self.memory[address + 1] << 8)


def bank_labels(page: int, report: dict, linked: dict[str, int]) -> list[tuple[int, str]]:
    # Глобальные метки банка — из карты компоновки (24-битные адреса), статические — из
    # листинга банка текущей сборки (листинги прежних раскладок не читаются).
    labels = {(address & 0xFFFF, name.lstrip('_')) for name, address in linked.items()
              if address >> 16 == page and not name.startswith(('s__', 'l__', 'b_'))}
    listing = BUILD / f'bank_{page:02x}.lst'
    if f'{page:02X}' in report['banks'] and listing.is_file():
        labels |= {(0xC000 + int(match[1], 16), match[2]) for match in
                   re.finditer(r'^\s+([0-9A-F]{8})\s+\d+\s+_([A-Za-z_]\w*)::?\s*$',
                               listing.read_text(encoding='latin1'), re.M)}
    return sorted(labels)


class Locator:
    """Имя функции по адресу: резидент — карта компоновки, банк — листинг банка."""

    def __init__(self, report: dict) -> None:
        # Статические функции резидента: метки листингов модулей, база — по глобальной метке модуля.
        linked = p2c_z80.map_symbols((BUILD / 'program.map').read_text(encoding='latin1'))
        resident = {(address, name) for name, address in linked.items()
                    if address < 0x3400 and not name.startswith(('s__', 'l__', 'b_'))}
        for listing in ('runtime_hot', 'z80_hot', 'z80_main', 'adapter', 'tables', 'p2c_z80_crt', 'p2c_z80_access'):
            path = BUILD / f'{listing}.lst'
            if not path.is_file():
                continue
            labels = [(int(match[1], 16), match[2]) for match in
                      re.finditer(r'^\s+([0-9A-F]{8})\s+\d+\s+_?([A-Za-z_]\w*)::?\s*$',
                                  path.read_text(encoding='latin1'), re.M)]
            base = next((linked['_' + name] - offset for offset, name in labels if '_' + name in linked
                         and linked['_' + name] < 0x4000), None)
            if base is not None:
                resident |= {(base + offset, name) for offset, name in labels}
        self.resident = sorted(resident)
        self.report = report
        self.linked = linked
        self.banks: dict[int, list[tuple[int, str]]] = {}

    def __call__(self, pc: int, bank: int) -> str:
        if pc < 0x4000:
            table = self.resident
        else:
            if bank not in self.banks:
                self.banks[bank] = bank_labels(bank, self.report, self.linked)
            table = self.banks[bank]
        index = bisect.bisect_right(table, (pc, '￿')) - 1
        return f'{table[index][1]}+{pc - table[index][0]:#x}' if index >= 0 else f'#{pc:04X}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=400)
    parser.add_argument('--start-frame', type=int, default=320)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--chaos', action='store_true')
    parser.add_argument('--profile', type=int, default=0, help='шаг выборки PC в тактах (0 — без профиля)')
    parser.add_argument('--profile-from', type=int, default=0, help='первый кадр профиля')
    parser.add_argument('--state-every', type=int, default=0, help='сверка состояния объектов каждые N кадров')
    parser.add_argument('--watch-frame', type=int, default=0, help='кадр наблюдения записей в память')
    parser.add_argument('--trace-frame', type=int, default=0, help='кадр пошагового исполнения')
    parser.add_argument('--break-frame', type=int, default=0, help='кадр остановок на функциях --break-at')
    parser.add_argument('--break-at', action='append', default=[], help='имя функции банка для остановки')
    parser.add_argument('--watch', action='append', default=[], help='путь объекта от app для наблюдения')
    parser.add_argument('--idle', action='store_true', help='после старта без ввода (как ручной запуск)')
    parser.add_argument('--render', action='append', type=int, default=[],
                        help='кадр, для которого модель FT812 сохраняет изображение экрана')
    parser.add_argument('--report', default=str(BUILD / 'z80_check.json'))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    report = json.loads((BUILD / 'build_report.json').read_text(encoding='utf-8'))
    symbols = report['symbols']
    zero_pages = set(report.get('zero_pages', ()))
    pages = {int(path.stem.split('_')[1], 16): path.read_bytes() for path in (BUILD / 'pages').glob('page_*.bin')}
    pages = {number: data for number, data in pages.items() if number not in zero_pages}
    model = TSConfModel(pages, zero_pages, args.seed)
    locate = Locator(report)
    ft = None
    if report.get('adapter') == 'ft812':
        from p2c_z80_ft812_model import FT812Model, coordinate_inverse, expected_blits
        ft = FT812Model(model)
        catalog = json.loads((BUILD / 'catalog_model.json').read_text(encoding='utf-8'))
        entry_by_pixels: dict[str, int] = {}
        for index, digest in enumerate(catalog['pixels']):
            entry_by_pixels.setdefault(digest, index)
        inverse_x, inverse_y = coordinate_inverse()
        keys_down: set[str] = set()
        # Клавиатура ZX в модели: полуряды портов #xxFE, нажатая клавиша — нулевой бит.
        key_ports = {'O': (0xDF, 1), 'P': (0xDF, 0), 'Q': (0xFB, 0), 'A': (0xFD, 0), 'SPACE': (0x7F, 0),
                     'N': (0x7F, 3)}
        # Те же клавиши — скан-кодами PS/2 в очереди Mr.Gluk (#BFF7): ввод адаптера с 28.09.2026 читает клавиатуру
        # только оттуда (p2c_ft_keyboard), смена нажатия — код нажатия или F0 и код.
        from v30z80_ft812 import PS2_CODES, ps2_changes
        ps2_names = {'O': 'o', 'P': 'p', 'Q': 'q', 'A': 'a', 'SPACE': 'space', 'N': 'n'}
        ps2_state = {'down': set(), 'queue': bytearray()}
        chained_input = ft.input

        def keyboard_input(address: int) -> int:
            if address & 0xFF == 0xFE:
                value = 0xFF
                for key in keys_down:
                    row, bit = key_ports[key]
                    if (address >> 8) == row:
                        value &= ~(1 << bit) & 0xFF
                return value
            if address == 0xBFF7:
                pressed = {ps2_names[key] for key in keys_down if ps2_names.get(key) in PS2_CODES}
                if pressed != ps2_state['down']:
                    ps2_state['queue'] += ps2_changes(ps2_state['down'], pressed)
                    ps2_state['down'] = pressed
                return ps2_state['queue'].pop(0) if ps2_state['queue'] else 0
            return chained_input(address)
        model.cpu.set_input_callback(keyboard_input)

    app, sound = p2c_app.build_snapshot()
    compiler, module, image_id, image_ids, alive, roots, _entries = p2c_z80.prepare(app)
    image = p2c_z80.image_for(compiler, module, image_id, roots, report['data'])
    _mapping, content = image.physical_pages(p2c_z80.PHYSICAL_DATA_FIRST)
    for number, data in content.items():
        if pages.get(number, bytes(0x4000) if number in zero_pages else None) != data:
            raise SystemExit(f'страница данных #{number:02X} модели отличается от сборки: пересобрать')

    # Стек заполняется образцом для замера глубины.
    stack_bottom = p2c_z80.STACK_BOTTOM
    resident = model.page(report['page_resident'])
    resident[stack_bottom:0x4000] = bytes([STACK_PATTERN]) * (0x4000 - stack_bottom)
    model.map_all([report['page_resident'], report['page_data1'], report['page_data2'], report['first_bank']])
    cpu = model.cpu
    cpu.pc = report['entry']
    cpu.sp = 0x4000
    cpu.a = report['first_bank']
    hook = symbols['_p2c_z80_hook']
    fault = symbols['_p2c_raise']
    cpu.set_breakpoint(hook)
    cpu.set_breakpoint(fault)

    from p2c_app import INPUT_FIELDS, Recorder, first_difference, input_bits
    from p2c_z80_state import Z80StateComparer
    comparer = Z80StateComparer(model, compiler, module.r, module.layout, image_ids,
                                {int(key): value for key, value in report['page_map'].items()})

    def check_state(frame: int) -> None:
        comparer.collect = []
        found = comparer.compare_root(app, symbols['_p2c_root_app'])
        found_all = comparer.collect + ([found] if found else [])
        comparer.collect = None
        if found_all:
            raise SystemExit(f'кадр {frame}: состояние расходится ({len(found_all)}), {heap_state()}:\n' +
                             '\n'.join(found_all[:40]))

    from rtype_port.autopilot import Stage1Autopilot
    from rtype_port.game import InputState
    game = app.prepared_game
    recorder = Recorder(image_ids, game.enemy_world.atlas)
    pilot = Stage1Autopilot()
    rng = random.Random(args.seed)
    chaos_left = 0
    chaos_input = None
    profile: dict[str, int] = {}
    inclusive: dict[str, int] = {}
    trampoline_return = symbols.get('___sdcc_bcall_ehl', 0x26) + 0x11
    frame_ticks = []

    def run_to_hook(frame: int) -> int:
        budget = 400_000_000
        spent = 0
        while True:
            sampling = args.profile and frame >= args.profile_from
            step = args.profile if sampling else budget
            cpu.ticks_to_stop = step
            events = cpu.run()
            # Чтение ticks_to_stop через свойство пакета искажает старший байт: читаем байты состояния.
            remaining = int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            used = step - remaining
            spent += used
            if sampling:
                bank = model.memory[symbols['_p2c_bank']]
                name = locate(cpu.pc, bank).split('+')[0]
                profile[name] = profile.get(name, 0) + used
                # Включительное время: цепочка кадров IX (у банкового вызова — возврат через трамплин).
                seen_names = {name}
                frame_pointer = cpu.ix
                frame_bank = bank
                for _depth in range(40):
                    if not (p2c_z80.STACK_BOTTOM <= frame_pointer < 0x3FF8):
                        break
                    return_address = model.word(frame_pointer + 2)
                    if return_address == trampoline_return:
                        frame_bank = model.memory[frame_pointer + 4]
                        return_address = model.word(frame_pointer + 5)
                    caller = locate(return_address, frame_bank).split('+')[0]
                    if caller not in seen_names:
                        seen_names.add(caller)
                        inclusive[caller] = inclusive.get(caller, 0) + used
                    frame_pointer = model.word(frame_pointer)
                inclusive[name] = inclusive.get(name, 0) + used
            if cpu.pc == hook:
                cpu.ticks_to_stop = 0
                return spent
            if cpu.pc == fault:
                code = cpu.hl - 0x10000 if cpu.hl & 0x8000 else cpu.hl
                caller = model.word(cpu.sp)
                bank = model.memory[symbols['_p2c_bank']]
                raise SystemExit(f'отказ Z80 на кадре {frame}: код {code} из {locate(caller, bank)} '
                                 f'(банк #{bank:02X})')
            if spent >= budget:
                raise SystemExit(f'кадр {frame}: больше {budget} тактов, PC {locate(cpu.pc, model.memory[symbols["_p2c_bank"]])}')
            if remaining and not events & 0x2 and not sampling and events == 0:
                raise SystemExit(f'кадр {frame}: остановка без события на #{cpu.pc:04X}')

    def step_past_hook() -> None:
        cpu.clear_breakpoint(hook)
        cpu.ticks_to_stop = 1
        cpu.run()
        cpu.set_breakpoint(hook)

    def z80_commands() -> tuple[list, list]:
        log = model.page_bytes(report['log_page'])
        log2 = model.page_bytes(report['log_page2'])
        count = struct.unpack_from('<H', log, 0)[0]
        cells = struct.unpack_from('<H', log2, 0)[0]
        keys = struct.unpack_from(f'<{cells}I', log2, 2)
        texts = struct.unpack_from('<H', log2, 0x3400)[0]
        commands = []
        for index in range(count):
            image_number, x, y = struct.unpack_from('<Hhh', log, 2 + index * 6)
            if image_number == 0xFFFF:
                commands.append((0xFFFFFFFF, 0, 0))
            elif (image_number & 0xC000) == 0xC000:
                pointer, color, antialias = struct.unpack_from('<HIB', log2, 0x3402 + (image_number & 0x3F) * 7)
                length, data = struct.unpack_from('<HH', bytes(model.memory[pointer + 2:pointer + 6]))
                text = bytes(model.memory[data:data + length]).decode('utf-8')
                commands.append((('text', text, bool(antialias),
                                  ((color >> 16) & 255, (color >> 8) & 255, color & 255)), x, y))
            elif image_number & 0x8000:
                commands.append((keys[image_number & 0x7FFF], x, y))
            else:
                commands.append((image_number, x, y))
        sounds_count = struct.unpack_from('<H', log2, 0x3000)[0]
        sounds = list(struct.unpack_from(f'<{sounds_count}h', log2, 0x3002))
        del texts
        return commands, sounds

    def compare_frame() -> str | None:
        if ft is None:
            commands, sounds = z80_commands()
            difference = first_difference(recorder.commands, commands)
            if difference:
                return f'{difference}; CPython {recorder.commands[:6]} Z80 {commands[:6]}'
            if sounds != sound.commands:
                return f'звук CPython={sound.commands} Z80={sounds}'
            return None
        if ft.errors:
            return 'модель FT812: ' + '; '.join(ft.errors[:5])
        expected = expected_blits(recorder.commands, catalog)
        actual = ft.decode(catalog['defines'], entry_by_pixels, inverse_x, inverse_y)
        difference = first_difference(expected, actual)
        if difference:
            dropped = model.word(symbols['_p2c_ft_dropped'])
            return f'{difference}; отброшено DL {dropped}; ожидалось {expected[:5]} Z80 {actual[:5]}'
        return None

    def heap_state() -> str:
        top = model.word(symbols['_p2c_heap_top'])
        used = model.word(symbols['_p2c_used_bytes'])
        peak = model.word(symbols['_p2c_peak_bytes'])
        deepest = next((address for address in range(stack_bottom, 0x4000)
                        if model.memory[address] != STACK_PATTERN), 0x4000)
        return f'куча: вершина #{top:04X}, занято {used}, пик {peak}; стек до #{deepest:04X}'

    started = time.perf_counter()
    recorder.commands.clear()
    app.title.render(recorder)
    ticks = run_to_hook(0)
    difference = compare_frame()
    if difference:
        raise SystemExit(f'кадр 0 (первичная отрисовка титула): {difference}')
    if args.state_every:
        check_state(0)
    print(f'кадр 0: совпадает, тактов {ticks}, {heap_state()}', flush=True)
    for frame in range(1, args.frames + 1):
        start_pressed = frame == args.start_frame
        if app.game is not None and args.idle:
            planned = InputState()
        elif app.game is not None:
            planned = pilot.next(app.game)
            if args.chaos:
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
        app.frame(start_pressed, planned, recorder)
        if ft is None:
            model.memory[symbols['_p2c_z80_rec_start']] = int(start_pressed)
            model.memory[symbols['_p2c_z80_rec_bits']] = input_bits(planned)
        else:
            keys_down.clear()
            bits = input_bits(planned)
            for bit, key in enumerate(('O', 'P', 'Q', 'A', 'SPACE', 'N')):
                if bits & (1 << bit):
                    keys_down.add(key)
            if start_pressed:
                keys_down.add('SPACE')
        watch_log = []
        if args.watch_frame == frame:
            # Отладка порчи памяти: записи в объекты по путям --watch и в переменные кучи.
            comparer.collect = []
            comparer.compare_root(app, symbols['_p2c_root_app'])
            comparer.collect = None
            ranges = []
            for path in args.watch:
                target = app
                for part in path.split('.'):
                    target = target[int(part)] if part.isdigit() else getattr(target, part)
                pointer = comparer.seen[id(target)]
                ranges.append((pointer, pointer + 64, path))
            for name in ('_p2c_peak_bytes', '_p2c_heap_top', '_p2c_used_bytes'):
                ranges.append((symbols[name], symbols[name] + 2, name))

            code_pages = {int(page, 16) for page in report['banks']}

            def on_write(address: int, value: int) -> None:
                for low, high, label in ranges:
                    if low <= address < high:
                        bank = model.memory[symbols['_p2c_bank']]
                        watch_log.append((label, address - low, value, locate(cpu.pc, bank), cpu.sp))
                if address >= 0xC000 and model.windows[3] in code_pages:
                    bank = model.memory[symbols['_p2c_bank']]
                    watch_log.append(('КОД', address, value, locate(cpu.pc, bank), cpu.sp))
                model.memory[address] = value
            cpu.set_write_callback(on_write)
        step_past_hook()
        if args.break_frame == frame and args.break_at:
            # Остановки на входе функции (метка листинга банка): регистры и вершина стека.
            targets = []
            for name in args.break_at:
                for page in [int(page, 16) for page in report['banks']]:
                    for address, label in bank_labels(page, report, locate.linked):
                        if label == name:
                            targets.append((address, page, name))
            for address, _page, _name in targets:
                cpu.set_breakpoint(address)
            hits = 0
            while True:
                cpu.ticks_to_stop = 400_000_000
                cpu.run()
                if cpu.pc == hook:
                    break
                if cpu.pc == fault:
                    break
                bank = model.memory[symbols['_p2c_bank']]
                for address, page, name in targets:
                    if cpu.pc == address and bank == page:
                        stack = bytes(model.memory[cpu.sp:cpu.sp + 16]).hex(' ')
                        print(f'остановка {name}: HL #{cpu.hl:04X} DE #{cpu.de:04X} A #{cpu.a:02X} '
                              f'SP #{cpu.sp:04X} стек {stack}')
                        hits += 1
                pc = cpu.pc
                for address, _page, _name in targets:
                    cpu.clear_breakpoint(address)
                cpu.ticks_to_stop = 1
                cpu.run()
                for address, _page, _name in targets:
                    cpu.set_breakpoint(address)
            for address, _page, _name in targets:
                cpu.clear_breakpoint(address)
            print(f'остановок {hits}')
        if args.trace_frame == frame:
            # Пошаговое исполнение кадра с кольцом последних адресов: поиск перехода на #0000.
            from collections import deque as ring_type
            history = ring_type(maxlen=80)
            steps = 0
            cpu.clear_breakpoint(hook)
            while cpu.pc != hook:
                pc = cpu.pc
                bank = model.memory[symbols['_p2c_bank']]
                text, length = cpu._disasm(bytes(model.memory[pc:pc + 4]))
                if pc == report['entry']:
                    for source, target, bank_now, sp, instruction in history:
                        print(f'  #{source:04X} {locate(source, bank_now)} [{instruction}] -> #{target:04X} '
                              f'{locate(target, model.memory[symbols["_p2c_bank"]])} банк #{bank_now:02X} SP #{sp:04X}')
                    raise SystemExit(f'кадр {frame}: переход на старт после {steps} шагов')
                cpu.ticks_to_stop = 1
                cpu.run()
                steps += 1
                if cpu.pc != (pc + length) & 0xFFFF:
                    history.append((pc, cpu.pc, bank, cpu.sp, text))
            cpu.set_breakpoint(hook)
        ticks = run_to_hook(frame)
        frame_ticks.append(ticks)
        if watch_log:
            for item in watch_log[:200]:
                print('запись', item)
        if ft is not None and frame in args.render:
            from PIL import Image
            shot = BUILD / 'frames' / f'model_{frame:05d}.png'
            shot.parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes('RGB', (1024, 768), ft.render()).save(shot)
            commands = len(ft.display_bitmaps())
            words = next((offset for offset in range(0, 0x2000, 4)
                          if int.from_bytes(ft.shown_dl[offset:offset + 4], 'little') == 0), 0x2000) // 4
            print(f'кадр {frame}: изображение модели {shot}, вершин {commands}, команд DL {words}', flush=True)
        difference = compare_frame()
        if difference:
            if args.state_every:
                check_state(frame)
            raise SystemExit(f'кадр {frame}: {difference}')
        if args.state_every and frame % args.state_every == 0:
            check_state(frame)
        if frame % 20 == 0 or frame == args.start_frame + 1:
            print(f'кадр {frame}: совпадает, тактов {ticks}, переключений страниц {model.switches}, '
                  f'{heap_state()}, {frame / (time.perf_counter() - started):.1f} к/с', flush=True)
    result = {'result': 'identical', 'frames': args.frames, 'ticks_max': max(frame_ticks, default=0),
              'ticks_median': sorted(frame_ticks)[len(frame_ticks) // 2] if frame_ticks else 0}
    if profile:
        total = sum(profile.values())
        result['profile'] = [(name, spent, round(100 * spent / total, 1))
                             for name, spent in sorted(profile.items(), key=lambda item: -item[1])[:60]]
        result['inclusive'] = [(name, spent, round(100 * spent / total, 1))
                               for name, spent in sorted(inclusive.items(), key=lambda item: -item[1])[:80]]
        for name, spent, share in result['profile'][:25]:
            print(f'{share:5.1f}% {spent:10d} {name}')
        print('--- включительно')
        for name, spent, share in result['inclusive'][:40]:
            print(f'{share:5.1f}% {spent:10d} {name}')
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('profile', 'inclusive')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
