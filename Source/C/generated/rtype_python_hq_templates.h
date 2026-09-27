/* Generated from active Python M72SpriteAtlas preload. */
#ifndef RTYPE_PYTHON_HQ_TEMPLATES_H
#define RTYPE_PYTHON_HQ_TEMPLATES_H

#include <stdint.h>

#define PYZ80_FT_HQ_TEMPLATE_COUNT 40u
#define PYZ80_FT_ASM_HQ_TEMPLATE_COUNT 40
#define PYZ80_FT_HQ_TEMPLATE_CELL_COUNT 206u
#define PYZ80_FT_HQ_BITMAP_STATE_COUNT 12u
#define PYZ80_FT_HQ_APPEND_PHASE_COUNT 5u
#define PYZ80_FT_HQ_APPEND_ENTRY_COUNT 1000u
#define PYZ80_FT_HQ_APPEND_BLOB_COUNT 73u
#define PYZ80_FT_ASM_HQ_APPEND_BLOB_COUNT 73
#define PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS 128u
#define PYZ80_FT_HQ_TEMPLATE_HASH_MASK 0x007Fu
#define PYZ80_FT_HQ_TEMPLATE_HASH_MAX_PROBE 0u
#define PYZ80_FT_TYPED_RESOURCE_BYTES 32u
#define PYZ80_FT_BANK_TYPED 0x0100u
#define PYZ80_FT_BANK_FALLBACK 0x0000u
#define PYZ80_FT_BITMAP_ARGB4 6u
#define PYZ80_FT_BITMAP_PALETTED4444 15u
#define PYZ80_FT_NO_PALETTE 0xFFFFFFFFul

typedef struct PyZ80FtHQTemplate {
    uint16_t bank_key;
    uint8_t flags;
    uint8_t resource_hint;
    uint16_t descriptor_address;
    int16_t dx;
    int16_t dy;
    uint16_t code;
    uint8_t width;
    uint8_t height;
    uint16_t cell_first;
    uint16_t cell_count;
} PyZ80FtHQTemplate;

typedef struct PyZ80FtHQTemplateCell {
    uint32_t ram_g;
    int16_t local_x;
    int16_t local_y;
    uint8_t state_index;
} PyZ80FtHQTemplateCell;

typedef struct PyZ80FtHQBitmapState {
    uint32_t layout;
    uint32_t palette_ram_g;
} PyZ80FtHQBitmapState;

/* Exact anchor-domain guard and modulo-16-bit bias for the assembly batch
 * preflight. Passing the bounds proves that the biased result is inside the
 * public native-coordinate domain, so the low word is the exact result. */
typedef struct PyZ80FtHQBatchGeometry {
    int16_t anchor_x_min;
    int16_t anchor_x_max;
    uint16_t native_x_bias;
    int16_t anchor_y_min;
    int16_t anchor_y_max;
    uint16_t native_y_bias;
} PyZ80FtHQBatchGeometry;

_Static_assert(sizeof(PyZ80FtHQTemplate) == 18,
               "HQ template ABI changed");
_Static_assert(sizeof(PyZ80FtHQTemplateCell) == 9,
               "HQ template cell ABI changed");
_Static_assert(sizeof(PyZ80FtHQBitmapState) == 8,
               "HQ bitmap state ABI changed");
_Static_assert(sizeof(PyZ80FtHQBatchGeometry) == 12,
               "HQ batch geometry ABI changed");

extern const PyZ80FtHQTemplate
    PyZ80FT_HQTemplates[PYZ80_FT_HQ_TEMPLATE_COUNT];
/* Entry zero is empty; every other entry is template_index + 1. */
extern const uint16_t
    PyZ80FT_HQTemplateHash[PYZ80_FT_HQ_TEMPLATE_HASH_SLOTS];
extern const uint8_t
    PyZ80FT_TypedResources[PYZ80_FT_TYPED_RESOURCE_BYTES];
extern const PyZ80FtHQTemplateCell
    PyZ80FT_HQTemplateCells[PYZ80_FT_HQ_TEMPLATE_CELL_COUNT];
extern const PyZ80FtHQBitmapState
    PyZ80FT_HQBitmapStates[PYZ80_FT_HQ_BITMAP_STATE_COUNT];
extern const PyZ80FtHQBatchGeometry
    PyZ80FT_HQBatchGeometry[PYZ80_FT_HQ_TEMPLATE_COUNT];
/* Map order is template, Python-positive x%5, Python-positive y%5. */
extern const uint8_t
    PyZ80FT_HQAppendMap[PYZ80_FT_HQ_APPEND_ENTRY_COUNT];
extern const uint32_t
    PyZ80FT_HQAppendAddress[PYZ80_FT_HQ_APPEND_BLOB_COUNT];
extern const uint16_t
    PyZ80FT_HQAppendSize[PYZ80_FT_HQ_APPEND_BLOB_COUNT];

#endif
