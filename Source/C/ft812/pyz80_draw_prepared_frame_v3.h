/* Prepared-frame v3: no per-frame VM callback and no HQT identity lookup.
 *
 * The translator/gameplay backend owns a private TS-RAM frame buffer.  Cached
 * template identity is updated when descriptor/state/level-pack changes; the
 * frame producer only lowers current coordinates and emits phase-specific
 * append_ref + vertex coordinates.  This gate performs one linear validation
 * pass, then publishes the same immutable buffer atomically.
 */
#ifndef PYZ80_DRAW_PREPARED_FRAME_V3_H
#define PYZ80_DRAW_PREPARED_FRAME_V3_H

#include <stdint.h>

#include "pyz80_ft812.h"

#define PYZ80_DRAW_PREPARED_V3_CERTIFICATE_VERSION 3u
#define PYZ80_DRAW_PREPARED_V3_MAX_RECORDS 228u
#define PYZ80_DRAW_PREPARED_V3_CHUNK_RECORDS 128u
#define PYZ80_DRAW_PREPARED_V3_MAX_CHUNKS 2u
#define PYZ80_DRAW_PREPARED_V3_PREFIX_WORDS 10u
#define PYZ80_DRAW_PREPARED_V3_SUFFIX_WORDS 3u
#define PYZ80_DRAW_PREPARED_V3_RECORD_DL_WORDS 2u
#define PYZ80_DRAW_PREPARED_V3_RECORD_PHYSICAL_WORDS 5u
#define PYZ80_DRAW_PREPARED_V3_SAFE_LINE_CYCLES 1209u
#define PYZ80_DRAW_PREPARED_V3_GLOBAL_TEMPLATE_COUNT 10776u

/* Exact six-byte hot-frame record.  append_ref indexes the immutable loaded
 * level working-set append directory, not the 10,776-key identity catalog.
 * vertex_x/y are signed pre-x2 VERTEX_TRANSLATE values. */
typedef struct PyZ80DrawPreparedV3Record {
    uint16_t append_ref;
    int16_t vertex_x;
    int16_t vertex_y;
} PyZ80DrawPreparedV3Record;

/* The identity/phase cache is rebuilt outside the frame hot path.  Its final
 * lowering produces this compact directory.  Run reads entries directly in
 * O(1); there is deliberately no per-record callback or global HQT lookup. */
typedef struct PyZ80DrawPreparedV3AppendEntry {
    uint16_t ram_g_address_lo;
    uint16_t ram_g_address_hi;
    uint16_t byte_size;
} PyZ80DrawPreparedV3AppendEntry;

/* Generated object state owns one cache.  Resolver work is legal only on
 * spawn or one of the explicit identity mutation paths below. */
typedef enum PyZ80DrawPreparedV3Mutation {
    PYZ80_DRAW_PREPARED_V3_MUTATION_SPAWN = 0,
    PYZ80_DRAW_PREPARED_V3_MUTATION_BANK_KEY = 1,
    PYZ80_DRAW_PREPARED_V3_MUTATION_DESCRIPTOR = 2,
    PYZ80_DRAW_PREPARED_V3_MUTATION_STATE = 3,
    PYZ80_DRAW_PREPARED_V3_MUTATION_LEVEL_PACK = 4
} PyZ80DrawPreparedV3Mutation;

typedef struct PyZ80DrawPreparedV3IdentityCache {
    uint16_t bank_key;
    uint16_t descriptor;
    uint16_t template_index;
    uint16_t generation;
    uint8_t valid;
    uint8_t last_mutation;
} PyZ80DrawPreparedV3IdentityCache;

/* The translator emits these linearly from render order.  template_index is
 * copied from the cache solely to fail closed on stale invalidation; append_ref
 * is selected from that template's already localized phase table. */
typedef struct PyZ80DrawPreparedV3SourceRecord {
    uint16_t append_ref;
    int16_t vertex_x;
    int16_t vertex_y;
    uint16_t template_index;
} PyZ80DrawPreparedV3SourceRecord;

/* Register-ABI input for the optional Z80 hot producer in
 * Source/ASM/pyz80_draw_prepared_frame_v3.asm.  Call with HL=&params; it
 * returns A=0 on success or A=PYZ80_DRAW_PREPARED_V3_FAST_* on failure.
 * This is intentionally not exposed as a normal SDCC function prototype. */
