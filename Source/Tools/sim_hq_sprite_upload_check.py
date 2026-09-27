#!/usr/bin/env python3
"""Проверить DMA→CMD_INFLATE загрузку точных Python HQ sprite cells."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import types
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


FT_CMD_INFLATE = 0xFFFFFF22
RAM_CMD_SIZE = 0x1000


def install_streaming_inflate(machine: TSConfFT812Machine) -> None:
    """Моделировать потребление zlib-потока, который больше 4-КБ FIFO."""
    if machine.ft.cmd_read_ptr != machine.ft.cmd_write_ptr:
        raise AssertionError("FT812 FIFO должен быть пуст перед HQ upload")
    state: dict[str, object] = {}

    def fifo_bytes(self: TSConfFT812Machine, position: int, size: int) -> bytes:
        return bytes(
            self.ft.ram_cmd[(position + index) & (RAM_CMD_SIZE - 1)]
            for index in range(size))

    def process(self: TSConfFT812Machine) -> None:
        while True:
            read = self.ft.cmd_read_ptr & (RAM_CMD_SIZE - 1)
            write = self.ft.cmd_write_ptr & (RAM_CMD_SIZE - 1)
            available = (write - read) & (RAM_CMD_SIZE - 1)
            if "inflater" not in state:
                if available < 8:
                    return
                command, destination = struct.unpack(
                    "<II", fifo_bytes(self, read, 8))
                if command != FT_CMD_INFLATE:
                    raise AssertionError(
                        f"неожиданная FT812-команда ${command:08X}")
                self.ft.cmd_read_ptr = (read + 8) & (RAM_CMD_SIZE - 1)
                state.update({
                    "inflater": zlib.decompressobj(),
                    "destination": destination,
                    "output": 0,
                    "input": 0,
                })
                continue
            if available == 0:
                return
            # TS DMA вызывает модель после каждого байта. Реальный FT812
            # потребляет поток параллельно крупными порциями; группировка по
            # 256 байт сохраняет FIFO-семантику и не превращает тест в 40 000
            # отдельных вызовов zlib. Неизменившийся короткий хвост означает,
            # что producer закончил очередной DMA chunk или вошёл в WaitFlush.
            if available < 256:
                final_padding_visible = (
                    available >= 3 and
                    fifo_bytes(self, read + available - 3, 3) == b"\0\0\0")
                if (not final_padding_visible and
                        state.get("short_available") != available):
                    state["short_available"] = available
                    return
            state.pop("short_available", None)
            inflater = state["inflater"]
            payload = fifo_bytes(self, read, available)
            output = inflater.decompress(payload)
            consumed = len(payload) - len(inflater.unused_data)
            destination = int(state["destination"]) + int(state["output"])
            end = destination + len(output)
            if not 0 <= destination <= end <= len(self.ft.ram_g):
                raise AssertionError("CMD_INFLATE вышел за RAM_G")
            self.ft.ram_g[destination:end] = output
            state["output"] = int(state["output"]) + len(output)
            state["input"] = int(state["input"]) + consumed
            self.ft.cmd_read_ptr = (read + consumed) & (RAM_CMD_SIZE - 1)
            if not inflater.eof:
                if consumed == 0:
                    return
                continue
            padding = (-int(state["input"])) & 3
            read = self.ft.cmd_read_ptr & (RAM_CMD_SIZE - 1)
            write = self.ft.cmd_write_ptr & (RAM_CMD_SIZE - 1)
            if ((write - read) & (RAM_CMD_SIZE - 1)) < padding:
                return
            self.ft.cmd_read_ptr = (read + padding) & (RAM_CMD_SIZE - 1)
            state.clear()

    machine._process_cmd_fifo = types.MethodType(process, machine)


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)
    install_streaming_inflate(machine)

    manifest = json.loads((
        ROOT / "Build" / "rtype_python_assets.json").read_text(
            encoding="utf-8"))
    artifact = next(
        item for item in manifest["artifacts"]
        if item["kind"] == "sprite-bootstrap-working-set")
    pixels = (ROOT / artifact["path"]).read_bytes()
    append_info = artifact["templates"]["append"]
    append_pack = (ROOT / append_info["path"]).read_bytes()
    destination = int(artifact["ram_g_base"])
    append_destination = int(append_info["ram_g_base"])
    if append_destination != (destination + len(pixels) + 3) & ~3:
        raise AssertionError("CMD_APPEND pack does not immediately follow pixels")
    expected = (
        pixels + bytes(append_destination - destination - len(pixels)) +
        append_pack)
    machine.ft.ram_g[destination:destination + len(expected)] = bytes(
        len(expected))

    before = machine.tstates
    machine.call(symbols["RTypePyHQSprite_Upload"], max_steps=20_000_000)
    elapsed = machine.tstates - before
    actual = bytes(machine.ft.ram_g[
        destination:destination + len(expected)])
    if actual != expected:
        mismatch = next(
            index for index, pair in enumerate(zip(actual, expected))
            if pair[0] != pair[1])
        raise AssertionError(
            f"HQ upload расходится по offset {mismatch}: "
            f"${actual[mismatch]:02X} != ${expected[mismatch]:02X}")
    if machine.ft.cmd_read_ptr != machine.ft.cmd_write_ptr:
        raise AssertionError("CMD_INFLATE не освободил FT812 FIFO")
    print(
        f"Python HQ sprite upload: {len(pixels)} pixel + "
        f"{len(append_pack)} CMD_APPEND bytes, "
        f"sha256={hashlib.sha256(actual).hexdigest()}, {elapsed} t-states"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
