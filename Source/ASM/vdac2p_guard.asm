; VDAC2+: защита строки FT812 — вторая страница хоста (HOST2_PAGE, вход HOST2_GUARD из FrameEmit хоста перед словами
; спрайтов через переходник Host2Check резидента). Решение пользователя 2026-09-24 «сделай»: в кадре, где строка
; развёртки FT812 не успела бы, спрайты выводятся только проходом A — из слов спрайтов уходят вершины прохода B: ячеек
; (handle-псевдонимы 8, 9) и объектов (нечётные ячейки handle классов). Записи игрока — корабль, биты, Force — не трогаются
; никогда (решение пользователя 2026-09-25, ProtectMark).
;
; Отступление на аппаратном пределе. У проходов A и B спрайта одно место: проход B несёт второе перо смешанных
; пикселей HQ (края мягче), без него края грубее, зато строки не рвутся. Так — с раскладки 2026-09-25 (пак: у
; непрозрачного пикселя спрайта главное перо в проходе A, m72_ft812_compositor.encode_cell): до неё у 38 %
; непрозрачных пикселей спрайтов тело было только в B, и в кадрах защиты спрайты выходили полыми — у v009…v011 так
; выглядели босс этапа 4, босс этапа 2 и взрывы босса этапа 1 (жалоба пользователя «большие спрайты глючат»).
; Замер ячейками (v008, модель реального
; времени, восемь этапов сценария автоогня): строка дороже 1200 тактов — в 250 кадрах (взрывы боссов этапов 1, 2, 4,
; плотные места этапа 5, до 1462). Со спрайтами объектами (v010) — до 1247, только на этапе 5; порог — 1250 (решение
; пользователя 2026-09-25 «подними до 1250»: защитный режим в сценарии не включается, запас до разрывов — 50 тактов).
;
; Цена строки — как у модели ft812_line_cost: каждое слово списка — такт на каждой строке, плюс сумма ширин примитивов
; строки / 8. Оценка = слов кадра (записанные, спрайты, хвост основной части) + кольцо фона (128) + наибольшая по
; строкам поля сумма ширин примитивов слоёв и спрайтов. Все они высотой 48 строк (объекты — 48·высота: считаются
; стопкой из 1, 2 или 4 примитивов по 48 строк) и начинаются на строке, кратной 3: сдвиг Y слоя — −(128 + sy)·3 плюс 512
; на область, вершина в области — 48·строка − 512·область; спрайты — 3i − 48 во всех окнах Y. Поэтому гистограмма по
; полосам в 3 строки точна: ширина примитива — в полосу строки начала, сумма строки — скользящим окном из 16 полос.
; Слова подпрограмм слоёв (каждая вызывается один раз) читаются обратно из RAM_DL по SPI (запись списка на это время
; закрыта), слова спрайтов — из страницы состояния. Строки панели (720…767: слой
; панели и кольцо) не считаются. Вершина прохода A идёт с двойной шириной, а вершина B сразу за ней (её пара: полосы и
; картинки — всегда, спрайты — 98 % ячеек) не разбирается; вершина B без A перед ней — со своей шириной. У объектов
; (спрайты объектами, vdac2p_objects.asm: handle 4, 5, 10, 11, 12) проход A — чётная ячейка, B — следующая нечётная.
;
; Проверка стоит ≈0,1 млн тактов и делается в кадрах от GUARD_MIN слов. Она пропускается, если прошлая оценка ниже
; порога правила, слов с тех пор прибавилось не больше его прироста, а подряд пропущено не больше его числа
; (LG_RULES): далеко от предела — реже, у предела — через кадр. После срабатывания защита держится GUARD_HOLD кадров
; вывода без проверки — края спрайтов не мигают. На тех же 35 355 кадрах: проверок 1166, ни один перегруженный кадр
; не пропущен, ложных срабатываний 30. Оценка Z80 совпала с ft812_line_cost во всех 1761 сверенных кадрах (с запасом
; хвоста основной части в 3–4 слова).
;
; Процедуры и переменные страницы хоста отсюда недоступны: вход и выход — блок GUARD_ARGS в странице состояния (окно W1):
; +0 — место слова JUMP в списке, +2 — DL_SENT (запись списка SPI открыта там), +4 — байт слов спрайтов (на выходе — без
; вершин прохода B, если защита сработала). Прерывания выключены: слова разбираются POP, гистограмма чистится PUSH.

                IFDEF RTYPE_GUARD_ALWAYS
; Диагностическая сборка (в релизный SPG не входит): защита в каждом кадре со спрайтами — вид спрайтов без прохода B
; на всех этапах (сверка раскладки проходов пака против эталона).
GUARD_LIMIT     EQU 1
GUARD_MIN       EQU 1
GUARD_RULES_ON  EQU 0                   ; пороги правил пропуска (LG_RULES) — 0: проверка в каждом кадре
                ELSE
GUARD_LIMIT     EQU 1250                ; тактов строки FT812 по модели; разрывы на плате — от ≈1300 (до 25.09 — 1200)
GUARD_MIN       EQU 320                 ; слов кадра меньше — строка не перегружена: со спрайтами объектами (25.09) у
                                        ; кадров дороже 1100 тактов — от 354 слов, дороже 1200 — от 369 (ячейками — от 464)
GUARD_RULES_ON  EQU 1                   ; пороги правил пропуска проверки (LG_RULES) — от предела
                ENDIF
GUARD_RING      EQU 128                 ; кольцо фона: 1024 пикселя на каждой строке — 128 тактов
GUARD_TAIL      EQU 10                  ; слов основной части после спрайтов: ножницы и CALL прохода 1, DISPLAY
GUARD_HOLD      EQU 4                   ; кадров вывода защиты без проверки после срабатывания
GUARD_Y0        EQU 2048                ; LG_DIV3[строка + 48 + GUARD_Y0]: строки −2096…2047
GUARD_FIELD     EQU 720                 ; строк поля (ниже — панель)

; Вход HOST2_GUARD. Сохраняет IX, IY; портит остальное.
LineGuard:      push ix
                push iy
                call .run
                pop iy
                pop ix
                ret
.run:           ld hl,(GUARD_ARGS+4)
                ld a,h
                or l
                ret z                           ; спрайтов нет — выбрасывать нечего
                ld de,(GUARD_ARGS+2)
                add hl,de
                srl h
                rr l
                srl h
                rr l
                ld de,GUARD_TAIL
                add hl,de
                ld (LG_COMMANDS),hl             ; слов списка кадра
                ld a,(LG_HOLD)
                or a
                jr z,.noHold
                dec a
                ld (LG_HOLD),a
                jp LgDrop                       ; удержание после срабатывания — без проверки
.noHold:        ld de,-GUARD_MIN
                add hl,de
                jr c,.candidate
                xor a
                ld (LG_VALID),a                 ; слов мало — строка не перегружена, прошлая оценка — не в счёт
                ret
.candidate:     ld a,(LG_VALID)
                or a
                jr z,.full
                ld ix,LG_RULES
                ld b,LG_RULES_COUNT
.rule:          ld hl,(LG_LAST_E)
                ld e,(ix+0)
                ld d,(ix+1)
                or a
                sbc hl,de
                jr nc,.nextRule                 ; прошлая оценка не ниже порога правила
                ld hl,(LG_LAST_C)
                ld e,(ix+2)
                ld d,0
                add hl,de
                ld de,(LG_COMMANDS)
                or a
                sbc hl,de
                jr c,.nextRule                  ; слов прибавилось больше прироста правила
                ld a,(ix+3)
                ld hl,LG_SINCE
                cp (hl)
                jr nc,.skip                     ; подряд пропущено не больше числа правила
.nextRule:      ld de,4
                add ix,de
                djnz .rule
                jr .full
.skip:          inc (hl)
                ret                             ; проверка пропущена — защиты нет
