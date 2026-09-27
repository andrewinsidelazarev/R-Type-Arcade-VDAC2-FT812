#!/usr/bin/env python3
"""Pinned Z80 certificate for the prelocalized prepared-frame v3 ABI."""

from __future__ import annotations

import argparse
import ast
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
from test_pyz80_draw_prepared_frame_v3 import HARNESS, run_host_reference_matrix


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))
from tsconf_ft812_sim import TSConfFT812Machine  # noqa: E402


FORMAT = "pyz80-draw-prepared-frame-v3-certificate-v3"
STATUS_PASS = "PRELOCALIZED_PREPARED_FRAME_V3_ISOLATED_DRAW_PROVED_FRAME_SCHEDULE_BLOCKED"
STATUS_QUEUE = "PRELOCALIZED_PREPARED_FRAME_V3_PREFLIGHT_100K_MET_QUEUE_MISSED"
STATUS_TIMING = "PRELOCALIZED_PREPARED_FRAME_V3_PREFLIGHT_100K_MISSED"
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
    "--data-loc", "0xA000",
)
INPUTS = (
    "Source/C/ft812/pyz80_draw_prepared_frame_v3.c",
    "Source/C/ft812/pyz80_draw_prepared_frame_v3.h",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/ASM/pyz80_draw_prepared_frame_v3.asm",
    "Source/ASM/pyz80_draw_prepared_queue_v3.asm",
    "Source/Tools/test_pyz80_draw_prepared_frame_v3.py",
    "Source/Tools/check_pyz80_draw_prepared_frame_v3.py",
    "Source/Tools/rtype_python_compiler.json",
    "Build/rtype_python_draw_private_tape_v2_status.json",
    "Build/rtype_python_full_hqt3_inventory_status.json",
)
V2_REFERENCE_PATH = "Build/rtype_python_draw_private_tape_v2_status.json"


