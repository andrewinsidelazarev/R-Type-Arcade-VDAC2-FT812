#include "pyz80_draw_private_tape_v2.h"

#include <stddef.h>

#include "rtype_python_hq_templates.h"

#define PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_X 0x2B000000ul
#define PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_Y 0x2C000000ul
#define PYZ80_DRAW_TAPE_V2_DL_END 0x21000000ul
#define PYZ80_DRAW_TAPE_V2_CMD_APPEND 0xFFFFFF1Eul

static const uint32_t PyZ80DrawTapeV2_BatchPrefix[
        PYZ80_DRAW_TAPE_V2_PREFIX_WORDS] = {
    0x04FFFFFFul, 0x150000A0ul, 0x16000000ul, 0x17000000ul,
    0x18000000ul, 0x190000A0ul, 0x1A000000ul, 0x08005830ul,
    0x27000003ul, 0x1F000001ul
};

typedef char PyZ80DrawTapeV2_RecordSize[
    sizeof(PyZ80DrawTapeV2Record) == 8 ? 1 : -1];
typedef char PyZ80DrawTapeV2_MaxBytes[
    PYZ80_DRAW_TAPE_V2_MAX_BYTES == 1824u ? 1 : -1];
typedef char PyZ80DrawTapeV2_CatalogEntrySize[
    sizeof(PyZ80DrawTapeV2CatalogEntry) == 6 ? 1 : -1];

typedef struct PyZ80DrawTapeV2EvalState {
    const PyZ80DrawTapeV2Certificate *certificate;
    PyZ80DrawTapeV2Resolve resolve;
    void *resolve_context;
    volatile PyZ80DrawTapeV2Record *tape;
    uint16_t tape_capacity;
    uint16_t records;
    uint16_t append_words;
    uint16_t failure_index;
    uint16_t failure_bank;
    uint16_t failure_descriptor;
    uint8_t failure;
} PyZ80DrawTapeV2EvalState;

static void PyZ80DrawTapeV2_ZeroResult(PyZ80DrawTapeV2Result *result)
{
    uint8_t *target = (uint8_t *)result;
    uint16_t count = (uint16_t)sizeof(*result);
    while (count != 0u) {
        *target++ = 0u;
        --count;
    }
}

static void PyZ80DrawTapeV2_Fail(
        PyZ80DrawTapeV2EvalState *state, uint8_t failure,
        const rtype_python_draw_vm_record *record)
{
    if (state->failure != 0u) {
        return;
    }
    state->failure = failure;
    state->failure_index = state->records;
    if (record != NULL) {
        state->failure_bank = record->bank_key;
        state->failure_descriptor = record->descriptor;
    }
}

static uint8_t PyZ80DrawTapeV2_Emit(
        void *context, const rtype_python_draw_vm_record *record)
{
    PyZ80DrawTapeV2EvalState *state =
        (PyZ80DrawTapeV2EvalState *)context;
    PyZ80DrawTapeV2Resolution resolved;
    volatile PyZ80DrawTapeV2Record *target;
    uint16_t next_append;
    if (state == NULL || record == NULL || state->failure != 0u ||
            state->certificate == NULL || state->resolve == NULL ||
            state->tape == NULL) {
        if (state != NULL) {
            PyZ80DrawTapeV2_Fail(
                state, PYZ80_DRAW_TAPE_V2_INVALID_INPUT, record);
        }
        return 0u;
    }
    if (state->records >= state->certificate->certified_max_records ||
            state->records >= state->tape_capacity) {
        PyZ80DrawTapeV2_Fail(
            state, PYZ80_DRAW_TAPE_V2_RECORD_BOUND, record);
        return 0u;
    }
    resolved.template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    resolved.append_expanded_words = 0u;
    if (state->resolve(state->resolve_context, record, &resolved) == 0u ||
            resolved.template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND ||
            resolved.append_expanded_words == 0u) {
        PyZ80DrawTapeV2_Fail(
            state, PYZ80_DRAW_TAPE_V2_LOOKUP, record);
        return 0u;
    }
    if (state->append_words >
            (uint16_t)(0xFFFFu - resolved.append_expanded_words)) {
        PyZ80DrawTapeV2_Fail(
            state, PYZ80_DRAW_TAPE_V2_APPEND_BOUND, record);
        return 0u;
    }
    next_append = (uint16_t)(
        state->append_words + resolved.append_expanded_words);
    if (next_append >
            state->certificate->max_cmd_append_expanded_words) {
        PyZ80DrawTapeV2_Fail(
            state, PYZ80_DRAW_TAPE_V2_APPEND_BOUND, record);
        return 0u;
    }
    target = &state->tape[state->records];
    target->template_index = resolved.template_index;
    target->anchor_x = record->anchor_x;
    target->anchor_y = record->anchor_y;
    target->append_expanded_words = resolved.append_expanded_words;
    state->append_words = next_append;
    state->records++;
    return 1u;
}

