"""Проверка загрузчика данных уровней на модели: Z80 с окнами TS-Config, драйвер FAT32 и SD-карта.

SD-карта — модель проекта драйвера (E:\\zx\\FAT32 Driver\\tests: Card и Z-Controller, сверенные с
Unreal) поверх образа Build/V30Z80/rtype_sd.img, записи в образ не сохраняются. Загрузчик
вызывается так же, как из хоста видеоадаптера: окна W0 — резидент машины, W1 — страница хоста,
W2 — страница загрузчика, W3 — страница хоста, стек — в резиденте. Проверяется открытие файла
(путь GAMES\\R-Type VDAC2\\RTYPELVL.PAC, таблица кусков) и выборка ячеек: признаки, длина и
поток zlib в слотах кэша секторов (куски LOADER_PIECES) совпадают с файлом; печатаются такты на ячейку.
"""
from __future__ import annotations

import argparse
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'Build' / 'V30Z80'
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
sys.path.insert(0, r'E:\zx\FAT32 Driver\tests')

from p2c_z80_check import TSConfModel  # noqa: E402
from test_sdzc import Card, ZController  # noqa: E402

RETURN = 0xC100                        # точка возврата в странице «хоста»
HOST_STACK = 0x3F00


class ImageDisk:
    """Образ SD: чтение из файла, записи — в памяти."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.written: dict[int, bytes] = {}

    def read(self, lba: int) -> bytes:
        return self.written.get(lba) or self.data[lba * 512:(lba + 1) * 512].ljust(512, b'\0')

    def write(self, lba: int, data: bytes) -> None:
        self.written[lba] = bytes(data)


def sd_controller(image: Path):
    """Z-Controller с SD-картой над образом (для моделей SPI проверок): (контроллер, карта)."""
    card = Card(ImageDisk(image.read_bytes()), 'sdsc')
    return ZController(card), card


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cells', type=int, default=300)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = json.loads((BUILD / 'rtype_loader.json').read_text(encoding='utf-8'))
    symbols = report['symbols']
    pac = (BUILD / 'RTYPELVL.PAC').read_bytes()
    pages = {page: (BUILD / 'pages' / f'page_{page:02x}.bin').read_bytes() for page in report['pages']}
    pages[0x08] = bytes(0x4000)
    pages[0x0C] = bytes(0x4000)
    pages[0xC0] = bytes(0x4000)
    model = TSConfModel(pages, set(pages), 3)
    model.map_all([0x08, 0xC0, report['loader_page'], 0x0C])
    card = Card(ImageDisk((BUILD / 'rtype_sd.img').read_bytes()), 'sdsc')
    zc = ZController(card)
    cpu = model.cpu

    dma_target = {0x1D: 0, 0x1E: 0, 0x1F: 0, 0x26: 0, 0x28: 0}

    def output(port: int, value: int) -> None:
        if port & 0xFF in (0x57, 0x77):
            zc.output(port, value)
            return
        if port & 0xFF == 0xAF and port >> 8 in dma_target:
            dma_target[port >> 8] = value
        if port == 0x27AF and value == 0x02:
            # DMA SPI→RAM (vdac2p_sdzc.asm, SD_READ_DMA): байты SD — как IN из #57 — в страницу приёмника
            count = (dma_target[0x28] + 1) * (dma_target[0x26] + 1) * 2
            linear = (dma_target[0x1F] << 14) | (((dma_target[0x1E] << 8) | dma_target[0x1D]) & 0x3FFE)
            model.write_block(linear, bytes(zc.input(0x57) for _ in range(count)))
            return
        model.output(port, value)

    def port_input(port: int) -> int:
        if port & 0xFF == 0x57:
            return zc.input(port)
        return model.input(port)

    cpu.set_output_callback(output)
    cpu.set_input_callback(port_input)
    cpu.set_breakpoint(RETURN)

    def call(entry: str, **registers) -> int:
        model.memory[symbols['LOADER_HOST_W1']] = 0xC0
        cpu.sp = HOST_STACK - 2
        model.memory[cpu.sp] = RETURN & 0xFF
        model.memory[cpu.sp + 1] = RETURN >> 8
        for name, value in registers.items():
            setattr(cpu, name, value)
        cpu.pc = symbols[entry]
        spent = 0
        while True:
            cpu.ticks_to_stop = 50_000_000
            cpu.run()
            spent += 50_000_000 - int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            if cpu.pc == RETURN:
                break
            if spent > 2_000_000_000:
                raise SystemExit(f'{entry}: нет возврата, PC #{cpu.pc:04X}, окна {model.windows}')
        if model.windows != [0x08, 0xC0, report['loader_page'], 0x0C]:
            raise SystemExit(f'{entry}: окна хоста не восстановлены: {model.windows}')
        if cpu.sp != HOST_STACK:
            raise SystemExit(f'{entry}: стек хоста #{cpu.sp:04X}')
        return spent

    ticks = call('LOADER_INIT')
    print(f'открытие: A = #{cpu.a:02X}, тактов {ticks}, чтений SD {sum(1 for c in card.commands if c[0] == 17)}')
    if cpu.a != 0:
        return 1
    rng = random.Random(args.seed)
    index_sector = struct.unpack_from('<I', pac, 12)[0]
    cells = []
    for number in range(args.cells):
        set_number = rng.randrange(3)
        palette = rng.randrange(16)
        code = rng.randrange(4096) if number % 3 else (number * 7) % 4096
        cells.append((set_number, palette, code))
    # Ряд подряд идущих кодов спрайтов одной палитры (как кадры анимации) дважды: второй проход — из кэша секторов.
    row = [(2, 0, 0x100 + index) for index in range(64)]
    sequence = ([('случайные', cell) for cell in cells] + [('ряд спрайтов', cell) for cell in row] +
                [('ряд спрайтов повторно', cell) for cell in row])
    stats: dict[str, dict[str, int]] = {}

    def sd_reads() -> int:
        return sum(1 for command in card.commands if command[0] == 17)

    for label, (set_number, palette, code) in sequence:
        entry = stats.setdefault(label, {'cells': 0, 'ticks': 0, 'checked': 0, 'empty': 0, 'reads': 0})
        reads = sd_reads()
        spent = call('LOADER_CELL', a=set_number * 16 + palette, hl=code)
        entry['cells'] += 1
        entry['ticks'] += spent
        entry['reads'] += sd_reads() - reads
        position = (index_sector + (set_number * 16 + palette) * 64) * 512 + code * 8
        first, offset, length = struct.unpack_from('<IHH', pac, position)
        flags_expected = (offset >> 8) & 0xC0 if first else 0
        if cpu.f & 1:
            raise SystemExit(f'ячейка {set_number} {palette} {code}: ошибка чтения')
        if cpu.a != flags_expected:
            raise SystemExit(f'ячейка {set_number} {palette} {code}: признаки #{cpu.a:02X}, в файле #{flags_expected:02X}')
        if not first:
            entry['empty'] += 1
            continue
        within = offset & 0x1FF
        if cpu.de != within or cpu.bc != length:
            raise SystemExit(f'ячейка {set_number} {palette} {code}: DE #{cpu.de:04X} BC {cpu.bc}, в файле {within} {length}')
        # Поток — в слотах кэша секторов: куски LOADER_PIECES (страница, старший байт смещения слота) по секторам подряд.
        pieces = model.page_bytes(report['loader_page'])[symbols['LOADER_PIECES'] - 0x8000:]
        stream = bytearray()
        for index in range((within + length + 511) >> 9):
            sector = first + index
            page, high = pieces[index * 2], pieces[index * 2 + 1]
            cache_pages = report['cache_pages']
            # Слот куска: его метка — этот сектор, набор слота (по 4 слота) — сектор mod числа наборов.
            slot = cache_pages.index(page) * 32 + high // 2 if page in cache_pages and high % 2 == 0 else -1
            loader_page = model.page_bytes(report['loader_page'])
            tags = symbols['CacheTags'] - 0x8000
            tag = loader_page[tags + slot * 2] | loader_page[tags + slot * 2 + 1] << 8 if slot >= 0 else -1
            if tag != sector or slot // 4 != sector % (len(cache_pages) * 8):
                raise SystemExit(f'ячейка {set_number} {palette} {code}: кусок {index} — страница #{page:02X} '
                                 f'смещение #{high:02X}00, сектор {sector} не в своём слоте (метка {tag})')
            data = model.page_bytes(page)[high * 256:high * 256 + 512]
            stream += data[within:] if index == 0 else data
        start = first * 512 + within
        if stream[:length] != pac[start:start + length]:
            raise SystemExit(f'ячейка {set_number} {palette} {code}: поток в кэше секторов не совпал с файлом')
        entry['checked'] += 1
    for label, entry in stats.items():
        print(f'{label}: ячеек {entry["cells"]}, сверено {entry["checked"]}, пустых {entry["empty"]}, '
              f'в среднем тактов {entry["ticks"] // entry["cells"]}, чтений SD {entry["reads"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
