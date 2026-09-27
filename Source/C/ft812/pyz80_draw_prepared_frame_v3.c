#include "pyz80_draw_prepared_frame_v3.h"

#include <stddef.h>

#define PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_X 0x2B000000ul
#define PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_Y 0x2C000000ul
#define PYZ80_DRAW_PREPARED_V3_DL_END 0x21000000ul
#define PYZ80_DRAW_PREPARED_V3_CMD_APPEND 0xFFFFFF1Eul

static const uint32_t PyZ80DrawPreparedV3_BatchPrefix[
        PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS] = {
    0x04FFFFFFul, 0x150000A0ul, 0x16000000ul, 0x17000000ul,
    0x18000000ul, 0x190000A0ul, 0x1A000000ul, 0x08005830ul,
    0x27000003ul, 0x1F000001ul
};

static uint32_t PyZ80DrawPreparedV3_AppendAddress(
        const volatile PyZ80DrawPreparedV3AppendEntry *append)
{
    return (uint32_t)append->ram_g_address_lo |
        ((uint32_t)append->ram_g_address_hi << 16);
}

typedef char PyZ80DrawPreparedV3_RecordSize[
    sizeof(PyZ80DrawPreparedV3Record) == 6 ? 1 : -1];
typedef char PyZ80DrawPreparedV3_MaxBytes[
    PYZ80_DRAW_PREPARED_V3_MAX_BYTES == 1368u ? 1 : -1];
typedef char PyZ80DrawPreparedV3_AppendEntrySize[
    sizeof(PyZ80DrawPreparedV3AppendEntry) == 6 ? 1 : -1];
typedef char PyZ80DrawPreparedV3_SourceRecordSize[
    sizeof(PyZ80DrawPreparedV3SourceRecord) == 8 ? 1 : -1];
typedef char PyZ80DrawPreparedV3_CacheSize[
    sizeof(PyZ80DrawPreparedV3IdentityCache) == 10 ? 1 : -1];
#if defined(__SDCC)
typedef char PyZ80DrawPreparedV3_FastParamsSize[
    sizeof(PyZ80DrawPreparedV3FastParams) == 23 ? 1 : -1];
typedef char PyZ80DrawPreparedV3_FastQueueParamsSize[
    sizeof(PyZ80DrawPreparedV3FastQueueParams) == 12 ? 1 : -1];
#endif

static void PyZ80DrawPreparedV3_ZeroResult(
        PyZ80DrawPreparedV3Result *result)
{
    uint8_t *target = (uint8_t *)result;
    uint16_t count = (uint16_t)sizeof(*result);
    while (count != 0u) {
        *target++ = 0u;
        --count;
    }
}

static uint8_t PyZ80DrawPreparedV3_CertificateValid(
        const PyZ80DrawPreparedV3Certificate *certificate,
        const PyZ80DrawPreparedV3FrameBudget *budget)
{
    uint16_t fixed_words;
    uint16_t expected_words;
    uint16_t total_words;
    if (certificate == NULL || budget == NULL ||
            certificate->format_version !=
                PYZ80_DRAW_PREPARED_V3_CERTIFICATE_VERSION ||
            certificate->sizing_proof_complete != 1u ||
            certificate->identity_cache_mutation_proved != 1u ||
            certificate->private_render_order_producer_proved != 1u ||
            certificate->append_directory_proved != 1u ||
            certificate->raster_768_lines_proved != 1u ||
            certificate->certified_max_records !=
                PYZ80_DRAW_PREPARED_V3_MAX_RECORDS ||
            certificate->worst_raster_line >= 768u ||
            budget->ram_dl_word_limit != PYZ80_FT_RAM_DL_WORD_LIMIT ||
            budget->safe_line_cycles !=
                PYZ80_DRAW_PREPARED_V3_SAFE_LINE_CYCLES ||
            budget->non_fragment_dl_words >= budget->ram_dl_word_limit) {
        return 0u;
    }
    fixed_words = (uint16_t)(
        PYZ80_DRAW_PREPARED_V3_MAX_CHUNKS *
            (PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS +
             PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS) +
        PYZ80_DRAW_PREPARED_V3_MAX_RECORDS *
            PYZ80_DRAW_PREPARED_V3_RECORD_DL_WORDS);
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
    total_words = (uint16_t)(budget->non_fragment_dl_words + expected_words);
    if (total_words > budget->safe_line_cycles ||
            certificate->worst_raster_cycles >
                (uint16_t)(budget->safe_line_cycles - total_words)) {
        return 0u;
    }
    return 1u;
}

