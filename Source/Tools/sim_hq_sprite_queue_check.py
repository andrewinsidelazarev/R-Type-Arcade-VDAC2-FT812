#!/usr/bin/env python3
"""Execute and verify the compiled C FT812 HQ-sprite queue on the Z80.

The check calls the real SDCC ``__sdcccall(0)`` entry points from page #F0.
It deliberately does not call or modify the live renderer: page #ED is used as
an isolated queue, then one completed stream is sent through the resident DMA
backend into the simulated FT812.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

from pyz80_compiler.ft812_budget import (  # noqa: E402
    FT812Timing,
    analyze_display_list,
    expand_coprocessor_stream,
)
from rtype_port import enemies as python_enemies  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


HQT_HEADER = struct.Struct("<4sBBHIII")
HQT_TEMPLATE = struct.Struct("<HBBHhhHBBHH")
HQT_STATE = struct.Struct("<II")
HQT_CELL = struct.Struct("<IhhB")
QUEUE_HEADER = struct.Struct("<HBBHHHHBBBB")
LOWERED_COORD = struct.Struct("<hhB")
DRAW_RECORD = struct.Struct("<HHhh")
FAST_DRAW_RECORD = struct.Struct("<Hhh")

QUEUE_ADDRESS = 0xC000
QUEUE_WORDS = QUEUE_ADDRESS + QUEUE_HEADER.size
QUEUE_BYTES = 0x4000
QUEUE_PAGES = (0xED, 0xEE)
QUEUE_MAGIC = 0x4651
QUEUE_FORMAT = 3
QUEUE_FREE = 0
QUEUE_BUILDING = 1
QUEUE_READY = 2
QUEUE_FULL = 0
QUEUE_FRAGMENT = 1
QUEUE_STATE_ADDRESS = QUEUE_ADDRESS + 12
LOWER_SCRATCH = QUEUE_ADDRESS + 0x3FF0
BATCH_RECORD_ADDRESS = 0xFC00
BATCH_RECORD_MIN = 0xCA44
BATCH_RECORD_BYTES = 0x35BC
BATCH_MAX_RECORDS = 128
BATCH_CACHE_ADDRESS = 0xB800
BATCH_CACHE_RECORD_BYTES = 10
BATCH_CACHE_BYTES = BATCH_MAX_RECORDS * BATCH_CACHE_RECORD_BYTES
NATIVE_X_RANGE = (-1535, 1535)
NATIVE_Y_RANGE = (-1365, 1365)
LOGICAL_VERTEX_RANGE = (-512, 767)
GENERIC_APPEND_BASELINE_TSTATES = 76821
BATCH_BASELINE_CODE_BYTES = 12998
BATCH_BASELINE_TSTATES = {
    0: 12946,
    1: 40080,
    4: 120570,
    16: 447090,
    32: 881234,
    128: 3486098,
}
STREAM_CHUNK_PERF_RECORDS = 32
ZCLK_HZ = 14_000_000
TARGET_FRAME_HZ = 55

# Every project input that can change this executable proof or its ABI is
# bound into the emitted report.  The list is deliberately explicit: adding
# a new simulator/compiler dependency requires a conscious report update,
# while absolute checkout paths never leak into the reproducible artifact.
REPORT_BINDING_PATHS = (
    "Source/Tools/sim_hq_sprite_queue_check.py",
    "Source/Tools/pyz80_compiler/ft812_budget.py",
    "Source/Tools/rtype_python_assets.py",
    "Source/Python/rtype_port/enemies.py",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Build/rtype_python_assets.json",
    "Build/rtype_python_compiler.json",
    "Build/python_compiled_p00.bin",
    "Build/rtype_python_compiled.asm",
    "Build/rtype_python_compiled.map",
)

CMD_DLSTART = 0xFFFFFF00
CMD_SWAP = 0xFFFFFF01
CMD_APPEND = 0xFFFFFF1E
DL_DISPLAY = 0x00000000
DL_COLOR_WHITE = 0x04FFFFFF
DL_BITMAP_SOURCE = 0x01000000
DL_BITMAP_LAYOUT = 0x07000000
DL_PALETTE_SOURCE = 0x2A000000
DL_BITMAP_SIZE = (0x08 << 24) | (44 << 9) | 48
DL_BITMAP_TRANSFORM_A = (0x15 << 24) | 160
DL_BITMAP_TRANSFORM_B = 0x16000000
DL_BITMAP_TRANSFORM_C = 0x17000000
DL_BITMAP_TRANSFORM_D = 0x18000000
DL_BITMAP_TRANSFORM_E = (0x19 << 24) | 160
DL_BITMAP_TRANSFORM_F = 0x1A000000
DL_VERTEX_FORMAT_3 = (0x27 << 24) | 3
DL_VERTEX_TRANSLATE_X = 0x2B << 24
DL_VERTEX_TRANSLATE_Y = 0x2C << 24
DL_BEGIN_BITMAPS = (0x1F << 24) | 1
DL_END = 0x21000000

SPRITE_SETUP = (
    DL_BITMAP_TRANSFORM_A,
    DL_BITMAP_TRANSFORM_B,
    DL_BITMAP_TRANSFORM_C,
    DL_BITMAP_TRANSFORM_D,
    DL_BITMAP_TRANSFORM_E,
    DL_BITMAP_TRANSFORM_F,
    DL_BITMAP_SIZE,
    DL_VERTEX_FORMAT_3,
    DL_BEGIN_BITMAPS,
)
BATCH_PREFIX = (DL_COLOR_WHITE,) + SPRITE_SETUP


@dataclass(frozen=True)
class HQTemplate:
    bank_key: int
    flags: int
    resource_type: int
    descriptor_address: int
    dx: int
    dy: int
    code: int
    width: int
    height: int
    cell_first: int
    cell_count: int


@dataclass(frozen=True)
class HQCell:
    ram_g: int
    local_x: int
    local_y: int
    state_index: int


@dataclass(frozen=True)
class HQBitmapState:
    layout: int
    palette_ram_g: int


@dataclass(frozen=True)
class HQAppendPack:
    ram_g_base: int
    data: bytes
    blob_count: int


@dataclass(frozen=True)
class HQSpritePack:
    ram_g_base: int
    data: bytes
    inflated: bytes
    decoded_by_key: dict[tuple[int, int, int], bytes]


@dataclass(frozen=True)
class QueueHeader:
    magic: int
    format: int
    page: int
    frame_sequence: int
    count: int
    payload_bytes: int
    dl_words: int
    state: int
    overflow: int
    kind: int
    reserved: int


def _report_source_bindings() -> dict[str, str]:
    """Return path-stable SHA-256 bindings for every focused-proof input."""
    result: dict[str, str] = {}
    for relative in REPORT_BINDING_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise AssertionError(f"report binding input is missing: {relative}")
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _translator_protocol_binding() -> str:
    """Bind only the translator's declared queue ABI, not unrelated code."""
    path = ROOT / "Source" / "Tools" / "rtype_python_translator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected: list[ast.AST] = []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and
                any(isinstance(target, ast.Name) and
                    target.id == "FT812_SUPPORT_EXPORTS"
                    for target in node.targets)):
            selected.append(node)
        elif (isinstance(node, ast.FunctionDef) and
              node.name == "ft812_queue_protocol_contract"):
            selected.append(node)
    if len(selected) != 2:
        raise AssertionError(
            "translator FT812 support/protocol declaration is incomplete")
    payload = "\n".join(
        ast.dump(node, annotate_fields=True, include_attributes=False)
        for node in selected).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _expected_template_hash(
        templates: list[HQTemplate],
        ) -> tuple[list[int], dict[str, object]]:
    """Rebuild the generator's deterministic bounded resolver table."""
    slot_count = 2
    while slot_count < max(2, len(templates) * 2):
        slot_count <<= 1
    while True:
        slots = [0] * slot_count
        max_probe = 0
        for template_index, template in enumerate(templates):
            slot = (
                template.bank_key ^ (template.bank_key >> 8) ^
                template.descriptor_address ^
                (template.descriptor_address >> 8)
            ) & (slot_count - 1)
            probe = 0
            while slots[slot] != 0:
                slot = (slot + 1) & (slot_count - 1)
                probe += 1
            slots[slot] = template_index + 1
            max_probe = max(max_probe, probe)
        if max_probe <= 4:
            break
        slot_count <<= 1
        if slot_count > 0x8000:
            raise AssertionError("cannot rebuild bounded HQT3 resolver hash")
    return slots, {
        "algorithm": "xor-u16-bytes-open-address-v1",
        "seed": 0,
        "slot_count": slot_count,
        "entry_bytes": 2,
        "table_bytes": slot_count * 2,
        "batch_geometry_bytes": len(templates) * 12,
        "load_count": len(templates),
        "max_preceding_probes": max_probe,
        "max_lookup_probes": max_probe + 1,
        "empty_entry": 0,
        "stored_value": "template_index_plus_one",
    }


def _load_linker_layout() -> dict[str, object]:
    """Prove private-cache placement from the actual SDCC linker map."""
    map_path = ROOT / "Build" / "rtype_python_compiled.map"
    text = map_path.read_text(encoding="utf-8", errors="strict")

    def symbol(name: str) -> int:
        match = re.search(
            rf"(?m)^\s*([0-9A-Fa-f]{{8}})\s+{re.escape(name)}(?:\s|$)",
            text)
        if match is None:
            raise AssertionError(f"compiled linker map misses {name}")
        return int(match.group(1), 16)

    code_start = symbol("s__CODE")
    code_size = symbol("l__CODE")
    data_start = symbol("s__DATA")
    data_size = symbol("l__DATA")
    home_start = symbol("s__HOME")
    home_size = symbol("l__HOME")
    cache_start = symbol("_PyZ80FT_BatchResolved")
    hash_start = symbol("_PyZ80FT_HQTemplateHash")
    geometry_start = symbol("_PyZ80FT_HQBatchGeometry")
    code_end = code_start + code_size
    data_end = data_start + data_size
    home_end = home_start + home_size
    if (code_start != 0x8000 or code_end > data_start or
            data_start != BATCH_CACHE_ADDRESS or
            data_size != BATCH_CACHE_BYTES or cache_start != data_start or
            data_end != 0xBD00 or home_start < data_end or
            home_end > QUEUE_ADDRESS):
        raise AssertionError(
            "compiled #F0 CODE/cache/HOME ranges overlap or moved")
    if not (code_start <= hash_start < geometry_start < code_end):
        raise AssertionError("generated resolver/geometry left compiled CODE")
    code_headroom = data_start - code_end
    if code_headroom < 1802:
        raise AssertionError(
            f"compiled #F0 code headroom shrank to {code_headroom} bytes")
    if not (data_end <= QUEUE_ADDRESS and
            not (cache_start < 0x10000 and QUEUE_ADDRESS < data_end)):
        raise AssertionError("private batch cache overlaps public queue VMA")
    return {
        "map": map_path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "code": {
            "start": code_start,
            "end_exclusive": code_end,
            "size": code_size,
            "headroom_before_cache": code_headroom,
        },
        "private_cache": {
            "symbol": "PyZ80FT_BatchResolved",
            "start": cache_start,
            "end_exclusive": data_end,
            "size": data_size,
            "record_size": BATCH_CACHE_RECORD_BYTES,
            "records": BATCH_MAX_RECORDS,
            "physical_page": 0xF0,
            "public_queue_pages": list(QUEUE_PAGES),
            "public_queue_vma": [QUEUE_ADDRESS, 0x10000],
            "non_overlapping": True,
            "published": False,
        },
        "home": {
            "start": home_start,
            "end_exclusive": home_end,
            "size": home_size,
        },
        "free_after_cache": QUEUE_ADDRESS - data_end,
        "hash_address": hash_start,
        "geometry_address": geometry_start,
    }


def _load_templates(
        ) -> tuple[
            list[HQTemplate], list[HQBitmapState], list[HQCell],
            HQAppendPack, HQSpritePack]:
    manifest = json.loads((
        ROOT / "Build" / "rtype_python_assets.json").read_text(
            encoding="utf-8"))
    artifact = next(
        item for item in manifest["artifacts"]
        if item["kind"] == "sprite-bootstrap-working-set")
    info = artifact["templates"]
    path = ROOT / info["path"]
    data = path.read_bytes()
    if len(data) != int(info["size"]):
        raise AssertionError("HQT3 size differs from the asset manifest")
    if hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise AssertionError("HQT3 hash differs from the asset manifest")

    (magic, version, template_size, template_count, cell_count, cell_size,
     state_count) = HQT_HEADER.unpack_from(data)
    if (magic, version, template_size, template_count, cell_count, cell_size,
            state_count) != (
            b"HQT3", 3, HQT_TEMPLATE.size, int(info["record_count"]),
            int(info["cell_count"]), HQT_CELL.size,
            int(info["state_count"])):
        raise AssertionError("unexpected HQT3 header")
    templates = [
        HQTemplate(*HQT_TEMPLATE.unpack_from(
            data, HQT_HEADER.size + index * HQT_TEMPLATE.size))
        for index in range(template_count)
    ]
    state_base = HQT_HEADER.size + template_count * HQT_TEMPLATE.size
    states = [
        HQBitmapState(*HQT_STATE.unpack_from(
            data, state_base + index * HQT_STATE.size))
        for index in range(state_count)
    ]
    cell_base = state_base + state_count * HQT_STATE.size
    cells = [
        HQCell(*HQT_CELL.unpack_from(
            data, cell_base + index * HQT_CELL.size))
        for index in range(cell_count)
    ]
    if len(data) != cell_base + len(cells) * HQT_CELL.size:
        raise AssertionError("HQT3 has trailing or truncated cell data")
    for index, template in enumerate(templates):
        if template.cell_count != template.width * template.height:
            raise AssertionError(
                f"HQT3 template {index} cell grid is inconsistent")
        if template.cell_first + template.cell_count > len(cells):
            raise AssertionError(f"HQT3 template {index} cells are out of range")
    if any(cell.state_index >= len(states) for cell in cells):
        raise AssertionError("HQT3 cell has an invalid state index")
    append_info = info["append"]
    append_data = (ROOT / append_info["path"]).read_bytes()
    if (len(append_data) != int(append_info["size"]) or
            hashlib.sha256(append_data).hexdigest() != append_info["sha256"]):
        raise AssertionError("CMD_APPEND pack differs from the asset manifest")
    append_base = int(append_info["ram_g_base"])
    if append_base & 3 or append_base + len(append_data) > 0x100000:
        raise AssertionError("CMD_APPEND pack has an invalid RAM_G range")

    pack_path = ROOT / artifact["path"]
    pack_data = pack_path.read_bytes()
    if (len(pack_data) != int(artifact["size"]) or
            hashlib.sha256(pack_data).hexdigest() != artifact["sha256"]):
        raise AssertionError("hybrid FT812 sprite pack differs from manifest")
    compressed_info = artifact["compressed"]
    compressed = (ROOT / compressed_info["path"]).read_bytes()
    if (len(compressed) != int(compressed_info["size"]) or
            hashlib.sha256(compressed).hexdigest() !=
            compressed_info["sha256"]):
        raise AssertionError("hybrid FT812 zlib differs from manifest")
    inflated = zlib.decompress(compressed[:int(compressed_info["zlib_size"])])
    padding = append_base - (int(artifact["ram_g_base"]) + len(pack_data))
    if inflated != pack_data + bytes(padding) + append_data:
        raise AssertionError("hybrid FT812 zlib does not contain pack+append")

    decoded_by_key: dict[tuple[int, int, int], bytes] = {}
    for entry in artifact["entries"]:
        offset = int(entry["offset"])
        size = int(entry["size"])
        payload = pack_data[offset:offset + size]
        format_code = int(entry["format_code"])
        if format_code == 6:
            decoded = payload
        elif format_code == 15:
            palette_offset = int(entry["palette_offset"])
            palette_data = pack_data[palette_offset:palette_offset + 512]
            decoded = b"".join(
                palette_data[index * 2:index * 2 + 2]
                for index in payload)
        else:
            raise AssertionError(f"unsupported FT812 format {format_code}")
        if hashlib.sha256(decoded).hexdigest() != entry["decoded_sha256"]:
            raise AssertionError("hybrid FT812 decoded cell hash differs")
        resource = str(entry["resource"])
        bank_key = (0x0100 | int(resource[4:], 16)
                    if resource.startswith("type") else
                    int(entry["palette"]) & 0x0F)
        key = (
            bank_key,
            int(bool(entry["flip_x"])) |
            (int(bool(entry["flip_y"])) << 1),
            int(entry["code"]),
        )
        decoded_by_key[key] = decoded
    return (templates, states, cells,
            HQAppendPack(append_base, append_data,
                         int(append_info["blob_count"])),
            HQSpritePack(int(artifact["ram_g_base"]), pack_data, inflated,
                         decoded_by_key))


