; Сгенерировано rtype_python_translator.py из M72SpriteAtlas.draw/cell.
; Ручное редактирование запрещено: следующая сборка перезапишет файл.
; Python перебирает cells конкретного descriptor. Поэтому target хранит cells,
; а не 8-КБ chunks. Все 1024 slots постоянны до смены world: immutable cell
; после первого TS DMA больше не гоняется заново через Z80 каждый второй кадр.

RTYPE_PY_SPRITE_CODE_COUNT       EQU 4096
RTYPE_PY_SPRITE_CELL_BYTES       EQU 256
RTYPE_PY_SPRITE_CACHE_BUFFERS    EQU 1
RTYPE_PY_SPRITE_CELLS_PER_BUFFER EQU 1024
RTYPE_PY_SPRITE_CACHE_TOTAL      EQU 1024
RTYPE_PY_SPRITE_CACHE_RAMG       EQU #0C0000
; Вся bookkeeping живёт в отдельной физической странице TS RAM. Page #09
; уже занята object pool/FIFO/scheduler/palette records: размещение map там
; стирает allocator и даёт пустой level без единого enemy.
RTYPE_PY_SPRITE_META_PAGE        EQU #EC
RTYPE_PY_SPRITE_CELL_MAP         EQU #C000
RTYPE_PY_SPRITE_CELL_MAP_BYTES   EQU 8192
RTYPE_PY_LOGICAL_BITMAP_TRANSFORM EQU 160
RTYPE_PY_WORLD_STRIP_WIDTH       EQU 64
RTYPE_PY_WORLD_STRIP_HEIGHT      EQU 240
RTYPE_PY_WORLD_SLOT_HEIGHT       EQU 512
RTYPE_PY_WORLD_SLOT_BYTES        EQU #8000
RTYPE_PY_WORLD_SLOT_COUNT        EQU 8

; Масштаб вычислен из WIDTH/HEIGHT активного rtype_port.app и физического
; FT812 target. Terrain меняет A/C/E/F, поэтому перед logical Python blit
; translated backend обязан восстановить все шесть коэффициентов.
RTypePyLogicalBitmapState:
                FT_BitmapTransformA RTYPE_PY_LOGICAL_BITMAP_TRANSFORM
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE RTYPE_PY_LOGICAL_BITMAP_TRANSFORM
                FT_BitmapTransformF 0
                RET

; Title Sprite RAM больше не читается в GAME. Resident bytes после
; fixed-player принадлежат сгенерированному backend и видны при любом bank.
RTypePyWorldRenderCount          EQU #4488
RTypeSpriteCacheNextSlot         EQU #4489
RTypePyWorldRenderBaseHigh       EQU #448B
RTypePyWorldRenderSlot           EQU #448C
RTypePyWorldRenderX              EQU #448D
; Scratch lookup принадлежит сгенерированному renderer backend. Python render
; однопоточен, поэтому это не re-entrant ABI и стек Z80 не расходуется под key.
RTypePyHQLookupBankKey           EQU #448E
RTypePyHQLookupFlags             EQU #4490
RTypePyHQLookupCode              EQU #4491
RTypePyHQLookupLow               EQU #4493
RTypePyHQLookupHigh              EQU #4495
RTypePyHQLookupMid               EQU #4497
RTypePyHQLookupSavedPage3        EQU #4499

; Загрузить готовый Python bootstrap 27x30 ARGB4444 в RAM_G. Z80 передаёт
; только выровненный zlib-поток через TS DMA; распаковку выполняет FT812.
; Функция пока является отдельной проверяемой стадией backend: переключение
; draw path выполняется только после готовности resource-aware render queue.
RTypePyHQSprite_Upload:
                CALL FT.Coprocessor.WaitFlush
                RET  C
                FT_WR32_CMD FT_CMD_INFLATE
                LD   DE, RTYPE_PY_HQ_SPRITE_RAMG_BASE & #FFFF
                LD   A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 16) & #FF
                LD   H, 0
                LD   L, A
                CALL FT.Coprocessor.Write32
                RET  C
                LD   A, RTYPE_PY_HQ_SPRITE_ZLIB_FIRST_PAGE
                LD   (.sourcePage), A
                LD   HL, RTYPE_PY_HQ_SPRITE_ZLIB_SIZE
                LD   (.remaining), HL
