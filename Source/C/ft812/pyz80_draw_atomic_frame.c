#include "pyz80_draw_atomic_frame.h"

#include <stddef.h>

#include "rtype_python_hq_templates.h"

#define PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_X 0x2B000000ul
#define PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_Y 0x2C000000ul
#define PYZ80_DRAW_ATOMIC_DL_END 0x21000000ul
#define PYZ80_DRAW_ATOMIC_CMD_APPEND 0xFFFFFF1Eul

static const uint32_t PyZ80DrawAtomic_BatchPrefix[
        PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS] = {
    0x04FFFFFFul, 0x150000A0ul, 0x16000000ul, 0x17000000ul,
    0x18000000ul, 0x190000A0ul, 0x1A000000ul, 0x08005830ul,
    0x27000003ul, 0x1F000001ul
};

typedef char PyZ80DrawAtomic_VMRecordSize[
    sizeof(rtype_python_draw_vm_record) == 8 ? 1 : -1];
typedef char PyZ80DrawAtomic_FastRecordSize[
    sizeof(PyZ80FtTemplateDrawRecord) == 6 ? 1 : -1];
typedef char PyZ80DrawAtomic_MaxChunkMatchesFT812[
    PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS == PYZ80_FT_BATCH_MAX_RECORDS ? 1 : -1];

typedef struct PyZ80DrawAtomicPassState {
    const PyZ80DrawAtomicCertificate *certificate;
    PyZ80DrawAtomicResolve resolve;
    void *resolve_context;
    const PyZ80DrawAtomicWriter *writer;
    volatile PyZ80FtTemplateDrawRecord *chunk_records;
    uint16_t chunk_capacity;
    uint16_t chunk_count;
    uint16_t records;
    uint16_t append_words;
    uint16_t signature_a;
    uint16_t signature_b;
    uint16_t private_records;
    uint16_t private_chunks;
    uint16_t failure_index;
    uint16_t failure_bank;
    uint16_t failure_descriptor;
    uint8_t failure;
    uint8_t pass;
} PyZ80DrawAtomicPassState;

static void PyZ80DrawAtomic_ZeroResult(PyZ80DrawAtomicResult *result)
{
    uint8_t *target = (uint8_t *)result;
    uint16_t count = (uint16_t)sizeof(*result);
    while (count != 0u) {
        *target++ = 0u;
        --count;
    }
}

static uint16_t PyZ80DrawAtomic_Rotate5(uint16_t value)
{
    return (uint16_t)((value << 5) | (value >> 11));
}

static void PyZ80DrawAtomic_SignWord(PyZ80DrawAtomicPassState *state,
                                     uint16_t value)
{
    state->signature_a = (uint16_t)(
        PyZ80DrawAtomic_Rotate5(state->signature_a) ^ value ^ 0x9E37u);
    state->signature_b = (uint16_t)(
        state->signature_b + state->signature_a + value + 0x7F4Au);
}

static void PyZ80DrawAtomic_SignRecord(
        PyZ80DrawAtomicPassState *state,
        const rtype_python_draw_vm_record *record,
        const PyZ80DrawAtomicResolvedRecord *resolved)
{
    PyZ80DrawAtomic_SignWord(state, record->bank_key);
    PyZ80DrawAtomic_SignWord(state, record->descriptor);
    PyZ80DrawAtomic_SignWord(state, (uint16_t)record->anchor_x);
    PyZ80DrawAtomic_SignWord(state, (uint16_t)record->anchor_y);
    PyZ80DrawAtomic_SignWord(state, resolved->template_index);
    PyZ80DrawAtomic_SignWord(state, resolved->append_expanded_words);
}

static void PyZ80DrawAtomic_Fail(
        PyZ80DrawAtomicPassState *state, uint8_t failure,
        const rtype_python_draw_vm_record *record)
{
    if (state->failure == 0u) {
        state->failure = failure;
        state->failure_index = state->records;
        if (record != NULL) {
            state->failure_bank = record->bank_key;
            state->failure_descriptor = record->descriptor;
        }
    }
}

