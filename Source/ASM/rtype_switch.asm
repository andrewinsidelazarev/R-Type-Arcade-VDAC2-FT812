; Страница переключения (окно #C000): вызов машины (переведённый код ROM, v30z80) из цикла
; app.main (код p2c). Раскладки окон у них разные: машина — резидент RTYPE_A_RESIDENT в #0000,
; рабочее ОЗУ V30 в #4000, свой стек; p2c — резидент RTYPE_B_RESIDENT и страницы данных
; RTYPE_B_DATA1/RTYPE_B_DATA2. Вход из p2c_z80_switch.s: A' — номер вызова, HL' и E' —
; аргументы. Вход машины #0003 возвращается с этой страницей в окне #C000 и результатом в DE.
; Константы — из rtype_spg.py (Build/V30Z80/rtype_switch.inc).
                INCLUDE "rtype_switch.inc"
                ORG #C000
SwitchEnter:    ld a,RTYPE_A_RESIDENT
                ld bc,#10AF
                out (c),a                       ; окно #0000 — резидент машины
                ld sp,RTYPE_A_STACK
                ld a,RTYPE_A_WORK
                ld bc,#11AF
                out (c),a                       ; окно #4000 — рабочее ОЗУ V30
                exx                             ; HL, E — аргументы
                ex af,af'                       ; A — номер вызова
                call RTYPE_A_API
                exx                             ; результат DE — в теневой набор
                ld a,RTYPE_B_DATA1
                ld bc,#11AF
                out (c),a
                ld a,RTYPE_B_DATA2
                ld bc,#12AF
                out (c),a
                ld a,RTYPE_B_RESIDENT
                ld bc,#10AF
                out (c),a                       ; окно #0000 — резидент p2c
                jp RTYPE_B_RETURN

; Вызов машины из загрузчика SPG (rtype_boot.asm, с 2026-09-27: пак уровней и звуки — под шкалой экрана загрузки, а
; не чёрной паузой в начале игры). Загрузчик и его стек — в окне #4000 (страница RTYPE_BOOT_PAGE), эта страница — в
; #C000. A — номер вызова, HL и E — аргументы, как у SwitchEnter; возврат — результат в DE, окно #4000 и стек
; загрузчика на месте (окно #0000 остаётся резидентом машины, #8000 — каким его оставила машина). Прерывания
; запрещены. Адрес входа постоянный — его знает загрузчик (RTYPE_BOOT_CALL, rtype_spg.py).
                ASSERT $ <= #C080
                DS #C080-$
BootCall:       ld (BootSp),sp
                ex af,af'                       ; A' — номер вызова
                ld a,RTYPE_A_RESIDENT
                ld bc,#10AF
                out (c),a                       ; окно #0000 — резидент машины
                ld sp,RTYPE_A_STACK
                ld a,RTYPE_A_WORK
                ld bc,#11AF
                out (c),a                       ; окно #4000 — рабочее ОЗУ V30
                ex af,af'
                call RTYPE_A_API
                ld a,RTYPE_BOOT_PAGE
                ld bc,#11AF
                out (c),a                       ; окно #4000 — снова загрузчик SPG
                ld sp,(BootSp)
                ret
BootSp:         dw 0
SwitchEnd:
                ASSERT SwitchEnd < #C100
