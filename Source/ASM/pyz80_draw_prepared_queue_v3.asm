; ============================================================================
; Prepared-frame v3 atomic FT812 queue builder (prototype, not in the SPG).
;
; Custom register ABI:
;   HL -> packed 12-byte PyZ80DrawPreparedV3FastQueueParams
;   A  <- 0 after exactly one final READY store, 1 if queue was not FREE
;
; Entry is legal only after the fast producer has completed every dynamic
; record/append/RAM_DL/raster check.  The eight-byte append stream directory
; is immutable and prevalidated at level-pack load.  Queue payload is private
; while header.state=BUILDING; state=READY is the sole publication store.
; IX/IY are preserved.  Static counters make the prototype non-reentrant.
; ============================================================================

PYZ80_V3_Q_FREE                  EQU 0
PYZ80_V3_Q_BUILDING              EQU 1
PYZ80_V3_Q_READY                 EQU 2
PYZ80_V3_Q_FRAGMENT              EQU 1

PYZ80_V3_QP_RECORDS              EQU 0
PYZ80_V3_QP_APPEND_STREAM        EQU 2
PYZ80_V3_QP_QUEUE                EQU 4
PYZ80_V3_QP_PREFLIGHT            EQU 6
PYZ80_V3_QP_RECORD_COUNT         EQU 8
PYZ80_V3_QP_SEQUENCE             EQU 9
PYZ80_V3_QP_STATUS               EQU 11

PYZ80_V3_QFP_TARGET              EQU 2
PYZ80_V3_QFP_RECORD_COUNT        EQU 6
PYZ80_V3_QFP_OUT_FRAGMENT        EQU 16
PYZ80_V3_QFP_STATUS              EQU 22

PYZ80_V3_QH_SEQUENCE             EQU 4
PYZ80_V3_QH_COUNT                EQU 6
PYZ80_V3_QH_PAYLOAD              EQU 8
PYZ80_V3_QH_DL_WORDS             EQU 10
PYZ80_V3_QH_STATE                EQU 12
PYZ80_V3_QH_OVERFLOW             EQU 13
PYZ80_V3_QH_KIND                 EQU 14
PYZ80_V3_QH_WORDS                EQU 16

PyZ80DrawPreparedV3_ASMQueue_Start:

PyZ80DrawPreparedV3_ASMQueue:
                PUSH IX
                PUSH IY
                PUSH HL
                POP  IY

                ; Bind publication to the exact successful producer result and
                ; the same private tape.  Any mismatch fails before BUILDING.
                LD   L, (IY + PYZ80_V3_QP_PREFLIGHT)
                LD   H, (IY + PYZ80_V3_QP_PREFLIGHT + 1)
                LD   BC, PYZ80_V3_QFP_STATUS
                ADD  HL, BC
                LD   A, (HL)
                OR   A
                JP   NZ, .busy
                LD   L, (IY + PYZ80_V3_QP_PREFLIGHT)
                LD   H, (IY + PYZ80_V3_QP_PREFLIGHT + 1)
                LD   BC, PYZ80_V3_QFP_RECORD_COUNT
                ADD  HL, BC
                LD   A, (HL)
                LD   B, A
                LD   A, (IY + PYZ80_V3_QP_RECORD_COUNT)
                CP   B
                JP   NZ, .busy
                LD   L, (IY + PYZ80_V3_QP_PREFLIGHT)
                LD   H, (IY + PYZ80_V3_QP_PREFLIGHT + 1)
                LD   BC, PYZ80_V3_QFP_TARGET
                ADD  HL, BC
                LD   A, (HL)
                CP   (IY + PYZ80_V3_QP_RECORDS)
                JP   NZ, .busy
                INC  HL
                LD   A, (HL)
                CP   (IY + PYZ80_V3_QP_RECORDS + 1)
                JP   NZ, .busy

                ; Derive physical words from record_count; do not trust a
                ; second caller-supplied length.
                LD   A, (IY + PYZ80_V3_QP_RECORD_COUNT)
                LD   L, A
                LD   H, 0
                LD   E, A
                LD   D, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   A, (IY + PYZ80_V3_QP_RECORD_COUNT)
                OR   A
                JR   Z, .physicalReady
                CP   129
                LD   BC, 13
                JR   C, .addPhysicalChunk
                LD   BC, 26
.addPhysicalChunk:
                ADD  HL, BC
.physicalReady:LD   (PyZ80DrawPreparedV3_QPhysicalWords), HL

                LD   L, (IY + PYZ80_V3_QP_QUEUE)
                LD   H, (IY + PYZ80_V3_QP_QUEUE + 1)
                PUSH HL
                POP  DE
                LD   BC, PYZ80_V3_QH_STATE
                ADD  HL, BC
                LD   A, (HL)
                OR   A
                JP   NZ, .busy

                ; Acquire BUILDING without publishing any payload prefix.
                LD   L, (IY + PYZ80_V3_QP_QUEUE)
                LD   H, (IY + PYZ80_V3_QP_QUEUE + 1)
                LD   BC, PYZ80_V3_QH_SEQUENCE
                ADD  HL, BC
                LD   A, (IY + PYZ80_V3_QP_SEQUENCE)
                LD   (HL), A
                INC  HL
                LD   A, (IY + PYZ80_V3_QP_SEQUENCE + 1)
                LD   (HL), A
                INC  HL
                XOR  A
                LD   B, 6
