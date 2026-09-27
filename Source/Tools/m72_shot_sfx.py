"""Сборка звука обычного выстрела (команда $30) для General Sound.

Почему отдельный скрипт, а не общий конвейер эффектов: у выстрела спектр
принципиально иной, чем у Wave Cannon. Wave — низкий гул, ему хватает 11025 Гц.
Выстрел резкий, и **42.6 % его энергии лежит выше 5512 Гц** — предела Найквиста
для 11025 Гц. На той частоте он терял характер, тогда как Wave звучал верно.

Поэтому выстрел собирается на 22050 Гц: полоса вдвое шире, за потолок уходит
лишь малая часть спектра. General Sound задаёт скорость воспроизведения нотой,
и вдвое большая частота — это ровно +12 полутонов (см. GS_SHOT_NOTE в
general_sound.asm); остальные эффекты продолжают играть на своей ноте.

Источник — эталон из MAME `Build/Arcade/Audio/scan/cmd_30.wav`, снятый подачей
одной команды в тишине. Ресемплинг с антиалиасным фильтром: без него всё, что
выше нового Найквиста, сложилось бы в грязь вместо того, чтобы быть отброшенным.
"""

from __future__ import annotations

import argparse
import hashlib
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = ROOT / "Build" / "Arcade" / "Audio" / "scan" / "cmd_30.wav"
DEFAULT_RAW = ROOT / "Audio" / "Converted" / "RTYPE_SFX_SHOT_U8_22050.raw"
DEFAULT_WAV = DEFAULT_RAW.with_suffix(".wav")
TARGET_RATE = 22050
SILENCE_THRESHOLD = 200      # уровень, ниже которого считаем тишиной (из int16)
LEAD_IN = 0.004              # запас перед атакой, с
TAIL = 0.010                 # запас после затухания, с


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as handle:
        rate = handle.getframerate()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        if handle.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data.astype(np.float64), rate


def trim(data: np.ndarray, rate: int) -> np.ndarray:
    """Вырезать сам эффект: в эталоне он начинается через несколько секунд."""
    loud = np.nonzero(np.abs(data) > SILENCE_THRESHOLD)[0]
    if not len(loud):
        raise SystemExit("в эталоне нет звука — не та команда?")
    start = max(0, loud[0] - int(LEAD_IN * rate))
    stop = min(len(data), loud[-1] + int(TAIL * rate))
    return data[start:stop]


def lowpass(data: np.ndarray, rate: int, cutoff: float) -> np.ndarray:
    """Окно-синк фильтр: всё выше cutoff должно быть отброшено ДО прореживания.

    Без него частоты выше нового Найквиста не исчезают, а зеркалятся вниз и
    ложатся поверх полезного сигнала — именно так резкий звук превращается в
    грязь.
    """
    taps = 129
    n = np.arange(taps) - (taps - 1) / 2
    fc = cutoff / rate
    kernel = np.sinc(2 * fc * n) * np.blackman(taps)
    kernel /= kernel.sum()
    return np.convolve(data, kernel, mode="same")


def resample(data: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Дробная передискретизация с линейной интерполяцией после фильтра."""
    data = lowpass(data, rate, cutoff=target * 0.45)
    length = int(round(len(data) * target / rate))
    source = np.arange(len(data))
    wanted = np.arange(length) * (rate / target)
    return np.interp(wanted, source, data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--rate", type=int, default=TARGET_RATE)
    args = parser.parse_args()

    if not args.src.exists():
        raise SystemExit(f"нет эталона {args.src} — сначала m72_sfx_scan.py")

    data, rate = load_mono(args.src)
    data = trim(data, rate)
    original_top = float(np.abs(data).max())
    data = resample(data, rate, args.rate)

    # Нормировка по пику: у оригинала он всего 7 % шкалы, а 8-битный тракт GS
    # такой запас просто выбросил бы в шум квантования. Потолок 126, чтобы
    # интерполяция не упёрлась в край.
    peak = float(np.abs(data).max())
    if peak > 0:
        data = data * (126.0 / peak)
    pcm = np.clip(np.round(data) + 128, 0, 255).astype(np.uint8)

    args.raw.parent.mkdir(parents=True, exist_ok=True)
    args.raw.write_bytes(pcm.tobytes())
    with wave.open(str(args.raw.with_suffix(".wav")), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(args.rate)
        handle.writeframes(pcm.tobytes())

    digest = hashlib.sha256(pcm.tobytes()).hexdigest()
    print(f"эталон: {args.src.name}, {rate} Гц, пик {original_top:.0f}")
    print(f"выстрел: {len(pcm)} Б = {len(pcm)/args.rate:.3f} с при {args.rate} Гц")
    print(f"sha256:  {digest}")
    print(f"raw:     {args.raw}")


if __name__ == "__main__":
    main()
