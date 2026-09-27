; VDAC2+: спрайты объектами — вторая страница хоста (HOST2_PAGE; вход HOST2_OBJECT из SpriteEntry хоста через переходник
; Host2Check резидента). Решение пользователя 2026-09-25 «да» на «собирать многоклеточные спрайты в одну картинку офлайн»:
; защита строки на реальной плате уводила в проход A этап 5, где черви (по 13–14 записей 2×2 и голова 2×4) набирали
; строку FT812 вершинами ячеек — у каждой ячейки две вершины, а каждое слово списка — такт на каждой из 768 строк.
;
; Многоклеточная запись sprite RAM (2×2, 2×4, 2×1, 1×2, 1×4 ячейки 16×16) выводится одной картинкой: две вершины
; VERTEX2II — проходы A и B — вместо двух на каждую ячейку. Картинки собраны офлайн (vdac2p_objects.py) из тех же
; HQ-ячеек пака и лежат в его хвосте; каталог (ключ — палитра, код, класс формы) читается с SD при первом объекте в
; страницу OBJ_DIR_PAGE. Отражения — матрицей FT812, как у ячеек (сдвиг зеркала — ширина или высота картинки на экране).
; Отступление на аппаратном пределе строки FT812: правый столбец объекта стоит на 27 текселей правее левого, а у ячеек
; каждый столбец округляется до пикселя сам — на шве столбцов до пикселя разницы.
;
; Пул RAM_G общий с ячейками спрайтов (v30z80_video_assets.py): 256 мест по SPRITE_CELL_BYTES, объект 2×4 — 8 мест,
; 2×2 и 1×4 — 4, 2×1 и 1×2 — 2 (только в местах 0…127: ячейка VERTEX2II — 7 бит); место кратно размеру. Места объекта
; в SPRITE_OWNER помечены OBJ_OWNER и смещением его записи каталога, кадр вывода — SLOT_USED, как у ячеек (прижимает
; SpriteAge). Берётся место, выводившееся давнее всех; место, выводившееся в последних SP_KEEP кадрах, не трогается:
; FT812 может ещё показывать список два кадра назад. Вытесняются и объекты (целиком), и ячейки (OwnerRelease хоста);
; ячейке место уступает SpriteAllocS резидента (объект на нём — ObjEvictUnit). Первый вариант 25.09 — 64 ячейки и
; 96 мест объектов отдельно, защита двух кадров — не выдерживал босса этапа 4 и конца этапа 2 (объекты вытеснялись
; из-под показанного списка: «большие спрайты глючат» на плате). Загрузка: поток записи загрузчиком (LOADER_RECORD —
; секторы в кэш секторов) и CMD_INFLATE в очередь сопроцессора кусками по сектору, перед каждым — место в очереди.
;
; Ячейками, как раньше (выход CF = 0): форма не из пяти, записи нет в каталоге, последняя строка записи ниже поля
; (y + 16 ≥ 256 — такие строки ячейки не выводят, объект вывел бы их над панелью), нет места в буфере слов или в пуле,
; каталог или поток не прочитались.
;
; Процедуры и переменные страницы хоста отсюда недоступны: общее с хостом — в резиденте (VIDEO_FRAME, SPRITE_FILL,
; SPRITE_PAL, SPRITE_FLIP, SPRITE_RX, SPRITE_RY, OBJ_VALID), процедуры хоста (CmdSpace, CmdOpen, DmaToSpi, Inflate.close,
; OwnerRelease, SpriteCellAddress) — через HostCall. Окно W1 — страница состояния (запись буфера спрайтов, слова
; спрайтов кадра, SPRITE_OWNER, SLOT_USED), W2 — каталог, страница загрузчика или карта слотов (OwnerRelease).

                INCLUDE "rtype_objects.inc"

OBJ_WAIT        EQU WAIT_TRIES          ; опросов места в очереди сопроцессора (как у Inflate хоста)
OBJ_CHUNK       EQU 512+8               ; места в очереди перед куском: сектор и слово CMD_INFLATE с адресом
OBJ_ROOM        EQU 52                  ; запас буфера слов, как у ячеек: слова объекта (палитра, матрица — 4 слова, сдвиги
                                        ; X и Y, две вершины — 36 байт) и сброс матрицы в конце спрайтов (16)
                ASSERT OBJ_ENTRY == 11 && OBJ_ENTRIES == #0400 && OBJ_DIR_SECTORS == 32
                ASSERT OBJ_SECTORS_MAX*2 <= LOADER_RECORD_BYTES

; Вход HOST2_OBJECT: DE — запись в SPRITE_TEMP (окно W1: Y, код, атрибут, X — слова). Выход: CF = 1 — выведена одной
; картинкой, CF = 0 — выводить ячейками. Сохраняет IX, IY; портит остальное, окно W2.
ObjEntry:       push ix
                push iy
                call .run
                pop iy
                pop ix
                ret
.run:           ld a,(OBJ_VALID)
                or a
                jr nz,.valid
                push de
                call ObjReset                   ; видеоадаптер сброшен или машина перезапущена: пул пуст
                pop de
.valid:         ld a,(OBJ_DIR_STATE)
                cp 1
                jr z,.parse
                ret nc                          ; 2 — каталог не прочитался: ячейками
                push de
                call ObjDirLoad                 ; первый объект — каталог с SD
                pop de
                ld a,(OBJ_DIR_STATE)
                cp 1
                ret nz                          ; не прочитался (A = 2, CF = 0)