.full:          call LgClear
                call LgLayers
                call LgSprites
                jr c,.force                     ; буфер спрайтов почти полон — кадр заведомо тяжёлый
                call LgWindow                   ; HL — наибольшая по строкам поля сумма ширин, пикселей
.estimated:     srl h                           ; (метка — точка сверки гистограммы в модели, RT_GUARDHIST)
                rr l
                srl h
                rr l
                srl h
                rr l                            ; тактов
                ld de,(LG_COMMANDS)
                add hl,de
                ld de,GUARD_RING
                add hl,de                       ; HL — оценка худшей строки
                ld (LG_LAST_E),hl
                ld de,(LG_COMMANDS)
                ld (LG_LAST_C),de
                xor a
                ld (LG_SINCE),a
                inc a
                ld (LG_VALID),a
                ld de,-GUARD_LIMIT-1
                add hl,de
                ret nc                          ; не дороже GUARD_LIMIT
.force:         ld a,GUARD_HOLD
                ld (LG_HOLD),a
                ; дальше — LgDrop

; Вершины прохода B спрайтов — вон из слов спрайтов (окно W1), новая длина — в GUARD_ARGS+4: VERTEX2II (байт 3 —
; #80…#BF) ячеек — handle 8, 9 (в байте 1 биты 3…0 — handle >> 1 = 4) и объектов — handle 4, 5, 10, 11, 12 (handle >> 1 —
; 2, 5, 6) с нечётной ячейкой (бит 0 байта 0). Слова записей игрока — корабль, биты, Force (ProtectMark,
; vdac2p_sprites.asm: первые в буфере, до PROTECT_END) — не трогаются никогда (решение пользователя 2026-09-25).
; Портит всё.
LgDrop:         ld a,(PROTECT_OPEN)
                or a
                ret nz                          ; все слова кадра — игрока
                ld hl,(PROTECT_END)
                ld de,#4000+SPRITE_WORDS
                or a
                sbc hl,de                       ; HL — байт слов игрока
                ex de,hl
                ld hl,(GUARD_ARGS+4)
                or a
                sbc hl,de                       ; HL — байт слов за ними
                ret c
                ret z
                srl h
                rr l
                srl h
                rr l
                ld b,h
                ld c,l                          ; BC — слов спрайтов за словами игрока
                ld hl,(PROTECT_END)             ; откуда
                ld d,h
                ld e,l                          ; куда
.word:          push bc
                inc hl
                ld c,(hl)                       ; байт 1
                inc hl
                inc hl
                ld a,(hl)                       ; байт 3
                dec hl
                dec hl
                dec hl
                and #C0
                cp #80
                jr nz,.keep                     ; не VERTEX2II
                ld a,c
                and #0F
                cp 4
                jr z,.skip                      ; handle 8, 9 — проход B ячейки
                cp 2
                jr z,.object
                cp 5
                jr z,.object
                cp 6
                jr nz,.keep
.object:        bit 0,(hl)
                jr nz,.skip                     ; нечётная ячейка handle объекта — проход B
.keep:          ldi
                ldi
                ldi
                ldi
                jr .next
.skip:          inc hl
                inc hl
                inc hl
                inc hl
.next:          pop bc
                dec bc
                ld a,b
                or c
                jr nz,.word
                ex de,hl
                ld de,#4000+SPRITE_WORDS
                or a
                sbc hl,de
                ld (GUARD_ARGS+4),hl
                ret

; Гистограмма LG_WL/LG_WH (младшие и старшие байты сумм ширин по индексу полосы начала) — нули, стеком. Портит AF, B,
; HL.
LgClear:        ld (LG_SP),sp
                ld sp,LG_WH+256
                ld hl,0
                ld b,32
.push:          push hl
                push hl
                push hl
                push hl
                push hl
                push hl
                push hl
                push hl
                djnz .push                      ; 32·16 байт
                ld sp,(LG_SP)
                ret
                ASSERT LG_WH == LG_WL+256

; Слова подпрограмм слоёв — чтением RAM_DL по SPI: с места слова JUMP (его поле — номер первой команды основной части)
; до основной части, пачками по 64 слова в LG_BUF (за пачкой — слово-граница с байтом 3 = #FF), разбор LgParse. Запись
; списка на время чтения закрыта, на выходе снова открыта на DL_SENT. Портит всё.
LgLayers:       ld hl,LG_DIV3+GUARD_Y0+48
                ld (LG_BASE),hl                 ; сдвиг Y 0 до первого VERTEX_TRANSLATE_Y
                ld a,FT_CS_OFF
                out (SPI_CTRL),a                ; запись списка — закрыть
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,#30
                out (SPI_DATA),a                ; RAM_DL, чтение
                ld de,(GUARD_ARGS)
                ld a,d
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                out (SPI_DATA),a                ; пустой байт после адреса
                in a,(SPI_DATA)                 ; пустое чтение
                ld c,SPI_DATA
                in l,(c)
                in h,(c)                        ; номер первой команды основной части
                in a,(c)
                in a,(c)
                srl d
                rr e
                srl d
                rr e
                inc de                          ; номер первого слова подпрограмм
                or a
                sbc hl,de                       ; HL — слов подпрограмм
                jr c,.close
.chunk:         ld a,h
                or l
                jr z,.close
                ld de,64
                or a
                sbc hl,de
                ld b,0                          ; 64 слова — 256 байт
                jr nc,.read
                add hl,de                       ; осталось меньше 64 слов
                ld a,l
                add a,a
                add a,a
                ld b,a
                ld hl,0
.read:          push hl                         ; слов после пачки
                ld hl,LG_BUF
                ld c,SPI_DATA
                inir
                ; Пачка не рвёт пару: кончилась вершиной A полосы или картинки (handle 0, 1 — пара B у неё всегда следом) —
                ; её B дочитывается в ту же пачку. Иначе B в начале следующей пачки считалась бы отдельной вершиной (+172
                ; пикселя картинки в полосу; сверка RT_GUARDHIST, 25.09.2026).
                pop de                          ; DE — слов после пачки
                ld a,d
                or e
                jr z,.bound                     ; пачка последняя
                dec hl
                ld a,(hl)                       ; байт 3 последнего слова
                inc hl
                and #C0
                cp #80
                jr nz,.bound                    ; не VERTEX2II
                dec hl
                dec hl
                dec hl
                ld a,(hl)                       ; байт 1: биты 3…0 — handle >> 1
                inc hl
                inc hl
                inc hl
                and #0F
                jr nz,.bound                    ; не handle 0, 1
                ld b,4
                inir                            ; пара B — в эту пачку
                dec de
.bound:         push de
                ld a,#FF
                ld (hl),a
                inc hl
                ld (hl),a
                inc hl
                ld (hl),a
                inc hl
                ld (hl),a                       ; слово-граница
                ld hl,LG_BUF
                call LgParse
                pop hl
                jr .chunk
.close:         ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,#B0                        ; RAM_DL, запись (как FtOpenWrite хоста)
                out (SPI_DATA),a
                ld hl,(GUARD_ARGS+2)
                ld a,h
                out (SPI_DATA),a
                ld a,l
                out (SPI_DATA),a
                ret

; Слова спрайтов (страница состояния, окно W1): за ними — слово-граница, разбор LgParse; CF = 0. Слово-граница легла
; бы за страницу (буфер почти полон — за последней ячейкой ещё сброс матрицы) — разбора нет, CF = 1. Портит всё.
LgSprites:      ld hl,LG_DIV3+GUARD_Y0+48
                ld (LG_BASE),hl
                ld hl,(GUARD_ARGS+4)
                ld de,#4000+SPRITE_WORDS
                add hl,de
                ld a,h
                cp high #7FFC
                jr c,.room
                ld a,l
                cp low #7FFC
                jr c,.room
                scf                             ; слово-граница легла бы в окно W2
                ret
.room:          ld a,#FF
                ld (hl),a
                inc hl
                ld (hl),a
                inc hl
                ld (hl),a
                inc hl
                ld (hl),a                       ; слово-граница за словами спрайтов
                ex de,hl
                call LgParse
                or a
                ret

; Разбор слов с HL до слова с байтом 3 = #FF (POP: L — байт 0, H — байт 1, E — байт 2, D — байт 3). VERTEX_TRANSLATE_Y
; — база LG_BASE (LG_DIV3 + GUARD_Y0 + 48 + сдвиг в пикселях); VERTEX2II — ширина по handle (LG_WIDTH: у прохода A —
; двойная, пара B следом пропускается) в полосу строки начала. Строка прошлой вершины (IXH — байт 2 & #1F, IXL —
; байт 1 & #F0, IYL — индекс полосы) заново не считается: картинки и полосы одной строки. Портит всё, IX, IY.
LgParse:        ld (LG_SP),sp
                ld sp,hl
                ld ix,#FFFF                     ; прошлой вершины нет
.word:          pop hl
                pop de
.classify:      ld a,d
                and #C0
                cp #80
                jr z,.vertex
                ld a,d
                cp #2C
                jr z,.translate
                inc a
                jr nz,.word                     ; прочие команды
                ld sp,(LG_SP)                   ; слово-граница
                ret
.translate:     ; 1/16 пикселя, 17 бит со знаком (бит 16 — бит 0 байта 2) → пиксели (13 бит со знаком)
                ld a,e
                and 1
                ld d,a
                srl d
                rr h
                rr l
                srl d
                rr h
                rr l
                srl d
                rr h
                rr l
                srl d
                rr h
                rr l
                ld a,h
                bit 4,a
                jr z,.plus
                or #E0
                ld h,a                          ; знак — в биты 13…15
.plus:          ld de,LG_DIV3+GUARD_Y0+48
                add hl,de
                ld (LG_BASE),hl
                ld ix,#FFFF                     ; строки вершин — заново
                jr .word
.vertex:        ld a,l
                ld (LG_OBJ0),a                  ; байт 0 (у объекта бит 0 — проход B): в памяти — .newY портит DE
                ld a,h
                and #0F
                rl l
                rla
                ld iyh,a                        ; IYH — handle: (байт 1 & #0F)·2 + бит 7 байта 0
                ld a,h
                and #F0
                ld c,a                          ; C — (y & 15) << 4
                ld a,e
                and #1F
                ld e,a                          ; E — y >> 4
                cp ixh
                jr nz,.newY
                ld a,c
                cp ixl
                jr nz,.newY
                ld a,iyl                        ; строка прошлой вершины
                jr .add
.newY:          ld ixh,e
                ld ixl,c
                ld a,c
                rrca
                rrca
                rrca
                rrca                            ; y & 15
                ld l,e
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                or l
                ld l,a                          ; HL — y (0…511)
                ld de,(LG_BASE)
                add hl,de
                ld a,(hl)                       ; индекс полосы начала: 1…255, вне поля — 0
                ld iyl,a
.add:           ld e,a                          ; E — индекс полосы
                ld a,iyh
                ld l,a
                ld h,high LG_WIDTH
                ld c,(hl)                       ; C — ширина, младший байт
                inc h
                ld b,(hl)                       ; B — старший; бит 7 — проход B, бит 6 — объект
                bit 6,b
                jr nz,.object
                ld l,e
                ld h,high LG_WL
                ld a,(hl)
                add a,c
                ld (hl),a
                inc h
                ld a,b
                res 7,a                         ; флаги — от сложения младших байтов
                adc a,(hl)
                ld (hl),a
                bit 7,b
                jp nz,.word                     ; проход B без A перед ним — своя ширина, дальше обычный разбор
                ; проход A (ширина двойная): вершина B сразу за ним — его пара, не разбирается
                pop hl
                pop de
                ld a,d
                and #C0
                cp #80
                jp nz,.classify
                ld a,h
                and #0F
                cp 1
                jp z,.word                      ; handle 2, 3 — проход B полосы или картинки
                cp 4
                jp z,.word                      ; handle 8, 9 — проход B ячейки спрайта
                jp .vertex
.object:        ; объект: C — ширина прохода, B — #40 | примитивов по 48 строк (1, 2, 4); у прохода A (чётная ячейка) ширина
                ; двойная — вершина B следом (ячейка + 1 того же handle) не разбирается. Индекс полосы каждого примитива — по
                ; строке его начала (LG_DIV3; объект выше поля начинается выше строки −48, его нижние примитивы видны), y
                ; вершины — из кэша строки (IXH — y >> 4, IXL — (y & 15) << 4).
                ld a,(LG_OBJ0)
                rrca
                jr c,.objectB
                sla c                           ; проход A с парой B (ширина объекта меньше 128)
.objectB:       ld a,b
                and 7
                ld b,a                          ; B — примитивов
                ld a,ixl
                rrca
                rrca
                rrca
                rrca
                ld e,a                          ; y & 15
                ld a,ixh
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                ld a,l
                or e
                ld l,a                          ; HL — y (0…511)
                ld de,(LG_BASE)
                add hl,de                       ; HL → LG_DIV3[строка начала + 48 + GUARD_Y0]
                ; Стек здесь — указатель разбора (POP по словам): ни PUSH, ни CALL — они затёрли бы только что
                ; прочитанное слово.
.segment:       ld e,(hl)                       ; индекс полосы начала примитива (0 — вне поля: окно его не берёт)
                ld d,high LG_WL
                ld a,(de)
                add a,c
                ld (de),a
                inc d
                ld a,(de)
                adc a,0
                ld (de),a
                ld a,l
                add a,48
                ld l,a                          ; следующий примитив — на 48 строк ниже
                jr nc,.segmentNext
                inc h
.segmentNext:   djnz .segment
                ld a,(LG_OBJ0)
                bit 0,a
                jp nz,.word                     ; проход B без A перед ним — дальше обычный разбор
                inc a
                ld c,a                          ; C — байт 0 пары B (ячейка + 1)
                pop hl
                pop de
                ld a,d
                and #C0
                cp #80
                jp nz,.classify
                ld a,l
                cp c
                jp nz,.vertex
                ld a,iyh
                srl a
                ld b,a
                ld a,h
                and #0F
                cp b
                jp z,.word                      ; пара B объекта
                jp .vertex

; Наибольшая по строкам поля сумма ширин: полоса строк b (0…239) — сумма окна полос начала b + 1…b + 16 (индекс =
; строка начала / 3 + 16: примитив в 48 строк задевает 16 полос). Полоса начала без примитивов сумму не растит —
; наибольшую не сверяем. Выход: HL. Портит всё, IX.
LgWindow:       ld de,0                         ; DE — сумма окна
                ld ix,0                         ; IX — наибольшая
                ld hl,LG_WL+1
                ld b,15
.fill:          ld a,(hl)
                add a,e
                ld e,a
                inc h
                ld a,(hl)
                adc a,d
                ld d,a
                dec h
                inc l
                djnz .fill
                ld bc,LG_WL+1                   ; BC — уходящая полоса начала (L − 15)
.slide:         ld a,(hl)                       ; L — входящая полоса начала (16…255: строки поля 0…719)
                inc h
                or (hl)
                jr z,.leave                     ; W[L] = 0
                dec h
                ld a,(hl)
                add a,e
                ld e,a
                inc h
                ld a,(hl)
                adc a,d
                ld d,a                          ; сумма += W[L]
                ld a,e
                sub ixl
                ld a,d
                sbc a,ixh
                jr c,.leave
                ld ixl,e
                ld ixh,d
.leave:         dec h
                ld a,(bc)
                cpl
                scf
                adc a,e
                ld e,a
                inc b
                ld a,(bc)
                cpl
                adc a,d
                ld d,a
                dec b                           ; сумма −= W[C]: окно следующей полосы строк
                inc c
                inc l
                jr nz,.slide
                push ix
                pop hl
                ret
                ASSERT GUARD_FIELD/3+16 == 256

; Пропуск проверки (LineGuard): прошлая оценка ниже порога, слов прибавилось не больше прироста, пропущено подряд не
; больше числа — правила по возрастанию порога (замер: те же 35 355 кадров — ни одного пропущенного перегруженного).
LG_RULES:       DW (GUARD_LIMIT-150)*GUARD_RULES_ON
                DB 8, 6                         ; далеко от предела — проверка раз в 8 кадров
                DW (GUARD_LIMIT-60)*GUARD_RULES_ON
                DB 8, 2                         ; раз в 4
                DW GUARD_LIMIT*GUARD_RULES_ON
                DB 4, 0                         ; у предела — через кадр
LG_RULES_COUNT  EQU ($-LG_RULES)/4

LG_SP           DW 0
LG_BASE         DW 0                    ; LG_DIV3 + GUARD_Y0 + 48 + сдвиг Y (пиксели)
LG_COMMANDS     DW 0
LG_LAST_E       DW 0                    ; оценка последней проверки
LG_LAST_C       DW 0                    ; слов кадра последней проверки
LG_SINCE        DB 0                    ; кадров с пропущенной проверкой подряд
LG_VALID        DB 0                    ; прошлая оценка годна для пропуска
LG_HOLD         DB 0                    ; кадров удержания защиты
LG_OBJ0         DB 0                    ; байт 0 вершины объекта
LG_BUF          DS 64*4+8               ; пачка слов подпрограмм (64 и, может быть, пара B последней вершины A),
                                        ; слово-граница

                ALIGN 256
LG_WL           DS 256                  ; суммы ширин по индексу полосы начала: младшие байты
LG_WH           DS 256                  ; старшие байты
; Ширина битмапа по handle (пикселей экрана, как BITMAP_SIZE v30z80_video_assets.dl_handles): полосы 23, картинки
; 172, ячейки спрайтов 44. У прохода A (handle 0, 1, 6, 7) — двойная (с парой B), у прохода B (2, 3, 8, 9) — одинарная, бит 7
; старшего байта — признак прохода B. Объекты (handle 4, 5, 10, 11, 12: 2×4, 2×2, 1×4, 2×1, 1×2) — ширина прохода
; (87 у ширины 2, 44 у ширины 1), в старшем байте #40 | примитивов по 48 строк (высота объекта в ячейках); проход — по
; чётности ячейки (.object). Прочих handle в словах слоёв и спрайтов нет.
LG_WIDTH:       DB low 46, low 344, 23, 172, 87, 87, 88, 88, 44, 44, 44, 87, 44
                DS 256-13
LG_WIDTH_H:     DB high 46, high 344, #80, #80, #44, #42, high 88, high 88, #80, #80, #44, #41, #42
                DS 32-13
                ASSERT low LG_WIDTH == 0 && LG_WIDTH_H == LG_WIDTH+256
                ASSERT STRIP_HANDLE_B == 2 && IMAGE_HANDLE_B == 3 && SPRITE_HANDLE0 == 6 && SPRITE_HANDLE_B == 8
                ASSERT OBJ_HANDLE0 == 5 && OBJ_HANDLE1 == 4 && OBJ_HANDLE2 == 11 && OBJ_HANDLE3 == 12 && OBJ_HANDLE4 == 10
; Индекс полосы начала по строке: LG_DIV3[строка + 48 + GUARD_Y0] = (строка + 48) / 3 для строк −48…719, иначе 0
; (полоса −16: ни в одно окно поля не входит).
LG_DIV3:
lg_div3_n = 0
                DUP 4096
                IF lg_div3_n >= GUARD_Y0 && lg_div3_n < GUARD_Y0+GUARD_FIELD+48
                DB (lg_div3_n-GUARD_Y0)/3
                ELSE
                DB 0
                ENDIF
lg_div3_n = lg_div3_n + 1
                EDUP