.page:         LD   BC, #4000
                LD   HL, (.remaining)
                OR   A
                SBC  HL, BC
                JR   NC, .chunkReady
                ADD  HL, BC
                LD   B, H
                LD   C, L
.chunkReady:   LD   (.chunk), BC
                LD   A, (.sourcePage)
                LD   HL, #C000
                CALL RTypeFT_CmdWritePageDMA
                JR   C, .failure
                LD   BC, (.chunk)
                LD   HL, (.remaining)
                OR   A
                SBC  HL, BC
                LD   (.remaining), HL
                LD   A, H
                OR   L
                JR   Z, .complete
                LD   HL, .sourcePage
                INC  (HL)
                JR   .page
.complete:     CALL FT.Coprocessor.WaitFlush
                RET
.failure:      SCF
                RET
.sourcePage:   DEFB 0
.remaining:    DEFW 0
.chunk:        DEFW 0

; Exact HQA2 lookup generated from active Python M72SpriteAtlas._asset keys.
; In:  DE=bank_key ((kind<<8)|value), C=flip flags, HL=Python code.
; Out: CF=0 and A:DE=absolute RAM_G address; CF=1 on an explicit miss.
; Python semantics are applied here: only flip bits 0..1 and code bits 0..11
; participate in the key. The previous slot3 page is always restored.
RTypePyHQSprite_FindCell:
                LD   (RTypePyHQLookupBankKey), DE
                LD   A, C
                AND  #03
                LD   (RTypePyHQLookupFlags), A
                LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTypePyHQLookupCode), HL
                GetPage3
                LD   (RTypePyHQLookupSavedPage3), A
                LD   A, RTYPE_PY_HQ_LOOKUP_PAGE
                SetPage3_A
                LD   HL, 0
                LD   (RTypePyHQLookupLow), HL
                LD   HL, RTYPE_PY_HQ_LOOKUP_COUNT
                LD   (RTypePyHQLookupHigh), HL
.search:        LD   HL, (RTypePyHQLookupLow)
                LD   DE, (RTypePyHQLookupHigh)
                OR   A
                SBC  HL, DE
                JR   NC, .miss
                LD   HL, (RTypePyHQLookupHigh)
                LD   DE, (RTypePyHQLookupLow)
                OR   A
                SBC  HL, DE
                SRL  H
                RR   L
                ADD  HL, DE
                LD   (RTypePyHQLookupMid), HL
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, RTYPE_PY_HQ_LOOKUP_PTR + 16
                ADD  HL, DE
                INC  HL
                LD   A, (RTypePyHQLookupBankKey + 1)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                DEC  HL
                LD   A, (RTypePyHQLookupBankKey)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                LD   A, (RTypePyHQLookupFlags)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                INC  HL
                LD   A, (RTypePyHQLookupCode + 1)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                DEC  HL
                LD   A, (RTypePyHQLookupCode)
                CP   (HL)
                JR   C, .less
                JR   NZ, .greater
                INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   B, (HL)
                INC  HL
                LD   A, (HL)
                OR   A
                JR   NZ, .miss
                LD   A, E
                ADD  A, RTYPE_PY_HQ_SPRITE_RAMG_BASE & #FF
                LD   E, A
                LD   A, D
                ADC  A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 8) & #FF
                LD   D, A
                LD   A, B
                ADC  A, (RTYPE_PY_HQ_SPRITE_RAMG_BASE >> 16) & #FF
                JR   C, .miss
                CP   #40
                JR   NC, .miss
                LD   B, A
                PUSH BC
                PUSH DE
                LD   A, (RTypePyHQLookupSavedPage3)
                SetPage3_A
                POP  DE
                POP  BC
                LD   A, B
                OR   A
                RET
.less:         LD   HL, (RTypePyHQLookupMid)
                LD   (RTypePyHQLookupHigh), HL
                JP   .search
.greater:      LD   HL, (RTypePyHQLookupMid)
                INC  HL
                LD   (RTypePyHQLookupLow), HL
                JP   .search
.miss:         LD   A, (RTypePyHQLookupSavedPage3)
                SetPage3_A
                SCF
                RET

                ASSERT RTYPE_PY_HQ_LOOKUP_REC_SIZE = 10
                ASSERT RTYPE_PY_HQ_LOOKUP_SIZE = 16 + RTYPE_PY_HQ_LOOKUP_COUNT * 10
                ASSERT RTYPE_PY_HQ_LOOKUP_PTR + RTYPE_PY_HQ_LOOKUP_SIZE <= #10000

; Полный сброс нужен только при входе в новый world/level. Python sprite cells
; immutable, поэтому уже загруженный slot остаётся валиден между кадрами.
RTypeSpriteCache_Reset:
                XOR  A
                LD   (RTypeTargetSpriteLoaded), A
                LD   A, RTYPE_PY_SPRITE_META_PAGE
                SetPage3_A
                LD   HL, RTYPE_PY_SPRITE_CELL_MAP
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP + 1
                LD   BC, RTYPE_PY_SPRITE_CELL_MAP_BYTES - 1
                LD   (HL), #FF
                LDIR
                XOR  A
                LD   (RTypeSpriteCacheNextSlot), A
                LD   (RTypeSpriteCacheNextSlot + 1), A
                INC  A
                LD   (RTypeTargetSpriteLoaded), A
                RET

; Межкадровое начало теперь не очищает map и не вызывает повторные DMA.
RTypeSpriteCache_BeginFrame:
                LD   A, (RTypeTargetSpriteLoaded)
                OR   A
                JP   Z, RTypeSpriteCache_Reset
                RET

; HL=Python cell code 0..4095. Вернуть HL=absolute cache slot 0..1023.
; Каждый miss копирует аппаратным TS DMA ровно одну исходную 16x16 index8 cell.
RTypeSpriteCache_LoadCell:
                LD   A, H
                AND  #F0
                JP   NZ, .full
                LD   (.requested), HL
                LD   A, (RTypeTargetSpriteLoaded)
                OR   A
                CALL Z, RTypeSpriteCache_Reset
                LD   A, RTYPE_PY_SPRITE_META_PAGE
                SetPage3_A
                LD   HL, (.requested)
                ADD  HL, HL
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                EX   DE, HL
                LD   A, H
                CP   #FF
                JR   Z, .miss
                OR   A
                RET

.miss:         LD   HL, (RTypeSpriteCacheNextSlot)
                LD   A, H
                CP   4
                JP   NC, .full
                INC  HL
                LD   (RTypeSpriteCacheNextSlot), HL
                DEC  HL
                LD   (.slot), HL

                LD   HL, (.requested)
                ADD  HL, HL
                LD   DE, RTYPE_PY_SPRITE_CELL_MAP
                ADD  HL, DE
                LD   DE, (.slot)
                LD   (HL), E
                INC  HL
                LD   (HL), D

                LD   HL, (.requested)
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   DE, RTypeSpriteRawPageTable
                ADD  HL, DE
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                LD   HL, (.requested)
                LD   A, L
                AND  #3F
                OR   #C0
                LD   H, A
                LD   L, 0
                LD   DE, (.slot)
                LD   A, D
                ADD  A, (RTYPE_PY_SPRITE_CACHE_RAMG >> 16) & #FF
                LD   D, E
                LD   E, 0
                LD   BC, RTYPE_PY_SPRITE_CELL_BYTES
                CALL RTypeFT_WriteMemDMA
                LD   HL, (.slot)
                OR   A
                RET
.full:         SCF
                RET