def _load_support() -> tuple[dict[str, int], int, dict[str, object]]:
    report = json.loads((
        ROOT / "Build" / "rtype_python_compiler.json").read_text(
            encoding="utf-8"))
    binary = (ROOT / "Build" / "python_compiled_p00.bin").read_bytes()
    if len(binary) != int(report["binary_size"]):
        raise AssertionError("compiled C bank size differs from its report")
    if hashlib.sha256(binary).hexdigest() != report["binary_sha256"]:
        raise AssertionError("compiled C bank hash differs from its report")
    support = {
        str(item["export"]): int(item["address"])
        for item in report["support_functions"]
    }
    required = {
        "PyZ80FT_QueueInitialize",
        "PyZ80FT_QueueAcquire",
        "PyZ80FT_QueueAcquireFragment",
        "PyZ80FT_QueuePushDL",
        "PyZ80FT_ResolveBankKey",
        "PyZ80FT_LogicalVertex",
        "PyZ80FT_LowerNativeX",
        "PyZ80FT_LowerNativeY",
        "PyZ80FT_FindHQTemplate",
        "PyZ80FT_QueuePushTemplate",
        "PyZ80FT_QueuePushDescriptor",
        "PyZ80FT_QueuePushDescAppend",
        "PyZ80FT_BuildSpriteBatch",
        "PyZ80FT_BuildSpriteBatchFast",
        "PyZ80FT_QueueCommit",
        "PyZ80FT_QueueCommitFragment",
    }
    missing = sorted(required - support.keys())
    if missing:
        raise AssertionError(f"compiled C report misses {', '.join(missing)}")
    code_page = int(report["target"]["code_page"])
    if code_page != 0xF0:
        raise AssertionError(f"unexpected compiled C page #{code_page:02X}")
    assembly = (ROOT / "Build" / "rtype_python_compiled.asm").read_text(
        encoding="utf-8")
    for function_name in (
            "PyZ80FT_LogicalVertex",
            "PyZ80FT_LowerNativeX", "PyZ80FT_LowerNativeY",
            "PyZ80FT_ResolveDescriptor", "PyZ80FT_QueuePushTemplateAppend",
            "PyZ80FT_QueuePushDescAppend", "PyZ80FT_BuildSpriteBatch",
            "PyZ80FT_BuildSpriteBatchFast"):
        marker = f"; Function {function_name}\n"
        start = assembly.find(marker)
        if start < 0:
            raise AssertionError(f"compiled assembly misses {marker}")
        end = assembly.find("; Function ", start + len(marker))
        body = assembly[start:end if end >= 0 else len(assembly)]
        if "__div" in body or "__mod" in body:
            raise AssertionError(
                f"hot append lowering {function_name} calls division/modulo")
        if (function_name == "PyZ80FT_LogicalVertex" and
                "\tcall\t" in body):
            raise AssertionError(
                "compiled logical vertex unexpectedly calls a helper")
        if function_name == "PyZ80FT_BuildSpriteBatch":
            if body.count("call _PyZ80FT_FindHQTemplate") != 1:
                raise AssertionError(
                    "batch hot path must contain one generated hash call site")
            for forbidden_call in (
                    "_PyZ80FT_ResolveBankDescriptor",
                    "_PyZ80FT_ResolveDescriptor",
                    "_PyZ80FT_LowerNativeX",
                    "_PyZ80FT_LowerNativeY"):
                if forbidden_call in body:
                    raise AssertionError(
                        "batch hot path repeated portable-C resolution: "
                        f"{forbidden_call}")
            if ("#_PyZ80FT_BatchResolved" not in body or
                    "#_PyZ80FT_HQBatchGeometry" not in body):
                raise AssertionError(
                    "batch hot path lost generated geometry/private cache")
        if function_name == "PyZ80FT_BuildSpriteBatchFast":
            if ("ld -26 (ix), #6" not in body or
                    "jp _PyZ80FT_BuildSpriteBatchShared" not in body):
                raise AssertionError(
                    "pre-resolved batch wrapper lost its shared fast entry")
    for forbidden in ("__divulong", "__divuint", "__modulong", "__moduint"):
        if forbidden in assembly:
            raise AssertionError(
                f"compiled FT812 support still links {forbidden}")
    if "PyZ80FT_LogicalVertexTable" in assembly:
        raise AssertionError("compiled FT812 support still contains vertex LUT")
    return support, code_page, report["target"]["ft812"]


def _call_sdcc0(
        machine: TSConfFT812Machine,
        address: int,
        arguments: bytes,
        *,
        max_steps: int = 2_000_000,
        result_width: int = 8,
        preserve_iy: bool = False,
        ) -> tuple[int, int, int]:
    """Call a caller-cleanup ABI function; read its L or HL result."""
    original_sp = machine.reg.SP
    original_ix = machine.reg.IX
    original_iy = machine.reg.IY
    original_pages = tuple(machine.mem.pages)
    argument_sp = (original_sp - len(arguments)) & 0xFFFF
    machine.mem.write_block_linear(argument_sp, arguments)
    machine.reg.SP = argument_sp
    before = machine.tstates
    steps = machine.call(address, max_steps=max_steps)
    clocks = machine.tstates - before
    if machine.reg.SP != argument_sp:
        raise AssertionError(
            f"SDCC function ${address:04X} returned SP=${machine.reg.SP:04X}, "
            f"expected caller-cleanup SP=${argument_sp:04X}")
    if machine.reg.IX != original_ix:
        raise AssertionError(f"SDCC function ${address:04X} changed IX")
    if preserve_iy and machine.reg.IY != original_iy:
        raise AssertionError(f"SDCC function ${address:04X} changed IY")
    if tuple(machine.mem.pages) != original_pages:
        raise AssertionError(f"SDCC function ${address:04X} changed MMU pages")
    if result_width == 8:
        result = machine.reg.L
    elif result_width == 16:
        result = (machine.reg.H << 8) | machine.reg.L
    else:
        raise AssertionError(f"unsupported SDCC result width {result_width}")
    machine.reg.SP = original_sp
    return result, steps, clocks


def _header(machine: TSConfFT812Machine) -> QueueHeader:
    return QueueHeader(*QUEUE_HEADER.unpack(
        machine.get_memory(QUEUE_ADDRESS, QUEUE_HEADER.size)))


def _words(machine: TSConfFT812Machine, count: int) -> list[int]:
    data = machine.get_memory(QUEUE_WORDS, count * 4)
    return [item[0] for item in struct.iter_unpack("<I", data)]


def _logical_vertex(value: int) -> int:
    magnitude = (abs(value) * 64 + 2) // 5
    return (-magnitude if value < 0 else magnitude) & 0xFFFF


def _template_words(
        template: HQTemplate,
        states: list[HQBitmapState],
        cells: list[HQCell],
        base_x: int,
        base_y: int,
        ) -> list[int]:
    result: list[int] = []
    current_layout: int | None = None
    current_palette: int | None = None
    for cell in cells[
            template.cell_first:template.cell_first + template.cell_count]:
        state = states[cell.state_index]
        format_code = (state.layout >> 19) & 0x1F
        if state.layout != current_layout:
            result.append(state.layout)
            current_layout = state.layout
        if format_code == 15 and state.palette_ram_g != current_palette:
            result.append(DL_PALETTE_SOURCE | state.palette_ram_g)
            current_palette = state.palette_ram_g
        vertex_x = _logical_vertex(base_x + cell.local_x)
        vertex_y = _logical_vertex(base_y + cell.local_y)
        result.extend((
            DL_BITMAP_SOURCE | (cell.ram_g & 0x003FFFFF),
            0x40000000 |
            ((vertex_x & 0x7FFF) << 15) |
            (vertex_y & 0x7FFF),
        ))
    return result


def _verify_uploaded_pixels(
        machine: TSConfFT812Machine,
        templates: list[HQTemplate],
        states: list[HQBitmapState],
        cells: list[HQCell],
        decoded_by_key: dict[tuple[int, int, int], bytes],
        ) -> None:
    """Decode every HQT3 cell from RAM_G and compare exact active pixels."""
    covered: set[tuple[int, int, int]] = set()
    for template in templates:
        template_cells = cells[
            template.cell_first:template.cell_first + template.cell_count]
        for ordinal, cell in enumerate(template_cells):
            cell_x, cell_y = divmod(ordinal, template.height)
            source_x = (template.width - 1 - cell_x
                        if template.flags & 1 else cell_x)
            source_y = (template.height - 1 - cell_y
                        if template.flags & 2 else cell_y)
            key = (
                template.bank_key, template.flags,
                (template.code + 8 * source_x + source_y) & 0x0FFF,
            )
            state = states[cell.state_index]
            format_code = (state.layout >> 19) & 0x1F
            stride = (state.layout >> 9) & 0x3FF
            height = state.layout & 0x1FF
            payload = bytes(machine.ft.ram_g[
                cell.ram_g:cell.ram_g + stride * height])
            if format_code == 6:
                if state.palette_ram_g != 0xFFFFFFFF:
                    raise AssertionError("ARGB4 HQT3 state has a palette")
                decoded = payload
            elif format_code == 15:
                palette_data = bytes(machine.ft.ram_g[
                    state.palette_ram_g:state.palette_ram_g + 512])
                decoded = b"".join(
                    palette_data[index * 2:index * 2 + 2]
                    for index in payload)
            else:
                raise AssertionError("HQT3 state has unsupported bitmap format")
            if decoded != decoded_by_key.get(key):
                raise AssertionError(
                    f"HQT3 RAM_G pixels differ for key {key}")
            covered.add(key)
    if covered != set(decoded_by_key):
        raise AssertionError("HQT3 pixel proof did not cover the working set")


def _initialize(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        page: int,
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueueInitialize"],
        struct.pack("<HH", QUEUE_ADDRESS, page),
    )
    if result != 1:
        raise AssertionError(f"QueueInitialize(#{page:02X}) returned {result}")
    expected = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, page, 0, 0, 0, 0,
        QUEUE_FREE, 0, QUEUE_FULL, 0)
    if _header(machine) != expected:
        raise AssertionError(
            f"QueueInitialize header {_header(machine)} != {expected}")
    return steps, clocks


def _acquire(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        page: int,
        sequence: int,
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueueAcquire"],
        struct.pack("<HH", QUEUE_ADDRESS, sequence),
    )
    if result != 1:
        raise AssertionError(f"QueueAcquire(#{page:02X}) returned {result}")
    expected = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, page, sequence, 1, 0, 0,
        QUEUE_BUILDING, 0, QUEUE_FULL, 0)
    if _header(machine) != expected:
        raise AssertionError(
            f"QueueAcquire header {_header(machine)} != {expected}")
    if _words(machine, 1) != [CMD_DLSTART]:
        raise AssertionError("QueueAcquire did not emit CMD_DLSTART")
    return steps, clocks


def _acquire_fragment(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        page: int,
        sequence: int,
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueueAcquireFragment"],
        struct.pack("<HH", QUEUE_ADDRESS, sequence),
    )
    if result != 1:
        raise AssertionError(
            f"QueueAcquireFragment(#{page:02X}) returned {result}")
    expected = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, page, sequence, 0, 0, 0,
        QUEUE_BUILDING, 0, QUEUE_FRAGMENT, 0)
    if _header(machine) != expected:
        raise AssertionError(
            f"QueueAcquireFragment header {_header(machine)} != {expected}")
    return steps, clocks


def _test_release(machine: TSConfFT812Machine) -> None:
    """Stand in for the not-yet-connected resident consumer in this check."""
    if _header(machine).state != QUEUE_READY:
        raise AssertionError("test consumer may release only a READY queue")
    machine.cpu_write(QUEUE_STATE_ADDRESS, QUEUE_FREE)


def _push_dl(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        word: int,
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueuePushDL"],
        struct.pack("<HI", QUEUE_ADDRESS, word & 0xFFFFFFFF),
    )
    if result != 1:
        raise AssertionError(f"QueuePushDL(${word:08X}) returned {result}")
    return steps, clocks


