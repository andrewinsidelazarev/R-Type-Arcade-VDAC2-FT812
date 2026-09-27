; Звуковой адаптер переведённой программы World ROM: страница SOUND_PAGE в окне W3 (#C000).
;
; Команды звукового latch машины (очередь SOUND_QUEUE шага): мелодии и их control-команды $00…$2F —
; TurboSound FM (два YM2203, порты #FFFD/#BFFD); эффекты $30…$FF — General Sound (v30z80_gs.asm,
; та же страница: PCM из раздела 3 пака грузится при старте мелодии уровня).
; Логика мелодий — rtype_port.audio.TurboSoundFm: таблица MUSIC_TABLE (rtype_sound.py) — пропуск;
; затухание владельца (MUSIC_FADE_FRAMES шагов); замена владельца потоком без повтора; мелодия — новый
; поток, владелец = команда. Шаг потока (SoundStep; SoundFrame после кадра цикла app.main делает их по числу
; кадров развёртки FT812) — как TurboSoundFm.step_frame: события кадра потока, затем счёт затухания (по концу — тишина, мелодии и
; владельца нет) либо сброс владельца, когда эмулятор эталона дошёл до конца потока без повтора. Эмулятор
; эталона в первом шаге после старта делает MUSIC_PREFILL_FRAMES = 8 шагов (заполнение буфера PCM),
; поэтому конец для владельца наступает на шаге «кадров потока − 8» — счётчик MUSIC_EMU_LEFT.
;
; Поток мелодии читается с SD из раздела 2 пака (загрузчик, LOADER_READ, по 32 сектора через буфер
; DATA_BUF_PAGE и DMA) в страницы MUSIC_PAGE0… и на время шага отображается в окно W2. Формат — как у
; TsfmMusic_Update (Source/ASM/tsfm_music.asm, проверен на железе): [пауза][число записей]
; ([чип][регистр][значение])…, $FE — продолжение с начала следующей страницы, $FF — конец. Поправка по
; эталону (TsfmEmulator.step): после последнего кадра повторяемого потока его первый кадр — в следующем
; шаге. Записи в чип — как port_writer эталона: выбор чипа перед каждой записью.
;
; Отступления на аппаратном пределе (отмечены у подпрограмм):
;   * эталон при старте потока создаёт новые чипы и сбрасывает буфер PCM; сбросить YM2203 программно
;     нельзя — MusicSilence глушит операторы (TL = 127, быстрый RR, снятие нот), ChipsReset обнуляет SSG-EG
;     и пишет инициализацию TsfmEmulator.reset; остальные регистры потоки пишут сами до нажатия ноты
;     (проверяет rtype_sound.py);
;   * затухание эталона — усиление PCM; здесь — ослабление несущих операторов (MUSIC_FADE_ATT шагов TL
;     по 0.75 дБ), значения потока в тени TL_SHADOW не меняются; бас в SSG-части (rtype_port.tsfm_bass)
;     ослабляется громкостями SSG по тем же шагам (SsgFade, тень SSG_VOL_SHADOW) — с 2026-09-17 перенос баса
;     выключен (BASS_TO_SSG = False, бас на FM, как у аркады), SSG-записей в потоках нет, SsgFade ничего не меняет;
;   * шаг потока эталона — кадр игры; здесь — кадр развёртки FT812 (59.08 Гц, стандартный VM_1024_768_59Hz:
;     мелодии, как и игра, быстрее аркады на 7.4 %, решение пользователя 2026-09-16), чтобы темп мелодии не
;     зависел от скорости игры на Z80 (SoundFrame).
;
; Петля повторяемого потока (ym2151_to_tsfm.encode_stream, rtype_music.py): маркер $FD $00 после пустого
; блока-якоря на кадре начала петли. StreamStep запоминает страницу и адрес за маркером; после $FF повтор идёт
; оттуда, без маркера — с начала потока (как у TsfmEmulator.step: frame = loop_frame).

                ORG #C000
SOUND_ENTRY_COMMANDS:                   ; #C000: команды шага из SOUND_QUEUE
                jp SoundCommands
SOUND_ENTRY_FRAME:                      ; #C003: шаг кадра цикла app.main
                jp SoundFrame
SOUND_ENTRY_RESET:                      ; #C006: сброс сессии (возврат к титулу)
                jp SoundReset
SOUND_ENTRY_PRELOAD:                    ; #C009: шаг предзагрузки звука загрузчиком SPG (вызов машины 10)
                jp SoundPreload
SOUND_ENTRY_LABEL:                      ; #C00C: надпись скорости мыши (vdac2p_label.asm; из FrameEmit хоста)
                jp MouseLabel

                INCLUDE "rtype_sound.inc"
                INCLUDE "rtype_gs.inc"
                INCLUDE "rtype_ay.inc"

TSFM_PORT_ADDR  EQU #FFFD
TSFM_SELECT0    EQU #F8                 ; 1111_1000: YM1, выход включён (как WildCommander)
TSFM_SELECT1    EQU #F9
TSFM_WRITE_DELAY EQU 12                 ; пауза после каждого OUT (≈11 мкс, минимум YM2203 ≈9.7 мкс)
REG_FRAMES      EQU #302004             ; счёт кадров развёртки FT812
MUSIC_CATCHUP   EQU 16                  ; шагов потока за вызов не больше
MUSIC_END       EQU #FF
MUSIC_PAGE_MARK EQU #FE
MUSIC_LOOP_MARK EQU #FD                 ; точка петли: повтор продолжается с блока за маркером
MUSIC_PAGE0     EQU SOUND_PAGE+1        ; буфер потока: MUSIC_TRACK_PAGES страниц подряд
MUSIC_NONE      EQU #FF                 ; нет владельца или текущей мелодии
PAGE_SECTORS    EQU 32

; --- команды -------------------------------------------------------------------------------------------
SoundCommands:  call GsDetectOnce               ; первый же звук решает: плата GS или простой AY
                ld a,(SOUND_COUNT)
                or a
                ret z
                ld b,a
                ld hl,SOUND_QUEUE
.command:       ld a,(hl)
                inc hl
                cp #30
                jr c,.music
                ; Эффекты $30…$FF — General Sound (v30z80_gs.asm). Фильтр нашего титула стоит внутри GsPlay,
                ; на ветке запуска звука: здесь он выбрасывал команду целиком, вместе с остановками. Стоп
                ; петли заряда BEAM ($33 для $32) ROM шлёт через 1…70 кадров после старта (трасса аркады
                ; 2026-09-20: 86 пар, незакрытых нет), и стоило ему попасть на кадр нашего экрана — петля
                ; оставалась звучать сиреной. Оттуда же «SFX срабатывают не каждый раз».
                ld (GS_COMMAND),a
                push bc
                push hl
                ld a,(GS_PRESENT)
                or a
                jr nz,.board
                ld a,(GS_COMMAND)               ; платы нет — эффект на простом AY (v30z80_ay.asm)
                call AyPlay
                jr .played
.board:         call GsPlay
.played:        pop hl
                pop bc
                jr .next
.music:         push bc
                push hl
                ld c,a
                ld a,(GS_PRESENT)
                or a
                jr nz,.board2
                ; Платы GS нет — значит нет и платы с YM2203: музыку не играем вовсе (решение
                ; пользователя 2026-09-21). Из команд $00…$2F слушаем только «заглушить всё».
                ld a,c
                or a
                jr nz,.doneMusic
                call AyStop
                jr .doneMusic
.board2:        ld a,c
                or a
                jr nz,.tsfm
                push af
                call GsStopAll                  ; $00 драйвера аркады глушит всё, эффекты GS тоже
                pop af
.tsfm:          call MusicCommand
.doneMusic:     pop hl
                pop bc
.next:          djnz .command
                ret

; A — команда $00…$2F (TurboSoundFm.command).
MusicCommand:   ld (MUSIC_COMMAND),a
                ld l,a
                ld h,0
                add hl,hl
                ld de,MUSIC_TABLE
                add hl,de
                ld a,(hl)                       ; вид
                inc hl
                ld c,(hl)                       ; поток | повтор
                or a
                ret z                           ; пропуск
                cp MUSIC_KIND_FADE
                jr nz,.replace
                ld a,(MUSIC_COMMAND)
                sub 2
                ld hl,MUSIC_OWNER
                cp (hl)
                ret nz                          ; затухает только мелодия команды на 2 меньше
                ld a,MUSIC_FADE_FRAMES
                ld (MUSIC_FADE),a
                ret
.replace:       cp MUSIC_KIND_REPLACE
                jr nz,.music
                ld a,(MUSIC_COMMAND)
                dec a
                ld hl,MUSIC_OWNER
                cp (hl)
                ret nz                          ; заменяется только мелодия команды на 1 меньше
                ld a,MUSIC_NONE
                jr .start
.music:         ld a,(MUSIC_COMMAND)
.start:         ld (MUSIC_OWNER),a
                ld a,(MUSIC_COMMAND)
                ld (MUSIC_CURRENT),a
                xor a
                ld (MUSIC_FADE),a
                ld a,c
                ; провал в MusicStart

; A — поток (бит 7 — повтор): тишина, чтение с SD, начало потока. Ошибка чтения — мелодии нет.
MusicStart:     push af
                call GsLoadAll                  ; эффекты General Sound грузим здесь же, «по музыке»
                pop af
                ld c,a
                and #80
                ld (MUSIC_LOOP),a
                xor a
                ld (MUSIC_ACTIVE),a
                ld (MUSIC_ATT),a
                ld a,c
                and #7F
                ld l,a
                ld h,0
                add hl,hl
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; ·6
                ld de,MUSIC_STREAMS
                add hl,de
                push hl
                call MusicSilence               ; прежняя мелодия смолкает сразу, до чтения с SD
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; первый сектор
                inc hl
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; секторов
                inc hl
                push hl
                call MusicLoad
                pop hl
                ret nz
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; кадров потока
                ld hl,-7
                add hl,de
                jr c,.left
                ld hl,0
.left:          ld (MUSIC_EMU_LEFT),hl          ; max(0, кадров − 7): после декремента шага s — кадров − 8 − s
                call ChipsReset
                call FramesRead
                dec a
                ld (FRAMES_LAST),a              ; первый шаг потока — в SoundFrame этого же кадра, как в эталоне
                xor a
                ld (MUSIC_PAGE_INDEX),a
                ld (MUSIC_WAIT),a
                ld (MUSIC_ARMED),a
                ld (MUSIC_FINISHED),a
                ld (MUSIC_LOOP_PAGE),a          ; без маркера петли повтор — с начала потока
                ld hl,#8000
                ld (MUSIC_PTR),hl
                ld (MUSIC_LOOP_PTR),hl
                inc a
                ld (MUSIC_ACTIVE),a
                ret

; DE — первый сектор файла, BC — секторов → страницы MUSIC_PAGE0…: куски по 32 сектора (страница) чтением загрузчика
; через DMA SPI→RAM прямо в страницу (VDAC2+; прежде — через буфер загрузчика и DmaCopy). Z — успех. Портит всё, окно W2.
MusicLoad:      ld a,MUSIC_PAGE0
                ld (LOAD_PAGE),a
                ld (LOAD_SECTOR),de
                ld (LOAD_LEFT),bc
.chunk:         ld hl,(LOAD_LEFT)
                ld a,h
                or l
                ret z
                ld de,PAGE_SECTORS
                sbc hl,de                       ; CF = 0 после OR
                jr nc,.take
                ld de,(LOAD_LEFT)
.take:          ld (LOAD_TAKE),de
                ld a,(LOAD_PAGE)
                cp MUSIC_PAGE0+MUSIC_TRACK_PAGES
                jr nc,.error
                ld a,LOADER_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a
                ld a,(LOADER_READY)
                or a
                jr z,.error                     ; пак не открыт
                ld a,V30_PAGE_BASE+WORK_PAGE
                ld (LOADER_HOST_W1),a
                ld a,SOUND_PAGE
                ld (LOADER_HOST_W3),a
                ld hl,(LOAD_SECTOR)
                ld bc,(LOAD_TAKE)
                ld a,(LOAD_PAGE)
                call LOADER_READ_DMA
                ld a,HOST_PAGE                  ; LD не меняет признаков
                ld (LOADER_HOST_W3),a
                ret nz
                ld hl,(LOAD_SECTOR)
                ld de,(LOAD_TAKE)
                add hl,de
                ld (LOAD_SECTOR),hl
                ld hl,(LOAD_LEFT)
                or a
                sbc hl,de
                ld (LOAD_LEFT),hl
                ld hl,LOAD_PAGE
                inc (hl)
                jr .chunk
.error:         or 1                            ; NZ
                ret

; --- шаг кадра -------------------------------------------------------------------------------------------
; Вызов после кадра цикла app.main. Темп мелодии — реальное время: шагов потока (SoundStep) столько, сколько
; кадров развёртки FT812 прошло с прошлого вызова (REG_FRAMES; 59.08 Гц — стандартный режим загрузчика, а кадр
; M72 и потоков — 55.02 Гц), но не больше MUSIC_CATCHUP. Отступление на аппаратном пределе: в эталоне шаг потока — кадр
; игры; Z80 не всегда успевает кадр игры за кадр развёртки, и мелодия замедлялась бы вместе с игрой. Успевает —
; шаг ровно один, как в эталоне.
SoundFrame:     call GsDetectOnce
                call FramesRead
                ld (FRAMES_NOW),a
                push af
                call GsPreload                  ; сэмпл звука кредита — заранее, как только открыт пак (v30z80_gs.asm)
                pop af
                push af
                call AyTick                     ; кадр эффекта на простом AY (без платы GS)
                pop af
                call GsTick                     ; голоса эффектов GS считают кадры и без мелодии
                call GsChargeWatch              ; петля заряда BEAM: глушим, когда счётчик заряда ROM обнулён
                call GsTitleSilence             ; на нашем титуле звучит только звук нажатого старта
                ld a,(MUSIC_ACTIVE)
                or a
                ret z
                ld a,(FRAMES_NOW)
                ld hl,FRAMES_LAST
                ld c,(hl)
                ld (hl),a
                sub c                           ; A = кадров развёртки с прошлого вызова (по модулю 256)
                ret z
                cp MUSIC_CATCHUP
                jr c,.steps
                ld a,MUSIC_CATCHUP              ; долгий кадр (чтение с SD): остаток отставания не догоняется
.steps:         ld b,a
.step:          push bc
                call SoundStep
                pop bc
                ld a,(MUSIC_ACTIVE)
                or a
                ret z                           ; затухание кончилось — мелодии нет
                djnz .step
                ret

; Младший байт REG_FRAMES FT812 → A. Портит F, C.
FramesRead:     ld a,FT_CS_ON
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
                ld c,a
                ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ld a,c
                ret

; Шаг потока: как TurboSoundFm.step_frame эталона.
SoundStep:      ld a,(MUSIC_FADE)
                or a
                call nz,FadeApply
                ld a,(MUSIC_FINISHED)
                or a
                call z,StreamStep
                ld hl,(MUSIC_EMU_LEFT)
                ld a,h
                or l
                jr z,.emulated
                dec hl
                ld (MUSIC_EMU_LEFT),hl
.emulated:      ld a,(MUSIC_FADE)
                or a
                jr z,.noFade
                dec a
                ld (MUSIC_FADE),a
                ret nz
                jr MusicStop                    ; затухание кончилось: мелодии и владельца нет
.noFade:        ld a,(MUSIC_LOOP)
                or a
                ret nz
                ld hl,(MUSIC_EMU_LEFT)
                ld a,h
                or l
                ret nz
                ; Поток без повтора доигран: владельца нет, но состояние мелодии — как у эталона
                ; (он держит текущую мелодию и активность до следующей команды), иначе сверка
                ; `rtype_check` расходится на кадре конца потока. Глушим только чипы: раньше здесь
                ; снимался лишь владелец, и последняя нота YM2203 оставалась без key-off — тянулась
                ; зависшим звуком (жалоба пользователя 2026-09-20).
                ld a,MUSIC_NONE
                ld (MUSIC_OWNER),a
                jp MusicSilence

; Сброс сессии (TurboSoundFm.reset) и конец затухания: мелодии и владельца нет, тишина.
SoundReset:     call AyStop
                call GsReset
MusicStop:      xor a
                ld (MUSIC_ACTIVE),a
                ld (MUSIC_FADE),a
                ld (MUSIC_ATT),a
                ld a,MUSIC_NONE
                ld (MUSIC_CURRENT),a
                ld (MUSIC_OWNER),a
                jp MusicSilence

; События одного кадра потока (как TsfmEmulator.step: кадр события — сумма пауз блоков).
StreamStep:     ld a,(MUSIC_WAIT)
                or a
                jr z,.play
                dec a
                ld (MUSIC_WAIT),a
                ret nz
.play:          call MapMusicPage
                ld hl,(MUSIC_PTR)
.block:         ld a,(MUSIC_ARMED)
                or a
                jr nz,.events                   ; пауза блока уже отсчитана
                ld a,(hl)
                cp MUSIC_END
                jr z,.end
                cp MUSIC_PAGE_MARK
                jr z,.nextPage
                cp MUSIC_LOOP_MARK
                jr z,.loopMark
                or a
                jr z,.events                    ; нулевая пауза — события этого кадра
                ld (MUSIC_WAIT),a
                ld a,1
                ld (MUSIC_ARMED),a
                jr .leave
.events:        xor a
                ld (MUSIC_ARMED),a
                inc hl                          ; байт паузы
                ld b,(hl)                       ; записей
                inc hl
                ld a,b
                or a
                jr z,.block
.write:         push bc
                ld a,(hl)                       ; чип
                inc hl
                ld e,(hl)                       ; регистр
                inc hl
                ld d,(hl)                       ; значение
                inc hl
                push hl
                call EventWrite
                pop hl
                pop bc
                djnz .write
                jr .block
.nextPage:      ld a,(MUSIC_PAGE_INDEX)
                inc a
                ld (MUSIC_PAGE_INDEX),a
                call MapMusicPage
                ld hl,#8000
                jr .block
.loopMark:      inc hl                          ; маркер петли: запомнить блок за ним
                inc hl
                ld (MUSIC_LOOP_PTR),hl
                ld a,(MUSIC_PAGE_INDEX)
                ld (MUSIC_LOOP_PAGE),a
                jr .block
.end:           ld a,(MUSIC_LOOP)
                or a
                jr z,.finish
                ld a,(MUSIC_LOOP_PAGE)          ; повтор: с точки петли, её первый кадр — в следующем шаге
                ld (MUSIC_PAGE_INDEX),a
                ld hl,(MUSIC_LOOP_PTR)
                jr .leave
.finish:        ld a,1
                ld (MUSIC_FINISHED),a
.leave:         ld (MUSIC_PTR),hl
                ld a,#FF
                ld (W2_PAGE),a                  ; окно W2 занято страницей потока
                ret

MapMusicPage:   ld a,(MUSIC_PAGE_INDEX)
                add a,MUSIC_PAGE0
                ld bc,PORT_PAGE2
                out (c),a
                ret

; Событие потока: A — чип, E — регистр, D — значение. TL (#40…#4F) и алгоритм (#B0…#B2) — в тени; при
; затухании TL несущих ослабляется. Портит всё.
EventWrite:     ld (EVENT_CHIP),a
SOUND_EVENT_HOOK:                       ; точка останова модели сверки: A — чип, E — регистр, D — значение
                call TsfmSelect
                ld a,e
                sub #08
                cp 3
                jr c,.ssgVolume                 ; громкость SSG (#08…#0A)
                ld a,e
                sub #40
                cp #10
                jr c,.tl
                sub #B0-#40
                cp 3
                jp nc,TsfmWrite
                ld c,a                          ; канал
                ld a,(EVENT_CHIP)
                ld b,a
                add a,a
                add a,b
                add a,c
                ld hl,ALG_SHADOW
                call AddHlA
                ld a,d
                and 7
                ld (hl),a
                call TsfmWrite
                ld a,(MUSIC_ATT)
                or a
                ret z
                ld a,e                          ; затухание: у операторов канала могла смениться роль
                sub #B0
                ld (FADE_SLOT),a
.channelTl:     ld a,(FADE_SLOT)
                ld c,a
                call TlOut
                ld a,(FADE_SLOT)
                add a,4
                ld (FADE_SLOT),a
                cp 16
                jr c,.channelTl
                ret
.ssgVolume:     ld c,a                          ; канал
                ld a,(EVENT_CHIP)
                ld b,a
                add a,a
                add a,b
                add a,c                         ; чип·3 + канал
                ld hl,SSG_VOL_SHADOW
                call AddHlA
                ld (hl),d
                jp SsgVolOut
.tl:            ld c,a                          ; слот·4 + канал
                and 3
                cp 3
                jp z,TsfmWrite                  ; канала 3 у YM2203 нет
                ld a,(EVENT_CHIP)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,c
                ld hl,TL_SHADOW
                call AddHlA
                ld (hl),d
                ; провал в TlOut

; TL оператора C (слот·4 + канал) чипа EVENT_CHIP из тени; у несущих при затухании — ослабление
; MUSIC_ATT (до 127). Чип выбран. Портит AF, BC, DE, HL.
TlOut:          ld a,c
                and 3
                cp 3
                ret z                           ; канала 3 у YM2203 нет
                ld a,(EVENT_CHIP)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,c
                ld hl,TL_SHADOW
                call AddHlA
                ld d,(hl)
                ld a,c
                add a,#40
                ld e,a
                ld a,(MUSIC_ATT)
                or a
                jp z,TsfmWrite
                ld a,c
                call CarrierTest
                jp z,TsfmWrite
                ld a,d
                and #7F
                ld hl,MUSIC_ATT
                add a,(hl)
                cp 128
                jr c,.value
                ld a,127
.value:         ld d,a
                jp TsfmWrite

; Громкость SSG регистра E (#08…#0A) чипа EVENT_CHIP из тени SSG_VOL_SHADOW; дальше — как SsgVolOut.
; Чип выбран. Портит AF, BC, D, HL.
SsgShadowOut:   ld a,(EVENT_CHIP)
                ld b,a
                add a,a
                add a,b
                add a,e
                sub #08                         ; чип·3 + канал
                ld hl,SSG_VOL_SHADOW
                call AddHlA
                ld d,(hl)
                ; провал в SsgVolOut

; Запись громкости SSG: E — регистр #08…#0A, D — значение потока; при затухании — ослабленное (SsgFade).
; Чип выбран. Портит AF, BC, D, HL.
SsgVolOut:      ld a,(MUSIC_ATT)
                or a
                call nz,SsgFade
                jp TsfmWrite

; Отступление на аппаратном пределе: у эталона затухание — усиление PCM всего TSFM, у SSG YM2203 есть только
; 4-битная громкость (ступени ≈ 2.5…4 дБ), а у голоса с огибающей (бит 4) громкости нет вовсе. Поэтому:
;   * громкость v заменяется ближайшей по уровню громкостью, тише на MUSIC_ATT шагов TL: T = SSG_VOL_ATT[v] +
;     MUSIC_ATT, спуск v → v − 1, пока T > SSG_VOL_MID[v] (у v = 1 порог — уход в тишину);
;   * голос с огибающей звучит как есть до ослабления SSG_ENV_KEEP (6 дБ: нужная амплитуда ещё не меньше
;     половины), дальше молчит. Постоянной громкостью огибающую не заменить: в рецепте баса она даёт основную
;     частоту, а тон её только модулирует.
; Ступени ЦАП посчитаны по модели платы (rtype_port.tsfm_bass.ssg_fade_tables).
; Вход: D — значение потока, E — регистр, MUSIC_ATT ≠ 0. Выход: D. Портит AF, BC, HL.
SsgFade:        ld a,d
                and #1F
                ret z                           ; тишина остаётся тишиной
                bit 4,a
                jr z,.fixed
                ld a,(MUSIC_ATT)
                cp SSG_ENV_KEEP+1
                ret c                           ; ослабление ≤ 6 дБ — огибающая звучит
                ld d,0                          ; дальше голос молчит
                ret
.fixed:         and #0F
                ld b,a                          ; B — громкость потока
                ld hl,SSG_VOL_ATT
                call AddHlA
                ld a,(MUSIC_ATT)
                add a,(hl)
                ld c,a                          ; C — T
.down:          ld a,b
                or a
                jr z,.done                      ; дошли до тишины
                ld hl,SSG_VOL_MID
                call AddHlA
                ld a,(hl)
                cp c
                jr nc,.done                     ; порог ≥ T — громкость B
                dec b
                jr .down
.done:          ld d,b
                ret

; A — слот·4 + канал (канал 0…2), чип EVENT_CHIP: NZ — оператор несущий в алгоритме канала. Портит AF,
; BC, HL.
CarrierTest:    ld c,a
                and 3
                ld b,a
                ld a,(EVENT_CHIP)
                ld h,a
                add a,a
                add a,h
                add a,b                         ; чип·3 + канал
                ld hl,ALG_SHADOW
                call AddHlA
                ld a,(hl)
                ld hl,CARRIER_MASK
                call AddHlA
                ld b,(hl)                       ; маска несущих слотов
                ld a,c
                rrca
                rrca
                and 3
                inc a                           ; слот + 1
.shift:         rrc b                           ; CF — очередной бит маски
                dec a                           ; DEC не меняет CF
                jr nz,.shift
                sbc a,a                         ; A = 0: CF → #FF
                and 1
                ret

; Несущие операторы YM2203 по алгоритму: бит слота регистра (#40 — оператор 1, #44 — 3, #48 — 2, #4C — 4).
CARRIER_MASK:   DB #08, #08, #08, #08, #0C, #0E, #0E, #0F

; HL += A. Портит AF.
AddHlA:         add a,l
                ld l,a
                adc a,h
                sub l
                ld h,a
                ret

; A — оставшиеся кадры затухания: ослабление MUSIC_FADE_ATT[A]; при изменении — TL всех операторов заново.
FadeApply:      ld e,a
                ld d,0
                ld hl,MUSIC_FADE_ATT
                add hl,de
                ld a,(hl)
                ld hl,MUSIC_ATT
                cp (hl)
                ret z
                ld (hl),a
                xor a
                ld (EVENT_CHIP),a
.chip:          ld a,(EVENT_CHIP)
                call TsfmSelect
                xor a
                ld (FADE_SLOT),a
.slot:          ld a,(FADE_SLOT)
                ld c,a
                call TlOut
                ld hl,FADE_SLOT
                inc (hl)
                ld a,(hl)
                cp 16
                jr c,.slot
                ld e,#08                        ; громкости SSG (бас) — по тем же шагам
.ssg:           call SsgShadowOut
                inc e
                ld a,e
                cp #0B
                jr c,.ssg
                ld hl,EVENT_CHIP
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.chip
                ret

; Отступление на аппаратном пределе: вместо новых чипов эталона — MusicSilence, SSG-EG всех операторов = 0
; и инициализация TsfmEmulator.reset (#2D, #27 = 0, снятие нот каналов 0…2). Тени: TL = 127 (как в
; чипе после MusicSilence), алгоритмы — 0.
ChipsReset:     call MusicSilence
                ld hl,TL_SHADOW
                ld de,TL_SHADOW+1
                ld bc,31
                ld (hl),127
                ldir
                ld hl,ALG_SHADOW
                ld de,ALG_SHADOW+1
                ld bc,5
                ld (hl),0
                ldir
                xor a
                ld (EVENT_CHIP),a
.chip:          ld a,(EVENT_CHIP)
                call TsfmSelect
                ld e,#90
                ld d,0
.ssgEg:         call TsfmWrite
                inc e
                ld a,e
                cp #A0
                jr c,.ssgEg
                ld e,#2D                        ; прескалер 1/6: 3.5 МГц платы / 6 → 48 611 Гц синтеза
                call TsfmWrite
                ld e,#27
                call TsfmWrite
                ld e,#28
.keyOff:        call TsfmWrite
                inc d
                ld a,d
                cp 3
                jr c,.keyOff
                ld hl,EVENT_CHIP
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.chip
                ret

; Отступление на аппаратном пределе: вместо сброса буфера PCM эталона — TL = 127 всех операторов (звук
; пропадает сразу), SL/RR = #0F (огибающие быстро уходят в тишину) и снятие нот каналов 0…2 обоих чипов.
MusicSilence:   ld hl,SSG_VOL_SHADOW
                ld b,6
.shadow:        ld (hl),0                       ; тень громкостей SSG — как в чипе после записи нулей ниже
                inc hl
                djnz .shadow
                xor a
                ld (EVENT_CHIP),a
.chip:          ld a,(EVENT_CHIP)
                call TsfmSelect
                ld e,#40
                ld d,127
.tl:            call TsfmWrite
                inc e
                ld a,e
                cp #50
                jr c,.tl
                ld e,#80
                ld d,#0F
.rr:            call TsfmWrite
                inc e
                ld a,e
                cp #90
                jr c,.rr
                ld e,#28
                ld d,0
.keyOff:        call TsfmWrite
                inc d
                ld a,d
                cp 3
                jr c,.keyOff
                ld e,#08                        ; SSG: громкости A, B, C в ноль — там бас (rtype_port.tsfm_bass)
                ld d,0
.ssg:           call TsfmWrite
                inc e
                ld a,e
                cp #0B
                jr c,.ssg
                ld hl,EVENT_CHIP
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.chip
                ret

; A — чип 0/1. Портит AF, BC.
TsfmSelect:     ld bc,TSFM_PORT_ADDR
                or a
                ld a,TSFM_SELECT0
                jr z,.out
                ld a,TSFM_SELECT1
.out:           out (c),a
                ld b,TSFM_WRITE_DELAY
.wait:          djnz .wait
                ret

; E — регистр, D — значение. Портит AF, BC.
TsfmWrite:      ld bc,TSFM_PORT_ADDR            ; B = #FF, C = #FD
                out (c),e
                ld b,TSFM_WRITE_DELAY
.wa:            djnz .wa
                ld b,#BF                        ; #BFFD
                out (c),d
                ld b,TSFM_WRITE_DELAY
.wd:            djnz .wd
                ret

; --- состояние ------------------------------------------------------------------------------------------
MUSIC_ACTIVE    DB 0                    ; поток есть (эталон: emulator не None)
MUSIC_CURRENT   DB MUSIC_NONE
MUSIC_OWNER     DB MUSIC_NONE
MUSIC_FADE      DB 0                    ; оставшиеся кадры затухания
MUSIC_COMMAND   DB 0
MUSIC_LOOP      DB 0
MUSIC_FINISHED  DB 0                    ; поток без повтора дошёл до конца (записей больше нет)
MUSIC_EMU_LEFT  DW 0                    ; шагов до конца эмулятора эталона
MUSIC_ATT       DB 0                    ; текущее ослабление несущих (шагов TL)
MUSIC_PTR       DW #8000
MUSIC_PAGE_INDEX DB 0
MUSIC_LOOP_PTR  DW #8000                ; точка петли: адрес блока за маркером $FD
MUSIC_LOOP_PAGE DB 0                    ; и номер страницы потока
MUSIC_WAIT      DB 0
MUSIC_ARMED     DB 0
FRAMES_LAST     DB 0                    ; младший байт REG_FRAMES прошлого вызова SoundFrame
FRAMES_NOW      DB 0                    ; младший байт REG_FRAMES этого вызова
EVENT_CHIP      DB 0
FADE_SLOT       DB 0
LOAD_PAGE       DB 0
LOAD_SECTOR     DW 0
LOAD_LEFT       DW 0
LOAD_TAKE       DW 0
TL_SHADOW       DS 32, 127              ; чип·16 + слот·4 + канал
ALG_SHADOW      DS 6                    ; чип·3 + канал
SSG_VOL_SHADOW  DS 6                    ; громкости SSG из потока (#08…#0A): чип·3 + канал
                INCLUDE "v30z80_gs.asm"
                INCLUDE "v30z80_ay.asm"
                INCLUDE "vdac2p_label.asm"

SOUND_END:
                ASSERT SOUND_END <= #10000
