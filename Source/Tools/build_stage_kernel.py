"""Отдельный исполняемый банк полного скроллера для аппаратного backend.

Не публикует SPG и не заменяет работающую контрольную точку. Входные команды
вызывают исходные методы; на выходе — исходные свойства, не таблица кадров.
"""
import hashlib
import json
import re

from build_stage_record import ROOT,OUTPUT,main as generate
from build_translator_demo import command,validate_layout,write

BUILD=ROOT/'Build/StageKernel'


def main():
    generate(); BUILD.mkdir(parents=True,exist_ok=True)
    record=json.loads((ROOT/'Build/StageRecord/record_manifest.json').read_text(encoding='utf-8'))
    properties=[n['name'] for n in record['methods'] if n['kind']=='property']
    assert len(properties)==8
    bridge='''/* Аппаратный ABI: команды вызывают методы сгенерированного класса. */
#include "stage_scroll_generated.h"
static StageScroll stage;
void StageKernel_Dispatch(void) {
    PyRecordMaybeI32 foreground,background;
    volatile uint8_t *request=(volatile uint8_t *)0x2140;
    volatile uint16_t *arguments=(volatile uint16_t *)0x2142;
    volatile uint16_t *output=(volatile uint16_t *)0x2120;
    *(volatile uint8_t *)0x2130=0;
    foreground.value=arguments[0]; foreground.present=request[1]&1;
    background.value=arguments[1]; background.present=(request[1]>>1)&1;
    switch(request[0]) {
    case 0: StageScroll_init(&stage); break;
    case 1: StageScroll_advance(&stage); break;
    case 2: StageScroll_queue_object_velocity_write(&stage,&foreground,&background); break;
    case 3: StageScroll_queue_stage_transition_reset(&stage); break;
    case 4: StageScroll_queue_stage_init(&stage,arguments[0],arguments[1],arguments[2]); break;
    default: *(volatile uint8_t *)0x2130=1; return;
    }
'''
    bridge+='\n'.join(f'    output[{i}]=(uint16_t)StageScroll_{name}(&stage);' for i,name in enumerate(properties))+'\n}\n'
    write(OUTPUT/'stage_kernel_generated.c',bridge)
    flags=['E:/zx/sdcc/bin/sdcc.exe','-mz80','--std-c11','--sdcccall','1','--opt-code-speed','-I'+str(OUTPUT)]
    for name in ('stage_scroll','stage_kernel'):
        command([*flags,'-c',OUTPUT/(name+'_generated.c'),'-o',BUILD/(name+'.rel')])
    command([*flags,'--no-std-crt0','--code-loc','0xc000','--data-loc','0x3000',
             BUILD/'stage_scroll.rel',BUILD/'stage_kernel.rel','-o',BUILD/'stage.ihx'])
    map_text=(BUILD/'stage.map').read_text(encoding='latin1')
    layout=validate_layout(map_text)
    entry=int(re.search(r'^\s*([0-9A-Fa-f]{8})\s+_StageKernel_Dispatch\b',map_text,re.M)[1],16)
    command(['E:/zx/sdcc/bin/makebin.exe','-s','65536','-o','49152',BUILD/'stage.ihx',BUILD/'stage_kernel.bin'])
    report=dict(source_sha256=record['source_sha256'],entry=entry,physical_page=0xa2,memory_layout=layout,
        abi={'request':0x2140,'presence_bits':0x2141,'arguments_u16':0x2142,'output_u16':0x2120,'error':0x2130,
             'commands':{'0':'init','1':'advance','2':'queue_object_velocity_write','3':'queue_stage_transition_reset','4':'queue_stage_init'},
             'outputs':properties},spg_linked=False,
        binary_sha256=hashlib.sha256((BUILD/'stage_kernel.bin').read_bytes()).hexdigest())
    write(BUILD/'kernel_manifest.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Stage kernel:',layout,flush=True)


if __name__=='__main__': main()
