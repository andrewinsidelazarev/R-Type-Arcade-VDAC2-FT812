/* Аппаратный ABI: команды вызывают методы сгенерированного класса. */
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
    output[0]=(uint16_t)StageScroll_foreground_x(&stage);
    output[1]=(uint16_t)StageScroll_background_x(&stage);
    output[2]=(uint16_t)StageScroll_progression(&stage);
    output[3]=(uint16_t)StageScroll_dispatch_progression(&stage);
    output[4]=(uint16_t)StageScroll_dispatch_foreground_x(&stage);
    output[5]=(uint16_t)StageScroll_dispatch_background_x(&stage);
    output[6]=(uint16_t)StageScroll_dispatch_foreground_delta(&stage);
    output[7]=(uint16_t)StageScroll_dispatch_background_delta(&stage);
}
