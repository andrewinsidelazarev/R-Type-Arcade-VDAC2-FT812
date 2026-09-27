; ============================================================================
; Resident Python/C -> FT812 fragment bridge (transport only; no render hook).
;
; This module is the bank boundary, not a renderer.  It neither starts nor
; closes a display list.  A READY fragment is inserted byte-for-byte into the
; command stream which the caller has already opened with FT_CMD_Start and
; FT_DL_Start.
;
; Required resident services supplied by main.asm before this module:
;   Memory.GetPage2 / SetPage2, Memory.GetPage3 / SetPage3
;   FT.Coprocessor.FlushChunk, RTypeFT_CmdWritePageDMA
;   generated_python_stack.asm constants and RTypePyStackFault
;
; The module is assembled into the permanently mapped page #00 window
; #0500..#0FFF in slot0.  The #0400..#04FF hardware FMap window is deliberately
; kept below it, and the coordinate tables start at #1000.  Page #F0 is
; executable only in slot2; queue pages #ED/#EE are visible only through
; slot3; the legacy FT staging window is physical page #06 in slot2.
; ============================================================================

RTYPE_PYFT_C_PAGE                 EQU #F0
RTYPE_PYFT_QUEUE_PAGE_A           EQU #ED
RTYPE_PYFT_QUEUE_PAGE_B           EQU #EE
RTYPE_PYFT_STAGING_PAGE           EQU #06

; pyz80_ft812.h ABI, format 3.  The host-side bridge check compares these
; values with the C header and fails closed if either side changes.
RTYPE_PYFTQ_MAGIC                 EQU #4651
RTYPE_PYFTQ_FORMAT                EQU 3
RTYPE_PYFTQ_HEADER_BYTES          EQU 16
RTYPE_PYFTQ_VMA                   EQU #C000
RTYPE_PYFTQ_PAYLOAD_VMA           EQU #C010
RTYPE_PYFTQ_CAPACITY_WORDS        EQU #0FFC
RTYPE_PYFTQ_PAYLOAD_MAX           EQU #3FF0
RTYPE_PYFTQ_DL_WORD_LIMIT         EQU #0800

RTYPE_PYFTQ_OFF_MAGIC             EQU 0
RTYPE_PYFTQ_OFF_FORMAT            EQU 2
RTYPE_PYFTQ_OFF_PAGE              EQU 3
RTYPE_PYFTQ_OFF_SEQUENCE          EQU 4
RTYPE_PYFTQ_OFF_COUNT             EQU 6
RTYPE_PYFTQ_OFF_PAYLOAD           EQU 8
RTYPE_PYFTQ_OFF_DL_WORDS          EQU 10
RTYPE_PYFTQ_OFF_STATE             EQU 12
RTYPE_PYFTQ_OFF_OVERFLOW          EQU 13
RTYPE_PYFTQ_OFF_KIND              EQU 14
RTYPE_PYFTQ_OFF_RESERVED          EQU 15

RTYPE_PYFTQ_FREE                  EQU 0
RTYPE_PYFTQ_BUILDING              EQU 1
RTYPE_PYFTQ_READY                 EQU 2
RTYPE_PYFTQ_CONSUMING             EQU 3
RTYPE_PYFTQ_KIND_FULL             EQU 0
RTYPE_PYFTQ_KIND_FRAGMENT         EQU 1

RTYPE_PYFTBR_OK                   EQU 0
RTYPE_PYFTBR_IDLE                 EQU 1
RTYPE_PYFTBR_BUSY                 EQU 2
RTYPE_PYFTBR_BAD_PAGE             EQU 3
RTYPE_PYFTBR_BAD_TARGET           EQU 4
RTYPE_PYFTBR_BAD_HEADER           EQU 5
RTYPE_PYFTBR_STAGING_DMA          EQU 6
RTYPE_PYFTBR_QUEUE_DMA            EQU 7
RTYPE_PYFTBR_POSTCLAIM            EQU 8
RTYPE_PYFTBR_STACK                EQU 9
RTYPE_PYFTBR_CANARY               EQU 10
RTYPE_PYFTBR_IX                   EQU 11

RTypePyFTFragmentBridge_Start:

; ---------------------------------------------------------------------------
; RTypePyFTFragment_CallC0 -- generic __sdcccall(0) bank trampoline.
;
; In:
;   A  = queue physical page (#ED or #EE), mapped in slot3 for the C call
;   HL = arbitrary C entry in #8000..#BFFF on physical page #F0
;   SP = ordinary sdcccall(0) layout prepared by the caller:
;          [return-to-caller][arg0][arg1]...
;
; The trampoline replaces only the first return word with its resident gate
; and tail-jumps through HL.  Therefore the C target sees the gate at SP+0 and
; its first argument at SP+2 exactly as a direct sdcccall(0) call requires.
; The target's RET reaches the gate; the original return word and both MMU
; pages are restored before this routine returns.  Argument cleanup remains
; the caller's responsibility.  No producer name or signature is assumed.
;
; Out:
;   CF=0: transport succeeded, C scalar return remains in DE:HL
;   CF=1: bridge contract fault, A=RTYPE_PYFTBR_*
; Preserves IX and restores SP/page2/page3.  Other C-volatile registers are
; deliberately not promised.  Calls are non-reentrant; nested entry gets BUSY.
; ---------------------------------------------------------------------------
RTypePyFTFragment_CallC0:
                LD   C, A
                CP   RTYPE_PYFT_QUEUE_PAGE_A
                JR   Z, .pageOK
                CP   RTYPE_PYFT_QUEUE_PAGE_B
                JR   Z, .pageOK
                LD   A, RTYPE_PYFTBR_BAD_PAGE
                SCF
                RET
.pageOK:       LD   A, H
                AND  #C0
                CP   #80                          ; only slot2 is callable
                JR   Z, .targetOK
                LD   A, RTYPE_PYFTBR_BAD_TARGET
                SCF
                RET
.targetOK:     LD   A, (RTypePyFTFragmentBusy)
                OR   A
                JR   Z, .lock
                LD   A, RTYPE_PYFTBR_BUSY
                SCF
                RET
.lock:         LD   A, 1
                LD   (RTypePyFTFragmentBusy), A
                XOR  A
                LD   (RTypePyFTFragmentLastStatus), A
                LD   A, C
                LD   (RTypePyFTFragmentQueuePage), A
                LD   (RTypePyFTFragmentTarget), HL
                LD   (RTypePyFTFragmentSavedIX), IX

                LD   HL, 0
                ADD  HL, SP
                LD   (RTypePyFTFragmentSavedSP), HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypePyFTFragmentSavedReturn), DE

                CALL Memory.GetPage2
                LD   (RTypePyFTFragmentSavedPage2), A
                CALL Memory.GetPage3
                LD   (RTypePyFTFragmentSavedPage3), A
                LD   A, RTYPE_PYFT_C_PAGE
                CALL Memory.SetPage2
                LD   A, (RTypePyFTFragmentQueuePage)
                CALL Memory.SetPage3

                ; No CALL wrapper here: gate is the target's real return word.
                LD   HL, (RTypePyFTFragmentSavedSP)
                LD   DE, RTypePyFTFragment_ReturnGate
                LD   (HL), E
                INC  HL
                LD   (HL), D
                LD   HL, (RTypePyFTFragmentTarget)
                JP   (HL)

RTypePyFTFragment_ReturnGate:
                ; Preserve every SDCC scalar return register before diagnostics.
                LD   (RTypePyFTFragmentResultHL), HL
                LD   (RTypePyFTFragmentResultDE), DE

                ; A callee-cleanup convention would land at a different SP and
                ; is rejected.  Recover the caller-clean layout before any CALL.
                LD   HL, 0
                ADD  HL, SP
                EX   DE, HL
                LD   HL, (RTypePyFTFragmentSavedSP)
                INC  HL
                INC  HL
                OR   A
                SBC  HL, DE
                JR   Z, .spRecovered
                LD   A, 2
                LD   (RTypePyStackFault), A
                LD   A, RTYPE_PYFTBR_STACK
                LD   (RTypePyFTFragmentLastStatus), A
                LD   HL, (RTypePyFTFragmentSavedSP)
                INC  HL
                INC  HL
                LD   SP, HL
