; ============================================================================
; Игровое состояние аркадного R-Type в логических координатах 640x480.
; Позиции беззнаковые Q16.8: [дробь][младший байт целой части][старший байт].
; На границе FT812 отрисовщик преобразует только целую логическую координату.
; ============================================================================

ArcadePlayerX          EQU #4203        ; 3 байта, логическая Q16.8
ArcadePlayerY          EQU #4206        ; 3 байта, логическая Q16.8
ArcadeMousePrevX       EQU #4209        ; слово, логическая координата мыши
ArcadeMousePrevY       EQU #420B        ; слово
ArcadeMouseValid       EQU #420D        ; байт
ArcadeReleasePrev      EQU #420E        ; байт, прошлый уровень глобального ПКМ
ArcadeForceDetached    EQU #420F        ; зеркало: 1 только в состоянии свободного полёта
ArcadeFireHeld         EQU #4210        ; байт
ArcadeWaveCharge       EQU #4211        ; байт, длительность удержания с насыщением
ArcadeWaveShotPower    EQU #4212        ; байт, последний отпущенный заряд
ArcadeWaveShotPending  EQU #4213        ; байт, фронт при отпускании огня
; Адреса #4214..#421D принадлежат general_sound.asm.
ArcadeShotTable        EQU #4220        ; три 9-байтные нативные записи `$04D6`
ArcadeWaveActive       EQU #423C        ; байт: снаряд Wave существует
ArcadeWaveDelay        EQU #423D        ; байт: задержка появления после отпускания
ArcadeWaveAnim         EQU #423E        ; байт: счётчик двухкадровой анимации
ArcadeWaveX            EQU #423F        ; word, нативный anchor M72
ArcadeWaveY            EQU #4241        ; word, нативный anchor M72
ArcadeWaveReleaseX     EQU #4243        ; word, неподвижная вспышка у носа
ArcadeWaveReleaseY     EQU #4245        ; word, нативный anchor M72
ArcadeWaveLogicalY     EQU #4247        ; word, точный offline-crop Y для FT812
ArcadeShotPending      EQU #424B        ; байт, фронт обычного выстрела (звук $30)
; `$424C…$4258` — резидентная трансляция fixed player/director. Поля не живут
; в banked object pool: как и исходные DS:$0000/$0020, они доступны каждому
; enemy handler независимо от страницы slot2/slot3.
ArcadeLives            EQU #424C        ; оставшиеся жизни, пользовательский баланс 1…8
ArcadeLifeState        EQU #424D        ; 0=active, 1=death `$22CD`, 2=game over
ArcadeDeathAge         EQU #424E        ; word, возраст director смерти в VBlank
ArcadeInvulnerability  EQU #4250        ; byte, штатные `$80` кадров после respawn
ArcadePlayerVisible    EQU #4251        ; byte, player record ещё выводится
ArcadeDeathDescriptor EQU #4252        ; word `$1338…$1362`, фаза взрыва R-9
ArcadeScore            EQU #4254        ; 4 bytes packed BCD, восемь цифр
ArcadeBonusIndex       EQU #4258        ; следующий порог призовой жизни
; Свободный промежуток видеосостояния #4284…#428F хранит только fixed-player.
; Он доступен при любом slot2/slot3 bank и не отнимает место у object pools.
ArcadeIntroFrame       EQU #4284        ; word, 0…226: точный launch-кадр Python
ArcadePlayerPitch      EQU #4286        ; byte 0…39, индекс корпуса = pitch >> 3
ArcadeIntroEffectKind EQU #4287        ; byte 0=нет, 1…4=подлинный launch-эффект
ArcadeIntroEffectX    EQU #4288        ; word, готовая signed logical X
ArcadeIntroEffectY    EQU #428A        ; word, готовая signed logical Y

; После входа в gameplay титульная копия Sprite RAM #4300…#46FF больше не
; используется. Fixed-player занимает свободный хвост после общего object-work
; #4340…#4385. Все code banks видят эти записи без переключения slot3.
RTypeFixedStateBase            EQU #4386
ArcadeForceLevel               EQU RTypeFixedStateBase + 0
ArcadeForceRequestedLevel      EQU RTypeFixedStateBase + 1
ArcadeForceState               EQU RTypeFixedStateBase + 2
ArcadeForceXQ8                 EQU RTypeFixedStateBase + 3  ; fraction, integer word
ArcadeForceYQ8                 EQU RTypeFixedStateBase + 6
ArcadeForceVelocityX           EQU RTypeFixedStateBase + 9  ; signed Q8 word
ArcadeForceVelocityY           EQU RTypeFixedStateBase + 11
ArcadeForceBehind              EQU RTypeFixedStateBase + 13
ArcadeForceReturnHistory       EQU RTypeFixedStateBase + 14
ArcadeForceAttached            EQU RTypeFixedStateBase + 15
ArcadeForceAnimation           EQU RTypeFixedStateBase + 16
ArcadeForceAnimationGroup      EQU RTypeFixedStateBase + 17
ArcadeForceDescriptor          EQU RTypeFixedStateBase + 18
ArcadeForceOldXQ8              EQU RTypeFixedStateBase + 20
ArcadeForceLastVertical        EQU RTypeFixedStateBase + 23
ArcadeForcePalette             EQU RTypeFixedStateBase + 25
ArcadeForceActionEdge          EQU RTypeFixedStateBase + 26
ArcadeForceDirection           EQU RTypeFixedStateBase + 27
ArcadePlayerNativeHistory      EQU RTypeFixedStateBase + 28 ; 16 пар X,Y
ArcadeBitCount                 EQU RTypeFixedStateBase + 92 ; исходный DS:$0033
ArcadeWeaponPickupPending      EQU RTypeFixedStateBase + 93 ; исходный DS:$0037
ArcadeWeaponType              EQU RTypeFixedStateBase + 94 ; исходный DS:$003C
ArcadePlayerRam0035           EQU RTypeFixedStateBase + 95
ArcadePlayerRam0036           EQU RTypeFixedStateBase + 96
ArcadeBitsLastDirection       EQU RTypeFixedStateBase + 97
ArcadeBit0Record              EQU RTypeFixedStateBase + 98
ArcadeBit1Record              EQU ArcadeBit0Record + 80
RTypeFixedStateEnd            EQU ArcadeBit1Record + 80

RTYPE_FORCE_HIDDEN            EQU 0
RTYPE_FORCE_RETURN            EQU 1
RTYPE_FORCE_ATTACHED          EQU 2
RTYPE_FORCE_DETACHED          EQU 3
RTYPE_FIXED_PLAYER_BANK_PAGE  EQU #E6

ARCADE_LIFE_ACTIVE     EQU 0
ARCADE_LIFE_DEATH      EQU 1
ARCADE_LIFE_GAME_OVER  EQU 2
; Эти значения принадлежат запускаемой run_python.cmd версии. Транслятор
; извлекает их из rtype_port.player_lifecycle; ручной баланс здесь запрещён.
ARCADE_INITIAL_LIVES   EQU RTYPEPY_INITIAL_LIVES
ARCADE_MAX_LIVES       EQU RTYPEPY_MAX_LIVES
ARCADE_PLAYER_CLEAR_AGE EQU RTYPEPY_PLAYER_CLEAR_AGE
ARCADE_LIFE_DECREMENT_AGE EQU RTYPEPY_LIFE_DECREMENT_AGE
ARCADE_RESPAWN_AGE     EQU RTYPEPY_RESPAWN_AGE
ARCADE_RESPAWN_INVULNERABILITY EQU RTYPEPY_RESPAWN_INVULNERABILITY
ARCADE_INTRO_FRAMES    EQU 226
ARCADE_INTRO_REC_SIZE  EQU 14
ARCADE_PITCH_NEUTRAL   EQU 20
ARCADE_PITCH_MAX       EQU 39

ARCADE_SHOT_COUNT      EQU 3
ARCADE_SHOT_REC_SIZE   EQU 9
ARCADE_SHOT_ACTIVE     EQU 0            ; 0=free, 1=очередь, 2=flight, 3=spent, 4=terminal
ARCADE_SHOT_X          EQU 1            ; word, исходный anchor `$04D6+$04`
ARCADE_SHOT_Y          EQU 3            ; word, исходный anchor `$04D6+$08`
ARCADE_SHOT_LOGICAL_Y  EQU 5            ; word, точный offline-crop Y для FT812
ARCADE_SHOT_TIMER      EQU 7            ; задержка очереди/три terminal-фазы
ARCADE_SHOT_IMPACT     EQU 8            ; 0=`$2000`, 1=`$2018` от terrain
ARCADE_SHOT_WAIT       EQU 1
ARCADE_SHOT_FLIGHT     EQU 2
ARCADE_SHOT_SPENT      EQU 3
ARCADE_SHOT_TERMINAL   EQU 4

                ifndef RTYPE_PLAYER_START_X
RTYPE_PLAYER_START_X   EQU 233
                endif
