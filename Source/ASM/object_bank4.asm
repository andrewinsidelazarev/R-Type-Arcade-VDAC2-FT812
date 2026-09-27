; =============================================================================
; R-Type World: поздний boss Stage 7 `$B7FB…$C0A8`, page #0D / slot2.
;
; Файл сохранён в UTF-8. Комментарии намеренно описывают не только назначение,
; но и scheduler/allocator границы: восемь частей создаются раньше root, root
; получает последний FIFO slot и поэтому является newest-first `$8010` записью.
; =============================================================================

RTypeBank4_InitBossB7FB:
                XOR  A
                LD   (RTypeBank4_PartCount), A
                LD   HL, #02D0
                LD   (RTypeBank4_SegmentX), HL
                LD   HL, #03C0
                LD   (RTypeBank4_SegmentThreshold), HL
                LD   B, 5
.segment:      PUSH BC
                CALL RTypeBank4_SpawnSegment
                LD   HL, (RTypeBank4_SegmentX)
                LD   DE, #0040
                ADD  HL, DE
                LD   (RTypeBank4_SegmentX), HL
                LD   HL, (RTypeBank4_SegmentThreshold)
                LD   DE, -#0020
                ADD  HL, DE
                LD   (RTypeBank4_SegmentThreshold), HL
                POP  BC
                DJNZ .segment
                CALL RTypeBank4_SpawnRandomSpawner
                CALL RTypeBank4_SpawnMissileSpawner
                CALL RTypeBank4_SpawnCore

                ; Активный Python выделяет root после вложенных pending.append;
                ; поэтому root slot берётся последним, затем восемь links патчатся.
                CALL RTypeObjects_New
                RET  C
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_RootIndex), A
                LD   A, RTYPE_OBJ_B7FB_ROOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_DEFEATED), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeObjects_CommitCurrent
                CALL RTypeBank4_PatchRootLinks
                LD   A, (RTypeBank4_RootIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_SavePartIndex:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   C, A
                LD   A, (RTypeBank4_PartCount)
                LD   E, A
                LD   D, 0
                LD   HL, RTypeBank4_PartIndices
                ADD  HL, DE
                LD   (HL), C
                INC  A
                LD   (RTypeBank4_PartCount), A
                RET

RTypeBank4_PatchRootLinks:
                LD   A, (RTypeBank4_PartCount)
                LD   B, A
                LD   HL, RTypeBank4_PartIndices
.next:         LD   A, B
                OR   A
                RET  Z
                LD   A, (HL)
                INC  HL
                PUSH HL
                CALL RTypeObjects_RecordAddress
                LD   DE, #0020                   ; у всех восьми parts root=+$20
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeBank4_RootIndex)
                LD   (HL), A
                POP  HL
                DJNZ .next
                RET

RTypeBank4_SpawnSegment:
                CALL RTypeObjects_New
                RET  C
                CALL RTypeBank4_SavePartIndex
                LD   A, RTYPE_OBJ_B7FB_SEGMENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank4_SegmentX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0160
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #60E6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, (RTypeBank4_SegmentThreshold)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_THRESHOLD), HL
                LD   A, #2F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #60E6
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank4_SpawnRandomSpawner:
                CALL RTypeObjects_New
                RET  C
                CALL RTypeBank4_SavePartIndex
                LD   A, RTYPE_OBJ_B7FB_RANDOM_SPAWNER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #611E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_X_POINTER), HL
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_CADENCE), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RELOAD), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RAMP), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank4_SpawnMissileSpawner:
                CALL RTypeObjects_New
                RET  C
                CALL RTypeBank4_SavePartIndex
                LD   A, RTYPE_OBJ_B7FB_MISSILE_SPAWNER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #627C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank4_SpawnCore:
                CALL RTypeObjects_New
                RET  C
                CALL RTypeBank4_SavePartIndex
                LD   A, RTYPE_OBJ_B7FB_CORE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02E8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0110
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #63E6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, #017F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE), HL
                LD   HL, #0055
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_HP), HL
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_PALETTE), A
                LD   A, #54
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #54
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #63E6
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; Root timer открывает 128 terrain cells на `$0300`; natural timeout `$1120`
; и core fatal flag сходятся в один `$00C0` exit countdown.
RTypeBank4_UpdateBossB7FBRoot:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_B7_ROOT_EXIT
                JR   Z, .exit
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER), HL
                LD   DE, #0300
                OR   A
                SBC  HL, DE
                CALL Z, RTypeBank4_OpenTerrain
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER)
                LD   DE, #1120
                OR   A
                SBC  HL, DE
                JR   C, .checkExit
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_DEFEATED), A
.checkExit:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_TIMER)
                LD   DE, #1160
                OR   A
                SBC  HL, DE
                JR   Z, .beginExit
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_DEFEATED)
                OR   A
                RET  Z
.beginExit:    LD   A, RTYPE_B7_ROOT_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #00C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_EXIT_TIMER), HL
                RET
.exit:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_ROOT_EXIT_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_OpenTerrain:
                LD   HL, #1002
                LD   B, #80
.cell:         LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                INC  HL
                INC  HL
                LD   A, (HL)
                OR   #80
                LD   (HL), A
                INC  HL
                INC  HL
                LD   A, H
                AND  #3F
                LD   H, A
                DJNZ .cell
                RET

; Carry=1, если root уже удалён либо defeated byte ненулевой.
RTypeBank4_RootDefeated:
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_B7FB_ROOT
                JR   NZ, .yes
                LD   DE, RTYPE_OBJ_B7_ROOT_DEFEATED
                ADD  HL, DE
                LD   A, (HL)
                OR   A
                JR   NZ, .yes
                OR   A
                RET
.yes:          SCF
                RET

RTypeBank4_UpdateBossB7FBSegment:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_TIMER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_THRESHOLD)
                OR   A
                SBC  HL, DE
                LD   (RTypeBank4_SegmentDelta), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_REVERSE)
                OR   A
                JR   NZ, .reverseDescriptor
                BIT  7, H
                LD   HL, #60E6
                JR   NZ, .descriptorReady
                LD   HL, (RTypeBank4_SegmentDelta)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                LD   HL, #60F2
                JR   C, .descriptorReady
                LD   HL, (RTypeBank4_SegmentDelta)
                LD   DE, #0020
                OR   A
                SBC  HL, DE
                LD   HL, #60FE
                JR   C, .descriptorReady
                LD   HL, #610A
                JR   .descriptorReady
.reverseDescriptor:
                LD   HL, (RTypeBank4_SegmentDelta)
                ; Python-oracle считает `timer-threshold` знаковым числом.
                ; После включения retreat timer снова равен нулю, поэтому до
                ; достижения threshold отрицательная delta обязана держать
                ; первый reverse-кадр `$610A`, а не проваливаться в `$60E6`.
                BIT  7, H
                LD   HL, #610A
                JR   NZ, .descriptorReady
                LD   HL, (RTypeBank4_SegmentDelta)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                LD   HL, #610A
                JR   C, .descriptorReady
                LD   HL, (RTypeBank4_SegmentDelta)
                LD   DE, #0020
                OR   A
                SBC  HL, DE
                LD   HL, #60FE
                JR   C, .descriptorReady
                LD   HL, (RTypeBank4_SegmentDelta)
                LD   DE, #0030
                OR   A
                SBC  HL, DE
                LD   HL, #60F2
                JR   C, .descriptorReady
                LD   HL, #60E6
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_ROOT)
                CALL RTypeBank4_RootDefeated
                JR   NC, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_REVERSE)
                OR   A
                JR   NZ, .bounds
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_REVERSE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_TIMER + 1), A
.bounds:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_REVERSE)
                OR   A
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0120
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank4_RemoveSingle

RTypeBank4_DamageBossB7FBSegment:
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_DAMAGE)
                ADD  A, B
                JR   C, .clamp
                CP   #A0
                JR   C, .store
.clamp:        LD   A, #A0
.store:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_SEGMENT_DAMAGE), A
                RET

RTypeBank4_UpdateBossB7FBRandomSpawner:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_ROOT)
                CALL RTypeBank4_RootDefeated
                JP   C, RTypeBank4_ClearCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_TIMER), HL
                LD   DE, #0360
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RAMP)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RAMP), HL
                LD   A, H
                OR   L
                JR   NZ, .reload
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RAMP), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_CADENCE)
                LD   A, H
                OR   A
                JR   NZ, .decrementCadence
                LD   A, L
                CP   9
                JR   C, .reload