typedef struct PyZ80DrawPreparedV3FastParams {
    const volatile PyZ80DrawPreparedV3SourceRecord *source_records;
    volatile PyZ80DrawPreparedV3Record *private_records;
    const volatile uint16_t *append_word_directory;
    uint8_t record_count;
    uint8_t append_directory_count;
    uint16_t max_append_words;
    uint16_t non_fragment_words;
    uint16_t worst_raster_cycles;
    uint16_t out_append_words;
    uint16_t out_fragment_words;
    uint16_t out_total_words;
    uint16_t out_failure_index;
    uint8_t status;
} PyZ80DrawPreparedV3FastParams;

typedef enum PyZ80DrawPreparedV3FastStatus {
    PYZ80_DRAW_PREPARED_V3_FAST_OK = 0,
    PYZ80_DRAW_PREPARED_V3_FAST_INVALID_RECORD = 1,
    PYZ80_DRAW_PREPARED_V3_FAST_APPEND_BOUND = 2,
    PYZ80_DRAW_PREPARED_V3_FAST_RAM_DL = 3,
    PYZ80_DRAW_PREPARED_V3_FAST_RASTER = 4
} PyZ80DrawPreparedV3FastStatus;

/* Register-ABI input for Source/ASM/pyz80_draw_prepared_queue_v3.asm.
 * Call with HL=&params after FAST_OK; it returns A=0 only after the final
 * queue READY byte has been published.  append_stream_directory contains one
 * prebuilt eight-byte {uint32 address,uint32 byte_size} pair per local ref. */
typedef struct PyZ80DrawPreparedV3FastQueueParams {
    const volatile PyZ80DrawPreparedV3Record *private_records;
    const volatile uint8_t *append_stream_directory;
    volatile PyZ80FtQueue *queue;
    const volatile PyZ80DrawPreparedV3FastParams *preflight;
    uint8_t record_count;
    uint16_t frame_sequence;
    uint8_t status;
} PyZ80DrawPreparedV3FastQueueParams;

void PyZ80DrawPreparedV3_CacheSpawn(
    PyZ80DrawPreparedV3IdentityCache *cache,
    uint16_t bank_key, uint16_t descriptor, uint16_t template_index);
void PyZ80DrawPreparedV3_CacheMutateBankKey(
    PyZ80DrawPreparedV3IdentityCache *cache, uint16_t bank_key);
void PyZ80DrawPreparedV3_CacheMutateDescriptor(
    PyZ80DrawPreparedV3IdentityCache *cache, uint16_t descriptor);
void PyZ80DrawPreparedV3_CacheMutateState(
    PyZ80DrawPreparedV3IdentityCache *cache);
void PyZ80DrawPreparedV3_CacheMutateLevelPack(
    PyZ80DrawPreparedV3IdentityCache *cache);
uint8_t PyZ80DrawPreparedV3_CacheInstallResolved(
    PyZ80DrawPreparedV3IdentityCache *cache,
    uint16_t expected_generation, uint16_t template_index);

#define PYZ80_DRAW_PREPARED_V3_MAX_BYTES \
    (PYZ80_DRAW_PREPARED_V3_MAX_RECORDS * \
     sizeof(PyZ80DrawPreparedV3Record))

typedef struct PyZ80DrawPreparedV3Certificate {
    uint8_t format_version;
    uint8_t sizing_proof_complete;
    uint8_t identity_cache_mutation_proved;
    uint8_t private_render_order_producer_proved;
    uint8_t append_directory_proved;
    uint8_t raster_768_lines_proved;
    uint16_t certified_max_records;
    uint16_t max_cmd_append_expanded_words;
    uint16_t max_fragment_expanded_dl_words;
    uint16_t worst_raster_line;
    uint16_t worst_raster_cycles;
} PyZ80DrawPreparedV3Certificate;

typedef struct PyZ80DrawPreparedV3FrameBudget {
    uint16_t ram_dl_word_limit;
    uint16_t non_fragment_dl_words;
    uint16_t safe_line_cycles;
} PyZ80DrawPreparedV3FrameBudget;

typedef struct PyZ80DrawPreparedV3Preflight {
    uint16_t record_count;
    uint16_t chunk_count;
    uint16_t cmd_append_expanded_words;
    uint16_t fragment_expanded_dl_words;
    uint16_t fragment_physical_words;
    uint16_t total_frame_dl_words;
    uint16_t worst_raster_line;
    uint16_t worst_line_cycles;
} PyZ80DrawPreparedV3Preflight;

typedef uint8_t (*PyZ80DrawPreparedV3WriterBegin)(
    void *context, const PyZ80DrawPreparedV3Preflight *preflight);
typedef uint8_t (*PyZ80DrawPreparedV3WriterAppend)(
    void *context,
    const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
    uint16_t append_directory_count,
    const volatile PyZ80DrawPreparedV3Record *records,
    uint16_t count, uint16_t first_record_index);
typedef uint8_t (*PyZ80DrawPreparedV3WriterCommit)(
    void *context, const PyZ80DrawPreparedV3Preflight *preflight);
typedef void (*PyZ80DrawPreparedV3WriterAbort)(void *context);

typedef struct PyZ80DrawPreparedV3Writer {
    PyZ80DrawPreparedV3WriterBegin begin;
    PyZ80DrawPreparedV3WriterAppend append;
    PyZ80DrawPreparedV3WriterCommit commit;
    PyZ80DrawPreparedV3WriterAbort abort;
    void *context;
} PyZ80DrawPreparedV3Writer;

typedef enum PyZ80DrawPreparedV3Status {
    PYZ80_DRAW_PREPARED_V3_OK = 0,
    PYZ80_DRAW_PREPARED_V3_INVALID_INPUT = 1,
    PYZ80_DRAW_PREPARED_V3_CERTIFICATE = 2,
    PYZ80_DRAW_PREPARED_V3_RECORD_BOUND = 3,
    PYZ80_DRAW_PREPARED_V3_INVALID_RECORD = 4,
    PYZ80_DRAW_PREPARED_V3_APPEND_BOUND = 5,
    PYZ80_DRAW_PREPARED_V3_RAM_DL = 6,
    PYZ80_DRAW_PREPARED_V3_RASTER = 7,
    PYZ80_DRAW_PREPARED_V3_WRITER_BEGIN = 8,
    PYZ80_DRAW_PREPARED_V3_WRITER_APPEND = 9,
    PYZ80_DRAW_PREPARED_V3_WRITER_COMMIT = 10
} PyZ80DrawPreparedV3Status;

typedef struct PyZ80DrawPreparedV3Result {
    PyZ80DrawPreparedV3Preflight preflight;
    uint16_t validated_records;
    uint16_t private_records_written;
    uint16_t private_chunks_written;
    uint16_t failure_record_index;
    uint16_t failure_append_ref;
    uint8_t status;
    uint8_t committed;
} PyZ80DrawPreparedV3Result;

PyZ80DrawPreparedV3Status PyZ80DrawPreparedV3_Run(
    const volatile PyZ80DrawPreparedV3Record *private_records,
    uint16_t record_count,
    const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
    uint16_t append_directory_count,
    const PyZ80DrawPreparedV3Certificate *certificate,
    const PyZ80DrawPreparedV3FrameBudget *budget,
    const PyZ80DrawPreparedV3Writer *writer,
    PyZ80DrawPreparedV3Result *result);

/* Fused v3 hot path: one direct source pass both produces the six-byte private
 * tape and computes its complete budget.  There is no second VM, resolver,
 * HQT identity lookup, or per-record function callback. */
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
    PyZ80DrawPreparedV3Result *result);

typedef struct PyZ80DrawPreparedV3FT812WriterContext {
    volatile PyZ80FtQueue *queue;
    uint16_t frame_sequence;
    uint16_t expected_physical_words;
    uint16_t expected_dl_words;
    uint16_t write_index;
    uint16_t dl_words;
    uint16_t records_written;
    uint16_t chunks_written;
    uint8_t begun;
} PyZ80DrawPreparedV3FT812WriterContext;

uint8_t PyZ80DrawPreparedV3FT812_Begin(
    void *context, const PyZ80DrawPreparedV3Preflight *preflight);
uint8_t PyZ80DrawPreparedV3FT812_Append(
    void *context,
    const volatile PyZ80DrawPreparedV3AppendEntry *append_directory,
    uint16_t append_directory_count,
    const volatile PyZ80DrawPreparedV3Record *records,
    uint16_t count, uint16_t first_record_index);
uint8_t PyZ80DrawPreparedV3FT812_Commit(
    void *context, const PyZ80DrawPreparedV3Preflight *preflight);
void PyZ80DrawPreparedV3FT812_Abort(void *context);

#endif