uint8_t PyZ80DrawTapeV2_FindCatalogBounded(
        PyZ80DrawTapeV2CatalogRead read_entry, void *context,
        uint16_t entry_count, uint16_t bank_key, uint16_t descriptor,
        uint16_t *template_index_out, uint8_t *comparisons_out)
{
    uint16_t low = 0u;
    uint16_t high = entry_count;
    uint8_t comparisons = 0u;
    PyZ80DrawTapeV2CatalogEntry entry;
    if (read_entry == NULL || template_index_out == NULL ||
            comparisons_out == NULL || entry_count == 0u ||
            entry_count > PYZ80_DRAW_TAPE_V2_CATALOG_KEYS) {
        return 0u;
    }
    *template_index_out = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    *comparisons_out = 0u;
    while (low < high &&
            comparisons < PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS) {
        uint16_t middle = (uint16_t)(low + ((high - low) >> 1));
        if (read_entry(context, middle, &entry) == 0u) {
            *comparisons_out = comparisons;
            return 0u;
        }
        comparisons++;
        if (entry.bank_key == bank_key && entry.descriptor == descriptor) {
            if (entry.template_index == PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) {
                *comparisons_out = comparisons;
                return 0u;
            }
            *template_index_out = entry.template_index;
            *comparisons_out = comparisons;
            return 1u;
        }
        if (entry.bank_key < bank_key ||
                (entry.bank_key == bank_key &&
                 entry.descriptor < descriptor)) {
            low = (uint16_t)(middle + 1u);
        } else {
            high = middle;
        }
    }
    *comparisons_out = comparisons;
    return 0u;
}

static uint16_t PyZ80DrawTapeV2_CuckooHash1(
        uint16_t bank_key, uint16_t descriptor)
{
    uint16_t bank_mix = (uint16_t)(
        bank_key + (uint16_t)(bank_key << 8));
    return (uint16_t)((descriptor ^ (descriptor >> 7) ^ bank_mix ^
        PYZ80_DRAW_TAPE_V2_CUCKOO_SEED1) &
        PYZ80_DRAW_TAPE_V2_CUCKOO_MASK);
}

static uint16_t PyZ80DrawTapeV2_CuckooHash2(
        uint16_t bank_key, uint16_t descriptor)
{
    uint16_t rotated = (uint16_t)(
        (uint16_t)(descriptor << 5) | (descriptor >> 11));
    uint16_t bank_mix = (uint16_t)(
        bank_key + (uint16_t)(bank_key << 4));
    return (uint16_t)((rotated ^ bank_mix ^
        PYZ80_DRAW_TAPE_V2_CUCKOO_SEED2) &
        PYZ80_DRAW_TAPE_V2_CUCKOO_MASK);
}

uint8_t PyZ80DrawTapeV2_FindCatalogCuckoo(
        PyZ80DrawTapeV2CatalogRead read_slot, void *context,
        uint16_t bank_key, uint16_t descriptor,
        uint16_t *template_index_out, uint8_t *reads_out)
{
    PyZ80DrawTapeV2CatalogEntry entry;
    uint16_t slot1;
    uint16_t slot2;
    if (read_slot == NULL || template_index_out == NULL ||
            reads_out == NULL) {
        return 0u;
    }
    *template_index_out = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    *reads_out = 0u;
    slot1 = PyZ80DrawTapeV2_CuckooHash1(bank_key, descriptor);
    if (read_slot(context, slot1, &entry) == 0u) {
        return 0u;
    }
    *reads_out = 1u;
    if (entry.bank_key == bank_key && entry.descriptor == descriptor &&
            entry.template_index != PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) {
        *template_index_out = entry.template_index;
        return 1u;
    }
    slot2 = PyZ80DrawTapeV2_CuckooHash2(bank_key, descriptor);
    if (slot2 == slot1 || read_slot(context, slot2, &entry) == 0u) {
        return 0u;
    }
    *reads_out = 2u;
    if (entry.bank_key == bank_key && entry.descriptor == descriptor &&
            entry.template_index != PYZ80_FT_HQ_TEMPLATE_NOT_FOUND) {
        *template_index_out = entry.template_index;
        return 1u;
    }
    return 0u;
}

