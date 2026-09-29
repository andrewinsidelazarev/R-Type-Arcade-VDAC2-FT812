/* Ввод цикла app.main полного runtime на TS-Config (адаптер событий pygame и RuntimeInput),
 * банковая часть. Клавиатура PS/2 ZX Evolution, Kempston-джойстик, Kempston-мышь. Управление — как в CLAUDE.md
 * (как в HMM2); клавиш монеты и старта системы нет.
 *
 * События кадра (FrameEvents, биты 0–3): title_start — нажатие огня (Space, Enter, огонь Kempston, ЛКМ),
 * system_start и coin — всегда 0, demo_wake — нажатие любой клавиши (и правого Alt), огня Kempston или ЛКМ
 * (любой KEYDOWN, JOYBUTTONDOWN, MOUSEBUTTONDOWN кнопки 1; ПКМ не будит — как в Python).
 * Кнопки игры (GameButtons, биты 0–5, как _input_mask): вправо, влево, вниз, вверх — стрелки, QAOP,
 * Kempston-джойстик; огонь — Space, Enter, огонь Kempston или ЛКМ; Force — правый Alt (AltGr) или ПКМ (FORCE_KEYS
 * K_RALT и кнопка 3 мыши Python-версии): удерживаемые или нажатые в этом кадре. После p2c_z80_input_clear (сброс
 * сессии, held_input.clear_actions) удерживаемые огонь и Force не действуют до отпускания.
 *
 * Клавиатура — только очередь скан-кодов PS/2 контроллера AVR ZX Evolution (p2c_ft_keyboard, p2c_z80_ft812_cold.c —
 * как в Wild Commander и Zuma); матрица клавиш ZX не читается (просьба пользователя 28.09.2026: у HIDman mini клавиши
 * залипали в матрице AVR, «клавиатуру 40-pin вообще не нужно опрашивать»).
 *
 * Kempston-мышь: #FBDF — счётчик X (растёт вправо), #FFDF — счётчик Y (растёт вверх), #FADF —
 * кнопки (бит 0 — левая, бит 1 — правая, бит 2 — средняя; 0 — нажата). Без мыши порты читаются как #FF: движения и
 * нажатий нет. Мышь — источник координат R-9, а не направлений (отступление на аппаратном пределе
 * ввода, как в первых версиях порта): смещение счётчиков за кадр — p2c_z80_mouse_dx / p2c_z80_mouse_dy,
 * их переносит в позицию корабля вызов машины 9 (p2c_port_mouse, ApiMouse в v30z80_runtime.asm).
 * Чувствительность мыши (просьба пользователя 2026-09-17: новая PS/2-мышь бегает вдвое быстрее) — 1 или 1/2,
 * переключается средней кнопкой по фронту нажатия, при запуске — 1: при 1/2 смещение кадра делится пополам с
 * переносом остатка оси (p2c_rt_mouse_scale), так что за много кадров путь ровно вдвое короче.
 *
 * Esc (p2c_kb_esc) действует по экрану прошлого кадра p2c_rt_screen — тому, что игрок видел, нажимая (решения
 * пользователя 2026-09-29, отступления от оригинала, как скорость мыши):
 *   титул — развёртка FT812 59 ↔ 55 Гц и надпись «VSync 59 Hz» / «VSync 55 Hz» (p2c_ft_vsync_toggle,
 *     p2c_z80_ft812_cold.c): «в главном меню нажатие кнопки ESC приводило к смене кадровой частоты FT812 59 (по
 *     умолчанию) / 50 Гц», затем «Давай сделаем 59 / 55 (родные)»;
 *   игра — шаг R-9 от клавиш и Kempston-джойстика ×1 ↔ ×2 (p2c_rt_keys_double, при запуске — ×1): «при нажатии ESC
 *     корабль сдвигается с шагом в 2 больше с клавиатуры или Kempston Joystick. Повторное нажатие клавиши ESC
 *     возвращает обычное поведение». Машине он приходит битом 3 флагов шага (p2c_port_step): шаг по направлению
 *     обработчика R-9 $2027 прибавляется дважды (N_2027, vdac2p_native2.asm), и около трёх секунд видна надпись
 *     «Keys / joystick speed: 2x» или «1x» (vdac2p_label.asm);
 *   демо — только пробуждение (как любая клавиша): ни развёртка, ни шаг клавиш не меняются. */
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

