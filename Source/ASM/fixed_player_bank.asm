; ============================================================================
; Банк #E6: постоянные записи Force и двух Bits из `$0060/$0120/$0140`.
;
; Код исполняется в slot2, но всё живое состояние находится в резидентном
; диапазоне #4386…#4487. Таблицы ниже предсохранены из World ROM на ПК.
; Никакой float-математики и построения траекторий во время кадра здесь нет.
; ============================================================================

RTYPE_BIT_ACTIVE        EQU 0
RTYPE_BIT_X_Q8          EQU 1
RTYPE_BIT_Y_Q8          EQU 4
RTYPE_BIT_PALETTE       EQU 7
RTYPE_BIT_ANIMATION     EQU 8
RTYPE_BIT_STRENGTH      EQU 9
RTYPE_BIT_IDLE_COUNTER  EQU 10
RTYPE_BIT_WRITE_CURSOR  EQU 11
RTYPE_BIT_READ_CURSOR   EQU 12
RTYPE_BIT_DESCRIPTOR    EQU 13
RTYPE_BIT_HISTORY_X     EQU 15
RTYPE_BIT_HISTORY_Y     EQU 47
RTYPE_BIT_RECORD_SIZE   EQU 80

; Сбросить fixed-player и заполнить шестнадцать history-пар тем же начальным
; `(native X=$01B0,Y=$0100)`, который использует Python reset после заставки.
RTypeFixedPlayerBank_Init:
                XOR  A
                LD   HL, RTypeFixedStateBase
                LD   DE, RTypeFixedStateBase + 1
                LD   BC, RTypeFixedStateEnd - RTypeFixedStateBase - 1
                LD   (HL), A
                LDIR
                LD   A, #FF
                LD   (ArcadeForcePalette), A
                LD   HL, #0080
                LD   (ArcadeForceXQ8 + 1), HL
                LD   (ArcadeForceOldXQ8 + 1), HL
                LD   HL, #0020
                LD   (ArcadeForceYQ8 + 1), HL
                LD   HL, #26FE
                LD   (ArcadeForceDescriptor), HL
                LD   HL, ArcadePlayerNativeHistory
                LD   B, 16
.history:      LD   (HL), #B0
                INC  HL
                LD   (HL), #01
                INC  HL
                LD   (HL), 0
                INC  HL
                LD   (HL), #01
                INC  HL
                DJNZ .history
                RET

; Один fixed-player pass: pending pickup, history, Force, затем оба Bit.
RTypeFixedPlayerBank_Update:
                CALL RTypeFixedPlayer_Direction
                CALL RTypeFixedPlayer_ShiftHistory
                CALL RTypeFixedPlayer_ConsumePickup
                CALL RTypeForce_SyncLevel
                JR   C, .bits                         ; level-handler завершает pass
                CALL RTypeForce_UpdateState
.bits:         CALL RTypeBits_Update
                XOR  A
                LD   (ArcadeForceDetached), A
                LD   A, (ArcadeForceState)
                CP   RTYPE_FORCE_DETACHED
                RET  NZ
                LD   A, 1
                LD   (ArcadeForceDetached), A
                RET

; Переложить аппаратные биты управления в `$2F21&$0F`: R,L,D,U.
RTypeFixedPlayer_Direction:
                LD   A, (InputState)
                LD   B, A
                XOR  A
                BIT  1, B
                JR   Z, .left
                OR   1
.left:         BIT  0, B
                JR   Z, .down
                OR   2
.down:         BIT  3, B
                JR   Z, .up
                OR   4
.up:           BIT  2, B
                JR   Z, .done
                OR   8
.done:         LD   (ArcadeForceDirection), A
                RET

; Python `append/del[0]`: после сдвига первая пара отстаёт ровно на 15 кадров.
RTypeFixedPlayer_ShiftHistory:
                LD   HL, ArcadePlayerNativeHistory + 4
                LD   DE, ArcadePlayerNativeHistory
                LD   BC, 15 * 4
                LDIR
                LD   HL, (RTypePlayerNativeX)
                LD   (ArcadePlayerNativeHistory + 15 * 4), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (ArcadePlayerNativeHistory + 15 * 4 + 2), HL
                RET

; `$216D…$2182` предшествует записи Force: один pending byte даёт один level.
RTypeFixedPlayer_ConsumePickup:
                LD   A, (ArcadeWeaponPickupPending)
                OR   A
                RET  Z
                DEC  A
                LD   (ArcadeWeaponPickupPending), A
                LD   A, (ArcadeForceRequestedLevel)
                CP   3
                RET  NC
                INC  A
                LD   (ArcadeForceRequestedLevel), A
                RET

; Выполнить один из `$2682/$26AD/$26D0/$26E9` только при смене уровня.
; Carry=1 сообщает вызывающему, что обычный state-handler в этот pass запрещён.
RTypeForce_SyncLevel:
                LD   A, (ArcadeForceRequestedLevel)
                CP   4
                JR   C, .clamped
                LD   A, 3
                LD   (ArcadeForceRequestedLevel), A
.clamped:      LD   B, A
                LD   A, (ArcadeForceLevel)
                CP   B
                JR   NZ, .changed
                OR   A
                RET
.changed:      LD   (RTypeForce_WasHidden), A
                LD   A, (ArcadeForcePalette)
                CALL RTypeResources_Release
                LD   A, B
                OR   A
                JR   NZ, .visible
                XOR  A
                LD   (ArcadeForceLevel), A
                LD   (ArcadeForceState), A
                LD   (ArcadeForceAnimation), A
                LD   (ArcadeForceBehind), A
                LD   (ArcadeForceReturnHistory), A
                LD   (ArcadeForceAttached), A
                LD   A, #FF
                LD   (ArcadeForcePalette), A
                SCF
                RET