static void PyZ80DrawPreparedV3_CacheInvalidate(
        PyZ80DrawPreparedV3IdentityCache *cache,
        PyZ80DrawPreparedV3Mutation mutation)
{
    if (cache == NULL) {
        return;
    }
    cache->generation++;
    if (cache->generation == 0u) {
        cache->generation = 1u;
    }
    cache->template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
    cache->valid = 0u;
    cache->last_mutation = (uint8_t)mutation;
}

void PyZ80DrawPreparedV3_CacheSpawn(
        PyZ80DrawPreparedV3IdentityCache *cache,
        uint16_t bank_key, uint16_t descriptor, uint16_t template_index)
{
    if (cache == NULL) {
        return;
    }
    cache->bank_key = bank_key;
    cache->descriptor = descriptor;
    cache->generation = 1u;
    cache->last_mutation = PYZ80_DRAW_PREPARED_V3_MUTATION_SPAWN;
    if (template_index < PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT) {
        cache->template_index = template_index;
        cache->valid = 1u;
    } else {
        cache->template_index = PYZ80_FT_HQ_TEMPLATE_NOT_FOUND;
        cache->valid = 0u;
    }
}

void PyZ80DrawPreparedV3_CacheMutateBankKey(
        PyZ80DrawPreparedV3IdentityCache *cache, uint16_t bank_key)
{
    if (cache == NULL) {
        return;
    }
    cache->bank_key = bank_key;
    PyZ80DrawPreparedV3_CacheInvalidate(
        cache, PYZ80_DRAW_PREPARED_V3_MUTATION_BANK_KEY);
}

void PyZ80DrawPreparedV3_CacheMutateDescriptor(
        PyZ80DrawPreparedV3IdentityCache *cache, uint16_t descriptor)
{
    if (cache == NULL) {
        return;
    }
    cache->descriptor = descriptor;
    PyZ80DrawPreparedV3_CacheInvalidate(
        cache, PYZ80_DRAW_PREPARED_V3_MUTATION_DESCRIPTOR);
}

void PyZ80DrawPreparedV3_CacheMutateState(
        PyZ80DrawPreparedV3IdentityCache *cache)
{
    PyZ80DrawPreparedV3_CacheInvalidate(
        cache, PYZ80_DRAW_PREPARED_V3_MUTATION_STATE);
}

void PyZ80DrawPreparedV3_CacheMutateLevelPack(
        PyZ80DrawPreparedV3IdentityCache *cache)
{
    PyZ80DrawPreparedV3_CacheInvalidate(
        cache, PYZ80_DRAW_PREPARED_V3_MUTATION_LEVEL_PACK);
}

uint8_t PyZ80DrawPreparedV3_CacheInstallResolved(
        PyZ80DrawPreparedV3IdentityCache *cache,
        uint16_t expected_generation, uint16_t template_index)
{
    if (cache == NULL || cache->valid != 0u ||
            cache->generation != expected_generation ||
            template_index >= PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT) {
        return 0u;
    }
    cache->template_index = template_index;
    cache->valid = 1u;
    return 1u;
}

