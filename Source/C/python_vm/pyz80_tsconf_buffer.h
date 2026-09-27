/* Отображение логического bytes/bytearray в последовательность страниц TS-Conf.
 * Код, стек, context и буфер передачи находятся вне окна 2 (#8000..#BFFF).
 * FMap должен быть включён. restore_page задаётся владельцем окна явно. */
#ifndef PYZ80_TSCONF_BUFFER_H
#define PYZ80_TSCONF_BUFFER_H
#include "pyz80_buffer_view.h"

typedef struct { uint8_t first_page; uint16_t pages; uint8_t restore_page; } PyTSBuffer;

static uint8_t PyTSBuffer_Transfer(void *context,uint32_t position,
                                  uint8_t *data,uint8_t size,uint8_t write) {
    PyTSBuffer *backing=(PyTSBuffer *)context;
    uint32_t limit=(uint32_t)backing->pages<<14;
    uint16_t address;
    uint8_t page,index;
    if(backing->pages>256 || (uint16_t)backing->first_page+backing->pages>256 ||
       position>limit || size>limit-position) return PYBUF_BACKING;
    if(!size) return 0;
    page=backing->first_page+(uint8_t)(position>>14);
    address=0x8000u|(uint16_t)(position&0x3fff);
    *(volatile uint8_t *)0x0412=page;
    for(index=0;index<size;++index) {
        if(write) *(volatile uint8_t *)address=data[index];
        else data[index]=*(const volatile uint8_t *)address;
        ++address; /* INC: следующий байт в окне, в том числе на стыке страниц. */
        if(address==0xc000 && index+1<size) {
            address=0x8000; ++page;
            *(volatile uint8_t *)0x0412=page;
        }
    }
    *(volatile uint8_t *)0x0412=backing->restore_page;
    return 0;
}
#endif
