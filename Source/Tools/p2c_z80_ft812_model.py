"""Модель FT812 для проверки Z80-сборки p2c: SPI TS-Config, DMA RAM->SPI, RAM_G, RAM_DL,
очередь сопроцессора с CMD_INFLATE и разбор display list в команды вывода.

Команды кадра сравниваются с выводом CPython после тех же отсевов, что делает
адаптер (изображение вне экрана, сплошной чёрный глиф до первого вывода).
Изображение вершины определяется так же, как его выберет FT812: по источнику,
раскладке и ячейке текущего BITMAP_HANDLE берутся байты RAM_G, и их хэш ищется
среди записей каталога; размер вывода BITMAP_SIZE проверяется по масштабу 8/5.
"""
from __future__ import annotations

import hashlib
import struct
import zlib

RAM_G_SIZE = 1 << 20
RAM_DL = 0x300000
RAM_DL_SIZE = 0x2000
REG_ID = 0x302000
REG_DLSWAP = 0x302054
REG_CMDB_SPACE = 0x302574
REG_CMDB_WRITE = 0x302578


class FT812Model:
    def __init__(self, machine) -> None:
        self.machine = machine
        self.ram_g = bytearray(RAM_G_SIZE)
        self.ram_dl = bytearray(RAM_DL_SIZE)
        self.shown_dl = bytes(RAM_DL_SIZE)
        self.swaps = 0
        self.selected = False
        self.phase = 0
        self.writing = False
        self.address = 0
        self.read_state = None
        self.fifo = bytearray()
        self.dma = {'src_l': 0, 'src_h': 0, 'src_x': 0, 'len': 0, 'num': 0}
        self.uploads: dict[int, str] = {}          # адрес RAM_G -> хэш распакованных пикселей
        self.errors: list[str] = []
        self.chain_output = machine.output
        machine.cpu.set_output_callback(self.output)
        machine.cpu.set_input_callback(self.input)

    # --- порты ------------------------------------------------------------------------

    def output(self, address: int, value: int) -> None:
        low = address & 0xFF
        if low == 0x77:
            self.selected = value == 0x07
            self.phase = 0
            self.read_state = None
            return
        if low == 0x57:
            self.spi_byte(value)
            return
        if low == 0xAF:
            register = address >> 8
            names = {0x1A: 'src_l', 0x1B: 'src_h', 0x1C: 'src_x', 0x26: 'len', 0x28: 'num'}
            if register in names:
                self.dma[names[register]] = value
                return
            if register == 0x27:
                self.dma_start(value)
                return
        self.chain_output(address, value)

    def input(self, address: int) -> int:
        low = address & 0xFF
        if low == 0x57:
            # Чтение TSLib: пустой байт после адреса, пустое IN, затем данные по порядку.
            if self.read_state == 'dummy':
                self.read_state = 'data'
                return 0
            if self.read_state == 'data':
                value = self.read(self.address)
                self.address += 1
                return value
            return 0xFF
        if low == 0xAF and (address >> 8) == 0x27:
            return 0                                 # DMA завершается мгновенно
        return 0xFF                                  # клавиатура, Kempston: ничего не нажато

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
            return
        if self.writing:
            self.write(self.address, value)
            self.address += 1
        else:
            self.read_state = 'dummy'

    def dma_start(self, mode: int) -> None:
        if mode != 0x82:
            self.errors.append(f'режим DMA #{mode:02X}')
            return
        if not (self.selected and self.writing and self.phase >= 3):
            self.errors.append('DMA RAM->SPI без открытой записи SPI')
            return
        count = (self.dma['num'] + 1) * (self.dma['len'] + 1) * 2
        page = self.dma['src_x']
        # Передача RAM->SPI идёт словами с чётного адреса: у нечётного младший бит отбрасывается.
        offset = ((self.dma['src_h'] << 8) | self.dma['src_l']) & 0x3FFE
        position = 0
        while position < count:
            data = self.machine.page_bytes(page)
            chunk = min(count - position, 0x4000 - offset)
            for byte in data[offset:offset + chunk]:
                self.write(self.address, byte)
                self.address += 1
            position += chunk
            page += 1
            offset = 0

    # --- память FT812 -------------------------------------------------------------------

    def read(self, address: int) -> int:
        address &= 0x3FFFFF
        if address < RAM_G_SIZE:
            return self.ram_g[address]
        if RAM_DL <= address < RAM_DL + RAM_DL_SIZE:
            return self.ram_dl[address - RAM_DL]
        if address == REG_ID:
            return 0x7C
        if address == REG_DLSWAP:
            return 0
        if address in (REG_CMDB_SPACE, REG_CMDB_SPACE + 1):
            return (4092 >> (8 * (address - REG_CMDB_SPACE))) & 0xFF
        return 0

    def write(self, address: int, value: int) -> None:
        address &= 0x3FFFFF
        if RAM_G_SIZE <= address < RAM_DL:
            self.errors.append(f'запись вне RAM_G #{address:06X}')
        if address < RAM_G_SIZE:
            self.ram_g[address] = value
        elif RAM_DL <= address < RAM_DL + RAM_DL_SIZE:
            self.ram_dl[address - RAM_DL] = value
        elif address == REG_DLSWAP:
            if value:
                self.shown_dl = bytes(self.ram_dl)
                self.swaps += 1
        elif REG_CMDB_WRITE <= address < REG_CMDB_WRITE + 0x1000:
            # Байты записи в REG_CMDB_WRITE добавляются в очередь сопроцессора.
            self.fifo.append(value)
            if len(self.fifo) % 4 == 0:
                self.process_fifo()

    def process_fifo(self) -> None:
        while len(self.fifo) >= 4:
            word = struct.unpack_from('<I', self.fifo, 0)[0]
            if word != 0xFFFFFF22:
                self.errors.append(f'команда сопроцессора #{word:08X}')
                del self.fifo[:4]
                continue
            if len(self.fifo) < 8:
                return
            pointer = struct.unpack_from('<I', self.fifo, 4)[0] & 0x3FFFFF
            decompressor = zlib.decompressobj()
            try:
                data = decompressor.decompress(bytes(self.fifo[8:]))
            except zlib.error as error:
                self.errors.append(f'CMD_INFLATE: {error}')
                self.fifo.clear()
                return
            if not decompressor.eof:
                return
            used = len(self.fifo) - 8 - len(decompressor.unused_data)
            total = 8 + ((used + 3) & ~3)
            if len(self.fifo) < total:
                return
            if pointer + len(data) > RAM_G_SIZE:
                self.errors.append(f'CMD_INFLATE за пределы RAM_G: #{pointer:06X}+{len(data)}')
                data = data[:max(0, RAM_G_SIZE - pointer)]
            self.ram_g[pointer:pointer + len(data)] = data
            self.uploads[pointer] = hashlib.sha1(data).hexdigest()
            del self.fifo[:total]

    # --- разбор кадра ---------------------------------------------------------------------

    def display_bitmaps(self) -> list:
        """Вершины показанного display list: состояние BITMAP_HANDLE, ячейка и координаты в 1/8 пикселя."""
        handles: dict[int, dict] = {}
        handle = 0
        cell = 0
        translate_x = 0
        translate_y = 0
        result = []
        for offset in range(0, RAM_DL_SIZE, 4):
            word = struct.unpack_from('<I', self.shown_dl, offset)[0]
            if word == 0:
                break
            state = handles.setdefault(handle, {'source': 0, 'format': 0, 'stride': 0, 'height': 0,
                                                'width_px': 0, 'height_px': 0})
            if (word >> 30) == 1:
                x_units = (word >> 15) & 0x7FFF
                y_units = word & 0x7FFF
                result.append((dict(state), handle, cell, x_units, y_units, translate_x, translate_y))
                continue
            opcode = word >> 24
            if opcode == 0x05:
                handle = word & 0x1F
            elif opcode == 0x06:
                cell = word & 0x7F
            elif opcode == 0x01:
                state['source'] = word & 0x3FFFFF
            elif opcode == 0x07:
                state['format'] = (word >> 19) & 0x1F
                state['stride'] = (state['stride'] & ~1023) | ((word >> 9) & 1023)
                state['height'] = (state['height'] & ~511) | (word & 511)
            elif opcode == 0x28:
                state['stride'] = (state['stride'] & 1023) | (((word >> 2) & 3) << 10)
                state['height'] = (state['height'] & 511) | ((word & 3) << 9)
            elif opcode == 0x08:
                state['width_px'] = (state['width_px'] & ~511) | ((word >> 9) & 511)
                state['height_px'] = (state['height_px'] & ~511) | (word & 511)
            elif opcode == 0x29:
                state['width_px'] = (state['width_px'] & 511) | (((word >> 2) & 3) << 9)
                state['height_px'] = (state['height_px'] & 511) | ((word & 3) << 9)
            elif opcode == 0x2B:
                translate_x = word & 0x1FFFF
                translate_x -= 0x20000 if translate_x & 0x10000 else 0
            elif opcode == 0x2C:
                translate_y = word & 0x1FFFF
                translate_y -= 0x20000 if translate_y & 0x10000 else 0
        return result

    def decode(self, defines: dict, entry_by_pixels: dict[str, int], inverse_x: dict, inverse_y: dict) -> list:
        """Команды вывода показанного display list: (запись каталога, логический X, Y)."""
        del defines
        blits = []
        for state, handle, cell, x_units, y_units, _tx, _ty in self.display_bitmaps():
            stride = state['stride']
            height = state['height']
            address = state['source'] + cell * stride * height
            data = bytes(self.ram_g[address:address + stride * height])
            entry = entry_by_pixels.get(hashlib.sha1(data).hexdigest()) if stride and height else None
            width = stride // 2
            if entry is None:
                entry = ('нет изображения', handle, cell, f'#{address:06X}', width, height)
            elif state['format'] != 6 or (state['width_px'], state['height_px']) != (
                    (width * 8 + 4) // 5, (height * 8 + 4) // 5):
                entry = ('раскладка', entry, state['format'], state['width_px'], state['height_px'])
            blits.append((entry, inverse_x.get(x_units, ('x', x_units)), inverse_y.get(y_units, ('y', y_units))))
        return blits

    def render(self) -> bytes:
        """Кадр 1024x768 RGB из показанного display list: NEAREST с матрицей A=E=160, смешение SRC_ALPHA."""
        import numpy
        frame = numpy.zeros((768, 1024, 3), dtype=numpy.float32)
        for state, _handle, cell, x_units, y_units, translate_x, translate_y in self.display_bitmaps():
            stride = state['stride']
            height = state['height']
            if state['format'] != 6 or not stride or not height:
                continue
            width = stride // 2
            address = state['source'] + cell * stride * height
            raw = numpy.frombuffer(bytes(self.ram_g[address:address + stride * height]), dtype='<u2')
            if raw.size != width * height:
                continue
            texels = raw.reshape(height, width)
            left = x_units // 8 + translate_x // 16          # VERTEX_TRANSLATE — в 1/16 пикселя
            top = y_units // 8 + translate_y // 16
            columns = numpy.arange(state['width_px'])
            rows = numpy.arange(state['height_px'])
            u = (columns * 160) >> 8
            v = (rows * 160) >> 8
            screen_x = left + columns
            screen_y = top + rows
            keep_x = (screen_x >= 0) & (screen_x < 1024) & (u < width)
            keep_y = (screen_y >= 0) & (screen_y < 768) & (v < height)
            if not keep_x.any() or not keep_y.any():
                continue
            patch = texels[numpy.ix_(v[keep_y], u[keep_x])].astype(numpy.uint32)
            alpha = ((patch >> 12) & 15).astype(numpy.float32)[..., None] / 15.0
            color = numpy.stack([(patch >> 8) & 15, (patch >> 4) & 15, patch & 15],
                                axis=-1).astype(numpy.float32) * 17.0
            index = numpy.ix_(screen_y[keep_y], screen_x[keep_x])
            frame[index] = color * alpha + frame[index] * (1.0 - alpha)
        return numpy.clip(frame + 0.5, 0, 255).astype(numpy.uint8).tobytes()


def coordinate_inverse() -> tuple[dict, dict]:
    inverse_x = {((x * 64) // 5 + 4096) & 0x7FFF: x for x in range(-320, 640)}
    inverse_y = {((y * 64) // 5 + 4096) & 0x7FFF: y for y in range(-320, 480)}
    return inverse_x, inverse_y


def expected_blits(commands: list, catalog: dict) -> list:
    """Вывод CPython в записях каталога с отсевами адаптера FT812."""
    sizes = catalog['sizes']
    black = catalog['solid_black']
    image_entry = {int(key): value for key, value in catalog['image_entry'].items()}
    cell_entry = catalog['cell_entry']
    typed = catalog['typed_banks']
    glyphs = catalog['text_glyphs']
    advance = catalog['text_advance']
    result = []
    drawn = False

    def draw(entry: int, x: int, y: int) -> None:
        nonlocal drawn
        if entry == 0:
            result.append(('нет записи', x, y))
            return
        width, height = sizes[entry]
        if x >= 640 or y >= 480 or x + width <= 0 or y + height <= 0 or x < -320 or y < -320:
            return
        if black[entry] and not drawn:
            return
        result.append((entry, x, y))
        drawn = True

    for image, x, y in commands:
        if image == 0xFFFFFFFF:
            continue
        if isinstance(image, tuple):
            _kind, text, _antialias, color = image
            cursor = x
            for character in text:
                code = ord(character)
                if 32 <= code < 128:
                    entry = glyphs[((code - 32) << 1) | (1 if color == (0, 0, 0) else 0)]
                    if entry:
                        draw(entry, cursor, y)
                    cursor += advance[code - 32]
            continue
        if image & 0x80000000:
            is_typed = (image >> 30) & 1
            bank_value = (image >> 16) & 0xFF
            code = (image >> 2) & 0x0FFF
            flips = image & 3
            bank = typed[bank_value] if is_typed else bank_value
            draw(cell_entry.get(f'{bank},{flips},{code}', 0), x, y)
            continue
        draw(image_entry.get(image, 0), x, y)
    return result
