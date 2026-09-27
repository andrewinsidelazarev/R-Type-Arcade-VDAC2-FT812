; VDAC2+: выделение мест спрайтов пула RAM_G (SPRITE_CELLS = 256; пул общий с объектами vdac2p_objects.asm — объект
; занимает 2, 4 или 8 мест, в SPRITE_OWNER его места помечены OBJ_OWNER) — выборка давнейшей вместо круга (решение
; пользователя
; 2026-09-24 «делай» на «меньше распаковок спрайтов»). Замер (трасса SpriteCell, кадры 1…11 400): круг хоста брал
; первую ячейку, не выводившуюся в этом и прошлом кадре, — и выбивал спрайты, которые снова нужны через десяток кадров
; (медиана возврата 27 кадров). Здесь из SP_SAMPLE ячеек от руки (свободная берётся сразу) берётся та, что выводилась
; давнее всех: модель пула — подгрузок 8368 → 7599 (−9 %; этап 2 — −10 %). Больше не выжать правилом: на этапе 2 за
; 16 кадров выводится до 304 разных ячеек — пул меньше рабочего множества.
;
; Кадр вывода SLOT_USED — байт (VIDEO_FRAME по кругу 256), и ячейка, не выводившаяся 256 кадров и дольше, казалась бы
; свежей: SpriteAge раз в кадр прижимает возраст четырёх мест (весь пул за 64 кадра) к SP_OLD, так что возраст
; давних лежит в SP_OLD…SP_OLD + 64 и по кругу не переходит.
;
; Место, выводившееся в этом, прошлом или позапрошлом кадре (возраст < SP_KEEP), не берётся: пока новый список не
; переключён, FT812 ещё показывает список два кадра назад (FrameEmit ждёт показа прошлого списка только перед своим),
; и запись в его место портила бы показанную картинку. До 2026-09-25 порог был 2 — у ячеек это случалось редко, а с
; объектами в тяжёлых сценах (конец этапа 2, босс этапа 4) — постоянно («большие спрайты глючат» на плате).
;
; Код — в резиденте (окно W0): зовут хост (CellEnsure — SpriteAllocS, EarlyBefore — SpriteAge), окно W3 — страница
; хоста, W1 — страница состояния (владельцы SPRITE_OWNER и кадры SLOT_USED).

SP_SAMPLE       EQU 8                   ; занятых ячеек в выборке
SP_KEEP         EQU 3                   ; места моложе стольких кадров вывода не трогаются (показанный и ждущий списки)
SP_OLD          EQU 128                 ; возраст давних ячеек после прижатия (кадров)
SP_AGE_HAND     DB 0                    ; следующая ячейка прижатия возраста

; Ячейка спрайта для CELL_SETPAL, CELL_CODE (W1 — страница состояния): от руки SPRITE_HAND свободное место — сразу;
; иначе из SP_SAMPLE занятых, не выводившихся SP_KEEP кадров, — выводившееся давнее всех; прежний владелец — ячейка
; («не загружена») или объект (вытесняется целиком: HOST2_EVICT второй страницы хоста). Выход: HL — слот (SPRITE_SLOT0 +
; место), INFLATE_ADDRESS; CF = 1 — нет (весь пул выводится). Портит всё, окно W2. Вместо SpriteAlloc хоста.
SpriteAllocS:   ld a,(SPRITE_HAND)
                ld e,a                          ; E — место пробы
                ld b,0                          ; B — проб по кругу (256)
                ld c,SP_SAMPLE                  ; C — занятых в выборке осталось
                ld d,#FF                        ; D — лучшая ячейка (SP_BEST_AGE = 0 — её нет)
                xor a
                ld (SP_BEST_AGE),a
.probe:         ld l,e
                ld h,0
                push de
                ld d,h
                add hl,hl
                add hl,de                       ; ячейка·3
                ld de,#4000+SPRITE_OWNER
                add hl,de
                pop de
                ld a,(hl)
                cp FREE_OWNER
                jr z,.free                      ; свободная — сразу
                ld h,high (#4000+SLOT_USED)
                ld l,e
                ld a,(VIDEO_FRAME)
                sub (hl)                        ; возраст (кадров с последнего вывода)
                cp SP_KEEP
                jr c,.next                      ; выводится (этот, прошлый или позапрошлый кадр)
                ld hl,SP_BEST_AGE
                cp (hl)
                jr c,.sample
                jr z,.sample
                ld (hl),a                       ; давнее лучшей
                ld d,e
.sample:        dec c
                jr z,.chosen
.next:          inc e                           ; по кругу 256
                djnz .probe
                ld a,(SP_BEST_AGE)
                or a
                scf
                ret z                           ; не выводившихся SP_KEEP кадров нет — весь пул на экране
                jr .chosen
.free:          ld d,e
.chosen:        ld a,e
                inc a
                ld (SPRITE_HAND),a              ; рука — за последней пробой
                ld l,d
                ld h,0
                ld (ALLOC_PAIR),hl
                ld b,h
                ld c,l
                add hl,hl
                add hl,bc
                ld bc,#4000+SPRITE_OWNER
                add hl,bc
                ld (ALLOC_OWNER),hl
                ld a,(hl)
                cp FREE_OWNER
                jr z,.take
                cp OBJ_OWNER
                jr nz,.cell
                ld de,(ALLOC_PAIR)              ; место объекта: объект — вон целиком (его места свободны, запись
                ld hl,HOST2_EVICT               ; каталога — «не загружен»)
                call Host2Check
                jr .take
.cell:          ld hl,(ALLOC_PAIR)
                ld bc,SPRITE_SLOT0
                add hl,bc
                ld b,h
                ld c,l
                ld hl,(ALLOC_OWNER)
                call OwnerRelease               ; прежний владелец — «ячейка не загружена»
.take:          ld hl,(ALLOC_PAIR)
                ld de,#4000+SLOT_USED
                add hl,de
                ld a,(VIDEO_FRAME)
                dec a
                ld (hl),a                       ; занят (прошлый кадр); первый вывод ячейки — не повторный
                ld hl,(ALLOC_OWNER)
                ld a,(CELL_SETPAL)
                ld (hl),a
                inc hl
                ld de,(CELL_CODE)
                ld (hl),e
                inc hl
                ld (hl),d
                ld hl,(ALLOC_PAIR)
                call SpriteCellAddress
                ld (INFLATE_ADDRESS),de
                ld (INFLATE_ADDRESS+2),a
                ld hl,(ALLOC_PAIR)
                ld de,SPRITE_SLOT0
                add hl,de
                or a
                ret
                ASSERT SPRITE_CELLS == 256 && low SLOT_USED == 0

SP_BEST_AGE     DB 0                    ; возраст лучшей ячейки выборки

; Корабль и модуль оружия — вне любых защит и упрощений вывода (решение пользователя 2026-09-25: «это главный герой
; игры»). Их записи sprite RAM ROM пишет в свои места процедурой $1BE9 (адрес задаёт вызывающий): R-9 — запись 120
; ($3C0; $3C8 — пустая вторая половина), биты — 122 и 123 ($3D0, $3D8), Force — 125 ($3E8); общие объекты ($1BCC)
; кончаются на записи 119 (предел указателя [2EFC] — $3C8). SpritesBuild выводит записи от последней к первой, поэтому
; слова записей 120…127 идут в буфере спрайтов первыми. ProtectMark зовётся перед каждой записью (HL — её адрес в
; SPRITE_TEMP окна W1: у записи 1×1 — байт 5, у записи с формой — начало): перед первой записью не игрока граница
; PROTECT_END = SPRITE_FILL; PROTECT_OPEN = 1, пока граница не записана (все слова кадра — игрока). Начало кадра
; узнаётся по SPRITE_FILL = началу слов. Защита строки (vdac2p_guard.asm, LgDrop) выбрасывает вершины прохода B
; только за границей. Сохраняет BC, DE, HL; портит AF.
PLAYER_ENTRIES  EQU #4000+SPRITE_TEMP+120*8     ; записи игрока: 120…127
ProtectMark:    push de
                ld de,(SPRITE_FILL)
                ld a,e
                cp low (#4000+SPRITE_WORDS)
                jr nz,.started
                ld a,d
                cp high (#4000+SPRITE_WORDS)
                jr nz,.started
                ld a,1                          ; слов кадра ещё нет: граница не записана
                ld (PROTECT_OPEN),a
                ld (PROTECT_END),de
.started:       ld a,l
                sub low PLAYER_ENTRIES
                ld a,h
                sbc a,high PLAYER_ENTRIES
                jr nc,.done                     ; запись игрока
                ld a,(PROTECT_OPEN)
                or a
                jr z,.done                      ; граница уже записана
                xor a
                ld (PROTECT_OPEN),a
                ld (PROTECT_END),de             ; первая запись не игрока: слова до неё — игрока
.done:          pop de
                ret

; Раз в кадр (EarlyBefore; W1 — страница состояния, ставится здесь): четыре ячейки от SP_AGE_HAND — у ячеек с
; возрастом не меньше SP_OLD кадр вывода ставится на VIDEO_FRAME − SP_OLD (возраст прижат, по кругу 256 не переходит).
; Портит всё.
SpriteAge:      ld a,VIDEO_STATE_PAGE
                call Map1                       ; W1 — кадры вывода SLOT_USED
                ld a,(SP_AGE_HAND)
                ld l,a
                add a,4
                ld (SP_AGE_HAND),a
                ld h,high (#4000+SLOT_USED)
                ld b,4
.cell:          ld a,(VIDEO_FRAME)
                sub (hl)
                cp SP_OLD
                jr c,.fresh
                ld a,(VIDEO_FRAME)
                sub SP_OLD
                ld (hl),a                       ; у свободных тоже — им кадр вывода не нужен
.fresh:         inc l
                djnz .cell
                ret