static PyZ80DrawPreparedV3Status PyZ80DrawPreparedV3_Publish(
        const volatile PyZ80DrawPreparedV3Record *private_records,
        uint16_t record_count, uint16_t append_words,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        const PyZ80DrawPreparedV3Certificate *certificate,
        const PyZ80DrawPreparedV3FrameBudget *budget,
        const PyZ80DrawPreparedV3Writer *writer,
        PyZ80DrawPreparedV3Result *result)
{
    uint16_t chunks;
    uint16_t fragment_words;
    uint16_t physical_words;
    uint16_t total_words;
    uint16_t first;
    PyZ80DrawPreparedV3Status status;
    chunks = record_count == 0u ? 0u :
        (uint16_t)(((record_count - 1u) >> 7) + 1u);
    fragment_words = (uint16_t)(
        chunks * (PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS +
                  PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS) +
        record_count * PYZ80_DRAW_PREPARED_V3_RECORD_DL_WORDS +
        append_words);
    physical_words = (uint16_t)(
        chunks * (PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS +
                  PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS) +
        record_count * PYZ80_DRAW_PREPARED_V3_RECORD_PHYSICAL_WORDS);
    total_words = (uint16_t)(budget->non_fragment_dl_words + fragment_words);
    result->preflight.record_count = record_count;
    result->preflight.chunk_count = chunks;
    result->preflight.cmd_append_expanded_words = append_words;
    result->preflight.fragment_expanded_dl_words = fragment_words;
    result->preflight.fragment_physical_words = physical_words;
    result->preflight.total_frame_dl_words = total_words;
    result->preflight.worst_raster_line = certificate->worst_raster_line;
    result->preflight.worst_line_cycles = (uint16_t)(
        total_words + certificate->worst_raster_cycles);
    if (chunks > PYZ80_DRAW_PREPARED_V3_MAX_CHUNKS ||
            fragment_words > certificate->max_fragment_expanded_dl_words ||
            total_words >= budget->ram_dl_word_limit) {
        result->status = PYZ80_DRAW_PREPARED_V3_RAM_DL;
        return PYZ80_DRAW_PREPARED_V3_RAM_DL;
    }
    if (result->preflight.worst_line_cycles > budget->safe_line_cycles) {
        result->status = PYZ80_DRAW_PREPARED_V3_RASTER;
        return PYZ80_DRAW_PREPARED_V3_RASTER;
    }
    if (writer->begin(writer->context, &result->preflight) == 0u) {
        writer->abort(writer->context);
        result->status = PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN;
        return PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN;
    }
    first = 0u;
    while (first < record_count) {
        uint16_t remaining = (uint16_t)(record_count - first);
        uint16_t count = remaining > PYZ80_DRAW_PREPARED_V3_CHUNK_RECORDS ?
            PYZ80_DRAW_PREPARED_V3_CHUNK_RECORDS : remaining;
        if (writer->append(
                writer->context, append_directory, append_directory_count,
                &private_records[first], count, first) == 0u) {
            status = PYZ80_DRAW_PREPARED_V3_WRITER_APPEND;
            goto fail_after_begin;
        }
        first = (uint16_t)(first + count);
        result->private_records_written = first;
        result->private_chunks_written++;
    }
    if (writer->commit(writer->context, &result->preflight) == 0u) {
        status = PYZ80_DRAW_PREPARED_V3_WRITER_COMMIT;
        goto fail_after_begin;
    }
    result->committed = 1u;
    result->status = PYZ80_DRAW_PREPARED_V3_OK;
    return PYZ80_DRAW_PREPARED_V3_OK;

fail_after_begin:
    writer->abort(writer->context);
    result->status = (uint8_t)status;
    return status;
}

PyZ80DrawPreparedV3Status PyZ80DrawPreparedV3_Run(
        const volatile PyZ80DrawPreparedV3Record *private_records,
        uint16_t record_count,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        const PyZ80DrawPreparedV3Certificate *certificate,
        const PyZ80DrawPreparedV3FrameBudget *budget,
        const PyZ80DrawPreparedV3Writer *writer,
        PyZ80DrawPreparedV3Result *result)
{
    const volatile PyZ80DrawPreparedV3Record *record;
    uint16_t index;
    uint16_t append_words = 0u;
    if (result == NULL) {
        return PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
    }
    PyZ80DrawPreparedV3_ZeroResult(result);
    if ((private_records == NULL && record_count != 0u) ||
            append_directory == NULL || append_directory_count == 0u ||
            writer == NULL ||
            writer->begin == NULL || writer->append == NULL ||
            writer->commit == NULL || writer->abort == NULL) {
        result->status = PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
        return PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
    }
    if (!PyZ80DrawPreparedV3_CertificateValid(certificate, budget)) {
        result->status = PYZ80_DRAW_PREPARED_V3_CERTIFICATE;
        return PYZ80_DRAW_PREPARED_V3_CERTIFICATE;
    }
    if (record_count > certificate->certified_max_records) {
        result->status = PYZ80_DRAW_PREPARED_V3_RECORD_BOUND;
        return PYZ80_DRAW_PREPARED_V3_RECORD_BOUND;
    }
    record = private_records;
    for (index = 0u; index < record_count; ++index, ++record) {
        const volatile PyZ80DrawPreparedV3AppendEntry *append;
        uint16_t byte_size;
        uint16_t words;
        if (record->append_ref >= append_directory_count) {
            result->failure_record_index = index;
            result->failure_append_ref = record->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
            return PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
        }
        append = &append_directory[record->append_ref];
        byte_size = append->byte_size;
        if (byte_size == 0u || (byte_size & 3u) != 0u ||
                PyZ80DrawPreparedV3_AppendAddress(append) >
                    0x00100000ul - (uint32_t)byte_size) {
            result->failure_record_index = index;
            result->failure_append_ref = record->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
            return PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
        }
        words = (uint16_t)(byte_size >> 2);
        if (append_words > (uint16_t)(0xFFFFu - words) ||
                (uint16_t)(append_words + words) >
                    certificate->max_cmd_append_expanded_words) {
            result->failure_record_index = index;
            result->failure_append_ref = record->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_APPEND_BOUND;
            return PYZ80_DRAW_PREPARED_V3_APPEND_BOUND;
        }
        append_words = (uint16_t)(append_words + words);
        result->validated_records++;
    }
    return PyZ80DrawPreparedV3_Publish(
        private_records, record_count, append_words,
        append_directory, append_directory_count,
        certificate, budget, writer, result);
}

