; ============================================================================
; Bank #0C: stage-specific object handlers после Dobkeratops.
;
; Банк отображается только resident trampoline-ом в CPU slot2 `$8000…$BFFF`.
; Общие temporaries Core находятся в `$4340…$4379`, поэтому вызовы allocator,
; ROM reader, Q8 integrator и sprite cache не зависят от выбранной page #0C.
; Комментарии фиксируют именно наблюдаемую семантику World ROM, включая ветки,
; где descriptor или проверка bounds намеренно пропускаются.
; ============================================================================

; ----------------------------------------------------------------------------
; `$6F89/$6FD0/$7048/$7106`: двухскоростной Stage 2 object.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy6F89:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_6F89
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02D0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL

                ; Четыре 14-байтные записи `$9384`; индекс берётся только из
                ; command bits0..1. Умножение 14 выполнено как index*16-*2.
                LD   A, (RTypeWorldLastCommand)
                AND  3
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                OR   A
                SBC  HL, DE
                LD   DE, #9384
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_PRIMARY_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_PRIMARY_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_SECONDARY_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_SECONDARY_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_DESCRIPTOR_TABLE), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_TARGET_DIRECTION), DE

                ; Command bits2..3 выбирают либо обычный countdown, либо
                ; `$8000`-режим ожидания точного 16-direction угла к R-9.
                LD   A, (RTypeWorldLastCommand)
                SRL  A
                SRL  A
                AND  3
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #93BC
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_WAIT_VALUE), DE

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_DESCRIPTOR_TABLE)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_PALETTE), A
                LD   A, #27
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #27
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, 10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_HP), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_TIMER), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy6F89:
                ; Flash palette выбирает renderer по flags bit1. Handler на
                ; каждом pass сначала снимает старое значение этого бита.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_TIMER)
                OR   A
                JP   NZ, RTypeBank3_6FFlashUpdate

                CALL RTypeBank3_6FAddForegroundDelta
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_6F_WAITING
                JR   Z, RTypeBank3_6FWaiting
                JP   RTypeBank3_6FMoving

RTypeBank3_6FAddForegroundDelta:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                RET

; Повреждение временно замораживает normal state machine: только scroll,
; timer, animation и descriptor продолжаются; bounds в этой ветке не вызывается.
RTypeBank3_6FFlashUpdate:
                CALL RTypeBank3_6FAddForegroundDelta
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_TIMER)
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_TIMER), A
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION), HL
                CALL RTypeBank3_6FAnimatedDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_TIMER)
                AND  3
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                RET

RTypeBank3_6FWaiting:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_WAIT_VALUE)
                BIT  7, H
                JR   Z, .countdown
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_TARGET_DIRECTION)
                CP   L
                JR   Z, .ready
                JR   .descriptor
.countdown:    DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_WAIT_VALUE), HL
                LD   A, H
                OR   L
                JR   Z, .ready
.descriptor:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_WAIT_VALUE)
                BIT  7, H
                LD   A, 2
                JR   NZ, .offsetReady
                LD   A, L
                AND  #3F
                LD   A, 2
                JR   NZ, .offsetReady
                LD   A, 4
.offsetReady:  CALL RTypeBank3_6FReadDescriptorAtOffset
                JP   RTypeBank3_6FBounds
.ready:        LD   A, RTYPE_6F_MOVING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET                              ; ready-pass не проверяет bounds

RTypeBank3_6FMoving:
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0FA0
                OR   A
                SBC  HL, DE
                JR   NZ, .secondary
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_PRIMARY_X)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_PRIMARY_Y)
                CALL RTypeProjectile_AddQ8Y
                LD   A, 4
                CALL RTypeBank3_6FReadDescriptorAtOffset
                JP   RTypeBank3_6FBounds
.secondary:    LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_SECONDARY_X)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_SECONDARY_Y)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION), HL
                CALL RTypeBank3_6FAnimatedDescriptor

RTypeBank3_6FBounds:
                CALL RTypeWalker_InsideBounds
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; A=byte offset в descriptor table; таблица содержит words, а animation
; использует `(counter & $003C) >> 1`, то есть ровно 0,2,…,$1E.
RTypeBank3_6FReadDescriptorAtOffset:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_DESCRIPTOR_TABLE)
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank3_6FAnimatedDescriptor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_ANIMATION)
                LD   A, L
                AND  #3C
                SRL  A
                JP   RTypeBank3_6FReadDescriptorAtOffset

; ----------------------------------------------------------------------------
; `$875D/$8798/$87BA/$8817` и child `$8861/$893E`.
; ----------------------------------------------------------------------------

RTypeBank3_InitSpawner875D:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_SPAWNER_875D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0120
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #3AFE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SCRIPT_POINTER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_COUNTER + 1), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_RELOAD), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_TIMER), HL
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_RELOAD), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_TIMER), HL
                LD   HL, #0130
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_TARGET_Y), HL
                LD   HL, #0600
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_LIFE), HL
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateSpawner875D:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_LIFE)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_LIFE), HL
                LD   A, H
                OR   L
                JR   NZ, .alive
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.alive:        CALL RTypeBank3_87UpdateParameters
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_TIMER), HL
                XOR  A
                LD   (RTypeBank3_87SpawnDelay), A
                LD   (RTypeBank3_87SpawnDelay + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .spawn
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_TIMER), HL
                ; `$8817` передаёт child только младший byte RNG AX.
                CALL RTypeRng_Next
                LD   A, L
                LD   (RTypeBank3_87SpawnDelay), A
.spawn:        JP   RTypeBank3_87SpawnChild

; Каждый pass сначала возвращает difficulty-zero defaults `$3B12/$3B14`,
; затем применяет все script records с threshold <= уже увеличенного counter.
RTypeBank3_87UpdateParameters:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_COUNTER), HL
                LD   HL, #3B12
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_RELOAD), DE
                LD   HL, #3B14
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_RELOAD), DE
.script:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SCRIPT_POINTER)
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_COUNTER)
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SCRIPT_POINTER)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   H, D
                LD   L, E
                BIT  7, H
                JR   Z, .notSpawnReload
                LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_RELOAD), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SPAWN_TIMER), HL
                JR   .advance
.notSpawnReload:
                BIT  6, H
                JR   Z, .target
                LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_RELOAD), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_DELAY_TIMER), HL
                JR   .advance
.target:       LD   A, H
                AND  #0F
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_TARGET_Y), HL
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SCRIPT_POINTER)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_SCRIPT_POINTER), HL
                JR   .script

RTypeBank3_87SpawnChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_87ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_87ParentX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_87ParentY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_TARGET_Y)
                LD   (RTypeBank3_87ParentTargetY), HL
                LD   A, (RTypeBank3_87ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JP   C, .restore
                LD   A, RTYPE_OBJ_SPAWNER_875D_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_87ParentX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #3B2A
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   A, #2D
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeRng_Next
                LD   A, L
                AND  #3F
                LD   E, A
                LD   D, 0
                LD   HL, (RTypeBank3_87ParentY)
                LD   BC, -#0020
                ADD  HL, BC
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #3BB2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DESCRIPTOR), HL
                LD   A, (RTypeBank3_87ParentIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_PARENT), A
                LD   HL, (RTypeBank3_87SpawnDelay)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DELAY), HL
                LD   HL, (RTypeBank3_87ParentTargetY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_TARGET_Y), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_OSCILLATOR), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION + 1), A
                LD   HL, #3BB2
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_87ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_UpdateSpawner875DChild:
                CALL RTypeBank3_87ChildRefreshTarget
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_87_CHILD_AIMED
                JP   Z, RTypeBank3_87ChildAimed
                CALL RTypeBank3_6FAddForegroundDelta
                CALL RTypeRng_Next
                LD   A, L
                AND  #3F
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_TARGET_Y)
                LD   BC, -#0020
                ADD  HL, BC
                ADD  HL, DE
                EX   DE, HL                       ; DE=случайная target Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                LD   HL, #0010
                JR   C, .towardReady
                LD   HL, -#0010
.towardReady:  LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_OSCILLATOR)
                INC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_OSCILLATOR), A
                LD   DE, #0040
                BIT  6, A
                JR   Z, .oscillationReady
                LD   DE, -#0040
.oscillationReady:
                ADD  HL, DE
                LD   (RTypeBank3_87ChildYVelocity), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTypeBank3_87ChildYVelocity)
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank3_87ChildAnimateWavy
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DELAY)
                LD   A, H
                OR   L
                JP   Z, RTypeBank3_87ChildBounds
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DELAY), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank3_87ChildBeginAimed
                JP   RTypeBank3_87ChildBounds

RTypeBank3_87ChildAimed:
                CALL RTypeBank3_6FAddForegroundDelta
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION), HL
                LD   A, L
                AND  #0C
                SRL  A
                SRL  A
                LD   B, A
                ADD  A, A
                ADD  A, B                        ; phase*3
                ADD  A, A                        ; phase*6
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DESCRIPTOR)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeBank3_87ChildBounds

RTypeBank3_87ChildAnimateWavy:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_ANIMATION), HL
                LD   A, L
                AND  #0C
                SRL  A
                SRL  A
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #3BB2
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank3_87ChildBeginAimed:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                LD   (RTypeBank3_87Direction), A
                LD   E, A
                LD   D, 0
                LD   HL, #3B22
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL                       ; HL=velocity table
                LD   A, (RTypeBank3_87Direction)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   A, (RTypeBank3_87Direction)
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #3B32
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_DESCRIPTOR), DE
                LD   A, RTYPE_87_CHILD_AIMED
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank3_87ChildBounds:
                CALL RTypeWalker_InsideBounds
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Пока parent жив, child видит изменения target_y в тот же pass. Если owner
; уже освобождён, cached word остаётся последним корректным значением.
RTypeBank3_87ChildRefreshTarget:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_PARENT)
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                CP   RTYPE_OBJ_SPAWNER_875D
                RET  NZ
                LD   DE, RTYPE_OBJ_87_TARGET_Y
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_87_CHILD_TARGET_Y), DE
                RET

; ----------------------------------------------------------------------------
; `$7D68…$8035`: шестисостояний Stage 2 parent.
;
; Две разновидности берут Y и variant-word из перекрывающейся ROM-таблицы
; `$37DE/$37E0`. На hold-кадрах `$00C0` и `$0080` parent создаёт `$8D85`.
; Parent и child имеют одинаковый priority `$8010`; отдельный child-band уже
; завершён, поэтому вставленная запись не исполняется в этот же VBlank.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy7D68:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_7D68
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02D0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL

                LD   A, (RTypeWorldLastCommand)
                AND  1
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #37DE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #37E0
                LD   A, (RTypeWorldLastCommand)
                AND  1
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_VARIANT), DE

                ; `$7D9B` всегда потребляет RNG и складывает его с IRQ frame
                ; counter, хотя seed не участвует в шести movement states.
                CALL RTypeRng_Next
                LD   DE, (FrameCounter)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_ANIMATION_SEED), HL
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_PALETTE), A
                LD   A, #29
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #29
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0028
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_TIMER), A
                CALL RTypeBank3_7DBaseDescriptor
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy7D68:
                ; flags bit1 — исключительно текущая видимость flash palette;
                ; normal pass обязан снять его до state machine.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                CALL RTypeBank3_6FAddForegroundDelta
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_7D_APPROACH
                JP   Z, RTypeBank3_7DApproach
                CP   RTYPE_7D_RISE
                JP   Z, RTypeBank3_7DRise
                CP   RTYPE_7D_OPEN
                JP   Z, RTypeBank3_7DOpen
                CP   RTYPE_7D_HOLD
                JP   Z, RTypeBank3_7DHold
                CP   RTYPE_7D_CLOSE
                JP   Z, RTypeBank3_7DClose
                JP   RTypeBank3_7DRetreat

RTypeBank3_7DApproach:
                CALL RTypeBank3_7DSetBaseDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0270
                OR   A
                SBC  HL, DE
                JP   NC, RTypeBank3_7DFinishPass
                LD   A, RTYPE_7D_RISE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DRise:
                ; `variant*4-2`: верхний экземпляр идёт вниз на два native
                ; pixels, нижний — вверх на два, как signed word в `$7E09`.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_VARIANT)
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, -2
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                CALL RTypeBank3_7DSetBaseDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                JP   NZ, RTypeBank3_7DFinishPass
                LD   A, RTYPE_7D_OPEN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #003F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DOpen:
                ; Descriptor offset = `((-timer)&$30) * 3/2`, поэтому четыре
                ; 48-byte группы выбираются без искусственной frame table.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                NEG
                AND  #30
                CALL RTypeBank3_7DSetDescriptorOffset
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                JP   NZ, RTypeBank3_7DFinishPass
                LD   A, RTYPE_7D_HOLD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #00C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DHold:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_VARIANT)
                CALL RTypeBank3_7DVariantTimesTwelve
                LD   DE, #382E
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeBank3_7DSpawnChild
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                JP   NZ, RTypeBank3_7DFinishPass
                LD   A, RTYPE_7D_CLOSE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #003F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DClose:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                AND  #30
                CALL RTypeBank3_7DSetDescriptorOffset
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                JP   NZ, RTypeBank3_7DFinishPass
                LD   A, RTYPE_7D_RETREAT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DRetreat:
                CALL RTypeBank3_7DSetBaseDescriptor
                JP   RTypeBank3_7DFinishPass

RTypeBank3_7DFinishPass:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_TIMER)
                OR   A
                JR   Z, .bounds
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_TIMER), A
                AND  3
                JR   NZ, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.bounds:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_7D_RETREAT
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0130
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank3_7DRemove

RTypeBank3_7DRemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; A=damage. Обычное попадание только уменьшает HP и запускает 16-pass flash;
; фатальное оставляет pool slot на месте и заменяет handler на paired `$E817`.
RTypeBank3_DamageEnemy7D68:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP)
                OR   A
                SBC  HL, DE
                JR   C, .destroy
                LD   A, H
                OR   L
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP), HL
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_TIMER), A
                RET
.destroy:      XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP + 1), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE817

RTypeBank3_7DSetBaseDescriptor:
                CALL RTypeBank3_7DBaseDescriptor
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_7DBaseDescriptor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_VARIANT)
                CALL RTypeBank3_7DVariantTimesTwelve
                LD   DE, #37E6
                ADD  HL, DE
                RET

; HL=variant (ROM currently stores 0/1), result HL=variant*12.
RTypeBank3_7DVariantTimesTwelve:
                ADD  HL, HL
                LD   D, H
                LD   E, L                       ; variant*2
                ADD  HL, HL                     ; *4
                ADD  HL, DE                     ; *6
                ADD  HL, HL                     ; *12
                RET

; A содержит `$00/$10/$20/$30`; к base прибавляется A+A/2.
RTypeBank3_7DSetDescriptorOffset:
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                PUSH DE
                CALL RTypeBank3_7DBaseDescriptor
                POP  DE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_7DSpawnChild:
                ; Только два exact hold-значения создают child; проверка идёт
                ; до DEC timer, поэтому кадры `$C0/$80` не сдвинуты на один.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                LD   DE, #00C0
                OR   A
                SBC  HL, DE
                JR   Z, .first
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                LD   DE, #0080
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   HL, #A45A
                LD   DE, -#0018
                LD   BC, -#0040
                JR   .variant
.first:        LD   HL, #A434
                LD   DE, -#0020
                LD   BC, -#0028
.variant:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_VARIANT)
                OR   A
                JR   Z, .parametersReady
                LD   A, H
                CP   #A4
                JR   NZ, .parametersReady
                ; Обе variant-1 script roots известны буквально; выбор по
                ; уже установленному root не требует ещё одного timer test.
                LD   A, L
                CP   #34
                LD   HL, #A484
                JR   Z, .parametersReady
                LD   HL, #A4B8
.parametersReady:
                LD   (RTypeBank3_8DScript), HL
                LD   (RTypeBank3_8DXVelocity), DE
                LD   (RTypeBank3_8DYVelocity), BC
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_7DParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_7DParentX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_7DParentY), HL
                LD   A, (RTypeBank3_7DParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank3_InitChild8D85
                LD   A, (RTypeBank3_7DParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; ----------------------------------------------------------------------------
; `$8D85/$8DC6/$8E15`: scripted -> terminal -> active child.
; ----------------------------------------------------------------------------

RTypeBank3_InitChild8D85:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_CHILD_8D85
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_7DParentX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_7DParentY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #3F26
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, (RTypeBank3_8DXVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank3_8DYVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL

                ; `$F5C1` начинает с word по root и исполняет три movement
                ; command за VBlank; phase-команды команды не расходуют.
                LD   HL, (RTypeBank3_8DScript)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A

                ; difficulty=0 выбирает четвёртую шестибайтную `$8E10`
                ; запись, то есть слова `$8E22/$8E24/$8E26`.
                LD   HL, #8E22
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIRE_A), DE
                LD   HL, #8E24
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIRE_B), DE
                LD   HL, #8E26
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_PROJECTILE_SCRIPT), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIRE_A)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIRE_COUNTER), HL

                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_PALETTE), A
                LD   A, #3E
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #3E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_ANIMATION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_ANIMATION + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_TARGET_PLAYER_NEXT), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIXED_DESCRIPTOR), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_TIMER), A
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP), HL
                LD   HL, #3F26
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateChild8D85:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_8D_SCRIPTED
                JP   Z, RTypeBank3_8DScripted
                CP   RTYPE_8D_TERMINAL
                JP   Z, RTypeBank3_8DTerminal
                JP   RTypeBank3_8DActive

RTypeBank3_8DScripted:
                CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_8DBeginTerminal
                CALL RTypeBank3_6FAddForegroundDelta
                LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                ADD  HL, DE
                LD   A, L
                AND  #0C
                SRL  A
                SRL  A                         ; phase 0…3
                CALL RTypeBank3_8DSetDescriptor3F26
                JP   RTypeBank3_8DPrepareDescriptor

RTypeBank3_8DBeginTerminal:
                LD   A, RTYPE_8D_TERMINAL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                RET

RTypeBank3_8DTerminal:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                AND  #18
                SRL  A
                SRL  A
                SRL  A                         ; `(timer & $18) >> 3`
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                      ; phase*6
                LD   E, A
                LD   D, 0
                LD   HL, #3F3E
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_8D_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP), HL
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                RET

RTypeBank3_8DActive:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank3_8DChooseTarget
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIXED_DESCRIPTOR)
                OR   A
                JR   Z, .animated
                LD   HL, #3F56
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JR   .descriptor
.animated:     LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                ADD  HL, DE
                LD   A, L
                AND  #18
                SRL  A
                SRL  A
                SRL  A
                CALL RTypeBank3_8DSetDescriptor3F56
.descriptor:   CALL RTypeBank3_8DPrepareDescriptor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_TIMER)
                OR   A
                JR   Z, .bounds
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_TIMER), A
                AND  3
                JR   NZ, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank3_8DRemove

RTypeBank3_8DChooseTarget:
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIXED_DESCRIPTOR), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_TARGET_PLAYER_NEXT)
                OR   A
                JR   Z, .randomTarget
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_TARGET_PLAYER_NEXT), A
                LD   HL, (RTypePlayerNativeX)
                LD   (RTypeBank3_8DTargetX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTypeBank3_8DTargetY), HL
                JR   .velocities
.randomTarget: CALL RTypeRng_Next
                LD   A, L
                AND  #0F
                LD   (RTypeBank3_8DTargetIndex), A
                CP   4
                JR   NC, .readTarget
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_TARGET_PLAYER_NEXT), A
.readTarget:   LD   A, (RTypeBank3_8DTargetIndex)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #3EE6
                ADD  HL, DE
                LD   (RTypeBank3_8DTargetPointer), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_8DTargetX), DE
                LD   HL, (RTypeBank3_8DTargetPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_8DTargetY), DE
.velocities:   LD   HL, (RTypeBank3_8DTargetX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank3_8DTargetY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, #0080
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                RET

RTypeBank3_8DSetDescriptor3F26:
                LD   HL, #3F26
                JR   RTypeBank3_8DSetDescriptorPhase

RTypeBank3_8DSetDescriptor3F56:
                LD   HL, #3F56

RTypeBank3_8DSetDescriptorPhase:
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                      ; phase*6
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_8DPrepareDescriptor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank3_8DRemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; A=damage. В scripted/terminal `$8D85` не теряет HP: первый scripted hit
; лишь ставит `$8DC6`. Только active state получает обычный четырёхочковый HP.
RTypeBank3_DamageChild8D85:
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_8D_SCRIPTED
                JP   Z, RTypeBank3_8DBeginTerminal
                CP   RTYPE_8D_TERMINAL
                RET  Z
                LD   A, B
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP)
                OR   A
                SBC  HL, DE
                JR   C, .destroy
                LD   A, H
                OR   L
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP), HL
                LD   A, #0C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1), A
                LD   HL, -#0300
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #00B0
                OR   A
                SBC  HL, DE
                BIT  7, H
                JR   NZ, .belowTarget
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FIXED_DESCRIPTOR), A
                SRL  H
                RR   L
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                RET
.belowTarget:  XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                RET
.destroy:      XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP + 1), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE817

; ----------------------------------------------------------------------------
; `$696E/$69B4/$6A78`: Stage 4 scripted terrain enemy.
; ----------------------------------------------------------------------------

RTypeBank3_InitTerrainEnemy696E:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TERRAIN_ENEMY_696E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #8DD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   HL, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL

                ; High command nibble после `>>2` является byte offset в
                ; паре `(motion_root, command_count)` `$92AC/$92AE`.
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                SRL  A
                SRL  A
                LD   (RTypeBank3_69MotionOffset), A
                LD   E, A
                LD   D, 0
                LD   HL, #92AC
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), DE
                EX   DE, HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, (RTypeBank3_69MotionOffset)
                LD   E, A
                LD   D, 0
                LD   HL, #92AE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadByte
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_TIMER), A

                LD   HL, #9294
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), DE
                LD   A, #2A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_PALETTE), A
                LD   HL, #2D8C
                CALL RTypeWorldRom_ReadByte
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_HP), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_HP + 1), A
                LD   HL, #2DD0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateTerrainEnemy696E:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_69Remove
                CALL RTypeBank3_6FAddForegroundDelta
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent

                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                AND  #0F
                LD   (RTypeBank3_69Direction), A
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #2DD0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                LD   A, (RTypeBank3_69Direction)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #2D90
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank3_69ProbeX), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_69ProbeY), HL
                LD   BC, (RTypeBank3_69ProbeX)
                LD   DE, (RTypeBank3_69ProbeY)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0FA0
                OR   A
                SBC  HL, DE
                JR   NZ, .flash
                ; `$6A1D` заменяет полную 4-байтную cell: code `$09F6`,
                ; attribute `$0082`; ring address вычислен probe-вызовом.
                LD   HL, (RTypeTerrain_Address)
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   (HL), #F6
                INC  HL
                LD   (HL), #09
                INC  HL
                LD   (HL), #82
                INC  HL
                LD   (HL), #00
.flash:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_TIMER)
                OR   A
                RET  Z
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_TIMER), A
                AND  3
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                RET

RTypeBank3_69Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; A=damage; фатальный hit ставит обычный in-place `$E7BE`.
RTypeBank3_DamageTerrainEnemy696E:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_HP)
                OR   A
                SBC  HL, DE
                JR   C, .destroy
                LD   A, H
                OR   L
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_HP), HL
                LD   A, #0C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_TIMER), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$8F5E/$8F86/$90A2/$90E0`: четырёхнаправленный Stage 4 enemy.
;
; Координаты и начальное направление берутся из World ROM без адаптации.
; Нормальная ветка движется в Q8, выбирает четырёхкадровый descriptor и
; стирает под собой до четырёх cells `$09F6`. При пересечении узкой полосы
; около R-9 объект на 31 update переходит в одну из 16 ROM-дуг разворота.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy8F5E:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_8F5E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8230
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL

                ; Low command nibble индексирует общую Stage 4 position table
                ; `$8DD0`: каждая запись содержит native X/Y words.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   (RTypeBank3_8FPositionIndex), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #8DD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                ; Та же исходная index выбирает byte направления `$3F76`.
                LD   A, (RTypeBank3_8FPositionIndex)
                LD   E, A
                LD   D, 0
                LD   HL, #3F76
                ADD  HL, DE
                CALL RTypeWorldRom_ReadByte
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_NEXT_DIRECTION), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TABLE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TABLE + 1), A
                LD   HL, #4006
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #2E
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #4006
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy8F5E:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER)
                LD   A, H
                OR   L
                JP   NZ, RTypeBank3_8FTurnUpdate

                ; Difficulty RAM target пока равен нулю: `$3F86` содержит
                ; четыре пары signed Q8 `(vx,vy)`, по четыре bytes на direction.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #3F86
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8X
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank3_6FAddForegroundDelta

                ; Горизонтальные directions 0/1 реагируют на unsigned полосу
                ; `x+16-player_x < $20`; вертикальные 2/3 — на
                ; `y+4-player_y < 8`. Отрицательное смещение после wrap не
                ; считается близостью: это точная семантика V30 `JB/JAE`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION)
                BIT  1, A
                JR   NZ, .verticalDirection
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0010
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                OR   A
                SBC  HL, DE
                JP   NC, RTypeBank3_8FNormalDescriptor
                LD   A, 2
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                JR   C, .nextDirectionReady
                INC  A                           ; self.y >= player.y -> 3
                JR   .nextDirectionReady
.verticalDirection:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 4
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                LD   DE, 8
                OR   A
                SBC  HL, DE
                JP   NC, RTypeBank3_8FNormalDescriptor
                XOR  A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   C, .nextDirectionReady
                INC  A                           ; self.x >= player.x -> 1
.nextDirectionReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_NEXT_DIRECTION), A
                LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER), HL

                ; matrix index = current*4+next, word pointer at `$3FC6`.
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION)
                ADD  A, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #3FC6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TABLE), DE

                ; `$9075` не возвращается, а сразу входит в `$90A2`: поэтому
                ; на entry-frame foreground delta прибавляется второй раз.

RTypeBank3_8FTurnUpdate:
                CALL RTypeBank3_6FAddForegroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TABLE)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER)
                BIT  4, E
                JR   Z, .turnDescriptorReady
                INC  HL
                INC  HL
.turnDescriptorReady:
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_TURN_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_NEXT_DIRECTION)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION), A
                RET