.decrementCadence:
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_CADENCE), HL
.reload:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RELOAD)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RELOAD), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_CADENCE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_RELOAD), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  #3E
                LD   E, A
                LD   D, 0
                LD   HL, #612C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank4_RandomHandler), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_X_POINTER)
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank4_RandomX), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_X_POINTER)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_X_POINTER), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                CP   #80
                JR   NZ, .velocity
                LD   A, E
                OR   A
                JR   NZ, .velocity
                LD   HL, #611E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_X_POINTER), HL
.velocity:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_CADENCE)
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; cadence*$10
                LD   DE, -#0400
                ADD  HL, DE                     ; `-(0400-cadence*10)`
                LD   (RTypeBank4_RandomVelocity), HL
                JP   RTypeBank4_SpawnRandomChild

RTypeBank4_SpawnRandomChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank4_ConfigureRandomChild
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_B7FB_RANDOM_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank4_RandomX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0168
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank4_RandomVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, (RTypeBank4_RandomDescriptor)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, (RTypeBank4_RootIndexFromParent)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_ROOT), A
                LD   A, (RTypeBank4_RandomAnimated)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_ANIMATED), A
                LD   A, (RTypeBank4_RandomHP)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_HP), A
                LD   A, (RTypeBank4_RandomResource)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank4_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_ConfigureRandomChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_RANDOM_ROOT)
                LD   (RTypeBank4_RootIndexFromParent), A
                XOR  A
                LD   (RTypeBank4_RandomAnimated), A
                LD   A, 1
                LD   (RTypeBank4_RandomHP), A
                LD   A, #5F
                LD   (RTypeBank4_RandomResource), A
                LD   HL, #616C
                LD   (RTypeBank4_RandomDescriptor), HL
                LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BB72
                OR   A
                SBC  HL, DE
                JR   NZ, .bb7e
                LD   HL, #6178
                JP   .storeDescriptor
.bb7e:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BB7E
                OR   A
                SBC  HL, DE
                JR   NZ, .bb8a
                LD   HL, #6184
                JP   .storeDescriptor
.bb8a:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BB8A
                OR   A
                SBC  HL, DE
                JR   NZ, .bb96
                LD   HL, #6190
                JP   .storeDescriptor
.bb96:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BB96
                OR   A
                SBC  HL, DE
                JR   NZ, .bba2
                LD   HL, #619C
                JP   .storeDescriptor
.bba2:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BBA2
                OR   A
                SBC  HL, DE
                JR   NZ, .bbae
                LD   HL, #61A8
                JP   .storeDescriptor
.bbae:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BBAE
                OR   A
                SBC  HL, DE
                JR   NZ, .bbc3
                LD   A, #0C
                LD   (RTypeBank4_RandomHP), A
                LD   HL, #61B4
                JR   .storeDescriptor
.bbc3:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BBC3
                OR   A
                SBC  HL, DE
                JR   NZ, .bc08
                LD   A, #0F
                LD   (RTypeBank4_RandomResource), A
                LD   HL, #61C0
                JR   .storeDescriptor
.bc08:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BC08
                OR   A
                SBC  HL, DE
                JR   NZ, .bc31
                LD   A, #44
                LD   (RTypeBank4_RandomResource), A
                LD   A, 1
                LD   (RTypeBank4_RandomAnimated), A
                LD   HL, #61CC
                JR   .storeDescriptor
.bc31:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BC31
                OR   A
                SBC  HL, DE
                JR   NZ, .bc63
                LD   A, #0C
                LD   (RTypeBank4_RandomResource), A
                LD   HL, #622C
                JR   .randomFlip
.bc63:         LD   HL, (RTypeBank4_RandomHandler)
                LD   DE, #BC63
                OR   A
                SBC  HL, DE
                JR   NZ, .bb40Flip
                LD   A, #2E
                LD   (RTypeBank4_RandomResource), A
                LD   HL, #6238
                JR   .randomFlip
.bb40Flip:     LD   HL, #616C
.randomFlip:   LD   (RTypeBank4_RandomDescriptor), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  2
                RET  Z
                LD   HL, (RTypeBank4_RandomDescriptor)
                LD   DE, 6
                ADD  HL, DE
.storeDescriptor:
                LD   (RTypeBank4_RandomDescriptor), HL
                RET

RTypeBank4_UpdateBossB7FBRandomChild:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_ANIMATED)
                OR   A
                JR   Z, .lifetime
                LD   A, (FrameCounter)
                AND  #3C
                LD   B, A
                ADD  A, A
                ADD  A, B
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #61CC
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
.lifetime:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_ROOT)
                CALL RTypeBank4_RootDefeated
                JP   C, RTypeBank4_RemoveSingle
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #00B0
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank4_RemoveSingle

RTypeBank4_DamageBossB7FBRandomChild:
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_HP)
                CP   B
                JP   C, RTypeBank4_ConvertCurrentToE7BE
                JP   Z, RTypeBank4_ConvertCurrentToE7BE
                SUB  B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_HP), A
                RET

RTypeBank4_UpdateBossB7FBMissileSpawner:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_ROOT)
                CALL RTypeBank4_RootDefeated
                JP   C, RTypeBank4_ClearCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_TIMER), HL
                LD   DE, #0360
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_TIMER)
                LD   A, L
                AND  #7F
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER)
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank4_MissileX), DE
                ; `ReadWord` возвращает DE, но HL оставляет mapped-адресом
                ; второго byte в slot3. Следующий ROM cursor поэтому берём из
                ; записи spawner заново, а не инкрементируем испорченный HL.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER), HL
                LD   A, D
                CP   #80
                JR   NZ, .spawn
                LD   A, E
                OR   A                           ; sentinel только exact `$8000`
                JR   Z, .checkWrap
.spawn:
                CALL RTypeBank4_SpawnMissile
.checkWrap:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                RET  NZ
                LD   HL, #627C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_POINTER), HL
                RET

RTypeBank4_SpawnMissile:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ParentIndex), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MSPAWNER_ROOT)
                LD   (RTypeBank4_RootIndexFromParent), A
                ; StoreScratch принимает индекс именно в A. После чтения root
                ; здесь уже был root slot, поэтому без восстановления A новый
                ; missile незаметно сохранял spawner scratch поверх root.
                LD   A, (RTypeBank4_ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_B7FB_MISSILE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank4_MissileX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0090
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #62FE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, #9010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), HL
                LD   A, (RTypeBank4_RootIndexFromParent)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_ROOT), A
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_HP), HL
                LD   A, #21
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #21
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #62FE
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank4_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_UpdateBossB7FBMissile:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_ROOT)
                CALL RTypeBank4_RootDefeated
                JP   C, RTypeBank4_RemoveSingle
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER)
                LD   DE, #00C0
                OR   A
                SBC  HL, DE
                JR   NC, .up
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER)
                LD   DE, #0040
                OR   A
                SBC  HL, DE
                JR   NC, .fire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                JR   .fire
.up:           LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
.fire:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER)
                LD   DE, #0060
                OR   A
                SBC  HL, DE
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER)
                LD   DE, #00A0
                OR   A
                SBC  HL, DE
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #625C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_TIMER), HL
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                RET  NZ
                JP   RTypeBank4_RemoveSingle

RTypeBank4_DamageBossB7FBMissile:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_HP)
                OR   A
                SBC  HL, DE
                JP   C, RTypeBank4_ConvertCurrentToE7BE
                LD   A, H
                OR   L
                JP   Z, RTypeBank4_ConvertCurrentToE7BE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_HP), HL
                RET

RTypeBank4_UpdateBossB7FBCore:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_B7_CORE_EXPLODING
                JP   Z, RTypeBank4_UpdateCoreExplosion
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_TIMER), HL
                LD   DE, #0500
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE)
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                JR   C, .advancePhase
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_ROOT)
                CALL RTypeBank4_RootDefeated
                JP   C, RTypeBank4_RemoveCore
.advancePhase: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE), HL
                LD   DE, #0180
                OR   A
                SBC  HL, DE
                JR   C, .under180
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE), HL
                CALL RTypeBank4_SpawnCoreChild
