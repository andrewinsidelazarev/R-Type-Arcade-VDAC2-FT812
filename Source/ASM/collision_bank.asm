; ============================================================================
; Общий collision-dispatcher фиксированных записей R-9/Force/Wave `$F493`,
; `$F548`, `$F578`. Банк #E5 исполняется в slot2 и держит тяжёлые таблицы,
; оставляя resident Core и FT812 command buffer в page #05/#06.
; ============================================================================

RTYPE_COLLISION_FLAG_WEAPON      EQU #01
RTYPE_COLLISION_FLAG_HOSTILE     EQU #02
RTYPE_COLLISION_FLAG_DESCRIPTOR  EQU #04
RTYPE_COLLISION_FLAG_FORCE_ONLY  EQU #08
RTYPE_COLLISION_FLAG_CADENCED    EQU #10
RTYPE_COLLISION_REC_SIZE         EQU 12

RTypeCollisionBank_Update:
                ; `$F6DA`: persistent Force (добавляется ниже) идёт первым,
                ; затем Wave, fixed `$04D6` и контакт самого R-9.
                CALL RTypeCollision_UpdateWave
                CALL RTypeCollision_UpdateShots
                JP   RTypeCollision_UpdatePlayer

; ---------------------------------------------------------------------------
; Три fixed-shot record `$04D6`. Только FLIGHT участвует в `$F548`; после
; первого попадания состояние SPENT остаётся до следующего `$4F40` pass.
; ---------------------------------------------------------------------------
RTypeCollision_UpdateShots:
                LD   IX, ArcadeShotTable
                LD   A, ARCADE_SHOT_COUNT
                LD   (RTypeCollision_ShotRemaining), A
.slot:         LD   A, (IX + ARCADE_SHOT_ACTIVE)
                CP   ARCADE_SHOT_FLIGHT
                JR   NZ, .advance
                LD   HL, (IX + ARCADE_SHOT_X)
                LD   DE, #000F
                OR   A
                SBC  HL, DE
                LD   (RTypeCollision_SourceLeft), HL
                LD   HL, (IX + ARCADE_SHOT_X)
                ADD  HL, DE
                LD   (RTypeCollision_SourceRight), HL
                LD   HL, (IX + ARCADE_SHOT_Y)
                LD   DE, 4
                OR   A
                SBC  HL, DE
                LD   (RTypeCollision_SourceLower), HL
                LD   HL, (IX + ARCADE_SHOT_Y)
                ADD  HL, DE
                LD   (RTypeCollision_SourceUpper), HL
                LD   A, 1
                CALL RTypeCollision_ScanFirstWeapon
                JR   NC, .advance
                LD   (IX + ARCADE_SHOT_ACTIVE), ARCADE_SHOT_SPENT
.advance:      LD   DE, ARCADE_SHOT_REC_SIZE
                ADD  IX, DE
                LD   HL, RTypeCollision_ShotRemaining
                DEC  (HL)
                JR   NZ, .slot
                RET

; ---------------------------------------------------------------------------
; Wave `$F703…$F717`: одна запись задевает все targets этого кадра. Каждый
; получает исходную силу, а затем сумма оставшихся HP вычитается один раз.
; ---------------------------------------------------------------------------
RTypeCollision_UpdateWave:
                LD   A, (ArcadeWaveActive)
                OR   A
                RET  Z
                LD   A, (ArcadeWaveDelay)
                OR   A
                RET  NZ
                LD   A, (ArcadeWaveShotPower)
                OR   A
                RET  Z
                LD   (RTypeCollision_Damage), A
                ; power всегда 4/8/12/16/20: `(power/4-1)*4`.
                RRCA
                RRCA
                DEC  A
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeCollision_WaveRadii
                ADD  HL, DE
                LD   A, (HL)                     ; left radius
                INC  HL
                LD   E, A
                LD   D, 0
                PUSH HL
                LD   HL, (ArcadeWaveX)
                OR   A
                SBC  HL, DE
                LD   (RTypeCollision_SourceLeft), HL
                POP  HL
                LD   A, (HL)                     ; right radius
                INC  HL
                LD   E, A
                LD   D, 0
                PUSH HL
                LD   HL, (ArcadeWaveX)
                ADD  HL, DE
                LD   (RTypeCollision_SourceRight), HL
                POP  HL
                LD   A, (HL)                     ; lower radius
                INC  HL
                LD   E, A
                LD   D, 0
                PUSH HL
                LD   HL, (ArcadeWaveY)
                OR   A
                SBC  HL, DE
                LD   (RTypeCollision_SourceLower), HL
                POP  HL
                LD   A, (HL)                     ; upper radius
                LD   E, A
                LD   D, 0
                LD   HL, (ArcadeWaveY)
                ADD  HL, DE
                LD   (RTypeCollision_SourceUpper), HL
                XOR  A
                LD   (RTypeCollision_WaveCost), A
                CALL RTypeCollision_ScanAllWeapons
                LD   A, (RTypeCollision_WaveCost)
                LD   B, A
                LD   A, (ArcadeWaveShotPower)
                SUB  B
                JR   C, .spent
                LD   (ArcadeWaveShotPower), A
                RET
