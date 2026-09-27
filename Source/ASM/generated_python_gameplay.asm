; Сгенерировано rtype_python_translator.py из Game.update/render,
; PlayerLifecycle и BackgroundParticleE5CD.update активного Python-графа.
; Ручное редактирование запрещено: следующая сборка перезапишет файл.

RTYPE_PY_TERRAIN_FG_CLEAR EQU #0DFC
RTYPE_PY_TERRAIN_BG_CLEAR EQU #07D0
RTYPE_PY_HUD_MAX_LIVES    EQU 8
RTYPE_PY_FRAME_COUNTER_SEED EQU #0292
RTYPE_PY_FRAME_COUNTER_STEP EQU 1
RTYPE_PY_FRAME_COUNTER_MASK EQU #FFFF
RTYPE_PY_SOURCE_FRAME_RATE_X1000 EQU 55000
RTYPE_PY_INTRO_FRAMES      EQU 226
RTYPE_PY_CHARGE_VISIBLE    EQU #0F
RTYPE_PY_MOVE_X_Q8         EQU 853
RTYPE_PY_MOVE_Y_Q8         EQU 960
RTYPE_PY_SHOT_VX_Q8        EQU 6827

; Дополнительное translated-состояние lifecycle. Блок #44C0…#44CF не
; пересекает ArcadeStageFrame (#4290), title overlay и fixed-player state.
RTypePyDeathPalette       EQU #44C0
RTypePyDeathNativeX       EQU #44C1
RTypePyDeathNativeY       EQU #44C3
RTypePyFastParticleIndex  EQU #44C5
RTypePyParticleCellCode   EQU #44C6
RTypePyParticleX          EQU #44C8
RTypePyParticleY          EQU #44CA
RTypePyParticlePalette    EQU #44CC
RTypePyParticleVertexX    EQU #44CD
RTypePyParticleWasReady   EQU #44CF

RTYPE_PY_PARTICLE_DESCRIPTOR_BASE EQU #846C
RTYPE_PY_PARTICLE_DESCRIPTOR_COUNT EQU 6
RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE EQU 6
RTYPE_PY_PARTICLE_CELL_BASE EQU #0AF2
RTYPE_PY_PARTICLE_X_BIAS EQU -334
RTYPE_PY_PARTICLE_Y_ORIGIN EQU 372

; Буквальный перенос Game._begin_player_death. Checkpoint выбирается из
; активного stage-пакета до очистки объектов и ресурсов.
RTypePyLifecycle_BeginDeathBackend:
                CALL RTypePyLifecycle_SaveCheckpoint
                LD   HL, (RTypePlayerNativeX)
                LD   (RTypePyDeathNativeX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTypePyDeathNativeY), HL
                ; Постоянно отображённый helper безопасно переключает slot2,
                ; тогда как сам сгенерированный backend находится в Core slot2.
                CALL RTypePyLifecycle_ClearFixedPlayer
                ; Enemy fixed bytes, input edges, shots, pending matrix fire,
                ; Wave object and charge are all cleared in the same branch.
                XOR  A
                LD   HL, ArcadeReleasePrev
                LD   DE, ArcadeReleasePrev + 1
                LD   BC, 5
                LD   (HL), A
                LDIR
                LD   HL, ArcadeShotTable
                LD   DE, ArcadeShotTable + 1
                LD   BC, ArcadeShotPending - ArcadeShotTable
                LD   (HL), A
                LDIR
                LD   A, #09
                CALL RTypeResources_Acquire
                LD   (RTypePyDeathPalette), A
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                ; play_sfx($00), затем play_sfx($35): target-latch передаёт
                ; аппаратному звуковому мосту ту же последнюю команду.
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, #35
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                RET

RTypePyLifecycle_ClearBackend:
                LD   A, (RTypePyDeathPalette)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTypePyDeathPalette), A
                RET

; Буквальный _restore_checkpoint: сбросить ring выбранного stage, создать
; новый мир объектов/ресурсов, вернуть постоянное transition-состояние и
; поставить event-reader на первую запись с progression checkpoint.
RTypePyLifecycle_RespawnBackend:
                CALL RTypePyLifecycle_RebuildCheckpoint
                XOR  A
                LD   (ArcadePlayerX), A
                LD   (ArcadePlayerY), A
                LD   HL, 160
                LD   (ArcadePlayerX + 1), HL
                LD   HL, 221
                LD   (ArcadePlayerY + 1), HL
                LD   A, ARCADE_PITCH_NEUTRAL
                LD   (ArcadePlayerPitch), A
                CALL ArcadePlayer_SyncNative
                XOR  A
                LD   (RTypePyDeathNativeX), A
                LD   (RTypePyDeathNativeX + 1), A
                LD   (RTypePyDeathNativeY), A
                LD   (RTypePyDeathNativeY + 1), A
                LD   A, #FF
                LD   (RTypePyDeathPalette), A
                RET

; Неактивные Python-кадры обновляют остановленный мир, затем lifecycle;
; ввод и оружие игрока не исполняются. GAME OVER терминален.
RTypePyLifecycle_DeathFrame:
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_GAME_OVER
                RET  Z
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                CALL RTypeWorld_Update
                XOR  A
                LD   (RTypeWorldFgVelocity), A
                LD   (RTypeWorldFgVelocity + 1), A
                LD   (RTypeWorldBgVelocity), A
                LD   (RTypeWorldBgVelocity + 1), A
                CALL ArcadeLifecycle_Update
                ; PlayerLifecycle.advance выдаёт checkpoint_rebuild только на
                ; кадре уменьшения жизней и только если осталась ещё жизнь.
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_DEATH
                RET  NZ
                LD   HL, (ArcadeDeathAge)
                LD   DE, ARCADE_LIFE_DECREMENT_AGE
                OR   A
                SBC  HL, DE
                RET  NZ
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, 1
                LD   (RTYPE_CLEANUP_ACTIVE), A
                RET

RTypePyLifecycle_PrepareExplosion:
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                LD   A, (RTypePyDeathPalette)
                CP   #FF
                RET  Z
                LD   HL, (ArcadeDeathDescriptor)
                LD   A, H
                OR   L
                RET  Z
                JP   RTypeSprite_PrepareDescriptor

; Game.render chooses explosion while dying and the five-frame pitch body only
; while active.  This prevents a silent R-9 disappearance at the death edge.
RTypePyRenderPlayerLifecycle:
                LD   A, (ArcadeLifeState)
                CP   ARCADE_LIFE_DEATH
                JP   NZ, Render_M72DynamicPlayer
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                LD   A, (RTypePyDeathPalette)
                CP   #FF
                RET  Z
                LD   HL, (ArcadeDeathDescriptor)
                LD   BC, (RTypePyDeathNativeX)
                LD   DE, (RTypePyDeathNativeY)
                JP   RTypeSprite_DrawDescriptor

; HUD_FIXED contains two captured icons.  Clear only their black HUD area on
; screen, then reuse the first icon directly from RAM_G and draw ArcadeLives
; copies.  No runtime scaling/filtering and no modification of Python assets.
RTypePyRenderLives:
                FT_ColorRGB 0, 0, 0
                FT_Begin FT_RECTS
                LD   BC, 16 * 8
                LD   DE, 720 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   BC, 212 * 8
                LD   DE, 750 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                LD   A, (ArcadeLives)
                OR   A
                RET  Z
                CP   RTYPE_PY_HUD_MAX_LIVES + 1
                JR   C, .countReady
                LD   A, RTYPE_PY_HUD_MAX_LIVES
.countReady:    LD   (.remaining), A
                LD   HL, 12
                LD   (.logicalX), HL
                FT_BitmapTransformA 160
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160
                FT_BitmapTransformF 0
                FT_BitmapSource ARCADE_BG_RAMG + 12 * 2
                FT_BitmapLayout FT_RGB565, ARCADE_BG_STRIDE, 18
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 24, 29
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
.nextLife:     LD   HL, (.logicalX)
                CALL M72_LogicalToVertex
                LD   DE, 720 * 8
                CALL FT.Coprocessor.Vertex2f
                LD   HL, (.logicalX)
                LD   DE, 15
                ADD  HL, DE
                LD   (.logicalX), HL
                LD   HL, .remaining
                DEC  (HL)
                JR   NZ, .nextLife
                FT_End
                RET
.remaining:    DEFB 0
.logicalX:     DEFW 0

; Активной BackgroundParticleE5CD нужны только перенесённый шаг Q8 и проверка
; границы. Прямой путь в page #09 убирает два 64-байтных LDIR на каждую звезду.
; Carry=0 передаёт одноразовый Python-initializer общему пути.
RTypePyBackgroundParticleFastUpdate:
                LD   (RTypePyFastParticleIndex), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_RecordAddress
                PUSH HL
                POP  IX
                ; Python scheduler проверяет cleanup до вызова update любого
                ; Enemy. Быстрый путь обязан удалить частицу в том же кадре.
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .cleanupPassed
                LD   A, (IX + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_Release
                SCF
                RET
.cleanupPassed:
                LD   A, (IX + RTYPE_OBJ_STATE)
                OR   A
                RET  Z
                LD   A, (IX + RTYPE_OBJ_SUBSTATE)
                LD   (RTypePyParticleWasReady), A
                LD   L, (IX + RTYPE_OBJ_X_FRACTION)
                LD   H, (IX + RTYPE_OBJ_X)
                LD   E, (IX + RTYPE_OBJ_X_VELOCITY)
                LD   D, (IX + RTYPE_OBJ_X_VELOCITY + 1)
                ADD  HL, DE
                LD   (IX + RTYPE_OBJ_X_FRACTION), L
                LD   (IX + RTYPE_OBJ_X), H
                LD   C, 0
                BIT  7, D
                JR   Z, .velocitySignReady
                DEC  C
.velocitySignReady:
                LD   A, (IX + RTYPE_OBJ_X + 1)
                ADC  A, C
                LD   (IX + RTYPE_OBJ_X + 1), A
                LD   (IX + RTYPE_OBJ_SUBSTATE), 1
                LD   L, (IX + RTYPE_OBJ_SCRIPT)
                LD   H, (IX + RTYPE_OBJ_SCRIPT + 1)
                LD   DE, #832C
                OR   A
                SBC  HL, DE
                JR   NZ, .leftMoving
                LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   DE, #02C0
                OR   A
                SBC  HL, DE
                JR   C, .prepare
                JR   .remove
.leftMoving:   LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                JR   NC, .prepare
.remove:       LD   A, (IX + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTypePyFastParticleIndex)
                CALL RTypeObjects_Release
                SCF
                RET
.prepare:      LD   A, (RTypePyParticleWasReady)
                OR   A
                JR   NZ, .prepared
                LD   L, (IX + RTYPE_OBJ_DESCRIPTOR)
                LD   H, (IX + RTYPE_OBJ_DESCRIPTOR + 1)
                CALL RTypeSprite_PrepareDescriptor
.prepared:
                SCF
                RET

; Python-initializer ставит initialized=True и возвращает render_ready=False.
; Подготовка descriptor здесь опережала семантику на кадр и давала пик кэша
; на 80 объектов. Следующий перенесённый шаг готовит его ровно один раз.
RTypePyBackgroundParticleAfterInit:
                RET

; Звёзды/background particles выводятся раньше остальных объектов. Python-выбор
; 32 вариантов ES:$83AC проверен как шесть соседних неотражённых 1x1 descriptor
; с общим смещением. Поэтому FT812-state общий для всей пачки; меняются только
; palette, источник кэшированной cell и vertex каждой частицы.
RTypePyDrawBackgroundParticles:
                FT_ColorRGB 255, 255, 255
                FT_BitmapTransformA 96
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_PALETTED4444, 16, 16
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 43, 49
                FT_Begin FT_BITMAPS
                LD   A, 2
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, RTYPE_OBJECT_BASE + 2 * RTYPE_OBJECT_REC_SIZE
                LD   (.recordPtr), HL
.nextParticle: LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (.recordPtr)
                LD   A, (HL)
                CP   RTYPE_OBJ_BG_PARTICLE
                JP   NZ, .advance
                PUSH HL
                POP  IX
                LD   A, (IX + RTYPE_OBJ_SUBSTATE)
                OR   A
                JP   Z, .advance
                LD   L, (IX + RTYPE_OBJ_DESCRIPTOR)
                LD   H, (IX + RTYPE_OBJ_DESCRIPTOR + 1)
                LD   DE, RTYPE_PY_PARTICLE_DESCRIPTOR_BASE
                OR   A
                SBC  HL, DE
                JP   C, .advance
                LD   A, H
                OR   A
                JP   NZ, .advance
                LD   A, L
                LD   B, 0
.descriptorIndex:
                OR   A
                JR   Z, .descriptorReady
                CP   RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE
                JP   C, .advance
                SUB  RTYPE_PY_PARTICLE_DESCRIPTOR_STRIDE
                INC  B
                JR   .descriptorIndex
.descriptorReady:
                LD   A, B
                CP   RTYPE_PY_PARTICLE_DESCRIPTOR_COUNT
                JP   NC, .advance
                LD   L, A
                LD   H, 0
                LD   DE, RTYPE_PY_PARTICLE_CELL_BASE
                ADD  HL, DE
                LD   (RTypePyParticleCellCode), HL
                LD   L, (IX + RTYPE_OBJ_X)
                LD   H, (IX + RTYPE_OBJ_X + 1)
                LD   (RTypePyParticleX), HL
                LD   L, (IX + RTYPE_OBJ_Y)
                LD   H, (IX + RTYPE_OBJ_Y + 1)
                LD   (RTypePyParticleY), HL
                LD   A, (IX + RTYPE_OBJ_PALETTE)
                LD   (RTypePyParticlePalette), A

                ; PALETTE_SOURCE = translated live resource slot * 32.
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_WORLD_SPRITE_PALETTE_RAMG & #FFFF
                ADD  HL, DE
                LD   E, L
                LD   D, H
                LD   C, (RTYPE_WORLD_SPRITE_PALETTE_RAMG >> 16) & #FF
                LD   B, #2A
                CALL FT.Coprocessor.Command_BCDE

                ; BITMAP_SOURCE = persistent cache slot * 256.
                LD   HL, (RTypePyParticleCellCode)
                CALL RTypeSpriteCache_LoadCell
                JP   C, .advance
                LD   A, H
                ADD  A, (RTYPE_PY_SPRITE_CACHE_RAMG >> 16) & #FF
                LD   D, L
                LD   E, 0
                LD   C, A
                LD   B, #01
                CALL FT.Coprocessor.Command_BCDE

                ; Same descriptor geometry as read_descriptor()/atlas.draw.
                LD   HL, (RTypePyParticleX)
                LD   DE, RTYPE_PY_PARTICLE_X_BIAS
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (RTypePyParticleVertexX), BC
                LD   HL, RTYPE_PY_PARTICLE_Y_ORIGIN
                LD   DE, (RTypePyParticleY)
                OR   A
                SBC  HL, DE
                CALL RTypeSprite_NativeYToVertex
                PUSH BC
                LD   BC, (RTypePyParticleVertexX)
                POP  DE
                CALL FT.Coprocessor.Vertex2f
.advance:      LD   A, (RTypeObjects_ScanIndex)
                INC  A
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, (.recordPtr)
                LD   DE, RTYPE_OBJECT_REC_SIZE
                ADD  HL, DE
                LD   (.recordPtr), HL
                CP   RTYPE_OBJECT_COUNT
                JP   C, .nextParticle
                FT_End
                RET
.recordPtr:    DEFW 0
; Descriptor count for each compact target object type, extracted
; from every unconditional adjacent draw in M72EnemyWorld.draw.
RTypePyObjectDrawCount:
                DEFB 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 2, 1, 1
                DEFB 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
                DEFB 1, 1, 1, 2, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 2
                DEFB 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
                DEFB 1, 2, 1, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1

; Game.__init__ literal seed. It drives every translated phase selector,
; including the eight-frame charge animation.
RTypePyGameplay_InitFrameCounter:
                CALL RTypePyInstallBank4Bridges
                ; M72ObjectPool хранит Q8 residue отдельно от owner-а. После
                ; очистки физической записи восстановить оба сохранённых byte.
                LD   HL, RTypePyObjects_ClearScratchWithResidue
                LD   (RTypeObjects_New + 9), HL
                ; Четырёхбайтный LD DE,(progression) заменяется на вызов
                ; свойства M72Scroll.dispatch_progression, сгенерированного
                ; из активного stage.py. Последний byte становится NOP.
                LD   A, #CD
                LD   (RTypeWorld_Update.eventReady - 12), A
                LD   HL, RTypePyGameplay_GetDispatchProgression
                LD   (RTypeWorld_Update.eventReady - 11), HL
                XOR  A
                LD   (RTypeWorld_Update.eventReady - 9), A
                ; В Python $F0F3 остаётся delegated event без изменения
                ; progression. Невозможное значение отключает старую ветку.
                LD   HL, #FFFF
                LD   (RTypeWorld_DispatchGlobal + 4), HL
                ; M72EnemyWorld.update reseed: `(frame_counter + 1) & $1FF`.
                LD   HL, RTypePyGameplay_RngReseedAndUpdate
                LD   (RTypeObjects_Update + 1), HL
                LD   A, #C3
                LD   (RTypeObjects_Update), A
                LD   HL, RTypePyGameplay_ObjectsUpdateWithDispatchDeltas
                LD   (RTypeWorld_Update.eventLoop - 5), HL
                ; Первые семь байтов ArcadeGame_Update раньше вручную
                ; повторяли Python-присваивание. Теперь исполняется только
                ; код, сгенерированный из AST Game.update.
                LD   HL, RTypePyGameplay_AdvanceFrameCounter
                LD   (ArcadeGame_Update + 1), HL
                LD   A, #C3
                LD   (ArcadeGame_Update), A
                LD   A, 1
                LD   (RTypePyInitialSnapshotPending), A
                LD   HL, RTYPE_PY_FRAME_COUNTER_SEED
                LD   (FrameCounter), HL
                RET

RTypePyGameplay_AdvanceFrameCounter:
                LD   A, (RTypePyInitialSnapshotPending)
                OR   A
                CALL NZ, RTypePyGameplay_LoadInitialSnapshot
                LD   HL, (FrameCounter)
                INC  HL
                LD   (FrameCounter), HL
                JP   ArcadeGame_Update + 7

; Serialized by executing Game.__init__/M72EnemyWorld.__init__ from the
; launched Python graph. Source is mapped in slot2; page #09 stays in slot3.
RTypePyInitialSnapshotPending:
                DEFB 0

RTypePyObjects_ClearScratchWithResidue:
                CALL RTypeObjects_ClearScratch
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                RET

RTypePyGameplay_GetDispatchProgression:
                PUSH BC
                PUSH HL
                LD   HL, (RTypeWorldProgressQ8)
                LD   DE, (RTypeWorldFgVelocity)
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:     ADD  HL, DE
                LD   A, (RTypeWorldProgressQ8 + 2)
                ADC  A, C
                LD   E, H
                LD   D, A
                POP  HL
                POP  BC
                RET

RTypePyGameplay_RngReseedAndUpdate:
                LD   HL, (FrameCounter)
                INC  HL
                LD   A, L
                OR   A
                JR   NZ, .bands
                LD   A, H
                AND  1
                CALL Z, RTypeRng_Reset
.bands:         JP   RTypeObjects_UpdateOrdered

; Upload the eight cropped Python charge bitmaps after title RAM_G is detached.
RTypePyChargeAssetsUpload:
                LD   HL, RTypePyChargePageTable
                LD   (.tblPtr), HL
                LD   A, (RTYPE_PY_CHARGE_RAMG >> 16) & #FF
                LD   (.ramgHi), A
                LD   HL, RTYPE_PY_CHARGE_RAMG & #FFFF
                LD   (.ramgLo), HL
                LD   A, RTYPE_PY_CHARGE_PAGE_COUNT
                LD   (.count), A
.next:         LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next
                RET
.tblPtr:       DEFW 0
.ramgLo:       DEFW 0
.ramgHi:       DEFB 0
.chunkLen:     DEFW 0
.count:        DEFB 0

; Python _draw_charge_orb: after intro, while FIRE is held and charge >= $0F.
RTypePyRenderChargeOrb:
                LD   HL, (ArcadeIntroFrame)
                LD   DE, RTYPE_PY_INTRO_FRAMES
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (ArcadeFireHeld)
                OR   A
                RET  Z
                LD   A, (ArcadeWaveCharge)
                CP   RTYPE_PY_CHARGE_VISIBLE
                RET  C
                LD   A, (FrameCounter)
                AND  #1C
                RRCA
                RRCA
                AND  7
                LD   (.phase), A
                CALL RTypePyLogicalBitmapState
                LD   A, (.phase)
                CALL RTypePyCharge_CopyAsset
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, (.phase)
                LD   E, A
                LD   D, 0
                LD   HL, RTypePyChargeCropLeft
                ADD  HL, DE
                LD   E, (HL)
                LD   D, 0
                LD   HL, (ArcadePlayerX + 1)
                ADD  HL, DE
                LD   DE, 53
                ADD  HL, DE
                CALL M72_LogicalToVertex
                LD   (M72SprX), BC
                LD   A, (.phase)
                LD   E, A
                LD   D, 0
                LD   HL, RTypePyChargeCropTop
                ADD  HL, DE
                LD   E, (HL)
                LD   D, 0
                LD   HL, (ArcadePlayerY + 1)
                ADD  HL, DE
                LD   DE, -8
                ADD  HL, DE
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
                FT_End
                RET
.phase:        DEFB 0

; A=phase 0..7, append its five FT812 bitmap-state commands.
RTypePyCharge_CopyAsset:
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, RTypePyChargeCommandTable
                ADD  HL, DE
                LD   BC, 20
                JP   FT.Coprocessor.Copy

; Сохраняет буквальный порядок Game.render: Beam, затем DIST.
RTypePyRenderBeamMeter:
                CALL RTypePyRenderBeamMeterBody
                JP   RTypePyRenderDistance

; Python _draw_beam_meter: собирать захваченный crop 213x9 из 17 HQ tiles.
; Транслятор заранее разрешил все источники и vertex в неизменяемую полосу
; FT812-команд. Runtime выбирает одно из 65 точных состояний.
RTypePyRenderBeamMeterBody:
                LD   HL, (ArcadeIntroFrame)
                LD   DE, RTYPE_PY_INTRO_FRAMES
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (ArcadeWaveCharge)
                CP   #81
                JR   C, .chargeReady
                LD   A, #80
.chargeReady:  SRL  A
                LD   L, A
                LD   H, 0
                PUSH HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                POP  DE
                ADD  HL, DE
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                    ; state * 17 * 8 bytes
                LD   DE, #C000
                ADD  HL, DE
                LD   (.commandPtr), HL
                FT_ScissorXY 352, 726
                FT_ScissorSize 341, 15
                FT_BitmapTransformA 160
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 160
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_ARGB4, M72_GLYPH_W * 2, M72_GLYPH_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, M72_GLYPH_PHYS_W, M72_GLYPH_PHYS_H
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   A, RTYPE_PY_BEAM_COMMAND_PAGE
                SetPage3_A
                LD   HL, (.commandPtr)
                LD   BC, 17 * 8
                CALL FT.Coprocessor.Copy
                FT_End
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 768
                RET
.commandPtr:   DEFW 0

; `$F0F3` body is unreachable after the generated delegated-event patch.
; Reuse those bytes for the two M72Scroll dispatch-delta properties without
; growing Core past the configured FT812 command window.
RTypePyGameplay_OverlayResume EQU $
                ORG  RTypeWorld_DispatchGlobal + 11
RTypePyGameplay_ObjectsUpdateWithDispatchDeltas:
                LD   A, (RTypeWorldFgScrollQ8)
                LD   L, A
                LD   H, 0
                LD   DE, (RTypeWorldFgVelocity)
                CALL .integratedDelta
                LD   (RTypeWorldFgDelta), HL
                LD   A, (RTypeWorldBgScrollQ8)
                LD   L, A
                LD   H, 0
                LD   DE, (RTypeWorldBgVelocity)
                CALL .integratedDelta
                LD   (RTypeWorldBgDelta), HL
                JP   RTypeObjects_Update
.integratedDelta:
                ADD  HL, DE
                LD   A, H
                NEG
                LD   L, A
                ADD  A, A
                SBC  A, A
                LD   H, A
                RET
                ASSERT $ <= RTypeWorld_DispatchGlobal.checkStop
                ORG  RTypePyGameplay_OverlayResume