.under180:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE)
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                RET  NC
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE)
                LD   A, L
                AND  #F0
                SRL  A
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #631A
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                CALL RTypeProjectile_AddQ8X
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_PHASE)
                LD   A, L
                AND  #F8
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #633A
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_TIMER)
                OR   A
                RET  Z
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_TIMER), A
                LD   A, (FrameCounter)
                AND  1
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                RET

RTypeBank4_DamageBossB7FBCore:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_HP)
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_HP), HL
                LD   A, 5
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_TIMER), A
                JR   C, .fatal
                LD   A, H
                OR   L
                RET  NZ
.fatal:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_ROOT)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_B7_ROOT_DEFEATED
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   (HL), 1
                LD   A, RTYPE_B7_CORE_EXPLODING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0080
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_TIMER), HL
                JP   RTypeBank4_ClearTerrainAttributes

RTypeBank4_ClearTerrainAttributes:
                LD   HL, #1002
                LD   BC, #0800
.cell:         LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                INC  HL
                INC  HL
                LD   A, (HL)
                AND  #0F
                LD   (HL), A
                INC  HL
                XOR  A
                LD   (HL), A
                INC  HL
                ; После high byte attribute указатель уже стоит на `cell+3`;
                ; единственный INC переводит его на code следующей cell (+4).
                LD   A, H
                AND  #3F
                LD   H, A
                DEC  BC
                LD   A, B
                OR   C
                JR   NZ, .cell
                RET

RTypeBank4_UpdateCoreExplosion:
                LD   A, (FrameCounter)
                AND  3
                CALL Z, RTypeBank4_SpawnCoreExplosion
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank4_RemoveCore

RTypeBank4_SpawnCoreExplosion:
                CALL RTypeRng_Next
                LD   A, H
                AND  1
                LD   D, A
                LD   E, L
                LD   HL, #0140
                ADD  HL, DE
                LD   (RTypeBank4_ExplosionX), HL
                CALL RTypeRng_Next
                LD   A, L
                LD   B, A
                AND  #7F
                ADD  A, #80
                LD   L, A
                LD   H, 0
                BIT  7, B
                JR   Z, .yReady
                LD   DE, #00A0
                ADD  HL, DE
.yReady:       LD   (RTypeBank4_ExplosionY), HL
                BIT  6, B
                LD   A, 0                         ; `$E7B6`
                JR   Z, .effectReady
                INC  A                           ; `$E817`
.effectReady:  LD   (RTypeBank4_ExplosionEffect), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank4_ExplosionX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank4_ExplosionY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #8506
                LD   B, 2
                LD   A, (RTypeBank4_ExplosionEffect)
                OR   A
                JR   Z, .sequenceReady
                LD   HL, #85FA
                LD   B, 1
.sequenceReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                LD   A, B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), A
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank4_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_SpawnCoreChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0030
                ADD  HL, DE
                LD   (RTypeBank4_CoreChildX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                LD   (RTypeBank4_CoreChildY), HL
                ; Как и все allocator helpers, сохраняем владеющий core slot,
                ; а не случайное A, оставшееся после предыдущих вычислений.
                LD   A, (RTypeBank4_ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeRng_Next
                LD   A, L
                AND  6
                LD   E, A
                LD   D, 0
                LD   HL, #6312
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank4_CoreChildDescriptor), DE
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_B7FB_CORE_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank4_CoreChildX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank4_CoreChildY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank4_CoreChildDescriptor)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, #A7FC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   A, #5F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #5F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank4_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_UpdateBossB7FBCoreChild:
                CALL RTypeObjects_ScriptedMotion
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_B7_CORE_CHILD_OUT
                JR   NZ, RTypeBank4_RemoveSingle
                LD   A, RTYPE_B7_CORE_CHILD_RETURN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                RET

RTypeBank4_RemoveCore:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_PALETTE)
                CALL RTypeResources_Release
                JR   RTypeBank4_ClearCurrent

RTypeBank4_RemoveSingle:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
RTypeBank4_ClearCurrent:
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_ConvertCurrentToE7BE:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #8530
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL
                RET

; `$FB10`: пройти zero-terminated таблицу `ES:$945C` по 6 bytes. В ROM это
; восемнадцать, а не шесть, объектов: `(timeline pointer,Y,resource type)`.
; Все получают literal priority `$FF70`, X=`$0120` и впервые исполняются
; только после возврата event dispatcher-а, как записи allocator `$03A6`.
RTypeBank4_InitFinalStreamFB10:
                LD   HL, #945C
.next:         LD   (RTypeBank4_FBTable), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                RET  Z
                LD   (RTypeBank4_FBStream), DE

                LD   HL, (RTypeBank4_FBTable)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank4_FBY), DE
                LD   HL, (RTypeBank4_FBTable)
                LD   DE, 4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   A, E
                LD   (RTypeBank4_FBResource), A

                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FINAL_STREAM_FB53
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #FF70
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0120
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank4_FBY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank4_FBStream)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_ELAPSED), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_ELAPSED + 1), A
                LD   A, (RTypeBank4_FBResource)
                PUSH AF
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                POP  AF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTypeBank4_FBStream)
                LD   DE, 6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent

                LD   HL, (RTypeBank4_FBTable)
                LD   DE, 6
                ADD  HL, DE
                JR   .next

; `$FB53`: timeline хранит cumulative threshold в следующей записи. Поэтому
; сначала сравнивается `[stream+8]`, затем при достижении порога pointer
; сдвигается ровно на одну 8-byte запись; текущие `vx,vy,descriptor` лежат
; в `+2,+4,+6`. Velocities — signed Q8 и используют общий точный интегратор.
RTypeBank4_UpdateFinalStreamFB53:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_ELAPSED)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_ELAPSED), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM)
                LD   DE, 8
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_ELAPSED)
                OR   A
                SBC  HL, DE
                JR   C, .recordReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM)
                LD   DE, 8
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM), HL

.recordReady:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                CALL RTypeProjectile_AddQ8X
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM)
                LD   DE, 4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FB_STREAM)
                LD   DE, 6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02E0
                OR   A
                SBC  HL, DE
                JR   NC, .remove
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                RET  Z
.remove:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$EE0B`: невидимый record с priority `$0200`. Инициализатор исходника сразу
; останавливает все четыре X/Y интегратора и обнуляет их accumulators; timer 8
; начинает уменьшаться только когда foreground strip-writer догнал target.
RTypeBank4_InitFinalResetEE0B:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FINAL_RESET_EE3C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                CALL RTypeBank4_FinalClearAllScroll
                JP   RTypeObjects_CommitCurrent

; `$EE3C`: после восьми спокойных pass игра возвращается к началу World. На
; оригинальной плате event pointer ставится прямо на `$B9B3`/progress `$06C0`.
; Target-runtime сначала атомарно выбирает Stage 1 (включая SD-подгрузку),
; затем выставляет тот же progression; начальные resource events исполняются
; обычным one-event-per-VBlank диспетчером и поэтому не теряются.
RTypeBank4_UpdateFinalResetEE3C:
                LD   A, (RTypeWorldFgTracker)
                LD   B, A
                LD   A, (RTypeWorldFgTarget)
                CP   B
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ

                LD   A, 1
                CALL RTypeStage_LoadAndSelect
                XOR  A
                LD   (RTypeWorldProgressQ8), A
                LD   A, #C0
                LD   (RTypeWorldProgressQ8 + 1), A
                LD   A, #06
                LD   (RTypeWorldProgressQ8 + 2), A
                LD   A, (RTypeFinalLoopCount)
                INC  A
                LD   (RTypeFinalLoopCount), A
                XOR  A
                LD   (RTypeFinalStageLatch), A
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                XOR  A
                LD   (RTYPE_CLEANUP_ACTIVE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$EEAB`: event создаёт только priority `$0100` record. Настоящий `$EEB5`
; выполняется scheduler-ом на следующем VBlank, поэтому здесь не меняются ни
; scroll, ни palette, ни cleanup latch.
RTypeBank4_InitFinalSequenceEEAB:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FINAL_SEQUENCE_EEB5
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypeObjects_CommitCurrent