.visible:      LD   (ArcadeForceLevel), A
                PUSH AF
                LD   A, #56
                CALL RTypeResources_Acquire
                LD   (ArcadeForcePalette), A
                XOR  A
                LD   (ArcadeForceAnimation), A
                POP  AF
                CP   1
                JR   Z, .startReturn
                LD   A, (RTypeForce_WasHidden)
                OR   A
                JR   NZ, .done
.startReturn:  XOR  A
                LD   (ArcadeForceYQ8), A
                LD   HL, #0100
                LD   (ArcadeForceYQ8 + 1), HL
                LD   HL, 1
                LD   (ArcadeForceLastVertical), HL
                LD   A, RTYPE_FORCE_RETURN
                LD   (ArcadeForceState), A
                XOR  A
                LD   (ArcadeForceAttached), A
.done:         SCF
                RET

RTypeForce_UpdateState:
                LD   A, (ArcadeForceLevel)
                OR   A
                RET  Z
                LD   A, (ArcadeForcePalette)
                CP   #FF
                RET  Z
                LD   A, (ArcadeForceState)
                CP   RTYPE_FORCE_ATTACHED
                JP   Z, RTypeForce_UpdateAttached
                CP   RTYPE_FORCE_DETACHED
                JP   Z, RTypeForce_UpdateDetached
                JP   RTypeForce_UpdateReturn

; `$24D8…$2564`: возврат, terrain avoidance и захват переднего/заднего порта.
RTypeForce_UpdateReturn:
                LD   HL, ArcadeForceXQ8
                LD   DE, ArcadeForceOldXQ8
                LD   BC, 3
                LDIR
                LD   HL, (ArcadeForceVelocityY)
                LD   A, H
                OR   L
                JR   Z, .edge
                LD   (ArcadeForceLastVertical), HL
.edge:         LD   A, (ArcadeForceActionEdge)
                OR   A
                JR   Z, .target
                LD   (ArcadeForceReturnHistory), A
.target:       LD   HL, (ArcadePlayerNativeHistory)
                LD   (RTypeForce_DelayedX), HL
                LD   HL, (ArcadePlayerNativeHistory + 2)
                LD   (RTypeForce_DelayedY), HL
                LD   A, (ArcadeForceReturnHistory)
                OR   A
                JR   Z, .sideTarget
                LD   HL, (RTypeForce_DelayedX)
                JR   .targetReady
.sideTarget:   LD   HL, (RTypePlayerNativeX)
                LD   DE, #01F8
                OR   A
                SBC  HL, DE
                LD   HL, #01A0
                JR   NC, .targetReady
                LD   HL, #0238
.targetReady:  LD   (RTypeForce_TargetX), HL
                CALL RTypeForce_HorizontalReturn
                CALL RTypeForce_VerticalReturn
                CALL RTypeForce_ClearBlocks
                CALL RTypeForce_ReturnDescriptor
                CALL RTypeForce_TestAttach
                RET

RTypeForce_UpdateAttached:
                LD   HL, (RTypePlayerNativeX)
                LD   A, (ArcadeForceBehind)
                OR   A
                LD   DE, #0018
                JR   Z, .xReady
                LD   DE, -#0018
.xReady:       ADD  HL, DE
                XOR  A
                LD   (ArcadeForceXQ8), A
                LD   (ArcadeForceXQ8 + 1), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (ArcadeForceYQ8), A
                LD   (ArcadeForceYQ8 + 1), HL
                CALL RTypeForce_AttachedDescriptor
                LD   A, (ArcadeForceActionEdge)
                OR   A
                RET  Z
                LD   HL, #0900
                LD   A, (ArcadeForceBehind)
                OR   A
                JR   Z, .velocity
                LD   HL, -#0900
.velocity:     LD   (ArcadeForceVelocityX), HL
                XOR  A
                LD   (ArcadeForceReturnHistory), A
                LD   (ArcadeForceAttached), A
                LD   A, RTYPE_FORCE_DETACHED
                LD   (ArcadeForceState), A
                LD   A, #36
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                RET

RTypeForce_UpdateDetached:
                LD   HL, ArcadeForceXQ8
                LD   DE, (ArcadeForceVelocityX)
                CALL RTypeFixed_AddQ8
                CALL RTypeForce_ClearBlocks
                ; Второе интегрирование `$2632` служит только probe и не
                ; записывается обратно. У detached velocity дробь всегда ноль.
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, (ArcadeForceVelocityX)
                LD   E, D
                LD   D, 0
                BIT  7, E
                JR   Z, .probeSignReady
                LD   D, #FF
.probeSignReady:
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (ArcadeForceYQ8 + 1)
                CALL RTypeFixed_CollisionCodes
                LD   HL, (RTypeFixed_ForegroundCode)
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .return
                LD   HL, (RTypeFixed_BackgroundCode)
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .return
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, #0150
                OR   A
                SBC  HL, DE
                JR   C, .return
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, #02A0
                OR   A
                SBC  HL, DE
                JR   C, .descriptor
.return:       LD   A, RTYPE_FORCE_RETURN
                LD   (ArcadeForceState), A
.descriptor:   JP   RTypeForce_DetachedDescriptor

RTypeForce_HorizontalReturn:
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, #0120
                OR   A
                SBC  HL, DE
                JR   NC, .probe
                XOR  A
                LD   (ArcadeForceXQ8), A
                LD   (ArcadeForceYQ8), A
                LD   HL, #0128
                LD   (ArcadeForceXQ8 + 1), HL
                LD   HL, #0100
                LD   (ArcadeForceYQ8 + 1), HL
.probe:        LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, 8
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   DE, (ArcadeForceYQ8 + 1)
                CALL RTypeFixed_CollisionCodes
                LD   HL, (RTypeFixed_ForegroundCode)
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .scroll
                LD   HL, (RTypeFixed_BackgroundCode)
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .scroll
                LD   HL, (RTypeForce_TargetX)
                LD   DE, (ArcadeForceXQ8 + 1)
                OR   A
                SBC  HL, DE                       ; signed target-current
                LD   A, H
                OR   L
                RET  Z
                BIT  7, H
                JR   Z, .positive
                LD   DE, -2
                OR   A
                SBC  HL, DE
                RET  NC                           ; -2…-1
                LD   HL, ArcadeForceXQ8
                LD   DE, -#0140
                JP   RTypeFixed_AddQ8
