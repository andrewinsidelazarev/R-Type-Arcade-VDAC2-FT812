#include "tilemap_buffer_generated.c"
#include "tilemap_kernel_abi_generated.h"
#include "tilemap_bank_provider_generated.h"
void Tilemap_DecoderDispatch(void) {
    PyBufferTransfer saved[4];
    TilemapState *record=tilemap_job.record;
    Tilemap_BankCallbacks(saved,0);
    tilemap_job.status=Tilemaps_DrawStrip(tilemap_job.fault,&record->rom,&record->vram,
        tilemap_job.layer,tilemap_job.source,tilemap_job.destination);
    Tilemap_BankCallbacks(saved,1);
}
