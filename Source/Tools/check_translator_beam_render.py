"""Выпуск BEAM: целые Game.update/render против кода SPG и его ресурсов.

Проверка не использует проекцию генератора в качестве эталона. Интро пропущено
только в начальном состоянии, как в ограниченной демо; дальнейшие кадры Python
исполняются целиком. Бессмертие включается только у проверочного экземпляра.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import logging
import re
import struct

from check_translator_demo import BUILD, ROOT, StrictDemoMachine, parse_sym
import pygame
from PIL import Image, ImageDraw
from rtype_port import game
from sim_frame_png import DLRenderer


class Capture(pygame.Surface):
    """Настоящая поверхность pygame, записывающая интересующие нас blit."""

    def __init__(self, resources):
        super().__init__((640, 480))
        self.resources = resources
        self.jobs = []

    def blit(self, source, dest, *args, **kwargs):
        name = self.resources.get(id(source))
        if name is not None:
            self.jobs.append((name, int(dest[0]), int(dest[1])))
        return super().blit(source, dest, *args, **kwargs)


class BeamRenderer(DLRenderer):
    """Только выбранные битмапы; все настройки читает из настоящего DL."""

    def __init__(self, blob, sources):
        super().__init__(blob)
        self.sources = sources
        self.jobs = []

    def draw_bitmap(self, x, y):
        if self.bmp_source in self.sources:
            self.jobs.append((self.sources[self.bmp_source], x, y))
            super().draw_bitmap(x, y)


def resources(player):
    result = {}
    for prefix, images in (('PITCH', player.player_images),
                           ('CHARGE', player.charge_images),
                           ('RELEASE', player.wave_release_images)):
        result.update((prefix + str(i), image) for i, image in enumerate(images))
    for power, images in player.wave_images.items():
        result.update((f'WAVE{power}_{i}', image) for i, image in enumerate(images))
    return result


def packed(surface):
    raw = pygame.image.tobytes(surface, 'RGBA')
    return b''.join(struct.pack('<H', (a >> 4) << 12 | (r >> 4) << 8 |
                                (g >> 4) << 4 | (b >> 4))
                    for r, g, b, a in zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-ft', action='store_true', help='Также снять кадры через DLL настоящего эмулятора FT812')
    args = parser.parse_args()
    logging.getLogger().setLevel(logging.ERROR)
    pygame.init()
    pygame.display.set_mode((1, 1))
    report = json.loads((BUILD / 'build_report.json').read_text(encoding='utf-8'))
    sealed = hashlib.sha256((BUILD / 'rtype_vdac2.spg').read_bytes()).hexdigest()
    assert sealed == report['spg_sha256']
    assets = report['assets']
    blob = (BUILD / 'graphics.bin').read_bytes()
    output = BUILD / 'BeamCheck'
    output.mkdir(exist_ok=True)
    sym = parse_sym(BUILD / 'demo.sym')
    sym.update({name: int(address, 16) for address, name in re.findall(
        r'^\s*([0-9A-Fa-f]{8})\s+_(\w+)\b',
        (BUILD / 'demo.map').read_text(encoding='latin1'), re.M)})
    machine = StrictDemoMachine(ROOT, spgbld_path=BUILD / 'demo.ini',
                                sym_path=BUILD / 'demo.sym', load_spg=True)
    machine.mem.pages[:] = [0, 5, 0x30, 6]
    machine.reg.SP = 0x3fff
    machine.fmaddr_enabled = True
    machine.mem.write_block_linear(0x3c00, b'\xa5' * 0x3f0)
    # Начальные координаты — входные условия теста, не поправки к BEAM.
    cases = ((12, 233, 192, 0), (24, 233, 192, 4), (36, 233, 192, 8),
             (48, 233, 192, 1), (64, 233, 192, 2),
             (64, 0, 0, 0), (64, 587, 422, 0))
    checked = 0
    powers, pitches, charge_phases, release_phases = set(), set(), set(), set()
    samples, records = [], []
    for case, (hold, x, y, direction) in enumerate(cases):
        player = game.Game()
        player.intro_frame = game.INTRO_FRAMES
        player.lifecycle.invulnerability = 0xffff
        player.player_x, player.player_y = x * game.Q8, y * game.Q8
        machine.mem.pages[2] = 0x30
        machine.mem.write_block_linear(0x2100, bytes(6))
        machine.call(sym['Demo_Init'])
        machine.mem.write_block_linear(sym['player'], struct.pack('<ii', player.player_x, player.player_y))
        images = resources(player)
        sizes = {}
        sources = {}
        for name, image in images.items():
            source, width, height = assets['bitmaps'][assets['image_ids'][name]]
            assert image.get_size() == (width, height), (name, 'размер ресурса')
            assert blob[source:source + width * height * 2] == packed(image), (name, 'пиксели ресурса')
            sources[source] = name
            sizes[name] = width, height
        capture = Capture({id(image): name for name, image in images.items()})
        for tick in range(1, hold + 13):
            flags = direction | (16 if tick <= hold else 0)
            inputs = game.InputState(*(bool(flags & bit) for bit in (1, 2, 4, 8, 16)))
            player.update(inputs)
            machine.mem.pages[2] = 0x30
            machine.mem.write_block_linear(0x2100, struct.pack('<BBHH', flags, 0, 0, 0))
            machine.call(sym['Demo_Tick'])
            expected = tuple(int(getattr(player, field)) for field in (
                'player_x', 'player_y', 'player_pitch', 'fire_held', 'wave_charge', 'pending_shot_spawn'))
            actual = struct.unpack('<6i', machine.get_memory(sym['player'], 24))
            assert actual == expected, (case, tick, 'player', actual, expected)
            actual = struct.unpack('<9i', machine.get_memory(sym['wave'], 36))
            expected_wave = None if player.wave is None else tuple(getattr(player.wave, field) for field in (
                'x', 'y', 'release_x', 'release_y', 'power', 'delay', 'animation', 'render_power'))
            assert (actual[:8] if actual[8] else None) == expected_wave, (case, tick, 'wave', actual, expected_wave)
            capture.jobs.clear()
            player.render(capture)
            expected_jobs = [(name, px * 64 // 5, py * 64 // 5)
                             for name, px, py in capture.jobs
                             if px < 640 and py < 480 and px + sizes[name][0] > 0 and py + sizes[name][1] > 0]
            machine.mem.pages[2] = 0x32
            machine.call(sym['Demo_Render'])
            renderer = BeamRenderer(blob, sources)
            renderer.run(machine.get_memory(0x1000, machine.get_word(sym['demo_dl_bytes'])))
            assert renderer.jobs == expected_jobs, (case, tick, 'blit', renderer.jobs, expected_jobs)
            assert machine.get_byte(sym['demo_fault']) == 0, (case, tick, 'fault')
            assert machine.reg.SP == 0x3fff and machine.get_byte(0x3c00) == 0xa5
            checked += 1
            for name, _, _ in capture.jobs:
                if name.startswith('PITCH'): pitches.add(int(name[5:]))
                if name.startswith('CHARGE'): charge_phases.add(int(name[6:]))
                if name.startswith('RELEASE'): release_phases.add(int(name[7:]))
            if player.wave is not None:
                powers.add(player.wave.render_power)
                records.append(dict(case=case, tick=tick, wave=list(expected_wave), jobs=expected_jobs))
                if case == 4 and player.wave.delay == 0 and player.wave.animation in (0, 1, 4):
                    logical = pygame.Surface((640, 480))
                    logical.fill('black')
                    for name, px, py in capture.jobs:
                        logical.blit(images[name], (px, py))
                    original = Image.frombytes('RGB', (640, 480), pygame.image.tobytes(logical, 'RGB'))
                    display_list = machine.get_memory(0x1000, machine.get_word(sym['demo_dl_bytes']))
                    samples.append((player.wave.animation, original, renderer.img, display_list))
                    (output / f'animation_{player.wave.animation}.dl').write_bytes(display_list)
                    original.save(output / f'python_animation_{player.wave.animation}.png')
        print(f'{case + 1}/{len(cases)}: целые Game.update/render, выпуск и ресурсы совпадают', flush=True)
    assert powers == set(game.WAVE_POWER_TABLE[1:]), powers
    assert pitches == set(range(5)), pitches
    assert charge_phases == set(range(8)), charge_phases
    assert release_phases == set(range(4)), release_phases
    assert hashlib.sha256((BUILD / 'rtype_vdac2.spg').read_bytes()).hexdigest() == sealed
    native = None
    if args.native_ft:
        from ft812_offscreen import FT812Offscreen
        device = FT812Offscreen()
        try:
            device.write(0, blob)
            for animation, original, translated, display_list in samples:
                frame = device.render(display_list)
                assert frame.size == (1024, 768), frame.size
                frame.save(output / f'ft812_animation_{animation}.png')
            native = dict(library=str(device.library), library_sha256=device.library_sha256,
                          frames=len(samples), messages=device.messages)
            assert not any(kind == 0 for kind, message in device.messages), device.messages
        finally:
            device.close()
    # Сравнение геометрии: слева pygame, справа DL-модель с квантованием ARGB4444.
    sheet = Image.new('RGB', (1024, len(samples) * 156), '#202020')
    draw = ImageDraw.Draw(sheet)
    for row, (animation, original, translated, display_list) in enumerate(samples):
        draw.text((8, row * 156 + 5), f'Python Game.render | animation={animation}', fill='white')
        draw.text((520, row * 156 + 5), 'SDCC/Z80 -> ' + ('bt8xxemu' if native else 'FT DL model'), fill='white')
        if native:
            translated = Image.open(output / f'ft812_animation_{animation}.png').convert('RGB')
        original = original.resize((1024, 768), Image.Resampling.NEAREST)
        box = (480, 270, 992, 400)
        sheet.paste(original.crop(box), (0, row * 156 + 24))
        sheet.paste(translated.crop(box), (512, row * 156 + 24))
    sheet.save(output / 'beam_compare.png')
    result = dict(spg_sha256=sealed, frames=checked, full_source_update_render=True,
                  initial_intro_skipped=True, initial_invulnerability=0xffff,
                  powers=sorted(powers), pitches=sorted(pitches), charge_phases=sorted(charge_phases),
                  release_phases=sorted(release_phases), state_mismatches=0, vertex_mismatches=0,
                  resource_mismatches=0, native_ft_capture=native, full_native_game_checked=False, records=records)
    (output / 'beam_check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({k: v for k, v in result.items() if k != 'records'}, flush=True)
    pygame.quit()


if __name__ == '__main__':
    main()
