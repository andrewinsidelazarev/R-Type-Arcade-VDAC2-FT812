"""Звук переведённой программы World ROM: потоки TurboSound FM (мелодии $00…$2F) — раздел 2 пака
RTYPELVL.PAC, таблицы адаптера — Build/V30Z80/rtype_sound.inc.

Логика команд берётся из rtype_port.audio (TurboSoundFm): таблица на 48 команд — вид (пропуск, затухание
владельца, замена владельца, мелодия), поток и повтор; порядок проверок как в TurboSoundFm.command
(пропуск, затухание, замена, поток). Потоки — файлы MUSIC_STREAMS и REPLACE_STREAM без изменений (формат
TsfmMusic_Update: [пауза][число записей]([чип][регистр][значение])…, $FE — продолжение с начала
следующей страницы 16 КБ, $FF $00 — конец); в паке каждый поток начинается с сектора. Раздел ячеек пака
(заголовок, индекс, ячейки — rtype_data.py) не пересобирается: берётся из готового пака, звуковые
разделы дописываются заново.

Затухание эталона — усиление PCM fade/FADE_FRAMES; на железе TSFM общего усиления нет: отступление на
аппаратном пределе — ослабление несущих операторов YM2203 на round(−20·lg(усиление)/0.75) шагов TL.

Эталон начинает каждый поток на новых чипах; адаптер (v30z80_sound.asm) сбросить YM2203 не может и
глушит операторы (TL = 127, SL/RR = #0F, снятие нот), громкости SSG A/B/C и обнуляет SSG-EG. Это совпадает с
новыми чипами, если потоки (проверка check_stream): у каждого нажатого оператора с ненулевой скоростью атаки
до нажатия записаны DT/MUL, TL, KS/AR, DR, SR, SL/RR, F-Num, блок и алгоритм канала; у нажатого оператора
без атаки (у нового чипа он молчит) не записан TL — тогда TL = 127 его тоже глушит; SSG-часть (бас,
rtype_port.tsfm_bass) до первой ненулевой громкости канала записала микшер, период тона (если тон канала
включён), период шума (если включён шум) и, у громкости с огибающей, период и форму огибающей.

Затухание баса в SSG-части — таблицы SSG_VOL_ATT/SSG_VOL_MID и порог SSG_ENV_KEEP (tsfm_bass.ssg_fade_tables).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

BUILD = ROOT / 'Build' / 'V30Z80'
PACK = BUILD / 'RTYPELVL.PAC'
SECTOR = 512
PAGE = 0x4000
TRACK_PAGES = 7                         # буфер потока адаптера: страницы SOUND_PAGE+1…
KIND_NONE, KIND_FADE, KIND_REPLACE, KIND_MUSIC = 0, 1, 2, 3
# Слоты регистров оператора: бит нажатия в #28 → смещение регистра (#40 — оператор 1, #44 — 3, #48 — 2,
# #4C — 4).
KEY_SLOTS = ((0x10, 0x0), (0x20, 0x8), (0x40, 0x4), (0x80, 0xC))


def check_stream(path: Path, events: dict[int, tuple[tuple[int, int, int], ...]]) -> None:
    """Свойства потока, при которых тишина адаптера вместо новых чипов звучит так же (см. описание)."""
    written: dict[tuple[int, int], int] = {}
    for frame in sorted(events):
        for chip, register, value in events[frame]:
            if register < 0x10:
                # SSG-часть: бас (rtype_port.tsfm_bass); MusicSilence глушит только громкости
                if 0x08 <= register <= 0x0A and value & 0x1F:
                    channel = register - 0x08
                    need = [0x07]
                    mixer = written.get((chip, 0x07), 0x3F)
                    if not mixer & (1 << channel):
                        need += [channel * 2, channel * 2 + 1]
                    if not mixer & (8 << channel):
                        need.append(0x06)
                    if value & 0x10:
                        need += [0x0B, 0x0C, 0x0D]
                    lack = [f'${item:02X}' for item in need if (chip, item) not in written]
                    if lack:
                        raise SystemExit(f'{path.name}: кадр {frame}, чип {chip}: громкость SSG канала {channel} '
                                         f'до записи {", ".join(lack)}')
                written[(chip, register)] = value
                continue
            if register == 0x28 and value & 0xF0 and value & 3 < 3:
                channel = value & 3
                for bit, offset in KEY_SLOTS:
                    if not value & bit:
                        continue
                    attack = written.get((chip, 0x50 + offset + channel), 0) & 0x1F
                    if attack:
                        need = [base + offset + channel for base in (0x30, 0x40, 0x50, 0x60, 0x70, 0x80)]
                        need += [0xA0 + channel, 0xA4 + channel, 0xB0 + channel]
                        lack = [f'${item:02X}' for item in need if (chip, item) not in written]
                        if lack:
                            raise SystemExit(f'{path.name}: кадр {frame}, чип {chip}: нота оператора ${offset:X} '
                                             f'канала {channel} до записи {", ".join(lack)}')
                    elif (chip, 0x40 + offset + channel) in written:
                        raise SystemExit(f'{path.name}: кадр {frame}, чип {chip}: оператор ${offset:X} канала '
                                         f'{channel} без атаки с записанным TL')
            written[(chip, register)] = value


def command_table(audio) -> tuple[list[tuple[int, int, bool]], list[Path]]:
    """[(вид, поток, повтор)] на команды 0…47 и список файлов потоков (номер — индекс)."""
    streams: list[Path] = []

    def stream_index(path: Path) -> int:
        if path not in streams:
            streams.append(path)
        return streams.index(path)

    table = []
    for command in range(0x30):
        if command in audio.NOOP_COMMANDS:
            table.append((KIND_NONE, 0, False))
        elif command in audio.FADE_COMMANDS:
            table.append((KIND_FADE, 0, False))
        elif command in audio.REPLACE_COMMANDS:
            table.append((KIND_REPLACE, stream_index(audio.REPLACE_STREAM), False))
        else:
            path = audio.MUSIC_STREAMS.get(command)
            if path is None or not path.is_file():
                table.append((KIND_NONE, 0, False))
            else:
                table.append((KIND_MUSIC, stream_index(path), command not in audio.ONE_SHOT_COMMANDS))
    return table, streams


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    from rtype_port import audio, tsfm, tsfm_bass

    table, streams = command_table(audio)
    pack = bytearray(PACK.read_bytes())
    if pack[0:8] != b'RTYPEDAT':
        raise SystemExit(f'{PACK}: не пак RTYPEDAT')
    count = struct.unpack_from('<H', pack, 10)[0]
    sections = [struct.unpack_from('<II', pack, 12 + number * 8) for number in range(count)]
    cells_end = sections[1][0] + sections[1][1]
    body = bytearray(pack[:cells_end * SECTOR])
    music_first = cells_end
    locations = []
    for path in streams:
        # Перенос баса в SSG-часть — тем же преобразованием, что у эталона (rtype_port.tsfm_bass); с 2026-09-17
        # выключен (BASS_TO_SSG = False): поток не меняется, бас на FM, как у аркады.
        data = tsfm_bass.move_bass_to_ssg(path.read_bytes())
        if len(data) > TRACK_PAGES * PAGE:
            raise SystemExit(f'{path.name}: {len(data)} байт — больше {TRACK_PAGES} страниц буфера мелодии')
        events, frames = tsfm.decode_stream(data)
        if frames > 0xFFFF:
            raise SystemExit(f'{path.name}: {frames} кадров — счётчик адаптера 16-битный')
        check_stream(path, events)
        first = len(body) // SECTOR
        body += data + bytes((-len(data)) % SECTOR)
        locations.append((first, (len(data) + SECTOR - 1) // SECTOR, len(data), frames))
    music_sectors = len(body) // SECTOR - music_first
    total = len(body) // SECTOR
    new_sections = [sections[0], sections[1], (music_first, music_sectors), (total, 0)]
    struct.pack_into('<HH', body, 8, struct.unpack_from('<H', pack, 8)[0], len(new_sections))
    for number, (first, sectors) in enumerate(new_sections):
        struct.pack_into('<II', body, 12 + number * 8, first, sectors)
    struct.pack_into('<I', body, 44, total)
    if total > 0xFFFF:
        raise SystemExit('пак длиннее 65535 секторов: номер сектора файла у загрузчика — слово')
    PACK.write_bytes(bytes(body))
    report_path = BUILD / 'rtype_data.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    report.update(size=len(body), sectors=total, sha256=hashlib.sha256(body).hexdigest(),
                  sections={'index': new_sections[0], 'cells': new_sections[1], 'music': new_sections[2],
                            'effects': new_sections[3]},
                  music=[{'file': path.name, 'sector': first, 'sectors': sectors, 'bytes': size, 'frames': frames}
                         for path, (first, sectors, size, frames) in zip(streams, locations)])
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    fade = [0] + [min(127, round(-20 * math.log10(remaining / audio.FADE_FRAMES) / 0.75))
                  for remaining in range(1, audio.FADE_FRAMES + 1)]
    lines = [
        '; Сгенерировано rtype_sound.py: команды мелодий (rtype_port.audio.TurboSoundFm) и потоки TSFM в паке.',
        f'MUSIC_KIND_NONE EQU {KIND_NONE}', f'MUSIC_KIND_FADE EQU {KIND_FADE}',
        f'MUSIC_KIND_REPLACE EQU {KIND_REPLACE}', f'MUSIC_KIND_MUSIC EQU {KIND_MUSIC}',
        f'MUSIC_FADE_FRAMES EQU {audio.FADE_FRAMES}', f'MUSIC_STREAM_COUNT EQU {len(streams)}',
        f'MUSIC_TRACK_PAGES EQU {TRACK_PAGES}',
        '; Команда $00…$2F: вид, поток (бит 7 — повтор).',
        'MUSIC_TABLE:']
    for command, (kind, stream, loop) in enumerate(table):
        lines.append(f'                DB {kind}, #{stream | (0x80 if loop else 0):02X}          ; ${command:02X}')
    lines.append('; Поток: первый сектор файла пака, секторов, кадров (tsfm.decode_stream: сумма пауз + 1).')
    lines.append('MUSIC_STREAMS:')
    for path, (first, sectors, size, frames) in zip(streams, locations):
        lines.append(f'                DW {first}, {sectors}, {frames}          ; {path.name}, {size} байт')
    lines.append('; Ослабление несущих операторов (шагов TL) при оставшихся кадрах затухания 0…FADE_FRAMES.')
    lines.append('MUSIC_FADE_ATT:')
    for start in range(0, len(fade), 16):
        lines.append('                DB ' + ', '.join(str(value) for value in fade[start:start + 16]))
    ssg = tsfm_bass.ssg_fade_tables()
    lines += [
        '; Затухание баса в SSG-части (tsfm_bass.ssg_fade_tables, шаги TL по 0.75 дБ): ослабление громкости 0…15',
        '; относительно 15 и порог спуска с громкости v на v − 1.',
        'SSG_VOL_ATT:    DB ' + ', '.join(str(value) for value in ssg['vol_att']),
        'SSG_VOL_MID:    DB ' + ', '.join(str(value) for value in ssg['vol_mid']),
        '; Голос с огибающей звучит как есть до этого ослабления (6 дБ), дальше молчит.',
        f"SSG_ENV_KEEP    EQU {ssg['env_keep']}"]
    (BUILD / 'rtype_sound.inc').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'звук: потоков TSFM {len(streams)}, раздел 2 — секторы {music_first}…{total - 1} ({music_sectors}), '
          f'пак {len(body)} байт')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
