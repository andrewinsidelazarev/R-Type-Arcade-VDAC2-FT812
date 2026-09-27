; ============================================================================
; Полный all-stage диспетчер ROM-derived пакета для целевого Z80 runtime.
; Пакет лежит в последовательных 16-КБ страницах SPG и никогда не копируется
; целиком: текущая запись отображается в slot3 только на время чтения.
; ============================================================================

RTypeTargetValid       EQU #42A6
RTypeTargetStage       EQU #42A7
RTypeTargetEventCount  EQU #42A8        ; word
RTypeTargetEventIndex  EQU #42AA        ; word
RTypeTargetEventPage   EQU #42AC
RTypeTargetEventPtr    EQU #42AD        ; word внутри slot3
RTypeTargetCheckPage   EQU #42AF
RTypeTargetCheckPtr    EQU #42B0        ; word внутри slot3
RTypeWorldProgressQ8   EQU #42B2        ; signed 24-bit Q16.8
RTypeWorldFgVelocity   EQU #42B5        ; signed Q8 word
RTypeWorldBgVelocity   EQU #42B7        ; signed Q8 word
RTypeWorldTransition   EQU #42B9
RTypeWorldLastCommand  EQU #42BA        ; word
RTypeWorldLastHandler  EQU #42BC        ; word
RTypeTargetGlobalPage  EQU #42BE
RTypeTargetGlobalPtr   EQU #42BF        ; word внутри slot3
RTypeWorldFgStreamPage EQU #42C1
RTypeWorldBgStreamPage EQU #42C2
RTypeWorldFgStripCount EQU #42C3        ; word
RTypeWorldBgStripCount EQU #42C5        ; word
RTypeWorldFgStripIndex EQU #42C7        ; word
RTypeWorldBgStripIndex EQU #42C9        ; word
RTypeWorldFgTracker    EQU #42CB
RTypeWorldBgTracker    EQU #42CC
RTypeWorldFgTarget     EQU #42CD
RTypeWorldBgTarget     EQU #42CE
RTypeWorldFgScrollQ8   EQU #42CF        ; signed 24-bit Q16.8
RTypeWorldBgScrollQ8   EQU #42D2        ; signed 24-bit Q16.8
RTypeWorldFgDelta      EQU #42D5        ; signed word
RTypeWorldBgDelta      EQU #42D7        ; signed word
RTypeWorldFgSourceBase EQU #42D9        ; word
RTypeWorldBgSourceBase EQU #42DB        ; word
RTypeWorldFgSource     EQU #42DD        ; word checkpoint source
RTypeWorldBgSource     EQU #42DF        ; word checkpoint source
RTypeTargetFgTexturePage EQU #42E1
RTypeTargetFgTexturePtr  EQU #42E2
RTypeTargetBgTexturePage EQU #42E4
RTypeTargetBgTexturePtr  EQU #42E5
RTypeTargetPalettePage   EQU #42E7
RTypeTargetPalettePtr    EQU #42E8
RTypeTargetTextureLoaded EQU #42EA
RTypeWorldFgYScrollQ8    EQU #42EB        ; signed 24-bit Q16.8
RTypeWorldBgYScrollQ8    EQU #42EE        ; signed 24-bit Q16.8
RTypeWorldFgYVelocity    EQU #42F1        ; signed Q8 word
RTypeWorldBgYVelocity    EQU #42F3        ; signed Q8 word
RTypeWorldStage3Active   EQU #42F5
RTypeWorldStage3PathPtr  EQU #42F6        ; адрес внутри одной pack-страницы
RTypeWorldStage3DirY     EQU #42F8        ; signed byte из ROM-записи
RTypeWorldStage3DirX     EQU #42F9        ; signed byte из ROM-записи
RTypeWorldStage3Timer    EQU #42FA        ; byte duration текущей записи
RTypeWorldStage3State    EQU #42FB        ; 0=path, 1=terminal
RTypeWorldStage3Terminal EQU #42FC        ; word, обратный отсчёт 384 VBlank
RTypeTargetSpriteLoaded  EQU #42FE
; Общая страница содержит все заранее преобразованные ARGB4444 palette types.
; Адрес живёт сразу за resident object-work: титульная sprite-копия после
; входа в GAME/DEMO уже не используется, а bank-код видит этот диапазон всегда.
RTypeTargetPaletteResourcePage EQU #437C
RTypeTargetPaletteResourcePtr  EQU #437D        ; word, обычно #C000
RTypePaletteWorkType           EQU #437F
RTypePaletteWorkSlot           EQU #4380
RTypePaletteWorkMask           EQU #4381        ; word
; Финальная последовательность Stage 8 использует три глобальных latch-а из
; исходных `$2F2D/$2FBF/$2FC2`. Они живут в resident RAM: code-bank #0D
; должен видеть их даже когда slot3 занят World ROM или object-page.
RTypeFinalLoopCount            EQU #4383
RTypeFinalStageLatch           EQU #4384
RTypeFinalPlayerExitLatch      EQU #4385

RTYPE_WORLD_FG_MAP_PAGE EQU #07
RTYPE_WORLD_BG_MAP_PAGE EQU #08
RTYPE_WORLD_STRIP_RAMG EQU #018000
RTYPE_WORLD_TILE_PALETTE_RAMG EQU #01C000
RTYPE_WORLD_BG_TEXTURE_RAMG EQU #040000
RTYPE_WORLD_FG_TEXTURE_RAMG EQU #080000
RTYPE_WORLD_SPRITE_TEXTURE_RAMG EQU #0C0000
RTYPE_WORLD_SPRITE_PALETTE_RAMG EQU RTYPE_WORLD_TILE_PALETTE_RAMG + RTYPE_TARGET_SPRITE_PAL_OFF
; Страница #09 целиком принадлежит игровому runtime. Первые 6 КБ отданы
; буквальному M72-пулу из 96 записей по 64 байта; служебные таблицы sprite
; cache лежат после пула. Slot3 отображается сюда только на короткое время:
; распаковщик и ROM-reader вправе немедленно заменить mapping своей страницей.
RTYPE_OBJECT_PAGE        EQU #09
; Метаданные сгенерированного M72SpriteAtlas.draw cache вынесены в отдельную
; физическую page #0F: #D800… page #09 занята FIFO/scheduler object runtime.
RTYPE_WORLD_STAGE3_ABSOLUTE EQU RTYPE_TARGET_WORLD_OFFSET + RTYPE_TARGET_STAGE3_PATH
RTYPE_WORLD_STAGE3_PAGE EQU RTYPE_TARGET_PACK_BASE_PAGE + (RTYPE_WORLD_STAGE3_ABSOLUTE >> 14)
RTYPE_WORLD_STAGE3_PTR EQU #C000 + (RTYPE_WORLD_STAGE3_ABSOLUTE & #3FFF)

; Проверить заголовок target pack и выбрать первый stage/checkpoint.
RTypeTarget_Init:
                XOR  A
                LD   (RTypeTargetValid), A
                LD   (RTypeWorldTransition), A
                LD   (RTypeWorldLastCommand), A
                LD   (RTypeWorldLastCommand + 1), A
                LD   (RTypeWorldLastHandler), A
                LD   (RTypeWorldLastHandler + 1), A
                LD   (RTypeTargetTextureLoaded), A
                LD   (RTypeTargetSpriteLoaded), A
                LD   (RTypeWorldStage3Active), A
                LD   (RTypeFinalLoopCount), A
                LD   (RTypeFinalStageLatch), A
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, RTYPE_TARGET_PACK_BASE_PAGE
                SetPage3_A
                LD   HL, #C000
                LD   A, (HL)
                CP   RTYPE_TARGET_MAGIC_0
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_MAGIC_1
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_MAGIC_2
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_MAGIC_3
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_VERSION
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                OR   A
                JR   NZ, .invalid               ; старший byte version
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_STAGE_COUNT
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_STAGE_REC_SIZE
                JR   NZ, .invalid
                LD   HL, #C038                  ; глобальная checkpoint-таблица
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetGlobalPage), A
                LD   (RTypeTargetGlobalPtr), DE
                ; Header +$1C хранит page-aligned таблицу всех palette types.
                ; Она остаётся общей для восьми подгружаемых stage PAK.
                LD   A, RTYPE_TARGET_PACK_BASE_PAGE
                SetPage3_A
                LD   HL, #C01C
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetPaletteResourcePage), A
                LD   (RTypeTargetPaletteResourcePtr), DE
                LD   A, 1
                LD   (RTypeTargetValid), A
                JP   RTypeTarget_SelectStage
.invalid:      XOR  A
                LD   (RTypeTargetValid), A
                RET