.clearHeader:  LD   (HL), A
                INC  HL
                DJNZ .clearHeader
                ; HL now points at state (offset 12).
                LD   (HL), PYZ80_V3_Q_BUILDING
                INC  HL
                LD   (HL), 0
                INC  HL
                LD   (HL), PYZ80_V3_Q_FRAGMENT

                LD   L, (IY + PYZ80_V3_QP_RECORDS)
                LD   H, (IY + PYZ80_V3_QP_RECORDS + 1)
                PUSH HL
                POP  IX
                LD   E, (IY + PYZ80_V3_QP_QUEUE)
                LD   D, (IY + PYZ80_V3_QP_QUEUE + 1)
                LD   HL, PYZ80_V3_QH_WORDS
                ADD  HL, DE
                EX   DE, HL
                LD   A, (IY + PYZ80_V3_QP_RECORD_COUNT)
                OR   A
                JP   Z, .publish
                LD   B, A
                XOR  A
                LD   (PyZ80DrawPreparedV3_QSecondCount), A
                LD   A, B
                CP   129
                JR   C, .oneChunk
                SUB  128
                LD   (PyZ80DrawPreparedV3_QSecondCount), A
                LD   A, 128
.oneChunk:     LD   (PyZ80DrawPreparedV3_QChunkRemaining), A

.chunk:        LD   HL, PyZ80DrawPreparedV3_QPrefix
                LD   BC, 40
                LDIR

.record:       ; VERTEX_TRANSLATE_X: signed uint16 << 1, masked to 17 bits.
                LD   L, (IX + 2)
                LD   H, (IX + 3)
                ADD  HL, HL
                LD   A, L
                LD   (DE), A
                INC  DE
                LD   A, H
                LD   (DE), A
                INC  DE
                LD   A, 0
                ADC  A, 0
                LD   (DE), A
                INC  DE
                LD   A, #2B
                LD   (DE), A
                INC  DE

                ; VERTEX_TRANSLATE_Y.
                LD   L, (IX + 4)
                LD   H, (IX + 5)
                ADD  HL, HL
                LD   A, L
                LD   (DE), A
                INC  DE
                LD   A, H
                LD   (DE), A
                INC  DE
                LD   A, 0
                ADC  A, 0
                LD   (DE), A
                INC  DE
                LD   A, #2C
                LD   (DE), A
                INC  DE

                ; CMD_APPEND word.
                LD   A, #1E
                LD   (DE), A
                INC  DE
                LD   A, #FF
                LD   (DE), A
                INC  DE
                LD   (DE), A
                INC  DE
                LD   (DE), A
                INC  DE

                ; Direct 256-entry, 8-byte {address,size} stream directory.
                LD   A, (IX + 0)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   C, (IY + PYZ80_V3_QP_APPEND_STREAM)
                LD   B, (IY + PYZ80_V3_QP_APPEND_STREAM + 1)
                ADD  HL, BC
                LD   BC, 8
                LDIR
                LD   BC, 6
                ADD  IX, BC

                LD   A, (PyZ80DrawPreparedV3_QChunkRemaining)
                DEC  A
                LD   (PyZ80DrawPreparedV3_QChunkRemaining), A
                JR   NZ, .record

                LD   HL, PyZ80DrawPreparedV3_QSuffix
                LD   BC, 12
                LDIR
                LD   A, (PyZ80DrawPreparedV3_QSecondCount)
                OR   A
                JR   Z, .publish
                LD   (PyZ80DrawPreparedV3_QChunkRemaining), A
                XOR  A
                LD   (PyZ80DrawPreparedV3_QSecondCount), A
                JR   .chunk

.publish:      ; Header metadata first; READY is the unique final store.
                LD   L, (IY + PYZ80_V3_QP_QUEUE)
                LD   H, (IY + PYZ80_V3_QP_QUEUE + 1)
                LD   BC, PYZ80_V3_QH_COUNT
                ADD  HL, BC
                LD   BC, (PyZ80DrawPreparedV3_QPhysicalWords)
                LD   (HL), C
                INC  HL
                LD   (HL), B
                INC  HL
                ; payload_bytes = physical_words * 4.
                SLA  C
                RL   B
                SLA  C
                RL   B
                LD   (HL), C
                INC  HL
                LD   (HL), B
                INC  HL
                PUSH HL
                LD   L, (IY + PYZ80_V3_QP_PREFLIGHT)
                LD   H, (IY + PYZ80_V3_QP_PREFLIGHT + 1)
                LD   BC, PYZ80_V3_QFP_OUT_FRAGMENT
                ADD  HL, BC
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                POP  HL
                LD   A, C
                LD   (HL), A
                INC  HL
                LD   A, B
                LD   (HL), A
                INC  HL
                LD   (HL), PYZ80_V3_Q_READY
                XOR  A
                JR   .finish

.busy:         LD   A, 1
.finish:       LD   (IY + PYZ80_V3_QP_STATUS), A
                POP  IY
                POP  IX
                RET

PyZ80DrawPreparedV3_QSecondCount:    DB 0
PyZ80DrawPreparedV3_QChunkRemaining: DB 0
PyZ80DrawPreparedV3_QPhysicalWords:  DW 0

PyZ80DrawPreparedV3_QPrefix:
                DD #04FFFFFF, #150000A0, #16000000, #17000000
                DD #18000000, #190000A0, #1A000000, #08005830
                DD #27000003, #1F000001
PyZ80DrawPreparedV3_QSuffix:
                DD #2B000000, #2C000000, #21000000

PyZ80DrawPreparedV3_ASMQueue_End:
