#include "tilemap_state_generated.c"
#include "tilemap_binding_generated.c"
#include "tilemap_kernel_abi_generated.h"
#include "pyz80_tsconf_bulk.h"
TilemapState kernel_state;
static PyTSBuffer rom_backing,initial_backing,table_backing,layer_backing[2];
static PyBufferView layer_views[2];
static uint8_t staging[960];
static void configure_view(PyBufferView *view,PyTSBuffer *backing,uint8_t first,uint16_t pages,uint32_t size,uint8_t writable) {
    backing->first_page=first; backing->pages=pages; backing->restore_page=0x30;
    view->size=size; view->writable=writable; view->context=backing; view->transfer=PyTSBuffer_BulkTransfer;
}
static void make_job(TilemapState *record,int32_t layer,int32_t source,int32_t destination) {
    tilemap_job.record=record; tilemap_job.resources=&tilemap_resources;
    tilemap_job.layer=layer; tilemap_job.source=source; tilemap_job.destination=destination;
}
uint8_t Tilemap_ApplyTable(TilemapState *record,int32_t layer,int32_t source,int32_t destination,uint8_t *error) {
    make_job(record,layer,source,destination);
    ((void (*)(void))0x4d00)();
    *error=tilemap_job.error; return tilemap_job.status;
}
uint8_t Tilemap_ApplyDecoder(PyBufferFault *fault,TilemapState *record,int32_t layer,int32_t source,int32_t destination) {
    make_job(record,layer,source,destination); tilemap_job.fault=fault;
    ((void (*)(void))0x4d20)();
    return tilemap_job.status;
}
static void scroll_command(uint8_t command) {
    *(volatile uint8_t *)0x2170=command; ((void (*)(void))0x4d40)();
}
void Tilemap_KernelDispatch(void) {
    PyBufferFault fault;
    uint8_t i,ok=1;
    int32_t result[2];
    int32_t a=*(volatile int32_t *)0x2144,b=*(volatile int32_t *)0x2148,c=*(volatile int32_t *)0x214c;
    fault.error=0; fault.line=0;
    switch(*(volatile uint8_t *)0x2140) {
    case 0:
        configure_view(&kernel_state.rom,&rom_backing,0xc0,64,0x100000UL,0);
        configure_view(&tilemap_resources.initial,&initial_backing,0x56,2,32768UL,0);
        configure_view(&tilemap_resources.table,&table_backing,0x40,21,335872UL,0);
        for(i=0;i<2;++i) configure_view(&layer_views[i],&layer_backing[i],0x58+i,1,16384UL,1);
        kernel_state.vram.items=layer_views; kernel_state.vram.size=2;
        tilemap_resources.scratch.data=staging; tilemap_resources.scratch.size=960; tilemap_resources.scratch.writable=1;
        ok=TilemapState___init__(&fault,&kernel_state); scroll_command(0); break;
    case 1: scroll_command(1); ok=TilemapState_advance(&fault,&kernel_state,&kernel_scroll); break;
    case 2: ok=TilemapState__crossing(&fault,&kernel_state,a,b,c); break;
    case 3:
        ok=TilemapState_state(&fault,&kernel_state,a,b,c,result);
        if(ok) { *(volatile int32_t *)0x2020=result[0]; *(volatile int32_t *)0x2024=result[1]; }
        break;
    case 4: ok=TilemapState__draw_strip(&fault,&kernel_state,a,b,c); break;
    case 5: ok=TilemapState__pump(&fault,&kernel_state); break;
    case 6: ok=TilemapState___init__(&fault,&kernel_state); break;
    case 7: scroll_command(2); break;
    case 8: scroll_command(3); break;
    default: ok=0; fault.error=255; break;
    }
    for(i=0;i<2;++i) {
        ((volatile int32_t *)0x2000)[i]=kernel_state.target[i];
        ((volatile int32_t *)0x2008)[i]=kernel_state.tracker[i];
        ((volatile int32_t *)0x2010)[i]=kernel_state.source[i];
    }
    *(volatile uint8_t *)0x2130=ok; *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