; A=1…8. Выбрать первую checkpoint-запись уровня и подготовить event cursor.
RTypeTarget_SelectStage:
                CP   1
                JP   C, .invalid
                CP   RTYPE_TARGET_STAGE_COUNT + 1
                JP   NC, .invalid
                LD   (RTypeTargetStage), A
                PUSH AF
                LD   A, RTYPE_TARGET_PACK_BASE_PAGE
                SetPage3_A
                POP  AF
                CALL RTypeTarget_StageRecord
                PUSH HL
                LD   DE, 6
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeTargetEventCount), DE
                POP  HL
                PUSH HL
                LD   DE, 2
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgStripCount), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgStripCount), DE
                INC  HL
                INC  HL                          ; event count уже сохранён
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgSourceBase), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgSourceBase), DE
                XOR  A
                LD   (RTypeTargetEventIndex), A
                LD   (RTypeTargetEventIndex + 1), A
                LD   (RTypeWorldTransition), A
                POP  HL

                PUSH HL
                LD   DE, 44                       ; foreground TXS4 offset u32
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetFgTexturePage), A
                LD   (RTypeTargetFgTexturePtr), DE
                POP  HL

                PUSH HL
                LD   DE, 52                       ; background TXS4 offset u32
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetBgTexturePage), A
                LD   (RTypeTargetBgTexturePtr), DE
                POP  HL

                PUSH HL
                LD   DE, 64                       ; палитры текущего уровня
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetPalettePage), A
                LD   (RTypeTargetPalettePtr), DE
                POP  HL

                PUSH HL
                LD   DE, 20                       ; checkpoint offset u32
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetCheckPage), A
                LD   (RTypeTargetCheckPtr), DE
                POP  HL

                PUSH HL
                LD   DE, 24                       ; event offset u32
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeTargetEventPage), A
                LD   (RTypeTargetEventPtr), DE
                POP  HL

                PUSH HL
                LD   DE, 28                       ; foreground stream offset
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeWorldFgStreamPage), A
                POP  HL
                LD   DE, 36                       ; background stream offset
                ADD  HL, DE
                CALL RTypeTarget_OffsetAtHL
                LD   (RTypeWorldBgStreamPage), A

                LD   A, (RTypeTargetCheckPage)
                SetPage3_A
                LD   HL, (RTypeTargetCheckPtr)
                INC  HL                           ; index
                INC  HL
                LD   E, (HL)                      ; progression
                INC  HL
                LD   D, (HL)
                XOR  A
                LD   (RTypeWorldProgressQ8), A
                LD   (RTypeWorldProgressQ8 + 1), DE
                INC  HL
                LD   E, (HL)                      ; foreground source
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgSource), DE
                INC  HL
                LD   E, (HL)                      ; background source
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgSource), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgVelocity), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgVelocity), DE
                LD   HL, (RTypeWorldFgSource)
                LD   DE, (RTypeWorldFgSourceBase)
                CALL RTypeWorld_SourceIndex
                LD   (RTypeWorldFgStripIndex), HL
                LD   HL, (RTypeWorldBgSource)
                LD   DE, (RTypeWorldBgSourceBase)
                CALL RTypeWorld_SourceIndex
                LD   (RTypeWorldBgStripIndex), HL
                XOR  A
                LD   (RTypeWorldFgTracker), A
                LD   (RTypeWorldBgTracker), A
                LD   (RTypeWorldFgScrollQ8), A
                LD   (RTypeWorldFgScrollQ8 + 1), A
                LD   (RTypeWorldFgScrollQ8 + 2), A
                LD   (RTypeWorldBgScrollQ8), A
                LD   (RTypeWorldBgScrollQ8 + 1), A
                LD   (RTypeWorldBgScrollQ8 + 2), A
                LD   (RTypeWorldFgYScrollQ8), A
                LD   (RTypeWorldFgYScrollQ8 + 1), A
                LD   (RTypeWorldFgYScrollQ8 + 2), A
                LD   (RTypeWorldBgYScrollQ8), A
                LD   (RTypeWorldBgYScrollQ8 + 1), A
                LD   (RTypeWorldBgYScrollQ8 + 2), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                LD   (RTypeWorldStage3Active), A
                LD   (RTypeWorldStage3State), A
                LD   A, #70
                LD   (RTypeWorldFgTarget), A
                LD   (RTypeWorldBgTarget), A
                XOR  A
                LD   (RTypeTargetTextureLoaded), A
                CALL RTypeWorldTexture_Validate
                LD   A, (GameMode)
                OR   A
                CALL NZ, RTypeWorldTexture_Enable
                CALL RTypeWorld_ClearMaps
                LD   B, 7
.preload:      PUSH BC
                CALL RTypeWorld_PumpForeground
                CALL RTypeWorld_PumpBackground
                POP  BC
                DJNZ .preload
                RET
.invalid:      XOR  A
                LD   (RTypeTargetValid), A
                RET

; A=stage 1…8, результат HL=#C040+(stage-1)*размер записи.
RTypeTarget_StageRecord:
                DEC  A
                LD   B, A
                LD   HL, 0
                LD   DE, RTYPE_TARGET_STAGE_REC_SIZE
                OR   A
                JR   Z, .ready
.multiply:     ADD  HL, DE
                DJNZ .multiply
.ready:
                LD   DE, #C000 + RTYPE_TARGET_STAGE_DIR
                ADD  HL, DE
                RET

; HL указывает на абсолютный u32 offset внутри pack.
; Результат: A=страница TS-Config, DE=адрес #C000…#FFFF.
RTypeTarget_OffsetAtHL:
                LD   E, (HL)
                INC  HL
                LD   A, (HL)
                LD   D, A
                LD   B, A
                INC  HL
                LD   A, (HL)
                ADD  A, A
                ADD  A, A
                LD   C, A                        ; старший byte даёт page bits 2…7
                LD   A, B
                AND  #C0
                RLCA
                RLCA                             ; bits 6…7 становятся 0…1
                OR   C
                ADD  A, RTYPE_TARGET_PACK_BASE_PAGE
                LD   C, A
                LD   A, D
                AND  #3F
                OR   #C0
                LD   D, A
                LD   A, C
                RET

; Проверить два page-safe TXS4-потока сжатых index8-полос текущего stage.
RTypeWorldTexture_Validate:
                LD   A, (RTypeTargetFgTexturePage)
                LD   HL, (RTypeTargetFgTexturePtr)
                LD   DE, (RTypeWorldFgStripCount)
                CALL RTypeWorldTexture_ValidateOne
                RET  NZ
                LD   A, (RTypeTargetBgTexturePage)
                LD   HL, (RTypeTargetBgTexturePtr)
                LD   DE, (RTypeWorldBgStripCount)
RTypeWorldTexture_ValidateOne:
                SetPage3_A
                LD   A, (HL)
                CP   'T'
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   'X'
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   'S'
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   '4'
                JR   NZ, .invalid
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                PUSH HL
                LD   H, B
                LD   L, C
                OR   A
                SBC  HL, DE
                POP  HL
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                CP   RTYPE_TARGET_TEXTURE_REC
                JR   NZ, .invalid
                INC  HL
                LD   A, (HL)
                OR   A
                RET  Z
.invalid:      XOR  A
                LD   (RTypeTargetValid), A
                OR   1                           ; NZ для вызывающего
                RET

; Палитра сохраняет hardware slot в high nibble index8. Два набора:
; background полностью непрозрачен, foreground прозрачен только по pen 0.
RTypeWorldTexture_Enable:
                LD   A, (RTypeTargetValid)
                OR   A
                RET  Z
                LD   A, (RTypeTargetPalettePage)
                LD   (RTypeFT_DmaSourcePage), A
                LD   HL, (RTypeTargetPalettePtr)
                LD   BC, RTYPE_TARGET_TILE_PAL_SIZE
                LD   DE, RTYPE_WORLD_TILE_PALETTE_RAMG & #FFFF
                LD   A, (RTYPE_WORLD_TILE_PALETTE_RAMG >> 16) & #FF
                CALL RTypeFT_WriteMemDMA
                LD   A, 1
                LD   (RTypeTargetTextureLoaded), A
                RET

; Реализация получается из активных M72SpriteAtlas.draw/cell. Она хранится
; отдельным generated-файлом, чтобы изменение Python AST ломало трансляцию,
; а не оставляло незаметно старый вручную написанный cache backend.
                include "generated_python_sprite_cache.asm"

; A=0 foreground/1 background, HL=strip index, C=ring tracker.
; FT812 распаковывает 64x240 index8 во временную RAM_G, затем ровно 240
; CMD_MEMCPY раскладывают строки по stride 512 живой ring-текстуры.
RTypeWorldTexture_Pump:
                ; Алгоритм создаётся транслятором из активного Python
                ; M72Tilemaps: FT812 inflate сразу в 64x512 hardware slot.
                JP   RTypePyWorldTexturePump
                if 0
                LD   (.layer), A
                LD   A, C
                LD   (.tracker), A
                LD   A, (.layer)
                LD   (.stripIndex), HL
                OR   A
                JR   NZ, .background
                LD   A, (RTypeTargetFgTexturePage)
                LD   HL, (RTypeTargetFgTexturePtr)
                LD   D, #09                      ; FG base $080000 + Y $010000
                JR   .streamReady
.background:   LD   A, (RTypeTargetBgTexturePage)
                LD   HL, (RTypeTargetBgTexturePtr)
                LD   D, #05                      ; BG base $040000 + Y $010000
.streamReady:  LD   (.streamPage), A
                LD   (.streamPtr), HL
                LD   A, D
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
                LD   E, (HL)                    ; relative offset u32
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   C, (HL)
                INC  HL
                INC  HL                          ; пропустить старший offset byte 0
                LD   (.relative), DE
                LD   A, C
                LD   (.relative + 2), A
                LD   E, (HL)                    ; compressed size u16
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
                LD   C, A                       ; page delta
                LD   A, (.streamPage)
                ADD  A, C
                LD   (.compressedPage), A
                LD   A, D
                AND  #3F
                LD   H, A                       ; Inflate сам добавит $C000
                LD   L, E

                LD   BC, (.compressedSize)
                EXX
                LD   B, 0
                EXX
                LD   A, (.compressedPage)
                EX   AF, AF'
                LD   DE, RTYPE_WORLD_STRIP_RAMG & #FFFF
                LD   A, (RTYPE_WORLD_STRIP_RAMG >> 16) & #FF
                CALL FT.Coprocessor.Inflate
                RET  C

                LD   A, (.tracker)
                SRL  A
                ADD  A, 8
                AND  63
                ; Tracker хранит позицию в исходных 4-байтных tile-cell:
                ; после деления на два и ring-смещения получаем tile X 0…56.
                ; Умножать его на восемь в A нельзя: для правой половины
                ; bitmap координаты 256…448 теряли девятый бит и полосы
                ; ошибочно перезаписывали левую половину в X=0…192. Сначала
                ; расширяем tile X до 16 бит и только затем считаем byte X.
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; destination X byte 0…448
                LD   (.destinationLow), HL
                LD   HL, RTYPE_WORLD_STRIP_RAMG & #FFFF
                LD   (.sourceLow), HL
                LD   A, (RTYPE_WORLD_STRIP_RAMG >> 16) & #FF
                LD   (.sourceHigh), A
                LD   A, 240
                LD   (.rows), A
                FT_CMD_Start
.row:          LD   DE, FT_CMD_MEMCPY & #FFFF
                LD   BC, (FT_CMD_MEMCPY >> 16) & #FFFF
                CALL FT.Coprocessor.Command_BCDE
                LD   DE, (.destinationLow)
                LD   A, (.destinationHigh)
                LD   C, A
                LD   B, 0
                CALL FT.Coprocessor.Command_BCDE
                LD   DE, (.sourceLow)
                LD   A, (.sourceHigh)
                LD   C, A
                LD   B, 0
                CALL FT.Coprocessor.Command_BCDE
                LD   DE, 64
                LD   BC, 0
                CALL FT.Coprocessor.Command_BCDE
                LD   HL, (.sourceLow)
                LD   DE, 64
                ADD  HL, DE
                LD   (.sourceLow), HL
                LD   A, (.sourceHigh)
                ADC  A, 0
                LD   (.sourceHigh), A
                LD   HL, (.destinationLow)
                LD   DE, 512
                ADD  HL, DE
                LD   (.destinationLow), HL
                LD   A, (.destinationHigh)
                ADC  A, 0
                LD   (.destinationHigh), A
                LD   HL, .rows
                DEC  (HL)
                JR   NZ, .row
                FT_CMD_Write
                JP   FT.Coprocessor.WaitFlush
.layer:        DEFB 0
.tracker:      DEFB 0
.stripIndex:   DEFW 0
.streamPage:   DEFB 0
.streamPtr:    DEFW 0
.relative:     DEFS 3
.compressedSize: DEFW 0
.compressedPage: DEFB 0
.sourceLow:    DEFW 0
.sourceHigh:   DEFB 0
.destinationLow: DEFW 0
.destinationHigh: DEFB 0
.rows:         DEFB 0
                endif

; HL=ROM source текущего checkpoint, DE=source_start stage. Результат —
; номер десятисловной descriptor-полосы внутри stage stream.
RTypeWorld_SourceIndex:
                OR   A
                SBC  HL, DE
                LD   BC, 0
.divide:       LD   DE, 10
                OR   A
                SBC  HL, DE
                JR   C, .done
                INC  BC
                JR   .divide
.done:         ADD  HL, DE
                LD   H, B
                LD   L, C
                RET

; Очистить обе 16-КБ ring-карты tile code `$0FA0`, attribute 0.
RTypeWorld_ClearMaps:
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   HL, #C000
                LD   (HL), 0
                LD   DE, #C001
                LD   BC, #3FFF
                LDIR
                LD   HL, #C200                    ; первые #200 bytes FG нулевые
                LD   BC, #3DFC
                CALL RTypeWorld_FillBlank
                LD   A, RTYPE_WORLD_BG_MAP_PAGE
                JP   RTypeWorld_ClearMap
RTypeWorld_ClearMap:
                SetPage3_A
                LD   HL, #C000
                LD   BC, #3FFC
RTypeWorld_FillBlank:
                LD   (HL), #A0
                INC  HL
                LD   (HL), #0F
                INC  HL
                LD   (HL), 0
                INC  HL
                LD   (HL), 0
                DEC  HL
                DEC  HL
                DEC  HL
                LD   D, H
                LD   E, L
                INC  DE
                INC  DE
                INC  DE
                INC  DE
                LDIR
                RET

RTypeWorld_PumpForeground:
                LD   A, (RTypeWorldFgTracker)
                LD   B, A
                LD   A, (RTypeWorldFgTarget)
                CP   B
                RET  Z
                LD   A, (RTypeWorldFgTracker)
                LD   C, A
                LD   D, RTYPE_WORLD_FG_MAP_PAGE
                LD   A, (RTypeWorldFgStreamPage)
                LD   HL, (RTypeWorldFgStripIndex)
                CALL RTypePyWorldMapStripDirect
                LD   A, (RTypeTargetTextureLoaded)
                OR   A
                JR   Z, .advance
                LD   A, (RTypeWorldFgTracker)
                LD   C, A
                LD   HL, (RTypeWorldFgStripIndex)
                XOR  A
                CALL RTypeWorldTexture_Pump
.advance:
                LD   HL, (RTypeWorldFgStripIndex)
                INC  HL
                LD   (RTypeWorldFgStripIndex), HL
                LD   A, (RTypeWorldFgTracker)
                ADD  A, #10
                LD   (RTypeWorldFgTracker), A
                RET

RTypeWorld_PumpBackground:
                LD   A, (RTypeWorldBgTracker)
                LD   B, A
                LD   A, (RTypeWorldBgTarget)
                CP   B
                RET  Z
                LD   A, (RTypeWorldBgTracker)
                LD   C, A
                LD   D, RTYPE_WORLD_BG_MAP_PAGE
                LD   A, (RTypeWorldBgStreamPage)
                LD   HL, (RTypeWorldBgStripIndex)
                CALL RTypePyWorldMapStripDirect
                LD   A, (RTypeTargetTextureLoaded)
                OR   A
                JR   Z, .advance
                LD   A, (RTypeWorldBgTracker)
                LD   C, A
                LD   HL, (RTypeWorldBgStripIndex)
                LD   A, 1
                CALL RTypeWorldTexture_Pump
.advance:
                LD   HL, (RTypeWorldBgStripIndex)
                INC  HL
                LD   (RTypeWorldBgStripIndex), HL
                LD   A, (RTypeWorldBgTracker)
                ADD  A, #10
                LD   (RTypeWorldBgTracker), A
                RET

; A=base page секции, HL=strip index. Скопировать page-safe запись в #4700.
RTypeWorld_CopyStripToScratch:
                CALL RTypeWorld_StripPointer
                SetPage3_A
                LD   DE, M72StageEventScratch
                LD   BC, RTYPE_TARGET_STRIP_BYTES
                LDIR
                RET

; A=base page, HL=strip index. Результат A=страница, HL=адрес записи.
RTypeWorld_StripPointer:
                LD   C, A
                LD   B, 0                         ; page delta
.page:         LD   DE, RTYPE_TARGET_STRIPS_PAGE
                OR   A
                SBC  HL, DE
                JR   C, .slot
                INC  B
                JR   .page
.slot:         ADD  HL, DE                       ; остаток 0…16
                LD   A, L
                LD   HL, #C000
                OR   A
                JR   Z, .addressReady
                LD   DE, RTYPE_TARGET_STRIP_BYTES
.offset:       ADD  HL, DE
                DEC  A
                JR   NZ, .offset
.addressReady: LD   A, C
                ADD  A, B
                RET

; A=tracker `$00,$10…`: перенести scratch-полосу в 30 строк ring tilemap.
RTypeWorld_ApplyStrip:
                LD   HL, M72StageEventScratch
RTypeWorld_ApplyStripFromHL:
                LD   (.source), HL
                ADD  A, A
                ADD  A, #20
                LD   (.destinationLow), A
                LD   A, #D0                      ; #C000 + VRAM offset #1000
                LD   (.destinationHigh), A
                LD   HL, (.source)
                LD   B, 30
.row:          PUSH BC
                LD   A, (.destinationLow)
                LD   E, A
                LD   A, (.destinationHigh)
                LD   D, A
                LD   BC, 32                      ; восемь code/attribute cells
                LDIR
                LD   A, (.destinationHigh)
                INC  A                           ; следующая строка через #100
                LD   (.destinationHigh), A
                POP  BC
                DJNZ .row
                RET
.destinationLow:
                DEFB 0
.destinationHigh:
                DEFB 0
.source:       DEFW 0

; HL=адрес signed 24-bit accumulator, DE=signed Q8 velocity.
; Возвращает NZ, если native X пересёк границу 64 пикселя.
RTypeWorld_AddScrollVelocity:
                PUSH HL
                POP  IX
                LD   A, (IX + 1)
                AND  #40
                LD   B, A
                LD   L, (IX + 0)
                LD   H, (IX + 1)
                ADD  HL, DE
                LD   (IX + 0), L
                LD   (IX + 1), H
                LD   C, 0
                BIT  7, D
                JR   Z, .positive
                DEC  C
.positive:     LD   A, (IX + 2)
                ADC  A, C
                LD   (IX + 2), A
                LD   A, (IX + 1)
                XOR  B
                AND  #40
                RET

; Преобразовать signed byte A в signed Q8 word со сдвигом влево на четыре.
; Именно так V30-код Stage 3 превращает direction `$F8…$08` из ROM path в
; скорость интегратора. Расширение знака выполняется до сдвигов, иначе
; отрицательные направления превратились бы в большие положительные слова.
RTypeWorld_SignedByteShift4:
                LD   L, A
                LD   H, 0
                BIT  7, L
                JR   Z, .shift
                DEC  H
.shift:        ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                RET