.requested:    DEFW 0
.slot:         DEFW 0

; A=0 foreground/1 background, HL=strip index, C=ring tracker. Python создаёт
; contiguous 64x240 strip; FT812 распаковывает его прямо в один из восьми
; 64x512 slots. Старые 240 CMD_MEMCPY и 3840-байтная Z80 SPI-команда исчезли.
RTypePyWorldTexturePump:
                LD   (.layer), A
                LD   A, C
                LD   (.tracker), A
                LD   (.stripIndex), HL
                LD   A, (.layer)
                OR   A
                JR   NZ, .background
                LD   A, (RTypeTargetFgTexturePage)
                LD   HL, (RTypeTargetFgTexturePtr)
                LD   D, #08
                JR   .streamReady
.background:   LD   A, (RTypeTargetBgTexturePage)
                LD   HL, (RTypeTargetBgTexturePtr)
                LD   D, #04
.streamReady:  LD   (.streamPage), A
                LD   (.streamPtr), HL
                LD   A, D
                LD   (.textureBaseHigh), A

                ; destination slot = ((tracker >> 4) + 1) & 7. Y=128 leaves
                ; the same vertical guard area as the former 512x512 ring.
                LD   A, (.tracker)
                RRCA
                RRCA
                RRCA
                RRCA
                INC  A
                AND  7
                LD   C, A
                AND  1
                JR   Z, .evenSlot
                LD   DE, #A000
                JR   .destinationLowReady
.evenSlot:     LD   DE, #2000
.destinationLowReady:
                LD   (.destinationLow), DE
                LD   A, C
                SRL  A
                LD   B, A
                LD   A, (.textureBaseHigh)
                ADD  A, B
                LD   (.destinationHigh), A

                LD   A, (.streamPage)
                SetPage3_A
                LD   HL, (.stripIndex)
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                ADD  HL, HL                      ; index * 6
                LD   DE, (.streamPtr)
                ADD  HL, DE
                LD   DE, RTYPE_TARGET_TEXTURE_HEAD
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   C, (HL)
                INC  HL
                INC  HL
                LD   (.relative), DE
                LD   A, C
                LD   (.relative + 2), A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.compressedSize), DE
                LD   DE, (.relative)
                LD   A, (.relative + 2)
                ADD  A, A
                ADD  A, A
                LD   C, A
                LD   A, D
                AND  #C0
                RLCA
                RLCA
                OR   C
                LD   C, A
                LD   A, (.streamPage)
                ADD  A, C
                LD   (.compressedPage), A
                LD   A, D
                AND  #3F
                LD   H, A
                LD   L, E
                LD   BC, (.compressedSize)
                EXX
                LD   B, 0
                EXX
                LD   A, (.compressedPage)
                EX   AF, AF'
                LD   DE, (.destinationLow)
                LD   A, (.destinationHigh)
                JP   FT.Coprocessor.Inflate
.layer:        DEFB 0
.tracker:      DEFB 0
.stripIndex:   DEFW 0
.streamPage:   DEFB 0
.streamPtr:    DEFW 0
.relative:     DEFS 3
.compressedSize: DEFW 0
.compressedPage: DEFB 0
.textureBaseHigh: DEFB 0
.destinationHigh: DEFB 0
.destinationLow: DEFW 0

; A=physical source page, HL=page-safe strip index, C=tracker, D=map page.
; Source and collision map are simultaneously mapped into slot3/slot2. This
; removes the former 960-byte scratch copy; only the thirty unavoidable
; strided 32-byte map rows remain on Z80, while bitmap pixels go through FT812.
RTypePyWorldMapStripDirect:
                LD   (.inputPage), A
                LD   A, C
                LD   (.tracker), A
                LD   A, D
                LD   (.destinationPage), A
                LD   A, (.inputPage)
                CALL RTypeWorld_StripPointer
                SetPage3_A
                LD   (.source), HL
                LD   A, (.destinationPage)
                SetPage2_A
                LD   A, (.tracker)
                ADD  A, A
                ADD  A, #20
                LD   (.destinationLow), A
                LD   A, #90                      ; slot2 + map offset #1000
                LD   (.destinationHigh), A
                LD   HL, (.source)
                LD   B, 30
.row:
                PUSH BC
                LD   A, (.destinationLow)
                LD   E, A
                LD   A, (.destinationHigh)
                LD   D, A
                LD   BC, 32
                LDIR
                LD   A, (.destinationHigh)
                INC  A
                LD   (.destinationHigh), A
                POP  BC
                DJNZ .row
                LD   A, CorePage + 1
                SetPage2_A
                RET
.inputPage:    DEFB 0
.tracker:      DEFB 0
.destinationPage: DEFB 0
.source:       DEFW 0
.destinationLow: DEFB 0
.destinationHigh: DEFB 0

; Семь отдельных 64x512 bitmap slots покрывают 384 native pixels. FT812 сам
; масштабирует, обрезает первый slot по scroll offset и повторяет Y; Z80 выдаёт
; только семь BITMAP_SOURCE/VERTEX2F вместо копирования 240 строк.
RTypePyRenderWorldBackground:
                LD   A, #04
                LD   (RTypePyWorldRenderBaseHigh), A
                LD   HL, (RTypeWorldBgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL RTypePyWorldRenderPrepareX
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                CALL RTypePyWorldRenderTransform
                LD   HL, (RTypeWorldBgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG
                JP   RTypePyWorldRenderSlots

RTypePyRenderWorldForeground:
                LD   A, #08
                LD   (RTypePyWorldRenderBaseHigh), A
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL RTypePyWorldRenderPrepareX
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                CALL RTypePyWorldRenderTransform
                LD   HL, (RTypeWorldFgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG + 512
                JP   RTypePyWorldRenderSlots

RTypePyWorldRenderPrepareX:
                LD   (.scroll), HL
                LD   A, H
                AND  1
                LD   H, A
                LD   A, L
                AND  #3F
                JR   Z, .zeroOffset
                NEG
                LD   L, A
                LD   H, #FF
                JR   .xReady
.zeroOffset:   LD   HL, 0
.xReady:       LD   (RTypePyWorldRenderX), HL
                ; slot = ((scroll & 511) >> 6) & 7
                LD   HL, (.scroll)
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   A, L
                AND  7
                LD   (RTypePyWorldRenderSlot), A
                RET
.scroll:       DEFW 0

RTypePyWorldRenderTransform:
                FT_BitmapTransformA 96
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85
                RET

RTypePyWorldRenderSlots:
                FT_BitmapLayout FT_PALETTED4444, 64, 512
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_REPEAT, 171, 720
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, 7
                LD   (RTypePyWorldRenderCount), A
.next:         LD   A, (RTypePyWorldRenderSlot)
                LD   C, A
                SRL  A
                LD   B, A
                LD   A, (RTypePyWorldRenderBaseHigh)
                ADD  A, B
                LD   C, A
                LD   A, (RTypePyWorldRenderSlot)
                AND  1
                JR   Z, .sourceEven
                LD   D, #80
                JR   .sourceReady
.sourceEven:   LD   D, 0
.sourceReady:  LD   E, 0
                LD   B, #01
                CALL FT.Coprocessor.Command_BCDE
                LD   HL, (RTypePyWorldRenderX)
                CALL RTypeSprite_NativeXToVertex
                LD   H, B
                LD   L, C
                LD   DE, 0
                CALL M72Video_Vertex2f
                LD   HL, (RTypePyWorldRenderX)
                LD   DE, 64
                ADD  HL, DE
                LD   (RTypePyWorldRenderX), HL
                LD   A, (RTypePyWorldRenderSlot)
                INC  A
                AND  7
                LD   (RTypePyWorldRenderSlot), A
                LD   HL, RTypePyWorldRenderCount
                DEC  (HL)
                JR   NZ, .next
                FT_End
                RET