.spRecovered:
                LD   A, (RTypePyFTFragmentSavedPage3)
                CALL Memory.SetPage3
                LD   A, (RTypePyFTFragmentSavedPage2)
                CALL Memory.SetPage2

                PUSH IX
                POP  HL
                LD   DE, (RTypePyFTFragmentSavedIX)
                OR   A
                SBC  HL, DE
                JR   Z, .ixOK
                LD   A, (RTypePyFTFragmentLastStatus)
                OR   A
                JR   NZ, .ixOK
                LD   A, RTYPE_PYFTBR_IX
                LD   (RTypePyFTFragmentLastStatus), A
.ixOK:         CALL RTypePyFTFragment_CheckCanary
                JR   NC, .canaryOK
                LD   A, 1
                LD   (RTypePyStackFault), A
                LD   A, (RTypePyFTFragmentLastStatus)
                OR   A
                JR   NZ, .canaryOK
                LD   A, RTYPE_PYFTBR_CANARY
                LD   (RTypePyFTFragmentLastStatus), A
.canaryOK:
                ; Restore the original wrapper return at its exact entry slot.
                LD   HL, (RTypePyFTFragmentSavedSP)
                LD   DE, (RTypePyFTFragmentSavedReturn)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                LD   SP, (RTypePyFTFragmentSavedSP)
                LD   IX, (RTypePyFTFragmentSavedIX)
                XOR  A
                LD   (RTypePyFTFragmentBusy), A
                LD   HL, (RTypePyFTFragmentResultHL)
                LD   DE, (RTypePyFTFragmentResultDE)
                LD   A, (RTypePyFTFragmentLastStatus)
                OR   A
                RET  Z                             ; OR cleared carry
                SCF
                RET

; ---------------------------------------------------------------------------
; RTypePyFTFragment_ConsumeReady
;
; In:  A = #ED or #EE
; Out: CF=0/A=OK after READY->CONSUMING->FREE, or CF=0/A=IDLE when the
;      selected page is not READY.  CF=1/A=RTYPE_PYFTBR_* is fail-closed.
;
; Only format-3 FRAGMENT pages are accepted.  Header validation happens before
; the atomic CONSUMING byte store.  Invalid READY headers remain READY for
; inspection.  A transport fault after the claim deliberately leaves the page
; CONSUMING: retrying a possibly partial FT FIFO transfer would duplicate the
; prefix and corrupt command order.
;
; Existing bytes in physical staging page #06 are flushed first.  Then the
; payload at physical page:A/#0010 is passed directly to the real FIFO-aware
; RTypeFT_CmdWritePageDMA routine.  It performs aligned <=#0FFC chunks; this
; bridge never parses, sorts, pads or inserts lifecycle words.
; ---------------------------------------------------------------------------
RTypePyFTFragment_ConsumeReady:
                LD   C, A
                CP   RTYPE_PYFT_QUEUE_PAGE_A
                JR   Z, .pageOK
                CP   RTYPE_PYFT_QUEUE_PAGE_B
                JR   Z, .pageOK
                LD   A, RTYPE_PYFTBR_BAD_PAGE
                SCF
                RET
.pageOK:       LD   A, (RTypePyFTFragmentBusy)
                OR   A
                JR   Z, .lock
                LD   A, RTYPE_PYFTBR_BUSY
                SCF
                RET
