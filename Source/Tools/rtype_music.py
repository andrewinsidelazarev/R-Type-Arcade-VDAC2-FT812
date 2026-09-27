"""Потоки TurboSound FM всех мелодий R-Type из оракула: исходная программа звукового Z80 и ymfm YM2151.

Источник — rtype_m72.sound.M72SoundSystem: программа звукового ЦП World ROM (Build/Analysis/rtype_sound_upload.bin)
на эмуляторе Z80 и YM2151 из ymfm; таймер A оракула исправлен 2026-09-16 (темп совпал с драйвером и MAME).
Прежние потоки были записями MAME по одной команде в окне 218 с: мелодия повторялась с начала вместе со
вступлением, конец окна рвал фразу, а команда замены попала в запись посреди чужого звука.

Мелодия (команда из rtype_port.audio.MUSIC_STREAMS):
  1. декодер драйвера (m72_sound_driver.command_shape) — период петли T в тактах (НОК периодов частей) или конец;
  2. оракул пишет журнал YM2151 по тактам драйвера (driver_tick: такт, обработку которого начал главный цикл;
     такт — 224 сэмпла YM2151, 249.69 Гц);
  3. начало периодичности a — первый такт, с которого записи каждого такта повторяются через T до конца журнала
     (не меньше VERIFY_PASSES − 1 проходов сравнения); у первого прохода переход из вступления сдвигает ноты;
  4. точка петли a' ≥ a — первый такт, где состояние YM2151 (регистры, нажатые операторы) и фаза LFO (счётчик по
     модулю 2^30) совпадают с состоянием через T. Поток — такты [0, a' + T), повтор с a': воспроизведение совпадает
     с аркадой запись в запись. Если фаза LFO не повторяется (LFO без сброса), a' берётся по регистрам, а
     фаза вибрато на шве петли расходится с аркадой — отчёт отмечает это;
  5. такты → кадры потока: у петли кадр = (такт·P + c) // T, P = round(T · кадров на такт), c ставит начало петли
     на границу кадра (петля ровно P кадров; темп отличается от аркады на |T·r − P| / (T·r) — в отчёте); без
     петли — такт · r, r = 55.018 / 249.69;
  6. ym2151_to_tsfm.convert (DT2 → MUL, программный LFO) и encode_stream с маркером петли;
  7. проверка: поток с петлёй, развёрнутый на VERIFY_PASSES проходов, после переноса баса в SSG (tsfm_bass) кадр в
     кадр совпадает с линейным потоком тех же проходов.

Мелодия без петли ($1C, $22, $2B) — все записи до конца мелодии. Команда замены (тип $10: $02, $05, …, общий поток
REPLACE_STREAM) — записи драйвера после $02, поданной во время мелодии $01: снятие нот и RR = $F на её каналах.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python', ROOT / 'Build' / 'PythonDeps'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import m72_sound_driver                                          # noqa: E402
import rtype_sound                                               # noqa: E402
import ym2151_to_tsfm as opm                                     # noqa: E402
from rtype_m72.sound import M72SoundSystem                      # noqa: E402
from rtype_port import audio, tsfm, tsfm_bass                    # noqa: E402

REPORT_PATH = ROOT / 'Build' / 'Arcade' / 'Music' / 'rtype_music.json'
# $1F пишется в отдельный файл: STAGE1_TSFM.bin (tsfm.DEFAULT_STREAM) остаётся прежнему плееру tsfm_music.asm
# (build.cmd), который маркера петли $FD не знает; audio.MUSIC_STREAMS указывает на новый файл.
COMMAND_1F_STREAM = audio.MUSIC_DIR / 'COMMAND_1F_TSFM.bin'
TRASH = ROOT / '.to-delete'
TICK_SAMPLES = 224                                  # сэмплов YM2151 на такт драйвера (таймер A, TA = 800)
FRAMES_PER_TICK = opm.M72_FRAME_RATE / (opm.OPM_SAMPLE_RATE / TICK_SAMPLES)
TIMER_REGISTERS = frozenset((0x10, 0x11, 0x12, 0x13, 0x14))   # таймеры драйвера: звука не касаются
VERIFY_PASSES = 3
INTRO_RESERVE = 512                                 # тактов журнала сверх проходов: на вступление
TAIL_TICKS = 256                                    # тактов после конца мелодии без петли
REPLACE_OWNER = 0x01                                # замена $02 снимает дорожки мелодии $01
REPLACE_COMMAND = 0x02
REPLACE_AFTER = 1024                                # тактов мелодии до команды замены
BUDGET_WRITES = 120                                 # записей в кадр: больше — строка в отчёте
DRIVER_PENDING_TICKS = 0xF801                       # тактов к обработке: +1 в прерывании таймера, −1 в главном цикле
MAX_LOG_PASSES = 12                                 # журнал не длиннее вступления и 12 периодов: без роста памяти


def driver_tick(sound: M72SoundSystem) -> int:
    """Такт драйвера, обработку которого начал главный цикл: прерывание таймера ($0076) пишет $14 и увеличивает
    счётчик DRIVER_PENDING_TICKS, главный цикл ($02E8) уменьшает его и проходит 16 дорожек при разрешённых
    прерываниях. Число переполнений таймера для журнала не годится: когда обработка такта затягивается, часть
    его записей приходится на следующее переполнение, и проходы петли расходились на такт (у $04 — десятки мест)."""
    return sound.timer_a_irqs - sound.cpu.memory[DRIVER_PENDING_TICKS]


def oracle_log(commands: list[tuple[int, int]]) -> tuple[list[tuple[int, int, int]], list[int], bytes]:
    """Команды подряд [(команда, тактов после неё)] → журнал (такт драйвера от первой команды, регистр, значение)
    без регистров таймеров, такты подачи команд, регистры YM2151 перед первой командой (после сброса драйвера)."""
    sound = M72SoundSystem(output=False)
    try:
        initial = sound.ym_registers
        sound.write_log = []
        sound.write_tick = lambda: driver_tick(sound)
        base = driver_tick(sound)
        marks = []
        for command, ticks in commands:
            marks.append(driver_tick(sound) - base)
            sound.command(command)
            stop = sound.timer_a_overflows + ticks
            while sound.timer_a_overflows < stop:
                sound.step_frame()
        log = [(tick - base, register, value) for tick, register, value in sound.write_log
               if register not in TIMER_REGISTERS]
        return log, marks, initial
    finally:
        sound.close()


def periodic_start(log: list[tuple[int, int, int]], period: int, ticks: int) -> int:
    """Первый такт a, с которого записи каждого такта [a, ticks − T) равны записям через T."""
    by_tick: list[list[tuple[int, int]]] = [[] for _ in range(ticks)]
    for tick, register, value in log:
        if tick < ticks:
            by_tick[tick].append((register, value))
    start = 0
    for tick in range(ticks - period):
        if by_tick[tick] != by_tick[tick + period]:
            start = tick + 1
    if ticks - period - start < (VERIFY_PASSES - 1) * period:
        raise SystemExit(f'записи не повторяются с периодом {period} тактов: последнее расхождение на такте '
                         f'{start - 1} из {ticks}')
    return start


def register_states(log: list[tuple[int, int, int]], initial: bytes, ticks: int) -> tuple[list[bytes], list[int]]:
    """Для t = 0…ticks: состояние YM2151 перед записями такта t (256 регистров, PMD — в ячейке $1A, как у ymfm,
    плюс маски нажатых операторов 8 каналов) и фаза LFO — счётчик по модулю 2^30 (значение LFO — его биты
    22…29; −1 — счётчик держится сбросом). Модель LFO — та же, что у конвертера (ym2151_to_tsfm.Lfo), отсчёт
    от команды. Фаза повторяется и без сбросов, если шаг счётчика за период петли кратен 2^30: у Stage 1
    (LFRQ $C8) 9216 тактов · 224 сэмпла · 98304 = 189 · 2^30."""
    registers = bytearray(initial)
    keys = bytearray(8)
    lfo = opm.Lfo()
    lfo.rate = initial[0x18]
    lfo.wave = initial[0x1B] & 0x03
    states: list[bytes] = []
    phases: list[int] = []
    index = 0
    for tick in range(ticks + 1):
        while index < len(log) and log[index][0] < tick:
            at, register, value = log[index]
            index += 1
            if register in opm.LFO_REGISTERS:
                lfo.write(at * TICK_SAMPLES, register, value)
            if register == 0x08:
                keys[value & 7] = (value >> 3) & 0x0F
            elif register == 0x01:                  # сброс LFO — действие: фаза учитывается отдельно
                pass
            elif register == 0x19:
                registers[0x19 + (value >> 7)] = value & 0x7F
            else:
                registers[register] = value
        states.append(bytes(registers) + bytes(keys))
        phases.append(-1 if lfo.hold else lfo.counter(tick * TICK_SAMPLES) & 0x3FFFFFFF)
    return states, phases


class TickFrames:
    """Такты драйвера → кадры потока и окно кадра в сэмплах YM2151 (для выборки LFO).

    Сдвиг c, ставящий начало петли на границу кадра, может унести первые такты мелодии в кадр 1 (так было у $1F):
    весь поток запаздывал на кадр, и шаг команды проходил без записей. Поэтому кадры считаются от кадра первой
    записи first_tick — сдвиг целиком, петля остаётся на границе кадра и длиной P."""

    def __init__(self, period: int | None = None, loop_tick: int = 0, first_tick: int = 0) -> None:
        if period is None:
            self.numerator, self.denominator, self.offset = FRAMES_PER_TICK.numerator, FRAMES_PER_TICK.denominator, 0
        else:
            self.numerator = round(period * FRAMES_PER_TICK)
            self.denominator = period
            self.offset = (-loop_tick * self.numerator) % period
        self.shift = 0
        self.shift = self.frame(first_tick)

    def frame(self, tick: int) -> int:
        return (tick * self.numerator + self.offset) // self.denominator - self.shift

    def window(self, frame: int) -> tuple[Fraction, Fraction]:
        def edge(value: int) -> Fraction:
            return Fraction((value + self.shift) * self.denominator - self.offset, self.numerator) * TICK_SAMPLES
        return edge(frame), edge(frame + 1)


def convert(log: list[tuple[int, int, int]], frames: TickFrames, limit: int, *,
            lfo: bool = True) -> list[tuple[int, int, int, int]]:
    """Записи тактов [0, limit) → записи YM2203 (кадр, чип, регистр, значение)."""
    rows = [(frames.frame(tick), tick * TICK_SAMPLES, register, value)
            for tick, register, value in log if tick < limit]
    # Последний кадр — кадр такта limit − 1 (кадров на такт меньше одного). У петли limit — начало прохода, и кадр
    # такта limit начинается ровно на нём (TickFrames), так что это кадр перед петлёй.
    return opm.convert(rows, frames.window, lfo_enabled=lfo, quiet=True, last_frame=frames.frame(limit - 1))


def expand(events: dict, frame_count: int, loop_frame: int, passes: int) -> dict:
    """Кадры потока с петлёй, развёрнутые на passes проходов петли."""
    period = frame_count - loop_frame
    out = {frame: writes for frame, writes in events.items() if frame < loop_frame}
    for number in range(passes):
        for frame, writes in events.items():
            if frame >= loop_frame:
                out[frame + number * period] = writes
    return out


def first_difference(a: dict, b: dict) -> int | None:
    frames = sorted(set(a) | set(b))
    return next((frame for frame in frames if a.get(frame) != b.get(frame)), None)


def verify_loop(log, frames: TickFrames, loop_tick: int, period: int, *, lfo: bool) -> tuple[bytes, dict]:
    """Поток с петлёй и его сверка с линейным потоком VERIFY_PASSES проходов (до и после переноса баса)."""
    loop_frame = frames.frame(loop_tick)
    frames_per_pass = frames.frame(loop_tick + period) - loop_frame
    looped = opm.encode_stream(convert(log, frames, loop_tick + period, lfo=lfo),
                               loop_frame=loop_frame, end_frame=loop_frame + frames_per_pass - 1)
    total = loop_frame + VERIFY_PASSES * frames_per_pass
    linear = opm.encode_stream(convert(log, frames, loop_tick + VERIFY_PASSES * period, lfo=lfo),
                               end_frame=total - 1)
    result = {}
    # Бас выбирается по потоку с петлёй, как при упаковке (rtype_sound.py); линейному задаётся тот же канал.
    bass = tsfm_bass.bass_channel(looped)
    stages = [('YM2203', looped, linear)]
    if bass is not None:
        stages.append(('бас в SSG', tsfm_bass.move_bass_to_ssg(looped, bass), tsfm_bass.move_bass_to_ssg(linear, bass)))
    for stage, a, b in stages:
        events, count = tsfm.decode_stream(a)
        if tsfm.stream_loop_frame(a) != loop_frame or count != loop_frame + frames_per_pass:
            raise SystemExit(f'{stage}: петля потока не на месте ({tsfm.stream_loop_frame(a)}, {count})')
        unrolled = expand(events, count, loop_frame, VERIFY_PASSES)
        reference, reference_count = tsfm.decode_stream(b)
        if reference_count != total:
            raise SystemExit(f'{stage}: линейный поток {reference_count} кадров вместо {total}')
        result[stage] = first_difference(unrolled, reference)
    result.setdefault('бас в SSG', result['YM2203'])              # без баса поток не меняется
    result['бас'] = bass
    return looped, result


def budget(data: bytes) -> tuple[int, int, int]:
    """(наибольшее число записей в кадр, его кадр, кадров с записями больше BUDGET_WRITES) после переноса баса."""
    events, _ = tsfm.decode_stream(tsfm_bass.move_bass_to_ssg(data))
    if not events:
        return 0, 0, 0
    frame = max(events, key=lambda key: len(events[key]))
    return len(events[frame]), frame, sum(len(writes) > BUDGET_WRITES for writes in events.values())


def vibrato_channels(log: list[tuple[int, int, int]]) -> list[int]:
    """Каналы OPM, у которых PMS ≠ 0 записана при PMD ≠ 0 хоть раз."""
    pmd = 0
    channels = set()
    for _, register, value in log:
        if register == 0x19 and value & 0x80:
            pmd = value & 0x7F
        elif 0x38 <= register <= 0x3F and (value >> 4) & 7 and pmd:
            channels.add(register - 0x38)
    return sorted(channels)


def looped_song(command: int, period: int) -> tuple[bytes, dict]:
    ticks = INTRO_RESERVE + (VERIFY_PASSES + 2) * period
    while True:
        log, _, initial = oracle_log([(command, ticks + 8)])
        try:
            start = periodic_start(log, period, ticks)
        except SystemExit:
            if ticks + period > INTRO_RESERVE + MAX_LOG_PASSES * period:
                raise
            ticks += period                              # вступление длиннее запаса
            continue
        if start + (VERIFY_PASSES + 1) * period <= ticks:
            break
        ticks = start + (VERIFY_PASSES + 1) * period + INTRO_RESERVE
    states, phases = register_states(log, initial, ticks)
    loop_tick = next((tick for tick in range(start, start + period + 1)
                      if states[tick] == states[tick + period] and phases[tick] == phases[tick + period]), None)
    lfo_phase = loop_tick is not None
    if loop_tick is None:
        loop_tick = next(tick for tick in range(start, start + period + 1) if states[tick] == states[tick + period])
    frames = TickFrames(period, loop_tick, log[0][0])
    data, checks = verify_loop(log, frames, loop_tick, period, lfo=True)
    vibrato = vibrato_channels(log)
    exact = checks['бас в SSG'] is None
    info = {
        'петля': True, 'период_тактов': period, 'периодичность_с_такта': start, 'петля_с_такта': loop_tick,
        'петля_с_кадра': frames.frame(loop_tick), 'кадров_петли': frames.frame(loop_tick + period) - frames.frame(loop_tick),
        'темп_петли_отклонение': float(Fraction(frames.numerator) / (period * FRAMES_PER_TICK) - 1),
        'вибрато_каналы_OPM': vibrato, 'фаза_LFO_повторяется': lfo_phase or not vibrato,
        'бас_SSG': checks['бас'], 'сверка_YM2203': checks['YM2203'], 'сверка_после_баса': checks['бас в SSG'],
    }
    if not exact:
        # Расходятся ли проходы только вибрато: та же сверка без LFO.
        _, plain = verify_loop(log, frames, loop_tick, period, lfo=False)
        info['сверка_без_LFO'] = plain['бас в SSG']
        if plain['бас в SSG'] is not None or lfo_phase:
            raise SystemExit(f'${command:02X}: развёрнутая петля расходится с линейным потоком на кадре '
                             f'{checks["бас в SSG"]} (без LFO — {plain["бас в SSG"]})')
    return data, info


def one_shot_song(command: int, end_tick: int) -> tuple[bytes, dict]:
    log, _, _ = oracle_log([(command, end_tick + TAIL_TICKS)])
    last = max(tick for tick, _, _ in log)
    if last >= end_tick + TAIL_TICKS - 8:
        raise SystemExit(f'${command:02X}: записи не кончились за {TAIL_TICKS} тактов после конца мелодии')
    frames = TickFrames()
    data = opm.encode_stream(convert(log, frames, last + 1))
    return data, {'петля': False, 'конец_такт_декодера': end_tick, 'последний_такт_записей': last,
                  'вибрато_каналы_OPM': vibrato_channels(log)}


def replace_stream() -> tuple[bytes, dict]:
    log, marks, _ = oracle_log([(REPLACE_OWNER, REPLACE_AFTER), (REPLACE_COMMAND, TAIL_TICKS)])
    at = marks[1]
    rows = [(-1 if tick < at else int((tick - at) * FRAMES_PER_TICK), tick * TICK_SAMPLES, register, value)
            for tick, register, value in log]
    frames = TickFrames()
    stream = [entry for entry in opm.convert(rows, lambda frame: frames.window(max(frame, 0)), quiet=True)
              if entry[0] >= 0]
    after = [(tick - at, register, value) for tick, register, value in log if tick >= at]
    return opm.encode_stream(stream), {'петля': False, 'владелец': f'${REPLACE_OWNER:02X}',
                                       'записей_YM2151_после_команды': len(after)}


def retire(path: Path) -> None:
    """Прежний поток — в корзину проекта по тому же относительному пути (однажды: первую версию)."""
    if not path.is_file():
        return
    target = TRASH / path.relative_to(ROOT)
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--commands', help='только эти команды через запятую (например 0x1F,0x22)')
    parser.add_argument('--no-write', action='store_true', help='только разбор и проверки, без записи потоков')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    driver = m72_sound_driver.Driver()
    wanted = None if args.commands is None else {int(value, 0) for value in args.commands.split(',')}
    jobs: list[tuple[int, Path]] = [(command, COMMAND_1F_STREAM if command == 0x1F else path)
                                    for command, path in sorted(audio.MUSIC_STREAMS.items())]
    jobs.append((REPLACE_COMMAND, audio.REPLACE_STREAM))
    outputs: list[tuple[Path, bytes]] = []
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8')) if REPORT_PATH.is_file() else {}
    limit = rtype_sound.TRACK_PAGES * rtype_sound.PAGE
    for command, path in jobs:
        if wanted is not None and command not in wanted:
            continue
        if command == REPLACE_COMMAND:
            data, info = replace_stream()
        else:
            kind, value = driver.command_shape(command)
            data, info = looped_song(command, value) if kind == 'петля' else one_shot_song(command, value)
        packed = tsfm_bass.move_bass_to_ssg(data)
        if len(packed) > limit:
            raise SystemExit(f'${command:02X}: {len(packed)} байт — больше {rtype_sound.TRACK_PAGES} страниц буфера')
        _, frame_count = tsfm.decode_stream(packed)
        peak, peak_frame, heavy = budget(data)
        info.update(файл=path.name, байт=len(data), байт_в_паке=len(packed), кадров=frame_count,
                    записей_в_кадр_наибольшее=peak, кадр_наибольшего=peak_frame, кадров_тяжелее_бюджета=heavy)
        report[f'${command:02X}'] = info
        loop = (f'петля с кадра {info["петля_с_кадра"]} по {info["кадров_петли"]} кадров (такт {info["петля_с_такта"]}, '
                f'период {info["период_тактов"]}, темп {info["темп_петли_отклонение"] * 100:+.3f} %)'
                if info['петля'] else 'без петли')
        notes = ''
        if info['петля']:
            exact = info['сверка_после_баса'] is None
            notes += ', развёрнутая петля = линейный поток' if exact else (
                f', проходы расходятся с кадра {info["сверка_после_баса"]} (без LFO — {info.get("сверка_без_LFO")})')
        if info.get('вибрато_каналы_OPM'):
            notes += f', вибрато на каналах OPM {info["вибрато_каналы_OPM"]}'
            if info['петля'] and not info['фаза_LFO_повторяется']:
                notes += ' (фаза LFO на шве петли не повторяется)'
        print(f'${command:02X} {path.name}: {frame_count} кадров, {len(packed)} байт в паке, {loop}; '
              f'записей в кадр до {peak} (кадр {peak_frame}), тяжелее {BUDGET_WRITES}: {heavy}{notes}')
        outputs.append((path, data))
    if not args.no_write:
        # Потоки пишутся только после проверки всех мелодий: сборка посреди прогона не возьмёт смесь.
        for path, data in outputs:
            retire(path)
            path.write_bytes(data)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
