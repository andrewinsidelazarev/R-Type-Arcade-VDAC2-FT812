#include "stage_scroll_generated.c"
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
