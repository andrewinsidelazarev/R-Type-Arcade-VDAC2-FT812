; ============================================================================
; Bank #0B: составной босс Dobkeratops и связанные с ним state machines.
;
; Файл собирается с ORG `$8000` после сохранения resident Core. Вызывающие
; trampolines находятся в page #05/#06; никакая функция этого банка не имеет
; права возвращаться, оставив slot2 отличным от #0B — восстановление делает
; trampoline сразу после CALL.
; ============================================================================

; ----------------------------------------------------------------------------
; `$98FD/$9915/$9A80`: root и создание 25 физических частей Dobkeratops.
; ----------------------------------------------------------------------------

RTypeBank2_InitDobkeratops:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_DOB_ROOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #3800
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   HL, #1000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_TIMEOUT), HL
                LD   A, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_ANCHORS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_DEFEATED), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_BODY_DEAD), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_RootIndex), A
                XOR  A
                LD   (RTypeBank2_Defeated), A
                LD   (RTypeBank2_BodyDestroyed), A
                LD   A, 4
                LD   (RTypeBank2_AnchorsRemaining), A
                JP   RTypeObjects_CommitCurrent

RTypeBank2_UpdateDobRoot:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_RootIndex), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ROOT_SPAWN
                JP   Z, RTypeBank2_DobSpawnParts
                CP   RTYPE_DOB_ROOT_END
                JP   Z, RTypeBank2_DobRootEnd
                LD   A, (RTypeBank2_Defeated)
                OR   A
                JR   Z, .bodyFlag
                ; Только root-defeated `$9AAE` поднимает глобальный cleanup.
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, 1
                LD   (RTYPE_CLEANUP_ACTIVE), A
                JR   RTypeBank2_DobBeginEnd
.bodyFlag:     LD   A, (RTypeBank2_BodyDestroyed)
                OR   A
                JR   NZ, RTypeBank2_DobBeginEnd
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_TIMEOUT)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_TIMEOUT), HL
                LD   A, H
                OR   L
                JR   Z, RTypeBank2_DobBeginEnd
                LD   A, (RTypeBank2_AnchorsRemaining)
                OR   A
                RET  NZ
                LD   HL, #0040
                LD   (RTypeWorldBgVelocity), HL
                RET

RTypeBank2_DobBeginEnd:
                LD   A, RTYPE_DOB_ROOT_END
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #00C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_END_TIMER), HL
                RET

RTypeBank2_DobRootEnd:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_END_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ROOT_END_TIMER), HL
                LD   A, H
                OR   L
                JR   Z, .finish
                ; `$9ADE` ставит fixed-player exit latch на `$0010`.
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   A, #FF
                LD   (RTypeBank2_PlayerExitLatch), A
                RET
.finish:       LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                LD   (RTypeWorldBgVelocity), HL
                LD   A, 1
                LD   (RTypeBank2_BossDefeated), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank2_DobSpawnParts:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_RootIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank2_DobSpawnBack
                CALL RTypeBank2_DobSpawnBody
                CALL RTypeBank2_DobSpawnAnchors
                CALL RTypeBank2_DobSpawnTentacles
                LD   A, (RTypeBank2_RootIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, RTYPE_DOB_ROOT_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank2_DobSpawnBack:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_DOB_BACK
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #3810
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0328
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0128
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #44AC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #15
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #44AC
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank2_DobSpawnBody:
                CALL RTypeObjects_New
                RET  C
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_BodyIndex), A
                LD   A, RTYPE_OBJ_DOB_BODY
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #3818
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0358
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #44D2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #15
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   HL, #454E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER), HL
                LD   HL, #001E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_PALETTE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #44D2
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank2_DobSpawnAnchors:
                LD   HL, #4394
                LD   (RTypeBank2_RecordPointer), HL
                LD   B, 4
.next:         PUSH BC
                CALL RTypeBank2_DobSpawnAnchor
                POP  BC
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 6
                ADD  HL, DE
                LD   (RTypeBank2_RecordPointer), HL
                DJNZ .next
                RET

