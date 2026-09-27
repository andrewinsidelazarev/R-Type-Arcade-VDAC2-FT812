#!/usr/bin/env python3
"""Host/reference proofs for the two-pass whole-frame draw publication gate."""

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

#include "pyz80_draw_atomic_frame.h"
#include "rtype_python_hq_templates.h"

#define TEST_RECORD_CAPACITY 230u

static rtype_python_draw_vm_record vm_records_a[TEST_RECORD_CAPACITY];
static rtype_python_draw_vm_record vm_records_b[TEST_RECORD_CAPACITY];
static uint16_t vm_count_a;
static uint16_t vm_count_b;
static uint8_t vm_status_a;
static uint8_t vm_status_b;
static uint8_t active_pass;
static uint8_t prepare_fail_pass;
static uint32_t token_a;
static uint32_t token_b;

static uint8_t resolve_fail_pass;
static uint16_t resolve_fail_index;
static uint16_t resolve_append_a;
static uint16_t resolve_append_b;
static uint16_t resolve_template_b_xor_index;
static uint16_t resolve_calls[2];

typedef struct TestWriter {
    uint16_t begin_calls;
    uint16_t append_calls;
    uint16_t commit_calls;
    uint16_t abort_calls;
    uint16_t private_records;
    uint16_t private_chunks;
    uint16_t public_count;
    uint8_t public_ready;
    uint8_t begun;
    uint8_t fail_begin;
    uint16_t fail_append_call;
    uint8_t fail_commit;
    uint8_t prefix_observed;
} TestWriter;

static TestWriter capture;
static uint16_t raster[PYZ80_DRAW_ATOMIC_RASTER_LINES];
static PyZ80FtTemplateDrawRecord chunk[PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS];
static rtype_python_draw_vm_input vm_input;
static PyZ80DrawAtomicCertificate certificate;
static PyZ80DrawAtomicFrameBudget budget;
static PyZ80DrawAtomicReplay replay;
static PyZ80DrawAtomicWriter writer;
static PyZ80DrawAtomicResult result;

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit_record,
        void *emit_context, uint16_t *output_count)
{
    const rtype_python_draw_vm_record *records;
    uint16_t count;
    uint16_t index;
    uint8_t terminal;
    (void)input;
    records = active_pass == 0u ? vm_records_a : vm_records_b;
    count = active_pass == 0u ? vm_count_a : vm_count_b;
    terminal = active_pass == 0u ? vm_status_a : vm_status_b;
    for (index = 0u; index < count; ++index) {
        if (emit_record(emit_context, &records[index]) == 0u) {
            *output_count = index;
            return RTYPE_PYTHON_DRAW_VM_EMITTER;
        }
    }
    *output_count = count;
    return (rtype_python_draw_vm_status)terminal;
}

static uint8_t prepare(void *context, uint8_t pass, uint32_t *token_out)
{
    (void)context;
    active_pass = pass;
    if (prepare_fail_pass == (uint8_t)(pass + 1u)) return 0u;
    *token_out = pass == 0u ? token_a : token_b;
    return 1u;
}

static uint8_t resolve(void *context,
        const rtype_python_draw_vm_record *record,
        PyZ80DrawAtomicResolvedRecord *resolved)
{
    uint16_t index;
    (void)context;
    (void)record;
    index = resolve_calls[active_pass]++;
    if (resolve_fail_pass == (uint8_t)(active_pass + 1u) &&
            resolve_fail_index == index) return 0u;
    resolved->template_index = (uint16_t)(index & 31u);
    if (active_pass == 1u && resolve_template_b_xor_index == index)
        resolved->template_index ^= 1u;
    resolved->append_expanded_words = active_pass == 0u ?
        resolve_append_a : resolve_append_b;
    return 1u;
}

static uint8_t writer_begin(void *context,
        const PyZ80DrawAtomicPreflight *preflight)
{
    TestWriter *state = (TestWriter *)context;
    (void)preflight;
    state->begin_calls++;
    if (state->public_ready != 0u || state->public_count != 0u)
        state->prefix_observed = 1u;
    state->begun = 1u;
    if (state->fail_begin != 0u) return 0u;
    return 1u;
}

