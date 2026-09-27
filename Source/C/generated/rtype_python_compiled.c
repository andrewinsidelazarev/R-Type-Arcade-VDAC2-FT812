/* Сгенерировано Python AST -> typed IR -> C11. Не редактировать. */
#include <stdint.h>
#if !defined(__SDCC) || (__SDCCCALL != 1)
#error "pyz80_compiler requires SDCC module ABI version 1"
#endif

uint16_t RTypePyCompiled_AdvancePitch(uint16_t pyz80_arg_pitch, uint16_t pyz80_arg_up, uint16_t pyz80_arg_down) __sdcccall(0)
{
    uint16_t pitch = (uint16_t)pyz80_arg_pitch;
    uint8_t up = (uint8_t)pyz80_arg_up;
    uint8_t down = (uint8_t)pyz80_arg_down;
    uint8_t pyz80_v0;
    uint8_t pyz80_v1;
    uint8_t pyz80_v2;
    uint8_t pyz80_v3;
    uint8_t pyz80_v4;
    uint8_t pyz80_v5;
    uint8_t pyz80_v6;
    int8_t pyz80_v7;
    uint8_t pyz80_v8;
    uint8_t pyz80_v9;
    uint8_t pyz80_v10;
    uint8_t pyz80_v11;
    uint8_t pyz80_v12;
    uint8_t pyz80_v13;
    uint8_t pyz80_v14;
    uint8_t pyz80_v15;
    uint8_t pyz80_v16;
    uint8_t pyz80_v17;
    uint8_t pyz80_v18;
    uint8_t pyz80_v19;
    uint8_t pyz80_v20;
    uint8_t pyz80_v21;
    uint8_t pyz80_v22;
    uint8_t pyz80_v23;
    uint8_t pyz80_v24;
    uint8_t pyz80_v25;
    uint8_t pyz80_v26;
    uint8_t pyz80_v27;

pyz80_RTypePyCompiled_AdvancePitch_entry_000:
    pyz80_v0 = up;
    pyz80_v1 = down;
    pyz80_v2 = (uint8_t)((uint16_t)(pyz80_v0) != (uint16_t)(pyz80_v1));
    if (pyz80_v2) goto pyz80_RTypePyCompiled_AdvancePitch_if_true_001;
    goto pyz80_RTypePyCompiled_AdvancePitch_if_false_002;
pyz80_RTypePyCompiled_AdvancePitch_if_true_001:
    pyz80_v3 = up;
    pyz80_v4 = (uint8_t)(0);
    pyz80_v5 = pitch;
    pyz80_v6 = (uint8_t)(1);
    pyz80_v7 = pyz80_v5 - pyz80_v6;
    pyz80_v8 = ((int16_t)(pyz80_v4) >= (int16_t)(pyz80_v7)) ? pyz80_v4 : pyz80_v7;
    pyz80_v9 = (uint8_t)(39);
    pyz80_v10 = pitch;
    pyz80_v11 = (uint8_t)(1);
    pyz80_v12 = pyz80_v10 + pyz80_v11;
    pyz80_v13 = ((uint16_t)(pyz80_v9) <= (uint16_t)(pyz80_v12)) ? pyz80_v9 : pyz80_v12;
    pyz80_v14 = pyz80_v3 ? pyz80_v8 : pyz80_v13;
    return pyz80_v14;
pyz80_RTypePyCompiled_AdvancePitch_if_false_002:
    goto pyz80_RTypePyCompiled_AdvancePitch_if_merge_003;
pyz80_RTypePyCompiled_AdvancePitch_if_merge_003:
    pyz80_v15 = pitch;
    pyz80_v16 = (uint8_t)(20);
    pyz80_v17 = (uint8_t)((uint16_t)(pyz80_v15) < (uint16_t)(pyz80_v16));
    if (pyz80_v17) goto pyz80_RTypePyCompiled_AdvancePitch_if_true_004;
    goto pyz80_RTypePyCompiled_AdvancePitch_if_false_005;
pyz80_RTypePyCompiled_AdvancePitch_if_true_004:
    pyz80_v18 = pitch;
    pyz80_v19 = (uint8_t)(1);
    pyz80_v20 = pyz80_v18 + pyz80_v19;
    return pyz80_v20;
pyz80_RTypePyCompiled_AdvancePitch_if_false_005:
    goto pyz80_RTypePyCompiled_AdvancePitch_if_merge_006;
pyz80_RTypePyCompiled_AdvancePitch_if_merge_006:
    pyz80_v21 = pitch;
    pyz80_v22 = (uint8_t)(20);
    pyz80_v23 = (uint8_t)((uint16_t)(pyz80_v21) > (uint16_t)(pyz80_v22));
    if (pyz80_v23) goto pyz80_RTypePyCompiled_AdvancePitch_if_true_007;
    goto pyz80_RTypePyCompiled_AdvancePitch_if_false_008;
pyz80_RTypePyCompiled_AdvancePitch_if_true_007:
    pyz80_v24 = pitch;
    pyz80_v25 = (uint8_t)(1);
    pyz80_v26 = pyz80_v24 - pyz80_v25;
    return pyz80_v26;
pyz80_RTypePyCompiled_AdvancePitch_if_false_008:
    goto pyz80_RTypePyCompiled_AdvancePitch_if_merge_009;
pyz80_RTypePyCompiled_AdvancePitch_if_merge_009:
    pyz80_v27 = pitch;
    return pyz80_v27;
}

void RTypePyABI_Bridge_000(void) __naked
{
    __asm
        ld hl, #0x0000
        ld a, e
        and a, #0x0c
        cp a, #0x08
        jr nz, 80002$
        inc l
80002$:
        push hl
        ld hl, #0x0000
        ld a, e
        and a, #0x0c
        cp a, #0x04
        jr nz, 80001$
        inc l
80001$:
        push hl
        ld l, d
        ld h, #0x00
        push hl
        call _RTypePyCompiled_AdvancePitch
        pop bc
        pop bc
        pop bc
        ld a, l
        ret
    __endasm;
}
