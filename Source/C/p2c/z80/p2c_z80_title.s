; Отрисовка титула на Z80: TitleScreen.render как проигрыватель таблиц p2c_z80_title.inc (генератор
; p2c_title_native.py — значения и порядок выводов из title.py, сверены с render на кадрах 0…4096).
; Страница банка TITLE_PAGE (#4F, область _BANK79). Порядок выводов: глифы логотипа, строки, приглашение;
; каждый вывод — p2c_blit16 (резидент).
;
; void p2c_title_render_native(const int32_t *frame, const uint8_t *starting) __banked — в стеке (SP+5) адрес поля
; кадра TitleScreen, (SP+7) — адрес поля starting (старт игры запрошен: вместо приглашения — «GAME STARTING»).
        .module p2c_z80_title
        .include "p2c_z80_title_constants.inc"
        .globl  _p2c_title_render_native
        .globl  b_p2c_title_render_native
        .globl  _p2c_blit16

b_p2c_title_render_native = 79

        .area   _BANK79

_p2c_title_render_native::
        ld      hl, #7
        add     hl, sp
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a                    ; HL → поле starting
        ld      a, (hl)
        ld      (title_starting_flag), a
        ld      hl, #5
        add     hl, sp
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a                    ; HL → кадр (int32, не отрицательный)
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE = младшее слово кадра
        ld      a, e
        ld      (title_low), a          ; младший байт — фаза мерцания приглашения
        inc     hl
        ld      a, (hl)
        inc     hl
        or      a, (hl)
        jr      z, title_fits
        ld      de, #0xFFFF             ; кадр ≥ 65536: пороги логотипа и строк пройдены
title_fits:
        ld      (title_frame), de

        ; --- логотип: запись min(кадр, TITLE_LOGO_LAST) ------------------------------------------------
        ld      hl, #TITLE_LOGO_LAST
        or      a, a
        sbc     hl, de
        jr      nc, title_logo_frame    ; кадр ≤ LAST
        ld      de, #TITLE_LOGO_LAST
title_logo_frame:
        ld      hl, #title_logo_index
        add     hl, de
        add     hl, de                  ; HL → адрес записи кадра
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a
        ld      b, (hl)                 ; B = число выводов
        inc     hl
        call    title_play

        ; --- строки: выводов counts[min((кадр − первый + 1) · 3, n)] ------------------------------------
        ld      hl, #title_lines
        ld      b, #TITLE_LINES
title_line:
        push    bc
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE = первый кадр строки
        inc     hl
        ld      c, (hl)                 ; C = n (видимых знаков строки)
        inc     hl
        ld      (title_line_ptr), hl    ; → адреса счётчиков и выводов
        ld      hl, (title_frame)
        or      a, a
        sbc     hl, de                  ; кадр − первый
        jr      c, title_line_next      ; кадр < первого: видимых знаков 0
        inc     hl                      ; шаг = кадр − первый + 1 (1…65535)
        ld      a, h
        or      a, a
        jr      z, title_step_byte
        ld      hl, #255                ; шаг ≥ 256: насыщение
title_step_byte:
        ld      de, #title_scaled
        add     hl, de
        ld      a, (hl)                 ; A = min(шаг · 3, 255)
        cp      a, c
        jr      c, title_visible
        ld      a, c                    ; не больше n
title_visible:
        ld      hl, (title_line_ptr)
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE → счётчики
        inc     hl
        push    hl
        ex      de, hl
        ld      e, a
        ld      d, #0
        add     hl, de
        ld      b, (hl)                 ; B = выводов при A видимых знаках
        pop     hl
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a                    ; HL → выводы строки
        call    title_play
title_line_next:
        ld      hl, (title_line_ptr)
        inc     hl
        inc     hl
        inc     hl
        inc     hl                      ; следующая строка таблицы
        pop     bc
        djnz    title_line

        ; --- старт запрошен: строка «GAME STARTING» вместо приглашения ------------------------------------------
        ld      a, (title_starting_flag)
        or      a, a
        jr      z, title_prompt_check
        ld      hl, #title_starting
        ld      b, (hl)
        inc     hl
        jr      title_play              ; вывод и возврат
title_prompt_check:
        ; --- приглашение: кадр ≥ FIRST и ((кадр − FIRST) & MASK) < VISIBLE --------------------------------
        ld      hl, (title_frame)
        ld      de, #TITLE_PROMPT_FIRST
        or      a, a
        sbc     hl, de
        ret     c
        ld      a, (title_low)
        sub     a, #<TITLE_PROMPT_FIRST ; (кадр − FIRST) по модулю 256
        and     a, #TITLE_PROMPT_MASK
        cp      a, #TITLE_PROMPT_VISIBLE
        ret     nc
        ld      hl, #title_prompt
        ld      b, (hl)
        inc     hl
        ; вывод записей приглашения и возврат

; Вывод B записей с HL: изображение, x, y (по 2 байта) — p2c_blit16 (HL image, DE x, в стеке y).
; Портит все регистры, кроме IX.
title_play:
        ld      a, b
        or      a, a
        ret     z
title_play_next:
        ld      (title_count), a
        ld      c, (hl)
        inc     hl
        ld      b, (hl)                 ; BC = изображение
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE = x
        inc     hl
        ld      a, (hl)
        inc     hl
        push    hl
        ld      h, (hl)
        ld      l, a                    ; HL = y
        ex      (sp), hl                ; в стеке y; HL → старший байт y
        inc     hl
        ld      (title_ptr), hl         ; следующая запись
        ld      h, b
        ld      l, c                    ; HL = изображение
        call    _p2c_blit16             ; снимает y
        ld      hl, (title_ptr)
        ld      a, (title_count)
        dec     a
        jr      nz, title_play_next
        ret

title_frame:
        .dw     0                       ; кадр, насыщенный до 16 бит
title_low:
        .db     0
title_starting_flag:
        .db     0                       ; поле starting кадра (≠ 0 — старт запрошен)
title_count:
        .db     0
title_ptr:
        .dw     0
title_line_ptr:
        .dw     0

        .include "p2c_z80_title.inc"
