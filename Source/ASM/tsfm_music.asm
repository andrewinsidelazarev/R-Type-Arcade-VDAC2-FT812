; ============================================================================
; Плеер музыки для TurboSound FM (2×YM2203) на ZX-MultiSound.
;
; Партитура снята с YM2151 оригинала в MAME и переложена на OPN конвертером
; Source/Tools/ym2151_to_tsfm.py. Игра занимает всего 4 FM-канала из восьми,
; поэтому переаранжировки нет: каналы OPM 0…2 идут в первый чип, канал 3 — во
; второй.
;
; Интерфейс платы (взято из RTL UzixLS/zx-multisound, cpld/rtl/top.v):
;   #FFFD — регистр адреса, #BFFD — данные;
;   выбор чипа — запись в #FFFD значения вида 1111xxxx, бит 0 = номер чипа
;   (#FE — первый чип, #FF — второй).
;
; Формат потока: [пауза в кадрах][число записей]([чип][регистр][значение])…,
; конец потока — пара $FF $00 (пауза $FF И следующий счётчик $00).
; ВАЖНО: пауза $FF с ненулевым счётчиком — легитимный блок с паузой 255
; кадров; такие блоки в потоке есть, и признак конца обязан проверять ОБА
; байта. Проверка только по $FF обрывала музыку на 248-м байте (2 % потока).
;
; ЛОВУШКА (уже учтена): TsfmMusic_Write и TsfmMusic_SelectChip делают LD BC,#FFFD
; и затирают BC. Поэтому счётчик записей блока сохраняется через стек вокруг ОБОИХ
; вызовов, а номер канала при заглушении держится в памяти, а не в регистре.
; ============================================================================

TSFM_PORT_ADDR    EQU #FFFD
TSFM_PORT_DATA    EQU #BFFD
; Команда выбора чипа в #FFFD (по RTL UzixLS/zx-multisound top.v:118-122):
; старший ниббл ОБЯЗАН быть 1111 (маска команды), бит 0 = номер чипа
; (0→YM1, 1→YM2). Бит 1 = ~ym_get_stat, бит 2 = fm*_ena (0 → выход 0,
; 1 → Hi-Z). По сбросу fm*_ena=0; оба варианта (0 и z) на плате дают
; unmute — это подтверждено рабочим плеером WildCommander Improved
; (WPLAYER.ASM, TFMDET/AYOFF), который играет именно на #FE/#FF.
; ФАКТ С ЖЕЛЕЗА (2026-08-07): перебор восьми форм команды в тест-сборке дал
; звук — значит чип и порты исправны. Играет форма с битом 2 = 0 (un-mute);
; прежние #FE/#FF (бит 2 = 1, Hi-Z) на этой плате звука не давали. Берём
; %11111000/%11111001 — ровно ту, что использует рабочий WildCommander.
TSFM_SELECT_CHIP0 EQU #F8          ; 1111_1000: YM1, un-mute
TSFM_SELECT_CHIP1 EQU #F9          ; 1111_1001: YM2, un-mute
TSFM_STREAM_BASE  EQU #C000        ; страница потока мапится в slot3
TSFM_END_MARKER   EQU #FF
TSFM_PAGE_MARKER  EQU #FE          ; «блоки продолжаются в следующей странице»
TSFM_MAX_BLOCKS   EQU 64           ; предохранитель от битого потока за кадр
TSFM_REG_KEYON    EQU #28
TSFM_REG_MODE     EQU #27          ; LFO/таймеры/прерывания
TSFM_REG_PRESCALE EQU #2D          ; прескалер /6: YM2203 платы тактируется 3.5 МГц
                                   ; (ym_m = 32 МГц × 7/64), и /6 даёт 48 611 Гц синтеза —
                                   ; частоту, на которую рассчитаны F-номера потока
; Пауза между записями в чип. Минимум по даташиту YM2203 — 17 тактов чипа,
; при его фиксированных 1.75 МГц это ≈9.7 мкс, то есть ≈136 тактов Z80 на
; 14 МГц. 12×DJNZ ≈ 156 тактов ≈ 11 мкс: запас есть, но вдвое быстрее прежних
; 24. Это удваивает бюджет записей в кадре, и партитуру больше не приходится
; резать — она идёт в чип такой, какой снята с оригинала.
TSFM_WRITE_DELAY  EQU 12

; ---------------------------------------------------------------------------
; TsfmMusic_Start — начать воспроизведение с начала потока.
; ---------------------------------------------------------------------------
TsfmMusic_Start:
                CALL TsfmMusic_InitChips         ; un-mute + прескалер + режим + key-off
                XOR  A
                LD   (TsfmMusic_PageIndex), A    ; трек начинается с первой страницы
                LD   HL, TSFM_STREAM_BASE
                LD   (TsfmMusic_Ptr), HL
                XOR  A
                LD   (TsfmMusic_Wait), A
                LD   A, 1
                LD   (TsfmMusic_Active), A
                RET

; ---------------------------------------------------------------------------
; TsfmMusic_InitChips — обязательный минимум перед первой нотой (ответ Z-Code):
; снять mute, задать прескалер /6, обнулить режим, key-off всех каналов.
; Оба чипа. Приём с провалом: chip0 инициализируется, затем провал в chip1.
; ---------------------------------------------------------------------------
TsfmMusic_InitChips:
                XOR  A                           ; чип 0
                CALL TsfmMusic_InitOneChip
                LD   A, 1                         ; чип 1
TsfmMusic_InitOneChip:
                CALL TsfmMusic_SelectChip         ; #F2/#F3: выбор + un-mute
                LD   E, TSFM_REG_PRESCALE : LD D, #00 : CALL TsfmMusic_Write
                LD   E, TSFM_REG_MODE     : LD D, #00 : CALL TsfmMusic_Write
                LD   E, TSFM_REG_KEYON    : LD D, #00 : CALL TsfmMusic_Write
                LD   E, TSFM_REG_KEYON    : LD D, #01 : CALL TsfmMusic_Write
                LD   E, TSFM_REG_KEYON    : LD D, #02 : CALL TsfmMusic_Write
                RET

; ---------------------------------------------------------------------------
; TsfmMusic_Stop — остановить и заглушить оба чипа.
; ---------------------------------------------------------------------------
TsfmMusic_Stop:
                XOR  A
                LD   (TsfmMusic_Active), A
                ; fall through

; Снять key-on со всех каналов обоих чипов.
TsfmMusic_Silence:
                LD   A, 0
                CALL TsfmMusic_SelectChip
                CALL TsfmMusic_SilenceChip
                LD   A, 1
                CALL TsfmMusic_SelectChip
TsfmMusic_SilenceChip:
                ; Номер канала — в памяти: TsfmMusic_Write затирает BC.
                XOR  A
                LD   (TsfmMusic_Channel), A
.channel:       LD   A, (TsfmMusic_Channel)
                LD   D, A                        ; операторы = 0 ⇒ key-off
                LD   E, TSFM_REG_KEYON
                CALL TsfmMusic_Write
                LD   A, (TsfmMusic_Channel)
                INC  A
                LD   (TsfmMusic_Channel), A
                CP   3                           ; три FM-канала на чип
                JR   C, .channel
                RET

; ---------------------------------------------------------------------------
; TsfmMusic_TestTone — диагностика «жив ли чип» (рецепт Z-Code, ответ 7).
; Один непрерывный тон на канале 0 первого чипа, без партитуры и без потока.
; Собирается только при -DRTYPE_TSFM_TEST и вызывается вместо музыки:
;   есть гудение  → порты, un-mute и cfg[0] в порядке, виновата партитура;
;   тишина        → чип не получает записи (cfg[0]/перемычка/обвязка платы).
; ---------------------------------------------------------------------------
; Перебор вариантов команды выбора чипа: если тон зазвучит на каком-то из них,
; значит верна именно эта форма команды. #F8 — та, что использует рабочий
; WPLAYER (WildCommander); #F2/#F3 — мой вариант; #FE/#FF — прежний (bit2=1).
TsfmMusic_TestSelects:
                DEFB #F8, #F9, #F2, #F3, #FC, #FD, #FE, #FF
TSFM_TEST_SELECTS EQU 8

; ---------------------------------------------------------------------------
; TsfmMusic_Detect — детект TSFM ровно как в рабочем WildCommander (TFMDET):
;   #F8 в #FFFD (маска 1111, un-mute, режим чтения статуса),
;   регистр $00, значение $BF, затем чтение #FFFD.
; У YM2203 бит7 прочитанного статуса = BUSY. Если чипа нет, шина подтянута к
; #FF и бит7 = 1. Результат: A = 1 (чип есть) или 0, дубль в TsfmMusic_Present.
; ---------------------------------------------------------------------------
TsfmMusic_Detect:
                LD   BC, TSFM_PORT_ADDR
                LD   A, %11111000
                OUT  (C), A
                CALL TsfmMusic_DetectWait
                XOR  A
                OUT  (C), A                      ; выбрать регистр $00
                CALL TsfmMusic_DetectWait
                LD   B, HIGH TSFM_PORT_DATA      ; BC = #BFFD
                LD   A, #BF
                OUT  (C), A                      ; записать значение
                CALL TsfmMusic_DetectWait
                LD   B, HIGH TSFM_PORT_ADDR      ; BC = #FFFD
                IN   A, (C)                      ; статус чипа
                OR   A                            ; выставить флаг знака по бит7
                LD   A, 1
                JP   P, .present                 ; бит7 = 0 → чип отвечает
                XOR  A
.present:       LD   (TsfmMusic_Present), A
                OR   A
                RET

TsfmMusic_DetectWait:
                PUSH BC
                LD   B, 0
.w:             DJNZ .w
                POP  BC
                RET

TsfmMusic_Present:   DEFB 0

TsfmMusic_TestTone:
                CALL TsfmMusic_Detect            ; сначала — есть ли чип вообще
                CALL TsfmMusic_TestAY            ; затем AY-часть тех же чипов
                LD   A, TSFM_TEST_SELECTS
                LD   (TsfmMusic_TestLeft), A
                LD   HL, TsfmMusic_TestSelects
                LD   (TsfmMusic_TestPtr), HL
.variant:       LD   HL, (TsfmMusic_TestPtr)
                LD   A, (HL)
                INC  HL
                LD   (TsfmMusic_TestPtr), HL
                LD   (TsfmMusic_TestSelect), A
                CALL TsfmMusic_TestOne
                ; Пауза ≈2 секунды между вариантами, чтобы на слух различить.
                LD   B, 0
.delay1:        LD   C, 0
.delay2:        DEC  C : JR NZ, .delay2
                DJNZ .delay1
                LD   HL, TsfmMusic_TestLeft
                DEC  (HL)
                JR   NZ, .variant
                RET

TsfmMusic_TestPtr:    DEFW 0
TsfmMusic_TestLeft:   DEFB 0
TsfmMusic_TestSelect: DEFB 0

; ---------------------------------------------------------------------------
; TsfmMusic_TestAY — писк через AY-СОВМЕСТИМУЮ часть YM2203 (регистры $00-$0F)
; на тех же портах #FFFD/#BFFD. Разделяет две причины тишины:
;   слышно  → порты и cfg[0] в порядке, молчит именно FM-часть;
;   тишина  → до чипа вообще не доходят записи (cfg[0]/перемычка/обвязка).
; Играет ~2 секунды на обоих вариантах выбора чипа.
; ---------------------------------------------------------------------------
TsfmMusic_TestAY:
                LD   A, #FE                      ; вариант выбора чипа 1
                CALL TsfmMusic_TestAYOne
                LD   A, #FF                      ; вариант выбора чипа 2
TsfmMusic_TestAYOne:
                LD   BC, TSFM_PORT_ADDR
                OUT  (C), A
                LD   B, TSFM_WRITE_DELAY
.w:             DJNZ .w
                LD   E, #00 : LD D, #FE : CALL TsfmMusic_Write  ; период канала A, младший
                LD   E, #01 : LD D, #01 : CALL TsfmMusic_Write  ; период, старший (~440 Гц)
                LD   E, #07 : LD D, #3E : CALL TsfmMusic_Write  ; микшер: тон A включён
                LD   E, #08 : LD D, #0F : CALL TsfmMusic_Write  ; громкость A максимум
                ; Пауза ≈2 с, затем выключить, чтобы не мешать FM-тестам.
                LD   B, 0
.d1:            LD   C, 0
.d2:            DEC  C : JR NZ, .d2
                DJNZ .d1
                LD   E, #08 : LD D, #00 : CALL TsfmMusic_Write  ; громкость в ноль
                RET

; Один прогон тона с текущим вариантом команды выбора.
TsfmMusic_TestOne:
                LD   BC, TSFM_PORT_ADDR
                LD   A, (TsfmMusic_TestSelect)
                OUT  (C), A                      ; проверяемая команда выбора
                LD   B, TSFM_WRITE_DELAY
.w:             DJNZ .w
                LD   E, TSFM_REG_KEYON    : LD D, #00 : CALL TsfmMusic_Write ; глушим прошлый вариант
                LD   E, TSFM_REG_PRESCALE : LD D, #00 : CALL TsfmMusic_Write ; прескалер /6
                LD   E, TSFM_REG_MODE     : LD D, #00 : CALL TsfmMusic_Write ; LFO/таймеры off
                LD   E, #B0 : LD D, #30 : CALL TsfmMusic_Write  ; FB=6, алгоритм 0
                LD   E, #30 : LD D, #71 : CALL TsfmMusic_Write  ; модулятор: DT=0, MUL=1
                LD   E, #40 : LD D, #23 : CALL TsfmMusic_Write  ; TL модулятора
                LD   E, #34 : LD D, #01 : CALL TsfmMusic_Write  ; несущая: MUL=1
                LD   E, #44 : LD D, #00 : CALL TsfmMusic_Write  ; TL несущей = максимум
                LD   E, #50 : LD D, #1F : CALL TsfmMusic_Write  ; AR модулятора
                LD   E, #54 : LD D, #1F : CALL TsfmMusic_Write  ; AR несущей
                LD   E, #60 : LD D, #00 : CALL TsfmMusic_Write  ; D1R = 0 (не затухает)
                LD   E, #64 : LD D, #00 : CALL TsfmMusic_Write
                LD   E, #80 : LD D, #00 : CALL TsfmMusic_Write  ; RR = 0
                LD   E, #84 : LD D, #00 : CALL TsfmMusic_Write
                LD   E, #B4 : LD D, #C0 : CALL TsfmMusic_Write  ; оба выхода включены
                LD   E, #A4 : LD D, #32 : CALL TsfmMusic_Write  ; block=6, F-Num старший
                LD   E, #A0 : LD D, #A2 : CALL TsfmMusic_Write  ; F-Num младший (≈440 Гц)
                LD   E, #28 : LD D, #F0 : CALL TsfmMusic_Write  ; KEY ON, все операторы
                RET

; ---------------------------------------------------------------------------
; TsfmMusic_Update — вызывать раз в кадр из главного цикла.
; Портит AF, BC, DE, HL.
; ---------------------------------------------------------------------------
TsfmMusic_Update:
                LD   A, (TsfmMusic_Active)
                OR   A
                RET  Z

                ; Пауза идёт — просто тикаем. Указатель всегда стоит на начале
                ; блока (на его байте паузы), а флаг TsfmMusic_Armed говорит,
                ; что пауза этого блока уже прочитана и отсчитана.
                LD   A, (TsfmMusic_Wait)
                OR   A
                JR   Z, .play
                DEC  A
                LD   (TsfmMusic_Wait), A
                RET  NZ

.play:          GetPage3
                LD   (TsfmMusic_SavedPage), A
                CALL TsfmMusic_MapCurrentPage
                LD   HL, (TsfmMusic_Ptr)
                LD   A, TSFM_MAX_BLOCKS
                LD   (TsfmMusic_Guard), A

.block:         LD   A, (TsfmMusic_Guard)
                DEC  A
                LD   (TsfmMusic_Guard), A
                JR   Z, .leave                   ; слишком много блоков за кадр

                ; Пауза текущего блока: читаем только если ещё не отсчитана.
                LD   A, (TsfmMusic_Armed)
                OR   A
                JR   NZ, .haveWait               ; уже отсчитана — сразу к записям
                LD   A, (HL)
                CP   TSFM_END_MARKER
                JR   Z, .finished
                CP   TSFM_PAGE_MARKER
                JR   Z, .nextPage
                OR   A
                JR   Z, .consumeWait             ; нулевая пауза — играем сейчас
                ; Ненулевая пауза: взводим таймер и выходим до её истечения.
                LD   (TsfmMusic_Wait), A
                LD   A, 1
                LD   (TsfmMusic_Armed), A
                JR   .leave

.consumeWait:   LD   A, 1
                LD   (TsfmMusic_Armed), A
.haveWait:      INC  HL                          ; пропустить байт паузы
                LD   B, (HL)                     ; число записей
                INC  HL
                XOR  A
                LD   (TsfmMusic_Armed), A        ; блок начат — пауза израсходована
                LD   A, B
                OR   A
                JR   Z, .block                   ; пустой блок (длинная тишина)
.write:         LD   A, (HL)                     ; чип
                INC  HL
                PUSH BC
                CALL TsfmMusic_SelectChip        ; портит BC — счётчик на стек
                POP  BC
                LD   E, (HL)                     ; регистр
                INC  HL
                LD   D, (HL)                     ; значение
                INC  HL
                PUSH BC
                CALL TsfmMusic_Write             ; тоже портит BC
                POP  BC
                DJNZ .write
                JR   .block                      ; следующий блок этого же кадра

.nextPage:      LD   A, (TsfmMusic_PageIndex)
                INC  A
                LD   (TsfmMusic_PageIndex), A
                CP   TSFM_MUSIC_PAGE_COUNT
                JR   NC, .finished
                CALL TsfmMusic_MapCurrentPage
                LD   HL, TSFM_STREAM_BASE
                JR   .block

                ; Конец потока — трек зацикливается: в оригинале музыка уровня
                ; играет непрерывно, пока идёт этап.
.finished:      XOR  A
                LD   (TsfmMusic_PageIndex), A
                LD   (TsfmMusic_Wait), A
                LD   (TsfmMusic_Armed), A
                CALL TsfmMusic_MapCurrentPage
                LD   HL, TSFM_STREAM_BASE
                JR   .block

.leave:         LD   (TsfmMusic_Ptr), HL
                LD   A, (TsfmMusic_SavedPage)
                SetPage3_A
                RET

TsfmMusic_Armed:     DEFB 0

; ---------------------------------------------------------------------------
; TsfmMusic_MapCurrentPage — замапить в slot3 страницу потока по текущему
; индексу. Запись таблицы: [номер страницы][длина.W]. Портит AF, DE, HL.
; ---------------------------------------------------------------------------
TsfmMusic_MapCurrentPage:
                PUSH BC
                LD   A, (TsfmMusic_PageIndex)
                LD   L, A
                LD   H, 0
                LD   D, H
                LD   E, L
                ADD  HL, HL                      ; ×2
                ADD  HL, DE                      ; ×3 — запись [страница][длина.W]
                LD   DE, TsfmMusicPageTable
                ADD  HL, DE
                LD   A, (HL)
                SetPage3_A
                POP  BC
                RET

TsfmMusic_PageIndex: DEFB 0

; ---------------------------------------------------------------------------
; TsfmMusic_SelectChip — A = 0/1. Портит AF, BC.
; ---------------------------------------------------------------------------
TsfmMusic_SelectChip:
                LD   BC, TSFM_PORT_ADDR
                OR   A
                LD   A, TSFM_SELECT_CHIP0
                JR   Z, .out
                LD   A, TSFM_SELECT_CHIP1
.out:           OUT  (C), A
                LD   B, TSFM_WRITE_DELAY         ; чипу нужно время до след. записи
.wait:          DJNZ .wait
                RET

; ---------------------------------------------------------------------------
; TsfmMusic_Write — E = регистр, D = значение. Портит AF, BC.
; Паузы после КАЖДОГО OUT: YM2203 без них теряет записи. C держит #FD весь
; вызов, B переиспользуется под задержку и перезагружается под порт данных.
; ---------------------------------------------------------------------------
TsfmMusic_Write:
                LD   BC, TSFM_PORT_ADDR          ; B=#FF, C=#FD
                OUT  (C), E                       ; номер регистра → #FFFD
                LD   B, TSFM_WRITE_DELAY
.wa:            DJNZ .wa
                LD   B, HIGH TSFM_PORT_DATA        ; B=#BF, C=#FD → #BFFD
                OUT  (C), D                       ; значение → #BFFD
                LD   B, TSFM_WRITE_DELAY
.wd:            DJNZ .wd
                RET

TsfmMusic_Ptr:       DEFW TSFM_STREAM_BASE
TsfmMusic_Wait:      DEFB 0
TsfmMusic_Active:    DEFB 0
TsfmMusic_SavedPage: DEFB 0
TsfmMusic_Channel:   DEFB 0
TsfmMusic_Guard:     DEFB 0
