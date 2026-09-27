; VDAC2+: надпись скорости мыши — «Mouse speed: 1x» или «Mouse speed: 0,5x» в правом нижнем углу, около трёх секунд
; после переключения. Отступление от оригинала по решению пользователя 2026-09-27: «Нужно немного отступить от
; оригинала: в игре в правом нижнем углу писать (например ROM шрифтом) Mouse speed: 1x или 0,5x», «пусть надпись
; держится не всё время, а около трёх секунд после переключения скорости мыши». У аркады мыши нет: чувствительность
; (1 ↔ 1/2) переключает средняя кнопка Kempston Mouse в оболочке p2c (p2c_z80_runtime_cold.c), машине она приходит
; битом 2 флагов шага (API_FLAGS резидента, p2c_port_step).
;
; Модуль — в свободной части звуковой страницы (SOUND_PAGE, окно W3 на время вызова): в страницах хоста места нет.
; Вход SOUND_ENTRY_LABEL — из FrameEmit хоста (переходник LabelCall резидента) после DISPLAY кадра: слова надписи
; дописываются в RAM_DL на место DISPLAY (DL_LAST хоста) и кончаются своим DISPLAY, DL_LAST сдвигается за них —
; затемнение HostVideoFade ляжет поверх. Места до DL_LIMIT нет — кадр без надписи. Переменные хоста — через окно W2
; (страница хоста в #8000). Надпись бывает только в кадрах вывода машины (демо и игра): переключение на титуле
; оболочки видно с первого такого кадра.
;
; Шрифт — ПЗУ FT812, как у надписи загрузчика SPG (handle ML_FONT; ширины знаков — из таблицы метрик ПЗУ: указатель
; в #2FFFFC, блок шрифта — 148 байт с номера 16). Знак — одно слово VERTEX2II (handle и знак в самом слове) со
; сдвигом VERTEX_TRANSLATE: у VERTEX2II координаты до 511. Матрица — единичная, ставится целиком (глифы шрифта —
; битмап: под матрицей масштаба кадра они рвутся), ножницы — весь экран. Слова собираются при переключении (MlBuild),
; в кадре — только запись в SPI. Цена строки FT812 — такт на слово на каждой строке: надпись — 27…29 слов, тени нет
; (панель под надписью чёрная), чтобы худшая строка игры (1247 тактов, этап 5) осталась ниже потолка ~1300.

ML_FONT         EQU 28                          ; ПЗУ-шрифт FT812 (handle 16…31 — шрифты ПЗУ с включения)
ML_RIGHT        EQU 1024-16                     ; правый край надписи, физические пиксели 1024×768
ML_TOP          EQU 730                         ; верх строки шрифта: низ знаков — на уровне нижней строки панели
                ifdef RTYPE_LABEL_TEST
; Диагностика (в релизный SPG не входит): надпись с первого кадра вывода машины и надолго — проверка шрифта и места в
; Unreal без средней кнопки мыши; с RTYPE_LABEL_HALF бит скорости читается наоборот — строка «0,5x».
ML_FRAMES       EQU 30000
                else
ML_FRAMES       EQU 177                         ; показ — ≈3 с кадров развёртки FT812 (59,08 Гц)
                endif
ML_DX           EQU 512                         ; начало координат VERTEX2II (VERTEX_TRANSLATE)
ML_DY           EQU 256
ML_HALF_BIT     EQU 4                           ; бит флагов шага: чувствительность мыши 1/2
ML_ROM_FONTS    EQU #2FFFFC                     ; указатель таблицы шрифтов ПЗУ FT812
ML_Y            EQU ML_TOP-ML_DY                ; y знаков в координатах VERTEX2II
                ASSERT ML_Y >= 0 && ML_Y < 512 && ML_RIGHT-ML_DX < 512
; Байты 1 и 2 слова VERTEX2II(x, y, handle, знак) = 2 << 30 | x << 21 | y << 12 | handle << 7 | знак: байт 1 — handle
; >> 1 и биты 0…3 y, байт 2 — биты 4…8 y и биты 0…2 x (их добавляет MlBuild).
ML_BYTE1        EQU ((ML_FONT>>1)&15)|((ML_Y&15)<<4)
ML_BYTE2        EQU (ML_Y>>4)&#1F
                ASSERT (ML_FONT&1) == 0                 ; младший бит handle — бит 7 байта 0: у знаков ASCII он 0

; --- кадр ---------------------------------------------------------------------------------------------------------------
; Переключение (бит флагов не как в прошлом кадре вывода) — слова новой надписи и показ до ML_UNTIL. Показ идёт —
; слова в RAM_DL за DL_LAST. Портит всё, окно W2.
MouseLabel:     ld a,(API_FLAGS)
                and ML_HALF_BIT
                ifdef RTYPE_LABEL_HALF
                xor ML_HALF_BIT
                endif
                ld hl,ML_HALF
                cp (hl)
                jr z,.same
                ld (hl),a
                call MlBuild
                call MlFrames
                ld de,ML_FRAMES
                add hl,de
                ld (ML_UNTIL),hl
                ld a,1
                ld (ML_ON),a
.same:          ld a,(ML_ON)
                or a
                ret z
                call MlFrames
                ld de,(ML_UNTIL)
                or a
                sbc hl,de
                jp m,.show                      ; срок ещё не вышел (разность кадров со знаком)
                xor a
                ld (ML_ON),a
                ret
.show:          ld a,HOST_PAGE
                ld bc,PORT_PAGE2
                out (c),a                       ; переменные хоста — в окне W2
                ld de,(DL_LAST-#4000)           ; место DISPLAY кадра
                ld hl,(ML_BYTES)
                add hl,de                       ; место DISPLAY за надписью
                ld bc,DL_LIMIT+1
                or a
                sbc hl,bc
                ret nc                          ; за пределом DL_LIMIT — кадр без надписи
                add hl,bc
                ld (DL_LAST-#4000),hl           ; затемнение — за надписью
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,#B0                        ; запись с адреса #30xxxx — RAM_DL
                out (SPI_DATA),a
                ld a,d
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                ld hl,ML_WORDS
                ld a,(ML_BYTES)
                ld b,a
                ld c,SPI_DATA
                otir                            ; порт SPI — по младшему байту адреса
                xor a
                out (SPI_DATA),a
                out (SPI_DATA),a
                out (SPI_DATA),a
                out (SPI_DATA),a                ; DISPLAY
                ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ret

; --- слова надписи ------------------------------------------------------------------------------------------------------
; Для скорости ML_HALF: ширины знаков шрифта ML_FONT из ПЗУ FT812, строка выравнивается по правому краю ML_RIGHT; слова
; ML_HEAD и по слову VERTEX2II на знак → ML_WORDS, их байт — ML_BYTES. Портит всё.
MlBuild:        ld a,ML_ROM_FONTS >> 16
                ld de,ML_ROM_FONTS & #FFFF
                ld hl,ML_WIDTHS
                ld b,3
                call MlRead                     ; адрес таблицы шрифтов (биты 23…0)
                ld hl,(ML_WIDTHS)
                ld de,148*(ML_FONT-16)
                add hl,de
                ex de,hl                        ; DE — младшие 16 бит блока шрифта
                ld a,(ML_WIDTHS+2)
                adc a,0                         ; A — биты 23…16 (перенос сложения)
                ld hl,ML_WIDTHS
                ld b,128
                call MlRead                     ; ширины знаков 0…127
                ld hl,ML_TEXT_1X
                ld a,(ML_HALF)
                or a
                jr z,.text
                ld hl,ML_TEXT_HALF
.text:          ld (ML_TEXT),hl
                ld bc,0                         ; BC — ширина строки
.width:         ld a,(hl)
                or a
                jr z,.words
                inc hl
                call MlWidth
                add a,c
                ld c,a
                jr nc,.width
                inc b
                jr .width
.words:         ld hl,ML_RIGHT-ML_DX
                or a
                sbc hl,bc                       ; HL — x первого знака (координаты VERTEX2II)
                push hl
                ld hl,ML_HEAD
                ld de,ML_WORDS
                ld bc,ML_HEAD_END-ML_HEAD
                ldir                            ; сдвиг, ножницы, матрица, BEGIN, белый
                pop hl
                ld bc,(ML_TEXT)
.glyph:         ld a,(bc)
                or a
                jr z,.done
                inc bc
                ld (de),a                       ; байт 0: знак
                inc de
                push af
                ld a,ML_BYTE1
                ld (de),a                       ; байт 1: handle >> 1, биты 0…3 y
                inc de
                ld a,l
                rrca
                rrca
                rrca
                push af                         ; биты 3…7 x — в 0…4, биты 0…2 — в 5…7
                and #E0
                or ML_BYTE2
                ld (de),a                       ; байт 2: биты 4…8 y, биты 0…2 x
                inc de
                pop af
                and #1F
                bit 0,h
                jr z,.x8
                or #20                          ; бит 8 x
.x8:            or #80
                ld (de),a                       ; байт 3: 2 << 6 | биты 3…8 x
                inc de
                pop af
                push de
                call MlWidth
                ld e,a
                ld d,0
                add hl,de                       ; x += ширина знака
                pop de
                jr .glyph
.done:          ex de,hl
                ld de,ML_WORDS
                or a
                sbc hl,de
                ld (ML_BYTES),hl
                ret

; Ширина знака A → A. Портит DE.
MlWidth:        push hl
                ld e,a
                ld d,0
                ld hl,ML_WIDTHS
                add hl,de
                ld a,(hl)
                pop hl
                ret

; REG_FRAMES (младшие 16 бит) → HL. Портит AF.
MlFrames:       ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,REG_FRAMES >> 16           ; адрес чтения: старшие 6 бит, биты 7, 6 = 0
                out (SPI_DATA),a
                ld a,(REG_FRAMES >> 8) & #FF
                out (SPI_DATA),a
                ld a,REG_FRAMES & #FF
                out (SPI_DATA),a
                out (SPI_DATA),a                ; пустой байт после адреса
                in a,(SPI_DATA)                 ; пустое чтение
                in a,(SPI_DATA)
                ld l,a
                in a,(SPI_DATA)
                ld h,a
                ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ret

; B байт памяти FT812 с адреса A:DE (A — биты 21…16) → (HL). Портит AF, B, HL.
MlRead:         push af
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                pop af
                out (SPI_DATA),a
                ld a,d
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                out (SPI_DATA),a                ; пустой байт после адреса
                in a,(SPI_DATA)                 ; пустое чтение
.byte:          in a,(SPI_DATA)
                ld (hl),a
                inc hl
                djnz .byte
                ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ret

; Состояние графики перед знаками: после основного прохода хоста сдвиг, ножницы, матрица и цвет могут быть любыми.
ML_HEAD:        DD #2B000000|(ML_DX*16)         ; VERTEX_TRANSLATE_X (1/16 пикселя)
                DD #2C000000|(ML_DY*16)         ; VERTEX_TRANSLATE_Y
                DD #1B000000                    ; SCISSOR_XY 0,0
                DD #1C400300                    ; SCISSOR_SIZE 1024,768
                DD #15000100                    ; BITMAP_TRANSFORM_A 256 — матрица единичная, целиком
                DD #16000000                    ; BITMAP_TRANSFORM_B 0
                DD #17000000                    ; BITMAP_TRANSFORM_C 0
                DD #18000000                    ; BITMAP_TRANSFORM_D 0
                DD #19000100                    ; BITMAP_TRANSFORM_E 256
                DD #1A000000                    ; BITMAP_TRANSFORM_F 0
                DD #1F000001                    ; BEGIN BITMAPS
                DD #04FFFFFF                    ; COLOR_RGB 255,255,255
ML_HEAD_END:
ML_TEXT_1X:     DB "Mouse speed: 1x",0
ML_TEXT_HALF:   DB "Mouse speed: 0,5x",0
ML_MAX_BYTES    EQU ML_HEAD_END-ML_HEAD+4*17
                ASSERT ML_MAX_BYTES < 256               ; OTIR — до 255 байт
                ifdef RTYPE_LABEL_TEST
ML_HALF         DB #FF                          ; диагностика: «переключение» в первом кадре вывода
                else
ML_HALF         DB 0                            ; бит скорости прошлого кадра вывода (при запуске — 1)
                endif
ML_ON           DB 0                            ; надпись показывается
ML_UNTIL        DW 0                            ; кадр развёртки конца показа (младшие 16 бит REG_FRAMES)
ML_TEXT         DW 0                            ; строка надписи
ML_BYTES        DW 0                            ; байт в ML_WORDS
ML_WIDTHS       DS 128                          ; ширины знаков ПЗУ-шрифта ML_FONT
ML_WORDS        DS ML_MAX_BYTES                 ; слова надписи
