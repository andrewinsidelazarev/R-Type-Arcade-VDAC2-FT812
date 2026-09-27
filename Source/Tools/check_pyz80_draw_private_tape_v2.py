#!/usr/bin/env python3
"""Certificate and pinned-Z80 timing for private-frame tape v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc
from test_pyz80_draw_private_tape_v2 import HARNESS, run_host_reference_matrix


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))
from tsconf_ft812_sim import TSConfFT812Machine  # noqa: E402


FORMAT = "pyz80-draw-private-frame-tape-v2-certificate-v2"
STATUS_PASS = "SINGLE_EVALUATION_PRIVATE_TAPE_PROVED_LIVE_BINDING_BLOCKED"
STATUS_TIMING = "SINGLE_EVALUATION_PRIVATE_TAPE_PROVED_TARGET_100K_MISSED"
CPU_HZ = 14_000_000
FRAME_HZ = 55
WHOLE_FRAME_TSTATES = CPU_HZ // FRAME_HZ
PREFLIGHT_TARGET_TSTATES = 100_000
MAX_Z80_INSTRUCTION_TSTATES = 23
PINNED_ARGUMENTS = (
    "-mz80", "--std-c11", "--sdcccall", "1",
    "--fno-omit-frame-pointer", "--stack-auto", "--opt-code-speed",
    "--no-c-code-in-asm",
)
LINK_ARGUMENTS = (
    "-mz80", "--no-std-crt0", "--code-loc", "0x2000",
    "--data-loc", "0xC000",
)
INPUTS = (
    "Source/C/ft812/pyz80_draw_private_tape_v2.c",
    "Source/C/ft812/pyz80_draw_private_tape_v2.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_draw_vm.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Source/Tools/test_pyz80_draw_private_tape_v2.py",
    "Source/Tools/check_pyz80_draw_private_tape_v2.py",
    "Source/Tools/rtype_python_compiler.json",
    "Build/rtype_python_full_hqt3_inventory_status.json",
    "Build/rtype_python_draw_atomic_frame_status.json",
)
OLD_REFERENCE_PATH = "Build/rtype_python_draw_atomic_frame_status.json"
FULL_INVENTORY_PATH = "Build/rtype_python_full_hqt3_inventory_status.json"
CUCKOO_ARTIFACT_PATH = "Build/rtype_python_hqt3_cuckoo_v2.bin"


BENCH_SOURCE = r'''
#include <stdint.h>
#include "pyz80_draw_private_tape_v2.h"
#include "rtype_python_hq_templates.h"

const PyZ80FtHQTemplate
    PyZ80FT_HQTemplates[PYZ80_FT_HQ_TEMPLATE_COUNT] = {{0}};
const uint8_t
    PyZ80FT_HQAppendMap[PYZ80_FT_HQ_APPEND_ENTRY_COUNT] = {{0}};
const uint32_t
    PyZ80FT_HQAppendAddress[PYZ80_FT_HQ_APPEND_BLOB_COUNT] = {{0}};
const uint16_t
    PyZ80FT_HQAppendSize[PYZ80_FT_HQ_APPEND_BLOB_COUNT] = {{4}};
uint8_t PyZ80FT_LowerNativeX(int16_t value, PyZ80FtLoweredCoord *result)
    PYZ80_CALL0
{{ (void)value; (void)result; return 0u; }}
uint8_t PyZ80FT_LowerNativeY(int16_t value, PyZ80FtLoweredCoord *result)
    PYZ80_CALL0
{{ (void)value; (void)result; return 0u; }}
uint8_t PyZ80FT_QueueAcquireFragment(
        volatile PyZ80FtQueue *queue, uint16_t sequence) PYZ80_CALL0
{{ (void)queue; (void)sequence; return 0u; }}

static volatile PyZ80DrawTapeV2Record
    tape[PYZ80_DRAW_TAPE_V2_MAX_RECORDS];
static PyZ80DrawTapeV2Result result;
static uint16_t vm_calls;
static uint16_t resolve_calls;
static uint16_t catalog_reads;
static uint16_t writer_records;
static uint16_t writer_chunks;
static uint8_t begin_should_fail;
static uint16_t append_calls;
static uint16_t commit_calls;
static uint16_t abort_calls;

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit,
        void *context, uint16_t *output_count)
{{
    rtype_python_draw_vm_record record;
    uint16_t index;
    (void)input;
    vm_calls++;
    for (index = 0u; index < 228u; ++index) {{
        record.bank_key = 0u;
        record.descriptor = 0u;
        record.anchor_x = (int16_t)(index - 100);
        record.anchor_y = (int16_t)(80 - index);
        if (emit(context, &record) == 0u) {{
            *output_count = index;
            return RTYPE_PYTHON_DRAW_VM_EMITTER;
        }}
    }}
    *output_count = 228u;
    return RTYPE_PYTHON_DRAW_VM_OK;
}}

static uint8_t catalog_read(void *context, uint16_t index,
                            PyZ80DrawTapeV2CatalogEntry *entry)
{{
    (void)context;
    if (index >= PYZ80_DRAW_TAPE_V2_CATALOG_KEYS) return 0u;
    catalog_reads++;
    entry->bank_key = 0u;
    entry->descriptor = (uint16_t)(index << 1);
    entry->template_index = index;
    return 1u;
}}

static uint8_t cuckoo_read(void *context, uint16_t slot,
                          PyZ80DrawTapeV2CatalogEntry *entry)
{{
    (void)context;
    catalog_reads++;
    if (slot == PYZ80_DRAW_TAPE_V2_CUCKOO_SEED1) {{
        entry->bank_key = 0u;
        entry->descriptor = 2u;
        entry->template_index = 1u;
    }} else if (slot == PYZ80_DRAW_TAPE_V2_CUCKOO_SEED2) {{
        entry->bank_key = 0u;
        entry->descriptor = 0u;
        entry->template_index = 0u;
    }} else {{
        entry->bank_key = 0xFFFFu;
        entry->descriptor = 0xFFFFu;
        entry->template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    }}
    return 1u;
}}

static uint8_t resolve_catalog(void *context,
        const rtype_python_draw_vm_record *record,
        PyZ80DrawTapeV2Resolution *resolved)
{{
    uint16_t found;
    uint8_t comparisons;
    (void)context;
    resolve_calls++;
    if (PyZ80DrawTapeV2_FindCatalogCuckoo(
            cuckoo_read, 0,
            record->bank_key, record->descriptor,
            &found, &comparisons) == 0u || comparisons != 2u)
        return 0u;
    resolved->template_index = found;
    resolved->append_expanded_words = 1u;
    return 1u;
}}

static uint8_t noop_emit(void *context,
        const rtype_python_draw_vm_record *record)
{{ (void)context; (void)record; return 1u; }}

static uint8_t writer_begin(void *context,
        const PyZ80DrawTapeV2Preflight *preflight)
{{ (void)context; (void)preflight; return begin_should_fail ? 0u : 1u; }}
static uint8_t writer_append(void *context,
        const volatile PyZ80DrawTapeV2Record *records,
        uint16_t count, uint16_t first)
{{
    (void)context;
    (void)records;
    if (first != writer_records) return 0u;
    append_calls++;
    writer_records = (uint16_t)(writer_records + count);
    writer_chunks++;
    return 1u;
}}
static uint8_t writer_commit(void *context,
        const PyZ80DrawTapeV2Preflight *preflight)
{{ (void)context; (void)preflight; commit_calls++; return 1u; }}
static void writer_abort(void *context)
{{ (void)context; abort_calls++; }}

static uint8_t run_gate(uint8_t preflight_only)
{{
    rtype_python_draw_vm_input input;
    PyZ80DrawTapeV2Certificate certificate;
    PyZ80DrawTapeV2FrameBudget budget;
    PyZ80DrawTapeV2Writer writer;
    PyZ80DrawTapeV2Status status;
    input.objects = 0;
    input.object_count = 0u;
    input.load_object = 0;
    input.object_context = 0;
    input.transients = 0;
    input.transient_count = 0u;
    input.resolve_resource_type = 0;
    input.resource_context = 0;
    input.resolve_bank_key = 0;
    input.bank_context = 0;
    certificate.format_version = PYZ80_DRAW_TAPE_V2_CERTIFICATE_VERSION;
    certificate.sizing_proof_complete = 1u;
    certificate.catalog_order_unique_proved = 1u;
    certificate.catalog_cuckoo_layout_proved = 1u;
    certificate.raster_768_lines_proved = 1u;
    certificate.catalog_key_count = PYZ80_DRAW_TAPE_V2_CATALOG_KEYS;
    certificate.catalog_max_comparisons =
        PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS;
    certificate.catalog_max_runtime_reads =
        PYZ80_DRAW_TAPE_V2_CUCKOO_MAX_READS;
    certificate.certified_max_records = PYZ80_DRAW_TAPE_V2_MAX_RECORDS;
    certificate.max_cmd_append_expanded_words = 228u;
    certificate.max_fragment_expanded_dl_words = 710u;
    certificate.worst_raster_line = 0u;
    certificate.worst_raster_cycles = 0u;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_TAPE_V2_SAFE_LINE_CYCLES;
    writer.begin = writer_begin;
    writer.append = writer_append;
    writer.commit = writer_commit;
    writer.abort = writer_abort;
    writer.context = 0;
    vm_calls = 0u;
    resolve_calls = 0u;
    catalog_reads = 0u;
    writer_records = 0u;
    writer_chunks = 0u;
    append_calls = 0u;
    commit_calls = 0u;
    abort_calls = 0u;
    begin_should_fail = preflight_only;
    status = PyZ80DrawTapeV2_Run(
        &input, &certificate, &budget, resolve_catalog, 0,
        tape, PYZ80_DRAW_TAPE_V2_MAX_RECORDS, &writer, &result);
    if (vm_calls != 1u || resolve_calls != 228u ||
            catalog_reads != 456u || result.evaluated_records != 228u)
        return 0u;
    if (preflight_only)
        return (uint8_t)(status == PYZ80_DRAW_TAPE_V2_WRITER_BEGIN &&
            abort_calls == 1u && append_calls == 0u && commit_calls == 0u &&
            result.committed == 0u);
    return (uint8_t)(status == PYZ80_DRAW_TAPE_V2_OK &&
        append_calls == 2u && writer_records == 228u &&
        writer_chunks == 2u && commit_calls == 1u && abort_calls == 0u &&
        result.committed == 1u);
}}

uint8_t PyZ80TapeV2Bench_Noop(void) PYZ80_CALL0
{{ return 1u; }}
uint8_t PyZ80TapeV2Bench_VMOnly(void) PYZ80_CALL0
{{
    rtype_python_draw_vm_input input;
    uint16_t count;
    vm_calls = 0u;
    if (rtype_python_draw_vm_stream(&input, noop_emit, 0, &count) !=
            RTYPE_PYTHON_DRAW_VM_OK) return 0u;
    return (uint8_t)(count == 228u && vm_calls == 1u);
}}
uint8_t PyZ80TapeV2Bench_Catalog228(void) PYZ80_CALL0
{{
    uint16_t iteration;
    uint16_t found;
    uint8_t comparisons;
    catalog_reads = 0u;
    for (iteration = 0u; iteration < 228u; ++iteration) {{
        if (PyZ80DrawTapeV2_FindCatalogBounded(
                catalog_read, 0, PYZ80_DRAW_TAPE_V2_CATALOG_KEYS,
                0u, 0u, &found, &comparisons) == 0u ||
                found != 0u || comparisons != 14u) return 0u;
    }}
    return (uint8_t)(catalog_reads == 3192u);
}}
uint8_t PyZ80TapeV2Bench_Cuckoo228(void) PYZ80_CALL0
{{
    uint16_t iteration;
    uint16_t found;
    uint8_t reads;
    catalog_reads = 0u;
    for (iteration = 0u; iteration < 228u; ++iteration) {{
        if (PyZ80DrawTapeV2_FindCatalogCuckoo(
                cuckoo_read, 0, 0u, 0u, &found, &reads) == 0u ||
                found != 0u || reads != 2u) return 0u;
    }}
    return (uint8_t)(catalog_reads == 456u);
}}
uint8_t PyZ80TapeV2Bench_Preflight(void) PYZ80_CALL0
{{ return run_gate(1u); }}
uint8_t PyZ80TapeV2Bench_Full(void) PYZ80_CALL0
{{ return run_gate(0u); }}
'''


class DrawPrivateTapeV2CheckError(RuntimeError):
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


def _run(command: list[str], directory: Path, environment: Mapping[str, str],
         timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=directory, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=dict(environment))
    if completed.returncode != 0:
        raise DrawPrivateTapeV2CheckError(
            f"command failed ({completed.returncode}): " +
            " ".join(command) + "\n" + completed.stdout)
    return completed


def _areas(text: str) -> dict[str, int]:
    return {match.group(1): int(match.group(2), 16) for match in re.finditer(
        r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+", text, re.MULTILINE)}


def _map_area(text: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"^{re.escape(name)}\s+([0-9A-Fa-f]{{8}})\s+"
        rf"([0-9A-Fa-f]{{8}})\s+=", text, re.MULTILINE)
    if match is None:
        raise DrawPrivateTapeV2CheckError(f"linked map lacks {name}")
    return int(match.group(1), 16), int(match.group(2), 16)


def _symbols(text: str) -> dict[str, int]:
    result = {match.group(2): int(match.group(1), 16) for match in re.finditer(
        r"^\s*([0-9A-Fa-f]{8})\s+_"
        r"(PyZ80TapeV2Bench_(?:Noop|VMOnly|Catalog228|Cuckoo228|Preflight|Full))\s+",
        text, re.MULTILINE)}
    expected = {
        "PyZ80TapeV2Bench_Noop", "PyZ80TapeV2Bench_VMOnly",
        "PyZ80TapeV2Bench_Catalog228", "PyZ80TapeV2Bench_Cuckoo228",
        "PyZ80TapeV2Bench_Preflight", "PyZ80TapeV2Bench_Full",
    }
    if set(result) != expected:
        raise DrawPrivateTapeV2CheckError(
            "benchmark map symbols missing: " +
            ", ".join(sorted(expected - set(result))))
    return result


def _parse_ihx(path: Path) -> list[tuple[int, bytes]]:
    upper = 0
    blocks: list[tuple[int, bytes]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count = raw[0]
        address = (raw[1] << 8) | raw[2]
        kind = raw[3]
        payload = raw[4:4 + count]
        if kind == 0:
            blocks.append((upper + address, payload))
        elif kind == 4:
            upper = int.from_bytes(payload, "big") << 16
        elif kind == 1:
            break
    return blocks


def _local_frame(assembly: str, symbol: str) -> int:
    match = re.search(
        rf"(?ms)^_{re.escape(symbol)}::?\s*$.*?"
        r"\bld\s+iy,\s*#-([0-9]+)\s*$.*?\badd\s+iy,\s*sp\s*$.*?"
        r"\bld\s+sp,\s*iy\s*$", assembly)
    if match is None:
        raise DrawPrivateTapeV2CheckError(
            f"cannot bind local stack frame for {symbol}")
    return int(match.group(1))


def _compile_target(root: Path, sdcc: Path,
                    environment: Mapping[str, str]) -> dict[str, object]:
    copied = INPUTS[:2] + (
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    with tempfile.TemporaryDirectory(prefix="pyz80-private-tape-v2-obj-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", "pyz80_draw_private_tape_v2.c"]
        completed = _run(command, directory, environment)
        rel = (directory / "pyz80_draw_private_tape_v2.rel").read_bytes()
        asm = (directory / "pyz80_draw_private_tape_v2.asm").read_bytes()
    areas = _areas(rel.decode("latin1"))
    code = areas.get("_CODE", -1)
    data = areas.get("_DATA", -1)
    if not 0 < code < 0x4000 or data != 0:
        raise DrawPrivateTapeV2CheckError("v2 object CODE/DATA contract failed")
    frame = _local_frame(asm.decode("latin1"), "PyZ80DrawTapeV2_Run")
    return {
        "command": command,
        "compiler_output": completed.stdout.strip(),
        "object_sha256": _sha256(rel),
        "assembly_sha256": _sha256(asm),
        "code_bytes": code,
        "data_bytes": data,
        "single_16k_bank_headroom_bytes": 0x4000 - code,
        "run_automatic_local_frame_bytes": frame,
    }


def _benchmark(root: Path, sdcc: Path,
               environment: Mapping[str, str]) -> dict[str, object]:
    copied = INPUTS[:2] + (
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    with tempfile.TemporaryDirectory(prefix="pyz80-private-tape-v2-bench-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "private_tape_v2_bench.c").write_text(
            BENCH_SOURCE, encoding="utf-8", newline="\n")
        for source_name in (
                "pyz80_draw_private_tape_v2.c", "private_tape_v2_bench.c"):
            _run([str(sdcc), *PINNED_ARGUMENTS, "-c", source_name],
                 directory, environment)
        link_command = [str(sdcc), *LINK_ARGUMENTS,
                        "-o", "private_tape_v2_bench.ihx",
                        "pyz80_draw_private_tape_v2.rel",
                        "private_tape_v2_bench.rel"]
        _run(link_command, directory, environment)
        ihx = directory / "private_tape_v2_bench.ihx"
        map_path = directory / "private_tape_v2_bench.map"
        ihx_bytes = ihx.read_bytes()
        map_bytes = map_path.read_bytes()
        map_text = map_bytes.decode("latin1")
        symbols = _symbols(map_text)
        code_start, code_bytes = _map_area(map_text, "_CODE")
        data_start, data_bytes = _map_area(map_text, "_DATA")
        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x2000",
            default_stack="0xFF00")
        for address, payload in _parse_ihx(ihx):
            if address + len(payload) > 0x10000:
                raise DrawPrivateTapeV2CheckError("benchmark exceeds Z80 space")
            machine.mem.write_block_linear(address, payload)

        measurements: dict[str, dict[str, int]] = {}
        original_step = machine.step
        minimum_sp = machine.reg.SP

        def tracked_step() -> int:
            nonlocal minimum_sp
            clocks = original_step()
            minimum_sp = min(minimum_sp, machine.reg.SP)
            return clocks

        machine.step = tracked_step  # type: ignore[method-assign]
        for public, symbol in (
                ("noop", "PyZ80TapeV2Bench_Noop"),
                ("vm_228", "PyZ80TapeV2Bench_VMOnly"),
                ("catalog_228_worst14", "PyZ80TapeV2Bench_Catalog228"),
                ("cuckoo_228_worst2", "PyZ80TapeV2Bench_Cuckoo228"),
                ("preflight_228", "PyZ80TapeV2Bench_Preflight"),
                ("full_private_commit_228", "PyZ80TapeV2Bench_Full")):
            initial_sp = machine.reg.SP
            minimum_sp = initial_sp
            before = machine.tstates
            steps = machine.call(symbols[symbol], max_steps=10_000_000)
            tstates = machine.tstates - before
            if machine.reg.L != 1 or machine.reg.SP != initial_sp:
                raise DrawPrivateTapeV2CheckError(
                    f"benchmark {public} failed/result/SP mismatch")
            measurements[public] = {
                "steps": steps,
                "tstates": tstates,
                "stack_bytes_including_outer_return": initial_sp - minimum_sp,
                "conservative_reference_path_bound_tstates":
                    steps * MAX_Z80_INSTRUCTION_TSTATES,
            }

    baseline = measurements["noop"]["tstates"]
    for name, row in measurements.items():
        row["net_tstates"] = max(0, row["tstates"] - baseline)
    preflight = measurements["preflight_228"]["net_tstates"]
    full = measurements["full_private_commit_228"]["net_tstates"]
    vm = measurements["vm_228"]["net_tstates"]
    catalog = measurements["catalog_228_worst14"]["net_tstates"]
    cuckoo = measurements["cuckoo_228_worst2"]["net_tstates"]
    return {
        "benchmark_source_sha256": _sha256(BENCH_SOURCE.encode("utf-8")),
        "link_command": link_command,
        "linked_image": {
            "ihx_bytes": len(ihx_bytes), "ihx_sha256": _sha256(ihx_bytes),
            "map_bytes": len(map_bytes), "map_sha256": _sha256(map_bytes),
            "code_start_hex": f"0x{code_start:04X}", "code_bytes": code_bytes,
            "data_start_hex": f"0x{data_start:04X}", "data_bytes": data_bytes,
            "symbols": {key: f"0x{value:04X}"
                        for key, value in sorted(symbols.items())},
        },
        "measurements": measurements,
        "breakdown": {
            "vm_stream_228_reference_net_tstates": vm,
            "catalog_228_times_14_reads_net_tstates": catalog,
            "cuckoo_228_times_2_reads_net_tstates": cuckoo,
            "single_evaluation_preflight_net_tstates": preflight,
            "full_private_tape_and_commit_net_tstates": full,
            "preflight_residual_after_separate_vm_and_catalog":
                preflight - vm - cuckoo,
            "private_tape_replay_and_commit_delta": full - preflight,
        },
        "target": {
            "cpu_hz": CPU_HZ,
            "frame_hz": FRAME_HZ,
            "whole_frame_tstates": WHOLE_FRAME_TSTATES,
            "preflight_target_tstates": PREFLIGHT_TARGET_TSTATES,
            "measured_preflight_tstates": preflight,
            "met": preflight <= PREFLIGHT_TARGET_TSTATES,
            "fraction_of_whole_frame": round(preflight / WHOLE_FRAME_TSTATES, 6),
        },
    }


def _static_checks(source: str, header: str) -> dict[str, bool]:
    checks = {
        "tape_record_is_compile_time_8_bytes":
            "sizeof(PyZ80DrawTapeV2Record) == 8" in source,
        "maximum_tape_is_1824_bytes":
            "PYZ80_DRAW_TAPE_V2_MAX_BYTES == 1824u" in source,
        "draw_vm_called_exactly_once_in_gate_source":
            source.count("rtype_python_draw_vm_stream(") == 1,
        "identity_resolver_called_only_in_tape_emitter":
            source.count("state->resolve(") == 1,
        "physical_writer_does_not_call_catalog_resolver":
            "PyZ80DrawTapeV2_FindCatalogBounded" not in
            source[source.find("PyZ80DrawTapeV2_ResolvePhysical"):],
        "catalog_bound_is_10776":
            "PYZ80_DRAW_TAPE_V2_CATALOG_KEYS 10776u" in header,
        "binary_lookup_bound_is_14":
            "PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS 14u" in header,
        "cuckoo_hot_lookup_bound_is_2":
            "PYZ80_DRAW_TAPE_V2_CUCKOO_MAX_READS 2u" in header and
            source.count("read_slot(context,") == 2,
        "cuckoo_fixed_table_is_32768_slots":
            "PYZ80_DRAW_TAPE_V2_CUCKOO_SLOTS 32768u" in header,
        "catalog_has_no_linear_increment_scan":
            "middle + 1u" in source and "low++" not in source,
        "strict_ram_dl_less_than_2048":
            "total_words >= budget->ram_dl_word_limit" in source,
        "fixed_1209_limit":
            "PYZ80_DRAW_TAPE_V2_SAFE_LINE_CYCLES 1209u" in header,
        "single_ready_publication_store": len(re.findall(
            r"header\.state\s*=\s*PYZ80_FT_QUEUE_READY\s*;", source)) == 1,
    }
    if not all(checks.values()):
        raise DrawPrivateTapeV2CheckError(
            "v2 static checks failed: " + ", ".join(
                key for key, value in checks.items() if not value))
    return checks


def _cuckoo_hashes(bank: int, descriptor: int) -> tuple[int, int]:
    bank1 = (bank + ((bank << 8) & 0xFFFF)) & 0xFFFF
    first = (descriptor ^ (descriptor >> 7) ^ bank1 ^ 0x3594) & 0x7FFF
    rotated = ((descriptor << 5) | (descriptor >> 11)) & 0xFFFF
    bank2 = (bank + ((bank << 4) & 0xFFFF)) & 0xFFFF
    second = (rotated ^ bank2 ^ 0x729C) & 0x7FFF
    return first, second


def _build_cuckoo_layout(root: Path) -> tuple[bytes, dict[str, object]]:
    inventory_bytes = (root / FULL_INVENTORY_PATH).read_bytes()
    inventory = json.loads(inventory_bytes.decode("utf-8"))
    try:
        rows = inventory["global_catalog"]["templates"]
        declared_count = inventory["global_catalog"]["template_count"]
        declared_hash = inventory["global_catalog"]["template_rows_sha256"]
    except (KeyError, TypeError) as exc:
        raise DrawPrivateTapeV2CheckError(
            "full HQT3 inventory lacks global catalog") from exc
    if not isinstance(rows, list) or declared_count != 10776 or len(rows) != 10776:
        raise DrawPrivateTapeV2CheckError("full HQT3 catalog is not 10,776 rows")
    keys: list[tuple[int, int, int]] = []
    for index, row in enumerate(rows):
        try:
            bank = int(row["bank"]["encoded_hqt3_key"])
            descriptor = int(row["descriptor"]["address"])
            template = int(row["template_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DrawPrivateTapeV2CheckError(
                f"invalid full HQT3 row {index}") from exc
        if template != index or not 0 <= bank <= 0xFFFF or not 0 <= descriptor <= 0xFFFF:
            raise DrawPrivateTapeV2CheckError(
                f"full HQT3 row/index/range mismatch at {index}")
        keys.append((bank, descriptor, template))
    key_pairs = [(bank, descriptor) for bank, descriptor, _ in keys]
    if len(set(key_pairs)) != len(key_pairs) or key_pairs != sorted(key_pairs):
        raise DrawPrivateTapeV2CheckError(
            "full HQT3 catalog is not strictly sorted and unique")

    endpoints = [_cuckoo_hashes(bank, descriptor)
                 for bank, descriptor, _ in keys]
    if any(first == second for first, second in endpoints):
        raise DrawPrivateTapeV2CheckError("cuckoo key has identical choices")
    slot_to_edge = [-1] * 32768
    seen = [0] * 32768
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100_000))

    def place(edge: int, stamp: int) -> bool:
        for slot in endpoints[edge]:
            if seen[slot] == stamp:
                continue
            seen[slot] = stamp
            occupant = slot_to_edge[slot]
            if occupant < 0 or place(occupant, stamp):
                slot_to_edge[slot] = edge
                return True
        return False

    for edge in range(len(keys)):
        if not place(edge, edge + 1):
            raise DrawPrivateTapeV2CheckError(
                f"fixed cuckoo seeds cannot place catalog edge {edge}")
    edge_to_slot = [-1] * len(keys)
    for slot, edge in enumerate(slot_to_edge):
        if edge >= 0:
            if edge_to_slot[edge] >= 0:
                raise DrawPrivateTapeV2CheckError("cuckoo edge assigned twice")
            edge_to_slot[edge] = slot
    if any(slot < 0 for slot in edge_to_slot):
        raise DrawPrivateTapeV2CheckError("cuckoo placement lost a key")
    binary = bytearray(b"\xFF" * (32768 * 6))
    first_choice = 0
    second_choice = 0
    for edge, (bank, descriptor, template) in enumerate(keys):
        slot = edge_to_slot[edge]
        if slot == endpoints[edge][0]:
            first_choice += 1
        elif slot == endpoints[edge][1]:
            second_choice += 1
        else:
            raise DrawPrivateTapeV2CheckError("cuckoo placement uses alien slot")
        struct.pack_into("<HHH", binary, slot * 6,
                         bank, descriptor, template)
    table = bytes(binary)
    # Re-run the exact runtime two-read rule against every source key.
    maximum_reads = 0
    for bank, descriptor, template in keys:
        first, second = _cuckoo_hashes(bank, descriptor)
        row1 = struct.unpack_from("<HHH", table, first * 6)
        if row1 == (bank, descriptor, template):
            reads = 1
        else:
            row2 = struct.unpack_from("<HHH", table, second * 6)
            if row2 != (bank, descriptor, template):
                raise DrawPrivateTapeV2CheckError(
                    f"cuckoo runtime lookup misses template {template}")
            reads = 2
        maximum_reads = max(maximum_reads, reads)
    if maximum_reads != 2:
        raise DrawPrivateTapeV2CheckError("cuckoo worst-case is not exactly 2")
    report = {
        "source_inventory_path": FULL_INVENTORY_PATH,
        "source_inventory_sha256": _sha256(inventory_bytes),
        "source_template_rows_sha256": declared_hash,
        "keys": len(keys),
        "slots": 32768,
        "slot_bytes": 6,
        "table_bytes": len(table),
        "load_factor": round(len(keys) / 32768, 9),
        "seed1_hex": "0x3594",
        "seed2_hex": "0x729C",
        "first_choice_keys": first_choice,
        "second_choice_keys": second_choice,
        "maximum_runtime_reads": maximum_reads,
        "strict_source_order_and_uniqueness_proved": True,
        "all_source_keys_placed_once": True,
        "exhaustive_runtime_lookup_replay_passed": True,
        "artifact_path": CUCKOO_ARTIFACT_PATH,
        "artifact_sha256": _sha256(table),
    }
    return table, report


def _atomic_binary(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def probe(project_root: Path | str = ROOT) -> dict[str, object]:
    root = Path(project_root).resolve()
    manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(manifest.target).resolve()
    sdcc_bytes = sdcc.read_bytes()
    if _sha256(sdcc_bytes).upper() != manifest.target.toolchain_sha256.upper():
        raise DrawPrivateTapeV2CheckError("SDCC hash does not match manifest")
    environment = os.environ.copy()
    environment["PATH"] = str(sdcc.parent) + os.pathsep + environment.get("PATH", "")
    version = _run([str(sdcc), "--version"], root, environment).stdout.splitlines()[0]
    inputs = [_file_record(root, relative) for relative in INPUTS]
    source = (root / INPUTS[0]).read_text(encoding="utf-8")
    header = (root / INPUTS[1]).read_text(encoding="utf-8")
    static = _static_checks(source, header)
    host = run_host_reference_matrix(root)
    cuckoo_binary, cuckoo = _build_cuckoo_layout(root)
    _atomic_binary(root / CUCKOO_ARTIFACT_PATH, cuckoo_binary)
    target = _compile_target(root, sdcc, environment)
    timing = _benchmark(root, sdcc, environment)
    timing_met = bool(timing["target"]["met"])
    status = STATUS_PASS if timing_met else STATUS_TIMING
    old = json.loads((root / OLD_REFERENCE_PATH).read_text(encoding="utf-8"))
    old_tstates = int(old["timing_certificate"]
                      ["reference_228_record_two_pass"]
                      ["measured_tstates_including_reference_callbacks"])
    new_full = int(timing["breakdown"]["full_private_tape_and_commit_net_tstates"])
    checks = {
        **static,
        **{key: bool(value) for key, value in host["matrix"].items()},
        "pinned_sdcc_object_compiled": True,
        "pinned_sdcc_code_fits_one_16k_bank": True,
        "pinned_sdcc_mutable_data_zero": True,
        "old_double_replay_reference_preserved": True,
        "single_evaluation_faster_than_old_double_replay": new_full < old_tstates,
        "preflight_at_most_100000_tstates": timing_met,
        "actual_10776_catalog_content_bound": True,
        "actual_cuckoo_layout_exhaustively_proved": True,
        "cuckoo_runtime_reads_at_most_two": True,
        "actual_banked_catalog_reader_wcet_bound": False,
        "scratch_ts_ram_page_final_binding": False,
        "final_hqt3_ram_g_and_link_binding": False,
        "live_vm_provider_wcet_stack_bound": False,
    }
    payload = {
        "input_sha256": {row["path"]: row["sha256"] for row in inputs},
        "compiler_sha256": _sha256(sdcc_bytes),
        "target": target,
        "host_matrix": host["matrix"],
        "cuckoo_layout": cuckoo,
        "timing": timing,
        "old_reference_tstates": old_tstates,
        "checks": checks,
    }
    return {
        "format": FORMAT,
        "status": status,
        "semantic_sha256": _sha256(_json_bytes(payload)),
        "input": {"files": inputs,
                  "test_harness_sha256": _sha256(HARNESS.encode("utf-8")),
                  "semantic_payload": payload},
        "architecture": {
            "vm_evaluations_per_frame": 1,
            "hqt_identity_resolutions_per_record": 1,
            "second_vm_or_identity_lookup": False,
            "private_tape_record_bytes": 8,
            "private_tape_max_records": 228,
            "private_tape_max_bytes": 1824,
            "scratch_memory": "mapped TS-Config RAM within 4 MiB; never RAM_G",
            "catalog_keys": 10776,
            "catalog_lookup": "binary indexed banked-reader callback",
            "catalog_fallback_max_comparisons": 14,
            "catalog_hot_lookup": "fixed two-choice cuckoo table",
            "catalog_hot_max_reads": 2,
            "catalog_table_bytes_in_ts_ram": 196608,
            "publication": "one READY store after complete private replay",
        },
        "host_reference_tests": host,
        "compiler": {"path": sdcc.as_posix(), "bytes": len(sdcc_bytes),
                     "sha256": _sha256(sdcc_bytes), "version": version,
                     "arguments": list(PINNED_ARGUMENTS)},
        "target_object": target,
        "cuckoo_catalog": cuckoo,
        "z80_timing": timing,
        "comparison_to_v1": {
            "v1_status_path": OLD_REFERENCE_PATH,
            "v1_measured_228_double_replay_tstates": old_tstates,
            "v2_measured_full_private_commit_tstates": new_full,
            "speedup": round(old_tstates / new_full, 6),
        },
        "checks": checks,
        "live": False,
        "live_blockers": [
            {"code": "PZTV201", "detail": (
                f"measured single-evaluation preflight is "
                f"{timing['target']['measured_preflight_tstates']} tstates; "
                f"target is <= {PREFLIGHT_TARGET_TSTATES}")}
            if not timing_met else
            {"code": "PZTV201", "detail": (
                "timing target passes only with synthetic reader; live WCET "
                "is not yet bound")},
            {"code": "PZTV202", "detail": (
                "the actual banked 10,776-entry catalog reader and its page "
                "switch WCET are not linked")},
            {"code": "PZTV203", "detail": (
                "the proved 196,608-byte cuckoo artifact is not yet assigned "
                "to production TS pages or selected level working sets")},
            {"code": "PZTV204", "detail": (
                "the 1,824-byte tape has no final physical TS RAM scratch "
                "page assignment or ISR ownership contract")},
            {"code": "PZTV205", "detail": (
                "final HQT3 RAM_G residency, generated phase tables and "
                "production bank link are absent")},
            {"code": "PZTV206", "detail": (
                "the translated live VM/provider stack and WCET are not "
                "substituted for the deterministic benchmark provider")},
        ],
    }


def validate_report(report: object, project_root: Path | str = ROOT) -> None:
    if not isinstance(report, dict) or report.get("format") != FORMAT:
        raise DrawPrivateTapeV2CheckError("v2 report format mismatch")
    if (report.get("status") not in (STATUS_PASS, STATUS_TIMING) or
            report.get("live") is not False):
        raise DrawPrivateTapeV2CheckError("v2 report status/live mismatch")
    payload = report.get("input", {}).get("semantic_payload")  # type: ignore[union-attr]
    if not isinstance(payload, dict) or report.get("semantic_sha256") != _sha256(
            _json_bytes(payload)):
        raise DrawPrivateTapeV2CheckError("v2 report semantic hash mismatch")
    root = Path(project_root).resolve()
    rows = report.get("input", {}).get("files")  # type: ignore[union-attr]
    if not isinstance(rows, list) or len(rows) != len(INPUTS):
        raise DrawPrivateTapeV2CheckError("v2 report input set mismatch")
    for row, relative in zip(rows, INPUTS):
        if row != _file_record(root, relative):
            raise DrawPrivateTapeV2CheckError(f"stale v2 input: {relative}")
    timing = report.get("z80_timing")
    if not isinstance(timing, dict):
        raise DrawPrivateTapeV2CheckError("v2 timing missing")
    met = bool(timing.get("target", {}).get("met"))
    if report.get("status") != (STATUS_PASS if met else STATUS_TIMING):
        raise DrawPrivateTapeV2CheckError("v2 timing/status disagreement")
    cuckoo = report.get("cuckoo_catalog")
    if not isinstance(cuckoo, dict):
        raise DrawPrivateTapeV2CheckError("v2 cuckoo certificate missing")
    artifact = root / CUCKOO_ARTIFACT_PATH
    data = artifact.read_bytes()
    if (len(data) != 196608 or cuckoo.get("table_bytes") != len(data) or
            cuckoo.get("artifact_sha256") != _sha256(data) or
            cuckoo.get("maximum_runtime_reads") != 2):
        raise DrawPrivateTapeV2CheckError("v2 cuckoo artifact is stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
        default=Path("Build/rtype_python_draw_private_tape_v2_status.json"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        result = probe(ROOT)
        validate_report(result, ROOT)
        _atomic_json(output, result)
    except (DrawPrivateTapeV2CheckError, OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    target = result["z80_timing"]["target"]
    breakdown = result["z80_timing"]["breakdown"]
    print(
        f"Private tape v2: CODE={result['target_object']['code_bytes']} B, "
        f"tape=1824 B, preflight={target['measured_preflight_tstates']} "
        f"tstates/{PREFLIGHT_TARGET_TSTATES}, full="
        f"{breakdown['full_private_tape_and_commit_net_tstates']}; "
        f"status={result['status']}, live=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
