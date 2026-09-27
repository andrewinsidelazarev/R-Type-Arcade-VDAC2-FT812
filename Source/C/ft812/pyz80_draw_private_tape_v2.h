/* Single-evaluation whole-frame draw gate.
 *
 * The active Python draw VM and HQT identity resolver execute exactly once.
 * Their resolved records are written to a private tape in mapped TS RAM
 * (never RAM_G and never the public FT812 queue).  Only after the complete
 * record/append/RAM_DL/raster preflight succeeds is that immutable tape
 * replayed into an inactive FT812 queue and published by one final commit.
 */
#ifndef PYZ80_DRAW_PRIVATE_TAPE_V2_H
#define PYZ80_DRAW_PRIVATE_TAPE_V2_H

#include <stdint.h>

#include "pyz80_ft812.h"
#include "rtype_python_draw_vm.h"

#define PYZ80_DRAW_TAPE_V2_CERTIFICATE_VERSION 2u
#define PYZ80_DRAW_TAPE_V2_MAX_RECORDS 228u
#define PYZ80_DRAW_TAPE_V2_CHUNK_RECORDS 128u
#define PYZ80_DRAW_TAPE_V2_MAX_CHUNKS 2u
#define PYZ80_DRAW_TAPE_V2_PREFIX_WORDS 10u
#define PYZ80_DRAW_TAPE_V2_SUFFIX_WORDS 3u
#define PYZ80_DRAW_TAPE_V2_RECORD_DL_WORDS 2u
#define PYZ80_DRAW_TAPE_V2_RECORD_PHYSICAL_WORDS 5u
#define PYZ80_DRAW_TAPE_V2_SAFE_LINE_CYCLES 1209u
#define PYZ80_DRAW_TAPE_V2_CATALOG_KEYS 10776u
#define PYZ80_DRAW_TAPE_V2_CATALOG_MAX_COMPARISONS 14u
#define PYZ80_DRAW_TAPE_V2_CUCKOO_SLOTS 32768u
#define PYZ80_DRAW_TAPE_V2_CUCKOO_MASK 0x7FFFu
#define PYZ80_DRAW_TAPE_V2_CUCKOO_SEED1 0x3594u
#define PYZ80_DRAW_TAPE_V2_CUCKOO_SEED2 0x729Cu
#define PYZ80_DRAW_TAPE_V2_CUCKOO_MAX_READS 2u

typedef struct PyZ80DrawTapeV2Record {
    uint16_t template_index;
    int16_t anchor_x;
    int16_t anchor_y;
    uint16_t append_expanded_words;
} PyZ80DrawTapeV2Record;

#define PYZ80_DRAW_TAPE_V2_MAX_BYTES \
    (PYZ80_DRAW_TAPE_V2_MAX_RECORDS * sizeof(PyZ80DrawTapeV2Record))

typedef struct PyZ80DrawTapeV2Resolution {
    uint16_t template_index;
    uint16_t append_expanded_words;
} PyZ80DrawTapeV2Resolution;

/* A 10,776-key catalog is expected to live in banked TS RAM.  The reader is
 * the only paging boundary; binary search performs at most 14 indexed reads
 * and never scans the table.  The build-time certificate must prove strict
 * lexicographic order and uniqueness. */
typedef struct PyZ80DrawTapeV2CatalogEntry {
    uint16_t bank_key;
    uint16_t descriptor;
    uint16_t template_index;
} PyZ80DrawTapeV2CatalogEntry;

typedef uint8_t (*PyZ80DrawTapeV2CatalogRead)(
    void *context, uint16_t index, PyZ80DrawTapeV2CatalogEntry *entry_out);

uint8_t PyZ80DrawTapeV2_FindCatalogBounded(
    PyZ80DrawTapeV2CatalogRead read_entry, void *context,
    uint16_t entry_count, uint16_t bank_key, uint16_t descriptor,
    uint16_t *template_index_out, uint8_t *comparisons_out);

/* Actual hot-path lookup: the build-time checker places all 10,776 exact keys
 * into a fixed 32,768-slot two-choice cuckoo table.  Runtime performs at most
 * two indexed TS-RAM reads, with the key stored in each slot preventing a
 * false hit. */
uint8_t PyZ80DrawTapeV2_FindCatalogCuckoo(
    PyZ80DrawTapeV2CatalogRead read_slot, void *context,
    uint16_t bank_key, uint16_t descriptor,
    uint16_t *template_index_out, uint8_t *reads_out);

typedef uint8_t (*PyZ80DrawTapeV2Resolve)(
    void *context, const rtype_python_draw_vm_record *record,
    PyZ80DrawTapeV2Resolution *resolved_out);

typedef struct PyZ80DrawTapeV2Certificate {
    uint8_t format_version;
    uint8_t sizing_proof_complete;
    uint8_t catalog_order_unique_proved;
    uint8_t catalog_cuckoo_layout_proved;
    uint8_t raster_768_lines_proved;
    uint16_t catalog_key_count;
    uint8_t catalog_max_comparisons;
    uint8_t catalog_max_runtime_reads;
    uint16_t certified_max_records;
    uint16_t max_cmd_append_expanded_words;
    uint16_t max_fragment_expanded_dl_words;
    uint16_t worst_raster_line;
    uint16_t worst_raster_cycles;
} PyZ80DrawTapeV2Certificate;

