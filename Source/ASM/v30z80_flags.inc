; Флаги, сдвиги, десятичная коррекция и строковые команды V30 для переведённого кода.
; Семантика — как у эталона (unicorn на QEMU): AF после логики и сдвигов 0, флаги сдвигов
; по последнему шагу, у RCL/RCR меняются только CF и OF.

FLG_R           DW 0            ; результат 16-битной операции
FLG_X           DB 0            ; (приёмник ^ источник) младший байт для AF
TARGET_IP       DW 0
SH_PREV         DW 0
SH_SRC8         DB 0

; Запись OF (бит 11 FLAGS): B = 0/1.
SET_OF_B:       ld hl,V_FL+1
                res 3,(hl)
                ld a,b
                or a
                ret z
                set 3,(hl)
                ret

; Младший байт FLAGS: A = S|Z|A|C-часть, E = младший байт результата → + PF и бит 1.
STORE_LOW_PE:   ld d,0
                ld hl,PARITY
                add hl,de
                or (hl)
                or #02
                ld (V_FL),a
                ret

; После 8-битных add/adc/sub/sbc/cmp: B = результат, C = F Z80.
FLG_AR8:        ld e,b
                ld a,c
                and #D1
                call STORE_LOW_PE
                ld b,0
                bit 2,c
                jp z,SET_OF_B
                inc b
                jp SET_OF_B

; После 8-битных and/or/xor/test: B = результат. CF = OF = AF = 0.
FLG_LOG8:       ld a,b
                and #80
                ld c,a
                ld a,b
                or a
                jr nz,.nz
                set 6,c
.nz:            ld e,b
                ld a,c
                call STORE_LOW_PE
                ld b,0
                jp SET_OF_B

; После 8-битных inc/dec: B = результат, C = F Z80; CF x86 сохраняется.
FLG_INC8:       ld a,(V_FL)
                and #01
                ld d,a
                ld a,c
                and #D0
                or d
                ld e,b
                call STORE_LOW_PE
                ld b,0
                bit 2,c
                jp z,SET_OF_B
                inc b
                jp SET_OF_B

; После 16-битных adc/sbc hl,de: (FLG_R) = результат, (FLG_X) = (dst^src) мл. байт, C = F Z80.
FLG_AR16:       ld hl,(FLG_R)
                ld a,(FLG_X)
                xor l
                and #10
                ld b,a
                ld e,l
                ld a,c
                and #C1
                or b
                call STORE_LOW_PE
                ld b,0
                bit 2,c
                jp z,SET_OF_B
                inc b
                jp SET_OF_B

; После 16-битных and/or/xor/test: (FLG_R) = результат.
FLG_LOG16:      ld hl,(FLG_R)
                ld a,h
                and #80
                ld c,a
                ld a,h
                or l
                jr nz,.nz
                set 6,c
.nz:            ld e,l
                ld a,c
                call STORE_LOW_PE
                ld b,0
                jp SET_OF_B

; После 16-битных inc/dec: (FLG_R) = результат, E = 1 inc / 0 dec. CF сохраняется.
FLG_INC16:      ld hl,(FLG_R)
                ld a,(V_FL)
                and #01
                ld c,a
                ld a,h
                and #80
                or c
                ld c,a
                ld a,h
                or l
                jr nz,.nz
                set 6,c
.nz:            ld b,0
                ld a,l
                and #0F
                bit 0,e
                jr z,.dec
                or a
                jr nz,.ofInc
                set 4,c
.ofInc:         ld a,h
                cp #80
                jr nz,.store
                ld a,l
                or a
                jr nz,.store
                inc b
                jr .store
.dec:           cp #0F
                jr nz,.ofDec
                set 4,c
.ofDec:         ld a,h
                cp #7F
                jr nz,.store
                ld a,l
                cp #FF
                jr nz,.store
                inc b
.store:         ld e,l
                ld a,c
                push bc
                call STORE_LOW_PE
                pop bc
                jp SET_OF_B

; Флаги SHL/SHR: HL (16) или A (8) = результат, C = CF (0/1), B = OF (0/1); AF = 0.
FLG_SHIFT16:    push hl
                ld a,h
                and #80
                or c
                ld c,a
                ld a,h
                or l
                jr nz,.nz
                set 6,c
.nz:            ld e,l
                ld a,c
                call STORE_LOW_PE
                call SET_OF_B
                pop hl
                ret
