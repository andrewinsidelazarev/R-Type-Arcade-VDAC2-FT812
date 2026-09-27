/* Байтовый объект с логическими адресами, не ограниченный окном Z80.
 * transfer отображает/восстанавливает банки и копирует не более четырёх байт.
 * Владелец гарантирует неизменность size и backing в течение вызова. */
#ifndef PYZ80_BUFFER_VIEW_H
#define PYZ80_BUFFER_VIEW_H
#include "pyz80_buffer_span.h"

typedef uint8_t (*PyBufferTransfer)(void *context,uint32_t position,
                                   uint8_t *data,uint8_t size,uint8_t write);
typedef struct {
    uint32_t size;
    uint8_t writable;
    void *context;
    PyBufferTransfer transfer;
} PyBufferView;
typedef struct { PyBufferView *items; uint16_t size; } PyBufferViewArray;
enum { PYBUF_BACKING=5, PYBUF_INDEX=6 };

static uint8_t PyView_Range(const PyBufferView *buffer,int32_t offset,
                            uint16_t size,uint32_t *position) {
    /* CMP до ADD: длина должна помещаться в положительный i32. */
    if(buffer->size>2147483647UL || !buffer->transfer) return PYBUF_BACKING;
    if(offset<0) offset+=(int32_t)buffer->size;
    if(offset<0 || (uint32_t)offset>buffer->size ||
       size>buffer->size-(uint32_t)offset) return PYBUF_BOUNDS;
    *position=(uint32_t)offset;
    return 0;
}

static uint8_t PyView_Index(PyBufferViewArray *array,int32_t index,PyBufferView **result) {
    if(index<0) index+=array->size;
    if(index<0 || index>=array->size) return PYBUF_INDEX;
    *result=&array->items[(uint16_t)index];
    return 0;
}

static uint8_t PyView_Read(const PyBufferView *buffer,uint32_t position,
                           uint8_t width,uint8_t big,uint8_t sign,int32_t *result) {
    uint8_t raw[4],error,index,cursor;
    uint32_t value=0;
    error=buffer->transfer(buffer->context,position,raw,width,0);
    if(error) return error;
    cursor=0;
    if(!big) cursor=width-1;
    for(index=0;index<width;++index) {
        value=(value<<8)|raw[cursor]; /* SHL/OR: собрать значение в порядке старших байтов. */
        if(big) ++cursor; else --cursor;
    }
    if(sign && width<4 && (value&((uint32_t)1<<(width*8-1))))
        *result=(int32_t)value-((int32_t)1<<(width*8));
    else *result=(int32_t)value;
    return 0;
}

static uint8_t PyView_Write(PyBufferView *buffer,uint32_t position,
                            uint8_t width,uint8_t big,uint8_t sign,int32_t value) {
    uint8_t raw[4],index,cursor=0;
    uint32_t bits=(uint32_t)value;
    if(width<4) {
        int32_t limit=(int32_t)1<<(width*8-(sign?1:0));
        if(value<(sign?-limit:0) || value>=limit) return PYBUF_INTEGER;
    }
    if(big) cursor=width-1;
    for(index=0;index<width;++index) {
        raw[cursor]=(uint8_t)bits;
        if(big) --cursor; else ++cursor;
        bits>>=8; /* LSR: перейти к следующему байту. */
    }
    return buffer->transfer(buffer->context,position,raw,width,1);
}
#endif
