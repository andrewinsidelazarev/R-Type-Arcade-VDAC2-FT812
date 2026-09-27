/* Аппаратные адаптеры кадра Z80: вывод, ввод, звук. */
#ifndef P2C_Z80_ADAPTER_H
#define P2C_Z80_ADAPTER_H

#include <stdint.h>

/* Инициализация адаптера вывода (один раз до первого кадра). */
void p2c_z80_adapter_init(void);
/* Начало кадра (ожидание показа прошлого списка) и конец кадра (показ списка, точка останова модели). */
void p2c_z80_frame_begin(void);
void p2c_z80_frame_end(void);
/* Ввод отдельной сборки p2c_z80.py: нажатие огня в этом кадре и биты кнопок. */
void p2c_z80_input(uint8_t *start_pressed, uint8_t *input_bits);
/* Шаг звука кадра (у полного runtime звук идёт через машину — пусто). */
void p2c_z80_sound_frame(void);
/* Точка останова модели проверки: конец кадра, до сборки мусора. */
void p2c_z80_hook(void);

#endif