; `$EEB5…$F012`: финальный автомат Stage 8. Исходные `$E883/$ED93` — задания
; task-очереди по подготовке VRAM. В target-порте те же карты и palette types
; уже находятся в 4-МБ RAM и передаются FT812 DMA, поэтому их 64-frame cadence
; и общий `$0560` lifetime сохраняются, а повторное CPU-копирование не нужно.
RTypeBank4_UpdateFinalSequenceEEB5:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                JP   Z, .bootstrap
                CP   1
                JP   Z, .waitStrips
                CP   2
                JP   Z, .timeline
                CP   3
                JP   Z, .firstFadeWait
                CP   4
                JP   Z, .secondFadeWait
                CP   5
                JP   Z, .playerExitWait
                JP   .playerExitFinish

.bootstrap:    LD   A, #FF
                LD   (RTypeFinalStageLatch), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, #FF
                LD   (RTYPE_CLEANUP_ACTIVE), A
                ; `$2EC4=$F000`, остальные X accumulators/velocities нулевые.
                XOR  A
                LD   (RTypeWorldFgScrollQ8), A
                LD   (RTypeWorldFgScrollQ8 + 1), A
                LD   (RTypeWorldFgScrollQ8 + 2), A
                LD   (RTypeWorldBgScrollQ8), A
                LD   A, #F0
                LD   (RTypeWorldBgScrollQ8 + 1), A
                XOR  A
                LD   (RTypeWorldBgScrollQ8 + 2), A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   HL, #88E8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TABLE), HL
                LD   HL, #0030
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_CADENCE), HL
                LD   HL, #0560
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_LIFETIME), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.waitStrips:   LD   A, (RTypeWorldFgTracker)
                LD   B, A
                LD   A, (RTypeWorldFgTarget)
                CP   B
                RET  NZ
                ; `$2EF0=$0080` — второй аппаратный scroll-channel. В нашей
                ; раздельной модели это foreground Y velocity.
                LD   HL, #0080
                LD   (RTypeWorldFgYVelocity), HL
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.timeline:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_CADENCE)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_CADENCE), HL
                LD   A, H
                OR   L
                JR   NZ, .lifetime
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_CADENCE), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TABLE)
                PUSH HL
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TABLE), HL
                POP  HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   NZ, .lifetime              ; nonzero `$ED93` task уже в RAM
                LD   HL, #FFFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_CADENCE), HL

.lifetime:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_LIFETIME)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_LIFETIME), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTypeWorldBgScrollQ8), A
                LD   (RTypeWorldBgScrollQ8 + 1), A
                LD   (RTypeWorldBgScrollQ8 + 2), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   A, (RTypeFinalLoopCount)
                OR   A
                JR   NZ, .playerExitBegin

                ; Первый круг: `$54E4(BX=1,CX=$10,DX=0)`, 128 pass,
                ; затем общий `$5596` и ещё 64 pass palette convergence.
                LD   A, #10
                LD   C, 1
                LD   DE, 0
                CALL RTypePalette_SetTile
                LD   HL, #0080
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, 3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.firstFadeWait:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                ; Любой handler кроме `$5526` выбирает arena-ветвь setter-а.
                CALL RTypeBank4_InitPaletteControl
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.secondFadeWait:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

.playerExitBegin:
                LD   HL, #0120
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, 5
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.playerExitWait:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FINAL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                LD   A, #FF
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, #22
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, 6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

.playerExitFinish:
                LD   A, 2
                LD   (RTypeWorldTransition), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Общий эквивалент нулевых `$2EC0…$2ECE/$2EEC/$2EF4`: обе координаты X/Y и
; все четыре Q8 velocity очищаются одним bank-local вызовом.
RTypeBank4_FinalClearAllScroll:
                XOR  A
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
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                RET

; =============================================================================
; Поздние контроллеры `$A22E/$B0E1/$B1D8/$C0A9`.
;
; В Python-слое эти handlers были помечены delegated: их фактическим эталоном
; остаётся полный V30 runtime. Здесь state и thresholds перенесены из World ROM,
; а большие таблицы заранее сгенерированы в конце bank #0D. Редкие изменения
; terrain выполняются блоками; в основном 57-Hz цикле нет разбора ROM-структур.
; =============================================================================

RTYPE_CTRL_A22E              EQU 1
RTYPE_CTRL_B0E1              EQU 2
RTYPE_CTRL_C0A9              EQU 3

RTYPE_A22_NORMAL             EQU 0
RTYPE_A22_PATTERN_UP         EQU 1
RTYPE_A22_PATTERN_HOLD       EQU 2
RTYPE_A22_PATTERN_DOWN       EQU 3
RTYPE_A22_FLASH              EQU 4
RTYPE_A22_EXIT               EQU 5

RTYPE_B0_ACTIVE              EQU 0
RTYPE_B0_EXIT                EQU 1

RTYPE_B1_BOOT                EQU 0
RTYPE_B1_ACTIVE              EQU 1
RTYPE_B1_LEAVE               EQU 2
RTYPE_B1_EXIT                EQU 3

RTYPE_C0_ACTIVE              EQU 0
RTYPE_C0_EXIT                EQU 1
RTYPE_C0_SCROLL              EQU 2
RTYPE_C0_PALETTE             EQU 3

RTypeBank4_InitStageControllers:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #A22E
                OR   A
                SBC  HL, DE
                JP   Z, RTypeBank4_InitControllerA22E
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #B0E1
                OR   A
                SBC  HL, DE
                JP   Z, RTypeBank4_InitControllerB0E1
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #B1D8
                OR   A
                SBC  HL, DE
                JP   Z, RTypeBank4_InitBossB1D8
                JP   RTypeBank4_InitControllerC0A9

; `$A22E`: event создаёт только priority `$3800` root и сразу останавливает
; четыре scroll velocity. Accumulators не очищаются: исходник также оставляет
; текущую позицию arena и обнуляет лишь `$2EEC/$2EF4` с дробными half-words.
RTypeBank4_InitControllerA22E:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_STAGE_CONTROLLER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #3800
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, RTYPE_CTRL_A22E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_KIND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_DAMAGE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS + 1), A
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0104
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), HL
                LD   HL, #0164
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   HL, RTypeBank4_A22MultipartTimeline
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                LD   HL, RTypeBank4_A22TerrainTimeline
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX), HL
                LD   HL, #01E0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   A, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_HP), A
                LD   HL, #A290
                LD   (RTypeWorldStageControllerHandler), HL
                CALL RTypeBank4_ClearAllVelocities
                LD   A, #19
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                JP   RTypeObjects_CommitCurrent

; `$B0E1/$B111`: 16 готовых spawn records, затем точный `$0800` exit.
RTypeBank4_InitControllerB0E1:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_STAGE_CONTROLLER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, RTYPE_CTRL_B0E1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_KIND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER + 1), A
                LD   HL, RTypeBank4_B0SpawnTimeline
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                CALL RTypeBank4_ClearAllVelocities
                LD   A, #19
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                JP   RTypeObjects_CommitCurrent

; `$C0A9`: root не меняет scroll и начинает progression с нуля. В record
; хранится уже compact callback table, но threshold/pорядок равны ES:$6416.
RTypeBank4_InitControllerC0A9:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_STAGE_CONTROLLER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #C800
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, RTYPE_CTRL_C0A9
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_KIND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX4), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX4 + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX5), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX5 + 1), A
                LD   HL, RTypeBank4_C0Timeline
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                JP   RTypeObjects_CommitCurrent

RTypeBank4_UpdateStageController:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_KIND)
                CP   RTYPE_CTRL_A22E
                JP   Z, RTypeBank4_UpdateControllerA22E
                CP   RTYPE_CTRL_B0E1
                JP   Z, RTypeBank4_UpdateControllerB0E1
                JP   RTypeBank4_UpdateControllerC0A9

RTypeBank4_UpdateControllerA22E:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE)
                CP   RTYPE_A22_EXIT
                JP   Z, RTypeBank4_A22Exit

                ; Внешняя очистка `$2FC4` обрывает arena без восстановления
                ; движения, как `$A4A0`; root выдаёт `$1A` и освобождает запись.
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .damage
                CALL RTypeBank4_ClearAllVelocities
                LD   A, #1A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

.damage:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_DAMAGE)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_HP)
                CP   B
                JR   NC, .phase
                JP   RTypeBank4_A22BeginExit

.phase:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_DAMAGE)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS)
                CP   B
                JR   Z, .phaseTick
                LD   A, B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS), A
                LD   A, RTYPE_A22_FLASH
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, 15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   HL, #A3B3
                LD   (RTypeWorldStageControllerHandler), HL
                JR   .common

