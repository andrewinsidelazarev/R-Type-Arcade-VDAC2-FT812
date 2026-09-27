"""Исполняемые банки полного объекта карт, скроллера, таблиц и запасного декодера."""
import hashlib
import json
from pathlib import Path
import re
import struct

from build_tilemap_aggregate import ROOT,OUTPUT,BUILD as AGG_BUILD,main as build_aggregate
from build_tilemap_table import BUILD as TABLE_BUILD,main as build_table
from build_translator_demo import command,write,validate_layout

BUILD=ROOT/'Build/TilemapKernel'


def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    build_aggregate();build_table()
    table=json.loads((TABLE_BUILD/'manifest.json').read_text(encoding='utf-8'))
    binding='''#ifndef TILEMAP_KERNEL_ABI_H
#define TILEMAP_KERNEL_ABI_H
#include "tilemap_binding_generated.h"
typedef struct {
    PyBufferFault *fault;
    TilemapState *record;
    TilemapResources *resources;
    int32_t layer,source,destination;
    uint8_t error,status;
} TilemapJob;
#define tilemap_job (*(volatile TilemapJob *)0x2180)
#define kernel_scroll (*(StageScroll *)0x3100)
#endif
'''
    write(OUTPUT/'tilemap_kernel_abi_generated.h',binding)
    provider='''#ifndef TILEMAP_BANK_PROVIDER_H
#define TILEMAP_BANK_PROVIDER_H
#include "pyz80_tsconf_bulk.h"
/* Указатель функции из другого кодового банка недействителен до возврата.
 * На время вызова привязать байтовые операции к провайдеру текущего банка. */
static void Tilemap_BankCallbacks(PyBufferTransfer *saved,uint8_t restore) {
    PyBufferView *views[4];
    uint8_t i;
    views[0]=&tilemap_job.record->rom;
    views[1]=&tilemap_job.resources->table;
    views[2]=&tilemap_job.record->vram.items[0];
    views[3]=&tilemap_job.record->vram.items[1];
    for(i=0;i<4;++i) {
        if(restore) views[i]->transfer=saved[i];
        else { saved[i]=views[i]->transfer; views[i]->transfer=PyTSBuffer_BulkTransfer; }
    }
}
#endif
'''
    write(OUTPUT/'tilemap_bank_provider_generated.h',provider)
    cache='''#include "tilemap_table_generated.c"
#include "tilemap_kernel_abi_generated.h"
#include "tilemap_bank_provider_generated.h"
void Tilemap_CacheDispatch(void) {
    uint8_t error;
    PyBufferTransfer saved[4];
    TilemapResources *resources=tilemap_job.resources;
    Tilemap_BankCallbacks(saved,0);
    tilemap_job.status=Tilemaps_TryTable(&resources->table,&tilemap_job.record->vram,&resources->scratch,
        tilemap_job.layer,tilemap_job.source,tilemap_job.destination,&error);
    tilemap_job.error=error;
    Tilemap_BankCallbacks(saved,1);
}
'''
    fallback='''#include "tilemap_buffer_generated.c"
#include "tilemap_kernel_abi_generated.h"
#include "tilemap_bank_provider_generated.h"
void Tilemap_DecoderDispatch(void) {
    PyBufferTransfer saved[4];
    TilemapState *record=tilemap_job.record;
    Tilemap_BankCallbacks(saved,0);
    tilemap_job.status=Tilemaps_DrawStrip(tilemap_job.fault,&record->rom,&record->vram,
        tilemap_job.layer,tilemap_job.source,tilemap_job.destination);
    Tilemap_BankCallbacks(saved,1);
}
'''
    scroll='''#include "stage_scroll_generated.c"
void Tilemap_ScrollDispatch(void) {
    StageScroll *scroll=(StageScroll *)0x3100;
    PyRecordMaybeI32 foreground,background;
    foreground.value=*(volatile int32_t *)0x2144; foreground.present=*(volatile uint8_t *)0x2142&1;
    background.value=*(volatile int32_t *)0x2148; background.present=(*(volatile uint8_t *)0x2142>>1)&1;
    switch(*(volatile uint8_t *)0x2170) {
    case 0: StageScroll_init(scroll); break;
    case 1: StageScroll_advance(scroll); break;
    case 2: StageScroll_queue_object_velocity_write(scroll,&foreground,&background); break;
    case 3: StageScroll_queue_stage_transition_reset(scroll); break;
    }
}
'''
    state='''#include "tilemap_state_generated.c"
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
        configure_view(&tilemap_resources.table,&table_backing,0x40,TABLE_PAGES,TABLE_BYTES,0);
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
'''.replace('TABLE_PAGES',str((table['table_bytes']+16383)//16384)).replace('TABLE_BYTES',str(table['table_bytes'])+'UL')
    modules={'state':(state,0xa6,'Tilemap_KernelDispatch'), 'cache':(cache,0xa8,'Tilemap_CacheDispatch'),
             'decoder':(fallback,0xa7,'Tilemap_DecoderDispatch'),'scroll':(scroll,0xa2,'Tilemap_ScrollDispatch')}
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed',
           '-I'+str(OUTPUT),'-I'+str(ROOT/'Source/C/python_vm')]
    banks={}
    for name,(source,page,symbol) in modules.items():
        path=OUTPUT/('tilemap_bank_'+name+'_generated.c');write(path,source)
        command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x2200','-Wl-b_HOME=0xF800',
                 path,'-o',BUILD/(name+'.ihx')])
        mapping=(BUILD/(name+'.map')).read_text(encoding='latin1')
        layout=validate_layout(mapping,require_data=name=='state')
        if name!='state' and '_DATA' in layout: raise RuntimeError('Скрытое состояние в служебном банке')
        if name=='state' and layout['_DATA']['end']>0x3100: raise RuntimeError('Пересечение с объектом скроллера')
        entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_'+symbol+r'\b',mapping,re.M)[1],16)
        command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',BUILD/(name+'.ihx'),BUILD/(name+'.bin')])
        banks[name]=dict(physical_page=page,entry=entry,memory_layout=layout,
                        sha256=hashlib.sha256((BUILD/(name+'.bin')).read_bytes()).hexdigest())
    thunks=bytearray(0x60)
    for offset,name in [(0,'cache'),(0x20,'decoder'),(0x40,'scroll')]:
        bank=banks[name]
        code=b'\x3e'+bytes([bank['physical_page']])+b'\x32\x13\x04\xcd'+struct.pack('<H',bank['entry'])+b'\x3e\xa6\x32\x13\x04\xc9'
        thunks[offset:offset+len(code)]=code
    write(BUILD/'thunks.bin',thunks)
    resources=[dict(name='table',path=str(TABLE_BUILD/'records.bin'),first_page=0x40,pages=(table['table_bytes']+16383)//16384),
               dict(name='initial',path=str(AGG_BUILD/'initial_vram.bin'),first_page=0x56,pages=2),
               dict(name='rom',path=str(ROOT/'Assets/Converted/Arcade/RTYPE_MAINCPU_REGION.bin'),first_page=0xc0,pages=64)]
    occupied={0,5,0x30,0x58,0x59,*[bank['physical_page'] for bank in banks.values()]}
    for resource in resources:
        resource['sha256']=hashlib.sha256(Path(resource['path']).read_bytes()).hexdigest()
        pages=set(range(resource['first_page'],resource['first_page']+resource['pages']))
        if occupied&pages or max(pages)>255: raise RuntimeError('Пересечение физических банков')
        occupied.update(pages)
    manifest=dict(banks=banks,resources=resources,thunk_address=0x4d00,stack=0x3fff,
        scroll_address=0x3100,vram_pages=[0x58,0x59],state_request=0x2140,scalar_output=0x2000,
        state_result=0x2020,status=0x2130,error=0x2131,spg_linked=False,
        aggregate_manifest_sha256=hashlib.sha256((AGG_BUILD/'manifest.json').read_bytes()).hexdigest())
    write(BUILD/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('Банки полного объекта:',{name:bank['memory_layout'] for name,bank in banks.items()},flush=True)
    return manifest


if __name__=='__main__': main()
