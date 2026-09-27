; ============================================================================
; Банк object handlers #0A, исполняемый в slot2 `$8000..$BFFF`.
;
; Резидентные trampolines отображают эту страницу только на время CALL и до
; возврата восстанавливают Core page #06. Код банка хранит живую запись в
; `RTYPE_OBJECT_SCRATCH` (#4300), поэтому World ROM и обе ring-карты можно
; читать через slot3 без самомодификации исполняемого кода.
; ============================================================================

; `$55E9`: создать terrain-bound carrier. Координаты берутся из общей таблицы
; `$8DD0`, high nibble команды задаёт начальную motion phase и будущий pickup.
; Оба Q8 residue наследуются от физического FIFO slot буквально, как байты
; `$0672/$0689` исходной 64-байтовой записи.
RTypeBank1_InitTerrainBound:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TERRAIN_BOUND
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                LD   (RTypeBank1_TerrainCommand), A
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
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #2826
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #0F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #0F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTypeBank1_TerrainCommand)
                RRCA
                RRCA
                RRCA
                RRCA
                AND  7
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_INDEX), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0150
                OR   A
                SBC  HL, DE
                LD   HL, #9A96
                JR   NC, .scriptReady
                LD   HL, #9AB2
.scriptReady:  CALL RTypeBank1_TerrainInstallMotion
                LD   A, RTYPE_TERRAIN_SCRIPT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #2826
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; HL=корень compressed-motion list. Инициализировать `$F5C1` на два movement
; command за VBlank. Phase хранится отдельно: initializer уже записал high
; nibble события, а turn-path после этого вызова явно создаёт новую phase=0,
; как конструктор ScriptedMotion в Python oracle.
RTypeBank1_TerrainInstallMotion:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                RET

; Возврат A=1 для right-facing phase `$00/$0C`, A=0 для `$04/$08`.
; ROM выбирает ветвь по parity после AND `$0C`; явное сравнение сохраняет тот
; же результат и делает выбор descriptor pair читаемым.
RTypeBank1_TerrainRightFacing:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                AND  #0C
                JR   Z, .right
                CP   #0C
                JR   Z, .right
                XOR  A
                RET
.right:        LD   A, 1
                RET

; HL=right descriptor, DE=left descriptor. Вернуть выбранный base в HL.
RTypeBank1_TerrainDescriptorPair:
                CALL RTypeBank1_TerrainRightFacing
                OR   A
                RET  NZ
                EX   DE, HL
                RET

; Добавить signed foreground delta к native X.
RTypeBank1_TerrainAddScroll:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                RET

; Подготовить выбранный descriptor и пометить sprite готовым к draw-pass.
RTypeBank1_TerrainPrepareHL:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                JP   RTypeSprite_PrepareDescriptor

