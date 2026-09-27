; Быстрый путь вывода изображения адаптера FT812 (резидент): вывод изображения, уже лежащего в RAM_G,
; пишет те же слова display list в том же порядке, что p2c_blit_c и p2c_ft_draw_entry на C
; (p2c_z80_ft812.c). Остальные случаи уходят в код C со стеком возврат, x, y по 4 байта: строка
; отладочного текста (p2c_blit_c), чужой вывод, неоткрытый список, нет записи каталога, переполнение
; display list, загрузка изображения, смена размеров BITMAP_LAYOUT класса C (p2c_ft_draw_entry).
;
; Входы (sdcccall 1, аргументы стека снимает вызываемая функция, сохраняется только IX):
;   void p2c_blit(P2cImage image, int32_t x, int32_t y)   — HL image; в стеке возврат, x, y (по 4 байта);
;   void p2c_blit16(P2cImage image, int16_t x, int16_t y) — HL image, DE x; в стеке возврат, y.
        .module p2c_z80_blit
        .include "p2c_z80_config.inc"
        .globl  _p2c_blit
        .globl  _p2c_blit16
        .globl  _p2c_blit_c
        .globl  _p2c_ft_draw_entry
        .globl  _p2c_dl_flush
        .globl  _p2c_bank
        .globl  _p2c_ft_foreign
        .globl  _p2c_ft_list_open
        .globl  _p2c_ft_frame
        .globl  _p2c_ft_drawn
        .globl  _p2c_ft_handle
        .globl  _p2c_ft_cell
        .globl  _p2c_ft_c_w
        .globl  _p2c_ft_c_h
        .globl  _p2c_ft_blits
        .globl  _p2c_dl_fill
        .globl  _p2c_dl_sent

PORT_PAGE3 = 0x13AF             ; окно #C000 TS-Config
FT_DL_LIMIT = 8184              ; p2c_z80_ft812.h: 2046 команд
FT_HANDLE_C = 15

        .area   _CODE

; --- входы -------------------------------------------------------------------------------------------

_p2c_blit16::
        ld      (blit_image), hl
        ld      (blit_x16), de
        pop     bc                      ; возврат
        pop     de                      ; y
        push    de
        push    bc
        ld      (blit_y16), de
        ld      a, #1
        ld      (blit_mode), a          ; режим 1: в стеке y (2 байта)
        xor     a, a
        ld      (blit_far), a
        ld      a, h
        and     a, #0xC0
        cp      a, #0xC0
        jp      z, blit_text16          ; строка отладочного текста — код C
        jr      blit_common

_p2c_blit::
        ld      a, h
        and     a, #0xC0
        cp      a, #0xC0
        jp      z, _p2c_blit_c          ; image & #C000 = #C000: строка отладочного текста
        ld      (blit_image), hl
        xor     a, a
        ld      (blit_mode), a          ; режим 0: в стеке x, y по 4 байта
        ld      (blit_far), a
        ; x, y — в 16 бит; не помещающееся значение заведомо вне экрана (blit_far)
        ld      hl, #2
        add     hl, sp                  ; → x
        call    blit_narrow
        ld      (blit_x16), de
        jr      z, blit_x_near
        ld      a, #1
        ld      (blit_far), a
blit_x_near:
        call    blit_narrow             ; → y
        ld      (blit_y16), de
        jr      z, blit_y_near
        ld      a, #1
        ld      (blit_far), a
blit_y_near:
        ld      hl, (blit_image)

; --- общий путь: HL — image, x и y — blit_x16, blit_y16 -------------------------------------------------
blit_common:
        bit     7, h
        jr      z, blit_table
        ld      a, h
        and     a, #0x3F
        ld      h, a                    ; индекс = image & #3FFF
        jr      blit_index
