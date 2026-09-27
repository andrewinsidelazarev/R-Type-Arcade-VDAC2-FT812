; ============================================================================
; Resident sdcccall(0) tail gate for the split Python draw C bundle.
;
; This file is deliberately not included by main.asm yet.  The placement
; checker assembles and measures it at #07A0, but the final-image/callback
; binding remains a fail-closed live blocker until the production linker and
; packer install both C banks and this resident gate together.
;
; Call path:
;   page #F1 C proxy (JP, no CALL) -> this gate -> page #F2 entry at #8000
;
; At entry SP is the original __sdcccall(0) layout:
;   [return-to-page-F1][queue][records][count][remaining_dl_words]
; The gate replaces only the return word and tail-jumps.  Therefore the page
; #F2 target observes the exact stack layout of a direct call.  Its RET enters
; the resident return gate, which restores page #F1 and the original return.
;
; Required existing resident services:
;   Memory.GetPage2 / Memory.SetPage2
; ============================================================================

RTYPE_PYDRAW_BANK0_PAGE           EQU #F1
RTYPE_PYDRAW_BANK1_PAGE           EQU #F2
RTYPE_PYDRAW_BANK1_ENTRY          EQU #8000

RTypePyDrawBankGate_Start:

RTypePyDrawBank_CallF2C0:
                LD   A, (RTypePyDrawBankBusy)
                OR   A
                JR   Z, .lock
                ; Fail closed for a nested entry.  uint8_t is returned in L;
                ; DE:HL=0 also covers wider scalar interpretations.
                LD   DE, 0
                LD   HL, 0
                RET
.lock:          LD   A, 1
                LD   (RTypePyDrawBankBusy), A
                LD   (RTypePyDrawBankSavedIX), IX
                LD   (RTypePyDrawBankSavedIY), IY

                LD   HL, 0
                ADD  HL, SP
                LD   (RTypePyDrawBankSavedSP), HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypePyDrawBankSavedReturn), DE

                CALL Memory.GetPage2
                LD   (RTypePyDrawBankSavedPage2), A
                CP   RTYPE_PYDRAW_BANK0_PAGE
                JR   Z, .callerPageOK
                LD   IX, (RTypePyDrawBankSavedIX)
                LD   IY, (RTypePyDrawBankSavedIY)
                XOR  A
                LD   (RTypePyDrawBankBusy), A
                LD   DE, 0
                LD   HL, 0
                RET
.callerPageOK:
                LD   A, RTYPE_PYDRAW_BANK1_PAGE
                CALL Memory.SetPage2

                ; Do not add a wrapper CALL: the F1 target must see its first
                ; argument at SP+2, exactly like a direct __sdcccall(0) call.
                LD   HL, (RTypePyDrawBankSavedSP)
                LD   DE, RTypePyDrawBank_ReturnGate
                LD   (HL), E
                INC  HL
                LD   (HL), D
                JP   RTYPE_PYDRAW_BANK1_ENTRY

RTypePyDrawBank_ReturnGate:
                LD   (RTypePyDrawBankResultHL), HL
                LD   (RTypePyDrawBankResultDE), DE

                ; A caller-clean target returns with SP=entry_SP+2.  Any other
                ; value is rejected and normalized before resident CALLs.
                LD   HL, 0
                ADD  HL, SP
                EX   DE, HL
                LD   HL, (RTypePyDrawBankSavedSP)
                INC  HL
                INC  HL
                OR   A
                SBC  HL, DE
                JR   Z, .stackOK
                LD   HL, 0
                LD   (RTypePyDrawBankResultHL), HL
                LD   (RTypePyDrawBankResultDE), HL
                LD   HL, (RTypePyDrawBankSavedSP)
                INC  HL
                INC  HL
                LD   SP, HL
.stackOK:       LD   A, (RTypePyDrawBankSavedPage2)
                CALL Memory.SetPage2

                LD   HL, (RTypePyDrawBankSavedSP)
                LD   DE, (RTypePyDrawBankSavedReturn)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                LD   SP, (RTypePyDrawBankSavedSP)
                LD   IX, (RTypePyDrawBankSavedIX)
                LD   IY, (RTypePyDrawBankSavedIY)
                XOR  A
                LD   (RTypePyDrawBankBusy), A
                LD   HL, (RTypePyDrawBankResultHL)
                LD   DE, (RTypePyDrawBankResultDE)
                RET

RTypePyDrawBankBusy:              DB 0
RTypePyDrawBankSavedPage2:        DB 0
RTypePyDrawBankSavedSP:           DW 0
RTypePyDrawBankSavedReturn:       DW 0
RTypePyDrawBankSavedIX:           DW 0
RTypePyDrawBankSavedIY:           DW 0
RTypePyDrawBankResultHL:          DW 0
RTypePyDrawBankResultDE:          DW 0

RTypePyDrawBankGate_End:
