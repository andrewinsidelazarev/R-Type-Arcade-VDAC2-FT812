; Резидентная часть переведённой программы World ROM (V30 → Z80), TS-Config.
;
; Окна: #0000 — эта часть (состояние V30, память, порты M72, прерывания, диспетчеризация),
; #4000 — W1, всегда рабочее ОЗУ V30 #40000..#43FFF (страница WORK_PAGE), #8000 — W2,
; другая страница V30 по требованию (W2_PAGE), #C000 — страница переведённого кода (на
; время поиска в DISPATCH — страница таблицы).
; Память V30 (1 МБ) — 64 страницы TS-Config с V30_PAGE_BASE: страница V30 = адрес >> 14.
; Прерывания Z80 выключены. Семантика машины — rtype_m72.machine (эталон на unicorn).

; --- порты TS-Config ---------------------------------------------------------------
PORT_PAGE1      EQU #11AF
PORT_PAGE2      EQU #12AF
PORT_PAGE3      EQU #13AF
PORT_BORDER     EQU #0FAF
; Контроллер DMA TS-Config (TSLib TSConf.inc): адреса источника и приёмника — страница и
; смещение в ней (14 бит), длина пакета в словах − 1, число пакетов − 1, режим (запись
; запускает копирование), состояние (бит 7 — копирование идёт).
DMASADDRL       EQU #1AAF
DMASADDRH       EQU #1BAF
DMASADDRX       EQU #1CAF
DMADADDRL       EQU #1DAF
DMADADDRH       EQU #1EAF
DMADADDRX       EQU #1FAF
DMALEN          EQU #26AF
DMACTR          EQU #27AF
DMASTATUS       EQU #27AF
DMANUM          EQU #28AF
DMA_RAM         EQU #01
DMA_WNR         EQU #80

                ORG #0000
                jp Start
                jp ApiCall                      ; #0003: вызовы платформы (страница переключения)

; --- состояние V30 ---------------------------------------------------------------------
; Порядок 16-битных регистров — номера x86 (AX CX DX BX SP BP SI DI); 8-битные AL..BH
; лежат в младших и старших байтах AX..BX.
V_REG:
V_AX            DW INIT_AX
V_CX            DW INIT_CX
V_DX            DW INIT_DX
V_BX            DW INIT_BX
V_SP            DW INIT_SP
V_BP            DW INIT_BP
V_SI            DW INIT_SI
V_DI            DW INIT_DI
V_SREG:
V_ES            DW INIT_ES
V_CS            DW INIT_CS
V_SS            DW INIT_SS
V_DS            DW INIT_DS
V_FL            DW INIT_FL      ; FLAGS x86
V_IP            DW INIT_IP
W2_PAGE         DB #FF          ; страница V30 в окне W2 (#FF — служебная или неизвестна)
LIN_PAGE        DB 0            ; страница последнего обращения
DRIVER_SP       DW 0
V30_SP_SAVE     DW 0            ; SP V30 (со смещением #4000) на время подпрограмм
; Быстрые версии циклов (генератор, loopgen.py): число проходов - 1, страница диапазона,
; страница W2 цикла, начальные IX/IY и адреса окна для неизменных регистров.
LOOP_N1         DW 0
LOOP_PAGE       DB 0
LOOP_W2         DB 0
LOOP_IX         DW 0
LOOP_IY         DW 0
LOOP_BIAS_IX    DW 0
LOOP_BIAS_IY    DW 0
LOOP_SLOTL      DB 0
LOOP_SLOTH      DB 0
LOOP_SLOT0      DW 0
LOOP_SLOT1      DW 0
LOOP_SLOT2      DW 0
LOOP_SLOT3      DW 0
LOOP_SLOT4      DW 0
LOOP_SLOT5      DW 0
LOOP_SLOT6      DW 0
LOOP_SLOT7      DW 0
TEMP_EA         DW 0
MISS_IP         DW 0

; --- состояние платы M72 ---------------------------------------------------------------
IN0             DW INIT_IN0
IN1             DW INIT_IN1
DSW             DW INIT_DSW
PIC_BASE        DB INIT_PIC_BASE
PIC_MASK        DB INIT_PIC_MASK
PIC_STEP        DB INIT_PIC_STEP
VID_FLIP        DB INIT_VID_FLIP
VID_OFF         DB INIT_VID_OFF
SCROLL_Y0       DW INIT_SCROLL_Y0
SCROLL_X0       DW INIT_SCROLL_X0
SCROLL_Y1       DW INIT_SCROLL_Y1
SCROLL_X1       DW INIT_SCROLL_X1
RASTER_RAW      DW INIT_RASTER_RAW  ; значение портов 6/7 (9 бит): позиция = raw - 128
DMA_COUNT       DW INIT_DMA
AFTER_RASTER    DS 8            ; скроллы после IRQ2 (Y0 X0 Y1 X1)
RASTER_ROW      DW #FFFF        ; строка растра этого кадра или #FFFF
SOUND_QUEUE     DS 32           ; команды звука кадра для адаптера
; Пометки изменений для адаптера FT812 (снимает адаптер после вывода кадра), ненулевой байт —
; изменение: VRAM слоя 0 (страница V30 #34) и слоя 1 (#36) — байт на группу из 8 тайлов строки
; (смещение >> 5) и байт на строку (H смещения); палитры банка 0 (#32) и банка 1 (#33) — байт на
; палитру ((слово & #FF) >> 4, слово = смещение >> 1, смещения #000…#BFF).
VRAM_DIRTY0     DS 512
VRAM_ROWS0      DS 64
VRAM_DIRTY1     DS 512
VRAM_ROWS1      DS 64
PAL_DIRTY0      DS 16
PAL_DIRTY1      DS 16
PEN_DIRTY0      DS 32           ; ядро переноса палитр: бит изменённого пера, слово на палитру банка 0
PEN_DIRTY1      DS 32           ; банка 1
VIDEO_DIRTY     DB 0            ; ненулевой — есть пометки
SOUND_COUNT     DB 0
FRAME_COUNT     DW 0
                ifdef RTYPE_LASTSTAGE
LAST_STAGE_ARMED DB 0           ; монета брошена — это настоящая игра, а не аттракт
                endif
                ifdef RTYPE_CREDITS
                ifndef CREDITS_FRAME
CREDITS_FRAME   EQU 900         ; кадр прыжка в титры (около 15 с от включения; можно задать -DCREDITS_FRAME=N)
                endif
                endif

; --- запуск -------------------------------------------------------------------------------
; Самостоятельный цикл (сверка и отладочный SPG): хуки платформы вокруг шага кадра.
Start:          di
                ld sp,STACK_TOP
                call RuntimeInit
FrameLoop:      call HOST_BEFORE
                call FrameStep
                call HOST_AFTER
                jp FrameLoop

RuntimeInit:    ld a,V30_PAGE_BASE+WORK_PAGE
                ld bc,PORT_PAGE1
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a
                ; Кэши баз сегментов из начальных значений регистров.
                ld hl,(V_ES)
                call SEGSET_ES
                ld hl,(V_CS)
                call SEGSET_CS
                ld hl,(V_SS)
                call SEGSET_SS
                ld hl,(V_DS)
                jp SEGSET_DS

; --- вызовы платформы -------------------------------------------------------------------------
; Цикл app.main исполняется кодом p2c в другой раскладке окон; он вызывает машину через
; страницу переключения SWITCH_PAGE (окно W3): A — номер вызова, HL и E — аргументы,
; результат — DE; стек — стек драйвера этой страницы. Перед возвратом в W3 ставится
; SWITCH_PAGE. Окно W2 при входе занято чужой страницей.
;   0 — инициализация; 1 — шаг кадра: L — маска игрока (биты как _input_mask: вправо 1,
;   влево 2, вниз 4, вверх 8, огонь #10, Force #20), E — бит 0 start1, бит 1 coin1, бит 2 —
;   мышь 1/2 (надпись vdac2p_label.asm), бит 3 — шаг R-9 от клавиш и джойстика ×2 (Esc: N_2027
;   vdac2p_native2.asm и надпись), бит 7 — вывод кадра адаптером FT812; 2 — слово
;   рабочего ОЗУ: HL — адрес − #40000; 3 — новая машина
;   (состояние после загрузки); 4 — сброс видеоадаптера (RAM_G занимал вывод титула); 5 — открыть
;   пак уровней на SD-карте (результат — состояние: 1 — открыт, 2 — ошибка); 6 — показанный кадр
;   машины гаснет в чёрное (перед выводом титула в RAM_G кадра); 7 — шаг кадра звука
;   (TargetAudio.step_frame); 8 — сброс звука сессии (TargetAudio.reset_session); 9 — мышь — координаты R-9:
;   L — смещение X, H — смещение Y в отсчётах мыши за кадр (ApiMouse); 10 — шаг предзагрузки звука (загрузчик SPG,
;   rtype_boot.asm: сэмпл GS или блок эффектов AY за вызов; результат — секторов пака прочитано, 0 — грузить нечего).
;   Команды звука шага (очередь SOUND_QUEUE) звуковой адаптер получает в конце вызова 1.
ApiCall:        ld (API_ARG),hl
                ld l,a
                ld a,#FF
                ld (W2_PAGE),a
                ld a,l
                ld hl,(API_ARG)
                or a
                jr z,ApiInit
                dec a
                jr z,ApiStep
                dec a
                jr z,ApiWord
                dec a
                jp z,ApiReboot
                dec a
                jr z,ApiVideoReset
                dec a
                jr z,ApiDataOpen
                dec a
                jr z,ApiVideoFade
                dec a
                jr z,ApiSoundFrame
                dec a
                jr z,ApiSoundReset
                dec a
                jp z,ApiMouse
                dec a
                jr z,ApiSoundPreload
ApiReturn:      ld a,SWITCH_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                ret
ApiInit:        call RuntimeInit
                jr ApiReturn
ApiVideoReset:  ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call HOST_ENTRY_VIDEO_RESET
                jr ApiReturn
ApiDataOpen:    ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call HOST_ENTRY_DATA_OPEN
                jr ApiReturn
ApiVideoFade:   ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call HOST_ENTRY_VIDEO_FADE
                jr ApiReturn
ApiSoundFrame:  call MapSound
                call SOUND_ENTRY_FRAME
                jr ApiReturn
ApiSoundReset:  call MapSound
                call SOUND_ENTRY_RESET
                jr ApiReturn
ApiSoundPreload: call MapSound
                call SOUND_ENTRY_PRELOAD
                jr ApiReturn
MapSound:       ld a,SOUND_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                ret
ApiWord:        ld a,V30_PAGE_BASE+WORK_PAGE
                ld bc,PORT_PAGE1
                out (c),a
                ld de,#4000
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                jr ApiReturn
; Ввод как Inputs.set_player / set_system эталона: IN0 = (IN0 | #CF) & ~биты игрока,
; IN1 = (IN1 | #05) & ~(start1 1 | coin1 4).
ApiStep:        ld a,e
                ld (API_FLAGS),a
                and #80                         ; кадр показывает машину (демо или игра), а не экран
                ld (API_SHOW),a                 ; оболочки: этот бит, в отличие от API_FLAGS, не снимает
                                                ; пропуск вывода при отставании от развёртки. Для звука
                                                ; разница решающая: по API_FLAGS фильтр титула считал
                                                ; «нашим экраном» каждый пропущенный кадр игры и выбрасывал
                                                ; эффекты — отсюда паузы в звуке (жалоба 2026-09-20).
                ld a,l
                and #0F
                ld b,a
                bit 4,l
                jr z,.noFire
                set 7,b                         ; кнопка 1
.noFire:        bit 5,l
                jr z,.noForce
                set 6,b                         ; кнопка 2
.noForce:       ld a,b
                cpl
                ld b,a
                ld a,(IN0)
                or #CF
                and b
                ld (IN0),a
                ld b,#FF
                bit 0,e
                jr z,.noStart
                res 0,b
.noStart:       bit 1,e
                jr z,.noCoin
                res 2,b
.noCoin:        ld a,(IN1)
                or #05
                and b
                ld (IN1),a
                ld a,(API_FLAGS)
                rlca
                jr nc,.frame
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call HOST_ENTRY_VIDEO_SKIP      ; отставание от развёртки — шаг без вывода
                jr c,.skip
                call HOST_ENTRY_VIDEO_BEFORE
                jr .frame
.skip:          ld hl,API_FLAGS
                res 7,(hl)                      ; и после шага адаптер не зовётся
.frame:         call FrameStep
                ld a,(API_FLAGS)
                rlca
                jr nc,.sound
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                call HOST_ENTRY_AFTER
.sound:         ld a,(SOUND_COUNT)
                or a
                jp z,ApiReturn
                call MapSound
                call SOUND_ENTRY_COMMANDS
                jp ApiReturn
; Новая машина: страницы V30, которые ROM меняет (рабочее ОЗУ, спрайты, палитры, VRAM), буфер
; спрайтов и данные резидента до стека помощников — из копий состояния после загрузки
; (страницы PRISTINE_*), DMA RAM→RAM по 16 КБ.
ApiReboot:      ld hl,PRISTINE_TABLE
.page:          ld a,(hl)
                or a
                jr z,.resident
                inc hl
                ld d,(hl)                       ; D — источник, A — приёмник
                inc hl
                push hl
                ld e,a
                ld hl,0
                ld bc,#4000
                call DmaCopy
                pop hl
                jr .page
.resident:      ld a,PRISTINE_RESIDENT
                ld d,a
                ld e,RES_PAGE
                ld hl,0
                ld bc,HELPER_TOP
                call DmaCopy
                call RuntimeInit
                jp ApiReturn
; DMA RAM→RAM: D — страница источника, E — страница приёмника, HL — смещение (то же в обеих),
; BC — чётное число байт, кратное 512. Портит AF, BC.
DmaCopy:        push de
                push hl
                ld a,l
                push bc
                ld bc,DMASADDRL
                out (c),a
                ld bc,DMADADDRL
                out (c),a
                ld a,h
                ld bc,DMASADDRH
                out (c),a
                ld bc,DMADADDRH
                out (c),a
                ld a,d
                ld bc,DMASADDRX
                out (c),a
                ld a,e
                ld bc,DMADADDRX
                out (c),a
                pop bc
                ld a,#FF
                push bc
                ld bc,DMALEN
                out (c),a                       ; пакет 256 слов
                pop bc
                ld a,b
                srl a                           ; пакетов = байт / 512
                dec a
                ld bc,DMANUM
                out (c),a
                ld a,DMA_RAM
                ld bc,DMACTR
                out (c),a
.wait:          ld bc,DMASTATUS
                in a,(c)
                and DMA_WNR
                jr nz,.wait
                pop hl
                pop de
                ret
; Страницы для новой машины: приёмник, источник; 0 — конец.
PRISTINE_TABLE: DB V30_PAGE_BASE+#10, PRISTINE_V30_PAGE0
                DB V30_PAGE_BASE+#30, PRISTINE_V30_PAGE0+1
                DB V30_PAGE_BASE+#32, PRISTINE_V30_PAGE0+2
                DB V30_PAGE_BASE+#33, PRISTINE_V30_PAGE0+3
                DB V30_PAGE_BASE+#34, PRISTINE_V30_PAGE0+4
                DB V30_PAGE_BASE+#36, PRISTINE_V30_PAGE0+5
                DB SPRITE_BUFFER_PAGE, PRISTINE_V30_PAGE0+6
                DB 0
API_ARG         DW 0
API_FLAGS       DB 0
API_KEYS2X      EQU 8                   ; бит 3 флагов шага: шаг R-9 от клавиш и джойстика ×2 (Esc; n2.NKeys2x, надпись)
API_SHOW        DB 0                    ; бит 7 шага: кадр принадлежит машине, а не экрану оболочки
; Мышь — источник координат R-9 (решение пользователя; отступление от эталона на аппаратном пределе ввода: у M72 нет
; мыши, координаты задаёт вход платформы). L — смещение X (вправо — плюс), H — смещение Y (вверх — плюс, как ось Y
; ROM) в отсчётах мыши за кадр, со знаком; скачки больше 63 отсчётов ввод p2c отбрасывает. Чувствительность — как в
; первых версиях порта (arcade_game.asm: 2 логических пикселя 640×480 на отсчёт; нативные X = логический·3/5 + $0150,
; Y = $0176 − логический·8/15): X — 1,2 пикселя M72 на отсчёт (MOUSE_X_Q8 = 307/256), Y — 16/15 (MOUSE_Y_Q8 =
; 273/256); на экране FT812 оба — 3,2 физических пикселя. Позиция R-9 — 24 бита Q8 ([bp+3..5] и [bp+7..9] при
; bp = $0020, интегрирование скорости $0672/$0689): смещение прибавляется к ней целиком, целая часть — в рамки, которыми
; обработчик сам ограничивает корабль (IP $2109…$2146, линейные $02509…$02546): X $015C…$02A0, Y $009A…$0174. Только у
; R-9 со штатным обработчиком $2027 (слово DS:$0020; запуск, смерть и возрождение не трогаются) и без автопилота
; [$2FC1] (ROM сам ведёт корабль). Окно W1 при входе — рабочее ОЗУ V30 (SwitchEnter); DS машины — #40000.
MOUSE_X_Q8      EQU 307
MOUSE_Y_Q8      EQU 273
ApiMouse:       ld a,(#4000+#0021)
                cp #20
                jp nz,ApiReturn
                ld a,(#4000+#0020)
                cp #27
                jp nz,ApiReturn
                ld a,(#4000+#2FC1)
                or a
                jp nz,ApiReturn
                ld a,h
                ld (API_FLAGS),a                ; смещение Y — на время оси X
                ld a,l
                ld de,MOUSE_X_Q8
                call MulSigned8
                ex de,hl                        ; DE — смещение X в Q8
                ld a,d
                rlca
                sbc a,a
                ld c,a                          ; C — знак смещения (старший байт 24-битного)
                ld hl,(#4000+#0023)             ; дробный и младший целый байты X
                add hl,de
                ld (#4000+#0023),hl
                ld a,(#4000+#0025)
                adc a,c
                ld (#4000+#0025),a
                ld hl,(#4000+#0024)
                ld de,#015C
                ld bc,#02A0
                call Clamp16
                ld (#4000+#0024),hl             ; целая часть X — в рамки
                ld a,(API_FLAGS)
                ld de,MOUSE_Y_Q8
                call MulSigned8
                ex de,hl                        ; DE — смещение Y в Q8
                ld a,d
                rlca
                sbc a,a
                ld c,a
                ld hl,(#4000+#0027)             ; дробный и младший целый байты Y
                add hl,de
                ld (#4000+#0027),hl
                ld a,(#4000+#0029)
                adc a,c
                ld (#4000+#0029),a
                ld hl,(#4000+#0028)
                ld de,#009A
                ld bc,#0174
                call Clamp16
                ld (#4000+#0028),hl             ; целая часть Y — в рамки
                jp ApiReturn
; HL = A·DE: A — со знаком, DE — множитель без знака, произведение — в пределах слова со знаком. Портит AF, B, DE.
MulSigned8:     ld hl,0
                ld b,8
                or a
                push af                         ; флаг S — знак A
                jp p,.loop
                neg                             ; модуль (у −128 — #80, верный как беззнаковый)
.loop:          add hl,hl                       ; сдвиг-сложение от старшего бита A
                rla
                jr nc,.next
                add hl,de
.next:          djnz .loop
                pop af
                ret p
                ex de,hl                        ; отрицательный A: HL = 0 − произведение
                ld hl,0
                or a
                sbc hl,de
                ret
; HL = наименьшее из BC и наибольшего из HL и DE (значения без знака; сравнения как `jae`/`jb` обработчика ROM).
; Портит AF.
Clamp16:        or a
                sbc hl,de
                add hl,de
                jr nc,.aboveMin
                ex de,hl                        ; меньше нижней рамки — рамка
                ret
.aboveMin:      or a
                sbc hl,bc
                add hl,bc
                ret c                           ; меньше верхней рамки
                ld h,b
                ld l,c                          ; не меньше верхней — рамка (как `jb` ROM)
                ret

; Шаг кадра M72.
FrameStep:
INPUT_HOOK:     ; точка остановки модели: ввод кадра записан в IN0/IN1
                ifdef RTYPE_INVINCIBLE
                ; Диагностика: бессмертие игрока — латч неуязвимости эталона $2FC6 рабочего ОЗУ V30 (окно W1
                ; всегда WORK_PAGE) взводится каждый кадр, как это делают модельные проверки. Нужно, чтобы
                ; пройти все восемь этапов со снимками. В релизный SPG не входит: собирается только при
                ; определении RTYPE_INVINCIBLE (переменная сборки RTYPE_ASM_DEFINES).
                ld a,1
                ld (#4000+#2FC6),a
                endif
                ifdef RTYPE_LASTSTAGE
                ; Диагностика: игра начинается с последнего этапа — так концовку видно в настоящих
                ; условиях, а не врезкой. Механизм штатный, ROM: таблица чекпойнтов `ES:$87FA` по
                ; 14 байт, номер записи лежит в байте чекпойнта игрока `$2F42` (живой — `$2F2D`),
                ; а `$F01B` по нему поднимает progression, полосы, скорости и палитру этапа. Запись 15 —
                ; этап 8 (progression $5400), записи 0…3 — этап 1. Пишем номер, пока номер этапа `$2FCD`
                ; не станет восьмым. В релизный SPG не входит.
                ; Подставлять номер записи можно только для настоящей игры: аттракт ROM гоняет демо тем же
                ; кодом, и если писать номер всегда, демо идёт с позднего уровня — в оригинале не так.
                ; Признак настоящей игры — брошенная монета: бит 2 IN1 активен низким (set_system эталона).
                ld a,(IN1)
                bit 2,a
                jr nz,.noCoin
                ld a,1
                ld (LAST_STAGE_ARMED),a
.noCoin:        ld a,(LAST_STAGE_ARMED)
                or a
                jr z,.lastStageDone
                ld a,(#4000+#2FCD)
                cp 8
                jr z,.lastStageDone
                ld a,15
                ld (#4000+#2F42),a
                ld (#4000+#2F2D),a
.lastStageDone:
                endif
                ifdef RTYPE_CREDITS
                ; Диагностика: прыжок в конечные титры, чтобы ловить их глюк, не проходя восемь этапов.
                ; Аркада создаёт объект титров событием этапа 8 `$EEAB`: `cx = $0100`, `dx = $EEB5`,
                ; аллокатор `$03A6`. Инициализатор `$EEB5` ставит полям объекта `+$10 = $88E8` (таблица
                ; записей текста `$88E8…$8911`), `+$12 = $30`, `+$14 = $560` и переводит обработчик
                ; `+$00` на `$EF09`. Слот директора по линейному `$40000` (окно W1 — WORK_PAGE, то есть
                ; #4000) имеет ту же раскладку полей, поэтому хватает записи `$EEB5` в его слово
                ; обработчика. Пишем ровно на кадре CREDITS_FRAME: FRAME_COUNT растёт по кадру, так что
                ; совпадение одно. К этому кадру титул уже пройден и игра идёт (автоклавиша ini — 1.6 с).
                ; В релизный SPG не входит: собирается только при определении RTYPE_CREDITS.
                ld hl,(FRAME_COUNT)
                ld de,CREDITS_FRAME
                or a
                sbc hl,de
                jr nz,.creditsSkip
                ld hl,#EEB5
                ld (#4000+#0000),hl
.creditsSkip:
                endif
                xor a
                ld (SOUND_COUNT),a
                ; Шаг кадра как RTypeM72Machine.step_frame: IRQ2 при позиции растра 0..255, затем IRQ0.
                ld hl,#FFFF
                ld (RASTER_ROW),hl
                ld hl,(RASTER_RAW)
                ld a,h
                and 1
                ld h,a
                ld de,128
                or a
                sbc hl,de
                jr c,.noRaster          ; raw < 128: позиция отрицательная
                ld a,h
                or a
                jr nz,.noRaster         ; позиция >= 256
                ld (RASTER_ROW),hl
                ld a,2
                call IRQ
                ld hl,SCROLL_Y0
                ld de,AFTER_RASTER
                ld bc,8
                ldir
.noRaster:      xor a
                call IRQ
                ld hl,(FRAME_COUNT)
                inc hl
                ld (FRAME_COUNT),hl
FRAME_HOOK:     ; точка остановки модели: кадр исполнен
                ret

; --- платформа ------------------------------------------------------------------------
; Хуки SPG вокруг кадра: страница HOST_PAGE (адаптеры ввода, видео и звука) в окне W3 и вызов
; её входа на стеке драйвера. Загрузчик SPG ставит HOST_PRESENT = 1; в модели сверки
; HOST_PRESENT = 0 и хуки сразу возвращаются.
HOST_PRESENT    DB 0
HOST_BEFORE:    ld a,(HOST_PRESENT)
                or a
                ret z
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                jp HOST_ENTRY_BEFORE
HOST_AFTER:     ld a,(HOST_PRESENT)
                or a
                ret z
                ld a,HOST_PAGE
                ld bc,PORT_PAGE3
                out (c),a
                jp HOST_ENTRY_AFTER

; --- прерывание ------------------------------------------------------------------------
; Вход: A = номер IRQ. Как RTypeM72Machine.interrupt: при маске — возврат; иначе в стек
; V30 FLAGS, CS, IP; FLAGS без IF и TF; CS:IP из вектора PIC_BASE + номер; исполнение до
; точки простоя. Тело — во второй нативной странице (n2.IrqEnter, VDAC2+ 2026-09-26: быстрый
; вход без PUSHW и чтения вектора через окно W2 — в резиденте ему нет места): отображение её
; в W3 и переход.
IRQ:            ld e,a
                ld a,NATIVE_PAGE1
                ld bc,PORT_PAGE3
                out (c),a
                ld a,e
                jp n2.IrqEnter

; Точка простоя: DE = IP V30, возврат в драйвер кадра.
IDLE_EXIT:      ld (V_IP),de
                ld hl,#C000
                add hl,sp
                ld (V_SP),hl
                ld sp,(DRIVER_SP)
                ret

; Слово по линейному адресу HL в сегменте 0 → DE.
RW_LIN0:        ld de,0
                xor a
                jp RW_COMMON

; --- диспетчеризация по IP ----------------------------------------------------------------
; Вход: DE = IP. Сначала кэш из двух путей по 256 записей, индекс — младший байт IP: массивы
; RC_IPH (старший байт IP), RC_PAGE (страница кода), RC_LO/RC_HI (адрес) и те же массивы
; второго пути RC2_* на 4 страницы H выше. Сборка заполняет записи действительными входами
; (или остановом MISS для младших байтов без входов). При промахе обоих путей — прямая
; таблица: 16 страниц DISPATCH_BASE + (IP >> 12), по 4 байта на IP со смещения
; (IP & #FFF) * 4: страница кода, адрес (мл., ст.), 0; найденный вход записывается в первый
; путь, прежняя запись первого пути переходит во второй.
; Страница #FF — у IP нет входа переведённой программы: останов с MISS_IP.
DISPATCH:       ld h,RC_IPH/256
                ld l,e
                ld a,(hl)
                cp d
                jr nz,DISPATCH_WAY2
DISPATCH_HIT:   inc h
                ld a,(hl)
                inc h
                ld c,(hl)
                inc h
                ld h,(hl)
                ld l,c
                ld bc,PORT_PAGE3
                out (c),a
                jp (hl)
DISPATCH_WAY2:  ld h,RC2_IPH/256
                ld a,(hl)
                cp d
                jr z,DISPATCH_HIT
DISPATCH_SLOW:  ld (V_IP),de
                ld a,d
                rrca
                rrca
                rrca
                rrca
                and #0F
                add a,DISPATCH_BASE
                ld bc,PORT_PAGE3
                out (c),a
                ld a,d
                and #0F
                ld h,a
                ld l,e
                add hl,hl
                add hl,hl
                ld a,h
                or #C0
                ld h,a
                ld a,(hl)
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                cp #FF
                jr z,.miss
                ld c,a
                ld hl,(V_IP)
                ld b,h
                ld h,RC_IPH/256
                ld a,(hl)                   ; запись первого пути → второй путь (H + 4)
                ld (hl),b
                set 2,h
                ld (hl),a
                res 2,h
                inc h
                ld a,(hl)
                ld (hl),c
                set 2,h
                ld (hl),a
                res 2,h
                inc h
                ld a,(hl)
                ld (hl),e
                set 2,h
                ld (hl),a
                res 2,h
                inc h
                ld a,(hl)
                ld (hl),d
                set 2,h
                ld (hl),a
                ld a,c
                ld bc,PORT_PAGE3
                out (c),a
                ex de,hl
                jp (hl)
.miss:          ld de,(V_IP)

MISS:           ld (MISS_IP),de
                ld hl,#C000
                add hl,sp
                ld (V_SP),hl
                ld a,2
                ld bc,PORT_BORDER
                out (c),a
MISS_HOOK:      jr MISS_HOOK

; Отказ переведённой программы (дальний переход и т. п.): DE = IP.
FAULT:          ld (MISS_IP),de
                ld hl,#C000
                add hl,sp
                ld (V_SP),hl
                ld a,6
                ld bc,PORT_BORDER
                out (c),a
FAULT_HOOK:     jr FAULT_HOOK

; Переход в код другой страницы: A = страница, HL = адрес.
FARJP:          ld bc,PORT_PAGE3
                out (c),a
                jp (hl)

; --- сегменты -------------------------------------------------------------------------------
; Вход: HL = значение сегментного регистра. Базу для линейного адреса вычисляют только
; подпрограммы обращения к памяти (SEGLOAD) — переведённый код пишет регистр напрямую.
SEGSET_ES:      ld (V_ES),hl
                ret
SEGSET_CS:      ld (V_CS),hl
                ret
SEGSET_SS:      ld (V_SS),hl
                ret
SEGSET_DS:      ld (V_DS),hl
                ret

; --- память V30 -----------------------------------------------------------------------------
; Отображение страницы V30 A (не WORK_PAGE) в W2. Сохраняет HL, DE; портит BC.
MAP_W2:         ld (W2_PAGE),a
                add a,V30_PAGE_BASE
                ld bc,PORT_PAGE2
                out (c),a
                ret

; Линейный адрес: HL = смещение, DE = база (мл. 16 бит), A = старшие 4 бита. Выход: HL —
; адрес байта в окне (рабочее ОЗУ — W1, иначе W2), LIN_PAGE — страница; портит A, BC.
LIN_W1:         add hl,de
                adc a,0
                and #0F
                add a,a
                add a,a
                ld b,a
                ld a,h
                rlca
                rlca
                and 3
                or b
                ld (LIN_PAGE),a
                cp WORK_PAGE
                jr z,.work
                ld b,a
                ld a,(W2_PAGE)
                cp b
                ld a,b
                call nz,MAP_W2
                ld a,h
                and #3F
                or #80
                ld h,a
                ret
.work:          ld a,h
                and #3F
                or #40
                ld h,a
                ret

; Следующий байт после HL (линейный адрес + 1): конец окна → следующая страница V30.
NEXT_W1:        ld a,l
                inc a
                jr nz,.inc
                ld a,h
                and #3F
                cp #3F
                jr nz,.inc
                ld a,(LIN_PAGE)
                inc a
                and 63
                ld (LIN_PAGE),a
                cp WORK_PAGE
                ld hl,#4000
                ret z
                call MAP_W2
                ld hl,#8000
                ret
.inc:           inc hl
                ret

; База сегмента: DE = (сегмент << 4) & #FFFF, A = сегмент >> 12; HL сохраняется.
SEGLOAD_ES:     ld de,(V_ES)
                jr SEGLOAD_COMMON
SEGLOAD_CS:     ld de,(V_CS)
                jr SEGLOAD_COMMON
SEGLOAD_SS:     ld de,(V_SS)
                jr SEGLOAD_COMMON
SEGLOAD_DS:     ld de,(V_DS)
SEGLOAD_COMMON: ld a,d
                rrca
                rrca
                rrca
                rrca
                and #0F
                sla e
                rl d
                sla e
                rl d
                sla e
                rl d
                sla e
                rl d
                ret

; Чтение байта: HL = смещение → A.
RB_ES:          call SEGLOAD_ES
                jr RB_COMMON
RB_CS:          call SEGLOAD_CS
                jr RB_COMMON
RB_SS:          call SEGLOAD_SS
                jr RB_COMMON
RB_DS:          call SEGLOAD_DS
RB_COMMON:      call LIN_W1
                ld a,(hl)
                ret

; Чтение слова: HL = смещение → DE.
RW_ES:          call SEGLOAD_ES
                jr RW_COMMON
RW_CS:          call SEGLOAD_CS
                jr RW_COMMON
RW_SS:          call SEGLOAD_SS
                jr RW_COMMON
RW_DS:          call SEGLOAD_DS
RW_COMMON:      call LIN_W1
                ld e,(hl)
                call NEXT_W1
                ld d,(hl)
                ret

; Запись байта: HL = смещение, A = значение (зеркало палитры — как _palette_write).
WB_ES:          push af
                call SEGLOAD_ES
                jr WB_COMMON
WB_CS:          push af
                call SEGLOAD_CS
                jr WB_COMMON
WB_SS:          push af
                call SEGLOAD_SS
                jr WB_COMMON
WB_DS:          push af
                call SEGLOAD_DS
WB_COMMON:      call LIN_W1
                pop af
                ld (hl),a
                jp VIDEO_MARK_LIN

; Запись слова: HL = смещение, DE = значение.
WW_ES:          push de
                call SEGLOAD_ES
                jr WW_COMMON
WW_CS:          push de
                call SEGLOAD_CS
                jr WW_COMMON
WW_SS:          push de
                call SEGLOAD_SS
                jr WW_COMMON
WW_DS:          push de
                call SEGLOAD_DS
WW_COMMON:      call LIN_W1
                pop de
                ld (hl),e
                call VIDEO_MARK_LIN
                call NEXT_W1
                ld (hl),d
                jp VIDEO_MARK_LIN

; --- пометки видеопамяти ------------------------------------------------------------------------
; VIDEO_MARK_LIN: HL — адрес окна записанного байта, LIN_PAGE — его страница V30.
; VIDEO_W2_MARK1 / VIDEO_W2_MARK2 / VIDEO_W2_MARK2BC: HL (BC) — адрес окна W2 записанного байта /
; второго байта слова (помечаются оба), страница — W2_PAGE. VIDEO_MARK_DE: A — страница V30,
; DE — смещение. VIDEO_MARK: A — страница V30, HL — смещение. Все сохраняют AF, BC, DE, HL.
VIDEO_MARK_LIN: push af
                ld a,(LIN_PAGE)
                jr VIDEO_WINDOW
VIDEO_W2_MARK2BC:
                push hl
                ld h,b
                ld l,c
                call VIDEO_W2_MARK2
                pop hl
                ret
VIDEO_MARK_DE:  push hl
                ex de,hl
                call VIDEO_MARK
                ex de,hl
                pop hl
                ret
; Второй байт слова: первый байт — в той же группе тайлов и той же палитре, если смещение
; второго байта не кратно 32.
VIDEO_W2_MARK2: push af
                ld a,l
                and 31
                jr nz,.one
                dec hl
                call VIDEO_W2_MARK1
                inc hl
.one:           pop af
VIDEO_W2_MARK1: push af
                ld a,(W2_PAGE)
VIDEO_WINDOW:   sub #32
                cp 5
                jr nc,.done
                add a,#32
                push hl
                push af
                ld a,h
                and #3F
                ld h,a
                pop af
                call VIDEO_MARK
                pop hl
.done:          pop af
                ret
VIDEO_MARK:     push af
                push de
                push hl
                cp #34
                jr z,.vram0
                cp #36
                jr z,.vram1
                ld de,PAL_DIRTY0
                cp #32
                jr z,.palette
                ld de,PAL_DIRTY1
                cp #33
                jr nz,.done
.palette:       ld a,h
                cp #0C
                jr nc,.done
                ; палитра = ((смещение >> 1) & #FF) >> 4 = (H & 1) * 8 + (L >> 5)
                and 1
                add a,a
                add a,a
                add a,a
                ld h,a
                ld a,l
                rlca
                rlca
                rlca
                and 7
                or h
                ld l,a
                ld h,0
                add hl,de
                ld (hl),#FF
                ld de,PAL_SYNC-PAL_DIRTY0
                add hl,de
                ld (hl),0                       ; слот памяти палитр переписан мимо ядра переноса
                ld de,-PAL_SYNC
                add hl,de                       ; HL = r (группа·16 + палитра)
                add hl,hl
                ld de,PEN_CHG
                add hl,de
                ld (hl),#FF
                inc hl
                ld (hl),#FF                     ; перенос сверяет все перья слота (v30z80_kernels.asm)
                jr .flag
.vram0:         ld de,VRAM_DIRTY0
                jr .vram
.vram1:         ld de,VRAM_DIRTY1
.vram:          ; группа = смещение >> 5 = H·8 + (L >> 5); строка = H
                ld a,l
                rlca
                rlca
                rlca
                and 7
                ld l,a
                ld a,h
                push hl
                add a,a
                add a,a
                add a,a
                or l
                ld l,a
                ld a,h
                rlca
                rlca
                rlca
                and 1
                ld h,a
                add hl,de
                ld (hl),#FF
                pop hl
                ld l,h
                ld h,0
                inc d
                inc d                   ; сводка строк = таблица + 512
                add hl,de
                ld (hl),#FF
.flag:          ld a,1
                ld (VIDEO_DIRTY),a
.done:          pop hl
                pop de
                pop af
                ret
; Пометка диапазона при входе в быструю версию цикла: A — страница V30, HL — смещение первого
; байта, DE — смещение последнего байта той же страницы (DE >= HL). Группы тайлов и палитры —
; по 32 байта. Сохраняет A, BC, DE; портит F, HL.
VIDEO_MARK_RANGE:
                call VIDEO_MARK
                push af
                ld a,l
                or 31
                ld l,a
                inc hl                          ; начало следующей группы
                pop af
                push hl
                scf
                sbc hl,de                       ; перенос — HL <= DE
                pop hl
                jr c,VIDEO_MARK_RANGE
                ret
VIDEO_BITS:     DB 1,2,4,8,16,32,64,128

; --- стек V30 ---------------------------------------------------------------------------------
; PUSHW: DE → SS:SP-2. POPW: SS:SP → DE.
PUSHW:          ld hl,(V_SP)
                dec hl
                dec hl
                ld (V_SP),hl
                jp WW_SS
POPW:           ld hl,(V_SP)
                push hl
                call RW_SS
                pop hl
                inc hl
                inc hl
                ld (V_SP),hl
                ret

; --- порты M72 ---------------------------------------------------------------------------------
; IN: HL = порт, A = размер (1/2) → HL = значение (байт в L).
PORT_IN:        ld b,a
                ld a,h
                or a
                jr nz,.none
                ld a,l
                cp 6
                jr nc,.pic
                ; 0..1 IN0, 2..3 IN1, 4..5 DSW: байт порта base — младший, base+1 — старший
                ld c,l
                srl a
                add a,a
                ld e,a
                ld d,0
                ld hl,IN0
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,b
                cp 2
                jr z,.word
                ld a,c
                rra
                jr nc,.low
                ld l,d
                ld h,0
                ret
.low:           ld l,e
                ld h,0
                ret
.word:          ex de,hl
                ret
.pic:           cp #40
                jr c,.none
                cp #44
                jr nc,.none
                sub #40
                srl a
                or a
                ld hl,0
                ret z                   ; регистр 0 читается как 0
                ld a,(PIC_MASK)
                ld l,a
                ret
.none:          ld a,b
                cp 2
                ld hl,#FFFF
                ret z
                ld hl,#00FF
                ret

; OUT: HL = порт, DE = значение, A = размер.
PORT_OUT:       cp 2
                jr z,.sized
                ld d,0
.sized:         ld a,h
                or a
                ret nz
                ld a,l
                or a
                jr z,.sound
                cp 2
                jr z,.video
                cp 4
                jp z,SPRITE_DMA
                cp 6
                jr z,.raster
                cp 7
                jr z,.raster
                cp #40
                jr c,.scroll
                cp #44
                jr c,.pic
.scroll:        cp #80
                ret c
                cp #87
                ret nc
                bit 0,a
                ret nz
                sub #80
                ld c,a
                ld b,0
                ld hl,SCROLL_Y0
                add hl,bc
                ld (hl),e
                inc hl
                ld (hl),d
                ret
.sound:         ld a,(SOUND_COUNT)
                cp 32
                ret nc
                ld c,a
                inc a
                ld (SOUND_COUNT),a
                ld b,0
                ld hl,SOUND_QUEUE
                add hl,bc
                ld (hl),e
                ret
.video:         ld a,e
                and 4
                ld (VID_FLIP),a
                ld a,e
                and 8
                ld (VID_OFF),a
                ret
.raster:        ld (RASTER_RAW),de
                ld a,d
                and 1
                ld (RASTER_RAW+1),a
                ret
.pic:           sub #40
                srl a
                ld c,a
                ld a,e
                jr nz,.picData
                ; регистр 0: бит 4 — ICW1
                bit 4,a
                ret z
                ld a,1
                ld (PIC_STEP),a
                xor a
                ld (PIC_MASK),a
                ret
.picData:       ld a,(PIC_STEP)
                cp 1
                jr nz,.picNext
                ld a,e
                and #F8
                ld (PIC_BASE),a
                ld a,2
                ld (PIC_STEP),a
                ret
.picNext:       cp 2
                jr z,.picStep
                cp 3
                jr z,.picStep
                ld a,e
                ld (PIC_MASK),a
                ret
.picStep:       inc a
                ld (PIC_STEP),a
                ret

; OUT 4: копия спрайтовой памяти #C0000..#C03FF в буфер кадра, IN1 |= #80. Копирует
; контроллер DMA TS-Config (страница спрайтов V30 → страница буфера, 2 пакета по 512 байт),
; процессор ждёт окончания; окна не меняются.
SPRITE_DMA:     xor a
                ld bc,DMASADDRL
                out (c),a
                ld bc,DMASADDRH
                out (c),a
                ld a,V30_PAGE_BASE+SPRITE_V30_PAGE
                ld bc,DMASADDRX
                out (c),a
                xor a
                ld bc,DMADADDRL
                out (c),a
                ld bc,DMADADDRH
                out (c),a
                ld a,SPRITE_BUFFER_PAGE
                ld bc,DMADADDRX
                out (c),a
                ld a,#FF
                ld bc,DMALEN
                out (c),a
                ld a,1
                ld bc,DMANUM
                out (c),a
                ld a,DMA_RAM
                ld bc,DMACTR
                out (c),a
.wait:          ld bc,DMASTATUS
                in a,(c)
                and DMA_WNR
                jr nz,.wait
                ld hl,(DMA_COUNT)
                inc hl
                ld (DMA_COUNT),hl
                ld a,(IN1)
                or #80
                ld (IN1),a
                ret

; --- блочный REP MOVSW ------------------------------------------------------------------------
; Страницы V30 известны при переводе: MV_SRC — источника (DS), MV_DST — приёмника (ES); базы
; сегментов кратны странице. Блоком, если DF = 0, CX < #2000, страницы различны, SI + 2CX и
; DI + 2CX не больше #4000: до 256 слов — контроллером DMA TS-Config (один пакет), больше —
; LDIR; иначе — пословно, как MOVSW_REP_DS. Результат как у CX шагов MOVSW.
MV_SRC          DB 0
MV_DST          DB 0
MV_COUNT        DW 0
REP_MOVSW_FAST: ld a,(V_FL+1)
                and 4
                jp nz,MOVSW_REP_DS
                ld hl,(V_CX)
                ld a,h
                or l
                ret z
                ld a,h
                cp #20
                jp nc,MOVSW_REP_DS
                add hl,hl
                ld (MV_COUNT),hl
                ld a,(MV_SRC)
                ld e,a
                ld a,(MV_DST)
                cp e
                jp z,MOVSW_REP_DS
                ld de,(MV_COUNT)
                ld hl,(V_SI)
                add hl,de
                jp c,MOVSW_REP_DS
                call MV_LIMIT
                jp c,MOVSW_REP_DS
                ld hl,(V_DI)
                add hl,de
                jp c,MOVSW_REP_DS
                call MV_LIMIT
                jp c,MOVSW_REP_DS
                ld hl,(V_CX)
                dec hl
                ld a,h
                or a
                jr z,.dma
                ld a,(MV_DST)
                cp WORK_PAGE
                jr z,.toWork
                call MAP_W2             ; приёмник — W2
                ld a,(MV_SRC)
                cp WORK_PAGE
                jr z,.srcWork
                add a,V30_PAGE_BASE     ; источник на время копии — в W1
                ld bc,PORT_PAGE1
                out (c),a
.srcWork:       ld hl,(V_SI)
                set 6,h
                ld de,(V_DI)
                set 7,d
                jr .copy
.toWork:        ld a,(MV_SRC)
                call MAP_W2             ; источник — W2, приёмник — рабочее ОЗУ в W1
                ld hl,(V_SI)
                set 7,h
                ld de,(V_DI)
                set 6,d
.copy:          ld bc,(MV_COUNT)
                ldir
                ld a,V30_PAGE_BASE+WORK_PAGE
                ld bc,PORT_PAGE1
                out (c),a
                jr .advance
.dma:           ld a,l                  ; L = CX - 1 слов в пакете
                ld bc,DMALEN
                out (c),a
                xor a
                ld bc,DMANUM
                out (c),a
                ld hl,(V_SI)
                ld a,l
                ld bc,DMASADDRL
                out (c),a
                ld a,h
                ld bc,DMASADDRH
                out (c),a
                ld a,(MV_SRC)
                add a,V30_PAGE_BASE
                ld bc,DMASADDRX
                out (c),a
                ld hl,(V_DI)
                ld a,l
                ld bc,DMADADDRL
                out (c),a
                ld a,h
                ld bc,DMADADDRH
                out (c),a
                ld a,(MV_DST)
                add a,V30_PAGE_BASE
                ld bc,DMADADDRX
                out (c),a
                ld a,DMA_RAM
                ld bc,DMACTR
                out (c),a
.wait:          ld bc,DMASTATUS
                in a,(c)
                and DMA_WNR
                jr nz,.wait
.advance:       ld a,(MV_DST)               ; приёмник — VRAM или палитра: пометить группы
                sub #32
                cp 5
                jr nc,.marked
                add a,#32
                ld hl,(V_DI)
                ld de,(MV_COUNT)
                ex de,hl
                add hl,de
                ex de,hl                        ; DE = конец диапазона, HL = начало
.mark:          call VIDEO_MARK                 ; группа из 8 тайлов VRAM / палитра — 32 байта
                ld a,l
                or 31
                ld l,a
                inc hl                          ; начало следующей группы
                push hl
                or a
                sbc hl,de
                pop hl
                ld a,(MV_DST)
                jr c,.mark
.marked:        ld de,(MV_COUNT)
                ld hl,(V_SI)
                add hl,de
                ld (V_SI),hl
                ld hl,(V_DI)
                add hl,de
                ld (V_DI),hl
                ld hl,0
                ld (V_CX),hl
                ret
; HL — конец диапазона (смещение + байтов): C, если больше #4000.
MV_LIMIT:       ld a,h
                cp #40
                ccf
                ret nc
                ret nz
                ld a,l
                or a
                ret z
                scf
                ret

; --- ADD4S NEC -------------------------------------------------------------------------------
; Упакованный BCD DS:SI → ES:DI, байтов (CL+1)/2; CF — перенос, ZF — все байты результата нулевые.
ADD4S:          ld a,(V_CX)
                inc a
                ld l,a
                ld h,0
                jr nz,.count
                ld h,1
.count:         srl h
                rr l
                ld (A4_COUNT),hl
                ld hl,0
                ld (A4_INDEX),hl
                xor a
                ld (A4_CARRY),a
                inc a
                ld (A4_ZERO),a
.loop:          ld hl,(A4_COUNT)
                ld de,(A4_INDEX)
                or a
                sbc hl,de
                jr z,.done
                ld hl,(V_SI)
                add hl,de
                call RB_DS
                ld (A4_SOURCE),a
                ld hl,(V_DI)
                ld de,(A4_INDEX)
                add hl,de
                call RB_ES
                ld b,a
                ld a,(A4_SOURCE)
                call BCD_TO_BIN
                ld c,a
                ld a,b
                call BCD_TO_BIN
                add a,c
                ld c,a
                ld a,(A4_CARRY)
                add a,c
                ld c,0
                cp 100
                jr c,.nocarry
                sub 100
                inc c
.nocarry:       ld b,a
                ld a,c
                ld (A4_CARRY),a
                ld a,b
                call BIN_TO_BCD
                or a
                jr z,.zero
                ld b,a
                xor a
                ld (A4_ZERO),a
                ld a,b
.zero:          ld hl,(V_DI)
                ld de,(A4_INDEX)
                add hl,de
                call WB_ES
                ld hl,(A4_INDEX)
                inc hl
                ld (A4_INDEX),hl
                jr .loop
.done:          ld hl,(V_FL)
                ld a,l
                and #BE
                ld l,a
                ld a,(A4_CARRY)
                or l
                ld l,a
                ld a,(A4_ZERO)
                or a
                jr z,.store
                set 6,l
.store:         ld (V_FL),hl
                ret
A4_COUNT        DW 0
A4_INDEX        DW 0
A4_SOURCE       DB 0
A4_CARRY        DB 0
A4_ZERO         DB 0

; A = упакованный BCD (оба полубайта могут быть > 9, как в эталоне: старший*10 + младший) → A.
BCD_TO_BIN:     push bc
                ld c,a
                and #0F
                ld b,a
                ld a,c
                rrca
                rrca
                rrca
                rrca
                and #0F
                ld c,a
                add a,a
                add a,a
                add a,c
                add a,a                 ; старший * 10
                add a,b
                pop bc
                ret
; A = 0..99 → упакованный BCD.
BIN_TO_BCD:     push bc
                ld b,0
.tens:          cp 10
                jr c,.ones
                sub 10
                inc b
                jr .tens
.ones:          ld c,a
                ld a,b
                rlca
                rlca
                rlca
                rlca
                or c
                pop bc
                ret

; --- флаги --------------------------------------------------------------------------------------
; Чётность младшего байта: PARITY[x] = #04 при чётном числе единиц (генерирует сборка).
PARITY:
                INCLUDE "parity.inc"

                INCLUDE "v30z80_flags.inc"

                INCLUDE "v30z80_kernels.asm"

                INCLUDE "v30z80_ring.asm"

                INCLUDE "vdac2p_early.asm"

                INCLUDE "vdac2p_sprites.asm"

; --- пулы картинок и полос хоста (VDAC2+ 2026-09-27; страница хоста заполнена — код здесь) -------------------------
; HL — номер картинки → HL — её запись (W1 — страница тайлов). Портит DE.
ImageAddress:   add hl,hl
                add hl,hl
                add hl,hl
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,de                       ; ·40
                ld de,#4000+IMAGE_TABLE
                add hl,de
                ret
                ASSERT IMAGE_ENTRY == 40

; Кандидат ALLOC_PAIR на вытеснение уже взят собираемой строкой? Ссылки строки группы на картинки (NEW_IREFS) хост
; прибавляет к их числам только после всех классов строки (ImagePositionUpdate), ссылки столбца на полосы (NEW_REFS) —
; после обоих слотов (PositionUpdate). Найденная в корзине картинка (полоса) без ссылок, отпущенная раньше прошлого
; кадра, до того выглядит свободной: ImageAlloc (StripAlloc) следующего класса (слота) вытеснял её и собирал под свой
; ключ — оба выводили одну картинку, на месте первого класса была дыра (этап 2, вспышка существа: кадр 15354 модели
; реального времени с пропусками вывода — v021 тоже). ImageRowTaken — среди NEW_IREFS, StripColumnTaken — среди
; NEW_REFS (незанятые слова — 0, с номером + 1 не совпадают). ZF = 1 — взят. Сохраняют HL; портят AF, B, DE.
ImageRowTaken:  push hl
                ld hl,NEW_IREFS
                ld b,IMAGE_REFS
                jr RefsTaken
StripColumnTaken:
                push hl
                ld hl,NEW_REFS
                ld b,2
RefsTaken:      ld de,(ALLOC_PAIR)
                inc de                          ; ссылка — номер + 1
.ref:           ld a,(hl)
                inc hl
                cp e
                jr nz,.next
                ld a,(hl)
                cp d
                jr z,.done                      ; ZF = 1 — взят
.next:          inc hl
                djnz .ref
                or h                            ; ZF = 0: H — старший байт адреса в хосте, не 0
.done:          pop hl
                ret
                ASSERT NEW_REFS >= #C000 && NEW_IREFS >= #C000

                ASSERT $ <= #3000
                ORG #3000
; Кэш диспетчеризации (см. DISPATCH): четыре массива по 256 байт на границах страниц H.
RC_IPH          DS 256
RC_PAGE         DS 256
RC_LO           DS 256
RC_HI           DS 256
RC2_IPH         DS 256
RC2_PAGE        DS 256
RC2_LO          DS 256
RC2_HI          DS 256
                ASSERT RC_IPH == #3000 && RC2_IPH == #3400     ; второй путь — `set 2,h`
; Данные ядер за кэшем диспетчеризации (до #3C00: ниже HELPER_TOP место стека подпрограмм). Маски перьев менеджера и
; переноса палитр (v30z80_kernels.asm), слово на запись r = группа·16 + слот, бит p — перо p.
PEN_EQ          DS 64                   ; перья, все компоненты которых равны целям типа PAL_KIND
PEN_CHG         DS 64,#FF               ; перья, плоскости которых могли разойтись с памятью палитр после переноса
; Кэш описания пачки снарядов (BulletRun, VDAC2+): BX описания и его байты X, Y, код, старший байт атрибута.
BR_DESC         DW #FFFF
BR_XY           DW 0
BR_CODE         DW 0
BR_ATTR         DB 0
; VDAC2+, ранняя сборка строк групп (vdac2p_early.asm, vdac2p_host2.asm) — общее у хоста и его второй страницы:
; предсказанные тайлы строки полос (64 байта, как TILE_TEMP хоста), группа полосы, режим StripRowRebuild (ROW_SPEC:
; бит 0 — тайлы из SP_TEMP, не 0 — каскад в той же области за ранней сборкой) и перестроек строк в кадре (SP_BUSY).
SP_TEMP         DS 64
SP_GROUP        DB 0
ROW_SPEC        DB 0
SP_BUSY         DB 0
IMG_FAILS       DB 0                    ; отказов пула картинок (ImageAlloc) по кругу 256
; VDAC2+, спрайты объектами (vdac2p_objects.asm на второй странице хоста) — общее у хоста и второй страницы: кадр вывода,
; указатель слов спрайтов кадра и состояние буфера спрайтов парами (Sprite1 сверяет через HL + 1): палитра и режим
; матрицы, область X и окно Y (SPRITE_RY: 1 — верхнее, 2 — нижнее, 4 — окно объектов выше поля, 0 — не задано);
; OBJ_VALID = 0 — пул объектов RAM_G недействителен: видеоадаптер сброшен (VideoInit) или машина перезапущена (ApiReboot
; возвращает резидент из копии — там 0); вторая страница, сбросив пул, ставит 1.
VIDEO_FRAME     DB 0
SPRITE_FILL     DW 0
SPRITE_PAL      DB 0
SPRITE_FLIP     DB 0
SPRITE_RX       DB 0
SPRITE_RY       DB 0
                ASSERT SPRITE_FLIP == SPRITE_PAL+1 && SPRITE_RY == SPRITE_RX+1
OBJ_VALID       DB 0
; Граница слов записей игрока в буфере спрайтов кадра (ProtectMark, vdac2p_sprites.asm): PROTECT_END — первое слово
; не игрока; PROTECT_OPEN = 1 — границы нет, все слова кадра — игрока.
PROTECT_END     DW 0
PROTECT_OPEN    DB 0
; Кэш столкновений (VDAC2+ 2026-09-26): цикл списка объектов IRQ0 ($0263…$0277, враги). 0 — вне его (сканы — как
; ROM, без кэша); 1 — в цикле, крайние X записей ещё не собраны; 2 — собраны (CollBuild нативной страницы). Ставят входы
; n2.N_0263 (1), n2.N_0277 и n2.N_00FE (0); меняет на 2 CollBuild.
COLL_STATE      DB 0
                ASSERT $ <= #3900                ; SCRIPT_FLAGS ниже остаётся на #3900 (ALIGN 256)
; Признаки байта скрипта движения (ядро $F9C1): 2 — бит 7; 1 — бит 2 (конец отрезка после перемещений); 0 — шаг.
; SCRIPT_DX, SCRIPT_DY — перемещение X (биты 6, 5) и Y (биты 4, 3): +1, −1 (#FF) или 0; у байтов с битом 7 — 0.
                ALIGN 256
SCRIPT_FLAGS:
script_byte = 0
                DUP 256
                DB ((script_byte >> 7) & 1) * 2 + (1 - ((script_byte >> 7) & 1)) * ((script_byte >> 2) & 1)
script_byte = script_byte + 1
                EDUP
SCRIPT_DX:
script_byte = 0
                DUP 256
                DB ((1 - ((script_byte >> 7) & 1)) * ((script_byte >> 5) & 1) * (1 - 2 * ((script_byte >> 6) & 1))) & #FF
script_byte = script_byte + 1
                EDUP
SCRIPT_DY:
script_byte = 0
                DUP 256
                DB ((1 - ((script_byte >> 7) & 1)) * ((script_byte >> 3) & 1) * (1 - 2 * ((script_byte >> 4) & 1))) & #FF
script_byte = script_byte + 1
                EDUP
                ASSERT low SCRIPT_FLAGS == 0 && SCRIPT_DX == SCRIPT_FLAGS+256 && SCRIPT_DY == SCRIPT_FLAGS+512

STACK_TOP       EQU #4000
                ASSERT V30_PAGE_BASE == #80     ; MAP_W2_LINES генератора: `set 7,a`
HELPER_TOP      EQU #3E00           ; стек подпрограмм из переведённого кода (выше — стек драйвера)
WORK_PAGE       EQU #10             ; рабочее ОЗУ V30 #40000..#43FFF
                ASSERT $ <= #3C00                   ; #3C00…#3DFF — стек подпрограмм (HELPER_TOP)
