#ifndef TILEMAP_BANK_PROVIDER_H
#define TILEMAP_BANK_PROVIDER_H
#include "pyz80_tsconf_bulk.h"
/* Указатель функции из другого кодового банка недействителен до возврата.
 * На время вызова привязать байтовые операции к провайдеру текущего банка. */
static void Tilemap_BankCallbacks(PyBufferTransfer *saved,uint8_t restore) {
    PyBufferView *views[4];
    uint8_t i;
    views[0]=&tilemap_job.record->rom;
    views[1]=&tilemap_job.resources->table;
    views[2]=&tilemap_job.record->vram.items[0];
    views[3]=&tilemap_job.record->vram.items[1];
    for(i=0;i<4;++i) {
        if(restore) views[i]->transfer=saved[i];
        else { saved[i]=views[i]->transfer; views[i]->transfer=PyTSBuffer_BulkTransfer; }
    }
}
#endif
