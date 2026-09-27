"""Эффекты General Sound переведённой программы: PCM команд $30…$7F — раздел 3 пака RTYPELVL.PAC,
таблицы адаптера — Build/V30Z80/rtype_gs.inc.

Какие команды. Только те, что World ROM действительно отправляет звуковому Z80 (аудит 2026-09-16):
  * константы перед вызовами отправки `$0303` (сегмент кода с базой `$0400`, 245 вызовов, `MOV CL,imm8`):
    $30…$38, $3A…$3D, $3F, $40, $41, $50…$57, $59…$5B, $5D…$5F, $61…$68;
  * таблица отсчёта «continue» `ES:$0DE0` (автомат `$141F`): $70…$79 — проверено прохождением эталона;
  * $00 (шесть вызовов с `XOR CL,CL`) — «заглушить всё» драйвера (`$0DC4`), обрабатывается адаптером.
Остальные звучащие в скане команды не нужны: $81…$AB — мелодии $01…$2B с битом 7 (драйвер делает AND $7F),
$B0…$FF — двойники $30…$7F, $39, $3E, $4C…$4F, $58, $5C, $60, $69, $6A ROM не шлёт. Лишние 750 КиБ не
влезали в память GS: у ZX-MultiSound 1024 КБ, настоящая прошивка приняла 913 КБ и отказала.

Команды остановки — из данных программы звукового Z80 (Build/Analysis/rtype_sound_upload.bin): заголовок
эффекта с типом $10 привязан к голосу другой команды и заменяет её дорожку: $33 глушит заряд $32, $5B — звук
$5A (проверено оракулом rtype_m72.sound).

Источник PCM — оригиналы Audio/Original/rtype_sfx_XX.wav (звучащие части записей MAME по одной команде,
48 кГц 16 бит, каталог rtype_sfx.json; переносит rtype_sfx_originals.py), их же играет эталон
rtype_port.audio.GeneralSound. 64-отводный sinc с окном Ханна, unsigned 8 бит; готовые сэмплы —
Audio/Converted/RTYPE_GS_SFX_XX_U8_<частота>.raw, из них собирается раздел 3 пака. Отступления на
аппаратном пределе:
  * частота: 22050 Гц (нота GS 65), если выше 5.5 кГц у эффекта не меньше 5 % энергии, иначе 11025 Гц
    (нота 53) — на 11025 Гц у заряда $32 срезалось 75 % энергии, у $55 — 49 %, у $56 — 38 %;
  * 8 бит и громкость: каждый эффект нормируется по своему пику на полную шкалу и играет с громкостью голоса
    64 — полная амплитуда GS (решение пользователя 2026-09-16: GS у ZX-MultiSound и так тихий — каналы GS
    входят в сумматор платы через 47 кОм против 10 кОм у FM); соотношение громкостей эффектов аркады
    (было volume = 64 × пик / пик самого громкого, типично 20–30) при этом не сохраняется;
  * заряд $32 в аркаде — вступление (31 нота через 32.3 мс, с 0.133 с после команды) и бесконечный круг из
    шести нот (0.19398 с) до $33; сэмпл — вступление и два круга с петлёй GS, последние 20 мс петли плавно
    сведены в звук перед её началом (фазы операторов YM2151 не повторяются, без сведения стык щёлкает).
Одинаковые по содержимому команды делят один сэмпл в памяти GS.

Запускать после rtype_sound.py: тот дописывает раздел 2 (мелодии) и оставляет раздел 3 пустым.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import numpy as np                                                  # noqa: E402

BUILD = ROOT / 'Build' / 'V30Z80'
PACK = BUILD / 'RTYPELVL.PAC'
ORIGINAL = ROOT / 'Audio' / 'Original'
CONVERTED = ROOT / 'Audio' / 'Converted'
SOUND_IMAGE = ROOT / 'Build' / 'Analysis' / 'rtype_sound_upload.bin'
SECTOR = 512
GS_MAX_VOLUME = 64              # шкала громкости голоса GS: эффекты играют на полной
FULL_SCALE = 0.99               # пик сэмпла после нормировки (запас на выбросы ресемплера)
GS_RAM_LIMIT = 900 * 1024       # настоящая прошивка GS (Unreal, GSType=Z80) приняла 913 КБ из 1024 КБ платы
GS_MAX_SAMPLES = 64             # предел числа FX у прошивки GS
FIRST_COMMAND = 0x30            # ниже — мелодии TSFM
LAST_COMMAND = 0x7F
FRAME_RATE = 55                 # шаг счёта голосов — кадр развёртки FT812 (≈55 Гц)

# Команды, которые World ROM отправляет звуковому Z80 (см. описание модуля).
ROM_COMMANDS = (
    0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x3A, 0x3B, 0x3C, 0x3D, 0x3F, 0x40, 0x41,
    0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x59, 0x5A, 0x5B, 0x5D, 0x5E, 0x5F,
    0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
    0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79)

# Частоты воспроизведения: нота GS → частота (прошивка и HLE Unreal: периоды Amiga, ≈11063 и ≈22126 Гц).
RATE_LOW, NOTE_LOW = 11025, 53
RATE_HIGH, NOTE_HIGH = 22050, 65
HIGH_BAND_HZ = 5512.5
HIGH_BAND_SHARE = 0.05

# Заряд $32 по оракулу: первая нота через 0.133 с после команды (в скане отсчёт от первого звука),
# круг из шести нот начинается на 1.1348 с, период круга 0.19398 с.
CHARGE_COMMAND = 0x32
CHARGE_FIRST_NOTE = 0.133
CHARGE_CYCLE_START = 1.1348
CHARGE_CYCLE = 0.19398
CHARGE_LOOP_CYCLES = 2
CHARGE_CROSSFADE = 0.020


def sinc_resample(source: np.ndarray, input_rate: int, output_rate: int, taps: int = 64) -> np.ndarray:
    """Моно-ресемплер с ограничением полосы и sinc-окном Ханна — как в mame_audio_capture.py."""
    if input_rate == output_rate:
        return source.astype(np.float64)
    ratio = output_rate / input_rate
    count = int(round(len(source) * ratio))
    positions = np.arange(count) / ratio
    cutoff = min(1.0, ratio) * 0.94
    result = np.zeros(count, dtype=np.float64)
    half = taps // 2
    for index, position in enumerate(positions):
        centre = int(np.floor(position))
        first = max(0, centre - half + 1)
        last = min(len(source), centre + half + 1)
        if first >= last:
            continue
        window_positions = np.arange(first, last)
        distance = position - window_positions
        weights = cutoff * np.sinc(cutoff * distance)
        weights *= 0.5 + 0.5 * np.cos(np.pi * distance / half)      # окно Ханна
        result[index] = float(np.dot(source[first:last], weights))
    return result


def stop_targets() -> dict[int, int]:
    """Команды с заголовком типа $10: номер голоса, чью дорожку они заменяют (таблица указателей $1000)."""
    image = SOUND_IMAGE.read_bytes()
    result = {}
    for command in ROM_COMMANDS:
        pointer = image[0x1000 + command * 2] | (image[0x1001 + command * 2] << 8)
        if image[pointer] & 0xF0 == 0x10:
            result[command] = image[pointer + 1]
    return result


def effect_pcm(command: int, meta: dict) -> tuple[bytes, float, int, int | None]:
    """Вырезка эффекта по каталогу → (PCM unsigned 8 бит, пик до нормировки, частота)."""
    path = ORIGINAL / meta['file']
    with wave.open(str(path), 'rb') as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise SystemExit(f'{path.name}: нужен моно PCM S16')
        rate = source.getframerate()
        start = max(0, round(meta['start_seconds'] * rate))
        count = max(1, round(meta['duration_seconds'] * rate))
        source.setpos(min(start, source.getnframes()))
        samples = np.frombuffer(source.readframes(min(count, source.getnframes() - source.tell())),
                                dtype='<i2').astype(np.float64)
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak <= 0:
        raise SystemExit(f'${command:02X}: в вырезке тишина, каталог считает эффект звучащим')
    power = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) ** 2
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    share = float(power[freqs > HIGH_BAND_HZ].sum() / power.sum())
    output_rate = RATE_HIGH if share >= HIGH_BAND_SHARE else RATE_LOW
    if command == CHARGE_COMMAND:
        # Звук накопления BEAM — единственный длящийся: в аркаде он тянется, пока держат огонь. Раньше мы
        # отдавали плате петлю (#48/#49) и длительность «255 — до остановки», и потерянный стоп $33 оставлял
        # сирену навсегда (жалобы 2026-09-20). Теперь сэмпл — только устойчивый круг: его крутит повтором
        # сторож заряда, пока ROM подтверждает накопление, так что вечного звука взяться неоткуда.
        # Кросс-фейд хвоста с участком перед началом круга делает стык повтора бесшовным.
        begin = CHARGE_CYCLE_START + CHARGE_CYCLE - CHARGE_FIRST_NOTE      # второй круг: устойчивый звук
        end = begin + CHARGE_LOOP_CYCLES * CHARGE_CYCLE
        first, last, fade = round(begin * rate), round(end * rate), round(CHARGE_CROSSFADE * rate)
        if last > len(samples):
            raise SystemExit(f'${command:02X}: скан короче круга заряда')
        samples = samples[:last].copy()
        weight = np.linspace(0.0, 1.0, fade)
        samples[last - fade:last] = samples[last - fade:last] * (1 - weight) + samples[first - fade:first] * weight
        samples = samples[first:last]
    samples = samples * (FULL_SCALE / peak)
    resampled = np.clip(sinc_resample(samples, rate, output_rate), -1.0, 1.0)
    pcm = np.rint(128.0 + resampled * 127.0).clip(0, 255).astype(np.uint8).tobytes()
    return pcm, peak, output_rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    catalog = json.loads((ORIGINAL / 'rtype_sfx.json').read_text(encoding='utf-8'))['sounding']
    stops = stop_targets()
    sounding = [command for command in ROM_COMMANDS if f'0x{command:02X}' in catalog]
    silent = [command for command in ROM_COMMANDS if command not in sounding and command not in stops]
    if silent:
        raise SystemExit('немые в скане команды ROM без привязки остановки: ' + ', '.join(f'${c:02X}' for c in silent))

    samples: list[bytes] = []                 # PCM уникальных эффектов
    sample_note: list[int] = []
    by_digest: dict[str, int] = {}
    size = LAST_COMMAND - FIRST_COMMAND + 1
    command_sample = [0xFF] * size            # команда → индекс сэмпла
    command_volume = [0] * size
    command_frames = [0] * size               # кадров звучания; 255 — петля до остановки
    command_stop = [0xFF] * size              # команда, чей голос глушит эта (тип $10 драйвера)
    for command, target in stops.items():
        command_stop[command - FIRST_COMMAND] = target
        print(f'  ${command:02X}: остановка голоса ${target:02X}', flush=True)
    for command in sounding:
        pcm, peak, rate = effect_pcm(command, catalog[f'0x{command:02X}'])
        (CONVERTED / f'RTYPE_GS_SFX_{command:02X}_U8_{rate}.raw').write_bytes(pcm)
        digest = hashlib.sha256(pcm + bytes([rate >> 8])).hexdigest()
        index = by_digest.get(digest)
        if index is None:
            index = len(samples)
            by_digest[digest] = index
            samples.append(pcm)
            sample_note.append(NOTE_HIGH if rate == RATE_HIGH else NOTE_LOW)
        slot = command - FIRST_COMMAND
        command_sample[slot] = index
        command_volume[slot] = GS_MAX_VOLUME
        command_frames[slot] = min(254, math.ceil(len(pcm) / rate * FRAME_RATE) + 1)
        print(f'  ${command:02X}: {len(pcm)} байт, {rate} Гц, сэмпл {index}, громкость {command_volume[slot]}, '
              f'кадров {command_frames[slot]}', flush=True)
    payload = sum(len(pcm) for pcm in samples)
    if len(samples) > GS_MAX_SAMPLES:
        raise SystemExit(f'сэмплов {len(samples)} — больше {GS_MAX_SAMPLES}, предел прошивки GS')
    if payload > GS_RAM_LIMIT:
        raise SystemExit(f'сэмплы {payload} байт — не влезут в память GS ({GS_RAM_LIMIT} байт)')

    pack = bytearray(PACK.read_bytes())
    if pack[0:8] != b'RTYPEDAT':
        raise SystemExit(f'{PACK}: не пак RTYPEDAT')
    count = struct.unpack_from('<H', pack, 10)[0]
    sections = [struct.unpack_from('<II', pack, 12 + number * 8) for number in range(count)]
    if len(sections) < 4:
        raise SystemExit('в паке нет раздела 3 под эффекты: сначала rtype_sound.py')
    music_end = sections[2][0] + sections[2][1]
    body = bytearray(pack[:music_end * SECTOR])
    effects_first = music_end
    locations = []
    for pcm in samples:
        first = len(body) // SECTOR
        body += pcm + bytes([0x80]) * ((-len(pcm)) % SECTOR)        # добивка тишиной (0x80 — середина)
        locations.append((first, (len(pcm) + SECTOR - 1) // SECTOR, len(pcm)))
    total = len(body) // SECTOR
    new_sections = [sections[0], sections[1], sections[2], (effects_first, total - effects_first)]
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
                  sections={'index': new_sections[0], 'cells': new_sections[1],
                            'music': new_sections[2], 'effects': new_sections[3]},
                  effects=[{'sample': index, 'sector': first, 'sectors': sectors, 'bytes': size_bytes,
                            'note': sample_note[index]}
                           for index, (first, sectors, size_bytes) in enumerate(locations)])
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    def rows(values, fmt):
        out = []
        for start in range(0, size, 16):
            out.append('                DB ' + ', '.join(fmt(value) for value in values[start:start + 16]) +
                       f'   ; ${FIRST_COMMAND + start:02X}')
        return out

    lines = [
        '; Сгенерировано rtype_gs.py: эффекты General Sound (команды $30…$7F, которые шлёт ROM) в разделе 3 пака.',
        f'GS_SAMPLE_COUNT EQU {len(samples)}',
        f'GS_LAST_COMMAND EQU #{LAST_COMMAND:02X}',
        '; Сэмпл: первый сектор пака, секторов, байт.',
        'GS_SAMPLES:']
    for index, (first, sectors, size_bytes) in enumerate(locations):
        lines.append(f'                DW {first}, {sectors}, {size_bytes}          ; сэмпл {index}')
    lines.append(f'; Нота GS сэмпла: {NOTE_LOW} — {RATE_LOW} Гц, {NOTE_HIGH} — {RATE_HIGH} Гц.')
    lines.append('GS_SAMPLE_NOTE:')
    for start in range(0, len(samples), 16):
        lines.append('                DB ' + ', '.join(str(note) for note in sample_note[start:start + 16]))
    lines.append(f'; Команды ${FIRST_COMMAND:02X}…${LAST_COMMAND:02X}: индекс сэмпла (#FF — нет звука).')
    lines.append('GS_COMMAND_SAMPLE:')
    lines += rows(command_sample, lambda v: f'#{v:02X}')
    lines.append('; Громкость голоса GS: у всех эффектов полная (решение пользователя: GS у платы тихий).')
    lines.append('GS_COMMAND_VOLUME:')
    lines += rows(command_volume, str)
    lines.append('; Кадров звучания (голос свободен после них), 255 — петля до команды остановки.')
    lines.append('GS_COMMAND_FRAMES:')
    lines += rows(command_frames, str)
    lines.append('; Команда, чей голос глушит эта (заголовок типа $10 драйвера), #FF — не остановка.')
    lines.append('GS_COMMAND_STOP:')
    lines += rows(command_stop, lambda v: f'#{v:02X}')
    (BUILD / 'rtype_gs.inc').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')

    print(f'эффекты GS: команд {len(sounding)}, сэмплов {len(samples)}, {payload} байт ({payload / 1024:.0f} КиБ), '
          f'раздел 3 — секторы {effects_first}…{total - 1}, пак {len(body)} байт')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