/* Состояние ввода (адреса — в ассемблере p2c_z80_runtime_input). Клавиши кадра — p2c_kb_moves, p2c_kb_buttons,
 * p2c_kb_wake (p2c_ft_keyboard). */
uint8_t p2c_rt_fire_previous;            /* огонь прошлого кадра (0/1) */
uint8_t p2c_rt_force_previous;           /* Force прошлого кадра (0/1) */
uint8_t p2c_rt_start_previous;           /* вторая кнопка старта прошлого кадра (бит 7 #1F, #80 — нажата) */
uint8_t p2c_rt_blocked;                  /* биты 16 и 32: огонь и Force держатся со сброса сессии */
uint8_t p2c_rt_joystick;                 /* Kempston-джойстик кадра (порт без джойстика — 0) */
uint8_t p2c_rt_mouse_keys;               /* кнопки мыши кадра (#FADF, 0 — нажата) */
uint8_t p2c_rt_mouse_ready;              /* счётчики мыши прошлого кадра прочитаны */
uint8_t p2c_rt_mouse_x_previous;
uint8_t p2c_rt_mouse_y_previous;
uint8_t p2c_rt_mouse_half;               /* чувствительность мыши: 0 — 1, 1 — 1/2 (средняя кнопка; нули загрузчика) */
uint8_t p2c_rt_mmb_previous;             /* средняя кнопка прошлого кадра (4 — нажата) */
uint8_t p2c_rt_mouse_rest_x;             /* остатки деления смещения пополам по осям (0/1) */
uint8_t p2c_rt_mouse_rest_y;
uint8_t p2c_rt_keys_double;              /* шаг R-9 от клавиш и джойстика: 0 — ×1, 1 — ×2 (Esc; нули загрузчика) */
uint8_t p2c_rt_screen;                   /* экран прошлого кадра: 0 — титул (и до первого кадра), 1 — машина без игрока
                                            (демо), 2 — игра (p2c_rt_frame_end) */
uint8_t p2c_rt_game_frame;               /* в этом кадре был ход игрока (p2c_port_mouse зовётся только вне демо) */
int8_t p2c_z80_mouse_dx;                 /* смещение мыши кадра в отсчётах: вправо — плюс (p2c_port_mouse) */
int8_t p2c_z80_mouse_dy;                 /* вверх — плюс */
uint8_t p2c_z80_input_events;            /* FrameEvents кадра: бит 0 title_start, 3 demo_wake (1, 2 — всегда 0) */
uint8_t p2c_z80_input_buttons;           /* GameButtons кадра: вправо 1, влево 2, вниз 4, вверх 8, огонь 16, Force 32 */

/* Ввод кадра — на ассемблере (C-версия после SDCC стоила ≈6 тыс. тактов на кадр). Итог — в p2c_z80_input_events и
 * p2c_z80_input_buttons. По шагам (как C-версия до переписывания):
 *   p2c_ft_keyboard(): moves, buttons — нажатые клавиши PS/2, wake — нажата любая, esc — нажат Esc;
 *     esc: screen 0 (титул) — p2c_ft_vsync_toggle(), 2 (игра) — keys_double ^= 1, 1 (демо) — ничего;
 *     kempston = IN(#1F), #FF → 0;
 *   мышь: средняя кнопка нажата впервые — half ^= 1, остатки осей 0; dx = X − X_прошл, dy = Y − Y_прошл (по модулю
 *     256 со знаком; |d| > 63 — скачок, 0; первый кадр — 0); при half: s = d + остаток, d = s >> 1, остаток = s & 1;
 *   fire = buttons & (Space | Enter) | kempston & 16 | ЛКМ — 0/1;
 *   force = buttons & правый Alt | ПКМ | kempston & 32 (вторая кнопка джойстика) — 0/1;
 *   bits = kempston & 15 | (moves | moves >> 4) & 15 (стрелки | P O A Q: вправо 1, влево 2, вниз 4, вверх 8);
 *   held = fire·16 + force·32; blocked &= held; bits |= held & ~blocked; огонь нажат впервые — | 16, Force — | 32;
 *   start = kempston & 128 (восьмая кнопка джойстика); events = (огонь впервые | start впервые) +
 *     (wake | огонь впервые)·8 — start только стартует игру: в bits и в wake он не идёт;
 *   fire/force/start_previous = fire/force/start.
 * Регистры не сохраняются: вызывающий — код C. */
