/* Блочное копирование обычной RAM через окно 2; не применять к MMIO.
 * Код, стек, context и резидентный data находятся вне окна 2. */
#ifndef PYZ80_TSCONF_BULK_H
#define PYZ80_TSCONF_BULK_H
#include "pyz80_tsconf_buffer.h"

static uint8_t PyTSBuffer_BulkTransfer(void *context,uint32_t position,
                                     uint8_t *data,uint8_t size,uint8_t write) {
    PyTSBuffer *backing=(PyTSBuffer *)context;
    uint32_t limit=(uint32_t)backing->pages<<14;
    uint16_t address,chunk,left=size;
    uint8_t page;
    if(backing->pages>256 || (uint16_t)backing->first_page+backing->pages>256 ||
       position>limit || size>limit-position) return PYBUF_BACKING;
    if(!size) return 0;
    page=backing->first_page+(uint8_t)(position>>14);
    address=0x8000u|(uint16_t)(position&0x3fff);
    while(left) {
        chunk=0xc000u-address;
        if(chunk>left) chunk=left;
        *(volatile uint8_t *)0x0412=page;
        if(write) memcpy((void *)address,data,chunk);
        else memcpy(data,(const void *)address,chunk);
        data+=chunk; left-=chunk; /* ADD/SUB: перейти к непереданному остатку. */
        address=0x8000; ++page;
    }
    *(volatile uint8_t *)0x0412=backing->restore_page;
    return 0;
}
#endif