RTypeBank3_8FNormalDescriptor:
                ; `$4006 + direction*24 + frame*6`, где frame — bits2..3
                ; глобального VBlank counter. Все операции здесь byte-safe:
                ; максимальный offset равен `$5A`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8F_DIRECTION)
                LD   B, A
                ADD  A, A                       ; *2
                ADD  A, B                       ; *3
                ADD  A, A                       ; *6
                ADD  A, A                       ; *12
                ADD  A, A                       ; *24
                LD   B, A
                LD   A, (FrameCounter)
                AND  #0C
                LD   C, A
                SRL  A
                ADD  A, C                       ; `(counter&$0C)*3/2`
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #4006
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeBank3_8FClearFourCells
                CALL RTypeWalker_InsideBounds
                RET  NC

RTypeBank3_8FRemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$90E0` начинает с terrain address для `(x-4,y+4)`. Горизонтальные соседи
; вычисляются изменением только low byte (BL), поэтому `$..FE+4 -> $..02` не
; переносит carry в строку; переход вниз, наоборот, добавляет ровно `$0100`.
RTypeBank3_8FClearFourCells:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   BC, -4
                ADD  HL, BC
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 4
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeBank3_8FTerrainCell), HL
                CALL RTypeBank3_8FClearCell

                LD   HL, (RTypeBank3_8FTerrainCell)
                LD   A, L
                ADD  A, 4
                LD   L, A                       ; byte-wise BL arithmetic
                LD   (RTypeBank3_8FTerrainCell), HL
                CALL RTypeBank3_8FClearCell

                LD   HL, (RTypeBank3_8FTerrainCell)
                INC  H                           ; add `$0100`
                LD   A, H
                AND  #3F                        ; 16-КБ vertical ring wrap
                LD   H, A
                LD   (RTypeBank3_8FTerrainCell), HL
                CALL RTypeBank3_8FClearCell

                LD   HL, (RTypeBank3_8FTerrainCell)
                LD   A, L
                SUB  4
                LD   L, A                       ; снова без borrow в H
                JP   RTypeBank3_8FClearCell

; HL=14-bit byte offset в foreground ring page. Меняются все четыре bytes
; только если младшие 12 бит tile code равны `$09F6`; верхние code flags
; участвуют в чтении, но не мешают сравнению — как `AND AX,$0FFF` в `$90E0`.
RTypeBank3_8FClearCell:
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                AND  #0F
                CP   #09
                RET  NZ
                LD   A, E
                CP   #F6
                RET  NZ
                DEC  HL
                LD   (HL), #A0
                INC  HL
                LD   (HL), #0F
                INC  HL
                LD   (HL), #00
                INC  HL
                LD   (HL), #00
                RET

RTypeBank3_DamageEnemy8F5E:
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$8469/$8490`: Stage 7 enemy, скользящий вдоль foreground-стен.
;
; В свободном пространстве он движется влево с Q8 `-$0200`. Solid cell слева
; останавливает X и выбирает вертикаль `±$0100` по чётности VBlank. После
; выхода из стены ещё восемь pass сохраняется вертикальное движение; solid
; probe на `y±$18` отражает знак скорости. Стрельба — общий literal `$F63A`.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy8469:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_8469
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL

                ; Low nibble выбирает одно Y-word из `$8DB0`.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8DB0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                ; High nibble индексирует шестибайтную fire-запись `$8E10`:
                ; trigger A, upper limit B и 16-direction velocity table.
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B                       ; *3
                ADD  A, A                       ; *6
                LD   E, A
                LD   D, 0
                LD   HL, #8E10
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), DE

                ; `$F8A7`: `(rng.next()*4) & (fire_a-1)`. Маска применяется
                ; к обоим bytes word, а RNG обновляется ровно один раз.
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL

                LD   HL, -#0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_84_PAUSE_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #39A6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #18
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #18
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #39A6
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy8469:
                ; `$8490` сначала применяет foreground scroll, затем обе Q8
                ; скорости и только после этого вызывает общую стрельбу.
                CALL RTypeBank3_6FAddForegroundDelta
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent

                ; Левый probe находится на `(x-$20,y)`. Tile codes ниже
                ; `$0DFC` считаются solid; `$0DFC…$0FFF` — свободный воздух.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   BC, -#0020
                ADD  HL, BC
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .freeLeft

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   A, H
                OR   L
                JR   NZ, .verticalProbe
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, -#0100
                LD   A, (FrameCounter)
                AND  1
                JR   Z, .verticalSelected
                LD   HL, #0100
.verticalSelected:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_84_PAUSE_TIMER), HL
                JR   .bounds

.verticalProbe:
                LD   DE, #0018
                BIT  7, H
                JR   Z, .probeOffsetReady
                LD   DE, -#0018
.probeOffsetReady:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                EX   DE, HL
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .bounds
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                XOR  A
                LD   D, A
                LD   E, A
                EX   DE, HL
                SBC  HL, DE                      ; `0 - y_velocity`
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                JR   .bounds

.freeLeft:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_84_PAUSE_TIMER)
                LD   A, H
                OR   L
                JR   Z, .resumeLeft
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_84_PAUSE_TIMER), HL
                JR   .bounds
.resumeLeft:   LD   HL, -#0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL

.bounds:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  NC

RTypeBank3_84Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageEnemy8469:
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$8561/$85B0/$865E`: Stage 5 composite shooter и общий child `$E6AB`.
;
; Parent использует восемь paired phases `$39CE`, 30 HP и отдельный flash
; resource `$55`. Каждые N pass он создаёт straight child на `x-$10` и
; циклическом Y-offset из пяти ROM words `$39C4`. Child имеет priority `$6000`,
; resource `$02`, четыре paired phases `$84CE` и только Q8 X-скорость.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy8561:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_8561
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL

                ; `$FAC1` для этого handler-а берёт Y из `$941C[low nibble]`.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #941C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                ; Difficulty target сейчас нулевой: первая запись `$39B4`
                ; содержит child Q8 vx и spawn cadence.
                LD   HL, #39B4
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_RELOAD), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_COUNTER), DE

                LD   HL, -#0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_ANIMATION_BIAS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_ANIMATION_BIAS + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_Y_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_Y_PHASE + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_TIMER), A
                LD   A, #1E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_HP), A
                LD   HL, #39CE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL

                ; Порядок acquire точный: сначала `$55`, затем normal `$19`.
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_PALETTE), A
                LD   A, #19
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #19
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #39CE
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy8561:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X

                ; descriptor = `$39CE + (((frame+bias)&$70)>>4)*12`.
                LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_ANIMATION_BIAS)
                ADD  HL, DE
                LD   A, L
                AND  #70
                RRCA
                RRCA
                RRCA
                RRCA
                AND  7
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                ADD  A, A                       ; phase * 12
                LD   E, A
                LD   D, 0
                LD   HL, #39CE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                ; Flash timer уменьшается до проверки кадра. Если handler был
                ; активен на входе, кадр `(frame&3)==0` остаётся flash даже при
                ; переходе timer 1->0 — это заметная деталь `$85CD…$85EC`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_TIMER)
                OR   A
                JR   Z, .fire
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_TIMER), A
                LD   A, (FrameCounter)
                AND  3
                JR   NZ, .fire
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A

.fire:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_COUNTER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_COUNTER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank3_85SpawnShot

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank3_85Remove

RTypeBank3_85SpawnShot:
                ; Перезагрузка counter происходит до allocation: при полном
                ; pool cadence всё равно считается из нового периода.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FIRE_COUNTER), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_85ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0010
                ADD  HL, DE
                LD   (RTypeBank3_85ShotX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_85ShotY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_VELOCITY)
                LD   (RTypeBank3_85ShotVelocity), HL

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_Y_PHASE)
                LD   DE, #39C4
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTypeBank3_85ShotY)
                ADD  HL, DE
                LD   (RTypeBank3_85ShotY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_Y_PHASE)
                INC  HL
                INC  HL
                LD   A, L
                CP   10
                JR   C, .phaseReady
                LD   HL, 0
.phaseReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_SHOT_Y_PHASE), HL

                LD   A, (RTypeBank3_85ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_STRAIGHT_SHOT_E6AB
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #6000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_85ShotX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_85ShotY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank3_85ShotVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, #84CE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #02
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #02
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #84CE
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_85ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_UpdateStraightShotE6AB:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   A, (FrameCounter)
                AND  6
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                       ; `(frame&6)*6`
                LD   E, A
                LD   D, 0
                LD   HL, #84CE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeWalker_InsideBounds
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_85Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; A=damage. Активный Python хранит remaining HP; это эквивалентно ROM
; accumulator `+$1F` до порога `+$2F=$1E`, но удобнее для общего collision API.
RTypeBank3_DamageEnemy8561:
                OR   A
                RET  Z
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_HP)
                SUB  B
                JR   C, .destroy
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_HP), A
                LD   A, 7
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_TIMER), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE817

; ----------------------------------------------------------------------------
; `$5CEA/$5D2D/$5D9A`: горизонтальный стрелок Stages 5/7.
;
; Parent перемещается Q8 `-$0200`, анимируется восемью single descriptors
; `$299A` и каждые `$0030` pass создаёт уже общий `$E6AB` без Y-offset.
; Инициализатор всё равно потребляет один RNG и сохраняет `$30…$4F`: поле не
; участвует в runtime `$5D2D`, но его наличие важно для общей RNG-последовательности.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy5CEA:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_5CEA
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8DB0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                LD   HL, #298A                  ; difficulty-zero pair
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_SHOT_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_RELOAD), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_COUNTER), DE
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                ADD  A, #30
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_RANDOM_DELAY), HL

                LD   HL, -#0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, #299A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #0E
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #0E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #299A
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy5CEA:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                ; `$299A + ((frame&$1C)>>2)*6` = base + raw*3/2.
                LD   A, (FrameCounter)
                AND  #1C
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #299A
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_COUNTER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_COUNTER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank3_5CSpawnShot
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_5CSpawnShot:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_FIRE_COUNTER), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_85ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_85ShotX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_85ShotY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5C_SHOT_VELOCITY)
                LD   (RTypeBank3_85ShotVelocity), HL
                LD   A, (RTypeBank3_85ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_STRAIGHT_SHOT_E6AB
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #6000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_85ShotX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_85ShotY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank3_85ShotVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, #84CE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #02
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #02
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #84CE
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_85ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_DamageEnemy5CEA:
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$5EED/$5F3C/$5FD5`: Stage 6 cardinal terrain enemy.
;
; Command задаёт одну из 16 position/direction records, скорость, сторону
; поворота и mirrored descriptor/ray. После Q8 шага объект проверяет максимум
; три foreground cells вдоль ROM-луча `$2A40`; первый solid sample поворачивает
; direction на `+1` или `-1` modulo 4. Sprite всегда состоит из двух descriptors.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy5EED:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_5EED
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #4030
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL

                ; Шестибайтная запись `$9324`: X, Y, direction word.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                       ; index * 6
                LD   E, A
                LD   D, 0
                LD   HL, #9324
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   A, E
                AND  3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_DIRECTION), A

                ; Word command bit8 выбирает clockwise, low-byte bit6 mirror.
                LD   HL, (RTypeWorldLastCommand)
                XOR  A
                BIT  0, H
                JR   Z, .clockwiseReady
                INC  A
.clockwiseReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_TURN_CLOCKWISE), A
                XOR  A
                BIT  6, L
                JR   Z, .mirrorReady
                INC  A
.mirrorReady:  LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_MIRRORED), A

                ; Bits4..5 дают word offset 0,2,4,6 в speed table `$931C`.
                LD   A, L
                AND  #30
                RRCA
                RRCA
                RRCA                         ; `$10->$02`, `$20->$04`
                AND  6
                LD   E, A
                LD   D, 0
                LD   HL, #931C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_SPEED_OFFSET), DE
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_TIMER), A
                LD   HL, 10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_HP), HL

                LD   HL, #2AC0
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_MIRRORED)
                OR   A
                JR   Z, .descriptorReady
                LD   HL, #2AF0
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #51
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_PALETTE), A
                LD   A, #28
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #28
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy5EED:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A

                ; Velocity address = `$2A80 + speed_offset + direction*4`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_DIRECTION)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_SPEED_OFFSET)
                ADD  HL, DE
                LD   DE, #2A80
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8X
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank3_6FAddForegroundDelta

                LD   HL, #2AC0
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_MIRRORED)
                OR   A
                JR   Z, .baseReady
                LD   HL, #2AF0
.baseReady:    LD   A, (FrameCounter)
                AND  #18
                LD   B, A
                SRL  A
                ADD  A, B                       ; `(frame&$18)*3/2`
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                ; Flash выбирается по уже уменьшенному `(timer&4)==0`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_TIMER)
                OR   A
                JR   Z, .ray
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_TIMER), A
                AND  4
                JR   NZ, .ray
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A

.ray:          CALL RTypeBank3_5ERayBlocked
                JR   NC, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_DIRECTION)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_TURN_CLOCKWISE)
                OR   A
                LD   A, B
                JR   Z, .counterClockwise
                INC  A
                AND  3
                JR   .storeDirection
.counterClockwise:
                DEC  A
                AND  3
.storeDirection:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_DIRECTION), A

.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank3_5ERemove

; Carry=1, если один из трёх samples solid. При X >= `$02C0` sample считается
; воздухом `$0FA0`, но координаты луча всё равно продвигаются перед итерацией.
RTypeBank3_5ERayBlocked:
                LD   HL, #2A40
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_MIRRORED)
                OR   A
                JR   Z, .mirrorOffsetReady
                LD   DE, #0020
                ADD  HL, DE
