"""SPG порта `rtype_vdac2.spg`: цикл app.main текущей Python-версии (титул и управление машиной,
код p2c) и машина World ROM (переведённый код V30 → Z80 с адаптером FT812).

Шаги: сборка машины (v30z80_build.py, без её отладочного SPG), сборка кода p2c
(p2c_runtime_z80.py), страница переключения rtype_switch.asm (окна машины ↔ окна p2c),
загрузчик rtype_boot.asm (FT812, нулевые страницы, переход в резидент p2c), spgbld.
Страницы обеих частей не должны пересекаться. Результат — Build/V30Z80/rtype_vdac2.spg.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'Source' / 'Tools'
ASM = ROOT / 'Source' / 'ASM'
MACHINE = ROOT / 'Build' / 'V30Z80'
P2C = ROOT / 'Build' / 'P2cRuntime'
SJASMPLUS = Path('E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe')
SPGBLD = Path('E:/zx/z80/tsconf_project/exe/spgbld/spgbld.exe')
BOOT_PAGE = 0x05
SWITCH_PAGE = 0x0E
BOOT_CALL = 0xC080                  # вход вызова машины из загрузчика SPG в странице переключения (rtype_switch.asm)


def run(command: list, cwd: Path) -> None:
    result = subprocess.run([str(item) for item in command], cwd=cwd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    output = result.stdout + result.stderr
    if result.returncode:
        raise SystemExit(f'{Path(str(command[0])).name}: код {result.returncode}\n{output[-6000:]}')
    for line in output.splitlines():
        if 'error' in line.lower():
            raise SystemExit(output[-6000:])


def write(path: Path, text: str) -> None:
    if not path.is_file() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8', newline='\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--skip-parts', action='store_true', help='не пересобирать машину и код p2c')
    parser.add_argument('--output', type=Path, default=MACHINE / 'rtype_vdac2.spg',
                        help='отдельный rtype_vdac2.spg для проверки без замены рабочей SPG')
    args = parser.parse_args()
    if args.output.name != 'rtype_vdac2.spg':
        parser.error('имя SPG должно быть rtype_vdac2.spg')
    if args.output.resolve() != (MACHINE / 'rtype_vdac2.spg').resolve() and not args.skip_parts:
        parser.error('изолированная упаковка требует --skip-parts: пересборка частей меняет рабочий Build')
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    if not args.skip_parts:
        for script in ('v30z80_build.py', 'p2c_runtime_z80.py'):
            result = subprocess.run([sys.executable, str(TOOLS / script)], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            lines = [line for line in (result.stdout + result.stderr).splitlines()
                     if 'Warning' not in line and 'warning' not in line]
            if result.returncode:
                print('\n'.join(lines[-40:]))
                return 1
            print(f'{script}: {lines[-1] if lines else ""}', flush=True)
    machine = json.loads((MACHINE / 'build_report.json').read_text(encoding='utf-8'))
    p2c = json.loads((P2C / 'build_report.json').read_text(encoding='utf-8'))
    symbols = machine['symbols']
    video = json.loads((MACHINE / 'video_catalog.json').read_text(encoding='utf-8'))
    loader = json.loads((MACHINE / 'rtype_loader.json').read_text(encoding='utf-8'))
    machine_pages = sorted({machine['res_page'], symbols['HOST_PAGE'] if 'HOST_PAGE' in symbols else 0x0C,
                            machine['sprite_buffer_page'], symbols.get('PRISTINE_RESIDENT', 0x0F)} |
                           set(machine['code_pages']) | {machine['dispatch_base'] + index for index in range(16)} |
                           {machine['v30_page_base'] + index for index in range(64)} | set(video['pages']) |
                           set(loader['pages']) | set(machine.get('sound_pages', [])) |
                           set(machine.get('kernel_pages', [])) | set(machine.get('native_pages', [])) |
                           set(machine.get('host2_pages', [])) | set(machine.get('object_pages', [])) |
                           {symbols.get('PRISTINE_V30_PAGE0', 0x42) + index for index in range(7)})
    p2c_pages = sorted(p2c['pages'])
    overlap = (set(machine_pages) & set(p2c_pages)) | ({SWITCH_PAGE, BOOT_PAGE} & (set(machine_pages) | set(p2c_pages)))
    if overlap:
        raise SystemExit(f'страницы частей пересекаются: {sorted(hex(page) for page in overlap)}')
    # Кэш секторов загрузчика (страницы только времени работы, rtype_loader.py) — вне SPG, загрузчика SPG и всех банков
    # кода p2c #49…#4E (p2c_runtime_z80.BANK_PAGES: заняты по мере роста кода, а не только нынешние).
    cache_overlap = set(loader.get('cache_pages', [])) & (set(machine_pages) | set(p2c_pages) | {SWITCH_PAGE, BOOT_PAGE} |
                                                          set(range(0x49, 0x4F)))
    if cache_overlap:
        raise SystemExit(f'страницы кэша секторов заняты частями SPG: {sorted(hex(page) for page in cache_overlap)}')

    # Страница переключения.
    write(MACHINE / 'rtype_switch.inc', '\n'.join([
        '; Сгенерировано rtype_spg.py: окна машины и кода p2c для страницы переключения.',
        f'RTYPE_A_RESIDENT EQU #{machine["res_page"]:02X}',
        f'RTYPE_A_WORK EQU #{machine["v30_page_base"] + 0x10:02X}',
        f'RTYPE_A_STACK EQU #{symbols["STACK_TOP"]:04X}',
        'RTYPE_A_API EQU #0003',
        f'RTYPE_B_RESIDENT EQU #{p2c["page_resident"]:02X}',
        f'RTYPE_B_DATA1 EQU #{p2c["page_data1"]:02X}',
        f'RTYPE_B_DATA2 EQU #{p2c["page_data2"]:02X}',
        f'RTYPE_B_RETURN EQU #{p2c["switch_return"]:04X}',
        f'RTYPE_BOOT_PAGE EQU #{BOOT_PAGE:02X}', '']))
    run([SJASMPLUS, '--nologo', '--msg=war', f'-i{MACHINE}', ASM / 'rtype_switch.asm', '--raw=' + str(MACHINE / 'rtype_switch.bin'),
         f'--sym={MACHINE / "rtype_switch.sym"}'], cwd=ASM)
    switch = (MACHINE / 'rtype_switch.bin').read_bytes()
    (MACHINE / 'pages').mkdir(exist_ok=True)
    (MACHINE / 'pages' / f'page_{SWITCH_PAGE:02x}.bin').write_bytes(switch + bytes(0x4000 - len(switch)))

    # Содержимое страниц: машина, p2c, переключение.
    contents: dict[int, bytes] = {}
    for page in machine_pages + [SWITCH_PAGE]:
        path = MACHINE / 'pages' / f'page_{page:02x}.bin'
        contents[page] = path.read_bytes() if path.is_file() else bytes(0x4000)
    for page in p2c_pages:
        contents[page] = (P2C / 'pages' / f'page_{page:02x}.bin').read_bytes()
    zero_pages = sorted({page for page, data in contents.items() if not any(data)} | set(p2c['zero_pages']))

    # Релиз (VDAC2+ 2026-09-27, решение пользователя: «SPG → картинка заставки, скролл-бар индикатора загрузки основной
    # игры, автодетект звуковой схемы», «основной код игры превращаем в PAK-файл»). SPG — только загрузчик SPG (страница
    # BOOT_PAGE), страницы загрузчика пака (драйвер FAT32 и его обработчик SD) и заставка; все остальные ненулевые
    # страницы — в RTYPECOD.PAC рядом с паком уровней: загрузчик SPG читает их через DMA SPI→RAM и двигает шкалу BEAM.
    # Код — отдельным файлом, а не разделом RTYPELVL.PAC: новая версия меняет его и SPG, пак уровней (28 МБ) — редко.
    loader_pages = [page for page in loader['pages'] if page in contents and page not in zero_pages]
    pak_pages = [page for page in sorted(contents) if page not in zero_pages and page not in loader_pages]
    # Плоскости заставки (vdac2p_splash.py) лежат в SPG в страницах, которые потом придут из пака: загрузчик SPG
    # отдаёт их в RAM_G через DMA ОЗУ→SPI (процессор их не читает — в кэше TS-Conf нет строк, которые DMA пака потом
    # перепишет), затем читает пак поверх.
    splash_dir = MACHINE / 'splash'
    planes = [('b0', 'SPLASH_B0'), ('b1', 'SPLASH_B1'), ('c0', 'SPLASH_C0'), ('c1', 'SPLASH_C1'), ('beam', '')]
    plane_data = {name: (splash_dir / f'{name}.bin').read_bytes() for name, _ in planes}
    carriers: list[tuple[int, bytes]] = []
    for name, _ in planes:
        data = plane_data[name]
        assert len(data) % 0x4000 == 0, name
        carriers += [(None, data[offset:offset + 0x4000]) for offset in range(0, len(data), 0x4000)]
    if len(carriers) > len(pak_pages):
        raise SystemExit('заставке не хватает страниц-носителей')
    carriers = [(pak_pages[index], data) for index, (_, data) in enumerate(carriers)]
    splash_blocks_dir = MACHINE / 'splash_pages'
    splash_blocks_dir.mkdir(exist_ok=True)
    for page, data in carriers:
        (splash_blocks_dir / f'page_{page:02x}.bin').write_bytes(data)
    pak = bytearray(512)
    pak[0:8] = b'RTYPECOD'
    pak[8:10] = len(pak_pages).to_bytes(2, 'little')
    if 16 + len(pak_pages) > 512:
        raise SystemExit('страниц кода больше, чем помещается в заголовок RTYPECOD.PAC')
    pak[16:16 + len(pak_pages)] = bytes(pak_pages)
    for page in pak_pages:
        pak += contents[page]
    (MACHINE / 'RTYPECOD.PAC').write_bytes(bytes(pak))
    sound = symbols['SOUND_PAGE']
    # Объём звуков, которые загрузчик SPG грузит машиной (вызов 10) под шкалой: секторы сэмплов GS (rtype_gs.inc) и блока
    # эффектов AY (rtype_ay.inc) — доля шкалы на сектор.
    gs_sectors = sum(int(match[1]) for match in re.finditer(r'^\s+DW \d+, (\d+), \d+\s+; сэмпл',
                                                             (MACHINE / 'rtype_gs.inc').read_text(encoding='utf-8'), re.M))
    ay_sectors = int(re.search(r'^AY_DATA_SECTORS\s+EQU (\d+)', (MACHINE / 'rtype_ay.inc').read_text(encoding='utf-8'),
                               re.M)[1])
    if not gs_sectors:
        raise SystemExit('rtype_gs.inc: не найдены сэмплы')
    lines = ['; Сгенерировано rtype_spg.py: вход кода p2c, нулевые страницы и код игры в RTYPECOD.PAC для загрузчика SPG.',
             f'RTYPE_B_START EQU #{p2c["entry"]:04X}',
             f'RTYPE_B_RESIDENT EQU #{p2c["page_resident"]:02X}',
             f'RTYPE_B_DATA2 EQU #{p2c["page_data2"]:02X}',
             f'RTYPE_B_FIRST_BANK EQU #{p2c["first_bank"]:02X}',
             f'CODE_PAK_SIZE EQU {len(pak)}                ; RTYPECOD.PAC: поиск на карте по имени и размеру',
             f'CODE_PAGE_COUNT EQU {len(pak_pages)}',
             f'ZERO_PAGE_COUNT EQU {len(zero_pages)}',
             f'SOUND_PAGE_NUMBER EQU #{sound:02X}',
             f'GS_DETECTED_AT EQU #{symbols["GS_DETECTED"]:04X}         ; решение о плате GS — передать игре',
             f'GS_PRESENT_AT EQU #{symbols["GS_PRESENT"]:04X}',
             f'LOADER_PAGE_NUMBER EQU #{loader["loader_page"]:02X}',
             f'RTYPE_SWITCH_PAGE EQU #{SWITCH_PAGE:02X}',
             f'RTYPE_BOOT_CALL EQU #{BOOT_CALL:04X}           ; вызов машины из загрузчика SPG (rtype_switch.asm)',
             f'GS_SECTORS_TOTAL EQU {gs_sectors}             ; секторов сэмплов GS',
             f'AY_SECTORS_TOTAL EQU {ay_sectors}             ; секторов блока эффектов AY',
             '; Страницы-носители заставки: плоскости b0, b1, c0, c1 и шкалы — в RAM_G подряд с адреса 0, по 16 КБ.',
             '                MACRO SPLASH_PAGE_LIST',
             f'                DB {", ".join(f"#{page:02X}" for page, _ in carriers)}',
             '                ENDM',
             '                MACRO CODE_PAGE_LIST']
    lines += [f'                DB {", ".join(f"#{page:02X}" for page in pak_pages[start:start + 16])}'
              for start in range(0, len(pak_pages), 16)]
    lines += ['                ENDM', '                MACRO RTYPE_ZERO_PAGE_LIST']
    lines += [f'                DB {", ".join(f"#{page:02X}" for page in zero_pages[start:start + 16])}'
              for start in range(0, len(zero_pages), 16)]
    lines += ['                DB 0', '                ENDM', '']
    write(MACHINE / 'rtype_boot.inc', '\n'.join(lines))
    run([SJASMPLUS, '--nologo', '--msg=war', ASM / 'rtype_boot.asm', '--syntax=ab', f'--sym={MACHINE / "rtype_boot.sym"}'],
        cwd=ASM)
    blocks = [f'Block = #5000, #{BOOT_PAGE:02X}, {(MACHINE / "rtype_boot.bin").relative_to(ROOT).as_posix()}']
    for page in loader_pages:
        blocks.append(f'Block = #0000, #{page:02X}, {(MACHINE / "pages" / f"page_{page:02x}.bin").relative_to(ROOT).as_posix()}')
    for page, _ in carriers:
        blocks.append(f'Block = #0000, #{page:02X}, {(splash_blocks_dir / f"page_{page:02x}.bin").relative_to(ROOT).as_posix()}')
    ini = ['Desc = R-Type (World ROM V30 -> Z80, app.main p2c)', 'Start = 0x5000', 'Stack = 0x3FFF',
           'Resident = 0x4F00', 'Page3 = 0', 'Clock = 2', 'INT = 0', 'Pager = 0', 'Compression = 0', ''] + blocks
    write(MACHINE / 'rtype_spg.ini', '\n'.join(ini) + '\n')
    spg_path = args.output.resolve()
    spg_path.parent.mkdir(parents=True, exist_ok=True)
    run([SPGBLD, '-b', MACHINE / 'rtype_spg.ini', spg_path], cwd=ROOT)
    spg = spg_path.read_bytes()
    report = {'machine_pages': machine_pages, 'p2c_pages': p2c_pages, 'switch_page': SWITCH_PAGE,
              'zero_pages': zero_pages, 'blocks': len(blocks), 'spg_sha256': hashlib.sha256(spg).hexdigest(),
              'loader_pages': loader_pages, 'code_pak_pages': pak_pages, 'code_pak_size': len(pak),
              'code_pak_sha256': hashlib.sha256(pak).hexdigest(), 'splash_pages': [page for page, _ in carriers]}
    write(spg_path.parent / 'rtype_spg.json', json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    print(f'SPG: {spg_path} {len(spg)} байт, блоков {len(blocks)}, нулевых страниц {len(zero_pages)}, '
          f'SHA-256 {report["spg_sha256"][:16]}; RTYPECOD.PAC {len(pak)} байт, страниц {len(pak_pages)}, '
          f'SHA-256 {report["code_pak_sha256"][:16]}, {time.perf_counter() - started:.0f} с')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