static uint8_t writer_append(void *context,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first_record_index)
{
    TestWriter *state = (TestWriter *)context;
    (void)records;
    state->append_calls++;
    if (state->begun != 1u || state->public_ready != 0u ||
            state->public_count != 0u ||
            first_record_index != state->private_records)
        state->prefix_observed = 1u;
    if (state->fail_append_call == state->append_calls) return 0u;
    state->private_records = (uint16_t)(state->private_records + count);
    state->private_chunks++;
    return 1u;
}

static uint8_t writer_commit(void *context,
        const PyZ80DrawAtomicPreflight *preflight)
{
    TestWriter *state = (TestWriter *)context;
    state->commit_calls++;
    if (state->begun != 1u || state->public_ready != 0u ||
            state->public_count != 0u ||
            state->private_records != preflight->record_count ||
            state->private_chunks != preflight->chunk_count)
        state->prefix_observed = 1u;
    if (state->fail_commit != 0u) return 0u;
    state->public_count = state->private_records;
    state->public_ready = 1u;
    state->begun = 0u;
    return 1u;
}

static void writer_abort(void *context)
{
    TestWriter *state = (TestWriter *)context;
    state->abort_calls++;
    state->begun = 0u;
    state->private_records = 0u;
    state->private_chunks = 0u;
    state->public_count = 0u;
    state->public_ready = 0u;
}

static void configure(uint16_t records, uint16_t maximum,
                      uint16_t append_maximum)
{
    uint16_t index;
    uint16_t chunks;
    memset(vm_records_a, 0, sizeof(vm_records_a));
    memset(vm_records_b, 0, sizeof(vm_records_b));
    memset(&capture, 0, sizeof(capture));
    memset(raster, 0, sizeof(raster));
    memset(&result, 0, sizeof(result));
    memset(&vm_input, 0, sizeof(vm_input));
    for (index = 0u; index < records; ++index) {
        vm_records_a[index].bank_key = (uint16_t)(0x0100u + (index & 15u));
        vm_records_a[index].descriptor = (uint16_t)(0x2000u + index);
        vm_records_a[index].anchor_x = (int16_t)(index - 100);
        vm_records_a[index].anchor_y = (int16_t)(80 - index);
        vm_records_b[index] = vm_records_a[index];
    }
    vm_count_a = records;
    vm_count_b = records;
    vm_status_a = RTYPE_PYTHON_DRAW_VM_OK;
    vm_status_b = RTYPE_PYTHON_DRAW_VM_OK;
    active_pass = 0u;
    prepare_fail_pass = 0u;
    token_a = 0x8120A55Aul;
    token_b = token_a;
    resolve_fail_pass = 0u;
    resolve_fail_index = 0xFFFFu;
    resolve_append_a = 1u;
    resolve_append_b = 1u;
    resolve_template_b_xor_index = 0xFFFFu;
    resolve_calls[0] = 0u;
    resolve_calls[1] = 0u;
    capture.fail_append_call = 0xFFFFu;
    chunks = (uint16_t)((maximum +
        PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS - 1u) /
        PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS);
    certificate.format_version = PYZ80_DRAW_ATOMIC_CERTIFICATE_VERSION;
    certificate.sizing_proof_complete = 1u;
    certificate.certified_max_records = maximum;
    certificate.chunk_capacity_records =
        PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS;
    certificate.max_chunks = chunks;
    certificate.max_cmd_append_expanded_words = append_maximum;
    certificate.max_fragment_expanded_dl_words = (uint16_t)(
        chunks * (PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS +
                  PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS) +
        maximum * PYZ80_DRAW_ATOMIC_RECORD_DL_WORDS + append_maximum);
    certificate.raster_cycles_by_line = raster;
    certificate.raster_line_count = PYZ80_DRAW_ATOMIC_RASTER_LINES;
    budget.ram_dl_word_limit = PYZ80_FT_RAM_DL_WORD_LIMIT;
    budget.non_fragment_dl_words = 0u;
    budget.safe_line_cycles = PYZ80_DRAW_ATOMIC_SAFE_LINE_CYCLES;
    replay.prepare = prepare;
    replay.context = 0;
    writer.begin = writer_begin;
    writer.append = writer_append;
    writer.commit = writer_commit;
    writer.abort = writer_abort;
    writer.context = &capture;
}

