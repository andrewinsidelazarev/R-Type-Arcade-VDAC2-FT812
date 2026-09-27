; ============================================================================
; Видеотракт M72 на FT812 — перенос src/mame/irem/m72_v.cpp.
;
; Порт держит те же структуры, что и оригинал: тайловую память двух слоёв,
; sprite RAM и регистры скролла. Игровой код пишет в них ровно то же, что писал
; V30, а этот модуль превращает их в список отображения FT812. Никаких готовых
; кадров: экран каждый раз собирается из примитивов, поэтому мигающий текст,
; счётчик кредитов и анимация работают сами собой.
;
; Тайловая память (по m72_v.cpp): карта 64×64 тайла, НА ТАЙЛ ДВА СЛОВА —
; код и атрибут. В коде биты 0..13 — номер тайла, бит 14 — отражение по X,
; бит 15 — по Y. В атрибуте младший ниббл — палитра, биты 6..7 — приоритет.
; Видимая область начинается с X=64, по Y смещена на 128.
;
; Геометрия. Логический экран 640×480 против нативных 384×256: по вертикали
; тайл 8 px разворачивается в 15 ровно, по горизонтали 640/48 = 13.333 —
; нецелое. Поэтому глиф в атласе шириной 14, а позиция считается в 1/8 пикселя
; абсолютно (VERTEX_FORMAT 3): ошибка не копится, лишний столбец перекрывает
; сосед, который рисуется поверх.
; ============================================================================

M72_TILEMAP_COLS    EQU 64           ; карта в памяти
M72_TILEMAP_ROWS    EQU 64
M72_VISIBLE_COLS    EQU 48           ; видимая область 384/8
M72_VISIBLE_ROWS    EQU 32           ; 256/8
M72_RAW_VISIBLE_X   EQU 64           ; левый край видимой части raster
M72_SCROLL_DY       EQU 128          ; -TILE_SCROLL_DY из m72_v.cpp

; Глиф испечён в ЛОГИЧЕСКОМ размере 640×480. Последний масштаб 8/5 до
; физических 1024×768 всегда выполняет FT812 в режиме NEAREST.
M72_GLYPH_W         EQU 14           ; 640/48 = 13.33 с запасом на перекрытие
M72_GLYPH_H         EQU 15           ; 480/32 = 15 ровно
M72_GLYPH_BYTES     EQU M72_GLYPH_W * M72_GLYPH_H * 2   ; ARGB4444
; Физический размер после аппаратного 8/5: ширина берётся с запасом в
; пиксель, иначе при дробной позиции справа появлялась бы щель.
M72_GLYPH_PHYS_W    EQU 22           ; ceil(14 * 8/5)
M72_GLYPH_PHYS_H    EQU 24           ; 15 * 8/5
; Шаг тайла по X в 1/8 пикселя: 640 / 48 × 8 = 106.667. Дробь хранится
; отдельно, чтобы позиция считалась абсолютно, а не приращением.
M72_STEP_INT        EQU 170          ; 1024/48 × 8 = 170.667
M72_STEP_NUM        EQU 2            ; +2/3 пикселя в восьмых
M72_STEP_DEN        EQU 3

; --- Структуры оригинала в памяти Z80 (страница данных) ---
M72_VRAM0           EQU #C000        ; слой 0: 64×64×2 слова = 16 КБ
M72_VRAM1           EQU #C000        ; слой 1: в своей странице
M72_SPRITERAM       EQU #E000        ; 1 КБ, формат sprite RAM M72

; --- Резидентное состояние видеотракта ---
; Карта резидентных переменных продолжается ЗА состоянием игры: блок
; arcade_game.asm занят по #424B включительно (ArcadeShotPending), и первая
; раскладка видеотракта наложилась прямо на него — инициализация игры затирала
; номер страницы с тайловой памятью, отчего рендерер читал чужие данные.
M72_ScrollFgX       EQU #4260        ; 2Б
M72_ScrollFgY       EQU #4262
M72_ScrollBgX       EQU #4264
M72_ScrollBgY       EQU #4266
M72_VramPage0       EQU #4268        ; номер страницы со слоем 0
M72_VramPage1       EQU #4269
M72_SpritePage      EQU #426A
M72_TileAtlasLo     EQU #426B        ; база атласа глифов в RAM_G
M72_TileAtlasHi     EQU #426D
M72_SprAtlasLo      EQU #426E        ; база спрайтового атласа в RAM_G
M72_SprAtlasHi      EQU #4270
; #4271 занят GameMode в main.asm. Состояние титула начинается строго после
; него: прежнее наложение таймера на GameMode включало игру на первом кадре.
M72_TitleTimer      EQU #4272        ; 16-битный номер кадра меню
M72_TitleBlink      EQU #4273        ; старший байт M72_TitleTimer
M72_TitleLogoOffset EQU #4275        ; знаковое смещение логотипа Y, 2 Б
M72_TitleInputArmed EQU #4277        ; прошлый уровень FIRE для фронта KEYDOWN
M72_TitleReleaseCnt EQU #4278        ; резерв
M72TitleEventPtr       EQU #4279      ; адрес пакета в текущей stream page
M72TitleEventPageIndex EQU #427B
M72TitleEventDone      EQU #427C
M72TitlePalette6       EQU #427D      ; 5-битный уровень бирюзового текста
M72TitlePalettePromptR EQU #427E      ; 5-битный цвет строки PRESS FIRE
M72TitlePalettePromptB EQU #427F
M72TitleFtFrameLast    EQU #4280      ; low word FT_REG_FRAMES
M72TitleRateAccum      EQU #4282      ; дробь: M72 55 Гц / FT812 60 Гц

; Плеер точных пакетов MAME VRAM-delta. Поток лежит в одной SPG-странице,
; карты — в двух других; поэтому записи одного слоя сначала копируются в
; резидентный scratch, затем применяются после переключения slot3.
; Счётчик оставлен локально только для отключённого экспериментального
; stage-прохода; игровая логика arcade_game.asm полностью возвращена из v002.
ArcadeStageFrame       EQU #4290
M72StageEventPtr       EQU #42A0      ; адрес следующего пакета внутри #C000
M72StageEventPageIndex EQU #42A2      ; индекс 16К-страницы потока
M72StageEventDone      EQU #42A3
M72StageEventFgCount   EQU #42A4
M72StageEventBgCount   EQU #42A5
M72StageEventScratch    EQU #4700     ; максимум 255 записей × 4 = 1020 Б
M72StageEventScratchEnd EQU M72StageEventScratch + 255 * 4
; Верхняя граница всех resident данных — машинно-читаемый контракт для
; rtype_python_translator.py. Стек размещается только после этого адреса.
RTYPE_RESIDENT_DATA_END EQU M72StageEventScratchEnd
M72_TITLE_SHOW_TEXT EQU %00000001
; Резидентная копия sprite RAM (1 КБ). Читать структуру оригинала прямо из
; slot3 во время построения списка нельзя: EmitSprite мапит страницы RAM_G под
; атлас, и любой промах слота даёт чтение чужой страницы. Копия снимается один
; раз и лежит в резиденте, поэтому обход не зависит от текущего маппинга slot3.
M72_SprRamCopy      EQU #4300        ; 1 КБ, #4300..#46FF
M72TitleGlyphState  EQU #4300        ; 7 записей visible/x/y по 5 байт
M72TitleTextCount   EQU #4323
M72TitleTextState   EQU #4324        ; до 96 записей cell/style/x/y