BENCH_SOURCE = r'''
#include <stdint.h>
#include "pyz80_draw_prepared_frame_v3.h"

static volatile PyZ80DrawPreparedV3SourceRecord source_records[228];
static volatile PyZ80DrawPreparedV3Record private_records[228];
static volatile PyZ80DrawPreparedV3AppendEntry directory[2];
static PyZ80DrawPreparedV3Certificate certificate;
static PyZ80DrawPreparedV3FrameBudget budget;
static PyZ80DrawPreparedV3Result result;
static PyZ80DrawPreparedV3IdentityCache cache;
static volatile uint16_t fast_append_words[2];
static volatile uint8_t fast_append_stream[16];
static PyZ80DrawPreparedV3FastParams fast_params;
static PyZ80DrawPreparedV3FastQueueParams fast_queue_params;
static PyZ80FtQueue queue;
static PyZ80DrawPreparedV3FT812WriterContext ft_context;
static uint16_t writer_records;
static uint16_t writer_chunks;
static uint16_t append_calls;
static uint16_t commit_calls;
static uint16_t abort_calls;
static uint8_t begin_should_fail;

uint8_t PyZ80FT_QueueAcquireFragment(
        volatile PyZ80FtQueue *target, uint16_t sequence) PYZ80_CALL0
{
    if (target == 0 || target->header.state != PYZ80_FT_QUEUE_FREE)
        return 0u;
    target->header.frame_sequence = sequence;
    target->header.count = 0u;
    target->header.payload_bytes = 0u;
    target->header.dl_words = 0u;
    target->header.overflow = 0u;
    target->header.kind = PYZ80_FT_QUEUE_FRAGMENT;
    target->header.state = PYZ80_FT_QUEUE_BUILDING;
    return 1u;
}

static uint8_t writer_begin(void *context,
        const PyZ80DrawPreparedV3Preflight *preflight)
{
    (void)context;
    (void)preflight;
    return begin_should_fail ? 0u : 1u;
}

static uint8_t writer_append(void *context,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        const volatile PyZ80DrawPreparedV3Record *records,
        uint16_t count, uint16_t first)
{
    (void)context;
    (void)records;
    if (append_directory != directory || append_directory_count != 2u ||
            first != writer_records) return 0u;
    append_calls++;
    writer_records = (uint16_t)(writer_records + count);
    writer_chunks++;
    return 1u;
}

static uint8_t writer_commit(void *context,
        const PyZ80DrawPreparedV3Preflight *preflight)
{
    (void)context;
    commit_calls++;
    return (uint8_t)(writer_records == preflight->record_count &&
        writer_chunks == preflight->chunk_count);
}

static void writer_abort(void *context)
{
    (void)context;
    abort_calls++;
}

static PyZ80DrawPreparedV3Writer generic_writer;
static PyZ80DrawPreparedV3Writer ft_writer;

uint8_t PyZ80PreparedV3Bench_Setup(void) PYZ80_CALL0
{
    uint16_t index;
    directory[0].ram_g_address_lo = 0x1000u;
    directory[0].ram_g_address_hi = 0u;
    directory[0].byte_size = 4u;
    directory[1].ram_g_address_lo = 0x2000u;
    directory[1].ram_g_address_hi = 0u;
    directory[1].byte_size = 8u;
    fast_append_words[0] = 1u;
    fast_append_words[1] = 2u;
    fast_append_stream[0] = 0x00u;
    fast_append_stream[1] = 0x10u;
    fast_append_stream[2] = 0u;
    fast_append_stream[3] = 0u;
    fast_append_stream[4] = 4u;
    fast_append_stream[5] = 0u;
    fast_append_stream[6] = 0u;
    fast_append_stream[7] = 0u;
    fast_append_stream[8] = 0x00u;
    fast_append_stream[9] = 0x20u;
    fast_append_stream[10] = 0u;
    fast_append_stream[11] = 0u;
    fast_append_stream[12] = 8u;
    fast_append_stream[13] = 0u;
    fast_append_stream[14] = 0u;
    fast_append_stream[15] = 0u;
    for (index = 0u; index < 228u; ++index) {
        source_records[index].append_ref = (uint16_t)(index & 1u);
        source_records[index].vertex_x = (int16_t)(index - 100);
        source_records[index].vertex_y = (int16_t)(80 - index);
        source_records[index].template_index = (uint16_t)(index & 31u);
        private_records[index].append_ref = (uint16_t)(index & 1u);
        private_records[index].vertex_x = (int16_t)(index - 100);
        private_records[index].vertex_y = (int16_t)(80 - index);
    }
    certificate.format_version = PYZ80_DRAW_PREPARED_V3_CERTIFICATE_VERSION;
    certificate.sizing_proof_complete = 1u;
    certificate.identity_cache_mutation_proved = 1u;
    certificate.private_render_order_producer_proved = 1u;
    certificate.append_directory_proved = 1u;
    certificate.raster_768_lines_proved = 1u;
    certificate.certified_max_records = 228u;
    certificate.max_cmd_append_expanded_words = 456u;
    certificate.max_fragment_expanded_dl_words = 938u;
    certificate.worst_raster_line = 767u;
    certificate.worst_raster_cycles = 0u;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_PREPARED_V3_SAFE_LINE_CYCLES;
    fast_params.source_records = source_records;
    fast_params.private_records = private_records;
    fast_params.append_word_directory = fast_append_words;
    fast_params.record_count = 228u;
    fast_params.append_directory_count = 2u;
    fast_params.max_append_words = 456u;
    fast_params.non_fragment_words = 0u;
    fast_params.worst_raster_cycles = 0u;
    fast_params.out_append_words = 342u;
    fast_params.out_fragment_words = 824u;
    fast_params.out_total_words = 824u;
    fast_params.out_failure_index = 0xFFFFu;
    fast_params.status = PYZ80_DRAW_PREPARED_V3_FAST_OK;
    fast_queue_params.private_records = private_records;
    fast_queue_params.append_stream_directory = fast_append_stream;
    fast_queue_params.queue = &queue;
    fast_queue_params.preflight = &fast_params;
    fast_queue_params.record_count = 228u;
    fast_queue_params.frame_sequence = 3u;
    generic_writer.begin = writer_begin;
    generic_writer.append = writer_append;
    generic_writer.commit = writer_commit;
    generic_writer.abort = writer_abort;
    generic_writer.context = 0;
    ft_writer.begin = PyZ80DrawPreparedV3FT812_Begin;
    ft_writer.append = PyZ80DrawPreparedV3FT812_Append;
    ft_writer.commit = PyZ80DrawPreparedV3FT812_Commit;
    ft_writer.abort = PyZ80DrawPreparedV3FT812_Abort;
    ft_writer.context = &ft_context;
    queue.header.state = PYZ80_FT_QUEUE_FREE;
    queue.header.kind = PYZ80_FT_QUEUE_FRAGMENT;
    ft_context.queue = &queue;
    ft_context.frame_sequence = 3u;
    ft_context.begun = 0u;
    return 1u;
}

static void reset_generic(uint8_t fail_begin)
{
    writer_records = 0u;
    writer_chunks = 0u;
    append_calls = 0u;
    commit_calls = 0u;
    abort_calls = 0u;
    begin_should_fail = fail_begin;
}

uint8_t PyZ80PreparedV3Bench_Noop(void) PYZ80_CALL0
{
    return 1u;
}

uint8_t PyZ80PreparedV3Bench_ASMPre(void) PYZ80_CALL0 __naked
{
    __asm
        ld hl, #_fast_params
        call 0x1800
        or a
        jr nz, 00001$
        ld l, #1
        ret
00001$:
        ld l, #0
        ret
    __endasm;
}

uint8_t PyZ80PreparedV3Bench_ASMQueue(void) PYZ80_CALL0 __naked
{
    __asm
        ld hl, #(_queue + 12)
        ld (hl), #0
        ld hl, #_fast_queue_params
        call 0x1A00
        or a
        jr nz, 00002$
        ld l, #1
        ret
00002$:
        ld l, #0
        ret
    __endasm;
}

uint8_t PyZ80PreparedV3Bench_ASMFull(void) PYZ80_CALL0 __naked
{
    __asm
        ld hl, #_fast_params
        call 0x1800
        or a
        jr nz, 00003$
        ld hl, #(_queue + 12)
        ld (hl), #0
        ld hl, #_fast_queue_params
        call 0x1A00
        or a
        jr nz, 00003$
        ld l, #1
        ret
00003$:
        ld l, #0
        ret
    __endasm;
}

uint8_t PyZ80PreparedV3Bench_Copy228(void) PYZ80_CALL0
{
    uint16_t index;
    for (index = 0u; index < 228u; ++index) {
        if (source_records[index].template_index >=
                PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT) return 0u;
        private_records[index].append_ref = source_records[index].append_ref;
        private_records[index].vertex_x = source_records[index].vertex_x;
        private_records[index].vertex_y = source_records[index].vertex_y;
    }
    return 1u;
}

uint8_t PyZ80PreparedV3Bench_RunPre(void) PYZ80_CALL0
{
    PyZ80DrawPreparedV3Status status;
    reset_generic(1u);
    status = PyZ80DrawPreparedV3_Run(
        private_records, 228u, directory, 2u, &certificate, &budget,
        &generic_writer, &result);
    if (status != PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN)
        return (uint8_t)(20u + status);
    if (result.validated_records != 228u) return 2u;
    if (abort_calls != 1u) return 3u;
    if (append_calls != 0u || commit_calls != 0u || result.committed)
        return 4u;
    return 1u;
}

uint8_t PyZ80PreparedV3Bench_BuildPre(void) PYZ80_CALL0
{
    reset_generic(1u);
    return (uint8_t)(PyZ80DrawPreparedV3_Build(
        source_records, 228u, directory, 2u, private_records, 228u,
        &certificate, &budget, &generic_writer, &result) ==
            PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN &&
        result.validated_records == 228u && abort_calls == 1u &&
        append_calls == 0u && commit_calls == 0u && !result.committed);
}

uint8_t PyZ80PreparedV3Bench_BuildGen(void) PYZ80_CALL0
{
    reset_generic(0u);
    return (uint8_t)(PyZ80DrawPreparedV3_Build(
        source_records, 228u, directory, 2u, private_records, 228u,
        &certificate, &budget, &generic_writer, &result) ==
            PYZ80_DRAW_PREPARED_V3_OK && result.committed &&
        append_calls == 2u && commit_calls == 1u && abort_calls == 0u);
}

uint8_t PyZ80PreparedV3Bench_BuildFT(void) PYZ80_CALL0
{
    queue.header.state = PYZ80_FT_QUEUE_FREE;
    queue.header.kind = PYZ80_FT_QUEUE_FRAGMENT;
    ft_context.begun = 0u;
    return (uint8_t)(PyZ80DrawPreparedV3_Build(
        source_records, 228u, directory, 2u, private_records, 228u,
        &certificate, &budget, &ft_writer, &result) ==
            PYZ80_DRAW_PREPARED_V3_OK && result.committed &&
        queue.header.state == PYZ80_FT_QUEUE_READY &&
        queue.header.count == 1166u && queue.header.dl_words == 824u);
}

uint8_t PyZ80PreparedV3Bench_CacheSpawn(void) PYZ80_CALL0
{
    uint16_t index;
    for (index = 0u; index < 228u; ++index)
        PyZ80DrawPreparedV3_CacheSpawn(
            &cache, index, (uint16_t)(0x2000u + index), index);
    return (uint8_t)(cache.valid && cache.template_index == 227u);
}

uint8_t PyZ80PreparedV3Bench_CacheState(void) PYZ80_CALL0
{
    uint16_t index;
    PyZ80DrawPreparedV3_CacheSpawn(&cache, 0u, 0u, 0u);
    for (index = 0u; index < 228u; ++index) {
        PyZ80DrawPreparedV3_CacheMutateState(&cache);
        if (!PyZ80DrawPreparedV3_CacheInstallResolved(
                &cache, cache.generation, index)) return 0u;
    }
    return (uint8_t)(cache.valid && cache.template_index == 227u);
}

uint8_t PyZ80PreparedV3Bench_CacheBank(void) PYZ80_CALL0
{
    uint16_t index;
    PyZ80DrawPreparedV3_CacheSpawn(&cache, 0u, 0u, 0u);
    for (index = 0u; index < 228u; ++index) {
        PyZ80DrawPreparedV3_CacheMutateBankKey(&cache, index);
        if (!PyZ80DrawPreparedV3_CacheInstallResolved(
                &cache, cache.generation, index)) return 0u;
    }
    return (uint8_t)(cache.valid && cache.bank_key == 227u);
}

uint8_t PyZ80PreparedV3Bench_CacheDesc(void) PYZ80_CALL0
{
    uint16_t index;
    PyZ80DrawPreparedV3_CacheSpawn(&cache, 0u, 0u, 0u);
    for (index = 0u; index < 228u; ++index) {
        PyZ80DrawPreparedV3_CacheMutateDescriptor(&cache, index);
        if (!PyZ80DrawPreparedV3_CacheInstallResolved(
                &cache, cache.generation, index)) return 0u;
    }
    return (uint8_t)(cache.valid && cache.descriptor == 227u);
}

uint8_t PyZ80PreparedV3Bench_CacheLevel(void) PYZ80_CALL0
{
    uint16_t index;
    PyZ80DrawPreparedV3_CacheSpawn(&cache, 0u, 0u, 0u);
    for (index = 0u; index < 228u; ++index) {
        PyZ80DrawPreparedV3_CacheMutateLevelPack(&cache);
        if (!PyZ80DrawPreparedV3_CacheInstallResolved(
                &cache, cache.generation, index)) return 0u;
    }
    return (uint8_t)(cache.valid && cache.template_index == 227u);
}
'''


