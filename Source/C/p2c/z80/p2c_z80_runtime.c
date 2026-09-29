/* Платформа цикла app.main текущей Python-версии (титул + полный runtime World ROM) на
 * TS-Config: кадровый цикл, порт машины M72 и владение RAM_G FT812. Логики игры здесь нет:
 * цикл app.main и титул — в банках, сгенерированных p2c (p2c_entry_runtime.py), машина —
 * переведённый код ROM (v30z80) в своей раскладке окон; вызовы машины идут через страницу
 * переключения (p2c_z80_switch.s, rtype_spg.py).
 *
 * Вызовы машины (номер в L у p2c_switch_call, аргументы p2c_port_arg / p2c_port_flags,
 * результат p2c_port_result): 0 — инициализация, 1 — шаг кадра, 2 — слово рабочего ОЗУ,
 * 3 — новая машина, 4 — сброс видеоадаптера машины, 5 — открыть пак уровней RTYPELVL.PAC на
 * SD-карте (поиск по всей карте; выполняется, пока на экране первый кадр титула), 6 — показанный
 * кадр машины гаснет в чёрное, 7 — шаг кадра звука (sound.step_frame цикла app.main, после кадра),
 * 8 — сброс звука сессии (sound.reset_session), 9 — смещение мыши кадра в координаты R-9 (L — X,
 * H — Y в отсчётах). Команды звука машины звуковой адаптер получает в конце шага (вызов 1).
 *
 * RAM_G и handle FT812 делят вывод титула (адаптер p2c_z80_ft812) и видеоадаптер машины:
 * шаг с выводом после кадров титула сбрасывает адаптер машины, вывод титула после кадров
 * игры — слоты титула (p2c_ft_foreign). Переходы без мусора на экране: изображения титула лежат
 * в верхних полосах машины, и в двух кадрах после сброса адаптер машины их не берёт (титул цел до
 * первого кадра игры); перед выводом титула после игры кадр машины гаснет в чёрное
 * (v30z80_video_assets.py). */
#include "p2c_runtime.h"
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

void p2c_title_render(void) __banked;
void p2c_app_frame(uint8_t a0, uint8_t a1) __banked;
void p2c_mark_children__b(P2cObject *object) __banked;
void p2c_z80_runtime_input(void) __banked;
void p2c_z80_input_clear(void) __banked;
void p2c_switch_call(uint8_t api) __z88dk_fastcall;

extern int8_t p2c_z80_mouse_dx;   /* смещение мыши кадра (p2c_z80_runtime_cold.c): вправо — плюс */
extern int8_t p2c_z80_mouse_dy;   /* вверх — плюс */
extern uint8_t p2c_z80_input_events;   /* FrameEvents кадра (биты title_start, system_start, coin, demo_wake) */
extern uint8_t p2c_z80_input_buttons;  /* GameButtons кадра (вправо, влево, вниз, вверх, огонь, Force) */
extern uint8_t p2c_rt_mouse_half;      /* чувствительность мыши (p2c_z80_runtime_cold.c): 0 — 1, 1 — 1/2 */
extern uint8_t p2c_rt_keys_double;     /* шаг R-9 от клавиш и джойстика (p2c_z80_runtime_cold.c): 0 — ×1, 1 — ×2 */
extern uint8_t p2c_rt_game_frame;      /* в кадре был ход игрока (p2c_port_mouse) — экран «игра» для Esc */
void p2c_rt_frame_end(void) __banked;  /* экран кадра для Esc и снятие надписи развёртки (p2c_z80_runtime_cold.c) */

uint16_t p2c_z80_frames;          /* кадров цикла app.main */
uint16_t p2c_port_arg;            /* аргумент вызова машины (маска кнопок или смещение слова ОЗУ) */
uint8_t p2c_port_flags;           /* флаги шага: бит 0 — START 1, бит 1 — COIN 1, бит 2 — мышь 1/2, бит 3 — шаг клавиш и
                                     джойстика ×2, бит 7 — выводить кадр */
uint16_t p2c_port_result;         /* результат вызова машины */
uint8_t p2c_port_video;          /* 1 — RAM_G у видеоадаптера машины */

/* Дети объекта для сборщика: разметку по классам генерирует p2c (банковая функция), резидентная — только переход. */
void p2c_mark_children(P2cObject *object) {
    p2c_mark_children__b(object);
}

/* MachinePort: новая машина (вызов 3 — страницы ROM и ОЗУ из копий состояния после загрузки). */
void p2c_port_boot(void) {
    p2c_switch_call(3);
}