.positive:     LD   DE, 2
                OR   A
                SBC  HL, DE
                RET  C                            ; 0…1
                LD   HL, ArcadeForceXQ8
                LD   DE, #0180
                JP   RTypeFixed_AddQ8
.scroll:       LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (ArcadeForceXQ8 + 1), HL
                RET

; Буквальная адресная ветвь `$2AB4…$2C29`: девять probes, затем длины
; вертикальных solid-run в живых foreground/background ring-картах.
RTypeForce_VerticalReturn:
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, -8
                ADD  HL, DE
                LD   (RTypeForce_ProbeX), HL
                LD   A, 9
                LD   (RTypeForce_ProbeCount), A
.probeLoop:    LD   BC, (RTypeForce_ProbeX)
                LD   DE, (ArcadeForceYQ8 + 1)
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeForce_FgAddress), HL
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE                       ; сравнение ниже повторим по коду
                ; Адрес был в HL до сравнения, поэтому сам code читаем ещё раз
                ; готовым helper-ом из сохранённого ring address.
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                LD   HL, (RTypeForce_FgAddress)
                CALL RTypeFixed_ReadMapCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .foundForeground

                LD   BC, (RTypeForce_ProbeX)
                LD   DE, (ArcadeForceYQ8 + 1)
                CALL RTypeTerrain_BackgroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeForce_BgAddress), HL
                LD   A, RTYPE_WORLD_BG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                CALL RTypeFixed_ReadMapCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .foundBackground

                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                LD   HL, (RTypeForce_FgAddress)
                LD   DE, #0100
                ADD  HL, DE
                CALL RTypeFixed_ReadMapCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .foundForeground
                LD   HL, (RTypeForce_FgAddress)
                LD   DE, -#0100
                ADD  HL, DE
                CALL RTypeFixed_ReadMapCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .foundForeground
                LD   HL, (RTypeForce_ProbeX)
                LD   DE, 8
                ADD  HL, DE
                LD   (RTypeForce_ProbeX), HL
                LD   HL, RTypeForce_ProbeCount
                DEC  (HL)
                JP   NZ, .probeLoop
                JP   RTypeForce_VerticalFollower

.foundForeground:
                XOR  A
                LD   (RTypeForce_CollisionLayer), A
                LD   HL, (RTypeForce_FgAddress)
                LD   (RTypeForce_CollisionAddress), HL
                JR   RTypeForce_ForegroundAvoidance
.foundBackground:
                LD   A, 1
                LD   (RTypeForce_CollisionLayer), A
                LD   HL, (RTypeForce_BgAddress)
                LD   (RTypeForce_CollisionAddress), HL
                JP   RTypeForce_BackgroundAvoidance

RTypeForce_ForegroundAvoidance:
                XOR  A
                LD   (RTypeForce_LowCount), A
                LD   (RTypeForce_HighCount), A
                LD   (RTypeForce_Edge), A
                LD   HL, (RTypeForce_CollisionAddress)
                LD   (RTypeForce_ScanCursor), HL
.low:          LD   HL, (RTypeForce_ScanCursor)
                LD   DE, -#0100
                ADD  HL, DE
                LD   (RTypeForce_ScanCursor), HL
                LD   DE, #1000
                OR   A
                SBC  HL, DE
                JR   C, .lowEdge
                LD   HL, RTypeForce_LowCount
                INC  (HL)
                LD   HL, (RTypeForce_ScanCursor)
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                CALL RTypeFixed_ReadMapCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .low
                JR   .highStart
.lowEdge:      LD   A, 1
                LD   (RTypeForce_Edge), A
.highStart:    LD   HL, (RTypeForce_CollisionAddress)
                LD   (RTypeForce_ScanCursor), HL
.high:         LD   HL, (RTypeForce_ScanCursor)
                LD   DE, #0100
                ADD  HL, DE
                LD   (RTypeForce_ScanCursor), HL
                LD   DE, #2E00
                OR   A
                SBC  HL, DE
                JR   NC, .highEdge
                LD   HL, RTypeForce_HighCount
                INC  (HL)
                LD   HL, (RTypeForce_ScanCursor)
                CALL RTypeFixed_ReadMapCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .high
                JR   .select
.highEdge:     LD   A, (RTypeForce_Edge)
                OR   #10
                LD   (RTypeForce_Edge), A
.select:       LD   A, (RTypeForce_Edge)
                CP   #11
                JP   Z, RTypeForce_VerticalFollower
                OR   A
                JR   Z, RTypeForce_SelectCounts
                BIT  0, A
                LD   HL, #0200
                JR   Z, RTypeForce_ApplyAvoidance
                LD   HL, -#0200
                JR   RTypeForce_ApplyAvoidance

RTypeForce_BackgroundAvoidance:
                XOR  A
                LD   (RTypeForce_LowCount), A
                LD   (RTypeForce_HighCount), A
                LD   HL, (RTypeForce_CollisionAddress)
                LD   (RTypeForce_ScanCursor), HL
                XOR  A
                LD   (RTypeForce_ScanLimit), A   ; DEC от нуля даёт 256 проходов
.low:          LD   HL, (RTypeForce_ScanCursor)
                LD   DE, -#0100
                ADD  HL, DE
                LD   (RTypeForce_ScanCursor), HL
                LD   HL, RTypeForce_LowCount
                INC  (HL)
                LD   HL, (RTypeForce_ScanCursor)
                LD   A, RTYPE_WORLD_BG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                CALL RTypeFixed_ReadMapCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   NC, .highStart
                LD   HL, RTypeForce_ScanLimit
                DEC  (HL)
                JR   NZ, .low
.highStart:    LD   HL, (RTypeForce_CollisionAddress)
                LD   (RTypeForce_ScanCursor), HL
                XOR  A
                LD   (RTypeForce_ScanLimit), A
.high:         LD   HL, (RTypeForce_ScanCursor)
                LD   DE, #0100
                ADD  HL, DE
                LD   (RTypeForce_ScanCursor), HL
                LD   HL, RTypeForce_HighCount
                INC  (HL)
                LD   HL, (RTypeForce_ScanCursor)
                CALL RTypeFixed_ReadMapCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   NC, RTypeForce_SelectCounts
                LD   HL, RTypeForce_ScanLimit
                DEC  (HL)
                JR   NZ, .high

RTypeForce_SelectCounts:
                LD   A, (RTypeForce_LowCount)
                LD   B, A
                LD   A, (RTypeForce_HighCount)
                LD   C, A
                LD   A, B
                CP   C
                LD   HL, -#0200
                JR   NC, RTypeForce_ApplyAvoidance ; low>=high: вверх/negative
                LD   HL, #0200                    ; low<high: вниз/positive

RTypeForce_ApplyAvoidance:
                LD   (ArcadeForceVelocityY), HL
                LD   (ArcadeForceLastVertical), HL
                EX   DE, HL
                LD   HL, ArcadeForceYQ8
                CALL RTypeFixed_AddQ8
                JP   RTypeForce_ClampY

RTypeForce_VerticalFollower:
                LD   HL, (ArcadeForceVelocityY)
                LD   A, H
                OR   L
                JR   Z, .history
                BIT  7, H
                LD   DE, -8
                JR   Z, .probeReady
                LD   DE, 8
.probeReady:   LD   HL, (ArcadeForceYQ8 + 1)
                ADD  HL, DE
                EX   DE, HL
                LD   BC, (ArcadeForceXQ8 + 1)
                CALL RTypeFixed_CollisionCodes
                LD   HL, (RTypeFixed_ForegroundCode)
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .clamp
                LD   HL, (RTypeFixed_BackgroundCode)
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .clamp
                XOR  A
                LD   (ArcadeForceVelocityY), A
                LD   (ArcadeForceVelocityY + 1), A
.clamp:        JP   RTypeForce_ClampY
.history:      LD   A, (ArcadeForceReturnHistory)
                OR   A
                JR   NZ, .follow
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, 4
                ADD  HL, DE
                LD   DE, (RTypeForce_TargetX)
                OR   A
                SBC  HL, DE
                LD   DE, 8
                OR   A
                SBC  HL, DE
                JR   NC, .clampOnly               ; unsigned окно 0…7
.follow:       LD   HL, (RTypeForce_DelayedY)
                LD   DE, (ArcadeForceYQ8 + 1)
                OR   A
                SBC  HL, DE
                BIT  7, H
                JR   Z, .positive
                LD   DE, -2
                OR   A
                SBC  HL, DE
                JR   NC, .clampOnly
                LD   HL, -#0200
                JR   .move
.positive:     LD   DE, 3
                OR   A
                SBC  HL, DE
                JR   C, .clampOnly
                LD   HL, #0200
.move:         LD   (ArcadeForceVelocityY), HL
                LD   (ArcadeForceLastVertical), HL
                EX   DE, HL
                LD   HL, ArcadeForceYQ8
                CALL RTypeFixed_AddQ8
.clampOnly:    JP   RTypeForce_ClampY

RTypeForce_ClampY:
                LD   HL, (ArcadeForceYQ8 + 1)
                LD   DE, #0098
                OR   A
                SBC  HL, DE
                JR   NC, .maximum
                XOR  A
                LD   (ArcadeForceYQ8), A
                LD   HL, #0098
                LD   (ArcadeForceYQ8 + 1), HL
                RET
.maximum:      LD   HL, (ArcadeForceYQ8 + 1)
                LD   DE, #0178
                OR   A
                SBC  HL, DE
                RET  C
                JR   NZ, .clampMaximum
                LD   A, (ArcadeForceYQ8)
                OR   A
                RET  Z
.clampMaximum:
                XOR  A
                LD   (ArcadeForceYQ8), A
                LD   HL, #0178
                LD   (ArcadeForceYQ8 + 1), HL
                RET

; Стереть четыре специальные `$09F6` cells вокруг Force (`$2702/$2736`).
RTypeForce_ClearBlocks:
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  C
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, 4
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (ArcadeForceYQ8 + 1)
                ADD  HL, DE
                EX   DE, HL
                JP   RTypeFixed_Clear09F6AtProbe

; Проверка радиуса level hitbox и переход в attached с точным выбором стороны.
RTypeForce_TestAttach:
                LD   A, (ArcadeForceLevel)
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeForceHitboxTable
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; первый/left radius
                PUSH DE
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                CALL RTypeFixed_AbsHL
                POP  DE
                LD   BC, 8
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL                      ; DE=radius+8, HL=abs dx
                OR   A
                SBC  HL, DE
                JR   C, .xInside
                RET  NZ                          ; equality допустима
.xInside:
                LD   A, (ArcadeForceLevel)
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeForceHitboxTable
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                PUSH DE
                LD   HL, (ArcadeForceYQ8 + 1)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                CALL RTypeFixed_AbsHL
                POP  DE
                LD   BC, 6
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL
                OR   A
                SBC  HL, DE
                JR   C, .attach
                RET  NZ
.attach:
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   A, 0
                ADC  A, 0                        ; carry = Force.x < player.x
                LD   (ArcadeForceBehind), A
                LD   A, 1
                LD   (ArcadeForceAttached), A
                LD   A, RTYPE_FORCE_ATTACHED
                LD   (ArcadeForceState), A
                LD   A, #37
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                RET