.mirrorOffsetReady:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_DIRECTION)
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank3_5EProbeX), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_5EProbeY), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_5ERepeatX), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_5ERepeatY), DE
                LD   A, 3
                LD   (RTypeBank3_5EIterations), A
.nextSample:   LD   HL, (RTypeBank3_5EProbeX)
                LD   DE, #02C0
                OR   A
                SBC  HL, DE
                JR   NC, .airCode
                LD   BC, (RTypeBank3_5EProbeX)
                LD   DE, (RTypeBank3_5EProbeY)
                CALL RTypeTerrain_ForegroundCode
                JR   .codeReady
.airCode:      LD   HL, #0FA0
.codeReady:    LD   (RTypeBank3_5EProbeCode), HL
                LD   HL, (RTypeBank3_5EProbeX)
                LD   DE, (RTypeBank3_5ERepeatX)
                ADD  HL, DE
                LD   (RTypeBank3_5EProbeX), HL
                LD   HL, (RTypeBank3_5EProbeY)
                LD   DE, (RTypeBank3_5ERepeatY)
                ADD  HL, DE
                LD   (RTypeBank3_5EProbeY), HL
                LD   HL, (RTypeBank3_5EProbeCode)
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .sampleFree
                SCF
                RET
.sampleFree:
                LD   A, (RTypeBank3_5EIterations)
                DEC  A
                LD   (RTypeBank3_5EIterations), A
                JR   NZ, .nextSample
                OR   A                            ; carry=0
                RET

RTypeBank3_5ERemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageEnemy5EED:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_HP)
                OR   A
                SBC  HL, DE
                JR   C, .destroy
                LD   A, H
                OR   L
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_HP), HL
                LD   A, #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_TIMER), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE817

; ----------------------------------------------------------------------------
; `$7182/$71C7`: 16-direction Stage 5 seeker.
;
; Пока active timer `$0280` ненулевой, каждые `$0010` pass direction сдвигается
; ровно на один сектор к R-9. Скорости берутся из ROM-root `$320E`, descriptor
; равен `$3216+6*direction`, стрельба использует общий `$F63A/$E601`.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy7182:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_7182
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   (RTypeBank3_71PositionIndex), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #8DD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                ; Fire record `$8E10[high nibble]`, затем один `$F8A7` RNG.
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8E10
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL

                LD   A, (RTypeBank3_71PositionIndex)
                LD   E, A
                LD   D, 0
                LD   HL, #31FE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadByte
                AND  #0F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_DIRECTION), A
                LD   HL, #31F6                  ; difficulty-zero cadence
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_RELOAD), DE
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_COUNTER), HL
                LD   HL, #0280
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_ACTIVE_TIMER), HL
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                CALL RTypeBank3_71SetDescriptor
                LD   A, #44
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #44
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy7182:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_ACTIVE_TIMER)
                LD   A, H
                OR   L
                JR   Z, .integrate
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_ACTIVE_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_COUNTER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_COUNTER), HL
                LD   A, H
                OR   L
                JR   NZ, .integrate

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                SRL  A
                SRL  A
                LD   (RTypeBank3_71TargetDirection), A
                LD   C, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_DIRECTION)
                LD   B, A
                LD   A, C
                CP   B
                JR   C, .turnDown
                CP   8
                JR   C, .turnUp
                SUB  8
                CP   B
                JR   C, .turnUp
.turnDown:     LD   A, B
                DEC  A
                JR   .directionReady
.turnUp:       LD   A, B
                INC  A
.directionReady:
                AND  #0F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_DIRECTION), A

                LD   B, A
                ADD  A, A
                ADD  A, A
                LD   C, A                       ; direction * 4
                LD   HL, #320E
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL                     ; HL=velocity root
                LD   E, C
                LD   D, 0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_TURN_COUNTER), HL

.integrate:    LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank3_71SetDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                CALL RTypeWalker_InsideBounds
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_71SetDescriptor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_71_DIRECTION)
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                       ; direction * 6
                LD   E, A
                LD   D, 0
                LD   HL, #3216
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_DamageEnemy7182:
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$7294/$72D2/$73DB`: Stage 6 terrain-reflecting shooter.
;
; Направления 0/1 образуют горизонтальную пару, 2/3 — вертикальную. Probe из
; `$32AE` инвертирует младший бит сначала при выходе за native bounds, затем
; ещё раз при code `>= $0DFC`. Это именно две независимые проверки ROM, а не
; объединённое условие. Выстрел создаёт специальный `$7435`, не общий `$E601`.
; ----------------------------------------------------------------------------

RTypeBank3_InitEnemy7294:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ENEMY_7294
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #4020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL

                ; Общая fire-запись `$8E10[command high nibble]` и буквальный
                ; `(F8A7()*4)&(fire_a-1)` задают первый момент выстрела.
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                       ; index * 6
                LD   E, A
                LD   D, 0
                LD   HL, #8E10
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL

                ; Low nibble выбирает `(X,Y)` в `$93DC`; command bit8 даёт
                ; начальное cardinal direction 0 либо 2.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #93DC
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, (RTypeWorldLastCommand)
                LD   A, H
                AND  1
                ADD  A, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION), A

                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_ANIMATION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_ANIMATION + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_TIMER), A
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_HP), HL
                CALL RTypeBank3_72SetDescriptor

                ; Порядок acquire важен для FIFO resource slots: normal `$43`
                ; захватывается раньше flash `$55`, как в `$7294`.
                LD   A, #43
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #43
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_PALETTE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateEnemy7294:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                CALL RTypeBank3_6FAddForegroundDelta

                ; `$329E + direction*4` хранит signed Q8 `(vx,vy)`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #329E
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8X
                CALL RTypeObjects_ReadWordNext
                CALL RTypeProjectile_AddQ8Y

                ; Раз в восемь кадров animation += 6; `$1E` — sentinel,
                ; поэтому реально выдаются offsets 0,6,$0C,$12,$18.
                LD   A, (FrameCounter)
                AND  7
                JR   NZ, .animationReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_ANIMATION)
                LD   DE, 6
                ADD  HL, DE
                LD   A, L
                CP   #1E
                JR   NZ, .storeAnimation
                LD   HL, 0
.storeAnimation:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_ANIMATION), HL
.animationReady:
                CALL RTypeBank3_72SetDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor

                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeBank3_SpawnProjectile7435
                CALL RTypeBank3_72ReflectTerrain

                ; Flash видим по уже уменьшенному `(timer&3)==0`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_TIMER)
                OR   A
                JR   Z, .bounds
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_TIMER), A
                AND  3
                JR   NZ, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank3_72Remove

RTypeBank3_72SetDescriptor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION)
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #32BE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL                     ; HL=direction descriptor base
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_ANIMATION)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_72ReflectTerrain:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #32AE
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank3_72ProbeX), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_72ProbeY), HL

                ; Unsigned native bounds. При outside инверсия выполняется,
                ; но terrain lookup ниже всё равно использует тот же probe.
                LD   HL, (RTypeBank3_72ProbeX)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTypeBank3_72ProbeX)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                JR   NC, .outside
                LD   HL, (RTypeBank3_72ProbeY)
                LD   DE, #007C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTypeBank3_72ProbeY)
                LD   DE, #0194
                OR   A
                SBC  HL, DE
                JR   C, .terrain
.outside:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION)
                XOR  1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION), A
.terrain:      LD   BC, (RTypeBank3_72ProbeX)
                LD   DE, (RTypeBank3_72ProbeY)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION)
                XOR  1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_DIRECTION), A
                RET

; `$73DB->$7435`: специализированный allocator почти совпадает с `$F63A`,
; но handler, descriptor stream, terrain delay и collision table иные. Новый
; priority `$A000` исполняется здесь немедленно; BORN не допускает второй Q8
; шаг, когда scheduler позже дойдёт до projectile band в том же VBlank.
RTypeBank3_SpawnProjectile7435:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT)
                LD   A, H
                OR   L
                RET  Z
                LD   (RTypeObjects_ProjectileVelocityTable), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeObjects_ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeDirection_Offset
                LD   (RTypeObjects_ProjectileDirection), A
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_PROJECTILE_7435
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
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                LD   A, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_74_TERRAIN_DELAY), A
                CALL RTypeBank3_UpdateProjectile7435Core
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeObjects_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_UpdateProjectile7435:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BORN)
                LD   DE, (FrameCounter)
                OR   A
                SBC  HL, DE
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                LD   A, H
                OR   L
                JP   NZ, RTypeProjectile_UpdateBurst

RTypeBank3_UpdateProjectile7435Core:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y

                ; `$327E + 6*(((frame+phase_seed)&$18)>>3)`.
                LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_PHASE)
                ADD  HL, DE
                LD   A, L
                AND  #18
                SRL  A
                SRL  A
                SRL  A
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #327E
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                ; В отличие от `$E601`, `$7435` читает текущий frame без +1.
                LD   A, (FrameCounter)
                AND  1
                JR   NZ, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_74_TERRAIN_DELAY)
                OR   A
                JR   Z, .probe
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_74_TERRAIN_DELAY), A
                JR   .bounds
.probe:        LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_74BeginBurst
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_74BeginBurst
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank3_74Remove

RTypeBank3_74BeginBurst:
                LD   HL, #000A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                RET

RTypeBank3_DamageProjectile7435:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                LD   A, H
                OR   L
                RET  NZ
                JR   RTypeBank3_74BeginBurst

RTypeBank3_74Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_72Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageEnemy7294:
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_HP)
                OR   A
                SBC  HL, DE
                JR   C, .destroy
                LD   A, H
                OR   L
                JR   Z, .destroy
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_HP), HL
                LD   A, #0C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_TIMER), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$8C12…$8D54`: четыре взрыва и буквальный модификатор terrain ring Stage 7.
;
; Контроллер невидим. Начальный timer — `(F8A7()&$FF)*2`; следующие интервалы
; равны `$10,$08,$10,$20`. Последняя фаза создаёт resource-$63 `$E80C` и
; применяет список `(bytewise delta, tile code)` к живой foreground page #07.
; ----------------------------------------------------------------------------

RTypeBank3_InitStageObject8C12:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_STAGE_OBJECT_8C12
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #DFFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL

                ; `$93C4[index&7] = Y, terrain-path`.
                LD   A, (RTypeWorldLastCommand)
                AND  7
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #93C4
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TERRAIN_PATH), DE
                CALL RTypeRng_Next
                LD   H, 0
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateStageObject8C12:
                CALL RTypeBank3_6FAddForegroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_PHASE)
                OR   A
                JR   Z, .phase0
                CP   1
                JR   Z, .phase1
                CP   2
                JR   Z, .phase2
                CP   3
                JR   Z, .phase3
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.phase0:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 14
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnY), HL
                XOR  A                           ; `$E7BE`
                CALL RTypeBank3_8CSpawnExplosion
                LD   HL, #0010
                JR   .finishPhase
.phase1:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0010
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_8CSpawnY), HL
                XOR  A
                CALL RTypeBank3_8CSpawnExplosion
                LD   HL, #0008
                JR   .finishPhase
.phase2:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -4
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnY), HL
                XOR  A
                CALL RTypeBank3_8CSpawnExplosion
                LD   HL, #0010
                JR   .finishPhase
.phase3:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_8CSpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_8CSpawnY), HL
                LD   A, 1                        ; `$E80C`, resource `$63`
                CALL RTypeBank3_8CSpawnExplosion
                CALL RTypeBank3_8CApplyTerrainPath
                LD   HL, #0020
.finishPhase:  LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TIMER), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_PHASE)
                INC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_PHASE), A
                RET

; A=0 создаёт `$E7BE`, A=1 — `$E80C`, A=2 — `$F000/$E7B6`,
; A=3 — обычный `$8010/$E817`, A=4 — обычный `$8010/$E7B6`. Координаты
; заранее сохранены, потому
; что allocator занимает общий scratch новой записью. Оба explosion priority
; `$8010` уже прошли к моменту `$DFFF/$8C2E`, поэтому initializer не делает
; первый animation tick немедленно.
RTypeBank3_8CSpawnExplosion:
                LD   (RTypeBank3_8CEffect), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_8CParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JP   C, .restore
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_8CSpawnX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_8CSpawnY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, (RTypeBank3_8CEffect)
                OR   A
                JR   Z, .e7be
                CP   1
                JR   Z, .e80c
                CP   2
                JR   Z, .e7b6F000
                CP   3
                JR   NZ, .e7b6
.e817:         LD   HL, #85FA
                LD   B, 1
                LD   C, #01
                JR   .effectReady
.e80c:         LD   HL, #85FA
                LD   B, 1
                LD   C, #63
                JR   .effectReady
.e7b6F000:    LD   HL, #F000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
.e7b6:
                LD   HL, #8506
                LD   B, 2
                LD   C, #01
                JR   .effectReady
.e7be:
                LD   HL, #8530
                LD   B, 2
                LD   C, #01
                JR   .effectReady
.effectReady:  LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                LD   A, B
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL
                LD   A, C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_8CParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; `$8D54`: delta складывается с ring-адресом раздельно по байтам, перенос из
; low byte намеренно теряется. После сложения маскируются только 14 адресных
; бит, затем пишутся `tile code` и literal attribute `$000A`.
RTypeBank3_8CApplyTerrainPath:
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeBank3_8CTerrainAddress), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8C_TERRAIN_PATH)
                LD   (RTypeBank3_8CTerrainPointer), HL
