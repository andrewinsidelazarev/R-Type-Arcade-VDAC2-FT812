"""Проверка SPG транслированного Stage в модели Z80 + TS-Config + FT812.

Загрузка SPG, выгрузка атласов в RAM_G, затем покадровое исполнение: display
list, который Z80 отдал в RAM_DL, разбирается обратно в команды тайлов и
сравнивается с выводом объекта Stage в CPython для того же кадра; поля Stage и
обе VRAM читаются из памяти Z80 и сравниваются с CPython. Замеряются такты.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import statistics
import struct
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

from py2c.ctypes_model import BoolType, IntType, OptionalIntType  # noqa: E402
from py2c.heap import Heap  # noqa: E402
from py2c.program import Program  # noqa: E402
from py2c.translate import Translator  # noqa: E402
from py2c.z80module import build_z80_module  # noqa: E402
from py2c_stage_spg import BUILD, FIRST_DATA_PAGE, ROOTS, symbol_address  # noqa: E402
from sim_boot_check import TSConfFT812Machine, parse_sym  # noqa: E402


class StrictMachine(TSConfFT812Machine):
    """HALT завершается только входом в разрешённый IM2-обработчик кадра."""
    irq_mask = 0

    def _write_ref(self, ref, value):
        if ref == 0x042A and self.fmaddr_enabled:
            self.irq_mask = value
        return super()._write_ref(ref, value)

    def _write_tsconf_register(self, reg, value):
        if reg == 0x2A:
            self.irq_mask = value
        return super()._write_tsconf_register(reg, value)

    def run_until_pc(self, pc, max_steps=50_000_000):
        for _ in range(max_steps):
            if self.reg.PC == pc:
                return
            if self.mem.read(self.reg.PC) == 0x76:
                if not self.reg.IFF or not (self.irq_mask & 1) or self.reg.IM != 2:
                    raise RuntimeError(f'необратимый HALT на #{self.reg.PC:04X}')
                resume = (self.reg.PC + 1) & 0xFFFF
                self.reg.SP = (self.reg.SP - 2) & 0xFFFF
                self.mem.write(self.reg.SP, resume & 0xFF)
                self.mem.write((self.reg.SP + 1) & 0xFFFF, resume >> 8)
                vector = (self.reg.I << 8) | 0xFF
                self.reg.PC = self.mem.read(vector) | (self.mem.read((vector + 1) & 0xFFFF) << 8)
                self.reg.IFF = False
                self.reg.IFF2 = False
            else:
                self.step()
        raise TimeoutError(f'PC=#{self.reg.PC:04X}, ожидался #{pc:04X}')


FIELD_SIZE = {'i32': 4, 'u32': 4, 'i16': 2, 'u16': 2, 'i8': 1, 'u8': 1}


def field_layout(heap: Heap, class_name: str) -> dict[str, tuple[int, object]]:
    """Смещения полей структуры SDCC: подряд, без выравнивания, указатель 2 байта."""
    offset = 0
    result = {}
    for name, field_type in heap.fields[class_name].items():
        result[name] = (offset, field_type)
        if isinstance(field_type, IntType):
            offset += field_type.bits // 8
        elif isinstance(field_type, BoolType):
            offset += 1
        elif isinstance(field_type, OptionalIntType):
            offset += 5
        else:
            offset += 2
    return result


def expected_commands(blits):
    """Модель адаптера FT812: номер изображения кодирует handle/cell/чёрный/не загружено."""
    commands = []
    colored = False
    for image, x, y in blits:
        if image & 0x8000:
            continue
        if not colored:
            if image & 0x4000:
                continue
            colored = True
        if not (-16 <= x < 704 and 0 <= y < 480):
            continue
        commands.append(((image >> 8) & 0x1F, image & 0x7F, (x * 64) // 5 + 256, (y * 64) // 5))
    return commands


def decode_dl(data: bytes):
    """Команды тайлов из display list: (handle, cell, x, y) каждой VERTEX2F после BEGIN."""
    words = struct.unpack(f'<{len(data) // 4}I', data)
    handle = cell = 0
    tiles = []
    setup_done = False
    for word in words:
        opcode = word >> 24
        if word == 0:
            break
        if (word >> 30) == 1:
            tiles.append((handle, cell, (word >> 15) & 0x7FFF, word & 0x7FFF))
        elif opcode == 0x05:
            handle = word & 0xFF
        elif opcode == 0x06:
            cell = word & 0x7F
        elif opcode == 0x01:
            setup_done = True
    return tiles, setup_done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=12)
    parser.add_argument('--skip', type=int, default=0, help='кадров без сравнения вывода перед проверкой')
    parser.add_argument('--profile', action='store_true', help='такты по функциям (символы карты SDCC)')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    logging.getLogger().setLevel(logging.ERROR)
    pygame.init()
    pygame.display.set_mode((64, 64))
    from rtype_port.stage import Stage
    stage = Stage()
    program = Program('rtype_port', ['stage'])
    heap = Heap(program, {'stage': stage}, external_threshold=256)
    translator = Translator(program, heap)
    translator.translate([(c, m) for c, methods in ROOTS.values() for m in methods])
    from py2c_stage_spg import resources
    _header, _blob, _manifest, image_ids = resources(stage, 0)
    module = build_z80_module(translator, heap, ROOTS, FIRST_DATA_PAGE, 'py2c_stage', image_ids)
    if module.source != (BUILD / 'py2c_stage.c').read_text(encoding='utf-8'):
        raise SystemExit('сгенерированный C проверки отличается от собранного SPG: пересобрать')
    report_build = json.loads((BUILD / 'build_report.json').read_text(encoding='utf-8'))
    emitter = module.emitter
    symbols_c = report_build['symbols']
    boot = parse_sym(BUILD / 'boot.sym')
    machine = StrictMachine(ROOT, spgbld_path=BUILD / 'stage.ini', load_spg=True,
                            default_start='0x5000', default_stack='0x3FFF')
    if machine.errors:
        raise SystemExit(f'ошибки загрузки: {machine.errors}')
    machine.run_until_pc(boot['MainLoop'])
    graphics = (BUILD / 'graphics.bin').read_bytes()
    if bytes(machine.ft.ram_g[:len(graphics)]) != graphics:
        raise SystemExit('RAM_G отличается от атласов сборки')
    print(f'загрузка: RAM_G {len(graphics)} байт совпадает, тактов {machine.tstates}', flush=True)

    root_symbol = module.manifest['root_symbols']['stage']
    root_address = symbol_address((BUILD / 'stage.map').read_text(encoding='latin1'), root_symbol)
    stage_layout = field_layout(heap, 'Stage')
    scroll_layout = field_layout(heap, 'M72Scroll')
    placements = {item.symbol: item for item in module.placements}

    def read_int(address: int, field_type) -> int:
        if isinstance(field_type, BoolType):
            return machine.get_byte(address)
        size = field_type.bits // 8
        return int.from_bytes(machine.get_memory(address, size), 'little', signed=field_type.signed)

    profile: dict[str, int] = {}
    if args.profile:
        import bisect
        import re as re_module
        map_text = (BUILD / 'stage.map').read_text(encoding='latin1')
        entries = sorted({(int(address, 16), name) for address, name in
                          re_module.findall(r'^\s+([0-9A-Fa-f]{8})\s+(_\w+)', map_text, re_module.M)
                          if int(address, 16) >= 0x4000})
        starts = [address for address, _ in entries]
        original_step = machine.step

        def profiled_step():
            pc = machine.reg.PC
            spent = original_step()
            position = bisect.bisect_right(starts, pc) - 1
            name = entries[position][1] if position >= 0 else '?'
            if pc < 0x6000 and pc >= 0x5000:
                name = 'boot/TSLib'
            profile[name] = profile.get(name, 0) + spent
            return spent
        machine.step = profiled_step
    frame_tstates = []
    dl_sizes = []
    compared = 0
    for frame in range(1, args.frames + 1):
        before = machine.tstates
        machine.step()
        machine.run_until_pc(boot['MainLoop'])
        frame_tstates.append(machine.tstates - before)
        if machine.get_byte(symbols_c['py2c_fault']):
            code = int.from_bytes(machine.get_memory(symbols_c['py2c_fault_code'], 2), 'little', signed=True)
            raise SystemExit(f'отказ Z80 на кадре {frame}: код {code}')
        if machine.get_byte(0x3C00) != 0xA5:
            raise SystemExit(f'стек пробил сторожевой байт на кадре {frame}')
        stage.update()
        dl_bytes = machine.get_word(symbols_c['py2c_dl_bytes'])
        dl_sizes.append(dl_bytes)
        if frame > args.skip:
            recorder = []

            class Target:
                @staticmethod
                def blit(surface, position):
                    recorder.append((image_ids.get(id(surface), 0xFFFF), position[0], position[1]))
            stage.draw_back(Target)
            stage.draw_front(Target)
            expected = expected_commands(recorder)
            actual, _ = decode_dl(bytes(machine.ft.ram_dl[:dl_bytes]))
            if expected[:len(actual)] != actual or len(actual) != min(len(expected), len(actual)):
                index = next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
                             min(len(expected), len(actual)))
                raise SystemExit(f'вывод Z80 расходится с CPython на кадре {frame}: тайл {index} '
                                 f'ожидался {expected[index:index + 1]} получен {actual[index:index + 1]}; '
                                 f'длины {len(expected)}/{len(actual)}')
            if len(actual) != len(expected):
                raise SystemExit(f'кадр {frame}: тайлов {len(actual)} из {len(expected)} (переполнение DL)')
            compared += 1
        # Поля Stage/M72Scroll и VRAM из памяти Z80 против CPython.
        for name in ('frame', 'section_index'):
            offset, field_type = stage_layout[name]
            value = read_int(root_address + offset, field_type)
            if value != getattr(stage, name):
                raise SystemExit(f'Stage.{name}: Z80 {value}, CPython {getattr(stage, name)} (кадр {frame})')
        scroll_pointer = machine.get_word(root_address + stage_layout['m72_scroll'][0])
        for name, (offset, field_type) in scroll_layout.items():
            if isinstance(field_type, OptionalIntType):
                continue
            value = read_int(scroll_pointer + offset, field_type)
            if value != int(getattr(stage.m72_scroll, name)):
                raise SystemExit(f'M72Scroll.{name}: Z80 {value}, CPython {getattr(stage.m72_scroll, name)} (кадр {frame})')
        for layer in range(2):
            symbol = emitter.symbols[id(stage.tilemaps.vram[layer])]
            placement = placements[symbol]
            vram = machine.mem.read_physical(placement.page, placement.offset, 0x4000)
            if vram != bytes(stage.tilemaps.vram[layer]):
                raise SystemExit(f'VRAM слоя {layer} расходится на кадре {frame}')
        print(f'кадр {frame}: совпадает; тактов {frame_tstates[-1]}, DL {dl_bytes} байт', flush=True)

    report = {
        'frames': args.frames, 'compared_frames': compared,
        'tstates_min': min(frame_tstates), 'tstates_median': statistics.median(frame_tstates),
        'tstates_max': max(frame_tstates), 'dl_bytes_max': max(dl_sizes),
        'dl_peak_commands': machine.get_word(symbols_c['py2c_dl_peak']),
        'spg_sha256': hashlib.sha256((BUILD / 'rtype_vdac2.spg').read_bytes()).hexdigest(),
        'result': 'identical',
    }
    if profile:
        total = sum(profile.values())
        report['profile_top'] = [(name, spent, round(100 * spent / total, 1))
                                 for name, spent in sorted(profile.items(), key=lambda item: -item[1])[:25]]
        for name, spent, share in report['profile_top']:
            print(f'{share:5.1f}%  {spent:9d}  {name}')
    (BUILD / 'z80_check.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
