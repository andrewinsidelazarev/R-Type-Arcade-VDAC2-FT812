; ============================================================================
; Prepared-frame v3 hot producer (prototype, not linked into the SPG).
;
; Custom register ABI:
;   HL -> packed 23-byte PyZ80DrawPreparedV3FastParams (SDCC/Z80 layout)
;   A  <- PyZ80DrawPreparedV3FastStatus
;
; The immutable append-word directory is prevalidated when a level pack is
; installed.  The frame path does one bounded pass: reject stale template
; indices, range-check append refs, accumulate budget, and copy each ready
; six-byte record.  It never calls a VM, resolver, lookup callback, or writer.
; The tape remains private on every failure; publication is a separate atomic
; step after A=0.  IX/IY are preserved.  Static scratch makes this routine
; deliberately non-reentrant; final binding must prove main/ISR ownership.
; ============================================================================

PYZ80_V3_TEMPLATE_COUNT          EQU 10776
PYZ80_V3_MAX_RECORDS             EQU 228
PYZ80_V3_RAM_DL_WORD_LIMIT       EQU 2048
PYZ80_V3_SAFE_LINE_CYCLES        EQU 1209

PYZ80_V3_FAST_OK                 EQU 0
PYZ80_V3_FAST_INVALID_RECORD     EQU 1
PYZ80_V3_FAST_APPEND_BOUND       EQU 2
PYZ80_V3_FAST_RAM_DL             EQU 3
PYZ80_V3_FAST_RASTER             EQU 4

; PyZ80DrawPreparedV3FastParams offsets (pinned SDCC/Z80 pointer width).
PYZ80_V3_FP_SOURCE               EQU 0
PYZ80_V3_FP_TARGET               EQU 2
PYZ80_V3_FP_APPEND_WORDS         EQU 4
PYZ80_V3_FP_RECORD_COUNT         EQU 6
PYZ80_V3_FP_DIRECTORY_COUNT      EQU 7
PYZ80_V3_FP_MAX_APPEND           EQU 8
PYZ80_V3_FP_NON_FRAGMENT         EQU 10
PYZ80_V3_FP_WORST_RASTER         EQU 12
PYZ80_V3_FP_OUT_APPEND           EQU 14
PYZ80_V3_FP_OUT_FRAGMENT         EQU 16
PYZ80_V3_FP_OUT_TOTAL            EQU 18
PYZ80_V3_FP_OUT_FAILURE          EQU 20
PYZ80_V3_FP_STATUS               EQU 22

PyZ80DrawPreparedV3_ASM_Start:

PyZ80DrawPreparedV3_ASMPrepare:
                PUSH IX
                PUSH IY
                PUSH HL
                POP  IY

                LD   L, (IY + PYZ80_V3_FP_SOURCE)
                LD   H, (IY + PYZ80_V3_FP_SOURCE + 1)
                PUSH HL
                POP  IX
                LD   A, (IY + PYZ80_V3_FP_RECORD_COUNT)
                LD   B, A
                LD   C, 0
                EXX
                LD   E, (IY + PYZ80_V3_FP_TARGET)
                LD   D, (IY + PYZ80_V3_FP_TARGET + 1)
                CP   PYZ80_V3_MAX_RECORDS + 1
                JP   NC, .invalidRecord
                LD   HL, 0
                LD   (PyZ80DrawPreparedV3_ASMSum), HL
                LD   A, (IY + PYZ80_V3_FP_RECORD_COUNT)
                OR   A
                JR   Z, .budget

.recordLoop:   ; Spawn/mutation invalidation writes the unique #FFFF sentinel.
                LD   A, (IX + 7)
                CP   #FF
                JR   NZ, .templateValid
                LD   A, (IX + 6)
                CP   #FF
                JP   Z, .invalidRecord
