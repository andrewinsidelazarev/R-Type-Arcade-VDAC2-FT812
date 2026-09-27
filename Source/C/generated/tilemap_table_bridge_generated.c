/* Аппаратная связка теста: игровые формулы отсутствуют. */
#include "tilemap_table_generated.h"
#include "pyz80_tsconf_bulk.h"
static PyTSBuffer table_backing,layer_backing[2];
static PyBufferView table_view,layer_views[2];
static PyBufferViewArray layers;
static uint8_t staging[960];
static PyBufferSpan scratch;
void Table_Dispatch(void) {
    uint8_t i,error;
    table_backing.first_page=0x40; table_backing.pages=21; table_backing.restore_page=0x30;
    table_view.size=335872UL; table_view.writable=0;
    table_view.context=&table_backing; table_view.transfer=PyTSBuffer_BulkTransfer;
    for(i=0;i<2;++i) {
        layer_backing[i].first_page=0xa4+i; layer_backing[i].pages=1; layer_backing[i].restore_page=0x30;
        layer_views[i].size=16384; layer_views[i].writable=1;
        layer_views[i].context=&layer_backing[i]; layer_views[i].transfer=PyTSBuffer_BulkTransfer;
    }
    layers.items=layer_views; layers.size=2;
    scratch.data=staging; scratch.size=sizeof(staging); scratch.writable=1;
    *(volatile uint8_t *)0x2130=Tilemaps_TryTable(&table_view,&layers,&scratch,
        *(volatile int16_t *)0x2140,*(volatile int16_t *)0x2142,*(volatile int16_t *)0x2144,&error);
    *(volatile uint8_t *)0x2131=error;
}
void Table_BoundaryProbe(void) {
    uint8_t error;
    layer_backing[0].pages=2;
    error=PyTSBuffer_BulkTransfer(&table_backing,*(volatile uint32_t *)0x2150,staging,255,0);
    if(!error) error=PyTSBuffer_BulkTransfer(&layer_backing[0],*(volatile uint32_t *)0x2154,staging,255,1);
    *(volatile uint8_t *)0x2131=error;
}
