; Ядра: процедуры ROM, переведённые нативно (часть резидента, окно W0). Транслятор ставит на вход процедуры
; переход на ядро (codegen.KERNELS); ядро выполняет те же записи в память V30, что код ROM, и возвращается
; как RET V30 (адрес возврата — на стеке V30, DISPATCH). Регистры V30 на выходе ядро не восстанавливает —
; у каждой процедуры это оговорено: они не живут (у ядер рельефа живущие AX, BX, CX, DI ядро ставит как ROM). Свои вызовы ядро делает на стеке помощников (HELPER_TOP),
; поэтому остатков стека V30 ниже SP, которые оставил бы код ROM, у ядра нет (сверка их не сравнивает).

; --- данные менеджера палитр (код — vdac2p_native.asm: VDAC2+ перенёс его из резидента) -----------------
; Кэш записей и маски перьев общие с переносом палитр и VIDEO_MARK; новая машина обнуляет резидент.
PAL_COUNT       DB 0
PAL_PLANES      DW 0                    ; плоскость R слота 0 группы
PAL_GROUP       DW 0                    ; PAL_EQ + группа·16
PAL_AT          DW 0                    ; PAL_EQ записи
PAL_MASK_AT     DW 0                    ; PEN_EQ записи
; Кэш записей менеджера и переноса (r = группа·16 + слот; PAL_KIND = PAL_EQ + 32, PAL_SYNC = PAL_EQ + 64).
PAL_EQ          DS 32                   ; 1 — плоскости равны целям типа PAL_KIND
PAL_KIND        DS 32
PAL_SYNC        DS 32                   ; 1 — слот памяти палитр равен плоскостям
                ASSERT PAL_KIND == PAL_EQ+32 && PAL_SYNC == PAL_EQ+64

; --- вывод спрайтов в память спрайтов ------------------------------------------------------------------
; ROM $1FCC (IP $1BCC, 152 места вызова) и его продолжение $1FE9 (IP $1BE9, ещё 20 мест): спрайт объекта BP
; по описанию ES:BX — в память спрайтов C000:SI…SI+7: Y = [bp+8] + байт [bx+1] со знаком, код = [bx+2],
; атрибут = старший байт [bx+4] и младший [bp+6], X = [bp+4] + байт [bx] со знаком. У $1FCC: SI = [2EFC],
; DI = SI, AX = SI + размер (8, при бите 14 атрибута — 16); AX ≥ #3C8 — возврат без записи, иначе
; [2EFC] = AX. На выходе CX = [bp+4], DX = [bp+8], AX = атрибут, DS прежний; флаги после RET не живут
; (flags.liveness). Описание вне одной страницы V30 (или в рабочем ОЗУ), DS ≠ #4000, BP или SI у края
; страницы — обычный перевод с того же места (K_01FCC, K_01FE9). Вызовы ядра — на стеке V30: адреса возврата
; ложатся ниже SP, как PUSH DS и CALL у ROM (эти остатки сверка не сравнивает).
KERNEL_SPRITE_ADD:
                ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,.translated               ; [2EFC] читается через DS
                call SpriteAdd
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_01FCC
                ld hl,K_01FCC
                jp FARJP

KERNEL_SPRITE_PUT:
                call SpritePut
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_01FE9
                ld hl,K_01FE9
                jp FARJP

; $1FCC при DS = #4000. CF = 1 — ядро не берёт: память V30 не тронута (окно W2 могло смениться).
SpriteAdd:      ld a,(V_BP+1)
                cp #3F
                jr nc,SpriteFail                ; BP у края рабочего ОЗУ
                ld a,(#4000+#2EFD)
                cp #3F
                jr nc,SpriteFail                ; SI = [2EFC] у края памяти спрайтов
                call SpriteDefinition
                ret c
; C — байт X, B — байт Y, DE — код, A — старший байт атрибута описания. SI = DI = [2EFC], AX = SI + размер,
; заполнено — AX и возврат, иначе [2EFC] = AX и запись (SpritePutCore). CF = 0. Портит всё.
SpriteAddDefined:
                ld hl,(#4000+#2EFC)
                ld (V_SI),hl                    ; SI = [2EFC]
                ld (V_DI),hl                    ; DI = SI
                push de
                ld de,8
                bit 6,a
                jr z,.size
                ld e,16                         ; бит 14 атрибута — две записи
.size:          add hl,de                       ; AX = SI + размер
                ex af,af'                       ; A' — атрибут
                ld de,#3C8
                or a
                sbc hl,de
                jr nc,.full                     ; AX ≥ #3C8: память спрайтов заполнена
                add hl,de
                ld (#4000+#2EFC),hl             ; [2EFC] = AX
                pop de
                ex af,af'
                jr SpritePutCore
.full:          add hl,de
                ld (V_AX),hl
                pop de
                or a
                ret
SpriteFail:     scf
                ret

; $1FE9: CF = 1 — ядро не берёт (память V30 не тронута).
SpritePut:      ld a,(V_BP+1)
                cp #3F
                jr nc,SpriteFail                ; BP у края рабочего ОЗУ
                ld a,(V_SI+1)
                cp #3F
                jr nc,SpriteFail                ; SI у края страницы памяти спрайтов
                call SpriteDefinition
                ret c
; Запись C000:SI (BP, SI < #3F00): C — байт X, B — байт Y, DE — код, A — старший байт атрибута. CX = [bp+4],
; DX = [bp+8], AX = атрибут. CF = 0. Портит всё.
SpritePutCore:  ex af,af'                       ; A' — атрибут
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → [bp] (окно W1, SS = #4000)
                ld hl,(V_SI)
                set 7,h                         ; HL → C000:SI в окне W2
                ld a,(W2_PAGE)
                cp #30
                jr z,.mapped                    ; память спрайтов уже в W2
                ld a,#30
                ld (W2_PAGE),a
                exx
                ld a,V30_PAGE_BASE+#30
                ld bc,PORT_PAGE2
                out (c),a
                exx
.mapped:        push de                         ; код
                ld e,b
                ld a,b
                rla
                sbc a,a
                ld d,a                          ; DE = байт Y со знаком
                ld a,(ix+8)
                ld (V_DX),a
                add a,e
                ld (hl),a
                inc hl
                ld a,(ix+9)
                ld (V_DX+1),a                   ; DX = [bp+8]
                adc a,d
                ld (hl),a                       ; [si] = Y
                inc hl
                pop de
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+2] = код
                inc hl
                ld a,(ix+6)
                ld (hl),a
                ld (V_AX),a
                inc hl
                ex af,af'
                ld (hl),a                       ; [si+4] = атрибут: старший — описание, младший — [bp+6]
                ld (V_AX+1),a
                inc hl
                ld e,c
                ld a,c
                rla
                sbc a,a
                ld d,a                          ; DE = байт X со знаком
                ld a,(ix+4)
                ld (V_CX),a
                add a,e
                ld (hl),a
                inc hl
                ld a,(ix+5)
                ld (V_CX+1),a                   ; CX = [bp+4]
                adc a,d
                ld (hl),a                       ; [si+6] = X
                or a
                ret

; Описание ES:BX…BX+5 → C — байт [bx] (X), B — [bx+1] (Y), DE — слово [bx+2] (код), A — байт [bx+5] (старший
; атрибута). Описание читается через окно W3 (ядро исполняется в W0; DISPATCH и FARJP после ядра отображают W3 сами),
; окно W2 не трогается — у подряд идущих спрайтов в нём остаётся память спрайтов. CF = 1 — описание в рабочем ОЗУ или
; не в одной странице V30. ES = #1000 (обработчик IRQ0) — без вычисления адреса. Портит HL.
SpriteDefinition:
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.general
                ld hl,(V_BX)                    ; ES = #1000: адрес #10000 + BX
                ld a,h
                rlca
                rlca
                and 3
                add a,4                         ; страница V30 = 4 + BX >> 14
                jr .page
.general:       ld a,h
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a                          ; C = ES >> 12
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = ES·16 & #FFFF
                ld de,(V_BX)
                add hl,de
                ld a,c
                adc a,0                         ; A:HL = ES·16 + BX
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; A = страница V30
.page:          cp WORK_PAGE
                jr z,.fail                      ; рабочее ОЗУ — обычный перевод
                ld c,a
                ld a,h
                and #3F
                cp #3F
                jr c,.inside
                ld h,a
                ld a,l
                cp #FB
                jr nc,.fail                     ; смещение + 6 > #4000
                ld a,h
.inside:        or #C0
                ld h,a                          ; HL → описание в окне W3
                ld a,c
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE3
                out (c),a
                ld c,(hl)                       ; [bx] — X
                inc hl
                ld b,(hl)                       ; [bx+1] — Y
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; [bx+2] — код
                inc hl
                inc hl
                ld a,(hl)                       ; [bx+5] — старший байт атрибута
                or a                            ; CF = 0
                ret
.fail:          scf
                ret

; --- цикл объектов ------------------------------------------------------------------------------------------
; ROM $0657…$0661 (IP $0257: 40 слотов, BP = #20 шагом #20, CX — счётчик) и $0666…$0675 (IP $0266: список с
; BP = #540 по [bp+#1C] до #FFFF) обработчика IRQ0: у объекта — CALL [bp]. Флаги на входах обработчиков и после
; циклов не живут (flags.liveness). Обработчик из NATIVE_TABLE исполняется нативно (NativeHandler) без CALL/RET
; V30 (PUSH-остатков ниже SP нет — сверка их не сравнивает); у остальных — те же PUSH и CALL, что у ROM (адрес
; возврата #025C / #026A), и переход на обработчик: его RET ведёт в перевод $065C / $066A, а тот — снова на вход
; ядра. Слот у края рабочего ОЗУ — перевод с входа (K_).
KERNEL_OBJECTS_A:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                set 6,h
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE = [bp] — IP обработчика
                ld hl,(V_CX)
                ld a,d
                sub #39
                cp 5
                jr nc,.notIdle                  ; VDAC2+: IP #39xx…#3Dxx — может быть холостой слот оружия
                ld (OBJ_CX),hl
                call WeaponIdleFar
                jr c,.batched                   ; холостые слоты обойдены пачкой: V_BP, V_CX — после них
                ld hl,(OBJ_CX)
.notIdle:       ld a,d
                cp high NATIVE_IP0
                jr z,.native
                cp high NATIVE_IP1
                jr z,.native
                cp high NATIVE_IP3
                jr z,.native
                cp high NATIVE_IP2
                jr nz,.call
.native:        ld (OBJ_CX),hl
                xor a
                ld (OBJ_LOOP),a
                push de
                call NativeHandler
.nativeDone:    pop de
                or a
                ld hl,(OBJ_CX)
                jr nz,.call
.advance:       ld hl,(V_BP)                    ; POP BP, POP CX; ADD BP,#20; LOOP
                ld de,#20
                add hl,de
                ld (V_BP),hl
                ld hl,(OBJ_CX)
                dec hl
                ld (V_CX),hl
.loopTest:      ld a,h
                or l
                jr nz,KERNEL_OBJECTS_A
                ld a,$$A_00663
                ld hl,A_00663
                jp FARJP
.batched:       ld hl,(V_CX)
                jr .loopTest
.call:          push hl                         ; PUSH CX (HL = CX, DE = IP обработчика)
                ld hl,(V_BP)
                push hl                         ; PUSH BP
                ld hl,#025C
                push hl                         ; CALL [bp]: адрес возврата
                jp DISPATCH
.translated:    ld a,$$K_00657
                ld hl,K_00657
                jp FARJP

KERNEL_OBJECTS_B:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                set 6,h
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE = [bp] — IP обработчика
                ld a,d
                cp high NATIVE_IP0
                jp z,BulletBatch                ; снаряды игрока — пачкой
                cp high NATIVE_IP1
                jr z,.native
                cp high NATIVE_IP3
                jr z,.native
                cp high NATIVE_IP2
                jr nz,.call
.native:        ld a,1
                ld (OBJ_LOOP),a
                push de
                call NativeHandler
.nativeDone:    pop de
                or a
                jr nz,.call
                ld hl,(V_BP)                    ; POP BP; MOV AX,[bp+#1C]; CMP AX,#FFFF; JE $0677; MOV BP,AX
                ld de,#4000+#1C
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_AX),de
                ld a,d
                and e
                inc a
                jr z,.end                       ; AX = #FFFF — конец списка
                ld (V_BP),de
                jr KERNEL_OBJECTS_B
.end:           ld a,$$A_00677
                ld hl,A_00677
                jp FARJP
.call:          ld hl,(V_BP)
                push hl                         ; PUSH BP (DE = IP обработчика)
                ld hl,#026A
                push hl                         ; CALL [bp]: адрес возврата
                jp DISPATCH
.translated:    ld a,$$K_00666
                ld hl,K_00666
                jp FARJP

; Возврат обработчика в цикл слотов — ROM $065C (IP $025C: RET обработчика ведёт сюда): POP BP, POP CX, ADD BP,#20
; (флаги не живут), LOOP на $0657 — сразу ядром цикла.
KERNEL_OBJECTS_A_RET:
                pop hl
                ld de,#20
                add hl,de
                ld (V_BP),hl
                pop hl
                dec hl
                ld (V_CX),hl
                ld a,h
                or l
                jp nz,KERNEL_OBJECTS_A
                ld a,$$A_00663
                ld hl,A_00663
                jp FARJP

; Возврат обработчика в цикл списка — ROM $066A (IP $026A): POP BP, MOV AX,[bp+#1C], CMP AX,#FFFF (флаги не живут
; после JE), JE $0677, MOV BP,AX, JMP $0666 — ядром цикла. BP у края рабочего ОЗУ — перевод с того же места.
KERNEL_OBJECTS_B_RET:
                pop hl                          ; POP BP
                ld a,h
                cp #3F
                jr nc,.translated
                ld (V_BP),hl
                ld de,#4000+#1C
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_AX),de                    ; AX = [bp+#1C]
                ld a,d
                and e
                inc a
                jr z,.end                       ; AX = #FFFF — конец списка
                ld (V_BP),de
                jp KERNEL_OBJECTS_B
.end:           ld a,$$A_00677
                ld hl,A_00677
                jp FARJP
.translated:    push hl
                ld a,$$K_0066A
                ld hl,K_0066A
                jp FARJP

; Обработчик объекта V_BP (< #3F00) с IP DE — нативно, если он есть в NATIVE_TABLE: A = 0 — исполнен; A = 1 — нет
; (ни одной записи в память V30 — обычный CALL). Продолжение переводом с середины обработчика — HandlerBail.
NativeHandler:  ld (NATIVE_SP),sp               ; вершина — адрес возврата в ядро цикла
                ld hl,NATIVE_TABLE
                ld b,NATIVE_COUNT
.find:          ld a,(hl)
                inc hl
                cp e
                jr nz,.skip
                ld a,(hl)
                cp d
                jr nz,.skip
                inc hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                jp (hl)
.skip:          inc hl
                inc hl
                inc hl
                djnz .find
                ld a,1
                ret
NATIVE_IP0      EQU #E5CD                       ; снаряд игрока ($E9CD)
NATIVE_IP1      EQU #59A2                       ; скриптовый враг ($5DA2)
NATIVE_IP2      EQU #5E8E                       ; скриптовый враг ($628E)
NATIVE_IP3      EQU #7A3F                       ; звено червя этапа 5 ($7E3F; и зеркальное #7AFA — тот же старший байт)
NATIVE_TABLE:   DW NATIVE_IP0, BulletNative
                DW NATIVE_IP1, Enemy59A2
                DW NATIVE_IP2, Enemy5E8E
                DW NATIVE_IP3, WormFar
                DW #7AFA, WormFar
NATIVE_COUNT    EQU ($-NATIVE_TABLE)/4
                ASSERT high #7AFA == high NATIVE_IP3

; Звенья червя ($7A3F, $7AFA) — нативная страница: окно W3 — она, DE (IP обработчика) — вариант. Портит BC.
WormFar:        ld a,NATIVE_PAGE0
                ld bc,PORT_PAGE3
                out (c),a
                jp N_WORM_ENTRY

; Выход нативного обработчика в перевод (не возвращается): A — страница, HL — адрес метки, DE — IP возврата
; вложенного CALL ROM на стеке V30 (0 — нет). Стек Z80 — как на входе NativeHandler (адрес возврата в ядро и
; сохранённый под ним IP снимаются), затем кадр вызова обработчика ROM: цикл слотов — PUSH CX (OBJ_CX), PUSH BP, #025C; списка — PUSH BP,
; #026A. RET обработчика в переводе ведёт в $065C / $066A, как при обычном вызове.
HandlerBail:    ld (BAIL_PAGE),a
                ld (BAIL_TARGET),hl
                ld sp,(NATIVE_SP)
                pop hl                          ; адрес возврата в ядро цикла
                pop hl                          ; сохранённый ядром цикла IP обработчика
                ld a,(OBJ_LOOP)
                or a
                jr nz,.list
                ld hl,(OBJ_CX)
                push hl
                ld hl,(V_BP)
                push hl
                ld hl,#025C
                push hl
                jr .inner
.list:          ld hl,(V_BP)
                push hl
                ld hl,#026A
                push hl
.inner:         ld a,d
                or e
                jr z,.jump
                push de
.jump:          ld a,(BAIL_PAGE)
                ld hl,(BAIL_TARGET)
                jp FARJP

OBJ_LOOP        DB 0                            ; 0 — цикл слотов, 1 — цикл списка
OBJ_CX          DW 0                            ; CX цикла слотов на входе обработчика
NATIVE_SP       DW 0
BAIL_PAGE       DB 0
BAIL_TARGET     DW 0

; Скриптовый враг — обработчик ROM $5DA2 (IP $59A2): $F9C1 (CF — уход с $5DD8), X += [2ED0] (AX = [2ED0]), $FA3A,
; кадр спрайта BX = (([2EB6] + [bp+#16]) & #1C)·1.5 + #28E2 (AX = BX >> 1 до сложения) и $1FCC, DI = #2912 и $FA94
; (CF — попадание, $5DE5), [2FC4] ≠ 0 — уход. Флаги между вызовами и на местах продолжения не живут. Условия
; каждого вызова — перед ним: до первой записи — A = 1 (обычный CALL), после — продолжение переводом с места
; вызова (HandlerBail).
Enemy59A2:      call EnemyStart
                ret nz                          ; A = 1
                call ScriptCore
                jr c,.destroy                   ; скрипт кончился
                call EnemyScroll
                call CounterCore
                or a
                jr z,.counted
                ld de,#59B0                     ; порождение: RET в $5DB0
                ld a,$$A_0FA57
                ld hl,A_0FA57
                jp HandlerBail
.counted:       ld hl,(#4000+#2EB6)
                ld e,(ix+#16)
                ld d,(ix+#17)
                add hl,de
                ld a,l
                and #1C
                ld l,a
                ld h,0                          ; BX = ([2EB6] + [bp+#16]) & #1C
                srl a
                ld e,a
                ld d,h
                ld (V_AX),de                    ; AX = BX >> 1
                add hl,de
                ld de,#28E2
                add hl,de
                ld (V_BX),hl
                call SpriteAdd
                jr nc,.sprite
                ld de,#59C8                     ; условия $1FCC: RET в $5DC8
                ld a,$$K_01FCC
                ld hl,K_01FCC
                jp HandlerBail
.sprite:        ld hl,#2912
                ld (V_DI),hl
                call CollideSetup
                jr nc,.collide
                ld de,#59CE                     ; условия $FA94: RET в $5DCE
                ld a,$$K_0FA94
                ld hl,K_0FA94
                jp HandlerBail
.collide:       call CollideA94
                jr c,.hit
                ld a,(#4000+#2FC4)
                or a
                jr nz,.destroy
                xor a
                ret
.hit:           ld de,0
                ld a,$$A_05DE5
                ld hl,A_05DE5
                jp HandlerBail
.destroy:       ld de,0
                ld a,$$A_05DD8
                ld hl,A_05DD8
                jp HandlerBail

; Скриптовый враг — обработчик ROM $628E (IP $5E8E): как $5DA2, кадр спрайта BX = байт [bp+#16]·6 + #29D2 (AX = байт·2),
; DI = #2A38; попадание — $62D0, уход — $62C3.
Enemy5E8E:      call EnemyStart
                ret nz
                call ScriptCore
                jr c,.destroy
                call EnemyScroll
                call CounterCore
                or a
                jr z,.counted
                ld de,#5E9C                     ; порождение: RET в $629C
                ld a,$$A_0FA57
                ld hl,A_0FA57
                jp HandlerBail
.counted:       ld l,(ix+#16)
                ld h,0
                add hl,hl
                ld (V_AX),hl                    ; AX = байт·2
                ld e,l
                ld d,h
                add hl,hl
                add hl,de
                ld de,#29D2
                add hl,de
                ld (V_BX),hl                    ; BX = байт·6 + #29D2
                call SpriteAdd
                jr nc,.sprite
                ld de,#5EB0                     ; условия $1FCC: RET в $62B0
                ld a,$$K_01FCC
                ld hl,K_01FCC
                jp HandlerBail
.sprite:        ld hl,#2A38
                ld (V_DI),hl
                call CollideSetup
                jr nc,.collide
                ld de,#5EB6                     ; условия $FA94: RET в $62B6
                ld a,$$K_0FA94
                ld hl,K_0FA94
                jp HandlerBail
.collide:       call CollideA94
                jr c,.hit
                ld a,(#4000+#2FC4)
                or a
                jr nz,.destroy
                xor a
                ret
.hit:           ld de,0
                ld a,$$A_062D0
                ld hl,A_062D0
                jp HandlerBail
.destroy:       ld de,0
                ld a,$$A_062C3
                ld hl,A_062C3
                jp HandlerBail

; Условия скриптового врага до записей: DS = #4000 и условия ядра скрипта (ScriptCheck). NZ, A = 1 — нельзя;
; иначе Z, IX → [bp], B — шагов скрипта.
EnemyStart:     ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,.not
                call ScriptCheck
                jr c,.not
                xor a
                ret
.not:           ld a,1
                or a
                ret

; MOV AX,[2ED0]; ADD [bp+4],AX (IX → [bp]). Портит F, DE, HL.
EnemyScroll:    ld hl,(#4000+#2ED0)
                ld (V_AX),hl
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                ret

; Снаряд игрока — обработчик ROM $E9CD (IP $E5CD) над объектом V_BP (< #3F00): [2FC4] ≠ 0 — сразу уничтожение
; (обычный вызов); иначе X += [bp+#30] ($0A72: слово [bp+3] и перенос/заём в байт [bp+5]), BX = [bp+#34], спрайт
; ($1FCC), затем при [bp+#32] = #832C уход при [bp+4] ≥ #2C0, иначе при [bp+4] < #140 — продолжение с $E9F7.
; Флаги после $0A72 у этого места вызова не живут. Условия: DS = #4000, BP кратен 16 (запись [bp+3…5] не задевает
; [2EFC]), [2EFC] < #3F00, описание спрайта ES:[bp+#34] читается ядром — проверяются до записей. Выход: A = 0 —
; сделано, 1 — ядро не берёт (память V30 не тронута); уход — продолжение переводом с $E9F7 (HandlerBail).
BulletNot:      ld a,1
                ret
BulletNative:   ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,BulletNot
                ld a,(V_BP)
                and #0F
                jr nz,BulletNot
                ld a,(#4000+#2FC4)
                or a
                jr nz,BulletNot
                ld a,(#4000+#2EFD)
                cp #3F
                jr nc,BulletNot
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld l,(ix+#34)
                ld h,(ix+#35)
                ld (V_BX),hl                    ; BX = [bp+#34] (при отказе ядра обработчик задаст его сам)
                call SpriteDefinition
                jr c,BulletNot
                push bc
                push de
                push af                         ; описание спрайта (SpriteDefinition не трогает IX)
                ld e,(ix+#30)
                ld d,(ix+#31)
                ld (V_AX),de                    ; AX = [bp+#30]
                ld l,(ix+3)
                ld h,(ix+4)
                bit 7,d                         ; Z — AX ≥ 0
                add hl,de                       ; [bp+3] += AX; CF — перенос (ADD HL не меняет Z)
                ld (ix+3),l
                ld (ix+4),h
                jr nz,.negative
                jr nc,.moved
                inc (ix+5)                      ; $0A7C
                jr .moved
.negative:      jr c,.moved
                dec (ix+5)                      ; $0A85
.moved:         pop af
                pop de
                pop bc
                call SpriteAddDefined           ; IX → [bp] и после (SpritePutCore ставит тот же)
                ld a,(ix+#32)
                cp #2C
                jr nz,.left
                ld a,(ix+#33)
                cp #83
                jr nz,.left
                ld l,(ix+4)                     ; $E9EF: [bp+4] ≥ #2C0 — уход
                ld h,(ix+5)
                ld de,#2C0
                or a
                sbc hl,de
                jr nc,.destroy
                xor a
                ret
.left:          ld l,(ix+4)                     ; $E9E7: [bp+4] < #140 — уход
                ld h,(ix+5)
                ld de,#140
                or a
                sbc hl,de
                jr c,.destroy
                xor a
                ret
.destroy:       ld de,0                         ; продолжение с $E9F7 — переводом
                ld a,$$A_0E9F7
                ld hl,A_0E9F7
                jp HandlerBail

; Снаряды игрока подряд в цикле списка объектов ($0666, обработчик $E5CD): те же записи в память V30 и регистры, что у
; BulletNative и $1FCC (SpriteAddDefined, SpritePutCore), и тот же переход к следующему объекту ($066A), но одним циклом
; ядра: без поиска в NATIVE_TABLE и вызовов общих ядер, описание спрайта — через окно W3 (ядро исполняется в W0; DISPATCH
; и FARJP после ядра отображают W3 сами; BB_W3 — его страница), память спрайтов — в окне W2 на всю пачку. Условия пачки
; (DS = #4000) — на входе, условия снаряда ([2FC4] = 0, BP кратен 16, [2EFC] < #3F00, описание ES:[bp+#34] в одной
; странице V30 не в рабочем ОЗУ) — до его записей: не выполнены — обычный CALL обработчика. Уход ($E9F7) — продолжение
; переводом (HandlerBail: кадр стека как у NativeHandler). Вход из KERNEL_OBJECTS_B: DE = [bp], старший байт — #E5.
BulletBatch:    ld a,e
                cp low NATIVE_IP0
                jp nz,KERNEL_OBJECTS_B.call     ; другой обработчик страницы #E5
                ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,.translatedCall           ; BulletNative не взял бы
                ld a,1
                ld (OBJ_LOOP),a
                ld a,#30
                ld (W2_PAGE),a
                ld a,V30_PAGE_BASE+#30
                ld bc,PORT_PAGE2
                out (c),a                       ; память спрайтов — в W2 на всю пачку
                ld a,#FF
                ld (BB_W3),a
                push de                         ; кадр HandlerBail: IP обработчика и адрес возврата
                call .body
                pop de
                dec a
                jp m,KERNEL_OBJECTS_B           ; 0 — следующий объект (V_BP) общим циклом
                jr z,.translatedCall            ; 1 — снаряд V_BP ядро не берёт: CALL обработчика
                ld a,$$A_00677                  ; 2 — конец списка
                ld hl,A_00677
                jp FARJP
.translatedCall:
                ld de,NATIVE_IP0
                jp KERNEL_OBJECTS_B.call
; Снаряды, пока следующий объект — снаряд. Выход: A = 0 — следующий объект другой (V_BP, V_AX заданы), 1 — снаряд V_BP
; не взят (записей не было), 2 — конец списка (V_AX = #FFFF). [2FC4] снаряды не пишут — проверяется один раз на пачку.
; [2EFC] проверяется на входе: дальше ядро записывает туда только значение < #3C8.
; Записи движения [bp+3…5] при BP, кратном 16, не могут затронуть [2EFC…2EFD].
.body:          ld (NATIVE_SP),sp
                ld a,(#4000+#2FC4)
                or a
                jr nz,.refuse                   ; не 0 — уничтожение обычным вызовом
                ld a,(#4000+#2EFD)
                cp #3F
                jr nc,.refuse                   ; [2EFC] не у края памяти спрайтов
                call BulletRun
                cp 3
                ret nz                          ; пачка закончена: A — прежний код выхода
                jr .bullet                      ; остаток — общий путь
.refuse:        ld a,1
                ret
.bullet:        ld hl,(V_BP)
                ld a,l
                and #0F
                jr nz,.refuse                   ; BP не кратен 16
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld c,(ix+#34)
                ld b,(ix+#35)                   ; BC = BX = [bp+#34]
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.general
                ld h,b                          ; ES = #1000: адрес #10000 + BX
                ld l,c
                ld a,b
                rlca
                rlca
                and 3
                add a,4                         ; страница V30 = 4 + BX >> 14
                jr .page
.general:       push bc
                ld a,h
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a                          ; C = ES >> 12
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = ES·16 & #FFFF
                pop de
                push de
                add hl,de
                ld a,c
                adc a,0                         ; A:HL = ES·16 + BX
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; A — страница V30
                pop bc
.page:          cp WORK_PAGE
                jr z,.refuse                    ; описание в рабочем ОЗУ
                ld e,a                          ; E — страница описания
                ld a,h
                and #3F
                cp #3F
                jr c,.inside
                ld a,l
                cp #FB
                jr nc,.refuse                   ; смещение + 6 > #4000
                ld a,#3F
.inside:        or #C0
                ld h,a                          ; HL → описание в окне W3
                ld a,(BB_W3)
                cp e
                jr z,.mapped
                ld a,e
                ld (BB_W3),a
                add a,V30_PAGE_BASE
                push bc
                ld bc,PORT_PAGE3
                out (c),a
                pop bc
.mapped:        ld (V_BX),bc                    ; BX = [bp+#34]
                ld c,(hl)                       ; C — [bx]: X
                inc hl
                ld b,(hl)                       ; B — [bx+1]: Y
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — [bx+2]: код
                inc hl
                inc hl
                ld a,(hl)
                ex af,af'                       ; A' — [bx+5]: старший байт атрибута
                push de
                ld e,(ix+#30)
                ld d,(ix+#31)
                ; Промежуточный AX = [bp+#30] не читается: до любого выхода его заменяет атрибут или .full.
                ld l,(ix+3)
                ld h,(ix+4)
                bit 7,d                         ; Z — AX ≥ 0
                add hl,de                       ; [bp+3] += AX ($0A72); CF — перенос
                ld (ix+3),l
                ld (ix+4),h
                jr nz,.negative
                jr nc,.moved
                inc (ix+5)                      ; $0A7C
                jr .moved
.negative:      jr c,.moved
                dec (ix+5)                      ; $0A85
.moved:         ld hl,(#4000+#2EFC)
                ld (V_SI),hl                    ; SI = [2EFC]
                ld (V_DI),hl                    ; DI = SI
                ex af,af'
                ld de,8
                bit 6,a
                jr z,.size
                ld e,16                         ; бит 14 атрибута — две записи
.size:          ex af,af'
                add hl,de                       ; AX = SI + размер
                ld de,#3C8
                or a
                sbc hl,de
                jr nc,.full                     ; AX ≥ #3C8: память спрайтов заполнена
                add hl,de
                ld (#4000+#2EFC),hl             ; [2EFC] = AX
                ld hl,(V_SI)
                set 7,h                         ; HL → C000:SI в окне W2
                ld e,b
                ld a,b
                rla
                sbc a,a
                ld d,a                          ; DE = байт Y со знаком
                ld a,(ix+8)
                ld (V_DX),a
                add a,e
                ld (hl),a
                inc hl
                ld a,(ix+9)
                ld (V_DX+1),a                   ; DX = [bp+8]
                adc a,d
                ld (hl),a                       ; [si] = Y
                inc hl
                pop de
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+2] = код
                inc hl
                ld a,(ix+6)
                ld (hl),a
                ld (V_AX),a
                inc hl
                ex af,af'
                ld (hl),a                       ; [si+4] = атрибут
                ld (V_AX+1),a
                inc hl
                ld e,c
                ld a,c
                rla
                sbc a,a
                ld d,a                          ; DE = байт X со знаком
                ld a,(ix+4)
                ld (V_CX),a
                add a,e
                ld (hl),a
                inc hl
                ld a,(ix+5)
                ld (V_CX+1),a                   ; CX = [bp+4]
                adc a,d
                ld (hl),a                       ; [si+6] = X
                jr .bounds
.full:          add hl,de
                ld (V_AX),hl
                pop de
.bounds:        ld a,(ix+#32)
                cp #2C
                jr nz,.left
                ld a,(ix+#33)
                cp #83
                jr nz,.left
                ld a,(ix+5)                     ; $E9EF: [bp+4] ≥ #2C0 — уход; сравнение со старшего байта
                cp #02
                jr c,.next
                jr nz,.destroy
                ld a,(ix+4)
                cp #C0
                jr nc,.destroy
                jr .next
.left:          ld a,(ix+5)                     ; $E9E7: [bp+4] < #140 — уход
                cp #01
                jr c,.destroy
                jr nz,.next
                ld a,(ix+4)
                cp #40
                jr c,.destroy
.next:          ld e,(ix+#1C)                   ; $066A: MOV AX,[bp+#1C]; CMP AX,#FFFF; JE $0677; MOV BP,AX
                ld d,(ix+#1D)
                ld (V_AX),de
                ld a,d
                and e
                inc a
                jr z,.end
                ld (V_BP),de
                ld a,d
                cp #3F
                jr nc,.other                    ; у края рабочего ОЗУ — общим циклом (перевод)
                set 6,d
                ld a,(de)
                cp low NATIVE_IP0
                jr nz,.other
                inc de
                ld a,(de)
                cp high NATIVE_IP0
                jp z,.bullet
.other:         xor a
                ret
.end:           ld a,2
                ret
.destroy:       ld de,0                         ; продолжение с $E9F7 — переводом
                ld a,$$A_0E9F7
                ld hl,A_0E9F7
                jp HandlerBail

BB_W3           DB #FF                          ; страница V30 в окне W3 во время пачки снарядов

; Плотная пачка: ES = #1000, записи объектов по 64 байта ниже #2000, буфер выровнен по 8,
; описание без второй записи. Записи объектов не пересекают друг друга и глобальный #2EFC;
; описание — ROM. До выхода никто не читает промежуточные AX/BX/CX/DX/SI/DI и #2EFC:
; сохраняем результат последнего спрайта один раз. Необычный вход — прежний BulletBatch.
; IX — последний принятый объект, IY — следующий адрес буфера в W2. A = 3 — продолжить общий путь.
; VDAC2+: кандидат проверяется по HL (IX меняется только у принятого — отказ без PUSH/POP); байты описания прошлого
; снаряда пачки — в BR_XY, BR_CODE, BR_ATTR (то же [bp+#34] — без окна W3 и шести чтений; BR_DESC = #FFFF — кэш пуст,
; такое BX отсекает проверка края страницы); следующий снаряд плотной раскладки — сразу к проверке места в буфере.
BulletRun:      ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.decline
                ld hl,(#6EFC)
                ld a,l
                and 7
                jr nz,.decline
                set 7,h
                push hl
                pop iy
                ld ix,#FFFF                     ; ещё нет принятого объекта, нечего сохранять при отказе
                ld hl,#FFFF
                ld (BR_DESC),hl
                ld hl,(V_BP)
                ld (BR_NEXT),hl
                jr .candidate
.decline:       ld a,3
                ret
; Кандидат HL = BP: проверки до записей.
.candidate:     ld a,h
                cp #20
                jp nc,.fallback
                ld a,l
                and #3F
                jp nz,.fallback
                set 6,h                         ; HL → запись кандидата (W1)
.checked:       ld a,iyh                        ; следующая запись должна целиком поместиться до #3C8
                cp #83
                jr c,.room
                jp nz,.fallback
                ld a,iyl
                cp #C0
                jp nc,.fallback
.room:          ld e,l
                ld d,h                          ; DE → запись кандидата
                ld a,l
                or #34
                ld l,a
                ld a,(hl)
                inc l
                ld h,(hl)
                ld l,a                          ; HL = BX = [bp+#34]
                ld a,h
                and #3F
                cp #3F
                jr nz,.inside
                ld a,l
                cp #FB
                jp nc,.fallback                 ; описание через край страницы V30
.inside:        ld a,(BR_DESC)
                cp l
                jr nz,.load
                ld a,(BR_DESC+1)
                cp h
                jr z,.accept                    ; то же описание, что у прошлого снаряда пачки
.load:          push hl
                ld a,h
                rlca
                rlca
                and 3
                add a,4                         ; ES:BX лежит только в страницах ROM 4…7
                ld c,a
                ld a,h
                or #C0
                ld h,a                          ; HL → описание в окне W3
                ld a,(BB_W3)
                cp c
                jr z,.mapped
                ld a,c
                ld (BB_W3),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE3
                out (c),a
.mapped:        ld c,(hl)
                inc hl
                ld b,(hl)
                inc hl
                ld (BR_XY),bc                   ; байты X и Y
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — код
                inc hl
                inc hl
                ld a,(hl)                       ; старший байт атрибута
                pop hl
                bit 6,a
                jp nz,.fallback                 ; вторая запись — общий путь
                ld (BR_CODE),bc
                ld (BR_ATTR),a
                ld (BR_DESC),hl
.accept:        ld ixl,e
                ld ixh,d                        ; IX — принятый снаряд
                ld e,(ix+#30)
                ld d,(ix+#31)
                ld l,(ix+3)
                ld h,(ix+4)
                bit 7,d
                add hl,de                       ; прежнее 24-битное движение с переносом/заёмом
                ld (ix+3),l
                ld (ix+4),h
                jr nz,.negative
                jr nc,.moved
                inc (ix+5)
                jr .moved
.negative:      jr c,.moved
                dec (ix+5)
.moved:         ld b,h                          ; B — новый [bp+4] (запись и проверка границ)
                push iy
                pop hl
                ld a,(BR_XY+1)
                ld e,a
                rla
                sbc a,a
                ld d,a                          ; DE = байт Y со знаком
                ld a,(ix+8)
                add a,e
                ld (hl),a
                inc l
                ld a,(ix+9)
                adc a,d
                ld (hl),a
                inc l
                ld de,(BR_CODE)
                ld (hl),e
                inc l
                ld (hl),d
                inc l
                ld a,(ix+6)
                ld (hl),a
                inc l
                ld a,(BR_ATTR)
                ld (hl),a
                inc l
                ld a,(BR_XY)
                ld e,a
                rla
                sbc a,a
                ld d,a                          ; DE = байт X со знаком
                ld a,b
                add a,e
                ld (hl),a
                inc l
                ld a,(ix+5)
                ld c,a                          ; C — [bp+5]
                adc a,d
                ld (hl),a
                inc hl                          ; последняя прибавка может пересечь границу 256 байт
                push hl
                pop iy
                ld a,(ix+#32)
                cp #2C
                jr nz,.left
                ld a,(ix+#33)
                cp #83
                jr nz,.left
                ld a,c
                cp 2
                jr c,.next
                jr nz,.destroy
                ld a,b
                cp #C0
                jr nc,.destroy
                jr .next
.left:          ld a,c
                cp 1
                jr c,.destroy
                jr nz,.next
                ld a,b
                cp #40
                jr c,.destroy
.next:          ld l,(ix+#1C)
                ld h,(ix+#1D)
                ld (BR_NEXT),hl
                ld a,h
                cp #20
                jr nc,.nextFar
                ld a,l
                and #3F
                jr nz,.nextFar
                set 6,h
                ld a,(hl)
                cp low NATIVE_IP0
                jr nz,.other
                inc l
                ld a,(hl)
                cp high NATIVE_IP0
                jr nz,.other
                dec l
                jp .checked                     ; плотная раскладка: BP < #2000 и кратен #40 — уже проверено
.nextFar:       ld a,h                          ; конец списка, край рабочего ОЗУ или снаряд вне плотной раскладки
                and l
                inc a
                jr z,.end
                ld a,h
                cp #3F
                jr nc,.other                    ; у края рабочего ОЗУ — общим циклом (перевод)
                set 6,h
                ld a,(hl)
                cp low NATIVE_IP0
                jr nz,.other
                inc hl
                ld a,(hl)
                cp high NATIVE_IP0
                jr nz,.other
                ld hl,(BR_NEXT)
                jp .candidate                   ; снаряд вне плотной раскладки: кандидат откажет — общий путь
.fallback:      ld a,ixh
                inc a
                jp z,.decline
                call .flushNext
                ld a,3
                ret
.other:         call .flushNext
                xor a
                ret
.end:           call .flush
                ld hl,#FFFF
                ld (V_AX),hl
                ld a,2
                ret
.destroy:       call .flush
                set 7,h                         ; HL — SI последнего спрайта
                inc l
                inc l
                inc l
                inc l
                ld e,(hl)
                inc l
                ld d,(hl)
                ld (V_AX),de                    ; при уничтожении AX — атрибут, не адрес следующего объекта
                ld sp,(NATIVE_SP)               ; тот же стек, что у выхода общего пути
                ld de,0
                ld a,$$A_0E9F7
                ld hl,A_0E9F7
                jp HandlerBail
.flushNext:     call .flush
                ld hl,(BR_NEXT)
                ld (V_AX),hl
                ld (V_BP),hl
                ret
.flush:         push ix
                pop hl
                res 6,h
                ld (V_BP),hl
                ld l,(ix+#34)
                ld h,(ix+#35)
                ld (V_BX),hl
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_CX),hl
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_DX),hl
                push iy
                pop hl
                res 7,h
                ld (#6EFC),hl
                ld de,8
                or a
                sbc hl,de
                ld (V_SI),hl
                ld (V_DI),hl
                ret
BR_NEXT        DW 0

; ROM $0A53 (IP $0653, раз за кадр) — KERNEL_SPRITE_CLEAR: с 2026-09-25 в нативной странице (vdac2p_native.asm,
; вход через NATIVE) — с границей прошлой очистки.


; --- метатайлы фона -------------------------------------------------------------------------------------------
; ROM $EF02 (IP $EB02, слой B: VRAM #D8000) и $EE95 (IP $EA95, слой A: #D0000, продолжение на $EF13): AX = слово
; ES:[bx−#2971] (у слоя A — ES:[bx−#39D9]); DS = #3000, ES = VRAM слоя; биты 15, 14 AX — вариант, SI = (AX & #3FFF)·144
; (DX = ·16): 6 строк по 8 тайлов из DS:SI по 3 байта (4 байта с перекрытием) в ES:DI. Вариант 00 — строки DI + #100·r,
; тайлы вперёд; 10 — строки DI + #500 − #100·r, первое слово тайла XOR #8000; 01 — строки DI + #1C + #100·r, тайлы
; назад (шаг −4), XOR #4000; 11 — строки DI + #51C − #100·r, назад, XOR #C000. После: AX — SI начала (00) или последнее
; слово с XOR, CX = #0800, SI += 144, DI — за последней строкой, BX += 2, DS и ES прежние; флаги после RET не живут.
; Пометки для адаптера FT812 — группы и строки всех байтов строк (как VIDEO_MARK у записей). Условия ядра: слово
; таблицы и 145 байт тайлов — в одной странице V30 каждое, DI ≤ #3AE0 (все строки в странице VRAM); иначе обычный
; перевод. Окно W2 — страница тайлов, W3 — VRAM (DISPATCH после RET отображает страницу кода сам).
KERNEL_METATILE_B:
                ld de,-#2971
                ld a,#36
                call MetatileCore
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_0EF02
                ld hl,K_0EF02
                jp FARJP

KERNEL_METATILE_A:
                ld de,-#39D9
                ld a,#34
                call MetatileCore
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_0EE95
                ld hl,K_0EE95
                jp FARJP

; DE — смещение слова таблицы от BX, A — страница V30 VRAM слоя (#34, #36). CF = 1 — условия не выполнены (память V30
; не тронута). Портит всё.
MetatileCore:   ld (MT_VRAM),a
                ld hl,(V_DI)
                ld a,h
                cp #3A
                jr c,.diOk
                scf
                ret nz                          ; DI > #3AFF
                ld a,l
                cp #E1
                ccf
                ret c                           ; DI > #3AE0
.diOk:          ld hl,(V_BX)
                add hl,de                       ; смещение слова в ES
                ld de,(V_ES)
                call SegPage                    ; A — страница, HL — смещение в странице
                ret c
                ld c,a
                ld a,h
                cp #3F
                jr c,.word
                ld a,l
                inc a
                scf
                ret z                           ; слово на границе страниц
.word:          ld a,c
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                set 7,h
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE = AX (слово таблицы)
                ld a,d
                and #C0
                ld (MT_KIND),a
                ld a,d
                and #3F
                ld h,a
                ld l,e                          ; HL = AX & #3FFF
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·16
                ld (MT_DX),hl
                ex de,hl
                ld h,d
                ld l,e
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·128
                add hl,de                       ; SI = ·144
                ld (MT_SI),hl
                ; тайлы DS = #3000: страница #0C + SI >> 14, смещение + 144 в той же странице
                ld a,h
                and #3F
                cp #3F
                jr c,.srcOk
                ld a,l
                cp #6F
                ccf
                ret c                           ; SI & #3FFF > #3F6F
.srcOk:         ld a,h
                rlca
                rlca
                and 3
                add a,#0C
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,(MT_VRAM)
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE3
                out (c),a
                ; копирование строк: HL — тайлы (W2), DE — VRAM (W3), IX → пометки слоя
                ld a,h
                and #3F
                or #80
                ld h,a
                ld de,(V_DI)
                ld a,(MT_VRAM)
                cp #34
                ld ix,VRAM_DIRTY0
                jr z,.marks
                ld ix,VRAM_DIRTY1
.marks:         ld a,(MT_KIND)
                ld c,a
                ld b,6                          ; строк
                ; начало первой строки и шаг строк
                push hl
                ld hl,0
                bit 7,c
                jr z,.noH
                ld hl,#500
.noH:           bit 6,c
                jr z,.noV
                ld a,l
                add a,#1C
                ld l,a
.noV:           add hl,de
                ld (MT_ROW),hl                  ; DI первой строки
                pop hl
.row:           push bc
                ld de,(MT_ROW)
                push de
                bit 6,c
                jr z,.span
                ld a,e                          ; тайлы назад: байты строки с MT_ROW − #1C
                sub #1C
                ld e,a
                jr nc,.span
                dec d
.span:          call MetatileMarks              ; пометки байтов строки
                pop de
                ld a,d
                or #C0
                ld d,a                          ; DE → VRAM в окне W3
                ld b,8
.tile:          ld a,c
                or a
                jr nz,.xor
                ld a,(hl)                       ; вариант 00: MOVSW, MOVSW, DEC SI — 4 байта как есть
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                inc de                          ; SI += 3
                djnz .tile
                jr .rowDone
.xor:           ld a,(hl)                       ; LODSW; XOR; STOSW; MOVSW; DEC SI
                ld (de),a
                ld (MT_AX-1),a                  ; младший байт AX
                inc hl
                inc de
                ld a,(hl)
                xor c
                ld (de),a
                ld (MT_AX),a                    ; старший байт AX (с XOR)
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                inc de                          ; SI += 3
                bit 6,c
                jr z,.forward
                ld a,e                          ; тайлы назад: DI −= 8 после 4 байт
                sub 8
                ld e,a
                jr nc,.forward
                dec d
.forward:       djnz .tile
.rowDone:       ld de,(MT_ROW)
                ld a,d
                bit 7,c
                jr nz,.rowUp
                add a,1
                jr .rowSet
.rowUp:         sub 1
.rowSet:        ld d,a
                ld (MT_ROW),de
                pop bc
                djnz .row
                ; регистры ROM
                ld (V_DI),de                    ; DI за последней строкой
                ld hl,(V_BX)
                inc hl
                inc hl
                ld (V_BX),hl
                ld hl,#0800
                ld (V_CX),hl
                ld hl,(MT_DX)
                ld (V_DX),hl
                ld hl,(MT_SI)
                ld a,(MT_KIND)
                or a
                jr nz,.axWord
                ld (V_AX),hl                    ; вариант 00: AX = SI начала
                jr .si
.axWord:        ld de,(MT_AX-1)
                ld (V_AX),de
.si:            ld de,144
                add hl,de
                ld (V_SI),hl
                or a                            ; CF = 0 (окно W3 — VRAM: DISPATCH отобразит страницу кода)
                ret

; Пометки VRAM строки тайлов: DE — смещение первого байта строки (32 байта), IX → пометки групп слоя (+512 — строк).
; Как VIDEO_MARK: группа = смещение >> 5, строка = смещение >> 8; VIDEO_DIRTY. Сохраняет BC, DE, HL.
MetatileMarks:  push hl
                push de
                push bc
                ld a,1
                ld (VIDEO_DIRTY),a
                call .one
                ld hl,31
                add hl,de
                ex de,hl
                call .one
                pop bc
                pop de
                pop hl
                ret
; Группа и строка смещения DE.
.one:           push de
                ld a,e
                rlca
                rlca
                rlca
                and 7
                ld l,a
                ld a,d
                add a,a
                add a,a
                add a,a
                or l
                ld l,a
                ld a,d
                rlca
                rlca
                rlca
                and 1
                ld h,a                          ; HL = группа (смещение >> 5)
                push ix
                pop bc
                add hl,bc
                ld (hl),#FF
                ld l,d
                ld h,0                          ; строка = смещение >> 8
                inc b
                inc b                           ; сводка строк = таблица + 512
                add hl,bc
                ld (hl),#FF
                pop de
                ret

; Сегмент DE : смещение HL → A — страница V30 (линейный адрес >> 14), HL — смещение в странице; CF = 0. Портит F, BC,
; DE.
SegPage:        ld a,d
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a                          ; C = сегмент >> 12
                ex de,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = сегмент·16 & #FFFF
                add hl,de
                ld a,c
                adc a,0                         ; A:HL — линейный адрес
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; A = страница
                ld c,a
                ld a,h
                and #3F
                ld h,a
                ld a,c
                or a                            ; CF = 0
                ret

MT_VRAM         DB 0
MT_KIND         DB 0
MT_DX           DW 0
MT_SI           DW 0
MT_ROW          DW 0
                DB 0
MT_AX           DB 0                            ; MT_AX-1 — младший байт

; --- столкновения ---------------------------------------------------------------------------------------
; ROM $F978 (IP $F578): прямоугольник объекта SS:BP (X = [bp+4], Y = [bp+8]; смещения хитбокса ES:BX: +0 и +2 —
; к X, +4 и +6 — к Y) против записи DS:SI (границы X1 = [si+2], X2 = [si+4], Y1 = [si+6], Y2 = [si+8]), CF = 1 —
; пересечение. Сканы над ним: $F885 (запись #56 при [#57] = 0), $F893 (#76, #136, #156), $F8AA (#F6, #116), $F8BF
; (#B6, #D6 с признаком [si+1]; #A8, #C8 — привязка [si+#C] = BP), $F948 (3 записи с #4D6) и $F960 (24 записи с
; #176) — шаг #20 по [si+1] ≠ 0; $FA94 — вся цепочка для объекта с BX = DI. Флаги после их RET живут только CF
; (flags.liveness); AX, BX, CX, SI на выходе — как у ROM. Условия ядра: DS = SS = #4000; BP кратен #20 и меньше
; #3F00 — записи сканов ([si+1] ≡ #17, [si+#C] ≡ #14 по модулю #20) не задевают [bp+4…9], поэтому X и Y
; читаются один раз; хитбокс ES:BX…BX+7 в одной странице V30 вне рабочего ОЗУ (не меняется). Иначе — обычный
; перевод с входа (K_). Вызовы ядра — на стеке V30 ниже SP (остатки, как у CALL ROM).
KERNEL_COLLIDE_78:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                ld hl,(V_SI)
                ld a,h
                cp #3F
                jr nc,.translated               ; запись у края рабочего ОЗУ
                set 6,h
                push hl
                pop ix
                call BoxTest
                jp CollideReturn
.translated:    ld a,$$K_0F978
                ld hl,K_0F978
                jp FARJP

KERNEL_COLLIDE_85:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call Collide85
                jp CollideReturn
.translated:    ld a,$$K_0F885
                ld hl,K_0F885
                jp FARJP

KERNEL_COLLIDE_93:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call Collide93
                jp CollideReturn
.translated:    ld a,$$K_0F893
                ld hl,K_0F893
                jp FARJP

KERNEL_COLLIDE_AA:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call CollideAA
                jp CollideReturn
.translated:    ld a,$$K_0F8AA
                ld hl,K_0F8AA
                jp FARJP

KERNEL_COLLIDE_BF:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call CollideBF
                jp CollideReturn
.translated:    ld a,$$K_0F8BF
                ld hl,K_0F8BF
                jp FARJP

KERNEL_COLLIDE_48:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call NC48Far
                jp CollideReturn
.translated:    ld a,$$K_0F948
                ld hl,K_0F948
                jp FARJP

KERNEL_COLLIDE_60:
                ld hl,(V_BX)
                call CollideSetup
                jr c,.translated
                call NC60Far
                jp CollideReturn
.translated:    ld a,$$K_0F960
                ld hl,K_0F960
                jp FARJP

KERNEL_COLLIDE_A94:
                ld hl,(V_DI)
                call CollideSetup
                jr c,.translated
                call CollideA94
                jp CollideReturn
.translated:    ld a,$$K_0FA94
                ld hl,K_0FA94
                jp FARJP

; CF → бит 0 V_FL, RET V30.
CollideReturn:  ld hl,V_FL
                jr c,.carry
                res 0,(hl)
                pop de
                jp DISPATCH
.carry:         set 0,(hl)
                pop de
                jp DISPATCH

; Условия ядра и данные объекта: HL — BX (смещение хитбокса в ES). KC_X = [bp+4], KC_Y = [bp+8], KC_HB0…KC_HB6 —
; слова хитбокса (окно W2 — его страница), KC_XR, KC_XL — края X объекта для BoxX (BoxEdges). CF = 1 — ядро не берёт.
; Окно W3 — нативная страница (с 2026-09-25: сканы зовут из неё BoxX; вызывающие CollideSetup — нативный код этой
; страницы или ядра резидента, которые дальше W3 не читают: их выход — DISPATCH/FARJP, отображающие своё, или возврат в
; цикл объектов, как после NC48Far/NC60Far). Портит всё, кроме IX, IY.
; VDAC2+ (2026-09-25, скорость): у ES = #1000 хитбокс — в ROM (страницы 4…7) и не меняется: тот же BX, что у прошлого
; взятого вызова (KC_BX), — слова уже в KC_HB, без окна W2 и восьми LDI (объект зовёт подряд сканы $F960, $F948, …
; с одним хитбоксом). Сканы окно W2 не читают — только KC_*. Иной ES — KC_BX = #FFFF (копия не из ROM).
CollideFail:    scf                             ; ранние отказы CollideSetup (JR назад короче JP)
                ret
CollideSetup:   ex de,hl                        ; DE — BX до проверки кэша и .general (VDAC2+ 2026-09-25, скорость:
                                                ; без PUSH/POP, X и Y — BC и INC L: ≈316 тактов против ≈408)
                ld a,NATIVE_PAGE0
                ld bc,PORT_PAGE3
                out (c),a                       ; W3 — нативная страница (BoxX, BoxEdges, KC_XR, KC_XL)
                ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,CollideFail               ; SS = #4000 — всегда (стек V30 — стек Z80)
                ld hl,(V_BP)
                ld a,l
                and #1F
                jr nz,CollideFail               ; BP не кратен #20
                ld a,h
                cp #3F
                jr nc,CollideFail
                set 6,h
                ld a,l
                or 4
                ld l,a                          ; HL → [bp+4] (BP кратен #20: без переноса)
                ld c,(hl)
                inc l
                ld b,(hl)
                ld (KC_X),bc                    ; X = [bp+4]
                ld a,l
                add a,3
                ld l,a                          ; HL → [bp+8]
                ld c,(hl)
                inc l
                ld b,(hl)
                ld (KC_Y),bc                    ; Y = [bp+8]
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.general                  ; ES = #1000: адрес #10000 + BX
                ld hl,(KC_BX)
                sbc hl,de                       ; CF = 0 после OR
                jp z,BoxEdges                   ; тот же хитбокс ROM: KC_HB готовы — края X, CF = 0
                ex de,hl                        ; HL = BX
.miss:          ld (KC_BXNEW),hl
                ld de,#FFFF
                ld (KC_BX),de                   ; копия годна только после удачного копирования
                ld a,h
                rlca
                rlca
                and 3
                add a,4                         ; страница V30 = 4 + BX >> 14
                jr .page
.general:       push de                         ; BX
                ld de,#FFFF
                ld (KC_BX),de                   ; копия хитбокса — не из ROM: кэш недействителен
                ld (KC_BXNEW),de
                ld a,h
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a                          ; C = ES >> 12
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = ES·16 & #FFFF
                pop de
                add hl,de
                ld a,c
                adc a,0                         ; A:HL = ES·16 + BX
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; A = страница V30
.page:          cp WORK_PAGE
                jr z,.fail                      ; рабочее ОЗУ — мог бы меняться сканом
                ld c,a
                ld a,h
                and #3F
                ld h,a
                cp #3F
                jr c,.inside
                ld a,l
                cp #F9
                jr nc,.fail                     ; смещение + 8 > #4000
.inside:        ld a,c
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                set 7,h                         ; HL → хитбокс в окне W2
                ld de,KC_HB0
                ld bc,8                         ; восемь LDI — 128 тактов против 178 у LDIR со счётчиком
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ld hl,(KC_BXNEW)
                ld (KC_BX),hl                   ; ES = #1000 — BX хитбокса ROM, иначе #FFFF
                jp BoxEdges                     ; края X, CF = 0
.fail:          scf
                ret

; $F978 над записью IX (#4000 + SI): CF — пересечение, V_AX — AX ROM. Портит AF, BC, DE, HL.
BoxTest:        ld hl,(KC_X)                    ; AX = X
                ld e,(ix+2)
                ld d,(ix+3)
                ld a,h
                cp d
                jr nz,.x1
                ld a,l
                cp e
.x1:            jr c,.left                      ; X < X1
                ld e,(ix+4)
                ld d,(ix+5)
                ld a,h
                cp d
                jr nz,.x2
                ld a,l
                cp e
.x2:            jr nc,.right                    ; X ≥ X2
.y:             ld hl,(KC_Y)                    ; AX = Y
                ld e,(ix+6)
                ld d,(ix+7)
                ld a,h
                cp d
                jr nz,.y1
                ld a,l
                cp e
.y1:            jr c,.low                       ; Y < Y1
                ld e,(ix+8)
                ld d,(ix+9)
                ld a,h
                cp d
                jr nz,.y2
                ld a,l
                cp e
.y2:            jr nc,.high                     ; Y ≥ Y2
                ld (V_AX),hl
                scf                             ; внутри по Y ($F992)
                ret
.left:          ld bc,(KC_HB2)                  ; $F994: AX = X + [bx+2]; AX < X1 — нет, иначе к Y (DE = X1)
                add hl,bc
                ld a,h
                cp d
                jr nz,.left1
                ld a,l
                cp e
.left1:         jr nc,.y
                ld (V_AX),hl
                or a                            ; CF = 0
                ret
.right:         ld bc,(KC_HB0)                  ; $F99F: AX = X + [bx]; AX < X2 — к Y, иначе нет (DE = X2)
                add hl,bc
                ld a,h
                cp d
                jr nz,.right1
                ld a,l
                cp e
.right1:        jr c,.y
                ld (V_AX),hl
                or a
                ret
.low:           ld bc,(KC_HB6)                  ; $F9AA: AX = Y + [bx+6]; AX ≥ Y1 — пересечение (DE = Y1)
                add hl,bc
                ld (V_AX),hl
                ld a,h
                cp d
                jr nz,.low1
                ld a,l
                cp e
.low1:          ccf
                ret
.high:          ld bc,(KC_HB4)                  ; $F9B6: AX = Y + [bx+4]; AX < Y2 — пересечение (DE = Y2)
                add hl,bc
                ld (V_AX),hl
                ld a,h
                cp d
                ret nz
                ld a,l
                cp e
                ret

; Сканы ниже — через BoxX (нативная страница в W3 — от CollideSetup): HL → запись + 2, BC = X, DE = XR (2026-09-25,
; скорость, партия 2: BoxTest по IX стоил ≈240 тактов на запись, BoxX — ≈140). Вход .go — BC и DE уже загружены
; (цепочки CollideA94 и NDamage грузят их раз на объект). CF, SI, AX — как у ROM; BC, DE сохраняются.
; $F885: SI = #56; [si+1] ≠ 0 — CF = 0, иначе $F978.
Collide85:      ld bc,(KC_X)
                ld de,(KC_XR)
.go:            ld hl,#56
                ld (V_SI),hl
                ld a,(#4000+#57)
                or a
                ret nz                          ; CF = 0 после OR
                ld hl,#4000+#56+2
                jp BoxX

; $F893: записи #76, #136, #156 до первого пересечения.
Collide93:      ld bc,(KC_X)
                ld de,(KC_XR)
.go:            ld hl,#76
                ld (V_SI),hl
                ld hl,#4000+#76+2
                call BoxX
                ret c
                ld hl,#136
                ld (V_SI),hl
                ld hl,#4000+#136+2
                call BoxX
                ret c
                ld hl,#156
                ld (V_SI),hl
                ld hl,#4000+#156+2
                jp BoxX

; $F8AA: записи #F6, #116.
CollideAA:      ld bc,(KC_X)
                ld de,(KC_XR)
.go:            ld hl,COLL_AA                   ; кэш столкновений: объект в стороне от обеих записей (нативная
                call CollGroup                  ; страница в W3 — от CollideSetup)
                jr nc,.test
                ld (V_AX),hl
                ld hl,#116
                ld (V_SI),hl
                or a                            ; CF = 0 — промах обеих
                ret
.test:          ld hl,#F6
                ld (V_SI),hl
                ld hl,#4000+#F6+2
                call BoxX
                ret c
                ld hl,#116
                ld (V_SI),hl
                ld hl,#4000+#116+2
                jp BoxX

; $F8BF: #B6 и #D6 при [si+1] ≠ 0 (пересечение — [si+1] = 0, CF = 1); #A8 при [si+#C] = 0 и [#D4] ≠ BP, затем
; #C8 при [si+#C] = 0 и [#B4] ≠ BP (пересечение — [si+#C] = BP, CF = 0); [#D4] = BP у первой — сразу CF = 0.
CollideBF:      ld bc,(KC_X)
                ld de,(KC_XR)
.go:            ld hl,#B6
                ld (V_SI),hl
                ld a,(#4000+#B7)
                or a
                jr z,.second
                ld hl,#4000+#B6+2
                call BoxX
                jr nc,.second
                xor a
                ld (#4000+#B7),a                ; $F8B9: [si+1] = 0
                scf
                ret
.second:        ld hl,#D6
                ld (V_SI),hl
                ld a,(#4000+#D7)
                or a
                jr z,.third
                ld hl,#4000+#D6+2
                call BoxX
                jr nc,.third
                xor a
                ld (#4000+#D7),a
                scf
                ret
.third:         ld hl,#A8
                ld (V_SI),hl
                ld hl,(#4000+#B4)               ; [si+#C]
                ld a,h
                or l
                jr nz,.fourth
                push de
                ld hl,(#4000+#D4)
                ld de,(V_BP)
                or a
                sbc hl,de
                pop de
                jr z,.clear                     ; [#D4] = BP
                ld hl,#4000+#A8+2
                call BoxX
                jr nc,.fourth
                ld hl,(V_BP)                    ; $F907: [si+#C] = BP
                ld (#4000+#B4),hl
                or a
                ret
.fourth:        ld hl,#C8
                ld (V_SI),hl
                ld hl,(#4000+#D4)               ; [si+#C]
                ld a,h
                or l
                jr nz,.clear
                push de
                ld hl,(#4000+#B4)
                ld de,(V_BP)
                or a
                sbc hl,de
                pop de
                jr z,.clear                     ; [#B4] = BP
                ld hl,#4000+#C8+2
                call BoxX
                jr nc,.clear
                ld hl,(V_BP)
                ld (#4000+#D4),hl
.clear:         or a
                ret
                ASSERT (#56 & #FF) <= #F6 && (#76 & #FF) <= #F6 && (#136 & #FF) <= #F6 && (#156 & #FF) <= #F6
                ASSERT (#F6 & #FF) <= #F6 && (#116 & #FF) <= #F6 && (#B6 & #FF) <= #F6 && (#D6 & #FF) <= #F6
                ASSERT (#A8 & #FF) <= #F6 && (#C8 & #FF) <= #F6

; VDAC2+: сканы $F948/$F960 развёрнутыми проверками (NCollide48/NCollide60 в нативной странице окна W3): те же BoxTest по
; тем же записям, те же SI, CX, CF. Окно W3 после них — нативная страница (DISPATCH и FARJP отображают своё сами).
WeaponIdleFar:  ld a,NATIVE_PAGE0
                ld bc,PORT_PAGE3
                out (c),a
                jp WeaponIdle
NC60Far:        ld a,NATIVE_PAGE0
                ld bc,PORT_PAGE3
                out (c),a
                jp NCollide60
NC48Far:        ld a,NATIVE_PAGE0
                ld bc,PORT_PAGE3
                out (c),a
                jp NCollide48

; $FA94: объект BP за правым краем ([bp+4] ≥ #2B4) — CF = 0; иначе BX = DI и цепочка сканов.
CollideA94:     ld hl,(KC_X)
                ld de,#2B4
                or a
                sbc hl,de
                ret nc                          ; CF = 0
                ld hl,(V_DI)
                ld (V_BX),hl
                ld bc,(KC_X)
                ld de,(KC_XR)                   ; X и XR — для BoxX сканов (входы .go)
                call CollReject                 ; кэш столкновений (нативная страница в W3 — от CollideSetup)
                jr nc,.scan
                ld hl,#156
                ld (V_SI),hl                    ; как после $F493 без попадания (AX — от CollReject)
                jr .aa                          ; $F485, $F493 — промах; дальше $F4AA (свой отказ), $F4BF, $F548, $F560
.scan:          call Collide85.go
                jr nc,.a6
                ld a,1
                ld (#4000+#57),a                ; $FAA2: [si+1] = 1 (SI = #56)
.a6:            call Collide93.go
                ret c                           ; $FAD6
.aa:            call CollideAA.go
                jr nc,.ba
                ld hl,(V_SI)
                set 6,h
                inc hl
                inc (hl)                        ; $FAB4: [si+1] += 1
                scf
                ret
.ba:            call CollideBF.go
                ret c
                call NC48Far
                jr nc,.cf
                ld hl,(V_SI)
                set 6,h
                inc hl
                ld (hl),0                       ; $FAC8: [si+1] = 0
                scf
                ret
.cf:            jp NC60Far                    ; $FACF: CF — как у скана

; --- скрипт движения ------------------------------------------------------------------------------------------
; ROM $F9C1 (IP $F5C1, 22 места вызова): CX = байт [bp+#17] шагов; шаг — байт скрипта ES:[bp+#14] (BX = [bp+#14]):
; бит 7 — [bp+#16] = байт & #1F (AL = он же) и шаг не считается; иначе биты 6, 5 — X ([bp+4]): 01 → +1, 11 → −1;
; биты 4, 3 — Y ([bp+8]) так же; затем бит 2 — конец отрезка ($FA0E: [bp+#12] += 2, слово ES:[[bp+#12]]: 0 —
; переход по ES:[bx+2] (новые [bp+#12] и [bp+#14]), CF = 1; старший байт #F0 — [bp+#17] = младший и следующее
; слово; иначе [bp+#14] = слово, CF = 0); без бита 2 — [bp+#14] += 1, LOOP; по концу CF = 0. AL после шага —
; байт, повёрнутый RCL шесть раз при CF = 0 (AH не меняется). Флаги после RET живут только CF. Условия ядра: ES =
; #1000 (обработчик IRQ0: адрес #10000 + BX, страницы V30 4…7 — чтения через окно W2 с учётом перехода страницы),
; BP < #3F00, [bp+#17] ≠ 0 (иначе LOOP шёл бы с CX = #FFFF) — проверки до записей; иначе обычный перевод (K_0F9C1).
KERNEL_SCRIPT:
                call ScriptCheck
                jr c,.translated
                call ScriptCore
                jp CollideReturn                ; CF → V_FL, RET V30
.translated:    ld a,$$K_0F9C1
                ld hl,K_0F9C1
                jp FARJP

; Условия ядра скрипта: ES = #1000, BP < #3F00, [bp+#17] ≠ 0. CF = 1 — нельзя; иначе IX → [bp]. Портит AF, HL.
ScriptCheck:    ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.fail
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.fail
                set 6,h
                push hl
                pop ix
                ld a,(ix+#17)
                or a
                ret nz                          ; CF = 0
.fail:          scf
                ret

; $F9C1 над IX → [bp] (условия ScriptCheck выполнены): записи, AX, BX, CX — как у ROM; CF — результат. Портит всё,
; кроме IX.
ScriptCore:     ld b,(ix+#17)                   ; B = CX (CH = 0)
.step:          ld l,(ix+#14)
                ld h,(ix+#15)
                ld (V_BX),hl                    ; BX = [bp+#14]
                call ScriptByte                 ; A = ES:[bx]
                ld e,a
                ld d,high SCRIPT_FLAGS
                ld a,(de)
                cp 2
                jr z,.speed                     ; бит 7
                push af
                inc d                           ; SCRIPT_DX
                ld a,(de)
                or a
                jr z,.noX
                ld l,(ix+4)
                ld h,(ix+5)
                inc hl                          ; INC HL не меняет S от OR
                jp p,.xStore
                dec hl
                dec hl
.xStore:        ld (ix+4),l
                ld (ix+5),h
.noX:           inc d                           ; SCRIPT_DY
                ld a,(de)
                or a
                jr z,.noY
                ld l,(ix+8)
                ld h,(ix+9)
                inc hl
                jp p,.yStore
                dec hl
                dec hl
.yStore:        ld (ix+8),l
                ld (ix+9),h
.noY:           ld a,e                          ; AL = байт, повёрнутый RCL шесть раз при CF = 0
                rrca
                rrca
                rrca
                and #1F
                ld c,a
                ld a,e
                and 3
                rrca
                rrca
                or c
                ld (V_AX),a
                pop af
                or a
                jr nz,.segment                  ; бит 2 — конец отрезка
                ld l,(ix+#14)                   ; [bp+#14] += 1
                ld h,(ix+#15)
                inc hl
                ld (ix+#14),l
                ld (ix+#15),h
                djnz .step
                ld hl,0
                ld (V_CX),hl
                or a                            ; CF = 0
                ret
.speed:         ld a,e                          ; $FA03: [bp+#16] = AL = байт & #1F; INC CX и LOOP — без счёта
                and #1F
                ld (ix+#16),a
                ld (V_AX),a
                ld l,(ix+#14)
                ld h,(ix+#15)
                inc hl
                ld (ix+#14),l
                ld (ix+#15),h
                jp .step
.segment:       ld c,b                          ; $FA0E: CX на этом шаге
                ld b,0
                ld (V_CX),bc
.nextSegment:   ld l,(ix+#12)
                ld h,(ix+#13)
                inc hl
                inc hl
                ld (ix+#12),l
                ld (ix+#13),h                   ; [bp+#12] += 2
                ld (V_BX),hl                    ; BX = [bp+#12]
                call ScriptWord                 ; DE = ES:[bx]
                ld (V_AX),de
                ld a,d
                or e
                jr z,.jump
                ld a,d
                cp #F0
                jr nz,.pointer
                ld (ix+#17),e                   ; [bp+#17] = AL
                jr .nextSegment
.pointer:       ld (ix+#14),e
                ld (ix+#15),d                   ; [bp+#14] = AX
                or a                            ; CF = 0 (A = старший байт ≠ … OR не даёт переноса)
                ret
.jump:          ld hl,(V_BX)                    ; $FA2B: BX = ES:[bx+2]; [bp+#12] = BX; AX = ES:[bx]; [bp+#14] = AX
                inc hl
                inc hl
                call ScriptWord
                ld (V_BX),de
                ld (ix+#12),e
                ld (ix+#13),d
                ex de,hl
                call ScriptWord
                ld (V_AX),de
                ld (ix+#14),e
                ld (ix+#15),d
                scf                             ; CF = 1
                ret

; Байт ES:HL при ES = #1000 (страница V30 4 + HL >> 14, окно W2) → A. Портит C, DE, HL.
ScriptByte:     ld a,h
                rlca
                rlca
                and 3
                add a,4
                ld c,a
                ld a,(W2_PAGE)
                cp c
                jr z,.mapped
                ld a,c
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                push bc
                ld bc,PORT_PAGE2
                out (c),a
                pop bc
.mapped:        ld a,h
                and #3F
                or #80
                ld h,a
                ld a,(hl)
                ret

; Слово ES:HL при ES = #1000 → DE (байты могут лежать в разных страницах). Портит AF, C, HL.
ScriptWord:     push hl
                call ScriptByte
                pop hl
                push af
                inc hl
                call ScriptByte
                ld d,a
                pop af
                ld e,a
                ret

; Таблицы признаков байта скрипта SCRIPT_FLAGS, SCRIPT_DX, SCRIPT_DY — в области данных резидента #3900
; (v30z80_runtime.asm).

; ROM $FA3A (IP $F63A, 16 мест вызова): [bp+#26] += 1, AX = он; AX = [bp+#2A] — к $FA50; AX ≥ [bp+#2C] — [bp+#26] = 0 и
; к $FA50; иначе возврат. $FA50: [bp+#28] = 0 — возврат, иначе порождение объекта — обычный перевод с $FA57 (флаги
; там не живут). Флаги после RET не живут. BP у края рабочего ОЗУ — перевод с входа (K_0FA3A).
KERNEL_COUNTER:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                set 6,h
                push hl
                pop ix
                call CounterCore
                or a
                jr nz,.spawn
                pop de                          ; RET V30
                jp DISPATCH
.spawn:         ld a,$$A_0FA57
                ld hl,A_0FA57
                jp FARJP
.translated:    ld a,$$K_0FA3A
                ld hl,K_0FA3A
                jp FARJP

; $FA3A над IX → [bp] (BP < #3F00): A = 0 — возврат ROM; A = 1 — порождение (продолжение переводом с $FA57). Портит
; всё, кроме IX.
CounterCore:    ld l,(ix+#26)
                ld h,(ix+#27)
                inc hl
                ld (ix+#26),l
                ld (ix+#27),h
                ld (V_AX),hl                    ; AX = [bp+#26]
                ld e,(ix+#2A)
                ld d,(ix+#2B)
                or a
                sbc hl,de
                jr z,.period                    ; AX = [bp+#2A]
                add hl,de
                ld e,(ix+#2C)
                ld d,(ix+#2D)
                or a
                sbc hl,de
                jr nc,.reset                    ; AX ≥ [bp+#2C]
                xor a
                ret
.reset:         xor a
                ld (ix+#26),a
                ld (ix+#27),a
.period:        ld a,(ix+#28)
                or (ix+#29)
                ret z                           ; A = 0: [bp+#28] = 0
                ld a,1
                ret

; --- тайлы рельефа под объектом ---------------------------------------------------------------------------------
; ROM $226C (IP $1E6C, 46 мест возврата): слово VRAM слоя A под точкой объекта BP. S = [#2EC1] (DS = #4000 на входе —
; сегменты сборки), CX = S & 7; BX = ((S >> 1) & #FC) + #1020; AX = (([bp+4] + CX − #140) >> 1) & #FFFC; BX = (BX + AX)
; & #10FF; AX = #17F − [bp+8] (заём — 0), AX = (AX & #FFF8) << 5; BX = (BX + AX) & #3FFF; PUSH DS, DS = AX = #D000,
; AX = [bx] & #FFF, POP DS, RET. Выход ROM: AX, BX, CX — живут у вызывающих; DS прежний; флаги после RET не живут ни в
; одном из мест возврата (flags.liveness). Остатков PUSH ниже SP у ядра нет (сверка их не сравнивает).
; ROM $22B5 (IP $1EB5, 48 мест возврата): CALL $226C; PUSH BX, PUSH AX; то же для слоя B: S = [#2EC9], CX = S & 7,
; X-часть как у слоя A; T = [#2ECD], CX = T & 7, BX += (T << 5) & #3F00; AX = #17F + CX − [bp+8] (заём по вычитанию —
; 0), (AX & #FFF8) << 5, BX = (BX + AX) & #3FFF; DS = #D800: CX = [bx] & #FFF, DI = BX; POP DS, POP AX, POP BX, RET.
; Выход: AX, BX — слоя A, CX, DI — слоя B. Условия ядер: BP < #3F00 (поля объекта — в окне W1) и BX ≠ #3FFF (слово VRAM
; не на границе страниц V30); иначе — перевод с входа (регистры, записанные ядром до отказа, процедура вычисляет заново).
KERNEL_TERRAIN_A:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                call TerrainA
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_0226C
                ld hl,K_0226C
                jp FARJP

KERNEL_TERRAIN_AB:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                call TerrainA
                jr c,.translated
                call TerrainB
                jr c,.translated
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_022B5
                ld hl,K_022B5
                jp FARJP

; X-часть (макрос, развёрнут в TerrainA и TerrainB): DE = слово прокрутки S, C = S & 7, IX → [bp] → HL = (((S >> 1) &
; #FC) + #1020 + ((([bp+4] + (S & 7) − #140) >> 1) & #FFFC)) & #10FF (BX: MOV BX,AX; ADD BX,AX′; AND BX,#10FF — сложения
; по модулю 2^16). (S >> 1) & #FC — биты 8…1 S двумя RRA (старший байт маски — 0). Портит AF, BC, DE.
                MACRO TERRAIN_X
                ld b,0
                ld l,(ix+4)
                ld h,(ix+5)                     ; AX = [bp+4]
                add hl,bc                       ; ADD AX,CX
                ld bc,-#140
                add hl,bc                       ; SUB AX,#140
                srl h
                rr l                            ; SHR AX,1
                ld a,l
                and #FC
                ld l,a                          ; AND AX,#FFFC
                ld a,d
                rra                             ; CF = бит 8 S
                ld a,e
                rra                             ; биты 8…1 S
                and #FC                         ; (S >> 1) & #FC
                add a,#20
                ld e,a
                ld a,#10
                adc a,0
                ld d,a                          ; DE = ((S >> 1) & #FC) + #1020
                add hl,de                       ; ADD BX,AX
                ld a,h
                and #10
                ld h,a                          ; AND BX,#10FF
                ENDM

; Y-часть (макрос): HL = AX (после заёма, < #200), DE = BX → HL = (BX + ((AX & #FFF8) << 5)) & #3FFF. По маске #3FFF
; (AX & #FFF8) << 5 = ((AX >> 3) & #3F) << 8: младший байт BX не меняется, у старшего — сложение по модулю #40. Портит AF.
                MACRO TERRAIN_Y
                ld a,h
                rra                             ; CF = бит 8 AX
                ld a,l
                rra
                rra
                rra                             ; биты 3…8 AX — в младших шести
                and #3F
                add a,d
                and #3F
                ld h,a
                ld l,e                          ; BX = (BX + AX′) & #3FFF
                ENDM

; Слово VRAM (макрос): HL = BX (≤ #3FFF), страница V30 слоя (#34, #36; сегмент #D000/#D800 — смещение BX целиком в
; ней) → DE = слово & #FFF, окно W2 — эта страница (W2_PAGE). BX = #3FFF (слово на границе страниц) — RET с CF = 1.
; Портит AF, BC, HL.
                MACRO TERRAIN_WORD vpage
                ld a,h
                cp #3F
                jr nz,.inside
                ld a,l
                inc a
                scf
                ret z                           ; BX = #3FFF — перевод
.inside:        ld a,(W2_PAGE)
                cp vpage
                jr z,.mapped
                ld a,vpage
                ld (W2_PAGE),a
                ld a,vpage+V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
.mapped:        set 7,h                         ; окно W2 (#8000)
                ld e,(hl)
                inc hl
                ld a,(hl)
                and #0F
                ld d,a                          ; AND AX,#FFF
                ENDM

; Слой A ($226C): HL = BP (< #3F00) → V_CX, V_BX, V_AX; IX → [bp]. CF = 1 — BX = #3FFF. Портит всё.
TerrainA:       set 6,h
                push hl
                pop ix                          ; IX → [bp] (окно W1)
                ld de,(#4000+#2EC1)             ; S
                ld a,e
                and 7
                ld c,a
                ld (V_CX),a
                xor a
                ld (V_CX+1),a                   ; CX = S & 7
                TERRAIN_X                       ; HL = BX X-части
                ex de,hl                        ; DE = BX
                ld hl,#17F
                ld c,(ix+8)
                ld b,(ix+9)
                or a
                sbc hl,bc                       ; AX = #17F − [bp+8]
                jr nc,.y
                ld hl,0                         ; заём — XOR AX,AX
.y:             TERRAIN_Y                       ; HL = BX
                ld (V_BX),hl
                TERRAIN_WORD #34                ; VRAM слоя A — страница V30 #34 (#D0000)
                ld (V_AX),de                    ; AX = слово & #FFF
                or a                            ; CF = 0
                ret

; Слой B ($22B8…$231A): IX → [bp] → V_DI, V_CX (V_AX, V_BX — слоя A, их POP). CF = 1 — BX = #3FFF. Портит всё.
TerrainB:       ld de,(#4000+#2EC9)             ; S
                ld a,e
                and 7
                ld c,a                          ; CX = S & 7 (дальше не живёт)
                TERRAIN_X                       ; HL = BX X-части
                ; T = [#2ECD]: CX = T & 7; BX += (T << 5) & #3F00 = ((T >> 3) & #3F) << 8 — перенос в старший байт
                ; не выходит за #4F (BX X-части ≤ #10FF)
                ld a,(#4000+#2ECD+1)
                rra                             ; CF = бит 8 T
                ld a,(#4000+#2ECD)
                ld c,a
                rra
                rra
                rra
                and #3F                         ; (T >> 3) & #3F
                add a,h
                ld d,a
                ld e,l                          ; DE = BX
                ld a,c
                and 7
                ld c,a                          ; CX = T & 7
                ld hl,#17F
                ld b,0
                add hl,bc                       ; AX = #17F + CX
                ld c,(ix+8)
                ld b,(ix+9)
                or a
                sbc hl,bc                       ; − [bp+8]
                jr nc,.y
                ld hl,0
.y:             TERRAIN_Y                       ; HL = BX
                ld (V_DI),hl                    ; DI = BX
                TERRAIN_WORD #36                ; VRAM слоя B — страница V30 #36 (#D8000)
                ld (V_CX),de                    ; CX = слово & #FFF
                or a                            ; CF = 0
                ret

; --- прямоугольник объекта ---------------------------------------------------------------------------------------
; ROM $3CF4 (IP $38F4, 19 мест возврата): BX, CX, DX, SI = слова ES:[si], [si+2], [si+4], [si+6] (ES = #1000 на входе —
; сегменты сборки: страница V30 4 + SI >> 14); [bp+#18] = [bp+4] − BX, [bp+#1A] = [bp+4] + CX, [bp+#1C] = [bp+8] − DX,
; [bp+#1E] = AX = [bp+8] + SI. Выход: AX, BX, CX, DX, SI — как у ROM; флаги после RET не живут (flags.liveness).
; Чтения ES:[si] (страницы #04…#07) и поля объекта (рабочее ОЗУ) не пересекаются — порядок чтений и записей не важен.
; Условия: BP < #3F00 и 8 байт ES:[si] в одной странице V30; иначе — перевод (K_03CF4).
KERNEL_HITBOX:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix                          ; IX → [bp] (окно W1)
                ld hl,(V_SI)
                ld a,h
                and #3F
                cp #3F
                jr nz,.inside
                ld a,l
                cp #F9
                jp nc,.translated               ; ES:[si+7] — в следующей странице V30
.inside:        ld a,h
                rlca
                rlca
                and 3
                add a,4                         ; страница V30: (#10000 + SI) >> 14
                ld c,a
                ld a,(W2_PAGE)
                cp c
                jr z,.mapped
                ld a,c
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
.mapped:        ld a,h
                or #C0
                xor #40
                ld h,a                          ; HL = #8000 + (SI & #3FFF) — окно W2
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (V_BX),de                    ; BX = ES:[si]
                ld c,(ix+4)
                ld b,(ix+5)                     ; BC = [bp+4]
                push hl
                ld h,b
                ld l,c
                or a
                sbc hl,de
                ld (ix+#18),l
                ld (ix+#19),h                   ; [bp+#18] = [bp+4] − BX
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (V_CX),de                    ; CX = ES:[si+2]
                push hl
                ld h,b
                ld l,c
                add hl,de
                ld (ix+#1A),l
                ld (ix+#1B),h                   ; [bp+#1A] = [bp+4] + CX
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (V_DX),de                    ; DX = ES:[si+4]
                ld c,(ix+8)
                ld b,(ix+9)                     ; BC = [bp+8]
                push hl
                ld h,b
                ld l,c
                or a
                sbc hl,de
                ld (ix+#1C),l
                ld (ix+#1D),h                   ; [bp+#1C] = [bp+8] − DX
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_SI),de                    ; SI = ES:[si+6]
                ld h,b
                ld l,c
                add hl,de
                ld (ix+#1E),l
                ld (ix+#1F),h                   ; [bp+#1E] = [bp+8] + SI
                ld (V_AX),hl                    ; AX = он же
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_03CF4
                ld hl,K_03CF4
                jp FARJP

; ROM $3D24 (IP $3924, 29 мест возврата): [bp+#18] = #80, [bp+#1A] = #82, [bp+#1C] = #80, [bp+#1E] = #82 (слова, SS =
; #4000). Регистры не меняет; флаги после RET не живут. Условие: BP < #3F00; иначе — перевод (K_03D24).
KERNEL_HITBOX_FIXED:
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jr nc,.translated
                ld de,#4000+#18
                add hl,de                       ; HL → [bp+#18] (окно W1)
                ld de,#80                       ; E = #80, D = 0
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (hl),#82
                inc hl
                ld (hl),d
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (hl),#82
                inc hl
                ld (hl),d
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_03D24
                ld hl,K_03D24
                jp FARJP

KC_X            DW 0
KC_Y            DW 0
KC_HB0          DW 0                            ; слова хитбокса ES:BX
KC_HB2          DW 0
KC_HB4          DW 0
KC_HB6          DW 0
KC_BX           DW #FFFF                        ; BX хитбокса ROM в KC_HB (ES = #1000); #FFFF — нет
KC_BXNEW        DW #FFFF                        ; BX копируемого хитбокса (до удачного копирования)
