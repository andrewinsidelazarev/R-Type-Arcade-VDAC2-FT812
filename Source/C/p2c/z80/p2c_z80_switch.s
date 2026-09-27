; Вызов машины (переведённый код ROM в своей раскладке окон) из кода p2c, резидент.
;
; Машина исполняется со своим резидентом в окне #0000 и своим стеком. Переход — через
; страницу переключения _p2c_switch_page в окне #C000 (Build: rtype_spg.py): она ставит
; окна машины, вызывает её вход #0003 и возвращается сюда, восстановив окна p2c.
; Аргументы и номер вызова переносятся теневым набором регистров и A'.
; IX — указатель кадра SDCC (вызываемый обязан его сохранить), машина же пользуется IX и IY:
; оба сохраняются на стеке p2c на время вызова.
        .module p2c_z80_switch
        .globl  _p2c_switch_call
        .globl  _p2c_switch_return
        .globl  _p2c_port_arg
        .globl  _p2c_port_flags
        .globl  _p2c_port_result
        .globl  _p2c_bank
        .globl  _p2c_switch_page

        .area   _CODE

; void p2c_switch_call(uint8_t api) __z88dk_fastcall — L: номер вызова машины.
_p2c_switch_call::
        push    ix
        push    iy
        ld      a, l
        ex      af, af'
        ld      hl, (_p2c_port_arg)
        ld      a, (_p2c_port_flags)
        ld      e, a
        exx
        ld      (p2c_switch_sp), sp
        ld      a, #_p2c_switch_page
        ld      bc, #0x13AF
        out     (c), a
        jp      0xC000

; Возврат со страницы переключения: окна #0000–#BFFF снова p2c, результат — DE теневого набора.
_p2c_switch_return::
        ld      sp, (p2c_switch_sp)
        exx
        ld      (_p2c_port_result), de
        pop     iy
        pop     ix
        ld      a, (_p2c_bank)
        ld      bc, #0x13AF
        out     (c), a
        ret

        .area   _DATA
p2c_switch_sp:
        .ds     2