.phaseTick:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   A, H
                OR   L
                JR   NZ, .common
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE)
                CP   RTYPE_A22_NORMAL
                JR   Z, .toUp
                CP   RTYPE_A22_PATTERN_UP
                JR   Z, .toHold
                CP   RTYPE_A22_PATTERN_HOLD
                JR   Z, .toDown
                ; PATTERN_DOWN и FLASH сходятся обратно в `$A290`.
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, 15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   HL, #A290
                LD   (RTypeWorldStageControllerHandler), HL
                JR   .common
.toUp:         LD   A, RTYPE_A22_PATTERN_UP
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, 15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   HL, #A334
                LD   (RTypeWorldStageControllerHandler), HL
                JR   .common
.toHold:       LD   A, RTYPE_A22_PATTERN_HOLD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   HL, #A2B0
                LD   (RTypeWorldStageControllerHandler), HL
                JR   .common
.toDown:       LD   A, RTYPE_A22_PATTERN_DOWN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, 15
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX2), HL
                LD   HL, #A375
                LD   (RTypeWorldStageControllerHandler), HL

.common:       CALL RTypeBank4_A22SpawnMultipart
                CALL RTypeBank4_A22TerrainTimelineStep
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), HL
                LD   DE, #1720
                OR   A
                SBC  HL, DE
                JR   NC, .milestones
                LD   A, (FrameCounter)
                AND  #0F
                JR   NZ, .milestones
                LD   A, (FrameCounter)
                AND  #10
                LD   A, #27
                JR   Z, .palette
                LD   A, #2E
.palette:      LD   C, 7
                LD   DE, 0
                CALL RTypePalette_SetTile

.milestones:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                LD   DE, #1740
                OR   A
                SBC  HL, DE
                JR   NZ, .mask
                LD   A, #FF
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, #1C
                LD   (RTYPE_LAST_SOUND_COMMAND), A
.mask:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                LD   DE, #1760
                OR   A
                SBC  HL, DE
                CALL Z, RTypeBank4_MaskForegroundArena
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                LD   DE, #1780
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                LD   (RTypeWorldBgVelocity), HL
                XOR  A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_A22BeginExit:
                LD   A, RTYPE_A22_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, #0180
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                LD   HL, #A523
                LD   (RTypeWorldStageControllerHandler), HL
                CALL RTypeBank4_MaskForegroundArena
                RET

RTypeBank4_A22Exit:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                JR   NZ, .player
                LD   A, #1B
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                XOR  A
                LD   C, 7
                LD   DE, 0
                CALL RTypePalette_SetTile
.player:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                LD   DE, #0080
                OR   A
                SBC  HL, DE
                JR   NZ, .motion
                LD   A, #FF
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, #1C
                LD   (RTYPE_LAST_SOUND_COMMAND), A
.motion:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                LD   A, H
                OR   L
                JR   Z, .done
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                RET  NC
                LD   HL, #00C0
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                AND  2
                JR   NZ, .vertical
                LD   HL, #FF00
.vertical:     LD   (RTypeWorldFgYVelocity), HL
                RET
.done:         LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                LD   (RTypeWorldBgVelocity), HL
                XOR  A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Сохранить текущий controller, создать `$915B` через bank #0C и вернуть
; scratch именно controller-а. Reload `$FFFF` навсегда закрывает stream.
RTypeBank4_A22SpawnMultipart:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTypeWorldLastCommand), DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), DE
                LD   A, D
                CP   #FF
                RET  Z
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ControllerIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjectBank4_SpawnMultipart915B
                LD   A, (RTypeBank4_ControllerIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Threshold table создаёт готовый terrain pattern без отдельного CPU-writer
; object. В V30 writer только чередует две заранее известные фазы; target
; выбирает фазу по тому же bit4 frame и переносит весь прямоугольник разом.
RTypeBank4_A22TerrainTimelineStep:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                CP   #FF
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                OR   A
                SBC  HL, DE
                RET  C
                ; ROM вызывает writer при `counter >= threshold`, включая
                ; точное равенство текущего pass.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX)
                INC  HL
                INC  HL
                LD   A, (HL)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX), HL
                JP   RTypeBank4_A22ApplyTerrainPattern

RTypeBank4_UpdateControllerB0E1:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE)
                CP   RTYPE_B0_EXIT
                JP   Z, RTypeBank4_B0Exit
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .active
                LD   A, #1A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.active:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), HL
                LD   DE, #0800
                OR   A
                SBC  HL, DE
                JP   NC, RTypeBank4_B0BeginExit
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER)
                INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                LD   (RTypeWorldLastCommand), DE
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ControllerIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjectBank4_SpawnEnemy5EED
                LD   A, (RTypeBank4_ControllerIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_B0BeginExit:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, #FF
                LD   (RTYPE_CLEANUP_ACTIVE), A
                CALL RTypeBank4_InitPaletteControl
                LD   A, #1B
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   HL, #0090
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                LD   A, RTYPE_B0_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                RET

RTypeBank4_B0Exit:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                LD   DE, #0080
                OR   A
                SBC  HL, DE
                JR   NZ, .doneCheck
                LD   A, #FF
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, #1C
                LD   (RTYPE_LAST_SOUND_COMMAND), A
.doneCheck:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_ClearAllVelocities:
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                LD   (RTypeWorldFgYVelocity), A
                LD   (RTypeWorldFgYVelocity + 1), A
                LD   (RTypeWorldBgYVelocity), A
                LD   (RTypeWorldBgYVelocity + 1), A
                RET

; `$A44C/$A4FF`: убрать collision attributes с 1152 cells arena. Карта page
; #07 уже лежит в 4-МБ RAM; редкий линейный проход не входит в обычный кадр.
RTypeBank4_MaskForegroundArena:
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   HL, #DC02
                LD   BC, #0480
.cell:         LD   A, (HL)
                AND  #0F
                LD   (HL), A
                INC  HL
                INC  HL
                INC  HL
                INC  HL
                DEC  BC
                LD   A, B
                OR   C
                JR   NZ, .cell
                RET

RTypeBank4_A22ApplyTerrainPattern:
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE                    ; index * 10
                LD   DE, RTypeBank4_A22TerrainRecords
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   A, (FrameCounter)
                AND  #10
                JR   Z, .sourceReady
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                DEC  HL
.sourceReady:  LD   (RTypeBank4_TerrainSource), DE
                INC  HL
                INC  HL                       ; перейти за второй source
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   A, D
                LD   (RTypeBank4_TerrainWidth), A
                LD   A, E
                LD   (RTypeBank4_TerrainHeight), A
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   A, H
                OR   #C0
                LD   H, A
                LD   (RTypeBank4_TerrainDestination), HL

.row:          LD   HL, (RTypeBank4_TerrainSource)
                LD   DE, (RTypeBank4_TerrainDestination)
                LD   A, (RTypeBank4_TerrainWidth)
                LD   B, A
.column:       LD   A, (HL)
                LD   (DE), A
                INC  HL
                INC  DE
                LD   A, (HL)
                LD   (DE), A
                INC  HL
                INC  DE
                LD   A, #88
                LD   (DE), A
                INC  DE
                XOR  A
                LD   (DE), A
                INC  DE
                DJNZ .column
                LD   (RTypeBank4_TerrainSource), HL
                LD   HL, (RTypeBank4_TerrainDestination)
                LD   DE, #0100
                ADD  HL, DE
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   (RTypeBank4_TerrainDestination), HL
                LD   A, (RTypeBank4_TerrainHeight)
                DEC  A
                LD   (RTypeBank4_TerrainHeight), A
                JR   NZ, .row
                RET

; ----------------------------------------------------------------------------
; `$B1D8/$B1FA…$B7FA`: 37-part Stage-6 boss.
; ----------------------------------------------------------------------------

RTypeBank4_InitBossB1D8:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_B1D8_ROOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #7D00
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, RTYPE_B1_BOOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   HL, #0060
                LD   (RTypeWorldBgVelocity), HL
                LD   A, #19
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                JP   RTypeObjects_CommitCurrent

; Первый scheduler pass создаёт все parts, как `$B1FA`: event pass ничего,
; кроме root, не создаёт. Allocation failures уменьшают реальный remaining.
RTypeBank4_B1Bootstrap:
                LD   HL, #0260
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTypeBank4_B1RootX), HL
                LD   HL, #0060
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   (RTypeBank4_B1RootY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_B1RootIndex), A
                XOR  A
                LD   (RTypeBank4_B1ChildCount), A
                LD   (RTypeBank4_B1ChildOrdinal), A
                LD   HL, #7D01
                LD   (RTypeBank4_B1ChildPriority), HL
                LD   HL, RTypeBank4_B1ChildOffsets
                LD   (RTypeBank4_B1ChildPointer), HL