.lock:         LD   A, 1
                LD   (RTypePyFTFragmentBusy), A
                XOR  A
                LD   (RTypePyFTFragmentLastStatus), A
                LD   (RTypePyFTFragmentReturnCarry), A
                LD   A, C
                LD   (RTypePyFTFragmentQueuePage), A
                LD   (RTypePyFTFragmentSavedIX), IX
                LD   HL, 0
                ADD  HL, SP
                LD   (RTypePyFTFragmentSavedSP), HL
                CALL Memory.GetPage2
                LD   (RTypePyFTFragmentSavedPage2), A
                CALL Memory.GetPage3
                LD   (RTypePyFTFragmentSavedPage3), A

                LD   A, (RTypePyFTFragmentQueuePage)
                CALL Memory.SetPage3
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_STATE)
                CP   RTYPE_PYFTQ_READY
                JR   Z, .validate
                LD   A, RTYPE_PYFTBR_IDLE
                LD   (RTypePyFTFragmentLastStatus), A
                JP   .restore

.validate:     LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_MAGIC)
                LD   DE, RTYPE_PYFTQ_MAGIC
                OR   A
                SBC  HL, DE
                JP   NZ, .badHeader
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_FORMAT)
                CP   RTYPE_PYFTQ_FORMAT
                JP   NZ, .badHeader
                LD   A, (RTypePyFTFragmentQueuePage)
                LD   B, A
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_PAGE)
                CP   B
                JP   NZ, .badHeader
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_OVERFLOW)
                OR   A
                JP   NZ, .badHeader
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_KIND)
                CP   RTYPE_PYFTQ_KIND_FRAGMENT
                JP   NZ, .badHeader
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_RESERVED)
                OR   A
                JP   NZ, .badHeader

                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_COUNT)
                LD   DE, RTYPE_PYFTQ_CAPACITY_WORDS + 1
                OR   A
                SBC  HL, DE
                JP   NC, .badHeader               ; count > capacity
                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_COUNT)
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_PAYLOAD)
                OR   A
                SBC  HL, DE
                JP   NZ, .badHeader               ; payload must be count * 4
                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_PAYLOAD)
                LD   DE, RTYPE_PYFTQ_PAYLOAD_MAX + 1
                OR   A
                SBC  HL, DE
                JP   NC, .badHeader
                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_DL_WORDS)
                LD   DE, RTYPE_PYFTQ_DL_WORD_LIMIT + 1
                OR   A
                SBC  HL, DE
                JP   NC, .badHeader

                ; Re-read the publication byte immediately before the claim.
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_STATE)
                CP   RTYPE_PYFTQ_READY
                JP   NZ, .badHeader
                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_SEQUENCE)
                LD   (RTypePyFTFragmentLastSequence), HL
                LD   HL, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_PAYLOAD)
                LD   (RTypePyFTFragmentPayloadBytes), HL
                LD   A, RTYPE_PYFTQ_CONSUMING
                LD   (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_STATE), A

                ; Restore unrelated slot3 before touching the legacy stream.
                LD   A, (RTypePyFTFragmentSavedPage3)
                CALL Memory.SetPage3
                LD   A, RTYPE_PYFT_STAGING_PAGE
                CALL Memory.SetPage2
                CALL FT.Coprocessor.FlushChunk
                JR   C, .stagingFault

                LD   BC, (RTypePyFTFragmentPayloadBytes)
                LD   A, B
                OR   C
                JR   Z, .publishFree
                LD   A, (RTypePyFTFragmentQueuePage)
                LD   HL, RTYPE_PYFTQ_PAYLOAD_VMA
                CALL RTypeFT_CmdWritePageDMA
                JR   C, .queueFault

.publishFree:  LD   A, (RTypePyFTFragmentQueuePage)
                CALL Memory.SetPage3
                LD   A, (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_STATE)
                CP   RTYPE_PYFTQ_CONSUMING
                JR   NZ, .postClaimFault
                XOR  A                             ; FREE is the final store
                LD   (RTYPE_PYFTQ_VMA + RTYPE_PYFTQ_OFF_STATE), A
                LD   (RTypePyFTFragmentLastStatus), A
                JR   .restore

.badHeader:    LD   A, RTYPE_PYFTBR_BAD_HEADER
                JR   .preClaimFault
.stagingFault: LD   A, RTYPE_PYFTBR_STAGING_DMA
                JR   .claimedFault
.queueFault:   LD   A, RTYPE_PYFTBR_QUEUE_DMA
                JR   .claimedFault
.postClaimFault:
                LD   A, RTYPE_PYFTBR_POSTCLAIM