/* Шаг кадра машины (вызов 1). Шаг с выводом после кадров титула (RAM_G занимал титул или показан список титула) сначала
 * сбрасывает видеоадаптер машины (вызов 4); после шага с выводом RAM_G считается чужой для адаптера титула. Бит 2 флагов —
 * чувствительность мыши 1/2: по нему видеоадаптер машины около трёх секунд после переключения пишет «Mouse speed: 1x»
 * или «0,5x» (vdac2p_label.asm; отступление от оригинала по решению пользователя 2026-09-27). Бит 3 — шаг R-9 от клавиш
 * и джойстика ×2 (Esc): обработчик R-9 прибавляет шаг по направлению дважды (N_2027, vdac2p_native2.asm), надпись —
 * «Keys / joystick speed: 2x» или «1x» (отступление по решению пользователя 2026-09-29). */
void p2c_port_step(int32_t mask, uint8_t start1, uint8_t coin1, uint8_t render) {
    if (render && (!p2c_port_video || p2c_ft_swapped)) {
        p2c_switch_call(4);
        p2c_port_video = 1;
        p2c_ft_swapped = 0;
    }
    p2c_port_arg = (uint16_t)mask;
    p2c_port_flags = (uint8_t)((start1 ? 1u : 0u) | (coin1 ? 2u : 0u) | (p2c_rt_mouse_half ? 4u : 0u) |
                               (p2c_rt_keys_double ? 8u : 0u) | (render ? 0x80u : 0u));
    p2c_switch_call(1);
    if (render) p2c_ft_foreign = 1;
}

/* Мышь — координаты R-9 (MachinePort.mouse, до шага кадра игры): смещение счётчиков мыши кадра — в вызов 9
 * (L — X, H — Y; пересчёт в пиксели M72 и проверка состояния корабля — в машине). Без движения вызова нет. Цикл app.main
 * зовёт её в каждом кадре игры игрока и только в нём (RuntimeGame.update вне демо) — отсюда и признак кадра игры для
 * Esc (p2c_rt_game_frame). */
void p2c_port_mouse(void) {
    p2c_rt_game_frame = 1;
    if (!(p2c_z80_mouse_dx | p2c_z80_mouse_dy)) return;
    p2c_port_arg = (uint16_t)((uint8_t)p2c_z80_mouse_dx | ((uint16_t)(uint8_t)p2c_z80_mouse_dy << 8));
    p2c_switch_call(9);
}

/* Слово рабочего ОЗУ машины (вызов 2): аргумент — смещение от #40000. */
int32_t p2c_port_word(int32_t address) {
    p2c_port_arg = (uint16_t)(address - 0x40000L);
    p2c_switch_call(2);
    return (int32_t)p2c_port_result;
}

/* Кадр игры уже показан видеоадаптером машины (DLSWAP в шаге): адаптер титула свой список не показывает. */
void p2c_port_show(void) {
    p2c_ft_skip_swap = 1;
}

/* Сброс сессии (sound.reset_session и held_input.clear_actions цикла app.main): звук машины (вызов 8) и ввод. */
void p2c_port_reset_session(void) {
    p2c_switch_call(8);
    p2c_z80_input_clear();
}

/* Кадр машины гаснет перед загрузкой изображений титула в её RAM_G (вызов машины 6). */
static void p2c_port_video_fade(void) {
    p2c_switch_call(6);
}

/* Вход кода p2c (p2c_z80_crt.s): куча, адаптер FT812, инициализация машины (вызов 0), первый кадр титула до тяжёлой
 * загрузки (как app.main), открытие пака уровней, машина конструктора (FullRuntimeGame снимка) и бесконечный цикл
 * кадров: ввод, кадр RuntimeApp.frame, шаг звука, показ списка, экран кадра для Esc (p2c_rt_frame_end: титул, демо
 * или игра; кадр не титула снимает надпись развёртки), сборка мусора. */
void p2c_z80_main(void) {
    p2c_heap_init();
    p2c_z80_adapter_init();
    p2c_ft_foreign_fade = p2c_port_video_fade;
    p2c_switch_call(0);
    p2c_z80_frame_begin();
    p2c_title_render();
    p2c_z80_frame_end();
#ifdef P2C_VSYNC_TEST
    /* Диагностика (в релизный SPG не входит): развёртка 55 Гц и её надпись с первого кадра титула — проверка в Unreal
     * без Esc (время титула до демо и надпись). */
    p2c_ft_vsync_toggle();
#endif
    /* Пак уровней (ячейки графики машины) — до первого кадра игры. */
    p2c_switch_call(5);
    /* FullRuntimeGame снимка (prepared_game): новая машина и шаг конструктора. */
    p2c_port_boot();
    p2c_port_step(0, 0, 0, 0);
    for (;;) {
        p2c_z80_runtime_input();
        p2c_z80_frame_begin();
        p2c_app_frame(p2c_z80_input_events, p2c_z80_input_buttons);
        /* sound.step_frame() цикла app.main: после кадра, до точки конца кадра модели сверки. */
        p2c_switch_call(7);
        p2c_z80_frame_end();
        p2c_rt_frame_end();
        p2c_collect();
        ++p2c_z80_frames;
    }
}
