; VDAC2+: нативные процедуры ROM World (страница NATIVE_PAGE0, окно W3 #C000).
;
; Процедура ROM, записанная в codegen.NATIVE, у переведённой программы начинается переходом сюда (FARJP: A — страница,
; HL — метка); возврат — адрес возврата V30 со стека (POP DE) и DISPATCH, как у RET. Окно W1 — рабочее ОЗУ V30
; (#40000…#43FFF, SS = DS = #4000), окно W2 — любая страница V30 (W2_PAGE — её номер, #FF — неизвестна), окно W3 —
; эта страница: подпрограммы резидента, переключающие W3, отсюда не вызываются.
; Каждая процедура оставляет память V30, регистры (зеркала V_*) и живые после RET флаги (V_FL) такими же, как ROM;
; случаи, которые она не берёт, уходят в обычный перевод с того же места (K_ за переходом на входе процедуры).

NATIVE_START:

; Таблицы с выравниванием — в начале страницы (#C000, с 2026-09-26): прежде ALIGN 256 в середине страницы терял до
; 255 байт.
; Таблица холостых обработчиков цикла слотов: по младшему байту IP — старший байт (бит 7 — голый RET $3D16).
WEAPON_IDLE:
                DB #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #3B, #00
                DB #00, #00, #00, #00, #00, #00, #BD, #00, #00, #00, #00, #00, #00, #00, #3A, #00
                DB #00, #00, #00, #00, #00, #00, #3C, #00, #00, #00, #00, #00, #00, #00, #00, #00
                DB #00, #00, #00, #00, #00, #00, #3B, #00, #00, #00, #00, #00, #00, #00, #00, #00
                DB #00, #00, #00, #00, #00, #00, #3A, #00, #00, #00, #00, #00, #00, #00, #3C, #00
                DB #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #39, #00, #00, #00, #3B, #00
                DB #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #3A, #00
                DB #00, #00, #00, #00, #00, #00, #3C, #00, #00, #00, #00, #00, #00, #00, #00, #00
                DB #39, #00, #00, #00, #00, #00, #3B, #00, #00, #00, #00, #00, #00, #00, #00, #00
                DB #00, #00, #00, #00, #00, #00, #3A, #00, #00, #00, #00, #00, #00, #00, #3C, #00
                DB #00, #00, #00, #00, #00, #00, #39, #00, #00, #00, #00, #00, #00, #00, #3B, #00
                DB #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #3A, #00
                DB #00, #00, #00, #00, #00, #00, #3C, #00, #00, #00, #00, #00, #00, #00, #39, #00
                DB #00, #00, #00, #00, #00, #00, #3B, #00, #00, #00, #00, #00, #00, #00, #00, #00
                DB #00, #00, #00, #00, #00, #00, #3A, #00, #00, #00, #00, #00, #00, #00, #3C, #00
                DB #00, #00, #00, #00, #00, #00, #39, #00, #00, #00, #00, #00, #00, #00, #3B, #00

; Кэш описаний спрайтов (NDescCache): 64 записи по 8 байт — метка BX (2 байта) и 6 байт описания ES:BX (ES = #1000,
; ROM). Индекс — биты 1…6 BX; начальная метка записи i нечётна и её биты 1…6 не равны i — попадания не даёт.
DESC_CACHE:
                DB #03, #00, #00, #00, #00, #00, #00, #00
                DB #05, #00, #00, #00, #00, #00, #00, #00
                DB #07, #00, #00, #00, #00, #00, #00, #00
                DB #09, #00, #00, #00, #00, #00, #00, #00
                DB #0B, #00, #00, #00, #00, #00, #00, #00
                DB #0D, #00, #00, #00, #00, #00, #00, #00
                DB #0F, #00, #00, #00, #00, #00, #00, #00
                DB #11, #00, #00, #00, #00, #00, #00, #00
                DB #13, #00, #00, #00, #00, #00, #00, #00
                DB #15, #00, #00, #00, #00, #00, #00, #00
                DB #17, #00, #00, #00, #00, #00, #00, #00
                DB #19, #00, #00, #00, #00, #00, #00, #00
                DB #1B, #00, #00, #00, #00, #00, #00, #00
                DB #1D, #00, #00, #00, #00, #00, #00, #00
                DB #1F, #00, #00, #00, #00, #00, #00, #00
                DB #21, #00, #00, #00, #00, #00, #00, #00
                DB #23, #00, #00, #00, #00, #00, #00, #00
                DB #25, #00, #00, #00, #00, #00, #00, #00
                DB #27, #00, #00, #00, #00, #00, #00, #00
                DB #29, #00, #00, #00, #00, #00, #00, #00
                DB #2B, #00, #00, #00, #00, #00, #00, #00
                DB #2D, #00, #00, #00, #00, #00, #00, #00
                DB #2F, #00, #00, #00, #00, #00, #00, #00
                DB #31, #00, #00, #00, #00, #00, #00, #00
                DB #33, #00, #00, #00, #00, #00, #00, #00
                DB #35, #00, #00, #00, #00, #00, #00, #00
                DB #37, #00, #00, #00, #00, #00, #00, #00
                DB #39, #00, #00, #00, #00, #00, #00, #00
                DB #3B, #00, #00, #00, #00, #00, #00, #00
                DB #3D, #00, #00, #00, #00, #00, #00, #00
                DB #3F, #00, #00, #00, #00, #00, #00, #00
                DB #41, #00, #00, #00, #00, #00, #00, #00
                DB #43, #00, #00, #00, #00, #00, #00, #00
                DB #45, #00, #00, #00, #00, #00, #00, #00
                DB #47, #00, #00, #00, #00, #00, #00, #00
                DB #49, #00, #00, #00, #00, #00, #00, #00
                DB #4B, #00, #00, #00, #00, #00, #00, #00
                DB #4D, #00, #00, #00, #00, #00, #00, #00
                DB #4F, #00, #00, #00, #00, #00, #00, #00
                DB #51, #00, #00, #00, #00, #00, #00, #00
                DB #53, #00, #00, #00, #00, #00, #00, #00
                DB #55, #00, #00, #00, #00, #00, #00, #00
                DB #57, #00, #00, #00, #00, #00, #00, #00
                DB #59, #00, #00, #00, #00, #00, #00, #00
                DB #5B, #00, #00, #00, #00, #00, #00, #00
                DB #5D, #00, #00, #00, #00, #00, #00, #00
                DB #5F, #00, #00, #00, #00, #00, #00, #00
                DB #61, #00, #00, #00, #00, #00, #00, #00
                DB #63, #00, #00, #00, #00, #00, #00, #00
                DB #65, #00, #00, #00, #00, #00, #00, #00
                DB #67, #00, #00, #00, #00, #00, #00, #00
                DB #69, #00, #00, #00, #00, #00, #00, #00
                DB #6B, #00, #00, #00, #00, #00, #00, #00
                DB #6D, #00, #00, #00, #00, #00, #00, #00
                DB #6F, #00, #00, #00, #00, #00, #00, #00
                DB #71, #00, #00, #00, #00, #00, #00, #00
                DB #73, #00, #00, #00, #00, #00, #00, #00
                DB #75, #00, #00, #00, #00, #00, #00, #00
                DB #77, #00, #00, #00, #00, #00, #00, #00
                DB #79, #00, #00, #00, #00, #00, #00, #00
                DB #7B, #00, #00, #00, #00, #00, #00, #00
                DB #7D, #00, #00, #00, #00, #00, #00, #00
                DB #7F, #00, #00, #00, #00, #00, #00, #00
                DB #01, #00, #00, #00, #00, #00, #00, #00
                ASSERT low WEAPON_IDLE == 0 && low DESC_CACHE == 0

; Возврат в переведённую программу: RET V30. Возврат обработчика в цикл объектов ($026A — список, $025C — слоты) —
; сразу в ядро цикла (KERNEL_OBJECTS_B_RET / _A_RET), без поиска IP и переведённого фрагмента за CALL [bp].
NRet:           pop de
                ld a,d
                cp #02
                jp nz,DISPATCH
                ld a,e
                cp #6A
                jp z,KERNEL_OBJECTS_B_RET
                cp #5C
                jp z,KERNEL_OBJECTS_A_RET
                jp DISPATCH

; Страница V30 A — в окно W2 (W2_PAGE = A). Портит AF, BC.
NMap2:          ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ret

; Память спрайтов C000 (страница V30 #30) — в окно W2, если её там нет. Портит AF, BC.
NMapSprites:    ld a,(W2_PAGE)
                cp #30
                ret z
                ld a,#30
                jr NMap2

; Описание ES:BX → N_DESC: NDescriptor12 — двенадцать байт (две записи спрайта по шесть), NDescriptor6 — шесть.
; CF = 1 — описание переходит границу страницы V30 (тогда ничего не прочитано). Рабочее ОЗУ читается прямо из окна
; W1, остальное — через окно W2 (уже отображённая страница не переключается). ES = #1000 (почти всегда) — страница
; 4 + BX >> 14 без 20-битной суммы; копия — цепочкой LDI (LDIR дороже на 5 тактов за байт). Портит AF, BC, DE, HL.
; Описание ES:BX (6 байт) для записи спрайта: DE → копия. ES = #1000 (ROM, не меняется) — кэш DESC_CACHE: попадание —
; DE → байты записи кэша (окно W2 не трогается); промах — NDescriptor6 в N_DESC и запись в кэш. Иной ES — DE = N_DESC
; (копия NDescriptor6). CF = 1 — описание через границу страницы (ничего не прочитано). VDAC2+ 2026-09-26 (скорость:
; попаданий 73…95 % — без двух переключений W2 и копии на каждую запись спрайта). Портит AF, BC, HL.
NDescCache:     ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.plain
                ld hl,(V_BX)
                ld a,l
                and #7E
                add a,a
                add a,a                         ; CF — девятый бит смещения записи ((BX & #7E)·4)
                ld e,a
                ld a,high DESC_CACHE
                adc a,0
                ld d,a                          ; DE → запись кэша
                ld a,(de)
                cp l
                jr nz,.miss
                inc e
                ld a,(de)
                cp h
                jr nz,.miss1
                inc e                           ; DE → 6 байт описания (CF = 0 после CP с равенством)
                ret
.miss1:         dec e
.miss:          push de
                call NDescriptor6               ; → N_DESC; CF — через границу страницы
                pop de
                ret c
                ld hl,(V_BX)
                ex de,hl                        ; HL → запись кэша, DE = BX
                ld (hl),e
                inc l
                ld (hl),d                       ; метка
                inc l
                ex de,hl                        ; DE → байты записи
                ld hl,N_DESC
                push de
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                pop de
                or a
                ret
.plain:         call NDescriptor6
                ld de,N_DESC
                ret

NDescriptor6:   ld a,#FB                        ; младший байт смещения должен быть меньше (при старшем #3F)
                ld (NDescriptor.limit+1),a
                ld hl,NDescriptor.ldi6
                jr NDescriptor
NDescriptor12:  ld a,#F5
                ld (NDescriptor.limit+1),a
                ld hl,NDescriptor.ldi12
NDescriptor:    ld (NDescriptor.chain+1),hl
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.general
                ld hl,(V_BX)                    ; ES = #1000: линейный адрес #10000 + BX
                ld a,h
                rlca
                rlca
                and 3
                add a,4
                ld c,a                          ; страница V30
                ld a,h
                and #3F
                ld h,a                          ; HL = смещение в странице
                jr .offset
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
                adc a,0                         ; A:HL = ES·16 + BX (20 бит)
                and #0F
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; A = страница V30 (линейный адрес >> 14)
                ld c,a
                ld a,h
                and #3F
                ld h,a                          ; HL = смещение в странице
.offset:        cp #3F
                jr c,.inside
                ld a,l
.limit:         cp #F5
                ccf
                ret c                           ; смещение + длина > #4000
.inside:        ld a,c
                cp WORK_PAGE
                jr z,.work
                ld a,(W2_PAGE)
                cp c
                jr z,.mapped
                ld a,c
                push hl
                call NMap2
                pop hl
.mapped:        set 7,h                         ; окно W2
                jr .copy
.work:          set 6,h                         ; окно W1
.copy:          ld de,N_DESC
.chain:         jp .ldi12
.ldi12:         ldi
                ldi
                ldi
                ldi
                ldi
                ldi
.ldi6:          ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                or a
                ret

; Запись спрайта (8 байт) по описанию DE (6 байт) для объекта IX: HL — запись в окне W2. Y = [ix+8] + байт +1
; описания со знаком, код = слово +2, атрибут = младший байт [ix+6] и старший — байт +5 описания, X = [ix+4] +
; байт +0 со знаком. На выходе HL — за записью, DE — за описанием. Портит AF, BC.
NSpriteEntry:   ld a,(de)
                ld c,a                          ; C — байт X
                inc de
                ld a,(de)
                inc de
                ld b,a                          ; B — байт Y
                add a,a
                sbc a,a                         ; A — знак Y (#00 или #FF)
                push de
                ld d,a
                ld a,(ix+8)
                add a,b
                ld (hl),a
                inc hl
                ld a,(ix+9)
                adc a,d
                ld (hl),a                       ; [si] = [bp+8] + Y
                inc hl
                pop de
                ld a,(de)
                ld (hl),a
                inc de
                inc hl
                ld a,(de)
                ld (hl),a                       ; [si+2] = код
                inc de
                inc hl
                inc de                          ; младший байт атрибута описания заменяет [bp+6]
                ld a,(ix+6)
                ld (hl),a
                inc hl
                ld a,(de)
                ld (hl),a                       ; [si+4] = атрибут
                inc de
                inc hl
                ld a,c
                add a,a
                sbc a,a
                ld b,a                          ; B — знак X
                ld a,(ix+4)
                add a,c
                ld (hl),a
                inc hl
                ld a,(ix+5)
                adc a,b
                ld (hl),a                       ; [si+6] = [bp+4] + X
                inc hl
                ret

; ROM $0201B (IP $1C1B, 54 места вызова): два спрайта объекта BP по описаниям ES:BX и ES:BX+6 — в память спрайтов
; C000:SI и C000:DI, где SI = [2EFC], DI = SI + размер первой записи (8, при бите 14 атрибута описания — 16).
; Первая не влезает (DI ≥ #3C8) — возврат без записи: AX = размер, SI, DI. Вторая не влезает (DI + размер ≥ #3C8) —
; первая записана, [2EFC] прежний, AX = DI + размер. Иначе [2EFC] = DI + размер второй и обе записи. Выход: CX = [bp+4],
; DX = [bp+8], AX = атрибут второй записи. Флаги после RET не живут (flags.liveness). DS ≠ #4000 ([2EFC] читается
; через DS), BP у края рабочего ОЗУ или описание через границу страницы — перевод с входа.
N_1C1B:         ld hl,(V_DS)
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
                pop ix                          ; IX → объект (окно W1)
                call NSpritePair
                jp nc,NRet
.translated:    ld a,$$K_0201B
                ld hl,K_0201B
                jp FARJP

; Тело $1C1B для нативных вызовов: IX → объект, описание ES:V_BX (DS = #4000 проверен вызывающим). CF = 1 — описание
; через границу страницы (ничего не сделано). Портит всё, кроме IX.
NSpritePair:    ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.plain
                call NDescCache                 ; первое описание — ES:BX
                ret c
                ld (N_DESCP1),de
                ld hl,(V_BX)
                push hl
                ld de,6
                add hl,de
                ld (V_BX),hl
                call NDescCache                 ; второе — ES:BX+6 (запись кэша другая: индекс сдвинут на 3…4)
                pop hl
                ld (V_BX),hl                    ; BX прежний
                ret c
                ld (N_DESCP2),de
                jr .pointers
.plain:         call NDescriptor12
                ret c
                ld hl,N_DESC
                ld (N_DESCP1),hl
                ld hl,N_DESC+6
                ld (N_DESCP2),hl
.pointers:      ld hl,(N_DESCP2)
                ld de,5
                add hl,de
                ld a,(hl)
                ld (N_ATTR2),a                  ; байт +5 второго описания
                ld hl,(N_DESCP1)
                add hl,de
                ld a,(hl)                       ; байт +5 первого
                ld hl,(#4000+#2EFC)
                ld (V_SI),hl                    ; SI = [2EFC]
                ld de,8
                bit 6,a
                jr z,.size1
                ld e,16
.size1:         add hl,de
                ld (V_DI),hl                    ; DI = SI + размер
                ld bc,-#3C8
                add hl,bc
                jr nc,.fits1
                ld (V_AX),de                    ; AX = размер: память спрайтов заполнена
                or a
                ret
.fits1:         ld l,(ix+4)
                ld h,(ix+5)
                ld (V_CX),hl                    ; CX = [bp+4]
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_DX),hl                    ; DX = [bp+8]
                call NMapSprites
                ld hl,(V_SI)
                set 7,h                         ; C000:SI в окне W2
                ld de,(N_DESCP1)
                call NSpriteEntry
                ld de,8
                ld a,(N_ATTR2)
                bit 6,a
                jr z,.size2
                ld e,16
.size2:         ld hl,(V_DI)
                add hl,de                       ; AX = DI + размер второй записи
                push hl
                ld bc,-#3C8
                add hl,bc
                pop hl
                jr nc,.fits2
                ld (V_AX),hl                    ; вторая не влезла: [2EFC] прежний
                or a
                ret
.fits2:         ld (#4000+#2EFC),hl
                ld hl,(V_DI)
                set 7,h
                ld de,(N_DESCP2)
                call NSpriteEntry
                ld a,(ix+6)
                ld (V_AX),a
                ld a,(N_ATTR2)
                ld (V_AX+1),a                   ; AX = атрибут второй записи
                or a
                ret

; ROM $00A89 (IP $0689) для нативных вызовов: Y объекта IX (24 бита [ix+7…9], Q8) += AX = HL со знаком. Флаги после
; вызовов этой страницы не живут. Портит AF.
NAddY:          bit 7,h
                jr nz,.negative
                ld a,(ix+7)
                add a,l
                ld (ix+7),a
                ld a,(ix+8)
                adc a,h
                ld (ix+8),a
                ret nc
                inc (ix+9)
                ret
.negative:      ld a,(ix+7)
                add a,l
                ld (ix+7),a
                ld a,(ix+8)
                adc a,h
                ld (ix+8),a
                ret c
                dec (ix+9)
                ret

; Слово VRAM страницы W2 по смещению HL (в странице) → DE = слово & #FFF. Портит AF.
NVramWord:      push hl
                set 7,h
                ld e,(hl)
                inc hl
                ld a,(hl)
                and #0F
                ld d,a
                pop hl
                ret

; Тело $2736 для нативных вызовов: IX → объект (DS = #4000 проверен вызывающим). CF = 1 — слово VRAM на границе
; страниц (X и Y прежние, записей не было): вызывающий уходит в перевод. Портит всё, кроме IX.
N2736Core:      ld l,(ix+4)
                ld h,(ix+5)
                ld (N_X0),hl                    ; X
                ld de,-#140
                add hl,de
                ret nc                          ; X < #140 — возврат (CF = 0: не отказ)
                ld l,(ix+8)
                ld h,(ix+9)
                ld (N_Y0),hl                    ; Y
                ld de,4
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; Y + 4
                ld hl,(N_X0)
                or a
                sbc hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; X − 4
                push ix
                pop hl
                res 6,h                         ; BP
                call TerrainA                   ; AX, BX, CX; окно W2 — VRAM слоя A; IX → [bp]
                jr c,.fail
                ld hl,(V_BX)
                ld de,(V_AX)
                call N2736Tile
                ld a,l
                add a,4
                ld l,a                          ; ADD BL,4
                call NVramWord
                call N2736Tile
                inc h
                ld a,h
                and #3F
                ld h,a                          ; ADD BX,#100; AND BX,#3FFF
                call NVramWord
                call N2736Tile
                ld a,l
                sub 4
                ld l,a                          ; SUB BL,4
                call NVramWord
                call N2736Tile
                ld (V_BX),hl
                ld (V_AX),de
                call .restore
                or a
                ret
.fail:          call .restore
                scf
                ret
.restore:       ld hl,(N_Y0)
                ld (ix+8),l
                ld (ix+9),h
                ld hl,(N_X0)
                ld (ix+4),l
                ld (ix+5),h
                ret
; Тайл по смещению HL слоя A с кодом DE: #9F6 — стереть (пометка группы для вывода), [#2F30] + 1. Сохраняет DE, HL.
N2736Tile:      ld a,d
                cp #09
                ret nz
                ld a,e
                cp #F6
                ret nz
                push hl
                set 7,h
                ld (hl),#A0
                inc hl
                ld (hl),#0F
                inc hl
                ld (hl),0
                inc hl
                ld (hl),0                       ; [bx] = #FA0, [bx+2] = 0
                pop hl
                ld a,#34
                call VIDEO_MARK                 ; группа и строка VRAM слоя A — для вывода
                ld a,(#4000+#2F30)
                inc a
                ld (#4000+#2F30),a
                ret

; Тело $2702 для нативных вызовов: IX → объект (DS = #4000, BP < #3F00 — проверяет вызывающий). CF = 1 — отказ до
; окончательных записей (X восстановлен): вызывающий уходит в перевод с вызова процедуры. Портит всё, кроме IX.
N2702Core:
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#140
                add hl,de
                jp nc,.coreOk                      ; X < #140
                ld l,(ix+4)
                ld h,(ix+5)
                ld (N_X1),hl
                ld l,(ix+8)
                ld h,(ix+9)
                ld (N_Y1),hl
                ld de,8
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; Y + 8
                ld hl,(N_X1)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; X + 8
                call N2736Core
                jr c,.fail
                ld de,-#10
                call .moveX
                call N2736Core
                jr c,.fail
                ld de,-#10
                call .moveY
                call N2736Core
                jr c,.fail
                ld de,#10
                call .moveX
                call N2736Core
                jr c,.fail
                call .restore
                jp .coreOk
.fail:          call .restore
.translated:    scf                             ; отказ: вызывающий уходит в перевод
                ret
.coreOk:        or a
                ret
.moveX:         ld l,(ix+4)
                ld h,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                ret
.moveY:         ld l,(ix+8)
                ld h,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h
                ret
.restore:       ld hl,(N_Y1)
                ld (ix+8),l
                ld (ix+9),h
                ld hl,(N_X1)
                ld (ix+4),l
                ld (ix+5),h
                ret

; Тело $2AB4 для нативных вызовов: IX → объект (DS = #4000, BP < #3F00 — проверяет вызывающий). CF = 1 — отказ до
; окончательных записей (X восстановлен): вызывающий уходит в перевод с вызова процедуры. Портит всё, кроме IX.
N2AB4Core:
                ld l,(ix+4)
                ld h,(ix+5)
                ld (N_X0),hl                    ; DX = X (PUSH DX)
                ld de,-#10
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; X − #10
                ld a,9
                ld (N_LOOP),a                   ; CX = 9
                call .fastPrep                  ; VDAC2+: шаги по X без $1EB5 (адреса тайлов — прибавкой)
                jp nc,.fastStep
                jp .step
; Подготовка быстрого пути: для слоёв A и B — сумма X-части (база + ((X + c − #140) >> 1) & #FFFC) первого шага (X0 − 8)
; и добавки к старшему байту адреса (Y-часть, у B ещё (T >> 3) & #3F). X-часть следующего шага — сумма + 4, если
; X + c − #140 на девяти шагах не переходит через ноль (иначе CF = 1: обычный путь с $1EB5). Портит всё, кроме IX.
.fastPrep:      ld de,(#4000+#2EC1)             ; S слоя A
                ld a,e
                and 7
                ld c,a                          ; c
                call .fastBase                  ; DE — база X-части
                call .fastSum                   ; HL — сумма первого шага; CF — переход через ноль
                ret c
                ld (N_SUMA),hl
                ld l,(ix+8)
                ld h,(ix+9)
                ex de,hl                        ; DE = Y
                ld hl,#17F
                or a
                sbc hl,de                       ; AX = #17F − Y
                jr nc,.fastYA
                ld hl,0
.fastYA:        call .fastY
                ld (N_YA),a
                ld de,(#4000+#2EC9)             ; S слоя B
                ld a,e
                and 7
                ld c,a
                call .fastBase
                call .fastSum
                ret c
                ld (N_SUMB),hl
                ld a,(#4000+#2ECD+1)
                rra
                ld a,(#4000+#2ECD)
                ld c,a
                rra
                rra
                rra
                and #3F                         ; (T >> 3) & #3F
                ld b,a
                ld a,c
                and 7                           ; T & 7
                ld l,a
                ld h,0
                ld de,#17F
                add hl,de                       ; AX = #17F + (T & 7)
                ld e,(ix+8)
                ld d,(ix+9)
                or a
                sbc hl,de                       ; − Y
                jr nc,.fastYB
                ld hl,0
.fastYB:        call .fastY
                add a,b
                ld (N_YB),a                     ; добавка старшего байта B: T-часть + Y-часть
                or a
                ret
; DE = S → DE = ((S >> 1) & #FC) + #1020. Портит AF.
.fastBase:      ld a,d
                rra
                ld a,e
                rra
                and #FC
                add a,#20
                ld e,a
                ld a,#10
                adc a,0
                ld d,a
                ret
; C = c, DE = база → HL = база + (((X0 − 8 + c − #140) >> 1) & #FFFC); CF = 1 — X0 − 8 + c − #140 и X0 + 56 + c − #140
; разного знака (сумма шагами +4 была бы неверной). Портит AF, BC.
.fastSum:       ld hl,(N_X0)
                ld b,0
                add hl,bc
                ld bc,-#148
                add hl,bc                       ; v = X0 − 8 + c − #140
                push hl
                ld bc,64
                add hl,bc                       ; v + 64 — последний шаг
                ld a,h
                pop hl
                xor h
                rla
                ret c                           ; знак меняется — переход через ноль
                srl h
                rr l
                ld a,l
                and #FC
                ld l,a
                add hl,de
                or a
                ret
; HL = AX (≤ #17F + 7) → A = (AX >> 3) & #3F. Портит F.
.fastY:         ld a,h
                rra
                ld a,l
                rra
                rra
                rra
                and #3F
                ret
; Адрес тайла по сумме HL и добавке старшего байта A: ((H & #10) + A) & #3F : L. Портит AF, HL (→ адрес).
.fastAddr:      push bc
                ld b,a
                ld a,h
                and #10
                add a,b
                and #3F
                ld h,a
                pop bc
                ret
; Шаги быстрого пути. Сначала слой B (окно W2 #36 один раз): первый шаг k_B, где тайл B < #7D0 (9 — такого нет), —
; в N_KB; тайлы B дальше k_B не нужны. Затем слой A (окно #34 один раз) по шагам в порядке ROM: тайл A(k) < #DFC —
; стена A; k = k_B — стена B; тайлы A(k) ± #100 (за страницей слоя — отказ) < #DFC — стена A. Зеркала регистров на
; выходе — как после шага ROM, на котором выход (.fastTile, .fastRegs, .fastB). Сумма кратна 4: слово тайла не
; пересекает границу 256 байт. Прежний вариант переключал окно дважды на шаг и звал NVramWord — 1 200 тактов на шаг.
.fastStep:      ld a,#36
                call NMap2
                ld hl,(N_SUMB)
                ld a,(N_YB)
                ld c,a                          ; C — добавка старшего байта B
                ld b,0                          ; B — шаг k
.fbStep:        ld a,h
                and #10
                add a,c
                and #3F
                or #80
                ld d,a
                ld e,l
                inc e                           ; DE → старший байт слова тайла B(k) в окне W2
                ld a,(de)
                and #0F
                cp 7
                jr c,.fbWall                    ; тайл < #700
                jr nz,.fbNext
                dec e
                ld a,(de)
                cp #D0
                jr c,.fbWall                    ; #700…#7CF
.fbNext:        ld a,l
                add a,4
                ld l,a
                jr nc,.fbCarry
                inc h                           ; сумма + 4
.fbCarry:       inc b
                ld a,b
                cp 9
                jr c,.fbStep
.fbWall:        ld a,b
                ld (N_KB),a                     ; первый шаг со стеной B (9 — нет)
                ld a,#34
                call NMap2
                ld hl,(N_SUMA)
                ld a,(N_YA)
                ld c,a                          ; C — добавка старшего байта A
                ld b,0
.faStep:        ld a,h
                and #10
                add a,c
                and #3F
                or #80
                ld d,a
                ld e,l
                inc e                           ; DE → старший байт тайла A(k)
                ld a,(de)
                and #0F
                cp #0D
                jr c,.faWall                    ; тайл < #D00
                jr nz,.faB
                dec e
                ld a,(de)
                inc e
                cp #FC
                jr c,.faWall                    ; #D00…#DFB
.faB:           ld a,(N_KB)
                cp b
                jp z,.faWallB                   ; тайл B(k) < #7D0
                inc d                           ; BX + #100
                ld a,d
                cp #C0
                jp z,.bail                      ; за страницей слоя A
                ld a,(de)
                and #0F
                cp #0D
                jr c,.faWallUp
                jr nz,.faDown
                dec e
                ld a,(de)
                inc e
                cp #FC
                jr c,.faWallUp
.faDown:        dec d
                dec d                           ; BX − #100
                bit 7,d
                jp z,.bail                      ; BX − #100 < 0
                ld a,(de)
                and #0F
                cp #0D
                jr c,.faWallDown
                jr nz,.faNext
                dec e
                ld a,(de)
                inc e
                cp #FC
                jr c,.faWallDown
.faNext:        inc d                           ; D — снова A(k)
                ld a,l
                add a,4
                ld l,a
                jr nc,.faCarry
                inc h
.faCarry:       inc b
                ld a,b
                cp 9
                jp c,.faStep
                ; девять шагов без стены: AX — тайл A(8) − #100, BX = A(8), DI — адрес B(8), CX = 0, POP DX
                dec b                           ; B = 8
                dec d
                call .fastTile
                inc d
                call .fastRegs
                call .fastB                     ; V_DX перепишет POP DX
                xor a
                ld (V_CX),a                     ; CX = 0 после LOOP
                ld hl,(N_X0)
                ld (V_DX),hl                    ; POP DX
                ld (ix+4),l
                ld (ix+5),h                     ; X прежний
                jp .still
.faWallUp:      call .fastTile                  ; стена над A(k)
                dec d
                jr .faWallRegs
.faWallDown:    call .fastTile                  ; стена под A(k)
                inc d
                jr .faWallRegs
.faWall:        call .fastTile
.faWallRegs:    call .fastRegs
                call .fastB
                jp .wallA                       ; выходы сами ставят X прежним
.faWallB:       call .fastTile
                call .fastRegs
                call .fastB
                jp .wallB
; DE → старший байт слова тайла в окне W2 (E нечётный) → V_AX = слово & #FFF. Портит A.
.fastTile:      ld a,(de)
                and #0F
                ld (V_AX+1),a
                dec e
                ld a,(de)
                inc e
                ld (V_AX),a
                ret
; D:E — A(k) в окне W2 (E нечётный), B = k → V_BX = A(k), V_CX = 9 − k (POP CX ROM на шаге k). Портит A.
.fastRegs:      ld a,d
                and #7F
                ld (V_BX+1),a
                ld a,e
                dec a
                ld (V_BX),a
                ld a,9
                sub b
                ld (V_CX),a
                xor a
                ld (V_CX+1),a
                ret
; B = k → V_DI — адрес тайла B(k), V_DX — тайл B(k); окно W2 — #36. Портит всё, кроме IX.
.fastB:         ld l,b
                ld h,0
                add hl,hl
                add hl,hl                       ; 4k
                ld de,(N_SUMB)
                add hl,de
                ld a,(N_YB)
                call .fastAddr
                ld (V_DI),hl
                ld a,#36
                call NMap2
                call NVramWord
                ld (V_DX),de
                ret
.step:          ld l,(ix+4)
                ld h,(ix+5)
                ld de,8
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; X + 8
                ld hl,(V_BP)
                call TerrainA
                jp c,.bail
                call TerrainB
                jp c,.bail
                ld hl,(V_CX)
                ld (V_DX),hl                    ; DX = CX (тайл B)
                ld a,(N_LOOP)
                ld (V_CX),a
                xor a
                ld (V_CX+1),a                   ; POP CX — счётчик
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jp nc,.wallA                    ; тайл A < #DFC
                ld hl,(V_DX)
                ld de,-#7D0
                add hl,de
                jp nc,.wallB                    ; тайл B < #7D0
                ld a,#34
                call NMap2                      ; ES = #D000: слой A (после $1EB5 в окне W2 — слой B)
                ld hl,(V_BX)
                inc h
                bit 6,h
                jp nz,.bail                     ; BX + #100 за страницей слоя A
                call NVramWord
                ld (V_AX),de
                ex de,hl
                ld bc,-#DFC
                add hl,bc
                jp nc,.wallA
                ld hl,(V_BX)
                dec h
                bit 7,h
                jp nz,.bail                     ; BX − #100 < 0
                call NVramWord
                ld (V_AX),de
                ex de,hl
                ld bc,-#DFC
                add hl,bc
                jp nc,.wallA
                ld hl,N_LOOP                    ; LOOP
                dec (hl)
                jp nz,.step
                xor a
                ld (V_CX),a                     ; CX = 0 после LOOP
                ld hl,(N_X0)
                ld (V_DX),hl                    ; POP DX
                ld (ix+4),l
                ld (ix+5),h                     ; X прежний
                jp .still

; Стена слоя A ($2B01…$2B7D): окно W2 — VRAM слоя A.
.wallA:         ld hl,(N_X0)
                ld (ix+4),l
                ld (ix+5),h                     ; POP DX; X прежний
                ld a,#34
                ld hl,W2_PAGE
                cp (hl)
                call nz,NMap2
                xor a
                ld (ix+#10),a
                ld (ix+#11),a                   ; [bp+#10] = DI = 0
                ld c,a                          ; C — DI
                ld hl,(V_BX)
                ld (V_DX),hl                    ; DX = BX
                ld de,(V_CX)                    ; DE — CX (последний прочитанный тайл), пока прежний
.upA:           dec h                           ; SUB BX,#100 (старший байт; младший не меняется)
                bit 7,h
                jp nz,.bail                     ; заём: ROM читал бы за страницей слоя
                ld a,h
                cp #10
                jr c,.upAEnd                    ; BX < #1000 (в том числе заём)
                inc (ix+#10)
                call NVramWord
                push hl
                ld hl,-#DFC
                add hl,de
                pop hl
                jr nc,.upA                      ; тайл < #DFC — выше
                jr .downA
.upAEnd:        inc c                           ; DI + 1
.downA:         ld hl,(V_DX)                    ; BX = DX
.downALoop:     inc h                           ; ADD BX,#100
                ld a,h
                cp #2E
                jr nc,.downAEnd                 ; BX ≥ #2E00
                inc (ix+#11)
                call NVramWord
                push hl
                ld hl,-#DFC
                add hl,de
                pop hl
                jr nc,.downALoop
                jr .decideA
.downAEnd:      ld a,c
                add a,#10
                ld c,a                          ; DI + #10
.decideA:       ld (V_BX),hl
                ld (V_CX),de
                ld a,c
                cp #11
                jr nz,.decideA2
                ld (V_DI),a
                xor a
                ld (V_DI+1),a
                jp .still                       ; DI = #11 — стены с обеих сторон
.decideA2:      or a
                jr z,.countA
                and 1
                ld (V_DI),a
                xor a
                ld (V_DI+1),a                   ; AND DI,1
                ld hl,#FE00
                ld a,(V_DI)
                or a
                jr nz,.speed
                ld hl,#200
                jr .speed
.countA:        ld (V_DI),a
                ld (V_DI+1),a                   ; DI = 0
                ld a,(ix+#10)
                cp (ix+#11)
                ld hl,#200
                jr c,.speed                     ; вверх меньше, чем вниз
                ld hl,#FE00
.speed:         ld (V_AX),hl                    ; AX — скорость
                ld (ix+#C),l
                ld (ix+#D),h                    ; [bp+#C] = AX
                call NAddY                      ; $0689
                jp .clamp

; Стена слоя B ($2BEF…$2C3B): окно W2 — VRAM слоя B (после $1EB5 оно там). Переходы за страницу — перевод.
.wallB:         ld hl,(N_X0)
                ld (ix+4),l
                ld (ix+5),h                     ; POP DX; X прежний
                ld a,#36
                ld hl,W2_PAGE
                cp (hl)
                call nz,NMap2
                ld hl,(V_DI)
                ld (N_DI),hl                    ; DX = DI (запишем в конце: до перевода ничего не портим)
                xor a
                ld (ix+#10),a
                ld (ix+#11),a                   ; [bp+#10] = DI = 0
                ld b,a                          ; B — счёт вверх
.upB:           dec h
                bit 6,h
                jp nz,.bailB                    ; BX − #100 < 0: за страницей слоя B
                inc b
                call NVramWord
                push hl
                ld hl,-#7D0
                add hl,de
                pop hl
                jr nc,.upB
                ld c,0                          ; C — счёт вниз
                ld hl,(N_DI)                    ; BX = DX
.downB:         inc h
                bit 6,h
                jp nz,.bailB                    ; BX + #100 ≥ #4000
                inc c
                call NVramWord
                push hl
                ld hl,-#7D0
                add hl,de
                pop hl
                jr nc,.downB
                ld (ix+#10),b
                ld (ix+#11),c
                ld (V_BX),hl
                ld (V_CX),de
                ld hl,(N_DI)
                ld (V_DX),hl
                ld hl,0
                ld (V_DI),hl                    ; DI = 0
                ld a,b
                cp c
                ld hl,#200
                jr c,.speedB
                ld hl,#FE00
.speedB:        ld (V_AX),hl
                ld (ix+#C),l
                ld (ix+#D),h
                call NAddY
                jp .clamp
.bailB:         xor a
                ld (ix+#10),a                   ; перевод перепишет [bp+#10] заново
.bail:          ld hl,(N_X0)
                ld (ix+4),l
                ld (ix+5),h
.translated:    scf                             ; отказ: вызывающий уходит в перевод
                ret
.coreOk:        or a
                ret

; $2B80: стены нет с обеих сторон либо девять шагов без стены.
.still:         ld a,(ix+#C)
                or (ix+#D)
                jr z,.aim
                bit 7,(ix+#D)
                ld de,8
                jr nz,.probe                    ; $2C58: Y + 8
                ld de,-8                        ; $2C76: Y − 8
.probe:         ld l,(ix+8)
                ld h,(ix+9)
                push hl
                add hl,de
                ld (ix+8),l
                ld (ix+9),h
                ld hl,(V_BP)
                call TerrainA
                jr c,.probeFail
                call TerrainB
                jr c,.probeFail
                pop hl
                ld (ix+8),l
                ld (ix+9),h                     ; POP [bp+8]
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jp nc,.clamp
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jp nc,.clamp
                xor a
                ld (ix+#C),a
                ld (ix+#D),a                    ; [bp+#C] = 0
                jr .clamp
.probeFail:     pop hl
                ld (ix+8),l
                ld (ix+9),h
                jr .bail                        ; слово VRAM на границе — перевод (X уже прежний)
.aim:           ld a,(ix+#B)
                or a
                jr nz,.target
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,4
                add hl,de
                ld e,(ix+#32)
                ld d,(ix+#33)
                or a
                sbc hl,de                       ; AX = X + 4 − [bp+#32]
                ld (V_AX),hl
                jr c,.clamp
                ld de,8
                sbc hl,de                       ; − 8 (CF = 0 после JB)
                ld (V_AX),hl
                jr nc,.clamp
.target:        ld l,(ix+#24)
                ld h,(ix+#25)
                ld (V_SI),hl                    ; SI = [bp+#24]
                ld de,#1D40
                add hl,de
                ld a,h
                cp #3F
                jr nc,.aimTranslated            ; [si+#1D40] у края или вне рабочего ОЗУ (DS = #4000)
                set 6,h
                ld e,(hl)
                inc hl
                ld d,(hl)
                ex de,hl                        ; HL = [si+#1D40]
                ld e,(ix+8)
                ld d,(ix+9)
                or a
                sbc hl,de                       ; BX = [si+#1D40] − Y
                ld (V_BX),hl
                jr nc,.below
                ld de,#FFFD
                or a
                push hl
                sbc hl,de
                pop hl
                jr nc,.clamp                    ; BX ≥ −3
                ld hl,#FE00
                jr .aimSpeed
.below:         ld de,3
                push hl
                or a
                sbc hl,de
                pop hl
                jr c,.clamp                     ; BX < 3
                ld hl,#200
.aimSpeed:      ld (V_AX),hl
                ld (ix+#C),l
                ld (ix+#D),h
                call NAddY
.clamp:         ld l,(ix+8)
                ld h,(ix+9)
                ld de,-#98
                add hl,de
                jr c,.upper
                ld (ix+8),#98
                ld (ix+9),0                     ; Y < #98 — #98
                jp .coreOk
.upper:         ld l,(ix+8)
                ld h,(ix+9)
                ld de,-#178
                add hl,de
                jp nc,.coreOk
                ld (ix+8),#78
                ld (ix+9),1                     ; Y ≥ #178 — #178
                jp .coreOk
.aimTranslated: jp .bail

; ROM $01FCC (IP $1BCC, 152 места вызова) для нативных вызовов: спрайт объекта IX по описанию ES:BX (6 байт) — в
; память спрайтов C000:SI, SI = DI = [2EFC], AX = SI + размер (8, при бите 14 атрибута — 16); AX ≥ #3C8 — без записи
; (AX так и остаётся), иначе [2EFC] = AX и запись; CX = [bp+4], DX = [bp+8], AX = атрибут. Зеркала V_* — как у ROM.
; DS = #4000 проверяет вызывающий. CF = 1 — описание через границу страницы (ничего не сделано). Портит всё, кроме IX.
NSpriteAdd:     call NDescCache                 ; DE → описание
                ret c
                push de
                ld hl,5
                add hl,de
                ld a,(hl)
                ld (N_ATTR),a                   ; байт +5 описания — старший атрибута
                ld hl,(#4000+#2EFC)
                ld (V_SI),hl
                ld (V_DI),hl                    ; SI = DI = [2EFC]
                ld de,8
                bit 6,a
                jr z,.size
                ld e,16
.size:          add hl,de                       ; AX = SI + размер
                ld (V_AX),hl
                push hl
                ld bc,-#3C8
                add hl,bc
                pop hl
                jr c,.full                      ; AX ≥ #3C8: память спрайтов заполнена
                ld (#4000+#2EFC),hl
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_CX),hl
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_DX),hl
                call NMapSprites
                ld hl,(V_SI)
                set 7,h
                pop de
                call NSpriteEntry
                ld a,(ix+6)
                ld (V_AX),a
                ld a,(N_ATTR)
                ld (V_AX+1),a                   ; AX = атрибут
                or a
                ret
.full:          pop de
                or a                            ; CF = 0
                ret

; Слово ES:HL → DE (сегмент V_ES). Страница V30 — в окно W2 (рабочее ОЗУ — из W1). CF = 1 — слово на границе страниц.
; Портит AF, BC, HL.
NReadES16:      ld de,(V_ES)
                ld a,d
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a
                ex de,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,de
                ld a,c
                adc a,0
                and #0F
                add a,a
                add a,a
                ld c,a
                ld a,h
                rlca
                rlca
                and 3
                or c                            ; страница V30
                ld c,a
                ld a,h
                and #3F
                ld h,a
                cp #3F
                jr c,.inside
                ld a,l
                inc a
                scf
                ret z                           ; смещение #3FFF: слово через границу
.inside:        ld a,c
                cp WORK_PAGE
                jr z,.work
                push hl
                call NMap2
                pop hl
                set 7,h
                jr .read
.work:          set 6,h
.read:          ld e,(hl)
                inc hl
                ld d,(hl)
                or a
                ret

; ROM $0FADA (IP $F6DA, 62 места вызова): урон объекта BP от снарядов игрока — сканы столкновений ядра ($F485 …
; $F560) с хитбоксом ES:DI, один раз прочитанными X, Y и хитбоксом (сканы их не меняют): $F485 — запись #56
; ([#57] = 1); $F493 — каждые 16 кадров ([#2EB6] & #F = 0) урон [bp+#1F] + 1; $F4AA — урон += [si], [si+1] +=
; остаток HP ([bp+#2F] − урон, если не отрицателен); $F4BF — урон + 1; $F548 — урон + 1 и [si+1] = 0, если HP ≥ [si+1];
; $F560 — урон += [si+1] и [si+1] = 0, если HP − урон − [si+1] ≥ 0. X ≥ #2B4 — без сканов. Выход: AX = прежний AH и
; урон на входе, ZF = урон не изменился (живёт только Z), BX, CX, SI — как у ROM. Условия: DS = #4000, BP кратен #20 и
; меньше #3F00, хитбокс вне рабочего ОЗУ и не через границу страницы (CollideSetup) — иначе перевод с входа.
N_F6DA:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,l
                and #1F
                jp nz,.translated
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop iy                          ; IY → объект (сканы портят IX)
                call NDamage
                jp c,.translated
                ld hl,V_FL
                jr nz,.changed
                set 6,(hl)                      ; ZF = 1: урон не изменился
                jp NRet
.changed:       res 6,(hl)
                jp NRet
.translated:    ld a,$$K_0FADA
                ld hl,K_0FADA
                jp FARJP

; ROM $0FB5F (IP $F75F, 16 мест вызова: части кораблей этапа 3 и враги этапов 6, 7) — тот же урон, что $F6DA, но
; четвёртый скан — $F525 (записи #B6 и #D6; у $F6DA — $F4BF с записями #A8 и #C8 после них). Выход и условия — как у
; N_F6DA (VDAC2+ 2026-09-25, скорость: перевод звал шесть ядер сканов вызовами V30 с CollideSetup у каждого).
N_F75F:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,l
                and #1F
                jp nz,.translated
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                push hl
                pop iy                          ; IY → объект (сканы портят IX)
                call NDamageB6
                jp c,.translated
                ld hl,V_FL
                jr nz,.changed
                set 6,(hl)                      ; ZF = 1: урон не изменился
                jp NRet
.changed:       res 6,(hl)
                jp NRet
.translated:    ld a,$$K_0FB5F
                ld hl,K_0FB5F
                jp FARJP

; Тело $F6DA для нативных вызовов: IY → объект (DS = #4000, BP кратен #20 и < #3F00 — проверяет вызывающий), DI —
; V_DI. CF = 1 — хитбокс ES:DI в рабочем ОЗУ или через границу страницы (ничего не записано); иначе ZF = урон не
; изменился (как у CMP ROM). Регистры V30 — как у ROM. Портит всё, кроме IY (IX — тоже: сканы).
; NDamageB6 — то же для $F75F: четвёртый скан — $F525 (NCollideB6) вместо $F4BF (CollideBF).
NDamageB6:      ld a,1
                jr NDamage.variant
NDamage:        xor a
.variant:       ld (N_DMGV),a                   ; 0 — $F6DA, 1 — $F75F
                ld a,(iy+#1F)
                ld (N_DMG0),a                   ; MOV AL,[bp+#1F]; PUSH AX
                ld l,(iy+4)
                ld h,(iy+5)
                ld de,-#2B4
                add hl,de
                jp c,.done                      ; X ≥ #2B4 — сканов нет
                ld hl,(V_DI)
                call CollideSetup               ; X, Y, хитбокс ES:DI
                ret c
                ld hl,(V_DI)
                ld (V_BX),hl                    ; MOV BX,DI
                ld bc,(KC_X)
                ld de,(KC_XR)                   ; X и XR — для BoxX сканов цепочки (входы .go)
                call CollReject                 ; кэш столкновений: объект в стороне от R-9, Force и битов
                jr nc,.scan
                ld hl,#156
                ld (V_SI),hl                    ; как после $F493 без попадания (AX — от CollReject)
                jp .s3                          ; $F485, $F493 — промах; дальше $F4AA (свой отказ), лучи, $F548, $F560
.scan:          call Collide85.go
                jr nc,.s2
                ld a,1
                ld (#4000+#57),a                ; [si+1] = 1 (SI = #56)
.s2:            call Collide93.go
                jr nc,.s3
                ld a,(#4000+#2EB6)
                and #0F
                jr nz,.s3
                inc (iy+#1F)
.s3:            call CollideAA.go
                jr nc,.s4
                ld hl,(V_SI)
                set 6,h
                ld c,(hl)                       ; AH = [si]
                ld a,(iy+#1F)
                ld (V_BX),a                     ; BL = урон
                ld b,a
                ld a,(iy+#2F)
                sub b                           ; AL = HP − урон
                jp c,.done
                ld b,a
                ld a,(iy+#1F)
                add a,c
                ld (iy+#1F),a                   ; урон += AH
                inc hl
                ld a,(hl)
                add a,b
                ld (hl),a                       ; [si+1] += AL
                ld bc,(KC_X)
                ld de,(KC_XR)                   ; BC портился выше
.s4:            ld hl,(V_DI)
                ld (V_BX),hl
                ld a,(N_DMGV)
                or a
                jr nz,.b6
                call CollideBF.go               ; $F4BF
                jr .s4done
.b6:            call NCollideB6.go              ; $F525 (у $F75F)
.s4done:        jr nc,.s5
                inc (iy+#1F)
.s5:            call NCollide48.go
                jr nc,.s6
                inc (iy+#1F)
                ld hl,(V_SI)
                set 6,h
                inc hl                          ; [si+1]
                ld a,(iy+#2F)
                cp (hl)
                jr c,.done                      ; HP < [si+1]
                ld (hl),0
.s6:            call NCollide60.go
                jr nc,.done
                ld hl,(V_SI)
                set 6,h
                inc hl
                ld c,(hl)                       ; AH = [si+1]
                ld a,(iy+#1F)
                ld (V_BX),a                     ; BL = урон
                ld b,a
                ld a,(iy+#2F)
                sub b                           ; AL = HP − урон
                jr c,.done
                ld b,a
                ld a,(iy+#1F)
                add a,c
                ld (iy+#1F),a                   ; урон += AH
                ld a,b
                sub (hl)
                jr c,.done                      ; AL − [si+1] < 0
                ld (hl),0
.done:          ld a,(N_DMG0)
                ld (V_AX),a                     ; POP AX: AH прежний, AL — урон на входе
                cp (iy+#1F)                     ; ZF — урон не изменился; CF нужен 0
                scf
                ccf                             ; CF = 0, ZF — от CP
                ret

; ROM $00A72 (IP $0672) для нативных вызовов: X объекта IX (24 бита [ix+3…5], Q8) += AX = HL со знаком. Флаги после
; вызовов этой страницы не живут. Портит AF.
NAddX:          bit 7,h
                jr nz,.negative
                ld a,(ix+3)
                add a,l
                ld (ix+3),a
                ld a,(ix+4)
                adc a,h
                ld (ix+4),a
                ret nc
                inc (ix+5)
                ret
.negative:      ld a,(ix+3)
                add a,l
                ld (ix+3),a
                ld a,(ix+4)
                adc a,h
                ld (ix+4),a
                ret c
                dec (ix+5)
                ret

; ROM $03CF4 (IP $38F4) для нативных вызовов: прямоугольник объекта IX по таблице ES:SI (ES = #1000, SI = HL):
; BX, CX, DX, SI = слова [si], [si+2], [si+4], [si+6]; [bp+#18] = [bp+4] − BX, [bp+#1A] = [bp+4] + CX, [bp+#1C] =
; [bp+8] − DX, [bp+#1E] = AX = [bp+8] + SI. CF = 1 — таблица через границу страницы V30 (ничего не сделано) или
; ES ≠ #1000. Портит всё, кроме IX.
NHitbox:        ex de,hl
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                scf
                ret nz                          ; ES ≠ #1000
                ex de,hl
                ld a,h
                and #3F
                cp #3F
                jr nz,.inside
                ld a,l
                cp #F9
                ccf
                ret c                           ; ES:[si+7] — в следующей странице V30
.inside:        ld a,h
                rlca
                rlca
                and 3
                add a,4                         ; страница V30: (#10000 + SI) >> 14
                push hl
                ld hl,W2_PAGE
                cp (hl)
                call nz,NMap2
                pop hl
                ld a,h
                and #3F
                or #80
                ld h,a                          ; окно W2
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (V_BX),de                    ; BX = ES:[si]
                ld c,(ix+4)
                ld b,(ix+5)
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
                ld b,(ix+9)
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
                or a
                ret

; $1EB5 для нативных вызовов: объект IX → AX, BX (слой A), CX, DI (слой B), как у ядра. CF = 1 — слово VRAM на
; границе страниц (отказ ядра). Портит всё; IX сохраняется (ядро ставит его на тот же объект).
NTerrainAB:     push ix
                pop hl
                res 6,h                         ; BP
                call TerrainA
                ret c
                jp TerrainB

; Объект на поле ($1D6B) для нативных вызовов: IX → объект; CF = 1 — вне поля; V_AX — как у ROM. Портит AF, DE, HL.
NOnField:       ld l,(ix+4)
                ld h,(ix+5)
                ld de,#12C
                or a
                sbc hl,de
                jr c,.outside
                ld de,#1A8
                sbc hl,de
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
                or a
                ret
.outside:       ld (V_AX),hl
                scf
                ret

; Переход в перевод с середины процедуры: A — страница, HL — метка A_ инструкции (продолжение пути, редкого для
; нативной части). Регистры V30 — в зеркалах, стек V30 — как у ROM в этой точке.
                MACRO NTAIL label
                ld a,$$label
                ld hl,label
                jp FARJP
                ENDM

; ROM $00703 (IP $0303, 244 места вызова): звуковая команда CL — в очередь #2020 (32 байта): индекс записи
; [#2EDE] + 1 по модулю 32; очередь полна (равен индексу чтения [#2EDC]) — команда теряется. AX, BX — прежние
; (PUSH/POP ROM), IF = 1 (CLI … STI), CF — как у CMP нового индекса с [#2EDC] (после RET живёт только он).
; Условие: DS = #4000.
N_0303:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld a,(V_CX)
                call NSoundCore
                ld hl,V_FL
                res 0,(hl)
                jr nc,.carry
                set 0,(hl)
.carry:         inc hl
                set 1,(hl)                      ; STI
                jp NRet
.translated:    ld a,$$K_00703
                ld hl,K_00703
                jp FARJP

; Звуковая команда A — в очередь (DS = #4000). CF — как у CMP ROM (новый индекс < [#2EDC]). Портит AF, BC, DE, HL.
NSoundCore:     ld c,a
                ld hl,(#4000+#2EDE)
                ld e,l
                ld d,h                          ; BX — прежний индекс
                inc hl
                ld a,l
                and #1F
                ld l,a
                ld h,0                          ; AX = (AX + 1) & #1F
                ld a,(#4000+#2EDC+1)
                or a
                jr nz,.high                     ; [#2EDC] ≥ #100 > AX: CF = 1, не равны
                ld a,(#4000+#2EDC)
                ld b,a
                ld a,l
                cp b                            ; CF = AX < [#2EDC], ZF — равны
                jr z,.full                      ; очередь полна (CF = 0)
                jr .store
.high:          scf
.store:         push af
                push hl
                ld hl,#4000+#2020
                add hl,de
                ld (hl),c                       ; [bx+#2020] = CL
                pop hl
                ld (#4000+#2EDE),hl
                pop af
                ret
.full:          or a
                ret
; Для нативных обработчиков: звук A, V_FL: IF = 1 (STI), CF — как у ROM. Портит AF, BC, DE, HL.
NSound:         call NSoundCore
                ld hl,V_FL
                res 0,(hl)
                jr nc,.carry
                set 0,(hl)
.carry:         inc hl
                set 1,(hl)
                ret

; ROM $02189 (IP $1D89, 32 места вызова): сектор направления от объекта BP (SI = [bp+4], DI = [bp+8]) к объекту BX
; (DX = [bx+4], BX = [bx+8]) — BX = 0…#3C шагом 4 (0 — вниз, #10 — вправо, #20 — вверх, #30 — влево, диагонали —
; по разности |dx| − |dy| с порогом ±#20). AX, CX — как у ROM; флаги после RET не живут. Условия: DS = #4000, BP и
; BX < #3F00.
N_1D89:         ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.translated
                ld hl,(V_BP)
                ld a,h
                cp #3F
                jp nc,.translated
                ld hl,(V_BX)
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                ld de,(V_BP)
                set 6,d
                call NAimCore
                jp NRet
.translated:    ld a,$$K_02189
                ld hl,K_02189
                jp FARJP

; Тело $1D89: DE → объект (окно W1), HL → цель (окно W1). Выход: V_SI, V_DI, V_DX, V_BX (сектор), V_AX, V_CX — как у
; ROM. Портит всё.
NAimCore:       push hl
                ex de,hl
                ld de,4
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_SI),de                    ; SI = [bp+4]
                inc hl
                inc hl
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_DI),de                    ; DI = [bp+8]
                pop hl
                ld de,4
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_DX),de                    ; DX = [bx+4]
                inc hl
                inc hl
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (N_TY),de                    ; BX = [bx+8]
                ; DI + 8 − BX: заём — цель ниже
                ld hl,(V_DI)
                ld bc,8
                add hl,bc
                or a
                sbc hl,de
                ld (V_AX),hl
                jr c,.below
                ld hl,(V_DI)
                or a
                sbc hl,bc
                or a
                sbc hl,de
                ld (V_AX),hl
                jr nc,.above
                ld hl,(V_SI)                    ; по Y рядом
                ld de,(V_DX)
                or a
                sbc hl,de
                ld (V_AX),hl
                ld hl,#30
                jr nc,.set
                ld hl,#10
.set:           ld (V_BX),hl
                ret
.below:         call .xSplit                    ; цель ниже
                jr c,.belowRight
                jr nc,.belowCheckLeft
.belowCheckLeft:
                call .xLeft
                jp nc,.belowLeft
                ld hl,0
                jr .set
.above:         call .xSplit
                jp c,.aboveRight
                call .xLeft
                jp nc,.aboveLeft
                ld hl,#20
                jr .set
; SI + 8 − DX: CF = 1 — цель правее (AX — разность).
.xSplit:        ld hl,(V_SI)
                ld de,8
                add hl,de
                ld de,(V_DX)
                or a
                sbc hl,de
                ld (V_AX),hl
                ret
; SI − 8 − DX: CF = 0 — цель левее.
.xLeft:         ld hl,(V_SI)
                ld de,8
                or a
                sbc hl,de
                ld de,(V_DX)
                or a
                sbc hl,de
                ld (V_AX),hl
                ret
; Диагональ: HL = |dx|, DE = |dy| → AX = HL − DE + #20; сектор: AX < #40 — B, иначе бит 15 AX = 0 — C, иначе N_SECT3.
.diag:          or a
                sbc hl,de
                ld de,#20
                add hl,de
                ld (V_AX),hl
                ld a,h
                or a
                jr nz,.diagFar
                ld a,l
                cp #40
                jr nc,.diagFar
                ld a,b
                jr .diagSet
.diagFar:       bit 7,h
                ld a,c
                jr z,.diagSet
                ld a,(N_SECT3)
.diagSet:       ld l,a
                ld h,0
                ld (V_BX),hl
                ret
.belowRight:    ld hl,(V_DX)                    ; AX = DX − SI, CX = BX − DI
                ld de,(V_SI)
                or a
                sbc hl,de
                push hl
                ld hl,(N_TY)
                ld de,(V_DI)
                or a
                sbc hl,de
                ld (V_CX),hl
                ex de,hl
                pop hl
                ld a,4
                ld (N_SECT3),a                  ; сектор при AX < 0 (дальше от оси)
                ld bc,#080C                     ; ближе к оси — 8, иначе при AX ≥ 0 — #C, при AX < 0 — 4
                jr .diag
.belowLeft:     ld hl,(V_SI)                    ; AX = SI − DX, CX = BX − DI
                ld de,(V_DX)
                or a
                sbc hl,de
                push hl
                ld hl,(N_TY)
                ld de,(V_DI)
                or a
                sbc hl,de
                ld (V_CX),hl
                ex de,hl
                pop hl
                ld a,#3C
                ld (N_SECT3),a                  ; сектор при AX < 0 (дальше от оси)
                ld bc,#3834
                jr .diag
.aboveRight:    ld hl,(V_DX)                    ; AX = DX − SI, CX = DI − BX
                ld de,(V_SI)
                or a
                sbc hl,de
                push hl
                ld hl,(V_DI)
                ld de,(N_TY)
                or a
                sbc hl,de
                ld (V_CX),hl
                ex de,hl
                pop hl
                ld a,#1C
                ld (N_SECT3),a                  ; сектор при AX < 0 (дальше от оси)
                ld bc,#1814
                jp .diag
.aboveLeft:     ld hl,(V_SI)                    ; AX = SI − DX, CX = DI − BX
                ld de,(V_DX)
                or a
                sbc hl,de
                push hl
                ld hl,(V_DI)
                ld de,(N_TY)
                or a
                sbc hl,de
                ld (V_CX),hl
                ex de,hl
                pop hl
                ld a,#24
                ld (N_SECT3),a                  ; сектор при AX < 0 (дальше от оси)
                ld bc,#282C
                jp .diag

; Общие условия обработчиков змейки этапа 2: DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00. CF = 1 — нет.
; Иначе IX → объект. Портит AF, HL.
NSnakeCheck:    ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                scf
                ret nz
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                scf
                ret nz
                ld hl,(V_BP)
                ld a,l
                and #1F
                scf
                ret nz
                ld a,h
                cp #3F
                ccf
                ret c
                set 6,h
                push hl
                pop ix
                or a
                ret

; X объекта IX += шаг прокрутки переднего слоя [#2ED0] (V_AX = он же). Портит AF, DE, HL.
NScrollX:       ld de,(#4000+#2ED0)
                ld (V_AX),de
                ld l,(ix+4)
                ld h,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                ret

; Кадр змейки: V_BX = [bp+#20] + DE, затем BX = ES:[bx] (описание пары спрайтов). CF = 1 — слово на границе
; страницы (V_BX — адрес таблицы, как у ROM до MOV BX,ES:[BX]). Портит всё, кроме IX.
NSnakeFrame:    ld l,(ix+#20)
                ld h,(ix+#21)
                add hl,de
                ld (V_BX),hl
                call NReadES16
                ret c
                ld (V_BX),de
                ret

; Урон, звук попадания и проверки змейки после пары спрайтов. B = 1 — у $7106 (без проверок попадания и поля).
; Выход: A — 0 RET, 1 смерть ($70E3), 2 попадание ($70D2), 3 удаление ($7155); CF = 1 — хитбокс не взят ядром (ничего
; не записано) — остаток переводом с MOV DI,#31EE. Портит всё, кроме IX.
NSnakeDamage:   push bc
                ld hl,#31EE
                ld (V_DI),hl                    ; MOV DI,#31EE
                push ix
                pop iy
                call NDamage
                push iy
                pop ix
                pop bc
                ret c
                jr z,.noHit
                push bc
                ld a,#57
                ld (V_CX),a                     ; MOV CL,#57
                call NSound
                pop bc
.noHit:         ld a,(ix+#1F)
                ld (V_AX),a                     ; MOV AL,[bp+#1F]
                cp (ix+#2F)
                ld a,1
                jr nc,.result                   ; урон ≥ HP — смерть
                ld a,b
                or a
                jr nz,.pause
                ld a,(ix+#1F)
                cp (ix+#1E)
                ld a,2
                jr nz,.result                   ; урон вырос — попадание
                call NOnField
                ld a,3
                jr c,.result                    ; вне поля — удаление
.pause:         ld a,(#4000+#2FC4)
                or a
                ld a,3
                jr nz,.result                   ; [#2FC4] ≠ 0 — удаление
                xor a
.result:        or a                            ; CF = 0
                ret

; Попадание ($70D2): [bp+#28] = #17, [bp+#2A] = AX = обработчик, обработчик $7106.
NSnakeHit:      ld (ix+#28),#17
                ld (ix+#29),0
                ld l,(ix+0)
                ld h,(ix+1)
                ld (V_AX),hl
                ld (ix+#2A),l
                ld (ix+#2B),h
                ld (ix+0),#06
                ld (ix+1),#71
                jp NRet

; ROM $073D0 (IP $6FD0, змейка этапа 2 — выход на цель): X += шаг прокрутки; при бите 15 [bp+#34] — сектор на R-9
; ($1D89 с BX = #20): совпал с [bp+#36] — обработчик $7048; иначе [bp+#34] − 1: 0 — $7048; каждые 64 — кадр +4,
; иначе +2 из таблицы [bp+#20]; затем пара спрайтов, урон, звук попадания и проверки ($1D6B, [#2FC4]). Смерть и
; удаление — переводом. Регистры — как у ROM.
N_6FD0:         call NSnakeCheck
                jp c,.translated
                call NScrollX
                bit 7,(ix+#35)
                jr z,.timer
                ld hl,#20
                ld (V_BX),hl
                ld hl,#4000+#20
                push ix
                pop de
                call NAimCore
                ld a,(V_BX)
                cp (ix+#36)
                jr nz,.frame2
                ld a,(V_BX+1)
                cp (ix+#37)
                jr nz,.frame2
.next:          ld (ix+0),#48
                ld (ix+1),#70                   ; обработчик $7048
                jp NRet
.timer:         ld l,(ix+#34)
                ld h,(ix+#35)
                dec hl
                ld (ix+#34),l
                ld (ix+#35),h
                ld a,h
                or l
                jr z,.next
                ld a,l
                and #3F
                jr nz,.frame2
                ld de,4
                jr .frame
.frame2:        ld de,2
.frame:         call NSnakeFrame
                jr c,.frameFail
                call NSpritePair
                jr c,.pairFail
                ld b,0
                call NSnakeDamage
                jr c,.damageFail
                or a
                jp z,NRet
                dec a
                jr z,.death
                dec a
                jp z,NSnakeHit
                NTAIL A_07555                   ; удаление
.death:         NTAIL A_074E3
.frameFail:     NTAIL A_07406
.pairFail:      NTAIL A_07409
.damageFail:    NTAIL A_0740C
.translated:    ld a,$$K_073D0
                ld hl,K_073D0
                jp FARJP

; ROM $07448 (IP $7048, змейка этапа 2 — движение): X += шаг прокрутки; тайл A под объектом ($1E6C): пустой (#FA0) —
; [bp+#3C] = 0, X, Y += [bp+#30], [bp+#32], кадр +4; иначе раз в 32 кадра звук #5F ([bp+#3C] — таймер), X, Y +=
; [bp+#38], [bp+#3A], [bp+#22] + 1, кадр по кольцу ([bp+#22] & #3C) >> 1; затем как у $6FD0.
N_7048:         call NSnakeCheck
                jp c,.translated
                call NScrollX
                push ix
                pop hl
                res 6,h
                call TerrainA                   ; AX — тайл A
                jp c,.terrainFail
                ld hl,(V_AX)
                ld a,h
                cp #0F
                jr nz,.solid
                ld a,l
                cp #A0
                jr nz,.solid
                ld (ix+#3C),0
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX
                ld l,(ix+#32)
                ld h,(ix+#33)
                ld (V_AX),hl
                call NAddY
                ld de,4
                jr .frame
.solid:         ld a,(ix+#3C)
                or a
                jr nz,.tick
                ld a,#5F
                ld (V_CX),a                     ; MOV CL,#5F
                call NSound
                ld (ix+#3C),#20
                jr .move
.tick:          dec (ix+#3C)
.move:          ld l,(ix+#38)
                ld h,(ix+#39)
                ld (V_AX),hl
                call NAddX
                ld l,(ix+#3A)
                ld h,(ix+#3B)
                ld (V_AX),hl
                call NAddY
                ld l,(ix+#22)
                ld h,(ix+#23)
                inc hl
                ld (ix+#22),l
                ld (ix+#23),h
                ld a,l
                and #3C
                rrca
                ld e,a
                ld d,0                          ; BX = ([bp+#22] & #3C) >> 1
.frame:         call NSnakeFrame
                jr c,.frameFail
                call NSpritePair
                jr c,.pairFail
                ld b,0
                call NSnakeDamage
                jr c,.damageFail
                or a
                jp z,NRet
                dec a
                jr z,.death
                dec a
                jp z,NSnakeHit
                NTAIL A_07555
.death:         NTAIL A_074E3
.frameFail:     NTAIL A_0749C
.pairFail:      NTAIL A_0749F
.damageFail:    NTAIL A_074A2
.terrainFail:   NTAIL A_0744E
.translated:    ld a,$$K_07448
                ld hl,K_07448
                jp FARJP

; ROM $07506 (IP $7106, змейка этапа 2 — вспышка после попадания): X += шаг прокрутки; [bp+#28] − 1 = 0 — [bp+#1E] =
; урон, обработчик = [bp+#2A]; иначе кадр по кольцу, пара спрайтов ($7168: при [bp+#28] & 3 = 0 палитра [bp+#3E] на
; время вывода), урон, звук, смерть и [#2FC4]. Регистры — как у ROM.
N_7106:         call NSnakeCheck
                jp c,.translated
                call NScrollX
                ld l,(ix+#28)
                ld h,(ix+#29)
                dec hl
                ld (ix+#28),l
                ld (ix+#29),h
                ld a,h
                or l
                jr nz,.flash
                ld a,(ix+#1F)
                ld (ix+#1E),a                   ; [bp+#1E] = урон
                ld (V_AX),a                     ; MOV AL,[bp+#1F]
                ld l,(ix+#2A)
                ld h,(ix+#2B)
                ld (V_AX),hl                    ; MOV AX,[bp+#2A]
                ld (ix+0),l
                ld (ix+1),h
                jp NRet
.flash:         ld l,(ix+#22)
                ld h,(ix+#23)
                inc hl
                ld (ix+#22),l
                ld (ix+#23),h
                ld a,l
                and #3C
                rrca
                ld e,a
                ld d,0
                call NSnakeFrame
                jr c,.frameFail
                ld a,(ix+#28)
                and 3
                jr nz,.plain
                ld a,(ix+6)
                ld (N_PAL),a                    ; PUSH [bp+6]
                ld a,(ix+#3E)
                ld (V_AX),a                     ; MOV AL,[bp+#3E]
                ld (ix+6),a
                call NSpritePair
                ld a,(N_PAL)
                ld (ix+6),a                     ; POP [bp+6]
                jr c,.pairFail
                jr .damage
.plain:         call NSpritePair
                jr c,.pairFail
.damage:        ld b,1
                call NSnakeDamage
                jr c,.damageFail
                or a
                jp z,NRet
                dec a
                jr z,.death
                NTAIL A_07555
.death:         NTAIL A_074E3
.frameFail:     NTAIL A_07520
.pairFail:      NTAIL A_07523
.damageFail:    NTAIL A_07526
.translated:    ld a,$$K_07506
                ld hl,K_07506
                jp FARJP

; Общие условия обработчиков врагов: DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00 (сканы столкновений ядра).
; CF = 1 — нет. Иначе IX → объект. Портит AF, HL.
NEnemyCheck:    ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                scf
                ret nz
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                scf
                ret nz
                ld hl,(V_BP)
                ld a,l
                and #1F
                scf
                ret nz
                ld a,h
                cp #3F
                ccf
                ret c
                set 6,h
                push hl
                pop ix
                or a
                ret

; ROM $0EA03 (IP $E603; обработчик $E601 — тот же код после XOR AX,AX, AX тут же перезаписан, и приходит сюда же):
; снаряд врага. X, Y += [bp+#30], [bp+#32] (Q8); у обработчика $E601 с задержкой [bp+#20] ≠ 0 — задержка − 1 и без
; спрайта; иначе спрайт по кадру ((BP >> 3) + [#2EB6]) & #18 из таблицы #84AE (шаг 6). Столкновения с хитбоксом
; #84C6: $F485 (запись #56 — [#57] = 1) и $F578 с записью #76 — попадание ($E686: [bp+#20] = #A, обработчик $E691).
; В нечётных кадрах — RET; в чётных рельеф ($1EB5): стена — $E686; [#2FC4] ≠ 0 или вне поля — удаление ($E67C,
; переводом). Регистры — как у ROM.
N_E603:         call NEnemyCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX
                ld l,(ix+#32)
                ld h,(ix+#33)
                ld (V_AX),hl
                call NAddY
                ld a,(ix+0)
                cp #03
                jr nz,.delay
                ld a,(ix+1)
                cp #E6
                jr z,.sprite                    ; обработчик $E603 — спрайт всегда
.delay:         ld l,(ix+#20)
                ld h,(ix+#21)
                ld a,h
                or l
                jr z,.sprite
                dec hl
                ld (ix+#20),l
                ld (ix+#21),h
                jr .collide
.sprite:        push ix
                pop hl
                res 6,h                         ; BP
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l                            ; BX = BP >> 3
                ld de,(#4000+#2EB6)
                add hl,de
                ld a,l
                and #18
                rrca                            ; (… & #18) >> 1: 0, 4, 8, #C
                ld (V_CX),a
                ld e,a
                xor a
                ld (V_CX+1),a                   ; CX = он же
                ld a,e
                rrca                            ; BX >> 1
                add a,e                         ; + CX: 0, 6, #C, #12
                ld l,a
                ld h,0
                ld de,#84AE
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd
                jp c,.spriteFail
.collide:       ld hl,#84C6
                ld (V_BX),hl                    ; MOV BX,#84C6
                call CollideSetup
                jp c,.collideFail
                push ix
                call Collide85
                pop ix
                jr nc,.player
                ld a,1
                ld (#4000+#57),a                ; [si+1] = 1 (SI = #56)
.player:        ld hl,#84C6
                ld (V_BX),hl
                ld hl,#76
                ld (V_SI),hl                    ; MOV SI,#76
                ld bc,(KC_X)
                ld de,(KC_XR)
                ld hl,#4000+#76+2
                call BoxX                       ; $F578
                jr c,.hit
                ld a,(#4000+#2EB6)
                rrca
                jp c,NRet                       ; нечётный кадр — без рельефа
                call NTerrainAB
                jp c,.terrainFail
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.hit
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jr nc,.hit
                ld a,(#4000+#2FC4)
                or a
                jr nz,.remove
                call NOnField
                jr c,.remove
                jp NRet
.hit:           ld (ix+#20),#0A
                ld (ix+#21),0
                ld (ix+0),#91
                ld (ix+1),#E6                   ; обработчик $E691
                jp NRet
.remove:        NTAIL A_0EA7C
.spriteFail:    NTAIL A_0EA3F                   ; описание через границу — $1BCC переводом
.collideFail:   NTAIL A_0EA42
.terrainFail:   NTAIL A_0EA61
.translated:    ld a,$$K_0EA03
                ld hl,K_0EA03
                jp FARJP

; Проба рельефа $5A88/$5AA3: X += HL, Y += DE (на время), тайл A ($1E6C) → V_AX, V_BX, V_CX; X и Y прежние (PUSH/POP
; ROM). CF = 1 — слово VRAM на границе страниц (X, Y прежние). Портит всё, кроме IX.
NProbeA:        ld c,(ix+4)
                ld b,(ix+5)
                push bc                         ; PUSH [bp+4]
                push hl
                ld l,(ix+8)
                ld h,(ix+9)
                push hl                         ; PUSH [bp+8]
                add hl,de
                ld (ix+8),l
                ld (ix+9),h
                pop de                          ; DE — прежний Y
                pop hl
                push de
                add hl,bc
                ld (ix+4),l
                ld (ix+5),h
                push ix
                pop hl
                res 6,h
                call TerrainA
                pop de
                pop bc
                ld (ix+8),e
                ld (ix+9),d                     ; POP [bp+8]
                ld (ix+4),c
                ld (ix+5),b                     ; POP [bp+4]
                ret

; ROM $05E2B (IP $5A2B, ходок этапа 1): счётчик периода ($F63A; порождение — переводом с возвратом в перевод $5A2E);
; при [bp+#1E] = 0 — X += шаг прокрутки и скорость #FF40, иначе #C0 ($0672); спрайт по кадру ([#2EB6] & #18) >> 2 из
; таблицы #291A / #2922; столкновения $F694 с хитбоксом #2982 (попадание — $5C83, переводом); вне поля или [#2FC4] ≠ 0
; — удаление ($5CD7, переводом); пробы рельефа впереди: вверху (±#10, −#14) проходимо (≥ #DFC) — поворот $5AE9; внизу
; (±#12, −#C) не опора (< #DFC) — падение $5CA6; иначе RET.
N_5A2B:         call NEnemyCheck
                jp c,.translated
                call CounterCore                ; $F63A
                or a
                jr z,.move
                ld hl,#5A2E
                push hl                         ; CALL $F63A: адрес возврата — перевод $5A2E
                NTAIL A_0FA57                   ; порождение — переводом
.move:          ld hl,#C0
                ld a,(ix+#1E)
                or a
                jr nz,.speed
                call NScrollX
                ld hl,#FF40
.speed:         ld (V_AX),hl
                call NAddX
                ld hl,#291A
                ld a,(ix+#1E)
                or a
                jr z,.table
                ld hl,#2922
.table:         ld (V_SI),hl                    ; SI — таблица кадров
                ld a,(#4000+#2EB6)
                and #18
                rrca
                rrca
                ld e,a
                ld d,0
                ld (V_BX),de                    ; BX = ([#2EB6] & #18) >> 2
                add hl,de
                call NReadES16                  ; BX = ES:[bx+si]
                jp c,.frameFail
                ld (V_BX),de
                call NSpriteAdd
                jp c,.spriteFail
                ld hl,#2982
                ld (V_DI),hl                    ; MOV DI,#2982
                call CollideSetup               ; $F694: хитбокс ES:DI
                jp c,.collideFail
                push ix
                call CollideA94
                pop ix
                jr c,.hit
                call NOnField
                jr c,.remove
                ld a,(#4000+#2FC4)
                or a
                jr nz,.remove
                ld hl,#10                       ; вперёд: ±#10, выше на #14
                ld a,(ix+#1E)
                or a
                jr nz,.ahead
                ld hl,-#10
.ahead:         ld (V_AX),hl
                ld de,-#14
                call NProbeA
                jp c,.probeFail1
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr c,.turn                      ; проходимо — поворот
                ld hl,#12                       ; под ногами: ±#12, выше на #C
                ld a,(ix+#1E)
                or a
                jr nz,.foot
                ld hl,-#12
.foot:          ld (V_AX),hl
                ld de,-#C
                call NProbeA
                jr c,.probeFail2
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jp c,NRet                       ; опора есть
                ld (ix+0),#A6
                ld (ix+1),#5C                   ; обработчик $5CA6 — падение
                jp NRet
.turn:          ld hl,#292A
                ld a,(ix+#1E)
                or a
                jr z,.turnTable
                ld hl,#2932
.turnTable:     ld (V_BX),hl
                ld (ix+#20),l
                ld (ix+#21),h
                ld (ix+#22),4
                ld (ix+0),#E9
                ld (ix+1),#5A                   ; обработчик $5AE9
                jp NRet
.hit:           NTAIL A_06083
.remove:        NTAIL A_060D7
.frameFail:     NTAIL A_05E5A
.spriteFail:    NTAIL A_05E5D
.collideFail:   NTAIL A_05E60
.probeFail1:    NTAIL A_05E7D
.probeFail2:    NTAIL A_05EA3
.translated:    ld a,$$K_05E2B
                ld hl,K_05E2B
                jp FARJP

; Сканы столкновений ядра ($F948, $F960) развёрнутыми проверками признака [si+1] (24 такта на неактивную запись вместо
; 42 у цикла): те же проверки прямоугольника по тем же записям в том же порядке, те же SI, CX, AX и CF на выходе.
; Для нативных вызовов (CollideSetup уже прочитал объект и хитбокс и отобразил эту страницу в W3). VDAC2+ (2026-09-25,
; скорость, партия 2): прямоугольник — BoxX по указателю записи (X и XR в BC и DE) вместо BoxTest по IX; попадание —
; общий хвост (SI и CX из HL и A). Вход .go — BC и DE уже загружены (цепочка NDamage). Портит AF, HL; BC, DE, IX, IY
; сохраняет.
; ROM $0F960 (IP $F560): 24 записей с #176.
NCollide60:     ld bc,(KC_X)
                ld de,(KC_XR)
.go:            ld a,(COLL_STATE)
                cp 2
                jr nz,.c0
                ld a,(COLL_60N)
                or a
                jr nz,.c0
                ld hl,#476                      ; кэш столкновений: в начале цикла списка живых записей не было —
                ld (V_SI),hl                    ; ни одной проверки (флаги в цикле только гаснут): SI, CX — как после
                ld hl,0                         ; LOOP, AX прежний, CF = 0
                ld (V_CX),hl
                xor a
                ret
.c0:            ld a,(#4000+#177)
                or a
                jp nz,.t0
.c1:            ld a,(#4000+#197)
                or a
                jp nz,.t1
.c2:            ld a,(#4000+#1B7)
                or a
                jp nz,.t2
.c3:            ld a,(#4000+#1D7)
                or a
                jp nz,.t3
.c4:            ld a,(#4000+#1F7)
                or a
                jp nz,.t4
.c5:            ld a,(#4000+#217)
                or a
                jp nz,.t5
.c6:            ld a,(#4000+#237)
                or a
                jp nz,.t6
.c7:            ld a,(#4000+#257)
                or a
                jp nz,.t7
.c8:            ld a,(#4000+#277)
                or a
                jp nz,.t8
.c9:            ld a,(#4000+#297)
                or a
                jp nz,.t9
.c10:           ld a,(#4000+#2B7)
                or a
                jp nz,.t10
.c11:           ld a,(#4000+#2D7)
                or a
                jp nz,.t11
.c12:           ld a,(#4000+#2F7)
                or a
                jp nz,.t12
.c13:           ld a,(#4000+#317)
                or a
                jp nz,.t13
.c14:           ld a,(#4000+#337)
                or a
                jp nz,.t14
.c15:           ld a,(#4000+#357)
                or a
                jp nz,.t15
.c16:           ld a,(#4000+#377)
                or a
                jp nz,.t16
.c17:           ld a,(#4000+#397)
                or a
                jp nz,.t17
.c18:           ld a,(#4000+#3B7)
                or a
                jp nz,.t18
.c19:           ld a,(#4000+#3D7)
                or a
                jp nz,.t19
.c20:           ld a,(#4000+#3F7)
                or a
                jp nz,.t20
.c21:           ld a,(#4000+#417)
                or a
                jp nz,.t21
.c22:           ld a,(#4000+#437)
                or a
                jp nz,.t22
.c23:           ld a,(#4000+#457)
                or a
                jp nz,.t23
                ld hl,#476
                ld (V_SI),hl                    ; SI — за последней записью
                ld hl,0
                ld (V_CX),hl                    ; CX = 0 после LOOP
                xor a                           ; CF = 0
                ret
.t0:            ld hl,#4000+#176+2
                call BoxX
                jp nc,.c1
                ld hl,#176
                ld a,24                          ; CX — ещё не уменьшенный LOOP
                jp .hit
.t1:            ld hl,#4000+#196+2
                call BoxX
                jp nc,.c2
                ld hl,#196
                ld a,23
                jp .hit
.t2:            ld hl,#4000+#1B6+2
                call BoxX
                jp nc,.c3
                ld hl,#1B6
                ld a,22
                jp .hit
.t3:            ld hl,#4000+#1D6+2
                call BoxX
                jp nc,.c4
                ld hl,#1D6
                ld a,21
                jp .hit
.t4:            ld hl,#4000+#1F6+2
                call BoxX
                jp nc,.c5
                ld hl,#1F6
                ld a,20
                jp .hit
.t5:            ld hl,#4000+#216+2
                call BoxX
                jp nc,.c6
                ld hl,#216
                ld a,19
                jp .hit
.t6:            ld hl,#4000+#236+2
                call BoxX
                jp nc,.c7
                ld hl,#236
                ld a,18
                jp .hit
.t7:            ld hl,#4000+#256+2
                call BoxX
                jp nc,.c8
                ld hl,#256
                ld a,17
                jp .hit
.t8:            ld hl,#4000+#276+2
                call BoxX
                jp nc,.c9
                ld hl,#276
                ld a,16
                jp .hit
.t9:            ld hl,#4000+#296+2
                call BoxX
                jp nc,.c10
                ld hl,#296
                ld a,15
                jp .hit
.t10:           ld hl,#4000+#2B6+2
                call BoxX
                jp nc,.c11
                ld hl,#2B6
                ld a,14
                jp .hit
.t11:           ld hl,#4000+#2D6+2
                call BoxX
                jp nc,.c12
                ld hl,#2D6
                ld a,13
                jp .hit
.t12:           ld hl,#4000+#2F6+2
                call BoxX
                jp nc,.c13
                ld hl,#2F6
                ld a,12
                jp .hit
.t13:           ld hl,#4000+#316+2
                call BoxX
                jp nc,.c14
                ld hl,#316
                ld a,11
                jp .hit
.t14:           ld hl,#4000+#336+2
                call BoxX
                jp nc,.c15
                ld hl,#336
                ld a,10
                jp .hit
.t15:           ld hl,#4000+#356+2
                call BoxX
                jp nc,.c16
                ld hl,#356
                ld a,9
                jp .hit
.t16:           ld hl,#4000+#376+2
                call BoxX
                jp nc,.c17
                ld hl,#376
                ld a,8
                jp .hit
.t17:           ld hl,#4000+#396+2
                call BoxX
                jp nc,.c18
                ld hl,#396
                ld a,7
                jp .hit
.t18:           ld hl,#4000+#3B6+2
                call BoxX
                jp nc,.c19
                ld hl,#3B6
                ld a,6
                jp .hit
.t19:           ld hl,#4000+#3D6+2
                call BoxX
                jp nc,.c20
                ld hl,#3D6
                ld a,5
                jp .hit
.t20:           ld hl,#4000+#3F6+2
                call BoxX
                jp nc,.c21
                ld hl,#3F6
                ld a,4
                jp .hit
.t21:           ld hl,#4000+#416+2
                call BoxX
                jp nc,.c22
                ld hl,#416
                ld a,3
                jp .hit
.t22:           ld hl,#4000+#436+2
                call BoxX
                jp nc,.c23
                ld hl,#436
                ld a,2
                jp .hit
.t23:           ld hl,#4000+#456+2
                call BoxX
                jp nc,.last
                ld hl,#456
                ld a,1
.hit:           ld (V_SI),hl
                ld l,a
                ld h,0
                ld (V_CX),hl
                scf
                ret
.last:          ld hl,#476
                ld (V_SI),hl
                ld hl,0
                ld (V_CX),hl
                xor a
                ret
                ASSERT (#176 & #1F) == #16          ; младшие байты записей ≡ #16 по модулю #20 — не больше #F6
; ROM $0F948 (IP $F548): 3 записи с #4D6.
NCollide48:     ld bc,(KC_X)
                ld de,(KC_XR)
.go:
.c0:            ld a,(#4000+#4D7)
                or a
                jp nz,.t0
.c1:            ld a,(#4000+#4F7)
                or a
                jp nz,.t1
.c2:            ld a,(#4000+#517)
                or a
                jp nz,.t2
                ld hl,#536
                ld (V_SI),hl                    ; SI — за последней записью
                ld hl,0
                ld (V_CX),hl                    ; CX = 0 после LOOP
                xor a                           ; CF = 0
                ret
.t0:            ld hl,#4000+#4D6+2
                call BoxX
                jp nc,.c1
                ld hl,#4D6
                ld a,3                          ; CX — ещё не уменьшенный LOOP
                jp .hit
.t1:            ld hl,#4000+#4F6+2
                call BoxX
                jp nc,.c2
                ld hl,#4F6
                ld a,2
                jp .hit
.t2:            ld hl,#4000+#516+2
                call BoxX
                jp nc,.last
                ld hl,#516
                ld a,1
.hit:           ld (V_SI),hl
                ld l,a
                ld h,0
                ld (V_CX),hl
                scf
                ret
.last:          ld hl,#536
                ld (V_SI),hl
                ld hl,0
                ld (V_CX),hl
                xor a
                ret
                ASSERT (#4D6 & #1F) == #16          ; так же

; ROM $F978 (IP $F578) по указателю записи: HL → #4000 + SI + 2 (поле X1; поля X1…Y2 — в одной странице 256 байт,
; младший байт SI не больше #F6 — ASSERT у сканов), BC = X объекта (KC_X), DE = XR = X + [bx] (KC_XR); KC_XL = X +
; [bx+2], KC_Y, KC_HB4, KC_HB6 — от CollideSetup. Ветви и AX — как у BoxTest (резидент): X < X1 — AX = XL, XL < X1 —
; нет; X ≥ X2 — AX = XR, XR ≥ X2 — нет; иначе Y: Y < Y1 — AX = Y + [bx+6], пересечение при AX ≥ Y1; Y ≥ Y2 — AX = Y +
; [bx+4], пересечение при AX < Y2; между — AX = Y, пересечение. Сравнения — байтами с памятью записи (SUB/SBC (HL)),
; без загрузок по IX (VDAC2+ 2026-09-25, скорость: отказ справа ≈140 тактов с вызовом против ≈300 у BoxTest). Выход:
; CF — пересечение, V_AX. Сохраняет BC, DE, IX, IY; портит AF, HL.
BoxX:           ld a,c
                sub (hl)
                inc l
                ld a,b
                sbc a,(hl)                      ; CF: X < X1
                jr c,.left
                inc l
                ld a,c
                sub (hl)
                inc l
                ld a,b
                sbc a,(hl)                      ; CF: X < X2
                jr c,.y5                        ; X1 ≤ X < X2 — к Y
                dec l
                ld a,e
                sub (hl)
                inc l
                ld a,d
                sbc a,(hl)                      ; $F99F: CF: XR < X2 — к Y
                jr c,.y5
                ld (V_AX),de                    ; нет: AX = XR, CF = 0
                ret
.left:          dec l                           ; $F994: AX = XL; XL < X1 — нет, иначе к Y
                ld a,(KC_XL)
                sub (hl)
                inc l
                ld a,(KC_XL+1)
                sbc a,(hl)                      ; CF: XL < X1
                jr nc,.y3
                ld hl,(KC_XL)
                ld (V_AX),hl
                or a                            ; CF = 0
                ret
.y3:            inc l
                inc l                           ; HL → запись + 5
.y5:            inc l                           ; HL → Y1 (запись + 6)
                push de
                ld de,(KC_Y)                    ; AX = Y
                ld a,e
                sub (hl)
                inc l
                ld a,d
                sbc a,(hl)                      ; CF: Y < Y1
                jr c,.low
                inc l
                ld a,e
                sub (hl)
                inc l
                ld a,d
                sbc a,(hl)                      ; CF: Y < Y2
                jr c,.inside
                dec l                           ; $F9B6: AX = Y + [bx+4]; AX < Y2 — пересечение
                push hl
                ld hl,(KC_HB4)
                add hl,de
                ld (V_AX),hl
                ex de,hl
                pop hl
                ld a,e
                sub (hl)
                inc l
                ld a,d
                sbc a,(hl)                      ; CF: AX < Y2
                pop de
                ret
.inside:        ld (V_AX),de                    ; $F992: внутри по Y — AX = Y, CF = 1
                pop de
                ret
.low:           dec l                           ; $F9AA: AX = Y + [bx+6]; AX ≥ Y1 — пересечение
                push hl
                ld hl,(KC_HB6)
                add hl,de
                ld (V_AX),hl
                ex de,hl
                pop hl
                ld a,e
                sub (hl)
                inc l
                ld a,d
                sbc a,(hl)                      ; CF: AX < Y1
                ccf
                pop de
                ret

; Края X объекта для BoxX — хвост CollideSetup (резидент), раз на объект: KC_XR = X + [bx], KC_XL = X + [bx+2] (по
; модулю #10000, как ADD ROM). CF = 0. Портит AF, DE, HL.
BoxEdges:       ld de,(KC_X)
                ld hl,(KC_HB0)
                add hl,de
                ld (KC_XR),hl
                ld hl,(KC_HB2)
                add hl,de
                ld (KC_XL),hl
                or a
                ret
KC_XR           DW 0                            ; X + [bx] (правый отказ, AX)
KC_XL           DW 0                            ; X + [bx+2] (левый отказ, AX)

; Холостые слоты оружия R-9 в цикле слотов ($0257): обработчики $395A…$3CEE (24 входа одной формы) при [#98] = 0 лишь
; пишут [bp+4] = #40, [bp+7] = 0, [bp+#17] = 0 и возвращаются (флаги после — мёртвые, регистры не меняются); $3D16 —
; голый RET. Такие слоты ядро цикла обходит без вызова. VDAC2+: пачкой — подряд идущие холостые слоты за один вход, как
; сделал бы цикл ROM (BP += #20, LOOP); их записи [#98] не задевают (+4, +5, +7, +#17 у BP, кратного #20). Вход: DE —
; IP обработчика слота V_BP (#20…#500, в окне W1), V_CX — счётчик LOOP. CF = 0 — слот V_BP не холостой (ничего не
; записано, DE сохранён); CF = 1 — холостые слоты обойдены: V_BP — следующий слот, V_CX — остаток LOOP (0 — цикл
; окончен; иначе слот V_BP ядро цикла обрабатывает само). Вход — из резидента через WeaponIdleFar.
WeaponIdle:     ld h,high WEAPON_IDLE
                ld l,e
                ld a,(hl)
                ld c,a
                and #7F
                cp d
                jp nz,.no
                ld a,(#4000+#98)
                or a
                jp nz,.launch                   ; запуск оружия — прежним циклом (холостые — лишь голые RET)
                ld hl,(V_CX)
                ld a,h
                or a
                jp nz,.no                       ; CX ≥ 256 — в цикле слотов не бывает: обычный вызов
                or l
                jp z,.no
                ld b,l                          ; B — счётчик LOOP
                ld d,high WEAPON_IDLE
                ld hl,(V_BP)
                ld a,l
                and #1F
                jp nz,.no                       ; BP не кратен #20 — обычный вызов (ниже SET 2,L и SET 4,L)
                set 6,h                         ; HL → слот в окне W1
                ld a,c                          ; A — байт таблицы слота
                ; VDAC2+ 2026-09-26 (скорость): [#98] = 0 на всю пачку (записи холостых его не задевают), слот — по
                ; HL, счётчик — B: ≈240 тактов на холостой слот вместо ≈340 у цикла по IX
.slot:          rla
                jr c,.ret                       ; $3D16 — голый RET
                set 2,l                         ; HL → [bp+4] (BP кратен #20)
                ld (hl),#40
                inc l
                ld (hl),0                       ; [bp+4] = #40
                inc l
                inc l
                ld (hl),0                       ; [bp+7] = 0
                set 4,l
                ld (hl),0                       ; [bp+#17] = 0
                ld a,l
                add a,#20-#17
                jr .step
.ret:           ld a,l
                add a,#20
.step:          ld l,a
                jr nc,.same
                inc h                           ; ADD BP,#20
.same:          dec b                           ; LOOP
                jr z,.fastEnd                   ; цикл окончен
                ld a,h
                cp #7F
                jr nc,.fastEnd                  ; у края рабочего ОЗУ — ядру цикла (оно уйдёт в перевод)
                ld e,(hl)
                inc l
                ld c,(hl)
                dec l                           ; C:E — IP обработчика следующего слота
                ld a,c
                sub #39
                cp 5
                jr nc,.fastEnd
                ld a,(de)                       ; байт таблицы (D — старший байт WEAPON_IDLE)
                ld e,a
                and #7F
                cp c
                jr nz,.fastEnd                  ; не холостой — ядру цикла
                ld a,e
                jp .slot
.fastEnd:       ld c,b
                ld b,0
                ld (V_CX),bc
                res 6,h
                ld (V_BP),hl
                scf
                ret
.launch:        bit 7,c
                jr z,.no                        ; не голый RET — обычный вызов
                ld a,c                          ; A — байт таблицы слота
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → слот
                ld bc,(V_CX)                    ; BC — счётчик LOOP
.lslot:         rla
                jr c,.adv                       ; $3D16 — голый RET
                ld (ix+4),#40
                ld (ix+5),0                     ; [bp+4] = #40
                ld (ix+7),0
                ld (ix+#17),0
.adv:           ld de,#20
                add ix,de                       ; ADD BP,#20
                dec bc                          ; LOOP
                ld a,b
                or c
                jr z,.end                       ; цикл окончен
                ld a,ixh
                cp #7F
                jr nc,.end                      ; у края рабочего ОЗУ — ядру цикла (оно уйдёт в перевод)
                ld e,(ix+0)
                ld d,(ix+1)                     ; DE — IP обработчика следующего слота
                ld a,d
                sub #39
                cp 5
                jr nc,.end
                ld h,high WEAPON_IDLE
                ld l,e
                ld a,(hl)
                ld l,a                          ; L — байт таблицы
                and #7F
                cp d
                jr nz,.end                      ; не холостой — ядру цикла
                ld a,l
                rla
                jr c,.adv                       ; голый RET — без проверки [#98]
                ld a,(#4000+#98)
                or a
                jr nz,.end                      ; запуск оружия — обычный вызов ядром
                ld a,l
                jr .lslot
.end:           ld (V_CX),bc
                push ix
                pop hl
                res 6,h
                ld (V_BP),hl
                scf
                ret
.no:            or a
                ret

; Запись спрайта C000:V_SI по описанию DE (6 байт) для объекта IX ($1BE9): CX = [bp+4], DX = [bp+8], AX = атрибут.
; Портит AF, BC, DE, HL.
NSpritePutCore: push de
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_CX),hl
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_DX),hl
                call NMapSprites
                ld hl,(V_SI)
                set 7,h
                pop de
                push de
                call NSpriteEntry
                pop hl
                ld a,(ix+6)
                ld (V_AX),a
                ld de,5
                add hl,de
                ld a,(hl)
                ld (V_AX+1),a
                ret

; --- Force: состояние возврата $24CE ------------------------------------------------------------------------------

; Уход в перевод из подпрограммы, которую нативный обработчик позвал CALL-ом Z80 вместо CALL процедуры ROM: адрес
; возврата Z80 снимается, на стек V30 кладётся адрес возврата процедуры ROM в обработчик (retip), дальше — перевод с
; инструкции label внутри этой процедуры (её RET вернёт в перевод обработчика).
                MACRO NSUBTAIL retip, label
                pop hl
                ld hl,retip
                push hl
                NTAIL label
                ENDM

; Слово ES:HL (ES = #1000 проверен вызывающим; страницы V30 4…7) → DE. CF = 1 — слово на границе страниц. Портит AF, BC,
; HL. Окно W2 — страница слова.
NWord1000:      ld a,h
                and #3F
                cp #3F
                jr c,.inside
                ld a,l
                inc a
                scf
                ret z                           ; смещение #3FFF
.inside:        ld a,h
                rlca
                rlca
                and 3
                add a,4
                push hl
                ld hl,W2_PAGE
                cp (hl)
                call nz,NMap2
                pop hl
                ld a,h
                and #3F
                or #80
                ld h,a
                ld e,(hl)
                inc hl
                ld d,(hl)
                or a
                ret

; Байт ES:HL (ES = #1000) → A. Портит F, BC, HL; окно W2 — страница байта.
NByte1000:      ld a,h
                rlca
                rlca
                and 3
                add a,4
                push hl
                ld hl,W2_PAGE
                cp (hl)
                call nz,NMap2
                pop hl
                ld a,h
                and #3F
                or #80
                ld h,a
                ld a,(hl)
                ret

; $1BE9 для нативных вызовов: спрайт объекта IX по описанию ES:V_BX в запись C000:V_SI (SI < #3F00). CF = 1 — описание
; через границу страницы (ничего не записано). Портит всё, кроме IX.
NSpritePut:     call NDescCache
                ret c
                call NSpritePutCore
                or a
                ret

; ROM $03094 (IP $2C94) для нативного вызова Force: X ≥ #120, иначе X = #128, Y = #100; рельеф впереди ($1EB5 в точке
; X + 8): стена (A < #DFC или B < #7D0) — X += шаг прокрутки [#2ED0]; иначе к цели [bp+#32]: разница ≥ 2 — X += #180,
; ≤ −2 — X += #FEC0 ($0672), иначе ничего. Регистры — как у ROM. CF = 1 — слово VRAM на границе страниц: X прежний (после
; возможной установки #128/#100 — то же сделал бы и ROM до $2CA5).
NForceX:        ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#120
                add hl,de
                jr c,.probe
                ld (ix+4),#28
                ld (ix+5),1                     ; X = #128
                ld (ix+8),0
                ld (ix+9),1                     ; Y = #100
.probe:         ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH [bp+4]
                ld de,8
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                call NTerrainAB                 ; $1EB5
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP [bp+4]
                ret c
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.scroll
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jr nc,.scroll
                ld l,(ix+#32)
                ld h,(ix+#33)
                ld e,(ix+4)
                ld d,(ix+5)
                or a
                sbc hl,de                       ; BX = цель − X
                ld (V_BX),hl
                ret z                           ; на месте (CF = 0)
                jr nc,.right
                ld de,-2
                push hl
                or a
                sbc hl,de
                pop hl
                jr nc,.stay                     ; BX ≥ −2 (−2, −1) — на месте
                ld hl,#FEC0
                jr .move
.right:         ld de,2
                push hl
                or a
                sbc hl,de
                pop hl
                jr c,.stay                      ; BX < 2
                ld hl,#180
.move:          ld (V_AX),hl
                call NAddX                      ; $0672
.stay:          or a
                ret
.scroll:        ld de,(#4000+#2ED0)
                ld (V_AX),de                    ; AX = шаг прокрутки
                ld l,(ix+4)
                ld h,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                or a
                ret

; Флаги $2835 ROM (TEST WORD [bp+#3A],#FFFF): Z80 Z — слово = 0, S — его старший бит. Портит AF.
NTest3A:        ld a,(ix+#3A)
                or (ix+#3B)
                ret z
                ld a,(ix+#3B)
                or #01                          ; Z = 0, S — старший бит слова
                ret

; ROM $02C78 (IP $2878) для нативного вызова из Force: спрайт Force в запись #3E8 по уровню [bp+#12]: 0 — описание
; #26FE; 1 — кадр [bp+#13] (шаг раз в 4 кадра по знаку [bp+#3A], если оно ≠ 0), таблица #144C; 2 — кадр 0…5 раз в 4
; кадра, при [bp+#3A] = 0 — кадр = AL на входе; таблицы #1458/#1470/#1464/#147C по знаку [bp+#3A] и биту 0 [bp+#14];
; 3 — направление движения (X против прежнего [bp+#2A]/[bp+#34], знак [bp+#3A]) → [bp+#15] по таблице #15AE, кадр 0…3
; раз в 8 кадров, описание из #1488. Регистры — как у ROM. Отказ чтения описания или таблицы (граница страницы ROM —
; для этих таблиц не бывает) — сам уходит в перевод с инструкции внутри $2878 (адрес возврата в $24CE — #2523).
NForceSprite:   ld hl,#3E8
                ld (V_SI),hl                    ; SI = #3E8
                ld a,(ix+#12)
                cp 3
                jp z,.level3
                cp 2
                jp z,.level2
                cp 1
                jr z,.level1
                ld hl,#26FE
                ld (V_BX),hl
                call NSpritePut
                ret nc
                NSUBTAIL #2523, A_02C90
.level1:        call NTest3A
                jr z,.frame1
                ld a,(#4000+#2EB6)
                and 3
                jr nz,.frame1
                call NTest3A
                ld a,1
                jp p,.dir1
                ld a,#FF
.dir1:          add a,(ix+#13)
                cp #FF
                jr z,.wrap5
                cp 6
                jr c,.set1
                xor a
                jr .set1
.wrap5:         ld a,5
.set1:          ld (ix+#13),a
                ld (ix+#35),a
                ld (V_AX),a                     ; AL
.frame1:        ld l,(ix+#13)
                ld h,0
                add hl,hl
                ld (V_BX),hl                    ; BX = кадр·2
                ld de,#144C
                add hl,de
                call NWord1000                  ; BX = ES:[bx+#144C]
                jr c,.fail1
                ld (V_BX),de
                call NSpritePut
                ret nc
                NSUBTAIL #2523, A_02C74
.fail1:         NSUBTAIL #2523, A_02C6F
.level2:        ld a,(#4000+#2EB6)
                and 3
                jr nz,.check2
                ld a,(ix+#13)
                inc a
                cp 6
                jr c,.store2
                xor a
.store2:        ld (ix+#13),a
                ld (ix+#35),a
                ld (V_AX),a                     ; AL
.check2:        call NTest3A
                jr nz,.sign2
                ld a,(V_AX)
                ld (ix+#13),a                   ; [bp+#3A] = 0: кадр = AL (ZF = 1 — и SF = 0: к $2923)
                ld hl,#1464
                jr .odd2
.sign2:         ld hl,#1464
                jp p,.odd2
                ld hl,#1458
                bit 0,(ix+#14)
                jr nz,.table2
                ld hl,#1470
                jr .table2
.odd2:          bit 0,(ix+#14)
                jr nz,.table2
                ld hl,#147C
.table2:        ld (V_DI),hl                    ; DI — таблица
                ld e,(ix+#13)
                ld d,0
                ex de,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = кадр·2
                add hl,de
                call NWord1000                  ; BX = ES:[bx+di]
                jr c,.fail2
                ld (V_BX),de
                call NSpritePut
                ret nc
                NSUBTAIL #2523, A_02D39
.fail2:         NSUBTAIL #2523, A_02D36
.level3:        ld bc,0                         ; B — CL, C — CH (XOR CX,CX)
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_AX),hl                    ; $2825: AX = X
                ld e,(ix+#2A)
                ld d,(ix+#2B)
                or a
                sbc hl,de                       ; CMP AX,[bp+#2A]
                jr nz,.xMoved
                ld a,(ix+3)
                ld (V_AX),a                     ; AL = [bp+3]
                cp (ix+#34)
                jr z,.xDone
.xMoved:        ld b,1
                jr nc,.xSet
                ld b,2
.xSet:          ld c,b                          ; OR CH,CL (CH был 0)
.xDone:         call NTest3A
                jr z,.yDone
                ld b,8
                jp p,.ySet
                ld b,4
.ySet:          ld a,c
                or b
                ld c,a                          ; OR CH,CL
.yDone:         ld a,b
                ld (V_CX),a
                ld a,c
                ld (V_CX+1),a                   ; CX = CH:CL
                or a
                jr nz,.dir3
                ld (ix+#13),0
.dir3:          ld l,c
                ld h,0
                ld (V_BX),hl                    ; BX = CH
                ld de,#15AE
                add hl,de
                call NByte1000                  ; AL = ES:[bx+#15AE]
                ld (V_AX),a
                ld (ix+#15),a
                ld a,(#4000+#2EB6)
                and 7
                jr nz,.frame3
                inc (ix+#13)
                ld a,(ix+#13)
                cp 4
                jr c,.frame3
                ld (ix+#13),0
.frame3:        ld l,(ix+#15)
                ld h,0
                add hl,hl
                ld (V_BX),hl
                ld de,#1488
                add hl,de
                call NWord1000                  ; DI = ES:[bx+#1488]
                jr c,.fail3a
                ld (V_DI),de
                ld l,(ix+#13)
                ld h,0
                add hl,hl
                ld (V_BX),hl
                add hl,de
                call NWord1000                  ; BX = ES:[bx+di]
                jr c,.fail3b
                ld (V_BX),de
                call NSpritePut
                ret nc
                NSUBTAIL #2523, A_02CEE
.fail3a:        NSUBTAIL #2523, A_02CDF
.fail3b:        NSUBTAIL #2523, A_02CEB

; ROM $028CE (IP $24CE, обработчик Force в состоянии возврата): [bp+#A] = 0; при уровне [bp+#12] ≠ 0 — прежний X
; ([bp+#2A], [bp+#34]), [bp+#3A] = [bp+#C] (если ≠ 0), при бите 6 [#2F23] — [bp+#B] = 1; цель X [bp+#32] — из истории R-9
; ([[bp+#24]+#1D60]) или #1A0 / #238 по X игрока [#24]; X к цели ($2C94) и рельеф ($2AB4). Затем спрайт ($2878),
; прямоугольник по таблице ES:#15BE ($38F4), разрушаемые тайлы вокруг ($2702), захват игроком ($F485 с хитбоксом #1428:
; сторона [bp+#A] = [bp+#14] по X, звук #37, обработчик $2581, [#3F] = 1); смена уровня ([#3E] ≠ [bp+#12]) — переводом.
; Условия: DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00. Регистры — как у ROM.
N_24CE:         call NEnemyCheck
                jp c,.translated
                ld (ix+#0A),0
                ld a,(ix+#12)
                or a
                jp z,.render
                ld l,(ix+4)
                ld h,(ix+5)
                ld (ix+#2A),l
                ld (ix+#2B),h
                ld a,(ix+3)
                ld (ix+#34),a
                ld l,(ix+#0C)
                ld h,(ix+#0D)
                ld (V_AX),hl                    ; AX = [bp+#C]
                ld a,h
                or l
                jr z,.noSpeed
                ld (ix+#3A),l
                ld (ix+#3B),h
.noSpeed:       ld a,(#4000+#2F23)
                and #40
                jr z,.noHistory
                ld (ix+#0B),1
.noHistory:     ld a,(ix+#0B)
                or a
                jr z,.fixed
                ld l,(ix+#24)
                ld h,(ix+#25)
                ld de,#1D60
                add hl,de
                ld a,h
                cp #3F
                jp nc,.historyFar               ; вне рабочего ОЗУ — переводом с $24FF
                ld e,(ix+#24)
                ld d,(ix+#25)
                ld (V_BX),de                    ; BX = [bp+#24]
                set 6,h
                ld e,(hl)
                inc hl
                ld d,(hl)
                ex de,hl
                jr .target
.fixed:         ld de,(#4000+#24)
                ld hl,-#1F8
                add hl,de
                ld hl,#1A0
                jr c,.target                    ; [#24] ≥ #1F8
                ld hl,#238
.target:        ld (V_AX),hl
                ld (ix+#32),l
                ld (ix+#33),h
                call NForceX                    ; $2C94
                jp c,.tailX
                call N2AB4Core                  ; $2AB4
                jp c,.tail2AB4
.render:        call NForceSprite               ; $2878 (отказы уходят в перевод сами)
                ld a,(ix+#12)
                and #7F
                add a,a
                ld l,a
                ld h,0
                ld (V_BX),hl                    ; BX = (уровень & #7F)·2
                ld de,#15BE
                add hl,de
                call NWord1000                  ; SI = ES:[bx+#15BE]
                jp c,.tailHitbox
                ld (V_SI),de
                ex de,hl
                call NHitbox                    ; $38F4
                jp c,.tailHitboxCall
                call N2702Core                  ; $2702
                jp c,.tail2702
                ld hl,#1428
                ld (V_BX),hl                    ; MOV BX,#1428
                call CollideSetup
                jp c,.tailCapture
                push ix
                call Collide85                  ; $F485
                pop ix
                jr nc,.level
                ld (ix+#0A),1
                ld (ix+#14),1
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,(#4000+#24)
                ld (V_CX),de                    ; CX = X игрока
                or a
                sbc hl,de
                ld (V_AX),hl                    ; AX = X − X игрока
                jr c,.side
                ld (ix+#0A),0
                ld (ix+#14),0
.side:          ld a,#37
                ld (V_CX),a                     ; MOV CL,#37
                call NSound
                ld (ix+0),#81
                ld (ix+1),#25                   ; обработчик $2581
                ld a,1
                ld (#4000+#3F),a
.level:         ld a,(#4000+#3E)
                ld (V_AX),a                     ; AL = [#3E]
                cp (ix+#12)
                jp z,NRet
                NTAIL A_02972                   ; смена уровня — переводом
.translated:    ld a,$$K_028CE
                ld hl,K_028CE
                jp FARJP
.historyFar:    NTAIL A_028FF
.tailX:         ld hl,#251D
                push hl                         ; адрес возврата из $2C94
                NTAIL A_030A5
.tail2AB4:      NTAIL A_0291D
.tailHitbox:    NTAIL A_0292C
.tailHitboxCall: NTAIL A_02931
.tail2702:      NTAIL A_02934
.tailCapture:   NTAIL A_02937

; ROM $08C61 (IP $8861, обработчик мелкого врага этапа 2 — потомок $8817): X += шаг прокрутки [#2ED0] и скорость
; ES:[#3B2A + уровень [#2F2E]·2] ($0672); Y к точке [[bp+#30]+#2A] − #20 + (случайное $EDE9 & #3F) — ±#10 ($0689) и
; покачивание ±#40 по биту 6 счётчика [bp+#28] ($0689); кадр [bp+#20] + 1 → описание #3BB2 + (кадр & #C)·1,5 ($1BCC);
; столкновения с хитбоксом #3C12 ($F694: попадание — конец $88E0 переводом); таймер [bp+#36] (≠ 0 — минус 1, ноль —
; прицеливание $890A переводом); вне поля ($1D6B) или [#2FC4] ≠ 0 — конец $88FD переводом. Регистры — как у ROM,
; флаги после RET не живут. Условия: DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00, слово [[bp+#30]+#2A] —
; в рабочем ОЗУ до #3F00; иначе перевод с входа.
N_8861:         call NEnemyCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld de,#2A
                add hl,de
                jp c,.translated
                ld a,h
                cp #3F
                jp nc,.translated               ; [bx+#2A] — не прямым чтением окна W1
                set 6,h
                ld (N_PARENT),hl                ; → слово [bx+#2A] в окне W1
                ld hl,(#4000+#2ED0)
                ld (V_AX),hl                    ; AX = [#2ED0]
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld a,(#4000+#2F2E)
                ld l,a
                ld h,0
                add hl,hl
                ld (V_BX),hl                    ; BX = уровень·2
                ld de,#3B2A
                add hl,de
                call NWord1000                  ; AX = ES:[bx+#3B2A]
                jp c,.failSpeed
                ld (V_AX),de
                ex de,hl
                call NAddX                      ; $0672
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_BX),hl                    ; BX = [bp+#30]
                ld hl,(N_PARENT)
                ld e,(hl)
                inc hl
                ld d,(hl)
                push de                         ; CX = [bx+#2A] — до записей $EDE9, как у ROM
                ; $EDE9: DL = [#2F28]; AL = [#2F29] + [#2F2A], AH = [#2F2A]; затем [#2F28] = AL, [#2F29] = DL,
                ; [#2F2A] = прежний [#2F29]. BX и CX сохраняются, DH не меняется.
                ld a,(#4000+#2F28)
                ld (V_DX),a
                ld c,a                          ; C — прежний [#2F28]
                ld a,(#4000+#2F2A)
                ld b,a                          ; B — прежний [#2F2A]
                ld a,(#4000+#2F29)
                ld (#4000+#2F2A),a
                add a,b
                ld (#4000+#2F28),a
                ld b,a                          ; B — AL
                ld a,c
                ld (#4000+#2F29),a
                ld a,b
                and #3F
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AND AX,#3F
                pop de                          ; DE = CX
                add hl,de
                ld de,-#20
                add hl,de                       ; CX − #20 + AX
                ld (V_CX),hl
                ex de,hl                        ; DE = CX
                ld l,(ix+8)
                ld h,(ix+9)
                or a
                sbc hl,de                       ; CMP [bp+8],CX
                ld hl,#FFF0
                jr nc,.moveY                    ; Y ≥ CX — вверх
                ld hl,#10
.moveY:         ld (V_AX),hl
                call NAddY                      ; $0689
                inc (ix+#28)
                ld hl,#40
                bit 6,(ix+#28)
                jr z,.sway
                ld hl,#FFC0
.sway:          ld (V_AX),hl
                call NAddY                      ; $0689
                ld l,(ix+#20)
                ld h,(ix+#21)
                inc hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; INC WORD [bp+#20]
                ld a,l
                and #0C
                ld c,a                          ; BX = [bp+#20] & #C
                rrca                            ; AX = BX >> 1
                ld (V_AX),a
                add a,c
                ld l,a
                xor a
                ld (V_AX+1),a
                ld h,a
                ld de,#3BB2
                add hl,de
                ld (V_BX),hl                    ; BX = #3BB2 + BX + AX
                call NSpriteAdd                 ; $1BCC
                jp c,.failSprite
                ld hl,#3C12
                ld (V_DI),hl                    ; MOV DI,#3C12
                call CollideSetup               ; $F694: хитбокс ES:DI
                jp c,.failCollide
                push ix
                call CollideA94
                pop ix
                jp c,.hit                       ; попадание — $88E0 переводом
                ld l,(ix+#36)
                ld h,(ix+#37)
                ld a,h
                or l
                jr z,.field
                dec hl
                ld (ix+#36),l
                ld (ix+#37),h                   ; DEC WORD [bp+#36]
                ld a,h
                or l
                jp z,.aim                       ; таймер вышел — $890A переводом
.field:         call NOnField                   ; $1D6B
                jp c,.remove
                ld a,(#4000+#2FC4)
                or a
                jp nz,.remove
                jp NRet
.translated:    ld a,$$K_08C61
                ld hl,K_08C61
                jp FARJP
.failSpeed:     NTAIL A_08C6F                   ; не бывает: таблица скорости в одной странице
.failSprite:    NTAIL A_08CBC
.failCollide:   NTAIL A_08CC2
.hit:           NTAIL A_08CE0
.aim:           NTAIL A_08D0A
.remove:        NTAIL A_08CFD

; ROM $07E3F (IP $7A3F) и $07EFA (IP $7AFA) — звенья червя этапа 5 (formation child $7A1E и $7AD9): обработчики
; объекта V_BP из цикла объектов — NativeHandler через переходник резидента WormFar (окно W3 — нативная страница;
; DE — IP обработчика: вариант). Профиль этапа 5 (RT_OBJPROFILE, 25.09): $7A3F со всеми вызовами — 15,4 % тактов.
; [2FC4] ≠ 0 — $7C3D; таймер [bp+24] ≠ 0 — DEC, по нулю $7B85 / $7BA0; иначе звено BX = [bp+3C], AL = [bx+1E]: бит 1
; — задержка [bp+24] = AX = [bx+24] + 4 и [bp+17] = 3 (у $7A3F до неё ещё [bp+1E] = 2); бит 0 — [bp+1E] = 1 и $7C9E /
; $7CA6; иначе [bp+17] = 2, [bp+20] = ([bp+20] + 1) & #7F и при [bp+20] < #1F — [bp+17] = 1. Затем скрипт $F5C1 (CF —
; $7C3D), спрайт $7D22 по описанию BX = #3676 / #371E + [bp+16]·6 (AX = [bp+16]·2; вспышка: [bp+3F] ≠ 0 — DEC, при
; (& 3) = 0 — спрайт с ресурсом [bp+6] = [bp+3E], AL = он же, затем [bp+6] прежний — PUSH/POP ROM), урон $F6DA (у
; $7A3F через кадр — при AX = ([2EB6] ^ [bp+18]) & 1 ≠ 0, DI = #37CE; у $7AFA каждый кадр, DI = #37D6; попадание —
; [bp+3F] = #0C, CL = #57 и звук $0303), [bp+1F] ≥ 6 — $7C77. Регистры V30 — как у ROM (ядра и нативные вызовы ставят
; свои так же); флаги у выходов и после RET не живут (flags.liveness), остатки PUSH/CALL ниже SP сверка не сравнивает.
; Условия до записей (иначе A = 1 — обычный вызов): DS = #4000, ES = #1000, [2FC4] = 0, BP кратен #20 и меньше #3F00;
; у таймера — ещё [bp+17] ≠ 0 (условие ядра скрипта), у звена — BX < #3F00. Описание (не дальше #3C75 + 5) и хитбокс
; ES:#37CE / #37D6 не переходят границу страницы V30 — NSpriteAdd и NDamage здесь не отказывают. Выход: A = 0.
; Выход нативного обработчика объекта в перевод с середины (HandlerBail резидента: кадр вызова ROM — как у
; обычного CALL [bp]), DE — IP возврата вложенного вызова (0 — нет).
                MACRO NBAIL label
                ld a,$$label
                ld hl,label
                jp HandlerBail
                ENDM
N_WORM_ENTRY:   ld a,e
                sub low #7A3F
                ld (N_WORM),a                   ; 0 — $7A3F, иначе $7AFA
                ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,.not
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.not
                ld a,(#4000+#2FC4)
                or a
                jr nz,.not                      ; $7C3D — обычным вызовом
                ld hl,(V_BP)
                ld a,l
                and #1F
                jr nz,.not
                ld a,h
                cp #3F
                jr nc,.not
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld l,(ix+#24)
                ld h,(ix+#25)
                ld a,h
                or l
                jr z,.link
                ld a,(ix+#17)
                or a
                jr z,.not                       ; скрипт без шагов — ядро его не берёт: обычным вызовом
                dec hl
                ld (ix+#24),l
                ld (ix+#25),h                   ; DEC WORD [bp+24]
                ld a,h
                or l
                jp nz,.script
                ld de,0
                ld a,(N_WORM)
                or a
                jr nz,.timer2
                NBAIL A_07F85                   ; $7B85
.timer2:        NBAIL A_07FA0                   ; $7BA0
.not:           ld a,1
                ret
.link:          ld l,(ix+#3C)
                ld h,(ix+#3D)
                ld a,h
                cp #3F
                jr nc,.not                      ; звено у края рабочего ОЗУ
                ld (V_BX),hl                    ; BX = [bp+3C]
                set 6,h
                ld de,#1E
                add hl,de
                ld a,(hl)
                ld (V_AX),a                     ; AL = [bx+1E]
                bit 1,a
                jr z,.link1
                ld a,(N_WORM)
                or a
                jr nz,.delay
                ld (ix+#1E),2                   ; только у $7A3F
.delay:         ld de,#24-#1E
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ex de,hl
                ld de,4
                add hl,de
                ld (V_AX),hl                    ; AX = [bx+24] + 4
                ld (ix+#24),l
                ld (ix+#25),h
                ld (ix+#17),3
                jr .script
.link1:         bit 0,a
                jr z,.link2
                ld (ix+#1E),1
                ld de,0
                ld a,(N_WORM)
                or a
                jr nz,.link1b
                NBAIL A_0809E                   ; $7C9E
.link1b:        NBAIL A_080A6                   ; $7CA6
.link2:         ld (ix+#17),2
                ld l,(ix+#20)
                inc l                           ; INC WORD и AND #7F: старший байт — 0, младший — (младший + 1) & #7F
                ld a,l
                and #7F
                ld (ix+#20),a
                ld (ix+#21),0
                cp #1F
                jr nc,.script
                ld (ix+#17),1
.script:        call ScriptCore                 ; $F5C1 (IX → [bp]): AX, BX, CX — как у ROM; CF
                jr nc,.sprite
                ld de,0
                NBAIL A_0803D                   ; $7C3D
.sprite:        ld l,(ix+#16)
                ld h,0
                add hl,hl
                ld (V_AX),hl                    ; AX = [bp+16]·2
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; [bp+16]·6
                ld de,#3676
                ld a,(N_WORM)
                or a
                jr z,.base
                ld de,#371E
.base:          add hl,de
                ld (V_BX),hl                    ; BX — описание спрайта
                ld a,(ix+#3F)                   ; $7D22: вспышка
                or a
                jr z,.plain
                dec a
                ld (ix+#3F),a
                and 3
                jr nz,.plain
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3E)
                ld (V_AX),a                     ; AL = [bp+3E]
                ld (ix+6),a
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                jr .damage
.plain:         call NSpriteAdd                 ; $1BCC
.damage:        push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                ld hl,#37D6
                ld a,(N_WORM)
                or a
                jr nz,.probe                    ; $7AFA — каждый кадр
                ld hl,(#4000+#2EB6)
                ld a,(iy+#18)
                xor l
                and 1
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = ([2EB6] ^ [bp+18]) & 1
                jr z,.final
                ld hl,#37CE
.probe:         ld (V_DI),hl                    ; DI — хитбокс
                call NDamage                    ; $F6DA: ZF — урон не изменился
                jr z,.final
                ld (iy+#3F),#0C
                ld a,#57
                ld (V_CX),a                     ; CL = #57
                call NSound                     ; $0303
.final:         ld a,(iy+#1F)
                cp 6
                jr nc,.end
                xor a                           ; исполнен
                ret
.end:           ld de,0
                NBAIL A_08077                   ; $7C77

; ROM $0E557 (IP $E157) и $0E6AA (IP $E2AA) — турели этапа 3 (дети spawn-table $E129 и $E277): обработчики объекта,
; вход NATIVE — цикл объектов зовёт их CALL [bp] через диспетчеризацию, возврат — NRet (сразу в ядро цикла). Профиль
; этапа 3 (RT_OBJPROFILE, 25.09): $E2AA и $E157 со всеми вызовами — 6,5 и 6,4 % тактов. X += [2ED4], Y += [2ED6]
; (AX = [2ED6]); сектор к R-9 ($1D89, BX = #20) и описание BX = ES:[сектор >> 1 + [bp+30]]; вспышка: [bp+3D] ≠ 0 —
; DEC, в нечётном кадре ([2EB6] & 1) — спрайт с ресурсом [bp+6] = [bp+3C] (AL — он же; PUSH/POP ROM), иначе — обычный
; спрайт $1BCC; помощник стрельбы ($E201; у $E2AA — $E361 при [bp+30] = #8258, иначе $E3CA): [bp+26] + 1 (AX), равен
; [bp+2A] — выстрел, не меньше [bp+2C] — [bp+26] = 0 и выстрел; выстрел (сектор, новый объект $03A6, ресурс $51EE) —
; переводом с места в помощнике, адрес возврата CALL ROM — на стеке V30; урон $F6DA (DI = #8250 / [bp+10]; попадание
; — [bp+3D] = 5, CL = #56, звук $0303); затем уходы: у $E157 — [[bp+3E]+3E] ≠ 0 или AL = [bp+1F] ≥ [bp+2F] — $E1DE,
; [2FC4] ≠ 0 или [bp+4] < #130 — $E1CB; у $E2AA — те же проверки в порядке AL, [[bp+3E]+3E] ($E33E), [2FC4] и
; [bp+4] < #120 ($E32B). Регистры V30 — как у ROM; флаги у выходов и после RET не живут (flags.liveness). Условия до
; записей (иначе перевод с входа): DS = #4000, ES = #1000, BP кратен #20 и меньше #3F00, [bp+3E] < #3F00.
N_E157:         xor a
                jr N_TURRET
N_E2AA:         ld a,1
N_TURRET:       ld (N_TUR),a
                ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jr nz,.translated
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                jr nz,.translated
                ld hl,(V_BP)
                ld a,l
                and #1F
                jr nz,.translated
                ld a,h
                cp #3F
                jr nc,.translated
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
                ld a,(ix+#3F)
                cp #3F
                jr c,.body                      ; [bp+3E] < #3F00
.translated:    ld a,(N_TUR)
                or a
                jr nz,.translated2
                ld a,$$K_0E557
                ld hl,K_0E557
                jp FARJP
.translated2:   ld a,$$K_0E6AA
                ld hl,K_0E6AA
                jp FARJP
.body:          ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; X += [2ED4]
                ld hl,(#4000+#2ED6)
                ld (V_AX),hl                    ; AX = [2ED6]
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; Y += AX
                ld hl,#20
                ld (V_BX),hl                    ; BX = #20 — R-9
                ld hl,#4000+#20
                push ix
                pop de
                call NAimCore                   ; $1D89: V_BX — сектор; V_SI, V_DI, V_DX, V_AX, V_CX — как у ROM
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix
                ld hl,(V_BX)
                srl h
                rr l                            ; SHR BX,1
                ld e,(ix+#30)
                ld d,(ix+#31)
                add hl,de                       ; + [bp+30]
                ld (V_BX),hl
                call NWord1000                  ; DE = ES:[bx]
                jr c,.descFail
                ld (V_BX),de                    ; BX — описание спрайта
                ld a,(ix+#3D)                   ; вспышка
                or a
                jr z,.plain
                dec a
                ld (ix+#3D),a
                ld a,(#4000+#2EB6)
                rra
                jr nc,.plain                    ; чётный кадр — обычный спрайт
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3C)
                ld (V_AX),a                     ; AL = [bp+3C]
                ld (ix+6),a
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                jr .timer
.descFail:      ld a,(N_TUR)                    ; не бывает: таблица описаний — не на границе страницы
                or a
                jr nz,.descFail2
                NTAIL A_0E56E
.descFail2:     NTAIL A_0E6C1
.plain:         call NSpriteAdd                 ; $1BCC
.timer:         ld l,(ix+#26)
                ld h,(ix+#27)
                inc hl
                ld (ix+#26),l
                ld (ix+#27),h                   ; INC WORD [bp+26]
                ld (V_AX),hl                    ; AX = [bp+26]
                ld a,l
                cp (ix+#2A)
                jr nz,.notEqual
                ld a,h
                cp (ix+#2B)
                jp z,.fireA                     ; = [bp+2A] — выстрел
.notEqual:      ld e,(ix+#2C)
                ld d,(ix+#2D)
                or a
                sbc hl,de
                jp nc,.fireB                    ; ≥ [bp+2C] — сброс и выстрел
.damage:        ld hl,#8250
                ld a,(N_TUR)
                or a
                jr z,.di
                ld l,(ix+#10)
                ld h,(ix+#11)                   ; $E2AA: DI = [bp+10]
.di:            ld (V_DI),hl
                push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                call NDamage                    ; $F6DA: ZF — урон не изменился
                jr z,.post
                ld (iy+#3D),5
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound                     ; $0303
.post:          push iy
                pop ix
                ld a,(N_TUR)
                or a
                jr nz,.post2
                call .link                      ; $E157: BX = [bp+3E]; [bx+3E] ≠ 0 — уход $E1DE
                jr nz,.destroy157
                ld a,(ix+#1F)
                ld (V_AX),a                     ; AL = [bp+1F]
                cp (ix+#2F)
                jr nc,.destroy157
                ld de,#130
                call .bounds                    ; [2FC4] ≠ 0 или [bp+4] < #130 — CF
                jp nc,NRet
                NTAIL A_0E5CB                   ; $E1CB
.destroy157:    NTAIL A_0E5DE                   ; $E1DE
.post2:         ld a,(ix+#1F)
                ld (V_AX),a                     ; AL = [bp+1F]
                cp (ix+#2F)
                jr nc,.destroy2AA
                call .link
                jr nz,.destroy2AA
                ld de,#120
                call .bounds
                jp nc,NRet
                NTAIL A_0E72B                   ; $E32B
.destroy2AA:    NTAIL A_0E73E                   ; $E33E
; BX = [bp+3E] (V_BX); NZ — слово [bx+3E] ≠ 0. Портит AF, DE, HL.
.link:          ld l,(ix+#3E)
                ld h,(ix+#3F)
                ld (V_BX),hl
                set 6,h
                ld de,#3E
                add hl,de
                ld a,(hl)
                inc hl
                or (hl)
                ret
; CF = 1 — [2FC4] ≠ 0 или [bp+4] < DE. Портит AF, HL.
.bounds:        ld a,(#4000+#2FC4)
                or a
                jr nz,.boundsOut
                ld l,(ix+4)
                ld h,(ix+5)
                sbc hl,de                       ; CF = 0 после OR: CF — [bp+4] < DE
                ret
.boundsOut:     scf
                ret
; Выстрел — переводом с места в помощнике: адрес возврата его CALL ROM — на стек V30 (он же стек Z80), затем туда.
.fireA:         call .helper                    ; HL — возврат, DE — помощник: A — «равно», B — «сброс»
                push hl
                ex de,hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld a,(N_FIREPAGE)
                jp FARJP
.fireB:         call .helper
                push hl
                ex de,hl
                inc hl
                inc hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld a,(N_FIREPAGE+1)
                jp FARJP
; HL — адрес возврата CALL помощника (V30), DE → пара меток помощника (N_FIRE*), N_FIREPAGE — их страницы.
.helper:        ld a,(N_TUR)
                or a
                ld hl,#E199
                ld de,N_FIRE201
                jr z,.helperPages
                ld a,(ix+#30)
                cp #58
                jr nz,.helper3CA
                ld a,(ix+#31)
                cp #82
                jr nz,.helper3CA
                ld hl,#E2F9
                ld de,N_FIRE361
                jr .helperPages
.helper3CA:     ld hl,#E2F3
                ld de,N_FIRE3CA
.helperPages:   push hl
                ex de,hl
                ld de,4
                add hl,de
                ld a,(hl)
                ld (N_FIREPAGE),a
                inc hl
                ld a,(hl)
                ld (N_FIREPAGE+1),a
                ld de,-5
                add hl,de
                ex de,hl
                pop hl
                ret
; Метки выстрела помощников: «равно [bp+2A]», «сброс [bp+26]» и их страницы.
N_FIRE201:      DW A_0E617, A_0E612
                DB $$A_0E617, $$A_0E612
N_FIRE361:      DW A_0E777, A_0E772
                DB $$A_0E777, $$A_0E772
N_FIRE3CA:      DW A_0E7E0, A_0E7DB
                DB $$A_0E7E0, $$A_0E7DB

; ROM $0F925 (IP $F525) для нативных цепочек: записи #B6 и #D6 при [si+1] ≠ 0 — пересечение: [si+1] = 0, CF = 1;
; иначе CF = 0 и SI = #D6 (AX — от последней проверки). Как первая половина $F8BF (CollideBF). Вход .go — BC = X, DE =
; XR уже загружены (CollideSetup). Портит AF, HL; BC, DE, IX, IY сохраняет.
NCollideB6:     ld bc,(KC_X)
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
                ld (#4000+#B7),a                ; [si+1] = 0
                scf
                ret
.second:        ld hl,#D6
                ld (V_SI),hl
                ld a,(#4000+#D7)
                or a
                ret z                           ; CF = 0 (TEST)
                ld hl,#4000+#D6+2
                call BoxX
                ret nc
                xor a
                ld (#4000+#D7),a
                scf
                ret

; ROM $0CD3F (IP $C93F, вход NATIVE; зовут части линкора этапа 3 $C7C3 и др. — через кадр): урон объекта BP от
; снарядов игрока по хитбоксу ES:DI — сканы $F4AA, $F525, $F548, $F560 с одной подготовкой (CollideSetup; записи
; сканов [bp+4…9] не задевают — X и Y читаются один раз, как у $F6DA). X ≥ #2B0 — сразу RET. $F4AA: пересечение — AH =
; [si], BL = [bp+1F], AL = [bp+2F] − BL (заём — RET), [bp+1F] += AH, [si+1] += AL; $F525: [bp+1F] + 1; $F548: [bp+1F]
; + 1, AL = [si+1], [bp+2F] < AL — RET, иначе [si+1] = 0; $F560: AH = [si+1], BL = [bp+1F], AL = [bp+2F] − BL (заём —
; RET), [bp+1F] += AH, AL −= [si+1] (заём — RET), [si+1] = 0. Перед каждым сканом BX = DI. Регистры V30 — как у ROM,
; флаги после RET не живут (flags.liveness). Условия (до записей, иначе перевод с входа): DS = #4000, BP кратен #20 и
; меньше #3F00, условия CollideSetup. VDAC2+ 2026-09-25 (партия 3): прежде — четыре ядра с подготовкой и
; диспетчеризацией у каждого и переведённый $F525.
N_C93F:         call NC93F
                jp nc,NRet
                ld a,$$K_0CD3F
                ld hl,K_0CD3F
                jp FARJP

; Тело $C93F (для N_C93F и нативных обработчиков частей): CF = 1 — нельзя (ничего не записано: перевод с входа $C93F);
; иначе CF = 0 — сделано всё до RET ROM. IY → [bp] (ставит само). Портит всё, кроме IY.
NC93F:          ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                jp nz,.no
                ld hl,(V_BP)
                ld a,l
                and #1F
                jp nz,.no
                ld a,h
                cp #3F
                jp nc,.no
                set 6,h
                push hl
                pop iy                          ; IY → [bp]
                ld l,(iy+4)
                ld h,(iy+5)
                ld de,-#2B0
                add hl,de
                jp c,.ok                       ; X ≥ #2B0 — RET
                ld hl,(V_DI)
                ld (V_BX),hl                    ; BX = DI
                call CollideSetup               ; хитбокс ES:DI (окно W3 — эта страница)
                jp c,.no
                ld bc,(KC_X)
                ld de,(KC_XR)
                call CollideAA.go               ; $F4AA (кэш столкновений — внутри)
                jr nc,.s2
                ld hl,(V_SI)
                set 6,h
                ld c,(hl)
                ld a,c
                ld (V_AX+1),a                   ; AH = [si]
                ld a,(iy+#1F)
                ld (V_BX),a                     ; BL = [bp+1F]
                ld b,a
                ld a,(iy+#2F)
                sub b                           ; AL = [bp+2F] − BL
                ld (V_AX),a
                jp c,.ok
                ld b,a
                ld a,(iy+#1F)
                add a,c
                ld (iy+#1F),a                   ; [bp+1F] += AH
                inc hl
                ld a,(hl)
                add a,b
                ld (hl),a                       ; [si+1] += AL
                ld bc,(KC_X)
                ld de,(KC_XR)                   ; BC портился выше
.s2:            ld hl,(V_DI)
                ld (V_BX),hl                    ; BX = DI
                call NCollideB6.go              ; $F525
                jr nc,.s3
                inc (iy+#1F)
.s3:            ld hl,(V_DI)
                ld (V_BX),hl
                call NCollide48.go              ; $F548
                jr nc,.s4
                inc (iy+#1F)
                ld hl,(V_SI)
                set 6,h
                inc hl
                ld a,(hl)
                ld (V_AX),a                     ; AL = [si+1]
                ld a,(iy+#2F)
                cp (hl)
                jp c,.ok                       ; [bp+2F] < AL — RET
                ld (hl),0                       ; [si+1] = 0
.s4:            ld hl,(V_DI)
                ld (V_BX),hl
                call NCollide60.go              ; $F560
                ret nc
                ld hl,(V_SI)
                set 6,h
                inc hl
                ld c,(hl)
                ld a,c
                ld (V_AX+1),a                   ; AH = [si+1]
                ld a,(iy+#1F)
                ld (V_BX),a                     ; BL = [bp+1F]
                ld b,a
                ld a,(iy+#2F)
                sub b                           ; AL = [bp+2F] − BL
                ld (V_AX),a
                jp c,.ok
                ld b,a
                ld a,(iy+#1F)
                add a,c
                ld (iy+#1F),a                   ; [bp+1F] += AH
                ld a,b
                sub (hl)                        ; AL −= [si+1]
                ld (V_AX),a
                jp c,.ok
                ld (hl),0                       ; [si+1] = 0
                jr .ok
.ok:            or a                            ; CF = 0 — RET ROM
                ret
.no:            scf
                ret

; Общие подпрограммы частей линкора и турелей этапа 3 (обработчики $E157, $E2AA, $DBB5, $D90E): IX → [bp].
; Спрайт части со вспышкой: BX — описание (V_BX); [bp+3D] ≠ 0 — DEC и в нечётном кадре ([2EB6] & 1) — спрайт с
; ресурсом [bp+6] = [bp+3C] (AL — он же; PUSH/POP ROM), иначе — обычный спрайт $1BCC. Портит всё, кроме IX.
NPartSprite:    ld a,(ix+#3D)
                or a
                jr z,.plain
                dec a
                ld (ix+#3D),a
                ld a,(#4000+#2EB6)
                rra
                jr nc,.plain                    ; чётный кадр — обычный спрайт
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3C)
                ld (V_AX),a                     ; AL = [bp+3C]
                ld (ix+6),a
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                ret
.plain:         jp NSpriteAdd                   ; $1BCC

; Урон части: HL — DI (хитбокс ES:DI); $F6DA, попадание — [bp+3D] = 5, CL = #56, звук $0303. Портит всё, кроме IX.
NPartDamage:    ld (V_DI),hl
                push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                call NDamage                    ; ZF — урон не изменился
                jr z,.done
                ld (iy+#3D),5
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound
.done:          push iy
                pop ix
                ret

; Связь части: BX = [bp+3E] (V_BX); NZ — слово [bx+3E] ≠ 0 (связанная часть уходит). Портит AF, DE, HL.
NPartLink:      ld l,(ix+#3E)
                ld h,(ix+#3F)
                ld (V_BX),hl
                set 6,h
                ld de,#3E
                add hl,de
                ld a,(hl)
                inc hl
                or (hl)
                ret

; Прочность: AL = [bp+1F] (V_AX); CF = 0 — [bp+1F] ≥ [bp+2F] (разрушена). Портит AF.
NPartHp:        ld a,(ix+#1F)
                ld (V_AX),a
                cp (ix+#2F)
                ret

; Прокрутка части: X += [2ED4], Y += [2ED6] (AX = [2ED6]). Портит AF, DE, HL.
NPartScroll:    ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h
                ld hl,(#4000+#2ED6)
                ld (V_AX),hl
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h
                ret

; Условия частей до записей: условия NObjCheck и [bp+3E] < #3F00. CF = 1 — нельзя; иначе IX → [bp]. Портит AF, HL.
NPartCheck:     call NObjCheck
                ret c
                ld a,(ix+#3F)
                cp #3F
                ccf                             ; CF = 1 — [bp+3E] ≥ #3F00
                ret

; Условия нативных обработчиков объекта до записей: DS = #4000, ES = #1000, BP кратен #20 и < #3F00. CF = 1 —
; нельзя; иначе IX → [bp]. Портит AF, HL.
NObjCheck:      ld hl,(V_DS)
                ld a,h
                xor #40
                or l
                scf
                ret nz
                ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                scf
                ret nz
                ld hl,(V_BP)
                ld a,l
                and #1F
                scf
                ret nz
                ld a,h
                cp #3F
                ccf
                ret c
                set 6,h
                push hl
                pop ix                          ; CF = 0
                ret

; ROM $0DFB5 (IP $DBB5) — часть линкора этапа 3 (вход NATIVE; профиль этапа 3 — 4,5 % тактов со всеми вызовами):
; прокрутка; описание BX = (([2EB6] & #30) >> 2)·1,5 + [bp+30] (AX = (([2EB6] & #30) >> 3); спрайт со вспышкой;
; помощник $DC63: AX = [2EB6], при (& #F) ≠ 0 — RET, иначе выстрел — переводом с $DC6B (адрес возврата #DBFB — на стек
; V30); урон DI = #80C6; уходы: [[bp+3E]+3E] ≠ 0 или [bp+1F] ≥ [bp+2F] — $DC40, [bp+4] < #120 или [2FC4] ≠ 0 —
; $DC2D. Регистры — как у ROM; флаги у выходов не живут. Условия — NPartCheck (иначе перевод с входа).
N_DBB5:         call NPartCheck
                jr nc,.body
                ld a,$$K_0DFB5
                ld hl,K_0DFB5
                jp FARJP
.body:          call NPartScroll
                ld a,(#4000+#2EB6)
                and #30
                rrca
                rrca                            ; AX = ([2EB6] & #30) >> 2
                ld c,a
                rrca                            ; AX >> 1
                ld (V_AX),a
                xor a
                ld (V_AX+1),a
                ld a,(V_AX)
                add a,c                         ; BX = AX·1,5 (≤ #12)
                ld l,a
                ld h,0
                ld e,(ix+#30)
                ld d,(ix+#31)
                add hl,de
                ld (V_BX),hl                    ; + [bp+30]
                call NPartSprite
                ld hl,(#4000+#2EB6)
                ld (V_AX),hl                    ; $DC63: AX = [2EB6]
                ld a,l
                and #0F
                jr nz,.damage                   ; не кратно 16 — RET помощника
                ld hl,#DBFB
                push hl                         ; адрес возврата CALL $DC63
                NTAIL A_0E06B                   ; $DC6B — выстрел переводом
.damage:        ld hl,#80C6
                call NPartDamage
                call NPartLink
                jr nz,.destroy
                call NPartHp
                jr nc,.destroy
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,#120
                or a
                sbc hl,de
                jr c,.clean                     ; [bp+4] < #120
                ld a,(#4000+#2FC4)
                or a
                jp z,NRet
.clean:         NTAIL A_0E02D                   ; $DC2D
.destroy:       NTAIL A_0E040                   ; $DC40

; ROM $0DD0E (IP $D90E) — часть линкора этапа 3 (вход NATIVE; 3,3 % тактов этапа со всеми вызовами): прокрутка;
; описание BX = ES:[[bp+20] + #7E9A]; спрайт со вспышкой; урон DI = #7ECA; [bp+1F] ≥ [bp+2F] или [[bp+3E]+3E] ≠ 0 —
; $D9D1; AX = [[bp+3E]+32] ≥ ES:[[bp+30]] (BX = [bp+30]) — смена фазы переводом с $D977; иначе [2FC4] ≠ 0 или
; [bp+4] < #120 — $DA36, иначе RET. Регистры — как у ROM; флаги у выходов не живут.
N_D90E:         call NPartCheck
                jr nc,.body
.translated:    ld a,$$K_0DD0E
                ld hl,K_0DD0E
                jp FARJP
.body:          call NPartScroll
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld de,#7E9A
                add hl,de
                ld (V_BX),hl                    ; BX = [bp+20] + #7E9A
                call NWord1000                  ; ES:[bx]
                jr c,.descFail
                ld (V_BX),de
                call NPartSprite
                ld hl,#7ECA
                call NPartDamage
                call NPartHp
                jr nc,.destroy
                call NPartLink
                jr nz,.destroy
                ld hl,(V_BX)
                set 6,h
                ld de,#32
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (V_AX),de                    ; AX = [bx+32]
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_BX),hl                    ; BX = [bp+30]
                push de
                call NWord1000                  ; DE = ES:[bx]
                pop hl                          ; HL = AX
                jr c,.phaseFail
                or a
                sbc hl,de
                jr nc,.phase                    ; AX ≥ ES:[bx] — смена фазы
                ld a,(#4000+#2FC4)
                or a
                jr nz,.clean
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,#120
                sbc hl,de                       ; CF = 0 после OR
                jp nc,NRet
.clean:         NTAIL A_0DE36                   ; $DA36
.destroy:       NTAIL A_0DDD1                   ; $D9D1
.phase:         NTAIL A_0DD77                   ; $D977
.descFail:      NTAIL A_0DD21                   ; не бывает: таблица — не на границе страницы
.phaseFail:     NTAIL A_0DD72                   ; то же

; Спрайт звена червя этапа 5 ($7D22): BX — описание (V_BX); [bp+3F] ≠ 0 — DEC, при (& 3) = 0 — спрайт с ресурсом
; [bp+6] = [bp+3E] (AL — он же; PUSH/POP ROM), иначе — обычный спрайт $1BCC. IX → [bp]. Портит всё, кроме IX.
NWormSprite:    ld a,(ix+#3F)
                or a
                jr z,.plain
                dec a
                ld (ix+#3F),a
                and 3
                jr nz,.plain
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3E)
                ld (V_AX),a                     ; AL = [bp+3E]
                ld (ix+6),a
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                ret
.plain:         jp NSpriteAdd                   ; $1BCC

; Урон звена червя: HL — DI; $F6DA, попадание — [bp+3F] = #0C, CL = #57, звук $0303. Затем CF = 1 — [bp+1F] < 6
; (звено живо). IX → [bp]. Портит всё, кроме IX.
NWormDamage:    ld (V_DI),hl
                push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                call NDamage                    ; ZF — урон не изменился
                jr z,.done
                ld (iy+#3F),#0C
                ld a,#57
                ld (V_CX),a                     ; CL = #57
                call NSound                     ; $0303
.done:          push iy
                pop ix
                ld a,(ix+#1F)
                cp 6
                ret

; ROM $07FFC (IP $7BFC) — звено червя этапа 5, «следование» (вход NATIVE; профиль этапа 5 — 2,5 % тактов со всеми
; вызовами): [2FC4] ≠ 0 — $7C3D; скрипт $F5C1 (CF — $7C3D); спрайт $7D22 по описанию [bp+16]·6 + #3676 (AX =
; [bp+16]·2); урон DI = #37CE; [bp+1F] ≥ 6 — $7C77, иначе RET. Регистры — как у ROM; флаги у выходов не живут.
; Условия (иначе перевод с входа): NObjCheck и [bp+17] ≠ 0 (условие ядра скрипта).
N_7BFC:         call NObjCheck
                jr c,.translated
                ld a,(#4000+#2FC4)
                or a
                jr nz,.leave                    ; $7C3D — записей до него нет
                ld a,(ix+#17)
                or a
                jr z,.translated
                call ScriptCore                 ; $F5C1
                jr c,.leave
                ld l,(ix+#16)
                ld h,0
                add hl,hl
                ld (V_AX),hl                    ; AX = [bp+16]·2
                ld e,l
                ld d,h
                add hl,hl
                add hl,de
                ld de,#3676
                add hl,de
                ld (V_BX),hl                    ; BX = [bp+16]·6 + #3676
                call NWormSprite
                ld hl,#37CE
                call NWormDamage
                jp c,NRet
                NTAIL A_08077                   ; $7C77
.leave:         NTAIL A_0803D                   ; $7C3D
.translated:    ld a,$$K_07FFC
                ld hl,K_07FFC
                jp FARJP

; ROM $080D3 (IP $7CD3) — звено червя этапа 5, «уход» (вход NATIVE; 2,0 % тактов этапа): [2FC4] ≠ 0 — $7C3D; X += AX
; = [bp+38], Y += AX = [bp+3A] (Q8, $0672/$0689); [bp+16] + 1; спрайт $7D22 по описанию BX = ([bp+16] & #1E)·3 +
; [bp+30] (AX = ([bp+16] & #1E)·2); вне поля ($1D6B) — $7C3D; урон DI = #37CE; [bp+1F] ≥ 6 — $7C77, иначе RET.
; Условия (иначе перевод с входа): NObjCheck.
N_7CD3:         call NObjCheck
                jr c,.translated
                ld a,(#4000+#2FC4)
                or a
                jr nz,.leave
                ld l,(ix+#38)
                ld h,(ix+#39)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld l,(ix+#3A)
                ld h,(ix+#3B)
                ld (V_AX),hl
                call NAddY                      ; $0689
                ld l,(ix+#16)
                ld h,(ix+#17)
                inc hl
                ld (ix+#16),l
                ld (ix+#17),h                   ; INC WORD [bp+16]
                ld a,l
                and #1E
                ld l,a
                ld h,0                          ; BX = [bp+16] & #1E
                ld e,l
                ld d,h
                add hl,hl
                ld (V_AX),hl                    ; AX = BX·2
                add hl,de                       ; BX·3
                ld e,(ix+#30)
                ld d,(ix+#31)
                add hl,de
                ld (V_BX),hl                    ; + [bp+30]
                call NWormSprite
                call NOnField                   ; $1D6B: CF — вне поля (AX — как у ROM)
                jr c,.leave
                ld hl,#37CE
                call NWormDamage
                jp c,NRet
                NTAIL A_08077                   ; $7C77
.leave:         NTAIL A_0803D                   ; $7C3D
.translated:    ld a,$$K_080D3
                ld hl,K_080D3
                jp FARJP

; Спрайт со вспышкой по счётчику [bp+3D] ($737D этапа 6 и подобные): BX — описание (V_BX); [bp+3D] ≠ 0 — DEC, при
; (& 3) = 0 — спрайт с ресурсом [bp+6] = [bp+3C] (AL — он же; PUSH/POP ROM), иначе — обычный спрайт $1BCC. IX → [bp].
; Портит всё, кроме IX.
NFlash3D:       ld a,(ix+#3D)
                or a
                jr z,.plain
                dec a
                ld (ix+#3D),a
                and 3
                jr nz,.plain
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3C)
                ld (V_AX),a                     ; AL = [bp+3C]
                ld (ix+6),a
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                ret
.plain:         jp NSpriteAdd                   ; $1BCC

; ROM $076D2 (IP $72D2) — враг этапа 6 (23 штуки от $7294; вход NATIVE; профиль этапа 6 — 8,2 % тактов со всеми
; вызовами). X += [2ED0] (AX); X += AX = ES:[[bp+10]·4 + #329E], Y += AX = ES:[… + #32A0] (Q8, $0672, $0689); раз в 8
; кадров AX = [bp+20] + 6, #1E → 0, [bp+20] = AX; спрайт $737D по описанию BX = ES:[[bp+10]·2 + #32BE] + [bp+20]
; (NFlash3D); выстрел $73DB: [bp+26] + 1 (AX), равен [bp+2A] или не меньше [bp+2C] — переводом с $73F1 / $73EC (адрес
; возврата #731E — на стек V30); рельеф $73A0: BX = [bp+10]·4, AX = ES:[bx+#32AE], CX = ES:[bx+#32B0], точка объекта
; сдвигается на (AX, CX) на время проб (PUSH/POP ROM): вне поля ($1D6B) — [bp+10] ^= 1, тайл слоя A ($1E6C) ≥ #DFC —
; [bp+10] ^= 1 (тайл #3FFF-места — переводом с $73C8, стек V30 как у ROM); урон DI = #333E (попадание — [bp+3D] =
; #0C, CL = #56, звук); [bp+1F] ≥ [bp+2F] — $735A; вне поля или [2FC4] ≠ 0 — $7347; иначе RET. Регистры — как у ROM;
; флаги у выходов не живут (flags.liveness). Условия (иначе перевод с входа): NObjCheck. Таблицы ES:#329E…#32C1 — не
; на границе страницы V30: NWord1000 здесь не отказывает.
N_72D2:         call NObjCheck
                jr nc,.body
                ld a,$$K_076D2
                ld hl,K_076D2
                jp FARJP
.body:          ld hl,(#4000+#2ED0)
                ld (V_AX),hl
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld l,(ix+#10)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = [bp+10]·4
                push hl
                ld de,#329E
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddX                      ; $0672
                pop hl
                ld de,#32A0
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddY                      ; $0689
                ld a,(#4000+#2EB6)
                and 7
                jr nz,.frame
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld de,6
                add hl,de
                ld a,l
                cp #1E
                jr nz,.phase
                ld a,h
                or a
                jr nz,.phase
                ld l,a                          ; #1E → 0 (H = 0)
.phase:         ld (V_AX),hl
                ld (ix+#20),l
                ld (ix+#21),h
.frame:         ld l,(ix+#10)
                ld h,0
                add hl,hl
                ld de,#32BE
                add hl,de
                call NWord1000                  ; ES:[[bp+10]·2 + #32BE]
                ld l,(ix+#20)
                ld h,(ix+#21)
                add hl,de
                ld (V_BX),hl                    ; + [bp+20] — описание
                call NFlash3D                   ; $737D
                ld l,(ix+#26)
                ld h,(ix+#27)
                inc hl
                ld (ix+#26),l
                ld (ix+#27),h
                ld (V_AX),hl                    ; $73DB: AX = [bp+26] + 1
                ld a,l
                cp (ix+#2A)
                jr nz,.notEqual
                ld a,h
                cp (ix+#2B)
                jp z,.fireA                     ; = [bp+2A] — выстрел
.notEqual:      ld e,(ix+#2C)
                ld d,(ix+#2D)
                or a
                sbc hl,de
                jp nc,.fireB                    ; ≥ [bp+2C] — сброс и выстрел
                ; $73A0: пробы рельефа от сдвинутой точки (CALL ROM: возврат #7321, затем PUSH [bp+4], PUSH [bp+8])
.probe:         ld hl,#7321
                push hl
                ld l,(ix+#10)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = [bp+10]·4
                push hl
                ld de,#32AE
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#32AE]
                pop hl
                push de
                ld de,#32B0
                add hl,de
                call NWord1000
                ld (V_CX),de                    ; CX = ES:[bx+#32B0]
                pop hl                          ; HL = AX
                ld c,(ix+4)
                ld b,(ix+5)
                push bc                         ; PUSH [bp+4]
                push hl
                ld l,(ix+8)
                ld h,(ix+9)
                ex (sp),hl                      ; PUSH [bp+8]; HL = AX
                add hl,bc
                ld (ix+4),l
                ld (ix+5),h                     ; [bp+4] += AX
                ld l,(ix+8)
                ld h,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; [bp+8] += CX
                call NOnField                   ; $1D6B: V_AX, CF — вне поля
                jr nc,.inField
                ld a,(ix+#10)
                xor 1
                ld (ix+#10),a
.inField:       ld hl,(V_BP)
                call TerrainA                   ; $1E6C: V_CX, V_BX, V_AX; IX → [bp]; CF — место #3FFF
                jp c,.terrainTranslated
                pop bc
                ld (ix+8),c
                ld (ix+9),b                     ; POP [bp+8]
                pop bc
                ld (ix+4),c
                ld (ix+5),b                     ; POP [bp+4]
                pop hl                          ; адрес возврата CALL $73A0 (#7321)
                ld hl,(V_AX)
                ld de,#DFC
                or a
                sbc hl,de
                jr c,.damage                    ; тайл < #DFC
                ld a,(ix+#10)
                xor 1
                ld (ix+#10),a
.damage:        ld hl,#333E
                ld (V_DI),hl
                push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                call NDamage                    ; $F6DA
                jr z,.post
                ld (iy+#3D),#0C
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound                     ; $0303
.post:          push iy
                pop ix
                ld a,(ix+#1F)
                ld (V_AX),a                     ; AL = [bp+1F]
                cp (ix+#2F)
                jr nc,.destroy
                call NOnField                   ; $1D6B
                jr c,.clean
                ld a,(#4000+#2FC4)
                or a
                jp z,NRet
.clean:         NTAIL A_07747                   ; $7347
.destroy:       NTAIL A_0775A                   ; $735A
.fireB:         ld (ix+#26),0
                ld (ix+#27),0                   ; $73EC: [bp+26] = 0
.fireA:         ld a,(ix+#28)
                or (ix+#29)
                jp z,.probe                     ; $73F1: [bp+28] = 0 — выстрела нет (RET $7434), дальше $731E
                ld hl,#731E
                push hl                         ; адрес возврата CALL $73DB
                NTAIL A_077F8                   ; $73F8: выстрел — переводом (его RET — в N_731E)
.terrainTranslated:
                NTAIL A_077C8                   ; $73C8 — стек V30: #7321, [bp+4], [bp+8]

; ROM $0771E (IP $731E) — продолжение $72D2 после выстрела $73DB (RET переведённого выстрела приходит сюда
; диспетчеризацией): пробы $73A0, урон, концы — как у N_72D2 с метки .probe; регистры V30 после выстрела та часть не
; читает. Условия (иначе перевод с места): NObjCheck.
N_731E:         call NObjCheck
                jp nc,N_72D2.probe
                ld a,$$K_0771E
                ld hl,K_0771E
                jp FARJP

; ROM $0633C (IP $5F3C) — враг этапа 6 (45 штук от $5EED; вход NATIVE; профиль этапа 6 — 11,3 % тактов со всеми
; вызовами). Раз в 64 кадра — запись менеджера палитр ($54C4: BX = [bp+6]·12 + #2D34, [bx] = CX = #8028 / #8050 по
; биту 6 [2EB6], [bx+4] = 1, [bx+8] = DX = 0, [bx+#0A] = #1F; AX = [bp+6]·4); [2FC4] ≠ 0 — $6035; скорость: BX =
; [bp+20]·4 + [bp+22], X += AX = ES:[bx+#2A80], Y += AX = ES:[bx+#2A82] ($0672, $0689), X += AX = [2ED0]; спрайт-пара
; $1C1B по описанию BX = ([2EB6] & #18)·1,5 + #2AC0 / #2AF0 ([bp+2E]); вспышка: AL = ([2EB6] & #18) >> 1, [bp+11] & AL ≠ 0
; — DEC [bp+11], при бите 2 = 0 — ресурс [bp+6] = [bp+10] (PUSH/POP ROM); урон $6081 (X < #2B0: первая проба DI =
; #2B20/#2B28 со словом [bp+1E] под PUSH/POP ROM — её урон отменяется, вторая DI = #2B30/#2B38: попадание — CL = #56,
; звук, [bp+11] = #1F); [bp+1F] ≥ #0A — $6048; вне поля ($1D6B) — $6035; луч: три пробы тайла слоя A ($1E6C; X ≥ #2C0 —
; AX = #FA0) от точки + ES:[[bp+20]·8 + #2A40/#2A60] с шагом ES:[+4], [+6] (PUSH/POP ROM точки и CX, BX, DX); тайл <
; #DFC — поворот $606B: [bp+20] ± 1 & 3 по биту 0 [bp+1E]. Регистры — как у ROM; флаги у выходов не живут. Условия
; (иначе перевод с входа): NObjCheck. Таблицы ES:#2A40…#2AFF — не на границе страницы V30.
N_5F3C:         call NObjCheck
                jr nc,.body
                ld a,$$K_0633C
                ld hl,K_0633C
                jp FARJP
.body:          ld a,(#4000+#2EB6)
                ld c,a
                and #3F
                jr nz,.noPalette
                ld hl,0
                ld (V_DX),hl                    ; DX = 0
                ld a,#28
                bit 6,c
                jr z,.cl
                ld a,#50
.cl:            ld l,a
                ld h,#80
                ld (V_CX),hl                    ; CX = #80xx (CH = #80 — у ROM MOV CH,#80 в $54C4)
                ld l,(ix+6)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_AX),hl                    ; AX = BX·4
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; BX·12
                ld de,#2D34
                add hl,de
                ld (V_BX),hl
                set 6,h
                ld de,(V_CX)
                ld (hl),e
                inc hl
                ld (hl),d                       ; [bx] = CX
                inc hl
                inc hl
                inc hl
                ld (hl),1
                inc hl
                ld (hl),0                       ; [bx+4] = 1
                inc hl
                inc hl
                inc hl
                ld (hl),0
                inc hl
                ld (hl),0                       ; [bx+8] = DX = 0
                inc hl
                ld (hl),#1F
                inc hl
                ld (hl),0                       ; [bx+#0A] = #1F
.noPalette:     ld a,(#4000+#2FC4)
                or a
                jp nz,.clean                    ; $6035
                ld l,(ix+#20)
                ld h,0
                add hl,hl
                add hl,hl
                ld e,(ix+#22)
                ld d,(ix+#23)
                add hl,de
                ld (V_BX),hl                    ; BX = [bp+20]·4 + [bp+22]
                push hl
                ld de,#2A80
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddX                      ; $0672
                pop hl
                ld de,#2A82
                add hl,de
                call NWord1000
                ld (V_AX),de
                ex de,hl
                call NAddY                      ; $0689
                ld hl,(#4000+#2ED0)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,#2AC0
                ld a,(ix+#2E)
                or a
                jr z,.base
                ld hl,#2AF0
.base:          ld a,(#4000+#2EB6)
                and #18
                ld e,a
                srl a
                ld (V_AX),a
                ld c,a                          ; AL = ([2EB6] & #18) >> 1
                xor a
                ld (V_AX+1),a
                add a,e
                add a,c
                ld e,a
                ld d,0
                add hl,de
                ld (V_BX),hl                    ; BX — описание пары
                ld a,(ix+#11)
                and c
                jr z,.plain
                dec (ix+#11)
                bit 2,(ix+#11)
                jr nz,.plain
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#10)
                ld (V_AX),a                     ; AL = [bp+10]
                ld (ix+6),a
                call NSpritePair                ; $1C1B
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                jr .damage
.plain:         call NSpritePair                ; $1C1B
.damage:        ld l,(ix+4)                     ; $6081: X ≥ #2B0 — без проб
                ld h,(ix+5)
                ld de,-#2B0
                add hl,de
                jr c,.afterDamage
                push ix
                pop iy                          ; IY → [bp]
                ld l,(iy+#1E)
                ld h,(iy+#1F)
                push hl                         ; PUSH WORD [bp+1E]
                ld hl,#2B20
                ld a,(iy+#2E)
                or a
                jr z,.di1
                ld hl,#2B28
.di1:           ld (V_DI),hl
                call NDamage                    ; $F6DA
                pop hl
                ld (iy+#1E),l
                ld (iy+#1F),h                   ; POP WORD [bp+1E] — урон первой пробы отменён
                ld hl,#2B30
                ld a,(iy+#2E)
                or a
                jr z,.di2
                ld hl,#2B38
.di2:           ld (V_DI),hl
                call NDamage                    ; $F6DA
                jr z,.damaged
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound                     ; $0303
                ld (iy+#11),#1F
.damaged:       push iy
                pop ix
.afterDamage:   ld a,(ix+#1F)
                cp #0A
                jp nc,.destroy                  ; $6048
                call NOnField                   ; $1D6B
                jp c,.clean
                ; луч: BX = [bp+20]·8 + #2A40 / #2A60; AX, CX — сдвиг точки, DX, BX — шаг
                ld l,(ix+#20)
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld de,#2A40
                ld a,(ix+#2E)
                or a
                jr z,.ray
                ld de,#2A60
.ray:           add hl,de
                ld (V_BX),hl
                push hl
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx]
                pop hl
                push hl
                inc hl
                inc hl
                call NWord1000
                ld (V_CX),de                    ; CX = ES:[bx+2]
                pop hl
                push hl
                ld de,4
                add hl,de
                call NWord1000
                ld (V_DX),de                    ; DX = ES:[bx+4]
                pop hl
                ld de,6
                add hl,de
                call NWord1000
                ld (V_BX),de                    ; BX = ES:[bx+6]
                ld l,(ix+4)
                ld h,(ix+5)
                push hl                         ; PUSH [bp+4]
                ld l,(ix+8)
                ld h,(ix+9)
                push hl                         ; PUSH [bp+8]
                ld hl,(V_AX)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; [bp+4] += AX
                ld hl,(V_CX)
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; [bp+8] += CX
                ld hl,3
                ld (V_CX),hl                    ; CX = 3
.probe:         ld hl,(V_DX)
                push hl                         ; PUSH DX
                ld hl,(V_BX)
                push hl                         ; PUSH BX
                ld hl,(V_CX)
                push hl                         ; PUSH CX
                ld hl,#FA0
                ld (V_AX),hl                    ; AX = #FA0
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#2C0
                add hl,de
                jr c,.far                       ; [bp+4] ≥ #2C0 — без пробы
                ld hl,(V_BP)
                call TerrainA                   ; $1E6C: V_CX, V_BX, V_AX; IX → [bp]
                jp c,.probeTranslated
.far:           pop hl
                ld (V_CX),hl                    ; POP CX
                pop hl
                ld (V_BX),hl                    ; POP BX
                pop de
                ld (V_DX),de                    ; POP DX
                ld c,(ix+4)
                ld b,(ix+5)
                ex de,hl                        ; HL = DX, DE = BX
                add hl,bc
                ld (ix+4),l
                ld (ix+5),h                     ; [bp+4] += DX
                ld l,(ix+8)
                ld h,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; [bp+8] += BX
                ld hl,(V_AX)
                ld de,#DFC
                or a
                sbc hl,de
                jr c,.hit                       ; тайл < #DFC — поворот
                ld hl,(V_CX)
                dec hl
                ld (V_CX),hl                    ; LOOP
                ld a,h
                or l
                jr nz,.probe
                pop hl
                ld (ix+8),l
                ld (ix+9),h                     ; POP [bp+8]
                pop hl
                ld (ix+4),l
                ld (ix+5),h                     ; POP [bp+4]
                jp NRet
.hit:           pop hl
                ld (ix+8),l
                ld (ix+9),h
                pop hl
                ld (ix+4),l
                ld (ix+5),h
                ld a,(ix+#20)                   ; $606B: поворот по биту 0 [bp+1E]
                bit 0,(ix+#1E)
                jr z,.left
                inc a
                jr .turn
.left:          dec a
.turn:          and 3
                ld (ix+#20),a
                jp NRet
.clean:         NTAIL A_06435                   ; $6035
.destroy:       NTAIL A_06448                   ; $6048
.probeTranslated:
                NTAIL A_06419                   ; $6019 — стек V30: [bp+4], [bp+8], DX, BX, CX

; ROM $0CBC3 (IP $C7C3) — часть линкора этапа 3 (вход NATIVE; профиль этапа 3 — 5,8 % тактов со всеми вызовами, из
; них перевод тела ≈ 1,6 %): X += [2ED4], Y += AX = [2ED6]; AL = ([2EB6] & 1) ^ [bp+3C] (AH — от [2ED6]): 0 — урон
; $C93F с DI = [bp+12] (NC93F; отказ — переводом $C93F с адресом возврата #C7DF на стеке V30); родитель BX = [bp+3E]:
; слово [bx+3E] ≠ 0 или AL = [bp+1F] ≥ [bp+2F] — $C83B ([bp+14] = #10, обработчик $C846); AL ≠ [bp+3D] — взрыв
; (переводом с $C7F6); [2FC4] ≠ 0 или X < #110 — $C837 (переводом: CALL $03EC); иначе RET. Регистры — как у ROM; флаги
; у выходов не живут. Условия (иначе перевод с входа): NObjCheck и [bp+3E] < #3F00 (слово [bx+3E] — окном W1).
N_C7C3:         call NObjCheck
                jp c,.translated
                ld a,(ix+#3F)
                cp #3F
                jp nc,.translated
                ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,(#4000+#2ED6)
                ld (V_AX),hl
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD [bp+8],AX
                ld a,(#4000+#2EB6)
                and 1
                xor (ix+#3C)
                ld (V_AX),a                     ; AL (AH — от [2ED6])
                jr nz,.parent
                ld l,(ix+#12)
                ld h,(ix+#13)
                ld (V_DI),hl                    ; MOV DI,[bp+12]
                call NC93F                      ; $C93F (IY → [bp])
                jr c,.damageTranslated
                ld hl,(V_BP)
                set 6,h
                push hl
                pop ix                          ; IX → [bp]
.parent:        ld l,(ix+#3E)
                ld h,(ix+#3F)
                ld (V_BX),hl                    ; MOV BX,[bp+3E]
                set 6,h
                ld de,#3E
                add hl,de
                ld a,(hl)
                inc hl
                or (hl)
                jr nz,.detach                   ; [bx+3E] ≠ 0 — $C83B
                ld a,(ix+#1F)
                ld (V_AX),a                     ; AL = [bp+1F]
                cp (ix+#2F)
                jr nc,.detach                   ; ≥ [bp+2F] — $C83B
                cp (ix+#3D)
                jr nz,.blast                    ; урон изменился — взрыв
                ld a,(#4000+#2FC4)
                or a
                jr nz,.free
                ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#110
                add hl,de
                jp c,NRet                       ; X ≥ #110 — RET
.free:          NTAIL A_0CC37                   ; $C837: CALL $03EC
.blast:         NTAIL A_0CBF6                   ; $C7F6: [bp+3D] = AL, взрыв $E7BE
.detach:        ld (ix+#14),#10
                ld (ix+#15),0                   ; MOV WORD [bp+14],#10
                ld (ix+0),#46
                ld (ix+1),#C8                   ; обработчик $C846
                jp NRet
.damageTranslated:
                ld hl,#C7DF
                push hl                         ; CALL $C93F: адрес возврата
                ld a,$$K_0CD3F
                ld hl,K_0CD3F
                jp FARJP
.translated:    ld a,$$K_0CBC3
                ld hl,K_0CBC3
                jp FARJP

; ROM $08DB0 (IP $89B0) и $08EEE (IP $8AEE) — два состояния врага этапов 4 и 7 (профиль этапа 4 — 3,7 и 1,2 % тактов со
; всеми вызовами): счётчик периода $F63A (порождение — переводом с адресом возврата #89B3 / #8AF1 на стеке V30); [bp+20]
; + 1, при [bp+20] & [bp+30] = 0 и [bp+20] < #400 — направление [bp+2E] = BL: 1 или 2 по Y к [#28] ($89B0: Y < [#28]
; — 1; $8AEE — наоборот) | 4 или 8 по X к [#24]; [bp+1E] = 2; по битам [bp+2E] — пробы рельефа слоя A ($1E6C) в точке
; Y + #18, Y − #18, X − #18, X + #18 (PUSH/POP ROM): тайл ≥ #DFC — [bp+1E] − 1 и шаг #C0 / #FF40 ($0689, $0672); у
; $8AEE по Y без шага — [bp+22] = 1; X += [2ED0]; спрайт $1BCC по описанию ES:[([2EB6] & #30) >> 3 + SI], SI = #3C2A
; (бит 3) / #3C22; столкновения $F694 с хитбоксом #3C56 (попадание — $8AD1), вне поля или [2FC4] ≠ 0 — $8AC4 (оба —
; переводом); [bp+1E] = 2 — смена состояния ($89B0: обработчик $8AEE и [bp+22] = #3FF; $8AEE: $89B0), иначе у $8AEE
; DEC [bp+22] (ноль — смена). Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа):
; NObjCheck; отказы проб рельефа, слова описания и описания спрайта, подготовки столкновений — переводом с места.
N_8AEE:         ld a,1
                jr N_89B0.mode
N_89B0:         xor a
.mode:          ld (N_HOP),a                    ; 0 — $89B0, 1 — $8AEE
                call NObjCheck
                jp c,.translated
                call CounterCore                ; $F63A (IX → [bp])
                or a
                jr z,.counted
                ld hl,#89B3
                ld a,(N_HOP)
                or a
                jr z,.spawn
                ld hl,#8AF1
.spawn:         push hl                         ; CALL $F63A: адрес возврата
                NTAIL A_0FA57                   ; порождение — переводом
.counted:       ld l,(ix+#20)
                ld h,(ix+#21)
                inc hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; INC WORD [bp+20]
                ld e,(ix+#30)
                ld d,(ix+#31)
                ld (V_AX),de                    ; MOV AX,[bp+30]
                ld a,l
                and e
                jr nz,.go
                ld a,h
                and d
                jr nz,.go                       ; TEST [bp+20],AX ≠ 0
                ld a,h
                cp #04
                jr nc,.go                       ; [bp+20] ≥ #400
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_AX),hl                    ; MOV AX,[bp+8]
                ld de,(#4000+#28)
                ld c,1                          ; MOV BL,1
                or a
                sbc hl,de                       ; CF: Y < [#28]
                ld a,(N_HOP)
                jr c,.yLess
                or a
                jr nz,.yDone                    ; $8AEE: Y ≥ [#28] — BL = 1
                ld c,2
                jr .yDone
.yLess:         or a
                jr z,.yDone                     ; $89B0: Y < [#28] — BL = 1
                ld c,2
.yDone:         ld l,(ix+4)
                ld h,(ix+5)
                ld (V_AX),hl                    ; MOV AX,[bp+4]
                ld de,(#4000+#24)
                or a
                sbc hl,de
                ld a,c
                jr c,.xLess
                or 4
                jr .xDone
.xLess:         or 8
.xDone:         ld (ix+#2E),a                   ; MOV [bp+2E],BL
                ld (V_BX),a                     ; BL (BH прежний)
.go:            ld (ix+#1E),2
                bit 0,(ix+#2E)
                jr z,.skip1
                ld hl,0
                ld de,#18
                call NProbeA                    ; Y + #18
                jp c,.probeFail1
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.skip1                    ; тайл < #DFC
                dec (ix+#1E)
                ld hl,#C0
                ld (V_AX),hl
                call NAddY                      ; $0689
                jr .probe2
.skip1:         call .stay                      ; у $8AEE — [bp+22] = 1
.probe2:        bit 1,(ix+#2E)
                jr z,.skip2
                ld hl,0
                ld de,-#18
                call NProbeA                    ; Y − #18
                jp c,.probeFail2
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.skip2
                dec (ix+#1E)
                ld hl,#FF40
                ld (V_AX),hl
                call NAddY                      ; $0689
                jr .probe3
.skip2:         call .stay
.probe3:        bit 2,(ix+#2E)
                jr z,.probe4
                ld hl,-#18
                ld de,0
                call NProbeA                    ; X − #18
                jp c,.probeFail3
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.probe4
                dec (ix+#1E)
                ld hl,#FF40
                ld (V_AX),hl
                call NAddX                      ; $0672
.probe4:        bit 3,(ix+#2E)
                jr z,.sprite
                ld hl,#18
                ld de,0
                call NProbeA                    ; X + #18
                jp c,.probeFail4
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.sprite
                dec (ix+#1E)
                ld hl,#C0
                ld (V_AX),hl
                call NAddX                      ; $0672
.sprite:        ld hl,#3C2A
                bit 3,(ix+#2E)
                jr nz,.table
                ld hl,#3C22
.table:         ld (V_SI),hl                    ; SI — таблица кадров
                call NScrollX                   ; ADD [bp+4],AX (AX = [2ED0])
                ld a,(#4000+#2EB6)
                and #30
                rrca
                rrca
                rrca
                ld e,a
                ld d,0
                ld (V_BX),de                    ; BX = ([2EB6] & #30) >> 3
                ld hl,(V_SI)
                add hl,de
                call NWord1000                  ; BX = ES:[bx+si]
                jp c,.frameFail
                ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jp c,.spriteFail
                ld hl,#3C56
                ld (V_DI),hl                    ; MOV DI,#3C56
                call CollideSetup               ; $F694: хитбокс ES:DI
                jp c,.collideFail
                push ix
                call CollideA94
                pop ix
                jp c,.hit                       ; попадание — $8AD1
                call NOnField                   ; $1D6B
                jp c,.remove
                ld a,(#4000+#2FC4)
                or a
                jp nz,.remove
                ld a,(N_HOP)
                or a
                jr nz,.second
                ld a,(ix+#1E)
                cp 2
                jp nz,NRet
                ld (ix+0),#EE
                ld (ix+1),#8A                   ; обработчик $8AEE
                ld (ix+#22),#FF
                ld (ix+#23),#03                 ; [bp+22] = #3FF
                jp NRet
.second:        ld a,(ix+#1E)
                cp 2
                jr z,.flip
                ld l,(ix+#22)
                ld h,(ix+#23)
                dec hl
                ld (ix+#22),l
                ld (ix+#23),h                   ; DEC WORD [bp+22]
                ld a,h
                or l
                jp nz,NRet
.flip:          ld (ix+0),#B0
                ld (ix+1),#89                   ; обработчик $89B0
                jp NRet
; $8AEE без шага по Y: [bp+22] = 1 (у $89B0 — ничего). Портит AF.
.stay:          ld a,(N_HOP)
                or a
                ret z
                ld (ix+#22),1
                ld (ix+#23),0
                ret
.hit:           NTAIL A_08ED1                   ; $8AD1
.remove:        NTAIL A_08EC4                   ; $8AC4
.probeFail1:    ld a,(N_HOP)
                or a
                jr nz,.probeFail1b
                NTAIL A_08DF1
.probeFail1b:   NTAIL A_08F2F
.probeFail2:    ld a,(N_HOP)
                or a
                jr nz,.probeFail2b
                NTAIL A_08E12
.probeFail2b:   NTAIL A_08F58
.probeFail3:    ld a,(N_HOP)
                or a
                jr nz,.probeFail3b
                NTAIL A_08E33
.probeFail3b:   NTAIL A_08F81
.probeFail4:    ld a,(N_HOP)
                or a
                jr nz,.probeFail4b
                NTAIL A_08E54
.probeFail4b:   NTAIL A_08FA2
.frameFail:     ld a,(N_HOP)
                or a
                jr nz,.frameFailB
                NTAIL A_08E8C
.frameFailB:    NTAIL A_08FDA
.spriteFail:    ld a,(N_HOP)
                or a
                jr nz,.spriteFailB
                NTAIL A_08E8F
.spriteFailB:   NTAIL A_08FDD
.collideFail:   ld a,(N_HOP)
                or a
                jr nz,.collideFailB
                NTAIL A_08E95
.collideFailB:  NTAIL A_08FE3
.translated:    ld a,(N_HOP)
                or a
                jr nz,.translatedB
                ld a,$$K_08DB0
                ld hl,K_08DB0
                jp FARJP
.translatedB:   ld a,$$K_08EEE
                ld hl,K_08EEE
                jp FARJP

; --- враги этапа 7: семейство $7502…$7719 (профиль этапа 7 — ≈12 % тактов логики со всеми вызовами) ----------------
; Общее: X += [2ED0]; спрайт со вспышкой $779E (≡ $737D — NFlash3D); урон $F6DA с хитбоксом #3426 (попадание —
; [bp+3D] = #0C, CL = #56, звук); AL = [bp+1F] ≥ [bp+2F] — уничтожение $777B (переводом); вне поля или [2FC4] ≠ 0 —
; удаление $7768 (переводом). Смены состояния: $75F5 — к игроку ([bp+10] = #200 / #FE80, обработчик $7502) или стоять
; ($759F), [bp+20] = 8; $762D — [bp+20] = #1F, обработчик $7654, описания [bp+14], [bp+16] по стороне игрока. Регистры
; — как у ROM; флаги у выходов не живут. Условия (иначе перевод с входа): NObjCheck. Описания и хитбокс — ES:#3340…
; #3460 (ROM, не на границе страницы V30): NSpriteAdd и NDamage здесь не отказывают.

; Урон врага семейства: HL — DI; $F6DA, попадание — [bp+3D] = #0C, CL = #56, звук $0303; затем AL = [bp+1F] (V_AX), CF
; = 1 — AL < [bp+2F] (враг жив). IX → [bp]. Портит всё, кроме IX.
NDamage3D:      ld (V_DI),hl
                push ix
                pop iy                          ; IY → [bp] (NDamage портит IX)
                call NDamage                    ; ZF — урон не изменился
                jr z,.done
                ld (iy+#3D),#0C
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound                     ; $0303
.done:          push iy
                pop ix
                ld a,(ix+#1F)
                ld (V_AX),a                     ; MOV AL,[bp+1F]
                cp (ix+#2F)                     ; CMP AL,[bp+2F]: CF — жив
                ret

; Описание по фазе: BX = t + t/2 + [bp+14], t = ([bp+20] & #18) >> 1, AX = t/2 ($765A, $771F). Портит AF, DE, HL.
NPhase3D:       ld a,(ix+#20)
                and #18
                rrca                            ; t
                ld e,a
                rrca                            ; t/2
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = t/2
                add a,e
                ld l,a                          ; H = 0
                ld e,(ix+#14)
                ld d,(ix+#15)
                add hl,de
                ld (V_BX),hl
                ret

; $75F5: AX = [#24] − X; без заёма — $760F; AX + #68 с переносом — $760F; AX + #14 с переносом — $7617 (стоять:
; обработчик $759F); иначе [bp+10] = #FE80; $760F — [bp+10] = #200; затем обработчик $7502; [bp+20] = 8; RET.
N75F5:          ld hl,(#4000+#24)
                ld e,(ix+4)
                ld d,(ix+5)
                or a
                sbc hl,de
                ld (V_AX),hl                    ; SUB AX,[bp+4]
                jr nc,.right                    ; JAE $760F
                ld de,#68
                add hl,de
                ld (V_AX),hl
                jr c,.right                     ; JB $760F
                ld de,#14
                add hl,de
                ld (V_AX),hl
                jr c,.stand                     ; JB $7617
                ld (ix+#10),#80
                ld (ix+#11),#FE                 ; [bp+10] = #FE80
                jr .walk
.right:         ld (ix+#10),0
                ld (ix+#11),2                   ; [bp+10] = #200
.walk:          ld (ix+0),#02
                ld (ix+1),#75                   ; обработчик $7502
                jr .timer
.stand:         ld (ix+0),#9F
                ld (ix+1),#75                   ; обработчик $759F
.timer:         ld (ix+#20),8
                ld (ix+#21),0                   ; [bp+20] = 8
                jp NRet

; $762D: [bp+20] = #1F, обработчик $7654, [bp+14]/[bp+16] = #33AE/#33DE, при [#24] ≥ X — #33C6/#3402 (AX = [#24]).
N762D:          ld (ix+#20),#1F
                ld (ix+#21),0
                ld (ix+0),#54
                ld (ix+1),#76                   ; обработчик $7654
                ld hl,(#4000+#24)
                ld (V_AX),hl                    ; MOV AX,[#24]
                ld e,(ix+4)
                ld d,(ix+5)
                or a
                sbc hl,de                       ; CMP AX,[bp+4]: CF — AX < X
                ld hl,#33AE
                ld de,#33DE
                jr c,.store
                ld hl,#33C6
                ld de,#3402
.store:         ld (ix+#14),l
                ld (ix+#15),h
                ld (ix+#16),e
                ld (ix+#17),d
                jp NRet

; Хвост $757B / $75D1: [bp+30] + 1; DEC [bp+22] — ноль: [bp+22] = AX = [bp+24] и $762D; DEC [bp+20] — ноль: $75F5;
; иначе [2FC4] ≠ 0 — $7768, RET.
N757B:          ld l,(ix+#30)
                ld h,(ix+#31)
                inc hl
                ld (ix+#30),l
                ld (ix+#31),h                   ; INC WORD [bp+30]
                ld l,(ix+#22)
                ld h,(ix+#23)
                dec hl
                ld (ix+#22),l
                ld (ix+#23),h                   ; DEC WORD [bp+22]
                ld a,h
                or l
                jr nz,.timer
                ld l,(ix+#24)
                ld h,(ix+#25)
                ld (V_AX),hl
                ld (ix+#22),l
                ld (ix+#23),h                   ; [bp+22] = [bp+24]
                jp N762D
.timer:         ld l,(ix+#20)
                ld h,(ix+#21)
                dec hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; DEC WORD [bp+20]
                ld a,h
                or l
                jp z,N75F5
N7594:          ld a,(#4000+#2FC4)
                or a
                jp z,NRet
                NTAIL A_07B68                   ; $7768: удаление

; ROM $0799F (IP $759F) — стоять: описание #334E / #337E (бит 15 [bp+10]); хвост $75D1.
N_759F:         call NObjCheck
                jp c,.translated
                call NScrollX
                ld hl,#334E
                bit 7,(ix+#11)
                jr z,.desc
                ld hl,#337E
.desc:          ld (V_BX),hl
                call NFlash3D                   ; $779E
                ld hl,#3426
                call NDamage3D
                jp nc,.destroy
                jp N757B
.destroy:       NTAIL A_07B7B                   ; $777B: уничтожение
.translated:    ld a,$$K_0799F
                ld hl,K_0799F
                jp FARJP

; ROM $07902 (IP $7502) — идти: описание #334E / #337E + ([bp+30] & #1C)·1,5 (CX — [bp+30] & #1C); проба рельефа
; впереди (X ± #10, Y − #C; PUSH/POP ROM): тайл < #DFC — стоять ($7617); иначе X += AX = [bp+10] ($0672); вне поля —
; $7768; хвост $757B.
N_7502:         call NObjCheck
                jp c,.translated
                call NScrollX
                ld hl,#334E
                bit 7,(ix+#11)
                jr z,.base
                ld hl,#337E
.base:          ld a,(ix+#30)
                and #1C
                ld c,a
                ld b,0
                ld (V_CX),bc                    ; CX = [bp+30] & #1C
                srl a
                add a,c
                ld e,a
                ld d,0
                ld (V_AX),de                    ; AX = CX + CX/2
                add hl,de
                ld (V_BX),hl
                call NFlash3D                   ; $779E
                ld hl,#3426
                call NDamage3D
                jp nc,.destroy
                ld hl,#10
                bit 7,(ix+#11)
                jr z,.ahead
                ld hl,#FFF0
.ahead:         ld (V_AX),hl
                ld de,-#C
                call NProbeA                    ; $1E6C в (X + AX, Y − #C)
                jp c,.probeFail
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.stand                    ; тайл < #DFC — $7617
                ld l,(ix+#10)
                ld h,(ix+#11)
                ld (V_AX),hl
                call NAddX                      ; $0672
                call NOnField                   ; $1D6B
                jp c,.remove
                jp N757B
.stand:         ld (ix+0),#9F
                ld (ix+1),#75                   ; обработчик $759F
                ld (ix+#20),8
                ld (ix+#21),0
                jp NRet
.destroy:       NTAIL A_07B7B
.remove:        NTAIL A_07B68
.probeFail:     NTAIL A_0794F                   ; PUSH [bp+4] — перевод пробы
.translated:    ld a,$$K_07902
                ld hl,K_07902
                jp FARJP

; ROM $07A54 (IP $7654) — поворот: описание NPhase3D; вне поля — $7768; [bp+30] + 1; DEC [bp+20] — ноль: обработчик
; $76AC; иначе [2FC4] ≠ 0 — $7768, RET.
N_7654:         call NObjCheck
                jp c,.translated
                call NScrollX
                call NPhase3D
                call NFlash3D                   ; $779E
                ld hl,#3426
                call NDamage3D
                jr nc,.destroy
                call NOnField
                jr c,.remove
                ld l,(ix+#30)
                ld h,(ix+#31)
                inc hl
                ld (ix+#30),l
                ld (ix+#31),h                   ; INC WORD [bp+30]
                ld l,(ix+#20)
                ld h,(ix+#21)
                dec hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; DEC WORD [bp+20]
                ld a,h
                or l
                jp nz,N7594
                ld (ix+0),#AC
                ld (ix+1),#76                   ; обработчик $76AC
                jp NRet
.destroy:       NTAIL A_07B7B
.remove:        NTAIL A_07B68
.translated:    ld a,$$K_07A54
                ld hl,K_07A54
                jp FARJP

; ROM $07AAC (IP $76AC) — стрельба: описание [bp+16] (+6 при бите 3 [bp+30] после INC); каждые 16 кадров — выстрел
; $77C1 (переводом, адрес возврата #76CF на стеке V30); вне поля — $7768; [bp+20] + 1 ≥ #80 — [bp+20] = #1F, [bp+14]
; = AX = [bp+16] + #C, обработчик $7719; иначе [2FC4] ≠ 0 — $7768, RET.
N_76AC:         call NObjCheck
                jp c,.translated
                call NScrollX
                ld l,(ix+#16)
                ld h,(ix+#17)                   ; MOV BX,[bp+16]
                ld e,(ix+#30)
                ld d,(ix+#31)
                inc de
                ld (ix+#30),e
                ld (ix+#31),d                   ; INC WORD [bp+30]
                bit 3,e
                jr z,.desc
                ld de,6
                add hl,de
.desc:          ld (V_BX),hl
                call NFlash3D                   ; $779E
                ld a,(ix+#30)
                and #0F
                jr z,.fire                      ; [bp+30] & #F = 0 — выстрел
.damage:        ld hl,#3426
                call NDamage3D
                jr nc,.destroy
                call NOnField
                jr c,.remove
                ld l,(ix+#20)
                ld h,(ix+#21)
                inc hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; INC WORD [bp+20]
                ld de,-#80
                add hl,de
                jp nc,N7594                     ; < #80
                ld (ix+#20),#1F
                ld (ix+#21),0
                ld l,(ix+#16)
                ld h,(ix+#17)
                ld de,#0C
                add hl,de
                ld (V_AX),hl
                ld (ix+#14),l
                ld (ix+#15),h                   ; [bp+14] = [bp+16] + #C
                ld (ix+0),#19
                ld (ix+1),#77                   ; обработчик $7719
                jp NRet
.fire:          ld hl,#76CF
                push hl                         ; CALL $77C1: адрес возврата
                NTAIL A_07BC1                   ; выстрел — переводом
.destroy:       NTAIL A_07B7B
.remove:        NTAIL A_07B68
.translated:    ld a,$$K_07AAC
                ld hl,K_07AAC
                jp FARJP

; ROM $07B19 (IP $7719) — отход: описание NPhase3D; вне поля — $7768; [bp+30] + 1; DEC [bp+20] — ноль: $75F5; иначе
; [2FC4] ≠ 0 — $7768, RET.
N_7719:         call NObjCheck
                jp c,.translated
                call NScrollX
                call NPhase3D
                call NFlash3D                   ; $779E
                ld hl,#3426
                call NDamage3D
                jr nc,.destroy
                call NOnField
                jr c,.remove
                ld l,(ix+#30)
                ld h,(ix+#31)
                inc hl
                ld (ix+#30),l
                ld (ix+#31),h                   ; INC WORD [bp+30]
                ld l,(ix+#20)
                ld h,(ix+#21)
                dec hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; DEC WORD [bp+20]
                ld a,h
                or l
                jp z,N75F5
                jp N7594
.destroy:       NTAIL A_07B7B
.remove:        NTAIL A_07B68
.translated:    ld a,$$K_07B19
                ld hl,K_07B19
                jp FARJP

; ROM $07C0E (IP $780E) — снаряд семейства: X += AX = [bp+30], Y += AX = [bp+20] ($0672, $0689); описание #343A /
; #3446 / #3452 / #345E по [bp+20] (≥ #240, #180, #100), +6 при [bp+30] ≥ 0; спрайт $1BCC; тайл слоя A в точке ($1E6C)
; < #DFC — взрыв $7875; вне поля — $786B; столкновения $F694 с хитбоксом #34A6 (попадание — $7875); [bp+20] − #10 с
; заёмом — $7886; [2FC4] ≠ 0 — $786B; иначе RET (все концы — переводом).
N_780E:         call NObjCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld (V_AX),hl
                call NAddY                      ; $0689
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld de,#343A
                ld bc,-#240
                add hl,bc
                jr c,.plus
                ld de,#3446
                ld bc,#240-#180
                add hl,bc
                jr c,.plus
                ld de,#3452
                ld bc,#180-#100
                add hl,bc
                jr c,.plus
                ld de,#345E
.plus:          bit 7,(ix+#31)
                jr nz,.desc
                ld hl,6
                add hl,de
                ex de,hl
.desc:          ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jp c,.spriteFail
                ld hl,(V_BP)
                call TerrainA                   ; $1E6C: V_AX — тайл; IX → [bp]
                jp c,.terrainFail
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.blast                    ; тайл < #DFC
                call NOnField                   ; $1D6B
                jr c,.remove
                ld hl,#34A6
                ld (V_DI),hl                    ; MOV DI,#34A6
                call CollideSetup               ; $F694: хитбокс ES:DI
                jp c,.collideFail
                push ix
                call CollideA94
                pop ix
                jr c,.blast
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld de,-#10
                add hl,de
                ld (ix+#20),l
                ld (ix+#21),h                   ; SUB WORD [bp+20],#10
                jr nc,.fall                     ; заём — $7886
                ld a,(#4000+#2FC4)
                or a
                jp z,NRet
.remove:        NTAIL A_07C6B                   ; $786B
.blast:         NTAIL A_07C75                   ; $7875
.fall:          NTAIL A_07C86                   ; $7886
.spriteFail:    NTAIL A_07C45                   ; CALL $1BCC
.terrainFail:   NTAIL A_07C48                   ; CALL $1E6C
.collideFail:   NTAIL A_07C58                   ; CALL $F694
.translated:    ld a,$$K_07C0E
                ld hl,K_07C0E
                jp FARJP

; ROM $0EAC0 (IP $E6C0) — снаряд врага (этапы 3, 5): X += AX = [bp+30] ($0672); пара спрайтов $1C1B по описанию BX =
; ([2EB6] & 6)·6 + #84CE (AX = ([2EB6] & 6)·2); столкновение с R-9 $F485 по хитбоксу BX = #84FE — попадание: [#57] =
; #FF; [2FC4] ≠ 0 или вне поля ($1D6B) — удаление ($E6F6, переводом); иначе RET. Регистры — как у ROM; флаги у выходов
; не живут. Условия (иначе перевод с входа): NObjCheck; отказ описания и подготовки столкновения — переводом с места.
N_E6C0:         call NObjCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld a,(#4000+#2EB6)
                and 6
                add a,a
                ld l,a
                ld h,0
                ld (V_AX),hl                    ; AX = ([2EB6] & 6)·2
                ld e,a
                add a,a
                add a,e
                ld l,a                          ; ([2EB6] & 6)·6
                ld de,#84CE
                add hl,de
                ld (V_BX),hl
                call NSpritePair                ; $1C1B
                jp c,.spriteFail
                ld hl,#84FE
                ld (V_BX),hl                    ; MOV BX,#84FE
                call CollideSetup               ; хитбокс ES:BX
                jp c,.collideFail
                call Collide85                  ; $F485: SI = #56, CF — попадание
                jr nc,.field
                ld a,#FF
                ld (#4000+#57),a                ; MOV BYTE [si+1],#FF
.field:         ld a,(#4000+#2FC4)
                or a
                jr nz,.free
                call NOnField                   ; $1D6B
                jp nc,NRet
.free:          NTAIL A_0EAF6                   ; $E6F6: ресурс и CALL $03EC
.spriteFail:    NTAIL A_0EADA                   ; CALL $1C1B
.collideFail:   NTAIL A_0EAE0                   ; CALL $F485
.translated:    ld a,$$K_0EAC0
                ld hl,K_0EAC0
                jp FARJP

; ROM $0BD97 (IP $B997) и $0BDFD (IP $B9FD) — два состояния врага этапа 7 (профиль этапа 7 — перевод ≈0,7 % тактов):
; X += AX = [2ED0]; [2FC4] ≠ 0 — удаление $BA91 (переводом); [bp+30] + 1; описание пары $1C1B по порогам счётчика —
; у $B997 AX = [bp+30] − [bp+20] (CX): заём — #60E6, дальше шагом #10: #60F2, #60FE, #610A; у $B9FD AX = [bp+30]: #610A,
; #60FE, #60F2, #60E6; на пороге, где AX стал ровно 0, — звук #68; [bp+1F] = 0, [bp+2F] = #A0; урон $F75F с хитбоксом
; #6116. Затем у $B997 родитель BX = [bp+10]: [bx+30] ≠ 0 — [bp+30] = 0, обработчик $B9FD; [bx+31] ≠ 0 — $BA4E
; (переводом); у $B9FD X < #120 — удаление. Регистры — как у ROM; флаги у выходов не живут. Условия (иначе перевод с
; входа): NObjCheck; родитель у края рабочего ОЗУ — переводом с $B9E2.
N_B9FD:         ld a,1
                jr N_B997.mode
N_B997:         xor a
.mode:          ld (N_B99V),a
                call NObjCheck
                jp c,.translated
                call NScrollX                   ; ADD [bp+4],AX (AX = [2ED0])
                ld a,(#4000+#2FC4)
                or a
                jp nz,.free
                ld l,(ix+#30)
                ld h,(ix+#31)
                inc hl
                ld (ix+#30),l
                ld (ix+#31),h                   ; INC WORD [bp+30]
                ld a,(N_B99V)
                or a
                jr nz,.down
                ld e,(ix+#20)
                ld d,(ix+#21)
                ld (V_CX),de                    ; CX = [bp+20]
                or a
                sbc hl,de                       ; AX = [bp+30] − CX
                ld de,#60E6
                jr c,.pair
                ld de,#60F2
                ld bc,-#10
                add hl,bc
                jr nc,.pair                     ; заём
                call .zeroSound
                ld de,#60FE
                ld bc,-#10
                add hl,bc
                jr nc,.pair
                ld de,#610A
                jr .pair
.down:          ld de,#610A
                ld bc,-#10
                add hl,bc                       ; AX = [bp+30] − #10
                jr nc,.pair
                ld de,#60FE
                ld bc,-#10
                add hl,bc
                jr nc,.pair
                call .zeroSound
                ld de,#60F2
                ld bc,-#10
                add hl,bc
                jr nc,.pair
                ld de,#60E6
.pair:          ld (V_AX),hl                    ; AX — после последнего SUB
                ld (V_BX),de
                call NSpritePair                ; $1C1B
                jp c,.pairFail
                ld (ix+#1F),0
                ld (ix+#2F),#A0
                ld hl,#6116
                ld (V_DI),hl                    ; MOV DI,#6116
                push ix
                pop iy
                call NDamageB6                  ; $F75F
                push iy
                pop ix
                ld a,(N_B99V)
                or a
                jr nz,.edge
                ld l,(ix+#10)
                ld h,(ix+#11)
                ld (V_BX),hl                    ; MOV BX,[bp+10]
                ld a,h
                cp #3F
                jr nc,.parentFail
                set 6,h
                ld de,#30
                add hl,de
                ld a,(hl)
                or a
                jr nz,.release                  ; [bx+30] ≠ 0
                inc hl
                ld a,(hl)
                or a
                jp z,NRet
                NTAIL A_0BE4E                   ; [bx+31] ≠ 0 — $BA4E
.release:       ld (ix+#30),0
                ld (ix+#31),0                   ; MOV WORD [bp+30],0
                ld (ix+0),#FD
                ld (ix+1),#B9                   ; обработчик $B9FD
                jp NRet
.edge:          ld l,(ix+4)
                ld h,(ix+5)
                ld de,-#120
                add hl,de
                jp c,NRet                       ; X ≥ #120
.free:          NTAIL A_0BE91                   ; $BA91: удаление
.parentFail:    NTAIL A_0BDE2                   ; MOV BX,[bp+10] — переводом
.pairFail:      ld a,(N_B99V)
                or a
                jr nz,.pairFail2
                NTAIL A_0BDD1                   ; CALL $1C1B ($B9D1)
.pairFail2:     NTAIL A_0BE35                   ; CALL $1C1B ($BA35)
; AX (HL) после SUB ровно 0 — звук #68 (CL; AX и BX у ROM сохраняются). Портит AF, BC; HL, DE сохраняет.
.zeroSound:     ld a,h
                or l
                ret nz
                push hl
                push de
                ld a,#68
                ld (V_CX),a                     ; MOV CL,#68
                call NSound                     ; $0303
                pop de
                pop hl
                ret
.translated:    ld a,(N_B99V)
                or a
                jr nz,.translated2
                ld a,$$K_0BD97
                ld hl,K_0BD97
                jp FARJP
.translated2:   ld a,$$K_0BDFD
                ld hl,K_0BDFD
                jp FARJP

; Пара спрайтов со вспышкой ($7D45 этапа 5): BX — описание (V_BX); [bp+3F] ≠ 0 — DEC, при (& 3) = 0 — пара с ресурсом
; [bp+6] = [bp+3E] (AL — он же; PUSH/POP ROM), иначе — обычная пара $1C1B. CF = 1 — описание через границу страницы
; ([bp+6] прежний). IX → [bp]. Портит всё, кроме IX.
NPairFlash3F:   ld a,(ix+#3F)
                or a
                jr z,.plain
                dec a
                ld (ix+#3F),a
                and 3
                jr nz,.plain
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3E)
                ld (V_AX),a                     ; AL = [bp+3E]
                ld (ix+6),a
                call NSpritePair                ; $1C1B
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                ret
.plain:         jp NSpritePair

; ROM $07DC1 (IP $79C1) — звено змеи этапа 5 (профиль этапа 5 — перевод ≈0,5 % тактов): [2FC4] ≠ 0 — $7C3D; скрипт
; $F5C1 (CF — $7C3D); [bp+17] = 2, [bp+20] = ([bp+20] + 1) & #7F, < #1F — [bp+17] = 1; пара со вспышкой $7D45 по
; описанию [bp+16]·12 + #3526 (AX = [bp+16]·4); урон $F6DA с хитбоксом #37C6 (попадание — [bp+3F] = #0C, CL = #57, звук);
; [bp+1F] ≥ #0E — [bp+1E] = 1 и $7C50 (переводом); иначе RET. Условия (иначе перевод с входа): NObjCheck и [bp+17] ≠ 0.
N_79C1:         call NObjCheck
                jp c,.translated
                ld a,(#4000+#2FC4)
                or a
                jp nz,.leave                    ; $7C3D
                ld a,(ix+#17)
                or a
                jp z,.translated                ; скрипт без шагов — ядро его не берёт
                call ScriptCore                 ; $F5C1
                jp c,.leave
                ld (ix+#17),2
                ld a,(ix+#20)
                inc a
                and #7F
                ld (ix+#20),a
                ld (ix+#21),0                   ; INC WORD и AND #7F: старший байт — 0
                cp #1F
                jr nc,.sprite
                ld (ix+#17),1
.sprite:        ld l,(ix+#16)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_AX),hl                    ; AX = [bp+16]·4
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; ·12
                ld de,#3526
                add hl,de
                ld (V_BX),hl
                call NPairFlash3F               ; $7D45
                jp c,.pairFail
                ld hl,#37C6
                ld (V_DI),hl
                push ix
                pop iy
                call NDamage                    ; $F6DA
                jr z,.hp
                ld (iy+#3F),#0C
                ld a,#57
                ld (V_CX),a                     ; CL = #57
                call NSound
.hp:            push iy
                pop ix
                ld a,(ix+#1F)
                cp #0E
                jp c,NRet
                ld (ix+#1E),1
                NTAIL A_08050                   ; $7C50
.leave:         NTAIL A_0803D                   ; $7C3D
.pairFail:      NTAIL A_07DFC                   ; CALL $7D45 — переводом
.translated:    ld a,$$K_07DC1
                ld hl,K_07DC1
                jp FARJP

; ROM $09215 (IP $8E15) — враг этапа 2 (профиль этапа 2 — перевод ≈0,5 % тактов): DEC [bp+26] — ноль: $8EFA (переводом,
; адрес возврата #8E1D на стеке V30); X += AX = [bp+30], Y += AX = [bp+32]; описание: [bp+38] ≠ 0 — #3F56, иначе
; #3F56 + t + t/2, t = (([2EB6] + [bp+16]) & #18) >> 1 (AX = t/2); спрайт со вспышкой $8EA9 (≡ NFlash3D); урон $F6DA с
; хитбоксом #3F6E (попадание — [bp+3D] = #0C, CL = #57, звук, $8ECC); AL = [bp+1F] ≥ [bp+2F] — $8E86, [2FC4] ≠ 0 —
; $8E73 (оба переводом); иначе RET. Условия (иначе перевод с входа): NObjCheck.
N_8E15:         call NObjCheck
                jp c,.translated
                ld l,(ix+#26)
                ld h,(ix+#27)
                dec hl
                ld (ix+#26),l
                ld (ix+#27),h                   ; DEC WORD [bp+26]
                ld a,h
                or l
                jr nz,.move
                ld hl,#8E1D
                push hl                         ; CALL $8EFA: адрес возврата
                NTAIL A_092FA                   ; $8EFA — переводом
.move:          ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld l,(ix+#32)
                ld h,(ix+#33)
                ld (V_AX),hl
                call NAddY                      ; $0689
                ld hl,0
                ld a,(ix+#38)
                or (ix+#39)
                jr nz,.base                     ; [bp+38] ≠ 0 — BX = 0
                ld a,(#4000+#2EB6)
                add a,(ix+#16)
                and #18
                rrca                            ; t
                ld e,a
                rrca                            ; t/2
                ld l,a
                ld (V_AX),hl                    ; AX = t/2 (H = 0)
                add a,e
                ld l,a                          ; BX = t + t/2
.base:          ld de,#3F56
                add hl,de
                ld (V_BX),hl
                call NFlash3D                   ; $8EA9
                ld hl,#3F6E
                ld (V_DI),hl
                push ix
                pop iy
                call NDamage                    ; $F6DA
                jr z,.hp
                ld (iy+#3D),#0C
                ld a,#57
                ld (V_CX),a                     ; CL = #57
                call NSound
                push iy
                pop ix
                call .turn                      ; $8ECC
                jr .hp2
.hp:            push iy
                pop ix
.hp2:           ld a,(ix+#1F)
                ld (V_AX),a                     ; MOV AL,[bp+1F]
                cp (ix+#2F)
                jr nc,.destroy
                ld a,(#4000+#2FC4)
                or a
                jp z,NRet
                NTAIL A_09273                   ; $8E73: удаление
.destroy:       NTAIL A_09286                   ; $8E86: уничтожение
; $8ECC: [bp+30] = 0, [bp+32] = #FD00; AX = [bp+8] − #B0: заём — [bp+30] = [bp+32] = 0, [bp+26] = 1; иначе [bp+38] = 1,
; [bp+26] = AX = (AX >> 1) + 1. Портит AF, DE, HL.
.turn:          ld (ix+#30),0
                ld (ix+#31),0
                ld (ix+#32),0
                ld (ix+#33),#FD
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,-#B0
                add hl,de                       ; SUB AX,#B0 (CF = 1 — без заёма)
                ld (V_AX),hl
                jr nc,.low
                ld (ix+#38),1
                ld (ix+#39),0
                srl h
                rr l
                inc hl
                ld (V_AX),hl
                ld (ix+#26),l
                ld (ix+#27),h
                ret
.low:           ld (ix+#32),0
                ld (ix+#33),0                   ; [bp+32] = 0 ([bp+30] уже 0)
                ld (ix+#26),1
                ld (ix+#27),0
                ret
.translated:    ld a,$$K_09215
                ld hl,K_09215
                jp FARJP

; ROM $05FA4 (IP $5BA4) и $0603E (IP $5C3E) — прыжок и приземление ходока этапов 1 и 6 (профиль этапа 6 — перевод
; ≈0,6 % тактов): счётчик $F63A (порождение — переводом с адресом возврата #5BA7 / #5C41); $5BA4: Y −= 3; описание
; #2970 (при [bp+1E] = 0 — X += [2ED0] и #294C), +6 при бите 3 [2EB6] = 0; спрайт с ресурсом [bp+6] = [bp+3C] (PUSH/POP
; ROM); столкновения $F694 с хитбоксом #2982 (попадание — $5C83), вне поля или [2FC4] ≠ 0 — $5CD7 (оба переводом); проба
; рельефа $1E6C в (X ± 8, Y − #10): тайл < #DFC — приземление ([bp+8] = ([bp+8] + 7) & #FFF8, [bp+20] = #292A / #2932,
; [bp+22] = 4, обработчик $5C3E). $5C3E: при [bp+1E] = 0 — X += [2ED0]; спрайт по описанию ES:[[bp+20]]; столкновения;
; [2FC4]; DEC [bp+22] — ноль: [bp+22] = 4, [bp+20] += 2, слово ES:[[bp+20]] = 0 — обработчик $5A2B. Условия (иначе
; перевод с входа): NEnemyCheck; отказы описаний, подготовки столкновений и пробы — переводом с места.
N_5BA4:         call NEnemyCheck
                jp c,.translated
                call CounterCore                ; $F63A
                or a
                jr z,.counted
                ld hl,#5BA7
                push hl
                NTAIL A_0FA57                   ; порождение — переводом
.counted:       ld l,(ix+8)
                ld h,(ix+9)
                ld de,-3
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; SUB WORD [bp+8],3
                ld hl,#2970
                ld a,(ix+#1E)
                or a
                jr nz,.frame
                call NScrollX                   ; ADD [bp+4],AX
                ld hl,#294C
.frame:         ld a,(#4000+#2EB6)
                and 8
                jr nz,.desc
                ld de,6
                add hl,de
.desc:          ld (V_BX),hl
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3C)
                ld (V_AX),a
                ld (ix+6),a                     ; [bp+6] = AL = [bp+3C]
                call NSpriteAdd                 ; $1BCC
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                jp c,.spriteFail
                ld hl,#2982
                ld (V_DI),hl
                call CollideSetup               ; $F694
                jp c,.collideFail
                push ix
                call CollideA94
                pop ix
                jp c,.hit
                call NOnField
                jp c,.remove
                ld a,(#4000+#2FC4)
                or a
                jp nz,.remove
                ld hl,8
                ld a,(ix+#1E)
                or a
                jr nz,.ahead
                ld hl,-8
.ahead:         ld (V_AX),hl
                ld de,-#10
                call NProbeA                    ; $1E6C в (X + AX, Y − #10)
                jp c,.probeFail
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jp c,NRet                       ; тайл ≥ #DFC — RET
                ld l,(ix+8)
                ld h,(ix+9)
                ld de,7
                add hl,de
                ld a,l
                and #F8
                ld (ix+8),a
                ld (ix+9),h                     ; [bp+8] = ([bp+8] + 7) & #FFF8
                ld hl,#292A
                ld a,(ix+#1E)
                or a
                jr z,.land
                ld hl,#2932
.land:          ld (V_AX),hl
                ld (ix+#20),l
                ld (ix+#21),h
                ld (ix+#22),4
                ld (ix+0),#3E
                ld (ix+1),#5C                   ; обработчик $5C3E
                jp NRet
.hit:           NTAIL A_06083                   ; $5C83
.remove:        NTAIL A_060D7                   ; $5CD7
.spriteFail:    NTAIL A_05FC8                   ; PUSH [bp+6] … CALL $1BCC — переводом ([bp+6] прежний)
.collideFail:   NTAIL A_05FDA                   ; CALL $F694
.probeFail:     NTAIL A_05FF4                   ; PUSH [bp+4] — проба переводом
.translated:    ld a,$$K_05FA4
                ld hl,K_05FA4
                jp FARJP

N_5C3E:         call NEnemyCheck
                jp c,.translated
                call CounterCore                ; $F63A
                or a
                jr z,.counted
                ld hl,#5C41
                push hl
                NTAIL A_0FA57
.counted:       ld a,(ix+#1E)
                or a
                jr nz,.frame
                call NScrollX
.frame:         ld l,(ix+#20)
                ld h,(ix+#21)
                ld (V_BX),hl
                call NWord1000                  ; BX = ES:[bx]
                jp c,.frameFail
                ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jp c,.spriteFail
                ld hl,#2982
                ld (V_DI),hl
                call CollideSetup               ; $F694
                jp c,.collideFail
                push ix
                call CollideA94
                pop ix
                jp c,N_5BA4.hit
                ld a,(#4000+#2FC4)
                or a
                jp nz,N_5BA4.remove
                dec (ix+#22)
                jp nz,NRet
                ld (ix+#22),4
                ld l,(ix+#20)
                ld h,(ix+#21)
                inc hl
                inc hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; ADD WORD [bp+20],2
                ld (V_BX),hl
                call NWord1000                  ; AX = ES:[bx]
                jp c,.nextFail
                ld (V_AX),de
                ld a,d
                or e
                jp nz,NRet
                ld (ix+0),#2B
                ld (ix+1),#5A                   ; обработчик $5A2B
                jp NRet
.frameFail:     NTAIL A_06050                   ; MOV BX,ES:[bx]
.spriteFail:    NTAIL A_06053                   ; CALL $1BCC
.collideFail:   NTAIL A_06059                   ; CALL $F694
.nextFail:      NTAIL A_06075                   ; MOV AX,ES:[bx]
.translated:    ld a,$$K_0603E
                ld hl,K_0603E
                jp FARJP

; ROM $020A6 (IP $1CA6, 15 мест вызова): три спрайта объекта BP по описаниям ES:BX, ES:BX+6, ES:BX+12 — в память
; спрайтов C000:SI, C000:DI, C000:DI' (SI = [2EFC], DI = SI + размер первой, DI' = DI + размер второй; размер — 8, при
; бите 14 атрибута описания — 16). DI ≥ #3C8 — возврат без записи (AX = размер первой); затем CX = [bp+4], DX = [bp+8],
; первая запись; SI = DI, DI += размер второй, DI ≥ #3C8 — возврат (AX = размер второй); вторая запись; AX = DI + размер
; третьей ≥ #3C8 — возврат ([2EFC] прежний); иначе [2EFC] = AX и третья запись в C000:DI. AX — атрибут последней
; записанной. Флаги после RET не живут. DS ≠ #4000, BP у края рабочего ОЗУ или описание через границу страницы —
; перевод с входа.
N_1CA6:         ld hl,(V_DS)
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
                pop ix                          ; IX → объект (окно W1)
                call NSpriteTriple
                jp nc,NRet
.translated:    ld a,$$K_020A6
                ld hl,K_020A6
                jp FARJP

; Тело $1CA6 для нативных вызовов: IX → объект, описание ES:V_BX (18 байт). CF = 1 — ES ≠ #1000 (три описания в
; кэше — только у ROM) или описание через границу страницы (ничего не сделано). Портит всё, кроме IX.
NSpriteTriple:  ld hl,(V_ES)
                ld a,h
                xor #10
                or l
                scf
                ret nz
                call NDescCache                 ; ES:BX
                ret c
                ld (N_DESCP1),de
                ld hl,(V_BX)
                push hl
                ld de,6
                add hl,de
                ld (V_BX),hl
                call NDescCache                 ; ES:BX+6 (индекс кэша сдвинут на 3…4 — запись другая)
                jp c,.fail
                ld (N_DESCP2),de
                ld hl,(V_BX)
                ld de,6
                add hl,de
                ld (V_BX),hl
                call NDescCache                 ; ES:BX+12
                jp c,.fail
                ld (N_DESCP3),de
                pop hl
                ld (V_BX),hl                    ; BX прежний
                ld hl,(#4000+#2EFC)
                ld (V_SI),hl                    ; SI = [2EFC]
                ld de,(N_DESCP1)
                call .size
                ld (V_AX),de                    ; AX = размер первой
                add hl,de
                ld (V_DI),hl                    ; DI = SI + размер
                call .full
                ret c                           ; DI ≥ #3C8: CF = 0 (без записи)
                ld l,(ix+4)
                ld h,(ix+5)
                ld (V_CX),hl                    ; CX = [bp+4]
                ld l,(ix+8)
                ld h,(ix+9)
                ld (V_DX),hl                    ; DX = [bp+8]
                call NMapSprites
                ld hl,(V_SI)
                set 7,h
                ld de,(N_DESCP1)
                call NSpriteEntry               ; C000:SI
                ld hl,(N_DESCP1)
                call .attr                      ; AX = атрибут первой
                ld hl,(V_DI)
                ld (V_SI),hl                    ; SI = DI
                ld de,(N_DESCP2)
                call .size
                ld (V_AX),de                    ; AX = размер второй
                add hl,de
                ld (V_DI),hl                    ; DI += размер
                call .full
                ret c
                ld hl,(V_SI)
                set 7,h
                ld de,(N_DESCP2)
                call NSpriteEntry               ; C000:SI
                ld hl,(N_DESCP2)
                call .attr
                ld de,(N_DESCP3)
                call .size
                ld hl,(V_DI)
                add hl,de
                ld (V_AX),hl                    ; AX = DI + размер третьей
                call .full
                ret c                           ; [2EFC] прежний
                ld (#4000+#2EFC),hl
                ld hl,(V_DI)
                set 7,h
                ld de,(N_DESCP3)
                call NSpriteEntry               ; C000:DI
                ld hl,(N_DESCP3)
                call .attr
                or a
                ret
.fail:          pop hl
                ld (V_BX),hl
                scf
                ret
; DE → описание: DE = размер записи (8, при бите 6 байта +5 — 16); HL сохраняется. Портит AF.
.size:          push hl
                ld hl,5
                add hl,de
                ld a,(hl)
                pop hl
                ld de,8
                bit 6,a
                ret z
                ld e,16
                ret
; HL (значение) ≥ #3C8 — CF = 1 (возврат ROM; вызывающий отдаёт CF = 0); HL сохраняется. Портит AF, BC.
.full:          push hl
                ld bc,-#3C8
                add hl,bc
                pop hl
                ret nc
                pop bc                          ; снять адрес возврата .full: выход из NSpriteTriple
                or a                            ; CF = 0 — сделано всё, что сделал бы ROM
                ret
; HL → описание: AX = атрибут записи (младший — [bp+6], старший — байт +5 описания). Портит AF, DE, HL.
.attr:          ld de,5
                add hl,de
                ld a,(hl)
                ld (V_AX+1),a
                ld a,(ix+6)
                ld (V_AX),a
                ret

; Спрайты части линкора $D497: BX = #7B28 — три спрайта $1CA6, #7B3A — пара $1C1B; [bp+3D] ≠ 0 — DEC и в нечётном кадре
; — с ресурсом [bp+6] = [bp+3C] (AL — он же; PUSH/POP ROM). CF = 1 — описание через границу (переводом с места вызова
; $D497; [bp+3D] и [bp+6] — как до вызова не будут: у этих описаний ROM не бывает). IX → [bp]. Портит всё, кроме IX.
NPartSprite3:   ld a,(ix+#3D)
                or a
                jr z,.plain
                dec a
                ld (ix+#3D),a
                ld a,(#4000+#2EB6)
                rra
                jr nc,.plain                    ; чётный кадр
                ld l,(ix+6)
                ld h,(ix+7)
                push hl                         ; PUSH WORD [bp+6]
                ld a,(ix+#3C)
                ld (V_AX),a
                ld (ix+6),a
                call .plain
                pop hl
                ld (ix+6),l
                ld (ix+7),h                     ; POP WORD [bp+6]
                ret
.plain:         ld hl,#7B28
                ld (V_BX),hl
                call NSpriteTriple              ; $1CA6
                ret c
                ld hl,#7B3A
                ld (V_BX),hl
                jp NSpritePair                  ; $1C1B

; ROM $0D7C9 (IP $D3C9) — часть линкора этапа 3 (профиль этапа 3 — перевод ≈0,8 % тактов): X += [2ED4], Y += AX =
; [2ED6]; спрайты $D497; урон $F75F с хитбоксом #7B46 (попадание — [bp+3D] = 5, CL = #56, звук); AL = [bp+1F] ≥
; [bp+2F], DEC [bp+10] до нуля или слово [[bp+3E]+3E] ≠ 0 — $D47F (переводом); R-9 по Y в пределах [#28] − #10 … +#20
; от точки — [bp+20] = ([bp+20] + 1) & #3F, ноль — выстрел ($D426, переводом); иначе [bp+20] = 0; [2FC4] ≠ 0 — $D503
; (переводом); иначе RET. Условия (иначе перевод с входа): NObjCheck и [bp+3E] < #3F00.
N_D3C9:         call NObjCheck
                jp c,.translated
                ld a,(ix+#3F)
                cp #3F
                jp nc,.translated
                ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,(#4000+#2ED6)
                ld (V_AX),hl
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD [bp+8],AX
                call NPartSprite3               ; $D497
                jp c,.spriteFail
                ld hl,#7B46
                ld (V_DI),hl
                push ix
                pop iy
                call NDamageB6                  ; $F75F
                jr z,.hp
                ld (iy+#3D),5
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound
.hp:            push iy
                pop ix
                ld a,(ix+#1F)
                ld (V_AX),a                     ; MOV AL,[bp+1F]
                cp (ix+#2F)
                jr nc,.phase
                ld l,(ix+#10)
                ld h,(ix+#11)
                dec hl
                ld (ix+#10),l
                ld (ix+#11),h                   ; DEC WORD [bp+10]
                ld a,h
                or l
                jr z,.phase
                ld l,(ix+#3E)
                ld h,(ix+#3F)
                ld (V_BX),hl                    ; MOV BX,[bp+3E]
                set 6,h
                ld de,#3E
                add hl,de
                ld a,(hl)
                inc hl
                or (hl)
                jr nz,.phase                    ; [bx+3E] ≠ 0
                ld hl,(#4000+#28)
                ld de,-#10
                add hl,de                       ; AX = [#28] − #10
                ld (V_AX),hl
                ld e,(ix+8)
                ld d,(ix+9)
                or a
                sbc hl,de                       ; CMP AX,[bp+8]
                jr nc,.idle                     ; AX ≥ Y
                add hl,de
                ld bc,#30
                add hl,bc
                ld (V_AX),hl                    ; AX += #30
                or a
                sbc hl,de
                jr c,.idle                      ; AX < Y
                ld a,(ix+#20)
                inc a
                and #3F
                ld (ix+#20),a
                ld (ix+#21),0                   ; INC WORD и AND #3F
                jr nz,.field
                NTAIL A_0D826                   ; $D426: выстрел
.idle:          ld (ix+#20),0
                ld (ix+#21),0                   ; MOV WORD [bp+20],0
.field:         ld a,(#4000+#2FC4)
                or a
                jp z,NRet
                NTAIL A_0D903                   ; $D503
.phase:         NTAIL A_0D87F                   ; $D47F: смена фазы
.spriteFail:    NTAIL A_0D7D5                   ; CALL $D497 — переводом
.translated:    ld a,$$K_0D7C9
                ld hl,K_0D7C9
                jp FARJP

; ROM $06DB4 (IP $69B4) — «каменщик» этапа 4 (профиль этапа 4 — перевод ≈0,5 % тактов): скрипт $F5C1 (CF — удаление
; $6A42); X += [2ED0]; счётчик $F63A (порождение — переводом с адресом возврата #69C5); спрайт со вспышкой $6A78 (≡
; NFlash3D) по описанию [bp+16]·6 + #2DD0 (AX = [bp+16]·2); проба рельефа $1E6C в точке + ES:[#2D90/#2D92 + [bp+16]·4]
; (PUSH/POP ROM); слово VRAM слоя A в найденном месте (ES = #D000): & #FFF = #FA0 — туда #09F6 и #0082 (разрушаемый
; блок; пометки для адаптера — VIDEO_MARK_RANGE); урон $F6DA с хитбоксом #2E36 (попадание — [bp+3D] = #0C, CL = #56,
; звук); AL = [bp+1F] ≥ [bp+2F] — $6A55, [2FC4] ≠ 0 — $6A42 (оба переводом); иначе RET. Условия (иначе перевод с
; входа): NObjCheck и [bp+17] ≠ 0 (условие ядра скрипта); отказы пробы и слова VRAM у края страницы — переводом с места.
N_69B4:         call NObjCheck
                jp c,.translated
                ld a,(ix+#17)
                or a
                jp z,.translated
                call ScriptCore                 ; $F5C1
                jp c,.free
                call NScrollX                   ; ADD [bp+4],AX
                call CounterCore                ; $F63A
                or a
                jr z,.counted
                ld hl,#69C5
                push hl
                NTAIL A_0FA57                   ; порождение — переводом
.counted:       ld l,(ix+#16)
                ld h,0
                add hl,hl
                ld (V_AX),hl                    ; AX = [bp+16]·2
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; ·6
                ld de,#2DD0
                add hl,de
                ld (V_BX),hl
                call NFlash3D                   ; $6A78
                ld l,(ix+#16)
                ld h,0
                add hl,hl
                add hl,hl
                ld (V_BX),hl                    ; BX = [bp+16]·4
                push hl
                ld de,#2D90
                add hl,de
                call NWord1000
                ld (V_AX),de                    ; AX = ES:[bx+#2D90]
                pop hl
                push de
                ld de,#2D92
                add hl,de
                call NWord1000
                ld (V_CX),de                    ; CX = ES:[bx+#2D92]
                pop hl                          ; HL = AX, DE = CX
                call NProbeA                    ; $1E6C в (X + AX, Y + CX)
                jp c,.probeFail
                ld hl,(V_BX)                    ; слово VRAM слоя A по смещению BX
                ld a,h
                cp #3F
                jr c,.inside
                ld a,l
                cp #FC
                jp nc,.vramFail                 ; BX + 3 > #3FFF
.inside:        ld a,(W2_PAGE)
                cp #34
                ld a,#34
                call nz,NMap2                   ; VRAM слоя A (#D0000) — окно W2
                ld hl,(V_BX)
                set 7,h
                ld e,(hl)
                inc hl
                ld a,(hl)
                and #0F
                ld d,a                          ; AX = ES:[bx] & #FFF
                ld (V_AX),de
                ld a,e
                cp #A0
                jr nz,.damage
                ld a,d
                cp #0F
                jr nz,.damage
.block:         ld (hl),#09
                dec hl
                ld (hl),#F6                     ; ES:[bx] = #09F6
                inc hl
                inc hl
                ld (hl),#82
                inc hl
                ld (hl),0                       ; ES:[bx+2] = #0082
                ld hl,(V_BX)
                ld d,h
                ld e,l
                inc de
                inc de
                inc de
                ld a,#34
                call VIDEO_MARK_RANGE           ; группы и строки слова пары
.damage:        ld hl,#2E36
                ld (V_DI),hl
                push ix
                pop iy
                call NDamage                    ; $F6DA
                jr z,.hp
                ld (iy+#3D),#0C
                ld a,#56
                ld (V_CX),a                     ; CL = #56
                call NSound
.hp:            push iy
                pop ix
                ld a,(ix+#1F)
                ld (V_AX),a                     ; MOV AL,[bp+1F]
                cp (ix+#2F)
                jr nc,.destroy
                ld a,(#4000+#2FC4)
                or a
                jp z,NRet
.free:          NTAIL A_06E42                   ; $6A42: удаление
.destroy:       NTAIL A_06E55                   ; $6A55: уничтожение
.probeFail:     NTAIL A_06DEC                   ; PUSH [bp+4] — проба переводом
.vramFail:      NTAIL A_06E01                   ; PUSH ES — слово VRAM переводом
.translated:    ld a,$$K_06DB4
                ld hl,K_06DB4
                jp FARJP

; ROM $07835 (IP $7435) — снаряд врага этапа 6 (профиль этапа 6 — перевод ≈0,4 % тактов): X += AX = [bp+30], Y += AX
; = [bp+32]; описание #327E + t + t/2, t = ((BP >> 3) + [2EB6]) & #18 >> 1 (CX = t); спрайт $1BCC; столкновение с R-9
; $F485 (хитбокс #3296; попадание — [#57] = 1) и с Force $F578 (запись #76; попадание — взрыв $E686 переводом); в
; нечётном кадре — RET; таймер [bp+20] ≠ 0 — DEC, иначе рельеф $1EB5 (стена — взрыв); [2FC4] ≠ 0 или вне поля —
; удаление $74AA (переводом); иначе RET. Условия (иначе перевод с входа): NObjCheck; отказы — переводом с места.
N_7435:         call NObjCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_AX),hl
                call NAddX                      ; $0672
                ld l,(ix+#32)
                ld h,(ix+#33)
                ld (V_AX),hl
                call NAddY                      ; $0689
                ld hl,(V_BP)
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l                            ; BX = BP >> 3
                ld de,(#4000+#2EB6)
                add hl,de                       ; + [2EB6]
                ld a,l
                and #18
                rrca                            ; t
                ld c,a
                ld b,0
                ld (V_CX),bc                    ; CX = t
                rrca                            ; t/2
                add a,c
                ld l,a
                ld h,0
                ld de,#327E
                add hl,de
                ld (V_BX),hl
                call NSpriteAdd                 ; $1BCC
                jp c,.spriteFail
                ld hl,#3296
                ld (V_BX),hl                    ; MOV BX,#3296
                call CollideSetup               ; хитбокс ES:BX
                jp c,.collideFail
                call Collide85                  ; $F485: SI = #56, CF — попадание в R-9
                jr nc,.force
                ld a,1
                ld (#4000+#57),a                ; MOV BYTE [si+1],1
.force:         ld hl,#3296
                ld (V_BX),hl                    ; MOV BX,#3296
                ld hl,#76
                ld (V_SI),hl                    ; MOV SI,#76
                ld bc,(KC_X)
                ld de,(KC_XR)
                ld hl,#4000+#76+2
                call BoxX                       ; $F578: Force
                jp c,.blast
                ld a,(#4000+#2EB6)
                rra
                jp c,NRet                       ; нечётный кадр — RET
                ld l,(ix+#20)
                ld h,(ix+#21)
                ld a,h
                or l
                jr z,.probe
                dec hl
                ld (ix+#20),l
                ld (ix+#21),h                   ; DEC WORD [bp+20]
                jr .field
.probe:         call NTerrainAB                 ; $1EB5
                jp c,.terrainFail
                ld hl,(V_AX)
                ld de,-#DFC
                add hl,de
                jr nc,.blast                    ; AX < #DFC
                ld hl,(V_CX)
                ld de,-#7D0
                add hl,de
                jr nc,.blast                    ; CX < #7D0
.field:         ld a,(#4000+#2FC4)
                or a
                jr nz,.free
                call NOnField                   ; $1D6B
                jp nc,NRet
.free:          NTAIL A_078AA                   ; $74AA: удаление
.blast:         NTAIL A_078A7                   ; $74A7: JMP $E686
.spriteFail:    NTAIL A_0785D                   ; CALL $1BCC
.collideFail:   NTAIL A_07863                   ; CALL $F485
.terrainFail:   NTAIL A_0788C                   ; CALL $1EB5
.translated:    ld a,$$K_07835
                ld hl,K_07835
                jp FARJP

; ROM $0DF02 (IP $DB02) — деталь линкора этапа 3 (профиль этапа 3 — перевод ≈0,5 % тактов): слово [[bp+30]] ≠ [bp+32]
; — удаление $DB58; X += [2ED4], Y += AX = [2ED6]; DEC [bp+10] — ноль: [bp+10] = 5, [bp+12] += 2, слово ES:[[bp+12]] =
; 0 — удаление; спрайты $1BCC по описаниям BX = ES:[[bp+12]] и BX + 6 (DX = ES:[bx] между ними); [bp+20] ≠ #C —
; столкновение с R-9 $F485 по хитбоксу [bp+14] (попадание — [#57] = 1); RET. Условия (иначе перевод с входа):
; NObjCheck, [bp+30] < #3F00; отказы — переводом с места.
N_DB02:         call NObjCheck
                jp c,.translated
                ld l,(ix+#30)
                ld h,(ix+#31)
                ld (V_BX),hl                    ; MOV BX,[bp+30]
                ld a,h
                cp #3F
                jp nc,.translated
                set 6,h
                ld e,(ix+#32)
                ld d,(ix+#33)
                ld (V_AX),de                    ; MOV AX,[bp+32]
                ld a,(hl)
                cp e
                jp nz,.free
                inc hl
                ld a,(hl)
                cp d
                jp nz,.free                     ; CMP AX,[bx] — не равно: удаление
                ld hl,(#4000+#2ED4)
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (ix+4),l
                ld (ix+5),h                     ; ADD [bp+4],AX
                ld hl,(#4000+#2ED6)
                ld (V_AX),hl
                ld e,(ix+8)
                ld d,(ix+9)
                add hl,de
                ld (ix+8),l
                ld (ix+9),h                     ; ADD [bp+8],AX
                ld l,(ix+#10)
                ld h,(ix+#11)
                dec hl
                ld (ix+#10),l
                ld (ix+#11),h                   ; DEC WORD [bp+10]
                ld a,h
                or l
                jr nz,.sprites
                ld (ix+#10),5
                ld (ix+#11),0
                ld l,(ix+#12)
                ld h,(ix+#13)
                inc hl
                inc hl
                ld (ix+#12),l
                ld (ix+#13),h                   ; ADD WORD [bp+12],2
                ld (V_BX),hl
                call NWord1000                  ; ES:[bx]
                jp c,.nextFail
                ld a,d
                or e
                jp z,.free                      ; конец таблицы — удаление
.sprites:       ld l,(ix+#12)
                ld h,(ix+#13)
                ld (V_BX),hl
                call NWord1000                  ; BX = ES:[bx]
                jp c,.descFail
                ld (V_BX),de
                call NSpriteAdd                 ; $1BCC
                jp c,.sprite1Fail
                ld hl,(V_BX)
                call NWord1000
                jp c,.dxFail
                ld (V_DX),de                    ; MOV DX,ES:[bx]
                ld hl,(V_BX)
                ld de,6
                add hl,de
                ld (V_BX),hl                    ; ADD BX,6
                call NSpriteAdd                 ; $1BCC
                jp c,.sprite2Fail
                ld a,(ix+#20)
                cp #0C
                jr nz,.collide
                ld a,(ix+#21)
                or a
                jp z,NRet                       ; [bp+20] = #C — RET
.collide:       ld l,(ix+#14)
                ld h,(ix+#15)
                ld (V_BX),hl                    ; MOV BX,[bp+14]
                call CollideSetup
                jp c,.collideFail
                call Collide85                  ; $F485
                jp nc,NRet
                ld a,1
                ld (#4000+#57),a                ; MOV BYTE [si+1],1
                jp NRet
.free:          NTAIL A_0DF58                   ; $DB58: удаление
.nextFail:      NTAIL A_0DF2C                   ; TEST WORD ES:[bx]
.descFail:      NTAIL A_0DF36                   ; MOV BX,ES:[bx]
.sprite1Fail:   NTAIL A_0DF39                   ; CALL $1BCC
.dxFail:        NTAIL A_0DF3C                   ; MOV DX,ES:[bx]
.sprite2Fail:   NTAIL A_0DF42                   ; CALL $1BCC
.collideFail:   NTAIL A_0DF4E                   ; CALL $F485
.translated:    ld a,$$K_0DF02
                ld hl,K_0DF02
                jp FARJP

; --- данные ------------------------------------------------------------------------------------------------------
N_X0            DW 0                            ; сохранённый X объекта (PUSH ROM)
N_Y0            DW 0                            ; сохранённый Y объекта
N_DI            DW 0
N_X1            DW 0                            ; X и Y объекта у $2702
N_Y1            DW 0
N_LOOP          DB 0                            ; счётчик LOOP ROM (CX)
N_SUMA          DW 0                            ; быстрый путь $2AB4: суммы X-частей слоёв A и B
N_SUMB          DW 0
N_YA            DB 0                            ; добавки старшего байта адреса
N_YB            DB 0
N_KB            DB 0                            ; первый шаг со стеной слоя B (9 — нет)
N_OLD           DB 0
N_PAL           DB 0
N_DESC          DS 12                           ; описание спрайта(ов), прочитанное NDescriptor12
N_DESCP1        DW 0                            ; NSpritePair: указатели на первое и второе описание
N_DESCP2        DW 0
N_DESCP3        DW 0                            ; NSpriteTriple: третье описание
N_ATTR          DB 0                            ; NSpriteAdd: байт +5 описания
N_ATTR2         DB 0                            ; NSpritePair: байт +5 второго описания

N_DMG0          DB 0                            ; урон объекта на входе $F6DA (PUSH AX)
N_DMGV          DB 0                            ; вариант урона: 0 — $F6DA, 1 — $F75F (четвёртый скан $F525)
N_HOP           DB 0                            ; состояние врага: 0 — $89B0, 1 — $8AEE
N_B99V          DB 0                            ; состояние врага этапа 7: 0 — $B997, 1 — $B9FD
N_TY            DW 0                            ; Y цели ($1D89)
N_SECT3         DB 0

N_PARENT        DW 0                            ; $8861: адрес слова [[bp+#30]+#2A] в окне W1
N_WORM          DB 0                            ; звено червя: 0 — $7A3F, иначе $7AFA
; --- кэш столкновений (VDAC2+ 2026-09-26, шаги 2 и 3) ----------------------------------------------------------------
; В цикле списка объектов IRQ0 (враги) записи сканов — поля слотов игрока — меняются только самими сканами: флаги
; [si+1] только гаснут (0) сразу после попадания в эту же запись, прямоугольники не пишет никто; флаг R-9 [#57] только
; ставится (у $F485 это «не проверять»); владельцы лучей [#B4], [#D4] меняются в обе стороны (эталон, вся игра и
; случайный ввод: rtype_check --collide-watch). Первые три скана цепочек урона — $F485 (R-9 #56 при [#57] = 0), $F493
; (#76, #136, #156) и $F4AA (#F6, #116) — проверяют записи игрока, которые держатся у корабля; их прямоугольники в
; цикле постоянны, поэтому крайние X группы собираются один раз в начале цикла: COLL_MAXX — наибольший из X1 и X2,
; COLL_MINX — наименьший X1 (#56 — если [#57] = 0 в начале: в цикле флаг только ставится). Враг правее всех записей
; группы — все проверки этих трёх сканов промахиваются по X (оценка на эталоне по всем записям: 8…42 % цепочек, по
; группе игрока — больше; снаряды и лучи летят через весь экран, их записи оставлены сканам).

; Сборка в начале цикла списка (первый скан с кэшем): крайние X группы игрока (COLL_MAXX, COLL_MINX — записи сканов
; $F485 и $F493: #56, если [#57] = 0, #76, #136, #156) и группы $F4AA (COLL_AA: #F6, #116); признак живых записей
; снарядов $F560 (COLL_60N: 0 — в начале цикла все 24 погашены, значит, и до конца цикла: флаги только гаснут). Записи
; — по постоянным адресам окна W1, крайние X — в регистрах (BC — наибольший, DE — наименьший X1). COLL_STATE = 2.
; Сохраняет IX, IY; портит остальное.
                MACRO COLL_TAKE record
                ld hl,(#4000+record+2)
                call CollTakeX1
                ld hl,(#4000+record+4)
                call CollTakeX2
                ENDM
CollBuild:      ld bc,0                         ; наибольший X1/X2
                ld de,#FFFF                     ; наименьший X1
                COLL_TAKE #F6                   ; $F4AA
                COLL_TAKE #116
                ld (COLL_AA),bc
                ld (COLL_AA+2),de
                ld bc,0
                ld de,#FFFF
                ld a,(#4000+#57)
                or a
                jr nz,.noR9                     ; R-9 проверяется при флаге 0
                COLL_TAKE #56
.noR9:          COLL_TAKE #76                   ; $F493: Force и биты
                COLL_TAKE #136
                COLL_TAKE #156
                ld (COLL_MAXX),bc
                ld (COLL_MINX),de
                ld hl,#4000+#177                ; $F560: флаги 24 записей снарядов до первой живой
                ld de,#20
                ld b,24
.shot:          ld a,(hl)
                or a
                jr nz,.shotsDone
                add hl,de
                djnz .shot
                xor a
.shotsDone:     ld (COLL_60N),a
                ld a,2
                ld (COLL_STATE),a
                ret
; HL = X1: DE = min(DE, X1), BC = max(BC, X1). CollTakeX2 — HL = X2: BC = max(BC, X2). Портят AF.
CollTakeX1:     or a
                sbc hl,de
                add hl,de
                jr nc,CollTakeX2
                ld d,h
                ld e,l                          ; X1 < наименьшего
CollTakeX2:     or a
                sbc hl,bc
                add hl,bc
                ret c
                ld b,h
                ld c,l                          ; не меньше наибольшего
                ret

; Отказ группы записей в цикле списка: HL → группа (DW MAXX, DW MINX), BC = X, DE = XR (KC_XL — от CollideSetup).
; Объект правее всех записей группы (X ≥ MAXX и XR ≥ MAXX) — у каждой проверки ROM ($F578) ветвь «X ≥ X2», промах,
; AX = XR; левее (X < MINX и XL < MINX) — ветвь «X < X1», промах, AX = XL. Сравнения — те же беззнаковые, что у BoxX:
; точны при любых значениях. CF = 1 — отказ, HL = AX последней проверки группы; CF = 0 — проверять (вне цикла списка —
; всегда; первый вызов в цикле собирает кэш). Сохраняет BC, DE, IX, IY; портит AF, HL.
CollGroup:      ld a,(COLL_STATE)
                cp 2
                jr z,.ready
                or a
                ret z                           ; вне цикла списка: CF = 0
                push hl
                push bc
                push de
                call CollBuild
                pop de
                pop bc
                pop hl
.ready:         ld a,c
                sub (hl)
                inc hl
                ld a,b
                sbc a,(hl)
                jr c,.left                      ; X < MAXX
                dec hl
                ld a,e
                sub (hl)
                inc hl
                ld a,d
                sbc a,(hl)
                jr c,.no                        ; XR < MAXX (левее быть не может: X ≥ MAXX ≥ MINX)
                ld h,d
                ld l,e                          ; правее всех записей группы: AX = XR
                scf
                ret
.left:          inc hl                          ; → MINX
                ld a,c
                sub (hl)
                inc hl
                ld a,b
                sbc a,(hl)
                jr nc,.no                       ; X ≥ MINX
                dec hl
                ld a,(KC_XL)
                sub (hl)
                inc hl
                ld a,(KC_XL+1)
                sbc a,(hl)
                jr nc,.no                       ; XL ≥ MINX
                ld hl,(KC_XL)                   ; левее всех записей группы: AX = XL
                scf
                ret
.no:            or a
                ret

; Быстрый отказ двух сканов группы игрока ($F485, $F493) в цепочке урона: CF = 1 — все их проверки промахиваются по X,
; V_AX — как после последней ($F493, запись #156; SI ставит вызывающий); CF = 0 — проверять сканами. Вход: BC = X, DE =
; XR. Сохраняет BC, DE, IX, IY; портит AF, HL.
CollReject:     ld hl,COLL_MAXX
                call CollGroup
                ret nc
                ld (V_AX),hl
                ret                             ; CF = 1 (LD флаги не меняет)

COLL_MAXX       DW 0                            ; группа игрока ($F485, $F493): наибольший X1/X2
COLL_MINX       DW 0                            ; и наименьший X1
COLL_AA         DW 0, 0                         ; группа $F4AA (#F6, #116): MAXX, MINX
COLL_60N        DB 0                            ; $F560: ≠ 0 — в начале цикла была живая запись
                ASSERT (#56 & #FF) <= #F6 && (#76 & #FF) <= #F6 && (#136 & #FF) <= #F6 && (#156 & #FF) <= #F6
                ASSERT (#F6 & #FF) <= #F6 && (#116 & #FF) <= #F6

N_TUR           DB 0                            ; турель: 0 — $E157, 1 — $E2AA
N_FIREPAGE      DS 2                            ; страницы меток выстрела помощника турели

NATIVE_END:
                ASSERT NATIVE_END <= #10000
