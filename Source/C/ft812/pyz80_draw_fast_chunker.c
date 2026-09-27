#include "pyz80_draw_fast_chunker.h"

#include <stddef.h>

typedef char PyZ80DrawFast_VMRecordSize[
    sizeof(rtype_python_draw_vm_record) == 8 ? 1 : -1];
typedef char PyZ80DrawFast_VMRecordBankOffset[
    offsetof(rtype_python_draw_vm_record, bank_key) == 0 ? 1 : -1];
typedef char PyZ80DrawFast_VMRecordDescriptorOffset[
    offsetof(rtype_python_draw_vm_record, descriptor) == 2 ? 1 : -1];
typedef char PyZ80DrawFast_VMRecordXOffset[
    offsetof(rtype_python_draw_vm_record, anchor_x) == 4 ? 1 : -1];
typedef char PyZ80DrawFast_VMRecordYOffset[
    offsetof(rtype_python_draw_vm_record, anchor_y) == 6 ? 1 : -1];
typedef char PyZ80DrawFast_TargetRecordSize[
    sizeof(PyZ80FtTemplateDrawRecord) == 6 ? 1 : -1];

static void PyZ80DrawFastChunk_CopyResult(
        const PyZ80DrawFastChunkState *state, uint8_t draw_vm_status,
        PyZ80DrawFastChunkResult *result)
{
    result->accepted_records = state->accepted_records;
    result->published_records = state->published_records;
    result->buffered_records = state->count;
    result->chunk_count = state->chunk_count;
    result->failure_record_index = state->failure_record_index;
    result->failure_bank_key = state->failure_bank_key;
    result->failure_descriptor = state->failure_descriptor;
    result->draw_vm_status = draw_vm_status;
    result->failure = state->failure;
}

static void PyZ80DrawFastChunk_SetFailure(
        PyZ80DrawFastChunkState *state, uint8_t failure,
        uint16_t record_index, uint16_t bank_key, uint16_t descriptor)
{
    if (state->failure == PYZ80_DRAW_FAST_FAILURE_NONE) {
        state->failure = failure;
        state->failure_record_index = record_index;
        state->failure_bank_key = bank_key;
        state->failure_descriptor = descriptor;
    }
}

static uint8_t PyZ80DrawFastChunk_FlushBuffered(
        PyZ80DrawFastChunkState *state)
{
    uint16_t first_record_index;
    if (state->count == 0u) {
        return 1u;
    }
    if (state->failure != PYZ80_DRAW_FAST_FAILURE_NONE) {
        return 0u;
    }
    if (state->published_records >
            (uint16_t)(0xFFFFu - state->count) ||
            state->chunk_count == 0xFFFFu) {
        PyZ80DrawFastChunk_SetFailure(
            state, PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW,
            state->published_records, 0u, 0u);
        return 0u;
    }
    first_record_index = state->published_records;
    if (state->submit(
            state->submit_context, state->records, state->count,
            first_record_index) == 0u) {
        PyZ80DrawFastChunk_SetFailure(
            state, PYZ80_DRAW_FAST_FAILURE_SUBMIT,
            first_record_index, 0u, 0u);
        return 0u;
    }
    state->published_records = (uint16_t)(
        state->published_records + state->count);
    state->chunk_count++;
    state->count = 0u;
    return 1u;
}

uint8_t PyZ80DrawFastChunk_Initialize(
        PyZ80DrawFastChunkState *state,
        volatile PyZ80FtTemplateDrawRecord *records, uint16_t capacity,
        PyZ80DrawFastChunkSubmit submit, void *submit_context)
{
    if (state == NULL || records == NULL || submit == NULL ||
            capacity == 0u || capacity > PYZ80_FT_BATCH_MAX_RECORDS) {
        return 0u;
    }
    state->records = records;
    state->capacity = capacity;
    state->count = 0u;
    state->accepted_records = 0u;
    state->published_records = 0u;
    state->chunk_count = 0u;
    state->failure_record_index = 0u;
    state->failure_bank_key = 0u;
    state->failure_descriptor = 0u;
    state->submit = submit;
    state->submit_context = submit_context;
    state->failure = PYZ80_DRAW_FAST_FAILURE_NONE;
    return 1u;
}

uint8_t PyZ80DrawFastChunk_Emit(
        void *context, const rtype_python_draw_vm_record *record)
{
    PyZ80DrawFastChunkState *state = (PyZ80DrawFastChunkState *)context;
    uint16_t template_index;
    volatile PyZ80FtTemplateDrawRecord *target;
    if (state == NULL || record == NULL ||
            state->failure != PYZ80_DRAW_FAST_FAILURE_NONE ||
            state->records == NULL || state->submit == NULL ||
            state->capacity == 0u ||
            state->capacity > PYZ80_FT_BATCH_MAX_RECORDS ||
            state->count > state->capacity) {
        if (state != NULL) {
            PyZ80DrawFastChunk_SetFailure(
                state, PYZ80_DRAW_FAST_FAILURE_INVALID_INPUT,
                state->accepted_records, 0u, 0u);
        }
        return 0u;
    }
    /* Preserve the literal chunker's accepted-prefix boundary: publish the
     * complete preceding chunk before touching the next VM record. */
    if (state->count == state->capacity &&
            PyZ80DrawFastChunk_FlushBuffered(state) == 0u) {
        return 0u;
    }
    if (state->accepted_records == 0xFFFFu) {
        PyZ80DrawFastChunk_SetFailure(
            state, PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW,
            state->accepted_records, record->bank_key, record->descriptor);
        return 0u;
    }
    /* This hash table and its immutable indices are generated from the same
     * active-Python HQT3 source as PyZ80FT_BuildSpriteBatchFast. */
    template_index = PyZ80FT_FindHQTemplate(
        record->bank_key, record->descriptor);
    if (template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) {
        PyZ80DrawFastChunk_SetFailure(
            state, PYZ80_DRAW_FAST_FAILURE_LOOKUP,
            state->accepted_records, record->bank_key, record->descriptor);
        return 0u;
    }
    target = &state->records[state->count];
    target->template_index = template_index;
    target->anchor_x = record->anchor_x;
    target->anchor_y = record->anchor_y;
    state->count++;
    state->accepted_records++;
    return 1u;
}