static PyZ80DrawAtomicStatus run_gate(void)
{
    return PyZ80DrawAtomic_Run(
        &vm_input, &certificate, &budget, resolve, 0, &replay, &writer,
        chunk, PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS, &result);
}

static int check_success_228(void)
{
    configure(228u, 228u, 228u);
    if (run_gate() != PYZ80_DRAW_ATOMIC_OK) return 10;
    if (result.committed != 1u || result.pass_a_records != 228u ||
            result.pass_b_records != 228u ||
            result.private_records_written != 228u ||
            result.private_chunks_written != 2u ||
            result.preflight.record_count != 228u ||
            result.preflight.chunk_count != 2u ||
            result.preflight.cmd_append_expanded_words != 228u ||
            result.preflight.fragment_expanded_dl_words != 710u ||
            result.preflight.fragment_physical_words != 1166u ||
            result.preflight.worst_line_cycles != 710u) return 11;
    if (resolve_calls[0] != 228u || resolve_calls[1] != 228u ||
            capture.begin_calls != 1u || capture.append_calls != 2u ||
            capture.commit_calls != 1u || capture.abort_calls != 0u ||
            capture.public_ready != 1u || capture.public_count != 228u ||
            capture.prefix_observed != 0u) return 12;
    return 0;
}

static int check_pass_a_never_writes(void)
{
    configure(20u, 20u, 20u);
    resolve_fail_pass = 1u;
    resolve_fail_index = 7u;
    if (run_gate() != PYZ80_DRAW_ATOMIC_LOOKUP_A ||
            result.committed != 0u || capture.begin_calls != 0u ||
            capture.append_calls != 0u || capture.commit_calls != 0u ||
            capture.abort_calls != 0u) return 20;
    configure(4u, 3u, 3u);
    if (run_gate() != PYZ80_DRAW_ATOMIC_RECORD_BOUND ||
            capture.begin_calls != 0u || capture.append_calls != 0u ||
            capture.commit_calls != 0u || capture.abort_calls != 0u) return 21;
    configure(4u, 4u, 3u);
    if (run_gate() != PYZ80_DRAW_ATOMIC_APPEND_BOUND ||
            capture.begin_calls != 0u || capture.append_calls != 0u ||
            capture.commit_calls != 0u || capture.abort_calls != 0u) return 22;
    return 0;
}

static int check_preflight_boundaries(void)
{
    configure(1u, 1u, 1u);
    budget.non_fragment_dl_words = 2032u; /* 2032 + 16 == 2048 */
    if (run_gate() != PYZ80_DRAW_ATOMIC_CERTIFICATE ||
            capture.begin_calls != 0u || result.committed != 0u) return 30;

    configure(1u, 1u, 1u);
    raster[333] = 1193u; /* 16-word walk + 1193 == 1209 */
    if (run_gate() != PYZ80_DRAW_ATOMIC_OK ||
            result.preflight.worst_raster_line != 333u ||
            result.preflight.worst_line_cycles != 1209u) return 31;
    configure(1u, 1u, 1u);
    raster[333] = 1194u;
    if (run_gate() != PYZ80_DRAW_ATOMIC_CERTIFICATE ||
            capture.begin_calls != 0u || result.committed != 0u) return 32;

    configure(1u, 1u, 1u);
    budget.safe_line_cycles = 1210u;
    if (run_gate() != PYZ80_DRAW_ATOMIC_CERTIFICATE) return 33;

    configure(229u, 228u, 228u);
    if (run_gate() != PYZ80_DRAW_ATOMIC_RECORD_BOUND ||
            result.pass_a_records != 228u || result.committed != 0u) return 34;
    return 0;
}

static int expect_b_abort(PyZ80DrawAtomicStatus expected, int code)
{
    PyZ80DrawAtomicStatus status = run_gate();
    if (status != expected || result.committed != 0u ||
            capture.commit_calls > 1u || capture.abort_calls != 1u ||
            capture.public_ready != 0u || capture.public_count != 0u ||
            capture.begun != 0u || capture.prefix_observed != 0u)
        return code;
    return 0;
}

