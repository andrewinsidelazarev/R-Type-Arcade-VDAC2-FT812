/* Ввод цикла app.main полного runtime на TS-Config (адаптер событий pygame и RuntimeInput),
 * банковая часть. Клавиатура ZX, PS/2-клавиатура ZX Evolution (правый Alt), Kempston-джойстик,
 * Kempston-мышь. Управление — как в CLAUDE.md (как в HMM2); клавиш монеты и старта системы нет.
 *
 * События кадра (FrameEvents, биты 0–3): title_start — нажатие огня (Space, Enter, огонь Kempston, ЛКМ),
 * system_start и coin — всегда 0, demo_wake — нажатие любой клавиши (и правого Alt), огня Kempston или ЛКМ
 * (любой KEYDOWN, JOYBUTTONDOWN, MOUSEBUTTONDOWN кнопки 1; ПКМ не будит — как в Python).
 * Кнопки игры (GameButtons, биты 0–5, как _input_mask): вправо, влево, вниз, вверх — стрелки
 * (Caps+8, Caps+5, Caps+6, Caps+7), QAOP, Kempston-джойстик; огонь — Space, Enter, огонь Kempston
 * или ЛКМ; Force — правый Alt (AltGr) или ПКМ (FORCE_KEYS K_RALT и кнопка 3 мыши Python-версии):
 * удерживаемые или нажатые в этом кадре. После p2c_z80_input_clear (сброс сессии,
 * held_input.clear_actions) удерживаемые огонь и Force не действуют до отпускания.
 *
 * Правый Alt в матрице ZX не виден: он читается из очереди скан-кодов PS/2 контроллера Mr.Gluk ZX Evolution
 * (p2c_ft_altgr, p2c_z80_ft812_cold.c — как во вводе Zuma и HMM2 на VDAC2).
 *
 * Kempston-мышь: #FBDF — счётчик X (растёт вправо), #FFDF — счётчик Y (растёт вверх), #FADF —
 * кнопки (бит 0 — левая, бит 1 — правая, бит 2 — средняя; 0 — нажата). Без мыши порты читаются как #FF: движения и
 * нажатий нет. Мышь — источник координат R-9, а не направлений (отступление на аппаратном пределе
 * ввода, как в первых версиях порта): смещение счётчиков за кадр — p2c_z80_mouse_dx / p2c_z80_mouse_dy,
 * их переносит в позицию корабля вызов машины 9 (p2c_port_mouse, ApiMouse в v30z80_runtime.asm).
 * Чувствительность мыши (просьба пользователя 2026-09-17: новая PS/2-мышь бегает вдвое быстрее) — 1 или 1/2,
 * переключается средней кнопкой по фронту нажатия, при запуске — 1: при 1/2 смещение кадра делится пополам с
 * переносом остатка оси (p2c_rt_mouse_scale), так что за много кадров путь ровно вдвое короче. */
#include "p2c_z80_adapter.h"
#include "p2c_z80_ft812.h"

/* Состояние ввода (адреса — в ассемблере p2c_z80_runtime_input). */
uint8_t p2c_rt_rows[8];                  /* нажатые клавиши матрицы этого кадра (1 — нажата): строки #FEFE…#7FFE */
uint8_t p2c_rt_rows_previous[8];         /* прошлого кадра */
uint8_t p2c_rt_fire_previous;            /* огонь прошлого кадра (0/1) */
uint8_t p2c_rt_force_previous;           /* Force прошлого кадра (0/1) */
uint8_t p2c_rt_start_previous;           /* вторая кнопка старта прошлого кадра (бит 7 #1F, #80 — нажата) */
uint8_t p2c_rt_blocked;                  /* биты 16 и 32: огонь и Force держатся со сброса сессии */
uint8_t p2c_rt_altgr;                    /* правый Alt этого кадра (0/1) */
uint8_t p2c_rt_altgr_previous;           /* прошлого кадра */
uint8_t p2c_rt_wake;                     /* пробуждение кадра от матрицы и правого Alt (0/1) */
uint8_t p2c_rt_joystick;                 /* Kempston-джойстик кадра (порт без джойстика — 0) */
uint8_t p2c_rt_mouse_keys;               /* кнопки мыши кадра (#FADF, 0 — нажата) */
uint8_t p2c_rt_mouse_ready;              /* счётчики мыши прошлого кадра прочитаны */
uint8_t p2c_rt_mouse_x_previous;
uint8_t p2c_rt_mouse_y_previous;
uint8_t p2c_rt_mouse_half;               /* чувствительность мыши: 0 — 1, 1 — 1/2 (средняя кнопка; нули загрузчика) */
uint8_t p2c_rt_mmb_previous;             /* средняя кнопка прошлого кадра (4 — нажата) */
uint8_t p2c_rt_mouse_rest_x;             /* остатки деления смещения пополам по осям (0/1) */
uint8_t p2c_rt_mouse_rest_y;
int8_t p2c_z80_mouse_dx;                 /* смещение мыши кадра в отсчётах: вправо — плюс (p2c_port_mouse) */
int8_t p2c_z80_mouse_dy;                 /* вверх — плюс */
uint8_t p2c_z80_input_events;            /* FrameEvents кадра: бит 0 title_start, 3 demo_wake (1, 2 — всегда 0) */
uint8_t p2c_z80_input_buttons;           /* GameButtons кадра: вправо 1, влево 2, вниз 4, вверх 8, огонь 16, Force 32 */

