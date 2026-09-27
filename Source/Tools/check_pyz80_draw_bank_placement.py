#!/usr/bin/env python3
"""Fail-closed linked placement certificate for the split C draw bundle.

The unsplit certificate measures the active source-derived bundle but cannot
fit it into one 16 KiB slot2 page.  This checker performs two real SDCC links:

* physical page #F1: render order, persistent state, VM, chunker and the local
  HQT lookup needed by every emitted record;
* physical page #F2: the exact FT812 batch-builder dependency slice and all
  immutable HQT data it consumes.

The only cross-bank edge is one chunk submission.  A page-F1 naked proxy
tail-jumps to a resident page-00 gate, which maps #F2 and tail-jumps to a
link-proved #8000 entry.  The gate is assembled and measured here, but this
tool never claims live integration: production final-link, packer and callback
evidence are mandatory and are deliberately absent at this stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from check_pyz80_draw_target_bundle import (
    DrawTargetBundleError,
    PINNED_ARGUMENTS,
    _area_map,
    _atomic_json,
    _extract_c_array,
    _json_bytes,
    _linked_files,
    _run,
    _sdnm_symbols,
    build_dependency_slices,
    probe as probe_unsplit_bundle,
)
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.memory import MemoryLayout
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-bank-placement-certificate-v1"
STATUS = "LINKED_BANK_PLACEMENT_PROVED_FINAL_BINDING_BLOCKED"
PLACEMENT_FORMAT = "pyz80-draw-bank-placement-v1"
PAGE_BYTES = 0x4000
CODE_START = 0x8000
CODE_END = 0xC000
DATA_START = 0x0B00
DATA_END = 0x1000
GATE_START = 0x07A0

PLACEMENT_INPUTS = (
    "Source/Tools/rtype_python_draw_bank_placement.json",
    "Source/Tools/rtype_memory_layout.json",
    "Source/Tools/rtype_python_compiler.json",
    "Source/Tools/check_pyz80_draw_bank_placement.py",
    "Source/Tools/check_pyz80_draw_target_bundle.py",
    "Source/ASM/pyz80_draw_bank_gate.asm",
    "Source/ASM/pyz80_ft812_fragment_bridge.asm",
    "Source/ASM/main.asm",
    "Source/C/ft812/pyz80_draw_bank0_proxy.c",
    "Source/C/ft812/pyz80_draw_bank1_entry.c",
    "Source/C/ft812/pyz80_draw_fast_chunker.c",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Docs/TSLib/Include/Memory/Functions.inc",
    "Build/pyz80_ft812_fragment_bridge.bin",
    "Build/coordinate_tables.bin",
    "Build/resident_tables.bin",
    "Build/python_compiled_p00.bin",
    "Build/rtype.sym",
    "Build/rtype_python_draw_target_bundle_status.json",
    "spgbld_rtype.ini",
    "build.cmd",
)


class DrawBankPlacementError(DrawTargetBundleError):
    """A placement, link, source binding or resident ABI fact changed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrawBankPlacementError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DrawBankPlacementError(f"JSON root is not an object: {path}")
    return value