.spent:        XOR  A
                LD   (ArcadeWaveActive), A
                LD   (ArcadeWaveShotPower), A
                RET

; ---------------------------------------------------------------------------
; R-9 `$2027`: native endpoints (-7,+8,-1,+6). BeginDeath сам отсекает
; штатные `$80` кадров respawn-защиты и уже идущую последовательность смерти.
; ---------------------------------------------------------------------------
RTypeCollision_UpdatePlayer:
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                ; Тот же terrain_hit, что Game.update активного Python. Код
                ; процедуры выдаёт транслятор после проверки AST-порогов.
                CALL RTypePyPlayerTerrainCollision
                JP   C, RTypePyCollisionBeginDeath
                LD   HL, (RTypePlayerNativeX)
                LD   DE, 7
                OR   A
                SBC  HL, DE
                LD   (RTypeCollision_SourceLeft), HL
                LD   HL, (RTypePlayerNativeX)
                LD   DE, 8
                ADD  HL, DE
                LD   (RTypeCollision_SourceRight), HL
                LD   HL, (RTypePlayerNativeY)
                DEC  HL
                LD   (RTypeCollision_SourceLower), HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, 6
                ADD  HL, DE
                LD   (RTypeCollision_SourceUpper), HL
                CALL RTypeCollision_ScanFirstHostile
                RET  NC
                JP   RTypePyCollisionBeginDeath

; A=тип: IY указывает на его 12-байтную предвычисленную запись.
RTypeCollision_SelectType:
                LD   L, A
                LD   H, 0
                ADD  HL, HL                      ; type*2
                LD   D, H
                LD   E, L
                ADD  HL, HL                      ; type*4
                ADD  HL, HL                      ; type*8
                ADD  HL, DE                      ; type*10
                ADD  HL, DE                      ; type*12
                LD   DE, RTypeCollisionTypeTable
                ADD  HL, DE
                PUSH HL
                POP  IY
                RET

; Текущий target уже в scratch. Отсеять динамические состояния, где Python
; выставляет shootable=False, хотя тип записи и hitbox ещё существуют.
RTypeCollision_TargetWeaponEnabled:
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JR   NZ, .dobBody
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_TERRAIN_PICKUP
                JR   NC, .disabled
                XOR  A
                RET
.dobBody:      CP   RTYPE_OBJ_DOB_BODY
                JR   NZ, .dobAnchor
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_BODY_ACTIVE
                RET
.dobAnchor:    CP   RTYPE_OBJ_DOB_ANCHOR
                JR   NZ, .a22
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_ANCHOR_ACTIVE
                RET
.a22:          CP   RTYPE_OBJ_STAGE_CONTROLLER
                JR   NZ, .b1root
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_KIND)
                CP   RTYPE_CTRL_A22E
                RET
.b1root:       CP   RTYPE_OBJ_B1D8_ROOT
                JR   NZ, .b1child
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_REMAINING)
                CP   12
                JR   NC, .disabled
                XOR  A
                RET
.b1child:      CP   RTYPE_OBJ_B1D8_CHILD
                JR   NZ, .enabled
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                RET
.enabled:      XOR  A
                RET
.disabled:     LD   A, 1
                OR   A
                RET

; Построить target endpoints. Static путь — четыре готовых signed word.
; Descriptor fallback нужен `$5EED` и Dobkeratops back с меняющимся кадром.
RTypeCollision_BuildTargetBounds:
                LD   A, (IY + 8)
                AND  RTYPE_COLLISION_FLAG_DESCRIPTOR
                JR   NZ, .descriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   E, (IY + 0)
                LD   D, (IY + 1)
                ADD  HL, DE
                LD   (RTypeCollision_TargetLeft), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   E, (IY + 2)
                LD   D, (IY + 3)
                ADD  HL, DE
                LD   (RTypeCollision_TargetRight), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   E, (IY + 4)
                LD   D, (IY + 5)
                ADD  HL, DE
                LD   (RTypeCollision_TargetLower), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   E, (IY + 6)
                LD   D, (IY + 7)
                ADD  HL, DE
                LD   (RTypeCollision_TargetUpper), HL
                RET
