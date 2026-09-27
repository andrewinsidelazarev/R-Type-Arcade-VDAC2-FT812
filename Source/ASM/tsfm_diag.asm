; ============================================================================
; ДИАГНОСТИКА TurboSound FM (RTYPE_TSFMDIAG).
;
; Цель: за один запуск на реальном железе ответить, ДОХОДЯТ ли записи в YM2203,
; и отделить «неверные порты» от «неверной инициализации» от «mute».
;
; Что делает:
;   1. Включает видео (FT_DL). Рисует синий фон — если виден синий экран,
;      значит видео и шина FT живы, дошли до диагностики.
;   2. Выбирает чип 0 и шлёт un-mute команду %11111000 (как WildCommander TFMDET).
;   3. Прописывает тестовый тон в FM-канал 0: алгоритм, TL операторов,
;      частоту и KEY-ON. Должен загудеть ровный тон.
;   4. Рисует КРАСНЫЙ прямоугольник во весь экран (контраст с фоном):
;      если виден красный прямоугольник — диагностика отработала полностью,
;      все записи в YM ушли. Если звук при этом есть — FM жив. Если красный
;      есть, а звука нет — проблема в cfg[0]/mute/тактовой, а не в коде.
;
; Включается ключом sjasmplus: -DRTYPE_TSFMDIAG.
; В релиз НЕ входит.
; ============================================================================

TSFMD_PORT_ADDR   EQU #FFFD
TSFMD_PORT_DATA   EQU #BFFD
TSFMD_DELAY       EQU 40            ; 40×DJNZ ≈ 520 тактов — с запасом на 14 МГц

; ---------------------------------------------------------------------------
; TsfmDiag_Run — точка входа. Вызывается из Start ПЕРЕД игровой логикой,
; если определён RTYPE_TSFMDIAG. Не возвращается (зависает на синем фоне,
; чтобы пользователь успел послушать тестовый тон).
; ---------------------------------------------------------------------------
TsfmDiag_Run:
                ; --- Шаг 0: синий фон. Видео работает = дошли до диагностики. ---
                CALL TsfmDiag_DrawBlue
                ; Небольшая пауза, чтобы пользователь увидел синий ДО звука.
                LD   B, 0
.waitBlue:      CALL TsfmDiag_Delay256
                DJNZ .waitBlue

                ; --- Шаг A: unmute + выбор чипа 0. Команда по образцу WildCommander. ---
                LD   BC, TSFMD_PORT_ADDR
                LD   A, %11111000        ; маска 1111, bit0=0 (чип 0), bit1=0, bit2=0 (fm_ena=0)
                OUT  (C), A
                CALL TsfmDiag_ChipDelay

                ; --- Шаг B: прескалер /3 (reg $2E). Обязательно до нот. ---
                LD   E, $2E
                LD   D, $00
                CALL TsfmDiag_WriteReg

                ; --- Шаг C: сброс режима и key-off каналов 0..2 (reg $27, $28). ---
                LD   E, $27
                LD   D, $00
                CALL TsfmDiag_WriteReg
                LD   E, $28
                LD   D, $00
                CALL TsfmDiag_WriteReg
                LD   E, $28
                LD   D, $01
                CALL TsfmDiag_WriteReg
                LD   E, $28
                LD   D, $02
                CALL TsfmDiag_WriteReg

                ; --- Шаг D: настроить инструмент на канале 0 ---
                ; alg/feedback (reg $B0): feedback=7, alg=0 (только слот1)
                LD   E, $B0
                LD   D, %00111000        ; FB=7 (111), CONNECT=000
                CALL TsfmDiag_WriteReg
                ; оператор 1 (модулятор): DT/MUL, reg $30
                LD   E, $30
                LD   D, %00000001        ; DT=0, MULT=1
                CALL TsfmDiag_WriteReg
                ; оператор 1: TL (громкость модулятора), reg $40 — ТИХО, чтобы
                ; несущий оператор звучал чисто. TL=0x3F = почти тишина.
                LD   E, $40
                LD   D, %00111111        ; TL=63 (модулятор почти silent)
                CALL TsfmDiag_WriteReg
                ; оператор 2 (несущий): DT/MUL, reg $34
                LD   E, $34
                LD   D, %00000001        ; DT=0, MULT=1
                CALL TsfmDiag_WriteReg
                ; оператор 2: TL = 0x00 — МАКСИМАЛЬНАЯ громкость несущего.
                LD   E, $44
                LD   D, %00000000        ; TL=0 (громко)
                CALL TsfmDiag_WriteReg
                ; оператор 1: attack rate (reg $50), AR=31 (быстрый старт)
                LD   E, $50
                LD   D, %00011111        ; RS=0, AR=31
                CALL TsfmDiag_WriteReg
                ; оператор 2: attack rate (reg $54)
                LD   E, $54
                LD   D, %00011111
                CALL TsfmDiag_WriteReg
                ; оператор 1: D1R (decay, reg $60) — низкий, чтобы тон держался
                LD   E, $60
                LD   D, %00000000        ; D1R=0 (не затухает)
                CALL TsfmDiag_WriteReg
                LD   E, $64
                LD   D, %00000000
                CALL TsfmDiag_WriteReg
                ; оператор 1: D2R (sustain, reg $70) — 0, не затухает
                LD   E, $70
                LD   D, %00000000
                CALL TsfmDiag_WriteReg
                LD   E, $74
                LD   D, %00000000
                CALL TsfmDiag_WriteReg
                ; оператор 1: release (reg $80), RR=0 — не отпускается
                LD   E, $80
                LD   D, %00000000
                CALL TsfmDiag_WriteReg
                LD   E, $84
                LD   D, %00000000
                CALL TsfmDiag_WriteReg
                ; громкость канала (reg $B4) — максимум, без панорамы по центру
                LD   E, $B4
                LD   D, %10111111        ; AMS=0, PMS=0, L=R=1 (центр), громкость max
                CALL TsfmDiag_WriteReg

                ; --- Шаг E: частота ноты A4 (~440 Гц) в канал 0 ---
                ; F-Number для 1.75 МГц /3: block=3, fnum≈$026A. Младший в $A0, ст. в $A4.
                LD   E, $A0
                LD   D, $6A               ; мл. байт F-Num
                CALL TsfmDiag_WriteReg
                LD   E, $A4
                LD   D, %00110010         ; block=3, старшие биты F-Num
                CALL TsfmDiag_WriteReg

                ; --- Шаг F: KEY-ON канала 0 (reg $28, val $F0) ---
                LD   E, $28
                LD   D, $F0               ; KEY-ON, канал 0
                CALL TsfmDiag_WriteReg

                ; --- Шаг G: КРАСНЫЙ прямоугольник = диагностика завершена. ---
                CALL TsfmDiag_DrawRed

                ; Зависаем: даём пользователю время слушать тестовый тон.
.diagHold:      JR   .diagHold

; ---------------------------------------------------------------------------
; TsfmDiag_WriteReg — E = регистр, D = значение. Портит AF, BC.
; С паузами после каждого OUT (требование шины YM2203).
; ---------------------------------------------------------------------------
TsfmDiag_WriteReg:
                LD   BC, TSFMD_PORT_ADDR
                OUT  (C), E               ; номер регистра → #FFFD
                LD   B, TSFMD_DELAY
.wa:            DJNZ .wa
                LD   B, #BF               ; порт #BFFD (C=#FD)
                OUT  (C), D               ; значение → #BFFD
                LD   B, TSFMD_DELAY
.wd:            DJNZ .wd
                RET

TsfmDiag_ChipDelay:
                PUSH BC
                LD   B, 0
.l:             DJNZ .l
                POP BC
                RET

TsfmDiag_Delay256:
                PUSH BC
                LD   BC, 0
.l:             DEC BC
                LD   A, B
                OR   C
                JR   NZ, .l
                POP BC
                RET

; --- Отрисовка: синий фон на весь физический экран (1024×768). ---
TsfmDiag_DrawBlue:
                FT_CMD_Start
                FT_DL_Start
                FT_ClearColorRGB 0, 0, 80
                FT_ClearAll
                FT_Display
                FT_CMD_Swap
                FT_CMD_Write
                CALL TsfmDiag_FinishSwap
                RET

; --- Красный прямоугольник 300×300 по центру (поверх синего фона). ---
TsfmDiag_DrawRed:
                FT_CMD_Start
                FT_DL_Start
                FT_ClearColorRGB 0, 0, 80      ; синий фон снова
                FT_ClearAll
                FT_VertexFormat 0              ; пиксели (1/1)
                FT_ColorRGB 255, 0, 0          ; красный
                FT_Begin FT_RECTS
                FT_Vertex2ii 360, 230, 0, 0    ; левый-верхний угол
                FT_Vertex2ii 660, 530, 0, 0    ; правый-нижний угол
                FT_End
                FT_Display
                FT_CMD_Swap
                FT_CMD_Write
                CALL TsfmDiag_FinishSwap
                RET

TsfmDiag_FinishSwap:
                LD   A, 200
                LD  (.t), A
.w:             FT_RD_REG8 FT_REG_INT_FLAGS
                AND  FT_INT_SWAP
                RET  NZ
                LD   A, (.t)
                DEC  A
                LD   (.t), A
                JR   NZ, .w
                RET
.t:             DEFB 0
