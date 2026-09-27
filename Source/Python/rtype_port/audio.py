"""Целевой звук R-Type: музыка TSFM, эффекты General Sound."""
from __future__ import annotations

import ctypes
import json
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .tsfm import TsfmEmulator


ROOT = Path(__file__).resolve().parents[3]
BASS_DLL = Path(r"E:\zx\unreal_x64\bass.dll")
# Оригиналы эффектов (звучащие части записей MAME по одной команде): Audio/Original, каталог rtype_sfx.json.
GS_CAPTURE_DIR = ROOT / "Audio" / "Original"
MUSIC_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "Music"

BASS_SAMPLE_LOOP = 4
BASS_ATTRIB_VOL = 2
BASS_STREAMPROC_PUSH = ctypes.c_void_p(-1)
BASS_CONFIG_UPDATEPERIOD = 1
MUSIC_PREFILL_FRAMES = 8

# Потоки мелодий строит Source/Tools/rtype_music.py из оракула (программа звукового Z80 и ymfm YM2151) с
# точной петлёй и вибрато; $1F — отдельный файл: STAGE1_TSFM.bin остаётся прежнему плееру tsfm_music.asm
# (build.cmd), который маркера петли $FD не знает.
MUSIC_STREAMS = {
    0x1F: MUSIC_DIR / "COMMAND_1F_TSFM.bin",
    0x01: MUSIC_DIR / "STAGE_COMMAND_01_TSFM.bin",
    0x04: MUSIC_DIR / "STAGE_COMMAND_04_TSFM.bin",
    0x07: MUSIC_DIR / "STAGE_COMMAND_07_TSFM.bin",
    0x0A: MUSIC_DIR / "STAGE_COMMAND_0A_TSFM.bin",
    0x0D: MUSIC_DIR / "STAGE_COMMAND_0D_TSFM.bin",
    0x10: MUSIC_DIR / "STAGE_COMMAND_10_TSFM.bin",
    0x13: MUSIC_DIR / "STAGE_COMMAND_13_TSFM.bin",
    0x16: MUSIC_DIR / "STAGE_COMMAND_16_TSFM.bin",
    0x19: MUSIC_DIR / "START_COMMAND_19_TSFM.bin",
    0x1C: MUSIC_DIR / "START_COMMAND_1C_TSFM.bin",
    0x22: MUSIC_DIR / "COMMAND_22_TSFM.bin",
    0x25: MUSIC_DIR / "COMMAND_25_TSFM.bin",
    0x28: MUSIC_DIR / "COMMAND_28_TSFM.bin",
    0x2B: MUSIC_DIR / "COMMAND_2B_TSFM.bin",
}

REPLACE_STREAM = MUSIC_DIR / "CONTROL_COMMAND_02_TSFM.bin"
REPLACE_COMMANDS = frozenset(range(0x02, 0x2D, 3))
FADE_COMMANDS = frozenset(set(range(0x03, 0x2E, 3)) - {0x24})
NOOP_COMMANDS = frozenset((0x00, 0x24, 0x2E, 0x2F))
ONE_SHOT_COMMANDS = frozenset((0x1C, 0x22, 0x2B))
FADE_FRAMES = 0x70

STAGE_MUSIC_COMMANDS = {
    1: 0x01,
    2: 0x04,
    3: 0x07,
    4: 0x0A,
    5: 0x10,
    6: 0x0D,
    7: 0x13,
    8: 0x16,
}

LEGACY_COMMANDS = {
    "shot": 0x30,
    "wave": 0x31,
    "charge": 0x32,
    "charge_stop": 0x33,
    "force_detach": 0x36,
    "force_attach": 0x37,
}


class _BassMixer:
    """Один BASS-сеанс для нативного TSFM-потока и GS-семплов."""

    def __init__(self, music_rate: int) -> None:
        if not BASS_DLL.is_file():
            raise FileNotFoundError(f"BASS DLL не найден: {BASS_DLL}")
        self._bass = ctypes.WinDLL(str(BASS_DLL))
        self._configure()
        if not self._bass.BASS_Init(-1, 44_100, 0, None, None):
            raise RuntimeError(
                f"BASS_Init: ошибка {self._bass.BASS_ErrorGetCode()}")
        # Стандартные 100 мс между обновлениями слишком велики для игрового
        # push-потока. BASS обновляет свой playback buffer отдельным потоком.
        if not self._bass.BASS_SetConfig(BASS_CONFIG_UPDATEPERIOD, 10):
            error = self._bass.BASS_ErrorGetCode()
            self._bass.BASS_Free()
            raise RuntimeError(f"BASS_SetConfig update: ошибка {error}")
        self.music_stream = self._bass.BASS_StreamCreate(
            music_rate, 1, 0, BASS_STREAMPROC_PUSH, None)
        if not self.music_stream:
            error = self._bass.BASS_ErrorGetCode()
            self._bass.BASS_Free()
            raise RuntimeError(f"BASS_StreamCreate TSFM: ошибка {error}")
        self._bass.BASS_ChannelSetAttribute(
            self.music_stream, BASS_ATTRIB_VOL, ctypes.c_float(0.55))
        self._music_started = False
        self._music_prefill_frames = 0
        self._samples: dict[int, int] = {}
        self._charge_channel = 0

    def _configure(self) -> None:
        bass = self._bass
        bass.BASS_Init.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                   ctypes.c_void_p, ctypes.c_void_p]
        bass.BASS_Init.restype = ctypes.c_int
        bass.BASS_Free.argtypes = []
        bass.BASS_Free.restype = ctypes.c_int
        bass.BASS_SetConfig.argtypes = [ctypes.c_uint, ctypes.c_uint]
        bass.BASS_SetConfig.restype = ctypes.c_int
        bass.BASS_ErrorGetCode.argtypes = []
        bass.BASS_ErrorGetCode.restype = ctypes.c_int
        bass.BASS_StreamCreate.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p]
        bass.BASS_StreamCreate.restype = ctypes.c_uint
        bass.BASS_StreamPutData.argtypes = [
            ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        bass.BASS_StreamPutData.restype = ctypes.c_uint
        bass.BASS_StreamFree.argtypes = [ctypes.c_uint]
        bass.BASS_StreamFree.restype = ctypes.c_int
        bass.BASS_SampleCreate.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_uint]
        bass.BASS_SampleCreate.restype = ctypes.c_uint
        bass.BASS_SampleSetData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        bass.BASS_SampleSetData.restype = ctypes.c_int
        bass.BASS_SampleGetChannel.argtypes = [ctypes.c_uint, ctypes.c_int]
        bass.BASS_SampleGetChannel.restype = ctypes.c_uint
        bass.BASS_SampleFree.argtypes = [ctypes.c_uint]
        bass.BASS_SampleFree.restype = ctypes.c_int
        bass.BASS_SampleStop.argtypes = [ctypes.c_uint]
        bass.BASS_SampleStop.restype = ctypes.c_int
        bass.BASS_ChannelSetAttribute.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_float]
        bass.BASS_ChannelSetAttribute.restype = ctypes.c_int
        bass.BASS_ChannelPlay.argtypes = [ctypes.c_uint, ctypes.c_int]
        bass.BASS_ChannelPlay.restype = ctypes.c_int
        bass.BASS_ChannelStop.argtypes = [ctypes.c_uint]
        bass.BASS_ChannelStop.restype = ctypes.c_int
        bass.BASS_ChannelIsActive.argtypes = [ctypes.c_uint]
        bass.BASS_ChannelIsActive.restype = ctypes.c_uint

    def reset_music(self) -> None:
        self._bass.BASS_ChannelStop(self.music_stream)
        self._music_started = False
        self._music_prefill_frames = 0

    def push_music(self, samples: np.ndarray, gain: float = 1.0) -> None:
        if not len(samples):
            return
        scaled = np.rint(
            np.asarray(samples, dtype=np.float64) * 2.5 * gain)
        pcm = np.ascontiguousarray(
            np.clip(scaled, -32768, 32767), dtype="<i2").tobytes()
        buffer = ctypes.create_string_buffer(pcm)
        queued = self._bass.BASS_StreamPutData(
            self.music_stream, buffer, len(pcm))
        if queued == 0xFFFFFFFF:
            raise RuntimeError(
                f"BASS_StreamPutData TSFM: ошибка "
                f"{self._bass.BASS_ErrorGetCode()}")
        if not self._music_started:
            self._music_prefill_frames += 1
        if (not self._music_started and
                self._music_prefill_frames >= MUSIC_PREFILL_FRAMES):
            if not self._bass.BASS_ChannelPlay(self.music_stream, 0):
                raise RuntimeError(
                    f"BASS_ChannelPlay TSFM: ошибка "
                    f"{self._bass.BASS_ErrorGetCode()}")
            self._music_started = True

    def play_gs(self, command: int, pcm: bytes, rate: int,
                channels: int, *, loop: bool = False) -> None:
        sample = self._samples.get(command)
        if sample is None:
            flags = BASS_SAMPLE_LOOP if loop else 0
            sample = self._bass.BASS_SampleCreate(
                len(pcm), rate, channels, 8, flags)
            if not sample:
                raise RuntimeError(
                    f"BASS_SampleCreate GS ${command:02X}: ошибка "
                    f"{self._bass.BASS_ErrorGetCode()}")
            buffer = ctypes.create_string_buffer(pcm)
            if not self._bass.BASS_SampleSetData(sample, buffer):
                self._bass.BASS_SampleFree(sample)
                raise RuntimeError(
                    f"BASS_SampleSetData GS ${command:02X}: ошибка "
                    f"{self._bass.BASS_ErrorGetCode()}")
            self._samples[command] = sample
        if command == 0x32 and self._charge_channel:
            if self._bass.BASS_ChannelIsActive(self._charge_channel):
                return
        channel = self._bass.BASS_SampleGetChannel(sample, 0)
        if not channel:
            return
        self._bass.BASS_ChannelSetAttribute(
            channel, BASS_ATTRIB_VOL, ctypes.c_float(0.8))
        if self._bass.BASS_ChannelPlay(channel, 1) and command == 0x32:
            self._charge_channel = channel

    def stop_charge(self) -> None:
        if self._charge_channel:
            self._bass.BASS_ChannelStop(self._charge_channel)
            self._charge_channel = 0

    def stop_gs(self) -> None:
        """Остановить все голоса GS при возврате к стартовому экрану."""
        for sample in self._samples.values():
            self._bass.BASS_SampleStop(sample)
        self._charge_channel = 0

    def close(self) -> None:
        self.stop_charge()
        if self.music_stream:
            self._bass.BASS_StreamFree(self.music_stream)
            self.music_stream = 0
        for sample in self._samples.values():
            self._bass.BASS_SampleFree(sample)
        self._samples.clear()
        self._bass.BASS_Free()


