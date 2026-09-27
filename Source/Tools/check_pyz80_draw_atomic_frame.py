#!/usr/bin/env python3
"""Reproduce the fail-closed C certificate for atomic whole-frame draw commit.

The certificate is intentionally target-neutral and ``live=false``.  It proves
the two-pass protocol, concrete inactive FT812 queue writer, pinned-SDCC object
size, and a 228-record reference execution.  Immutable gameplay providers,
final HQT3 residency, final banking/linking, ISR composition, and their callback
WCET/stack contracts remain separate live-integration obligations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc
from test_pyz80_draw_atomic_frame import HARNESS, run_host_reference_matrix


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine  # noqa: E402


FORMAT = "pyz80-draw-atomic-frame-c-certificate-v1"
STATUS = "TWO_PASS_ATOMIC_FRAME_C_PROVED_LIVE_BINDING_BLOCKED"
CPU_HZ = 14_000_000
MAXIMUM_Z80_INSTRUCTION_TSTATES = 23
PINNED_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
)
LINK_ARGUMENTS = (
    "-mz80",
    "--no-std-crt0",
    "--code-loc", "0x2000",
    "--data-loc", "0xC000",
)
INPUTS = (
    "Source/C/ft812/pyz80_draw_atomic_frame.c",
    "Source/C/ft812/pyz80_draw_atomic_frame.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_draw_vm.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Source/Tools/test_pyz80_draw_atomic_frame.py",
    "Source/Tools/check_pyz80_draw_atomic_frame.py",
    "Source/Tools/rtype_python_compiler.json",
)


BENCH_SOURCE = r'''
#include <stdint.h>
#include "pyz80_draw_atomic_frame.h"
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
uint16_t PyZ80FT_FindHQTemplate(uint16_t bank, uint16_t descriptor)
    PYZ80_CALL0
{{ (void)bank; (void)descriptor; return PYZ80_FT_HQ_TEMPLATE_NOT_FOUND; }}
uint8_t PyZ80FT_QueueAcquireFragment(
        volatile PyZ80FtQueue *queue, uint16_t sequence)
    PYZ80_CALL0
{{ (void)queue; (void)sequence; return 0u; }}

static uint16_t raster[PYZ80_DRAW_ATOMIC_RASTER_LINES];
static PyZ80FtTemplateDrawRecord
    chunk[PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS];
static PyZ80DrawAtomicResult result;
static uint16_t vm_calls;
static uint16_t resolve_calls;
static uint16_t begin_calls;
static uint16_t append_calls;
static uint16_t commit_calls;
static uint16_t abort_calls;
static uint16_t appended_records;

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
        record.bank_key = (uint16_t)(0x0100u + (index & 15u));
        record.descriptor = (uint16_t)(0x2000u + index);
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

static uint8_t bench_prepare(void *context, uint8_t pass, uint32_t *token)
{{ (void)context; (void)pass; *token = 0x8120A55Aul; return 1u; }}

static uint8_t bench_resolve(void *context,
        const rtype_python_draw_vm_record *record,
        PyZ80DrawAtomicResolvedRecord *resolved)
{{
    (void)context;
    (void)record;
    resolve_calls++;
    resolved->template_index = 0u;
    resolved->append_expanded_words = 1u;
    return 1u;
}}

static uint8_t bench_begin(void *context,
        const PyZ80DrawAtomicPreflight *preflight)
{{ (void)context; (void)preflight; begin_calls++; return 1u; }}

static uint8_t bench_append(void *context,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first)
{{
    (void)context;
    (void)records;
    if (first != appended_records) return 0u;
    append_calls++;
    appended_records = (uint16_t)(appended_records + count);
    return 1u;
}}

static uint8_t bench_commit(void *context,
        const PyZ80DrawAtomicPreflight *preflight)
{{ (void)context; (void)preflight; commit_calls++; return 1u; }}
static void bench_abort(void *context)
{{ (void)context; abort_calls++; }}

uint8_t PyZ80AtomicBench_Noop(void) PYZ80_CALL0
{{ return 1u; }}

uint8_t PyZ80AtomicBench_Run(void) PYZ80_CALL0
{{
    rtype_python_draw_vm_input input;
    PyZ80DrawAtomicCertificate certificate;
    PyZ80DrawAtomicFrameBudget budget;
    PyZ80DrawAtomicReplay replay;
    PyZ80DrawAtomicWriter writer;
    PyZ80DrawAtomicStatus status;
    uint16_t index;
    uint16_t chunk_count = 2u;
    uint16_t fragment_words = 710u;
    for (index = 0u; index < PYZ80_DRAW_ATOMIC_RASTER_LINES; ++index)
        raster[index] = 0u;
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
    certificate.format_version = PYZ80_DRAW_ATOMIC_CERTIFICATE_VERSION;
    certificate.sizing_proof_complete = 1u;
    certificate.certified_max_records = 228u;
    certificate.chunk_capacity_records = 128u;
    certificate.max_chunks = chunk_count;
    certificate.max_cmd_append_expanded_words = 228u;
    certificate.max_fragment_expanded_dl_words = fragment_words;
    certificate.raster_cycles_by_line = raster;
    certificate.raster_line_count = PYZ80_DRAW_ATOMIC_RASTER_LINES;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_ATOMIC_SAFE_LINE_CYCLES;
    replay.prepare = bench_prepare;
    replay.context = 0;
    writer.begin = bench_begin;
    writer.append = bench_append;
    writer.commit = bench_commit;
    writer.abort = bench_abort;
    writer.context = 0;
    vm_calls = 0u;
    resolve_calls = 0u;
    begin_calls = 0u;
    append_calls = 0u;
    commit_calls = 0u;
    abort_calls = 0u;
    appended_records = 0u;
    status = PyZ80DrawAtomic_Run(
        &input, &certificate, &budget, bench_resolve, 0, &replay, &writer,
        chunk, PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS, &result);
    return (uint8_t)(status == PYZ80_DRAW_ATOMIC_OK &&
        result.committed == 1u && result.pass_a_records == 228u &&
        result.pass_b_records == 228u &&
        result.preflight.chunk_count == 2u &&
        result.preflight.fragment_expanded_dl_words == 710u &&
        vm_calls == 2u && resolve_calls == 456u && begin_calls == 1u &&
        append_calls == 2u && commit_calls == 1u && abort_calls == 0u &&
        appended_records == 228u);
}}
'''


class DrawAtomicFrameCheckError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")


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


def _area_map(text: str) -> dict[str, int]:
    return {
        match.group(1): int(match.group(2), 16)
        for match in re.finditer(
            r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+",
            text, re.MULTILINE)
    }


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


def _map_symbols(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for match in re.finditer(
            r"^\s*([0-9A-Fa-f]{8})\s+_"
            r"(PyZ80AtomicBench_(?:Noop|Run))\s+",
            text, re.MULTILINE):
        result[match.group(2)] = int(match.group(1), 16)
    expected = {"PyZ80AtomicBench_Noop", "PyZ80AtomicBench_Run"}
    if set(result) != expected:
        raise DrawAtomicFrameCheckError(
            "benchmark map lacks symbols: " +
            ", ".join(sorted(expected - set(result))))
    return result


def _map_area(text: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"^{re.escape(name)}\s+([0-9A-Fa-f]{{8}})\s+"
        rf"([0-9A-Fa-f]{{8}})\s+=",
        text, re.MULTILINE)
    if match is None:
        raise DrawAtomicFrameCheckError(f"linked map lacks {name}")
    return int(match.group(1), 16), int(match.group(2), 16)


def _run(command: list[str], directory: Path, environment: Mapping[str, str],
         *, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=directory, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=dict(environment))
    if completed.returncode != 0:
        raise DrawAtomicFrameCheckError(
            f"command failed ({completed.returncode}): " +
            " ".join(command) + "\n" + completed.stdout)
    return completed


def _public_frame_bytes(assembly: str, symbol: str) -> int:
    match = re.search(
        rf"(?ms)^_{re.escape(symbol)}::?\s*$.*?"
        r"\bld\s+iy,\s*#-([0-9]+)\s*$.*?\badd\s+iy,\s*sp\s*$.*?"
        r"\bld\s+sp,\s*iy\s*$",
        assembly)
    if match is None:
        raise DrawAtomicFrameCheckError(
            f"cannot bind pinned-SDCC local frame for {symbol}")
    return int(match.group(1))


def _compile_atomic(root: Path, sdcc: Path,
                    environment: Mapping[str, str]) -> dict[str, object]:
    copied = (
        "Source/C/ft812/pyz80_draw_atomic_frame.c",
        "Source/C/ft812/pyz80_draw_atomic_frame.h",
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    with tempfile.TemporaryDirectory(prefix="pyz80-atomic-frame-object-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", "pyz80_draw_atomic_frame.c"]
        completed = _run(command, directory, environment)
        rel_bytes = (directory / "pyz80_draw_atomic_frame.rel").read_bytes()
        asm_bytes = (directory / "pyz80_draw_atomic_frame.asm").read_bytes()
        areas = _area_map(rel_bytes.decode("latin1"))
        assembly = asm_bytes.decode("latin1")
    if "_CODE" not in areas or "_DATA" not in areas:
        raise DrawAtomicFrameCheckError("SDCC object lacks CODE/DATA areas")
    frame_bytes = _public_frame_bytes(assembly, "PyZ80DrawAtomic_Run")
    if frame_bytes <= 0 or frame_bytes > 127:
        raise DrawAtomicFrameCheckError(
            "atomic Run local frame is outside proved encodable range")
    return {
        "command": command,
        "compiler_output": completed.stdout.strip(),
        "object_sha256": _sha256(rel_bytes),
        "assembly_sha256": _sha256(asm_bytes),
        "code_bytes": areas["_CODE"],
        "data_bytes": areas["_DATA"],
        "run_automatic_local_frame_bytes": frame_bytes,
        "single_16k_code_bank_headroom_bytes": 0x4000 - areas["_CODE"],
    }


def _benchmark(root: Path, sdcc: Path,
               environment: Mapping[str, str]) -> dict[str, object]:
    copied = (
        "Source/C/ft812/pyz80_draw_atomic_frame.c",
        "Source/C/ft812/pyz80_draw_atomic_frame.h",
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    with tempfile.TemporaryDirectory(prefix="pyz80-atomic-frame-bench-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "atomic_frame_bench.c").write_text(
            BENCH_SOURCE, encoding="utf-8", newline="\n")
        for source_name in (
                "pyz80_draw_atomic_frame.c", "atomic_frame_bench.c"):
            _run([str(sdcc), *PINNED_ARGUMENTS, "-c", source_name],
                 directory, environment)
        link_command = [
            str(sdcc), *LINK_ARGUMENTS, "-o", "atomic_frame_bench.ihx",
            "pyz80_draw_atomic_frame.rel", "atomic_frame_bench.rel",
        ]
        _run(link_command, directory, environment)
        ihx_path = directory / "atomic_frame_bench.ihx"
        map_path = directory / "atomic_frame_bench.map"
        ihx_bytes = ihx_path.read_bytes()
        map_bytes = map_path.read_bytes()
        map_text = map_bytes.decode("latin1")
        symbols = _map_symbols(map_text)
        code_start, code_bytes = _map_area(map_text, "_CODE")
        data_start, data_bytes = _map_area(map_text, "_DATA")

        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x2000",
            default_stack="0xFF00")
        for address, payload in _parse_ihx(ihx_path):
            if address + len(payload) > 0x10000:
                raise DrawAtomicFrameCheckError(
                    "atomic benchmark exceeds Z80 linear address space")
            machine.mem.write_block_linear(address, payload)

        minimum_sp = machine.reg.SP
        original_step = machine.step

        def tracked_step() -> int:
            nonlocal minimum_sp
            clocks = original_step()
            if machine.reg.SP < minimum_sp:
                minimum_sp = machine.reg.SP
            return clocks

        machine.step = tracked_step  # type: ignore[method-assign]
        initial_sp = machine.reg.SP
        before = machine.tstates
        noop_steps = machine.call(symbols["PyZ80AtomicBench_Noop"])
        noop_tstates = machine.tstates - before
        minimum_sp = machine.reg.SP
        initial_sp = machine.reg.SP
        before = machine.tstates
        run_steps = machine.call(
            symbols["PyZ80AtomicBench_Run"], max_steps=8_000_000)
        run_tstates = machine.tstates - before
        run_result = machine.reg.L
        final_sp = machine.reg.SP

    if run_result != 1:
        raise DrawAtomicFrameCheckError(
            f"pinned Z80 228-record benchmark returned {run_result}")
    if final_sp != initial_sp:
        raise DrawAtomicFrameCheckError(
            f"benchmark did not restore SP: {initial_sp:04X}->{final_sp:04X}")
    reference_bound = run_steps * MAXIMUM_Z80_INSTRUCTION_TSTATES
    if run_tstates > reference_bound:
        raise DrawAtomicFrameCheckError(
            "reference tstate measurement exceeds instruction bound")
    return {
        "benchmark_source_sha256": _sha256(BENCH_SOURCE.encode("utf-8")),
        "link_command": link_command,
        "linked_image": {
            "ihx_bytes": len(ihx_bytes),
            "ihx_sha256": _sha256(ihx_bytes),
            "map_bytes": len(map_bytes),
            "map_sha256": _sha256(map_bytes),
            "code_start_hex": f"0x{code_start:04X}",
            "code_bytes": code_bytes,
            "data_start_hex": f"0x{data_start:04X}",
            "data_bytes": data_bytes,
            "symbols": {
                key: f"0x{value:04X}" for key, value in sorted(symbols.items())
            },
        },
        "reference_execution": {
            "cpu_hz": CPU_HZ,
            "records": 228,
            "passes": 2,
            "resolver_calls": 456,
            "private_chunks": 2,
            "atomic_commits": 1,
            "aborts": 0,
            "simulator": "TSConfFT812Machine instruction tstates",
            "noop_wrapper_steps": noop_steps,
            "noop_wrapper_tstates": noop_tstates,
            "steps_including_wrapper": run_steps,
            "measured_tstates_including_reference_callbacks": run_tstates,
            "milliseconds_at_14mhz": round(run_tstates * 1000 / CPU_HZ, 6),
            "conservative_reference_path_tstate_bound": reference_bound,
            "bound_method": (
                "executed instruction count multiplied by 23, the maximum "
                "Z80 instruction cost accepted by this reference model"),
        },
        "stack": {
            "initial_sp_hex": f"0x{initial_sp:04X}",
            "minimum_sp_hex": f"0x{minimum_sp:04X}",
            "maximum_reference_path_bytes_including_outer_return":
                initial_sp - minimum_sp,
            "sp_restored": True,
            "complete_live_callback_stack_bytes": None,
        },
    }


def _static_protocol_checks(source: str, header: str) -> dict[str, bool]:
    ready_stores = re.findall(
        r"header\.state\s*=\s*PYZ80_FT_QUEUE_READY\s*;", source)
    signature_compare = source.find("pass.signature_a !=")
    final_flush = source.find("PyZ80DrawAtomic_FlushChunk(&pass)")
    checks = {
        "certificate_version_4":
            "PYZ80_DRAW_ATOMIC_CERTIFICATE_VERSION 4u" in header,
        "fixed_768_line_vector":
            "PYZ80_DRAW_ATOMIC_RASTER_LINES 768u" in header,
        "fixed_practical_1209_limit":
            "PYZ80_DRAW_ATOMIC_SAFE_LINE_CYCLES 1209u" in header and
            "budget->safe_line_cycles !=" in source,
        "strict_ram_dl_less_than_2048":
            "total_dl_words >= budget->ram_dl_word_limit" in source and
            "expected_words >=\n                budget->ram_dl_word_limit" in source,
        "single_ready_publication_store": len(ready_stores) == 1,
        "pass_a_writer_is_null": "pass.writer = NULL;" in source,
        "pass_b_replay_signatures_compared_before_final_flush":
            signature_compare >= 0 and final_flush >= 0 and
            signature_compare < final_flush,
        "failed_begin_aborts":
            "writer->abort(writer->context);\n        result->status = "
            "PYZ80_DRAW_ATOMIC_WRITER_BEGIN" in source,
        "prepare_b_and_token_failure_abort":
            source.count("writer->abort(writer->context);") == 4,
        "hqt_map_index_is_32_bit": "uint32_t map_index;" in source,
        "ram_g_address_check_is_overflow_safe":
            "address > 0x00100000ul - (uint32_t)byte_size" in source,
    }
    if not all(checks.values()):
        failed = ", ".join(key for key, value in checks.items() if not value)
        raise DrawAtomicFrameCheckError(
            "atomic protocol source invariant failed: " + failed)
    return checks


def probe(project_root: Path | str = ROOT) -> dict[str, object]:
    root = Path(project_root).resolve()
    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    sdcc_bytes = sdcc.read_bytes()
    if _sha256(sdcc_bytes).upper() != (
            compiler_manifest.target.toolchain_sha256.upper()):
        raise DrawAtomicFrameCheckError("located SDCC does not match pinned hash")
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    version = _run([str(sdcc), "--version"], root, environment).stdout.splitlines()[0]

    inputs = [_file_record(root, relative) for relative in INPUTS]
    source = (root / INPUTS[0]).read_text(encoding="utf-8")
    header = (root / INPUTS[1]).read_text(encoding="utf-8")
    static_checks = _static_protocol_checks(source, header)
    host = run_host_reference_matrix(root)
    target = _compile_atomic(root, sdcc, environment)
    benchmark = _benchmark(root, sdcc, environment)
    if target["code_bytes"] >= 0x4000 or target["data_bytes"] != 0:
        raise DrawAtomicFrameCheckError(
            "atomic C object does not fit one code bank or owns mutable DATA")

    checks = {
        **static_checks,
        **{key: bool(value) for key, value in host["matrix"].items()},
        "pinned_sdcc_object_compiled": True,
        "pinned_sdcc_code_fits_one_16k_bank": True,
        "pinned_sdcc_mutable_data_zero": True,
        "reference_228_record_two_pass_z80_execution": True,
        "reference_stack_sp_restored": True,
        "immutable_live_provider_bound": False,
        "full_hqt3_ram_g_working_set_bound": False,
        "final_bank_link_and_entry_bound": False,
        "live_callback_stack_wcet_bound": False,
        "isr_queue_ownership_bound": False,
    }
    semantic_payload = {
        "input_sha256": {row["path"]: row["sha256"] for row in inputs},
        "compiler_sha256": _sha256(sdcc_bytes),
        "target_object": target,
        "host_matrix": host["matrix"],
        "benchmark": benchmark,
        "checks": checks,
    }
    semantic_sha256 = _sha256(_json_bytes(semantic_payload))
    return {
        "format": FORMAT,
        "status": STATUS,
        "semantic_sha256": semantic_sha256,
        "input": {
            "files": inputs,
            "test_harness_sha256": _sha256(HARNESS.encode("utf-8")),
            "semantic_payload": semantic_payload,
        },
        "protocol": {
            "maximum_frame_records": 228,
            "passes": [
                "A: complete count/HQT/CMD_APPEND/RAM_DL/768-line preflight; no writer call",
                "B: replay into inactive bounded chunks; abort on every failure",
            ],
            "chunk_capacity_records": 128,
            "maximum_chunks": 2,
            "publication": "one final READY store; no READY-prefix",
            "ram_dl_rule": "total expanded frame words < 2048",
            "raster_rule": "every line <= 1209 cycles",
        },
        "host_reference_tests": host,
        "compiler": {
            "path": sdcc.as_posix(),
            "bytes": len(sdcc_bytes),
            "sha256": _sha256(sdcc_bytes),
            "version": version,
            "arguments": list(PINNED_ARGUMENTS),
        },
        "target_object": target,
        "z80_reference": benchmark,
        "stack_certificate": {
            "run_automatic_local_frame_bytes":
                target["run_automatic_local_frame_bytes"],
            "reference_path": benchmark["stack"],
            "complete_live_bound_bytes": None,
            "reason": (
                "immutable VM/provider/resolver/writer callback stack bounds "
                "are not yet linked"),
        },
        "timing_certificate": {
            "reference_228_record_two_pass":
                benchmark["reference_execution"],
            "complete_live_wcet_tstates": None,
            "reason": (
                "the reference bound includes deterministic test callbacks; "
                "live translated provider/resolver/writer WCET is not bound"),
        },
        "checks": checks,
        "live": False,
        "live_blockers": [
            {"code": "PZAF001", "detail": (
                "the generated active-game VM/provider is not yet proved "
                "immutable across the two replay passes")},
            {"code": "PZAF002", "detail": (
                "the complete level-loadable HQT3 working set, RAM_G "
                "addresses and append sizes are not bound to this gate")},
            {"code": "PZAF003", "detail": (
                "the atomic object is not in the real final F1/F2 link and "
                "production packer entry graph")},
            {"code": "PZAF004", "detail": (
                "complete live callback stack and WCET bounds are absent; "
                "only the pinned 228-record reference path is measured")},
            {"code": "PZAF005", "detail": (
                "ISR exclusion, inactive ED/EE queue ownership and consumer "
                "memory-order composition are not proved in the live image")},
        ],
    }


def validate_report(report: object, project_root: Path | str = ROOT) -> None:
    if not isinstance(report, dict):
        raise DrawAtomicFrameCheckError("atomic-frame report is not an object")
    if report.get("format") != FORMAT or report.get("status") != STATUS:
        raise DrawAtomicFrameCheckError("atomic-frame report format/status mismatch")
    if report.get("live") is not False:
        raise DrawAtomicFrameCheckError("atomic-frame report must remain live=false")
    payload = report.get("input", {}).get("semantic_payload")  # type: ignore[union-attr]
    if not isinstance(payload, dict) or report.get("semantic_sha256") != _sha256(
            _json_bytes(payload)):
        raise DrawAtomicFrameCheckError("atomic-frame semantic hash mismatch")
    root = Path(project_root).resolve()
    rows = report.get("input", {}).get("files")  # type: ignore[union-attr]
    if not isinstance(rows, list) or len(rows) != len(INPUTS):
        raise DrawAtomicFrameCheckError("atomic-frame input binding set mismatch")
    for row, relative in zip(rows, INPUTS):
        if not isinstance(row, dict) or row.get("path") != relative:
            raise DrawAtomicFrameCheckError("atomic-frame input order/path mismatch")
        actual = _file_record(root, relative)
        if row != actual:
            raise DrawAtomicFrameCheckError(
                f"atomic-frame input binding is stale: {relative}")
    checks = report.get("checks")
    required_false = {
        "immutable_live_provider_bound",
        "full_hqt3_ram_g_working_set_bound",
        "final_bank_link_and_entry_bound",
        "live_callback_stack_wcet_bound",
        "isr_queue_ownership_bound",
    }
    if not isinstance(checks, dict):
        raise DrawAtomicFrameCheckError("atomic-frame checks missing")
    for key, value in checks.items():
        expected = key not in required_false
        if value is not expected:
            raise DrawAtomicFrameCheckError(
                f"atomic-frame check has unexpected value: {key}")
    blockers = report.get("live_blockers")
    if not isinstance(blockers, list) or [item.get("code") for item in blockers
                                         if isinstance(item, dict)] != [
            "PZAF001", "PZAF002", "PZAF003", "PZAF004", "PZAF005"]:
        raise DrawAtomicFrameCheckError("atomic-frame blockers changed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_atomic_frame_status.json"))
    arguments = parser.parse_args()
    output = arguments.output
    if not output.is_absolute():
        output = ROOT / output
    try:
        result = probe(ROOT)
        validate_report(result, ROOT)
        _atomic_json(output, result)
    except (DrawAtomicFrameCheckError, OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    timing = result["timing_certificate"]["reference_228_record_two_pass"]
    print(
        "Atomic frame C: CODE="
        f"{result['target_object']['code_bytes']} B, DATA=0 B, "
        f"stack(reference)={result['z80_reference']['stack']['maximum_reference_path_bytes_including_outer_return']} B, "
        f"228x2={timing['measured_tstates_including_reference_callbacks']} tstates "
        f"(conservative reference bound {timing['conservative_reference_path_tstate_bound']}); "
        "live provider/link remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