; ---------------------------------------------------------------------------
; M72Video_DrawTileLayer — слой тайлов из VRAM в список отображения.
;
; Проход идёт по видимой сетке 48×32, как в m72_v.cpp: для каждой ячейки
; вычисляется адрес в карте с учётом скролла и обёртки по 512 пикселям, затем
; читается пара слов (код, атрибут). Прозрачные тайлы (код пробела) не выдаются
; вовсе — на них ушла бы четверть списка отображения впустую.
;
; Вход: A = номер страницы со слоем, HL = адрес скролла (X, Y).
; ---------------------------------------------------------------------------
M72Video_EmitCount:  DEFB 0
M72Video_SolidCount: DEFB 0      ; непустых ячеек карты (до поиска глифа)
M72Video_FirstByte:  DEFB 0      ; что реально лежит по #C000 после SetPage3
M72Video_TilePass:   DEFB 0      ; 0=за спрайтами, 1=перед спрайтами

M72Video_DrawTileLayer:
                LD   C, A                        ; номер страницы переживает сброс счётчика
                XOR  A
                LD   (M72Video_EmitCount), A
                LD   (M72Video_SolidCount), A
                LD   A, C
                SetPage3_A
                ; Контроль страницы: первый байт карты должен быть $A0
                ; (код тайла $0FA0 фонового заполнения титульного экрана).
                LD   A, (#C000)
                LD   (M72Video_FirstByte), A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; DE = scroll X
                LD   (.scrollX), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; DE = scroll Y
                LD   (.scrollY), DE

                XOR  A
                LD   (.row), A                   ; ty = 0
.rowLoop:
                ; source_y = (ty*8 + M72_SCROLL_DY + scrollY) & 511
                LD   A, (.row)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; ty*8
                LD   DE, M72_SCROLL_DY
                ADD  HL, DE
                LD   DE, (.scrollY)
                ADD  HL, DE
                LD   A, H
                AND  1                           ; & 511
                LD   H, A
                LD   (.sourceY), HL

                ; Экранная Y тайла в 1/8 пикселя: 768/32 = 24 px ровно,
                ; значит ty × 24 × 8 = ty × 192. Обе координаты VERTEX2F идут
                ; в одних единицах — восьмых долях пикселя.
                LD   A, (.row)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; ty*64
                LD   D, H
                LD   E, L
                ADD  HL, HL                      ; ty*128
                ADD  HL, DE                      ; ty*192
                LD   (.screenY), HL

                XOR  A
                LD   (.column), A
.columnLoop:
                CALL M72Video_TileAt
                JR   Z, .skip                    ; пусто — ничего не рисуем
                ; Уровни палитр идут из точной MAME-трассы. Цветные варианты
                ; запечены в HQ-атласе, а нулевой уровень означает прозрачность.
                PUSH AF
                AND  #0F
                CP   6
                JR   NZ, .notPalette6
                LD   A, (M72TitlePalette6)
                OR   A
                JR   NZ, .tileVisible
                POP  AF
                JR   .skip
.notPalette6:
                CP   14
                JR   NZ, .tileVisible
                LD   A, (M72TitlePalettePromptR)
                OR   A
                JR   NZ, .tileVisible
                LD   A, (M72TitlePalettePromptB)
                JR   NZ, .tileVisible
                POP  AF
                JR   .skip
.tileVisible:   POP  AF
                PUSH AF
                PUSH BC
                LD   A, (M72Video_SolidCount)
                INC  A
                LD   (M72Video_SolidCount), A
                POP  BC
                POP  AF
                CALL M72Video_FindGlyph
                JR   NC, .skip                   ; глифа нет в атласе сцены
                CALL M72Video_EmitTile
.skip:
                LD   A, (.column)
                INC  A
                LD   (.column), A
                CP   M72_VISIBLE_COLS
                JR   C, .columnLoop

                LD   A, (.row)
                INC  A
                LD   (.row), A
                CP   M72_VISIBLE_ROWS
                JP   C, .rowLoop
                RET

.scrollX:       DEFW 0
.scrollY:       DEFW 0
.sourceY:       DEFW 0
.screenY:       DEFW 0
.row:           DEFB 0
.column:        DEFB 0

; ---------------------------------------------------------------------------
; M72Video_TileAt — прочитать ячейку карты для текущих (.row, .column).
;
; Возврат: BC = код тайла (с флагами отражения), A = атрибут, ZF=1 если ячейка
; пустая (код 0 или пробел — оба означают «ничего не рисовать»).
; ---------------------------------------------------------------------------
M72Video_TileAt:
                ; source_x = (tx*8 + M72_RAW_VISIBLE_X + scrollX) & 511
                LD   A, (M72Video_DrawTileLayer.column)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, M72_RAW_VISIBLE_X
                ADD  HL, DE
                LD   DE, (M72Video_DrawTileLayer.scrollX)
                ADD  HL, DE
                LD   A, H
                AND  1
                LD   H, A                        ; & 511

                ; index = (source_y >> 3) * 64 + (source_x >> 3), запись 4 байта
                LD   A, L
                RRCA
                RRCA
                RRCA
                AND  #1F                         ; (source_x >> 3) & 63, старший бит ниже
                LD   C, A
                LD   A, H
                RRCA
                RRCA
                RRCA
                AND  #20
                OR   C
                LD   C, A                        ; C = source_x >> 3 (0..63)

                LD   HL, (M72Video_DrawTileLayer.sourceY)
                LD   A, H
                RRCA
                RRCA
                RRCA
                AND  #20
                LD   B, A
                LD   A, L
                RRCA
                RRCA
                RRCA
                AND  #1F
                OR   B
                LD   B, A                        ; B = source_y >> 3 (0..63)

                ; адрес = VRAM + (B*64 + C) * 4
                LD   L, B
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; B*64
                LD   E, C
                LD   D, 0
                ADD  HL, DE                      ; + C
                ADD  HL, HL
                ADD  HL, HL                      ; ×4 — на тайл два слова
                LD   DE, M72_VRAM0
                ADD  HL, DE

                LD   C, (HL)
                INC  HL
                LD   B, (HL)                     ; BC = код с флагами отражения
                INC  HL
                LD   A, (HL)                     ; атрибут (младший байт: палитра)
                LD   (.attribute), A

                ; Пустыми считаются код 0 и пробел: оригинал заполняет ими фон.
                LD   A, B
                AND  #3F
                OR   C
                RET  Z
                LD   A, B
                AND  #3F
                OR   A
                JR   NZ, .notSpace
                LD   A, C
                CP   #20
                RET  Z                           ; пробел — ZF=1
.notSpace:
                LD   A, (.attribute)
                OR   #10                         ; ZF=0 гарантированно
                RET
.attribute:     DEFB 0

; ---------------------------------------------------------------------------
; M72Video_EmitTile — выдать один тайл в список отображения.
;
; На тайл уходят две команды: BITMAP_SOURCE с адресом глифа в RAM_G и
; VERTEX2F с позицией. Формат/размер выставляются один раз до цикла — все
; глифы атласа одинаковы, и повторять их на каждую ячейку значило бы утроить
; список отображения.
;
; Вход: A = номер глифа в атласе (из таблицы соответствия кода и палитры).
; ---------------------------------------------------------------------------
M72Video_EmitTile:
                PUSH AF
                LD   A, (M72Video_EmitCount)
                INC  A
                LD   (M72Video_EmitCount), A
                POP  AF
                ; Адрес глифа = база атласа + номер × M72_GLYPH_BYTES.
                LD   L, A
                LD   H, 0
                LD   DE, M72_GLYPH_BYTES
                CALL M72Video_MulHLDE            ; HL:DE = смещение (24 бита)
                LD   BC, (M72_TileAtlasLo)
                ADD  HL, BC
                LD   A, (M72_TileAtlasHi)
                ADC  A, 0                        ; перенос из младших 16 бит
                ; Умножение даёт не больше 16 бит: атлас сцены — десятки
                ; килобайт, поэтому старший байт берётся только из базы.
                ; BITMAP_SOURCE = #01 << 24 | адрес (22 бита).
                LD   B, #01
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE

                ; Позиция: X абсолютно в 1/8 пикселя, Y — целыми пикселями.
                CALL M72Video_ColumnX            ; HL = X в 1/8 пикселя
                LD   DE, (M72Video_DrawTileLayer.screenY)
                JP   M72Video_Vertex2f

; ---------------------------------------------------------------------------
; M72Video_Vertex2f — VERTEX2F из готовых координат в 1/8 пикселя.
;
; Общий FT.Coprocessor.Vertex2f принимает координаты в своём масштабе и сам их
; сдвигает; порт подаёт туда значения через M72_LogicalToVertex. Здесь позиция
; уже посчитана в единицах VERTEX_FORMAT 3, поэтому слово собирается напрямую:
;   VERTEX2F = %01 << 30 | (x & 0x7FFF) << 15 | (y & 0x7FFF)
;
; Вход: HL = X, DE = Y (обе в 1/8 пикселя).
; ---------------------------------------------------------------------------
M72Video_Vertex2f:
                ; E = младшие 8 бит Y — кладётся как есть.
                LD   A, E
                LD   (.byteE), A
                ; D = бит 0 X в старший разряд плюс старшие биты Y.
                LD   A, D
                AND  #7F
                SRL  H
                RR   L                           ; HL >>= 1, вытесненный бит в CF
                JR   NC, .noCarry
                OR   #80
.noCarry:       LD   (.byteD), A
                ; C = следующие 8 бит X, B = остаток с меткой команды %01.
                LD   A, L
                LD   (.byteC), A
                LD   A, H
                AND  #3F
                OR   #40                         ; код VERTEX2F
                LD   B, A
                LD   A, (.byteC)
                LD   C, A
                LD   A, (.byteD)
                LD   D, A
                LD   A, (.byteE)
                LD   E, A
                JP   FT.Coprocessor.Command_BCDE
.byteC:         DEFB 0
.byteD:         DEFB 0
.byteE:         DEFB 0

; ---------------------------------------------------------------------------
; M72Video_ColumnX — X текущей колонки в единицах VERTEX2F.
;
; Шаг 640/48 = 13.333 px нецелый, поэтому позиция считается АБСОЛЮТНО:
; x8 = round(column × 106.667). Приращением ошибка копилась бы и к правому
; краю уводила сетку на два пикселя. Физический экран шире логического в 8/5,
; и перевод делает общая для порта таблица.
; ---------------------------------------------------------------------------
M72Video_ColumnX:
                LD   A, (M72Video_DrawTileLayer.column)
                LD   L, A
                LD   H, 0
                LD   DE, M72_STEP_INT
                CALL M72Video_MulHLDE            ; column × 106
                ; Дробная часть: + round(column × 2 / 3) восьмых.
                LD   A, (M72Video_DrawTileLayer.column)
                ADD  A, A                        ; ×2
                LD   E, A
                LD   D, 0
                LD   A, M72_STEP_DEN
                CALL M72Video_DivDE_A            ; DE = column×2/3
                ADD  HL, DE
                RET                              ; HL = X в 1/8 физического пикселя

; HL = HL × DE (16×16, младшие 16 бит в HL, старшие в D).
M72Video_MulHLDE:
                LD   B, H
                LD   C, L
                LD   HL, 0
                LD   A, 16
.loop:          ADD  HL, HL
                RL   E
                RL   D
                JR   NC, .skip
                ADD  HL, BC
.skip:          DEC  A
                JR   NZ, .loop
                RET

; DE = DE / A (беззнаково, малые значения).
; HL НЕ ТРОГАЕТСЯ: вызывающий код держит в нём накопленную позицию, и
; обнуление здесь стирало целую часть X, оставляя одну дробную.
M72Video_DivDE_A:
                LD   B, A
                LD   A, E
                LD   C, 0
.loop:          CP   B
                JR   C, .done
                SUB  B
                INC  C
                JR   .loop
.done:          LD   E, C
                LD   D, 0
                RET

; ---------------------------------------------------------------------------
; M72Video_Init — атлас глифов в RAM_G, тайловая память в страницу Z80.
;
; Атлас уходит в FT812 один раз: глифы не меняются. Тайловая память остаётся в
; памяти Z80, потому что игровой код пишет в неё каждый кадр — ровно как V30
; писал в VRAM оригинала.
; ---------------------------------------------------------------------------
M72Video_Init:
                LD   HL, M72AtlasPageTable
                LD   (.tblPtr), HL
                LD   HL, M72_ATLAS_RAMG & #FFFF
                LD   (.ramgLo), HL
                LD   A, (M72_ATLAS_RAMG >> 16) & #FF
                LD   (.ramgHi), A
                LD   A, M72_ATLAS_PAGE_COUNT
                LD   (.count), A
.next:
                LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next

                ; База атласа в RAM_G — рендерер отсчитывает от неё глифы.
                LD   HL, M72_ATLAS_RAMG & #FFFF
                LD   (M72_TileAtlasLo), HL
                LD   A, (M72_ATLAS_RAMG >> 16) & #FF
                LD   (M72_TileAtlasHi), A

                ; Спрайтовый атлас титула вынесен в отдельную процедуру: World
                ; перезаписывает середину этого RAM_G-диапазона, и возврат из
                ; Повторная инициализация обязана тем же DMA-путём восстановить пиксели.
                CALL M72Video_UploadTitleAtlas

                ; Страницы со структурами оригинала: тайловая память и sprite RAM.
                LD   HL, M72SpriteRamPageTable
                LD   A, (HL)
                LD   (M72_SpritePage), A
                SetPage3_A
                LD   HL, #C000
                LD   DE, M72_SprRamCopy
                LD   BC, 1024
                LDIR                             ; sprite RAM -> резидент
                LD   HL, M72TitleVramPageTable
                LD   A, (HL)
                LD   (M72_VramPage0), A
                XOR  A
                LD   (M72_ScrollFgX), A
                LD   (M72_ScrollFgX + 1), A
                LD   (M72_ScrollFgY), A
                LD   (M72_ScrollFgY + 1), A
                ; Старые Stage1 HQ atlases принадлежат отключённому
                ; экспериментальному tile renderer. Живой World загружает
                ; terrain textures из RTZ2, поэтому не тратим старт на лишний
                ; перенос в RAM_G, который всё равно сразу будет перезаписан.
                RET
.tblPtr:        DEFW 0
.ramgLo:        DEFW 0
.ramgHi:        DEFB 0
.chunkLen:      DEFW 0
.count:         DEFB 0

; ---------------------------------------------------------------------------
; Восстановить только ARGB4444 title-font atlas по сгенерированной базе
; M72_SPRATLAS_RAMG. База больше не зависит от размера игрового sprite blob.
;
; Нужен при первом старте и при повторной инициализации. Все пиксели
; уже лежат в 19 физических страницах SPG; Z80 лишь задаёт источник/назначение,
; а 300720 байт переносит DMA TS-Config прямо в SPI FT812.
; ---------------------------------------------------------------------------
M72Video_UploadTitleAtlas:
                LD   HL, M72SprAtlasPageTable
                LD   (.tblPtr), HL
                LD   HL, M72_SPRATLAS_RAMG & #FFFF
                LD   (.ramgLo), HL
                LD   A, (M72_SPRATLAS_RAMG >> 16) & #FF
                LD   (.ramgHi), A
                LD   A, M72_SPRATLAS_PAGE_COUNT
                LD   (.count), A
.nextSpr:
                LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .nextSpr

                LD   HL, M72_SPRATLAS_RAMG & #FFFF
                LD   (M72_SprAtlasLo), HL
                LD   A, (M72_SPRATLAS_RAMG >> 16) & #FF
                LD   (M72_SprAtlasHi), A
                RET
.tblPtr:        DEFW 0
.ramgLo:        DEFW 0
.ramgHi:        DEFB 0
.chunkLen:      DEFW 0
.count:         DEFB 0

; ---------------------------------------------------------------------------
; Титульный экран: последовательные состояния оригинальной sprite RAM и
; изменения foreground VRAM, снятые write taps MAME. В пакете нет пикселей:
; FT812 по-прежнему собирает кадр из ROM-примитивов и priority-проходов.
; ---------------------------------------------------------------------------
M72TitleEvents_Reset:
                LD   HL, #C000
                LD   (M72TitleEventPtr), HL
                XOR  A
                LD   (M72TitleEventPageIndex), A
                LD   (M72TitleEventDone), A
                LD   (M72TitlePalette6), A
                LD   (M72TitlePalettePromptR), A
                LD   (M72TitlePalettePromptB), A
                LD   (M72TitleTextCount), A
                RET

M72TitleEvents_Update:
                LD   A, (M72TitleEventDone)
                OR   A
                JR   NZ, .advanceFrame
                LD   HL, (M72TitleEventPtr)
                LD   DE, #FECA                    ; 38 * 423 байт в странице
                OR   A
                SBC  HL, DE
                JR   NZ, .map
                LD   HL, #C000
                LD   (M72TitleEventPtr), HL
                LD   A, (M72TitleEventPageIndex)
                INC  A
                LD   (M72TitleEventPageIndex), A
.map:           CALL M72TitleEvents_MapPage
                LD   HL, (M72TitleEventPtr)
                LD   DE, M72TitleGlyphState
                LD   BC, M72_TITLE_GLYPH_STATE_SIZE
                LDIR
                LD   A, (HL)
                LD   (M72TitleTextCount), A
                INC  HL
                LD   DE, M72TitleTextState
                LD   BC, M72_TITLE_TEXT_STATE_BYTES
                LDIR
                LD   A, (HL)
                LD   (M72TitlePalette6), A
                INC  HL
                LD   A, (HL)
                LD   (M72TitlePalettePromptR), A
                INC  HL
                LD   A, (HL)
                LD   (M72TitlePalettePromptB), A
                INC  HL
                LD   (M72TitleEventPtr), HL
.advanceFrame:  LD   HL, (M72_TitleTimer)
                INC  HL
                LD   (M72_TitleTimer), HL
                LD   DE, M72_TITLE_FRAME_COUNT
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   A, 1
                LD   (M72TitleEventDone), A
                RET

M72TitleEvents_MapPage:
                LD   A, (M72TitleEventPageIndex)
                LD   L, A
                LD   H, 0
                LD   E, A
                LD   D, 0
                ADD  HL, HL
                ADD  HL, DE                      ; индекс * 3
                LD   DE, M72TitleEventPageTable
                ADD  HL, DE
                LD   A, (HL)
                SetPage3_A
                RET

; Два игровых tile-прохода заранее увеличены как ЦЕЛЫЕ слои, но хранятся
; ячейками: runtime меняет scroll и каждый кадр собирает карту примитивами.
M72Stage_UploadAtlases:
                LD   HL, M72StageBgAtlasPageTable
                LD   DE, M72_STAGE_BG_ATLAS_RAMG & #FFFF
                LD   A, (M72_STAGE_BG_ATLAS_RAMG >> 16) & #FF
                LD   B, M72_STAGE_BG_ATLAS_PAGE_COUNT
                CALL .group
                LD   HL, M72StageFgAtlasPageTable
                LD   DE, M72_STAGE_FG_ATLAS_RAMG & #FFFF
                LD   A, (M72_STAGE_FG_ATLAS_RAMG >> 16) & #FF
                LD   B, M72_STAGE_FG_ATLAS_PAGE_COUNT
.group:         LD   (.tblPtr), HL
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   A, B
                LD   (.count), A
.next:          LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next
                RET
.tblPtr:        DEFW 0
.ramgLo:        DEFW 0
.ramgHi:        DEFB 0
.chunkLen:      DEFW 0
.count:         DEFB 0

; ---------------------------------------------------------------------------
; M72StageEvents_Reset / Update — runtime replay VRAM-пакетов MAME.
;
; Пакет: frame word, fg_count byte, bg_count byte, затем записи обоих слоёв.
; Запись: индекс word-map word + новый slot word. $FFFE переключает следующую
; 16К-страницу, $FFFF завершает поток. Генератор не разрывает пакет границей.
; ---------------------------------------------------------------------------
M72StageEvents_Reset:
                LD   HL, #C000
                LD   (M72StageEventPtr), HL
                XOR  A
                LD   (M72StageEventPageIndex), A
                LD   (M72StageEventDone), A
                RET

M72StageEvents_Update:
                LD   A, (M72StageEventDone)
                OR   A
                RET  NZ
.nextPacket:
                CALL M72StageEvents_MapPage
                LD   HL, (M72StageEventPtr)
                LD   E, (HL)                    ; целевой игровой кадр
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   A, D
                CP   #FF
                JR   NZ, .normalPacket
                LD   A, E
                CP   #FF
                JR   Z, .finished
                CP   #FE
                JR   NZ, .finished              ; повреждённый служебный marker
                LD   HL, M72StageEventPageIndex
                INC  (HL)
                LD   HL, #C000
                LD   (M72StageEventPtr), HL
                JR   .nextPacket
.normalPacket:
                PUSH HL                         ; указатель на два count
                LD   HL, (ArcadeStageFrame)
                OR   A
                SBC  HL, DE
                POP  HL
                RET  C                          ; пакет ещё не наступил

                LD   A, (HL)
                INC  HL
                LD   (M72StageEventFgCount), A
                LD   A, (HL)
                INC  HL
                LD   (M72StageEventBgCount), A

                ; Сначала FG-записи: источник скрывается после map page switch.
                LD   (.copySource), HL
                LD   A, (M72StageEventFgCount)
                CALL M72StageEvents_CopyRecords
                LD   (.bgSource), HL
                LD   A, (M72StageEventFgCount)
                PUSH AF
                LD   A, (M72StageFgMapPageTable)
                LD   C, A
                POP  AF
                CALL M72StageEvents_ApplyRecords

                ; Вернуться к текущей stream page, скопировать BG и запомнить
                ; следующий пакет. Внутри одного пакета границы страницы нет.
                CALL M72StageEvents_MapPage
                LD   HL, (.bgSource)
                LD   (.copySource), HL
                LD   A, (M72StageEventBgCount)
                CALL M72StageEvents_CopyRecords
                LD   (M72StageEventPtr), HL
                LD   A, (M72StageEventBgCount)
                PUSH AF
                LD   A, (M72StageBgMapPageTable)
                LD   C, A
                POP  AF
                CALL M72StageEvents_ApplyRecords
                JR   .nextPacket                 ; допускает несколько overdue-пакетов
.finished:      LD   A, 1
                LD   (M72StageEventDone), A
                RET
.copySource:    DEFW 0
.bgSource:      DEFW 0

; Замапить 16К-страницу потока по трёхбайтной записи page/size. Размер нужен
; загрузчику SPG; runtime выбирает только первый байт записи.
M72StageEvents_MapPage:
                LD   A, (M72StageEventPageIndex)
                LD   L, A
                LD   H, 0
                LD   E, A
                LD   D, 0
                ADD  HL, HL
                ADD  HL, DE                      ; индекс * 3
                LD   DE, M72StageEventPageTable
                ADD  HL, DE
                LD   A, (HL)
                SetPage3_A
                RET

; A записей по четыре байта: HL stream -> scratch. Нулевой count LDIR не запускает.
M72StageEvents_CopyRecords:
                OR   A
                RET  Z
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                      ; HL = count * 4
                LD   B, H
                LD   C, L
                LD   HL, (M72StageEvents_Update.copySource)
                LD   DE, M72StageEventScratch
                LDIR
                RET                              ; HL указывает вслед за записями

; A=count, C=страница word-map. Каждая запись: index word, slot word.
M72StageEvents_ApplyRecords:
                OR   A
                RET  Z
                LD   (.count), A
                LD   A, C
                SetPage3_A
                LD   HL, M72StageEventScratch
.record:        LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                INC  HL
                PUSH HL
                LD   HL, #C000
                ADD  HL, DE
                ADD  HL, DE                      ; word-map: index * 2
                LD   (HL), C
                INC  HL
                LD   (HL), B
                POP  HL
                LD   A, (.count)
                DEC  A
                LD   (.count), A
                JR   NZ, .record
                RET
.count:         DEFB 0

; Stage 1: живой horizontal scroll двух проходов M72. Back рисуется до
; спрайтов, Front — после них, как priority masks из m72_v.cpp.
M72Stage_DrawBack:
                LD   HL, M72_STAGE_BG_ATLAS_RAMG & #FFFF
                LD   (M72Stage_DrawPass.baseLo), HL
                LD   A, (M72_STAGE_BG_ATLAS_RAMG >> 16) & #FF
                LD   (M72Stage_DrawPass.baseHi), A
                LD   A, (M72StageBgMapPageTable)
                LD   HL, M72_ScrollBgX
                JR   M72Stage_DrawPass

M72Stage_DrawFront:
                LD   HL, M72_STAGE_FG_ATLAS_RAMG & #FFFF
                LD   (M72Stage_DrawPass.baseLo), HL
                LD   A, (M72_STAGE_FG_ATLAS_RAMG >> 16) & #FF
                LD   (M72Stage_DrawPass.baseHi), A
                LD   A, (M72StageFgMapPageTable)
                LD   HL, M72_ScrollFgX

M72Stage_DrawPass:
                LD   (.mapPage), A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.scroll), DE
                LD   A, E
                AND  7
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, M72StageShiftTable
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.shiftUnits), DE
                LD   HL, (.scroll)
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   A, L
                ADD  A, 8                        ; raw visible X=64 = 8 тайлов
                AND  63
                LD   (.sourceBase), A
                LD   A, (.mapPage)
                SetPage3_A

                FT_BitmapTransformA 160
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_ARGB4, M72_STAGE_GLYPH_W * 2, M72_STAGE_GLYPH_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, M72_GLYPH_PHYS_W, M72_GLYPH_PHYS_H
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                XOR  A
                LD   (.row), A
