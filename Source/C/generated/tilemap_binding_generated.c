/* Ресурсная связка; вычисления игры находятся в AST-модулях. */
#include "tilemap_binding_generated.h"
TilemapResources tilemap_resources;
PY_AGGREGATE_API uint8_t TilemapState___init__(PyBufferFault *fault,TilemapState *record) {
    uint8_t i,error;
    uint16_t position,chunk;
    PyBufferView *target;
    fault->error=0; fault->line=0;
    if(record->vram.size!=2 || !record->vram.items || !tilemap_resources.initial.transfer ||
       tilemap_resources.initial.size!=32768UL || !tilemap_resources.scratch.data ||
       tilemap_resources.scratch.size<240 || !tilemap_resources.scratch.writable)
        return PyBuf_Fail(fault,PYBUF_BACKING,309);
    for(i=0;i<2;++i) {
        target=&record->vram.items[i];
        if(target->size!=16384UL || !target->writable || !target->transfer)
            return PyBuf_Fail(fault,PYBUF_BACKING,309);
    }
    for(i=0;i<2;++i) {
        target=&record->vram.items[i]; position=0;
        while(position<16384u) {
            chunk=16384u-position;
            if(chunk>240) chunk=240;
            error=tilemap_resources.initial.transfer(tilemap_resources.initial.context,
                (uint32_t)i*16384UL+position,tilemap_resources.scratch.data,(uint8_t)chunk,0);
            if(error) return PyBuf_Fail(fault,error,309);
            error=target->transfer(target->context,position,tilemap_resources.scratch.data,(uint8_t)chunk,1);
            if(error) return PyBuf_Fail(fault,error,309);
            position+=chunk; /* ADD: следующая часть образа начального состояния. */
        }
    }
    record->target[0]=128L;
    record->target[1]=144L;
    record->tracker[0]=128L;
    record->tracker[1]=144L;
    record->source[0]=80L;
    record->source[1]=90L;
    tilemap_resources.hits=0; tilemap_resources.misses=0;
    return 1;
}
PY_AGGREGATE_API uint8_t TilemapState__draw_strip(PyBufferFault *fault,TilemapState *record,
    int32_t layer,int32_t source,int32_t destination) {
    uint8_t error,status;
    fault->error=0; fault->line=0;
    status=Tilemap_ApplyTable(record,layer,source,destination,&error);
    if(status==1) { ++tilemap_resources.hits; return 1; }
    if(status==2) return PyBuf_Fail(fault,error,361);
    ++tilemap_resources.misses;
    return Tilemap_ApplyDecoder(fault,record,layer,source,destination);
}
