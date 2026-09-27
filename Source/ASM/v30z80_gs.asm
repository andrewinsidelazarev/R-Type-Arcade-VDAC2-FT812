; Эффекты General Sound / MultiSound (команды звукового latch $30…$7F) для переведённой программы.
; Часть звуковой страницы SOUND_PAGE: таблицы — rtype_gs.inc (генератор Source/Tools/rtype_gs.py),
; PCM эффектов — раздел 3 пака RTYPELVL.PAC, читается тем же загрузчиком, что и мелодии.
;
; Протокол платы взят из проверенного на железе general_sound.asm (путь Zuma): перед КАЖДОЙ записью
; данных в #B3 ждём в статусе #BB бит 7 = 0 (есть место в FIFO), команда в #BB считается выполненной по
; биту 0 = 0. У ожиданий есть таймаут: без платы кадр не должен вставать. Остановка — команда GS #3A
; (заглушить каналы по маске из данных). Петли сэмплов плате не задаются вовсе: длящийся звук (накопление
; BEAM) набирается повтором круга, см. GsChargeWatch.
;
; Когда грузим: одним проходом, как только открыт пак (GsPreload из SoundFrame) — сначала сэмпл звука
; кредита GS_START_COMMAND ($63, ROM $05DC — «монета»), затем сразу остальные (GsLoadAll). Раньше всё,
; кроме кредита, грузилось только при старте мелодии уровня, и демо аттракта оставалось немым: мелодию
; в аттракте ROM шлёт лишь на одном проходе цикла (`$0862: cmp word ptr [0x308c], 2`), а эффекты шлёт
; всегда (замер 2026-09-20: кадр 654 — команда $30, кадр 661 — $32 заряда). У аркады сэмплы лежат в ПЗУ
; звуковой платы и доступны с включения. Звук кредита ROM шлёт в кадре, когда игрок нажал FIRE на титуле
; (порт подаёт машине импульс монеты — p2c_entry_runtime.advance_start), поэтому он и грузится первым.
; MusicStart по-прежнему зовёт GsLoadAll: уже загруженные сэмплы проход пропускает, а если плата не
; проснулась к титулу, попытка повторяется. Загруженные эффекты играют и во время загрузки остальных.
; С 2026-09-27 (релизная загрузка) всё это делает загрузчик SPG под шкалой экрана загрузки — вызовом машины 10
; (SoundPreload: сэмпл за вызов, те же GsPreloadCredit и GsLoadOne); игре остаётся готовое состояние, и GsPreload
; с GsLoadAll в игре ничего не грузят. Сборки без загрузчика SPG (модели сверки) грузят, как прежде, в игре.
;
; Голоса. У драйвера аркады эффекты делят восемь каналов YM2151 с музыкой и вытесняют друг друга по
; приоритету; у нас эффекты на отдельном устройстве (решение пользователя 2026-09-16: не вытеснять), а
; каналов у GS четыре. Правило (модель на трассе всей игры: важные эффекты доигрывают на 96 %, взрывы на
; 90 %, пропусков нет):
;   * та же команда уже звучит — перезапуск на её голосе (как у драйвера аркады);
;   * иначе — свободный голос, стороны по очереди (каналы GS 0–1 слева, 2–3 справа);
;   * все заняты — голос, которому до конца осталось меньше всего кадров (GS_COMMAND_FRAMES).
; Остановки — как у драйвера аркады: команда с заголовком типа $10 глушит голос своей команды ($33 — заряд
; $32, $5B — звук $5A), $00 — все голоса (GsStopAll из SoundCommands), сброс сессии — тоже все.
;
; Отступления на аппаратном пределе (эталон rtype_port.audio.GeneralSound играет PCM микшером ПК):
;   * сэмплы 8-битные 11025 или 22050 Гц, громкость голоса восстанавливает относительные уровни аркады;
;   * эффект звучит на одном канале GS — слева или справа, у аркады моно.

GS_PORT_DATA    EQU #00B3
GS_PORT_CMD     EQU #00BB
GS_TIMEOUT      EQU #0800               ; попыток ожидания статуса (нет платы → выходим сразу)
GS_PROBE_LIMIT  EQU 60                  ; кадров опроса платы, прежде чем уйти на простой AY
GS_CMD_RESET    EQU #F3
GS_CMD_RAM      EQU #23
GS_CMD_FX_VOL   EQU #2B
GS_CMD_LOAD_FX  EQU #38
GS_CMD_STOP     EQU #3A
GS_CMD_SELECT   EQU #2E
GS_CMD_NOTE     EQU #40
GS_CMD_VOLUME   EQU #41
GS_CMD_PRIORITY EQU #45
GS_CMD_SEEK_A   EQU #46
GS_CMD_SEEK_B   EQU #47
GS_CMD_OPEN     EQU #D1
GS_CMD_CLOSE    EQU #D2
GS_START_COMMAND EQU #63                ; звук кредита аркады (ROM $05DC): его ROM шлёт на импульс монеты при старте
GS_CMD_PLAY     EQU #98
GS_FX_VOLUME    EQU #40                 ; общая громкость FX-тракта GS
GS_PRIORITY     EQU #C0
GS_CHANNELS     EQU 4                   ; каналы FX у GS
GS_CHUNK        EQU 32                  ; секторов пака за одно чтение (16 КиБ — страница буфера)
GS_NONE         EQU #FF

GS_STATE_NEW    EQU 0                   ; плата ещё не инициализирована
GS_STATE_LOAD   EQU 1                   ; идёт загрузка сэмплов
GS_STATE_READY  EQU 2                   ; все сэмплы в памяти GS
GS_STATE_ABSENT EQU #FF                 ; платы нет или протокол не отвечает

; ---------------------------------------------------------------------------------------------
; Команда $30…$FF (из SOUND_QUEUE): эффект или остановка. Портит всё.
; ---------------------------------------------------------------------------------------------
GsPlay:         ld a,(GS_STATE)
                cp GS_STATE_READY
                jr z,.loaded
                cp GS_STATE_LOAD
                ret nz                          ; платы нет или она не ответила
                                                ; идёт загрузка: играют сэмплы с готовым handle (предзагрузка)
.loaded:        ld a,(GS_COMMAND)
                cp GS_LAST_COMMAND+1
                ret nc                          ; $80…$FF ROM не шлёт
                sub #30
                ld (GS_SLOT),a
                ld hl,GS_COMMAND_STOP
                call GsSlotByte
                cp GS_NONE
                jr z,.effect
                call GsFindCommand              ; остановка: голос, где звучит команда A
                ret c
                ld a,c
                jp GsStopVoice
                ; Новый звук. На нашем титуле его не начинаем: машина за экраном продолжает крутить демо
                ; аттракта и шлёт её эффекты, а показываем мы свой экран (решение пользователя 2026-09-20:
                ; «на нашем экране без мелодии — только SFX в демах и SFX нажатого старта»). Признак —
                ; снятый бит 7 API_SHOW (именно он, а не API_FLAGS: там бит снимает и пропуск вывода при
                ; отставании от развёртки, и по нему выбрасывались эффекты обычных кадров игры).
                ; Остановки сюда не попадают — они выше по ветке и проходят всегда.
.effect:        ld a,(API_SHOW)
                rlca
                jr c,.sound                     ; кадр машины — демо или игра, звук как в оригинале
                ld a,(GS_COMMAND)
                cp GS_START_COMMAND
                ret nz                          ; чужой эффект демо — на нашем экране не звучит
.sound:         ld hl,GS_COMMAND_SAMPLE
                call GsSlotByte
                cp GS_NONE
                ret z                           ; у команды нет звука
                ld (GS_SAMPLE),a
                ld hl,GS_HANDLES
                call AddHlA
                ld a,(hl)
                cp GS_NONE
                ret z                           ; сэмпл не загрузился
                ld (GS_HANDLE),a
                ld a,(GS_COMMAND)
                cp #32
                jr nz,.pick
                ld a,(GS_CHARGE_VOICE)          ; круг накопления держим на одном канале: голос мог успеть
                cp GS_NONE                      ; освободиться, и очередной круг ушёл бы на другую сторону
                jr z,.pick
                ld c,a
                jr .voice
.pick:          ld a,(GS_COMMAND)
                call GsFindCommand              ; та же команда звучит — перезапуск на её голосе
                jr nc,.voice
                call GsFindFree
                jr nc,.voice
                call GsFindShortest             ; все заняты — голос, которому меньше всего осталось
.voice:         ld a,c
                ld (GS_VOICE),a
                ; данные: handle, команда #98+канал, затем нота и громкость
                ld a,(GS_HANDLE)
                call GsData
                ret nc
                ld a,(GS_VOICE)
                add a,GS_CMD_PLAY
                call GsCommand
                ret nc
                ld a,(GS_SAMPLE)
                ld hl,GS_SAMPLE_NOTE
                call AddHlA
                ld a,(hl)
                call GsData
                ret nc
                ld hl,GS_COMMAND_VOLUME
                call GsSlotByte
                call GsData
                ret nc
                ld a,(GS_VOICE)                 ; голос занят командой на её длительность
                ld (GS_LAST_VOICE),a
                ld hl,GS_VOICE_CMD
                call AddHlA
                ld a,(GS_COMMAND)
                ld (hl),a
                ld hl,GS_COMMAND_FRAMES
                call GsSlotByte
                ld c,a
                ld a,(GS_VOICE)
                ld hl,GS_VOICE_LEFT
                call AddHlA
                ld (hl),c
                ld a,(GS_COMMAND)
                cp #32
                ret nz
                ld a,1
                ld (GS_CHARGE_HOLD),a           ; накопление BEAM: круг продлевает GsChargeWatch
                ld a,(GS_VOICE)
                ld (GS_CHARGE_VOICE),a
                ret

