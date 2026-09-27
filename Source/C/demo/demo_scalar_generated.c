/* Сгенерировано Python AST -> typed IR -> C11. Не редактировать. */
#include <stdint.h>
#if !defined(__SDCC) || (__SDCCCALL != 1)
#error "pyz80_compiler requires SDCC module ABI version 1"
#endif

uint8_t advance_pitch(uint16_t pyz80_arg_pitch, uint16_t pyz80_arg_up, uint16_t pyz80_arg_down) __sdcccall(0)
{
    uint8_t pitch = (uint8_t)pyz80_arg_pitch;
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

pyz80_advance_pitch_entry_000:
    pyz80_v0 = up;
    pyz80_v1 = down;
    pyz80_v2 = (uint8_t)((uint16_t)(pyz80_v0) != (uint16_t)(pyz80_v1));
    if (pyz80_v2) goto pyz80_advance_pitch_if_true_001;
    goto pyz80_advance_pitch_if_false_002;
pyz80_advance_pitch_if_true_001:
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
pyz80_advance_pitch_if_false_002:
    goto pyz80_advance_pitch_if_merge_003;
pyz80_advance_pitch_if_merge_003:
    pyz80_v15 = pitch;
    pyz80_v16 = (uint8_t)(20);
    pyz80_v17 = (uint8_t)((uint16_t)(pyz80_v15) < (uint16_t)(pyz80_v16));
    if (pyz80_v17) goto pyz80_advance_pitch_if_true_004;
    goto pyz80_advance_pitch_if_false_005;
pyz80_advance_pitch_if_true_004:
    pyz80_v18 = pitch;
    pyz80_v19 = (uint8_t)(1);
    pyz80_v20 = pyz80_v18 + pyz80_v19;
    return pyz80_v20;
pyz80_advance_pitch_if_false_005:
    goto pyz80_advance_pitch_if_merge_006;
pyz80_advance_pitch_if_merge_006:
    pyz80_v21 = pitch;
    pyz80_v22 = (uint8_t)(20);
    pyz80_v23 = (uint8_t)((uint16_t)(pyz80_v21) > (uint16_t)(pyz80_v22));
    if (pyz80_v23) goto pyz80_advance_pitch_if_true_007;
    goto pyz80_advance_pitch_if_false_008;
pyz80_advance_pitch_if_true_007:
    pyz80_v24 = pitch;
    pyz80_v25 = (uint8_t)(1);
    pyz80_v26 = pyz80_v24 - pyz80_v25;
    return pyz80_v26;
pyz80_advance_pitch_if_false_008:
    goto pyz80_advance_pitch_if_merge_009;
pyz80_advance_pitch_if_merge_009:
    pyz80_v27 = pitch;
    return pyz80_v27;
}

uint8_t advance_wave_charge(uint16_t pyz80_arg_charge) __sdcccall(0)
{
    uint8_t charge = (uint8_t)pyz80_arg_charge;
    uint8_t pyz80_v0;
    uint8_t pyz80_v1;
    uint8_t pyz80_v2;
    uint8_t pyz80_v3;
    uint8_t pyz80_v4;

pyz80_advance_wave_charge_entry_000:
    pyz80_v0 = (uint8_t)(128);
    pyz80_v1 = charge;
    pyz80_v2 = (uint8_t)(2);
    pyz80_v3 = pyz80_v1 + pyz80_v2;
    pyz80_v4 = ((uint16_t)(pyz80_v0) <= (uint16_t)(pyz80_v3)) ? pyz80_v0 : pyz80_v3;
    return pyz80_v4;
}

