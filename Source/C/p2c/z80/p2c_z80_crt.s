; Резидентная обвязка кода p2c на TS-Config: старт, трамплин банков, отказ.
; Банк кода — страница в окне #C000; номер банка равен номеру страницы.
        .module p2c_z80_crt
        .globl  _p2c_z80_start
        .globl  _p2c_z80_main
        .globl  ___sdcc_bcall_ehl
        .globl  _p2c_raise
        .globl  _p2c_bank
        .globl  _p2c_fault_code
        .globl  _p2c_fault_pc
        .globl  _p2c_fault_bank
        .globl  _p2c_fault_sp
        .globl  _p2c_z80_stack_top
        .globl  _p2c_z80_page_data1
        .globl  s__DATA
        .globl  l__DATA

        .area   _CODE

; Вход из загрузчика: окна уже содержат страницы резидента, данных и банка,
; номер страницы банка в окне #C000 — в регистре A.
_p2c_z80_start::
        di
        ld      sp, #_p2c_z80_stack_top
        push    af
        ; Окно #4000: страница данных резидента (загрузчик исполнялся в нём).
        ld      a, #_p2c_z80_page_data1
        ld      bc, #0x11AF
        out     (c), a
        ; Обнуление _DATA: у кода без crt0 нет инициализации глобальных переменных.
        ld      hl, #s__DATA
        ld      bc, #l__DATA
        ld      a, b
        or      c
        jr      z, p2c_start_main
        ld      (hl), #0
        dec     bc
        ld      a, b
        or      c
        jr      z, p2c_start_main
        ld      d, h
        ld      e, l
        inc     de
        ldir
p2c_start_main:
        pop     af
        ld      (_p2c_bank), a
        call    _p2c_z80_main
p2c_hang:
        di
        halt
        jr      p2c_hang

; Трамплин вызова __banked: E — страница банка, HL — адрес функции.
; На время вызова в стеке один байт с банком вызывающего кода, поэтому
; параметры функции лежат на 3 байта дальше обычного (как ожидает SDCC).
; Результат: A, DE или HLDE — регистры сохраняются при возврате банка.
___sdcc_bcall_ehl::
        ld      a, (_p2c_bank)
        push    af
        inc     sp
        ld      a, e
        ld      (_p2c_bank), a
        ld      bc, #0x13AF
        out     (c), a
        call    p2c_jump_hl
        ld      (p2c_result_a), a
        dec     sp
        pop     af
        ld      (_p2c_bank), a
        ld      bc, #0x13AF
        out     (c), a
        ld      a, (p2c_result_a)
        ret
p2c_jump_hl:
        jp      (hl)

; Отказ (исключение CPython без обработчика): код в HL, место — адрес возврата.
_p2c_raise::
        ld      (_p2c_fault_code), hl
        pop     hl
        ld      (_p2c_fault_pc), hl
        ld      (_p2c_fault_sp), sp
        ld      a, (_p2c_bank)
        ld      (_p2c_fault_bank), a
        ld      a, #2
        ld      bc, #0x0FAF
        out     (c), a
        jr      p2c_hang

        .area   _DATA
_p2c_bank::
        .ds     1
p2c_result_a:
        .ds     1
_p2c_fault_code::
        .ds     2
_p2c_fault_pc::
        .ds     2
_p2c_fault_sp::
        .ds     2
_p2c_fault_bank::
        .ds     1
