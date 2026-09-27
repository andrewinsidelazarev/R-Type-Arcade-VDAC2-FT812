/* Direct-RAM_DL shadow v4 prototype.
 *
 * This file is deliberately not linked into the current translator/SPG.  The
 * translated object list is maintained outside render time.  A complete,
 * immutable display list is built in one of two TS-RAM shadows; render only
 * transports the READY shadow to FT812 RAM_DL and requests a frame swap.
 */
#ifndef PYZ80_DRAW_RAMDL_SHADOW_V4_H
#define PYZ80_DRAW_RAMDL_SHADOW_V4_H

#include <stdint.h>

#define PYZ80_DRAW_RAMDL_V4_CERTIFICATE_VERSION 4u
#define PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS 228u
#define PYZ80_DRAW_RAMDL_V4_RAM_DL_WORDS 2048u
#define PYZ80_DRAW_RAMDL_V4_MAX_USED_WORDS 2047u
#define PYZ80_DRAW_RAMDL_V4_SHADOW_BYTES 8192u
#define PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT 2u
#define PYZ80_DRAW_RAMDL_V4_DOUBLE_SHADOW_BYTES 16384u
#define PYZ80_DRAW_RAMDL_V4_TS_RAM_BYTES 4194304ul
#define PYZ80_DRAW_RAMDL_V4_TS_PAGE_BYTES 16384u
#define PYZ80_DRAW_RAMDL_V4_SAFE_LINE_CYCLES 1209u
#define PYZ80_DRAW_RAMDL_V4_CALL_STACK_LIMIT 4u
#define PYZ80_DRAW_RAMDL_V4_INVALID_INDEX 0xFFFFu
#define PYZ80_DRAW_RAMDL_V4_DEDUP_SCRATCH_TARGET_BYTES 1830u

#define PYZ80_DRAW_RAMDL_V4_DL_DISPLAY 0x00000000ul
#define PYZ80_DRAW_RAMDL_V4_DL_CALL 0x1D000000ul
#define PYZ80_DRAW_RAMDL_V4_DL_JUMP 0x1E000000ul
#define PYZ80_DRAW_RAMDL_V4_DL_RETURN 0x24000000ul
#define PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_X 0x2B000000ul
#define PYZ80_DRAW_RAMDL_V4_DL_VERTEX_TRANSLATE_Y 0x2C000000ul

typedef enum PyZ80DrawRamDLV4ShadowState {
    PYZ80_DRAW_RAMDL_V4_SHADOW_FREE = 0,
    PYZ80_DRAW_RAMDL_V4_SHADOW_BUILDING = 1,
    PYZ80_DRAW_RAMDL_V4_SHADOW_READY = 2,
    PYZ80_DRAW_RAMDL_V4_SHADOW_DMA = 3,
    PYZ80_DRAW_RAMDL_V4_SHADOW_SWAP_PENDING = 4,
    PYZ80_DRAW_RAMDL_V4_SHADOW_RETIRED = 5,
    PYZ80_DRAW_RAMDL_V4_SHADOW_ABORTED = 6,
    PYZ80_DRAW_RAMDL_V4_SHADOW_ACTIVE = 7
} PyZ80DrawRamDLV4ShadowState;

typedef enum PyZ80DrawRamDLV4Dirty {
    PYZ80_DRAW_RAMDL_V4_DIRTY_NONE = 0,
    PYZ80_DRAW_RAMDL_V4_DIRTY_COORDINATES = 1,
    PYZ80_DRAW_RAMDL_V4_DIRTY_IDENTITY = 2,
    PYZ80_DRAW_RAMDL_V4_DIRTY_ORDER = 4,
    PYZ80_DRAW_RAMDL_V4_DIRTY_LIST = 8
} PyZ80DrawRamDLV4Dirty;

/* Fragment words are copied byte-for-byte.  They must be immutable, aligned
 * FT812 display-list words and may not contain CALL/JUMP/RETURN/DISPLAY.
 * Structural control stays owned by this builder, so CALL nesting is one. */
typedef struct PyZ80DrawRamDLV4Fragment {
    const uint32_t *words;
    uint16_t word_count;
    uint16_t worst_line_cycles;
    uint16_t identity;
    uint16_t generation;
} PyZ80DrawRamDLV4Fragment;