ARCADE_PLAYER_START_X  EQU RTYPE_PLAYER_START_X ; начало обрезанного R-9, кадр 900
ARCADE_PLAYER_START_Y  EQU 192
ARCADE_PLAYER_W        EQU 53
ARCADE_PLAYER_H        EQU 28
ARCADE_PLAYFIELD_H     EQU 450          ; нативный y=240 после масштаба 15/8
ARCADE_PLAYER_MAX_X    EQU 640 - ARCADE_PLAYER_W
ARCADE_PLAYER_MAX_Y    EQU ARCADE_PLAYFIELD_H - ARCADE_PLAYER_H

; Приближение оригинальных 2 нативных пикселей/кадр в логическом масштабе.
; X: 2*5/3 = 3.332 пикселя, Y: 2*15/8 = 3.75; приращения хранятся в Q8.
ARCADE_MOVE_X_Q8       EQU 853
ARCADE_MOVE_Y_Q8       EQU 960
ARCADE_MOUSE_DELTA_MAX EQU 63
ARCADE_WAVE_MIN        EQU #18
ARCADE_WAVE_MAX        EQU #80

ArcadeGame_Init:
                XOR  A
                LD   (ArcadePlayerX), A
                LD   (ArcadePlayerY), A
                LD   HL, ARCADE_PLAYER_START_X
                LD   (ArcadePlayerX + 1), HL
                LD   HL, ARCADE_PLAYER_START_Y
                LD   (ArcadePlayerY + 1), HL
                LD   (ArcadeMouseValid), A
                LD   (ArcadeReleasePrev), A
                LD   (ArcadeForceDetached), A
                LD   (ArcadeFireHeld), A
                LD   (ArcadeWaveCharge), A
                LD   (ArcadeWaveShotPower), A
                LD   (ArcadeWaveShotPending), A
                LD   (ArcadeShotPending), A
                LD   (ArcadeIntroFrame), A
                LD   (ArcadeIntroFrame + 1), A
                LD   (ArcadeIntroEffectKind), A
                LD   (ArcadeIntroEffectX), A
                LD   (ArcadeIntroEffectX + 1), A
                LD   (ArcadeIntroEffectY), A
                LD   (ArcadeIntroEffectY + 1), A
                LD   A, ARCADE_PITCH_NEUTRAL
                LD   (ArcadePlayerPitch), A
                XOR  A
                LD   HL, ArcadeShotTable
                LD   DE, ArcadeShotTable + 1
                LD   BC, ARCADE_SHOT_COUNT * ARCADE_SHOT_REC_SIZE - 1
                LD   (HL), A
                LDIR
                LD   HL, ArcadeWaveActive
                LD   DE, ArcadeWaveActive + 1
                LD   BC, 14
                LD   (HL), A
                LDIR
                ; Literal Game.__init__.m72_frame_counter приходит из AST:
                ; от него зависят анимации R-9, Beam и object handlers.
                CALL RTypePyGameplay_InitFrameCounter
                CALL RTypeObjects_Reset
                CALL ArcadeFixedPlayer_Init
                CALL ArcadeLifecycle_Reset
                CALL ArcadePlayer_SyncNative
                JP   RTypeTarget_Init

ArcadeGame_Update:
                LD   HL, (FrameCounter)
                INC  HL
                LD   (FrameCounter), HL
                ; Первые 226 кадров принадлежат штатному `$1F3D`: мир и
                ; тупые automata продолжают идти, но управление/оружие и
                ; lifecycle игрока ещё не исполняются. После object pass
                ; выбирается следующая готовая запись вылета, как в Python.
                LD   HL, (ArcadeIntroFrame)
                LD   DE, ARCADE_INTRO_FRAMES
                OR   A
                SBC  HL, DE
                JR   NC, .activePlayer
                CALL RTypeWorld_Update
                JP   ArcadePlayer_IntroUpdate
.activePlayer:
                ; Python Game.update отделяет death/game-over frame до player
                ; input и fixed weapons. Сам death-path сгенерирован из AST.
                LD   A, (ArcadeLifeState)
                OR   A
                JP   NZ, RTypePyLifecycle_DeathFrame
                CALL ArcadeLifecycle_Update
                ifdef RTYPE_SHOT_AUTORUN
                ; Диагностическая сборка Unreal: три коротких импульса FIRE
                ; создают подлинные снаряды без синтетического ввода Windows.
                LD   A, (FrameCounter + 1)
                OR   A
                JR   NZ, .shotProbeNoFire
                LD   A, (FrameCounter)
                CP   120
                JR   C, .shotProbeNoFire
                CP   122
                JR   C, .shotProbeFire
                CP   150
                JR   C, .shotProbeNoFire
                CP   152
                JR   C, .shotProbeFire
                CP   180
                JR   C, .shotProbeNoFire
                CP   182
                JR   C, .shotProbeFire