.nextCell:     LD   HL, (RTypeBank3_8CTerrainPointer)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                RET  Z
                LD   HL, (RTypeBank3_8CTerrainAddress)
                LD   A, L
                ADD  A, E
                LD   L, A
                LD   A, H
                ADD  A, D
                AND  #3F
                LD   H, A
                LD   (RTypeBank3_8CTerrainAddress), HL
                LD   HL, (RTypeBank3_8CTerrainPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_8CTerrainCode), DE
                LD   HL, (RTypeBank3_8CTerrainPointer)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTypeBank3_8CTerrainPointer), HL
                LD   HL, (RTypeBank3_8CTerrainAddress)
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   DE, (RTypeBank3_8CTerrainCode)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                INC  HL
                LD   (HL), #0A
                INC  HL
                LD   (HL), 0
                JR   .nextCell

; ----------------------------------------------------------------------------
; `$6E9B/$6EC4/$6F32`: фиксированный восьмидескрипторный объект Stage 7.
;
; X сначала получает foreground scroll. До `$0280` Q8 `+$00C0` разрешён
; только когда probe `(x+$40,y)` свободен в обеих ring-картах; после `$0280`
; движение безусловно. Фатальный hit ставит `$E817` и создаёт 18 overlapping
; пар из `$301C` как независимые `$F000/$E7B6` explosions.
; ----------------------------------------------------------------------------

RTypeBank3_InitFixedLarge6E9B:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FIXED_LARGE_6E9B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #A000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0110
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0108
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #3042
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, #C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6E_HP), A
                LD   A, #54
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #54
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A

                ; Все четыре paired roots подготавливаются заранее; renderer
                ; каждый pass выдаёт их в порядке `$3042,$304E,$305A,$3066`.
                LD   HL, #3042
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #3048
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #304E
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #3054
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #305A
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #3060
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #3066
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #306C
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateFixedLarge6E9B:
                CALL RTypeBank3_6FAddForegroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0280
                OR   A
                SBC  HL, DE
                JR   NC, .move
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0040
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .bounds
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0040
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .bounds
.move:         LD   DE, #00C0
                CALL RTypeProjectile_AddQ8X
.bounds:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0108
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_6ERemove
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0300
                OR   A
                SBC  HL, DE
                RET  C
RTypeBank3_6ERemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageFixedLarge6E9B:
                OR   A
                RET  Z
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6E_HP)
                CP   B
                JR   C, .destroy
                JR   Z, .destroy
                SUB  B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6E_HP), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   HL, #301C
                LD   (RTypeBank3_6EDebrisPointer), HL
.spawnDebris:  LD   HL, (RTypeBank3_6EDebrisPointer)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                CP   #80
                JR   NZ, .haveDx
                LD   A, E
                OR   A
                JR   Z, .installDeath
.haveDx:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnX), HL
                LD   HL, (RTypeBank3_6EDebrisPointer)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnY), HL
                LD   A, 2                        ; `$F000/$E7B6`
                CALL RTypeBank3_8CSpawnExplosion
                LD   HL, (RTypeBank3_6EDebrisPointer)
                INC  HL
                INC  HL                         ; overlapping window +1 word
                LD   (RTypeBank3_6EDebrisPointer), HL
                JR   .spawnDebris
.installDeath: JP   RTypeBank3_ConvertCurrentToE817

; ----------------------------------------------------------------------------
; `$78F8/$7935/$799C…$7D45`: связанная formation Stage 5.
;
; Parent получает настоящий scheduler priority `$4100…$4400`, читает 11- или
; 17-record список `(initializer,delay)` и передаёт каждому ребёнку priority,
; уменьшающийся на единицу. Link хранит физический индекс предыдущей записи;
; flags 1/2 распространяют escape либо delayed follow даже после замены
; предыдущей части explosion-handler-ом.
; ----------------------------------------------------------------------------

RTypeBank3_InitFormation78F8:
                ; Priority выбирается до allocator и принадлежит самому parent.
                LD   HL, (RTypeWorldLastCommand)
                LD   A, H
                AND  3
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #34AE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_78ParentPriority), DE
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FORMATION_78_PARENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, (RTypeBank3_78ParentPriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_NEXT_PRIORITY), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HEAD), A

                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8DD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #9274
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_ROOT), DE
                LD   HL, #34B6
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_NEXT_PRIORITY)
                LD   BC, #4280
                EX   DE, HL
                OR   A
                SBC  HL, BC
                EX   DE, HL
                JR   NC, .sequenceReady
                LD   HL, #34E2
.sequenceReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_SEQUENCE), HL
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_TIMER), HL
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateFormation78Parent:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_SEQUENCE)
                LD   (RTypeBank3_78SequenceRecord), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_78Initializer), DE
                LD   HL, (RTypeBank3_78SequenceRecord)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_78Delay), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_NEXT_PRIORITY)
                LD   (RTypeBank3_78ChildPriority), HL
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_NEXT_PRIORITY), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HEAD)
                LD   (RTypeBank3_78PreviousIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_ROOT)
                LD   (RTypeBank3_78MotionRoot), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_78SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_78SourceY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_78ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank3_InitFormation78Child
                JR   C, .restore
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_78SpawnedIndex), A
.restore:      LD   A, (RTypeBank3_78ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, (RTypeBank3_78SpawnedIndex)
                CP   #FF
                JR   Z, .timer
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HEAD), A
.timer:        LD   HL, (RTypeBank3_78Delay)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .advance
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_SEQUENCE)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_SEQUENCE), HL
                RET

RTypeBank3_InitFormation78Child:
                LD   A, #FF
                LD   (RTypeBank3_78SpawnedIndex), A
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FORMATION_78_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, (RTypeBank3_78ChildPriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_LOGICAL_PRIORITY), HL
                LD   HL, (RTypeBank3_78SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_78SourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTypeBank3_78PreviousIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_PREVIOUS), A
                LD   HL, (RTypeBank3_78MotionRoot)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_TIMER + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DELAY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DELAY + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_STATE_FLAG), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_TIMER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_ANIMATION_SEED), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_ANIMATION_SEED + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   HL, (RTypeBank3_78Initializer)
                LD   DE, #799C
                OR   A
                SBC  HL, DE
                JR   Z, .first
                LD   HL, (RTypeBank3_78Initializer)
                LD   DE, #7A1E
                OR   A
                SBC  HL, DE
                JR   Z, .main
                LD   A, RTYPE_78_TERMINAL
                LD   HL, #371E
                LD   B, 6
                LD   C, #25
                JR   .configured
.first:        LD   A, RTYPE_78_FIRST
                LD   HL, #3526
                LD   B, #0E
                LD   C, #25
                JR   .configured
.main:         LD   A, RTYPE_78_MAIN
                LD   HL, #3676
                LD   B, 6
                LD   C, #26
.configured:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HP), A
                LD   A, C
                LD   (RTypeBank3_78ResourceType), A
                ; Активный Python удерживает flash slot раньше normal slot;
                ; порядок оставлен явным, чтобы FIFO resource manager совпал.
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_PALETTE), A
                LD   A, (RTypeBank3_78ResourceType)
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, (RTypeBank3_78ResourceType)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
                OR   A
                RET

RTypeBank3_UpdateFormation78Child:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_78_FIRST
                JP   Z, RTypeBank3_78First
                CP   RTYPE_78_MAIN
                JP   Z, RTypeBank3_78Main
                CP   RTYPE_78_TERMINAL
                JP   Z, RTypeBank3_78Terminal
                CP   RTYPE_78_MAIN_FOLLOW
                JP   Z, RTypeBank3_78MainFollow
                CP   RTYPE_78_TERMINAL_FOLLOW
                JP   Z, RTypeBank3_78TerminalFollow
                JP   RTypeBank3_78Escape

RTypeBank3_78First:
                CALL RTypeBank3_78AdvanceMotionTimer
                CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_78Remove
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                ADD  A, A                       ; phase * 12
                LD   E, A
                LD   D, 0
                LD   HL, #3526
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeBank3_78Finish

RTypeBank3_78Main:
                LD   B, RTYPE_78_MAIN_FOLLOW
                LD   HL, #3676
                JR   RTypeBank3_78Linked
RTypeBank3_78Terminal:
                LD   B, RTYPE_78_TERMINAL_FOLLOW
                LD   HL, #371E
RTypeBank3_78Linked:
                LD   (RTypeBank3_78EscapeBase), HL
                LD   A, B
                LD   (RTypeBank3_78FollowState), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DELAY)
                LD   A, H
                OR   L
                JR   Z, .readLink
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DELAY), HL
                LD   A, H
                OR   L
                JR   NZ, .runMotion
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                CP   9
                LD   HL, #A3E6
                JR   C, .installFollow
                LD   HL, #A380
.installFollow:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, (RTypeBank3_78FollowState)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypeBank3_78Flash
.readLink:     CALL RTypeBank3_78ReadPrevious
                LD   A, (RTypeBank3_78PreviousFlag)
                BIT  1, A
                JR   Z, .escapeCheck
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_STATE_FLAG), A
                LD   HL, (RTypeBank3_78PreviousDelay)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DELAY), HL
                LD   A, 3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                JR   .runMotion
.escapeCheck:  BIT  0, A
                JR   Z, .ordinary
                LD   HL, (RTypeBank3_78EscapeBase)
                CALL RTypeBank3_78BeginEscape
                JP   RTypeBank3_78Flash
.ordinary:     CALL RTypeBank3_78AdvanceMotionTimer
.runMotion:    CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_78Remove
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                LD   HL, (RTypeBank3_78EscapeBase)
                CALL RTypeBank3_78SetDescriptorPhase
                JP   RTypeBank3_78Finish

RTypeBank3_78MainFollow:
                LD   HL, #3676
                JR   RTypeBank3_78Follow
RTypeBank3_78TerminalFollow:
                LD   HL, #371E
RTypeBank3_78Follow:
                LD   (RTypeBank3_78EscapeBase), HL
                CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_78Remove
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                LD   HL, (RTypeBank3_78EscapeBase)
                CALL RTypeBank3_78SetDescriptorPhase
                JP   RTypeBank3_78Finish

RTypeBank3_78Escape:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_ANIMATION_SEED)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_ANIMATION_SEED), HL
                LD   A, L
                AND  #1E
                LD   B, A
                ADD  A, A
                ADD  A, B                       ; phase * 3
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DESCRIPTOR_BASE)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank3_78Remove
                JR   RTypeBank3_78Finish

; Motion cadence: `(counter+1)&$7F`, commands 1 для `$00…$1E`, иначе 2.
RTypeBank3_78AdvanceMotionTimer:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_TIMER)
                INC  HL
                LD   A, L
                AND  #7F
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_MOTION_TIMER), HL
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   A, L
                CP   #1F
                RET  NC
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                RET

RTypeBank3_78BeginEscape:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_DESCRIPTOR_BASE), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_STATE_FLAG), A
                LD   A, RTYPE_78_ESCAPE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_LOGICAL_PRIORITY)
                LD   A, L
                AND  #0F
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8FD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                CALL RTypeRng_Next
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_ANIMATION_SEED), HL
                RET

RTypeBank3_78SetDescriptorPhase:
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                       ; phase * 6
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank3_78Finish:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
RTypeBank3_78Flash:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_TIMER)
                OR   A
                RET  Z
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_TIMER), A
                AND  3
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                RET

RTypeBank3_78ReadPrevious:
                XOR  A
                LD   (RTypeBank3_78PreviousFlag), A
                LD   HL, 0
                LD   (RTypeBank3_78PreviousDelay), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_PREVIOUS)
                CP   #FF
                RET  Z
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_78_STATE_FLAG
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                LD   (RTypeBank3_78PreviousFlag), A
                LD   DE, RTYPE_OBJ_78_DELAY - RTYPE_OBJ_78_STATE_FLAG
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank3_78PreviousDelay), DE
                RET

RTypeBank3_78Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageFormation78Child:
                OR   A
                RET  Z
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HP)
                CP   B
                JR   C, .destroy
                JR   Z, .destroy
                SUB  B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HP), A
                LD   A, #0C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_TIMER), A
                RET
.destroy:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_78_FIRST
                LD   A, 2
                JR   NZ, .flagReady
                DEC  A
.flagReady:    LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_STATE_FLAG), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

; ----------------------------------------------------------------------------
; `$9660/$9674/$96E9…$9750`: финальный периодический spawner Stage 8.
;
; Event-object невидим и движется ровно на background delta. Младшие четыре
; бита команды выбирают period из `$943C`, bit4 — верхнюю/нижнюю стартовую Y.
; При нуле таймера `$1D89` выбирает одно из 16 направлений к R-9; velocity pair
; читается через difficulty-zero pointer `$4284`, а descriptor — из `$428C`.
; Child имеет собственный resource `$60`, двухкадровую анимацию и особый
; weapon-death `$973F`: тот же `$E7D4` stream `$8530`, но resource `$6B`.
; ----------------------------------------------------------------------------

RTypeBank3_InitFinalSpawner9660:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FINAL_SPAWNER_9660
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #0174
                LD   A, (RTypeWorldLastCommand)
                BIT  4, A
                JR   Z, .yReady
                LD   HL, #009C