uint8_t wave_power(uint16_t pyz80_arg_charge) __sdcccall(0)
{
    uint8_t charge = (uint8_t)pyz80_arg_charge;
    uint8_t pyz80_v0;
    uint8_t pyz80_v1;
    uint8_t pyz80_v2;
    uint8_t pyz80_v3;
    uint8_t pyz80_v4;
    uint8_t pyz80_v5;
    uint8_t pyz80_v6;
    uint8_t pyz80_v7;
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

pyz80_wave_power_entry_000:
    pyz80_v0 = charge;
    pyz80_v1 = (uint8_t)(24);
    pyz80_v2 = (uint8_t)((uint16_t)(pyz80_v0) < (uint16_t)(pyz80_v1));
    if (pyz80_v2) goto pyz80_wave_power_if_true_001;
    goto pyz80_wave_power_if_false_002;
pyz80_wave_power_if_true_001:
    pyz80_v3 = (uint8_t)(0);
    return pyz80_v3;
pyz80_wave_power_if_false_002:
    goto pyz80_wave_power_if_merge_003;
pyz80_wave_power_if_merge_003:
    pyz80_v4 = charge;
    pyz80_v5 = (uint8_t)(48);
    pyz80_v6 = (uint8_t)((uint16_t)(pyz80_v4) < (uint16_t)(pyz80_v5));
    if (pyz80_v6) goto pyz80_wave_power_if_true_004;
    goto pyz80_wave_power_if_false_005;
pyz80_wave_power_if_true_004:
    pyz80_v7 = (uint8_t)(4);
    return pyz80_v7;
pyz80_wave_power_if_false_005:
    goto pyz80_wave_power_if_merge_006;
pyz80_wave_power_if_merge_006:
    pyz80_v8 = charge;
    pyz80_v9 = (uint8_t)(72);
    pyz80_v10 = (uint8_t)((uint16_t)(pyz80_v8) < (uint16_t)(pyz80_v9));
    if (pyz80_v10) goto pyz80_wave_power_if_true_007;
    goto pyz80_wave_power_if_false_008;
pyz80_wave_power_if_true_007:
    pyz80_v11 = (uint8_t)(8);
    return pyz80_v11;
pyz80_wave_power_if_false_008:
    goto pyz80_wave_power_if_merge_009;
pyz80_wave_power_if_merge_009:
    pyz80_v12 = charge;
    pyz80_v13 = (uint8_t)(80);
    pyz80_v14 = (uint8_t)((uint16_t)(pyz80_v12) < (uint16_t)(pyz80_v13));
    if (pyz80_v14) goto pyz80_wave_power_if_true_010;
    goto pyz80_wave_power_if_false_011;
pyz80_wave_power_if_true_010:
    pyz80_v15 = (uint8_t)(12);
    return pyz80_v15;
pyz80_wave_power_if_false_011:
    goto pyz80_wave_power_if_merge_012;
pyz80_wave_power_if_merge_012:
    pyz80_v16 = charge;
    pyz80_v17 = (uint8_t)(104);
    pyz80_v18 = (uint8_t)((uint16_t)(pyz80_v16) < (uint16_t)(pyz80_v17));
    if (pyz80_v18) goto pyz80_wave_power_if_true_013;
    goto pyz80_wave_power_if_false_014;
pyz80_wave_power_if_true_013:
    pyz80_v19 = (uint8_t)(16);
    return pyz80_v19;
pyz80_wave_power_if_false_014:
    goto pyz80_wave_power_if_merge_015;
pyz80_wave_power_if_merge_015:
    pyz80_v20 = (uint8_t)(20);
    return pyz80_v20;
}

uint8_t wave_power_tier(uint16_t pyz80_arg_power) __sdcccall(0)
{
    uint8_t power = (uint8_t)pyz80_arg_power;
    uint8_t pyz80_v0;
    uint8_t pyz80_v1;
    uint8_t pyz80_v2;
    uint8_t pyz80_v3;
    uint8_t pyz80_v4;
    uint8_t pyz80_v5;
    uint8_t pyz80_v6;
    uint8_t pyz80_v7;
    uint8_t pyz80_v8;
    uint8_t pyz80_v9;
    uint8_t pyz80_v10;

pyz80_wave_power_tier_entry_000:
    pyz80_v0 = power;
    pyz80_v1 = (uint8_t)(0);
    pyz80_v2 = (uint8_t)((uint16_t)(pyz80_v0) <= (uint16_t)(pyz80_v1));
    if (pyz80_v2) goto pyz80_wave_power_tier_if_true_001;
    goto pyz80_wave_power_tier_if_false_002;
pyz80_wave_power_tier_if_true_001:
    pyz80_v3 = (uint8_t)(0);
    return pyz80_v3;
pyz80_wave_power_tier_if_false_002:
    goto pyz80_wave_power_tier_if_merge_003;
pyz80_wave_power_tier_if_merge_003:
    pyz80_v4 = power;
    pyz80_v5 = (uint8_t)(1);
    pyz80_v6 = pyz80_v4 - pyz80_v5;
    pyz80_v7 = (uint8_t)(28);
    pyz80_v8 = pyz80_v6 & pyz80_v7;
    pyz80_v9 = (uint8_t)(4);
    pyz80_v10 = pyz80_v8 + pyz80_v9;
    return pyz80_v10;
}

uint8_t beam_animation_phase(uint16_t pyz80_arg_m72_frame_counter) __sdcccall(0)
{
    uint16_t m72_frame_counter = (uint16_t)pyz80_arg_m72_frame_counter;
    uint16_t pyz80_v0;
    uint8_t pyz80_v1;
    uint8_t pyz80_v2;
    uint8_t pyz80_v3;
    uint8_t pyz80_v4;

pyz80_beam_animation_phase_entry_000:
    pyz80_v0 = m72_frame_counter;
    pyz80_v1 = (uint8_t)(28);
    pyz80_v2 = pyz80_v0 & pyz80_v1;
    pyz80_v3 = (uint8_t)(2);
    pyz80_v4 = pyz80_v2 >> pyz80_v3;
    return pyz80_v4;
}