/* Ввод кадра — на ассемблере (C-версия после SDCC стоила ≈6 тыс. тактов на кадр). Итог — в p2c_z80_input_events и
 * p2c_z80_input_buttons. По шагам (как C-версия до переписывания):
 *   altgr = p2c_ft_altgr(); rows[i] = ~IN(#FEFE, #FDFE, … #7FFE) & 31;
 *   wake = есть бит rows[i] & ~rows_previous[i] или altgr & ~altgr_previous; kempston = IN(#1F), #FF → 0;
 *   мышь: средняя кнопка нажата впервые — half ^= 1, остатки осей 0; dx = X − X_прошл, dy = Y − Y_прошл (по модулю
 *     256 со знаком; |d| > 63 — скачок, 0; первый кадр — 0); при half: s = d + остаток, d = s >> 1, остаток = s & 1;
 *   fire = rows[7] & 1 (Space) | rows[6] & 1 (Enter) | kempston & 16 | ЛКМ — 0/1;
 *   force = altgr | ПКМ | kempston & 32 (вторая кнопка джойстика) — 0/1;
 *   bits = kempston & 15 | rows[5] & 3 (P вправо, O влево) | rows[1] & 1 → 4 (A вниз) | rows[2] & 1 → 8 (Q вверх),
 *     с Caps (rows[0] & 1) ещё «8» (rows[4] & 4) → 1, «5» (rows[3] & 16) → 2, «6» (rows[4] & 16) → 4, «7» (rows[4] & 8) → 8;
 *   held = fire·16 + force·32; blocked &= held; bits |= held & ~blocked; огонь нажат впервые — | 16, Force — | 32;
 *   start = kempston & 128 (восьмая кнопка джойстика); events = (огонь впервые | start впервые) +
 *     (wake | огонь впервые)·8 — start только стартует игру: в bits и в wake он не идёт;
 *   rows_previous = rows, fire/force/altgr/start_previous = fire/force/altgr/start.
 * Регистры не сохраняются: вызывающий — код C. */
void p2c_z80_runtime_input(void) __banked __naked {
    __asm
        call    _p2c_ft_altgr                   ; A — правый Alt (0/1); тот же банк — прямой вызов
        ld      (_p2c_rt_altgr), a
        ; --- матрица ZX ---
        ld      hl, #_p2c_rt_rows
        ld      bc, #0xFEFE
        ld      d, #8
p2c_rt_row:
        in      a, (c)
        cpl
        and     a, #0x1F
        ld      (hl), a
        inc     hl
        rlc     b                               ; #FE → #FD → … → #7F
        dec     d
        jr      nz, p2c_rt_row
        ; --- пробуждение: клавиша нажата впервые (C = 1) ---
        ld      hl, #_p2c_rt_rows
        ld      de, #_p2c_rt_rows_previous
        ld      bc, #0x0800
p2c_rt_wake_row:
        ld      a, (de)
        cpl
        and     a, (hl)
        jr      z, p2c_rt_wake_next
        ld      c, #1
p2c_rt_wake_next:
        inc     hl
        inc     de
        djnz    p2c_rt_wake_row
        ld      a, (_p2c_rt_altgr_previous)
        cpl
        ld      hl, #_p2c_rt_altgr
        and     a, (hl)                         ; правый Alt нажат впервые
        jr      z, p2c_rt_wake_store
        ld      c, #1
p2c_rt_wake_store:
        ld      a, c
        ld      (_p2c_rt_wake), a
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
        ld      a, (_p2c_rt_rows+7)             ; Space Sym M N B
        and     a, #0x01                        ; Space
        ld      b, a
        ld      a, (_p2c_rt_rows+6)             ; Enter L K J H
        and     a, #0x01                        ; Enter
        or      a, b
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
        ld      a, (_p2c_rt_altgr)
        or      a, c
        ld      c, a
        ld      a, (_p2c_rt_joystick)
        and     a, #0x20                        ; вторая кнопка Kempston — тоже сброс модуля защиты
        jr      z, p2c_rt_force_done
        ld      c, #1
p2c_rt_force_done:
        ; --- направления: E ---
        ld      a, (_p2c_rt_joystick)
        and     a, #0x0F
        ld      e, a
        ld      a, (_p2c_rt_rows+5)             ; P O I U Y
        and     a, #0x03                        ; P — вправо, O — влево
        or      a, e
        ld      e, a
        ld      a, (_p2c_rt_rows+1)             ; A S D F G
        rra
        jr      nc, p2c_rt_key_q
        set     2, e                            ; A — вниз
p2c_rt_key_q:
        ld      a, (_p2c_rt_rows+2)             ; Q W E R T
        rra
        jr      nc, p2c_rt_caps
        set     3, e                            ; Q — вверх
p2c_rt_caps:
        ld      a, (_p2c_rt_rows)               ; Caps Z X C V
        rra
        jr      nc, p2c_rt_held                 ; без Caps стрелок нет
        ld      a, (_p2c_rt_rows+4)             ; 0 9 8 7 6
        bit     2, a
        jr      z, p2c_rt_caps_6
        set     0, e                            ; Caps+8 — вправо
p2c_rt_caps_6:
        bit     4, a
        jr      z, p2c_rt_caps_7
        set     2, e                            ; Caps+6 — вниз
p2c_rt_caps_7:
        bit     3, a
        jr      z, p2c_rt_caps_5
        set     3, e                            ; Caps+7 — вверх
p2c_rt_caps_5:
        ld      a, (_p2c_rt_rows+3)             ; 1 2 3 4 5
        bit     4, a
        jr      z, p2c_rt_held
        set     1, e                            ; Caps+5 — влево
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
        ld      a, (_p2c_rt_wake)
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
        ld      a, (_p2c_rt_altgr)
        ld      (_p2c_rt_altgr_previous), a
        ld      hl, #_p2c_rt_rows
        ld      de, #_p2c_rt_rows_previous
        ld      bc, #8
        ldir
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
