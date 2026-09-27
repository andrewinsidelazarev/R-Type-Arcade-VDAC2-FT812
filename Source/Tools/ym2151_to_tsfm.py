#!/usr/bin/env python3
"""Перенос музыки R-Type с YM2151 (OPM) на TurboSound FM (2×YM2203, OPN).

Основной вход — журнал оракула (Source/Tools/rtype_music.py: исходная программа звукового Z80 и ymfm YM2151)
по тактам драйвера. Прежний вход этого скрипта — регистровый лог MAME (`mame_music_log.lua`): кадр, регистр,
значение; его обязательно снимать подачей ОДНОЙ звуковой команды в тишине: у M72 музыку и эффекты играет один
YM2151, и запись из attract-режима содержит вперемешку музыку и стрельбу демо.

Трек занимает до восьми каналов OPM, а на двух YM2203 их шесть. Лишние каналы не отбрасываются, а раздаются
динамически: голос закрепляется за каналом, пока канал не понадобится другому. При переназначении тембр
переносится целиком, иначе нота зазвучала бы чужим инструментом. Мелодии драйвера занимают четыре канала.

Что переносится дословно (регистровые модели OPM и OPN родственны):
    DT1/MUL, TL, KS/AR, D1R, D2R, D1L/RR, алгоритм и обратная связь.
Чего у YM2203 нет и как это заменено (отступления на аппаратном пределе):
    DT2 (второй детюн) сворачивается в множитель MUL (merge_dt2);
    аппаратный LFO — частотная модуляция (вибрато) считается программно по формулам ymfm (класс Lfo) и
    выдаётся записями F-Number раз в кадр потока; AM-модуляция (тремоло) не переносится — у операторов
    музыки R-Type бит AMS-EN не стоит, convert проверяет это.

Громкость (отступление на аппаратном пределе, решение пользователя 2026-09-23 «+3 дБ»): у платы ZX-MultiSound ЦАП
YM3014B (±1.25 В) входит в выходной сумматор без усиления (10 кОм / 10 кОм), а музыка R-Type занимает около трети
шкалы чипа (RMS −22.4 дБ, как у аркадного YM2151: там уровень добирал усилитель автомата) — на выходе платы ≈0.1 В
RMS. TL несущих операторов (по текущему алгоритму канала) выдаются на MUSIC_BOOST_TL ступеней по 0.75 дБ меньше;
модуляторы — как у аркады, поэтому тембр и баланс голосов прежние. Самый громкий несущий оператор всех мелодий —
TL 8 (замер 2026-09-23), до TL 0 не упирается ни один. В голосе хранятся аркадные значения; при смене алгоритма
TL канала переиздаются (набор несущих меняется).

Формат потока (читает TsfmMusic_Update / StreamStep v30z80_sound.asm и rtype_port.tsfm.decode_stream):
[пауза в кадрах][число записей]([чип][регистр][значение])…; $FE $00 — продолжение с начала следующей
страницы 16 КБ; $FD $00 — точка петли: после последнего кадра повторяемого потока воспроизведение
продолжается отсюда (без маркера — с начала); $FF $00 — конец.
"""
from __future__ import annotations

import argparse
import csv
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "Build" / "Arcade" / "Music" / "ym2151_writes.csv"
DEFAULT_BIN = ROOT / "Assets" / "Converted" / "Arcade" / "Music" / "STAGE1_TSFM.bin"
DEFAULT_INC = ROOT / "Source" / "ASM" / "generated_music.inc"

