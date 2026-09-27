"""Сборка транслированной программы app.main для Z80 (TS-Config): C из p2c, SDCC, страницы, SPG.

Порядок как у сверки на ПК: снимок объектов app.main, анализ от корней
(первичная отрисовка титула и App.frame), затем образ начального состояния в
раскладке SDCC, банки кода и резидент. Раскладка окон:
  #0000 страница RESIDENT — резидентный код (рантайм, платформа, адаптер, библиотека SDCC),
        _DATA, часть объектов снимка, стек #3400–#3FFF;
  #4000 страница DATA1, #8000 страница DATA2 — объекты снимка и куча;
  #C000 — банк кода, на время доступа — страница данных.
Крупные массивы без ссылок лежат на логических страницах данных; одинаковые
неизменяемые страницы делят одну физическую (таблица p2c_page_map).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import p2c_app  # noqa: E402
from p2c.cgen import CModule  # noqa: E402
from p2c.cgen_z80 import Z80Module, listing_sizes  # noqa: E402
from p2c.z80data import PAGE_SIZE, Z80Image  # noqa: E402

BUILD = ROOT / 'Build' / 'P2cZ80'
C_DIR = ROOT / 'Source' / 'C' / 'p2c'
SDCC = Path('E:/zx/sdcc/bin/sdcc.exe')
SDAS = SDCC.with_name('sdasz80.exe')
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
SPGBLD = Path('E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe')
PAGE_BOOT = 0x05
PAGE_RESIDENT = 0x08
PAGE_DATA1 = 0x09
PAGE_DATA2 = 0x0A
BANK_PAGES = list(range(0x10, 0x2F))
COLD_PAGE = 0x2F
PHYSICAL_DATA_FIRST = 0x30
LOGICAL_DATA_FIRST = 1
POOL_PAGES = 8
LOG_PAGE = 0xFE
LOG_PAGE2 = 0xFF
LAST_FREE_PAGE = 0xFD
STACK_TOP = 0x4000
STACK_BOTTOM = 0x3700
# Буфер display list адаптера FT812 перед стеком: DMA RAM->SPI начинает передачу с чётного
# адреса, поэтому у буфера постоянный чётный адрес вне _DATA.
DL_BUFFER = 0x3600


def run(command: list, cwd: Path = BUILD) -> str:
    env = os.environ.copy()
    env['PATH'] = str(SDCC.parent) + os.pathsep + env['PATH']
    result = subprocess.run([str(item) for item in command], cwd=cwd, env=env, capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(f'{Path(str(command[0])).name}: код {result.returncode}\n{output[-6000:]}')
    return output


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        if not path.exists() or path.read_text(encoding='utf-8') != data:
            path.write_text(data, encoding='utf-8', newline='\n')
    else:
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)


def area_sizes(rel: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for line in rel.read_text(encoding='latin1').splitlines():
        match = re.match(r'^A (\S+) size ([0-9A-Fa-f]+)', line)
        if match:
            sizes[match[1]] = sizes.get(match[1], 0) + int(match[2], 16)
    return sizes


def sdcc_compile(source: Path, target: Path, segment: str | None, defines: tuple = (),
                 optimize: str = '--opt-code-speed') -> Path:
    command = [SDCC, '-mz80', '--std-c11', optimize, '--no-c-code-in-asm',
               '-I', BUILD, '-I', C_DIR / 'z80', '-I', C_DIR, *[f'-D{item}' for item in defines]]
    if segment:
        command += ['--codeseg', segment, '--constseg', segment]
    command += ['-c', source, '-o', target]
    output = run(command)
    errors = [line for line in output.splitlines() if ' error ' in line.lower() or 'error:' in line.lower()]
    if errors:
        raise RuntimeError('\n'.join(errors[:20]))
    return target


def parse_ihx(path: Path) -> dict[int, int]:
    """Байты по 24-битным адресам (записи расширенного адреса 04)."""
    memory: dict[int, int] = {}
    upper = 0
    for line in path.read_text(encoding='latin1').splitlines():
        if not line.startswith(':'):
            continue
        data = bytes.fromhex(line[1:])
        count, address, kind = data[0], (data[1] << 8) | data[2], data[3]
        payload = data[4:4 + count]
        if kind == 0:
            for offset, byte in enumerate(payload):
                memory[(upper << 16) | (address + offset)] = byte
        elif kind == 4:
            upper = (payload[0] << 8) | payload[1]
        elif kind == 1:
            break
    return memory


def map_symbols(map_text: str) -> dict[str, int]:
    symbols = {}
    for address, name in re.findall(r'^\s+([0-9A-Fa-f]{8})\s+(\S+)', map_text, re.M):
        symbols[name] = int(address, 16)
    return symbols


def text_width_table(font) -> tuple[bytes, int]:
    """Ширины поверхностей font.render('DIST XXXX') по значению, по полбайта (адаптер отладочной строки)."""
    import pygame
    widths = [pygame.font.Font.render(font, f'DIST {value:04X}', False, (255, 255, 255)).get_width()
              for value in range(65536)]
    base = min(widths)
    if max(widths) - base > 15:
        raise RuntimeError('ширины отладочной строки не помещаются в полбайта')
    packed = bytearray(32768)
    for value, width in enumerate(widths):
        nibble = width - base
        packed[value >> 1] |= nibble << 4 if value & 1 else nibble
    return bytes(packed), base


def image_for(compiler, module, image_id, roots, data_size: int, ranges=None) -> Z80Image:
    image = Z80Image(compiler, module.r, module.layout, image_id,
                     ranges or [(0x4000 + data_size, 0xC000)], LOGICAL_DATA_FIRST)
    image.build(roots)
    return image


def prepare(app):
    """Анализ, генерация функций и нумерация изображений — общие для сборки и модели."""
    compiler, entry_list = p2c_app.analyze(app, ['frame'])
    image_ids: dict[int, int] = {}
    alive = []

    def image_id(surface) -> int:
        if id(surface) not in image_ids:
            image_ids[id(surface)] = len(image_ids) + 1
            alive.append(surface)
        return image_ids[id(surface)]

    roots = {'app': app, 'app_title': app.title}
    module = CModule(compiler, image_id, roots, entry_list)
    module.emit_functions()
    module.collect_value_types()
    return compiler, module, image_id, image_ids, alive, roots, entry_list


def compile_banks(z80, jobs: int, started: float, changed: set[str]) -> dict[int, Path]:
    objects = {}
    pending = []
    # Банки зависят и от общих заголовков платформы и рантайма.
    headers = max(path.stat().st_mtime for path in (C_DIR / 'z80' / 'p2c_platform.h', C_DIR / 'p2c_runtime.h',
                                                    BUILD / 'p2c_z80_config.h', BUILD / 'p2c_z80_program.h'))
    for bank in z80.banks:
        source = BUILD / f'bank_{bank.page:02x}.c'
        target = BUILD / f'bank_{bank.page:02x}.rel'
        objects[bank.page] = target
        if (source.name in changed or not target.is_file() or
                target.stat().st_mtime < max(source.stat().st_mtime, headers)):
            pending.append((bank, source, target))
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(sdcc_compile, source, target, f'BANK{bank.page}'): bank
                   for bank, source, target in pending}
        for future in concurrent.futures.as_completed(futures):
            future.result()
            print(f'банк #{futures[future].page:02X} собран, {time.perf_counter() - started:.0f} с', flush=True)
    return objects


def measured_sizes(z80, linked: dict[str, int]) -> dict[str, int]:
    sizes = {}
    for bank in z80.banks:
        listing = BUILD / f'bank_{bank.page:02x}.lst'
        if listing.is_file():
            sizes.update(listing_sizes(listing.read_text(encoding='latin1'), linked.get(f'l__BANK{bank.page}')))
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--adapter', default='record', choices=('record', 'ft812'),
                        help='record — журнал для модели проверки; ft812 — вывод VDAC2 и SPG')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    BUILD.mkdir(parents=True, exist_ok=True)

    app, _sound = p2c_app.build_snapshot()
    compiler, module, image_id, image_ids, alive, roots, entry_list = prepare(app)

    from rtype_port.enemies import RESOURCE_HQ
    typed_types = [resource_type for resource_type in range(256)
                   if (RESOURCE_HQ / f'RTYPE_SPRITES_TYPE{resource_type:02X}_HQ_ARGB4444.bin').is_file()]
    typed_bits = [0] * 32
    for resource_type in typed_types:
        typed_bits[resource_type >> 3] |= 1 << (resource_type & 7)
    width_cache = BUILD / 'text_widths.bin'
    if width_cache.is_file():
        cached = width_cache.read_bytes()
        width_base, widths = cached[0], cached[1:]
    else:
        widths, width_base = text_width_table(app.prepared_game.debug_distance_font)
        write(width_cache, bytes([width_base]) + widths)

    # Страницы: данные снимка (логические -> физические), пул буферов, ширины текста, каталог FT812.
    probe = image_for(compiler, module, image_id, roots, 0)
    page_map, data_content = probe.physical_pages(PHYSICAL_DATA_FIRST)
    next_physical = PHYSICAL_DATA_FIRST + len(data_content)
    pool_logical = probe.next_page
    if pool_logical + POOL_PAGES > 0x100:
        raise RuntimeError('логические страницы пула не помещаются')
    for index in range(POOL_PAGES):
        page_map[pool_logical + index] = next_physical + index
    next_physical += POOL_PAGES
    width_page = next_physical
    next_physical += 2
    pages: dict[int, bytes] = {}
    catalog_lines: list[str] = []
    catalog_tables = ''
    catalog_cold_tables = ''
    catalog_model = None
    if args.adapter == 'ft812':
        import p2c_z80_catalog
        surfaces = {number: alive[number - 1] for number in range(1, len(alive) + 1)}
        catalog = p2c_z80_catalog.build_catalog(surfaces, BUILD / 'sprite_cells.json',
                                                app.prepared_game.debug_distance_font, next_physical, typed_types)
        pages.update(catalog.pages)
        next_physical = catalog.defines['P2C_FT_LAST_PAGE'] + 1
        catalog_lines = p2c_z80_catalog.config_lines(catalog)
        catalog_tables, catalog_cold_tables = p2c_z80_catalog.tables_source(catalog)
        catalog_model = p2c_z80_catalog.model_description(catalog)
        print(f'каталог: записей {len(catalog.entries)}, изображений {len(catalog.image_entry)}, '
              f'ячеек {len(catalog.cell_entry)}, страниц {catalog.defines["P2C_FT_LAST_PAGE"] - catalog.defines["P2C_FT_ENTRY_PAGE"] + 1}',
              flush=True)
    if next_physical - 1 > LAST_FREE_PAGE:
        raise RuntimeError(f'физических страниц не хватает: последняя #{next_physical - 1:02X}')
    config = '\n'.join([
        '/* Сгенерировано p2c_z80.py: страницы сборки. */',
        '#ifndef P2C_Z80_CONFIG_H', '#define P2C_Z80_CONFIG_H', '#include <stdint.h>',
        f'#define P2C_Z80_PAGE_RESIDENT 0x{PAGE_RESIDENT:02X}u',
        f'#define P2C_Z80_DL_BUFFER 0x{DL_BUFFER:04X}u',
        f'#define P2C_Z80_POOL_FIRST 0x{pool_logical:02X}u',
        f'#define P2C_Z80_POOL_COUNT {POOL_PAGES}u',
        f'#define P2C_Z80_LOG_PAGE 0x{LOG_PAGE:02X}u',
        f'#define P2C_Z80_LOG_PAGE2 0x{LOG_PAGE2:02X}u',
        f'#define P2C_Z80_TEXT_WIDTH_PAGE 0x{width_page:02X}u',
        f'#define P2C_Z80_TEXT_WIDTH_BASE {width_base}',
        '#define P2C_Z80_TEXT_HEIGHT 15',
        'extern const uint8_t p2c_z80_typed_banks[32];',
        'extern const uint8_t p2c_page_map[256];',
        *catalog_lines,
        '#endif', ''])
    write(BUILD / 'p2c_z80_config.h', config)
    map_values = [page_map.get(index, 0) for index in range(256)]
    tables_c = BUILD / 'p2c_z80_tables.c'
    write(tables_c, '/* Сгенерировано p2c_z80.py: таблицы страниц и адаптеров. */\n#include <stdint.h>\n'
          'const uint8_t p2c_z80_typed_banks[32] = { ' + ', '.join(map(str, typed_bits)) + ' };\n'
          'const uint8_t p2c_page_map[256] = { ' + ', '.join(map(str, map_values)) + ' };\n' + catalog_tables)

    adapter = C_DIR / 'z80' / ('p2c_z80_record.c' if args.adapter == 'record' else 'p2c_z80_ft812.c')
    resident = [
        sdcc_compile(C_DIR / 'p2c_runtime.c', BUILD / 'runtime_hot.rel', None, ('P2C_SPLIT_HOT',), '--opt-code-size'),
        sdcc_compile(C_DIR / 'z80' / 'p2c_z80.c', BUILD / 'z80_hot.rel', None, ('P2C_SPLIT_HOT',), '--opt-code-size'),
        sdcc_compile(C_DIR / 'z80' / 'p2c_z80_main.c', BUILD / 'z80_main.rel', None, (), '--opt-code-size'),
        sdcc_compile(adapter, BUILD / 'adapter.rel', None, (), '--opt-code-size'),
        sdcc_compile(tables_c, BUILD / 'tables.rel', None, (), '--opt-code-size'),
    ]
    run([SDAS, '-plosgff', '-o', BUILD / 'p2c_z80_access.rel', C_DIR / 'z80' / 'p2c_z80_access.s'])
    resident.append(BUILD / 'p2c_z80_access.rel')
    cold = [
        sdcc_compile(C_DIR / 'p2c_runtime.c', BUILD / 'runtime_cold.rel', f'BANK{COLD_PAGE}', ('P2C_SPLIT_COLD',),
                     '--opt-code-size'),
        sdcc_compile(C_DIR / 'z80' / 'p2c_z80.c', BUILD / 'z80_cold.rel', f'BANK{COLD_PAGE}', ('P2C_SPLIT_COLD',),
                     '--opt-code-size'),
    ]
    if args.adapter == 'ft812':
        tables_cold_c = BUILD / 'p2c_z80_tables_cold.c'
        write(tables_cold_c, '/* Сгенерировано p2c_z80.py: таблицы глифов отладочной строки (банк). */\n'
              '#include <stdint.h>\n' + catalog_cold_tables)
        cold += [
            sdcc_compile(C_DIR / 'z80' / 'p2c_z80_ft812_cold.c', BUILD / 'adapter_cold.rel', f'BANK{COLD_PAGE}', (),
                         '--opt-code-size'),
            sdcc_compile(tables_cold_c, BUILD / 'tables_cold.rel', f'BANK{COLD_PAGE}', (), '--opt-code-size'),
        ]
    run([SDAS, '-plosgff', '-o', BUILD / 'p2c_z80_crt.rel', C_DIR / 'z80' / 'p2c_z80_crt.s'])
    crt = BUILD / 'p2c_z80_crt.rel'
    data_size = sum(area_sizes(rel).get('_DATA', 0) for rel in resident + cold + [crt])

    def place_image(home_end: int):
        # Остаток окна #0000 после кода и _DATA — объекты снимка, затем окна #4000–#BFFF; куча — после образа.
        ranges = [(home_end + data_size, DL_BUFFER), (0x4000, 0xC000)]
        placed = image_for(compiler, module, image_id, roots, data_size, ranges)
        if placed.next_page != pool_logical:
            raise RuntimeError('число страниц образа зависит от адреса резидентной части')
        base = placed.cursor if placed.range_index == len(ranges) - 1 else 0x4000
        symbols = dict(placed.symbols)
        symbols['p2c_z80_heap_base'] = base
        symbols['p2c_z80_heap_limit'] = 0xC000
        symbols['p2c_z80_stack_top'] = STACK_TOP
        symbols['p2c_z80_page_data1'] = PAGE_DATA1
        lines = ['; Сгенерировано p2c_z80.py: адреса начального состояния.', '\t.module p2c_z80_symbols']
        for name, address in sorted(symbols.items()):
            lines += [f'\t.globl _{name}', f'_{name} = 0x{address:04X}']
        write(BUILD / 'p2c_z80_symbols.s', '\n'.join(lines) + '\n')
        run([SDAS, '-plosgff', '-o', BUILD / 'p2c_z80_symbols.rel', BUILD / 'p2c_z80_symbols.s'])
        return placed, base

    def link_program(bank_objects: dict, home_loc: int, data_loc: int) -> dict[str, int]:
        link = [SDCC, '-mz80', '--no-std-crt0', '--code-loc', '0x0000', '--data-loc', f'0x{data_loc:04X}',
                f'-Wl-b_HOME=0x{home_loc:04X}']
        for page in sorted(bank_objects) + [COLD_PAGE]:
            link.append(f'-Wl-b_BANK{page}=0x{page:02X}C000')
        link += ['-o', BUILD / 'program.ihx', crt, *resident, BUILD / 'p2c_z80_symbols.rel', *cold,
                 *[bank_objects[page] for page in sorted(bank_objects)]]
        output = run(link)
        if 'Undefined' in output or 'error' in output.lower():
            raise RuntimeError('компоновка:\n' + output[-6000:])
        return map_symbols((BUILD / 'program.map').read_text(encoding='latin1'))

    image, heap_base = place_image(0x2800)
    sizes_path = BUILD / 'function_sizes.json'
    sizes: dict[str, int] = json.loads(sizes_path.read_text(encoding='utf-8')) if sizes_path.is_file() else {}
    value_structs = module.value_struct_definitions()
    layout_path = BUILD / 'bank_layout.json'
    previous = json.loads(layout_path.read_text(encoding='utf-8')) if layout_path.is_file() else {}
    for attempt in range(4):
        z80 = Z80Module(module, image, entry_list, BANK_PAGES, sizes, previous=previous)
        files = z80.generate(value_structs, {name: f'p2c_root_{name}' for name in roots})
        changed = set()
        for name, text in files.items():
            path = BUILD / name
            if not path.is_file() or path.read_text(encoding='utf-8') != text:
                changed.add(name)
            write(path, text)
        print(f'раскладка {attempt + 1}: банков {len(z80.banks)}, изменено файлов {len(changed)}, '
              f'{time.perf_counter() - started:.0f} с', flush=True)
        if 'p2c_z80_program.h' in changed:
            changed |= {f'bank_{bank.page:02x}.c' for bank in z80.banks}
        if attempt == 0:
            write(BUILD / 'layout_check.c', z80.layout_check())
            sdcc_compile(BUILD / 'layout_check.c', BUILD / 'layout_check.rel', None)
        bank_objects = compile_banks(z80, args.jobs, started, changed)
        linked = link_program(bank_objects, 0x2200, 0x2800)
        sizes.update(measured_sizes(z80, linked))
        write(sizes_path, json.dumps(sizes, ensure_ascii=False, indent=0, sort_keys=True) + '\n')
        overfull = [page for page in [bank.page for bank in z80.banks] + [COLD_PAGE]
                    if linked.get(f'l__BANK{page}', 0) > PAGE_SIZE]
        if not overfull:
            write(layout_path, json.dumps(z80.bank_layout(), ensure_ascii=False, indent=0, sort_keys=True) + '\n')
            break
        previous = {}
        print('переполнены банки: ' + ', '.join(f'#{page:02X} ({linked[f"l__BANK{page}"]} байт)'
                                                for page in overfull), flush=True)
    else:
        raise RuntimeError('раскладка банков не сошлась')

    # Окончательное размещение: библиотека SDCC (_HOME) и _DATA сразу за резидентным кодом.
    home_loc = linked['l__CODE']
    data_loc = home_loc + linked.get('l__HOME', 0)
    image, heap_base = place_image(data_loc)
    linked = link_program(bank_objects, home_loc, data_loc)
    print(f'резидент: код {home_loc} байт, библиотека {linked.get("l__HOME", 0)}, _DATA #{data_loc:04X} '
          f'({data_size}), образ до #{image.cursor:04X}, куча #{heap_base:04X}–#BFFF ({0xC000 - heap_base} байт), '
          f'стек #{STACK_BOTTOM:04X}–#{STACK_TOP - 1:04X}', flush=True)
    if data_loc + data_size > DL_BUFFER:
        raise RuntimeError(f'резидентный код и _DATA до #{data_loc + data_size:04X} залезают в буфер DL и стек')
    if linked.get('s__DATA') != data_loc or linked.get('l__DATA', 0) != data_size:
        raise RuntimeError(f'_DATA {linked.get("l__DATA")} вместо {data_size}')
    for area in ('l__INITIALIZED', 'l__INITIALIZER', 'l__GSINIT', 'l__GSFINAL'):
        if linked.get(area, 0):
            raise RuntimeError(f'непустая секция {area} без crt0')

    memory = parse_ihx(BUILD / 'program.ihx')
    resident_page = bytearray(PAGE_SIZE)
    window1 = bytearray(PAGE_SIZE)
    window2 = bytearray(PAGE_SIZE)
    for address, byte in memory.items():
        if address < 0x4000:
            resident_page[address] = byte
    for address, byte in image.resident.items():
        if address < STACK_BOTTOM:
            resident_page[address] = byte
        elif 0x4000 <= address < 0x8000:
            window1[address - 0x4000] = byte
        elif 0x8000 <= address < 0xC000:
            window2[address - 0x8000] = byte
        else:
            raise RuntimeError(f'байт образа вне окон данных: #{address:04X}')
    pages.update({PAGE_RESIDENT: bytes(resident_page), PAGE_DATA1: bytes(window1), PAGE_DATA2: bytes(window2)})
    report: dict = {'banks': {}, 'data': data_size, 'heap_base': heap_base}
    for page in [bank.page for bank in z80.banks] + [COLD_PAGE]:
        size = linked.get(f'l__BANK{page}', 0)
        report['banks'][f'{page:02X}'] = size
        data = bytearray(PAGE_SIZE)
        base = (page << 16) | 0xC000
        for address in range(base, base + size):
            data[address - base] = memory.get(address, 0)
        pages[page] = bytes(data)
    final_map, final_content = image.physical_pages(PHYSICAL_DATA_FIRST)
    if {key: value for key, value in final_map.items()} != {key: value for key, value in page_map.items()
                                                            if key < pool_logical}:
        raise RuntimeError('раскладка страниц данных изменилась при размещении')
    pages.update(final_content)
    pages[width_page] = bytes(widths[:PAGE_SIZE])
    pages[width_page + 1] = bytes(widths[PAGE_SIZE:])
    for old in (BUILD / 'pages').glob('page_*.bin'):
        if int(old.stem.split('_')[1], 16) not in pages:
            old.unlink()
    for page, data in pages.items():
        write(BUILD / 'pages' / f'page_{page:02x}.bin', data)
    # Страницы, которые программа считает нулевыми, в SPG не входят: их обнуляет загрузчик
    # (ОЗУ при запуске не очищено). Сюда же страницы пула буферов и журналов модели.
    zero_pages = sorted({page for page, data in pages.items() if not any(data)} |
                        {page_map[pool_logical + index] for index in range(POOL_PAGES)} |
                        ({LOG_PAGE, LOG_PAGE2} if args.adapter == 'record' else set()))
    report.update(
        adapter=args.adapter, resident_code=home_loc, entry=linked['_p2c_z80_start'], pages=sorted(pages),
        zero_pages=zero_pages,
        data_loc=data_loc, heap_limit=0xC000, stack_top=STACK_TOP, stack_bottom=STACK_BOTTOM,
        page_map={str(key): value for key, value in page_map.items()},
        symbols={name: address for name, address in linked.items() if name.startswith(('_p2c_', 's__', 'l__'))},
        page_resident=PAGE_RESIDENT, page_data1=PAGE_DATA1, page_data2=PAGE_DATA2,
        first_bank=z80.banks[0].page, cold_page=COLD_PAGE, log_page=LOG_PAGE, log_page2=LOG_PAGE2,
        bank_of={unit.name: bank.page for bank in z80.banks for unit in bank.units})
    if catalog_model is not None:
        write(BUILD / 'catalog_model.json', json.dumps(catalog_model, ensure_ascii=False) + '\n')
    write(BUILD / 'build_report.json', json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    print(f'Z80: резидентный код {home_loc} байт, банки {sum(report["banks"].values())} байт, '
          f'страниц {len(pages)} (последняя #{max(pages):02X}), {time.perf_counter() - started:.0f} с', flush=True)

    if args.adapter == 'ft812':
        write(BUILD / 'p2c_z80_boot.inc', '\n'.join([
            '; Сгенерировано p2c_z80.py: страницы и вход резидента для загрузчика.',
            f'P2C_START EQU #{linked["_p2c_z80_start"]:04X}',
            f'P2C_PAGE_RESIDENT EQU #{PAGE_RESIDENT:02X}',
            f'P2C_PAGE_DATA2 EQU #{PAGE_DATA2:02X}',
            f'P2C_FIRST_BANK EQU #{z80.banks[0].page:02X}',
            '                MACRO P2C_ZERO_PAGE_LIST',
            *[f'                DB {", ".join(f"#{page:02X}" for page in zero_pages[start:start + 16])}'
              for start in range(0, len(zero_pages), 16)],
            '                DB 0',
            '                ENDM', '']))
        run([SJASMPLUS, ROOT / 'Source' / 'ASM' / 'p2c_boot.asm', '--syntax=ab',
             f'--lst={BUILD / "boot.lst"}', f'--sym={BUILD / "boot.sym"}'], cwd=ROOT / 'Source' / 'ASM')
        blocks = [('#5000', PAGE_BOOT, BUILD / 'boot.bin')]
        for page, data in sorted(pages.items()):
            if page in zero_pages:
                continue
            blocks.append(('#0000', page, BUILD / 'pages' / f'page_{page:02x}.bin'))
        ini = ['Desc = R-Type translated app.main (p2c)', 'Start = 0x5000', 'Stack = 0x3FFF', 'Resident = 0x4F00',
               'Page3 = 0', 'Clock = 2', 'INT = 0', 'Pager = 0', 'Compression = 0', '']
        ini += [f'Block = {address}, #{page:02X}, {path.relative_to(ROOT).as_posix()}' for address, page, path in blocks]
        write(BUILD / 'spg.ini', '\n'.join(ini) + '\n')
        run([SPGBLD, '-b', BUILD / 'spg.ini', BUILD / 'rtype_vdac2.spg'], cwd=ROOT)
        spg = (BUILD / 'rtype_vdac2.spg').read_bytes()
        print(f'SPG: {BUILD / "rtype_vdac2.spg"} {len(spg)} байт, блоков {len(blocks)}, '
              f'SHA-256 {hashlib.sha256(spg).hexdigest()[:16]}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
