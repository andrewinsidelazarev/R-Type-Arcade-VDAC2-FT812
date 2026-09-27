"""Перенос басовой партии TSFM из FM-части YM2203 в SSG-часть — отступление от аркады, С 2026-09-17 ВЫКЛЮЧЕНО
(BASS_TO_SSG = False): потоки идут с басом на FM, как у аркады.

Зачем делалось (2026-09-16): на двух YM2203 басовый FM-патч R-Type звучит как в аркаде (спектры совпадают в пределах
0.6 дБ по полосам), но на обычных колонках низа почти не слышно. SSG-часть обоих чипов в музыке
не используется, поэтому бас переносился туда.

Почему выключено (пользователь 2026-09-17: «TSFM музыка от оригинала далеко. Особенно это ощущается во вступлении
первой мелодии»): сравнение формы спектра полосами 1/3 октавы с аркадой ($1F: журнал MAME через ymfm YM2151 против
потока через модель платы tsfm_core) — запись OST отличается от ymfm на 0.6…0.9 дБ, поток с басом на FM — на 0.3…1.1
дБ, с басом в SSG — на 1.1…4.7 дБ; хуже всего вступление 0…2 с: полосы 200…250 Гц +18 дБ, 500 Гц +9 дБ, основной тон
80 Гц −8 дБ — призвуки SSG, которых у FM-баса нет. Рецепт и функции оставлены: включение — BASS_TO_SSG = True.

Тембр подобран перебором возможностей SSG по совпадению с басом YM2151 (скрипт ssg_sweep3.py в рабочем
каталоге сессии, 2026-09-16). Кандидат играет те же 120 нот басовой партии Stage 1 с тем же ритмом (ноты
через 7 кадров, удержание 6) через модель платы, окно ноты 0.1 с; мера — спектр полосами 1/24 октавы
30 Гц…12 кГц, плоскостность спектра 0.5…6 кГц (отличает шум от призвуков), форма громкости внутри ноты и
громкость нот по высоте. Первый рецепт (перебор по узлам гармонической сетки, окна на 2–3 ноты) выбрал
шум SSG — на слух это треск; мера новой версии шум отвергает.

Рецепт — таблица голосов VOICES: у каждого голоса чип и канал (на плате A → левый, C → правый, B → оба),
тон — множитель частоты ноты, огибающая — форма и множитель частоты ноты (повторяющаяся огибающая
работает как форма волны), шум, громкость (если огибающей нет). Регистры шума, огибающей и микшера у
чипа общие.

Басом считается физический FM-канал с самой низкой медианой ноты, если медиана ниже BASS_MAX_HZ и нот
не меньше BASS_MIN_NOTES; иначе поток не меняется. Одинаковые подряд записи регистров SSG
отбрасываются (кроме формы огибающей #0D — её запись перезапускает огибающую), чтобы поток не
разрастался за 7 страниц буфера адаптера.

Функция move_bass_to_ssg используется и эталоном (tsfm.TsfmEmulator), и генератором пака
(Source/Tools/rtype_sound.py): записи в чипы у Z80 и у эталона остаются одинаковыми. ssg_fade_tables —
таблицы затухания SSG для адаптера (у эталона затухание — усиление PCM, у YM2203 общего усиления нет).
"""
from __future__ import annotations

import math
import statistics
from typing import NamedTuple

import numpy as np

PAGE = 0x4000
PAGE_MARKER = 0xFE
END_MARKER = 0xFF
LOOP_MARKER = 0xFD               # точка петли ($FD $00) — переносится в том же месте потока

TSFM_CLOCK = 3_500_000           # YM2203 платы ZX-MultiSound (ym_m = 32 МГц × 7/64)
FM_PRESCALE = 6                  # плеер ставит $2D
SSG_CLOCK = TSFM_CLOCK // 2      # при прескалере 1/6 SSG ведёт себя как AY на 1.75 МГц

BASS_TO_SSG = False              # перенос баса в SSG (см. описание модуля): выключен 2026-09-17 — бас на FM, как у аркады
BASS_MAX_HZ = 180.0
BASS_MIN_NOTES = 20
LOOP_WEIGHT = 4                  # вес нот тела петли при выборе баса (_bass_channel)


