/* Target-neutral bounded bridge from the compact active-Python draw VM to
 * the pre-resolved FT812 sprite-batch ABI.
 *
 * The VM is the sole owner of draw order.  This adapter never sorts and never
 * materializes a complete frame: it resolves immutable HQT3 identities into
 * a caller-owned chunk of six-byte records, then submits that whole chunk.
 * A successful submit callback is one indivisible published prefix.  The
 * supplied FT812 submit wrapper calls PyZ80FT_BuildSpriteBatchFast, whose
 * preflight publishes no partial payload on failure.
 */
#ifndef PYZ80_DRAW_FAST_CHUNKER_H
#define PYZ80_DRAW_FAST_CHUNKER_H

#include <stdint.h>

#include "pyz80_ft812.h"
#include "rtype_python_draw_vm.h"

typedef uint8_t (*PyZ80DrawFastChunkSubmit)(
    void *context,
    const volatile PyZ80FtTemplateDrawRecord *records,
    uint16_t count, uint16_t first_record_index);

typedef struct PyZ80DrawFastBatchTarget {
    volatile PyZ80FtQueue *queue;
    uint16_t remaining_dl_words;
} PyZ80DrawFastBatchTarget;

/* A live integrator may rotate queue pages here.  It must return a fresh
 * BUILDING fragment whose source-record window contains the caller's chunk.
 * This bridge does not acquire pages, alter MMU state, or guess a frame
 * budget. */
typedef uint8_t (*PyZ80DrawFastTargetProvider)(
    void *context, uint16_t chunk_index, uint16_t first_record_index,
    PyZ80DrawFastBatchTarget *target_out);

typedef struct PyZ80DrawFastFT812SubmitContext {
    PyZ80DrawFastTargetProvider provide_target;
    void *provider_context;
    uint16_t submitted_chunks;
} PyZ80DrawFastFT812SubmitContext;

typedef enum PyZ80DrawFastFailure {
    PYZ80_DRAW_FAST_FAILURE_NONE = 0,
    PYZ80_DRAW_FAST_FAILURE_INVALID_INPUT = 1,
    PYZ80_DRAW_FAST_FAILURE_LOOKUP = 2,
    PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW = 3,
    PYZ80_DRAW_FAST_FAILURE_SUBMIT = 4,
    PYZ80_DRAW_FAST_FAILURE_VM_COUNT = 5
} PyZ80DrawFastFailure;

typedef struct PyZ80DrawFastChunkState {
    volatile PyZ80FtTemplateDrawRecord *records;
    uint16_t capacity;
    uint16_t count;
    /* Accepted is the exact VM prefix held or already submitted. */
    uint16_t accepted_records;
    /* Published is the exact prefix covered by successful whole chunks. */
    uint16_t published_records;
    uint16_t chunk_count;
    uint16_t failure_record_index;
    uint16_t failure_bank_key;
    uint16_t failure_descriptor;
    PyZ80DrawFastChunkSubmit submit;
    void *submit_context;
    uint8_t failure;
} PyZ80DrawFastChunkState;

typedef enum PyZ80DrawFastChunkStatus {
    PYZ80_DRAW_FAST_CHUNK_OK = 0,
    PYZ80_DRAW_FAST_CHUNK_INVALID_INPUT = 1,
    PYZ80_DRAW_FAST_CHUNK_VM = 2,
    PYZ80_DRAW_FAST_CHUNK_LOOKUP = 3,
    PYZ80_DRAW_FAST_CHUNK_COUNTER_OVERFLOW = 4,
    PYZ80_DRAW_FAST_CHUNK_SUBMIT = 5
} PyZ80DrawFastChunkStatus;

typedef struct PyZ80DrawFastChunkResult {
    uint16_t accepted_records;
    uint16_t published_records;
    uint16_t buffered_records;
    uint16_t chunk_count;
    uint16_t failure_record_index;
    uint16_t failure_bank_key;
    uint16_t failure_descriptor;
    uint8_t draw_vm_status;
    uint8_t failure;
} PyZ80DrawFastChunkResult;

uint8_t PyZ80DrawFastChunk_Initialize(
    PyZ80DrawFastChunkState *state,
    volatile PyZ80FtTemplateDrawRecord *records, uint16_t capacity,
    PyZ80DrawFastChunkSubmit submit, void *submit_context);

/* Signature-compatible with rtype_python_draw_vm_record_emitter. */
uint8_t PyZ80DrawFastChunk_Emit(
    void *context, const rtype_python_draw_vm_record *record);

uint8_t PyZ80DrawFastChunk_Finish(PyZ80DrawFastChunkState *state);

/* Complete VM-preflight/stream/final-submit transaction.  If the VM or this
 * bridge fails, an incomplete final chunk remains private in caller memory;
 * only result.published_records may already be visible as complete batches. */
PyZ80DrawFastChunkStatus PyZ80DrawFastChunk_Run(
    const rtype_python_draw_vm_input *input,
    PyZ80DrawFastChunkState *state,
    volatile PyZ80FtTemplateDrawRecord *records, uint16_t capacity,
    PyZ80DrawFastChunkSubmit submit, void *submit_context,
    PyZ80DrawFastChunkResult *result);

/* Production submit callback.  It obtains the caller-owned queue/budget and
 * invokes the current six-byte PyZ80FT_BuildSpriteBatchFast entry point.
 * Records still must satisfy that function's target address/alignment rules. */
uint8_t PyZ80DrawFastChunk_SubmitFT812(
    void *context,
    const volatile PyZ80FtTemplateDrawRecord *records,
    uint16_t count, uint16_t first_record_index);

#endif