class DrawPreparedV3CheckError(RuntimeError):
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


def _active_python_mutation_inventory(root: Path) -> dict[str, object]:
    fields = {"bank_key", "descriptor", "state", "palette", "resource_type"}
    rows: list[dict[str, object]] = []
    files: list[dict[str, object]] = []

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

        def record(self, target: ast.AST) -> None:
            if isinstance(target, (ast.Tuple, ast.List)):
                for item in target.elts:
                    self.record(item)
            elif (isinstance(target, ast.Attribute) and
                  isinstance(target.value, ast.Name) and
                  target.value.id == "self" and target.attr in fields):
                rows.append({
                    "path": self.relative,
                    "line": target.lineno,
                    "field": target.attr,
                    "site_class": "spawn" if self.function == "__init__"
                                  else "mutation",
                    "function": self.function,
                })

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                self.record(target)
            self.generic_visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.record(node.target)
            if node.value is not None:
                self.generic_visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.record(node.target)
            self.generic_visit(node.value)

    base = root / "Source" / "Python" / "rtype_port"
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        files.append({"path": relative, "bytes": len(data),
                      "sha256": _sha256(data)})
        tree = ast.parse(data.decode("utf-8"), filename=relative)
        Visitor(relative).visit(tree)
    rows.sort(key=lambda row: (
        str(row["path"]), int(row["line"]), str(row["field"])))
    by_field = {field: sum(row["field"] == field for row in rows)
                for field in sorted(fields)}
    by_class = {kind: sum(row["site_class"] == kind for row in rows)
                for kind in ("spawn", "mutation")}
    return {
        "scope": "Source/Python/rtype_port/**/*.py self-attribute writes",
        "fields": sorted(fields),
        "files": files,
        "site_count": len(rows),
        "by_field": by_field,
        "by_site_class": by_class,
        "rows_sha256": _sha256(_json_bytes(rows)),
        "rows": rows,
        "instrumented_site_count": 0,
        "all_sites_instrumented": False,
    }


