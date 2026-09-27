#!/usr/bin/env python3
"""Differential and failure proofs for the compact-VM -> fast-batch bridge."""

from __future__ import annotations

import json
import os
import random
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


def _template_records() -> list[dict[str, int]]:
    manifest = json.loads(
        (ROOT / "Build" / "rtype_python_assets.json").read_text(
            encoding="utf-8"))
    bootstrap = manifest["artifacts"][-1]
    records = bootstrap["templates"]["records"]
    if len(records) != 40:
        raise AssertionError("unexpected generated HQT3 template count")
    return records


def _oracle_records() -> list[tuple[int, int, int, int, int]]:
    templates = _template_records()
    records: list[tuple[int, int, int, int, int]] = []
    # Every generated identity is covered once in immutable table order.
    for index, template in enumerate(templates):
        x = -511 + index * 19
        y = -383 + index * 13
        records.append((
            int(template["bank_key"]),
            int(template["descriptor_address"]), x, y, index))
    # Seeded disorder, negative coordinates and deliberate coordinate ties.
    randomizer = random.Random(0x8125A17)
    for ordinal in range(233):
        index = randomizer.randrange(len(templates))
        template = templates[index]
        if ordinal % 9 in (0, 1, 2):
            x, y = -320, -144
        else:
            x = -randomizer.randrange(1, 1200)
            y = -randomizer.randrange(1, 900)
        records.append((
            int(template["bank_key"]),
            int(template["descriptor_address"]), x, y, index))
    return records


def _c_record(value: tuple[int, int, int, int, int]) -> str:
    bank, descriptor, x, y, template = value
    return (
        f"    {{ 0x{bank:04X}u, 0x{descriptor:04X}u, "
        f"{x}, {y}, {template}u }},")


