/* Только отображение памяти и ABI; алгоритм полосы сгенерирован. */
#include "terrain_buffer_generated.h"
void Terrain_Dispatch(void) {
    PyBufferSpan vram,strip;
    PyBufferFault fault;
    vram.data=(uint8_t *)0x8000; vram.size=0x4000; vram.writable=1;
    strip.data=(uint8_t *)0x3200; strip.size=*(volatile uint16_t *)0x2142; strip.writable=0;
    *(volatile uint8_t *)0x2130=Terrain_ApplyStrip(&fault,&vram,*(volatile uint16_t *)0x2140,&strip);
    *(volatile uint8_t *)0x2131=fault.error;
    *(volatile uint16_t *)0x2132=fault.line;
}
