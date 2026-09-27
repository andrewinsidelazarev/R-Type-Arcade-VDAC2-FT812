; Эффекты на простом AY — для машин без платы General Sound. Часть звуковой страницы SOUND_PAGE.
;
; Метод взят у Zuma Deluxe VDAC2 (Build/Reference/Zuna-Deluxe-VDAC2-FT812: Source/OTHER/make_ay_sfx.py
; и Source/ASM/AYSfx.asm): эффект — поток строк «сколько кадров держать + полные регистры AY 0…10»,
; подобранных офлайн под звук оригинала. Плеер только отсчитывает кадры и выгружает регистры, никакой
; арифметики звука на Z80 нет.
;
; Данные готовит Source/Tools/rtype_ay_sfx.py: таблица на каждую команду (три байта — смещение строки
; от начала блока) и сами строки по AY_ROW_SIZE байт, нулевой счётчик кадров — конец эффекта. Блок
; лежит в паке (AY_DATA_SECTOR) и читается в страницы буфера мелодий: без GS музыки нет вовсе
; (решение пользователя 2026-09-21), и семь страниц MUSIC_PAGE0 свободны.
;
; Голос один: AY у простого Spectrum отдан эффектам целиком, новый эффект прерывает прежний. Это
; отступление от аркады на аппаратном пределе — у неё эффекты идут по восьми каналам YM2151.

AY_REG_PORT     EQU #FFFD
AY_DATA_PORT    EQU #BFFD
AY_MIXER_SILENT EQU #3F
AY_WINDOW       EQU #8000               ; окно W2, как у потока мелодии
AY_PAGE0        EQU MUSIC_PAGE0         ; блок эффектов ложится в буфер мелодий

; Шаг предзагрузки вместо GsPreload, когда платы нет: ждём открытия пака и читаем блок эффектов.
; Портит всё, как и GsPreload.
AyPreload:      ld a,(AY_LOADED)
                or a
                ret nz
                ld a,LOADER_PAGE
                ld bc,PORT_PAGE2
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a
                ld a,(LOADER_READY)
                or a
                ret z                           ; пак ещё не открыт — в следующем кадре
                jp AyLoad

; Загрузка блока с SD в страницы буфера. Зовут один раз, когда платы GS нет и пак открыт.
; Возврат: CF = 1 — блок в памяти. Портит всё.
AyLoad:         ld a,(AY_LOADED)
                or a
                scf
                ret nz
                ld de,AY_DATA_SECTOR
                ld bc,AY_DATA_SECTORS
                call MusicLoad                  ; тот же чтец, что у потоков мелодий
                ret nz
                ld a,1
                ld (AY_LOADED),a
                scf
                ret

; Тишина и сброс состояния. Портит A, BC, E, HL.
AyInit:         xor a
                ld (AY_ACTIVE),a
                ld (AY_LEFT),a
                ; провал в AySilence

AySilence:      ld e,0
                ld a,8
                call AyWriteReg
                ld a,9
                call AyWriteReg
                ld a,10
                call AyWriteReg
                ld e,AY_MIXER_SILENT
                ld a,7
                jp AyWriteReg

AyStop:         xor a
                ld (AY_ACTIVE),a
                ld (AY_LEFT),a
                jp AySilence

; A — команда $30…$FF. Ищем эффект в таблице и начинаем с первой строки. Портит всё.
AyPlay:         ld (AY_REQUEST),a               ; команду держим в памяти: PUSH AF/POP AF затёр бы
                ld hl,(AY_CALLS)                ; признак возврата AyLoad сохранёнными флагами
                inc hl
                ld (AY_CALLS),hl
                call AyLoad
                ret nc                          ; блок не прочитан — играть нечего
                ; Тот же фильтр экрана, что у платы (GsPlay): на нашем титуле машина за кадром крутит
                ; демо и шлёт её эффекты, а показываем мы свой экран. Пропускаем только звук нажатого
                ; старта, как с платой.
                ld a,(API_SHOW)
                rlca
                jr c,.sound
                ld a,(AY_REQUEST)
                cp GS_START_COMMAND
                ret nz
