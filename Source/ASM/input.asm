; ============================================================================
; Input.asm — РЕЗИДЕНТНЫЙ модуль ВСЕГО управления, схема перенесена из HMM2
; VDAC2 (тот же принцип: все источники читаются в одном месте, любая сцена
; опрашивает готовые флаги).
;
; Источники:
;   * Расширенная PS/2-клавиатура ZX Evolution через Mr.Gluk Z-контроллер:
;       OUT #EFF7,#80 = enable; #DFF7 = выбор регистра; #BFF7 = данные.
;       Регистр #F0 = FIFO скан-кодов (set-2). Тот же чип обслуживает RTC и
;       гасит #EFF7 после чтения — поэтому Input_Scan включает его каждый кадр.
;   * Kempston-джойстик (TSLib Input.Kempston).
;   * Мышь (TSLib Input.Mouse) — кнопки ЛКМ/ПКМ.
;
; Схема управления R-Type:
;   Движение корабля  — ↑↓←→ | Q/A/O/P | Kempston.
;   ОГОНЬ (глобальный) — Space | Enter | Kempston-Fire | ЛКМ.
;   ОТПУСКАНИЕ ЗАЩИТЫ  — глобальный ПКМ: AltGr | правая кнопка мыши
;                        (ровно как ПКМ-действие в HMM2).
;
; Применение: Input_Init один раз на старте, Input_Poll один раз за кадр.
; ============================================================================

; Скан-коды PS/2 set-2 (make-коды; стрелки приходят с префиксом E0, но их коды
; уникальны, поэтому при сопоставлении префикс игнорируется).
INP_SC_ESC      EQU #76
INP_SC_UP       EQU #75
INP_SC_DOWN     EQU #72
INP_SC_LEFT     EQU #6B
INP_SC_RIGHT    EQU #74
INP_SC_ENTER    EQU #5A
INP_SC_SPACE    EQU #29
INP_SC_Q        EQU #15
INP_SC_A        EQU #1C
INP_SC_O        EQU #44          ; O = влево (классическая ZX-раскладка)
INP_SC_P        EQU #4D          ; P = вправо
INP_SC_ALT      EQU #11          ; #11 с префиксом E0 = AltGr = ПКМ; без E0 = левый Alt (игнор)

; Биты InputState.
INPUT_LEFT      EQU %00000001
INPUT_RIGHT     EQU %00000010
INPUT_UP        EQU %00000100
INPUT_DOWN      EQU %00001000
INPUT_FIRE      EQU %00010000
INPUT_RELEASE   EQU %00100000    ; отпускание защиты (глобальный ПКМ)

; Флаги «клавиша нажата» (1/0), обновляются Input_Scan.
Input_KEsc:     DEFB 0
Input_KUp:      DEFB 0
Input_KDown:    DEFB 0
Input_KLeft:    DEFB 0
Input_KRight:   DEFB 0
Input_KEnter:   DEFB 0
Input_KSpace:   DEFB 0
Input_KQ:       DEFB 0
Input_KA:       DEFB 0
Input_KO:       DEFB 0
Input_KP:       DEFB 0
Input_KAlt:     DEFB 0           ; AltGr (E0 11) — виртуальная ПКМ
Input_PS2Brk:   DEFB 0           ; ожидается код отпускания (префикс #F0)
Input_PS2Ext:   DEFB 0           ; видели префикс #E0 — отличает AltGr от левого Alt
Input_DrainCnt: DEFB 0           ; ограничитель дренажа FIFO за скан

; ----------------------------------------------------------------------------
; Input_Init — включить Mr.Gluk и взвести PS/2-клавиатуру. Один раз на старте.
; ----------------------------------------------------------------------------
Input_Init:
                CALL Input_ClearState
                LD   BC, #EFF7 : LD A, #80 : OUT (C), A    ; Mr.Gluk enable
                LD   BC, #DFF7 : LD A, #0C : OUT (C), A
                LD   BC, #BFF7 : LD A, #01 : OUT (C), A    ; сброс буфера PS/2
                LD   BC, #DFF7 : LD A, #F0 : OUT (C), A
                LD   BC, #BFF7 : LD A, #02 : OUT (C), A    ; PS/2 ON
                CALL Input_DiscardPS2Fifo
Input_ClearState:
                XOR  A
                LD   (InputState), A
                LD   (InputAnyPressed), A
                LD   (Input_KEsc), A
                LD   (Input_KUp), A
                LD   (Input_KDown), A
                LD   (Input_KLeft), A
                LD   (Input_KRight), A
                LD   (Input_KEnter), A
                LD   (Input_KSpace), A
                LD   (Input_KQ), A
                LD   (Input_KA), A
                LD   (Input_KO), A
                LD   (Input_KP), A
                LD   (Input_KAlt), A
                LD   (Input_PS2Brk), A
                LD   (Input_PS2Ext), A
                LD   (Input_DrainCnt), A
                RET

Input_DiscardPS2Fifo:
                LD   BC, #EFF7 : LD A, #80 : OUT (C), A
                LD   BC, #DFF7 : LD A, #F0 : OUT (C), A
                LD   A, 64
                LD   (Input_DrainCnt), A
                LD   BC, #BFF7
.drain:         IN   A, (C)
                OR   A
                RET  Z
                LD   A, (Input_DrainCnt)
                DEC  A
                LD   (Input_DrainCnt), A
                JR   NZ, .drain
                RET

; ----------------------------------------------------------------------------
; Input_Scan — опрос всех источников за кадр: мышь + дренаж PS/2 FIFO.
; Портит AF, BC, DE, HL.
; ----------------------------------------------------------------------------
Input_Scan:
                CALL Input.Mouse.UpdateMouseState          ; мышь — единая точка опроса
                LD   BC, #EFF7 : LD A, #80 : OUT (C), A    ; enable заново (RTC мог погасить)
                LD   BC, #DFF7 : LD A, #F0 : OUT (C), A    ; регистр FIFO PS/2
                LD   A, 24 : LD (Input_DrainCnt), A        ; ограничить дренаж
                LD   BC, #BFF7
.drain:         IN   A, (C)
                OR   A : RET Z                             ; FIFO пуст
                CP   #FF : JR Z, .overflow                 ; переполнение: отпускания потеряны
                CP   #E0 : JR Z, .set_ext                  ; префикс extended
                CP   #F0 : JR Z, .set_brk                  ; префикс отпускания
                CALL Input_SetKey
.next:          LD   A, (Input_DrainCnt) : DEC A : LD (Input_DrainCnt), A : RET Z
                JR   .drain
.set_brk:       LD   A, 1 : LD (Input_PS2Brk), A
                JR   .next
.set_ext:       LD   A, 1 : LD (Input_PS2Ext), A           ; E0 приходит ПЕРЕД F0
                JR   .next
.overflow:      CALL Input_ClearState                      ; иначе клавиши залипают
                JR   .next

; A = скан-код -> выставить/сбросить флаг. Сохраняет BC (порт дренажа).
Input_SetKey:
                LD   E, A
                LD   A, (Input_PS2Brk)
                XOR  1                                     ; 1 = нажатие, 0 = отпускание
                LD   D, A
                XOR  A : LD (Input_PS2Brk), A
                ; В attract-demo важен любой make-код, включая клавиши, для
                ; которых нет игрового бита. Префиксы E0/F0 сюда не попадают,
                ; поэтому одно физическое нажатие даёт ровно один wake-флаг.
                LD   A, D
                OR   A
                JR   Z, .mapKnown
                LD   A, 1
                LD   (InputAnyPressed), A
.mapKnown:
                LD   A, E
                CP   INP_SC_ALT       : JR Z, .alt
                LD   HL, Input_KEsc   : CP INP_SC_ESC   : JR Z, .sk
                LD   HL, Input_KUp    : CP INP_SC_UP    : JR Z, .sk
                LD   HL, Input_KDown  : CP INP_SC_DOWN  : JR Z, .sk
                LD   HL, Input_KLeft  : CP INP_SC_LEFT  : JR Z, .sk
                LD   HL, Input_KRight : CP INP_SC_RIGHT : JR Z, .sk
                LD   HL, Input_KEnter : CP INP_SC_ENTER : JR Z, .sk
                LD   HL, Input_KSpace : CP INP_SC_SPACE : JR Z, .sk
                LD   HL, Input_KQ     : CP INP_SC_Q     : JR Z, .sk
                LD   HL, Input_KA     : CP INP_SC_A     : JR Z, .sk
                LD   HL, Input_KO     : CP INP_SC_O     : JR Z, .sk
                LD   HL, Input_KP     : CP INP_SC_P     : JR NZ, .eat_ext
.sk:            LD   (HL), D
.eat_ext:       XOR  A : LD (Input_PS2Ext), A              ; реальный код съедает E0
                RET
.alt:           LD   A, (Input_PS2Ext)
                OR   A
                JR   Z, .eat_ext                           ; без E0 = левый Alt → игнор
                LD   HL, Input_KAlt                        ; с E0 = AltGr → виртуальная ПКМ
                JR   .sk

; ----------------------------------------------------------------------------
; Опросы: NZ = активно, Z = нет.
; ----------------------------------------------------------------------------
Input_Esc:      LD   A, (Input_KEsc) : OR A : RET

Input_Up:       LD   A, (Input_KUp) : OR A : RET NZ
                LD   A, (Input_KQ)  : OR A : RET NZ
                LD   A, Input.VK_KEMPSTON_UP
                JP   Input.Kempston.KeyState

Input_Down:     LD   A, (Input_KDown) : OR A : RET NZ
                LD   A, (Input_KA)    : OR A : RET NZ
                LD   A, Input.VK_KEMPSTON_DOWN
                JP   Input.Kempston.KeyState

Input_Left:     LD   A, (Input_KLeft) : OR A : RET NZ
                LD   A, (Input_KO)    : OR A : RET NZ
                LD   A, Input.VK_KEMPSTON_LEFT
                JP   Input.Kempston.KeyState

Input_Right:    LD   A, (Input_KRight) : OR A : RET NZ
                LD   A, (Input_KP)     : OR A : RET NZ
                LD   A, Input.VK_KEMPSTON_RIGHT
                JP   Input.Kempston.KeyState

; Огонь с клавиатуры/джойстика (без мыши).
Input_FireKey:  LD   A, (Input_KSpace) : OR A : RET NZ
                LD   A, (Input_KEnter) : OR A : RET NZ
                LD   A, Input.VK_KEMPSTON_B
                JP   Input.Kempston.KeyState

; Input_Fire — ГЛОБАЛЬНЫЙ огонь: клавиатура/джойстик или ЛКМ.
; Kempston-мышь active-LOW: в покое биты кнопок = 1, при нажатии сбрасываются,
; поэтому CP с маской даёт NZ именно на нажатии (проверено в HMM2 на эмуляторе).
Input_Fire:     CALL Input_FireKey
                RET  NZ
                LD   A, Input.Mouse.SVK_LBUTTON
                CALL Input.Mouse.KeyState
                CP   Input.Mouse.SVK_LBUTTON
                RET

; Input_Release — ОТПУСКАНИЕ ЗАЩИТЫ: глобальный ПКМ (AltGr или правая кнопка).
; Та же active-LOW семантика, что у ЛКМ.
Input_Release:  LD   A, (Input_KAlt)
                OR   A
                RET  NZ
                LD   A, Input.Mouse.SVK_RBUTTON
                CALL Input.Mouse.KeyState
                CP   Input.Mouse.SVK_RBUTTON
                RET

; Позиция мыши (обновляется в Input_Scan) — логические 0…639 / 0…479.
Input_MouseX:   LD   HL, (Input.Mouse.PositionX) : RET
Input_MouseY:   LD   HL, (Input.Mouse.PositionY) : RET

; ----------------------------------------------------------------------------
; Input_Poll — собрать InputState за кадр (вызывается из главного цикла).
; ----------------------------------------------------------------------------
Input_Poll:
                XOR  A
                LD   (InputAnyPressed), A
                CALL Input_Scan
                XOR  A
                LD   (InputState), A

                ; Python будит demo по ЛКМ и кнопке джойстика. Старший ниббл
                ; Kempston — B/C/A/START; направления в младшем ниббле не
                ; заменяют JOYBUTTONDOWN. ПКМ также не будит: он принадлежит
                ; игровому действию Force и в Python явно исключён.
                LD   A, Input.Mouse.SVK_LBUTTON
                CALL Input.Mouse.KeyState
                CP   Input.Mouse.SVK_LBUTTON
                JR   NZ, .wake
                IN   A, (#1F)
                AND  %11110000
                OR   A
                JR   Z, .wakeDone
.wake:          LD   A, 1
                LD   (InputAnyPressed), A
.wakeDone:

                CALL Input_Left
                LD   C, INPUT_LEFT
                CALL .set
                CALL Input_Right
                LD   C, INPUT_RIGHT
                CALL .set
                CALL Input_Up
                LD   C, INPUT_UP
                CALL .set
                CALL Input_Down
                LD   C, INPUT_DOWN
                CALL .set
                CALL Input_Fire
                LD   C, INPUT_FIRE
                CALL .set
                CALL Input_Release
                LD   C, INPUT_RELEASE
                CALL .set
                RET

; Z от предыдущего опроса = не активно; C = бит. «LD C, n» флаги не портит,
; поэтому результат опроса доходит сюда целым.
.set:           RET  Z
                LD   A, (InputState)
                OR   C
                LD   (InputState), A
                RET