def _run(command: list[str], directory: Path, environment: Mapping[str, str],
         timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=directory, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=dict(environment))
    if completed.returncode != 0:
        raise DrawPreparedV3CheckError(
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
        raise DrawPreparedV3CheckError(f"linked map lacks {name}")
    return int(match.group(1), 16), int(match.group(2), 16)


def _symbols(text: str) -> dict[str, int]:
    result = {match.group(2): int(match.group(1), 16) for match in re.finditer(
        r"^\s*([0-9A-Fa-f]{8})\s+_"
        r"(PyZ80PreparedV3Bench_(?:Setup|Noop|ASMPre|ASMQueue|ASMFull|"
        r"Copy228|RunPre|BuildPre|"
        r"BuildGen|BuildFT|CacheSpawn|CacheState|CacheBank|CacheDesc|"
        r"CacheLevel))\s+", text, re.MULTILINE)}
    expected = {
        "PyZ80PreparedV3Bench_Setup", "PyZ80PreparedV3Bench_Noop",
        "PyZ80PreparedV3Bench_ASMPre",
        "PyZ80PreparedV3Bench_ASMQueue",
        "PyZ80PreparedV3Bench_ASMFull",
        "PyZ80PreparedV3Bench_Copy228",
        "PyZ80PreparedV3Bench_RunPre",
        "PyZ80PreparedV3Bench_BuildPre",
        "PyZ80PreparedV3Bench_BuildGen",
        "PyZ80PreparedV3Bench_BuildFT",
        "PyZ80PreparedV3Bench_CacheSpawn",
        "PyZ80PreparedV3Bench_CacheState",
        "PyZ80PreparedV3Bench_CacheBank",
        "PyZ80PreparedV3Bench_CacheDesc",
        "PyZ80PreparedV3Bench_CacheLevel",
    }
    if set(result) != expected:
        raise DrawPreparedV3CheckError(
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
        raise DrawPreparedV3CheckError(
            f"cannot bind local stack frame for {symbol}")
    return int(match.group(1))


def _locate_sjasmplus(root: Path) -> Path:
    configured = os.environ.get("SJASMPLUS", "").strip('" ')
    candidates = [Path(configured)] if configured else []
    candidates.append(
        root.parent / "z80" / "tsconf_project" / "exe" /
        "sjasmplus" / "sjasmplus.exe")
    build = (root / "build.cmd").read_text(
        encoding="utf-8", errors="replace")
    match = re.search(
        r'(?mi)^if\s+"%SJASMPLUS%"==""\s+set\s+SJASMPLUS=(.+?)\s*$',
        build)
    if match:
        candidates.append(Path(match.group(1).strip('" ')))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise DrawPreparedV3CheckError("pinned sjasmplus is unavailable")


def _assemble_fast(root: Path) -> tuple[bytes, bytes, dict[str, object]]:
    assembler = _locate_sjasmplus(root)
    source = (root / "Source" / "ASM" /
              "pyz80_draw_prepared_frame_v3.asm").resolve()
    queue_source = (root / "Source" / "ASM" /
                    "pyz80_draw_prepared_queue_v3.asm").resolve()
    with tempfile.TemporaryDirectory(prefix="pyz80-prepared-v3-asm-") as tmp:
        directory = Path(tmp)
        wrapper = (
            "                DEVICE ZXSPECTRUM128\n"
            "                ORG #1800\n"
            f'                include "{source.as_posix()}"\n'
            "                ASSERT PyZ80DrawPreparedV3_ASM_Start = #1800\n"
            "                ASSERT PyZ80DrawPreparedV3_ASM_End <= #2000\n"
            "                SAVEBIN \"prepared_v3.bin\", "
            "PyZ80DrawPreparedV3_ASM_Start, "
            "PyZ80DrawPreparedV3_ASM_End - PyZ80DrawPreparedV3_ASM_Start\n"
            "                ORG #1A00\n"
            f'                include "{queue_source.as_posix()}"\n'
            "                ASSERT PyZ80DrawPreparedV3_ASMQueue_Start = #1A00\n"
            "                ASSERT PyZ80DrawPreparedV3_ASMQueue_End <= #2000\n"
            "                SAVEBIN \"prepared_queue_v3.bin\", "
            "PyZ80DrawPreparedV3_ASMQueue_Start, "
            "PyZ80DrawPreparedV3_ASMQueue_End - "
            "PyZ80DrawPreparedV3_ASMQueue_Start\n"
        )
        (directory / "prepared_v3_wrapper.asm").write_text(
            wrapper, encoding="utf-8", newline="\n")
        completed = _run(
            [str(assembler), "--nologo", "prepared_v3_wrapper.asm"],
            directory, os.environ.copy())
        binary = (directory / "prepared_v3.bin").read_bytes()
        queue_binary = (directory / "prepared_queue_v3.bin").read_bytes()
    if not binary or len(binary) > 0x800:
        raise DrawPreparedV3CheckError("v3 ASM exceeds reserved prototype window")
    if not queue_binary or len(queue_binary) > 0x600:
        raise DrawPreparedV3CheckError("v3 queue ASM exceeds prototype window")
    return binary, queue_binary, {
        "assembler_path": assembler.as_posix(),
        "assembler_sha256": _sha256(assembler.read_bytes()),
        "assembler_output": completed.stdout.strip(),
        "source_path": "Source/ASM/pyz80_draw_prepared_frame_v3.asm",
        "source_sha256": _sha256(source.read_bytes()),
        "origin_hex": "0x1800",
        "end_exclusive_hex": f"0x{0x1800 + len(binary):04X}",
        "bytes": len(binary),
        "binary_sha256": _sha256(binary),
        "queue_source_path": "Source/ASM/pyz80_draw_prepared_queue_v3.asm",
        "queue_source_sha256": _sha256(queue_source.read_bytes()),
        "queue_origin_hex": "0x1A00",
        "queue_end_exclusive_hex": f"0x{0x1A00 + len(queue_binary):04X}",
        "queue_bytes": len(queue_binary),
        "queue_binary_sha256": _sha256(queue_binary),
    }


def _asm_reference_oracle(root: Path, binary: bytes,
                          queue_binary: bytes) -> dict[str, object]:
    source_address = 0x6000
    target_address = 0x6800
    words_address = 0x7000
    params_address = 0x7100

    def execute(*, bad_template: int | None = None,
                bad_ref: int | None = None, zero_words: bool = False,
                max_append: int = 456, non_fragment: int = 0,
                worst_raster: int = 0) -> dict[str, object]:
        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x1800",
            default_stack="0xFF00")
        machine.mem.write_block_linear(0x1800, binary)
        source = bytearray()
        expected = bytearray()
        for index in range(228):
            append_ref = index & 1
            if bad_ref == index:
                append_ref = 2
            template = index & 31
            if bad_template == index:
                template = 0xFFFF
            row = struct.pack("<HhhH", append_ref,
                              index - 100, 80 - index, template)
            source.extend(row)
            expected.extend(row[:6])
        words = struct.pack("<HH", 0 if zero_words else 1, 2)
        params = struct.pack(
            "<HHHBBHHHHHHHB",
            source_address, target_address, words_address, 228, 2,
            max_append, non_fragment, worst_raster,
            0, 0, 0, 0, 0xFF)
        machine.mem.write_block_linear(source_address, bytes(source))
        machine.mem.write_block_linear(target_address, b"\xA5" * 1368)
        machine.mem.write_block_linear(words_address, words)
        machine.mem.write_block_linear(params_address, params)
        initial_sp = machine.reg.SP
        before = machine.tstates
        steps = machine.call(0x1800, h=params_address >> 8,
                             l=params_address & 0xFF, max_steps=1_000_000)
        elapsed = machine.tstates - before
        if machine.reg.SP != initial_sp:
            raise DrawPreparedV3CheckError("ASM oracle did not restore SP")
        raw = machine.mem.read_block(params_address, 23)
        unpacked = struct.unpack("<HHHBBHHHHHHHB", raw)
        return {
            "status": machine.reg.A,
            "param_status": unpacked[-1],
            "append_words": unpacked[8],
            "fragment_words": unpacked[9],
            "total_words": unpacked[10],
            "failure_index": unpacked[11],
            "target": machine.mem.read_block(target_address, 1368),
            "expected": bytes(expected),
            "steps": steps,
            "tstates": elapsed,
            "stack_bytes_including_outer_return": 6,
        }

    success = execute()
    invalid_template = execute(bad_template=5)
    append_bound = execute(max_append=341)
    ram_dl = execute(non_fragment=1224)
    raster_pass = execute(worst_raster=385)
    raster_fail = execute(worst_raster=386)

    queue_address = 0x8000
    stream_address = 0x7400
    queue_params_address = 0x7200
    queue_machine = TSConfFT812Machine(
        root, load_spg=False, default_start="0x1A00",
        default_stack="0xFF00")
    queue_machine.mem.write_block_linear(0x1A00, queue_binary)
    queue_machine.mem.write_block_linear(target_address, success["target"])
    stream = struct.pack("<II", 0x1000, 4) + struct.pack("<II", 0x2000, 8)
    queue_machine.mem.write_block_linear(stream_address, stream)
    queue_machine.mem.write_block_linear(queue_address, b"\x00" * 0x4000)
    queue_preflight = struct.pack(
        "<HHHBBHHHHHHHB",
        source_address, target_address, words_address, 228, 2,
        456, 0, 0, 342, 824, 824, 0xFFFF, 0)
    queue_machine.mem.write_block_linear(params_address, queue_preflight)
    queue_params = struct.pack(
        "<HHHHBHB", target_address, stream_address, queue_address,
        params_address, 228, 9, 0xFF)
    queue_machine.mem.write_block_linear(queue_params_address, queue_params)
    queue_initial_sp = queue_machine.reg.SP
    queue_before = queue_machine.tstates
    queue_steps = queue_machine.call(
        0x1A00, h=queue_params_address >> 8, l=queue_params_address & 0xFF,
        max_steps=2_000_000)
    queue_tstates = queue_machine.tstates - queue_before
    if queue_machine.reg.SP != queue_initial_sp:
        raise DrawPreparedV3CheckError("queue ASM oracle did not restore SP")
    header = queue_machine.mem.read_block(queue_address, 16)
    payload = queue_machine.mem.read_block(queue_address + 16, 1166 * 4)
    expected_words: list[int] = []
    prefix = [
        0x04FFFFFF, 0x150000A0, 0x16000000, 0x17000000,
        0x18000000, 0x190000A0, 0x1A000000, 0x08005830,
        0x27000003, 0x1F000001,
    ]
    suffix = [0x2B000000, 0x2C000000, 0x21000000]
    for first, count in ((0, 128), (128, 100)):
        expected_words.extend(prefix)
        for index in range(first, first + count):
            append_ref = index & 1
            x = index - 100
            y = 80 - index
            expected_words.extend((
                0x2B000000 | (((x & 0xFFFF) << 1) & 0x1FFFF),
                0x2C000000 | (((y & 0xFFFF) << 1) & 0x1FFFF),
                0xFFFFFF1E,
                0x1000 if append_ref == 0 else 0x2000,
                4 if append_ref == 0 else 8,
            ))
        expected_words.extend(suffix)
    expected_payload = b"".join(
        struct.pack("<I", word) for word in expected_words)
    queue_param_result = struct.unpack(
        "<HHHHBHB", queue_machine.mem.read_block(queue_params_address, 12))

    busy_machine = TSConfFT812Machine(
        root, load_spg=False, default_start="0x1A00",
        default_stack="0xFF00")
    busy_machine.mem.write_block_linear(0x1A00, queue_binary)
    busy_machine.mem.write_block_linear(params_address, queue_preflight)
    busy_machine.mem.write_block_linear(queue_params_address, queue_params)
    busy_machine.mem.write(queue_address + 12, 1)
    busy_machine.call(0x1A00, h=queue_params_address >> 8,
                      l=queue_params_address & 0xFF, max_steps=10_000)

    mismatch_machine = TSConfFT812Machine(
        root, load_spg=False, default_start="0x1A00",
        default_stack="0xFF00")
    mismatch_machine.mem.write_block_linear(0x1A00, queue_binary)
    stale_preflight = bytearray(queue_preflight)
    stale_preflight[22] = 1
    mismatch_machine.mem.write_block_linear(params_address, stale_preflight)
    mismatch_machine.mem.write_block_linear(queue_params_address, queue_params)
    mismatch_machine.mem.write_block_linear(queue_address, b"\x00" * 32)
    mismatch_machine.call(0x1A00, h=queue_params_address >> 8,
                          l=queue_params_address & 0xFF, max_steps=10_000)
    checks = {
        "success_status_zero": success["status"] == 0 and
            success["param_status"] == 0,
        "success_exact_1368_byte_tape":
            success["target"] == success["expected"],
        "success_exact_budget":
            (success["append_words"], success["fragment_words"],
             success["total_words"], success["failure_index"]) ==
            (342, 824, 824, 0xFFFF),
        "stale_template_fails_at_exact_index":
            invalid_template["status"] == 1 and
            invalid_template["failure_index"] == 5,
        "append_sum_bound_fails_after_complete_dynamic_sum":
            append_bound["status"] == 2 and
            append_bound["failure_index"] == 228,
        "strict_ram_dl_2048_fails": ram_dl["status"] == 3,
        "raster_1209_passes": raster_pass["status"] == 0 and
            raster_pass["total_words"] == 824,
        "raster_1210_fails": raster_fail["status"] == 4,
        "queue_payload_is_word_exact_for_228_records":
            payload == expected_payload and len(expected_words) == 1166,
        "queue_header_metadata_is_exact":
            struct.unpack_from("<HHH", header, 6) == (1166, 4664, 824) and
            header[12] == 2 and header[13] == 0 and header[14] == 1,
        "queue_ready_is_reported_only_after_success":
            queue_machine.reg.A == 0 and queue_param_result[-1] == 0,
        "busy_queue_fails_without_overwrite":
            busy_machine.reg.A == 1 and
            busy_machine.mem.read(queue_address + 12) == 1,
        "stale_preflight_fails_before_building":
            mismatch_machine.reg.A == 1 and
            mismatch_machine.mem.read(queue_address + 12) == 0 and
            mismatch_machine.mem.read_block(queue_address + 16, 16) ==
                b"\x00" * 16,
    }
    if not all(checks.values()):
        mismatch = next((index for index, (actual, expected) in enumerate(
            zip(success["target"], success["expected"]))
            if actual != expected), None)
        raise DrawPreparedV3CheckError(
            "v3 ASM oracle failed: " + ", ".join(
                key for key, value in checks.items() if not value) +
            f"; first_tape_mismatch={mismatch}")
    return {
        "matrix": checks,
        "success_steps": success["steps"],
        "success_tstates": success["tstates"],
        "stack_bytes_including_outer_return":
            success["stack_bytes_including_outer_return"],
        "queue_success_steps": queue_steps,
        "queue_success_tstates": queue_tstates,
        "queue_stack_bytes_including_outer_return": 6,
    }


def _compile_target(root: Path, sdcc: Path,
                    environment: Mapping[str, str]) -> dict[str, object]:
    copied = INPUTS[:3]
    with tempfile.TemporaryDirectory(prefix="pyz80-prepared-v3-obj-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        command = [str(sdcc), *PINNED_ARGUMENTS,
                   "-c", "pyz80_draw_prepared_frame_v3.c"]
        completed = _run(command, directory, environment)
        rel = (directory / "pyz80_draw_prepared_frame_v3.rel").read_bytes()
        asm = (directory / "pyz80_draw_prepared_frame_v3.asm").read_bytes()
    areas = _areas(rel.decode("latin1"))
    code = areas.get("_CODE", -1)
    data = areas.get("_DATA", -1)
    if not 0 < code < 0x4000 or data != 0:
        raise DrawPreparedV3CheckError("v3 object CODE/DATA contract failed")
    assembly = asm.decode("latin1")
    return {
        "command": command,
        "compiler_output": completed.stdout.strip(),
        "object_sha256": _sha256(rel),
        "assembly_sha256": _sha256(asm),
        "code_bytes": code,
        "data_bytes": data,
        "single_16k_bank_headroom_bytes": 0x4000 - code,
        "run_automatic_local_frame_bytes":
            _local_frame(assembly, "PyZ80DrawPreparedV3_Run"),
        "build_automatic_local_frame_bytes":
            _local_frame(assembly, "PyZ80DrawPreparedV3_Build"),
    }


def _benchmark(root: Path, sdcc: Path, environment: Mapping[str, str],
               asm_binary: bytes, queue_asm_binary: bytes) -> dict[str, object]:
    copied = INPUTS[:3]
    with tempfile.TemporaryDirectory(prefix="pyz80-prepared-v3-bench-") as tmp:
        directory = Path(tmp)
        for relative in copied:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "prepared_v3_bench.c").write_text(
            BENCH_SOURCE, encoding="utf-8", newline="\n")
        for source_name in (
                "pyz80_draw_prepared_frame_v3.c", "prepared_v3_bench.c"):
            _run([str(sdcc), *PINNED_ARGUMENTS, "-c", source_name],
                 directory, environment)
        link_command = [str(sdcc), *LINK_ARGUMENTS,
                        "-o", "prepared_v3_bench.ihx",
                        "pyz80_draw_prepared_frame_v3.rel",
                        "prepared_v3_bench.rel"]
        _run(link_command, directory, environment)
        ihx = directory / "prepared_v3_bench.ihx"
        map_path = directory / "prepared_v3_bench.map"
        ihx_bytes = ihx.read_bytes()
        map_bytes = map_path.read_bytes()
        map_text = map_bytes.decode("latin1")
        symbols = _symbols(map_text)
        code_start, code_bytes = _map_area(map_text, "_CODE")
        data_start, data_bytes = _map_area(map_text, "_DATA")
        if data_start + data_bytes >= 0xFF00:
            raise DrawPreparedV3CheckError("benchmark data collides with stack")
        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x2000",
            default_stack="0xFF00")
        for address, payload in _parse_ihx(ihx):
            if address + len(payload) > 0x10000:
                raise DrawPreparedV3CheckError("benchmark exceeds Z80 space")
            machine.mem.write_block_linear(address, payload)
        machine.mem.write_block_linear(0x1800, asm_binary)
        machine.mem.write_block_linear(0x1A00, queue_asm_binary)

        measurements: dict[str, dict[str, int]] = {}
        original_step = machine.step
        minimum_sp = machine.reg.SP

        def tracked_step() -> int:
            nonlocal minimum_sp
            clocks = original_step()
            minimum_sp = min(minimum_sp, machine.reg.SP)
            return clocks

        machine.step = tracked_step  # type: ignore[method-assign]

        def measure(public: str, symbol: str) -> None:
            nonlocal minimum_sp
            initial_sp = machine.reg.SP
            minimum_sp = initial_sp
            before = machine.tstates
            steps = machine.call(symbols[symbol], max_steps=10_000_000)
            tstates = machine.tstates - before
            if machine.reg.L != 1 or machine.reg.SP != initial_sp:
                raise DrawPreparedV3CheckError(
                    f"benchmark {public} failed/result/SP mismatch: "
                    f"L={machine.reg.L}, SP=0x{machine.reg.SP:04X}, "
                    f"initial=0x{initial_sp:04X}")
            measurements[public] = {
                "steps": steps,
                "tstates": tstates,
                "stack_bytes_including_outer_return": initial_sp - minimum_sp,
                "conservative_reference_path_bound_tstates":
                    steps * MAX_Z80_INSTRUCTION_TSTATES,
            }

        measure("setup", "PyZ80PreparedV3Bench_Setup")
        for public, symbol in (
                ("noop", "PyZ80PreparedV3Bench_Noop"),
                ("asm_fused_preflight_228", "PyZ80PreparedV3Bench_ASMPre"),
                ("asm_atomic_queue_228", "PyZ80PreparedV3Bench_ASMQueue"),
                ("asm_full_draw_228", "PyZ80PreparedV3Bench_ASMFull"),
                ("raw_linear_copy_228", "PyZ80PreparedV3Bench_Copy228"),
                ("prepared_scan_preflight_228",
                 "PyZ80PreparedV3Bench_RunPre"),
                ("fused_build_preflight_228",
                 "PyZ80PreparedV3Bench_BuildPre"),
                ("fused_build_full_generic_228",
                 "PyZ80PreparedV3Bench_BuildGen"),
                ("fused_build_full_ft812_228",
                 "PyZ80PreparedV3Bench_BuildFT"),
                ("cache_spawn_228", "PyZ80PreparedV3Bench_CacheSpawn"),
                ("cache_state_mutate_install_228",
                 "PyZ80PreparedV3Bench_CacheState"),
                ("cache_bank_mutate_install_228",
                 "PyZ80PreparedV3Bench_CacheBank"),
                ("cache_descriptor_mutate_install_228",
                 "PyZ80PreparedV3Bench_CacheDesc"),
                ("cache_level_pack_mutate_install_228",
                 "PyZ80PreparedV3Bench_CacheLevel")):
            measure(public, symbol)

    baseline = measurements["noop"]["tstates"]
    for name, row in measurements.items():
        row["net_tstates"] = max(0, row["tstates"] - baseline)
    c_preflight = measurements["fused_build_preflight_228"]["net_tstates"]
    preflight = measurements["asm_fused_preflight_228"]["net_tstates"]
    generic = measurements["fused_build_full_generic_228"]["net_tstates"]
    c_concrete = measurements["fused_build_full_ft812_228"]["net_tstates"]
    asm_queue = measurements["asm_atomic_queue_228"]["net_tstates"]
    asm_full = measurements["asm_full_draw_228"]["net_tstates"]
    generic_delta = generic - c_preflight
    concrete_delta = c_concrete - c_preflight
    selected_generic = preflight + generic_delta
    selected_concrete = preflight + concrete_delta
    return {
        "benchmark_source_sha256": _sha256(BENCH_SOURCE.encode("utf-8")),
        "link_command": link_command,
        "linked_image": {
            "ihx_bytes": len(ihx_bytes), "ihx_sha256": _sha256(ihx_bytes),
            "map_bytes": len(map_bytes), "map_sha256": _sha256(map_bytes),
            "code_start_hex": f"0x{code_start:04X}",
            "code_bytes": code_bytes,
            "data_start_hex": f"0x{data_start:04X}",
            "data_bytes": data_bytes,
            "symbols": {key: f"0x{value:04X}"
                        for key, value in sorted(symbols.items())},
        },
        "measurements": measurements,
        "breakdown": {
            "fused_source_producer_and_preflight_net_tstates": preflight,
            "c_fused_source_producer_and_preflight_net_tstates": c_preflight,
            "generic_two_chunk_commit_net_tstates": generic,
            "generic_publication_delta_tstates": generic_delta,
            "selected_asm_plus_generic_commit_tstates": selected_generic,
            "c_concrete_ft812_queue_and_commit_net_tstates": c_concrete,
            "concrete_queue_delta_after_c_preflight_tstates": concrete_delta,
            "selected_asm_plus_concrete_queue_tstates": selected_concrete,
            "asm_atomic_queue_net_tstates": asm_queue,
            "measured_asm_full_draw_net_tstates": asm_full,
            "cache_spawn_per_object_tstates": round(
                measurements["cache_spawn_228"]["net_tstates"] / 228, 3),
            "cache_state_mutate_install_per_object_tstates": round(
                measurements["cache_state_mutate_install_228"]
                ["net_tstates"] / 228, 3),
            "cache_bank_mutate_install_per_object_tstates": round(
                measurements["cache_bank_mutate_install_228"]
                ["net_tstates"] / 228, 3),
            "cache_descriptor_mutate_install_per_object_tstates": round(
                measurements["cache_descriptor_mutate_install_228"]
                ["net_tstates"] / 228, 3),
            "cache_level_pack_mutate_install_per_object_tstates": round(
                measurements["cache_level_pack_mutate_install_228"]
                ["net_tstates"] / 228, 3),
        },
        "target": {
            "cpu_hz": CPU_HZ,
            "frame_hz": FRAME_HZ,
            "whole_frame_tstates": WHOLE_FRAME_TSTATES,
            "preflight_target_tstates": PREFLIGHT_TARGET_TSTATES,
            "measured_preflight_tstates": preflight,
            "preflight_met": preflight <= PREFLIGHT_TARGET_TSTATES,
            "measured_full_concrete_tstates": asm_full,
            "whole_frame_met_by_draw_path_alone":
                asm_full <= WHOLE_FRAME_TSTATES,
            "preflight_fraction_of_whole_frame": round(
                preflight / WHOLE_FRAME_TSTATES, 6),
            "full_draw_fraction_of_whole_frame": round(
                asm_full / WHOLE_FRAME_TSTATES, 6),
        },
    }


