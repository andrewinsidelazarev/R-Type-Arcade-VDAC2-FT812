#!/usr/bin/env python3
"""Verify a full FT812 frame larger than one usable CMD FIFO window.

The queue stores a complete stream.  Resident DMA must split it into aligned
chunks of at most 4092 bytes while FT812 consumes the FIFO; the full payload is
not itself limited to 4092 bytes.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from pyz80_compiler.ft812_budget import (  # noqa: E402
    FT812Timing,
    analyze_display_list,
    expand_coprocessor_stream,
)
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


QUEUE_PAGE = 0xED
PAYLOAD_ADDRESS = 0xC010
FIFO_USABLE = 4092
CMD_DLSTART = 0xFFFFFF00
CMD_SWAP = 0xFFFFFF01
DL_DISPLAY = 0x00000000


class StreamingCommandMachine(TSConfFT812Machine):
    """Add incremental DL consumption missing from the shared test model.

    The shared simulator waits for DISPLAY/SWAP to be present in the same FIFO
    window as DLSTART.  Real FT812 consumes ordinary display-list words while
    the host is still streaming them, which is precisely what a payload larger
    than 4092 bytes needs.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._stream_active = False
        self._stream_dl_ptr = 0

    def _process_cmd_fifo(self) -> None:
        mask = len(self.ft.ram_cmd) - 1

        def available() -> int:
            return (self.ft.cmd_write_ptr - self.ft.cmd_read_ptr) & mask

        def word_at(position: int) -> int:
            return int.from_bytes(bytes(
                self.ft.ram_cmd[(position + offset) & mask]
                for offset in range(4)), "little")

        while available() >= 4:
            read = self.ft.cmd_read_ptr & mask
            word = word_at(read)
            if not self._stream_active:
                self.ft.cmd_read_ptr = (read + 4) & mask
                if word == CMD_DLSTART:
                    self._stream_active = True
                    self._stream_dl_ptr = 0
                continue
            if word == CMD_SWAP:
                self.ft.cmd_read_ptr = (read + 4) & mask
                self.ft.int_flags |= 0x01
                self._stream_active = False
                continue
            # This synthetic stream contains no multiword coprocessor command;
            # all words between DLSTART and SWAP are literal RAM_DL words.
            end = self._stream_dl_ptr + 4
            if end <= len(self.ft.ram_dl):
                self.ft.ram_dl[self._stream_dl_ptr:end] = word.to_bytes(
                    4, "little")
            self._stream_dl_ptr = end
            self.ft.cmd_read_ptr = (read + 4) & mask


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    # 1100 harmless state words make the stream cross the FIFO boundary while
    # staying below both RAM_DL=2048 and the practical 1209 clocks/line limit.
    display_words = [
        (0x04 << 24) | ((index * 37) & 0xFFFFFF)
        for index in range(1100)
    ] + [DL_DISPLAY]
    stream_words = [CMD_DLSTART] + display_words + [CMD_SWAP]
    payload = b"".join(struct.pack("<I", word) for word in stream_words)
    if not FIFO_USABLE < len(payload) < 0x4000 - 0x10:
        raise AssertionError("test payload does not cross exactly one TS page FIFO")

    expansion = expand_coprocessor_stream(payload)
    expected_dl = b"".join(struct.pack("<I", word) for word in display_words)
    if expansion.display_list != expected_dl:
        raise AssertionError("host expansion changed the synthetic FT stream")
    budget = analyze_display_list(
        expansion.display_list,
        FT812Timing(hcycle=1344, pclk=1, safety_utilization=0.90),
    )
    if not budget.passed or budget.worst_cycles > 1209:
        raise AssertionError(
            f"synthetic stream exceeds working line limit: "
            f"{budget.worst_cycles}/1209")

    machine = StreamingCommandMachine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    machine.cpu_write(0x0413, QUEUE_PAGE)
    machine.mem.write_block_linear(PAYLOAD_ADDRESS, payload)
    machine.ft.ram_cmd[:] = bytes(len(machine.ft.ram_cmd))
    machine.ft.ram_dl[:] = bytes(len(machine.ft.ram_dl))
    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    machine._stream_active = False
    machine._stream_dl_ptr = 0

    before_sp = machine.reg.SP
    before_pages = tuple(machine.mem.pages)
    before_errors = len(machine.errors)
    machine.call(
        symbols["RTypeFT_CmdWritePageDMA"],
        a=QUEUE_PAGE,
        b=(len(payload) >> 8) & 0xFF,
        c=len(payload) & 0xFF,
        h=(PAYLOAD_ADDRESS >> 8) & 0xFF,
        l=PAYLOAD_ADDRESS & 0xFF,
        max_steps=8_000_000,
    )
    if machine.reg.F & 1:
        raise AssertionError("resident page DMA returned carry")
    if machine.reg.SP != before_sp or tuple(machine.mem.pages) != before_pages:
        raise AssertionError("resident page DMA changed SP or MMU pages")
    if len(machine.errors) != before_errors:
        raise AssertionError(
            f"FT812 simulator errors: {machine.errors[before_errors:]}")
    actual_dl = bytes(machine.ft.ram_dl[:len(expected_dl)])
    if actual_dl != expected_dl:
        first = next(
            index for index, (actual, expected) in
            enumerate(zip(actual_dl, expected_dl)) if actual != expected)
        raise AssertionError(
            f"multi-chunk DMA changed FT812 RAM_DL at byte {first}: "
            f"actual={actual_dl[first]:02X}, expected={expected_dl[first]:02X}; "
            f"CMD read/write={machine.ft.cmd_read_ptr}/"
            f"{machine.ft.cmd_write_ptr}; "
            f"actual words={[f'{item[0]:08X}' for item in struct.iter_unpack('<I', actual_dl[:32])]}; "
            f"expected words={[f'{item[0]:08X}' for item in struct.iter_unpack('<I', expected_dl[:32])]}")

    chunks = (len(payload) + FIFO_USABLE - 1) // FIFO_USABLE
    print(
        f"FT812 page DMA: {len(payload)} bytes in {chunks} aligned chunks; "
        f"RAM_DL {budget.word_count}/2048 words; line "
        f"{budget.worst_line}={budget.worst_cycles}/1209; SP/MMU preserved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