static uint8_t PyZ80DrawAtomic_FlushChunk(PyZ80DrawAtomicPassState *state)
{
    uint16_t first;
    if (state->chunk_count == 0u) {
        return 1u;
    }
    if (state->writer == NULL || state->writer->append == NULL ||
            state->private_records >
                (uint16_t)(0xFFFFu - state->chunk_count)) {
        PyZ80DrawAtomic_Fail(
            state, PYZ80_DRAW_ATOMIC_WRITER_APPEND, NULL);
        return 0u;
    }
    first = state->private_records;
    if (state->writer->append(
            state->writer->context, state->chunk_records,
            state->chunk_count, first) == 0u) {
        PyZ80DrawAtomic_Fail(
            state, PYZ80_DRAW_ATOMIC_WRITER_APPEND, NULL);
        return 0u;
    }
    state->private_records = (uint16_t)(
        state->private_records + state->chunk_count);
    state->private_chunks++;
    state->chunk_count = 0u;
    return 1u;
}

static uint8_t PyZ80DrawAtomic_Emit(
        void *context, const rtype_python_draw_vm_record *record)
{
    PyZ80DrawAtomicPassState *state = (PyZ80DrawAtomicPassState *)context;
    PyZ80DrawAtomicResolvedRecord resolved;
    volatile PyZ80FtTemplateDrawRecord *target;
    uint16_t next_append;
    if (state == NULL || record == NULL || state->failure != 0u ||
            state->resolve == NULL || state->certificate == NULL) {
        if (state != NULL) {
            PyZ80DrawAtomic_Fail(
                state, PYZ80_DRAW_ATOMIC_INVALID_INPUT, record);
        }
        return 0u;
    }
    if (state->records >= state->certificate->certified_max_records) {
        PyZ80DrawAtomic_Fail(
            state, PYZ80_DRAW_ATOMIC_RECORD_BOUND, record);
        return 0u;
    }
    if (state->pass == 1u && state->chunk_count == state->chunk_capacity &&
            PyZ80DrawAtomic_FlushChunk(state) == 0u) {
        return 0u;
    }
    resolved.template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    resolved.append_expanded_words = 0u;
    if (state->resolve(
            state->resolve_context, record, &resolved) == 0u ||
            resolved.template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND ||
            resolved.append_expanded_words == 0u) {
        PyZ80DrawAtomic_Fail(
            state, state->pass == 0u ?
                PYZ80_DRAW_ATOMIC_LOOKUP_A : PYZ80_DRAW_ATOMIC_LOOKUP_B,
            record);
        return 0u;
    }
    if (state->append_words >
            (uint16_t)(0xFFFFu - resolved.append_expanded_words)) {
        PyZ80DrawAtomic_Fail(
            state, PYZ80_DRAW_ATOMIC_APPEND_BOUND, record);
        return 0u;
    }
    next_append = (uint16_t)(
        state->append_words + resolved.append_expanded_words);
    if (next_append >
            state->certificate->max_cmd_append_expanded_words) {
        PyZ80DrawAtomic_Fail(
            state, PYZ80_DRAW_ATOMIC_APPEND_BOUND, record);
        return 0u;
    }
    if (state->pass == 1u) {
        target = &state->chunk_records[state->chunk_count];
        target->template_index = resolved.template_index;
        target->anchor_x = record->anchor_x;
        target->anchor_y = record->anchor_y;
        state->chunk_count++;
    }
    PyZ80DrawAtomic_SignRecord(state, record, &resolved);
    state->append_words = next_append;
    state->records++;
    return 1u;
}