; Освободить carrier resource и удалить запись. Q8 fractions намеренно
; остаются в scratch: scheduler возвращает slot в FIFO без их затирания.
RTypeBank1_TerrainRemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$5629/$5620/$568F/$5704/$577B`: normal terrain state machine. Pickup и
; speed-indicator ветви добавляются вместе с fixed-player collision/weapon
; subsystem; до разрушения carrier ни одна из них недостижима.
RTypeBank1_UpdateTerrainBound:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_TERRAIN_SCRIPT
                JP   Z, RTypeBank1_TerrainScript
                CP   RTYPE_TERRAIN_AIR_STEP
                JP   Z, RTypeBank1_TerrainAirStep
                CP   RTYPE_TERRAIN_LAND
                JP   Z, RTypeBank1_TerrainLand
                CP   RTYPE_TERRAIN_WALK
                JP   Z, RTypeBank1_TerrainWalk
                CP   RTYPE_TERRAIN_TURN
                JP   Z, RTypeBank1_TerrainTurn
                CP   RTYPE_TERRAIN_PICKUP
                JP   Z, RTypeBank1_TerrainPickup
                CP   RTYPE_TERRAIN_SPEED
                JP   Z, RTypeBank1_TerrainSpeedIndicator
                RET

RTypeBank1_TerrainScript:
                CALL RTypeObjects_ScriptedMotion
                JR   RTypeBank1_TerrainAirCommon

RTypeBank1_TerrainAirStep:
                ; Velocity `$FF00` меняет целую Y на -1 и сохраняет residue.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL

RTypeBank1_TerrainAirCommon:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2826
                LD   DE, #282C
                CALL RTypeBank1_TerrainDescriptorPair
                CALL RTypeBank1_TerrainPrepareHL
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_TerrainRemove
                ; Нижний probe `(x,y-$10)`: solid выравнивает native Y к 8,
                ; ставит 31-кадровую посадочную анимацию и завершает pass.
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0010
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .sideProbe
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 7
                ADD  HL, DE
                LD   A, L
                AND  #F8
                LD   L, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, RTYPE_TERRAIN_LAND
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.sideProbe:    CALL RTypeBank1_TerrainRightFacing
                LD   DE, -#0010
                OR   A
                JR   Z, .sideXReady
                LD   DE, #0010
.sideXReady:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .installAir
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0010
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  NC
.installAir:   LD   A, RTYPE_TERRAIN_AIR_STEP
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_TerrainLand:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2832
                LD   DE, #284A
                CALL RTypeBank1_TerrainDescriptorPair
                PUSH HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   E, A
                LD   D, 0
                POP  HL
                ADD  HL, DE
                CALL RTypeBank1_TerrainPrepareHL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_TERRAIN_WALK
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_TerrainWalk:
                CALL RTypeBank1_TerrainRightFacing
                OR   A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                JR   Z, .moveLeft
                INC  HL
                JR   .moveReady
.moveLeft:     DEC  HL
.moveReady:    LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2862
                LD   DE, #287A
                CALL RTypeBank1_TerrainDescriptorPair
                PUSH HL
                LD   A, (FrameCounter)
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   E, A
                LD   D, 0
                POP  HL
                ADD  HL, DE
                CALL RTypeBank1_TerrainPrepareHL
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_TerrainRemove
                CALL RTypeBank1_TerrainRightFacing
                LD   DE, -#0010
                OR   A
                JR   Z, .aheadXReady
                LD   DE, #0010
.aheadXReady:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0014
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .beginTurn
                CALL RTypeBank1_TerrainRightFacing
                LD   DE, -#0012
                OR   A
                JR   Z, .secondXReady
                LD   DE, #0012
.secondXReady: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#000E
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                XOR  8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
.beginTurn:    LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, RTYPE_TERRAIN_TURN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_TerrainTurn:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2892
                LD   DE, #28AA
                CALL RTypeBank1_TerrainDescriptorPair
                PUSH HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   E, A
                LD   D, 0
                POP  HL
                ADD  HL, DE
                CALL RTypeBank1_TerrainPrepareHL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                CALL RTypeBank1_TerrainRightFacing
                LD   HL, #9AA2
                OR   A
                JR   Z, .scriptReady
                LD   HL, #9AB2
.scriptReady:  CALL RTypeBank1_TerrainInstallMotion
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, RTYPE_TERRAIN_SCRIPT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

; `$5811`: carrier остаётся в своей записи, меняет resource/handler на pickup,
; а отдельная запись `$E7BE` создаётся с priority `$A000`.
RTypeBank1_ConvertTerrainToPickup:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_INDEX)
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   A, (FrameCounter)
                AND  2
                ADD  A, E
                LD   E, A
                LD   HL, #27FE
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord       ; E=resource type, D=pickup type
                LD   A, D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_TYPE), A
                LD   (RTypeBank1_PickupType), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_PHASE), A
                LD   A, RTYPE_TERRAIN_PICKUP
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                CALL RTypeBank1_PickupDescriptor
                CALL RTypeSprite_PrepareDescriptor

                ; Зафиксировать изменённый carrier, временно занять новую
                ; запись под `$E7BE`, затем вернуть исходный scratch вызывающему.
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_PickupSourceIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_PickupSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_PickupSourceY), HL
                LD   A, (RTypeBank1_PickupSourceIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_DOB_DEBRIS
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #A000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_PickupSourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank1_PickupSourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
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
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank1_PickupSourceIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Выбрать статический descriptor типа либо двенадцатикадровый special type 8.
RTypeBank1_PickupDescriptor:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_TYPE)
                CP   8
                JR   Z, .animated
                LD   E, A
                LD   D, 0
                ADD  A, A
                ADD  A, E
                ADD  A, A                        ; pickup type * 6
                LD   E, A
                LD   D, 0
                LD   HL, #278C
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET
.animated:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_PHASE)
                LD   E, A
                LD   D, 0
                ADD  A, A
                ADD  A, E
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #27B6
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank1_TerrainPickup:
                LD   A, (FrameCounter)
                AND  7
                JR   NZ, .scroll
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_PHASE)
                INC  A
                CP   12
                JR   C, .phaseReady
                XOR  A
.phaseReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_PHASE), A
.scroll:       CALL RTypeBank1_TerrainAddScroll
                CALL RTypeBank1_PickupDescriptor
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeBank1_PickupOverlapsPlayer
                JR   C, RTypeBank1_PickupCollect
                CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank1_TerrainRemove

; Carry=1 для точного asymmetric overlap pickup `$2784` и R-9 `$2027`.
RTypeBank1_PickupOverlapsPlayer:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -16
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                LD   BC, 8
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL                      ; DE=player.x+8
                OR   A
                SBC  HL, DE
                JR   NC, .no                     ; pickup.left строго меньше
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, 14
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                LD   BC, -7
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL                      ; DE=player.x-7
                OR   A
                SBC  HL, DE
                JR   C, .no                      ; equality допустима
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -14
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                LD   BC, 6
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL
                OR   A
                SBC  HL, DE
                JR   NC, .no
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 14
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                DEC  DE
                OR   A
                SBC  HL, DE
                JR   C, .no
                SCF
                RET
.no:           OR   A
                RET

RTypeBank1_PickupCollect:
                LD   A, #3A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, 4                        ; ES:$86F4 common collection score
                CALL RTypeObjectBank1_AwardScore
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TERRAIN_PICKUP_TYPE)
                CP   8
                JR   NC, .auxiliary
                LD   HL, ArcadeWeaponPickupPending
                INC  (HL)
                LD   (ArcadeWeaponType), A
                JP   RTypeBank1_TerrainRemove
.auxiliary:    LD   E, A
                LD   D, 0
                LD   HL, #281E - 8
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   HL, #0033
                OR   A
                SBC  HL, DE
                JR   Z, .bit
                LD   HL, #0035
                OR   A
                SBC  HL, DE
                JR   Z, .ram35
                LD   HL, #0036
                OR   A
                SBC  HL, DE
                JP   NZ, RTypeBank1_TerrainRemove
                LD   HL, ArcadePlayerRam0036
                INC  (HL)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #09
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #09
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, RTYPE_TERRAIN_SPEED
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JR   RTypeBank1_TerrainSpeedIndicator
.bit:          LD   HL, ArcadeBitCount
                INC  (HL)
                JP   RTypeBank1_TerrainRemove
.ram35:        LD   HL, ArcadePlayerRam0035
                INC  (HL)
                JP   RTypeBank1_TerrainRemove

RTypeBank1_TerrainSpeedIndicator:
                LD   HL, (RTypePlayerNativeX)
                LD   DE, -#001F
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                AND  #0C
                LD   E, A
                LD   D, 0
                SRL  A
                ADD  A, E                        ; phase + phase/2
                LD   E, A
                LD   HL, #28C2
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank1_TerrainRemove

RTypeBank1_PickupType:        DEFB 0
RTypeBank1_PickupSourceIndex: DEFB 0
RTypeBank1_PickupSourceX:     DEFW 0
RTypeBank1_PickupSourceY:     DEFW 0
RTypeBank1_TerrainCommand:
                DEFB 0

; ----------------------------------------------------------------------------
; `$80E3/$8138/$82D6`: player-targeting mini-boss и два attack child.
; ----------------------------------------------------------------------------

RTypeBank1_InitTargeting80E3:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TARGETING_80E3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #A000
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
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #38A2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #20
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #20
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_PALETTE), A
                LD   HL, (RTypePlayerNativeX)
                LD   DE, #00F0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_X), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PREVIOUS_TARGET_X), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_Y), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PREVIOUS_TARGET_Y), HL
                LD   HL, #FFFF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RETARGET_COUNTER), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_DELAY), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_DELAY + 1), A
                LD   HL, #01C0
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ACTIVATION_TIMER), HL
                LD   HL, #001E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_HP), HL
                LD   A, RTYPE_TARGETING_TRACKING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #38A2
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; Освободить обе палитры root `$80E3` и удалить его запись.
RTypeBank1_TargetingRemoveRoot:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Удалить attack child, который удерживает единственный resource `$09`.
RTypeBank1_TargetingRemoveChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; BC=X, DE=Y. Carry=0 только если и foreground >= `$0DFC`, и background
; >= `$07D0`. Координаты сохраняются, потому что первый probe меняет slot3.
RTypeBank1_TargetingCollisionClear:
                LD   (RTypeBank1_ProbeX), BC
                LD   (RTypeBank1_ProbeY), DE
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .blocked
                LD   BC, (RTypeBank1_ProbeX)
                LD   DE, (RTypeBank1_ProbeY)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .blocked
                OR   A
                RET
.blocked:      SCF
                RET

; Вызвать общий `$1D89` для произвольной target-пары, временно подставив её
; вместо fixed-player coordinates. Реальные слова восстанавливаются до RET.
RTypeBank1_TargetingDirection:
                LD   HL, (RTypePlayerNativeX)
                LD   (RTypeBank1_SavedPlayerX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTypeBank1_SavedPlayerY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_X)
                LD   (RTypePlayerNativeX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_Y)
                LD   (RTypePlayerNativeY), HL
                CALL RTypeDirection_Offset
                LD   (RTypeBank1_TargetDirection), A
                LD   HL, (RTypeBank1_SavedPlayerX)
                LD   (RTypePlayerNativeX), HL
                LD   HL, (RTypeBank1_SavedPlayerY)
                LD   (RTypePlayerNativeY), HL
                LD   A, (RTypeBank1_TargetDirection)
                RET

RTypeBank1_UpdateTargeting80E3:
                ; `$8409`: каждый pass сначала обслуживает 16-count hit flash.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_TIMER)
                LD   A, H
                OR   L
                JR   Z, .state
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_TIMER), HL
                LD   A, L
                AND  3
                JR   NZ, .state
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.state:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_TARGETING_ATTACK
                JP   Z, RTypeBank1_TargetingAttack

; `$8138`: раз в 32 passes переснять player target и две Q8 velocity.
RTypeBank1_TargetingTrack:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RETARGET_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RETARGET_COUNTER), HL
                LD   A, L
                AND  #1F
                JR   NZ, .velocityReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_X)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PREVIOUS_TARGET_X), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_Y)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PREVIOUS_TARGET_Y), HL
                LD   HL, (RTypePlayerNativeX)
                LD   DE, #00A0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_X), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_Y), HL
                CALL RTypeBank1_TargetingDirection
                LD   E, A
                LD   D, 0
                LD   HL, #3966
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
.velocityReady:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ACTIVATION_TIMER)
                LD   A, H
                OR   L
                JR   NZ, .xProbe
                LD   HL, -#0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL

; X probe находится на 48 native pixels впереди по знаку velocity. Движение
; блокируется любой картой и правой границей `$02A0` для неотрицательной Xv.
.xProbe:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0030
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   Z, .xProbeReady
                LD   DE, -#0030
.xProbeReady:  ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeBank1_TargetingCollisionClear
                JR   C, .yProbe
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   NZ, .moveX
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02A0
                OR   A
                SBC  HL, DE
                JR   NC, .yProbe
.moveX:        LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X

.yProbe:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0030
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1)
                BIT  7, A
                JR   Z, .yProbeReady
                LD   DE, -#0030
.yProbeReady:  ADD  HL, DE
                EX   DE, HL
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                CALL RTypeBank1_TargetingCollisionClear
                JR   C, .animation
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y

; `$81D9…$8231`: сторона игрока выбирает table, отрицательная X velocity —
; alternate table и saturating animation offset `$00..$3E`.
.animation:    LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                LD   HL, #3866
                JR   C, .sideReady
                LD   HL, #3876
.sideReady:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   Z, .positiveVelocity
                LD   DE, 8
                ADD  HL, DE
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATION_OFFSET)
                CP   #3E
                JR   NC, .offsetReady
                INC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATION_OFFSET), A
                JR   .offsetReady
.positiveVelocity:
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATION_OFFSET), A
.offsetReady:  LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATION_OFFSET)
                AND  #30
                RRCA
                RRCA
                RRCA
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE

; Вертикальное окно `(playerY-$18, playerY+$18]` единственное уменьшает delay.
                LD   HL, (RTypePlayerNativeY)
                LD   DE, #0018
                ADD  HL, DE
                LD   (RTypeBank1_TargetUpper), HL
                LD   DE, #0030
                OR   A
                SBC  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                OR   A
                SBC  HL, DE
                JR   NC, .activation             ; lower >= y: вне окна
                LD   HL, (RTypeBank1_TargetUpper)
                OR   A
                SBC  HL, DE
                JR   C, .activation              ; upper < y: вне окна
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_DELAY)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_DELAY), HL
                LD   A, H
                OR   L
                JR   NZ, .activation
                ; Difficulty=0 пока соответствует активному DSW target build;
                ; таблица всё равно читается из ROM, а не пришита константой.
                LD   HL, #3856
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_DELAY), DE
                LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_TIMER), HL
                LD   A, RTYPE_TARGETING_ATTACK
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A

.activation:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ACTIVATION_TIMER)
                LD   A, H
                OR   L
                JR   Z, .bounds
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ACTIVATION_TIMER), HL
.bounds:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0130
                OR   A
                SBC  HL, DE
                JP   C, RTypeBank1_TargetingRemoveRoot
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

; `$82D6`: 31-count lunge. На timer `$10` projectile и launch flash занимают
; два последовательных FIFO slots, но их более ранние priorities исполняются
; только со следующего VBlank.
RTypeBank1_TargetingAttack:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_TIMER)
                LD   (RTypeBank1_TargetAttackTimer), HL
                LD   A, H
                OR   A
                JR   NZ, .descriptor
                LD   A, L
                CP   #0E
                JR   NC, .descriptor
                LD   DE, -#00C0
                CP   8
                JR   C, .move
                LD   DE, #0200
.move:         CALL RTypeProjectile_AddQ8X
.descriptor:   LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                LD   HL, #388E
                JR   NC, .tableReady
                LD   HL, #3886
.tableReady:   LD   A, (RTypeBank1_TargetAttackTimer)
                AND  #18
                RRCA
                RRCA
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                LD   HL, (RTypeBank1_TargetAttackTimer)
                LD   A, H
                OR   A
                JR   NZ, .decrement
                LD   A, L
                CP   #10
                CALL Z, RTypeBank1_TargetingSpawnChildren
.decrement:    LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ATTACK_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .bounds
                LD   A, RTYPE_TARGETING_TRACKING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
.bounds:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0130
                OR   A
                SBC  HL, DE
                JP   C, RTypeBank1_TargetingRemoveRoot
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_TargetingSpawnChildren:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_TargetParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_TargetParentX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_TargetParentY), HL
                CALL RTypeObjects_StoreScratch
                CALL RTypeBank1_TargetingSpawnShot
                CALL RTypeBank1_TargetingSpawnFlash
                LD   A, (RTypeBank1_TargetParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank1_TargetingSpawnShot:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TARGETING_SHOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #2000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_TargetParentY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #3926
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, #385E
                CALL RTypeWorldRom_ReadWord
                LD   HL, (RTypePlayerNativeX)
                LD   BC, (RTypeBank1_TargetParentX)
                OR   A
                SBC  HL, BC
                LD   HL, (RTypeBank1_TargetParentX)
                JR   C, .left
                LD   BC, #0030
                ADD  HL, BC
                ; Отрицание signed Q8 velocity без потери borrow.
                LD   A, E
                CPL
                LD   E, A
                LD   A, D
                CPL
                LD   D, A
                INC  DE
                JR   .positionReady
.left:         LD   BC, -#0030
                ADD  HL, BC
.positionReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                LD   A, #09
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #09
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #3926
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank1_TargetingSpawnFlash:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TARGETING_FLASH
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1F00
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_TargetParentY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTypeBank1_TargetParentX)
                OR   A
                SBC  HL, DE
                LD   HL, (RTypeBank1_TargetParentX)
                JR   C, .left
                LD   DE, #0032
                ADD  HL, DE
                LD   DE, #38F6
                JR   .ready
.left:         LD   DE, -#0026
                ADD  HL, DE
                LD   DE, #390E
.ready:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_ROOT), DE
                LD   HL, #000F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_SEQUENCE), HL
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_DELAY), HL
                LD   A, #09
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #09
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                JP   RTypeObjects_CommitCurrent

RTypeBank1_UpdateTargetingFlash:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_DELAY)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_DELAY), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_DELAY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_SEQUENCE)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_SEQUENCE), HL
                LD   A, H
                OR   L
                JP   Z, RTypeBank1_TargetingRemoveChild
                LD   A, L
                AND  #0C
                LD   B, A
                SRL  A
                ADD  A, B                         ; `(timer & $0C) * 3 / 2`
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_ROOT)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_UpdateTargetingShot:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   HL, #3926
                LD   A, (FrameCounter)
                AND  4
                JR   NZ, .phaseReady
                LD   DE, #0018
                ADD  HL, DE
.phaseReady:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   NZ, .descriptorReady
                LD   DE, #000C
                ADD  HL, DE
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank1_TargetingRemoveChild

RTypeBank1_ProbeX:              DEFW 0
RTypeBank1_ProbeY:              DEFW 0
RTypeBank1_SavedPlayerX:        DEFW 0
RTypeBank1_SavedPlayerY:        DEFW 0
RTypeBank1_TargetUpper:         DEFW 0
RTypeBank1_TargetAttackTimer:   DEFW 0
RTypeBank1_TargetParentX:       DEFW 0
RTypeBank1_TargetParentY:       DEFW 0
RTypeBank1_TargetDirection:     DEFB 0
RTypeBank1_TargetParentIndex:   DEFB 0

; ----------------------------------------------------------------------------
; `$74B4` parent и ballistic `$780E` child.
; ----------------------------------------------------------------------------

RTypeBank1_InitLargeTerrain:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_LARGE_TERRAIN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                ; Parent наследует только X fraction: Y никогда не интегрируется
                ; Q8-операцией и в Python объект не объявляет y_fraction.
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, #8230
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
                EX   DE, HL
                LD   DE, -8
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #334E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #2B
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_PALETTE), A
                LD   A, 6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_HP), A
                ; Difficulty=0: literal first word `$3346`, всё последующее
                ; состояние использует сохранённый reload, а не константу.
                LD   HL, #3346
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN_RELOAD), DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN), DE
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   HL, #0080
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                LD   HL, #33AE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE), HL
                LD   HL, #33DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE), HL
                LD   A, RTYPE_LARGE_BOOTSTRAP
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #334E
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank1_LargeRemoveParent:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank1_LargeRemoveChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Подготовить descriptor HL и сохранить render-ready marker.
RTypeBank1_LargePrepareHL:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                JP   RTypeSprite_PrepareDescriptor

; Descriptor движения: отрицательная velocity выбирает `$337E`, иначе
; `$334E`; A=0 оставляет базовый кадр, A!=0 добавляет animation phase.
RTypeBank1_LargeMoveDescriptor:
                LD   C, A
                LD   HL, #334E
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   Z, .baseReady
                LD   HL, #337E
.baseReady:    LD   A, C
                OR   A
                RET  Z
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                AND  #1C
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                RET

; `$7607`: relation с fixed-player выбирает следующий 8-count move/wait.
RTypeBank1_LargeChooseDirection:
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                JR   NC, .moveRight
                EX   DE, HL                       ; HL=object X
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE                       ; distance object-player
                LD   DE, #0069
                OR   A
                SBC  HL, DE
                JR   C, .moveRight                ; distance <= `$68`
                LD   DE, #0014                    ; `$7D-$69`
                OR   A
                SBC  HL, DE
                JR   C, .wait                     ; distance <= `$7C`
                LD   HL, -#0180
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   A, RTYPE_LARGE_MOVE
                JR   .stateReady
.moveRight:    LD   HL, #0200
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   A, RTYPE_LARGE_MOVE
                JR   .stateReady
.wait:         LD   A, RTYPE_LARGE_WAIT
.stateReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                RET

RTypeBank1_LargeBeginOpen:
                LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, RTYPE_LARGE_OPEN
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #33AE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE), HL
                LD   HL, #33DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE), HL
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, #33C6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE), HL
                LD   HL, #3402
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE), HL
                RET

; Проверить bounds и подготовить текущий descriptor; Carry/outside удаляет
; parent вместе с обеими палитрами.
RTypeBank1_LargeParentFinish:
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_LargeRemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_UpdateLargeTerrain:
                ; Hit flash cadence общий с `$80E3`, но initial timer здесь 0.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_TIMER)
                OR   A
                JR   Z, .state
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_TIMER), A
                AND  3
                JR   NZ, .state
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.state:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_LARGE_BOOTSTRAP
                JR   NZ, .scroll
                LD   HL, -#0180
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, RTYPE_LARGE_MOVE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.scroll:       CALL RTypeBank1_TerrainAddScroll
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_LARGE_MOVE
                JP   Z, RTypeBank1_LargeMove
                CP   RTYPE_LARGE_WAIT
                JP   Z, RTypeBank1_LargeWait
                CP   RTYPE_LARGE_OPEN
                JP   Z, RTypeBank1_LargeOpen
                CP   RTYPE_LARGE_SHOOT
                JP   Z, RTypeBank1_LargeShoot
                JP   RTypeBank1_LargeClose

RTypeBank1_LargeMove:
                LD   A, 1
                CALL RTypeBank1_LargeMoveDescriptor
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                ; Ahead terrain probe выполняется до независимой Q8 velocity.
                LD   DE, #0010
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   Z, .aheadReady
                LD   DE, -#0010
.aheadReady:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#000C
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .move
                LD   A, RTYPE_LARGE_WAIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, 8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor
.move:         LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_LargeRemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                CALL RTypeBank1_LargeCooldown
                JR   NZ, .cooldownActive
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor
.cooldownActive:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank1_LargeChooseDirection
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

; Уменьшить cooldown. Z=1 означает transition в open, NZ — обычный pass.
RTypeBank1_LargeCooldown:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN), HL
                LD   A, H
                OR   L
                JR   NZ, .active
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_COOLDOWN), HL
                CALL RTypeBank1_LargeBeginOpen
                XOR  A
                RET
.active:       OR   1
                RET

RTypeBank1_LargeWait:
                XOR  A
                CALL RTypeBank1_LargeMoveDescriptor
                CALL RTypeBank1_LargePrepareHL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                CALL RTypeBank1_LargeCooldown
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, H
                OR   L
                JP   Z, RTypeBank1_LargeChooseDirection
                RET

RTypeBank1_LargeOpen:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE)
                PUSH HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   E, A
                LD   D, 0
                POP  HL
                ADD  HL, DE
                CALL RTypeBank1_LargePrepareHL
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_LargeRemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_LARGE_SHOOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_LargeShoot:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                LD   A, L
                LD   (RTypeBank1_LargeAnimationLow), A
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE)
                LD   A, L
                AND  8
                JR   Z, .descriptorReady
                LD   HL, 6
                ADD  HL, DE
                EX   DE, HL
.descriptorReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                LD   A, (RTypeBank1_LargeAnimationLow)
                AND  #0F
                CALL Z, RTypeBank1_LargeSpawnChild
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_LargeRemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, H
                OR   A
                JR   NZ, .beginClose
                LD   A, L
                CP   #80
                JR   C, .prepare
.beginClose:   LD   HL, #001F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE)
                LD   DE, #000C
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE), HL
                LD   A, RTYPE_LARGE_CLOSE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
.prepare:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_LargeClose:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_OPEN_BASE)
                PUSH HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   E, A
                LD   D, 0
                POP  HL
                ADD  HL, DE
                CALL RTypeBank1_LargePrepareHL
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_LargeRemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_ANIMATION), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_STATE_TIMER), HL
                LD   A, H
                OR   L
                JP   Z, RTypeBank1_LargeChooseDirection
                RET

; `$77C1`: parent priority `$8230`, child `$C000`; scheduler вызовет первый
; `$780E` pass позже в этом же VBlank. Здесь только allocation/init/commit.
RTypeBank1_LargeSpawnChild:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_LargeParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_LargeParentX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_LargeParentY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_SHOOT_BASE)
                LD   (RTypeBank1_LargeParentShootBase), HL
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_LARGE_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #C000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_LargeParentX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank1_LargeParentY)
                LD   DE, #0010
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #343A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #2C
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #2C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeRng_Next                 ; vertical random
                LD   A, L
                AND  1
                LD   D, A
                LD   E, H                          ; low byte swapped value
                EX   DE, HL
                LD   DE, #0280
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                CALL RTypeRng_Next                 ; horizontal random
                LD   L, H
                LD   H, 0
                LD   DE, #00C0
                ADD  HL, DE
                PUSH HL
                LD   HL, (RTypeBank1_LargeParentShootBase)
                LD   DE, #33DE
                OR   A
                SBC  HL, DE
                POP  HL
                JR   NZ, .velocityReady
                LD   A, L
                CPL
                LD   L, A
                LD   A, H
                CPL
                LD   H, A
                INC  HL
.velocityReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   A, RTYPE_LARGE_CHILD_RISE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #343A
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank1_LargeParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Перевести ballistic child в explosion player `$E7AE` в той же записи.
RTypeBank1_LargeChildBeginExplosion:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, RTYPE_LARGE_CHILD_EXPLOSION
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #8552
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_PTR), HL
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_TIMER), HL
                RET

RTypeBank1_UpdateLargeChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_LARGE_CHILD_EXPLOSION
                JP   Z, RTypeBank1_LargeChildExplosion
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_LARGE_CHILD_RISE
                JP   NZ, RTypeBank1_LargeChildFall

; Rise descriptor выбирается до gravity decrement.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #0240
                OR   A
                SBC  HL, DE
                LD   HL, #343A
                JR   NC, .descriptorSide
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #0180
                OR   A
                SBC  HL, DE
                LD   HL, #3446
                JR   NC, .descriptorSide
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #0100
                OR   A
                SBC  HL, DE
                LD   HL, #3452
                JR   NC, .descriptorSide
                LD   HL, #345E
.descriptorSide:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   NZ, .descriptorReady
                LD   DE, 6
                ADD  HL, DE
.descriptorReady:
                CALL RTypeBank1_LargePrepareHL
                CALL RTypeBank1_LargeChildCollision
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   (RTypeBank1_LargeOldYVelocity), HL
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   HL, (RTypeBank1_LargeOldYVelocity)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                RET  NC
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY + 1), A
                LD   A, RTYPE_LARGE_CHILD_FALL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_LargeChildFall:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), HL
                LD   DE, #FDC0
                OR   A
                SBC  HL, DE
                LD   HL, #346A
                JR   C, .side
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #FE80
                OR   A
                SBC  HL, DE
                LD   HL, #3476
                JR   C, .side
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #FF00
                OR   A
                SBC  HL, DE
                LD   HL, #3482
                JR   C, .side
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                LD   DE, #FF80
                OR   A
                SBC  HL, DE
                LD   HL, #348E
                JR   C, .side
                LD   HL, #349A
.side:         LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY + 1)
                BIT  7, A
                JR   NZ, .ready
                LD   DE, 6
                ADD  HL, DE
.ready:        CALL RTypeBank1_LargePrepareHL
                CALL RTypeBank1_LargeChildCollision
                RET

; Carry=1 означает, что update завершён collision/explosion либо bounds remove.
RTypeBank1_LargeChildCollision:
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   NC, .bounds
                CALL RTypeBank1_LargeChildBeginExplosion
                SCF
                RET
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                CALL RTypeBank1_LargeRemoveChild
                SCF
                RET

RTypeBank1_LargeChildExplosion:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_PTR)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_PTR)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_PTR), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JP   Z, RTypeBank1_LargeRemoveChild
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_EXPLOSION_TIMER + 1), A
                RET

RTypeBank1_LargeParentX:         DEFW 0
RTypeBank1_LargeParentY:         DEFW 0
RTypeBank1_LargeParentShootBase: DEFW 0
RTypeBank1_LargeOldYVelocity:    DEFW 0
RTypeBank1_LargeParentIndex:     DEFB 0
RTypeBank1_LargeAnimationLow:    DEFB 0

; ----------------------------------------------------------------------------
; `$897E/$89B0/$8AEE`: four-probe terrain seeker.
; ----------------------------------------------------------------------------

RTypeBank1_InitTerrainAware:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TERRAIN_AWARE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #8030
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                LD   (RTypeBank1_SeekerCommand), A
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
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #3C22
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #1D
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #1D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTypeBank1_SeekerCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #8E10
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT), DE
                ; `$F8E4` потребляет RNG даже для all-zero fire record.
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
                LD   HL, #007F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_COUNT), HL
                LD   HL, #3C1A
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_MASK), DE
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, #3C22
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

RTypeBank1_SeekerRemove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank1_UpdateTerrainAware:
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_COUNT)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_COUNT), HL
                PUSH HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_MASK)
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                OR   L
                POP  HL
                JR   NZ, .directionReady
                LD   DE, #0400
                OR   A
                SBC  HL, DE
                JR   NC, .directionReady
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE                       ; Carry: object Y < player Y
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE)
                OR   A
                JR   NZ, .reverseVertical
                LD   A, 2
                JR   NC, .verticalReady
                LD   A, 1
                JR   .verticalReady
.reverseVertical:
                LD   A, 1
                JR   NC, .verticalReady
                LD   A, 2
.verticalReady:
                LD   B, A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   A, 8
                JR   C, .horizontalReady
                LD   A, 4
.horizontalReady:
                OR   B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS), A

.directionReady:
                XOR  A
                LD   (RTypeBank1_SeekerApplied), A
                ; Bit 0: probe Y+$18 и Q8 +$00C0.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS)
                AND  1
                JR   Z, .downUnavailable
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .downUnavailable
                LD   DE, #00C0
                CALL RTypeProjectile_AddQ8Y
                LD   A, (RTypeBank1_SeekerApplied)
                INC  A
                LD   (RTypeBank1_SeekerApplied), A
                JR   .up
.downUnavailable:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE)
                OR   A
                JR   Z, .up
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_ESCAPE_COUNTER), HL

                ; Bit 1: probe Y-$18 и Q8 -$00C0. В reverse state отсутствие
                ; выбранной ветви также сокращает escape lifetime до 1.
.up:           LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS)
                AND  2
                JR   Z, .upUnavailable
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .upUnavailable
                LD   DE, -#00C0
                CALL RTypeProjectile_AddQ8Y
                LD   A, (RTypeBank1_SeekerApplied)
                INC  A
                LD   (RTypeBank1_SeekerApplied), A
                JR   .left
.upUnavailable:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE)
                OR   A
                JR   Z, .left
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_ESCAPE_COUNTER), HL

.left:         LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS)
                AND  4
                JR   Z, .right
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0018
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .right
                LD   DE, -#00C0
                CALL RTypeProjectile_AddQ8X
                LD   A, (RTypeBank1_SeekerApplied)
                INC  A
                LD   (RTypeBank1_SeekerApplied), A

.right:        LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS)
                AND  8
                JR   Z, .scroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0018
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .scroll
                LD   DE, #00C0
                CALL RTypeProjectile_AddQ8X
                LD   A, (RTypeBank1_SeekerApplied)
                INC  A
                LD   (RTypeBank1_SeekerApplied), A

.scroll:       CALL RTypeBank1_TerrainAddScroll
                LD   HL, #3C22
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_DIRECTION_FLAGS)
                AND  8
                JR   Z, .tableReady
                LD   HL, #3C2A
.tableReady:   LD   A, (FrameCounter)
                AND  #30
                RRCA
                RRCA
                RRCA
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_SeekerRemove

                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE)
                OR   A
                JR   NZ, .reverseState
                LD   A, (RTypeBank1_SeekerApplied)
                OR   A
                JR   NZ, .prepare
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE), A
                LD   HL, #03FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_ESCAPE_COUNTER), HL
                JR   .prepare
.reverseState: LD   A, (RTypeBank1_SeekerApplied)
                OR   A
                JR   NZ, .escapeTick
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE), A
                JR   .prepare
.escapeTick:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_ESCAPE_COUNTER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_ESCAPE_COUNTER), HL
                LD   A, H
                OR   L
                JR   NZ, .prepare
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SEEK_REVERSE), A
.prepare:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_SeekerApplied:       DEFB 0
RTypeBank1_SeekerCommand:       DEFB 0

; ----------------------------------------------------------------------------
; `$86A6/$86D3/$86EA`: stationary direction-facing shooter.
; ----------------------------------------------------------------------------

RTypeBank1_InitAnimated86A6:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_ANIMATED_86A6
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (RTypeWorldLastCommand)
                LD   (RTypeBank1_AnimatedCommand), A
                AND  7
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   DE, #930C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #3A36
                BIT  0, D
                JR   Z, .baseReady
                LD   HL, #3A96
.baseReady:    LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATED_DESCRIPTOR_BASE), HL
                LD   A, #10
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTypeBank1_AnimatedCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #8E10
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
                CALL RTypeBank1_AnimatedSelectDescriptor
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; Выбрать одну из шестнадцати сторон: direction byte-offset `$00..$3C`
; превращается в 6-byte descriptor offset как `direction + direction/2`.
RTypeBank1_AnimatedSelectDescriptor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                LD   B, A
                SRL  A
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_ANIMATED_DESCRIPTOR_BASE)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                RET

RTypeBank1_UpdateAnimated86A6:
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                CALL RTypeBank1_TerrainAddScroll
                LD   A, (FrameCounter)
                AND  #0F
                CALL Z, RTypeBank1_AnimatedSelectDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                JR   NC, .prepare
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.prepare:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_AnimatedCommand:     DEFB 0

; ----------------------------------------------------------------------------
; `$6A9B/$6ACB/$6C37/$6E27`: rotating terrain-modifier chain.
; ----------------------------------------------------------------------------

RTypeBank1_InitTerrainModifier:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TERRAIN_MOD_PARENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, #02D8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTypeBank1_ModParentX), HL
                LD   HL, #0154
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #2E46
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_RECORD_POINTER), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_ModParentIndex), A
                XOR  A
                LD   (RTypeBank1_ModChildCount), A
                LD   (RTypeBank1_ModCenterDead), A
                LD   (RTypeBank1_ModBuildPath), A
                LD   (RTypeBank1_ModBuildPath + 1), A
                LD   (RTypeBank1_ModErasePath), A
                LD   (RTypeBank1_ModErasePath + 1), A
                JP   RTypeObjects_CommitCurrent

; A=offset, HL=word: немедленно записать изменённое child-ом parent field в
; page #09. Это сохраняет наблюдаемое состояние конца VBlank, хотя parent с
; меньшим priority уже завершил свой handler.
RTypeBank1_ModWriteParentWord:
                LD   C, A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeBank1_ModParentIndex)
                CALL RTypeObjects_RecordAddress
                LD   E, C
                LD   D, 0
                ADD  HL, DE
                EX   DE, HL
                LD   HL, (RTypeBank1_ModWriteValue)
                LD   A, L
                LD   (DE), A
                INC  DE
                LD   A, H
                LD   (DE), A
                RET

; Вход HL=value; обёртка сохраняет его до расчёта physical record address.
RTypeBank1_ModStoreParentWord:
                LD   (RTypeBank1_ModWriteValue), HL
                JP   RTypeBank1_ModWriteParentWord

RTypeBank1_UpdateTerrainModifierParent:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_ModParentX), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                JP   Z, RTypeBank1_ModSpawnChildren
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank1_ModWriteFullPath
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_ModParentX), HL
                LD   A, (FrameCounter)
                INC  A
                AND  7
                JR   NZ, .lifetime
                LD   A, 1
                CALL RTypeBank1_ModStepPath
                XOR  A
                CALL RTypeBank1_ModStepPath
.lifetime:     LD   A, (RTypeBank1_ModChildCount)
                OR   A
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank1_ModSpawnChildren:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_ModParentIndex), A
                CALL RTypeObjects_StoreScratch
                LD   HL, #2E46
                LD   (RTypeBank1_ModRecord), HL
                LD   A, 1
                LD   (RTypeBank1_ModOrdinal), A
                XOR  A
                LD   (RTypeBank1_ModChildCount), A
.next:         CALL RTypeBank1_ModInitChild
                JR   C, .finish
                LD   A, (RTypeBank1_ModChildCount)
                INC  A
                LD   (RTypeBank1_ModChildCount), A
                LD   HL, (RTypeBank1_ModRecord)
                LD   DE, 8
                ADD  HL, DE
                LD   (RTypeBank1_ModRecord), HL
                LD   A, (RTypeBank1_ModOrdinal)
                INC  A
                LD   (RTypeBank1_ModOrdinal), A
                CP   #11
                JR   C, .next
.finish:       LD   A, (RTypeBank1_ModParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   HL, (RTypeBank1_ModRecord)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_RECORD_POINTER), HL
                LD   A, (RTypeBank1_ModChildCount)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_CHILD_COUNT), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_CHILD_COUNT + 1), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_TIMER), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_ModInitChild:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TERRAIN_MOD_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8021
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_ModRecord)
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #A0BC
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                LD   HL, (RTypeBank1_ModRecord)
                LD   DE, 6
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   A, (RTypeBank1_ModOrdinal)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ORDINAL), A
                ADD  A, A
                ADD  A, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_LOCAL_TIMER), A
                LD   A, #13
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #13
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_HP), A
                LD   A, (RTypeBank1_ModOrdinal)
                CP   4
                JR   NZ, .hpReady
                LD   HL, #2E3E                  ; DSW difficulty 0
                CALL RTypeWorldRom_ReadWord
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_HP), A
.hpReady:
                LD   A, (RTypeBank1_ModOrdinal)
                CP   4
                LD   HL, 4
                JR   Z, .commandReady
                LD   HL, (RTypeBank1_ModRecord)
                LD   DE, 4
                ADD  HL, DE
.commandReady: CALL RTypeWorldRom_ReadWord
                LD   A, E
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #8E10
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
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                CALL RTypeObjects_CommitCurrent
                OR   A
                RET

RTypeBank1_UpdateTerrainModifierChild:
                CALL RTypeObjects_ScriptedMotion
                LD   HL, (RTypeBank1_ModParentX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   NC, .scroll
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeBank1_ModSpawnShot
.scroll:       CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2F0E
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ORDINAL)
                CP   4
                JR   NZ, .baseReady
                LD   HL, #2F6E
.baseReady:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B                         ; phase * 3
                ADD  A, A                         ; phase * 6
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeBank1_ModLinkPaths
                LD   A, (RTypeBank1_ModCenterDead)
                OR   A
                JR   Z, .bounds
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_LOCAL_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_LOCAL_TIMER), HL
                LD   A, H
                OR   L
                JP   Z, RTypeBank1_ModRemoveChild
.bounds:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #00E0
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank1_ModRemoveChild

RTypeBank1_ModRemoveChild:
                LD   A, (RTypeBank1_ModChildCount)
                OR   A
                JR   Z, .resource
                DEC  A
                LD   (RTypeBank1_ModChildCount), A
                LD   L, A
                LD   H, 0
                LD   A, RTYPE_OBJ_MOD_CHILD_COUNT
                CALL RTypeBank1_ModStoreParentWord
.resource:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeBank1_ModLinkPaths:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                BIT  0, H
                RET  Z
                LD   DE, #0144
                OR   A
                SBC  HL, DE
                RET  NC
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ORDINAL)
                CP   #10
                JR   Z, .build
                CP   1
                RET  NZ
                LD   HL, (RTypeBank1_ModErasePath)
                LD   A, H
                OR   L
                RET  NZ
                JR   .relationErase
.build:        LD   HL, (RTypeBank1_ModBuildPath)
                LD   A, H
                OR   L
                RET  NZ
.relationErase:
                LD   HL, (RTypeBank1_ModParentX)
                LD   DE, #0030
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                RET  C
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ORDINAL)
                CP   #10
                JR   NZ, .setErase
                LD   HL, 1
                LD   (RTypeBank1_ModBuildPath), HL
                LD   A, RTYPE_OBJ_MOD_BUILD_PATH
                JP   RTypeBank1_ModStoreParentWord
.setErase:     LD   HL, 1
                LD   (RTypeBank1_ModErasePath), HL
                LD   A, RTYPE_OBJ_MOD_ERASE_PATH
                JP   RTypeBank1_ModStoreParentWord

RTypeBank1_ModSpawnShot:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_SCRIPT)
                LD   A, H
                OR   L
                RET  Z
                LD   (RTypeBank1_ModShotTable), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_ModShotX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_ModShotY), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                LD   (RTypeBank1_ModShotPhase), A
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_ModChildIndex), A
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_TERRAIN_MOD_SHOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, #A000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeBank1_ModShotX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank1_ModShotY)
                LD   DE, #000C
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, #56
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #56
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, (RTypeBank1_ModShotPhase)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTypeBank1_ModShotTable)
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   A, (RTypeObjects_CurrentIndex)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #00A8
                ADD  HL, DE                       ; `(slot_address >> 3)`
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_SHOT_SLOT_PHASE), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank1_ModChildIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank1_UpdateTerrainModifierShot:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_SHOT_BURST)
                LD   A, H
                OR   L
                JR   Z, .move
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_SHOT_BURST), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeBank1_ModRemoveShot
.move:         LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_SHOT_SLOT_PHASE)
                LD   DE, (FrameCounter)
                ADD  HL, DE
                LD   A, L
                AND  #18
                SRL  A
                SRL  A
                LD   B, A
                ADD  A, A
                ADD  A, B
                LD   L, A
                LD   H, 0
                LD   DE, #2EEE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .burst
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_ModRemoveShot
                LD   HL, (RTypeBank1_ModParentX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                JR   NC, .burst
                LD   HL, (RTypeBank1_ModParentX)
                LD   DE, #00C0
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                RET  NC
                JP   RTypeBank1_ModRemoveShot
.burst:        LD   HL, #000A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_SHOT_BURST), HL
                RET

RTypeBank1_ModRemoveShot:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Записать одну foreground cell по byte cursor из HL. DE=code, BC=attribute.
RTypeBank1_ModWriteCell:
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   (HL), E
                INC  HL
                LD   (HL), D
                INC  HL
                LD   (HL), C
                INC  HL
                LD   (HL), B
                RET

; HL=cursor, DE=delta. Сложить байты независимо, без carry low->high.
RTypeBank1_ModAdvanceCursor:
                LD   A, L
                ADD  A, E
                LD   L, A
                LD   A, H
                ADD  A, D
                LD   H, A
                RET

RTypeBank1_ModWriteFullPath:
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_PATH_ORIGIN), HL
                LD   (RTypeBank1_ModPathCursor), HL
                LD   HL, #2EC6
                LD   (RTypeBank1_ModPathPointer), HL
.cell:         LD   HL, (RTypeBank1_ModPathCursor)
                LD   DE, #03E8
                LD   BC, #0081
                CALL RTypeBank1_ModWriteCell
                LD   HL, (RTypeBank1_ModPathPointer)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                RET  Z
                LD   HL, (RTypeBank1_ModPathCursor)
                CALL RTypeBank1_ModAdvanceCursor
                LD   (RTypeBank1_ModPathCursor), HL
                LD   HL, (RTypeBank1_ModPathPointer)
                INC  HL
                INC  HL
                LD   (RTypeBank1_ModPathPointer), HL
                JR   .cell

; A=1 build, A=0 erase. Обработать ровно одну path cell.
RTypeBank1_ModStepPath:
                OR   A
                JR   Z, .erase
                LD   HL, (RTypeBank1_ModBuildPath)
                LD   (RTypeBank1_ModPathMode), A
                JR   .selected
.erase:        LD   HL, (RTypeBank1_ModErasePath)
                LD   (RTypeBank1_ModPathMode), A
.selected:     LD   A, H
                OR   L
                RET  Z
                LD   DE, 1
                OR   A
                SBC  HL, DE
                JR   NZ, .resumeCursor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_PATH_ORIGIN)
                LD   (RTypeBank1_ModPathCursor), HL
                LD   HL, #2EC6
                JR   .havePointer
.resumeCursor: INC  HL                              ; вернуть исходный path pointer
                LD   (RTypeBank1_ModPathPointer), HL
                LD   A, (RTypeBank1_ModPathMode)
                OR   A
                JR   Z, .loadEraseCursor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_BUILD_CURSOR)
                JR   .cursorReady
.loadEraseCursor:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ERASE_CURSOR)
.cursorReady:   LD   (RTypeBank1_ModPathCursor), HL
                LD   HL, (RTypeBank1_ModPathPointer)
.havePointer:  LD   (RTypeBank1_ModPathPointer), HL
                LD   DE, #03E8
                LD   A, (RTypeBank1_ModPathMode)
                OR   A
                JR   NZ, .codeReady
                LD   DE, #0FA0
.codeReady:    LD   HL, (RTypeBank1_ModPathCursor)
                LD   BC, #0081
                CALL RTypeBank1_ModWriteCell
                LD   HL, (RTypeBank1_ModPathPointer)
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   Z, .finished
                LD   HL, (RTypeBank1_ModPathCursor)
                CALL RTypeBank1_ModAdvanceCursor
                LD   (RTypeBank1_ModPathCursor), HL
                LD   A, (RTypeBank1_ModPathMode)
                OR   A
                JR   Z, .saveEraseCursor
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_BUILD_CURSOR), HL
                JR   .cursorSaved
.saveEraseCursor:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ERASE_CURSOR), HL
.cursorSaved:
                LD   HL, (RTypeBank1_ModPathPointer)
                INC  HL
                INC  HL
                JR   .store
.finished:     LD   HL, 0
.store:        LD   A, (RTypeBank1_ModPathMode)
                OR   A
                JR   Z, .storeErase
                LD   (RTypeBank1_ModBuildPath), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_BUILD_PATH), HL
                RET
.storeErase:   LD   (RTypeBank1_ModErasePath), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_ERASE_PATH), HL
                RET

RTypeBank1_ModParentX:       DEFW 0
RTypeBank1_ModChildCount:    DEFB 0
RTypeBank1_ModCenterDead:    DEFB 0
RTypeBank1_ModBuildPath:     DEFW 0
RTypeBank1_ModErasePath:     DEFW 0
RTypeBank1_ModRecord:        DEFW 0
RTypeBank1_ModWriteValue:    DEFW 0
RTypeBank1_ModShotTable:     DEFW 0
RTypeBank1_ModShotX:         DEFW 0
RTypeBank1_ModShotY:         DEFW 0
RTypeBank1_ModPathCursor:    DEFW 0
RTypeBank1_ModPathPointer:   DEFW 0
RTypeBank1_ModOrdinal:       DEFB 0
RTypeBank1_ModParentIndex:   DEFB 0
RTypeBank1_ModChildIndex:    DEFB 0
RTypeBank1_ModShotPhase:     DEFB 0
RTypeBank1_ModPathMode:      DEFB 0

; ----------------------------------------------------------------------------
; `$60BA/$610D…$68EE`: многофазный противник, горизонтальный снаряд и
; четыре отделяемых спутника. Поля разнесены по типам записи, но сохраняют
; исходные offsets M72 object pool.
; ----------------------------------------------------------------------------

RTypeBank1_InitHandler60BA:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_HANDLER_60BA
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                ; command low nibble выбирает пару X/Y из `$8DD0`.
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
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, #2BC8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #21
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #21
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #55
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_PALETTE), A
                LD   HL, #001E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_HP), HL
                ; `$60E7` и `$60FE` делают два RNG-вызова. Второй результат
                ; маскируется оригиналом, но намеренно нигде не сохраняется.
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_PHASE), A
                LD   HL, #2B40
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_RELOAD), DE
                CALL RTypeRng_Next
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER + 1), A
                LD   A, RTYPE_60_STATE_610D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, RTYPE_60_STATE_6243
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_STATE), A
                LD   HL, #0050
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_TIMER), HL
                LD   HL, #2B60
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_LANDING_TABLE), HL
                LD   HL, #2BC8
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; `$661A`: alternate palette видима только после уменьшения счётчика и только
; на значениях, кратных четырём.
RTypeBank1_UpdateHandler60BA:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  #FD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_TIMER)
                OR   A
                JR   Z, .dispatch
                DEC  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_TIMER), A
                AND  3
                JR   NZ, .dispatch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                OR   2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
.dispatch:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_STATE_610D
                JP   Z, RTypeBank1_60State610D
                CP   RTYPE_60_STATE_61E3
                JP   Z, RTypeBank1_60StateLanding
                CP   RTYPE_60_STATE_652F
                JP   Z, RTypeBank1_60StateLanding
                CP   RTYPE_60_STATE_62BD
                JP   Z, RTypeBank1_60State62BD
                CP   RTYPE_60_STATE_6243
                JP   Z, RTypeBank1_60State6243
                CP   RTYPE_60_STATE_631B
                JP   Z, RTypeBank1_60State631B
                CP   RTYPE_60_STATE_6392
                JP   Z, RTypeBank1_60State63Group
                CP   RTYPE_60_STATE_6374
                JP   Z, RTypeBank1_60State63Group
                CP   RTYPE_60_STATE_638C
                JP   Z, RTypeBank1_60State63Group
                CP   RTYPE_60_STATE_6380
                JP   Z, RTypeBank1_60State63Group
                CP   RTYPE_60_STATE_6459
                JP   Z, RTypeBank1_60State6459
                JP   RTypeBank1_60State657C

; Снять сторону R-9: равенство относится к right-facing branch.
RTypeBank1_60FacePlayer:
                LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                LD   A, 0
                JR   C, .store
                INC  A
.store:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING), A
                RET

; Выбрать fall-дескриптор по стороне и `(frame+phase)&4`.
RTypeBank1_60SelectFallDescriptor:
                LD   HL, #2BC8
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .baseReady
                LD   HL, #2C28
.baseReady:    LD   A, (FrameCounter)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_PHASE)
                ADD  A, B
                AND  4
                RET  Z
                LD   DE, #000C
                ADD  HL, DE
                RET

; HL=descriptor. Обычные состояния дополнительно исполняют `$663E`.
RTypeBank1_60ShowFire:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeBank1_60Fire

RTypeBank1_60ShowNoFire:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

; `$663E`: reload-счётчик, асимметричное вертикальное окно и сторона выстрела.
RTypeBank1_60Fire:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_RELOAD)
                OR   A
                SBC  HL, DE
                RET  C
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FIRE_COUNTER + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0018
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                RET  NC                           ; Y-$18 >= playerY
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0020
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                RET  C                            ; Y+$20 < playerY
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .leftFacing
                RET  NC                           ; facing right: только X<player
                JP   RTypeBank1_60SpawnShot
.leftFacing:   RET  C                             ; facing left: только X>=player
                JP   RTypeBank1_60SpawnShot

RTypeBank1_60LandingState: DEFB 0

; A=`$61E3` либо `$652F`: выровнять Y, сдвинуть X на восемь и начать
; пятнадцатикадровую landing-анимацию.
RTypeBank1_60BeginLanding:
                LD   (RTypeBank1_60LandingState), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 7
                ADD  HL, DE
                LD   A, L
                AND  #F8
                LD   L, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -8
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .xReady
                LD   DE, 8
.xReady:       ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #2B60
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .tableReady
                LD   HL, #2B68
.tableReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_LANDING_TABLE), HL
                LD   HL, #000F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, (RTypeBank1_60LandingState)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_60State610D:
                CALL RTypeBank1_60FacePlayer
                LD   DE, -#0080
                CALL RTypeProjectile_AddQ8X
                LD   DE, -#0100
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank1_60SelectFallDescriptor
                CALL RTypeBank1_60ShowFire
                ; Два нижне-левых terrain probes: `(X-4,Y-$18)` и
                ; `(X-$18,Y-$18)`. Любой solid code начинает `$61E3`.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -4
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .land
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0018
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  NC
.land:         LD   A, RTYPE_60_STATE_61E3
                JP   RTypeBank1_60BeginLanding

RTypeBank1_60StateLanding:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_LANDING_TABLE)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                AND  #0C
                SRL  A
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_STATE_652F
                JR   NZ, .firstLanding
                LD   A, RTYPE_60_STATE_657C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.firstLanding: XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING), A
                LD   A, RTYPE_60_STATE_62BD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, RTYPE_60_STATE_6243
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_STATE), A
                LD   HL, #0050
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_TIMER), HL
                RET

RTypeBank1_60State62BD:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                CALL Z, RTypeBank1_60SpawnChildren
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, #2B80
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .descriptorReady
                LD   HL, #2BE0
.descriptorReady:
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_STATE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_TIMER)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                RET

RTypeBank1_60State6243:
                CALL RTypeBank1_TerrainAddScroll
                LD   DE, -#0100
                CALL RTypeProjectile_AddQ8X
                LD   A, (FrameCounter)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_PHASE)
                ADD  A, B
                AND  #38
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, #2B70
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_60_STATE_62BD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0040
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, RTYPE_60_STATE_631B
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_STATE), A
                LD   HL, #000F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_NEXT_TIMER), HL
                ; Landing table выбирается свежим сравнением player X,
                ; но поле facing оригинал в этой точке не переписывает.
                LD   HL, #2B60
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                PUSH HL
                LD   HL, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   C, .tableReady
                LD   HL, #2B68
.tableReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_LANDING_TABLE), HL
                RET

RTypeBank1_60State631B:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_LANDING_TABLE)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                AND  #0C
                SRL  A
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                CALL RTypeBank1_60ShowNoFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_60_STATE_6392
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #0048
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                RET

RTypeBank1_60State63Group:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_STATE_6374
                JR   Z, .possibleChildren
                CP   RTYPE_60_STATE_6380
                JR   NZ, .motion
.possibleChildren:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                LD   DE, #0010
                OR   A
                SBC  HL, DE
                CALL Z, RTypeBank1_60SpawnChildren
.motion:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_STATE_6392
                JR   NZ, .xMotion
                LD   DE, #0100
                CALL RTypeProjectile_AddQ8Y
                JR   .show
.xMotion:      CP   RTYPE_60_STATE_638C
                JR   NZ, .show
                LD   DE, #0100
                CALL RTypeProjectile_AddQ8X
.show:         CALL RTypeBank1_60FacePlayer
                CALL RTypeBank1_60SelectFallDescriptor
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_STATE_6392
                JR   NZ, .after6392
                LD   A, RTYPE_60_STATE_6374
                LD   HL, #0040
                JR   .store
.after6392:    CP   RTYPE_60_STATE_6374
                JR   NZ, .after6374
                LD   A, RTYPE_60_STATE_638C
                LD   HL, #0080
                JR   .store
.after6374:    CP   RTYPE_60_STATE_638C
                JR   NZ, .after638C
                LD   A, RTYPE_60_STATE_6380
                LD   HL, #0040
                JR   .store
.after638C:    LD   A, RTYPE_60_STATE_6459
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.store:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_TIMER), HL
                RET

RTypeBank1_60State6459:
                CALL RTypeBank1_60FacePlayer
                LD   DE, #0080
                CALL RTypeProjectile_AddQ8X
                LD   DE, -#0100
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank1_60SelectFallDescriptor
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, 4
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .land
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0018
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0018
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  NC
.land:         LD   A, RTYPE_60_STATE_652F
                JP   RTypeBank1_60BeginLanding

RTypeBank1_60State657C:
                LD   A, (FrameCounter)
                INC  A
                AND  #7F
                CALL Z, RTypeBank1_60SpawnChildren
                CALL RTypeBank1_TerrainAddScroll
                CALL RTypeBank1_60FacePlayer
                LD   HL, #2C48
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                OR   A
                JR   Z, .descriptorReady
                LD   HL, #2C60
.descriptorReady:
                CALL RTypeBank1_60ShowFire
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank1_60RemoveParent
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                RET  C

RTypeBank1_60RemoveParent:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$663E/$6688`: горизонтальный projectile получает priority `$6000`, поэтому
; созданный parent-ом `$8020` объект впервые исполнится на следующем pass.
RTypeBank1_60SpawnShot:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_60ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_60SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_60SourceY), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FACING)
                LD   (RTypeBank1_60SourceFacing), A
                LD   A, (RTypeBank1_60ParentIndex)
                CALL RTypeObjects_StoreScratch
                CALL RTypeObjects_New
                JR   C, .restore
                LD   A, RTYPE_OBJ_HANDLER_60BA_SHOT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #6000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, (RTypeBank1_60SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeBank1_60SourceY)
                LD   DE, #000A
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, #21
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #21
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #2B50
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                XOR  A
                LD   D, A
                LD   E, A
                OR   A
                EX   DE, HL
                SBC  HL, DE                       ; `-signed(word $2B50)` modulo 16-bit
                LD   DE, #2C78
                LD   A, (RTypeBank1_60SourceFacing)
                OR   A
                JR   Z, .velocityReady
                LD   HL, #2B48
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL
                LD   DE, #2C7E
.velocityReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeBank1_60ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeBank1_UpdateHandler60BAShot:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_AUX_EXPLOSION_WAIT
                JP   Z, RTypeBank1_60ExplosionInit
                CP   RTYPE_60_AUX_EXPLOSION
                JP   Z, RTypeBank1_60ExplosionUpdate
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank1_60BeginExplosionWait
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, RTypeBank1_60RemoveAux
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                RET  C
                JP   RTypeBank1_60RemoveAux

; Terrain/weapon hit освобождает старую палитру сейчас, но `$E7AE` получает
; type `$01` только на следующем scheduler pass в этой же physical записи.
RTypeBank1_60BeginExplosionWait:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, RTYPE_60_AUX_EXPLOSION_WAIT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeBank1_60ExplosionInit:
                LD   A, #01
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #01
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, RTYPE_60_AUX_EXPLOSION
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, #8552
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_PTR), HL
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_TIMER), HL
                ; Инициализатор `$E7AE` падает прямо в первый `$E7D4` pass.

RTypeBank1_60ExplosionUpdate:
                CALL RTypeBank1_TerrainAddScroll
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_PTR)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_PTR)
                LD   DE, 4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_PTR), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JP   Z, RTypeBank1_60RemoveAux
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_TIMER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_EXPLOSION_TIMER + 1), A
                RET

