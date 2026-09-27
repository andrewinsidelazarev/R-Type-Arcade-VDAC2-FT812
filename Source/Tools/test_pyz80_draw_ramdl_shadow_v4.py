#!/usr/bin/env python3
"""Host/reference matrix for the isolated direct-RAM_DL v4 prototype."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST_CC = next((candidate for candidate in (
    Path(os.environ["PYZ80_HOST_CC"])
    if os.environ.get("PYZ80_HOST_CC") else None,
    Path(shutil.which("tcc")) if shutil.which("tcc") else None,
    ROOT.parent / "tcc-0.9.27" / "tcc" / "tcc.exe",
) if candidate is not None and candidate.is_file()), None)


HARNESS = r'''
#include <stdint.h>
#include <string.h>

#include "pyz80_draw_ramdl_shadow_v4.h"

#define PREFIX_WORDS 10u
#define SUFFIX_WORDS 3u
#define ACTIVE_UNIQUE 73u

static const uint8_t active_sizes[ACTIVE_UNIQUE] = {
    6,6,7,7,7,7,4,6,6,7,7,7,7,7,7,7,7,7,7,7,7,6,6,7,7,7,7,6,6,
    25,25,22,22,24,24,25,25,24,24,13,22,22,25,25,25,25,24,24,13,
    23,23,23,23,21,21,21,21,23,23,22,22,13,21,21,23,23,23,23,22,
    22,13,22,22
};

static uint32_t fragment_words[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS][25];
static PyZ80DrawRamDLV4Fragment fragments[
    PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
static PyZ80DrawRamDLV4Object objects[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
static PyZ80DrawRamDLV4Model model;
static PyZ80DrawRamDLV4Certificate certificate;
static uint16_t raster_lines[768];
static PyZ80DrawRamDLV4RasterProof raster;
static PyZ80DrawRamDLV4DedupScratch scratch;
static PyZ80DrawRamDLV4Layout layout;
static uint32_t shadow_words[2][PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS];
static PyZ80DrawRamDLV4DoubleShadow shadows;
static const uint32_t prefix[PREFIX_WORDS] = {
    0x02010203ul, 0x26000007ul, 0x0A000001ul, 0x05000000ul,
    0x1F000001ul, 0x22000000ul, 0x23000000ul, 0x27000004ul,
    0x28000000ul, 0x29000000ul
};
static const uint32_t suffix[SUFFIX_WORDS] = {
    0x26000007ul, 0x21000000ul, PYZ80_DRAW_RAMDL_V4_DL_DISPLAY
};

static void initialize_common(uint16_t count)
{
    uint16_t index;
    uint16_t word;
    memset(fragment_words, 0, sizeof(fragment_words));
    memset(fragments, 0, sizeof(fragments));
    memset(objects, 0, sizeof(objects));
    memset(&model, 0, sizeof(model));
    memset(&certificate, 0, sizeof(certificate));
    memset(raster_lines, 0, sizeof(raster_lines));
    memset(&raster, 0, sizeof(raster));
    memset(&scratch, 0xCC, sizeof(scratch));
    memset(&layout, 0xCC, sizeof(layout));
    memset(shadow_words, 0x5A, sizeof(shadow_words));
    memset(&shadows, 0, sizeof(shadows));
    for (index = 0u; index < PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS; ++index) {
        for (word = 0u; word < 25u; ++word) {
            /* Opcode 0x09 is deliberately not structural control. */
            fragment_words[index][word] = 0x09000000ul |
                ((uint32_t)index << 8) | word;
        }
        fragments[index].words = fragment_words[index];
        fragments[index].word_count = 4u;
        fragments[index].worst_line_cycles = (uint16_t)(20u + index);
        fragments[index].identity = (uint16_t)(1000u + index);
        fragments[index].generation = (uint16_t)(2000u + index);
        objects[index].object_id = (uint16_t)(3000u + index);
        objects[index].generation = fragments[index].generation;
        objects[index].vertex_x = (int16_t)(index - 100);
        objects[index].vertex_y = (int16_t)(80 - index);
        objects[index].fragment = &fragments[index];
    }
    model.objects = objects;
    model.count = count;
    model.capacity = PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS;
    model.epoch = 7u;
    model.dirty = PYZ80_DRAW_RAMDL_V4_DIRTY_NONE;
    model.mutation_lock = 0u;
    certificate.format_version = PYZ80_DRAW_RAMDL_V4_CERTIFICATE_VERSION;
    certificate.immutable_fragment_proof = 1u;
    certificate.dedup_identity_generation_proof = 1u;
    certificate.exact_order_hook_proof = 1u;
    certificate.direct_ram_dl_proof = 1u;
    certificate.double_shadow_epoch_proof = 1u;
    certificate.swap_fence_proof = 1u;
    certificate.raster_proof = 1u;
    certificate.ts_ram_allocation_proof = 1u;
    certificate.max_objects = PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS;
    certificate.max_used_words = PYZ80_DRAW_RAMDL_V4_MAX_USED_WORDS;
    certificate.safe_line_cycles = PYZ80_DRAW_RAMDL_V4_SAFE_LINE_CYCLES;
    certificate.fragment_min_words = 4u;
    certificate.fragment_max_words = 25u;
    raster.cycles_by_line = raster_lines;
    raster.line_count = 768u;
    raster.model_epoch = model.epoch;
    raster.max_cycles = 0u;
    raster.worst_line = 0u;
    shadows.slot[0].words = shadow_words[0];
    shadows.slot[0].capacity_words = PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS;
    shadows.slot[0].physical_page = 9u;
    shadows.slot[0].physical_offset = 0u;
    shadows.slot[0].state = PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE;
    shadows.slot[0].slot = 0u;
    shadows.slot[1].words = shadow_words[1];
    shadows.slot[1].capacity_words = PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS;
    shadows.slot[1].physical_page = 9u;
    shadows.slot[1].physical_offset = 0x2000u;
    shadows.slot[1].state = PYZ80_DRAW_RAMDL_V4_SHADOW_FREE;
    shadows.slot[1].slot = 1u;
    shadows.active_slot = 0u;
    shadows.dma_slot = 0xFFu;
}

static PyZ80DrawRamDLV4Status preflight(void)
{
    return PyZ80DrawRamDLV4_Preflight(
        &model, prefix, PREFIX_WORDS, suffix, SUFFIX_WORDS,
        &certificate, &raster, &scratch, &layout);
}

static PyZ80DrawRamDLV4Status build(void)
{
    return PyZ80DrawRamDLV4_BuildInactive(
        &model, prefix, PREFIX_WORDS, suffix, SUFFIX_WORDS,
        &certificate, &raster, &scratch, &shadows, &layout);
}

static int check_active_catalog_dedup_and_exact_order(void)
{
    uint16_t index;
    uint16_t unique;
    uint16_t cursor;
    initialize_common(228u);
    for (unique = 0u; unique < ACTIVE_UNIQUE; ++unique)
        fragments[unique].word_count = active_sizes[unique];
    for (index = 0u; index < 228u; ++index) {
        unique = (uint16_t)(index % ACTIVE_UNIQUE);
        objects[index].fragment = &fragments[unique];
        objects[index].generation = fragments[unique].generation;
    }
    if (preflight() != PYZ80_DRAW_RAMDL_V4_OK) return 10;
    if (layout.main_words != 697u || layout.subroutine_words != 1237u ||
            layout.total_words != 1934u ||
            layout.unique_fragment_count != ACTIVE_UNIQUE ||
            layout.coordinate_words != 456u || layout.call_words != 228u ||
            scratch.unique_count != ACTIVE_UNIQUE ||
            scratch.model_epoch != model.epoch || !scratch.map_checksum)
        return 11;
    if (build() != PYZ80_DRAW_RAMDL_V4_OK ||
            shadows.slot[1].state != PYZ80_DRAW_RAMDL_V4_SHADOW_READY ||
            shadows.slot[1].used_words != 1934u ||
            shadows.slot[1].unique_fragment_count != ACTIVE_UNIQUE ||
            shadows.slot[1].dedup_checksum != scratch.map_checksum ||
            model.mutation_lock != 0u)
        return 12;
    for (index = 0u; index < PREFIX_WORDS; ++index)
        if (shadow_words[1][index] != prefix[index]) return 13;
    for (index = 0u; index < 228u; ++index) {
        uint16_t at = (uint16_t)(PREFIX_WORDS + index * 3u);
        uint32_t expected_x = PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_X |
            ((((uint32_t)(uint16_t)objects[index].vertex_x) << 1) &
             0x1FFFFul);
        uint32_t expected_y = PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_Y |
            ((((uint32_t)(uint16_t)objects[index].vertex_y) << 1) &
             0x1FFFFul);
        uint16_t mapped = (uint16_t)(index % ACTIVE_UNIQUE);
        uint32_t destination =
            (uint32_t)scratch.unique_word_offsets[mapped] * 4ul;
        if (shadow_words[1][at] != expected_x ||
                shadow_words[1][at + 1u] != expected_y ||
                shadow_words[1][at + 2u] !=
                    (PYZ80_DRAW_RAMDL_V4_DL_CALL | destination) ||
                (destination & 3ul) || destination > 8191ul)
            return 14;
    }
    if (shadow_words[1][694] != suffix[0] ||
            shadow_words[1][695] != suffix[1] ||
            shadow_words[1][696] != PYZ80_DRAW_RAMDL_V4_DL_DISPLAY)
        return 15;
    cursor = layout.main_words;
    for (unique = 0u; unique < ACTIVE_UNIQUE; ++unique) {
        uint16_t word;
        if (scratch.unique_word_offsets[unique] != cursor) return 16;
        for (word = 0u; word < fragments[unique].word_count; ++word)
            if (shadow_words[1][cursor++] != fragment_words[unique][word])
                return 17;
        if (shadow_words[1][cursor++] != PYZ80_DRAW_RAMDL_V4_DL_RETURN)
            return 18;
    }
    if (cursor != 1934u) return 19;
    for (cursor = 1934u; cursor < PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS;
            ++cursor)
        if (shadow_words[1][cursor] != PYZ80_DRAW_RAMDL_V4_DL_DISPLAY)
            return 20;
    return 0;
}

static int check_capacity_boundaries(void)
{
    uint16_t index;
    initialize_common(228u);
    for (index = 0u; index < 228u; ++index) {
        objects[index].fragment = &fragments[0];
        objects[index].generation = fragments[0].generation;
    }
    fragments[0].word_count = 4u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_OK ||
            layout.total_words != 702u || scratch.unique_count != 1u)
        return 30;
    fragments[0].word_count = 25u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_OK ||
            layout.total_words != 723u || scratch.unique_count != 1u)
        return 31;

    initialize_common(71u);
    for (index = 0u; index < 69u; ++index)
        fragments[index].word_count = 25u;
    fragments[69].word_count = 4u;
    fragments[70].word_count = 21u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_OK ||
            layout.total_words != 2047u || scratch.unique_count != 71u)
        return 32;
    if (build() != PYZ80_DRAW_RAMDL_V4_OK ||
            shadows.slot[1].used_words != 2047u ||
            shadow_words[1][2046] != PYZ80_DRAW_RAMDL_V4_DL_RETURN ||
            shadow_words[1][2047] != PYZ80_DRAW_RAMDL_V4_DL_DISPLAY)
        return 33;

    initialize_common(71u);
    for (index = 0u; index < 69u; ++index)
        fragments[index].word_count = 25u;
    fragments[69].word_count = 4u;
    fragments[70].word_count = 22u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_CAPACITY ||
            layout.first_failure_index != 70u ||
            scratch.model_epoch != 0u || scratch.map_checksum != 0u)
        return 34;

    initialize_common(228u);
    for (index = 0u; index < 228u; ++index)
        fragments[index].word_count = 25u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_CAPACITY ||
            layout.first_failure_index != 51u)
        return 35;
    return 0;
}

static int check_duplicate_contract_and_fragment_gate(void)
{
    initialize_common(2u);
    fragments[1].identity = fragments[0].identity;
    fragments[1].generation = fragments[0].generation;
    objects[1].generation = fragments[1].generation;
    fragment_words[1][2] ^= 1ul;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_DEDUP_MISMATCH ||
            layout.first_failure_index != 1u) return 40;
    initialize_common(2u);
    fragments[1].identity = fragments[0].identity;
    fragments[1].generation = fragments[0].generation;
    objects[1].generation = fragments[1].generation;
    fragments[1].word_count = 5u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_DEDUP_MISMATCH ||
            layout.first_failure_index != 1u) return 41;
    initialize_common(2u);
    fragments[1].identity = fragments[0].identity;
    fragments[1].generation = fragments[0].generation;
    objects[1].generation = fragments[1].generation;
    fragments[1].worst_line_cycles++;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_DEDUP_MISMATCH ||
            layout.first_failure_index != 1u) return 42;
    initialize_common(1u);
    fragment_words[0][1] = PYZ80_DRAW_RAMDL_V4_DL_CALL | 4u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_FRAGMENT ||
            layout.first_failure_index != 0u) return 43;
    initialize_common(1u);
    fragments[0].generation++;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_FRAGMENT ||
            layout.first_failure_index != 0u) return 44;
    initialize_common(1u);
    certificate.dedup_identity_generation_proof = 0u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_CERTIFICATE) return 45;
    return 0;
}

static int check_raster_exact_gate(void)
{
    initialize_common(1u);
    raster_lines[400] = 1209u;
    raster.max_cycles = 1209u;
    raster.worst_line = 400u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_OK ||
            layout.worst_line_cycles != 1209u) return 50;
    raster_lines[400] = 1210u;
    raster.max_cycles = 1210u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_RASTER) return 51;
    raster_lines[400] = 1209u;
    raster.max_cycles = 1209u;
    raster.model_epoch--;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_STALE_EPOCH) return 52;
    raster.model_epoch = model.epoch;
    raster.max_cycles = 1208u;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_STALE_EPOCH) return 53;
    return 0;
}

static int check_mutation_hooks_and_stale_proof(void)
{
    PyZ80DrawRamDLV4Object spawned;
    uint16_t prior_epoch;
    initialize_common(3u);
    spawned = objects[8];
    prior_epoch = model.epoch;
    if (PyZ80DrawRamDLV4_OnSpawn(&model, 1u, &spawned) !=
            PYZ80_DRAW_RAMDL_V4_OK || model.count != 4u ||
            model.objects[1].object_id != spawned.object_id ||
            model.objects[2].object_id != 3001u || model.epoch == prior_epoch ||
            !(model.dirty & PYZ80_DRAW_RAMDL_V4_DIRTY_LIST) ||
            !(model.dirty & PYZ80_DRAW_RAMDL_V4_DIRTY_ORDER)) return 60;
    if (preflight() != PYZ80_DRAW_RAMDL_V4_STALE_EPOCH) return 61;
    raster.model_epoch = model.epoch;
    prior_epoch = model.epoch;
    if (PyZ80DrawRamDLV4_OnMove(&model, 1u, 3u) !=
            PYZ80_DRAW_RAMDL_V4_OK ||
            model.objects[3].object_id != spawned.object_id ||
            model.epoch == prior_epoch) return 62;
    if (PyZ80DrawRamDLV4_OnCoordinates(&model, 0u, -7, 99) !=
            PYZ80_DRAW_RAMDL_V4_OK || model.objects[0].vertex_x != -7 ||
            model.objects[0].vertex_y != 99) return 63;
    if (PyZ80DrawRamDLV4_OnIdentity(
            &model, 0u, &fragments[5], fragments[5].generation) !=
            PYZ80_DRAW_RAMDL_V4_OK ||
            model.objects[0].fragment != &fragments[5]) return 64;
    if (PyZ80DrawRamDLV4_OnRemove(&model, 2u) !=
            PYZ80_DRAW_RAMDL_V4_OK || model.count != 3u) return 65;
    model.mutation_lock = 1u;
    if (PyZ80DrawRamDLV4_OnCoordinates(&model, 0u, 0, 0) !=
            PYZ80_DRAW_RAMDL_V4_INVALID_INPUT) return 66;
    if (build() != PYZ80_DRAW_RAMDL_V4_BUSY ||
            model.mutation_lock != 1u) return 67;
    model.mutation_lock = 0u;
    return 0;
}

static int check_fail_atomic_publication(void)
{
    initialize_common(1u);
    /* Alias the immutable source into the chosen inactive shadow.  Main-list
     * writes then violate the seal; the final checksum gate must abort and
     * must never expose READY despite a partially written shadow. */
    fragments[0].words = shadow_words[1];
    fragments[0].word_count = 4u;
    shadow_words[1][0] = 0x09000011ul;
    shadow_words[1][1] = 0x09000022ul;
    shadow_words[1][2] = 0x09000033ul;
    shadow_words[1][3] = 0x09000044ul;
    if (build() != PYZ80_DRAW_RAMDL_V4_STALE_EPOCH ||
            shadows.slot[1].state != PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED ||
            shadows.slot[1].publish_epoch != 0u ||
            shadows.next_publish_epoch != 0u ||
            model.mutation_lock != 0u) return 70;
    return 0;
}

static int check_double_shadow_and_both_fences(void)
{
    uint8_t slot = 0xFFu;
    uint16_t epoch;
    initialize_common(2u);
    if (build() != PYZ80_DRAW_RAMDL_V4_OK) return 80;
    epoch = shadows.slot[1].publish_epoch;
    if (!epoch || PyZ80DrawRamDLV4_AcquireReady(&shadows, &slot) !=
            PYZ80_DRAW_RAMDL_V4_OK || slot != 1u ||
            shadows.slot[1].state != PYZ80_DRAW_RAMDL_V4_SHADOW_DMA)
        return 81;
    if (build() != PYZ80_DRAW_RAMDL_V4_NO_INACTIVE_SHADOW ||
            model.mutation_lock != 0u) return 82;
    if (PyZ80DrawRamDLV4_MarkDMADone(&shadows, 1u) !=
            PYZ80_DRAW_RAMDL_V4_OK ||
            shadows.slot[1].state !=
                PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING) return 83;
    if (PyZ80DrawRamDLV4_RetireSwap(&shadows, 1u, 1u, 0u) !=
            PYZ80_DRAW_RAMDL_V4_FENCE ||
            PyZ80DrawRamDLV4_RetireSwap(&shadows, 1u, 0u, 1u) !=
                PYZ80_DRAW_RAMDL_V4_FENCE ||
            shadows.retired_epoch != 0u || shadows.active_slot != 0u ||
            shadows.slot[1].state !=
                PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING) return 84;
    if (PyZ80DrawRamDLV4_RetireSwap(&shadows, 1u, 1u, 1u) !=
            PYZ80_DRAW_RAMDL_V4_OK || shadows.active_slot != 1u ||
            shadows.retired_epoch != epoch || shadows.dma_slot != 0xFFu ||
            shadows.slot[0].state != PYZ80_DRAW_RAMDL_V4_SHADOW_RETIRED ||
            shadows.slot[1].state != PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE)
        return 85;
    raster.model_epoch = model.epoch;
    if (build() != PYZ80_DRAW_RAMDL_V4_OK ||
            shadows.slot[0].state != PYZ80_DRAW_RAMDL_V4_SHADOW_READY ||
            shadows.slot[0].publish_epoch == epoch) return 86;
    return 0;
}

int main(void)
{
    int result;
    result = check_active_catalog_dedup_and_exact_order();
    if (result) return result;
    result = check_capacity_boundaries();
    if (result) return result;
    result = check_duplicate_contract_and_fragment_gate();
    if (result) return result;
    result = check_raster_exact_gate();
    if (result) return result;
    result = check_mutation_hooks_and_stale_proof();
    if (result) return result;
    result = check_fail_atomic_publication();
    if (result) return result;
    result = check_double_shadow_and_both_fences();
    if (result) return result;
    return 0;
}
'''


def run_host_reference_matrix() -> dict[str, object]:
    if HOST_CC is None:
        raise RuntimeError("pinned/local TCC host compiler was not found")
    with tempfile.TemporaryDirectory(prefix="pyz80_ramdl_v4_") as raw:
        work = Path(raw)
        harness = work / "harness.c"
        executable = work / "harness.exe"
        harness.write_text(HARNESS, encoding="utf-8", newline="\n")
        compile_run = subprocess.run(
            [
                str(HOST_CC), "-Wall", "-Werror", "-std=c11",
                f"-I{ROOT / 'Source' / 'C' / 'ft812'}",
                str(harness),
                str(ROOT / "Source" / "C" / "ft812" /
                    "pyz80_draw_ramdl_shadow_v4.c"),
                "-o", str(executable),
            ],
            cwd=ROOT, check=False, capture_output=True, text=True,
        )
        if compile_run.returncode:
            raise RuntimeError(
                "host harness compilation failed:\n" +
                compile_run.stdout + compile_run.stderr)
        test_run = subprocess.run(
            [str(executable)], cwd=ROOT, check=False,
            capture_output=True, text=True,
        )
        if test_run.returncode:
            raise RuntimeError(
                f"host matrix failed with code {test_run.returncode}:\n" +
                test_run.stdout + test_run.stderr)
    return {
        "compiler": str(HOST_CC),
        "cases": 7,
        "active_catalog_cyclic_words": 1934,
        "shared_min_words": 702,
        "shared_max_words": 723,
        "boundary_pass_words": 2047,
        "boundary_fail_words": 2048,
        "status": "pass",
    }


class DirectRamDLShadowV4Tests(unittest.TestCase):
    def test_host_reference_matrix(self) -> None:
        self.assertEqual(run_host_reference_matrix()["status"], "pass")


if __name__ == "__main__":
    unittest.main()
