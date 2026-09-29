; VDAC2+: вторая нативная страница (NATIVE_PAGE1, окно W3 #C000) — модуль n2. Собирает vdac2p_native2_gen.py: этот
; файл и копии нужных подпрограмм первой нативной страницы (vdac2p_native.asm) — в первой странице места нет. Код
; здесь не зовёт CollideSetup и сканы (они отображают в W3 первую страницу; генератор такое останавливает). Входы NATIVE
; — codegen.NATIVE с префиксом модуля (n2.N_…), диспетчеризация — в эту страницу.

; --- ракеты игрока (VDAC2+ 2026-09-26, скорость: перевод ракет — 0,4…0,8 % тактов на каждом этапе, у каждой) --------
; Две ракеты: нижняя ($33A1, наведение $3512, взрыв $35F1 → $360A) и верхняя ($366D, $37DC, $38BB → $38D4) — один
; код с разными постоянными (у верхней — вверх: Y − 3, падение и снос с обратным знаком). Слово [bp+14] — цель
; наведения (≥ #18 шагов разгона [bp+13] и цель есть — наведение в том же кадре), [bp+17] ≠ 0 — жива, [bp+16] —
; таймер падения, [bp+2] — направление к стене, [bp+12] — курс (16 направлений), [bp+13] — разгон. Регистры V30 —
; как у ROM; флаги у выходов не живут. Концы (взрыв $35F1/$38BB, удаление $34FC/$37C6/$35E0/$38AA) и стирание
; разрушаемого тайла ($4FB9) — переводом с места. Таблицы ES:#1A08…#1B7A — ROM (ES = #1000 — NObjCheck), не на
; границе страницы V30: NWord1000, NSpriteAdd и NHitbox здесь не отказывают.

; Поворот курса [bp+12] к направлению B (BL ROM, $3441…$346C): равны — без изменений; BL > AL — AL + 8 (перенос или BL <
; AL + 8 — INC, иначе DEC); BL < AL — AL − 8 (заём или BL ≥ AL − 8 — DEC, иначе INC). V_AX (младший) — AL ROM после
; ветви. Портит AF, C.
MisSteer:       ld a,(ix+#12)
                ld c,a                          ; C = AL
                ld a,b
                cp c                            ; CMP BL,AL
                jr z,.same
                jr nc,.up                       ; JAE — BL > AL
                ld a,c
                sub 8                           ; SUB AL,8
                jr c,.dec                       ; JB
                ld c,a
                ld a,b
                cp c                            ; CMP BL,AL
                ld a,c
                jr nc,.dec                      ; JAE
                inc (ix+#12)
                jr .done
.up:            ld a,c
                add a,8                         ; ADD AL,8
                jr c,.inc                       ; JB
                ld c,a
                ld a,b
                cp c
                ld a,c
                jr nc,.dec                      ; JAE
.inc:           inc (ix+#12)
                jr .done
.dec:           dec (ix+#12)
.done:          ld (V_AX),a                     ; AL
                ret
.same:          ld a,c
                ld (V_AX),a
                ret

; Второй спрайт ракеты ($3472…$34AB, $3564…$359D): точка объекта на время — + ES:[#1A58 + [bp+12]·4], + ES:[#1A5A + …]
; (PUSH/POP ROM; курс — до маски & #F), описание #1B50 + ([2EB6] & 7)·6 (AX = ([2EB6] & 7)·4), спрайт $1BCC. Портит
; всё, кроме IX.
MisSprite2:     ld l,(ix+8)
                ld h,(ix+9)
                push hl                         ; PUSH [bp+8]
                ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH [bp+4]
                ld l,(ix+#12)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = [bp+12]·4
                push hl
                ld de,#1A58
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#1A58]
                ld l,(ix+4)
                ld h,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                pop hl
                ld de,#1A5A
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#1A5A]
                ld l,(ix+8)
                ld h,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD [bp+8],AX
                ld a,(#4000+#2EB6)
                and 7
                add a,a
                ld c,a                          ; ·2
                add a,a
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = ·4
                add a,c
                ld l,a                          ; ·6
                ld de,#1B50
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP [bp+4]
                pop hl
                ld (ix+8),l
                ld (ix+9),h                     ; POP [bp+8]
                ret

; Спрайт корпуса ($34C8…$34DD): [bp+12] &= #F; описание #1AF0 + [bp+12]·6 (AX = [bp+12]·4), спрайт $1BCC. Портит всё,
; кроме IX.
MisBody:        ld a,(ix+#12)
                and #0F
                ld (ix+#12),a
                add a,a
                ld c,a                          ; ·2
                add a,a
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = ·4
                add a,c
                ld l,a                          ; ·6
                ld de,#1AF0
                add hl,de
                ld (V_BX),hl
                jp NSpriteAdd                   ; $1BCC

; ROM $03A2A (IP $362A): [bp+13] < #38 — [bp+A], [bp+C], [bp+E], [bp+10] = #1F0, #1F2, #1F0, #1F2; иначе [bp+A] = X −
; ES:[si], [bp+C] = X + ES:[si+2], [bp+E] = Y − ES:[si+4], [bp+10] = AX = Y + ES:[si+6]. HL — SI (V_SI). Портит всё,
; кроме IX.
Mis362A:        ld (V_SI),hl
                ld a,(ix+#13)
                cp #38
                jr c,.fixed
                push hl
                call NWord1000                  ; ES:[si]
                ld l,(ix+4)
                ld h,(ix+5)
                or a
                sbc hl,de
                ld (V_AX),hl
                ld (ix+#0A),l
                ld (ix+#0B),h
                pop hl
                inc hl
                inc hl
                push hl
                call NWord1000                  ; ES:[si+2]
                ld l,(ix+4)
                ld h,(ix+5)
                add hl,de
                ld (ix+#0C),l
                ld (ix+#0D),h
                pop hl
                inc hl
                inc hl
                push hl
                call NWord1000                  ; ES:[si+4]
                ld l,(ix+8)
                ld h,(ix+9)
                or a
                sbc hl,de
                ld (ix+#0E),l
                ld (ix+#0F),h
                pop hl
                inc hl
                inc hl
                call NWord1000                  ; ES:[si+6]
                ld l,(ix+8)
                ld h,(ix+9)
                add hl,de
                ld (V_AX),hl
                ld (ix+#10),l
                ld (ix+#11),h
                ret
.fixed:         ld (ix+#0A),#F0
                ld (ix+#0B),1
                ld (ix+#0C),#F2
                ld (ix+#0D),1
                ld (ix+#0E),#F0
                ld (ix+#0F),1
                ld (ix+#10),#F2
                ld (ix+#11),1
                ret

; Проверка рельефа в точке ракеты после $1EB5 (V_AX — тайл A, V_CX — тайл B): CF = 1 — тайл #9F6 (стирание $4FB9 —
; переводом), иначе Z80 A = 0 — летим, A = 1 — стена (AX < #DFC или CX < #7D0 — взрыв). Портит AF, DE, HL.
MisWall:        ld hl,(V_AX)
                ld a,h
                cp #09
                jr nz,.tile
                ld a,l
                cp #F6
                scf
                ret z                           ; #9F6
.tile:          ld de,-#DFC
                add hl,de
                jr nc,.wall
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jr nc,.wall
                xor a                           ; CF = 0, A = 0
                ret
.wall:          ld a,1
                or a                            ; CF = 0
                ret

; ROM $037A1 (IP $33A1) — нижняя ракета игрока: жива ([bp+17]) — разгон или полёт вниз, у стены —
; направление [bp+2], рельеф в точке, падение, курс, спрайты, прямоугольники $362A/$38F4; наведение — с
; $3512 в том же кадре.
N_33A1:         call NObjCheck
                jp c,.translated
.main:          ld a,(ix+#17)
                or a
                jp z,.explode                   ; $35F1
                ld a,(ix+#13)
                cp #18
                jr c,.fly
                ld a,(ix+#14)
                or (ix+#15)
                jr z,.fly
                ld (ix+0),#12
                ld (ix+1),#35                   ; [bp] = #3512 — наведение, в том же кадре
                jp N_3512.body
.fly:           ld a,(ix+2)
                cp 4
                jr z,.climb
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,3
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD WORD [bp+8],3
                jr .probe
.climb:         ld a,(ix+#13)
                inc a
                ld (ix+#13),a                   ; ADD BYTE [bp+13],1
                cp #24
                jr c,.probe
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = AX·8 (SHL AX,3; MOV BX,AX)
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; AX = [bp+13]·24
                ld (V_AX),hl
                call NAddX                      ; $0672
.probe:         ld a,4
                ld (V_BX),a                     ; MOV BL,4
                ld a,(ix+#13)
                cp #14
                jr c,.dir
                ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH [bp+4]
                ld de,#20
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],#20
                call NTerrainAB                 ; $1EB5
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP [bp+4]
                jp c,.probeFail
                ld a,4
                ld (V_BX),a                     ; MOV BL,4
                call MisWall
                or a
                jr z,.dir                       ; стены впереди нет — BL = 4
                ld a,0
                ld (V_BX),a                     ; XOR BL,BL
.dir:           ld a,(V_BX)
                ld (ix+2),a                     ; MOV [bp+2],BL
                call NTerrainAB                 ; $1EB5 в точке ракеты
                jp c,.terrainFail
                call MisWall
                jp c,.erase                     ; тайл #9F6
                or a
                jp nz,.explode
                ld a,(ix+#16)
                or a
                jr z,.steer
                dec a
                ld (ix+#16),a                   ; DEC BYTE [bp+16]
                cp #10
                jr nc,.steer
                ld hl,#80
                call NAddY                      ; ADD WORD [bp+7],#80, перенос — INC [bp+9] (Y — 24 бита, без AX)
.steer:         ld a,(ix+2)
                ld (V_BX),a                     ; MOV BL,[bp+2]
                ld b,a
                call MisSteer
                ld a,(ix+#13)
                cp #22
                jr c,.drift
                call MisSprite2
                ld a,(ix+#13)
                cp #24
                jr nc,.body
.drift:         ld hl,#90
                call NAddY                      ; ADD WORD [bp+7],#90, перенос — INC [bp+9]
                ld hl,#C0
                call NAddX                      ; ADD WORD [bp+3],#C0 (X — 24 бита)
.body:          call MisBody
                call NOnField                   ; $1D6B
                jp c,.end
                ld hl,#1A08
                ld a,(ix+#20)
                cp #6D
                jr nz,.box18
                ld a,(ix+#21)
                cp #36
                jr z,.box                       ; [bp+20] = #366D — #1A08
.box18:         ld hl,#1A18
.box:           call Mis362A                    ; $362A
                ld hl,#1A20
                call NHitbox                    ; $38F4
                jp NRet
.explode:       NTAIL A_039F1                   ; $35F1: взрыв
.end:           NTAIL A_038FC                   ; $34FC: удаление
.erase:         NTAIL A_03814                   ; CALL $4FB9
.probeFail:     NTAIL A_037EA                   ; PUSH [bp+4] — проба переводом
.terrainFail:   NTAIL A_0380C                   ; CALL $1EB5
.translated:    ld a,$$K_037A1
                ld hl,K_037A1
                jp FARJP

; ROM $03912 (IP $3512) — наведение нижней ракеты: цели нет ([bp+14] = 0) — код $33A1, затем [bp+17] = 0 — взрыв; сектор к цели $1D89 (NAimCore), X, Y +=
; ES:[#1A98/#1A9A + сектор], курс к сектору / 4, спрайты, прямоугольники $1A08/$1A20, рельеф (стена — взрыв),
; вне поля — $35E0.
N_3512:         call NObjCheck
                jp c,.translated
.body:
                ld l,(ix+#14)
                ld h,(ix+#15)
                ld (V_BX),hl                    ; MOV BX,[bp+14]
                ld a,h
                or l
                jp z,N_33A1.main                ; цели нет — код $33A1 (обработчик остаётся $3512)
                ld a,(ix+#17)
                or a
                jp z,N_33A1.explode             ; $35F1
                ld hl,(V_BX)
                ld a,h
                cp #3F
                jp nc,.aimFail                  ; цель у края рабочего ОЗУ — $1D89 переводом
                set 6,h                         ; HL → цель
                push ix
                pop de                          ; DE → объект
                call NAimCore                   ; $1D89: V_BX — сектор (·4)
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld hl,(V_BX)
                push hl
                ld de,#1A98
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#1A98]
                ex de,hl
                call NAddX                      ; $0672
                pop hl
                push hl
                ld de,#1A9A
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddY                      ; $0689
                pop hl
                srl h
                rr l
                srl h
                rr l
                ld (V_BX),hl                    ; SHR BX,1 ×2
                ld b,l
                call MisSteer
                call MisSprite2
                call MisBody
                ld hl,#1A08
                call Mis362A                    ; $362A
                ld hl,#1A20
                call NHitbox                    ; $38F4
                call NTerrainAB                 ; $1EB5
                jp c,.terrainFail
                call MisWall
                jp c,.erase
                or a
                jp nz,N_33A1.explode
                call NOnField
                jp c,.end
                jp NRet
.end:           NTAIL A_039E0                   ; $35E0: удаление
.erase:         NTAIL A_039CC                   ; CALL $4FB9
.terrainFail:   NTAIL A_039C4                   ; CALL $1EB5
.aimFail:       NTAIL A_03925                   ; CALL $1D89
.translated:    ld a,$$K_03912
                ld hl,K_03912
                jp FARJP

; ROM $03A0A (IP $360A) — взрыв нижней ракеты: X += AX = [2ED0]; спрайт $1BCC по описанию #1A28 +
; ([bp+10] & #1C)·1,5 (AX — половина); DEC [bp+10] — ноль: $35E0 (переводом), иначе RET.
N_360A:         call NObjCheck
                jr c,.translated
                call NScrollX                   ; ADD [bp+4],AX
                ld a,(ix+#10)
                and #1C
                ld c,a                          ; BX = [bp+10] & #1C
                srl a
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = BX >> 1
                add a,c
                ld l,a
                ld de,#1A28
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC
                ld l,(ix+#10)
                ld h,(ix+#11)
                dec hl
                ld (ix+#10),l
                ld (ix+#11),h                   ; DEC WORD [bp+10]
                ld a,h
                or l
                jp nz,NRet
                NTAIL A_039E0                   ; $35E0
.translated:    ld a,$$K_03A0A
                ld hl,K_03A0A
                jp FARJP

; ROM $03A6D (IP $366D) — верхняя ракета игрока: жива ([bp+17]) — разгон или полёт вверх, у стены —
; направление [bp+2], рельеф в точке, падение, курс, спрайты, прямоугольники $38F4/$362A; наведение — с
; $37DC в том же кадре.
N_366D:         call NObjCheck
                jp c,.translated
.main:          ld a,(ix+#17)
                or a
                jp z,.explode                   ; $38BB
                ld a,(ix+#13)
                cp #18
                jr c,.fly
                ld a,(ix+#14)
                or (ix+#15)
                jr z,.fly
                ld (ix+0),#DC
                ld (ix+1),#37                   ; [bp] = #37DC — наведение, в том же кадре
                jp N_37DC.body
.fly:           ld a,(ix+2)
                cp 4
                jr z,.climb
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,-3
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; SUB WORD [bp+8],3
                jr .probe
.climb:         ld a,(ix+#13)
                inc a
                ld (ix+#13),a                   ; ADD BYTE [bp+13],1
                cp #24
                jr c,.probe
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = AX·8 (SHL AX,3; MOV BX,AX)
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; AX = [bp+13]·24
                ld (V_AX),hl
                call NAddX                      ; $0672
.probe:         ld a,4
                ld (V_BX),a                     ; MOV BL,4
                ld a,(ix+#13)
                cp #14
                jr c,.dir
                ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH [bp+4]
                ld de,#20
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],#20
                call NTerrainAB                 ; $1EB5
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP [bp+4]
                jp c,.probeFail
                ld a,4
                ld (V_BX),a                     ; MOV BL,4
                call MisWall
                or a
                jr z,.dir                       ; стены впереди нет — BL = 4
                ld a,8
                ld (V_BX),a                     ; MOV BL,8
.dir:           ld a,(V_BX)
                ld (ix+2),a                     ; MOV [bp+2],BL
                call NTerrainAB                 ; $1EB5 в точке ракеты
                jp c,.terrainFail
                call MisWall
                jp c,.erase                     ; тайл #9F6
                or a
                jp nz,.explode
                ld a,(ix+#16)
                or a
                jr z,.steer
                dec a
                ld (ix+#16),a                   ; DEC BYTE [bp+16]
                cp #10
                jr nc,.steer
                ld hl,#FF80
                call NAddY                      ; SUB WORD [bp+7],#80, заём — DEC [bp+9] (Y — 24 бита, без AX)
.steer:         ld a,(ix+2)
                ld (V_BX),a                     ; MOV BL,[bp+2]
                ld b,a
                call MisSteer
                ld a,(ix+#13)
                cp #22
                jr c,.drift
                call MisSprite2
                ld a,(ix+#13)
                cp #24
                jr nc,.body
.drift:         ld hl,#FF70
                call NAddY                      ; SUB WORD [bp+7],#90, заём — DEC [bp+9]
                ld hl,#C0
                call NAddX                      ; ADD WORD [bp+3],#C0 (X — 24 бита)
.body:          call MisBody
                call NOnField                   ; $1D6B
                jp c,.end
                ld hl,#1A20
                call NHitbox                    ; $38F4
                ld hl,#1A10
                ld a,(#4000+#A0)
                cp #A1
                jr nz,.box18
                ld a,(#4000+#A1)
                cp #33
                jr z,.box                       ; [#A0] = #33A1 — #1A10
.box18:         ld hl,#1A18
.box:           call Mis362A                    ; $362A
                jp NRet
.explode:       NTAIL A_03CBB                   ; $38BB: взрыв
.end:           NTAIL A_03BC6                   ; $37C6: удаление
.erase:         NTAIL A_03AE0                   ; CALL $4FB9
.probeFail:     NTAIL A_03AB6                   ; PUSH [bp+4] — проба переводом
.terrainFail:   NTAIL A_03AD8                   ; CALL $1EB5
.translated:    ld a,$$K_03A6D
                ld hl,K_03A6D
                jp FARJP

; ROM $03BDC (IP $37DC) — наведение верхней ракеты: [bp+17] = 0 — взрыв, затем цели нет — код $366D; сектор к цели $1D89 (NAimCore), X, Y +=
; ES:[#1A98/#1A9A + сектор], курс к сектору / 4, спрайты, прямоугольники $1A10/$1A20, рельеф (стена — взрыв),
; вне поля — $38AA.
N_37DC:         call NObjCheck
                jp c,.translated
.body:
                ld a,(ix+#17)
                or a
                jp z,N_366D.explode             ; $38BB
                ld l,(ix+#14)
                ld h,(ix+#15)
                ld (V_BX),hl                    ; MOV BX,[bp+14]
                ld a,h
                or l
                jp z,N_366D.main                ; цели нет — код $366D (обработчик остаётся $37DC)
                ld hl,(V_BX)
                ld a,h
                cp #3F
                jp nc,.aimFail                  ; цель у края рабочего ОЗУ — $1D89 переводом
                set 6,h                         ; HL → цель
                push ix
                pop de                          ; DE → объект
                call NAimCore                   ; $1D89: V_BX — сектор (·4)
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld hl,(V_BX)
                push hl
                ld de,#1A98
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#1A98]
                ex de,hl
                call NAddX                      ; $0672
                pop hl
                push hl
                ld de,#1A9A
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddY                      ; $0689
                pop hl
                srl h
                rr l
                srl h
                rr l
                ld (V_BX),hl                    ; SHR BX,1 ×2
                ld b,l
                call MisSteer
                call MisSprite2
                call MisBody
                ld hl,#1A10
                call Mis362A                    ; $362A
                ld hl,#1A20
                call NHitbox                    ; $38F4
                call NTerrainAB                 ; $1EB5
                jp c,.terrainFail
                call MisWall
                jp c,.erase
                or a
                jp nz,N_366D.explode
                call NOnField
                jp c,.end
                jp NRet
.end:           NTAIL A_03CAA                   ; $38AA: удаление
.erase:         NTAIL A_03C96                   ; CALL $4FB9
.terrainFail:   NTAIL A_03C8E                   ; CALL $1EB5
.aimFail:       NTAIL A_03BEF                   ; CALL $1D89
.translated:    ld a,$$K_03BDC
                ld hl,K_03BDC
                jp FARJP

; ROM $03CD4 (IP $38D4) — взрыв верхней ракеты: X += AX = [2ED0]; спрайт $1BCC по описанию #1A28 +
; ([bp+10] & #1C)·1,5 (AX — половина); DEC [bp+10] — ноль: $38AA (переводом), иначе RET.
N_38D4:         call NObjCheck
                jr c,.translated
                call NScrollX                   ; ADD [bp+4],AX
                ld a,(ix+#10)
                and #1C
                ld c,a                          ; BX = [bp+10] & #1C
                srl a
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = BX >> 1
                add a,c
                ld l,a
                ld de,#1A28
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC
                ld l,(ix+#10)
                ld h,(ix+#11)
                dec hl
                ld (ix+#10),l
                ld (ix+#11),h                   ; DEC WORD [bp+10]
                ld a,h
                or l
                jp nz,NRet
                NTAIL A_03CAA                   ; $38AA
.translated:    ld a,$$K_03CD4
                ld hl,K_03CD4
                jp FARJP

; --- мелкие обработчики цикла слотов (по вызову на шаг на всех этапах; в переводе — по 0,2 % тактов) ----------------

; ROM $052D8 (IP $4ED8) — ожидание пуска оружия: [bp+4] = #40, [bp+17] = 0; [#38] = 0 — RET, иначе пуск (переводом
; с $4EE9). Флаги у выходов не живут. Условия (иначе перевод с входа): NObjCheck.
N_4ED8:         call NObjCheck
                jr c,.translated
                ld (ix+4),#40
                ld (ix+5),0                     ; MOV WORD [bp+4],#40
                ld (ix+#17),0
                ld a,(#4000+#38)
                or a
                jp z,NRet
                NTAIL A_052E9                   ; $4EE9: пуск
.translated:    ld a,$$K_052D8
                ld hl,K_052D8
                jp FARJP

; ROM $01FA7 (IP $1BA7) — сценарий уровня (объект списка, вызов на каждом шаге игры): SI = #2F4B, BX = [2EFE] (указатель
; сценария), AX = [2F4B] (путь прокрутки); AX < ES:[BX] — RET (порождать рано); иначе порождение ($1BB5: [2EFE] += 4 и
; вызов по таблице ES:[BX − #46D3]) — переводом с места, SI, BX, AX уже как у ROM. Флаги у выходов не живут (у $1BB5 их
; ставит ADD). Условия (иначе перевод с входа): DS = #4000, ES = #1000 (BP не читается), слово ES:[BX] — не на границе
; страниц V30.
N_1BA7:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jp nz,.translated
                ld hl,(#4000+#2EFE)
                ld de,(N_1BA7BX)
                or a
                sbc hl,de
                jr nz,.read
                ld a,d
                and e
                inc a
                jr z,.read                      ; ключ #FFFF — кэш пуст
                ld de,(N_1BA7W)                 ; слово ES:[BX] того же BX (ROM не меняется)
                jr .have
.read:          add hl,de                       ; HL = BX
                push hl
                call NWord1000                  ; DE = ES:[BX]
                pop hl
                jp c,.translated
                ld (N_1BA7BX),hl
                ld (N_1BA7W),de
.have:          ld hl,#2F4B
                ld (V_SI),hl                    ; MOV SI,#2F4B
                ld hl,(#4000+#2EFE)
                ld (V_BX),hl                    ; MOV BX,[2EFE]
                ld hl,(#4000+#2F4B)
                ld (V_AX),hl                    ; MOV AX,[SI]
                or a
                sbc hl,de                       ; CMP AX,ES:[BX]
                jp c,NRet                       ; JB — RET
                NTAIL A_01FB5                   ; $1BB5: порождение
.translated:    ld a,$$K_01FA7
                ld hl,K_01FA7
                jp FARJP
N_1BA7BX        DW #FFFF                        ; $1BA7: BX последнего прочитанного слова сценария (#FFFF — нет)
N_1BA7W         DW 0                            ; и слово ES:[BX]

; ROM $03470 (IP $3070) — след R-9 для битов: в нечётном кадре — RET; иначе [bp+2] = ([bp+2] + 2) & #1F, [#1D40 +
; [bp+2]] = BX = [#28] (Y), [bp+4] = ([bp+2] + 2) & #1F; [bp+6] = ([bp+6] + 2) & #1F, [#1D60 + [bp+6]] = BX = [#24] (X),
; [bp+8] = AX = ([bp+6] + 2) & #1F (SI — [bp+6]). Условия (иначе перевод с входа): NObjCheck.
N_3070:         call NObjCheck
                jr c,.translated
                ld a,(#4000+#2EB6)
                rra
                jp c,NRet                       ; TEST [2EB6],1 ≠ 0 — RET
                ld a,(ix+2)
                add a,2
                and #1F
                ld (ix+2),a
                ld (ix+3),0                     ; [bp+2] = AX = ([bp+2] + 2) & #1F
                ld l,a
                ld h,0
                ld de,#4000+#1D40
                add hl,de
                ld de,(#4000+#28)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+#1D40] = BX = [#28]
                add a,2
                and #1F
                ld (ix+4),a
                ld (ix+5),0                     ; [bp+4] = AX
                ld a,(ix+6)
                add a,2
                and #1F
                ld (ix+6),a
                ld (ix+7),0                     ; [bp+6] = AX
                ld l,a
                ld h,0
                ld (V_SI),hl                    ; SI = AX
                ld de,#4000+#1D60
                add hl,de
                ld de,(#4000+#24)
                ld (V_BX),de                    ; BX = [#24]
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+#1D60] = BX
                add a,2
                and #1F
                ld (ix+8),a
                ld (ix+9),0                     ; [bp+8] = AX
                ld l,a
                ld h,0
                ld (V_AX),hl
                jp NRet
.translated:    ld a,$$K_03470
                ld hl,K_03470
                jp FARJP

; ROM $032A6 (IP $2EA6) — объект R-9 у запуска ($3924: прямоугольник #80…#82; [bp+4] = #120; спрайт $1BE9 по описанию
; #26FE в запись #3D8); [#33] ≥ 2 — дальше переводом ($2EBF), иначе RET. Условия (иначе перевод с входа): NObjCheck.
N_2EA6:         call NObjCheck
                jr c,.translated
                ld (ix+#18),#80
                ld (ix+#19),0
                ld (ix+#1A),#82
                ld (ix+#1B),0
                ld (ix+#1C),#80
                ld (ix+#1D),0
                ld (ix+#1E),#82
                ld (ix+#1F),0                   ; $3924
                ld (ix+4),#20
                ld (ix+5),1                     ; MOV WORD [bp+4],#120
                ld hl,#26FE
                ld (V_BX),hl
                ld hl,#3D8
                ld (V_SI),hl
                call NSpritePut                 ; $1BE9
                jr c,.spriteFail
                ld a,(#4000+#33)
                cp 2
                jp c,NRet
                NTAIL A_032BF                   ; $2EBF
.spriteFail:    NTAIL A_032B4                   ; CALL $1BE9
.translated:    ld a,$$K_032A6
                ld hl,K_032A6
                jp FARJP

; --- перенесено из первой нативной страницы (2026-09-26): входы без столкновений — место первой нужно
; обработчикам со сканами (CollideSetup отображает только её) -----------------------------------------------

; ROM $02B36 (IP $2736, 12 мест вызова): разрушаемые тайлы у точки объекта. [bp+4] < #140 — возврат. Иначе точка
; (X − 4, Y + 4) → слово VRAM слоя A ($1E6C: AX, BX, CX), и у тайлов BX, BX+4 (только младший байт), BX+#100 (& #3FFF)
; и BX+#100−4 (младший байт) код & #FFF = #9F6 заменяется пустым: слово #FA0, атрибут 0, байт [#2F30] + 1. X и Y
; объекта возвращаются (PUSH/POP ROM), ES — прежний. Выход: AX — код четвёртого тайла, BX — его смещение, CX = S & 7.
; Флаги после RET не живут. BX из $1E6C кратен 4, поэтому слова тайлов не пересекают границу страницы.
; Условия: DS = #4000 ([#2F30] через DS), BP < #3F00; иначе — перевод с входа.
N_2736:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix                          ; IX → объект
                call N2736Core
                jp nc,NRet
.translated:    ld a,$$K_02B36
                ld hl,K_02B36
                jp FARJP

; ROM $02B02 (IP $2702, 26 мест вызова): $2736 в четырёх точках вокруг объекта — (X+8, Y+8), (X−8, Y+8), (X−8, Y−8),
; (X+8, Y−8); X и Y — прежние (PUSH/POP ROM). [bp+4] < #140 — возврат сразу. Регистры — от последнего $2736, флаги
; после RET не живут. Условия: DS = #4000, BP < #3F00. Отказ тела (слово VRAM на границе страниц — не бывает: BX
; кратен 4) — перевод с входа: стирание тайлов повторно не срабатывает, поэтому повтор с начала даёт то же.
N_2702:        ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix                          ; IX → объект
                call N2702Core
                jp nc,NRet
.translated:    ld a,$$K_02B02
                ld hl,K_02B02
                jp FARJP

; ROM $02EB4 (IP $2AB4, вызов из обработчика Force $24CE): Force у рельефа. X сохраняется (DX), затем X − #10 и
; девять шагов по 8 вправо: $1EB5 (AX, BX — слой A, CX, DI — слой B). Тайл A < #DFC или тайл A над/под (BX ± #100)
; < #DFC — «стена слоя A» ($2B01); тайл B < #7D0 — «стена слоя B» ($2BEF); девять шагов без стены — $2B80.
; $2B01: X прежний, DI = 0, [bp+#10] = 0; вверх по слою A (BX − #100, пока BX ≥ #1000; иначе DI + 1) считаем тайлы
; < #DFC в [bp+#10], вниз (BX + #100, пока BX < #2E00; иначе DI + #10) — в [bp+#11]; DI = #11 — $2B80; DI ≠ 0 —
; скорость [bp+#C] = #FE00 при нечётном DI, иначе #200; DI = 0 — #200, если счёт вверх меньше счёта вниз, иначе
; #FE00; затем Y += скорость ($0689). $2BEF: то же по слою B (порог #7D0) без границ, ES = #D800 до POP ES.
; $2B80: скорость ≠ 0 — $2C58 (вниз, бит 15) или $2C76 (вверх): $1EB5 в точке Y ± 8, при тайле A ≥ #DFC и B ≥ #7D0
; скорость = 0; скорость = 0 — наводка по Y на R-9 ([si+#1D40], SI = [bp+#24]) при [bp+#B] ≠ 0 или
; 0 ≤ X + 4 − [bp+#32] < 8: разница ≥ 3 — #200, ≤ −3 — #FE00 и Y += скорость. В конце Y ограничен #98…#177.
; Регистры на выходе — как у ROM на каждом пути. Условия: DS = #4000 (чтение [si+#1D40]), BP < #3F00; чтения VRAM за
; страницей слоя (BX ± #100 вне #0000…#3FFF) — перевод с входа (до своих окончательных записей: X восстановлен,
; [bp+#10] ROM пишет заново).
N_2AB4:        ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix                          ; IX → объект
                call N2AB4Core
                jp nc,NRet
.translated:    ld a,$$K_02EB4
                ld hl,K_02EB4
                jp FARJP

; Слово тайла DE в VRAM слоя A по смещению HL (окно W2 — страница #34): пишется и помечается для вывода, только если
; отличается (одинаковое слово вывод перестраивать не заставляет). HL += 2. Портит AF.
NTileSet:       push hl
                set 7,h
                ld a,(hl)
                cp e
                jr nz,.write
                inc hl
                ld a,(hl)
                cp d
                jr z,.same
                dec hl
.write:         ld (hl),e
                inc hl
                ld (hl),d
                pop hl
                ld a,#34
                call VIDEO_MARK
                inc hl
                inc hl
                ret
.same:          pop hl
                inc hl
                inc hl
                ret

; ROM $053D2 (IP $4FD2, 4 места вызова): полоса заряда BEAM в VRAM слоя A (DS = #D000), смещения #60…#A3: 16 тайлов
; (код, атрибут #8F). AX ≤ 4 — начало по таблице ES:[#2740 + AX·2], 15 пустых (#6AE), конец #6BF. AX ≥ #7C — начало
; #6B2, 15 полных (#6BA), конец по таблице ES:[#274A + (AX − #7C)·2]. Иначе — начало #6B2, (AX − 4) >> 3 полных,
; частичный по таблице ES:[#272E + ((AX − 4) & 7)·2], пустые до 16-го, конец #6BF. Регистры на выходе — как у ROM;
; флаги после RET не живут. Слово пишется только при отличии (вывод по пометкам не перестраивает то же самое).
N_4FD2:         call N4FD2Core
                jp nc,NRet
                ld a,$$K_053D2
                ld hl,K_053D2
                jp FARJP

; Тело $4FD2 для нативных вызовов (AX — V_AX). CF = 1 — отказ чтения таблицы (до записей VRAM). Портит всё, кроме IX.
N4FD2Core:      ld hl,(V_AX)
                ld a,h
                or a
                jp nz,.full                     ; AX ≥ #100
                ld a,l
                cp 5
                jp c,.low                       ; AX ≤ 4
                cp #7C
                jp nc,.full
                sub 4                           ; частичная полоса
                ld c,a                          ; AX − 4
                and 7
                ld (N_PART),a                   ; CH = (AX − 4) & 7
                ld a,c
                rrca
                rrca
                rrca
                and #1F
                ld (V_DX),a
                xor a
                ld (V_DX+1),a                   ; DX = (AX − 4) >> 3
                ld a,(N_PART)
                add a,a
                ld l,a
                ld h,0
                ld de,#272E
                add hl,de
                call NReadES16                  ; таблица частичного тайла
                jp c,.translated
                ld (V_AX),de
                push de
                ld a,#34
                call NMap2
                ld hl,#60
                ld de,#6B2
                call NTileSet
                ld de,#8F
                call NTileSet                   ; HL = #64
                ld a,(V_DX)
                or a
                jr z,.partial
                ld b,a
.fullTiles:     ld de,#6BA
                call NTileSet
                ld de,#8F
                call NTileSet
                djnz .fullTiles
.partial:       ld (V_SI),hl                    ; SI — частичный тайл
                pop de
                call NTileSet
                ld de,#8F
                call NTileSet                   ; HL — за атрибутом частичного
                ld a,(V_DX)
                neg
                add a,#E                        ; CX = #E − DX
                jr z,.partialEnd
                ld b,a
.emptyTiles:    ld de,#6AE
                call NTileSet
                ld de,#8F
                call NTileSet
                djnz .emptyTiles
                jr .partialDone
.partialEnd:    dec hl
                dec hl                          ; BX — на атрибуте частичного (JE мимо ADD BX,2)
.partialDone:   ld (V_BX),hl
                call .tail
                jp .coreOk
.low:           add a,a
                ld l,a
                ld h,0
                ld de,#2740
                add hl,de                       ; BX = AX·2 + #2740
                call NReadES16
                jp c,.translated
                ld (V_AX),de
                push de
                ld a,#34
                call NMap2
                pop de
                ld hl,#60
                call NTileSet                   ; [#60] = таблица
                ld de,#8F
                call NTileSet
                ld b,15
.lowEmpty:      ld de,#6AE
                call NTileSet
                ld de,#8F
                call NTileSet
                djnz .lowEmpty
                ld (V_BX),hl                    ; BX = #A0
                call .tail
                jp .coreOk
.full:          ld de,-#7C
                add hl,de
                add hl,hl
                ld de,#274A
                add hl,de
                push hl                         ; BX = (AX − #7C)·2 + #274A
                call NReadES16
                pop hl
                jp c,.translated
                ld (V_BX),hl
                ld (V_AX),de
                push de
                ld a,#34
                call NMap2
                ld hl,#60
                ld de,#6B2
                call NTileSet
                ld de,#8F
                call NTileSet
                ld b,15
.fullAll:       ld de,#6BA
                call NTileSet
                ld de,#8F
                call NTileSet
                djnz .fullAll
                pop de
                call NTileSet                   ; [#A0] — конец по таблице
                ld de,#8F
                call NTileSet
                xor a
                ld (V_CX),a
                ld (V_CX+1),a                   ; CX = 0 после LOOP
                jp .coreOk
; Конец полосы: [#A0] = #6BF, [#A2] = #8F; CX = 0.
.tail:          ld hl,#A0
                ld de,#6BF
                call NTileSet
                ld de,#8F
                call NTileSet
                xor a
                ld (V_CX),a
                ld (V_CX+1),a
                ret
.translated:    scf                             ; таблица через границу страницы (не бывает): отказ
                ret
.coreOk:        or a
                ret

; ROM $0997C (IP $957C, 6 мест вызова): спрайт звена составного объекта ($1BCC). Если [[bp+#36]] = #A3B3 и кадр
; [#2EB6] нечётный — на время вывода младший байт [bp+6] (палитра) = [bp+#3E]. Флаги после RET не живут.
; Условия: DS = #4000, BP и [bp+#36] внутри рабочего ОЗУ; описание через границу страницы — перевод с входа.
N_957C:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix
                ld l,(ix+#36)
                ld h,(ix+#37)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                ld a,(hl)
                cp #B3
                jr nz,.plain
                inc hl
                ld a,(hl)
                cp #A3
                jr nz,.plain
                ld a,(#4000+#2EB6)
                rrca
                jr nc,.plain
                ld a,(ix+6)
                ld (N_PAL),a
                ld a,(ix+#3E)
                ld (ix+6),a
                ld (V_AX),a                     ; MOV AL,[bp+#3E]
                call NSpriteAdd
                ld a,(N_PAL)
                ld (ix+6),a                     ; POP [bp+6]
                jp c,.translated                ; описание через границу: [bp+6] уже прежний
                jp NRet
.plain:         call NSpriteAdd
                jp c,.translated
                jp NRet
.translated:    ld a,$$K_0997C
                ld hl,K_0997C
                jp FARJP

; ROM $042C4 (IP $3EC4, обработчик снаряда игрока из матрицы оружия): X += [bp+#10], Y += [bp+#12] (Q8), спрайт по
; описанию ES:[bp+#14] ($1BCC), прямоугольник по таблице #204E ($38F4), рельеф ($1EB5): тайл A = #9F6 — стирание
; ($4FB9 — переводом до конца обработчика); стена (A < #DFC или B < #7D0) — конец $3F07; [bp+#17] = 0 — конец $3EFE;
; вне поля ($1D6B) — конец $3F10; иначе RET. Концы (освобождение ресурса $523E и новый обработчик) — переводом.
; Регистры — как у ROM. Условия: DS = #4000, BP < #3F00, ES = #1000; отказ до первой записи — перевод с входа.
N_3EC4:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix
                ld l,(ix+#14)
                ld h,(ix+#15)
                ld a,h
                and #3F
                cp #3F
                jr nz,.descOk
                ld a,l
                cp #FB
                jp nc,.translated               ; описание через границу страницы
.descOk:        ld l,(ix+#10)
                ld h,(ix+#11)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld l,(ix+#12)
                ld h,(ix+#13)
                ld (V_AX),hl
                call NAddY                      ; $0689
                ld l,(ix+#14)
                ld h,(ix+#15)
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC (граница страницы проверена выше)
                ld hl,#204E
                ld (V_SI),hl
                call NHitbox                    ; $38F4 (#204E: всегда в одной странице)
                call NTerrainAB                 ; $1EB5
                jr c,.afterTerrain
                ld hl,(V_AX)
                ld a,h
                cp #09
                jr nz,.noErase
                ld a,l
                cp #F6
                jr nz,.noErase
                NTAIL A_042E4                   ; стирание тайла — переводом
.noErase:       ld de,-#DFC
                add hl,de
                jr nc,.wall
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jr nc,.wall
                ld a,(ix+#17)
                or a
                jr z,.endTimer
                call NOnField
                jr c,.endField
                jp NRet
.wall:          NTAIL A_04307
.endTimer:      NTAIL A_042FE
.endField:      NTAIL A_04310
.afterTerrain:  NTAIL A_042DC                   ; слово VRAM на границе: $1EB5 — переводом
.translated:    ld a,$$K_042C4
                ld hl,K_042C4
                jp FARJP

; ROM $05340 (IP $4F40, обработчик выстрела игрока): X += 8 (24 бита), рельеф ($1EB5): тайл A = #9F6 — стирание
; ($4FB9 — переводом), стена — конец $4FA3; ещё X += 8, прямоугольник по таблице #26E4 ($38F4), рельеф снова (стена —
; $4FA3), спрайт по описанию #26EC ($1BCC); [bp+#17] = 0 — конец $4F9A; X ≥ #2B8 — конец $4FAC; иначе RET. Концы —
; переводом. Регистры — как у ROM. Условия: DS = #4000, BP < #3F00, ES = #1000.
N_4F40:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix
                ld hl,#800
                call NAddX                      ; ADD [bp+3],#800 с переносом в [bp+5]
                call NTerrainAB
                jp c,.terrain1
                ld hl,(V_AX)
                ld a,h
                cp #09
                jr nz,.check1
                ld a,l
                cp #F6
                jr nz,.check1
                NTAIL A_05352                   ; стирание тайла — переводом
.check1:        call .wallCheck
                jr c,.wall
                ld hl,#800
                call NAddX
                ld hl,#26E4
                ld (V_SI),hl
                call NHitbox
                call NTerrainAB
                jr c,.terrain2
                ld hl,(V_AX)
                ld a,h
                cp #09
                jr nz,.check2
                ld a,l
                cp #F6
                jr nz,.check2
                NTAIL A_05378
.check2:        call .wallCheck
                jr c,.wall
                ld hl,#26EC
                ld (V_BX),hl
                call NSpriteAdd
                ld a,(ix+#17)
                or a
                jr z,.endTimer
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#2B8
                add hl,de
                jr c,.endRight
                jp NRet
; Стена: тайл A < #DFC или тайл B < #7D0 — CF = 1.
.wallCheck:     ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                ccf
                ret c
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                ccf
                ret
.wall:          NTAIL A_053A3
.endTimer:      NTAIL A_0539A
.endRight:      NTAIL A_053AC
.terrain1:      NTAIL A_0534A
.terrain2:      NTAIL A_05370
.translated:    ld a,$$K_05340
                ld hl,K_05340
                jp FARJP

; ROM $03150 (IP $2D50, бит R-9 — первое состояние следа): счётчик [bp+#11] (при заряде [#2F26] ≠ 0 и [bp+#11] < #E0 —
; +5), затем −1 до нуля; раз в 8 кадров при [bp+#13] ≥ 7 — [bp+#11] = 0, [bp+#13] = 0; без заряда [bp+#13] + 1.
; Точка следа: смещение по таблице ES:#15DE/#15E0 (направление [#2F25] & #F, фаза ([bp+#11] >> 6) & 3) от R-9
; ([#24], [#28] + #20) — в кольцо истории #1DA0/#1D80 по [#8C] (+2). Движение к точке кольца по [#8E] (+2) со скоростью
; из таблицы ES:#16DE (по [bp+#11] >> 3 при [#2F25] ≠ 0, иначе 0): по X ($0672) и по Y ($0689), с мёртвой зоной DL.
; Кадр [bp+#C] 0…11 раз в 4 кадра, спрайт по описанию #175E + кадр·6 в запись #3D0 ($1BE9), прямоугольник по таблице
; #17EE ($38F4), разрушаемые тайлы ($2736). [#33] = 0 — освобождение ресурса и обработчик $2CE5 (переводом).
; Условия: DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00. Регистры — как у ROM.
N_2D50:         call NEnemyCheck
                jp c,.translated
                ld a,(#4000+#2F26)
                ld (V_BX),a                     ; BL = [#2F26]
                or a
                jr z,.decay
                ld a,(ix+#11)
                cp #E0
                jr nc,.decay
                add a,5
                ld (ix+#11),a
.decay:         ld a,(ix+#11)
                sub 1
                jr nc,.decayed
                xor a
.decayed:       ld (ix+#11),a
                ld a,(#4000+#2EB6)
                and 7
                jr nz,.charge
                ld a,(ix+#13)
                ld (ix+#13),0
                cp 7
                jr c,.charge
                ld (ix+#11),0
.charge:        ld a,(#4000+#2F26)
                ld (V_AX),a                     ; AL = [#2F26]
                or a
                jr nz,.point
                inc (ix+#13)
.point:         ld a,(#4000+#2F25)
                and #0F
                add a,a
                add a,a
                ld e,a
                ld d,0                          ; BX = ([#2F25] & #F)·4
                ld a,(ix+#11)
                rlca
                rlca
                and 3                           ; AL = ([bp+#11] >> 6) & 7 (старшие два бита)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; AX << 6
                add hl,de
                ld (V_BX),hl                    ; BX += AX
                push hl
                ld de,#15DE
                add hl,de
                call NWord1000                  ; AX = ES:[bx+#15DE]
                pop hl
                jp c,.fail1
                push hl
                ld hl,(#4000+#24)
                add hl,de
                ld (N_BITAX),hl                 ; AX + [#24]
                pop hl
                ld de,#15E0
                add hl,de
                call NWord1000                  ; CX = ES:[bx+#15E0]
                jp c,.fail1
                ld hl,#20
                add hl,de
                ld de,(#4000+#28)
                add hl,de                       ; CX + #20 + [#28]
                ld (V_CX),hl
                ld b,h
                ld c,l                          ; BC — CX
                ld hl,(#4000+#8C)
                ld a,l
                and #1E
                ld l,a
                ld h,0
                ld (V_SI),hl                    ; SI = [#8C] & #1E
                ld de,#4000+#1DA0
                add hl,de
                ld de,(N_BITAX)
                ld (V_AX),de
                ld (hl),e
                inc hl
                ld (hl),d                       ; [si+#1DA0] = AX
                ld de,-#21
                add hl,de                       ; → [si+#1D80]
                ld (hl),c
                inc hl
                ld (hl),b                       ; [si+#1D80] = CX
                ld hl,(#4000+#8C)
                inc hl
                inc hl
                ld (#4000+#8C),hl               ; [#8C] += 2
                ; скорость X: [#2F25] = 0 — строка 0, иначе ([bp+#11] >> 3) & #1F
                ld hl,0
                ld a,(#4000+#2F25)
                or a
                jr z,.speedX
                call .rowIndex
.speedX:        ld (V_BX),hl
                call .readSpeed                 ; AX = ES:[bx+#16DE], DX = AH
                jp c,.fail2
                ld hl,#4000+#1DA0
                call .ringWord                  ; BX = [si+#1DA0], SI по [#8E]
                ld e,(ix+4)
                ld d,(ix+5)
                call .axis
                call NAddX                      ; $0672 с AX = HL
                call .rowIndex                  ; BL = ([bp+#11] >> 3) & #1F, ·2
                ld (V_BX),hl
                call .readSpeed
                jp c,.fail3
                ld hl,#4000+#1D80
                call .ringWord
                ld e,(ix+8)
                ld d,(ix+9)
                call .axis
                call NAddY                      ; $0689
                ld hl,(#4000+#8E)
                inc hl
                inc hl
                ld (#4000+#8E),hl               ; [#8E] += 2
                ld a,(#4000+#2EB6)
                and 3
                jr nz,.frame
                inc (ix+#0C)
                ld a,(ix+#0C)
                cp #0C
                jr c,.frame
                ld (ix+#0C),0
.frame:         ld a,(ix+#0C)
                add a,a
                ld l,a
                add a,a
                add a,l                         ; кадр·6
                ld l,a
                ld h,0
                ld de,#175E
                add hl,de
                ld (V_BX),hl                    ; описание кадра
                ld hl,#3D0
                ld (V_SI),hl
                call NSpritePut                 ; $1BE9
                jp c,.failSprite
                ld hl,#17EE
                ld (V_SI),hl
                call NHitbox                    ; $38F4
                jp c,.failHitbox
                call N2736Core                  ; $2736
                jp c,.fail2736
                ld a,(#4000+#33)
                or a
                jp nz,NRet
                NTAIL A_0329A                   ; [#33] = 0 — освобождение и $2CE5 переводом
; Индекс строки таблицы скоростей: HL = (([bp+#11] >> 3) & #1F)·2. Портит AF.
.rowIndex:      ld a,(ix+#11)
                rrca
                rrca
                rrca
                and #1F
                add a,a
                ld l,a
                ld h,0
                ret
; AX = ES:[bx+#16DE] (BX = HL), DX = старший байт. CF = 1 — граница страницы. Портит AF, BC, DE, HL.
.readSpeed:     ld de,#16DE
                add hl,de
                call NWord1000
                ret c
                ld (V_AX),de
                ld a,d
                ld (V_DX),a
                xor a
                ld (V_DX+1),a                   ; DX = AH
                ret
; Точка кольца: SI = [#8E] & #1E, BX = слово [si+база] (HL — база в окне W1). Портит AF, DE, HL.
.ringWord:      ld a,(#4000+#8E)
                and #1E
                ld e,a
                ld d,0
                ld (V_SI),de
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_BX),de
                ret
; Ось: DE = координата объекта → HL = AX с учётом мёртвой зоны: CX = коорд. + DX; BX ≥ CX — AX; иначе AX = −AX, CX =
; коорд. − DX; BX < CX — оставить −AX, иначе AX = 0. V_AX, V_CX — как у ROM. Портит AF, BC, DE.
.axis:          ld hl,(V_DX)
                add hl,de                       ; CX = коорд. + DX
                ld (V_CX),hl
                ex de,hl                        ; DE = CX, HL = коорд.
                push hl
                ld hl,(V_BX)
                or a
                sbc hl,de                       ; CMP BX,CX
                pop hl
                jr c,.below
                ld hl,(V_AX)
                ret
.below:         ld bc,(V_DX)
                or a
                sbc hl,bc                       ; CX = коорд. − DX
                ld (V_CX),hl
                ex de,hl
                ld hl,(V_BX)
                or a
                sbc hl,de                       ; CMP BX,CX
                jr c,.neg
                ld hl,0
                ld (V_AX),hl                    ; XOR AX,AX
                ret
.neg:           ld hl,(V_AX)
                ld a,l
                cpl
                ld l,a
                ld a,h
                cpl
                ld h,a
                inc hl                          ; NEG AX
                ld (V_AX),hl
                ret
.fail1:         NTAIL A_031B1                   ; таблица точки — переводом (не бывает: таблица в одной странице)
.fail2:         NTAIL A_031F1
.fail3:         NTAIL A_0322B
.failSprite:    NTAIL A_03285
.failHitbox:    NTAIL A_0328B
.fail2736:      NTAIL A_0328E
.translated:    ld a,$$K_03150
                ld hl,K_03150
                jp FARJP

; ROM $02427 (IP $2027, R-9 в полёте): уровень скорости в [#2F2E] (кнопки ускорения [#2F2D], бит 11 [#2044], [bp+#1E] ≥ 2;
; не больше 3), сброс признаков [bp+#18], [bp+#78…#7A]; скорость [bp+#16] ≤ 4; шаг по направлению [#2F21] & #F из
; таблицы ES:[#11B0 + уровень·2] ($0672, $0689); границы поля X #15C…#2A0, Y #9A…#174 (со снятием битов направления);
; прямоугольник [bp+#38…#3E]; счётчик [#37] и [#3E] ≤ 3; наклон [bp+#14] (вверх/вниз, возврат к #14); спрайт наклона
; ES:#12FA (мигание неуязвимости — #26FE) в запись #3C0 ($1BE9); заряд BEAM: удержание — [bp+#1D] + 2 до #80 и полоса
; ($4FD2), [bp+#1B] + 1 до #3F; отпускание — выстрел ($23EA, переводом); рельеф ($1EB5): столкновение — переводом.
; Редкие ветви (автопилот [#2FC1], [#2FC3], [#2FC2]) — переводом. Условия: DS = #4000, ES = #1000, BP < #3F00.
; Отступление по решению пользователя 2026-09-29: при шаге клавиш и джойстика ×2 (Esc) шаг по направлению прибавляется
; дважды (NKeys2x).
N_2027:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop ix
                ld a,(#4000+#2FC3)
                or a
                jp nz,.translated               ; [#2FC3] ≠ 0 — переводом с входа (он и запишет 0)
                xor a
                ld (#4000+#2F2E),a
                ld a,(#4000+#2F2D)
                or a
                jr z,.button
                ld a,2
                ld (#4000+#2F2E),a
                jr .level
.button:        ld a,(#4000+#2044+1)
                and #08
                jr z,.level
                ld a,1
                ld (#4000+#2F2E),a
.level:         ld a,(ix+#1E)
                cp 2
                jr c,.levelCap
                ld hl,#4000+#2F2E
                inc (hl)
.levelCap:      ld a,(#4000+#2F2E)
                cp 4
                jr c,.flags
                ld a,3
                ld (#4000+#2F2E),a
.flags:         xor a
                ld (V_AX),a
                ld (V_AX+1),a                   ; AX = 0
                ld (ix+#18),a
                ld (ix+#19),a
                ld (ix+#78),a
                ld (ix+#79),a
                ld (ix+#1A),a
                ld a,(ix+#16)
                cp 5
                jr c,.speedOk
                ld (ix+#16),4
.speedOk:       ld a,(#4000+#2FC1)
                ld (V_DX),a                     ; DL = [#2FC1]
                or a
                jp nz,.autopilot                ; автопилот — переводом
                ld a,(#4000+#2F21)
                and #0F
                add a,a
                add a,a
                ld (V_AX),a
                ld (V_BX),a
                ld (V_CX),a
                xor a
                ld (V_AX+1),a
                ld (V_BX+1),a
                ld (V_CX+1),a                   ; AX = BX = CX = направление·4
                ld a,(ix+#16)
                add a,a
                ld l,a
                ld h,0
                ld (V_BX),hl                    ; BX = скорость·2
                ld de,#11B0
                add hl,de
                call NWord1000                  ; SI = ES:[bx+#11B0]
                jp c,.failTable
                ld (V_SI),de
                ld hl,(V_CX)
                ld (V_BX),hl                    ; BX = CX
                add hl,de
                push hl
                call NWord1000                  ; AX = ES:[bx+si]
                pop hl
                jp c,.failStep
                ld (V_AX),de
                ex de,hl
                call NAddX                      ; $0672
                call NKeys2x
                call c,NAddX                    ; шаг ×2 (Esc): тот же шаг X ещё раз
                ex de,hl
                inc hl
                inc hl
                call NWord1000                  ; AX = ES:[bx+si+2]
                jp c,.failStepY
                ld (V_AX),de
                ex de,hl
                call NAddY                      ; $0689
                call NKeys2x
                call c,NAddY                    ; шаг ×2 (Esc): тот же шаг Y ещё раз
                ; границы поля: AX = #15C, BX = #2A0, CX = #9A, DX = #174
                ld hl,#15C
                ld (V_AX),hl
                ld hl,#2A0
                ld (V_BX),hl
                ld hl,#9A
                ld (V_CX),hl
                ld hl,#174
                ld (V_DX),hl
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#15C
                add hl,de
                jr c,.xLowOk
                ld hl,#4000+#2F21
                res 1,(hl)
                ld (ix+4),#5C
                ld (ix+5),1
.xLowOk:        ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#2A0
                add hl,de
                jr nc,.xHighOk
                ld hl,#4000+#2F21
                res 0,(hl)
                ld (ix+4),#A0
                ld (ix+5),2
.xHighOk:       ld l,(ix+8)
                ld h,(ix+9)
                ld de,-#9A
                add hl,de
                jr c,.yLowOk
                ld hl,#4000+#2F21
                res 2,(hl)
                ld (ix+8),#9A
                ld (ix+9),0
.yLowOk:        ld l,(ix+8)
                ld h,(ix+9)
                ld de,-#174
                add hl,de
                jr nc,.yHighOk
                ld hl,#4000+#2F21
                res 3,(hl)
                ld (ix+8),#74
                ld (ix+9),1
.yHighOk:       ld l,(ix+4)
                ld h,(ix+5)
                ld de,-7
                add hl,de
                ld (ix+#38),l
                ld (ix+#39),h                   ; [bp+#38] = X − 7
                ld de,15
                add hl,de
                ld (ix+#3A),l
                ld (ix+#3B),h                   ; [bp+#3A] = X + 8
                ld l,(ix+8)
                ld h,(ix+9)
                dec hl
                ld (ix+#3C),l
                ld (ix+#3D),h                   ; [bp+#3C] = Y − 1
                ld de,7
                add hl,de
                ld (ix+#3E),l
                ld (ix+#3F),h                   ; [bp+#3E] = Y + 6
                ld (V_AX),hl                    ; AX = Y + 6
                ld hl,#37
                ld (V_BX),hl                    ; BX = #37
                ld a,(#4000+#37)
                or a
                jr z,.pitch
                dec a
                ld (#4000+#37),a
                ld a,(#4000+#3E)
                cp 3
                jr nc,.pitch
                inc a
                ld (#4000+#3E),a
.pitch:         ld a,(#4000+#2F21)
                bit 3,a
                jr z,.pitchDown
                ld a,(ix+#14)
                or a
                jr z,.pitchDown
                dec (ix+#14)
.pitchDown:     ld a,(#4000+#2F21)
                bit 2,a
                jr z,.pitchBack
                ld a,(ix+#14)
                cp #27
                jr z,.pitchBack
                inc (ix+#14)
.pitchBack:     ld a,(#4000+#2F21)
                and #0C
                jr nz,.sprite
                ld a,(ix+#14)
                cp #14
                jr z,.sprite
                jr c,.pitchUp                   ; CMP [bp+#14],#14: CF — ниже #14
                dec (ix+#14)                    ; выше — DEC (JAE по CF от CMP)
                jr .sprite
.pitchUp:       inc (ix+#14)                    ; ниже — DEC и ADD 2
.sprite:        ld a,(ix+#14)
                and #38
                rrca                            ; BX >> 1
                ld (V_AX),a
                ld c,a
                rrca                            ; BX >> 1 ещё раз
                add a,c
                ld l,a
                ld h,0
                ld de,#12FA
                add hl,de                       ; BX — описание наклона
                xor a
                ld (V_AX+1),a                   ; AX = (наклон & #38) >> 1
                ld a,(#4000+#2FC6)
                or a
                jr z,.put
                ld a,(#4000+#2EB6)
                and 3
                jr nz,.put
                ld hl,#26FE                     ; мигание неуязвимости
.put:           ld (V_BX),hl
                ld hl,#3C0
                ld (V_SI),hl                    ; SI = #3C0
                call NSpritePut                 ; $1BE9
                jp c,.failSprite
                ld a,(#4000+#2F23)
                ld (V_AX),a
                bit 7,a
                jr z,.release
                ld (ix+#18),1
                ld (ix+#78),1
.release:       ld a,(#4000+#2F24)
                ld (V_AX),a
                bit 7,a
                jp nz,.fire                     ; отпускание — выстрел ($23EA) переводом
                ld a,(#4000+#2F21)
                ld (V_AX),a
                bit 7,a
                jr z,.charged
                ld a,(ix+#1D)
                cp #80
                jr nc,.charged
                add a,2
                ld (ix+#1D),a
                ld (V_AX),a
                xor a
                ld (V_AX+1),a                   ; AX = [bp+#1D]
                call N4FD2Core                  ; $4FD2 — полоса заряда
                jp c,.failMeter
.charged:       ld a,(#4000+#2F23)
                ld (V_AX),a
                bit 7,a
                jr nz,.full
                ld a,(#4000+#2F21)
                ld (V_AX),a
                bit 7,a
                jr z,.terrain
                inc (ix+#1B)
                ld a,(ix+#1B)
                cp #3F
                jr c,.terrain
.full:          ld (ix+#1A),1
.terrain:       ld a,(#4000+#2FC2)
                or a
                jp nz,.special                  ; [#2FC2] ≠ 0 — переводом
                call NTerrainAB                 ; $1EB5
                jp c,.failTerrain
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jp nc,.crash
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jp nc,.crash
                ld a,(ix+#37)
                or a
                jp nz,.crash
                jp NRet
.translated:    ld a,$$K_02427
                ld hl,K_02427
                jp FARJP
.autopilot:     NTAIL A_0248C
.failTable:     NTAIL A_024F5
.failStep:      NTAIL A_024FC
.failStepY:     NTAIL A_02502
.failSprite:    NTAIL A_025DF
.fire:          NTAIL A_025F8
.failMeter:     NTAIL A_0261B
.special:       NTAIL A_02640
.failTerrain:   NTAIL A_02643
.crash:         NTAIL A_02669

; Шаг R-9 от клавиш и Kempston-джойстика ×2 — отступление от оригинала по решению пользователя 2026-09-29: «при нажатии
; ESC корабль сдвигается с шагом в 2 больше с клавиатуры или Kempston Joystick. Повторное нажатие клавиши ESC
; возвращает обычное поведение». Переключает Esc в оболочке p2c (p2c_z80_runtime_cold.c), машине — бит API_KEYS2X
; флагов шага (API_FLAGS резидента, p2c_port_step). Шаг по направлению [#2F21] (клавиши и джойстик игрока) из таблицы
; скорости N_2027 прибавляется дважды — $0672 и $0689 ещё раз с тем же AX, до рамок поля, как если бы шаг таблицы был
; вдвое больше; наклон, прямоугольник и прочее — как у ROM. Не в демо аттракта: при обработчике директора [DS:0] = $0A8B
; ROM ведёт корабль записью ввода ($0167). Автопилот [#2FC1] идёт переводом и сюда не попадает; мышь (ApiMouse) не
; удваивается. Эталон сверки делает то же ловушками на IP $2102 и $2109 (rtype_check.py, install_keys_double).
; CF = 1 — прибавить шаг ещё раз. Портит AF; HL, DE сохраняет.
NKeys2x:        ld a,(API_FLAGS)
                and API_KEYS2X                  ; CF = 0
                ret z
                ld a,(#4000+1)
                cp #0A
                jr nz,.twice
                ld a,(#4000)
                cp #8B
                jr nz,.twice
                or a                            ; демо аттракта: CF = 0
                ret
.twice:         scf
                ret

; ROM $0EBD4 (IP $E7D4) — взрыв (обработчик от $E7BE, все этапы; профиль этапа 7 — 2,0 %, этапа 3 — 1,1 % тактов со
; всеми вызовами): X += AX = [2ED0]; спрайт $1BCC по описанию BX = ES:[[bp+0E] + 2]; DEC [bp+0D] — ноль: [bp+0E] +=
; 4, AX = ES:[[bp+0E]] — 0: конец ($E802 переводом), иначе [bp+0D] = AL; [2FC4] ≠ 0 — конец; иначе RET. Регистры —
; как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа): NObjCheck; слово таблицы на границе страницы
; V30 и отказ описания спрайта — переводом с места.
N_E7D4:         call NObjCheck
                jr c,.translated
                call NScrollX                   ; ADD [bp+4],AX (AX = [2ED0])
                ld l,(ix+#0E)
                ld h,(ix+#0F)
                ld (V_BX),hl                    ; MOV BX,[bp+0E]
                inc hl
                inc hl
                call NWord1000                  ; ES:[bx+2]
                jr c,.descTranslated
                ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jr c,.spriteTranslated
                dec (ix+#0D)
                jr nz,.check
                ld l,(ix+#0E)
                ld h,(ix+#0F)
                ld de,4
                add hl,de
                ld (ix+#0E),l
                ld (ix+#0F),h                   ; ADD WORD [bp+0E],4
                ld (V_BX),hl                    ; MOV BX,[bp+0E]
                call NWord1000                  ; AX = ES:[bx]
                jr c,.nextTranslated
                ld (V_AX),de
                ld a,d
                or e
                jr z,.end                       ; AND AX,AX; JE $E802
                ld (ix+#0D),e                   ; MOV [bp+0D],AL
.check:         ld a,(#4000+#2FC4)
                or a
                jp z,NRet
.end:           NTAIL A_0EC02                   ; $E802: ресурс и CALL $03EC
.descTranslated:
                NTAIL A_0EBDD                   ; MOV BX,ES:[bx+2]
.spriteTranslated:
                NTAIL A_0EBE1                   ; CALL $1BCC
.nextTranslated:
                NTAIL A_0EBF0                   ; MOV AX,ES:[bx]
.translated:    ld a,$$K_0EBD4
                ld hl,K_0EBD4
                jp FARJP

; ROM $0FFED (IP $FBED) — таймер вспышки палитры (этап 6; с циклом объектов — ≈2,3 % тактов этапа): [2FC4] ≠ 0 или
; DEC [bp+26] до нуля — удаление ($FC1C, переводом); AX = [2EB6] + [bp+2C]; [bp+2A] & AX ≠ 0 — RET; иначе запись
; палитры $54E4 (переводом с $FC04). Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа):
; NObjCheck.
N_FBED:         call NObjCheck
                jr c,.translated
                ld a,(#4000+#2FC4)
                or a
                jr nz,.free
                ld l,(ix+#26)
                ld h,(ix+#27)
                dec hl
                ld (ix+#26),l
                ld (ix+#27),h                   ; DEC WORD [bp+26]
                ld a,h
                or l
                jr z,.free
                ld hl,(#4000+#2EB6)
                ld e,(ix+#2C)
                ld d,(ix+#2D)
                add hl,de
                ld (V_AX),hl                    ; AX = [2EB6] + [bp+2C]
                ld a,l
                and (ix+#2A)
                jp nz,NRet
                ld a,h
                and (ix+#2B)
                jp nz,NRet                      ; TEST [bp+2A],AX ≠ 0 — RET
                NTAIL A_10004                   ; $FC04: запись палитры
.free:          NTAIL A_1001C                   ; $FC1C: CALL $03EC
.translated:    ld a,$$K_0FFED
                ld hl,K_0FFED
                jp FARJP

; ROM $04157 (IP $3D57) — кадры вспышки оружия (цикл слотов): спрайт $1BCC по описанию BX = [bp+14]·6 + [bp+12] (AX =
; [bp+14]·4); DEC [bp+14] — ноль: ресурс и возврат обработчика [bp] = [bp+0A] ($3D6E, переводом); иначе RET. Регистры
; — как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа): NObjCheck; отказ описания — переводом с места.
N_3D57:         call NObjCheck
                jr c,.translated
                ld l,(ix+#14)
                ld h,(ix+#15)
                add hl,hl                       ; BX = [bp+14]·2
                ld d,h
                ld e,l
                add hl,hl
                ld (V_AX),hl                    ; AX = BX·2
                add hl,de                       ; BX + AX
                ld e,(ix+#12)
                ld d,(ix+#13)
                add hl,de
                ld (V_BX),hl                    ; + [bp+12]
                call NSpriteAdd                 ; $1BCC
                jr c,.spriteFail
                ld l,(ix+#14)
                ld h,(ix+#15)
                dec hl
                ld (ix+#14),l
                ld (ix+#15),h                   ; DEC WORD [bp+14]
                ld a,h
                or l
                jp nz,NRet
                NTAIL A_0416E                   ; $3D6E: ресурс, [bp] = [bp+0A]
.spriteFail:    NTAIL A_04165                   ; CALL $1BCC
.translated:    ld a,$$K_04157
                ld hl,K_04157
                jp FARJP

; ROM $0F061 (IP $EC61) — заливка ячеек слоя A пустым тайлом #19 с атрибутом #8F: CX ячеек с ES:BX (ES = #D000), шаг
; 4. Зовёт только печать панели $EC7B при каждом уничтожении (100 ячеек; в переводе — ≈200 записей VRAM через
; помощники, ≈1,5 % тактов этапа 7). Пометки для адаптера — диапазоном (VIDEO_MARK_RANGE: те же группы и строки, что
; у записей по одной). После: AX = #19, DX = #8F, BX — за последней ячейкой, CX = 0, ES прежний; флаги после RET не
; живут (flags.liveness). Условия (иначе перевод с входа): 1 ≤ CX < #1000, BX + CX·4 ≤ #4000.
N_EC61:         ld hl,(V_CX)
                ld a,h
                or l
                jr z,.translated
                ld a,h
                cp #10
                jr nc,.translated
                add hl,hl
                add hl,hl                       ; CX·4
                ld de,(V_BX)
                add hl,de
                jr c,.translated
                ld (N_ECEND),hl                 ; BX после цикла
                ld bc,#4001
                or a
                sbc hl,bc
                jr nc,.translated               ; конец дальше #4000
                ld a,(W2_PAGE)
                cp #34
                ld a,#34
                call nz,NMap2                   ; VRAM слоя A (#D0000) — в окно W2
                ld hl,(V_BX)
                set 7,h
                ld bc,(V_CX)
.fill:          ld (hl),#19
                inc hl
                ld (hl),0                       ; ES:[bx] = AX = #19
                inc hl
                ld (hl),#8F
                inc hl
                ld (hl),0                       ; ES:[bx+2] = DX = #8F
                inc hl
                dec bc
                ld a,b
                or c
                jr nz,.fill
                ld hl,(V_BX)
                ld de,(N_ECEND)
                dec de                          ; последний байт
                ld a,#34
                call VIDEO_MARK_RANGE           ; группы и строки диапазона, VIDEO_DIRTY
                ld hl,(N_ECEND)
                ld (V_BX),hl
                ld hl,0
                ld (V_CX),hl
                ld hl,#19
                ld (V_AX),hl
                ld hl,#8F
                ld (V_DX),hl
                jp NRet
.translated:    ld a,$$K_0F061
                ld hl,K_0F061
                jp FARJP

; ROM $0F07B (IP $EC7B) — печать панели в VRAM слоя A (#D0000; задача главного цикла и вызов из начисления очков $E989 —
; при каждом уничтожении; в переводе с помощниками — до ≈0,8 % тактов этапа 7): заливка ячеек пустым тайлом ($EC61:
; #20…#DF, #120…#12B, #13C…#1A3, #1B4…#1DF — тайл #19, атрибут #8F), значки жизней ([2F32], у второго игрока ([2F20] ≠ 0)
; — [2F3A]: при ≥ 2 — lives − 1 значков #6A с #24), полоса BEAM ($4FD2 по байту [#3D]: ячейки #60…#A3) и счёт $E9A0
; (при [2F1F] ≠ 0 — второй игрок [2F3F…] в #1B4; первый [2F37…] в #13C; рекорд [2F50…] в #178: 7 цифр BCD → #30…#39 в
; [2FD0…2FD6], ведущие нули (до 6) → #11, ячейка — цифра с атрибутом #8F; надписи ROM #18754 (8 слов) в #168 и #18764
; (12 слов) в #48). Нативно — сразу итог: ячейка, которую ROM сначала заливает, а потом рисует, получает только рисунок;
; слово пишется и помечается для вывода, только если отличается (NTileSet), — память V30 после процедуры та же, что у
; ROM, пометки покрывают все изменённые слова. Надписи ROM читаются один раз (ROM не меняется). После: AX = #D000, CX = 0,
; SI = #877C, DI = #60, BX и DX — от $4FD2, [2FD0…2FD6] — цифры рекорда; флаги — от последнего INC SI ($E9E7, SI = #2FD7
; после ADD DI,4 без переноса): CF = ZF = SF = AF = OF = 0, PF = 1. Условия (иначе перевод с входа): DS = #4000, DF = 0
; (REP MOVSW надписей), значков не больше 9 (дальше их закрыла бы надпись BEAM).
N_EC7B:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld a,(V_FL+1)
                and 4
                jp nz,.translated               ; DF = 1
                ld hl,(#4000+#2F32)
                ld a,(#4000+#2F20)
                or a
                jr z,.lives
                ld hl,(#4000+#2F3A)
.lives:         ld a,h
                or a
                jp nz,.translated               ; жизней ≥ #100
                ld a,l
                sub 1
                jr nc,.count
                xor a                           ; жизней 0 — значков нет
.count:         cp 10
                jp nc,.translated               ; значков больше 9
                ld (N_HUDN),a                   ; значков: жизни − 1 (при 0 и 1 — нет)
                ; Регистры перед CALL $4FD2 ($ECD6): AX = [#3D], BX — за последней ячейкой (значков или четвёртой
                ; заливки), CX = 0, DX = #8F.
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                ld de,#24
                add hl,de                       ; BX = #24 + значков·4
                or a
                jr nz,.bx
                ld hl,#1E0                      ; без значков — за заливкой #1B4
.bx:            ld (V_BX),hl
                ld hl,0
                ld (V_CX),hl
                ld hl,#8F
                ld (V_DX),hl
                ld a,(#4000+#3D)
                ld l,a
                ld h,0
                ld (V_AX),hl
                ; Надписи ROM (40 байт с #18754) — в копию на странице при первом вызове.
                ld a,(N_HUDOK)
                or a
                jr nz,.labelsReady
                ld a,6
                call NMap2                      ; ROM #18000…#1BFFF — в окно W2
                ld hl,#8000+#0754
                ld de,N_HUDLBL
                ld bc,40
                ldir
                ld a,1
                ld (N_HUDOK),a
.labelsReady:   call N4FD2Core                  ; полоса BEAM: ячейки #60…#A3 (их заливку ROM перекрывает полосой)
                jp c,.translated                ; до записей VRAM; регистры перевод с входа ставит заново
                ld a,(W2_PAGE)
                cp #34
                ld a,#34
                call nz,NMap2                   ; VRAM слоя A — в окно W2
                ; Строка 0: #20 — пусто; #24…#47 — значки, дальше пусто; #48…#5F — надпись; #A4…#DF — пусто.
                ld hl,#20
                ld b,1
                call .blanks
                ld a,(N_HUDN)
                or a
                jr z,.noIcons
                ld b,a
.icons:         ld de,#6A
                call .cell
                djnz .icons
.noIcons:       ld a,(N_HUDN)
                neg
                add a,9
                jr z,.label0
                ld b,a
                call .blanks
.label0:        ld hl,#48
                ld ix,N_HUDLBL+16
                ld b,12                         ; 12 слов надписи #18764
                call .words
                ld hl,#A4
                ld b,15
                call .blanks
                ; Строка 1 (второй игрок, первый, рекорд — в порядке ROM: буфер [2FD0…] остаётся за рекордом).
                ld hl,#120
                ld b,3
                call .blanks
                ld a,(#4000+#2F1F)
                or a
                jr z,.noP2
                ld hl,#2F3F
                ld de,#1B4
                call .number                    ; второй игрок
.noP2:          ld hl,#2F37
                ld de,#13C
                call .number                    ; первый игрок
                ld hl,#158
                ld b,4
                call .blanks
                ld hl,#168
                ld ix,N_HUDLBL
                ld b,8                          ; 8 слов надписи #18754
                call .words
                ld hl,#2F50
                ld de,#178
                call .number                    ; рекорд
                ld hl,#194
                ld b,4
                call .blanks
                ld a,(#4000+#2F1F)
                or a
                ld hl,#1B4
                ld b,11
                jr z,.p2Blank
                ld hl,#1D0
                ld b,4
.p2Blank:       call .blanks
                ; Регистры и флаги — как после RET $E9A0.
                ld hl,#D000
                ld (V_AX),hl
                ld hl,0
                ld (V_CX),hl
                ld hl,#877C
                ld (V_SI),hl
                ld hl,#60
                ld (V_DI),hl
                ld a,#06
                ld (V_FL),a                     ; PF = 1, бит 1; CF = AF = ZF = SF = 0
                ld hl,V_FL+1
                res 3,(hl)                      ; OF = 0
                jp NRet
.translated:    ld a,$$K_0F07B
                ld hl,K_0F07B
                jp FARJP
; B пустых ячеек (#19, #8F) с HL. Портит AF, B, DE; HL — за ячейками.
.blanks:        ld de,#19
.blank:         call .cell
                djnz .blank
                ret
; Ячейка слоя A по смещению HL (окно W2 — #34): слово тайла DE и слово атрибута #8F. Пишется и помечается для вывода
; (VIDEO_MARK — группа ячейки), только если хоть один из четырёх байтов отличается. HL += 4 (ячейки панели не
; переходят границу 256 байт: строки #20…#DF, #120…#1DF). Портит AF.
.cell:          push hl
                set 7,h
                ld a,(hl)
                cp e
                jr nz,.cellWrite
                inc l
                ld a,(hl)
                cp d
                jr nz,.cellWrite
                inc l
                ld a,(hl)
                cp #8F
                jr nz,.cellWrite
                inc l
                ld a,(hl)
                or a
                jr nz,.cellWrite
                pop hl
                ld a,l
                add a,4
                ld l,a
                ret
.cellWrite:     pop hl
                push hl
                set 7,h
                ld (hl),e
                inc l
                ld (hl),d
                inc l
                ld (hl),#8F
                inc l
                ld (hl),0
                pop hl
                ld a,#34
                call VIDEO_MARK                 ; группа и строка ячейки, VIDEO_DIRTY
                ld a,l
                add a,4
                ld l,a
                ret
; B слов с IX в ячейки с HL. Портит AF, B, DE, IX.
.words:         ld e,(ix+0)
                ld d,(ix+1)
                call NTileSet
                inc ix
                inc ix
                djnz .words
                ret
; Число BCD: HL = SI (старший байт, DS = #4000), DE = DI (ячейки VRAM). $192F, три $193A — 7 цифр в [2FD0…2FD6],
; $191B — ведущие нули → #11, цикл $EA0A — ячейки (цифра, #8F). Портит всё, кроме IY.
.number:        push de
                set 6,h                         ; DS:[SI] — окно W1
                ld de,#4000+#2FD0
                ld a,(hl)
                and #0F
                or #30
                ld (de),a                       ; $192F: младшая тетрада старшего байта
                inc de
                dec hl
                ld b,3
.bcd:           ld a,(hl)
                rrca
                rrca
                rrca
                rrca
                and #0F
                or #30
                ld (de),a                       ; $193A: старшая тетрада
                inc de
                ld a,(hl)
                and #0F
                or #30
                ld (de),a                       ; младшая
                inc de
                dec hl
                djnz .bcd
                ld hl,#4000+#2FD0
                ld b,6
.zeros:         ld a,(hl)
                cp #30
                jr nz,.digits
                ld (hl),#11                     ; $191B: ведущий ноль — пусто
                inc hl
                djnz .zeros
.digits:        pop hl                          ; ячейки с DI
                ld ix,#4000+#2FD0
                ld b,7
.digit:         ld e,(ix+0)
                ld d,0
                call .cell                      ; ES:[DI] = AX = цифра, ES:[DI+2] = #8F
                inc ix
                djnz .digit
                ret

N_PART          DB 0
N_ECEND         DW 0                            ; $EC61: BX после цикла заливки
N_HUDN          DB 0                            ; $EC7B: значков жизней
N_HUDOK         DB 0                            ; $EC7B: надписи ROM прочитаны
N_HUDLBL        DS 40                           ; надписи ROM #18754…#1877B (8 слов — в #168, 12 — в #48)


N_BITAX         DW 0                            ; точка следа бита ($2D50)

; ROM $0C8BC (IP $C4BC) — управление линкором этапа 3 (объект списка, каждый шаг; в переводе — ≈0,5 % тактов этапа):
; INC [bp+32] (значения #1180 и #12C0 — события, переводом с входа); X += [2ED4], Y += [2ED6]; снос фона: [2EF4] =
; [bp+20]·16 (байт), слово [2EF5] = знак [bp+20] (#FFFF или 0), [2EF8], [2EF9] — так же от [bp+22]; $C61F — порождение
; частей по таблице ES:[bp+30]: AX = −X, BX = [bp+30], CX = ES:[BX]; AX < CX — рано (RET), иначе — переводом с $C62E
; (адрес возврата $C50C — в стек V30); [bp+3E] ≠ 0 — гибель ($C544, переводом); DEC [bp+14] до нуля — $C5F8: шаг
; сценария ES:[bp+12]: [bp+22] = AX с AL = байт 0 (AH — от −X), [bp+20] = AX с AL = байт 1, байт 2 = #80 — конец сценария
; (переводом с $C60C, адрес возврата $C51A), иначе [bp+14] = AX = байт 2, [bp+12] = BX = [bp+12] + 3; [2FC4] ≠ 0 —
; $C524 (переводом); иначе RET. Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа):
; NObjCheck; слово ES:[bp+30] на границе страниц — перевод с $C627 (адрес возврата $C50C).
N_C4BC:         call NObjCheck
                jp c,.translated
                ld l,(ix+#32)
                ld h,(ix+#33)
                inc hl
                ld de,-#1180
                add hl,de
                ld a,h
                or l
                jp z,.translated                ; [bp+32] станет #1180 — $F366
                ld de,#1180-#12C0
                add hl,de
                ld a,h
                or l
                jp z,.translated                ; #12C0 — звук #19
                inc (ix+#32)
                jr nz,.counted
                inc (ix+#33)                    ; INC WORD [bp+32]
.counted:       ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,(#4000+#2ED6)
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD [bp+8],AX
                ld a,(ix+#20)
                call .drift
                ld (#4000+#2EF4),a
                ld (#4000+#2EF5),hl
                ld a,(ix+#22)
                call .drift
                ld (#4000+#2EF8),a
                ld (#4000+#2EF9),hl
                ld l,(ix+4)                     ; $C61F: AX = −X
                ld h,(ix+5)
                xor a
                sub l
                ld l,a
                sbc a,a
                sub h
                ld h,a
                ld (V_AX),hl
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_BX),hl                    ; BX = [bp+30]
                call NWord1000                  ; DE = ES:[BX]
                jr nc,.table
                ld hl,#C50C
                push hl                         ; CALL $C61F: адрес возврата
                NTAIL A_0CA27                   ; слово на границе страниц — MOV CX,ES:[BX] переводом
.table:         ld (V_CX),de
                ld hl,(V_AX)
                or a
                sbc hl,de                       ; CMP AX,CX
                jr c,.early                     ; JB — рано
                ld hl,#C50C
                push hl
                NTAIL A_0CA2E                   ; порождение
.early:         ld a,(ix+#3E)
                or a
                jr z,.alive
                NTAIL A_0C944                   ; гибель
.alive:         ld l,(ix+#14)
                ld h,(ix+#15)
                dec hl
                ld (ix+#14),l
                ld (ix+#15),h                   ; DEC WORD [bp+14]
                ld a,h
                or l
                jr nz,.field
                ld l,(ix+#12)                   ; $C5F8: BX = [bp+12]
                ld h,(ix+#13)
                ld (V_BX),hl
                push hl
                call NByte1000
                ld (ix+#22),a
                ld a,(V_AX+1)
                ld (ix+#23),a                   ; [bp+22] = AX (AL = ES:[bx])
                pop hl
                push hl
                inc hl
                call NByte1000
                ld (ix+#20),a
                ld a,(V_AX+1)
                ld (ix+#21),a                   ; [bp+20] = AX (AL = ES:[bx+1])
                pop hl
                push hl
                inc hl
                inc hl
                call NByte1000                  ; AL = ES:[bx+2]
                pop hl
                ld (V_AX),a
                cp #80
                jr nz,.step
                ld hl,#C51A
                push hl                         ; CALL $C5F8: адрес возврата
                NTAIL A_0CA0C                   ; конец сценария: CMP AL,#80 переводом
.step:          ld (ix+#14),a
                ld (ix+#15),0                   ; [bp+14] = AX (AH = 0)
                xor a
                ld (V_AX+1),a
                inc hl
                inc hl
                inc hl
                ld (ix+#12),l
                ld (ix+#13),h                   ; [bp+12] = BX = BX + 3
                ld (V_BX),hl
.field:         ld a,(#4000+#2FC4)
                or a
                jp z,NRet
                NTAIL A_0C924                   ; конец этапа
.translated:    ld a,$$K_0C8BC
                ld hl,K_0C8BC
                jp FARJP
; Снос фона: A = байт направления → A = A·16 (байт), HL = знак (#FFFF при бите 7, иначе 0). Портит F.
.drift:         ld hl,0
                bit 7,a
                jr z,.shl
                dec hl
.shl:           add a,a
                add a,a
                add a,a
                add a,a
                ret

; --- пожиратель блоков этапа 4 ($8F86, $90A2; VDAC2+ 2026-09-26: в переводе с помощниками — ≈0,8 % тактов этапа 4) ---
; Два состояния объекта: $8F86 — ход по таблице скоростей и поедание блоков, $90A2 — поворот (счётчик [bp+30]). Сканы
; столкновений $F694 (ядро резидента с первой нативной страницей) зовутся как CALL V30: адрес возврата — в стек V30,
; дальше заглушка перевода A_0FA94 (JP ядра); ядро возвращается RET-ом V30 в продолжение — нативные входы $8F96, $90AE.

; ROM $09386 (IP $8F86) — первое состояние: [2FC4] ≠ 0 — $9078 (удаление, переводом); иначе DI = #407E и CALL $F694
; (возврат — N_8F96). Условия (иначе перевод с входа): NObjCheck.
N_8F86:         call NObjCheck
                jp c,.translated
                ld a,(#4000+#2FC4)
                or a
                jr z,.scan
                NTAIL A_09478                   ; JMP $9078
.scan:          ld hl,#407E
                ld (V_DI),hl
                ld hl,#8F96
                push hl                         ; CALL $F694: адрес возврата
                NTAIL A_0FA94
.translated:    ld a,$$K_09386
                ld hl,K_09386
                jp FARJP

; ROM $09396 (IP $8F96) — продолжение после сканов: CF — попадание ($9085, переводом). Иначе скорость по таблице
; ES:[BX + #3F86], ES:[BX + #3F88], BX = [bp+20]·4 + [2F2E]·16 ($0672, $0689 — 24-битные X [bp+3…5] и Y [bp+7…9]);
; X += [2ED0]; направление [bp+20] (бит 1 — вертикальное): R-9 в полосе хода — поворот ($9055: [bp+21] — новое
; направление, [bp+30] = #1F, [bp+32] = ES:[((([bp+20]·4) | [bp+21]) & #FF)·2 + #3FC6], [bp] = #90A2 и сразу $90A2);
; иначе ($9028) спрайт по описанию BX = [bp+20]·24 + ([2EB6] & #C)·3/2 + #4006, поедание блоков $90E0 и проверка поля
; $1D6B (вне поля — $9078, переводом). Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с места):
; NObjCheck; отказы чтений (слово на границе страниц) и строки VRAM за #3FFF — перевод с места отказа.
N_8F96:         call NObjCheck
                jp c,.translated
                ld a,(V_FL)
                rra
                jr nc,.free
                NTAIL A_09485                   ; JMP $9085: попадание
.free:          ld l,(ix+#20)
                ld h,0
                add hl,hl
                add hl,hl                       ; [bp+20]·4
                ld a,(#4000+#2F2E)
                ld e,a
                ld d,0
                ex de,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; [2F2E]·16
                add hl,de
                ld (V_BX),hl                    ; BX
                push hl
                ld de,#3F86
                add hl,de
                call NWord1000                  ; ES:[BX + #3F86]
                jr nc,.velX
                pop hl
                jp .translated                  ; до изменений
.velX:          ld (V_AX),de
                ld bc,3
                call .integrate                 ; $0672: [bp+3…5] += AX
                pop hl
                push hl
                ld de,#3F88
                add hl,de
                call NWord1000                  ; ES:[BX + #3F88]
                pop hl
                jr nc,.velY
                NTAIL A_093CC                   ; MOV AX,ES:[BX+#3F88] переводом
.velY:          ld (V_AX),de
                ld bc,7
                call .integrate                 ; $0689: [bp+7…9] += AX
                ld hl,(#4000+#2ED0)
                ld (V_AX),hl
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                bit 1,(ix+#20)
                jr nz,.vertical
                ld l,(ix+4)                     ; горизонтальный ход: AX = [bp+4] + #10 − [24]
                ld h,(ix+5)
                ld de,#10
                add hl,de
                ld de,(#4000+#24)
                or a
                sbc hl,de
                ld (V_AX),hl
                jp c,.walk                      ; JB
                ld de,#20
                sbc hl,de
                jp nc,.walk                     ; JAE
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_AX),hl                    ; AX = [bp+8]
                ld de,(#4000+#28)
                ld b,2
                or a
                sbc hl,de
                jr c,.turnH
                inc b                           ; [bp+8] ≥ [28]
.turnH:         ld (ix+#21),b
                jr .turn
.vertical:      ld l,(ix+8)                     ; вертикальный ход: AX = [bp+8] + 4 − [28]
                ld h,(ix+9)
                ld de,4
                add hl,de
                ld de,(#4000+#28)
                or a
                sbc hl,de
                ld (V_AX),hl
                jr c,.walk
                ld de,8
                sbc hl,de
                jr nc,.walk
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_AX),hl                    ; AX = [bp+4]
                ld de,(#4000+#24)
                ld b,0
                or a
                sbc hl,de
                jr c,.turnV
                inc b                           ; [bp+4] ≥ [24]
.turnV:         ld (ix+#21),b
.turn:          ld (ix+#30),#1F                 ; $9055
                ld (ix+#31),0
                ld a,(ix+#20)
                add a,a
                add a,a
                or (ix+#21)
                ld l,a
                ld h,0
                add hl,hl
                ld (V_BX),hl                    ; BX = ((([bp+20]·4) | [bp+21]) & #FF)·2
                ld de,#3FC6
                add hl,de
                call NWord1000
                jr nc,.turnWord
                NTAIL A_09468                   ; MOV AX,ES:[BX+#3FC6] переводом
.turnWord:      ld (V_AX),de
                ld (ix+#32),e
                ld (ix+#33),d
                ld (ix+0),#A2
                ld (ix+1),#90                   ; [bp] = #90A2
                jp N_90A2.body                  ; JMP $90A2
.walk:          ld l,(ix+#20)                   ; $9028
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; [bp+20]·24
                ld a,(#4000+#2EB6)
                and #0C
                ld e,a
                ld d,0
                add hl,de
                srl e
                add hl,de
                ld (V_AX),de                    ; AX = ([2EB6] & #C) >> 1
                ld de,#4006
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC
                jr nc,.eatBlocks
                NTAIL A_09449                   ; CALL $1BCC переводом
.eatBlocks:     ld hl,#904F
                push hl                         ; CALL $90E0: адрес возврата
                ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH WORD [bp+4]
                ld l,(ix+8)
                ld h,(ix+9)
                push hl                         ; PUSH WORD [bp+8]
                ld hl,(V_ES)
                push hl                         ; PUSH ES
                ld hl,#D000
                ld (V_AX),hl
                ld (V_ES),hl                    ; ES = #D000
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-4
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; SUB WORD [bp+4],4
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,4
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD WORD [bp+8],4
                push ix
                pop hl
                res 6,h                         ; BP
                call TerrainA                   ; $1E6C: AX, BX, CX (окно W2 — #34, IX → [bp])
                jr nc,.tile0
                NTAIL A_094F4                   ; BX = #3FFF — CALL $1E6C переводом
.tile0:         ld hl,(V_BX)
                call .eat                       ; ES:[BX]
                ld a,l
                add a,4
                ld l,a                          ; ADD BL,4
                ld (V_BX),hl
                call .eat
                ld de,#100
                add hl,de                       ; ADD BX,#100
                ld (V_BX),hl
                ld a,h
                cp #40
                jr c,.row2
                NTAIL A_09524                   ; строка за концом VRAM слоя A — переводом
.row2:          call .eat
                ld a,l
                sub 4
                ld l,a                          ; SUB BL,4
                ld (V_BX),hl
                call .eat
                pop hl
                ld (V_ES),hl                    ; POP ES
                pop hl
                ld (ix+8),l
                ld (ix+9),h                     ; POP WORD [bp+8]
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP WORD [bp+4]
                pop hl                          ; RET $90E0
                call NOnField                   ; $1D6B: CF — вне поля
                jp nc,NRet
                NTAIL A_09478                   ; JB $9078
.translated:    ld a,$$K_09396
                ld hl,K_09396
                jp FARJP
; [bp+C…bp+C+2] += AX со знаком (24 бита): $0672 (BC = 3), $0689 (BC = 7). IX → [bp]. Портит AF, BC, DE, HL.
.integrate:     push ix
                pop hl
                add hl,bc                       ; HL → [bp+C]
                ld de,(V_AX)
                ld a,(hl)
                add a,e
                ld (hl),a
                inc hl
                ld a,(hl)
                adc a,d
                ld (hl),a                       ; ADD [bp+C],AX
                inc hl
                bit 7,d
                jr nz,.negative
                ret nc                          ; без переноса — всё
                inc (hl)                        ; INC BYTE [bp+C+2]
                ret
.negative:      ret c                           ; с переносом — всё
                dec (hl)                        ; DEC BYTE [bp+C+2]
                ret
; Тайл ES:[HL] слоя A (окно W2 — #34): AX = слово & #FFF; блок #9F6 — слово = #FA0, следующее — 0 (запись с пометкой).
; HL сохраняется. Портит AF, DE.
.eat:           push hl
                set 7,h
                ld e,(hl)
                inc hl
                ld a,(hl)
                and #0F
                ld d,a
                pop hl
                ld (V_AX),de                    ; AX = ES:[BX] & #FFF
                ld a,e
                cp #F6
                ret nz
                ld a,d
                cp #09
                ret nz
                push hl
                ld de,#FA0
                call NTileSet                   ; ES:[BX] = #FA0
                ld de,0
                call NTileSet                   ; ES:[BX+2] = 0
                pop hl
                ret

; ROM $094A2 (IP $90A2) — второе состояние (поворот): X += [2ED0]; DI = #407E и CALL $F694 (возврат — N_90AE).
; Условия (иначе перевод с входа): NObjCheck.
N_90A2:         call NObjCheck
                jp c,.translated
.body:          ld hl,(#4000+#2ED0)
                ld (V_AX),hl
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,#407E
                ld (V_DI),hl
                ld hl,#90AE
                push hl                         ; CALL $F694: адрес возврата
                NTAIL A_0FA94
.translated:    ld a,$$K_094A2
                ld hl,K_094A2
                jp FARJP

; ROM $094AE (IP $90AE) — продолжение второго состояния: CF — попадание ($9085, переводом); иначе описание BX =
; ES:[(([bp+30] & #10) >> 3) + [bp+32]], спрайт $1BCC; [2FC4] ≠ 0 — $9078 (переводом); DEC [bp+30] до нуля — [bp+20] =
; AL = [bp+21], [bp] = #8F86. Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с места): NObjCheck.
N_90AE:         call NObjCheck
                jp c,.translated
                ld a,(V_FL)
                rra
                jr nc,.free
                NTAIL A_09485                   ; JMP $9085 ($90B0): попадание
.free:          ld a,(ix+#30)
                and #10
                rrca
                rrca
                rrca                            ; ([bp+30] & #10) >> 3
                ld l,a
                ld h,0
                ld e,(ix+#32)
                ld d,(ix+#33)
                add hl,de
                ld (V_BX),hl                    ; BX
                call NWord1000                  ; ES:[BX]
                jr nc,.desc
                NTAIL A_094BF                   ; MOV BX,ES:[BX] переводом
.desc:          ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jr nc,.shown
                NTAIL A_094C2                   ; CALL $1BCC переводом
.shown:         ld a,(#4000+#2FC4)
                or a
                jr z,.count
                NTAIL A_09478                   ; JMP $9078
.count:         ld l,(ix+#30)
                ld h,(ix+#31)
                dec hl
                ld (ix+#30),l
                ld (ix+#31),h                   ; DEC WORD [bp+30]
                ld a,h
                or l
                jp nz,NRet
                ld a,(ix+#21)
                ld (ix+#20),a
                ld (V_AX),a                     ; AL = [bp+21]
                ld (ix+0),#86
                ld (ix+1),#8F                   ; [bp] = #8F86
                jp NRet
.translated:    ld a,$$K_094AE
                ld hl,K_094AE
                jp FARJP

; ROM $00663 (IP $0263) — начало цикла списка объектов IRQ0 (враги): MOV BP,#540 и цикл ($0266 — ядро KERNEL_OBJECTS_B).
; Кэш столкновений: COLL_STATE = 1 — крайние X записей соберёт первая цепочка урона в этом цикле (CollBuild).
N_0263:         ld a,1
                ld (COLL_STATE),a
                ld hl,#540
                ld (V_BP),hl
                jp KERNEL_OBJECTS_B

; ROM $00677 (IP $0277) — цикл списка кончился: кэш столкновений недействителен (COLL_STATE = 0), дальше — перевод с
; того же места (CALL $0653).
N_0277:         xor a
                ld (COLL_STATE),a
                ld a,$$K_00677
                ld hl,K_00677
                jp FARJP


; --- обработчики прерываний (VDAC2+ 2026-09-26, скорость: переведённый верх IRQ0 и IRQ2 — ≈0,6 % тактов каждого шага) --
; ROM $004FE (IP $00FE) — вход кадрового прерывания до переноса палитр: PUSH DS, PUSH ES, PUSHA; DS = #4000, ES = #1000;
; [2F18] = 1 (вход не вложен), IF = 1; INC [2EB4]; OUT 4 (копия памяти спрайтов); ввод: [2040] = ¬IN0, [2042] = ¬IN1,
; [2044] = ¬DSW; $0443 — прокрутка (порты #80…#86: [2EC5], [2EC1] или при [2F1A] ≠ 0 — [2EBE], 0; затем [2ECD], [2EC9]);
; $041B — растр (порт 6: [2EBC] + бит 0 [2F1A]) и прокрутка второй половины кадра [2EB8], [2EBA] (при [2F1A] = 0 —
; [2EBE], 0, иначе [2EC5], [2EC1]); CALL $525A — перенос палитр (ядро второй страницы хоста), возврат — в $0153
; (N_0153). У CALL регистры — как у ROM (AX, BX — от $041B), флаги — от TEST [2F1A],#FF или XOR BX,BX $041B (CF = AF =
; OF = 0). Условия (иначе перевод с входа): SS = #4000 (стек V30 — стек Z80), [308E] = 0 (иначе ROM уходит на экран
; диагностики), бит 0 [2F18] = 0 (иначе вложенный вход $0299).
N_00FE:         ld hl,(V_SS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(#4000+#308E)
                ld a,h
                or l
                jp nz,.translated
                ld a,(#4000+#2F18)
                rra
                jp c,.translated
                xor a
                ld (COLL_STATE),a               ; кэш столкновений: вне цикла списка (на случай ухода из него переводом)
                ld hl,(V_DS)
                push hl                         ; PUSH DS
                ld hl,(V_ES)
                push hl                         ; PUSH ES
                ld hl,#C000
                add hl,sp
                ex de,hl                        ; DE — SP перед PUSHA
                ld hl,(V_AX)
                push hl
                ld hl,(V_CX)
                push hl
                ld hl,(V_DX)
                push hl
                ld hl,(V_BX)
                push hl
                push de
                ld hl,(V_BP)
                push hl
                ld hl,(V_SI)
                push hl
                ld hl,(V_DI)
                push hl                         ; PUSHA
                ld hl,#4000
                ld (V_DS),hl
                ld hl,#1000
                ld (V_ES),hl
                ld a,1
                ld (#4000+#2F18),a              ; AND [2F18],1 (бит 0 был 0); MOV [2F18],1
                ld hl,V_FL+1
                set 1,(hl)                      ; STI
                ld hl,(#4000+#2EB4)
                inc hl
                ld (#4000+#2EB4),hl             ; INC WORD [2EB4]
                call SPRITE_DMA                 ; OUT 4,AX
                ld hl,(IN0)
                ld a,l
                cpl
                ld l,a
                ld a,h
                cpl
                ld h,a
                ld (#4000+#2040),hl             ; [2040] = ¬IN0
                ld hl,(IN1)
                ld a,l
                cpl
                ld l,a
                ld a,h
                cpl
                ld h,a
                ld (#4000+#2042),hl             ; [2042] = ¬IN1
                ld hl,(DSW)
                ld a,l
                cpl
                ld l,a
                ld a,h
                cpl
                ld h,a
                ld (#4000+#2044),hl             ; [2044] = ¬DSW
                ld de,(#4000+#2EC1)             ; $0443: BX
                ld hl,(#4000+#2EC5)             ; AX
                ld a,(#4000+#2F1A)
                or a
                jr z,.scroll
                ld de,0
                ld hl,(#4000+#2EBE)
.scroll:        ld (SCROLL_Y0),hl               ; OUT #80,AX
                ld (SCROLL_X0),de               ; OUT #82 (AX = BX)
                ld hl,(#4000+#2ECD)
                ld (SCROLL_Y1),hl               ; OUT #84
                ld hl,(#4000+#2EC9)
                ld (SCROLL_X1),hl               ; OUT #86
                ld hl,(#4000+#2EBC)             ; $041B
                ld a,(#4000+#2F1A)
                rra
                jr nc,.raster
                inc hl
.raster:        ld a,h
                and 1
                ld h,a
                ld (RASTER_RAW),hl              ; OUT 6,AX (9 бит)
                ld de,(#4000+#2EC1)
                ld hl,(#4000+#2EC5)
                ld a,(#4000+#2F1A)
                or a
                jr nz,.half
                ld de,0
                ld hl,(#4000+#2EBE)
.half:          ld (#4000+#2EB8),hl
                ld (#4000+#2EBA),de
                ld (V_AX),hl
                ld (V_BX),de
                ld a,(#4000+#2F1A)              ; флаги: TEST [2F1A] (≠ 0) или XOR BX,BX (= 0)
                ld e,a
                or a
                ld a,#40
                jr z,.flags
                ld a,e
                and #80
.flags:         call STORE_LOW_PE               ; + PF по E, бит 1
                ld hl,V_FL+1
                res 3,(hl)                      ; OF = 0
                ld hl,#0153
                push hl                         ; CALL $525A: адрес возврата
                ld de,#525A
                jp DISPATCH
.translated:    ld a,$$K_004FE
                ld hl,K_004FE
                jp FARJP

; ROM $00553 (IP $0153) — продолжение IRQ0 за переносом палитр до вызова директора: $05F5 (при ([2EB4] & #F) = 0:
; [2F19] = 0, а при бите 4 — ещё и убывание [2F00], [2F01] до нуля с битами 0, 1 в [2F19]), $061E ([2F1A], порт 2),
; $055E (монеты: [2F06] = 2 при [2F0C] = 0; история [2F04] — два RCL с битами 2 и 3 [2042]; [2F05] = #1C; CH — три RCR
; и два RCR с CF от CMP истории, CL = 3), $0320 (команда звука из очереди #2020 в порт 0 по условиям ROM, [2F30] = 0),
; $051F ([2F1C] = 0, CF = 0), ввод игрока ($01B9: [2F21…2F26], [2050], [2052]), INC [2EB6] (каждые 512 кадров — $EDD9),
; [2EFC] = #C0, BP = 0 и CALL [0] (директор; адрес возврата $0247 — в стек V30). У CALL: AX = IN1 & #20, BX = [2042],
; CX = CH·256 + 3, DX, SI, DI — как после $525A; флаги — от AND AX,#20 (все 0, кроме бита 1). Редкие пути — перевод с
; входа (до него ничего не изменено): DS ≠ #4000, ES ≠ #1000, включён сервис (бит 13 [2044]), демо аттракта ([0] =
; $0A8B), бит 7 или 5 IN1 = 0 (ROM ждёт или уходит на тест), индекс очереди звука ≥ #20, событие монет $055E (зачёт
; монеты — история & #55 = 5, сервисная кнопка — бит 4 [2042]).
N_0153:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jp nz,.translated
                ld a,(#4000+#2045)
                and #20
                jp nz,.translated               ; $051F: сервис
                ld hl,(#4000+0)
                ld de,#0A8B
                or a
                sbc hl,de
                jp z,.translated                ; $0167: демо аттракта
                ld a,(IN1)
                and #A0
                cp #A0
                jp nz,.translated               ; $0228, $022F
                ld a,(#4000+#2EDD)
                or a
                jp nz,.translated
                ld a,(#4000+#2EDC)
                cp #20
                jp nc,.translated               ; индекс очереди звука ≥ #20
                ld a,(#4000+#2042)
                ld c,a                          ; C — b7…b0 (CH до сдвигов $055E)
                bit 4,c
                jp nz,.translated               ; сервисная кнопка
                call .history                   ; B = H1, A = H2
                and #55
                cp 5
                jp z,.translated                ; зачёт монеты (второй CMP)
                ld a,b
                and #55
                cp 5
                jp z,.translated                ; зачёт монеты (первый CMP)
                ; --- $05F5
                ld hl,(#4000+#2EB4)
                ld a,l
                and #0F
                jr nz,.s5f5done                 ; TEST AX,#F ≠ 0 — RET
                ld b,a                          ; AL = 0
                bit 4,l
                jr z,.s5f5store
                ld hl,#4000+#2F00
                ld a,(hl)
                or a
                jr z,.no0
                dec (hl)
                set 0,b
.no0:           inc hl
                ld a,(hl)
                or a
                jr z,.s5f5store
                dec (hl)
                set 1,b
.s5f5store:     ld a,b
                ld (#4000+#2F19),a
.s5f5done:      ; --- $061E
                ld a,(#4000+#2045)
                and 1
                ld e,a                          ; AH = бит 8 ¬DSW
                ld a,(#4000+#2F1B)
                and 1
                ld a,(#4000+#2F20)
                jr z,.v1
                xor a
.v1:            ld c,a                          ; CL
                xor e
                and 1
                ld (#4000+#2F1A),a
                ld a,c
                add a,a
                add a,a                         ; SHL CL,2
                ld c,a
                ld a,(#4000+#2F19)
                or c
                ld c,a
                ld a,(#4000+#2F1E)
                or a
                ld a,c
                jr z,.v2
                or 8
.v2:            or #10
                and #1F                         ; OUT 2,AX
                ld c,a
                and 4
                ld (VID_FLIP),a
                ld a,c
                and 8
                ld (VID_OFF),a
                ; --- $055E
                ld hl,(#4000+#2F0C)
                ld a,h
                or l
                jr nz,.coins
                ld a,2
                ld (#4000+#2F06),a
.coins:         ld a,(#4000+#2042)
                ld c,a
                call .history
                ld (#4000+#2F04),a              ; [2F04] = H2
                and #55
                cp 5
                ld a,0
                rla
                ld d,a                          ; y — CF второго CMP
                ld a,b
                and #55
                cp 5
                ld a,0
                rla
                ld e,a                          ; x — CF первого CMP
                ld a,#1C
                ld (#4000+#2F05),a              ; бит 4 = 0: JAE — [2F05] = #1C
                ld a,c                          ; CH = y x b1 b0 0 b7 b6 b5
                rlca
                rlca
                rlca
                and #07
                ld b,a                          ; b7 b6 b5 → биты 2…0
                ld a,c
                and #03
                rlca
                rlca
                rlca
                rlca
                or b                            ; b1 b0 → биты 5, 4
                ld b,a
                ld a,e
                rrca
                rrca
                or b                            ; x → бит 6
                ld b,a
                ld a,d
                rrca
                or b                            ; y → бит 7
                ld (V_CX+1),a
                ld a,3
                ld (V_CX),a                     ; CL = 3
                ; --- $0320: звук из очереди
                ld hl,(#4000+#2EDC)
                ld de,(#4000+#2EDE)
                or a
                sbc hl,de
                jr z,.sndDone
                ld a,(#4000+#2EDC)
                ld l,a
                inc a
                and #1F
                ld (#4000+#2EDC),a
                xor a
                ld (#4000+#2EDD),a              ; [2EDC] = (индекс + 1) & #1F
                ld h,0
                ld de,#4000+#2020
                add hl,de
                ld e,(hl)                       ; команда [индекс + #2020]
                ld hl,N_SNDDIR
                ld b,6
.dir:           ld a,(#4000+0)
                cp (hl)
                inc hl
                jr nz,.dirNext
                ld a,(#4000+1)
                cp (hl)
                jr z,.send                      ; директор из списка ROM — команда уходит всегда
.dirNext:       inc hl
                djnz .dir
                ld a,e
                or a
                jr z,.send
                cp #63
                jr z,.send
                ld a,(#4000+#2F2B)
                and 4
                jr z,.sndDone
                ld a,e
                cp #22
                jr c,.sndDone
.send:          ld d,0
                ld hl,0
                ld a,2
                call PORT_OUT                   ; OUT 0,AX (AH = 0)
.sndDone:       xor a
                ld (#4000+#2F30),a
                ld (#4000+#2F1C),a              ; $051F: [2F1C] = 0
                ; --- $01B9: ввод игрока
                ld hl,(#4000+#2040)
                ld a,(#4000+#2F1B)
                or a
                ld a,l
                jr nz,.in1p
                ld a,(#4000+#2F20)
                or a
                ld a,l
                jr z,.in1p
                ld a,h                          ; второй игрок: AL = AH
.in1p:          ld (#4000+#2F21),a
                ld c,a                          ; BL — текущие
                ld hl,#4000+#2F22
                ld e,(hl)                       ; прежние
                xor e
                ld d,a                          ; прежние ^ текущие
                and e
                ld (#4000+#2F24),a              ; отпущенные
                ld a,d
                and c
                ld (#4000+#2F23),a              ; нажатые
                ld (hl),c                       ; [2F22] = текущие
                ld hl,(#4000+#2042)
                ld (V_BX),hl                    ; BX = [2042]
                ld de,(#4000+#2050)
                ld a,e
                xor l
                and l
                ld (#4000+#2052),a
                ld a,d
                xor h
                and h
                ld (#4000+#2053),a              ; [2052] = ([2050] ^ BX) & BX
                ld (#4000+#2050),hl
                xor a
                ld (#4000+#2F26),a
                ld a,(#4000+#2F21)
                and #0F
                ld hl,#4000+#2F25
                cp (hl)
                jr z,.dirSame
                ld (hl),a
                ld (#4000+#2F26),a
.dirSame:       ld hl,(#4000+#2EB6)
                inc hl
                ld (#4000+#2EB6),hl             ; INC WORD [2EB6]
                ld a,h
                and 1
                or l
                jr nz,.noSeed
                ld a,5
                ld (#4000+#2F28),a              ; $EDD9
                ld a,1
                ld (#4000+#2F29),a
                ld a,3
                ld (#4000+#2F2A),a
.noSeed:        ld a,(IN1)
                and #20
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; IN AX,2; AND AX,#20
                ld a,#02
                ld (V_FL),a                     ; флаги AND (результат #20): CF = PF = AF = ZF = SF = 0
                ld hl,V_FL+1
                res 3,(hl)                      ; OF = 0
                ld hl,#C0
                ld (#4000+#2EFC),hl
                ld hl,0
                ld (V_BP),hl
                ld hl,#0247
                push hl                         ; CALL [bp]: адрес возврата
                ld de,(#4000+0)
                jp DISPATCH
.translated:    ld a,$$K_00553
                ld hl,K_00553
                jp FARJP
; История монет $055E: C — ¬IN1 (младший байт [2042]); B = H1 = [2F04]·2 + бит 2 C (RCR CH,3 → RCL), A = H2 =
; H1·2 + бит 3 C (RCR CH,1 → RCL). Портит F.
.history:       ld a,(#4000+#2F04)
                bit 2,c
                scf
                jr nz,.h1
                or a
.h1:            rla
                ld b,a
                bit 3,c
                scf
                jr nz,.h2
                or a
.h2:            rla
                ret

; ROM $006EE (IP $02EE) — растровое прерывание: прокрутка слоя 0 второй половины кадра — порт #80 = [2EB8], #82 = [2EBA];
; IRET (IP, CS, FLAGS — как SET_FLAGS). PUSH AX / PUSH DS и их POP оставляют байты ниже SP (мусор стека, сверка его не
; сравнивает), STI перекрывает FLAGS со стека. Условие (иначе перевод с входа): SS = #4000.
N_02EE:         ld hl,(V_SS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(#4000+#2EB8)
                ld (SCROLL_Y0),hl
                ld hl,(#4000+#2EBA)
                ld (SCROLL_X0),hl
                pop de                          ; IRET: IP
                pop hl
                ld (V_CS),hl                    ; CS
                pop hl                          ; FLAGS
                ld a,l
                and #D5
                or #02
                ld (V_FL),a
                ld a,h
                and #7F
                ld (V_FL+1),a
                jp DISPATCH
.translated:    ld a,$$K_006EE
                ld hl,K_006EE
                jp FARJP

N_SNDDIR        DW #10FA, #160F, #1660, #17D7, #132A, #136E ; $0320: директоры, у которых команда звука уходит всегда

; --- вход в прерывание (VDAC2+ 2026-09-26, скорость: вход резидента — ≈1,3 % тактов шага, два IRQ на шаг) --------------
; Резидент (IRQ) отображает эту страницу в W3 и переходит сюда: A = номер IRQ (0 — кадровое, 2 — растровое). Как
; RTypeM72Machine.interrupt: при маске — возврат в драйвер; иначе в стек V30 FLAGS, CS, IP; во FLAGS снимаются IF и TF;
; CS:IP — из вектора PIC_BASE + номер; исполнение до точки простоя (IDLE_EXIT возвращает в драйвер).
; Вектор — из таблицы векторов ROM (линейные 0…#3FF: страница V30 0 — ROM, программа в неё не пишет): кэш на номер IRQ
; (8 записей по 8 байт: номер вектора, 0 — занята (#FF — пусто), IP, CS), промах — чтение RW_LIN0 и запись в кэш. Прежний
; вход отображал для чтения вектора страницу 0 в W2 — теперь W2 остаётся как была (W2_PAGE ей соответствует).
; Стек: SS = #4000 и 6 ≤ SP ≤ #4000 — три слова кладёт стек Z80, поставленный на стек V30 (окно W1 — рабочее ОЗУ,
; пометок видеопамяти у него нет): те же байты, что пишут три PUSHW; иначе — PUSHW.
IrqEnter:       ld c,a                          ; C — номер IRQ
                ld b,a
                ld a,(PIC_MASK)
                inc b
.shift:         dec b
                jr z,.bit
                rrca
                jr .shift
.bit:           rrca
                ret c                           ; IRQ замаскирован
.lookup:        ld a,c
                and 7
                add a,a
                add a,a
                add a,a
                add a,low IRQ_VECTORS
                ld l,a
                adc a,high IRQ_VECTORS
                sub l
                ld h,a                          ; HL → запись кэша номера IRQ
                ld a,(PIC_BASE)
                add a,c                         ; номер вектора
                cp (hl)
                jp nz,.fill
                inc hl
                ld a,(hl)
                or a
                jp nz,.fill1                    ; запись пуста
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — IP вектора
                inc hl
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — CS вектора
                ld hl,(V_SS)
                ld a,h
                xor #40
                or l
                jr nz,.pushSlow                 ; SS ≠ #4000
                ld hl,(V_SP)
                ld a,h
                or a
                jr nz,.spHigh
                ld a,l
                cp 6
                jr c,.pushSlow                  ; SP < 6
                jr .spOk
.spHigh:        cp #40
                jr c,.spOk                      ; #0100…#3FFF
                jr nz,.pushSlow                 ; SP > #40FF
                ld a,l
                or a
                jr nz,.pushSlow                 ; SP = #4001…#40FF
.spOk:          ld (DRIVER_SP),sp
                ld a,h
                add a,#40
                ld h,a                          ; #4000 + SP (SP ≤ #4000 — не выше #8000)
                ld sp,hl
                ld hl,(V_FL)
                push hl                         ; [SP − 2] = FLAGS
                ld hl,(V_CS)
                push hl                         ; [SP − 4] = CS
                ld hl,(V_IP)
                push hl                         ; [SP − 6] = IP
                ld hl,#C000
                add hl,sp
                ld (V_SP),hl                    ; SP − 6
.pushed:        ld (V_IP),de
                ld (V_CS),bc
                ld hl,V_FL+1
                ld a,(hl)
                and #FC
                ld (hl),a                       ; IF = TF = 0
                jp DISPATCH                     ; DE — IP; стек Z80 — стек V30
.pushSlow:      push de
                push bc
                ld de,(V_FL)
                call PUSHW
                ld de,(V_CS)
                call PUSHW
                ld de,(V_IP)
                call PUSHW
                pop bc
                pop de
                ld (DRIVER_SP),sp
                ld hl,(V_SP)
                ld a,h
                add a,#40
                ld h,a                          ; SP + #4000 (перенос за #FFFF отбрасывается)
                ld sp,hl
                jr .pushed
.fill1:         dec hl
.fill:          ld (IRQ_VECP),hl
                ld a,(PIC_BASE)
                add a,c
                ld (IRQ_VECNUM),a               ; номер вектора
                push bc                         ; C — номер IRQ
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl                       ; линейный адрес вектора (сегмент 0)
                push hl
                call RW_LIN0
                ld (IRQ_VECIP),de
                pop hl
                inc hl
                inc hl
                call RW_LIN0                    ; DE — CS
                pop bc
                ld hl,(IRQ_VECP)
                ld a,(IRQ_VECNUM)
                ld (hl),a                       ; ключ — номер вектора
                inc hl
                ld (hl),0                       ; запись занята
                inc hl
                ld a,(IRQ_VECIP)
                ld (hl),a
                inc hl
                ld a,(IRQ_VECIP+1)
                ld (hl),a
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                jp .lookup                      ; теперь — попадание

IRQ_VECNUM      DB 0
IRQ_VECP        DW 0
IRQ_VECIP       DW 0
IRQ_VECTORS     DS 64,#FF                       ; 8 записей по 8 байт: номер вектора, 0 (#FF — пусто), IP, CS, 0, 0
