#include "pyz80_ft812.h"

/* Page-F1 import proxy for the only F1 -> F2 edge in the draw bundle.
 * The resident gate owns the MMU transition and preserves the original
 * __sdcccall(0) stack.  This source is linked only into the placement proof;
 * production callback/final-image binding is intentionally still blocked. */
#if defined(__SDCC)
uint8_t PyZ80FT_BuildSpriteBatchFast(
        volatile PyZ80FtQueue *queue,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t remaining_dl_words)
    PYZ80_CALL0 __naked
{
    queue; records; count; remaining_dl_words;
    __asm
        jp 0x07A0
    __endasm;
}
#endif
