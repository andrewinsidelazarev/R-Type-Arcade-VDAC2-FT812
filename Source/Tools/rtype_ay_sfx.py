#!/usr/bin/env python3
"""Эффекты на простом AY для машин без General Sound: покадровые состояния регистров.

Метод — тот же, что в Zuma Deluxe VDAC2 (`Build/Reference/Zuna-Deluxe-VDAC2-FT812/Source/OTHER/
make_ay_sfx.py`): AY считается словарём синтеза (три тональных канала и общий генератор шума), и
каждый кадр звука подгоняется под этот словарь методом преследования соответствия — жадный выбор до
трёх атомов (тон, шум, тон И шум) с неотрицательным МНК на каждом шаге. Состояние регистров меняется
только на тике, поэтому эффект — поток строк «сколько кадров держать + полные регистры AY 0…10».

Отличия от Zuma только во входе и раскладке:
  * источник — те же вырезки оригиналов, что идут в General Sound (`Audio/Original/rtype_sfx_XX.wav`
    по каталогу `rtype_sfx.json`), то есть звук тот же, что у аркады, а не синтезированный заново;
  * набор команд — `rtype_gs.ROM_COMMANDS`, индекс эффекта в таблице равен индексу команды в этом
    наборе (таблица команд `AY_COMMAND_INDEX` переводит $30…$FF в индекс);
  * тик — кадр развёртки FT812 (59.08 Гц), строка держится кратно `ROW_FRAMES` кадрам, поэтому темп
    эффекта не зависит от скорости игры, как и у эффектов GS.

Результат: `Build/V30Z80/rtype_ay.bin` (таблица + строки) и `Build/V30Z80/rtype_ay.inc` (мета для
ассемблера). Запускать после `rtype_gs.py` — он готовит каталог вырезок.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import sys
import wave
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import rtype_gs                                   # noqa: E402  (набор команд и каталог вырезок)

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / 'Audio' / 'Original'
CATALOG = ORIGINAL / 'rtype_sfx.json'
# Готовые строки — производный звук, поэтому живут рядом с сэмплами GS в Audio/Converted и переживают
# очистку Build: подбор регистров считается минутами, в сборке машины идёт только укладка в пак.
OUT_BIN = ROOT / 'Audio' / 'Converted' / 'RTYPE_AY_SFX.bin'
OUT_REPORT = ROOT / 'Audio' / 'Converted' / 'RTYPE_AY_SFX_report.txt'
OUT_INC = ROOT / 'Build' / 'V30Z80' / 'rtype_ay.inc'

# Такт AY на ZX Evolution / TS-Conf — 1.75 МГц (у Zuma 1773400 Гц Spectrum 128; на TS-Conf делитель
# даёт 1.75 МГц, разница 0.2 % и на подбор периодов не влияет).
AY_CLOCK = 1_750_000
FRAME_RATE = 59.08                                # кадр развёртки FT812, как у остального звука порта
ROW_FRAMES = int(os.environ.get('RTYPE_AY_ROW_FRAMES', '1'))   # кадров развёртки на строку
                                                  # 1 — тик 59.08 Гц: огибающая эффекта заметно ближе
                                                  # к оригиналу, чем на 20 Гц у Zuma (у нас эффекты
                                                  # короткие, 0.1…1 с, и на 20 Гц атака смазывалась)
ROW_RATE = FRAME_RATE / ROW_FRAMES
ROW_SIZE = 12                                     # счётчик кадров + R0…R10
RECORD_SIZE = 3                                   # запись таблицы: адрес строки (2) + страница (1)
MIXER_SILENT = 0x3F
OUTPUT_GAIN = 1.0                                 # вырезку уже нормируем по пику, как тракт GS:
                                                  # усиление Zuma (×4) там нужно для ненормированных
                                                  # 8-битных исходников, у нас оно дало бы перегруз
MIN_ACTIVE_VOLUME = int(os.environ.get('RTYPE_AY_MINVOL', '1'))  # порог ненулевого канала: у Zuma 7,
                                                  # но там он поднимал тихие места, а у нас гасит
                                                  # огибающую взрывов — оставляем минимум
MAX_ATOMS = 3

# Громкости AY: шаг 3 дБ (амплитуда ×√2), уровень 15 — единица.
VOLUME_LEVELS = np.array([0.0] + [2.0 ** ((level - 15) / 2.0) for level in range(1, 16)],
                         dtype=np.float32)


@dataclass(frozen=True)
class Atom:
    """Атом словаря: что именно звучит в канале и с каким периодом."""
    mode: str                                     # tone | noise | both
    period: int
    noise: int
    basis: np.ndarray


@dataclass(frozen=True)
class FrameState:
    """Состояние регистров AY на строку."""
    periods: tuple[int, int, int]
    noise: int
    mixer: int
    volumes: tuple[int, int, int]


@dataclass(frozen=True)
class SoundResult:
    index: int
    command: int
    payload: bytes
    rows: int
    seconds: float
    rms_pct: float


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def period_from_freq(freq: float) -> int:
    if freq <= 0.0:
        return 256
    return clamp(int(round(AY_CLOCK / (16.0 * freq))), 1, 0x0FFF)


def volume_to_level(volume: int) -> float:
    return float(VOLUME_LEVELS[clamp(volume, 0, 15)])


def level_to_volume(level: float) -> int:
    level = max(0.0, min(1.0, level))
    return int(np.argmin(np.abs(VOLUME_LEVELS - level)))


def normalize_basis(basis: np.ndarray) -> np.ndarray:
    """Атом без постоянной составляющей и с единичным СКЗ: коэффициент МНК сразу даёт громкость."""
    basis = basis.astype(np.float32, copy=False) - float(np.mean(basis))
    rms = float(np.sqrt(np.mean(basis * basis)))
    return basis if rms < 1e-8 else basis / rms


def tone_basis(period: int, sample_rate: int, start: int, length: int) -> np.ndarray:
    """Меандр тонального канала AY с нужной фазой (фаза непрерывна между кадрами)."""
    period = clamp(period, 1, 0x0FFF)
    freq = AY_CLOCK / (16.0 * period)
    phase = (np.arange(start, start + length, dtype=np.float32) * freq / sample_rate) % 1.0
    return normalize_basis(np.where(phase < 0.5, 1.0, -1.0).astype(np.float32))


def noise_basis(period: int, start: int, length: int, sample_rate: int) -> np.ndarray:
    """Шум AY: 17-битный регистр сдвига с обратной связью, отсчёты держатся периодом генератора."""
    period = clamp(period, 1, 31)
    freq = AY_CLOCK / (16.0 * period)
    hold = max(1, int(round(sample_rate / max(1.0, freq))))
    lfsr = 0x1FFFF
    for _ in range(start // hold):                # доводим регистр до нужного места записи
        bit = (lfsr ^ (lfsr >> 3)) & 1
        lfsr = ((lfsr >> 1) | (bit << 16)) & 0x1FFFF
    out = np.empty(length, dtype=np.float32)
    pos = 0
    first = start % hold
    if first:
        bit = (lfsr ^ (lfsr >> 3)) & 1
        lfsr = ((lfsr >> 1) | (bit << 16)) & 0x1FFFF
        take = min(length, hold - first)
        out[:take] = 1.0 if (lfsr & 1) else -1.0
        pos = take
    while pos < length:
        bit = (lfsr ^ (lfsr >> 3)) & 1
        lfsr = ((lfsr >> 1) | (bit << 16)) & 0x1FFFF
        out[pos:pos + hold] = 1.0 if (lfsr & 1) else -1.0
        pos += hold
    return normalize_basis(out)


def frame_rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0


def tone_candidates(chunk: np.ndarray, sample_rate: int, previous: tuple[int, int, int]) -> list[int]:
    """Периоды-кандидаты: вершины спектра кадра (и их субгармоники) плюс окрестность прошлого кадра."""
    if len(chunk) < 16:
        return [p for p in previous if p > 0] or [128]
    window = np.hanning(len(chunk)).astype(np.float32)
    spectrum = np.abs(np.fft.rfft((chunk - float(np.mean(chunk))) * window))
    freqs = np.fft.rfftfreq(len(chunk), 1.0 / sample_rate)
    mask = (freqs >= 70.0) & (freqs <= min(5200.0, sample_rate * 0.46))
    periods: set[int] = set()
    if np.any(mask):
        idx = np.where(mask)[0]
        count = min(12, idx.size)
        for i in idx[np.argpartition(spectrum[idx], -count)[-count:]]:
            freq = float(freqs[i])
            for divisor in (1.0, 3.0, 5.0):       # AY даёт меандр: слышно и нечётные субгармоники
                p = period_from_freq(freq / divisor)
                for delta in (-8, -4, -2, -1, 0, 1, 2, 4, 8):
                    periods.add(clamp(p + delta, 1, 0x0FFF))
    for p in previous:
        if p > 0:
            for delta in (-16, -8, -4, -2, -1, 0, 1, 2, 4, 8, 16):
                periods.add(clamp(p + delta, 1, 0x0FFF))
    return sorted(periods) or [128]


def noise_candidates(chunk: np.ndarray, sample_rate: int) -> list[int]:
    """Периоды шума: сетка плюс оценка по числу переходов через ноль."""
    values = {1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 31}
    if len(chunk) >= 16:
        centered = chunk - float(np.mean(chunk))
        zcr = np.count_nonzero(np.diff(np.signbit(centered))) / max(1, len(centered) - 1)
        freq = max(80.0, min(5000.0, zcr * sample_rate * 0.5))
        p = clamp(period_from_freq(freq), 1, 31)
        for delta in (-4, -2, -1, 0, 1, 2, 4):
            values.add(clamp(p + delta, 1, 31))
    return sorted(values)


def solve_nonnegative(atoms: list[Atom], target: np.ndarray) -> tuple[list[Atom], np.ndarray]:
    """Преследование соответствия: по одному атому за шаг, каждый раз пересчитывая МНК без минусов."""
    if not atoms:
        return [], np.zeros(0, dtype=np.float32)
    residual = target.astype(np.float32, copy=True)
    selected: list[int] = []
    for _ in range(MAX_ATOMS):
        best_idx, best_score = -1, 0.0
        for idx, atom in enumerate(atoms):
            if idx in selected:
                continue
            score = float(np.dot(residual, atom.basis))
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx < 0:
            break
        selected.append(best_idx)
        matrix = np.stack([atoms[i].basis for i in selected], axis=1)
        coef, *_ = np.linalg.lstsq(matrix, target, rcond=None)
        coef = np.maximum(coef, 0.0)
        residual = target - matrix @ coef
    if not selected:
        return [], np.zeros(0, dtype=np.float32)
    matrix = np.stack([atoms[i].basis for i in selected], axis=1)
    coef, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    coef = np.maximum(coef, 0.0)
    keep = [i for i, c in zip(selected, coef) if c > 0.002]
    return [atoms[i] for i in keep], np.array([c for c in coef if c > 0.002], dtype=np.float32)


def mixer_for_modes(modes: list[str]) -> int:
    """Регистр 7: единица запрещает источник. Биты 0…2 — тон каналов, 3…5 — шум."""
    mixer = 0
    for channel, mode in enumerate(modes):
        if mode not in ('tone', 'both'):
            mixer |= 1 << channel
        if mode not in ('noise', 'both'):
            mixer |= 1 << (channel + 3)
    return mixer & 0x3F


def fit_frame(source: np.ndarray, sample_rate: int, start: int, end: int,
              previous: tuple[int, int, int]) -> tuple[FrameState, np.ndarray]:
    """Лучшее состояние регистров для куска звука: перебор периода шума, внутри — словарь тонов."""
    target = source[start:end].astype(np.float32, copy=False)
    target = target - float(np.mean(target))
    length = len(target)
    if length == 0 or frame_rms(target) < 0.004:
        return FrameState((1, 1, 1), 16, MIXER_SILENT, (0, 0, 0)), np.zeros(length, dtype=np.float32)

    periods = tone_candidates(target, sample_rate, previous)
    noises = noise_candidates(target, sample_rate)
    best_error = float('inf')
    best_state: FrameState | None = None
    best_recon = np.zeros(length, dtype=np.float32)

    for noise_period in noises:
        noise = noise_basis(noise_period, start, length, sample_rate)
        atoms: list[Atom] = [Atom('noise', 1, noise_period, noise)]
        for period in periods:
            tone = tone_basis(period, sample_rate, start, length)
            atoms.append(Atom('tone', period, noise_period, tone))
            # «Тон И шум» — как их смешивает сам AY: оба разрешены в микшере.
            atoms.append(Atom('both', period, noise_period,
                              normalize_basis(np.where((tone > 0) & (noise > 0), 1.0, -1.0)
                                              .astype(np.float32))))
        selected, coef = solve_nonnegative(atoms, target)
        if not selected:
            continue
        quant = np.array([volume_to_level(level_to_volume(float(c))) for c in coef], dtype=np.float32)
        recon = np.zeros(length, dtype=np.float32)
        periods_out, volumes_out, modes_out = [1, 1, 1], [0, 0, 0], []
        for channel, (atom, level) in enumerate(zip(selected[:3], quant[:3])):
            volume = level_to_volume(float(level) * OUTPUT_GAIN)
            if 0 < volume < MIN_ACTIVE_VOLUME:
                volume = MIN_ACTIVE_VOLUME
            if volume == 0:
                modes_out.append('sil')
            else:
                modes_out.append(atom.mode)
                recon += volume_to_level(volume) * atom.basis
            periods_out[channel] = atom.period if atom.mode != 'noise' else (previous[channel] or 1)
            volumes_out[channel] = volume
        while len(modes_out) < 3:
            modes_out.append('sil')
        error = float(np.sqrt(np.mean((target - recon) ** 2)))
        if error < best_error:
            best_error = error
            best_state = FrameState(tuple(clamp(p, 1, 0x0FFF) for p in periods_out),
                                    noise_period, mixer_for_modes(modes_out),
                                    tuple(clamp(v, 0, 15) for v in volumes_out))
            best_recon = recon
    if best_state is None:
        return FrameState((1, 1, 1), 16, MIXER_SILENT, (0, 0, 0)), np.zeros(length, dtype=np.float32)
    return best_state, best_recon


def state_to_row(frames: int, state: FrameState) -> bytes:
    """Строка потока: сколько кадров держать состояние, затем регистры 0…10 подряд."""
    pa, pb, pc = state.periods
    va, vb, vc = state.volumes
    return bytes([frames,
                  pa & 0xFF, (pa >> 8) & 0x0F,
                  pb & 0xFF, (pb >> 8) & 0x0F,
                  pc & 0xFF, (pc >> 8) & 0x0F,
                  state.noise & 0x1F, state.mixer & 0x3F,
                  va & 0x0F, vb & 0x0F, vc & 0x0F])


def source_pcm(command: int, meta: dict) -> tuple[int, np.ndarray]:
    """Вырезка оригинала по каталогу: моно float −1…1 и частота записи."""
    with wave.open(str(ORIGINAL / meta['file']), 'rb') as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise SystemExit(f'${command:02X}: нужен моно PCM S16')
        rate = source.getframerate()
        start = max(0, round(meta['start_seconds'] * rate))
        count = max(1, round(meta['duration_seconds'] * rate))
        source.setpos(min(start, source.getnframes()))
        raw = source.readframes(min(count, source.getnframes() - source.tell()))
    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak <= 0:
        raise SystemExit(f'${command:02X}: в вырезке тишина')
    return rate, samples / peak                   # нормируем по пику, как это делает тракт GS


def encode_sound(task: tuple[int, int, dict]) -> SoundResult:
    index, command, meta = task
    rate, pcm = source_pcm(command, meta)
    seconds = len(pcm) / rate
    rows_count = max(1, int(round(seconds * ROW_RATE)))
    recon = np.zeros(len(pcm), dtype=np.float32)
    states: list[FrameState] = []
    previous = (1, 1, 1)
    for row in range(rows_count):
        start = int(round(row * rate / ROW_RATE))
        end = min(len(pcm), int(round((row + 1) * rate / ROW_RATE)))
        if end <= start:
            end = min(len(pcm), start + 1)
        state, chunk = fit_frame(pcm, rate, start, end, previous)
        states.append(state)
        previous = state.periods
        recon[start:end] = chunk[:end - start]

    # Одинаковые подряд состояния сливаются: счётчик строки — в кадрах развёртки.
    payload = bytearray()
    written = 0
    last: FrameState | None = None
    run = 0
    for state in states:
        if last is not None and state == last and run + ROW_FRAMES <= 255:
            run += ROW_FRAMES
            continue
        if last is not None:
            payload.extend(state_to_row(run, last))
            written += 1
        last, run = state, ROW_FRAMES
    if last is not None:
        payload.extend(state_to_row(run, last))
        written += 1
    payload.append(0)                             # ноль в счётчике — конец эффекта

    centered = pcm - float(np.mean(pcm))
    rms = frame_rms(centered)
    error = float(np.sqrt(np.mean((centered - recon) ** 2)))
    return SoundResult(index=index, command=command, payload=bytes(payload), rows=written,
                       seconds=seconds, rms_pct=100.0 * error / max(rms, 1e-9))


def render_rows(payload: bytes) -> np.ndarray:
    """Проиграть поток строк на SSG-части YM2203 (она AY-совместима) — получаем то, что услышит игрок."""
    sys.path.insert(0, str(ROOT / 'Build' / 'PythonDeps'))
    import ymfm
    chip = ymfm.YM2203(clock=AY_CLOCK)
    chip.reset()
    blocks: list[np.ndarray] = []
    samples_per_frame = chip.sample_rate / FRAME_RATE
    offset = 0
    produced = 0.0
    while offset < len(payload) and payload[offset]:
        frames = payload[offset]
        for register in range(11):
            chip.write_address(register)
            chip.write_data(payload[offset + 1 + register])
        offset += ROW_SIZE
        produced += frames * samples_per_frame
        count = int(produced) - sum(len(block) for block in blocks)
        if count > 0:
            blocks.append(np.asarray(chip.generate(count), dtype=np.int32))
    # Глушим, как делает плеер по концу эффекта.
    for register, value in ((8, 0), (9, 0), (10, 0), (7, MIXER_SILENT)):
        chip.write_address(register)
        chip.write_data(value)
    if not blocks:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(blocks)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    peak = float(np.max(np.abs(audio))) if audio.size else 1.0
    pcm = np.rint(np.clip(audio / max(peak, 1e-9) * 30000.0, -32768, 32767)).astype('<i2')
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


def preview(results: list[SoundResult], catalog: dict) -> None:
    """WAV на каждый переведённый эффект: слева оригинал, справа — как он звучит на AY."""
    from scipy.signal import resample_poly
    out_dir = ROOT / 'Build' / 'V30Z80' / 'ay_preview'
    for result in results:
        audio = render_rows(result.payload)
        if audio.size == 0:
            continue
        ay = resample_poly(audio.astype(np.float64), 441, 4375).astype(np.float32)
        rate, source = source_pcm(result.command, catalog[f'0x{result.command:02X}'])
        ratio = Fraction(44100, rate).limit_denominator(1000)
        original = resample_poly(source.astype(np.float64), ratio.numerator,
                                 ratio.denominator).astype(np.float32)
        write_wav(out_dir / f'ay_{result.command:02X}.wav', ay, 44100)
        write_wav(out_dir / f'src_{result.command:02X}.wav', original, 44100)
    print(f'превью: {out_dir.relative_to(ROOT)}', flush=True)


SECTOR = 512


def charge_loop_offset(blob: bytes) -> tuple[int, int]:
    """Точка круга заряда $32: смещение строки в блоке и длина круга в кадрах.

    В аркаде накопление — вступление и бесконечный круг из шести нот (rtype_gs.CHARGE_CYCLE,
    0.19398 с) до команды $33. Вырезка оригинала кончается ещё на круге, поэтому поток AY при
    долгом удержании надо закольцевать: берём два круга от конца — 22.92 кадра, ближайшее к целому
    число кругов (набег 0.08 кадра, 1.4 мс за оборот, на слух незаметно).
    """
    index = rtype_gs.ROM_COMMANDS.index(rtype_gs.CHARGE_COMMAND)
    offset = int.from_bytes(blob[index * RECORD_SIZE:(index + 1) * RECORD_SIZE], 'little')
    rows: list[tuple[int, int]] = []            # (смещение строки, кадр её начала)
    frame = 0
    while blob[offset]:
        rows.append((offset, frame))
        frame += blob[offset]
        offset += ROW_SIZE
    loop_frames = round(2 * rtype_gs.CHARGE_CYCLE * FRAME_RATE)
    target = frame - loop_frames
    start_frame = rtype_gs.CHARGE_CYCLE_START * FRAME_RATE
    if target < start_frame:
        raise SystemExit('поток заряда короче вступления и двух кругов — круг не выделить')
    row_offset, row_frame = min(rows, key=lambda item: abs(item[1] - target))
    return row_offset, frame - row_frame


def write_inc(first: int, sectors: int, size: int, blob: bytes) -> None:
    """rtype_ay.inc: где блок лежит в паке и какой команде какой эффект."""
    lines = ['; Сгенерировано rtype_ay_sfx.py: эффекты на простом AY для машин без General Sound.',
             f'AY_SOUND_COUNT  EQU {len(rtype_gs.ROM_COMMANDS)}',
             f'AY_RECORD_SIZE  EQU {RECORD_SIZE}',
             f'AY_ROW_SIZE     EQU {ROW_SIZE}',
             f'AY_DATA_SIZE    EQU {size}',
             f'AY_DATA_SECTOR  EQU {first}          ; хвост пака после кольца фона',
             f'AY_DATA_SECTORS EQU {sectors}',
             f'AY_CHARGE_LOOP  EQU #{charge_loop_offset(blob)[0]:06X}   ; строка начала круга заряда $32 '
             f'(круг {charge_loop_offset(blob)[1]} кадров)',
             '; Команда $30…$FF → индекс эффекта (#FF — эффекта нет).',
             'AY_COMMAND_INDEX:']
    lookup = {command: index for index, command in enumerate(rtype_gs.ROM_COMMANDS)}
    row = []
    for command in range(0x30, 0x100):
        row.append(f'#{lookup.get(command, 0xFF):02X}')
        if len(row) == 16:
            lines.append('                DB ' + ', '.join(row))
            row = []
    if row:
        lines.append('                DB ' + ', '.join(row))
    # Голос у AY один, и без правила вытеснения частые выстрелы ($30, приоритет 80) обрывали всё: на
    # этапе 1 луч мини-босса $3A доигрывал 14 %, взрывы 12 % (модель по журналу 879 эффектов, 22.09.2026).
    # Правило — самого драйвера аркады: новый эффект прерывает звучащий, только если он не менее важен
    # (приоритет — первый байт первой части эффекта в программе звукового Z80, меньше — важнее).
    priorities, stops = command_priorities()
    lines.append('; Приоритет эффекта драйвера аркады по индексу (меньше — важнее), #FF — остановка.')
    lines.append('AY_PRIORITY:')
    values = [f'#{priorities[command]:02X}' for command in rtype_gs.ROM_COMMANDS]
    for first in range(0, len(values), 16):
        lines.append('                DB ' + ', '.join(values[first:first + 16]))
    lines.append('; Остановка по индексу: команда, чей звук она глушит ($33 — заряд $32, $5B — $5A), 0 — нет.')
    lines.append('AY_STOP_TARGET:')
    values = [f'#{stops.get(command, 0):02X}' for command in rtype_gs.ROM_COMMANDS]
    for first in range(0, len(values), 16):
        lines.append('                DB ' + ', '.join(values[first:first + 16]))
    OUT_INC.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def command_priorities() -> tuple[dict[int, int], dict[int, int]]:
    """Приоритеты эффектов и цели остановок из программы звукового Z80 (таблица указателей $1000).

    Заголовок эффекта: младшие 3 бита — частей − 1, старшие — тип ($10 — остановка чужого голоса, за
    заголовком номер этого голоса); у обычного эффекта за заголовком указатели частей, первый байт
    данных части — приоритет. Разбор совпадает с аудитом SFX 2026-09-16 ($30 — 80, $32 — 3,
    $50 — 48, $55/$5A/$3A/$61 — 16, $59/$64 — 32).
    """
    image = rtype_gs.SOUND_IMAGE.read_bytes()

    def word(address: int) -> int:
        return image[address] | (image[address + 1] << 8)
    stops = rtype_gs.stop_targets()
    priorities = {}
    for command in rtype_gs.ROM_COMMANDS:
        pointer = word(0x1000 + command * 2)
        if command in stops:
            priorities[command] = 0xFF
            continue
        priorities[command] = image[word(pointer + 1)]
    return priorities, stops


def pack_into_level_pack() -> int:
    """Дописать готовый блок в хвост пака (сразу за кольцом фона) и записать rtype_ay.inc."""
    import struct
    if not OUT_BIN.is_file():
        print(f'нет {OUT_BIN.relative_to(ROOT)}: сначала rtype_ay_sfx.py без --pack (считает эффекты)')
        return 1
    blob = OUT_BIN.read_bytes()
    pack_path = ROOT / 'Build' / 'V30Z80' / 'RTYPELVL.PAC'
    pack = bytearray(pack_path.read_bytes())
    if pack[0:8] != b'RTYPEDAT':
        raise SystemExit(f'{pack_path}: не пак RTYPEDAT')
    report_path = ROOT / 'Build' / 'V30Z80' / 'rtype_data.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    ring = report.get('ring_tiles')
    if ring is None:
        raise SystemExit('в отчёте пака нет кольца фона: сначала rtype_ring.py')
    # Обрезаем пак сразу за кольцом: повторный запуск не наращивает хвост.
    body = bytearray(pack[:(ring['sector'] + ring['sectors']) * SECTOR])
    first = len(body) // SECTOR
    body += blob + bytes((-len(blob)) % SECTOR)
    sectors = (len(blob) + SECTOR - 1) // SECTOR
    total = len(body) // SECTOR
    struct.pack_into('<I', body, 44, total)
    if total > 0xFFFF:
        raise SystemExit('пак длиннее 65535 секторов: номер сектора у загрузчика — слово')
    pack_path.write_bytes(bytes(body))
    report.update(size=len(body), sectors=total, sha256=hashlib.sha256(bytes(body)).hexdigest(),
                  ay_sfx={'sector': first, 'sectors': sectors, 'bytes': len(blob)})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    write_inc(first, sectors, len(blob), blob)
    pages = (len(blob) + 0x3FFF) // 0x4000
    print(f'эффекты AY: {len(blob)} Б ({pages} страниц буфера мелодий), секторы {first}…{total - 1}, '
          f'пак {len(body)} байт', flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commands', help='только эти команды через запятую (например 0x30,0x50)')
    parser.add_argument('--jobs', type=int, default=0, help='процессов (0 — по числу ядер)')
    parser.add_argument('--wav', action='store_true', help='записать WAV: оригинал и звучание на AY')
    parser.add_argument('--pack', action='store_true',
                        help='только уложить готовый блок в пак и записать rtype_ay.inc')
    args = parser.parse_args()

    if args.pack:
        return pack_into_level_pack()

    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))['sounding']
    commands = list(rtype_gs.ROM_COMMANDS)
    if args.commands:
        wanted = {int(value, 0) for value in args.commands.split(',') if value.strip()}
        commands = [command for command in commands if command in wanted]
    tasks = []
    for index, command in enumerate(rtype_gs.ROM_COMMANDS):
        meta = catalog.get(f'0x{command:02X}')
        if meta is None or command not in commands:
            continue
        tasks.append((index, command, meta))
    print(f'эффектов к переводу на AY: {len(tasks)} из {len(rtype_gs.ROM_COMMANDS)} команд', flush=True)

    jobs = args.jobs or min(mp.cpu_count(), len(tasks)) or 1
    if jobs > 1:
        with mp.Pool(jobs) as pool:
            results = pool.map(encode_sound, tasks)
    else:
        results = [encode_sound(task) for task in tasks]
    results.sort(key=lambda item: item.index)

    table = bytearray(len(rtype_gs.ROM_COMMANDS) * RECORD_SIZE)
    body = bytearray()
    for result in results:
        offset = len(table) + len(body)
        table[result.index * RECORD_SIZE:result.index * RECORD_SIZE + RECORD_SIZE] = bytes(
            [offset & 0xFF, (offset >> 8) & 0xFF, (offset >> 16) & 0xFF])
        body.extend(result.payload)
    blob = bytes(table) + bytes(body)
    OUT_BIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_BIN.write_bytes(blob)


    if args.wav:
        preview(results, catalog)

    report = [f'{result.command:#04X}: строк {result.rows:4d}, {result.seconds:5.2f} с, '
              f'ошибка {result.rms_pct:5.1f} % СКЗ' for result in results]
    OUT_REPORT.write_text('\n'.join(report) + '\n', encoding='utf-8')
    worst = max(results, key=lambda item: item.rms_pct) if results else None
    print(f'таблица {len(table)} Б + строки {len(body)} Б = {len(blob)} Б, '
          f'SHA-256 {hashlib.sha256(blob).hexdigest()[:16]}', flush=True)
    if worst is not None:
        print(f'худшая подгонка: ${worst.command:02X} — {worst.rms_pct:.1f} % СКЗ; '
              f'отчёт {OUT_REPORT.relative_to(ROOT)}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
