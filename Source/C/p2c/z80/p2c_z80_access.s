; Доступ к элементам страничных списков p2c на TS-Config (резидент).
;
; Страничный список хранит в data адрес внутри окна #C000 первой логической
; страницы, в page — её номер; физическую страницу даёт таблица p2c_page_map.
; Элемент копируется в кольцевой буфер: указатель на копию остаётся верным и
; после возврата банка кода в окно #C000.
        .module p2c_z80_access
        .globl  _p2c_z80_at_paged
        .globl  _p2c_page_map
        .globl  _p2c_bank

        .area   _DATA
p2c_ring:           .ds 256
p2c_ring_cursor:    .ds 1
p2c_acc_page:       .ds 1

        .area   _CODE

; void *p2c_z80_at_paged(const void *list, uint16_t index, uint8_t size)
; Вход: HL — список, DE — индекс, байт размера элемента на стеке (снимает вызываемая).
; Выход: DE — адрес копии элемента. IX не трогается.
_p2c_z80_at_paged::
        ld      iy, #2
        add     iy, sp
        ld      c, 0 (iy)               ; C = размер элемента
        push    hl
        pop     iy                      ; IY = список
        ex      de, hl                  ; HL = индекс
        ld      a, c
        dec     a
        jr      z, at_offset            ; размер 1
        dec     a
        jr      z, at_size2
        sub     #2
        jr      z, at_size4
        ld      a, c                    ; прочие размеры: HL = индекс * C
        ex      de, hl
        ld      hl, #0
        ld      b, #8
at_mul:
        add     hl, hl
        rla
        jr      nc, at_mul_next
        add     hl, de
at_mul_next:
        djnz    at_mul
        jr      at_offset
at_size4:
        add     hl, hl
at_size2:
        add     hl, hl
at_offset:
        ld      e, 6 (iy)
        ld      a, 7 (iy)
        sub     #0xC0
        ld      d, a                    ; DE = начало данных внутри первой страницы
        add     hl, de                  ; HL = смещение элемента; перенос — ещё 4 страницы
        sbc     a, a
        and     #4
        ld      b, a
        ld      a, h
        rlca
        rlca
        and     #3
        add     a, b
        add     a, 8 (iy)
        ld      (p2c_acc_page), a       ; логическая страница элемента
        ld      a, h
        or      #0xC0
        ld      h, a                    ; HL = адрес элемента в окне #C000
        ; Место под копию в кольцевом буфере.
        ld      a, (p2c_ring_cursor)
        ld      e, a
        add     a, c
        jr      nc, at_ring
        ld      e, #0
        ld      a, c
at_ring:
        ld      (p2c_ring_cursor), a
        ld      d, #0
        push    hl
        ld      hl, #p2c_ring
        add     hl, de
        ex      de, hl                  ; DE = копия
        pop     hl
        push    de                      ; результат
        ; Элемент переходит на следующую страницу, если HL + размер - 1 > #FFFF.
        ld      a, c
        dec     a
        add     a, l
        ld      a, h
        adc     a, #0
        jr      c, at_straddle
        call    p2c_acc_map
        ld      b, #0
        ldir
at_done:
        ld      a, (_p2c_bank)
        ld      bc, #0x13AF
        out     (c), a
        pop     de                      ; DE = копия элемента
        pop     iy                      ; адрес возврата
        inc     sp                      ; байт размера
        jp      (iy)

; Элемент на границе страниц: побайтно, на #0000 — следующая логическая страница.
at_straddle:
        call    p2c_acc_map
at_straddle_byte:
        ld      a, (hl)
        ld      (de), a
        inc     de
        inc     hl
        ld      a, h
        or      l
        jr      nz, at_straddle_next
        ld      hl, #p2c_acc_page
        inc     (hl)
        ld      hl, #0xC000
        call    p2c_acc_map
at_straddle_next:
        dec     c
        jr      nz, at_straddle_byte
        jr      at_done

; Логическая страница p2c_acc_page — в окно #C000. Портит A, сохраняет BC, DE, HL.
p2c_acc_map:
        push    bc
        push    hl
        ld      a, (p2c_acc_page)
        ld      hl, #_p2c_page_map
        add     a, l
        ld      l, a
        adc     a, h
        sub     l
        ld      h, a
        ld      a, (hl)
        ld      bc, #0x13AF
        out     (c), a
        pop     hl
        pop     bc
        ret