; Запустить объект `$C46E`: первая трёхбайтная запись только загружается.
; Её скорость начнёт действовать в следующем VBlank, потому что исходный
; object scheduler выполняется после четырёх scroll-интеграторов `$0467`.
RTypeWorld_Stage3Start:
                LD   HL, RTYPE_WORLD_STAGE3_PTR
                LD   (RTypeWorldStage3PathPtr), HL
                XOR  A
                LD   (RTypeWorldStage3State), A
                INC  A
                LD   (RTypeWorldStage3Active), A
                JP   RTypeWorld_Stage3LoadRecord

; Прочитать `(signed BG-Y, signed BG-X, duration)` из World ROM. Поток
; `$6F8A…$72FF` целиком помещается в одной 16-КБ странице target pack.
; NZ означает обычную запись; Z — terminal sentinel duration `$80`.
RTypeWorld_Stage3LoadRecord:
                LD   A, RTYPE_WORLD_STAGE3_PAGE
                SetPage3_A
                LD   HL, (RTypeWorldStage3PathPtr)
                LD   A, (HL)
                LD   (RTypeWorldStage3DirY), A
                INC  HL
                LD   A, (HL)
                LD   (RTypeWorldStage3DirX), A
                INC  HL
                LD   A, (HL)
                CP   #80
                RET  Z
                LD   (RTypeWorldStage3Timer), A
                INC  HL
                LD   (RTypeWorldStage3PathPtr), HL
                OR   1
                RET

; Один шаг фонового контроллера Stage 3 после текущих интеграторов.
RTypeWorld_Stage3Update:
                LD   A, (RTypeWorldStage3Active)
                OR   A
                RET  Z
                LD   A, (RTypeWorldStage3State)
                OR   A
                JR   NZ, .terminal
                LD   A, (RTypeWorldStage3DirY)
                CALL RTypeWorld_SignedByteShift4
                LD   (RTypeWorldBgYVelocity), HL
                LD   A, (RTypeWorldStage3DirX)
                CALL RTypeWorld_SignedByteShift4
                LD   (RTypeWorldBgVelocity), HL
                LD   HL, RTypeWorldStage3Timer
                DEC  (HL)
                RET  NZ
                CALL RTypeWorld_Stage3LoadRecord
                RET  NZ
                ; Sentinel `$80`: foreground X останавливается немедленно,
                ; а вертикальный выход со скоростью -$40 начнётся со
                ; следующего вызова, как в ветке `$C55D/$C57D` оригинала.
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                INC  A
                LD   (RTypeWorldStage3State), A
                LD   HL, #0180
                LD   (RTypeWorldStage3Terminal), HL
                RET
.terminal:     XOR  A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   HL, -#0040
                LD   (RTypeWorldBgYVelocity), HL
                LD   HL, (RTypeWorldStage3Terminal)
                DEC  HL
                LD   (RTypeWorldStage3Terminal), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTypeWorldStage3Active), A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                INC  A
                LD   (RTypeWorldTransition), A
                RET

; Один VBlank общего progression/event scheduler для выбранного stage.
RTypeWorld_Update:
                LD   A, (RTypeTargetValid)
                OR   A
                RET  Z
                ; Object handlers получают не Q8 velocity, а фактическое
                ; signed целое смещение foreground за этот VBlank. Сохраняем
                ; старую integer часть, после интегратора заменяем её разностью.
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   (RTypeWorldFgDelta), HL
                LD   HL, RTypeWorldFgScrollQ8
                LD   DE, (RTypeWorldFgVelocity)
                CALL RTypeWorld_AddScrollVelocity
                PUSH AF
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   DE, (RTypeWorldFgDelta)
                OR   A
                SBC  HL, DE
                LD   (RTypeWorldFgDelta), HL
                POP  AF
                JR   Z, .backgroundScroll
                LD   A, (RTypeWorldFgTarget)
                ADD  A, #10
                LD   (RTypeWorldFgTarget), A
.backgroundScroll:
                LD   HL, RTypeWorldBgScrollQ8
                LD   DE, (RTypeWorldBgVelocity)
                CALL RTypeWorld_AddScrollVelocity
                JR   Z, .verticalScroll
                LD   A, (RTypeWorldBgTarget)
                ADD  A, #10
                LD   (RTypeWorldBgTarget), A
.verticalScroll:
                LD   HL, RTypeWorldFgYScrollQ8
                LD   DE, (RTypeWorldFgYVelocity)
                CALL RTypeWorld_AddScrollVelocity
                LD   HL, RTypeWorldBgYScrollQ8
                LD   DE, (RTypeWorldBgYVelocity)
                CALL RTypeWorld_AddScrollVelocity
.pumpTerrain:  CALL RTypeWorld_PumpForeground
                CALL RTypeWorld_PumpBackground
                LD   HL, (RTypeWorldProgressQ8)
                LD   DE, (RTypeWorldFgVelocity)
                ADD  HL, DE
                LD   (RTypeWorldProgressQ8), HL
                LD   C, 0
                BIT  7, D
                JR   Z, .positiveVelocity
                DEC  C                            ; sign extension `$FF`