; Descriptor selectors используют только предсохранённые линейные таблицы.
RTypeForce_ReturnDescriptor:
                LD   A, (ArcadeForceLevel)
                CP   1
                JR   Z, .level1
                CP   2
                JR   Z, .level2
                ; Level 3: direction из полного старого/нового Q8 X и Y-sign.
                CALL RTypeForce_XDirection
                LD   B, A
                LD   HL, (ArcadeForceLastVertical)
                LD   A, H
                OR   L
                JR   Z, .verticalReady
                BIT  7, H
                LD   A, 4
                JR   NZ, .verticalOr
                LD   A, 8
.verticalOr:   OR   B
                LD   B, A
.verticalReady:
                LD   A, B
                OR   A
                JR   NZ, .animate3
                LD   (ArcadeForceAnimation), A
.animate3:     LD   A, (FrameCounter)
                AND  7
                JR   NZ, .table3
                LD   A, (ArcadeForceAnimation)
                INC  A
                AND  3
                LD   (ArcadeForceAnimation), A
.table3:       LD   A, B
                JP   RTypeForce_SelectDirectionDescriptor
.level1:       LD   HL, (ArcadeForceLastVertical)
                LD   A, H
                OR   L
                JR   Z, .level1Table
                LD   A, (FrameCounter)
                AND  3
                JR   NZ, .level1Table
                LD   A, (ArcadeForceAnimation)
                BIT  7, H
                JR   Z, .inc1
                DEC  A
                JR   .norm1
.inc1:         INC  A
.norm1:        CALL RTypeFixed_Normalize6
                LD   (ArcadeForceAnimation), A
.level1Table:  LD   HL, RTypeForceLevel1ReturnDescriptors
                JP   RTypeForce_SelectAnimation6
.level2:       LD   A, (FrameCounter)
                AND  3
                JR   NZ, .base2
                LD   A, (ArcadeForceAnimation)
                INC  A
                CALL RTypeFixed_Normalize6
                LD   (ArcadeForceAnimation), A
.base2:        LD   HL, RTypeForceLevel2DownBehindDescriptors
                LD   DE, (ArcadeForceLastVertical)
                BIT  7, D
                JR   Z, .side2
                LD   HL, RTypeForceLevel2UpBehindDescriptors
.side2:        LD   A, (ArcadeForceBehind)
                OR   A
                JP   NZ, RTypeForce_SelectAnimation6
                LD   DE, RTypeForceLevel2UpFrontDescriptors - RTypeForceLevel2UpBehindDescriptors
                ADD  HL, DE
                JP   RTypeForce_SelectAnimation6

RTypeForce_AttachedDescriptor:
                LD   A, (ArcadeForceLevel)
                CP   3
                JR   NZ, .lower
                LD   A, (FrameCounter)
                AND  7
                JR   NZ, .table3
                LD   A, (ArcadeForceAnimation)
                INC  A
                AND  3
                LD   (ArcadeForceAnimation), A
.table3:       LD   A, (ArcadeForceDirection)
                JP   RTypeForce_SelectDirectionDescriptor
.lower:        LD   A, (FrameCounter)
                AND  3
                JR   NZ, .base
                LD   A, (ArcadeForceDirection)
                LD   E, A
                LD   D, 0
                LD   HL, RTypeForceAttachedAnimationDelta
                ADD  HL, DE
                LD   A, (ArcadeForceAnimation)
                ADD  A, (HL)
                CALL RTypeFixed_Normalize6
                LD   (ArcadeForceAnimation), A
.base:         LD   A, (ArcadeForceLevel)
                CP   2
                LD   HL, RTypeForceLevel1AttachedDescriptors
                JR   NZ, RTypeForce_SelectAnimation6
                LD   HL, RTypeForceLevel2UpBehindDescriptors
                LD   A, (ArcadeForceBehind)
                OR   A
                JR   NZ, RTypeForce_SelectAnimation6
                LD   HL, RTypeForceLevel2UpFrontDescriptors
                JR   RTypeForce_SelectAnimation6

RTypeForce_DetachedDescriptor:
                LD   A, (ArcadeForceLevel)
                CP   3
                JR   Z, .level3
                LD   A, (FrameCounter)
                AND  1
                JR   NZ, .base
                LD   A, (ArcadeForceAnimation)
                INC  A
                CALL RTypeFixed_Normalize6
                LD   (ArcadeForceAnimation), A
.base:         LD   A, (ArcadeForceLevel)
                CP   2
                LD   HL, RTypeForceLevel1ReturnDescriptors
                JR   NZ, RTypeForce_SelectAnimation6
                LD   HL, RTypeForceLevel2UpBehindDescriptors
                LD   A, (ArcadeForceBehind)
                OR   A
                JR   NZ, RTypeForce_SelectAnimation6
                LD   HL, RTypeForceLevel2UpFrontDescriptors
                JR   RTypeForce_SelectAnimation6
.level3:       LD   A, (FrameCounter)
                AND  1
                JR   NZ, .table3
                LD   A, (ArcadeForceAnimation)
                INC  A
                AND  3
                LD   (ArcadeForceAnimation), A
.table3:       LD   HL, RTypeForceLevel3DetachedFrontDescriptors
                LD   DE, (ArcadeForceVelocityX)
                BIT  7, D
                JR   Z, RTypeForce_SelectAnimation4
                LD   HL, RTypeForceLevel3DetachedBehindDescriptors
                JR   RTypeForce_SelectAnimation4

RTypeForce_SelectDirectionDescriptor:
                AND  #0F
                ADD  A, A
                ADD  A, A
                ADD  A, A                       ; direction * 8 bytes
                LD   E, A
                LD   D, 0
                LD   HL, RTypeForceLevel3DirectionDescriptors
                ADD  HL, DE
RTypeForce_SelectAnimation4:
                LD   A, (ArcadeForceAnimation)
                AND  3
                JR   RTypeForce_SelectWord
RTypeForce_SelectAnimation6:
                LD   A, (ArcadeForceAnimation)