.child:        LD   A, (RTypeBank4_B1RootIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JP   C, .restoreAdvance
                LD   A, RTYPE_OBJ_B1D8_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, (RTypeBank4_B1ChildPriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeBank4_B1RootIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_ROOT), A
                LD   HL, (RTypeBank4_B1ChildPointer)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DX), DE
                EX   DE, HL
                LD   BC, (RTypeBank4_B1RootX)
                ADD  HL, BC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                EX   DE, HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DY), DE
                EX   DE, HL
                LD   BC, (RTypeBank4_B1RootY)
                ADD  HL, BC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_X), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_X + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_Y), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_Y + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DAMAGE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
                LD   A, 14
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_HP), A
                CALL RTypeRng_Next
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_PHASE), HL
                LD   HL, #608E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #69
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #69
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE), A
                LD   HL, #608E
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
                LD   A, (RTypeBank4_B1ChildCount)
                INC  A
                LD   (RTypeBank4_B1ChildCount), A

.restoreAdvance:
                LD   A, (RTypeBank4_B1RootIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   HL, (RTypeBank4_B1ChildPointer)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTypeBank4_B1ChildPointer), HL
                LD   HL, (RTypeBank4_B1ChildPriority)
                INC  HL
                LD   (RTypeBank4_B1ChildPriority), HL
                LD   A, (RTypeBank4_B1ChildOrdinal)
                INC  A
                LD   (RTypeBank4_B1ChildOrdinal), A
                CP   37
                JP   C, .child

                LD   HL, #6082
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #1D
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #1D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_DAMAGE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VX), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VX + 1), A
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VY), HL
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_TARGET_TIMER), HL
                LD   HL, #0C80
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_LIFETIME), HL
                LD   HL, #0033
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_RELOAD), HL
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ATTACK_FLAG), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ATTACK_FLAG + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_SELECTED_CHILD), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_SELECTED_CHILD + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_PREVIOUS_CHILD), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_PREVIOUS_CHILD + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_NEAREST), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_NEAREST + 1), A
                LD   A, (RTypeBank4_B1ChildCount)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_REMAINING), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_REMAINING + 1), A
                LD   A, #28
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_HP), A
                LD   A, RTYPE_B1_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #6082
                JP   RTypeSprite_PrepareDescriptor

RTypeBank4_UpdateBossB1D8Root:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_B1_BOOT
                JP   Z, RTypeBank4_B1Bootstrap
                CP   RTYPE_B1_LEAVE
                JP   Z, RTypeBank4_B1Leave
                CP   RTYPE_B1_EXIT
                JP   Z, RTypeBank4_B1Exit

                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JP   NZ, RTypeBank4_B1ExternalCleanup
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER)
                OR   A
                JR   Z, .motion
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
                LD   B, A
                LD   A, (FrameCounter)
                AND  1
                JR   Z, .motion
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A

.motion:       LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VX)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, #6082
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_TARGET_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_TARGET_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank4_B1PickTarget

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .damage
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ANIM_TIMER), HL
                LD   HL, #FFFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_ATTACK_FLAG), HL

.damage:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_REMAINING)
                CP   12
                JR   NC, .life
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_DAMAGE)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_HP)
                CP   B
                JP   C, RTypeBank4_B1BeginExit
.life:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_LIFETIME)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_LIFETIME), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_B1_LEAVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

; Выбор точки дословно использует 32 готовых пары `$6002`; расстояние меньше
; `$58` отбрасывается. Ограничение 32 attempts защищает target от битого RNG.
RTypeBank4_B1PickTarget:
                LD   B, 32
.pick:         PUSH BC
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeBank4_B1Targets
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTypeBank4_B1TargetX), DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                LD   (RTypeBank4_B1TargetY), BC
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                CALL RTypeBank4_AbsHL
                LD   (RTypeBank4_B1Distance), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, (RTypeBank4_B1TargetY)
                OR   A
                SBC  HL, DE
                CALL RTypeBank4_AbsHL
                LD   DE, (RTypeBank4_B1Distance)
                ADD  HL, DE
                LD   DE, #0058
                OR   A
                SBC  HL, DE
                POP  BC
                JR   NC, .selected
                DJNZ .pick
.selected:     LD   HL, (RTypeBank4_B1TargetX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                CALL RTypeBank4_ScaleThreeHalves
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VX), HL
                LD   HL, (RTypeBank4_B1TargetY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                CALL RTypeBank4_ScaleThreeHalves
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_VY), HL
                LD   HL, #00CC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_TARGET_TIMER), HL
                RET

RTypeBank4_AbsHL:
                BIT  7, H
                RET  Z
                XOR  A
                SUB  L
                LD   L, A
                SBC  A, A
                SUB  H
                LD   H, A
                RET

; Signed `value*2-value/2`, точная V30 формула `$B34C…$B35F`.
RTypeBank4_ScaleThreeHalves:
                LD   D, H
                LD   E, L
                SRA  D
                RR   E
                ADD  HL, HL
                OR   A
                SBC  HL, DE
                RET

RTypeBank4_B1Leave:
                LD   DE, #0400
                CALL RTypeProjectile_AddQ8X
                LD   HL, #6082
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02E0
                OR   A
                SBC  HL, DE
                RET  C
                JP   RTypeBank4_B1BeginExit

RTypeBank4_B1BeginExit:
                LD   A, RTYPE_B1_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_EXIT_TIMER), HL
                RET

RTypeBank4_B1Exit:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_EXIT_TIMER), HL
                LD   DE, #0090
                OR   A
                SBC  HL, DE
                JR   NZ, .player
                XOR  A
                LD   C, 1
                LD   DE, 0
                CALL RTypePalette_SetTile
.player:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_EXIT_TIMER)
                LD   DE, #0080
                OR   A
                SBC  HL, DE
                JR   NZ, .done
                LD   A, #FF
                LD   (RTypeFinalPlayerExitLatch), A
                LD   A, #1C
                LD   (RTYPE_LAST_SOUND_COMMAND), A
.done:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_EXIT_TIMER)
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE)
                CALL RTypeResources_Release
                LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_B1ExternalCleanup:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE)
                CALL RTypeResources_Release
                LD   A, #1A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   HL, #0080
                LD   (RTypeWorldFgVelocity), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_UpdateBossB1D8Child:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_ROOT)
                CALL RTypeBank4_B1ReadRoot
                JP   C, RTypeBank4_B1RemoveChild
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                JR   NZ, .dying
                LD   A, (RTypeBank4_B1RootState)
                CP   RTYPE_B1_EXIT
                JR   Z, .beginDying

                LD   HL, (RTypeBank4_B1RootX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DX)
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_X)
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                CALL RTypeBank4_B1StepToward
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank4_B1RootY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DY)
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_Y)
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeBank4_B1StepToward
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL

                LD   A, (FrameCounter)
                AND  7
                CALL Z, RTypeBank4_B1WobbleChild
                CALL RTypeBank4_B1AnimateChild
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DAMAGE)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_HP)
                CP   B
                RET  NC
                CALL RTypeBank4_B1DecrementRoot
                LD   A, #52
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                JP   RTypeBank4_B1RemoveChild

.beginDying:   LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_PHASE)
                LD   A, L
                AND  #3F
                ADD  A, 4
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DELAY), HL
                RET
.dying:        LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DELAY)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DELAY), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank4_B1RemoveChild

; A=root index. Carry=1 при удалённом/чужом root; иначе bank-local snapshot.
RTypeBank4_B1ReadRoot:
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_B1D8_ROOT
                JR   NZ, .missing
                LD   DE, RTYPE_OBJ_X
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank4_B1RootX), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank4_B1RootY), DE
                LD   DE, RTYPE_OBJ_STATE - (RTYPE_OBJ_Y + 1)
                ADD  HL, DE
                LD   A, (HL)
                LD   (RTypeBank4_B1RootState), A
                OR   A
                RET
.missing:      SCF
                RET

