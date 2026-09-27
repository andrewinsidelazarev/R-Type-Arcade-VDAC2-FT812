; VDAC2+: заливки VRAM, перенос палитр и менеджер палитр — во второй странице хоста (HOST2_PAGE), с 2026-09-25
; (скорость, партия 3): нативной странице нужно место под обработчики объектов. Входы — NATIVE с диспетчеризацией в
; эту страницу (codegen.NATIVE_HOST2); окно W3 эти процедуры не читают — их страница лишь место кода, данные — в
; резиденте (PAL_*, PEN_*, флаги) и в своих переменных VF_*. Прежде (23.09) — нативная страница, до того — резидент.

; --- заливка VRAM ----------------------------------------------------------------------------------------------
; VDAC2+: перенесена из резидента (v30z80_kernels.asm) в нативную страницу (23.09) — место резидента ушло под дозапись
; кольца фона. Окно W3 заливка не трогает (VRAM — окно W2, пометки и флаги — резидент), вход — через NATIVE.
; ROM $EC65 (IP $E865): ES = #D000, DI = #200, CX = #F80; $EC83 (IP $E883): ES = #D000, DI = 0, CX = #1000; $ECA0 (IP
; $E8A0): ES = #D800, DI = 0, CX = #1000 — PUSH ES; слова ES:[DI] = #0FA0 и ES:[DI+2] = 0 с шагом 4, CX проходов; POP ES;
; RET. После: AX = 0, CX = 0, DI — за последним словом, ES прежний, флаги — ADD DI,4 последнего прохода (вызывающий
; неизвестен — флаги живы), ниже SP — слово ES (PUSH ROM). Перевод платил флагами на каждом из ≈4000 проходов (два таких
; кадра старта игры — по ≈6 млн тактов); здесь заливка стеком (SP — конец диапазона в окне W2, PUSH #0000 и PUSH #0FA0
; на проход: 2 байта за 11 тактов; прерывания в игре запрещены), пометки для адаптера FT812 — сразу таблицами групп и
; строк (то же, что VIDEO_MARK каждого байта диапазона), флаги — один раз.
KERNEL_VRAM_FILL_A200:
                ld a,#34
                ld hl,#0200
                ld bc,#0F80
                jr VramFill
KERNEL_VRAM_FILL_A:
                ld a,#34
                ld hl,0
                ld bc,#1000
                jr VramFill
KERNEL_VRAM_FILL_B:
                ld a,#36
                ld hl,0
                ld bc,#1000
; A — страница V30 слоя VRAM, HL — начальный DI, BC — CX (1…#1000; DI + CX·4 ≤ #4000 — у всех трёх мест так).
VramFill:       ld (VF_PAGE),a
                ld (VF_DI),hl
                ld (VF_CX),bc
                add hl,bc
                add hl,bc
                add hl,bc
                add hl,bc
                ld (VF_END),hl                  ; DI после цикла
                ld hl,(V_ES)
                push hl
                pop hl                          ; PUSH ES / POP ES ROM: слово ES ниже SP
                ld hl,0
                ld (V_AX),hl                    ; XOR AX,AX
                ld (V_CX),hl                    ; LOOP до нуля
                ld a,(VF_PAGE)
                ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ld (V30_SP_SAVE),sp
                ld hl,(VF_END)
                set 7,h                         ; HL → ES:DI после цикла в окне W2 (#8200…#C000)
                ld sp,hl
                ld bc,(VF_CX)
                ld a,c
                ld c,b                          ; C — кругов по 256 проходов
                ld b,a                          ; B — проходов первого круга (0 — 256)
                or a
                jr z,.words
                inc c                           ; неполный первый круг
.words:         ld hl,#0FA0
                ld de,0
.fill:          push de                         ; ES:[DI+2] = 0
                push hl                         ; ES:[DI] = #0FA0 (от последнего прохода к первому)
                djnz .fill
                dec c
                jr nz,.fill
                ld sp,HELPER_TOP
                ; пометки: группы (смещение >> 5) и строки (старший байт смещения) диапазона — #FF
                ld hl,VRAM_DIRTY0
                ld a,(VF_PAGE)
                cp #34
                jr z,.table
                ld hl,VRAM_DIRTY1
.table:         ld (VF_TABLE),hl
                ld hl,(VF_DI)
                call VfShr5
                ex de,hl                        ; DE — первая группа
                ld hl,(VF_END)
                dec hl
                call VfShr5                     ; HL — последняя группа
                or a
                sbc hl,de
                ld b,h
                ld c,l                          ; BC — групп − 1
                ld hl,(VF_TABLE)
                add hl,de
                call VfMarks
                ld hl,(VF_END)
                dec hl
                ld a,h                          ; последняя строка
                ld hl,(VF_DI)
                ld e,h                          ; первая строка
                ld d,0
                sub e
                ld c,a
                ld b,d                          ; BC — строк − 1
                ld hl,(VF_TABLE)
                inc h
                inc h                           ; сводка строк — таблица + 512
                add hl,de
                call VfMarks
                ld a,1
                ld (VIDEO_DIRTY),a
                ld hl,(VF_END)
                ld de,-4
                add hl,de                       ; DI последнего прохода
                ld de,#0004                     ; ADD DI,4 — как перевод: FLG_X, FLG_R, FLG_AR16
                ld a,l
                xor e
                ld (FLG_X),a
                or a
                adc hl,de
                ld (FLG_R),hl
                ld (V_DI),hl
                push af
                pop bc
                call FLG_AR16
                ld sp,(V30_SP_SAVE)
                pop de                          ; RET V30
                jp DISPATCH
; HL = HL >> 5. Портит F.
VfShr5:         srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                ret
; Байты HL…HL+BC = #FF (BC — число байт − 1). Портит AF, BC, DE, HL.
VfMarks:        ld (hl),#FF
                ld a,b
                or c
                ret z
                ld d,h
                ld e,l
                inc de
                ldir
                ret
VF_PAGE         DB 0
VF_DI           DW 0
VF_CX           DW 0
VF_END          DW 0
VF_TABLE        DW 0
                ASSERT VRAM_ROWS0 == VRAM_DIRTY0+512 && VRAM_ROWS1 == VRAM_DIRTY1+512

; --- перенос палитр --------------------------------------------------------------------------------------------
; VDAC2+: перенесён из резидента (v30z80_kernels.asm) в нативную страницу (23.09) — место резидента ушло под дозапись
; кольца фона. Окно W3 перенос не трогает (записи — окно W1, память палитр — W2), вход — через NATIVE, раз в кадр.
; ROM $565A (IP $525A, вызов из IRQ0 $0550): у записи менеджера палитр (группы $2D34 и $2DF4 по 12 байт) с флагом
; переноса [+6] ≠ 0 (слово) — флаг = 0 и 48 слов плоскостей R, G, B слота (#2134 + слот·32, +#200, +#400; группа 1 —
; #2734…) в память палитр C800:слот·32 (+#400, +#800; группа 1 — CC00) — REP MOVSW по 16 слов при DF = 0. Слова
; пишутся только несовпадающие (память та же), вместо пометок всей палитры (VIDEO_MARK) — биты изменённых перьев
; PEN_DIRTY0/1 (слово на палитру) для адаптера FT812. Слот, равный плоскостям с прошлого переноса (PAL_SYNC, см.
; менеджер палитр), не сверяется; у остального сверяются только перья из PEN_CHG. На выходе, как у ROM: AX = #CC00, BP = #2EBA, SI = #2934,
; DI = #200, CX = 0 (DS, ES восстановлены, BX, DX прежние); флаги после RET не живут. DF = 1 — обычный перевод.
KERNEL_PAL_TRANSFER:
                ld a,(V_FL+1)
                and 4
                jr nz,.translated
                ld hl,#4000+#2D3A
                ld de,#4000+#2134
                ld bc,PAL_SYNC
                ld (PT_SYNC),bc
                ld bc,PEN_DIRTY0
                ld a,PALETTE_V30_PAGE0
                call PalTransferBank
                ld hl,#4000+#2DFA
                ld de,#4000+#2734
                ld bc,PAL_SYNC+16
                ld (PT_SYNC),bc
                ld bc,PEN_DIRTY1
                ld a,PALETTE_V30_PAGE0+1
                call PalTransferBank
                ld hl,#CC00
                ld (V_AX),hl
                ld hl,#2EBA
                ld (V_BP),hl
                ld hl,#2934
                ld (V_SI),hl
                ld hl,#0200
                ld (V_DI),hl
                ld hl,0
                ld (V_CX),hl
                pop de                          ; RET V30
                jp DISPATCH
.translated:    ld a,$$K_0565A
                ld hl,K_0565A
                jp FARJP

; Группа записей: A — страница V30 памяти палитр, HL → флаг записи 0 (#4000 + BP, окно W1), DE → плоскость R слота 0
; (W1), BC — пометки перьев группы, PT_SYNC — PAL_SYNC группы. Запись без флага — только проверка слова. Портит всё.
PalTransferBank:
                ld (W2_PAGE),a
                ld (PT_PLANES),de
                ld (PT_MARKS),bc
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ld de,12
                ld b,16
.record:        ld a,(hl)
                inc hl
                or (hl)
                dec hl
                jr nz,.flag                     ; [bp+6] ≠ 0: перенести
.next:          add hl,de
                djnz .record
                ret
.flag:          push bc
                push hl
                push hl
                pop ix                          ; IX → флаг
                ld a,16
                sub b                           ; A — слот
                call PalTransferSlot
                pop hl
                pop bc
                ld de,12
                jr .next

; Запись с флагом: флаг = 0. Слот памяти палитр уже равен плоскостям (PAL_SYNC) — больше ничего (сверка слов не нашла
; бы отличий); иначе PAL_SYNC = 1, у перьев из PEN_CHG записи (r = группа·16 + слот) слова R, G, B — в память палитр
; (несовпадающие), биты перьев — в пометки слота; PEN_CHG = 0. Перья вне PEN_CHG с прошлого переноса не менялись ни в
; плоскостях, ни в памяти палитр — их слова совпадают. Порядок записи (по перьям, а не по плоскостям) итог не меняет:
; плоскости и память палитр не пересекаются. A — слот, IX → флаг. Портит всё, кроме IX.
PalTransferSlot:
                ld (ix+0),0
                ld (ix+1),0                     ; [bp] = 0
                ld e,a
                ld d,0
                ld hl,(PT_SYNC)
                add hl,de
                ld a,(hl)
                or a
                ret nz                          ; слот уже равен плоскостям
                ld (hl),1
                ld bc,-PAL_SYNC
                add hl,bc                       ; HL = r
                add hl,hl
                ld bc,PEN_CHG
                add hl,bc                       ; → PEN_CHG записи
                ld c,(hl)
                xor a
                ld (hl),a
                inc hl
                ld b,(hl)
                ld (hl),a                       ; BC — перья к сверке; PEN_CHG = 0
                ld a,b
                or c
                ret z
                push bc
                ld hl,(PT_MARKS)
                add hl,de
                add hl,de
                ld (PT_MARK),hl                 ; слово пометок перьев слота
                ex de,hl                        ; HL = слот
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; слот·32
                push hl
                ld de,#8000
                add hl,de
                ex de,hl                        ; DE → R пера 0 слота в памяти палитр (окно W2)
                pop hl
                ld bc,(PT_PLANES)
                add hl,bc                       ; HL → R пера 0 слота в плоскостях (окно W1)
                exx
                pop bc                          ; BC' — перья к сверке (сдвиг вправо, бит 0 — текущее перо)
                exx
                ld bc,0
                ld (PT_MASK),bc
                inc c                           ; BC = 1 — бит пера 0
.pen:           exx
                srl b
                rr c                            ; CF — перо к сверке
                exx
                call c,PtPen
                exx
                ld a,b
                or c
                exx
                jr z,.marks                     ; дальше перьев к сверке нет
                inc hl
                inc hl
                inc de
                inc de                          ; следующее перо
                sla c
                rl b
                jr .pen
.marks:         ld hl,(PT_MASK)
                ld a,h
                or l
                ret z
                ex de,hl                        ; DE — изменённые перья
                ld hl,(PT_MARK)
                ld a,(hl)
                or e
                ld (hl),a
                inc hl
                ld a,(hl)
                or d
                ld (hl),a
                ld a,1
                ld (VIDEO_DIRTY),a
                ret

; Перо: слова R, G, B (HL → R в плоскостях, DE → R в памяти палитр; G и B — на #200 и #400 дальше в плоскостях, на #400
; и #800 — в памяти палитр) — несовпадающие записать, перо BC — в PT_MASK. Сохраняет BC, DE, HL.
PtPen:          push hl
                push de
                call PtWord                     ; R
                inc h
                inc h
                inc d
                inc d
                inc d
                inc d
                call PtWord                     ; G
                inc h
                inc h
                inc d
                inc d
                inc d
                inc d
                call PtWord                     ; B
                pop de
                pop hl
                ret

; Слово (HL) → (DE): не совпало — записать, перо BC — в PT_MASK. Сохраняет BC, DE, HL.
PtWord:         ld a,(de)
                cp (hl)
                jr nz,.copy
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                dec hl
                dec de
                ret z
.copy:          ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a
                dec hl
                dec de
                push hl
                ld hl,(PT_MASK)
                ld a,l
                or c
                ld l,a
                ld a,h
                or b
                ld h,a
                ld (PT_MASK),hl
                pop hl
                ret

PT_MARKS        DW 0                    ; пометки перьев группы
PT_MARK         DW 0                    ; слово пометок слота
PT_MASK         DW 0
PT_PLANES       DW 0                    ; плоскость R слота 0 группы
PT_SYNC         DW 0                    ; PAL_SYNC группы

; --- менеджер палитр ------------------------------------------------------------------------------
; VDAC2+: перенесён из резидента (v30z80_kernels.asm) в нативную страницу — место резидента ушло под кольцо фона.
; Окно W3 менеджер не трогает (записи — W1, цели — W2), данные PAL_* — в резиденте; вход — через NATIVE, раз в кадр.
; ROM $5701 (IP $5301), Docs/RTYPE_WORLD_ROM_MAP.md «Полный palette manager»: вызывается из обработчика
; IRQ0 ($068C), за ним — POPA, POP ES, POP DS, IRET: регистры и флаги на выходе не живут. Две группы по
; 16 записей по 12 байт ($2D34 и $2DF4, SS = DS = #4000 — окно W1): +0 бит 15 — активна, младший байт —
; тип палитры-цели; +2 — число изменённых компонент; +4 — 0 мгновенная загрузка, иначе постепенная;
; +6 — признак переноса в память палитр; +8 — маска кадров; +A — порог. Плоскости R/G/B записи —
; $2134/$2314/$24F4 и $2734/$2914/$2AF4 (+слот·32), цели — байты ROM 3B00:тип·48 и 3B00:$2400+тип·48
; (таблицы PAL_TARGET_PAGE0/1 со смещения тип·48, v30z80_build.py).
; Кэш записей r = группа·16 + слот (память V30 — та же, что у ROM): PAL_EQ[r] = 1 и PAL_KIND[r] — все 48 компонент
; плоскостей равны целям этого типа; PAL_SYNC[r] = 1 — слот памяти палитр равен плоскостям записи. Плоскости пишут
; только эти ядра (эталон: писатели $2134…$2D33 — $5797, $57A1, $57F2, $5849, $5853, $58A8 менеджера), цели — ROM;
; память палитр — ядро переноса и переведённый код (VIDEO_MARK снимает PAL_SYNC слота). Новая машина восстанавливает
; резидент (нули). Совпавшая запись того же типа: постепенная загрузка ничего не меняет (цикл компонент не нужен),
; мгновенная пишет те же значения; перенос совпадающего слота ничего не пишет.
; Маски перьев (слово на запись, бит p — перо p; v30z80_runtime.asm, область #3800): PEN_EQ[r] — перья, все три
; компоненты которых равны целям типа PAL_KIND[r] (у пера из маски цикл компонент постепенной загрузки ничего не меняет —
; его пропускают); PEN_CHG[r] — перья, плоскости которых могли разойтись с памятью палитр после прошлого переноса
; (остальные перья перенос не сверяет: с прошлого переноса их не меняли ни менеджер, ни запись мимо ядра переноса —
; такая запись ставит PEN_CHG = #FFFF). На замер 2026-09-17 (Stage 1, неуязвимость, автоогонь) у постепенной записи в
; среднем 14,5 из 16 перьев уже равны целям, перенос меняет 1…2 пера.
KERNEL_PALETTES:
                ld (V30_SP_SAVE),sp
                ld sp,HELPER_TOP
                ld hl,#4000+#2D34
                ld de,#4000+#2134
                ld bc,PAL_EQ
                ld a,PAL_TARGET_PAGE0
                call PalBank
                ld hl,#4000+#2DF4
                ld de,#4000+#2734
                ld bc,PAL_EQ+16
                ld a,PAL_TARGET_PAGE1
                call PalBank
                ld a,#FF
                ld (W2_PAGE),a                  ; окно W2 занято таблицей целей
                ld sp,(V30_SP_SAVE)
                pop de                          ; RET V30
                jp DISPATCH

; Группа: A — страница целей, HL — первая запись, DE — плоскость R слота 0, BC — кэш группы (PAL_EQ + группа·16).
; Как цикл $570A/$5739: активная запись с режимом 0 — мгновенная загрузка ($57CF/$5881), иначе постепенная
; ($5760/$580E). Неактивная запись — только проверка бита. Портит всё.
PalBank:        ld (PAL_PLANES),de
                ld (PAL_GROUP),bc
                ld bc,PORT_PAGE2
                out (c),a
                inc hl                          ; HL → старший байт [bp]
                ld de,12
                ld b,16
.record:        bit 7,(hl)
                jr nz,.active                   ; бит 15 [bp] = 1: запись активна
.next:          add hl,de
                djnz .record
                ret
.active:        push bc
                push hl
                dec hl
                push hl
                pop ix                          ; IX → [bp]
                ld a,16
                sub b                           ; A — слот
                ld l,a
                ld h,0
                ld de,(PAL_GROUP)
                add hl,de
                ld (PAL_AT),hl                  ; кэш записи
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; слот·32
                ld de,(PAL_PLANES)
                add hl,de
                push hl
                pop iy                          ; IY → плоскость R записи
                ld a,(ix+4)
                or (ix+5)
                jr z,.immediate
                ld hl,(#4000+#2EB6)             ; постепенная — только при ([2EB6] & [bp+8]) = 0
                ld a,l
                and (ix+8)
                ld e,a
                ld a,h
                and (ix+9)
                or e
                call z,PalGradual
                jr .done
.immediate:     call PalImmediate
.done:          pop hl
                pop bc
                ld de,12
                jr .next

; Запись совпадает с целями своего типа (PAL_EQ и PAL_KIND). Z — да. HL → PAL_EQ записи. Портит AF, DE.
PalEqual:       ld hl,(PAL_AT)
                ld a,(hl)
                or a
                jr z,.no
                push hl
                ld de,32
                add hl,de
                ld a,(ix+0)
                cp (hl)                         ; PAL_KIND
                pop hl
                ret
.no:            inc a                           ; NZ
                ret

; HL = #8000 + тип·48: цели типа [bp] (младший байт) в окне W2. Портит DE.
PalTargets:     ld l,(ix+0)
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = тип·16
                ld e,l
                ld d,h
                add hl,hl                       ; HL = тип·32
                add hl,de                       ; HL = тип·48
                ld de,#8000
                add hl,de
                ret

; Мгновенная загрузка ($57CF/$5881): 16 перьев × 3 компоненты — слово плоскости = байт цели; затем
; [bp] = [bp] & #00FF, [bp+6] = 1. Запись, уже равная целям того же типа, не переписывается (те же значения); иначе
; PAL_EQ = 1, PAL_KIND = тип, PAL_SYNC = 0, PEN_EQ = PEN_CHG = #FFFF. Портит всё, кроме IX, IY.
PalImmediate:   call PalEqual
                jr z,PalImmediateFlags
                ld (hl),1                       ; PAL_EQ
                ld de,32
                add hl,de
                ld a,(ix+0)
                ld (hl),a                       ; PAL_KIND
                add hl,de
                ld (hl),0                       ; PAL_SYNC: плоскости меняются
                call PalMaskAt                  ; HL → PEN_EQ записи
                ld a,#FF
                ld (hl),a
                inc hl
                ld (hl),a                       ; PEN_EQ: все перья равны целям
                ld de,PEN_CHG-PEN_EQ-1
                add hl,de
                ld (hl),a
                inc hl
                ld (hl),a                       ; PEN_CHG: все перья — к сверке при переносе
                call PalTargets
                push iy
                pop de                          ; DE — слово R пера 0
                ld b,16
.pen:           ld c,3
.component:     ld a,(hl)                       ; A = байт цели
                inc hl
                ld (de),a                       ; слово = A (младший байт)
                inc de
                xor a
                ld (de),a                       ; старший байт = 0
                dec de
                inc d
                inc d                           ; DE += #200: следующая плоскость
                dec c
                jr nz,.component
                ld a,d
                sub 6
                ld d,a                          ; DE −= #600: назад к плоскости R
                inc de
                inc de                          ; DE += 2: следующее перо
                djnz .pen
PalImmediateFlags:
                xor a
                ld (ix+1),a                     ; [bp] &= #00FF
                ld (ix+7),a
                inc a
                ld (ix+6),a                     ; [bp+6] = 1
                ret

; Постепенная загрузка ($5760/$580E после проверки маски): [bp+2] = 0; каждая компонента c (слово) с целью t
; (байт): d = t − c (16 бит); d = 0 — без изменений; t < c — c −= 1; иначе при d ≥ порога [bp+A] — c += 1;
; каждое изменение — [bp+2] += 1. Затем [bp+6] = 1, порог −= 1; порог стал 0 — порог = 1 и при [bp+2] = 0
; [bp] &= #00FF. Запись, равная целям того же типа (PAL_EQ, PAL_KIND), — сразу итог «изменений 0»; иначе цикл по перьям:
; перо из PEN_EQ (при типе, равном PAL_KIND; иначе маска пуста) пропускается — его компоненты равны целям, цикл ничего
; бы не изменил; у остальных — цикл компонент. После цикла PEN_EQ = перья, все компоненты которых были равны целям до
; шага (изменённые перья в неё не входят), PAL_EQ = все перья такие, PAL_KIND = тип; при изменениях PAL_SYNC = 0 и
; PEN_CHG |= перья вне новой PEN_EQ (среди них все изменённые). В цикле: BC' — входная маска (сдвиг вправо, бит 0 —
; текущее перо), DE' — новая маска (бит пера входит сверху, после 16 перьев перо 0 — бит 0), IYL — перо не равно целям
; (≠ 0). Портит всё, кроме IX.
PalGradual:     call PalEqual
                jr nz,.compare
                xor a
                ld (PAL_COUNT),a                ; равная целям: изменений нет
                jp .result
.compare:       push hl                         ; → PAL_EQ записи
                ld de,32
                add hl,de
                ld a,(ix+0)
                sub (hl)                        ; A = 0 — тип записи равен PAL_KIND
                push af
                call PalMaskAt
                ld (PAL_MASK_AT),hl             ; → PEN_EQ записи
                pop af
                ld bc,0
                jr nz,.mask                     ; другой тип — равенство перьев неизвестно
                ld c,(hl)
                inc hl
                ld b,(hl)
.mask:          push bc
                exx
                pop bc                          ; BC' — перья, известные как равные целям
                exx
                call PalTargets                 ; HL → цели пера 0 (окно W2)
                push iy
                pop de                          ; DE — слово R пера 0
                xor a
                ld (PAL_COUNT),a                ; изменений 0 (не больше 48 — байт)
                ; Перья идут двумя байтами маски. На замер 2026-09-17 равны целям в среднем 14,5 из 16, поэтому
                ; байт #FF (все восемь перьев равны) проходится целиком: маска входа сдвигается на байт, в маску
                ; выхода уходят восемь единиц, указатели — на 8·3 целей и 8·2 плоскостей. 98 тактов вместо 8·90.
                ld b,8
                call .eight
                ld b,8
                call .eight
                jp .masks
.eight:         exx
                ld a,c
                inc a
                jr nz,.bits                     ; в байте есть перья, не равные целям
                ld c,b                          ; вход: восемь перьев пройдено
                ld e,d
                ld d,#FF                        ; выход: те же восемь равны
                exx
                ld bc,24
                add hl,bc                       ; цели через восемь перьев
                ex de,hl
                ld bc,16
                add hl,bc                       ; плоскости через восемь перьев
                ex de,hl
                ret                             ; B испорчен: вызывающий ставит счётчик заново
.bits:          exx
.pen:           exx
                srl b
                rr c                            ; CF — перо известно как равное целям
                jr nc,.unknown
                rr d
                rr e                            ; равное перо: тот же бит — в новую маску
                exx
                inc hl
                inc hl
                inc hl                          ; цели следующего пера
                inc de
                inc de                          ; слово R следующего пера
                djnz .pen
                ret
.unknown:       exx
                ld iyl,0                        ; пока все компоненты пера равны целям
                ld c,3
.component:     inc de
                ld a,(de)                       ; старший байт c
                dec de
                or a
                jr nz,.downUnequal              ; c ≥ 256 > t
                ld a,(de)
                sub (hl)                        ; A = c − t (младшие байты)
                jr z,.done                      ; c = t
                jr nc,.downUnequal              ; c > t
                neg                             ; A = t − c = d (1…255)
                ld iyl,a                        ; перо не равно целям; IYL = d
                ld a,(ix+11)
                or a
                jr nz,.done                     ; порог ≥ 256 > d
                ld a,iyl
                cp (ix+10)
                jr c,.done                      ; d < порога
                ld a,(de)                       ; c += 1 (слово)
                add a,1
                ld (de),a
                inc de
                ld a,(de)
                adc a,0
                ld (de),a
                dec de
                jr .count
.downUnequal:   ld iyl,1                        ; перо не равно целям
                ld a,(de)                       ; c −= 1 (слово)
                sub 1
                ld (de),a
                inc de
                ld a,(de)
                sbc a,0
                ld (de),a
                dec de
.count:         ld a,(PAL_COUNT)
                inc a
                ld (PAL_COUNT),a
.done:          inc hl                          ; следующая цель
                inc d
                inc d                           ; DE += #200: следующая плоскость
                dec c
                jr nz,.component
                ld a,d
                sub 6
                ld d,a                          ; DE −= #600: плоскость R
                inc de
                inc de                          ; DE += 2: следующее перо
                ld a,iyl
                cp 1                            ; CF = 1 — все компоненты пера были равны целям
.penDone:       exx
                rr d
                rr e                            ; бит пера — в новую маску сверху
                exx
                djnz .pen
                ret                             ; байт перьев пройден
.masks:         exx
                push de
                exx
                pop bc                          ; BC — новая PEN_EQ
                ld hl,(PAL_MASK_AT)
                ld (hl),c
                inc hl
                ld (hl),b                       ; PEN_EQ записи
                pop hl                          ; → PAL_EQ записи
                ld a,b
                and c
                inc a                           ; Z — все перья были равны целям
                ld a,0
                jr nz,.equal
                inc a
.equal:         ld (hl),a                       ; PAL_EQ: все компоненты были равны целям
                ld de,32
                add hl,de
                ld a,(ix+0)
                ld (hl),a                       ; PAL_KIND
                ld a,(PAL_COUNT)
                or a
                jr z,.result
                add hl,de
                ld (hl),0                       ; PAL_SYNC: плоскости изменились
                ld hl,(PAL_MASK_AT)
                ld de,PEN_CHG-PEN_EQ
                add hl,de                       ; → PEN_CHG записи
                ld a,c
                cpl
                or (hl)
                ld (hl),a                       ; PEN_CHG |= перья, не равные целям до шага
                inc hl
                ld a,b
                cpl
                or (hl)
                ld (hl),a
.result:        ld a,(PAL_COUNT)
                ld (ix+2),a
                xor a
                ld (ix+3),a                     ; [bp+2] = число изменений
                ld (ix+7),a
                inc a
                ld (ix+6),a                     ; [bp+6] = 1
                ld l,(ix+10)
                ld h,(ix+11)
                dec hl                          ; порог −= 1
                ld a,h
                or l
                jr nz,.threshold
                inc hl                          ; порог 0 → 1
                ld a,(PAL_COUNT)
                or a
                jr nz,.threshold
                ld (ix+1),a                     ; изменений нет: [bp] &= #00FF (A = 0)
.threshold:     ld (ix+10),l
                ld (ix+11),h
                ret

; HL → PEN_EQ записи PAL_AT (r = PAL_AT − PAL_EQ; слово на запись). Портит DE.
PalMaskAt:      ld hl,(PAL_AT)
                ld de,-PAL_EQ
                add hl,de
                add hl,hl
                ld de,PEN_EQ
                add hl,de
                ret