static uint8_t PyZ80DrawTapeV2_CertificateValid(
        const PyZ80DrawTapeV2Certificate *certificate,
        const PyZ80DrawTapeV2FrameBudget *budget)
{
    uint16_t fixed_words;
    uint16_t expected_words;
    uint16_t total_words;
    if (certificate == NULL || budget == NULL ||
            certificate->format_version !=
                PYZ80_DRAW_TAPE_V2_CERTIFICATE_VERSION ||
            certificate->sizing_proof_complete != 1u ||
            certificate->catalog_order_unique_proved != 1u ||
            certificate->catalog_cuckoo_layout_proved != 1u ||
            certificate->raster_768_lines_proved != 1u ||
            certificate->catalog_key_count !=
                PYZ80_DRAW_TAPE_V2_CATALOG_KEYS ||
            certificate->catalog_max_comparisons !=
                PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS ||
            certificate->catalog_max_runtime_reads !=
                PYZ80_DRAW_TAPE_V2_CUCKOO_MAX_READS ||
            certificate->certified_max_records !=
                PYZ80_DRAW_TAPE_V2_MAX_RECORDS ||
            certificate->worst_raster_line >= 768u ||
            budget->ram_dl_word_limit != PYZ80_FT_RAM_DL_WORD_LIMIT ||
            budget->safe_line_cycles !=
                PYZ80_DRAW_TAPE_V2_SAFE_LINE_CYCLES ||
            budget->non_fragment_dl_words >= budget->ram_dl_word_limit) {
        return 0u;
    }
    fixed_words = (uint16_t)(
        PYZ80_DRAW_TAPE_V2_MAX_CHUNKS *
            (PYZ80_DRAW_TAPE_V2_PREFIX_WORDS +
             PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS) +
        PYZ80_DRAW_TAPE_V2_MAX_RECORDS *
            PYZ80_DRAW_TAPE_V2_RECORD_DL_WORDS);
    if (certificate->max_cmd_append_expanded_words >
            (uint16_t)(0xFFFFu - fixed_words)) {
        return 0u;
    }
    expected_words = (uint16_t)(fixed_words +
        certificate->max_cmd_append_expanded_words);
    if (expected_words != certificate->max_fragment_expanded_dl_words ||
            expected_words >= budget->ram_dl_word_limit ||
            budget->non_fragment_dl_words >
                (uint16_t)(budget->ram_dl_word_limit - expected_words - 1u)) {
        return 0u;
    }
    total_words = (uint16_t)(
        budget->non_fragment_dl_words + expected_words);
    if (total_words > budget->safe_line_cycles ||
            certificate->worst_raster_cycles >
            (uint16_t)(budget->safe_line_cycles - total_words)) {
        return 0u;
    }
    return 1u;
}

