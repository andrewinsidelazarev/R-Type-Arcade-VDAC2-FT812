/* ABI теста; игровой алгоритм находится только в сгенерированном методе. */
#include "tilemap_buffer_generated.h"
#include "tilemap_buffer_probe_generated.h"
#include "pyz80_tsconf_buffer.h"
static PyTSBuffer rom_backing,layer_backing[2];
static PyBufferView rom_view,layer_views[2];
static PyBufferViewArray layers;
void Tilemap_Dispatch(void) {
    PyBufferFault fault;
    uint8_t i;
    rom_backing.first_page=0x40; rom_backing.pages=64; rom_backing.restore_page=0x30;
    rom_view.size=0x100000UL; rom_view.writable=0; rom_view.context=&rom_backing; rom_view.transfer=PyTSBuffer_Transfer;
    for(i=0;i<2;++i) {
        layer_backing[i].first_page=0xa4+i; layer_backing[i].pages=1; layer_backing[i].restore_page=0x30;
        layer_views[i].size=0x4000; layer_views[i].writable=1;
        layer_views[i].context=&layer_backing[i]; layer_views[i].transfer=PyTSBuffer_Transfer;
    }
    layers.items=layer_views; layers.size=2;
    *(volatile uint8_t *)0x2130=Tilemaps_DrawStrip(&fault,&rom_view,&layers,
        *(volatile int16_t *)0x2140,*(volatile uint16_t *)0x2142,*(volatile uint16_t *)0x2144);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
void Tilemap_Probe(void) {
    PyBufferFault fault;
    layer_backing[0].pages=2; layer_views[0].size=0x8000;
    *(volatile uint8_t *)0x2130=Buffer_CopyWord(&fault,&rom_view,&layer_views[0],
        *(volatile int32_t *)0x2150,*(volatile int32_t *)0x2154);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