; HL=target, DE=current; вернуть current±2 либо target, без overshoot.
RTypeBank4_B1StepToward:
                PUSH HL
                OR   A
                SBC  HL, DE
                JR   Z, .equal
                BIT  7, H
                JR   NZ, .negative
                POP  HL
                INC  DE
                INC  DE
                OR   A
                SBC  HL, DE
                JR   C, .targetWasNear
                EX   DE, HL
                RET
.negative:     POP  HL
                DEC  DE
                DEC  DE
                OR   A
                SBC  HL, DE
                JR   NC, .targetWasNear
                EX   DE, HL
                RET
.targetWasNear:
                ADD  HL, DE                    ; восстановить исходный target
                RET
.equal:        POP  HL
                RET

RTypeBank4_B1WobbleChild:
                CALL RTypeRng_Next
                LD   A, L
                SRL  A
                AND  3
                SUB  2
                JR   NZ, .xDelta
                LD   A, 2
.xDelta:       LD   E, A
                RLCA
                SBC  A, A
                LD   D, A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_X)
                ADD  HL, DE
                CALL RTypeBank4_B1ClampWobble
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_X), HL
                CALL RTypeRng_Next
                LD   A, L
                SRL  A
                AND  3
                SUB  2
                JR   NZ, .yDelta
                LD   A, 2
.yDelta:       LD   E, A
                RLCA
                SBC  A, A
                LD   D, A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_Y)
                ADD  HL, DE
                CALL RTypeBank4_B1ClampWobble
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_WOBBLE_Y), HL
                RET

RTypeBank4_B1ClampWobble:
                BIT  7, H
                JR   Z, .positive
                LD   DE, #FFFC
                OR   A
                SBC  HL, DE
                JR   NC, .restoreNegative
                LD   HL, #FFFC
                RET
.restoreNegative:
                ADD  HL, DE
                RET
.positive:     LD   DE, 4
                OR   A
                SBC  HL, DE
                JR   C, .restorePositive
                LD   HL, 4
                RET
.restorePositive:
                ADD  HL, DE
                RET

RTypeBank4_B1AnimateChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER)
                OR   A
                JR   Z, .descriptor
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
                LD   A, (FrameCounter)
                AND  1
                JR   Z, .descriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.descriptor:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_PHASE)
                LD   A, (FrameCounter)
                ADD  A, L
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                SRL  A
                ADD  A, C                      ; `(phase&18)*3/4` = 0,6,12,18
                LD   E, A
                LD   D, 0
                LD   HL, #608E
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank4_B1DecrementRoot:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_ROOT)
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   DE, RTYPE_OBJ_B1_REMAINING
                ADD  HL, DE
                LD   A, (HL)
                OR   A
                RET  Z
                DEC  (HL)
                RET

RTypeBank4_B1RemoveChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; ----------------------------------------------------------------------------
; `$C0A9/$C0CA`: финальный stage-controller и callback script ES:$6416.
; ----------------------------------------------------------------------------

RTypeBank4_UpdateControllerC0A9:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE)
                CP   RTYPE_C0_EXIT
                JP   Z, RTypeBank4_C0Exit
                CP   RTYPE_C0_SCROLL
                JP   Z, RTypeBank4_C0Scroll
                CP   RTYPE_C0_PALETTE
                JP   Z, RTypeBank4_C0PaletteWait

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                OR   A
                SBC  HL, DE
                JR   C, .afterCallback
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER)
                INC  HL
                INC  HL
                LD   A, (HL)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_POINTER), HL
                CALL RTypeBank4_C0RunCallback

.afterCallback:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_COUNTER)
                LD   DE, #2000
                OR   A
                SBC  HL, DE
                JP   NC, RTypeBank4_C0BeginExit
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .damageCount
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.damageCount:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX5)
                LD   DE, #0500
                OR   A
                SBC  HL, DE
                RET  C
                JP   RTypeBank4_C0BeginExit

RTypeBank4_C0RunCallback:
                CP   1
                JP   C, .done
                CP   5
                JP   C, RTypeBank4_C0SpawnFinalSprite
                CP   5
                JP   Z, RTypeBank4_C0SpawnTerrainChild
                CP   6
                JP   Z, RTypeBank4_C0TimedControl
                CP   7
                JP   Z, RTypeBank4_C0PatternLeft
                CP   8
                JP   Z, RTypeBank4_ClearAllVelocities
                CP   9
                JR   Z, .sound19
                CP   10
                JR   Z, .flag36
                CP   11
                JR   Z, .pattern1
                CP   12
                JR   Z, .pattern2
                CP   13
                JR   Z, .pattern3
                CP   14
                JR   Z, .pattern4
                CP   15
                JP   Z, RTypeBank4_C0PatternCenter
                CP   16
                JR   NZ, .done
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_FLAGS + 1), A
.done:         RET
.sound19:      LD   A, #19
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                RET
.flag36:       LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_AUX4), A
                RET
.pattern1:     LD   A, #68
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, 1
                JR   .pattern
.pattern2:     LD   A, 2
                JR   .pattern
.pattern3:     LD   A, 3
                JR   .pattern
.pattern4:     LD   A, 4
.pattern:      LD   BC, #0284
                LD   DE, #0124
                JP   RTypeBank4_C0ApplyTerrainPattern

RTypeBank4_C0PatternLeft:
                XOR  A
                LD   BC, #02C4
                LD   DE, #0124
                JP   RTypeBank4_C0ApplyTerrainPattern
RTypeBank4_C0PatternCenter:
                XOR  A
                LD   BC, #0284
                LD   DE, #0124
                JP   RTypeBank4_C0ApplyTerrainPattern

; A=1..4. Save/restore root scratch исключает подмену callback-controller newly
; allocated object-ом. Motion roots и command count равны `$9758…$9801`.
RTypeBank4_C0SpawnFinalSprite:
                LD   (RTypeBank4_C0Form), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ControllerIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JP   C, RTypeBank4_C0RestoreController
                LD   A, RTYPE_OBJ_C0_FINAL_SPRITE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeBank4_ControllerIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_OWNER), A
                LD   A, (RTypeBank4_C0Form)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_FORM), A
                CP   1
                JR   NZ, .later
                LD   HL, #A872
                LD   BC, #0278
                LD   DE, #0090
                LD   A, 3
                JR   .configured
.later:        LD   BC, #02A0
                LD   DE, #0108
                LD   HL, #A90C
                LD   A, (RTypeBank4_C0Form)
                CP   2
                JR   Z, .laterRootReady
                LD   HL, #A96C
                CP   3
                JR   Z, .laterRootReady
                LD   HL, #A9F6
.laterRootReady:
                LD   A, 8
.configured:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), BC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                PUSH AF
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                POP  AF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_LIFETIME), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_LIFETIME + 1), A
                LD   HL, #437A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #6A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #6A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #437A
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
RTypeBank4_C0RestoreController:
                LD   A, (RTypeBank4_ControllerIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank4_UpdateC0FinalSprite:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_OWNER)
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_STAGE_CONTROLLER
                JP   NZ, RTypeBank4_C0RemoveFinalSprite
                CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank4_C0RemoveFinalSprite
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_LIFETIME)
                INC  A
                CP   3
                JR   C, .phaseReady
                XOR  A
.phaseReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_LIFETIME), A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeBank4_C0DescriptorCycle
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                EX   DE, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank4_C0RemoveFinalSprite:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_C0SpawnTerrainChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ControllerIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, RTypeBank4_C0RestoreController
                LD   A, RTYPE_OBJ_C0_TERRAIN_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1D00
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #011C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTypeBank4_ControllerIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_OWNER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_TIMER + 1), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeObjects_CommitCurrent
                JP   RTypeBank4_C0RestoreController

RTypeBank4_UpdateC0TerrainChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_OWNER)
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_STAGE_CONTROLLER
                JR   NZ, .remove
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldBgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_C0_TERRAIN_TIMER), HL
                RET
