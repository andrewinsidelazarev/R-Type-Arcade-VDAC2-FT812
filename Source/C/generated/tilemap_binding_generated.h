#ifndef TILEMAP_BINDING_H
#define TILEMAP_BINDING_H
#include "tilemap_state_generated.h"
typedef struct {
    PyBufferView initial,table;
    PyBufferSpan scratch;
    uint32_t hits,misses;
} TilemapResources;
extern TilemapResources tilemap_resources;
uint8_t Tilemap_ApplyTable(TilemapState *record,int32_t layer,int32_t source,int32_t destination,uint8_t *error);
uint8_t Tilemap_ApplyDecoder(PyBufferFault *fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination);
#endif