.claimedFault: ; State intentionally remains CONSUMING after a possible prefix.
.preClaimFault:LD   (RTypePyFTFragmentLastStatus), A
                LD   A, 1
                LD   (RTypePyFTFragmentReturnCarry), A

.restore:      ; Check/recover SP before page-restoration CALLs.
                LD   HL, 0
                ADD  HL, SP
                EX   DE, HL
                LD   HL, (RTypePyFTFragmentSavedSP)
                OR   A
                SBC  HL, DE
                JR   Z, .spOK
                LD   A, 2
                LD   (RTypePyStackFault), A
                LD   A, RTYPE_PYFTBR_STACK
                LD   (RTypePyFTFragmentLastStatus), A
                LD   A, 1
                LD   (RTypePyFTFragmentReturnCarry), A
                LD   SP, (RTypePyFTFragmentSavedSP)
.spOK:         LD   A, (RTypePyFTFragmentSavedPage3)
                CALL Memory.SetPage3
                LD   A, (RTypePyFTFragmentSavedPage2)
                CALL Memory.SetPage2

                PUSH IX
                POP  HL
                LD   DE, (RTypePyFTFragmentSavedIX)
                OR   A
                SBC  HL, DE
                JR   Z, .ixOK
                LD   A, RTYPE_PYFTBR_IX
                LD   (RTypePyFTFragmentLastStatus), A
                LD   A, 1
                LD   (RTypePyFTFragmentReturnCarry), A
.ixOK:         CALL RTypePyFTFragment_CheckCanary
                JR   NC, .canaryOK
                LD   A, 1
                LD   (RTypePyStackFault), A
                LD   A, RTYPE_PYFTBR_CANARY
                LD   (RTypePyFTFragmentLastStatus), A
                LD   A, 1
                LD   (RTypePyFTFragmentReturnCarry), A
.canaryOK:     LD   IX, (RTypePyFTFragmentSavedIX)
                XOR  A
                LD   (RTypePyFTFragmentBusy), A
                LD   A, (RTypePyFTFragmentReturnCarry)
                OR   A
                LD   A, (RTypePyFTFragmentLastStatus)
                RET  Z                             ; carry cleared by OR
                SCF
                RET

; Carry-only canary check usable at either bridge exit.  It intentionally does
; not CALL the main-loop checker, whose SP contract is fixed at StackTop-2.
RTypePyFTFragment_CheckCanary:
                LD   HL, RTYPE_PY_Z80_STACK_GUARD_BASE
                LD   B, RTYPE_PY_Z80_STACK_GUARD_BYTES
                LD   A, RTYPE_PY_Z80_STACK_CANARY
.loop:         CP   (HL)
                JR   NZ, .fault
                INC  HL
                DJNZ .loop
                OR   A
                RET
.fault:        SCF
                RET

; Shared only while Busy=1.  The guard explicitly rejects nested calls, so no
; return address or MMU snapshot can be overwritten by a second bridge entry.
RTypePyFTFragmentBusy:             DEFB 0
RTypePyFTFragmentLastStatus:       DEFB 0
RTypePyFTFragmentReturnCarry:      DEFB 0
RTypePyFTFragmentQueuePage:        DEFB 0
RTypePyFTFragmentSavedPage2:       DEFB 0
RTypePyFTFragmentSavedPage3:       DEFB 0
RTypePyFTFragmentSavedSP:          DEFW 0
RTypePyFTFragmentSavedReturn:      DEFW 0
RTypePyFTFragmentSavedIX:          DEFW 0
RTypePyFTFragmentTarget:           DEFW 0
RTypePyFTFragmentResultHL:         DEFW 0
RTypePyFTFragmentResultDE:         DEFW 0
RTypePyFTFragmentPayloadBytes:     DEFW 0
RTypePyFTFragmentLastSequence:     DEFW 0

RTypePyFTFragmentBridge_End:
                ASSERT RTypePyFTFragmentBridge_Start = #0500
                ASSERT RTypePyFTFragmentBridge_End <= #1000
