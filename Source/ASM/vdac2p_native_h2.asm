; VDAC2+ (2026-09-25, скорость, партия 3): самодостаточные нативные процедуры ROM — во второй странице хоста
; (HOST2_PAGE): $1D6B, $0467, $51EE, $03A6 зовутся только переводом (входы NATIVE с диспетчеризацией сюда,
; codegen.NATIVE_HOST2) и не зовут процедур нативной страницы; место нативной страницы — под обработчики объектов.
; Окно W3 — эта страница; память V30 — окна W1, W2, как у нативной страницы. Возврат — H2Ret (копия NRet).

; Возврат в переведённую программу: RET V30; возврат обработчика в цикл объектов — сразу в ядро цикла (как NRet).
H2Ret:          pop de
                ld a,d
                cp #02
                jp nz,DISPATCH
                ld a,e
                cp #6A
                jp z,KERNEL_OBJECTS_B_RET
                cp #5C
                jp z,KERNEL_OBJECTS_A_RET
                jp DISPATCH

; ROM $0216B (IP $1D6B, 56 мест вызова): объект на поле? AX = [bp+4] − #12C (заём — CF = 1), − #1A8 (без заёма —
; CF = 1), AX = [bp+8] − #7C (заём — CF = 1), − #118 (без заёма — CF = 1), иначе CF = 0. AX — последняя разность.
; После RET живёт только CF (V_FL бит 0). BP у края рабочего ОЗУ — перевод.
N_1D6B:         ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,#12C
                or a
                sbc hl,de
                jr c,.outside
                ld de,#1A8
                sbc hl,de                       ; CF = 0 после первой проверки
                jr nc,.outside
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,#7C
                or a
                sbc hl,de
                jr c,.outside
                ld de,#118
                sbc hl,de
                jr nc,.outside
                ld (V_AX),hl
                ld hl,V_FL
                res 0,(hl)                      ; CLC
                jp H2Ret
.outside:       ld (V_AX),hl
                ld hl,V_FL
                set 0,(hl)                      ; STC
                jp H2Ret
.translated:    ld a,$$K_0216B
                ld hl,K_0216B
                jp FARJP