/* Array order is the exact Python draw order. */
typedef struct PyZ80DrawRamDLV4Object {
    uint16_t object_id;
    uint16_t generation;
    int16_t vertex_x;
    int16_t vertex_y;
    const PyZ80DrawRamDLV4Fragment *fragment;
} PyZ80DrawRamDLV4Object;

typedef struct PyZ80DrawRamDLV4Model {
    PyZ80DrawRamDLV4Object *objects;
    uint16_t count;
    uint16_t capacity;
    uint16_t epoch;
    uint8_t dirty;
    uint8_t mutation_lock;
} PyZ80DrawRamDLV4Model;

typedef struct PyZ80DrawRamDLV4Shadow {
    volatile uint32_t *words;
    uint16_t capacity_words;
    uint16_t used_words;
    uint16_t main_words;
    uint16_t subroutine_words;
    uint16_t object_count;
    uint16_t unique_fragment_count;
    uint16_t model_epoch;
    uint16_t publish_epoch;
    uint16_t worst_line_cycles;
    uint16_t checksum;
    uint16_t dedup_checksum;
    uint8_t physical_page;
    uint16_t physical_offset;
    uint8_t state;
    uint8_t slot;
} PyZ80DrawRamDLV4Shadow;

typedef struct PyZ80DrawRamDLV4DoubleShadow {
    PyZ80DrawRamDLV4Shadow slot[PYZ80_DRAW_RAMDL_V4_SHADOW_COUNT];
    uint16_t next_publish_epoch;
    uint16_t retired_epoch;
    uint16_t dma_epoch;
    uint8_t active_slot;
    uint8_t dma_slot;
} PyZ80DrawRamDLV4DoubleShadow;

/* Custom HL parameter ABI for pyz80_draw_ramdl_shadow_v4.asm.  The target
 * routine always transports one complete 8 KiB shadow as one TS DMA request;
 * unused words are DISPLAY(0), prepared off-frame by BuildInactive. */
typedef struct PyZ80DrawRamDLV4FastPublishParams {
    volatile uint8_t *shadow_state;
    volatile uint16_t *retired_epoch;
    uint16_t used_words;
    uint16_t publish_epoch;
    uint16_t source_offset;
    uint16_t fence_poll_limit;
    uint8_t source_page;
    uint8_t status;
} PyZ80DrawRamDLV4FastPublishParams;

typedef struct PyZ80DrawRamDLV4Certificate {
    uint8_t format_version;
    uint8_t immutable_fragment_proof;
    uint8_t dedup_identity_generation_proof;
    uint8_t exact_order_hook_proof;
    uint8_t direct_ram_dl_proof;
    uint8_t double_shadow_epoch_proof;
    uint8_t swap_fence_proof;
    uint8_t raster_proof;
    uint8_t ts_ram_allocation_proof;
    uint16_t max_objects;
    uint16_t max_used_words;
    uint16_t safe_line_cycles;
    uint16_t fragment_min_words;
    uint16_t fragment_max_words;
} PyZ80DrawRamDLV4Certificate;

/* Caller-owned, preallocated off-frame workspace.  It is deliberately an
 * explicit ABI object rather than an automatic local: with 16-bit target
 * pointers its exact size is 1,830 bytes, far too large for the Z80 stack.
 * The bounded table replaces heap allocation.  BuildInactive consumes the
 * exact map produced by its Preflight call; the publish ASM never sees it. */
