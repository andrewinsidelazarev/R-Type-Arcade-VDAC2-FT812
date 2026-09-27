#include "pyz80_ft812.h"

/* Stable VMA #8000 entry for the resident F1 -> F2 tail gate.  The placement
 * checker links this object first and rejects any link map where the symbol
 * moves.  The jump is a tail jump so the real batch builder returns directly
 * through the resident gate already present at SP+0. */
#if defined(__SDCC)
uint8_t PyZ80DrawBank1_BuildSpriteBatchFast(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0 __naked
{
    queue; records; count; remaining_dl_words;
    __asm
        .globl _PyZ80FT_BuildSpriteBatchFast
        jp _PyZ80FT_BuildSpriteBatchFast
    __endasm;
}
#endif
