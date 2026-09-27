; Direct-RAM_DL v4 target prototype (not linked into the SPG).
;
; Custom ABI: HL -> packed PyZ80DrawRamDLV4FastPublishParams (14 bytes).
; It consumes only a READY immutable TS-RAM shadow, sends exactly one 8 KiB
; DMA_RAM_SPI request to FT812 RAM_DL, requests DLSWAP_FRAME, and retires the
; epoch only after both INT_SWAP and REG_DLSWAP==0 have been observed.

PYZ80_V4_SPI_DATA             EQU #57
PYZ80_V4_SPI_CTRL             EQU #77
PYZ80_V4_SPI_FT_OFF           EQU #03
PYZ80_V4_SPI_FT_ON            EQU #07

PYZ80_V4_DMASADDRL            EQU #1AAF
PYZ80_V4_DMASADDRH            EQU #1BAF
PYZ80_V4_DMASADDRX            EQU #1CAF
PYZ80_V4_DMALEN               EQU #26AF
PYZ80_V4_DMACTR               EQU #27AF
PYZ80_V4_DMASTATUS            EQU #27AF
PYZ80_V4_DMANUM               EQU #28AF
PYZ80_V4_DMA_WNR              EQU #80
PYZ80_V4_DMA_RAM_SPI          EQU #82

PYZ80_V4_REG_DLSWAP           EQU #2054
PYZ80_V4_REG_INT_FLAGS        EQU #20A8
PYZ80_V4_DLSWAP_FRAME         EQU 2
PYZ80_V4_INT_SWAP             EQU 1

PYZ80_V4_STATE_READY          EQU 2
PYZ80_V4_STATE_DMA            EQU 3
PYZ80_V4_STATE_SWAP_PENDING   EQU 4
PYZ80_V4_STATE_ACTIVE         EQU 7

PYZ80_V4_OK                   EQU 0
PYZ80_V4_INVALID_INPUT        EQU 1
PYZ80_V4_CAPACITY             EQU 5
PYZ80_V4_STALE_EPOCH          EQU 7
PYZ80_V4_BUSY                 EQU 9
PYZ80_V4_FENCE                EQU 10

; params offsets
PYZ80_V4_P_STATE_PTR          EQU 0
PYZ80_V4_P_RETIRED_PTR        EQU 2
PYZ80_V4_P_USED_WORDS         EQU 4
PYZ80_V4_P_PUBLISH_EPOCH      EQU 6
PYZ80_V4_P_SOURCE_OFFSET      EQU 8
PYZ80_V4_P_POLL_LIMIT         EQU 10
PYZ80_V4_P_SOURCE_PAGE        EQU 12
PYZ80_V4_P_STATUS             EQU 13

PyZ80DrawRamDLV4_ASM_Start:
PyZ80DrawRamDLV4_ASMPublish:
                PUSH IX
                PUSH IY
                PUSH HL
                POP  IX

                ; READY must be the exact producer publication state.
                LD   L, (IX + PYZ80_V4_P_STATE_PTR)
                LD   H, (IX + PYZ80_V4_P_STATE_PTR + 1)
                LD   A, H
                OR   L
                JP   Z, .invalid
                LD   A, (HL)
                CP   PYZ80_V4_STATE_READY
                JP   NZ, .busy

                ; 1 <= used_words < 2048.  DMA still copies the deterministic
                ; full 8 KiB shadow; this count certifies RAM_DL semantics.
                LD   E, (IX + PYZ80_V4_P_USED_WORDS)
                LD   D, (IX + PYZ80_V4_P_USED_WORDS + 1)
                LD   A, D
                OR   E
                JP   Z, .invalid
                LD   A, D
                CP   8
                JP   NC, .capacity

                ; Only the two non-overlapping half-page offsets are accepted.
                LD   E, (IX + PYZ80_V4_P_SOURCE_OFFSET)
                LD   D, (IX + PYZ80_V4_P_SOURCE_OFFSET + 1)
                LD   A, E
                OR   A
                JP   NZ, .invalid
                LD   A, D
                OR   A
                JR   Z, .sourceOK
                CP   #20
                JP   NZ, .invalid
.sourceOK:
                LD   E, (IX + PYZ80_V4_P_PUBLISH_EPOCH)
                LD   D, (IX + PYZ80_V4_P_PUBLISH_EPOCH + 1)
                LD   A, D
                OR   E
                JP   Z, .stale
                LD   L, (IX + PYZ80_V4_P_RETIRED_PTR)
                LD   H, (IX + PYZ80_V4_P_RETIRED_PTR + 1)
                LD   A, H
                OR   L
                JP   Z, .invalid
                LD   A, (HL)
                CP   E
                JR   NZ, .epochFresh
                INC  HL
                LD   A, (HL)
                CP   D
                JP   Z, .stale