PyZ80DrawPreparedV3Status PyZ80DrawPreparedV3_Build(
        const volatile PyZ80DrawPreparedV3SourceRecord *source_records,
        uint16_t record_count,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        volatile PyZ80DrawPreparedV3Record *private_records,
        uint16_t private_capacity,
        const PyZ80DrawPreparedV3Certificate *certificate,
        const PyZ80DrawPreparedV3FrameBudget *budget,
        const PyZ80DrawPreparedV3Writer *writer,
        PyZ80DrawPreparedV3Result *result)
{
    const volatile PyZ80DrawPreparedV3SourceRecord *source;
    volatile PyZ80DrawPreparedV3Record *target;
    uint16_t index;
    uint16_t append_words = 0u;
    if (result == NULL) {
        return PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
    }
    PyZ80DrawPreparedV3_ZeroResult(result);
    if ((source_records == NULL && record_count != 0u) ||
            (private_records == NULL && record_count != 0u) ||
            append_directory == NULL || append_directory_count == 0u ||
            writer == NULL || writer->begin == NULL ||
            writer->append == NULL || writer->commit == NULL ||
            writer->abort == NULL) {
        result->status = PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
        return PYZ80_DRAW_PREPARED_V3_INVALID_INPUT;
    }
    if (!PyZ80DrawPreparedV3_CertificateValid(certificate, budget)) {
        result->status = PYZ80_DRAW_PREPARED_V3_CERTIFICATE;
        return PYZ80_DRAW_PREPARED_V3_CERTIFICATE;
    }
    if (record_count > certificate->certified_max_records ||
            record_count > private_capacity) {
        result->status = PYZ80_DRAW_PREPARED_V3_RECORD_BOUND;
        return PYZ80_DRAW_PREPARED_V3_RECORD_BOUND;
    }
    source = source_records;
    target = private_records;
    for (index = 0u; index < record_count;
            ++index, ++source, ++target) {
        const volatile PyZ80DrawPreparedV3AppendEntry *append;
        uint16_t byte_size;
        uint16_t words;
        if (source->template_index >=
                PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT ||
                source->append_ref >= append_directory_count) {
            result->failure_record_index = index;
            result->failure_append_ref = source->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
            return PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
        }
        append = &append_directory[source->append_ref];
        byte_size = append->byte_size;
        if (byte_size == 0u || (byte_size & 3u) != 0u ||
                PyZ80DrawPreparedV3_AppendAddress(append) >
                    0x00100000ul - (uint32_t)byte_size) {
            result->failure_record_index = index;
            result->failure_append_ref = source->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
            return PYZ80_DRAW_PREPARED_V3_INVALID_RECORD;
        }
        words = (uint16_t)(byte_size >> 2);
        if (append_words > (uint16_t)(0xFFFFu - words) ||
                (uint16_t)(append_words + words) >
                    certificate->max_cmd_append_expanded_words) {
            result->failure_record_index = index;
            result->failure_append_ref = source->append_ref;
            result->status = PYZ80_DRAW_PREPARED_V3_APPEND_BOUND;
            return PYZ80_DRAW_PREPARED_V3_APPEND_BOUND;
        }
        target->append_ref = source->append_ref;
        target->vertex_x = source->vertex_x;
        target->vertex_y = source->vertex_y;
        append_words = (uint16_t)(append_words + words);
        result->validated_records++;
    }
    return PyZ80DrawPreparedV3_Publish(
        private_records, record_count, append_words,
        append_directory, append_directory_count,
        certificate, budget, writer, result);
}