.rowLoop:       LD   A, (.row)
                LD   L, A
                LD   H, 0
                LD   DE, 192
                CALL M72Video_MulHLDE
                LD   (M72Video_DrawTileLayer.screenY), HL
                XOR  A
                LD   (.column), A
.columnLoop:    LD   A, (.sourceBase)
                LD   C, A
                LD   A, (.column)
                ADD  A, C
                AND  63
                LD   C, A
                LD   A, (.row)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; row * 64
                LD   E, C
                LD   D, 0
                ADD  HL, DE                      ; + column = cell index
                ADD  HL, HL                      ; word slot
                LD   DE, #C000
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                AND  E
                INC  A                          ; Z только для пустого $FFFF
                EX   DE, HL
                CALL NZ, M72Stage_EmitGlyph
                LD   A, (.column)
                INC  A
                LD   (.column), A
                CP   49
                JR   C, .columnLoop
                LD   A, (.row)
                INC  A
                LD   (.row), A
                CP   32
                JP   C, .rowLoop
                FT_End
                RET
.mapPage:       DEFB 0
.scroll:        DEFW 0
.sourceBase:    DEFB 0
.shiftUnits:    DEFW 0
.row:           DEFB 0
.column:        DEFB 0
.baseLo:        DEFW 0
.baseHi:        DEFB 0

; HL = 16-битный слот текущего прохода.
M72Stage_EmitGlyph:
                LD   A, H
                LD   (.slotHi), A
                LD   A, L
                LD   DE, M72_STAGE_GLYPH_BYTES
                CALL M72Video_Mul8x16_24         ; low(slot) * glyph bytes
                LD   (.offsetLo), HL
                LD   (.offsetHi), A
                LD   A, (.slotHi)
                LD   L, A
                LD   H, 0
                LD   DE, M72_STAGE_GLYPH_BYTES
                CALL M72Video_MulHLDE            ; high(slot) * glyph bytes
                LD   A, (.offsetLo + 1)
                ADD  A, L                        ; вклад результата, сдвинутый на 8
                LD   (.offsetLo + 1), A
                LD   A, (.offsetHi)
                ADC  A, H
                LD   (.offsetHi), A
                LD   HL, (.offsetLo)
                LD   BC, (M72Stage_DrawPass.baseLo)
                ADD  HL, BC
                LD   A, (.offsetHi)
                LD   C, A
                LD   A, (M72Stage_DrawPass.baseHi)
                ADC  A, C
                LD   B, #01
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE
                LD   A, (M72Stage_DrawPass.column)
                LD   (M72Video_DrawTileLayer.column), A
                CALL M72Video_ColumnX
                LD   DE, (M72Stage_DrawPass.shiftUnits)
                OR   A
                SBC  HL, DE
                LD   DE, (M72Video_DrawTileLayer.screenY)
                JP   M72Video_Vertex2f
.slotHi:        DEFB 0
.offsetLo:      DEFW 0
.offsetHi:      DEFB 0

M72StageShiftTable:
                DEFW 0, 21, 43, 64, 85, 107, 128, 149

; ---------------------------------------------------------------------------
; M72Video_FindGlyph — (код, палитра, priority group, pass) -> глиф.
;
; Оригинал берёт цвет из палитры в атрибуте; здесь палитра запечена в глиф,
; поэтому ключом служит пара. Таблица короткая (десятки записей на сцену), и
; линейный поиск дешевле, чем индекс на 4096 кодов.
;
; Вход: BC = код тайла с флагами, A = атрибут. Выход: A = номер, CF=1 если найден.
; ---------------------------------------------------------------------------
M72Video_FindGlyph:
                LD   (.attribute), A
                AND  #0F
                LD   (.palette), A
                LD   A, (.attribute)
                AND  #C0
                RLCA
                RLCA                             ; биты 6..7 -> 0..3
                LD   (.group), A
                LD   A, B
                AND  #3F                         ; код без битов отражения
                LD   B, A
                LD   (.code), BC
                LD   HL, M72GlyphLookup
                LD   A, M72_GLYPH_COUNT
                LD   (.left), A
.scan:
                LD   (.entry), HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                PUSH HL
                LD   HL, (.code)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   NZ, .miss
                LD   A, (HL)
                LD   E, A
                LD   A, (.palette)
                CP   E
                JR   NZ, .miss
                INC  HL
                LD   A, (HL)
                LD   E, A
                LD   A, (.group)
                CP   E
                JR   NZ, .miss
                INC  HL                         ; back slot
                LD   A, (M72Video_TilePass)
                OR   A
                JR   Z, .haveSlot
                INC  HL                         ; front slot
.haveSlot:      LD   A, (HL)
                CP   M72_GLYPH_SKIP
                RET  Z                           ; прозрачный — ZF=1, CF=0
                SCF
                RET
.miss:          LD   HL, (.entry)
                LD   DE, 6
                ADD  HL, DE
                LD   A, (.left)
                DEC  A
                LD   (.left), A
                JR   NZ, .scan
                XOR  A                           ; не найден — CF=0
                RET
.attribute:     DEFB 0
.palette:       DEFB 0
.group:         DEFB 0
.code:          DEFW 0
.entry:         DEFW 0
.left:          DEFB 0

; ---------------------------------------------------------------------------
; M72Video_DrawTitle — тайловый слой из VRAM за один проход.
;
; Формат и размер глифа выставляются один раз: все элементы атласа одинаковы,
; и повторять их на каждую ячейку значило бы утроить список отображения.
; Масштаб 8/5 (логические 640×480 в физические 1024×768) делает FT812 своим
; NEAREST — ровно тот же путь, что у остальных объектов порта.
; ---------------------------------------------------------------------------
M72Video_DrawTitle:
                ; Диагностика: зелёный прямоугольник в левом верхнем углу
                ; означает, что список отображения строится и сцена вызвана.
                ; Красная полоса ниже — счётчик выданных тайлов (ширина = число).
                ifdef RTYPE_TITLE_DIAG
                FT_ColorRGB 0, 255, 0
                FT_Begin FT_RECTS
                FT_Vertex2f 16, 16
                FT_Vertex2f 96, 48
                FT_End
                endif
                ; Пролог сцены: transform сбрасывается ЦЕЛИКОМ. B/D/F —
                ; глобальное состояние и протекают между сценами; ненулевой B
                ; даёт диагональный перекос, копящийся по высоте.
                FT_BitmapTransformA 160          ; логические 640 -> физические 1024
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160          ; логические 480 -> физические 768
                FT_BitmapTransformF 0
                FT_ColorRGB 255, 255, 255
                ; Семь крупных bitmap-font cells: R, точка, T, Y, P, E, TM.
                ; Z80 передаёт FT812 только cell и координаты текущего кадра.
                FT_BitmapHandle 0
                FT_BitmapLayout FT_ARGB4, M72_TITLE_FONT_STRIDE, M72_TITLE_FONT_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 172, 192
                FT_Begin FT_BITMAPS
                CALL M72Video_DrawTitleFont
                FT_End

                ; Строки меню — второй bitmap-font. Никакого обхода 48x32:
                ; поток содержит только реально видимые cell/style/X/Y.
                FT_BitmapHandle 0
                FT_BitmapLayout FT_ARGB4, M72_TITLE_TEXT_STRIDE, M72_TITLE_TEXT_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 22, 24
                FT_Begin FT_BITMAPS
                CALL M72Video_DrawTitleText
                CALL M72Video_DrawTitlePrompt
                FT_End
                ifdef RTYPE_TITLE_DIAG
                CALL M72Video_DiagBar
                endif
                RET

; Семь составных глифов логотипа. Как в Zuna DrawString, каждый глиф получает
; собственный BITMAP_SOURCE и рисуется CELL 0: так адрес ячейки не зависит от
; эмуляторной реализации шага CELL для крупных ARGB4444 bitmap.
M72Video_DrawTitleFont:
                LD   HL, (M72_SprAtlasLo)
                LD   (.sourceLo), HL
                LD   A, (M72_SprAtlasHi)
                LD   (.sourceHi), A
                LD   IX, M72TitleGlyphState
                XOR  A
                LD   (.glyph), A
.nextGlyph:     LD   A, (IX + 0)
                OR   A
                JR   Z, .advance
                LD   HL, (.sourceLo)
                LD   A, (.sourceHi)
                LD   B, #01                     ; BITMAP_SOURCE этого глифа
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE
                LD   B, #06                     ; CELL(0)
                LD   C, 0
                LD   D, 0
                LD   E, 0
                CALL FT.Coprocessor.Command_BCDE

                LD   L, (IX + 1)
                LD   H, (IX + 2)                ; native visible X
                LD   DE, 64
                CALL M72Video_MulHLDE
                LD   DE, 3
                CALL M72Video_DivHL_DE           ; x8 = X * 64/3
                PUSH HL
                LD   L, (IX + 3)
                LD   H, (IX + 4)                ; native Y
                LD   DE, 24
                CALL M72Video_MulHLDE             ; y8 = Y * 24
                EX   DE, HL
                POP  HL
                CALL M72Video_Vertex2f
.advance:       LD   HL, (.sourceLo)
                LD   DE, M72_TITLE_FONT_CELL_BYTES
                ADD  HL, DE
                LD   (.sourceLo), HL
                LD   A, (.sourceHi)
                ADC  A, 0
                LD   (.sourceHi), A
                LD   DE, 5
                ADD  IX, DE
                LD   A, (.glyph)
                INC  A
                LD   (.glyph), A
                CP   M72_TITLE_FONT_COUNT
                JR   C, .nextGlyph
                RET
.glyph:         DEFB 0
.sourceLo:      DEFW 0
.sourceHi:      DEFB 0

M72Video_DrawTitleText:
                LD   IX, M72TitleTextState
                LD   A, (M72TitleTextCount)
                LD   (.left), A
                OR   A
                RET  Z
.next:          LD   A, (IX + 1)                ; style 0=p6, 1=p14, 2=p15
                OR   A
                JR   Z, .style6
                CP   1
                JR   Z, .style14
                LD   HL, (M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES * 2) & #FFFF
                LD   A, ((M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES * 2) >> 16) & #FF
                JR   .base
.style14:       LD   HL, (M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES) & #FFFF
                LD   A, ((M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES) >> 16) & #FF
                JR   .base
.style6:        LD   HL, (M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET) & #FFFF
                LD   A, ((M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET) >> 16) & #FF
.base:          LD   (.baseLo), HL
                LD   (.baseHi), A
                LD   A, (IX + 0)
                LD   L, A
                LD   H, 0
                LD   DE, M72_TITLE_TEXT_CELL_BYTES
                CALL M72Video_MulHLDE
                LD   DE, (.baseLo)
                ADD  HL, DE
                LD   A, (.baseHi)
                ADC  A, 0
                LD   B, #01                     ; BITMAP_SOURCE глифа
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE
                LD   B, #06                     ; CELL(0)
                LD   C, 0
                LD   D, 0
                LD   E, 0
                CALL FT.Coprocessor.Command_BCDE

                LD   A, (IX + 2)
                LD   (M72Video_DrawTileLayer.column), A
                CALL M72Video_ColumnX
                PUSH HL
                LD   A, (IX + 3)
                LD   L, A
                LD   H, 0
                LD   DE, 192
                CALL M72Video_MulHLDE
                EX   DE, HL
                POP  HL
                CALL M72Video_Vertex2f
                LD   DE, 4
                ADD  IX, DE
                LD   A, (.left)
                DEC  A
                LD   (.left), A
                JR   NZ, .next
                RET
.left:          DEFB 0
.baseLo:        DEFW 0
.baseHi:        DEFB 0

; Мигающая строка Python ``PRESS FIRE`` не входит в конечный packet: после
; кадра 315 остальные логотипы и строки неподвижны, а prompt продолжает цикл
; 32 кадра видим / 32 кадра скрыт. Поэтому Z80 выбирает только фазу таймера,
; но сами девять cell и координаты всё равно лежат в готовой таблице.
M72Video_DrawTitlePrompt:
                LD   HL, (M72_TitleTimer)
                DEC  HL                          ; timer = Python frame + 1
                LD   DE, 276
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, L
                AND  63                         ; период Python: 32 on + 32 off
                LD   L, A
                LD   H, 0
                LD   DE, RTYPEPYTITLEPROMPTVISIBLE_ADDRESS
                ADD  HL, DE
                LD   A, RTYPEPYTITLEPROMPTVISIBLE_PAGE
                SetPage3_A
                LD   A, (HL)                    ; literal title.prompt_visible(frame)
                OR   A
                RET  Z
                LD   IX, M72TitlePromptState
                LD   A, 9
                LD   (.left), A
.next:          ; Все prompt-глифы используют style 1 (бирюзовый p14 atlas).
                LD   A, (IX + 0)
                LD   L, A
                LD   H, 0
                LD   DE, M72_TITLE_TEXT_CELL_BYTES
                CALL M72Video_MulHLDE
                LD   DE, (M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES) & #FFFF
                ADD  HL, DE
                LD   A, ((M72_SPRATLAS_RAMG + M72_TITLE_TEXT_BASE_OFFSET + M72_TITLE_TEXT_STYLE_BYTES) >> 16) & #FF
                ADC  A, 0
                LD   B, #01                     ; BITMAP_SOURCE готового cell
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE
                LD   B, #06                     ; CELL(0), source задаётся явно
                LD   C, 0
                LD   D, 0
                LD   E, 0
                CALL FT.Coprocessor.Command_BCDE
                LD   A, (IX + 1)                ; колонка сетки 48 символов
                LD   (M72Video_DrawTileLayer.column), A
                CALL M72Video_ColumnX
                LD   DE, 10 * 192                ; Python row 10, 15 logical px
                CALL M72Video_Vertex2f
                LD   DE, 2
                ADD  IX, DE
                LD   A, (.left)
                DEC  A
                LD   (.left), A
                JR   NZ, .next
                RET
.left:          DEFB 0

; (cell=ASCII-32, column). Пробел между PRESS и FIRE не занимает запись.
M72TitlePromptState:
                DEFB #30, 32                    ; P
                DEFB #32, 33                    ; R
                DEFB #25, 34                    ; E
                DEFB #33, 35                    ; S
                DEFB #33, 36                    ; S
                DEFB #26, 38                    ; F
                DEFB #29, 39                    ; I
                DEFB #32, 40                    ; R
                DEFB #25, 41                    ; E

; ---------------------------------------------------------------------------
; M72Video_DiagBar — красная полоса длиной в число выданных тайлов.
; Отделяет «проход не дошёл до вывода» от «вывод был, но не виден».
; ---------------------------------------------------------------------------
M72Video_DiagBar:
                FT_ColorRGB 255, 255, 0
                FT_Begin FT_RECTS
                LD   BC, 16 * 8
                LD   DE, 128 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   A, (M72Video_FirstByte)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, 16 * 8
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, 144 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                FT_ColorRGB 0, 128, 255
                FT_Begin FT_RECTS
                LD   BC, 16 * 8
                LD   DE, 96 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   A, (M72Video_SolidCount)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, 16 * 8
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, 112 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                FT_ColorRGB 255, 0, 0
                FT_Begin FT_RECTS
                LD   BC, 16 * 8
                LD   DE, 64 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   A, (M72Video_EmitCount)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; ×8 — единицы VERTEX_FORMAT 3
                LD   DE, 16 * 8
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, 80 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                RET

; ---------------------------------------------------------------------------
; Спрайты M72 — обход sprite RAM по m72_v.cpp.
;
; Запись объекта: слово 0 — Y, слово 1 — код, слово 2 — атрибут, слово 3 — X.
; Ширина и высота в ячейках берутся степенями двойки из атрибута (биты 14-15 и
; 12-13), следующая запись лежит через width*4 слова — список не однородный.
; Экранные координаты по оригиналу:
;     sx = -256 + (X & 0x3FF),  sy = 384 - (Y & 0x1FF) - 16*height
; Видимая область начинается с X=64, поэтому из sx вычитается 64.
;
; Масштаб в физический экран: 1024/384 = 8/3 по горизонтали, 768/256 = 3 по
; вертикали. Обе координаты VERTEX2F идут в 1/8 пикселя, значит
;     x8 = (sx-64) * 64/3,   y8 = sy * 24.
; ---------------------------------------------------------------------------
M72_SPRRAM_BASE     EQU #C000
M72_SPRRAM_WORDS    EQU 512          ; 1 КБ sprite RAM

M72Video_ObjCount:   DEFB 0      ; записей sprite RAM, прошедших цикл
M72Video_CellCount:  DEFB 0      ; ячеек, дошедших до выдачи

M72Video_DrawSprites:
                XOR  A
                LD   (M72Video_ObjCount), A
                LD   (M72Video_CellCount), A
                LD   HL, M72_SprRamCopy          ; обход по резидентной копии
                LD   (.entry), HL
.next:
                ; Конец списка — по указателю, одним счётчиком. Раньше позиция
                ; велась двумя независимыми величинами (номер слова и адрес), и
                ; расхождение между ними уводило обход в чужие записи.
                LD   HL, (.entry)
                LD   DE, M72_SprRamCopy + M72_SPRRAM_WORDS * 2
                OR   A
                SBC  HL, DE
                RET  NC                          ; список кончился

                LD   HL, (.entry)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.rawY), DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.code), DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.attr), DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.rawX), DE

                ; Ширина объекта в ячейках: 1 << ((attr >> 14) & 3).
                ; Атрибут читается ИЗ ПАМЯТИ: в регистре D к этому моменту
                ; старший байт X — он прочитан последним и затёр атрибут.
                ; Из-за этого ширина всегда получалась 1, обход шёл по всем 128
                ; записям с шагом в одну ячейку, а половина логотипа терялась.
                LD   A, (.attr + 1)
                RLCA
                RLCA
                AND  #03
                LD   B, A
                LD   A, 1
.widthShift:    DEC  B
                JP   M, .widthDone
                ADD  A, A
                JR   .widthShift
.widthDone:     LD   (.width), A

                LD   A, (M72Video_ObjCount)
                INC  A
                LD   (M72Video_ObjCount), A
.noLog:

                ; Пустая запись (код и атрибут нулевые) объектом не является.
                LD   HL, (.code)
                LD   A, H
                OR   L
                LD   B, A
                LD   HL, (.attr)
                LD   A, H
                OR   L
                OR   B
                JR   Z, .skipObject

                ; Высота объекта в ячейках: 1 << ((attr >> 12) & 3).
                LD   A, (.attr + 1)
                AND  #30
                RRCA
                RRCA
                RRCA
                RRCA
                LD   B, A
                LD   A, 1
.heightShift:   DEC  B
                JP   M, .heightDone
                ADD  A, A
                JR   .heightShift
.heightDone:    LD   (.height), A

                CALL M72Video_EmitSprite
.skipObject:
                ; Шаг к следующей записи: width * 4 слова. Ширина берётся ИЗ
                ; ПАМЯТИ: регистр A к этому моменту испорчен отрисовкой объекта,
                ; и обход прыгал мимо записей.
                LD   A, (.width)
                LD   B, A
                LD   HL, (.entry)
.advance:       LD   DE, 8                       ; 4 слова на ячейку ширины
                ADD  HL, DE
                DJNZ .advance
                LD   (.entry), HL
                JP   .next                       ; тело цикла длиннее ветвления JR

.entry:         DEFW 0
.rawX:          DEFW 0
.rawY:          DEFW 0
.code:          DEFW 0
.attr:          DEFW 0
.width:         DEFB 0
.height:        DEFB 0

; ---------------------------------------------------------------------------
; M72Video_EmitSprite — выдать ячейки одного объекта sprite RAM.
;
; Экранные координаты по m72_v.cpp:
;     sx = -256 + (X & 0x3FF),  sy = 384 - (Y & 0x1FF) - 16*height
; Видимая область начинается с X=64, поэтому дальше берётся sx-64.
; Перевод в физический экран: по горизонтали 1024/384 = 8/3, по вертикали
; 768/256 = 3; координаты VERTEX2F — в 1/8 пикселя, значит
;     x8 = visible_x * 64/3,   y8 = sy * 24.
; ---------------------------------------------------------------------------
M72Video_EmitSprite:
                ; sx = -256 + (X & 0x3FF)
                LD   HL, (M72Video_DrawSprites.rawX)
                LD   A, H
                AND  #03
                LD   H, A
                LD   DE, 256 + M72_RAW_VISIBLE_X
                OR   A
                SBC  HL, DE                      ; visible_x
                LD   (.visX), HL

                ; sy = 384 - (Y & 0x1FF) - 16*height
                LD   HL, (M72Video_DrawSprites.rawY)
                LD   A, H
                AND  #01
                LD   H, A
                EX   DE, HL
                LD   HL, 384
                OR   A
                SBC  HL, DE
                LD   A, (M72Video_DrawSprites.height)
                LD   B, A
