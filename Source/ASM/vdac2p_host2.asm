; VDAC2+: вторая страница хоста (HOST2_PAGE, окно #C000 на время вызова из хоста через переходники резидента —
; vdac2p_early.asm; в резиденте и странице хоста места нет). Против средних затыков (решение пользователя 2026-09-23
; «делай» на переделку перестройки групп): ранняя сборка строк групп переднего слоя по предсказанной полосе карты.
; Ранней подгрузки ячеек тайлов здесь больше нет (была 23.09): она выбивала горячие ячейки из пула 96 (круг без учёта
; обращений) — повторных подгрузок втрое больше, чтений SD на 13 % больше; ранняя сборка грузит ячейки сама, в миг
; сборки строки, и они сразу идут в дело (замер 2026-09-24: чтений SD даже меньше, чем без неё).
;
; Здесь же — защита строки FT812 (vdac2p_guard.asm, вход HOST2_GUARD из FrameEmit хоста): в перегруженном кадре спрайты
; выводятся только проходом A; и спрайты объектами (vdac2p_objects.asm, вход HOST2_OBJECT из SpriteEntry хоста):
; многоклеточная запись — одной картинкой из пака.
;
; Процедуры и переменные страницы хоста отсюда недоступны (окно W3 занято этой страницей) — только через переходники
; резидента HostCall, SpecRow, SpecVisible; общие с хостом данные — в резиденте (SP_TEMP, SP_GROUP, ROW_SPEC, SP_BUSY).
; Окна W1, W2 — свободны (на выходе переходник ставит в W1 страницу состояния, W2 восстановит RestoreWindows хоста).
;
; Генератор полос ROM ($02AE/$02CE → $EA51/$EA73, ядра KERNEL_METATILE_A/B; Docs/RTYPE_WORLD_ROM_MAP.md проекта VDAC2,
; «Stage 1: ROM tilemap generator»): при переходе скролла слоя через 64 px цель [#2EE6] / [#2EEA] растёт на #10, и насос
; в том же шаге рисует полосу — пять метаблоков 8×6 тайлов столбцом по дескрипторам ES:[источник + 2m − смещение]
; (ES = #1000; слой 0 — смещение #39D9, слой 1 — #2971); номер метаблока — младшие 14 бит дескриптора, бит 14 —
; отражение по горизонтали, бит 15 — по вертикали; метаблок — 48 записей по 3 байта (слово кода, байт атрибута) с
; DS:(номер·144) (DS = #3000, SI — 16 бит). Тайл в VRAM — слово кода с отражениями метаблока и слово «атрибут + младший
; байт кода следующей записи» (перекрывающийся MOVSW). Место — 8 столбцов с ((назначение·2 + #20) & #FF) >> 2 (группа
; целиком), строки карты 16…45 (строки полос 8…22). Источник следующей полосы — слово [#2EE4] / [#2EE8] рабочего ОЗУ,
; назначение — байт [#2EE7] / [#2EEB]; после полосы источник + #0A, назначение + #10.

                ORG #C000
HOST2_ENTRY_BEFORE:                     ; #C000: перед TilesUpdate (EarlyBefore)
                jp SpBefore
HOST2_ENTRY_AFTER:                      ; #C003: после RingCatchUp (EarlyAfter)
                ifndef RTYPE_NO_SPEC            ; диагностика: сборка без ранней сборки строк (сверка «до/после»)
                jp SpStep
                else
                ret
                DS 2
                endif
HOST2_ENTRY_GUARD:                      ; #C006: перед словами спрайтов кадра (FrameEmit) — защита строки FT812
                jp LineGuard
HOST2_ENTRY_OBJECT:                     ; #C009: запись буфера спрайтов с формой (SpriteEntry) — одной картинкой
                jp ObjEntry
HOST2_ENTRY_EVICT:                      ; #C00C: место пула спрайтов нужно ячейке (SpriteAllocS) — объект на нём вон
                jp ObjEvictUnit
                ASSERT HOST2_ENTRY_BEFORE == HOST2_BEFORE && HOST2_ENTRY_AFTER == HOST2_AFTER
                ASSERT HOST2_ENTRY_GUARD == HOST2_GUARD && HOST2_ENTRY_OBJECT == HOST2_OBJECT
                ASSERT HOST2_ENTRY_EVICT == HOST2_EVICT

; --- общее --------------------------------------------------------------------------------------------------------------
; Линейный адрес V30 A:HL (A — биты 16…19) → окно W2 (страница V30_PAGE_BASE + адрес >> 14), HL — указатель.
; Портит AF, BC.
V30Map:          add a,a
                add a,a
                ld b,a
                ld a,h
                rlca
                rlca
                and 3
                or b
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,h
                and #3F
                or #80
                ld h,a
                ret

; BC байт с DS:HL (DS = #3000; смещение идёт по кругу сегмента, как SI у ROM) → DE: через границу страницы V30 —
; частями. Портит всё, окно W2.
SpCopy:         ld (CP_LEFT),bc
                ld (CP_DEST),de
                ld (CP_SI),hl
.part:          ld hl,(CP_SI)
                ld a,3
                call V30Map                      ; HL — окно W2
                push hl
                ex de,hl
                ld hl,#C000
                or a
                sbc hl,de                       ; HL — байт до конца страницы (1…#4000)
                ld de,(CP_LEFT)
                or a
                sbc hl,de
                jr c,.split
                ld b,d
                ld c,e                          ; остаток помещается целиком
                jr .copy
.split:         add hl,de
                ld b,h
                ld c,l                          ; до конца страницы
.copy:          ld hl,(CP_LEFT)
                or a
                sbc hl,bc
                ld (CP_LEFT),hl
                ld hl,(CP_SI)
                add hl,bc
                ld (CP_SI),hl                   ; по кругу сегмента
                pop hl
                ld de,(CP_DEST)
                ldir
                ld (CP_DEST),de
                ld hl,(CP_LEFT)
                ld a,h
                or l
                jr nz,.part
                ret

CP_LEFT         DW 0
CP_DEST         DW 0
CP_SI           DW 0

; Номер метаблока B полосы с источником HL слоя A (0/1) → дескриптор DE: ES:[(источник − смещение + 2·B) & #FFFF]
; (ES = #1000). Портит AF, BC, HL, окно W2.
MetaDescriptor: or a
                ld de,-#39D9
                jr z,.bias
                ld de,-#2971
.bias:          add hl,de
                ld a,b
                add a,a
                ld e,a
                ld d,0
                add hl,de                       ; смещение дескриптора в сегменте #1000
                push hl
                ld a,1
                call V30Map
                ld e,(hl)                       ; младший байт
                pop hl
                inc hl                          ; старший — отдельно: слово может пересечь страницу
                push de
                ld a,1
                call V30Map
                pop de
                ld d,(hl)
                ret

; Дескриптор DE → SI первой записи метаблока в HL: (номер & #3FFF)·144 по модулю 65536, как у ROM. Портит AF, DE.
MetaSource:     ld a,d
                and #3F
                ld h,a
                ld l,e
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·16
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·128
                add hl,de                       ; ·144
                ret

; --- ранняя сборка строк групп переднего слоя ------------------------------------------------------------------------
; Полоса слоя 0 приходит от ROM ровно тогда, когда её столбец групп входит в окно (замер 2026-09-23: 2–3 кадра от записи
; до показа), и все её 15 строк полос с каскадами перестраивались за один-два кадра — это и были средние затыки. Но
; содержимое следующей полосы известно заранее (источник [#2EE4] и назначение [#2EE7]), а её столбец групп всё время до
; прихода невидим: он только что ушёл из окна слева. Поэтому строки полосы собираются заранее, по строке за кадр, из
; предсказанных тайлов (SpPredict — те же байты, что запишет ROM): StripRowRebuild с тайлами SP_TEMP вместо VRAM
; кладёт их и в тень. Когда полоса приходит, сверка с тенью находит строки неизменными — перестраивать нечего.
;
; Невидимость — условие верности: предсказанные строки показывали бы будущее, поэтому столбец проверяется каждый кадр до
; TilesUpdate (SpBefore); стал виден раньше прихода — строки помечаются к сверке, и TilesUpdate того же кадра
; возвращает им тайлы VRAM. Каскад: изменилось состояние потока в конце строки — следующая строка той же области
; ждёт (SP_CASC) и собирается в свой черёд; строки после полосы (хвост области 2, 23…31) — тоже по одной за кадр, из
; VRAM. Ждущий каскад, которого ранняя сборка не успела, при приходе полосы или показе строки делается сразу обычной
; перестройкой. Строки, собранные заранее, при приходе помечаются к сверке всегда: неверное предсказание перестроится.
;
; Собранные заранее строки держат картинки новой полосы, а пул картинок (53 с кольцом, со ссылками до 52) почти полон:
; сроки выделения решают, какой класс уйдёт полосами (у эталонного пути 32 отказа за 40 000 кадров). Замеры 2026-09-24:
; — если полоса не приходит (слой встал — бой в конце этапа), её картинки держались бы весь бой, и классы анимации
;   босса уходили бы полосами (441 отказ): поэтому ранняя сборка начинается, только когда слой едет не медленнее
;   SP_MIN_SPEED, а слой встал или замедлился до прихода полосы — собранное помечается к сверке (вернутся тайлы VRAM,
;   картинки освободятся);
; — запас пула проверяется в начале полосы (SP_START_ROOM): пауза посреди полосы оставляла ждущий каскад, и при приходе
;   полосы он шёл сразу — всплеск выделений опустошал пул; предел расстояния до перехода через 64 px сжимал сборку во
;   времени — тоже всплески; отказ в строке ранней сборки (IMG_FAILS) возвращает строку к VRAM.
; Итог — 35 отказов за 40 000 кадров (у эталонного пути 32), вывод совпадает, кроме 4 кадров шкалы BEAM панели.
SP_MAX_BUSY     EQU 1                   ; ранняя сборка — в кадре, где TilesUpdate перестроил не больше стольких строк
SP_START_ROOM   EQU 8                   ; полоса начинается, когда в пуле картинок свободно не меньше
SP_FIRST        EQU 8                   ; строки полос полосы: 8…22 (строки карты 16…45)
SP_LAST         EQU 22
SP_TAIL_END     EQU 31                  ; последняя строка области 2 (22…31, video.inc: REGION_FIRST)
SP_MIN_SPEED    EQU #40                 ; начинать, когда слой едет не медленнее (Q8.8: 0,25 px за кадр; этап 1 — 0,5)
SP_REGION1      EQU 11                  ; первые строки областей 1 и 2 (video.inc: REGION_FIRST)
SP_REGION2      EQU 22

SP_ACTIVE       DB 0                    ; 1 — полоса SP_SRC / SP_DEST собирается
SP_HELD         DB 0                    ; 1 — её предсказанные строки лежат в тени, а полоса ещё не пришла
SP_SRC          DW 0
SP_DEST         DB 0
SP_ROW          DB 0                    ; следующая строка полос: SP_FIRST…SP_LAST — предсказанные, дальше — хвост
SP_CASC         DB 0                    ; 1 — каскад в строку SP_ROW ждёт (её состояние перед строкой изменилось)
SP_DONE_SRC     DW #FFFF                ; полоса, собранная (или брошенная) последней
SP_DONE_DEST    DB #FF
SP_S            DW 0                    ; слой 0 этого кадра: источник [#2EE4], цель [#2EE6], назначение [#2EE7]
SP_TG           DB 0
SP_T            DB 0
SP_MOVING       DB 0                    ; 1 — слой 0 едет (скорость ≥ SP_MIN_SPEED)
SP_FLIP         DB 0                    ; отражения метаблока: биты 7 (fy) и 6 (fx) старшего байта слова кода
SP_FAILS        DB 0                    ; IMG_FAILS перед строкой ранней сборки
SP_ROWBUF       DS 25                   ; строка метаблока: 8 записей и байт за ними

; Слой 0 этого кадра: источник, цель и назначение ([#2EE4], [#2EE6], [#2EE7]) → SP_S, SP_TG, SP_T; скорость X
; ([#2EEC:#2EEE], 24 бита со знаком, Q16.8) не меньше SP_MIN_SPEED → SP_MOVING = 1, иначе 0. Портит AF, BC, HL, окно W2.
SpReadMap:      ld a,V30_PAGE_BASE+#10          ; рабочее ОЗУ V30 #40000…#43FFF
                ld bc,PORT_PAGE2
                out (c),a
                ld hl,(#8000+#2EE4)
                ld (SP_S),hl
                ld hl,(#8000+#2EE6)             ; цель и назначение — байты подряд
                ld (SP_TG),hl
                ld a,(#8000+#2EEE)              ; старший байт скорости
                or a
                jp m,.slow                      ; назад
                jr nz,.moving
                ld a,(#8000+#2EED)
                or a
                jr nz,.moving
                ld a,(#8000+#2EEC)
                cp SP_MIN_SPEED
                jr nc,.moving
.slow:          xor a
                ld (SP_MOVING),a
                ret
.moving:        ld a,1
                ld (SP_MOVING),a
                ret

; Перед TilesUpdate, пока полоса собирается или её собранные строки ждут прихода. Полоса пришла (источник или
; назначение сменились: насос нарисовал её или карта сброшена) — собранные строки к сверке с тенью, ждущий каскад —
; сразу. Не пришла, а слой встал или замедлился либо её столбец групп уже виден — предсказанные строки к сверке
; (вернутся тайлы VRAM, картинки новой полосы освободятся). Портит всё.
SpBefore:       ld a,(SP_ACTIVE)
                ld hl,SP_HELD
                or (hl)
                ret z
                call SpReadMap
                ld hl,(SP_S)
                ld de,(SP_SRC)
                or a
                sbc hl,de
                jr nz,.arrived
                ld a,(SP_T)
                ld hl,SP_DEST
                cp (hl)
                jr nz,.arrived
                ld a,(SP_MOVING)
                or a
                jr z,.back                      ; слой встал (бой в конце этапа): полоса не придёт
                ld a,#FF
                call SpecVisible                ; столбец группы в окне слоя?
                ret nc
                ld a,(SP_HELD)
                or a
                jr nz,.back
                xor a                           ; ещё ничего не собрано: подождать, пока столбец уйдёт из окна
                ld (SP_ACTIVE),a
                ret
.back:          ld a,(SP_HELD)
                or a
                call nz,SpMarkRows              ; предсказанное — назад к VRAM
                jr SpRelease
.arrived:       ld a,(SP_HELD)
                or a
                call nz,SpMarkRows              ; к сверке: у верного предсказания тень уже равна VRAM
                ld a,(SP_ACTIVE)
                or a
                jr z,SpRelease
                ld a,(SP_CASC)
                or a
                jr z,SpRelease
                ld a,(SP_ROW)                   ; ждущий каскад — обычной перестройкой (с каскадом)
                ld c,0
                call SpecRow
SpRelease:      xor a
                ld (SP_HELD),a
SpStop:         xor a
                ld (SP_ACTIVE),a
                ld (SP_CASC),a
                ld hl,(SP_SRC)                  ; эта полоса больше не собирается
                ld (SP_DONE_SRC),hl
                ld a,(SP_DEST)
                ld (SP_DONE_DEST),a
                ret

; Предсказанные строки полосы в работе (SP_FIRST … SP_ROW − 1, не дальше SP_LAST) — пометки VRAM слоя 0 группы
; SP_GROUP: TilesUpdate сверит их с тенью. Портит AF, BC, DE, HL.
SpMarkRows:     ld a,(SP_ROW)
                cp SP_LAST+1
                jr c,.rows
                ld a,SP_LAST+1
.rows:          sub SP_FIRST
                ret z
                add a,a
                ld b,a                          ; строк карты
                ld a,(SP_GROUP)
                ld e,a
                ld d,0
                ld hl,VRAM_DIRTY0+2*SP_FIRST*8
                add hl,de
                ld de,VRAM_ROWS0+2*SP_FIRST
.mark:          ld a,#FF
                ld (hl),a                       ; группа строки карты
                ld (de),a                       ; строка карты
                inc de
                ld a,l
                add a,8
                ld l,a
                jr nc,.next
                inc h
.next:          djnz .mark
                ld a,1
                ld (VIDEO_DIRTY),a
                ret
                ASSERT VRAM_ROWS0 == VRAM_DIRTY0+512   ; пометки: байт на группу строки карты (строка·8 + группа)

; После RingCatchUp: следующая строка ранней сборки, если кадр лёгкий (SP_BUSY), насос не подаёт полос, а столбец
; группы невидим. Портит всё.
SpStep:         ld a,(SP_BUSY)
                cp SP_MAX_BUSY+1
                ret nc                          ; кадр уже тяжёлый
                call SpReadMap
                ld a,(SP_T)
                ld hl,SP_TG
                cp (hl)
                ret nz                          ; насос ещё подаёт полосы (начало этапа, возврат к точке)
                ld a,(SP_ACTIVE)
                or a
                jr nz,.run
                ld hl,(SP_S)                    ; новая полоса: не собиралась ли уже
                ld de,(SP_DONE_SRC)
                or a
                sbc hl,de
                jr nz,.new
                ld a,(SP_T)
                ld hl,SP_DONE_DEST
                cp (hl)
                ret z
.new:           ld a,(SP_MOVING)
                or a
                ret z                           ; слой стоит или медлит: полоса может не прийти
                call SpecRoom
                cp SP_START_ROOM
                ret c                           ; пул картинок почти полон: полоса пойдёт обычным путём
                ld hl,(SP_S)
                ld (SP_SRC),hl
                ld a,(SP_T)
                ld (SP_DEST),a
                add a,a
                add a,#20
                rlca
                rlca
                rlca
                and 7
                ld (SP_GROUP),a                 ; ((назначение·2 + #20) & #FF) >> 5
                ld a,#FF
                call SpecVisible                ; столбец ещё уходит из окна слева — подождать
                ret c
                ld a,SP_FIRST
                ld (SP_ROW),a
                xor a
                ld (SP_CASC),a
                inc a
                ld (SP_ACTIVE),a
.run:           ld a,(SP_ROW)                   ; столбец невидим: проверен до TilesUpdate (SpBefore) или сейчас
                cp SP_LAST+1
                jr nc,.tail
                call SpPredict
                ld a,(SP_CASC)
                or a
                jr nz,.room
                call SpSame
                jr nz,.room
                ld hl,SP_ROW                    ; тайлы те же и состояние перед строкой то же — собирать нечего (как
                inc (hl)                        ; у сверки с тенью эталонного пути); следующая — в этом же кадре
                jr .run
.room:          ld a,(IMG_FAILS)
                ld (SP_FAILS),a
                ld a,(SP_ROW)
                ld c,3                          ; тайлы из SP_TEMP; каскад — за ранней сборкой
                call SpecRow
                ld b,a
                ld a,1
                ld (SP_HELD),a                  ; предсказанное — в тени (к сверке при приходе или назад)
                ld a,(IMG_FAILS)
                ld hl,SP_FAILS
                cp (hl)
                ld a,b
                jr z,.result
                ; Картинки всё же не хватило: строка — назад к VRAM (её полоса пойдёт обычным путём), следующая строка
                ; той же области — сейчас, с каскадом: её слова ждут состояния после строки до ранней сборки.
                ld a,(SP_ROW)
                ld c,2
                call SpecRow
                ld a,(SP_ROW)
                cp SP_REGION1-1
                jp z,SpStop
                cp SP_REGION2-1
                jp z,SpStop
                inc a
                ld c,0
                call SpecRow
                jp SpStop
.tail:          ld a,(SP_CASC)
                or a
                jp z,SpStop                     ; хвост не нужен
                ld a,(SP_ROW)
                call SpecVisible
                jr c,.visible
                ld a,(SP_ROW)
                ld c,2                          ; тайлы из VRAM; каскад — за ранней сборкой
                call SpecRow
.result:        cp 2
                sbc a,a
                inc a                           ; 1 — CASCADE = 2: каскад в той же области ждёт
                ld (SP_CASC),a
                ld hl,SP_ROW
                inc (hl)
                ld a,(hl)
                cp SP_TAIL_END+1
                ret c
                jp SpStop
.visible:       ld a,(SP_CASC)                  ; строка уже видна: ждущий каскад — сейчас обычной перестройкой
                or a
                jp z,SpStop
                ld a,(SP_ROW)
                ld c,0
                call SpecRow
                jp SpStop

; Предсказанная строка SP_TEMP равна тени строки полос SP_ROW группы SP_GROUP слоя 0 (VIDEO_SHADOW_PAGE0)? Z = 1 — да.
; Портит AF, B, DE, HL, окно W2.
SpSame:         ld a,VIDEO_SHADOW_PAGE0
                ld bc,PORT_PAGE2
                out (c),a
                ld a,(SP_ROW)
                add a,a
                add a,#80
                ld h,a                          ; строка карты 2k: 2k·256 в окне W2
                ld a,(SP_GROUP)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                ld l,a                          ; группа·32: 8 тайлов по 4 байта
                push hl
                ld de,SP_TEMP
                call .row
                pop hl
                ret nz
                inc h                           ; строка карты 2k + 1 (SP_TEMP + 32)
.row:           ld b,32
.byte:          ld a,(de)
                cp (hl)
                ret nz
                inc de
                inc hl
                djnz .byte
                ret

; Строка полос SP_ROW (SP_FIRST…SP_LAST) полосы SP_SRC → SP_TEMP: строки карты 2·SP_ROW и 2·SP_ROW + 1 — строки полосы
; r = 2·SP_ROW − 16 и r + 1, по 8 тайлов по 4 байта, как их запишет ROM в VRAM. Портит всё, окно W2.
SpPredict:      ld a,(SP_ROW)
                add a,a
                sub 2*SP_FIRST
                push af
                ld de,SP_TEMP
                call SpStripRow
                pop af
                inc a
                ld de,SP_TEMP+32
; Строка полосы A (0…29) полосы SP_SRC слоя 0 → 32 байта с DE. Портит всё, окно W2.
SpStripRow:     push de
                ld b,-1
.div:           inc b
                sub 6
                jr nc,.div
                add a,6
                ld c,a                          ; C — строка в метаблоке, B — метаблок
                push bc
                ld hl,(SP_SRC)
                xor a
                call MetaDescriptor
                pop bc
                ld a,d
                and #C0
                ld (SP_FLIP),a
                jp p,.row                       ; без отражения по вертикали
                ld a,5
                sub c
                ld c,a                          ; строки метаблока снизу вверх: строка источника 5 − t
.row:           call MetaSource
                ld a,c
                add a,a
                add a,a
                add a,a
                ld e,a                          ; t·8
                add a,a
                add a,e                         ; t·24
                ld e,a
                ld d,0
                add hl,de                       ; SI строки источника
                ld de,SP_ROWBUF
                ld bc,25
                call SpCopy                     ; 8 записей и байт за ними (слово атрибута последней)
                pop de                          ; DE — первый тайл строки
                ld hl,SP_ROWBUF
                ld a,(SP_FLIP)
                ld c,a
                ld b,8
                bit 6,c
                jr z,.tile
                ld a,e                          ; отражение по горизонтали: запись i — в столбец 7 − i
                add a,28
                ld e,a
                jr nc,.tile
                inc d
.tile:          ld a,(hl)
                ld (de),a                       ; младший байт кода
                inc hl
                inc de
                ld a,(hl)
                xor c
                ld (de),a                       ; старший: с отражениями метаблока
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; атрибут
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; младший байт кода следующей записи (перекрывающийся MOVSW)
                inc de
                bit 6,c
                jr z,.next
                ld a,e
                sub 8
                ld e,a
                jr nc,.next
                dec d
.next:          djnz .tile
                ret

                INCLUDE "vdac2p_guard.asm"

                INCLUDE "vdac2p_objects.asm"

                INCLUDE "vdac2p_sprclear.asm"

                INCLUDE "vdac2p_palettes.asm"

                INCLUDE "vdac2p_native_h2.asm"

HOST2_END:
                ASSERT HOST2_END <= #10000
