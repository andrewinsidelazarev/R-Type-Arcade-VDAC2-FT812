#ifndef TILEMAP_KERNEL_ABI_H
#define TILEMAP_KERNEL_ABI_H
#include "tilemap_binding_generated.h"
typedef struct {
    PyBufferFault *fault;
    TilemapState *record;
    TilemapResources *resources;
    int32_t layer,source,destination;
    uint8_t error,status;
} TilemapJob;
#define tilemap_job (*(volatile TilemapJob *)0x2180)
#define kernel_scroll (*(StageScroll *)0x3100)
#endif