def _harness() -> str:
    values = _oracle_records()
    initializers = "\n".join(_c_record(value) for value in values)
    return rf'''#include <stdint.h>
#include <string.h>

#include "pyz80_draw_fast_chunker.h"
#include "pyz80_draw_chunker.h"
#include "rtype_python_hq_templates.h"

#define SOURCE_RECORDS {len(values)}u
#define NO_OVERRIDE 0xFFFFu

typedef struct OracleRecord {{
    uint16_t bank_key;
    uint16_t descriptor;
    int16_t anchor_x;
    int16_t anchor_y;
    uint16_t template_index;
}} OracleRecord;

static const OracleRecord oracle[SOURCE_RECORDS] = {{
{initializers}
}};

static uint16_t vm_limit = SOURCE_RECORDS;
static uint16_t vm_output_bias = 0u;
static uint16_t vm_override_index = NO_OVERRIDE;
static uint8_t vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
static rtype_python_draw_vm_record vm_override;

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit_record,
        void *emit_context, uint16_t *output_count)
{{
    uint16_t index;
    rtype_python_draw_vm_record record;
    (void)input;
    for (index = 0u; index < vm_limit; ++index) {{
        if (index == vm_override_index) {{
            record = vm_override;
        }} else {{
            record.bank_key = oracle[index].bank_key;
            record.descriptor = oracle[index].descriptor;
            record.anchor_x = oracle[index].anchor_x;
            record.anchor_y = oracle[index].anchor_y;
        }}
        if (emit_record(emit_context, &record) == 0u) {{
            *output_count = index;
            return RTYPE_PYTHON_DRAW_VM_EMITTER;
        }}
    }}
    *output_count = (uint16_t)(vm_limit + vm_output_bias);
    return (rtype_python_draw_vm_status)vm_terminal_status;
}}

rtype_python_draw_plan_status rtype_python_draw_plan_stream(
        const rtype_python_draw_plan_input *input,
        rtype_python_draw_plan_record_emitter emit_record,
        void *emit_context, uint16_t *output_count)
{{
    uint16_t index;
    rtype_python_draw_plan_record record;
    (void)input;
    for (index = 0u; index < SOURCE_RECORDS; ++index) {{
        record.bank_key = oracle[index].bank_key;
        record.descriptor = oracle[index].descriptor;
        record.anchor_x = oracle[index].anchor_x;
        record.anchor_y = oracle[index].anchor_y;
        if (emit_record(emit_context, &record) == 0u) {{
            *output_count = index;
            return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
        }}
    }}
    *output_count = SOURCE_RECORDS;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}}

typedef struct FastCapture {{
    PyZ80FtTemplateDrawRecord output[SOURCE_RECORDS];
    uint16_t output_count;
    uint16_t calls;
    uint16_t fail_call;
    uint16_t first[32];
    uint16_t count[32];
}} FastCapture;

typedef struct LiteralCapture {{
    rtype_python_draw_plan_record output[SOURCE_RECORDS];
    uint16_t output_count;
    uint16_t calls;
    uint16_t first[32];
    uint16_t count[32];
}} LiteralCapture;

static uint8_t fast_submit(
        void *context,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first_record_index)
{{
    FastCapture *capture = (FastCapture *)context;
    uint16_t index;
    capture->calls++;
    if (capture->calls == capture->fail_call) return 0u;
    if (first_record_index != capture->output_count ||
            capture->calls > 32u ||
            count > (uint16_t)(SOURCE_RECORDS - capture->output_count)) {{
        return 0u;
    }}
    capture->first[capture->calls - 1u] = first_record_index;
    capture->count[capture->calls - 1u] = count;
    for (index = 0u; index < count; ++index) {{
        capture->output[capture->output_count++] = records[index];
    }}
    return 1u;
}}

static uint8_t literal_flush(
        void *context, const rtype_python_draw_plan_record *records,
        uint16_t count)
{{
    LiteralCapture *capture = (LiteralCapture *)context;
    uint16_t index;
    if (capture->calls >= 32u ||
            count > (uint16_t)(SOURCE_RECORDS - capture->output_count)) {{
        return 0u;
    }}
    capture->first[capture->calls] = capture->output_count;
    capture->count[capture->calls] = count;
    capture->calls++;
    for (index = 0u; index < count; ++index) {{
        capture->output[capture->output_count++] = records[index];
    }}
    return 1u;
}}

static int check_success(void)
{{
    PyZ80FtTemplateDrawRecord fast_buffer[17];
    rtype_python_draw_plan_record literal_buffer[17];
    PyZ80DrawFastChunkState fast_state;
    PyZ80DrawFastChunkResult fast_result;
    PyZ80DrawChunkState literal_state;
    PyZ80DrawChunkResult literal_result;
    rtype_python_draw_vm_input vm_input;
    rtype_python_draw_plan_input literal_input;
    FastCapture fast;
    LiteralCapture literal;
    uint16_t index;
    PyZ80DrawFastChunkStatus fast_status;
    PyZ80DrawChunkStatus literal_status;
    memset(&vm_input, 0, sizeof(vm_input));
    memset(&literal_input, 0, sizeof(literal_input));
    memset(&fast, 0, sizeof(fast));
    memset(&literal, 0, sizeof(literal));
    fast.fail_call = 0xFFFFu;
    vm_limit = SOURCE_RECORDS;
    vm_output_bias = 0u;
    vm_override_index = NO_OVERRIDE;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
    fast_status = PyZ80DrawFastChunk_Run(
        &vm_input, &fast_state, fast_buffer, 17u,
        fast_submit, &fast, &fast_result);
    literal_status = PyZ80DrawChunk_Run(
        &literal_input, &literal_state, literal_buffer, 17u,
        literal_flush, &literal, &literal_result);
    if (fast_status != PYZ80_DRAW_FAST_CHUNK_OK ||
            literal_status != PYZ80_DRAW_CHUNK_OK) return 10;
    if (fast_result.accepted_records != SOURCE_RECORDS ||
            fast_result.published_records != SOURCE_RECORDS ||
            fast_result.buffered_records != 0u ||
            fast_result.chunk_count != literal_result.chunk_count ||
            fast_result.failure != PYZ80_DRAW_FAST_FAILURE_NONE ||
            fast_result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_OK ||
            fast.output_count != SOURCE_RECORDS ||
            literal.output_count != SOURCE_RECORDS ||
            fast.calls != literal.calls) return 11;
    for (index = 0u; index < fast.calls; ++index) {{
        if (fast.first[index] != literal.first[index] ||
                fast.count[index] != literal.count[index]) return 12;
    }}
    for (index = 0u; index < SOURCE_RECORDS; ++index) {{
        if (literal.output[index].bank_key != oracle[index].bank_key ||
                literal.output[index].descriptor != oracle[index].descriptor ||
                literal.output[index].anchor_x != oracle[index].anchor_x ||
                literal.output[index].anchor_y != oracle[index].anchor_y) {{
            return 13;
        }}
        if (fast.output[index].template_index !=
                    oracle[index].template_index ||
                fast.output[index].anchor_x != oracle[index].anchor_x ||
                fast.output[index].anchor_y != oracle[index].anchor_y) {{
            return 14;
        }}
    }}
    for (index = 0u; index < PYZ80_FT_HQ_TEMPLATE_COUNT; ++index) {{
        if (PyZ80FT_FindHQTemplate(
                oracle[index].bank_key, oracle[index].descriptor) != index) {{
            return 15;
        }}
    }}
    return 0;
}}

static int check_lookup_failures(void)
{{
    PyZ80FtTemplateDrawRecord buffer[17];
    PyZ80DrawFastChunkState state;
    PyZ80DrawFastChunkResult result;
    rtype_python_draw_vm_input input;
    FastCapture capture;
    PyZ80DrawFastChunkStatus status;
    memset(&input, 0, sizeof(input));
    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 0xFFFFu;
    vm_limit = SOURCE_RECORDS;
    vm_output_bias = 0u;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
    vm_override.bank_key = 0xFFFFu;
    vm_override.descriptor = 0xFFFFu;
    vm_override.anchor_x = -1;
    vm_override.anchor_y = -1;
    if (PyZ80FT_FindHQTemplate(0xFFFFu, 0xFFFFu) !=
            PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) return 20;
    vm_override_index = 17u;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 17u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_LOOKUP ||
            result.accepted_records != 17u ||
            result.published_records != 17u ||
            result.buffered_records != 0u || capture.calls != 1u ||
            capture.output_count != 17u ||
            result.failure_record_index != 17u ||
            result.failure_bank_key != 0xFFFFu ||
            result.failure_descriptor != 0xFFFFu ||
            result.failure != PYZ80_DRAW_FAST_FAILURE_LOOKUP ||
            result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_EMITTER) return 21;
    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 0xFFFFu;
    vm_override_index = 3u;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 17u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_LOOKUP ||
            result.accepted_records != 3u ||
            result.published_records != 0u ||
            result.buffered_records != 3u || capture.calls != 0u) return 22;
    vm_override_index = NO_OVERRIDE;
    return 0;
}}

static int check_submit_failures(void)
{{
    PyZ80FtTemplateDrawRecord buffer[128];
    PyZ80DrawFastChunkState state;
    PyZ80DrawFastChunkResult result;
    rtype_python_draw_vm_input input;
    FastCapture capture;
    PyZ80DrawFastChunkStatus status;
    uint16_t index;
    memset(&input, 0, sizeof(input));
    memset(&capture, 0, sizeof(capture));
    vm_limit = SOURCE_RECORDS;
    vm_output_bias = 0u;
    vm_override_index = NO_OVERRIDE;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
    capture.fail_call = 2u;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 7u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_SUBMIT || capture.calls != 2u ||
            result.accepted_records != 14u ||
            result.published_records != 7u ||
            result.buffered_records != 7u ||
            result.chunk_count != 1u ||
            result.failure_record_index != 7u ||
            result.failure != PYZ80_DRAW_FAST_FAILURE_SUBMIT ||
            result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_EMITTER) return 30;
    for (index = 0u; index < 7u; ++index) {{
        if (buffer[index].template_index != oracle[index + 7u].template_index ||
                buffer[index].anchor_x != oracle[index + 7u].anchor_x ||
                buffer[index].anchor_y != oracle[index + 7u].anchor_y) return 31;
    }}
    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 1u;
    vm_limit = 100u;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 128u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_SUBMIT || capture.calls != 1u ||
            result.accepted_records != 100u ||
            result.published_records != 0u ||
            result.buffered_records != 100u ||
            result.chunk_count != 0u ||
            result.failure_record_index != 0u ||
            result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_OK) return 32;
    return 0;
}}

static int check_vm_and_counter_failures(void)
{{
    PyZ80FtTemplateDrawRecord buffer[17];
    PyZ80DrawFastChunkState state;
    PyZ80DrawFastChunkResult result;
    rtype_python_draw_vm_input input;
    FastCapture capture;
    PyZ80DrawFastChunkStatus status;
    rtype_python_draw_vm_record record;
    memset(&input, 0, sizeof(input));
    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 0xFFFFu;
    vm_override_index = NO_OVERRIDE;
    vm_output_bias = 0u;
    vm_limit = 5u;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_RANGE;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 17u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_VM ||
            result.accepted_records != 5u ||
            result.published_records != 0u ||
            result.buffered_records != 5u || capture.calls != 0u ||
            result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_RANGE) return 40;

    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 0xFFFFu;
    vm_limit = SOURCE_RECORDS;
    vm_terminal_status = RTYPE_PYTHON_DRAW_VM_OK;
    vm_output_bias = (uint16_t)-1;
    status = PyZ80DrawFastChunk_Run(
        &input, &state, buffer, 17u, fast_submit, &capture, &result);
    if (status != PYZ80_DRAW_FAST_CHUNK_VM ||
            result.failure != PYZ80_DRAW_FAST_FAILURE_VM_COUNT ||
            result.accepted_records != SOURCE_RECORDS ||
            result.published_records != 272u ||
            result.buffered_records != 1u ||
            result.draw_vm_status != RTYPE_PYTHON_DRAW_VM_EMITTER) return 41;
    vm_output_bias = 0u;

    if (PyZ80DrawFastChunk_Initialize(
            &state, buffer, 1u, fast_submit, &capture) == 0u) return 42;
    state.accepted_records = 0xFFFFu;
    record.bank_key = oracle[0].bank_key;
    record.descriptor = oracle[0].descriptor;
    record.anchor_x = oracle[0].anchor_x;
    record.anchor_y = oracle[0].anchor_y;
    if (PyZ80DrawFastChunk_Emit(&state, &record) != 0u ||
            state.failure != PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW ||
            state.count != 0u || capture.calls != 16u) return 43;

    if (PyZ80DrawFastChunk_Initialize(
            &state, buffer, 1u, fast_submit, &capture) == 0u) return 44;
    state.records[0].template_index = 0u;
    state.records[0].anchor_x = 0;
    state.records[0].anchor_y = 0;
    state.count = 1u;
    state.accepted_records = 1u;
    state.published_records = 0xFFFFu;
    if (PyZ80DrawFastChunk_Finish(&state) != 0u ||
            state.failure != PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW) return 45;
    return 0;
}}

static uint16_t provider_calls;
static uint8_t provider_mode;
static PyZ80FtQueue provider_queue;

static uint8_t target_provider(
        void *context, uint16_t chunk_index, uint16_t first_record_index,
        PyZ80DrawFastBatchTarget *target_out)
{{
    (void)context;
    (void)chunk_index;
    (void)first_record_index;
    provider_calls++;
    if (provider_mode == 1u) return 0u;
    target_out->queue = provider_mode == 2u ? NULL : &provider_queue;
    target_out->remaining_dl_words = provider_mode == 3u ? 2049u : 2048u;
    return 1u;
}}

static int check_invalid_and_ft812_wrapper(void)
{{
    PyZ80FtTemplateDrawRecord buffer[129];
    PyZ80DrawFastChunkState state;
    PyZ80DrawFastFT812SubmitContext submit_context;
    if (PyZ80DrawFastChunk_Initialize(
            &state, buffer, 0u, fast_submit, NULL) != 0u) return 50;
    if (PyZ80DrawFastChunk_Initialize(
            &state, buffer, 129u, fast_submit, NULL) != 0u) return 51;
    if (PyZ80DrawFastChunk_Initialize(
            NULL, buffer, 1u, fast_submit, NULL) != 0u) return 52;
    if (PyZ80DrawFastChunk_Initialize(
            &state, NULL, 1u, fast_submit, NULL) != 0u) return 53;
    if (PyZ80DrawFastChunk_Initialize(
            &state, buffer, 1u, NULL, NULL) != 0u) return 54;
    submit_context.provide_target = target_provider;
    submit_context.provider_context = NULL;
    submit_context.submitted_chunks = 0u;
    provider_calls = 0u;
    provider_mode = 1u;
    if (PyZ80DrawFastChunk_SubmitFT812(
            &submit_context, buffer, 1u, 0u) != 0u ||
            provider_calls != 1u) return 55;
    provider_mode = 2u;
    if (PyZ80DrawFastChunk_SubmitFT812(
            &submit_context, buffer, 1u, 0u) != 0u) return 56;
    provider_mode = 3u;
    if (PyZ80DrawFastChunk_SubmitFT812(
            &submit_context, buffer, 1u, 0u) != 0u) return 57;
    /* A valid provider reaches the real fast builder.  The zeroed host queue
     * is intentionally not BUILDING, so the target-neutral call fails closed
     * without publishing and the completed-chunk counter cannot advance. */
    provider_mode = 0u;
    memset(&provider_queue, 0, sizeof(provider_queue));
    if (PyZ80DrawFastChunk_SubmitFT812(
            &submit_context, buffer, 1u, 0u) != 0u ||
            submit_context.submitted_chunks != 0u) return 58;
    submit_context.submitted_chunks = 0xFFFFu;
    if (PyZ80DrawFastChunk_SubmitFT812(
            &submit_context, buffer, 1u, 0u) != 0u) return 59;
    return 0;
}}

int main(void)
{{
    int status;
    status = check_success();
    if (status != 0) return status;
    status = check_lookup_failures();
    if (status != 0) return status;
    status = check_submit_failures();
    if (status != 0) return status;
    status = check_vm_and_counter_failures();
    if (status != 0) return status;
    return check_invalid_and_ft812_wrapper();
}}
'''


