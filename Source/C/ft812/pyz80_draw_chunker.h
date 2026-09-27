/* Bounded bridge from generated Python draw records to target FT812 batches.
 *
 * The generated draw plan owns semantic order.  This adapter owns only a
 * caller-provided finite buffer and a flush callback.  It never drops a
 * record when the buffer becomes full: the complete preceding chunk must be
 * accepted before the next Python record is copied.
 */
#ifndef PYZ80_DRAW_CHUNKER_H
#define PYZ80_DRAW_CHUNKER_H

#include <stdint.h>

#include "rtype_python_draw_plan.h"

typedef uint8_t (*PyZ80DrawChunkFlush)(
    void *context, const rtype_python_draw_plan_record *records,
    uint16_t count);

typedef struct PyZ80DrawChunkState {
    rtype_python_draw_plan_record *records;
    uint16_t capacity;
    uint16_t count;
    uint16_t accepted_records;
    uint16_t flushed_records;
    uint16_t chunk_count;
    PyZ80DrawChunkFlush flush;
    void *flush_context;
    uint8_t failed;
} PyZ80DrawChunkState;

typedef enum PyZ80DrawChunkStatus {
    PYZ80_DRAW_CHUNK_OK = 0,
    PYZ80_DRAW_CHUNK_INVALID_INPUT = 1,
    PYZ80_DRAW_CHUNK_DRAW_PLAN = 2,
    PYZ80_DRAW_CHUNK_FLUSH = 3
} PyZ80DrawChunkStatus;

typedef struct PyZ80DrawChunkResult {
    uint16_t accepted_records;
    uint16_t flushed_records;
    uint16_t chunk_count;
    uint8_t draw_plan_status;
} PyZ80DrawChunkResult;

uint8_t PyZ80DrawChunk_Initialize(
    PyZ80DrawChunkState *state, rtype_python_draw_plan_record *records,
    uint16_t capacity, PyZ80DrawChunkFlush flush, void *flush_context);

/* Signature-compatible with rtype_python_draw_plan_record_emitter. */
uint8_t PyZ80DrawChunk_Emit(
    void *context, const rtype_python_draw_plan_record *record);

uint8_t PyZ80DrawChunk_Finish(PyZ80DrawChunkState *state);

/* Complete generated preflight/stream/final-flush transaction.  A FLUSH
 * result leaves the unaccepted chunk in the caller-owned buffer for
 * inspection; later Python records have not been visited. */
PyZ80DrawChunkStatus PyZ80DrawChunk_Run(
    const rtype_python_draw_plan_input *input,
    PyZ80DrawChunkState *state, rtype_python_draw_plan_record *records,
    uint16_t capacity, PyZ80DrawChunkFlush flush, void *flush_context,
    PyZ80DrawChunkResult *result);

#endif