uint8_t PyZ80DrawFastChunk_Finish(PyZ80DrawFastChunkState *state)
{
    if (state == NULL ||
            state->failure != PYZ80_DRAW_FAST_FAILURE_NONE) {
        return 0u;
    }
    return PyZ80DrawFastChunk_FlushBuffered(state);
}

PyZ80DrawFastChunkStatus PyZ80DrawFastChunk_Run(
        const rtype_python_draw_vm_input *input,
        PyZ80DrawFastChunkState *state,
        volatile PyZ80FtTemplateDrawRecord *records, uint16_t capacity,
        PyZ80DrawFastChunkSubmit submit, void *submit_context,
        PyZ80DrawFastChunkResult *result)
{
    rtype_python_draw_vm_status draw_status;
    uint16_t streamed = 0u;
    if (result == NULL ||
            PyZ80DrawFastChunk_Initialize(
                state, records, capacity, submit, submit_context) == 0u) {
        return PYZ80_DRAW_FAST_CHUNK_INVALID_INPUT;
    }
    draw_status = rtype_python_draw_vm_stream(
        input, PyZ80DrawFastChunk_Emit, state, &streamed);
    if (draw_status != RTYPE_PYTHON_DRAW_VM_OK) {
        PyZ80DrawFastChunk_CopyResult(state, (uint8_t)draw_status, result);
        if (draw_status == RTYPE_PYTHON_DRAW_VM_EMITTER) {
            if (state->failure == PYZ80_DRAW_FAST_FAILURE_LOOKUP) {
                return PYZ80_DRAW_FAST_CHUNK_LOOKUP;
            }
            if (state->failure ==
                    PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW) {
                return PYZ80_DRAW_FAST_CHUNK_COUNTER_OVERFLOW;
            }
            if (state->failure == PYZ80_DRAW_FAST_FAILURE_SUBMIT) {
                return PYZ80_DRAW_FAST_CHUNK_SUBMIT;
            }
        }
        return PYZ80_DRAW_FAST_CHUNK_VM;
    }
    if (streamed != state->accepted_records) {
        PyZ80DrawFastChunk_SetFailure(
            state, PYZ80_DRAW_FAST_FAILURE_VM_COUNT,
            state->accepted_records, 0u, 0u);
        PyZ80DrawFastChunk_CopyResult(
            state, (uint8_t)RTYPE_PYTHON_DRAW_VM_EMITTER, result);
        return PYZ80_DRAW_FAST_CHUNK_VM;
    }
    if (PyZ80DrawFastChunk_Finish(state) == 0u) {
        PyZ80DrawFastChunk_CopyResult(state, (uint8_t)draw_status, result);
        if (state->failure == PYZ80_DRAW_FAST_FAILURE_COUNTER_OVERFLOW) {
            return PYZ80_DRAW_FAST_CHUNK_COUNTER_OVERFLOW;
        }
        return PYZ80_DRAW_FAST_CHUNK_SUBMIT;
    }
    PyZ80DrawFastChunk_CopyResult(state, (uint8_t)draw_status, result);
    return PYZ80_DRAW_FAST_CHUNK_OK;
}

uint8_t PyZ80DrawFastChunk_SubmitFT812(
        void *context,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first_record_index)
{
    PyZ80DrawFastFT812SubmitContext *submit_context =
        (PyZ80DrawFastFT812SubmitContext *)context;
    PyZ80DrawFastBatchTarget target;
    if (submit_context == NULL || records == NULL || count == 0u ||
            count > PYZ80_FT_BATCH_MAX_RECORDS ||
            submit_context->provide_target == NULL ||
            submit_context->submitted_chunks == 0xFFFFu) {
        return 0u;
    }
    target.queue = NULL;
    target.remaining_dl_words = 0u;
    if (submit_context->provide_target(
            submit_context->provider_context,
            submit_context->submitted_chunks, first_record_index,
            &target) == 0u || target.queue == NULL ||
            target.remaining_dl_words > PYZ80_FT_RAM_DL_WORD_LIMIT) {
        return 0u;
    }
    if (PyZ80FT_BuildSpriteBatchFast(
            target.queue, records, count,
            target.remaining_dl_words) == 0u) {
        return 0u;
    }
    submit_context->submitted_chunks++;
    return 1u;
}