.yReady:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL

                ; `$943C` содержит 16 unsigned periods; masking RNG словом
                ; `period-1` выполняется побайтно, как V30 AND AX,DX.
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #943C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_PERIOD), DE
                CALL RTypeRng_Next
                ; `$EDE9` использует D/E как рабочие oldA/oldB, поэтому mask
                ; перечитывается после RNG, иначе DE незаметно разрушится.
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_PERIOD)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_TIMER), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateFinalSpawner9660:
                ; Spawner принадлежит background plane, не foreground.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldBgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank3_96SpawnAimedChild
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  NC
                XOR  A                           ; невидимый parent resource не держит
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_96SpawnAimedChild:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_PERIOD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   (RTypeBank3_96SpawnX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                LD   (RTypeBank3_96SpawnY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_96ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeDirection_Offset
                LD   (RTypeBank3_96Direction), A

                ; Difficulty zero: `$4284` — pointer на 16 velocity pairs.
                LD   HL, #4284
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_96VelocityTable), DE
                LD   A, (RTypeBank3_96Direction)
                LD   E, A
                LD   D, 0
                LD   HL, (RTypeBank3_96VelocityTable)
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_96VelocityX), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_96VelocityY), DE

                ; В descriptor-table каждая запись word, поэтому direction
                ; byte-offset velocity-table делится на два, а не на четыре.
                LD   A, (RTypeBank3_96Direction)
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #428C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_96Descriptor), DE
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_FINAL_PROJECTILE_96E9
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_96SpawnX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_96SpawnY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank3_96VelocityX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank3_96VelocityY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, (RTypeBank3_96Descriptor)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_DESCRIPTOR_BASE), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   A, #60
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #60
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTYPE_PROJECTILE_COUNT)
                INC  HL
                LD   (RTYPE_PROJECTILE_COUNT), HL
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_96ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_UpdateFinalProjectile96E9:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_96_DESCRIPTOR_BASE)
                LD   A, (FrameCounter)
                AND  8
                JR   Z, .descriptorReady
                LD   DE, 6
                ADD  HL, DE
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                ; `$970C…$973E`: отдельный более широкий rectangle, не общий
                ; `$1D6B`: X `$012C…$02D3`, Y `$007C…$0193`.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_96RemoveChild
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                JR   NC, RTypeBank3_96RemoveChild
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #007C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_96RemoveChild
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0194
                OR   A
                SBC  HL, DE
                RET  C

RTypeBank3_96RemoveChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_DamageFinalProjectile96E9:
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                ; `$973F` не использует общий resource `$01`: animation stream
                ; тот же `$8530`, но palette/resource type обязан быть `$6B`.
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #6B
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #6B
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

; ----------------------------------------------------------------------------
; `$A71D…$B1D7`: три синхронизированных тела Stage 5, навесные пушки и debris.
;
; Все записи имеют priority `$8010`. Controller создаётся event-dispatcher-ом,
; а на первом scheduler-pass строит upper/middle/lower и три `$AC4C`. Индексы
; физических 64-байтных записей заменяют V30 pointers: attachment читает тело,
; body атомарно OR-ит arrived/completed bits controller-а. Это сохраняет кадр,
; в котором все три маршрута одновременно переходят к следующей секции.
; ----------------------------------------------------------------------------

RTypeBank3_InitMultipartA71D:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_A71D_CONTROLLER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                CALL RTypeRng_Next
                LD   DE, (RTypePlayerNativeY)
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                ADD  HL, DE
                LD   A, L
                AND  7
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_SELECTOR), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_SELECTOR + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_COMPLETED), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ARRIVED), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ADVANCE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateMultipartA71DController:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_A7_CONTROLLER_SPAWN
                JR   Z, RTypeBank3_A7SpawnAll
                CP   RTYPE_A7_CONTROLLER_ACTIVE
                JR   Z, .active
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_EXIT_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_EXIT_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.active:       XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ADVANCE), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_COMPLETED)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ARRIVED)
                OR   B
                AND  7
                CP   7
                JR   NZ, .checkCompleted
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ADVANCE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ARRIVED), A
.checkCompleted:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_COMPLETED)
                AND  7
                CP   7
                RET  NZ
                LD   A, RTYPE_A7_CONTROLLER_EXIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_EXIT_TIMER), HL
                RET

RTypeBank3_A7SpawnAll:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_A7ControllerIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_SELECTOR)
                LD   (RTypeBank3_A7Selector), HL
                CALL RTypeObjects_StoreScratch
                ; Upper: selector+$5ABA, bit1, render `$5A02`, debris `$58EE`.
                XOR  A
                LD   (RTypeBank3_A7BodyKind), A
                LD   A, 1
                LD   (RTypeBank3_A7BodyBit), A
                LD   HL, #5A02
                LD   (RTypeBank3_A7BodyRender), HL
                LD   HL, #58EE
                LD   (RTypeBank3_A7BodyDebrisRoot), HL
                LD   HL, (RTypeBank3_A7Selector)
                LD   DE, #5ABA
                ADD  HL, DE
                LD   (RTypeBank3_A7RouteRecord), HL
                CALL RTypeBank3_A7SpawnBody

                ; Middle: bit2 и две attached guns fire-index 3/4.
                LD   A, 1
                LD   (RTypeBank3_A7BodyKind), A
                LD   A, 2
                LD   (RTypeBank3_A7BodyBit), A
                LD   HL, #5A46
                LD   (RTypeBank3_A7BodyRender), HL
                LD   HL, #594E
                LD   (RTypeBank3_A7BodyDebrisRoot), HL
                LD   HL, (RTypeBank3_A7Selector)
                LD   DE, #5ABC
                ADD  HL, DE
                LD   (RTypeBank3_A7RouteRecord), HL
                CALL RTypeBank3_A7SpawnBody
                LD   HL, -#0020
                LD   (RTypeBank3_A7AttachDX), HL
                LD   HL, -#0028
                LD   (RTypeBank3_A7AttachDY), HL
                LD   A, 3
                LD   (RTypeBank3_A7AttachFireIndex), A
                CALL RTypeBank3_A7SpawnAttachment
                LD   HL, -#0018
                LD   (RTypeBank3_A7AttachDX), HL
                LD   HL, -#0040
                LD   (RTypeBank3_A7AttachDY), HL
                LD   A, 4
                LD   (RTypeBank3_A7AttachFireIndex), A
                CALL RTypeBank3_A7SpawnAttachment

                ; Lower: bit4 и одна attached gun.
                LD   A, 2
                LD   (RTypeBank3_A7BodyKind), A
                LD   A, 4
                LD   (RTypeBank3_A7BodyBit), A
                LD   HL, #5A82
                LD   (RTypeBank3_A7BodyRender), HL
                LD   HL, #59A6
                LD   (RTypeBank3_A7BodyDebrisRoot), HL
                LD   HL, (RTypeBank3_A7Selector)
                LD   DE, #5ABE
                ADD  HL, DE
                LD   (RTypeBank3_A7RouteRecord), HL
                CALL RTypeBank3_A7SpawnBody
                LD   HL, -#0048
                LD   (RTypeBank3_A7AttachDX), HL
                LD   HL, #0018
                LD   (RTypeBank3_A7AttachDY), HL
                LD   A, 3
                LD   (RTypeBank3_A7AttachFireIndex), A
                CALL RTypeBank3_A7SpawnAttachment

                LD   A, (RTypeBank3_A7ControllerIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, RTYPE_A7_CONTROLLER_ACTIVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank3_A7SpawnBody:
                LD   HL, (RTypeBank3_A7RouteRecord)
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_A7RouteList), DE
                EX   DE, HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_A7MotionPointer), DE
                EX   DE, HL
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7VelocityX), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7VelocityY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7MotionTimer), DE
                CALL RTypeObjects_New
                RET  C
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_A7LastBodyIndex), A
                LD   A, RTYPE_OBJ_A71D_BODY
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTypeBank3_A7BodyX), HL
                LD   HL, #0108
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   (RTypeBank3_A7BodyY), HL
                LD   HL, (RTypeBank3_A7BodyRender)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, (RTypeBank3_A7VelocityX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank3_A7VelocityY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   A, (RTypeBank3_A7ControllerIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_CONTROLLER), A
                LD   A, (RTypeBank3_A7BodyKind)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_KIND), A
                LD   A, (RTypeBank3_A7BodyBit)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_BIT), A
                LD   HL, (RTypeBank3_A7RouteList)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ROUTE_LIST), HL
                LD   HL, (RTypeBank3_A7MotionPointer)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_POINTER), HL
                LD   HL, (RTypeBank3_A7MotionTimer)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_TIMER), HL
                LD   HL, (RTypeBank3_A7BodyDebrisRoot)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_ROOT), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER), HL
                LD   HL, #0028
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_HP), HL
                LD   HL, #5844
                CALL RTypeWorldRom_ReadByte
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_RELOAD), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_TIMER), A
                LD   A, #53
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE), A
                LD   A, #41
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #41
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_A7SpawnAttachment:
                LD   A, (RTypeBank3_A7AttachFireIndex)
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #8E10
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7FireA), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7FireB), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTypeBank3_A7FireScript), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTypeBank3_A7FireA)
                DEC  DE
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTypeBank3_A7FireCounter), HL
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_A71D_ATTACHMENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_A7BodyX)
                LD   DE, (RTypeBank3_A7AttachDX)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_A7BodyY)
                LD   DE, (RTypeBank3_A7AttachDY)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #58C2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, (RTypeBank3_A7FireCounter)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL
                LD   HL, (RTypeBank3_A7FireA)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), HL
                LD   HL, (RTypeBank3_A7FireB)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), HL
                LD   HL, (RTypeBank3_A7FireScript)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), HL
                LD   A, (RTypeBank3_A7LastBodyIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_SOURCE), A
                LD   HL, (RTypeBank3_A7AttachDX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_DX), HL
                LD   HL, (RTypeBank3_A7AttachDY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_DY), HL
                LD   A, #53
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ALT_PALETTE), A
                LD   A, #42
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #42
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #58C2
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateMultipartA71DBody:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_A7_BODY_DEBRIS
                JP   Z, RTypeBank3_A7UpdateBodyDebris
                CALL RTypeBank3_A7ControllerAlive
                JP   C, RTypeBank3_A7RemoveBody
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PHASE)
                OR   A
                JR   NZ, .path
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_KIND)
                OR   A
                CALL Z, RTypeBank3_A7FireUpper
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_KIND)
                CP   2
                CALL Z, RTypeBank3_A7FireLower
.path:         CALL RTypeBank3_A7AdvanceBodyPath
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FLASH_TIMER)
                OR   A
                JR   Z, .phase80
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FLASH_TIMER), A
                LD   A, (FrameCounter)
                AND  4
                JR   Z, .phase80
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.phase80:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PHASE)
                CP   #80
                RET  NZ
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE), A
                RET

RTypeBank3_A7ControllerAlive:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_CONTROLLER)
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_A71D_CONTROLLER
                RET  Z
                SCF
                RET

RTypeBank3_A7FireUpper:
                LD   HL, #0050
                LD   (RTypeBank3_A7ShotXOffset), HL
                LD   HL, #5850
                LD   (RTypeBank3_A7ShotOffsets), HL
                LD   A, #50
                LD   (RTypeBank3_A7ShotSpan), A
                JP   RTypeBank3_A7FireStraight

RTypeBank3_A7FireLower:
                LD   HL, #0010
                LD   (RTypeBank3_A7ShotXOffset), HL
                LD   HL, #5860
                LD   (RTypeBank3_A7ShotOffsets), HL
                LD   A, #30
                LD   (RTypeBank3_A7ShotSpan), A
                CALL RTypeBank3_A7FireStraight
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #00B8
                OR   A
                SBC  HL, DE
                JR   NC, .resetPair
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PAIR_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PAIR_TIMER), HL
                LD   A, H
                OR   A
                RET  NZ
                LD   A, L
                CP   #40
                RET  NC
                AND  #0F
                RET  NZ
                LD   HL, -8
                LD   (RTypeBank3_A7DebrisXOffset), HL
                XOR  A
                LD   (RTypeBank3_A7DebrisPhase), A
                CALL RTypeBank3_A7SpawnDebris
                LD   HL, -#0028
                LD   (RTypeBank3_A7DebrisXOffset), HL
                LD   A, 1
                LD   (RTypeBank3_A7DebrisPhase), A
                JP   RTypeBank3_A7SpawnDebris
.resetPair:    LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PAIR_TIMER), HL
                RET

RTypeBank3_A7FireStraight:
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTypePlayerNativeY)
                LD   DE, #0010
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                LD   A, H
                OR   A
                RET  NZ
                LD   A, L
                LD   B, A
                LD   A, (RTypeBank3_A7ShotSpan)
                CP   B
                RET  C
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_TIMER)
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_TIMER), A
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FIRE_TIMER), A
                CALL RTypeRng_Next
                LD   A, L
                AND  #0E
                LD   E, A
                LD   D, 0
                LD   HL, (RTypeBank3_A7ShotOffsets)
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_A7ShotY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeBank3_A7ShotXOffset)
                ADD  HL, DE
                LD   (RTypeBank3_A7ShotX), HL
                LD   HL, #5848
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_A7ShotVelocity), DE
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_A7BodyCurrentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_STRAIGHT_SHOT_E6AB
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #6000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_A7ShotX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_A7ShotY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank3_A7ShotVelocity)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, #84CE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #02
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #02
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #84CE
                CALL RTypeSprite_PrepareDescriptor
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (RTYPE_PROJECTILE_COUNT)
                INC  HL
                LD   (RTYPE_PROJECTILE_COUNT), HL
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_A7BodyCurrentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_A7AdvanceBodyPath:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_TIMER)
                LD   A, H
                OR   L
                JR   Z, .arrived
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_TIMER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                JP   RTypeProjectile_AddQ8Y
.arrived:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_CONTROLLER)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_A7_ARRIVED
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_BIT)
                OR   (HL)
                LD   (HL), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_CONTROLLER)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_A7_ADVANCE
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                OR   A
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_POINTER)
                LD   DE, 6
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_POINTER), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                CP   #80
                JR   NZ, .loadCurrent
                LD   A, E
                OR   A
                JR   NZ, .loadCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ROUTE_LIST)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ROUTE_LIST), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   NZ, .installStream
                LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                CALL RTypeBank3_A7MarkCompleted
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ROUTE_LIST)
                DEC  HL
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ROUTE_LIST), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PHASE)
                INC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PHASE), A
                RET