.remove:       XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$F366` внутри callback: первая ветвь выдаёт `$21` и priority `$1000`
; delayed `$20` через `$0180`. Это локальная копия, потому что Core handler
; находится в slot2 и недоступен, пока исполняется bank #0D.
RTypeBank4_C0TimedControl:
                LD   A, #21
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank4_ControllerIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JP   C, RTypeBank4_C0RestoreController
                LD   A, RTYPE_OBJ_TIMED_CONTROL_F3C1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0180
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_TIMER), HL
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_SOUND_COMMAND), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeObjects_CommitCurrent
                JP   RTypeBank4_C0RestoreController

; A=pattern 0..4, BC/DE=native anchor. Каждый pattern — готовые 8x8 cells по
; четыре bytes; восемь LDIR по 32 bytes заменяют 64 разрозненных V30 writes.
RTypeBank4_C0ApplyTerrainPattern:
                LD   (RTypeBank4_C0Pattern), A
                PUSH BC
                PUSH DE
                CALL RTypeTerrain_BackgroundCode
                POP  DE
                POP  BC
                LD   HL, (RTypeTerrain_Address)
                LD   A, H
                OR   #C0
                LD   H, A
                LD   (RTypeBank4_TerrainDestination), HL
                LD   A, (RTypeBank4_C0Pattern)
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeBank4_C0PatternPointers
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                EX   DE, HL
                LD   B, 8
.row:          PUSH BC
                LD   DE, (RTypeBank4_TerrainDestination)
                LD   BC, 32
                LDIR
                LD   (RTypeBank4_TerrainSource), HL
                LD   HL, (RTypeBank4_TerrainDestination)
                LD   DE, #0100
                ADD  HL, DE
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   (RTypeBank4_TerrainDestination), HL
                LD   HL, (RTypeBank4_TerrainSource)
                POP  BC
                DJNZ .row
                RET

RTypeBank4_C0BeginExit:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, #FF
                LD   (RTYPE_CLEANUP_ACTIVE), A
                LD   A, RTYPE_C0_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                LD   HL, #0180
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                CALL RTypeBank4_C0ClearArena
                RET

RTypeBank4_C0Exit:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                LD   DE, #017C
                OR   A
                SBC  HL, DE
                JR   NZ, .decrement
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                XOR  A
                LD   (RTYPE_CLEANUP_ACTIVE), A
.decrement:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER), HL
                LD   DE, #0080
                OR   A
                SBC  HL, DE
                JR   NZ, .zero
                LD   A, #1A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
.zero:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_EXIT_TIMER)
                LD   A, H
                OR   L
                RET  NZ
                LD   A, #0F
                LD   (RTypeFinalPlayerExitLatch), A
                LD   HL, #00C0
                LD   (RTypeWorldFgVelocity), HL
                LD   (RTypeWorldBgVelocity), HL
                LD   HL, #00E0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   A, RTYPE_C0_SCROLL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                RET

RTypeBank4_C0Scroll:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   C, 1
                LD   DE, 7
                CALL RTypePalette_SetTile
                XOR  A
                LD   C, 2
                LD   DE, 7
                CALL RTypePalette_SetTile
                XOR  A
                LD   C, 3
                LD   DE, 7
                CALL RTypePalette_SetTile
                XOR  A
                LD   C, #0F
                LD   DE, 7
                CALL RTypePalette_SetTile
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   A, RTYPE_C0_PALETTE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_PHASE), A
                RET

RTypeBank4_C0PaletteWait:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, #2B
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank4_C0ClearArena:
                LD   A, RTYPE_WORLD_BG_MAP_PAGE
                SetPage3_A
                LD   HL, #D002
                LD   BC, #0800
.background:   LD   A, (HL)
                AND  #0F
                LD   (HL), A
                INC  HL
                INC  HL
                INC  HL
                INC  HL
                DEC  BC
                LD   A, B
                OR   C
                JR   NZ, .background
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   HL, #D002
                LD   BC, #0800
.foreground:   LD   (HL), #A0
                INC  HL
                LD   (HL), #0F
                INC  HL
                INC  HL
                INC  HL
                DEC  BC
                LD   A, B
                OR   C
                JR   NZ, .foreground
                RET

RTypeBank4_C0DescriptorCycle:
                DEFW #437A, #4380, #4386
RTypeBank4_C0PatternPointers:
                DEFW RTypeBank4_C0TerrainPattern0
                DEFW RTypeBank4_C0TerrainPattern1
                DEFW RTypeBank4_C0TerrainPattern2
                DEFW RTypeBank4_C0TerrainPattern3
                DEFW RTypeBank4_C0TerrainPattern4

; `$5526/$5596`: точные event setters второго M72 palette-bank. RGB не
; вычисляется Z80: все 128 tile palette types уже преобразованы в ARGB4444
; внутри общей страницы PAK, а RTypePalette_SetTile переносит выбранные
; 2*32 bytes в opaque/alpha таблицы FT812 аппаратным DMA.
RTypeBank4_InitPaletteControl:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5526
                OR   A
                SBC  HL, DE
                JR   Z, .indexed

                ; `$5596` дословно активирует slots 0…14 с target type 0,
                ; gradual mode 1, cadence mask 3 и threshold `$1F`.
                LD   B, 15
                LD   C, 0
.arenaSlot:    PUSH BC
                XOR  A
                LD   DE, 3
                CALL RTypePalette_SetTile
                POP  BC
                INC  C
                DJNZ .arenaSlot
                RET

.indexed:      LD   A, (RTypeWorldLastCommand)
                CP   12
                RET  NC
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                     ; 4 bytes на `(slot,type)`
                LD   DE, RTypeBank4_PaletteEventRecords
                ADD  HL, DE
                LD   C, (HL)                    ; high word byte всегда ноль
                INC  HL
                INC  HL
                LD   A, (HL)
                LD   DE, #000F
                JP   RTypePalette_SetTile

; Буквальная таблица `ES:$2754…$2783`; три последних события намеренно
; адресуют служебный slot 15, который существует в 16-record manager.
RTypeBank4_PaletteEventRecords:
                DEFW 7, #17
                DEFW 7, 0
                DEFW #0D, 0
                DEFW 9, 0
                DEFW #0A, 0
                DEFW #0B, 0
                DEFW #0C, 0
                DEFW #0D, 0
                DEFW #0E, 0
                DEFW #0F, #0F
                DEFW #0F, #0F
                DEFW #0F, #0F

                include "generated_stage_controller_tables.inc"

RTypeBank4_PartCount:          DEFB 0
RTypeBank4_PartIndices:        DEFS 8, 0
RTypeBank4_RootIndex:          DEFB 0
RTypeBank4_RootIndexFromParent: DEFB 0
RTypeBank4_ParentIndex:        DEFB 0
RTypeBank4_RandomAnimated:     DEFB 0
RTypeBank4_RandomHP:           DEFB 0
RTypeBank4_RandomResource:     DEFB 0
RTypeBank4_ExplosionEffect:    DEFB 0
RTypeBank4_SegmentX:           DEFW 0
RTypeBank4_SegmentThreshold:   DEFW 0
RTypeBank4_SegmentDelta:       DEFW 0
RTypeBank4_RandomHandler:      DEFW 0
RTypeBank4_RandomX:            DEFW 0
RTypeBank4_RandomVelocity:     DEFW 0
RTypeBank4_RandomDescriptor:   DEFW 0
RTypeBank4_MissileX:           DEFW 0
RTypeBank4_ExplosionX:         DEFW 0
RTypeBank4_ExplosionY:         DEFW 0
RTypeBank4_CoreChildX:         DEFW 0
RTypeBank4_CoreChildY:         DEFW 0
RTypeBank4_CoreChildDescriptor: DEFW 0
RTypeBank4_FBTable:             DEFW 0
RTypeBank4_FBStream:            DEFW 0
RTypeBank4_FBY:                 DEFW 0
RTypeBank4_FBResource:          DEFB 0
RTypeBank4_ControllerIndex:     DEFB 0
RTypeBank4_TerrainWidth:        DEFB 0
RTypeBank4_TerrainHeight:       DEFB 0
RTypeBank4_TerrainSource:       DEFW 0
RTypeBank4_TerrainDestination:  DEFW 0
RTypeBank4_B1RootIndex:         DEFB 0
RTypeBank4_B1RootState:         DEFB 0
RTypeBank4_B1ChildCount:        DEFB 0
RTypeBank4_B1ChildOrdinal:      DEFB 0
RTypeBank4_B1ChildPriority:     DEFW 0
RTypeBank4_B1ChildPointer:      DEFW 0
RTypeBank4_B1RootX:             DEFW 0
RTypeBank4_B1RootY:             DEFW 0
RTypeBank4_B1TargetX:           DEFW 0
RTypeBank4_B1TargetY:           DEFW 0
RTypeBank4_B1Distance:          DEFW 0
RTypeBank4_C0Form:              DEFB 0
RTypeBank4_C0Pattern:           DEFB 0