PyZ80DrawTapeV2Status PyZ80DrawTapeV2_Run(
        const rtype_python_draw_vm_input *input,
        const PyZ80DrawTapeV2Certificate *certificate,
        const PyZ80DrawTapeV2FrameBudget *budget,
        PyZ80DrawTapeV2Resolve resolve, void *resolve_context,
        volatile PyZ80DrawTapeV2Record *private_tape,
        uint16_t private_tape_capacity,
        const PyZ80DrawTapeV2Writer *writer,
        PyZ80DrawTapeV2Result *result)
{
    PyZ80DrawTapeV2EvalState state;
    rtype_python_draw_vm_status vm_status;
    uint16_t streamed;
    uint16_t chunks;
    uint16_t fragment_words;
    uint16_t physical_words;
    uint16_t total_words;
    uint16_t first;
    PyZ80DrawTapeV2Status status;
    if (result == NULL) {
        return PYZ80_DRAW_TAPE_V2_INVALID_INPUT;
    }
    PyZ80DrawTapeV2_ZeroResult(result);
    if (input == NULL || resolve == NULL || private_tape == NULL ||
            writer == NULL || writer->begin == NULL ||
            writer->append == NULL || writer->commit == NULL ||
            writer->abort == NULL) {
        result->status = PYZ80_DRAW_TAPE_V2_INVALID_INPUT;
        return PYZ80_DRAW_TAPE_V2_INVALID_INPUT;
    }
    if (!PyZ80DrawTapeV2_CertificateValid(certificate, budget) ||
            private_tape_capacity < certificate->certified_max_records) {
        result->status = PYZ80_DRAW_TAPE_V2_CERTIFICATE;
        return PYZ80_DRAW_TAPE_V2_CERTIFICATE;
    }

    state.certificate = certificate;
    state.resolve = resolve;
    state.resolve_context = resolve_context;
    state.tape = private_tape;
    state.tape_capacity = private_tape_capacity;
    state.records = 0u;
    state.append_words = 0u;
    state.failure_index = 0u;
    state.failure_bank = 0u;
    state.failure_descriptor = 0u;
    state.failure = 0u;
    streamed = 0u;
    vm_status = rtype_python_draw_vm_stream(
        input, PyZ80DrawTapeV2_Emit, &state, &streamed);
    result->vm_status = (uint8_t)vm_status;
    result->evaluated_records = state.records;
    if (vm_status != RTYPE_PYTHON_DRAW_VM_OK ||
            streamed != state.records || state.failure != 0u) {
        result->failure_record_index = state.failure_index;
        result->failure_bank_key = state.failure_bank;
        result->failure_descriptor = state.failure_descriptor;
        status = state.failure != 0u ?
            (PyZ80DrawTapeV2Status)state.failure : PYZ80_DRAW_TAPE_V2_VM;
        result->status = (uint8_t)status;
        return status;
    }

    chunks = state.records == 0u ? 0u :
        (uint16_t)(((state.records - 1u) >> 7) + 1u);
    fragment_words = (uint16_t)(
        chunks * (PYZ80_DRAW_TAPE_V2_PREFIX_WORDS +
                  PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS) +
        state.records * PYZ80_DRAW_TAPE_V2_RECORD_DL_WORDS +
        state.append_words);
    physical_words = (uint16_t)(
        chunks * (PYZ80_DRAW_TAPE_V2_PREFIX_WORDS +
                  PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS) +
        state.records * PYZ80_DRAW_TAPE_V2_RECORD_PHYSICAL_WORDS);
    total_words = (uint16_t)(budget->non_fragment_dl_words + fragment_words);
    result->preflight.record_count = state.records;
    result->preflight.chunk_count = chunks;
    result->preflight.cmd_append_expanded_words = state.append_words;
    result->preflight.fragment_expanded_dl_words = fragment_words;
    result->preflight.fragment_physical_words = physical_words;
    result->preflight.total_frame_dl_words = total_words;
    result->preflight.worst_raster_line = certificate->worst_raster_line;
    result->preflight.worst_line_cycles = (uint16_t)(
        total_words + certificate->worst_raster_cycles);
    if (chunks > PYZ80_DRAW_TAPE_V2_MAX_CHUNKS ||
            fragment_words > certificate->max_fragment_expanded_dl_words ||
            total_words >= budget->ram_dl_word_limit) {
        result->status = PYZ80_DRAW_TAPE_V2_RAM_DL;
        return PYZ80_DRAW_TAPE_V2_RAM_DL;
    }
    if (result->preflight.worst_line_cycles > budget->safe_line_cycles) {
        result->status = PYZ80_DRAW_TAPE_V2_RASTER;
        return PYZ80_DRAW_TAPE_V2_RASTER;
    }

    if (writer->begin(writer->context, &result->preflight) == 0u) {
        writer->abort(writer->context);
        result->status = PYZ80_DRAW_TAPE_V2_WRITER_BEGIN;
        return PYZ80_DRAW_TAPE_V2_WRITER_BEGIN;
    }
    first = 0u;
    while (first < state.records) {
        uint16_t remaining = (uint16_t)(state.records - first);
        uint16_t count = remaining > PYZ80_DRAW_TAPE_V2_CHUNK_RECORDS ?
            PYZ80_DRAW_TAPE_V2_CHUNK_RECORDS : remaining;
        if (writer->append(
                writer->context, &private_tape[first], count, first) == 0u) {
            status = PYZ80_DRAW_TAPE_V2_WRITER_APPEND;
            goto fail_after_begin;
        }
        first = (uint16_t)(first + count);
        result->private_records_written = first;
        result->private_chunks_written++;
    }
    if (result->private_records_written != state.records ||
            result->private_chunks_written != chunks) {
        status = PYZ80_DRAW_TAPE_V2_WRITER_APPEND;
        goto fail_after_begin;
    }
    if (writer->commit(writer->context, &result->preflight) == 0u) {
        status = PYZ80_DRAW_TAPE_V2_WRITER_COMMIT;
        goto fail_after_begin;
    }
    result->committed = 1u;
    result->status = PYZ80_DRAW_TAPE_V2_OK;
    return PYZ80_DRAW_TAPE_V2_OK;

fail_after_begin:
    writer->abort(writer->context);
    result->status = (uint8_t)status;
    return status;
}

