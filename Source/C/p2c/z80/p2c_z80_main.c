/* Кадровый цикл Z80 в порядке app.main: первичная отрисовка титула, затем
 * кадры App.frame с опросом ввода, шагом звука и сборкой мусора между кадрами.
 * Логики игры здесь нет: она целиком в банках, сгенерированных p2c.
 * Используется отдельной сборкой p2c_z80.py (цикл без машины); SPG полного runtime — p2c_z80_runtime.c. */
#include "p2c_runtime.h"
#include "p2c_z80_adapter.h"

void p2c_title_render(void) __banked;
void p2c_app_frame(uint8_t a0, uint8_t a1) __banked;
void p2c_mark_children__b(P2cObject *object) __banked;

uint16_t p2c_z80_frames;          /* кадров цикла */

/* Дети объекта для сборщика — сгенерированная банковая функция. */
void p2c_mark_children(P2cObject *object) {
    p2c_mark_children__b(object);
}

/* Вход кода p2c: куча, адаптер, первый кадр титула, затем кадры: ввод (нажатие огня, биты кнопок), кадр App.frame,
 * показ списка, шаг звука, сборка мусора. */
void p2c_z80_main(void) {
    uint8_t start_pressed;
    uint8_t input_bits;
    p2c_heap_init();
    p2c_z80_adapter_init();
    p2c_z80_frame_begin();
    p2c_title_render();
    p2c_z80_frame_end();
    for (;;) {
        p2c_z80_input(&start_pressed, &input_bits);
        p2c_z80_frame_begin();
        p2c_app_frame(start_pressed, input_bits);
        p2c_z80_frame_end();
        p2c_z80_sound_frame();
        p2c_collect();
        ++p2c_z80_frames;
    }
}