def _push_template(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        template_index: int,
        base_x: int,
        base_y: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_QueuePushTemplate"],
        struct.pack("<HHhh", QUEUE_ADDRESS, template_index, base_x, base_y),
    )


def _find_hq_template(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        bank_key: int,
        descriptor_address: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_FindHQTemplate"],
        struct.pack("<HH", bank_key & 0xFFFF,
                    descriptor_address & 0xFFFF),
        result_width=16,
    )


def _resolve_bank_key(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        palette: int,
        resource_type: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_ResolveBankKey"],
        struct.pack("<HH", palette & 0xFFFF, resource_type & 0xFFFF),
        result_width=16,
    )


def _logical_vertex_c(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        value: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_LogicalVertex"],
        struct.pack("<h", value),
        result_width=16,
    )


def _lower_native(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        export: str,
        native: int,
        ) -> tuple[int, tuple[int, int, int], int, int]:
    sentinel = b"\xA5\x5A\xC3\x3C\x96"
    machine.mem.write_block_linear(LOWER_SCRATCH, sentinel)
    result, steps, clocks = _call_sdcc0(
        machine,
        support[export],
        struct.pack("<hH", native, LOWER_SCRATCH),
    )
    raw = machine.get_memory(LOWER_SCRATCH, LOWERED_COORD.size)
    if result == 0:
        if raw != sentinel:
            raise AssertionError(f"{export} changed output on failure")
        lowered = (0, 0, 0)
    else:
        lowered = LOWERED_COORD.unpack(raw)
    return result, lowered, steps, clocks


def _push_descriptor(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        palette: int,
        resource_type: int,
        descriptor_address: int,
        anchor_x: int,
        anchor_y: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_QueuePushDescriptor"],
        struct.pack(
            "<HHHHhh", QUEUE_ADDRESS, palette & 0xFFFF,
            resource_type & 0xFFFF,
            descriptor_address & 0xFFFF, anchor_x, anchor_y),
    )


def _push_descriptor_append(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        palette: int,
        resource_type: int,
        descriptor_address: int,
        anchor_x: int,
        anchor_y: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_QueuePushDescAppend"],
        struct.pack(
            "<HHHHhh", QUEUE_ADDRESS, palette & 0xFFFF,
            resource_type & 0xFFFF,
            descriptor_address & 0xFFFF, anchor_x, anchor_y),
    )


def _build_sprite_batch(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        records_address: int,
        count: int,
        remaining_dl_words: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_BuildSpriteBatch"],
        struct.pack(
            "<HHHH", QUEUE_ADDRESS, records_address,
            count, remaining_dl_words),
        max_steps=5_000_000,
        preserve_iy=True,
    )


def _build_sprite_batch_fast(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        records_address: int,
        count: int,
        remaining_dl_words: int,
        ) -> tuple[int, int, int]:
    return _call_sdcc0(
        machine,
        support["PyZ80FT_BuildSpriteBatchFast"],
        struct.pack(
            "<HHHH", QUEUE_ADDRESS, records_address,
            count, remaining_dl_words),
        max_steps=5_000_000,
        preserve_iy=True,
    )


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _normalize_append_body(words: list[int]) -> list[int]:
    """Resolve FT812 translation state back to direct VERTEX_FORMAT(3)."""
    translate_x = 0
    translate_y = 0
    direct: list[int] = []
    for word in words:
        opcode = (word >> 24) & 0x3F
        if opcode == 0x2B:
            translate_x = _sign_extend(word & 0x1FFFF, 17)
            continue
        if opcode == 0x2C:
            translate_y = _sign_extend(word & 0x1FFFF, 17)
            continue
        if word & 0x40000000:
            relative_x = _sign_extend((word >> 15) & 0x7FFF, 15)
            relative_y = _sign_extend(word & 0x7FFF, 15)
            effective_x16 = (relative_x << 1) + translate_x
            effective_y16 = (relative_y << 1) + translate_y
            if effective_x16 & 1 or effective_y16 & 1:
                raise AssertionError(
                    "CMD_APPEND translation cannot be represented by direct "
                    "VERTEX_FORMAT(3)")
            vertex_x = effective_x16 // 2
            vertex_y = effective_y16 // 2
            # VERTEX2F stores exactly the low 15 bits. Active Python applies
            # the same mask when an off-screen template cell extends beyond
            # the signed base-coordinate domain at a boundary anchor.
            direct.append(
                0x40000000 |
                ((vertex_x & 0x7FFF) << 15) |
                (vertex_y & 0x7FFF))
            continue
        direct.append(word)
    return direct


class _CaptureAtlas(python_enemies.M72SpriteAtlas):
    """Execute the active Python draw loop without loading pixel banks."""

    def __init__(self) -> None:
        pass

    def cell(self, palette: int, resource_type: int, code: int,
             flip_x: bool, flip_y: bool
             ) -> tuple[tuple[int, int], int, bool, bool]:
        bank_key, _path = self._asset(palette, resource_type)
        return (bank_key, code & 0x0FFF,
                bool(flip_x), bool(flip_y))


class _CaptureTarget:
    def __init__(self) -> None:
        self.blits: list[tuple[
            tuple[tuple[int, int], int, bool, bool], tuple[int, int]
        ]] = []

    def blit(self, image: tuple[tuple[int, int], int, bool, bool],
             position: tuple[int, int]) -> None:
        self.blits.append((image, position))


def _python_descriptor_words(
        rom: python_enemies.M72Rom,
        template: HQTemplate,
        states: list[HQBitmapState],
        cells: list[HQCell],
        palette: int,
        anchor_x: int,
        anchor_y: int,
        ) -> list[int]:
    """Run active M72SpriteAtlas.draw and lower its exact blits to FT words."""
    descriptor = python_enemies.read_descriptor(
        rom, template.descriptor_address)
    source_tuple = (
        descriptor.dx, descriptor.dy, descriptor.code,
        descriptor.width, descriptor.height,
        int(descriptor.flip_x) | (int(descriptor.flip_y) << 1),
    )
    template_tuple = (
        template.dx, template.dy, template.code,
        template.width, template.height, template.flags,
    )
    if source_tuple != template_tuple:
        raise AssertionError(
            f"HQT3 descriptor ${template.descriptor_address:04X} "
            f"{template_tuple} != active Python {source_tuple}")
    target = _CaptureTarget()
    _CaptureAtlas().draw(
        target, descriptor, palette, template.resource_type,
        anchor_x, anchor_y)
    template_cells = cells[
        template.cell_first:template.cell_first + template.cell_count]
    if len(target.blits) != len(template_cells):
        raise AssertionError("active Python draw changed descriptor cell count")
    result: list[int] = []
    current_layout: int | None = None
    current_palette: int | None = None
    for ordinal, ((image, (logical_x, logical_y)), cell) in enumerate(
            zip(target.blits, template_cells)):
        cell_x, cell_y = divmod(ordinal, template.height)
        source_x = (template.width - 1 - cell_x
                    if template.flags & 1 else cell_x)
        source_y = (template.height - 1 - cell_y
                    if template.flags & 2 else cell_y)
        expected_image = (
            (template.bank_key >> 8, template.bank_key & 0xFF),
            (template.code + 8 * source_x + source_y) & 0x0FFF,
            bool(template.flags & 1), bool(template.flags & 2),
        )
        if image != expected_image:
            raise AssertionError(
                f"active Python/HQT3 cell key differs at ordinal {ordinal}")
        state = states[cell.state_index]
        format_code = (state.layout >> 19) & 0x1F
        if state.layout != current_layout:
            result.append(state.layout)
            current_layout = state.layout
        if format_code == 15 and state.palette_ram_g != current_palette:
            result.append(DL_PALETTE_SOURCE | state.palette_ram_g)
            current_palette = state.palette_ram_g
        vertex_x = _logical_vertex(logical_x)
        vertex_y = _logical_vertex(logical_y)
        result.extend((
            DL_BITMAP_SOURCE | (cell.ram_g & 0x003FFFFF),
            0x40000000 |
            ((vertex_x & 0x7FFF) << 15) |
            (vertex_y & 0x7FFF),
        ))
    return result


def _commit(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueueCommit"],
        struct.pack("<H", QUEUE_ADDRESS),
    )
    if result != 1:
        raise AssertionError("QueueCommit failed")
    return steps, clocks


def _commit_fragment(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        ) -> tuple[int, int]:
    result, steps, clocks = _call_sdcc0(
        machine,
        support["PyZ80FT_QueueCommitFragment"],
        struct.pack("<H", QUEUE_ADDRESS),
    )
    if result != 1:
        raise AssertionError("QueueCommitFragment failed")
    return steps, clocks


def _reject_acquire_atomically(
        machine: TSConfFT812Machine,
        support: dict[str, int],
        sequence: int,
        state_name: str,
        fragment: bool = False,
        ) -> tuple[int, int]:
    before = machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES)
    result, steps, clocks = _call_sdcc0(
        machine,
        support[
            "PyZ80FT_QueueAcquireFragment"
            if fragment else "PyZ80FT_QueueAcquire"],
        struct.pack("<HH", QUEUE_ADDRESS, sequence),
    )
    if result != 0:
        raise AssertionError(
            f"QueueAcquire{'Fragment' if fragment else ''} accepted a "
            f"{state_name} queue")
    if machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES) != before:
        raise AssertionError(
            f"rejected QueueAcquire changed the {state_name} queue")
    return steps, clocks