void p2c_z80_runtime_input(void) __banked __naked {
    __asm
        call    _p2c_ft_keyboard                ; клавиши PS/2 кадра: p2c_kb_moves, p2c_kb_buttons, p2c_kb_wake,
                                                ; p2c_kb_esc; тот же банк — прямой вызов
        ; --- Esc по экрану прошлого кадра: титул (0) — развёртка 59 ↔ 55 Гц, игра (2) — шаг клавиш ×1 ↔ ×2,
        ;     демо (1) — только пробуждение ---
        ld      a, (_p2c_kb_esc)
        or      a, a
        jr      z, p2c_rt_esc_done
        ld      a, (_p2c_rt_screen)
        or      a, a
        jr      nz, p2c_rt_esc_game
        call    _p2c_ft_vsync_toggle            ; тот же банк — прямой вызов
        jr      p2c_rt_esc_done
p2c_rt_esc_game:
        cp      a, #2
        jr      nz, p2c_rt_esc_done
        ld      hl, #_p2c_rt_keys_double
        ld      a, (hl)
        xor     a, #1
        ld      (hl), a
p2c_rt_esc_done:
        ; --- Kempston-джойстик ---
        ld      bc, #0x001F
        in      a, (c)
        inc     a
        jr      z, p2c_rt_joystick_store         ; #FF — порт без джойстика: 0
        dec     a
p2c_rt_joystick_store:
        ld      (_p2c_rt_joystick), a
        ; --- мышь ---
        ld      bc, #0xFADF
        in      a, (c)
        ld      (_p2c_rt_mouse_keys), a
        ld      b, #0xFB
        in      e, (c)                          ; E — счётчик X
        ld      b, #0xFF
        in      d, (c)                          ; D — счётчик Y (IN r,(C) не меняет A — в нём кнопки)
        ; чувствительность: средняя кнопка (бит 2, 0 — нажата) по фронту нажатия переключает 1 ↔ 1/2
        cpl
        and     a, #0x04
        ld      c, a                            ; C = 4 — средняя кнопка нажата
        ld      a, (_p2c_rt_mmb_previous)
        cpl
        and     a, c                            ; Z — не нажата впервые (LD ниже флаги не меняет)
        ld      a, c
        ld      (_p2c_rt_mmb_previous), a
        jr      z, p2c_rt_mouse_counts
        ld      a, (_p2c_rt_mouse_half)
        xor     a, #1
        ld      (_p2c_rt_mouse_half), a
        xor     a, a
        ld      (_p2c_rt_mouse_rest_x), a
        ld      (_p2c_rt_mouse_rest_y), a       ; остатки прежней чувствительности — прочь
p2c_rt_mouse_counts:
        xor     a, a
        ld      (_p2c_z80_mouse_dx), a
        ld      (_p2c_z80_mouse_dy), a
        ld      a, (_p2c_rt_mouse_ready)
        or      a, a
        jr      z, p2c_rt_mouse_store           ; первый кадр — только запомнить счётчики
        ld      a, (_p2c_rt_mouse_x_previous)
        neg
        add     a, e                            ; A = X − X_прошл
        call    p2c_rt_mouse_delta
        ld      hl, #_p2c_rt_mouse_rest_x
        call    p2c_rt_mouse_scale
        ld      (_p2c_z80_mouse_dx), a
        ld      a, (_p2c_rt_mouse_y_previous)
        neg
        add     a, d                            ; A = Y − Y_прошл
        call    p2c_rt_mouse_delta
        ld      hl, #_p2c_rt_mouse_rest_y
        call    p2c_rt_mouse_scale
        ld      (_p2c_z80_mouse_dy), a
p2c_rt_mouse_store:
        ld      a, e
        ld      (_p2c_rt_mouse_x_previous), a
        ld      a, d
        ld      (_p2c_rt_mouse_y_previous), a
        ld      a, #1
        ld      (_p2c_rt_mouse_ready), a
        ; --- огонь: B = 0/1 ---
        ld      a, (_p2c_kb_buttons)
        and     a, #0x03                        ; Space, Enter (P2C_KB_SPACE | P2C_KB_ENTER)
        ld      b, a
        ld      a, (_p2c_rt_joystick)
        and     a, #0x10                        ; огонь Kempston
        or      a, b
        ld      b, a
        ld      a, (_p2c_rt_mouse_keys)
        rra                                     ; CF — бит 0: 0 — ЛКМ нажата
        jr      c, p2c_rt_fire_bool
        ld      b, #1
p2c_rt_fire_bool:
        ld      a, b
        or      a, a
        jr      z, p2c_rt_force
        ld      b, #1
p2c_rt_force:
        ; --- Force: C = 0/1 ---
        ld      c, #0
        ld      a, (_p2c_rt_mouse_keys)
        and     a, #0x02
        jr      nz, p2c_rt_force_altgr
        ld      c, #1                           ; ПКМ нажата
p2c_rt_force_altgr:
        ld      a, (_p2c_kb_buttons)
        and     a, #0x04                        ; правый Alt (P2C_KB_ALTGR)
        jr      z, p2c_rt_force_joystick
        ld      c, #1
p2c_rt_force_joystick:
        ld      a, (_p2c_rt_joystick)
        and     a, #0x20                        ; вторая кнопка Kempston — тоже сброс модуля защиты
        jr      z, p2c_rt_force_done
        ld      c, #1
p2c_rt_force_done:
        ; --- направления: E = (moves | moves >> 4) & 15 | kempston & 15 ---
        ld      a, (_p2c_kb_moves)              ; стрелки → ← ↓ ↑ — биты 0…3, P O A Q — биты 4…7
        ld      e, a
        rrca
        rrca
        rrca
        rrca                                    ; P O A Q — в биты 0…3
        or      a, e
        and     a, #0x0F                        ; вправо 1, влево 2, вниз 4, вверх 8
        ld      e, a
        ld      a, (_p2c_rt_joystick)
        and     a, #0x0F
        or      a, e
        ld      e, a
p2c_rt_held:
        ; --- удерживаемые: held = огонь·16 + Force·32; blocked &= held; bits |= held & ~blocked ---
        ld      a, c
        add     a, a
        add     a, b                            ; Force·2 + огонь
        add     a, a
        add     a, a
        add     a, a
        add     a, a                            ; ·16
        ld      d, a                            ; D — held
        ld      hl, #_p2c_rt_blocked
        and     a, (hl)
        ld      (hl), a                         ; отпущенные кнопки снова действуют
        cpl
        and     a, d
        or      a, e
        ld      e, a
        ; --- нажатие в этом кадре действует и после сброса ---
        ld      a, (_p2c_rt_fire_previous)
        cpl
        and     a, b
        ld      d, a                            ; D — огонь нажат впервые (0/1)
        jr      z, p2c_rt_force_new
        set     4, e
p2c_rt_force_new:
        ld      a, (_p2c_rt_force_previous)
        cpl
        and     a, c
        jr      z, p2c_rt_buttons
        set     5, e
p2c_rt_buttons:
        ld      a, e
        ld      (_p2c_z80_input_buttons), a
        ; --- события: H ---
        ld      h, d                            ; title_start — огонь нажат впервые
        ; Восьмая кнопка Kempston (бит 7 порта #1F) — второй старт игры, и только он: в GameButtons она не
        ; идёт (ни огня, ни Force), пробуждением демо сама по себе не считается. E свободен: bits уже сняты.
        ld      a, (_p2c_rt_joystick)
        and     a, #0x80
        ld      e, a                            ; E = #80 — кнопка нажата
        ld      a, (_p2c_rt_start_previous)
        cpl
        and     a, e                            ; кнопка нажата впервые (LD ниже флаги не меняет)
        ld      a, e
        ld      (_p2c_rt_start_previous), a
        jr      z, p2c_rt_events_wake
        set     0, h                            ; title_start и от неё
p2c_rt_events_wake:
        ld      a, (_p2c_kb_wake)               ; нажата клавиша PS/2
        or      a, d                            ; огонь нажат впервые — тоже пробуждение
        jr      z, p2c_rt_events
        set     3, h
p2c_rt_events:
        ld      a, h
        ld      (_p2c_z80_input_events), a
        ; --- состояние на следующий кадр ---
        ld      a, b
        ld      (_p2c_rt_fire_previous), a
        ld      a, c
        ld      (_p2c_rt_force_previous), a
        ret
; Смещение счётчика мыши: A — разность по модулю 256; со знаком больше 63 или меньше −63 — 0.
p2c_rt_mouse_delta:
        cp      a, #64
        ret     c                               ; 0…63
        cp      a, #0xC1
        ret     nc                              ; −63…−1
        xor     a, a
        ret
; Чувствительность: A — смещение кадра со знаком (−63…63), HL → остаток оси (0/1). При 1 — A без изменений; при 1/2 —
; сумма S = A + остаток (−63…64), A = S >> 1 (арифметический сдвиг — округление вниз), остаток = младший бит S: за
; много кадров путь ровно вдвое короче в обе стороны. Портит F, C; D, E сохраняет.
p2c_rt_mouse_scale:
        ld      c, a
        ld      a, (_p2c_rt_mouse_half)
        or      a, a
        ld      a, c
        ret     z                               ; чувствительность 1
        add     a, (hl)
        ld      c, a                            ; C = S
        and     a, #1
        ld      (hl), a                         ; остаток — младший бит S
        ld      a, c
        sra     a                               ; S >> 1
        ret
    __endasm;
}

/* Сброс сессии (held_input.clear_actions): удерживаемые огонь и Force не действуют до отпускания. */
void p2c_z80_input_clear(void) __banked {
    p2c_rt_blocked = 48u;
}

/* Конец кадра цикла app.main (после p2c_z80_frame_end): экран кадра — для Esc следующего. Кадр не показывала машина —
 * показан список титула: титул; показала — с ходом игрока (p2c_port_mouse) игра, без него демо. Кадр не титула снимает
 * надпись развёртки: «надпись не должна существовать на экране дольше перехода с главного экрана на любой другой»
 * (просьба пользователя 2026-09-29) — и при возврате на титул прежняя не показывается. В банке, а не в резиденте: там
 * места нет. */
void p2c_rt_frame_end(void) __banked {
    if (!p2c_ft_skip_swap) {
        p2c_rt_screen = 0;
    } else {
        p2c_rt_screen = p2c_rt_game_frame ? 2u : 1u;
        p2c_ft_label_on = 0;
    }
    p2c_rt_game_frame = 0;
}