blit_table:
        ld      a, h
        rlca
        rlca
        rlca
        and     a, #0x07
        add     a, #P2C_FT_IMAGE_PAGE   ; страница = P2C_FT_IMAGE_PAGE + (image >> 13)
        ld      bc, #PORT_PAGE3
        out     (c), a
        ld      a, h
        and     a, #0x1F
        ld      h, a
        add     hl, hl                  ; HL = (image & #1FFF) · 2
        ld      a, h
        add     a, #0xC0
        ld      h, a
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a                    ; индекс = слово таблицы изображений
blit_index:
        ld      (blit_index_word), hl
        ld      a, (_p2c_ft_foreign)
        or      a, a
        jp      nz, blit_slow           ; чужой вывод: затемнение и сброс — код C
        ld      a, (_p2c_ft_list_open)
        or      a, a
        jp      z, blit_slow            ; заголовок display list кадра — код C
        ld      (blit_ix), ix
        ; запись: страница P2C_FT_ENTRY_PAGE + (индекс >> 10), адрес #C000 + (индекс & 1023) · 16
        ld      a, h
        rrca
        rrca
        and     a, #0x3F
        add     a, #P2C_FT_ENTRY_PAGE
        ld      bc, #PORT_PAGE3
        out     (c), a
        ld      a, h
        and     a, #0x03
        ld      h, a
        add     hl, hl
        add     hl, hl
        add     hl, hl
        add     hl, hl
        ld      a, h
        add     a, #0xC0
        ld      h, a
        push    hl
        pop     ix                      ; IX → запись (cls, flags, w, h, …, state[3], used)
        ld      a, 0 (ix)
        inc     a
        jp      z, blit_slow_ix         ; cls = #FF: изображения нет, счётчик пропусков ведёт C
        ld      a, (blit_far)
        or      a, a
        jp      nz, blit_done           ; x или y вне int16 — вне экрана

        ; --- видимость: x ∈ [-320, 639], y ∈ [-320, 479], x + w > 0, y + h > 0 ------------------------
        ld      hl, (blit_x16)
        ld      de, #320
        add     hl, de                  ; HL = x + 320 (по модулю 65536)
        ld      a, h                    ; видимо при x + 320 < 960 (#03C0)
        cp      a, #0x03
        jr      c, blit_x_in
        jp      nz, blit_done
        ld      a, l
        cp      a, #0xC0
        jp      nc, blit_done
blit_x_in:
        ld      (blit_x), hl
        ld      e, 2 (ix)
        ld      d, 3 (ix)               ; DE = w
        add     hl, de
        jr      c, blit_x_seen          ; (x + 320) + w > 65535 > 320
        ld      de, #321
        or      a, a
        sbc     hl, de
        jp      c, blit_done            ; (x + 320) + w ≤ 320: x + w ≤ 0
blit_x_seen:
        ld      hl, (blit_y16)
        ld      de, #320
        add     hl, de
        ld      a, h                    ; y + 320 < 800 (#0320)
        cp      a, #0x03
        jr      c, blit_y_in
        jp      nz, blit_done
        ld      a, l
        cp      a, #0x20
        jp      nc, blit_done
blit_y_in:
        ld      (blit_y), hl
        ld      e, 4 (ix)
        ld      d, 5 (ix)               ; DE = h
        add     hl, de
        jr      c, blit_y_seen
        ld      de, #321
        or      a, a
        sbc     hl, de
        jp      c, blit_done            ; y + h ≤ 0
blit_y_seen:
        ; сплошной чёрный глиф до первого вывода кадра не выводится
        bit     0, 1 (ix)
        jr      z, blit_flags_ok
        ld      a, (_p2c_ft_drawn)
        or      a, a
        jp      z, blit_done
blit_flags_ok:
        ; p2c_dl_sent + p2c_dl_fill + 32 > FT_DL_LIMIT — переполнение, считает код C
        ld      hl, (_p2c_dl_sent)
        ld      de, (_p2c_dl_fill)
        add     hl, de
        ld      de, #32 - FT_DL_LIMIT - 1
        add     hl, de
        jp      c, blit_slow_ix         ; sent + fill + 32 ≥ 8185
        ld      a, 0 (ix)
        cp      a, #2
        jr      nc, blit_class_c

        ; --- классы A и B: слот загружен ---------------------------------------------------------------
        ld      l, 12 (ix)
        ld      h, 13 (ix)              ; HL = слот
        ld      a, h
        or      a, l
        jp      z, blit_slow_ix         ; слот не выделен: загрузка — код C
        ld      a, (_p2c_ft_frame)
        cp      a, 15 (ix)
        jr      z, blit_used
        ld      15 (ix), a              ; used = кадр (запись состояния каталога)
blit_used:
        dec     hl                      ; HL = слот − 1
        ld      a, l
        and     a, #0x7F
        ld      c, a                    ; C = cell = (слот − 1) & 127
        add     hl, hl                  ; H = (слот − 1) >> 7
        ld      a, 0 (ix)
        or      a, a
        ld      a, h
        jr      z, blit_handle_a
        add     a, #P2C_FT_A_HANDLES    ; класс B: после handle класса A
blit_handle_a:
        ld      hl, #_p2c_ft_handle
        cp      a, (hl)
        jr      z, blit_same_handle
        ld      (hl), a
        push    bc
        ld      e, a
        ld      d, #0
        ld      bc, #0x0500             ; BITMAP_HANDLE: байты E, D, C = 0, B = #05
        call    blit_dl
        pop     bc
blit_same_handle:
        ld      a, c
        ld      hl, #_p2c_ft_cell
        cp      a, (hl)
        jr      z, blit_vertex
        ld      (hl), a
        ld      e, a
        ld      d, #0
        ld      bc, #0x0600             ; CELL
        call    blit_dl
        jr      blit_vertex

        ; --- класс C: изображение по адресу, размеры BITMAP_LAYOUT/SIZE не меняются ---------------------
blit_class_c:
        ld      a, 12 (ix)
        or      a, 13 (ix)
        or      a, 14 (ix)
        jp      z, blit_slow_ix         ; не загружено: загрузка — код C
        ld      hl, (_p2c_ft_c_w)
        ld      e, 2 (ix)
        ld      d, 3 (ix)
        or      a, a
        sbc     hl, de
        jp      nz, blit_slow_ix        ; другой размер: слова BITMAP_LAYOUT/SIZE — код C
        ld      hl, (_p2c_ft_c_h)
        ld      e, 4 (ix)
        ld      d, 5 (ix)
        sbc     hl, de                  ; CF = 0 после вычитания с нулевым результатом
        jp      nz, blit_slow_ix
        ld      hl, #_p2c_ft_handle
        ld      a, (hl)
        cp      a, #FT_HANDLE_C
        jr      z, blit_c_handle
        ld      (hl), #FT_HANDLE_C
        ld      de, #FT_HANDLE_C
        ld      bc, #0x0500             ; BITMAP_HANDLE 15
        call    blit_dl
blit_c_handle:
        ld      hl, #_p2c_ft_cell
        ld      a, (hl)
        or      a, a
        jr      z, blit_c_cell
        ld      (hl), #0
        ld      de, #0
        ld      bc, #0x0600             ; CELL 0: после ячейки слота
        call    blit_dl
blit_c_cell:
        ld      e, 12 (ix)
        ld      d, 13 (ix)
        ld      c, 14 (ix)
        ld      b, #0x01                ; BITMAP_SOURCE адрес
        call    blit_dl

        ; --- вершина: X — 3 байта на X с -320 (#C000), Y — 2 байта с #1000 (#D000), страница таблиц ------
blit_vertex:
        ld      a, #P2C_FT_TABLE_PAGE
        ld      bc, #PORT_PAGE3
        out     (c), a
        ld      hl, (blit_y)
        add     hl, hl
        ld      a, h
        add     a, #0xD0
        ld      h, a                    ; HL → yb = #D000 + (y + 320) · 2
        ld      e, (hl)                 ; E = yb[0]
        inc     hl
        ld      a, (hl)                 ; A = yb[1]
        push    af
        ld      hl, (blit_x)
        ld      b, h
        ld      c, l
        add     hl, hl
        add     hl, bc                  ; HL = (x + 320) · 3
        ld      a, h
        add     a, #0xC0
        ld      h, a                    ; HL → xb
        ld      b, (hl)                 ; B = xb[0]
        inc     hl
        ld      c, (hl)                 ; C = xb[1]
        inc     hl
        ld      a, (hl)                 ; xb[2]
        or      a, e
        ld      d, a                    ; D = yb[0] | xb[2]
        pop     af
        ld      e, a                    ; E = yb[1]
        call    blit_dl                 ; слово: yb[1], yb[0] | xb[2], xb[1], xb[0]
        ld      a, #1
        ld      (_p2c_ft_drawn), a
        ld      hl, (_p2c_ft_blits)
        inc     hl
        ld      (_p2c_ft_blits), hl

; --- выходы ------------------------------------------------------------------------------------------------

blit_done:
        ; выведено или вне экрана: окно #C000 — банк вызывающего, IX — прежний, снять аргументы стека
        ld      ix, (blit_ix)
        ld      a, (_p2c_bank)
        ld      bc, #PORT_PAGE3
        out     (c), a
        ld      a, (blit_mode)
        pop     hl                      ; возврат
        or      a, a
        jr      nz, blit_done16
        pop     bc                      ; x, y по 4 байта
        pop     bc
        pop     bc
blit_done16:
        pop     bc                      ; y (режим 1)
        jp      (hl)

blit_slow_ix:
        ld      ix, (blit_ix)
blit_slow:
        ld      a, (_p2c_bank)
        ld      bc, #PORT_PAGE3
        out     (c), a
        ld      hl, (blit_index_word)
        ld      a, (blit_mode)
        or      a, a
        jp      z, _p2c_ft_draw_entry   ; HL — индекс, стек: возврат, x, y
        call    blit_widen
        ld      hl, (blit_index_word)
        jp      _p2c_ft_draw_entry

blit_text16:
        call    blit_widen
        ld      hl, (blit_image)
        jp      _p2c_blit_c

; Стек режима 1 (возврат вызывающего, y) → возврат, x, y по 4 байта со знаковым расширением.
; Вызывается командой call: собственный адрес возврата снимается первым. IX не трогает.
blit_widen:
        pop     hl
        ld      (blit_widen_return), hl
        pop     bc                      ; возврат вызывающего
        pop     de                      ; y (2 байта)
        ld      de, (blit_y16)
        ld      a, d
        rla
        sbc     a, a
        ld      h, a
        ld      l, a
        push    hl                      ; старшее слово y
        push    de                      ; младшее слово y
        ld      de, (blit_x16)
        ld      a, d
        rla
        sbc     a, a
        ld      h, a
        ld      l, a
        push    hl                      ; старшее слово x
        push    de                      ; младшее слово x
        push    bc                      ; возврат вызывающего
        ld      hl, (blit_widen_return)
        jp      (hl)

; Значение int32 по HL → DE — младшее слово; Z, если старшее слово — знаковое расширение младшего
; (значение помещается в int16). HL += 4. Портит A.
blit_narrow:
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      a, d
        rla
        sbc     a, a                    ; A = знак младшего слова (#00 или #FF)
        cp      a, (hl)
        inc     hl
        jr      nz, blit_narrow_far
        cp      a, (hl)
blit_narrow_far:
        inc     hl
        ret

; Слово display list: E, D, C, B — байты от младшего. Буфер #3600 (p2c_dl_buffer) на 256 байт;
; полный буфер уходит в RAM_DL (p2c_dl_flush). Портит AF, HL; при сбросе буфера — все, кроме IX.
blit_dl:
        ld      a, (_p2c_dl_fill + 1)
        or      a, a
        jr      z, blit_dl_room         ; заполнено < 256
        push    bc
        push    de
        call    _p2c_dl_flush
        pop     de
        pop     bc
blit_dl_room:
        ld      a, (_p2c_dl_fill)
        ld      l, a
        ld      h, #>P2C_Z80_DL_BUFFER
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      (hl), c
        inc     hl
        ld      (hl), b
        ld      hl, (_p2c_dl_fill)
        inc     hl
        inc     hl
        inc     hl
        inc     hl
        ld      (_p2c_dl_fill), hl
        ret

        .area   _DATA
blit_image:
        .ds     2
blit_index_word:
        .ds     2
blit_x16:
        .ds     2
blit_y16:
        .ds     2
blit_x:
        .ds     2                       ; x + 320
blit_y:
        .ds     2                       ; y + 320
blit_ix:
        .ds     2
blit_widen_return:
        .ds     2
blit_mode:
        .ds     1
blit_far:
        .ds     1