def _static_checks(source: str, header: str, assembly: str,
                   queue_assembly: str) -> dict[str, bool]:
    build_start = source.index("PyZ80DrawPreparedV3Status PyZ80DrawPreparedV3_Build")
    build_end = source.index("uint8_t PyZ80DrawPreparedV3FT812_Begin", build_start)
    build = source[build_start:build_end]
    checks = {
        "ready_record_compile_time_6_bytes":
            "sizeof(PyZ80DrawPreparedV3Record) == 6" in source,
        "private_tape_compile_time_1368_bytes":
            "PYZ80_DRAW_PREPARED_V3_MAX_BYTES == 1368u" in source,
        "source_record_compile_time_8_bytes":
            "sizeof(PyZ80DrawPreparedV3SourceRecord) == 8" in source,
        "global_identity_bound_is_10776":
            "PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT 10776u" in header,
        "hot_build_has_no_draw_vm": "draw_vm" not in build,
        "hot_build_has_no_hqt_resolver":
            "FindCatalog" not in build and "Resolve" not in build,
        "hot_build_has_no_per_record_callback":
            "writer->" not in build[build.index("for (index"):build.index(
                "return PyZ80DrawPreparedV3_Publish")],
        "asm_hot_loop_has_no_call":
            "CALL" not in assembly[assembly.index(".recordLoop:"):
                                   assembly.index(".budget:")],
        "asm_fast_params_are_compile_time_23_bytes":
            "sizeof(PyZ80DrawPreparedV3FastParams) == 23" in source,
        "asm_fast_queue_params_are_compile_time_12_bytes":
            "sizeof(PyZ80DrawPreparedV3FastQueueParams) == 12" in source,
        "asm_queue_has_one_ready_store":
            queue_assembly.count("LD   (HL), PYZ80_V3_Q_READY") == 1,
        "asm_queue_has_no_ready_prefix":
            "PYZ80_V3_Q_READY" not in queue_assembly[
                queue_assembly.index("PyZ80DrawPreparedV3_ASMQueue:"):
                queue_assembly.index(".publish:")],
        "all_identity_mutations_use_common_invalidator":
            source.count("PyZ80DrawPreparedV3_CacheInvalidate(") == 5,
        "strict_ram_dl_less_than_2048":
            "total_words >= budget->ram_dl_word_limit" in source,
        "fixed_1209_limit":
            "PYZ80_DRAW_PREPARED_V3_SAFE_LINE_CYCLES 1209u" in header,
        "single_ready_publication_store": len(re.findall(
            r"header\.state\s*=\s*PYZ80_FT_QUEUE_READY\s*;", source)) == 1,
    }
    if not all(checks.values()):
        raise DrawPreparedV3CheckError(
            "v3 static checks failed: " + ", ".join(
                key for key, value in checks.items() if not value))
    return checks