# Тактовые частоты: у M72 YM2151 работает на 3.579545 МГц (проверено -listxml),
# на ZX-MultiSound оба YM2203 тактируются 3.5 МГц — вывод ym_m прошивки платы:
# clk3_5_cnt += 7 по фронту clk32 и ym_m = clk3_5_cnt[5], то есть 32 МГц × 7/64
# (UzixLS/zx-multisound, cpld/rtl/top.v). Прежние 1.75 МГц здесь были ошибкой:
# на плате весь трек звучал октавой выше (проверено 16.09.2026 в Unreal_tsfm).
OPM_CLOCK = 3_579_545
OPN_CLOCK = 3_500_000
# Прескалер YM2203, который выставляет плеер: $2D = /6, $2E = /3, $2F = /2.
# Плеер пишет $2D, см. TSFM_REG_PRESCALE в tsfm_music.asm и ChipsReset в
# v30z80_sound.asm: 3.5 МГц / 6 даёт ту же частоту синтеза 48 611 Гц, на которую
# рассчитаны F-номера потока, и ближе всего к 55 930 Гц оригинального YM2151.
OPN_PRESCALE = 6
# Множитель в формуле F-Number равен 12 × прескалер: чип обслуживает 12
# операторных слотов (3 канала × 4 оператора) за период, и частота обновления
# синтеза равна clock / (12 × прескалер).
#
# Ошибиться здесь вдвое — значит сдвинуть ВЕСЬ трек на октаву: басовая партия
# уезжает в середину и пропадает, а верхние ноты фальшивят. Так и было дважды:
# сперва стояло 144 (прескалер /6 без учёта, что 144 — это уже 12×12), потом 72
# (величина для /6) при выставленном /3.
OPN_FREQ_MULT = 12 * OPN_PRESCALE

# Время: сэмпл синтеза YM2151 — OPM_CLOCK / 64 (55 930.4 Гц; на нём тикают LFO и таймер), кадр потока — кадр
# развёртки M72: 8 МГц / (512 × 284) = 55.018 Гц, то есть 1016.6 сэмпла YM2151.
OPM_SAMPLE_RATE = Fraction(OPM_CLOCK, 64)
M72_FRAME_RATE = Fraction(8_000_000, 512 * 284)
OPM_SAMPLES_PER_FRAME = OPM_SAMPLE_RATE / M72_FRAME_RATE

# Маркеры потока (см. описание модуля).
STREAM_END = 0xFF
STREAM_PAGE = 0xFE
STREAM_LOOP = 0xFD
STREAM_PAGE_SIZE = 0x4000
# Пауза блока не больше 250: $FD…$FF заняты маркерами.
STREAM_MAX_WAIT = 250

# Физические каналы: два YM2203 по три FM-канала. Эффекты играет General Sound,
# поэтому под музыку отдаются оба чипа целиком.
PHYS_CHANNELS = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2))

# Порядок операторов: у OPM слоты идут M1,M2,C1,C2 с шагом 8 регистров,
# у OPN — тем же порядком с шагом 4.
OPERATOR_COUNT = 4

# Базы операторных регистров: OPM -> OPN.
OPERATOR_BASES = (
    (0x40, 0x30),   # DT1 | MUL
    (0x60, 0x40),   # TL
    (0x80, 0x50),   # KS | AR
    (0xA0, 0x60),   # AMS-EN | D1R  ->  AM | D1R
    (0xC0, 0x70),   # DT2  | D2R    ->  D2R (DT2 отбрасывается)
    (0xE0, 0x80),   # D1L  | RR
)

# Ноты OPM в KC: старший ниббл — октава, младший — поле NOTE.
#
# ВАЖНО: поле NOTE начинается НЕ с C, а с C#, и C стоит в конце (значение 14) —
# внутри октавы OCT код ноты растёт вместе с частотой, поэтому C оказывается
# выше B и принадлежит уже СЛЕДУЮЩЕЙ музыкальной октаве. Значения 3, 7, 11, 15
# запрещены.
#
# Здесь таблица переводит NOTE в полутон, отсчитанный от C текущей октавы OCT.
# У C он равен 12 — то есть на октаву выше, и никакого отдельного случая для
# перевода октавы не нужно. Прежняя таблица просто нумеровала ноты подряд с
# нуля, отчего A получала 8 вместо 9 и ВЕСЬ трек звучал на полтона ниже.
OPM_NOTE_INDEX = {0: 1, 1: 2, 2: 3, 4: 4, 5: 5, 6: 6,
                  8: 7, 9: 8, 10: 9, 12: 10, 13: 11, 14: 12}

# DT2 (регистры $C0-$DF OPM) — не тонкий детюн, а грубый множитель частоты
# оператора: 0 → ×1.0, 1 → ×1.414, 2 → ×1.581, 3 → ×1.732. У YM2203 такого
# регистра нет вовсе, и без компенсации тембр теряет объём, особенно в басу.
# Ближайшее, чем OPN располагает, — множитель MUL, поэтому DT2 сворачивается
# в него: MUL_эфф = clamp(round(MUL × коэффициент), 1, 15). Приближение грубое
# (MUL целочисленный), но сохраняет соотношение частот операторов, ради
# которого DT2 и ставился.
OPM_DT2_RATIO = (1.0, 1.414, 1.581, 1.732)