.shotProbeNoFire:
                XOR  A
                LD   (InputState), A
                JR   .shotProbeDone
.shotProbeFire:
                LD   A, INPUT_FIRE
                LD   (InputState), A
.shotProbeDone:
                endif
                ifdef RTYPE_WAVE_AUTORUN
                ; Диагностическая сборка Unreal: ровно 67 кадров удержания FIRE
                ; и последующее отпускание создают настоящий Wave Cannon.
                LD   A, (FrameCounter + 1)
                OR   A
                JR   NZ, .waveProbeNoFire
                LD   A, (FrameCounter)
                CP   120
                JR   C, .waveProbeNoFire
                CP   187
                JR   NC, .waveProbeNoFire
                LD   A, INPUT_FIRE
                LD   (InputState), A
                JR   .waveProbeDone
.waveProbeNoFire:
                XOR  A
                LD   (InputState), A
.waveProbeDone:
                endif
                CALL ArcadePlayer_Keyboard
                CALL ArcadePlayer_UpdatePitch
                ifdef RTYPE_EDGE_AUTORUN
                ; Диагностическая сборка только для эмулятора: сначала даёт
                ; окну FT812 и захвату стабилизироваться, затем ведёт настоящую
                ; игровую координату влево без синтетического ввода Windows.
                LD   HL, (FrameCounter)
                LD   DE, 120
                OR   A
                SBC  HL, DE
                CALL NC, ArcadePlayer_SubX
                endif
                CALL ArcadePlayer_Mouse
                CALL ArcadePlayer_Clamp
                ; Enemy `$1D89`, projectile fire и boss tracking читают native
                ; fixed-player words. Они должны соответствовать текущей, а не
                ; стартовой логической координате уже в этом object pass.
                CALL ArcadePlayer_SyncNative
                CALL ArcadeForce_Update
                CALL ArcadeShots_Update
                CALL ArcadeWaveProjectile_Update
                CALL ArcadeWave_Update
                JP   RTypeWorld_Update

; ---------------------------------------------------------------------------
; Fixed-player/native boundary и автомат жизней `$10FA/$11BB/$11CC/$22CD`.
; ---------------------------------------------------------------------------