uint8_t PyZ80DrawPreparedV3FT812_Begin(
        void *context, const PyZ80DrawPreparedV3Preflight *preflight)
{
    PyZ80DrawPreparedV3FT812WriterContext *target =
        (PyZ80DrawPreparedV3FT812WriterContext *)context;
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

uint8_t PyZ80DrawPreparedV3FT812_Append(
        void *context,
        const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
        uint16_t append_directory_count,
        const volatile PyZ80DrawPreparedV3Record *records,
        uint16_t count, uint16_t first_record_index)
{
    PyZ80DrawPreparedV3FT812WriterContext *target =
        (PyZ80DrawPreparedV3FT812WriterContext *)context;
    uint16_t index;
    uint16_t output;
    uint16_t dl_words;
    uint16_t needed;
    if (target == NULL || target->queue == NULL || records == NULL ||
            append_directory == NULL || append_directory_count == 0u ||
            target->begun != 1u || count == 0u ||
            count > PYZ80_DRAW_PREPARED_V3_CHUNK_RECORDS ||
            first_record_index != target->records_written ||
            target->queue->header.state != PYZ80_FT_QUEUE_BUILDING ||
            target->queue->header.kind != PYZ80_FT_QUEUE_FRAGMENT ||
            target->queue->header.count != 0u ||
            target->queue->header.payload_bytes != 0u ||
            target->queue->header.dl_words != 0u) {
        return 0u;
    }
    needed = (uint16_t)(
        PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS +
        PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS +
        count * PYZ80_DRAW_PREPARED_V3_RECORD_PHYSICAL_WORDS);
    if (needed > target->expected_physical_words ||
            target->write_index >
                (uint16_t)(target->expected_physical_words - needed)) {
        return 0u;
    }
    output = target->write_index;
    dl_words = target->dl_words;
    for (index = 0u; index < PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS; ++index) {
        target->queue->words[output++] = PyZ80DrawPreparedV3_BatchPrefix[index];
    }
    dl_words = (uint16_t)(dl_words + PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS);
    for (index = 0u; index < count; ++index) {
        uint16_t append_ref = records[index].append_ref;
        uint16_t byte_size;
        uint32_t address;
        uint16_t record_dl_words;
        if (append_ref >= append_directory_count) {
            return 0u;
        }
        address = PyZ80DrawPreparedV3_AppendAddress(
            &append_directory[append_ref]);
        byte_size = append_directory[append_ref].byte_size;
        if (byte_size == 0u || (byte_size & 3u) != 0u ||
                address > 0x00100000ul - (uint32_t)byte_size) {
            return 0u;
        }
        record_dl_words = (uint16_t)(2u + (byte_size >> 2));
        if (record_dl_words > target->expected_dl_words ||
                dl_words > (uint16_t)(
                    target->expected_dl_words - record_dl_words)) {
            return 0u;
        }
        target->queue->words[output++] =
            PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_X |
            (((uint32_t)(uint16_t)records[index].vertex_x << 1) &
             0x0001FFFFul);
        target->queue->words[output++] =
            PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_Y |
            (((uint32_t)(uint16_t)records[index].vertex_y << 1) &
             0x0001FFFFul);
        target->queue->words[output++] = PYZ80_DRAW_PREPARED_V3_CMD_APPEND;
        target->queue->words[output++] = address;
        target->queue->words[output++] = byte_size;
        dl_words = (uint16_t)(dl_words + record_dl_words);
    }
    target->queue->words[output++] =
        PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_X;
    target->queue->words[output++] =
        PYZ80_DRAW_PREPARED_V3_DL_VERTEX_TRANSLATE_Y;
    target->queue->words[output++] = PYZ80_DRAW_PREPARED_V3_DL_END;
    dl_words = (uint16_t)(dl_words + PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS);
    target->write_index = output;
    target->dl_words = dl_words;
    target->records_written = (uint16_t)(target->records_written + count);
    target->chunks_written++;
    return 1u;
}

uint8_t PyZ80DrawPreparedV3FT812_Commit(
        void *context, const PyZ80DrawPreparedV3Preflight *preflight)
{
    PyZ80DrawPreparedV3FT812WriterContext *target =
        (PyZ80DrawPreparedV3FT812WriterContext *)context;
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

void PyZ80DrawPreparedV3FT812_Abort(void *context)
{
    PyZ80DrawPreparedV3FT812WriterContext *target =
        (PyZ80DrawPreparedV3FT812WriterContext *)context;
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