def probe(project_root: Path | str = ROOT) -> dict[str, object]:
    root = Path(project_root).resolve()
    manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(manifest.target).resolve()
    sdcc_bytes = sdcc.read_bytes()
    if _sha256(sdcc_bytes).upper() != manifest.target.toolchain_sha256.upper():
        raise DrawPreparedV3CheckError("SDCC hash does not match manifest")
    environment = os.environ.copy()
    environment["PATH"] = str(sdcc.parent) + os.pathsep + environment.get("PATH", "")
    version = _run([str(sdcc), "--version"], root, environment).stdout.splitlines()[0]
    inputs = [_file_record(root, relative) for relative in INPUTS]
    source = (root / INPUTS[0]).read_text(encoding="utf-8")
    header = (root / INPUTS[1]).read_text(encoding="utf-8")
    assembly_source = (root / INPUTS[3]).read_text(encoding="utf-8")
    queue_assembly_source = (root / INPUTS[4]).read_text(encoding="utf-8")
    static = _static_checks(
        source, header, assembly_source, queue_assembly_source)
    host = run_host_reference_matrix(root)
    mutation_inventory = _active_python_mutation_inventory(root)
    asm_binary, queue_asm_binary, asm = _assemble_fast(root)
    asm_oracle = _asm_reference_oracle(root, asm_binary, queue_asm_binary)
    target = _compile_target(root, sdcc, environment)
    timing = _benchmark(
        root, sdcc, environment, asm_binary, queue_asm_binary)
    v2 = json.loads((root / V2_REFERENCE_PATH).read_text(encoding="utf-8"))
    v2_vm_floor = int(v2["z80_timing"]["breakdown"]
                      ["vm_stream_228_reference_net_tstates"])
    preflight_met = bool(timing["target"]["preflight_met"])
    full_met = bool(timing["target"]["whole_frame_met_by_draw_path_alone"])
    status = (STATUS_PASS if preflight_met and full_met else
              STATUS_QUEUE if preflight_met else STATUS_TIMING)
    checks = {
        **static,
        **{key: bool(value) for key, value in host["matrix"].items()},
        **{f"asm_{key}": bool(value)
           for key, value in asm_oracle["matrix"].items()},
        "pinned_sdcc_object_compiled": True,
        "pinned_sdcc_code_fits_one_16k_bank": True,
        "pinned_sdcc_mutable_data_zero": True,
        "v2_reference_preserved_and_not_live": v2.get("live") is False,
        "v3_fused_preflight_at_most_100000_tstates": preflight_met,
        "v3_full_draw_path_fits_14mhz_55hz_frame": full_met,
        "actual_translator_spawn_sites_instrumented": False,
        "actual_translator_bank_mutation_sites_instrumented": False,
        "actual_translator_descriptor_mutation_sites_instrumented": False,
        "actual_translator_state_mutation_sites_instrumented": False,
        "actual_level_pack_mutation_sites_instrumented": False,
        "active_python_mutation_inventory_is_nonempty":
            int(mutation_inventory["site_count"]) > 0,
        "immutable_append_directory_final_linked": False,
        "private_ts_ram_page_final_bound": False,
        "spawn_and_mutation_hqt_resolver_wcet_bound": False,
        "preflight_to_queue_parameter_ownership_final_bound": False,
        "gameplay_irq_audio_and_dma_frame_budget_proved": False,
    }
    payload = {
        "input_sha256": {row["path"]: row["sha256"] for row in inputs},
        "compiler_sha256": _sha256(sdcc_bytes),
        "target": target,
        "host_matrix": host["matrix"],
        "asm": asm,
        "asm_oracle": asm_oracle,
        "mutation_inventory": mutation_inventory,
        "timing": timing,
        "v2_vm_callback_abi_measured_floor_tstates": v2_vm_floor,
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
            "identity_resolution_per_frame": 0,
            "identity_resolution_events": [
                "spawn", "bank_key mutation", "descriptor mutation",
                "state mutation", "level-pack mutation"],
            "global_hqt_keys": 10776,
            "cached_identity": "uint16 template_index",
            "source_record_bytes": 8,
            "ready_record_bytes": 6,
            "private_tape_max_records": 228,
            "private_tape_max_bytes": 1368,
            "append_resolution":
                "O(1) index into immutable level working-set directory",
            "per_record_function_callbacks": 0,
            "producer_passes": 1,
            "selected_hot_producer": "custom-register-ABI Z80 ASM",
            "publication": "one READY store after complete private tape",
            "integration_decision": (
                "fail closed: do not link into translator/SPG until immutable "
                "queue/APPEND preparation moves outside the gameplay frame "
                "and the remaining gameplay/IRQ/audio/DMA schedule is proved"),
            "next_architectural_step": (
                "prebuild immutable FT812 CMD_APPEND address/size streams at "
                "level-pack load and use FT812/DMA for frame transport; the "
                "frame may patch only dynamic VERTEX_TRANSLATE values"),
        },
        "host_reference_tests": host,
        "compiler": {"path": sdcc.as_posix(), "bytes": len(sdcc_bytes),
                     "sha256": _sha256(sdcc_bytes), "version": version,
                     "arguments": list(PINNED_ARGUMENTS)},
        "target_object": target,
        "asm_object": asm,
        "asm_reference_oracle": asm_oracle,
        "active_python_mutation_inventory": mutation_inventory,
        "z80_timing": timing,
        "current_callback_abi_lower_bound": {
            "source": V2_REFERENCE_PATH,
            "description": (
                "exact pinned measurement of the old 228-record VM callback "
                "pipeline alone; it is not a universal algorithmic bound"),
            "tstates": v2_vm_floor,
            "exceeds_100000": v2_vm_floor > PREFLIGHT_TARGET_TSTATES,
        },
        "checks": checks,
        "live": False,
        "live_blockers": [
            {"code": "PZPV301", "detail": (
                "the generated translator has not instrumented every spawn, "
                "bank_key, descriptor, state and level-pack mutation site")},
            {"code": "PZPV302", "detail": (
                "the immutable level working-set append directory and its "
                "RAM_G residency are not final-linked")},
            {"code": "PZPV303", "detail": (
                "the 1,368-byte private tape has no final TS RAM page, ISR "
                "ownership or page-switch WCET binding")},
            {"code": "PZPV304", "detail": (
                f"measured fused preflight is "
                f"{timing['target']['measured_preflight_tstates']} tstates "
                f"against {PREFLIGHT_TARGET_TSTATES}")}
            if not preflight_met else
            {"code": "PZPV304", "detail": (
                "the <=100,000 timing holds only for the isolated pinned "
                "prototype, not a final translated producer")},
            {"code": "PZPV305", "detail": (
                f"measured complete concrete draw path is "
                f"{timing['target']['measured_full_concrete_tstates']} tstates "
                f"against the entire {WHOLE_FRAME_TSTATES}-tstate frame")}
            if not full_met else
            {"code": "PZPV305", "detail": (
                "the measured draw path fits in isolation but gameplay, IRQ, "
                "audio and DMA contention are not included")},
            {"code": "PZPV306", "detail": (
                f"AST inventory found {mutation_inventory['site_count']} "
                "active-Python spawn/mutation writes; zero are instrumented "
                "in the current translator-generated target")},
            {"code": "PZPV307", "detail": (
                "cache invalidation/install plumbing is measured separately, "
                "but the real off-frame HQT resolver and page-switch WCET are "
                "not linked or bounded")},
            {"code": "PZPV308", "detail": (
                "the successful isolated ASM draw leaves only "
                f"{WHOLE_FRAME_TSTATES - timing['target']['measured_full_concrete_tstates']} "
                "tstates for all gameplay, IRQ, TSFM/GS and DMA contention; "
                "therefore the final whole-frame schedule is not proved. "
                "Next step is off-frame immutable queue/APPEND construction "
                "plus FT812/DMA transport, not an SPG rebuild")},
        ],
    }