.descriptor:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeSprite_AnchorX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeSprite_AnchorY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                CALL RTypeSprite_ReadDescriptor
                LD   HL, (RTypeSprite_BaseX)
                LD   DE, 320
                ADD  HL, DE
                LD   (RTypeCollision_TargetLeft), HL
                LD   A, (RTypeSprite_Width)
                LD   E, A
                LD   D, 0
                SLA  E
                RL   D
                SLA  E
                RL   D
                SLA  E
                RL   D
                SLA  E
                RL   D
                ADD  HL, DE
                LD   (RTypeCollision_TargetRight), HL
                LD   HL, (RTypeSprite_AnchorPlusDy)
                LD   (RTypeCollision_TargetLower), HL
                LD   A, (RTypeSprite_Height)
                LD   E, A
                LD   D, 0
                SLA  E
                RL   D
                SLA  E
                RL   D
                SLA  E
                RL   D
                SLA  E
                RL   D
                ADD  HL, DE
                LD   (RTypeCollision_TargetUpper), HL
                RET

; `$F578` использует несимметричные half-open comparisons.
; Carry=1 — overlap, Carry=0 — разделены хотя бы по одной оси.
RTypeCollision_Overlap:
                LD   HL, (RTypeCollision_TargetRight)
                LD   DE, (RTypeCollision_SourceLeft)
                OR   A
                SBC  HL, DE
                JR   C, .no
                LD   HL, (RTypeCollision_SourceRight)
                LD   DE, (RTypeCollision_TargetLeft)
                OR   A
                SBC  HL, DE
                JR   C, .no
                LD   A, H
                OR   L
                JR   Z, .no
                LD   HL, (RTypeCollision_TargetUpper)
                LD   DE, (RTypeCollision_SourceLower)
                OR   A
                SBC  HL, DE
                JR   C, .no
                LD   HL, (RTypeCollision_SourceUpper)
                LD   DE, (RTypeCollision_TargetLower)
                OR   A
                SBC  HL, DE
                JR   C, .no
                LD   A, H
                OR   L
                JR   Z, .no
                SCF
                RET
.no:           OR   A
                RET

; A=damage. Первый weapon target в live `(priority,-serial)` порядке.
RTypeCollision_ScanFirstWeapon:
                LD   (RTypeCollision_Damage), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_SCHED_HEAD)
.next:         CP   RTYPE_SCHED_NULL
                RET  Z
                LD   (RTypeCollision_ScanIndex), A
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                OR   A
                JR   Z, .advance
                CP   80
                JR   NC, .advance
                LD   (RTypeCollision_TargetType), A
                CALL RTypeCollision_SelectType
                LD   A, (IY + 8)
                AND  RTYPE_COLLISION_FLAG_WEAPON
                JR   Z, .advance
                LD   A, (RTypeCollision_ScanIndex)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_X
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, #02B4
                OR   A
                SBC  HL, DE
                JR   C, .advance
                JR   Z, .advance
                LD   A, (RTypeCollision_ScanIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                CALL RTypeCollision_TargetWeaponEnabled
                JR   NZ, .advance
                CALL RTypeCollision_BuildTargetBounds
                CALL RTypeCollision_Overlap
                JR   NC, .advance
                LD   A, (IY + 9)
                LD   (RTypeCollision_TargetScore), A
                LD   A, (RTypeCollision_Damage)
                CALL RTypeCollision_DamageTarget
                CALL RTypeCollision_AwardIfDestroyed
                CALL RTypeCollision_CommitTarget
                SCF
                RET
.advance:      CALL RTypeCollision_NextIndex
                JR   .next

; Wave-версия того же scan не останавливается после первого target.
RTypeCollision_ScanAllWeapons:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_SCHED_HEAD)
.next:         CP   RTYPE_SCHED_NULL
                RET  Z
                LD   (RTypeCollision_ScanIndex), A
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                OR   A
                JR   Z, .advance
                CP   80
                JR   NC, .advance
                LD   (RTypeCollision_TargetType), A
                CALL RTypeCollision_SelectType
                LD   A, (IY + 8)
                AND  RTYPE_COLLISION_FLAG_WEAPON
                JR   Z, .advance
                LD   A, (RTypeCollision_ScanIndex)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_X
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, #02B4
                OR   A
                SBC  HL, DE
                JR   C, .advance
                JR   Z, .advance
                LD   A, (RTypeCollision_ScanIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                CALL RTypeCollision_TargetWeaponEnabled
                JR   NZ, .advance
                CALL RTypeCollision_BuildTargetBounds
                CALL RTypeCollision_Overlap
                JR   NC, .advance
                LD   A, (IY + 9)
                LD   (RTypeCollision_TargetScore), A
                CALL RTypeCollision_TargetCost
                LD   HL, RTypeCollision_WaveCost
                ADD  A, (HL)
                LD   (HL), A
                LD   A, (RTypeCollision_Damage)
                CALL RTypeCollision_DamageTarget
                CALL RTypeCollision_AwardIfDestroyed
                CALL RTypeCollision_CommitTarget
.advance:      CALL RTypeCollision_NextIndex
                JR   .next

; Первый hostile target для player. Палитра `$FF` означает невидимую и
; collision-disabled запись. Pickup terrain-bound обрабатывается отдельно.
RTypeCollision_ScanFirstHostile:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_SCHED_HEAD)
.next:         CP   RTYPE_SCHED_NULL
                RET  Z
                LD   (RTypeCollision_ScanIndex), A
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                OR   A
                JR   Z, .advance
                CP   80
                JR   NC, .advance
                LD   (RTypeCollision_TargetType), A
                CALL RTypeCollision_SelectType
                LD   A, (IY + 8)
                AND  RTYPE_COLLISION_FLAG_HOSTILE
                JR   Z, .advance
                LD   A, (RTypeCollision_ScanIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CP   #FF
                JR   Z, .advance
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JR   NZ, .bounds
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_TERRAIN_PICKUP
                JR   NC, .advance                ; pickup не ранит R-9
.bounds:       CALL RTypeCollision_BuildTargetBounds
                CALL RTypeCollision_Overlap
                JR   NC, .advance
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_MULTIPART_915B_CHILD
                CALL Z, RTypeObjectBank3_ContactMultipart915BChild
                SCF
                RET
.advance:      CALL RTypeCollision_NextIndex
                JR   .next

; Вернуть A=NEXT текущего scheduler index. Page3 мог быть ROM/ring после
; descriptor/damage handler, поэтому object page назначается явно.
RTypeCollision_NextIndex:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeCollision_ScanIndex)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (HL)
                RET

; Сохранить изменённый scratch или физически вернуть уничтоженный slot FIFO.
RTypeCollision_CommitTarget:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                OR   A
                JR   Z, .release
                LD   A, (RTypeCollision_ScanIndex)
                JP   RTypeObjects_StoreScratch
.release:      LD   A, (RTypeCollision_ScanIndex)
                JP   RTypeObjects_Release

; Damage-handler сменил type записи на explosion/0 — начислить его исходный
; `$E8BD` increment ровно один раз. Нефатальный flash оставляет прежний type.
RTypeCollision_AwardIfDestroyed:
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JR   NZ, .compareType
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_TERRAIN_PICKUP
                JR   NZ, .compareType
                LD   A, (RTypeCollision_TargetScore)
                OR   A
                RET  Z
                JP   RTypeCollision_AwardScore
.compareType:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                LD   B, A
                LD   A, (RTypeCollision_TargetType)
                CP   B
                RET  Z
                LD   A, (RTypeCollision_TargetScore)
                OR   A
                RET  Z

; A=индекс 1…15. Четыре DAA повторяют NEC `ADD4S` над little-endian BCD.
RTypeCollision_AwardScore:
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTypeCollisionScoreIncrements
                ADD  HL, DE
                LD   DE, ArcadeScore
                LD   B, 4
                OR   A                           ; первый младший byte без carry
.addByte:      LD   A, (DE)
                ADC  A, (HL)
                DAA
                LD   (DE), A
                INC  DE
                INC  HL
                DJNZ .addByte                    ; DJNZ сохраняет decimal carry
                LD   A, (ArcadeScore + 3)
                AND  #F0
                JR   Z, .bonus
                LD   A, #99                      ; ROM saturate 9,999,999
                LD   (ArcadeScore), A
                LD   (ArcadeScore + 1), A
                LD   (ArcadeScore + 2), A
                LD   A, #09
                LD   (ArcadeScore + 3), A