static uint8_t PyZ80DrawTapeV2_ResolvePhysical(
        const volatile PyZ80DrawTapeV2Record *record,
        PyZ80FtLoweredCoord *lowered_x, PyZ80FtLoweredCoord *lowered_y,
        uint32_t *address_out, uint16_t *byte_size_out)
{
    const PyZ80FtHQTemplate *template;
    int32_t native_x;
    int32_t native_y;
    uint32_t map_index;
    uint16_t blob_index;
    uint16_t byte_size;
    uint32_t address;
    if (record == NULL ||
            record->template_index >= PYZ80_FT_HQ_TEMPLATE_COUNT ||
            lowered_x == NULL || lowered_y == NULL ||
            address_out == NULL || byte_size_out == NULL) {
        return 0u;
    }
    template = &PyZ80FT_HQTemplates[record->template_index];
    native_x = (int32_t)record->anchor_x + (int32_t)template->dx - 320l;
    native_y = 384l - (int32_t)record->anchor_y - (int32_t)template->dy -
        (int32_t)template->height * 16l;
    if (native_x < PYZ80_FT_NATIVE_X_MIN ||
            native_x > PYZ80_FT_NATIVE_X_MAX ||
            native_y < PYZ80_FT_NATIVE_Y_MIN ||
            native_y > PYZ80_FT_NATIVE_Y_MAX ||
            PyZ80FT_LowerNativeX((int16_t)native_x, lowered_x) == 0u ||
            PyZ80FT_LowerNativeY((int16_t)native_y, lowered_y) == 0u) {
        return 0u;
    }
    map_index = (uint32_t)record->template_index * 25ul;
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
            record->append_expanded_words != (uint16_t)(byte_size >> 2) ||
            address > 0x00100000ul - (uint32_t)byte_size) {
        return 0u;
    }
    *address_out = address;
    *byte_size_out = byte_size;
    return 1u;
}

