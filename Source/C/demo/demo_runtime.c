#include "demo_platform.h"
#include "demo_assets_generated.h"
#include "demo_stage_generated.h"
#include "../python_vm/pyz80_ordered_slots.h"
#include <string.h>

/* Только статическое размещение, ввод, вызовы трансляции и аппаратный вывод. */
Player player;
Inputs inputs;
uint16_t frame;
uint8_t demo_fault;
uint16_t demo_dl_bytes;
/* Имена доступны проверке через linker map; сами записи остаются статическими. */
Enemy enemies[DEMO_ENEMY_CAPACITY];
Projectile shots[3];
Wave wave;
/* Индексы сохраняют порядок Python-списков при освобождении/повторном занятии. */
static uint8_t enemy_order[DEMO_ENEMY_CAPACITY], enemy_count;
static uint8_t shot_order[3], shot_count;
static uint16_t tick, next_spawn, old_mouse_x, old_mouse_y, distance;
static uint16_t dl_count;
static int16_t frame_delta;
static uint16_t high_line_cost;
#include "demo_line_budget.h"

void translated_init(Player *p);
void translated_move(Player *p, Inputs *in);
void translated_fire(Player *p, Inputs *in, int32_t occupied_shot_slots);
void translated_pending(Player *p, int32_t occupied_shot_slots);
void translated_enemy(Enemy *e, int32_t foreground_delta);
void translated_wave_update(void);
void translated_wave_init(Wave *w,int32_t x,int32_t y,int32_t release_x,int32_t release_y,int32_t power);
void translated_wave_draw(void);
uint8_t translated_shot(Projectile *s);
uint8_t translated_shot_alive(Projectile *s);
uint8_t beam_animation_phase(uint16_t counter) __sdcccall(0);

static void stage_command(uint8_t operation) {
    *(volatile uint8_t *)STAGE_REQUEST=operation;
    /* Резидентный CALL переключает только кодовый банк и возвращает его назад. */
    ((void (*)(void))STAGE_KERNEL_THUNK)();
    if (*(volatile uint8_t *)STAGE_ERROR) demo_fault=10;
}

int32_t py_floor(int32_t a, int32_t b) {
    int32_t q = a / b;
    /* DIV с коррекцией к минус бесконечности, как Python //. */
    if (a < 0 && a % b) --q;
    return q;
}
int32_t py_round_ratio(int32_t a, int32_t b) {
    int32_t q = py_floor(a,b);
    int32_t r = a - q*b;
    /* Сравнить удвоенный остаток; точную половину округлить к чётному. */
    r += r;
    if (r > b || (r == b && (q&1))) ++q;
    return q;
}
int32_t rom_byte(int32_t a) {
    if (a < 0x8000L || a >= 0xc000L) { demo_fault = 2; return 0; }
    return *(const uint8_t *)(uint16_t)a;
}
int32_t rom_word(int32_t a) {
    return rom_byte(a) | (rom_byte(a+1)<<8);
}

int32_t demo_table_i32(uint16_t index,uint8_t first_page) {
    int32_t answer;
    uint16_t address=0x8000u|((index&4095u)<<2);
    /* SHR выбирает банк по старшим четырём битам индекса; SHL задаёт смещение i32. */
    *(volatile uint8_t *)0x0412=first_page+(index>>12);
    answer=*(const volatile int32_t *)address;
    /* Контракт провайдера: вызовы только из Tick, где окно 2 принадлежит ROM. */
    *(volatile uint8_t *)0x0412=0x30;
    return answer;
}

void demo_spawn(int32_t x,int32_t y,int32_t nx,int32_t ny) {
    uint8_t i;
    for (i=0;i<3;++i) if (!shots[i].active) {
        if (!pyz80_slots_append(shot_order,&shot_count,3,i)) { demo_fault=11; return; }
        shots[i].x=x; shots[i].y=y;
        shots[i].native_x=nx; shots[i].native_y=ny; shots[i].active=1;
        return;
    }
    demo_fault=3;
}

int32_t demo_wave_spawn(int32_t x,int32_t y,int32_t rx,int32_t ry,int32_t power) {
    translated_wave_init(&wave,x,y,rx,ry,power);
    wave.active=1;
    return 1;
}

