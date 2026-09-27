#include "demo_platform.h"
uint8_t advance_pitch(uint16_t pyz80_arg_pitch, uint16_t pyz80_arg_up, uint16_t pyz80_arg_down) __sdcccall(0);
uint8_t advance_wave_charge(uint16_t pyz80_arg_charge) __sdcccall(0);
uint8_t wave_power(uint16_t pyz80_arg_charge) __sdcccall(0);
uint8_t wave_power_tier(uint16_t pyz80_arg_power) __sdcccall(0);
uint8_t beam_animation_phase(uint16_t pyz80_arg_m72_frame_counter) __sdcccall(0);
void translated_move(Player *p, Inputs *in) {
    int32_t direction;
    int32_t down;
    int32_t up;
    /* Python: строка 761; If. */
    if (in->left) {
        /* Python: строка 762; AugAssign. */
        p->player_x = (p->player_x - 853L); /* Вычислить, затем записать. */
    }
    /* Python: строка 763; If. */
    if (in->right) {
        /* Python: строка 764; AugAssign. */
        p->player_x = (p->player_x + 853L); /* Вычислить, затем записать. */
    }
    /* Python: строка 765; Assign. */
    up = in->up; /* Вычислить, затем записать. */
    /* Python: строка 766; Assign. */
    down = in->down; /* Вычислить, затем записать. */
    /* Python: строка 767; If. */
    if (up) {
        /* Python: строка 768; AugAssign. */
        p->player_y = (p->player_y - 960L); /* Вычислить, затем записать. */
    }
    /* Python: строка 769; If. */
    if (down) {
        /* Python: строка 770; AugAssign. */
        p->player_y = (p->player_y + 960L); /* Вычислить, затем записать. */
    }
    /* Python: строка 771; Assign. */
    direction = ((((in->right ? 1L : 0L) | (in->left ? 2L : 0L)) | (in->down ? 4L : 0L)) | (in->up ? 8L : 0L)); /* Вычислить, затем записать. */
    /* Python: строка 783; Assign. */
    p->player_pitch = advance_pitch(p->player_pitch, up, down); /* Вычислить, затем записать. */
    /* Python: строка 784; Assign. */
    p->player_x = py_min(py_max(p->player_x, 0L), ((640L - 53L) * 256L)); /* Вычислить, затем записать. */
    /* Python: строка 785; Assign. */
    p->player_y = py_min(py_max(p->player_y, 0L), ((450L - 28L) * 256L)); /* Вычислить, затем записать. */
}
int32_t translated_native_x(Player *p) {
    /* Python: строка 669; Return. */
    return demo_table_i32((uint16_t)(p->player_x >> 8), 160);
}
int32_t translated_native_y(Player *p) {
    /* Python: строка 670; Return. */
    return demo_table_i32((uint16_t)(p->player_y >> 8), 161);
}
void translated_fire(Player *p, Inputs *in, int32_t occupied_shot_slots) {
    int32_t fire;
    int32_t power;
    /* Python: строка 964; Assign. */
    fire = in->fire; /* Вычислить, затем записать. */
    /* Python: строка 965; If. */
    if (fire) {
        /* Python: строка 966; If. */
        if ((!p->fire_held)) {
            /* Python: строка 967; Assign. */
            p->fire_held = 1L; /* Вычислить, затем записать. */
            /* Python: строка 969; If. */
            if ((((occupied_shot_slots + py_int(p->pending_shot_spawn)) < 3L))) {
                /* Python: строка 971; Assign. */
                p->pending_shot_spawn = 1L; /* Вычислить, затем записать. */
            }
        }
        /* Python: строка 990; Assign. */
        p->wave_charge = advance_wave_charge(p->wave_charge); /* Вычислить, затем записать. */
    } else {
        /* Python: строка 997; If. */
        if (p->fire_held) {
            /* Python: строка 998; Assign. */
            p->fire_held = 0L; /* Вычислить, затем записать. */
            /* Python: строка 1003; Assign. */
            power = wave_power(p->wave_charge); /* Вычислить, затем записать. */
            /* Python: строка 1004; If. */
            if (power) {
                /* Python: строка 1005; Assign. */
                wave.active = demo_wave_spawn((p->player_x + 6827L), (p->player_y + 768L), (p->player_x + 6827L), (p->player_y + 768L), power); /* Вычислить, затем записать. */
            }
            /* Python: строка 1010; Assign. */
            p->wave_charge = 0L; /* Вычислить, затем записать. */
        }
    }
}
void demo_spawn(int32_t x, int32_t y, int32_t nx, int32_t ny);
void translated_pending(Player *p, int32_t occupied_shot_slots) {
    int32_t native_x;
    int32_t native_y;
    /* Python: строка 955; If. */
    if (p->pending_shot_spawn) {
        /* Python: строка 956; Assign. */
        p->pending_shot_spawn = 0L; /* Вычислить, затем записать. */
        /* Python: строка 957; If. */
        if (((occupied_shot_slots < 3L))) {
            /* Python: строка 958; Assign. */
            native_x = demo_table_i32((uint16_t)(p->player_x >> 8), 160); /* Вычислить, затем записать. */
            /* Python: строка 958; Assign. */
            native_y = demo_table_i32((uint16_t)(p->player_y >> 8), 161); /* Вычислить, затем записать. */
            /* Python: строка 959; Expr. */
            demo_spawn((p->player_x + 6827L), (p->player_y + 3072L), (native_x + 8L), native_y);
            /* Python: строка 962; AugAssign. */
            occupied_shot_slots = (occupied_shot_slots + 1L); /* Вычислить, затем записать. */
        }
    }
}
uint8_t translated_shot(Projectile *s) {
    int32_t _step;
    /* Python: строка 646; For. */
    for (_step=0; _step<2; ++_step) {
        /* Python: строка 647; Assign. */
        s->native_x = ((s->native_x + 8L) & 65535L); /* Вычислить, затем записать. */
    }
    /* Python: строка 665; Assign. */
    s->x = demo_table_i32((uint16_t)s->native_x, 144); /* Вычислить, затем записать. */
    /* Python: строка 666; Return. */
    return 0L;
}
uint8_t translated_shot_alive(Projectile *s) { return ((s->native_x < 696L)) && ((s->x < (640L * 256L))); }
void translated_init(Player *p) {
    /* Python: строка 450; Assign. */
    p->player_x = (233L * 256L); /* Вычислить, затем записать. */
    /* Python: строка 451; Assign. */
    p->player_y = (192L * 256L); /* Вычислить, затем записать. */
    /* Python: строка 452; Assign. */
    p->player_pitch = 20L; /* Вычислить, затем записать. */
    /* Python: строка 462; Assign. */
    p->pending_shot_spawn = 0L; /* Вычислить, затем записать. */
    /* Python: строка 471; Assign. */
    p->fire_held = 0L; /* Вычислить, затем записать. */
    /* Python: строка 473; Assign. */
    p->wave_charge = 0L; /* Вычислить, затем записать. */
}
void translated_wave_init(Wave *w, int32_t x, int32_t y, int32_t release_x, int32_t release_y, int32_t power) {
    /* Python: строка 320; Assign. */
    w->x = x; /* Вычислить, затем записать. */
    /* Python: строка 321; Assign. */
    w->y = y; /* Вычислить, затем записать. */
    /* Python: строка 322; Assign. */
    w->release_x = release_x; /* Вычислить, затем записать. */
    /* Python: строка 323; Assign. */
    w->release_y = release_y; /* Вычислить, затем записать. */
    /* Python: строка 324; Assign. */
    w->power = power; /* Вычислить, затем записать. */
    /* Python: строка 325; Assign. */
    w->delay = 2L; /* Вычислить, затем записать. */
    /* Python: строка 326; Assign. */
    w->animation = 0L; /* Вычислить, затем записать. */
    /* Python: строка 327; Assign. */
    w->render_power = 0L; /* Вычислить, затем записать. */
    /* Python: строка 330; If. */
    if ((!w->render_power)) {
        /* Python: строка 331; Assign. */
        w->render_power = wave_power_tier(w->power); /* Вычислить, затем записать. */
    }
}
void translated_wave_update(void) {
    int32_t cost;
    /* Python: строка 876; If. */
    if (((wave.active != 0))) {
        /* Python: строка 877; If. */
        if (((wave.power <= 0L))) {
            /* Python: строка 879; Assign. */
            wave.active = 0; /* Вычислить, затем записать. */
        } else {
            /* Python: строка 880; If. */
            if (wave.delay) {
                /* Python: строка 881; AugAssign. */
                wave.delay = (wave.delay - 1L); /* Вычислить, затем записать. */
            } else {
                /* Python: строка 885; Assign. */
                wave.render_power = wave_power_tier(wave.power); /* Вычислить, затем записать. */
                /* Python: строка 886; AugAssign. */
                wave.animation = (wave.animation + 1L); /* Вычислить, затем записать. */
                /* Python: строка 887; AugAssign. */
                wave.x = (wave.x + 3413L); /* Вычислить, затем записать. */
                /* Python: строка 888; If. */
                if (((wave.x >= (640L * 256L)))) {
                    /* Python: строка 889; Assign. */
                    wave.active = 0; /* Вычислить, затем записать. */
                } else {
                    /* Python: строка 891; Assign. */
                    cost = 0L; /* Вычислить, затем записать. */
                    /* Python: строка 893; If. */
                    if (((cost > wave.power))) {
                        /* Python: строка 895; Assign. */
                        wave.active = 0; /* Вычислить, затем записать. */
                    } else {
                        /* Python: строка 897; AugAssign. */
                        wave.power = (wave.power - cost); /* Вычислить, затем записать. */
                    }
                }
            }
        }
    }
}
#include "demo_images_generated.h"
void demo_wave_blit(uint8_t image,int16_t x,int16_t y);
void translated_wave_draw(void) {
    int32_t phase;
    int32_t release_index;
    /* Python: строка 1089; If. */
    if ((((wave.active != 0)) && ((wave.delay == 0L)))) {
        /* Python: строка 1090; If. */
        if (((wave.animation < 7L))) {
            /* Python: строка 1091; Assign. */
            release_index = py_min(3L, ((int32_t)(wave.animation) >> 1) /* ASR: деление вниз на 2. */); /* Вычислить, затем записать. */
            /* Python: строка 1092; Expr. */
            demo_wave_blit(IMG_RELEASE0 + release_index, ((int32_t)(wave.release_x) >> 8) /* ASR: деление вниз на 256. */, ((int32_t)(wave.release_y) >> 8) /* ASR: деление вниз на 256. */);
        }
        /* Python: строка 1094; Assign. */
        phase = (((wave.animation + 1L) >> 1L) & 1L); /* Вычислить, затем записать. */
        /* Python: строка 1095; Expr. */
        demo_wave_blit(wave_images[wave.render_power][phase], ((int32_t)(wave.x) >> 8) /* ASR: деление вниз на 256. */, ((int32_t)(wave.y) >> 8) /* ASR: деление вниз на 256. */);
    }
}
uint8_t translated_motion(Motion *m, Enemy *o) {
    int32_t remaining;
    int32_t value;
    int32_t word;
    uint16_t fuel = 256;
    /* Python: строка 401; Assign. */
    remaining = m->commands; /* Вычислить, затем записать. */
    /* Python: строка 402; While. */
    while (remaining) {
        if (!fuel--) { demo_fault = 1; return 1; }
        /* Python: строка 403; Assign. */
        value = rom_byte(m->pointer); /* Вычислить, затем записать. */
        /* Python: строка 404; If. */
        if ((value & 128L)) {
            /* Python: строка 405; Assign. */
            m->phase = (value & 31L); /* Вычислить, затем записать. */
            /* Python: строка 409; Assign. */
            m->pointer = _u16((m->pointer + 1L)); /* Вычислить, затем записать. */
            /* Python: строка 410; Continue. */
            continue;
        }
        /* Python: строка 411; If. */
        if ((value & 64L)) {
            /* Python: строка 412; If. */
            if ((value & 32L)) {
                /* Python: строка 413; Assign. */
                o->x = _u16((o->x - 1L)); /* Вычислить, затем записать. */
            }
        } else {
            /* Python: строка 414; If. */
            if ((value & 32L)) {
                /* Python: строка 415; Assign. */
                o->x = _u16((o->x + 1L)); /* Вычислить, затем записать. */
            }
        }
        /* Python: строка 416; If. */
        if ((value & 16L)) {
            /* Python: строка 417; If. */
            if ((value & 8L)) {
                /* Python: строка 418; Assign. */
                o->y = _u16((o->y - 1L)); /* Вычислить, затем записать. */
            }
        } else {
            /* Python: строка 419; If. */
            if ((value & 8L)) {
                /* Python: строка 420; Assign. */
                o->y = _u16((o->y + 1L)); /* Вычислить, затем записать. */
            }
        }
        /* Python: строка 421; If. */
        if ((value & 4L)) {
            /* Python: строка 422; While. */
            while (1L) {
                if (!fuel--) { demo_fault = 1; return 1; }
                /* Python: строка 423; Assign. */
                m->script = _u16((m->script + 2L)); /* Вычислить, затем записать. */
                /* Python: строка 424; Assign. */
                word = rom_word(m->script); /* Вычислить, затем записать. */
                /* Python: строка 425; If. */
                if (((word == 0L))) {
                    /* Python: строка 426; Assign. */
                    m->script = rom_word((m->script + 2L)); /* Вычислить, затем записать. */
                    /* Python: строка 427; Assign. */
                    m->pointer = rom_word(m->script); /* Вычислить, затем записать. */
                    /* Python: строка 428; Return. */
                    return 1L;
                }
                /* Python: строка 429; If. */
                if ((((word & 65280L) == 61440L))) {
                    /* Python: строка 430; Assign. */
                    m->commands = (word & 255L); /* Вычислить, затем записать. */
                    /* Python: строка 431; Continue. */
                    continue;
                }
                /* Python: строка 432; Assign. */
                m->pointer = word; /* Вычислить, затем записать. */
                /* Python: строка 433; Return. */
                return 0L;
            }
        }
        /* Python: строка 434; Assign. */
        m->pointer = _u16((m->pointer + 1L)); /* Вычислить, затем записать. */
        /* Python: строка 435; AugAssign. */
        remaining = (remaining - 1L); /* Вычислить, затем записать. */
    }
    /* Python: строка 436; Return. */
    return 0L;
}
void translated_enemy(Enemy *e, int32_t foreground_delta) {
    int32_t animation_offset;
    /* Python: строка 912; If. */
    if (translated_motion(&e->motion, e)) {
        /* Python: строка 913; Assign. */
        e->alive = 0L; /* Вычислить, затем записать. */
        /* Python: строка 914; Return. */
        return;
    }
    /* Python: строка 915; Assign. */
    e->x = _u16((e->x + foreground_delta)); /* Вычислить, затем записать. */
    /* Python: строка 916; Assign. */
    animation_offset = ((frame + e->motion.phase) & 28L); /* Вычислить, затем записать. */
    /* Python: строка 917; Assign. */
    e->descriptor = (10466L + ((animation_offset >> 2L) * 6L)); /* Вычислить, затем записать. */
}