class Voice(NamedTuple):
    chip: int
    channel: int                  # 0 — A, 1 — B, 2 — C
    tone: float | None            # множитель частоты ноты для тона SSG; None — тон выключен
    env: tuple[int, float] | None  # (форма #08…#0F, множитель частоты ноты для цикла огибающей)
    shared_env: bool = False      # огибающая чипа от другого голоса
    noise: int | None = None      # период шума; None — шум выключен
    volume: int = 15              # громкость без огибающей


# Рецепт перебора (ssg_sweep3.py — 25 392 варианта, уточнение ssg_refine.py — 3 372; 2026-09-16), итог меры 7.6
# против 30.1 у первого рецепта с шумом. Оба голоса по центру (канал B платы идёт в L и R):
#   * тон ×6, пила вверх #0C с циклом ×0.5: пила на октаву ниже ноты (у аркадного патча есть оператор ×0.5),
#     умноженная на меандр 6f, — призвуки вокруг 6f, как от оператора ×6;
#   * тон ×1.5, пила вниз #08 с циклом ×1 — заполняет середину спектра.
# Шума нет. Огибающие не быстрее ×1: период огибающей в 16 раз грубее тона, её частота отклоняется от
# нужной на долю, растущую с частотой; при огибающей ×4 боковые полосы уходили в среднем на 15 Гц
# (дребезг), здесь — 0.58 Гц (медленные биения). Лучший вариант без этого ограничения (7.24) отброшен.
VOICES: tuple[Voice, ...] = (
    Voice(chip=0, channel=1, tone=6.0, env=(0x0C, 0.5)),
    Voice(chip=1, channel=1, tone=1.5, env=(0x08, 1.0)),
)

R_TONE = {0: (0x00, 0x01), 1: (0x02, 0x03), 2: (0x04, 0x05)}
R_VOLUME = {0: 0x08, 1: 0x09, 2: 0x0A}
R_NOISE, R_MIXER = 0x06, 0x07
R_ENV_LOW, R_ENV_HIGH, R_ENV_SHAPE = 0x0B, 0x0C, 0x0D
VOLUME_ENVELOPE = 0x10


def _parse(data: bytes) -> list[tuple[int | None, list[tuple[int, int, int]]]]:
    """Блоки потока (пауза, записи); маркер петли — (None, [])."""
    blocks, index, page = [], 0, 0
    while index + 1 < len(data):
        pause = data[index]
        if pause == END_MARKER and data[index + 1] == 0x00:
            break
        if pause == PAGE_MARKER:
            page += 1
            index = page * PAGE
            continue
        if pause == LOOP_MARKER:
            blocks.append((None, []))
            index += 2
            continue
        count = data[index + 1]
        index += 2
        events = [(data[index + 3 * n], data[index + 3 * n + 1], data[index + 3 * n + 2])
                  for n in range(count)]
        index += 3 * count
        blocks.append((pause, events))
    return blocks


def _emit(blocks) -> bytes:
    out, page_start = bytearray(), 0
    for pause, events in blocks:
        for start in range(0, max(1, len(events)), 255):   # в блоке не больше 255 записей
            part = events[start:start + 255]
            if pause is None:
                chunk = bytes([LOOP_MARKER, 0x00])
            else:
                chunk = bytes([pause if start == 0 else 0, len(part)]) + b''.join(bytes(e) for e in part)
            if len(out) - page_start + len(chunk) > PAGE - 2:
                out.append(PAGE_MARKER)
                out += b'\x00' * (PAGE - (len(out) - page_start))
                page_start = len(out)
            out += chunk
    out += bytes([END_MARKER, 0x00])
    return bytes(out)


def _frequency(block: int, fnum: int) -> float:
    divisor = TSFM_CLOCK * (2 ** (block - 1)) if block else TSFM_CLOCK / 2
    return fnum * divisor / ((1 << 20) * 12 * FM_PRESCALE)