static int check_pass_b_abort_matrix(void)
{
    int status;
    configure(10u, 10u, 10u);
    prepare_fail_pass = 2u;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_PREPARE_B, 40);
    if (status != 0) return status;

    configure(10u, 10u, 10u);
    token_b ^= 1ul;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_REPLAY_TOKEN, 41);
    if (status != 0) return status;

    configure(10u, 10u, 10u);
    capture.fail_begin = 1u;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_WRITER_BEGIN, 42);
    if (status != 0 || capture.begin_calls != 1u) return status ? status : 43;

    configure(130u, 130u, 130u);
    resolve_fail_pass = 2u;
    resolve_fail_index = 129u;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_LOOKUP_B, 44);
    if (status != 0 || capture.append_calls != 1u) return status ? status : 45;

    configure(130u, 130u, 130u);
    vm_records_b[129].anchor_x++;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_REPLAY_MISMATCH, 46);
    if (status != 0 || capture.append_calls != 1u) return status ? status : 47;

    configure(130u, 130u, 130u);
    vm_status_b = RTYPE_PYTHON_DRAW_VM_RANGE;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_VM_B, 48);
    if (status != 0 || capture.append_calls != 1u) return status ? status : 49;

    configure(228u, 228u, 228u);
    capture.fail_append_call = 2u;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_WRITER_APPEND, 50);
    if (status != 0 || capture.append_calls != 2u) return status ? status : 51;

    configure(10u, 10u, 10u);
    capture.fail_commit = 1u;
    status = expect_b_abort(PYZ80_DRAW_ATOMIC_WRITER_COMMIT, 52);
    if (status != 0 || capture.commit_calls != 1u) return status ? status : 53;
    return 0;
}

static int check_concrete_ft812_publication(void)
{
    static PyZ80FtQueue queue_success;
    static PyZ80FtQueue queue_abort;
    PyZ80DrawAtomicFT812WriterContext context;
    PyZ80DrawAtomicPreflight preflight;
    PyZ80FtTemplateDrawRecord record;
    uint8_t blob;
    uint16_t append_words;

    memset(&queue_success, 0, sizeof(queue_success));
    memset(&context, 0, sizeof(context));
    memset(&preflight, 0, sizeof(preflight));
    if (PyZ80FT_QueueInitialize(&queue_success,
            PYZ80_FT_QUEUE_PAGE_A) == 0u) return 60;
    record.template_index = 0u;
    record.anchor_x = (int16_t)(320 - PyZ80FT_HQTemplates[0].dx);
    record.anchor_y = (int16_t)(384 - PyZ80FT_HQTemplates[0].dy -
        (int16_t)PyZ80FT_HQTemplates[0].height * 16);
    blob = PyZ80FT_HQAppendMap[0];
    if (blob >= PYZ80_FT_HQ_APPEND_BLOB_COUNT) return 61;
    append_words = (uint16_t)(PyZ80FT_HQAppendSize[blob] >> 2);
    if (append_words == 0u) return 62;
    preflight.record_count = 1u;
    preflight.chunk_count = 1u;
    preflight.cmd_append_expanded_words = append_words;
    preflight.fragment_expanded_dl_words = (uint16_t)(15u + append_words);
    preflight.fragment_physical_words = 18u;
    context.queue = &queue_success;
    context.frame_sequence = 7u;
    if (PyZ80DrawAtomicFT812_Begin(&context, &preflight) == 0u ||
            queue_success.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue_success.header.count != 0u ||
            queue_success.header.payload_bytes != 0u ||
            queue_success.header.dl_words != 0u) return 63;
    if (PyZ80DrawAtomicFT812_Append(&context, &record, 1u, 0u) == 0u ||
            queue_success.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue_success.header.count != 0u ||
            queue_success.header.payload_bytes != 0u ||
            queue_success.header.dl_words != 0u) return 64;
    if (PyZ80DrawAtomicFT812_Commit(&context, &preflight) == 0u ||
            queue_success.header.state != PYZ80_FT_QUEUE_READY ||
            queue_success.header.count != 18u ||
            queue_success.header.payload_bytes != 72u ||
            queue_success.header.dl_words !=
                preflight.fragment_expanded_dl_words) return 65;

    memset(&queue_abort, 0, sizeof(queue_abort));
    memset(&context, 0, sizeof(context));
    if (PyZ80FT_QueueInitialize(&queue_abort,
            PYZ80_FT_QUEUE_PAGE_B) == 0u) return 66;
    context.queue = &queue_abort;
    context.frame_sequence = 8u;
    if (PyZ80DrawAtomicFT812_Begin(&context, &preflight) == 0u) return 67;
    record.template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    if (PyZ80DrawAtomicFT812_Append(&context, &record, 1u, 0u) != 0u ||
            queue_abort.header.state != PYZ80_FT_QUEUE_BUILDING ||
            queue_abort.header.count != 0u) return 68;
    PyZ80DrawAtomicFT812_Abort(&context);
    if (queue_abort.header.state != PYZ80_FT_QUEUE_FREE ||
            queue_abort.header.count != 0u ||
            queue_abort.header.payload_bytes != 0u ||
            queue_abort.header.dl_words != 0u) return 69;
    return 0;
}

