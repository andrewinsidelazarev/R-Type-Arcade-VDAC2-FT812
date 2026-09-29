"""Модель VDAC2 (FT812) для проверки видеоадаптера переведённой программы World ROM.

Подключается к TSConfModel (p2c_z80_check): SPI TS-Config (порт #57 данные, #77 выбор),
DMA RAM→SPI (режим #82: данные страниц идут в открытую запись SPI) и SPI→RAM (режим #02: байты SD-карты, как IN из #57,
— в страницу приёмника; DMA_SPI_READS — счётчик байт для цены времени), RAM_G, RAM_DL,
REG_DLSWAP, очередь сопроцессора через REG_CMDB_WRITE с CMD_INFLATE, REG_CMDB_SPACE.
Клавиатура ZX и Kempston — из заданного набора нажатых клавиш. На той же шине SPI — SD-карта
(необязательная модель Z-Controller: байты #57, пока FT812 не выбран, и выбор #77 — ей).
Клавиатура PS/2 — скан-коды набора 2 в очереди Mr.Gluk (чтение #BFF7, 0 — очередь пуста) при смене нажатия
клавиш набора (PS2_CODES: клавиши ZX по именам, стрелки «right», «left», «down», «up», правый Alt «altgr», Esc
«esc»); игра с 28.09.2026 берёт клавиши только отсюда, матрица ZX (#xxFE) по именам клавиш осталась для прочих проверок;
Kempston-мышь: кнопки «lmb», «rmb», «mmb» (#FADF биты 0…2, активный ноль), движение
«mouse_right», «mouse_left», «mouse_up», «mouse_down» — MOUSE_COUNTS отсчётов на чтение счётчика #FBDF / #FFDF.

render() строит кадр 1024×768 RGB из показанного display list: CLEAR с ножницами, VERTEX2II
и VERTEX2F с VERTEX_TRANSLATE, параметры BITMAP_* у каждого handle сохраняются между списками
(как у FT81X), BITMAP_TRANSFORM A…F, PALETTE_SOURCE и формат PALETTED4444, смешение
SRC_ALPHA / ONE_MINUS_SRC_ALPHA, выборка NEAREST по центрам пикселей, BORDER.
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

RAM_G_SIZE = 1 << 20
RAM_DL = 0x300000
RAM_DL_SIZE = 0x2000
REG_BASE = 0x302000
REG_FRAMES = 0x302004
REG_DLSWAP = 0x302054
REG_CMD_READ = 0x3020F8
REG_CMD_WRITE = 0x3020FC
REG_CMDB_SPACE = 0x302574
REG_CMDB_WRITE = 0x302578
WIDTH, HEIGHT = 1024, 768
PALETTED4444 = 15
ARGB4 = 6

# Клавиатура ZX: полуряд (старший байт порта #xxFE) → клавиши битов 0…4.
KEY_ROWS = {
    0xFE: ('caps', 'z', 'x', 'c', 'v'), 0xFD: ('a', 's', 'd', 'f', 'g'), 0xFB: ('q', 'w', 'e', 'r', 't'),
    0xF7: ('1', '2', '3', '4', '5'), 0xEF: ('0', '9', '8', '7', '6'), 0xDF: ('p', 'o', 'i', 'u', 'y'),
    0xBF: ('enter', 'l', 'k', 'j', 'h'), 0x7F: ('space', 'sym', 'm', 'n', 'b'),
}
# Клавиатура PS/2 (набор 2) — очередь Mr.Gluk (#BFF7), единственный источник клавиш игры с 28.09.2026: имя клавиши
# набора → код нажатия (у расширенных — с E0; отпускание — F0 перед последним байтом). Клавиши ZX по именам — как
# их даёт AVR ZX Evolution с клавиатуры PC («caps» — левый Shift, «sym» — правый Shift); стрелки — псевдоклавиши
# «right», «left», «down», «up»; правый Alt — «altgr»; Esc — «esc» (шаг клавиш и джойстика ×1 ↔ ×2, с 29.09.2026).
PS2_CODES = {
    'a': b'\x1C', 'b': b'\x32', 'c': b'\x21', 'd': b'\x23', 'e': b'\x24', 'f': b'\x2B', 'g': b'\x34', 'h': b'\x33',
    'i': b'\x43', 'j': b'\x3B', 'k': b'\x42', 'l': b'\x4B', 'm': b'\x3A', 'n': b'\x31', 'o': b'\x44', 'p': b'\x4D',
    'q': b'\x15', 'r': b'\x2D', 's': b'\x1B', 't': b'\x2C', 'u': b'\x3C', 'v': b'\x2A', 'w': b'\x1D', 'x': b'\x22',
    'y': b'\x35', 'z': b'\x1A', '0': b'\x45', '1': b'\x16', '2': b'\x1E', '3': b'\x26', '4': b'\x25', '5': b'\x2E',
    '6': b'\x36', '7': b'\x3D', '8': b'\x3E', '9': b'\x46', 'space': b'\x29', 'enter': b'\x5A', 'caps': b'\x12',
    'sym': b'\x59', 'right': b'\xE0\x74', 'left': b'\xE0\x6B', 'down': b'\xE0\x72', 'up': b'\xE0\x75',
    'altgr': b'\xE0\x11', 'esc': b'\x76',
}


def ps2_changes(before: set[str], after: set[str]) -> bytes:
    """Скан-коды смены нажатых клавиш PS/2: сначала отпускания, затем нажатия, в порядке PS2_CODES."""
    out = bytearray()
    for name, code in PS2_CODES.items():
        if name in before and name not in after:
            out += code[:-1] + b'\xF0' + code[-1:]
    for name, code in PS2_CODES.items():
        if name in after and name not in before:
            out += code
    return bytes(out)


MOUSE_COUNTS = 3                 # отсчётов счётчика мыши на чтение при нажатой псевдоклавише движения
JOY_KEYS = ('joy_right', 'joy_left', 'joy_down', 'joy_up', 'joy_fire', 'joy_force', '', 'joy_start')
# Биты 0…4 порта #1F — как у обычного Kempston; бит 5 — вторая кнопка джойстика (отделение и возврат
# Force), бит 6 не используется (пустое имя не совпадает ни с одной псевдоклавишей), бит 7 — восьмая
# кнопка: только старт игры.


class Ft812Model:
    def __init__(self, model, sd=None, corner: bool = False) -> None:
        self.model = model
        self.sd = sd
        # Выборка текстуры: по центру пикселя (по умолчанию) или по его углу — так ведёт себя эмулятор
        # FT812 в Unreal (строка за краем ячейки у отражённого вывода при F = высота·256).
        self.sample_offset = 0 if corner else 8
        self.ram_g = bytearray(RAM_G_SIZE)
        self.ram_dl = bytearray(RAM_DL_SIZE)
        self.shown_dl = bytes(RAM_DL_SIZE)
        self.registers: dict[int, int] = {}
        self.frames = 0                          # REG_FRAMES: кадры развёртки задаёт сверка (кадр за кадр игры)
        self.swaps = 0
        self.selected = False
        self.phase = 0
        self.writing = False
        self.address = 0
        self.start = 0
        self.read_state = None
        self.fifo = bytearray()
        self.inflate = None
        self.inflates = 0
        self.copies = 0
        self.dma_ops = 0
        self.errors: list[str] = []
        self.keys: set[str] = set()
        self.kempston = 0
        self.ps2_queue = bytearray()     # скан-коды PS/2 очереди Mr.Gluk
        self.ps2_down: set[str] = set()  # клавиши PS/2, уже переданные нажатыми
        self.mouse_x = 0                 # счётчики Kempston-мыши (8 бит)
        self.mouse_y = 0
        self.handles = {handle: {'source': 0, 'format': 0, 'stride': 0, 'height': 0, 'width_px': 0, 'height_px': 0,
                                 'filter': 0, 'wrapx': 0, 'wrapy': 0} for handle in range(32)}
        self.dma = {'src_l': 0, 'src_h': 0, 'src_x': 0, 'dst_l': 0, 'dst_h': 0, 'dst_x': 0, 'len': 0, 'num': 0}
        self.dma_spi_reads = 0                   # байт SD, прочитанных DMA SPI→RAM (всего)
        self.chain_output = model.output
        self.chain_input = model.input
        model.cpu.set_output_callback(self.output)
        model.cpu.set_input_callback(self.input)

    # --- порты -------------------------------------------------------------------------------

    def output(self, address: int, value: int) -> None:
        low = address & 0xFF
        if low == 0x77:
            self.selected = value == 0x07
            self.phase = 0
            self.read_state = None
            if self.sd is not None:
                self.sd.output(address, value)
            return
        if low == 0x57:
            if self.selected or self.sd is None:
                self.spi_byte(value)
            else:
                self.sd.output(address, value)
            return
        if low == 0xAF:
            register = address >> 8
            names = {0x1A: 'src_l', 0x1B: 'src_h', 0x1C: 'src_x', 0x1D: 'dst_l', 0x1E: 'dst_h', 0x1F: 'dst_x',
                     0x26: 'len', 0x28: 'num'}
            if register in names:
                self.dma[names[register]] = value
            if register == 0x27 and value == 0x82:
                self.dma_spi()
                return
            if register == 0x27 and value == 0x02:
                self.dma_spi_read()
                return
        self.chain_output(address, value)

    def input(self, address: int) -> int:
        low = address & 0xFF
        if low == 0x57:
            if not self.selected and self.sd is not None:
                return self.sd.input(address)
            if self.read_state == 'dummy':
                self.read_state = 'data'
                return 0
            if self.read_state == 'data':
                value = self.read(self.address)
                self.address += 1
                return value
            return 0xFF
        if low == 0x1F:
            # Kempston-джойстик: значение kempston и псевдоклавиши «joy_right» (бит 0), «joy_left» (1), «joy_down» (2),
            # «joy_up» (3), «joy_fire» (4), «joy_force» (5), «joy_start» (7); 1 — нажата.
            return self.kempston | sum(1 << bit for bit, name in enumerate(JOY_KEYS) if name in self.keys)
        if address == 0xBFF7:
            pressed = {name for name in self.keys if name in PS2_CODES}
            if pressed != self.ps2_down:
                self.ps2_queue += ps2_changes(self.ps2_down, pressed)
                self.ps2_down = pressed
            return self.ps2_queue.pop(0) if self.ps2_queue else 0
        if address == 0xFADF:
            return (0xFF & ~(1 if 'lmb' in self.keys else 0) & ~(2 if 'rmb' in self.keys else 0) &
                    ~(4 if 'mmb' in self.keys else 0))
        if address == 0xFBDF:
            self.mouse_x = (self.mouse_x + MOUSE_COUNTS * (('mouse_right' in self.keys) -
                                                          ('mouse_left' in self.keys))) & 0xFF
            return self.mouse_x
        if address == 0xFFDF:
            self.mouse_y = (self.mouse_y + MOUSE_COUNTS * (('mouse_up' in self.keys) -
                                                          ('mouse_down' in self.keys))) & 0xFF
            return self.mouse_y
        if low == 0xFE:
            row = KEY_ROWS.get(address >> 8, ())
            bits = 0x1F
            for bit, name in enumerate(row):
                if name in self.keys:
                    bits &= ~(1 << bit)
            return bits | 0xE0
        return self.chain_input(address)

    def load_counters(self) -> dict[str, int]:
        """Нагрузка на FT812 с начала работы модели (байты): запись по SPI в RAM_G, RAM_DL и очередь сопроцессора
        (сюда же DMA RAM→SPI), копирование и заливка сопроцессора в RAM_G, распакованное CMD_INFLATE."""
        return dict(getattr(self, 'load', {}))

    def count_load(self, name: str, value: int) -> None:
        load = self.__dict__.setdefault('load', {})
        load[name] = load.get(name, 0) + value

    def spi_byte(self, value: int) -> None:
        if not self.selected:
            return
        if self.phase == 0:
            self.writing = bool(value & 0x80)
            self.address = value & 0x3F
            self.phase = 1
            return
        if self.phase < 3:
            self.address = (self.address << 8) | value
            self.phase += 1
            if self.phase == 3:
                self.start = self.address
            return
        if self.writing:
            if RAM_DL <= self.start < RAM_DL + RAM_DL_SIZE and self.address >= RAM_DL + RAM_DL_SIZE:
                self.errors.append(f'запись display list за RAM_DL: #{self.address:06X}')
            self.count_load('spi_' + ('ram_g' if self.address < RAM_G_SIZE else 'ram_dl'
                                      if RAM_DL <= self.address < RAM_DL + RAM_DL_SIZE else 'cmd'
                                      if REG_CMDB_WRITE <= self.address < REG_CMDB_WRITE + 4 else 'reg'), 1)
            self.write(self.address, value)
            if not REG_CMDB_WRITE <= self.address < REG_CMDB_WRITE + 4:
                self.address += 1
        else:
            self.read_state = 'dummy'

    def dma_spi(self) -> None:
        self.dma_ops += 1
        if not (self.selected and self.writing and self.phase >= 3):
            self.errors.append('DMA RAM->SPI без открытой записи SPI')
            return
        count = (self.dma['num'] + 1) * (self.dma['len'] + 1) * 2
        page = self.dma['src_x']
        offset = ((self.dma['src_h'] << 8) | self.dma['src_l']) & 0x3FFE
        position = 0
        while position < count:
            data = self.model.page_bytes(page)
            chunk = min(count - position, 0x4000 - offset)
            target = self.address
            if RAM_DL <= self.start < RAM_DL + RAM_DL_SIZE and target + chunk > RAM_DL + RAM_DL_SIZE:
                self.errors.append(f'пакет display list за RAM_DL: #{target:06X}+{chunk}')
            if RAM_DL <= target and target + chunk <= RAM_DL + RAM_DL_SIZE:
                self.ram_dl[target - RAM_DL:target - RAM_DL + chunk] = data[offset:offset + chunk]
                self.address += chunk
                self.count_load('spi_ram_dl', chunk)
            elif target + chunk <= RAM_G_SIZE:
                self.ram_g[target:target + chunk] = data[offset:offset + chunk]
                self.address += chunk
                self.count_load('spi_ram_g', chunk)
            else:
                self.count_load('spi_cmd' if REG_CMDB_WRITE <= target < REG_CMDB_WRITE + 4 else 'spi_reg', chunk)
                for byte in data[offset:offset + chunk]:
                    self.write(self.address, byte)
                    if not REG_CMDB_WRITE <= self.address < REG_CMDB_WRITE + 4:
                        self.address += 1
            position += chunk
            page += 1
            offset = 0

    def dma_spi_read(self) -> None:
        """DMA SPI→RAM (#02): (длина + 1)·2·(число + 1) байт с SD-карты — каждый как IN из #57 (прошлый байт, запуск
        следующего обмена), в страницу приёмника со смещения (14 бит, чётное; переход страницы — в следующую)."""
        self.dma_ops += 1
        if self.selected or self.sd is None:
            self.errors.append('DMA SPI->RAM не с SD-карты')
            return
        count = (self.dma['num'] + 1) * (self.dma['len'] + 1) * 2
        linear = (self.dma['dst_x'] << 14) | (((self.dma['dst_h'] << 8) | self.dma['dst_l']) & 0x3FFE)
        data = bytes(self.sd.input(0x57) for _ in range(count))
        self.dma_spi_reads += count
        position = 0
        while position < count:
            chunk = min(count - position, 0x4000 - ((linear + position) & 0x3FFF))
            self.model.write_block((linear + position) & 0x3FFFFF, data[position:position + chunk])
            position += chunk

    # --- память --------------------------------------------------------------------------------

    def read(self, address: int) -> int:
        address &= 0x3FFFFF
        if address < RAM_G_SIZE:
            return self.ram_g[address]
        if RAM_DL <= address < RAM_DL + RAM_DL_SIZE:
            return self.ram_dl[address - RAM_DL]
        if address == 0x302000:
            return 0x7C
        if REG_CMDB_SPACE <= address < REG_CMDB_SPACE + 4:
            space = 4092 - len(self.fifo)
            return (space >> (8 * (address - REG_CMDB_SPACE))) & 0xFF
        if REG_DLSWAP <= address < REG_DLSWAP + 4:
            return 0
        if REG_FRAMES <= address < REG_FRAMES + 4:
            return (self.frames >> (8 * (address - REG_FRAMES))) & 0xFF
        return self.registers.get(address, 0)

    def write(self, address: int, value: int) -> None:
        address &= 0x3FFFFF
        if address < RAM_G_SIZE:
            self.ram_g[address] = value
        elif RAM_DL <= address < RAM_DL + RAM_DL_SIZE:
            self.ram_dl[address - RAM_DL] = value
        elif address == REG_DLSWAP:
            if value:
                self.shown_dl = bytes(self.ram_dl)
                self.swaps += 1
                self.apply_handles()
        elif REG_CMDB_WRITE <= address < REG_CMDB_WRITE + 4:
            self.fifo.append(value)
            if len(self.fifo) % 4 == 0:
                self.process_fifo()
        elif RAM_G_SIZE <= address < RAM_DL:
            self.errors.append(f'запись вне RAM_G #{address:06X}')
        else:
            self.registers[address] = value

    def process_fifo(self) -> None:
        """Сопроцессор забирает данные CMD_INFLATE по мере поступления (как FT81X): очередь
        занимают только ещё не прочитанные байты, поэтому сжатый поток может быть длиннее 4 КБ."""
        while True:
            if self.inflate is not None:
                decompressor, pointer, fed = self.inflate
                if not self.fifo:
                    return
                chunk = bytes(self.fifo)
                self.fifo.clear()
                try:
                    data = decompressor.decompress(chunk)
                except zlib.error as error:
                    self.errors.append(f'CMD_INFLATE: {error}')
                    self.inflate = None
                    return
                if pointer + len(data) > RAM_G_SIZE:
                    self.errors.append(f'CMD_INFLATE за пределы RAM_G: #{pointer:06X}+{len(data)}')
                    data = data[:max(0, RAM_G_SIZE - pointer)]
                self.ram_g[pointer:pointer + len(data)] = data
                self.count_load('inflate_out', len(data))
                pointer += len(data)
                fed += len(chunk)
                if not decompressor.eof:
                    self.inflate = (decompressor, pointer, fed)
                    return
                rest = decompressor.unused_data
                used = fed - len(rest)
                padding = (-used) & 3
                self.fifo[:0] = rest[padding:]
                self.inflate = None
                self.inflates += 1
                continue
            if len(self.fifo) < 4:
                return
            word = struct.unpack_from('<I', self.fifo, 0)[0]
            if word in (0xFFFFFF1D, 0xFFFFFF1B):
                # CMD_MEMCPY (приёмник, источник, байт) и CMD_MEMSET (адрес, значение, байт) в RAM_G
                if len(self.fifo) < 16:
                    return
                first, second, count = struct.unpack_from('<III', self.fifo, 4)
                del self.fifo[:16]
                first &= 0x3FFFFF
                if first + count > RAM_G_SIZE or (word == 0xFFFFFF1D and (second & 0x3FFFFF) + count > RAM_G_SIZE):
                    self.errors.append(f'команда #{word:08X} за пределами RAM_G: #{first:06X}+{count}')
                    continue
                if word == 0xFFFFFF1D:
                    source = second & 0x3FFFFF
                    self.ram_g[first:first + count] = bytes(self.ram_g[source:source + count])
                    self.count_load('memcpy', count)
                    self.count_load('memcpy_cmds', 1)
                else:
                    self.ram_g[first:first + count] = bytes([second & 0xFF]) * count
                    self.count_load('memset', count)
                self.copies += 1
                continue
            if word != 0xFFFFFF22:
                self.errors.append(f'команда сопроцессора #{word:08X}')
                del self.fifo[:4]
                continue
            if len(self.fifo) < 8:
                return
            pointer = struct.unpack_from('<I', self.fifo, 4)[0] & 0x3FFFFF
            del self.fifo[:8]
            self.inflate = (zlib.decompressobj(), pointer, 0)

    # --- кадр ------------------------------------------------------------------------------------

    def words(self, dl: bytes | None = None) -> list[int]:
        dl = self.shown_dl if dl is None else dl
        result = []
        for offset in range(0, RAM_DL_SIZE, 4):
            word = struct.unpack_from('<I', dl, offset)[0]
            result.append(word)
            if word == 0:
                break
        return result

    def apply_handles(self) -> None:
        """Параметры handle показанного списка: FT812 исполняет каждый список, и BITMAP_SOURCE,
        BITMAP_LAYOUT, BITMAP_SIZE сохраняются для следующих (render вызывается не на каждом)."""
        handle = 0
        for word in self.words():
            if word == 0:
                break
            if word >> 30:
                continue
            opcode = word >> 24
            state = self.handles[handle]
            if opcode == 0x05:
                handle = word & 31
            elif opcode == 0x01:
                state['source'] = word & 0x3FFFFF
            elif opcode == 0x07:
                state['format'] = (word >> 19) & 31
                state['stride'] = (state['stride'] & ~1023) | ((word >> 9) & 1023)
                state['height'] = (state['height'] & ~511) | (word & 511)
            elif opcode == 0x28:
                state['stride'] = (state['stride'] & 1023) | (((word >> 2) & 3) << 10)
                state['height'] = (state['height'] & 511) | ((word & 3) << 9)
            elif opcode == 0x08:
                state['filter'] = (word >> 20) & 1
                state['wrapx'] = (word >> 19) & 1
                state['wrapy'] = (word >> 18) & 1
                state['width_px'] = (state['width_px'] & ~511) | ((word >> 9) & 511)
                state['height_px'] = (state['height_px'] & ~511) | (word & 511)
            elif opcode == 0x29:
                state['width_px'] = (state['width_px'] & 511) | (((word >> 2) & 3) << 9)
                state['height_px'] = (state['height_px'] & 511) | ((word & 3) << 9)

    def render(self) -> tuple[np.ndarray, dict]:
        """Кадр (768, 1024, 3) и счётчики: слов, вершин, ошибок разбора."""
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
        clear_color = (0, 0, 0)
        scissor = [0, 0, WIDTH, HEIGHT]
        handle = 0
        cell = 0
        palette = 0
        translate = [0, 0]
        vertex_shift = 4
        transform = [256, 0, 0, 0, 256, 0]
        primitive = 0
        stats = {'words': 0, 'vertices': 0, 'unknown': 0}
        ram_g = np.frombuffer(bytes(self.ram_g), dtype=np.uint8)
        dl_words = [struct.unpack_from('<I', self.shown_dl, offset)[0] for offset in range(0, RAM_DL_SIZE, 4)]
        pc = 0
        stack: list[int] = []
        while pc < len(dl_words):
            word = dl_words[pc]
            pc += 1
            stats['words'] += 1
            if stats['words'] > 20000:
                self.errors.append('display list: цикл CALL/JUMP')
                break
            if word == 0:
                break
            if word >> 24 == 0x1D:                   # CALL: номер команды
                if len(stack) >= 4:
                    self.errors.append('display list: глубина CALL больше 4')
                    break
                stack.append(pc)
                pc = word & 0xFFFF
                continue
            if word >> 24 == 0x1E:                   # JUMP
                pc = word & 0xFFFF
                continue
            if word >> 24 == 0x24:                   # RETURN
                if not stack:
                    self.errors.append('display list: RETURN без CALL')
                    break
                pc = stack.pop()
                continue
            kind = word >> 30
            if kind in (1, 2):
                if kind == 2:
                    x = ((word >> 21) & 511) * 16
                    y = ((word >> 12) & 511) * 16
                    draw_handle = (word >> 7) & 31
                    draw_cell = word & 127
                else:
                    x = ((word >> 15) & 0x7FFF)
                    y = word & 0x7FFF
                    x = (x - 0x8000 if x & 0x4000 else x) << (4 - vertex_shift) if vertex_shift <= 4 else 0
                    y = (y - 0x8000 if y & 0x4000 else y) << (4 - vertex_shift) if vertex_shift <= 4 else 0
                    draw_handle, draw_cell = handle, cell
                stats['vertices'] += 1
                if primitive != 1:
                    continue
                self.draw_bitmap(frame, ram_g, self.handles[draw_handle], draw_cell, palette,
                                 x + translate[0], y + translate[1], transform, scissor)
                continue
            opcode = word >> 24
            if opcode == 0x02:
                clear_color = ((word >> 16) & 255, (word >> 8) & 255, word & 255)
            elif opcode == 0x26:
                if word & 4:
                    x0, y0, w, h = scissor
                    frame[y0:y0 + h, x0:x0 + w] = clear_color
            elif opcode == 0x1B:
                scissor[0], scissor[1] = (word >> 11) & 2047, word & 2047
            elif opcode == 0x1C:
                scissor[2], scissor[3] = (word >> 12) & 4095, word & 4095
            elif opcode == 0x05:
                handle = word & 31
            elif opcode == 0x06:
                cell = word & 127
            elif opcode == 0x01:
                self.handles[handle]['source'] = word & 0x3FFFFF
            elif opcode == 0x07:
                state = self.handles[handle]
                state['format'] = (word >> 19) & 31
                state['stride'] = (state['stride'] & ~1023) | ((word >> 9) & 1023)
                state['height'] = (state['height'] & ~511) | (word & 511)
            elif opcode == 0x28:
                state = self.handles[handle]
                state['stride'] = (state['stride'] & 1023) | (((word >> 2) & 3) << 10)
                state['height'] = (state['height'] & 511) | ((word & 3) << 9)
            elif opcode == 0x08:
                state = self.handles[handle]
                state['filter'] = (word >> 20) & 1
                state['wrapx'] = (word >> 19) & 1
                state['wrapy'] = (word >> 18) & 1
                state['width_px'] = (state['width_px'] & ~511) | ((word >> 9) & 511)
                state['height_px'] = (state['height_px'] & ~511) | (word & 511)
            elif opcode == 0x29:
                state = self.handles[handle]
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
            elif opcode in (0x21, 0x04, 0x10, 0x0B):
                pass
            else:
                stats['unknown'] += 1
        return np.clip(frame + 0.5, 0, 255).astype(np.uint8), stats

    def draw_bitmap(self, frame, ram_g, state, cell, palette, vx16, vy16, transform, scissor) -> None:
        if state['format'] not in (PALETTED4444, ARGB4) or not state['stride'] or not state['height']:
            return
        if state['format'] == ARGB4:
            width, height = state['stride'] // 2, state['height']
            base = state['source'] + cell * state['stride'] * height
            raw = ram_g[base:base + width * height * 2]
            if raw.size != width * height * 2:
                return
            texels = raw.view('<u2').reshape(height, width)
            colors = None
        else:
            width, height = state['stride'], state['height']
            base = state['source'] + cell * width * height
            texels = ram_g[base:base + width * height]
            if texels.size != width * height:
                # Ячейка заходит за конец RAM_G (проход B последнего слота спрайтов: handle-псевдоним со
                # сдвигом источника): FT812 читает только выводимые строки, остальное — нули.
                if base >= RAM_G_SIZE:
                    return
                texels = np.concatenate([texels, np.zeros(width * height - texels.size, dtype=np.uint8)])
            texels = texels.reshape(height, width)
            colors = np.frombuffer(bytes(self.ram_g[palette:palette + 512]), dtype='<u2')
        size_x, size_y = state['width_px'], state['height_px']
        x0 = max((vx16 + 8) // 16 - 1, scissor[0], 0)
        y0 = max((vy16 + 8) // 16 - 1, scissor[1], 0)
        x1 = min((vx16 + size_x * 16) // 16 + 1, scissor[0] + scissor[2], WIDTH)
        y1 = min((vy16 + size_y * 16) // 16 + 1, scissor[1] + scissor[3], HEIGHT)
        if x0 >= x1 or y0 >= y1:
            return
        px = np.arange(x0, x1)
        py = np.arange(y0, y1)
        rel_x = px * 16 + self.sample_offset - vx16
        rel_y = py * 16 + self.sample_offset - vy16
        keep_x = (rel_x >= 0) & (rel_x < size_x * 16)
        keep_y = (rel_y >= 0) & (rel_y < size_y * 16)
        a, _b, c, _d, e, f = transform

        def fetch(u, v):
            """Тексели (строки v, столбцы u) → цвет 0…255 и альфа 0…1; REPEAT — по модулю, BORDER — за краем прозрачно."""
            inside_u = np.ones(u.shape, dtype=bool)
            inside_v = np.ones(v.shape, dtype=bool)
            if state['wrapx']:
                u = u % width
            else:
                inside_u = (u >= 0) & (u < width)
                u = np.clip(u, 0, width - 1)
            if state['wrapy']:
                v = v % height
            else:
                inside_v = (v >= 0) & (v < height)
                v = np.clip(v, 0, height - 1)
            index = texels[np.ix_(v, u)]
            argb = (colors[index] if colors is not None else index).astype(np.int32)
            alpha = ((argb >> 12) & 15).astype(np.float32)[..., None] * 17.0 / 255.0
            alpha *= np.outer(inside_v, inside_u)[..., None]
            rgb = np.stack([(argb >> 8) & 15, (argb >> 4) & 15, argb & 15], axis=-1).astype(np.float32) * 17.0
            return rgb, alpha

        if state['filter']:
            # BILINEAR: четыре соседних тексела (центры — со сдвигом на полтексела) смешиваются после палитры
            su = rel_x * a // 16 + c - 128
            sv = rel_y * e // 16 + f - 128
            if not keep_x.any() or not keep_y.any():
                return
            su, sv = su[keep_x], sv[keep_y]
            u0, v0 = su >> 8, sv >> 8
            fu = ((su & 255).astype(np.float32) / 256.0)[None, :, None]
            fv = ((sv & 255).astype(np.float32) / 256.0)[:, None, None]
            rgb00, alpha00 = fetch(u0, v0)
            rgb01, alpha01 = fetch(u0 + 1, v0)
            rgb10, alpha10 = fetch(u0, v0 + 1)
            rgb11, alpha11 = fetch(u0 + 1, v0 + 1)
            rgb = (rgb00 * (1 - fu) + rgb01 * fu) * (1 - fv) + (rgb10 * (1 - fu) + rgb11 * fu) * fv
            alpha = (alpha00 * (1 - fu) + alpha01 * fu) * (1 - fv) + (alpha10 * (1 - fu) + alpha11 * fu) * fv
        else:
            u = (rel_x * a // 16 + c) >> 8
            v = (rel_y * e // 16 + f) >> 8
            if not state['wrapx']:
                keep_x &= (u >= 0) & (u < width)
            if not state['wrapy']:
                keep_y &= (v >= 0) & (v < height)
            if not keep_x.any() or not keep_y.any():
                return
            rgb, alpha = fetch(u[keep_x], v[keep_y])
        region = frame[np.ix_(py[keep_y], px[keep_x])]
        frame[np.ix_(py[keep_y], px[keep_x])] = rgb * alpha + region * (1.0 - alpha)