def _bass_channel(blocks) -> tuple[int, int] | None:
    """Ноты тела петли (после маркера $FD) считаются LOOP_WEIGHT раз: петля звучит многократно, а у короткой
    петли в одном проходе нот меньше BASS_MIN_NOTES (у $16 — 4.7 с), и бас без веса остался бы в FM."""
    high, low, notes = {}, {}, {}
    weight = 1
    for pause, events in blocks:
        if pause is None:
            weight = LOOP_WEIGHT
        for chip, register, value in events:
            if 0xA4 <= register <= 0xA6:
                high[(chip, register - 0xA4)] = value
            elif 0xA0 <= register <= 0xA2:
                low[(chip, register - 0xA0)] = value
            elif register == 0x28 and value & 0xF0 and value & 3 < 3:
                key = (chip, value & 3)
                if key in high and key in low:
                    notes.setdefault(key, []).extend(
                        [_frequency((high[key] >> 3) & 7, ((high[key] & 7) << 8) | low[key])] * weight)
    medians = {key: statistics.median(values) for key, values in notes.items()
               if len(values) >= BASS_MIN_NOTES}
    if not medians:
        return None
    key = min(medians, key=medians.get)
    return key if medians[key] < BASS_MAX_HZ else None


def bass_channel(data: bytes) -> tuple[int, int] | None:
    """(чип, канал) FM-канала, который move_bass_to_ssg переносит в SSG; None — поток не меняется (и при
    выключенном переносе BASS_TO_SSG)."""
    if not BASS_TO_SSG:
        return None
    return _bass_channel(_parse(data))


def _tone_period(frequency: float, multiplier: float) -> int:
    return min(4095, max(1, round(SSG_CLOCK / (16 * frequency * multiplier))))


def _env_period(frequency: float, multiplier: float) -> int:
    return min(0xFFFF, max(1, round(SSG_CLOCK / (256 * frequency * multiplier))))


def _voice_on(frequency: float) -> list[tuple[int, int, int]]:
    """Записи SSG на нажатие ноты: тон, шум, огибающая (форма перезапускает её), микшеры чипов и последними
    громкости — голос включается уже настроенным, остатки регистров прошлой мелодии не звучат."""
    events, mixers, volumes = [], {}, []
    for voice in VOICES:
        chip, channel = voice.chip, voice.channel
        mixer = mixers.setdefault(chip, 0b00111111)
        if voice.tone:
            period = _tone_period(frequency, voice.tone)
            low, high = R_TONE[channel]
            events += [(chip, low, period & 0xFF), (chip, high, period >> 8)]
            mixer &= ~(1 << channel)
        if voice.noise:
            events.append((chip, R_NOISE, voice.noise))
            mixer &= ~(1 << (3 + channel))
        mixers[chip] = mixer & 0xFF
        if voice.env:
            shape, multiplier = voice.env
            envelope = _env_period(frequency, multiplier)
            events += [(chip, R_ENV_LOW, envelope & 0xFF), (chip, R_ENV_HIGH, envelope >> 8),
                       (chip, R_ENV_SHAPE, shape)]
        if voice.env or voice.shared_env:
            volumes.append((chip, R_VOLUME[channel], VOLUME_ENVELOPE))
        else:
            volumes.append((chip, R_VOLUME[channel], voice.volume))
    events += [(chip, R_MIXER, mixer) for chip, mixer in mixers.items()]
    return events + volumes


def _voice_off() -> list[tuple[int, int, int]]:
    return [(voice.chip, R_VOLUME[voice.channel], 0) for voice in VOICES]


