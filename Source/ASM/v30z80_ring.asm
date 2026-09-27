; Кольцо дальнего слоя — фон одной картинкой (Source/Tools/rtype_ring.py, rtype_ring.inc). Решение пользователя 2026-09-16:
; фон «апскейлить из низкого разрешения — заодно эффект ГРИП» — для всех уровней.
;
; Слой 1 M72 (64×64 тайла, 512×512 текселей с переносом по скроллу) выводится из кольца 512×256 текселей
; PALETTED4444 в родном разрешении: индекс тексела — палитра·16 + перо. Таблица палитры кольца RING_LUT — цвета
; перьев таблиц банка 1 (16 + палитра) с полной альфой: у фона перо 0 непрозрачно (маски M72 BG_LAYER0,
; m72_ft812_compositor.py). Вывод — один битмап на полосу растра (RingEmit): повтор по обеим осям, фильтр NEAREST,
; масштаб 8/3 по X и 3 по Y (родной пиксель M72 → физический FT812), тексел слоя u = x + 64 + sx, v = y + 128 + sy —
; те же соотношения, что у слоёв из ячеек (ColumnsSetup, RowsSetup хоста); повтор кольца по v — через 256.
; Только NEAREST (решение пользователя 2026-09-16 после разрывов строк второго уровня на реальной плате): по таблице
; 1 FT81X Series Programmer Guide команда списка стоит такт на каждой строке, PALETTED4444 рисуется по 8 пикселей
; за такт, а с BILINEAR — по 2; кольцо с BILINEAR стоило строке 512 тактов (дороже фона из HQ-ячеек), с NEAREST — 128.
; Матрица FT812 — только 8.8 (точность 1.15 есть лишь у BT81x): A = 96 — ровно 3/8, C на 48/256 меньше — столбец
; тексела floor(3x/8), как у идеального растяжения; E = 85 вместо 85,33 — к низу экрана набегает 1 тексел, доля F
; 120/256 держит границы родных строк не дальше 1 физического пикселя от идеальных (перебор долей для выборки FT812
; по центрам пикселей) — отступление на аппаратном пределе.
;
; Высота кольца 256 (замер 2026-09-16: кольцо 512×512 оставляло пулу 33 картинки групп, а переднему слою их нужно
; до 52): строка кольца r хранит ту из строк слоя r и r + 256, что видна в окне кадра — v от w = (128 + sy) & 511
; до w + 255 (sy слоя 1 верхней полосы растра, TOP_SCROLL; у полосы после растра по замеру всей игры sy тот же —
; иначе её строки вне окна были бы старыми: отступление на аппаратном пределе). Сдвиг окна до 16 строк переписывает
; строки кольца, сменившие хозяина (RingRow), больший — всё окно (RingFull).
;
; Запись в кольцо: при изменении группы слоя 1 (StripRowRebuild хоста) — только тайлы, отличные от тени VRAM, по
; строке карты диапазоном от первого изменённого столбца до последнего, только строки текселей окна (RingWrite).
; Тексели собираются в RING_TEX рабочей страницы RING_WORK_PAGE (8 строк по 512) через её таблицы «байт родного
; тайла → старший и младший тексел с палитрой» (RingBuild) и уходят записями SPI: DMA RAM→SPI, у диапазона в один
; тайл — OTIR (RingOut). После инициализации видео окно пишется целиком, когда изображения титула в верхней части
; пула картинок уже не показаны.
;
; VDAC2+, отложенная запись (решение пользователя 2026-09-23 «размазать перестройку кольца по кадрам»): столбцы вне
; зоны видимости (RingZone — видимые 48–49 столбцов и столбец слева) RingWrite не пишет, а откладывает маской на
; группу строки карты (RingDefer); RingCatchUp дописывает их из VRAM слоя 1 по бюджету групп на кадр — не в кадре
; отложения, — а вошедшие в зону — сразу. Так полосу карты, которую эталон переписывает впрок, кольцо получает не за
; один кадр. Видимое совпадает со сборкой без отложенной записи покадрово (rtype_check.py --ring-visible).
;
; Отступления на аппаратном пределе (цена строки растра FT812): фон в родном разрешении, крупными пикселями вместо HQ-ячеек; тайлы
; фона низкого прохода приоритета не выводятся ячейками — в TILE_TEMP они заменяются маской RING_MARK (слово
; кода с битом 13), и SlotRead считает их пустыми; тайлы высокого прохода по-прежнему идут ячейками поверх
; спрайтов (и есть в кольце под ними — они непрозрачны, картинка та же).
;
; Код — в резиденте (окно W0), вызывает только хост (окно W3 — страница хоста, её переменные и подпрограммы).

RING_MARK       EQU #20                 ; бит 13 слова кода тайла (старший байт): тайл выводит кольцо
; Рабочая страница RING_WORK_PAGE: таблицы палитры p — старшие тексели с p·512, младшие с p·512 + 256; RING_TEX —
; 8 строк текселей по 512; RING_VROW — тайлы строки карты из VRAM.
RING_TEX_OFFSET EQU #2000
RING_VROW_OFFSET EQU #3000
; VDAC2+: отложенные столбцы кольца — маска на группу строки карты (строка·8 + группа, бит c — столбец 8·группа + c)
; и у строки — маска групп с отложенными (бит g — группа g; RingDefer, RingCatchUp).
RING_DEF_OFFSET EQU #3100
RING_ROWDEF_OFFSET EQU #3300
RING_CATCH      EQU 3                   ; бюджет дозаписи отложенных: групп строк карты за кадр (до 8 тайлов каждая)
RING_ZONE       EQU 50                  ; зона обязательной записи: столбцов тайлов (видимые 48–49 и запас слева)
                ASSERT RING_ROWDEF_OFFSET == RING_DEF_OFFSET+512 && low RING_DEF_OFFSET == 0
; VDAC2+: карта одноцветных родных тайлов (rtype_ring.py: все 64 пикселя одним пером) — байт код & 511, бит код >> 9;
; приходит последним сектором хвоста тайлов в начало рабочей страницы, RingInit переносит её сюда до таблиц палитры.
RING_UNI_OFFSET EQU #3400
RING_BITS_OFFSET EQU #3600              ; маски 1, 2, 4 … 128: номер страницы тайлов (код >> 9) → бит карты
                ASSERT low RING_UNI_OFFSET == 0 && low RING_BITS_OFFSET == 0 && RING_UNI_OFFSET >= RING_ROWDEF_OFFSET+64

RING_READY      DB 0                    ; 1 — кольцо записано целиком после инициализации видео (выводится)
RING_FULL       DB 0                    ; 1 — кольцо ждёт полной записи (VideoInit; пишется, когда TITLE_GUARD = 0)
RING_W          DW 0                    ; окно кольца: первая строка текселей слоя (0…511)
RING_MAPPED     DB 0                   ; страница родных тайлов в окне W2
RING_MASKS:                             ; изменённые тайлы группы: бит c — столбец c строки карты
RING_MASK0      DB 0                    ; строка карты 2k
RING_MASK1      DB 0                    ; строка карты 2k + 1
RING_M          DB 0                    ; строка карты в группе (0, 1)
RING_TSRC       DW 0                    ; диапазон записи: первая запись тайла (4 байта), её столбец, тайлов
RING_DCOL       DB 0
RING_N          DB 0
RING_T          DW 0                    ; строка текселей слоя строки 0 диапазона (0…511)
RING_C          DB 0                    ; RingBuild: столбец тайла, тайлов осталось
RING_LEFT_T     DB 0
RING_ROWS       DB 0                    ; RingOut: строк осталось; строка в рабочей странице
RING_SRC        DW 0
RING_BX         DS 3                    ; RingOut: RING_BASE + столбец текселей (младший, средний, старший байт)
RING_SSTEP      DB 2                    ; RingOut: шаг источника по строкам (старший байт: 2 — +512, 0 — та же строка)
RING_CVAL       DB 0                    ; RingConstant: значение тексела диапазона
RING_MR         DB 0                    ; RingFull: строка карты
RING_ROW        DB 0                    ; RingRow: строка кольца, строк осталось, её строка текселя тайла
RING_ROWS_LEFT  DB 0
RING_R          DB 0
RING_VROW_M     DB 0                    ; строка карты в RING_VROW (#FF — нет)
RING_STALE      DB 0                    ; отложенные столбцы: бит 0 — есть, бит 1 — откладывались в этом кадре
RING_ZC         DB 0                    ; первый столбец зоны обязательной записи (RingZone)
RING_BUDGET     DB 0                    ; остаток бюджета дозаписи кадра (групп)
RING_G          DB 0                    ; RingCatchUp: группа строки карты
RING_ALL        DB 0                    ; RingCatchUp: #FF — строка нижней полосы растра (все отложенные сразу)
RING_GMASK      DB 0                    ; RingCatchUp: группы строки, ещё не пройденные
RING_MOVED      DB 0                    ; ≠ 0 — зона сдвигалась после полного прохода дозаписи (RingZone)
RING_SCAN       DB 0                    ; RingCatchUp: ≠ 0 — полный проход (обязательная запись возможна)
RING_BAND       DW 0                    ; VIS_ROW2, VIS_ROWS2 полного прохода

; Родные тайлы из хвоста пака (RING_TILES_SECTOR) → страницы RING_TILE_PAGE0…: VDAC2+ — одним чтением загрузчика через
; DMA SPI→RAM прямо в страницы (32 сектора на страницу; прежде — куски по 32 сектора через буфер загрузчика и DmaCopy).
; Вызов из хоста сразу после открытия пака. Z — прочитано. Портит всё, окно W2.
RingTilesLoad:  call LoaderMap
                ld hl,RING_TILES_SECTOR
                ld bc,RING_TILES_SECTORS
                ld a,RING_TILE_PAGE0
                jp LOADER_READ_DMA

; Таблицы рабочей страницы (окно W2): палитра p, байт b родного тайла → с p·512 + b старший тексел (b >> 4) + p·16,
; с p·512 + 256 + b младший (b & 15) + p·16. Один раз после RingTilesLoad. Портит всё, окно W2.
RingInit:       ld a,RING_WORK_PAGE
                call Map2
                ld hl,#8000                     ; VDAC2+: карта одноцветных тайлов (последний сектор хвоста) — на место
                ld de,#8000+RING_UNI_OFFSET
                ld bc,512
                ldir
                ld hl,#8000+RING_BITS_OFFSET    ; маски бит карты по номеру страницы тайлов
                ld a,1
.bits:          ld (hl),a
                inc l
                add a,a
                jr nc,.bits
                ld hl,#8000
                ld c,0                          ; палитра·16
.palette:       ld b,0                          ; байт
.high:          ld a,b
                rrca
                rrca
                rrca
                rrca
                and 15
                add a,c
                ld (hl),a
                inc hl
                inc b
                jr nz,.high
.low:           ld a,b
                and 15
                add a,c
                ld (hl),a
                inc hl
                inc b
                jr nz,.low
                ld a,c
                add a,16
                ld c,a
                jr nz,.palette
                ld hl,#8000+RING_DEF_OFFSET     ; отложенных столбцов нет
                ld de,#8000+RING_DEF_OFFSET+1
                ld bc,512+64-1
                ld (hl),0
                ldir
                xor a
                ld (RING_STALE),a
                ret

; Перед перестройкой тайлов (HostVideoBefore, W1 — страница состояния; TOP_SCROLL — скроллы кадра). Пока показаны
; изображения титула (TITLE_GUARD), кольцо не трогается. Ждёт полной записи — таблица палитры кольца из PAL_SHADOW
; (таблицы 16…31), окно кадра и всё окно (RingFull), затем кольцо выводится. Иначе при сдвиге окна на d строк —
; строки кольца, сменившие хозяина (вниз — w_old…w_old + d − 1, вверх — w…w_old − 1 по модулю 256), до 16 строк
; по одной (RingRow), больше — всё окно. W1 на выходе — страница состояния. Портит всё, окно W2.
RingService:    ld a,(TITLE_GUARD)
                or a
                ret nz
                ld a,(RING_FULL)
                or a
                jr nz,.full
                ld a,(RING_READY)
                or a
                ret z
                call RingWindow
                ld de,(RING_W)
                ld (RING_W),hl
                or a
                sbc hl,de                       ; w − w_old
                ld a,h
                and 1
                ld h,a                          ; d = (w − w_old) & 511
                or l
                ret z                           ; окно то же
                ld a,h
                or a
                jr nz,.up
                ld a,l                          ; вниз на d (1…255): с w_old & 255
                cp 17
                jr nc,.rewrite
                ld b,a
                ld a,e
                jr .rows
.up:            ld a,l
                neg                             ; вверх на 512 − d строк
                jr z,.rewrite                   ; 256 строк
                cp 17
                jr nc,.rewrite
                ld b,a
                ld a,(RING_W)                   ; с w & 255
.rows:          ld (RING_ROW),a
                ld a,b
                ld (RING_ROWS_LEFT),a
                ld a,RING_WORK_PAGE
                call Map1
                ld a,#FF
                ld (RING_VROW_M),a
.row:           call RingRow
                ld hl,RING_ROW
                inc (hl)
                ld hl,RING_ROWS_LEFT
                dec (hl)
                jr nz,.row
                jr .done
.full:          ld a,RING_LUT >> 16
                ld de,RING_LUT & #FFFF
                call FtOpenWrite
                ld hl,PAL_SHADOW+16*32
                ld b,0                          ; 256 записей: G4·16 + B4, R4
.lut:           ld a,(hl)
                out (SPI_DATA),a
                inc hl
                ld a,(hl)
                or #F0
                out (SPI_DATA),a                ; альфа 15
                inc hl
                djnz .lut
                call FtClose
                xor a
                ld (RING_FULL),a
                call RingWindow
                ld (RING_W),hl
.rewrite:       ld a,RING_WORK_PAGE
                call Map1
                call RingFull
.done:          ld a,VIDEO_STATE_PAGE
                call Map1
                ld a,1
                ld (RING_READY),a
                ret

; Окно кадра → HL: (128 + sy слоя 1 верхней полосы) & 511. Портит AF, DE.
RingWindow:     ld hl,(TOP_SCROLL+4)
                ld de,128
                add hl,de
                ld a,h
                and 1
                ld h,a
                ret

; Всё окно RING_W: строки карты с w >> 3 (32, у окна с частью строки сверху и снизу — 33) из VRAM слоя 1 в RING_VROW,
; 64 тайла → RingBuild → RingOut (строки текселей окна). W1 — рабочая страница. Портит всё, окно W2.
RingFull:       ld hl,(RING_W)
                ld a,l
                and 7
                ld a,32
                jr z,.count
                inc a
.count:         ld (RING_ROWS_LEFT),a
                ld a,l
                rrca
                rrca
                rrca
                and #1F
                ld e,a
                ld a,h
                rrca
                rrca
                rrca                            ; бит 8 w → 32
                or e                            ; строка карты w >> 3
.mapRow:        ld (RING_MR),a
                call RingVrow
                ld hl,#4000+RING_VROW_OFFSET
                ld (RING_TSRC),hl
                xor a
                ld (RING_DCOL),a
                ld a,64
                ld (RING_N),a
                ld a,(RING_MR)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld (RING_T),hl                  ; строка текселей слоя: строка карты·8
                call RingBuild
                call RingOut
                ld a,(RING_MR)
                inc a
                and 63
                ld hl,RING_ROWS_LEFT
                dec (hl)
                jr nz,.mapRow
                ret

; Строка кольца RING_ROW из VRAM слоя 1: её хозяин — строка текселей слоя t = r или r + 256 в окне RING_W
; ((t − w) & 511 < 256), строка карты t >> 3, строка тайла t & 7; 64 тайла (RING_VROW, W1 — рабочая страница) →
; 512 текселей RING_TEX → DMA одной записью SPI по адресу RING_BASE + r·512. Портит всё, окно W2.
RingRow:        ld a,(RING_ROW)
                ld l,a
                ld h,0
                ld de,(RING_W)
                or a
                sbc hl,de
                ld a,h
                and 1                           ; 1 — (r − w) & 511 ≥ 256: хозяин r + 256
                ld h,a
                ld a,(RING_ROW)
                ld l,a                          ; HL — t
                and 7
                ld (RING_R),a
                ld a,l
                rrca
                rrca
                rrca
                and #1F
                ld e,a
                ld a,h
                rrca
                rrca
                rrca                            ; бит 8 t → 32
                or e                            ; строка карты t >> 3
                ld hl,RING_VROW_M
                cp (hl)
                jr z,.vrow
                ld (hl),a
                call RingVrow
                ld a,#FF
                ld (RING_MAPPED),a
.vrow:          ld ix,#4000+RING_VROW_OFFSET
                ld de,#4000+RING_TEX_OFFSET
                ld a,64
.tile:          ld (RING_C),a
                ld a,(ix+1)
                and #0F
                ld h,a
                ld l,(ix+0)                     ; HL — код (12 бит)
                ld a,h
                srl a
                add a,RING_TILE_PAGE0           ; страница: код >> 9
                ld b,a
                ld a,(RING_MAPPED)
                cp b
                jr z,.mapped
                ld a,b
                ld (RING_MAPPED),a
                ld bc,PORT_PAGE2
                out (c),a
.mapped:        add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; код·32
                ld a,(RING_R)
                bit 7,(ix+1)
                jr z,.noFy
                cpl
                and 7                           ; fy: строка 7 − R
.noFy:          add a,a
                add a,a
                add a,l
                ld l,a
                jr nc,.noCarry
                inc h
.noCarry:       ld a,h
                and #3F
                or #80
                ld h,a                          ; HL — 4 байта строки родного тайла
                ld a,(ix+2)
                and 15
                add a,a
                add a,#40
                ld b,a                          ; B — таблица палитры: старшие тексели
                bit 6,(ix+1)
                jr nz,.fx
                ld c,(hl)
                inc hl
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld c,(hl)
                inc hl
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld c,(hl)
                inc hl
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld c,(hl)
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld a,(bc)
                ld (de),a
                inc de
                jr .next
.fx:            inc hl                          ; fx: байты 3…0, в байте — сначала младший тексел
                inc hl
                inc hl
                inc b
                ld c,(hl)
                dec hl
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld c,(hl)
                dec hl
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld c,(hl)
                dec hl
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld a,(bc)
                ld (de),a
                inc de
                inc b
                ld c,(hl)
                ld a,(bc)
                ld (de),a
                inc de
                dec b
                ld a,(bc)
                ld (de),a
                inc de
.next:          ld bc,4
                add ix,bc
                ld a,(RING_C)
                dec a
                jp nz,.tile
                ld a,(RING_ROW)
                ld l,a
                ld h,0
                add hl,hl                       ; r·512: H — старший, L — средний байт
                ld de,RING_BASE >> 8
                add hl,de
                ld a,h
                ld d,l
                ld e,RING_BASE & 255
                call FtOpenWrite
                ld hl,RING_TEX_OFFSET
                ld bc,512
                ld a,RING_WORK_PAGE
                call DmaToSpi
                jp FtClose

; Изменённая группа TILE_GROUP строки полос TILE_ROW слоя 1 (StripRowRebuild до записи тени: TILE_TEMP — VRAM, тень —
; окно W1 с TILE_OFFSET + #4000): тайлы, отличные от тени (код, отражения, атрибут), → кольцо. Пока кольцо не готово,
; ничего не пишется (полная запись возьмёт VRAM). Окна на выходе — как у StripRowRebuild: W1 — тень слоя 1,
; W2 — VRAM1_PAGE. Портит всё.
RingGroup:      ld a,(RING_READY)
                or a
                ret z
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#40
                ld h,a
                ld de,TILE_TEMP
                call RingCompare
                ld (RING_MASK0),a
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#41
                ld h,a
                call RingCompare                ; DE — уже TILE_TEMP + 32
                ld (RING_MASK1),a
                ld hl,RING_MASK0
                or (hl)
                ret z                           ; тайлы те же (перестройка каскадом)
                call RingWrite
                ld a,VIDEO_SHADOW_PAGE0+1
                call Map1
                ld a,VRAM1_PAGE
                jp Map2

; 8 тайлов: DE — TILE_TEMP, HL — тень → A: бит c — байты 0…2 тайла c различаются. DE и HL — на 32 дальше.
; Портит F, BC.
RingCompare:    ld b,8
.tile:          ld a,(de)
                cp (hl)
                jr nz,.diff3
                inc de
                inc hl
                ld a,(de)
                cp (hl)
                jr nz,.diff2
                inc de
                inc hl
                ld a,(de)
                cp (hl)
                jr nz,.diff1
                inc de                          ; равны: CF = 0 после CP (16-битный INC признаков не меняет)
                inc hl
                inc de
                inc hl
                jr .bit
.diff3:         inc de
                inc hl
.diff2:         inc de
                inc hl
.diff1:         inc de
                inc hl
                inc de
                inc hl
                scf
.bit:           rr c                            ; после 8 сдвигов столбец 0 — бит 0
                djnz .tile
                ld a,c
                ret

; Тайлы TILE_TEMP с пометками RING_MASK0, RING_MASK1 → кольцо: у строки карты с пометками и строками текселей в окне —
; диапазон столбцов от первой пометки до последней. VDAC2+: столбцы вне зоны обязательной записи (RingZone, RingSplit)
; не пишутся сразу, а откладываются (RingDefer) — их допишет RingCatchUp до того, как они войдут в экран. Так полоса
; карты, которую эталон раз в 64 кадра переписывает впрок, не пишется в кольцо вся в один кадр (затык подгрузки).
; Портит всё, окна W1 (рабочая страница) и W2.
RingWrite:      call RingZone
                ld a,RING_WORK_PAGE
                call Map1
                xor a
.mapRow:        ld (RING_M),a
                ld e,a
                ld d,0
                ld hl,RING_MASKS
                add hl,de
                ld a,(hl)
                or a
                jr z,.next
                ld c,a
                ld a,(TILE_ROW)
                add a,a
                ld hl,RING_M
                add a,(hl)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld (RING_T),hl                  ; первая строка текселей t0 = строка карты·8
                ld de,(RING_W)
                or a
                sbc hl,de
                bit 0,h
                jr z,.inside                    ; t0 в окне
                ld de,7
                add hl,de
                bit 0,h
                jr nz,.next                     ; и t0 + 7 вне окна: строка карты не видна
.inside:        call RingSplit                  ; VDAC2+: C — столбцы писать сейчас, B — отложить
                ld a,b
                or a
                call nz,RingDefer
                ld a,c
                or a
                jr z,.next
                call RingEnds                   ; B — первый столбец, C — последний + 1
                ld a,c
                sub b
                ld (RING_N),a                   ; последний + 1 − первый
                ld c,b                          ; C — первый столбец
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                add a,c
                ld (RING_DCOL),a
                ld a,(RING_M)
                add a,a
                add a,a
                add a,a
                add a,c
                add a,a
                add a,a
                ld e,a
                ld d,0
                ld hl,TILE_TEMP
                add hl,de
                ld (RING_TSRC),hl               ; TILE_TEMP + (строка карты в группе·8 + первый)·4
                call RingBuild
                call RingOut
.next:          ld a,(RING_M)
                inc a
                cp 2
                jp c,.mapRow
                ret

; Строка карты A из VRAM слоя 1 (окно W2 — VRAM1_PAGE, #8000 + A·256) → RING_VROW рабочей страницы (окно W1): 64 тайла
; по 4 байта. Общая для RingFull, RingRow и RingCatchUp. Портит AF, BC, DE, HL.
RingVrow:       add a,#80
                ld h,a
                ld l,0
                ld a,VRAM1_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld de,#4000+RING_VROW_OFFSET
                ld bc,256
                ldir
                ret

; VDAC2+: зона обязательной записи кольца по скроллу слоя 1 верхней полосы (TOP_SCROLL + 6 — sx). Тексел строки
; экрана — u = 64 + sx + x, x = 0…383: видимые столбцы тайлов — с q = ((64 + sx) >> 3) & 63, их 48 (sx + 64 кратно 8)
; или 49; правый край — тексел 447 + sx (столбец q + 47 или q + 48) при любом правиле выборки FT812, левый при выборке
; не по центрам пикселей — 63 + sx. Зона — RING_ZONE столбцов по кругу 64 с RING_ZC = q − 1: столбец c писать сразу,
; если (c − RING_ZC) & 63 < RING_ZONE. Портит AF, DE, HL.
RingZone:       ld hl,(TOP_SCROLL+6)
                ld de,64
                add hl,de
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                ld a,l
                dec a
                and 63
                ld hl,RING_ZC
                cp (hl)
                ret z
                ld (hl),a
                ld a,1
                ld (RING_MOVED),a               ; отложенные прежде могли войти в новую зону
                ret

; Строка полос A слоя 1 — в полосе экрана после растрового разрыва (VIS_ROW2, VIS_ROWS2 — LayerWindow)? CF = 1 — да:
; у той полосы свой скролл, её столбцы не сверяются с зоной. Портит AF, HL.
RingBottom:     ld hl,VIS_ROW2
                sub (hl)
                and 31
                ld hl,VIS_ROWS2
                cp (hl)
                ret

; Маска зоны группы A (0…7) → A: бит c взведён, если столбец 8·A + c в зоне (RingZone). Зона — дуга круга 64 длиной
; RING_ZONE, группа — дуга 8: их пересечение одно и сплошное. d = (8·A − ZC) & 63 — место столбца 0 группы в круге от
; начала зоны. Портит F, B.
RingZoneMask:   add a,a
                add a,a
                add a,a
                ld b,a
                ld a,(RING_ZC)
                neg
                add a,b
                and 63
                cp RING_ZONE-7
                jr c,.all                       ; d + 7 < RING_ZONE: вся группа в зоне
                cp RING_ZONE
                jr c,.low                       ; зона кончается в группе: в ней биты c < RING_ZONE − d
                cp 64-7
                jr c,.none                      ; вся группа вне зоны
                sub 64
                ld b,a                          ; зона начинается в группе: в ней биты c ≥ 64 − d
                ld a,#FF
.high:          add a,a
                inc b
                jr nz,.high
                ret
.low:           sub RING_ZONE
                ld b,a
                xor a
.lowBit:        scf
                rla                             ; RING_ZONE − d младших битов
                inc b
                jr nz,.lowBit
                ret
.all:           ld a,#FF
                ret
.none:          xor a
                ret

; Маска C изменённых столбцов группы TILE_GROUP строки полос TILE_ROW → C — столбцы в зоне (писать сейчас; у строки
; нижней полосы растра — все), B — прочие (отложить). Портит AF, HL.
RingSplit:      ld a,(TILE_ROW)
                call RingBottom
                ld b,0
                ret c
                ld a,(TILE_GROUP)
                call RingZoneMask
                ld b,a
                and c
                ld l,a                          ; в зоне
                ld a,b
                cpl
                and c
                ld b,a                          ; вне зоны
                ld c,l
                ret

; Строка карты A, группа E → HL — маска её отложенных столбцов в RING_DEF (окно W1 — рабочая страница). Портит AF.
RingDefAt:      ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld a,l
                or e
                ld l,a
                ld a,h
                add a,(#4000+RING_DEF_OFFSET) >> 8
                ld h,a
                ret

; Маска B отложенных столбцов группы TILE_GROUP строки карты 2·TILE_ROW + RING_M → в RING_DEF, бит группы — в маску
; групп строки RING_ROWDEF (окно W1 — рабочая страница); RING_STALE = 3: есть отложенные, отложены в этом кадре.
; Сохраняет BC. Портит AF, DE, HL.
RingDefer:      ld a,(TILE_GROUP)
                ld e,a                          ; E — группа
                inc a
                ld d,a
                xor a
                scf
.bit:           rla
                dec d
                jr nz,.bit
                ld d,a                          ; D — бит группы
                ld a,(TILE_ROW)
                add a,a
                ld hl,RING_M
                add a,(hl)                      ; строка карты
                ld l,a
                ld h,(#4000+RING_ROWDEF_OFFSET) >> 8
                push af
                ld a,(hl)
                or d
                ld (hl),a
                pop af
                call RingDefAt
                ld a,(hl)
                or b
                ld (hl),a
                ld a,3
                ld (RING_STALE),a
                ret

; Маска A (≠ 0) → B — номер младшего взведённого бита, C — старшего + 1. Портит AF.
RingEnds:       ld c,a
                ld b,0
.low:           rrca
                jr c,.found
                inc b
                jr .low
.found:         ld a,c
                ld c,8
.high:          rlca
                ret c
                dec c
                jr .high

; Столбцы маски A (≠ 0) группы RING_G строки карты RING_MR → кольцо: тайлы от первого столбца маски до последнего —
; слова из VRAM слоя 1 (окно W2, #8000 + строка·256 + столбец·4) в RING_VROW (окно W1 — рабочая страница), затем
; RingBuild и RingOut. RING_T ставится здесь: RingOut сдвигает его по строкам текселей. Портит всё, окно W2.
RingPiece:      ld e,a
                ld a,(RING_MR)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld (RING_T),hl                  ; первая строка текселей строки карты
                ld a,e
                call RingEnds                   ; B — первый, C — последний + 1
                ld a,c
                sub b
                ld (RING_N),a
                add a,a
                add a,a
                ld c,a                          ; байт слов тайлов
                ld a,(RING_G)
                add a,a
                add a,a
                add a,a
                add a,b
                ld (RING_DCOL),a                ; столбец 8·группа + первый
                add a,a
                add a,a
                ld l,a
                ld e,a
                ld a,(RING_MR)
                add a,#80
                ld h,a
                ld d,(#4000+RING_VROW_OFFSET) >> 8
                ld (RING_TSRC),de
                ld b,0
                push bc
                ld a,VRAM1_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                pop bc
                ldir
                call RingBuild
                jp RingOut

; Дозапись отложенных столбцов (RING_DEF рабочей страницы) перед выводом кадра. Строка карты вне окна кольца только
; снимается (войдёт в окно — её напишут RingRow или RingFull из VRAM). Столбцы, вошедшие в зону обязательной записи, и
; все отложенные строки нижней полосы растра пишутся сразу; прочие — группой, пока хватает бюджета RING_CATCH групп на
; кадр. В кадре, где столбцы откладывались (перестройка полосы карты — и так тяжёлый кадр), бюджета нет. Обязательная
; запись возможна только после сдвига зоны (RING_MOVED) или смены нижней полосы растра: отложенные при прежних зоне и
; полосе были вне них. Тогда проход полный, иначе — до конца бюджета. Тайлы — нынешние из VRAM слоя 1 (как у RingRow).
; Пока показаны изображения титула или кольцо не готово, дозапись ждёт. Зовёт хост после TilesUpdate (W3 — страница
; хоста). W1 на выходе — страница состояния. Портит всё, окно W2.
RingCatchUp:    ld hl,RING_STALE
                ld a,(hl)
                or a
                ret z
                ld a,(TITLE_GUARD)
                or a
                ret nz
                ld a,(RING_READY)
                or a
                ret z
                ld a,(hl)
                ld (hl),1                       ; отложенные остаются, пока полный проход не покажет иного
                and 2
                ld a,RING_CATCH
                jr z,.budget
                xor a                           ; в этом кадре откладывали — только обязательное
.budget:        ld (RING_BUDGET),a
                call RingZone
                ld hl,(VIS_ROW2)                ; L — VIS_ROW2, H — VIS_ROWS2
                ld de,(RING_BAND)
                ld (RING_BAND),hl
                or a
                sbc hl,de
                ld hl,RING_MOVED
                ld a,(hl)
                ld (hl),0
                jr z,.band
                inc a                           ; нижняя полоса растра сменилась
.band:          ld (RING_SCAN),a
                ld hl,RING_BUDGET
                or (hl)
                ret z                           ; ни бюджета, ни обязательной записи
                ld a,RING_WORK_PAGE
                call Map1
                xor a
                ld (RING_STALE),a               ; снова взведут остаток строки (.rowEnd) или неполный проход (.done)
.row:           ld (RING_MR),a
                ld a,(RING_BUDGET)
                ld hl,RING_SCAN
                or (hl)
                jp z,.done                      ; бюджет кончился, обязательной записи нет
                ld a,(RING_MR)
                ld l,a
                ld h,(#4000+RING_ROWDEF_OFFSET) >> 8
                ld a,(hl)
                or a
                jp z,.next                      ; у строки отложенных нет
                ld (RING_GMASK),a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; t0 = строка карты·8
                ld de,(RING_W)
                or a
                sbc hl,de
                bit 0,h
                jr z,.inside
                ld de,7
                add hl,de
                bit 0,h
                jr nz,.clear                    ; строка вне окна кольца
.inside:        ld a,(RING_MR)
                srl a
                call RingBottom
                sbc a,a
                ld (RING_ALL),a                 ; #FF — строка нижней полосы растра: все отложенные сразу
                xor a
.group:         ld (RING_G),a
                ld hl,RING_GMASK
                srl (hl)
                jr nc,.groupNext                ; у группы отложенных нет
                ld e,a
                ld a,(RING_MR)
                call RingDefAt
                ld a,(hl)
                or a
                jr z,.groupNext                 ; маска пуста (защита: RingEnds ждёт ненулевую)
                ld c,a                          ; C — отложенные столбцы группы
                ld a,(RING_ALL)
                or a
                jr nz,.take
                ld a,e
                call RingZoneMask
                and c
                jr nz,.take                     ; вошедшие в зону — сейчас (только они)
                ld a,(RING_BUDGET)
                or a
                jr z,.groupNext                 ; бюджета кадра нет — ждать
                dec a
                ld (RING_BUDGET),a
                ld a,c                          ; вся группа
.take:          and c
                ld b,a
                cpl
                and c
                ld (hl),a                       ; остаются отложенными
                ld a,b
                call RingPiece
.groupNext:     ld a,(RING_GMASK)
                or a
                jr z,.rowMask                   ; групп с отложенными дальше нет
                ld a,(RING_G)
                inc a
                jr .group
.rowMask:       ld a,(RING_MR)                  ; маска групп строки заново: бит g — у группы остались отложенные
                ld e,0
                call RingDefAt
                ld bc,#0800
.any:           ld a,(hl)
                add a,#FF                       ; CF — байт ≠ 0
                rr c
                inc l
                djnz .any
                ld a,c
                jr .rowEnd
.clear:         ld a,(RING_MR)
                ld e,0
                call RingDefAt
                xor a
                ld b,8
.zero:          ld (hl),a
                inc l
                djnz .zero
.rowEnd:        ld e,a                          ; ≠ 0 — у строки остались отложенные
                ld a,(RING_MR)
                ld l,a
                ld h,(#4000+RING_ROWDEF_OFFSET) >> 8
                ld (hl),e
                ld a,e
                or a
                jr z,.next
                ld a,1
                ld (RING_STALE),a
.next:          ld a,(RING_MR)
                inc a
                cp 64
                jp c,.row
                jr .restore
.done:          ld a,1
                ld (RING_STALE),a               ; проход не дошёл до конца — отложенные могли остаться
.restore:       ld a,VIDEO_STATE_PAGE
                jp Map1

; RING_N тайлов с записи RING_TSRC (4 байта: код, старший байт с fy — бит 7, fx — бит 6, атрибут) → RING_TEX (окно
; W1): строка текселей R — с R·512, тайл столбца c = RING_DCOL + i — с c·8. Родной тайл — в окне W2 (страница
; RING_TILE_PAGE0 + (код >> 9), смещение (код·32) & #3FFF), 4 байта на строку, перо чётного столбца — старший
; полубайт; байт → два тексела с палитрой через таблицы W1 (B — #40 + палитра·2, C — байт). fy — приёмник со строки 7
; вверх, fx — назад; четыре цикла строк с постоянным шагом приёмника к следующей строке, счётчик строк — IXL.
; Портит всё, окно W2.
RingBuild:      ld a,#FF
                ld (RING_MAPPED),a
                ld a,(RING_N)
                cp 2
                jr c,.plain
                call RingConstant               ; VDAC2+: весь диапазон одним значением?
                ret nc                          ; да: строка 0 готова, RingOut пошлёт её во все 8 строк
.plain:         ld ix,(RING_TSRC)
                ld a,(RING_DCOL)
                ld (RING_C),a
                ld a,(RING_N)
                ld (RING_LEFT_T),a
.tile:          ld a,(RING_C)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; c·8
                ld c,(ix+1)                     ; старший байт слова: fy, fx, код
                ld a,h
                bit 7,c
                jr z,.noFy
                add a,7*2                       ; fy: со строки 7 (+ 7·512)
.noFy:          add a,(#4000+RING_TEX_OFFSET) >> 8
                ld h,a
                bit 6,c
                jr z,.noFx
                ld a,l
                add a,7
                ld l,a                          ; fx: с последнего тексела (c·8 + 7 — без переноса)
.noFx:          push hl                         ; приёмник
                ld a,c
                and #0F
                ld h,a
                ld l,(ix+0)                     ; HL — код
                ld a,h
                srl a
                add a,RING_TILE_PAGE0           ; страница: код >> 9
                ld b,a
                ld a,(RING_MAPPED)
                cp b
                jr z,.mapped
                ld a,b
                ld (RING_MAPPED),a
                ld bc,PORT_PAGE2
                out (c),a
.mapped:        ld a,h                          ; VDAC2+: одноцветный тайл? Карта RING_UNI (окно W1): байт код & 511,
                srl a                           ; бит код >> 9
                ld c,a
                ld a,h
                and 1
                add a,(#4000+RING_UNI_OFFSET) >> 8
                ld d,a
                ld e,l
                ld b,(#4000+RING_BITS_OFFSET) >> 8
                ld a,(bc)                       ; маска бита
                ex de,hl
                and (hl)
                ex de,hl
                ld c,a                          ; C ≠ 0 — одноцветный
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; код·32 (бит 16 теряется: он и есть номер страницы)
                ld a,h
                and #3F
                or #80
                ld h,a                          ; HL — родной тайл
                ld a,(ix+2)
                and 15
                add a,a
                add a,#40
                ld b,a                          ; B — таблица палитры: старшие тексели
                ld a,c
                or a
                jp nz,.uniform
                ld a,(ix+1)
                pop de
                push ix
                ld ixl,8
                rlca
                jp c,.fy
                rlca
                jp c,.rowsFx
.rowsPlain:     ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                dec b
                ld a,e
                add a,#F9
                ld e,a
                ld a,d
                adc a,#01
                ld d,a                          ; + 505: начало строки ниже (от последнего тексела)
                dec ixl
                jp nz,.rowsPlain
                jp .tileNext
.rowsFx:        ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec b
                ld a,e
                add a,#07
                ld e,a
                ld a,d
                adc a,#02
                ld d,a                          ; + 519: последний тексел строки ниже (от первого)
                dec ixl
                jp nz,.rowsFx
                jp .tileNext
.fy:            rlca
                jp c,.rowsFxFy
.rowsFy:        ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                inc e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                inc e
                inc b
                ld a,(bc)
                ld (de),a
                dec b
                ld a,e
                add a,#F9
                ld e,a
                ld a,d
                adc a,#FD
                ld d,a                          ; − 519: начало строки выше (от последнего тексела)
                dec ixl
                jp nz,.rowsFy
                jp .tileNext
.rowsFxFy:      ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec e
                dec b
                ld c,(hl)
                inc l
                ld a,(bc)
                ld (de),a
                dec e
                inc b
                ld a,(bc)
                ld (de),a
                dec b
                ld a,e
                add a,#07
                ld e,a
                ld a,d
                adc a,#FE
                ld d,a                          ; − 505: последний тексел строки выше (от первого)
                dec ixl
                jp nz,.rowsFxFy
.tileNext:      pop ix
.tileStep:      ld bc,4
                add ix,bc
                ld hl,RING_C
                inc (hl)
                ld hl,RING_LEFT_T
                dec (hl)
                jp nz,.tile
                ret
; VDAC2+: одноцветный тайл — 8 строк по 8 текселей одного значения (отражения не меняют картинку): тексел — по таблице
; палитры B от первого байта тайла (HL), приёмник — строка 0 тайла столбца RING_C; приёмник с учётом отражений со стека
; не нужен. Около 1000 тактов на тайл против 2600 табличной сборки.
.uniform:       pop de
                ld c,(hl)
                ld a,(bc)                       ; палитра·16 + перо
                ld c,a
                ld a,(RING_C)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; c·8
                ld a,h
                add a,(#4000+RING_TEX_OFFSET) >> 8
                ld h,a                          ; строка 0 тайла в RING_TEX (окно W1)
                ld de,505
                ld b,8
.uRow:          ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                inc l
                ld (hl),c
                add hl,de                       ; + 505: начало строки ниже (от последнего тексела)
                djnz .uRow
                jp .tileStep

; VDAC2+: все RING_N тайлов с RING_TSRC одноцветные и одного значения (палитра·16 + перо)? CF = 0 — да: строка 0
; диапазона в RING_TEX (окно W1) залита им, RING_SSTEP = 0 — RingOut шлёт её во все 8 строк, отражения не важны. CF = 1 —
; нет (сборка обычная). Конец этапа стирает слой целиком (1472 тайла пера 0), пустое пространство этапа 1 — такие же
; диапазоны. Портит всё, окно W2.
RingConstant:   ld ix,(RING_TSRC)
                call RingTileValue
                ret c
                ld (RING_CVAL),a
                ld a,(RING_N)
                dec a
                ld b,a
.next:          push bc
                ld bc,4
                add ix,bc
                call RingTileValue
                pop bc
                ret c                           ; не одноцветный
                ld hl,RING_CVAL
                cp (hl)
                scf
                ret nz                          ; другое значение
                djnz .next
                ld a,(RING_DCOL)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; DCOL·8
                ld a,h
                add a,(#4000+RING_TEX_OFFSET) >> 8
                ld h,a                          ; строка 0 диапазона (окно W1)
                ld a,(RING_CVAL)
                ld (hl),a
                ld d,h
                ld e,l
                inc de
                ld a,(RING_N)
                ld c,a
                ld b,0
                sla c
                rl b
                sla c
                rl b
                sla c
                rl b                            ; N·8
                dec bc
                ldir
                xor a                           ; CF = 0
                ld (RING_SSTEP),a
                ret

; Тайл записи IX (код, отражения, атрибут) одноцветный? CF = 0 — да, A — палитра·16 + перо (перо — младший полубайт
; первого байта родного тайла, страница — в окне W2 через RING_MAPPED); CF = 1 — нет. Портит AF, BC, DE, HL.
RingTileValue:  ld a,(ix+1)
                and #0F
                ld h,a
                ld l,(ix+0)                     ; HL — код
                ld a,h
                srl a
                ld c,a                          ; C — код >> 9
                ld a,h
                and 1
                add a,(#4000+RING_UNI_OFFSET) >> 8
                ld d,a
                ld e,l
                ld b,(#4000+RING_BITS_OFFSET) >> 8
                ld a,(bc)
                ex de,hl
                and (hl)
                ex de,hl
                scf
                ret z                           ; не одноцветный
                ld a,c
                add a,RING_TILE_PAGE0
                ld b,a
                ld a,(RING_MAPPED)
                cp b
                jr z,.mapped
                ld a,b
                ld (RING_MAPPED),a
                ld bc,PORT_PAGE2
                out (c),a
.mapped:        add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; код·32
                ld a,h
                and #3F
                or #80
                ld h,a
                ld a,(hl)
                and #0F
                ld c,a                          ; перо
                ld a,(ix+2)
                and 15
                rlca
                rlca
                rlca
                rlca
                or c                            ; CF = 0
                ret

; Строки текселей R = 0…7 из RING_TEX → RAM_G кольца: строка слоя t = RING_T + R в окне ((t − w) & 511 < 256) — записью
; SPI по адресу RING_BASE + (t & 255)·512 + RING_DCOL·8, RING_N·8 текселей с R·512 + RING_DCOL·8 рабочей страницы;
; от двух тайлов — DMA RAM→SPI, один тайл — OTIR из окна W1. RING_T на выходе — на 8 дальше. VDAC2+: длина пачки,
; число пачек и страница источника DMA пишутся один раз на вызов — DMA TS-Conf их не меняет (после передачи меняется
; только адрес источника: Unreal, dma_next_burst), на строку — адрес источника и запуск; RING_BASE + столбец
; текселей (RING_BX) — тоже один раз. Прерываний Z80 в цикле кадров нет — регистры DMA между строками никто не
; трогает. Портит всё.
RingOut:        ld a,(RING_DCOL)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; столбец текселей
                push hl
                ld de,RING_TEX_OFFSET
                add hl,de
                ld (RING_SRC),hl                ; строка 0 в рабочей странице
                pop hl
                ld de,RING_BASE & #FFFF
                add hl,de
                ld a,l
                ld (RING_BX),a                  ; младший байт RING_BASE + столбец
                ld a,h
                ld (RING_BX+1),a                ; средний
                ld a,RING_BASE >> 16
                adc a,0
                ld (RING_BX+2),a                ; старший
                ld a,(RING_N)
                cp 2
                jr c,.lines                     ; один тайл — OTIR
                add a,a
                add a,a
                dec a                           ; слов пачки − 1: N·4 − 1 (N ≤ 64)
                ld bc,DMALEN
                out (c),a
                xor a
                ld b,DMANUM >> 8
                out (c),a                       ; одна пачка
                ld a,RING_WORK_PAGE
                ld b,DMASADDRX >> 8
                out (c),a
.lines:         ld a,8
.row:           ld (RING_ROWS),a
                ld hl,(RING_T)
                ld de,(RING_W)
                or a
                sbc hl,de
                bit 0,h
                jr nz,.skip                     ; строка вне окна
                ld a,(RING_T)                   ; t & 255
                ld l,a
                ld h,0
                add hl,hl                       ; (t & 255)·2: к среднему и старшему байту
                ld de,(RING_BX+1)
                add hl,de                       ; H — старший, L — средний байт адреса
                ld a,(RING_BX)
                ld e,a
                ld d,l
                ld a,h
                call FtOpenWrite                ; A — старший байт, DE — младшие 16 бит
                ld hl,(RING_SRC)
                ld a,(RING_N)
                cp 2
                jr c,.otir
                ld a,l
                ld bc,DMASADDRL
                out (c),a
                ld a,h
                ld b,DMASADDRH >> 8
                out (c),a
                ld a,DMA_RAM_SPI
                ld b,DMACTR >> 8
                out (c),a
.wait:          in a,(c)                        ; DMASTATUS — тот же порт
                rla
                jr c,.wait                      ; бит 7 — передача идёт
                jr .close
.otir:          ld b,8
                ld a,h
                add a,#40
                ld h,a                          ; смещение → окно W1
                ld c,SPI_DATA
                otir
.close:         call FtClose
.skip:          ld hl,RING_SRC+1
                ld a,(RING_SSTEP)
                add a,(hl)
                ld (hl),a                       ; следующая строка: + 512 (у диапазона одним значением — та же)
                ld hl,(RING_T)
                inc hl
                ld (RING_T),hl
                ld a,(RING_ROWS)
                dec a
                jr nz,.row
                ld a,2
                ld (RING_SSTEP),a               ; следующий вызов — снова построчно
                ret
                ASSERT low DMASADDRL == #AF && low DMASADDRH == #AF && low DMASADDRX == #AF
                ASSERT low DMALEN == #AF && low DMANUM == #AF && low DMACTR == #AF && DMASTATUS == DMACTR
                ASSERT DMA_WNR == #80

; После записи тени строки группы слоя 1: тайлы низкого прохода приоритета (PASS_TABLE фона) в TILE_TEMP → маска
; RING_MARK (слово кода #2000, атрибут 0): ячейками их не выводят, фон даёт кольцо. У тайлов высокого прохода бит
; RING_MARK снимается (в коде M72 он лишний: код набора — 12 бит). Портит AF, B, DE, HL.
RingMask:       ld hl,TILE_TEMP
                ld b,16
.tile:          push hl
                inc hl
                inc hl
                ld a,(hl)                       ; атрибут: режим приоритета — биты 7, 6
                rlca
                rlca
                and 3
                add a,4                         ; PASS_TABLE[слой 1·4 + режим]
                ld e,a
                ld d,0
                ld hl,PASS_TABLE
                add hl,de
                ld a,(hl)
                pop hl
                inc hl
                or a
                jr nz,.high                     ; высокий проход — ячейками поверх спрайтов
                dec hl
                ld (hl),0
                inc hl
                ld (hl),RING_MARK
                inc hl
                ld (hl),0
                inc hl
                ld (hl),0
                inc hl
                djnz .tile
                ret
.high:          res 5,(hl)
                inc hl
                inc hl
                inc hl
                djnz .tile
                ret


; Перо PAL_PEN таблицы PAL_TABLE банка 1 (16…31) → запись таблицы палитры кольца (палитра·16 + перо): DE — цвет
; пера (E — G4·16 + B4, D — R4), альфа полная. Пока кольцо не готово, таблицу целиком пишет RingService (её место —
; в зоне изображений титула). Портит AF, BC, HL.
RingLutPen:     ld a,(RING_READY)
                or a
                ret z
                push de
                ld a,(PAL_TABLE)
                sub 16
                add a,a
                add a,a
                add a,a
                add a,a
                ld hl,PAL_PEN
                add a,(hl)
                ld l,a
                ld h,0
                add hl,hl                       ; запись·2
                ld de,RING_LUT & #FFFF
                add hl,de
                ld a,RING_LUT >> 16
                adc a,0
                ex de,hl
                call FtOpenWrite
                pop de
                ld a,e
                out (SPI_DATA),a
                ld a,d
                or #F0
                out (SPI_DATA),a
                jp FtClose