def main() -> int:
    report_bindings = _report_source_bindings()
    translator_protocol_binding = _translator_protocol_binding()
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    support, code_page, ft_target = _load_support()
    linker_layout = _load_linker_layout()
    templates, states, cells, append_pack, sprite_pack = _load_templates()
    expected_hash_slots, resolver_hash = _expected_template_hash(templates)
    if (linker_layout["geometry_address"] -
            linker_layout["hash_address"] != len(expected_hash_slots) * 2):
        raise AssertionError(
            "compiled resolver hash size differs from deterministic table")
    python_rom = python_enemies.M72Rom()
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=50_000_000)

    # HQA3 is intentionally not connected to the live/ASM uploader yet. This
    # isolated ABI test validates the current zlib artifact and installs its
    # exact decompressed RAM_G image without rebuilding or deploying an SPG.
    machine.ft.ram_g[
        sprite_pack.ram_g_base:
        sprite_pack.ram_g_base + len(sprite_pack.inflated)] = \
        sprite_pack.inflated
    if bytes(machine.ft.ram_g[
            sprite_pack.ram_g_base:
            sprite_pack.ram_g_base + len(sprite_pack.data)]) != sprite_pack.data:
        raise AssertionError("hybrid FT812 pack upload differs")
    if bytes(machine.ft.ram_g[
            append_pack.ram_g_base:
            append_pack.ram_g_base + len(append_pack.data)]) != append_pack.data:
        raise AssertionError("hybrid upload did not install exact append pack")
    _verify_uploaded_pixels(
        machine, templates, states, cells, sprite_pack.decoded_by_key)

    machine.cpu_write(0x0412, code_page)
    compiled_binary = (ROOT / "Build" / "python_compiled_p00.bin").read_bytes()
    if len(compiled_binary) != 0x4000:
        raise AssertionError("compiled C bank is not one TS page")
    # This ABI check intentionally does not rebuild/deploy the SPG. Replace
    # only the mapped compiler page in simulator RAM with this translation.
    machine.mem.write_block_linear(0x8000, compiled_binary)
    compiled_hash = [
        struct.unpack("<H", machine.get_memory(
            int(linker_layout["hash_address"]) + index * 2, 2))[0]
        for index in range(len(expected_hash_slots))
    ]
    if compiled_hash != expected_hash_slots:
        raise AssertionError(
            "compiled resolver hash differs from deterministic HQT3 table")
    timing = FT812Timing(
        width=int(ft_target["width"]),
        height=int(ft_target["height"]),
        hcycle=int(ft_target["hcycle"]),
        pclk=int(ft_target["pclk"]),
        safety_utilization=float(ft_target["safety_utilization"]),
    )
    if timing.safe_line_cycles != int(ft_target["safe_line_cycles"]):
        raise AssertionError("FT812 timing differs from compiler manifest")
    if timing.safe_line_cycles != 1209:
        raise AssertionError(
            f"working FT812 line limit is {timing.safe_line_cycles}, not 1209")
    maximum_steps = 0
    maximum_clocks = 0
    tested_cells = 0
    descriptor_cells = 0
    append_cells = 0
    append_worst_cycles = 0
    append_call_max_steps = 0
    append_call_max_clocks = 0
    batch_call_max_steps = 0
    batch_call_max_clocks = 0
    batch_measurements: dict[int, tuple[int, int]] = {}
    fast_batch_call_max_steps = 0
    fast_batch_call_max_clocks = 0
    fast_batch_measurements: dict[int, tuple[int, int]] = {}
    fast_batch_failure_sources: list[str] = []
    fast_batch_differential_vectors = 0
    lookup_hit_max_steps = 0
    lookup_hit_max_clocks = 0
    lookup_miss_max_steps = 0
    lookup_miss_max_clocks = 0
    hash_fail_closed_vectors = 0
    hash_fault_max_steps = 0
    hash_fault_max_clocks = 0
    batch_differential_vectors = 0
    batch_failure_sources: list[str] = []

    # The host oracle proves the shift/add divide-by-5 identity over every
    # int16 input. The real SDCC export is then exhaustively called over the
    # renderer's declared direct-coordinate domain formerly covered by LUT.
    for logical in range(-0x8000, 0x8000):
        expected_vertex = round(Fraction(logical * 64, 5)) & 0xFFFF
        if _logical_vertex(logical) != expected_vertex:
            raise AssertionError(
                f"host logical vertex differs at {logical}")
    vertex_max_steps = 0
    vertex_max_clocks = 0
    for logical in range(
            LOGICAL_VERTEX_RANGE[0], LOGICAL_VERTEX_RANGE[1] + 1):
        actual_vertex, steps, clocks = _logical_vertex_c(
            machine, support, logical)
        vertex_max_steps = max(vertex_max_steps, steps)
        vertex_max_clocks = max(vertex_max_clocks, clocks)
        expected_vertex = round(Fraction(logical * 64, 5)) & 0xFFFF
        if actual_vertex != expected_vertex:
            raise AssertionError(
                f"compiled logical vertex {logical}=${actual_vertex:04X}, "
                f"Python=${expected_vertex:04X}")

    # Exhaustive fixed-point differential proof. Fraction keeps the oracle
    # independent of binary floating point; round(Fraction) is exact Python
    # ties-to-even, including every negative and half-way native coordinate.
    machine.cpu_write(0x0413, QUEUE_PAGES[0])
    lowering_vectors = 0
    lowering_ties = 0
    lowering_max_steps = 0
    lowering_max_clocks = 0
    for export, bounds, ratio in (
            ("PyZ80FT_LowerNativeX", NATIVE_X_RANGE, Fraction(5, 3)),
            ("PyZ80FT_LowerNativeY", NATIVE_Y_RANGE, Fraction(15, 8))):
        for native in range(bounds[0], bounds[1] + 1):
            result, lowered, steps, clocks = _lower_native(
                machine, support, export, native)
            lowering_max_steps = max(lowering_max_steps, steps)
            lowering_max_clocks = max(lowering_max_clocks, clocks)
            if result != 1:
                raise AssertionError(f"{export} rejected native {native}")
            logical = round(native * ratio)
            vertex = _sign_extend(_logical_vertex(logical), 16)
            expected = (logical, vertex, logical % 5)
            if lowered != expected:
                raise AssertionError(
                    f"{export}({native})={lowered}, Python={expected}")
            lowering_vectors += 1
            if export == "PyZ80FT_LowerNativeY" and (
                    (abs(native) * 15) & 7) == 4:
                lowering_ties += 1
        for native in (bounds[0] - 1, bounds[1] + 1):
            result, _lowered, steps, clocks = _lower_native(
                machine, support, export, native)
            lowering_max_steps = max(lowering_max_steps, steps)
            lowering_max_clocks = max(lowering_max_clocks, clocks)
            if result != 0:
                raise AssertionError(
                    f"{export} accepted out-of-range native {native}")

    # Prove the public C resolver directly against active Python for the full
    # palette/resource domain. Unlike the current typed-only HQT3 working set,
    # this necessarily exercises both typed files and real palette fallbacks.
    resolved_bank_keys: set[int] = set()
    for palette in range(0x10):
        for resource in range(0x100):
            active_bank, _path = python_enemies.M72SpriteAtlas._asset(
                palette, resource)
            expected_bank_key = (
                ((int(active_bank[0]) & 0xFF) << 8) |
                (int(active_bank[1]) & 0xFF))
            actual_bank_key, steps, clocks = _resolve_bank_key(
                machine, support, palette, resource)
            maximum_steps = max(maximum_steps, steps)
            maximum_clocks = max(maximum_clocks, clocks)
            if actual_bank_key != expected_bank_key:
                raise AssertionError(
                    f"ResolveBankKey({palette},{resource})="
                    f"${actual_bank_key:04X}, active Python="
                    f"${expected_bank_key:04X}")
            resolved_bank_keys.add(actual_bank_key)
    if not any(bank_key < 0x0100 for bank_key in resolved_bank_keys):
        raise AssertionError("ResolveBankKey proof did not exercise fallback")
    if not any(bank_key >= 0x0100 for bank_key in resolved_bank_keys):
        raise AssertionError("ResolveBankKey proof did not exercise typed banks")

    # Initialize both physical pages once. Acquisition is a strict FREE ->
    # BUILDING transition and publication is BUILDING -> READY; neither a
    # second producer nor a producer racing a published queue may alter it.
    ready_page_images: dict[int, bytes] = {}
    for page_index, queue_page in enumerate(QUEUE_PAGES):
        machine.cpu_write(0x0413, queue_page)
        if machine.mem.pages[2:] != [code_page, queue_page]:
            raise AssertionError(
                "could not map compiled C and isolated queue pages")
        steps, clocks = _initialize(machine, support, queue_page)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        sequence = 0x3000 + page_index
        steps, clocks = _acquire(
            machine, support, queue_page, sequence)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        steps, clocks = _reject_acquire_atomically(
            machine, support, sequence + 0x100, "BUILDING")
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        steps, clocks = _commit(machine, support)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        expected_ready = QueueHeader(
            QUEUE_MAGIC, QUEUE_FORMAT, queue_page, sequence,
            3, 12, 1, QUEUE_READY, 0, QUEUE_FULL, 0)
        if _header(machine) != expected_ready:
            raise AssertionError(
                f"QueueCommit publication {_header(machine)} != "
                f"{expected_ready}")
        if _words(machine, 3) != [CMD_DLSTART, DL_DISPLAY, CMD_SWAP]:
            raise AssertionError("QueueCommit published an incomplete stream")
        steps, clocks = _reject_acquire_atomically(
            machine, support, sequence + 0x200, "READY")
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        ready_page_images[queue_page] = machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES)

    for queue_page, expected_image in ready_page_images.items():
        machine.cpu_write(0x0413, queue_page)
        if machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES) != expected_image:
            raise AssertionError(
                f"queue page #{queue_page:02X} was not physically isolated")

    # Kind is part of the READY publication. A full-frame producer and a
    # fragment producer may never complete one another's BUILDING queue.
    fragment_page = QUEUE_PAGES[0]
    machine.cpu_write(0x0413, fragment_page)
    _test_release(machine)
    _initialize(machine, support, fragment_page)
    machine.cpu_write(QUEUE_ADDRESS + 14, 2)
    _reject_acquire_atomically(
        machine, support, 0x37FF, "invalid queue kind", fragment=True)
    _initialize(machine, support, fragment_page)
    _acquire(machine, support, fragment_page, 0x3800)
    _reject_acquire_atomically(
        machine, support, 0x3801, "full BUILDING", fragment=True)
    header_before = _header(machine)
    words_before = machine.get_memory(
        QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
    result, steps, clocks = _call_sdcc0(
        machine, support["PyZ80FT_QueueCommitFragment"],
        struct.pack("<H", QUEUE_ADDRESS))
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0:
        raise AssertionError("CommitFragment accepted a full-frame queue")
    if (_header(machine).kind != QUEUE_FULL or
            _header(machine).overflow != 1 or
            _header(machine).count != header_before.count or
            _header(machine).dl_words != header_before.dl_words or
            machine.get_memory(
                QUEUE_WORDS,
                QUEUE_BYTES - QUEUE_HEADER.size) != words_before):
        raise AssertionError("mixed fragment commit was not fail-closed")

    _initialize(machine, support, fragment_page)
    _acquire_fragment(machine, support, fragment_page, 0x3810)
    _reject_acquire_atomically(
        machine, support, 0x3811, "fragment BUILDING")
    _reject_acquire_atomically(
        machine, support, 0x3812, "fragment BUILDING", fragment=True)
    header_before = _header(machine)
    words_before = machine.get_memory(
        QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
    result, steps, clocks = _call_sdcc0(
        machine, support["PyZ80FT_QueueCommit"],
        struct.pack("<H", QUEUE_ADDRESS))
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0:
        raise AssertionError("full commit accepted a fragment queue")
    if (_header(machine).kind != QUEUE_FRAGMENT or
            _header(machine).overflow != 1 or
            _header(machine).count != header_before.count or
            _header(machine).dl_words != header_before.dl_words or
            machine.get_memory(
                QUEUE_WORDS,
                QUEUE_BYTES - QUEUE_HEADER.size) != words_before):
        raise AssertionError("mixed full commit was not fail-closed")

    # A real descriptor fragment contains exactly the two translation DL
    # words and one CMD_APPEND triple. CommitFragment only publishes those
    # five words; dl_words accounts the expanded immutable body as well.
    _initialize(machine, support, fragment_page)
    _acquire_fragment(machine, support, fragment_page, 0x3820)
    fragment_template = templates[0]
    fragment_palette = (fragment_template.bank_key & 0x0F
                        if fragment_template.bank_key < 0x0100 else 5)
    fragment_anchor_x = 320 - fragment_template.dx + 17
    fragment_anchor_y = (
        384 - fragment_template.dy - 16 * fragment_template.height - 11)
    result, steps, clocks = _push_descriptor_append(
        machine, support, fragment_palette, fragment_template.resource_type,
        fragment_template.descriptor_address,
        fragment_anchor_x, fragment_anchor_y)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 1:
        raise AssertionError("descriptor append failed in fragment mode")
    fragment_words = _words(machine, 5)
    if (len(fragment_words) != 5 or
            fragment_words[0] & 0x3F000000 != DL_VERTEX_TRANSLATE_X or
            fragment_words[1] & 0x3F000000 != DL_VERTEX_TRANSLATE_Y or
            fragment_words[2] != CMD_APPEND):
        raise AssertionError("fragment contains a full-frame prefix/suffix")
    fragment_appended_words = fragment_words[4] >> 2
    fragment_direct_words = _template_words(
        fragment_template, states, cells,
        round(Fraction(17 * 5, 3)), round(Fraction(11 * 15, 8)))
    if fragment_appended_words != len(fragment_direct_words):
        raise AssertionError("fragment CMD_APPEND expanded size is not exact")
    expected_fragment_dl = fragment_appended_words + 2
    expected_building = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, fragment_page, 0x3820,
        5, 0, expected_fragment_dl, QUEUE_BUILDING, 0,
        QUEUE_FRAGMENT, 0)
    if _header(machine) != expected_building:
        raise AssertionError("fragment append DL accounting differs")
    steps, clocks = _commit_fragment(machine, support)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    expected_fragment = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, fragment_page, 0x3820,
        5, 20, expected_fragment_dl, QUEUE_READY, 0,
        QUEUE_FRAGMENT, 0)
    if (_header(machine) != expected_fragment or
            _words(machine, 5) != fragment_words):
        raise AssertionError("fragment commit added or changed payload words")
    ready_fragment = machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES)
    result, steps, clocks = _call_sdcc0(
        machine, support["PyZ80FT_QueueCommitFragment"],
        struct.pack("<H", QUEUE_ADDRESS))
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0 or machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES) != ready_fragment:
        raise AssertionError("fragment re-commit changed a READY publication")

    # One packed batch call owns the complete fragment lifecycle. It consumes
    # literal active-Python bank keys, preserves record order, preflights the
    # caller's full-frame remaining DL budget, and publishes READY last.
    batch_indices = (0, len(templates) // 3, len(templates) // 2,
                     len(templates) - 1)
    batch_records: list[tuple[int, int, int, int]] = []
    batch_expected_direct: list[int] = []
    for ordinal, template_index in enumerate(batch_indices):
        template = templates[template_index]
        anchor_x = 90 + ordinal * 117
        anchor_y = 48 + ordinal * 83
        batch_records.append((
            template.bank_key, template.descriptor_address,
            anchor_x, anchor_y))
        palette = template.bank_key & 0x0F if template.bank_key < 0x0100 else 0
        batch_expected_direct.extend(_python_descriptor_words(
            python_rom, template, states, cells, palette,
            anchor_x, anchor_y))
    batch_record_data = b"".join(
        DRAW_RECORD.pack(*record) for record in batch_records)
    fast_batch_record_data = b"".join(
        FAST_DRAW_RECORD.pack(
            template_index, batch_records[ordinal][2],
            batch_records[ordinal][3])
        for ordinal, template_index in enumerate(batch_indices))

    def acquire_batch(sequence: int, address: int, data: bytes) -> None:
        _initialize(machine, support, fragment_page)
        _acquire_fragment(machine, support, fragment_page, sequence)
        machine.mem.write_block_linear(address, data)

    acquire_batch(0x3900, BATCH_RECORD_ADDRESS, batch_record_data)
    result, batch_steps, batch_clocks = _build_sprite_batch(
        machine, support, BATCH_RECORD_ADDRESS, len(batch_records), 2048)
    batch_call_max_steps = max(batch_call_max_steps, batch_steps)
    batch_call_max_clocks = max(batch_call_max_clocks, batch_clocks)
    batch_measurements[len(batch_records)] = (batch_steps, batch_clocks)
    maximum_steps = max(maximum_steps, batch_steps)
    maximum_clocks = max(maximum_clocks, batch_clocks)
    if result != 1:
        raise AssertionError("ordered sprite batch failed")
    batch_header = _header(machine)
    batch_words = _words(machine, batch_header.count)
    if (batch_header.state != QUEUE_READY or
            batch_header.kind != QUEUE_FRAGMENT or
            batch_header.count != 13 + 5 * len(batch_records) or
            batch_header.payload_bytes != batch_header.count * 4 or
            batch_words[:len(BATCH_PREFIX)] != list(BATCH_PREFIX) or
            batch_words[-3:] != [
                DL_VERTEX_TRANSLATE_X, DL_VERTEX_TRANSLATE_Y, DL_END]):
        raise AssertionError("sprite batch publication/prefix/suffix differs")
    batch_appended_words = sum(
        batch_words[10 + ordinal * 5 + 4] // 4
        for ordinal in range(len(batch_records)))
    expected_batch_dl = (
        13 + 2 * len(batch_records) + batch_appended_words)
    if batch_header.dl_words != expected_batch_dl:
        raise AssertionError("sprite batch expanded DL accounting differs")
    batch_payload = machine.get_memory(
        QUEUE_WORDS, batch_header.payload_bytes)
    # The strict validator must see the fragment in its real embedding: an
    # already opened frame, followed by the caller-owned DISPLAY/SWAP tail.
    framed_batch_payload = (
        struct.pack("<I", CMD_DLSTART) + batch_payload +
        struct.pack("<II", DL_DISPLAY, CMD_SWAP))
    batch_expansion = expand_coprocessor_stream(
        framed_batch_payload, ram_g=machine.ft.ram_g)
    batch_expanded_words = [
        word[0] for word in struct.iter_unpack(
            "<I", batch_expansion.display_list)]
    if batch_expanded_words[-1:] != [DL_DISPLAY]:
        raise AssertionError("synthetic full frame lost its DISPLAY tail")
    batch_normalized = _normalize_append_body(batch_expanded_words[:-1])
    if batch_normalized != (
            list(BATCH_PREFIX) + batch_expected_direct + [DL_END]):
        raise AssertionError(
            "sprite batch expansion/order differs from active Python")
    if len(batch_expanded_words) != expected_batch_dl + 1:
        raise AssertionError(
            "sprite fragment/full-frame tail DL accounting differs")

    acquire_batch(0x3980, BATCH_RECORD_ADDRESS, fast_batch_record_data)
    result, fast_batch_steps, fast_batch_clocks = _build_sprite_batch_fast(
        machine, support, BATCH_RECORD_ADDRESS, len(batch_records), 2048)
    fast_batch_call_max_steps = max(
        fast_batch_call_max_steps, fast_batch_steps)
    fast_batch_call_max_clocks = max(
        fast_batch_call_max_clocks, fast_batch_clocks)
    fast_batch_measurements[len(batch_records)] = (
        fast_batch_steps, fast_batch_clocks)
    if result != 1:
        raise AssertionError("ordered pre-resolved sprite batch failed")
    fast_batch_header = _header(machine)
    fast_batch_payload = machine.get_memory(
        QUEUE_WORDS, fast_batch_header.payload_bytes)
    if (fast_batch_header.count != batch_header.count or
            fast_batch_header.payload_bytes != batch_header.payload_bytes or
            fast_batch_header.dl_words != batch_header.dl_words or
            fast_batch_header.state != QUEUE_READY or
            fast_batch_payload != batch_payload):
        raise AssertionError(
            "pre-resolved batch is not byte-exact with literal oracle")

    # Exact remaining-budget acceptance and one-word-under atomic rejection.
    acquire_batch(0x3901, BATCH_RECORD_ADDRESS, batch_record_data)
    result, steps, clocks = _build_sprite_batch(
        machine, support, BATCH_RECORD_ADDRESS,
        len(batch_records), expected_batch_dl)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    if result != 1 or _header(machine).dl_words != expected_batch_dl:
        raise AssertionError("sprite batch rejected its exact remaining budget")

    def assert_batch_failure(
            reason: str, sequence: int, address: int, count: int, budget: int,
            data: bytes = b"",
            *, expect_cache_mutation: bool = False,
            ) -> None:
        nonlocal batch_call_max_steps, batch_call_max_clocks
        acquire_batch(sequence, address, data)
        before = bytearray(machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
        if before[13] != 0:
            raise AssertionError(f"{reason}: overflow was already sticky")
        cache_before = bytes([0xA5]) * BATCH_CACHE_BYTES
        if expect_cache_mutation:
            machine.mem.write_block_linear(BATCH_CACHE_ADDRESS, cache_before)
        result, failure_steps, failure_clocks = _build_sprite_batch(
            machine, support, address, count, budget)
        batch_call_max_steps = max(batch_call_max_steps, failure_steps)
        batch_call_max_clocks = max(batch_call_max_clocks, failure_clocks)
        if result != 0:
            raise AssertionError(f"{reason}: invalid sprite batch was accepted")
        before[13] = 1
        if machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES) != bytes(before):
            raise AssertionError(
                f"{reason}: failed sprite batch changed public queue/records")
        if _header(machine).overflow != 1:
            raise AssertionError(f"{reason}: sticky overflow is not exactly 1")
        if (expect_cache_mutation and machine.get_memory(
                BATCH_CACHE_ADDRESS, BATCH_CACHE_BYTES) == cache_before):
            raise AssertionError(
                f"{reason}: proof did not reach the private preflight cache")
        batch_failure_sources.append(reason)

    def assert_fast_batch_failure(
            reason: str, sequence: int, address: int, count: int, budget: int,
            data: bytes = b"",
            *, expect_cache_mutation: bool = False,
            ) -> None:
        nonlocal fast_batch_call_max_steps, fast_batch_call_max_clocks
        acquire_batch(sequence, address, data)
        before = bytearray(machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
        if before[13] != 0:
            raise AssertionError(
                f"fast {reason}: overflow was already sticky")
        cache_before = bytes([0x5A]) * BATCH_CACHE_BYTES
        if expect_cache_mutation:
            machine.mem.write_block_linear(BATCH_CACHE_ADDRESS, cache_before)
        result, failure_steps, failure_clocks = _build_sprite_batch_fast(
            machine, support, address, count, budget)
        fast_batch_call_max_steps = max(
            fast_batch_call_max_steps, failure_steps)
        fast_batch_call_max_clocks = max(
            fast_batch_call_max_clocks, failure_clocks)
        if result != 0:
            raise AssertionError(
                f"fast {reason}: invalid sprite batch was accepted")
        before[13] = 1
        if machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES) != bytes(before):
            raise AssertionError(
                f"fast {reason}: public queue/records changed on failure")
        if _header(machine).overflow != 1:
            raise AssertionError(
                f"fast {reason}: sticky overflow is not exactly 1")
        if (expect_cache_mutation and machine.get_memory(
                BATCH_CACHE_ADDRESS, BATCH_CACHE_BYTES) == cache_before):
            raise AssertionError(
                f"fast {reason}: did not reach private preflight cache")
        fast_batch_failure_sources.append(reason)

    assert_batch_failure(
        "budget-underflow", 0x3902,
        BATCH_RECORD_ADDRESS, len(batch_records),
        expected_batch_dl - 1, batch_record_data)
    acquire_batch(0x3981, BATCH_RECORD_ADDRESS, fast_batch_record_data)
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, BATCH_RECORD_ADDRESS,
        len(batch_records), expected_batch_dl)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    if result != 1 or _header(machine).dl_words != expected_batch_dl:
        raise AssertionError(
            "pre-resolved batch rejected its exact remaining budget")
    assert_fast_batch_failure(
        "budget-underflow", 0x3982,
        BATCH_RECORD_ADDRESS, len(batch_records),
        expected_batch_dl - 1, fast_batch_record_data)

    # count=0 still emits a complete empty sprite fragment. A 12-word budget
    # is the matching underflow rejection for its 13 DL words.
    acquire_batch(0x3903, 0xFFF8, b"")
    result, steps, clocks = _build_sprite_batch(
        machine, support, 0xFFF8, 0, 13)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    batch_measurements[0] = (steps, clocks)
    if (result != 1 or _header(machine).count != 13 or
            _header(machine).payload_bytes != 52 or
            _header(machine).dl_words != 13 or
            _words(machine, 13) != list(BATCH_PREFIX) + [
                DL_VERTEX_TRANSLATE_X, DL_VERTEX_TRANSLATE_Y, DL_END]):
        raise AssertionError("count=0 sprite batch is not exact")
    assert_batch_failure("empty-budget-underflow", 0x3904, 0xFFF8, 0, 12)
    acquire_batch(0x3983, 0xFFF8, b"")
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, 0xFFF8, 0, 13)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    fast_batch_measurements[0] = (steps, clocks)
    if (result != 1 or _header(machine).count != 13 or
            _words(machine, 13) != list(BATCH_PREFIX) + [
                DL_VERTEX_TRANSLATE_X, DL_VERTEX_TRANSLATE_Y, DL_END]):
        raise AssertionError("fast count=0 sprite batch is not exact")
    assert_fast_batch_failure(
        "empty-budget-underflow", 0x3984, 0xFFF8, 0, 12)

    # Repeated records prove literal order and the maximum 128-record ABI.
    smallest_index = min(
        range(len(templates)),
        key=lambda item: len(_template_words(
            templates[item], states, cells, 0, 0)))
    smallest = templates[smallest_index]
    zero_anchor_x = 320 - smallest.dx
    zero_anchor_y = 384 - smallest.dy - 16 * smallest.height
    repeated_record = (
        smallest.bank_key, smallest.descriptor_address,
        zero_anchor_x, zero_anchor_y)
    repeated_data = DRAW_RECORD.pack(*repeated_record) * BATCH_MAX_RECORDS
    fast_repeated_record = FAST_DRAW_RECORD.pack(
        smallest_index, zero_anchor_x, zero_anchor_y)
    fast_repeated_data = fast_repeated_record * BATCH_MAX_RECORDS
    smallest_direct = _python_descriptor_words(
        python_rom, smallest, states, cells,
        smallest.bank_key & 0x0F if smallest.bank_key < 0x0100 else 0,
        zero_anchor_x, zero_anchor_y)
    repeated_dl = 13 + BATCH_MAX_RECORDS * (2 + len(smallest_direct))
    if repeated_dl > 2048:
        raise AssertionError("128-record proof cannot fit RAM_DL")
    for measurement_index, measurement_count in enumerate((16, 32, 128)):
        measurement_dl = (
            13 + measurement_count * (2 + len(smallest_direct)))
        acquire_batch(
            0x3905 + measurement_index, 0xFC00,
            repeated_data[:measurement_count * DRAW_RECORD.size])
        result, steps, clocks = _build_sprite_batch(
            machine, support, 0xFC00, measurement_count, measurement_dl)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        batch_call_max_steps = max(batch_call_max_steps, steps)
        batch_call_max_clocks = max(batch_call_max_clocks, clocks)
        batch_measurements[measurement_count] = (steps, clocks)
        if (result != 1 or _header(machine).count !=
                13 + 5 * measurement_count or
                _header(machine).dl_words != measurement_dl):
            raise AssertionError(
                f"count={measurement_count}/FC00 sprite batch failed")
        acquire_batch(
            0x3990 + measurement_index, 0xFC00,
            fast_repeated_data[:
                measurement_count * FAST_DRAW_RECORD.size])
        result, fast_steps, fast_clocks = _build_sprite_batch_fast(
            machine, support, 0xFC00, measurement_count, measurement_dl)
        fast_batch_call_max_steps = max(
            fast_batch_call_max_steps, fast_steps)
        fast_batch_call_max_clocks = max(
            fast_batch_call_max_clocks, fast_clocks)
        fast_batch_measurements[measurement_count] = (
            fast_steps, fast_clocks)
        if (result != 1 or _header(machine).count !=
                13 + 5 * measurement_count or
                _header(machine).dl_words != measurement_dl):
            raise AssertionError(
                f"fast count={measurement_count}/FC00 batch failed")

    # At #CA44 the 128-record payload ends exactly where its source begins.
    equality_address = BATCH_RECORD_MIN
    if (QUEUE_WORDS + (13 + 5 * BATCH_MAX_RECORDS) * 4 !=
            equality_address):
        raise AssertionError("batch payload/record equality constant changed")
    acquire_batch(0x3910, equality_address, repeated_data)
    result, steps, clocks = _build_sprite_batch(
        machine, support, equality_address,
        BATCH_MAX_RECORDS, repeated_dl)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    if result != 1:
        raise AssertionError("payload/record boundary equality was rejected")
    acquire_batch(0x3993, equality_address, fast_repeated_data)
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, equality_address,
        BATCH_MAX_RECORDS, repeated_dl)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    if result != 1:
        raise AssertionError(
            "fast payload/record boundary equality was rejected")

    # #FFF8+one record exactly reaches the page end; +two must fail before
    # dereferencing/writing. A pointer two bytes below the reserved tail also
    # exercises the explicit payload-overlap/tail guard.
    one_record = DRAW_RECORD.pack(*repeated_record)
    acquire_batch(0x3907, 0xFFF8, one_record)
    result, steps, clocks = _build_sprite_batch(
        machine, support, 0xFFF8, 1, 2048)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    batch_measurements[1] = (steps, clocks)
    if result != 1:
        raise AssertionError("one record at #FFF8 was rejected")
    acquire_batch(0x3994, 0xFFF8, fast_repeated_record)
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, 0xFFF8, 1, 2048)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    fast_batch_measurements[1] = (steps, clocks)
    if result != 1:
        raise AssertionError("fast one record at #FFF8 was rejected")
    assert_batch_failure(
        "record-page-overflow", 0x3908, 0xFFF8, 2, 2048, one_record)
    assert_batch_failure(
        "payload-record-overlap", 0x3909, BATCH_RECORD_MIN - 2,
        BATCH_MAX_RECORDS, 2048)
    assert_fast_batch_failure(
        "record-page-overflow", 0x3995, 0xFFF8, 2, 2048,
        fast_repeated_record)
    assert_fast_batch_failure(
        "payload-record-overlap", 0x3996, BATCH_RECORD_MIN - 2,
        BATCH_MAX_RECORDS, 2048)

    # A miss or coordinate-range error in the middle of otherwise valid data
    # must leave the entire queue and source records byte-exact except for the
    # sticky overflow byte.
    invalid_descriptor = (
        repeated_record[1] + 1) & 0xFFFF
    while (smallest.bank_key, invalid_descriptor) in {
            (item.bank_key, item.descriptor_address) for item in templates}:
        invalid_descriptor = (invalid_descriptor + 1) & 0xFFFF
    invalid_records = (
        one_record + DRAW_RECORD.pack(
            smallest.bank_key, invalid_descriptor,
            zero_anchor_x, zero_anchor_y) + one_record)
    assert_batch_failure(
        "hash-miss-mid-preflight", 0x390A,
        BATCH_RECORD_ADDRESS, 3, 2048, invalid_records,
        expect_cache_mutation=True)
    range_records = (
        one_record + DRAW_RECORD.pack(
            smallest.bank_key, smallest.descriptor_address,
            320 - smallest.dx + NATIVE_X_RANGE[1] + 1,
            zero_anchor_y) + one_record)
    assert_batch_failure(
        "coordinate-range-mid-preflight", 0x390B,
        BATCH_RECORD_ADDRESS, 3, 2048, range_records,
        expect_cache_mutation=True)
    assert_batch_failure(
        "budget-above-RAM-DL", 0x390C,
        BATCH_RECORD_ADDRESS, 1, 2049, one_record)
    invalid_fast_records = (
        fast_repeated_record + FAST_DRAW_RECORD.pack(
            0xFFFF, zero_anchor_x, zero_anchor_y) +
        fast_repeated_record)
    assert_fast_batch_failure(
        "template-index-mid-preflight", 0x3997,
        BATCH_RECORD_ADDRESS, 3, 2048, invalid_fast_records,
        expect_cache_mutation=True)
    fast_range_records = (
        fast_repeated_record + FAST_DRAW_RECORD.pack(
            smallest_index,
            320 - smallest.dx + NATIVE_X_RANGE[1] + 1,
            zero_anchor_y) + fast_repeated_record)
    assert_fast_batch_failure(
        "coordinate-range-mid-preflight", 0x3998,
        BATCH_RECORD_ADDRESS, 3, 2048, fast_range_records,
        expect_cache_mutation=True)
    assert_fast_batch_failure(
        "budget-above-RAM-DL", 0x3999,
        BATCH_RECORD_ADDRESS, 1, 2049, fast_repeated_record)

    # The producer owns a fresh FRAGMENT only: FULL and an already populated
    # fragment are rejected without adopting or rewriting their payload.
    _initialize(machine, support, fragment_page)
    _acquire(machine, support, fragment_page, 0x390D)
    machine.mem.write_block_linear(BATCH_RECORD_ADDRESS, one_record)
    full_before = bytearray(machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
    result, steps, clocks = _build_sprite_batch(
        machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    full_before[13] = 1
    if result != 0 or machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES) != bytes(full_before):
        raise AssertionError("sprite batch accepted/changed a FULL queue")
    if _header(machine).overflow != 1:
        raise AssertionError("FULL queue failure lost exact sticky overflow")
    batch_failure_sources.append("FULL-kind")

    _initialize(machine, support, fragment_page)
    _acquire(machine, support, fragment_page, 0x399A)
    machine.mem.write_block_linear(
        BATCH_RECORD_ADDRESS, fast_repeated_record)
    fast_full_before = bytearray(
        machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    fast_full_before[13] = 1
    if result != 0 or machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES) != bytes(fast_full_before):
        raise AssertionError("fast sprite batch accepted/changed a FULL queue")
    fast_batch_failure_sources.append("FULL-kind")

    _initialize(machine, support, fragment_page)
    _acquire_fragment(machine, support, fragment_page, 0x390E)
    _push_dl(machine, support, DL_COLOR_WHITE)
    machine.mem.write_block_linear(BATCH_RECORD_ADDRESS, one_record)
    populated_before = bytearray(
        machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
    result, steps, clocks = _build_sprite_batch(
        machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
    batch_call_max_steps = max(batch_call_max_steps, steps)
    batch_call_max_clocks = max(batch_call_max_clocks, clocks)
    populated_before[13] = 1
    if result != 0 or machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES) != bytes(populated_before):
        raise AssertionError(
            "sprite batch accepted/changed a populated fragment")
    if _header(machine).overflow != 1:
        raise AssertionError(
            "populated-fragment failure lost exact sticky overflow")
    batch_failure_sources.append("nonempty-fragment")

    _initialize(machine, support, fragment_page)
    _acquire_fragment(machine, support, fragment_page, 0x399B)
    _push_dl(machine, support, DL_COLOR_WHITE)
    machine.mem.write_block_linear(
        BATCH_RECORD_ADDRESS, fast_repeated_record)
    fast_populated_before = bytearray(
        machine.get_memory(QUEUE_ADDRESS, QUEUE_BYTES))
    result, steps, clocks = _build_sprite_batch_fast(
        machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
    fast_batch_call_max_steps = max(fast_batch_call_max_steps, steps)
    fast_batch_call_max_clocks = max(fast_batch_call_max_clocks, clocks)
    fast_populated_before[13] = 1
    if result != 0 or machine.get_memory(
            QUEUE_ADDRESS, QUEUE_BYTES) != bytes(fast_populated_before):
        raise AssertionError(
            "fast batch accepted/changed a populated fragment")
    fast_batch_failure_sources.append("nonempty-fragment")

    # HQT3 is keyed by exact active-Python bank identity, never by the
    # transient resource argument alone.
    template_keys = {
        (item.bank_key, item.descriptor_address) for item in templates
    }
    for index, template in enumerate(templates):
        result, steps, clocks = _find_hq_template(
            machine, support, template.bank_key,
            template.descriptor_address)
        lookup_hit_max_steps = max(lookup_hit_max_steps, steps)
        lookup_hit_max_clocks = max(lookup_hit_max_clocks, clocks)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != index:
            raise AssertionError(
                f"FindHQTemplate({template.bank_key:04X},"
                f"{template.descriptor_address:04X}) returned {result}, "
                f"expected {index}")
    misses = [(0, 0), (0xFFFF, 0xFFFF)]
    candidate = (templates[0].bank_key,
                 (templates[0].descriptor_address + 1) & 0xFFFF)
    if candidate not in template_keys:
        misses.append(candidate)
    for bank_key, descriptor_address in misses:
        if (bank_key, descriptor_address) in template_keys:
            continue
        result, steps, clocks = _find_hq_template(
            machine, support, bank_key, descriptor_address)
        lookup_miss_max_steps = max(lookup_miss_max_steps, steps)
        lookup_miss_max_clocks = max(lookup_miss_max_clocks, clocks)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != 0xFFFF:
            raise AssertionError(
                "FindHQTemplate accepted an absent Python descriptor")

    # Deliberately replace one generated slot first with a different valid
    # template and then with an out-of-range stored index. Both represent a
    # collision/stale generated table; the complete bank+descriptor compare
    # must fail closed and must not touch public queue state.
    probe_template = templates[0]
    probe_slot = (
        probe_template.bank_key ^ (probe_template.bank_key >> 8) ^
        probe_template.descriptor_address ^
        (probe_template.descriptor_address >> 8)
    ) & (len(expected_hash_slots) - 1)
    hash_entry_address = int(
        linker_layout["hash_address"]) + probe_slot * 2
    saved_hash_entry = machine.get_memory(hash_entry_address, 2)
    public_before_hash_fault = machine.get_memory(
        QUEUE_ADDRESS, QUEUE_BYTES)
    try:
        for stale_stored in (2, 0xFFFF):
            if stale_stored == expected_hash_slots[probe_slot]:
                stale_stored = 3
            machine.mem.write_block_linear(
                hash_entry_address, struct.pack("<H", stale_stored))
            result, steps, clocks = _find_hq_template(
                machine, support, probe_template.bank_key,
                probe_template.descriptor_address)
            hash_fault_max_steps = max(hash_fault_max_steps, steps)
            hash_fault_max_clocks = max(hash_fault_max_clocks, clocks)
            maximum_steps = max(maximum_steps, steps)
            maximum_clocks = max(maximum_clocks, clocks)
            if result != 0xFFFF:
                raise AssertionError(
                    "stale/colliding resolver hash did not fail closed")
            if machine.get_memory(
                    QUEUE_ADDRESS, QUEUE_BYTES) != public_before_hash_fault:
                raise AssertionError(
                    "resolver hash fault changed public queue state")
            hash_fail_closed_vectors += 1
    finally:
        machine.mem.write_block_linear(hash_entry_address, saved_hash_entry)
    restored, _steps, _clocks = _find_hq_template(
        machine, support, probe_template.bank_key,
        probe_template.descriptor_address)
    if restored != 0:
        raise AssertionError("resolver hash did not recover after fault proof")

    # Differential proof for the naked preflight/emitter itself. Every HQT3
    # template is exercised at all 25 positive Python phases, all four public
    # coordinate-domain corners, and negative residual/tie vectors. The
    # physical CMD_APPEND fragment is expanded and normalized against a fresh
    # active-M72SpriteAtlas.draw oracle for every call.
    native_vectors = [
        (native_x, native_y)
        for native_x in range(5)
        for native_y in range(5)
    ]
    native_vectors.extend((
        (NATIVE_X_RANGE[0], NATIVE_Y_RANGE[0]),
        (NATIVE_X_RANGE[0], NATIVE_Y_RANGE[1]),
        (NATIVE_X_RANGE[1], NATIVE_Y_RANGE[0]),
        (NATIVE_X_RANGE[1], NATIVE_Y_RANGE[1]),
        (-1, -1), (-2, -2), (-3, -3), (-4, -4),
        (1, -4), (-4, 1),
    ))
    native_vectors = list(dict.fromkeys(native_vectors))
    batch_differential_max_steps = 0
    batch_differential_max_clocks = 0
    fast_batch_differential_max_steps = 0
    fast_batch_differential_max_clocks = 0
    differential_sequence = 0x6000
    for template_index, template in enumerate(templates):
        palette = (template.bank_key & 0x0F
                   if template.bank_key < 0x0100 else
                   (template_index * 7) & 0x0F)
        for native_x, native_y in native_vectors:
            anchor_x = native_x - template.dx + 320
            anchor_y = (
                384 - template.dy - template.height * 16 - native_y)
            if not (-0x8000 <= anchor_x <= 0x7FFF and
                    -0x8000 <= anchor_y <= 0x7FFF):
                raise AssertionError(
                    "generated geometry produced a non-int16 anchor")
            record = DRAW_RECORD.pack(
                template.bank_key, template.descriptor_address,
                anchor_x, anchor_y)
            acquire_batch(
                differential_sequence, BATCH_RECORD_ADDRESS, record)
            differential_sequence = (differential_sequence + 1) & 0xFFFF
            result, steps, clocks = _build_sprite_batch(
                machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
            batch_differential_max_steps = max(
                batch_differential_max_steps, steps)
            batch_differential_max_clocks = max(
                batch_differential_max_clocks, clocks)
            if result != 1:
                raise AssertionError(
                    "naked batch rejected a valid template/anchor vector: "
                    f"template={template_index}, native=({native_x},{native_y})")
            header = _header(machine)
            if (header.state != QUEUE_READY or header.count != 18 or
                    header.payload_bytes != 72):
                raise AssertionError(
                    "naked batch published an invalid one-record fragment")
            payload = machine.get_memory(QUEUE_WORDS, header.payload_bytes)
            expansion = expand_coprocessor_stream(
                struct.pack("<I", CMD_DLSTART) + payload +
                struct.pack("<II", DL_DISPLAY, CMD_SWAP),
                ram_g=machine.ft.ram_g)
            expanded = [
                word[0] for word in struct.iter_unpack(
                    "<I", expansion.display_list)
            ]
            expected_direct = _python_descriptor_words(
                python_rom, template, states, cells, palette,
                anchor_x, anchor_y)
            if (expanded[-1:] != [DL_DISPLAY] or
                    _normalize_append_body(expanded[:-1]) !=
                    list(BATCH_PREFIX) + expected_direct + [DL_END]):
                raise AssertionError(
                    "naked batch differs from active Python: "
                    f"template={template_index}, native=({native_x},{native_y})")
            batch_differential_vectors += 1
            fast_record = FAST_DRAW_RECORD.pack(
                template_index, anchor_x, anchor_y)
            acquire_batch(
                differential_sequence, BATCH_RECORD_ADDRESS, fast_record)
            differential_sequence = (differential_sequence + 1) & 0xFFFF
            fast_result, fast_steps, fast_clocks = _build_sprite_batch_fast(
                machine, support, BATCH_RECORD_ADDRESS, 1, 2048)
            fast_batch_differential_max_steps = max(
                fast_batch_differential_max_steps, fast_steps)
            fast_batch_differential_max_clocks = max(
                fast_batch_differential_max_clocks, fast_clocks)
            fast_header = _header(machine)
            if (fast_result != 1 or fast_header.count != header.count or
                    fast_header.payload_bytes != header.payload_bytes or
                    fast_header.dl_words != header.dl_words or
                    machine.get_memory(
                        QUEUE_WORDS, fast_header.payload_bytes) != payload):
                raise AssertionError(
                    "pre-resolved batch differs from literal/Python oracle: "
                    f"template={template_index}, native=({native_x},{native_y})")
            fast_batch_differential_vectors += 1

    queue_page = QUEUE_PAGES[0]
    machine.cpu_write(0x0413, queue_page)
    # The last atomic-failure vector intentionally leaves BUILDING+overflow;
    # restore the isolated test page before the legacy direct-path matrix.
    _initialize(machine, support, queue_page)
    for index, template in enumerate(templates):
        # Exercise negative coordinates as well as the full generated lookup
        # table without leaving VERTEX2F's signed 15-bit domain.
        base_x = -180 + index * 19
        base_y = -120 + ((index * 37) % 510)
        steps, clocks = _acquire(
            machine, support, queue_page, 0x4100 + index)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        result, steps, clocks = _push_template(
            machine, support, index, base_x, base_y)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != 1:
            raise AssertionError(f"QueuePushTemplate({index}) returned {result}")
        template_words = _template_words(
            template, states, cells, base_x, base_y)
        expected_words = [CMD_DLSTART] + template_words
        if _words(machine, len(expected_words)) != expected_words:
            raise AssertionError(
                f"compiled C words differ from HQT3 template {index}")
        expected_header = QueueHeader(
            QUEUE_MAGIC, QUEUE_FORMAT, queue_page, 0x4100 + index,
            len(expected_words), 0, len(template_words),
            QUEUE_BUILDING, 0, QUEUE_FULL, 0)
        if _header(machine) != expected_header:
            raise AssertionError(
                f"compiled C header differs for HQT3 template {index}")
        tested_cells += template.cell_count
        steps, clocks = _commit(machine, support)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        _test_release(machine)

    # Now enter through the public native-anchor API. Expected coordinates are
    # obtained by executing the active Python M72SpriteAtlas.draw itself, so a
    # changed dx/dy formula, loop order, scale, or round mode fails this check.
    for index, template in enumerate(templates):
        palette = ((template.bank_key & 0x0F)
                   if template.bank_key < 0x0100 else (index * 7) & 0x0F)
        resource_argument = template.resource_type | 0x0300
        active_bank, _path = python_enemies.M72SpriteAtlas._asset(
            palette, resource_argument)
        if active_bank != (template.bank_key >> 8, template.bank_key & 0xFF):
            raise AssertionError("HQT3 bank key differs from active Python _asset")
        anchor_x = 96 + ((index * 53) % 560)
        anchor_y = 32 + ((index * 41) % 416)
        steps, clocks = _acquire(
            machine, support, queue_page, 0x5100 + index)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        result, steps, clocks = _push_descriptor(
            machine, support, palette, resource_argument,
            template.descriptor_address, anchor_x, anchor_y)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != 1:
            raise AssertionError(
                f"QueuePushDescriptor({index}) returned {result}")
        python_words = _python_descriptor_words(
            python_rom, template, states, cells, palette, anchor_x, anchor_y)
        expected_words = [CMD_DLSTART] + python_words
        if _words(machine, len(expected_words)) != expected_words:
            raise AssertionError(
                f"compiled C descriptor coordinates differ from active "
                f"Python template {index}")
        expected_header = QueueHeader(
            QUEUE_MAGIC, QUEUE_FORMAT, queue_page, 0x5100 + index,
            len(expected_words), 0, len(python_words),
            QUEUE_BUILDING, 0, QUEUE_FULL, 0)
        if _header(machine) != expected_header:
            raise AssertionError(
                f"compiled C descriptor header differs for template {index}")
        descriptor_cells += template.cell_count
        steps, clocks = _commit(machine, support)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        _test_release(machine)

    # Exercise the isolated hardware-offload API for every descriptor. The
    # compiled C emits two translation words plus one phase-selected
    # CMD_APPEND. Expansion is normalized back to direct VERTEX_FORMAT(3) and
    # compared word-for-word with active Python M72SpriteAtlas.draw output.
    for index, template in enumerate(templates):
        palette = ((template.bank_key & 0x0F)
                   if template.bank_key < 0x0100 else (index * 11) & 0x0F)
        resource_argument = template.resource_type | 0x0500
        anchor_x = 80 + ((index * 47) % 600)
        anchor_y = 24 + ((index * 43) % 432)
        steps, clocks = _acquire(
            machine, support, queue_page, 0x5900 + index)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        for word in SPRITE_SETUP:
            steps, clocks = _push_dl(machine, support, word)
            maximum_steps = max(maximum_steps, steps)
            maximum_clocks = max(maximum_clocks, clocks)
        result, steps, clocks = _push_descriptor_append(
            machine, support, palette, resource_argument,
            template.descriptor_address, anchor_x, anchor_y)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        append_call_max_steps = max(append_call_max_steps, steps)
        append_call_max_clocks = max(append_call_max_clocks, clocks)
        if result != 1:
            raise AssertionError(
                f"QueuePushDescriptorAppend({index}) returned {result}")
        command_words = _words(machine, _header(machine).count)
        append_command = command_words[1 + len(SPRITE_SETUP):]
        if (len(append_command) != 5 or
                append_command[0] & 0x3F000000 != DL_VERTEX_TRANSLATE_X or
                append_command[1] & 0x3F000000 != DL_VERTEX_TRANSLATE_Y or
                append_command[2] != CMD_APPEND):
            raise AssertionError(
                f"compiled C append command shape differs for template {index}")
        append_address = append_command[3]
        append_size = append_command[4]
        if (append_address < append_pack.ram_g_base or
                append_address + append_size >
                append_pack.ram_g_base + len(append_pack.data) or
                append_size == 0 or append_size & 3):
            raise AssertionError(
                f"compiled C append range differs for template {index}")
        expected_building = QueueHeader(
            QUEUE_MAGIC, QUEUE_FORMAT, queue_page, 0x5900 + index,
            1 + len(SPRITE_SETUP) + 5, 0,
            len(SPRITE_SETUP) + 2 + append_size // 4,
            QUEUE_BUILDING, 0, QUEUE_FULL, 0)
        if _header(machine) != expected_building:
            raise AssertionError(
                f"CMD_APPEND accounting differs for template {index}")
        steps, clocks = _push_dl(machine, support, DL_END)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        steps, clocks = _commit(machine, support)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)

        header = _header(machine)
        payload = machine.get_memory(QUEUE_WORDS, header.payload_bytes)
        expansion = expand_coprocessor_stream(
            payload, ram_g=machine.ft.ram_g)
        if expansion.append_commands != 1:
            raise AssertionError("compiled append stream did not execute CMD_APPEND")
        expanded_words = [
            item[0] for item in struct.iter_unpack(
                "<I", expansion.display_list)
        ]
        if (expanded_words[:len(SPRITE_SETUP)] != list(SPRITE_SETUP) or
                expanded_words[-2:] != [DL_END, DL_DISPLAY]):
            raise AssertionError("CMD_APPEND expansion changed surrounding Z-order")
        normalized = _normalize_append_body(
            expanded_words[len(SPRITE_SETUP):-2])
        python_words = _python_descriptor_words(
            python_rom, template, states, cells, palette, anchor_x, anchor_y)
        if normalized != python_words:
            raise AssertionError(
                f"CMD_APPEND expansion differs from active Python direct words "
                f"for template {index}")
        budget = analyze_display_list(expansion.display_list, timing)
        if budget.worst_cycles > 1209 or not budget.passed:
            raise AssertionError(
                f"CMD_APPEND template {index} exceeds FT812 line budget: "
                f"{budget.worst_cycles}/1209")
        append_worst_cycles = max(append_worst_cycles, budget.worst_cycles)
        append_cells += template.cell_count
        _test_release(machine)

    if lowering_max_clocks > 2500:
        raise AssertionError(
            f"fixed coordinate lowering regressed to "
            f"{lowering_max_clocks} t-states")
    if append_call_max_clocks > 20000:
        raise AssertionError(
            f"descriptor CMD_APPEND lowering regressed to "
            f"{append_call_max_clocks} t-states")

    # Explicit half-way vectors distinguish Python's ties-to-even from the
    # usual add-half/truncate implementation: +/-7.5 -> +/-8, while
    # +/-22.5 -> +/-22.
    tie_template = templates[0]
    tie_palette = (tie_template.bank_key & 0x0F
                   if tie_template.bank_key < 0x0100 else 13)
    for tie_index, native_y in enumerate((4, 12, -4, -12)):
        anchor_x = 320 - tie_template.dx
        anchor_y = (384 - tie_template.dy -
                    16 * tie_template.height - native_y)
        _acquire(machine, support, queue_page, 0x6100 + tie_index)
        result, steps, clocks = _push_descriptor(
            machine, support, tie_palette, tie_template.resource_type,
            tie_template.descriptor_address, anchor_x, anchor_y)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != 1:
            raise AssertionError("ties-to-even descriptor push failed")
        expected_words = [CMD_DLSTART] + _python_descriptor_words(
            python_rom, tie_template, states, cells, tie_palette,
            anchor_x, anchor_y)
        if _words(machine, len(expected_words)) != expected_words:
            raise AssertionError(
                f"Python ties-to-even differs for native_y={native_y}")
        _commit(machine, support)
        _test_release(machine)

    # An absent translated descriptor must only latch overflow; it must not
    # partially alter the already built command stream.
    machine.cpu_write(0x0413, QUEUE_PAGES[1])
    _test_release(machine)
    _acquire(machine, support, QUEUE_PAGES[1], 0xBEEF)
    words_before = machine.get_memory(
        QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
    header_before = _header(machine)
    missing_template = templates[0]
    missing_descriptor = (missing_template.descriptor_address + 1) & 0xFFFF
    while (missing_template.bank_key, missing_descriptor) in template_keys:
        missing_descriptor = (missing_descriptor + 1) & 0xFFFF
    missing_palette = (missing_template.bank_key & 0x0F
                       if missing_template.bank_key < 0x0100 else 9)
    result, steps, clocks = _push_descriptor(
        machine, support, missing_palette, missing_template.resource_type,
        missing_descriptor, 123, 234)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0:
        raise AssertionError("absent Python descriptor was accepted")
    expected_failed = QueueHeader(
        header_before.magic, header_before.format, header_before.page,
        header_before.frame_sequence, header_before.count,
        header_before.payload_bytes, header_before.dl_words,
        header_before.state, 1, header_before.kind, header_before.reserved)
    if _header(machine) != expected_failed:
        raise AssertionError(
            "absent descriptor changed queue state beyond overflow")
    if machine.get_memory(
            QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size) != words_before:
        raise AssertionError("absent descriptor partially wrote queue words")

    # Select a resource for which active Python _asset actually chooses a
    # palette fallback. The generated C availability bitset must make the same
    # decision and fail closed because this typed-only bootstrap has no HQT3
    # record for that fallback bank.
    fallback_resource = next(
        resource for resource in range(0x100)
        if python_enemies.M72SpriteAtlas._asset(0, resource)[0][0] == 0)
    fallback_palette = next(
        palette for palette in range(0x10)
        if (palette, templates[0].descriptor_address) not in template_keys)
    _initialize(machine, support, QUEUE_PAGES[1])
    _acquire(machine, support, QUEUE_PAGES[1], 0xBEF0)
    words_before = machine.get_memory(
        QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
    header_before = _header(machine)
    result, steps, clocks = _push_descriptor_append(
        machine, support, fallback_palette, fallback_resource | 0x0700,
        templates[0].descriptor_address, 123, 234)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0:
        raise AssertionError("fallback bank incorrectly aliased a typed HQT3 key")
    if (_header(machine).count != header_before.count or
            _header(machine).dl_words != header_before.dl_words or
            _header(machine).overflow != 1 or
            machine.get_memory(
                QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size) != words_before):
        raise AssertionError("fallback HQT3 miss was not atomic")

    # The public descriptor path must propagate the coordinate-domain guard
    # atomically, rather than wrapping a signed FT812 translation field.
    range_template = templates[0]
    range_palette = (range_template.bank_key & 0x0F
                     if range_template.bank_key < 0x0100 else 7)
    for range_index, (native_x, native_y) in enumerate((
            (NATIVE_X_RANGE[1] + 1, 0),
            (0, NATIVE_Y_RANGE[0] - 1))):
        _initialize(machine, support, QUEUE_PAGES[1])
        _acquire(machine, support, QUEUE_PAGES[1], 0xBEF1 + range_index)
        words_before = machine.get_memory(
            QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
        header_before = _header(machine)
        anchor_x = native_x - range_template.dx + 320
        anchor_y = (384 - range_template.dy -
                    16 * range_template.height - native_y)
        result, steps, clocks = _push_descriptor_append(
            machine, support, range_palette, range_template.resource_type,
            range_template.descriptor_address, anchor_x, anchor_y)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
        if result != 0:
            raise AssertionError("out-of-range descriptor append was accepted")
        if (_header(machine).count != header_before.count or
                _header(machine).dl_words != header_before.dl_words or
                _header(machine).overflow != 1 or
                machine.get_memory(
                    QUEUE_WORDS,
                    QUEUE_BYTES - QUEUE_HEADER.size) != words_before):
            raise AssertionError(
                "out-of-range descriptor append was not atomic")

    # Force the append producer against its queue-capacity preflight. A valid
    # descriptor must fail before writing either translation or CMD_APPEND;
    # only the sticky overflow bit may change.
    _initialize(machine, support, QUEUE_PAGES[1])
    _acquire(machine, support, QUEUE_PAGES[1], 0xBF00)
    forced_count = (QUEUE_BYTES - QUEUE_HEADER.size) // 4 - 6
    machine.cpu_write(QUEUE_ADDRESS + 6, forced_count & 0xFF)
    machine.cpu_write(QUEUE_ADDRESS + 7, forced_count >> 8)
    header_before = _header(machine)
    words_before = machine.get_memory(
        QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size)
    result, steps, clocks = _push_descriptor_append(
        machine, support,
        (templates[0].bank_key & 0x0F
         if templates[0].bank_key < 0x0100 else 3),
        templates[0].resource_type,
        templates[0].descriptor_address, 320, 192)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 0:
        raise AssertionError("CMD_APPEND accepted a queue without commit reserve")
    header_after = _header(machine)
    if (header_after.count != header_before.count or
            header_after.dl_words != header_before.dl_words or
            header_after.state != header_before.state or
            header_after.overflow != 1):
        raise AssertionError("failed CMD_APPEND partially changed queue header")
    if machine.get_memory(
            QUEUE_WORDS, QUEUE_BYTES - QUEUE_HEADER.size) != words_before:
        raise AssertionError("failed CMD_APPEND partially wrote queue words")

    # Build one complete stream using the largest translated template.
    template_index = max(
        range(len(templates)), key=lambda item: templates[item].cell_count)
    template = templates[template_index]
    base_x, base_y = 160, 120
    machine.cpu_write(0x0413, queue_page)
    _acquire(machine, support, queue_page, 0xCAFE)
    setup = list(SPRITE_SETUP)
    for word in setup:
        steps, clocks = _push_dl(machine, support, word)
        maximum_steps = max(maximum_steps, steps)
        maximum_clocks = max(maximum_clocks, clocks)
    result, steps, clocks = _push_template(
        machine, support, template_index, base_x, base_y)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    if result != 1:
        raise AssertionError("complete-stream template append failed")
    steps, clocks = _push_dl(machine, support, DL_END)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)
    steps, clocks = _commit(machine, support)
    maximum_steps = max(maximum_steps, steps)
    maximum_clocks = max(maximum_clocks, clocks)

    final_template_words = _template_words(
        template, states, cells, base_x, base_y)
    expected_stream = (
        [CMD_DLSTART] + setup + final_template_words +
        [DL_END, DL_DISPLAY, CMD_SWAP]
    )
    payload = b"".join(struct.pack("<I", word) for word in expected_stream)
    expected_header = QueueHeader(
        QUEUE_MAGIC, QUEUE_FORMAT, queue_page, 0xCAFE,
        len(expected_stream), len(payload),
        len(setup) + len(final_template_words) + 2,
        QUEUE_READY, 0, QUEUE_FULL, 0)
    if _header(machine) != expected_header:
        raise AssertionError(f"QueueCommit header {_header(machine)} != {expected_header}")
    legacy_full_header = struct.pack(
        "<HBBHHHHBBH", QUEUE_MAGIC, QUEUE_FORMAT, queue_page, 0xCAFE,
        len(expected_stream), len(payload),
        len(setup) + len(final_template_words) + 2,
        QUEUE_READY, 0, 0)
    if machine.get_memory(QUEUE_ADDRESS, QUEUE_HEADER.size) != (
            legacy_full_header):
        raise AssertionError("full-frame queue header is no longer byte-exact")
    if machine.get_memory(QUEUE_WORDS, len(payload)) != payload:
        raise AssertionError("QueueCommit payload differs from expected FT812 words")

    expansion = expand_coprocessor_stream(payload)
    expected_display_list = b"".join(
        struct.pack("<I", word) for word in
        setup + final_template_words +
        [DL_END, DL_DISPLAY])
    if expansion.display_list != expected_display_list:
        raise AssertionError("coprocessor expansion changed the compiled C Z-order")

    budget = analyze_display_list(expansion.display_list, timing)
    if budget.worst_cycles > 1209 or not budget.passed:
        raise AssertionError(
            f"FT812 working line budget exceeded: {budget.worst_cycles}/1209")

    # Leave the C page before invoking the resident backend, exactly as the
    # eventual queue consumer must do. The DMA reads page #ED physically.
    machine.cpu_write(0x0412, 0x06)
    machine.ft.ram_cmd[:] = bytes(len(machine.ft.ram_cmd))
    machine.ft.ram_dl[:] = bytes(len(machine.ft.ram_dl))
    machine.ft.cmd_read_ptr = 0
    machine.ft.cmd_write_ptr = 0
    error_count = len(machine.errors)
    before_sp = machine.reg.SP
    machine.call(
        symbols["RTypeFT_CmdWritePageDMA"],
        a=queue_page,
        b=(len(payload) >> 8) & 0xFF,
        c=len(payload) & 0xFF,
        h=(QUEUE_WORDS >> 8) & 0xFF,
        l=QUEUE_WORDS & 0xFF,
        max_steps=5_000_000,
    )
    if machine.reg.F & 0x01:
        raise AssertionError("resident FT812 command DMA returned carry")
    if machine.reg.SP != before_sp:
        raise AssertionError("resident FT812 command DMA changed Z80 SP")
    if machine.mem.pages[2:] != [0x06, queue_page]:
        raise AssertionError("resident FT812 command DMA changed MMU pages")
    if len(machine.errors) != error_count:
        raise AssertionError(
            f"resident FT812 command DMA simulator errors: "
            f"{machine.errors[error_count:]}")
    if bytes(machine.ft.ram_cmd[:len(payload)]) != payload:
        raise AssertionError("DMA did not copy the exact queue into RAM_CMD")
    if bytes(machine.ft.ram_dl[:len(expansion.display_list)]) != (
            expansion.display_list):
        raise AssertionError("FT812 RAM_DL differs from the committed C queue")

    if set(batch_measurements) != {0, 1, 4, 16, 32, 128}:
        raise AssertionError("batch performance matrix is incomplete")
    if set(fast_batch_measurements) != {0, 1, 4, 16, 32, 128}:
        raise AssertionError(
            "pre-resolved batch performance matrix is incomplete")
    required_failure_sources = {
        "budget-underflow", "empty-budget-underflow",
        "record-page-overflow", "payload-record-overlap",
        "hash-miss-mid-preflight", "coordinate-range-mid-preflight",
        "budget-above-RAM-DL", "FULL-kind", "nonempty-fragment",
    }
    if set(batch_failure_sources) != required_failure_sources:
        raise AssertionError(
            "batch atomic-failure source matrix is incomplete")
    required_fast_failure_sources = {
        "budget-underflow", "empty-budget-underflow",
        "record-page-overflow", "payload-record-overlap",
        "template-index-mid-preflight", "coordinate-range-mid-preflight",
        "budget-above-RAM-DL", "FULL-kind", "nonempty-fragment",
    }
    if set(fast_batch_failure_sources) != required_fast_failure_sources:
        raise AssertionError(
            "pre-resolved batch atomic-failure matrix is incomplete")
    if batch_differential_vectors != len(templates) * len(native_vectors):
        raise AssertionError("naked batch differential matrix is incomplete")
    if fast_batch_differential_vectors != batch_differential_vectors:
        raise AssertionError(
            "pre-resolved/literal differential matrix is incomplete")
    frame_tstates = ZCLK_HZ // TARGET_FRAME_HZ
    stream_chunk_tstates = batch_measurements[STREAM_CHUNK_PERF_RECORDS][1]
    fast_stream_chunk_tstates = fast_batch_measurements[
        STREAM_CHUNK_PERF_RECORDS][1]
    if fast_stream_chunk_tstates >= stream_chunk_tstates:
        raise AssertionError(
            "pre-resolved ABI did not reduce the measured chunk cost")
    if (stream_chunk_tstates >= frame_tstates or
            batch_measurements[BATCH_MAX_RECORDS][1] <= frame_tstates):
        raise AssertionError(
            "chunk performance benchmark no longer distinguishes 32 from 128")
    compiler_report = json.loads((
        ROOT / "Build" / "rtype_python_compiler.json").read_text(
            encoding="utf-8"))
    compiled_binary = (ROOT / "Build" / "python_compiled_p00.bin").read_bytes()
    if (_report_source_bindings() != report_bindings or
            _translator_protocol_binding() != translator_protocol_binding):
        raise AssertionError(
            "focused simulator inputs changed while the proof was running")
    performance_report = {
        "format": "rtype-python-hq-queue-sim-v1",
        "bindings": {
            "algorithm": "sha256",
            "path_base": "project-root",
            "files": report_bindings,
            "contracts": {
                "translator_ft812_queue_abi_ast_sha256": (
                    translator_protocol_binding),
            },
            "stable_during_run": True,
        },
        "compiled_page": code_page,
        "compiled_binary_sha256": hashlib.sha256(
            compiled_binary).hexdigest(),
        "compiled_binary_size": len(compiled_binary),
        "logical_vertex": {
            "formula": "m=5q+r; 64q+{0,13,26,38,51}",
            "host_i16_vectors": 65536,
            "compiled_c_range": list(LOGICAL_VERTEX_RANGE),
            "compiled_c_vectors": (
                LOGICAL_VERTEX_RANGE[1] - LOGICAL_VERTEX_RANGE[0] + 1),
            "max_steps": vertex_max_steps,
            "max_tstates": vertex_max_clocks,
            "runtime_helpers": [],
        },
        "batch": {
            "record_format": "<bank_key:u16,descriptor:u16,x:i16,y:i16>",
            "record_size": DRAW_RECORD.size,
            "record_vma_first": BATCH_RECORD_MIN,
            "record_vma_common": BATCH_RECORD_ADDRESS,
            "record_vma_last_one": 0xFFF8,
            "max_records": BATCH_MAX_RECORDS,
            "stream_chunk_performance_records": STREAM_CHUNK_PERF_RECORDS,
            "two_pass_atomic": True,
            "pass_two_uses_private_cache_only": True,
            "remaining_dl_budget_is_full_frame": True,
            "measurements": {
                str(count): {
                    "steps": batch_measurements[count][0],
                    "tstates": batch_measurements[count][1],
                    "baseline_tstates": BATCH_BASELINE_TSTATES[count],
                    "tstates_saved": (
                        BATCH_BASELINE_TSTATES[count] -
                        batch_measurements[count][1]),
                    "reduction_percent": round(
                        100.0 * (
                            BATCH_BASELINE_TSTATES[count] -
                            batch_measurements[count][1]) /
                        BATCH_BASELINE_TSTATES[count], 3),
                    "milliseconds_at_zclk14": round(
                        batch_measurements[count][1] / 14000.0, 6),
                }
                for count in sorted(batch_measurements)
            },
            "proofs": [
                "active-Python order and normalized CMD_APPEND expansion",
                "count 0/1/4/16/32/128",
                "FC00 and FFF8 page-end bounds",
                "CA44 payload-record boundary equality",
                "budget exact and one-word underflow",
                "descriptor miss and coordinate-range failure",
                "FULL and populated FRAGMENT rejection",
                "IX/IY/SP and MMU restored on every batch return",
                "private cache may change, public header/words/records exact",
                "all HQT3 templates at boundary/phase anchors vs Python",
            ],
            "failure_sources": batch_failure_sources,
            "differential": {
                "oracle": "active M72SpriteAtlas.draw -> exact FT812 words",
                "templates": len(templates),
                "native_vectors_per_template": len(native_vectors),
                "vectors": batch_differential_vectors,
                "max_steps": batch_differential_max_steps,
                "max_tstates": batch_differential_max_clocks,
                "includes": [
                    "25 x/y positive phase pairs",
                    "four native coordinate-domain corners",
                    "negative residual and ties-to-even vectors",
                ],
            },
            "chunk_performance": {
                "zclk_hz": ZCLK_HZ,
                "target_frame_hz": TARGET_FRAME_HZ,
                "frame_tstates_floor": frame_tstates,
                "stream_chunk_records": STREAM_CHUNK_PERF_RECORDS,
                "measured_batch_tstates": stream_chunk_tstates,
                "measured_batch_milliseconds": round(
                    stream_chunk_tstates / 14000.0, 6),
                "batch_frame_utilization": round(
                    stream_chunk_tstates / frame_tstates, 6),
                "remaining_frame_tstates": frame_tstates-stream_chunk_tstates,
                "whole_frame_record_limit": None,
                "interpretation": (
                    "one chunk timing measurement, not a whole-frame "
                    "record-count certificate"),
                "status": "benchmark-only-pending-full-frame-certificate",
            },
            "live_hook": "forbidden-pending-full-frame-budget-and-integration",
        },
        "pre_resolved_batch": {
            "record_format": "<template_index:u16,x:i16,y:i16>",
            "record_size": FAST_DRAW_RECORD.size,
            "template_identity": "immutable generated HQT3 table index",
            "literal_oracle_export": "PyZ80FT_BuildSpriteBatch",
            "fast_export": "PyZ80FT_BuildSpriteBatchFast",
            "shared_naked_core": True,
            "two_pass_atomic": True,
            "pass_two_uses_private_cache_only": True,
            "remaining_dl_budget_is_full_frame": True,
            "measurements": {
                str(count): {
                    "steps": fast_batch_measurements[count][0],
                    "tstates": fast_batch_measurements[count][1],
                    "literal_tstates": batch_measurements[count][1],
                    "tstates_saved_vs_literal": (
                        batch_measurements[count][1] -
                        fast_batch_measurements[count][1]),
                    "reduction_vs_literal_percent": round(
                        100.0 * (
                            batch_measurements[count][1] -
                            fast_batch_measurements[count][1]) /
                        batch_measurements[count][1], 3),
                    "milliseconds_at_zclk14": round(
                        fast_batch_measurements[count][1] / 14000.0, 6),
                }
                for count in sorted(fast_batch_measurements)
            },
            "failure_sources": fast_batch_failure_sources,
            "differential": {
                "oracle": (
                    "literal bank+descriptor naked ABI and active Python"),
                "templates": len(templates),
                "native_vectors_per_template": len(native_vectors),
                "vectors": fast_batch_differential_vectors,
                "max_steps": fast_batch_differential_max_steps,
                "max_tstates": fast_batch_differential_max_clocks,
                "payload_byte_exact": True,
            },
            "chunk_performance": {
                "stream_chunk_records": STREAM_CHUNK_PERF_RECORDS,
                "literal_tstates": stream_chunk_tstates,
                "fast_tstates": fast_stream_chunk_tstates,
                "tstates_saved": (
                    stream_chunk_tstates - fast_stream_chunk_tstates),
                "reduction_percent": round(
                    100.0 * (
                        stream_chunk_tstates - fast_stream_chunk_tstates) /
                    stream_chunk_tstates, 3),
                "fast_milliseconds_at_zclk14": round(
                    fast_stream_chunk_tstates / 14000.0, 6),
                "status": "isolated-exact-benchmark-no-live-hook",
            },
            "proofs": [
                "template index range checked before cache publication",
                "exact negative and ties-to-even coordinate lowering",
                "budget/range/overlap/FULL/nonempty fail-before-publication",
                "IX/IY/SP and MMU restored on every return",
                "ordered physical payload byte-exact with literal ABI",
            ],
        },
        "template_lookup": {
            "algorithm": "generated bounded hash plus full key compare",
            "generator": resolver_hash,
            "compiled_table_address": linker_layout["hash_address"],
            "hit_vectors": len(templates),
            "miss_vectors": len(misses),
            "fail_closed_collision_stale_vectors": hash_fail_closed_vectors,
            "fail_closed_fault_max_steps": hash_fault_max_steps,
            "fail_closed_fault_max_tstates": hash_fault_max_clocks,
            "hit_max_steps": lookup_hit_max_steps,
            "hit_max_tstates": lookup_hit_max_clocks,
            "miss_max_steps": lookup_miss_max_steps,
            "miss_max_tstates": lookup_miss_max_clocks,
        },
        "bank_resolver": {
            "domain": "16 palettes x 256 resource types",
            "vectors": 4096,
            "exact": True,
            "oracle": "active Python M72SpriteAtlas._asset",
        },
        "linker_layout": linker_layout,
        "optimization": {
            "baseline_code_bytes": BATCH_BASELINE_CODE_BYTES,
            "optimized_code_bytes": linker_layout["code"]["size"],
            "code_bytes_delta": (
                linker_layout["code"]["size"] - BATCH_BASELINE_CODE_BYTES),
            "baseline": "pre-hash/pre-cache compiled C batch",
            "hot_path": "generated-table-driven naked Z80",
            "division_modulo_helpers": [],
        },
        "ft812": {
            "safe_line_cycles": timing.safe_line_cycles,
            "observed_append_worst_cycles": append_worst_cycles,
            "ram_dl_word_limit": int(
                compiler_report["target"]["ft812"]["ram_dl_word_limit"]),
        },
    }
    performance_path = ROOT / "Build" / "rtype_python_hq_queue_sim.json"
    temporary_path = performance_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(performance_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    temporary_path.replace(performance_path)

    append_speedup = GENERIC_APPEND_BASELINE_TSTATES / append_call_max_clocks
    append_reduction = 100.0 * (
        GENERIC_APPEND_BASELINE_TSTATES - append_call_max_clocks
    ) / GENERIC_APPEND_BASELINE_TSTATES
    print(
        f"Compiled C HQ queue: {len(templates)} HQT3 templates/"
        f"{tested_cells} direct + {descriptor_cells} Python descriptor cells "
        f"+ {append_cells} CMD_APPEND cells exact; "
        f"{append_pack.blob_count} blobs/{len(append_pack.data)} bytes uploaded; "
        f"fragment 0->5 words/{expected_fragment_dl} expanded DL exact; "
        f"append atomic, FT line <= {append_worst_cycles}/1209; "
        f"fixed lowering {lowering_vectors} exact/{lowering_ties} ties <= "
        f"{lowering_max_steps} steps/{lowering_max_clocks} t-states; "
        f"vertex /5 host 65536 + compiled "
        f"{LOGICAL_VERTEX_RANGE[1] - LOGICAL_VERTEX_RANGE[0] + 1} exact <= "
        f"{vertex_max_steps} steps/{vertex_max_clocks} t-states, no helper; "
        f"descriptor append <= {append_call_max_steps} steps/"
        f"{append_call_max_clocks} t-states "
        f"({append_speedup:.2f}x, {append_reduction:.1f}% lower); "
        f"batch 0/1/4/16/32/128 + FC00/FFF8/equality exact/atomic: 4 records "
        f"{batch_steps} steps/{batch_clocks} t-states, max128 <= "
        f"{batch_call_max_steps} steps/{batch_call_max_clocks} t-states; "
        f"naked/Python differential {batch_differential_vectors} vectors; "
        f"fast batch32 {fast_stream_chunk_tstates} vs "
        f"{stream_chunk_tstates} t-states, differential "
        f"{fast_batch_differential_vectors} vectors; "
        f"lookup hit/miss <= {lookup_hit_max_clocks}/"
        f"{lookup_miss_max_clocks} t-states; "
        f"ED/EE lifecycle atomic; resolver 4096/4096 exact; "
        f"absent descriptor atomic; "
        f"commit {len(expected_stream)} words -> RAM_DL {budget.word_count} "
        f"words; FT line {budget.worst_line}="
        f"{budget.worst_cycles}/1209; SDCC call <= {maximum_steps} steps/"
        f"{maximum_clocks} t-states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