def validate_report(report: object, project_root: Path | str = ROOT) -> None:
    if not isinstance(report, dict) or report.get("format") != FORMAT:
        raise DrawPreparedV3CheckError("v3 report format mismatch")
    if report.get("status") not in (STATUS_PASS, STATUS_QUEUE, STATUS_TIMING) or \
            report.get("live") is not False:
        raise DrawPreparedV3CheckError("v3 report status/live mismatch")
    payload = report.get("input", {}).get("semantic_payload")  # type: ignore[union-attr]
    if not isinstance(payload, dict) or report.get("semantic_sha256") != _sha256(
            _json_bytes(payload)):
        raise DrawPreparedV3CheckError("v3 report semantic hash mismatch")
    root = Path(project_root).resolve()
    rows = report.get("input", {}).get("files")  # type: ignore[union-attr]
    if not isinstance(rows, list) or len(rows) != len(INPUTS):
        raise DrawPreparedV3CheckError("v3 report input set mismatch")
    for row, relative in zip(rows, INPUTS):
        if row != _file_record(root, relative):
            raise DrawPreparedV3CheckError(f"stale v3 input: {relative}")
    target = report.get("z80_timing", {}).get("target", {})  # type: ignore[union-attr]
    passed = bool(target.get("preflight_met")) and bool(
        target.get("whole_frame_met_by_draw_path_alone"))
    expected_status = (STATUS_PASS if passed else STATUS_QUEUE
                       if bool(target.get("preflight_met")) else STATUS_TIMING)
    if report.get("status") != expected_status:
        raise DrawPreparedV3CheckError("v3 timing/status disagreement")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
        default=Path("Build/rtype_python_draw_prepared_frame_v3_status.json"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        result = probe(ROOT)
        validate_report(result, ROOT)
        _atomic_json(output, result)
    except (DrawPreparedV3CheckError, OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    target = result["z80_timing"]["target"]
    print(
        f"Prepared frame v3: CODE={result['target_object']['code_bytes']} B, "
        f"tape=1368 B, preflight={target['measured_preflight_tstates']}/"
        f"{PREFLIGHT_TARGET_TSTATES}, concrete="
        f"{target['measured_full_concrete_tstates']}/"
        f"{WHOLE_FRAME_TSTATES}; status={result['status']}, live=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
