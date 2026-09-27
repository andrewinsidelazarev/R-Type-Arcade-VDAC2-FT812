#!/usr/bin/env python3
"""Исполнить собранный загрузчик General Sound на строгой host-модели.

Проверяются порядок команд/данных Z80 и точные байты страниц SPG. Это
host-симуляция протокола, а не доказательство Unreal или физического MultiSound.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "HMM2" / "Pre-releases" /
                       "v020-2026-07-16-adventure-ui-battle-ai-reference" /
                       "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402
from split_sprites import pad_gs_fx  # noqa: E402


GS_PORT_DATA = 0xB3
GS_PORT_CMD = 0xBB
GS_WAVE_FX_HANDLE = 7
GS_SHOT_FX_HANDLE = 8
GS_RAM_PAGES = 0x80

GS_PRESENT = 0x4214
GS_LOADED = 0x4215
GS_WAVE_HANDLE_STATE = 0x4216
GS_REPORTED_PAGES = 0x4217
GS_LAST_ERROR = 0x4218
WAVE_PENDING = 0x4213
SHOT_PENDING = 0x424B
GS_SHOT_HANDLE_STATE = 0x421E


class GeneralSoundMachine(TSConfFT812Machine):
    """Минимальная модель GS FIFO/команд с точным захватом потока байтов."""

    def __init__(self, *args, pages_without_ready: bool = False,
                 **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.gs_commands: list[int] = []
        self.gs_control_data: list[int] = []
        self.gs_reads: list[int] = []
        self.gs_read_queue: list[int] = []
        self.gs_direct_read: int | None = None
        self.gs_next_handle = GS_WAVE_FX_HANDLE
        self.gs_streaming = False
        self.gs_stream = bytearray()
        self.gs_pages_without_ready = pages_without_ready
        super().__init__(*args, **kwargs)

    def in_port(self, port: int) -> int:
        low = port & 0xFF
        if low == GS_PORT_CMD:
            # bit7 сообщает об ожидающем байте host→Z80; bit0=0 завершает команду.
            return 0x80 if self.gs_read_queue else 0x00
        if low == GS_PORT_DATA:
            if self.gs_read_queue:
                value = self.gs_read_queue.pop(0)
            elif self.gs_direct_read is not None:
                value = self.gs_direct_read
                self.gs_direct_read = None
            else:
                value = 0x00
            self.gs_reads.append(value)
            return value
        return super().in_port(port)

    def out_port(self, port: int, value: int) -> None:
        low = port & 0xFF
        value &= 0xFF
        if low == GS_PORT_CMD:
            self.gs_commands.append(value)
            if value == 0x23:
                if self.gs_pages_without_ready:
                    # Unreal 0.37.9 BASS-HLE: #B3 содержит ответ, но #BB=$7E,
                    # поэтому bit7 data-ready не появляется.
                    self.gs_direct_read = GS_RAM_PAGES
                else:
                    self.gs_read_queue.append(GS_RAM_PAGES)
            elif value == 0x38:
                self.gs_direct_read = self.gs_next_handle
                self.gs_next_handle += 1
            elif value == 0xD1:
                self.gs_streaming = True
            elif value == 0xD2:
                self.gs_streaming = False
            return
        if low == GS_PORT_DATA:
            if self.gs_streaming:
                self.gs_stream.append(value)
            else:
                self.gs_control_data.append(value)
            return
        super().out_port(port, value)


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = GeneralSoundMachine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(sym["MainLoop"], max_steps=50_000_000)

    expected_wave = pad_gs_fx((
        ROOT / "Audio" / "Converted" /
        "RTYPE_WAVE_SHOT_U8_11025.raw"
    ).read_bytes())
    expected_shot = pad_gs_fx((
        ROOT / "Audio" / "Converted" /
        "RTYPE_SFX_SHOT_U8_22050.raw"
    ).read_bytes())
    assert bytes(machine.gs_stream) == expected_wave + expected_shot
    assert machine.get_byte(GS_PRESENT) == 1
    assert machine.get_byte(GS_LOADED) == 1
    assert machine.get_byte(GS_WAVE_HANDLE_STATE) == GS_WAVE_FX_HANDLE
    assert machine.get_byte(GS_SHOT_HANDLE_STATE) == GS_SHOT_FX_HANDLE
    assert machine.get_byte(GS_REPORTED_PAGES) == GS_RAM_PAGES
    assert machine.get_byte(GS_LAST_ERROR) == 0
    assert machine.mem.pages[3] == 0
    assert machine.gs_reads == [
        GS_RAM_PAGES, GS_WAVE_FX_HANDLE, GS_SHOT_FX_HANDLE]
    load_commands = [0x38, 0x2E, 0x40, 0x41, 0x45, 0x46, 0x47, 0xD1, 0xD2]
    assert machine.gs_commands == [0xF3, 0x23, 0x2B] + load_commands * 2
    assert machine.gs_control_data == [
        0x40,
        GS_WAVE_FX_HANDLE, 53, 0x40, 0xC0, 0xFF, 0xFF,
        GS_SHOT_FX_HANDLE, 53, 0x40, 0xC0, 0xFF, 0xFF,
    ]

    command_count = len(machine.gs_commands)
    data_count = len(machine.gs_control_data)
    machine.set_byte(WAVE_PENDING, 1)
    machine.call(sym["GeneralSound_Update"], max_steps=1_000_000)
    assert machine.gs_commands[command_count:] == [0x98]
    assert machine.gs_control_data[data_count:] == [
        GS_WAVE_FX_HANDLE, 53, 0x40]

    # Обычный выстрел использует второй handle и ноту на октаву выше, потому
    # что его PCM записан на 22050 Гц.
    machine.set_byte(WAVE_PENDING, 0)
    machine.set_byte(SHOT_PENDING, 1)
    command_count = len(machine.gs_commands)
    data_count = len(machine.gs_control_data)
    machine.call(sym["GeneralSound_Update"], max_steps=1_000_000)
    assert machine.gs_commands[command_count:] == [0x98]
    assert machine.gs_control_data[data_count:] == [
        GS_SHOT_FX_HANDLE, 65, 0x40]

    bass_hle = GeneralSoundMachine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
        pages_without_ready=True,
    )
    bass_hle.run_until_pc(sym["MainLoop"], max_steps=80_000_000)
    assert bass_hle.get_byte(GS_PRESENT) == 1
    assert bass_hle.get_byte(GS_LOADED) == 1
    assert bass_hle.get_byte(GS_REPORTED_PAGES) == GS_RAM_PAGES
    assert bass_hle.get_byte(GS_LAST_ERROR) == 0
    assert bytes(bass_hle.gs_stream) == expected_wave + expected_shot

    print("Собранный протокол General Sound: OK")
    print(f"Стартовый поток: {len(expected_wave) + len(expected_shot)} точных "
          "байтов из двух страниц SPG в GS")
    print("Runtime: Wave handle 7/нота 53; выстрел handle 8/нота 65")
    print("Unreal BASS-HLE status #7E fallback: OK")
    print("Граница: только host-модель; физический MultiSound не проверен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