RTypeBank2_DobSpawnAnchor:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_DOB_ANCHOR
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #3821
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank2_RecordPointer)
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_PATH), DE
                LD   HL, #0280
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_ACTIVATE), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   L, A
                LD   H, 0
                LD   DE, #0900
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TIMEOUT), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank2_DobSpawnTentacles:
                LD   HL, #43AC
                LD   (RTypeBank2_RecordPointer), HL
                LD   HL, #FF90
                LD   (RTypeBank2_TentaclePriority), HL
                LD   B, #12
.next:         PUSH BC
                CALL RTypeBank2_DobSpawnTentacleBody
                POP  BC
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 10
                ADD  HL, DE
                LD   (RTypeBank2_RecordPointer), HL
                LD   HL, (RTypeBank2_TentaclePriority)
                INC  HL
                LD   (RTypeBank2_TentaclePriority), HL
                DJNZ .next
                JP   RTypeBank2_DobSpawnTentacleTip

RTypeBank2_DobSpawnTentacleBody:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_DOB_TENTACLE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, (RTypeBank2_TentaclePriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, (RTypeBank2_RecordPointer)
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIXED_DESCRIPTOR), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_START), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_POINTER), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_CLEANUP_TIMER), DE
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_INTRO_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIP), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #17
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #17
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank2_DobSpawnTentacleTip:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_DOB_TENTACLE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #FFA8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #0277
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #00BF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #4CC6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIXED_DESCRIPTOR), HL
                LD   HL, #4C76
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_START), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_POINTER), HL
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_INTRO_TIMER), HL
                LD   HL, #0068
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_CLEANUP_TIMER), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIP), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_A), HL
                LD   HL, #0080
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_B), HL
                LD   HL, #4460
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_PROJECTILE_SCRIPT), HL
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   A, L
                AND  #3F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #17
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #17
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #4CC6
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; ----------------------------------------------------------------------------
; `$9B26/$9B39`: задняя часть и общий in-place `$E7BE` для boss components.
; ----------------------------------------------------------------------------

RTypeBank2_AddBackgroundDelta:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldBgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                RET

RTypeBank2_UpdateDobBack:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_BACK_EXP_WAIT
                JP   Z, RTypeBank2_ComponentExplosionInit
                CP   RTYPE_DOB_BACK_EXPLODE
                JP   Z, RTypeBank2_ComponentExplosionUpdate
                CALL RTypeBank2_AddBackgroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                LD   A, H
                OR   L
                JR   Z, .cyclic
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   HL, #44AC
                JR   .descriptorReady
.cyclic:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                INC  HL
                LD   DE, #0180
                PUSH HL
                OR   A
                SBC  HL, DE
                POP  HL
                JR   C, .timerReady
                LD   HL, 0
.timerReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   DE, #00C0
                OR   A
                SBC  HL, DE
                LD   HL, #44AC
                JR   C, .descriptorReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                LD   DE, #00D0
                OR   A
                SBC  HL, DE
                LD   HL, #44A0
                JR   C, .descriptorReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                LD   DE, #0170
                OR   A
                SBC  HL, DE
                LD   HL, #44A6
                JR   C, .descriptorReady
                LD   HL, #44A0
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0120
                OR   A
                SBC  HL, DE
                JP   C, RTypeBank2_RemoveSingleResource
                LD   A, (RTypeBank2_BodyDestroyed)
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, RTYPE_DOB_BACK_EXP_WAIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank2_ComponentExplosionInit:
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                CP   RTYPE_OBJ_DOB_TENTACLE
                LD   A, RTYPE_DOB_BACK_EXPLODE
                JR   NZ, .stateReady
                LD   A, RTYPE_DOB_TENTACLE_EXPLODE
.stateReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #8530
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL

RTypeBank2_ComponentExplosionUpdate:
                ; `$E7D4` у boss debris/components использует foreground delta.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JP   Z, RTypeBank2_RemoveSingleResource
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER + 1), A
                RET

RTypeBank2_RemoveSingleResource:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; ----------------------------------------------------------------------------
; `$9B9B/$9C33/$9C70`: vulnerable central body и его intro/active анимации.
; ----------------------------------------------------------------------------

RTypeBank2_UpdateDobBody:
                CALL RTypeBank2_AddBackgroundDelta
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_BODY_INTRO
                JP   Z, RTypeBank2_DobBodyIntro
                CP   RTYPE_DOB_BODY_EMERGE
                JP   Z, RTypeBank2_DobBodyEmerge
                CP   RTYPE_DOB_BODY_ACTIVE
                JP   Z, RTypeBank2_DobBodyActive
                JP   RTypeBank2_DobBodyDeath

RTypeBank2_DobBodyIntro:
                LD   HL, #44D2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   DE, #0060
                PUSH HL
                OR   A
                SBC  HL, DE
                POP  HL
                CALL Z, RTypeBank2_DobBodyIntroExplosions
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #16
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #16
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_PALETTE), A
                LD   A, RTYPE_DOB_BODY_EMERGE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #003F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                RET

RTypeBank2_DobBodyEmerge:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                AND  #30
                SRL  A
                SRL  A
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #44DE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_DOB_BODY_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #00C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   HL, #001E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP), HL
                RET

RTypeBank2_DobBodyActive:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                DEC  HL
                LD   A, L
                AND  #7F
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                AND  #70
                SRL  A
                SRL  A
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #44F6
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_TIMER)
                OR   A
                JR   Z, .fire
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_TIMER), A
                LD   A, (FrameCounter)
                AND  4
                JR   NZ, .fire
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.fire:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                LD   DE, #0030
                OR   A
                SBC  HL, DE
                CALL Z, RTypeBank2_DobSpawnOrb
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0120
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, 1
                LD   (RTypeBank2_Defeated), A
                LD   A, RTYPE_OBJ_DOB_ROOT_DEFEATED
                CALL RTypeBank2_WriteRootByteOne
                JP   RTypeBank2_RemoveBody

; `$9D30…$9D9D`: тело уже получило foreground/background delta один раз в
; общем входе `$9B9B`. Death-handler намеренно прибавляет background delta
; второй раз: это не опечатка, а видимый quirk оригинального кода.
RTypeBank2_DobBodyDeath:
                CALL RTypeBank2_AddBackgroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   A, H
                OR   L
                JP   NZ, .checkSentinel

                ; Первый RNG выбирал звук `$50…$53`. TSFM в Unreal не
                ; эмулируется, но состояние генератора обязано измениться.
                CALL RTypeRng_Next
                CALL RTypeRng_Next
                LD   A, L
                AND  1
                OR   1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER + 1), A

                ; Шестибайтная ROM-запись: signed dx, signed dy, handler.
                ; Два RNG выше выполняются даже при полном object pool.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER)
                LD   (RTypeBank2_RecordPointer), HL
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank2_SpawnX), HL
                LD   HL, (RTypeBank2_RecordPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank2_SpawnY), HL
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank2_DeathHandler), DE

                ; Все death children имеют один EF00 priority/type. Это
                ; сохраняет исходный порядок равноприоритетных записей:
                ; `$E700` отличается только невидимым initializer-pass.
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTypeBank2_SpawnType), A
                LD   HL, #EF00
                LD   (RTypeBank2_SpawnPriority), HL
                LD   HL, #8506
                LD   (RTypeBank2_SpawnSequence), HL
                LD   A, 2
                LD   (RTypeBank2_SpawnTimer), A
                LD   HL, (RTypeBank2_DeathHandler)
                LD   DE, #E7BE
                OR   A
                SBC  HL, DE
                JR   NZ, .notE7BE
                LD   HL, #8530
                LD   (RTypeBank2_SpawnSequence), HL
                JR   .spawnDeathChild
.notE7BE:      LD   HL, (RTypeBank2_DeathHandler)
                LD   DE, #E817
                OR   A
                SBC  HL, DE
                JR   NZ, .spawnDeathChild
                LD   HL, #85FA
                LD   (RTypeBank2_SpawnSequence), HL
                LD   A, 1
                LD   (RTypeBank2_SpawnTimer), A

.spawnDeathChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_BodyIndex), A
                CALL RTypeObjects_StoreScratch
                XOR  A
                LD   (RTypeBank2_SpawnSucceeded), A
                CALL RTypeBank2_SpawnGenericExplosion
                JR   C, .restoreBody
                LD   A, 1
                LD   (RTypeBank2_SpawnSucceeded), A
                LD   HL, (RTypeBank2_DeathHandler)
                LD   DE, #E700
                OR   A
                SBC  HL, DE
                JR   NZ, .restoreBody
                ; `$E700` не рисует первый pass. Следующий pass включает
                ; terrain timer и затем использует общий `$E7B6` stream.
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_TERRAIN_TIMER), HL
                LD   HL, #452E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_PATH), HL
                CALL RTypeObjects_CommitCurrent
.restoreBody:  LD   A, (RTypeBank2_BodyIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, (RTypeBank2_SpawnSucceeded)
                OR   A
                JR   Z, .checkSentinel
                ; `$03A6` failure повторяет ту же ROM-запись. Только реально
                ; созданный child сдвигает cursor ровно на шесть байт.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER)
                LD   DE, 6
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER), HL

.checkSentinel:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                CP   #80
                RET  NZ
                LD   A, E
                OR   A
                RET  NZ
                JP   RTypeBank2_RemoveBody

; Этот вход позже вызывает weapon/collision layer при фатальном попадании.
; Он записывает linked root немедленно, чтобы ещё не пройденные `$FF9x`
; щупальца увидели body-dead в том же scheduler pass.
RTypeBank2_DobBodyBeginDeath:
                LD   A, RTYPE_DOB_BODY_DEATH
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_TIMER), A
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIMER), HL
                LD   HL, #454E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEATH_POINTER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP + 1), A
                LD   A, 1
                LD   (RTypeBank2_BodyDestroyed), A
                LD   A, RTYPE_OBJ_DOB_ROOT_BODY_DEAD
                JP   RTypeBank2_WriteRootByteOne

RTypeBank2_RemoveBody:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Четыре `$E7B6` на timer `$0060`; каждая координата потребляет отдельный RNG.
RTypeBank2_DobBodyIntroExplosions:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_BodyIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank2_BodyX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank2_BodyY), HL
                CALL RTypeObjects_StoreScratch
                LD   B, 4
.next:         PUSH BC
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                SUB  #10
                LD   E, A
                LD   D, 0
                BIT  7, E
                JR   Z, .xOffsetReady
                DEC  D
.xOffsetReady: LD   HL, (RTypeBank2_BodyX)
                ADD  HL, DE
                LD   (RTypeBank2_SpawnX), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                SUB  #10
                LD   E, A
                LD   D, 0
                BIT  7, E
                JR   Z, .yOffsetReady
                DEC  D
.yOffsetReady: LD   HL, (RTypeBank2_BodyY)
                ADD  HL, DE
                LD   (RTypeBank2_SpawnY), HL
                LD   A, RTYPE_OBJ_DOB_EXP_F280
                LD   (RTypeBank2_SpawnType), A
                LD   HL, #F280
                LD   (RTypeBank2_SpawnPriority), HL
                LD   HL, #8506
                LD   (RTypeBank2_SpawnSequence), HL
                LD   A, 2
                LD   (RTypeBank2_SpawnTimer), A
                CALL RTypeBank2_SpawnGenericExplosion
                POP  BC
                DJNZ .next
                LD   A, (RTypeBank2_BodyIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Общий constructor неизменяемого explosion stream. Параметры заранее лежат
; в bank-globals; allocation failure не захватывает resource, как `$03A6`.
RTypeBank2_SpawnGenericExplosion:
                CALL RTypeObjects_New
                RET  C
                LD   A, (RTypeBank2_SpawnType)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, (RTypeBank2_SpawnPriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank2_SpawnX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank2_SpawnY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTypeBank2_SpawnSequence)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (RTypeBank2_SpawnTimer)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                CALL RTypeObjects_CommitCurrent
                OR   A                            ; Carry=0: allocation succeeded
                RET

RTypeBank2_UpdateDobExplosion:
                JP   RTypeBank2_GenericExplosionUpdate

RTypeBank2_GenericExplosionUpdate:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JP   Z, RTypeBank2_RemoveSingleResource
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER + 1), A
                RET

; ----------------------------------------------------------------------------
; `$9D9E/$9E07/$9E78` и `$9EC0/$9F18`: mouth orb и equal-priority trails.
; ----------------------------------------------------------------------------

RTypeBank2_DobSpawnOrb:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_BodyIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -8
                ADD  HL, DE
                LD   (RTypeBank2_SpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#000C
                ADD  HL, DE
                LD   (RTypeBank2_SpawnY), HL
                LD   A, (RTypeBank2_BodyIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_DOB_ORB
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #F000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, (RTypeBank2_SpawnX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ORIGIN_X), HL
                LD   HL, (RTypeBank2_SpawnY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ORIGIN_Y), HL
                LD   HL, #44BA
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #3F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #3F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_TRAIL_TIMER), HL
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT), HL
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #44BA
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank2_BodyIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank2_UpdateDobOrb:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ORB_CURVE
                JR   Z, .curve
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_TRAIL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_TRAIL_TIMER), HL
                LD   A, L
                AND  3
                CALL Z, RTypeBank2_DobSpawnOrbTrail
                CALL RTypeBank2_DobOrbMoveXAndDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank2_DobOrbBeginCurve
.curve:        CALL RTypeBank2_DobOrbIntegrateY
                CALL RTypeBank2_DobOrbMoveXAndDescriptor
                CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank2_RemoveSingleResource

RTypeBank2_DobOrbMoveXAndDescriptor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                XOR  A
                JP   RTypeBank2_DobOrbDescriptor

; A=phase offset low byte (orb=0, trail=сохранённый `$9DD9` counter).
RTypeBank2_DobOrbDescriptor:
                LD   B, A
                LD   A, (FrameCounter)
                ADD  A, B
                AND  #0C
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #44BA
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank2_DobOrbBeginCurve:
                LD   HL, (RTypePlayerNativeY)
                LD   DE, #0104
                OR   A
                SBC  HL, DE
                LD   HL, #0020
                JR   NC, .accelerationReady
                LD   HL, (RTypePlayerNativeY)
                LD   DE, #00F2
                OR   A
                SBC  HL, DE
                LD   HL, 0
                JR   NC, .accelerationReady
                LD   HL, -#0020
.accelerationReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCELERATION), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                LD   A, RTYPE_DOB_ORB_CURVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank2_DobOrbIntegrateY:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER)
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                JR   NZ, .integrate
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCELERATION)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
.integrate:    LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                JP   RTypeProjectile_AddQ8Y

RTypeBank2_DobSpawnOrbTrail:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_OrbIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ORIGIN_X)
                LD   (RTypeBank2_SpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ORIGIN_Y)
                LD   (RTypeBank2_SpawnY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_TRAIL_TIMER)
                LD   (RTypeBank2_OrbTrailPhase), HL
                LD   A, (RTypeBank2_OrbIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_DOB_ORB_TRAIL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #F000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, (RTypeBank2_SpawnX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank2_SpawnY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank2_OrbTrailPhase)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_PHASE), HL
                LD   A, (RTypeBank2_OrbIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_PARENT), A
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT), HL
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                LD   A, #3F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #3F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #44BA
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank2_OrbIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank2_UpdateDobOrbTrail:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ORB_CURVE
                JR   NZ, .move
                CALL RTypeBank2_DobOrbIntegrateY
.move:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_PHASE)
                CALL RTypeBank2_DobOrbDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ORB_STRAIGHT
                JR   NZ, .bounds
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_STRAIGHT), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_PARENT)
                LD   (RTypeBank2_ReadObjectIndex), A
                LD   A, RTYPE_OBJ_DOB_ORB_ACCELERATION
                CALL RTypeBank2_ReadObjectWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCELERATION), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ORB_ACCEL_TIMER), A
                LD   A, RTYPE_DOB_ORB_CURVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank2_RemoveSingleResource

; ----------------------------------------------------------------------------
; `$A035…$A22D`: восемнадцать звеньев и прицельный наконечник щупальца.
; ----------------------------------------------------------------------------

RTypeBank2_UpdateDobTentacle:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_TENTACLE_CLEANUP
                JP   Z, RTypeBank2_DobTentacleCleanup
                CP   RTYPE_DOB_TENTACLE_EXP_WAIT
                JP   Z, RTypeBank2_ComponentExplosionInit
                CP   RTYPE_DOB_TENTACLE_EXPLODE
                JP   Z, RTypeBank2_ComponentExplosionUpdate

                ; Body handler `$9C70` может записать root `+$27` до прохода
                ; band `$FF90…$FFA8`. Поэтому cleanup проверяется до intro,
                ; стрельбы и движения и действует в том же VBlank.
                LD   A, (RTypeBank2_BodyDestroyed)
                OR   A
                JR   Z, .normal
                LD   A, RTYPE_DOB_TENTACLE_CLEANUP
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypeBank2_DobTentacleCleanup

.normal:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_TENTACLE_ACTIVE
                JR   NZ, .scrollAndDescribe
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIP)
                OR   A
                CALL NZ, RTypeBank2_DobTipFire

.scrollAndDescribe:
                CALL RTypeBank2_AddBackgroundDelta
                CALL RTypeBank2_DobTentacleDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_INTRO_TIMER)
                LD   A, H
                OR   L
                JR   Z, .move
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_INTRO_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                CALL RTypeBank2_DobTentacleLoadStep
                LD   A, RTYPE_DOB_TENTACLE_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIP)
                OR   A
                RET  Z
                JP   RTypeBank2_DobTipSetupFire

.move:         LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_STEP_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_STEP_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank2_DobTentacleLoadStep

; Обычное звено всегда возвращает исходный descriptor. Наконечник читает
; одно из 16 слов `$4CC6` по буквальному direction offset `$1D89 >> 1`.
RTypeBank2_DobTentacleDescriptor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_TIP)
                OR   A
                JR   NZ, .tip
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIXED_DESCRIPTOR)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor
.tip:          LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #4CC6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                JP   RTypeSprite_PrepareDescriptor

; Один motion record состоит из `(s16 vx, s16 source-vy, u16 control)`.
; В оригинале Y-скорость инвертируется, low 12 bits задают длительность,
; а bit15 возвращает cursor к начальному адресу stream.
RTypeBank2_DobTentacleLoadStep:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_POINTER)
                LD   (RTypeBank2_RecordPointer), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                LD   HL, (RTypeBank2_RecordPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                LD   DE, 0
                EX   DE, HL
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   H, D
                LD   L, E
                PUSH HL
                LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_STEP_TIMER), HL
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 6
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_POINTER), HL
                POP  HL
                BIT  7, H
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_START)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_SCRIPT_POINTER), HL
                RET

; `$F8A7` после 32 intro-pass: пока общий difficulty равен нулю, выбирается
; первая шестибайтная запись `$8E22`. RNG умножается на четыре до mask.
RTypeBank2_DobTipSetupFire:
                LD   HL, #8E22
                LD   (RTypeBank2_RecordPointer), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_A), DE
                LD   HL, (RTypeBank2_RecordPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_B), DE
                LD   HL, (RTypeBank2_RecordPointer)
                LD   DE, 4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_PROJECTILE_SCRIPT), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_A)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER), HL
                LD   A, (RTypeBank2_CheckpointFlag)
                OR   A
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_PROJECTILE_SCRIPT), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_PROJECTILE_SCRIPT + 1), A
                RET

; Локальная копия `$F63A`: equality с fire_a не сбрасывает counter; ветка
; `counter >= fire_b` сначала очищает его. Нулевой script запрещает allocation.
RTypeBank2_DobTipFire:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_A)
                OR   A
                SBC  HL, DE
                JR   Z, .trigger
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_B)
                OR   A
                SBC  HL, DE
                RET  C
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FIRE_COUNTER + 1), A
.trigger:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_PROJECTILE_SCRIPT)
                LD   A, H
                OR   L
                RET  Z
                JP   RTypeBank2_DobTipSpawnProjectile

; Наконечник имеет priority `$FFA8`, а создаваемый `$E601` — `$A000`.
; Его band в текущем кадре уже пройден, поэтому здесь нет immediate Q8 pass,
; в отличие от общего spawner для более ранних `$8010` источников.
RTypeBank2_DobTipSpawnProjectile:
                LD   (RTypeObjects_ProjectileVelocityTable), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_TentacleIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeDirection_Offset
                LD   (RTypeObjects_ProjectileDirection), A
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_ENEMY_PROJECTILE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #A000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #84AE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #56
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #56
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTypeObjects_ProjectileDirection)
                LD   E, A
                LD   D, 0
                LD   HL, (RTypeObjects_ProjectileVelocityTable)
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTYPE_PROJECTILE_COUNT)
                INC  HL
                LD   (RTYPE_PROJECTILE_COUNT), HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_PHASE), HL
                LD   HL, (FrameCounter)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BORN), HL
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank2_TentacleIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank2_DobTentacleCleanup:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_CLEANUP_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_CLEANUP_TIMER), HL
                LD   A, H
                OR   L
                JR   Z, .finishLink
                JP   RTypeBank2_AddBackgroundDelta
.finishLink:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                ; Звук не отправляется без TSFM, но `$A11B` всегда вызывает
                ; RNG и тем самым влияет на все последующие boss effects.
                CALL RTypeRng_Next
                LD   A, RTYPE_DOB_TENTACLE_EXP_WAIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

; ----------------------------------------------------------------------------
; `$E700/$E71C/$E75C`: EF00 debris с одноразовым вырезанием foreground.
; ----------------------------------------------------------------------------

RTypeBank2_UpdateDobDebris:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                JP   Z, RTypeBank2_GenericExplosionUpdate
                CP   1
                JR   NZ, .active
                ; Constructor `$E700` только ставит `$E71C` и возвращается;
                ; первая sprite frame появляется на следующем scheduler pass.
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.active:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_TERRAIN_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_TERRAIN_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank2_DobDebrisCutTerrain
                JP   RTypeBank2_GenericExplosionUpdate

RTypeBank2_DobDebrisCutTerrain:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#000C
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #000C
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeBank2_TerrainAddress), HL
.cell:         LD   HL, (RTypeBank2_TerrainAddress)
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   (HL), #A0
                INC  HL
                LD   (HL), #0F                    ; два attribute bytes сохранены
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_PATH)
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_PATH)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_PATH), HL
                LD   A, D
                CP   #80
                JR   NZ, .advance
                LD   A, E
                OR   A
                JR   NZ, .advance
                LD   HL, #FFFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_DEBRIS_TERRAIN_TIMER), HL
                RET
.advance:      LD   HL, (RTypeBank2_TerrainAddress)
                ; `$E748` складывает low/high bytes независимо: перенос из
                ; low byte намеренно не попадает в high byte.
                LD   A, L
                ADD  A, E
                LD   L, A
                LD   A, H
                ADD  A, D
                AND  #3F
                LD   H, A
                LD   (RTypeBank2_TerrainAddress), HL
                JR   .cell

; ----------------------------------------------------------------------------
; `$9F63/$9F84/$9FE9`: четыре невидимых arena anchors и terrain writer.
; ----------------------------------------------------------------------------

RTypeBank2_UpdateDobAnchor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ANCHOR_ERASE
                JP   Z, RTypeBank2_DobAnchorErase
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ANCHOR_WAIT
                JR   NZ, .active
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_ACTIVATE)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_ACTIVATE), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_DOB_ANCHOR_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.active:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TIMEOUT)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TIMEOUT), HL
                LD   A, H
                OR   L
                JP   Z, RTypeBank2_DobAnchorBeginErase
                LD   A, (RTypeBank2_BodyIndex)
                LD   (RTypeBank2_ReadObjectIndex), A
                LD   A, RTYPE_OBJ_DOB_HP
                CALL RTypeBank2_ReadObjectWord
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                RET  NC                           ; HP >= $10: ещё не half-dead
                JP   RTypeBank2_DobAnchorBeginErase

RTypeBank2_DobAnchorBeginErase:
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TILE), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank2_AnchorIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTypeBank2_SpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTypeBank2_SpawnY), HL
                LD   A, (RTypeBank2_AnchorIndex)
                CALL RTypeObjects_StoreScratch
                LD   A, RTYPE_OBJ_DOB_EXP_FE00
                LD   (RTypeBank2_SpawnType), A
                LD   HL, #FE00
                LD   (RTypeBank2_SpawnPriority), HL
                LD   HL, #8506
                LD   (RTypeBank2_SpawnSequence), HL
                LD   A, 2
                LD   (RTypeBank2_SpawnTimer), A
                CALL RTypeBank2_SpawnGenericExplosion
                LD   A, (RTypeBank2_AnchorIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, RTYPE_DOB_ANCHOR_ERASE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank2_DobAnchorErase:
                LD   A, (FrameCounter)
                INC  A
                AND  1
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TILE)
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   (HL), #A0
                INC  HL
                LD   (HL), #0F                      ; attribute word не трогаем
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_PATH)
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_PATH)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_PATH), HL
                LD   A, D
                CP   #80
                JR   NZ, .advance
                LD   A, E
                OR   A
                JR   NZ, .advance
                LD   A, (RTypeBank2_AnchorsRemaining)
                OR   A
                JR   Z, .remove
                DEC  A
                LD   (RTypeBank2_AnchorsRemaining), A
                LD   B, A
                LD   A, RTYPE_OBJ_DOB_ROOT_ANCHORS
                CALL RTypeBank2_WriteRootByteB
.remove:       XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TILE)
                LD   A, L
                ADD  A, E
                LD   L, A
                LD   A, H
                ADD  A, D
                AND  #3F
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_ANCHOR_TILE), HL
                RET

; ----------------------------------------------------------------------------
; Доступ к связанным физическим records и малые resident-подобные globals.
; ----------------------------------------------------------------------------

; A=offset, индекс лежит в RTypeBank2_ReadObjectIndex; выход HL=word.
; Scratch текущего handler не затрагивается, меняется только slot3 mapping.
RTypeBank2_ReadObjectWord:
                LD   E, A
                LD   D, 0
                PUSH DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeBank2_ReadObjectIndex)
                CALL RTypeObjects_RecordAddress
                POP  DE
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                EX   DE, HL
                RET

RTypeBank2_WriteRootByteOne:
                LD   B, 1
RTypeBank2_WriteRootByteB:
                LD   (RTypeBank2_WriteOffset), A
                LD   A, B
                LD   (RTypeBank2_WriteValue), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeBank2_RootIndex)
                CALL RTypeObjects_RecordAddress
                LD   A, (RTypeBank2_WriteOffset)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   A, (RTypeBank2_WriteValue)
                LD   (HL), A
                RET

; Эти значения не заменяют поля объектов: они являются связями между slots
; и временными параметрами nested allocation, при котором общий scratch
; неизбежно занят создаваемой записью.
RTypeBank2_RootIndex:        DEFB 0
RTypeBank2_BodyIndex:        DEFB 0
RTypeBank2_AnchorIndex:      DEFB 0
RTypeBank2_TentacleIndex:    DEFB 0
RTypeBank2_OrbIndex:         DEFB 0
RTypeBank2_ReadObjectIndex:  DEFB 0
RTypeBank2_Defeated:         DEFB 0
RTypeBank2_BodyDestroyed:    DEFB 0
RTypeBank2_AnchorsRemaining: DEFB 0
RTypeBank2_PlayerExitLatch:  DEFB 0
RTypeBank2_BossDefeated:     DEFB 0
RTypeBank2_CheckpointFlag:   DEFB 0
RTypeBank2_SpawnType:        DEFB 0
RTypeBank2_SpawnTimer:       DEFB 0
RTypeBank2_SpawnSucceeded:   DEFB 0
RTypeBank2_WriteOffset:      DEFB 0
RTypeBank2_WriteValue:       DEFB 0
RTypeBank2_RecordPointer:    DEFW 0
RTypeBank2_TentaclePriority: DEFW 0
RTypeBank2_SpawnX:           DEFW 0
RTypeBank2_SpawnY:           DEFW 0
RTypeBank2_SpawnPriority:    DEFW 0
RTypeBank2_SpawnSequence:    DEFW 0
RTypeBank2_BodyX:            DEFW 0
RTypeBank2_BodyY:            DEFW 0
RTypeBank2_OrbTrailPhase:    DEFW 0
RTypeBank2_DeathHandler:     DEFW 0
RTypeBank2_TerrainAddress:   DEFW 0
