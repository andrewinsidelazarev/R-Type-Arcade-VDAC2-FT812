; Сгенерировано rtype_python_translator.py.
; Translator owns the Z80 stack contract. RTYPE_RESIDENT_DATA_END=#4AFC;
; #4B00…#4B1F is a canary and usable stack
; may not descend below #4B20.

RTYPE_PY_Z80_STACK_GUARD_BASE  EQU #4B00
RTYPE_PY_Z80_STACK_GUARD_BYTES EQU 32
RTYPE_PY_Z80_STACK_BOTTOM      EQU #4B20
RTYPE_PY_Z80_STACK_TOP         EQU #4EFF
RTYPE_PY_Z80_STACK_BYTES       EQU RTYPE_PY_Z80_STACK_TOP - RTYPE_PY_Z80_STACK_BOTTOM + 1
RTYPE_PY_Z80_STACK_CANARY      EQU #A5
RTypePyStackFault              EQU #44B0
RTypePyStackPhase              EQU #44B1
RTypePyStackObservedSP         EQU #44B2
; Scheduler watchdog state is translator-owned too: it must never overlap
; sprite/palette scratch assembled by the handwritten FT812 backend.
RTypePySchedulerUpdateRemaining EQU #44B4
RTypePySchedulerInsertRemaining EQU #44B5
RTypePySchedulerRebuildIndex    EQU #44B6
RTypePySchedulerRepairCount     EQU #44B7
; Per-frame number of intermediate FT812 command-buffer flushes.  The
; translator owns this byte so the backend diagnostic cannot overlap a Python
; gameplay field when the generated layout changes.
RTypePyCommandFlushCount         EQU #44B8

                ASSERT StackTop = RTYPE_PY_Z80_STACK_TOP
                ASSERT #4AFC <= RTYPE_PY_Z80_STACK_GUARD_BASE

RTypePyStack_Init:
                LD   HL, RTYPE_PY_Z80_STACK_GUARD_BASE
                LD   B, RTYPE_PY_Z80_STACK_GUARD_BYTES
                LD   A, RTYPE_PY_Z80_STACK_CANARY
.fill:         LD   (HL), A
                INC  HL
                DJNZ .fill
                XOR  A
                LD   (RTypePyStackFault), A
                LD   (RTypePyStackPhase), A
                LD   (RTypePySchedulerUpdateRemaining), A
                LD   (RTypePySchedulerInsertRemaining), A
                LD   (RTypePySchedulerRebuildIndex), A
                LD   (RTypePySchedulerRepairCount), A
                LD   (RTypePyCommandFlushCount), A
                LD   HL, RTYPE_PY_Z80_STACK_TOP
                LD   (RTypePyStackObservedSP), HL
                RET

; Проверяется на каждой итерации MainLoop до следующего Python update.
; Carry=1 останавливает игру до того, как повреждение уйдёт в object pool.
RTypePyStack_Check:
                LD   HL, 0
                ADD  HL, SP
                LD   (RTypePyStackObservedSP), HL
                LD   DE, RTYPE_PY_Z80_STACK_TOP - 2
                OR   A
                SBC  HL, DE
                JR   NZ, .spFault
                LD   HL, RTYPE_PY_Z80_STACK_GUARD_BASE
                LD   B, RTYPE_PY_Z80_STACK_GUARD_BYTES
                LD   A, RTYPE_PY_Z80_STACK_CANARY
.check:        CP   (HL)
                JR   NZ, .fault
                INC  HL
                DJNZ .check
                OR   A
                RET
.fault:        LD   A, 1
                LD   (RTypePyStackFault), A
                SCF
                RET
.spFault:      LD   A, 2
                LD   (RTypePyStackFault), A
                SCF
                RET

; Stack уже недостоверен: никаких CALL/PUSH. Красный border делает fault
; видимым и процессор остаётся в локальном цикле вместо дальнейшей порчи RAM.
RTypePyStack_Fatal:
                DI
                LD   A, 2
                OUT  (#FE), A
.halt:         JR   .halt