.sound:         ld a,(AY_REQUEST)
                sub #30
                ret c
                ld hl,AY_COMMAND_INDEX
                ld d,0
                ld e,a
                add hl,de
                ld a,(hl)
                cp AY_SOUND_COUNT
                ret nc                          ; команде эффект не сопоставлен
                ld (AY_INDEX),a
                ; Остановка ($33 для заряда $32, $5B для $5A): звука у неё нет, она глушит свою цель,
                ; если та звучит. Прежде её запись таблицы с нулевым смещением читалась как поток, и
                ; вместо тишины играли байты самой таблицы.
                ld hl,AY_STOP_TARGET
                call AyIndexByte
                or a
                jr z,.priority
                ld b,a
                ld a,(AY_ACTIVE)
                or a
                ret z
                ld a,(AY_CURRENT)
                cp b
                ret nz                          ; звучит не та команда — глушить нечего
                jp AyStop
                ; Вытеснение по правилу драйвера аркады: голос один, и новый эффект прерывает
                ; звучащий, только если он не менее важен (меньше число — важнее); та же команда
                ; перезапускается. Без этого частые выстрелы ($30, приоритет 80) обрывали всё: луч
                ; мини-босса $3A (16) доигрывал 14 %, взрывы (48) — 12 % (модель по журналу этапа 1).
.priority:      ld hl,AY_PRIORITY
                call AyIndexByte
                ld (AY_NEW_PRIO),a
                ld a,(AY_ACTIVE)
                or a
                jr z,.start
                ld a,(AY_REQUEST)
                ld b,a
                ld a,(AY_CURRENT)
                cp b
                jr z,.start                     ; та же команда — перезапуск на месте
                ld a,(AY_PRIO)
                ld b,a
                ld a,(AY_NEW_PRIO)
                cp b
                jr z,.start
                ret nc                          ; новый менее важен — звучащий доигрывает
.start:         ld a,(AY_REQUEST)
                ld (AY_CURRENT),a
                ld a,(AY_NEW_PRIO)
                ld (AY_PRIO),a
                ld a,(AY_INDEX)
                ; запись таблицы: индекс·3 — смещение строк от начала блока
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; HL = индекс·3
                ld de,AY_WINDOW
                add hl,de
                ld a,AY_PAGE0
                call AyMapPage
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld a,(hl)                       ; старший байт смещения
                call AySeek
                xor a
                ld (AY_LEFT),a
                inc a
                ld (AY_ACTIVE),a
                ld hl,(AY_STARTS)
                inc hl
                ld (AY_STARTS),hl
                jp AyRow                        ; первая строка звучит сразу

; Байт таблицы HL по индексу эффекта AY_INDEX → A. Портит DE, HL.
AyIndexByte:    ld a,(AY_INDEX)
                ld e,a
                ld d,0
                add hl,de
                ld a,(hl)
                ret

; Кадр эффекта: отсчёт кадров строки, по исчерпании — следующая строка. Портит всё.
AyTick:         ld a,(AY_ACTIVE)
                or a
                ret z
                ld a,(AY_LEFT)
                or a
                jp z,AyRow
                dec a
                ld (AY_LEFT),a
                ret nz
                ; провал в AyRow: строка доиграла

; Следующая строка потока: счётчик кадров и одиннадцать регистров.
AyRow:          call AyByte
                or a
                jp z,AyEnd                      ; нулевой счётчик — конец эффекта (jp: метка далеко)
                ld (AY_LEFT),a
                ld b,0                          ; B — номер регистра
.reg:           push bc
                call AyByte
                pop bc
                ld e,a
                ld a,b
                push bc
                call AyWriteReg
                pop bc
                inc b
                ld a,b
                cp 11
                jr c,.reg
                ret

; Конец потока. Накопление BEAM $32 в аркаде — вступление и бесконечный круг до $33, а вырезка
; оригинала кончается ещё на круге: пока ROM держит накопление, возвращаемся на два круга назад
; (AY_CHARGE_LOOP, rtype_ay_sfx.charge_loop_offset). Условие — то же, что у GsChargeWatch: игрок в
; полёте (обработчик записи $2027) и счётчик заряда DS:$003D не ноль. По одному $33 решать нельзя:
; погибнув с набранным зарядом, ROM его не шлёт, и круг звучал бы сиреной вечно.
AyEnd:          ld a,(AY_CURRENT)
                cp #32
                jp nz,AyStop
                ld a,V30_PAGE_BASE+WORK_PAGE
                ld bc,PORT_PAGE1
                out (c),a                       ; рабочее ОЗУ V30 — в окно W1, как в GsChargeWatch
                ld hl,(#4000+#0020)             ; обработчик записи игрока
                ld de,#2027
                or a
                sbc hl,de
                jp nz,AyStop                    ; игрок не в полёте — накопления нет
                ld a,(#4000+#003D)
                or a
                jp z,AyStop                     ; счётчик заряда обнулён
                ld a,AY_CHARGE_LOOP >> 16
                ld de,AY_CHARGE_LOOP & #FFFF
                call AySeek
                jp AyRow

; A:D:E — смещение строки от начала блока → AY_PAGE и AY_PTR (страница = AY_PAGE0 + смещение / #4000,
; адрес в окне #8000 + смещение mod #4000). Портит A, DE, HL.
AySeek:         ld l,a
                ld a,d
                and #C0
                rlca
                rlca
                ld h,a                          ; H = биты 14…15 смещения
                ld a,l
                add a,a
                add a,a
                add a,h
                add a,AY_PAGE0
                ld (AY_PAGE),a
                ld a,d
                and #3F
                or #80
                ld d,a
                ld (AY_PTR),de
                ret

; Очередной байт потока в A: окно перематывается на следующую страницу по краю #C000. Портит F, HL.
AyByte:         ld a,(AY_PAGE)
                call AyMapPage
                ld hl,(AY_PTR)
                ld a,h
                cp #C0
                jr c,.take
                ld a,(AY_PAGE)
                inc a
                ld (AY_PAGE),a
                call AyMapPage
                ld hl,AY_WINDOW
.take:          ld a,(hl)
                inc hl
                ld (AY_PTR),hl
                ret

; A — страница блока эффектов в окно W2. Портит BC.
AyMapPage:      ld bc,PORT_PAGE2
                out (c),a
                ld a,#FF
                ld (W2_PAGE),a                  ; окно занято не потоком мелодии
                ret

; A — номер регистра, E — значение. Портит BC.
AyWriteReg:     ld bc,AY_REG_PORT
                out (c),a
                ld b,AY_DATA_PORT >> 8
                out (c),e
                ret

AY_ACTIVE       DB 0                    ; эффект звучит
AY_LEFT         DB 0                    ; кадров до следующей строки
AY_PTR          DW AY_WINDOW            ; адрес строки в окне W2
AY_PAGE         DB 0                    ; страница строки
AY_LOADED       DB 0                    ; блок эффектов прочитан с SD
AY_REQUEST      DB 0                    ; команда, которую просили сыграть
AY_INDEX        DB 0                    ; её индекс в таблицах эффектов
AY_NEW_PRIO     DB 0                    ; её приоритет
AY_CURRENT      DB 0                    ; команда звучащего эффекта
AY_PRIO         DB 0                    ; приоритет звучащего эффекта
AY_CALLS        DW 0                    ; сколько раз звали AyPlay (диагностика)
AY_STARTS       DW 0                    ; сколько эффектов действительно начато