def opn_note(octave: int, semitone: int, clock: int,
             fraction: int = 0) -> tuple[int, int]:
    """Нота OPM -> (block, F-Number) для YM2203.

    `octave` — поле OCT, `semitone` — полутон от C этой октавы (см.
    OPM_NOTE_INDEX), `fraction` — KF, дробная часть ноты в 1/64 полутона.
    Игра ведёт этим полем плавные слайды, и без него портаменто превращается в
    ступеньки.

    F-Num = f × 2^20 × (12 × прескалер) / (clock × 2^(B-1)).

    Берём наименьший block, при котором число помещается в 11 бит: чем больше
    F-Number, тем мельче шаг по частоте и тем точнее строй.
    """
    freq = 440.0 * (2.0 ** ((octave - 4)
                            + (semitone - 9) / 12.0
                            + fraction / (64.0 * 12.0)))
    for block in range(8):
        divisor = clock * (2 ** (block - 1)) if block else clock / 2
        fnum = round(freq * (1 << 20) * OPN_FREQ_MULT / divisor)
        if fnum < 2048:
            return block, fnum
    return 7, 2047


def opn_frequency(block: int, fnum: int, clock: int) -> float:
    """Обратный пересчёт: какая частота реально зазвучит. Для самопроверки."""
    divisor = clock * (2 ** (block - 1)) if block else clock / 2
    return fnum * divisor / ((1 << 20) * OPN_FREQ_MULT)


def merge_dt2(voice: "Voice", slot: int) -> int:
    """DT1|MUL для OPN с учётом потерянного DT2: множитель сворачивается в MUL."""
    raw = voice.dt1mul.get(slot, 0)
    dt1 = raw & 0x70
    mul = raw & 0x0F
    ratio = OPM_DT2_RATIO[voice.dt2.get(slot, 0)]
    if mul == 0:                       # MUL=0 означает ×0.5
        scaled = 0 if ratio < 1.2 else 1
    else:
        scaled = min(15, max(1, round(mul * ratio)))
    return dt1 | scaled


class Lfo:
    """Программный LFO YM2151: у YM2203 его нет, вибрато переносится записями F-Number.

    Формулы — ymfm (ymfm_opm.cpp: opm_registers::clock_noise_and_lfo, compute_phase_step), той же библиотекой
    оракул эмулирует YM2151 аркады:
      * на каждый сэмпл синтеза счётчик += (0x10 | LFRQ & 15) << (LFRQ >> 4); пока стоит бит 1 регистра 1,
        счётчик держится в нуле (драйвер пишет 2, затем 0 перед нотой — сброс фазы);
      * значение LFO — биты 22…29 счётчика; волны (W — биты 0…1 регистра $1B), PM — знаковый байт:
        пила — v; меандр — (бит 7 ? 0 : 255) ^ $80; треугольник — am = бит 7 ? (v·2) & 255 : ((v ^ 255)·2) & 255,
        pm = бит 6 ? am : ~am; шум (W = 3) не переносится — convert откажет;
      * глубина: (pm · PMD) >> 7, PMD — регистр $19 с битом 7 (без бита 7 там AMD);
      * сдвиг ноты канала в 1/64 полутона: (…) >> (6 − PMS) при PMS < 6, иначе << (PMS − 5).
    Время — в сэмплах синтеза YM2151."""

    def __init__(self) -> None:
        self.rate = 0
        self.pmd = 0
        self.amd = 0
        self.wave = 0
        self.hold = False
        self.origin = 0                 # сэмпл, с которого счётчик растёт от base с текущей скоростью
        self.base = 0

    def increment(self) -> int:
        return (0x10 | (self.rate & 0x0F)) << (self.rate >> 4)

    def counter(self, time: int) -> int:
        if self.hold:
            return 0
        return self.base + self.increment() * max(0, time - self.origin)

    def write(self, time: int, register: int, value: int) -> bool:
        """Запись регистра LFO в момент time; True — запись отпустила сброс фазы."""
        if register == 0x01:
            hold = bool(value & 0x02)
            released = self.hold and not hold
            if hold or released:
                self.base, self.origin = 0, time
            self.hold = hold
            return released
        if register == 0x18:
            self.base, self.origin = self.counter(time), time
            self.rate = value
        elif register == 0x19:
            if value & 0x80:
                self.pmd = value & 0x7F
            else:
                self.amd = value & 0x7F
        elif register == 0x1B:
            self.wave = value & 0x03
        return False

    def raw_pm(self, time: int) -> int:
        """(pm · PMD) >> 7 в момент time."""
        if self.pmd == 0:
            return 0
        v = (self.counter(time) >> 22) & 0xFF
        if self.wave == 0:
            pm = v
        elif self.wave == 1:
            pm = (0 if v & 0x80 else 0xFF) ^ 0x80
        elif self.wave == 2:
            am = ((v << 1) if v & 0x80 else ((v ^ 0xFF) << 1)) & 0xFF
            pm = am if v & 0x40 else (~am & 0xFF)
        else:
            raise SystemExit("LFO: шумовая волна (W = 3) не переносится")
        pm = pm - 256 if pm & 0x80 else pm
        return (pm * self.pmd) >> 7

    @staticmethod
    def delta(raw_pm: int, pms: int) -> int:
        """Сдвиг ноты в 1/64 полутона при чувствительности PMS канала."""
        if pms == 0:
            return 0
        return raw_pm >> (6 - pms) if pms < 6 else raw_pm << (pms - 5)