RTypeForce_SelectWord:
                ADD  A, A
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (ArcadeForceDescriptor), DE
                EX   DE, HL
                JP   RTypeSprite_PrepareDescriptor

; A=1 при движении вправо, 2 при движении влево, 0 без изменения полного Q8.
RTypeForce_XDirection:
                LD   HL, (ArcadeForceXQ8 + 1)
                LD   DE, (ArcadeForceOldXQ8 + 1)
                OR   A
                SBC  HL, DE
                JR   C, .left
                JR   NZ, .right
                LD   A, (ArcadeForceXQ8)
                LD   B, A
                LD   A, (ArcadeForceOldXQ8)
                CP   B
                JR   C, .right
                JR   NZ, .left
                XOR  A
                RET
.right:        LD   A, 1
                RET
.left:         LD   A, 2
                RET

; ---------------------------------------------------------------------------
; Две постоянные Bit-записи `$2CE5…$3066`.
; ---------------------------------------------------------------------------

RTypeBits_Update:
                LD   A, (ArcadeForceDirection)
                LD   B, A
                LD   A, (ArcadeBitsLastDirection)
                CP   B
                LD   A, 0
                JR   Z, .changedReady
                LD   A, B
.changedReady: LD   (RTypeBits_ChangedDirection), A
                LD   A, B
                LD   (ArcadeBitsLastDirection), A
                LD   A, (ArcadeBitCount)
                OR   A
                JR   Z, .records
                LD   IX, ArcadeBit0Record
                LD   A, (IX + RTYPE_BIT_ACTIVE)
                OR   A
                CALL Z, RTypeBit_Activate
                LD   A, (ArcadeBitCount)
                CP   2
                JR   C, .records
                LD   IX, ArcadeBit1Record
                LD   A, (IX + RTYPE_BIT_ACTIVE)
                OR   A
                JR   NZ, .records
                LD   A, 1
                CALL RTypeBit_Activate
.records:      LD   IX, ArcadeBit0Record
                XOR  A
                CALL RTypeBit_UpdateOne
                LD   IX, ArcadeBit1Record
                LD   A, 1
                JP   RTypeBit_UpdateOne

; IX=record, A=index 0/1.
RTypeBit_Activate:
                LD   (RTypeBits_Index), A
                LD   (IX + RTYPE_BIT_ACTIVE), 1
                XOR  A
                LD   (IX + RTYPE_BIT_X_Q8), A
                LD   (IX + RTYPE_BIT_Y_Q8), A
                LD   (IX + RTYPE_BIT_ANIMATION), A
                LD   (IX + RTYPE_BIT_STRENGTH), A
                LD   (IX + RTYPE_BIT_IDLE_COUNTER), A
                LD   (IX + RTYPE_BIT_READ_CURSOR), A
                LD   (IX + RTYPE_BIT_WRITE_CURSOR), 2
                LD   HL, (RTypePlayerNativeX)
                LD   (IX + RTYPE_BIT_X_Q8 + 1), L
                LD   (IX + RTYPE_BIT_X_Q8 + 2), H
                LD   (RTypeBits_TargetX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (IX + RTYPE_BIT_Y_Q8 + 1), L
                LD   (IX + RTYPE_BIT_Y_Q8 + 2), H
                LD   A, (RTypeBits_Index)
                OR   A
                LD   DE, #0010
                JR   Z, .biasReady
                LD   DE, -#0010
.biasReady:    ADD  HL, DE
                LD   (RTypeBits_TargetY), HL
                PUSH IX
                POP  HL
                LD   DE, RTYPE_BIT_HISTORY_X
                ADD  HL, DE
                LD   B, 16
.history:      LD   DE, (RTypeBits_TargetX)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                INC  HL
                DJNZ .history
                PUSH IX
                POP  HL
                LD   DE, RTYPE_BIT_HISTORY_Y
                ADD  HL, DE
                LD   B, 16
.historyY:     LD   DE, (RTypeBits_TargetY)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                INC  HL
                DJNZ .historyY
                LD   A, #56
                CALL RTypeResources_Acquire
                LD   (IX + RTYPE_BIT_PALETTE), A
                RET

; IX=record, A=index. Count=1 оставляет обе уже активные записи, как ROM.
RTypeBit_UpdateOne:
                LD   (RTypeBits_Index), A
                LD   A, (IX + RTYPE_BIT_ACTIVE)
                OR   A
                RET  Z
                LD   A, (ArcadeBitCount)
                OR   A
                JR   NZ, .active
                LD   A, (IX + RTYPE_BIT_PALETTE)
                CALL RTypeResources_Release
                LD   (IX + RTYPE_BIT_ACTIVE), 0
                RET
.active:       LD   A, (RTypeBits_ChangedDirection)
                OR   A
                JR   Z, .decay
                LD   A, (IX + RTYPE_BIT_STRENGTH)
                CP   #E0
                JR   NC, .decay
                ADD  A, 5
                LD   (IX + RTYPE_BIT_STRENGTH), A
.decay:        LD   A, (IX + RTYPE_BIT_STRENGTH)
                OR   A
                JR   Z, .idleWindow
                DEC  A
                LD   (IX + RTYPE_BIT_STRENGTH), A
.idleWindow:   LD   A, (FrameCounter)
                AND  7
                JR   NZ, .idleIncrement
                LD   A, (IX + RTYPE_BIT_IDLE_COUNTER)
                CP   7
                JR   C, .clearIdle
                XOR  A
                LD   (IX + RTYPE_BIT_STRENGTH), A
.clearIdle:    XOR  A
                LD   (IX + RTYPE_BIT_IDLE_COUNTER), A
.idleIncrement:
                LD   A, (RTypeBits_ChangedDirection)
                OR   A
                JR   NZ, .target
                INC  (IX + RTYPE_BIT_IDLE_COUNTER)
.target:       LD   A, (IX + RTYPE_BIT_STRENGTH)
                SRL  A
                SRL  A
                SRL  A
                SRL  A
                SRL  A
                SRL  A                            ; coarse 0…3
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A                        ; coarse * 64
                LD   E, A
                LD   D, 0
                LD   A, (ArcadeForceDirection)
                ADD  A, A
                ADD  A, A
                ADD  A, E
                LD   E, A
                JR   NC, .offsetCarryReady
                INC  D
.offsetCarryReady:
                LD   HL, RTypeBitsOffsetTable
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTypePlayerNativeX)
                ADD  HL, DE
                LD   (RTypeBits_TargetX), HL
                INC  HL                           ; флаги здесь не нужны
                DEC  HL
                LD   E, (IX + RTYPE_BIT_WRITE_CURSOR)
                LD   D, 0
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_HISTORY_X
                ADD  HL, BC
                ADD  HL, DE
                LD   BC, (RTypeBits_TargetX)
                LD   (HL), C
                INC  HL
                LD   (HL), B

                ; Вертикальное смещение идёт из соседнего word той же записи.
                LD   HL, RTypeBitsOffsetTable
                LD   A, (IX + RTYPE_BIT_STRENGTH)
                SRL  A
                SRL  A
                SRL  A
                SRL  A
                SRL  A
                SRL  A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   A, (ArcadeForceDirection)
                ADD  A, A
                ADD  A, A
                ADD  A, E
                LD   E, A
                JR   NC, .verticalCarryReady
                INC  D