static uint8_t PyZ80DrawAtomic_CertificateValid(
        const PyZ80DrawAtomicCertificate *certificate,
        const PyZ80DrawAtomicFrameBudget *budget)
{
    uint32_t expected_chunks;
    uint32_t expected_words;
    uint16_t line;
    if (certificate == NULL || budget == NULL ||
            certificate->format_version !=
                PYZ80_DRAW_ATOMIC_CERTIFICATE_VERSION ||
            certificate->sizing_proof_complete != 1u ||
            certificate->certified_max_records == 0u ||
            certificate->chunk_capacity_records == 0u ||
            certificate->chunk_capacity_records >
                PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS ||
            certificate->raster_cycles_by_line == NULL ||
            certificate->raster_line_count !=
                PYZ80_DRAW_ATOMIC_RASTER_LINES ||
            budget->ram_dl_word_limit == 0u ||
            budget->ram_dl_word_limit > PYZ80_FT_RAM_DL_WORD_LIMIT ||
            budget->non_fragment_dl_words > budget->ram_dl_word_limit ||
            budget->safe_line_cycles !=
                PYZ80_DRAW_ATOMIC_SAFE_LINE_CYCLES) {
        return 0u;
    }
    expected_chunks = (
        (uint32_t)certificate->certified_max_records +
        certificate->chunk_capacity_records - 1u) /
        certificate->chunk_capacity_records;
    expected_words = expected_chunks * (
        PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS +
        PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS);
    expected_words += (uint32_t)certificate->certified_max_records *
        PYZ80_DRAW_ATOMIC_RECORD_DL_WORDS;
    expected_words += certificate->max_cmd_append_expanded_words;
    if (expected_chunks != certificate->max_chunks ||
            expected_words != certificate->max_fragment_expanded_dl_words ||
            expected_words > 0xFFFFul ||
            (uint32_t)budget->non_fragment_dl_words + expected_words >=
                budget->ram_dl_word_limit) {
        return 0u;
    }
    for (line = 0u; line < PYZ80_DRAW_ATOMIC_RASTER_LINES; ++line) {
        uint32_t cycles =
            (uint32_t)budget->non_fragment_dl_words + expected_words +
            certificate->raster_cycles_by_line[line];
        if (cycles > budget->safe_line_cycles) {
            return 0u;
        }
    }
    return 1u;
}

static void PyZ80DrawAtomic_CopyFailure(
        const PyZ80DrawAtomicPassState *state, PyZ80DrawAtomicResult *result)
{
    result->failure_record_index = state->failure_index;
    result->failure_bank_key = state->failure_bank;
    result->failure_descriptor = state->failure_descriptor;
}