.installStream: EX   DE, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_POINTER), HL
.loadCurrent:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_POINTER)
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                EX   DE, HL
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                CALL RTypeObjects_ReadWordNext
                EX   DE, HL
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                CALL RTypeObjects_ReadWordNext
                EX   DE, HL
                SRL  H
                RR   L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_MOTION_TIMER), HL
                RET

RTypeBank3_A7MarkCompleted:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_CONTROLLER)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_A7_COMPLETED
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_BIT)
                OR   (HL)
                LD   (HL), A
                RET

RTypeBank3_DamageMultipartA71DBody:
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_A7_BODY_ACTIVE
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_PHASE)
                OR   A
                RET  NZ
                LD   E, B
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_HP)
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_HP), HL
                LD   A, #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_FLASH_TIMER), A
                LD   A, H
                OR   L
                JP   Z, RTypeBank3_A7BeginBodyDebris
                RET  NC
                JP   RTypeBank3_A7BeginBodyDebris

RTypeBank3_A7BeginBodyDebris:
                CALL RTypeBank3_A7MarkCompleted
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE), A
                LD   A, RTYPE_A7_BODY_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_ROOT)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER), HL
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_TIMER), HL
                RET

RTypeBank3_A7UpdateBodyDebris:
                LD   A, (FrameCounter)
                AND  1
                JR   NZ, .timer
                LD   A, (FrameCounter)
                AND  3
                CALL Z, RTypeRng_Next
                CALL RTypeRng_Next
                LD   A, L
                AND  6
                LD   A, 4                        ; ordinary `$8010/$E7B6`
                JR   NZ, .effectReady
                DEC  A                           ; ordinary `$8010/$E817`
.effectReady:  LD   (RTypeBank3_A7ExplosionEffect), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER)
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnX), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTypeBank3_8CSpawnY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                CP   #80
                JR   NZ, .spawn
                LD   A, E
                OR   A
                JR   NZ, .spawn
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_ROOT)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_POINTER), HL
.spawn:        LD   A, (RTypeBank3_A7ExplosionEffect)
                CALL RTypeBank3_8CSpawnExplosion
.timer:        LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_DEBRIS_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_A7RemoveBody:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_UpdateMultipartA71DAttachment:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_SOURCE)
                CALL RTypeObjects_RecordAddress
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                CP   RTYPE_OBJ_A71D_BODY
                JP   NZ, RTypeBank3_A7RemoveAttachment
                PUSH HL
                LD   DE, RTYPE_OBJ_STATE
                ADD  HL, DE
                LD   A, (HL)
                CP   RTYPE_A7_BODY_ACTIVE
                POP  HL
                JP   NZ, RTypeBank3_A7RemoveAttachment
                PUSH HL
                LD   DE, RTYPE_OBJ_X
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank3_A7SourceX), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank3_A7SourceY), DE
                POP  HL
                LD   DE, RTYPE_OBJ_FLAGS
                ADD  HL, DE
                LD   A, (HL)
                AND  2
                JR   Z, .fire
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.fire:         LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ORIENTATION)
                LD   A, H
                OR   L
                JR   Z, .follow
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
.follow:       LD   HL, (RTypeBank3_A7SourceX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_DX)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTypeBank3_A7SourceY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_DY)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                LD   E, A
                LD   D, 0
                LD   HL, #5870
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ORIENTATION), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank3_A7RemoveAttachment:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ALT_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7BE

RTypeBank3_A7SpawnDebris:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_A7BodyCurrentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeBank3_A7DebrisXOffset)
                ADD  HL, DE
                LD   (RTypeBank3_A7DebrisX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0038
                ADD  HL, DE
                LD   (RTypeBank3_A7DebrisY), HL
                CALL RTypeObjects_StoreScratch
                CALL RTypeRng_Next
                LD   A, H
                ADD  A, #80
                LD   L, A
                LD   H, 0
                JR   NC, .magnitudeReady
                INC  H
.magnitudeReady:
                LD   A, (RTYPE_RNG_A)             ; low результата уже в RNG state
                AND  #20
                JR   Z, .xReady
                EX   DE, HL
                LD   HL, 0
                OR   A
                SBC  HL, DE
.xReady:       LD   (RTypeBank3_A7DebrisVX), HL
                CALL RTypeRng_Next
                LD   L, H
                LD   H, 0
                LD   DE, #0280
                ADD  HL, DE
                LD   (RTypeBank3_A7DebrisVY), HL
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_A71D_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_A7DebrisX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_A7DebrisY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypeBank3_A7DebrisVX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank3_A7DebrisVY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, #0010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_DEBRIS_GRAVITY), HL
                LD   A, (RTypeBank3_A7DebrisPhase)
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_DEBRIS_PHASE_OFFSET), HL
                LD   DE, #58CE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #56
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #56
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_A7BodyCurrentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank3_UpdateMultipartA71DDebris:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_DEBRIS_PHASE_OFFSET)
                LD   DE, #58CE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_A7RemoveDebris
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_A7RemoveDebris
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_A7RemoveDebris
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                JR   NC, RTypeBank3_A7RemoveDebris
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #007C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank3_A7RemoveDebris
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0194
                OR   A
                SBC  HL, DE
                JR   NC, RTypeBank3_A7RemoveDebris
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_DEBRIS_GRAVITY)
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_A7_DEBRIS_PAIRED
                RET  NZ
                BIT  7, H
                RET  Z
                LD   HL, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   A, RTYPE_A7_DEBRIS_FALLING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank3_A7RemoveDebris:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; ----------------------------------------------------------------------------
; `$915B/$91CC`: allocator 22 связанных частей Stage 2.
; ----------------------------------------------------------------------------

RTypeBank3_InitMultipart915B:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_MULTIPART_915B_PARENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_HEAD), A

                ; `$4086[index]` состоит из motion root, X и Y; index — только
                ; command bits0..2. Умножение на 6 не смешивает mode bits4..5.
                LD   A, (RTypeWorldLastCommand)
                AND  7
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #4086
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_MOTION_ROOT), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE

                ; Target build пока использует difficulty=0: mode равен
                ; `(command & $30) >> 3`, то есть byte offsets 0,2,4,6.
                LD   A, (RTypeWorldLastCommand)
                AND  #30
                SRL  A
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #40B6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   A, (RTypeWorldLastCommand)
                BIT  2, A
                JR   Z, .baseReady
                LD   DE, #00C0                   ; command bit2 overrides DSW
.baseReady:    LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_BASE_TIMER), DE
                LD   HL, #40C6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_SEQUENCE), HL
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   HL, #201F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PRIORITY_VALUE), HL
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_ORDINAL), HL
                JP   RTypeObjects_CommitCurrent

RTypeBank3_UpdateMultipart915BParent:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ

                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_SEQUENCE)
                LD   (RTypeBank3_91SequenceRecord), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_91Initializer), DE
                LD   HL, (RTypeBank3_91SequenceRecord)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeBank3_91Delay), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PRIORITY_VALUE)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PRIORITY_VALUE), HL
                LD   (RTypeBank3_91ChildPriority), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_ORDINAL)
                LD   (RTypeBank3_91ChildCleanup), HL
                LD   DE, 2
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_ORDINAL), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_HEAD)
                LD   (RTypeBank3_91PreviousIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_MOTION_ROOT)
                LD   (RTypeBank3_91MotionRoot), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_BASE_TIMER)
                LD   (RTypeBank3_91BaseTimer), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_91SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_91SourceY), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_91ParentIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank3_InitMultipart915BChild
                JR   C, .restore
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_91SpawnedIndex), A
.restore:      LD   A, (RTypeBank3_91ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, (RTypeBank3_91SpawnedIndex)
                CP   #FF
                JR   Z, .timer
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_HEAD), A
.timer:        LD   HL, (RTypeBank3_91Delay)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .advance
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_SEQUENCE)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_SEQUENCE), HL
                RET

RTypeBank3_InitMultipart915BChild:
                LD   A, #FF
                LD   (RTypeBank3_91SpawnedIndex), A
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_MULTIPART_915B_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_91SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_91SourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTypeBank3_91PreviousIndex)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PREVIOUS), A
                LD   HL, (RTypeBank3_91ChildPriority)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CHILD_PRIORITY), HL
                LD   HL, (RTypeBank3_91ChildCleanup)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_COUNTER), HL
                LD   HL, (RTypeBank3_91MotionRoot)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE + 1), A
                LD   HL, (RTypeBank3_91BaseTimer)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_RELOAD), HL
                LD   DE, #0028
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_TIMER), HL
                LD   HL, #7FFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_HP), HL

                ; Пять initializer addresses выбирают state/resource/base.
                LD   HL, (RTypeBank3_91Initializer)
                LD   DE, #9246
                OR   A
                SBC  HL, DE
                JR   Z, .first
                LD   HL, (RTypeBank3_91Initializer)
                LD   DE, #92C3
                OR   A
                SBC  HL, DE
                JR   Z, .second
                LD   HL, (RTypeBank3_91Initializer)
                LD   DE, #933C
                OR   A
                SBC  HL, DE
                JR   Z, .main
                LD   HL, (RTypeBank3_91Initializer)
                LD   DE, #9477
                OR   A
                SBC  HL, DE
                JR   Z, .late
                ; Последняя допустимая запись `$94E1` — terminal.
                LD   A, RTYPE_91_TERMINAL
                LD   HL, #41FE
                LD   B, #40
                JR   .configured
.first:        LD   A, RTYPE_91_FIRST
                LD   HL, #419E
                LD   B, #40
                JR   .configured
.second:       LD   A, RTYPE_91_SECOND
                LD   HL, #41FE
                LD   B, #40
                JR   .configured
.main:         LD   A, RTYPE_91_MAIN
                LD   HL, #425E
                LD   B, #3F
                JR   .configured
.late:         LD   A, RTYPE_91_LATE
                LD   HL, #419E
                LD   B, #40
.configured:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, B
                LD   (RTypeBank3_91ResourceType), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_FLASH_PALETTE), A
                LD   A, (RTypeBank3_91ResourceType)
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, (RTypeBank3_91ResourceType)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
                OR   A
                RET

; `$9246…$957C`: общий motion сначала, затем state-specific pulse/descriptor.
RTypeBank3_UpdateMultipart915BChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   HL, (RTypeWorldStageControllerHandler)
                LD   DE, #A3B3
                OR   A
                SBC  HL, DE
                JR   NZ, .motion
                LD   A, (FrameCounter)
                RRCA
                JR   NC, .motion
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.motion:       CALL RTypeObjects_ScriptedMotion
                JP   C, RTypeBank3_91RemoveChild
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_91_FIRST
                JP   Z, RTypeBank3_91First
                CP   RTYPE_91_SECOND
                JP   Z, RTypeBank3_91Second
                CP   RTYPE_91_MAIN
                JP   Z, RTypeBank3_91Main
                CP   RTYPE_91_HIT
                JP   Z, RTypeBank3_91Hit
                CP   RTYPE_91_LATE
                JP   Z, RTypeBank3_91Late
                JP   RTypeBank3_91Terminal

RTypeBank3_91First:
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .descriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE_TIMER), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  3
                INC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), A
.descriptor:   LD   HL, #419E
                CALL RTypeBank3_91SetMotionDescriptor
                JP   RTypeBank3_91FinishChild

RTypeBank3_91Second:
                CALL RTypeBank3_91ReadPrevious
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE + 1), A
                LD   A, (RTypeBank3_91PreviousState)
                CP   RTYPE_91_FIRST
                JR   NZ, .descriptor
                LD   HL, (RTypeBank3_91PreviousPulse)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), HL
.descriptor:   LD   HL, #41FE
                CALL RTypeBank3_91SetMotionDescriptor
                JP   RTypeBank3_91FinishChild

RTypeBank3_91Main:
                CALL RTypeBank3_91ReadPrevious
                LD   HL, (RTypeBank3_91PreviousPulse)
                DEC  HL
                LD   (RTypeBank3_91PulseValue), HL
                LD   A, H
                OR   L
                JR   NZ, .storePulse
                LD   A, (RTypeBank3_91PreviousState)
                CP   RTYPE_91_SECOND
                JR   C, .storePulse
                CP   RTYPE_91_HIT + 1
                JR   NC, .storePulse
                CALL RTypeBank3_91PlayerDistance
                LD   DE, #0090
                OR   A
                SBC  HL, DE
                JR   C, .storePulse
                CALL RTypeBank3_91SpawnRadials
.storePulse:   LD   HL, (RTypeBank3_91PulseValue)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), HL
                LD   A, (FrameCounter)
                AND  #18
                SRL  A
                SRL  A
                SRL  A
                LD   HL, #425E
                CALL RTypeBank3_91SetDescriptorPhaseA
                JP   RTypeBank3_91FinishChild

