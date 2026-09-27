#ifndef DEMO_LINE_BUDGET_H
#define DEMO_LINE_BUDGET_H
#include <stdint.h>
#include <string.h>

/* Один бит на физическую строку: пропускаются пустые группы, но сами строки
   не укрупняются. Разности очищаются при чтении, а не полным memset на кадр. */
static int16_t line_changes[768];
static uint8_t line_masks[96];

static void line_reset(void) {
    memset(line_changes,0,sizeof(line_changes));
    memset(line_masks,0,sizeof(line_masks));
}

static void line_event(uint16_t row,int16_t change) {
    /* Конец интервала за последней видимой строкой не влияет на максимум. */
    if(row==768) return;
    if(row>768) { demo_fault=9; return; }
    line_changes[row]+=change;
    line_masks[row>>3]|=(uint8_t)(1u<<(row&7));
}

static uint16_t line_peak(void) {
    uint8_t group,bits;
    int16_t *base=line_changes,*cursor;
    int16_t cost=0;
    uint16_t peak=0;
    for(group=0;group<96;++group) {
        bits=line_masks[group];
        if(bits) {
            line_masks[group]=0;
            cursor=base;
            do {
                if(bits&1) {
                    cost+=*cursor;
                    *cursor=0;
                    if(cost>peak) peak=cost;
                }
                ++cursor;
                bits>>=1;
            } while(bits);
        }
        base+=8;
    }
    return peak;
}
#endif