typedef struct PyZ80DrawRamDLV4DedupScratch {
    const PyZ80DrawRamDLV4Fragment
        *unique_fragments[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
    uint16_t unique_word_offsets[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
    uint16_t object_to_unique[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
    uint16_t unique_first_object[PYZ80_DRAW_RAMDL_V4_MAX_OBJECTS];
    uint16_t unique_count;
    uint16_t model_epoch;
    uint16_t map_checksum;
} PyZ80DrawRamDLV4DedupScratch;

/* Whole-scene scanline proof generated from the same immutable model epoch.
 * A per-fragment scalar is not sufficient because translated sprites overlap;
 * the 768-line array is the exact conservative composition used by the gate. */
typedef struct PyZ80DrawRamDLV4RasterProof {
    const uint16_t *cycles_by_line;
    uint16_t line_count;
    uint16_t model_epoch;
    uint16_t max_cycles;
    uint16_t worst_line;
} PyZ80DrawRamDLV4RasterProof;

typedef struct PyZ80DrawRamDLV4Layout {
    uint16_t object_count;
    uint16_t prefix_words;
    uint16_t coordinate_words;
    uint16_t call_words;
    uint16_t suffix_words;
    uint16_t main_words;
    uint16_t subroutine_words;
    uint16_t total_words;
    uint16_t unique_fragment_count;
    uint16_t worst_line_cycles;
    uint16_t first_failure_index;
    uint16_t model_epoch;
} PyZ80DrawRamDLV4Layout;

typedef enum PyZ80DrawRamDLV4Status {
    PYZ80_DRAW_RAMDL_V4_OK = 0,
    PYZ80_DRAW_RAMDL_V4_INVALID_INPUT = 1,
    PYZ80_DRAW_RAMDL_V4_CERTIFICATE = 2,
    PYZ80_DRAW_RAMDL_V4_RECORD_BOUND = 3,
    PYZ80_DRAW_RAMDL_V4_FRAGMENT = 4,
    PYZ80_DRAW_RAMDL_V4_CAPACITY = 5,
    PYZ80_DRAW_RAMDL_V4_RASTER = 6,
    PYZ80_DRAW_RAMDL_V4_STALE_EPOCH = 7,
    PYZ80_DRAW_RAMDL_V4_NO_INACTIVE_SHADOW = 8,
    PYZ80_DRAW_RAMDL_V4_BUSY = 9,
    PYZ80_DRAW_RAMDL_V4_FENCE = 10,
    PYZ80_DRAW_RAMDL_V4_DEDUP_MISMATCH = 11
} PyZ80DrawRamDLV4Status;

/* Mutation/list hooks.  They change only the authoritative off-frame model;
 * no hook writes the READY, DMA or active shadow. */
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnSpawn(
    PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
    const PyZ80DrawRamDLV4Object *object);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnRemove(
    PyZ80DrawRamDLV4Model *model, uint16_t draw_index);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnMove(
    PyZ80DrawRamDLV4Model *model, uint16_t from_index, uint16_t to_index);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnCoordinates(
    PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
    int16_t vertex_x, int16_t vertex_y);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_OnIdentity(
    PyZ80DrawRamDLV4Model *model, uint16_t draw_index,
    const PyZ80DrawRamDLV4Fragment *fragment, uint16_t object_generation);

/* Pass A only: validates immutable fragments and computes exact capacity. */
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_Preflight(
    const PyZ80DrawRamDLV4Model *model,
    const uint32_t *prefix, uint16_t prefix_words,
    const uint32_t *suffix, uint16_t suffix_words,
    const PyZ80DrawRamDLV4Certificate *certificate,
    const PyZ80DrawRamDLV4RasterProof *raster,
    PyZ80DrawRamDLV4DedupScratch *scratch,
    PyZ80DrawRamDLV4Layout *layout);

/* Pass B writes only an inactive shadow.  READY is the last store and is
 * withheld if model->epoch changes between preflight and completion. */
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_BuildInactive(
    PyZ80DrawRamDLV4Model *model,
    const uint32_t *prefix, uint16_t prefix_words,
    const uint32_t *suffix, uint16_t suffix_words,
    const PyZ80DrawRamDLV4Certificate *certificate,
    const PyZ80DrawRamDLV4RasterProof *raster,
    PyZ80DrawRamDLV4DedupScratch *scratch,
    PyZ80DrawRamDLV4DoubleShadow *shadows,
    PyZ80DrawRamDLV4Layout *layout);

/* Host/reference retirement protocol.  Target ASM performs the actual single
 * TS DMA, DLSWAP_FRAME request and INT_SWAP/REG_DLSWAP fence. */
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_AcquireReady(
    PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t *slot_out);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_MarkDMADone(
    PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t slot);
PyZ80DrawRamDLV4Status PyZ80DrawRamDLV4_RetireSwap(
    PyZ80DrawRamDLV4DoubleShadow *shadows, uint8_t slot,
    uint8_t int_swap_seen, uint8_t reg_dlswap_zero);

#endif
