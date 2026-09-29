; VDAC2+: ранняя сборка строк групп переднего слоя — резидентная часть: переходники между страницей хоста и второй
; страницей хоста HOST2_PAGE (vdac2p_host2.asm, окно W3 на время вызова; в резиденте и странице хоста места нет). Хост
; зовёт EarlyBefore перед TilesUpdate и EarlyAfter после RingCatchUp (окно W3 — страница хоста); процедуры второй
; страницы зовут процедуры страницы хоста и трогают её переменные только через HostCall, SpecRow, SpecVisible и
; SpecRoom — те на время вызова возвращают в W3 страницу хоста. Прерывания в машине выключены — смена W3 безопасна.
; Данные, общие с хостом (SP_TEMP, SP_GROUP, ROW_SPEC, SP_BUSY, IMG_FAILS), — в резиденте за кэшем диспетчеризации
; (v30z80_runtime.asm).

HOST2_BEFORE    EQU #C000               ; входы второй страницы хоста (vdac2p_host2.asm)
HOST2_AFTER     EQU #C003
HOST2_GUARD     EQU #C006               ; защита строки FT812 (vdac2p_guard.asm)
HOST2_OBJECT    EQU #C009               ; спрайты объектами (vdac2p_objects.asm): DE — запись буфера спрайтов
HOST2_EVICT     EQU #C00C               ; вытеснить объект, занимающий место DE пула спрайтов (SpriteAllocS)

; Перед TilesUpdate: пришла ли полоса, собранная заранее (её строки — на сверку с тенью), и не видна ли раньше
; прихода (предсказанные строки — назад). Счётчик перестроек кадра обнуляется, возраст ячеек спрайтов прижимается.
; Портит всё; на выходе W3 — страница хоста, W1 — страница состояния.
EarlyBefore:    call SpriteAge                  ; возраст ячеек спрайтов — без перехода по кругу (vdac2p_sprites.asm)
                xor a
                ld (SP_BUSY),a                  ; перестроек строк в этом кадре — считает StripRowRebuild
                ld hl,HOST2_BEFORE
                jr Host2Check
; После RingCatchUp: ранняя сборка строки полосы. Портит всё; на выходе — как у EarlyBefore.
EarlyAfter:     ld hl,HOST2_AFTER
Host2Check:     ld a,(DATA_STATUS)
                cp DATA_READY
                ret nz
                ld a,(TITLE_GUARD)
                or a
                ret nz
                ld a,HOST2_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call .hl
.back:          ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                ld a,VIDEO_STATE_PAGE
                jp Map1
.hl:            jp (hl)

; Надписи скорости мыши и клавиш (vdac2p_label.asm — в звуковой странице: в страницах хоста места нет) из FrameEmit
; хоста. На выходе, как у Host2Check, W3 — страница хоста, W1 — страница состояния. Портит всё.
LabelCall:      call MapSound
                call SOUND_ENTRY_LABEL
                jr Host2Check.back

; Из второй страницы хоста: процедура IX страницы хоста (W3 — страница хоста на время вызова). A, BC, DE, HL — входы
; процедуры; на выходе — её A, флаги, BC, DE, HL. Портит IX.
HostCall:       push bc
                push af
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                pop af
                pop bc
                call .ix
                push bc
                push af
                ld a,HOST2_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                pop af
                pop bc
                ret
.ix:            jp (ix)

; Из второй страницы хоста: строка полос A группы SP_GROUP слоя 0 — перестройка без сверки с тенью (StripRowRebuild с
; ROW_FORCE). C — ROW_SPEC: 0 — обычная, с каскадом; бит 0 — тайлы из SP_TEMP вместо VRAM; не 0 — каскад в той же
; области не делается, а отмечается CASCADE = 2 (его ведёт ранняя сборка). Слой хоста TILE_LAYER сохраняется.
; Выход: A — CASCADE. Портит всё.
SpecRow:        push bc
                push af
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                pop af
                pop bc
                ld (TILE_ROW),a
                ld a,c
                ld (ROW_SPEC),a
                ld a,(SP_GROUP)
                ld (TILE_GROUP),a
                ld a,(TILE_LAYER)
                push af
                xor a
                ld (TILE_LAYER),a
                ld (CASCADE),a
                inc a
                ld (ROW_FORCE),a
                bit 0,c
                jr z,.rebuild
                ld hl,SP_TEMP
                ld de,TILE_TEMP
                ld bc,64
                ldir
.rebuild:       call StripRowRebuild
                pop af
                ld (TILE_LAYER),a
                xor a
                ld (ROW_SPEC),a
                ld a,(CASCADE)
                jp Host2Back

; Из второй страницы хоста: видна ли группа SP_GROUP слоя 0 в строке полос A (как GroupInWindow — по окну слоя 0 этого
; кадра, LayerWindow, и полосе после растрового разрыва); A = #FF — только по столбцам (группа в маске видимых групп,
; строки любые). CF = 1 — видна. Окно, которое оставил TilesUpdate (VIS_*, SCAN_ROW, TILE_LAYER), сохраняется.
; Портит всё.
SpecVisible:    push af
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                pop af
                ld hl,(SCAN_ROW)                ; SCAN_ROW и TILE_LAYER — подряд
                push hl
                ld hl,(VIS_GROUPS)              ; VIS_GROUPS, VIS_ROW
                push hl
                ld hl,(VIS_ROW2)                ; VIS_ROW2, VIS_ROWS2
                push hl
                ld (SCAN_ROW),a
                xor a
                ld (TILE_LAYER),a
                call LayerWindow
                ld a,(SP_GROUP)
                ld b,a
                ld a,(SCAN_ROW)
                inc a
                jr nz,.row
                inc b                           ; только столбцы: бит группы в маске
                ld a,(VIS_GROUPS)
.bit:           rrca
                djnz .bit
                jr .result
.row:           call GroupInWindow
.result:        sbc a,a                         ; #FF — видна
                pop hl
                ld (VIS_ROW2),hl
                pop hl
                ld (VIS_GROUPS),hl
                pop hl
                ld (SCAN_ROW),hl
                add a,a                         ; CF = 1 — видна
                jp Host2Back

; Из второй страницы хоста: свободных картинок пула → A — как их ищет ImageAlloc: не занята либо без ссылок строк
; групп и отпущена не в этом кадре; пул — до предела ImageLimit. Портит всё, окно W1 — страница состояния.
SpecRoom:       ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                ld a,VIDEO_TILE_PAGE
                call Map1                       ; W1 — таблица картинок
                call ImageLimit
                ld b,l                          ; картинок в пуле (не больше 74)
                ld ix,#4000+IMAGE_TABLE
                ld c,0                          ; C — свободных
.entry:         ld a,(ix+IMAGE_KEY_SIZE+5)
                or a
                jr z,.free                      ; не занята
                ld a,(ix+IMAGE_KEY_SIZE+2)
                or (ix+IMAGE_KEY_SIZE+3)
                jr nz,.next                     ; есть ссылки
                ld a,(VIDEO_FRAME)
                cp (ix+IMAGE_KEY_SIZE+4)
                jr z,.next                      ; отпущена в этом кадре
.free:          inc c
.next:          ld de,IMAGE_ENTRY
                add ix,de
                djnz .entry
                ld a,c
                push af                         ; Map1 портит BC
                ld a,VIDEO_STATE_PAGE
                call Map1
                pop af
; Снова вторая страница хоста в W3; A и флаги сохраняются. Портит BC.
Host2Back:      push af
                ld a,HOST2_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                pop af
                ret