int main(void)
{
    int status;
    status = check_success_228();
    if (status != 0) return status;
    status = check_pass_a_never_writes();
    if (status != 0) return status;
    status = check_preflight_boundaries();
    if (status != 0) return status;
    status = check_pass_b_abort_matrix();
    if (status != 0) return status;
    return check_concrete_ft812_publication();
}
'''


SOURCES = (
    "Source/C/ft812/pyz80_draw_atomic_frame.c",
    "Source/C/ft812/pyz80_draw_atomic_frame.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_draw_vm.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
)


def run_host_reference_matrix(root: Path = ROOT) -> dict[str, object]:
    if HOST_CC is None:
        raise RuntimeError("portable host C compiler is unavailable")
    with tempfile.TemporaryDirectory(prefix="pyz80-atomic-frame-host-") as tmp:
        directory = Path(tmp)
        for relative in SOURCES:
            source = root / relative
            shutil.copy2(source, directory / source.name)
        (directory / "atomic_frame_check.c").write_text(
            HARNESS, encoding="utf-8", newline="\n")
        command = [
            str(HOST_CC), "-D_Static_assert(x,y)=",
            "pyz80_draw_atomic_frame.c", "pyz80_ft812.c",
            "rtype_python_hq_templates.c", "atomic_frame_check.c",
            "-o", "atomic_frame_check.exe",
        ]
        compiled = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180)
        if compiled.returncode != 0:
            raise RuntimeError("host compile failed:\n" + compiled.stdout)
        executable = directory / "atomic_frame_check.exe"
        executed = subprocess.run(
            [str(executable)], cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=120)
        if executed.returncode != 0:
            raise RuntimeError(
                f"host reference matrix failed with {executed.returncode}:\n" +
                executed.stdout)
        return {
            "compiler": HOST_CC.as_posix(),
            "compile_command": command,
            "compile_exit_code": compiled.returncode,
            "run_exit_code": executed.returncode,
            "matrix": {
                "pass_a_has_no_writer_calls": True,
                "pass_b_failures_abort_without_commit": True,
                "replay_token_and_content_mismatch_rejected": True,
                "missing_hqt_rejected_in_both_passes": True,
                "record_and_append_bounds_checked": True,
                "ram_dl_2048_rejected": True,
                "raster_1209_accepted_1210_rejected": True,
                "success_228_records_two_chunks_one_commit": True,
                "ft812_header_has_no_ready_prefix": True,
            },
        }


class DrawAtomicFrameTests(unittest.TestCase):
    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_host_reference_failure_and_boundary_matrix(self) -> None:
        result = run_host_reference_matrix()
        self.assertEqual(result["compile_exit_code"], 0)
        self.assertEqual(result["run_exit_code"], 0)
        self.assertTrue(all(result["matrix"].values()))

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_pinned_sdcc_compiles_atomic_gate(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-atomic-frame-z80-") as tmp:
            directory = Path(tmp)
            for relative in (
                "Source/C/ft812/pyz80_draw_atomic_frame.c",
                "Source/C/ft812/pyz80_draw_atomic_frame.h",
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
                 "pyz80_draw_atomic_frame.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=240,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            rel = (directory / "pyz80_draw_atomic_frame.rel").read_text(
                encoding="latin1")
            self.assertIn("A _CODE size ", rel)
            self.assertIn("A _DATA size 0 ", rel)


if __name__ == "__main__":
    unittest.main()