; Перевести верхний левый угол готового 640×480 R-9 asset обратно в нативный
; anchor M72, которым пользуются все ROM object handlers:
;   X = round(logical_x*3/5) + `$0150`
;   Y = `$0176` - round(logical_y*8/15)`.
; Знаменатели нечётные, поэтому точного half-way случая нет; добавление 2/7
; перед целочисленным делением полностью совпадает с текущей Python-версией.
ArcadePlayer_SyncNative:
                LD   HL, (ArcadePlayerX + 1)
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE                     ; logical X * 3
                LD   DE, 2
                ADD  HL, DE
                LD   DE, 5
                CALL ArcadePlayer_DivideUnsigned
                LD   H, B
                LD   L, C
                LD   DE, #0150
                ADD  HL, DE
                LD   (RTypePlayerNativeX), HL

                LD   HL, (ArcadePlayerY + 1)
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; logical Y * 8
                LD   DE, 7
                ADD  HL, DE
                LD   DE, 15
                CALL ArcadePlayer_DivideUnsigned
                LD   HL, #0176
                OR   A
                SBC  HL, BC
                LD   (RTypePlayerNativeY), HL
                RET

; HL=числитель, DE=ненулевой делитель. Вернуть BC=floor(HL/DE).
; Диапазон fixed player не превышает 1922, поэтому буквальное вычитание проще
; и короче общего 16-разрядного divider, а цена — менее 385 итераций/VBlank.
ArcadePlayer_DivideUnsigned:
                LD   BC, 0
.loop:         OR   A
                SBC  HL, DE
                JR   C, .done
                INC  BC
                JR   .loop
.done:         ADD  HL, DE
                RET

ArcadeLifecycle_Reset:
                LD   A, ARCADE_INITIAL_LIVES
                LD   (ArcadeLives), A
                XOR  A
                LD   (ArcadeLifeState), A
                LD   (ArcadeDeathAge), A
                LD   (ArcadeDeathAge + 1), A
                LD   (ArcadeInvulnerability), A
                LD   (ArcadeDeathDescriptor), A
                LD   (ArcadeDeathDescriptor + 1), A
                LD   A, #FF
                LD   (RTypePyDeathPalette), A
                XOR  A
                LD   HL, ArcadeScore
                LD   DE, ArcadeScore + 1
                LD   BC, 3
                LD   (HL), A
                LDIR
                LD   (ArcadeBonusIndex), A
                INC  A
                LD   (ArcadePlayerVisible), A
                RET

; Начать смерть только из collision-enabled active state. Carry=1 означает,
; что `$22CD` действительно установлен; повторный hit во время смерти либо
; `$80`-кадровой защиты ничего не меняет.
ArcadeLifecycle_BeginDeath:
                LD   A, (ArcadeLifeState)
                OR   A
                RET  NZ
                LD   A, (ArcadeInvulnerability)
                OR   A
                RET  NZ
                LD   A, ARCADE_LIFE_DEATH
                LD   (ArcadeLifeState), A
                XOR  A
                LD   (ArcadeDeathAge), A
                LD   (ArcadeDeathAge + 1), A
                LD   (ArcadeDeathDescriptor), A
                LD   (ArcadeDeathDescriptor + 1), A
                LD   A, 1
                LD   (ArcadePlayerVisible), A
                CALL RTypePyLifecycle_BeginDeathBackend
                SCF
                RET

; Добавить призовую жизнь. Carry=1 только при реальном 7->8 (или ниже)
; переходе; при восьми жизнях INC и ложный award sound запрещены.
ArcadeLives_Award:
                LD   A, (ArcadeLives)
                CP   ARCADE_MAX_LIVES
                RET  NC
                INC  A
                LD   (ArcadeLives), A
                SCF
                RET

ArcadeLifecycle_Update:
                LD   A, (ArcadeLifeState)
                OR   A
                JR   NZ, .notActive
                LD   A, (ArcadeInvulnerability)
                OR   A
                RET  Z
                DEC  A
                LD   (ArcadeInvulnerability), A
                RET
.notActive:    CP   ARCADE_LIFE_DEATH
                RET  NZ                         ; terminal GAME OVER
                LD   HL, (ArcadeDeathAge)
                INC  HL
                LD   (ArcadeDeathAge), HL
                CALL ArcadeLifecycle_SelectDeathDescriptor
                CALL RTypePyLifecycle_PrepareExplosion
                LD   HL, (ArcadeDeathAge)
                LD   DE, ARCADE_PLAYER_CLEAR_AGE
                OR   A
                SBC  HL, DE
                JR   NZ, .lifeAge
                CALL RTypePyLifecycle_ClearBackend
                XOR  A
                LD   (ArcadePlayerVisible), A
.lifeAge:      LD   HL, (ArcadeDeathAge)
                LD   DE, ARCADE_LIFE_DECREMENT_AGE
                OR   A
                SBC  HL, DE
                JR   NZ, .respawnAge
                LD   A, (ArcadeLives)
                DEC  A
                LD   (ArcadeLives), A
                OR   A
                JR   NZ, .respawnAge
                LD   A, ARCADE_LIFE_GAME_OVER
                LD   (ArcadeLifeState), A
                RET
.respawnAge:   LD   HL, (ArcadeDeathAge)
                LD   DE, ARCADE_RESPAWN_AGE
                OR   A
                SBC  HL, DE
                RET  NZ
                XOR  A
                LD   (ArcadeLifeState), A
                LD   (ArcadeDeathDescriptor), A
                LD   (ArcadeDeathDescriptor + 1), A
                LD   A, ARCADE_RESPAWN_INVULNERABILITY
                LD   (ArcadeInvulnerability), A
                LD   A, 1
                LD   (ArcadePlayerVisible), A
                JP   RTypePyLifecycle_RespawnBackend

; Указатель `$1318` держит первый кадр три раза, затем ROM durations выбирают
; семь descriptor roots. После age 19 player остаётся на `$1362` до очистки.
ArcadeLifecycle_SelectDeathDescriptor:
                LD   HL, (ArcadeDeathAge)
                LD   A, H
                OR   A
                JR   NZ, .last
                LD   A, L
                CP   4
                LD   HL, #1338
                JR   C, .store
                CP   7
                LD   HL, #133E
                JR   C, .store
                CP   9
                LD   HL, #1344
                JR   C, .store
                CP   11
                LD   HL, #134A
                JR   C, .store
                CP   13
                LD   HL, #1350
                JR   C, .store
                CP   16
                LD   HL, #1356
                JR   C, .store
                CP   20
                LD   HL, #135C
                JR   C, .store
.last:         LD   HL, #1362
.store:        LD   (ArcadeDeathDescriptor), HL
                RET

ArcadePlayer_Keyboard:
                LD   A, (InputState)
                LD   B, A
                BIT  0, B
                CALL NZ, ArcadePlayer_SubX
                BIT  1, B
                CALL NZ, ArcadePlayer_AddX
                BIT  2, B
                CALL NZ, ArcadePlayer_SubY
                BIT  3, B
                CALL NZ, ArcadePlayer_AddY
                RET

ArcadePlayer_AddX:
                LD   HL, (ArcadePlayerX)
                LD   DE, ARCADE_MOVE_X_Q8
                ADD  HL, DE
                LD   (ArcadePlayerX), HL
                LD   A, (ArcadePlayerX + 2)
                ADC  A, 0
                LD   (ArcadePlayerX + 2), A
                RET

ArcadePlayer_SubX:
                LD   HL, (ArcadePlayerX)
                LD   DE, ARCADE_MOVE_X_Q8
                OR   A
                SBC  HL, DE
                LD   (ArcadePlayerX), HL
                LD   A, (ArcadePlayerX + 2)
                SBC  A, 0
                LD   (ArcadePlayerX + 2), A
                RET

ArcadePlayer_AddY:
                LD   HL, (ArcadePlayerY)
                LD   DE, ARCADE_MOVE_Y_Q8
                ADD  HL, DE
                LD   (ArcadePlayerY), HL
                LD   A, (ArcadePlayerY + 2)
                ADC  A, 0
                LD   (ArcadePlayerY + 2), A
                RET

ArcadePlayer_SubY:
                LD   HL, (ArcadePlayerY)
                LD   DE, ARCADE_MOVE_Y_Q8
                OR   A
                SBC  HL, DE
                LD   (ArcadePlayerY), HL
                LD   A, (ArcadePlayerY + 2)
                SBC  A, 0
                LD   (ArcadePlayerY + 2), A
                RET

; Kempston Mouse задаёт относительное логическое движение. Первый отсчёт только
; включает слежение; скачки вне -63..+63 отбрасываются, как во входе HMM2.
ArcadePlayer_Mouse:
                LD   HL, (Input.Mouse.PositionX)
                LD   DE, (ArcadeMousePrevX)
                LD   (ArcadeMousePrevX), HL
                OR   A
                SBC  HL, DE
                LD   A, (ArcadeMouseValid)
                OR   A
                JR   Z, .sampleY
                LD   IX, ArcadePlayerX + 1
                CALL ArcadePlayer_ApplyMouseDelta
.sampleY:
                LD   HL, (Input.Mouse.PositionY)
                LD   DE, (ArcadeMousePrevY)
                LD   (ArcadeMousePrevY), HL
                OR   A
                SBC  HL, DE
                LD   A, (ArcadeMouseValid)
                OR   A
                JR   Z, .arm
                LD   IX, ArcadePlayerY + 1
                CALL ArcadePlayer_ApplyMouseDelta
                RET
.arm:           LD   A, 1
                LD   (ArcadeMouseValid), A
                RET

; HL = знаковое логическое смещение, IX = слово целой части позиции Q16.8.
ArcadePlayer_ApplyMouseDelta:
                LD   A, H
                OR   A
                JR   Z, .positive
                CP   #FF
                RET  NZ
                LD   A, L
                CP   256 - ARCADE_MOUSE_DELTA_MAX
                RET  C
                JR   .apply
.positive:      LD   A, L
                CP   ARCADE_MOUSE_DELTA_MAX + 1
                RET  NC
                ; Чувствительность мыши ×2 относительно TSLib: удваиваем
                ; принятую (после отсечки) дельту перед сложением с позицией.
                ; ADD HL,HL — корректный знаковый сдвиг влево для дополнения до двух.
.apply:         ADD  HL, HL
                LD   E, (IX + 0)
                LD   D, (IX + 1)
                ADD  HL, DE
                LD   (IX + 0), L
                LD   (IX + 1), H
                RET

ArcadePlayer_Clamp:
                LD   HL, ArcadePlayerX
                LD   DE, ARCADE_PLAYER_MAX_X
                CALL ArcadePlayer_ClampAxis
                LD   HL, ArcadePlayerY
                LD   DE, ARCADE_PLAYER_MAX_Y
                JP   ArcadePlayer_ClampAxis

; HL указывает на позицию Q16.8, DE = максимальная целая координата.
ArcadePlayer_ClampAxis:
                PUSH HL
                INC  HL
                INC  HL
                BIT  7, (HL)
                POP  HL
                JR   NZ, .zero
                PUSH HL
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                POP  HL
                PUSH HL
                LD   H, B
                LD   L, C
                OR   A
                SBC  HL, DE
                POP  HL
                RET  C
                JR   NZ, .maximum
                LD   A, (HL)                     ; на максимуме дробная часть равна нулю
                OR   A
                RET  Z
.maximum:      XOR  A
                LD   (HL), A
                INC  HL
                LD   (HL), E
                INC  HL
                LD   (HL), D
                RET
.zero:          XOR  A
                LD   (HL), A
                INC  HL
                LD   (HL), A
                INC  HL
                LD   (HL), A
                RET

; Глобальный ПКМ/AltGr работает по фронту. Сам Force больше не переключается
; булевым флагом: полный автомат `$24CE…$2CE4` исполняется из code-bank #E6.
ArcadeForce_Update:
                XOR  A
                LD   (ArcadeForceActionEdge), A
                LD   A, (InputState)
                AND  INPUT_RELEASE
                LD   B, A
                LD   A, (ArcadeReleasePrev)
                OR   A
                JR   NZ, .remember
                LD   A, B
                OR   A
                JR   Z, .remember
                LD   A, 1
                LD   (ArcadeForceActionEdge), A
.remember:      LD   A, B
                LD   (ArcadeReleasePrev), A
                LD   A, RTYPE_FIXED_PLAYER_BANK_PAGE
                SetPage2_A
                CALL RTypeFixedPlayerBank_Update
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Начальная очистка и шестнадцать исходных history-пар также живут в bank #E6.
ArcadeFixedPlayer_Init:
                LD   A, RTYPE_FIXED_PLAYER_BANK_PAGE
                SetPage2_A
                CALL RTypeFixedPlayerBank_Init
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Wave Cannon хранит буквальный счётчик player+$1D: по два за VBlank до `$80`.
; На отпускании `$23EA/$188C` превращают его в силу 0/4/8/12/16/20.
ArcadeWave_Update:
                XOR  A
                LD   (ArcadeWaveShotPending), A
                LD   A, (InputState)
                AND  INPUT_FIRE
                JR   Z, .released
                LD   A, (ArcadeFireHeld)
                OR   A
                JR   NZ, .charge
                LD   A, 1
                LD   (ArcadeFireHeld), A
                CALL ArcadeShot_Spawn
.charge:
                LD   A, (ArcadeWaveCharge)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPEPYADVANCEWAVECHARGE_ADDRESS
                ADD  HL, DE
                LD   A, RTYPEPYADVANCEWAVECHARGE_PAGE
                SetPage3_A
                LD   A, (HL)
                LD   (ArcadeWaveCharge), A
                RET
.released:      LD   A, (ArcadeFireHeld)
                OR   A
                RET  Z
                XOR  A
                LD   (ArcadeFireHeld), A
                LD   A, (ArcadeWaveCharge)
                LD   B, A
                XOR  A
                LD   (ArcadeWaveCharge), A
                LD   A, B
                LD   E, A
                LD   D, 0
                LD   HL, RTYPEPYWAVEPOWER_ADDRESS
                ADD  HL, DE
                LD   A, RTYPEPYWAVEPOWER_PAGE
                SetPage3_A
                LD   A, (HL)
                OR   A
                RET  Z
                LD   (ArcadeWaveShotPower), A
                LD   A, 1
                LD   (ArcadeWaveShotPending), A
                JP   ArcadeWaveProjectile_Spawn

; Создать одну из трёх fixed-записей `$04D6`. Один WAIT-pass воспроизводит
; pending `$4ED8`: новый объект не движется и не сталкивается в кадре FIRE,
; а на следующем VBlank уже входит в первый `$4F40`.
ArcadeShot_Spawn:
                LD   IX, ArcadeShotTable
                LD   B, ARCADE_SHOT_COUNT
.find:          LD   A, (IX + ARCADE_SHOT_ACTIVE)
                OR   A
                JR   Z, .found
                LD   DE, ARCADE_SHOT_REC_SIZE
                ADD  IX, DE
                DJNZ .find
                RET                              ; все слоты подлинных выстрелов заняты
.found:         LD   (IX + ARCADE_SHOT_ACTIVE), ARCADE_SHOT_WAIT
                LD   (IX + ARCADE_SHOT_TIMER), 1
                XOR  A
                LD   (IX + ARCADE_SHOT_IMPACT), A
                LD   A, 1                        ; фронт для General Sound
                LD   (ArcadeShotPending), A
                LD   HL, (RTypePlayerNativeX)
                LD   DE, 8
                ADD  HL, DE
                LD   (IX + ARCADE_SHOT_X), L
                LD   (IX + ARCADE_SHOT_X + 1), H
                LD   HL, (RTypePlayerNativeY)
                LD   (IX + ARCADE_SHOT_Y), L
                LD   (IX + ARCADE_SHOT_Y + 1), H
                LD   HL, (ArcadePlayerY + 1)
                LD   DE, 12
                ADD  HL, DE
                LD   (IX + ARCADE_SHOT_LOGICAL_Y), L
                LD   (IX + ARCADE_SHOT_LOGICAL_Y + 1), H
                RET

; `$4F40` делает два шага по восемь нативных пикселей. После enemy hit байт
; collision уже очищен: следующий pass всё ещё движется, отступает на 8 и
; проигрывает три terminal-фазы `$3D17` в том же fixed slot.
ArcadeShots_Update:
                LD   IX, ArcadeShotTable
                LD   B, ARCADE_SHOT_COUNT
.loop:          LD   A, (IX + ARCADE_SHOT_ACTIVE)
                OR   A
                JR   Z, .next
                CP   ARCADE_SHOT_WAIT
                JR   NZ, .notWait
                DEC  (IX + ARCADE_SHOT_TIMER)
                JR   NZ, .next
                LD   (IX + ARCADE_SHOT_ACTIVE), ARCADE_SHOT_FLIGHT
                JR   .move
.notWait:       CP   ARCADE_SHOT_TERMINAL
                JR   NZ, .move
                DEC  (IX + ARCADE_SHOT_TIMER)
                JR   NZ, .next
                JR   .remove
.move:          LD   L, (IX + ARCADE_SHOT_X)
                LD   H, (IX + ARCADE_SHOT_X + 1)
                LD   DE, 16
                ADD  HL, DE
                LD   A, (IX + ARCADE_SHOT_ACTIVE)
                CP   ARCADE_SHOT_SPENT
                JR   NZ, .storeMove
                LD   DE, -8
                ADD  HL, DE
                LD   (IX + ARCADE_SHOT_ACTIVE), ARCADE_SHOT_TERMINAL
                LD   (IX + ARCADE_SHOT_TIMER), 3
.storeMove:     LD   (IX + ARCADE_SHOT_X), L
                LD   (IX + ARCADE_SHOT_X + 1), H
                LD   DE, #02B8
                OR   A
                SBC  HL, DE
                JR   C, .next
.remove:        XOR  A
                LD   (IX + ARCADE_SHOT_ACTIVE), A
.next:          LD   DE, ARCADE_SHOT_REC_SIZE
                ADD  IX, DE
                DJNZ .loop
                RET

; Wave и ordinary shot используют одинаковый начальный native anchor `R-9+8`.
; Сила уже классифицирована `$23EA`, первая подвижная фаза — после delay=2.
ArcadeWaveProjectile_Spawn:
                LD   A, 1
                LD   (ArcadeWaveActive), A
                LD   A, M72_R9_WAVE_DELAY
                LD   (ArcadeWaveDelay), A
                XOR  A
                LD   (ArcadeWaveAnim), A

                LD   HL, (RTypePlayerNativeX)
                LD   DE, 8
                ADD  HL, DE
                LD   (ArcadeWaveX), HL
                LD   (ArcadeWaveReleaseX), HL
                LD   HL, (RTypePlayerNativeY)
                LD   (ArcadeWaveY), HL
                LD   (ArcadeWaveReleaseY), HL
                LD   HL, (ArcadePlayerY + 1)
                LD   DE, 3
                ADD  HL, DE
                LD   (ArcadeWaveLogicalY), HL
                RET

; После задержки Wave движется на 8 нативных пикселей M72 за кадр.
; Каждая из двух подлинных графических фаз держится два игровых кадра.
ArcadeWaveProjectile_Update:
                LD   A, (ArcadeWaveActive)
                OR   A
                RET  Z
                LD   A, (ArcadeWaveShotPower)
                OR   A
                JR   Z, .remove                  ; `$31E3`: нулевая сила гаснет
                LD   A, (ArcadeWaveDelay)
                OR   A
                JR   Z, .move
                DEC  A
                LD   (ArcadeWaveDelay), A
                RET
.move:          LD   A, (ArcadeWaveAnim)
                INC  A
                LD   (ArcadeWaveAnim), A
                LD   HL, (ArcadeWaveX)
                LD   DE, 8
                ADD  HL, DE
                LD   (ArcadeWaveX), HL
                LD   DE, #02C8                   ; logical top-left X < 640
                OR   A
                SBC  HL, DE
                RET  C
.remove:        XOR  A
                LD   (ArcadeWaveActive), A
                RET
