#include "pyz80_draw_chunker.h"

#include <stddef.h>

typedef char PyZ80DrawChunk_RecordSize[
    sizeof(rtype_python_draw_plan_record) == 8 ? 1 : -1];
typedef char PyZ80DrawChunk_BankOffset[
    offsetof(rtype_python_draw_plan_record, bank_key) == 0 ? 1 : -1];
typedef char PyZ80DrawChunk_DescriptorOffset[
    offsetof(rtype_python_draw_plan_record, descriptor) == 2 ? 1 : -1];
typedef char PyZ80DrawChunk_XOffset[
    offsetof(rtype_python_draw_plan_record, anchor_x) == 4 ? 1 : -1];
typedef char PyZ80DrawChunk_YOffset[
    offsetof(rtype_python_draw_plan_record, anchor_y) == 6 ? 1 : -1];

static void PyZ80DrawChunk_CopyResult(
        const PyZ80DrawChunkState *state, uint8_t draw_plan_status,
        PyZ80DrawChunkResult *result)
{
    result->accepted_records = state->accepted_records;
    result->flushed_records = state->flushed_records;
    result->chunk_count = state->chunk_count;
    result->draw_plan_status = draw_plan_status;
}

static uint8_t PyZ80DrawChunk_FlushBuffered(PyZ80DrawChunkState *state)
{
    if (state->count == 0u) {
        return 1u;
    }
    if (state->failed != 0u ||
            state->flush(state->flush_context, state->records,
                         state->count) == 0u) {
        state->failed = 1u;
        return 0u;
    }
    state->flushed_records = (uint16_t)(
        state->flushed_records + state->count);
    state->chunk_count++;
    state->count = 0u;
    return 1u;
}

uint8_t PyZ80DrawChunk_Initialize(
        PyZ80DrawChunkState *state, rtype_python_draw_plan_record *records,
        uint16_t capacity, PyZ80DrawChunkFlush flush, void *flush_context)
{
    if (state == NULL || records == NULL || flush == NULL || capacity == 0u) {
        return 0u;
    }
    state->records = records;
    state->capacity = capacity;
    state->count = 0u;
    state->accepted_records = 0u;
    state->flushed_records = 0u;
    state->chunk_count = 0u;
    state->flush = flush;
    state->flush_context = flush_context;
    state->failed = 0u;
    return 1u;
}

uint8_t PyZ80DrawChunk_Emit(
        void *context, const rtype_python_draw_plan_record *record)
{
    PyZ80DrawChunkState *state = (PyZ80DrawChunkState *)context;
    rtype_python_draw_plan_record *target;

    if (state == NULL || record == NULL || state->failed != 0u) {
        return 0u;
    }
    /* Flush the already accepted prefix before touching the next record. */
    if (state->count == state->capacity &&
            PyZ80DrawChunk_FlushBuffered(state) == 0u) {
        return 0u;
    }
    target = &state->records[state->count];
    target->bank_key = record->bank_key;
    target->descriptor = record->descriptor;
    target->anchor_x = record->anchor_x;
    target->anchor_y = record->anchor_y;
    state->count++;
    state->accepted_records++;
    return 1u;
}

uint8_t PyZ80DrawChunk_Finish(PyZ80DrawChunkState *state)
{
    if (state == NULL || state->failed != 0u) {
        return 0u;
    }
    return PyZ80DrawChunk_FlushBuffered(state);
}

PyZ80DrawChunkStatus PyZ80DrawChunk_Run(
        const rtype_python_draw_plan_input *input,
        PyZ80DrawChunkState *state, rtype_python_draw_plan_record *records,
        uint16_t capacity, PyZ80DrawChunkFlush flush, void *flush_context,
        PyZ80DrawChunkResult *result)
{
    rtype_python_draw_plan_status draw_status;
    uint16_t streamed = 0u;

    if (result == NULL ||
            PyZ80DrawChunk_Initialize(
                state, records, capacity, flush, flush_context) == 0u) {
        return PYZ80_DRAW_CHUNK_INVALID_INPUT;
    }
    draw_status = rtype_python_draw_plan_stream(
        input, PyZ80DrawChunk_Emit, state, &streamed);
    if (draw_status != RTYPE_PYTHON_DRAW_PLAN_OK) {
        PyZ80DrawChunk_CopyResult(state, (uint8_t)draw_status, result);
        if (draw_status == RTYPE_PYTHON_DRAW_PLAN_EMITTER &&
                state->failed != 0u) {
            return PYZ80_DRAW_CHUNK_FLUSH;
        }
        return PYZ80_DRAW_CHUNK_DRAW_PLAN;
    }
    if (streamed != state->accepted_records) {
        PyZ80DrawChunk_CopyResult(
            state, (uint8_t)RTYPE_PYTHON_DRAW_PLAN_EMITTER, result);
        return PYZ80_DRAW_CHUNK_DRAW_PLAN;
    }
    if (PyZ80DrawChunk_Finish(state) == 0u) {
        PyZ80DrawChunk_CopyResult(state, (uint8_t)draw_status, result);
        return PYZ80_DRAW_CHUNK_FLUSH;
    }
    PyZ80DrawChunk_CopyResult(state, (uint8_t)draw_status, result);
    return PYZ80_DRAW_CHUNK_OK;
}
