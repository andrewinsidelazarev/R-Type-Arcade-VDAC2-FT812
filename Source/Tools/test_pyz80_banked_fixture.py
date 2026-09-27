"""Host-only physical RAM/window model, shared by native banked tests."""
from __future__ import annotations


def banked_fixture(blob: bytes) -> str:
    return r'''
#include "pyz80_banked_image.h"
#include "pyz80_target_banked_tables.h"
static uint8_t bank_source[] = {'''+','.join(map(str,blob))+r'''};
static uint8_t bank_window[16384];
static unsigned bank_maps,bank_restores;
static uint8_t current_bank=3,fail_map,fail_restore,reenter;
static PyZ80BankedImage bank_image;
static uint8_t bank_restore(void *raw,uint16_t token) {
    (void)raw;++bank_restores;
    memset(bank_window,0xDD,sizeof(bank_window));current_bank=(uint8_t)token;
    return !fail_restore;
}
static uint8_t bank_map(void *raw,uint8_t page,const uint8_t **window,uint16_t *token) {
    uint32_t offset;uint16_t count;uint8_t byte;
    (void)raw;
    if(fail_map)return 0;
    if(page<7)return 0;
    offset=(uint32_t)(page-7)*16384;
    if(offset>=sizeof(bank_source))return 0;
    ++bank_maps;*token=current_bank;current_bank=page;
    memset(bank_window,0xCC,sizeof(bank_window));
    count=sizeof(bank_source)-offset>16384 ? 16384 : (uint16_t)(sizeof(bank_source)-offset);
    memcpy(bank_window,bank_source+offset,count);*window=bank_window;
    if(reenter && PyZ80Banked_Read(&bank_image,0,&byte,1))return 0;
    return 1;
}
static void bank_init(void) {
    bank_image.map=bank_map;bank_image.restore=bank_restore;
    bank_image.context=0;bank_image.size=sizeof(bank_source);bank_image.first_page=7;bank_image.busy=0;
}
'''