FLG_SHIFT8:     push af
                ld e,a
                and #80
                or c
                ld c,a
                ld a,e
                or a
                jr nz,.nz
                set 6,c
.nz:            ld a,c
                call STORE_LOW_PE
                call SET_OF_B
                pop af
                ret

; SHL16: HL = значение, B = счётчик → HL. Счётчик & #1F == 0 — без изменений.
SH_SHL16:       ld a,b
                and #1F
                ret z
                ld b,a
.loop:          ld (SH_PREV),hl
                add hl,hl
                djnz .loop
                ld de,(SH_PREV)
                ld a,d
                rlca
                and 1
                ld c,a
                ld a,d
                xor h
                rlca
                and 1
                ld b,a
                jp FLG_SHIFT16
; SHR16: CF — бит 0 значения перед последним шагом, OF — бит 15 (перед ^ результат).
SH_SHR16:       ld a,b
                and #1F
                ret z
                ld b,a
.loop:          ld (SH_PREV),hl
                srl h
                rr l
                djnz .loop
                ld de,(SH_PREV)
                ld a,e
                and 1
                ld c,a
                ld a,d
                xor h
                rlca
                and 1
                ld b,a
                jp FLG_SHIFT16
; SAR16: как SHR16, но старший бит сохраняется; OF = 0 (бит 15 результата равен исходному).
SH_SAR16:       ld a,b
                and #1F
                ret z
                ld b,a
.loop:          ld (SH_PREV),hl
                sra h
                rr l
                djnz .loop
                ld de,(SH_PREV)
                ld a,e
                and 1
                ld c,a
                ld b,0
                jp FLG_SHIFT16
; SHL8: A = значение, B = счётчик → A.
SH_SHL8:        ld c,a
                ld a,b
                and #1F
                ld a,c
                ret z
                ld a,b
                and #1F
                ld b,a
                ld a,c
.loop:          ld (SH_SRC8),a
                add a,a
                djnz .loop
                ld e,a
                ld a,(SH_SRC8)
                ld d,a
                rlca
                and 1
                ld c,a
                ld a,d
                xor e
                rlca
                and 1
                ld b,a
                ld a,e
                jp FLG_SHIFT8
SH_SHR8:        ld c,a
                ld a,b
                and #1F
                ld a,c
                ret z
                ld a,b
                and #1F
                ld b,a
                ld a,c
.loop:          ld (SH_SRC8),a
                srl a
                djnz .loop
                ld e,a
                ld a,(SH_SRC8)
                ld d,a
                and 1
                ld c,a
                ld a,d
                xor e
                rlca
                and 1
                ld b,a
                ld a,e
                jp FLG_SHIFT8