.epochFresh:
                LD   L, (IX + PYZ80_V4_P_POLL_LIMIT)
                LD   H, (IX + PYZ80_V4_P_POLL_LIMIT + 1)
                LD   A, H
                OR   L
                JP   Z, .invalid

                ; A pending previous swap makes RAM_DL unavailable.
                LD   DE, PYZ80_V4_REG_DLSWAP
                CALL .readReg8
                AND  3
                JP   NZ, .busy

                ; Consumer ownership begins only after every fail-fast check.
                LD   L, (IX + PYZ80_V4_P_STATE_PTR)
                LD   H, (IX + PYZ80_V4_P_STATE_PTR + 1)
                LD   (HL), PYZ80_V4_STATE_DMA

                ; FT812 memory-write transaction at RAM_DL = #300000.
                LD   A, PYZ80_V4_SPI_FT_ON
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A
                LD   C, PYZ80_V4_SPI_DATA
                LD   A, #B0
                OUT  (C), A
                XOR  A
                OUT  (C), A
                OUT  (C), A

                ; One DMACTR start: 16 bursts * 512 bytes = one full shadow.
                LD   A, (IX + PYZ80_V4_P_SOURCE_OFFSET)
                LD   BC, PYZ80_V4_DMASADDRL
                OUT  (C), A
                LD   A, (IX + PYZ80_V4_P_SOURCE_OFFSET + 1)
                AND  #3F
                LD   BC, PYZ80_V4_DMASADDRH
                OUT  (C), A
                LD   A, (IX + PYZ80_V4_P_SOURCE_PAGE)
                LD   BC, PYZ80_V4_DMASADDRX
                OUT  (C), A
                LD   A, #FF
                LD   BC, PYZ80_V4_DMALEN
                OUT  (C), A
                LD   A, 15
                LD   BC, PYZ80_V4_DMANUM
                OUT  (C), A
                LD   A, PYZ80_V4_DMA_RAM_SPI
                LD   BC, PYZ80_V4_DMACTR
                OUT  (C), A

                LD   L, (IX + PYZ80_V4_P_POLL_LIMIT)
                LD   H, (IX + PYZ80_V4_P_POLL_LIMIT + 1)
.waitDMA:       LD   BC, PYZ80_V4_DMASTATUS
                IN   A, (C)
                AND  PYZ80_V4_DMA_WNR
                JR   Z, .dmaDone
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .waitDMA
                LD   A, PYZ80_V4_SPI_FT_OFF
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A
                JP   .fence

.dmaDone:       LD   A, PYZ80_V4_SPI_FT_OFF
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A

                ; Direct register write: REG_DLSWAP <- DLSWAP_FRAME.
                LD   A, PYZ80_V4_SPI_FT_ON
                OUT  (C), A
                LD   C, PYZ80_V4_SPI_DATA
                LD   A, #B0
                OUT  (C), A
                LD   A, #20
                OUT  (C), A
                LD   A, #54
                OUT  (C), A
                LD   A, PYZ80_V4_DLSWAP_FRAME
                OUT  (C), A
                LD   A, PYZ80_V4_SPI_FT_OFF
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A

                LD   L, (IX + PYZ80_V4_P_STATE_PTR)
                LD   H, (IX + PYZ80_V4_P_STATE_PTR + 1)
                LD   (HL), PYZ80_V4_STATE_SWAP_PENDING

                ; Retirement requires the event and the level fence.  Each
                ; loop is bounded; timeout leaves SWAP_PENDING fail-closed.
                LD   L, (IX + PYZ80_V4_P_POLL_LIMIT)
                LD   H, (IX + PYZ80_V4_P_POLL_LIMIT + 1)
.waitInt:       LD   DE, PYZ80_V4_REG_INT_FLAGS
                CALL .readReg8
                AND  PYZ80_V4_INT_SWAP
                JR   NZ, .waitLevelSetup
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .waitInt
                JR   .fence

.waitLevelSetup:
                LD   L, (IX + PYZ80_V4_P_POLL_LIMIT)
                LD   H, (IX + PYZ80_V4_P_POLL_LIMIT + 1)
.waitLevel:     LD   DE, PYZ80_V4_REG_DLSWAP
                CALL .readReg8
                AND  3
                JR   Z, .retire
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .waitLevel
                JR   .fence

.retire:        LD   E, (IX + PYZ80_V4_P_PUBLISH_EPOCH)
                LD   D, (IX + PYZ80_V4_P_PUBLISH_EPOCH + 1)
                LD   L, (IX + PYZ80_V4_P_RETIRED_PTR)
                LD   H, (IX + PYZ80_V4_P_RETIRED_PTR + 1)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                LD   L, (IX + PYZ80_V4_P_STATE_PTR)
                LD   H, (IX + PYZ80_V4_P_STATE_PTR + 1)
                LD   (HL), PYZ80_V4_STATE_ACTIVE
                XOR  A
                JR   .return

.invalid:       LD   A, PYZ80_V4_INVALID_INPUT
                JR   .return
.capacity:      LD   A, PYZ80_V4_CAPACITY
                JR   .return
.stale:         LD   A, PYZ80_V4_STALE_EPOCH
                JR   .return
.busy:          LD   A, PYZ80_V4_BUSY
                JR   .return
.fence:         LD   A, PYZ80_V4_FENCE

.return:        LD   (IX + PYZ80_V4_P_STATUS), A
                POP  IY
                POP  IX
                RET

; DE = low 16 bits in RAM_REG page #30.  A = byte read.
.readReg8:      LD   A, PYZ80_V4_SPI_FT_ON
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A
                LD   C, PYZ80_V4_SPI_DATA
                LD   A, #30
                OUT  (C), A
                OUT  (C), D
                OUT  (C), E
                OUT  (C), E                 ; mandatory dummy write byte
                IN   A, (C)                 ; discard FT812 dummy response
                IN   A, (C)                 ; requested register byte
                PUSH AF
                LD   A, PYZ80_V4_SPI_FT_OFF
                LD   BC, PYZ80_V4_SPI_CTRL
                OUT  (C), A
                POP  AF
                RET

PyZ80DrawRamDLV4_ASM_End:
