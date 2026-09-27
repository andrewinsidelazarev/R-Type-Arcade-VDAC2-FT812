; Сгенерировано rtype_python_translator.py из Beam renderer/ассетов.
; Ручное редактирование запрещено.

; Eight offline-HQ bitmaps selected by beam_animation_phase.
RTypePyChargeCommandTable:
                ; phase 0: 52x60
                DEFD $0102C000
                DEFD $28000000
                DEFD $0730D03C
                DEFD $29000000
                DEFD $0800A860
                ; phase 1: 49x56
                DEFD $0102D860
                DEFD $28000000
                DEFD $0730C438
                DEFD $29000000
                DEFD $08009E5A
                ; phase 2: 51x56
                DEFD $0102EDD0
                DEFD $28000000
                DEFD $0730CC38
                DEFD $29000000
                DEFD $0800A45A
                ; phase 3: 46x52
                DEFD $01030420
                DEFD $28000000
                DEFD $0730B834
                DEFD $29000000
                DEFD $08009454
                ; phase 4: 51x46
                DEFD $010316D0
                DEFD $28000000
                DEFD $0730CC2E
                DEFD $29000000
                DEFD $0800A44A
                ; phase 5: 46x38
                DEFD $01032924
                DEFD $28000000
                DEFD $0730B826
                DEFD $29000000
                DEFD $0800943D
                ; phase 6: 41x34
                DEFD $010336CC
                DEFD $28000000
                DEFD $0730A422
                DEFD $29000000
                DEFD $08008437
                ; phase 7: 36x28
                DEFD $010341B0
                DEFD $28000000
                DEFD $0730901C
                DEFD $29000000
                DEFD $0800742D
RTypePyChargeCropLeft:
                DEFB 0, 0, 0, 1, 1, 1, 0, 0
RTypePyChargeCropTop:
                DEFB 0, 1, 3, 5, 7, 11, 12, 14

; Beam command strips live in a generated non-stage TS page.
RTYPE_PY_BEAM_COMMAND_PAGE EQU #EB
RTYPE_PY_BEAM_COMMAND_BYTES EQU 8840


; Медленный перенос death/checkpoint лежит в постоянно отображённой page 0
; TS-Conf и генерируется из проверенного выше Python-контракта lifecycle.
RTypePyLifecycle_ClearFixedPlayer:
                XOR  A
                LD   (ArcadeForceRequestedLevel), A
                LD   (ArcadeBitCount), A
                LD   (ArcadeForceDirection), A
                LD   A, RTYPE_FIXED_PLAYER_BANK_PAGE
                SetPage2_A
                CALL RTypeForce_SyncLevel
                CALL RTypeBits_Update
                CALL RTypeFixedPlayerBank_Init
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyLifecycle_SaveCheckpoint:
                LD   A, (RTypeTargetStage)
                LD   (RTypePyCheckpointStage), A
                LD   A, RTYPE_TARGET_PACK_BASE_PAGE
                SetPage3_A
                LD   A, (RTypePyCheckpointStage)
                CALL RTypeTarget_StageRecord
                INC  HL
                LD   A, (HL)
                LD   (RTypePyCheckpointRemaining), A
                LD   A, (RTypeTargetCheckPage)
                SetPage3_A
                LD   HL, (RTypeTargetCheckPtr)
                XOR  A
                LD   (RTypePyCheckpointOrdinal), A
                LD   (RTypePyCheckpointCandidate), A
.checkpoint:    PUSH HL
                INC  HL
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                LD   HL, (RTypeWorldProgressQ8 + 1)
                OR   A
                SBC  HL, BC
                POP  HL
                JR   C, .checkpointDone
                LD   A, (RTypePyCheckpointCandidate)
                LD   (RTypePyCheckpointOrdinal), A
                LD   DE, RTYPE_TARGET_CHECKPOINT_REC
                ADD  HL, DE
                LD   A, (RTypePyCheckpointCandidate)
                INC  A
                LD   (RTypePyCheckpointCandidate), A
                LD   A, (RTypePyCheckpointRemaining)
                DEC  A
                LD   (RTypePyCheckpointRemaining), A
                JR   NZ, .checkpoint
.checkpointDone:
                RET

RTypePyLifecycle_RebuildCheckpoint:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTYPE_TRANSITION_FLAGS)
                LD   (RTypePySavedTransitionFlags), HL
                LD   A, (RTYPE_TRANSITION_SOUND_INDEX)
                LD   (RTypePySavedTransitionSound), A
                LD   A, (RTypePyCheckpointStage)
                CALL RTypeTarget_SelectStage
                CALL RTypePyLifecycle_ApplyCheckpoint
                CALL RTypeObjects_Reset
                CALL RTypeSpriteCache_Reset
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTypePySavedTransitionFlags)
                LD   (RTYPE_TRANSITION_FLAGS), HL
                LD   A, (RTypePySavedTransitionSound)
                LD   (RTYPE_TRANSITION_SOUND_INDEX), A
                CALL RTypePyLifecycle_SelectCheckpointEvent
                CALL ArcadeFixedPlayer_Init
                XOR  A
                LD   (RTypeFinalPlayerExitLatch), A
                RET

RTypePyLifecycle_ApplyCheckpoint:
                LD   A, (RTypeTargetCheckPage)
                SetPage3_A
                LD   HL, (RTypeTargetCheckPtr)
                LD   A, (RTypePyCheckpointOrdinal)
.recordOffset:  OR   A
                JR   Z, .recordReady
                LD   DE, RTYPE_TARGET_CHECKPOINT_REC
                ADD  HL, DE
                DEC  A
                JR   .recordOffset
.recordReady:   INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                XOR  A
                LD   (RTypeWorldProgressQ8), A
                LD   (RTypeWorldProgressQ8 + 1), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeWorldFgSource), DE
                INC  HL
                LD   E, (HL)
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
                LD   A, #70
                LD   (RTypeWorldFgTarget), A
                LD   (RTypeWorldBgTarget), A
                CALL RTypeWorld_ClearMaps
                LD   B, 7
.preload:       PUSH BC
                CALL RTypeWorld_PumpForeground
                CALL RTypeWorld_PumpBackground
                POP  BC
                DJNZ .preload
                RET

RTypePyLifecycle_SelectCheckpointEvent:
                LD   A, (RTypeTargetEventPage)
                SetPage3_A
                LD   HL, (RTypeTargetEventPtr)
                LD   BC, 0
.event:         PUSH HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTypeWorldProgressQ8 + 1)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   Z, .eventFound
                LD   DE, RTYPE_TARGET_EVENT_REC
                ADD  HL, DE
                INC  BC
                LD   DE, (RTypeTargetEventCount)
                PUSH HL
                LD   H, B
                LD   L, C
                OR   A
                SBC  HL, DE
                POP  HL
                JR   C, .event
                RET
.eventFound:    LD   (RTypeTargetEventPtr), HL
                LD   (RTypeTargetEventIndex), BC
                RET

; Буквальный Game._draw_debug_distance: четыре hex-цифры берутся из того же
; progression, что Python выводит как `DIST {value:04X}`. Строку и тень рисует
; аппаратный ROM-font FT812 в правом нижнем углу без участия Z80 в пикселях.
; Процедура лежит в постоянно отображённой page 0, сохраняя место в Core.
RTypePyRenderDistance:
                LD   HL, (RTypeWorldProgressQ8 + 1)
                LD   DE, RTypePyDistanceBuffer + 5
                LD   A, H
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                CALL .storeHex
                LD   A, H
                AND  #0F
                CALL .storeHex
                LD   A, L
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                CALL .storeHex
                LD   A, L
                AND  #0F
                CALL .storeHex
                FT_LoadIdentity
                FT_Scale #0001999A, #0001999A
                FT_SetMatrix
                FT_ColorRGB 0, 0, 0
                FT_Text 915, 711, 26, 0
                LD   HL, RTypePyDistanceBuffer
                LD   BC, 12
                CALL FT.Coprocessor.Copy
                FT_ColorRGB 255, 255, 255
                FT_Text 914, 710, 26, 0
                LD   HL, RTypePyDistanceBuffer
                LD   BC, 12
                JP   FT.Coprocessor.Copy
.storeHex:     CP   10
                JR   C, .decimal
                ADD  A, 'A' - 10
                JR   .store
.decimal:      ADD  A, '0'
.store:        LD   (DE), A
                INC  DE
                RET

RTypePyDistanceBuffer:
                DEFM "DIST "
                DEFS 4, '0'
                DEFB 0, 0, 0

RTypePyCheckpointStage:          DEFB 1
RTypePyCheckpointOrdinal:        DEFB 0
RTypePyCheckpointCandidate:      DEFB 0
RTypePyCheckpointRemaining:      DEFB 0
RTypePySavedTransitionFlags:     DEFW 0
RTypePySavedTransitionSound:     DEFB 0

; Bank4-обёртки Core пересекли границу $8000. После смены page2
; возврат в такую обёртку зависел от случайного состояния кэша Z80.
; Транслятор ставит JP на постоянно отображённые мосты page 0.
RTypePyInstallBank4Bridges:
                LD   HL, RTypePyBank4BridgePatchTable
                LD   B, 26
.next:         LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   A, (HL)
                INC  HL
                PUSH HL
                EX   DE, HL
                LD   (HL), #C3
                INC  HL
                LD   (HL), C
                INC  HL
                LD   (HL), A
                POP  HL
                DJNZ .next
                RET

RTypePyBank4BridgePatchTable:
                DEFW RTypeObjectBank4_InitBossB7FB, RTypePyBridge_RTypeObjectBank4_InitBossB7FB
                DEFW RTypeObjectBank4_UpdateBossB7FBRoot, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRoot
                DEFW RTypeObjectBank4_UpdateBossB7FBSegment, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBSegment
                DEFW RTypeObjectBank4_DamageBossB7FBSegment, RTypePyBridge_RTypeObjectBank4_DamageBossB7FBSegment
                DEFW RTypeObjectBank4_UpdateBossB7FBRandomSpawner, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRandomSpawner
                DEFW RTypeObjectBank4_UpdateBossB7FBRandomChild, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRandomChild
                DEFW RTypeObjectBank4_DamageBossB7FBRandomChild, RTypePyBridge_RTypeObjectBank4_DamageBossB7FBRandomChild
                DEFW RTypeObjectBank4_UpdateBossB7FBMissileSpawner, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBMissileSpawner
                DEFW RTypeObjectBank4_UpdateBossB7FBMissile, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBMissile
                DEFW RTypeObjectBank4_DamageBossB7FBMissile, RTypePyBridge_RTypeObjectBank4_DamageBossB7FBMissile
                DEFW RTypeObjectBank4_UpdateBossB7FBCore, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBCore
                DEFW RTypeObjectBank4_DamageBossB7FBCore, RTypePyBridge_RTypeObjectBank4_DamageBossB7FBCore
                DEFW RTypeObjectBank4_UpdateBossB7FBCoreChild, RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBCoreChild
                DEFW RTypeObjectBank4_InitPaletteControl, RTypePyBridge_RTypeObjectBank4_InitPaletteControl
                DEFW RTypeObjectBank4_InitFinalStreamFB10, RTypePyBridge_RTypeObjectBank4_InitFinalStreamFB10
                DEFW RTypeObjectBank4_UpdateFinalStreamFB53, RTypePyBridge_RTypeObjectBank4_UpdateFinalStreamFB53
                DEFW RTypeObjectBank4_InitFinalResetEE0B, RTypePyBridge_RTypeObjectBank4_InitFinalResetEE0B
                DEFW RTypeObjectBank4_InitFinalSequenceEEAB, RTypePyBridge_RTypeObjectBank4_InitFinalSequenceEEAB
                DEFW RTypeObjectBank4_UpdateFinalResetEE3C, RTypePyBridge_RTypeObjectBank4_UpdateFinalResetEE3C
                DEFW RTypeObjectBank4_UpdateFinalSequenceEEB5, RTypePyBridge_RTypeObjectBank4_UpdateFinalSequenceEEB5
                DEFW RTypeObjectBank4_InitStageControllers, RTypePyBridge_RTypeObjectBank4_InitStageControllers
                DEFW RTypeObjectBank4_UpdateStageController, RTypePyBridge_RTypeObjectBank4_UpdateStageController
                DEFW RTypeObjectBank4_UpdateBossB1D8Root, RTypePyBridge_RTypeObjectBank4_UpdateBossB1D8Root
                DEFW RTypeObjectBank4_UpdateBossB1D8Child, RTypePyBridge_RTypeObjectBank4_UpdateBossB1D8Child
                DEFW RTypeObjectBank4_UpdateC0FinalSprite, RTypePyBridge_RTypeObjectBank4_UpdateC0FinalSprite
                DEFW RTypeObjectBank4_UpdateC0TerrainChild, RTypePyBridge_RTypeObjectBank4_UpdateC0TerrainChild

; Game.__init__/M72EnemyWorld.__init__ snapshot emitted by Python.
RTypePyGameplay_LoadInitialSnapshot:
                LD   A, RTYPEPYINITIALCHECKPOINT_PAGE
                SetPage2_A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, #8000 + RTYPEPYINITIALCHECKPOINT_OFFSET + 4
                LD   A, (HL)
                INC  HL
.record:       OR   A
                JR   Z, .recordsDone
                DEC  A
                PUSH AF
                LD   E, (HL)
                INC  HL
                PUSH HL
                LD   L, E
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_OBJECT_BASE
                ADD  HL, DE
                EX   DE, HL
                POP  HL
                LD   BC, RTYPE_OBJECT_REC_SIZE
                LDIR
                POP  AF
                JR   .record
.recordsDone:  LD   DE, RTYPE_OBJECT_FREE_QUEUE
                LD   BC, 96
                LDIR
                LD   DE, RTYPE_OBJECT_FREE_HEAD
                LD   BC, 5
                LDIR
                LD   DE, RTYPE_RESOURCE_TYPES
                LD   BC, 35
                LDIR
                LD   DE, RTYPE_SCHED_NEXT
                LD   BC, 194
                LDIR
                LD   DE, RTypeWorldProgressQ8
                LD   BC, 7
                LDIR
                LD   DE, RTypeWorldFgScrollQ8
                LD   BC, 6
                LDIR
                LD   HL, 8
                LD   (RTypeTargetEventIndex), HL
                LD   HL, (RTypeTargetEventPtr)
                LD   DE, 48
                ADD  HL, DE
                LD   (RTypeTargetEventPtr), HL
                LD   HL, 1
                LD   (ArcadeStageFrame), HL
                LD   A, CorePage + 1
                SetPage2_A
                XOR  A
                LD   (RTypePyInitialSnapshotPending), A
                RET

RTypePyBridge_RTypeObjectBank4_InitBossB7FB:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitBossB7FB
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRoot:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRoot
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBSegment:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBSegment
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_DamageBossB7FBSegment:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBSegment
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRandomSpawner:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRandomSpawner
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBRandomChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRandomChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_DamageBossB7FBRandomChild:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBRandomChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBMissileSpawner:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBMissileSpawner
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBMissile:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBMissile
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_DamageBossB7FBMissile:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBMissile
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBCore:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBCore
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_DamageBossB7FBCore:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBCore
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB7FBCoreChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBCoreChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_InitPaletteControl:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitPaletteControl
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_InitFinalStreamFB10:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalStreamFB10
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateFinalStreamFB53:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalStreamFB53
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_InitFinalResetEE0B:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalResetEE0B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_InitFinalSequenceEEAB:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalSequenceEEAB
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateFinalResetEE3C:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalResetEE3C
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateFinalSequenceEEB5:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalSequenceEEB5
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_InitStageControllers:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitStageControllers
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateStageController:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateStageController
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB1D8Root:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB1D8Root
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateBossB1D8Child:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB1D8Child
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateC0FinalSprite:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateC0FinalSprite
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypePyBridge_RTypeObjectBank4_UpdateC0TerrainChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateC0TerrainChild
                LD   A, CorePage + 1
                SetPage2_A
                RET