def move_bass_to_ssg(data: bytes, bass: tuple[int, int] | None = None) -> bytes:
    """Поток TSFM → тот же поток, где басовый FM-канал заменён SSG-голосами рецепта.

    bass — (чип, канал) баса вместо выбора по медиане нот (проверка петли в rtype_music.py сравнивает поток с
    петлёй и развёрнутый линейный с одним и тем же басовым каналом). При BASS_TO_SSG = False поток не меняется."""
    if not BASS_TO_SSG:
        return data
    blocks = _parse(data)
    if bass is None:
        bass = _bass_channel(blocks)
    if bass is None:
        return data
    high, low = {}, {}
    last: dict[tuple[int, int], int] = {}
    result = []
    for pause, events in blocks:
        if pause is None:
            result.append((None, []))                     # точка петли остаётся на месте
            continue
        new_events = []

        def put(event):
            chip, register, value = event
            if register < 0x10 and register != R_ENV_SHAPE and last.get((chip, register)) == value:
                return                                    # регистр SSG уже такой
            last[(chip, register)] = value
            new_events.append(event)

        for chip, register, value in events:
            if 0xA4 <= register <= 0xA6:
                high[(chip, register - 0xA4)] = value
                if (chip, register - 0xA4) == bass:
                    continue                              # нота баса уходит в SSG
            elif 0xA0 <= register <= 0xA2:
                low[(chip, register - 0xA0)] = value
                if (chip, register - 0xA0) == bass:
                    continue
            elif register == 0x28 and chip == bass[0] and value & 3 == bass[1]:
                if value & 0xF0:
                    if bass in high and bass in low:
                        frequency = _frequency((high[bass] >> 3) & 7, ((high[bass] & 7) << 8) | low[bass])
                        if frequency > 0:
                            for event in _voice_on(frequency):
                                put(event)
                else:
                    for event in _voice_off():
                        put(event)
                continue                                  # FM-нажатие баса убираем
            new_events.append((chip, register, value))
        result.append((pause, new_events))
    return _emit(result)


# --- затухание SSG -----------------------------------------------------------------------------------
# Ступени ЦАП SSG и тракт платы — те же, что в модели Unreal_tsfm (tsfm_core.cpp): сопротивления 32 ступеней
# YM2149 (MAME ay8910.cpp, ym2149_param_env), выходной каскад 630/801 Ом, нагрузка 3.3 кОм, вход сумматора
# 47 кОм ‖ 47 кОм (канал B) с обратной связью 10 кОм. Для A/C (24 кОм) относительные уровни те же (±0.1 дБ,
# проверено рендером модели платы).
SSG_RES = (103350, 73770, 52657, 37586, 32125, 27458, 24269, 21451,
           18447, 15864, 14009, 12371, 10506, 8922, 7787, 6796,
           5689, 4763, 4095, 3521, 2909, 2403, 2043, 1737,
           1397, 1123, 925, 762, 578, 438, 332, 251)
TL_STEP_DB = 0.75                # шаг ослабления адаптера — шаг TL YM2203
FADE_SILENCE_DB = 6.0            # запас ниже громкости 1, после которого голос замолкает


def _board_levels() -> np.ndarray:
    g_down = 1 / 801.0 + 1 / 3300.0
    levels = []
    for resistance in SSG_RES:
        g_up = 1 / resistance + 1 / 630.0
        levels.append(5.0 * g_up / (g_up + g_down + 2 / 47000.0) * 10000.0 / 47000.0)
    levels = np.array(levels)
    return levels - levels[0]                   # по переменному току важна разность со ступенью 0


def ssg_fade_tables() -> dict[str, list[int] | int]:
    """Таблицы для SsgFade (v30z80_sound.asm), в шагах TL (0.75 дБ):
      vol_att[v] — ослабление громкости v относительно 15 (v = 0 не используется);
      vol_mid[v] — порог спуска с v на v − 1: середина ослаблений (у v = 1 — ослабление 1 + 6 дБ);
      env_keep   — до какого ослабления голос с огибающей звучит как есть; дальше он молчит.

    Голосу с огибающей громкость не задать, а заменять огибающую постоянной громкостью нельзя: в рецепте
    VOICES огибающая даёт основную частоту, тон её только модулирует (без огибающей остался бы меандр 6f).
    Выбор из двух амплитуд — полной и нуля — ближе к нужной: полная, пока нужная не меньше половины, то есть
    до ослабления 6 дБ."""
    levels = _board_levels()
    vol_db = [0.0] + [20 * math.log10(levels[31] / levels[2 * v + 1]) for v in range(1, 16)]
    vol_att = [255] + [round(vol_db[v] / TL_STEP_DB) for v in range(1, 16)]
    vol_mid = [0, round((vol_db[1] + FADE_SILENCE_DB) / TL_STEP_DB)] +               [round((vol_db[v] + vol_db[v - 1]) / 2 / TL_STEP_DB) for v in range(2, 16)]
    env_keep = round(20 * math.log10(2) / TL_STEP_DB)
    return {'vol_att': vol_att, 'vol_mid': vol_mid, 'env_keep': env_keep}
