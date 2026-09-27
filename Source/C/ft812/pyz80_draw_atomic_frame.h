/* Two-pass whole-frame publication protocol for compact Python draw VM.
 *
 * Pass A replays the complete VM into a non-writing resolver, proves the
 * source-derived record/CMD_APPEND/RAM_DL/768-line bounds, and computes the
 * exact physical queue size.  Pass B replays the same immutable snapshot,
 * materializes only bounded six-byte chunks into an inactive queue, and calls
 * one final commit.  No full-frame record array is required.
 *
 * This file contains no gameplay branches.  A live caller still needs an
 * independently certified immutable snapshot/callback/ISR/link contract.
 */
#ifndef PYZ80_DRAW_ATOMIC_FRAME_H
#define PYZ80_DRAW_ATOMIC_FRAME_H

#include <stdint.h>

#include "pyz80_ft812.h"
#include "rtype_python_draw_vm.h"

#define PYZ80_DRAW_ATOMIC_CERTIFICATE_VERSION 4u
#define PYZ80_DRAW_ATOMIC_RASTER_LINES 768u
#define PYZ80_DRAW_ATOMIC_SAFE_LINE_CYCLES 1209u
#define PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS 128u
#define PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS 10u
#define PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS 3u
#define PYZ80_DRAW_ATOMIC_RECORD_DL_WORDS 2u
#define PYZ80_DRAW_ATOMIC_RECORD_PHYSICAL_WORDS 5u

typedef struct PyZ80DrawAtomicCertificate {
    /* Direct bindings to frame-sprite-fragment-envelope.v4. */
    uint8_t format_version;
    uint8_t sizing_proof_complete;
    uint16_t certified_max_records;
    uint16_t chunk_capacity_records;
    uint16_t max_chunks;
    uint16_t max_cmd_append_expanded_words;
    uint16_t max_fragment_expanded_dl_words;
    const uint16_t *raster_cycles_by_line;
    uint16_t raster_line_count;
} PyZ80DrawAtomicCertificate;

typedef struct PyZ80DrawAtomicFrameBudget {
    /* The active VDAC2 contract is exactly 2048 physical RAM_DL words, but
     * the final DISPLAY must occur before word 2047: total_frame_dl_words is
     * therefore required to be strictly less than this value. */
    uint16_t ram_dl_word_limit;
    uint16_t non_fragment_dl_words;
    uint16_t safe_line_cycles;
} PyZ80DrawAtomicFrameBudget;

typedef struct PyZ80DrawAtomicResolvedRecord {
    uint16_t template_index;
    uint16_t append_expanded_words;
} PyZ80DrawAtomicResolvedRecord;

/* The resolver must be pure for one immutable replay snapshot. */
typedef uint8_t (*PyZ80DrawAtomicResolve)(
    void *context, const rtype_python_draw_vm_record *record,
    PyZ80DrawAtomicResolvedRecord *resolved_out);

/* prepare(pass=0/1) resets any external traversal cursor and returns an
 * immutable snapshot token.  Equal tokens are necessary; the generated VM
 * and callbacks must additionally be certified pure by the integration gate. */
typedef uint8_t (*PyZ80DrawAtomicPrepareReplay)(
    void *context, uint8_t pass, uint32_t *snapshot_token_out);

typedef struct PyZ80DrawAtomicReplay {
    PyZ80DrawAtomicPrepareReplay prepare;
    void *context;
} PyZ80DrawAtomicReplay;

typedef struct PyZ80DrawAtomicPreflight {
    uint16_t record_count;
    uint16_t chunk_count;
    uint16_t cmd_append_expanded_words;
    uint16_t fragment_expanded_dl_words;
    uint16_t fragment_physical_words;
    uint16_t total_frame_dl_words;
    uint16_t worst_raster_line;
    uint16_t worst_line_cycles;
    uint16_t replay_signature_a;
    uint16_t replay_signature_b;
    uint32_t snapshot_token;
} PyZ80DrawAtomicPreflight;

/* begin and append may write only private/inactive storage.  They must not
 * expose READY or nonzero public length.  commit is the sole publication
 * callback and must either publish the complete image or publish nothing.
 * abort must be idempotent and safe even when prepare-B or begin failed: once
 * Pass A succeeds, every unsuccessful attempt to enter/execute Pass B invokes
 * it exactly once. */
typedef uint8_t (*PyZ80DrawAtomicWriterBegin)(
    void *context, const PyZ80DrawAtomicPreflight *preflight);
typedef uint8_t (*PyZ80DrawAtomicWriterAppend)(
    void *context, const volatile PyZ80FtTemplateDrawRecord *records,
    uint16_t count, uint16_t first_record_index);
typedef uint8_t (*PyZ80DrawAtomicWriterCommit)(
    void *context, const PyZ80DrawAtomicPreflight *preflight);
typedef void (*PyZ80DrawAtomicWriterAbort)(void *context);

typedef struct PyZ80DrawAtomicWriter {
    PyZ80DrawAtomicWriterBegin begin;
    PyZ80DrawAtomicWriterAppend append;
    PyZ80DrawAtomicWriterCommit commit;
    PyZ80DrawAtomicWriterAbort abort;
    void *context;
} PyZ80DrawAtomicWriter;

typedef enum PyZ80DrawAtomicStatus {
    PYZ80_DRAW_ATOMIC_OK = 0,
    PYZ80_DRAW_ATOMIC_INVALID_INPUT = 1,
    PYZ80_DRAW_ATOMIC_CERTIFICATE = 2,
    PYZ80_DRAW_ATOMIC_PREPARE_A = 3,
    PYZ80_DRAW_ATOMIC_VM_A = 4,
    PYZ80_DRAW_ATOMIC_RECORD_BOUND = 5,
    PYZ80_DRAW_ATOMIC_LOOKUP_A = 6,
    PYZ80_DRAW_ATOMIC_APPEND_BOUND = 7,
    PYZ80_DRAW_ATOMIC_RAM_DL = 8,
    PYZ80_DRAW_ATOMIC_RASTER = 9,
    PYZ80_DRAW_ATOMIC_PREPARE_B = 10,
    PYZ80_DRAW_ATOMIC_REPLAY_TOKEN = 11,
    PYZ80_DRAW_ATOMIC_WRITER_BEGIN = 12,
    PYZ80_DRAW_ATOMIC_VM_B = 13,
    PYZ80_DRAW_ATOMIC_LOOKUP_B = 14,
    PYZ80_DRAW_ATOMIC_REPLAY_MISMATCH = 15,
    PYZ80_DRAW_ATOMIC_WRITER_APPEND = 16,
    PYZ80_DRAW_ATOMIC_WRITER_COMMIT = 17
} PyZ80DrawAtomicStatus;

typedef struct PyZ80DrawAtomicResult {
    PyZ80DrawAtomicPreflight preflight;
    uint16_t pass_a_records;
    uint16_t pass_b_records;
    uint16_t private_records_written;
    uint16_t private_chunks_written;
    uint16_t failure_record_index;
    uint16_t failure_bank_key;
    uint16_t failure_descriptor;
    uint8_t pass_a_vm_status;
    uint8_t pass_b_vm_status;
    uint8_t status;
    uint8_t committed;
} PyZ80DrawAtomicResult;

PyZ80DrawAtomicStatus PyZ80DrawAtomic_Run(
    const rtype_python_draw_vm_input *input,
    const PyZ80DrawAtomicCertificate *certificate,
    const PyZ80DrawAtomicFrameBudget *budget,
    PyZ80DrawAtomicResolve resolve, void *resolve_context,
    const PyZ80DrawAtomicReplay *replay,
    const PyZ80DrawAtomicWriter *writer,
    volatile PyZ80FtTemplateDrawRecord *chunk_records,
    uint16_t chunk_record_capacity,
    PyZ80DrawAtomicResult *result);

/* Generated HQT3 resolver: target-neutral identity/coordinate preflight with
 * no queue write.  It returns the actual phase-selected CMD_APPEND size. */
uint8_t PyZ80DrawAtomic_ResolveGeneratedHQT3(
    void *context, const rtype_python_draw_vm_record *record,
    PyZ80DrawAtomicResolvedRecord *resolved_out);

typedef struct PyZ80DrawAtomicFT812WriterContext {
    volatile PyZ80FtQueue *queue;
    uint16_t frame_sequence;
    uint16_t expected_physical_words;
    uint16_t expected_dl_words;
    uint16_t write_index;
    uint16_t dl_words;
    uint16_t records_written;
    uint16_t chunks_written;
    uint8_t begun;
} PyZ80DrawAtomicFT812WriterContext;

uint8_t PyZ80DrawAtomicFT812_Begin(
    void *context, const PyZ80DrawAtomicPreflight *preflight);
uint8_t PyZ80DrawAtomicFT812_Append(
    void *context, const volatile PyZ80FtTemplateDrawRecord *records,
    uint16_t count, uint16_t first_record_index);
uint8_t PyZ80DrawAtomicFT812_Commit(
    void *context, const PyZ80DrawAtomicPreflight *preflight);
void PyZ80DrawAtomicFT812_Abort(void *context);

#endif
