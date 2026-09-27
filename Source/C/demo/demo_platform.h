#ifndef DEMO_PLATFORM_H
#define DEMO_PLATFORM_H
#include <stdint.h>

/* Статические записи демонстрационного профиля; игровая арифметика генерируется. */
typedef struct { int32_t script, pointer, commands, phase; } Motion;
typedef struct {
    int32_t x, y, descriptor, alive;
    Motion motion;
} Enemy;
typedef struct {
    int32_t player_x, player_y, player_pitch;
    int32_t fire_held, wave_charge, pending_shot_spawn;
} Player;
typedef struct { int32_t left, right, up, down, fire; } Inputs;
typedef struct { int32_t x, y, native_x, native_y, active; } Projectile;
typedef struct {
    int32_t x,y,release_x,release_y,power,delay,animation,render_power,active;
} Wave;

extern Player player;
extern Inputs inputs;
extern uint16_t frame;
extern uint8_t demo_fault;
extern Wave wave;
int32_t demo_wave_spawn(int32_t x,int32_t y,int32_t rx,int32_t ry,int32_t power);
int32_t py_floor(int32_t a, int32_t b);
int32_t py_round_ratio(int32_t a, int32_t b);
int32_t rom_byte(int32_t a);
int32_t rom_word(int32_t a);
int32_t demo_table_i32(uint16_t index,uint8_t first_page);
#define py_min(a,b) ((a)<(b)?(a):(b))
#define py_max(a,b) ((a)>(b)?(a):(b))
#define py_int(a) (a)
#define py_bool(a) (!!(a))
#define _u16(a) ((a)&65535L)
#endif