.positiveVelocity:
                LD   A, (RTypeWorldProgressQ8 + 2)
                ADC  A, C
                LD   (RTypeWorldProgressQ8 + 2), A
                CALL RTypeWorld_Stage3Update
                CALL RTypeObjects_Update
                ; Python-runtime выполняет fixed weapon/player scans после
                ; обновления всех автоматов, но до чтения следующего event.
                ; Так снаряд сталкивается уже с текущей позицией этого VBlank.
                CALL RTypeCollision_Update

.eventLoop:    LD   HL, (RTypeTargetEventIndex)
                LD   DE, (RTypeTargetEventCount)
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, (RTypeTargetEventPage)
                SetPage3_A
                LD   HL, (RTypeTargetEventPtr)
                LD   C, (HL)                      ; threshold
                INC  HL
                LD   B, (HL)
                LD   DE, (RTypeWorldProgressQ8 + 1)
                LD   A, D
                CP   B
                RET  C
                JR   NZ, .eventReady
                LD   A, E
                CP   C
                RET  C
.eventReady:   INC  HL
                LD   E, (HL)                      ; command
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldLastCommand), DE
                INC  HL
                LD   E, (HL)                      ; исходный V30 handler
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldLastHandler), DE
                INC  HL
                LD   (RTypeTargetEventPtr), HL
                LD   HL, (RTypeTargetEventIndex)
                INC  HL
                LD   (RTypeTargetEventIndex), HL
                CALL RTypeObjects_DispatchEvent
                CALL RTypeWorld_DispatchGlobal
                ; Исходный dispatcher забирает не более одной stage-записи
                ; за VBlank. Несколько одинаковых thresholds поэтому растягиваются
                ; на последовательные кадры и сохраняют порядок RNG/allocator.
                RET

; Уже перенесённые глобальные handlers; object handlers подключаются к пулу
; отдельно и не должны менять scroll-состояние через приблизительные ветви.
; `$F01B` выбирает global checkpoint по младшим пяти битам command. Для всех
; семи межуровневых записей это первая checkpoint следующего stage; поэтому
; после чтения stage byte можно сразу построить его карты, текстуры и event
; cursor. Вызов происходит внутри event loop, а SelectStage заменяет cursor:
; следующая итерация уже видит начальные события нового уровня.
RTypeWorld_SelectNextStage:
                LD   A, (RTypeWorldLastCommand)
                AND  #1F
                LD   L, A
                LD   H, 0
                ADD  HL, HL                       ; index * 2
                PUSH HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                       ; index * 16
                POP  DE
                OR   A
                SBC  HL, DE                       ; index * 14
                LD   DE, (RTypeTargetGlobalPtr)
                ADD  HL, DE
                LD   DE, 12                       ; stage word checkpoint
                ADD  HL, DE
                LD   A, (RTypeTargetGlobalPage)
                SetPage3_A
                LD   A, (HL)                      ; low byte = stage 1…8
                JP   RTypeStage_LoadAndSelect

RTypeWorld_DispatchGlobal:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F0F3                    ; применить global checkpoint
                OR   A
                SBC  HL, DE
                JR   NZ, .checkStop
                LD   A, (RTypeWorldLastCommand)
                AND  #1F
                LD   L, A
                LD   H, 0
                ADD  HL, HL                       ; index * 2
                PUSH HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                       ; index * 16
                POP  DE
                OR   A
                SBC  HL, DE                       ; index * 14
                LD   DE, (RTypeTargetGlobalPtr)
                ADD  HL, DE
                LD   A, (RTypeTargetGlobalPage)
                SetPage3_A
                INC  HL                           ; global index
                INC  HL
                LD   E, (HL)                      ; progression
                INC  HL
                LD   D, (HL)
                XOR  A
                LD   (RTypeWorldProgressQ8), A
                LD   (RTypeWorldProgressQ8 + 1), DE
                LD   BC, 5
                ADD  HL, BC                       ; cp+8 foreground velocity
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgVelocity), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldBgVelocity), DE
                RET
.checkStop:    LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F429                    ; остановить оба X-scroll
                OR   A
                SBC  HL, DE
                JR   NZ, .checkTransition
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                RET
.checkTransition:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #C46E                    ; Stage 3 vertical path
                OR   A
                SBC  HL, DE
                JP   Z, RTypeWorld_Stage3Start
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F130                    ; terminal transition
                OR   A
                SBC  HL, DE
                JR   NZ, .checkNextStage
                ; `$F130` очищает все четыре X/Y velocity, а не только
                ; горизонтальные слова. Нулевые значения интегрируются уже
                ; следующим VBlank после текущего object scheduler.
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                JR   .transition
.checkNextStage:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F01B                    ; init следующего stage
                OR   A
                SBC  HL, DE
                JP   Z, RTypeWorld_SelectNextStage
                RET
.transition:   LD   A, 1
                LD   (RTypeWorldTransition), A
                RET
