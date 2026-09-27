"""Полифоническое воспроизведение точных PCM-эффектов R-Type через BASS."""
from __future__ import annotations

import argparse
import ctypes
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASS = Path(r"E:\zx\unreal_x64\bass.dll")
SFX_DIR = ROOT / "Audio" / "Converted"

BASS_SAMPLE_8BITS = 0x00000001
BASS_STREAMPROC_END = 0x80000000
BASS_ACTIVE_STOPPED = 0
BASS_ATTRIB_VOL = 2


@dataclass(frozen=True)
class Effect:
    """Один неизменённый PCM-эффект, извлечённый из MAME."""

    path: Path
    frequency: int


EFFECTS: dict[str, Effect] = {
    "shot": Effect(SFX_DIR / "RTYPE_SFX_SHOT_U8_22050.raw", 22_050),
    "wave": Effect(SFX_DIR / "RTYPE_SFX_WAVE_U8_11025.raw", 11_025),
}


class BassSfx:
    """Неблокирующий BASS-микшер: каждый запуск получает отдельный канал."""

    def __init__(self, dll_path: Path = DEFAULT_BASS, volume: float = 0.8) -> None:
        if not dll_path.is_file():
            raise FileNotFoundError(f"BASS DLL не найден: {dll_path}")
        self._bass = ctypes.WinDLL(str(dll_path))
        self._configure_api()
        if not self._bass.BASS_Init(-1, 44_100, 0, None, None):
            raise RuntimeError(f"BASS_Init: ошибка {self._bass.BASS_ErrorGetCode()}")
        self.volume = max(0.0, min(1.0, float(volume)))
        self._channels: list[int] = []
        self._closed = False
        self._pcm = {name: effect.path.read_bytes() for name, effect in EFFECTS.items()}

    def _configure_api(self) -> None:
        bass = self._bass
        bass.BASS_Init.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                   ctypes.c_void_p, ctypes.c_void_p]
        bass.BASS_Init.restype = ctypes.c_int
        bass.BASS_Free.argtypes = []
        bass.BASS_Free.restype = ctypes.c_int
        bass.BASS_ErrorGetCode.argtypes = []
        bass.BASS_ErrorGetCode.restype = ctypes.c_int
        bass.BASS_StreamCreate.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                           ctypes.c_void_p, ctypes.c_void_p]
        bass.BASS_StreamCreate.restype = ctypes.c_uint
        bass.BASS_StreamPutData.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        bass.BASS_StreamPutData.restype = ctypes.c_uint
        bass.BASS_ChannelSetAttribute.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_float]
        bass.BASS_ChannelSetAttribute.restype = ctypes.c_int
        bass.BASS_ChannelPlay.argtypes = [ctypes.c_uint, ctypes.c_int]
        bass.BASS_ChannelPlay.restype = ctypes.c_int
        bass.BASS_ChannelIsActive.argtypes = [ctypes.c_uint]
        bass.BASS_ChannelIsActive.restype = ctypes.c_uint
        bass.BASS_StreamFree.argtypes = [ctypes.c_uint]
        bass.BASS_StreamFree.restype = ctypes.c_int

    def _reap(self) -> None:
        live: list[int] = []
        for channel in self._channels:
            if self._bass.BASS_ChannelIsActive(channel) == BASS_ACTIVE_STOPPED:
                self._bass.BASS_StreamFree(channel)
            else:
                live.append(channel)
        self._channels = live

    def play(self, name: str) -> None:
        """Запустить эффект с начала, не обрывая уже звучащие эффекты."""
        if self._closed:
            return
        try:
            effect = EFFECTS[name]
            pcm = self._pcm[name]
        except KeyError as error:
            raise KeyError(f"неизвестный эффект: {name}") from error
        self._reap()
        channel = self._bass.BASS_StreamCreate(
            effect.frequency, 1, BASS_SAMPLE_8BITS, ctypes.c_void_p(-1), None)
        if not channel:
            raise RuntimeError(f"BASS_StreamCreate: ошибка {self._bass.BASS_ErrorGetCode()}")
        buffer = ctypes.create_string_buffer(pcm)
        written = self._bass.BASS_StreamPutData(
            channel, buffer, len(pcm) | BASS_STREAMPROC_END)
        if written != len(pcm):
            self._bass.BASS_StreamFree(channel)
            raise RuntimeError(f"BASS_StreamPutData: записано {written} из {len(pcm)}")
        self._bass.BASS_ChannelSetAttribute(channel, BASS_ATTRIB_VOL, self.volume)
        if not self._bass.BASS_ChannelPlay(channel, 1):
            self._bass.BASS_StreamFree(channel)
            raise RuntimeError(f"BASS_ChannelPlay: ошибка {self._bass.BASS_ErrorGetCode()}")
        self._channels.append(channel)

    def play_shot(self) -> None:
        self.play("shot")

    def play_wave(self) -> None:
        self.play("wave")

    def close(self) -> None:
        if self._closed:
            return
        for channel in self._channels:
            self._bass.BASS_StreamFree(channel)
        self._channels.clear()
        self._bass.BASS_Free()
        self._closed = True

    def __enter__(self) -> "BassSfx":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", type=Path, default=DEFAULT_BASS)
    parser.add_argument("--volume", type=float, default=0.8)
    args = parser.parse_args()
    with BassSfx(args.dll, args.volume) as sfx:
        sfx.play_shot()
        time.sleep(0.18)
        sfx.play_shot()
        time.sleep(0.18)
        sfx.play_wave()
        time.sleep(0.8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