.bonus:
                ; Пользовательские пороги уже поделены на два: 25k, 75k,
                ; 125k, 200k, 300k. Индекс двигается даже при cap=8 жизней.
                LD   A, (ArcadeBonusIndex)
                CP   5
                RET  NC
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTypeCollisionBonusThresholds
                ADD  HL, DE
                PUSH HL
                LD   DE, 3
                ADD  HL, DE
                LD   DE, ArcadeScore + 3
                LD   B, 4
.compare:      LD   A, (DE)
                CP   (HL)
                JR   C, .below
                JR   NZ, .reached
                DEC  DE
                DEC  HL
                DJNZ .compare
.reached:      POP  HL
                LD   A, (ArcadeBonusIndex)
                INC  A
                LD   (ArcadeBonusIndex), A
                CALL ArcadeLives_Award
                JR   .bonus
.below:        POP  HL
                RET

; Остаток HP перед Wave-hit. Для однокадровых автоматов literal 1; для
; перенесённых multi-hit записей читается их реальный live field.
RTypeCollision_TargetCost:
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_TARGETING_80E3
                JR   Z, .targetWord
                CP   RTYPE_OBJ_HANDLER_60BA
                JR   Z, .handler60Word
                CP   RTYPE_OBJ_ENEMY_6F89
                JR   Z, .enemy6FWord
                CP   RTYPE_OBJ_ENEMY_7D68
                JR   Z, .enemy7DWord
                CP   RTYPE_OBJ_CHILD_8D85
                JR   Z, .enemy8DWord
                CP   RTYPE_OBJ_TERRAIN_ENEMY_696E
                JR   Z, .enemy69Word
                CP   RTYPE_OBJ_ENEMY_5EED
                JR   Z, .enemy5EWord
                CP   RTYPE_OBJ_ENEMY_7294
                JR   Z, .enemy72Word
                CP   RTYPE_OBJ_A71D_BODY
                JR   Z, .a71Word
                CP   RTYPE_OBJ_B7FB_MISSILE
                JR   Z, .b7MissileWord
                CP   RTYPE_OBJ_B7FB_CORE
                JR   Z, .b7CoreWord
                CP   RTYPE_OBJ_DOB_BODY
                JR   Z, .dobWord
                CP   RTYPE_OBJ_LARGE_TERRAIN
                JR   Z, .largeByte
                CP   RTYPE_OBJ_TERRAIN_MOD_CHILD
                JR   Z, .modByte
                CP   RTYPE_OBJ_ENEMY_8561
                JR   Z, .enemy85Byte
                CP   RTYPE_OBJ_FIXED_LARGE_6E9B
                JR   Z, .fixedByte
                CP   RTYPE_OBJ_FORMATION_78_CHILD
                JR   Z, .formation78Byte
                CP   RTYPE_OBJ_B7FB_RANDOM_CHILD
                JR   Z, .b7ChildByte
                LD   A, 1
                RET
.targetWord:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_HP)
                JR   .word
.handler60Word:LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_HP)
                JR   .word
.enemy6FWord: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_HP)
                JR   .word
.enemy7DWord: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_HP)
                JR   .word
.enemy8DWord: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_HP)
                JR   .word
.enemy69Word: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_HP)
                JR   .word
.enemy5EWord: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_HP)
                JR   .word
.enemy72Word: LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_HP)
                JR   .word
.a71Word:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_HP)
                JR   .word
.b7MissileWord:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_MISSILE_HP)
                JR   .word
.b7CoreWord:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_HP)
                JR   .word
.dobWord:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP)
.word:        LD   A, H
                OR   A
                LD   A, #FF
                RET  NZ
                LD   A, L
                RET
.largeByte:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_HP)
                RET
.modByte:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_HP)
                RET
.enemy85Byte: LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_HP)
                RET
.fixedByte:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6E_HP)
                RET
.formation78Byte:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_HP)
                RET
.b7ChildByte: LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CHILD_HP)
                RET