class Voice:
    """Теневое состояние одного голоса OPM: тембр и текущая нота.

    Регистры хранятся в кодировке OPN, но БЕЗ номера канала — номер добавляется
    в момент выдачи, потому что канал у голоса может смениться.
    """

    def __init__(self) -> None:
        self.regs: dict[int, int] = {}      # смещение регистра OPN -> значение
        self.kc = 0
        self.kf = 0
        self.note = False                   # KC записан хотя бы раз
        self.pms = 0                        # чувствительность к PM (регистр $38+канал, биты 4…6)
        self.ams = 0                        # чувствительность к AM (биты 0…1)
        self.am_enable: dict[int, bool] = {}  # бит AMS-EN операторов
        # Последняя выданная частота: пара $A4/$A0 нужна, только когда нота
        # реально изменилась. Игра переписывает KC каждый тик, и без этой
        # проверки на пиках набиралось больше сотни записей за кадр.
        self.freq: tuple[int, int] | None = None
        # DT1|MUL и DT2 по слотам — нужны вместе, чтобы свернуть DT2 в MUL.
        self.dt1mul: dict[int, int] = {}
        self.dt2: dict[int, int] = {}


class Allocator:
    """Раздача восьми голосов OPM по шести каналам двух YM2203.

    Закрепление «липкое»: голос держит свой канал и после того, как нота
    отзвучала, — так переназначений, а с ними и перезаливок тембра, почти не
    происходит. Канал отбирается, только когда свободных нет, и жертвой
    выбирается тот, что не менялся дольше всех.
    """

    def __init__(self) -> None:
        self.assign: dict[int, int] = {}                  # голос OPM -> канал
        self.owner: list[int | None] = [None] * len(PHYS_CHANNELS)
        self.sounding = [False] * len(PHYS_CHANNELS)
        self.since = [0] * len(PHYS_CHANNELS)             # кадр последней смены
        self.moves = 0                                    # счётчик перезаливок

    def held_by(self, voice: int) -> int | None:
        """Канал, которым голос владеет прямо сейчас (иначе None)."""
        phys = self.assign.get(voice)
        return phys if phys is not None and self.owner[phys] == voice else None

    def acquire(self, voice: int, frame: int) -> tuple[int, bool]:
        """Вернуть (канал, потребовалась ли перезаливка тембра)."""
        phys = self.held_by(voice)
        if phys is not None:
            return phys, False
        free = [p for p in range(len(PHYS_CHANNELS)) if not self.sounding[p]]
        # Среди молчащих берём тот, что не трогали дольше всех. Если молчащих
        # нет, по тому же правилу выбирается жертва среди звучащих, и её нота
        # обрывается — на этом треке такое возможно 2.4 % времени.
        pool = free or list(range(len(PHYS_CHANNELS)))
        phys = min(pool, key=lambda p: self.since[p])
        previous = self.owner[phys]
        if previous is not None:
            self.assign.pop(previous, None)
        self.owner[phys] = voice
        self.assign[voice] = phys
        self.since[phys] = frame
        self.moves += 1
        return phys, True


