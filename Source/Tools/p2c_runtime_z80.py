"""Сборка цикла app.main полного runtime (титул и управление машиной, p2c) для Z80 TS-Config.

Код p2c живёт рядом с переведённым кодом ROM (v30z80) в одном SPG (rtype_spg.py), поэтому
его страницы не пересекаются со страницами машины:
  #09 резидент p2c (окно #0000), #0A и #0D — данные снимка и куча (окна #4000, #8000),
  #49…#4E банки кода, #4F отрисовка титула на ассемблере, #50 холодный банк, #51… страницы данных,
  пула и каталога FT812.
Корни трансляции — первичная отрисовка титула и RuntimeApp.frame (p2c_runtime_app.py);
вызовы машины — p2c_z80_runtime.c и p2c_z80_switch.s. TitleScreen.render на Z80 — проигрыватель
таблиц p2c_z80_title.s (таблицы и сверка с render — p2c_title_native.py). Результат —
Build/P2cRuntime: pages/page_XX.bin, build_report.json (символы и страницы).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import p2c_runtime_app  # noqa: E402
import p2c_z80  # noqa: E402
from p2c.cgen import CModule  # noqa: E402
from p2c.cgen_z80 import Z80Module  # noqa: E402
from p2c.z80data import PAGE_SIZE  # noqa: E402

BUILD = ROOT / 'Build' / 'P2cRuntime'
C_DIR = ROOT / 'Source' / 'C' / 'p2c'
PAGE_RESIDENT = 0x09
PAGE_DATA1 = 0x0A
PAGE_DATA2 = 0x0D
BANK_PAGES = list(range(0x49, 0x4F))
TITLE_PAGE = 0x4F               # p2c_z80_title.s: область _BANK79
COLD_PAGE = 0x50
PHYSICAL_DATA_FIRST = 0x51
LAST_FREE_PAGE = 0x6F
POOL_PAGES = 2
SWITCH_PAGE = 0x0E
STACK_TOP = 0x4000
STACK_BOTTOM = 0x3700
DL_BUFFER = 0x3600


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    BUILD.mkdir(parents=True, exist_ok=True)
    # Функции сборки p2c_z80 берут каталог сборки и раскладку из своего модуля.
    p2c_z80.BUILD = BUILD
    p2c_z80.PAGE_RESIDENT = PAGE_RESIDENT
    p2c_z80.PAGE_DATA1 = PAGE_DATA1
    p2c_z80.PAGE_DATA2 = PAGE_DATA2
    p2c_z80.BANK_PAGES = BANK_PAGES
    p2c_z80.COLD_PAGE = COLD_PAGE
    p2c_z80.LOGICAL_DATA_FIRST = 1

    app, _port = p2c_runtime_app.build_snapshot()
    compiler, entry_list = p2c_runtime_app.analyze(app)
    # Отрисовка титула — ассемблерный проигрыватель таблиц; функции, нужные только ей, не генерируются.
    # P2C_TITLE_NATIVE=0 — переведённая отрисовка (сверочная сборка для сравнения трасс display list).
    render_key = ('method', 'TitleScreen', 'render')
    if os.environ.get('P2C_TITLE_NATIVE', '1') != '0':
        compiler.native_bodies[render_key] = lambda emitter: [
            f'    p2c_title_render_native(&{compiler.layout.field_code("self", "TitleScreen", "frame")}, '
            f'(const uint8_t *)&{compiler.layout.field_code("self", "TitleScreen", "starting")});',
            '    (void)target;']
        compiler.native_prototypes.append(
            'void p2c_title_render_native(const int32_t *frame, const uint8_t *starting) __banked;')
        removed = compiler.prune_native([compiler.plans[render_key], compiler.plans[('method', 'RuntimeApp', 'frame')]])
        print(f'отрисовка титула — p2c_z80_title.s, не генерируются: {", ".join(removed)}', flush=True)
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

    probe = p2c_z80.image_for(compiler, module, image_id, roots, 0)
    page_map, data_content = probe.physical_pages(PHYSICAL_DATA_FIRST)
    next_physical = PHYSICAL_DATA_FIRST + len(data_content)
    pool_logical = probe.next_page
    for index in range(POOL_PAGES):
        page_map[pool_logical + index] = next_physical + index
    next_physical += POOL_PAGES
    import p2c_z80_catalog
    surfaces = {number: alive[number - 1] for number in range(1, len(alive) + 1)}
    # Изображения титула — в зоне RAM_G, которую отдаёт видеоадаптер машины (ячейки тайлов, из
    # которых показанный кадр игры не читает; v30z80_video_assets.py).
    video_catalog = ROOT / 'Build' / 'V30Z80' / 'video_catalog.json'
    if not video_catalog.is_file():
        raise SystemExit('нет Build/V30Z80/video_catalog.json: сначала v30z80_build.py')
    ram_g = json.loads(video_catalog.read_text(encoding='utf-8'))['ram_g']
    catalog = p2c_z80_catalog.build_catalog(surfaces, None, None, next_physical, [],
                                            ram_zone=(ram_g['title_base'], ram_g['title_bytes']))
    pages: dict[int, bytes] = dict(catalog.pages)
    next_physical = catalog.defines['P2C_FT_LAST_PAGE'] + 1
    print(f'каталог: записей {len(catalog.entries)}, изображений {len(catalog.image_entry)}, страниц до '
          f'#{catalog.defines["P2C_FT_LAST_PAGE"]:02X}', flush=True)
    if next_physical - 1 > LAST_FREE_PAGE:
        raise RuntimeError(f'физических страниц не хватает: последняя #{next_physical - 1:02X}')
    # Таблицы ассемблерной отрисовки титула: номера изображений снимка, сверка с TitleScreen.render.
    import p2c_title_native
    from rtype_port import title as title_module

    def title_image(surface) -> int:
        """Изображение как запись каталога (#8000 | запись): p2c_blit берёт запись без таблицы изображений."""
        number = image_ids.get(id(surface))
        if number is None or number not in catalog.image_entry or catalog.image_entry[number] >= 0x4000:
            raise SystemExit('изображение титула не попало в каталог')
        return 0x8000 | catalog.image_entry[number]
    title_tables = p2c_title_native.TitleTables(title_module, app.title.assets, title_image)
    title_tables.verify()
    p2c_z80.write(BUILD / 'p2c_z80_title_constants.inc', title_tables.constants_asm(TITLE_PAGE))
    p2c_z80.write(BUILD / 'p2c_z80_title.inc', title_tables.asm())
    print(f'таблицы титула: логотип до кадра {title_tables.logo_last}, сверено с render на кадрах '
          f'0…{p2c_title_native.VERIFY_FRAMES}', flush=True)
    config = '\n'.join([
        '/* Сгенерировано p2c_runtime_z80.py: страницы сборки. */',
        '#ifndef P2C_Z80_CONFIG_H', '#define P2C_Z80_CONFIG_H', '#include <stdint.h>',
        f'#define P2C_Z80_PAGE_RESIDENT 0x{PAGE_RESIDENT:02X}u',
        f'#define P2C_Z80_DL_BUFFER 0x{DL_BUFFER:04X}u',
        f'#define P2C_Z80_POOL_FIRST 0x{pool_logical:02X}u',
        f'#define P2C_Z80_POOL_COUNT {POOL_PAGES}u',
        '#define P2C_Z80_LOG_PAGE 0x00u',
        '#define P2C_Z80_LOG_PAGE2 0x00u',
        '#define P2C_Z80_TEXT_WIDTH_PAGE 0x00u',
        '#define P2C_Z80_TEXT_WIDTH_BASE 0',
        '#define P2C_Z80_TEXT_HEIGHT 15',
        'extern const uint8_t p2c_z80_typed_banks[32];',
        'extern const uint8_t p2c_page_map[256];',
        *p2c_z80_catalog.config_lines(catalog),
        '#endif', ''])
    p2c_z80.write(BUILD / 'p2c_z80_config.h', config)
    # Те же константы для ассемблерной части адаптера (p2c_z80_blit.s).
    p2c_z80.write(BUILD / 'p2c_z80_config.inc', '\n'.join([
        '; Сгенерировано p2c_runtime_z80.py: константы адаптера для ассемблера.',
        f'P2C_Z80_DL_BUFFER = 0x{DL_BUFFER:04X}',
        *[f'{name} = {value}' for name, value in sorted(catalog.defines.items())], '']))
    map_values = [page_map.get(index, 0) for index in range(256)]
    catalog_tables, catalog_cold_tables = p2c_z80_catalog.tables_source(catalog)
    tables_c = BUILD / 'p2c_z80_tables.c'
    p2c_z80.write(tables_c, '/* Сгенерировано p2c_runtime_z80.py: таблицы страниц и адаптера. */\n#include <stdint.h>\n'
                  'const uint8_t p2c_z80_typed_banks[32] = { 0 };\n'
                  'const uint8_t p2c_page_map[256] = { ' + ', '.join(map(str, map_values)) + ' };\n' + catalog_tables)
    compile_ = p2c_z80.sdcc_compile
    # Диагностические ветки цикла оболочки (ifdef в p2c_z80_runtime.c) — переменной среды P2C_DEFINES: имена через
    # запятую, например P2C_VSYNC_TEST (как RTYPE_ASM_DEFINES у машины). В обычной сборке переменной нет.
    diagnostics = tuple(name.strip() for name in os.environ.get('P2C_DEFINES', '').split(',') if name.strip())
    resident = [
        compile_(C_DIR / 'p2c_runtime.c', BUILD / 'runtime_hot.rel', None, ('P2C_SPLIT_HOT',), '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80.c', BUILD / 'z80_hot.rel', None, ('P2C_SPLIT_HOT',), '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80_runtime.c', BUILD / 'z80_runtime.rel', None, diagnostics, '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80_ft812.c', BUILD / 'adapter.rel', None, ('P2C_BLIT_ASM',), '--opt-code-size'),
        compile_(tables_c, BUILD / 'tables.rel', None, (), '--opt-code-size'),
    ]
    for source in ('p2c_z80_access.s', 'p2c_z80_switch.s', 'p2c_z80_blit.s'):
        target = BUILD / source.replace('.s', '.rel')
        p2c_z80.run([p2c_z80.SDAS, '-plosgff', f'-I{BUILD}', '-o', target, C_DIR / 'z80' / source])
        resident.append(target)
    tables_cold_c = BUILD / 'p2c_z80_tables_cold.c'
    p2c_z80.write(tables_cold_c, '/* Сгенерировано p2c_runtime_z80.py: таблицы глифов отладочной строки (банк). */\n'
                  '#include <stdint.h>\n' + catalog_cold_tables)
    bank = f'BANK{COLD_PAGE}'
    cold = [
        compile_(C_DIR / 'p2c_runtime.c', BUILD / 'runtime_cold.rel', bank, ('P2C_SPLIT_COLD',), '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80.c', BUILD / 'z80_cold.rel', bank, ('P2C_SPLIT_COLD',), '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80_ft812_cold.c', BUILD / 'adapter_cold.rel', bank, (), '--opt-code-size'),
        compile_(C_DIR / 'z80' / 'p2c_z80_runtime_cold.c', BUILD / 'runtime_input.rel', bank, (), '--opt-code-size'),
        compile_(tables_cold_c, BUILD / 'tables_cold.rel', bank, (), '--opt-code-size'),
    ]
    title_rel = BUILD / 'p2c_z80_title.rel'
    p2c_z80.run([p2c_z80.SDAS, '-plosgff', f'-I{BUILD}', '-o', title_rel, C_DIR / 'z80' / 'p2c_z80_title.s'])
    if TITLE_PAGE != 79:
        raise RuntimeError('p2c_z80_title.s размещён в области _BANK79 (страница #4F)')
    p2c_z80.run([p2c_z80.SDAS, '-plosgff', '-o', BUILD / 'p2c_z80_crt.rel', C_DIR / 'z80' / 'p2c_z80_crt.s'])
    crt = BUILD / 'p2c_z80_crt.rel'
    data_size = sum(p2c_z80.area_sizes(rel).get('_DATA', 0) for rel in resident + cold + [crt])

    def place_image(home_end: int):
        ranges = [(home_end + data_size, DL_BUFFER), (0x4000, 0xC000)]
        placed = p2c_z80.image_for(compiler, module, image_id, roots, data_size, ranges)
        if placed.next_page != pool_logical:
            raise RuntimeError('число страниц образа зависит от адреса резидентной части')
        base = placed.cursor if placed.range_index == len(ranges) - 1 else 0x4000
        symbols = dict(placed.symbols)
        symbols['p2c_z80_heap_base'] = base
        symbols['p2c_z80_heap_limit'] = 0xC000
        symbols['p2c_z80_stack_top'] = STACK_TOP
        symbols['p2c_z80_page_data1'] = PAGE_DATA1
        symbols['p2c_switch_page'] = SWITCH_PAGE
        lines = ['; Сгенерировано p2c_runtime_z80.py: адреса начального состояния.', '\t.module p2c_z80_symbols']
        for name, address in sorted(symbols.items()):
            lines += [f'\t.globl _{name}', f'_{name} = 0x{address:04X}']
        p2c_z80.write(BUILD / 'p2c_z80_symbols.s', '\n'.join(lines) + '\n')
        p2c_z80.run([p2c_z80.SDAS, '-plosgff', '-o', BUILD / 'p2c_z80_symbols.rel', BUILD / 'p2c_z80_symbols.s'])
        return placed, base

    def link_program(bank_objects: dict, home_loc: int, data_loc: int) -> dict[str, int]:
        link = [p2c_z80.SDCC, '-mz80', '--no-std-crt0', '--code-loc', '0x0000', '--data-loc', f'0x{data_loc:04X}',
                f'-Wl-b_HOME=0x{home_loc:04X}']
        for page in sorted(bank_objects) + [TITLE_PAGE, COLD_PAGE]:
            link.append(f'-Wl-b_BANK{page}=0x{page:02X}C000')
        link += ['-o', BUILD / 'program.ihx', crt, *resident, BUILD / 'p2c_z80_symbols.rel', *cold, title_rel,
                 *[bank_objects[page] for page in sorted(bank_objects)]]
        output = p2c_z80.run(link)
        if 'Undefined' in output or 'error' in output.lower():
            raise RuntimeError('компоновка:\n' + output[-6000:])
        return p2c_z80.map_symbols((BUILD / 'program.map').read_text(encoding='latin1'))

    image, heap_base = place_image(0x2800)
    sizes_path = BUILD / 'function_sizes.json'
    sizes: dict[str, int] = json.loads(sizes_path.read_text(encoding='utf-8')) if sizes_path.is_file() else {}
    # Типы кортежей-констант модулей (PLAYER_LAUNCH_HANDLERS и др.) регистрируются до объявлений
    # структур: заголовок Z80 объявляет константы после них.
    for number in module.layout.constant_symbols:
        module.r.ctype(compiler.constants[number][1])
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
            p2c_z80.write(path, text)
        print(f'раскладка {attempt + 1}: банков {len(z80.banks)}, изменено файлов {len(changed)}, '
              f'{time.perf_counter() - started:.0f} с', flush=True)
        if 'p2c_z80_program.h' in changed:
            changed |= {f'bank_{bank_item.page:02x}.c' for bank_item in z80.banks}
        bank_objects = p2c_z80.compile_banks(z80, args.jobs, started, changed)
        linked = link_program(bank_objects, 0x2200, 0x2800)
        sizes.update(p2c_z80.measured_sizes(z80, linked))
        p2c_z80.write(sizes_path, json.dumps(sizes, ensure_ascii=False, indent=0, sort_keys=True) + '\n')
        overfull = [page for page in [bank_item.page for bank_item in z80.banks] + [TITLE_PAGE, COLD_PAGE]
                    if linked.get(f'l__BANK{page}', 0) > PAGE_SIZE]
        if not overfull:
            p2c_z80.write(layout_path, json.dumps(z80.bank_layout(), ensure_ascii=False, indent=0, sort_keys=True) + '\n')
            break
        previous = {}
        print('переполнены банки: ' + ', '.join(f'#{page:02X} ({linked[f"l__BANK{page}"]} байт)' for page in overfull),
              flush=True)
    else:
        raise RuntimeError('раскладка банков не сошлась')

    home_loc = linked['l__CODE']
    data_loc = home_loc + linked.get('l__HOME', 0)
    image, heap_base = place_image(data_loc)
    linked = link_program(bank_objects, home_loc, data_loc)
    print(f'резидент: код {home_loc} байт, библиотека {linked.get("l__HOME", 0)}, _DATA #{data_loc:04X} '
          f'({data_size}), образ до #{image.cursor:04X}, куча #{heap_base:04X}–#BFFF', flush=True)
    if data_loc + data_size > DL_BUFFER:
        raise RuntimeError(f'резидентный код и _DATA до #{data_loc + data_size:04X} залезают в буфер DL и стек')
    for area in ('l__INITIALIZED', 'l__INITIALIZER', 'l__GSINIT', 'l__GSFINAL'):
        if linked.get(area, 0):
            raise RuntimeError(f'непустая секция {area} без crt0')

    memory = p2c_z80.parse_ihx(BUILD / 'program.ihx')
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
    report: dict = {'banks': {}}
    for page in [bank_item.page for bank_item in z80.banks] + [TITLE_PAGE, COLD_PAGE]:
        size = linked.get(f'l__BANK{page}', 0)
        report['banks'][f'{page:02X}'] = size
        data = bytearray(PAGE_SIZE)
        base = (page << 16) | 0xC000
        for address in range(base, base + size):
            data[address - base] = memory.get(address, 0)
        pages[page] = bytes(data)
    final_map, final_content = image.physical_pages(PHYSICAL_DATA_FIRST)
    if final_map != {key: value for key, value in page_map.items() if key < pool_logical}:
        raise RuntimeError('раскладка страниц данных изменилась при размещении')
    pages.update(final_content)
    for old in (BUILD / 'pages').glob('page_*.bin'):
        if int(old.stem.split('_')[1], 16) not in pages:
            old.unlink()
    for page, data in pages.items():
        p2c_z80.write(BUILD / 'pages' / f'page_{page:02x}.bin', data)
    zero_pages = sorted({page for page, data in pages.items() if not any(data)} |
                        {page_map[pool_logical + index] for index in range(POOL_PAGES)})
    report.update(
        entry=linked['_p2c_z80_start'], switch_return=linked['_p2c_switch_return'], pages=sorted(pages),
        zero_pages=zero_pages, page_resident=PAGE_RESIDENT, page_data1=PAGE_DATA1, page_data2=PAGE_DATA2,
        first_bank=z80.banks[0].page, cold_page=COLD_PAGE, switch_page=SWITCH_PAGE,
        symbols={name: address for name, address in linked.items() if name.startswith(('_p2c_', 's__', 'l__'))},
        catalog=p2c_z80_catalog.model_description(catalog))
    p2c_z80.write(BUILD / 'build_report.json', json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    print(f'Z80: резидентный код {home_loc} байт, банки {sum(report["banks"].values())} байт, страниц {len(pages)} '
          f'(последняя #{max(pages):02X}), {time.perf_counter() - started:.0f} с', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