typedef struct PyZ80DrawTapeV2FrameBudget {
    uint16_t ram_dl_word_limit;
    uint16_t non_fragment_dl_words;
    uint16_t safe_line_cycles;
} PyZ80DrawTapeV2FrameBudget;

typedef struct PyZ80DrawTapeV2Preflight {
    uint16_t record_count;
    uint16_t chunk_count;
    uint16_t cmd_append_expanded_words;
    uint16_t fragment_expanded_dl_words;
    uint16_t fragment_physical_words;
    uint16_t total_frame_dl_words;
    uint16_t worst_raster_line;
    uint16_t worst_line_cycles;
} PyZ80DrawTapeV2Preflight;

/* begin/append operate only on inactive storage.  append consumes the already
 * resolved tape and may not invoke the bank+descriptor HQT resolver. */
typedef uint8_t (*PyZ80DrawTapeV2WriterBegin)(
    void *context, const PyZ80DrawTapeV2Preflight *preflight);
typedef uint8_t (*PyZ80DrawTapeV2WriterAppend)(
    void *context, const volatile PyZ80DrawTapeV2Record *records,
    uint16_t count, uint16_t first_record_index);
typedef uint8_t (*PyZ80DrawTapeV2WriterCommit)(
    void *context, const PyZ80DrawTapeV2Preflight *preflight);
typedef void (*PyZ80DrawTapeV2WriterAbort)(void *context);

typedef struct PyZ80DrawTapeV2Writer {
    PyZ80DrawTapeV2WriterBegin begin;
    PyZ80DrawTapeV2WriterAppend append;
    PyZ80DrawTapeV2WriterCommit commit;
    PyZ80DrawTapeV2WriterAbort abort;
    void *context;
} PyZ80DrawTapeV2Writer;

typedef enum PyZ80DrawTapeV2Status {
    PYZ80_DRAW_TAPE_V2_OK = 0,
    PYZ80_DRAW_TAPE_V2_INVALID_INPUT = 1,
    PYZ80_DRAW_TAPE_V2_CERTIFICATE = 2,
    PYZ80_DRAW_TAPE_V2_VM = 3,
    PYZ80_DRAW_TAPE_V2_RECORD_BOUND = 4,
    PYZ80_DRAW_TAPE_V2_LOOKUP = 5,
    PYZ80_DRAW_TAPE_V2_APPEND_BOUND = 6,
    PYZ80_DRAW_TAPE_V2_RAM_DL = 7,
    PYZ80_DRAW_TAPE_V2_RASTER = 8,
    PYZ80_DRAW_TAPE_V2_WRITER_BEGIN = 9,
    PYZ80_DRAW_TAPE_V2_WRITER_APPEND = 10,
    PYZ80_DRAW_TAPE_V2_WRITER_COMMIT = 11
} PyZ80DrawTapeV2Status;

typedef struct PyZ80DrawTapeV2Result {
    PyZ80DrawTapeV2Preflight preflight;
    uint16_t evaluated_records;
    uint16_t private_records_written;
    uint16_t private_chunks_written;
    uint16_t failure_record_index;
    uint16_t failure_bank_key;
    uint16_t failure_descriptor;
    uint8_t vm_status;
    uint8_t status;
    uint8_t committed;
} PyZ80DrawTapeV2Result;

PyZ80DrawTapeV2Status PyZ80DrawTapeV2_Run(
    const rtype_python_draw_vm_input *input,
    const PyZ80DrawTapeV2Certificate *certificate,
    const PyZ80DrawTapeV2FrameBudget *budget,
    PyZ80DrawTapeV2Resolve resolve, void *resolve_context,
    volatile PyZ80DrawTapeV2Record *private_tape,
    uint16_t private_tape_capacity,
    const PyZ80DrawTapeV2Writer *writer,
    PyZ80DrawTapeV2Result *result);

/* Concrete inactive ED/EE queue writer.  It performs only O(1) indexed phase
 * lowering from template_index; it never redoes the 10,776-key identity
 * lookup. */
typedef struct PyZ80DrawTapeV2FT812WriterContext {
    volatile PyZ80FtQueue *queue;
    uint16_t frame_sequence;
    uint16_t expected_physical_words;
    uint16_t expected_dl_words;
    uint16_t write_index;
    uint16_t dl_words;
    uint16_t records_written;
    uint16_t chunks_written;
    uint8_t begun;
} PyZ80DrawTapeV2FT812WriterContext;

uint8_t PyZ80DrawTapeV2FT812_Begin(
    void *context, const PyZ80DrawTapeV2Preflight *preflight);
uint8_t PyZ80DrawTapeV2FT812_Append(
    void *context, const volatile PyZ80DrawTapeV2Record *records,
    uint16_t count, uint16_t first_record_index);
uint8_t PyZ80DrawTapeV2FT812_Commit(
    void *context, const PyZ80DrawTapeV2Preflight *preflight);
void PyZ80DrawTapeV2FT812_Abort(void *context);

#endif