LFO_REGISTERS = (0x01, 0x18, 0x19, 0x1B)

# Громкость музыки на плате (см. заголовок): 4 ступени TL несущих = +3.0 дБ.
MUSIC_BOOST_TL = 4
# Несущие операторы алгоритма OPN по смещению регистра TL: +0 — S1, +4 — S3, +8 — S2, +C — S4.
CARRIER_OFFSETS = {
    0: (0xC,), 1: (0xC,), 2: (0xC,), 3: (0xC,), 4: (0x8, 0xC), 5: (0x4, 0x8, 0xC), 6: (0x4, 0x8, 0xC),
    7: (0x0, 0x4, 0x8, 0xC),
}


def output_value(voice: "Voice", offset: int, value: int) -> int:
    """Значение регистра тембра для чипа: TL несущего оператора (по алгоритму голоса) — на MUSIC_BOOST_TL меньше."""
    if 0x40 <= offset <= 0x4C and (offset - 0x40) in CARRIER_OFFSETS[voice.regs.get(0xB0, 0) & 7]:
        return max(0, (value & 0x7F) - MUSIC_BOOST_TL)
    return value


def frame_rows(rows: list[tuple[int, int, int]]) -> tuple[list[tuple[int, int, int, int]], object]:
    """Лог MAME (кадр M72, регистр, значение) → строки convert и окно кадра: время записи — начало её кадра."""
    timed = [(frame, int(frame * OPM_SAMPLES_PER_FRAME), register, value) for frame, register, value in rows]

    def window(frame: int) -> tuple[int, int]:
        return int(frame * OPM_SAMPLES_PER_FRAME), int((frame + 1) * OPM_SAMPLES_PER_FRAME)

    return timed, window