class DrawFastChunkerTests(unittest.TestCase):
    def _materialize(self, directory: Path) -> None:
        for source in (
            ROOT / "Source" / "C" / "ft812" /
            "pyz80_draw_fast_chunker.c",
            ROOT / "Source" / "C" / "ft812" /
            "pyz80_draw_fast_chunker.h",
            ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.c",
            ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.h",
            ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.c",
            ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.h",
            ROOT / "Source" / "C" / "generated" /
            "rtype_python_draw_vm.h",
            ROOT / "Source" / "C" / "generated" /
            "rtype_python_draw_plan.h",
            ROOT / "Source" / "C" / "generated" /
            "rtype_python_hq_templates.c",
            ROOT / "Source" / "C" / "generated" /
            "rtype_python_hq_templates.h",
        ):
            shutil.copy2(source, directory / source.name)

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_oracle_order_lookup_and_failure_matrix(self) -> None:
        assert HOST_CC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-fast-chunker-") as tmp:
            directory = Path(tmp)
            self._materialize(directory)
            (directory / "fast_chunker_check.c").write_text(
                _harness(), encoding="utf-8", newline="\n")
            compiled = subprocess.run(
                [str(HOST_CC), "-D_Static_assert(x,y)=",
                 "pyz80_draw_fast_chunker.c", "pyz80_draw_chunker.c",
                 "pyz80_ft812.c", "rtype_python_hq_templates.c",
                 "fast_chunker_check.c", "-o", "fast_chunker_check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "fast_chunker_check.exe")], cwd=directory,
                check=False, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, encoding="utf-8",
                errors="replace", timeout=60)
            self.assertEqual(executed.returncode, 0, executed.stdout)

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_pinned_sdcc_calls_generated_lookup_and_fast_batch(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(
                prefix="pyz80-fast-chunker-z80-") as tmp:
            directory = Path(tmp)
            for source in (
                ROOT / "Source" / "C" / "ft812" /
                "pyz80_draw_fast_chunker.c",
                ROOT / "Source" / "C" / "ft812" /
                "pyz80_draw_fast_chunker.h",
                ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.h",
                ROOT / "Source" / "C" / "generated" /
                "rtype_python_draw_vm.h",
            ):
                shutil.copy2(source, directory / source.name)
            environment = os.environ.copy()
            environment["PATH"] = (
                str(SDCC.parent) + os.pathsep +
                environment.get("PATH", ""))
            completed = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--fno-omit-frame-pointer", "--stack-auto",
                 "--opt-code-speed", "--no-c-code-in-asm",
                 "-c", "pyz80_draw_fast_chunker.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=180,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            assembly = (directory / "pyz80_draw_fast_chunker.asm").read_text(
                encoding="latin1")
            self.assertEqual(
                assembly.count("call\t_PyZ80FT_FindHQTemplate"), 1)
            self.assertEqual(
                assembly.count("call\t_PyZ80FT_BuildSpriteBatchFast"), 1)


if __name__ == "__main__":
    unittest.main()