; A=damage. Сложные handlers выполняются в родном code bank; простые
; одноударные автоматы переводятся в общий `$E7BE` без отдельного state machine.
RTypeCollision_DamageTarget:
                LD   (RTypeCollision_Damage), A
                LD   A, (RTypeCollision_TargetType)
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JP   Z, RTypeCollision_DamageTerrainCarrier
                CP   RTYPE_OBJ_ENEMY_7D68
                JP   Z, RTypeCollision_DamageBank3_7D
                CP   RTYPE_OBJ_CHILD_8D85
                JP   Z, RTypeCollision_DamageBank3_8D
                CP   RTYPE_OBJ_TERRAIN_ENEMY_696E
                JP   Z, RTypeCollision_DamageBank3_69
                CP   RTYPE_OBJ_ENEMY_8F5E
                JP   Z, RTypeCollision_DamageBank3_8F
                CP   RTYPE_OBJ_ENEMY_8469
                JP   Z, RTypeCollision_DamageBank3_84
                CP   RTYPE_OBJ_ENEMY_8561
                JP   Z, RTypeCollision_DamageBank3_85
                CP   RTYPE_OBJ_ENEMY_5CEA
                JP   Z, RTypeCollision_DamageBank3_5C
                CP   RTYPE_OBJ_ENEMY_5EED
                JP   Z, RTypeCollision_DamageBank3_5E
                CP   RTYPE_OBJ_ENEMY_7182
                JP   Z, RTypeCollision_DamageBank3_71
                CP   RTYPE_OBJ_ENEMY_7294
                JP   Z, RTypeCollision_DamageBank3_72
                CP   RTYPE_OBJ_PROJECTILE_7435
                JP   Z, RTypeCollision_DamageBank3_74
                CP   RTYPE_OBJ_FIXED_LARGE_6E9B
                JP   Z, RTypeCollision_DamageBank3_6E
                CP   RTYPE_OBJ_FORMATION_78_CHILD
                JP   Z, RTypeCollision_DamageBank3_78
                CP   RTYPE_OBJ_FINAL_PROJECTILE_96E9
                JP   Z, RTypeCollision_DamageBank3_96
                CP   RTYPE_OBJ_A71D_BODY
                JP   Z, RTypeCollision_DamageBank3_A7
                CP   RTYPE_OBJ_B7FB_SEGMENT
                JP   Z, RTypeCollision_DamageBank4_Segment
                CP   RTYPE_OBJ_B7FB_RANDOM_CHILD
                JP   Z, RTypeCollision_DamageBank4_Random
                CP   RTYPE_OBJ_B7FB_MISSILE
                JP   Z, RTypeCollision_DamageBank4_Missile
                CP   RTYPE_OBJ_B7FB_CORE
                JP   Z, RTypeCollision_DamageBank4_Core
                CP   RTYPE_OBJ_TARGETING_80E3
                JP   Z, RTypeCollision_DamageTargeting
                CP   RTYPE_OBJ_LARGE_TERRAIN
                JP   Z, RTypeCollision_DamageLarge
                CP   RTYPE_OBJ_HANDLER_60BA
                JP   Z, RTypeCollision_DamageHandler60
                CP   RTYPE_OBJ_ENEMY_6F89
                JP   Z, RTypeCollision_DamageEnemy6F
                CP   RTYPE_OBJ_DOB_BODY
                JP   Z, RTypeCollision_DamageDobBody
                CP   RTYPE_OBJ_DOB_ANCHOR
                JP   Z, RTypeCollision_DamageDobAnchor
                CP   RTYPE_OBJ_DOB_TENTACLE
                RET  Z                            ; `$A035`: hit потреблён, HP неизменен
                CP   RTYPE_OBJ_STAGE_CONTROLLER
                JP   Z, RTypeCollision_DamageController
                CP   RTYPE_OBJ_B1D8_ROOT
                JP   Z, RTypeCollision_DamageB1Root
                CP   RTYPE_OBJ_B1D8_CHILD
                JP   Z, RTypeCollision_DamageB1Child
                CP   RTYPE_OBJ_TERRAIN_MOD_CHILD
                JP   Z, RTypeCollision_DamageModChild
                CP   RTYPE_OBJ_C0_FINAL_SPRITE
                RET  Z
                ; Все оставшиеся WEAPON-типы Python имеют hp=1.
                JP   RTypeCollision_GenericDeathE7BE

; `$5811` не заменяет carrier общим взрывом: bank #0A сохраняет эту запись как
; pickup и отдельно создаёт `$E7BE`. Damage всегда фатален, поскольку HP=1.
RTypeCollision_DamageTerrainCarrier:
                LD   B, RTYPE_OBJECT_BANK1_PAGE
                LD   HL, RTypeBank1_ConvertTerrainToPickup
                XOR  A
                JP   RTypeCollision_CallBank