void Demo_Init(void) {
    memset(&player,0,sizeof(player));
    memset(&inputs,0,sizeof(inputs));
    memset(enemies,0,sizeof(enemies));
    memset(shots,0,sizeof(shots));
    memset(&wave,0,sizeof(wave));
    enemy_count=0; shot_count=0;
    translated_init(&player);
    tick=0; next_spawn=0; frame=0x0292; demo_fault=0; distance=0;
    stage_command(0);
    old_mouse_x=*(volatile uint16_t *)0x2102;
    old_mouse_y=*(volatile uint16_t *)0x2104;
    high_line_cost=0;
    line_reset();
}

void Demo_Tick(void) {
    uint8_t i,j,occupied=0;
    uint8_t flags=*(volatile uint8_t *)0x2100;
    uint16_t mx=*(volatile uint16_t *)0x2102;
    uint16_t my=*(volatile uint16_t *)0x2104;
    const DemoSpawn *s;
    /* Конечный демонстрационный сценарий повторяется, это не переход уровня. */
    if (tick==DEMO_FRAMES) Demo_Init();
    ++tick; ++frame;
    stage_command(1);
    frame_delta=*(volatile int16_t *)STAGE_DISPATCH_FOREGROUND_DELTA;
    distance=*(volatile uint16_t *)STAGE_PROGRESSION;
    /* Диагностические выходы ABI, больше не входы записанной траектории. */
    *(volatile int16_t *)0x2106=frame_delta;
    *(volatile uint16_t *)0x2108=distance;
    inputs.left=!!(flags&1); inputs.right=!!(flags&2);
    inputs.up=!!(flags&4); inputs.down=!!(flags&8); inputs.fire=!!(flags&16);
    /* Мышь остаётся источником абсолютных логических координат. */
    if (mx!=old_mouse_x || my!=old_mouse_y) {
        player.player_x=(int32_t)mx*256; player.player_y=(int32_t)my*256;
        old_mouse_x=mx; old_mouse_y=my;
    }
    translated_move(&player,&inputs);
    for (i=0;i<DEMO_ENEMY_CAPACITY;++i) if (enemies[i].alive) {
        translated_enemy(&enemies[i],frame_delta);
        if (!enemies[i].alive && !pyz80_slots_remove(enemy_order,&enemy_count,i)) demo_fault=11;
    }
    while (next_spawn<DEMO_SPAWNS && spawns[next_spawn].tick==tick) {
        s=&spawns[next_spawn++];
        for (j=0;j<DEMO_ENEMY_CAPACITY && enemies[j].alive;++j) {}
        if (j==DEMO_ENEMY_CAPACITY) { demo_fault=4; break; }
        if (!pyz80_slots_append(enemy_order,&enemy_count,DEMO_ENEMY_CAPACITY,j)) { demo_fault=11; break; }
        enemies[j].x=s->x; enemies[j].y=s->y; enemies[j].descriptor=s->descriptor;
        enemies[j].motion.script=s->script; enemies[j].motion.pointer=s->pointer;
        enemies[j].motion.commands=s->commands; enemies[j].motion.phase=s->phase;
        enemies[j].alive=1;
    }
    translated_wave_update();
    for (i=0;i<3;++i) if (shots[i].active) {
        translated_shot(&shots[i]);
        shots[i].active=translated_shot_alive(&shots[i]);
        if (shots[i].active) ++occupied;
        else if (!pyz80_slots_remove(shot_order,&shot_count,i)) demo_fault=11;
    }
    translated_pending(&player,occupied);
    occupied=0;
    for (i=0;i<3;++i) if (shots[i].active) ++occupied;
    translated_fire(&player,&inputs,occupied);
    *(volatile uint16_t *)0x210a=tick;
}

static void dl(uint32_t command) {
    if (dl_count>=1023) { demo_fault=5; return; }
    ((uint32_t *)0x1000)[dl_count++]=command;
}

static void bitmap(uint8_t index,int16_t x,int16_t y) {
    const DemoBitmap *b=&bitmaps[index];
    int16_t px,py,first,last;
    uint16_t cost=b->physical_width+18;
    if (x>=640 || y>=480 || x+(int16_t)b->width<=0 || y+(int16_t)b->height<=0) return;
    if(x < -256 || y < -256) { demo_fault=8; return; }
    px=((const int16_t *)0x8000)[x+256];
    py=((const int16_t *)0x8000)[y+256];
    first=py>>3; last=first+b->physical_height;
    if (first<0) first=0;
    if (last>768) last=768;
    /* Две границы интервала вместо пересчёта всех строк каждого битмапа. */
    line_event(first,cost);
    line_event(last,-(int16_t)cost);
    if(dl_count+6>=1024) { demo_fault=5; return; }
    memcpy((uint32_t *)0x1000+dl_count,b->commands,20);
    dl_count+=5;
    dl(0x40000000UL|((uint32_t)(px&32767)<<15)|(py&32767));
}

static void hex_number(uint16_t value,int16_t x,int16_t y) {
    uint8_t i;
    for(i=0;i<4;++i) {
        bitmap(IMG_DIGIT0+((value>>12)&15),x,y);
        value<<=4; x+=10;
    }
}

/* Провайдер blit: выбор фазы и координаты вычисляет сгенерированный код. */
void demo_wave_blit(uint8_t image,int16_t x,int16_t y) {
    bitmap(image,x,y);
}

void Demo_Render(void) {
    uint8_t i,j,phase;
    int16_t x,y;
    uint16_t peak;
    int32_t native_x,native_y;
    dl_count=0;
    dl(0x02000000UL); dl(0x26000007UL); dl(0x27000003UL);
    dl(0x04ffffffUL); dl(0x100000ffUL); dl(0x0b000014UL);
    /* Полная матрица: физический масштаб 8/5, только аппаратный NEAREST. */
    dl(0x150000a0UL); dl(0x16000000UL); dl(0x17000000UL);
    dl(0x18000000UL); dl(0x190000a0UL); dl(0x1a000000UL); dl(0x1f000001UL);
    for(j=0;j<enemy_count;++j) {
        i=enemy_order[j];
        if(enemies[i].descriptor<DEMO_RED_FIRST || enemies[i].descriptor>DEMO_RED_LAST) { demo_fault=6; continue; }
        phase=red_phase[(uint8_t)(enemies[i].descriptor-DEMO_RED_FIRST)];
        if(phase>=8) { demo_fault=6; continue; }
        /* Смещение дескриптора входит ВНУТРЬ round, как в SpriteAtlas.draw. */
        native_x=enemies[i].x+red_origin[phase][0];
        native_y=red_origin[phase][1]-enemies[i].y;
        /* За пределами таблицы весь битмап гарантированно вне экрана. */
        if(native_x < -512 || native_x >= 512 || native_y < -512 || native_y >= 512) continue;
        x=((const int16_t *)DEMO_NATIVE_X_LUT)[(int16_t)native_x+512]+red_origin[phase][2];
        y=((const int16_t *)DEMO_NATIVE_Y_LUT)[(int16_t)native_y+512]+red_origin[phase][3];
        bitmap(IMG_RED0+phase,x,y);
    }
    phase=(uint8_t)(player.player_pitch>>3);
    bitmap(IMG_PITCH0+phase,(int16_t)(player.player_x>>8),(int16_t)(player.player_y>>8)+pitch_crop[phase]-1);
    for(j=0;j<shot_count;++j) {
        i=shot_order[j];
        bitmap(IMG_SHOT,(int16_t)(shots[i].x>>8),(int16_t)(shots[i].y>>8));
    }
    translated_wave_draw();
    if(player.fire_held && player.wave_charge>=15) {
        phase=beam_animation_phase(frame);
        bitmap(IMG_CHARGE0+phase,(int16_t)(player.player_x>>8)+53+charge_left[phase],
               (int16_t)(player.player_y>>8)-8+charge_top[phase]);
    }
    bitmap(IMG_HUD_BEAM,136,450);
    bitmap(IMG_METER0+(uint8_t)(player.wave_charge/2),220,454);
    bitmap(IMG_NOTICE,8,8);
    bitmap(IMG_LIVES,8,464);
    bitmap(IMG_FRAME,280,464); hex_number(frame,333,464);
    bitmap(IMG_DIST,520,464); hex_number(distance,566,464);
    dl(0x21000000UL); dl(0);
    demo_dl_bytes=dl_count*4;
    peak=line_peak();
    if(peak>high_line_cost) high_line_cost=peak;
    *(volatile uint16_t *)0x210c=high_line_cost;
    if(high_line_cost>1209) demo_fault=7;
}
void demo_code_end(void) {}