.parse:         ; запись: Y, код, палитра, старший байт атрибута, X (SPRITE_TEMP кратен 256 — запись не пересекает
                ; границу 256 байт: INC L). VDAC2+ 2026-09-25 (скорость, партия 2): класс — таблицей по атрибуту, место
                ; в буфере — одним сложением, запись каталога — кэшем OC_* (≈400 тактов разбора и поиска вместо ≈1200)
                ex de,hl
                ld e,(hl)
                inc l
                ld a,(hl)
                and 1
                ld d,a                          ; DE = Y & #1FF
                inc l
                ld c,(hl)
                inc l
                ld a,(hl)
                and #0F
                ld b,a
                ld (OBJ_CODE),bc                ; код & #FFF
                inc l
                ld a,(hl)
                and 15
                ld (OBJ_PAL),a
                inc l
                ld a,(hl)
                ld (OBJ_ATTR),a                 ; log2 ширины (биты 7, 6), высоты (5, 4), fx (3), fy (2)
                inc l
                ld c,(hl)
                inc l
                ld b,(hl)                       ; BC = X (старшие биты — ниже)
                ; класс формы — OBJ_ATTR_CLASS[атрибут] (#FF — форма не из пяти) и его запись
                ld l,a
                ld h,high OBJ_ATTR_CLASS
                ld a,(hl)
                cp 5
                ret nc                          ; форма не из пяти: ячейками (CF = 0)
                ld (OBJ_CLASS),a
                add a,a
                add a,a
                add a,a
                add a,a
                add a,low OBJ_CLASSES
                ld l,a
                ld h,high OBJ_CLASSES
                push hl
                pop ix                          ; IX — запись класса
                ; X: таблицы по X − 256 (у видимой записи X — 273…703)
                ld a,b
                and 3
                dec a
                cp 2
                ret nc                          ; X вне 256…767 — у видимой записи не бывает
                add a,high OBJ_XT_RX
                ld h,a
                ld l,c
                ld (OBJ_XT),hl
                ; Y: i + 64 = (464 − 16·высота) − Y (i = y + 16 первой строки); последняя строка — выше края поля
                ld l,(ix+6)
                ld h,(ix+7)
                or a
                sbc hl,de
                ld (OBJ_YI),hl
                ld e,(ix+8)
                ld d,(ix+9)
                or a
                sbc hl,de
                ret nc                          ; строки ниже поля ячейки не выводят, объект вывел бы: ячейками
                ; место в буфере слов (иначе — ячейками: они сочтут переполнение): SPRITE_FILL + OBJ_ROOM ≤ конца
                ld hl,(SPRITE_FILL)
                ld de,-(#4000+SPRITE_WORDS_END+1-OBJ_ROOM)
                add hl,de
                ccf
                ret nc                          ; перенос — места нет: CF = 0
                ; каталог: запись ключа — кэш OC_* по младшему байту кода (тег — #80 | класс << 4 | старшие биты
                ; кода, палитра); промах — ObjFind, итог (и «нет в каталоге») — в кэш: каталог не меняется
                ld a,OBJ_DIR_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,(OBJ_CLASS)
                add a,a
                add a,a
                add a,a
                add a,a
                ld hl,OBJ_CODE+1
                or (hl)
                or #80
                ld c,a                          ; C — тег ключа
                ld hl,(OBJ_CODE)
                ld h,high OC_TAG                ; HL → OC_TAG[код & #FF]
                ld a,(hl)
                cp c
                jr nz,.findMiss
                inc h
                ld a,(OBJ_PAL)
                cp (hl)
                jr nz,.findMiss
                inc h
                ld e,(hl)
                inc h
                ld d,(hl)
                ld a,d
                or a
                ret z                           ; нет в каталоге (запомнено): ячейками, CF = 0
                ex de,hl                        ; HL → запись каталога
                jr .found
.findMiss:      push bc
                call ObjFind                    ; HL — запись; CF = 1 — нет
                pop bc
                push af
                ex de,hl
                jr nc,.store
                ld de,0                         ; нет в каталоге
.store:         ld hl,(OBJ_CODE)
                ld h,high OC_TAG
                ld (hl),c
                inc h
                ld a,(OBJ_PAL)
                ld (hl),a
                inc h
                ld (hl),e
                inc h
                ld (hl),d
                pop af
                ccf
                ret nc                          ; нет в каталоге: ячейками (CF = 0)
                ex de,hl                        ; HL → запись каталога
.found:         ld (OBJ_ENTRY_AT),hl
                ld de,7
                add hl,de
                ld a,(hl)
                and #80
                ld c,a                          ; проход A — бит 7
                inc hl
                inc hl
                ld a,(hl)
                and #80
                rrca
                or c
                ld (OBJ_PASSES),a               ; бит 7 — проход A, бит 6 — проход B
                inc hl
                ld a,(hl)                       ; первая четверть в пуле; #FF — не загружен
                inc a
                jr nz,.loaded
                call ObjLoad                    ; место в пуле, поток с SD → A — первая четверть; CF = 1 — не вышло
                jr nc,.touch
                or a
                ret                             ; ячейками
.loaded:        dec a
.touch:         ld (OBJ_FIRST),a
                ld l,a
                ld h,high (#4000+SLOT_USED)
                ld b,(ix+14)                    ; мест объекта
                ld a,(VIDEO_FRAME)
.stamp:         ld (hl),a                       ; выводится в этом кадре — все его места
                inc l
                djnz .stamp
                ld a,(OBJ_FIRST)                ; байт 0 вершины A: ячейка handle (место >> сдвиг класса) и бит handle
                ld b,(ix+2)
                inc b
                jr .cellShift
.cellHalf:      srl a
.cellShift:     djnz .cellHalf
                or (ix+1)
                ld (OBJ_CELL0),a
                ; слова: палитра, матрица, сдвиги X и Y — если состояние буфера другое; вершины проходов
                ld de,(SPRITE_FILL)
                ld a,(OBJ_PAL)
                ld hl,SPRITE_PAL
                cp (hl)
                jr z,.matrix
                ld (hl),a
                add a,a
                ex de,hl
                ld (hl),0                       ; PALETTE_SOURCE палитра·512 (слова кратны 4: три шага без переноса)
                inc l
                ld (hl),a
                inc l
                ld (hl),0
                inc l
                ld (hl),#2A
                inc hl
                ex de,hl
.matrix:        call ObjMatrix
                ld hl,(OBJ_XT)                  ; область X
                ld a,(SPRITE_RX)
                cp (hl)
                jr z,.windowY
                ld a,(hl)
                ld (SPRITE_RX),a
                ex de,hl
                ld (hl),0                       ; VERTEX_TRANSLATE_X область·8192 (1/16 пикселя)
                inc l
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; #FF/0/1 → #E0/0/#20: знак области — в бите 7
                ld (hl),a
                inc l
                rlca
                and 1
                ld (hl),a                       ; бит 16 — знак
                inc l
                ld (hl),#2B
                inc hl
                ex de,hl
.windowY:       ld hl,(OBJ_YI)
                ld a,h
                add a,high OBJ_YT_W
                ld h,a                          ; HL → OBJ_YT_W[i + 64]
                ld a,(SPRITE_RY)
                and (hl)
                jr nz,.vertex                   ; объект входит в текущее окно Y
                ld a,(hl)                       ; окно: верхнее, если входит, иначе нижнее, иначе выше поля
                ex de,hl
                ld (hl),0
                inc l
                rrca
                jr nc,.notUpper
                ld (hl),#FD                     ; −48 пикселей = #1FD00: вершина 3i
                inc l
                ld (hl),1
                ld a,1
                jr .translateY
.notUpper:      rrca
                jr nc,.aboveField
                ld (hl),#0D                     ; 208 пикселей = #00D00: вершина 3i − 256
                inc l
                ld (hl),0
                ld a,2
                jr .translateY
.aboveField:    ld (hl),#ED                     ; −304 пикселя = #1ED00: вершина 3i + 256 (объект выше поля)
                inc l
                ld (hl),1
                ld a,4
.translateY:    inc l
                ld (hl),#2C
                inc hl
                ex de,hl
                ld (SPRITE_RY),a
.vertex:        inc h
                inc h                           ; OBJ_YT_L
                ld a,(hl)
                or (ix+0)
                ld c,a                          ; C — байт 1: (y & 15) << 4 | handle >> 1
                inc h
                inc h                           ; OBJ_YT_H4: y >> 4 в окне выше поля
                ld b,(hl)
                ld a,(SPRITE_RY)
                cp 4
                jr z,.yHigh
                ld a,b
                sub 16                          ; верхнее окно: вершина на 256 выше
                ld b,a
                ld a,(SPRITE_RY)
                cp 2
                jr nz,.yHigh
                ld a,b
                sub 16                          ; нижнее — ещё на 256
                ld b,a
.yHigh:         ld hl,(OBJ_XT)
                inc h
                inc h                           ; OBJ_XT_B2
                ld a,(hl)
                or b
                ld b,a                          ; B — байт 2: y >> 4 | (x & 7) << 5
                inc h
                inc h                           ; OBJ_XT_B3
                ld a,(hl)
                ex af,af'                       ; A' — байт 3: #80 | x >> 3
                ld a,(OBJ_CELL0)                ; байт 0 вершины A: бит handle и ячейка
                ex de,hl                        ; HL — буфер
                ld e,a
                ex af,af'
                ld d,a                          ; D — байт 3
                ld a,(OBJ_PASSES)
                rla
                jr nc,.passB
                ld (hl),e
                inc l
                ld (hl),c
                inc l
                ld (hl),b
                inc l
                ld (hl),d
                inc hl
.passB:         rla
                jr nc,.done
                inc e                           ; проход B — следующая ячейка handle
                ld (hl),e
                inc l
                ld (hl),c
                inc l
                ld (hl),b
                inc l
                ld (hl),d
                inc hl
.done:          ld (SPRITE_FILL),hl
                scf
                ret

; Матрица объекта. Состояние SPRITE_FLIP: X-часть (fx: запись класса +4 — 1 у ширины 1, зеркало то же, что у ячейки;
; 3 у ширины 2) и Y-часть (fy: +5 — 4 у высоты 1, как у ячейки; #0C | log2 высоты << 5); без отражения — 0, как у
; неотражённой ячейки. У изменившейся части — слова A и C (X) или E и F (Y); сдвиг — если зеркало было или стало (как
; SpriteTransform хоста; тот по битам 1 и 3 отличает объект и ставит матрицу ячейки заново). DE — буфер (на выходе —
; после слов). Портит AF, BC, HL.
ObjMatrix:      ld a,(OBJ_ATTR)
                ld c,0
                bit 3,a
                jr z,.noFx
                ld c,(ix+4)
.noFx:          bit 2,a
                ld a,c
                jr z,.noFy
                or (ix+5)
.noFy:          ld hl,SPRITE_FLIP
                cp (hl)
                ret z
                ld c,(hl)                       ; C — прежнее состояние
                ld (hl),a
                ld b,a                          ; B — новое
                ex de,hl                        ; HL — буфер
                xor c
                and #13
                jr z,.axisY
                bit 0,b                         ; BITMAP_TRANSFORM_A: 160 или −160 (#1FF60)
                ld a,#A0
                ld d,0
                ld e,0
                jr z,.scaleX
                ld a,#60
                ld d,#FF
                ld e,1
.scaleX:        ld (hl),a
                inc l
                ld (hl),d
                inc l
                ld (hl),e
                inc l
                ld (hl),#15
                inc hl
                ld a,b
                or c
                and 1
                jr z,.axisY                     ; ни прежнее, ни новое не зеркало — сдвиг 0 у обоих
                ld de,0
                bit 0,b
                jr z,.shiftX
                ld e,(ix+10)
                ld d,(ix+11)                    ; BITMAP_TRANSFORM_C: ширина картинки на экране·160
.shiftX:        ld (hl),e
                inc l
                ld (hl),d
                inc l
                ld (hl),0
                inc l
                ld (hl),#17
                inc hl
.axisY:         ld a,b
                xor c
                and #6C
                jr z,.done
                bit 2,b                         ; BITMAP_TRANSFORM_E: 160 или −160
                ld a,#A0
                ld d,0
                ld e,0
                jr z,.scaleY
                ld a,#60
                ld d,#FF
                ld e,1
.scaleY:        ld (hl),a
                inc l
                ld (hl),d
                inc l
                ld (hl),e
                inc l
                ld (hl),#19
                inc hl
                ld a,b
                or c
                and 4
                jr z,.done
                ld de,0
                bit 2,b
                jr z,.shiftY
                ld e,(ix+12)
                ld d,(ix+13)                    ; BITMAP_TRANSFORM_F: 30·высота·256 − 1
.shiftY:        ld (hl),e
                inc l
                ld (hl),d
                inc l
                ld (hl),0
                inc l
                ld (hl),#1A
                inc hl
.done:          ex de,hl
                ret

; Запись каталога ключа OBJ_CODE, OBJ_PAL, OBJ_CLASS (окно W2 — каталог; IX — запись класса) → HL. Корзина — 9 бит, как
; у vdac2p_objects.py: биты 0…7 — (код >> 1) & #FF ^ палитра·17 ^ примесь класса, бит 8 — бит 9 кода ^ бит 0 кода ^
; класс; в цепочке корзины частые объекты первыми. CF = 1 — нет. Портит AF, BC, DE.
ObjFind:        ld hl,(OBJ_CODE)
                ld a,h
                rra
                ld a,l
                rra
                ld e,a                          ; (код >> 1) & #FF
                ld a,(OBJ_PAL)
                ld c,a
                add a,a
                add a,a
                add a,a
                add a,a
                or c                            ; палитра·17
                xor e
                xor (ix+3)
                ld e,a                          ; биты 0…7 корзины
                ld a,h
                rrca                            ; бит 9 кода — в бит 0
                xor l
                ld d,a
                ld a,(OBJ_CLASS)
                xor d
                and 1                           ; бит 8 корзины
                sla e
                rla
                add a,#80
                ld d,a                          ; DE → слово корзины (окно W2): #8000 + корзина·2
                ex de,hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — смещение первой записи; 0 — пусто
                ld a,(OBJ_CLASS)                ; ключ: +0 — младший байт кода, +1 — старшие биты | класс << 4
                add a,a
                add a,a
                add a,a
                add a,a
                ld hl,OBJ_CODE+1
                or (hl)
                ld b,a
                ld a,(OBJ_CODE)
                ld c,a
.entry:         ld a,d
                or e
                scf
                ret z                           ; конец цепочки: нет
                ld a,d
                or #80
                ld h,a
                ld l,e                          ; HL → запись в окне W2
                ld a,(hl)
                cp c
                jr nz,.next0
                inc hl
                ld a,(hl)
                cp b
                jr nz,.next1
                inc hl
                ld a,(OBJ_PAL)
                cp (hl)
                jr nz,.next2
                dec hl
                dec hl                          ; HL — начало записи
                or a
                ret
.next0:         inc hl
.next1:         inc hl
.next2:         inc hl                          ; +3 — следующая в корзине
                ld e,(hl)
                inc hl
                ld d,(hl)
                jr .entry

; Объект записи OBJ_ENTRY_AT (окно W2 — каталог; IX — запись класса) — в пул: место (ObjPlace, давние объекты
; вытесняются), поток с SD (LOADER_RECORD), CMD_INFLATE в RAM_G места. Выход: A — первая четверть; CF = 1 — не вышло
; (места нет или SD не прочиталась; объект остаётся «не загружен»). Сохраняет IX; портит остальное, окно W2.
ObjLoad:        ld hl,(OBJ_ENTRY_AT)            ; поток: +5 сектор, +7 смещение / 4 (биты 0…6), +8 длина / 4 (0…13)
                ld de,5
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (OBJ_SECTOR),de
                inc hl
                ld a,(hl)
                and #7F
                ld e,a
                ld d,0
                ex de,hl
                add hl,hl
                add hl,hl
                ld (OBJ_WITHIN),hl
                ex de,hl
                inc hl
                ld e,(hl)
                inc hl
                ld a,(hl)
                and #3F
                ld d,a
                ex de,hl
                add hl,hl
                add hl,hl
                ld (OBJ_BYTES),hl
                call ObjPlace                   ; A — первая четверть места; CF = 1 — места нет
                ret c
                ld (OBJ_FIRST),a
                call ObjLoaderMap
                ld hl,(OBJ_SECTOR)
                ld de,(OBJ_WITHIN)
                ld bc,(OBJ_BYTES)
                push ix
                call LOADER_RECORD              ; секторы потока — в слоты кэша, куски — LOADER_PIECES
                pop ix                          ; загрузчик портит IX (ExtentAddress)
                ld a,HOST_W3_PAGE
                ld (LOADER_HOST_W3),a
                ret c                           ; SD не прочиталась: место свободно, объект — ячейками
                ld hl,LOADER_PIECES
                ld de,OBJ_PIECES
                ld bc,LOADER_RECORD_BYTES
                ldir
                ld a,OBJ_DIR_PAGE
                ld bc,PORT_PAGE2
                out (c),a                       ; W2 — каталог
                ld hl,(OBJ_ENTRY_AT)
                ld de,10
                add hl,de
                ld a,(OBJ_FIRST)
                ld (hl),a                       ; загружен: первое место
                ld hl,(OBJ_ENTRY_AT)
                res 7,h
                ld (OBJ_OWNER_AT),hl            ; смещение записи в каталоге — владелец мест
                ld c,a
                ld b,(ix+14)                    ; мест объекта
.owner:         call ObjOwnerAt                 ; HL → владелец места C
                ld (hl),OBJ_OWNER
                inc hl
                ld de,(OBJ_OWNER_AT)
                ld (hl),e
                inc hl
                ld (hl),d
                inc c
                djnz .owner
                push ix
                ld a,(OBJ_FIRST)                ; адрес RAM_G места — как у ячейки (SpriteCellAddress хоста)
                ld l,a
                ld h,0
                ld ix,SpriteCellAddress
                call HostCall                   ; A:DE — адрес
                ld (OBJ_INFLATE+4),de
                ld (OBJ_INFLATE+6),a
                call ObjInflate
                pop ix
                ld a,(OBJ_FIRST)
                or a                            ; CF = 0
                ret

; C — место пула → HL — его владелец в SPRITE_OWNER (окно W1, 3 байта). Портит DE.
ObjOwnerAt:     ld l,c
                ld h,0
                ld e,l
                ld d,h
                add hl,hl
                add hl,de
                ld de,#4000+SPRITE_OWNER
                add hl,de
                ret

; W2 — страница загрузчика; загрузчик вернёт окна W1 — страницу состояния, W3 — эту страницу (LOADER_HOST_W3 после
; вызова — снова страница хоста). Портит AF, BC.
ObjLoaderMap:   ld a,LOADER_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,VIDEO_STATE_PAGE
                ld (LOADER_HOST_W1),a
                ld a,HOST2_PAGE
                ld (LOADER_HOST_W3),a
                ret

; Место в пуле для класса IX: кандидаты — места с шагом в размер объекта (+14 мест: 2, 4 или 8), +15 кандидатов (у
; объектов в два места — только места 0…127), обход по кругу от руки OP_HAND. Возраст кандидата — наименьший из
; возрастов его мест (VIDEO_FRAME − SLOT_USED; у свободного места — возраст его последнего вывода: SpriteAge прижимает
; и свободные); место, выводившееся в последних SP_KEEP кадрах, не годится. Кандидат, все места которого давние
; (возраст не меньше SP_OLD), — сразу; иначе — с наибольшим возрастом (первый из равных). Занятые места освобождаются:
; объект — целиком (ObjEvictAt), ячейка — OwnerRelease хоста («не загружена»).
; VDAC2+ (2026-09-25, скорость, партия 2): обход с порогом D = возраст лучшего кандидата + 1 (сначала SP_KEEP). Место
; моложе порога сразу снимает кандидата: его наименьший возраст не больше лучшего, а замена — только на строго
; больший (первый из равных остаётся). Выбор тот же, что у полного обхода, но в пуле, занятом выводимым, кандидат
; обычно снимается первым же местом: ≈55 тактов вместо ≈390 (этап 2: 0,5 размещения на шаг, из 897 загрузок 768 —
; повторные, размещение ≈19 тыс. тактов — 2,5 % времени). Кандидаты развёрнуты по классам: 2, 4 и 8 мест. До
; 2026-09-25 (v014) у каждого места читался и владелец (ObjOwnerAt), а обход шёл по всем кандидатам с места 0.
; Выход: A — первое место; CF = 1 — места нет. Портит всё, кроме IX; окно W2.
ObjPlace:       ld a,(ix+14)
                ld c,a                          ; C — мест объекта
                neg
                ld hl,OP_HAND
                and (hl)                        ; рука, выровненная по размеру объекта
                ld l,a
                ld h,high (#4000+SLOT_USED)
                ld b,(ix+15)                    ; B — кандидатов
                ld a,(VIDEO_FRAME)
                ld e,a                          ; E — кадр вывода
                ld d,SP_KEEP                    ; D — порог: возраст лучшего кандидата + 1
                ld a,c
                cp 4
                jp z,.c4
                jp nc,.c8
                res 7,l                         ; объект в два места — только места 0…127
.c2:            ld a,e
                sub (hl)                        ; возраст места 0
                cp d
                jp c,.s2a                   ; моложе порога — не лучше лучшего
                ld c,a                          ; C — наименьший возраст мест кандидата
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s2b
                cp c
                jr nc,.m2b
                ld c,a
.m2b:
                ld a,c
                cp SP_OLD
                jr nc,.take1                    ; все места давние — сразу (L — место 1)
                inc a
                ld d,a                          ; новый лучший: порог — его возраст + 1
                ld a,l
                dec a
                ld (OP_BEST),a
                jr .s2b
.s2a:           inc l
.s2b:           inc l
                res 7,l                         ; по кругу мест 0…127
                djnz .c2
                jp .end
.take1:         ld a,l
                dec a
                jp .take
.c4:            ld a,e
                sub (hl)                        ; возраст места 0
                cp d
                jp c,.s4a                   ; моложе порога — не лучше лучшего
                ld c,a                          ; C — наименьший возраст мест кандидата
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s4b
                cp c
                jr nc,.m4b
                ld c,a
.m4b:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s4c
                cp c
                jr nc,.m4c
                ld c,a
.m4c:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s4d
                cp c
                jr nc,.m4d
                ld c,a
.m4d:
                ld a,c
                cp SP_OLD
                jr nc,.take3                    ; L — место 3
                inc a
                ld d,a
                ld a,l
                sub 3
                ld (OP_BEST),a
                jr .s4d
.s4a:           inc l
.s4b:           inc l
.s4c:           inc l
.s4d:           inc l                           ; следующий кандидат (по кругу мест 0…255)
                djnz .c4
                jr .end
.take3:         ld a,l
                sub 3
                jr .take
.c8:            ld a,e
                sub (hl)                        ; возраст места 0
                cp d
                jp c,.s8a                   ; моложе порога — не лучше лучшего
                ld c,a                          ; C — наименьший возраст мест кандидата
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8b
                cp c
                jr nc,.m8b
                ld c,a
.m8b:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8c
                cp c
                jr nc,.m8c
                ld c,a
.m8c:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8d
                cp c
                jr nc,.m8d
                ld c,a
.m8d:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8e
                cp c
                jr nc,.m8e
                ld c,a
.m8e:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8f
                cp c
                jr nc,.m8f
                ld c,a
.m8f:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8g
                cp c
                jr nc,.m8g
                ld c,a
.m8g:
                inc l
                ld a,e
                sub (hl)
                cp d
                jp c,.s8h
                cp c
                jr nc,.m8h
                ld c,a
.m8h:
                ld a,c
                cp SP_OLD
                jr nc,.take7                    ; L — место 7
                inc a
                ld d,a
                ld a,l
                sub 7
                ld (OP_BEST),a
                jr .s8h
.s8a:           inc l
.s8b:           inc l
.s8c:           inc l
.s8d:           inc l
.s8e:           inc l
.s8f:           inc l
.s8g:           inc l
.s8h:           inc l
                djnz .c8
                jr .end
.take7:         ld a,l
                sub 7
                jr .take
.end:           ld a,d
                cp SP_KEEP
                scf
                ret z                           ; порог не поднялся: всё занято выводимым
                ld a,(OP_BEST)
.take:          ld (OP_P),a
                ld c,a
                add a,(ix+14)
                ld (OP_HAND),a                  ; рука — за взятым
                ld b,(ix+14)
.evict:         push bc
                call ObjOwnerAt                 ; HL → владелец места C
                ld a,(hl)
                cp FREE_OWNER
                jr z,.evicted
                cp OBJ_OWNER
                jr nz,.cellOwner
                call ObjEvictAt                 ; объект — вон целиком
                jr .evicted
.cellOwner:     ld b,high SPRITE_SLOT0          ; BC — слот ячейки: SPRITE_SLOT0 + место
                push ix
                ld ix,OwnerRelease
                call HostCall                   ; ячейка — «не загружена» (окно W2 — карта слотов)
                pop ix
.evicted:       pop bc
                inc c
                djnz .evict
                ld a,(OP_P)
                or a                            ; CF = 0
                ret
                ASSERT low SPRITE_SLOT0 == 0 && SPRITE_CELLS == 256

; Вход HOST2_EVICT (SpriteAllocS резидента берёт место DE под ячейку): объект на этом месте — вон целиком. Портит всё,
; окно W2.
ObjEvictUnit:   ld c,e
                call ObjOwnerAt
                ld a,(hl)
                cp OBJ_OWNER
                ret nz
; HL → владелец места объекта (OBJ_OWNER, смещение записи каталога): запись каталога +10 = #FF («не загружен»), все
; места объекта свободны. Портит всё, окно W2 — каталог.
ObjEvictAt:     inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — смещение записи каталога
                ld a,OBJ_DIR_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,d
                or #80
                ld h,a
                ld l,e                          ; HL → запись (окно W2)
                inc hl
                ld a,(hl)                       ; +1: старшие биты кода | класс << 4
                rrca
                rrca
                rrca
                rrca
                and 7
                ld e,a
                ld d,0
                push hl
                ld hl,OBJ_CLASS_UNITS
                add hl,de
                ld b,(hl)                       ; B — мест объекта
                pop hl
                ld de,9
                add hl,de                       ; +10 — первое место
                ld c,(hl)
                ld (hl),#FF                     ; не загружен
.unit:          call ObjOwnerAt
                ld (hl),FREE_OWNER
                inc c
                djnz .unit
                ret

; CMD_INFLATE потока OBJ_PIECES (первый кусок — со смещения OBJ_WITHIN в секторе, всего OBJ_BYTES байт) в RAM_G по
; адресу из слова OBJ_INFLATE. Очередь пишется кусками: слово команды с адресом, затем секторы (по REG_CMDB_WRITE, запись
; закрывается после куска — сопроцессор разбирает очередь, пока пишется следующий); перед куском — место OBJ_CHUNK в
; очереди. Смещение и длина потока кратны 4 — кусок DMA передаёт словами. В конце — Inflate.close хоста:
; VIDEO_UPLOADED (кадр дождётся исполнения загрузок) и счёт загрузок. Портит всё, IX.
ObjInflate:     ld hl,OBJ_PIECES
                ld (OBJ_PIECE),hl
                ld hl,(OBJ_BYTES)
                ld (OBJ_LEFT),hl
                ld hl,(OBJ_WITHIN)
                ld (OBJ_START),hl               ; начало куска в секторе (у следующих — 0)
                ld a,1
                ld (OBJ_HEAD),a
.piece:         call ObjSpace
                ld ix,CmdOpen
                call HostCall                   ; запись в REG_CMDB_WRITE открыта
                ld a,(OBJ_HEAD)
                or a
                jr z,.data
                xor a
                ld (OBJ_HEAD),a
                ld hl,OBJ_INFLATE               ; CMD_INFLATE и адрес RAM_G
                ld bc,8*256+SPI_DATA
                otir
.data:          ld hl,(OBJ_PIECE)
                ld a,(hl)
                ld (OBJ_PAGE),a                 ; страница слота кэша
                inc hl
                ld b,(hl)                       ; старший байт смещения слота в странице
                inc hl
                ld (OBJ_PIECE),hl
                ld de,(OBJ_START)
                ld hl,512
                or a
                sbc hl,de                       ; HL — байт до конца сектора
                ld a,d
                add a,b
                ld d,a                          ; DE — смещение куска в странице
                push de
                ex de,hl                        ; DE — байт до конца сектора
                ld hl,(OBJ_LEFT)
                or a
                sbc hl,de
                jr nc,.fits
                add hl,de
                ex de,hl                        ; DE — остаток целиком (последний кусок)
                ld hl,0
.fits:          ld (OBJ_LEFT),hl
                ld b,d
                ld c,e                          ; BC — байт куска
                pop hl                          ; HL — смещение куска
                ld a,(OBJ_PAGE)
                ld ix,DmaToSpi
                call HostCall                   ; кусок — DMA из слота кэша в очередь
                ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ld hl,0
                ld (OBJ_START),hl
                ld hl,(OBJ_LEFT)
                ld a,h
                or l
                jr nz,.piece
                ld ix,Inflate.close
                jp HostCall

; Место в очереди сопроцессора не меньше OBJ_CHUNK (CmdSpace хоста — со сбросом сопроцессора при сбое), не дольше
; OBJ_WAIT опросов: сбой FT812 не должен останавливать игру (как у Inflate хоста — дальше пишется как есть). Портит
; всё, IX.
ObjSpace:       ld hl,OBJ_WAIT
                ld (OBJ_TRIES),hl
.poll:          ld ix,CmdSpace
                call HostCall                   ; HL — место в очереди
                ld de,OBJ_CHUNK
                or a
                sbc hl,de
                ret nc
                ld hl,(OBJ_TRIES)
                dec hl
                ld (OBJ_TRIES),hl
                ld a,h
                or l
                jr nz,.poll
                ret

; Каталог объектов с SD (LOADER_READ_DMA: OBJ_DIR_SECTORS секторов в страницу OBJ_DIR_PAGE) → OBJ_DIR_STATE: 1 —
; прочитан, 2 — нет (объекты — ячейками до перезапуска). Портит всё, окно W2.
ObjDirLoad:     call ObjLoaderMap
                ld hl,OBJ_DIR_SECTOR
                ld bc,OBJ_DIR_SECTORS
                ld a,OBJ_DIR_PAGE
                call LOADER_READ_DMA
                ld a,HOST_W3_PAGE
                ld (LOADER_HOST_W3),a
                ld a,1
                jr z,.state
                inc a
.state:         ld (OBJ_DIR_STATE),a
                ret

; Пул недействителен (OBJ_VALID = 0: сброс видеоадаптера или перезапуск машины): места объектов свободны (после
; VideoInit их уже освободил OwnersRelease хоста), у всех записей каталога — «не загружен»; OBJ_VALID = 1. Портит всё,
; окно W2.
ObjReset:       ld a,1
                ld (OBJ_VALID),a
                ld hl,#4000+SPRITE_OWNER
                ld de,3
                ld b,0                          ; 256 мест
.unit:          ld a,(hl)
                cp OBJ_OWNER
                jr nz,.next
                ld (hl),FREE_OWNER
.next:          add hl,de
                djnz .unit
                ld a,(OBJ_DIR_STATE)
                cp 1
                ret nz                          ; каталога нет — и отметок в нём нет
                ld a,OBJ_DIR_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld hl,#8000+OBJ_ENTRIES+10
                ld de,OBJ_ENTRY
                ld bc,OBJ_COUNT
.entry:         ld (hl),#FF
                add hl,de
                dec bc
                ld a,b
                or c
                jr nz,.entry
                ret

; Класс по форме: индекс — старший байт атрибута >> 4 (log2 ширины·4 + log2 высоты); #FF — не объект.
OBJ_SHAPE_CLASS:
                DB #FF, 3, 4, #FF               ; ширина 1: 1×1, 1×2, 1×4, 1×8
                DB 2, 0, 1, #FF                 ; ширина 2: 2×1, 2×2, 2×4, 2×8
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF

; Запись класса (16 байт; класс — как в каталоге vdac2p_objects.py): +0 handle >> 1, +1 (handle & 1) << 7, +2 сдвиг
; «место → ячейка handle» (ячейка handle — проход объекта: 1, 2 или 4 места), +3 примесь класса в хеше корзины
; (CLASS_MIX), +4 X-часть состояния матрицы у fx, +5 Y-часть у fy, +6 464 − 16·высота (i + 64 = это − Y), +8 336 −
; 16·высота (предел i + 64: последняя строка y + 16 < 256), +10 сдвиг зеркала X (ширина картинки на экране·160: 86
; пикселей у ширины 2, 43 — как у ячейки), +12 сдвиг зеркала Y (30·высота·256 − 1), +14 мест объекта (2 << сдвиг), +15
; кандидатов в пуле.
                MACRO OBJ_CLASS_RECORD handle, shift, mix, x_part, y_part, rows, x_shift, candidates
                DB handle >> 1, (handle & 1) << 7, shift, mix, x_part, y_part
                DW 464-16*rows, 336-16*rows, x_shift, 30*rows*256-1
                DB 2 << shift, candidates
                ENDM
OBJ_CLASSES:    OBJ_CLASS_RECORD OBJ_HANDLE0, 1, 0, 3, #2C, 2, 86*160, 64       ; 2×2: 4 места, 256 / 4
                OBJ_CLASS_RECORD OBJ_HANDLE1, 2, 80, 3, #4C, 4, 86*160, 32      ; 2×4: 8 мест
                OBJ_CLASS_RECORD OBJ_HANDLE2, 0, 160, 3, 4, 1, 86*160, 64       ; 2×1: 2 места, только 0…127
                OBJ_CLASS_RECORD OBJ_HANDLE3, 0, 240, 1, #2C, 2, 43*160, 64     ; 1×2
                OBJ_CLASS_RECORD OBJ_HANDLE4, 1, 64, 1, #4C, 4, 43*160, 64      ; 1×4
                ASSERT $-OBJ_CLASSES == 5*16 && SPRITE_CELLS == 256
OBJ_CLASS_UNITS DB 4, 8, 2, 2, 4        ; мест объекта по классу (как +14 записи класса)
                ASSERT high OBJ_CLASSES == high (OBJ_CLASSES+5*16-1)   ; IX записи класса — младшим байтом

; Класс по старшему байту атрибута (для ObjEntry — без сдвигов): OBJ_SHAPE_CLASS[атрибут >> 4], #FF — не объект.
                ALIGN 256
OBJ_ATTR_CLASS:
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #00…#0F
                DB #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03, #03           ; атрибут #10…#1F
                DB #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04, #04           ; атрибут #20…#2F
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #30…#3F
                DB #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02, #02           ; атрибут #40…#4F
                DB #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00, #00           ; атрибут #50…#5F
                DB #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01, #01           ; атрибут #60…#6F
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #70…#7F
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #80…#8F
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #90…#9F
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #A0…#AF
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #B0…#BF
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #C0…#CF
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #D0…#DF
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #E0…#EF
                DB #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF, #FF           ; атрибут #F0…#FF
; Кэш каталога по младшему байту кода (ObjEntry, 2026-09-25): тег (#80 | класс << 4 | старшие биты кода; 0 — пусто),
; палитра, запись каталога (окно W2; 0 — ключа нет в каталоге). Каталог не меняется — кэш не сбрасывается.
OC_TAG          DS 256, 0
OC_PAL          DS 256, 0
OC_LO           DS 256, 0
OC_HI           DS 256, 0
                ASSERT OC_PAL == OC_TAG+256 && OC_HI == OC_TAG+768 && low OC_TAG == 0
                ASSERT OBJ_HANDLE0 == 5 && OBJ_HANDLE1 == 4 && OBJ_HANDLE2 == 11 && OBJ_HANDLE3 == 12 && OBJ_HANDLE4 == 10

OBJ_DIR_STATE   DB 0                    ; 0 — каталог не читался, 1 — в странице OBJ_DIR_PAGE, 2 — не прочитался
OBJ_CODE        DW 0                    ; ключ записи: код & #FFF, палитра, класс
OBJ_PAL         DB 0
OBJ_CLASS       DB 0
OBJ_ATTR        DB 0                    ; старший байт атрибута записи
OBJ_XT          DW 0                    ; → OBJ_XT_RX[X − 256]
OBJ_YI          DW 0                    ; i + 64
OBJ_ENTRY_AT    DW 0                    ; запись каталога (окно W2)
OBJ_PASSES      DB 0                    ; бит 7 — проход A, бит 6 — проход B
OBJ_FIRST       DB 0                    ; первое место объекта в пуле
OBJ_CELL0       DB 0                    ; байт 0 вершины A: ячейка handle и бит handle
OBJ_OWNER_AT    DW 0                    ; смещение записи каталога — владелец мест загружаемого объекта
OBJ_SECTOR      DW 0                    ; поток объекта: первый сектор, смещение в нём, байт
OBJ_WITHIN      DW 0
OBJ_BYTES       DW 0
OBJ_LEFT        DW 0                    ; ObjInflate: байт потока осталось, начало куска в секторе, кусок, страница
OBJ_START       DW 0
OBJ_PIECE       DW 0
OBJ_PAGE        DB 0
OBJ_HEAD        DB 0                    ; 1 — слово команды ещё не в очереди
OBJ_TRIES       DW 0
OBJ_INFLATE     DB #22, #FF, #FF, #FF, 0, 0, 0, 0   ; CMD_INFLATE и адрес RAM_G (3 байта и нулевой)
OBJ_PIECES      DS LOADER_RECORD_BYTES  ; куски потока (копия LOADER_PIECES): страница и старший байт смещения слота
OP_P            DB 0                    ; ObjPlace: взятое место, лучший кандидат, рука — место, с которого
OP_BEST         DB 0                    ; начнётся следующий обход
OP_HAND         DB 0

                INCLUDE "video_objects.inc"