uint8_t PyZ80DrawTapeV2FT812_Begin(
        void *context, const PyZ80DrawTapeV2Preflight *preflight)
{
    PyZ80DrawTapeV2FT812WriterContext *target =
        (PyZ80DrawTapeV2FT812WriterContext *)context;
    if (target == NULL || target->queue == NULL || preflight == NULL ||
            target->begun != 0u ||
            preflight->fragment_physical_words > PYZ80_FT_QUEUE_CAPACITY ||
            preflight->fragment_expanded_dl_words >=
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

uint8_t PyZ80DrawTapeV2FT812_Append(
        void *context, const volatile PyZ80DrawTapeV2Record *records,
        uint16_t count, uint16_t first_record_index)
{
    PyZ80DrawTapeV2FT812WriterContext *target =
        (PyZ80DrawTapeV2FT812WriterContext *)context;
    uint16_t index;
    uint16_t output;
    uint16_t dl_words;
    uint16_t needed;
    if (target == NULL || target->queue == NULL || records == NULL ||
            target->begun != 1u || count == 0u ||
            count > PYZ80_DRAW_TAPE_V2_CHUNK_RECORDS ||
            first_record_index != target->records_written ||
            target->queue->header.state != PYZ80_FT_QUEUE_BUILDING ||
            target->queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT ||
            target->queue->header.count != 0u ||
            target->queue->header.payload_bytes != 0u ||
            target->queue->header.dl_words != 0u) {
        return 0u;
    }
    needed = (uint16_t)(
        PYZ80_DRAW_TAPE_V2_PREFIX_WORDS +
        PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS +
        count * PYZ80_DRAW_TAPE_V2_RECORD_PHYSICAL_WORDS);
    if (needed > target->expected_physical_words ||
            target->write_index >
                (uint16_t)(target->expected_physical_words - needed)) {
        return 0u;
    }
    output = target->write_index;
    dl_words = target->dl_words;
    for (index = 0u; index < PYZ80_DRAW_TAPE_V2_PREFIX_WORDS; ++index) {
        target->queue->words[output++] = PyZ80DrawTapeV2_BatchPrefix[index];
    }
    dl_words = (uint16_t)(dl_words + PYZ80_DRAW_TAPE_V2_PREFIX_WORDS);
    for (index = 0u; index < count; ++index) {
        PyZ80FtLoweredCoord lowered_x;
        PyZ80FtLoweredCoord lowered_y;
        uint32_t address;
        uint16_t byte_size;
        uint16_t record_dl_words;
        if (PyZ80DrawTapeV2_ResolvePhysical(
                &records[index], &lowered_x, &lowered_y,
                &address, &byte_size) == 0u) {
            return 0u;
        }
        record_dl_words = (uint16_t)(2u + (byte_size >> 2));
        if (record_dl_words > target->expected_dl_words ||
                dl_words > (uint16_t)(
                    target->expected_dl_words - record_dl_words)) {
            return 0u;
        }
        target->queue->words[output++] =
            PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_X |
            (((uint32_t)(uint16_t)lowered_x.vertex << 1) & 0x0001FFFFul);
        target->queue->words[output++] =
            PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_Y |
            (((uint32_t)(uint16_t)lowered_y.vertex << 1) & 0x0001FFFFul);
        target->queue->words[output++] = PYZ80_DRAW_TAPE_V2_CMD_APPEND;
        target->queue->words[output++] = address;
        target->queue->words[output++] = byte_size;
        dl_words = (uint16_t)(dl_words + record_dl_words);
    }
    target->queue->words[output++] = PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_X;
    target->queue->words[output++] = PYZ80_DRAW_TAPE_V2_DL_VERTEX_TRANSLATE_Y;
    target->queue->words[output++] = PYZ80_DRAW_TAPE_V2_DL_END;
    dl_words = (uint16_t)(dl_words + PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS);
    target->write_index = output;
    target->dl_words = dl_words;
    target->records_written = (uint16_t)(target->records_written + count);
    target->chunks_written++;
    return 1u;
}

uint8_t PyZ80DrawTapeV2FT812_Commit(
        void *context, const PyZ80DrawTapeV2Preflight *preflight)
{
    PyZ80DrawTapeV2FT812WriterContext *target =
        (PyZ80DrawTapeV2FT812WriterContext *)context;
    if (target == NULL || target->queue == NULL || preflight == NULL ||
            target->begun != 1u ||
            target->queue->header.state != PYZ80_FT_QUEUE_BUILDING ||
            target->queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT ||
            target->queue->header.count != 0u ||
            target->queue->header.payload_bytes != 0u ||
            target->queue->header.dl_words != 0u ||
            target->expected_physical_words !=
                preflight->fragment_physical_words ||
            target->expected_dl_words !=
                preflight->fragment_expanded_dl_words ||
            target->write_index != target->expected_physical_words ||
            target->dl_words != target->expected_dl_words ||
            target->records_written != preflight->record_count ||
            target->chunks_written != preflight->chunk_count) {
        return 0u;
    }
    target->queue->header.count = target->write_index;
    target->queue->header.payload_bytes = (uint16_t)(
        target->write_index * sizeof(uint32_t));
    target->queue->header.dl_words = target->dl_words;
    target->begun = 0u;
    target->queue->header.state = PYZ80_FT_QUEUE_READY;
    return 1u;
}

void PyZ80DrawTapeV2FT812_Abort(void *context)
{
    PyZ80DrawTapeV2FT812WriterContext *target =
        (PyZ80DrawTapeV2FT812WriterContext *)context;
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
