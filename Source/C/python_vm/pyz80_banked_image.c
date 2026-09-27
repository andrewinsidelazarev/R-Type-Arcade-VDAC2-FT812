#include <string.h>
#include "pyz80_banked_image.h"

static uint8_t overlaps(const void *a, uint32_t size, const void *b, uint32_t extent)
{
    uintptr_t left=(uintptr_t)a,right=(uintptr_t)b;
    if(!a || !b || !size || !extent) return 0u;
    return left<=right ? right-left<size : left-right<extent;
}

uint8_t PyZ80Banked_Read(void *raw, uint32_t offset, uint8_t *destination, uint16_t size)
{
    PyZ80BankedImage *image=raw;
    const uint8_t *window;
    uint16_t chunk,within,token,page;
    uint8_t copied,restored;
    if(!image || image->busy || !image->map || !image->restore || (!destination && size) ||
        !image->size || image->size>4194304UL ||
        image->size>(256UL-image->first_page)*16384UL || offset>image->size || size>image->size-offset ||
        overlaps(destination,size,image,sizeof(*image))) return 0u;
#ifdef __SDCC
    if((uint32_t)(uintptr_t)destination+size>65536UL) return 0u; /* Reject wrapped near destination. */
#endif
    image->busy=1u;
    while(size) {
        page=image->first_page+(uint16_t)(offset>>14); /* SHR.U32 + ADD.U16; checked <=255. */
        within=(uint16_t)(offset & 16383UL); /* AND.U32: offset inside 16 KiB page. */
        chunk=16384u-within; if(chunk>size) chunk=size;
        window=0; token=0u;
        if(!image->map(image->context,(uint8_t)page,&window,&token)) { image->busy=0u;return 0u; }
        copied=window && !overlaps(destination,size,window,16384u);
#ifdef __SDCC
        if((uint32_t)(uintptr_t)window+16384UL>65536UL) copied=0u;
#endif
        if(copied) memcpy(destination,window+within,chunk);
        restored=image->restore(image->context,token);
        if(!copied || !restored) { image->busy=0u;return 0u; }
        offset+=chunk;destination+=chunk;size-=chunk; /* ADD/SUB: advance only copied extent. */
    }
    image->busy=0u;
    return 1u;
}