def convert(rows: list[tuple[int, int, int, int]], frame_window, *, lfo_enabled: bool = True,
            quiet: bool = False, last_frame: int | None = None) -> list[tuple[int, int, int, int]]:
    """Журнал OPM → список (кадр, чип, регистр OPN, значение).

    rows — (кадр потока, время в сэмплах YM2151, регистр, значение) в порядке записи, кадры не убывают;
    frame_window(кадр) → (начало, конец) кадра в сэмплах YM2151; last_frame — последний кадр потока (по
    умолчанию — кадр последней записи): вибрато пересчитывается в каждом кадре до него, и в кадрах без записей
    журнала — на долгой ноте драйвер регистры не трогает, а LFO аркады идёт.

    Вибрато (Lfo): регистры LFO кадра применяются первыми, сдвиг ноты берётся в середине кадра, а если в кадре
    фаза LFO сброшена — в середине отрезка от сброса до конца кадра: в потоке нота звучит с начала своего
    кадра, а у аркады — с такта сброса. Сдвиг один на все записи частоты кадра. После записей кадра частоты
    всех звучащих голосов пересчитываются и выдаются, если изменились (фаза LFO сдвинулась, сменилась PMS или
    глубина). Частота ноты с вибрато — та же формула opn_note с дробью KF + сдвиг."""
    voices = [Voice() for _ in range(8)]
    alloc = Allocator()
    lfo = Lfo()
    out: list[tuple[int, int, int, int]] = []
    # Что уже лежит в регистрах чипов. Игра переписывает тембры теми же
    # значениями каждый тик; на аркадном железе это бесплатно, а у нас каждая
    # запись стоит двух OUT с обязательными паузами YM2203.
    written: dict[tuple[int, int], int] = {}

    def put(frame: int, phys: int, offset: int, value: int, force: bool = False) -> None:
        chip, channel = PHYS_CHANNELS[phys]
        reg = offset + channel
        if not force and written.get((chip, reg)) == value:
            return
        written[(chip, reg)] = value
        out.append((frame, chip, reg, value))

    def flush(frame: int, index: int, phys: int) -> None:
        """Перенести тембр и ноту голоса на выданный ему канал."""
        voice = voices[index]
        for offset, value in sorted(voice.regs.items()):
            put(frame, phys, offset, output_value(voice, offset, value), force=True)
        if voice.freq is not None:
            block, fnum = voice.freq
            put(frame, phys, 0xA4, (block << 3) | (fnum >> 8), force=True)
            put(frame, phys, 0xA0, fnum & 0xFF, force=True)

    def store(frame: int, index: int, offset: int, value: int) -> None:
        """Запомнить регистр тембра и выдать его, если голос уже на канале."""
        voice = voices[index]
        voice.regs[offset] = value
        phys = alloc.held_by(index)
        if phys is not None:
            put(frame, phys, offset, output_value(voice, offset, value))
            if offset == 0xB0:
                # Сменился алгоритм — сменились несущие: TL всех операторов канала заново (put пропустит те же).
                for tl in (0x40, 0x44, 0x48, 0x4C):
                    if tl in voice.regs:
                        put(frame, phys, tl, output_value(voice, tl, voice.regs[tl]))

    def pitch(voice: Voice, raw_pm: int) -> tuple[int, int] | None:
        """(block, F-Num) ноты голоса со сдвигом LFO; None — запрещённый код ноты OPM."""
        note = OPM_NOTE_INDEX.get(voice.kc & 0x0F)
        if note is None:
            return None
        shift = Lfo.delta(raw_pm, voice.pms) if lfo_enabled else 0
        # KF лежит в старших шести битах регистра $30-$37.
        return opn_note((voice.kc >> 4) & 0x07, note, OPN_CLOCK, (voice.kf >> 2) + shift)

    def emit_pitch(frame: int, index: int, raw_pm: int) -> None:
        voice = voices[index]
        freq = pitch(voice, raw_pm)
        if freq is None or voice.freq == freq:
            return                                        # нота не изменилась
        voice.freq = freq
        phys = alloc.held_by(index)
        if phys is None:
            return                                        # голос ещё без канала
        block, fnum = freq
        # Порядок обязателен: старший байт (block|F-Num hi) пишется первым,
        # чип защёлкивает частоту по записи младшего.
        put(frame, phys, 0xA4, (block << 3) | (fnum >> 8), force=True)
        put(frame, phys, 0xA0, fnum & 0xFF, force=True)

    groups: dict[int, list[tuple[int, int, int]]] = {}
    for frame, time, reg, value in rows:
        groups.setdefault(frame, []).append((time, reg, value))
    if not groups:
        return out
    if last_frame is None:
        last_frame = max(groups)

    for frame in range(min(groups), last_frame + 1):
        items = groups.get(frame, [])
        start, end = frame_window(frame)
        sample_from = start
        for time, reg, value in items:
            if reg in LFO_REGISTERS and lfo.write(time, reg, value):
                sample_from = max(sample_from, time)
        raw_pm = lfo.raw_pm(int((sample_from + end) // 2)) if lfo_enabled else 0

        for time, reg, value in items:
            if reg in LFO_REGISTERS:
                continue

            if reg == 0x08:                               # key-on/off
                index = value & 0x07
                operators = (value >> 3) & 0x0F
                voice = voices[index]
                if operators:
                    if (lfo_enabled and lfo.amd and voice.ams
                            and any(voice.am_enable.get(slot) for slot in range(OPERATOR_COUNT))):
                        raise SystemExit(f"кадр {frame}: у канала OPM {index} включено тремоло (AMD {lfo.amd}, "
                                         f"AMS {voice.ams}) — у YM2203 его нет, конвертер AM не переносит")
                    phys, moved = alloc.acquire(index, frame)
                    if moved:
                        flush(frame, index, phys)
                    alloc.sounding[phys] = True
                    alloc.since[phys] = frame
                else:
                    phys = alloc.held_by(index)
                    if phys is None:
                        continue
                    alloc.sounding[phys] = False
                    alloc.since[phys] = frame
                # У OPN номер канала лежит в самом значении $28, а не в адресе
                # регистра, поэтому put() вызывается со смещением, гасящим канал.
                channel = PHYS_CHANNELS[phys][1]
                put(frame, phys, 0x28 - channel,
                    (operators << 4) | channel, force=True)
                continue

            if 0x20 <= reg <= 0x27:                       # RL | FB | CONNECT
                index = reg - 0x20
                feedback = (value >> 3) & 0x07
                store(frame, index, 0xB0, (feedback << 3) | (value & 0x07))
                continue

            if 0x28 <= reg <= 0x2F or 0x30 <= reg <= 0x37:  # нота KC / дробная KF
                index = reg & 0x07
                voice = voices[index]
                if 0x28 <= reg <= 0x2F:
                    voice.kc = value
                    voice.note = True
                else:
                    voice.kf = value
                emit_pitch(frame, index, raw_pm)
                continue

            if 0x38 <= reg <= 0x3F:                       # PMS | AMS канала
                voice = voices[reg - 0x38]
                voice.pms = (value >> 4) & 0x07
                voice.ams = value & 0x03
                continue

            for opm_base, opn_base in OPERATOR_BASES:
                if opm_base <= reg < opm_base + 0x20:
                    index = reg & 0x07
                    slot = (reg - opm_base) >> 3
                    voice = voices[index]
                    converted = value
                    if opm_base == 0x40:                  # DT1|MUL
                        voice.dt1mul[slot] = value
                        converted = merge_dt2(voice, slot)
                    elif opm_base == 0xC0:                # DT2|D2R
                        voice.dt2[slot] = (value >> 6) & 3
                        converted = value & 0x1F          # у OPN только D2R
                        # DT2 изменился — переиздать MUL с новым коэффициентом.
                        store(frame, index, 0x30 + slot * 4, merge_dt2(voice, slot))
                    elif opm_base == 0xA0:                # AMS-EN|D1R -> AM|D1R
                        voice.am_enable[slot] = bool(value & 0x80)
                        converted = (value & 0x80) | (value & 0x1F)
                    store(frame, index, opn_base + slot * 4, converted)
                    break

        # Конец кадра: частоты звучащих голосов с новым сдвигом LFO.
        for index, voice in enumerate(voices):
            if voice.note and alloc.held_by(index) is not None:
                emit_pitch(frame, index, raw_pm)

    if not quiet:
        print(f"перезаливок тембра при смене канала: {alloc.moves}")
    return out


def drop_redundant(stream: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Выбросить записи, не меняющие состояние чипа.

    Игра переписывает тембровые регистры теми же значениями каждый тик — в
    исходном логе таких записей 73 %. На аркадном железе это бесплатно, а у нас
    каждая запись стоит двух OUT с обязательными паузами: на пиковых кадрах
    набиралось 114 записей, кадр переполнялся и звук рассыпался.
    Key-on ($28) и частота ($A0-$A7) сохраняются всегда: первый запускает ноту,
    вторая защёлкивается парой регистров и обязана идти целиком."""
    state: dict[tuple[int, int], int] = {}
    out = []
    for frame, chip, reg, value in stream:
        if reg == 0x28 or 0xA0 <= reg <= 0xA7:
            out.append((frame, chip, reg, value))
            continue
        if state.get((chip, reg)) == value:
            continue
        state[(chip, reg)] = value
        out.append((frame, chip, reg, value))
    return out


def encode_stream(stream: list[tuple[int, int, int, int]], *, loop_frame: int | None = None,
                  end_frame: int | None = None) -> bytes:
    """Список (кадр, чип, регистр, значение) → байты потока (формат — в описании модуля).

    Кадр каждой записи сохраняется точно: пауза блока отсчитывается от кадра предыдущего блока (первого — от
    кадра 0), долгая тишина дробится пустыми блоками по STREAM_MAX_WAIT, больше 255 записей кадра — несколько
    блоков с паузой 0. Прежняя версия переносила хвост тяжёлого кадра на следующий кадр паузой 1, не
    вычитая её из паузы следующего блока, — всё дальнейшее запаздывало на кадр; теперь кадр не режется, бюджет
    записей в кадр отчитывает генератор. Блок не пересекает границу страницы 16 КБ: плеер отображает страницу
    в окно и переходит на следующую по маркеру $FE.

    loop_frame — точка петли: на кадре loop_frame ставится пустой блок-якорь и маркер $FD $00, записи этого
    кадра идут следующим блоком с паузой 0. Первый проход проходит якорь как обычный блок; после последнего
    кадра потока плеер читает блоки сразу за маркером, и они звучат с кадра loop_frame следующего прохода
    (паузы после маркера отсчитываются от loop_frame в обоих случаях). Последний кадр потока задаёт end_frame
    (loop_frame + период − 1): пустой блок, если записей на нём нет."""
    by_frame: dict[int, list[tuple[int, int, int]]] = {}
    for frame, chip, reg, value in stream:
        by_frame.setdefault(frame, []).append((chip, reg, value))
    if end_frame is not None:
        if by_frame and max(by_frame) > end_frame:
            raise ValueError(f"запись на кадре {max(by_frame)} после последнего кадра {end_frame}")
        by_frame.setdefault(end_frame, [])
    if loop_frame is not None:
        by_frame.setdefault(loop_frame, [])
    data = bytearray()

    def append(chunk: bytes) -> None:
        """Добавить блок, не дав ему пересечь границу страницы."""
        room = STREAM_PAGE_SIZE - len(data) % STREAM_PAGE_SIZE
        if room < len(chunk) + 2:                         # +2 на маркер перехода
            data.extend((STREAM_PAGE, 0))
            data.extend(bytes(-len(data) % STREAM_PAGE_SIZE))
        data.extend(chunk)

    def block(wait: int, entries: list[tuple[int, int, int]]) -> None:
        for start in range(0, max(1, len(entries)), 255):
            part = entries[start:start + 255]
            append(bytes((wait if start == 0 else 0, len(part))) + b"".join(bytes(entry) for entry in part))

    previous = 0
    for frame in sorted(by_frame):
        if frame < 0:
            raise ValueError(f"отрицательный кадр {frame}")
        wait = frame - previous
        while wait > STREAM_MAX_WAIT:                     # долгая тишина
            block(STREAM_MAX_WAIT, [])
            wait -= STREAM_MAX_WAIT
        entries = by_frame[frame]
        if frame == loop_frame:
            block(wait, [])                               # якорь петли
            append(bytes((STREAM_LOOP, 0)))
            wait = 0
            if entries:
                block(wait, entries)
        else:
            block(wait, entries)
        previous = frame
    append(bytes((STREAM_END, 0)))
    return bytes(data)


def emit(stream: list[tuple[int, int, int, int]], bin_path: Path, inc_path: Path) -> None:
    """Поток из лога MAME: [кадров ожидания][счётчик][чип,регистр,значение]…

    Начальная тишина отбрасывается. В логе MAME музыка стартует только после
    POST и вставленной монеты (первая нота — кадр 652), и если оставить эту
    паузу, игрок ждёт больше десяти секунд молчания. Настройки тембров, которые
    игра успела записать ДО первой ноты, сохраняются и выдаются в первом же
    блоке — иначе ноты заиграли бы на неинициализированных операторах."""
    first_note = min((f for f, _, reg, val in stream
                      if reg == 0x28 and (val >> 4)), default=None)
    if first_note is not None:
        stream = [(max(0, frame - first_note), chip, reg, value) for frame, chip, reg, value in stream]
    data = encode_stream(stream)

    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(data)

    frames = [frame for frame, _, _, _ in stream]
    inc = [
        "; ═══ СГЕНЕРИРОВАНО ym2151_to_tsfm.py — не редактировать вручную ═══",
        "; Музыка R-Type, перенесённая с YM2151 (OPM) на TurboSound FM (2×YM2203).",
        "; Формат потока: [пауза в кадрах][число записей][чип,регистр,значение]…,",
        "; конец потока — пауза $FF при нулевом числе записей.",
        "",
        f"TSFM_STREAM_SIZE   EQU {len(data)}",
        f"TSFM_STREAM_FRAMES EQU {max(frames) - min(frames) if frames else 0}",
        f"TSFM_STREAM_EVENTS EQU {len(stream)}",
        "",
    ]
    inc_path.write_text("\n".join(inc) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN)
    parser.add_argument("--inc", type=Path, default=DEFAULT_INC)
    args = parser.parse_args()

    if not args.log.exists():
        raise SystemExit(f"нет лога YM2151: {args.log} — сначала mame_ym2151_log.lua")
    rows = [(int(r["frame"]), int(r["register"], 16), int(r["value"], 16))
            for r in csv.DictReader(args.log.open(encoding="utf-8"))]
    timed, window = frame_rows(rows)
    stream = convert(timed, window)
    emit(stream, args.bin, args.inc)

    chips = {}
    for _, chip, _, _ in stream:
        chips[chip] = chips.get(chip, 0) + 1
    print(f"исходных записей OPM: {len(rows)}")
    print(f"событий для TSFM: {len(stream)} "
          f"(чип 0: {chips.get(0, 0)}, чип 1: {chips.get(1, 0)})")
    print(f"поток: {args.bin} ({args.bin.stat().st_size} Б)")
    print(f"inc:   {args.inc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
