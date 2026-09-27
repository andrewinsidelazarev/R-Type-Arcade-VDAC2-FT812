#ifndef PYZ80_TARGET_BANKED_TABLES_H
#define PYZ80_TARGET_BANKED_TABLES_H
#include "pyz80_target_object_runtime.h"

/* PZTB v1: 44-byte header, ten (offset:u32,count:u16) directory entries,
   packed LE records. No C struct padding is persisted. Immutable after attach. */
#define PYZ80_TABLE_IMAGE_HEADER 104u
typedef struct PyZ80TargetBankedTables {
    PyZ80VMImage image;
    uint32_t offsets[PYZ80_TABLE_COUNT];
    uint16_t counts[PYZ80_TABLE_COUNT];
} PyZ80TargetBankedTables;

/* Attach BEFORE scopes/imports/classes. The image proof must match the VM and
   expected_crc must come from its sealed generated descriptor, not the image.
   Caller owns state/keys, disjoint from VM/object storage and mapped windows.
   Failed attach leaves objects and state unchanged. Reader state, source,
   descriptors and callbacks must remain immutable and disjoint from keys.
   keys may be NULL with capacity 0 when bulk field stores are not used. */
uint8_t PyZ80Target_AttachBankedTables(PyZ80TargetContext *objects, PyZ80VM *vm,
    PyZ80TargetBankedTables *state, const PyZ80VMImage *image, uint32_t expected_crc,
    uint16_t *keys, uint16_t key_capacity);
#endif