; −(байт A со знаком) → HL (CBW, NEG ROM). Портит AF.
NNegCbw:        ld l,a
                neg
                ld h,0
                bit 7,l
                ld l,a
                ret nz                          ; A < 0: −A ≥ 0 (и #80 → #0080)
                or a
                ret z                           ; 0
                dec h                           ; A > 0: −A < 0
                ret
; Байт A со знаком → HL (CBW). Портит AF.
NCbw:           ld l,a
                add a,a
                sbc a,a
                ld h,a
                ret

; ROM $00867 (IP $0467, из обработчика кадра): четыре 24-битных интегратора прокрутки. Прогресс [#2F4A…#2F4C] и X
; переднего слоя [#2EC0…#2EC2] += скорость [#2EEC] (слово, перенос — в старший байт); X заднего слоя [#2EC8…#2ECA] +=
; [#2EF4…#2EF6], Y переднего [#2EC4…#2EC6] += [#2EF0…#2EF2], Y заднего [#2ECC…#2ECE] += [#2EF8…#2EFA]; у каждой оси
; слово +1 & #1FF. Шаг оси — младший байт разности со старым словом со знаком: у X — с обратным знаком ([#2ED0],
; [#2ED4]), у Y — прямо ([#2ED2], [#2ED6]); смена бита 6 X — байт [#2EE6] (передний) или [#2EEA] (задний) + #10.
; Выход: SI = #2F4A, BX — старое слово Y заднего слоя, AX — шаг Y заднего. Флаги после RET не живут.
N_0467:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld ix,#4000+#2EC0               ; IX → интеграторы (смещения от #2EC0)
                ld b,(ix+1)                     ; BL — старый младший байт X переднего слоя
                ld de,(#4000+#2EEC)             ; AX — скорость X переднего слоя
                ld hl,(#4000+#2F4A)
                add hl,de
                ld (#4000+#2F4A),hl
                jr nc,.progress
                ld hl,#4000+#2F4C
                inc (hl)                        ; прогресс — 24 бита
.progress:      ld l,(ix+0)
                ld h,(ix+1)
                add hl,de
                ld (ix+0),l
                ld (ix+1),h
                jr nc,.fgx
                inc (ix+2)
.fgx:           ld a,(ix+2)
                and 1
                ld (ix+2),a                     ; AND [#2EC1],#1FF
                ld a,(ix+1)
                sub b
                call NNegCbw
                ld (#4000+#2ED0),hl
                ld a,(ix+1)
                xor b
                and #40
                jr z,.bgx
                ld a,(#4000+#2EE6)
                add a,#10
                ld (#4000+#2EE6),a
.bgx:           ld b,(ix+9)                     ; BL — старый младший байт X заднего слоя ([#2EC9])
                ld hl,(#4000+#2EF4)
                ld a,(ix+8)
                add a,l
                ld (ix+8),a
                ld a,(ix+9)
                adc a,h
                ld (ix+9),a
                ld a,(#4000+#2EF6)
                adc a,(ix+10)
                and 1                           ; AND [#2EC9],#1FF
                ld (ix+10),a
                ld a,(ix+9)
                sub b
                call NNegCbw
                ld (#4000+#2ED4),hl
                ld a,(ix+9)
                xor b
                and #40
                jr z,.fgy
                ld a,(#4000+#2EEA)
                add a,#10
                ld (#4000+#2EEA),a
.fgy:           ld b,(ix+5)                     ; [#2EC5]
                ld hl,(#4000+#2EF0)
                ld a,(ix+4)
                add a,l
                ld (ix+4),a
                ld a,(ix+5)
                adc a,h
                ld (ix+5),a
                ld a,(#4000+#2EF2)
                adc a,(ix+6)
                and 1
                ld (ix+6),a
                ld a,(ix+5)
                sub b
                call NCbw
                ld (#4000+#2ED2),hl
                ld c,(ix+13)
                ld b,(ix+14)                    ; BX — старое слово [#2ECD]
                ld (V_BX),bc
                ld hl,(#4000+#2EF8)
                ld a,(ix+12)
                add a,l
                ld (ix+12),a
                ld a,(ix+13)
                adc a,h
                ld (ix+13),a
                ld a,(#4000+#2EFA)
                adc a,(ix+14)
                and 1
                ld (ix+14),a
                ld a,(ix+13)
                sub c
                call NCbw
                ld (#4000+#2ED6),hl
                ld (V_AX),hl
                ld hl,#2F4A
                ld (V_SI),hl
                jp H2Ret
.translated:    ld a,$$K_00867
                ld hl,K_00867
                jp FARJP

; ROM $055EE (IP $51EE, 194 места вызова): ресурс AL — в таблице #2114…#2133 (16 записей по 2 байта: ресурс, счётчик;
; #FF — свободна), просмотр с конца. Найден — счётчик + 1, BX = номер записи. Не найден и свободной нет — BL = #FF.
; Не найден при свободной (запись и загрузка $5228) — перевод с входа (до записей). Регистры — как у ROM: AH = байт
; последней просмотренной записи, CX — счётчик LOOP, DX — последняя (нижняя) свободная до места выхода или #FFFF.
; Флаги после RET не живут. Условие: DS = #4000.
N_51EE:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld a,(V_AX)
                ld c,a                          ; C — AL
                ld hl,#4000+#2132
                ld b,16                         ; CX
                ld de,#FFFF                     ; DX
.scan:          ld a,(hl)
                cp c
                jr z,.found
                inc a
                jr nz,.next
                ld e,l
                ld d,h                          ; DX = BX (свободная)
.next:          dec hl
                dec hl
                djnz .scan
                ld a,d
                and e
                inc a
                jp nz,.translated               ; есть свободная: запись и загрузка — переводом
                ld (V_DX),de                    ; DX = #FFFF
                xor a
                ld (V_CX),a
                ld (V_CX+1),a                   ; CX = 0
                ld a,(#4000+#2114)
                ld (V_AX+1),a                   ; AH — последняя просмотренная (#2114)
                ld hl,#21FF
                ld (V_BX),hl                    ; BX = #2112 после цикла, BL = #FF
                jp H2Ret
.found:         ld (V_AX+1),a                   ; AH = [bx]
                ld a,b
                ld (V_CX),a
                xor a
                ld (V_CX+1),a                   ; CX — ещё не уменьшенный LOOP
                ld a,d
                and e
                inc a
                jr z,.noFree
                res 6,d                         ; DX — смещение (не адрес окна)
.noFree:        ld (V_DX),de
                inc hl
                inc (hl)                        ; счётчик + 1
                dec hl
                res 6,h
                ld de,-#2114
                add hl,de
                srl h
                rr l
                ld (V_BX),hl                    ; BX = (BX − #2114) >> 1
                jp H2Ret
.translated:    ld a,$$K_055EE
                ld hl,K_055EE
                jp FARJP

; ROM $007A6 (IP $03A6, 194 места вызова): новый объект. Кольцо свободных слотов — индекс чтения [#2EE0], записи
; [#2EE2] (шаг 2, по модулю #C0); пусто — AX = индекс, CF = 1. Иначе [#2EE0] = следующий индекс, слот SI = [#2054 +
; индекс], [si] = DX (обработчик) и вставка в список по приоритету CX: от #540 по [bx+#1C] до первого с [bx+#18] ≥ CX,
; SI — перед ним ([si+#1C] = BX, [si+#1A] = прежний [bx+#1A], [bx+#1A] = SI, [прежний+#1C] = SI), [si+#18] = CX,
; CF = 0; AX = BX = прежний, SI — слот. Флаги после RET анализ считает живыми все: они как у ROM — от последнего CMP
; (CMP AX,[#2EE2] или CMP AX,CX) с CF от STC/CLC. Условие: DS = #4000; указатели слота и звеньев списка — в рабочем
; ОЗУ не у края (иначе перевод с входа; все проверки — до записей).
N_03A6:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(#4000+#2EE0)             ; AX
                ld de,(#4000+#2EE2)
                or a
                sbc hl,de
                jr nz,.take
                add hl,de
                ld (V_AX),hl                    ; пусто: AX = индекс
                ld a,#47                        ; CMP равных (ZF, PF) и STC
                ld (V_FL),a
                ld hl,V_FL+1
                res 3,(hl)                      ; OF = 0
                jp H2Ret
.take:          add hl,de                       ; HL = индекс (BX)
                ld de,#4000+#2054
                ex de,hl
                add hl,de                       ; → [bx+#2054]
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — слот SI
                ld a,b
                cp #3F
                jp nc,.translated               ; слот у края рабочего ОЗУ
                ld (N_SLOT),bc
                ex de,hl                        ; HL = индекс
                inc hl
                inc hl                          ; AX + 2
                ld a,h
                or a
                jr nz,.wrap
                ld a,l
                cp #C0
                jr c,.index
.wrap:          ld hl,0
.index:         ld (N_INDEX),hl
                ; поиск места: от #540 по [bx+#1C], пока [bx+#18] < CX (только чтения)
                ld de,(V_CX)
                ld hl,#540
.walk:          ld a,h
                cp #3F
                jp nc,.translated               ; звено у края или вне рабочего ОЗУ
                ld (N_NODE),hl
                set 6,h
                ld bc,#18
                add hl,bc
                ld a,(hl)
                inc hl
                ld b,(hl)                       ; B:A = [bx+#18]
                sub e
                ld a,b
                sbc a,d
                jr nc,.found                    ; [bx+#18] ≥ CX
                inc hl
                inc hl
                inc hl                          ; [bx+#1C]
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                jr .walk
.found:         ld hl,(N_NODE)
                ld bc,#4000+#1A
                add hl,bc
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — прежний [bx+#1A]
                ld a,b
                cp #3F
                jp nc,.translated               ; прежнее звено у края
                ; записи — в порядке ROM
                ld hl,(N_INDEX)
                ld (#4000+#2EE0),hl
                ld hl,(N_SLOT)
                set 6,h
                ld de,(V_DX)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si] = DX
                ld hl,(N_SLOT)
                ld de,#4000+#1C
                add hl,de
                ld de,(N_NODE)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+#1C] = BX
                ld hl,(N_NODE)
                ld de,#4000+#1A
                add hl,de
                ld de,(N_SLOT)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [bx+#1A] = SI (XCHG)
                ld hl,(N_SLOT)
                ld de,#4000+#1A
                add hl,de
                ld (hl),c
                inc hl
                ld (hl),b                       ; [si+#1A] = прежний
                ld (V_AX),bc
                ld (V_BX),bc                    ; AX = BX = прежний
                ld l,c
                ld h,b
                ld de,#4000+#1C
                add hl,de
                ld de,(N_SLOT)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [прежний+#1C] = SI
                ld (V_SI),de
                ld hl,(N_SLOT)
                ld de,#4000+#18
                add hl,de
                ld de,(V_CX)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+#18] = CX
                ; флаги последнего CMP AX,CX (AX = [узел+#18] ≥ CX), затем CLC
                ld hl,(N_NODE)
                ld bc,#4000+#18
                add hl,bc
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a                          ; HL = [узел+#18]
                ld a,l
                xor e
                ld (FLG_X),a
                or a
                sbc hl,de
                ld (FLG_R),hl
                push af
                pop bc                          ; C — флаги Z80
                call FLG_AR16
                ld hl,V_FL
                res 0,(hl)                      ; CLC
                jp H2Ret
.translated:    ld a,$$K_007A6
                ld hl,K_007A6
                jp FARJP

; Переменные $03A6 — в этой странице (окно W3 при её исполнении; прежде — в данных нативной страницы).
N_SLOT          DW 0                            ; слот нового объекта ($03A6)
N_INDEX         DW 0
N_NODE          DW 0
