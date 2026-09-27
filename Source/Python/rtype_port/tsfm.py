"""TurboSound FM stream player backed by two emulated YM2203 chips.

The binary stream consumed here is the same register stream as the Z80
``TsfmMusic_Update`` routine.  Rendering it offline keeps the slow laptop's
game loop free of 875 kHz worth of chip work while preserving the exact OPN
register writes used by the FT812/TS-Config build.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STREAM = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Music" /
    "STAGE1_TSFM.bin"
)
# Оба YM2203 платы ZX-MultiSound тактируются 3.5 МГц (ym_m = 32 МГц × 7/64,
# cpld/rtl/top.v). Плеер ставит прескалер 1/6 ($2D), поэтому частота синтеза
# FM — 48 611 Гц, как и было при прежней паре «1.75 МГц + 1/3»: звук эталона
# не меняется, а на плате ноты перестают уезжать на октаву вверх.
TSFM_CLOCK = 3_500_000
FRAME_RATE = 55
PAGE_SIZE = 0x4000
PAGE_MARKER = 0xFE
END_MARKER = 0xFF
# Точка петли ($FD $00, ym2151_to_tsfm.encode_stream): повторяемый поток после последнего кадра продолжается
# отсюда, с кадра маркера; без маркера — с начала.
LOOP_MARKER = 0xFD

RegisterWrite = tuple[int, int, int]


def decode_stream(data: bytes) -> tuple[dict[int, tuple[RegisterWrite, ...]], int]:
    """Decode the paged Z80 stream into exact frame-indexed writes."""
    position = 0
    frame = 0
    events: dict[int, list[RegisterWrite]] = defaultdict(list)
    while position + 2 <= len(data):
        wait = data[position]
        count = data[position + 1]
        if wait == END_MARKER:
            break
        if wait == PAGE_MARKER:
            position = ((position // PAGE_SIZE) + 1) * PAGE_SIZE
            continue
        if wait == LOOP_MARKER:
            position += 2
            continue
        position += 2
        end = position + count * 3
        if end > len(data):
            raise ValueError("TSFM stream ends inside a register block")
        frame += wait
        for offset in range(position, end, 3):
            chip, register, value = data[offset:offset + 3]
            if chip > 1:
                raise ValueError(f"invalid TSFM chip {chip} at ${offset:04X}")
            events[frame].append((chip, register, value))
        position = end
    else:
        raise ValueError("TSFM stream has no end marker")
    frozen = {key: tuple(value) for key, value in events.items()}
    return frozen, frame + 1


def stream_loop_frame(data: bytes) -> int:
    """Кадр точки петли потока (маркер LOOP_MARKER); 0 — маркера нет, повтор с начала."""
    position = 0
    frame = 0
    while position + 2 <= len(data):
        wait = data[position]
        if wait == END_MARKER:
            return 0
        if wait == PAGE_MARKER:
            position = ((position // PAGE_SIZE) + 1) * PAGE_SIZE
            continue
        if wait == LOOP_MARKER:
            return frame
        frame += wait
        position += 2 + data[position + 1] * 3
    return 0


class TsfmEmulator:
    """Frame-clocked emulation of the ZX MultiSound pair of YM2203 chips."""

    def __init__(self, stream_path: Path = DEFAULT_STREAM, *,
                 loop: bool = True) -> None:
        try:
            import ymfm
        except ImportError as error:  # pragma: no cover - installation failure
            raise RuntimeError(
                "ymfm-py is required to emulate the two TSFM YM2203 chips"
            ) from error
        # Перенос басовой партии в SSG-часть (tsfm_bass) — так же пакует потоки rtype_sound.py; с 2026-09-17 выключен
        # (tsfm_bass.BASS_TO_SSG): поток не меняется, бас на FM, как у аркады.
        from .tsfm_bass import move_bass_to_ssg
        data = move_bass_to_ssg(stream_path.read_bytes())
        self.events, self.frame_count = decode_stream(data)
        self.loop_frame = stream_loop_frame(data)
        self.chips = (ymfm.YM2203(clock=TSFM_CLOCK),
                      ymfm.YM2203(clock=TSFM_CLOCK))
        self.sample_rate = self.chips[0].sample_rate
        self.loop = loop
        self.finished = False
        self.frame = 0
        self._sample_numerator = 0
        self.reset()

    def reset(self) -> None:
        self.frame = 0
        self.finished = False
        self._sample_numerator = 0
        for chip in self.chips:
            chip.reset()
            # Literal TsfmMusic_Init register sequence from tsfm_music.asm.
            # $2D — прескалер 1/6 при 3.5 МГц платы (частота синтеза 48 611 Гц).
            for register, value in ((0x2D, 0x00), (0x27, 0x00),
                                    (0x28, 0x00), (0x28, 0x01),
                                    (0x28, 0x02)):
                chip.write_address(register)
                chip.write_data(value)

    @staticmethod
    def _write(chip: object, register: int, value: int) -> None:
        chip.write_address(register)
        chip.write_data(value)

    def step(self) -> np.ndarray:
        """Execute one 55 Hz stream tick and return native-rate mono int32."""
        for chip_index, register, value in self.events.get(self.frame, ()):
            self._write(self.chips[chip_index], register, value)
        self._sample_numerator += self.sample_rate
        sample_count, self._sample_numerator = divmod(
            self._sample_numerator, FRAME_RATE)
        mixed: np.ndarray | None = None
        for chip in self.chips:
            output = np.asarray(chip.generate(sample_count), dtype=np.int32)
            mono = output.astype(np.int64).sum(axis=1)
            mixed = mono if mixed is None else mixed + mono
        if not self.finished:
            self.frame += 1
            if self.frame == self.frame_count:
                if self.loop:
                    # ASM зацикливает указатель, не сбрасывая огибающие чипов: с точки петли потока.
                    self.frame = self.loop_frame
                else:
                    self.finished = True
        assert mixed is not None
        return mixed

    def frames(self, count: int) -> Iterable[np.ndarray]:
        for _ in range(count):
            yield self.step()