RTypeCollision_DamageBank3_7D:
                LD   HL, RTypeBank3_DamageEnemy7D68
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_8D:
                LD   HL, RTypeBank3_DamageChild8D85
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_69:
                LD   HL, RTypeBank3_DamageTerrainEnemy696E
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_8F:
                LD   HL, RTypeBank3_DamageEnemy8F5E
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_84:
                LD   HL, RTypeBank3_DamageEnemy8469
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_85:
                LD   HL, RTypeBank3_DamageEnemy8561
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_5C:
                LD   HL, RTypeBank3_DamageEnemy5CEA
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_5E:
                LD   HL, RTypeBank3_DamageEnemy5EED
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_71:
                LD   HL, RTypeBank3_DamageEnemy7182
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_72:
                LD   HL, RTypeBank3_DamageEnemy7294
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_74:
                LD   HL, RTypeBank3_DamageProjectile7435
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_6E:
                LD   HL, RTypeBank3_DamageFixedLarge6E9B
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_78:
                LD   HL, RTypeBank3_DamageFormation78Child
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_96:
                LD   HL, RTypeBank3_DamageFinalProjectile96E9
                JR   RTypeCollision_CallBank3Damage
RTypeCollision_DamageBank3_A7:
                LD   HL, RTypeBank3_DamageMultipartA71DBody
RTypeCollision_CallBank3Damage:
                LD   B, RTYPE_OBJECT_BANK3_PAGE
                LD   A, (RTypeCollision_Damage)
                JP   RTypeCollision_CallBank

RTypeCollision_DamageBank4_Segment:
                LD   HL, RTypeBank4_DamageBossB7FBSegment
                JR   RTypeCollision_CallBank4Damage
RTypeCollision_DamageBank4_Random:
                LD   HL, RTypeBank4_DamageBossB7FBRandomChild
                JR   RTypeCollision_CallBank4Damage
RTypeCollision_DamageBank4_Missile:
                LD   HL, RTypeBank4_DamageBossB7FBMissile
                JR   RTypeCollision_CallBank4Damage
RTypeCollision_DamageBank4_Core:
                LD   HL, RTypeBank4_DamageBossB7FBCore
RTypeCollision_CallBank4Damage:
                LD   B, RTYPE_OBJECT_BANK4_PAGE
                LD   A, (RTypeCollision_Damage)
                JP   RTypeCollision_CallBank

; Простые multi-hit roots, которые раньше вообще не имели target collision.
RTypeCollision_DamageTargeting:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TARGET_HP
                LD   B, #10
                LD   C, RTYPE_OBJ_FLASH_TIMER
                JR   RTypeCollision_DamageWordE817
RTypeCollision_DamageHandler60:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_HP
                LD   B, #0C
                LD   C, RTYPE_OBJ_60_FLASH_TIMER
RTypeCollision_DamageWordE817:
                LD   A, (RTypeCollision_Damage)
                LD   E, A
                LD   D, 0
                LD   A, (HL)
                SUB  E
                LD   (HL), A
                INC  HL
                LD   A, (HL)
                SBC  A, D
                LD   (HL), A
                JR   C, .dead
                DEC  HL
                OR   (HL)
                JR   Z, .dead
                LD   A, C
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_OBJECT_SCRATCH
                ADD  HL, DE
                LD   (HL), B
                RET
.dead:         JP   RTypeCollision_GenericDeathE817

RTypeCollision_DamageLarge:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_HP
                LD   B, #0C
                LD   C, RTYPE_OBJ_LARGE_FLASH_TIMER
                JR   RTypeCollision_DamageByteE7BE
RTypeCollision_DamageModChild:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOD_HP
                LD   B, 0
                LD   C, 0
RTypeCollision_DamageByteE7BE:
                LD   A, (RTypeCollision_Damage)
                LD   E, A
                LD   A, (HL)
                SUB  E
                LD   (HL), A
                JR   C, .dead
                JR   Z, .dead
                LD   A, C
                OR   A
                RET  Z
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_OBJECT_SCRATCH
                ADD  HL, DE
                LD   (HL), B
                RET
.dead:         JP   RTypeCollision_GenericDeathE7BE

RTypeCollision_DamageEnemy6F:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_HP
                LD   B, #10
                LD   C, RTYPE_OBJ_6F_FLASH_TIMER
                JR   RTypeCollision_DamageWordE7BE
RTypeCollision_DamageWordE7BE:
                LD   A, (RTypeCollision_Damage)
                LD   E, A
                LD   D, 0
                LD   A, (HL)
                SUB  E
                LD   (HL), A
                INC  HL
                LD   A, (HL)
                SBC  A, D
                LD   (HL), A
                JR   C, .dead
                DEC  HL
                OR   (HL)
                JR   Z, .dead
                LD   A, C
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_OBJECT_SCRATCH
                ADD  HL, DE
                LD   (HL), B
                RET
