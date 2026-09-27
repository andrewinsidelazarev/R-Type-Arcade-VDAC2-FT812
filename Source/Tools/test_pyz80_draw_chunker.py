#!/usr/bin/env python3
"""Bounded-record streaming proofs for the generated draw-plan adapter."""

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


HARNESS = r'''#include <stdint.h>
#include <string.h>
#include "pyz80_draw_chunker.h"

#define SOURCE_RECORDS 75u

typedef struct Capture {
    rtype_python_draw_plan_record output[96];
    uint16_t output_count;
    uint16_t calls;
    uint16_t fail_call;
} Capture;

rtype_python_draw_plan_status rtype_python_draw_plan_stream(
        const rtype_python_draw_plan_input *input,
        rtype_python_draw_plan_record_emitter emit_record,
        void *emit_context, uint16_t *output_count)
{
    uint16_t index;
    rtype_python_draw_plan_record record;
    (void)input;
    for (index = 0u; index < SOURCE_RECORDS; ++index) {
        record.bank_key = (uint16_t)(index + 1u);
        record.descriptor = (uint16_t)(0x4000u + index * 6u);
        record.anchor_x = (int16_t)(-((int16_t)index));
        record.anchor_y = (int16_t)(index * 2u);
        if (emit_record(emit_context, &record) == 0u) {
            *output_count = index;
            return RTYPE_PYTHON_DRAW_PLAN_EMITTER;
        }
    }
    *output_count = SOURCE_RECORDS;
    return RTYPE_PYTHON_DRAW_PLAN_OK;
}

static uint8_t capture_flush(
        void *context, const rtype_python_draw_plan_record *records,
        uint16_t count)
{
    Capture *capture = (Capture *)context;
    uint16_t index;
    capture->calls++;
    if (capture->calls == capture->fail_call) return 0u;
    for (index = 0u; index < count; ++index) {
        capture->output[capture->output_count++] = records[index];
    }
    return 1u;
}

static int record_ok(
        const rtype_python_draw_plan_record *record, uint16_t index)
{
    return record->bank_key == (uint16_t)(index + 1u) &&
           record->descriptor == (uint16_t)(0x4000u + index * 6u) &&
           record->anchor_x == (int16_t)(-((int16_t)index)) &&
           record->anchor_y == (int16_t)(index * 2u);
}

int main(void)
{
    rtype_python_draw_plan_record buffer[128];
    PyZ80DrawChunkState state;
    PyZ80DrawChunkResult result;
    rtype_python_draw_plan_input input;
    Capture capture;
    PyZ80DrawChunkStatus status;
    uint16_t index;

    memset(&input, 0, sizeof(input));
    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 0xFFFFu;
    status = PyZ80DrawChunk_Run(
        &input, &state, buffer, 7u, capture_flush, &capture, &result);
    if (status != PYZ80_DRAW_CHUNK_OK) return 10;
    if (result.accepted_records != SOURCE_RECORDS ||
            result.flushed_records != SOURCE_RECORDS ||
            result.chunk_count != 11u || capture.calls != 11u ||
            capture.output_count != SOURCE_RECORDS ||
            result.draw_plan_status != RTYPE_PYTHON_DRAW_PLAN_OK) return 11;
    for (index = 0u; index < SOURCE_RECORDS; ++index) {
        if (!record_ok(&capture.output[index], index)) return 12;
    }

    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 3u;
    status = PyZ80DrawChunk_Run(
        &input, &state, buffer, 7u, capture_flush, &capture, &result);
    if (status != PYZ80_DRAW_CHUNK_FLUSH || capture.calls != 3u ||
            result.accepted_records != 21u ||
            result.flushed_records != 14u || result.chunk_count != 2u ||
            result.draw_plan_status != RTYPE_PYTHON_DRAW_PLAN_EMITTER ||
            state.count != 7u) return 20;
    for (index = 0u; index < 7u; ++index) {
        if (!record_ok(&buffer[index], (uint16_t)(14u + index))) return 21;
    }

    memset(&capture, 0, sizeof(capture));
    capture.fail_call = 1u;
    status = PyZ80DrawChunk_Run(
        &input, &state, buffer, 128u, capture_flush, &capture, &result);
    if (status != PYZ80_DRAW_CHUNK_FLUSH || capture.calls != 1u ||
            result.accepted_records != SOURCE_RECORDS ||
            result.flushed_records != 0u || result.chunk_count != 0u ||
            result.draw_plan_status != RTYPE_PYTHON_DRAW_PLAN_OK ||
            state.count != SOURCE_RECORDS) return 30;

    if (PyZ80DrawChunk_Initialize(
            &state, buffer, 0u, capture_flush, &capture) != 0u) return 40;
    return 0;
}
'''


class DrawChunkerTests(unittest.TestCase):
    def _materialize(self, directory: Path) -> None:
        for source in (
            ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.c",
            ROOT / "Source" / "C" / "ft812" / "pyz80_draw_chunker.h",
            ROOT / "Source" / "C" / "generated" /
            "rtype_python_draw_plan.h",
        ):
            shutil.copy2(source, directory / source.name)

    @unittest.skipUnless(HOST_CC is not None,
                         "portable host C compiler unavailable")
    def test_order_chunk_boundaries_and_fail_closed_prefix(self) -> None:
        assert HOST_CC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-chunker-") as tmp:
            directory = Path(tmp)
            self._materialize(directory)
            (directory / "chunker_check.c").write_text(
                HARNESS, encoding="utf-8", newline="\n")
            compiled = subprocess.run(
                [str(HOST_CC), "-std=c11", "pyz80_draw_chunker.c",
                 "chunker_check.c", "-o", "chunker_check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "chunker_check.exe")], cwd=directory,
                check=False, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, encoding="utf-8",
                errors="replace", timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout)

    @unittest.skipUnless(SDCC is not None, "pinned local SDCC unavailable")
    def test_adapter_compiles_with_pinned_sdcc(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-draw-chunker-z80-") as tmp:
            directory = Path(tmp)
            self._materialize(directory)
            environment = os.environ.copy()
            environment["PATH"] = (
                str(SDCC.parent) + os.pathsep + environment.get("PATH", ""))
            completed = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--nolospre", "--nolabelopt", "--noinvariant",
                 "--noinduction", "--noloopreverse", "--no-peep",
                 "-c", "pyz80_draw_chunker.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=180,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue((directory / "pyz80_draw_chunker.rel").is_file())


if __name__ == "__main__":
    unittest.main()