; RCL8/RCR8: A = значение, B = счётчик; счётчик = (& #1F) mod 9; меняются только CF и OF.
RC_COUNT:       ld c,a
                ld a,b
                and #1F
.mod:           cp 9
                jr c,.done
                sub 9
                jr .mod
.done:          ld b,a
                ld a,c
                ret
SH_RCL8:        call RC_COUNT
                inc b
                dec b
                ret z
                ld (SH_SRC8),a
                ld c,a
                ld a,(V_FL)
                rra
                ld a,c
.loop:          rla
                djnz .loop
                jp RC_FLAGS
SH_RCR8:        call RC_COUNT
                inc b
                dec b
                ret z
                ld (SH_SRC8),a
                ld c,a
                ld a,(V_FL)
                rra
                ld a,c
.loop:          rra
                djnz .loop
; Флаги RCL/RCR: CF = перенос Z80, OF = бит 7 (исходное ^ результат); A сохраняется.
RC_FLAGS:       push af
                ld hl,V_FL
                res 0,(hl)
                jr nc,.nc
                set 0,(hl)
.nc:            ld c,a
                ld a,(SH_SRC8)
                xor c
                rlca
                and 1
                ld b,a
                call SET_OF_B
                pop af
                ret

; DAA/DAS над AL — по helper_daa/helper_das QEMU.
DAA_OP:         ld a,(V_FL)
                ld c,a
                ld a,(V_AX)
                ld b,a
                ld d,a                  ; старое AL
                ld e,0
                and #0F
                cp #0A
                jr nc,.adj1
                bit 4,c
                jr z,.no1
.adj1:          ld a,b
                add a,6
                ld b,a
                set 4,e
.no1:           ld a,d
                cp #9A
                jr nc,.adj2
                bit 0,c
                jr z,.no2
.adj2:          ld a,b
                add a,#60
                ld b,a
                set 0,e
.no2:           ld a,b
                jp DAX_STORE
DAS_OP:         ld a,(V_FL)
                ld c,a
                ld a,(V_AX)
                ld b,a
                ld d,a                  ; al1
                ld e,0
                and #0F
                cp #0A
                jr nc,.adj1
                bit 4,c
                jr z,.no1
.adj1:          set 4,e
                ld a,d
                cp 6
                jr c,.cf1
                bit 0,c
                jr z,.sub6
.cf1:           set 0,e
.sub6:          ld a,b
                sub 6
                ld b,a
.no1:           ld a,d
                cp #9A
                jr nc,.adj2
                bit 0,c
                jr z,.no2
.adj2:          ld a,b
                sub #60
                ld b,a
                set 0,e
.no2:           ld a,b
; AL = A, флаги: E = CF|AF, + ZF, SF, PF; OF = 0.
DAX_STORE:      ld (V_AX),a
                ld b,a
                and #80
                or e
                ld c,a
                ld a,b
                or a
                jr nz,.nz
                set 6,c
.nz:            ld e,b
                ld a,c
                call STORE_LOW_PE
                ld b,0
                jp SET_OF_B

; Условия jl/jge/jle/jg: NZ, если SF != OF (для jle — ещё и при ZF).
COND_SF_XOR_OF: ld a,(V_FL)
                rlca
                and 1
                ld b,a
                ld a,(V_FL+1)
                rrca
                rrca
                rrca
                and 1
                xor b
                ret
COND_LE:        ld a,(V_FL)
                and #40
                ret nz
                jp COND_SF_XOR_OF

; IRET: DE = FLAGS из стека → V_FL как загружает QEMU в реальном режиме.
SET_FLAGS:      ld a,e
                and #D5
                or #02
                ld (V_FL),a
                ld a,d
                and #7F
                ld (V_FL+1),a
                ret

; --- строковые команды ----------------------------------------------------------------------
; Шаг по DF → BC = ±размер (A = размер).
STR_STEP:       ld c,a
                ld b,0
                ld a,(V_FL+1)
                and 4
                ret z
                ld a,c
                neg
                ld c,a
                ld b,#FF
                ret
STR_ADVANCE_SI: ld hl,(V_SI)
                add hl,bc
                ld (V_SI),hl
                ret
STR_ADVANCE_DI: ld hl,(V_DI)
                add hl,bc
                ld (V_DI),hl
                ret
; Z — CX == 0.
CX_ZERO:        ld hl,(V_CX)
                ld a,h
                or l
                ret
CX_DEC:         ld hl,(V_CX)
                dec hl
                ld (V_CX),hl
                ld a,h
                or l
                ret

MOVSB_DS:       ld hl,(V_SI)
                call RB_DS
                ld hl,(V_DI)
                call WB_ES
                ld a,1
                call STR_STEP
                call STR_ADVANCE_SI
                jp STR_ADVANCE_DI
MOVSB_REP_DS:   call CX_ZERO
                ret z
.loop:          call MOVSB_DS
                call CX_DEC
                jr nz,.loop
                ret
MOVSW_DS:       ld hl,(V_SI)
                call RW_DS
                ld hl,(V_DI)
                call WW_ES
                ld a,2
                call STR_STEP
                call STR_ADVANCE_SI
                jp STR_ADVANCE_DI
MOVSW_REP_DS:   call CX_ZERO
                ret z
.loop:          call MOVSW_DS
                call CX_DEC
                jr nz,.loop
                ret
STOSB_DS:       ld hl,(V_DI)
                ld a,(V_AX)
                call WB_ES
                ld a,1
                call STR_STEP
                jp STR_ADVANCE_DI
STOSB_REP_DS:   call CX_ZERO
                ret z
.loop:          call STOSB_DS
                call CX_DEC
                jr nz,.loop
                ret
STOSW_DS:       ld hl,(V_DI)
                ld de,(V_AX)
                call WW_ES
                ld a,2
                call STR_STEP
                jp STR_ADVANCE_DI
STOSW_REP_DS:   call CX_ZERO
                ret z
.loop:          call STOSW_DS
                call CX_DEC
                jr nz,.loop
                ret
LODSW_DS:       ld hl,(V_SI)
                call RW_DS
                ld (V_AX),de
                ld a,2
                call STR_STEP
                jp STR_ADVANCE_SI