.dead:         JP   RTypeCollision_GenericDeathE7BE

RTypeCollision_DamageDobBody:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_HP
                LD   A, (RTypeCollision_Damage)
                LD   E, A
                LD   D, 0
                LD   A, (HL)
                SUB  E
                LD   (HL), A
                INC  HL
                LD   A, (HL)
                SBC  A, D
                LD   (HL), A
                JR   C, .death
                DEC  HL
                OR   (HL)
                JR   Z, .death
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_TIMER), A
                RET
.death:        LD   B, RTYPE_OBJECT_BANK2_PAGE
                LD   HL, RTypeBank2_DobBodyBeginDeath
                XOR  A
                JP   RTypeCollision_CallBank

RTypeCollision_DamageDobAnchor:
                LD   B, RTYPE_OBJECT_BANK2_PAGE
                LD   HL, RTypeBank2_DobAnchorBeginErase
                XOR  A
                JP   RTypeCollision_CallBank

; Controllers хранят accumulated damage отдельно: их собственный следующий
; update сравнивает threshold и выполняет точный exit/cleanup state machine.
RTypeCollision_DamageController:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CTRL_DAMAGE
                JR   RTypeCollision_AddDamageByte
RTypeCollision_DamageB1Root:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_DAMAGE
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
                JR   RTypeCollision_AddDamageByte
RTypeCollision_DamageB1Child:
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_CHILD_DAMAGE
                LD   A, #10
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_TIMER), A
RTypeCollision_AddDamageByte:
                LD   A, (RTypeCollision_Damage)
                ADD  A, (HL)
                JR   NC, .store
                LD   A, #FF
.store:        LD   (HL), A
                RET

RTypeCollision_GenericDeathE817:
                CALL RTypeCollision_CleanupCurrent
                LD   B, RTYPE_OBJECT_BANK3_PAGE
                LD   HL, RTypeBank3_ConvertCurrentToE817
                XOR  A
                JP   RTypeCollision_CallBank

RTypeCollision_GenericDeathE7BE:
                CALL RTypeCollision_CleanupCurrent
                LD   B, RTYPE_OBJECT_BANK3_PAGE
                LD   HL, RTypeBank3_ConvertCurrentToE7BE
                XOR  A
                JP   RTypeCollision_CallBank

; Cleanup расположен во второй половине Core (#8000…#BFFF). Пока здесь
; отображена page #E5, прямой CALL #8B33 исполнил бы данные collision-банка
; как код и разрушил адрес возврата. Тот же межбанковый шлюз временно ставит
; page #06, выполняет штатный `$F461` и возвращает отображение page #E5.
RTypeCollision_CleanupCurrent:
                LD   B, CorePage + 1
                LD   HL, RTypeObjects_CleanupCurrent
                XOR  A
                JP   RTypeCollision_CallBank

; Нативные радиусы Wave tiers 4/8/12/16/20: left,right,lower,upper.
RTypeCollision_WaveRadii:
                DEFB 2, 16, 8, 8
                DEFB 12, 22, 8, 8
                DEFB 12, 28, 8, 8
                DEFB 12, 20, 8, 8
                DEFB 12, 30, 8, 8

; Прямые packed-BCD thresholds, не `threshold-1`: сравнение здесь `>=`.
RTypeCollisionBonusThresholds:
                DEFB #00, #50, #02, #00          ; 25 000
                DEFB #00, #50, #07, #00          ; 75 000
                DEFB #00, #50, #12, #00          ; 125 000
                DEFB #00, #00, #20, #00          ; 200 000
                DEFB #00, #00, #30, #00          ; 300 000

RTypeCollision_SourceLeft:    DEFW 0
RTypeCollision_SourceRight:   DEFW 0
RTypeCollision_SourceLower:   DEFW 0
RTypeCollision_SourceUpper:   DEFW 0
RTypeCollision_TargetLeft:    DEFW 0
RTypeCollision_TargetRight:   DEFW 0
RTypeCollision_TargetLower:   DEFW 0
RTypeCollision_TargetUpper:   DEFW 0
RTypeCollision_ScanIndex:     DEFB RTYPE_SCHED_NULL
RTypeCollision_TargetType:    DEFB 0
RTypeCollision_TargetScore:   DEFB 0
RTypeCollision_Damage:        DEFB 0
RTypeCollision_WaveCost:      DEFB 0
RTypeCollision_ShotRemaining: DEFB 0

                include "generated_collision_tables.inc"
