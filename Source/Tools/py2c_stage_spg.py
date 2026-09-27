"""SPG транслированного Stage для TS-Config/VDAC2: C из py2c, SDCC, ресурсы FT812.

Весь игровой код — `Stage.update/draw_back/draw_front` активного rtype_port,
переведённые py2c. Руками написаны только аппаратные части: загрузка страниц,
DMA-выгрузка в FT812, адаптер display list и кадровый драйвер.
Демонстрационный профиль: в RAM_G лежат атласы участков 0–1.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame  # noqa: E402

from py2c.heap import Heap  # noqa: E402
from py2c.program import Program  # noqa: E402
from py2c.translate import Translator  # noqa: E402
from py2c.z80module import PAGE_SIZE, build_z80_module  # noqa: E402

BUILD = ROOT / 'Build' / 'Py2cStageZ80'
C_DIR = ROOT / 'Source' / 'C' / 'py2c'
SDCC = Path('E:/zx/sdcc/bin/sdcc.exe')
MAKEBIN = SDCC.with_name('makebin.exe')
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
SPGBLD = Path('E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe')
ROOTS = {'stage': ('Stage', ['update', 'draw_back', 'draw_front'])}
FIRST_DATA_PAGE = 0x10
DEMO_SECTIONS = 2
GLYPH_W, GLYPH_H = 14, 15
CELLS_PER_HANDLE = 128
CODE2_START = 0x6000


def run(command: list, cwd: Path = ROOT) -> str:
    env = os.environ.copy()
    env['PATH'] = str(SDCC.parent) + os.pathsep + env['PATH']
    result = subprocess.run([str(item) for item in command], cwd=cwd, env=env,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(str(command[0])).name}:\n{result.stdout}\n{result.stderr}')
    return result.stdout + result.stderr


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding='utf-8', newline='\n')
    else:
        path.write_bytes(data)


def argb4444(surface: pygame.Surface) -> bytes:
    raw = pygame.image.tobytes(surface, 'RGBA')
    out = bytearray()
    for r, g, b, a in zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4]):
        out += struct.pack('<H', ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4))
    return bytes(out)


def resources(stage, graphics_first_page: int) -> tuple[str, bytes, dict, dict[int, int]]:
    """Атласы загружаемых участков в RAM_G, номера изображений и таблицы вершин.

    Номер изображения кодирует команду FT812: биты 8..12 — BITMAP_HANDLE,
    биты 0..6 — CELL, бит 14 — сплошной чёрный глиф, бит 15 — не загружено.
    """
    atlases = []
    seen = set()
    for index in range(DEMO_SECTIONS):
        section = stage.sections[index]
        for name in ('bg_atlas', 'fg_atlas', 'boss_bg_atlas', 'boss_fg_atlas',
                     'flash_bg_atlas', 'flash_fg_atlas'):
            atlas = getattr(section, name)
            if id(atlas) in seen:
                continue
            seen.add(id(atlas))
            atlases.append((index, name, atlas))
    blob = bytearray()
    handle = 0
    setup = []
    image_ids: dict[int, int] = {}
    black_count = 0
    source_files = {}
    for section_index, name, atlas in atlases:
        base = len(blob)
        for position, surface in enumerate(atlas):
            if surface.get_size() != (GLYPH_W, GLYPH_H):
                raise RuntimeError(f'глиф {name}[{position}] не {GLYPH_W}×{GLYPH_H}')
            pixels = argb4444(surface)
            black = pixels == b'\x00\xF0' * (GLYPH_W * GLYPH_H)
            black_count += black
            blob += pixels
            code = ((handle + (position >> 7)) << 8) | (position & 127) | (0x4000 if black else 0)
            if id(surface) in image_ids and image_ids[id(surface)] != code:
                raise RuntimeError(f'поверхность {name}[{position}] уже имеет другой номер')
            image_ids[id(surface)] = code
        handles = (len(atlas) + CELLS_PER_HANDLE - 1) // CELLS_PER_HANDLE
        for part in range(handles):
            source = base + part * CELLS_PER_HANDLE * GLYPH_W * GLYPH_H * 2
            stride = GLYPH_W * 2
            width = (GLYPH_W * 8 + 4) // 5
            height = (GLYPH_H * 8 + 4) // 5
            setup += [0x01000000 | source,
                      0x07000000 | (6 << 19) | ((stride & 1023) << 9) | (GLYPH_H & 511),
                      0x28000000 | ((stride >> 10) << 2) | (GLYPH_H >> 9),
                      0x08000000 | ((width & 511) << 9) | (height & 511),
                      0x29000000 | ((width >> 9) << 2) | (height >> 9)]
        source_files[f'{section_index}:{name}'] = {'glyphs': len(atlas), 'handle': handle, 'ram_g': base}
        handle += handles
    if handle > 32:
        raise RuntimeError(f'нужно {handle} BITMAP_HANDLE, у FT812 их 32')
    if len(blob) > 1 << 20:
        raise RuntimeError(f'RAM_G переполнен: {len(blob)} байт')
    # Байты VERTEX2F: X в 1/8 физического пикселя + смещение 256 (VERTEX_TRANSLATE_X -32 px).
    x_bytes = []
    for x in range(-16, 704):
        units = (x * 64) // 5 + 256
        x_bytes += [0x40 | ((units >> 9) & 0x3F), (units >> 1) & 0xFF, (units & 1) << 7]
    y_bytes = []
    for y in range(480):
        units = (y * 64) // 5
        y_bytes += [(units >> 8) & 0x7F, units & 0xFF]
    lines = ['/* Сгенерировано py2c_stage_spg.py из поверхностей атласов снимка Stage. */',
             '#ifndef PY2C_STAGE_RESOURCES_H', '#define PY2C_STAGE_RESOURCES_H',
             f'#define PY2C_HANDLE_COUNT {handle}',
             'static const uint32_t py2c_handle_setup[] = {',
             '    ' + ', '.join(f'0x{word:08X}UL' for word in setup), '};',
             f'static const uint8_t py2c_x_bytes[{len(x_bytes)}] = {{ ' + ', '.join(map(str, x_bytes)) + ' };',
             f'static const uint8_t py2c_y_bytes[{len(y_bytes)}] = {{ ' + ', '.join(map(str, y_bytes)) + ' };',
             '#endif', '']
    pages = (len(blob) + PAGE_SIZE - 1) // PAGE_SIZE
    manifest = {'atlases': source_files, 'handles': handle, 'ram_g_bytes': len(blob),
                'graphics_pages': pages, 'graphics_first_page': graphics_first_page,
                'black_glyphs': black_count, 'images': len(image_ids)}
    return '\n'.join(lines), bytes(blob), manifest, image_ids


def section_map(map_text: str) -> dict:
    sections = {}
    for name, address, size in re.findall(r'^(_\w+)\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s+=', map_text, re.M):
        sections[name] = (int(address, 16), int(size, 16))
    return sections


def symbol_address(map_text: str, name: str) -> int:
    match = re.search(r'^\s*([0-9A-Fa-f]{8})\s+_' + re.escape(name) + r'\b', map_text, re.M)
    if not match:
        raise RuntimeError(f'нет символа {name} в карте компоновки')
    return int(match[1], 16)


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    pygame.init()
    pygame.display.set_mode((64, 64))
    from rtype_port.stage import Stage
    stage = Stage()
    program = Program('rtype_port', ['stage'])
    # Порог 256 байт: мелкие изменяемые буферы остаются резидентными, таблицы — на страницах.
    heap = Heap(program, {'stage': stage}, external_threshold=256)
    translator = Translator(program, heap)
    translator.translate([(class_name, method)
                          for class_name, methods in ROOTS.values() for method in methods])
    # Номера изображений задаются раскладкой атласов до генерации данных.
    header, blob, resource_manifest, image_ids = resources(stage, 0)
    module = build_z80_module(translator, heap, ROOTS, FIRST_DATA_PAGE, 'py2c_stage', image_ids)
    BUILD.mkdir(parents=True, exist_ok=True)
    write(BUILD / 'py2c_stage.h', module.header)
    write(BUILD / 'py2c_stage.c', module.source)
    graphics_first = module.manifest['last_page'] + 1
    resource_manifest['graphics_first_page'] = graphics_first
    write(BUILD / 'py2c_stage_resources.h', header)
    print(f'трансляция: функций {len(translator.queue)}, страниц данных '
          f'{graphics_first - FIRST_DATA_PAGE}, RAM_G {len(blob)} байт, '
          f'хэндлов {resource_manifest["handles"]}', flush=True)

    # Сгенерированный код игры — банк C000–FFFF (страница 6); рантайм, платформа,
    # адаптер FT812 и драйвер — резидентный сегмент CODE2 в окне 1 с #6000 (страница 5).
    sources = [(BUILD / 'py2c_stage.c', False), (C_DIR / 'py2c_runtime.c', True),
               (C_DIR / 'z80' / 'py2c_z80.c', True), (C_DIR / 'z80' / 'py2c_ft812.c', True),
               (C_DIR / 'z80' / 'py2c_stage_main.c', True)]
    objects = []
    for source, resident in sources:
        target = BUILD / (source.stem + '.rel')
        segment = ['--codeseg', 'CODE2', '--constseg', 'CODE2'] if resident else []
        run([SDCC, '-mz80', '--std-c11', '--opt-code-speed', '--no-c-code-in-asm', *segment,
             '-I', C_DIR / 'z80', '-I', C_DIR, '-I', BUILD, '-c', source, '-o', target])
        objects.append(target)
    run([SDCC, '-mz80', '--no-std-crt0', '--code-loc', '0xc000', '--data-loc', '0x3000',
         f'-Wl-b_CODE2={CODE2_START:#x}', '-o', BUILD / 'stage.ihx', *objects])
    map_text = (BUILD / 'stage.map').read_text(encoding='latin1')
    sections = section_map(map_text)
    code_start, code_size = sections.get('_CODE', (0, 0))
    code2_start, code2_size = sections.get('_CODE2', (0, 0))
    data_start, data_size = sections.get('_DATA', (0, 0))
    report = {'code': [code_start, code_size], 'code2': [code2_start, code2_size],
              'data': [data_start, data_size],
              'sections': {name: list(value) for name, value in sections.items() if value[1]}}
    if code_start != 0xC000 or code_start + code_size > 0x10000:
        raise RuntimeError(f'_CODE {code_size} байт не помещается в банк C000–FFFF')
    if code2_size and (code2_start != CODE2_START or code2_start + code2_size > 0x8000):
        raise RuntimeError(f'_CODE2 {code2_size} байт не помещается в окно 1 до #8000')
    if data_start + data_size > 0x3C00:
        raise RuntimeError(f'_DATA {data_size} байт залезает на стек: {data_start:#x}')
    for name, (address, size) in sections.items():
        if size and name not in ('_CODE', '_CODE2', '_DATA', '_HOME', '_GSINIT', '_GSFINAL',
                                 '_HEADER', '_HEADER0'):
            raise RuntimeError(f'непустая секция {name} ({size} байт) без CRT не поддержана')
    run([MAKEBIN, '-s', '65536', '-o', '49152', BUILD / 'stage.ihx', BUILD / 'code.bin'])
    run([MAKEBIN, '-s', '65536', '-o', str(CODE2_START), BUILD / 'stage.ihx', BUILD / 'code2.bin'])
    code2_bin = (BUILD / 'code2.bin').read_bytes()[:0x8000 - CODE2_START]
    write(BUILD / 'code2.bin', code2_bin)
    symbols = {name: symbol_address(map_text, name) for name in
               ('Py2c_Init', 'Py2c_Frame', 'py2c_page2', 'py2c_fault', 'py2c_fault_code', 'py2c_dl_bytes',
                'py2c_dl_count', 'py2c_dl_peak', 'py2c_dl_dropped', 'py2c_dl_missing', 'py2c_dl_skipped',
                'py2c_frames', 'py2c_restarts')}
    graphics_pages = resource_manifest['graphics_pages']
    symbol_lines = ['; Сгенерировано py2c_stage_spg.py из карты компоновки SDCC.']
    symbol_lines += [f'{name} EQU #{address:04X}' for name, address in symbols.items()]
    symbol_lines += [f'PY2C_FIRST_DATA_PAGE EQU #{FIRST_DATA_PAGE:02X}',
                     f'PY2C_GFX_FIRST_PAGE EQU #{graphics_first:02X}',
                     f'PY2C_GFX_PAGES EQU {graphics_pages}']
    write(BUILD / 'py2c_symbols.inc', '\n'.join(symbol_lines) + '\n')
    run([SJASMPLUS, ROOT / 'Source' / 'ASM' / 'py2c_stage_boot.asm', '--syntax=ab',
         f'--lst={BUILD / "boot.lst"}', f'--sym={BUILD / "boot.sym"}'])

    boot_size = (BUILD / 'boot.bin').stat().st_size
    if 0x5000 + boot_size > CODE2_START:
        raise RuntimeError(f'загрузчик {boot_size} байт залезает на CODE2 #{CODE2_START:04X}')
    blocks = [('#5000', 0x05, BUILD / 'boot.bin'), ('#0000', 0x06, BUILD / 'code.bin')]
    # CODE2 в той же странице 5 со смещения #2000: отдельный блок SPG.
    blocks.append((f'#{CODE2_START:04X}', 0x05, BUILD / 'code2.bin'))
    # Образы страниц: упакованные данные нескольких массивов собираются в одну страницу.
    page_images: dict[int, bytearray] = {}
    for placement in module.placements:
        targets = [placement.page] + ([placement.pristine] if placement.pristine is not None else [])
        for target in targets:
            for part in range(placement.pages):
                image = page_images.setdefault(target + part, bytearray(PAGE_SIZE))
                chunk = placement.payload[part * PAGE_SIZE:(part + 1) * PAGE_SIZE]
                start = placement.offset if part == 0 else 0
                if any(image[start:start + len(chunk)]):
                    raise RuntimeError(f'данные {placement.symbol} перекрывают страницу #{target + part:02X}')
                image[start:start + len(chunk)] = chunk
    for page in sorted(page_images):
        name = BUILD / f'data_{page:02x}.bin'
        write(name, bytes(page_images[page]))
        blocks.append(('#0000', page, name))
    for part in range(graphics_pages):
        name = BUILD / f'gfx_{graphics_first + part:02x}.bin'
        write(name, blob[part * PAGE_SIZE:(part + 1) * PAGE_SIZE].ljust(PAGE_SIZE, b'\0'))
        blocks.append(('#0000', graphics_first + part, name))
    used = [page for _, page, _ in blocks if page != 0x05] + [0x05]
    if len(used) != len(set(used)) or max(used) > 0xFF:
        raise RuntimeError('пересечение или выход физических страниц SPG')
    ini = ['Desc = py2c Stage translation checkpoint', 'Start = 0x5000', 'Stack = 0x3FFF',
           'Resident = 0x4F00', 'Page3 = 0', 'Clock = 2', 'INT = 0', 'Pager = 0', 'Compression = 0', '']
    ini += [f'Block = {address}, #{page:02X}, {path.relative_to(ROOT).as_posix()}' for address, page, path in blocks]
    write(BUILD / 'stage.ini', '\n'.join(ini) + '\n')
    run([SPGBLD, '-b', BUILD / 'stage.ini', BUILD / 'rtype_vdac2.spg'])
    spg = (BUILD / 'rtype_vdac2.spg').read_bytes()
    report.update(symbols=symbols, resources=resource_manifest, pages_last=max(used),
                  code_bytes=code_size, code2_bytes=code2_size, boot_bytes=boot_size, spg_bytes=len(spg),
                  spg_sha256=hashlib.sha256(spg).hexdigest(), graphics_sha256=hashlib.sha256(blob).hexdigest(),
                  placements=module.manifest['placements'])
    write(BUILD / 'graphics.bin', blob)
    write(BUILD / 'build_report.json', json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    print(f'SPG: {BUILD / "rtype_vdac2.spg"} {len(spg)} байт, код {code_size} байт, '
          f'_DATA {data_size} байт, страниц до #{max(used):02X}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