RTypeBank3_91Hit:
                CALL RTypeBank3_91ReadPrevious
                LD   HL, (RTypeBank3_91PreviousPulse)
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .pulseReady
                LD   HL, 1
.pulseReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PULSE), HL
                LD   HL, #4276
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeBank3_91FinishChild

RTypeBank3_91Late:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                ADD  A, 8
                AND  #0F
                LD   HL, #419E
                CALL RTypeBank3_91SetDescriptorPhaseA
                JP   RTypeBank3_91FinishChild

RTypeBank3_91Terminal:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                ADD  A, 8
                AND  #0F
                LD   HL, #41FE
                CALL RTypeBank3_91SetDescriptorPhaseA

RTypeBank3_91FinishChild:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTypeWorldStageControllerHandler)
                LD   DE, #A523
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_COUNTER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_CLEANUP_COUNTER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7B6

RTypeBank3_91RemoveChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank3_91SetMotionDescriptor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)

; HL=base, A=phase: descriptor=base+phase*6 с полным 16-bit offset.
RTypeBank3_91SetDescriptorPhaseA:
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                      ; phase*6, максимум 31*6
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

; Снять state/pulse предыдущей физической записи, не меняя resident scratch.
RTypeBank3_91ReadPrevious:
                LD   A, #FF
                LD   (RTypeBank3_91PreviousState), A
                LD   HL, 0
                LD   (RTypeBank3_91PreviousPulse), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_PREVIOUS)
                CP   #FF
                RET  Z
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_STATE
                ADD  HL, DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (HL)
                LD   (RTypeBank3_91PreviousState), A
                LD   DE, RTYPE_OBJ_91_PULSE - RTYPE_OBJ_STATE
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBank3_91PreviousPulse), DE
                RET

; Manhattan distance от части до R-9; координаты в игровом диапазоне, но
; absolute difference всё равно считается signed-safe через NEG word.
RTypeBank3_91PlayerDistance:
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                BIT  7, H
                JR   Z, .xReady
                XOR  A
                SUB  L
                LD   L, A
                SBC  A, A
                SUB  H
                LD   H, A
.xReady:       LD   (RTypeBank3_91DistanceX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                BIT  7, H
                JR   Z, .yReady
                XOR  A
                SUB  L
                LD   L, A
                SBC  A, A
                SUB  H
                LD   H, A
.yReady:       LD   DE, (RTypeBank3_91DistanceX)
                ADD  HL, DE
                RET

; Восемь difficulty-zero records `$411E + index*6`. Allocator и radial имеют
; одинаковый `$8010`, поэтому radial-band уже пройден и первый Q8 шаг ждёт.
RTypeBank3_91SpawnRadials:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_91SourceIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_91SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_91SourceY), HL
                LD   A, (RTypeBank3_91SourceIndex)
                CALL RTypeObjects_StoreScratch
                XOR  A
                LD   (RTypeBank3_91RadialIndex), A
.next:         CALL RTypeObjects_New
                JR   C, .advance
                LD   A, RTYPE_OBJ_RADIAL_95F1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_91SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_91SourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTypeBank3_91RadialIndex)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #411E + 2
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   HL, #417E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #3F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #3F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #417E
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.advance:      LD   A, (RTypeBank3_91RadialIndex)
                INC  A
                LD   (RTypeBank3_91RadialIndex), A
                CP   8
                JR   C, .next
                LD   A, (RTypeBank3_91SourceIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; `$95F1`: signed Q8, four-frame animation и collision/bounds только на
; нечётных VBlank. Terrain-hit становится in-place `$E7AE`.
RTypeBank3_UpdateRadial95F1:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   A, (FrameCounter)
                AND  6
                LD   B, A
                ADD  A, A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, #417E
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (FrameCounter)
                RRCA
                RET  NC
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .terrainHit
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .terrainHit
                CALL RTypeWalker_InsideBounds
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.terrainHit:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   RTypeBank3_ConvertCurrentToE7AE

; Main-part player contact: создать отдельный `$E7BE` в anchor и перейти hit.
RTypeBank3_ContactMultipart915BChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_91_MAIN
                RET  NZ
                LD   A, RTYPE_91_HIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank3_91SourceIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank3_91SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank3_91SourceY), HL
                LD   A, (RTypeBank3_91SourceIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank3_91SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank3_91SourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                CALL RTypeBank3_ConvertCurrentToE7BE
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank3_91SourceIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; In-place `$E817`: resource `$01`, paired descriptor stream `$85FA`, timer 1.
; Координаты, priority, serial и Q8 residue текущей 64-байтной записи намеренно
; сохраняются — именно так исходный death handler заменяет функцию объекта.
RTypeBank3_ConvertCurrentToE817:
                LD   HL, #85FA
                LD   A, 1
                JR   RTypeBank3_ConvertCurrentExplosion

RTypeBank3_ConvertCurrentToE7AE:
                LD   HL, #8552
                LD   A, 2
                JR   RTypeBank3_ConvertCurrentExplosion

RTypeBank3_ConvertCurrentToE7B6:
                LD   HL, #8506
                LD   A, 2
                JR   RTypeBank3_ConvertCurrentExplosion

RTypeBank3_ConvertCurrentToE7BE:
                LD   HL, #8530
                LD   A, 2

; HL=ROM sequence, A=начальный timer. Исходный resource вызывающий уже снял.
RTypeBank3_ConvertCurrentExplosion:
                LD   (RTypeBank3_ExplosionSequence), HL
                LD   (RTypeBank3_ExplosionTimer), A
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
                LD   HL, (RTypeBank3_ExplosionSequence)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER), HL
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (RTypeBank3_ExplosionTimer)
                LD   L, A
                LD   H, 0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_TIMER), HL
                RET

RTypeBank3_87ParentIndex:   DEFB 0
RTypeBank3_87Direction:     DEFB 0
RTypeBank3_87SpawnDelay:    DEFW 0
RTypeBank3_87ParentX:       DEFW 0
RTypeBank3_87ParentY:       DEFW 0
RTypeBank3_87ParentTargetY: DEFW 0
RTypeBank3_87ChildYVelocity: DEFW 0
RTypeBank3_7DParentIndex:   DEFB 0
RTypeBank3_7DParentX:       DEFW 0
RTypeBank3_7DParentY:       DEFW 0
RTypeBank3_8DScript:        DEFW 0
RTypeBank3_8DXVelocity:     DEFW 0
RTypeBank3_8DYVelocity:     DEFW 0
RTypeBank3_8DTargetIndex:   DEFB 0
RTypeBank3_8DTargetPointer: DEFW 0
RTypeBank3_8DTargetX:       DEFW 0
RTypeBank3_8DTargetY:       DEFW 0
RTypeBank3_69MotionOffset:  DEFB 0
RTypeBank3_69Direction:     DEFB 0
RTypeBank3_69ProbeX:        DEFW 0
RTypeBank3_69ProbeY:        DEFW 0
RTypeBank3_8FPositionIndex: DEFB 0
RTypeBank3_8FTerrainCell:   DEFW 0
RTypeBank3_85ParentIndex:   DEFB 0
RTypeBank3_85ShotX:         DEFW 0
RTypeBank3_85ShotY:         DEFW 0
RTypeBank3_85ShotVelocity:  DEFW 0
RTypeBank3_5EProbeX:        DEFW 0
RTypeBank3_5EProbeY:        DEFW 0
RTypeBank3_5ERepeatX:       DEFW 0
RTypeBank3_5ERepeatY:       DEFW 0
RTypeBank3_5EProbeCode:     DEFW 0
RTypeBank3_5EIterations:    DEFB 0
; Временные байты `$7182`: индекс стартовой записи и вычисленный сектор R-9.
; Они находятся в object bank, потому что нужны только во время init/update этого
; обработчика и не расходуют дефицитную общую область состояния объектов.
RTypeBank3_71PositionIndex: DEFB 0
RTypeBank3_71TargetDirection: DEFB 0
RTypeBank3_72ProbeX:        DEFW 0
RTypeBank3_72ProbeY:        DEFW 0
RTypeBank3_8CParentIndex:    DEFB 0
RTypeBank3_8CEffect:         DEFB 0
RTypeBank3_8CSpawnX:         DEFW 0
RTypeBank3_8CSpawnY:         DEFW 0
RTypeBank3_8CTerrainAddress: DEFW 0
RTypeBank3_8CTerrainPointer: DEFW 0
RTypeBank3_8CTerrainCode:    DEFW 0
RTypeBank3_6EDebrisPointer:  DEFW 0
RTypeBank3_78ParentIndex:    DEFB 0
RTypeBank3_78SpawnedIndex:   DEFB 0
RTypeBank3_78PreviousIndex:  DEFB 0
RTypeBank3_78PreviousFlag:   DEFB 0
RTypeBank3_78FollowState:    DEFB 0
RTypeBank3_78ResourceType:   DEFB 0
RTypeBank3_78ParentPriority: DEFW 0
RTypeBank3_78SequenceRecord: DEFW 0
RTypeBank3_78Initializer:    DEFW 0
RTypeBank3_78Delay:          DEFW 0
RTypeBank3_78ChildPriority:  DEFW 0
RTypeBank3_78MotionRoot:     DEFW 0
RTypeBank3_78SourceX:        DEFW 0
RTypeBank3_78SourceY:        DEFW 0
RTypeBank3_78EscapeBase:     DEFW 0
RTypeBank3_78PreviousDelay:  DEFW 0
RTypeBank3_96ParentIndex:    DEFB 0
RTypeBank3_96Direction:      DEFB 0
RTypeBank3_96SpawnX:         DEFW 0
RTypeBank3_96SpawnY:         DEFW 0
RTypeBank3_96VelocityTable:  DEFW 0
RTypeBank3_96VelocityX:      DEFW 0
RTypeBank3_96VelocityY:      DEFW 0
RTypeBank3_96Descriptor:     DEFW 0
RTypeBank3_A7ControllerIndex: DEFB 0
RTypeBank3_A7LastBodyIndex:   DEFB 0
RTypeBank3_A7BodyCurrentIndex: DEFB 0
RTypeBank3_A7BodyKind:       DEFB 0
RTypeBank3_A7BodyBit:        DEFB 0
RTypeBank3_A7AttachFireIndex: DEFB 0
RTypeBank3_A7ShotSpan:       DEFB 0
RTypeBank3_A7DebrisPhase:    DEFB 0
RTypeBank3_A7ExplosionEffect: DEFB 0
RTypeBank3_A7Selector:       DEFW 0
RTypeBank3_A7BodyRender:     DEFW 0
RTypeBank3_A7BodyDebrisRoot: DEFW 0
RTypeBank3_A7RouteRecord:    DEFW 0
RTypeBank3_A7RouteList:      DEFW 0
RTypeBank3_A7MotionPointer:  DEFW 0
RTypeBank3_A7MotionTimer:    DEFW 0
RTypeBank3_A7VelocityX:      DEFW 0
RTypeBank3_A7VelocityY:      DEFW 0
RTypeBank3_A7BodyX:          DEFW 0
RTypeBank3_A7BodyY:          DEFW 0
RTypeBank3_A7AttachDX:       DEFW 0
RTypeBank3_A7AttachDY:       DEFW 0
RTypeBank3_A7FireA:          DEFW 0
RTypeBank3_A7FireB:          DEFW 0
RTypeBank3_A7FireScript:     DEFW 0
RTypeBank3_A7FireCounter:    DEFW 0
RTypeBank3_A7ShotXOffset:    DEFW 0
RTypeBank3_A7ShotOffsets:    DEFW 0
RTypeBank3_A7ShotX:          DEFW 0
RTypeBank3_A7ShotY:          DEFW 0
RTypeBank3_A7ShotVelocity:   DEFW 0
RTypeBank3_A7SourceX:        DEFW 0
RTypeBank3_A7SourceY:        DEFW 0
RTypeBank3_A7DebrisXOffset:  DEFW 0
RTypeBank3_A7DebrisX:        DEFW 0
RTypeBank3_A7DebrisY:        DEFW 0
RTypeBank3_A7DebrisVX:       DEFW 0
RTypeBank3_A7DebrisVY:       DEFW 0
RTypeBank3_91ParentIndex:    DEFB 0
RTypeBank3_91SourceIndex:    DEFB 0
RTypeBank3_91SpawnedIndex:   DEFB 0
RTypeBank3_91PreviousIndex:  DEFB 0
RTypeBank3_91PreviousState:  DEFB 0
RTypeBank3_91RadialIndex:    DEFB 0
RTypeBank3_91ResourceType:   DEFB 0
RTypeBank3_91Initializer:    DEFW 0
RTypeBank3_91SequenceRecord: DEFW 0
RTypeBank3_91Delay:          DEFW 0
RTypeBank3_91ChildPriority:  DEFW 0
RTypeBank3_91ChildCleanup:   DEFW 0
RTypeBank3_91MotionRoot:     DEFW 0
RTypeBank3_91BaseTimer:      DEFW 0
RTypeBank3_91SourceX:        DEFW 0
RTypeBank3_91SourceY:        DEFW 0
RTypeBank3_91PreviousPulse:  DEFW 0
RTypeBank3_91PulseValue:     DEFW 0
RTypeBank3_91DistanceX:      DEFW 0
RTypeBank3_ExplosionSequence: DEFW 0
RTypeBank3_ExplosionTimer:    DEFB 0
