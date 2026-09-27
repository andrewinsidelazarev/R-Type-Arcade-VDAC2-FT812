#!/usr/bin/env python3
"""Verify the generated HQA2 lookup against assembled Z80 and exact pixels."""

from __future__ import annotations

import collections
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from sim_hq_sprite_upload_check import install_streaming_inflate  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


LOOKUP_HEADER = struct.Struct("<4sBBHII")
LOOKUP_RECORD = struct.Struct("<HBBHI")
SPRITE_CELL_BYTES = 27 * 30 * 2


def call_lookup(
        machine: TSConfFT812Machine,
        symbols: dict[str, int],
        bank_key: int,
        flags: int,
        code: int,
        *,
        expected_page3: int,
        ) -> tuple[bool, int, int]:
    before_sp = machine.reg.SP
    before_ix = machine.reg.IX
    before_iy = machine.reg.IY
    before_tstates = machine.tstates
    machine.call(
        symbols["RTypePyHQSprite_FindCell"],
        d=(bank_key >> 8) & 0xFF,
        e=bank_key & 0xFF,
        c=flags,
        h=(code >> 8) & 0xFF,
        l=code & 0xFF,
        max_steps=1_000_000,
    )
    elapsed = machine.tstates - before_tstates
    if machine.reg.SP != before_sp:
        raise AssertionError("HQ lookup changed Z80 SP")
    if machine.reg.IX != before_ix or machine.reg.IY != before_iy:
        raise AssertionError("HQ lookup changed IX/IY")
    if machine.mem.pages[3] != expected_page3:
        raise AssertionError(
            f"HQ lookup left page3 #{machine.mem.pages[3]:02X}, "
            f"expected #{expected_page3:02X}")
    hit = not bool(machine.reg.F & 0x01)
    address = (machine.reg.A << 16) | (machine.reg.D << 8) | machine.reg.E
    return hit, address, elapsed


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)

    manifest = json.loads((
        ROOT / "Build" / "rtype_python_assets.json").read_text(
            encoding="utf-8"))
    artifact = next(
        item for item in manifest["artifacts"]
        if item["kind"] == "sprite-bootstrap-working-set")
    raw = (ROOT / artifact["path"]).read_bytes()
    lookup = (ROOT / artifact["lookup"]["path"]).read_bytes()
    magic, version, record_size, count, raw_size, reserved = (
        LOOKUP_HEADER.unpack_from(lookup))
    if (magic, version, record_size, count, raw_size, reserved) != (
            b"HQA2", 2, LOOKUP_RECORD.size,
            artifact["lookup"]["record_count"], len(raw), 0):
        raise AssertionError("unexpected HQA2 header")
    records = [
        LOOKUP_RECORD.unpack_from(lookup, LOOKUP_HEADER.size + index * record_size)
        for index in range(count)
    ]
    if records != sorted(records):
        raise AssertionError("HQA2 records are not sorted")
    if any(reserved_byte != 0 for _, _, reserved_byte, _, _ in records):
        raise AssertionError("HQA2 reserved record byte is nonzero")

    lookup_page = symbols["RTYPE_PY_HQ_LOOKUP_PAGE"]
    lookup_ptr = symbols["RTYPE_PY_HQ_LOOKUP_PTR"]
    lookup_offset = lookup_ptr & 0x3FFF
    physical_at = lookup_page * 0x4000 + lookup_offset
    actual_lookup = bytes(machine.mem.physical[
        physical_at:physical_at + len(lookup)])
    if actual_lookup != lookup:
        raise AssertionError("SPG metadata page differs from generated HQA2")

    install_streaming_inflate(machine)
    ramg_base = int(artifact["ram_g_base"])
    machine.ft.ram_g[ramg_base:ramg_base + len(raw)] = bytes(len(raw))
    machine.call(symbols["RTypePyHQSprite_Upload"], max_steps=20_000_000)
    if bytes(machine.ft.ram_g[ramg_base:ramg_base + len(raw)]) != raw:
        raise AssertionError("HQ pixels were not uploaded exactly")

    sentinel_page3 = 0x09
    machine.cpu_write(0x0413, sentinel_page3)
    worst = (0, None)
    seen_keys: set[tuple[int, int, int]] = set()
    offsets: collections.defaultdict[int, list[tuple[int, int, int]]] = (
        collections.defaultdict(list))
    for bank_key, flags, _reserved_byte, code, offset in records:
        key = (bank_key, flags, code)
        if key in seen_keys:
            raise AssertionError(f"duplicate HQA2 key {key}")
        seen_keys.add(key)
        offsets[offset].append(key)
        hit, address, elapsed = call_lookup(
            machine, symbols, bank_key, flags, code,
            expected_page3=sentinel_page3)
        expected_address = ramg_base + offset
        if not hit or address != expected_address:
            raise AssertionError(
                f"lookup {key}: hit={hit}, address=${address:06X}, "
                f"expected=${expected_address:06X}")
        actual_cell = bytes(machine.ft.ram_g[
            address:address + SPRITE_CELL_BYTES])
        expected_cell = raw[offset:offset + SPRITE_CELL_BYTES]
        if actual_cell != expected_cell:
            raise AssertionError(f"lookup {key}: RAM_G pixels differ")
        worst = max(worst, (elapsed, key))

    first = records[0]
    hit, address, elapsed = call_lookup(
        machine, symbols, first[0], first[1] | 0xFC, first[3] | 0xF000,
        expected_page3=sentinel_page3)
    if not hit or address != ramg_base + first[4]:
        raise AssertionError("Python flag/code masking is not preserved")
    worst = max(worst, (elapsed, (first[0], first[1] | 0xFC,
                                  first[3] | 0xF000)))

    miss_candidates = [(0x0000, 0, 0),
                       (records[0][0], 2, records[0][3]),
                       (0xFFFF, 3, 0xFFFF)]
    miss_keys = [key for key in miss_candidates if key not in seen_keys]
    for key in miss_keys:
        hit, _, elapsed = call_lookup(
            machine, symbols, *key, expected_page3=sentinel_page3)
        if hit:
            raise AssertionError(f"unexpected HQA2 hit for {key}")
        worst = max(worst, (elapsed, key))

    duplicate_groups = sum(1 for keys in offsets.values() if len(keys) > 1)
    print(
        f"Python HQ lookup: {count} exact keys, {len(offsets)} pixel cells, "
        f"{duplicate_groups} dedup groups, worst {worst[0]} t-states, "
        "page3/SP/IX/IY preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