RTypeBank1_60RemoveAux:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$6715/$6788`: таблица содержит четыре возможных вектора. Когда source уже
; левее R-9, запись `$2C9C` пропускается, а оставшиеся векторы зеркалятся.
RTypeBank1_60SpawnChildren:
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeBank1_60ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeBank1_60SourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeBank1_60SourceY), HL
                XOR  A
                LD   (RTypeBank1_60MirrorChildren), A
                LD   HL, RTypeBank1_60ChildTablesFull
                LD   DE, (RTypePlayerNativeX)
                PUSH HL
                LD   HL, (RTypeBank1_60SourceX)
                OR   A
                SBC  HL, DE
                POP  HL
                JR   NC, .tableReady
                LD   A, 1
                LD   (RTypeBank1_60MirrorChildren), A
                LD   HL, RTypeBank1_60ChildTablesMirror
.tableReady:   LD   (RTypeBank1_60ChildListPointer), HL
                LD   A, (RTypeBank1_60ParentIndex)
                CALL RTypeObjects_StoreScratch
.next:         LD   HL, (RTypeBank1_60ChildListPointer)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTypeBank1_60ChildListPointer), HL
                LD   A, D
                OR   E
                JP   Z, .restore
                LD   (RTypeBank1_60ChildTable), DE
                CALL RTypeObjects_New
                JP   C, .restore
                LD   A, RTYPE_OBJ_HANDLER_60BA_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #5000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, (RTypeObjects_TakenYFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   HL, (RTypeBank1_60SourceX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_X), HL
                LD   HL, (RTypeBank1_60SourceY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_Y), HL
                LD   A, #3C
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #3C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A

                LD   HL, (RTypeBank1_60ChildTable)
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                LD   HL, (RTypeBank1_60ChildTable)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   HL, (RTypeBank1_60ChildTable)
                LD   DE, 4
                ADD  HL, DE
                LD   A, (RTypeBank1_60MirrorChildren)
                OR   A
                JR   Z, .directionAddress
                INC  HL
                INC  HL
                ; Mirror меняет знак только horizontal Q8 velocity.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                EX   DE, HL
                LD   HL, 0
                OR   A
                SBC  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), HL
                LD   HL, (RTypeBank1_60ChildTable)
                LD   DE, 6
                ADD  HL, DE
.directionAddress:
                CALL RTypeWorldRom_ReadWord
                LD   A, E
                AND  #0F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION), A
                LD   HL, #2B58
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_TURN_RELOAD), DE
                LD   HL, #0020
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER), HL
                LD   HL, #0800
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_LIFE_TIMER), HL
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                CALL RTypeBank1_60InitChildDescriptors
                CALL RTypeObjects_CommitCurrent
                JP   .next
.restore:      LD   A, (RTypeBank1_60ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Constructor `$67D5` задаёт первый main descriptor, но оставляет overlay на
; корне `$2D54` и ровно в source anchor до первого `$67FA` update.
RTypeBank1_60InitChildDescriptors:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION)
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, #2CB4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, #2D54
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY), HL
                JP   RTypeSprite_PrepareDescriptor

; Рассчитать основной descriptor и позицию/кадр второго overlay `$68EE`.
RTypeBank1_60PrepareChildDescriptors:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION)
                AND  #0F
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                         ; direction * 6
                LD   E, A
                LD   D, 0
                LD   HL, #2CB4
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor

                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION)
                AND  #0F
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                       ; direction * 4
                LD   DE, #2D14
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_X), HL
                CALL RTypeObjects_ReadWordNext
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_Y), HL
                LD   A, (FrameCounter)
                AND  7
                LD   B, A
                ADD  A, A
                ADD  A, B
                ADD  A, A                         ; frame * 6
                LD   E, A
                LD   D, 0
                LD   HL, #2D54
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeBank1_UpdateHandler60BAChild:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_AUX_EXPLOSION_WAIT
                JP   Z, RTypeBank1_60ExplosionInit
                CP   RTYPE_60_AUX_EXPLOSION
                JP   Z, RTypeBank1_60ExplosionUpdate
                CP   RTYPE_60_AUX_HOMING
                JR   NZ, .integrate

                ; `$687D` выполняет TEST life_timer с исходным V30 slot AX,
                ; то есть `$0540 + physical_index*$40`, а не с TS CPU address.
                LD   A, (RTypeObjects_CurrentIndex)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #0540
                ADD  HL, DE
                EX   DE, HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_LIFE_TIMER)
                LD   A, L
                AND  E
                LD   B, A
                LD   A, H
                AND  D
                OR   B
                JR   Z, .zeroTest
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_LIFE_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER), HL
                LD   A, H
                OR   L
                CALL Z, RTypeBank1_60TurnChild
                JR   .integrate
.zeroTest:     CALL RTypeWalker_InsideBounds
                JP   C, RTypeBank1_60RemoveAux

.integrate:    LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                CALL RTypeBank1_60PrepareChildDescriptors
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_AUX_FLIGHT
                JR   NZ, .terrain
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER), HL
                LD   A, H
                OR   L
                JR   NZ, .terrain
                LD   A, RTYPE_60_AUX_HOMING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   HL, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER), HL
.terrain:      LD   A, (FrameCounter)
                INC  A
                AND  1
                JR   Z, .bounds
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JP   C, RTypeBank1_60BeginExplosionWait
.bounds:       CALL RTypeWalker_InsideBounds
                RET  NC
                JP   RTypeBank1_60RemoveAux

; `$689B…$68BC`: повернуть сектор на один шаг по кратчайшей дуге. Равенство
; намеренно идёт в increment branch, поэтому exact target-sector осциллирует.
RTypeBank1_60TurnChild:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_ProjectileSourceX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_ProjectileSourceY), HL
                CALL RTypeDirection_Offset
                SRL  A
                SRL  A
                AND  #0F
                LD   (RTypeBank1_60WantedDirection), A
                LD   B, A                         ; B=wanted
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION)
                AND  #0F
                LD   C, A                         ; C=current
                LD   A, B
                CP   C
                JR   C, .wantedBelow
                CP   8
                JR   C, .increment
                SUB  8
                CP   C
                JR   C, .increment
                JR   .decrement
.wantedBelow:  LD   A, C
                CP   8
                JR   C, .decrement
                SUB  8
                CP   B
                JR   C, .decrement
.increment:    LD   A, C
                INC  A
                AND  #0F
                JR   .storeDirection
.decrement:    LD   A, C
                DEC  A
                AND  #0F
.storeDirection:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_DIRECTION), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                       ; sector * 4
                PUSH HL
                LD   HL, #2C8C
                CALL RTypeWorldRom_ReadWord
                EX   DE, HL                       ; HL=velocity table
                POP  DE                           ; DE=sector * 4
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_TURN_RELOAD)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_MOVE_TIMER), HL
                RET

RTypeBank1_60ChildTablesFull:
                DEFW #2C94, #2C9C, #2CA4, #2CAC, 0
RTypeBank1_60ChildTablesMirror:
                DEFW #2C94, #2CA4, #2CAC, 0

RTypeBank1_60SourceX:           DEFW 0
RTypeBank1_60SourceY:           DEFW 0
RTypeBank1_60ChildListPointer:  DEFW 0
RTypeBank1_60ChildTable:        DEFW 0
RTypeBank1_60ParentIndex:       DEFB 0
RTypeBank1_60SourceFacing:      DEFB 0
RTypeBank1_60MirrorChildren:    DEFB 0
RTypeBank1_60WantedDirection:   DEFB 0