PyZ80DrawAtomicStatus PyZ80DrawAtomic_Run(
        const rtype_python_draw_vm_input *input,
        const PyZ80DrawAtomicCertificate *certificate,
        const PyZ80DrawAtomicFrameBudget *budget,
        PyZ80DrawAtomicResolve resolve, void *resolve_context,
        const PyZ80DrawAtomicReplay *replay,
        const PyZ80DrawAtomicWriter *writer,
        volatile PyZ80FtTemplateDrawRecord *chunk_records,
        uint16_t chunk_record_capacity,
        PyZ80DrawAtomicResult *result)
{
    /* One state object is deliberately reused for both passes.  Apart from
     * reducing Z80 stack consumption, this keeps pinned SDCC away from frame
     * offsets it cannot encode efficiently.  Every Pass-A value needed by
     * Pass B is copied to result->preflight before the state is reset. */
    PyZ80DrawAtomicPassState pass;
    rtype_python_draw_vm_status vm_status;
    uint16_t streamed;
    uint32_t snapshot_a;
    uint32_t snapshot_b;
    uint32_t chunk_count;
    uint32_t fragment_words;
    uint32_t physical_words;
    uint32_t total_dl_words;
    uint32_t worst_cycles = 0u;
    uint16_t worst_line = 0u;
    uint16_t line;
    uint8_t began = 0u;
    PyZ80DrawAtomicStatus status;

    if (result == NULL) {
        return PYZ80_DRAW_ATOMIC_INVALID_INPUT;
    }
    PyZ80DrawAtomic_ZeroResult(result);
    if (input == NULL || resolve == NULL || replay == NULL ||
            replay->prepare == NULL || writer == NULL ||
            writer->begin == NULL || writer->append == NULL ||
            writer->commit == NULL || writer->abort == NULL ||
            chunk_records == NULL) {
        result->status = PYZ80_DRAW_ATOMIC_INVALID_INPUT;
        return PYZ80_DRAW_ATOMIC_INVALID_INPUT;
    }
    if (!PyZ80DrawAtomic_CertificateValid(certificate, budget) ||
            chunk_record_capacity < certificate->chunk_capacity_records) {
        result->status = PYZ80_DRAW_ATOMIC_CERTIFICATE;
        return PYZ80_DRAW_ATOMIC_CERTIFICATE;
    }
    snapshot_a = 0ul;
    if (replay->prepare(replay->context, 0u, &snapshot_a) == 0u) {
        result->status = PYZ80_DRAW_ATOMIC_PREPARE_A;
        return PYZ80_DRAW_ATOMIC_PREPARE_A;
    }

    pass.certificate = certificate;
    pass.resolve = resolve;
    pass.resolve_context = resolve_context;
    pass.writer = NULL;
    pass.chunk_records = NULL;
    pass.chunk_capacity = certificate->chunk_capacity_records;
    pass.chunk_count = 0u;
    pass.records = 0u;
    pass.append_words = 0u;
    pass.signature_a = 0xA55Au;
    pass.signature_b = 0x5AA5u;
    pass.private_records = 0u;
    pass.private_chunks = 0u;
    pass.failure_index = 0u;
    pass.failure_bank = 0u;
    pass.failure_descriptor = 0u;
    pass.failure = 0u;
    pass.pass = 0u;
    streamed = 0u;
    vm_status = rtype_python_draw_vm_stream(
        input, PyZ80DrawAtomic_Emit, &pass, &streamed);
    result->pass_a_vm_status = (uint8_t)vm_status;
    result->pass_a_records = pass.records;
    if (vm_status != RTYPE_PYTHON_DRAW_VM_OK ||
            streamed != pass.records || pass.failure != 0u) {
        PyZ80DrawAtomic_CopyFailure(&pass, result);
        status = (pass.failure != 0u ?
            (PyZ80DrawAtomicStatus)pass.failure :
            PYZ80_DRAW_ATOMIC_VM_A);
        result->status = (uint8_t)status;
        return status;
    }

    chunk_count = ((uint32_t)pass.records +
        certificate->chunk_capacity_records - 1u) /
        certificate->chunk_capacity_records;
    fragment_words = chunk_count * (
        PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS +
        PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS);
    fragment_words += (uint32_t)pass.records *
        PYZ80_DRAW_ATOMIC_RECORD_DL_WORDS;
    fragment_words += pass.append_words;
    physical_words = chunk_count * (
        PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS +
        PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS);
    physical_words += (uint32_t)pass.records *
        PYZ80_DRAW_ATOMIC_RECORD_PHYSICAL_WORDS;
    total_dl_words = (uint32_t)budget->non_fragment_dl_words + fragment_words;
    result->preflight.record_count = pass.records;
    result->preflight.chunk_count = (uint16_t)chunk_count;
    result->preflight.cmd_append_expanded_words = pass.append_words;
    result->preflight.fragment_expanded_dl_words =
        fragment_words <= 0xFFFFul ? (uint16_t)fragment_words : 0xFFFFu;
    result->preflight.fragment_physical_words =
        physical_words <= 0xFFFFul ? (uint16_t)physical_words : 0xFFFFu;
    result->preflight.total_frame_dl_words =
        total_dl_words <= 0xFFFFul ? (uint16_t)total_dl_words : 0xFFFFu;
    result->preflight.replay_signature_a = pass.signature_a;
    result->preflight.replay_signature_b = pass.signature_b;
    result->preflight.snapshot_token = snapshot_a;
    if (chunk_count > certificate->max_chunks ||
            fragment_words > certificate->max_fragment_expanded_dl_words ||
            fragment_words > 0xFFFFul || physical_words > 0xFFFFul ||
            total_dl_words >= budget->ram_dl_word_limit) {
        result->status = PYZ80_DRAW_ATOMIC_RAM_DL;
        return PYZ80_DRAW_ATOMIC_RAM_DL;
    }
    for (line = 0u; line < PYZ80_DRAW_ATOMIC_RASTER_LINES; ++line) {
        uint32_t cycles = total_dl_words +
            certificate->raster_cycles_by_line[line];
        if (cycles > worst_cycles) {
            worst_cycles = cycles;
            worst_line = line;
        }
        if (cycles > budget->safe_line_cycles) {
            result->status = PYZ80_DRAW_ATOMIC_RASTER;
            return PYZ80_DRAW_ATOMIC_RASTER;
        }
    }
    result->preflight.worst_raster_line = worst_line;
    result->preflight.worst_line_cycles = (uint16_t)worst_cycles;

    snapshot_b = 0ul;
    if (replay->prepare(replay->context, 1u, &snapshot_b) == 0u) {
        writer->abort(writer->context);
        result->status = PYZ80_DRAW_ATOMIC_PREPARE_B;
        return PYZ80_DRAW_ATOMIC_PREPARE_B;
    }
    if (snapshot_b != snapshot_a) {
        writer->abort(writer->context);
        result->status = PYZ80_DRAW_ATOMIC_REPLAY_TOKEN;
        return PYZ80_DRAW_ATOMIC_REPLAY_TOKEN;
    }
    if (writer->begin(writer->context, &result->preflight) == 0u) {
        /* A generic begin callback is allowed to fail after claiming private
         * storage.  Abort is therefore mandatory even though the concrete
         * FT812 begin implementation currently has no post-acquire failure. */
        writer->abort(writer->context);
        result->status = PYZ80_DRAW_ATOMIC_WRITER_BEGIN;
        return PYZ80_DRAW_ATOMIC_WRITER_BEGIN;
    }
    began = 1u;

    pass.certificate = certificate;
    pass.resolve = resolve;
    pass.resolve_context = resolve_context;
    pass.writer = writer;
    pass.chunk_records = chunk_records;
    pass.chunk_capacity = certificate->chunk_capacity_records;
    pass.chunk_count = 0u;
    pass.records = 0u;
    pass.append_words = 0u;
    pass.signature_a = 0xA55Au;
    pass.signature_b = 0x5AA5u;
    pass.private_records = 0u;
    pass.private_chunks = 0u;
    pass.failure_index = 0u;
    pass.failure_bank = 0u;
    pass.failure_descriptor = 0u;
    pass.failure = 0u;
    pass.pass = 1u;
    streamed = 0u;
    vm_status = rtype_python_draw_vm_stream(
        input, PyZ80DrawAtomic_Emit, &pass, &streamed);
    result->pass_b_vm_status = (uint8_t)vm_status;
    result->pass_b_records = pass.records;
    result->private_records_written = pass.private_records;
    result->private_chunks_written = pass.private_chunks;
    if (vm_status != RTYPE_PYTHON_DRAW_VM_OK ||
            streamed != pass.records || pass.failure != 0u) {
        PyZ80DrawAtomic_CopyFailure(&pass, result);
        status = (pass.failure != 0u ?
            (PyZ80DrawAtomicStatus)pass.failure :
            PYZ80_DRAW_ATOMIC_VM_B);
        goto fail_after_begin;
    }
    if (pass.records != result->preflight.record_count ||
            pass.append_words !=
                result->preflight.cmd_append_expanded_words ||
            pass.signature_a != result->preflight.replay_signature_a ||
            pass.signature_b != result->preflight.replay_signature_b) {
        status = PYZ80_DRAW_ATOMIC_REPLAY_MISMATCH;
        goto fail_after_begin;
    }
    if (PyZ80DrawAtomic_FlushChunk(&pass) == 0u) {
        PyZ80DrawAtomic_CopyFailure(&pass, result);
        status = PYZ80_DRAW_ATOMIC_WRITER_APPEND;
        goto fail_after_begin;
    }
    result->private_records_written = pass.private_records;
    result->private_chunks_written = pass.private_chunks;
    if (pass.private_records != result->preflight.record_count ||
            pass.private_chunks != chunk_count) {
        status = PYZ80_DRAW_ATOMIC_REPLAY_MISMATCH;
        goto fail_after_begin;
    }
    if (writer->commit(writer->context, &result->preflight) == 0u) {
        status = PYZ80_DRAW_ATOMIC_WRITER_COMMIT;
        goto fail_after_begin;
    }
    result->committed = 1u;
    result->status = PYZ80_DRAW_ATOMIC_OK;
    return PYZ80_DRAW_ATOMIC_OK;

fail_after_begin:
    if (began != 0u) {
        writer->abort(writer->context);
    }
    result->status = (uint8_t)status;
    return status;
}

