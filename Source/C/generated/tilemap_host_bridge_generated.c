#include "tilemap_binding_generated.h"
#include "tilemap_table_generated.h"
#include "tilemap_buffer_generated.h"
uint8_t Tilemap_ApplyTable(TilemapState *record,int32_t layer,int32_t source,int32_t destination,uint8_t *error) {
    return Tilemaps_TryTable(&tilemap_resources.table,&record->vram,&tilemap_resources.scratch,layer,source,destination,error);
}
uint8_t Tilemap_ApplyDecoder(PyBufferFault *fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination) {
    return Tilemaps_DrawStrip(fault,&record->rom,&record->vram,layer,source,destination);
}
PY_AGGREGATE_API TilemapResources *Tilemap_GetResources(void) { return &tilemap_resources; }
