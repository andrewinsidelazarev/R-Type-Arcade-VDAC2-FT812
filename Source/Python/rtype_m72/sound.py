"""Original R-Type sound CPU and YM2151, executed inside the Python runtime.

The main V30 uploads this 32 KiB program to the M72 sound RAM.  Running that
program is important: sound-latch bytes are not independent samples.  They
start, replace, fade and stop voices owned by the same eight-channel YM2151.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEPS_DIR = ROOT / "Build" / "PythonDeps"
for search_dir in (str(DEPS_DIR),):
    if search_dir not in sys.path:
        sys.path.insert(0, search_dir)

import ymfm
import z80


SOUND_IMAGE = ROOT / "Build" / "Analysis" / "rtype_sound_upload.bin"
BASS_DLL = Path(r"E:\zx\unreal_x64\bass.dll")
SOUND_CLOCK = 3_579_545
VIDEO_PIXEL_CLOCK = 8_000_000
VIDEO_HTOTAL = 512
VIDEO_VTOTAL = 284
BASS_ATTRIB_VOL = 2
BASS_STREAMPROC_PUSH = ctypes.c_void_p(-1)


class BassPcmStream:
    """One persistent BASS push stream for signed 16-bit mono PCM."""

    def __init__(self, sample_rate: int, volume: float = 0.8,
                 dll_path: Path = BASS_DLL) -> None:
        if not dll_path.is_file():
            raise FileNotFoundError(f"BASS DLL not found: {dll_path}")
        self._bass = ctypes.WinDLL(str(dll_path))
        bass = self._bass
        bass.BASS_Init.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                   ctypes.c_void_p, ctypes.c_void_p]
        bass.BASS_Init.restype = ctypes.c_int
        bass.BASS_Free.restype = ctypes.c_int
        bass.BASS_ErrorGetCode.restype = ctypes.c_int
        bass.BASS_StreamCreate.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                           ctypes.c_uint, ctypes.c_void_p,
                                           ctypes.c_void_p]
        bass.BASS_StreamCreate.restype = ctypes.c_uint
        bass.BASS_StreamPutData.argtypes = [ctypes.c_uint, ctypes.c_void_p,
                                            ctypes.c_uint]
        bass.BASS_StreamPutData.restype = ctypes.c_uint
        bass.BASS_ChannelSetAttribute.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                                  ctypes.c_float]
        bass.BASS_ChannelPlay.argtypes = [ctypes.c_uint, ctypes.c_int]
        bass.BASS_StreamFree.argtypes = [ctypes.c_uint]
        if not bass.BASS_Init(-1, sample_rate, 0, None, None):
            raise RuntimeError(f"BASS_Init failed: {bass.BASS_ErrorGetCode()}")
        self._stream = bass.BASS_StreamCreate(
            sample_rate, 1, 0, BASS_STREAMPROC_PUSH, None)
        if not self._stream:
            error = bass.BASS_ErrorGetCode()
            bass.BASS_Free()
            raise RuntimeError(f"BASS_StreamCreate failed: {error}")
        bass.BASS_ChannelSetAttribute(
            self._stream, BASS_ATTRIB_VOL,
            ctypes.c_float(max(0.0, min(1.0, volume))))
        self._started = False

    def write(self, pcm: np.ndarray) -> None:
        if not len(pcm):
            return
        data = np.ascontiguousarray(pcm, dtype="<i2").tobytes()
        buffer = ctypes.create_string_buffer(data)
        queued = self._bass.BASS_StreamPutData(
            self._stream, buffer, len(data))
        # BASS returns the resulting queue level (this build reports zero
        # while accepting the block), not the number of bytes written.  Only
        # DWORD(-1) is failure.
        if queued == 0xFFFFFFFF:
            raise RuntimeError(
                f"BASS_StreamPutData failed: "
                f"{self._bass.BASS_ErrorGetCode()}")
        if not self._started:
            if not self._bass.BASS_ChannelPlay(self._stream, 0):
                raise RuntimeError(
                    f"BASS_ChannelPlay failed: "
                    f"{self._bass.BASS_ErrorGetCode()}")
            self._started = True

    def close(self) -> None:
        if not self._stream:
            return
        self._bass.BASS_StreamFree(self._stream)
        self._stream = 0
        self._bass.BASS_Free()


class M72SoundSystem:
    """Cycle-scheduled sound Z80 plus the board's original YM2151.

    RST $18 is the sound-latch line and RST $28 is the YM2151 timer line.
    In Z80 interrupt mode 0 the acknowledge bus carries the RST *opcode*
    ($DF/$EF), not its destination address.  Their active-low wired buffer
    produces opcode $CF (RST $08) when both are pending.
    """

    def __init__(self, *, output: bool = True,
                 sound_image: Path = SOUND_IMAGE) -> None:
        image = sound_image.read_bytes()
        if len(image) != 0x8000:
            raise ValueError(
                f"sound upload must be 32768 bytes, got {len(image)}")
        self.cpu = z80.Z80Machine()
        self.cpu.memory[:] = bytes(0x10000)
        self.cpu.set_memory_block(0, image)
        self.cpu.pc = 0
        self.cpu.sp = 0
        self.cpu.set_input_callback(self._input)
        self.cpu.set_output_callback(self._output)
        self._cpu_state = self.cpu.get_state_view()

        self.ym = ymfm.YM2151(clock=SOUND_CLOCK)
        self.sample_rate = int(self.ym.sample_rate)
        self._ym_register = 0
        self._ym_registers = bytearray(256)
        self._sound_latch = 0
        self._latch_irq = False
        self._timer_a_irq = False
        self._timer_a_running = False
        self._timer_a_enabled = False
        self._timer_a_remaining = 0
        # Счёт переполнений таймера A — тактов драйвера (224 сэмпла YM2151).
        self.timer_a_overflows = 0
        # Принятые прерывания при активной линии таймера A (RST $28 или общий RST $08).
        self.timer_a_irqs = 0
        # Журнал записей YM2151 для генератора потоков TSFM (rtype_music.py):
        # список — (такт, регистр, значение); None — журнал не ведётся.
        self.write_log: list[tuple[int, int, int]] | None = None
        # Такт записи в журнале: функция без аргументов; None — число переполнений таймера A.
        self.write_tick = None
        self._cpu_tick_phase = 0
        self._frame_sample_phase = 0
        self._sample_in_block = 0
        self._ym_write_events: list[tuple[int, int, int]] = []
        self._closed = False
        self._sink = BassPcmStream(self.sample_rate) if output else None

        # Execute reset and driver initialization before the V30 releases its
        # first command.  The discarded samples are board power-on silence.
        self._render_samples(2048)

    @property
    def ym_registers(self) -> bytes:
        """Последние записанные значения регистров YM2151 (256 байт)."""
        return bytes(self._ym_registers)

    def command(self, value: int) -> None:
        """Write one literal V30 sound-latch byte and assert RST $18."""
        if self._closed:
            return
        self._sound_latch = value & 0xFF
        self._latch_irq = True

    def step_frame(self) -> np.ndarray:
        """Advance sound by one M72 video frame and queue its PCM."""
        self._frame_sample_phase += (
            self.sample_rate * VIDEO_HTOTAL * VIDEO_VTOTAL)
        sample_count, self._frame_sample_phase = divmod(
            self._frame_sample_phase, VIDEO_PIXEL_CLOCK)
        pcm = self._render_samples(sample_count)
        if self._sink is not None:
            self._sink.write(pcm)
        return pcm

    def render_seconds(self, seconds: float) -> np.ndarray:
        """Deterministic offline helper used by the MAME waveform tests."""
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        return self._render_samples(round(seconds * self.sample_rate))

    def _render_samples(self, count: int) -> np.ndarray:
        self._ym_write_events.clear()
        for index in range(count):
            self._sample_in_block = index
            self._cpu_tick_phase += SOUND_CLOCK
            ticks, self._cpu_tick_phase = divmod(
                self._cpu_tick_phase, self.sample_rate)
            self._advance_cpu(ticks)
        return self._render_ym_block(count)

    def _render_ym_block(self, count: int) -> np.ndarray:
        """Replay timestamped register writes around batched YM generation."""
        output = np.empty(count, dtype=np.int16)
        cursor = 0

        def generate(end: int) -> None:
            nonlocal cursor
            length = end - cursor
            if length <= 0:
                return
            stereo = np.frombuffer(
                self.ym.generate(length), dtype=np.int32,
                count=length * 2).reshape(length, 2)
            mixed = ((stereo[:, 0].astype(np.int64) +
                      stereo[:, 1].astype(np.int64)) // 2)
            output[cursor:end] = np.clip(
                mixed, -32768, 32767).astype(np.int16)
            cursor = end

        for sample_index, register, value in self._ym_write_events:
            sample_index = min(count, max(cursor, sample_index))
            generate(sample_index)
            self.ym.write_address(register)
            self.ym.write_data(value)
        generate(count)
        return output

    def _advance_cpu(self, ticks: int) -> None:
        if self._timer_a_running:
            self._timer_a_remaining -= ticks
            if self._timer_a_remaining <= 0:
                period = self._timer_a_period()
                while self._timer_a_remaining <= 0:
                    self._timer_a_remaining += period
                    self.timer_a_overflows += 1
                if self._timer_a_enabled:
                    self._timer_a_irq = True
        if self._latch_irq or self._timer_a_irq:
            if self._accept_interrupt():
                # A Z80 mode-0 interrupt acknowledge followed by RST takes
                # thirteen T-states.  Account for them outside the CPU core.
                ticks -= 13
        self.cpu.ticks_to_stop = max(1, ticks)
        self.cpu.run()

    def _accept_interrupt(self) -> bool:
        """Inject one exact IM0 RST without the package's fixed RST-$38 API.

        ``z80.Z80Machine.on_handle_active_int`` currently uses its default
        $FF acknowledge byte even when a Python vector callback is installed.
        The state image is public API, so the short IM0 acknowledge sequence
        is performed explicitly here and remains covered by waveform tests.
        """
        iff1 = 34
        int_disabled = 36
        if not self._cpu_state[iff1] or self._cpu_state[int_disabled]:
            return False
        opcode = self._interrupt_vector()
        if opcode & 0xC7 != 0xC7:
            raise RuntimeError(f"invalid IM0 acknowledge opcode ${opcode:02X}")
        if self._timer_a_irq:
            self.timer_a_irqs += 1
        pc = self.cpu.pc
        sp = (self.cpu.sp - 2) & 0xFFFF
        self.cpu.memory[sp] = pc & 0xFF
        self.cpu.memory[(sp + 1) & 0xFFFF] = pc >> 8
        self.cpu.sp = sp
        self.cpu.pc = opcode & 0x38
        self._cpu_state[34] = 0  # IFF1
        self._cpu_state[35] = 0  # IFF2
        return True

    def _interrupt_vector(self) -> int:
        vector = 0xFF
        if self._latch_irq:
            vector &= 0xDF  # opcode RST $18
        if self._timer_a_irq:
            vector &= 0xEF  # opcode RST $28
        return vector

    def _input(self, port: int) -> int:
        port &= 0xFF
        if port in (0x00, 0x01):
            return int(self.ym.read(port & 1))
        if port == 0x02:
            return self._sound_latch
        return 0xFF

    def _output(self, port: int, value: int) -> None:
        port &= 0xFF
        value &= 0xFF
        if port == 0x00:
            self._ym_register = value
        elif port == 0x01:
            self._ym_registers[self._ym_register] = value
            self._ym_write_events.append(
                (self._sample_in_block, self._ym_register, value))
            if self.write_log is not None:
                tick = (self.write_tick() if self.write_tick is not None
                        else self.timer_a_overflows)
                self.write_log.append((tick, self._ym_register, value))
            if self._ym_register == 0x14:
                self._timer_control(value)
        elif port == 0x06:
            self._latch_irq = False

    def _timer_control(self, value: int) -> None:
        # YM2151 CT/timer control: bits 0/1 load, 2/3 IRQ enable and
        # bits 4/5 clear the corresponding overflow flags.
        if value & 0x10:
            self._timer_a_irq = False
        self._timer_a_enabled = bool(value & 0x04)
        # Бит загрузки перезапускает таймер только при переходе 0 → 1, как у
        # YM2151 (MAME ym2151.cpp: «start timer _only_ if it wasn't already
        # started», ymfm update_timer). Обработчик прерывания драйвера ($0076)
        # пишет $35 в каждом такте, и прежняя перезагрузка на каждой записи
        # удлиняла период на задержку обработчика: музыка шла на 0.9 % медленнее
        # аркады. Переполнение само добавляет период (_advance_cpu).
        running = bool(value & 0x01)
        if running and not self._timer_a_running:
            self._timer_a_remaining = self._timer_a_period()
        self._timer_a_running = running

    def _timer_a_period(self) -> int:
        timer_value = ((self._ym_registers[0x10] << 2) |
                       (self._ym_registers[0x11] & 3))
        return max(64, 64 * (1024 - timer_value))

    def close(self) -> None:
        if self._closed:
            return
        if self._sink is not None:
            self._sink.close()
        self._closed = True

    def __enter__(self) -> "M72SoundSystem":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