.verticalCarryReady:
                ADD  HL, DE
                INC  HL
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, (RTypePlayerNativeY)
                LD   A, (RTypeBits_Index)
                OR   A
                LD   BC, #0020
                JR   Z, .bias
                LD   BC, -#0020
.bias:         ADD  HL, BC
                ADD  HL, DE
                LD   (RTypeBits_TargetY), HL
                LD   E, (IX + RTYPE_BIT_WRITE_CURSOR)
                LD   D, 0
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_HISTORY_Y
                ADD  HL, BC
                ADD  HL, DE
                LD   BC, (RTypeBits_TargetY)
                LD   (HL), C
                INC  HL
                LD   (HL), B
                LD   A, (IX + RTYPE_BIT_WRITE_CURSOR)
                ADD  A, 2
                AND  #1F
                LD   (IX + RTYPE_BIT_WRITE_CURSOR), A

                LD   A, (ArcadeForceDirection)
                OR   A
                JR   Z, .speedZero
                LD   A, (IX + RTYPE_BIT_STRENGTH)
                SRL  A
                SRL  A
                SRL  A
                AND  #1F
                JR   .speedIndex
.speedZero:    XOR  A
.speedIndex:   ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeBit0SpeedTable
                LD   A, (RTypeBits_Index)
                OR   A
                JR   Z, .speedTable
                LD   HL, RTypeBit1SpeedTable
.speedTable:   ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (RTypeBits_Speed), DE
                LD   A, D
                LD   (RTypeBits_Tolerance), A
                LD   E, (IX + RTYPE_BIT_READ_CURSOR)
                LD   D, 0
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_HISTORY_X
                ADD  HL, BC
                ADD  HL, DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)                     ; BC=target X
                LD   L, (IX + RTYPE_BIT_X_Q8 + 1)
                LD   H, (IX + RTYPE_BIT_X_Q8 + 2)
                CALL RTypeBit_AxisVelocity
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_X_Q8
                ADD  HL, BC
                CALL RTypeFixed_AddQ8
                LD   E, (IX + RTYPE_BIT_READ_CURSOR)
                LD   D, 0
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_HISTORY_Y
                ADD  HL, BC
                ADD  HL, DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                LD   L, (IX + RTYPE_BIT_Y_Q8 + 1)
                LD   H, (IX + RTYPE_BIT_Y_Q8 + 2)
                CALL RTypeBit_AxisVelocity
                PUSH IX
                POP  HL
                LD   BC, RTYPE_BIT_Y_Q8
                ADD  HL, BC
                CALL RTypeFixed_AddQ8
                LD   A, (IX + RTYPE_BIT_READ_CURSOR)
                ADD  A, 2
                AND  #1F
                LD   (IX + RTYPE_BIT_READ_CURSOR), A
                LD   A, (FrameCounter)
                AND  3
                JR   NZ, .descriptor
                LD   A, (IX + RTYPE_BIT_ANIMATION)
                INC  A
                CP   12
                JR   C, .storeAnimation
                XOR  A
.storeAnimation:
                LD   (IX + RTYPE_BIT_ANIMATION), A
.descriptor:   LD   HL, #175E
                LD   A, (RTypeBits_Index)
                OR   A
                JR   Z, .descriptorBase
                LD   HL, #17A6
.descriptorBase:
                LD   A, (IX + RTYPE_BIT_ANIMATION)
                LD   E, A
                LD   D, 0
                ADD  A, A
                ADD  A, E
                ADD  A, A                        ; animation * 6
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   (IX + RTYPE_BIT_DESCRIPTOR), L
                LD   (IX + RTYPE_BIT_DESCRIPTOR + 1), H
                CALL RTypeSprite_PrepareDescriptor
                LD   L, (IX + RTYPE_BIT_X_Q8 + 1)
                LD   H, (IX + RTYPE_BIT_X_Q8 + 2)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                RET  C
                LD   L, (IX + RTYPE_BIT_X_Q8 + 1)
                LD   H, (IX + RTYPE_BIT_X_Q8 + 2)
                LD   DE, -4
                ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   L, (IX + RTYPE_BIT_Y_Q8 + 1)
                LD   H, (IX + RTYPE_BIT_Y_Q8 + 2)
                LD   DE, 4
                ADD  HL, DE
                EX   DE, HL
                JP   RTypeFixed_Clear09F6AtProbe