; HL — таблица команд: A = байт команды GS_SLOT. Портит F, HL.
GsSlotByte:     ld a,(GS_SLOT)
                call AddHlA
                ld a,(hl)
                ret

; A — команда: C — голос, где она звучит, CF = 0; CF = 1 — нигде. Портит F, B, HL.
GsFindCommand:  ld hl,GS_VOICE_CMD
                ld c,0
                ld b,GS_CHANNELS
.scan:          cp (hl)
                ret z                           ; равенство: CF = 0
                inc hl
                inc c
                djnz .scan
                scf
                ret

; Свободный голос: C, CF = 0; после левого канала сначала правые и наоборот. CF = 1 — свободных нет.
; Портит AF, B, DE, HL.
GsFindFree:     ld a,(GS_LAST_VOICE)
                and 2
                ld de,GS_ORDER_RIGHT            ; последний был слева — сначала правые
                jr z,.order
                ld de,GS_ORDER_LEFT
.order:         ld b,GS_CHANNELS
.try:           ld a,(de)
                ld c,a
                ld hl,GS_VOICE_CMD
                call AddHlA
                ld a,(hl)
                cp GS_NONE
                ret z                           ; свободен: CF = 0
                inc de
                djnz .try
                scf
                ret

GS_ORDER_RIGHT: DB 2, 3, 0, 1
GS_ORDER_LEFT:  DB 0, 1, 2, 3

