#!/usr/bin/env python3
"""Fail-closed certificate for the isolated direct-RAM_DL v4 prototype.

The checker intentionally does not patch or build the game.  It certifies the
bounded prototype artifacts and records every missing live-integration proof.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from test_pyz80_draw_ramdl_shadow_v4 import run_host_reference_matrix


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))
from tsconf_ft812_sim import REG_DLSWAP, TSConfFT812Machine  # noqa: E402


FORMAT = "pyz80-draw-direct-ramdl-shadow-v4-certificate-v4"
STATUS = "DIRECT_RAMDL_DEDUP_LAYOUT_PROVED_LIVE_INTEGRATION_BLOCKED"
CPU_HZ = 14_000_000
FRAME_HZ = 55
FRAME_TSTATES = CPU_HZ // FRAME_HZ
RAM_DL_WORDS = 2048
MAX_USED_WORDS = 2047
MAX_OBJECTS = 228
SAFE_LINE_CYCLES = 1209
FT_SPI_MAX_HZ = 30_000_000
PREFIX_WORDS = 10
SUFFIX_WORDS = 3
ISR_RESERVE_PROPOSAL_BYTES = 256
DEDICATED_STACK_PROPOSAL_BYTES = 512
REQUIRED_BLOCKER_CODES = {
    "PZRAMDL401", "PZRAMDL402", "PZRAMDL403", "PZRAMDL404",
    "PZRAMDL405", "PZRAMDL406", "PZRAMDL407",
}
PINNED_ARGUMENTS = (
    "-mz80", "--std-c11", "--sdcccall", "1",
    "--fno-omit-frame-pointer", "--stack-auto", "--opt-code-speed",
    "--no-c-code-in-asm",
)
INPUTS = (
    "Source/C/ft812/pyz80_draw_ramdl_shadow_v4.c",
    "Source/C/ft812/pyz80_draw_ramdl_shadow_v4.h",
    "Source/ASM/pyz80_draw_ramdl_shadow_v4.asm",
    "Source/Tools/test_pyz80_draw_ramdl_shadow_v4.py",
    "Source/Tools/check_pyz80_draw_ramdl_shadow_v4.py",
    "Source/Tools/rtype_python_translator.py",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Build/PythonAssets/stage1_bootstrap_sprite_dl_templates.bin",
    "Build/rtype_python_full_hqt3_inventory_status.json",
    "Docs/TSLib/Examples/Game/Core/MainLoop.asm",
    "Docs/TSLib/Include/FT/DL  Macro.inc",
    "Docs/TSLib/Include/FT/812 Func.asm",
    "Docs/TSLib/Include/FT/812 Macro.inc",
    "Docs/TSLib/Include/DMA/Macro.inc",
)


class V4CheckError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) +
            "\n").encode("utf-8")


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    data = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _file_record(root: Path, relative: str) -> dict[str, object]:
    data = (root / relative).read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha256(data)}


def _run(command: list[str], directory: Path,
         environment: Mapping[str, str], timeout: int = 300
         ) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=directory, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=dict(environment))
    if completed.returncode:
        raise V4CheckError(
            f"command failed ({completed.returncode}): " +
            " ".join(command) + "\n" + completed.stdout)
    return completed


def _locate_sdcc(root: Path) -> Path:
    configured = os.environ.get("SDCC", "").strip('" ')
    candidates = [Path(configured)] if configured else []
    candidates.extend((
        root.parent / "sdcc" / "bin" / "sdcc.exe",
        Path(shutil.which("sdcc")) if shutil.which("sdcc") else Path(),
    ))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise V4CheckError("pinned SDCC was not found")


def _locate_sjasmplus(root: Path) -> Path:
    configured = os.environ.get("SJASMPLUS", "").strip('" ')
    candidates = [Path(configured)] if configured else []
    candidates.extend((
        root.parent / "z80" / "tsconf_project" / "exe" /
            "sjasmplus" / "sjasmplus.exe",
        Path(shutil.which("sjasmplus"))
        if shutil.which("sjasmplus") else Path(),
    ))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise V4CheckError("pinned sjasmplus was not found")


def _areas(text: str) -> dict[str, int]:
    return {match.group(1): int(match.group(2), 16) for match in re.finditer(
        r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+", text, re.MULTILINE)}


def _local_frame(assembly: str, symbol: str) -> int:
    match = re.search(
        rf"(?ms)^_{re.escape(symbol)}::?\s*$.*?"
        r"\bld\s+iy,\s*#-([0-9]+)\s*$.*?\badd\s+iy,\s*sp\s*$.*?"
        r"\bld\s+sp,\s*iy\s*$", assembly)
    if match is None:
        raise V4CheckError(f"cannot bind automatic frame for {symbol}")
    return int(match.group(1))


def _parse_ihx(path: Path) -> list[tuple[int, bytes]]:
    upper = 0
    rows: list[tuple[int, bytes]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count = raw[0]
        address = (raw[1] << 8) | raw[2]
        kind = raw[3]
        payload = raw[4:4 + count]
        if kind == 0:
            rows.append((upper + address, payload))
        elif kind == 4:
            upper = int.from_bytes(payload, "big") << 16
        elif kind == 1:
            break
    return rows


def _map_area(text: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"^{re.escape(name)}\s+([0-9A-Fa-f]{{8}})\s+"
        rf"([0-9A-Fa-f]{{8}})\s+=", text, re.MULTILINE)
    if match is None:
        raise V4CheckError(f"linked map lacks {name}")
    return int(match.group(1), 16), int(match.group(2), 16)


def _map_symbols(text: str, names: set[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for match in re.finditer(
            r"^\s*([0-9A-Fa-f]{8})\s+_([A-Za-z0-9_]+)\s+",
            text, re.MULTILINE):
        if match.group(2) in names:
            result[match.group(2)] = int(match.group(1), 16)
    if set(result) != names:
        raise V4CheckError(
            "benchmark symbols missing: " +
            ", ".join(sorted(names - set(result))))
    return result


def _parse_uint_array(text: str, name: str) -> list[int]:
    match = re.search(
        rf"\b{re.escape(name)}\s*\[[^]]+\]\s*=\s*\{{(.*?)\}};",
        text, re.DOTALL)
    if match is None:
        raise V4CheckError(f"cannot parse generated array {name}")
    values: list[int] = []
    for token in re.findall(r"0x[0-9A-Fa-f]+|\b[0-9]+", match.group(1)):
        values.append(int(token, 0))
    return values


def _active_catalog(root: Path) -> dict[str, object]:
    generated = (root / "Source/C/generated/rtype_python_hq_templates.c")
    text = generated.read_text(encoding="utf-8")
    sizes_bytes = _parse_uint_array(text, "PyZ80FT_HQAppendSize")
    addresses = _parse_uint_array(text, "PyZ80FT_HQAppendAddress")
    payload_path = root / (
        "Build/PythonAssets/stage1_bootstrap_sprite_dl_templates.bin")
    payload = payload_path.read_bytes()
    if len(sizes_bytes) != 73 or len(addresses) != 73:
        raise V4CheckError("active append catalog is not the certified 73 blobs")
    if any(size == 0 or size & 3 for size in sizes_bytes):
        raise V4CheckError("active append sizes are not nonzero aligned words")
    if sum(sizes_bytes) != len(payload):
        raise V4CheckError("active append payload size mismatch")
    for index in range(len(addresses) - 1):
        if addresses[index + 1] != addresses[index] + sizes_bytes[index]:
            raise V4CheckError("active append addresses are not contiguous")
    offset = 0
    control: list[dict[str, object]] = []
    opcodes: dict[int, int] = {}
    fragment_hashes: list[str] = []
    for blob, size in enumerate(sizes_bytes):
        fragment = payload[offset:offset + size]
        fragment_hashes.append(_sha256(fragment))
        words = struct.unpack("<" + "I" * (size // 4), fragment)
        for word_index, word in enumerate(words):
            opcode = word >> 24
            opcodes[opcode] = opcodes.get(opcode, 0) + 1
            if word == 0 or opcode in (0x1D, 0x1E, 0x24):
                control.append({"blob": blob, "word": word_index,
                                "value_hex": f"0x{word:08X}"})
        offset += size
    if control:
        raise V4CheckError("active append catalog contains structural control")
    sizes_words = [size // 4 for size in sizes_bytes]
    main_words = PREFIX_WORDS + 3 * MAX_OBJECTS + SUFFIX_WORDS
    cyclic_words = main_words + sum(size + 1 for size in sizes_words)
    if sum(sizes_words) != 1164 or cyclic_words != 1934:
        raise V4CheckError("active dedup layout arithmetic drifted")
    offsets: list[int] = []
    cursor = main_words
    for size in sizes_words:
        offsets.append(cursor)
        cursor += size + 1
    inventory_path = root / "Build/rtype_python_full_hqt3_inventory_status.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    bootstrap = inventory.get("current_bootstrap_hqt3", {})
    if bootstrap.get("full_template_count") != 10776:
        raise V4CheckError("full HQT inventory binding drifted")
    return {
        "blob_count": len(sizes_words),
        "size_words": sizes_words,
        "min_fragment_words": min(sizes_words),
        "max_fragment_words": max(sizes_words),
        "fragment_words_sum": sum(sizes_words),
        "payload_bytes": len(payload),
        "payload_sha256": _sha256(payload),
        "fragment_hash_list_sha256": _sha256(_json_bytes(fragment_hashes)),
        "control_word_count": len(control),
        "observed_high_bytes": {f"0x{key:02X}": value
                                for key, value in sorted(opcodes.items())},
        "first_ram_g_address_hex": f"0x{addresses[0]:06X}",
        "end_ram_g_address_exclusive_hex":
            f"0x{addresses[-1] + sizes_bytes[-1]:06X}",
        "main_words_for_228": main_words,
        "cyclic_228_all_73_unique_words": cyclic_words,
        "cyclic_228_headroom_words": MAX_USED_WORDS - cyclic_words,
        "maximum_call_destination_bytes": max(offsets) * 4,
        "all_call_destinations_aligned":
            all(((offset * 4) & 3) == 0 for offset in offsets),
        "full_hqt_key_count": bootstrap["full_template_count"],
        "bootstrap_record_count": bootstrap.get("record_count"),
        "full_catalog_residency_proved": False,
    }


def _layout_oracle(catalog: Mapping[str, object]) -> dict[str, object]:
    main = PREFIX_WORDS + 3 * MAX_OBJECTS + SUFFIX_WORDS
    shared_min = main + 4 + 1
    shared_max = main + 25 + 1
    all_unique_min = main + MAX_OBJECTS * (4 + 1)
    all_unique_max = main + MAX_OBJECTS * (25 + 1)
    boundary_pass_sizes = [25] * 69 + [4, 21]
    boundary_fail_sizes = [25] * 69 + [4, 22]
    boundary_main = PREFIX_WORDS + 3 * 71 + SUFFIX_WORDS
    boundary_pass = boundary_main + sum(size + 1 for size in boundary_pass_sizes)
    boundary_fail = boundary_main + sum(size + 1 for size in boundary_fail_sizes)
    if (shared_min, shared_max, all_unique_min, all_unique_max,
            boundary_pass, boundary_fail) != (702, 723, 1837, 6625, 2047, 2048):
        raise V4CheckError("closed-form layout boundary drifted")
    return {
        "formula": "prefix + suffix + 3*N + sum_unique(fragment_words + 1)",
        "main_words_228": main,
        "shared_identity_min_fragment_words": shared_min,
        "shared_identity_max_fragment_words": shared_max,
        "all_228_unique_min_fragment_words": all_unique_min,
        "all_228_unique_max_fragment_words": all_unique_max,
        "active_catalog_cyclic_words":
            catalog["cyclic_228_all_73_unique_words"],
        "strict_limit_words": MAX_USED_WORDS,
        "boundary_2047": {
            "objects": 71, "unique": 71,
            "fragment_sizes": "69*25 + 4 + 21",
            "words": boundary_pass, "passes": True,
        },
        "boundary_2048": {
            "objects": 71, "unique": 71,
            "fragment_sizes": "69*25 + 4 + 22",
            "words": boundary_fail, "passes": False,
        },
        "theoretical_all_unique_max_fits": all_unique_max <= MAX_USED_WORDS,
        "ft_call_byte_limit": 8191,
        "hardware_call_depth": 1,
        "hardware_call_stack_limit": 4,
    }


def _mutation_inventory(root: Path) -> dict[str, object]:
    identity_fields = {"bank_key", "descriptor", "state", "palette",
                       "resource_type"}
    list_methods = {"append", "extend", "insert", "remove", "pop",
                    "clear", "sort", "reverse"}
    identity_rows: list[tuple[str, int, str, str]] = []
    list_rows: list[tuple[str, int, str, str]] = []
    files: list[dict[str, object]] = []
    hook_calls = 0

    class Visitor(ast.NodeVisitor):
        def __init__(self, relative: str) -> None:
            self.relative = relative
            self.function = "<module>"

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.function
            self.function = node.name
            self.generic_visit(node)
            self.function = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def _target(self, node: ast.AST) -> None:
            if isinstance(node, (ast.Tuple, ast.List)):
                for item in node.elts:
                    self._target(item)
            elif (isinstance(node, ast.Attribute) and
                  isinstance(node.value, ast.Name) and
                  node.value.id == "self" and
                  node.attr in identity_fields):
                identity_rows.append((self.relative, node.lineno,
                                      self.function, node.attr))
            elif isinstance(node, ast.Subscript):
                list_rows.append((self.relative, node.lineno,
                                  self.function, "subscript-write"))

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                self._target(target)
            self.generic_visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._target(node.target)
            if node.value is not None:
                self.generic_visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self._target(node.target)
            self.generic_visit(node.value)

        def visit_Call(self, node: ast.Call) -> None:
            if (isinstance(node.func, ast.Attribute) and
                    node.func.attr in list_methods):
                list_rows.append((self.relative, node.lineno,
                                  self.function, node.func.attr))
            self.generic_visit(node)

    base = root / "Source/Python/rtype_port"
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        files.append({"path": relative, "bytes": len(data),
                      "sha256": _sha256(data)})
        hook_calls += data.count(b"PyZ80DrawRamDLV4_")
        Visitor(relative).visit(ast.parse(data.decode("utf-8"),
                                          filename=relative))
    identity_rows.sort()
    list_rows.sort()
    return {
        "scope": "Source/Python/rtype_port/**/*.py conservative AST inventory",
        "source_file_count": len(files),
        "source_tree_sha256": _sha256(_json_bytes(files)),
        "identity_write_site_count": len(identity_rows),
        "identity_write_rows_sha256": _sha256(_json_bytes(identity_rows)),
        "identity_by_field": {
            field: sum(row[3] == field for row in identity_rows)
            for field in sorted(identity_fields)},
        "list_mutation_or_subscript_site_count": len(list_rows),
        "list_rows_sha256": _sha256(_json_bytes(list_rows)),
        "list_by_kind": {
            kind: sum(row[3] == kind for row in list_rows)
            for kind in sorted({row[3] for row in list_rows})},
        "identity_sample": identity_rows[:16],
        "list_sample": list_rows[:16],
        "v4_hook_calls_found_in_active_python": hook_calls,
        "all_sites_instrumented": hook_calls > 0 and
            hook_calls >= len(identity_rows) + len(list_rows),
    }


def _compile_target(root: Path, sdcc: Path,
                    environment: Mapping[str, str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="pyz80-ramdl-v4-obj-") as raw:
        directory = Path(raw)
        for relative in INPUTS[:2]:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", "pyz80_draw_ramdl_shadow_v4.c"]
        completed = _run(command, directory, environment)
        rel = (directory / "pyz80_draw_ramdl_shadow_v4.rel").read_bytes()
        assembly = (directory / "pyz80_draw_ramdl_shadow_v4.asm").read_bytes()
    areas = _areas(rel.decode("latin1"))
    code = areas.get("_CODE", -1)
    data = areas.get("_DATA", -1)
    initialized = areas.get("_INITIALIZED", -1)
    if not 0 < code < 0x4000 or data != 0 or initialized != 0:
        raise V4CheckError("v4 target object CODE/DATA contract failed")
    assembly_text = assembly.decode("latin1")
    return {
        "compiler_path": sdcc.as_posix(),
        "compiler_sha256": _sha256(sdcc.read_bytes()),
        "arguments": list(PINNED_ARGUMENTS),
        "compiler_output": completed.stdout.strip(),
        "object_sha256": _sha256(rel),
        "assembly_sha256": _sha256(assembly),
        "code_bytes": code,
        "data_bytes": data,
        "initialized_data_bytes": initialized,
        "single_16k_bank_headroom_bytes": 0x4000 - code,
        "preflight_automatic_local_frame_bytes":
            _local_frame(assembly_text, "PyZ80DrawRamDLV4_Preflight"),
        "build_automatic_local_frame_bytes":
            _local_frame(assembly_text, "PyZ80DrawRamDLV4_BuildInactive"),
        "dedup_scratch_target_bytes": 1830,
        "dedup_scratch_is_automatic": False,
    }


def _assemble_target(root: Path, assembler: Path,
                     environment: Mapping[str, str]
                     ) -> tuple[bytes, dict[str, object]]:
    source = (root / "Source/ASM/pyz80_draw_ramdl_shadow_v4.asm").resolve()
    with tempfile.TemporaryDirectory(prefix="pyz80-ramdl-v4-asm-") as raw:
        directory = Path(raw)
        wrapper = (
            "                DEVICE ZXSPECTRUM128\n"
            "                ORG #1800\n"
            f'                include "{source.as_posix()}"\n'
            "                ASSERT PyZ80DrawRamDLV4_ASM_Start = #1800\n"
            "                ASSERT PyZ80DrawRamDLV4_ASM_End <= #1C00\n"
            "                SAVEBIN \"ramdl_v4.bin\", "
            "PyZ80DrawRamDLV4_ASM_Start, "
            "PyZ80DrawRamDLV4_ASM_End-PyZ80DrawRamDLV4_ASM_Start\n"
        )
        wrapper_path = directory / "wrapper.asm"
        wrapper_path.write_text(wrapper, encoding="utf-8", newline="\n")
        completed = _run(
            [str(assembler), "--nologo", wrapper_path.name],
            directory, environment)
        binary = (directory / "ramdl_v4.bin").read_bytes()
    if not binary or len(binary) > 0x400:
        raise V4CheckError("v4 publish ASM exceeds reserved prototype window")
    source_text = source.read_text(encoding="utf-8")
    checks = {
        "one_dma_start_instruction": len(re.findall(
            r"(?mi)^\s*LD\s+BC,\s*PYZ80_V4_DMACTR\s*$", source_text)) == 1,
        "fixed_16_bursts": bool(re.search(
            r"(?mi)^\s*LD\s+A,\s*15\s*$", source_text)),
        "fixed_256_words_per_burst": bool(re.search(
            r"(?mi)^\s*LD\s+A,\s*#FF\s*$", source_text)),
        "frame_swap_requested": "PYZ80_V4_DLSWAP_FRAME" in source_text,
        "int_swap_and_level_fences_present":
            ".waitInt:" in source_text and ".waitLevel:" in source_text,
        "dummy_and_data_reads_present":
            "discard FT812 dummy response" in source_text and
            "requested register byte" in source_text,
    }
    if not all(checks.values()):
        raise V4CheckError("v4 ASM structural contract failed")
    return binary, {
        "assembler_path": assembler.as_posix(),
        "assembler_sha256": _sha256(assembler.read_bytes()),
        "assembler_output": re.sub(
            r"work time:\s*[0-9.]+\s*seconds",
            "work time: <normalized>", completed.stdout.strip()),
        "origin_hex": "0x1800",
        "end_exclusive_hex": f"0x{0x1800 + len(binary):04X}",
        "bytes": len(binary),
        "binary_sha256": _sha256(binary),
        "source_sha256": _sha256(source.read_bytes()),
        "structural_checks": checks,
    }


def _reference_semantics(root: Path) -> dict[str, object]:
    main_path = root / "Docs/TSLib/Examples/Game/Core/MainLoop.asm"
    call_path = root / "Docs/TSLib/Include/FT/DL  Macro.inc"
    read_path = root / "Docs/TSLib/Include/FT/812 Func.asm"
    dma_path = root / "Docs/TSLib/Include/DMA/Macro.inc"
    main = main_path.read_text(encoding="utf-8", errors="replace")
    calls = call_path.read_text(encoding="utf-8", errors="replace")
    reads = read_path.read_text(encoding="utf-8", errors="replace")
    dma = dma_path.read_text(encoding="utf-8", errors="replace")
    checks = {
        "tslib_direct_ram_dl_write":
            "FT_WR_DL DL_Point, #0000, Tilemap.Size" in main,
        "tslib_dlswap_frame":
            "FT_WR_REG8 FT_REG_DLSWAP, FT_DLSWAP_FRAME" in main,
        "tslib_int_swap_wait": "AND FT_INT_SWAP" in main,
        "call_encoding_0x1d":
            "DEFD (29 << 24)" in calls,
        "return_encoding_0x24":
            "DEFD (36 << 24)" in calls,
        "ft_read_requires_dummy_then_data":
            len(re.findall(r"(?mi)^\s*IN A, \(C\)", reads)) >= 2,
        "dma_length_and_number_are_minus_one":
            "NumberBurst? - 1" in dma and "BurstSize? >> 1) - 1" in dma,
    }
    if not all(checks.values()):
        raise V4CheckError("local FT812/TSLib semantic witness drifted")
    return {
        "checks": checks,
        "local_witnesses": [
            _file_record(root, "Docs/TSLib/Examples/Game/Core/MainLoop.asm"),
            _file_record(root, "Docs/TSLib/Include/FT/DL  Macro.inc"),
            _file_record(root, "Docs/TSLib/Include/FT/812 Func.asm"),
            _file_record(root, "Docs/TSLib/Include/DMA/Macro.inc"),
        ],
        "authoritative_urls": {
            "ft81x_programmer_guide":
                "https://brtchip.com/wp-content/uploads/Support/Documentation/"
                "Application_Notes/ICs/EVE/BRT_AN_033_FT81X_Series_Programming_Guide.pdf",
            "ft81x_datasheet":
                "https://www.ftdichip.com/Support/Documents/DataSheets/ICs/DS_FT81x.pdf",
            "tsconf_dma_spec":
                "https://github.com/tslabs/zx-evo/blob/master/pentevo/docs/TSconf/tsconf_en.md",
            "tslib_game":
                "https://github.com/DeadlyKom/TSLib/tree/main/Examples/Game",
        },
    }


def _asm_oracle(root: Path, binary: bytes) -> dict[str, object]:
    state_address = 0x7000
    retired_address = 0x7002
    params_address = 0x7100
    source_page = 9
    source_offset = 0x2000
    shadow = bytes(((index * 37 + 11) & 0xFF) for index in range(8192))

    def execute(*, state: int = 2, used_words: int = 1934,
                publish_epoch: int = 9, retired_epoch: int = 8,
                offset: int = source_offset, page: int = source_page,
                poll_limit: int = 8, initial_dlswap: int = 0,
                dma_stuck: bool = False, swap_stuck: bool = False,
                source: bytes = shadow) -> dict[str, object]:
        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x1800",
            default_stack="0xFF00")
        machine.mem.write_block_linear(0x1800, binary)
        machine.mem.write_physical(page, offset, source)
        machine.mem.write(state_address, state)
        machine.mem.write_block_linear(
            retired_address, struct.pack("<H", retired_epoch))
        params = struct.pack(
            "<HHHHHHBB", state_address, retired_address, used_words,
            publish_epoch, offset, poll_limit, page, 0xFF)
        machine.mem.write_block_linear(params_address, params)
        machine.ft.dlswap = initial_dlswap
        if dma_stuck:
            def stuck_dma(mode: int) -> None:
                if mode != 0x82:
                    machine.errors.append(f"unexpected DMA mode {mode:#x}")
                machine.dma.status = 0x80
            machine._start_dma = stuck_dma  # type: ignore[method-assign]
        if swap_stuck:
            original_write = machine._write_ft_addr

            def stuck_swap(address: int, value: int) -> None:
                if (address & 0x3FFFFF) == REG_DLSWAP:
                    machine.ft.dlswap = value & 3
                    return
                original_write(address, value)
            machine._write_ft_addr = stuck_swap  # type: ignore[method-assign]
        initial_sp = machine.reg.SP
        minimum_sp = initial_sp
        original_step = machine.step

        def tracked_step() -> int:
            nonlocal minimum_sp
            clocks = original_step()
            minimum_sp = min(minimum_sp, machine.reg.SP)
            return clocks

        machine.step = tracked_step  # type: ignore[method-assign]
        before = machine.tstates
        steps = machine.call(
            0x1800, h=params_address >> 8, l=params_address & 0xFF,
            max_steps=2_000_000)
        tstates = machine.tstates - before
        if machine.reg.SP != initial_sp:
            raise V4CheckError("v4 ASM did not restore SP")
        raw = machine.mem.read_block(params_address, 14)
        result = struct.unpack("<HHHHHHBB", raw)
        dma_starts = [row for row in machine.ports_out
                      if row == (0x27AF, 0x82)]
        return {
            "a": machine.reg.A,
            "status": result[-1],
            "state": machine.mem.read(state_address),
            "retired_epoch": struct.unpack(
                "<H", machine.mem.read_block(retired_address, 2))[0],
            "ram_dl": bytes(machine.ft.ram_dl),
            "dma_start_count": len(dma_starts),
            "dmalean_values": [value for port, value in machine.ports_out
                                if port == 0x26AF],
            "dmanum_values": [value for port, value in machine.ports_out
                               if port == 0x28AF],
            "errors": list(machine.errors),
            "steps": steps,
            "cpu_tstates": tstates,
            "stack_bytes_including_outer_return": initial_sp - minimum_sp,
        }

    success = execute()
    busy = execute(state=0)
    capacity = execute(used_words=2048)
    stale = execute(retired_epoch=9)
    pending = execute(initial_dlswap=2)
    dma_timeout = execute(dma_stuck=True)
    swap_timeout = execute(swap_stuck=True)
    checks = {
        "success_exact_shadow_to_ram_dl":
            success["a"] == 0 and success["status"] == 0 and
            success["ram_dl"] == shadow,
        "success_one_dma_16x512":
            success["dma_start_count"] == 1 and
            success["dmalean_values"] == [255] and
            success["dmanum_values"] == [15],
        "success_retires_only_after_both_observed_fences":
            success["state"] == 7 and success["retired_epoch"] == 9,
        "success_has_no_simulator_errors": not success["errors"],
        "non_ready_fails_before_dma":
            busy["status"] == 9 and busy["dma_start_count"] == 0,
        "strict_2048_fails_before_dma":
            capacity["status"] == 5 and capacity["dma_start_count"] == 0,
        "retired_epoch_replay_fails_before_dma":
            stale["status"] == 7 and stale["dma_start_count"] == 0,
        "pending_previous_swap_fails_before_dma":
            pending["status"] == 9 and pending["dma_start_count"] == 0,
        "dma_timeout_never_retires":
            dma_timeout["status"] == 10 and
            dma_timeout["state"] == 3 and
            dma_timeout["retired_epoch"] == 8,
        "swap_timeout_never_retires":
            swap_timeout["status"] == 10 and
            swap_timeout["state"] == 4 and
            swap_timeout["retired_epoch"] == 8,
    }
    if not all(checks.values()):
        raise V4CheckError("v4 ASM oracle failed: " + ", ".join(
            key for key, value in checks.items() if not value))
    return {
        "matrix": checks,
        "success_cpu_steps_with_immediate_devices": success["steps"],
        "success_cpu_tstates_with_immediate_devices": success["cpu_tstates"],
        "success_stack_bytes_including_outer_return":
            success["stack_bytes_including_outer_return"],
        "dma_timeout_poll_limit_8_cpu_tstates": dma_timeout["cpu_tstates"],
        "swap_timeout_poll_limit_8_cpu_tstates": swap_timeout["cpu_tstates"],
        "device_model_note":
            "CPU instruction count only; simulator completes DMA and swap "
            "immediately and is not a hardware WCET source",
    }


BENCH_SOURCE = r'''
#include <stdint.h>
#include <string.h>
#include "pyz80_draw_ramdl_shadow_v4.h"

static uint32_t fragment_words[4];
static PyZ80DrawRamDLV4Fragment fragment;
static PyZ80DrawRamDLV4Object objects[2];
static PyZ80DrawRamDLV4Model model;
static PyZ80DrawRamDLV4Certificate certificate;
static uint16_t raster_lines[768];
static PyZ80DrawRamDLV4RasterProof raster;
static PyZ80DrawRamDLV4DedupScratch scratch;
static PyZ80DrawRamDLV4Layout layout;
static PyZ80DrawRamDLV4DoubleShadow shadows;
static uint32_t prefix[10];
static uint32_t suffix[3];
volatile uint8_t v4_bench_status;

uint8_t V4Bench_Setup(void)
{
    uint16_t index;
    memset(&fragment, 0, sizeof(fragment));
    memset(objects, 0, sizeof(objects));
    memset(&model, 0, sizeof(model));
    memset(&certificate, 0, sizeof(certificate));
    memset(raster_lines, 0, sizeof(raster_lines));
    memset(&raster, 0, sizeof(raster));
    memset(&scratch, 0, sizeof(scratch));
    memset(&layout, 0, sizeof(layout));
    memset(&shadows, 0, sizeof(shadows));
    for (index = 0u; index < 4u; ++index)
        fragment_words[index] = 0x09001000ul + index;
    fragment.words = fragment_words;
    fragment.word_count = 4u;
    fragment.worst_line_cycles = 20u;
    fragment.identity = 5u;
    fragment.generation = 7u;
    for (index = 0u; index < 2u; ++index) {
        objects[index].object_id = index;
        objects[index].generation = 7u;
        objects[index].vertex_x = (int16_t)index;
        objects[index].vertex_y = (int16_t)(2u - index);
        objects[index].fragment = &fragment;
    }
    model.objects = objects;
    model.count = 2u;
    model.capacity = 2u;
    model.epoch = 1u;
    certificate.format_version = 4u;
    certificate.immutable_fragment_proof = 1u;
    certificate.dedup_identity_generation_proof = 1u;
    certificate.exact_order_hook_proof = 1u;
    certificate.direct_ram_dl_proof = 1u;
    certificate.double_shadow_epoch_proof = 1u;
    certificate.swap_fence_proof = 1u;
    certificate.raster_proof = 1u;
    certificate.ts_ram_allocation_proof = 1u;
    certificate.max_objects = 228u;
    certificate.max_used_words = 2047u;
    certificate.safe_line_cycles = 1209u;
    certificate.fragment_min_words = 4u;
    certificate.fragment_max_words = 25u;
    raster.cycles_by_line = raster_lines;
    raster.line_count = 768u;
    raster.model_epoch = 1u;
    raster.max_cycles = 0u;
    raster.worst_line = 0u;
    prefix[0] = 0x02010203ul;
    for (index = 1u; index < 10u; ++index)
        prefix[index] = 0x09002000ul + index;
    suffix[0] = 0x26000007ul;
    suffix[1] = 0x21000000ul;
    suffix[2] = 0ul;
    shadows.slot[0].words = (volatile uint32_t *)0x6000u;
    shadows.slot[0].capacity_words = 2048u;
    shadows.slot[0].physical_page = 9u;
    shadows.slot[0].physical_offset = 0u;
    shadows.slot[0].state = PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE;
    shadows.slot[0].slot = 0u;
    shadows.slot[1].words = (volatile uint32_t *)0x8000u;
    shadows.slot[1].capacity_words = 2048u;
    shadows.slot[1].physical_page = 9u;
    shadows.slot[1].physical_offset = 0x2000u;
    shadows.slot[1].state = PYZ80_DRAW_RAMDL_V4_SHADOW_FREE;
    shadows.slot[1].slot = 1u;
    shadows.active_slot = 0u;
    shadows.dma_slot = 0xFFu;
    v4_bench_status = 0xFFu;
    return 1u;
}

uint8_t V4Bench_Build(void)
{
    v4_bench_status = (uint8_t)PyZ80DrawRamDLV4_BuildInactive(
        &model, prefix, 10u, suffix, 3u, &certificate, &raster,
        &scratch, &shadows, &layout);
    return (uint8_t)(v4_bench_status == 0u);
}
'''


def _target_stack_benchmark(root: Path, sdcc: Path,
                            environment: Mapping[str, str]
                            ) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="pyz80-ramdl-v4-bench-") as raw:
        directory = Path(raw)
        for relative in INPUTS[:2]:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "v4_bench.c").write_text(
            BENCH_SOURCE, encoding="utf-8", newline="\n")
        for name in ("pyz80_draw_ramdl_shadow_v4.c", "v4_bench.c"):
            _run([str(sdcc), *PINNED_ARGUMENTS, "-c", name],
                 directory, environment)
        _run([
            str(sdcc), "-mz80", "--no-std-crt0",
            "--code-loc", "0x2000", "--data-loc", "0xA000",
            "-o", "v4_bench.ihx",
            "pyz80_draw_ramdl_shadow_v4.rel", "v4_bench.rel",
        ], directory, environment)
        map_bytes = (directory / "v4_bench.map").read_bytes()
        map_text = map_bytes.decode("latin1")
        symbols = _map_symbols(map_text, {
            "V4Bench_Setup", "V4Bench_Build", "v4_bench_status"})
        code_start, code_bytes = _map_area(map_text, "_CODE")
        data_start, data_bytes = _map_area(map_text, "_DATA")
        image = _parse_ihx(directory / "v4_bench.ihx")
        image_sha256 = _sha256((directory / "v4_bench.ihx").read_bytes())
    if code_start + code_bytes >= 0x6000:
        raise V4CheckError("v4 benchmark code overlaps fixed shadow windows")
    if data_start < 0xA000 or data_start + data_bytes >= 0xF000:
        raise V4CheckError("v4 benchmark data overlaps shadow/stack windows")
    machine = TSConfFT812Machine(
        root, load_spg=False, default_start="0x2000",
        default_stack="0xFF00")
    for address, payload in image:
        if address + len(payload) > 0x10000:
            raise V4CheckError("v4 benchmark exceeds Z80 address space")
        machine.mem.write_block_linear(address, payload)
    initial_sp = machine.reg.SP
    minimum_sp = initial_sp
    original_step = machine.step

    def tracked_step() -> int:
        nonlocal minimum_sp
        clocks = original_step()
        minimum_sp = min(minimum_sp, machine.reg.SP)
        return clocks

    machine.step = tracked_step  # type: ignore[method-assign]

    def measure(symbol: str, max_steps: int) -> dict[str, int]:
        nonlocal minimum_sp
        minimum_sp = machine.reg.SP
        before = machine.tstates
        steps = machine.call(symbols[symbol], max_steps=max_steps)
        result = {
            "steps": steps,
            "tstates": machine.tstates - before,
            "stack_bytes_including_outer_return":
                initial_sp - minimum_sp,
        }
        if machine.reg.SP != initial_sp:
            raise V4CheckError(f"{symbol} did not restore SP")
        return result

    setup = measure("V4Bench_Setup", 2_000_000)
    build = measure("V4Bench_Build", 20_000_000)
    if machine.mem.read(symbols["v4_bench_status"]) != 0:
        raise V4CheckError("v4 target stack benchmark build failed")
    total_with_isr = (build["stack_bytes_including_outer_return"] +
                      ISR_RESERVE_PROPOSAL_BYTES)
    return {
        "linked_image_sha256": image_sha256,
        "linked_code_start_hex": f"0x{code_start:04X}",
        "linked_code_bytes": code_bytes,
        "linked_data_start_hex": f"0x{data_start:04X}",
        "linked_data_bytes": data_bytes,
        "setup": setup,
        "build_two_duplicate_objects": build,
        "proposed_isr_reserve_bytes": ISR_RESERVE_PROPOSAL_BYTES,
        "proposed_dedicated_stack_bytes": DEDICATED_STACK_PROPOSAL_BYTES,
        "measured_build_plus_proposed_isr_reserve_bytes": total_with_isr,
        "fits_proposed_dedicated_stack":
            total_with_isr <= DEDICATED_STACK_PROPOSAL_BYTES,
        "actual_game_isr_stack_bound_bytes": None,
        "complete_preemption_composition_proved": False,
    }


def _allocation_proof(catalog: Mapping[str, object]) -> dict[str, object]:
    target_sizes = {
        "object": 10,
        "fragment_descriptor": 10,
        "model": 10,
        "shadow_metadata": 29,
        "double_shadow_metadata": 66,
        "certificate": 19,
        "raster_proof": 10,
        "layout": 24,
        "dedup_scratch": 1830,
    }
    metadata_page_used = (
        int(catalog["payload_bytes"]) +
        target_sizes["dedup_scratch"] +
        MAX_OBJECTS * target_sizes["object"] +
        MAX_OBJECTS * target_sizes["fragment_descriptor"] +
        768 * 2 +
        target_sizes["model"] +
        target_sizes["double_shadow_metadata"] +
        target_sizes["certificate"] +
        target_sizes["raster_proof"] +
        target_sizes["layout"] +
        (PREFIX_WORDS + SUFFIX_WORDS) * 4)
    if metadata_page_used != 12763:
        raise V4CheckError("target active-catalog working-set arithmetic drifted")
    return {
        "target_struct_sizes_bytes": target_sizes,
        "shadow_page": {
            "bytes": 16384,
            "slot_0": {"offset": 0, "bytes": 8192},
            "slot_1": {"offset": 8192, "bytes": 8192},
            "overlap": False,
        },
        "active_catalog_workspace_page": {
            "bytes": 16384,
            "used_bytes": metadata_page_used,
            "headroom_bytes": 16384 - metadata_page_used,
            "includes": [
                "4656-byte active immutable fragment payload",
                "1830-byte caller-owned dedup scratch",
                "228 object records and 228 fragment descriptors",
                "768-line uint16 raster proof",
                "model/double-shadow/certificate/layout metadata",
                "10-word prefix and 3-word suffix",
            ],
        },
        "total_reserved_pages": 2,
        "total_reserved_bytes": 32768,
        "ts_ram_bytes": 4 * 1024 * 1024,
        "fraction_of_ts_ram": round(32768 / (4 * 1024 * 1024), 8),
        "arithmetic_fits_4mb": 32768 <= 4 * 1024 * 1024,
        "physical_page_numbers_bound": False,
        "cache_coherency_and_page_owner_bound": False,
        "full_10776_key_catalog_residency_in_two_pages_claimed": False,
    }


def _timing_proof(asm_oracle: Mapping[str, object]) -> dict[str, object]:
    bulk_spi_bytes = 3 + 8192
    register_write_bytes = 4
    register_read_transactions = 3
    bytes_per_read_transaction = 6
    success_spi_bytes = (bulk_spi_bytes + register_write_bytes +
                         register_read_transactions *
                         bytes_per_read_transaction)
    bulk_lower_tstates = math.ceil(
        bulk_spi_bytes * 8 * CPU_HZ / FT_SPI_MAX_HZ)
    complete_wire_lower_tstates = math.ceil(
        success_spi_bytes * 8 * CPU_HZ / FT_SPI_MAX_HZ)
    return {
        "cpu_hz": CPU_HZ,
        "frame_hz": FRAME_HZ,
        "whole_frame_tstates": FRAME_TSTATES,
        "fixed_dma_payload_bytes": 8192,
        "fixed_dma_geometry": {
            "words_per_burst": 256,
            "bytes_per_burst": 512,
            "burst_count": 16,
            "dma_start_count": 1,
        },
        "ft812_single_spi_max_hz": FT_SPI_MAX_HZ,
        "bulk_header_plus_payload_spi_bytes": bulk_spi_bytes,
        "success_minimum_spi_clocked_bytes": success_spi_bytes,
        "absolute_bulk_wire_lower_bound_tstates_at_30mhz":
            bulk_lower_tstates,
        "absolute_success_wire_lower_bound_tstates_at_30mhz":
            complete_wire_lower_tstates,
        "assembled_cpu_immediate_device_reference_tstates":
            asm_oracle["success_cpu_tstates_with_immediate_devices"],
        "assembled_cpu_immediate_device_reference_steps":
            asm_oracle["success_cpu_steps_with_immediate_devices"],
        "ts_dma_spi_contention_upper_bound_tstates": None,
        "dlswap_frame_retirement_upper_bound_tstates": None,
        "busy_poll_limit_is_caller_supplied_1_to_65535": True,
        "complete_publish_wcet_tstates": None,
        "fits_14mhz_55hz_frame_proved": False,
        "reason": (
            "The TS-Conf specification states that DMA speed depends on "
            "memory-controller load and peripheral speed but supplies no "
            "numeric worst case; DLSWAP_FRAME also waits for a display-frame "
            "boundary. Emulator-immediate timing is not hardware WCET."),
    }


def _static_atomic_checks(root: Path) -> dict[str, bool]:
    c_source = (root / INPUTS[0]).read_text(encoding="utf-8")
    asm_source = (root / INPUTS[2]).read_text(encoding="utf-8")
    build_start = c_source.index("PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_BuildInactive")
    build_body = c_source[build_start:]
    ready_store = "shadow->state = PYZ80_DRAW_RAMDL_V4_SHADOW_READY;"
    ready_index = build_body.rfind(ready_store)
    checksum_index = build_body.rfind("shadow->dedup_checksum =")
    checks = {
        "build_has_exactly_one_ready_store": build_body.count(ready_store) == 1,
        "ready_store_follows_all_metadata_and_checksums":
            ready_index > checksum_index > 0,
        "preflight_never_accepts_ram_dl_word_2048":
            "PYZ80_DRAW_RAMDL_V4_MAX_USED_WORDS 2047u" in
            (root / INPUTS[1]).read_text(encoding="utf-8"),
        "no_cmd_fifo_in_target_asm":
            "RAM_CMD" not in asm_source and "CMD_" not in asm_source,
        "one_target_dma_start": asm_source.count(
            "LD   BC, PYZ80_V4_DMACTR") == 1,
        "ready_not_written_by_target_asm":
            "PYZ80_V4_STATE_READY" in asm_source and
            "LD   (HL), PYZ80_V4_STATE_READY" not in asm_source,
        "dedup_compare_not_in_target_publish":
            "identity" not in asm_source.lower() and
            "fragment" not in asm_source.lower(),
    }
    if not all(checks.values()):
        raise V4CheckError("static atomic check failed")
    return checks


def _main_translator_evidence(root: Path,
                              mutations: Mapping[str, object]
                              ) -> dict[str, object]:
    relative = "Source/Tools/rtype_python_translator.py"
    data = (root / relative).read_bytes()
    abi_references = data.count(b"PyZ80DrawRamDLV4")
    status_references = data.count(
        b"rtype_python_draw_ramdl_shadow_v4_status")
    validator_references = data.count(b"validate_report")
    integrated = bool(
        abi_references > 0 and
        mutations.get("all_sites_instrumented") is True)
    return {
        "source": _file_record(root, relative),
        "v4_c_abi_reference_count": abi_references,
        "v4_status_path_reference_count": status_references,
        "validate_report_reference_count": validator_references,
        "v4_hooks_all_sites_instrumented":
            mutations.get("all_sites_instrumented") is True,
        "integrated": integrated,
    }


def build_report(root: Path) -> dict[str, object]:
    for relative in INPUTS:
        if not (root / relative).is_file():
            raise V4CheckError(f"missing v4 input: {relative}")
    environment = os.environ.copy()
    sdcc = _locate_sdcc(root)
    assembler = _locate_sjasmplus(root)
    environment["PATH"] = str(sdcc.parent) + os.pathsep + environment.get(
        "PATH", "")
    host = run_host_reference_matrix()
    catalog = _active_catalog(root)
    layout = _layout_oracle(catalog)
    target = _compile_target(root, sdcc, environment)
    asm_binary, assembly = _assemble_target(root, assembler, environment)
    asm_oracle = _asm_oracle(root, asm_binary)
    target_stack = _target_stack_benchmark(root, sdcc, environment)
    allocation = _allocation_proof(catalog)
    timing = _timing_proof(asm_oracle)
    mutations = _mutation_inventory(root)
    translator_evidence = _main_translator_evidence(root, mutations)
    semantics = _reference_semantics(root)
    atomic_checks = _static_atomic_checks(root)
    inputs = [_file_record(root, relative) for relative in INPUTS]
    proofs = {
        "dedup_layout_formula_and_2047_2048_boundary": True,
        "active_73_blob_catalog_lossless_and_control_free": True,
        "python_draw_order_x_y_call": True,
        "duplicate_identity_generation_byte_count_cycle_equality": True,
        "hardware_call_stack_depth_one": True,
        "isolated_build_fail_atomic_ready_last": True,
        "isolated_single_dma_and_two_fence_retirement": True,
        "synthetic_1209_1210_raster_gate": True,
        "caller_owned_1830_byte_scratch_not_z80_stack": True,
        "active_catalog_two_page_4mb_arithmetic": True,
        "full_translator_mutation_and_list_hooks": False,
        "real_scene_raster_provider_same_epoch": False,
        "immutable_fragment_provider_and_generation_owner": False,
        "physical_ts_page_ownership_and_cache_coherency": False,
        "ts_dma_and_swap_hardware_wcet": False,
        "game_isr_stack_bound_and_preemption_composition": False,
        "final_link_and_bank_placement": False,
        "target_asm_complete_double_shadow_metadata_transition": False,
    }
    blockers = [
        {
            "code": "PZRAMDL401",
            "scope": "translator-hooks",
            "detail": (
                f"{mutations['identity_write_site_count']} conservative "
                "identity writes and "
                f"{mutations['list_mutation_or_subscript_site_count']} "
                "list/subscript mutation sites are inventoried but no active "
                "Python site calls the v4 hooks."),
        },
        {
            "code": "PZRAMDL402",
            "scope": "fragment-and-raster-provider",
            "detail": (
                "No production immutable (identity,generation) fragment "
                "provider or exact 768-line raster proof is bound to every "
                "authoritative model epoch."),
        },
        {
            "code": "PZRAMDL403",
            "scope": "physical-allocation",
            "detail": (
                "The two-page/32768-byte placement arithmetic fits 4 MB, but "
                "no immutable TS page owner, mapping window, or cache policy "
                "is reserved in the target link."),
        },
        {
            "code": "PZRAMDL404",
            "scope": "hardware-timing",
            "detail": (
                "One 8192-byte DMA is exact, but TS DMA/SPI contention and "
                "DLSWAP_FRAME retirement have no numeric hardware WCET; the "
                "blocking poll path therefore has no frame-safe bound."),
        },
        {
            "code": "PZRAMDL405",
            "scope": "stack-and-isr",
            "detail": (
                "SDCC and ASM internal stacks are measured, and a 256-byte "
                "ISR reserve fits the proposed 512-byte stack, but the actual "
                "game ISR maximum is not certified."),
        },
        {
            "code": "PZRAMDL406",
            "scope": "target-retirement-wrapper",
            "detail": (
                "The isolated ASM retires the new state/epoch after both "
                "fences, but its compact ABI does not update active_slot, "
                "dma_slot, or the previous ACTIVE shadow; a final wrapper is "
                "required before integration."),
        },
        {
            "code": "PZRAMDL407",
            "scope": "full-catalog-capacity",
            "detail": (
                "The active 73-blob cyclic set fits at 1934 words, while 228 "
                "distinct 25-word fragments require 6625 words. A live-set "
                "capacity proof must fail closed for every level/state."),
        },
    ]
    integration_requirements = [
        "Generate the PyZ80DrawRamDLV4Model in exact Python draw order outside render.",
        "Route every spawn/remove/reorder/coordinate and identity-generation mutation through the v4 hooks; regenerate the epoch-bound raster proof.",
        "Install byte-immutable HQT fragments keyed by (identity,generation); conflicting duplicate keys must remain fatal.",
        "Preallocate the 1830-byte dedup scratch and active working set in a mapped non-stack page; reserve one separate 16 KB page for the two 8 KB shadows.",
        "Bind physical TS pages, disable/handle cache coherency, and prove no DMA or asset-loader ownership overlap.",
        "Run Preflight/Build off-frame; the render hot path may consume READY only and must never run dedup comparison or fragment lookup.",
        "Provide a target wrapper that atomically transitions dma_slot/active_slot/old shadow after INT_SWAP and REG_DLSWAP==0.",
        "Replace blocking frame-swap polling or schedule it outside gameplay, then measure worst-case DMA/SPI contention and swap retirement on patched Unreal and hardware.",
        "Prove the real ISR stack maximum is at most the reserved 256 bytes and reserve at least 512 bytes for composed stack use.",
        "Run the 2047-word and 1209-cycle gates for every emitted frame/live set; 2048, 1210, stale epoch, or missing provider must publish nothing.",
        "Repeat pinned final-link CODE/DATA/bank checks before setting live=true.",
    ]
    report: dict[str, object] = {
        "format": FORMAT,
        "status": STATUS,
        "live": False,
        "spg_built": False,
        "unreal_started": False,
        "inputs": inputs,
        "host_reference": host,
        "layout": layout,
        "active_catalog": catalog,
        "target_object": target,
        "target_assembly": assembly,
        "asm_reference_oracle": asm_oracle,
        "target_stack": target_stack,
        "allocation": allocation,
        "timing": timing,
        "raster": {
            "safe_line_cycles": SAFE_LINE_CYCLES,
            "synthetic_1209_passes": True,
            "synthetic_1210_fails": True,
            "real_scene_proof_bound": False,
        },
        "mutation_and_list_hook_inventory": mutations,
        "main_translator_integration": translator_evidence,
        "ft812_tsconf_semantics": semantics,
        "atomic_static_checks": atomic_checks,
        "proofs": proofs,
        "blockers": blockers,
        "integration_requirements": integration_requirements,
        "consumer_validation_api": {
            "module": "Source.Tools.check_pyz80_draw_ramdl_shadow_v4",
            "function": "validate_report(root, report)",
            "checks": ["analysis_sha256", "all input hashes",
                       "mandatory blocker code set", "live=false",
                       "fail-closed proof fields", "main integration=false"],
        },
        "conclusion": (
            "The deduplicated direct-RAM_DL layout is a positive isolated "
            "capacity/atomicity prototype for the current 73-blob catalog, "
            "but the live game path is deliberately rejected until all "
            "translator hooks, raster/provider epochs, physical pages, ISR "
            "composition, full live-set capacity, final metadata wrapper, and "
            "hardware DMA/swap WCET are proved."),
    }
    report["analysis_sha256"] = _sha256(_json_bytes(report))
    return report


def validate_report(root: Path, report: Mapping[str, object]
                    ) -> dict[str, object]:
    """Cheap public gate for a later translator status stage.

    This does not rerun compilers or emulators.  It verifies the immutable
    report seal, every recorded input hash, the mandatory fail-closed blocker
    set, and the non-live status.  A caller must reject any exception.
    """
    root = Path(root).resolve()
    if report.get("format") != FORMAT or report.get("status") != STATUS:
        raise V4CheckError("v4 report format/status mismatch")
    if report.get("live") is not False:
        raise V4CheckError("v4 prototype report must remain live=false")
    claimed = report.get("analysis_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise V4CheckError("v4 report analysis_sha256 is missing")
    unsealed = dict(report)
    del unsealed["analysis_sha256"]
    actual = _sha256(_json_bytes(unsealed))
    if claimed != actual:
        raise V4CheckError("v4 report analysis_sha256 mismatch")
    rows = report.get("inputs")
    if not isinstance(rows, list) or len(rows) != len(INPUTS):
        raise V4CheckError("v4 report input inventory length mismatch")
    for expected_path, row in zip(INPUTS, rows):
        if not isinstance(row, dict) or row.get("path") != expected_path:
            raise V4CheckError(f"v4 report input order mismatch: {expected_path}")
        if row != _file_record(root, expected_path):
            raise V4CheckError(f"stale v4 input: {expected_path}")
    blockers = report.get("blockers")
    if not isinstance(blockers, list):
        raise V4CheckError("v4 blocker inventory is missing")
    codes = {row.get("code") for row in blockers if isinstance(row, dict)}
    if codes != REQUIRED_BLOCKER_CODES:
        raise V4CheckError("v4 mandatory blocker set mismatch")
    proofs = report.get("proofs")
    if not isinstance(proofs, dict):
        raise V4CheckError("v4 proof matrix is missing")
    required_false = {
        "full_translator_mutation_and_list_hooks",
        "real_scene_raster_provider_same_epoch",
        "immutable_fragment_provider_and_generation_owner",
        "physical_ts_page_ownership_and_cache_coherency",
        "ts_dma_and_swap_hardware_wcet",
        "game_isr_stack_bound_and_preemption_composition",
        "final_link_and_bank_placement",
        "target_asm_complete_double_shadow_metadata_transition",
    }
    if any(proofs.get(key) is not False for key in required_false):
        raise V4CheckError("v4 fail-closed proof boundary was relaxed")
    translator = report.get("main_translator_integration")
    if not isinstance(translator, dict) or translator.get("integrated") is not False:
        raise V4CheckError("v4 report unexpectedly claims main integration")
    return {
        "status": "valid",
        "analysis_sha256": claimed,
        "input_count": len(rows),
        "blocker_codes": sorted(codes),
        "live": False,
    }


def _selftest_validate_report(root: Path,
                              report: Mapping[str, object]) -> None:
    validate_report(root, report)

    def reseal(candidate: dict[str, object]) -> None:
        candidate.pop("analysis_sha256", None)
        candidate["analysis_sha256"] = _sha256(_json_bytes(candidate))

    def must_reject(candidate: dict[str, object], label: str) -> None:
        try:
            validate_report(root, candidate)
        except V4CheckError:
            return
        raise V4CheckError(f"validate_report accepted {label} tamper")

    broken_seal = json.loads(json.dumps(report))
    broken_seal["analysis_sha256"] = "0" * 64
    must_reject(broken_seal, "analysis seal")

    stale_input = json.loads(json.dumps(report))
    stale_input["inputs"][0]["sha256"] = "0" * 64
    reseal(stale_input)
    must_reject(stale_input, "input hash")

    missing_blocker = json.loads(json.dumps(report))
    missing_blocker["blockers"] = missing_blocker["blockers"][:-1]
    reseal(missing_blocker)
    must_reject(missing_blocker, "blocker set")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_ramdl_shadow_v4_status.json"))
    parser.add_argument("--check", action="store_true",
                        help="verify that --output is byte-exact and current")
    args = parser.parse_args()
    root = ROOT
    output = args.output if args.output.is_absolute() else root / args.output
    report = build_report(root)
    _selftest_validate_report(root, report)
    encoded = _json_bytes(report)
    if args.check:
        if not output.is_file():
            raise V4CheckError(f"missing v4 status: {output}")
        existing = json.loads(output.read_text(encoding="utf-8"))
        validate_report(root, existing)
        if output.read_bytes() != encoded:
            raise V4CheckError(f"stale or missing v4 status: {output}")
    else:
        _atomic_json(output, report)
    print(
        f"v4: active={report['layout']['active_catalog_cyclic_words']} words, "
        f"CODE={report['target_object']['code_bytes']} B, "
        f"DATA={report['target_object']['data_bytes']} B, "
        f"live={str(report['live']).lower()}, status={report['status']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except V4CheckError as error:
        print(f"v4 certificate failed: {error}", file=sys.stderr)
        raise SystemExit(1)
