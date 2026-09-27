/* Непрерывное отображённое окно bytes/bytearray для статического backend.
 * Владение физическими страницами остаётся у аппаратного адаптера. */
#ifndef PYZ80_BUFFER_SPAN_H
#define PYZ80_BUFFER_SPAN_H
#include <stdint.h>
#include <string.h>
typedef struct { uint8_t *data; uint16_t size; uint8_t writable; } PyBufferSpan;
typedef struct { uint8_t error; uint16_t line; } PyBufferFault;
enum { PYBUF_SOURCE_VALUE=1, PYBUF_BOUNDS=2, PYBUF_READONLY=3, PYBUF_INTEGER=4 };

static int32_t PyBuf_Min(int32_t a,int32_t b) { return a<b ? a : b; }
static int32_t PyBuf_Max(int32_t a,int32_t b) { return a>b ? a : b; }

static uint8_t PyBuf_Fail(PyBufferFault *fault,uint8_t error,uint16_t line) {
    fault->error=error; fault->line=line; return 0;
}
static uint8_t PyBuf_Range(const PyBufferSpan *buffer,int32_t offset,uint16_t size,uint16_t *position) {
    /* ADD длины для отрицательного смещения, затем проверка до сужения. */
    if(offset<0) offset+=buffer->size;
    if(offset<0 || offset>buffer->size || (int32_t)size>buffer->size-offset) return PYBUF_BOUNDS;
    *position=(uint16_t)offset;
    return 0;
}
static int32_t PyBuf_Read(const PyBufferSpan *buffer,uint16_t position,uint8_t width,uint8_t big,uint8_t sign) {
    uint8_t i;
    uint16_t cursor=position;
    uint32_t value=0;
    if(!big) { cursor+=width; --cursor; }
    for(i=0;i<width;++i) {
        /* SHL/OR собирают байты без зависимости от выравнивания и endian CPU. */
        value=(value<<8)|buffer->data[cursor];
        /* Отдельный INC/DEC: не смешивать разрядности в тернарном индексе. */
        if(big) ++cursor; else --cursor;
    }
    if(sign && width<4 && (value&((uint32_t)1<<(width*8-1))))
        return (int32_t)value-((int32_t)1<<(width*8));
    return (int32_t)value;
}
static uint8_t PyBuf_Write(PyBufferSpan *buffer,uint16_t position,uint8_t width,uint8_t big,uint8_t sign,int32_t value) {
    uint8_t i;
    uint16_t cursor=position;
    uint32_t bits=(uint32_t)value;
    if(width<4) {
        int32_t limit=(int32_t)1<<(width*8-(sign?1:0));
        if(value < (sign?-limit:0) || value>=limit) return PYBUF_INTEGER;
    }
    if(big) { cursor+=width; --cursor; }
    for(i=0;i<width;++i) {
        buffer->data[cursor]=(uint8_t)bits;
        if(big) --cursor; else ++cursor;
        bits>>=8; /* LSR выдаёт очередной байт дополнения до двух. */
    }
    return 0;
}
static uint8_t PyBuf_TryCopyRun(const PyBufferSpan *source,int32_t read,PyBufferSpan *target,int32_t write,uint16_t size) {
    uint16_t first,last;
    uint8_t *src,*dst;
    if(!target->writable || PyBuf_Range(source,read,size,&first) || PyBuf_Range(target,write,size,&last)) return 0;
    src=source->data+first;dst=target->data+last;
    /* Несвязанные адреса сравниваются как целые, не как указатели C.
     * При перекрытии остаётся исходный поэлементный путь, сохраняющий порядок. */
    if((uintptr_t)src<=(uintptr_t)dst) {
        if((uintptr_t)dst-(uintptr_t)src<size) return 0;
    } else if((uintptr_t)src-(uintptr_t)dst<size) return 0;
    memcpy(dst,src,size);
    return 1;
}
#endif