.subCell:       LD   DE, 16
                OR   A
                SBC  HL, DE
                DJNZ .subCell
                LD   (.visY), HL

                ; Объект вне видимой области — пропустить. Проверяются обе оси:
                ; sx у M72 знаковый (объект может заходить за левый край), а
                ; дальше идёт беззнаковое умножение, и отрицательная координата
                ; превратилась бы в огромную — спрайт улетал за правый край.
                ; Отсечение по обеим осям с запасом на частичную видимость:
                ; объект заходит за край, и у M72 его левая/верхняя граница
                ; начинается с -16 нативных пикселей. Строгая проверка на ноль
                ; выбрасывала такие объекты целиком — на титуле это 22 ячейки
                ; из 112. Отдельные ячейки за краем отсеются ниже сами.
                ; Грубая отбраковка: объект целиком далеко за кадром. Точное
                ; отсечение идёт по каждой ячейке ниже — объект может заходить
                ; за край, и выбрасывать его целиком значит терять видимую часть.
                LD   HL, (.visY)
                LD   DE, 64
                ADD  HL, DE
                BIT  7, H
                JP   NZ, .skipAll
                LD   DE, 64 + 320
                OR   A
                SBC  HL, DE
                JP   NC, .skipAll
                LD   HL, (.visX)
                LD   DE, 64
                ADD  HL, DE
                BIT  7, H
                JP   NZ, .skipAll
                LD   DE, 64 + 448
                OR   A
                SBC  HL, DE
                JP   NC, .skipAll

                LD   A, 0
                LD   (.cellX), A
.columnLoop:
                XOR  A
                LD   (.cellY), A
.rowLoop:
                CALL M72Video_EmitSpriteCell
                LD   A, (.cellY)
                INC  A
                LD   (.cellY), A
                LD   B, A
                LD   A, (M72Video_DrawSprites.height)
                CP   B
                JR   NZ, .rowLoop
                LD   A, (.cellX)
                INC  A
                LD   (.cellX), A
                LD   B, A
                LD   A, (M72Video_DrawSprites.width)
                CP   B
                JR   NZ, .columnLoop
.skipAll:       RET
.visX:          DEFW 0
.visY:          DEFW 0
.cellX:         DEFB 0
.cellY:         DEFB 0

; Одна ячейка 16x16 объекта: код по адресации железа, позиция в 1/8 пикселя.
M72Video_EmitSpriteCell:
                ; Ячейка целиком за краем — не выдаётся. Координаты знаковые:
                ; nx = visX + cellX*16 должен лежать в 0..383, ny — в 0..255.
                LD   A, (M72Video_EmitSprite.cellX)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (M72Video_EmitSprite.visX)
                ADD  HL, DE
                BIT  7, H
                RET  NZ
                LD   DE, 384
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, (M72Video_EmitSprite.cellY)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (M72Video_EmitSprite.visY)
                ADD  HL, DE
                BIT  7, H
                RET  NZ
                LD   DE, 256
                OR   A
                SBC  HL, DE
                RET  NC

                LD   A, (M72Video_CellCount)
                INC  A
                LD   (M72Video_CellCount), A
                ; Код ячейки: шаг по горизонтали восемь кодов, по вертикали один,
                ; НО при отражении порядок ячеек зеркалится — иначе у флипнутых
                ; объектов получаются коды, которых нет в атласе, и ячейки молча
                ; выпадают (логотип рассыпался, текст без флипов стоял ровно).
                LD   A, (M72Video_DrawSprites.attr + 1)
                AND  #08                         ; бит 11 attr — flip_x
                JR   Z, .plainX
                LD   A, (M72Video_DrawSprites.width)
                DEC  A
                LD   B, A
                LD   A, (M72Video_EmitSprite.cellX)
                NEG
                ADD  A, B                        ; width-1-cellX
                JR   .haveX
.plainX:        LD   A, (M72Video_EmitSprite.cellX)
.haveX:         ADD  A, A
                ADD  A, A
                ADD  A, A                        ; ×8
                LD   C, A

                LD   A, (M72Video_DrawSprites.attr + 1)
                AND  #04                         ; бит 10 attr — flip_y
                JR   Z, .plainY
                LD   A, (M72Video_DrawSprites.height)
                DEC  A
                LD   B, A
                LD   A, (M72Video_EmitSprite.cellY)
                NEG
                ADD  A, B                        ; height-1-cellY
                JR   .haveY
.plainY:        LD   A, (M72Video_EmitSprite.cellY)
.haveY:         ADD  A, C
                LD   E, A
                LD   D, 0
                LD   HL, (M72Video_DrawSprites.code)
                ADD  HL, DE
                LD   A, H
                AND  #3F
                LD   H, A
                LD   (.cellCode), HL

                ; Поиск ячейки в таблице атласа.
                LD   HL, M72SpriteLookup
                LD   A, M72_SPRITE_COUNT
                LD   (.left), A
.scan:          LD   A, (HL)
                LD   E, A
                INC  HL
                LD   A, (HL)
                LD   D, A
                INC  HL
                INC  HL                          ; палитра здесь не различает
                LD   A, (HL)
                LD   (.slot), A
                INC  HL
                PUSH HL
                LD   HL, (.cellCode)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   Z, .found
                LD   A, (.left)
                DEC  A
                LD   (.left), A
                JR   NZ, .scan
                RET                              ; ячейки нет в атласе сцены

.found:         ; Адрес = база спрайтового атласа + номер * размер ячейки.
                ; Атлас пересекает границы 64 КБ, поэтому смещение считается
                ; полностью, как 8×16 -> 24 бита, а не только младшим словом.
                LD   A, (.slot)
                LD   DE, M72_SPRITE_BYTES
                CALL M72Video_Mul8x16_24         ; A:HL = slot * размер
                LD   B, A
                LD   A, (M72_SprAtlasHi)
                ADD  A, B
                LD   (.sourceHi), A
                LD   BC, (M72_SprAtlasLo)
                ADD  HL, BC
                LD   A, (.sourceHi)
                ADC  A, 0
                LD   B, #01
                LD   C, A
                LD   D, H
                LD   E, L
                CALL FT.Coprocessor.Command_BCDE

                ; x8 = (visible_x + cellX*16) * 64/3
                LD   A, (M72Video_EmitSprite.cellX)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; cellX*16
                LD   DE, (M72Video_EmitSprite.visX)
                ADD  HL, DE
                LD   DE, 64
                CALL M72Video_MulHLDE
                LD   DE, 3
                CALL M72Video_DivHL_DE
                PUSH HL

                ; y8 = (visible_y + cellY*16) * 24
                LD   A, (M72Video_EmitSprite.cellY)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (M72Video_EmitSprite.visY)
                ADD  HL, DE
                LD   DE, 24
                CALL M72Video_MulHLDE
                EX   DE, HL
                POP  HL
                JP   M72Video_Vertex2f
.cellCode:      DEFW 0
.slot:          DEFB 0
.sourceHi:      DEFB 0
.left:          DEFB 0

; A × DE -> A:HL (8×16, полный 24-битный результат).
M72Video_Mul8x16_24:
                LD   C, A
                LD   HL, 0
                XOR  A
                LD   B, 8
.loop:          SLA  C                           ; следующий бит множителя
                JR   NC, .zero
                ADD  HL, HL
                ADC  A, A
                ADD  HL, DE
                ADC  A, 0
                JR   .next
.zero:          ADD  HL, HL
                ADC  A, A
.next:          DJNZ .loop
                RET

; HL = HL / DE (беззнаково, сдвигово-вычитательное деление).
M72Video_DivHL_DE:
                LD   B, H
                LD   C, L
                LD   HL, 0
                LD   A, 16
.loop:          SLA  C
                RL   B
                ADC  HL, HL
                SBC  HL, DE
                JR   NC, .noAdd
                ADD  HL, DE
                DEC  C
.noAdd:         INC  C
                DEC  A
                JR   NZ, .loop
                LD   H, B
                LD   L, C
                RET
