#include "tilemap_table_generated.c"
#include "tilemap_kernel_abi_generated.h"
#include "tilemap_bank_provider_generated.h"
void Tilemap_CacheDispatch(void) {
    uint8_t error;
    PyBufferTransfer saved[4];
    TilemapResources *resources=tilemap_job.resources;
    Tilemap_BankCallbacks(saved,0);
    tilemap_job.status=Tilemaps_TryTable(&resources->table,&tilemap_job.record->vram,&resources->scratch,
        tilemap_job.layer,tilemap_job.source,tilemap_job.destination,&error);
    tilemap_job.error=error;
    Tilemap_BankCallbacks(saved,1);
}
