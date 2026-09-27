#!/usr/bin/env python3
"""Host/reference proofs for the prelocalized prepared-frame v3 ABI."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = CompilerManifest.load(
    ROOT / "Source" / "Tools" / "rtype_python_compiler.json")
try:
    SDCC: Path | None = locate_sdcc(MANIFEST.target)
except Exception:
    SDCC = None
HOST_CC = next((item for item in (
    Path(os.environ["PYZ80_HOST_CC"])
    if os.environ.get("PYZ80_HOST_CC") else None,
    Path(shutil.which("tcc")) if shutil.which("tcc") else None,
    ROOT.parent / "tcc-0.9.27" / "tcc" / "tcc.exe",
) if item is not None and item.is_file()), None)


HARNESS = r'''
#include <stdint.h>
#include <string.h>

#include "pyz80_draw_prepared_frame_v3.h"

static volatile PyZ80DrawPreparedV3Record records[
    PYZ80_DRAW_PREPARED_V3_MAX_RECORDS];
static volatile PyZ80DrawPreparedV3SourceRecord source_records[
    PYZ80_DRAW_PREPARED_V3_MAX_RECORDS];
static volatile PyZ80DrawPreparedV3AppendEntry directory[2];
static PyZ80DrawPreparedV3Certificate certificate;
static PyZ80DrawPreparedV3FrameBudget budget;
static PyZ80DrawPreparedV3Result result;

typedef struct TestWriter {
    uint16_t begin_calls;
    uint16_t append_calls;
    uint16_t commit_calls;
    uint16_t abort_calls;
    uint16_t records;
    uint16_t chunks;
    uint8_t begun;
    uint8_t public_ready;
    uint16_t public_count;
    uint8_t fail_begin;
    uint16_t fail_append_call;
    uint8_t fail_commit;
    uint8_t prefix_observed;
} TestWriter;

static TestWriter capture;
static PyZ80DrawPreparedV3Writer writer;

static uint8_t begin(void *context,
        const PyZ80DrawPreparedV3Preflight *preflight)
{
    TestWriter *state = (TestWriter *)context;
    (void)preflight;
    state->begin_calls++;
    state->begun = 1u;
    if (state->public_ready || state->public_count)
        state->prefix_observed = 1u;
    return state->fail_begin ? 0u : 1u;
}

static uint8_t append(void *context,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        const volatile PyZ80DrawPreparedV3Record *input,
        uint16_t count, uint16_t first)
{
    TestWriter *state = (TestWriter *)context;
    uint16_t index;
    state->append_calls++;
    if (state->begun != 1u || state->public_ready || state->public_count ||
            first != state->records || append_directory != directory ||
            append_directory_count != 2u)
        state->prefix_observed = 1u;
    if (state->fail_append_call == state->append_calls) return 0u;
    for (index = 0u; index < count; ++index) {
        uint16_t absolute = (uint16_t)(first + index);
        if (input[index].append_ref != (absolute & 1u) ||
                input[index].vertex_x != (int16_t)(absolute - 100) ||
                input[index].vertex_y != (int16_t)(80 - absolute))
            return 0u;
    }
    state->records = (uint16_t)(state->records + count);
    state->chunks++;
    return 1u;
}

static uint8_t commit(void *context,
        const PyZ80DrawPreparedV3Preflight *preflight)
{
    TestWriter *state = (TestWriter *)context;
    state->commit_calls++;
    if (state->begun != 1u || state->public_ready || state->public_count ||
            state->records != preflight->record_count ||
            state->chunks != preflight->chunk_count)
        state->prefix_observed = 1u;
    if (state->fail_commit) return 0u;
    state->public_count = state->records;
    state->public_ready = 1u;
    state->begun = 0u;
    return 1u;
}

static void abort_writer(void *context)
{
    TestWriter *state = (TestWriter *)context;
    state->abort_calls++;
    state->records = 0u;
    state->chunks = 0u;
    state->public_count = 0u;
    state->public_ready = 0u;
    state->begun = 0u;
}

static void initialize(void)
{
    uint16_t index;
    memset((void *)records, 0, sizeof(records));
    memset((void *)source_records, 0, sizeof(source_records));
    memset((void *)directory, 0, sizeof(directory));
    memset(&certificate, 0, sizeof(certificate));
    memset(&budget, 0, sizeof(budget));
    memset(&result, 0, sizeof(result));
    memset(&capture, 0, sizeof(capture));
    directory[0].ram_g_address_lo = 0x1000u;
    directory[0].ram_g_address_hi = 0u;
    directory[0].byte_size = 4u;
    directory[1].ram_g_address_lo = 0x2000u;
    directory[1].ram_g_address_hi = 0u;
    directory[1].byte_size = 8u;
    for (index = 0u; index < PYZ80_DRAW_PREPARED_V3_MAX_RECORDS; ++index) {
        records[index].append_ref = (uint16_t)(index & 1u);
        records[index].vertex_x = (int16_t)(index - 100);
        records[index].vertex_y = (int16_t)(80 - index);
        source_records[index].append_ref = (uint16_t)(index & 1u);
        source_records[index].vertex_x = (int16_t)(index - 100);
        source_records[index].vertex_y = (int16_t)(80 - index);
        source_records[index].template_index = (uint16_t)(index & 31u);
    }
    certificate.format_version = PYZ80_DRAW_PREPARED_V3_CERTIFICATE_VERSION;
    certificate.sizing_proof_complete = 1u;
    certificate.identity_cache_mutation_proved = 1u;
    certificate.private_render_order_producer_proved = 1u;
    certificate.append_directory_proved = 1u;
    certificate.raster_768_lines_proved = 1u;
    certificate.certified_max_records = PYZ80_DRAW_PREPARED_V3_MAX_RECORDS;
    certificate.max_cmd_append_expanded_words = 456u;
    certificate.max_fragment_expanded_dl_words = 938u;
    certificate.worst_raster_line = 767u;
    certificate.worst_raster_cycles = 0u;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_PREPARED_V3_SAFE_LINE_CYCLES;
    writer.begin = begin;
    writer.append = append;
    writer.commit = commit;
    writer.abort = abort_writer;
    writer.context = &capture;
}

static PyZ80DrawPreparedV3Status run(uint16_t count)
{
    return PyZ80DrawPreparedV3_Run(
        records, count, directory, 2u, &certificate, &budget,
        &writer, &result);
}

static PyZ80DrawPreparedV3Status build(uint16_t count)
{
    return PyZ80DrawPreparedV3_Build(
        source_records, count, directory, 2u, records,
        PYZ80_DRAW_PREPARED_V3_MAX_RECORDS, &certificate, &budget,
        &writer, &result);
}

static int no_writer_touched(void);

static int check_success(void)
{
    PyZ80DrawPreparedV3Status status;
    initialize();
    status = run(228u);
    if (status != PYZ80_DRAW_PREPARED_V3_OK || result.committed != 1u ||
            result.validated_records != 228u ||
            result.private_records_written != 228u ||
            result.private_chunks_written != 2u ||
            capture.begin_calls != 1u || capture.append_calls != 2u ||
            capture.commit_calls != 1u || capture.abort_calls != 0u ||
            capture.prefix_observed != 0u || capture.public_ready != 1u ||
            capture.public_count != 228u) return 10;
    if (result.preflight.record_count != 228u ||
            result.preflight.chunk_count != 2u ||
            result.preflight.cmd_append_expanded_words != 342u ||
            result.preflight.fragment_expanded_dl_words != 824u ||
            result.preflight.fragment_physical_words != 1166u ||
            result.preflight.total_frame_dl_words != 824u ||
            result.preflight.worst_raster_line != 767u ||
            result.preflight.worst_line_cycles != 824u) return 11;
    return 0;
}

static int check_fused_build_and_stale_cache(void)
{
    PyZ80DrawPreparedV3IdentityCache cache;
    uint16_t generation;
    uint16_t index;
    initialize();
    if (build(228u) != PYZ80_DRAW_PREPARED_V3_OK ||
            result.committed != 1u || result.validated_records != 228u ||
            capture.commit_calls != 1u || capture.abort_calls != 0u)
        return 12;
    for (index = 0u; index < 228u; ++index) {
        if (records[index].append_ref != source_records[index].append_ref ||
                records[index].vertex_x != source_records[index].vertex_x ||
                records[index].vertex_y != source_records[index].vertex_y)
            return 13;
    }
    initialize();
    source_records[5].template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    if (build(228u) != PYZ80_DRAW_PREPARED_V3_INVALID_RECORD ||
            result.validated_records != 5u || result.failure_record_index != 5u ||
            !no_writer_touched()) return 14;

    memset(&cache, 0, sizeof(cache));
    PyZ80DrawPreparedV3_CacheSpawn(&cache, 0x1234u, 0x5678u, 99u);
    if (cache.valid != 1u || cache.template_index != 99u ||
            cache.generation != 1u ||
            cache.last_mutation != PYZ80_DRAW_PREPARED_V3_MUTATION_SPAWN)
        return 15;
    PyZ80DrawPreparedV3_CacheMutateBankKey(&cache, 0x2222u);
    if (cache.valid || cache.template_index != PYZ80_FT_HQ_TEMPLATE_NOT_FOUND ||
            cache.bank_key != 0x2222u || cache.generation != 2u ||
            cache.last_mutation != PYZ80_DRAW_PREPARED_V3_MUTATION_BANK_KEY)
        return 16;
    generation = cache.generation;
    if (PyZ80DrawPreparedV3_CacheInstallResolved(
            &cache, (uint16_t)(generation - 1u), 100u) != 0u || cache.valid)
        return 17;
    if (PyZ80DrawPreparedV3_CacheInstallResolved(
            &cache, generation, 100u) == 0u || !cache.valid ||
            cache.template_index != 100u) return 18;
    PyZ80DrawPreparedV3_CacheMutateDescriptor(&cache, 0x3333u);
    if (cache.valid || cache.descriptor != 0x3333u ||
            cache.last_mutation != PYZ80_DRAW_PREPARED_V3_MUTATION_DESCRIPTOR)
        return 19;
    if (PyZ80DrawPreparedV3_CacheInstallResolved(
            &cache, cache.generation, 101u) == 0u) return 32;
    PyZ80DrawPreparedV3_CacheMutateState(&cache);
    if (cache.valid ||
            cache.last_mutation != PYZ80_DRAW_PREPARED_V3_MUTATION_STATE)
        return 33;
    if (PyZ80DrawPreparedV3_CacheInstallResolved(
            &cache, cache.generation, 102u) == 0u) return 34;
    PyZ80DrawPreparedV3_CacheMutateLevelPack(&cache);
    if (cache.valid || cache.last_mutation !=
            PYZ80_DRAW_PREPARED_V3_MUTATION_LEVEL_PACK) return 35;
    cache.generation = 0xFFFFu;
    PyZ80DrawPreparedV3_CacheMutateState(&cache);
    if (cache.generation != 1u || cache.valid) return 36;
    PyZ80DrawPreparedV3_CacheSpawn(
        &cache, 0u, 0u, PYZ80_FT_HQ_TEMPLATE_NOT_FOUND);
    if (cache.valid || cache.template_index != PYZ80_FT_HQ_TEMPLATE_NOT_FOUND)
        return 37;
    return 0;
}

static int no_writer_touched(void)
{
    return capture.begin_calls == 0u && capture.append_calls == 0u &&
        capture.commit_calls == 0u && capture.abort_calls == 0u &&
        result.committed == 0u;
}

static int check_preflight_failures(void)
{
    PyZ80DrawPreparedV3Status status;
    initialize();
    records[5].append_ref = 2u;
    status = run(228u);
    if (status != PYZ80_DRAW_PREPARED_V3_INVALID_RECORD ||
            result.validated_records != 5u ||
            result.failure_record_index != 5u || !no_writer_touched())
        return 20;
    initialize();
    directory[0].byte_size = 0u;
    if (run(1u) != PYZ80_DRAW_PREPARED_V3_INVALID_RECORD ||
            !no_writer_touched()) return 21;
    initialize();
    directory[0].byte_size = 6u;
    if (run(1u) != PYZ80_DRAW_PREPARED_V3_INVALID_RECORD ||
            !no_writer_touched()) return 22;
    initialize();
    directory[0].ram_g_address_lo = 0xFFFFu;
    directory[0].ram_g_address_hi = 0x000Fu;
    directory[0].byte_size = 4u;
    if (run(1u) != PYZ80_DRAW_PREPARED_V3_INVALID_RECORD ||
            !no_writer_touched()) return 23;
    initialize();
    if (run(229u) != PYZ80_DRAW_PREPARED_V3_RECORD_BOUND ||
            !no_writer_touched()) return 24;
    initialize();
    {
        uint16_t index;
        for (index = 0u; index < 228u; ++index)
            records[index].append_ref = 0u;
    }
    certificate.max_cmd_append_expanded_words = 227u;
    certificate.max_fragment_expanded_dl_words = 709u;
    if (run(228u) != PYZ80_DRAW_PREPARED_V3_APPEND_BOUND ||
            result.validated_records != 227u || !no_writer_touched())
        return 25;
    initialize();
    budget.ram_dl_word_limit = 2047u;
    if (run(0u) != PYZ80_DRAW_PREPARED_V3_CERTIFICATE ||
            !no_writer_touched()) return 26;
    initialize();
    certificate.max_cmd_append_expanded_words = 1566u;
    certificate.max_fragment_expanded_dl_words = 2048u;
    if (run(0u) != PYZ80_DRAW_PREPARED_V3_CERTIFICATE ||
            !no_writer_touched()) return 27;
    initialize();
    certificate.max_cmd_append_expanded_words = 727u;
    certificate.max_fragment_expanded_dl_words = 1209u;
    if (run(0u) != PYZ80_DRAW_PREPARED_V3_OK ||
            result.committed != 1u) return 28;
    initialize();
    certificate.max_cmd_append_expanded_words = 728u;
    certificate.max_fragment_expanded_dl_words = 1210u;
    if (run(0u) != PYZ80_DRAW_PREPARED_V3_CERTIFICATE ||
            !no_writer_touched()) return 29;
    initialize();
    certificate.worst_raster_line = 768u;
    if (run(0u) != PYZ80_DRAW_PREPARED_V3_CERTIFICATE ||
            !no_writer_touched()) return 30;
    initialize();
    if (PyZ80DrawPreparedV3_Run(
            records, 1u, 0, 0u, &certificate, &budget,
            &writer, &result) != PYZ80_DRAW_PREPARED_V3_INVALID_INPUT ||
            !no_writer_touched()) return 31;
    return 0;
}

static int check_writer_abort_matrix(void)
{
    initialize();
    capture.fail_begin = 1u;
    if (run(228u) != PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN ||
            capture.begin_calls != 1u || capture.abort_calls != 1u ||
            capture.append_calls || capture.commit_calls || result.committed)
        return 40;
    initialize();
    capture.fail_append_call = 1u;
    if (run(228u) != PYZ80_DRAW_PREPARED_V3_WRITER_APPEND ||
            capture.abort_calls != 1u || capture.commit_calls ||
            result.committed || capture.public_ready) return 41;
    initialize();
    capture.fail_append_call = 2u;
    if (run(228u) != PYZ80_DRAW_PREPARED_V3_WRITER_APPEND ||
            capture.append_calls != 2u || capture.abort_calls != 1u ||
            capture.commit_calls || result.committed || capture.public_ready)
        return 42;
    initialize();
    capture.fail_commit = 1u;
    if (run(228u) != PYZ80_DRAW_PREPARED_V3_WRITER_COMMIT ||
            capture.commit_calls != 1u || capture.abort_calls != 1u ||
            result.committed || capture.public_ready) return 43;
    return 0;
}

static int check_concrete_ft812_no_ready_prefix(void)
{
    static PyZ80FtQueue queue;
    PyZ80DrawPreparedV3FT812WriterContext context;
    PyZ80DrawPreparedV3Preflight preflight;
    PyZ80DrawPreparedV3Record record;
    PyZ80DrawPreparedV3AppendEntry entry;
    memset(&queue, 0, sizeof(queue));
    memset(&context, 0, sizeof(context));
    memset(&preflight, 0, sizeof(preflight));
    memset(&entry, 0, sizeof(entry));
    if (PyZ80FT_QueueInitialize(&queue, PYZ80_FT_QUEUE_PAGE_A) == 0u)
        return 50;
    record.append_ref = 0u;
    record.vertex_x = -1;
    record.vertex_y = 2;
    entry.ram_g_address_lo = 0x1234u;
    entry.ram_g_address_hi = 0u;
    entry.byte_size = 4u;
    preflight.record_count = 1u;
    preflight.chunk_count = 1u;
    preflight.cmd_append_expanded_words = 1u;
    preflight.fragment_expanded_dl_words = 16u;
    preflight.fragment_physical_words = 18u;
    context.queue = &queue;
    context.frame_sequence = 9u;
    if (PyZ80DrawPreparedV3FT812_Begin(&context, &preflight) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue.header.count || queue.header.payload_bytes ||
            queue.header.dl_words) return 51;
    if (PyZ80DrawPreparedV3FT812_Append(
            &context, &entry, 1u, &record, 1u, 0u) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue.header.count || queue.header.payload_bytes ||
            queue.header.dl_words) return 52;
    if (queue.words[10] != 0x2B01FFFEul ||
            queue.words[11] != 0x2C000004ul ||
            queue.words[12] != 0xFFFFFF1Eul ||
            queue.words[13] != 0x00001234ul || queue.words[14] != 4u)
        return 53;
    if (PyZ80DrawPreparedV3FT812_Commit(&context, &preflight) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_READY ||
            queue.header.count != 18u || queue.header.payload_bytes != 72u ||
            queue.header.dl_words != 16u) return 54;
    return 0;
}

int main(void)
{
    int status;
    if (sizeof(PyZ80DrawPreparedV3Record) != 6u ||
            sizeof(PyZ80DrawPreparedV3AppendEntry) != 6u ||
            PYZ80_DRAW_PREPARED_V3_MAX_BYTES != 1368u) return 1;
    status = check_success();
    if (status) return status;
    status = check_fused_build_and_stale_cache();
    if (status) return status;
    status = check_preflight_failures();
    if (status) return status;
    status = check_writer_abort_matrix();
    if (status) return status;
    return check_concrete_ft812_no_ready_prefix();
}
'''


SOURCES = (
    "Source/C/ft812/pyz80_draw_prepared_frame_v3.c",
    "Source/C/ft812/pyz80_draw_prepared_frame_v3.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
)


def run_host_reference_matrix(root: Path = ROOT) -> dict[str, object]:
    if HOST_CC is None:
        raise RuntimeError("portable host C compiler is unavailable")
    with tempfile.TemporaryDirectory(prefix="pyz80-prepared-v3-host-") as tmp:
        directory = Path(tmp)
        for relative in SOURCES:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "prepared_v3_check.c").write_text(
            HARNESS, encoding="utf-8", newline="\n")
        command = [
            str(HOST_CC), "-D_Static_assert(x,y)=",
            "pyz80_draw_prepared_frame_v3.c", "pyz80_ft812.c",
            "rtype_python_hq_templates.c", "prepared_v3_check.c",
            "-o", "prepared_v3_check.exe",
        ]
        compiled = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180)
        if compiled.returncode != 0:
            raise RuntimeError("host compile failed:\n" + compiled.stdout)
        executable = directory / "prepared_v3_check.exe"
        executed = subprocess.run(
            [str(executable)], cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180)
        if executed.returncode != 0:
            raise RuntimeError(
                f"host matrix failed with {executed.returncode}:\n" +
                executed.stdout)
        return {
            "compiler": HOST_CC.as_posix(),
            "compile_command": command,
            "compile_exit_code": compiled.returncode,
            "run_exit_code": executed.returncode,
            "matrix": {
                "ready_record_exactly_6_bytes": True,
                "append_directory_entry_exactly_6_bytes": True,
                "private_frame_exactly_1368_bytes_at_228": True,
                "fused_source_to_private_tape_pass": True,
                "no_vm_or_hqt_identity_lookup_in_frame_gate": True,
                "spawn_installs_resolved_identity_cache": True,
                "bank_descriptor_state_and_level_mutations_invalidate": True,
                "stale_generation_install_is_rejected": True,
                "stale_cache_record_fails_before_public_writer": True,
                "one_linear_preflight_before_writer": True,
                "all_preflight_failures_leave_writer_untouched": True,
                "writer_failures_abort_without_commit": True,
                "one_successful_atomic_commit_without_ready_prefix": True,
                "record_append_and_directory_boundaries": True,
                "ram_dl_limit_is_exactly_2048_and_strict": True,
                "raster_1209_pass_and_1210_fail": True,
                "raster_line_767_pass_and_768_fail": True,
            },
        }


class DrawPreparedV3Tests(unittest.TestCase):
    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_prepared_frame_matrix(self) -> None:
        result = run_host_reference_matrix()
        self.assertEqual(result["run_exit_code"], 0)
        self.assertTrue(all(result["matrix"].values()))

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_pinned_sdcc_compiles_v3(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-prepared-v3-z80-") as tmp:
            directory = Path(tmp)
            for relative in (
                "Source/C/ft812/pyz80_draw_prepared_frame_v3.c",
                "Source/C/ft812/pyz80_draw_prepared_frame_v3.h",
                "Source/C/ft812/pyz80_ft812.h",
            ):
                source = ROOT / relative
                shutil.copy2(source, directory / source.name)
            environment = os.environ.copy()
            environment["PATH"] = (
                str(SDCC.parent) + os.pathsep + environment.get("PATH", ""))
            completed = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--fno-omit-frame-pointer", "--stack-auto",
                 "--opt-code-speed", "--no-c-code-in-asm", "-c",
                 "pyz80_draw_prepared_frame_v3.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=240,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            rel = (directory / "pyz80_draw_prepared_frame_v3.rel").read_text(
                encoding="latin1")
            self.assertIn("A _CODE size ", rel)
            self.assertIn("A _DATA size 0 ", rel)


if __name__ == "__main__":
    unittest.main()