; Голос с наименьшим остатком кадров → C. Портит AF, B, E, HL.
; Звук накопления BEAM — единственный длящийся: в аркаде он тянется, пока ROM его не остановит. Раньше
; мы отдавали плате петлю (#48/#49) и длительность «до остановки», и любой потерянный `$33` оставлял
; сирену навсегда — прочим эффектам это не грозило, они конечны (жалобы 2026-09-20: «зависает только эта
; сирена», «и на реале зависает в игре»). Теперь сэмпл — один устойчивый круг (`Source/Tools/rtype_gs.py`),
; а держит звук сторож: пока ROM подтверждает накопление, круг запускается заново, как только доигран.
; Условия ROM: игрок в полёте (обработчик записи игрока `$40020` = `$2027`; по трассе MAME `$22CD` —
; смерть, `$1FC0` — ожидание возрождения) и счётчик заряда `DS:$003D` не ноль — ROM обнуляет его и при
; выстреле, и при смерти (PC `$022CC`, трасса `Build/Stages/beam_death`). Вечного звука взяться неоткуда:
; пропади хоть сама команда остановки — круг доиграет и не повторится.
; Окно W1 — рабочее ОЗУ V30. Портит всё. Вызов — из SoundFrame после GsTick.
; Тишина на нашем титуле: пока кадр идёт без вывода (бит 7 API_FLAGS снят — машину крутит титул
; оболочки), звучать может только звук нажатого старта GS_START_COMMAND. Отсекать одни лишь новые
; команды мало: голос, начатый в демо, доигрывал уже на нашем экране. Решение пользователя 2026-09-20:
; «на нашем экране без мелодии — только SFX в демах и SFX нажатого старта». Портит всё.
GsTitleSilence: ld a,(API_SHOW)
                rlca
                ret c                           ; кадр машины — демо или игра, звук как в оригинале
                ld hl,GS_VOICE_CMD
                ld b,GS_CHANNELS
                ld c,0
.voice:         ld a,(hl)
                cp GS_NONE
                jr z,.next
                cp GS_START_COMMAND
                jr z,.next                      ; звук старта оставляем
                push bc
                push hl
                ld a,c
                call GsStopVoice
                pop hl
                pop bc
.next:          inc hl
                inc c
                djnz .voice
                ret

GsChargeWatch:  ld a,(GS_CHARGE_HOLD)
                or a
                ret z                           ; ROM накопление не начинал — звучать нечему. Запуск всегда
                                                ; за ROM: счётчик заряда растёт и при обычном выстреле, и по
                                                ; нему звук пускать нельзя (жалоба 2026-09-20).
                ld a,V30_PAGE_BASE+WORK_PAGE
                ld bc,PORT_PAGE1
                out (c),a                       ; рабочее ОЗУ V30 — в окно W1: звуковой кадр зовут со
                                                ; стороны оболочки, и там в W1 лежит её страница (так же
                                                ; перед чтением делает ApiWord).
                ld hl,(#4000+#0020)             ; обработчик записи игрока
                ld de,#2027
                or a
                sbc hl,de
                jr nz,.silence                  ; игрок не в полёте — заряду звучать нечем
                ld a,(#4000+#003D)
                or a
                jr z,.silence                   ; счётчик заряда обнулён — накопления нет
                ld a,#32                        ; накопление идёт: круг должен звучать
                call GsFindCommand
                jr c,.again                     ; не звучит вовсе — начать круг
                ld a,c                          ; звучит: продлеваем, не дожидаясь тишины, иначе слышны
                ld hl,GS_VOICE_LEFT             ; разрыв и перескок звука на другой канал
                call AddHlA
                ld a,(hl)
                cp 3
                ret nc                          ; круг ещё звучит
.again:         ld a,#32
                ld (GS_COMMAND),a
                jp GsPlay                       ; фильтр нашего экрана — внутри GsPlay
.silence:       xor a
                ld (GS_CHARGE_HOLD),a           ; условия ROM сняты — накопление кончилось
                ld a,GS_NONE
                ld (GS_CHARGE_VOICE),a
                ld a,#32
                call GsFindCommand
                ret c                           ; заряд не звучит
                ld a,c
                jp GsStopVoice

GsFindShortest: ld hl,GS_VOICE_LEFT
                ld c,0
                ld e,(hl)
                ld b,1
.next:          inc hl
                ld a,(hl)
                cp e
                jr nc,.skip
                ld e,a
                ld c,b
.skip:          inc b
                ld a,b
                cp GS_CHANNELS
                jr c,.next
                ret

; A — голос: остановить канал GS (#3A, маска в данных) и освободить. Портит всё.
GsStopVoice:    ld (GS_VOICE),a
                ld hl,GS_MASKS
                call AddHlA
                ld a,(hl)
                call GsData
                ret nc
                ld a,GS_CMD_STOP
                call GsCommand
                ret nc                          ; плата остановку не приняла (таймаут FIFO): голос оставляем
                                                ; занятым, следующий кадр повторит — иначе таблица считала бы
                                                ; его свободным, а звук продолжался.
                ld a,(GS_VOICE)
                ld hl,GS_VOICE_CMD
                call AddHlA
                ld a,(hl)
                ld (hl),GS_NONE
                cp #32
                jr nz,.left
                xor a
                ld (GS_CHARGE_HOLD),a           ; остановлен круг накопления — продлевать больше нечего
                ld a,GS_NONE
                ld (GS_CHARGE_VOICE),a
.left:
                ld a,(GS_VOICE)
                ld hl,GS_VOICE_LEFT
                call AddHlA
                ld (hl),0
                ret

GS_MASKS:       DB 1, 2, 4, 8
GS_FAILS        DW 0                    ; неудачных обменов с платой (диагностика потерянных эффектов)

; Команда $00 драйвера аркады и сброс сессии: заглушить все каналы эффектов. Портит всё.
GsStopAll:      ld a,(GS_STATE)
                cp GS_STATE_READY
                jr z,.board
                cp GS_STATE_LOAD
                ret nz                          ; платы нет; при загрузке остановка нужна: предзагруженный звучит
.board:
                ld a,#0F
                call GsData
                ret nc
                ld a,GS_CMD_STOP
                call GsCommand
                ; провал в GsClearVoices

; Все голоса свободны. Портит F, B, HL.
GsClearVoices:  xor a
                ld (GS_CHARGE_HOLD),a           ; зовут после остановки всех каналов платы или её сброса
                ld a,GS_NONE
                ld (GS_CHARGE_VOICE),a
                ld hl,GS_VOICE_CMD
                ld b,GS_CHANNELS
.cmd:           ld (hl),GS_NONE
                inc hl
                djnz .cmd
                ld b,GS_CHANNELS                ; GS_VOICE_LEFT лежит сразу за GS_VOICE_CMD
.left:          ld (hl),0
                inc hl
                djnz .left
                ret

; A — младший байт REG_FRAMES (из SoundFrame): остатки кадров голосов уменьшаются на прошедшие кадры,
; доигравший голос свободен. Портит AF, BC, DE, HL.
GsTick:         ld hl,GS_FRAMES_LAST
                ld c,(hl)
                ld (hl),a
                sub c
                ret z
                ld c,a                          ; C — кадров с прошлого вызова
                ld hl,GS_VOICE_LEFT
                ld b,GS_CHANNELS
.voice:         ld a,(hl)
                or a
                jr z,.next                      ; свободен
                sub c
                jr z,.free
                jr nc,.store
.free:          xor a
                ld (hl),a
                push hl
                ld de,GS_CHANNELS
                or a
                sbc hl,de                       ; GS_VOICE_CMD того же голоса
                ld (hl),GS_NONE
                pop hl
                jr .next
.store:         ld (hl),a
.next:          inc hl
                djnz .voice
                ret

; ---------------------------------------------------------------------------------------------
; Предзагрузка сэмпла звука кредита (GS_START_COMMAND) — вызов каждый кадр из SoundFrame, работа только пока
; состояние NEW и открыт пак: инициализация платы и один сэмпл (25 секторов, ≈0.9 млн тактов в этом кадре
; титула). Остальные грузит GsLoadAll при старте мелодии, этот пропуская. Платы нет — состояние ABSENT, больше
; не пробуем. Портит всё.
; ---------------------------------------------------------------------------------------------
; Есть ли плата General Sound. Метод Zuma Deluxe (GS_Detect в ts-dos.asm): шлём команду сброса #F3 —
; плата снимает бит 0 статуса, на шине без платы он не снимается никогда и срабатывает таймаут
; GsCommand. Ответ запоминаем один раз: без платы эффекты идут на простой AY (v30z80_ay.asm), а
; мелодии не играются вовсе (решение пользователя 2026-09-21).
GsDetectOnce:   ld a,(GS_DETECTED)
                or a
                ret nz                          ; решение уже принято
                ld a,#F3
                call GsCommand
                jr nc,.silent
                ld a,1                          ; плата ответила
                ld (GS_PRESENT),a
                ld (GS_DETECTED),a
                ret
                ; Плата могла не проснуться к первому кадру, поэтому не решаем сразу: опрос
                ; повторяется каждый кадр звука, и только после GS_PROBE_LIMIT попыток порт
                ; окончательно уходит на простой AY.
.silent:        ld hl,GS_PROBES
                inc (hl)
                ld a,(hl)
                cp GS_PROBE_LIMIT
                ret c
                ld a,1
                ld (GS_DETECTED),a
                ret

GsPreload:      ld a,(GS_DETECTED)
                or a
                ret z                           ; про плату ещё не решили — ничего не грузим
                ld a,(GS_PRESENT)
                or a
                jp z,AyPreload                  ; платы нет: вместо сэмплов читаем строки AY
                call GsPreloadCredit
                ret nc                          ; попытка уже была, пак ещё не открыт или не вышло
                ; Остальные сэмплы тоже грузим здесь, а не только при старте мелодии уровня: в аттракте
                ; мелодии нет (ROM шлёт её лишь на одном проходе цикла — `$0862: cmp word [0x308c], 2`),
                ; поэтому демо оставалось немым, хотя ROM шлёт ему эффекты (замер 2026-09-20: кадр 654 —
                ; команда $30, кадр 661 — $32). У аркады сэмплы в ПЗУ звуковой платы и доступны всегда.
                jp GsLoadAll

; Первая часть предзагрузки (плата есть): инициализация платы и сэмпл звука кредита. CF = 1 — загружен, дальше
; остальные; CF = 0 — попытка уже была, пак ещё не открыт или не вышло (тогда состояние как до попытки). Портит всё.
GsPreloadCredit:
                ld a,(GS_PRELOAD)
                or a
                ret nz                          ; попытка уже была (CF = 0 после OR)
                ld a,LOADER_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a
                ld a,(LOADER_READY)
                or a
                ret z                           ; пак ещё не открыт — в следующем кадре
                ld a,1
                ld (GS_PRELOAD),a
                call GsInit
                ld a,(GS_STATE)
                cp GS_STATE_LOAD
                jr nz,.back
                ld a,GS_START_COMMAND-#30
                ld (GS_SLOT),a
                ld hl,GS_COMMAND_SAMPLE
                call GsSlotByte
                cp GS_NONE
                jr z,.back                      ; у команды нет сэмпла
                ld (GS_INDEX),a
                call GsSampleStart
.chunk:         ld a,(GS_STATE)
                cp GS_STATE_LOAD
                jr nz,.back                     ; ошибка протокола или чтения
                ld a,(GS_OPEN)
                or a
                jr z,.done
                call GsChunk
                jr .chunk
.done:          xor a
                ld (GS_INDEX),a                 ; полный проход — снова с нуля, загруженный сэмпл пропустится
                scf
                ret
.back:          ld a,GS_STATE_NEW               ; не вышло — состояние как до попытки: плату с нуля пробует GsLoadAll,
                ld (GS_STATE),a                 ; то есть поведение прежних сборок (плата могла не проснуться к титулу)
                xor a                           ; CF = 0
                ld (GS_INDEX),a
                ld (GS_OPEN),a
                ret

; ---------------------------------------------------------------------------------------------
; Шаг предзагрузки звука загрузчиком SPG (rtype_boot.asm, вызов машины 10; с 2026-09-27): загрузка — под шкалой
; экрана загрузки, а не чёрной паузой в начале игры. Плата есть — сэмпл за шаг (первым — звук кредита, как у
; GsPreload), чтобы шкала двигалась; платы нет — блок эффектов AY одним шагом. Решение о плате и открытый пак
; уровней — от загрузчика (GS_DETECTED, GS_PRESENT; вызов 5). DE — секторов пака, прочитанных шагом (доля шкалы);
; 0 — грузить больше нечего: всё в памяти или не вышло (тогда, как раньше, игра пробует сама — GsLoadAll при старте
; мелодии). Портит всё.
; ---------------------------------------------------------------------------------------------
SoundPreload:   ld hl,0
                ld (GS_LOADED),hl
                ld a,(GS_DETECTED)
                or a
                jr z,.none                      ; про плату не решено — не грузим
                ld a,(GS_PRESENT)
                or a
                jr nz,.gs
                ld a,(AY_LOADED)
                or a
                jr nz,.none                     ; блок эффектов AY уже в памяти
                call AyPreload
                ld a,(AY_LOADED)
                or a
                jr z,.none                      ; не прочитан
                ld de,AY_DATA_SECTORS
                ret
.gs:            ld a,(GS_PRELOAD)
                or a
                jr nz,.next
                call GsPreloadCredit            ; первый шаг: плата и звук кредита
                jr nc,.none
                jr .loaded
.next:          call GsLoadOne
                jr nc,.none
.loaded:        ld de,(GS_LOADED)
                ld a,d
                or e
                ret nz
                inc e                           ; сэмпл без секторов — шаг всё равно не последний
                ret
.none:          ld de,0
                ret

; ---------------------------------------------------------------------------------------------
; Загрузка всех сэмплов в память GS одним проходом (вызов из MusicStart и GsPreload). Портит всё.
; ---------------------------------------------------------------------------------------------
GsLoadAll:      ld a,(GS_STATE)
                cp GS_STATE_NEW
                call z,GsInit
.sample:        call GsLoadOne                  ; готово, платы нет или инициализация не удалась — CF = 0
                jr c,.sample
                ret

; Очередной сэмпл GsLoadAll (и шаг SoundPreload): CF = 1 — сэмпл загружен, могут быть ещё; CF = 0 — грузить нечего
; (все в памяти — READY, платы нет или ошибка). Портит всё.
GsLoadOne:      ld a,(GS_STATE)
                cp GS_STATE_LOAD
                jr nz,.none
                call GsSampleStart              ; кончились сэмплы — состояние станет READY
.chunk:         ld a,(GS_STATE)
                cp GS_STATE_LOAD
                jr nz,.none                     ; все в памяти или ошибка
                ld a,(GS_OPEN)
                or a
                scf
                ret z                           ; сэмпл дописан (CF = 1)
                call GsChunk
                jr .chunk
.none:          or a                            ; CF = 0
                ret

; Сброс платы, число страниц ОЗУ и общая громкость FX. Ошибка — GS_STATE_ABSENT.
GsInit:         ld a,GS_STATE_ABSENT
                ld (GS_STATE),a
                ld a,GS_CMD_RESET
                call GsCommand
                ret nc                          ; платы нет — больше не пробуем
                ld a,GS_CMD_RAM
                call GsCommand
                ret nc
                call GsRead                     ; ответ #23 не нужен, но шину надо прочитать
                ld a,GS_FX_VOLUME
                call GsData
                ret nc
                ld a,GS_CMD_FX_VOL
                call GsCommand
                ret nc
                xor a
                ld (GS_INDEX),a
                ld (GS_OPEN),a
                call GsClearVoices
                ld a,GS_STATE_LOAD
                ld (GS_STATE),a
                ret

; Начало сэмпла GS_INDEX: FX-слот, параметры голоса, открытие потока. Сэмплы с готовым handle (предзагрузка
; GsPreload) пропускаются.
GsSampleStart:  ld a,(GS_INDEX)
.find:          cp GS_SAMPLE_COUNT
                jp nc,GsAllLoaded
                ld c,a
                ld hl,GS_HANDLES
                call AddHlA
                ld a,(hl)
                cp GS_NONE
                ld a,c                          ; LD признаков не меняет
                jr z,.load                      ; сэмпла в памяти GS ещё нет
                inc a
                ld (GS_INDEX),a                 ; уже загружен — следующий
                jr .find
.load:          ld l,a
                ld h,0
                add hl,hl
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; ·6 — запись GS_SAMPLES: сектор, секторов, байт
                ld de,GS_SAMPLES
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (GS_SECTOR),de               ; первый сектор сэмпла в паке
                inc hl
                inc hl
                inc hl                          ; секторов не нужны: считаем по байтам
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (GS_LEFT),de
                ld a,GS_CMD_LOAD_FX
                call GsCommand
                jp nc,GsFailed
                call GsReadDirect               ; #38 возвращает handle сразу в #B3
                ld (GS_HANDLE),a
                call GsData                     ; data = handle
                jp nc,GsFailed
                ld a,GS_CMD_SELECT
                call GsCommand
                jp nc,GsFailed
                ld a,(GS_INDEX)
                ld hl,GS_SAMPLE_NOTE
                call AddHlA
                ld a,(hl)                       ; нота: 53 — 11025 Гц, 65 — 22050 Гц
                call GsData
                jp nc,GsFailed
                ld a,GS_CMD_NOTE
                call GsCommand
                jp nc,GsFailed
                ld a,GS_FX_VOLUME
                call GsData
                jp nc,GsFailed
                ld a,GS_CMD_VOLUME
                call GsCommand
                jp nc,GsFailed
                ld a,GS_PRIORITY
                call GsData
                jp nc,GsFailed
                ld a,GS_CMD_PRIORITY
                call GsCommand
                jp nc,GsFailed
                ld a,#FF
                call GsData
                jp nc,GsFailed
                ld a,GS_CMD_SEEK_A
                call GsCommand
                jp nc,GsFailed
                ld a,#FF
                call GsData
                jp nc,GsFailed
                ld a,GS_CMD_SEEK_B
                call GsCommand
                jp nc,GsFailed
                ld a,GS_CMD_OPEN
                call GsCommand
                jp nc,GsFailed
                ld a,1
                ld (GS_OPEN),a
                ret

GsAllLoaded:    ld a,GS_STATE_READY
                ld (GS_STATE),a
                ret

; Очередной кусок сэмпла: чтение до GS_CHUNK секторов пака и выталкивание байтов в GS.
GsChunk:        ld hl,(GS_LEFT)
                ld a,h
                or l
                jp z,GsSampleEnd
                ld de,GS_CHUNK*512
                or a
                sbc hl,de
                jr nc,.take
                ld hl,(GS_LEFT)                 ; последний кусок сэмпла короче
                ex de,hl
.take:          ld (GS_TAKE),de                 ; байт в этом куске
                ld hl,(GS_LEFT)
                or a
                sbc hl,de
                ld (GS_LEFT),hl
                ; чтение куска с SD в буфер загрузчика
                ld a,LOADER_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a
                ld a,(LOADER_READY)
                or a
                jp z,GsFailed                   ; пак не открыт
                ld a,V30_PAGE_BASE+WORK_PAGE
                ld (LOADER_HOST_W1),a
                ld a,SOUND_PAGE
                ld (LOADER_HOST_W3),a
                ld hl,(GS_TAKE)                 ; секторов в куске: (байт + 511) / 512
                ld de,511
                add hl,de
                ld a,h
                srl a
                ld c,a
                ld b,0
                ld (GS_SECTORS),bc
                ld hl,(GS_SECTOR)
                call LOADER_READ
                ld a,HOST_PAGE                  ; LD не меняет признаков
                ld (LOADER_HOST_W3),a
                jp nz,GsFailed
                ld hl,(GS_SECTOR)
                ld de,(GS_SECTORS)
                add hl,de
                ld (GS_SECTOR),hl
                ld hl,(GS_LOADED)
                add hl,de
                ld (GS_LOADED),hl               ; секторов прочитано (шаг SoundPreload — доля шкалы загрузчика SPG)
                ld a,DATA_BUF_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld hl,#8000
                ld de,(GS_TAKE)
                call GsStream
                jp nc,GsFailed
                ld hl,(GS_LEFT)
                ld a,h
                or l
                ret nz
                ; сэмпл дописан
GsSampleEnd:    ld a,GS_CMD_CLOSE
                call GsCommand
                jp nc,GsFailed
                ld a,(GS_INDEX)
                ld l,a
                ld h,0
                ld de,GS_HANDLES
                add hl,de
                ld a,(GS_HANDLE)
                ld (hl),a                       ; сэмпл готов к игре
                ld hl,GS_INDEX
                inc (hl)
                xor a
                ld (GS_OPEN),a
                ret

; Ошибка протокола или чтения: дальше без эффектов.
GsFailed:       ld a,GS_STATE_ABSENT
                ld (GS_STATE),a
                xor a
                ld (GS_OPEN),a
                ret

; Сброс сессии: загруженные сэмплы остаются, голоса (и петля заряда) смолкают.
GsReset:        jp GsStopAll

; HL — данные, DE — байт. CF = 1 — всё отправлено. Портит всё.
; Быстрый путь — OUTI: 48 тактов на байт (11 — статус, 4 — сдвиг, 7 — переход, 16 — вывод, 10 — цикл),
; около 3.4 мкс на 14 МГц. Порты читаются как IN A,(#BB) и пишутся OUTI при C = #B3: и прошивка платы,
; и io.cpp Unreal декодируют только младший байт адреса, старший не важен. Когда в FIFO нет места (на
; железе это бывает в начале потока), уходим на медленный путь с таймаутом.
GsStream:       ld a,d
                or e
                ret z
                ld c,GS_PORT_DATA & #FF
.next:          ld a,e
                or a
                jr nz,.part
                ld a,d
                or a
                jr z,.done
                dec d
                ld b,0                          ; полный блок 256 байт
                jr .byte
.part:          ld b,e                          ; хвост 1…255 байт
                ld e,0
.byte:          in a,(GS_PORT_CMD & #FF)
                rlca
                jr c,.stall
                outi                            ; (HL) → порт C, B--, HL++
                jp nz,.byte
                jr .next
.stall:         push bc
                ld bc,GS_TIMEOUT
.wait:          in a,(GS_PORT_CMD & #FF)
                rlca
                jr nc,.ready
                dec bc
                ld a,b
                or c
                jr nz,.wait
                pop bc
                or a
                ret                             ; FIFO не освобождается — плата потеряна
.ready:         pop bc
                jr .byte
.done:          scf
                ret

; A — команда в #BB; ждём бит 0 = 0. CF = 1 — выполнена. Портит AF, BC, HL.
GsCommand:      ld bc,GS_PORT_CMD
                out (c),a
                ld hl,GS_TIMEOUT
.wait:          in a,(c)
                rrca
                jr nc,.ready
                dec hl
                ld a,h
                or l
                jr nz,.wait
                call GsFail                     ; плата не подтвердила команду: обмен пропал
                or a
                ret
.ready:         scf
                ret

; Счёт неудачных обменов с платой: по нему видно, теряются ли запуски и остановки эффектов
; (жалоба пользователя 2026-09-20: «SFX срабатывают не каждый раз»). Портит только флаги.
GsFail:         push hl
                ld hl,(GS_FAILS)
                inc hl
                ld (GS_FAILS),hl
                pop hl
                ret

; A — байт данных: сначала ждём место в FIFO (бит 7 = 0), потом пишем в #B3. Портит AF, BC, HL.
GsData:         ld c,a
                ld b,0                          ; байт переживает ожидание в C
                push bc
                ld bc,GS_PORT_CMD
                ld hl,GS_TIMEOUT
.wait:          in a,(c)
                rlca
                jr nc,.ready
                dec hl
                ld a,h
                or l
                jr nz,.wait
                pop bc
                call GsFail                     ; плата не освободила FIFO: обмен пропал
                or a
                ret
.ready:         pop hl                          ; H = 0, L = байт
                ld a,l
                ld bc,GS_PORT_DATA
                out (c),a
                scf
                ret

; Ждём бит 7 = 1 и читаем байт из #B3; при таймауте читаем напрямую (так отвечает HLE Unreal).
GsRead:         ld bc,GS_PORT_CMD
                ld hl,GS_TIMEOUT
.wait:          in a,(c)
                rlca
                jr c,GsReadDirect
                dec hl
                ld a,h
                or l
                jr nz,.wait
GsReadDirect:   ld bc,GS_PORT_DATA
                in a,(c)
                ret

; --- состояние --------------------------------------------------------------------------------
GS_STATE        DB GS_STATE_NEW
GS_PRELOAD      DB 0                    ; 1 — предзагрузка звука кредита уже пробовалась (удачно или нет)
GS_DETECTED     DB 0                    ; решение о плате принято
GS_PROBES       DB 0                    ; неудачных опросов платы подряд
GS_PRESENT      DB 0                    ; плата General Sound ответила на #F3
GS_INDEX        DB 0                    ; загружаемый сэмпл
GS_OPEN         DB 0                    ; поток #D1 открыт
GS_SECTOR       DW 0                    ; следующий сектор пака
GS_LEFT         DW 0                    ; байт осталось в сэмпле
GS_TAKE         DW 0                    ; байт в текущем куске
GS_SECTORS      DW 0                    ; секторов в текущем куске
GS_LOADED       DW 0                    ; секторов прочитано с начала шага SoundPreload
GS_HANDLE       DB 0
GS_COMMAND      DB 0
GS_SLOT         DB 0                    ; команда − $30: индекс таблиц команд
GS_SAMPLE       DB 0
GS_VOICE        DB 0
GS_LAST_VOICE   DB 0                    ; канал последнего запуска: чередование сторон
GS_CHARGE_HOLD  DB 0                    ; ROM начал накопление BEAM ($32) и не остановил — круг продлеваем
GS_CHARGE_VOICE DB GS_NONE              ; канал круга накопления: продлеваем на нём же, без скачков сторон
GS_FRAMES_LAST  DB 0                    ; младший байт REG_FRAMES прошлого GsTick
GS_VOICE_CMD    DS GS_CHANNELS, GS_NONE ; команда, звучащая на канале
GS_VOICE_LEFT   DS GS_CHANNELS          ; кадров до конца (0 — свободен)
GS_HANDLES      DS GS_SAMPLE_COUNT, GS_NONE