; BC=target, HL=current. Вернуть DE=0,+speed или -speed по unsigned окну.
RTypeBit_AxisVelocity:
                LD   A, (RTypeBits_Tolerance)
                LD   E, A
                LD   D, 0
                PUSH HL
                ADD  HL, DE
                LD   A, B
                CP   H
                JR   C, .insideUpper
                JR   NZ, .positive
                LD   A, C
                CP   L
                JR   C, .insideUpper
.positive:     POP  HL
                LD   DE, (RTypeBits_Speed)
                RET
.insideUpper:  POP  HL
                OR   A
                SBC  HL, DE                       ; current-tolerance modulo 16-bit
                LD   A, B
                CP   H
                JR   C, .negative
                JR   NZ, .zero
                LD   A, C
                CP   L
                JR   C, .negative
.zero:         LD   DE, 0
                RET
.negative:     LD   HL, (RTypeBits_Speed)
                XOR  A
                SUB  L
                LD   E, A
                SBC  A, A
                SUB  H
                LD   D, A
                RET

; ---------------------------------------------------------------------------
; Общие арифметические и terrain helpers.
; ---------------------------------------------------------------------------

; HL -> `[fraction, integer-low, integer-high]`, DE=signed Q8 word.
RTypeFixed_AddQ8:
                LD   A, (HL)
                ADD  A, E
                LD   (HL), A
                INC  HL
                LD   A, (HL)
                ADC  A, D
                LD   (HL), A
                INC  HL
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:    LD   A, (HL)
                ADC  A, C
                LD   (HL), A
                RET

RTypeFixed_AbsHL:
                BIT  7, H
                RET  Z
                LD   A, L
                CPL
                LD   L, A
                LD   A, H
                CPL
                LD   H, A
                INC  HL
                RET

; Нормализовать signed/unsigned A в диапазон 0…5.
RTypeFixed_Normalize6:
                BIT  7, A
                JR   Z, .high
.low:          ADD  A, 6
                BIT  7, A
                JR   NZ, .low
.high:         CP   6
                RET  C
                SUB  6
                JR   .high

; BC=native X, DE=native Y. Сохранить оба живых collision code.
RTypeFixed_CollisionCodes:
                LD   (RTypeFixed_ProbeX), BC
                LD   (RTypeFixed_ProbeY), DE
                CALL RTypeTerrain_ForegroundCode
                LD   (RTypeFixed_ForegroundCode), HL
                LD   BC, (RTypeFixed_ProbeX)
                LD   DE, (RTypeFixed_ProbeY)
                CALL RTypeTerrain_BackgroundCode
                LD   (RTypeFixed_BackgroundCode), HL
                RET

; HL=ring byte address, page задана RTypeFixed_MapPage. Вернуть code&$0FFF.
RTypeFixed_ReadMapCode:
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, (RTypeFixed_MapPage)
                SetPage3_A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                AND  #0F
                LD   H, A
                LD   L, E
                RET

; BC/DE = probe coordinate. Стереть offsets 0,4,$104,$100, если code `$09F6`.
RTypeFixed_Clear09F6AtProbe:
                CALL RTypeTerrain_ForegroundCode
                LD   HL, (RTypeTerrain_Address)
                LD   (RTypeFixed_ClearBase), HL
                LD   HL, RTypeFixed_ClearOffsets
                LD   (RTypeFixed_ClearOffsetPtr), HL
                LD   A, 4
                LD   (RTypeFixed_ClearCount), A
.next:         LD   HL, (RTypeFixed_ClearOffsetPtr)
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (RTypeFixed_ClearOffsetPtr), HL
                LD   HL, (RTypeFixed_ClearBase)
                ADD  HL, DE
                LD   (RTypeFixed_ClearAddress), HL
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                LD   (RTypeFixed_MapPage), A
                CALL RTypeFixed_ReadMapCode
                LD   DE, #09F6
                OR   A
                SBC  HL, DE
                JR   NZ, .advance
                LD   HL, (RTypeFixed_ClearAddress)
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   (HL), #A0
                INC  HL
                LD   (HL), #0F
                INC  HL
                LD   (HL), 0
                INC  HL
                LD   (HL), 0
.advance:      LD   HL, RTypeFixed_ClearCount
                DEC  (HL)
                JR   NZ, .next
                RET

RTypeFixed_ClearOffsets:
                DEFW 0, 4, #0104, #0100

; Bank-local temporaries: они используются только пока page #E6 отображена.
RTypeForce_WasHidden:       DEFB 0
RTypeForce_DelayedX:        DEFW 0
RTypeForce_DelayedY:        DEFW 0
RTypeForce_TargetX:         DEFW 0
RTypeForce_ProbeX:          DEFW 0
RTypeForce_ProbeCount:      DEFB 0
RTypeForce_FgAddress:       DEFW 0
RTypeForce_BgAddress:       DEFW 0
RTypeForce_CollisionLayer:  DEFB 0
RTypeForce_CollisionAddress:DEFW 0
RTypeForce_ScanCursor:      DEFW 0
RTypeForce_LowCount:        DEFB 0
RTypeForce_HighCount:       DEFB 0
RTypeForce_Edge:            DEFB 0
RTypeForce_ScanLimit:       DEFB 0
RTypeBits_Index:            DEFB 0
RTypeBits_ChangedDirection: DEFB 0
RTypeBits_TargetX:          DEFW 0
RTypeBits_TargetY:          DEFW 0
RTypeBits_Speed:            DEFW 0
RTypeBits_Tolerance:        DEFB 0
RTypeFixed_ProbeX:          DEFW 0
RTypeFixed_ProbeY:          DEFW 0
RTypeFixed_ForegroundCode:  DEFW 0
RTypeFixed_BackgroundCode:  DEFW 0
RTypeFixed_MapPage:         DEFB 0
RTypeFixed_ClearBase:       DEFW 0
RTypeFixed_ClearAddress:    DEFW 0
RTypeFixed_ClearOffsetPtr:  DEFW 0
RTypeFixed_ClearCount:      DEFB 0

                include "generated_fixed_player_tables.inc"