class GeneralSound:
    """Командная модель GS с ленивой загрузкой изолированных MAME PCM."""

    def __init__(self, mixer: _BassMixer | None) -> None:
        self.mixer = mixer
        self.command_log: list[int] = []
        catalog_path = GS_CAPTURE_DIR / "rtype_sfx.json"
        catalog = (json.loads(catalog_path.read_text(encoding="utf-8"))
                   if catalog_path.is_file() else {"sounding": {}})
        self.catalog: dict[str, dict[str, float]] = catalog["sounding"]
        self._pcm: dict[int, tuple[bytes, int, int]] = {}

    def _load(self, command: int) -> tuple[bytes, int, int] | None:
        cached = self._pcm.get(command)
        if cached is not None:
            return cached
        metadata = self.catalog.get(f"0x{command:02X}")
        path = GS_CAPTURE_DIR / metadata["file"] if metadata else None
        if metadata is None or not path.is_file():
            return None
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
                raise ValueError(f"GS ${command:02X}: нужен PCM S16 WAV")
            rate = wav.getframerate()
            channels = wav.getnchannels()
            start = max(0, round(metadata["start_seconds"] * rate))
            count = max(1, round(metadata["duration_seconds"] * rate))
            wav.setpos(min(start, wav.getnframes()))
            pcm = wav.readframes(min(count, wav.getnframes() - wav.tell()))
        result = pcm, rate, channels
        self._pcm[command] = result
        return result

    def command(self, command: int) -> None:
        command &= 0xFF
        if command < 0x30:
            raise ValueError(
                f"музыкальная команда ${command:02X} не должна идти в GS")
        self.command_log.append(command)
        if command == 0x33:
            if self.mixer is not None:
                self.mixer.stop_charge()
            return
        # Смерть `$35` обрывает непрерывный charge voice внутри GS. В ROM
        # перед ней нет придуманной команды `$33`: latch получает только
        # документированную пару `0,$35`.
        if command == 0x35 and self.mixer is not None:
            self.mixer.stop_charge()
        effect = self._load(command)
        if effect is not None and self.mixer is not None:
            self.mixer.play_gs(command, *effect, loop=(command == 0x32))


class TurboSoundFm:
    """Два эмулируемых YM2203 с переключением потоков по sound-latch."""

    def __init__(self, mixer: _BassMixer | None, *, enabled: bool,
                 port_writer: Callable[[int, int], None] | None = None) -> None:
        self.mixer = mixer
        self.enabled = enabled
        self.port_writer = port_writer
        self.command_log: list[int] = []
        self.current_command: int | None = None
        self.owner_command: int | None = None
        self.emulator: TsfmEmulator | None = None
        self.fade_remaining = 0
        self.port_frame = 0
        self._port_finished = False
        self._prefill_pending = False

    def command(self, command: int) -> None:
        command &= 0xFF
        if command >= 0x30:
            raise ValueError(f"SFX-команда ${command:02X} не должна идти в TSFM")
        self.command_log.append(command)
        if command in NOOP_COMMANDS:
            return
        if command in FADE_COMMANDS:
            if self.owner_command == command - 2:
                self.fade_remaining = FADE_FRAMES
            return
        if command in REPLACE_COMMANDS:
            if self.owner_command != command - 1:
                return
            self.current_command = command
            self.owner_command = None
            self.fade_remaining = 0
            if self.enabled:
                self.emulator = TsfmEmulator(REPLACE_STREAM, loop=False)
                self.port_frame = 0
                self._port_finished = False
                self._prefill_pending = True
                if self.mixer is not None:
                    self.mixer.reset_music()
            return
        stream = MUSIC_STREAMS.get(command)
        if stream is None or not stream.is_file():
            return
        self.current_command = command
        self.owner_command = command
        self.fade_remaining = 0
        if self.enabled:
            self.emulator = TsfmEmulator(
                stream, loop=command not in ONE_SHOT_COMMANDS)
            self.port_frame = 0
            self._port_finished = False
            self._prefill_pending = True
            if self.mixer is not None:
                self.mixer.reset_music()

    def reset(self) -> None:
        """Сбросить владельца и PCM-поток между игровыми сессиями."""
        self.current_command = None
        self.owner_command = None
        self.emulator = None
        self.fade_remaining = 0
        self.port_frame = 0
        self._port_finished = False
        self._prefill_pending = False
        if self.mixer is not None:
            self.mixer.reset_music()

    def step_frame(self) -> None:
        if self.emulator is not None and self.mixer is not None:
            if self.port_writer is not None and not self._port_finished:
                for chip, register, value in self.emulator.events.get(
                        self.port_frame, ()):
                    self.port_writer(0xFFFD, 0xF8 | chip)
                    self.port_writer(0xFFFD, register)
                    self.port_writer(0xBFFD, value)
            if not self._port_finished:
                self.port_frame += 1
                if self.port_frame == self.emulator.frame_count:
                    if self.emulator.loop:
                        self.port_frame = self.emulator.loop_frame
                    else:
                        self._port_finished = True
            gain = (self.fade_remaining / FADE_FRAMES
                    if self.fade_remaining else 1.0)
            block_count = (MUSIC_PREFILL_FRAMES
                           if self._prefill_pending else 1)
            for _ in range(block_count):
                self.mixer.push_music(self.emulator.step(), gain)
            self._prefill_pending = False
            if self.fade_remaining:
                self.fade_remaining -= 1
                if self.fade_remaining == 0:
                    self.current_command = None
                    self.owner_command = None
                    self.emulator = None
            elif self.emulator.finished:
                self.owner_command = None


class TargetAudio:
    """Единственная точка маршрутизации: мелодии в TSFM, SFX в GS."""

    def __init__(self, *, enabled: bool = True,
                 port_writer: Callable[[int, int], None] | None = None) -> None:
        self.enabled = enabled
        self.port_writer = port_writer
        self.command_log: list[int] = []
        self._probe = TsfmEmulator() if enabled else None
        self._mixer = (_BassMixer(self._probe.sample_rate)
                       if self._probe is not None else None)
        self.tsfm = TurboSoundFm(
            self._mixer, enabled=enabled, port_writer=port_writer)
        self.gs = GeneralSound(self._mixer)

    def command(self, command: int | str) -> None:
        if isinstance(command, str):
            try:
                command = LEGACY_COMMANDS[command]
            except KeyError as error:
                raise ValueError(f"неизвестная звуковая команда {command!r}") from error
        command &= 0xFF
        self.command_log.append(command)
        if command < 0x30:
            self.tsfm.command(command)
        else:
            if self.port_writer is not None:
                self.port_writer(0x00BB, command)
            self.gs.command(command)

    def start_music(self) -> None:
        self.command(0x1F)

    def play(self, command: int | str) -> None:
        self.command(command)

    def step_frame(self) -> None:
        self.tsfm.step_frame()

    def reset_session(self) -> None:
        """Не переносить музыку и GS-голоса в новый стартовый экран."""
        self.tsfm.reset()
        if self._mixer is not None:
            self._mixer.stop_gs()

    def close(self) -> None:
        self.tsfm.emulator = None
        if self._mixer is not None:
            self._mixer.close()
            self._mixer = None


BassSfx = TargetAudio