static uint8_t PyZ80DrawAtomic_ResolveTemplate(
        uint16_t template_index, int16_t anchor_x, int16_t anchor_y,
        PyZ80FtLoweredCoord *lowered_x,
        PyZ80FtLoweredCoord *lowered_y,
        uint32_t *address_out, uint16_t *byte_size_out)
{
    const PyZ80FtHQTemplate *template;
    int32_t native_x;
    int32_t native_y;
    uint32_t map_index;
    uint8_t blob_index;
    uint16_t byte_size;
    uint32_t address;
    if (template_index >= PYZ80_FT_HQ_TEMPLATE_COUNT ||
            lowered_x == NULL || lowered_y == NULL ||
            address_out == NULL || byte_size_out == NULL) {
        return 0u;
    }
    template = &PyZ80FT_HQTemplates[template_index];
    native_x = (int32_t)anchor_x + (int32_t)template->dx - 320l;
    native_y = 384l - (int32_t)anchor_y - (int32_t)template->dy -
        (int32_t)template->height * 16l;
    if (native_x < PYZ80_FT_NATIVE_X_MIN ||
            native_x > PYZ80_FT_NATIVE_X_MAX ||
            native_y < PYZ80_FT_NATIVE_Y_MIN ||
            native_y > PYZ80_FT_NATIVE_Y_MAX ||
            PyZ80FT_LowerNativeX((int16_t)native_x, lowered_x) == 0u ||
            PyZ80FT_LowerNativeY((int16_t)native_y, lowered_y) == 0u) {
        return 0u;
    }
    map_index = (uint32_t)template_index * 25ul;
    map_index += (uint32_t)lowered_x->phase * 5ul + lowered_y->phase;
    if (map_index >= PYZ80_FT_HQ_APPEND_ENTRY_COUNT) {
        return 0u;
    }
    blob_index = PyZ80FT_HQAppendMap[map_index];
    if (blob_index >= PYZ80_FT_HQ_APPEND_BLOB_COUNT) {
        return 0u;
    }
    address = PyZ80FT_HQAppendAddress[blob_index];
    byte_size = PyZ80FT_HQAppendSize[blob_index];
    if (byte_size == 0u || (byte_size & 3u) != 0u ||
            address > 0x00100000ul - (uint32_t)byte_size) {
        return 0u;
    }
    *address_out = address;
    *byte_size_out = byte_size;
    return 1u;
}

