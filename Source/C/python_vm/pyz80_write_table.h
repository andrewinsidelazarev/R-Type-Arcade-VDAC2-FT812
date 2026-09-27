/* Конечная таблица записей. 0: промах без записей; 1: успех; 2: сбой backing.
 * Ресурс проверен загрузчиком по хешу; scratch, таблица и цель не пересекаются.
 * При результате 2 запрещено повторять исходный метод: запись могла начаться. */
#ifndef PYZ80_WRITE_TABLE_H
#define PYZ80_WRITE_TABLE_H
#include "pyz80_buffer_view.h"

static uint8_t PyWriteTable_Apply(PyBufferView *table,uint32_t position,
    PyBufferView *target,PyBufferSpan *scratch,const uint16_t *runs,
    uint16_t count,uint16_t bytes,uint8_t *error) {
    uint16_t i,cursor,chunk;
    *error=0;
    if(!scratch->writable || !scratch->data || scratch->size<bytes ||
       !target->writable || !target->transfer || !table->transfer ||
       position>table->size || bytes>table->size-position) return 0;
    /* CMP всех диапазонов до первой записи: промах не меняет целевое состояние. */
    cursor=0;
    for(i=0;i<count;++i) {
        if(runs[i*2]>target->size || runs[i*2+1]>target->size-runs[i*2] ||
           runs[i*2+1]>255 || cursor>bytes || runs[i*2+1]>bytes-cursor) return 0;
        cursor+=runs[i*2+1];
    }
    if(cursor!=bytes) return 0;
    cursor=0;
    while(cursor<bytes) {
        chunk=bytes-cursor;
        if(chunk>240) chunk=240;
        *error=table->transfer(table->context,position+cursor,scratch->data+cursor,(uint8_t)chunk,0);
        if(*error) return 2;
        cursor+=chunk; /* ADD: сместить источник и резидентный приёмник. */
    }
    cursor=0;
    for(i=0;i<count;++i) {
        *error=target->transfer(target->context,runs[i*2],scratch->data+cursor,(uint8_t)runs[i*2+1],1);
        if(*error) return 2;
        cursor+=runs[i*2+1];
    }
    return 1;
}
#endif