def _file_record(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DrawBankPlacementError(f"missing placement input {relative}") from exc
    return {"path": relative, "bytes": len(data), "sha256": _sha256(data)}


def _integer_define(text: str, name: str) -> int:
    matches = re.findall(
        rf"(?m)^\s*#define\s+{re.escape(name)}\s+"
        r"(0x[0-9A-Fa-f]+|[0-9]+)[uUlL]*\s*$",
        text,
    )
    if len(matches) != 1:
        raise DrawBankPlacementError(
            f"expected one integer define {name}, found {len(matches)}")
    return int(matches[0], 0)


def _asm_equ(text: str, name: str) -> int:
    matches = re.findall(
        rf"(?mi)^\s*{re.escape(name)}\s+EQU\s+(#[0-9A-F]+|[0-9]+)\s*$",
        text,
    )
    if len(matches) != 1:
        raise DrawBankPlacementError(
            f"expected one ASM EQU {name}, found {len(matches)}")
    return int(matches[0].replace("#", "0x"), 0)


def _sym_values(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for match in re.finditer(
            r"(?m)^([^:\r\n]+):\s+EQU\s+0x([0-9A-Fa-f]+)\s*$", text):
        result[match.group(1)] = int(match.group(2), 16)
    return result


def _noi_definitions(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for match in re.finditer(
            r"(?m)^DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)\s*$", text):
        symbol = match.group(1)
        address = int(match.group(2), 16)
        if symbol in result and result[symbol] != address:
            raise DrawBankPlacementError(f"NOI repeats symbol {symbol}")
        result[symbol] = address
    return result


def validate_intervals(
        intervals: Iterable[tuple[str, int, int]], limit: int = PAGE_BYTES,
        ) -> tuple[dict[str, object], ...]:
    """Validate deterministic half-open intervals and return sorted records."""
    rows = sorted((str(name), int(start), int(end))
                  for name, start, end in intervals)
    for name, start, end in rows:
        if not 0 <= start < end <= limit:
            raise DrawBankPlacementError(
                f"interval {name} outside page: 0x{start:04X}..0x{end:04X}")
    by_start = sorted(rows, key=lambda row: (row[1], row[2], row[0]))
    for left, right in zip(by_start, by_start[1:]):
        if left[2] > right[1]:
            raise DrawBankPlacementError(
                f"resident overlap: {left[0]} and {right[0]}")
    return tuple({
        "name": name,
        "start_hex": f"0x{start:04X}",
        "end_exclusive_hex": f"0x{end:04X}",
        "bytes": end - start,
    } for name, start, end in by_start)


def _extract_lookup_slices(root: Path) -> dict[str, object]:
    ft_path = root / "Source/C/ft812/pyz80_ft812.c"
    hq_path = root / "Source/C/generated/rtype_python_hq_templates.c"
    ft_text = ft_path.read_text(encoding="utf-8")
    hq_text = hq_path.read_text(encoding="utf-8")
    begin_token = "uint16_t PyZ80FT_FindHQTemplate("
    end_token = "uint16_t PyZ80FT_ResolveBankKey("
    start = ft_text.find(begin_token)
    end = ft_text.find(end_token)
    if start < 0 or end <= start:
        raise DrawBankPlacementError("FT812 HQT lookup source markers changed")
    ft_fragment = ft_text[start:end].rstrip() + "\n"
    ft_source = (
        '#include "pyz80_ft812.h"\n'
        '#include "rtype_python_hq_templates.h"\n\n' + ft_fragment)
    hq_symbols = ("PyZ80FT_HQTemplates", "PyZ80FT_HQTemplateHash")
    spans = [_extract_c_array(hq_text, symbol) for symbol in hq_symbols]
    if spans != sorted(spans, key=lambda row: row[0]):
        raise DrawBankPlacementError("HQT lookup arrays changed order")
    hq_source = (
        '#include "rtype_python_hq_templates.h"\n\n' +
        "\n".join(row[2].rstrip() for row in spans) + "\n")
    return {
        "ft_source": ft_source,
        "hq_source": hq_source,
        "report": {
            "algorithm": "exact-active-source-spans-v1",
            "ft812_lookup": {
                "source_path": "Source/C/ft812/pyz80_ft812.c",
                "start_byte": len(ft_text[:start].encode("utf-8")),
                "end_byte_exclusive": len(ft_text[:end].encode("utf-8")),
                "source_sha256": _sha256(ft_path.read_bytes()),
                "slice_sha256": _sha256(ft_source.encode("utf-8")),
            },
            "hqt_lookup": {
                "source_path": "Source/C/generated/rtype_python_hq_templates.c",
                "source_sha256": _sha256(hq_path.read_bytes()),
                "symbols": list(hq_symbols),
                "slice_sha256": _sha256(hq_source.encode("utf-8")),
                "spans": [{
                    "symbol": symbol,
                    "start_byte": len(hq_text[:row[0]].encode("utf-8")),
                    "end_byte_exclusive": len(hq_text[:row[1]].encode("utf-8")),
                    "sha256": _sha256(row[2].encode("utf-8")),
                } for symbol, row in zip(hq_symbols, spans)],
            },
        },
    }


def _compiler_environment(sdcc: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    return environment


def _validate_naked_tail_assembly(
        text: str, label: str, target: str, role: str,
        ) -> None:
    if len(re.findall(rf"(?m)^\s*{re.escape(label)}::?\s*$", text)) != 1:
        raise DrawBankPlacementError(f"{role} compiled label changed")
    jumps = re.findall(r"(?mi)^\s*jp\s+([^;\r\n]+?)\s*$", text)
    calls = re.findall(r"(?mi)^\s*call\s+([^;\r\n]+?)\s*$", text)
    if jumps != [target] or calls:
        raise DrawBankPlacementError(
            f"{role} is not one naked tail JP: jumps={jumps}, calls={calls}")


def _validate_gate_source(text: str) -> None:
    """Prove the checked gate still implements the declared tail-return ABI."""
    required_in_order = (
        "RTypePyDrawBank_CallF2C0:",
        "CALL Memory.GetPage2",
        "CP   RTYPE_PYDRAW_BANK0_PAGE",
        "CALL Memory.SetPage2",
        "LD   DE, RTypePyDrawBank_ReturnGate",
        "JP   RTYPE_PYDRAW_BANK1_ENTRY",
        "RTypePyDrawBank_ReturnGate:",
        "LD   (RTypePyDrawBankResultHL), HL",
        "LD   (RTypePyDrawBankResultDE), DE",
        "LD   A, (RTypePyDrawBankSavedPage2)",
        "CALL Memory.SetPage2",
        "LD   SP, (RTypePyDrawBankSavedSP)",
        "LD   IX, (RTypePyDrawBankSavedIX)",
        "LD   IY, (RTypePyDrawBankSavedIY)",
        "RET",
    )
    cursor = 0
    for token in required_in_order:
        found = text.find(token, cursor)
        if found < 0:
            raise DrawBankPlacementError(
                f"resident tail-gate ABI token missing/reordered: {token}")
        cursor = found + len(token)
    if re.search(r"(?mi)^\s*CALL\s+RTYPE_PYDRAW_BANK1_ENTRY\b", text):
        raise DrawBankPlacementError("resident gate added a stack-shifting CALL")


def _copy_compile_inputs(root: Path, directory: Path) -> None:
    paths = (
        "Source/C/generated/rtype_python_render_order.c",
        "Source/C/generated/rtype_python_render_order.h",
        "Source/C/generated/rtype_python_draw_state.c",
        "Source/C/generated/rtype_python_draw_state.h",
        "Source/C/generated/rtype_python_draw_vm.c",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/ft812/pyz80_draw_fast_chunker.c",
        "Source/C/ft812/pyz80_draw_fast_chunker.h",
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/ft812/pyz80_draw_bank0_proxy.c",
        "Source/C/ft812/pyz80_draw_bank1_entry.c",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    for relative in paths:
        source = root / relative
        (directory / source.name).write_bytes(source.read_bytes())


def _object_symbol_report(
        sdcc: Path, directory: Path, rels: tuple[str, ...],
        environment: Mapping[str, str],
        ) -> tuple[dict[str, object], set[str], set[str]]:
    sdnm = sdcc.parent / "sdnm.exe"
    if not sdnm.is_file():
        raise DrawBankPlacementError("pinned SDCC has no sdnm.exe")
    owners: dict[str, list[str]] = defaultdict(list)
    all_defined: set[str] = set()
    all_undefined: set[str] = set()
    report: dict[str, object] = {}
    for rel in rels:
        output = _run([str(sdnm), rel], directory, environment).stdout
        defined, undefined = _sdnm_symbols(output)
        for symbol in defined:
            owners[symbol].append(rel)
        all_defined.update(defined)
        all_undefined.update(undefined)
        raw = (directory / rel).read_bytes()
        report[rel] = {
            "bytes": len(raw),
            "sha256": _sha256(raw),
            "defined": sorted(defined),
            "undefined": sorted(undefined),
        }
    duplicates = {
        symbol: modules for symbol, modules in sorted(owners.items())
        if len(modules) > 1 and symbol != ".__.ABS."
    }
    if duplicates:
        raise DrawBankPlacementError(f"duplicate bank symbols: {duplicates}")
    return report, all_defined, all_undefined


def _compile_bank(
        root: Path, sdcc: Path, name: str,
        sources: tuple[str, ...], generated: Mapping[str, str],
        expected_direct: tuple[str, ...], expected_runtime: tuple[str, ...],
        ) -> dict[str, object]:
    environment = _compiler_environment(sdcc)
    with tempfile.TemporaryDirectory(prefix=f"pyz80-draw-{name}-") as temp:
        directory = Path(temp)
        _copy_compile_inputs(root, directory)
        for filename, text in generated.items():
            (directory / filename).write_text(
                text, encoding="utf-8", newline="\n")
        compile_logs: dict[str, str] = {}
        for source in sources:
            completed = _run(
                [str(sdcc), *PINNED_ARGUMENTS, "-c", source],
                directory, environment)
            compile_logs[source] = completed.stdout
        if "pyz80_draw_bank0_proxy.c" in sources:
            _validate_naked_tail_assembly(
                (directory / "pyz80_draw_bank0_proxy.asm").read_text(
                    encoding="latin1"),
                "_PyZ80FT_BuildSpriteBatchFast", "0x07A0",
                "page-F1 proxy")
        if "pyz80_draw_bank1_entry.c" in sources:
            _validate_naked_tail_assembly(
                (directory / "pyz80_draw_bank1_entry.asm").read_text(
                    encoding="latin1"),
                "_PyZ80DrawBank1_BuildSpriteBatchFast",
                "_PyZ80FT_BuildSpriteBatchFast", "page-F2 entry")
        rels = tuple(Path(source).with_suffix(".rel").name for source in sources)
        link_args = (
            "-mz80", "--no-std-crt0",
            "--code-loc", f"0x{CODE_START:04X}",
            "--data-loc", f"0x{DATA_START:04X}", "-Wl-m",
        )
        link = _run(
            [str(sdcc), *link_args, *rels, "-o", f"{name}.ihx"],
            directory, environment)
        map_bytes = (directory / f"{name}.map").read_bytes()
        map_text = map_bytes.decode("latin1")
        noi_bytes = (directory / f"{name}.noi").read_bytes()
        noi = _noi_definitions(noi_bytes.decode("latin1"))
        ihx_bytes = (directory / f"{name}.ihx").read_bytes()
        areas = _area_map(map_text)
        if "_CODE" not in areas:
            raise DrawBankPlacementError(f"{name} link lacks _CODE")
        code_origin, code_bytes = areas["_CODE"]
        data_origin, data_bytes = areas.get("_DATA", (DATA_START, 0))
        direct, runtime = _linked_files(map_text)
        if tuple(direct) != expected_direct:
            raise DrawBankPlacementError(
                f"{name} direct object inventory changed: {direct}")
        if tuple(sorted(runtime)) != tuple(sorted(expected_runtime)):
            raise DrawBankPlacementError(
                f"{name} runtime object inventory changed: {runtime}")
        objects, defined, undefined = _object_symbol_report(
            sdcc, directory, rels, environment)
        runtime_defs = {"___sdcc_call_iy", "___memcpy", "_memcpy"}
        unresolved = sorted(undefined - defined - runtime_defs)
        if unresolved:
            raise DrawBankPlacementError(
                f"{name} has unresolved direct references: {unresolved}")
        if code_origin != CODE_START or code_origin + code_bytes > CODE_END:
            raise DrawBankPlacementError(
                f"{name} CODE does not fit slot2: "
                f"0x{code_origin:04X}..0x{code_origin + code_bytes:04X}")
        if data_bytes and not (
                data_origin == DATA_START and data_origin + data_bytes <= DATA_END):
            raise DrawBankPlacementError(
                f"{name} DATA outside resident cache: "
                f"0x{data_origin:04X}..0x{data_origin + data_bytes:04X}")
        return {
            "link_arguments": list(link_args),
            "source_order": list(sources),
            "direct_objects": direct,
            "runtime_objects": runtime,
            "objects": objects,
            "code": {
                "origin_hex": f"0x{code_origin:04X}",
                "end_exclusive_hex": f"0x{code_origin + code_bytes:04X}",
                "bytes": code_bytes,
                "headroom_bytes": PAGE_BYTES - code_bytes,
                "fits_one_bank": code_bytes <= PAGE_BYTES,
            },
            "data": {
                "origin_hex": f"0x{data_origin:04X}",
                "end_exclusive_hex": f"0x{data_origin + data_bytes:04X}",
                "bytes": data_bytes,
            },
            "public_symbols": {
                symbol: f"0x{address:04X}"
                for symbol, address in sorted(noi.items())
                if symbol.startswith("_") and not symbol.startswith("l__")
                and not symbol.startswith("s__")
            },
            "map": {"bytes": len(map_bytes), "sha256": _sha256(map_bytes)},
            "noi": {"bytes": len(noi_bytes), "sha256": _sha256(noi_bytes)},
            "ihx": {"bytes": len(ihx_bytes), "sha256": _sha256(ihx_bytes)},
            "link_stdout_sha256": _sha256(link.stdout.encode("utf-8")),
            "compile_log_sha256": {
                source: _sha256(log.encode("utf-8"))
                for source, log in sorted(compile_logs.items())
            },
        }


def _locate_sjasmplus(root: Path) -> Path:
    environment_value = os.environ.get("SJASMPLUS", "").strip('" ')
    candidates: list[Path] = []
    if environment_value:
        candidates.append(Path(environment_value))
    candidates.append(
        root.parent / "z80" / "tsconf_project" / "exe" /
        "sjasmplus" / "sjasmplus.exe")
    build_text = (root / "build.cmd").read_text(
        encoding="utf-8", errors="replace")
    match = re.search(
        r"(?mi)^if\s+\"%SJASMPLUS%\"==\"\"\s+set\s+SJASMPLUS=(.+?)\s*$",
        build_text)
    if match:
        candidates.append(Path(match.group(1).strip('" ')))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise DrawBankPlacementError("project sjasmplus executable not found")


def _assemble_gate(
        root: Path, assembler: Path, gate_start: int, gate_end_limit: int,
        services: Mapping[str, int],
        ) -> dict[str, object]:
    if set(services) != {"Memory.GetPage2", "Memory.SetPage2"}:
        raise DrawBankPlacementError("gate service binding set changed")
    source_path = (root / "Source/ASM/pyz80_draw_bank_gate.asm").resolve()
    with tempfile.TemporaryDirectory(prefix="pyz80-draw-bank-gate-") as temp:
        directory = Path(temp)
        # Keep the include at the requested ORG and measure the exact emitted
        # bytes.  The source itself exports start/end labels for these asserts.
        wrapper = (
            "                DEVICE ZXSPECTRUM128\n"
            f"Memory.GetPage2 EQU #{services['Memory.GetPage2']:04X}\n"
            f"Memory.SetPage2 EQU #{services['Memory.SetPage2']:04X}\n"
            f"                ORG #{gate_start:04X}\n"
            f'                include "{source_path.as_posix()}"\n'
            f"                ASSERT RTypePyDrawBankGate_Start = #{gate_start:04X}\n"
            f"                ASSERT RTypePyDrawBankGate_End <= #{gate_end_limit:04X}\n"
            "                SAVEBIN \"gate.bin\", RTypePyDrawBankGate_Start, "
            "RTypePyDrawBankGate_End - RTypePyDrawBankGate_Start\n"
        )
        (directory / "gate_wrapper.asm").write_text(
            wrapper, encoding="utf-8", newline="\n")
        completed = _run(
            [str(assembler), "--nologo", "gate_wrapper.asm"],
            directory, os.environ.copy())
        binary = (directory / "gate.bin").read_bytes()
        if gate_start + len(binary) > gate_end_limit:
            raise DrawBankPlacementError("assembled resident gate exceeds window")
        return {
            "assembler_path": assembler.as_posix(),
            "assembler_sha256": _sha256(assembler.read_bytes()),
            "source_path": "Source/ASM/pyz80_draw_bank_gate.asm",
            "source_sha256": _sha256(source_path.read_bytes()),
            "origin_hex": f"0x{gate_start:04X}",
            "end_exclusive_hex": f"0x{gate_start + len(binary):04X}",
            "bytes": len(binary),
            "headroom_bytes": gate_end_limit - gate_start - len(binary),
            "binary_sha256": _sha256(binary),
        }


def _spg_blocks(text: str) -> tuple[dict[str, object], ...]:
    rows = []
    for match in re.finditer(
            r"(?mi)^\s*Block\s*=\s*#([0-9A-F]+)\s*,\s*"
            r"#([0-9A-F]+)\s*,\s*(\S.*?)\s*$", text):
        rows.append({
            "offset": int(match.group(1), 16),
            "page": int(match.group(2), 16),
            "path": match.group(3).replace("\\", "/"),
        })
    return tuple(rows)


def _contract_dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DrawBankPlacementError(f"placement {field} must be an object")
    return value


def probe(project_root: Path | str) -> dict[str, object]:
    root = Path(project_root).resolve()
    contract_path = root / "Source/Tools/rtype_python_draw_bank_placement.json"
    contract = _read_json(contract_path)
    if contract.get("format") != PLACEMENT_FORMAT:
        raise DrawBankPlacementError("unsupported draw-bank placement format")

    compiler_path = root / "Source/Tools/rtype_python_compiler.json"
    compiler_manifest = CompilerManifest.load(compiler_path)
    memory_path = root / "Source/Tools/rtype_memory_layout.json"
    memory = MemoryLayout.load(memory_path)
    memory_report = memory.validate()
    compiler_region = memory.region("compiler-code")
    queue_region = memory.region("ft812-render-queues")
    template_region = memory.region("ft812-command-templates")

    code_banks_raw = contract.get("code_banks")
    if not isinstance(code_banks_raw, list) or len(code_banks_raw) != 2:
        raise DrawBankPlacementError("placement needs exactly two code banks")
    code_banks = tuple(int(value) for value in code_banks_raw)
    compiler_pages = set(compiler_region.pages())
    if code_banks != (0xF1, 0xF2) or any(
            page not in compiler_pages or
            page not in compiler_manifest.target.code_pages
            for page in code_banks):
        raise DrawBankPlacementError("draw banks are not free compiler-code pages F1/F2")
    code_vma = _contract_dict(contract.get("code_vma"), "code_vma")
    if (int(code_vma.get("start", -1)), int(code_vma.get("end", -1))) != (
            CODE_START, CODE_END):
        raise DrawBankPlacementError("draw code VMA is not slot2 0x8000..0xBFFF")

    ft_contract = _contract_dict(contract.get("ft812"), "ft812")
    header_text = (root / "Source/C/ft812/pyz80_ft812.h").read_text(
        encoding="utf-8")
    queue_pages = (
        _integer_define(header_text, "PYZ80_FT_QUEUE_PAGE_A"),
        _integer_define(header_text, "PYZ80_FT_QUEUE_PAGE_B"),
    )
    queue_vma = _integer_define(header_text, "PYZ80_FT_QUEUE_VMA")
    queue_bytes = _integer_define(header_text, "PYZ80_FT_QUEUE_BYTES")
    record_vma = _integer_define(header_text, "PYZ80_FT_BATCH_RECORD_VMA")
    record_bytes = _integer_define(header_text, "PYZ80_FT_BATCH_RECORD_BYTES")
    template_page = _integer_define(header_text, "PYZ80_FT_TEMPLATE_PAGE")
    if queue_pages != tuple(int(value) for value in ft_contract["queue_pages"]):
        raise DrawBankPlacementError("queue page contract is stale")
    if queue_pages != tuple(queue_region.pages()):
        raise DrawBankPlacementError("queue pages disagree with memory layout")
    if template_page not in set(template_region.pages()) or template_page != int(
            ft_contract["command_template_page"]):
        raise DrawBankPlacementError("command-template page contract is stale")
    if (queue_vma, queue_vma + queue_bytes) != (
            int(_contract_dict(ft_contract["queue_vma"], "queue_vma")["start"]),
            int(_contract_dict(ft_contract["queue_vma"], "queue_vma")["end"]),
    ):
        raise DrawBankPlacementError("queue VMA contract is stale")
    if (record_vma, record_vma + record_bytes) != (
            int(_contract_dict(ft_contract["record_vma"], "record_vma")["start"]),
            int(_contract_dict(ft_contract["record_vma"], "record_vma")["end"]),
    ):
        raise DrawBankPlacementError("record-tail VMA contract is stale")

    resident = _contract_dict(contract.get("resident"), "resident")
    resident_rows = {
        name: _contract_dict(value, f"resident.{name}")
        for name, value in resident.items()
    }
    expected_resident = {
        "bridge": (0x0500, 0x07A0),
        "gate": (0x07A0, 0x0B00),
        "batch_cache": (0x0B00, 0x1000),
        "coordinate_tables": (0x1000, 0x2000),
        "resident_tables": (0x2000, 0x4000),
    }
    normalized = {}
    for name, (start, end) in expected_resident.items():
        row = resident_rows.get(name)
        if row is None:
            raise DrawBankPlacementError(f"resident range missing: {name}")
        actual_start = int(row.get("start", -1))
        actual_end = int(row.get("end", row.get("end_limit", -1)))
        if (actual_start, actual_end) != (start, end):
            raise DrawBankPlacementError(f"resident range is stale: {name}")
        normalized[name] = (start, end)

    bridge_binary = (root / "Build/pyz80_ft812_fragment_bridge.bin").read_bytes()
    coordinate_binary = (root / "Build/coordinate_tables.bin").read_bytes()
    resident_binary = (root / "Build/resident_tables.bin").read_bytes()
    bridge_actual_end = normalized["bridge"][0] + len(bridge_binary)
    coordinate_actual_end = normalized["coordinate_tables"][0] + len(
        coordinate_binary)
    resident_actual_end = normalized["resident_tables"][0] + len(
        resident_binary)
    if bridge_actual_end > normalized["bridge"][1]:
        raise DrawBankPlacementError("current resident bridge reaches draw gate")
    if coordinate_actual_end != normalized["coordinate_tables"][1]:
        raise DrawBankPlacementError("coordinate tables no longer fill 0x1000..0x1FFF")
    if resident_actual_end > normalized["resident_tables"][1]:
        raise DrawBankPlacementError("resident tables exceed page 00")

    sym_text = (root / "Build/rtype.sym").read_text(
        encoding="utf-8", errors="replace")
    symbols = _sym_values(sym_text)
    service_names = ("Memory.GetPage2", "Memory.SetPage2")
    try:
        services = {name: symbols[name] for name in service_names}
    except KeyError as exc:
        raise DrawBankPlacementError(f"missing resident MMU service {exc}") from exc
    if services != {"Memory.GetPage2": 0x0014, "Memory.SetPage2": 0x0010}:
        raise DrawBankPlacementError("resident MMU service addresses changed")

    gate_text = (root / "Source/ASM/pyz80_draw_bank_gate.asm").read_text(
        encoding="utf-8")
    _validate_gate_source(gate_text)
    if (
        _asm_equ(gate_text, "RTYPE_PYDRAW_BANK0_PAGE") != code_banks[0]
        or _asm_equ(gate_text, "RTYPE_PYDRAW_BANK1_PAGE") != code_banks[1]
        or _asm_equ(gate_text, "RTYPE_PYDRAW_BANK1_ENTRY") != CODE_START
    ):
        raise DrawBankPlacementError("resident gate bank constants are stale")
    assembler = _locate_sjasmplus(root)
    gate = _assemble_gate(
        root, assembler, GATE_START, normalized["gate"][1], services)
    gate_actual_end = GATE_START + int(gate["bytes"])
    resident_intervals = validate_intervals((
        ("existing_ft812_bridge", normalized["bridge"][0], bridge_actual_end),
        ("draw_cross_bank_gate", GATE_START, gate_actual_end),
        ("ft812_batch_cache", *normalized["batch_cache"]),
        ("coordinate_tables", normalized["coordinate_tables"][0],
         coordinate_actual_end),
        ("resident_tables", normalized["resident_tables"][0],
         resident_actual_end),
    ))

    unsplit = probe_unsplit_bundle(root)
    target_status_path = root / "Build/rtype_python_draw_target_bundle_status.json"
    if target_status_path.read_bytes() != _json_bytes(unsplit):
        raise DrawBankPlacementError("unsplit target-bundle status is stale")
    if unsplit.get("live") is not False:
        raise DrawBankPlacementError("unsplit target bundle unexpectedly claims live")
    unsplit_link = _contract_dict(unsplit.get("link"), "unsplit.link")
    unsplit_code = _contract_dict(unsplit_link.get("code"), "unsplit.code")
    unsplit_data = _contract_dict(unsplit_link.get("data"), "unsplit.data")
    if int(unsplit_code.get("bytes", -1)) != 17137 or int(
            unsplit_data.get("bytes", -1)) != 1280:
        raise DrawBankPlacementError("source-derived unsplit CODE/DATA size changed")

    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    if _sha256(sdcc.read_bytes()).upper() != (
            compiler_manifest.target.toolchain_sha256.upper()):
        raise DrawBankPlacementError("located SDCC does not match pinned hash")
    fast_slices = build_dependency_slices(root)
    lookup_slices = _extract_lookup_slices(root)
    bank0_sources = (
        "rtype_python_render_order.c",
        "rtype_python_draw_state.c",
        "rtype_python_draw_vm.c",
        "pyz80_draw_fast_chunker.c",
        "ft812_lookup_slice.c",
        "hqt3_lookup_slice.c",
        "pyz80_draw_bank0_proxy.c",
    )
    bank1_sources = (
        "pyz80_draw_bank1_entry.c",
        "ft812_fast_slice.c",
        "hqt3_fast_slice.c",
    )
    bank0 = _compile_bank(
        root, sdcc, "draw_bank_f1", bank0_sources,
        {
            "ft812_lookup_slice.c": str(lookup_slices["ft_source"]),
            "hqt3_lookup_slice.c": str(lookup_slices["hq_source"]),
        },
        tuple(Path(name).with_suffix(".rel").name for name in bank0_sources),
        ("__sdcc_call_iy.rel", "memcpy.rel"),
    )
    bank1 = _compile_bank(
        root, sdcc, "draw_bank_f2", bank1_sources,
        {
            "ft812_fast_slice.c": str(fast_slices["ft_source"]),
            "hqt3_fast_slice.c": str(fast_slices["hq_source"]),
        },
        tuple(Path(name).with_suffix(".rel").name for name in bank1_sources),
        (),
    )
    if int(_contract_dict(bank0["data"], "bank0.data")["bytes"]) != 0:
        raise DrawBankPlacementError("F1 bank unexpectedly owns mutable DATA")
    bank1_data = _contract_dict(bank1["data"], "bank1.data")
    if (
        int(bank1_data["bytes"]) != DATA_END - DATA_START
        or bank1_data["origin_hex"] != f"0x{DATA_START:04X}"
        or bank1_data["end_exclusive_hex"] != f"0x{DATA_END:04X}"
    ):
        raise DrawBankPlacementError("F2 preflight cache is not exact 0x0B00..0x0FFF")
    bank1_symbols = _contract_dict(bank1["public_symbols"], "bank1.symbols")
    entry_symbol = "_PyZ80DrawBank1_BuildSpriteBatchFast"
    if bank1_symbols.get(entry_symbol) != f"0x{CODE_START:04X}":
        raise DrawBankPlacementError("F2 tail entry moved away from 0x8000")
    if bank1_symbols.get("_PyZ80FT_BatchResolved") != f"0x{DATA_START:04X}":
        raise DrawBankPlacementError("F2 batch cache symbol moved away from 0x0B00")

    spg_text = (root / "spgbld_rtype.ini").read_text(
        encoding="utf-8", errors="replace")
    spg_blocks = _spg_blocks(spg_text)
    page_blocks: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in spg_blocks:
        page_blocks[int(row["page"])].append(row)
    if not any(
            row["path"] == "Build/python_compiled_p00.bin"
            for row in page_blocks.get(0xF0, [])):
        raise DrawBankPlacementError("existing compiler page F0 pack fact changed")
    if page_blocks.get(code_banks[0]) or page_blocks.get(code_banks[1]):
        raise DrawBankPlacementError("proposed F1/F2 pages are already packed")
    if any(row["page"] in queue_pages for row in spg_blocks):
        raise DrawBankPlacementError("runtime ED/EE queue page is statically packed")

    semantic_payload = {
        "placement_contract_sha256": _sha256(contract_path.read_bytes()),
        "memory_layout_sha256": _sha256(memory_path.read_bytes()),
        "unsplit_status_sha256": _sha256(target_status_path.read_bytes()),
        "lookup_slices": lookup_slices["report"],
        "fast_slices": fast_slices["report"],
        "gate_binary_sha256": gate["binary_sha256"],
        "bank_f1_ihx_sha256": bank0["ihx"]["sha256"],
        "bank_f2_ihx_sha256": bank1["ihx"]["sha256"],
        "bank_f1_code_bytes": bank0["code"]["bytes"],
        "bank_f2_code_bytes": bank1["code"]["bytes"],
        "cache_bytes": bank1["data"]["bytes"],
    }
    semantic_sha256 = _sha256(_json_bytes(semantic_payload))
    checks = {
        "unsplit_active_source_bundle_status_bound": True,
        "unsplit_code_17137_data_1280_measured": True,
        "two_actual_pinned_sdcc_links_completed": True,
        "each_code_link_fits_one_16k_slot2_bank": True,
        "physical_pages_f1_f2_free_in_current_packer": True,
        "mutable_cache_exactly_page00_0b00_1000": True,
        "resident_page00_ranges_nonoverlapping": True,
        "ft812_queues_remain_ed_ee_c000": True,
        "ft812_record_tail_remains_ca44_ffff": True,
        "ft812_template_page_ef_reserved": True,
        "cross_bank_edge_count_exactly_one": True,
        "sdcccall0_tail_stack_shape_preserved": True,
        "callee_entry_linked_at_8000": True,
        "resident_gate_assembled_and_fits": True,
        "real_final_link_proved": False,
        "production_packer_binding_proved": False,
        "live_callback_binding_proved": False,
        "isr_preemption_composition_proved": False,
    }
    blockers = [
        {
            "code": "PZBP001",
            "detail": (
                "the real production final link does not yet emit/install the "
                "proved F1/F2 bank images or the resident gate"),
        },
        {
            "code": "PZBP002",
            "detail": (
                "spgbld_rtype.ini still packs only the existing full F0 "
                "python_compiled_p00.bin; no F1/F2 draw-bank blocks are bound"),
        },
        {
            "code": "PZBP003",
            "detail": (
                "the generated draw VM/chunker/provider callbacks are not "
                "bound to these exact linked entry points in the live image"),
        },
        {
            "code": "PZBP004",
            "detail": (
                "the resident gate is deliberately non-reentrant; ISR and "
                "preemption composition across slot2 remapping is unproved"),
        },
        {
            "code": "PZBP005",
            "detail": (
                "page EF ownership is reserved but final command-template "
                "population/address binding is not proved"),
        },
        {
            "code": "PZBP006",
            "detail": (
                "the upstream whole-frame atomic budget and external stack "
                "contracts remain blocked; linked placement cannot raise them"),
        },
    ]
    return {
        "format": FORMAT,
        "status": STATUS,
        "semantic_sha256": semantic_sha256,
        "input": {
            "files": [_file_record(root, relative)
                      for relative in PLACEMENT_INPUTS],
            "placement_contract": contract,
            "placement_contract_sha256": _sha256(contract_path.read_bytes()),
            "semantic_payload": semantic_payload,
        },
        "memory": {
            "physical_page_bytes": PAGE_BYTES,
            "physical_page_count": memory.physical_page_count,
            "physical_ram_bytes": memory.physical_page_count * PAGE_BYTES,
            "layout_region_count": len(memory_report.region_names),
            "existing_compiler_page": {
                "page_hex": "0xF0",
                "artifact": "Build/python_compiled_p00.bin",
                "bytes": len((root / "Build/python_compiled_p00.bin").read_bytes()),
            },
            "draw_code_banks": [
                {"role": "render_vm_chunker_lookup", "page_hex": "0xF1"},
                {"role": "ft812_batch_builder", "page_hex": "0xF2"},
            ],
            "resident_intervals": list(resident_intervals),
            "existing_bridge_actual_end_hex": f"0x{bridge_actual_end:04X}",
            "mmu_services": {
                name: {"address_hex": f"0x{address:04X}"}
                for name, address in sorted(services.items())
            },
        },
        "ft812_storage": {
            "queue_pages": [f"0x{page:02X}" for page in queue_pages],
            "queue_vma": {
                "start_hex": f"0x{queue_vma:04X}",
                "end_exclusive_hex": f"0x{queue_vma + queue_bytes:05X}",
                "bytes": queue_bytes,
            },
            "record_tail": {
                "start_hex": f"0x{record_vma:04X}",
                "end_exclusive_hex": f"0x{record_vma + record_bytes:05X}",
                "bytes": record_bytes,
            },
            "batch_cache": {
                "physical_page_hex": "0x00",
                "start_hex": f"0x{DATA_START:04X}",
                "end_exclusive_hex": f"0x{DATA_END:04X}",
                "bytes": DATA_END - DATA_START,
                "always_mapped": True,
            },
            "command_template_page_hex": f"0x{template_page:02X}",
        },
        "unsplit_source_derived_bundle": {
            "status_path": "Build/rtype_python_draw_target_bundle_status.json",
            "status_sha256": _sha256(target_status_path.read_bytes()),
            "code_bytes": unsplit_code["bytes"],
            "data_bytes": unsplit_data["bytes"],
            "single_bank_overflow_bytes": unsplit_code[
                "single_bank_overflow_bytes"],
            "live": False,
        },
        "source_partition": {
            "bank_f1_lookup": lookup_slices["report"],
            "bank_f2_fast": fast_slices["report"],
            "hot_record_lookup_kept_in_caller_bank": True,
            "cross_bank_edges": [{
                "from_page_hex": "0xF1",
                "to_page_hex": "0xF2",
                "call_frequency": "once per submitted chunk, not per record",
                "proxy": "_PyZ80FT_BuildSpriteBatchFast",
                "resident_gate": "RTypePyDrawBank_CallF2C0",
                "callee_entry": entry_symbol,
                "callee_entry_address_hex": f"0x{CODE_START:04X}",
                "abi": "__sdcccall(0) caller cleanup; tail JP at both boundaries",
            }],
        },
        "resident_gate": gate,
        "links": {
            "page_f1": bank0,
            "page_f2": bank1,
        },
        "checks": checks,
        "final_binding_evidence": {
            "final_link_map_path": None,
            "final_link_map_sha256": None,
            "packed_page_f1_sha256": None,
            "packed_page_f2_sha256": None,
            "packed_resident_gate_sha256": None,
            "callback_binding_symbols": None,
            "proved": False,
        },
        "live": False,
        "live_blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_bank_placement_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = arguments.output
    if not output.is_absolute():
        output = root / output
    try:
        result = probe(root)
        _atomic_json(output, result)
    except (DrawTargetBundleError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "Draw bank placement: F1 CODE="
        f"{result['links']['page_f1']['code']['bytes']} B, F2 CODE="
        f"{result['links']['page_f2']['code']['bytes']} B, cache=1280 B; "
        "final link/callback binding remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