uint8_t PyZ80DrawAtomic_ResolveGeneratedHQT3(
        void *context, const rtype_python_draw_vm_record *record,
        PyZ80DrawAtomicResolvedRecord *resolved_out)
{
    uint16_t template_index;
    PyZ80FtLoweredCoord lowered_x;
    PyZ80FtLoweredCoord lowered_y;
    uint32_t address;
    uint16_t byte_size;
    (void)context;
    if (record == NULL || resolved_out == NULL) {
        return 0u;
    }
    template_index = PyZ80FT_FindHQTemplate(
        record->bank_key, record->descriptor);
    if (template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND ||
            PyZ80DrawAtomic_ResolveTemplate(
                template_index, record->anchor_x, record->anchor_y,
                &lowered_x, &lowered_y, &address, &byte_size) == 0u) {
        return 0u;
    }
    resolved_out->template_index = template_index;
    resolved_out->append_expanded_words = (uint16_t)(byte_size >> 2);
    return 1u;
}

uint8_t PyZ80DrawAtomicFT812_Begin(
        void *context, const PyZ80DrawAtomicPreflight *preflight)
{
    PyZ80DrawAtomicFT812WriterContext *target =
        (PyZ80DrawAtomicFT812WriterContext *)context;
    if (target == NULL || target->queue == NULL || preflight == NULL ||
            target->begun != 0u ||
            preflight->fragment_physical_words > PYZ80_FT_QUEUE_CAPACITY ||
            preflight->fragment_expanded_dl_words >
                PYZ80_FT_RAM_DL_WORD_LIMIT ||
            PyZ80FT_QueueAcquireFragment(
                target->queue, target->frame_sequence) == 0u) {
        return 0u;
    }
    target->expected_physical_words = preflight->fragment_physical_words;
    target->expected_dl_words = preflight->fragment_expanded_dl_words;
    target->write_index = 0u;
    target->dl_words = 0u;
    target->records_written = 0u;
    target->chunks_written = 0u;
    target->begun = 1u;
    return 1u;
}

uint8_t PyZ80DrawAtomicFT812_Append(
        void *context, const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first_record_index)
{
    PyZ80DrawAtomicFT812WriterContext *target =
        (PyZ80DrawAtomicFT812WriterContext *)context;
    uint16_t index;
    uint16_t output;
    uint16_t dl_words;
    uint16_t needed_physical;
    if (target == NULL || target->queue == NULL || records == NULL ||
            target->begun != 1u || count == 0u ||
            count > PYZ80_DRAW_ATOMIC_MAX_CHUNK_RECORDS ||
            first_record_index != target->records_written) {
        return 0u;
    }
    needed_physical = (uint16_t)(
        PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS +
        PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS +
        count * PYZ80_DRAW_ATOMIC_RECORD_PHYSICAL_WORDS);
    if (needed_physical > target->expected_physical_words ||
            target->write_index >
            (uint16_t)(target->expected_physical_words - needed_physical)) {
        return 0u;
    }
    output = target->write_index;
    dl_words = target->dl_words;
    for (index = 0u; index < PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS; ++index) {
        target->queue->words[output++] = PyZ80DrawAtomic_BatchPrefix[index];
    }
    dl_words = (uint16_t)(
        dl_words + PYZ80_DRAW_ATOMIC_CHUNK_PREFIX_WORDS);
    for (index = 0u; index < count; ++index) {
        PyZ80FtLoweredCoord lowered_x;
        PyZ80FtLoweredCoord lowered_y;
        uint32_t address;
        uint16_t byte_size;
        if (PyZ80DrawAtomic_ResolveTemplate(
                records[index].template_index,
                records[index].anchor_x, records[index].anchor_y,
                &lowered_x, &lowered_y, &address, &byte_size) == 0u) {
            return 0u;
        }
        {
            uint16_t record_dl_words = (uint16_t)(
                2u + (byte_size >> 2));
            if (record_dl_words > target->expected_dl_words ||
                    dl_words > (uint16_t)(
                        target->expected_dl_words - record_dl_words)) {
                return 0u;
            }
        }
        target->queue->words[output++] =
            PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_X |
            (((uint32_t)(uint16_t)lowered_x.vertex << 1) & 0x0001FFFFul);
        target->queue->words[output++] =
            PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_Y |
            (((uint32_t)(uint16_t)lowered_y.vertex << 1) & 0x0001FFFFul);
        target->queue->words[output++] = PYZ80_DRAW_ATOMIC_CMD_APPEND;
        target->queue->words[output++] = address;
        target->queue->words[output++] = byte_size;
        dl_words = (uint16_t)(dl_words + 2u + (byte_size >> 2));
    }
    target->queue->words[output++] =
        PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_X;
    target->queue->words[output++] =
        PYZ80_DRAW_ATOMIC_DL_VERTEX_TRANSLATE_Y;
    target->queue->words[output++] = PYZ80_DRAW_ATOMIC_DL_END;
    dl_words = (uint16_t)(
        dl_words + PYZ80_DRAW_ATOMIC_CHUNK_SUFFIX_WORDS);
    target->write_index = output;
    target->dl_words = dl_words;
    target->records_written = (uint16_t)(
        target->records_written + count);
    target->chunks_written++;
    return 1u;
}

uint8_t PyZ80DrawAtomicFT812_Commit(
        void *context, const PyZ80DrawAtomicPreflight *preflight)
{
    PyZ80DrawAtomicFT812WriterContext *target =
        (PyZ80DrawAtomicFT812WriterContext *)context;
    if (target == NULL || target->queue == NULL || preflight == NULL ||
            target->begun != 1u ||
            target->queue->header.state != PYZ80_FT_QUEUE_BUILDING ||
            target->queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT ||
            target->queue->header.count != 0u ||
            target->queue->header.payload_bytes != 0u ||
            target->queue->header.dl_words != 0u ||
            target->write_index != target->expected_physical_words ||
            target->dl_words != target->expected_dl_words ||
            target->records_written != preflight->record_count ||
            target->chunks_written != preflight->chunk_count) {
        return 0u;
    }
    /* Lengths become meaningful only inside this final commit; READY is the
     * single publication store observed by the consumer. */
    target->queue->header.count = target->write_index;
    target->queue->header.payload_bytes = (uint16_t)(
        target->write_index * sizeof(uint32_t));
    target->queue->header.dl_words = target->dl_words;
    target->begun = 0u;
    target->queue->header.state = PYZ80_FT_QUEUE_READY;
    return 1u;
}

void PyZ80DrawAtomicFT812_Abort(void *context)
{
    PyZ80DrawAtomicFT812WriterContext *target =
        (PyZ80DrawAtomicFT812WriterContext *)context;
    if (target == NULL || target->queue == NULL) {
        return;
    }
    if (target->queue->header.state == PYZ80_FT_QUEUE_BUILDING) {
        target->queue->header.count = 0u;
        target->queue->header.payload_bytes = 0u;
        target->queue->header.dl_words = 0u;
        target->queue->header.overflow = 0u;
        target->queue->header.state = PYZ80_FT_QUEUE_FREE;
    }
    target->write_index = 0u;
    target->dl_words = 0u;
    target->records_written = 0u;
    target->chunks_written = 0u;
    target->begun = 0u;
}