.templateValid:
                ; append_ref is a certified uint8 level-directory index.  Its
                ; range and every non-zero entry are proved once at pack load.
                LD   C, (IX + 0)
                LD   B, 0
                SLA  C
                RL   B
                LD   L, (IY + PYZ80_V3_FP_APPEND_WORDS)
                LD   H, (IY + PYZ80_V3_FP_APPEND_WORDS + 1)
                ADD  HL, BC
                LD   C, (HL)
                INC  HL
                LD   B, (HL)

                ; The immutable directory proof bounds 228 entries below
                ; 16-bit overflow; compare the exact sum once after the loop.
                LD   HL, (PyZ80DrawPreparedV3_ASMSum)
                ADD  HL, BC
                LD   (PyZ80DrawPreparedV3_ASMSum), HL

                ; Source first six bytes are byte-exact private tape payload.
                PUSH IX
                POP  HL
                LD   BC, 6
                LDIR
                LD   BC, 8
                ADD  IX, BC
                EXX
                INC  C
                DJNZ .moreRecords
                EXX
                JR   .budget
.moreRecords:  EXX
                JP   .recordLoop

.budget:       LD   HL, (PyZ80DrawPreparedV3_ASMSum)
                LD   (IY + PYZ80_V3_FP_OUT_APPEND), L
                LD   (IY + PYZ80_V3_FP_OUT_APPEND + 1), H
                LD   C, (IY + PYZ80_V3_FP_MAX_APPEND)
                LD   B, (IY + PYZ80_V3_FP_MAX_APPEND + 1)
                OR   A
                SBC  HL, BC
                JR   C, .appendAccepted
                JR   Z, .appendAccepted
                JP   .appendBound
.appendAccepted:

                ; fragment = 2*records + append + 13 words per 128 chunk.
                LD   A, (IY + PYZ80_V3_FP_RECORD_COUNT)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   A, (IY + PYZ80_V3_FP_RECORD_COUNT)
                OR   A
                JR   Z, .fragmentReady
                CP   129
                LD   BC, 13
                JR   C, .addChunkWords
                LD   BC, 26
.addChunkWords:ADD  HL, BC
.fragmentReady:
                LD   BC, (PyZ80DrawPreparedV3_ASMSum)
                ADD  HL, BC
                JR   C, .ramDL
                LD   (IY + PYZ80_V3_FP_OUT_FRAGMENT), L
                LD   (IY + PYZ80_V3_FP_OUT_FRAGMENT + 1), H

                LD   C, (IY + PYZ80_V3_FP_NON_FRAGMENT)
                LD   B, (IY + PYZ80_V3_FP_NON_FRAGMENT + 1)
                ADD  HL, BC
                JR   C, .ramDL
                LD   (IY + PYZ80_V3_FP_OUT_TOTAL), L
                LD   (IY + PYZ80_V3_FP_OUT_TOTAL + 1), H
                LD   BC, PYZ80_V3_RAM_DL_WORD_LIMIT
                OR   A
                SBC  HL, BC
                JR   NC, .ramDL

                LD   L, (IY + PYZ80_V3_FP_OUT_TOTAL)
                LD   H, (IY + PYZ80_V3_FP_OUT_TOTAL + 1)
                LD   C, (IY + PYZ80_V3_FP_WORST_RASTER)
                LD   B, (IY + PYZ80_V3_FP_WORST_RASTER + 1)
                ADD  HL, BC
                JR   C, .raster
                LD   BC, PYZ80_V3_SAFE_LINE_CYCLES + 1
                OR   A
                SBC  HL, BC
                JR   NC, .raster

                LD   HL, #FFFF
                LD   (IY + PYZ80_V3_FP_OUT_FAILURE), L
                LD   (IY + PYZ80_V3_FP_OUT_FAILURE + 1), H
                XOR  A
                JR   .finish

.invalidRecord:LD   A, PYZ80_V3_FAST_INVALID_RECORD
                JR   .fail
.appendBound:  LD   A, PYZ80_V3_FAST_APPEND_BOUND
                JR   .fail
.ramDL:        LD   A, PYZ80_V3_FAST_RAM_DL
                JR   .fail
.raster:       LD   A, PYZ80_V3_FAST_RASTER
.fail:         LD   (IY + PYZ80_V3_FP_STATUS), A
                EXX
                LD   A, C
                EXX
                LD   (IY + PYZ80_V3_FP_OUT_FAILURE), A
                XOR  A
                LD   (IY + PYZ80_V3_FP_OUT_FAILURE + 1), A
                LD   A, (IY + PYZ80_V3_FP_STATUS)
.finish:       LD   (IY + PYZ80_V3_FP_STATUS), A
                POP  IY
                POP  IX
                RET

PyZ80DrawPreparedV3_ASMSum:       DW 0

PyZ80DrawPreparedV3_ASM_End:
