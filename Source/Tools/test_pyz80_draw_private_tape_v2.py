#!/usr/bin/env python3
"""Host/reference proofs for single-evaluation private-frame tape v2."""

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

#include "pyz80_draw_private_tape_v2.h"
#include "rtype_python_hq_templates.h"

static uint16_t vm_count;
static uint8_t vm_terminal_status;
static uint16_t resolve_calls;
static uint16_t resolve_fail_index;
static uint16_t resolve_append_words;
static uint16_t vm_calls;

static volatile PyZ80DrawTapeV2Record tape[PYZ80_DRAW_TAPE_V2_MAX_RECORDS];
static rtype_python_draw_vm_input vm_input;
static PyZ80DrawTapeV2Certificate certificate;
static PyZ80DrawTapeV2FrameBudget budget;
static PyZ80DrawTapeV2Result result;

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
static PyZ80DrawTapeV2Writer writer;

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit,
        void *context, uint16_t *output_count)
{
    rtype_python_draw_vm_record record;
    uint16_t index;
    (void)input;
    vm_calls++;
    for (index = 0u; index < vm_count; ++index) {
        record.bank_key = (uint16_t)(0x0100u + (index & 15u));
        record.descriptor = (uint16_t)(0x2000u + index);
        record.anchor_x = (int16_t)(index - 100);
        record.anchor_y = (int16_t)(80 - index);
        if (emit(context, &record) == 0u) {
            *output_count = index;
            return RTYPE_PYTHON_DRAW_VM_EMITTER;
        }
    }
    *output_count = vm_count;
    return (rtype_python_draw_vm_status)vm_terminal_status;
}

static uint8_t resolve(void *context,
        const rtype_python_draw_vm_record *record,
        PyZ80DrawTapeV2Resolution *resolved)
{
    uint16_t index = resolve_calls++;
    (void)context;
    (void)record;
    if (index == resolve_fail_index) return 0u;
    resolved->template_index = (uint16_t)(index & 31u);
    resolved->append_expanded_words = resolve_append_words;
    return 1u;
}

static uint8_t begin(void *context,
        const PyZ80DrawTapeV2Preflight *preflight)
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
        const volatile PyZ80DrawTapeV2Record *records,
        uint16_t count, uint16_t first)
{
    TestWriter *state = (TestWriter *)context;
    uint16_t index;
    state->append_calls++;
    if (state->begun != 1u || state->public_ready || state->public_count ||
            first != state->records) state->prefix_observed = 1u;
    if (state->fail_append_call == state->append_calls) return 0u;
    for (index = 0u; index < count; ++index) {
        uint16_t absolute = (uint16_t)(first + index);
        if (records[index].template_index != (absolute & 31u) ||
                records[index].anchor_x != (int16_t)(absolute - 100) ||
                records[index].anchor_y != (int16_t)(80 - absolute) ||
                records[index].append_expanded_words !=
                    resolve_append_words) return 0u;
    }
    state->records = (uint16_t)(state->records + count);
    state->chunks++;
    return 1u;
}

static uint8_t commit(void *context,
        const PyZ80DrawTapeV2Preflight *preflight)
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

static void configure(uint16_t records)
{
    memset((void *)tape, 0, sizeof(tape));
    memset(&vm_input, 0, sizeof(vm_input));
    memset(&capture, 0, sizeof(capture));
    memset(&result, 0, sizeof(result));
    vm_count = records;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
    resolve_calls = 0u;
    resolve_fail_index = 0xFFFFu;
    resolve_append_words = 1u;
    vm_calls = 0u;
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
    certificate.worst_raster_line = 333u;
    certificate.worst_raster_cycles = 0u;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_TAPE_V2_SAFE_LINE_CYCLES;
    capture.fail_append_call = 0xFFFFu;
    writer.begin = begin;
    writer.append = append;
    writer.commit = commit;
    writer.abort = abort_writer;
    writer.context = &capture;
}

static PyZ80DrawTapeV2Status run_gate(void)
{
    return PyZ80DrawTapeV2_Run(
        &vm_input, &certificate, &budget, resolve, 0, tape,
        PYZ80_DRAW_TAPE_V2_MAX_RECORDS, &writer, &result);
}

static int check_success_and_single_evaluation(void)
{
    configure(228u);
    if (run_gate() != PYZ80_DRAW_TAPE_V2_OK) return 10;
    if (vm_calls != 1u || resolve_calls != 228u ||
            result.evaluated_records != 228u ||
            result.private_records_written != 228u ||
            result.private_chunks_written != 2u ||
            result.preflight.record_count != 228u ||
            result.preflight.chunk_count != 2u ||
            result.preflight.cmd_append_expanded_words != 228u ||
            result.preflight.fragment_expanded_dl_words != 710u ||
            result.preflight.fragment_physical_words != 1166u ||
            result.committed != 1u) return 11;
    if (capture.begin_calls != 1u || capture.append_calls != 2u ||
            capture.commit_calls != 1u || capture.abort_calls != 0u ||
            capture.public_ready != 1u || capture.public_count != 228u ||
            capture.prefix_observed != 0u || resolve_calls != 228u)
        return 12;
    return 0;
}

static int check_preflight_failures_do_not_touch_writer(void)
{
    configure(20u);
    resolve_fail_index = 7u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_LOOKUP ||
            capture.begin_calls || capture.append_calls ||
            capture.commit_calls || capture.abort_calls || result.committed)
        return 20;
    configure(229u);
    if (run_gate() != PYZ80_DRAW_TAPE_V2_RECORD_BOUND ||
            result.evaluated_records != 228u || capture.begin_calls)
        return 21;
    configure(115u);
    resolve_append_words = 2u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_APPEND_BOUND ||
            capture.begin_calls || result.committed) return 22;
    configure(20u);
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_RANGE;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_VM ||
            capture.begin_calls || result.committed) return 23;
    configure(1u);
    budget.non_fragment_dl_words = 1338u; /* 1338 + max 710 == 2048 */
    if (run_gate() != PYZ80_DRAW_TAPE_V2_CERTIFICATE || vm_calls ||
            capture.begin_calls) return 24;
    configure(1u);
    certificate.worst_raster_cycles = 499u; /* max walk 710 + 499 == 1209 */
    if (run_gate() != PYZ80_DRAW_TAPE_V2_OK ||
            result.preflight.worst_line_cycles != 515u) return 25;
    configure(1u);
    certificate.worst_raster_cycles = 500u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_CERTIFICATE || vm_calls) return 26;
    configure(1u);
    budget.safe_line_cycles = 1210u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_CERTIFICATE || vm_calls) return 27;
    return 0;
}

static int check_writer_abort_matrix(void)
{
    configure(10u);
    capture.fail_begin = 1u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_WRITER_BEGIN ||
            capture.abort_calls != 1u || capture.commit_calls ||
            result.committed || capture.public_ready) return 30;
    configure(228u);
    capture.fail_append_call = 2u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_WRITER_APPEND ||
            capture.append_calls != 2u || capture.abort_calls != 1u ||
            capture.commit_calls || result.committed || capture.public_ready)
        return 31;
    configure(10u);
    capture.fail_commit = 1u;
    if (run_gate() != PYZ80_DRAW_TAPE_V2_WRITER_COMMIT ||
            capture.commit_calls != 1u || capture.abort_calls != 1u ||
            result.committed || capture.public_ready) return 32;
    return 0;
}

typedef struct CatalogReaderState {
    uint16_t reads;
    uint16_t fail_index;
} CatalogReaderState;

static uint8_t catalog_read(void *context, uint16_t index,
                            PyZ80DrawTapeV2CatalogEntry *entry)
{
    CatalogReaderState *state = (CatalogReaderState *)context;
    state->reads++;
    if (index == state->fail_index ||
            index >= PYZ80_DRAW_TAPE_V2_CATALOG_KEYS) return 0u;
    entry->bank_key = 0u;
    entry->descriptor = (uint16_t)(index << 1);
    entry->template_index = index;
    return 1u;
}

static int check_bounded_catalog_10776(void)
{
    CatalogReaderState state;
    uint16_t index;
    uint16_t found;
    uint8_t comparisons;
    uint8_t maximum = 0u;
    for (index = 0u; index < PYZ80_DRAW_TAPE_V2_CATALOG_KEYS; ++index) {
        state.reads = 0u;
        state.fail_index = 0xFFFFu;
        if (PyZ80DrawTapeV2_FindCatalogBounded(
                catalog_read, &state, PYZ80_DRAW_TAPE_V2_CATALOG_KEYS,
                0u, (uint16_t)(index << 1), &found, &comparisons) == 0u ||
                found != index || comparisons != state.reads ||
                comparisons > PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS)
            return 40;
        if (comparisons > maximum) maximum = comparisons;
    }
    if (maximum != PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS) return 41;
    state.reads = 0u;
    state.fail_index = 0xFFFFu;
    if (PyZ80DrawTapeV2_FindCatalogBounded(
            catalog_read, &state, PYZ80_DRAW_TAPE_V2_CATALOG_KEYS,
            0u, 1u, &found, &comparisons) != 0u ||
            comparisons > PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS)
        return 42;
    state.reads = 0u;
    state.fail_index = PYZ80_DRAW_TAPE_V2_CATALOG_KEYS / 2u;
    if (PyZ80DrawTapeV2_FindCatalogBounded(
            catalog_read, &state, PYZ80_DRAW_TAPE_V2_CATALOG_KEYS,
            0u, 0u, &found, &comparisons) != 0u) return 43;
    return 0;
}

typedef struct CuckooReaderState {
    uint16_t reads;
    uint16_t fail_slot;
} CuckooReaderState;

static uint8_t cuckoo_read(void *context, uint16_t slot,
                           PyZ80DrawTapeV2CatalogEntry *entry)
{
    CuckooReaderState *state = (CuckooReaderState *)context;
    state->reads++;
    if (slot == state->fail_slot) return 0u;
    if (slot == PYZ80_DRAW_TAPE_V2_CUCKOO_SEED1) {
        entry->bank_key = 0u;
        entry->descriptor = 2u;
        entry->template_index = 1u;
    } else if (slot == PYZ80_DRAW_TAPE_V2_CUCKOO_SEED2) {
        entry->bank_key = 0u;
        entry->descriptor = 0u;
        entry->template_index = 0u;
    } else {
        entry->bank_key = 0xFFFFu;
        entry->descriptor = 0xFFFFu;
        entry->template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    }
    return 1u;
}

static int check_cuckoo_constant_two_reads(void)
{
    CuckooReaderState state;
    uint16_t found;
    uint8_t reads;
    state.reads = 0u;
    state.fail_slot = 0xFFFFu;
    if (PyZ80DrawTapeV2_FindCatalogCuckoo(
            cuckoo_read, &state, 0u, 0u, &found, &reads) == 0u ||
            found != 0u || reads != 2u || state.reads != 2u) return 44;
    state.reads = 0u;
    if (PyZ80DrawTapeV2_FindCatalogCuckoo(
            cuckoo_read, &state, 0u, 1u, &found, &reads) != 0u ||
            reads > 2u || state.reads > 2u) return 45;
    state.reads = 0u;
    state.fail_slot = PYZ80_DRAW_TAPE_V2_CUCKOO_SEED1;
    if (PyZ80DrawTapeV2_FindCatalogCuckoo(
            cuckoo_read, &state, 0u, 0u, &found, &reads) != 0u ||
            state.reads != 1u) return 46;
    return 0;
}

static int check_concrete_ft812_no_ready_prefix(void)
{
    static PyZ80FtQueue queue;
    PyZ80DrawTapeV2FT812WriterContext context;
    PyZ80DrawTapeV2Preflight preflight;
    PyZ80DrawTapeV2Record record;
    uint8_t blob;
    uint16_t append_words;
    memset(&queue, 0, sizeof(queue));
    memset(&context, 0, sizeof(context));
    memset(&preflight, 0, sizeof(preflight));
    if (PyZ80FT_QueueInitialize(&queue, PYZ80_FT_QUEUE_PAGE_A) == 0u)
        return 50;
    record.template_index = 0u;
    record.anchor_x = (int16_t)(320 - PyZ80FT_HQTemplates[0].dx);
    record.anchor_y = (int16_t)(384 - PyZ80FT_HQTemplates[0].dy -
        (int16_t)PyZ80FT_HQTemplates[0].height * 16);
    blob = PyZ80FT_HQAppendMap[0];
    append_words = (uint16_t)(PyZ80FT_HQAppendSize[blob] >> 2);
    record.append_expanded_words = append_words;
    preflight.record_count = 1u;
    preflight.chunk_count = 1u;
    preflight.cmd_append_expanded_words = append_words;
    preflight.fragment_expanded_dl_words = (uint16_t)(15u + append_words);
    preflight.fragment_physical_words = 18u;
    context.queue = &queue;
    context.frame_sequence = 9u;
    if (PyZ80DrawTapeV2FT812_Begin(&context, &preflight) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue.header.count || queue.header.payload_bytes ||
            queue.header.dl_words) return 51;
    if (PyZ80DrawTapeV2FT812_Append(
            &context, &record, 1u, 0u) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue.header.count || queue.header.payload_bytes ||
            queue.header.dl_words) return 52;
    if (PyZ80DrawTapeV2FT812_Commit(&context, &preflight) == 0u ||
            queue.header.state != PYZ80_FT_QUEUE_READY ||
            queue.header.count != 18u || queue.header.payload_bytes != 72u ||
            queue.header.dl_words != preflight.fragment_expanded_dl_words)
        return 53;
    return 0;
}

int main(void)
{
    int status;
    if (sizeof(PyZ80DrawTapeV2Record) != 8u ||
            PYZ80_DRAW_TAPE_V2_MAX_BYTES != 1824u) return 1;
    status = check_success_and_single_evaluation();
    if (status) return status;
    status = check_preflight_failures_do_not_touch_writer();
    if (status) return status;
    status = check_writer_abort_matrix();
    if (status) return status;
    status = check_bounded_catalog_10776();
    if (status) return status;
    status = check_cuckoo_constant_two_reads();
    if (status) return status;
    return check_concrete_ft812_no_ready_prefix();
}
'''


SOURCES = (
    "Source/C/ft812/pyz80_draw_private_tape_v2.c",
    "Source/C/ft812/pyz80_draw_private_tape_v2.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_draw_vm.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
)


def run_host_reference_matrix(root: Path = ROOT) -> dict[str, object]:
    if HOST_CC is None:
        raise RuntimeError("portable host C compiler is unavailable")
    with tempfile.TemporaryDirectory(prefix="pyz80-private-tape-v2-host-") as tmp:
        directory = Path(tmp)
        for relative in SOURCES:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "private_tape_v2_check.c").write_text(
            HARNESS, encoding="utf-8", newline="\n")
        command = [
            str(HOST_CC), "-D_Static_assert(x,y)=",
            "pyz80_draw_private_tape_v2.c", "pyz80_ft812.c",
            "rtype_python_hq_templates.c", "private_tape_v2_check.c",
            "-o", "private_tape_v2_check.exe",
        ]
        compiled = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180)
        if compiled.returncode != 0:
            raise RuntimeError("host compile failed:\n" + compiled.stdout)
        executable = directory / "private_tape_v2_check.exe"
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
                "one_vm_evaluation": True,
                "one_hqt_resolution_per_record": True,
                "private_tape_exactly_1824_bytes_at_228": True,
                "no_writer_call_before_complete_preflight": True,
                "writer_failures_abort_without_commit": True,
                "one_successful_atomic_commit_without_ready_prefix": True,
                "record_append_ram_dl_and_1209_boundaries": True,
                "catalog_10776_exhaustive_max_14_comparisons": True,
                "catalog_has_no_linear_scan": True,
                "cuckoo_hot_lookup_has_at_most_two_reads": True,
            },
        }


class DrawPrivateTapeV2Tests(unittest.TestCase):
    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_single_evaluation_and_catalog_matrix(self) -> None:
        result = run_host_reference_matrix()
        self.assertEqual(result["run_exit_code"], 0)
        self.assertTrue(all(result["matrix"].values()))

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_pinned_sdcc_compiles_v2(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-private-tape-v2-z80-") as tmp:
            directory = Path(tmp)
            for relative in (
                "Source/C/ft812/pyz80_draw_private_tape_v2.c",
                "Source/C/ft812/pyz80_draw_private_tape_v2.h",
                "Source/C/ft812/pyz80_ft812.h",
                "Source/C/generated/rtype_python_draw_vm.h",
                "Source/C/generated/rtype_python_hq_templates.h",
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
                 "pyz80_draw_private_tape_v2.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=240,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            rel = (directory / "pyz80_draw_private_tape_v2.rel").read_text(
                encoding="latin1")
            self.assertIn("A _CODE size ", rel)
            self.assertIn("A _DATA size 0 ", rel)


if __name__ == "__main__":
    unittest.main()
